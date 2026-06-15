"""
bridge/tts/piper_tts.py - Tier 2: Piper TTS (本地、ONNX、無網路 fallback)

Piper 是 RHASSpy 出的本地 TTS、用 ONNX 推論:
- 不需 GPU、CPU 跑
- 模型 ~100MB
- 聲線品質中等(比 edge-tts 差、但完全離線)
- 語音 ID 格式:`{lang}_{region}-{name}-{quality}`

範例: `zh_TW-hsiaochen-medium`

跟 edge-tts 命名不同(底線 vs 連字符、locale 大小寫),我們用 voices.py 做 mapping。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider, Voice

logger = logging.getLogger(__name__)


# Piper 模型預設路徑(透過 platform 抽象層)
def _default_models_dir() -> Path:
    try:
        from ..platform.paths import user_data_dir
        return user_data_dir(ensure=False) / "piper_models"
    except Exception:
        return Path.home() / ".local" / "share" / "siro" / "piper_models"


class PiperTTSProvider(TTSProvider):
    """Piper 本地 TTS via piper-tts 套件"""

    name = "piper"

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = models_dir or _default_models_dir()
        self._voices_cache: list[Voice] | None = None

    def _resolve_voice_path(self, voice_id: str) -> Path:
        """Piper 語音 ID → 對應的 .onnx 檔路徑

        慣例: models_dir/{voice_id}.onnx + {voice_id}.onnx.json
        """
        return self.models_dir / f"{voice_id}.onnx"

    async def synthesize(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        voice_path = self._resolve_voice_path(config.voice_id)
        if not voice_path.exists():
            raise FileNotFoundError(
                f"Piper 聲線模型找不到: {voice_path}\n"
                f"下載: python -m piper.download_voices {config.voice_id} "
                f"--outdir {self.models_dir}"
            )

        try:
            # piper-tts 1.3+ 提供 PiperVoice.load() 介面
            from piper import PiperVoice  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "piper-tts 套件沒裝,跑: pip install piper-tts"
            ) from e

        # Piper 推論是 sync、在 thread pool 跑避免 block event loop
        loop = asyncio.get_event_loop()

        def _synthesize_sync() -> bytes:
            voice = PiperVoice.load(str(voice_path))
            # synthesize() 回 WAV bytes (含 header)
            with voice.synthesize(text) as stream:
                wav_bytes = b"".join(stream)
            return wav_bytes

        # 整段合成後切成 chunk(避免一次吐太大 buffer)
        wav_bytes = await loop.run_in_executor(None, _synthesize_sync)
        chunk_size = 4096
        for i in range(0, len(wav_bytes), chunk_size):
            yield wav_bytes[i : i + chunk_size]

    async def list_voices(self, language: str = "") -> list[Voice]:
        """掃描 models_dir/ 列出所有 .onnx 檔

        (Piper 沒有像 edge-tts 的中央 API、要本地掃)
        """
        if self._voices_cache is not None:
            voices = self._voices_cache
        else:
            voices = []
            if self.models_dir.exists():
                for onnx in self.models_dir.glob("*.onnx"):
                    voice_id = onnx.stem
                    # 從 ID parse language(慣例: zh_TW-hsiaochen-medium)
                    # Piper 命名 = "{lang}_{region}-{name}-{quality}"
                    #   lang: 2 letter (zh, en, ja)
                    #   region: 2 letter (TW, CN, US, JP)
                    # 合併成 "zh_TW" 形式
                    lang = "unknown"
                    if "_" in voice_id:
                        parts = voice_id.split("_", 1)
                        lang = parts[0]
                        if len(parts) > 1 and len(parts[1]) >= 2 and parts[1][2] == "-":
                            lang = parts[0] + "_" + parts[1][:2]  # zh + TW
                    elif "-" in voice_id:
                        # 沒底線、用底線當 fallback(e.g. "en_US-amy-low" 才有底線)
                        lang = voice_id.split("-", 1)[0]
                    voices.append(
                        Voice(
                            id=voice_id,
                            name=voice_id,
                            language=lang,
                            gender="unknown",
                            provider=self.name,
                        )
                    )
            self._voices_cache = voices

        if language:
            return [v for v in voices if v.language.startswith(language)]
        return voices

    async def is_available(self) -> bool:
        """Piper 完全本地、不需網路、有模型就能用"""
        if not self.models_dir.exists():
            return False
        # 至少要有一個 .onnx 模型
        return any(self.models_dir.glob("*.onnx"))
