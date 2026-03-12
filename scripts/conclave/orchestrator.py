"""Orchestrator — phases, health check, and main run_conclave entry."""

import asyncio
import time
from typing import Optional

import httpx

from .bias import record_dialogue_run, record_vote_run
from .config import load_config, load_templates
from .dialogue import run_dialogue_rounds
from .progress import _Progress
from .providers import call_model, stream_model
from .ranking import (
    aggregate_rankings, build_critique_prompt, build_repair_prompt,
    parse_ranking, parse_ranking_json,
)
from .scoring import load_scores, record_round, save_scores
from .sessions import _SessionStore, _build_context_prompt, _record_turn
from .voting import aggregate_votes, build_vote_prompt, parse_vote_response


async def doctor(cfg: dict) -> list[dict]:
    """Quick health check — send a tiny prompt to each model."""
    members = cfg.get("council_members", [])
    # Only test non-local members (local ones run in Claude Code)
    remote_members = [m for m in members if not m.get("local", False)]
    local_members = [m for m in members if m.get("local", False)]

    prompt = "Reply with exactly: OK"
    timeout = cfg.get("defaults", {}).get("timeout_seconds", 120)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [call_model(m, prompt, None, cfg, client=client) for m in remote_members]
        results = await asyncio.gather(*tasks)
    report = []
    for m in local_members:
        report.append({"member": m["label"], "icon": m.get("icon", ""),
                        "status": "🏠 Local (Claude Code)"})
    for m, r in zip(remote_members, results):
        if "error" in r:
            status = "❌ " + r.get("error", "unknown")
        elif r.get("fallback"):
            status = f"✅ {r['elapsed']}s (fallback → {r['model']})"
        else:
            status = f"✅ {r['elapsed']}s"
        report.append({"member": m["label"], "icon": m.get("icon", ""), "status": status})
    return report


async def phase1(prompt: str, system: Optional[str], members: list, cfg: dict,
                  progress: _Progress, *, client=None) -> list:
    use_stream = cfg.get("stream", True)
    sequential = cfg.get("stream_sequential", False)

    if not use_stream:
        return await _phase1_standard(prompt, system, members, cfg, progress, client=client)

    if sequential:
        return await _phase1_stream_sequential(prompt, system, members, cfg, progress, client=client)

    return await _phase1_stream_parallel(prompt, system, members, cfg, progress, client=client)


async def _phase1_standard(prompt: str, system: Optional[str], members: list,
                            cfg: dict, progress: _Progress, *, client=None) -> list:
    """Original non-streaming Phase 1."""
    async def _call_and_report(m):
        result = await call_model(m, prompt, system, cfg, client=client)
        result["key"] = m["key"]
        result["label"] = m["label"]
        result["icon"] = m.get("icon", "")
        progress.member_done(m, result)
        return result

    return list(await asyncio.gather(*[_call_and_report(m) for m in members]))


async def _phase1_stream_sequential(prompt: str, system: Optional[str],
                                     members: list, cfg: dict,
                                     progress: _Progress, *, client=None) -> list:
    """Stream one model at a time — tokens displayed live on stderr."""
    import time as _time
    results = []
    for m in members:
        if m.get("local", False):
            result = await call_model(m, prompt, system, cfg, client=client)
            result["key"] = m["key"]
            result["label"] = m["label"]
            result["icon"] = m.get("icon", "")
            progress.member_done(m, result)
            results.append(result)
            continue

        start = _time.time()
        try:
            gen = stream_model(m, prompt, system, cfg, client=client)
            text = await progress.stream_member_response(
                m["label"], m.get("icon", "⚪"), gen)
            elapsed = round(_time.time() - start, 2)
            result = {
                "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                "content": text, "tokens": None,
                "model": m.get("direct_model", ""), "elapsed": elapsed,
                "streamed": True,
            }
        except Exception as e:
            elapsed = round(_time.time() - start, 2)
            result = {
                "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                "error": str(e), "elapsed": elapsed,
            }
            progress.member_done(m, result)
        results.append(result)
    return results


async def _phase1_stream_parallel(prompt: str, system: Optional[str],
                                   members: list, cfg: dict,
                                   progress: _Progress, *, client=None) -> list:
    """Stream all models in parallel, buffer tokens, display in completion order."""
    import time as _time

    completion_queue: asyncio.Queue = asyncio.Queue()

    async def _stream_one(m):
        if m.get("local", False):
            result = await call_model(m, prompt, system, cfg, client=client)
            result["key"] = m["key"]
            result["label"] = m["label"]
            result["icon"] = m.get("icon", "")
            await completion_queue.put(result)
            return result

        start = _time.time()
        buf: list[str] = []
        try:
            async for token in stream_model(m, prompt, system, cfg, client=client):
                buf.append(token)
            elapsed = round(_time.time() - start, 2)
            text = "".join(buf)
            result = {
                "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                "content": text, "tokens": None,
                "model": m.get("direct_model", ""), "elapsed": elapsed,
                "streamed": True,
            }
        except Exception as e:
            elapsed = round(_time.time() - start, 2)
            text = "".join(buf)
            if text:
                result = {
                    "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                    "content": text, "tokens": None,
                    "model": m.get("direct_model", ""), "elapsed": elapsed,
                    "streamed": True, "stream_error": str(e),
                }
            else:
                result = {
                    "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                    "error": str(e), "elapsed": elapsed,
                }
        await completion_queue.put(result)
        return result

    # Launch all streams in parallel
    tasks = [asyncio.create_task(_stream_one(m)) for m in members]

    # Display results as they complete
    for _ in range(len(members)):
        result = await completion_queue.get()
        if "error" in result:
            progress.member_done(result, result)
        elif result.get("needs_claude_code"):
            progress.member_done(result, result)
        else:
            progress.stream_member_buffered(
                result["label"], result.get("icon", "⚪"),
                result.get("content", ""), result.get("elapsed", 0))

    # Collect all results in original member order
    return [await t for t in tasks]


async def phase2(original_prompt: str, drafts: list, members: list,
                 cfg: dict, templates: dict, progress: _Progress,
                 *, client=None) -> list:
    """Anonymized cross-critique with ranking."""
    anonymize = cfg.get("anonymize_reviews", True)
    system = templates.get("critique_system", "You are a peer reviewer in an expert council.")

    ok_drafts = [d for d in drafts if "error" not in d]
    if len(ok_drafts) < 2:
        return []

    async def _critique_and_report(member, prompt_text, meta_info):
        valid_letters = set(meta_info["letter_map"].keys())
        result = await call_model(member, prompt_text, system, cfg, client=client)
        result.update(meta_info)
        result["ranking_reprompted"] = False

        if "error" not in result and "content" in result:
            content = result["content"]

            # 1. Try JSON extraction on initial response
            ranking = parse_ranking_json(content, valid_letters)

            # 2. If empty: repair prompt → try JSON on repair response
            repair_text = ""
            if not ranking:
                repair_msg = build_repair_prompt(valid_letters)
                repair_result = await call_model(member, repair_msg, system, cfg, client=client)
                result["ranking_reprompted"] = True
                if "error" not in repair_result and "content" in repair_result:
                    repair_text = repair_result["content"]
                    ranking = parse_ranking_json(repair_text, valid_letters)

            # 3. If still empty: regex fallback on original, then repair
            if not ranking:
                ranking = parse_ranking(content)
            if not ranking and repair_text:
                ranking = parse_ranking(repair_text)

            result["ranking"] = ranking

        progress.member_done(meta_info, result)
        return result

    tasks = []
    for m in members:
        if any(d["key"] == m["key"] and "error" in d for d in drafts):
            continue
        prompt_text, letter_map = build_critique_prompt(
            original_prompt, drafts, m["key"], anonymize, templates)
        meta_info = {"key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                     "letter_map": letter_map}
        tasks.append(_critique_and_report(m, prompt_text, meta_info))

    return list(await asyncio.gather(*tasks))


async def phase2_vote(original_prompt: str, drafts: list, members: list,
                      cfg: dict, progress: _Progress,
                      *, client=None) -> list:
    """Point-based voting instead of ordinal ranking."""
    anonymize = cfg.get("anonymize_reviews", True)
    system = "You are a judge in an expert council. Score the responses fairly."

    ok_drafts = [d for d in drafts if "error" not in d]
    if len(ok_drafts) < 2:
        return []

    async def _vote_and_report(member, prompt_text, meta_info):
        valid_letters = set(meta_info["letter_map"].keys())
        result = await call_model(member, prompt_text, system, cfg, client=client)
        result.update(meta_info)

        if "error" not in result and "content" in result:
            votes = parse_vote_response(result["content"], valid_letters)
            result["votes"] = votes
        else:
            result["votes"] = None

        progress.member_done(meta_info, result)
        return result

    tasks = []
    for m in members:
        if any(d["key"] == m["key"] and "error" in d for d in drafts):
            continue
        if m.get("local", False):
            # Local members get a placeholder
            prompt_text, letter_map = build_vote_prompt(
                original_prompt, drafts, m["key"], anonymize)
            meta_info = {"key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                         "letter_map": letter_map, "needs_claude_code": True,
                         "prompt": prompt_text, "content": "", "elapsed": 0, "votes": None}
            tasks.append(asyncio.coroutine(lambda mi=meta_info: mi)()
                         if False else _make_local_vote(meta_info, progress))
            continue
        prompt_text, letter_map = build_vote_prompt(
            original_prompt, drafts, m["key"], anonymize)
        meta_info = {"key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                     "letter_map": letter_map}
        tasks.append(_vote_and_report(m, prompt_text, meta_info))

    return list(await asyncio.gather(*tasks))


async def _make_local_vote(meta_info, progress):
    """Return a local placeholder for voting."""
    progress.member_done(meta_info, meta_info)
    return meta_info


async def run_conclave(prompt: str, depth: str = "standard",
                       system: Optional[str] = None,
                       member_keys: Optional[list[str]] = None,
                       cfg: Optional[dict] = None,
                       quiet: bool = False,
                       session: Optional[dict] = None,
                       vote: bool = False,
                       rounds: Optional[int] = None) -> dict:
    cfg = cfg or load_config()
    templates = load_templates()
    progress = _Progress(quiet=quiet)
    store = _SessionStore()
    total_start = time.time()

    members = cfg.get("council_members", [])
    if member_keys:
        members = [m for m in members if m["key"] in member_keys]

    # ── Build context-enriched prompt if continuing a session ──
    effective_prompt = prompt
    if session and session.get("turns"):
        token_budget = cfg.get("defaults", {}).get("session_token_budget", 20000)
        effective_prompt = _build_context_prompt(session, prompt, token_budget)
        progress._emit(f"  Session {session['id']} — turn {len(session['turns']) + 1}")

    progress.header(depth, len(members))

    timeout = cfg.get("defaults", {}).get("timeout_seconds", 120)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # ── Phase 1 ──
        progress.phase_start(1, "Independent drafts...")
        drafts = await phase1(effective_prompt, system, members, cfg, progress, client=client)
        local_count = sum(1 for d in drafts if d.get("needs_claude_code", False))
        api_ok_count = sum(1 for d in drafts if "error" not in d and not d.get("needs_claude_code", False))
        fail_count = sum(1 for d in drafts if "error" in d)

        # ── Phase 2: vote mode OR deep critique ──
        critiques = []
        rankings = {}
        vote_results = []
        vote_aggregation = {}
        phase2_pending = False

        if vote and (api_ok_count + local_count) >= 2:
            # Voting mode
            if local_count > 0:
                phase2_pending = True
            else:
                progress.phase_start(2, "Quorum voting...")
                vote_results = await phase2_vote(effective_prompt, drafts, members, cfg, progress, client=client)
                vote_aggregation = aggregate_votes(vote_results)
        elif depth == "deep" and (api_ok_count + local_count) >= 2:
            # Standard deep critique
            if local_count > 0:
                phase2_pending = True
            else:
                progress.phase_start(2, "Anonymized cross-critique...")
                critiques = await phase2(effective_prompt, drafts, members, cfg, templates, progress, client=client)
                rankings = aggregate_rankings(critiques)

        # ── Multi-round dialogue ──
        dialogue_data = {}
        if rounds and rounds > 1 and not phase2_pending and (critiques or vote_results):
            dialogue_data = await run_dialogue_rounds(
                effective_prompt, drafts, critiques or vote_results,
                members, cfg, call_model, rounds, progress, client=client)

    # ── Update scoring ──
    _scores = load_scores()
    _scores = record_round(_scores, drafts, rankings,
                           alpha=cfg.get("defaults", {}).get("scoring_ema_alpha", 0.3))
    save_scores(_scores)

    # ── Record bias data ──
    if vote and vote_aggregation:
        record_vote_run(
            prompt, "vote",
            vote_aggregation.get("per_model_votes", {}),
            vote_aggregation.get("consensus_strength", 0),
        )
    if rounds and rounds > 1 and dialogue_data:
        record_dialogue_run(
            prompt, dialogue_data.get("total_rounds", 1),
            dialogue_data.get("converged_at"),
            vote_aggregation.get("consensus_strength", 0) if vote_aggregation else 0,
        )

    # ── Save turn to session ──
    session_id = None
    if session is not None:
        _record_turn(session, prompt, depth, drafts)
        store.save(session)
        session_id = session["id"]

    total_elapsed = round(time.time() - total_start, 2)
    progress.done(total_elapsed)

    output = {
        "prompt": prompt,
        "system": system,
        "depth": depth,
        "session_id": session_id,
        "phase2_pending": phase2_pending,
        "effective_prompt": effective_prompt if phase2_pending else None,
        "total_elapsed_seconds": total_elapsed,
        "phase1_drafts": drafts,
        "phase2_critiques": critiques,
        "aggregate_rankings": rankings,
        "vote_results": vote_results,
        "vote_aggregation": vote_aggregation,
        "dialogue": dialogue_data,
        "member_scores": _scores.get("members", {}),
        "summary": {
            "models_queried": len(drafts),
            "api_calls": api_ok_count,
            "local": local_count,
            "failed": fail_count,
            "critiques": len([c for c in critiques if "error" not in c]),
            "vote_count": len([v for v in vote_results if v.get("votes")]),
            "dialogue_rounds": dialogue_data.get("total_rounds", 0) if dialogue_data else 0,
            "converged_at": dialogue_data.get("converged_at") if dialogue_data else None,
        },
    }
    return output


async def run_phase2_only(phase1_data: dict,
                          cfg: Optional[dict] = None,
                          quiet: bool = False) -> dict:
    """Run Phase 2 only, using completed Phase 1 data with local drafts filled in.

    Accepts the Phase 1 JSON (with local drafts' content populated),
    runs cross-critique, updates scoring (rankings only), and returns
    the complete output.
    """
    cfg = cfg or load_config()
    templates = load_templates()
    progress = _Progress(quiet=quiet)
    total_start = time.time()

    effective_prompt = phase1_data.get("effective_prompt")
    drafts = phase1_data.get("phase1_drafts", [])

    if not effective_prompt:
        return {"error": "Missing effective_prompt in phase1_data"}

    # Reconstruct members list by matching draft keys against config
    cfg_members = {m["key"]: m for m in cfg.get("council_members", [])}
    members = [cfg_members[d["key"]] for d in drafts if d["key"] in cfg_members]

    # Validate: need ≥2 non-error drafts with content
    ok_drafts = [d for d in drafts
                 if "error" not in d and d.get("content")]
    if len(ok_drafts) < 2:
        return {"error": f"Need ≥2 non-error drafts with content, got {len(ok_drafts)}"}

    timeout = cfg.get("defaults", {}).get("timeout_seconds", 120)
    async with httpx.AsyncClient(timeout=timeout) as client:
        progress.phase_start(2, "Anonymized cross-critique...")
        critiques = await phase2(effective_prompt, drafts, members, cfg,
                                 templates, progress, client=client)
        rankings = aggregate_rankings(critiques)

    # Update scoring — empty drafts list = no double-counting participations,
    # only ranking fields updated
    _scores = load_scores()
    _scores = record_round(_scores, [], rankings,
                           alpha=cfg.get("defaults", {}).get("scoring_ema_alpha", 0.3))
    save_scores(_scores)

    total_elapsed = round(time.time() - total_start, 2)
    progress.done(total_elapsed)

    return {
        "prompt": phase1_data.get("prompt"),
        "system": phase1_data.get("system"),
        "depth": "deep",
        "session_id": phase1_data.get("session_id"),
        "phase2_pending": False,
        "effective_prompt": None,
        "total_elapsed_seconds": total_elapsed,
        "phase1_drafts": drafts,
        "phase2_critiques": critiques,
        "aggregate_rankings": rankings,
        "member_scores": _scores.get("members", {}),
        "summary": {
            "models_queried": len(drafts),
            "api_calls": sum(1 for d in drafts
                             if "error" not in d
                             and not d.get("needs_claude_code", False)),
            "local": sum(1 for d in drafts
                         if d.get("needs_claude_code", False)),
            "failed": sum(1 for d in drafts if "error" in d),
            "critiques": len([c for c in critiques if "error" not in c]),
        },
    }
