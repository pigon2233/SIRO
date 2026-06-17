"""bridge.vad.silero — Silero VAD v6 wrapper(Pattern 1 完整實作)。

對應 design: docs/STT_INTEGRATION.md §`bridge/vad/silero.py` Pattern 1。
對應 source: O-LLVT vad/silero.py(演算法 port,v6 API 跟 v4 不同所以沒法直接 import)。

設計:
- 用 `silero_vad.VADIterator`(v6 內建)做核心 VAD state machine
- 上面再包 dB gate(避免環境噪音誤觸)
- yield `VadEvent` 給 caller(turn_id + audio bytes + duration_ms)
- 維護 20-chunk pre-buffer(PAUSE event 帶的 audio 包含 PAUSE 之前的 0.64s 緩衝)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field, model_validator

try:
    from silero_vad import VADIterator, load_silero_vad
except ImportError as e:
    raise ImportError(
        "silero-vad not installed. Run: pip install silero-vad"
    ) from e


class VadEventType(Enum):
    """VAD 事件類型。對應 design §訊息 schema。"""

    PAUSE = "pause"      # speech start(speech 從無到有)
    RESUME = "resume"    # utterance end(speech 從有到無 + 完整 audio buffer)


@dataclass
class VadEvent:
    """VAD 事件。

    Attributes:
        type: PAUSE / RESUME。
        turn_id: 從 Unity 來的 mic chunk 編號(用於 correlate 哪些音是誰講的)。
        audio: 16-bit PCM bytes,只有 RESUME 有值(PAUSE 不帶 audio、pre-buffer 留著等 RESUME 一起出)。
        duration_ms: speech 持續時間(只在 RESUME 有)。
    """

    type: VadEventType
    turn_id: int
    audio: Optional[bytes] = None
    duration_ms: Optional[int] = None


class SileroVADConfig(BaseModel):
    """Silero VAD 設定。對應 O-LLVT SileroVADConfig。"""

    # 音訊格式
    sample_rate: int = Field(default=16000, description="音訊取樣率(Hz)")
    chunk_samples: int = Field(default=512, description="每塊 sample 數(16kHz 32ms = 512)")

    # Silero VADIterator 參數
    prob_threshold: float = Field(default=0.3, description="speech probability 門檻")
    min_silence_duration_ms: int = Field(
        default=700,
        description="靜音超過此 ms 才算 utterance 結束(24 chunks @ 32ms ≈ 768ms)",
    )
    speech_pad_ms: int = Field(default=100, description="speech 邊界 pad ms")

    # SIRO 加的 dB gate(避免環境噪音誤觸)
    # Day 8.8 fix:60 太高 → 40 → 25(繼續調降,看 mic 實際音量到底多少)
    db_threshold: int = Field(default=25, description="RMS dB 門檻、低於此不算 speech")

    # Pre-buffer:PAUSE 前保留 N 個 chunk(0.64s @ 32ms = 20 chunks)
    pre_buffer_chunks: int = Field(default=20, description="PAUSE 前保留的 chunk 數")

    @model_validator(mode="after")
    def _check_chunk_samples(self):
        if self.chunk_samples not in (256, 512, 768, 1024):
            raise ValueError(
                f"chunk_samples must be 256/512/768/1024, got {self.chunk_samples}"
            )
        return self


class SileroVAD:
    """Silero VAD wrapper(Pattern 1 完整實作)。

    用法:
        vad = SileroVAD()
        for event in vad.feed(audio_bytes, turn_id=1):
            if event.type == VadEventType.PAUSE:
                ...
            elif event.type == VadEventType.RESUME:
                process(event.audio, event.duration_ms)
    """

    def __init__(self, config: Optional[SileroVADConfig] = None):
        self.config = config or SileroVADConfig()
        # Sanity check 已經在 SileroVADConfig.model_validator 跑過

        # 載入 Silero VAD model(v6)
        logger.info("Loading Silero-VAD model (v6, onnx)...")
        model = load_silero_vad(onnx=True)

        # VADIterator 處理 core state machine(threshold / min_silence / speech_pad)
        self._iterator = VADIterator(
            model,
            threshold=self.config.prob_threshold,
            sampling_rate=self.config.sample_rate,
            min_silence_duration_ms=self.config.min_silence_duration_ms,
            speech_pad_ms=self.config.speech_pad_ms,
        )

        # Pre-buffer:最近 20 個 chunk(PAUSE event 之前 0.64s)
        self._pre_buffer: deque[bytes] = deque(maxlen=self.config.pre_buffer_chunks)

        # Active speech 累積 buffer(RESUME event 才 yield)
        self._speech_buffer: list[bytes] = []
        self._speech_start_turn_id: Optional[int] = None
        self._is_speaking: bool = False
        # Day 8.8 debug:印 mic 收到的實際 dB(每 32 chunk = 1 秒印一次、避免 spam)
        self._db_log_counter: int = 0

    def feed(self, audio_chunk: bytes, turn_id: int) -> Iterator[VadEvent]:
        """吃一個 32ms 16-bit PCM mono chunk、yield 0~N 個 VadEvent。

        Args:
            audio_chunk: 16-bit PCM 16kHz mono,1024 bytes(512 samples * 2 bytes)。
            turn_id: 從 Unity 來的 mic chunk 編號(用於事件標記)。

        Yields:
            VadEvent: PAUSE / RESUME。
        """
        expected_bytes = self.config.chunk_samples * 2  # 16-bit = 2 bytes/sample
        if len(audio_chunk) < expected_bytes:
            # Partial chunk(可能 Unity 第一次 buffer 還沒滿)— 忽略、累積到下次
            return

        # dB gate(避免環境噪音)
        rms_db = self._calculate_db(audio_chunk)
        # Day 8.8 debug:每 32 chunk 印一次平均 dB(讓 user 知道 mic 實際音量)
        self._db_log_counter += 1
        if self._db_log_counter % 32 == 1 and not self._is_speaking:
            gate_status = "通過" if rms_db >= self.config.db_threshold else f"擋下(<{self.config.db_threshold})"
            logger.info(
                f"🔊 [vad] mic dB={rms_db:.1f} (gate={self.config.db_threshold}dB) {gate_status}"
            )
        if rms_db < self.config.db_threshold and not self._is_speaking:
            # 靜音 + 不在 speech 中 → 不送進 VAD、保留進 pre-buffer
            self._pre_buffer.append(audio_chunk)
            return

        # 轉 float32 給 Silero(範圍 [-1, 1])
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0

        # 跑 VADIterator:return None / {"start": ts} / {"end": ts}
        try:
            result = self._iterator(audio_np)
        except Exception as e:
            logger.warning(f"Silero VAD feed error: {e}")
            return

        if result is None:
            # 沒 boundary
            if self._is_speaking:
                self._speech_buffer.append(audio_chunk)
            else:
                self._pre_buffer.append(audio_chunk)
            return

        # 有 boundary
        if "start" in result:
            # Speech 開始 → 累積 pre-buffer + 本 chunk → yield PAUSE
            self._is_speaking = True
            self._speech_start_turn_id = turn_id
            self._speech_buffer = list(self._pre_buffer) + [audio_chunk]
            self._pre_buffer.clear()
            logger.debug(
                f"🎙️ VAD PAUSE turn_id={turn_id} prob_start@{result['start']}"
            )
            yield VadEvent(type=VadEventType.PAUSE, turn_id=turn_id)

        elif "end" in result:
            # Speech 結束 → 收尾 buffer + yield RESUME
            self._speech_buffer.append(audio_chunk)
            full_audio = b"".join(self._speech_buffer)
            duration_ms = self._estimate_duration_ms(len(self._speech_buffer))
            start_turn = self._speech_start_turn_id or turn_id

            self._is_speaking = False
            self._speech_buffer = []
            self._speech_start_turn_id = None
            logger.debug(
                f"🔇 VAD RESUME turn_id={start_turn} "
                f"duration={duration_ms}ms chunks={len(self._speech_buffer)}"
            )
            yield VadEvent(
                type=VadEventType.RESUME,
                turn_id=start_turn,
                audio=full_audio,
                duration_ms=duration_ms,
            )
            self._iterator.reset_states()

    @staticmethod
    def _calculate_db(audio_chunk: bytes) -> float:
        """計算 16-bit PCM chunk 的 RMS dB。"""
        samples = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples ** 2)))
        if rms <= 0:
            return -math.inf
        return 20.0 * math.log10(rms)

    def _estimate_duration_ms(self, num_chunks: int) -> int:
        """從 chunk 數推算 duration ms。"""
        chunk_ms = int(self.config.chunk_samples * 1000 / self.config.sample_rate)
        return num_chunks * chunk_ms

    def reset(self) -> None:
        """強制 reset state(例如 barge-in 取消舊 utterance)。"""
        self._iterator.reset_states()
        self._pre_buffer.clear()
        self._speech_buffer = []
        self._speech_start_turn_id = None
        self._is_speaking = False
