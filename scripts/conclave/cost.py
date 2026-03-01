"""Cost estimation — no API calls needed."""

import sys

# Pricing per million tokens: (input, output).  Approximate / best-effort.
# Models not listed fall back to a conservative default.
_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514":   (3.00,  15.00),
    "claude-opus-4-20250514":     (15.00, 75.00),
    "claude-opus-4.6":            (15.00, 75.00),
    "claude-haiku-4-20250514":    (0.80,  4.00),
    # Google
    "gemini-2.5-pro":             (1.25,  10.00),
    "gemini-2.5-flash":           (0.15,  0.60),
    "gemini-2.0-flash":           (0.10,  0.40),
    "gemini-3.1-pro-preview":     (1.25,  10.00),  # estimated
    # OpenAI
    "gpt-4.1":                    (2.00,  8.00),
    "gpt-4.1-mini":               (0.40,  1.60),
    "gpt-4.1-nano":               (0.10,  0.40),
    "gpt-5.2":                    (2.00,  8.00),    # estimated
    "o4-mini":                    (1.10,  4.40),
    # xAI
    "grok-3":                     (3.00,  15.00),
    "grok-3-mini":                (0.30,  0.50),
}
_DEFAULT_PRICING: tuple[float, float] = (3.00, 15.00)


def _estimate_tokens(text: str) -> int:
    """Rough token count — ~4 chars per token is a reasonable cross-model average."""
    return max(1, len(text) // 4)


def estimate_cost(prompt: str, depth: str, members: list, cfg: dict) -> dict:
    """Estimate cost without making any API calls.

    Returns {members: [...], phase1_total, phase2_total, total, note}.
    """
    defaults = cfg.get("defaults", {})
    max_out = defaults.get("max_tokens", 2048)
    system_text = ""  # system prompt is optional at CLI level; assume modest size
    prompt_tokens = _estimate_tokens(prompt) + _estimate_tokens(system_text)

    remote = [m for m in members if not m.get("local", False)]

    rows = []
    p1_total = 0.0
    for m in remote:
        model = m.get("direct_model", "")
        inp_rate, out_rate = _PRICING.get(model, _DEFAULT_PRICING)
        # Phase 1: input = prompt, output = up to max_tokens
        p1_in_cost = prompt_tokens * inp_rate / 1_000_000
        p1_out_cost = max_out * out_rate / 1_000_000
        p1_cost = p1_in_cost + p1_out_cost
        p1_total += p1_cost
        rows.append({
            "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
            "model": model, "local": False,
            "input_per_m": inp_rate, "output_per_m": out_rate,
            "phase1_est": round(p1_cost, 5),
        })

    local_members = [m for m in members if m.get("local", False)]
    for m in local_members:
        rows.append({
            "key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
            "model": m.get("direct_model", "claude-code"), "local": True,
            "phase1_est": 0.0,
        })

    # Phase 2 (deep only): each remote member reviews N-1 drafts.
    # Input is much larger (original prompt + all other drafts).
    p2_total = 0.0
    if depth == "deep" and len(members) >= 2:
        # Assume each draft is ~max_out tokens long
        drafts_tokens = (len(members) - 1) * max_out + prompt_tokens
        for row in rows:
            if row["local"]:
                row["phase2_est"] = 0.0
                continue
            inp_rate = row["input_per_m"]
            out_rate = row["output_per_m"]
            p2_in_cost = drafts_tokens * inp_rate / 1_000_000
            p2_out_cost = max_out * out_rate / 1_000_000
            p2_cost = p2_in_cost + p2_out_cost
            p2_total += p2_cost
            row["phase2_est"] = round(p2_cost, 5)

    total = p1_total + p2_total
    return {
        "members": rows,
        "phase1_total": round(p1_total, 5),
        "phase2_total": round(p2_total, 5),
        "total": round(total, 5),
        "note": "Estimates assume max output tokens; actual cost is usually lower.",
    }


def print_estimate(est: dict, depth: str) -> None:
    """Pretty-print cost estimate to stderr."""
    out = sys.stderr
    print(f"\n{'─'*52}", file=out)
    print(f"  Cost estimate  (depth={depth})", file=out)
    print(f"{'─'*52}", file=out)

    for r in est["members"]:
        icon = r.get("icon", "")
        label = r["label"]
        model = r["model"]
        if r["local"]:
            print(f"  🏠 {icon} {label:10s}  {model:32s}  free (local)", file=out)
        else:
            p1 = r["phase1_est"]
            line = f"  💰 {icon} {label:10s}  {model:32s}  P1 ${p1:.4f}"
            if "phase2_est" in r:
                p2 = r["phase2_est"]
                line += f"  P2 ${p2:.4f}"
            print(line, file=out)

    print(f"{'─'*52}", file=out)
    parts = [f"Phase 1 ${est['phase1_total']:.4f}"]
    if est["phase2_total"] > 0:
        parts.append(f"Phase 2 ${est['phase2_total']:.4f}")
    parts.append(f"Total ${est['total']:.4f}")
    print(f"  {' · '.join(parts)}", file=out)
    print(f"  {est['note']}", file=out)
    print(f"{'─'*52}\n", file=out)
