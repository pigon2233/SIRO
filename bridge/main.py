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
import time
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
from .agent_os import AgentOS, Event  # v0.2+ 後台作業系統
from .tasks import create_llm_reply_task  # v0.3 AgentOS 接 endpoint
from .tasks import get_task, register_builtin_tasks  # v1.2 SendTask infra
from .telegram_bot import TelegramBot, create_telegram_bot_from_env  # v1.0 Telegram 整合
from .models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    Live2DSignal,
    Emotion,
    PersonaSummary,
    PersonaDetail,
    PersonaListResponse,
    VisualSettings,
)
from .prompts import (
    get_personality,
    get_fallback_response,
    get_persona_expressions,
    get_persona_model_meta,
    get_persona_quirks,
    get_persona_visual,
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
    """Bridge 全域狀態

    v0.2+ 加 AgentOS 變成「後台作業系統」架構
    詳見 docs/AGENT_OS.md
    """

    def __init__(self):
        self.hermes: HermesClient | None = None
        self.ollama: OllamaClient | None = None
        self.parser: EmotionParser | None = None
        self.sessions: Dict[str, list[dict]] = {}  # session_id -> 對話歷史
        # v0.2+：per-persona parser cache — 同一 persona 重複 request 不重建 parser
        # EmotionParser.__init__ 雖然便宜，但 jieba 詞庫補強在第一次會跑 16 次 add_word
        # cache 起來省下這些 + dict copy
        self.parser_cache: Dict[str, EmotionParser] = {}
        # v0.2+：AgentOS — task queue + event bus + worker pool
        # bridge 是「後台作業系統」: 跟 Mao 對話同時可以跑排程、Telegram、stock query
        self.agent_os = None  # type: Optional[AgentOS]  # 在 lifespan 內啟動
        # v0.4：/chat /ws 是否走 AgentOS task queue 的開關
        # 預設 true（v0.3 觀察穩定後 v0.4 翻預設）
        # 設 false 可降回 v0.2 sync 路徑（向後相容、給不想要 AgentOS 的人逃生）
        # v0.3 之前是預設 false — 188 既有測試在 v0.3 用 enable_agent_os fixture 強制 true
        # v0.4 翻預設後那些 fixture 變成冗餘、但保留不破壞測試可讀性
        self.use_agent_os = os.environ.get("SIRO_USE_AGENT_OS", "true").lower() == "true"
        # v0.3.1：/chat /ws 是否走 MiniMax-M3 SSE streaming（STRATEGIC_NOTES Q2 選項 B）
        # 預設 false（保持 v0.2 sync、165 既有測試不動）
        # 設 true 後 /ws 推 {"type":"delta", "text":"..."} 增量訊息、
        # 讓 Unity 端可以邊收邊 render（v1+ Unity 端要改）
        # /chat HTTP 端點不影響 API 形狀（仍回完整 ChatResponse）
        self.use_streaming = os.environ.get("SIRO_STREAMING", "false").lower() == "true"
        # MiniMax SSE client（跟 hermes 共用 env vars）
        from .minimax_streaming_client import MiniMaxStreamingClient
        self.streaming_client = MiniMaxStreamingClient()
        # v1.5+：tool calling 路徑
        # true → /ws chat 走 chat_stream_with_tools、LLM 用 native tool_use 選 emotion
        # false → 走原本 regex parse [emotion:xxx] 文字
        # 注意：tool calling 路徑會自動啟用（前提是 use_streaming 也是 true）
        self.use_tool_calling = os.environ.get("SIRO_USE_TOOL_CALLING", "true").lower() == "true"
        # v0.2+：sessions_lock 保護多 thread / 多 request 並行讀寫
        # 雖然單 process + asyncio 已經序列化大部分 access，但
        # 1. tasks 在 worker thread pool（to_thread）執行
        # 2. 之後 v1+ 多觸發源（Telegram / schedule）也會同時寫
        # 用 RLock 支援 nested lock
        import threading
        self.sessions_lock = threading.RLock()
        # v1.2+：SendTask state（mood.set / motion.play / persona.switch 寫進來）
        # current_mood: {user_id: {emotion, intensity, set_at}}
        # last_motion: list of recent motion 觸發記錄（給 debug / 監控用）
        # active_persona: 當前 Unity active 的 persona（persona.switch 更新）
        self.current_mood: dict = {}
        self.last_motion: list = []
        self.active_persona: str = "siro-default"
        # v1.0+：Telegram bot（polling 模式、從 TELEGRAM_BOT_TOKEN env 啟動）
        self.telegram_bot: Optional[TelegramBot] = None


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

    # v1.1：預先 warm up jieba — 第一次 chat 不會被 jieba 字典載入（~1.5s）拖慢
    # 用一個假訊號跑一次 parse() 把 jieba + add_word 暖開
    import time
    t_jieba = time.time()
    try:
        _, _, _ = state.parser.parse("暖機測試 hello world", user_input="暖機")
        logger.info(f"✓ 情緒解析器就緒（jieba 暖機 { (time.time()-t_jieba)*1000:.0f}ms）")
    except Exception as e:
        logger.warning(f"✓ 情緒解析器就緒（jieba 暖機失敗: {e}）")

    # v0.2+：印出已註冊的路由（除錯用）
    routes = sorted({f"{r.methods} {r.path}" if hasattr(r, 'methods') else f"  {r.path}"
                     for r in app.routes if hasattr(r, 'path')})
    logger.info(f"  已註冊路由 ({len(routes)} 條):")
    for r in routes:
        logger.info(f"    {r}")

    # v0.2+：啟動 AgentOS — 後台作業系統
    # worker pool 預設 3 個，可以並行跑多個 LLM / Telegram / stock query
    state.agent_os = AgentOS()
    await state.agent_os.start(num_workers=3)
    logger.info("  AgentOS 啟動（3 個 worker，task queue + event bus 就緒）")
    logger.info(f"  /chat 走 AgentOS: {state.use_agent_os}（v0.4 預設 true、SIRO_USE_AGENT_OS=false 可降回 v0.2 sync）")
    logger.info(
        f"  /ws 走 SSE streaming: {state.use_streaming}（SIRO_STREAMING env 控制）"
    )
    if state.use_streaming:
        logger.info(
            f"  MiniMaxStreamingClient is_available: {state.streaming_client.is_available}"
        )
    logger.info(
        f"  /ws LLM tool calling: {state.use_tool_calling}（v1.5+、SIRO_USE_TOOL_CALLING=false 可降回 regex parse）"
    )

    # v1.2+：註冊 SendTask 內建 task handlers
    # mood.set / motion.play / persona.switch / chat.say / chat.summon
    register_builtin_tasks()
    from .tasks import list_tasks as _list_tasks
    logger.info(f"  SendTask 已註冊 {len(_list_tasks())} 個 built-in：{_list_tasks()}")

    # v1.2+：背景 warm-up LLM（讓第一個 user chat 不用等 cold start）
    # 不 block lifespan — 丟背景 task 跑、bridge 立刻接受 request
    # 第一次 LLM call 通常 5-8s（MiniMax cold connect + TTFT）、
    # warm-up 跑完後 user 第一個 chat 只要 3-5s
    # 環境變數 SIRO_LLM_WARMUP=false 可關
    if os.environ.get("SIRO_LLM_WARMUP", "true").lower() == "true":
        asyncio.create_task(_warmup_llm())

    # v1.0+：Telegram bot 整合（polling 模式）
    # 沒設 TELEGRAM_BOT_TOKEN 就跳過
    state.telegram_bot = create_telegram_bot_from_env(state)
    if state.telegram_bot:
        try:
            await state.telegram_bot.start()
            logger.info("  Telegram bot 已啟動、polling 開始")
        except Exception as e:
            logger.error(f"  Telegram bot 啟動失敗: {e}")
            state.telegram_bot = None
    else:
        logger.info("  Telegram bot: 未設 TELEGRAM_BOT_TOKEN、跳過")

    yield

    # 關閉
    if state.telegram_bot:
        await state.telegram_bot.stop()
    if state.agent_os:
        await state.agent_os.stop()
    logger.info("🛑 SIRO Bridge 關閉")


# ==================== v1.2+ LLM warm-up helper ====================

async def _warmup_llm() -> None:
    """
    bridge 啟動後背景 warm-up LLM — 讓第一個 user chat 不用等 cold start

    流程：
    1. sleep 2s（讓 bridge 開始接 request、不要擋 startup）
    2. 用 hermes.chat("hi", "") 丟個小 prompt
       → 第一次會 cold connect MiniMax API（5-8s）
       → 連線 + TLS + 認證都建立好
       → 結果丟掉（warm-up 不在意內容）
    3. 如果 streaming client 也有、順便暖 SSE 連線

    失敗沒關係、log warning、user 第一個 chat 還是有 cold start
    （只是沒有 warm-up 加速、不是壞掉）
    """
    import time
    await asyncio.sleep(2)
    t0 = time.time()
    logger.info("[warmup] 開始 LLM warm-up...")

    # 1. hermes warm-up
    if state.hermes and state.hermes.is_available():
        try:
            await asyncio.to_thread(
                state.hermes.chat,
                message="hi",
                system_prompt="",
            )
            logger.info(
                f"[warmup] hermes 連線暖好 ({int((time.time()-t0)*1000)}ms)"
            )
        except Exception as e:
            logger.warning(f"[warmup] hermes warm-up 失敗（user 第一個 chat 還是 cold start）: {e}")
    else:
        logger.info("[warmup] hermes 不可用、跳過 hermes warm-up")

    # 2. SSE streaming client warm-up（如果開啟的話）
    if state.use_streaming and state.streaming_client.is_available:
        try:
            result = await state.streaming_client.chat_collect("hi", system_prompt="")
            # MiniMaxStreamingResult 是 dataclass 不是 dict、用 .text
            text_len = len(result.text) if hasattr(result, "text") else 0
            logger.info(
                f"[warmup] MiniMax SSE 連線暖好 ({int((time.time()-t0)*1000)}ms, "
                f"回應 {text_len} 字)"
            )
        except Exception as e:
            logger.warning(f"[warmup] SSE warm-up 失敗: {e}")

    logger.info(
        f"[warmup] 完成、總耗時 {int((time.time()-t0)*1000)}ms。"
        f"user 第一個 chat 會比較快。"
    )


# ==================== v1.2 SendTask helper ====================

async def _handle_sendtask(websocket: WebSocket, data: dict) -> None:
    """
    v1.2 SendTask handler — 在 WS 收到 {"type": "task", ...} 時呼叫

    流程：
    1. 驗 task_id 格式（client 應傳 UUID4 hex[:8]）
    2. 查 registry、有 → 推 task_ack；無 → 推 task_failed（error: unknown task）
    3. 用 asyncio.create_task 跑 handler（不卡 WS 接收 loop）
    4. 跑完推 task_result 或 task_failed

    為什麼用 create_task 不直接 await：
    - WS 接收 loop 不能被慢 task 卡住（要能繼續收 ping、其他 chat）
    - 規格 §1：handler 簽名 async (args, ctx) -> result
    - inline 跑是 v1.2 簡化版：v1.5+ 慢 task 走 AgentOS queue（持久化 + worker pool）
    """
    task_id = data.get("task_id", "")
    name = data.get("name", "")
    args = data.get("args", {})
    user_id = data.get("user_id", "default")

    # task_id 驗證（8 字 hex = UUID4 hex[:8] 格式）
    if not task_id or not isinstance(task_id, str) or len(task_id) != 8:
        await websocket.send_json({
            "type": "error",
            "detail": f"task 訊息缺 task_id 或格式錯（要 8 字 hex）：{task_id!r}",
        })
        return

    # 查 handler
    handler = get_task(name)
    if handler is None:
        from .tasks import list_tasks as _list
        await websocket.send_json({
            "type": "task_failed",
            "task_id": task_id,
            "error": f"unknown task: {name!r}（available: {_list()})",
        })
        logger.warning(f"[SendTask] 未知 task: {name!r}（task_id={task_id}）")
        return

    # 推 ack
    await websocket.send_json({
        "type": "task_ack",
        "task_id": task_id,
        "status": "accepted",
    })

    # 背景跑 handler — ctx 包含 handler 可能用到的一切
    # （state, user_id, task_id, websocket — 給 mood.set 推 response 給 Unity 用）
    ctx = {
        "state": state,
        "user_id": user_id,
        "task_id": task_id,
        "websocket": websocket,
    }
    logger.info(f"[SendTask] 接 task: {name} args={args} (task_id={task_id})")

    async def _run_and_reply():
        try:
            result = await handler(args, ctx)
            await websocket.send_json({
                "type": "task_result",
                "task_id": task_id,
                "result": result,
            })
            logger.info(f"[SendTask] task 完成: {name} (task_id={task_id})")
        except Exception as e:
            logger.exception(f"[SendTask] task 失敗: {name} (task_id={task_id}): {e}")
            try:
                await websocket.send_json({
                    "type": "task_failed",
                    "task_id": task_id,
                    "error": f"{type(e).__name__}: {e}",
                })
            except Exception:
                # WS 可能已斷線，silently ignore
                pass

    asyncio.create_task(_run_and_reply())


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
    visual_raw = get_persona_visual(persona_id)

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
        visual=VisualSettings(**visual_raw),
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

    # v1.1+：分段計時診斷 — 拆開每段看哪裡慢
    # ⚠️ 60s 瓶頸診斷專用：把 is_available / history / hermes_chat / parse 拆開 log
    import time
    t_total_start = time.time()

    # 段 1: 拿 persona 專屬 parser
    t0 = time.time()
    parser = _build_parser_for_persona(persona_name)
    t_parser = time.time() - t0

    # 段 2: hermes is_available — 改用 asyncio.to_thread 跑 subprocess
    # 否則會卡 event loop 最多 10s、期間其他 SendTask（mood.set / motion.play
    # 點 Mao）也跟著被卡到 timeout。5s TTL cache 還在、cache miss 才真的問 hermes。
    t0 = time.time()
    if not await asyncio.to_thread(state.hermes.is_available):
        t_is_avail = time.time() - t0
        logger.warning(
            f"⏱ [chat] 段 2 is_available={t_is_avail*1000:.0f}ms (false) → fallback"
        )
        return await _make_fallback_response(
            user_id=req.user_id,
            session_id=session_id,
            category="error",
            persona_name=persona_name,
            error_detail="Hermes CLI not available",
            user_message=req.message,
        )
    t_is_avail = time.time() - t0

    # 載入對話歷史（簡化版：塞進 prompt 上下文）
    history = state.sessions.get(session_id, [])
    history_context = ""
    if history:
        history_context = "\n\n最近的對話：\n" + "\n".join(
            f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
        )

    # 段 3: 組 prompt（history build + 拼裝，純記憶體操作應該 < 1ms）
    t0 = time.time()
    # 載入對話歷史
    history = state.sessions.get(session_id, [])
    history_context = ""
    if history:
        history_context = "\n\n最近的對話：\n" + "\n".join(
            f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
        )

    user_message_with_context = req.message
    if history_context:
        user_message_with_context = f"{history_context}\n\n使用者: {req.message}"

    system_prompt = get_personality(persona_name)
    t_history = time.time() - t0

    # 段 4: 呼叫 LLM — v0.3 兩條路徑
    #   A. SIRO_USE_AGENT_OS=true → enqueue AgentOS task，await wait_for_task()
    #   B. false (預設) → 直接 asyncio.to_thread(state.hermes.chat) 走 v0.2 路徑
    t0 = time.time()
    if state.use_agent_os and state.agent_os:
        # v0.3 AgentOS 路徑：enqueue task + 等 event bus
        # llm_reply_task 已經做了 history + parse + live2d signal，
        # /chat 這邊只負責「收結果 + 組 ChatResponse」
        task = create_llm_reply_task(
            state=state,
            user_id=req.user_id,
            message=req.message,
            persona_name=persona_name,
            session_id=session_id,
        )
        state.agent_os.enqueue(task)
        logger.info(f"⏱ [chat] enqueue task id={task.id} → 走 AgentOS")
        agent_result = await state.agent_os.wait_for_task(
            "llm.reply", task.id, timeout=600.0,
        )
        t_hermes = time.time() - t0
        if agent_result is None:
            return await _make_fallback_response(
                user_id=req.user_id,
                session_id=session_id,
                category="error",
                persona_name=persona_name,
                error_detail="LLM timeout via AgentOS",
                user_message=req.message,
            )
        if "error" in agent_result:
            return await _make_fallback_response(
                user_id=req.user_id,
                session_id=session_id,
                category="error",
                persona_name=persona_name,
                error_detail=agent_result["error"],
                user_message=req.message,
            )
        # 成功 — task 已經做完所有事（包括 history 寫入、parse、live2d signal），
        # 結果在 agent_result["result"] 內（_execute_task 把 llm_reply_task 的 return 包成 "result"）
        result = agent_result["result"]
        t1 = time.time()
        chat_response = ChatResponse(
            text=result["text"],
            emotion=Emotion(result["emotion"]),
            intensity=result["intensity"],
            live2d=Live2DSignal(**result["live2d"]),
            session_id=result["session_id"],
            user_id=req.user_id,
            raw_response=result.get("raw_response"),
        )
        t_parse = time.time() - t1
        logger.info(
            f"💬 user={req.message[:40]!r} → llm={result.get('text','')[:80]!r} → emotion={result['emotion']} "
            f"[⏱分段: via=AgentOS parser={t_parser*1000:.0f}ms is_avail={t_is_avail*1000:.0f}ms "
            f"history={t_history*1000:.0f}ms task_in_queue={t_hermes*1000:.0f}ms parse={t_parse*1000:.0f}ms "
            f"total={(time.time()-t_total_start)*1000:.0f}ms]"
        )
        # 段 6 之前：寫歷史（v0.2+ RLock 保護）
        # 注意：llm_reply_task 已經自己寫過 history，這裡要重複嗎？檢查 — 不重複，
        # task 內的 history 寫入是用同個 session_id 跟同一個 state.sessions_lock，
        # 再寫一次會 duplicate。**故意跳過**。
        return chat_response
    else:
        # v0.2 sync 路徑（預設）
        result = await asyncio.to_thread(
            state.hermes.chat,
            message=user_message_with_context,
            system_prompt=system_prompt,
        )
        t_hermes = time.time() - t0

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

    # 段 5: 解析情緒 + 組 Live2D signal
    t0 = time.time()
    clean_text, emotion, intensity = parser.parse(
        result.output, user_input=req.message
    )
    live2d_signal = parser.to_live2d_signal(emotion, intensity)
    t_parse = time.time() - t0

    # 完整分段計時 log — 一眼看出 60s 在哪一段
    t_total = (time.time() - t_total_start) * 1000
    logger.info(
        f"💬 user={req.message[:40]!r} → llm={result.output[:80]!r} → emotion={emotion.value}\n"
        f"   ⏱分段: parser={t_parser*1000:.0f}ms is_avail={t_is_avail*1000:.0f}ms "
        f"history={t_history*1000:.0f}ms hermes_chat={t_hermes*1000:.0f}ms parse={t_parse*1000:.0f}ms "
        f"total={t_total:.0f}ms"
    )

    # 記錄歷史（v0.2+：用 RLock 保護，雖 asyncio 序列化但 to_thread 可能並行）
    with state.sessions_lock:
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


def _log_async_task_exception(task: asyncio.Task) -> None:
    """背景 task 的 exception sink — 給 asyncio.create_task 後用 add_done_callback 接

    為什麼需要：
    asyncio.create_task spawn 的 coroutine 如果噴 exception、沒人 await、
    asyncio 會在 task GC 時 log "Task exception was never retrieved"（ERROR 等級）。
    這在 production 環境會被誤判成「有 bug」、其實只是預期的錯誤場景。

    典型場景：_process_ws_chat 背景跑 5-30s LLM call、Unity 中途斷線、
    chat 跑完要 send_json 才發現 WS 已關、噴 RuntimeError 是預期的。

    行為：
    - task 正常完成（沒 exception）→ no-op、安靜
    - task 噴 exception → log warning（不是 error）+ 保留 full traceback 給 debug
    - 常見的「WS 已關」RuntimeError 降為 info（避免 log 噪音）
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    # 常見預期錯誤：Unity 斷線後 send_json 噴的 RuntimeError、WS close 後 receive
    if isinstance(exc, RuntimeError) and "websocket" in str(exc).lower():
        logger.info(f"[ws] 背景 task 預期結束（WS 已關）: {type(exc).__name__}: {exc}")
        return
    if isinstance(exc, WebSocketDisconnect):
        logger.info(f"[ws] 背景 task 預期結束（client 斷線）: {exc}")
        return
    # 其他 exception 是真 bug、log warning + traceback
    logger.warning(f"[ws] 背景 task 噴未預期 exception: {type(exc).__name__}: {exc}")
    logger.warning("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


async def _process_ws_chat(websocket: WebSocket, data: dict) -> None:
    """v1.2+ 抽出來 create_task 跑、不卡 receive loop。

    原本 chat 處理（5-30s LLM call）INLINE 在 /ws 的 while loop、
    整段期間不 `await receive_json` 也不 `await send_json`、
    下一個 message（mood.set / motion.play 點 Mao）就卡 OS receive buffer、5s timeout 觸發。

    抽出來後、main loop 立即回到 receive_json 收下一個 message。
    SendTask (mood.set/motion.play) 走 AgentOS.enqueue_fast 立即有反應。

    注意：背景 coroutine 噴 exception 不會被外層 except WebSocketDisconnect 接住、
    呼叫端用 `_log_async_task_exception` 統一吃掉（Unity 中途斷線 → chat 跑完
    才發現 WS 已關 → send_json 噴 RuntimeError 是預期的、log warning 就好）。
    """
    message = data.get("message", "").strip()
    user_id = data.get("user_id", "default")
    personality = data.get("personality", "default")

    if not message:
        await websocket.send_json({"type": "error", "detail": "訊息不能空白"})
        return

    # v0.2+：用 persona 專屬 parser 解析情緒
    # v1.1+：分段計時診斷 60s 瓶頸
    t_ws_total = time.time()
    t0 = time.time()
    parser = _build_parser_for_persona(personality)
    t_parser = time.time() - t0

    session_id = f"{user_id}-ws"

    # is_available() — 改用 to_thread 跑 subprocess、不卡 event loop
    # 不然 SendTask 點 Mao 會被同步 subprocess 卡到 timeout
    t0 = time.time()
    hermes_ok = await asyncio.to_thread(state.hermes.is_available)
    t_is_avail = time.time() - t0

    # 降級路徑：Hermes 不可用就直接走 fallback
    if not hermes_ok:
        logger.warning(
            f"⏱ [ws] 段 is_available={t_is_avail*1000:.0f}ms (false) → fallback"
        )
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
        return

    # v0.3.1 SSE streaming 路徑（STRATEGIC_NOTES Q2 選項 B）：
    #   - SIRO_STREAMING=true → 走 MiniMaxStreamingClient.chat_stream() 收 SSE
    #   - 每收到一個 text chunk 就推 {"type":"delta","text":"..."} 給 Unity
    #   - 收集完所有 chunk 後 parse emotion、推 {"type":"response",...}
    #   - Unity 端目前收到 delta 不 render（v1+ 才接 incremental render）
    #   - 預設 false — 既有測試不動
    t0 = time.time()
    # v1.5+ LLM tool calling 路徑（tool_use API 選 emotion）
    # 跟下面 streaming 流程幾乎一樣、只是用 chat_stream_with_tools 帶 tools 參數、
    # 解析 tool_use event 直接拿 emotion（不用 regex parse [emotion:xxx] 文字）
    if (
        state.use_tool_calling
        and state.use_streaming
        and state.streaming_client.is_available
    ):
        from .tasks.llm_reply_task import create_llm_reply_with_tools_task
        from .tools import get_available_tools

        stream_history = state.sessions.get(session_id, [])
        stream_history_context = ""
        if stream_history:
            stream_history_context = "\n\n最近的對話：\n" + "\n".join(
                f"使用者: {h['user']}\n你: {h['agent']}" for h in stream_history[-5:]
            )
        stream_prompt = f"{stream_history_context}\n\n使用者: {message}" if stream_history_context else message
        stream_system = get_personality(personality)

        logger.info(f"⏱ [ws] 走 MiniMax-M3 SSE streaming + tool calling (v1.5+)")
        t_stream_start = time.time()
        delta_count = 0
        full_text_parts: list[str] = []
        ttft_ms: Optional[int] = None
        tool_use_event = None  # v1.5+ LLM 選 tool 的事件
        try:
            async for event in state.streaming_client.chat_stream_with_tools(
                message=stream_prompt,
                system_prompt=stream_system,
                tools=get_available_tools(),
            ):
                if event.type == "text":
                    if ttft_ms is None:
                        ttft_ms = int((time.time() - t_stream_start) * 1000)
                        logger.info(f"⚡ [ws] TTFT={ttft_ms}ms")
                    delta_count += 1
                    full_text_parts.append(event.text)
                    # 推 delta 給 Unity
                    await websocket.send_json({
                        "type": "delta",
                        "text": event.text,
                    })
                elif event.type == "tool_use":
                    # v1.5+ LLM 選 tool（v1.5 一次只一個、記第一個）
                    if tool_use_event is None:
                        tool_use_event = event
                        logger.info(
                            f"⏱ [ws] LLM 選 tool: {event.name} input={event.input}"
                        )
        except Exception as e:
            logger.error(f"[ws] tool calling streaming 失敗: {e}")
            fallback = await _make_fallback_response(
                user_id=user_id,
                session_id=session_id,
                category="error",
                persona_name=personality,
                error_detail=f"tool calling error: {e}",
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
            return

        full_text = "".join(full_text_parts)
        t_stream_total = int((time.time() - t_stream_start) * 1000)
        logger.info(
            f"💬 [ws-tool-calling] user={message[:40]!r} → llm={full_text[:80]!r} "
            f"[⚡ TTFT={ttft_ms}ms total={t_stream_total}ms deltas={delta_count} tool_used={tool_use_event is not None}]"
        )

        # 解析情緒：tool_use 優先、否則 regex parse
        if tool_use_event and tool_use_event.name == "set_mood":
            emotion_str = tool_use_event.input.get("emotion", "neutral")
            intensity = float(tool_use_event.input.get("intensity", 0.7))
            logger.info(f"⏱ [ws] tool_use 選 emotion={emotion_str} intensity={intensity}")
        else:
            # Fallback：regex parse [emotion:xxx] 文字
            clean_text, emotion, intensity = parser.parse(full_text, user_input=message)
            emotion_str = emotion.value
            logger.info(f"⏱ [ws] 沒 tool_use、fallback regex: emotion={emotion_str}")

        try:
            live2d_signal = parser.to_live2d_signal(Emotion(emotion_str), intensity)
        except Exception:
            live2d_signal = parser.to_live2d_signal(Emotion("neutral"), 0.5)
            emotion_str = "neutral"
            intensity = 0.5

        # 寫歷史
        with state.sessions_lock:
            if session_id not in state.sessions:
                state.sessions[session_id] = []
            state.sessions[session_id].append({
                "user": message,
                "agent": full_text,
                "emotion": emotion_str,
            })
            state.sessions[session_id] = state.sessions[session_id][-20:]

        # 推 final response
        await websocket.send_json({
            "type": "response",
            "text": full_text,
            "emotion": emotion_str,
            "intensity": intensity,
            "live2d": live2d_signal.model_dump(),
            "session_id": session_id,
        })
        return

    if state.use_streaming and state.streaming_client.is_available:
        # 自己建 prompt + system（跟 v0.2 sync 路徑同樣邏輯）
        stream_history = state.sessions.get(session_id, [])
        stream_history_context = ""
        if stream_history:
            stream_history_context = "\n\n最近的對話：\n" + "\n".join(
                f"使用者: {h['user']}\n你: {h['agent']}" for h in stream_history[-5:]
            )
        stream_prompt = f"{stream_history_context}\n\n使用者: {message}" if stream_history_context else message
        stream_system = get_personality(personality)

        logger.info(f"⏱ [ws] 走 MiniMax-M3 SSE streaming")
        t_stream_start = time.time()
        delta_count = 0
        full_text_parts: list[str] = []
        ttft_ms: Optional[int] = None
        try:
            async for chunk in state.streaming_client.chat_stream(
                message=stream_prompt,
                system_prompt=stream_system,
            ):
                if ttft_ms is None:
                    ttft_ms = int((time.time() - t_stream_start) * 1000)
                    logger.info(f"⚡ [ws] TTFT={ttft_ms}ms")
                delta_count += 1
                full_text_parts.append(chunk)
                # 推 delta 給 Unity（v1+ 才用、目前客戶端會忽略）
                await websocket.send_json({
                    "type": "delta",
                    "text": chunk,
                })
        except Exception as e:
            logger.error(f"[ws] streaming 失敗: {e}")
            # streaming 失敗 → 走 fallback（跟 sync 路徑的 hermes 失敗同樣處理）
            fallback = await _make_fallback_response(
                user_id=user_id,
                session_id=session_id,
                category="error",
                persona_name=personality,
                error_detail=f"streaming error: {e}",
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
            return

        full_text = "".join(full_text_parts)
        t_stream_total = int((time.time() - t_stream_start) * 1000)
        logger.info(
            f"💬 [ws-streaming] user={message[:40]!r} → llm={full_text[:80]!r} "
            f"[⚡ TTFT={ttft_ms}ms total={t_stream_total}ms deltas={delta_count}]"
        )
        # 解析情緒（跟 sync 路徑一樣用 persona 專屬 parser）
        clean_text, emotion, intensity = parser.parse(
            full_text, user_input=message
        )
        live2d_signal = parser.to_live2d_signal(emotion, intensity)
        # 寫歷史（同樣用 state.sessions_lock）
        with state.sessions_lock:
            if session_id not in state.sessions:
                state.sessions[session_id] = []
            state.sessions[session_id].append({
                "user": message,
                "agent": clean_text,
                "emotion": emotion.value,
            })
            state.sessions[session_id] = state.sessions[session_id][-20:]
        # 推 final response（Unity 端跟 sync 路徑收到的格式一樣）
        await websocket.send_json({
            "type": "response",
            "text": clean_text,
            "emotion": emotion.value,
            "intensity": intensity,
            "live2d": live2d_signal.model_dump(),
            "session_id": session_id,
        })
        return

    # v0.3 段 4 兩條路徑（跟 /chat 對齊）：
    #   A. SIRO_USE_AGENT_OS=true → enqueue AgentOS task，await wait_for_task()
    #   B. false (預設) → 直接 asyncio.to_thread(state.hermes.chat) 走 v0.2 路徑
    t0 = time.time()
    if state.use_agent_os and state.agent_os:
        # v0.3 AgentOS 路徑：/ws 跟 /chat 走同一個 llm_reply_task factory
        task = create_llm_reply_task(
            state=state,
            user_id=user_id,
            message=message,
            persona_name=personality,
            session_id=session_id,
        )
        state.agent_os.enqueue(task)
        logger.info(f"⏱ [ws] enqueue task id={task.id} → 走 AgentOS")
        agent_result = await state.agent_os.wait_for_task(
            "llm.reply", task.id, timeout=600.0,
        )
        t_hermes = time.time() - t0
        if agent_result is None:
            fallback = await _make_fallback_response(
                user_id=user_id,
                session_id=session_id,
                category="error",
                persona_name=personality,
                error_detail="LLM timeout via AgentOS",
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
            return
        if "error" in agent_result:
            fallback = await _make_fallback_response(
                user_id=user_id,
                session_id=session_id,
                category="error",
                persona_name=personality,
                error_detail=agent_result["error"],
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
            return
        # 成功 — task 已經做完 history + parse + live2d signal，
        # 結果在 agent_result["result"] 內
        result = agent_result["result"]
        t_ws_total = (time.time() - t_ws_total) * 1000
        logger.info(
            f"💬 [ws] user={message[:40]!r} → llm={result.get('text','')[:80]!r} → emotion={result['emotion']} "
            f"[⏱分段: via=AgentOS parser={t_parser*1000:.0f}ms is_avail={t_is_avail*1000:.0f}ms "
            f"task_in_queue={t_hermes*1000:.0f}ms total={t_ws_total:.0f}ms]"
        )
        await websocket.send_json({
            "type": "response",
            "text": result["text"],
            "emotion": result["emotion"],
            "intensity": result["intensity"],
            "live2d": result["live2d"],
            "session_id": result["session_id"],
        })
        return

    # 跑對話
    t0 = time.time()
    history = state.sessions.get(session_id, [])
    history_context = ""
    if history:
        history_context = "\n\n最近的對話：\n" + "\n".join(
            f"使用者: {h['user']}\n你: {h['agent']}" for h in history[-5:]
        )
    t_history = time.time() - t0

    prompt_message = f"{history_context}\n\n使用者: {message}" if history_context else message
    system_prompt = get_personality(personality)

    # 段 4: 呼叫 Hermes（to_thread 把 subprocess 跑在 thread pool）
    t0 = time.time()
    result = await asyncio.to_thread(
        state.hermes.chat,
        message=prompt_message,
        system_prompt=system_prompt,
    )
    t_hermes = time.time() - t0

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
        return

    # 段 5: 解析情緒
    t0 = time.time()
    clean_text, emotion, intensity = parser.parse(
        result.output, user_input=message
    )
    live2d_signal = parser.to_live2d_signal(emotion, intensity)
    t_parse = time.time() - t0

    # v1.1+：完整分段計時 log（跟 /chat 對齊）
    t_ws_total = (time.time() - t_ws_total) * 1000
    logger.info(
        f"💬 user={message[:40]!r} → llm={result.output[:80]!r} → emotion={emotion.value}\n"
        f"   ⏱分段: parser={t_parser*1000:.0f}ms is_avail={t_is_avail*1000:.0f}ms "
        f"history={t_history*1000:.0f}ms hermes_chat={t_hermes*1000:.0f}ms parse={t_parse*1000:.0f}ms "
        f"total={t_ws_total:.0f}ms"
    )

    # 記錄歷史（v0.2+：RLock 保護，跟 /chat 一致）
    with state.sessions_lock:
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

    v0.3 細項：opt-in 走 AgentOS
    - SIRO_USE_AGENT_OS=true → /ws 跟 /chat 一樣 enqueue AgentOS task、wait_for_task 拿結果
    - 跟 /chat 共用 `create_llm_reply_task()` factory（無重複）
    - 預設 false（行為跟 v0.2 相同、165+ 既有測試不動）
    - Timeout / failed 都走 fallback response、WS 連線不中斷
    """
    await websocket.accept()
    logger.info(f"🔌 WebSocket 連線: {websocket.client}")

    if not state.hermes or not state.parser:
        await websocket.send_json({"type": "error", "detail": "Bridge 尚未初始化"})
        await websocket.close()
        return

    # 注意：is_available() false 不關連線。讓 Unity 維持連線、後續每次
    # chat 走 fallback。這樣 Mao 看起來「在但有點傻」而非「失蹤」。
    # 改用 to_thread：不卡 event loop、WS 接收 loop 仍能處理 ping/SendTask
    if not await asyncio.to_thread(state.hermes.is_available):
        logger.warning("⚠ Hermes 不可用，但維持 WebSocket 連線、走 fallback response")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "chat":
                # v1.2+ 改：chat 處理整段 create_task 出去跑、不卡 receive loop
                # 原因：chat 走 AgentOS / SSE streaming / hermes LLM call 全是慢任務（5-30s）、
                #       之前 INLINE 在 while loop、整段期間不 await receive_json 也不 await send_json、
                #       下一個 message（mood.set / motion.play 點 Mao）就卡 OS receive buffer、
                #       5s timeout 觸發時 chat 都還沒結束。
                # 解法：chat 整段抽成背景 coroutine、main loop 立即回到 receive_json 收下一個 message。
                # 注意：背景 coroutine 噴 exception 不會被外層 except WebSocketDisconnect 接住、
                #       add_done_callback 統一吃 log warning、避免 asyncio 報 "Task exception was never retrieved"
                #       （常見：Unity 中途斷線、chat 跑完要 send_json 才發現 WS 已關）
                chat_task = asyncio.create_task(_process_ws_chat(websocket, data))
                chat_task.add_done_callback(_log_async_task_exception)
                continue

            elif msg_type == "task":
                # v1.2 SendTask：Unity 主動推 task 進 bridge
                # 規格：docs/AGENT_OS.md v1.2 段
                # 流程：
                #   1. 收 {"type":"task", "task_id":"...", "name":"...", "args":{...}}
                #   2. 查 registry、有 → 推 task_ack；無 → 推 task_failed
                #   3. 跑 handler（inline，asyncio.create_task 不卡 WS 接收 loop）
                #   4. 跑完推 task_result 或 task_failed
                await _handle_sendtask(websocket, data)
                continue

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
