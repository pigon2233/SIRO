"""
bridge/models.py - Pydantic schemas for SIRO bridge API
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class Emotion(str, Enum):
    """支援的情緒種類（v0 鎖定 7 種）"""
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    THINKING = "thinking"
    EXCITED = "excited"
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


class ErrorResponse(BaseModel):
    """錯誤回應"""
    error: str
    detail: Optional[str] = None
