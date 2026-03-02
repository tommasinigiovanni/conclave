"""Session store — multi-turn conversation memory."""

import json
import random
import string
from datetime import datetime, timezone
from pathlib import Path

_SESSIONS_DIR = Path.home() / ".config" / "conclave" / "sessions"
_SUMMARY_MAX_CHARS = 300
_DEFAULT_TOKEN_BUDGET = 20000  # max tokens for session context (prior turns)
_CHARS_PER_TOKEN = 4  # approximate, same heuristic as cost.py


class _SessionStore:
    """Manages JSON session files for multi-turn conversations."""

    def __init__(self):
        self._dir = _SESSIONS_DIR

    def _ensure_dir(self):
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def new(self) -> dict:
        """Create a fresh session with a timestamp + random suffix."""
        self._ensure_dir()
        suffix = "".join(random.choices(string.ascii_lowercase, k=4))
        sid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{suffix}"
        session = {
            "id": sid,
            "created": datetime.now(timezone.utc).isoformat(),
            "turns": [],
        }
        self.save(session)
        return session

    def load(self, session_id: str) -> dict:
        p = self._path(session_id)
        if not p.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        with open(p) as f:
            return json.load(f)

    def save(self, session: dict):
        self._ensure_dir()
        with open(self._path(session["id"]), "w") as f:
            json.dump(session, f, indent=2, ensure_ascii=False)

    def list_sessions(self) -> list[dict]:
        """Return summaries of all sessions, most recent first."""
        if not self._dir.exists():
            return []
        sessions = []
        for p in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                with open(p) as f:
                    s = json.load(f)
                turns = s.get("turns", [])
                first_prompt = turns[0]["prompt"][:60] if turns else "(empty)"
                sessions.append({
                    "id": s["id"],
                    "created": s.get("created", "?"),
                    "turns": len(turns),
                    "preview": first_prompt,
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def resolve(self, arg: str) -> dict:
        """Resolve a --session argument to a session dict.

        Accepted values:
          "new"   — create a fresh session
          "last"  — load the most recently modified session
          "<id>"  — load by explicit session ID
        """
        if arg == "new":
            return self.new()
        if arg == "last":
            if not self._dir.exists():
                return self.new()
            files = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                return self.new()
            with open(files[0]) as f:
                return json.load(f)
        return self.load(arg)


def _summarize_draft(draft: dict) -> str:
    """Truncate a draft's content to a compact summary."""
    if "error" in draft:
        return f"[error: {draft['error'][:80]}]"
    if draft.get("needs_claude_code"):
        return "[local — Claude Code]"
    content = draft.get("content", "")
    if len(content) > _SUMMARY_MAX_CHARS:
        return content[:_SUMMARY_MAX_CHARS] + "..."
    return content


def _format_turn(index: int, turn: dict) -> str:
    """Format a single turn as text."""
    lines = [f"### Turn {index} — \"{turn['prompt'][:80]}\""]
    for d in turn.get("drafts", []):
        label = d.get("label", d.get("key", "?"))
        lines.append(f"**{label}:** {d['summary']}")
    lines.append("")  # blank line after turn
    return "\n".join(lines)


def _build_context_prompt(session: dict, current_prompt: str,
                          token_budget: int = _DEFAULT_TOKEN_BUDGET) -> str:
    """Prepend summarized prior turns to the current prompt.

    When the session history exceeds *token_budget* (estimated as chars/4),
    the oldest turns are dropped and a note is inserted.
    """
    turns = session.get("turns", [])
    if not turns:
        return current_prompt

    char_budget = token_budget * _CHARS_PER_TOKEN

    # Format all turns (most recent last), then trim oldest if over budget
    formatted = [_format_turn(i, t) for i, t in enumerate(turns, 1)]
    total_chars = sum(len(f) for f in formatted)
    dropped = 0

    while total_chars > char_budget and len(formatted) > 1:
        total_chars -= len(formatted[0])
        formatted.pop(0)
        dropped += 1

    parts = ["## Prior conversation\n"]
    if dropped:
        parts.append(f"*[{dropped} earlier turn(s) omitted for brevity]*\n")
    parts.extend(formatted)
    parts.append("---\n")
    parts.append("## Current question")
    parts.append(current_prompt)
    return "\n".join(parts)


def _record_turn(session: dict, prompt: str, depth: str, drafts: list) -> None:
    """Append a completed turn to the session (mutates in-place)."""
    turn = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "depth": depth,
        "drafts": [],
    }
    for d in drafts:
        turn["drafts"].append({
            "key": d.get("key", "?"),
            "label": d.get("label", d.get("key", "?")),
            "summary": _summarize_draft(d),
        })
    session["turns"].append(turn)
