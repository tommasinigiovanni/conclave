"""Ranking extraction, aggregation, and critique prompt building."""

import random
import re
import string

LETTERS = list(string.ascii_uppercase)  # A, B, C, ...


def build_critique_prompt(original_prompt: str, drafts: list, exclude_key: str,
                          anonymize: bool, templates: dict) -> tuple[str, dict]:
    """Build critique prompt. Returns (prompt_text, letter_to_key_map)."""
    others = [d for d in drafts if d["key"] != exclude_key and "error" not in d]
    if anonymize:
        random.shuffle(others)  # randomize order to prevent position bias

    letter_map = {}
    sections = []
    for i, d in enumerate(others):
        letter = LETTERS[i]
        letter_map[letter] = d["key"]
        sections.append(f"### Response {letter}\n{d['content']}")

    responses_text = "\n\n---\n\n".join(sections)

    tmpl = templates.get("critique_prompt", "{original_prompt}\n\n{anonymized_responses}")
    prompt_text = tmpl.format(
        original_prompt=original_prompt,
        anonymized_responses=responses_text,
    )
    return prompt_text, letter_map


# ── Compiled patterns for ranking extraction ──

# Flexible header: "FINAL RANKING", "Ranking:", "## Final Ranking", "My ranking:" …
_RANKING_HEADER_RE = re.compile(
    r'^[#\s]*\**\s*(?:final\s+)?ranking[:\-—.\s*]*$',
    re.IGNORECASE | re.MULTILINE,
)

# Numbered item: "1. Response A …", "2) **B** - reason", "1: A", "1- A" …
_NUMBERED_ITEM_RE = re.compile(
    r'^\s*\d+[.):\-]\s*'       # "1. " / "1) " / "1: " / "1- "
    r'[\[(*]*\s*\**\s*'        # optional [, (, *, **
    r'(?:[Rr]esponse\s+)?'     # optional "Response "
    r'\**\s*'                   # optional closing bold before letter
    r'([A-Z])\b',              # THE LETTER
    re.MULTILINE,
)

# Single uppercase letter (word-boundary isolated) — used for inline / standalone
_SINGLE_LETTER_RE = re.compile(r'\b([A-Z])\b')

# Standalone letter on its own line: "A", "**B**", "[C]", "(A)"
_STANDALONE_LETTER_RE = re.compile(
    r'^\s*[\[(*]*\**([A-Z])\**[\])*]*\s*$',
    re.MULTILINE,
)


def _dedup(seq: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_ranking(text: str) -> list[str]:
    """Extract FINAL RANKING from critique text.  Returns list of response letters.

    Handles common LLM output variations with layered strategies:
      Numbered:   "1. Response A", "2. B", "1. **A** - reason", "1) A"
      Inline:     "A > B > C"  /  "A → B → C"
      Comma:      "A, B, C"
      Standalone: lines containing just "A", "**B**", "[C]"
    """
    # ── Locate the ranking section ──
    header = _RANKING_HEADER_RE.search(text)
    if not header:
        return []

    section = text[header.end():]
    # Cap to ~20 lines to avoid false positives from subsequent prose
    lines = section.strip().split("\n")[:20]
    section_text = "\n".join(lines)

    # ── Strategy 1: numbered list ──
    found = _NUMBERED_ITEM_RE.findall(section_text)
    if found:
        return _dedup(found)

    # ── Strategy 2: inline arrows  ("A > B > C", "A → B → C", "A >> B >> C") ──
    for line in lines[:5]:
        if re.search(r'[>→≫»]', line):
            letters = _SINGLE_LETTER_RE.findall(line)
            if len(letters) >= 2:
                return _dedup(letters)

    # ── Strategy 3: comma-separated  ("A, B, C") ──
    for line in lines[:5]:
        stripped = line.strip()
        if ',' in stripped and len(stripped) < 80:
            letters = _SINGLE_LETTER_RE.findall(stripped)
            if len(letters) >= 2:
                return _dedup(letters)

    # ── Strategy 4: standalone letters on their own lines ──
    first_para = section_text.split("\n\n")[0]
    found = _STANDALONE_LETTER_RE.findall(first_para)
    if len(found) >= 2:
        return _dedup(found)

    return []


def aggregate_rankings(critiques: list) -> dict:
    """Compute average rank per model from all critiques."""
    scores: dict[str, list[float]] = {}
    for c in critiques:
        if "error" in c or "ranking" not in c:
            continue
        letter_map = c.get("letter_map", {})
        for position, letter in enumerate(c["ranking"]):
            model_key = letter_map.get(letter, letter)
            if model_key not in scores:
                scores[model_key] = []
            scores[model_key].append(position + 1)  # 1-indexed

    averages = {}
    for key, positions in scores.items():
        averages[key] = round(sum(positions) / len(positions), 2)
    return dict(sorted(averages.items(), key=lambda x: x[1]))
