"""tests.bridge.test_conversation — TurnManager / ConversationTask 測試(5 個 unit tests)。

對應 design: docs/STT_INTEGRATION.md §測試計畫 → test_conversation.py。

驗證 Pattern 4 的核心行為:
- 新 turn 取消舊(沒有 race condition)
- CancelledError 自然傳遞
- 冪等 / safe cancel / 收尾 cleanup
"""

from __future__ import annotations

import asyncio
import time

import pytest

from bridge.conversation import ConversationTask, TurnManager


# ============================================================
# Helpers
# ============================================================

async def _delay(seconds: float) -> None:
    """等 N 秒(cancel 用來驗證)。"""
    await asyncio.sleep(seconds)


async def _ticker(counter: list, stop: asyncio.Event) -> None:
    """無限 tick 直到 stop event。"""
    n = 0
    while not stop.is_set():
        counter.append(n)
        n += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.01)
        except asyncio.TimeoutError:
            continue


# ============================================================
# ConversationTask
# ============================================================

@pytest.mark.asyncio
async def test_conversation_task_starts_and_completes():
    """start() → run_fn 跑完 → done=True。"""
    started = []
    finished = []

    async def run():
        started.append(time.time())
        await _delay(0.05)
        finished.append(time.time())

    task = ConversationTask(turn_id=1, run_fn=run)
    task.start()
    await task.wait_done(timeout=1.0)
    assert task.done is True
    assert len(started) == 1
    assert len(finished) == 1


@pytest.mark.asyncio
async def test_conversation_task_cancel_during_run():
    """cancel() 在 run 期間呼叫 → 收到 CancelledError → done=True。"""
    started = []
    completed = []

    async def run():
        started.append(True)
        try:
            await _delay(5.0)  # 5s
            completed.append(True)
        except asyncio.CancelledError:
            raise

    task = ConversationTask(turn_id=1, run_fn=run)
    task.start()
    await asyncio.sleep(0.05)  # 讓 task 進 await
    assert task.done is False
    task.cancel()
    await task.wait_done(timeout=1.0)
    assert task.done is True
    assert started == [True]
    assert completed == []  # 沒跑到 completed


@pytest.mark.asyncio
async def test_conversation_task_idempotent_start():
    """start() 第二次呼叫(還沒 done)是 no-op(不會開新 task)。"""
    started_count = []

    async def run():
        started_count.append(1)
        await _delay(0.1)

    task = ConversationTask(turn_id=1, run_fn=run)
    task.start()
    task1 = task._task
    task.start()  # 第二次、應該 no-op
    task2 = task._task
    assert task1 is task2  # 同一個 task 物件
    await task.wait_done(timeout=1.0)
    assert len(started_count) == 1


# ============================================================
# TurnManager
# ============================================================

@pytest.mark.asyncio
async def test_turn_manager_starts_and_tracks_current():
    """start_new_turn → current_turn_id 對、has_running_task True。"""
    mgr = TurnManager()
    assert mgr.current_turn_id == 0
    assert mgr.has_running_task is False

    async def run():
        await _delay(0.1)

    await mgr.start_new_turn(turn_id=42, run_fn=run)
    assert mgr.current_turn_id == 42
    assert mgr.has_running_task is True
    await mgr.wait_current_done(timeout=2.0)
    assert mgr.has_running_task is False


@pytest.mark.asyncio
async def test_turn_manager_new_turn_cancels_old():
    """新 turn 進來時,舊 task 被 cancel。"""
    mgr = TurnManager()
    old_completed = []
    new_completed = []

    async def old_run():
        try:
            await _delay(5.0)
            old_completed.append(True)
        except asyncio.CancelledError:
            raise

    async def new_run():
        await _delay(0.05)
        new_completed.append(True)

    # 開 old
    await mgr.start_new_turn(turn_id=1, run_fn=old_run)
    assert mgr.current_turn_id == 1
    await asyncio.sleep(0.05)  # 讓 old 進 await

    # 開 new(自動 cancel old)
    await mgr.start_new_turn(turn_id=2, run_fn=new_run)
    assert mgr.current_turn_id == 2

    # 等兩邊
    await mgr.wait_current_done(timeout=2.0)
    await asyncio.sleep(0.1)  # 給 old cleanup 時間

    assert old_completed == []  # old 被 cancel、沒跑完
    assert new_completed == [True]  # new 跑完


@pytest.mark.asyncio
async def test_turn_manager_no_task_safe_cancel():
    """沒有 current task 時 cancel_current 不 crash。"""
    mgr = TurnManager()
    mgr.cancel_current()  # no-op
    assert mgr.has_running_task is False

    # reset 也 safe
    mgr.reset()
    assert mgr.current_turn_id == 0


@pytest.mark.asyncio
async def test_turn_manager_turn_id_monotonic_in_unity():
    """(模擬 Unity 端) 連續 3 個 turn → current_turn_id 一路遞增。"""
    mgr = TurnManager()

    async def quick():
        await _delay(0.01)

    for i in range(1, 4):
        await mgr.start_new_turn(turn_id=i, run_fn=quick)
        assert mgr.current_turn_id == i
        await mgr.wait_current_done(timeout=1.0)
