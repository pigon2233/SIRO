"""
bridge/tools/ — v1.5+ SIRO 工具集（package）

v1.5+ 設計：
- LLM 用 native tool_use API（Anthropic / OpenAI / Ollama 都支援）選 emotion/actions
- Bridge 收到 tool_use 區塊、invoke 對應的 executor

結構：
- filesystem / shell / memory / meta：v1.5+ 新加的 computer control 工具
- 內含 SET_MOOD / PLAY_MOTION（既有 v1.2+ SendTask tools）re-export

執行細節：
- 每個 tool 模組提供 (definition, executor, category)
- registry（這檔）把 tool name 對到 executor
- main.py 的 tool dispatch loop 查 registry

完整設計見 docs/PLANS/agent-computer-control.md
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# ============================================================
# 從 legacy compat 模組 re-export v1.2+ SendTask tools
# （bridge/tools.py 改名避免跟 package 衝突）
# ============================================================

from ..tools_legacy_compat import (
    SET_MOOD_TOOL,
    PLAY_MOTION_TOOL,
    TOOL_TO_TASK,
    get_tool_by_name,
    task_name_for_tool,
)


# ============================================================
# v1.5+ 工具實作
# ============================================================

from . import filesystem, shell, memory, meta


# ============================================================
# Tool registry: name → (definition, executor, category)
# ============================================================
#
# 每個 entry 形如：
# {
#     "definition": {...Anthropic tool schema...},
#     "executor":   async def executor(args, ctx) -> dict,
#     "category":   "auto" | "confirm" | "block",
# }
#
# - auto:     直接跑
# - confirm:  跑之前先問 user（透過 confirmation broker）
# - block:    永遠拒絕（不應該在這、blacklist 處理在 shell.py 內）
#
# ctx 內容（給 executor 用）：
#   {
#       "user_id": str,
#       "confirmation_broker": Optional[ConfirmationBroker],
#   }
# 工具可以自己決定要不要用 broker（meta.request_confirmation 用）


_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _register(name: str, definition: dict, executor: Callable, category: str = "auto") -> None:
    _REGISTRY[name] = {
        "definition": definition,
        "executor": executor,
        "category": category,
    }


# filesystem
_register("list_dir", filesystem.LIST_DIR_TOOL, filesystem.execute, "auto")
_register("read_file", filesystem.READ_FILE_TOOL, filesystem.read_file, "auto")
_register("write_file", filesystem.WRITE_FILE_TOOL, filesystem.write_file, "auto")
_register("search_files", filesystem.SEARCH_FILES_TOOL, filesystem.search_files, "auto")
_register("mkdir", filesystem.MKDIR_TOOL, filesystem.mkdir, "auto")

# shell
_register("run_shell_cmd", shell.RUN_SHELL_CMD_TOOL, shell.run_shell_cmd, "confirm")

# memory
_register("save_memory", memory.SAVE_MEMORY_TOOL, memory.save_memory, "auto")
_register("recall_memory", memory.RECALL_MEMORY_TOOL, memory.recall_memory, "auto")
_register("list_memories", memory.LIST_MEMORIES_TOOL, memory.list_memories, "auto")
_register("delete_memory", memory.DELETE_MEMORY_TOOL, memory.delete_memory, "confirm")

# meta
_register("get_current_time", meta.GET_CURRENT_TIME_TOOL, meta.get_current_time, "auto")
_register("sleep", meta.SLEEP_TOOL, meta.sleep_async, "auto")
_register("request_confirmation", meta.REQUEST_CONFIRMATION_TOOL, meta.request_confirmation, "auto")


# ============================================================
# Public API
# ============================================================

def get_available_tools() -> List[Dict[str, Any]]:
    """回傳所有 v1.5+ 啟用的 tool 定義 list

    用法：client.chat_stream(messages, tools=get_available_tools())

    合併兩組：
    - 既有 v1.2+ SendTask tools（set_mood / play_motion）
    - v1.5+ 新加的 computer control tools

    v1.5.2 trust_mode 時：把 request_confirmation 拿掉
        （trust mode 預設開了、LLM 不該需要問 user、直接做就好）
    """
    import os
    trust_mode = os.environ.get("SIRO_TRUST_MODE", "true").lower() == "true"

    all_tools = [SET_MOOD_TOOL, PLAY_MOTION_TOOL] + get_tool_definitions()
    if trust_mode:
        # trust mode 拿掉 request_confirmation（避免 LLM 浪費一輪問 user）
        all_tools = [t for t in all_tools if t["name"] != "request_confirmation"]
    return all_tools


def get_tool_definitions() -> list[dict]:
    """拿 v1.5+ 新加的 tool definition list（不含 mood/motion）"""
    return [entry["definition"] for entry in _REGISTRY.values()]


def get_tool_executor(name: str) -> Optional[Callable]:
    """拿 tool executor（給 dispatch loop 用）"""
    entry = _REGISTRY.get(name)
    return entry["executor"] if entry else None


def get_tool_category(name: str) -> str:
    """拿 tool category（給 main.py dispatch 決定要不要問 confirm）"""
    entry = _REGISTRY.get(name)
    return entry["category"] if entry else "unknown"


def get_tool_registry() -> Dict[str, Dict[str, Any]]:
    """拿完整 registry（給 debug 用）"""
    return _REGISTRY


# ============================================================
# v1.5+ Computer control — tool executor dispatch
# ============================================================

async def execute_tool_call(tool_name: str, args: dict, ctx: dict) -> dict:
    """執行一個 tool_use 區塊、回傳 tool_result 給 LLM

    Args:
        tool_name: LLM 在 tool_use 給的 name
        args: LLM 給的 input
        ctx: 給 executor 的 context（user_id、confirmation_broker、websocket 等）

    Returns:
        dict: tool 執行結果（給 LLM 看的 JSON string）

    Note:
        Routing:
        - "set_mood" / "play_motion" → caller 自己處理（SendTask 路徑）
          這裡回傳 {"_needs_sendtask": True, ...} 標記
        - 其他 tool → registry executor
        - 未知 tool → error
    """
    if tool_name in ("set_mood", "play_motion"):
        # 既有 v1.2+ SendTask 路徑（不動）
        # 呼叫端 (_process_ws_chat / _run_llm_reply_with_tools) 自己處理
        return {"_needs_sendtask": True, "tool": tool_name, "args": args}

    executor = get_tool_executor(tool_name)
    if executor is None:
        return {"ok": False, "error": f"未知 tool: {tool_name!r}"}

    # 跑 executor
    try:
        result = await executor(args, ctx)
        return result
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


__all__ = [
    "SET_MOOD_TOOL",
    "PLAY_MOTION_TOOL",
    "TOOL_TO_TASK",
    "get_tool_by_name",
    "task_name_for_tool",
    "get_available_tools",
    "get_tool_definitions",
    "get_tool_executor",
    "get_tool_category",
    "get_tool_registry",
    "execute_tool_call",
]
