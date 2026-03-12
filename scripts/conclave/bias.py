"""Bias & Impartiality Metrics — tracks voting patterns across runs."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import _load_env_file, _env

BIAS_FILE = Path.home() / ".config" / "conclave" / "bias.json"


def is_tracking_enabled() -> bool:
    """Check if bias tracking is enabled via env config."""
    env_file = _load_env_file()
    val = _env("CONCLAVE_BIAS_TRACKING", env_file, "true")
    return val.lower() != "false"


def load_bias_data() -> dict:
    """Load bias data from file. Returns empty structure on missing/corrupt file."""
    if not BIAS_FILE.exists():
        return {"runs": []}
    try:
        with open(BIAS_FILE) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "runs" not in data:
            return {"runs": []}
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        return {"runs": []}


def save_bias_data(data: dict) -> None:
    """Save bias data to file."""
    BIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BIAS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def record_vote_run(prompt: str, mode: str, per_model_votes: dict[str, dict[str, int]],
                    consensus_strength: float) -> None:
    """Record a voting run to bias.json."""
    if not is_tracking_enabled():
        return

    data = load_bias_data()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "topic_hint": prompt[:50],
        "votes": per_model_votes,
        "consensus_strength": consensus_strength,
    }
    data["runs"].append(entry)
    save_bias_data(data)


def record_dialogue_run(prompt: str, rounds_completed: int,
                        converged_at: Optional[int],
                        consensus_strength: float) -> None:
    """Record a dialogue run to bias.json."""
    if not is_tracking_enabled():
        return

    data = load_bias_data()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dialogue",
        "topic_hint": prompt[:50],
        "rounds_completed": rounds_completed,
        "converged_at": converged_at,
        "consensus_strength": consensus_strength,
    }
    data["runs"].append(entry)
    save_bias_data(data)


def compute_metrics(data: dict) -> dict:
    """Compute bias & impartiality metrics from stored run data.

    Returns:
        {
            "total_runs": int,
            "per_model": {model: {"avg_points_given": float, "avg_points_received": float,
                                   "convergence_rate": float}},
            "avg_consensus_by_mode": {mode: float},
            "most_contested_run": {...} | None,
        }
    """
    runs = data.get("runs", [])
    if not runs:
        return {
            "total_runs": 0,
            "per_model": {},
            "avg_consensus_by_mode": {},
            "most_contested_run": None,
        }

    # Per-model stats
    points_given: dict[str, list[float]] = {}      # model → list of avg points given to others
    points_received: dict[str, list[float]] = {}    # model → list of points received
    convergence_counts: dict[str, dict] = {}        # model → {"converge": n, "total": n}

    # Consensus by mode
    consensus_by_mode: dict[str, list[float]] = {}
    most_contested = None
    lowest_consensus = 1.0

    for run in runs:
        mode = run.get("mode", "unknown")
        cs = run.get("consensus_strength", 0)

        if mode not in consensus_by_mode:
            consensus_by_mode[mode] = []
        consensus_by_mode[mode].append(cs)

        if cs < lowest_consensus:
            lowest_consensus = cs
            most_contested = run

        votes = run.get("votes", {})
        for voter, voted in votes.items():
            if voter not in points_given:
                points_given[voter] = []
            if isinstance(voted, dict):
                vals = list(voted.values())
                if vals:
                    points_given[voter].append(sum(vals) / len(vals))
                for target, pts in voted.items():
                    if target not in points_received:
                        points_received[target] = []
                    points_received[target].append(pts)

    # Build per-model summary
    all_models = set(points_given.keys()) | set(points_received.keys())
    per_model = {}
    for model in sorted(all_models):
        given = points_given.get(model, [])
        received = points_received.get(model, [])
        per_model[model] = {
            "avg_points_given": round(sum(given) / len(given), 1) if given else 0.0,
            "avg_points_received": round(sum(received) / len(received), 1) if received else 0.0,
        }

    avg_consensus = {
        mode: round(sum(vals) / len(vals), 3) if vals else 0.0
        for mode, vals in consensus_by_mode.items()
    }

    return {
        "total_runs": len(runs),
        "per_model": per_model,
        "avg_consensus_by_mode": avg_consensus,
        "most_contested_run": most_contested,
    }


def print_bias_report(data: dict) -> None:
    """Pretty-print bias metrics to stderr."""
    out = sys.stderr
    metrics = compute_metrics(data)

    print(f"\n{'═'*56}", file=out)
    print(f"  📊 CONCLAVE — Bias & Impartiality Report", file=out)
    print(f"{'═'*56}", file=out)
    print(f"  Total runs tracked: {metrics['total_runs']}", file=out)

    if not metrics["per_model"]:
        print(f"\n  No voting data recorded yet.", file=out)
        print(f"  Run with --vote to start tracking.", file=out)
        print(f"{'═'*56}\n", file=out)
        return

    print(f"\n{'─'*56}", file=out)
    print(f"  Per-Model Statistics", file=out)
    print(f"{'─'*56}", file=out)
    for model, stats in metrics["per_model"].items():
        avg_given = stats["avg_points_given"]
        avg_received = stats["avg_points_received"]
        print(f"  {model:12s}  avg given: {avg_given:5.1f}  avg received: {avg_received:5.1f}", file=out)

    print(f"\n{'─'*56}", file=out)
    print(f"  Consensus by Mode", file=out)
    print(f"{'─'*56}", file=out)
    for mode, avg in metrics["avg_consensus_by_mode"].items():
        print(f"  {mode:12s}  avg consensus: {avg:.3f}", file=out)

    if metrics["most_contested_run"]:
        run = metrics["most_contested_run"]
        print(f"\n{'─'*56}", file=out)
        print(f"  Most Contested Run", file=out)
        print(f"{'─'*56}", file=out)
        print(f"  Topic:     {run.get('topic_hint', '?')}", file=out)
        print(f"  Mode:      {run.get('mode', '?')}", file=out)
        print(f"  Consensus: {run.get('consensus_strength', '?')}", file=out)
        print(f"  Date:      {run.get('timestamp', '?')}", file=out)

    print(f"{'═'*56}\n", file=out)
