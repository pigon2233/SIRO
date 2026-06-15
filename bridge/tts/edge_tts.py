"""
bridge/tts/edge_tts.py - Tier 1: Microsoft Edge TTS (雲端、免費、預設)

API: edge-tts Python 套件
- 不需 API key
- 透過 WebSocket 連 Microsoft 公開 endpoint
- 100+ 聲線(中/英/日/韓都有)
- 輸出 MP3 (mp3 預設 24kHz mono)

聲線 ID 格式:`{language}-{region}-{Name}Neural`
- zh-TW-HsiaoChenNeural (繁中 女 曉曉)
- zh-TW-HsiaoJhenNeural (繁中 男 曉正)
- zh-CN-XiaoxiaoNeural (簡中 女 小小)
- en-US-JennyNeural (英文 女 Jenny)
- ja-JP-NanamiNeural (日文 女 七海)

完整清單:`async for v in edge_tts.list_voices(): print(v)`
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider, Voice

logger = logging.getLogger(__name__)


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge TTS via edge-tts 套件"""

    name = "edge-tts"

    def __init__(self) -> None:
        self._voices_cache: list[Voice] | None = None

    async def synthesize(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        """串流合成

        edge-tts 用 Communicate.stream() 拿 MP3 bytes。
        我們 yield 每個 chunk 給上層、buffer 跟 bytes 切割交給 caller。
        """
        try:
            import edge_tts  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "edge-tts 套件沒裝,跑: pip install edge-tts"
            ) from e

        # edge-tts 參數:voice + rate + pitch + volume
        # rate: '+0%' (default), '+10%' (快 10%), '-10%' (慢 10%)
        # pitch: '+0Hz' (default), '+5Hz' (高), '-5Hz' (低)
        rate = f"+{int((config.speed - 1.0) * 100)}%"
        pitch = f"+{int(config.pitch * 5)}Hz"
        voice = config.voice_id
        if not voice.endswith("Neural") and not voice.endswith("Multilingual"):
            # 自動補 Neural 結尾(常見 user 漏打)
            voice = voice + "Neural"

        logger.info(
            f"[edge_tts] synthesize voice={voice} lang={config.language} "
            f"rate={rate} pitch={pitch} text_len={len(text)}"
        )

        comm = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )

        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
            elif chunk["type"] == "WordBoundary":
                # 單字邊界資訊(給 lipsync 用、目前先忽略)
                pass
            elif chunk["type"] == "SentenceBoundary":
                pass
            elif chunk["type"] == "error":
                raise RuntimeError(
                    f"edge-tts 錯誤: {chunk.get('message', 'unknown')}"
                )

    async def list_voices(self, language: str = "") -> list[Voice]:
        """列出所有可用聲線(用 edge-tts 的 list_voices API)"""
        if self._voices_cache is not None:
            voices = self._voices_cache
        else:
            try:
                import edge_tts  # type: ignore[import-untyped]
            except ImportError as e:
                raise RuntimeError(
                    "edge-tts 套件沒裝,跑: pip install edge-tts"
                ) from e
            # edge-tts.list_voices() 是 sync function
            raw_voices = edge_tts.list_voices()
            voices = [
                Voice(
                    id=v["ShortName"],
                    name=v["FriendlyName"],
                    language=v["Locale"],
                    gender=v["Gender"].lower(),
                    provider=self.name,
                    preview_url=v.get("SampleRateHertz", ""),
                )
                for v in raw_voices
            ]
            self._voices_cache = voices

        if language:
            return [v for v in voices if v.language.startswith(language)]
        return voices

    async def is_available(self) -> bool:
        """檢查 edge-tts endpoint 可連

        簡單做法:送一個 tiny 請求看會不會 raise。
        """
        try:
            import edge_tts  # type: ignore[import-untyped]
            # 1 char 不會太長、純測連線
            comm = edge_tts.Communicate(text=".", voice="zh-TW-HsiaoChenNeural")
            # 只取第一個 chunk 就退出(不要真等整個音檔)
            async for _ in comm.stream():
                return True
            return True
        except Exception as e:
            logger.warning(f"[edge_tts] unavailable: {e}")
            return False
