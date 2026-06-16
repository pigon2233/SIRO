"""VAD abstract interface — SIRO 可換 VAD backend(Silero / WebRTC / 能量偵測)。

對應 design: docs/STT_INTEGRATION.md §`bridge/vad/vad_interface`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from .silero import VadEvent  # re-export type for convenience


class VADInterface(ABC):
    """Phase 2 VAD 抽象介面。

    設計原則:
    - feed() 接收 16-bit PCM bytes(16kHz mono 32ms = 1024 bytes 一塊)。
    - yield VadEvent(PAUSE / RESUME + turn_id + 可選 audio bytes)。
    - 每個 Unity 連線一個 instance(各自維持 pre-buffer 跟 state)。
    """

    @abstractmethod
    def feed(self, audio_chunk: bytes, turn_id: int) -> Iterator[VadEvent]:
        """吃一個 32ms 的 16-bit PCM mono chunk、yield 0~N 個 VadEvent。

        Args:
            audio_chunk: 16kHz 16-bit mono PCM,1024 bytes(= 512 samples @ 16kHz)。
            turn_id: 從 Unity 來的 mic chunk 編號(用於事件標記、correlate 哪些音是誰講的)。

        Yields:
            VadEvent: 可能 PAUSE(speech start)、RESUME(utterance end 含 audio)。
        """
        raise NotImplementedError
