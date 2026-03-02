"""Tests for conclave.scoring — EMA, record_round, weights, leaderboard, file I/O."""

import json

from conclave.scoring import (
    _ema,
    get_leaderboard,
    get_weights,
    load_scores,
    print_leaderboard,
    record_round,
    save_scores,
)


# ── Helpers ───────────────────────────────────────────────────────


def _make_drafts(*specs):
    """Build draft list from (key, elapsed) or (key, "error") tuples."""
    drafts = []
    for spec in specs:
        key = spec[0]
        if len(spec) >= 2 and spec[1] == "error":
            drafts.append({"key": key, "error": "timeout", "elapsed": 5.0})
        elif len(spec) >= 2:
            drafts.append({"key": key, "content": "ok", "elapsed": spec[1]})
        else:
            drafts.append({"key": key, "content": "ok"})
    return drafts


def _empty_scores():
    return {"version": 1, "members": {}}


# ── TestEma ──────────────────────────────────────────────────────


class TestEma:
    def test_first_observation_returns_raw(self):
        assert _ema(None, 5.0, 0.3) == 5.0

    def test_updates_with_alpha(self):
        result = _ema(10.0, 20.0, 0.5)
        assert result == 15.0  # 0.5*20 + 0.5*10

    def test_low_alpha_favors_old(self):
        result = _ema(10.0, 20.0, 0.1)
        assert abs(result - 11.0) < 0.001  # 0.1*20 + 0.9*10

    def test_high_alpha_favors_new(self):
        result = _ema(10.0, 20.0, 0.9)
        assert abs(result - 19.0) < 0.001  # 0.9*20 + 0.1*10

    def test_alpha_one_returns_new(self):
        assert _ema(10.0, 20.0, 1.0) == 20.0

    def test_alpha_zero_returns_old(self):
        assert _ema(10.0, 20.0, 0.0) == 10.0


# ── TestRecordRound ──────────────────────────────────────────────


class TestRecordRound:
    def test_increments_participations(self):
        drafts = _make_drafts(("gpt", 2.0), ("gemini", 3.0))
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["participations"] == 1
        assert result["members"]["gemini"]["participations"] == 1

    def test_tracks_errors(self):
        drafts = _make_drafts(("gpt", "error"))
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["errors"] == 1

    def test_error_draft_does_not_update_latency(self):
        drafts = _make_drafts(("gpt", "error"))
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["avg_latency"] is None

    def test_updates_avg_latency_ema(self):
        drafts = _make_drafts(("gpt", 4.0))
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["avg_latency"] == 4.0

        # Second round — EMA update
        drafts2 = _make_drafts(("gpt", 10.0))
        result2 = record_round(result, drafts2, {})
        # alpha=0.3: 0.3*10 + 0.7*4 = 5.8
        assert abs(result2["members"]["gpt"]["avg_latency"] - 5.8) < 0.01

    def test_updates_avg_rank_on_deep(self):
        drafts = _make_drafts(("gpt", 2.0), ("gemini", 3.0))
        rankings = {"gpt": 1.5, "gemini": 2.0}
        result = record_round(_empty_scores(), drafts, rankings)
        assert result["members"]["gpt"]["avg_rank"] == 1.5
        assert result["members"]["gpt"]["deep_rounds"] == 1

    def test_rank_ema_accumulates(self):
        drafts = _make_drafts(("gpt", 2.0))
        r1 = record_round(_empty_scores(), drafts, {"gpt": 1.0})
        r2 = record_round(r1, drafts, {"gpt": 3.0})
        # alpha=0.3: 0.3*3 + 0.7*1 = 1.6
        assert abs(r2["members"]["gpt"]["avg_rank"] - 1.6) < 0.01

    def test_no_rankings_skips_rank_update(self):
        drafts = _make_drafts(("gpt", 2.0))
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["avg_rank"] is None
        assert result["members"]["gpt"]["deep_rounds"] == 0

    def test_sets_last_seen(self):
        drafts = _make_drafts(("gpt", 2.0))
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["last_seen"] is not None

    def test_does_not_mutate_input(self):
        scores = _empty_scores()
        scores["members"]["gpt"] = {
            "participations": 5, "errors": 0, "deep_rounds": 0,
            "avg_rank": None, "avg_latency": 3.0, "last_seen": None,
        }
        drafts = _make_drafts(("gpt", 4.0))
        result = record_round(scores, drafts, {})
        # Original should be unchanged
        assert scores["members"]["gpt"]["participations"] == 5
        assert result["members"]["gpt"]["participations"] == 6

    def test_skips_drafts_without_key(self):
        drafts = [{"content": "ok", "elapsed": 2.0}]  # no key
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"] == {}

    def test_draft_without_elapsed(self):
        drafts = [{"key": "gpt", "content": "ok"}]  # no elapsed
        result = record_round(_empty_scores(), drafts, {})
        assert result["members"]["gpt"]["avg_latency"] is None
        assert result["members"]["gpt"]["participations"] == 1

    def test_custom_alpha(self):
        drafts = _make_drafts(("gpt", 2.0))
        r1 = record_round(_empty_scores(), drafts, {"gpt": 1.0}, alpha=0.5)
        r2 = record_round(r1, drafts, {"gpt": 3.0}, alpha=0.5)
        # alpha=0.5: 0.5*3 + 0.5*1 = 2.0
        assert abs(r2["members"]["gpt"]["avg_rank"] - 2.0) < 0.01

    def test_ranking_creates_member_if_not_in_drafts(self):
        """A model can appear in rankings even if it didn't produce a draft."""
        drafts = _make_drafts(("gpt", 2.0))
        rankings = {"gpt": 1.0, "gemini": 2.0}
        result = record_round(_empty_scores(), drafts, rankings)
        assert "gemini" in result["members"]
        assert result["members"]["gemini"]["avg_rank"] == 2.0


# ── TestGetWeights ───────────────────────────────────────────────


class TestGetWeights:
    def test_empty_scores(self):
        assert get_weights(_empty_scores()) == {}

    def test_unranked_models_get_one(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": None},
        }}
        w = get_weights(scores)
        assert w["gpt"] == 1.0

    def test_best_rank_gets_highest_weight(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 1.0},
            "gemini": {"avg_rank": 2.0},
            "claude": {"avg_rank": 3.0},
        }}
        w = get_weights(scores)
        assert w["gpt"] >= w["gemini"] >= w["claude"]

    def test_top_model_normalized_to_one(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 1.0},
            "gemini": {"avg_rank": 2.0},
        }}
        w = get_weights(scores)
        assert w["gpt"] == 1.0

    def test_floor_applied(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 1.0},
            "bad": {"avg_rank": 100.0},
        }}
        w = get_weights(scores, floor=0.3)
        assert w["bad"] >= 0.3

    def test_custom_floor(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 1.0},
            "bad": {"avg_rank": 100.0},
        }}
        w = get_weights(scores, floor=0.5)
        assert w["bad"] >= 0.5

    def test_single_ranked_model(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 2.0},
        }}
        w = get_weights(scores)
        assert w["gpt"] == 1.0  # normalized to max=1.0


# ── TestGetLeaderboard ───────────────────────────────────────────


class TestGetLeaderboard:
    def test_empty_scores(self):
        assert get_leaderboard(_empty_scores()) == []

    def test_ranked_sorted_by_avg_rank(self):
        scores = {"version": 1, "members": {
            "gemini": {"avg_rank": 2.0, "participations": 5},
            "gpt": {"avg_rank": 1.0, "participations": 5},
        }}
        lb = get_leaderboard(scores)
        assert lb[0]["key"] == "gpt"
        assert lb[1]["key"] == "gemini"

    def test_unranked_sorted_alphabetically(self):
        scores = {"version": 1, "members": {
            "claude": {"avg_rank": None},
            "alpha": {"avg_rank": None},
        }}
        lb = get_leaderboard(scores)
        assert lb[0]["key"] == "alpha"
        assert lb[1]["key"] == "claude"

    def test_ranked_before_unranked(self):
        scores = {"version": 1, "members": {
            "alpha": {"avg_rank": None},
            "gpt": {"avg_rank": 1.5},
        }}
        lb = get_leaderboard(scores)
        assert lb[0]["key"] == "gpt"
        assert lb[1]["key"] == "alpha"

    def test_includes_all_fields(self):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 1.5, "participations": 10, "errors": 1,
                     "deep_rounds": 5, "avg_latency": 3.2, "last_seen": "2026-01-01"},
        }}
        lb = get_leaderboard(scores)
        assert lb[0]["participations"] == 10
        assert lb[0]["avg_latency"] == 3.2


# ── TestFileIO ───────────────────────────────────────────────────


class TestFileIO:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "scores.json"
        scores = {"version": 1, "members": {"gpt": {"avg_rank": 1.5}}}
        save_scores(scores, path)
        loaded = load_scores(path)
        assert loaded == scores

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "missing.json"
        result = load_scores(path)
        assert result == {"version": 1, "members": {}}

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")
        result = load_scores(path)
        assert result == {"version": 1, "members": {}}

    def test_load_wrong_version(self, tmp_path):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({"version": 999, "members": {}}))
        result = load_scores(path)
        assert result == {"version": 1, "members": {}}

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "scores.json"
        save_scores({"version": 1, "members": {}}, path)
        assert path.exists()

    def test_load_non_dict(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text(json.dumps([1, 2, 3]))
        result = load_scores(path)
        assert result == {"version": 1, "members": {}}


# ── TestPrintLeaderboard ─────────────────────────────────────────


class TestPrintLeaderboard:
    def test_empty_prints_no_data(self, capsys):
        print_leaderboard(_empty_scores())
        out = capsys.readouterr().out
        assert "No scoring data" in out

    def test_prints_table(self, capsys):
        scores = {"version": 1, "members": {
            "gpt": {"avg_rank": 1.5, "participations": 10, "errors": 1,
                     "deep_rounds": 5, "avg_latency": 3.2, "last_seen": "2026-01-01"},
            "gemini": {"avg_rank": 2.0, "participations": 8, "errors": 0,
                       "deep_rounds": 4, "avg_latency": 4.5, "last_seen": "2026-01-01"},
        }}
        print_leaderboard(scores)
        out = capsys.readouterr().out
        assert "LEADERBOARD" in out
        assert "gpt" in out
        assert "gemini" in out

    def test_unranked_shows_dash(self, capsys):
        scores = {"version": 1, "members": {
            "claude": {"avg_rank": None, "participations": 3, "errors": 0,
                       "deep_rounds": 0, "avg_latency": None, "last_seen": "2026-01-01"},
        }}
        print_leaderboard(scores)
        out = capsys.readouterr().out
        assert "-" in out  # rank and latency shown as dash
