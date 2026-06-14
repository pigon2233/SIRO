"""
bridge/confirmation.py - v1.5+ Confirmation Broker

SIRO 跑危險操作前要 user 確認的機制。

流程：
1. SIRO 工具需要 confirm → 呼叫 broker.request(tool, args, description)
2. Broker 推 WS 訊息給所有已連線的 Unity / Telegram clients
3. Broker 等 asyncio.Future resolve（user 從 WS 推 response）
4. timeout 60s → 自動拒絕
5. 結果回傳給 SIRO 工具

WS 訊息格式：
    Bridge → Client:
        {
            "type": "confirmation_request",
            "confirmation_id": "cf-7f3a9b2c",
            "tool": "run_shell_cmd",
            "args": {"cmd": "apt install foo"},
            "description": "SIRO 想要安裝 foo"
        }
    Client → Bridge:
        {
            "type": "confirmation_response",
            "confirmation_id": "cf-7f3a9b2c",
            "approved": true
        }

Threading：
- broker 在 asyncio 跑（coroutine 等 future）
- WS 收 response 在另一個 async 函式 resolve future
- 不需要額外 lock（asyncio.Future 本來就 single-threaded）
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# Type for the broadcaster function
Broadcaster = Callable[[dict], Awaitable[None]]


class ConfirmationBroker:
    """管理 confirmation request / response

    Usage:
        broker = ConfirmationBroker(broadcaster=ws_broadcast, timeout_sec=60.0)
        # 在 tool executor:
        approved = await broker.request(
            tool="run_shell_cmd",
            args={"cmd": "rm foo.txt"},
            description="SIRO 想要刪 foo.txt",
        )
        if approved:
            # ... 跑指令
    """

    def __init__(
        self,
        broadcaster: Broadcaster,
        timeout_sec: float = 60.0,
        trust_mode: bool = False,
    ):
        """
        Args:
            broadcaster: async 函式、收 dict、推到所有 WS clients
            timeout_sec: 多久沒回應視為拒絕（預設 60s）
            trust_mode: True → 全部 request 自動 approve、不問 user、只 log warning
                （v1.5+ 給 SIRO 完全自主權的選項）
        """
        self._broadcaster = broadcaster
        self._timeout_sec = timeout_sec
        self._pending: dict[str, asyncio.Future[bool]] = {}
        # asyncio.Lock 保護 _pending dict（雖然 asyncio 是 single-threaded、
        # 但 concurrent request/response 可能 race）
        self._lock: Optional[asyncio.Lock] = None
        self._trust_mode = trust_mode

    def _get_lock(self) -> asyncio.Lock:
        """lazy create asyncio.Lock（要等 event loop）"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def request(
        self,
        *,
        tool: str,
        args: dict,
        description: str,
        timeout_sec: Optional[float] = None,
    ) -> bool:
        """送出一個 confirmation request、user 回 yes/no 之前 block

        Args:
            tool: tool name（給 user 看）
            args: tool 的 args（給 user 看）
            description: 人話描述（給 user 看）
            timeout_sec: 覆寫預設 timeout

        Returns:
            bool: user 同意（True）/ user 拒絕或 timeout（False）

        v1.5+ trust_mode=True 時：直接 return True、不問 user、只 log warning
        """
        # v1.5+ trust mode：直接放行
        if self._trust_mode:
            logger.warning(
                f"[confirmation trust_mode] auto-approve：{tool} {description[:100]}"
            )
            return True

        confirmation_id = f"cf-{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        lock = self._get_lock()
        async with lock:
            self._pending[confirmation_id] = future

        # 推 WS 給 user
        msg = {
            "type": "confirmation_request",
            "confirmation_id": confirmation_id,
            "tool": tool,
            "args": args,
            "description": description,
            "timeout_sec": timeout_sec or self._timeout_sec,
        }
        try:
            await self._broadcaster(msg)
        except Exception as e:
            logger.warning(f"[confirmation] broadcast 失敗: {e}")
            # broadcast 失敗就視為拒絕（不冒險執行）
            async with lock:
                self._pending.pop(confirmation_id, None)
            return False

        # 等 user 回
        timeout = timeout_sec or self._timeout_sec
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            logger.info(
                f"[confirmation] {confirmation_id} resolved: "
                f"{'yes' if result else 'no'} ({tool})"
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                f"[confirmation] {confirmation_id} timeout ({timeout}s) "
                f"→ 視為拒絕 ({tool})"
            )
            return False
        finally:
            async with lock:
                self._pending.pop(confirmation_id, None)

    def resolve(self, confirmation_id: str, approved: bool) -> bool:
        """user 推 response 進來時呼叫、resolve 對應 future

        Args:
            confirmation_id: 從 client response 拿
            approved: True=user 同意、False=user 拒絕

        Returns:
            True if future was resolved, False if 找不到或已處理
        """
        # 注意：這個函式是 sync、可能從非 async 路徑呼叫
        # 走 asyncio.Future 的 thread-safe API
        future = self._pending.get(confirmation_id)
        if future is None:
            logger.warning(
                f"[confirmation] resolve 收到未知或過期的 id={confirmation_id}"
            )
            return False
        if future.done():
            logger.warning(
                f"[confirmation] resolve 重複: id={confirmation_id} 已被處理"
            )
            return False

        # 設 result（thread-safe、會 wake up 等 future 的 coroutine）
        future.get_loop().call_soon_threadsafe(future.set_result, approved)
        return True

    def has_pending(self) -> bool:
        """檢查有沒有 pending（debug / test 用）"""
        return len(self._pending) > 0

    def pending_count(self) -> int:
        """pending 數量（test 用）"""
        return len(self._pending)
