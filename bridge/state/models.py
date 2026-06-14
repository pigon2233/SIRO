"""
bridge/state/models.py - v2.0 persistence data models

對應 schema.sql 的 4 個 table。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Session:
    session_id: str
    user_id: str
    persona: str = "siro-default"
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Session":
        meta = row.get("metadata")
        if isinstance(meta, str):
            meta = json.loads(meta) if meta else {}
        return cls(
            session_id=row["session_id"],
            user_id=row["user_id"],
            persona=row.get("persona", "siro-default"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=meta or {},
        )


@dataclass
class Message:
    role: str  # 'user' / 'assistant' / 'system' / 'tool'
    content: str
    id: Optional[int] = None
    session_id: Optional[str] = None
    emotion: Optional[str] = None
    expression: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Message":
        def _maybe_json(v):
            if v is None or v == "":
                return None
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    return v
            return v

        return cls(
            id=row.get("id"),
            session_id=row.get("session_id"),
            role=row["role"],
            content=row["content"],
            emotion=row.get("emotion"),
            expression=row.get("expression"),
            tool_name=row.get("tool_name"),
            tool_args=_maybe_json(row.get("tool_args")),
            tool_result=_maybe_json(row.get("tool_result")),
            created_at=row.get("created_at", int(time.time() * 1000)),
        )


@dataclass
class Task:
    name: str
    payload: Dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    worker_id: Optional[str] = None
    enqueued_at: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    attempts: int = 0
    max_attempts: int = 3

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Task":
        def _maybe_json(v):
            if v is None or v == "":
                return None
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    return v
            return v

        return cls(
            id=row["id"],
            name=row["name"],
            payload=_maybe_json(row["payload"]) or {},
            status=TaskStatus(row["status"]),
            result=_maybe_json(row.get("result")),
            error=row.get("error"),
            worker_id=row.get("worker_id"),
            enqueued_at=row["enqueued_at"],
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            attempts=row.get("attempts", 0),
            max_attempts=row.get("max_attempts", 3),
        )


@dataclass
class AuditEntry:
    action: str  # 'tool.execute' / 'memory.save' / ...
    target: Optional[str] = None  # sandbox path / shell cmd
    result: str = "ok"  # 'ok' / 'denied' / 'error'
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    id: Optional[int] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "AuditEntry":
        def _maybe_json(v):
            if v is None or v == "":
                return None
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    return v
            return v

        return cls(
            id=row.get("id"),
            session_id=row.get("session_id"),
            user_id=row.get("user_id"),
            action=row["action"],
            target=row.get("target"),
            result=row.get("result", "ok"),
            detail=_maybe_json(row.get("detail")),
            created_at=row.get("created_at", int(time.time() * 1000)),
        )
