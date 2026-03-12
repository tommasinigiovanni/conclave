"""Quorum Voting — point-based voting instead of ordinal ranking."""

import json
import random
import re
import string

LETTERS = list(string.ascii_uppercase)

# ── JSON extraction patterns ──
_FENCED_JSON_RE = re.compile(r'```json\s*\n(.*?)```', re.DOTALL)
_BARE_JSON_RE = re.compile(r'\{[^{}]*"Response[^{}]*\}', re.DOTALL)


def build_vote_prompt(original_prompt: str, drafts: list, exclude_key: str,
                      anonymize: bool) -> tuple[str, dict]:
    """Build a voting prompt for one model. Returns (prompt_text, letter_map)."""
    others = [d for d in drafts if d["key"] != exclude_key and "error" not in d]
    if anonymize:
        random.shuffle(others)

    letter_map = {}
    sections = []
    for i, d in enumerate(others):
        letter = LETTERS[i]
        letter_map[letter] = d["key"]
        sections.append(f"### Response {letter}\n{d['content']}")

    responses_text = "\n\n---\n\n".join(sections)
    labels = ", ".join(f'"Response {l}"' for l in sorted(letter_map.keys()))

    prompt_text = (
        f"## Original Question\n{original_prompt}\n\n"
        f"## Council Responses\n\n{responses_text}\n\n---\n\n"
        "You have read the responses above. Distribute exactly 100 points among them "
        "to reflect their relative quality. Respond ONLY with JSON:\n"
        f'{{{labels.replace(chr(34)+"Response", " "+chr(34)+"Response")}}}\n\n'
        "Example format:\n"
        f'{{{", ".join(f"{chr(34)}Response {l}{chr(34)}: {100 // len(letter_map)}" for l in sorted(letter_map.keys()))}}}\n\n'
        "Points must sum to exactly 100. Respond with ONLY the JSON object, nothing else."
    )
    return prompt_text, letter_map


def parse_vote_response(text: str, valid_letters: set[str]) -> dict[str, int] | None:
    """Extract vote JSON from model response. Returns {letter: points} or None."""
    # Strategy 1: fenced ```json block
    for m in _FENCED_JSON_RE.finditer(text):
        result = _try_parse_votes(m.group(1).strip(), valid_letters)
        if result is not None:
            return result

    # Strategy 2: bare JSON object
    # Try to find any JSON-like object in the text
    for m in re.finditer(r'\{[^{}]+\}', text):
        result = _try_parse_votes(m.group(0), valid_letters)
        if result is not None:
            return result

    return None


def _try_parse_votes(json_str: str, valid_letters: set[str]) -> dict[str, int] | None:
    """Try to parse a JSON string as a vote dict."""
    try:
        obj = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(obj, dict):
        return None

    # Normalize keys: "Response A" → "A", "A" → "A"
    votes: dict[str, int] = {}
    for key, val in obj.items():
        letter = key.strip().upper()
        if letter.startswith("RESPONSE "):
            letter = letter[len("RESPONSE "):]
        letter = letter.strip()

        if letter not in valid_letters:
            return None
        if not isinstance(val, (int, float)):
            return None
        votes[letter] = int(round(val))

    # Must cover all valid letters
    if set(votes.keys()) != valid_letters:
        return None

    # Points must sum to ~100 (allow small tolerance for rounding)
    total = sum(votes.values())
    if abs(total - 100) > 5:
        return None

    # Normalize to exactly 100
    if total != 100:
        votes = _normalize_to_100(votes)

    return votes


def _normalize_to_100(votes: dict[str, int]) -> dict[str, int]:
    """Adjust vote points to sum to exactly 100."""
    total = sum(votes.values())
    if total == 0:
        n = len(votes)
        return {k: 100 // n + (1 if i < 100 % n else 0)
                for i, k in enumerate(votes)}

    # Scale proportionally
    scaled = {k: int(v * 100 / total) for k, v in votes.items()}
    diff = 100 - sum(scaled.values())
    # Add remainder to highest-voted
    if diff != 0:
        top_key = max(scaled, key=scaled.get)
        scaled[top_key] += diff
    return scaled


def aggregate_votes(vote_results: list[dict]) -> dict:
    """Aggregate vote results from all models.

    Each entry: {"key": model_key, "votes": {letter: points}, "letter_map": {letter: key}}

    Returns:
        {
            "weighted_scores": {model_key: total_points},
            "consensus_strength": float (0-1),
            "per_model_votes": {voter_key: {voted_key: points}},
        }
    """
    scores: dict[str, int] = {}
    per_model: dict[str, dict[str, int]] = {}

    for vr in vote_results:
        if "error" in vr or "votes" not in vr or vr["votes"] is None:
            continue
        voter_key = vr["key"]
        letter_map = vr.get("letter_map", {})
        votes = vr["votes"]

        voter_votes: dict[str, int] = {}
        for letter, points in votes.items():
            model_key = letter_map.get(letter, letter)
            scores[model_key] = scores.get(model_key, 0) + points
            voter_votes[model_key] = points
        per_model[voter_key] = voter_votes

    # Sort by score descending
    weighted_scores = dict(sorted(scores.items(), key=lambda x: -x[1]))

    # Consensus strength: average percentage given to the winner
    consensus = 0.0
    if weighted_scores and per_model:
        winner = next(iter(weighted_scores))
        winner_pcts = []
        for voter_key, voter_votes in per_model.items():
            if winner in voter_votes:
                winner_pcts.append(voter_votes[winner] / 100.0)
        if winner_pcts:
            consensus = sum(winner_pcts) / len(winner_pcts)

    return {
        "weighted_scores": weighted_scores,
        "consensus_strength": round(consensus, 3),
        "per_model_votes": per_model,
    }


def votes_to_ranking_fallback(vote_results: list[dict]) -> list[dict]:
    """Convert vote results to ordinal ranking format for fallback compatibility."""
    agg = aggregate_votes(vote_results)
    scores = agg["weighted_scores"]
    # Create a sorted list from highest to lowest score
    ranking = sorted(scores.keys(), key=lambda k: -scores[k])
    return ranking
