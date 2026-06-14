"""
bridge/state/sqlite_backend.py - v2.0 SQLite backend（production）

特性：
- 純同步 sqlite3 操作（用 asyncio.to_thread 包成 async）
- 一個 connection + WAL mode（多 worker process 同時讀 OK、寫互鎖）
- schema 自動 migrate（init 時跑 schema.sql）

v2.0 開工前可先用、正式 ship 要加：
- connection pool（多 worker 高併發）
- 自動 backup（每 10 分鐘 snapshot）
- vacuum 排程（避免 WAL 膨脹）
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from .backend import StateBackend
from .models import Session, Message, Task, AuditEntry, TaskStatus

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path,
        check_same_thread=False,
        isolation_level=None,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


class SQLiteBackend(StateBackend):
    """SQLite backend、async 介面（底層用 asyncio.to_thread 跑 sync sqlite3）

    範例：
        backend = SQLiteBackend("bridge/data/siro-data.db")
        await backend.init()
        session = await backend.get_or_create_session("user-1", "user-1")
        msg = await backend.append_message(Message(role="user", content="hi", session_id=session.session_id))
        await backend.close()
    """

    def __init__(self, db_path: str = "bridge/data/siro-data.db") -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # 序列化寫操作：async 層拿 asyncio.Lock、再呼叫 sync SQL
        self._lock = asyncio.Lock()

    # ==================== Lifecycle ====================

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        await asyncio.to_thread(self._init_sync, schema)

    def _init_sync(self, schema: str) -> None:
        if self._conn is not None:
            self._conn.close()
        conn = _connect(self.db_path)
        try:
            conn.executescript(schema)
        finally:
            conn.close()
        self._conn = _connect(self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    def _conn_check(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized — call init() first")
        return self._conn

    # ==================== Helpers ====================

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        return Session.from_row(dict(row))

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        return Message.from_row(dict(row))

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task.from_row(dict(row))

    def _row_to_audit(self, row: sqlite3.Row) -> AuditEntry:
        return AuditEntry.from_row(dict(row))

    def _serialize_payload(self, d: dict) -> str:
        return json.dumps(d, ensure_ascii=False, default=str)

    # ==================== Sessions ====================

    async def get_or_create_session(
        self, session_id: str, user_id: str, persona: str = "siro-default"
    ) -> Session:
        def _op() -> Session:
            conn = self._conn_check()
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (int(time.time() * 1000), session_id),
                )
                return self._row_to_session(row)
            now = int(time.time() * 1000)
            conn.execute(
                "INSERT INTO sessions (session_id, user_id, persona, created_at, updated_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, user_id, persona, now, now, "{}"),
            )
            return Session(
                session_id=session_id,
                user_id=user_id,
                persona=persona,
                created_at=now,
                updated_at=now,
            )

        async with self._lock:
            return await asyncio.to_thread(_op)

    async def get_session(self, session_id: str) -> Optional[Session]:
        def _op() -> Optional[Session]:
            conn = self._conn_check()
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return self._row_to_session(row) if row else None
        return await asyncio.to_thread(_op)

    async def list_sessions(self, user_id: str, limit: int = 20) -> List[Session]:
        def _op() -> List[Session]:
            conn = self._conn_check()
            rows = conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [self._row_to_session(r) for r in rows]
        return await asyncio.to_thread(_op)

    async def delete_session(self, session_id: str) -> bool:
        def _op() -> bool:
            conn = self._conn_check()
            cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            return cur.rowcount > 0
        async with self._lock:
            return await asyncio.to_thread(_op)

    async def touch_session(self, session_id: str) -> None:
        def _op() -> None:
            conn = self._conn_check()
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (int(time.time() * 1000), session_id),
            )
        await asyncio.to_thread(_op)

    # ==================== Messages ====================

    async def append_message(self, message: Message) -> Message:
        def _op() -> Message:
            conn = self._conn_check()
            now = message.created_at or int(time.time() * 1000)
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, emotion, expression, "
                "tool_name, tool_args, tool_result, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message.session_id,
                    message.role,
                    message.content,
                    message.emotion,
                    message.expression,
                    message.tool_name,
                    self._serialize_payload(message.tool_args) if message.tool_args else None,
                    self._serialize_payload(message.tool_result) if message.tool_result else None,
                    now,
                ),
            )
            message.id = cur.lastrowid
            message.created_at = now
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, message.session_id),
            )
            return message
        async with self._lock:
            return await asyncio.to_thread(_op)

    async def get_history(self, session_id: str, limit: int = 20) -> List[Message]:
        def _op() -> List[Message]:
            conn = self._conn_check()
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [self._row_to_message(r) for r in reversed(rows)]
        return await asyncio.to_thread(_op)

    async def search_messages(
        self, user_id: str, query: str, limit: int = 20
    ) -> List[Message]:
        def _op() -> List[Message]:
            conn = self._conn_check()
            rows = conn.execute(
                "SELECT m.* FROM messages m JOIN sessions s ON m.session_id = s.session_id "
                "WHERE s.user_id = ? AND m.content LIKE ? ORDER BY m.id DESC LIMIT ?",
                (user_id, f"%{query}%", limit),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]
        return await asyncio.to_thread(_op)

    # ==================== Tasks ====================

    async def enqueue_task(self, task: Task) -> Task:
        def _op() -> Task:
            conn = self._conn_check()
            conn.execute(
                "INSERT INTO tasks (id, name, payload, status, enqueued_at, attempts, max_attempts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.name,
                    self._serialize_payload(task.payload),
                    task.status.value,
                    task.enqueued_at,
                    task.attempts,
                    task.max_attempts,
                ),
            )
            return task
        async with self._lock:
            return await asyncio.to_thread(_op)

    async def claim_next_task(self, worker_id: str) -> Optional[Task]:
        def _op() -> Optional[Task]:
            conn = self._conn_check()
            row = conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY enqueued_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            now = int(time.time() * 1000)
            conn.execute(
                "UPDATE tasks SET status = 'running', worker_id = ?, started_at = ?, attempts = attempts + 1 "
                "WHERE id = ?",
                (worker_id, now, row["id"]),
            )
            task = self._row_to_task(row)
            task.status = TaskStatus.RUNNING
            task.worker_id = worker_id
            task.started_at = now
            task.attempts += 1
            return task
        async with self._lock:
            return await asyncio.to_thread(_op)

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> Task:
        def _op() -> Task:
            conn = self._conn_check()
            sets = ["status = ?"]
            params: list = [status]
            if result is not None:
                sets.append("result = ?")
                params.append(self._serialize_payload(result))
            if error is not None:
                sets.append("error = ?")
                params.append(error)
            if worker_id is not None:
                sets.append("worker_id = ?")
                params.append(worker_id)
            if status in ("done", "failed", "cancelled"):
                sets.append("finished_at = ?")
                params.append(int(time.time() * 1000))
            params.append(task_id)
            conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                raise KeyError(f"task {task_id} not found")
            return self._row_to_task(row)
        async with self._lock:
            return await asyncio.to_thread(_op)

    async def get_task(self, task_id: str) -> Optional[Task]:
        def _op() -> Optional[Task]:
            conn = self._conn_check()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None
        return await asyncio.to_thread(_op)

    async def list_tasks(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Task]:
        def _op() -> List[Task]:
            conn = self._conn_check()
            sql = "SELECT * FROM tasks WHERE 1=1"
            params: list = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            if session_id:
                sql += " AND json_extract(payload, '$.session_id') = ?"
                params.append(session_id)
            sql += " ORDER BY enqueued_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_task(r) for r in rows]
        return await asyncio.to_thread(_op)

    async def wait_for_task(
        self, task_id: str, timeout_sec: float = 30.0
    ) -> Optional[Task]:
        deadline = time.time() + timeout_sec
        poll = 0.1
        while time.time() < deadline:
            task = await self.get_task(task_id)
            if task and task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return task
            await asyncio.sleep(poll)
        return await self.get_task(task_id)

    # ==================== Audit ====================

    async def log_audit(self, entry: AuditEntry) -> AuditEntry:
        def _op() -> AuditEntry:
            conn = self._conn_check()
            cur = conn.execute(
                "INSERT INTO audit_log (session_id, user_id, action, target, result, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.session_id,
                    entry.user_id,
                    entry.action,
                    entry.target,
                    entry.result,
                    self._serialize_payload(entry.detail) if entry.detail else None,
                    entry.created_at,
                ),
            )
            entry.id = cur.lastrowid
            return entry
        async with self._lock:
            return await asyncio.to_thread(_op)

    async def get_audit(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        def _op() -> List[AuditEntry]:
            conn = self._conn_check()
            sql = "SELECT * FROM audit_log WHERE 1=1"
            params: list = []
            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_audit(r) for r in rows]
        return await asyncio.to_thread(_op)
