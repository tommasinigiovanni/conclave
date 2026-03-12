"""CLI entry point — argparse, pretty printing, session listing."""

import argparse
import asyncio
import json
import sys

from .bias import load_bias_data, print_bias_report
from .config import load_config
from .cost import estimate_cost, print_estimate
from .orchestrator import doctor, run_conclave, run_phase2_only
from .scoring import load_scores, print_leaderboard
from .sessions import _SessionStore


def print_pretty(result: dict) -> None:
    d = result["depth"]
    emoji = {"quick": "⚡", "standard": "🏛️", "deep": "🔥"}.get(d, "🏛️")
    label = {"quick": "Quick", "standard": "Standard", "deep": "Deep Debate"}.get(d, d)
    s = result["summary"]

    print(f"\n{'═'*64}")
    print(f"  {emoji}  CONCLAVE — {label.upper()}")
    print(f"{'═'*64}")
    p = result["prompt"]
    print(f"  Prompt:    {p[:72]}{'...' if len(p) > 72 else ''}")
    print(f"  Members:   {s['api_calls']} api, {s['local']} local, {s['failed']} failed")
    if d == "deep":
        print(f"  Critiques: {s['critiques']} completed")
        if result.get("aggregate_rankings"):
            rank_str = "  |  ".join(f"{k}: #{v}" for k, v in result["aggregate_rankings"].items())
            print(f"  Rankings:  {rank_str}")
    print(f"  Time:      {result['total_elapsed_seconds']}s")
    print(f"{'═'*64}\n")

    print("─── PHASE 1: Independent Drafts ───\n")
    for dr in result["phase1_drafts"]:
        icon = dr.get("icon", "")
        lbl = dr.get("label", dr.get("key", "?"))
        if "error" in dr:
            print(f"  ❌ {icon} {lbl} — {dr['error']}\n")
        elif dr.get("needs_claude_code"):
            print(f"  🏠 {icon} {lbl} — awaiting Claude Code\n")
        else:
            tok = f" · {dr.get('tokens', '?')} tok" if dr.get("tokens") else ""
            print(f"  ✅ {icon} {lbl} ({dr['elapsed']}s{tok})")
            c = dr["content"]
            preview = c[:400] + "..." if len(c) > 400 else c
            for line in preview.split("\n"):
                print(f"     {line}")
            print()

    if result.get("fallacies") and any(result["fallacies"].values()):
        _SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
        _SEVERITY_LABEL = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
        print("─── LOGICAL ANALYSIS ───\n")
        for dr in result["phase1_drafts"]:
            key = dr.get("key", "")
            icon = dr.get("icon", "")
            lbl = dr.get("label", key)
            items = result["fallacies"].get(key, [])
            if not items:
                print(f"  {icon} {lbl} — no fallacies detected\n")
                continue
            print(f"  {icon} {lbl} — {len(items)} fallac{'y' if len(items) == 1 else 'ies'} detected")
            items_sorted = sorted(items, key=lambda x: _SEVERITY_ORDER.get(x.get("severity", "low"), 3))
            for it in items_sorted:
                sev = _SEVERITY_LABEL.get(it["severity"], it["severity"].upper())
                ftype = it["type"].replace("_", " ").title()
                print(f"    [{sev}] {ftype}")
                print(f"      Quote: \"{it['quote']}\"")
                print(f"      -> {it['explanation']}")
            print()

    if result["phase2_critiques"]:
        print("─── PHASE 2: Anonymized Cross-Critique ───\n")
        for cr in result["phase2_critiques"]:
            icon = cr.get("icon", "")
            lbl = cr.get("label", cr.get("key", "?"))
            if "error" in cr:
                print(f"  ❌ {icon} {lbl} critique — {cr['error']}\n")
            elif cr.get("needs_claude_code"):
                print(f"  🏠 {icon} {lbl} critique — awaiting Claude Code\n")
            else:
                rank = cr.get("ranking", [])
                rank_str = f" → Ranking: {', '.join(rank)}" if rank else ""
                print(f"  💬 {icon} {lbl} ({cr['elapsed']}s){rank_str}")
                c = cr["content"]
                preview = c[:400] + "..." if len(c) > 400 else c
                for line in preview.split("\n"):
                    print(f"     {line}")
                print()

    if result.get("vote_results"):
        print("─── VOTING: Quorum Point Distribution ───\n")
        for vr in result["vote_results"]:
            icon = vr.get("icon", "")
            lbl = vr.get("label", vr.get("key", "?"))
            if "error" in vr:
                print(f"  ❌ {icon} {lbl} — {vr['error']}\n")
            elif vr.get("needs_claude_code"):
                print(f"  🏠 {icon} {lbl} — awaiting Claude Code\n")
            else:
                votes = vr.get("votes")
                if votes:
                    letter_map = vr.get("letter_map", {})
                    vote_str = ", ".join(f"{letter_map.get(l, l)}: {p}pts"
                                        for l, p in sorted(votes.items()))
                    print(f"  🗳️  {icon} {lbl} → {vote_str}")
                else:
                    print(f"  ⚠️  {icon} {lbl} — vote parse failed")
            print()
        va = result.get("vote_aggregation", {})
        if va.get("weighted_scores"):
            print("  Weighted Scores:")
            for model, score in va["weighted_scores"].items():
                print(f"    {model}: {score} pts")
            print(f"  Consensus Strength: {va.get('consensus_strength', 0):.1%}\n")

    if result.get("dialogue", {}).get("rounds"):
        dia = result["dialogue"]
        print(f"─── DIALOGUE: {dia.get('total_rounds', 0)} rounds ───\n")
        if dia.get("converged_at"):
            print(f"  Converged at round {dia['converged_at']}\n")
        for rd in dia["rounds"]:
            print(f"  Round {rd['round']}:")
            for r in rd["responses"]:
                icon = r.get("icon", "")
                lbl = r.get("label", r.get("key", "?"))
                stance = r.get("stance", "?")
                if "error" in r:
                    print(f"    ❌ {icon} {lbl} — {r['error']}")
                else:
                    print(f"    {icon} {lbl} [{stance}]")
            print()

    print(f"{'═'*64}")
    print("  ⬆️  Full data in JSON — Claude Code synthesizes from here")
    print(f"{'═'*64}\n")


def _print_session_list() -> None:
    """Print all saved sessions to stderr and exit."""
    store = _SessionStore()
    sessions = store.list_sessions()
    if not sessions:
        print("No saved sessions.", file=sys.stderr)
        sys.exit(0)
    print(f"\n{'─'*60}", file=sys.stderr)
    print("  Saved sessions", file=sys.stderr)
    print(f"{'─'*60}", file=sys.stderr)
    for s in sessions:
        turns = s["turns"]
        print(f"  {s['id']}  ({turns} turn{'s' if turns != 1 else ''})  {s['preview']}", file=sys.stderr)
    print(f"{'─'*60}\n", file=sys.stderr)
    sys.exit(0)


def main():
    # ── Handle special commands before argparse ──
    if len(sys.argv) >= 2 and sys.argv[1] == "doctor":
        cfg = load_config()
        results = asyncio.run(doctor(cfg))
        print("\n🩺 Conclave Health Check\n")
        for r in results:
            print(f"  {r['icon']} {r['member']}: {r['status']}")
        print()
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "leaderboard":
        print_leaderboard(load_scores())
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "bias":
        data = load_bias_data()
        print_bias_report(data)
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "sessions":
        _print_session_list()

    if len(sys.argv) >= 3 and sys.argv[1] == "phase2":
        filepath = sys.argv[2]
        raw = "--raw" in sys.argv
        quiet = "--quiet" in sys.argv or "-q" in sys.argv
        try:
            with open(filepath) as f:
                phase1_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"Cannot read phase1 file: {exc}"}),
                  file=sys.stderr)
            sys.exit(1)
        if not phase1_data.get("phase2_pending"):
            print(json.dumps({"error": "phase2_pending is not true in input"}),
                  file=sys.stderr)
            sys.exit(1)
        if not phase1_data.get("effective_prompt"):
            print(json.dumps({"error": "effective_prompt missing in input"}),
                  file=sys.stderr)
            sys.exit(1)
        result = asyncio.run(run_phase2_only(phase1_data, quiet=quiet))
        if raw:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print_pretty(result)
            print("JSON_OUTPUT_START")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print("JSON_OUTPUT_END")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Conclave — Multi-LLM Council with anonymized debate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  conclave.py "What is the CAP theorem?" --depth quick
  conclave.py "Review this architecture" --depth deep
  conclave.py --members claude,gemini "Explain monads"
  conclave.py --session new "What is CAP?"
  conclave.py --session last "Now explain PACELC"
  conclave.py --session 20260301-143022 "And Raft consensus?"
  conclave.py "Compare approaches" --vote
  conclave.py "Debate this" --rounds 3
  conclave.py "Debate this" --rounds 2 --vote
  conclave.py bias
  conclave.py phase2 /path/to/phase1.json --raw
  conclave.py sessions
  conclave.py leaderboard
  conclave.py doctor
        """,
    )
    parser.add_argument("prompt", help="Prompt for the council")
    parser.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    parser.add_argument("--members", default=None, help="Comma-separated member keys")
    parser.add_argument("--system", default=None, help="System prompt for all models")
    parser.add_argument("--raw", action="store_true", help="JSON only")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress stderr progress")
    parser.add_argument("--estimate", action="store_true",
                        help="Estimate cost and exit without calling APIs")
    parser.add_argument("--session", default=None, metavar="ID",
                        help="Multi-turn session: 'new', 'last', or a session ID")
    parser.add_argument("--vote", action="store_true",
                        help="Use quorum voting (point distribution) instead of ordinal ranking")
    parser.add_argument("--rounds", type=int, default=None, metavar="N",
                        help="Number of dialogue rounds (default: 1, no dialogue)")
    parser.add_argument("--fallacies", "-f", action="store_true",
                        help="Enable fallacy detection (analyzes responses for logical fallacies)")

    args = parser.parse_args()
    cfg = load_config()

    member_keys = [m.strip() for m in args.members.split(",")] if args.members else None

    # ── Resolve effective depth for estimation ──
    effective_depth = args.depth
    if args.vote:
        effective_depth = "deep"  # vote mode has same cost profile as deep

    # ── Estimate mode: print cost and exit ──
    if args.estimate:
        members = cfg.get("council_members", [])
        if member_keys:
            members = [m for m in members if m["key"] in member_keys]
        est = estimate_cost(args.prompt, effective_depth, members, cfg,
                            rounds=args.rounds, vote=args.vote,
                            fallacies=args.fallacies)
        if args.raw:
            print(json.dumps(est, indent=2, ensure_ascii=False))
        else:
            print_estimate(est, effective_depth, rounds=args.rounds, vote=args.vote,
                          fallacies=args.fallacies)
        sys.exit(0)

    # ── Resolve session ──
    session = None
    if args.session:
        store = _SessionStore()
        session = store.resolve(args.session)

    # ── CLI flag overrides ──
    if args.fallacies:
        cfg["fallacy_detection"] = True

    result = asyncio.run(run_conclave(
        prompt=args.prompt,
        depth=args.depth,
        system=args.system,
        member_keys=member_keys,
        cfg=cfg,
        quiet=args.quiet,
        session=session,
        vote=args.vote,
        rounds=args.rounds,
    ))

    if args.raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_pretty(result)
        print("JSON_OUTPUT_START")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("JSON_OUTPUT_END")
