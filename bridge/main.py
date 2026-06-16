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
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

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
from .runtime_client import RuntimeClient, get_runtime_client  # v0.3.0 Phase 3 siro-runtime gRPC client
from .confirmation import ConfirmationBroker  # v1.5+ computer control confirmation broker
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
    TTSRequest,
    TTSResponse,
    TTSVoiceInfo,
    TTSVoicesResponse,
)
from .tts import get_tts_orchestrator  # v1.0 Core Experience Phase 1 — TTS orchestrator
from .prompts import (
    get_personality,
    get_fallback_response,
    get_persona_expressions,
    get_persona_model_meta,
    get_persona_quirks,
    get_persona_visual,
    get_persona_voice,           # v1.0 Core Experience Phase 1
    list_personas,
    load_persona,
)

# 載入 .env（v0.5 抽象層：先試 CWD（dev mode），fallback 到 user_config_dir/.env）
_cwd_env = Path.cwd() / ".env"
if _cwd_env.exists():
    load_dotenv(_cwd_env)
else:
    from .platform.paths import user_config_dir
    _user_env = user_config_dir(ensure=False) / ".env"
    if _user_env.exists():
        load_dotenv(_user_env)
    else:
        # 兩個都沒有也不 raise — 跟原本 load_dotenv() 一樣容許沒 .env
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
        # v1.5+：computer control agent mode（multi-turn tool_use/tool_result loop）
        # 跟上面的 use_tool_calling 差別：
        #   - use_tool_calling=true → single-turn、LLM 選 set_mood / play_motion
        #   - use_agent_mode=true → multi-turn、LLM 可以 call 任何 15 個 tool、
        #     tool 結果會回傳給 LLM 繼續（最多 5 輪）
        # 用法：SIRO_USE_AGENT_MODE=false 關（預設 true、給 SIRO computer control 權限）
        # 預設 true（v1.5+ Computer Control 完成後的預設行為、2026-06-08 翻預設）
        # 想「降回原本純 chat」可以設 SIRO_USE_AGENT_MODE=false
        self.use_agent_mode = os.environ.get("SIRO_USE_AGENT_MODE", "true").lower() == "true"
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
        # v0.3.0：Phase 3 siro-runtime gRPC client（SIRO_RUNTIME_ENABLED=true 才會真的連）
        self.runtime: Optional[RuntimeClient] = None
        # v0.3.0：追蹤所有已連線的 WebSocket（給 system_event 廣播用）
        self.connected_websockets: Set = set()
        self.ws_lock = asyncio.Lock()  # 保護 connected_websockets 新增/移除
        # v1.5+：Confirmation broker — SIRO 危險操作前問 user
        # 初始化在 lifespan 內（要等 WS 連上才能廣播）
        self.confirmation_broker: Optional[ConfirmationBroker] = None
        # Phase 1.5.2b：句子級 TTS streaming
        # true → /ws 邊收 LLM delta 邊偵測句尾、每句背景 TTS 完成就推 tts_audio WS
        # 降低第一個音檔抵達 Unity 的時間(原 30s+ 變 8-10s)
        # 預設 false — 既有 Unity TTS 流程(收到 response 才 TTS)不破壞
        # 開:SIRO_TTS_STREAMING=true
        self.use_tts_streaming = os.environ.get("SIRO_TTS_STREAMING", "false").lower() == "true"


state = BridgeState()


# ============================================================
# v0.3.0：system_event 廣播（siro-runtime → bridge → Unity WS）
# ============================================================

# asyncio queue（lazy 創建、要等 event loop 存在才能建）
_event_queue: Optional[asyncio.Queue] = None


def _event_consumer_thread(client: RuntimeClient, loop: asyncio.AbstractEventLoop) -> None:
    """跑在獨立 thread、同步收 siro-runtime events 推到 asyncio queue

    為什麼用 thread 不用 asyncio：
    - gRPC sync streaming 是 blocking iterator
    - 直接在 asyncio event loop 跑會 block 整個 bridge
    - 跑在獨立 thread + asyncio.Queue.put_nowait_from_thread 推 queue 把 sync/async 邊界切乾淨

    v0.3.0+ 加 retry loop：siro-runtime 連不上 / 連線斷了 / RPC 失敗 → 等 5s 重連
    沒 retry 時 siro-runtime 還沒起、或重啟時 consumer 就死掉且永遠不會 reconnect
    """
    import time
    logger.info(f"[system_events] consumer thread 啟動 address={client.address}")
    retry_delay_sec = 5
    attempt = 0
    while True:
        attempt += 1
        try:
            logger.info(f"[system_events] subscribe 嘗試 #{attempt}（address={client.address}）")
            for i, event in enumerate(client.subscribe_events_sync([])):
                if i == 0:
                    logger.info(f"[system_events] 訂閱成功、開始收 events")
                logger.info(f"[system_events] got event #{i}: {event.get('event_type')} {event.get('data')}")
                loop.call_soon_threadsafe(_event_queue.put_nowait, event)
        except Exception as e:
            logger.warning(f"[system_events] consumer 例外 (attempt #{attempt}): {type(e).__name__}: {e}")
        # 失敗或 iterator 自然結束（不該發生、但保險）→ 等 5s 重試
        logger.info(f"[system_events] {retry_delay_sec}s 後 retry...")
        time.sleep(retry_delay_sec)


async def _consume_system_events() -> None:
    """背景 task：從 queue 收 events → log + 廣播給所有 WS clients

    給 K8 KPI 鋪路（subsystem 死掉 → Mao 切 fallback 表情 < 3s）

    重要：給 consumer 自己一個 RuntimeClient 實例、不共用 state.runtime 的 channel。
    原因：gRPC sync streaming 跟 unary call 共享 channel 有時會出 Channel closed 問題。
    """
    if state.runtime is None or not state.runtime.enabled:
        logger.info("[system_events] runtime client disabled、consumer 不啟動")
        return

    # 給 consumer 自己一個 RuntimeClient（獨立 channel、避免跟 state.runtime 的
    # is_connected() 共用 channel 造成 CANCELLED）
    consumer_client = RuntimeClient(
        address=state.runtime.address,
        enabled=True,
        timeout_sec=2.0,
    )
    loop = asyncio.get_running_loop()

    # lazy 創建 queue（要等 event loop 在跑）
    global _event_queue
    if _event_queue is None:
        _event_queue = asyncio.Queue(maxsize=1000)

    logger.info(f"[system_events] consumer 用獨立 client {id(consumer_client)} address={consumer_client.address}")

    # 啟動同步 gRPC streaming thread
    t = threading.Thread(
        target=_event_consumer_thread,
        args=(consumer_client, loop),
        daemon=True,
        name="system-event-consumer",
    )
    t.start()

    while True:
        try:
            # 從 asyncio queue 直接 await（不用 executor）
            event = await _event_queue.get()
            logger.info(f"[system_events] consume 從 queue 拿到 event: {event.get('event_type')}")
            await _broadcast_system_event(event)
        except Exception as e:
            logger.warning(f"[system_events] consume 例外: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


async def _broadcast_system_event(event: dict) -> None:
    """廣播 system event 給所有已連線的 WS clients

    WS message 格式（給 Unity 端用）：
        {
            "type": "system_event",
            "event_type": "service.restarted",
            "data": {"name": "bridge", "pid": "12345", "count": "2"},
            "timestamp_ms": 1234567890,
        }

    Unity 端看到 service.restarted / service.failed / service.stopped
    → Mao 切 thinking 或 sad 表情、UI 顯示「siro reloading...」
    看到 kiosk.enabled / kiosk.disabled → 鎖/解鍵盤（Phase 4 接）
    """
    event_type = event.get("event_type", "unknown")
    data = event.get("data", {})
    logger.info(f"[system_event] {event_type} {data}")

    # 組 WS 訊息
    msg = {
        "type": "system_event",
        "event_type": event_type,
        "data": data,
        "timestamp_ms": event.get("timestamp_ms", 0),
    }

    # 複製 WS 清單（避免 send_json 過程中有人斷線）
    async with state.ws_lock:
        targets = list(state.connected_websockets)

    if not targets:
        return

    # 對每個 WS 推（個別失敗不影響其他）
    for ws in targets:
        try:
            await ws.send_json(msg)
        except Exception as e:
            # WS 可能已斷線、silent drop
            logger.debug(f"[system_event] 推給某 WS 失敗（可能已斷線）: {e}")


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


# ============================================================
# Phase 1.5.2b: 句子級 TTS streaming helper
# ============================================================

async def _stream_tts_for_sentence(
    websocket: WebSocket,
    sentence: str,
    sentence_index: int,
    persona_id: str,
    tts_format: str = "wav",
    turn_id: int = 0,
    last_heard_sink: Optional[Callable[[int, str], None]] = None,
) -> None:
    """背景 TTS 一個句子 → 推 WS `tts_audio` 給 Unity

    Args:
        websocket: Unity 的 WebSocket connection
        sentence: 完整的一句(已 strip [emotion:xxx])
        sentence_index: 句子的全域編號(給 Unity 排序用)
        persona_id: 載 persona voice config 用
        tts_format: 音檔格式(wav / mp3 / opus)
        turn_id: 對話 turn 編號(Phase 2 STT 用,Unity 用來過濾舊 turn 的 TTS chunk)
                 0 = 沒帶(legacy chat flow、Unity 忽略此欄位)
        last_heard_sink: (turn_id, sentence) callback — Phase 2 STT 用來記住
                        上一句 Mao 講過的話,等 user 打斷時可以丟給 LLM context。

    設計:
    - fire-and-forget:被 caller 用 asyncio.create_task 啟動
    - 失敗不 raise:只在 log 記,不要炸 LLM streaming 主流程
    - 推完 tts_audio 後 Unity 自己排隊播放
    - Phase 2 STT:turn_id > 0 時 payload 帶 turn_id、Unity 收到 turn_id ≠ current 會 drop
    - Phase 2 STT barge-in:last_heard_sink 收到 callback 會被記住,等 user 打斷時
                         推 agent_interrupt event + 注入 LLM context
    """
    if not sentence.strip():
        return
    try:
        from .tts import TTSConfig
        from .tts.voices import get_voice_for_persona
        from .tts import get_tts_orchestrator
        # 拿 persona voice config(包含 F5-TTS ref_audio / ref_text)
        try:
            voice_cfg = get_voice_for_persona(persona_id)
        except Exception:
            voice_cfg = TTSConfig(voice_id="zh-TW-HsiaoChenNeural", language="zh-TW")
        orchestrator = get_tts_orchestrator()
        # 累積 audio chunks
        chunks: list[bytes] = []
        async for chunk in orchestrator.synthesize_stream(sentence, voice_cfg):
            chunks.append(chunk)
        if not chunks:
            logger.warning(f"[tts-stream] sentence #{sentence_index} TTS 沒產出音檔")
            return
        import base64
        audio_bytes = b"".join(chunks)
        payload = {
            "type": "tts_audio",
            "index": sentence_index,
            "sentence": sentence,
            "format": tts_format,
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "provider": voice_cfg.provider,
        }
        if turn_id > 0:
            payload["turn_id"] = turn_id  # Phase 2 STT:Unity 端過濾
        await websocket.send_json(payload)
        # Phase 2 STT barge-in:記下「上一句 Mao 講過的話」
        if last_heard_sink is not None and turn_id > 0:
            try:
                last_heard_sink(turn_id, sentence)
            except Exception as e:
                logger.warning(f"[tts-stream] last_heard_sink 失敗: {e}")
        logger.debug(
            f"[tts-stream] 推 sentence #{sentence_index} turn={turn_id}: "
            f"len={len(sentence)} audio={len(audio_bytes)}B via {voice_cfg.provider}"
        )
    except Exception as e:
        logger.error(f"[tts-stream] sentence #{sentence_index} TTS 失敗: {e}")


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
            f"  MiniMaxStreamingClient provider: {state.streaming_client.provider} is_available: {state.streaming_client.is_available}"
        )
    logger.info(
        f"  /ws LLM tool calling: {state.use_tool_calling}（v1.5+、SIRO_USE_TOOL_CALLING=false 可降回 regex parse）"
    )
    logger.info(
        f"  /ws computer control agent mode: {state.use_agent_mode}（v1.5+、SIRO_USE_AGENT_MODE=false 降回純 chat）"
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

    # v0.3.0：Phase 3 siro-runtime gRPC client
    # SIRO_RUNTIME_ENABLED=true 時才會真的去連 siro-runtime
    # 預設 disabled（不影響現有 Phase 1/2 行為）
    state.runtime = get_runtime_client()
    if state.runtime.enabled:
        # 嘗試探測一次（不阻塞 startup，失敗就 log warning）
        if state.runtime.is_connected():
            logger.info(f"  siro-runtime: ✓ 連線成功 ({state.runtime.address})")
        else:
            logger.warning(
                f"  siro-runtime: ✗ 連不上 {state.runtime.address}（siro-runtime 沒跑？"
                f"Phase 3 驗收 (4) 暫不通）"
            )
        # v0.3.0：背景 task 訂 siro-runtime events、廣播給 WS clients
        # （K8 KPI 鋪路：subsystem 死掉 → Mao 在 < 3s 收到 siro reloading）
        asyncio.create_task(_consume_system_events())
        logger.info("  system_event consumer 已啟動（背景訂 siro-runtime events 廣播給 WS）")
    else:
        logger.info("  siro-runtime: disabled（SIRO_RUNTIME_ENABLED=true 啟用）")

    # v1.5+ computer control：confirmation broker + tool action 廣播
    # 初始化在這裡、因為需要 _broadcast_system_event 已存在
    # v1.5.2 翻預設：trust_mode=true（user 說他要完整電腦控制權限、不想一直被問）
    # 想「降回保守模式」設 SIRO_TRUST_MODE=false
    trust_mode = os.environ.get("SIRO_TRUST_MODE", "true").lower() == "true"
    state.confirmation_broker = ConfirmationBroker(
        broadcaster=_broadcast_system_event,  # 複用 WS 廣播、未來可拆
        timeout_sec=float(os.environ.get("SIRO_CONFIRMATION_TIMEOUT_SEC", "60.0")),
        trust_mode=trust_mode,
    )
    if trust_mode:
        logger.warning(
            "  ⚠ TRUST MODE 啟動（預設）：blocklist + confirmation 都跳過、SIRO 完全自主（保留 sandbox + rate limit + audit log）"
        )
    else:
        logger.info("  confirmation broker 已啟動（v1.5+ 危險操作前會問 user）— SIRO_TRUST_MODE=true 可開 trust mode")

    yield

    # 關閉
    if state.telegram_bot:
        await state.telegram_bot.stop()
    if state.runtime:
        state.runtime.close()
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


@app.get("/runtime/status")
async def runtime_status() -> dict:
    """siro-runtime 系統狀態（Phase 3 驗收 (4) 用）

    回傳：
    - enabled: RuntimeClient 是否啟用（SIRO_RUNTIME_ENABLED）
    - address: 目標 gRPC 位址
    - connected: 目前連得上嗎
    - services: 每個 service 的狀態（如果連得上）
    - hardware: CPU/記憶體資訊（如果連得上）
    - runtime_health: siro-runtime 自己的 health RPC 結果
    - bridge_health: bridge 對 siro-runtime 的看法（from 自己的 is_connected）
    """
    if state.runtime is None:
        return {
            "enabled": False,
            "address": None,
            "connected": False,
            "reason": "runtime client not initialized",
        }

    enabled = state.runtime.enabled
    address = state.runtime.address
    connected = state.runtime.is_connected() if enabled else False

    result = {
        "enabled": enabled,
        "address": address,
        "connected": connected,
    }

    if not enabled:
        result["reason"] = "disabled（SIRO_RUNTIME_ENABLED=true 啟用）"
        return result

    if not connected:
        result["reason"] = "siro-runtime 連不上"
        return result

    # 連得上時多塞一些資訊（每次都打 gRPC、會慢一點但 endpoint 本身就 debug 用）
    status = state.runtime.get_status()
    hardware = state.runtime.get_hardware_info()
    health_info = state.runtime.health()
    result["services"] = status.get("services", {})
    result["hardware"] = hardware
    result["runtime_health"] = health_info
    return result


# ==================== v1.5+ Computer control observability ====================

@app.get("/siro/actions")
async def siro_actions(limit: int = 50) -> dict:
    """列出最近 SIRO 工具 actions（給 observability 用）

    Args:
        limit: 最多回幾條（預設 50、最大 500）

    Returns:
        {
            "count": N,
            "actions": [
                {
                    "timestamp": "2026-06-08T...",
                    "user_id": "...",
                    "tool": "run_shell_cmd",
                    "args": {...},
                    "result": "ok" / "denied" / "error",
                    "user_confirmed": bool,
                    "duration_ms": int,
                    ...
                },
                ...
            ]
        }
    """
    from .security import get_audit_log
    limit = max(1, min(int(limit), 500))
    audit = get_audit_log()
    actions = audit.read_recent(limit=limit)
    return {
        "count": len(actions),
        "actions": actions,
    }


@app.get("/siro/memories")
async def siro_memories(query: Optional[str] = None, limit: int = 20) -> dict:
    """列出 / 搜尋 SIRO 長期記憶

    Args:
        query: 模糊搜尋字串（optional）
        limit: 最多回幾條（預設 20、最大 100）

    Returns:
        {
            "count": N,
            "memories": [
                {"id": "...", "timestamp": "...", "content": "...", "tags": [...], "importance": 0.5},
                ...
            ]
        }
    """
    from .tools.memory import recall_memory as _recall, list_memories as _list
    limit = max(1, min(int(limit), 100))

    if query and query.strip():
        result = await _recall({"query": query, "limit": limit}, {})
    else:
        result = await _list({"limit": limit}, {})

    if not result.get("ok"):
        return {"count": 0, "memories": [], "error": result.get("error")}

    return {
        "count": result.get("count", 0),
        "query": query,
        "memories": result.get("memories", []),
    }


@app.get("/siro/tools")
async def siro_tools() -> dict:
    """列出所有 v1.5+ 啟用的 SIRO 工具（給前端 debug / 教學用）"""
    from .tools import get_available_tools
    tools = get_available_tools()
    return {
        "count": len(tools),
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", "")[:200],
                "category": (
                    "SendTask" if t["name"] in ("set_mood", "play_motion")
                    else None
                ),
            }
            for t in tools
        ],
    }


# ============================================================
# v1.0 Core Experience Phase 1: TTS 路由
# 設計見 docs/TTS_INTEGRATION.md
# Unity 端在 LLM 回應後主動打 /tts/synthesize 拿音檔
# Phase 1.5: 自動 trigger(LLM 出 sentence 立即合成)
# ============================================================

@app.get("/tts/voices", response_model=TTSVoicesResponse)
async def list_tts_voices(
    provider: str = "edge-tts",
    language: str = "",
) -> TTSVoicesResponse:
    """列出可用聲線(給 Unity 端 dropdown 用)

    Args:
        provider: edge-tts / piper / gpt-sovits
        language: 過濾語言(空字串 = 全部)
    """
    try:
        from .tts import list_available_voices, get_tts_orchestrator
        voices = await list_available_voices(provider=provider, language=language)
        active = await get_tts_orchestrator().get_active_provider()
        return TTSVoicesResponse(
            provider=provider,
            voices=[TTSVoiceInfo(
                id=v.id, name=v.name, language=v.language,
                gender=v.gender, provider=v.provider, preview_url=v.preview_url,
            ) for v in voices],
            active_provider=active.name,
            language_filter=language or None,
        )
    except Exception as e:
        # TTS 套件沒裝、或 edge-tts 連不上時,回空清單(不讓整個 bridge 掛掉)
        logger.warning(f"[tts] list_voices failed: {e}")
        return TTSVoicesResponse(
            provider=provider,
            voices=[],
            active_provider=None,
            language_filter=language or None,
        )


@app.get("/tts/persona/{persona_id}")
async def get_persona_voice_config(persona_id: str) -> dict:
    """拿 persona 預設的 TTS 設定(給 Unity 端知道用哪個 voice)"""
    from .tts.voices import get_voice_for_persona
    persona = load_persona(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"persona '{persona_id}' not found")
    config = get_voice_for_persona(persona)
    return {
        "persona_id": persona_id,
        "provider": config.provider,
        "voice_id": config.voice_id,
        "language": config.language,
        "speed": config.speed,
        "pitch": config.pitch,
        "format": config.format,
    }


@app.post("/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(req: TTSRequest) -> TTSResponse:
    """文字 → 音檔(給 Unity 端主動呼叫)

    回 base64 編碼的音檔 + 用了哪個 provider + chunk 數。

    Phase 1.5.1b 修:支援 F5-TTS — 自動從 persona 載入 ref_audio / ref_text,
    或直接從 req 帶。
    """
    from .tts import TTSConfig
    from .tts.voices import get_voice_for_persona
    try:
        # 若 req 帶 persona_id,自動載入 persona 設定(ref_audio / ref_text / voice 預設)
        extra: dict = {}
        persona_id = req.persona_id or "siro-default"
        try:
            persona = load_persona(persona_id)
            voice_cfg = persona.get("voice", {}) if persona else {}
            # req 沒帶 → 從 persona 拿
            if not req.ref_audio and voice_cfg.get("ref_audio"):
                extra["ref_audio"] = voice_cfg["ref_audio"]
            elif req.ref_audio:
                extra["ref_audio"] = req.ref_audio
            if not req.ref_text and voice_cfg.get("ref_text"):
                extra["ref_text"] = voice_cfg["ref_text"]
            elif req.ref_text:
                extra["ref_text"] = req.ref_text
            # nfe_step / cfg_strength(從 persona 拿)
            if req.nfe_step is None and voice_cfg.get("nfe_step"):
                extra["nfe_step"] = voice_cfg["nfe_step"]
            elif req.nfe_step is not None:
                extra["nfe_step"] = req.nfe_step
            if req.cfg_strength is None and voice_cfg.get("cfg_strength"):
                extra["cfg_strength"] = voice_cfg["cfg_strength"]
            elif req.cfg_strength is not None:
                extra["cfg_strength"] = req.cfg_strength
        except Exception as e:
            logger.warning(f"[tts] load persona {persona_id} failed: {e}, 用 req 帶的欄位")
            if req.ref_audio:
                extra["ref_audio"] = req.ref_audio
            if req.ref_text:
                extra["ref_text"] = req.ref_text
            if req.nfe_step is not None:
                extra["nfe_step"] = req.nfe_step
            if req.cfg_strength is not None:
                extra["cfg_strength"] = req.cfg_strength

        orchestrator = get_tts_orchestrator()
        config = TTSConfig(
            provider=req.provider,
            voice_id=req.voice_id,
            language=req.language,
            speed=req.speed,
            pitch=req.pitch,
            format=req.format,
            extra=extra,
        )
        # 累積 chunks
        chunks: list[bytes] = []
        chunk_count = 0
        async for chunk in orchestrator.synthesize_stream(req.text, config):
            chunks.append(chunk)
            chunk_count += 1
        if not chunks:
            raise RuntimeError("TTS 沒產出任何音檔")
        audio_bytes = b"".join(chunks)
        import base64
        return TTSResponse(
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            format=req.format,
            provider=config.provider,
            voice_id=config.voice_id,
            chunks=chunk_count,
            text_len=len(req.text),
        )
    except Exception as e:
        logger.error(f"[tts] synthesize failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS 合成失敗: {e}")


# ============================================================
# v1.5+ Free Exploration mode（24/7 自主探索）
# ============================================================

@app.post("/siro/explore/start")
async def siro_explore_start(
    interval_sec: float = 300.0,
    max_iter: int = 3,
) -> dict:
    """啟動 SIRO 24/7 自由探索

    SIRO 會在 sandbox 內自主決定要做什麼、靠本地小模型（qwen2.5:3b）跑
    不燒 token 也能探索

    Args:
        interval_sec: 兩次探索 session 的間隔（預設 5 分鐘）
        max_iter: 每次 session 最多幾輪 tool calls（預設 3）
    """
    from .free_exploration import (
        FreeExplorationScheduler,
        get_exploration_scheduler,
    )
    scheduler = get_exploration_scheduler()
    if scheduler is None:
        scheduler = FreeExplorationScheduler(
            state=state,
            interval_sec=interval_sec,
            max_iter_per_session=max_iter,
        )
        from .free_exploration import set_exploration_scheduler
        set_exploration_scheduler(scheduler)
    else:
        # 更新間隔
        scheduler.interval_sec = interval_sec
        scheduler.max_iter_per_session = max_iter
    return scheduler.start()


@app.post("/siro/explore/stop")
async def siro_explore_stop() -> dict:
    """暫停 SIRO 自由探索"""
    from .free_exploration import get_exploration_scheduler
    scheduler = get_exploration_scheduler()
    if scheduler is None:
        return {"ok": False, "error": "scheduler 沒初始化"}
    return scheduler.stop()


@app.get("/siro/explore/status")
async def siro_explore_status() -> dict:
    """看 SIRO 自由探索的狀態"""
    from .free_exploration import get_exploration_scheduler
    scheduler = get_exploration_scheduler()
    if scheduler is None:
        return {"initialized": False, "running": False}
    s = scheduler.get_status()
    s["initialized"] = True
    return s


@app.get("/siro/explore/log")
async def siro_explore_log(limit: int = 20) -> dict:
    """看 SIRO 自由探索的 log"""
    from .free_exploration import get_exploration_scheduler
    scheduler = get_exploration_scheduler()
    if scheduler is None:
        return {"count": 0, "entries": [], "error": "scheduler 沒初始化"}
    entries = scheduler.read_recent(limit=limit)
    return {"count": len(entries), "entries": entries}


# ============================================================
# 端點（Personas）
# ============================================================

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
    voice_cfg = get_persona_voice(persona_id)  # v1.0 Core Experience Phase 1

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
        voice=voice_cfg,
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

    # 段 2: 判斷實際可用的 LLM backend
    # v1.5.2 fix：原本只看 hermes.is_available()，但 v0.3.1+ streaming_client
    # (MiniMax / Ollama via OpenAI-compat) 是另一條獨立路徑、根本不依賴 hermes 二進位。
    # 沒裝 hermes 但 streaming 通，照樣能回 Unity — 不該走 fallback。
    # 改：列出所有可用 backend，只要「至少一個通」就放行；具體走哪條由後面
    # (use_streaming / use_tool_calling / use_agent_mode) 決定。
    t0 = time.time()
    backend_available = False
    backend_label = ""
    if state.use_streaming and state.streaming_client and state.streaming_client.is_available:
        backend_available = True
        backend_label = f"streaming({state.streaming_client.model})"
    if not backend_available and state.ollama and await asyncio.to_thread(state.ollama.is_available):
        backend_available = True
        backend_label = f"ollama({state.ollama.model})"
    if not backend_available and state.hermes and await asyncio.to_thread(state.hermes.is_available):
        backend_available = True
        backend_label = "hermes"
    t_is_avail = time.time() - t0
    if not backend_available:
        logger.warning(
            f"⏱ [chat] 段 2 no LLM backend available ({t_is_avail*1000:.0f}ms) → fallback"
        )
        return await _make_fallback_response(
            user_id=req.user_id,
            session_id=session_id,
            category="error",
            persona_name=persona_name,
            error_detail="no LLM backend available (streaming/ollama/hermes all down)",
            user_message=req.message,
        )
    logger.info(f"⏱ [chat] 段 2 backend={backend_label} ({t_is_avail*1000:.0f}ms) → 放行")

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


async def _process_ws_chat(
    websocket: WebSocket,
    data: dict,
    last_heard_sink: Optional[Callable[[int, str], None]] = None,
) -> None:
    """v1.2+ 抽出來 create_task 跑、不卡 receive loop。

    原本 chat 處理（5-30s LLM call）INLINE 在 /ws 的 while loop、
    整段期間不 `await receive_json` 也不 `await send_json`、
    下一個 message（mood.set / motion.play 點 Mao）就卡 OS receive buffer、5s timeout 觸發。

    抽出來後、main loop 立即回到 receive_json 收下一個 message。
    SendTask (mood.set/motion.play) 走 AgentOS.enqueue_fast 立即有反應。

    注意：背景 coroutine 噴 exception 不會被外層 except WebSocketDisconnect 接住、
    呼叫端用 `_log_async_task_exception` 統一吃掉（Unity 中途斷線 → chat 跑完
    才發現 WS 已關 → send_json 噴 RuntimeError 是預期的、log warning 就好）。

    Phase 2 STT:turn_id > 0 時,所有 tts_audio chunk 帶 turn_id 給 Unity 過濾。
    Day 3:last_heard_sink 記住「上一句 Mao 講過的話」,給 user 打斷時注入 LLM context。
    """
    message = data.get("message", "").strip()
    user_id = data.get("user_id", "default")
    personality = data.get("personality", "default")
    turn_id = int(data.get("turn_id", 0))  # Phase 2 STT:0 = legacy(不帶 turn_id)

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

    # 段 0: 判斷實際可用的 LLM backend
    # v1.5.2 fix：原本只看 hermes.is_available()，但 v0.3.1+ streaming_client
    # (MiniMax / Ollama via OpenAI-compat) 是另一條獨立路徑、根本不依賴 hermes 二進位。
    # 沒裝 hermes 但 streaming 通，照樣能回 Unity — 不該走 fallback。
    # 改：列出所有可用 backend，只要「至少一個通」就放行；具體走哪條由後面
    # (use_streaming / use_tool_calling / use_agent_mode) 決定。
    t0 = time.time()
    backend_available = False
    backend_label = ""
    if state.use_streaming and state.streaming_client and state.streaming_client.is_available:
        backend_available = True
        backend_label = f"streaming({state.streaming_client.model})"
    if not backend_available and state.ollama and await asyncio.to_thread(state.ollama.is_available):
        backend_available = True
        backend_label = f"ollama({state.ollama.model})"
    if not backend_available and state.hermes and await asyncio.to_thread(state.hermes.is_available):
        backend_available = True
        backend_label = "hermes"
    t_is_avail = time.time() - t0
    if not backend_available:
        logger.warning(
            f"⏱ [ws] no LLM backend available ({t_is_avail*1000:.0f}ms) → fallback"
        )
        fallback = await _make_fallback_response(
            user_id=user_id,
            session_id=session_id,
            category="disconnected",
            persona_name=personality,
            error_detail="no LLM backend available (streaming/ollama/hermes all down)",
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
    logger.info(f"⏱ [ws] backend={backend_label} ({t_is_avail*1000:.0f}ms) → 放行")

    # v0.3.1 SSE streaming 路徑（STRATEGIC_NOTES Q2 選項 B）：
    #   - SIRO_STREAMING=true → 走 MiniMaxStreamingClient.chat_stream() 收 SSE
    #   - 每收到一個 text chunk 就推 {"type":"delta","text":"..."} 給 Unity
    #   - 收集完所有 chunk 後 parse emotion、推 {"type":"response",...}
    #   - Unity 端目前收到 delta 不 render（v1+ 才接 incremental render）
    #   - 預設 false — 既有測試不動
    t0 = time.time()
    # v1.5+ Computer control agent mode（multi-turn tool_use/tool_result）
    # 走 streaming_client.run_agent_loop、可以 call 任何 15 個 tool（含 filesystem / shell / memory）
    # 跟下面 single-turn tool calling 差別：可以反覆 call tool 直到收工
    if (
        state.use_agent_mode
        and state.use_streaming
        and state.streaming_client.is_available
    ):
        from .tasks.llm_reply_task import create_llm_agent_task

        # 拿 history
        agent_history = state.sessions.get(session_id, [])
        agent_history_context = ""
        if agent_history:
            agent_history_context = "\n\n最近的對話：\n" + "\n".join(
                f"使用者: {h['user']}\n你: {h['agent']}" for h in agent_history[-5:]
            )
        agent_prompt = f"{agent_history_context}\n\n使用者: {message}" if agent_history_context else message
        agent_system = get_personality(personality)

        logger.info(f"⏱ [ws] 走 agent mode (v1.5+ computer control)")

        # 走 AgentOS（跟 /chat 一致）→ enqueue task → wait
        if state.use_agent_os and state.agent_os:
            task = create_llm_agent_task(
                state=state,
                user_id=user_id,
                message=agent_prompt,
                persona_name=personality,
                session_id=session_id,
            )
            state.agent_os.enqueue(task)
            logger.info(f"⏱ [ws] enqueue agent task id={task.id} → 走 AgentOS")
            agent_result = await state.agent_os.wait_for_task(
                "llm.reply.agent", task.id, timeout=600.0,
            )
            if agent_result is None or "error" in agent_result:
                error_detail = (
                    agent_result.get("error", "agent task timeout")
                    if agent_result else "agent task timeout"
                )
                fallback = await _make_fallback_response(
                    user_id=user_id,
                    session_id=session_id,
                    category="error",
                    persona_name=personality,
                    error_detail=error_detail,
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
            result = agent_result["result"]
            logger.info(
                f"⏱ [ws-agent] user={message[:40]!r} → text={result.get('text','')[:60]!r} "
                f"iter={result.get('iterations', 0)} tools={result.get('tool_calls', [])}"
            )
            # 推 tool_action 給 Unity（每個 tool call 一個 event）
            for tc in result.get("tool_calls", []):
                await websocket.send_json({
                    "type": "tool_action",
                    "tool": tc.get("tool"),
                    "args": tc.get("args"),
                    "ok": tc.get("ok"),
                    "duration_ms": tc.get("duration_ms"),
                })
            await websocket.send_json({
                "type": "response",
                "text": result["text"],
                "emotion": result["emotion"],
                "intensity": result["intensity"],
                "live2d": result["live2d"],
                "session_id": result["session_id"],
            })
            return

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
        # Phase 1.5.2b: 句子級 TTS streaming
        # LLM 出 token 邊累積邊切句、每句背景 invoke TTS
        from .tts.sentence_buffer import SentenceBuffer
        sentence_buffer = SentenceBuffer()
        sentence_idx_counter = 0
        tts_tasks: list = []  # background TTS task references
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
                    # 句子切割 → 背景觸發 TTS
                    if state.use_tts_streaming:
                        for sentence in sentence_buffer.feed(event.text):
                            sentence_idx_counter += 1
                            tts_tasks.append(asyncio.create_task(
                                _stream_tts_for_sentence(
                                    websocket, sentence, sentence_idx_counter,
                                    persona_id=personality,
                                    turn_id=turn_id,
                                    last_heard_sink=last_heard_sink,
                                )
                            ))
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
        # Phase 1.5.2b: 收尾 — 殘餘 buffer 也 TTS,等所有 TTS task 結束
        if state.use_tts_streaming:
            for sentence in sentence_buffer.flush():
                sentence_idx_counter += 1
                tts_tasks.append(asyncio.create_task(
                    _stream_tts_for_sentence(
                        websocket, sentence, sentence_idx_counter,
                        persona_id=personality,
                        turn_id=turn_id,
                        last_heard_sink=last_heard_sink,
                    )
                ))
            if tts_tasks:
                logger.info(
                    f"⏱ [tts-stream] 等待 {len(tts_tasks)} 個句子 TTS 完成..."
                )
                await asyncio.gather(*tts_tasks, return_exceptions=True)
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
        elif tool_use_event and tool_use_event.name == "play_motion":
            # v1.5+ play_motion tool：LLM 想觸發 body motion
            # emotion 用 regex parse（因為 LLM 沒設 emotion、預設中性）
            clean_text, emotion, intensity = parser.parse(full_text, user_input=message)
            emotion_str = emotion.value
            logger.info(f"⏱ [ws] tool_use=play_motion、emotion fallback regex: emotion={emotion_str}")

            # Invoke motion.play task handler
            # task 會自己 log + 推 WS event 給 Unity（見 bridge/tasks/builtin.py:165）
            motion_handler = get_task("motion.play")
            if motion_handler is not None:
                try:
                    await motion_handler(
                        tool_use_event.input,
                        {
                            "state": state,
                            "user_id": user_id,
                            "task_id": f"tool-{uuid.uuid4().hex[:8]}",
                            "websocket": websocket,
                        }
                    )
                    logger.info(
                        f"⏱ [ws] play_motion 觸發: {tool_use_event.input.get('motion_group')}[{tool_use_event.input.get('motion_index', 0)}]"
                    )
                except Exception as e:
                    logger.warning(f"[ws] play_motion task 失敗: {e}")
            else:
                logger.warning("[ws] motion.play task 沒註冊、跳過")
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
        # Phase 1.5.2b: 句子級 TTS streaming(plain path 沒有 tool use)
        from .tts.sentence_buffer import SentenceBuffer
        sentence_buffer = SentenceBuffer()
        sentence_idx_counter = 0
        tts_tasks: list = []
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
                # 句子切割 → 背景觸發 TTS
                if state.use_tts_streaming:
                    for sentence in sentence_buffer.feed(chunk):
                        sentence_idx_counter += 1
                        tts_tasks.append(asyncio.create_task(
                            _stream_tts_for_sentence(
                                websocket, sentence, sentence_idx_counter,
                                persona_id=personality,
                                turn_id=turn_id,
                                last_heard_sink=last_heard_sink,
                            )
                        ))
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
        # Phase 1.5.2b: 收尾 — 殘餘 buffer 也 TTS,等所有 TTS task 結束
        if state.use_tts_streaming:
            for sentence in sentence_buffer.flush():
                sentence_idx_counter += 1
                tts_tasks.append(asyncio.create_task(
                    _stream_tts_for_sentence(
                        websocket, sentence, sentence_idx_counter,
                        persona_id=personality,
                        turn_id=turn_id,
                        last_heard_sink=last_heard_sink,
                    )
                ))
            if tts_tasks:
                logger.info(
                    f"⏱ [tts-stream] 等待 {len(tts_tasks)} 個句子 TTS 完成..."
                )
                await asyncio.gather(*tts_tasks, return_exceptions=True)
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
        接收: {"type": "system_event", "event_type": "...", "data": {...}, "timestamp_ms": ...}  # v0.3.0

        Phase 2 STT 新加:
        發送: {"type": "text_input", "turn_id": N, "text": "...", "user_id": "..."}
        發送: {"type": "mic_chunk", "turn_id": N, "audio_base64": "..."}
        接收: {"type": "vad_pause", "turn_id": N}  # 偵測到 speech start
        接收: {"type": "vad_resume", "turn_id": N, "audio_base64": "...", "duration_ms": N}
        接收: {"type": "agent_interrupt", "turn_id": N, "last_heard": "..."}  # (Day 3)
        接收: {"type": "tts_audio", "turn_id": N, ...}  # 帶 turn_id(turn_id > 0 時)

    降級策略（GAPS.md #4 + #9）：
    - Bridge 內部沒初始化 → 關連線（這是 bug）
    - Hermes 不可用 → 維持連線，每次 chat 都回 fallback response（Mao 切 thinking）
    - Hermes chat 失敗 → 同上

    v0.3 細項：opt-in 走 AgentOS
    - SIRO_USE_AGENT_OS=true → /ws 跟 /chat 一樣 enqueue AgentOS task、wait_for_task 拿結果
    - 跟 /chat 共用 `create_llm_reply_task()` factory（無重複）
    - 預設 false（行為跟 v0.2 相同、165+ 既有測試不動）
    - Timeout / failed 都走 fallback response、WS 連線不中斷

    v0.3.0：system_event 廣播
    - SIRO_RUNTIME_ENABLED=true → background task 訂 siro-runtime events
    - 收到後 broadcast 給所有 state.connected_websockets
    - Unity 收到 service.restarted / failed → 切 thinking / sad 表情

    Phase 2 STT (Day 2):
    - 每個 WS 連線有自己的 TurnManager + SileroVAD(per-connection state)
    - text_input / mic_chunk(VAD resume)都走 TurnManager 開新 conversation
    - 新 turn 自動 cancel 舊 turn(Pattern 4)
    """
    await websocket.accept()
    logger.info(f"🔌 WebSocket 連線: {websocket.client}")

    # v0.3.0：加進連線清單（給 system_event 廣播用）
    async with state.ws_lock:
        state.connected_websockets.add(websocket)

    if not state.hermes or not state.parser:
        await websocket.send_json({"type": "error", "detail": "Bridge 尚未初始化"})
        await websocket.close()
        return

    # 注意：is_available() false 不關連線。讓 Unity 維持連線、後續每次
    # chat 走 fallback。這樣 Mao 看起來「在但有點傻」而非「失蹤」。
    # 改用 to_thread：不卡 event loop、WS 接收 loop 仍能處理 ping/SendTask
    if not await asyncio.to_thread(state.hermes.is_available):
        logger.warning("⚠ Hermes 不可用，但維持 WebSocket 連線、走 fallback response")

    # Phase 2 STT:per-WS state(turn manager + VAD)
    from .conversation import TurnManager
    from .vad import SileroVAD, SileroVADConfig
    turn_manager = TurnManager()
    vad = SileroVAD()  # 預設 config
    # 用來 correlate 還沒送 STT 的 utterance(給 agent_interrupt last_heard 用)
    last_utterance_text: list[str] = []  # 用 list 是為了 mutable closure
    # Phase 2 STT barge-in (Day 3):記住「上一句 Mao 講過的話」by turn_id
    # 等 user 講話打斷時 → 推 agent_interrupt event 給 Unity、注入 LLM context
    last_heard: dict[int, str] = {}  # turn_id → 最後一句 Mao 講的話

    def _last_heard_sink(turn_id: int, sentence: str) -> None:
        """被 _stream_tts_for_sentence 呼叫、記住每個 turn 的最後一句話。"""
        # 同一 turn 多句 → 只記最後一句(最 relevant)
        last_heard[turn_id] = sentence

    async def _run_conversation_turn(
        turn_id: int,
        text: str,
        user_id: str = "default",
        personality: str = "default",
        interrupted_text: str = "",
    ) -> None:
        """Pattern 4 包的 conversation run:用 _process_ws_chat 但帶 turn_id。

        Day 2 簡化版:直接 reuse 既有 chat 流程、加 turn_id 進去。
        TTS chunks 帶 turn_id、Unity 端可以過濾。

        Day 3:支援 barge-in interrupted_text — 上一句 Mao 講過的話、
        prepended 到 message 前面讓 LLM 知道 user 是打斷哪個話題。
        """
        # 模擬 chat message 格式
        final_text = text
        if interrupted_text:
            # Pattern 3:注入 [interrupted by user] 給 LLM context
            final_text = f"[User interrupted previous conversation about: '{interrupted_text}']\n\n{text}"
        data = {
            "type": "chat",
            "message": final_text,
            "user_id": user_id,
            "personality": personality,
            "turn_id": turn_id,
        }
        await _process_ws_chat(websocket, data)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "chat":
                # v1.2+ 改：chat 處理整段 create_task 出去跑、不卡 receive loop
                chat_task = asyncio.create_task(
                    _process_ws_chat(websocket, data, last_heard_sink=_last_heard_sink)
                )
                chat_task.add_done_callback(_log_async_task_exception)
                continue

            elif msg_type == "text_input":
                # Phase 2 STT:文字輸入(從 chat box)帶 turn_id
                # 走跟 chat 一樣的流程,但走 TurnManager(新 turn 自動 cancel 舊)
                turn_id = int(data.get("turn_id", 0))
                text = data.get("text", "").strip()
                user_id = data.get("user_id", "default")
                personality = data.get("personality", "default")
                if not text:
                    await websocket.send_json({"type": "error", "detail": "text 不能空白"})
                    continue
                if turn_id <= 0:
                    await websocket.send_json({"type": "error", "detail": "text_input 需要 turn_id > 0"})
                    continue
                # Day 3:user 打字也算打斷,推 agent_interrupt + 注入 interrupted_text
                prev_turn_id = turn_manager.current_turn_id
                prev_heard = last_heard.get(prev_turn_id, "") if prev_turn_id > 0 else ""
                if prev_heard:
                    await websocket.send_json({
                        "type": "agent_interrupt",
                        "turn_id": turn_id,
                        "last_heard": prev_heard,
                    })
                async def run_text_input():
                    await _run_conversation_turn(
                        turn_id, text, user_id, personality,
                        interrupted_text=prev_heard,
                    )
                conv_task = await turn_manager.start_new_turn(turn_id, run_text_input)
                conv_task.task.add_done_callback(_log_async_task_exception)
                continue

            elif msg_type == "mic_chunk":
                # Phase 2 STT:Unity mic 32ms chunk 16-bit PCM 16kHz
                turn_id = int(data.get("turn_id", 0))
                audio_b64 = data.get("audio_base64", "")
                if not audio_b64:
                    continue
                import base64
                try:
                    audio_bytes = base64.b64decode(audio_b64)
                except Exception:
                    continue
                # Day 8.6 debug log:確認 mic_chunk 真的進到 bridge
                if not hasattr(websocket, "_mic_chunk_logged_first"):
                    logger.info(
                        f"🎙️ [stt] 第一個 mic_chunk: turn_id={turn_id} bytes={len(audio_bytes)} "
                        f"client={websocket.client}"
                    )
                    websocket._mic_chunk_logged_first = True
                # 餵 VAD,看有沒有 PAUSE/RESUME event
                user_id = "default"  # TODO: 從 WS state 拿
                personality = data.get("personality", "default")
                # Day 8 fix:barge-in 被打斷 turn 的 last_heard 預設空字串
                # pause 段會覆寫、resume 段直接讀這個值(避免查已被覆寫的 turn_manager.current_turn_id)
                prev_heard = ""
                for event in vad.feed(audio_bytes, turn_id):
                    if event.type.value == "pause":
                        # Speech start → 推 vad_pause 給 Unity、準備 cancel 舊 turn
                        # Day 3:同時推 agent_interrupt(Pattern 3 — LLM 知道被打斷)
                        prev_turn_id = turn_manager.current_turn_id
                        prev_heard = last_heard.get(prev_turn_id, "") if prev_turn_id > 0 else ""
                        if prev_heard:
                            await websocket.send_json({
                                "type": "agent_interrupt",
                                "turn_id": turn_id,
                                "last_heard": prev_heard,
                            })
                        await websocket.send_json({
                            "type": "vad_pause",
                            "turn_id": turn_id,
                        })
                        async def run_idle_placeholder():
                            # 等 RESUME,什麼都不做(placeholder)
                            await asyncio.sleep(0.1)
                        await turn_manager.start_new_turn(turn_id, run_idle_placeholder)
                    elif event.type.value == "resume":
                        # Speech end → 推 vad_resume + 啟動 STT+LLM+TTS
                        duration_ms = event.duration_ms or 0
                        audio_b64_out = base64.b64encode(event.audio or b"").decode("ascii")
                        await websocket.send_json({
                            "type": "vad_resume",
                            "turn_id": turn_id,
                            "duration_ms": duration_ms,
                            "audio_base64": audio_b64_out,
                        })
                        # 啟動 ASR + LLM 流程
                        captured_audio = event.audio or b""
                        # Day 8 fix:重用 pause 段算的 prev_heard(被打斷 turn 的 last_heard)
                        # 不要重新查 turn_manager.current_turn_id(已被 start_new_turn 改成新 turn 了)
                        captured_interrupted = prev_heard
                        async def run_stt_llm():
                            from .stt import FasterWhisperAsr
                            asr = FasterWhisperAsr()  # TODO:state cache
                            if not asr.is_available():
                                logger.warning("[stt] ASR 不可用,跳過 STT")
                                return
                            # 16-bit PCM → float32 [-1, 1]
                            import numpy as np
                            if not captured_audio:
                                return
                            audio_np = np.frombuffer(captured_audio, dtype=np.int16).astype(np.float32) / 32768.0
                            asr_result = await asr.transcribe(audio_np, hint_language=personality[:2] if personality else None)
                            if not asr_result.text.strip():
                                logger.info(f"[stt] ASR 沒結果 turn_id={turn_id} → 跳過")
                                return
                            text = asr_result.text.strip()
                            last_utterance_text.append(text)
                            # 跑 LLM + TTS(帶 turn_id + interrupted_text 注入 context)
                            await _run_conversation_turn(
                                turn_id, text, user_id, personality,
                                interrupted_text=captured_interrupted,
                            )
                        conv_task = await turn_manager.start_new_turn(turn_id, run_stt_llm)
                        conv_task.task.add_done_callback(_log_async_task_exception)
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

            elif msg_type == "confirmation_response":
                # v1.5+：user 回應 confirmation request
                # 從 data 拿 confirmation_id + approved、轉給 broker
                confirmation_id = data.get("confirmation_id", "")
                approved = bool(data.get("approved", False))
                if not confirmation_id:
                    await websocket.send_json({
                        "type": "error",
                        "detail": "confirmation_response 缺 confirmation_id",
                    })
                    continue
                if state.confirmation_broker is None:
                    await websocket.send_json({
                        "type": "error",
                        "detail": "confirmation broker 還沒初始化",
                    })
                    continue
                resolved = state.confirmation_broker.resolve(confirmation_id, approved)
                await websocket.send_json({
                    "type": "confirmation_acked",
                    "confirmation_id": confirmation_id,
                    "resolved": resolved,
                })
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
    finally:
        # v0.3.0：從連線清單移除（不管怎麼離開都做）
        async with state.ws_lock:
            state.connected_websockets.discard(websocket)


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
