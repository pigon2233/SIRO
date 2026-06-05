"""
tests/bridge/test_telegram_bot.py - v1.0 Telegram bot 測試

用 httpx.MockTransport 模擬 Telegram API 回應、測試：
1. 沒設 TELEGRAM_BOT_TOKEN → create_telegram_bot_from_env 回 None
2. Bot 啟動後 polling loop 收到 updates、解析、call LLM、sendMessage 回
3. 白名單過濾（不允許的 chat_id 拒絕）
4. 空訊息 / 非文字訊息處理
5. sendMessage 長度超過 4000 截斷
6. 訊息 LLM 失敗 → 給使用者錯誤訊息

不依賴真 Telegram server、MockTransport 攔 httpx 請求。
"""

from __future__ import annotations

import asyncio
import json
import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock, patch

from bridge.telegram_bot import TelegramBot, create_telegram_bot_from_env


# ==================== Fixtures ====================

@pytest.fixture
def mock_state():
    """mock BridgeState 給 TelegramBot 用（hermes + parser）"""
    state = MagicMock()
    state.hermes = MagicMock()
    state.hermes.is_available.return_value = True
    state.hermes.chat.return_value = MagicMock(
        success=True, output="[emotion:happy] 哈囉！"
    )
    return state


def make_mock_transport(handler):
    """建一個 httpx MockTransport、handler 收到 request 回傳指定 response"""
    return httpx.MockTransport(handler)


def make_getupdates_response(updates=None, ok=True):
    """模擬 Telegram getUpdates API 回應"""
    return {
        "ok": ok,
        "result": updates or [],
    }


# ==================== 工廠 ====================

class TestCreateTelegramBotFromEnv:
    def test_no_token_returns_none(self, monkeypatch):
        """沒設 TELEGRAM_BOT_TOKEN → 回 None、bot 不啟動"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        result = create_telegram_bot_from_env(state=MagicMock())
        assert result is None

    def test_with_token_creates_bot(self, monkeypatch, mock_state):
        """有 token → 建 bot、timeout 跟 allowed 從 env 讀"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-12345")
        monkeypatch.setenv("TELEGRAM_POLLING_TIMEOUT", "10")
        monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111,222,333")
        bot = create_telegram_bot_from_env(state=mock_state)
        assert bot is not None
        assert bot.token == "test-token-12345"
        assert bot.polling_timeout == 10
        assert bot.allowed_chat_ids == {111, 222, 333}

    def test_no_allowed_means_all(self, monkeypatch, mock_state):
        """沒設 allowed → 接受所有 chat_id（白名單 = None）"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
        bot = create_telegram_bot_from_env(state=mock_state)
        assert bot.allowed_chat_ids is None


# ==================== 訊息處理 ====================

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_success(self, mock_state):
        """sendMessage 200 → 回 True"""
        bot = TelegramBot(token="t", state=mock_state)
        received = []
        def handler(request: httpx.Request) -> httpx.Response:
            received.append(request)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))
        ok = await bot._send_message(chat_id=123, text="hello")
        assert ok is True
        assert len(received) == 1
        body = json.loads(received[0].content)
        assert body["chat_id"] == 123
        assert body["text"] == "hello"

    @pytest.mark.asyncio
    async def test_send_message_truncates_long_text(self, mock_state):
        """text > 4000 chars → 截斷 + "..." 尾巴"""
        bot = TelegramBot(token="t", state=mock_state)
        received = []
        def handler(request: httpx.Request) -> httpx.Response:
            received.append(request)
            return httpx.Response(200, json={"ok": True})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))
        long_text = "x" * 5000
        ok = await bot._send_message(chat_id=123, text=long_text)
        assert ok is True
        body = json.loads(received[0].content)
        assert len(body["text"]) == 4000 + 3  # 4000 chars + "..."
        assert body["text"].endswith("...")

    @pytest.mark.asyncio
    async def test_send_message_failure_returns_false(self, mock_state):
        """sendMessage 4xx → 回 False（呼叫端選擇 retry 或忽略）"""
        bot = TelegramBot(token="t", state=mock_state)
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"ok": False, "error": "bad chat_id"})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))
        ok = await bot._send_message(chat_id=999, text="x")
        assert ok is False


# ==================== Update 處理 ====================

class TestHandleUpdate:
    @pytest.mark.asyncio
    async def test_handle_text_message_sends_reply(self, mock_state):
        """收到 text message → 解析 → call LLM → sendMessage 回"""
        bot = TelegramBot(token="t", state=mock_state)
        # 模擬 sendMessage 收到
        sent_messages = []
        def handler(request: httpx.Request) -> httpx.Response:
            if "sendMessage" in str(request.url):
                sent_messages.append(json.loads(request.content))
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            return httpx.Response(200, json={"ok": True, "result": []})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))

        update = {
            "update_id": 100,
            "message": {
                "message_id": 1,
                "chat": {"id": 555, "type": "private"},
                "from": {"id": 555, "first_name": "Alice"},
                "text": "你好",
                "date": 1234567890,
            }
        }
        await bot._handle_update(update)

        # 確認 LLM 被 call
        mock_state.hermes.chat.assert_called_once()
        # 確認 sendMessage 被 call 一次、內容包含 LLM 回應
        assert len(sent_messages) == 1
        assert sent_messages[0]["chat_id"] == 555
        assert "哈囉" in sent_messages[0]["text"]  # LLM 回 "[emotion:happy] 哈囉！"、parser 去掉 emotion tag

    @pytest.mark.asyncio
    async def test_handle_empty_text_rejects(self, mock_state):
        """text 空白（貼圖、純空白）→ 提示「只支援文字」"""
        bot = TelegramBot(token="t", state=mock_state)
        sent_messages = []
        def handler(request: httpx.Request) -> httpx.Response:
            sent_messages.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))

        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 555, "type": "private"},
                "from": {"id": 555, "first_name": "Bob"},
                "text": "  ",  # 純空白
                "date": 0,
            }
        }
        await bot._handle_update(update)
        # 送了一條「只支援文字訊息」回應
        assert len(sent_messages) == 1
        assert "只支援文字" in sent_messages[0]["text"]

    @pytest.mark.asyncio
    async def test_handle_non_text_message_rejects(self, mock_state):
        """text 缺（貼圖、照片）→ 提示「只支援文字」"""
        bot = TelegramBot(token="t", state=mock_state)
        sent_messages = []
        def handler(request: httpx.Request) -> httpx.Response:
            sent_messages.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))

        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 555, "type": "private"},
                "from": {"id": 555, "first_name": "Bob"},
                # 沒 text 欄位（貼圖）
                "sticker": {"file_id": "abc"},
                "date": 0,
            }
        }
        await bot._handle_update(update)
        assert len(sent_messages) == 1
        assert "只支援文字" in sent_messages[0]["text"]

    @pytest.mark.asyncio
    async def test_whitelist_blocks_unauthorized_chat(self, mock_state):
        """白名單外的 chat_id → 拒絕、不送訊息"""
        bot = TelegramBot(
            token="t", state=mock_state, allowed_chat_ids={999}
        )
        sent_messages = []
        def handler(request: httpx.Request) -> httpx.Response:
            sent_messages.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))

        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 555, "type": "private"},  # 不在白名單
                "from": {"id": 555, "first_name": "Eve"},
                "text": "hi",
                "date": 0,
            }
        }
        await bot._handle_update(update)
        # 沒送任何訊息
        assert len(sent_messages) == 0
        # 也沒 call LLM
        mock_state.hermes.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_llm_failure_sends_error_message(self, mock_state):
        """LLM 失敗 → 送錯誤訊息給 user（不丟水溝）"""
        mock_state.hermes.chat.return_value = MagicMock(
            success=False, output="", error="MiniMax API timeout"
        )
        bot = TelegramBot(token="t", state=mock_state)
        sent_messages = []
        def handler(request: httpx.Request) -> httpx.Response:
            sent_messages.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))

        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 555, "type": "private"},
                "from": {"id": 555, "first_name": "Carol"},
                "text": "test",
                "date": 0,
            }
        }
        await bot._handle_update(update)
        assert len(sent_messages) == 1
        # 錯誤訊息有包含 LLM 錯誤原因
        assert "失敗" in sent_messages[0]["text"] or "失敗" in sent_messages[0]["text"]

    @pytest.mark.asyncio
    async def test_handle_no_hermes_sends_unavailable(self, mock_state):
        """hermes 不可用 → 送「LLM 暫時不能用」"""
        mock_state.hermes = None
        bot = TelegramBot(token="t", state=mock_state)
        sent_messages = []
        def handler(request: httpx.Request) -> httpx.Response:
            sent_messages.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        bot._client = httpx.AsyncClient(transport=make_mock_transport(handler))

        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 555, "type": "private"},
                "from": {"id": 555, "first_name": "Dan"},
                "text": "test",
                "date": 0,
            }
        }
        await bot._handle_update(update)
        assert len(sent_messages) == 1
        assert "不能用" in sent_messages[0]["text"]


# ==================== Polling ====================

class TestPolling:
    @pytest.mark.asyncio
    async def test_poll_loop_processes_updates(self, mock_state):
        """polling 收到 updates → 處理 → 更新 offset

        直接 stub _get_updates、不用 httpx MockTransport（避免 long poll
        timeout 在測試 event loop 卡住、跨測試 async 干擾）
        """
        bot = TelegramBot(token="t", state=mock_state)

        # 第一次回 2 個 update、第二次回空
        call_count = [0]
        async def fake_get_updates():
            call_count[0] += 1
            if call_count[0] == 1:
                return [
                    {"update_id": 100, "message": {
                        "message_id": 1, "chat": {"id": 555, "type": "private"},
                        "from": {"id": 555, "first_name": "A"},
                        "text": "first", "date": 0
                    }},
                    {"update_id": 101, "message": {
                        "message_id": 2, "chat": {"id": 555, "type": "private"},
                        "from": {"id": 555, "first_name": "A"},
                        "text": "second", "date": 0
                    }},
                ]
            # 第二次：停
            bot._running = False
            return []

        # 把 _send_message 改成 mock（避免 httpx 呼叫）
        async def fake_send(chat_id, text):
            return True

        bot._get_updates = fake_get_updates
        bot._send_message = fake_send
        bot._running = True

        # 跑 poll loop 一次、輪到第二次 fake_get_updates 會把 _running 關掉、退出
        await bot._poll_loop()

        # 確認 hermes.chat 被 call 兩次（兩個 update）
        assert mock_state.hermes.chat.call_count == 2
        # 確認 offset 跑到 102
        assert bot._offset == 102
