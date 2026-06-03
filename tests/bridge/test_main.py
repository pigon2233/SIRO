"""
tests/bridge/test_main.py

測 FastAPI app 端點（用 TestClient，不用真的啟動 server）。
策略：直接 patch 全域 state，模擬 hermes / ollama 行為。

Phase 1.5+ 改版重點：
- Hermes 失敗 / 不可用 → 回 200 + fallback response（不是 502/503）
- 兩段式 fallback：先試 Ollama → 失敗才用 static persona 文字
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from bridge.main import app, state
from bridge.hermes_client import HermesResult, HermesClient
from bridge.ollama_client import OllamaClient, OllamaResult
from bridge.emotion_parser import EmotionParser


# ==================== Fixtures ====================

@pytest.fixture
def client():
    """FastAPI TestClient（不觸發 lifespan，手動管理 state）"""
    return TestClient(app)


@pytest.fixture
def mock_hermes():
    """替換 state.hermes 為 mock（available + get_version）"""
    mock = MagicMock(spec=HermesClient)
    mock.is_available.return_value = True
    mock.get_version.return_value = "v0.15.2"
    mock.timeout = 30

    original = state.hermes
    state.hermes = mock
    yield mock
    state.hermes = original


@pytest.fixture
def mock_ollama_available():
    """Ollama 也活著"""
    mock = MagicMock(spec=OllamaClient)
    mock.is_available.return_value = True
    mock.model = "test-model"
    mock.base_url = "http://fake:11434"

    original = state.ollama
    state.ollama = mock
    yield mock
    state.ollama = original


@pytest.fixture
def mock_ollama_unavailable():
    """Ollama 不在"""
    mock = MagicMock(spec=OllamaClient)
    mock.is_available.return_value = False

    original = state.ollama
    state.ollama = mock
    yield mock
    state.ollama = original


@pytest.fixture
def real_parser():
    """真的 EmotionParser（避免 mock 過度）"""
    original = state.parser
    state.parser = EmotionParser()
    yield state.parser
    state.parser = original


# ==================== /health ====================

class TestHealth:
    def test_health_when_hermes_available(self, client, mock_hermes, mock_ollama_available):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["hermes_available"] is True
        assert data["hermes_version"] == "v0.15.2"
        assert "bridge_version" in data

    def test_health_when_hermes_unavailable(self, client, mock_ollama_available):
        mock = MagicMock()
        mock.is_available.return_value = False
        mock.get_version.return_value = None
        original = state.hermes
        state.hermes = mock
        try:
            r = client.get("/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "degraded"
            assert data["hermes_available"] is False
        finally:
            state.hermes = original

    def test_health_when_hermes_is_none(self, client, mock_ollama_available):
        original = state.hermes
        state.hermes = None
        try:
            r = client.get("/health")
            data = r.json()
            assert data["hermes_available"] is False
            assert data["status"] == "degraded"
        finally:
            state.hermes = original


# ==================== /chat 正常路徑 ====================

class TestChatSuccess:
    def test_chat_success(self, client, mock_hermes, mock_ollama_available, real_parser):
        """對話成功 → 回傳含情緒的回應"""
        mock_hermes.chat.return_value = HermesResult(
            success=True,
            output="[emotion:happy] 你好呀！",
        )

        r = client.post("/chat", json={"message": "你好", "user_id": "test"})
        assert r.status_code == 200
        data = r.json()

        assert data["text"] == "你好呀！"
        assert data["emotion"] == "happy"
        assert "live2d" in data
        assert data["live2d"]["expression_id"]  # 有值
        assert data["user_id"] == "test"
        assert "session_id" in data
        assert data["raw_response"] == "[emotion:happy] 你好呀！"

    def test_chat_empty_message_rejected(self, client, mock_hermes, mock_ollama_available):
        """空訊息應該被 Pydantic 擋下"""
        r = client.post("/chat", json={"message": "", "user_id": "test"})
        assert r.status_code == 422

    def test_chat_message_too_long_rejected(self, client, mock_hermes, mock_ollama_available):
        """超過 2000 字應該被擋下"""
        long_msg = "x" * 2001
        r = client.post("/chat", json={"message": long_msg, "user_id": "test"})
        assert r.status_code == 422

    def test_chat_session_id_reuse(self, client, mock_hermes, mock_ollama_available, real_parser):
        """傳入 session_id 應該被保留"""
        mock_hermes.chat.return_value = HermesResult(
            success=True,
            output="[emotion:neutral] 嗨",
        )

        r = client.post("/chat", json={
            "message": "hi",
            "user_id": "test",
            "session_id": "my-session-123",
        })
        assert r.status_code == 200
        assert r.json()["session_id"] == "my-session-123"

    def test_chat_preserves_history_in_subsequent_calls(
        self, client, mock_hermes, mock_ollama_available, real_parser
    ):
        """同一 session 的第二次呼叫，prompt 應包含第一次的對話"""
        mock_hermes.chat.return_value = HermesResult(
            success=True,
            output="[emotion:happy] 你也好！",
        )

        r1 = client.post("/chat", json={
            "message": "你好",
            "user_id": "user-history",
            "session_id": "sess-1",
        })
        assert r1.status_code == 200

        mock_hermes.chat.return_value = HermesResult(
            success=True,
            output="[emotion:happy] 我記得你說你好",
        )
        r2 = client.post("/chat", json={
            "message": "你還記得我嗎",
            "user_id": "user-history",
            "session_id": "sess-1",
        })
        assert r2.status_code == 200

        second_call_args = mock_hermes.chat.call_args_list[1]
        second_message = second_call_args.kwargs.get("message") or second_call_args.args[0]
        assert "你好" in second_message


# ==================== /chat 降級路徑（GAPS #4 + #9）====================

class TestChatFallback:
    """Hermes 不可用 / 失敗時的降級路徑"""

    def test_hermes_failure_returns_soft_fallback_via_ollama(
        self, client, mock_ollama_available, real_parser
    ):
        """Hermes 失敗 + Ollama 在 → Ollama 拿真回應 + 真情緒"""
        mock_hermes = MagicMock(spec=HermesClient)
        mock_hermes.is_available.return_value = True
        mock_hermes.get_version.return_value = "v0.15.2"
        mock_hermes.chat.return_value = HermesResult(
            success=False,
            output="",
            error="hermes 對話 timeout",
        )

        # Ollama 給真回應 + emotion tag
        mock_ollama_available.chat.return_value = OllamaResult(
            success=True,
            output="[emotion:thinking] 嗯...讓我想想",
        )

        original = state.hermes
        state.hermes = mock_hermes
        try:
            r = client.post("/chat", json={"message": "你好", "user_id": "test"})
            assert r.status_code == 200
            data = r.json()
            # 走 Ollama 軟降級 → 拿到真的中文 + thinking 情緒
            assert "讓我想想" in data["text"]
            assert data["emotion"] == "thinking"
            # Ollama 應該被呼叫
            mock_ollama_available.chat.assert_called_once()
        finally:
            state.hermes = original

    def test_hermes_unavailable_returns_soft_fallback_via_ollama(
        self, client, mock_ollama_available, real_parser
    ):
        """Hermes 不可用 + Ollama 在 → 走 Ollama"""
        mock_hermes = MagicMock(spec=HermesClient)
        mock_hermes.is_available.return_value = False
        mock_hermes.get_version.return_value = None

        mock_ollama_available.chat.return_value = OllamaResult(
            success=True,
            output="[emotion:happy] 嗨嗨",
        )

        original = state.hermes
        state.hermes = mock_hermes
        try:
            r = client.post("/chat", json={"message": "hi", "user_id": "test"})
            assert r.status_code == 200
            data = r.json()
            assert data["emotion"] == "happy"
            assert "嗨嗨" in data["text"]
        finally:
            state.hermes = original

    def test_both_hermes_and_ollama_down_returns_hard_fallback(
        self, client, mock_ollama_unavailable, real_parser
    ):
        """Hermes 死 + Ollama 死 → 走 persona 靜態文字 + thinking 表情"""
        mock_hermes = MagicMock(spec=HermesClient)
        mock_hermes.is_available.return_value = False

        original = state.hermes
        state.hermes = mock_hermes
        try:
            r = client.post("/chat", json={"message": "hi", "user_id": "test"})
            assert r.status_code == 200
            data = r.json()
            # 硬降級：thinking 表情
            assert data["emotion"] == "thinking"
            # 文字應該是 persona 池裡的某一句
            assert isinstance(data["text"], str)
            assert len(data["text"]) > 0
            # raw_response 標記走 hard fallback
            assert "hard fallback" in (data.get("raw_response") or "")
        finally:
            state.hermes = original

    def test_hermes_failure_ollama_failure_returns_hard_fallback(
        self, client, mock_ollama_unavailable, real_parser
    ):
        """Hermes 失敗（不是不可用）+ Ollama 死 → 走 hard fallback"""
        mock_hermes = MagicMock(spec=HermesClient)
        mock_hermes.is_available.return_value = True
        mock_hermes.chat.return_value = HermesResult(
            success=False,
            output="",
            error="hermes timeout",
        )

        original = state.hermes
        state.hermes = mock_hermes
        try:
            r = client.post("/chat", json={"message": "hi", "user_id": "test"})
            assert r.status_code == 200
            data = r.json()
            assert data["emotion"] == "thinking"
        finally:
            state.hermes = original

    def test_hermes_not_initialized_returns_503(
        self, client, mock_ollama_available, real_parser
    ):
        """Bridge state.hermes = None → 503（這是系統 bug，應該明確報錯）"""
        original = state.hermes
        state.hermes = None
        try:
            r = client.post("/chat", json={"message": "hi", "user_id": "test"})
            assert r.status_code == 503
        finally:
            state.hermes = original


# ==================== /ws WebSocket ====================

class TestWebSocket:
    def test_websocket_chat_message(
        self, client, mock_hermes, mock_ollama_available, real_parser
    ):
        """WebSocket 對話流程"""
        mock_hermes.chat.return_value = HermesResult(
            success=True,
            output="[emotion:happy] WS 你好！",
        )

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "message": "你好", "user_id": "ws-test"})

            data = ws.receive_json()
            assert data["type"] == "response"
            assert data["text"] == "WS 你好！"
            assert data["emotion"] == "happy"
            assert "live2d" in data

    def test_websocket_ping_pong(
        self, client, mock_hermes, mock_ollama_available, real_parser
    ):
        """ping 應該回 pong"""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_websocket_unknown_type_returns_error(
        self, client, mock_hermes, mock_ollama_available, real_parser
    ):
        """未知 type 應該回 error"""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "wat"})
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_websocket_empty_message_returns_error(
        self, client, mock_hermes, mock_ollama_available, real_parser
    ):
        """空白訊息應該回 error"""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "message": "  ", "user_id": "test"})
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_websocket_hermes_failure_returns_fallback_response(
        self, client, mock_ollama_available, real_parser
    ):
        """Hermes 失敗 → 走 fallback response（不是 error，連線不中斷）

        Phase 1.5 改版：之前是回 error，現在是回 fallback response
        這樣 Mao 切 thinking 而不是 UI 看到錯誤訊息。
        """
        mock_hermes = MagicMock(spec=HermesClient)
        mock_hermes.is_available.return_value = True
        mock_hermes.chat.return_value = HermesResult(
            success=False,
            output="",
            error="hermes 對話失敗",
        )
        mock_ollama_available.chat.return_value = OllamaResult(
            success=True,
            output="[emotion:thinking] 嗯",
        )

        original = state.hermes
        state.hermes = mock_hermes
        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "chat", "message": "hi", "user_id": "test"})
                data = ws.receive_json()
                # 走 fallback response 而不是 error
                assert data["type"] == "response"
                assert data["emotion"] == "thinking"

                # 連線還能繼續用
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"
        finally:
            state.hermes = original
