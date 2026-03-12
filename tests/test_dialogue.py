"""Tests for conclave.dialogue — multi-round dialogue."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from conclave.dialogue import (
    build_round_prompt,
    check_convergence,
    detect_stance,
    extract_critiques_for_model,
    get_max_rounds,
    run_dialogue_rounds,
)
from conclave.progress import _Progress


@pytest.fixture
def members():
    return [
        {"key": "gemini", "label": "Gemini", "icon": "🔵",
         "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
        {"key": "gpt", "label": "GPT", "icon": "🟢",
         "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
    ]


@pytest.fixture
def cfg():
    return {
        "provider_mode": "direct",
        "direct_keys": {"google": "gk-g", "openai": "ok-o"},
        "openrouter": {"api_key": ""},
        "defaults": {
            "temperature": 0.7, "max_tokens": 100,
            "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
        },
        "anonymize_reviews": True,
        "council_members": [],
    }


class TestDetectStance:
    def test_converge(self):
        assert detect_stance("CONVERGE: I agree with the critiques.") == "converge"

    def test_maintain(self):
        assert detect_stance("MAINTAIN: My original position stands.") == "maintain"

    def test_update(self):
        assert detect_stance("UPDATE: I revise my position slightly.") == "update"

    def test_unknown(self):
        assert detect_stance("I think this is interesting.") == "unknown"

    def test_case_insensitive(self):
        assert detect_stance("converge: yes") == "converge"

    def test_with_leading_whitespace(self):
        assert detect_stance("  CONVERGE: agreed") == "converge"


class TestBuildRoundPrompt:
    def test_includes_answer_and_critiques(self):
        prompt = build_round_prompt("My answer", ["Critique 1", "Critique 2"], 2)
        assert "My answer" in prompt
        assert "Critique 1" in prompt
        assert "Critique 2" in prompt
        assert "CONVERGE:" in prompt
        assert "MAINTAIN:" in prompt
        assert "UPDATE:" in prompt


class TestCheckConvergence:
    def test_all_converge(self):
        responses = [
            {"content": "CONVERGE: agreed", "key": "a"},
            {"content": "CONVERGE: same here", "key": "b"},
        ]
        assert check_convergence(responses) is True

    def test_not_all_converge(self):
        responses = [
            {"content": "CONVERGE: agreed", "key": "a"},
            {"content": "MAINTAIN: no", "key": "b"},
        ]
        assert check_convergence(responses) is False

    def test_empty_responses(self):
        assert check_convergence([]) is False

    def test_skips_errors(self):
        responses = [
            {"content": "CONVERGE: agreed", "key": "a"},
            {"error": "timeout", "key": "b"},
        ]
        # Only one non-error response and it converges
        assert check_convergence(responses) is True


class TestExtractCritiquesForModel:
    def test_extracts_relevant_critiques(self):
        critiques = [
            {"key": "gpt", "content": "Critique of gemini",
             "letter_map": {"A": "gemini"}},
            {"key": "gemini", "content": "Critique of gpt",
             "letter_map": {"A": "gpt"}},
        ]
        result = extract_critiques_for_model(critiques, "gemini")
        assert len(result) == 1
        assert "Critique of gemini" in result[0]

    def test_returns_empty_for_no_match(self):
        critiques = [
            {"key": "gpt", "content": "Critique",
             "letter_map": {"A": "claude"}},
        ]
        result = extract_critiques_for_model(critiques, "gemini")
        assert result == []


class TestRunDialogueRounds:
    def test_runs_correct_number_of_rounds(self, members, cfg):
        drafts = [
            {"key": "gemini", "content": "Gemini answer"},
            {"key": "gpt", "content": "GPT answer"},
        ]
        critiques = [
            {"key": "gemini", "content": "Critique", "letter_map": {"A": "gpt"}},
            {"key": "gpt", "content": "Critique", "letter_map": {"A": "gemini"}},
        ]

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "MAINTAIN: my position", "tokens": 10,
                    "model": "x", "elapsed": 0.5}

        result = asyncio.run(run_dialogue_rounds(
            "test", drafts, critiques, members, cfg, fake_call, 3,
            _Progress(quiet=True)))

        assert result["total_rounds"] == 3
        assert len(result["rounds"]) == 2  # rounds 2 and 3
        assert result["converged_at"] is None

    def test_early_termination_on_convergence(self, members, cfg):
        drafts = [
            {"key": "gemini", "content": "Gemini answer"},
            {"key": "gpt", "content": "GPT answer"},
        ]
        critiques = [
            {"key": "gemini", "content": "Critique", "letter_map": {"A": "gpt"}},
            {"key": "gpt", "content": "Critique", "letter_map": {"A": "gemini"}},
        ]

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "CONVERGE: I agree", "tokens": 10,
                    "model": "x", "elapsed": 0.5}

        result = asyncio.run(run_dialogue_rounds(
            "test", drafts, critiques, members, cfg, fake_call, 3,
            _Progress(quiet=True)))

        assert result["converged_at"] == 2
        assert result["total_rounds"] == 2
        assert len(result["rounds"]) == 1  # only round 2

    def test_handles_model_failure_mid_round(self, members, cfg):
        drafts = [
            {"key": "gemini", "content": "Gemini answer"},
            {"key": "gpt", "content": "GPT answer"},
        ]
        critiques = [
            {"key": "gemini", "content": "Critique", "letter_map": {"A": "gpt"}},
            {"key": "gpt", "content": "Critique", "letter_map": {"A": "gemini"}},
        ]

        call_count = 0
        async def fake_call(member, prompt, system, cfg, **kwargs):
            nonlocal call_count
            call_count += 1
            if member["key"] == "gemini":
                return {"error": "timeout", "elapsed": 10}
            return {"content": "MAINTAIN: my position", "tokens": 10,
                    "model": "x", "elapsed": 0.5}

        result = asyncio.run(run_dialogue_rounds(
            "test", drafts, critiques, members, cfg, fake_call, 2,
            _Progress(quiet=True)))

        assert result["total_rounds"] == 2
        # gemini failed but round still completes
        assert len(result["rounds"]) == 1

    def test_single_round_returns_empty(self, members, cfg):
        result = asyncio.run(run_dialogue_rounds(
            "test", [], [], members, cfg, None, 1, _Progress(quiet=True)))
        assert result["rounds"] == []
        assert result["converged_at"] is None

    def test_respects_max_rounds_cap(self, members, cfg):
        drafts = [
            {"key": "gemini", "content": "Gemini answer"},
            {"key": "gpt", "content": "GPT answer"},
        ]
        critiques = [
            {"key": "gemini", "content": "Critique", "letter_map": {"A": "gpt"}},
            {"key": "gpt", "content": "Critique", "letter_map": {"A": "gemini"}},
        ]

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "MAINTAIN: holding", "tokens": 10,
                    "model": "x", "elapsed": 0.5}

        # Request 10 rounds but max_rounds defaults to 3
        with patch("conclave.dialogue.get_max_rounds", return_value=3):
            result = asyncio.run(run_dialogue_rounds(
                "test", drafts, critiques, members, cfg, fake_call, 10,
                _Progress(quiet=True)))

        assert result["total_rounds"] == 3

    def test_combined_with_vote_results(self, members, cfg):
        """Rounds work when given vote_results instead of critiques."""
        drafts = [
            {"key": "gemini", "content": "Gemini answer"},
            {"key": "gpt", "content": "GPT answer"},
        ]
        # vote results have letter_map like critiques
        vote_results = [
            {"key": "gemini", "votes": {"A": 60, "B": 40},
             "content": "Voting context", "letter_map": {"A": "gpt"}},
            {"key": "gpt", "votes": {"A": 55, "B": 45},
             "content": "Voting context", "letter_map": {"A": "gemini"}},
        ]

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "CONVERGE: agreed", "tokens": 10,
                    "model": "x", "elapsed": 0.5}

        result = asyncio.run(run_dialogue_rounds(
            "test", drafts, vote_results, members, cfg, fake_call, 2,
            _Progress(quiet=True)))

        assert result["converged_at"] == 2


class TestGetMaxRounds:
    def test_default_value(self):
        with patch("conclave.dialogue._load_env_file", return_value={}):
            assert get_max_rounds() == 3

    def test_from_env(self):
        with patch("conclave.dialogue._load_env_file",
                    return_value={"CONCLAVE_MAX_ROUNDS": "5"}):
            assert get_max_rounds() == 5

    def test_invalid_value_fallback(self):
        with patch("conclave.dialogue._load_env_file",
                    return_value={"CONCLAVE_MAX_ROUNDS": "abc"}):
            assert get_max_rounds() == 3
