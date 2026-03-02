"""Scoring system — EMA-based model performance tracking and leaderboard."""

import json
from datetime import datetime, timezone
from pathlib import Path

_SCORES_VERSION = 1
_DEFAULT_PATH = Path.home() / ".config" / "conclave" / "scores.json"


def _ema(old: float | None, new: float, alpha: float) -> float:
    """Exponential Moving Average. First observation returns raw value."""
    if old is None:
        return new
    return alpha * new + (1 - alpha) * old


def load_scores(path: Path | None = None) -> dict:
    """Load scores from JSON file. Returns empty structure on missing/corrupt/wrong version."""
    p = path or _DEFAULT_PATH
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict) or data.get("version") != _SCORES_VERSION:
            return {"version": _SCORES_VERSION, "members": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": _SCORES_VERSION, "members": {}}


def save_scores(scores: dict, path: Path | None = None) -> None:
    """Write scores JSON, creating parent directories as needed."""
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(scores, indent=2, ensure_ascii=False) + "\n")


def record_round(scores: dict, drafts: list, aggregate_rankings: dict,
                 alpha: float = 0.3) -> dict:
    """Pure function — returns new scores dict with updated per-member stats.

    Updates: participations, errors, avg_latency (EMA), avg_rank (EMA, deep only),
    deep_rounds, last_seen.
    """
    import copy
    new = copy.deepcopy(scores)
    members = new.setdefault("members", {})
    now = datetime.now(timezone.utc).isoformat()

    for draft in drafts:
        key = draft.get("key")
        if not key:
            continue

        entry = members.setdefault(key, {
            "participations": 0,
            "errors": 0,
            "deep_rounds": 0,
            "avg_rank": None,
            "avg_latency": None,
            "last_seen": None,
        })

        entry["participations"] += 1
        entry["last_seen"] = now

        if "error" in draft:
            entry["errors"] += 1

        elapsed = draft.get("elapsed")
        if elapsed is not None and "error" not in draft:
            entry["avg_latency"] = round(
                _ema(entry["avg_latency"], elapsed, alpha), 4
            )

    # Update rankings (deep mode only)
    if aggregate_rankings:
        for key, rank in aggregate_rankings.items():
            entry = members.setdefault(key, {
                "participations": 0,
                "errors": 0,
                "deep_rounds": 0,
                "avg_rank": None,
                "avg_latency": None,
                "last_seen": None,
            })
            entry["deep_rounds"] += 1
            entry["avg_rank"] = round(
                _ema(entry["avg_rank"], rank, alpha), 4
            )

    return new


def get_weights(scores: dict, floor: float = 0.3) -> dict:
    """Return {model_key: weight} — inverts avg_rank, applies floor, normalizes to max=1.0.

    Unranked models get weight 1.0.
    """
    members = scores.get("members", {})
    if not members:
        return {}

    weights = {}
    for key, entry in members.items():
        avg_rank = entry.get("avg_rank")
        if avg_rank is None or avg_rank <= 0:
            weights[key] = 1.0
        else:
            weights[key] = max(floor, 1.0 / avg_rank)

    # Normalize to max=1.0
    if weights:
        max_w = max(weights.values())
        if max_w > 0:
            weights = {k: round(v / max_w, 4) for k, v in weights.items()}

    return weights


def get_leaderboard(scores: dict) -> list[dict]:
    """Sorted list: ranked models by avg_rank asc, then unranked alphabetically."""
    members = scores.get("members", {})
    ranked = []
    unranked = []

    for key, entry in members.items():
        row = {"key": key, **entry}
        if entry.get("avg_rank") is not None:
            ranked.append(row)
        else:
            unranked.append(row)

    ranked.sort(key=lambda r: r["avg_rank"])
    unranked.sort(key=lambda r: r["key"])
    return ranked + unranked


def print_leaderboard(scores: dict) -> None:
    """Pretty-print leaderboard table to stdout."""
    rows = get_leaderboard(scores)
    if not rows:
        print("No scoring data yet. Run a deep conclave to start tracking.")
        return

    print(f"\n{'='*64}")
    print("  CONCLAVE LEADERBOARD")
    print(f"{'='*64}")
    print(f"  {'#':<4} {'Model':<12} {'Avg Rank':<10} {'Deep':<6} {'Runs':<6} {'Errs':<6} {'Latency':<8}")
    print(f"  {'-'*4} {'-'*12} {'-'*10} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")

    for i, row in enumerate(rows, 1):
        rank_str = f"{row['avg_rank']:.2f}" if row.get("avg_rank") is not None else "-"
        latency_str = f"{row['avg_latency']:.1f}s" if row.get("avg_latency") is not None else "-"
        print(f"  {i:<4} {row['key']:<12} {rank_str:<10} {row.get('deep_rounds', 0):<6} "
              f"{row.get('participations', 0):<6} {row.get('errors', 0):<6} {latency_str:<8}")

    print(f"{'='*64}\n")
