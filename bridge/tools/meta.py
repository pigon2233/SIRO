"""
bridge/tools/meta.py - v1.5+ Meta 工具

提供：
- get_current_time: 拿現在時間
- sleep: 睡幾秒（避免 SIRO busy loop）
- request_confirmation: 主動問 user 一個是非題
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Tool definitions
# ============================================================

GET_CURRENT_TIME_TOOL: dict[str, Any] = {
    "name": "get_current_time",
    "description": "拿現在時間（ISO 8601 格式）、可選時區。",
    "input_schema": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "default": "UTC",
                "description": "時區, e.g. 'UTC', 'Asia/Taipei'",
            },
        },
        "required": [],
    },
}

SLEEP_TOOL: dict[str, Any] = {
    "name": "sleep",
    "description": (
        "睡幾秒。SIRO 用這個避免 busy loop。"
        "最大 60 秒、最小 0.1 秒。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "minimum": 0.1,
                "maximum": 60.0,
                "description": "睡幾秒",
            },
        },
        "required": ["seconds"],
    },
}

REQUEST_CONFIRMATION_TOOL: dict[str, Any] = {
    "name": "request_confirmation",
    "description": (
        "主動問 user 一個是非題。user 回 yes / no 之前你會被 block 住。"
        "user 60 秒沒回就視為 no。\n"
        "用這個來：\n"
        "- 重要決策前先問 user\n"
        "- 跑不確定的操作前先確認\n"
        "- 詢問 user 偏好"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要問的問題"},
            "context": {
                "type": "string",
                "default": "",
                "description": "背景資訊（給 user 看的）",
            },
        },
        "required": ["question"],
    },
}


# ============================================================
# Executors
# ============================================================

async def get_current_time(args: dict, ctx: dict) -> dict:
    tz_name = args.get("timezone", "UTC")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
    except (ImportError, KeyError, ValueError):
        # 沒 zoneinfo（Py < 3.9）or 找不到時區 → fallback UTC
        now = datetime.now(timezone.utc)
        tz_name = "UTC"

    return {
        "ok": True,
        "timestamp": now.isoformat(),
        "timezone": tz_name,
        "unix": int(now.timestamp()),
    }


async def sleep_async(args: dict, ctx: dict) -> dict:
    seconds = float(args.get("seconds", 1.0))
    if seconds < 0.1:
        seconds = 0.1
    if seconds > 60.0:
        seconds = 60.0
    await asyncio.sleep(seconds)
    return {
        "ok": True,
        "slept_sec": seconds,
    }


async def request_confirmation(args: dict, ctx: dict) -> dict:
    """主動問 user 一個是非題"""
    question = args.get("question", "").strip()
    context = args.get("context", "").strip()

    if not question:
        return {"ok": False, "error": "question 必填"}

    broker = ctx.get("confirmation_broker")
    if broker is None:
        return {
            "ok": False,
            "error": "目前沒有 confirmation broker、無法問 user。",
        }

    description = question
    if context:
        description = f"{question}\n（{context}）"

    approved = await broker.request(
        tool="request_confirmation",
        args={"question": question, "context": context},
        description=description,
    )

    return {
        "ok": True,
        "question": question,
        "approved": approved,
        "user_response": "yes" if approved else "no",
    }
