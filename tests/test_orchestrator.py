"""Tests for conclave.orchestrator — phase1, phase2, run_conclave."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from conclave.orchestrator import doctor, phase1, phase2, run_conclave, run_phase2_only
from conclave.progress import _Progress


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def quiet_progress():
    return _Progress(quiet=True)


@pytest.fixture
def members():
    return [
        {"key": "claude", "label": "Claude", "icon": "🟣",
         "provider": "anthropic", "local": True, "direct_model": "claude-opus-4.6"},
        {"key": "gemini", "label": "Gemini", "icon": "🔵",
         "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
        {"key": "gpt", "label": "GPT", "icon": "🟢",
         "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
    ]


@pytest.fixture
def cfg():
    return {
        "provider_mode": "direct",
        "direct_keys": {"anthropic": "sk-a", "google": "gk-g", "openai": "ok-o"},
        "openrouter": {"api_key": ""},
        "defaults": {
            "temperature": 0.7, "max_tokens": 100,
            "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
        },
        "anonymize_reviews": True,
        "council_members": [],
    }


@pytest.fixture
def templates():
    return {
        "critique_system": "You are a peer reviewer.",
        "critique_prompt": "Q: {original_prompt}\n\n{anonymized_responses}",
    }


def _fake_call_model(responses: dict):
    """Return an AsyncMock that maps member key → response dict."""
    async def _call(member, prompt, system, cfg, **kwargs):
        key = member["key"]
        base = responses.get(key, {"error": "not configured"})
        return dict(base)  # copy to avoid mutation across calls
    return _call


# ── phase1 ────────────────────────────────────────────────────────


class TestPhase1:
    def test_calls_all_members(self, members, cfg, quiet_progress):
        responses = {
            "claude": {"content": "", "needs_claude_code": True, "model": "claude-opus-4.6",
                       "tokens": None, "elapsed": 0},
            "gemini": {"content": "Gemini says hi", "tokens": 10, "model": "gemini-2.0-flash",
                       "elapsed": 1.0},
            "gpt":    {"content": "GPT says hi", "tokens": 8, "model": "gpt-5.2",
                       "elapsed": 1.2},
        }
        with patch("conclave.orchestrator.call_model", side_effect=_fake_call_model(responses)):
            drafts = asyncio.run(phase1("hello", None, members, cfg, quiet_progress))

        assert len(drafts) == 3
        keys = {d["key"] for d in drafts}
        assert keys == {"claude", "gemini", "gpt"}

    def test_attaches_key_label_icon(self, members, cfg, quiet_progress):
        responses = {
            "claude": {"content": "", "needs_claude_code": True, "model": "x", "tokens": None, "elapsed": 0},
            "gemini": {"content": "ok", "tokens": 5, "model": "x", "elapsed": 0.5},
            "gpt":    {"content": "ok", "tokens": 5, "model": "x", "elapsed": 0.5},
        }
        with patch("conclave.orchestrator.call_model", side_effect=_fake_call_model(responses)):
            drafts = asyncio.run(phase1("test", None, members, cfg, quiet_progress))

        for d in drafts:
            assert "key" in d
            assert "label" in d
            assert "icon" in d

    def test_handles_errors_gracefully(self, members, cfg, quiet_progress):
        responses = {
            "claude": {"content": "", "needs_claude_code": True, "model": "x", "tokens": None, "elapsed": 0},
            "gemini": {"error": "timeout", "elapsed": 10},
            "gpt":    {"content": "ok", "tokens": 5, "model": "x", "elapsed": 0.5},
        }
        with patch("conclave.orchestrator.call_model", side_effect=_fake_call_model(responses)):
            drafts = asyncio.run(phase1("test", None, members, cfg, quiet_progress))

        assert len(drafts) == 3
        gemini_draft = next(d for d in drafts if d["key"] == "gemini")
        assert "error" in gemini_draft


# ── phase2 ────────────────────────────────────────────────────────


class TestPhase2:
    def test_returns_critiques_with_rankings(self, members, cfg, templates, quiet_progress):
        drafts = [
            {"key": "claude", "label": "Claude", "content": "Claude answer"},
            {"key": "gemini", "label": "Gemini", "content": "Gemini answer"},
            {"key": "gpt",    "label": "GPT",    "content": "GPT answer"},
        ]

        critique_text = (
            "Good analysis.\n\n"
            '```json\n{"ranking": ["A", "B"]}\n```\n'
        )

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": critique_text, "tokens": 50, "model": "test", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            critiques = asyncio.run(
                phase2("original q", drafts, members, cfg, templates, quiet_progress))

        assert len(critiques) == 3
        for c in critiques:
            assert "ranking" in c
            assert "letter_map" in c
            assert c["ranking"] == ["A", "B"]
            assert c["ranking_reprompted"] is False

    def test_reprompts_on_json_failure(self, members, cfg, templates, quiet_progress):
        """Initial response has no JSON → repair prompt succeeds → ranking_reprompted=True."""
        drafts = [
            {"key": "claude", "label": "Claude", "content": "Claude answer"},
            {"key": "gemini", "label": "Gemini", "content": "Gemini answer"},
            {"key": "gpt",    "label": "GPT",    "content": "GPT answer"},
        ]

        call_count = 0
        async def fake_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            # Odd calls = initial critique (no JSON), even calls = repair (with JSON)
            if call_count % 2 == 1:
                return {"content": "Good analysis but no JSON ranking here.",
                        "tokens": 50, "model": "test", "elapsed": 1.0}
            else:
                return {"content": '{"ranking": ["A", "B"]}',
                        "tokens": 10, "model": "test", "elapsed": 0.5}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            critiques = asyncio.run(
                phase2("original q", drafts, members, cfg, templates, quiet_progress))

        assert len(critiques) == 3
        for c in critiques:
            assert c["ranking"] == ["A", "B"]
            assert c["ranking_reprompted"] is True

    def test_regex_fallback_after_reprompt_failure(self, members, cfg, templates, quiet_progress):
        """Both JSON attempts fail → regex on original works."""
        drafts = [
            {"key": "claude", "label": "Claude", "content": "Claude answer"},
            {"key": "gemini", "label": "Gemini", "content": "Gemini answer"},
            {"key": "gpt",    "label": "GPT",    "content": "GPT answer"},
        ]

        call_count = 0
        async def fake_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                # Initial: has regex ranking but no JSON
                return {"content": "Analysis.\n\nFINAL RANKING:\n1. B\n2. A\n",
                        "tokens": 50, "model": "test", "elapsed": 1.0}
            else:
                # Repair: also no valid JSON
                return {"content": "Sorry, here: B, A",
                        "tokens": 10, "model": "test", "elapsed": 0.5}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            critiques = asyncio.run(
                phase2("original q", drafts, members, cfg, templates, quiet_progress))

        assert len(critiques) == 3
        for c in critiques:
            assert c["ranking"] == ["B", "A"]
            assert c["ranking_reprompted"] is True

    def test_skips_members_with_failed_drafts(self, members, cfg, templates, quiet_progress):
        drafts = [
            {"key": "claude", "label": "Claude", "content": "Claude answer"},
            {"key": "gemini", "label": "Gemini", "error": "timeout"},
            {"key": "gpt",    "label": "GPT",    "content": "GPT answer"},
        ]

        async def fake_call(member, prompt, system, cfg, **kwargs):
            # With only 1 other draft, valid_letters={"A"}, so return regex-parseable ranking
            return {"content": "Analysis.\n\nFINAL RANKING:\n1. A\n",
                    "tokens": 10, "model": "test", "elapsed": 0.5}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            critiques = asyncio.run(
                phase2("q", drafts, members, cfg, templates, quiet_progress))

        # gemini had error → skipped. claude + gpt participate = 2 critiques
        assert len(critiques) == 2
        critique_keys = {c["key"] for c in critiques}
        assert "gemini" not in critique_keys

    def test_returns_empty_if_fewer_than_2_ok_drafts(self, members, cfg, templates, quiet_progress):
        drafts = [
            {"key": "claude", "label": "Claude", "error": "fail"},
            {"key": "gemini", "label": "Gemini", "error": "fail"},
            {"key": "gpt",    "label": "GPT",    "content": "only one ok"},
        ]

        critiques = asyncio.run(
            phase2("q", drafts, members, cfg, templates, quiet_progress))
        assert critiques == []


# ── run_conclave ──────────────────────────────────────────────────


class TestRunConclave:
    def _cfg_with_members(self, members):
        return {
            "provider_mode": "direct",
            "direct_keys": {"anthropic": "sk-a", "google": "gk-g", "openai": "ok-o"},
            "openrouter": {"api_key": ""},
            "defaults": {
                "temperature": 0.7, "max_tokens": 100,
                "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
            },
            "anonymize_reviews": True,
            "council_members": members,
        }

    def _fake_call(self, member, prompt, system, cfg, **kwargs):
        """Simple mock: local → placeholder, remote → content."""
        if member.get("local"):
            return {"content": "", "needs_claude_code": True,
                    "model": member.get("direct_model", "x"), "tokens": None, "elapsed": 0}
        return {"content": f"{member['key']} response", "tokens": 10,
                "model": member.get("direct_model", "x"), "elapsed": 1.0}

    def test_quick_skips_phase2(self, members):
        cfg = self._cfg_with_members(members)
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave("test", depth="quick", cfg=cfg, quiet=True))

        assert result["depth"] == "quick"
        assert len(result["phase1_drafts"]) == 3
        assert result["phase2_critiques"] == []
        assert result["aggregate_rankings"] == {}

    def test_standard_skips_phase2(self, members):
        cfg = self._cfg_with_members(members)
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave("test", depth="standard", cfg=cfg, quiet=True))

        assert result["phase2_critiques"] == []

    def test_deep_defers_phase2_with_local(self, members):
        """Deep with local member → phase2_pending=True, Phase 1 only."""
        cfg = self._cfg_with_members(members)

        call_count = 0
        async def fake_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            if member.get("local"):
                return {"content": "", "needs_claude_code": True,
                        "model": "x", "tokens": None, "elapsed": 0}
            return {"content": 'resp', "tokens": 10, "model": "x", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            result = asyncio.run(run_conclave("test", depth="deep", cfg=cfg, quiet=True))

        assert result["depth"] == "deep"
        assert result["phase2_pending"] is True
        # Phase 1 only: 3 calls (no Phase 2)
        assert call_count == 3
        assert result["phase2_critiques"] == []
        assert result["aggregate_rankings"] == {}

    def test_member_keys_filters(self, members):
        cfg = self._cfg_with_members(members)
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave(
                "test", depth="quick", cfg=cfg, quiet=True, member_keys=["gemini"]))

        assert len(result["phase1_drafts"]) == 1
        assert result["phase1_drafts"][0]["key"] == "gemini"

    def test_output_structure(self, members):
        cfg = self._cfg_with_members(members)
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave("test prompt", depth="quick", cfg=cfg, quiet=True))

        assert result["prompt"] == "test prompt"
        assert "total_elapsed_seconds" in result
        assert "summary" in result
        summary = result["summary"]
        assert "models_queried" in summary
        assert "api_calls" in summary
        assert "local" in summary
        assert "failed" in summary
        assert "critiques" in summary

    def test_summary_counts(self, members):
        cfg = self._cfg_with_members(members)
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave("test", depth="quick", cfg=cfg, quiet=True))

        s = result["summary"]
        assert s["models_queried"] == 3
        assert s["local"] == 1       # claude
        assert s["api_calls"] == 2   # gemini + gpt
        assert s["failed"] == 0


# ── doctor ────────────────────────────────────────────────────────


class TestDoctor:
    def test_reports_local_and_remote(self, members):
        cfg = {
            "provider_mode": "direct",
            "direct_keys": {"google": "gk", "openai": "ok"},
            "openrouter": {"api_key": ""},
            "defaults": {"temperature": 0.7, "max_tokens": 50,
                         "timeout_seconds": 5, "max_retries": 0, "retry_base_delay": 0.01},
            "council_members": members,
        }

        async def fake_call(member, prompt, system, cfg, **kwargs):
            if member.get("local"):
                return {"content": "", "needs_claude_code": True, "model": "x",
                        "tokens": None, "elapsed": 0}
            return {"content": "OK", "tokens": 2, "model": "x", "elapsed": 0.5}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            report = asyncio.run(doctor(cfg))

        assert len(report) == 3
        local_entries = [r for r in report if "Local" in r["status"]]
        ok_entries = [r for r in report if "✅" in r["status"]]
        assert len(local_entries) == 1
        assert len(ok_entries) == 2

    def test_reports_errors(self):
        members = [
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
        ]
        cfg = {
            "provider_mode": "direct",
            "direct_keys": {},
            "openrouter": {"api_key": ""},
            "defaults": {"temperature": 0.7, "max_tokens": 50,
                         "timeout_seconds": 5, "max_retries": 0, "retry_base_delay": 0.01},
            "council_members": members,
        }

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"error": "API key for google not set", "elapsed": 0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            report = asyncio.run(doctor(cfg))

        assert len(report) == 1
        assert "❌" in report[0]["status"]


# ── Two-pass flow ────────────────────────────────────────────────


class TestTwoPassFlow:
    """Tests for phase2_pending deferral when local members are present."""

    def _cfg_with_members(self, members):
        return {
            "provider_mode": "direct",
            "direct_keys": {"anthropic": "sk-a", "google": "gk-g", "openai": "ok-o"},
            "openrouter": {"api_key": ""},
            "defaults": {
                "temperature": 0.7, "max_tokens": 100,
                "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
            },
            "anonymize_reviews": True,
            "council_members": members,
        }

    def _fake_call(self, member, prompt, system, cfg, **kwargs):
        if member.get("local"):
            return {"content": "", "needs_claude_code": True,
                    "model": member.get("direct_model", "x"), "tokens": None, "elapsed": 0}
        return {"content": f"{member['key']} response", "tokens": 10,
                "model": member.get("direct_model", "x"), "elapsed": 1.0}

    def test_deep_with_local_returns_phase2_pending(self, members):
        """Local member present → phase2_pending=True, empty critiques."""
        cfg = self._cfg_with_members(members)
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave("test", depth="deep", cfg=cfg, quiet=True))

        assert result["phase2_pending"] is True
        assert result["phase2_critiques"] == []
        assert result["aggregate_rankings"] == {}
        assert result["effective_prompt"] is not None

    def test_deep_without_local_runs_phase2_immediately(self):
        """No local members → phase2_pending=False, critiques populated."""
        api_only = [
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
            {"key": "gpt", "label": "GPT", "icon": "🟢",
             "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
            {"key": "llama", "label": "Llama", "icon": "🟠",
             "provider": "openai", "local": False, "direct_model": "llama-3"},
        ]
        cfg = self._cfg_with_members(api_only)

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": 'resp\n\n```json\n{"ranking": ["A", "B"]}\n```\n',
                    "tokens": 10, "model": "x", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            result = asyncio.run(run_conclave("test", depth="deep", cfg=cfg, quiet=True))

        assert result["phase2_pending"] is False
        assert result["effective_prompt"] is None
        assert len(result["phase2_critiques"]) == 3
        assert result["aggregate_rankings"]  # non-empty

    def test_quick_and_standard_never_set_phase2_pending(self, members):
        """Non-deep depths always have phase2_pending=False."""
        cfg = self._cfg_with_members(members)
        for depth in ("quick", "standard"):
            with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
                result = asyncio.run(run_conclave("test", depth=depth, cfg=cfg, quiet=True))
            assert result["phase2_pending"] is False
            assert result["effective_prompt"] is None

    def test_effective_prompt_includes_session_context(self, members):
        """Session mode: effective_prompt has prior turns baked in."""
        cfg = self._cfg_with_members(members)
        session = {
            "id": "test-session-123",
            "turns": [
                {"prompt": "first question", "depth": "quick",
                 "summaries": [{"key": "gemini", "summary": "Gemini said stuff"}]},
            ],
        }
        with patch("conclave.orchestrator.call_model", side_effect=self._fake_call):
            result = asyncio.run(run_conclave(
                "follow-up question", depth="deep", cfg=cfg, quiet=True,
                session=session))

        assert result["phase2_pending"] is True
        ep = result["effective_prompt"]
        assert "first question" in ep
        assert "follow-up question" in ep


# ── run_phase2_only ──────────────────────────────────────────────


class TestRunPhase2Only:
    """Tests for the Phase 2 only entry point."""

    def _cfg_with_members(self, members):
        return {
            "provider_mode": "direct",
            "direct_keys": {"anthropic": "sk-a", "google": "gk-g", "openai": "ok-o"},
            "openrouter": {"api_key": ""},
            "defaults": {
                "temperature": 0.7, "max_tokens": 100,
                "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
            },
            "anonymize_reviews": True,
            "council_members": [
                {"key": "claude", "label": "Claude", "icon": "🟣",
                 "provider": "anthropic", "local": True, "direct_model": "claude-opus-4.6"},
                {"key": "gemini", "label": "Gemini", "icon": "🔵",
                 "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
                {"key": "gpt", "label": "GPT", "icon": "🟢",
                 "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
            ],
        }

    def test_runs_phase2_with_completed_drafts(self):
        """Produces critiques and rankings from completed drafts."""
        members = [
            {"key": "claude", "label": "Claude", "icon": "🟣",
             "provider": "anthropic", "local": True, "direct_model": "claude-opus-4.6"},
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
            {"key": "gpt", "label": "GPT", "icon": "🟢",
             "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
        ]
        cfg = self._cfg_with_members(members)
        phase1_data = {
            "prompt": "test question",
            "system": None,
            "depth": "deep",
            "session_id": None,
            "phase2_pending": True,
            "effective_prompt": "test question",
            "phase1_drafts": [
                {"key": "claude", "label": "Claude", "content": "Claude's real answer",
                 "needs_claude_code": True, "elapsed": 0},
                {"key": "gemini", "label": "Gemini", "content": "Gemini response",
                 "elapsed": 1.0},
                {"key": "gpt", "label": "GPT", "content": "GPT response",
                 "elapsed": 1.2},
            ],
        }

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": 'Review.\n\n```json\n{"ranking": ["A", "B"]}\n```\n',
                    "tokens": 50, "model": "test", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            result = asyncio.run(run_phase2_only(phase1_data, cfg=cfg, quiet=True))

        assert result["phase2_pending"] is False
        assert len(result["phase2_critiques"]) == 3
        assert result["aggregate_rankings"]  # non-empty
        assert result["depth"] == "deep"

    def test_returns_error_if_fewer_than_2_ok_drafts(self):
        """Graceful error when not enough non-error drafts with content."""
        members = [
            {"key": "claude", "label": "Claude", "icon": "🟣",
             "provider": "anthropic", "local": True, "direct_model": "claude-opus-4.6"},
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
        ]
        cfg = self._cfg_with_members(members)
        phase1_data = {
            "prompt": "test",
            "effective_prompt": "test",
            "phase2_pending": True,
            "phase1_drafts": [
                {"key": "claude", "label": "Claude", "content": "Claude answer",
                 "elapsed": 0},
                {"key": "gemini", "label": "Gemini", "error": "timeout",
                 "elapsed": 10},
            ],
        }

        result = asyncio.run(run_phase2_only(phase1_data, cfg=cfg, quiet=True))
        assert "error" in result

    def test_uses_effective_prompt_for_critique(self):
        """Session context passed through to Phase 2 via effective_prompt."""
        members = [
            {"key": "claude", "label": "Claude", "icon": "🟣",
             "provider": "anthropic", "local": True, "direct_model": "claude-opus-4.6"},
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
            {"key": "gpt", "label": "GPT", "icon": "🟢",
             "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
        ]
        cfg = self._cfg_with_members(members)

        session_prompt = "PRIOR CONTEXT: first question\n\nCurrent question: follow-up"
        phase1_data = {
            "prompt": "follow-up",
            "system": None,
            "effective_prompt": session_prompt,
            "phase2_pending": True,
            "phase1_drafts": [
                {"key": "claude", "label": "Claude", "content": "Claude answer",
                 "elapsed": 0},
                {"key": "gemini", "label": "Gemini", "content": "Gemini response",
                 "elapsed": 1.0},
                {"key": "gpt", "label": "GPT", "content": "GPT response",
                 "elapsed": 1.2},
            ],
        }

        captured_prompts = []

        async def fake_call(member, prompt, system, cfg, **kwargs):
            captured_prompts.append(prompt)
            return {"content": '```json\n{"ranking": ["A", "B"]}\n```',
                    "tokens": 50, "model": "test", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            result = asyncio.run(run_phase2_only(phase1_data, cfg=cfg, quiet=True))

        # The critique prompts should contain session context
        assert len(captured_prompts) >= 1
        for p in captured_prompts:
            assert "PRIOR CONTEXT" in p or "first question" in p
