"""
bridge/tts/base.py - TTSProvider 抽象介面

業務邏輯(LLM streaming / persona)只跟 TTSProvider Protocol 互動,
不直接 import edge-tts / piper / gpt-sovits。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class TTSConfig:
    """TTS 設定(從 persona 載入、可被 env var 覆寫)"""

    provider: str = "edge-tts"      # edge-tts | piper | gpt-sovits
    voice_id: str = "zh-TW-HsiaoChenNeural"  # 聲線 ID(看 provider 別有不同命名)
    language: str = "zh-TW"        # BCP-47 語言標籤
    speed: float = 1.0              # 0.5-2.0
    pitch: float = 0.0             # -10 ~ +10 (semitones,看 provider 支援)
    sample_rate: int = 16000        # 給 Unity 端 AudioClip 用
    format: str = "mp3"             # mp3 | opus | pcm
    extra: dict = field(default_factory=dict)  # provider 特定參數

    @classmethod
    def from_persona(cls, persona_config: dict) -> "TTSConfig":
        """從 persona YAML 載入 TTS 設定(persona['voice'] 段)"""
        voice = persona_config.get("voice", {})
        return cls(
            provider=voice.get("provider", "edge-tts"),
            voice_id=voice.get("model") or voice.get("voice_id") or "zh-TW-HsiaoChenNeural",
            language=persona_config.get("language", "zh-TW"),
            speed=voice.get("speed", 1.0),
            pitch=voice.get("pitch", 0.0),
        )


@dataclass
class Voice:
    """單一聲線資訊"""

    id: str                        # 該 provider 內唯一 ID
    name: str                      # 人類可讀名稱(給 UI dropdown)
    language: str                  # BCP-47
    gender: str = "unknown"        # male | female | unknown
    provider: str = ""             # 哪個 provider
    preview_url: str = ""          # 預覽音檔 URL(optional)


@runtime_checkable
class TTSProvider(Protocol):
    """TTS provider 抽象介面

    每個實作(edge_tts / piper_tts / gpt_sovits)都要符合這個 Protocol。
    """

    name: str

    async def synthesize(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        """串流合成語音

        Args:
            text: 要唸的文字
            config: TTS 設定(provider/voice_id/language/speed 等)

        Yields:
            audio chunks (config.format 編碼、典型 mp3 16kHz mono)
        """
        ...

    async def list_voices(self, language: str = "") -> list[Voice]:
        """列出可用聲線(給 UI dropdown / persona 設定)

        Args:
            language: 過濾語言(空字串 = 全部)
        """
        ...

    async def is_available(self) -> bool:
        """檢查 provider 能不能用(網路 / API key / 本地 binary)"""
        ...
