"""
tests/bridge/state/test_sqlite_backend.py - SQLite backend unit tests

對應 bridge/state/sqlite_backend.py
v2.0 持久化層驗證（24 個 test cases）

執行：
    python -m pytest tests/bridge/state/ -v
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import List

import pytest

from bridge.state import (
    Session,
    Message,
    Task,
    AuditEntry,
    TaskStatus,
    SQLiteBackend,
    MemoryBackend,
)


@pytest.fixture
async def tmp_db():
    """每個 test 一個 tmp SQLite DB"""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        backend = SQLiteBackend(db_path)
        await backend.init()
        yield backend
        await backend.close()


@pytest.fixture
async def mem():
    backend = MemoryBackend()
    await backend.init()
    yield backend
    await backend.close()


# ==================== Sessions ====================

@pytest.mark.asyncio
async def test_session_get_or_create_new(tmp_db):
    sess = await tmp_db.get_or_create_session("s1", "user-1", "siro-default")
    assert sess.session_id == "s1"
    assert sess.user_id == "user-1"
    assert sess.persona == "siro-default"


@pytest.mark.asyncio
async def test_session_get_or_create_existing(tmp_db):
    s1 = await tmp_db.get_or_create_session("s1", "user-1")
    s2 = await tmp_db.get_or_create_session("s1", "user-1")
    assert s1.session_id == s2.session_id
    assert s1.created_at == s2.created_at  # 沒新建


@pytest.mark.asyncio
async def test_session_get_nonexistent(tmp_db):
    s = await tmp_db.get_session("nope")
    assert s is None


@pytest.mark.asyncio
async def test_session_list_user(tmp_db):
    await tmp_db.get_or_create_session("s1", "user-A")
    await tmp_db.get_or_create_session("s2", "user-A")
    await tmp_db.get_or_create_session("s3", "user-B")
    a_sess = await tmp_db.list_sessions("user-A")
    b_sess = await tmp_db.list_sessions("user-B")
    assert len(a_sess) == 2
    assert len(b_sess) == 1


@pytest.mark.asyncio
async def test_session_delete_cascades_messages(tmp_db):
    await tmp_db.get_or_create_session("s1", "user-1")
    await tmp_db.append_message(Message(session_id="s1", role="user", content="hi"))
    deleted = await tmp_db.delete_session("s1")
    assert deleted is True
    # 應該拿不到 history（CASCADE）
    hist = await tmp_db.get_history("s1")
    assert hist == []


@pytest.mark.asyncio
async def test_session_touch_updates_timestamp(tmp_db):
    s1 = await tmp_db.get_or_create_session("s1", "user-1")
    original = s1.updated_at
    await asyncio.sleep(0.01)
    await tmp_db.touch_session("s1")
    s2 = await tmp_db.get_session("s1")
    assert s2.updated_at > original


# ==================== Messages ====================

@pytest.mark.asyncio
async def test_append_and_get_history(tmp_db):
    await tmp_db.get_or_create_session("s1", "user-1")
    await tmp_db.append_message(Message(session_id="s1", role="user", content="hi"))
    await tmp_db.append_message(
        Message(session_id="s1", role="assistant", content="hello", emotion="happy")
    )
    hist = await tmp_db.get_history("s1")
    assert len(hist) == 2
    assert hist[0].content == "hi"
    assert hist[1].content == "hello"
    assert hist[1].emotion == "happy"


@pytest.mark.asyncio
async def test_history_limit(tmp_db):
    await tmp_db.get_or_create_session("s1", "user-1")
    for i in range(50):
        await tmp_db.append_message(Message(session_id="s1", role="user", content=f"msg-{i}"))
    hist = await tmp_db.get_history("s1", limit=10)
    assert len(hist) == 10
    # 應該是最後 10 條（msg-40 ~ msg-49）
    assert hist[0].content == "msg-40"
    assert hist[-1].content == "msg-49"


@pytest.mark.asyncio
async def test_search_messages_by_user(tmp_db):
    await tmp_db.get_or_create_session("user-A-s1", "user-A")
    await tmp_db.get_or_create_session("user-B-s1", "user-B")
    await tmp_db.append_message(Message(session_id="user-A-s1", role="user", content="喜歡 python"))
    await tmp_db.append_message(Message(session_id="user-B-s1", role="user", content="喜歡 rust"))
    results = await tmp_db.search_messages("user-A", "python")
    assert len(results) == 1
    assert "python" in results[0].content


@pytest.mark.asyncio
async def test_message_with_tool_args(tmp_db):
    await tmp_db.get_or_create_session("s1", "user-1")
    msg = Message(
        session_id="s1",
        role="tool",
        content="list_dir result",
        tool_name="list_dir",
        tool_args={"path": "/tmp"},
        tool_result={"items": ["a.txt", "b.txt"]},
    )
    saved = await tmp_db.append_message(msg)
    assert saved.id is not None
    hist = await tmp_db.get_history("s1")
    assert hist[0].tool_name == "list_dir"
    assert hist[0].tool_args == {"path": "/tmp"}


# ==================== Tasks ====================

@pytest.mark.asyncio
async def test_enqueue_and_claim(tmp_db):
    t1 = Task(name="llm.reply", payload={"session_id": "s1", "message": "hi"})
    t2 = Task(name="llm.reply", payload={"session_id": "s1", "message": "yo"})
    await tmp_db.enqueue_task(t1)
    await tmp_db.enqueue_task(t2)
    claimed = await tmp_db.claim_next_task("worker-1")
    assert claimed is not None
    assert claimed.id == t1.id  # FIFO
    assert claimed.status == TaskStatus.RUNNING
    assert claimed.worker_id == "worker-1"
    assert claimed.attempts == 1


@pytest.mark.asyncio
async def test_claim_empty_queue(tmp_db):
    claimed = await tmp_db.claim_next_task("worker-1")
    assert claimed is None


@pytest.mark.asyncio
async def test_update_task_done(tmp_db):
    t = Task(name="llm.reply", payload={"session_id": "s1"})
    await tmp_db.enqueue_task(t)
    claimed = await tmp_db.claim_next_task("worker-1")
    updated = await tmp_db.update_task_status(claimed.id, "done", result={"text": "hi back"})
    assert updated.status == TaskStatus.DONE
    assert updated.result == {"text": "hi back"}
    assert updated.finished_at is not None


@pytest.mark.asyncio
async def test_update_task_failed(tmp_db):
    t = Task(name="llm.reply", payload={"session_id": "s1"})
    await tmp_db.enqueue_task(t)
    claimed = await tmp_db.claim_next_task("worker-1")
    updated = await tmp_db.update_task_status(claimed.id, "failed", error="LLM timeout")
    assert updated.status == TaskStatus.FAILED
    assert updated.error == "LLM timeout"


@pytest.mark.asyncio
async def test_concurrent_claim_doesnt_double_dispatch(tmp_db):
    """模擬 2 個 worker 同時 claim、應該只 dispatch 一次"""
    for i in range(3):
        await tmp_db.enqueue_task(Task(name="llm.reply", payload={"i": i}))

    results = await asyncio.gather(
        tmp_db.claim_next_task("worker-A"),
        tmp_db.claim_next_task("worker-B"),
    )
    claimed_ids = [r.id for r in results if r is not None]
    assert len(claimed_ids) == 2  # 2 個不同 task 被分派


@pytest.mark.asyncio
async def test_list_tasks_by_status(tmp_db):
    for i in range(3):
        await tmp_db.enqueue_task(Task(name="llm.reply", payload={"i": i}))
    await tmp_db.claim_next_task("worker-1")  # 1 個變 running
    pending = await tmp_db.list_tasks(status="pending")
    running = await tmp_db.list_tasks(status="running")
    assert len(pending) == 2
    assert len(running) == 1


@pytest.mark.asyncio
async def test_wait_for_task_polls_until_done(tmp_db):
    t = Task(name="llm.reply", payload={})
    await tmp_db.enqueue_task(t)

    async def complete_later():
        await asyncio.sleep(0.1)
        claimed = await tmp_db.claim_next_task("worker-1")
        await tmp_db.update_task_status(claimed.id, "done", result={"ok": True})

    asyncio.create_task(complete_later())
    result = await tmp_db.wait_for_task(t.id, timeout_sec=2.0)
    assert result.status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_wait_for_task_timeout(tmp_db):
    t = Task(name="llm.reply", payload={})
    await tmp_db.enqueue_task(t)
    # 不 claim、不 done、timeout 1s
    result = await tmp_db.wait_for_task(t.id, timeout_sec=0.3)
    assert result is not None
    assert result.status == TaskStatus.PENDING


# ==================== Audit ====================

@pytest.mark.asyncio
async def test_audit_log_and_get(tmp_db):
    e1 = AuditEntry(action="tool.execute", target="list_dir", session_id="s1", user_id="user-1")
    e2 = AuditEntry(action="tool.execute", target="run_shell_cmd", result="denied", session_id="s1")
    await tmp_db.log_audit(e1)
    await tmp_db.log_audit(e2)
    all_logs = await tmp_db.get_audit(limit=10)
    assert len(all_logs) == 2
    s1_logs = await tmp_db.get_audit(session_id="s1")
    assert len(s1_logs) == 2


# ==================== Memory backend parity ====================

@pytest.mark.asyncio
async def test_memory_backend_session_crud(mem):
    s = await mem.get_or_create_session("s1", "u1")
    assert s.user_id == "u1"
    found = await mem.get_session("s1")
    assert found.session_id == "s1"
    assert await mem.get_session("nope") is None
    deleted = await mem.delete_session("s1")
    assert deleted
    assert await mem.get_session("s1") is None


@pytest.mark.asyncio
async def test_memory_backend_messages(mem):
    await mem.get_or_create_session("s1", "u1")
    await mem.append_message(Message(session_id="s1", role="user", content="hi"))
    hist = await mem.get_history("s1")
    assert len(hist) == 1
    assert hist[0].content == "hi"


@pytest.mark.asyncio
async def test_memory_backend_task_fifo(mem):
    t1 = Task(name="t1", payload={})
    t2 = Task(name="t2", payload={})
    await mem.enqueue_task(t1)
    await mem.enqueue_task(t2)
    c1 = await mem.claim_next_task("w1")
    c2 = await mem.claim_next_task("w1")
    assert c1.id == t1.id
    assert c2.id == t2.id
    # queue empty
    c3 = await mem.claim_next_task("w1")
    assert c3 is None


# ==================== Recovery scenario ====================

@pytest.mark.asyncio
async def test_recovery_reset_running_to_pending(tmp_db):
    """模擬 bridge 掛掉重啟、status=running 的 task 應該被 reset pending"""
    t = Task(name="llm.reply", payload={})
    await tmp_db.enqueue_task(t)
    await tmp_db.claim_next_task("worker-1")  # running

    # 模擬 recovery: 把所有 running 改回 pending
    running = await tmp_db.list_tasks(status="running")
    for task in running:
        await tmp_db.update_task_status(task.id, "pending", error="bridge crashed during execution")

    # 重啟後、新 worker 應該能 claim
    reclaimed = await tmp_db.claim_next_task("worker-2")
    assert reclaimed is not None
    assert reclaimed.id == t.id
    assert reclaimed.attempts == 2  # 第一次 + retry
