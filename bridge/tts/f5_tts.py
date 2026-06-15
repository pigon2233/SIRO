"""
bridge/tts/f5_tts.py - Tier 1.5: F5-TTS 本地高品質 TTS (Phase 1.5)

F5-TTS 是 2024 上海交大開源的 zero-shot voice clone TTS:
- 不需訓練、用 6-30 秒 ref_audio + 對應文字就能 clone 聲線
- 品質「像真人在講話」、明顯比 edge-tts 雲端好
- 本地推論、不需網路(有網路只為了第一次下 model weights)
- 速度: GPU 3-5s/句、CPU 10-20s/句

跟 edge-tts / piper 命名差異:
- voice_id 是任意命名(mao-clone、user-clone、...)
- ref_audio / ref_text 透過 TTSConfig.extra 帶
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider, Voice

logger = logging.getLogger(__name__)


# Lazy import — F5-TTS 沒裝時 is_available() 回 False、不影響其他 provider
def _try_import_f5tts():
    try:
        from f5_tts.api import F5TTS  # type: ignore[import-not-found]

        return F5TTS
    except ImportError:
        return None


def _try_import_soundfile():
    try:
        import soundfile as sf  # type: ignore[import-not-found]

        return sf
    except ImportError:
        return None


# F5-TTS model 預設 ref audio 路徑
def _default_refs_dir() -> Path:
    try:
        from ..platform.paths import user_data_dir

        return user_data_dir(ensure=False) / "f5_tts_refs"
    except Exception:
        return Path.home() / ".local" / "share" / "siro" / "f5_tts_refs"


class F5TTSProvider(TTSProvider):
    """F5-TTS 本地 TTS via f5-tts 套件"""

    name = "f5-tts"

    def __init__(self, refs_dir: Path | None = None) -> None:
        self.refs_dir = refs_dir or _default_refs_dir()
        self._f5tts = None  # lazy: F5TTS() 第一次 synthesize 才 instantiate

    def _get_f5tts(self):
        """Lazy load F5TTS() — 第一次用才 instantiate、之後 cache

        首次 instantiate 要 5-10s(model load + GPU init)、用一次後快取。
        """
        if self._f5tts is None:
            F5TTS = _try_import_f5tts()
            if F5TTS is None:
                raise RuntimeError(
                    "F5-TTS 套件沒裝,跑: pip install f5-tts"
                )
            self._f5tts = F5TTS()
        return self._f5tts

    async def synthesize(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        if not text or not text.strip():
            return

        # 驗證必要欄位
        ref_audio = config.extra.get("ref_audio")
        ref_text = config.extra.get("ref_text", "")
        if not ref_audio:
            raise ValueError(
                "F5-TTS 需要 ref_audio (在 TTSConfig.extra['ref_audio'] 帶路徑)"
            )
        ref_path = Path(ref_audio)
        if not ref_path.exists():
            raise FileNotFoundError(
                f"F5-TTS ref_audio 找不到: {ref_path}\n"
                f"請提供 6-30 秒 .wav 檔 (清晰、無背景噪音) + 對應 ref_text"
            )
        if not ref_text:
            raise ValueError(
                "F5-TTS 需要 ref_text (ref_audio 對應的文字, 跟要 clone 出的內容一致)"
            )

        sf = _try_import_soundfile()
        if sf is None:
            raise RuntimeError(
                "soundfile 套件沒裝,跑: pip install soundfile"
            )

        # 推論在 thread pool 跑(避免 block event loop)
        loop = asyncio.get_event_loop()
        f5 = self._get_f5tts()

        def _synthesize_sync() -> bytes:
            wav, sr, _spec = f5.infer(
                ref_file=str(ref_path),
                ref_text=ref_text,
                gen_text=text,
                speed=config.speed,
                nfe_step=config.extra.get("nfe_step", 32),
                cfg_strength=config.extra.get("cfg_strength", 2.0),
            )
            # wav → WAV bytes(整段, 然後切成 chunk yield)
            buf = io.BytesIO()
            sf.write(buf, wav, sr, format="WAV")
            return buf.getvalue()

        wav_bytes = await loop.run_in_executor(None, _synthesize_sync)
        chunk_size = 4096
        for i in range(0, len(wav_bytes), chunk_size):
            yield wav_bytes[i : i + chunk_size]

    async def list_voices(self, language: str = "") -> list[Voice]:
        """F5-TTS 沒有「內建 voice」(是 zero-shot clone),列出 refs_dir 裡的 .wav

        每個 ref_audio 檔就是一個「voice」(persona YAML 用 voice_id 對應 ref_audio)。
        """
        voices: list[Voice] = []
        if self.refs_dir.exists():
            for wav in self.refs_dir.glob("*.wav"):
                voice_id = wav.stem
                voices.append(
                    Voice(
                        id=voice_id,
                        name=f"{voice_id} (F5-TTS clone)",
                        language=language or "zh-TW",
                        gender="unknown",
                        provider=self.name,
                    )
                )
        return voices

    async def is_available(self) -> bool:
        """F5-TTS 套件裝了 + refs_dir 有至少一個 .wav 就能用"""
        F5TTS = _try_import_f5tts()
        if F5TTS is None:
            return False
        if not self.refs_dir.exists():
            return False
        return any(self.refs_dir.glob("*.wav"))
