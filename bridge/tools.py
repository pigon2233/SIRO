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
                    "happy",        # 開心、滿足
                    "sad",          # 難過、失落
                    "angry",        # 生氣、不滿
                    "surprised",    # 驚訝、意外
                    "neutral",      # 平靜、沒情緒
                    "relaxed",      # 放鬆、悠閒
                    "thinking",     # 思考、疑惑
                    "embarrassed",  # 害羞、不好意思
                    "love",         # 喜歡、關愛
                ],
                "description": "The emotion to display on Mao's face. Must be one of the 9 supported emotions."
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
# Tool registry
# ============================================================

# 哪些 task name 對應到 tool 名字
# 當 LLM 回 tool_use 時、bridge 查表決定 invoke 哪個 SendTask
TOOL_TO_TASK: Dict[str, str] = {
    "set_mood": "mood.set",
    # "play_motion": "motion.play",     # v1.5+ 待加
    # "switch_persona": "persona.switch",
}


def get_available_tools() -> List[Dict[str, Any]]:
    """回傳所有 v1.5+ 啟用的 tool 定義 list

    用法：client.chat_stream(messages, tools=get_available_tools())

    為什麼是 list：Anthropic API tools 是 list of tools（可多個同時提供）
    未來 v1.5+ 加新 tool 只要在這裡加、TOOL_TO_TASK 也加一筆
    """
    return [SET_MOOD_TOOL]


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
