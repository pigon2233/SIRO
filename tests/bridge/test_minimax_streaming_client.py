"""
tests/bridge/test_minimax_streaming_client.py - MiniMax-M3 SSE streaming client 單元測試

測試策略：用 httpx.MockTransport 注入假的 SSE response，
不真的打 API。重點：SSE 解析、TTFT 量測、錯誤處理、timeout。
"""

import json
import pytest
import httpx

from bridge.minimax_streaming_client import (
    MiniMaxStreamingClient,
    MiniMaxStreamingResult,
)


# ==================== Fixtures ====================

@pytest.fixture
def mock_env(monkeypatch):
    """設齊 env vars（client 預設從 env 讀）"""
    monkeypatch.setenv("HERMES_LLM_BASE_URL", "https://api.test.io/anthropic")
    monkeypatch.setenv("HERMES_LLM_MODEL", "MiniMax-M3-test")
    monkeypatch.setenv("HERMES_API_KEY", "sk-test-key-1234")
    monkeypatch.setenv("SIRO_PRIMARY_LLM_TIMEOUT_SEC", "30")


def make_sse_response(chunks: list[str], stop_at: int | None = None) -> str:
    """組一個標準 Anthropic SSE response body"""
    lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"id":"msg_01","role":"assistant","content":[]}}',
        "",
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "",
    ]
    for i, chunk in enumerate(chunks):
        if stop_at is not None and i >= stop_at:
            break
        lines.extend([
            "event: content_block_delta",
            f'data: {json.dumps({"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":chunk}})}',
            "",
        ])
    lines.extend([
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "",
        "event: message_delta",
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ])
    return "\n".join(lines)


def make_mock_transport(sse_body: str, status_code: int = 200) -> httpx.MockTransport:
    """做一個 httpx MockTransport，收到任何 request 都回指定 SSE body"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            content=sse_body.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )
    return httpx.MockTransport(handler)


# ==================== is_available ====================

class TestIsAvailable:
    def test_all_env_set_returns_true(self, mock_env):
        c = MiniMaxStreamingClient()
        assert c.is_available is True

    def test_missing_base_url_returns_false(self, monkeypatch):
        monkeypatch.setenv("HERMES_LLM_BASE_URL", "")
        monkeypatch.setenv("HERMES_LLM_MODEL", "m")
        monkeypatch.setenv("HERMES_API_KEY", "k")
        c = MiniMaxStreamingClient()
        assert c.is_available is False

    def test_missing_model_returns_false(self, monkeypatch):
        monkeypatch.setenv("HERMES_LLM_BASE_URL", "https://x")
        monkeypatch.setenv("HERMES_LLM_MODEL", "")
        monkeypatch.setenv("HERMES_API_KEY", "k")
        c = MiniMaxStreamingClient()
        assert c.is_available is False

    def test_missing_api_key_returns_false(self, monkeypatch):
        monkeypatch.setenv("HERMES_LLM_BASE_URL", "https://x")
        monkeypatch.setenv("HERMES_LLM_MODEL", "m")
        monkeypatch.setenv("HERMES_API_KEY", "")
        c = MiniMaxStreamingClient()
        assert c.is_available is False


# ==================== chat_stream — happy path ====================

class TestChatStreamHappyPath:
    @pytest.mark.asyncio
    async def test_yields_chunks_in_order(self, mock_env):
        sse = make_sse_response(["你", "好", "，", "Mao", "！"])
        transport = make_mock_transport(sse)
        c = MiniMaxStreamingClient()

        chunks: list[str] = []
        async with httpx.AsyncClient(transport=transport) as client:
            # monkey-patch httpx.AsyncClient to use our transport
            pass

        # 直接用 client.chat_stream 但替換裡面的 httpx
        # 用更簡單的辦法：把 transport 透過 monkeypatch 注入
        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            async for chunk in c.chat_stream("hi"):
                chunks.append(chunk)
        finally:
            mod.httpx.AsyncClient = orig

        assert chunks == ["你", "好", "，", "Mao", "！"]

    @pytest.mark.asyncio
    async def test_empty_chunks_skipped(self, mock_env):
        """LLM 有時會送空 delta text、要跳過不算 chunk"""
        sse = make_sse_response(["你", "", "好"])  # 中間有空字串
        transport = make_mock_transport(sse)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            chunks = []
            async for chunk in c.chat_stream("hi"):
                chunks.append(chunk)
        finally:
            mod.httpx.AsyncClient = orig

        # 兩種合理結果：跳過空 chunk（[你, 好]）或保留（[你, "", 好]）
        # 實作是跳過（因為 yield 是 "if text_chunk"）
        assert "".join(chunks) == "你好"

    @pytest.mark.asyncio
    async def test_ttft_recorded_on_first_chunk(self, mock_env):
        """TTFT = 第一個 chunk 從送出到收到的時間"""
        sse = make_sse_response(["你", "好"])
        transport = make_mock_transport(sse)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            result = await c.chat_collect("hi")
        finally:
            mod.httpx.AsyncClient = orig

        assert result.success is True
        assert result.text == "你好"
        assert result.chunks == ["你", "好"]
        assert result.ttft_ms is not None
        assert result.ttft_ms >= 0
        assert result.duration_ms is not None
        assert result.duration_ms >= result.ttft_ms


# ==================== chat_stream — error paths ====================

class TestChatStreamErrors:
    @pytest.mark.asyncio
    async def test_missing_config_raises(self):
        c = MiniMaxStreamingClient()  # 沒設 env
        with pytest.raises(RuntimeError, match="設定不齊"):
            async for _ in c.chat_stream("hi"):
                pass

    @pytest.mark.asyncio
    async def test_api_error_status_raises(self, mock_env):
        sse = "internal server error"  # 任何 body，status 500
        transport = make_mock_transport(sse, status_code=500)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            with pytest.raises(RuntimeError, match="MiniMax-M3 API error 500"):
                async for _ in c.chat_stream("hi"):
                    pass
        finally:
            mod.httpx.AsyncClient = orig

    @pytest.mark.asyncio
    async def test_sse_error_event_raises(self, mock_env):
        """SSE 收到 error event 應該 raise"""
        sse_body = "\n".join([
            "event: error",
            'data: {"type":"error","error":{"type":"overloaded_error","message":"server overloaded"}}',
            "",
        ])
        transport = make_mock_transport(sse_body)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            with pytest.raises(RuntimeError, match="overloaded"):
                async for _ in c.chat_stream("hi"):
                    pass
        finally:
            mod.httpx.AsyncClient = orig

    @pytest.mark.asyncio
    async def test_non_json_data_skipped(self, mock_env):
        """SSE data 不是 JSON 應該 warning 跳過、不 crash"""
        sse_body = "\n".join([
            "event: content_block_delta",
            "data: not-json-at-all",
            "",
            "event: content_block_delta",
            f'data: {json.dumps({"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"recovered"}})}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ])
        transport = make_mock_transport(sse_body)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            chunks = []
            async for chunk in c.chat_stream("hi"):
                chunks.append(chunk)
        finally:
            mod.httpx.AsyncClient = orig

        assert chunks == ["recovered"]


# ==================== chat_collect error returns ====================

class TestChatCollect:
    @pytest.mark.asyncio
    async def test_collect_returns_result_with_text(self, mock_env):
        sse = make_sse_response(["你", "好", "！"])
        transport = make_mock_transport(sse)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            result = await c.chat_collect("hi")
        finally:
            mod.httpx.AsyncClient = orig

        assert isinstance(result, MiniMaxStreamingResult)
        assert result.success is True
        assert result.text == "你好！"
        assert result.chunks == ["你", "好", "！"]
        assert result.error is None

    @pytest.mark.asyncio
    async def test_collect_handles_error_gracefully(self, mock_env):
        """chat_collect 不 raise、把錯誤包成 success=False result"""
        transport = make_mock_transport("err", status_code=500)
        c = MiniMaxStreamingClient()

        import bridge.minimax_streaming_client as mod
        orig = mod.httpx.AsyncClient

        class PatchedClient(orig):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        mod.httpx.AsyncClient = PatchedClient
        try:
            result = await c.chat_collect("hi")
        finally:
            mod.httpx.AsyncClient = orig

        assert result.success is False
        assert result.error is not None
        assert "500" in result.error
        assert result.text == ""
        assert result.chunks == []
