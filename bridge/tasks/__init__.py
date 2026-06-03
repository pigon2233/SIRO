"""
bridge/tasks - SIRO 背景任務集合

每個 task 是一個 async function，被 AgentOS worker 從 queue 拉出來執行。
任務做完後會 emit 'task.completed' event，subscriber 可以訂閱拿到結果。
"""

from .llm_reply_task import create_llm_reply_task

__all__ = ["create_llm_reply_task"]
