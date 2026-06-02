"""
bridge/main.py - SIRO Bridge FastAPI 入口

啟動：
    uvicorn bridge.main:app --reload --host 127.0.0.1 --port 8001
或：
    python -m bridge.main
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .emotion_parser import EmotionParser
from .hermes_client import HermesClient
from .models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    Live2DSignal,
    Emotion,
)
from .prompts import get_personality

# 載入 .env
load_dotenv()

# 設定 logging
LOG_LEVEL = os.environ.get("BRIDGE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("siro.bridge")

# 抑制 httpx 噪音
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ==================== 全域狀態 ====================

class BridgeState:
    """Bridge 全域狀態"""

    def __init__(self):
        self.hermes: HermesClient | None = None
        self.parser: EmotionParser | None = None
        self.sessions: Dict[str, list[dict]] = {}  # session_id -> 對話歷史


state = BridgeState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用啟動與關閉"""
    logger.info("🚀 SIRO Bridge 啟動中...")

    # 初始化 Hermes client
    state.hermes = HermesClient(
        binary_path=os.environ.get("HERMES_BIN_PATH"),
        timeout=int(os.environ.get("HERMES_TIMEOUT", "60")),
    )
    if state.hermes.is_available():
        version = state.hermes.get_version()
        logger.info(f"✓ Hermes 可用: {version}")
    else:
        logger.warning("⚠ Hermes 不可用，請確認有跑過 agent/install.sh")

    # 初始化情緒解析器
    state.parser = EmotionParser()
    logger.info("✓ 情緒解析器就緒")

    yield

    logger.info("🛑 SIRO Bridge 關閉")


# ==================== App ====================

app = FastAPI(
    title="SIRO Bridge",
    description="SIRO Live2D AI Agent OS - Bridge 服務",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS（給 Unity 開發用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 端點 ====================

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """健康檢查"""
    hermes_available = state.hermes.is_available() if state.hermes else False
    hermes_version = state.hermes.get_version() if hermes_available else None

    return HealthResponse(
        status="ok" if hermes_available else "degraded",
        hermes_available=hermes_available,
        hermes_version=hermes_version,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    單次對話。

    流程：
    1. 呼叫 Hermes CLI 取得回應
    2. 解析情緒標籤
    3. 映射成 Live2D 訊號
    4. 記錄 session 歷史
    """
    if not state.hermes or not state.parser:
        raise HTTPException(status_code=503, detail="Bridge 尚未初始化")

    if not state.hermes.is_available():
        raise HTTPException(
            status_code=503,
            detail="Hermes 不可用，請確認有跑過 agent/install.sh 並設定 LLM",
        )

    # 決定 session
    session_id = req.session_id or f"{req.user_id}-{uuid.uuid4().hex[:8]}"

    # 載入對話歷史（簡化版：塞進 prompt 上下文）
    history = state.sessions.get(session_id, [])
    history_context = ""
    if history:
        history_context = "\n\n最近的對話：\n" + "\n".join(
            f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
        )

    # 組 prompt
    user_message_with_context = req.message
    if history_context:
        user_message_with_context = f"{history_context}\n\n使用者: {req.message}"

    system_prompt = get_personality(req.personality or "default")

    # 呼叫 Hermes
    result = state.hermes.chat(
        message=user_message_with_context,
        system_prompt=system_prompt,
    )

    if not result.success:
        logger.error(f"Hermes 失敗: {result.error}")
        raise HTTPException(
            status_code=502,
            detail=f"Hermes 對話失敗: {result.error}",
        )

    # 解析情緒
    clean_text, emotion, intensity = state.parser.parse(result.output)
    live2d_signal = state.parser.to_live2d_signal(emotion, intensity)

    # 記錄歷史
    if session_id not in state.sessions:
        state.sessions[session_id] = []
    state.sessions[session_id].append({
        "user": req.message,
        "agent": clean_text,
        "emotion": emotion.value,
    })
    # 限制歷史長度
    state.sessions[session_id] = state.sessions[session_id][-20:]

    return ChatResponse(
        text=clean_text,
        emotion=emotion,
        intensity=intensity,
        live2d=live2d_signal,
        session_id=session_id,
        user_id=req.user_id,
        raw_response=result.output,
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 端點。

    訊息格式：
        發送: {"type": "chat", "message": "...", "user_id": "..."}
        接收: {"type": "response", "text": "...", "emotion": "...", "live2d": {...}}
        接收: {"type": "error", "detail": "..."}
    """
    await websocket.accept()
    logger.info(f"🔌 WebSocket 連線: {websocket.client}")

    if not state.hermes or not state.parser:
        await websocket.send_json({"type": "error", "detail": "Bridge 尚未初始化"})
        await websocket.close()
        return

    if not state.hermes.is_available():
        await websocket.send_json({"type": "error", "detail": "Hermes 不可用"})
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "chat":
                message = data.get("message", "").strip()
                user_id = data.get("user_id", "default")
                personality = data.get("personality", "default")

                if not message:
                    await websocket.send_json({"type": "error", "detail": "訊息不能空白"})
                    continue

                # 跑對話
                session_id = f"{user_id}-ws"
                history = state.sessions.get(session_id, [])
                history_context = ""
                if history:
                    history_context = "\n\n最近的對話：\n" + "\n".join(
                        f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
                    )

                prompt_message = f"{history_context}\n\n使用者: {message}" if history_context else message
                system_prompt = get_personality(personality)

                result = state.hermes.chat(
                    message=prompt_message,
                    system_prompt=system_prompt,
                )

                if not result.success:
                    await websocket.send_json({
                        "type": "error",
                        "detail": result.error or "Hermes 對話失敗",
                    })
                    continue

                clean_text, emotion, intensity = state.parser.parse(result.output)
                live2d_signal = state.parser.to_live2d_signal(emotion, intensity)

                if session_id not in state.sessions:
                    state.sessions[session_id] = []
                state.sessions[session_id].append({
                    "user": message,
                    "agent": clean_text,
                    "emotion": emotion.value,
                })
                state.sessions[session_id] = state.sessions[session_id][-20:]

                await websocket.send_json({
                    "type": "response",
                    "text": clean_text,
                    "emotion": emotion.value,
                    "intensity": intensity,
                    "live2d": live2d_signal.model_dump(),
                    "session_id": session_id,
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "detail": f"未知的訊息類型: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket 斷線: {websocket.client}")
    except Exception as e:
        logger.exception(f"WebSocket 錯誤: {e}")
        try:
            await websocket.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass


# ==================== 入口 ====================

def run():
    """指令列啟動"""
    import uvicorn
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "8001"))
    print(f"""
╔════════════════════════════════════════╗
║  SIRO Bridge                            ║
║  http://{host}:{port}
╚════════════════════════════════════════╝
    """)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
