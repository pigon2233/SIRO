"""
bridge/tools.py - v1.5+ LLM Tool Calling 工具定義（high-level facade）

v1.5+ 設計：
- LLM 用 native tool_use API（Anthropic / OpenAI / Ollama 都支援）選 emotion/actions
- 不再依賴 regex 解析 [emotion:xxx] 文字（v0.2~v1.2 機制）
- Bridge 收到 tool_use 區塊、invoke 對應的 executor

支援的 tool（v1.5+）：
- set_mood / play_motion：SendTask 路徑（既有 v1.2+）
- list_dir / read_file / write_file / search_files / mkdir：filesystem
- run_shell_cmd：shell（含 whitelist + confirmation + blocklist）
- save_memory / recall_memory / list_memories / delete_memory：SQLite 長期記憶
- get_current_time / sleep / request_confirmation：meta

執行細節在 bridge/tools/ 子模組、這檔是 high-level API：
- get_available_tools()：給 LLM 的 tool 定義 list
- get_tool_by_name() / task_name_for_tool()：查表
- execute_tool_call()：執行 tool、handle routing（SendTask vs registry）

格式：Anthropic tool_use 標準
（MiniMax-M3 是 Anthropic-compatible、Ollama 用同格式轉譯）

完整設計見 docs/PLANS/agent-computer-control.md
"""

from __future__ import annotations

from typing import Any, Dict, List

# ============================================================
# v1.5.0 第一個 tool：set_mood
# ============================================================

SET_MOOD_TOOL: Dict[str, Any] = {
    "name": "set_mood",
    "description": (
        "Set Mao's current emotion and intensity. "
        "Choose the most appropriate emotion based on the conversation context, "
        "Mao's personality, and what she's about to say. "
        "Always call this tool with your response, even if the emotion hasn't visibly changed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "emotion": {
                "type": "string",
                "enum": [
                    "happy",      # exp_01 開心、滿足
                    "joyful",     # exp_02 哈哈大笑
                    "proud",      # exp_03 驕傲、得意
                    "excited",    # exp_04 興奮
                    "sad",        # exp_05 難過、失落
                    "thinking",   # exp_06 思考、疑惑 — 注意：Mao 沒有真正 thinking 表情、
                                # 借用 exp_06 害羞臉。LLM 選 thinking 時 Mao 視覺會害羞，
                                # 視為「不好意思回答 / 在想怎麼說」之類的語意。
                    "surprised",  # exp_07 驚訝、意外
                    "angry",      # exp_08 生氣、不滿
                    "neutral",    # 無對應 expression、fallback 到 default
                ],
                "description": (
                    "The emotion to display on Mao's face. "
                    "Mao 支援 8 個 expression（exp_01-exp_08）+ neutral fallback、"
                    "所以 emotion 限定這 9 個值。\n"
                    "對應規則見 bridge/emotion_mapping.json emotion_map 段。"
                ),
            },
            "intensity": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.7,
                "description": (
                    "How strong the emotion is, 0-1. "
                    "Use 0.3-0.5 for subtle emotions, 0.7-0.9 for strong emotions, "
                    "1.0 for peak (rare)."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    "Brief internal note (1 sentence) explaining why this emotion fits. "
                    "For logging/debug, not shown to user."
                ),
            },
        },
        "required": ["emotion"],
    },
}


# ============================================================
# v1.5+ 第二個 tool：play_motion
# ============================================================

PLAY_MOTION_TOOL: Dict[str, Any] = {
    "name": "play_motion",
    "description": (
        "Trigger a Mao body/face motion animation. "
        "Use SPARINGLY — not every response needs a motion. "
        "Reserve for: emphasis (e.g., nodding along to a point), "
        "reactions (e.g., surprised jump), greetings (e.g., wave), "
        "or special moments (e.g., victory animation after good news). "
        "For routine text responses, do NOT call this tool — just respond with text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "motion_group": {
                "type": "string",
                "enum": [
                    "mtn_02",        # 短動作 1
                    "mtn_03",        # 短動作 2
                    "mtn_04",        # 短動作 3
                    "sample_01",     # gesture 範例
                    "special_01",    # 特殊動作 1
                    "special_02",    # 特殊動作 2
                    "special_03",    # 特殊動作 3
                ],
                "description": (
                    "Mao motion group name. "
                    "mtn_02-04 are short reaction motions (~2-3s). "
                    "sample_01 is a gesture example. "
                    "special_01-03 are longer special actions. "
                    "Note: mtn_01 is the idle breathing motion and runs automatically — do NOT trigger it."
                ),
            },
            "motion_index": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
                "description": (
                    "Index within the motion group. Most groups only have one motion, so 0 is the safe default."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Why this motion fits (for logging/debug).",
            },
        },
        "required": ["motion_group"],
    },
}


# ============================================================
# Tool registry
# ============================================================

# 哪些 task name 對應到 tool 名字
# 當 LLM 回 tool_use 時、bridge 查表決定 invoke 哪個 SendTask
TOOL_TO_TASK: Dict[str, str] = {
    "set_mood": "mood.set",
    "play_motion": "motion.play",
    # "switch_persona": "persona.switch",
}


def get_available_tools() -> List[Dict[str, Any]]:
    """回傳所有 v1.5+ 啟用的 tool 定義 list

    用法：client.chat_stream(messages, tools=get_available_tools())

    為什麼是 list：Anthropic API tools 是 list of tools（可多個同時提供）

    v1.5+ 自動合併：mood/motion tools（這檔）+ filesystem/shell/memory/meta
    tools（bridge.tools 子模組 registry）。
    """
    from .tools import get_tool_definitions
    return [SET_MOOD_TOOL, PLAY_MOTION_TOOL] + get_tool_definitions()


def get_tool_by_name(name: str) -> Dict[str, Any] | None:
    """依名字查 tool 定義（給 dynamic 場景用）"""
    for tool in get_available_tools():
        if tool["name"] == name:
            return tool
    return None


def task_name_for_tool(tool_name: str) -> str | None:
    """tool name → 對應的 SendTask name

    LLM 說 "set_mood"、bridge 知道要 invoke "mood.set" task
    """
    return TOOL_TO_TASK.get(tool_name)


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
        這個 function 處理 routing:
        - "set_mood" / "play_motion" 走 SendTask（既有 v1.2+ 路徑）
        - 其他 tool 走 bridge.tools registry
        - 未知 tool → error
    """
    from .tools import get_tool_executor

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
