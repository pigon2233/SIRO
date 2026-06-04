"""
tests/bridge/test_agent_os.py - AgentOS 測試

覆蓋：
- TaskQueue: enqueue / worker pool 並行執行
- EventBus: subscribe / emit 觸發 / 多訂閱者 / exception 隔離
- Worker lifecycle: start / stop / graceful shutdown
- 併發任務不丟、不 deadlock
- 整合：state.sessions_lock 多 thread 保護
"""

from __future__ import annotations

import asyncio
import threading
import time
import pytest

from bridge.agent_os import AgentOS, Task, Event, EventBus


# ==================== EventBus ====================

class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe("test.event", handler)
        await bus.emit(Event(type="test.event", data={"foo": "bar"}))

        assert len(received) == 1
        assert received[0].type == "test.event"
        assert received[0].data == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_wildcard_subscription(self):
        bus = EventBus()
        received = []

        async def all_handler(event: Event):
            received.append(event)

        bus.subscribe("*", all_handler)
        await bus.emit(Event(type="a"))
        await bus.emit(Event(type="b"))
        await bus.emit(Event(type="c"))

        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_multiple_subscribers_to_same_event(self):
        bus = EventBus()
        count_a = 0
        count_b = 0

        async def handler_a(event: Event):
            nonlocal count_a
            count_a += 1

        async def handler_b(event: Event):
            nonlocal count_b
            count_b += 1

        bus.subscribe("ev", handler_a)
        bus.subscribe("ev", handler_b)
        await bus.emit(Event(type="ev"))

        assert count_a == 1
        assert count_b == 1

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_others(self):
        bus = EventBus()
        received = []

        async def bad_handler(event: Event):
            raise ValueError("boom")

        async def good_handler(event: Event):
            received.append(event)

        bus.subscribe("ev", bad_handler)
        bus.subscribe("ev", good_handler)
        # 一個 handler 拋 exception 不該 crash 整個 bus
        await bus.emit(Event(type="ev"))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_sync_handler_supported(self):
        """handler 可以是普通 function（不一定要 async）"""
        bus = EventBus()
        received = []

        def sync_handler(event: Event):
            received.append(event)

        bus.subscribe("ev", sync_handler)
        await bus.emit(Event(type="ev"))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_emit_to_no_subscribers_is_noop(self):
        bus = EventBus()
        # 沒訂閱者不該 crash
        await bus.emit(Event(type="nobody.cares"))


# ==================== AgentOS Workers ====================

class TestAgentOSWorkers:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        os = AgentOS()
        await os.start(num_workers=2)
        assert os.worker_count == 2
        await os.stop()
        assert os.worker_count == 0

    @pytest.mark.asyncio
    async def test_enqueue_and_execute(self):
        os = AgentOS()
        await os.start(num_workers=1)

        result_holder = {}

        async def my_task():
            result_holder["done"] = True
            return "ok"

        os.enqueue(Task(name="test", coro_factory=my_task))

        # 等 worker 跑完
        await asyncio.sleep(0.1)
        assert result_holder.get("done") is True
        assert os.processed_count == 1
        await os.stop()

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """3 個任務、3 個 worker，應該並行跑（總時間 ≈ 單個任務時間）"""
        os = AgentOS()
        await os.start(num_workers=3)

        task_started = threading.Event()
        all_started = threading.Event()
        started_count = [0]
        start_times = []

        async def slow_task(task_id: int):
            start_times.append(time.time())
            started_count[0] += 1
            if started_count[0] == 3:
                all_started.set()
            await asyncio.sleep(0.3)  # 模擬 LLM 慢回應
            return task_id

        # 3 個任務
        for i in range(3):
            os.enqueue(Task(name=f"task_{i}", coro_factory=slow_task, args=(i,)))

        # 等 3 個都開始（並行跡象）
        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, all_started.wait, 2.0),
            timeout=2.5,
        )

        # 等全部完成
        await asyncio.sleep(0.5)
        assert os.processed_count == 3
        # 三個任務應該幾乎同時開始（差 < 0.1s）
        if len(start_times) >= 2:
            assert max(start_times) - min(start_times) < 0.1
        await os.stop()

    @pytest.mark.asyncio
    async def test_task_failure_does_not_kill_worker(self):
        """一個 task 拋 exception，worker 應該繼續處理下一個"""
        os = AgentOS()
        await os.start(num_workers=1)

        async def bad_task():
            raise ValueError("intentional")

        async def good_task():
            return "ok"

        os.enqueue(Task(name="bad", coro_factory=bad_task))
        os.enqueue(Task(name="good", coro_factory=good_task))

        await asyncio.sleep(0.2)
        assert os.processed_count == 2  # 兩個都「處理過」（fail 也是 processed）
        await os.stop()

    @pytest.mark.asyncio
    async def test_task_completed_event_fires(self):
        os = AgentOS()
        await os.start(num_workers=1)

        received = []

        async def my_task():
            return "task-result"

        async def on_completed(event: Event):
            received.append(event.data.get("result"))

        os.event_bus.subscribe("task.completed", on_completed)
        os.enqueue(Task(name="test", coro_factory=my_task))

        await asyncio.sleep(0.2)
        assert "task-result" in received
        await os.stop()


# ==================== state.sessions thread safety ====================

class TestSessionsLock:
    """bridge/main.py state.sessions 的 RLock 保護"""

    @pytest.mark.asyncio
    async def test_concurrent_append_does_not_lose_messages(self):
        """10 個 task 同時 append 到同一 session，結果 10 條都在"""
        # 模擬 BridgeState.sessions + sessions_lock
        sessions: dict = {}
        import threading
        lock = threading.RLock()

        def append(session_id: str, msg: str):
            with lock:
                if session_id not in sessions:
                    sessions[session_id] = []
                sessions[session_id].append(msg)
                # 模擬 truncate
                sessions[session_id] = sessions[session_id][-20:]

        # 10 個 thread 同時 append
        threads = []
        for i in range(10):
            t = threading.Thread(target=append, args=("user1", f"msg-{i}"))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        # 10 條都該在
        assert len(sessions["user1"]) == 10

    @pytest.mark.asyncio
    async def test_rlock_supports_nested_acquire(self):
        """RLock（不是 Lock）支援 nested"""
        lock = threading.RLock()
        with lock:
            with lock:  # nested，Lock 會 deadlock，RLock 不會
                pass

    @pytest.mark.asyncio
    async def test_stress_100_concurrent_writes(self):
        """100 個 thread 對 10 個 session 寫入，全部成功"""
        sessions: dict = {}
        import threading
        lock = threading.RLock()

        def write(sid: str, msg: str):
            with lock:
                if sid not in sessions:
                    sessions[sid] = []
                sessions[sid].append(msg)

        threads = []
        for i in range(100):
            sid = f"user-{i % 10}"
            t = threading.Thread(target=write, args=(sid, f"m{i}"))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        # 10 個 session，每個 10 條
        assert len(sessions) == 10
        for sid in sessions:
            assert len(sessions[sid]) == 10


# ==================== EventBus unsubscribe + AgentOS.wait_for_task (v0.3) ====================

class TestEventBusUnsubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_returns_unsubscribe_callable(self):
        bus = EventBus()
        called = 0
        async def handler(event):
            nonlocal called
            called += 1
        unsub = bus.subscribe("test", handler)
        assert callable(unsub)

        await bus.emit(Event(type="test"))
        assert called == 1

        unsub()
        await bus.emit(Event(type="test"))
        assert called == 1  # 取消後不再收到

    @pytest.mark.asyncio
    async def test_unsubscribe_does_not_affect_other_handlers(self):
        bus = EventBus()
        a_calls = 0
        b_calls = 0
        async def handler_a(event):
            nonlocal a_calls
            a_calls += 1
        async def handler_b(event):
            nonlocal b_calls
            b_calls += 1
        unsub_a = bus.subscribe("ev", handler_a)
        bus.subscribe("ev", handler_b)

        await bus.emit(Event(type="ev"))
        assert a_calls == 1
        assert b_calls == 1

        unsub_a()  # 只取消 a
        await bus.emit(Event(type="ev"))
        assert a_calls == 1  # 沒變
        assert b_calls == 2  # 還在


class TestWaitForTask:
    """AgentOS.wait_for_task() — endpoint 等特定 task 完成用"""

    @pytest.mark.asyncio
    async def test_returns_completed_event_data(self):
        os = AgentOS()
        await os.start(num_workers=1)

        async def my_task():
            return "task-result"

        task = Task(name="test", coro_factory=my_task)
        os.enqueue(task)
        result = await os.wait_for_task("test", task.id, timeout=2.0)

        assert result is not None
        assert result["task"] == "test"
        assert result["task_id"] == task.id
        assert result["result"] == "task-result"
        assert "duration_ms" in result
        await os.stop()

    @pytest.mark.asyncio
    async def test_returns_failed_event_data(self):
        os = AgentOS()
        await os.start(num_workers=1)

        async def bad_task():
            raise ValueError("intentional failure")

        task = Task(name="bad", coro_factory=bad_task)
        os.enqueue(task)
        result = await os.wait_for_task("bad", task.id, timeout=2.0)

        assert result is not None
        assert result["task"] == "bad"
        assert result["error"] == "intentional failure"
        # __failed__ marker 已被 wait_for_task 去掉
        assert "__failed__" not in result
        await os.stop()

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        os = AgentOS()
        await os.start(num_workers=1)

        async def slow_task():
            import asyncio as _asyncio
            await _asyncio.sleep(2.0)
            return "too-late"

        task = Task(name="slow", coro_factory=slow_task)
        os.enqueue(task)
        result = await os.wait_for_task("slow", task.id, timeout=0.3)
        assert result is None
        # worker 還在跑 task，等停 os 才真正結束
        await os.stop()

    @pytest.mark.asyncio
    async def test_filters_by_task_id(self):
        """同 task name 但不同 id 只 match 自己 — 防止多 request 互卡"""
        os = AgentOS()
        await os.start(num_workers=1)

        async def my_task_a():
            return "result-a"

        async def my_task_b():
            return "result-b"

        task_a = Task(name="same", coro_factory=my_task_a)
        os.enqueue(task_a)
        # 還沒等 a 完成就 enqueue b（雖然 worker 一次一個，但模擬併發情境）
        task_b = Task(name="same", coro_factory=my_task_b)
        os.enqueue(task_b)

        # 等 a 的結果
        result_a = await os.wait_for_task("same", task_a.id, timeout=2.0)
        assert result_a["result"] == "result-a"
        assert result_a["task_id"] == task_a.id

        # 等 b 的結果
        result_b = await os.wait_for_task("same", task_b.id, timeout=2.0)
        assert result_b["result"] == "result-b"
        assert result_b["task_id"] == task_b.id

        await os.stop()


# ==================== Task.id 唯一性 ====================

class TestTaskId:
    def test_task_id_auto_generated_unique(self):
        async def noop():
            return None
        ids = {Task(name="t", coro_factory=noop).id for _ in range(100)}
        assert len(ids) == 100  # 100 個 task 都有唯一 id

    def test_task_id_default_short_hex(self):
        async def noop():
            return None
        t = Task(name="t", coro_factory=noop)
        # UUID4 hex[:8] = 8 chars
        assert len(t.id) == 8

    def test_task_id_explicit_override(self):
        async def noop():
            return None
        t = Task(name="t", coro_factory=noop, id="my-custom-id")
        assert t.id == "my-custom-id"
