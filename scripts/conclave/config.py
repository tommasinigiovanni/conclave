"""Configuration loader — reads from .env file + environment variables."""

import os
from pathlib import Path


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
            "Be rigorous but constructive. This is peer review, not a competition.\n\n"
            "IMPORTANT: End your response with a ranking block in exactly this format:\n"
            "FINAL RANKING:\n"
            "1. A\n"
            "2. B\n"
            "3. C\n"
            "Use ONLY the single response letter on each line (A, B, C, etc.), "
            "best first. Do NOT add explanations on the ranking lines."
        ),
        "critique_prompt": (
            "## Original Question\n{original_prompt}\n\n"
            "## Council Responses\n\n{anonymized_responses}\n\n---\n\n"
            "Now provide your critique of each response above.\n"
            "End with your ranking in exactly this format:\n\n"
            "FINAL RANKING:\n"
            "1. A\n"
            "2. B\n"
            "3. C\n\n"
            "(Use only the single response letter per line, best to worst.)"
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
