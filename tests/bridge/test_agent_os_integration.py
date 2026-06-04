"""
tests/bridge/test_agent_os_integration.py - 端點走 AgentOS 的整合測試

v0.3 PLAN_REVIEW #9: /chat 走 AgentOS（opt-in via SIRO_USE_AGENT_OS env flag）
v0.4 翻預設：SIRO_USE_AGENT_OS 沒設時 use_agent_os 預設 true（觀察穩定後翻）

行為（v0.4）：
- env 沒設 / =true (預設) — 走 AgentOS 路徑（enqueue llm_reply_task → wait_for_task）
- env=false — 走 v0.2 sync 路徑（state.hermes.chat 直接呼叫）

這個檔專門測「env=true / 預設」的路徑。env=false 既有 test_main.py 已經覆蓋。

TestClient 是同步呼叫（用 BackgroundTasks 跑 endpoint 但 event loop 在 client 內），
不適合測「等 worker 跑完」的 async flow。改用 mock state.agent_os
（mock enqueue 直接同步跑 task），這樣 test 專注在「/chat 怎麼呼叫 agent_os」這層。
"""

from __future__ import annotations

import os
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from bridge.main import app, state
from bridge.hermes_client import HermesClient, HermesResult
from bridge.ollama_client import OllamaClient
from bridge.emotion_parser import EmotionParser
from bridge.agent_os import AgentOS, Task, Event


# ==================== Fixtures ====================

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_hermes_setup():
    """跟 test_main.py 一樣：手動塞 mock 到 state.hermes（TestClient 不跑 lifespan）"""
    mock = MagicMock(spec=HermesClient)
    mock.is_available.return_value = True
    mock.get_version.return_value = "v0.15.2"
    mock.timeout = 30

    original_hermes = state.hermes
    original_parser = state.parser
    state.hermes = mock
    state.parser = EmotionParser()
    yield mock
    state.hermes = original_hermes
    state.parser = original_parser


@pytest.fixture
def enable_agent_os(monkeypatch):
    """把 state.use_agent_os 強制設成 True"""
    monkeypatch.setattr(state, "use_agent_os", True, raising=False)
    yield


@pytest.fixture
def mock_agent_os_path(monkeypatch, mock_hermes_setup):
    """Mock state.agent_os：不真的跑 task，直接給假 result

    TestClient 是同步呼叫 /chat endpoint + TestClient 內部用 portal
    起 event loop。AgentOS worker 跑在另一個 asyncio task，
    但 TestClient 的 await wait_for_task 會 deadlock 跟 worker 互鎖。

    改法：mock state.agent_os — enqueue 只記 task_id + 設假 result，
    wait_for_task 直接回假 result。測試專注在「/chat 怎麼呼叫 agent_os」邏輯。
    """
    captured = {"enqueue_count": 0, "task_ids": []}

    def fake_enqueue(task: Task) -> None:
        captured["enqueue_count"] += 1
        captured["task_ids"].append(task.id)

    async def fake_wait_for_task(task_name, task_id, *, timeout=600.0):
        """直接根據 task_name 回對應的假 result，不真的跑 coroutine"""
        if task_name == "llm.reply":
            # 假裝 llm_reply_task 成功完成 — 內容用 hermes chat 模擬的回傳
            hermes_output = "[emotion:happy] 你好！"
            return {
                "task": "llm.reply",
                "task_id": task_id,
                "result": {
                    "status": "ok",
                    "session_id": f"u1-{task_id}",
                    "user_id": "u1",
                    "text": "你好！",
                    "emotion": "happy",
                    "intensity": 0.7,
                    "live2d": {
                        "expression_id": "exp_01",
                        "motion_group": "Idle",
                        "motion_index": 0,
                        "intensity": 0.7,
                        "duration_ms": 500,
                    },
                    "raw_response": hermes_output,
                },
                "duration_ms": 100.0,
            }
        return None

    mock = MagicMock(spec=AgentOS)
    mock.enqueue = fake_enqueue
    mock.wait_for_task = fake_wait_for_task

    original = state.agent_os
    state.agent_os = mock
    yield captured
    state.agent_os = original


# ==================== /chat 走 AgentOS ====================

class TestChatViaAgentOS:
    def test_flag_on_enqueues_task_and_uses_result(
        self, client, mock_agent_os_path, enable_agent_os, monkeypatch
    ):
        """flag=true 時 /chat 應該 enqueue task 到 AgentOS、拿 result 組 ChatResponse"""
        # hermes.chat 改成會回傳 emotion tag
        def fake_chat(*args, **kwargs):
            return HermesResult(
                success=True,
                output="[emotion:happy] 你好！",
            )

        monkeypatch.setattr(state.hermes, "chat", fake_chat)

        r = client.post("/chat", json={"message": "你好", "user_id": "agentos-test"})

        assert r.status_code == 200
        data = r.json()
        assert "你好" in data["text"]
        assert data["emotion"] == "happy"
        # 確認真的有 enqueue
        assert mock_agent_os_path["enqueue_count"] == 1
        # task id 應該被記錄
        assert len(mock_agent_os_path["task_ids"]) == 1
        assert len(mock_agent_os_path["task_ids"][0]) == 8  # UUID4 hex[:8]

    def test_hermes_failure_via_agentos_triggers_fallback(
        self, client, mock_agent_os_path, enable_agent_os, monkeypatch
    ):
        """AgentOS 路徑下 hermes.chat 失敗 → 走 fallback（不是 502）"""
        def fake_chat(*args, **kwargs):
            return HermesResult(
                success=False,
                output="",
                error="hermes 模擬失敗",
            )

        monkeypatch.setattr(state.hermes, "chat", fake_chat)

        r = client.post("/chat", json={"message": "test", "user_id": "u1"})

        # 失敗應該 fallback，HTTP 200
        assert r.status_code == 200
        data = r.json()
        # fallback 文字不該是空
        assert isinstance(data["text"], str)
        assert len(data["text"]) > 0
        # 確認走 AgentOS 路徑
        assert mock_agent_os_path["enqueue_count"] == 1


# ==================== Flag 預設值 (v0.4 翻預設) ====================

class TestUseAgentOSDefault:
    """v0.4 翻預設：SIRO_USE_AGENT_OS 沒設時 use_agent_os 預設 true

    v0.3 之前是預設 false（opt-in），v0.4 觀察穩定後翻成 true（default-on）。
    設 false 可降回 v0.2 sync 路徑 — 給不想要 AgentOS 的人逃生。
    """

    def test_default_is_true(self, monkeypatch):
        """v0.4 翻預設：沒設 env 時 use_agent_os 預設 true"""
        monkeypatch.delenv("SIRO_USE_AGENT_OS", raising=False)
        # 跟 main.py 同步的讀取 pattern
        result = os.environ.get("SIRO_USE_AGENT_OS", "true").lower() == "true"
        assert result is True

    def test_env_false_overrides_default(self, monkeypatch):
        """v0.4 翻預設後：SIRO_USE_AGENT_OS=false 可降回 v0.2 sync"""
        monkeypatch.setenv("SIRO_USE_AGENT_OS", "false")
        result = os.environ.get("SIRO_USE_AGENT_OS", "true").lower() == "true"
        assert result is False

    def test_env_true_sets_to_true(self, monkeypatch):
        """SIRO_USE_AGENT_OS=true 時 use_agent_os = true"""
        monkeypatch.setenv("SIRO_USE_AGENT_OS", "true")
        result = os.environ.get("SIRO_USE_AGENT_OS", "true").lower() == "true"
        assert result is True

    def test_env_truthy_values_set_to_true(self, monkeypatch):
        """TRUE / True / true 都算 true（case-insensitive 比對）"""
        for truthy in ["true", "True", "TRUE"]:
            monkeypatch.setenv("SIRO_USE_AGENT_OS", truthy)
            result = os.environ.get("SIRO_USE_AGENT_OS", "true").lower() == "true"
            assert result is True, f"{truthy!r} should be truthy"

    def test_env_falsy_values_set_to_false(self, monkeypatch):
        """false / False / FALSE / 其他字串 都算 false（只有 .lower()=="true" 才 truthy）"""
        for falsy in ["false", "False", "FALSE", "yes", "0", "", "anything-else"]:
            monkeypatch.setenv("SIRO_USE_AGENT_OS", falsy)
            result = os.environ.get("SIRO_USE_AGENT_OS", "true").lower() == "true"
            assert result is False, f"{falsy!r} should be falsy"


# ==================== /ws 走 AgentOS (v0.3 細項) ====================

class TestWebSocketViaAgentOS:
    """/ws WebSocket 端點也 opt-in 走 AgentOS（跟 /chat 平行）

    用 TestClient.websocket_connect 跑真的 WS 連線（不是 mock）。
    mock state.agent_os.enqueue / wait_for_task — 不實際跑 task coroutine
    避免 TestClient sync portal 跟 worker event loop 互鎖。
    """

    def test_ws_flag_on_enqueues_and_sends_response(
        self, client, mock_hermes_setup, enable_agent_os, monkeypatch
    ):
        """flag=true 時 /ws 應該 enqueue + 透過 AgentOS 拿 result 推回 client"""
        captured = {"enqueue_count": 0, "task_ids": []}

        def fake_enqueue(task: Task) -> None:
            captured["enqueue_count"] += 1
            captured["task_ids"].append(task.id)

        async def fake_wait_for_task(task_name, task_id, *, timeout=600.0):
            if task_name == "llm.reply":
                return {
                    "task": "llm.reply",
                    "task_id": task_id,
                    "result": {
                        "status": "ok",
                        "session_id": f"ws-test-{task_id}",
                        "user_id": "ws-test",
                        "text": "WS AgentOS 你好！",
                        "emotion": "happy",
                        "intensity": 0.7,
                        "live2d": {
                            "expression_id": "exp_01",
                            "motion_group": "Idle",
                            "motion_index": 0,
                            "intensity": 0.7,
                            "duration_ms": 500,
                        },
                        "raw_response": "[emotion:happy] WS AgentOS 你好！",
                    },
                    "duration_ms": 100.0,
                }
            return None

        mock = MagicMock(spec=AgentOS)
        mock.enqueue = fake_enqueue
        mock.wait_for_task = fake_wait_for_task

        original = state.agent_os
        state.agent_os = mock
        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "chat",
                    "message": "WS AgentOS 測試",
                    "user_id": "ws-test",
                })

                data = ws.receive_json()
                assert data["type"] == "response"
                assert data["text"] == "WS AgentOS 你好！"
                assert data["emotion"] == "happy"
                assert "live2d" in data

                # 確認有 enqueue 到 AgentOS
                assert captured["enqueue_count"] == 1
                assert len(captured["task_ids"]) == 1
                # task id 是 8 字 hex (UUID4 hex[:8])
                assert len(captured["task_ids"][0]) == 8
        finally:
            state.agent_os = original

    def test_ws_flag_on_hermes_failure_triggers_fallback_over_ws(
        self, client, mock_hermes_setup, enable_agent_os
    ):
        """AgentOS 路徑下 hermes 失敗 → 走 fallback over WS（連線不中斷）"""
        async def fake_wait_for_task(task_name, task_id, *, timeout=600.0):
            return {
                "task": "llm.reply",
                "task_id": task_id,
                "error": "WS hermes 模擬失敗",
                # 沒有 "result" key → 視為 task.failed
            }

        mock = MagicMock(spec=AgentOS)
        mock.enqueue = lambda t: None
        mock.wait_for_task = fake_wait_for_task

        original = state.agent_os
        state.agent_os = mock
        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "chat",
                    "message": "test",
                    "user_id": "ws-test",
                })

                data = ws.receive_json()
                # 失敗應該 fallback，response 而不是 error
                assert data["type"] == "response"
                assert isinstance(data["text"], str)
                assert len(data["text"]) > 0

                # 連線還能繼續用（ping/pong）
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"
        finally:
            state.agent_os = original


# ==================== /ws SSE Streaming (v0.3.1 選項 B) ====================

class TestWebSocketStreaming:
    """/ws WebSocket SSE streaming 路徑（SIRO_STREAMING=true）

    用 mock 的 MiniMaxStreamingClient 注入假的 chat_stream() 行為，
    不真的打 MiniMax-M3 API。測試重點：
    - /ws 收到 chat → 推多個 {"type":"delta","text":"..."}
    - 收完所有 chunk 後推 {"type":"response",...}（跟 sync 路徑同格式）
    - 連線不中斷（ping/pong 仍能用）
    """

    @pytest.fixture
    def enable_streaming(self, monkeypatch):
        """打開 SIRO_STREAMING flag + 把 streaming_client 換成 mock"""
        monkeypatch.setattr(state, "use_streaming", True, raising=False)
        yield

    @pytest.fixture
    def mock_streaming_client(self):
        """替換 state.streaming_client：is_available=True、chat_stream 給假 chunk"""
        from bridge.minimax_streaming_client import MiniMaxStreamingClient

        mock = MagicMock(spec=MiniMaxStreamingClient)
        mock.is_available = True

        async def fake_chat_stream(message, system_prompt=None):
            """模擬 LLM 邊生成邊吐 chunk"""
            for chunk in ["你", "好", "，", "Mao", "！"]:
                yield chunk

        mock.chat_stream = fake_chat_stream

        original = state.streaming_client
        state.streaming_client = mock
        yield mock
        state.streaming_client = original

    def test_ws_streaming_pushes_deltas_then_response(
        self, client, mock_hermes_setup, enable_streaming, mock_streaming_client
    ):
        """flag=true 時 /ws 應該推 5 個 delta + 1 個 response（順序正確）"""
        original_parser = state.parser
        state.parser = EmotionParser()
        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "chat",
                    "message": "hi",
                    "user_id": "ws-stream-test",
                })

                # 收 5 個 delta
                deltas = []
                for _ in range(5):
                    msg = ws.receive_json()
                    assert msg["type"] == "delta"
                    deltas.append(msg["text"])
                assert deltas == ["你", "好", "，", "Mao", "！"]

                # 第 6 個是 final response
                final = ws.receive_json()
                assert final["type"] == "response"
                assert final["text"] == "你好，Mao！"
                assert final["emotion"] in ("neutral", "happy")  # 視情緒標籤
                assert "live2d" in final

                # 連線還能用
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"
        finally:
            state.parser = original_parser

    def test_ws_streaming_failure_triggers_fallback_over_ws(
        self, client, mock_hermes_setup, enable_streaming
    ):
        """streaming_client 拋 exception → 走 fallback response（連線不中斷）"""
        from bridge.minimax_streaming_client import MiniMaxStreamingClient

        mock = MagicMock(spec=MiniMaxStreamingClient)
        mock.is_available = True

        async def failing_chat_stream(message, system_prompt=None):
            raise RuntimeError("simulated streaming failure")
            yield  # unreachable, makes it a generator

        mock.chat_stream = failing_chat_stream

        original = state.streaming_client
        state.streaming_client = mock
        original_parser = state.parser
        state.parser = EmotionParser()
        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "chat",
                    "message": "test",
                    "user_id": "ws-stream-fail",
                })

                # 應該直接收 fallback response（沒有 delta）
                data = ws.receive_json()
                assert data["type"] == "response"
                assert isinstance(data["text"], str)
                assert len(data["text"]) > 0
                assert "live2d" in data

                # 連線還能用
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"
        finally:
            state.streaming_client = original
            state.parser = original_parser
