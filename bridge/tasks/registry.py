"""
bridge/tasks/registry.py - v1.2 SendTask 的 task name → handler 對照表

v1.2 設計：
- Unity 透過 WS 送 {"type": "task", "task_id": "...", "name": "...", "args": {...}}
- bridge 從 registry 查 handler、跑完後推 task_result 或 task_failed
- handler 簽名：async (args: dict, ctx: dict) -> result: dict

為什麼用 registry 不用 if/elif：
- 加新 task 不用改 main.py
- 第三方 plugin（v1.5+）可以 register 自己的 task
- 測試可以替換 handler

ctx 內容（給 handler 用）：
- state: BridgeState（拿 persona、history、agent_os 等）
- user_id: 送 task 的 Unity 使用者
- task_id: 這次 task 的 ID（給 logging / 訂閱用）
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("siro.tasks.registry")

# handler 簽名：async (args, ctx) -> result
TaskHandler = Callable[[dict, dict], Awaitable[dict]]

_REGISTRY: dict[str, TaskHandler] = {}


def register(name: str, handler: TaskHandler, *, overwrite: bool = False) -> None:
    """
    註冊 task handler

    Args:
        name: task 名稱（例如 "mood.set"）
        handler: async function (args, ctx) -> result
        overwrite: 預設 False — 已存在同名 task 會 raise
    """
    if name in _REGISTRY and not overwrite:
        raise ValueError(
            f"task {name!r} already registered; use overwrite=True to replace"
        )
    _REGISTRY[name] = handler
    logger.info(f"[TaskRegistry] 註冊 task: {name} → {handler.__name__}")


def get(name: str) -> Optional[TaskHandler]:
    """拿 handler；找不到回 None（呼叫端自己決定怎麼處理）"""
    return _REGISTRY.get(name)


def has(name: str) -> bool:
    return name in _REGISTRY


def list_tasks() -> list[str]:
    """列出所有已註冊 task（給 debug / 監控用）"""
    return sorted(_REGISTRY.keys())


def unregister(name: str) -> bool:
    """取消註冊（測試用）"""
    if name in _REGISTRY:
        del _REGISTRY[name]
        return True
    return False
