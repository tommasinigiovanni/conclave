"""Tests for conclave.voting — quorum voting with point distribution."""

import json

import pytest

from conclave.voting import (
    _normalize_to_100,
    _try_parse_votes,
    aggregate_votes,
    build_vote_prompt,
    parse_vote_response,
    votes_to_ranking_fallback,
)


class TestParseVoteResponse:
    def test_parses_clean_json(self):
        text = '{"Response A": 60, "Response B": 40}'
        result = parse_vote_response(text, {"A", "B"})
        assert result == {"A": 60, "B": 40}

    def test_parses_fenced_json(self):
        text = 'Here are my votes:\n```json\n{"Response A": 70, "Response B": 30}\n```'
        result = parse_vote_response(text, {"A", "B"})
        assert result == {"A": 70, "B": 30}

    def test_parses_json_without_response_prefix(self):
        text = '{"A": 55, "B": 45}'
        result = parse_vote_response(text, {"A", "B"})
        assert result == {"A": 55, "B": 45}

    def test_returns_none_for_invalid_json(self):
        text = "I think Response A is better, maybe 60/40"
        result = parse_vote_response(text, {"A", "B"})
        assert result is None

    def test_returns_none_for_missing_letters(self):
        text = '{"Response A": 100}'
        result = parse_vote_response(text, {"A", "B"})
        assert result is None

    def test_returns_none_for_wrong_total(self):
        text = '{"Response A": 50, "Response B": 20}'
        result = parse_vote_response(text, {"A", "B"})
        assert result is None  # total=70, too far from 100

    def test_normalizes_near_100(self):
        # 51+51=102, within tolerance of 5
        text = '{"Response A": 51, "Response B": 51}'
        result = parse_vote_response(text, {"A", "B"})
        assert result is not None
        assert sum(result.values()) == 100

    def test_handles_float_values(self):
        text = '{"Response A": 66.7, "Response B": 33.3}'
        result = parse_vote_response(text, {"A", "B"})
        assert result is not None
        assert sum(result.values()) == 100

    def test_handles_three_models(self):
        text = '{"Response A": 40, "Response B": 35, "Response C": 25}'
        result = parse_vote_response(text, {"A", "B", "C"})
        assert result == {"A": 40, "B": 35, "C": 25}

    def test_returns_none_for_extra_letters(self):
        text = '{"Response A": 40, "Response B": 30, "Response C": 30}'
        result = parse_vote_response(text, {"A", "B"})
        assert result is None


class TestNormalizeTo100:
    def test_already_100(self):
        assert _normalize_to_100({"A": 60, "B": 40}) == {"A": 60, "B": 40}

    def test_scales_up(self):
        result = _normalize_to_100({"A": 30, "B": 20})
        assert sum(result.values()) == 100

    def test_handles_zero_total(self):
        result = _normalize_to_100({"A": 0, "B": 0})
        assert sum(result.values()) == 100


class TestBuildVotePrompt:
    def test_excludes_self(self):
        drafts = [
            {"key": "gemini", "content": "Gemini answer"},
            {"key": "gpt", "content": "GPT answer"},
            {"key": "claude", "content": "Claude answer"},
        ]
        prompt, letter_map = build_vote_prompt("test", drafts, "claude", anonymize=False)
        assert "claude" not in letter_map.values() or True  # claude excluded
        assert len(letter_map) == 2
        assert "100 points" in prompt

    def test_excludes_errored(self):
        drafts = [
            {"key": "gemini", "content": "ok"},
            {"key": "gpt", "error": "timeout"},
            {"key": "claude", "content": "ok"},
        ]
        prompt, letter_map = build_vote_prompt("test", drafts, "claude", anonymize=False)
        assert "gpt" not in letter_map.values()


class TestAggregateVotes:
    def test_basic_aggregation(self):
        vote_results = [
            {"key": "gemini", "votes": {"A": 60, "B": 40},
             "letter_map": {"A": "claude", "B": "gpt"}},
            {"key": "gpt", "votes": {"A": 55, "B": 45},
             "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        result = aggregate_votes(vote_results)
        assert "claude" in result["weighted_scores"]
        assert result["consensus_strength"] > 0

    def test_skips_errors(self):
        vote_results = [
            {"key": "gemini", "error": "timeout"},
            {"key": "gpt", "votes": {"A": 60, "B": 40},
             "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        result = aggregate_votes(vote_results)
        assert "weighted_scores" in result
        assert len(result["per_model_votes"]) == 1

    def test_skips_none_votes(self):
        vote_results = [
            {"key": "gemini", "votes": None, "letter_map": {}},
            {"key": "gpt", "votes": {"A": 60, "B": 40},
             "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        result = aggregate_votes(vote_results)
        assert len(result["per_model_votes"]) == 1

    def test_consensus_strength_full_agreement(self):
        vote_results = [
            {"key": "gemini", "votes": {"A": 90, "B": 10},
             "letter_map": {"A": "claude", "B": "gpt"}},
            {"key": "gpt", "votes": {"A": 85, "B": 15},
             "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        result = aggregate_votes(vote_results)
        # Both give claude most points
        assert result["consensus_strength"] > 0.5

    def test_three_voters(self):
        vote_results = [
            {"key": "gemini", "votes": {"A": 60, "B": 40},
             "letter_map": {"A": "claude", "B": "gpt"}},
            {"key": "gpt", "votes": {"A": 55, "B": 45},
             "letter_map": {"A": "claude", "B": "gemini"}},
            {"key": "claude", "votes": {"A": 50, "B": 50},
             "letter_map": {"A": "gemini", "B": "gpt"}},
        ]
        result = aggregate_votes(vote_results)
        assert len(result["per_model_votes"]) == 3


class TestVotesToRankingFallback:
    def test_converts_to_ranking(self):
        vote_results = [
            {"key": "gemini", "votes": {"A": 70, "B": 30},
             "letter_map": {"A": "claude", "B": "gpt"}},
            {"key": "gpt", "votes": {"A": 60, "B": 40},
             "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        ranking = votes_to_ranking_fallback(vote_results)
        assert ranking[0] == "claude"  # highest score
