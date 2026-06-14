"""
bridge/state/backend.py - StateBackend protocol

所有 backend（SQLite / Memory / 未來 Postgres）都要實作這個介面。
"""

from __future__ import annotations

from typing import List, Optional, Protocol

from .models import Session, Message, Task, AuditEntry


class StateBackend(Protocol):
    """SIRO 持久化層 protocol

    v0.x 用 in-memory（MemoryBackend）
    v2.0+ 用 SQLite（SQLiteBackend）
    v3+ 視規模可能用 PostgreSQL / Redis

    所有方法都是 async（即便 MemoryBackend 不需要 IO）— 介面統一好 mock
    """

    # ==================== Sessions ====================

    async def get_or_create_session(
        self, session_id: str, user_id: str, persona: str = "siro-default"
    ) -> Session:
        """拿 session、沒有就建一個"""
        ...

    async def get_session(self, session_id: str) -> Optional[Session]:
        """拿 session、沒有就回 None"""
        ...

    async def list_sessions(self, user_id: str, limit: int = 20) -> List[Session]:
        """列某 user 的 session（最新在前）"""
        ...

    async def delete_session(self, session_id: str) -> bool:
        """刪 session（CASCADE 刪 messages）、回傳是否真的有刪"""
        ...

    async def touch_session(self, session_id: str) -> None:
        """更新 updated_at（給「最近用的 session」查詢用）"""
        ...

    # ==================== Messages ====================

    async def append_message(self, message: Message) -> Message:
        """加一條訊息、回傳（含 id）"""
        ...

    async def get_history(
        self, session_id: str, limit: int = 20
    ) -> List[Message]:
        """拿 session 的最近 N 條訊息（給 LLM context 用）"""
        ...

    async def search_messages(
        self, user_id: str, query: str, limit: int = 20
    ) -> List[Message]:
        """跨 session 模糊搜尋（v1.5+ memory 用）"""
        ...

    # ==================== Tasks ====================

    async def enqueue_task(self, task: Task) -> Task:
        """塞 task 進 queue"""
        ...

    async def claim_next_task(self, worker_id: str) -> Optional[Task]:
        """worker 拉下一個 pending task、標 running"""
        ...

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> Task:
        """更新 task 狀態（done / failed / cancelled）"""
        ...

    async def get_task(self, task_id: str) -> Optional[Task]:
        """拿單一 task"""
        ...

    async def list_tasks(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Task]:
        """列 task（給 debug / observability 用）"""
        ...

    async def wait_for_task(
        self, task_id: str, timeout_sec: float = 30.0
    ) -> Optional[Task]:
        """等 task 結束（polling）。v2.0 用 SQLite 沒 native pub/sub、輪詢 100ms"""
        ...

    # ==================== Audit ====================

    async def log_audit(self, entry: AuditEntry) -> AuditEntry:
        """寫 audit log"""
        ...

    async def get_audit(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        """拿 audit log（給 /siro/actions endpoint）"""
        ...

    # ==================== Lifecycle ====================

    async def init(self) -> None:
        """backend 初始化（建 table / 建 connection pool）"""
        ...

    async def close(self) -> None:
        """backend 關閉（flush / close connection）"""
        ...
