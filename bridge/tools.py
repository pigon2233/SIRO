"""
bridge/tools.py - v1.5+ LLM Tool Calling 工具定義

v1.5+ 設計：
- LLM 用 native tool_use API（Anthropic / OpenAI / Ollama 都支援）選 emotion/actions
- 不再依賴 regex 解析 [emotion:xxx] 文字（v0.2~v1.2 機制）
- Bridge 收到 tool_use 區塊、invoke 對應的 SendTask

目前（v1.5.0）支援的 tool：
- set_mood：LLM 選 emotion + intensity → 觸發 mood.set task

未來 v1.5+ roadmap：
- play_motion：LLM 選 motion_group + index → 觸發 motion.play
- switch_persona：LLM 切 persona → 觸發 persona.switch
- summon_chat：LLM 主動召喚使用者回對話

格式：Anthropic tool_use 標準
（MiniMax-M3 是 Anthropic-compatible、Ollama 用同格式轉譯）
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
    未來 v1.5+ 加新 tool 只要在這裡加、TOOL_TO_TASK 也加一筆
    """
    return [SET_MOOD_TOOL, PLAY_MOTION_TOOL]


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
