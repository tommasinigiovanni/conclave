"""Tests for conclave.providers — _post retry logic and call_model routing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from conclave.providers import (
    _post, call_model, _call_openai, _call_openrouter, _call_anthropic, _call_gemini, _call_xai,
)


# ── Helpers ───────────────────────────────────────────────────────


def _make_response(status_code: int, json_data: dict | None = None):
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://fake.api/v1"),
        json=json_data or {},
    )
    return resp


# ── _post: success ────────────────────────────────────────────────


class TestPostSuccess:
    def test_returns_json_on_200(self):
        mock_resp = _make_response(200, {"ok": True})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(_post("https://fake.api/v1", {}, {}, timeout=5, max_retries=0))
        assert result == {"ok": True}


# ── _post: retries on transient HTTP errors ───────────────────────


class TestPostRetryHTTPErrors:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_retries_then_succeeds(self, status_code):
        fail_resp = _make_response(status_code)
        ok_resp = _make_response(200, {"recovered": True})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            httpx.HTTPStatusError("err", request=fail_resp.request, response=fail_resp),
            ok_resp,
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(_post(
                "https://fake.api/v1", {}, {},
                timeout=5, max_retries=2, retry_base_delay=0.01,
            ))
        assert result == {"recovered": True}
        assert mock_client.post.call_count == 2

    def test_exhausts_retries_then_raises(self):
        fail_resp = _make_response(503)
        exc = httpx.HTTPStatusError("err", request=fail_resp.request, response=fail_resp)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=exc)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                asyncio.run(_post(
                    "https://fake.api/v1", {}, {},
                    timeout=5, max_retries=2, retry_base_delay=0.01,
                ))
        # initial + 2 retries = 3 calls
        assert mock_client.post.call_count == 3

    def test_non_retryable_status_raises_immediately(self):
        """4xx errors (except 429) should NOT be retried."""
        fail_resp = _make_response(400)
        exc = httpx.HTTPStatusError("bad req", request=fail_resp.request, response=fail_resp)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=exc)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                asyncio.run(_post(
                    "https://fake.api/v1", {}, {},
                    timeout=5, max_retries=3, retry_base_delay=0.01,
                ))
        assert mock_client.post.call_count == 1  # no retries


# ── _post: retries on network errors ─────────────────────────────


class TestPostRetryNetworkErrors:
    def test_retries_on_timeout(self):
        ok_resp = _make_response(200, {"ok": True})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            httpx.TimeoutException("timed out"),
            ok_resp,
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(_post(
                "https://fake.api/v1", {}, {},
                timeout=5, max_retries=2, retry_base_delay=0.01,
            ))
        assert result == {"ok": True}

    def test_retries_on_connect_error(self):
        ok_resp = _make_response(200, {"ok": True})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            ok_resp,
        ])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(_post(
                "https://fake.api/v1", {}, {},
                timeout=5, max_retries=3, retry_base_delay=0.01,
            ))
        assert result == {"ok": True}
        assert mock_client.post.call_count == 3

    def test_timeout_exhausted_raises(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.TimeoutException):
                asyncio.run(_post(
                    "https://fake.api/v1", {}, {},
                    timeout=5, max_retries=1, retry_base_delay=0.01,
                ))
        assert mock_client.post.call_count == 2


# ── call_model ────────────────────────────────────────────────────


class TestCallModel:
    def _cfg(self, **overrides):
        base = {
            "provider_mode": "direct",
            "direct_keys": {"anthropic": "sk-test", "google": "gk-test", "openai": "ok-test", "xai": "xai-test"},
            "openrouter": {"api_key": ""},
            "defaults": {
                "temperature": 0.7, "max_tokens": 100,
                "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
            },
        }
        base.update(overrides)
        return base

    def test_local_member_returns_placeholder(self):
        member = {"key": "claude", "local": True, "direct_model": "claude-opus-4.6"}
        result = asyncio.run(call_model(member, "hello", None, self._cfg()))
        assert result["needs_claude_code"] is True
        assert result["elapsed"] == 0
        assert result["model"] == "claude-opus-4.6"

    def test_missing_api_key_returns_error(self):
        member = {"key": "gemini", "provider": "google", "local": False,
                  "direct_model": "gemini-2.0-flash"}
        cfg = self._cfg(direct_keys={})  # no keys
        result = asyncio.run(call_model(member, "hello", None, cfg))
        assert "error" in result
        assert "API key" in result["error"]

    def test_unknown_provider_no_openrouter_returns_error(self):
        member = {"key": "llama", "provider": "meta", "local": False,
                  "direct_model": "llama-3"}
        result = asyncio.run(call_model(member, "hello", None, self._cfg()))
        assert "error" in result
        assert "No caller for provider" in result["error"]

    def test_openrouter_mode_missing_key(self):
        member = {"key": "gemini", "provider": "google", "local": False,
                  "openrouter_model": "google/gemini-2.0-flash"}
        cfg = self._cfg(provider_mode="openrouter")
        result = asyncio.run(call_model(member, "hello", None, cfg))
        assert "error" in result
        assert "OPENROUTER_API_KEY" in result["error"]

    def test_routes_to_anthropic(self):
        member = {"key": "claude", "provider": "anthropic", "local": False,
                  "direct_model": "claude-sonnet-4-20250514"}
        with patch("conclave.providers._call_anthropic", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"content": "ok", "tokens": 10, "model": "claude-sonnet-4-20250514"}
            result = asyncio.run(call_model(member, "test", None, self._cfg()))
        assert result["content"] == "ok"
        assert "elapsed" in result
        mock_call.assert_called_once()

    def test_routes_to_gemini(self):
        member = {"key": "gemini", "provider": "google", "local": False,
                  "direct_model": "gemini-2.0-flash"}
        with patch("conclave.providers._call_gemini", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"content": "ok", "tokens": 5, "model": "gemini-2.0-flash"}
            result = asyncio.run(call_model(member, "test", None, self._cfg()))
        assert result["content"] == "ok"
        mock_call.assert_called_once()

    def test_routes_to_xai(self):
        member = {"key": "grok", "provider": "xai", "local": False,
                  "direct_model": "grok-3"}
        with patch("conclave.providers._call_xai", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"content": "ok", "tokens": 12, "model": "grok-3"}
            result = asyncio.run(call_model(member, "test", None, self._cfg()))
        assert result["content"] == "ok"
        mock_call.assert_called_once()

    def test_routes_to_openai(self):
        member = {"key": "gpt", "provider": "openai", "local": False,
                  "direct_model": "gpt-5.2"}
        with patch("conclave.providers._call_openai", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"content": "ok", "tokens": 8, "model": "gpt-5.2"}
            result = asyncio.run(call_model(member, "test", None, self._cfg()))
        assert result["content"] == "ok"
        mock_call.assert_called_once()

    def test_exception_returns_error_with_elapsed(self):
        member = {"key": "gemini", "provider": "google", "local": False,
                  "direct_model": "gemini-2.0-flash"}
        with patch("conclave.providers._call_gemini", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = RuntimeError("boom")
            result = asyncio.run(call_model(member, "test", None, self._cfg()))
        assert "error" in result
        assert "boom" in result["error"]
        assert "elapsed" in result


# ── Null content handling ────────────────────────────────────────


class TestNullContentHandling:
    """Reasoning models (gpt-5.x, o1, etc.) may return content: null."""

    def test_openai_null_content_returns_empty_string(self):
        api_response = {
            "choices": [{"message": {"role": "assistant", "content": None}}],
            "usage": {"total_tokens": 500},
            "model": "gpt-5.2",
        }
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_openai("test", "gpt-5.2", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""
        assert result["tokens"] == 500

    def test_openai_missing_content_key_returns_empty_string(self):
        api_response = {
            "choices": [{"message": {"role": "assistant"}}],
            "usage": {"total_tokens": 200},
            "model": "o3",
        }
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_openai("test", "o3", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""

    def test_openai_empty_choices_returns_empty_string(self):
        api_response = {"choices": [], "usage": {"total_tokens": 0}, "model": "gpt-5.2"}
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_openai("test", "gpt-5.2", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""

    def test_openrouter_null_content_returns_empty_string(self):
        api_response = {
            "choices": [{"message": {"role": "assistant", "content": None}}],
            "usage": {"total_tokens": 300},
        }
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_openrouter("test", "model-x", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""
        assert result["tokens"] == 300

    def test_anthropic_null_text_in_block_returns_empty_string(self):
        api_response = {
            "content": [{"type": "text", "text": None}],
            "usage": {"input_tokens": 10, "output_tokens": 0},
            "model": "claude-sonnet-4-20250514",
        }
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_anthropic("test", "claude-sonnet-4-20250514", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""

    def test_xai_null_content_returns_empty_string(self):
        api_response = {
            "choices": [{"message": {"role": "assistant", "content": None}}],
            "usage": {"total_tokens": 400},
            "model": "grok-3",
        }
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_xai("test", "grok-3", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""
        assert result["tokens"] == 400

    def test_gemini_null_text_in_parts_returns_empty_string(self):
        api_response = {
            "candidates": [{"content": {"parts": [{"text": None}]}}],
            "usageMetadata": {"totalTokenCount": 50},
        }
        with patch("conclave.providers._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = api_response
            result = asyncio.run(
                _call_gemini("test", "gemini-pro", None, "key", 0.7, 100, 10)
            )
        assert result["content"] == ""
