"""CLI entry point — argparse, pretty printing, session listing."""

import argparse
import asyncio
import json
import sys

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

    args = parser.parse_args()
    cfg = load_config()

    member_keys = [m.strip() for m in args.members.split(",")] if args.members else None

    # ── Estimate mode: print cost and exit ──
    if args.estimate:
        members = cfg.get("council_members", [])
        if member_keys:
            members = [m for m in members if m["key"] in member_keys]
        est = estimate_cost(args.prompt, args.depth, members, cfg)
        if args.raw:
            print(json.dumps(est, indent=2, ensure_ascii=False))
        else:
            print_estimate(est, args.depth)
        sys.exit(0)

    # ── Resolve session ──
    session = None
    if args.session:
        store = _SessionStore()
        session = store.resolve(args.session)

    result = asyncio.run(run_conclave(
        prompt=args.prompt,
        depth=args.depth,
        system=args.system,
        member_keys=member_keys,
        cfg=cfg,
        quiet=args.quiet,
        session=session,
    ))

    if args.raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_pretty(result)
        print("JSON_OUTPUT_START")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("JSON_OUTPUT_END")
