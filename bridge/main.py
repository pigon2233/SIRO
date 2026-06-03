"""
bridge/main.py - SIRO Bridge FastAPI 入口

啟動：
    uvicorn bridge.main:app --reload --host 127.0.0.1 --port 8001
或：
    python -m bridge.main
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

# Windows console 預設 cp950 會解錯 hermes 的 UTF-8 輸出
# 強制整個 process 用 UTF-8
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .emotion_parser import EmotionParser
from .hermes_client import HermesClient
from .ollama_client import OllamaClient
from .models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    Live2DSignal,
    Emotion,
    PersonaSummary,
    PersonaDetail,
    PersonaListResponse,
)
from .prompts import (
    get_personality,
    get_fallback_response,
    get_persona_expressions,
    get_persona_model_meta,
    get_persona_quirks,
    list_personas,
    load_persona,
)

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
        self.ollama: OllamaClient | None = None
        self.parser: EmotionParser | None = None
        self.sessions: Dict[str, list[dict]] = {}  # session_id -> 對話歷史
        # v0.2+：per-persona parser cache — 同一 persona 重複 request 不重建 parser
        # EmotionParser.__init__ 雖然便宜，但 jieba 詞庫補強在第一次會跑 16 次 add_word
        # cache 起來省下這些 + dict copy
        self.parser_cache: Dict[str, EmotionParser] = {}


state = BridgeState()


def _build_parser_for_persona(persona_name: str) -> EmotionParser:
    """依 persona 名字拿一個配好 expressions 的 EmotionParser

    v0.2+：emotion_mapping.json 已併入 persona，parser 從 persona["model"]["expressions"]
    拿設定。

    v1.1+：用 state.parser_cache cache 起來，同一 persona 重複 request
    不重建 parser。第一次會建，之後直接 dict lookup。

    換 persona 才會建新 parser（cache 命中或換 key 都 O(1)）。
    """
    # alias：default / "" 都對應 siro-default
    cache_key = persona_name if persona_name else "siro-default"
    if persona_name in ("default", "", None):
        cache_key = "siro-default"

    if cache_key in state.parser_cache:
        return state.parser_cache[cache_key]

    expressions = get_persona_expressions(cache_key)
    parser = EmotionParser(persona_expressions=expressions)
    state.parser_cache[cache_key] = parser
    return parser


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用啟動與關閉"""
    logger.info("🚀 SIRO Bridge 啟動中...")

    # 初始化 Hermes client
    # timeout 從 SIRO_PRIMARY_LLM_TIMEOUT_SEC 讀（hermes_client.py 內部 fallback 到 600s）
    state.hermes = HermesClient(
        binary_path=os.environ.get("HERMES_BIN_PATH"),
    )
    if state.hermes.is_available():
        version = state.hermes.get_version()
        logger.info(f"✓ Hermes 可用: {version}")
    else:
        logger.warning("⚠ Hermes 不可用，請確認有跑過 agent/install.sh")

    # 印出 LLM 路由設定 — 方便開機時一眼看到現在走哪台、timeout 多少、
    # fallback 是哪台。Phase 1.5 驗收/排錯都靠這段日誌。
    primary_model = os.environ.get("SIRO_PRIMARY_LLM_MODEL", "(未設定，Hermes 走預設)")
    primary_base = os.environ.get("SIRO_PRIMARY_LLM_BASE_URL", "(未設定)")
    primary_provider = os.environ.get("SIRO_PRIMARY_LLM_PROVIDER", "(未設定)")
    api_key_set = bool(os.environ.get("SIRO_PRIMARY_LLM_API_KEY", ""))

    logger.info("─" * 50)
    logger.info(f"  Primary LLM provider : {primary_provider}")
    logger.info(f"  Primary LLM model   : {primary_model}")
    logger.info(f"  Primary LLM base_url: {primary_base}")
    logger.info(f"  Primary API key 設定: {'✓' if api_key_set else '✗ 缺少 SIRO_PRIMARY_LLM_API_KEY'}")
    logger.info(f"  Primary timeout      : {state.hermes.timeout}s")

    # 初始化 fallback LLM（本地 Ollama）
    state.ollama = OllamaClient()
    if state.ollama.is_available():
        logger.info(f"  Fallback LLM (Ollama): ✓ {state.ollama.model} @ {state.ollama.base_url}")
    else:
        logger.warning(
            f"  Fallback LLM (Ollama): ✗ {state.ollama.model} @ {state.ollama.base_url} "
            f"（Ollama 沒跑 → timeout 時會直接走 static persona 文字）"
        )
    logger.info("─" * 50)

    # 初始化情緒解析器
    state.parser = EmotionParser()
    logger.info("✓ 情緒解析器就緒")

    # v0.2+：印出已註冊的路由（除錯用）
    routes = sorted({f"{r.methods} {r.path}" if hasattr(r, 'methods') else f"  {r.path}"
                     for r in app.routes if hasattr(r, 'path')})
    logger.info(f"  已註冊路由 ({len(routes)} 條):")
    for r in routes:
        logger.info(f"    {r}")

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

async def _make_fallback_response(
    user_id: str,
    session_id: str,
    category: str,
    persona_name: str,
    error_detail: str = "",
    user_message: str = "",
) -> ChatResponse:
    """
    產生降級回應 — Hermes 不可用 / 失敗時用。

    兩段式降級（GAPS.md #4 + #9）：
    1. Soft fallback：試本地 Ollama llama3.2:3b（真的 LLM 回應，只是比較笨）
    2. Hard fallback：拿 persona 靜態 fallback pool 文字 + thinking 表情

    兩段都回 200 — 讓 Unity Mao 看起來「在想」而不是「斷線」。

    Args:
        user_message: 使用者原文（給 soft fallback 讓 Ollama 看得懂問題）

    Note: async 因為 Ollama HTTP 呼叫用 to_thread 跑，避免 block event loop。
    """
    if error_detail:
        logger.warning(f"降級回應觸發 [{category}]: {error_detail}")

    # ---- 1. Soft fallback：試本地 Ollama（async 不卡 event loop）----
    ollama_text, ollama_emotion = await _try_ollama_fallback_async(
        user_message=user_message,
        persona_name=persona_name,
    )
    if ollama_text is not None:
        # Ollama 給了真的回應 → 走正常 emotion parse（用 persona parser）
        persona_parser = _build_parser_for_persona(persona_name)
        clean_text, emotion, intensity = persona_parser.parse(
            ollama_text, user_input=user_message
        )
        live2d = persona_parser.to_live2d_signal(emotion, intensity)
        logger.info(
            f"↩ soft fallback (Ollama) user={user_message[:40]!r} → "
            f"llm={ollama_text[:80]!r} → emotion={emotion.value}"
        )
        return ChatResponse(
            text=clean_text,
            emotion=emotion,
            intensity=intensity,
            live2d=live2d,
            session_id=session_id,
            user_id=user_id,
            raw_response=ollama_text,
        )

    # ---- 2. Hard fallback：persona 靜態文字 + thinking 表情 ----
    fallback_text = get_fallback_response(category, persona_name=persona_name)
    intensity = 0.5
    persona_parser = _build_parser_for_persona(persona_name)
    live2d = persona_parser.to_live2d_signal(Emotion.THINKING, intensity)

    logger.info(
        f"↩ hard fallback (static) user={user_message[:40]!r} → text={fallback_text!r}"
    )
    return ChatResponse(
        text=fallback_text,
        emotion=Emotion.THINKING,
        intensity=intensity,
        live2d=live2d,
        session_id=session_id,
        user_id=user_id,
        raw_response=f"[bridge hard fallback: {category}] {error_detail}",
    )


def _try_ollama_fallback(
    user_message: str,
    persona_name: str,
) -> tuple[Optional[str], Optional[Emotion]]:
    """
    嘗試用本地 Ollama 拿一條回應（同步版，呼叫端記得包 to_thread）。

    Returns:
        (text, None) — Ollama 成功，回 text 給 caller
        (None, None) — Ollama 不可用 / 失敗 / 沒訊息，caller 走 hard fallback
    """
    if state.ollama is None or not state.ollama.is_available():
        return None, None

    if not user_message.strip():
        return None, None

    try:
        system_prompt = get_personality(persona_name)
        result = state.ollama.chat(
            message=user_message,
            system_prompt=system_prompt,
        )
    except Exception as e:
        logger.warning(f"Ollama fallback 例外: {e}")
        return None, None

    if not result.success or not result.output:
        logger.warning(f"Ollama fallback 失敗: {result.error}")
        return None, None

    return result.output, None


async def _try_ollama_fallback_async(
    user_message: str,
    persona_name: str,
) -> tuple[Optional[str], Optional[Emotion]]:
    """async 版 _try_ollama_fallback — Ollama HTTP call 用 to_thread 避免 block event loop"""
    if state.ollama is None or not state.ollama.is_available():
        return None, None

    if not user_message.strip():
        return None, None

    try:
        # 跑在 thread pool 裡 — Ollama HTTP 請求不會卡 event loop
        text, _ = await asyncio.to_thread(
            _try_ollama_fallback, user_message, persona_name
        )
        return text, None
    except Exception as e:
        logger.warning(f"Ollama async fallback 例外: {e}")
        return None, None


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


@app.get("/personas", response_model=PersonaListResponse)
async def get_personas() -> PersonaListResponse:
    """列出所有可用的 persona（v1 多角色切換用）

    Unity persona selector 會打這 endpoint 拿清單給 UI dropdown。
    """
    personas_data = list_personas()
    summaries = [
        PersonaSummary(
            id=p["id"],
            name=p["name"],
            version=p.get("version"),
            language=p.get("language"),
            model_type=p.get("model_type"),
            prefab_path=p.get("prefab_path"),
        )
        for p in personas_data
    ]
    return PersonaListResponse(personas=summaries, current_default="siro-default")


@app.get("/personas/{persona_id}", response_model=PersonaDetail)
async def get_persona_detail(persona_id: str) -> PersonaDetail:
    """拿單一 persona 完整資料（含 Live2D 設定、quirks）

    Unity 在切換角色時會打這 endpoint 拿：
    - prefab_path：要動態載入的 prefab
    - expressions：emotion → Live2D signal 對照
    - quirks：角色特殊設定（眼動 hack 之類）
    """
    persona = load_persona(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"persona '{persona_id}' not found")

    model_meta = get_persona_model_meta(persona_id)
    quirks = get_persona_quirks(persona_id)
    expressions = get_persona_expressions(persona_id)

    return PersonaDetail(
        id=persona.get("id", persona_id),
        name=persona.get("name", persona_id),
        version=persona.get("version"),
        language=persona.get("language"),
        model_type=model_meta.get("type"),
        prefab_path=model_meta.get("prefab_path"),
        hide_eye_on_expressions=quirks.get("hide_eye_on_expressions", []),
        eye_drawable_indices=quirks.get("eye_drawable_indices", []),
        expressions=expressions,
        idle_motions=persona.get("idle_motions", []),
        idle_interval_seconds=persona.get("idle_interval_seconds", [15, 45]),
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

    降級策略（GAPS.md #4 + #9）：
    - Bridge 內部沒初始化 → 503（系統 bug，明確報錯）
    - Hermes 不可用 → 200 + 降級回應（Mao 切 thinking 表情、講「嗯..."）
    - Hermes 失敗 → 200 + 降級回應（同上，但不會破壞使用者體驗）
    """
    if not state.hermes or not state.parser:
        raise HTTPException(status_code=503, detail="Bridge 尚未初始化")

    persona_name = req.personality or "default"
    session_id = req.session_id or f"{req.user_id}-{uuid.uuid4().hex[:8]}"

    # v1.1 timing log：分段計時方便看哪裡慢
    import time
    t_total_start = time.time()
    t_parser = 0.0
    t_hermes = 0.0
    t_parse = 0.0

    # v0.2+：每個 request 依 persona 拿專屬的 EmotionParser（從 persona 讀 expressions）
    t0 = time.time()
    parser = _build_parser_for_persona(persona_name)
    t_parser = time.time() - t0

    if not state.hermes.is_available():
        return await _make_fallback_response(
            user_id=req.user_id,
            session_id=session_id,
            category="error",
            persona_name=persona_name,
            error_detail="Hermes CLI not available",
            user_message=req.message,
        )

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

    system_prompt = get_personality(persona_name)

    # 呼叫 Hermes（用 to_thread 把 subprocess 跑在 thread pool，
    # 這樣 FastAPI event loop 不會被 3-10 秒的 hermes call 卡住）
    result = await asyncio.to_thread(
        state.hermes.chat,
        message=user_message_with_context,
        system_prompt=system_prompt,
    )

    if not result.success:
        # 降級而非 502：使用者看到「嗯..."而不是「Internal Server Error」
        return await _make_fallback_response(
            user_id=req.user_id,
            session_id=session_id,
            category="error",
            persona_name=persona_name,
            error_detail=f"Hermes failed: {result.error}",
            user_message=req.message,
        )

    t_hermes = time.time() - t_parser + t0  # 含前面的 parser 時間
    t_hermes_only = time.time() - t0 - t_parser  # 純 hermes

    # 解析情緒（用 persona 專屬 parser，user_input 對明確情緒詞做強信號 override）
    t1 = time.time()
    clean_text, emotion, intensity = parser.parse(
        result.output, user_input=req.message
    )
    live2d_signal = parser.to_live2d_signal(emotion, intensity)
    t_parse = time.time() - t1
    logger.info(
        f"💬 user={req.message[:40]!r} → llm={result.output[:80]!r} → emotion={emotion.value} "
        f"[⏱ parser={t_parser*1000:.0f}ms hermes={t_hermes_only*1000:.0f}ms parse={t_parse*1000:.0f}ms total={(time.time()-t_total_start)*1000:.0f}ms]"
    )

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

    降級策略（GAPS.md #4 + #9）：
    - Bridge 內部沒初始化 → 關連線（這是 bug）
    - Hermes 不可用 → 維持連線，每次 chat 都回 fallback response（Mao 切 thinking）
    - Hermes chat 失敗 → 同上
    """
    await websocket.accept()
    logger.info(f"🔌 WebSocket 連線: {websocket.client}")

    if not state.hermes or not state.parser:
        await websocket.send_json({"type": "error", "detail": "Bridge 尚未初始化"})
        await websocket.close()
        return

    # 注意：is_available() false 不關連線。讓 Unity 維持連線、後續每次
    # chat 走 fallback。這樣 Mao 看起來「在但有點傻」而非「失蹤」。
    if not state.hermes.is_available():
        logger.warning("⚠ Hermes 不可用，但維持 WebSocket 連線、走 fallback response")

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

                # v0.2+：用 persona 專屬 parser 解析情緒
                parser = _build_parser_for_persona(personality)

                session_id = f"{user_id}-ws"

                # 降級路徑：Hermes 不可用就直接走 fallback，省下 subprocess 開銷
                if not state.hermes.is_available():
                    fallback = await _make_fallback_response(
                        user_id=user_id,
                        session_id=session_id,
                        category="disconnected",
                        persona_name=personality,
                        error_detail="Hermes not available",
                        user_message=message,
                    )
                    await websocket.send_json({
                        "type": "response",
                        "text": fallback.text,
                        "emotion": fallback.emotion.value,
                        "intensity": fallback.intensity,
                        "live2d": fallback.live2d.model_dump(),
                        "session_id": fallback.session_id,
                    })
                    continue

                # 跑對話
                history = state.sessions.get(session_id, [])
                history_context = ""
                if history:
                    history_context = "\n\n最近的對話：\n" + "\n".join(
                        f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
                    )

                prompt_message = f"{history_context}\n\n使用者: {message}" if history_context else message
                system_prompt = get_personality(personality)

                # to_thread 把 hermes subprocess 跑在 thread pool，
                # 這樣 FastAPI event loop 不被卡
                result = await asyncio.to_thread(
                    state.hermes.chat,
                    message=prompt_message,
                    system_prompt=system_prompt,
                )

                if not result.success:
                    # 降級而非 error event：Mao 切 thinking、講「嗯..."
                    fallback = await _make_fallback_response(
                        user_id=user_id,
                        session_id=session_id,
                        category="error",
                        persona_name=personality,
                        error_detail=f"Hermes failed: {result.error}",
                        user_message=message,
                    )
                    await websocket.send_json({
                        "type": "response",
                        "text": fallback.text,
                        "emotion": fallback.emotion.value,
                        "intensity": fallback.intensity,
                        "live2d": fallback.live2d.model_dump(),
                        "session_id": fallback.session_id,
                    })
                    continue

                clean_text, emotion, intensity = parser.parse(
                    result.output, user_input=message
                )
                live2d_signal = parser.to_live2d_signal(emotion, intensity)
                logger.info(
                    f"💬 user={message[:40]!r} → llm={result.output[:80]!r} → emotion={emotion.value}"
                )

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
