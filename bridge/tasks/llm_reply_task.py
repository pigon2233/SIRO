"""
bridge/tasks/llm_reply_task.py - LLM reply AgentOS 任務

兩條路徑：
- _run_llm_reply (v0.3): 走 hermes subprocess (sync)
- _run_llm_reply_with_tools (v1.5+): 走 MiniMax-M3 SSE + LLM tool calling

設計：用 closure 把 state 傳進去，避免全域變數依賴
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Dict

from ..agent_os import Task, Event
from ..emotion_parser import EmotionParser
from ..prompts import get_personality, get_fallback_response, get_persona_expressions
from ..models import ChatResponse, Live2DSignal, Emotion
from ..tools import get_available_tools, task_name_for_tool, SET_MOOD_TOOL

logger = logging.getLogger("siro.tasks.llm_reply")


def create_llm_reply_task(
    *,
    state,  # bridge.main.BridgeState
    user_id: str,
    message: str,
    persona_name: str = "default",
    session_id: str = "",
) -> Task:
    """建一個 LLM reply 任務

    Args:
        state: bridge 的 BridgeState（拿 hermes / ollama / sessions）
        user_id: 使用者 ID
        message: 使用者訊息
        persona_name: persona 名（siro-default / 等）
        session_id: session ID（留空會自動產生）

    Returns:
        Task 物件，可以丟給 AgentOS.enqueue()
    """
    if not session_id:
        session_id = f"{user_id}-{uuid.uuid4().hex[:8]}"

    return Task(
        name="llm.reply",
        coro_factory=_run_llm_reply,
        kwargs={
            "state": state,
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "persona_name": persona_name,
        },
    )


async def _run_llm_reply(
    *, state, user_id: str, session_id: str, message: str, persona_name: str,
) -> Dict[str, Any]:
    """實際跑 LLM 回覆（worker 呼叫）

    回傳 dict — AgentOS 會 emit task.completed event 把這 dict 帶出去
    """
    t_start = time.time()
    logger.info(f"[LLMReply] 開始 user={user_id!r} persona={persona_name!r} msg={message[:30]!r}")

    # 1. 拿 persona 專屬 parser
    expressions = get_persona_expressions(persona_name)
    parser = EmotionParser(persona_expressions=expressions)

    # 2. 載入對話歷史
    history = state.sessions.get(session_id, [])
    history_context = ""
    if history:
        history_context = "\n\n最近的對話：\n" + "\n".join(
            f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
        )

    user_message_with_context = message
    if history_context:
        user_message_with_context = f"{history_context}\n\n使用者: {message}"

    system_prompt = get_personality(persona_name)

    # 3. 檢查 hermes 可用
    if not state.hermes.is_available():
        return {
            "status": "error",
            "error": "Hermes CLI not available",
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    # 4. 叫 hermes（用 to_thread 不卡 event loop）
    t0 = time.time()
    result = await asyncio.to_thread(
        state.hermes.chat,
        message=user_message_with_context,
        system_prompt=system_prompt,
    )
    hermes_ms = (time.time() - t0) * 1000

    if not result.success:
        return {
            "status": "error",
            "error": result.error,
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    # 5. 解析情緒
    t1 = time.time()
    clean_text, emotion, intensity = parser.parse(result.output, user_input=message)
    live2d_signal = parser.to_live2d_signal(emotion, intensity)
    parse_ms = (time.time() - t1) * 1000

    # 6. 記錄歷史（用 RLock 保護 — 雖然這裡其實是單 thread 在做，
    #    但未來 v1+ 多 worker 時要保險）
    with state.sessions_lock:
        if session_id not in state.sessions:
            state.sessions[session_id] = []
        state.sessions[session_id].append({
            "user": message,
            "agent": clean_text,
            "emotion": emotion.value,
        })
        state.sessions[session_id] = state.sessions[session_id][-20:]

    total_ms = (time.time() - t_start) * 1000
    logger.info(
        f"[LLMReply] 完成 {total_ms:.0f}ms (hermes={hermes_ms:.0f}ms parse={parse_ms:.0f}ms) "
        f"emotion={emotion.value}"
    )

    return {
        "status": "ok",
        "session_id": session_id,
        "user_id": user_id,
        "text": clean_text,
        "emotion": emotion.value,
        "intensity": intensity,
        "live2d": live2d_signal.model_dump(),
        "raw_response": result.output,
    }


# ============================================================
# v1.5+ LLM Tool Calling 路徑
# ============================================================

def create_llm_reply_with_tools_task(
    *,
    state,
    user_id: str,
    message: str,
    persona_name: str = "default",
    session_id: str = "",
) -> Task:
    """建一個走 SSE + tool calling 的 LLM reply 任務

    v1.5+ 設計：LLM 用 native tool_use API 選 emotion/actions
    不再依賴 regex 解析 [emotion:xxx] 文字

    跟 create_llm_reply_task 差異：
    - 走 state.streaming_client.chat_stream_with_tools
    - 帶 tools 參數（Anthropic tool_use 格式 list）
    - 結果可能含 tool_use 事件（invoke 對應 SendTask）
    - 文字 + emotion 都從 LLM 的回應解析

    向後兼容：
    - LLM 沒回 tool_use → fallback 到 regex parse
    - SIRO_USE_TOOL_CALLING=false → 這個 task 不被建立、main.py 走舊路徑
    """
    if not session_id:
        session_id = f"{user_id}-{uuid.uuid4().hex[:8]}"

    return Task(
        name="llm.reply.tools",
        coro_factory=_run_llm_reply_with_tools,
        kwargs={
            "state": state,
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "persona_name": persona_name,
        },
    )


async def _run_llm_reply_with_tools(
    *, state, user_id: str, session_id: str, message: str, persona_name: str,
) -> Dict[str, Any]:
    """v1.5+ tool calling 版 LLM reply

    流程：
    1. 拿 persona parser
    2. 組對話歷史
    3. 帶 tools 呼叫 chat_stream_with_tools
    4. 累積 text chunks + 第一個 tool_use（v1.5+ LLM 選 emotion）
    5. 沒 tool_use 就 fallback regex parse
    6. 寫歷史
    7. 回傳 result（text + emotion + intensity + 可選 tool_use 資訊）
    """
    t_start = time.time()
    logger.info(
        f"[LLMReply-Tools] 開始 user={user_id!r} persona={persona_name!r} msg={message[:30]!r}"
    )

    # 1. parser
    expressions = get_persona_expressions(persona_name)
    parser = EmotionParser(persona_expressions=expressions)

    # 2. 對話歷史
    history = state.sessions.get(session_id, [])
    history_context = ""
    if history:
        history_context = "\n\n最近的對話：\n" + "\n".join(
            f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
        )

    user_message_with_context = message
    if history_context:
        user_message_with_context = f"{history_context}\n\n使用者: {message}"

    system_prompt = get_personality(persona_name)

    # 3. 檢查 streaming client 可用
    if not state.streaming_client or not state.streaming_client.is_available:
        return {
            "status": "error",
            "error": "Streaming client not available (need MiniMax-M3 / Ollama config)",
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    # 4. 帶 tools 呼叫 LLM
    t0 = time.time()
    text_parts: list[str] = []
    tool_use = None  # 記錄第一個 tool_use（v1.5+ LLM 選 emotion）
    ttft_ms: int | None = None

    try:
        async for event in state.streaming_client.chat_stream_with_tools(
            message=user_message_with_context,
            system_prompt=system_prompt,
            tools=get_available_tools(),
        ):
            if event.type == "text":
                text_parts.append(event.text)
                if ttft_ms is None:
                    ttft_ms = int((time.time() - t0) * 1000)
            elif event.type == "tool_use":
                # v1.5+ LLM 選了 tool
                if tool_use is None:  # 只記第一個（v1.5 一次只支援一個）
                    tool_use = {"id": event.id, "name": event.name, "input": event.input}
                    logger.info(
                        f"[LLMReply-Tools] LLM 選 tool: {event.name} input={event.input}"
                    )
    except Exception as e:
        logger.exception(f"[LLMReply-Tools] streaming 失敗: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    full_text = "".join(text_parts)
    llm_ms = (time.time() - t0) * 1000

    # 5. 決定 emotion + intensity
    t1 = time.time()
    if tool_use and tool_use["name"] == "set_mood":
        # v1.5+ LLM 透過 tool_use 選 emotion（不用 regex parse）
        emotion_str = tool_use["input"].get("emotion", "neutral")
        intensity = float(tool_use["input"].get("intensity", 0.7))
        logger.info(
            f"[LLMReply-Tools] tool_use 選 emotion={emotion_str} intensity={intensity}"
        )
    else:
        # Fallback：regex parse [emotion:xxx]（v0.2~v1.2 機制）
        clean_text, emotion, intensity = parser.parse(full_text, user_input=message)
        emotion_str = emotion.value
        logger.info(
            f"[LLMReply-Tools] 沒 tool_use、fallback regex parse: emotion={emotion_str} intensity={intensity}"
        )

    # 6. 組 Live2D signal
    try:
        live2d_signal = parser.to_live2d_signal(
            Emotion(emotion_str), intensity
        )
    except Exception as e:
        logger.warning(
            f"[LLMReply-Tools] to_live2d_signal 失敗: {e}、fallback neutral"
        )
        live2d_signal = parser.to_live2d_signal(Emotion("neutral"), 0.5)
        emotion_str = "neutral"
        intensity = 0.5
    parse_ms = (time.time() - t1) * 1000

    # 7. 寫歷史
    with state.sessions_lock:
        if session_id not in state.sessions:
            state.sessions[session_id] = []
        state.sessions[session_id].append({
            "user": message,
            "agent": full_text,
            "emotion": emotion_str,
        })
        state.sessions[session_id] = state.sessions[session_id][-20:]

    total_ms = (time.time() - t_start) * 1000
    logger.info(
        f"[LLMReply-Tools] 完成 {total_ms:.0f}ms "
        f"(llm={llm_ms:.0f}ms ttft={ttft_ms}ms parse={parse_ms:.0f}ms) "
        f"emotion={emotion_str} tool_used={tool_use is not None}"
    )

    return {
        "status": "ok",
        "session_id": session_id,
        "user_id": user_id,
        "text": full_text,
        "emotion": emotion_str,
        "intensity": intensity,
        "live2d": live2d_signal.model_dump(),
        "tool_used": tool_use["name"] if tool_use else None,
        "raw_response": full_text,
    }
