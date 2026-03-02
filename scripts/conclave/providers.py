"""HTTP helpers and provider-specific API callers."""

import asyncio
import random
import time
from typing import Optional

import httpx


async def _post(url: str, headers: dict, body: dict, timeout: int = 120,
                max_retries: int = 3, retry_base_delay: float = 1.0,
                *, client: httpx.AsyncClient | None = None) -> dict:
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout)
    last_exc: Exception | None = None
    try:
        for attempt in range(max_retries + 1):
            try:
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
    finally:
        if owns_client:
            await client.aclose()


async def _call_anthropic(prompt: str, model: str, system: Optional[str],
                          api_key: str, temp: float, max_tok: int, timeout: int,
                          max_retries: int = 3, retry_base_delay: float = 1.0,
                          *, client: httpx.AsyncClient | None = None) -> dict:
    body: dict = {
        "model": model, "max_tokens": max_tok, "temperature": temp,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    data = await _post("https://api.anthropic.com/v1/messages", {
        "x-api-key": api_key, "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, body, timeout, max_retries, retry_base_delay, client=client)
    text = "\n".join((b.get("text") or "") for b in data.get("content", []) if b.get("type") == "text")
    usage = data.get("usage", {})
    return {"content": text, "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "model": data.get("model", model)}


async def _call_gemini(prompt: str, model: str, system: Optional[str],
                       api_key: str, temp: float, max_tok: int, timeout: int,
                       max_retries: int = 3, retry_base_delay: float = 1.0,
                       *, client: httpx.AsyncClient | None = None) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temp, "maxOutputTokens": max_tok},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = await _post(url, {"content-type": "application/json"}, body, timeout,
                       max_retries, retry_base_delay, client=client)
    candidates = data.get("candidates", [])
    text = ""
    if candidates:
        text = "\n".join((p.get("text") or "") for p in candidates[0].get("content", {}).get("parts", []))
    tokens = data.get("usageMetadata", {}).get("totalTokenCount")
    return {"content": text, "tokens": tokens, "model": model}


async def _call_openai(prompt: str, model: str, system: Optional[str],
                       api_key: str, temp: float, max_tok: int, timeout: int,
                       max_retries: int = 3, retry_base_delay: float = 1.0,
                       *, client: httpx.AsyncClient | None = None) -> dict:
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
    }, body, timeout, max_retries, retry_base_delay, client=client)
    choices = data.get("choices", [])
    text = (choices[0]["message"].get("content") or "") if choices else ""
    tokens = data.get("usage", {}).get("total_tokens")
    return {"content": text, "tokens": tokens, "model": data.get("model", model)}


async def _call_xai(prompt: str, model: str, system: Optional[str],
                    api_key: str, temp: float, max_tok: int, timeout: int,
                    max_retries: int = 3, retry_base_delay: float = 1.0,
                    *, client: httpx.AsyncClient | None = None) -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict = {"model": model, "messages": messages,
                  "temperature": temp, "max_tokens": max_tok}
    data = await _post("https://api.x.ai/v1/chat/completions", {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    }, body, timeout, max_retries, retry_base_delay, client=client)
    choices = data.get("choices", [])
    text = (choices[0]["message"].get("content") or "") if choices else ""
    tokens = data.get("usage", {}).get("total_tokens")
    return {"content": text, "tokens": tokens, "model": data.get("model", model)}


async def _call_openrouter(prompt: str, model: str, system: Optional[str],
                           api_key: str, temp: float, max_tok: int, timeout: int,
                           max_retries: int = 3, retry_base_delay: float = 1.0,
                           *, client: httpx.AsyncClient | None = None) -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = await _post("https://openrouter.ai/api/v1/chat/completions", {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    }, {"model": model, "messages": messages, "temperature": temp, "max_tokens": max_tok},
        timeout, max_retries, retry_base_delay, client=client)
    choices = data.get("choices", [])
    text = (choices[0]["message"].get("content") or "") if choices else ""
    tokens = data.get("usage", {}).get("total_tokens")
    return {"content": text, "tokens": tokens, "model": model}


async def call_model(member: dict, prompt: str, system: Optional[str],
                     cfg: dict, *, client: httpx.AsyncClient | None = None) -> dict:
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
                                            timeout, max_retries, retry_base_delay, client=client)
        else:
            # Map provider to direct caller
            caller_map = {
                "anthropic": _call_anthropic,
                "google": _call_gemini,
                "openai": _call_openai,
                "xai": _call_xai,
            }
            caller_fn = caller_map.get(provider)
            if not caller_fn:
                # Unknown provider — try OpenRouter as fallback
                api_key = cfg.get("openrouter", {}).get("api_key", "")
                if api_key:
                    result = await _call_openrouter(prompt, member.get("openrouter_model", ""),
                                                    system, api_key, temp, max_tok, timeout,
                                                    max_retries, retry_base_delay, client=client)
                else:
                    return {"error": f"No caller for provider '{provider}' and no OpenRouter key",
                            "elapsed": 0}
            else:
                api_key = cfg.get("direct_keys", {}).get(provider, "")
                if not api_key:
                    return {"error": f"API key for {provider} not set", "elapsed": 0}
                model_id = member.get("direct_model", "")
                result = await caller_fn(prompt, model_id, system, api_key, temp, max_tok,
                                         timeout, max_retries, retry_base_delay, client=client)

        result["elapsed"] = round(time.time() - start, 2)
        return result
    except Exception as e:
        return {"error": str(e), "elapsed": round(time.time() - start, 2)}
