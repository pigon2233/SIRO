"""
bridge/tasks - SIRO 背景任務集合

每個 task 是一個 async function，被 AgentOS worker 從 queue 拉出來執行。
任務做完後會 emit 'task.completed' event，subscriber 可以訂閱拿到結果。

v1.2 加 SendTask infra：
- registry: task name → handler 對照表
- builtin: 5 個內建 task（mood.set / motion.play / persona.switch /
  chat.say / chat.summon）
- WS handler 在 main.py、SendTask 走 inline 跑（簡單 task 不走 AgentOS queue）
"""

from . import builtin  # 確保 builtin 模組被 import（register_builtin_tasks 用）
from .builtin import register_builtin_tasks
from .llm_reply_task import create_llm_reply_task
from .registry import (
    TaskHandler,
    get as get_task,
    has as has_task,
    list_tasks,
    register,
    unregister,
)

__all__ = [
    "create_llm_reply_task",
    "TaskHandler",
    "register",
    "get_task",
    "has_task",
    "list_tasks",
    "unregister",
    "register_builtin_tasks",
]
