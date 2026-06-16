"""bridge.conversation — Per-turn conversation task management (Pattern 4)。

對應 design: docs/STT_INTEGRATION.md §`bridge/conversation.py` Pattern 4 完整 port。

設計:
- 每個 Unity 連線一個 `TurnManager` instance(per-WebSocket local,不是 global)
- 每輪對話(text_input / mic_chunk → STT → LLM → TTS)是一個 `asyncio.Task`
- 新 turn 進來時,**取消舊 task**(`task.cancel()` → 自然 raise `asyncio.CancelledError` → 跑 cleanup)
- turn_id 由 Unity 產生、bridge 收到後用它來 cancel 舊 + 開新
- 這就是 O-LLVT 的 Pattern 4 — 用 asyncio 原生 cancel 機制,不用手寫 queue 處理

User 硬約束 #2「講話中或還沒講話的時候就給他新的對話不會抱錯」就靠這個:
- 舊 task 被 cancel → 它的 TTS streaming tasks / LLM SSE call 全部 raise CancelledError
- finally block 跑 cleanup(取消 background TTS task、清 audio buffer)
- 新 task 完全獨立、不等舊的清完

不 crash 保證:
- Task 被 cancel 不 raise 給 caller
- await task 時用 try/except CancelledError 吃掉
- LLM streaming task 內部收到 CancelledError 也走 finally 釋放
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from loguru import logger


class ConversationTask:
    """包一個 asyncio.Task、掛 turn_id + 提供 cancel + 等待 done。

    Pattern 4 實作:cancel 透過 asyncio.CancelledError 傳遞,舊 task 內部
    的 await 收到 CancelledError → 跑 finally cleanup。

    用法:
        task = ConversationTask(turn_id=5, run_fn=my_async_func)
        task.start()
        # 之後想取消:
        task.cancel()
        await task.wait_done()  # 等 cleanup 跑完
    """

    def __init__(
        self,
        turn_id: int,
        run_fn: Callable[[], Awaitable[None]],
        name: Optional[str] = None,
    ):
        self.turn_id = turn_id
        self._run_fn = run_fn
        self._task: Optional[asyncio.Task] = None
        self._name = name or f"conv-{turn_id}"

    def start(self) -> None:
        """啟動 background task。已經在跑就忽略(冪等)。"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_with_cancel_log(), name=self._name)

    async def _run_with_cancel_log(self) -> None:
        """跑 run_fn、收到 CancelledError log 後 re-raise。"""
        try:
            await self._run_fn()
        except asyncio.CancelledError:
            logger.info(f"🤡👍 Conversation turn {self.turn_id} cancelled")
            raise
        except Exception as e:
            logger.error(f"Conversation turn {self.turn_id} failed: {e}")
            raise

    def cancel(self) -> None:
        """要求 task 取消(非阻塞)。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def wait_done(self, timeout: Optional[float] = 2.0) -> None:
        """等 task 結束(給 cancel 後 cleanup 用)。"""
        if self._task is None or self._task.done():
            return
        try:
            if timeout is not None:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
            else:
                await asyncio.shield(self._task)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning(f"Conversation turn {self.turn_id} wait_done timeout")
        except Exception:
            pass

    @property
    def done(self) -> bool:
        return self._task is None or self._task.done()

    @property
    def task(self) -> Optional[asyncio.Task]:
        return self._task


class TurnManager:
    """管理「目前進行中」的 conversation task。

    新 turn 進來時:
    1. 取消舊 task(Pattern 4)
    2. 等待舊 task cleanup(短 timeout)
    3. 開新 task

    一個 TurnManager = 一個 Unity WS 連線的 state。
    """

    def __init__(self):
        self._current: Optional[ConversationTask] = None
        self._current_turn_id: int = 0
        # track 總 turn 數(debug 用)
        self._total_started: int = 0

    @property
    def current_turn_id(self) -> int:
        return self._current_turn_id

    @property
    def has_running_task(self) -> bool:
        return self._current is not None and not self._current.done

    async def start_new_turn(
        self,
        turn_id: int,
        run_fn: Callable[[], Awaitable[None]],
    ) -> ConversationTask:
        """取消舊 task、開新 task。

        Args:
            turn_id: Unity 產生的 monotonic counter(> 0)。
            run_fn: 新 turn 要跑的 async 函式(通常 = LLM streaming + TTS 串接)。

        Returns:
            新的 ConversationTask instance。
        """
        # 1. 取消舊 task
        if self._current is not None and not self._current.done:
            old_turn = self._current.turn_id
            logger.info(
                f"🔄 TurnManager: cancel old turn {old_turn} (new turn {turn_id})"
            )
            self._current.cancel()
            # 2. 等待 cleanup(短 timeout,不等太久免得卡 WS receive loop)
            await self._current.wait_done(timeout=1.0)

        # 3. 開新 task
        self._current_turn_id = turn_id
        self._current = ConversationTask(turn_id, run_fn)
        self._current.start()
        self._total_started += 1
        logger.debug(f"▶ TurnManager: started turn {turn_id} (total={self._total_started})")
        return self._current

    def cancel_current(self) -> None:
        """取消目前 task(不開新的,給 client 端想純停止用)。"""
        if self._current is not None and not self._current.done:
            self._current.cancel()

    async def wait_current_done(self, timeout: float = 2.0) -> None:
        """等目前 task 結束。"""
        if self._current is not None:
            await self._current.wait_done(timeout=timeout)

    def reset(self) -> None:
        """重置 state(WS 斷線時呼叫)。"""
        if self._current is not None and not self._current.done:
            self._current.cancel()
        self._current = None
        self._current_turn_id = 0
