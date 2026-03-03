"""Orchestrator — phases, health check, and main run_conclave entry."""

import asyncio
import time
from typing import Optional

import httpx

from .config import load_config, load_templates
from .progress import _Progress
from .providers import call_model
from .ranking import (
    aggregate_rankings, build_critique_prompt, build_repair_prompt,
    parse_ranking, parse_ranking_json,
)
from .scoring import load_scores, record_round, save_scores
from .sessions import _SessionStore, _build_context_prompt, _record_turn


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
    async def _call_and_report(m):
        result = await call_model(m, prompt, system, cfg, client=client)
        result["key"] = m["key"]
        result["label"] = m["label"]
        result["icon"] = m.get("icon", "")
        progress.member_done(m, result)
        return result

    return list(await asyncio.gather(*[_call_and_report(m) for m in members]))


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


async def run_conclave(prompt: str, depth: str = "standard",
                       system: Optional[str] = None,
                       member_keys: Optional[list[str]] = None,
                       cfg: Optional[dict] = None,
                       quiet: bool = False,
                       session: Optional[dict] = None) -> dict:
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

        # ── Phase 2 (deep only) ──
        critiques = []
        rankings = {}
        phase2_pending = False
        # Need at least 2 members with content (API responses) for cross-critique
        if depth == "deep" and (api_ok_count + local_count) >= 2:
            if local_count > 0:
                phase2_pending = True  # defer to Pass 2
            else:
                progress.phase_start(2, "Anonymized cross-critique...")
                critiques = await phase2(effective_prompt, drafts, members, cfg, templates, progress, client=client)
                rankings = aggregate_rankings(critiques)

    # ── Update scoring ──
    _scores = load_scores()
    _scores = record_round(_scores, drafts, rankings,
                           alpha=cfg.get("defaults", {}).get("scoring_ema_alpha", 0.3))
    save_scores(_scores)

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
        "member_scores": _scores.get("members", {}),
        "summary": {
            "models_queried": len(drafts),
            "api_calls": api_ok_count,
            "local": local_count,
            "failed": fail_count,
            "critiques": len([c for c in critiques if "error" not in c]),
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
