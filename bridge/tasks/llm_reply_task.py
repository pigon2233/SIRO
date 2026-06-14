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
from typing import Any, Callable, Dict, Optional

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

    # v1.5.3：優先用 streaming_client（minimax / ollama / openai 任何 provider）
    # fallback 才用 hermes（給沒裝 OpenAI 的人逃生）
    t0 = time.time()
    if state.streaming_client and state.streaming_client.is_available:
        logger.info(f"[LLMReply] 走 streaming_client (provider={state.streaming_client.provider})")
        result = await state.streaming_client.chat_collect(
            message=user_message_with_context,
            system_prompt=system_prompt,
            max_tokens=1024,
        )
        llm_ms = (time.time() - t0) * 1000
        if not result.success:
            return {
                "status": "error",
                "error": result.error or "streaming failed",
                "fallback_text": get_fallback_response("error", persona_name=persona_name),
            }
        llm_output = result.text
    elif state.hermes.is_available():
        # 舊 hermes 路徑
        logger.info("[LLMReply] 走 hermes subprocess (legacy)")
        result = await asyncio.to_thread(
            state.hermes.chat,
            message=user_message_with_context,
            system_prompt=system_prompt,
        )
        llm_ms = (time.time() - t0) * 1000
        if not result.success:
            return {
                "status": "error",
                "error": result.error,
                "fallback_text": get_fallback_response("error", persona_name=persona_name),
            }
        llm_output = result.output
    else:
        # 兩條路都沒
        return {
            "status": "error",
            "error": "no LLM backend available (streaming_client + hermes all down)",
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    # 5. 解析情緒
    t1 = time.time()
    clean_text, emotion, intensity = parser.parse(llm_output, user_input=message)
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
        f"[LLMReply] 完成 {total_ms:.0f}ms (llm={llm_ms:.0f}ms parse={parse_ms:.0f}ms) "
        f"emotion={emotion.value} text={clean_text[:60]!r}"
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


# ============================================================
# v1.5+ Computer Control — multi-turn agent loop
# ============================================================

def create_llm_agent_task(
    *,
    state,
    user_id: str,
    message: str,
    persona_name: str = "default",
    session_id: str = "",
    max_iterations: int = 3,  # v1.5+ 預設 3 輪（v1.5.1 觀察：5 輪會 runaway、3 輪更聚焦）
) -> Task:
    """v1.5+ 走 multi-turn agent loop 的 LLM reply task

    跟 create_llm_reply_with_tools_task 差異：
    - 走 state.streaming_client.run_agent_loop（非 streaming、多輪）
    - LLM 可以 call tool、execute、回 tool_result、再 LLM（最多 max_iterations 輪）
    - 支援 v1.5+ 全部 15 個 tools（含 filesystem / shell / memory / meta）

    用於「給 SIRO 一台空電腦養人格」這種 agent 場景。
    """
    if not session_id:
        session_id = f"{user_id}-{uuid.uuid4().hex[:8]}"

    return Task(
        name="llm.reply.agent",
        coro_factory=_run_llm_agent,
        kwargs={
            "state": state,
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "persona_name": persona_name,
            "max_iterations": max_iterations,
        },
    )


async def _run_llm_agent(
    *,
    state,
    user_id: str,
    session_id: str,
    message: str,
    persona_name: str,
    max_iterations: int,
) -> Dict[str, Any]:
    """v1.5+ multi-turn agent loop 的實際跑法

    流程：
    1. 拿 persona parser
    2. 組對話歷史（如果有）
    3. 用 run_agent_loop 跑 LLM
       - LLM 給 tool_use → 透過 tool dispatcher 執行
       - dispatcher 處理 set_mood/play_motion（SendTask）/ 走 registry / 走 confirmation
    4. 拿 LLM 最終文字
    5. emotion 用最後一個 set_mood tool_use、或 regex parse
    6. 寫歷史
    """
    t_start = time.time()
    logger.info(
        f"[LLMAgent] 開始 user={user_id!r} persona={persona_name!r} msg={message[:30]!r}"
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

    # 3. streaming client check
    if not state.streaming_client or not state.streaming_client.is_available:
        return {
            "status": "error",
            "error": "Streaming client not available (need MiniMax-M3 config)",
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    # 4. 定義 tool dispatcher（給 run_agent_loop 用的 executor）
    from ..confirmation import ConfirmationBroker
    from ..tools import execute_tool_call
    from ..security import guarded_action, SecurityError

    # ctx 給 executor 用（含 confirmation broker、user_id）
    ctx = {
        "user_id": user_id,
        "confirmation_broker": state.confirmation_broker,  # ConfirmationBroker | None
    }

    last_mood: Optional[Dict[str, Any]] = None  # 記最後一個 set_mood（給 emotion 用）

    async def _agent_executor(tool_name: str, tool_args: dict, _ctx: dict) -> dict:
        nonlocal last_mood

        # set_mood / play_motion 走 SendTask
        if tool_name in ("set_mood", "play_motion"):
            from ..tasks import get_task

            # 記 mood
            if tool_name == "set_mood":
                last_mood = {
                    "emotion": tool_args.get("emotion", "neutral"),
                    "intensity": float(tool_args.get("intensity", 0.7)),
                }

            task_handler = get_task("mood.set" if tool_name == "set_mood" else "motion.play")
            if task_handler is None:
                return {"ok": False, "error": f"{tool_name} task 沒註冊"}

            try:
                # SendTask handler 簽名是 (args, ctx)、ctx 內有 state / websocket
                # 這裡用 background 跑、不 await result（agent loop 只要成功 / 失敗）
                asyncio.create_task(
                    task_handler(tool_args, {
                        "state": state,
                        "user_id": user_id,
                        "task_id": f"agent-{uuid.uuid4().hex[:8]}",
                        # 沒 websocket（task handler 會自己處理「沒 WS」的情況）
                    })
                )
                return {"ok": True, "tool": tool_name, "args": tool_args}
            except Exception as e:
                return {"ok": False, "error": f"sendtask 失敗: {e}"}

        # 其他 tool 走 registry + security guard
        try:
            with guarded_action(
                user_id=user_id,
                tool=tool_name,
                args=tool_args,
                user_confirmed=False,  # confirmation 內部處理
            ) as guard:
                result = await execute_tool_call(tool_name, tool_args, ctx)
                if result.get("ok", True):
                    guard.set_result("ok")
                else:
                    guard.mark_error(result.get("error", "unknown"))
                return result
        except SecurityError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # 5. 跑 agent loop
    try:
        agent_result = await state.streaming_client.run_agent_loop(
            user_message=user_message_with_context,
            system_prompt=system_prompt,
            tools=get_available_tools(),
            executor=_agent_executor,
            max_iterations=max_iterations,
            ctx=ctx,
        )
    except Exception as e:
        logger.exception(f"[LLMAgent] agent loop 失敗: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fallback_text": get_fallback_response("error", persona_name=persona_name),
        }

    # 6. 決定 emotion
    full_text = agent_result.text
    if last_mood:
        emotion_str = last_mood["emotion"]
        intensity = last_mood["intensity"]
    else:
        clean_text, emotion, intensity = parser.parse(full_text, user_input=message)
        emotion_str = emotion.value

    # 7. Live2D signal
    try:
        live2d_signal = parser.to_live2d_signal(Emotion(emotion_str), intensity)
    except Exception:
        live2d_signal = parser.to_live2d_signal(Emotion("neutral"), 0.5)
        emotion_str = "neutral"
        intensity = 0.5

    # 8. 寫歷史
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
        f"[LLMAgent] 完成 {total_ms:.0f}ms "
        f"iterations={agent_result.iterations} "
        f"tool_calls={len(agent_result.tool_calls)} "
        f"emotion={emotion_str} finish={agent_result.finish_reason}"
    )

    return {
        "status": "ok",
        "session_id": session_id,
        "user_id": user_id,
        "text": full_text,
        "emotion": emotion_str,
        "intensity": intensity,
        "live2d": live2d_signal.model_dump(),
        "iterations": agent_result.iterations,
        "tool_calls": [
            {
                "tool": tc.tool_name,
                "args": tc.args,
                "ok": tc.result.get("ok", False),
                "duration_ms": tc.duration_ms,
            }
            for tc in agent_result.tool_calls
        ],
        "finish_reason": agent_result.finish_reason,
    }
