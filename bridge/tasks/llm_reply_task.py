"""
bridge/tasks/llm_reply_task.py - 第一個 AgentOS 任務

包現有 /chat 跟 /ws 的 hermes 呼叫邏輯：
- 拿 persona + system_prompt
- 組對話歷史
- 叫 hermes.chat()（透過 asyncio.to_thread 不卡 event loop）
- parse 情緒、組 Live2D signal
- 結果透過 task.completed event 推回 Unity

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
