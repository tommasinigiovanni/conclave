"""Real-time progress reporting to stderr."""

import sys
import time
from collections.abc import AsyncGenerator


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

    async def stream_member_response(self, label: str, icon: str,
                                      generator: AsyncGenerator[str, None]
                                      ) -> str:
        """Consume an async generator of tokens, display live on stderr.

        Returns the full accumulated text regardless of quiet mode.
        """
        if not self._quiet:
            sys.stderr.write(f"    ⟳ {icon} {label} — streaming...")
            sys.stderr.flush()

        buf: list[str] = []
        start = time.time()
        first_token = True

        async for token in generator:
            buf.append(token)
            if not self._quiet:
                if first_token:
                    # Clear the "streaming..." line and start fresh
                    sys.stderr.write(f"\r    ⟳ {icon} {label} — ")
                    sys.stderr.flush()
                    first_token = False
                sys.stderr.write(token)
                sys.stderr.flush()

        elapsed = round(time.time() - start, 2)
        text = "".join(buf)

        if not self._quiet:
            # End with a clean status line
            sys.stderr.write(f"\n    ✅ {icon} {label} — {elapsed}s · {len(text)} chars\n")
            sys.stderr.flush()

        return text

    def stream_member_buffered(self, label: str, icon: str,
                                text: str, elapsed: float):
        """Display a pre-buffered streaming result (parallel mode)."""
        if self._quiet:
            return
        preview = text[:200].replace("\n", " ")
        if len(text) > 200:
            preview += "..."
        sys.stderr.write(f"    ⟳ {icon} {label} — {preview}\n")
        sys.stderr.write(f"    ✅ {icon} {label} — {elapsed}s · {len(text)} chars\n")
        sys.stderr.flush()
