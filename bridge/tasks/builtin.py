"""
bridge/tasks/builtin.py - v1.2 預設 task handlers

5 個 built-in task（規格見 AGENT_OS.md v1.2 段）：
- mood.set      設當前 mood（emotion_parser 後續 chat 用）
- motion.play   記錄 motion 觸發（Unity 端 motion 執行留 v1.5+ 訂閱機制）
- persona.switch 切換 persona
- chat.say      Mao 主動說話（v1.2 只 log，TTS 留 v1.5+）
- chat.summon   Mao 召回對話（v1.2 只 log）

設計：每個 handler 都純函式、async、不副作用到全域（除了 state 明確欄位）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..models import Emotion
from ..prompts import load_persona
from .registry import register

logger = logging.getLogger("siro.tasks.builtin")


# ==================== mood.set ====================

async def mood_set(args: dict, ctx: dict) -> dict:
    """
    設當前 mood — 影響後續 chat 的 emotion 預設

    Args:
        args: {"emotion": "happy", "intensity": 0.7}（intensity optional，預設 0.7）
        ctx: {state, user_id, task_id}
    Returns:
        {"ok": True, "mood": {"emotion": "happy", "intensity": 0.7}}
    Raises:
        ValueError: emotion 不合法
    """
    emotion_str = args.get("emotion")
    if not emotion_str:
        raise ValueError("mood.set: missing required arg 'emotion'")

    intensity = float(args.get("intensity", 0.7))
    if not (0.0 <= intensity <= 1.0):
        raise ValueError(f"mood.set: intensity {intensity} out of range [0, 1]")

    # 驗證 emotion 合法（用現有 Emotion enum）
    valid_emotions = {e.value for e in Emotion}
    if emotion_str not in valid_emotions:
        raise ValueError(
            f"mood.set: invalid emotion {emotion_str!r} "
            f"(valid: {sorted(valid_emotions)})"
        )

    state = ctx["state"]
    # 設在 state 上（給後續 /chat 的 emotion_parser 預設用）
    if not hasattr(state, "current_mood") or state.current_mood is None:
        state.current_mood = {}
    state.current_mood[ctx["user_id"]] = {
        "emotion": emotion_str,
        "intensity": intensity,
        "set_at": time.time(),
    }

    logger.info(
        f"[mood.set] user={ctx['user_id']} → emotion={emotion_str} intensity={intensity}"
    )
    return {
        "ok": True,
        "mood": state.current_mood[ctx["user_id"]],
    }


# ==================== motion.play ====================

async def motion_play(args: dict, ctx: dict) -> dict:
    """
    記錄 motion 觸發（v1.2 不直接驅動 Unity，bridge 只 log/記錄）

    v1.5+ 預期：bridge 推 motion event 到 Unity event bus、Unity 訂閱執行
    v1.2 MVP：先 log + 存 state 給 debug 看

    Args:
        args: {"motion_group": "Idle", "motion_index": 0}
    Returns:
        {"ok": True, "motion": {"motion_group": "...", "motion_index": 0}}
    """
    motion_group = args.get("motion_group")
    motion_index = args.get("motion_index", 0)

    if not motion_group:
        raise ValueError("motion.play: missing required arg 'motion_group'")

    state = ctx["state"]
    if not hasattr(state, "last_motion") or state.last_motion is None:
        state.last_motion = []
    state.last_motion.append({
        "user_id": ctx["user_id"],
        "task_id": ctx["task_id"],
        "motion_group": motion_group,
        "motion_index": int(motion_index),
        "at": time.time(),
    })
    # 只留最近 50 個、避免無限制長大
    state.last_motion = state.last_motion[-50:]

    logger.info(
        f"[motion.play] user={ctx['user_id']} → "
        f"{motion_group}[{motion_index}]"
    )
    return {
        "ok": True,
        "motion": {
            "motion_group": motion_group,
            "motion_index": int(motion_index),
        },
    }


# ==================== persona.switch ====================

async def persona_switch(args: dict, ctx: dict) -> dict:
    """
    切換 persona — 載入新 persona YAML、驗證存在

    Args:
        args: {"persona_id": "siro-default"}
    Returns:
        {"ok": True, "persona_id": "...", "name": "..."}
    Raises:
        ValueError: persona 不存在
    """
    persona_id = args.get("persona_id")
    if not persona_id:
        raise ValueError("persona.switch: missing required arg 'persona_id'")

    persona = load_persona(persona_id)
    if persona is None:
        raise ValueError(
            f"persona.switch: persona {persona_id!r} not found"
        )

    state = ctx["state"]
    state.active_persona = persona_id
    logger.info(
        f"[persona.switch] user={ctx['user_id']} → {persona_id} "
        f"({persona.get('name', persona_id)})"
    )
    return {
        "ok": True,
        "persona_id": persona_id,
        "name": persona.get("name", persona_id),
    }


# ==================== chat.say ====================

async def chat_say(args: dict, ctx: dict) -> dict:
    """
    Mao 主動說話 — v1.2 只 log（TTS 留 v1.5+）

    用途：例如任務完成後 Mao 主動講「完成！」而不需 user 觸發
    v1.5+ 接 TTS 會：把 text 送 piper / edge-tts 然後 audio stream 到 Unity

    Args:
        args: {"text": "完成！"}
    Returns:
        {"ok": True, "text": "...", "delivered": False}  ← False = v1.2 還沒接 TTS
    """
    text = args.get("text")
    if not text:
        raise ValueError("chat.say: missing required arg 'text'")

    logger.info(
        f"[chat.say] user={ctx['user_id']} → Mao 主動說: {text!r} "
        f"（v1.2 只 log、TTS 留 v1.5+）"
    )
    return {
        "ok": True,
        "text": text,
        "delivered": False,  # v1.2 還沒 TTS
    }


# ==================== chat.summon ====================

async def chat_summon(args: dict, ctx: dict) -> dict:
    """
    Mao 召回對話 — v1.2 只 log（「嘿、在嗎？」觸發）

    用途：排程 / reminder 到時叫使用者回來
    v1.5+ 可以接 chat.say + emotion 自動選「呼喚」表情

    Args:
        args: {}（目前無參數）
    Returns:
        {"ok": True, "summoned": True}
    """
    logger.info(
        f"[chat.summon] user={ctx['user_id']} → Mao 召喚使用者回來對話"
    )
    return {"ok": True, "summoned": True}


# ==================== 註冊所有 built-in ====================

def register_builtin_tasks() -> None:
    """在 lifespan 啟動時呼叫、註冊所有 v1.2 內建 task

    Idempotent：已註冊的 task 不會 raise（用 overwrite=True 跳過 ValueError）。
    這樣測試 fixture 多次呼叫 register_builtin_tasks 不會壞、production
    lifespan 重啟也安全。
    """
    register("mood.set", mood_set, overwrite=True)
    register("motion.play", motion_play, overwrite=True)
    register("persona.switch", persona_switch, overwrite=True)
    register("chat.say", chat_say, overwrite=True)
    register("chat.summon", chat_summon, overwrite=True)
