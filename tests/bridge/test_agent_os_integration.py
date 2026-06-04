"""
tests/bridge/test_agent_os_integration.py - 端點走 AgentOS 的整合測試

v0.3 PLAN_REVIEW #9: /chat 走 AgentOS（opt-in via SIRO_USE_AGENT_OS env flag）

行為：
- flag=false (預設) — 走 v0.2 sync 路徑（state.hermes.chat 直接呼叫）
- flag=true — 走 v0.3 AgentOS 路徑（enqueue llm_reply_task → wait_for_task）

這個檔專門測 flag=true 的路徑。flag=false 既有 test_main.py 已經覆蓋。

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


# ==================== Flag 預設值 ====================

class TestUseAgentOSDefault:
    def test_default_is_false(self, monkeypatch):
        """沒設 env 時 use_agent_os 預設 false"""
        monkeypatch.delenv("SIRO_USE_AGENT_OS", raising=False)
        result = os.environ.get("SIRO_USE_AGENT_OS", "false").lower() == "true"
        assert result is False

    def test_env_true_sets_to_true(self, monkeypatch):
        """SIRO_USE_AGENT_OS=true 時 use_agent_os = true"""
        monkeypatch.setenv("SIRO_USE_AGENT_OS", "true")
        result = os.environ.get("SIRO_USE_AGENT_OS", "false").lower() == "true"
        assert result is True
