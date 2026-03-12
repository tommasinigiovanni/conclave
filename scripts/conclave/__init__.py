"""Conclave — Multi-LLM Council with anonymized debate."""

from .bias import compute_metrics, load_bias_data, print_bias_report, record_vote_run
from .config import load_config
from .fallacies import FALLACIES, detect_all_fallacies, detect_fallacies
from .cost import estimate_cost
from .dialogue import run_dialogue_rounds
from .orchestrator import doctor, run_conclave, run_phase2_only
from .providers import stream_model
from .scoring import get_leaderboard, get_weights, load_scores, print_leaderboard
from .voting import aggregate_votes, parse_vote_response

__all__ = [
    "run_conclave", "run_phase2_only", "load_config", "doctor", "estimate_cost",
    "load_scores", "get_weights", "get_leaderboard", "print_leaderboard",
    # Voting
    "aggregate_votes", "parse_vote_response",
    # Dialogue
    "run_dialogue_rounds",
    # Bias
    "load_bias_data", "compute_metrics", "print_bias_report", "record_vote_run",
    # Streaming
    "stream_model",
    # Fallacies
    "FALLACIES", "detect_fallacies", "detect_all_fallacies",
]
