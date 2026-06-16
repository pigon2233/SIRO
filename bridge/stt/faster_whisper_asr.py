"""bridge.stt.faster_whisper_asr — faster-whisper 實作(對應 design §`bridge/stt/faster_whisper_asr.py`)。

對應 source: O-LLVT asr/faster_whisper_asr.py(同步版)、SIRO 改成 async + 加 AsrResult dataclass。

設計:
- `FasterWhisperAsr` 接受 model_size("small" 預設,繁中品質 + 速度平衡)
- `transcribe` 走 `asyncio.to_thread` 避免 block event loop
- 自動 language detect + 接受 persona hint
- 計算 avg_logprob 作為 confidence proxy
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import numpy as np
from loguru import logger

from .asr_interface import ASRInterface


@dataclass
class AsrResult:
    """STT 結果。

    Attributes:
        text: 轉錄出來的文字。
        language: 偵測到的語言("zh" / "en" / ...)。None 代表 whisper 沒給。
        confidence: 信心度 0-1(用 avg_logprob 估)。
    """

    text: str
    language: str | None = None
    confidence: float = 0.0


class FasterWhisperAsr(ASRInterface):
    """faster-whisper backend(Phase 2 default)。

    用法:
        asr = FasterWhisperAsr(model_size="small", device="auto", compute_type="int8")
        result = await asr.transcribe(audio_np, hint_language="zh")
        print(result.text, result.language, result.confidence)
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        download_root: str | None = None,
        beam_size: int = 5,
    ):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._download_root = download_root
        self._beam_size = beam_size
        self._model = None
        self._init_error: str | None = None

        # 嘗試載入 model(延遲到第一次 transcribe 之前也 OK,call is_available 觸發)
        try:
            self._load_model()
        except Exception as e:
            # 不要炸 — STT 可能暫時不可用、user 還是可以打字
            logger.warning(f"FasterWhisperAsr init failed: {e}")
            self._init_error = str(e)

    def _load_model(self) -> None:
        """載入 faster-whisper model(同步,在 __init__ 跑一次)。"""
        from faster_whisper import WhisperModel  # lazy import(避免強制 deps)

        logger.info(
            f"Loading faster-whisper model: size={self._model_size} "
            f"device={self._device} compute={self._compute_type}"
        )
        # 預設 cache 到 HF hub 標準位置
        # download_root 可指定自訂位置(測試 / 離線模式用)
        download_root = self._download_root or os.environ.get("SIRO_WHISPER_CACHE")

        self._model = WhisperModel(
            model_size_or_path=self._model_size,
            device=self._device,
            compute_type=self._compute_type,
            download_root=download_root,
        )
        logger.info(f"faster-whisper model loaded: {self._model_size}")

    async def transcribe(
        self, audio: np.ndarray, hint_language: str | None = None
    ) -> AsrResult:
        """非同步轉錄(背景 thread pool,避免 block event loop)。

        Args:
            audio: float32 numpy 範圍 [-1, 1],16kHz mono。
            hint_language: 可選 hint("zh" / "en")。

        Returns:
            AsrResult(text/language/confidence)。
        """
        if self._model is None:
            # 嘗試重 load
            try:
                self._load_model()
            except Exception as e:
                logger.error(f"faster-whisper load failed: {e}")
                return AsrResult(text="", language=None, confidence=0.0)

        # 確保 float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # 走 thread pool 避免 block
        return await asyncio.to_thread(self._transcribe_sync, audio, hint_language)

    def _transcribe_sync(
        self, audio: np.ndarray, hint_language: str | None
    ) -> AsrResult:
        """同步轉錄(給 to_thread 包)。"""
        try:
            segments, info = self._model.transcribe(
                audio,
                beam_size=self._beam_size,
                language=hint_language if hint_language else None,
                condition_on_previous_text=False,
            )
        except Exception as e:
            logger.error(f"faster-whisper transcribe error: {e}")
            return AsrResult(text="", language=None, confidence=0.0)

        # 收 segments
        texts: list[str] = []
        logprobs: list[float] = []
        for seg in segments:
            texts.append(seg.text)
            if seg.avg_logprob is not None:
                logprobs.append(seg.avg_logprob)

        text = "".join(texts).strip()
        # logprob 範圍通常 -1 ~ 0,轉 0-1 confidence
        confidence = float(np.exp(np.mean(logprobs))) if logprobs else 0.0
        # 限制範圍
        confidence = max(0.0, min(1.0, confidence))

        return AsrResult(
            text=text,
            language=info.language if info else None,
            confidence=confidence,
        )

    def is_available(self) -> bool:
        """檢查 model 載入狀態。"""
        return self._model is not None

    @property
    def init_error(self) -> str | None:
        """初始化錯誤訊息(若有的話)。"""
        return self._init_error
