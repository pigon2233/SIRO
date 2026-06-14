"""
bridge/state/memory_backend.py - v0.x in-memory backend（v2.0 保留為 fallback）

跟 v0.x 既有 state.sessions 行為相容、給 unit test 用。
production v2.0 開始用 SQLiteBackend。
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

from .backend import StateBackend
from .models import Session, Message, Task, AuditEntry, TaskStatus


class MemoryBackend(StateBackend):
    """In-memory backend、行為跟 v0.x state.sessions 一致

    Thread-safety: 用 asyncio.Lock（跟 v0.x main.py 用的 RLock 等價）
    持久化: 無（process restart 全丟）
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: Dict[str, Session] = {}
        self._messages: Dict[str, List[Message]] = {}  # session_id -> messages
        self._tasks: Dict[str, Task] = {}
        self._audit: List[AuditEntry] = []

    # ==================== Sessions ====================

    async def get_or_create_session(
        self, session_id: str, user_id: str, persona: str = "siro-default"
    ) -> Session:
        async with self._lock:
            if session_id in self._sessions:
                sess = self._sessions[session_id]
                sess.updated_at = int(time.time() * 1000)
                return sess
            sess = Session(session_id=session_id, user_id=user_id, persona=persona)
            self._sessions[session_id] = sess
            return sess

    async def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    async def list_sessions(self, user_id: str, limit: int = 20) -> List[Session]:
        all_sess = [s for s in self._sessions.values() if s.user_id == user_id]
        all_sess.sort(key=lambda s: s.updated_at, reverse=True)
        return all_sess[:limit]

    async def delete_session(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._messages.pop(session_id, None)
                return True
            return False

    async def touch_session(self, session_id: str) -> None:
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].updated_at = int(time.time() * 1000)

    # ==================== Messages ====================

    async def append_message(self, message: Message) -> Message:
        async with self._lock:
            message.id = len(self._messages.get(message.session_id, [])) + 1
            if not message.created_at:
                message.created_at = int(time.time() * 1000)
            self._messages.setdefault(message.session_id, []).append(message)
        return message

    async def get_history(self, session_id: str, limit: int = 20) -> List[Message]:
        msgs = self._messages.get(session_id, [])
        return msgs[-limit:]

    async def search_messages(
        self, user_id: str, query: str, limit: int = 20
    ) -> List[Message]:
        # in-memory: filter by user_id prefix match on session_id (v0.x 慣例)
        # v1.5+ 既有 search 用 jieba 切詞、這裡簡化版
        results: List[Message] = []
        for sess_id, msgs in self._messages.items():
            if not sess_id.startswith(user_id):
                continue
            for msg in msgs:
                if query in msg.content:
                    results.append(msg)
                    if len(results) >= limit:
                        return results
        return results

    # ==================== Tasks ====================

    async def enqueue_task(self, task: Task) -> Task:
        async with self._lock:
            self._tasks[task.id] = task
        return task

    async def claim_next_task(self, worker_id: str) -> Optional[Task]:
        async with self._lock:
            pending = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
            pending.sort(key=lambda t: t.enqueued_at)
            if not pending:
                return None
            task = pending[0]
            task.status = TaskStatus.RUNNING
            task.worker_id = worker_id
            task.started_at = int(time.time() * 1000)
            task.attempts += 1
            return task

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> Task:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"task {task_id} not found")
            task.status = TaskStatus(status)
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if worker_id is not None:
                task.worker_id = worker_id
            if status in ("done", "failed", "cancelled"):
                task.finished_at = int(time.time() * 1000)
            return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    async def list_tasks(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Task]:
        all_tasks = list(self._tasks.values())
        if status:
            all_tasks = [t for t in all_tasks if t.status.value == status]
        if session_id:
            all_tasks = [t for t in all_tasks if t.payload.get("session_id") == session_id]
        all_tasks.sort(key=lambda t: t.enqueued_at, reverse=True)
        return all_tasks[:limit]

    async def wait_for_task(
        self, task_id: str, timeout_sec: float = 30.0
    ) -> Optional[Task]:
        deadline = time.time() + timeout_sec
        poll = 0.1
        while time.time() < deadline:
            task = self._tasks.get(task_id)
            if task and task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return task
            await asyncio.sleep(poll)
        return self._tasks.get(task_id)

    # ==================== Audit ====================

    async def log_audit(self, entry: AuditEntry) -> AuditEntry:
        async with self._lock:
            entry.id = len(self._audit) + 1
            self._audit.append(entry)
        return entry

    async def get_audit(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        results = list(self._audit)
        if session_id:
            results = [a for a in results if a.session_id == session_id]
        results.sort(key=lambda a: a.created_at, reverse=True)
        return results[:limit]

    # ==================== Lifecycle ====================

    async def init(self) -> None:
        pass  # in-memory 無初始化

    async def close(self) -> None:
        pass  # in-memory 無關閉
