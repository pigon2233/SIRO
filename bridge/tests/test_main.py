"""
bridge/tests/test_main.py

測試 FastAPI app 的端點（用 TestClient，不用真的啟動 server）。
策略：直接 patch 全域 state，而不是 patch 整個 HermesClient 類別
（避免跟 lifespan 互動的複雜性）。
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from bridge.main import app, state
from bridge.hermes_client import HermesResult, HermesClient
from bridge.emotion_parser import EmotionParser


@pytest.fixture
def client():
    """FastAPI TestClient（不觸發 lifespan，因為我們手動管理 state）"""
    return TestClient(app)


@pytest.fixture
def mock_hermes():
    """替換全域 state.hermes 為 mock，並確保 state.parser 也有值"""
    mock_instance = MagicMock(spec=HermesClient)
    mock_instance.is_available.return_value = True
    mock_instance.get_version.return_value = "v0.15.2"

    # 備份原始 state
    original_hermes = state.hermes
    original_parser = state.parser
    state.hermes = mock_instance
    state.parser = EmotionParser()  # 用真的 parser
    yield mock_instance
    # 恢復
    state.hermes = original_hermes
    state.parser = original_parser


class TestHealth:
    def test_health_when_hermes_available(self, client, mock_hermes):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["hermes_available"] is True
        assert data["hermes_version"] == "v0.15.2"
        assert "bridge_version" in data

    def test_health_when_hermes_unavailable(self, client):
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

    def test_health_when_hermes_is_none(self, client):
        original = state.hermes
        state.hermes = None
        try:
            r = client.get("/health")
            data = r.json()
            assert data["hermes_available"] is False
            assert data["status"] == "degraded"
        finally:
            state.hermes = original


class TestChatEndpoint:
    def test_chat_success(self, client, mock_hermes):
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
        assert data["live2d"]["expression_id"] == "F02"
        assert data["user_id"] == "test"
        assert "session_id" in data
        assert data["raw_response"] == "[emotion:happy] 你好呀！"

    def test_chat_empty_message_rejected(self, client, mock_hermes):
        """空訊息應該被 Pydantic 擋下"""
        r = client.post("/chat", json={"message": "", "user_id": "test"})
        assert r.status_code == 422

    def test_chat_message_too_long_rejected(self, client, mock_hermes):
        """超過 2000 字應該被擋下"""
        long_msg = "x" * 2001
        r = client.post("/chat", json={"message": long_msg, "user_id": "test"})
        assert r.status_code == 422

    def test_chat_hermes_failure_returns_502(self, client, mock_hermes):
        """Hermes 失敗 → 502 Bad Gateway"""
        mock_hermes.chat.return_value = HermesResult(
            success=False,
            output="",
            error="hermes 對話失敗",
        )

        r = client.post("/chat", json={"message": "hi", "user_id": "test"})
        assert r.status_code == 502
        assert "hermes" in r.json()["detail"].lower()

    def test_chat_hermes_unavailable_returns_503(self, client):
        """Hermes 不可用 → 503"""
        mock = MagicMock()
        mock.is_available.return_value = False
        original = state.hermes
        state.hermes = mock
        try:
            r = client.post("/chat", json={"message": "hi", "user_id": "test"})
            assert r.status_code == 503
        finally:
            state.hermes = original

    def test_chat_session_id_reuse(self, client, mock_hermes):
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

    def test_chat_preserves_history_in_subsequent_calls(self, client, mock_hermes):
        """同一 session 的第二次呼叫，prompt 應包含第一次的對話"""
        mock_hermes.chat.return_value = HermesResult(
            success=True,
            output="[emotion:happy] 你也好！",
        )

        # 第一次
        r1 = client.post("/chat", json={
            "message": "你好",
            "user_id": "user-history",
            "session_id": "sess-1",
        })
        assert r1.status_code == 200

        # 第二次
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

        # 第二次呼叫的 prompt 應該包含第一次的訊息
        second_call_args = mock_hermes.chat.call_args_list[1]
        second_message = second_call_args.kwargs.get("message") or second_call_args.args[0]
        assert "你好" in second_message


class TestWebSocket:
    def test_websocket_chat_message(self, client, mock_hermes):
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

    def test_websocket_ping_pong(self, client, mock_hermes):
        """ping 應該回 pong"""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_websocket_unknown_type_returns_error(self, client, mock_hermes):
        """未知 type 應該回 error"""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "wat"})
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_websocket_empty_message_returns_error(self, client, mock_hermes):
        """空白訊息應該回 error"""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "message": "  ", "user_id": "test"})
            data = ws.receive_json()
            assert data["type"] == "error"

    def test_websocket_hermes_failure_returns_error(self, client, mock_hermes):
        """Hermes 失敗 WS 應該回 error（不中斷連線）"""
        mock_hermes.chat.return_value = HermesResult(
            success=False,
            output="",
            error="hermes 對話失敗",
        )

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "message": "hi", "user_id": "test"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "hermes" in data["detail"].lower()

            # 連線還能繼續用
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"
