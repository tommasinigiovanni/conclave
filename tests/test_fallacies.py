"""Tests for fallacy detection — parsing, validation, integration."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conclave.fallacies import (
    FALLACIES,
    _parse_fallacy_response,
    _pick_analyzer,
    _truncate_quote,
    _validate_items,
    detect_all_fallacies,
    detect_fallacies,
)


# ── Parsing: valid JSON ──────────────────────────────────────


class TestParseFallacyResponse:
    def test_parses_single_fallacy(self):
        text = json.dumps([{
            "type": "false_dichotomy",
            "severity": "medium",
            "quote": "either we use PostgreSQL or we accept chaos",
            "explanation": "Ignores many valid alternatives.",
        }])
        result = _parse_fallacy_response(text)
        assert len(result) == 1
        assert result[0]["type"] == "false_dichotomy"
        assert result[0]["severity"] == "medium"

    def test_parses_two_fallacies(self):
        text = json.dumps([
            {"type": "straw_man", "severity": "high",
             "quote": "they want chaos", "explanation": "Misrepresents."},
            {"type": "ad_hominem", "severity": "low",
             "quote": "only a fool", "explanation": "Attacks person."},
        ])
        result = _parse_fallacy_response(text)
        assert len(result) == 2

    def test_parses_empty_array(self):
        result = _parse_fallacy_response("[]")
        assert result == []

    def test_parses_fenced_json(self):
        text = "Here's my analysis:\n```json\n" + json.dumps([{
            "type": "bandwagon", "severity": "low",
            "quote": "everyone uses it", "explanation": "Popularity != correctness.",
        }]) + "\n```\n"
        result = _parse_fallacy_response(text)
        assert len(result) == 1
        assert result[0]["type"] == "bandwagon"

    def test_parses_bare_array_in_prose(self):
        text = 'I found one fallacy:\n[{"type":"post_hoc","severity":"medium","quote":"after X, Y happened","explanation":"Correlation."}]\nThat is all.'
        result = _parse_fallacy_response(text)
        assert len(result) == 1
        assert result[0]["type"] == "post_hoc"


# ── Filtering invalid types ──────────────────────────────────


class TestFilterInvalidTypes:
    def test_filters_unknown_type(self):
        items = [
            {"type": "false_dichotomy", "severity": "low",
             "quote": "x", "explanation": "y"},
            {"type": "invented_fallacy", "severity": "low",
             "quote": "a", "explanation": "b"},
        ]
        result = _validate_items(items)
        assert len(result) == 1
        assert result[0]["type"] == "false_dichotomy"

    def test_filters_invalid_severity(self):
        items = [
            {"type": "straw_man", "severity": "critical",
             "quote": "x", "explanation": "y"},
        ]
        result = _validate_items(items)
        assert result == []

    def test_filters_missing_fields(self):
        items = [{"type": "straw_man"}]  # missing severity, quote, explanation
        result = _validate_items(items)
        assert result == []


# ── Graceful degradation ─────────────────────────────────────


class TestGracefulDegradation:
    def test_malformed_json_returns_empty(self):
        result = _parse_fallacy_response("this is not json at all {{{")
        assert result == []

    def test_api_error_returns_empty(self):
        async def failing_call(*args, **kwargs):
            raise Exception("API timeout")

        member = {"key": "test", "local": False, "provider": "openai",
                  "direct_model": "gpt-4"}
        cfg = _base_cfg()
        result = asyncio.run(detect_fallacies(
            "some text", member, cfg, _call_model=failing_call))
        assert result == []

    def test_empty_content_returns_empty(self):
        async def empty_call(*args, **kwargs):
            return {"content": "", "tokens": 0, "model": "gpt-4", "elapsed": 1}

        member = {"key": "test", "local": False, "provider": "openai",
                  "direct_model": "gpt-4"}
        cfg = _base_cfg()
        result = asyncio.run(detect_fallacies(
            "some text", member, cfg, _call_model=empty_call))
        assert result == []

    def test_error_result_returns_empty(self):
        async def error_call(*args, **kwargs):
            return {"error": "bad request", "elapsed": 0}

        member = {"key": "test", "local": False, "provider": "openai",
                  "direct_model": "gpt-4"}
        cfg = _base_cfg()
        result = asyncio.run(detect_fallacies(
            "some text", member, cfg, _call_model=error_call))
        assert result == []


# ── Quote truncation ─────────────────────────────────────────


class TestQuoteTruncation:
    def test_short_quote_unchanged(self):
        assert _truncate_quote("short quote here") == "short quote here"

    def test_long_quote_truncated(self):
        long_quote = " ".join(f"word{i}" for i in range(30))
        result = _truncate_quote(long_quote)
        assert result.endswith("...")
        # "word0 word1 ... word19..." — 20 words, last has "..." appended
        words = result.split()
        assert len(words) == 20
        assert words[-1].endswith("...")


# ── detect_all_fallacies parallel ────────────────────────────


class TestDetectAllFallacies:
    def test_runs_in_parallel(self):
        call_count = 0

        async def mock_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": '[]',
                "tokens": 10, "model": "test", "elapsed": 0.1,
            }

        drafts = [
            {"key": "gemini", "content": "response A", "label": "Gemini"},
            {"key": "gpt", "content": "response B", "label": "GPT"},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = [
            {"key": "claude", "local": True, "provider": "anthropic",
             "direct_model": "claude-3", "label": "Claude"},
            {"key": "gemini", "local": False, "provider": "google",
             "direct_model": "gemini", "label": "Gemini"},
            {"key": "gpt", "local": False, "provider": "openai",
             "direct_model": "gpt-4", "label": "GPT"},
        ]
        result = asyncio.run(detect_all_fallacies(
            drafts, cfg, _call_model=mock_call))
        # Both drafts analyzed in parallel
        assert call_count == 2
        assert "gemini" in result
        assert "gpt" in result

    def test_skips_error_drafts(self):
        call_count = 0

        async def mock_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"content": "[]", "tokens": 10, "model": "t", "elapsed": 0}

        drafts = [
            {"key": "gemini", "content": "ok", "label": "Gemini"},
            {"key": "gpt", "error": "timeout", "label": "GPT"},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = [
            {"key": "claude", "local": True, "provider": "anthropic",
             "direct_model": "c", "label": "Claude"},
        ]
        result = asyncio.run(detect_all_fallacies(
            drafts, cfg, _call_model=mock_call))
        assert call_count == 1
        assert "gemini" in result
        assert "gpt" not in result

    def test_skips_needs_claude_code_drafts(self):
        call_count = 0

        async def mock_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"content": "[]", "tokens": 10, "model": "t", "elapsed": 0}

        drafts = [
            {"key": "claude", "content": "", "needs_claude_code": True, "label": "Claude"},
            {"key": "gemini", "content": "ok", "label": "Gemini"},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = [
            {"key": "claude", "local": True, "provider": "anthropic",
             "direct_model": "c", "label": "Claude"},
        ]
        result = asyncio.run(detect_all_fallacies(
            drafts, cfg, _call_model=mock_call))
        assert call_count == 1

    def test_uses_local_analyzer(self):
        """Verifies the local member is chosen as analyzer."""
        members = [
            {"key": "gemini", "local": False},
            {"key": "claude", "local": True},
        ]
        analyzer = _pick_analyzer(members)
        assert analyzer["key"] == "claude"

    def test_fallback_to_first_when_no_local(self):
        members = [
            {"key": "gemini", "local": False},
            {"key": "gpt", "local": False},
        ]
        analyzer = _pick_analyzer(members)
        assert analyzer["key"] == "gemini"


# ── Orchestrator integration ─────────────────────────────────


class TestOrchestratorIntegration:
    def test_fallacy_detection_disabled_by_default(self):
        """When fallacy_detection=false, detect_all_fallacies is not called."""
        from conclave.orchestrator import run_conclave

        members = [
            {"key": "gemini", "label": "Gemini", "icon": "B",
             "provider": "google", "local": False, "direct_model": "gemini"},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = members
        cfg["fallacy_detection"] = False

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "response", "tokens": 10,
                    "model": "gemini", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call), \
             patch("conclave.orchestrator.detect_all_fallacies") as mock_detect:
            result = asyncio.run(run_conclave("test", cfg=cfg, quiet=True))

        mock_detect.assert_not_called()
        assert result["fallacies"] == {}

    def test_fallacy_detection_enabled(self):
        """When fallacy_detection=true, detect_all_fallacies IS called."""
        from conclave.orchestrator import run_conclave

        members = [
            {"key": "gemini", "label": "Gemini", "icon": "B",
             "provider": "google", "local": False, "direct_model": "gemini"},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = members
        cfg["fallacy_detection"] = True

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "response", "tokens": 10,
                    "model": "gemini", "elapsed": 1.0}

        fake_fallacies = {"gemini": [{"type": "straw_man", "severity": "high",
                                       "quote": "x", "explanation": "y"}]}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call), \
             patch("conclave.orchestrator.detect_all_fallacies",
                   return_value=fake_fallacies) as mock_detect:
            result = asyncio.run(run_conclave("test", cfg=cfg, quiet=True))

        mock_detect.assert_called_once()
        assert result["fallacies"] == fake_fallacies

    def test_cli_fallacies_flag_overrides_config(self):
        """--fallacies flag sets cfg['fallacy_detection'] = True."""
        from conclave.cli import main
        import sys

        with patch.object(sys, "argv", ["conclave.py", "test prompt", "--fallacies", "--raw", "--quiet"]), \
             patch("conclave.cli.run_conclave") as mock_run:
            mock_run.return_value = {
                "prompt": "test", "system": None, "depth": "standard",
                "session_id": None, "phase2_pending": False,
                "effective_prompt": None, "total_elapsed_seconds": 1,
                "phase1_drafts": [], "phase2_critiques": [],
                "aggregate_rankings": {}, "fallacies": {},
                "vote_results": [], "vote_aggregation": {},
                "dialogue": {}, "member_scores": {},
                "summary": {"models_queried": 0, "api_calls": 0,
                            "local": 0, "failed": 0, "critiques": 0,
                            "vote_count": 0, "dialogue_rounds": 0,
                            "converged_at": None},
            }
            try:
                main()
            except SystemExit:
                pass

            # Verify the cfg passed to run_conclave has fallacy_detection=True
            call_kwargs = mock_run.call_args
            cfg_passed = call_kwargs.kwargs.get("cfg") or call_kwargs[1].get("cfg")
            assert cfg_passed["fallacy_detection"] is True


# ── Cost estimation ──────────────────────────────────────────


class TestCostEstimation:
    def test_fallacy_cost_with_local_analyzer(self):
        from conclave.cost import estimate_cost

        members = [
            {"key": "claude", "label": "Claude", "icon": "C",
             "provider": "anthropic", "direct_model": "claude-3", "local": True},
            {"key": "gemini", "label": "Gemini", "icon": "G",
             "provider": "google", "direct_model": "gemini-2.0-flash", "local": False},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = members
        est = estimate_cost("test", "standard", members, cfg, fallacies=True)
        # With local analyzer, fallacy detection is free
        assert est["fallacy_total"] == 0.0

    def test_fallacy_cost_without_local(self):
        from conclave.cost import estimate_cost

        members = [
            {"key": "gemini", "label": "Gemini", "icon": "G",
             "provider": "google", "direct_model": "gemini-2.0-flash", "local": False},
            {"key": "gpt", "label": "GPT", "icon": "P",
             "provider": "openai", "direct_model": "gpt-4.1", "local": False},
        ]
        cfg = _base_cfg()
        cfg["council_members"] = members
        est = estimate_cost("test", "standard", members, cfg, fallacies=True)
        # Without local, fallacy detection has a cost
        assert est["fallacy_total"] > 0
        assert est["fallacy_note"]


# ── Helper ───────────────────────────────────────────────────


def _base_cfg():
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
        "stream": False,
        "stream_sequential": False,
        "fallacy_detection": False,
    }
