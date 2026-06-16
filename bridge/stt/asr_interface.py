"""ASR abstract interface — SIRO 可換 STT backend(whisper / 其他雲端)。"""

from __future__ import annotations

import abc

import numpy as np


class ASRInterface(abc.ABC):
    """STT 抽象介面。

    設計原則:
    - async transcribe 避免 block event loop。
    - 接收 float32 numpy(`[-1, 1]` 範圍)。
    - 回 AsrResult(text + language + confidence)。
    """

    SAMPLE_RATE: int = 16000
    NUM_CHANNELS: int = 1

    @abc.abstractmethod
    async def transcribe(
        self, audio: np.ndarray, hint_language: str | None = None
    ) -> "AsrResult":
        """非同步轉錄音訊。

        Args:
            audio: float32 numpy,範圍 [-1, 1],16kHz mono。
            hint_language: 可選的語言 hint("zh" / "en"),加速 whisper 推論。

        Returns:
            AsrResult: 文字 + 偵測語言 + 信心度。
        """
        raise NotImplementedError

    @abc.abstractmethod
    def is_available(self) -> bool:
        """檢查 backend 是否可用(model 載入 / 網路 OK)。"""
        raise NotImplementedError
