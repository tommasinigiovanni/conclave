"""Tests for conclave.sessions — context building and token budget."""

from conclave.sessions import _build_context_prompt, _format_turn, _record_turn


# ── Helpers ───────────────────────────────────────────────────────


def _make_session(num_turns: int, draft_summary_len: int = 100) -> dict:
    """Build a session with N turns, each having one draft."""
    turns = []
    for i in range(num_turns):
        turns.append({
            "prompt": f"Question {i + 1}",
            "depth": "standard",
            "drafts": [
                {"key": "gpt", "label": "GPT", "summary": "x" * draft_summary_len},
            ],
        })
    return {"id": "test-session", "created": "2026-01-01T00:00:00Z", "turns": turns}


# ── _format_turn ──────────────────────────────────────────────────


class TestFormatTurn:
    def test_includes_prompt_and_draft(self):
        turn = {
            "prompt": "What is X?",
            "drafts": [{"key": "gpt", "label": "GPT", "summary": "GPT said Y"}],
        }
        result = _format_turn(1, turn)
        assert "Turn 1" in result
        assert "What is X?" in result
        assert "**GPT:** GPT said Y" in result

    def test_truncates_long_prompts(self):
        turn = {"prompt": "a" * 200, "drafts": []}
        result = _format_turn(1, turn)
        # prompt is truncated to 80 chars in the format
        assert "a" * 80 in result
        assert "a" * 81 not in result


# ── _build_context_prompt — no truncation ─────────────────────────


class TestBuildContextPromptBasic:
    def test_empty_turns_returns_current_prompt(self):
        session = {"turns": []}
        assert _build_context_prompt(session, "hello") == "hello"

    def test_includes_prior_turns_and_current(self):
        session = _make_session(2, draft_summary_len=20)
        result = _build_context_prompt(session, "current?")
        assert "Prior conversation" in result
        assert "Turn 1" in result
        assert "Turn 2" in result
        assert "Current question" in result
        assert "current?" in result

    def test_no_omission_note_when_within_budget(self):
        session = _make_session(2, draft_summary_len=20)
        result = _build_context_prompt(session, "q?", token_budget=50000)
        assert "omitted" not in result


# ── _build_context_prompt — token budget truncation ───────────────


class TestBuildContextPromptTruncation:
    def test_drops_oldest_turns_when_over_budget(self):
        # Each turn is ~120 chars → ~30 tokens.  Budget of 40 tokens → keeps ~1 turn.
        session = _make_session(5, draft_summary_len=100)
        result = _build_context_prompt(session, "now?", token_budget=40)
        assert "omitted" in result
        # The most recent turn (Turn 5) should survive
        assert "Question 5" in result

    def test_omission_note_shows_count(self):
        session = _make_session(4, draft_summary_len=100)
        result = _build_context_prompt(session, "q?", token_budget=50)
        assert "earlier turn(s) omitted" in result

    def test_always_keeps_at_least_one_turn(self):
        # Even with a tiny budget, the last turn is never dropped
        session = _make_session(3, draft_summary_len=500)
        result = _build_context_prompt(session, "q?", token_budget=1)
        assert "Turn 3" in result or "Question 3" in result

    def test_large_budget_keeps_all_turns(self):
        session = _make_session(10, draft_summary_len=50)
        result = _build_context_prompt(session, "q?", token_budget=100000)
        assert "omitted" not in result
        for i in range(1, 11):
            assert f"Question {i}" in result

    def test_preserves_most_recent_turns(self):
        session = _make_session(6, draft_summary_len=100)
        result = _build_context_prompt(session, "q?", token_budget=80)
        # Most recent turns should be present, oldest dropped
        assert "Question 6" in result
        assert "Question 1" not in result


# ── _record_turn ──────────────────────────────────────────────────


class TestRecordTurn:
    def test_appends_turn(self):
        session = {"turns": []}
        drafts = [{"key": "gpt", "label": "GPT", "content": "hello world"}]
        _record_turn(session, "test prompt", "standard", drafts)
        assert len(session["turns"]) == 1
        assert session["turns"][0]["prompt"] == "test prompt"
        assert session["turns"][0]["depth"] == "standard"

    def test_summarizes_drafts(self):
        session = {"turns": []}
        drafts = [{"key": "gpt", "label": "GPT", "content": "a" * 500}]
        _record_turn(session, "q", "quick", drafts)
        summary = session["turns"][0]["drafts"][0]["summary"]
        assert len(summary) <= 303  # 300 + "..."

    def test_handles_error_drafts(self):
        session = {"turns": []}
        drafts = [{"key": "gpt", "error": "timeout", "elapsed": 10}]
        _record_turn(session, "q", "quick", drafts)
        assert "[error:" in session["turns"][0]["drafts"][0]["summary"]

    def test_handles_local_drafts(self):
        session = {"turns": []}
        drafts = [{"key": "claude", "needs_claude_code": True, "content": ""}]
        _record_turn(session, "q", "quick", drafts)
        assert "Claude Code" in session["turns"][0]["drafts"][0]["summary"]
