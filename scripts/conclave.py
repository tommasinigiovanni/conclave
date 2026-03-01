#!/usr/bin/env python3
"""
Conclave — Multi-LLM Council with anonymized debate.

Inspired by Karpathy's LLM Council pattern. Features:
  - 3 depth levels: quick / standard / deep
  - Anonymized cross-critique (Phase 2) to prevent favoritism
  - Aggregate ranking across all peer reviews
  - Configurable via .env file (models, keys, settings)
  - Supports OpenRouter (1 key) or direct API keys
  - Graceful degradation when models fail
"""

import argparse
import asyncio
import json
import os
import random
import string
import sys
import time
from pathlib import Path
from typing import Any, Optional


# ──────────────────────────────────────────────────────────────
# Config loader — reads from .env file + environment variables
# ──────────────────────────────────────────────────────────────

def _load_env_file() -> dict[str, str]:
    """Parse .env file into a dict. Does NOT override existing env vars.
    Searches ONLY safe locations (not the skill directory, to avoid
    exposing API keys to LLM agents that can read skill files)."""
    env_vals: dict[str, str] = {}
    search_paths = [
        Path.home() / ".config" / "conclave" / ".env",
        Path(".") / ".env",
    ]
    for p in search_paths:
        if p.exists():
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    # .env values only apply if NOT already in real env
                    if key not in os.environ:
                        env_vals[key] = val
            break  # use first .env found
    return env_vals


def _env(key: str, env_file: dict[str, str], default: str = "") -> str:
    """Get value from: real env var > .env file > default."""
    return os.environ.get(key, env_file.get(key, default))


def _discover_members(env_file: dict[str, str]) -> list[dict]:
    """Auto-discover council members from CONCLAVE_MEMBER_*_MODEL vars."""
    # Collect all keys from both real env and .env file
    all_keys = set(os.environ.keys()) | set(env_file.keys())

    # Find unique member keys: CONCLAVE_MEMBER_<KEY>_MODEL
    member_keys = set()
    for k in all_keys:
        if k.startswith("CONCLAVE_MEMBER_") and k.endswith("_MODEL"):
            member_key = k.replace("CONCLAVE_MEMBER_", "").replace("_MODEL", "")
            member_keys.add(member_key)

    members = []
    for mk in sorted(member_keys):
        prefix = f"CONCLAVE_MEMBER_{mk}_"
        model = _env(f"{prefix}MODEL", env_file)
        if not model:
            continue
        members.append({
            "key": mk.lower(),
            "label": _env(f"{prefix}LABEL", env_file, mk.capitalize()),
            "icon": _env(f"{prefix}ICON", env_file, "⚪"),
            "provider": _env(f"{prefix}PROVIDER", env_file, mk.lower()),
            "direct_model": model,
            "openrouter_model": _env(f"{prefix}OPENROUTER", env_file, model),
            "local": _env(f"{prefix}LOCAL", env_file, "false").lower() == "true",
        })
    return members


def load_config() -> dict:
    """Build config from .env file + environment variables."""
    env_file = _load_env_file()

    members = _discover_members(env_file)

    # Fallback: if no members discovered, use hardcoded defaults
    if not members:
        members = [
            {"key": "claude", "label": "Claude", "icon": "🟣", "provider": "anthropic",
             "direct_model": "claude-sonnet-4-20250514",
             "openrouter_model": "anthropic/claude-sonnet-4-20250514",
             "local": True},
            {"key": "gemini", "label": "Gemini", "icon": "🔵", "provider": "google",
             "direct_model": "gemini-2.0-flash",
             "openrouter_model": "google/gemini-2.0-flash",
             "local": False},
            {"key": "gpt", "label": "GPT", "icon": "🟢", "provider": "openai",
             "direct_model": "gpt-5.2",
             "openrouter_model": "openai/gpt-5.2",
             "local": False},
        ]

    # API keys — build lookup from provider name to key
    direct_keys = {}
    for m in members:
        prov = m["provider"]
        if prov == "anthropic":
            direct_keys["anthropic"] = _env("ANTHROPIC_API_KEY", env_file)
        elif prov == "google":
            direct_keys["google"] = _env("GOOGLE_GEMINI_API_KEY", env_file)
        elif prov == "openai":
            direct_keys["openai"] = _env("OPENAI_API_KEY", env_file)
        elif prov == "xai":
            direct_keys["xai"] = _env("XAI_API_KEY", env_file)

    return {
        "provider_mode": _env("CONCLAVE_PROVIDER_MODE", env_file, "direct"),
        "openrouter": {
            "api_key": _env("OPENROUTER_API_KEY", env_file),
        },
        "direct_keys": direct_keys,
        "council_members": members,
        "defaults": {
            "temperature": float(_env("CONCLAVE_TEMPERATURE", env_file, "0.7")),
            "max_tokens": int(_env("CONCLAVE_MAX_TOKENS", env_file, "2048")),
            "timeout_seconds": int(_env("CONCLAVE_TIMEOUT", env_file, "120")),
            "max_retries": int(_env("CONCLAVE_MAX_RETRIES", env_file, "3")),
            "retry_base_delay": float(_env("CONCLAVE_RETRY_BASE_DELAY", env_file, "1.0")),
        },
        "anonymize_reviews": _env("CONCLAVE_ANONYMIZE", env_file, "true").lower() == "true",
    }


def load_templates() -> dict:
    """Load prompt templates. YAML file is optional — has built-in defaults."""
    defaults = {
        "critique_system": (
            "You are a member of an expert council. Other council members have "
            "responded to the same question. Their identities are hidden.\n\n"
            "Your task:\n"
            "1. Evaluate each response for accuracy, completeness, and reasoning quality\n"
            "2. Identify specific errors, gaps, or weak arguments\n"
            "3. Acknowledge strong points you may have missed in your own thinking\n"
            "4. Provide a FINAL RANKING of the responses (best to worst)\n\n"
            "Be rigorous but constructive. This is peer review, not a competition."
        ),
        "critique_prompt": (
            "## Original Question\n{original_prompt}\n\n"
            "## Council Responses\n\n{anonymized_responses}\n\n---\n\n"
            "Now provide your critique of each response above.\n"
            "End with:\n\nFINAL RANKING:\n1. [Best response letter]\n"
            "2. [Second best]\n3. [Third best]"
        ),
    }
    try:
        import yaml
        paths = [
            Path(__file__).parent.parent / "prompts" / "templates.yaml",
            Path("./prompts/templates.yaml"),
        ]
        for p in paths:
            if p.exists():
                with open(p) as f:
                    loaded = yaml.safe_load(f) or {}
                defaults.update(loaded)
                break
    except ImportError:
        pass  # pyyaml not installed — use built-in defaults
    return defaults


# ──────────────────────────────────────────────────────────────
# HTTP helper
# ──────────────────────────────────────────────────────────────

async def _post(url: str, headers: dict, body: dict, timeout: int = 120,
                max_retries: int = 3, retry_base_delay: float = 1.0) -> dict:
    import httpx
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                last_exc = e
                delay = retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            if attempt < max_retries:
                delay = retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue
            raise
    raise last_exc  # unreachable, but satisfies type checker


# ──────────────────────────────────────────────────────────────
# Provider callers — Direct mode
# ──────────────────────────────────────────────────────────────

async def _call_anthropic(prompt: str, model: str, system: Optional[str],
                          api_key: str, temp: float, max_tok: int, timeout: int,
                          max_retries: int = 3, retry_base_delay: float = 1.0) -> dict:
    body: dict = {
        "model": model, "max_tokens": max_tok, "temperature": temp,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    data = await _post("https://api.anthropic.com/v1/messages", {
        "x-api-key": api_key, "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, body, timeout, max_retries, retry_base_delay)
    text = "\n".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    usage = data.get("usage", {})
    return {"content": text, "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "model": data.get("model", model)}


async def _call_gemini(prompt: str, model: str, system: Optional[str],
                       api_key: str, temp: float, max_tok: int, timeout: int,
                       max_retries: int = 3, retry_base_delay: float = 1.0) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temp, "maxOutputTokens": max_tok},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = await _post(url, {"content-type": "application/json"}, body, timeout,
                       max_retries, retry_base_delay)
    candidates = data.get("candidates", [])
    text = ""
    if candidates:
        text = "\n".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
    tokens = data.get("usageMetadata", {}).get("totalTokenCount")
    return {"content": text, "tokens": tokens, "model": model}


async def _call_openai(prompt: str, model: str, system: Optional[str],
                       api_key: str, temp: float, max_tok: int, timeout: int,
                       max_retries: int = 3, retry_base_delay: float = 1.0) -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Reasoning models (gpt-5.x, o1, o3, o4) don't accept temperature/max_tokens
    is_reasoning = any(model.startswith(p) for p in ("gpt-5", "o1", "o3", "o4"))
    body: dict = {"model": model, "messages": messages}
    if is_reasoning:
        body["max_completion_tokens"] = max_tok
    else:
        body["temperature"] = temp
        body["max_tokens"] = max_tok

    data = await _post("https://api.openai.com/v1/chat/completions", {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    }, body, timeout, max_retries, retry_base_delay)
    choices = data.get("choices", [])
    text = choices[0]["message"]["content"] if choices else ""
    tokens = data.get("usage", {}).get("total_tokens")
    return {"content": text, "tokens": tokens, "model": data.get("model", model)}


async def _call_openrouter(prompt: str, model: str, system: Optional[str],
                           api_key: str, temp: float, max_tok: int, timeout: int,
                           max_retries: int = 3, retry_base_delay: float = 1.0) -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = await _post("https://openrouter.ai/api/v1/chat/completions", {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    }, {"model": model, "messages": messages, "temperature": temp, "max_tokens": max_tok},
        timeout, max_retries, retry_base_delay)
    choices = data.get("choices", [])
    text = choices[0]["message"]["content"] if choices else ""
    tokens = data.get("usage", {}).get("total_tokens")
    return {"content": text, "tokens": tokens, "model": model}



# ──────────────────────────────────────────────────────────────
# Unified caller — routes to direct or OpenRouter
# ──────────────────────────────────────────────────────────────

async def call_model(member: dict, prompt: str, system: Optional[str],
                     cfg: dict) -> dict:
    """Call a single model. Returns {content, tokens, model, elapsed, error?}.
    For local members (local=true), returns a placeholder for Claude Code to fill."""

    # ── Local member: skip API call, return placeholder ──
    if member.get("local", False):
        return {
            "content": "",
            "needs_claude_code": True,
            "prompt": prompt,
            "system": system,
            "model": member.get("direct_model", "claude-code"),
            "tokens": None,
            "elapsed": 0,
        }

    mode = cfg.get("provider_mode", "direct")
    defaults = cfg.get("defaults", {})
    temp = defaults.get("temperature", 0.7)
    max_tok = defaults.get("max_tokens", 2048)
    timeout = defaults.get("timeout_seconds", 120)
    max_retries = defaults.get("max_retries", 3)
    retry_base_delay = defaults.get("retry_base_delay", 1.0)
    key = member["key"]
    provider = member.get("provider", key)

    start = time.time()
    try:
        if mode == "openrouter":
            api_key = cfg.get("openrouter", {}).get("api_key", "")
            if not api_key:
                return {"error": "OPENROUTER_API_KEY not set", "elapsed": 0}
            model_id = member.get("openrouter_model", "")
            result = await _call_openrouter(prompt, model_id, system, api_key, temp, max_tok,
                                            timeout, max_retries, retry_base_delay)
        else:
            # Map provider to direct caller
            caller_map = {
                "anthropic": _call_anthropic,
                "google": _call_gemini,
                "openai": _call_openai,
            }
            caller_fn = caller_map.get(provider)
            if not caller_fn:
                # Unknown provider — try OpenRouter as fallback
                api_key = cfg.get("openrouter", {}).get("api_key", "")
                if api_key:
                    result = await _call_openrouter(prompt, member.get("openrouter_model", ""),
                                                    system, api_key, temp, max_tok, timeout,
                                                    max_retries, retry_base_delay)
                else:
                    return {"error": f"No caller for provider '{provider}' and no OpenRouter key",
                            "elapsed": 0}
            else:
                api_key = cfg.get("direct_keys", {}).get(provider, "")
                if not api_key:
                    return {"error": f"API key for {provider} not set", "elapsed": 0}
                model_id = member.get("direct_model", "")
                result = await caller_fn(prompt, model_id, system, api_key, temp, max_tok,
                                         timeout, max_retries, retry_base_delay)

        result["elapsed"] = round(time.time() - start, 2)
        return result
    except Exception as e:
        return {"error": str(e), "elapsed": round(time.time() - start, 2)}


# ──────────────────────────────────────────────────────────────
# Phase 1: Parallel independent drafts
# ──────────────────────────────────────────────────────────────

async def phase1(prompt: str, system: Optional[str], members: list, cfg: dict) -> list:
    tasks = [call_model(m, prompt, system, cfg) for m in members]
    results = await asyncio.gather(*tasks)
    for m, r in zip(members, results):
        r["key"] = m["key"]
        r["label"] = m["label"]
        r["icon"] = m.get("icon", "")
    return list(results)


# ──────────────────────────────────────────────────────────────
# Phase 2: Anonymized cross-critique with ranking
# ──────────────────────────────────────────────────────────────

LETTERS = list(string.ascii_uppercase)  # A, B, C, ...


def build_critique_prompt(original_prompt: str, drafts: list, exclude_key: str,
                          anonymize: bool, templates: dict) -> tuple[str, dict]:
    """Build critique prompt. Returns (prompt_text, letter_to_key_map)."""
    others = [d for d in drafts if d["key"] != exclude_key and "error" not in d]
    if anonymize:
        random.shuffle(others)  # randomize order to prevent position bias

    letter_map = {}
    sections = []
    for i, d in enumerate(others):
        letter = LETTERS[i]
        letter_map[letter] = d["key"]
        sections.append(f"### Response {letter}\n{d['content']}")

    responses_text = "\n\n---\n\n".join(sections)

    tmpl = templates.get("critique_prompt", "{original_prompt}\n\n{anonymized_responses}")
    prompt_text = tmpl.format(
        original_prompt=original_prompt,
        anonymized_responses=responses_text,
    )
    return prompt_text, letter_map


def parse_ranking(text: str) -> list[str]:
    """Extract FINAL RANKING from critique text. Returns list of letters."""
    ranking = []
    in_ranking = False
    for line in text.split("\n"):
        stripped = line.strip()
        if "FINAL RANKING" in stripped.upper():
            in_ranking = True
            continue
        if in_ranking and stripped:
            # Try to extract letter: "1. Response C" or "1. C"
            for letter in LETTERS:
                if f"Response {letter}" in stripped or stripped.endswith(f". {letter}"):
                    ranking.append(letter)
                    break
    return ranking


def aggregate_rankings(critiques: list) -> dict:
    """Compute average rank per model from all critiques."""
    scores: dict[str, list[float]] = {}
    for c in critiques:
        if "error" in c or "ranking" not in c:
            continue
        letter_map = c.get("letter_map", {})
        for position, letter in enumerate(c["ranking"]):
            model_key = letter_map.get(letter, letter)
            if model_key not in scores:
                scores[model_key] = []
            scores[model_key].append(position + 1)  # 1-indexed

    averages = {}
    for key, positions in scores.items():
        averages[key] = round(sum(positions) / len(positions), 2)
    return dict(sorted(averages.items(), key=lambda x: x[1]))


async def phase2(original_prompt: str, drafts: list, members: list,
                 cfg: dict, templates: dict) -> list:
    """Anonymized cross-critique with ranking."""
    anonymize = cfg.get("anonymize_reviews", True)
    system = templates.get("critique_system", "You are a peer reviewer in an expert council.")

    ok_drafts = [d for d in drafts if "error" not in d]
    if len(ok_drafts) < 2:
        return []

    tasks = []
    meta = []
    for m in members:
        if any(d["key"] == m["key"] and "error" in d for d in drafts):
            continue
        prompt_text, letter_map = build_critique_prompt(
            original_prompt, drafts, m["key"], anonymize, templates)
        tasks.append(call_model(m, prompt_text, system, cfg))
        meta.append({"key": m["key"], "label": m["label"], "icon": m.get("icon", ""),
                      "letter_map": letter_map})

    results = await asyncio.gather(*tasks)
    critiques = []
    for r, m in zip(results, meta):
        r.update(m)
        if "error" not in r and "content" in r:
            r["ranking"] = parse_ranking(r["content"])
        critiques.append(r)

    return critiques


# ──────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────

async def doctor(cfg: dict) -> list[dict]:
    """Quick health check — send a tiny prompt to each model."""
    members = cfg.get("council_members", [])
    # Only test non-local members (local ones run in Claude Code)
    remote_members = [m for m in members if not m.get("local", False)]
    local_members = [m for m in members if m.get("local", False)]

    prompt = "Reply with exactly: OK"
    tasks = [call_model(m, prompt, None, cfg) for m in remote_members]
    results = await asyncio.gather(*tasks)
    report = []
    for m in local_members:
        report.append({"member": m["label"], "icon": m.get("icon", ""),
                        "status": "🏠 Local (Claude Code)"})
    for m, r in zip(remote_members, results):
        status = "❌ " + r.get("error", "unknown") if "error" in r else f"✅ {r['elapsed']}s"
        report.append({"member": m["label"], "icon": m.get("icon", ""), "status": status})
    return report


# ──────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────

async def run_conclave(prompt: str, depth: str = "standard",
                       system: Optional[str] = None,
                       member_keys: Optional[list[str]] = None,
                       cfg: Optional[dict] = None) -> dict:
    cfg = cfg or load_config()
    templates = load_templates()
    total_start = time.time()

    members = cfg.get("council_members", [])
    if member_keys:
        members = [m for m in members if m["key"] in member_keys]

    # ── Phase 1 ──
    drafts = await phase1(prompt, system, members, cfg)
    local_count = sum(1 for d in drafts if d.get("needs_claude_code", False))
    api_ok_count = sum(1 for d in drafts if "error" not in d and not d.get("needs_claude_code", False))
    fail_count = sum(1 for d in drafts if "error" in d)

    # ── Phase 2 (deep only) ──
    critiques = []
    rankings = {}
    # Need at least 2 members with content (API responses) for cross-critique
    if depth == "deep" and (api_ok_count + local_count) >= 2:
        critiques = await phase2(prompt, drafts, members, cfg, templates)
        rankings = aggregate_rankings(critiques)

    output = {
        "prompt": prompt,
        "system": system,
        "depth": depth,
        "total_elapsed_seconds": round(time.time() - total_start, 2),
        "phase1_drafts": drafts,
        "phase2_critiques": critiques,
        "aggregate_rankings": rankings,
        "summary": {
            "models_queried": len(drafts),
            "api_calls": api_ok_count,
            "local": local_count,
            "failed": fail_count,
            "critiques": len([c for c in critiques if "error" not in c]),
        },
    }
    return output


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

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


def main():
    # ── Handle "doctor" before argparse to avoid subparser conflicts ──
    if len(sys.argv) >= 2 and sys.argv[1] == "doctor":
        cfg = load_config()
        results = asyncio.run(doctor(cfg))
        print("\n🩺 Conclave Health Check\n")
        for r in results:
            print(f"  {r['icon']} {r['member']}: {r['status']}")
        print()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Conclave — Multi-LLM Council with anonymized debate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  conclave.py "What is the CAP theorem?" --depth quick
  conclave.py "Review this architecture" --depth deep
  conclave.py --members claude,gemini "Explain monads"
  conclave.py doctor
        """,
    )
    parser.add_argument("prompt", help="Prompt for the council")
    parser.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    parser.add_argument("--members", default=None, help="Comma-separated member keys")
    parser.add_argument("--system", default=None, help="System prompt for all models")
    parser.add_argument("--raw", action="store_true", help="JSON only")

    args = parser.parse_args()
    cfg = load_config()

    member_keys = [m.strip() for m in args.members.split(",")] if args.members else None

    result = asyncio.run(run_conclave(
        prompt=args.prompt,
        depth=args.depth,
        system=args.system,
        member_keys=member_keys,
        cfg=cfg,
    ))

    if args.raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_pretty(result)
        print("JSON_OUTPUT_START")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("JSON_OUTPUT_END")


if __name__ == "__main__":
    main()
