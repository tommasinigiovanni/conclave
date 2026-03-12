"""Tests for streaming — SSE parsing, stream_model, orchestrator integration."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conclave.progress import _Progress
from conclave.providers import (
    _iter_sse_lines,
    _stream_anthropic,
    _stream_gemini,
    _stream_openai_compat,
    stream_model,
)


# ── Helpers ──────────────────────────────────────────────────────


class FakeStreamResponse:
    """Simulates an httpx streaming response."""

    def __init__(self, chunks: list[str], status_code: int = 200):
        self._chunks = chunks
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    async def aiter_text(self):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


async def _collect(gen):
    """Collect all tokens from an async generator into a string."""
    tokens = []
    async for t in gen:
        tokens.append(t)
    return "".join(tokens)


# ── SSE line iteration ───────────────────────────────────────────


class TestIterSseLines:
    def test_splits_on_newlines(self):
        resp = FakeStreamResponse(["line1\nline2\nline3"])
        lines = asyncio.run(_collect_lines(resp))
        assert lines == ["line1", "line2", "line3"]

    def test_handles_chunked_delivery(self):
        resp = FakeStreamResponse(["li", "ne1\nli", "ne2\n"])
        lines = asyncio.run(_collect_lines(resp))
        assert lines == ["line1", "line2"]

    def test_yields_trailing_content(self):
        resp = FakeStreamResponse(["line1\npartial"])
        lines = asyncio.run(_collect_lines(resp))
        assert lines == ["line1", "partial"]


async def _collect_lines(resp):
    result = []
    async for line in _iter_sse_lines(resp):
        result.append(line)
    return result


# ── Anthropic SSE parsing ────────────────────────────────────────


class TestStreamAnthropic:
    def _make_sse(self, events: list[dict]) -> list[str]:
        """Build SSE text from a list of event dicts."""
        lines = []
        for ev in events:
            lines.append(f"event: {ev.get('event', 'unknown')}\n")
            lines.append(f"data: {json.dumps(ev.get('data', {}))}\n\n")
        return ["".join(lines)]

    def test_extracts_text_deltas(self):
        chunks = self._make_sse([
            {"event": "content_block_delta",
             "data": {"type": "content_block_delta",
                      "delta": {"type": "text_delta", "text": "Hello"}}},
            {"event": "content_block_delta",
             "data": {"type": "content_block_delta",
                      "delta": {"type": "text_delta", "text": " world"}}},
            {"event": "message_stop", "data": {"type": "message_stop"}},
        ])
        resp = FakeStreamResponse(chunks)
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_anthropic("hi", "claude-3", None, "key", 0.7, 100, 30,
                              client=client)))
        assert text == "Hello world"

    def test_skips_non_text_events(self):
        chunks = self._make_sse([
            {"event": "message_start", "data": {"type": "message_start"}},
            {"event": "content_block_delta",
             "data": {"type": "content_block_delta",
                      "delta": {"type": "text_delta", "text": "OK"}}},
            {"event": "content_block_stop", "data": {"type": "content_block_stop"}},
        ])
        resp = FakeStreamResponse(chunks)
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_anthropic("hi", "claude-3", None, "key", 0.7, 100, 30,
                              client=client)))
        assert text == "OK"

    def test_handles_empty_text_delta(self):
        chunks = self._make_sse([
            {"event": "content_block_delta",
             "data": {"type": "content_block_delta",
                      "delta": {"type": "text_delta", "text": ""}}},
            {"event": "content_block_delta",
             "data": {"type": "content_block_delta",
                      "delta": {"type": "text_delta", "text": "data"}}},
        ])
        resp = FakeStreamResponse(chunks)
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_anthropic("hi", "claude-3", None, "key", 0.7, 100, 30,
                              client=client)))
        assert text == "data"


# ── OpenAI/OpenRouter SSE parsing ────────────────────────────────


class TestStreamOpenAICompat:
    def _make_sse(self, deltas: list[str | None]) -> list[str]:
        lines = []
        for d in deltas:
            obj = {"choices": [{"delta": {"content": d}}]}
            lines.append(f"data: {json.dumps(obj)}\n\n")
        lines.append("data: [DONE]\n\n")
        return ["".join(lines)]

    def test_extracts_content_deltas(self):
        chunks = self._make_sse(["Hello", " ", "world"])
        resp = FakeStreamResponse(chunks)
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_openai_compat("hi", "gpt-4", None, "key", 0.7, 100, 30,
                                  "https://api.openai.com/v1/chat/completions",
                                  client=client)))
        assert text == "Hello world"

    def test_skips_null_deltas(self):
        chunks = self._make_sse([None, "text", None, "more"])
        resp = FakeStreamResponse(chunks)
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_openai_compat("hi", "gpt-4", None, "key", 0.7, 100, 30,
                                  "https://api.openai.com/v1/chat/completions",
                                  client=client)))
        assert text == "textmore"

    def test_handles_done_signal(self):
        sse_text = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        resp = FakeStreamResponse([sse_text])
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_openai_compat("hi", "gpt-4", None, "key", 0.7, 100, 30,
                                  "https://api.openai.com/v1/chat/completions",
                                  client=client)))
        assert text == "ok"


# ── Gemini streaming ────────────────────────────────────────────


class TestStreamGemini:
    def _make_sse(self, texts: list[str]) -> list[str]:
        lines = []
        for t in texts:
            obj = {"candidates": [{"content": {"parts": [{"text": t}]}}]}
            lines.append(f"data: {json.dumps(obj)}\n\n")
        return ["".join(lines)]

    def test_extracts_text_from_candidates(self):
        chunks = self._make_sse(["Hello", " world"])
        resp = FakeStreamResponse(chunks)
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_gemini("hi", "gemini-pro", None, "key", 0.7, 100, 30,
                           client=client)))
        assert text == "Hello world"

    def test_handles_empty_candidates(self):
        sse_text = 'data: {"candidates":[]}\n\n'
        resp = FakeStreamResponse([sse_text])
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(
            _stream_gemini("hi", "gemini-pro", None, "key", 0.7, 100, 30,
                           client=client)))
        assert text == ""


# ── stream_model entry point ─────────────────────────────────────


class TestStreamModel:
    def test_local_member_yields_nothing(self):
        member = {"key": "claude", "local": True, "provider": "anthropic",
                  "direct_model": "claude-3"}
        cfg = {"provider_mode": "direct", "defaults": {}, "direct_keys": {}}
        text = asyncio.run(_collect(stream_model(member, "hi", None, cfg,
                                                  client=MagicMock())))
        assert text == ""

    def test_routes_to_anthropic(self):
        member = {"key": "claude", "local": False, "provider": "anthropic",
                  "direct_model": "claude-3"}
        cfg = {
            "provider_mode": "direct",
            "defaults": {"temperature": 0.7, "max_tokens": 100, "timeout_seconds": 30},
            "direct_keys": {"anthropic": "sk-test"},
        }

        sse_text = (
            'event: content_block_delta\n'
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"streamed"}}\n\n'
        )
        resp = FakeStreamResponse([sse_text])
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(stream_model(member, "hi", None, cfg,
                                                  client=client)))
        assert text == "streamed"

    def test_routes_to_openai(self):
        member = {"key": "gpt", "local": False, "provider": "openai",
                  "direct_model": "gpt-4"}
        cfg = {
            "provider_mode": "direct",
            "defaults": {"temperature": 0.7, "max_tokens": 100, "timeout_seconds": 30},
            "direct_keys": {"openai": "sk-test"},
        }

        sse_text = (
            'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        resp = FakeStreamResponse([sse_text])
        client = _mock_streaming_client(resp)
        text = asyncio.run(_collect(stream_model(member, "hi", None, cfg,
                                                  client=client)))
        assert text == "hello"


# ── Progress streaming display ───────────────────────────────────


class TestProgressStreaming:
    def test_accumulates_text_in_quiet_mode(self):
        async def _gen():
            yield "Hello"
            yield " "
            yield "world"

        progress = _Progress(quiet=True)
        text = asyncio.run(progress.stream_member_response("Test", "🔵", _gen()))
        assert text == "Hello world"

    def test_accumulates_text_in_normal_mode(self):
        async def _gen():
            yield "token1"
            yield "token2"

        progress = _Progress(quiet=False)
        text = asyncio.run(progress.stream_member_response("Test", "🔵", _gen()))
        assert text == "token1token2"

    def test_returns_empty_for_empty_generator(self):
        async def _gen():
            return
            yield  # make it an async generator

        progress = _Progress(quiet=True)
        text = asyncio.run(progress.stream_member_response("Test", "🔵", _gen()))
        assert text == ""


# ── Orchestrator integration (stream=false fallback) ─────────────


class TestPhase1StreamConfig:
    def _cfg_with_stream(self, stream: bool, members: list):
        return {
            "provider_mode": "direct",
            "direct_keys": {"anthropic": "sk-a", "google": "gk-g", "openai": "ok-o"},
            "openrouter": {"api_key": ""},
            "defaults": {
                "temperature": 0.7, "max_tokens": 100,
                "timeout_seconds": 10, "max_retries": 0, "retry_base_delay": 0.01,
            },
            "anonymize_reviews": True,
            "council_members": members,
            "stream": stream,
            "stream_sequential": False,
        }

    def test_stream_false_uses_standard_call(self):
        """When stream=false, phase1 uses call_model (no regression)."""
        from conclave.orchestrator import phase1

        members = [
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
        ]
        cfg = self._cfg_with_stream(False, members)

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "standard response", "tokens": 10,
                    "model": "gemini-2.0-flash", "elapsed": 1.0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            drafts = asyncio.run(phase1("test", None, members, cfg,
                                        _Progress(quiet=True)))

        assert len(drafts) == 1
        assert drafts[0]["content"] == "standard response"
        assert "streamed" not in drafts[0]

    def test_stream_true_sequential_uses_streaming(self):
        """When stream=true + sequential, phase1 uses stream_model."""
        from conclave.orchestrator import phase1

        members = [
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
        ]
        cfg = self._cfg_with_stream(True, members)
        cfg["stream_sequential"] = True

        async def fake_stream(member, prompt, system, cfg, **kwargs):
            yield "chunk1"
            yield "chunk2"

        with patch("conclave.orchestrator.stream_model", side_effect=fake_stream):
            drafts = asyncio.run(phase1("test", None, members, cfg,
                                        _Progress(quiet=True)))

        assert len(drafts) == 1
        assert drafts[0]["content"] == "chunk1chunk2"
        assert drafts[0]["streamed"] is True

    def test_stream_true_parallel_uses_streaming(self):
        """When stream=true + parallel, phase1 uses stream_model."""
        from conclave.orchestrator import phase1

        members = [
            {"key": "gemini", "label": "Gemini", "icon": "🔵",
             "provider": "google", "local": False, "direct_model": "gemini-2.0-flash"},
            {"key": "gpt", "label": "GPT", "icon": "🟢",
             "provider": "openai", "local": False, "direct_model": "gpt-5.2"},
        ]
        cfg = self._cfg_with_stream(True, members)

        async def fake_stream(member, prompt, system, cfg, **kwargs):
            yield f"{member['key']}_token"

        with patch("conclave.orchestrator.stream_model", side_effect=fake_stream):
            drafts = asyncio.run(phase1("test", None, members, cfg,
                                        _Progress(quiet=True)))

        assert len(drafts) == 2
        keys = {d["key"] for d in drafts}
        assert keys == {"gemini", "gpt"}
        for d in drafts:
            assert d["streamed"] is True

    def test_local_members_not_streamed(self):
        """Local members use standard call_model even when streaming is on."""
        from conclave.orchestrator import phase1

        members = [
            {"key": "claude", "label": "Claude", "icon": "🟣",
             "provider": "anthropic", "local": True, "direct_model": "claude-3"},
        ]
        cfg = self._cfg_with_stream(True, members)
        cfg["stream_sequential"] = True

        async def fake_call(member, prompt, system, cfg, **kwargs):
            return {"content": "", "needs_claude_code": True,
                    "model": "claude-3", "tokens": None, "elapsed": 0}

        with patch("conclave.orchestrator.call_model", side_effect=fake_call):
            drafts = asyncio.run(phase1("test", None, members, cfg,
                                        _Progress(quiet=True)))

        assert len(drafts) == 1
        assert drafts[0].get("needs_claude_code") is True


# ── Helper ───────────────────────────────────────────────────────


def _mock_streaming_client(fake_response: FakeStreamResponse):
    """Create a mock httpx.AsyncClient that returns fake_response for .stream()."""
    client = MagicMock()
    client.stream = MagicMock(return_value=fake_response)
    return client
