"""
bridge/tools/memory.py - v1.5+ 長期記憶（SQLite）

提供：
- save_memory: 寫一條經驗
- recall_memory: 模糊搜尋（LIKE query）
- list_memories: 列出最近 N 條
- delete_memory: 刪一條（confirm category）

資料庫位置：bridge/data/siro-memory.db
Schema：
    memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,        -- ISO 8601 UTC
        content TEXT NOT NULL,
        tags TEXT,                      -- JSON array of strings
        importance REAL DEFAULT 0.5
    )

FTS5 暫時不用（避免外部依賴）、用 LIKE + 加權排序：
- 內容 match → 重
- tags match → 輕
- importance → 加成
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# DB 路徑
# ============================================================

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "siro-memory.db"

# Module-level lock（sqlite3 不是 thread-safe）
_db_lock = threading.Lock()


def get_db_path() -> Path:
    """拿 DB 路徑（給測試時設 SIRO_MEMORY_DB env 覆寫）"""
    import os
    env_path = os.environ.get("SIRO_MEMORY_DB")
    if env_path:
        p = Path(env_path)
    else:
        p = DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ============================================================
# Schema init
# ============================================================

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    importance REAL DEFAULT 0.5
);
CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
"""


@contextmanager
def _conn():
    """拿一個 sqlite3 connection（context manager）

    自動建 schema、close、commit on success
    """
    db_path = get_db_path()
    c = sqlite3.connect(str(db_path), timeout=5.0)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(_SCHEMA_SQL)
        c.commit()
        yield c
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # tags 是 JSON string、轉回 list
    if d.get("tags"):
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    else:
        d["tags"] = []
    return d


# ============================================================
# Tool definitions
# ============================================================

SAVE_MEMORY_TOOL: dict[str, Any] = {
    "name": "save_memory",
    "description": (
        "把一條經驗 / 學到的東西 / 用戶偏好評測存到長期記憶。"
        "之後用 recall_memory 找回來。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要記的內容"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "標籤方便之後搜尋, e.g. ['python', 'tool_use']",
            },
            "importance": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
                "description": "重要性, 0-1。重要的會在 recall 時優先返回",
            },
        },
        "required": ["content"],
    },
}

RECALL_MEMORY_TOOL: dict[str, Any] = {
    "name": "recall_memory",
    "description": (
        "用關鍵字 / tag 從長期記憶撈相關經驗。"
        "回傳按相關程度 + importance 排序、最多 limit 條。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜尋字串（會跟 content / tags 做 case-insensitive LIKE）",
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 50,
                "description": "最多回幾條",
            },
        },
        "required": ["query"],
    },
}

LIST_MEMORIES_TOOL: dict[str, Any] = {
    "name": "list_memories",
    "description": "列出最近 N 條記憶（按時間倒序）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": [],
    },
}

DELETE_MEMORY_TOOL: dict[str, Any] = {
    "name": "delete_memory",
    "description": "刪除一條記憶（用 memory id）。需要先 list_memories 拿 id。",
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "要刪的記憶 id"},
        },
        "required": ["memory_id"],
    },
}


# ============================================================
# Executors
# ============================================================

async def save_memory(args: dict, ctx: dict) -> dict:
    content = args.get("content", "")
    tags = args.get("tags", [])
    importance = float(args.get("importance", 0.5))

    if not content or not content.strip():
        return {"ok": False, "error": "content 不可為空"}
    # 容錯：LLM 常把 tags 給成 string（"a,b,c"）而不是 list
    # 兩種都接受、轉成統一 list
    if isinstance(tags, str):
        # "a,b,c" 或 "a, b, c" → ["a", "b", "c"]
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, list):
        return {"ok": False, "error": f"tags 必須是 list of strings 或逗號分隔字串、收到 {type(tags).__name__}"}
    # 確認 list 裡都是 str
    tags = [str(t) for t in tags if t]
    if not (0.0 <= importance <= 1.0):
        return {"ok": False, "error": "importance 必須 0-1"}

    memory_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now(timezone.utc).isoformat()
    tags_json = json.dumps(tags, ensure_ascii=False)

    try:
        with _db_lock, _conn() as c:
            c.execute(
                "INSERT INTO memories (id, timestamp, content, tags, importance) "
                "VALUES (?, ?, ?, ?, ?)",
                (memory_id, timestamp, content, tags_json, importance),
            )
            c.commit()
    except Exception as e:
        return {"ok": False, "error": f"寫入失敗：{e}"}

    return {
        "ok": True,
        "memory_id": memory_id,
        "timestamp": timestamp,
        "saved_chars": len(content),
    }


async def recall_memory(args: dict, ctx: dict) -> dict:
    query = args.get("query", "").strip()
    limit = int(args.get("limit", 5))

    if not query:
        return {"ok": False, "error": "query 必填"}

    # 用 LIKE 做 case-insensitive 搜尋
    # 注意：SQL injection 風險？query 是 LLM 給的字串、可能含特殊字元
    # 解法：用 ? placeholder、LIKE 用 ESCAPE '\\'
    like_pattern = f"%{query}%"

    try:
        with _db_lock, _conn() as c:
            # 1. 先撈所有可能的（避免 FTS5、效能還行、SIRO 記憶不會爆炸）
            rows = c.execute(
                "SELECT * FROM memories "
                "WHERE content LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' "
                "ORDER BY importance DESC, timestamp DESC",
                (like_pattern, like_pattern),
            ).fetchall()
    except Exception as e:
        return {"ok": False, "error": f"查詢失敗：{e}"}

    # 計算相關分數（in Python、加 importance 跟 timestamp 衰退）
    now = time.time()
    scored: list[tuple[float, dict]] = []
    query_lower = query.lower()
    for row in rows:
        d = _row_to_dict(row)
        content_lower = d["content"].lower()
        score = 0.0
        # content 包含 query → 重分
        if query_lower in content_lower:
            score += 1.0
            # 算出現次數（給多次出現的加分）
            score += 0.2 * content_lower.count(query_lower)
        # tags 包含 query → 中分
        if any(query_lower in t.lower() for t in d["tags"]):
            score += 0.5
        # importance 加成
        score *= 0.5 + 0.5 * d["importance"]
        # 時間衰退（越新稍微加分、但不要太多）
        try:
            t = datetime.fromisoformat(d["timestamp"]).timestamp()
            age_days = (now - t) / 86400
            score += 0.1 * max(0, 1.0 - age_days / 30)  # 30 天後完全不加分
        except (ValueError, TypeError):
            pass

        if score > 0:
            scored.append((score, d))

    scored.sort(key=lambda x: -x[0])
    top = [d for _, d in scored[:limit]]

    return {
        "ok": True,
        "query": query,
        "count": len(top),
        "total_matched": len(scored),
        "memories": top,
    }


async def list_memories(args: dict, ctx: dict) -> dict:
    limit = int(args.get("limit", 10))

    try:
        with _db_lock, _conn() as c:
            rows = c.execute(
                "SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as e:
        return {"ok": False, "error": f"查詢失敗：{e}"}

    return {
        "ok": True,
        "count": len(rows),
        "memories": [_row_to_dict(r) for r in rows],
    }


async def delete_memory(args: dict, ctx: dict) -> dict:
    memory_id = args.get("memory_id", "").strip()
    if not memory_id:
        return {"ok": False, "error": "memory_id 必填"}

    try:
        with _db_lock, _conn() as c:
            cur = c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            c.commit()
            deleted = cur.rowcount
    except Exception as e:
        return {"ok": False, "error": f"刪除失敗：{e}"}

    if deleted == 0:
        return {"ok": False, "error": f"找不到 memory_id={memory_id!r}"}

    return {"ok": True, "memory_id": memory_id, "deleted_count": deleted}
