"""Tests for conclave.bias — bias tracking and metrics."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from conclave.bias import (
    compute_metrics,
    is_tracking_enabled,
    load_bias_data,
    record_vote_run,
    save_bias_data,
)


@pytest.fixture
def tmp_bias_file(tmp_path):
    """Redirect BIAS_FILE to a temp location."""
    bias_file = tmp_path / "bias.json"
    with patch("conclave.bias.BIAS_FILE", bias_file):
        yield bias_file


class TestLoadBiasData:
    def test_returns_empty_on_missing_file(self, tmp_bias_file):
        assert not tmp_bias_file.exists()
        result = load_bias_data()
        assert result == {"runs": []}

    def test_loads_valid_file(self, tmp_bias_file):
        data = {"runs": [{"mode": "vote", "consensus_strength": 0.7}]}
        tmp_bias_file.write_text(json.dumps(data))
        result = load_bias_data()
        assert len(result["runs"]) == 1

    def test_handles_corrupt_file(self, tmp_bias_file):
        tmp_bias_file.write_text("not json{{{")
        result = load_bias_data()
        assert result == {"runs": []}

    def test_handles_missing_runs_key(self, tmp_bias_file):
        tmp_bias_file.write_text('{"other": true}')
        result = load_bias_data()
        assert result == {"runs": []}


class TestSaveBiasData:
    def test_creates_file(self, tmp_bias_file):
        data = {"runs": [{"mode": "vote"}]}
        save_bias_data(data)
        assert tmp_bias_file.exists()
        loaded = json.loads(tmp_bias_file.read_text())
        assert loaded == data


class TestRecordVoteRun:
    def test_appends_to_file(self, tmp_bias_file):
        with patch("conclave.bias.is_tracking_enabled", return_value=True):
            record_vote_run("test prompt", "vote",
                            {"gemini": {"claude": 60, "gpt": 40}}, 0.68)
            record_vote_run("another prompt", "vote",
                            {"gpt": {"claude": 55}}, 0.55)

        data = load_bias_data()
        assert len(data["runs"]) == 2
        assert data["runs"][0]["mode"] == "vote"
        assert data["runs"][0]["topic_hint"] == "test prompt"[:50]
        assert data["runs"][0]["consensus_strength"] == 0.68

    def test_respects_tracking_disabled(self, tmp_bias_file):
        with patch("conclave.bias.is_tracking_enabled", return_value=False):
            record_vote_run("test", "vote", {}, 0.5)

        assert not tmp_bias_file.exists()


class TestIsTrackingEnabled:
    def test_default_enabled(self):
        with patch("conclave.bias._load_env_file", return_value={}):
            assert is_tracking_enabled() is True

    def test_disabled_by_env(self):
        with patch("conclave.bias._load_env_file",
                    return_value={"CONCLAVE_BIAS_TRACKING": "false"}):
            assert is_tracking_enabled() is False


class TestComputeMetrics:
    def test_empty_data(self):
        metrics = compute_metrics({"runs": []})
        assert metrics["total_runs"] == 0
        assert metrics["per_model"] == {}

    def test_single_run(self):
        data = {"runs": [{
            "mode": "vote",
            "consensus_strength": 0.68,
            "votes": {
                "gemini": {"claude": 60, "gpt": 40},
                "gpt": {"claude": 55, "gemini": 45},
            },
        }]}
        metrics = compute_metrics(data)
        assert metrics["total_runs"] == 1
        assert "gemini" in metrics["per_model"]
        assert "gpt" in metrics["per_model"]
        assert "claude" in metrics["per_model"]
        assert metrics["avg_consensus_by_mode"]["vote"] == 0.68

    def test_most_contested_run(self):
        data = {"runs": [
            {"mode": "vote", "consensus_strength": 0.9, "votes": {}},
            {"mode": "vote", "consensus_strength": 0.3, "votes": {}},
            {"mode": "vote", "consensus_strength": 0.7, "votes": {}},
        ]}
        metrics = compute_metrics(data)
        assert metrics["most_contested_run"]["consensus_strength"] == 0.3

    def test_multiple_modes(self):
        data = {"runs": [
            {"mode": "vote", "consensus_strength": 0.8, "votes": {}},
            {"mode": "dialogue", "consensus_strength": 0.6, "votes": {}},
        ]}
        metrics = compute_metrics(data)
        assert "vote" in metrics["avg_consensus_by_mode"]
        assert "dialogue" in metrics["avg_consensus_by_mode"]

    def test_avg_points_given_and_received(self):
        data = {"runs": [{
            "mode": "vote",
            "consensus_strength": 0.7,
            "votes": {
                "gemini": {"claude": 70, "gpt": 30},
            },
        }]}
        metrics = compute_metrics(data)
        # gemini gave avg of (70+30)/2 = 50
        assert metrics["per_model"]["gemini"]["avg_points_given"] == 50.0
        # claude received 70
        assert metrics["per_model"]["claude"]["avg_points_received"] == 70.0
