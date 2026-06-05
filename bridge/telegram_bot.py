"""
bridge/telegram_bot.py - v1.0 Telegram 整合

設計：
- polling 模式（不設 webhook、v0.x 階段最簡單）
- 用 httpx 直接打 Telegram Bot API（不依賴 python-telegram-bot 套件、少一層 dependency）
- 訊息流：polling → 收 Telegram message → 直接 call hermes → sendMessage 回 Telegram
  （不走 AgentOS queue、v1.0 MVP 簡單版；v1.5+ 改成 enqueue task）
- 環境變數：
  - TELEGRAM_BOT_TOKEN：必填、從 @BotFather 拿
  - TELEGRAM_POLLING_TIMEOUT=30：long polling timeout（秒、Telegram 建議 < 30）
  - TELEGRAM_ALLOWED_CHAT_IDS=123,456：白名單、沒設就接受所有（不安全、開發用）

用法：
  TELEGRAM_BOT_TOKEN=xxx python -m bridge.main
  → lifespan 自動啟動 polling
  → 用戶在 Telegram 傳訊息給 bot
  → bridge 收到、call LLM、sendMessage 回

測試：
  - httpx.MockTransport 模擬 Telegram API 回應
  - 驗證 polling loop 行為
  - 驗證訊息 → LLM → sendMessage 流程
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("siro.telegram")


class TelegramBot:
    """v1.0 Telegram 整合（polling 模式）

    Attributes:
        token: Telegram Bot API token
        state: BridgeState（用來拿 hermes、ollama、persona_config）
        polling_timeout: long polling timeout（秒）
        allowed_chat_ids: 白名單（None = 接受所有）
    """

    TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
    MAX_MESSAGE_LENGTH = 4000  # Telegram 訊息上限 4096、留 buffer 給 "..."
    POLL_INTERVAL_ERROR = 5  # polling 錯誤時等 5s 重試（避免狂打 API）

    def __init__(
        self,
        token: str,
        state,
        polling_timeout: int = 30,
        allowed_chat_ids: Optional[list[int]] = None,
        system_prompt: Optional[str] = None,
    ):
        self.token = token
        self.state = state
        self.polling_timeout = polling_timeout
        self.allowed_chat_ids = set(allowed_chat_ids) if allowed_chat_ids else None
        self.system_prompt = system_prompt or "你是一個親切的 AI 助理，請用繁體中文簡短回應。"
        self._offset = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._base_url = self.TELEGRAM_API_BASE.format(token=token)

    # ==================== Lifecycle ====================

    async def start(self) -> None:
        """啟動 polling loop（在 lifespan 內呼叫）"""
        if self._running:
            logger.warning("[Telegram] start() 重複呼叫、忽略")
            return
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.polling_timeout + 10)
        )
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"[Telegram] bot polling 啟動 "
            f"(timeout={self.polling_timeout}s, "
            f"whitelist={len(self.allowed_chat_ids) if self.allowed_chat_ids else 'all'})"
        )

    async def stop(self) -> None:
        """停止 polling（在 lifespan 關閉時呼叫）"""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("[Telegram] bot polling 停止")

    # ==================== Polling loop ====================

    async def _poll_loop(self) -> None:
        """主迴圈：long poll → 拿一批 updates → 一個一個處理"""
        logger.info("[Telegram] poll loop 開始跑")
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    if not self._running:
                        break
                    await self._handle_update(update)
            except asyncio.CancelledError:
                logger.info("[Telegram] poll loop 被 cancel")
                break
            except Exception as e:
                logger.warning(
                    f"[Telegram] poll 錯誤、{self.POLL_INTERVAL_ERROR}s 後重試: {type(e).__name__}: {e}"
                )
                await asyncio.sleep(self.POLL_INTERVAL_ERROR)
        logger.info("[Telegram] poll loop 結束")

    async def _get_updates(self) -> list[dict]:
        """long poll 拿一批 updates（timeout 是 long poll 等待時間）"""
        url = f"{self._base_url}/getUpdates"
        params = {
            "offset": self._offset,
            "timeout": self.polling_timeout,
            "allowed_updates": ["message"],
        }
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data}")
        return data.get("result", [])

    # ==================== Update 處理 ====================

    async def _handle_update(self, update: dict) -> None:
        """處理一筆 update：filter 訊息、call LLM、回 Telegram"""
        # update_id 是單調遞增的、拿來當下次 poll 的 offset
        self._offset = max(self._offset, update.get("update_id", 0) + 1)

        # 只處理訊息類型（不處理 edited_message、callback_query 等 v1.0 用不到）
        message = update.get("message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        if not text:
            # 沒文字（貼圖、照片、語音）v1.0 不支援
            await self._send_message(chat_id, "（目前只支援文字訊息）")
            return

        # 白名單
        if self.allowed_chat_ids is not None and chat_id not in self.allowed_chat_ids:
            logger.warning(f"[Telegram] 拒絕 chat_id={chat_id} (不在白名單)")
            return

        user = message.get("from", {})
        user_id = str(user.get("id", chat_id))
        user_name = user.get("first_name", "")

        logger.info(
            f"[Telegram] chat_id={chat_id} user={user_name} ({user_id}) text={text!r}"
        )

        # Call LLM（同步 hermes.chat 跑在 thread pool、避免 block event loop）
        reply_text = await self._generate_reply(text, user_id, user_name)
        await self._send_message(chat_id, reply_text)

    async def _generate_reply(self, text: str, user_id: str, user_name: str) -> str:
        """call LLM 拿回應文字（給 _handle_update 用）

        失敗回固定錯誤訊息（讓 Telegram user 知道 bot 有收到、不是丟水溝）
        """
        # 沒有 hermes → 直接降級
        if not self.state.hermes or not self.state.hermes.is_available():
            return "（LLM 暫時不能用、稍後再試）"

        try:
            result = await asyncio.to_thread(
                self.state.hermes.chat,
                message=text,
                system_prompt=self.system_prompt,
            )
            if not result.success:
                logger.warning(f"[Telegram] LLM 失敗: {result.error}")
                return f"（LLM 回應失敗：{result.error}）"
            # 解析情緒標籤（如果有）
            from .emotion_parser import EmotionParser
            from .prompts import get_persona_expressions
            expressions = get_persona_expressions("siro-default")
            parser = EmotionParser(persona_expressions=expressions)
            clean_text, emotion, intensity = parser.parse(result.output, user_input=text)
            logger.info(
                f"[Telegram] LLM 回: {clean_text[:60]!r} emotion={emotion.value}"
            )
            return clean_text
        except Exception as e:
            logger.exception(f"[Telegram] LLM 呼叫例外: {e}")
            return f"（處理失敗：{type(e).__name__}）"

    async def _send_message(self, chat_id: int, text: str) -> bool:
        """送訊息回 Telegram

        Returns: True 成功、False 失敗
        """
        if not text:
            return True  # 空訊息不送
        # Telegram 上限 4096、留 buffer
        if len(text) > self.MAX_MESSAGE_LENGTH:
            text = text[: self.MAX_MESSAGE_LENGTH] + "..."

        try:
            resp = await self._client.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            if resp.status_code != 200:
                logger.warning(
                    f"[Telegram] sendMessage 失敗: {resp.status_code} {resp.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"[Telegram] sendMessage 例外: {e}")
            return False


# ==================== 工廠函式 ====================

def create_telegram_bot_from_env(state) -> Optional[TelegramBot]:
    """從環境變數建 Telegram bot、沒設 token 就回 None

    在 lifespan 內呼叫：
      bot = create_telegram_bot_from_env(state)
      if bot:
          await bot.start()
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    polling_timeout = int(os.environ.get("TELEGRAM_POLLING_TIMEOUT", "30"))
    allowed_str = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    allowed = [int(x) for x in allowed_str.split(",") if x.strip().isdigit()] if allowed_str else None
    logger.info(
        f"[Telegram] 建立 bot "
        f"(timeout={polling_timeout}s, allowed_chat_ids={allowed or 'all'})"
    )
    return TelegramBot(
        token=token,
        state=state,
        polling_timeout=polling_timeout,
        allowed_chat_ids=allowed,
    )
