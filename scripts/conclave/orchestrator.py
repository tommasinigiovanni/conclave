"""Orchestrator — phases, health check, and main run_conclave entry."""

import asyncio
import time
from typing import Optional

from .config import load_config, load_templates
from .progress import _Progress
from .providers import call_model
from .ranking import aggregate_rankings, build_critique_prompt, parse_ranking
from .sessions import _SessionStore, _build_context_prompt, _record_turn


async def doctor(cfg: dict) -> list[dict]:
    """Quick health check — send a tiny prompt to each model."""
    members = cfg.get("council_members", [])
    # Only test non-local members (local ones run in Claude Code)
    remote_members = [m for m in members if not m.get("local", False)]
    local_members = [m for m in members if m.get("local", False)]

    prompt = "Reply with exactly: OK"
    tasks = [call_model(m, prompt, None, cfg) for m in remote_members]
    results = await asyncio.gather(*tasks)
    report = []
    for m in local_members:
        report.append({"member": m["label"], "icon": m.get("icon", ""),
                        "status": "🏠 Local (Claude Code)"})
    for m, r in zip(remote_members, results):
        status = "❌ " + r.get("error", "unknown") if "error" in r else f"✅ {r['elapsed']}s"
        report.append({"member": m["label"], "icon": m.get("icon", ""), "status": status})
    return report


async def phase1(prompt: str, system: Optional[str], members: list, cfg: dict,
                  progress: _Progress) -> list:
    async def _call_and_report(m):
        result = await call_model(m, prompt, system, cfg)
        result["key"] = m["key"]
        result["label"] = m["label"]
        result["icon"] = m.get("icon", "")
        progress.member_done(m, result)
        return result

    return list(await asyncio.gather(*[_call_and_report(m) for m in members]))


async def phase2(original_prompt: str, drafts: list, members: list,
                 cfg: dict, templates: dict, progress: _Progress) -> list:
    """Anonymized cross-critique with ranking."""
    anonymize = cfg.get("anonymize_reviews", True)
    system = templates.get("critique_system", "You are a peer reviewer in an expert council.")

    ok_drafts = [d for d in drafts if "error" not in d]
    if len(ok_drafts) < 2:
        return []

    async def _critique_and_report(member, prompt_text, meta_info):
        result = await call_model(member, prompt_text, system, cfg)
        result.update(meta_info)
        if "error" not in result and "content" in result:
            result["ranking"] = parse_ranking(result["content"])
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
        effective_prompt = _build_context_prompt(session, prompt)
        progress._emit(f"  Session {session['id']} — turn {len(session['turns']) + 1}")

    progress.header(depth, len(members))

    # ── Phase 1 ──
    progress.phase_start(1, "Independent drafts...")
    drafts = await phase1(effective_prompt, system, members, cfg, progress)
    local_count = sum(1 for d in drafts if d.get("needs_claude_code", False))
    api_ok_count = sum(1 for d in drafts if "error" not in d and not d.get("needs_claude_code", False))
    fail_count = sum(1 for d in drafts if "error" in d)

    # ── Phase 2 (deep only) ──
    critiques = []
    rankings = {}
    # Need at least 2 members with content (API responses) for cross-critique
    if depth == "deep" and (api_ok_count + local_count) >= 2:
        progress.phase_start(2, "Anonymized cross-critique...")
        critiques = await phase2(effective_prompt, drafts, members, cfg, templates, progress)
        rankings = aggregate_rankings(critiques)

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
        "total_elapsed_seconds": total_elapsed,
        "phase1_drafts": drafts,
        "phase2_critiques": critiques,
        "aggregate_rankings": rankings,
        "summary": {
            "models_queried": len(drafts),
            "api_calls": api_ok_count,
            "local": local_count,
            "failed": fail_count,
            "critiques": len([c for c in critiques if "error" not in c]),
        },
    }
    return output
