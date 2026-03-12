"""Multi-round dialogue — iterative refinement after Phase 1."""

import asyncio
import os
import re
from typing import Optional

from .config import _load_env_file, _env


# ── Response prefix detection ──
_CONVERGE_RE = re.compile(r'^\s*CONVERGE:', re.IGNORECASE)
_MAINTAIN_RE = re.compile(r'^\s*MAINTAIN:', re.IGNORECASE)
_UPDATE_RE = re.compile(r'^\s*UPDATE:', re.IGNORECASE)


def get_max_rounds(cfg: dict | None = None) -> int:
    """Get hard cap for rounds from env config."""
    env_file = _load_env_file()
    val = _env("CONCLAVE_MAX_ROUNDS", env_file, "3")
    try:
        return max(1, int(val))
    except ValueError:
        return 3


def get_convergence_threshold() -> float:
    """Get convergence threshold from env config."""
    env_file = _load_env_file()
    val = _env("CONCLAVE_CONVERGENCE_THRESHOLD", env_file, "0.85")
    try:
        return float(val)
    except ValueError:
        return 0.85


def detect_stance(text: str) -> str:
    """Detect whether a response starts with CONVERGE:, MAINTAIN:, or UPDATE:."""
    if _CONVERGE_RE.match(text):
        return "converge"
    if _MAINTAIN_RE.match(text):
        return "maintain"
    if _UPDATE_RE.match(text):
        return "update"
    return "unknown"


def build_round_prompt(original_answer: str, critiques_received: list[str],
                       round_num: int) -> str:
    """Build the prompt for round 2+ of dialogue."""
    critiques_text = "\n\n---\n\n".join(
        f"Critique {i+1}:\n{c}" for i, c in enumerate(critiques_received)
    )
    return (
        f"In the previous round you answered:\n\n{original_answer}\n\n"
        f"Other models critiqued it as:\n\n{critiques_text}\n\n"
        "You may revise your position or defend it. "
        "If you substantially agree with the critiques, start your response with "
        "'CONVERGE:'. Otherwise start with 'MAINTAIN:' or 'UPDATE:'."
    )


def check_convergence(round_responses: list[dict]) -> bool:
    """Check if all models converged in this round."""
    ok_responses = [r for r in round_responses if "error" not in r and r.get("content")]
    if not ok_responses:
        return False
    return all(detect_stance(r["content"]) == "converge" for r in ok_responses)


def extract_critiques_for_model(critiques: list[dict], model_key: str) -> list[str]:
    """Extract critique text directed at a specific model from Phase 2 critiques."""
    result = []
    for c in critiques:
        if "error" in c or "content" not in c:
            continue
        # A critique is relevant if it reviewed this model's response
        letter_map = c.get("letter_map", {})
        # Check if this model's key appears in the letter_map values
        if model_key in letter_map.values():
            result.append(c["content"])
    return result


async def run_dialogue_rounds(
    original_prompt: str,
    drafts: list[dict],
    critiques: list[dict],
    members: list[dict],
    cfg: dict,
    call_model_fn,
    num_rounds: int,
    progress=None,
    *,
    client=None,
) -> dict:
    """Run multi-round dialogue after Phase 1 + Phase 2.

    Returns:
        {
            "rounds": [{"round": N, "responses": [...], "convergence": bool}],
            "converged_at": int | None,
            "total_rounds": int,
        }
    """
    max_rounds = get_max_rounds(cfg)
    actual_rounds = min(num_rounds, max_rounds)

    if actual_rounds <= 1:
        return {"rounds": [], "converged_at": None, "total_rounds": 1}

    system = "You are a member of an expert council engaged in a multi-round debate."
    rounds_data = []

    # Current answers = Phase 1 drafts
    current_answers = {d["key"]: d.get("content", "") for d in drafts if "error" not in d}
    current_critiques = critiques

    for round_num in range(2, actual_rounds + 1):
        if progress:
            progress._emit(f"  Round {round_num}/{actual_rounds} — Dialogue...")

        async def _call_for_round(member):
            key = member["key"]
            if key not in current_answers:
                return {"key": key, "error": "no prior answer", "round": round_num}

            if member.get("local", False):
                # Local members get a placeholder
                critique_texts = extract_critiques_for_model(current_critiques, key)
                prompt = build_round_prompt(current_answers[key], critique_texts, round_num)
                return {
                    "key": key, "label": member["label"], "icon": member.get("icon", ""),
                    "needs_claude_code": True, "prompt": prompt,
                    "round": round_num, "content": "", "elapsed": 0,
                }

            critique_texts = extract_critiques_for_model(current_critiques, key)
            if not critique_texts:
                # No critiques received — skip this round for this model
                return {
                    "key": key, "label": member["label"], "icon": member.get("icon", ""),
                    "content": current_answers[key], "stance": "maintain",
                    "round": round_num, "skipped": True, "elapsed": 0,
                }

            prompt = build_round_prompt(current_answers[key], critique_texts, round_num)
            result = await call_model_fn(member, prompt, system, cfg, client=client)
            result["key"] = key
            result["label"] = member["label"]
            result["icon"] = member.get("icon", "")
            result["round"] = round_num
            if "content" in result and "error" not in result:
                result["stance"] = detect_stance(result["content"])
            return result

        responses = list(await asyncio.gather(*[_call_for_round(m) for m in members]))

        converged = check_convergence(responses)
        rounds_data.append({
            "round": round_num,
            "responses": responses,
            "convergence": converged,
        })

        if converged:
            return {
                "rounds": rounds_data,
                "converged_at": round_num,
                "total_rounds": round_num,
            }

        # Update current answers for next round
        for r in responses:
            if "error" not in r and r.get("content") and not r.get("needs_claude_code"):
                current_answers[r["key"]] = r["content"]

        # Build fake critiques from this round's responses for next round
        # Each response's critique of others is implicit in their stance
        current_critiques = _responses_as_critiques(responses, drafts)

    return {
        "rounds": rounds_data,
        "converged_at": None,
        "total_rounds": actual_rounds,
    }


def _responses_as_critiques(responses: list[dict], drafts: list[dict]) -> list[dict]:
    """Convert round responses into critique-like dicts for the next round.

    Each response becomes a 'critique' that references all other models.
    """
    result = []
    ok_keys = [r["key"] for r in responses if "error" not in r and r.get("content")]
    for r in responses:
        if "error" in r or not r.get("content"):
            continue
        # Build a letter_map that maps other models to the reviewer
        letter_map = {}
        for i, key in enumerate([k for k in ok_keys if k != r["key"]]):
            from string import ascii_uppercase
            letter_map[ascii_uppercase[i]] = key
        result.append({
            "key": r["key"],
            "content": r["content"],
            "letter_map": letter_map,
        })
    return result
