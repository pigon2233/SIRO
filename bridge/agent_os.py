"""
bridge/agent_os.py - SIRO 「後台作業系統」

單 process 內的多工調度 — 把 bridge 從「純 HTTP server」升級成「像作業系統一樣」。

三個核心元件：
- TaskQueue: asyncio.Queue — 背景任務 FIFO
- EventBus: in-process pub/sub — 任務完成發事件、handlers 訂閱
- WorkerLoop: asyncio.Task — background worker 從 queue 拉任務執行

設計動機（Phase 1.75+ 演化）：
- 使用者要「後台像正常作業系統一樣」 — 任務序列、多 LLM 並行、事件匯流
- 多觸發源：UI 點 Live2D / Telegram 訊息 / 排程 → 都要能 enqueue task
- 任務完成 → 透過 event bus 推給 UI 或其他 handler

v0.2 範圍：
- Task + Event bus 基本功能
- Worker pool（3 個 default）
- 第一個 task: LLM reply（包現有 /chat 跟 /ws 的 hermes 呼叫）
- async 介面（FastAPI 可 await）

v0.2 不做：
- Telegram 整合（v1）
- 排程/cron（v1）
- 持久化（v2）
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

logger = logging.getLogger("siro.agent_os")


# ==================== Data 類別 ====================

@dataclass
class Task:
    """一個背景任務

    Attributes:
        name: 給 log / 除錯用的任務名（例 "llm.reply"）
        coro: 要執行的 async 函式
        id: 唯一 ID，UUID4，用於 event bus 比對 (v0.3 AgentOS 接 endpoint)
        kwargs: 傳給 coro 的參數
        created_at: enqueue 時間（unix time）
    """
    name: str
    coro_factory: Callable[..., Awaitable[Any]]  # 傳 *args, **kwargs 回 coroutine
    id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:8])
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    async def run(self) -> Any:
        """執行 task（worker 呼叫）"""
        return await self.coro_factory(*self.args, **self.kwargs)


@dataclass
class Event:
    """in-process 事件

    Attributes:
        type: 事件類型（例 "llm.reply", "task.completed"）
        data: 事件資料（dict，handler 自行解讀）
        source: 觸發事件者（task name、user_id、etc.）方便除錯
    """
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    timestamp: float = field(default_factory=time.time)


# ==================== EventBus ====================

class EventBus:
    """In-process pub/sub

    簡單實作：subscriber 是 async callable
    - 同步 handler 會被包成 coroutine
    - 拋出 exception 不會影響其他 subscriber
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Event], Awaitable[None]]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Event], Union[None, Awaitable[None]]]) -> Callable[[], None]:
        """訂閱事件

        Args:
            event_type: "*" 匹配所有事件
            handler: sync 或 async callable，接收 Event

        Returns:
            unsubscribe 函式 — 呼叫後取消訂閱（避免 memory leak / 殘留 handler）
        """
        async def wrap(event: Event):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(f"[EventBus] handler 對 {event_type} 拋 exception")

        self._subscribers.setdefault(event_type, []).append(wrap)
        logger.debug(f"[EventBus] 訂閱 {event_type}（共 {len(self._subscribers[event_type])} 個）")

        def unsubscribe() -> None:
            """取消這個 handler 對這個 event_type 的訂閱"""
            if event_type in self._subscribers:
                self._subscribers[event_type] = [
                    w for w in self._subscribers[event_type] if w is not wrap
                ]
                logger.debug(f"[EventBus] 取消訂閱 {event_type}（剩 {len(self._subscribers[event_type])} 個）")

        return unsubscribe

    async def emit(self, event: Event):
        """發事件 — 給所有訂閱者（type 完全匹配 + "*" 萬用）"""
        handlers = list(self._subscribers.get(event.type, [])) + list(self._subscribers.get("*", []))
        if not handlers:
            logger.debug(f"[EventBus] emit {event.type} 沒人訂閱")
            return
        logger.debug(f"[EventBus] emit {event.type} → {len(handlers)} 個 handlers")
        # 全部並行觸發（事件 handler 互不阻塞）
        await asyncio.gather(*[h(event) for h in handlers], return_exceptions=False)


# ==================== TaskQueue + Workers ====================

class AgentOS:
    """SIRO 後台作業系統

    用法：
        os = AgentOS()
        await os.start(num_workers=3)

        os.enqueue(Task(name="llm.reply", coro_factory=do_llm, args=("hi",)))

        os.event_bus.subscribe("llm.reply", on_llm_reply)

        await os.stop()
    """

    def __init__(self):
        self.task_queue: asyncio.Queue[Task] = asyncio.Queue()
        self.event_bus = EventBus()
        self._workers: List[asyncio.Task] = []
        self._stopped = False
        self._processed_count = 0  # 累計完成的 task 數

    # ==================== Lifecycle ====================

    async def start(self, num_workers: int = 3):
        """啟動 worker pool

        Args:
            num_workers: 平行 worker 數。建議 3-5 個。
        """
        if self._workers:
            logger.warning("[AgentOS] 已經啟動，跳過")
            return

        logger.info(f"[AgentOS] 啟動 {num_workers} 個 worker")
        self._stopped = False
        for i in range(num_workers):
            worker_id = i + 1
            worker = asyncio.create_task(self._worker_loop(worker_id), name=f"agent-os-worker-{worker_id}")
            self._workers.append(worker)

    async def stop(self):
        """停止 worker pool（會等目前 task 跑完）"""
        if self._stopped:
            return
        logger.info("[AgentOS] 停止中...")
        self._stopped = True

        # 等 queue 消化完（不接新 task）
        await self.task_queue.join()

        # 取消所有 worker
        for w in self._workers:
            w.cancel()
        # 等取消完成
        for w in self._workers:
            try:
                await w
            except asyncio.CancelledError:
                pass

        self._workers.clear()
        logger.info(f"[AgentOS] 停止完成（累計處理 {self._processed_count} 個 task）")

    # ==================== Enqueue / Workers ====================

    def enqueue(self, task: Task) -> None:
        """丟任務到 queue（同步介面，FastAPI endpoint 內可直接呼叫）

        適合：需要 LLM 的慢任務（chat、persona 切換帶情緒分析等）
        排隊：FIFO、可能被前面的 LLM task 阻塞
        """
        if self._stopped:
            logger.warning(f"[AgentOS] 已停止，拒收 task {task.name}")
            return
        logger.debug(f"[AgentOS] enqueue {task.name} (queue size: {self.task_queue.qsize()})")
        # put_nowait 因為 queue 是無限大的（asyncio.Queue() 預設無上限）
        self.task_queue.put_nowait(task)

    def enqueue_fast(self, task: Task) -> asyncio.Task:
        """跳過 queue、直接 spawn background coroutine 跑 task

        v1.2+ 給 SendTask（Unity 端點擊 Mao）用：
        - mood.set / motion.play / persona.switch / chat.say / chat.summon
          都不需要 LLM、< 100ms 就跑完
        - 走 queue 會被前面的 LLM task 拖到 100s+、點 Mao 沒反應
        - 走 fast lane 跟 LLM task 平行、立即執行

        行為：
        1. asyncio.create_task 立即 spawn（不排隊）
        2. 跑完自動 emit task.completed / task.failed event（跟 enqueue 一致）
        3. 失敗也不 raise、跟 worker 一樣繼續
        4. 回傳 asyncio.Task 讓 caller 可以 await 或 cancel

        注意：fast lane 沒有持久化 / 沒有 crash recovery
        （LIFO queue 才有 task_done() 機制保證）— 不適合慢任務。
        適合：< 1s 的即時互動任務。
        """
        if self._stopped:
            logger.warning(f"[AgentOS] 已停止，拒收 fast task {task.name}")
            # 已停止時 spawn 一個 no-op task 避免 caller crash
            return asyncio.create_task(asyncio.sleep(0))

        logger.debug(f"[AgentOS] enqueue_fast {task.name} (bypass queue, parallel)")

        async def _run_fast():
            """跟 _execute_task 一樣、但走 create_task 不走 queue"""
            duration_ms = (time.time() - task.created_at) * 1000
            t0 = time.time()
            try:
                result = await task.run()
                run_ms = (time.time() - t0) * 1000
                logger.info(
                    f"[AgentOS] fast {task.name}[id={task.id}] 完成 "
                    f"(queue 等待 {duration_ms:.0f}ms, 跑 {run_ms:.0f}ms)"
                )
                await self.event_bus.emit(Event(
                    type="task.completed",
                    data={"task": task.name, "task_id": task.id, "result": result, "duration_ms": run_ms},
                    source="fast-lane",
                ))
                return result
            except Exception as e:
                run_ms = (time.time() - t0) * 1000
                logger.exception(
                    f"[AgentOS] fast {task.name}[id={task.id}] 失敗 ({run_ms:.0f}ms): {e}"
                )
                await self.event_bus.emit(Event(
                    type="task.failed",
                    data={"task": task.name, "task_id": task.id, "error": str(e), "traceback": traceback.format_exc()},
                    source="fast-lane",
                ))
                # 不 raise — 跟 worker 一樣

        return asyncio.create_task(_run_fast())

    async def _worker_loop(self, worker_id: int):
        """單一 worker 的主迴圈"""
        logger.debug(f"[AgentOS] worker {worker_id} 啟動")
        try:
            while not self._stopped:
                try:
                    task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # 定期檢查 _stopped

                await self._execute_task(worker_id, task)
                self.task_queue.task_done()
                self._processed_count += 1
        except asyncio.CancelledError:
            logger.debug(f"[AgentOS] worker {worker_id} 被取消")
            raise
        except Exception:
            logger.exception(f"[AgentOS] worker {worker_id} crashed")
            raise

    async def _execute_task(self, worker_id: int, task: Task):
        """執行單一 task + 自動發 task.completed / task.failed 事件

        v0.3 改：event data 帶 task_id，caller 可用 wait_for_task() 對應到自己 enqueue 的 task
        """
        duration_ms = (time.time() - task.created_at) * 1000
        logger.info(
            f"[AgentOS] worker {worker_id} 跑 {task.name}[id={task.id}] "
            f"(queue 等待 {duration_ms:.0f}ms)"
        )
        t0 = time.time()
        try:
            result = await task.run()
            run_ms = (time.time() - t0) * 1000
            logger.info(f"[AgentOS] {task.name}[id={task.id}] 完成 ({run_ms:.0f}ms)")
            await self.event_bus.emit(Event(
                type="task.completed",
                data={"task": task.name, "task_id": task.id, "result": result, "duration_ms": run_ms},
                source=f"worker-{worker_id}",
            ))
            return result
        except Exception as e:
            run_ms = (time.time() - t0) * 1000
            logger.exception(f"[AgentOS] {task.name}[id={task.id}] 失敗 ({run_ms:.0f}ms)")
            await self.event_bus.emit(Event(
                type="task.failed",
                data={"task": task.name, "task_id": task.id, "error": str(e), "traceback": traceback.format_exc()},
                source=f"worker-{worker_id}",
            ))
            # 不 raise — worker loop 繼續跑下一個 task

    # ==================== 統計 ====================

    @property
    def queue_size(self) -> int:
        return self.task_queue.qsize()

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    @property
    def processed_count(self) -> int:
        return self._processed_count

    # ==================== v0.3 給 endpoint 用的 helper ====================

    async def wait_for_task(
        self,
        task_name: str,
        task_id: str,
        *,
        timeout: float = 600.0,
    ) -> Optional[Dict[str, Any]]:
        """等指定 task_id 的 task.completed / task.failed 事件

        用法（典型 /chat endpoint）：
            task = create_llm_reply_task(state=state, user_id="u1", message="hi")
            state.agent_os.enqueue(task)
            result = await state.agent_os.wait_for_task(
                task_name="llm.reply",
                task_id=task.id,
                timeout=600.0,
            )
            if result is None:  # timeout
                return fallback
            if "error" in result:  # failed
                return fallback
            return ChatResponse(**result["result"])

        Args:
            task_name: 等的 task name（用 task name 過濾避免其他 task 干擾）
            task_id: Task.id，用 UUID 唯一辨識
            timeout: 最長等多久（秒），預設 600s

        Returns:
            task.completed 事件的 data dict（含 "result" key），
            或 task.failed 事件的 data dict（含 "error" key），
            或 None（timeout）

        Note:
            timeout 不會 cancel task，task 仍會在 worker 跑完。
        """
        fut: asyncio.Future = asyncio.get_event_loop().create_future()

        def on_done(event: Event):
            if event.data.get("task") != task_name:
                return  # 其他 task 的事件，忽略
            if event.data.get("task_id") != task_id:
                return  # 同名 task 但不同 id，忽略
            if not fut.done():
                if event.type == "task.completed":
                    fut.set_result(event.data)
                elif event.type == "task.failed":
                    # 把 failed 事件包成「特殊結果」回傳，讓 caller 判斷
                    fut.set_result({"__failed__": True, **event.data})

        unsub_completed = self.event_bus.subscribe("task.completed", on_done)
        unsub_failed = self.event_bus.subscribe("task.failed", on_done)

        try:
            try:
                result = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"[AgentOS] wait_for_task({task_name}[{task_id}]) timeout ({timeout}s)"
                )
                return None
            if result.get("__failed__"):
                # 去掉內部 marker，回 caller 處理
                result.pop("__failed__", None)
            return result
        finally:
            unsub_completed()
            unsub_failed()
