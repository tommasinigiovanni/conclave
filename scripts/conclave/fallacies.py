"""Fallacy detection — analyze LLM responses for logical fallacies."""

import asyncio
import json
import re
import sys
from typing import Optional

FALLACIES = {
    "ad_hominem": "Attacks the person rather than the argument",
    "straw_man": "Misrepresents opponent's position to attack it",
    "false_dichotomy": "Presents only two options when more exist",
    "appeal_to_authority": "Uses authority as evidence without supporting logic",
    "slippery_slope": "Assumes one event will lead to extreme consequences",
    "circular_reasoning": "Uses conclusion as premise",
    "hasty_generalization": "Draws broad conclusions from limited examples",
    "appeal_to_emotion": "Uses emotions instead of logic",
    "false_equivalence": "Treats fundamentally different things as equal",
    "post_hoc": "Assumes correlation implies causation",
    "bandwagon": "Argues something is true because many believe it",
    "appeal_to_ignorance": "Claims something is true because it hasn't been disproven",
}

_VALID_SEVERITIES = {"high", "medium", "low"}

_FALLACY_PROMPT_TEMPLATE = """\
You are a critical thinking expert. Analyze the following response for \
logical fallacies. Be precise and conservative — only flag clear fallacies, \
not weak arguments.

For each fallacy found, respond ONLY with a JSON array:
[
  {{
    "type": "false_dichotomy",
    "severity": "high|medium|low",
    "quote": "exact quote from the text (max 20 words)",
    "explanation": "why this is a fallacy (1 sentence)"
  }}
]

If no fallacies are found, respond with: []

Do not include any text outside the JSON array.

Response to analyze:
{response_text}"""

# Regex for extracting JSON arrays from LLM responses
_FENCED_JSON_RE = re.compile(r'```(?:json)?\s*\n?(.*?)```', re.DOTALL)
_BARE_ARRAY_RE = re.compile(r'\[.*\]', re.DOTALL)


def _parse_fallacy_response(text: str) -> list[dict]:
    """Extract and validate fallacy list from LLM response."""
    # Strategy 1: fenced ```json block
    for m in _FENCED_JSON_RE.finditer(text):
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, list):
                return _validate_items(obj)
        except (json.JSONDecodeError, ValueError):
            continue

    # Strategy 2: bare JSON array
    match = _BARE_ARRAY_RE.search(text)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, list):
                return _validate_items(obj)
        except (json.JSONDecodeError, ValueError):
            pass

    return []


def _truncate_quote(quote: str, max_words: int = 20) -> str:
    """Truncate quote to max_words words."""
    words = quote.split()
    if len(words) <= max_words:
        return quote
    return " ".join(words[:max_words]) + "..."


def _validate_items(items: list) -> list[dict]:
    """Validate and filter fallacy items."""
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ftype = item.get("type")
        severity = item.get("severity")
        quote = item.get("quote")
        explanation = item.get("explanation")
        if not all(isinstance(v, str) for v in (ftype, severity, quote, explanation)):
            continue
        if ftype not in FALLACIES:
            continue
        if severity not in _VALID_SEVERITIES:
            continue
        valid.append({
            "type": ftype,
            "severity": severity,
            "quote": _truncate_quote(quote),
            "explanation": explanation,
        })
    return valid


async def detect_fallacies(
    response_text: str,
    analyzer_member: dict,
    config: dict,
    *,
    client=None,
    _call_model=None,
) -> list[dict]:
    """Detect fallacies in a single response using the analyzer model.

    Returns list of validated fallacy dicts, or [] on any error.
    """
    if _call_model is None:
        from .providers import call_model
        _call_model = call_model

    prompt = _FALLACY_PROMPT_TEMPLATE.format(response_text=response_text)
    system = "You are a critical thinking and logic expert. Respond only with valid JSON."

    try:
        result = await _call_model(analyzer_member, prompt, system, config, client=client)
        if "error" in result or not result.get("content"):
            return []
        return _parse_fallacy_response(result["content"])
    except Exception as e:
        print(f"  [fallacy-detection] warning: {e}", file=sys.stderr)
        return []


def _pick_analyzer(members: list) -> dict:
    """Pick the best analyzer member — prefer local (free), else first available."""
    for m in members:
        if m.get("local", False):
            return m
    return members[0] if members else {}


async def detect_all_fallacies(
    phase1_results: list[dict],
    config: dict,
    *,
    client=None,
    _call_model=None,
) -> dict[str, list[dict]]:
    """Detect fallacies in all Phase 1 responses in parallel.

    Returns dict: member_key -> list of fallacies found.
    """
    members = config.get("council_members", [])
    analyzer = _pick_analyzer(members)
    if not analyzer:
        return {}

    ok_drafts = [d for d in phase1_results
                 if "error" not in d and d.get("content") and not d.get("needs_claude_code")]

    if not ok_drafts:
        return {}

    async def _detect_one(draft):
        fallacies = await detect_fallacies(
            draft["content"], analyzer, config,
            client=client, _call_model=_call_model)
        return draft["key"], fallacies

    results = await asyncio.gather(*[_detect_one(d) for d in ok_drafts])
    return dict(results)
