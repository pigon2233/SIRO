"""
bridge/models.py - Pydantic schemas for SIRO bridge API
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class Emotion(str, Enum):
    """支援的情緒種類（v0.2 = 9 種，對應 Mao 8 個 expression + neutral 借用）"""
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    THINKING = "thinking"  # exp_06 實際是害羞臉（Mao 沒有真正 thinking 表情、借用此臉）
    EXCITED = "excited"
    JOYFUL = "joyful"      # 比 happy 更強的開心，哈哈大笑（exp_02）
    PROUD = "proud"        # 驕傲、得意（exp_03）
    NEUTRAL = "neutral"


class Live2DSignal(BaseModel):
    """驅動 Live2D 模型的動畫指令"""
    expression_id: str = Field(..., description="Cubism expression 檔 ID，如 'F02'")
    motion_group: Optional[str] = Field(None, description="Cubism motion 群組")
    motion_index: Optional[int] = Field(None, description="群組內的 motion 編號")
    intensity: float = Field(0.7, ge=0.0, le=1.0, description="情緒強度 0-1")
    duration_ms: int = Field(500, ge=0, description="過渡時間毫秒")


class ChatRequest(BaseModel):
    """對話請求"""
    message: str = Field(..., min_length=1, max_length=2000, description="使用者訊息")
    user_id: str = Field("default", description="使用者 ID，用於 session 管理")
    session_id: Optional[str] = Field(None, description="session ID，留空會自動產生")
    personality: Optional[str] = Field(None, description="角色人格 preset 名稱")


class ChatResponse(BaseModel):
    """對話回應"""
    text: str = Field(..., description="Agent 回應文字（不含情緒標籤）")
    emotion: Emotion = Field(..., description="偵測到的情緒")
    intensity: float = Field(0.7, ge=0.0, le=1.0, description="情緒強度")
    live2d: Live2DSignal = Field(..., description="Live2D 動畫指令")
    session_id: str = Field(..., description="本次 session ID")
    user_id: str = Field(..., description="使用者 ID")
    raw_response: Optional[str] = Field(None, description="Hermes 原始輸出（含標籤）")


class HealthResponse(BaseModel):
    """健康檢查回應"""
    status: str
    hermes_available: bool
    hermes_version: Optional[str] = None
    bridge_version: str = "0.1.0"


class PersonaSummary(BaseModel):
    """Persona 摘要（給 UI 列表用）"""
    id: str
    name: str
    version: Optional[str] = None
    language: Optional[str] = None
    # 視覺模型基本資料
    model_type: Optional[str] = None
    prefab_path: Optional[str] = None


class VisualPosition(BaseModel):
    """視覺錨點偏移（normalized，-1.0 ~ 1.0）

    對應 Unity RectTransform.anchoredPosition（normalized）：
    - x: -1.0 (螢幕最左) ~ 1.0 (螢幕最右)
    - y: -1.0 (螢幕最下) ~ 1.0 (螢幕最上)
    """
    x: float = Field(0.0, ge=-1.0, le=1.0)
    y: float = Field(0.0, ge=-1.0, le=1.0)


class VisualSettings(BaseModel):
    """v0.3+ 視覺設定檔（per-persona）

    Unity 啟動時 /personas/{id} 拿這份直接套用 transform/canvas。
    全部都有合理 default — 沒寫 YAML 也照跑。
    """
    scale: float = Field(1.0, ge=0.3, le=3.0, description="角色縮放 0.3-3.0 倍")
    position: VisualPosition = Field(default_factory=VisualPosition)
    anchor: str = Field(
        "bottom-center",
        description="9-grid 錨點：top-left/top-center/top-right/middle-left/center/middle-right/bottom-left/bottom-center/bottom-right",
    )
    brightness: float = Field(1.0, ge=0.3, le=1.5, description="整體亮度倍率 0.3-1.5")
    opacity: float = Field(1.0, ge=0.0, le=1.0, description="透明度 0.0-1.0")
    mirror: bool = Field(False, description="左右鏡像")
    z_order: int = Field(0, ge=-100, le=100, description="Canvas sortOrder")


class PersonaDetail(PersonaSummary):
    """Persona 完整資料（含 Live2D signal 設定、quirks、視覺設定檔）"""
    # quirks
    hide_eye_on_expressions: list[str] = Field(default_factory=list)
    eye_drawable_indices: list[int] = Field(default_factory=list)
    # emotions 對應的 Live2D signals
    expressions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # 待機動作
    idle_motions: list[str] = Field(default_factory=list)
    idle_interval_seconds: list[int] = Field(default_factory=list)
    # v0.3+ 視覺設定檔（scale/position/anchor/brightness/opacity/mirror/z_order）
    visual: VisualSettings = Field(default_factory=VisualSettings)
    # v1.0 Core Experience Phase 1：TTS 設定（給 Unity 端知道用哪個 voice）
    voice: dict[str, Any] = Field(default_factory=dict)


class PersonaListResponse(BaseModel):
    """GET /personas 回應"""
    personas: list[PersonaSummary]
    current_default: str = "siro-default"


class ErrorResponse(BaseModel):
    """錯誤回應"""
    error: str
    detail: Optional[str] = None


# ============================================================
# v1.0 Core Experience Phase 1: TTS schemas
# 設計見 docs/TTS_INTEGRATION.md
# ============================================================

class TTSRequest(BaseModel):
    """TTS 合成請求 (POST /tts/synthesize)"""
    text: str = Field(..., min_length=1, max_length=5000, description="要唸的文字")
    voice_id: str = Field(
        "zh-TW-HsiaoChenNeural",
        description="聲線 ID (跨 provider 命名,見 bridge/tts/voices.py:DEFAULT_VOICES)",
    )
    language: str = Field("zh-TW", description="BCP-47 語言標籤")
    provider: str = Field(
        "edge-tts",
        description="TTS provider: edge-tts | piper | gpt-sovits",
    )
    speed: float = Field(1.0, ge=0.5, le=2.0, description="語速倍率 0.5-2.0")
    pitch: float = Field(0.0, ge=-10.0, le=10.0, description="音調 ±10 semitones")
    format: str = Field("mp3", description="音檔格式: mp3 | opus | wav")
    # GPT-SoVITS 專用(可選)
    refer_wav_path: Optional[str] = Field(None, description="GPT-SoVITS 參考音檔路徑")


class TTSResponse(BaseModel):
    """TTS 合成回應"""
    audio_base64: str = Field(..., description="音檔 base64 編碼(給 Unity 端 AudioClip 解碼)")
    format: str = Field(..., description="音檔格式")
    duration_ms: Optional[int] = Field(None, description="音檔長度 (ms,估算)")
    provider: str = Field(..., description="實際使用的 TTS provider")
    voice_id: str = Field(..., description="實際使用的 voice_id")
    chunks: int = Field(1, description="串流 chunks 數(debug 用)")
    text_len: int = Field(0, description="輸入文字長度(debug 用)")


class TTSVoiceInfo(BaseModel):
    """單一聲線資訊 (GET /tts/voices 回應的 element)"""
    id: str
    name: str
    language: str
    gender: str = "unknown"
    provider: str = ""
    preview_url: Optional[str] = None


class TTSVoicesResponse(BaseModel):
    """GET /tts/voices 回應"""
    provider: str = Field("", description="查詢的 provider 名稱")
    voices: list[TTSVoiceInfo] = Field(default_factory=list)
    active_provider: Optional[str] = Field(None, description="目前自動選擇的 provider (給 Unity 端用)")
    language_filter: Optional[str] = Field(None, description="查詢時的 language 過濾")
