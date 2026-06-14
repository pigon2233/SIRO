"""
bridge/state - v2.0 持久化層（SQLite）

v0.x 既有 in-memory state（bridge/main.py 的 self.sessions dict）保留為 fallback。
v2.0 開始 production 走 SQLite backend、保留 memory backend 給 unit test。

模組：
    schema.sql: CREATE TABLE all
    backend.py: StateBackend protocol
    sqlite_backend.py: 實作
    memory_backend.py: in-memory 實作（v0.x 相容）
    models.py: dataclass（Session / Message / Task / AuditEntry）

v2.0 開工時 import 路徑：
    from bridge.state import StateBackend, SQLiteBackend, MemoryBackend

# v0.x 路徑仍可用（向後相容）：
    from bridge.state import MemoryBackend
"""

from .models import Session, Message, Task, AuditEntry, TaskStatus
from .backend import StateBackend
from .memory_backend import MemoryBackend
from .sqlite_backend import SQLiteBackend

__all__ = [
    "Session",
    "Message",
    "Task",
    "AuditEntry",
    "TaskStatus",
    "StateBackend",
    "MemoryBackend",
    "SQLiteBackend",
]
