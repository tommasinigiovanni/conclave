"""Real-time progress reporting to stderr."""

import sys


class _Progress:
    """Emits real-time progress to stderr so stdout JSON stays clean."""

    def __init__(self, quiet: bool = False):
        self._quiet = quiet

    def _emit(self, msg: str):
        if not self._quiet:
            print(msg, file=sys.stderr, flush=True)

    def header(self, depth: str, member_count: int):
        emoji = {"quick": "⚡", "standard": "🏛️", "deep": "🔥"}.get(depth, "🏛️")
        self._emit(f"{emoji} Conclave — {depth} · {member_count} members")

    def phase_start(self, phase: int, label: str):
        self._emit(f"  Phase {phase} — {label}")

    def member_done(self, member: dict, result: dict):
        icon = member.get("icon", "⚪")
        label = member.get("label", member.get("key", "?"))
        if "error" in result:
            self._emit(f"    ❌ {icon} {label} — {result['error'][:60]}")
        elif result.get("needs_claude_code"):
            self._emit(f"    🏠 {icon} {label} — local (Claude Code)")
        else:
            elapsed = result.get("elapsed", "?")
            self._emit(f"    ✅ {icon} {label} — {elapsed}s")

    def done(self, total_seconds: float):
        self._emit(f"  Done in {total_seconds}s")
