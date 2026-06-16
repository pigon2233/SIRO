"""tests.bridge.test_vad — SileroVAD event/state machine 測試(15 個 unit tests)。

對應 design: docs/STT_INTEGRATION.md §測試計畫 → test_vad.py。

策略:
- VADIterator / Silero model 用 mock(真模型只認真語音、synth audio 測不動)
- 測的是 SileroVAD 的 event 邏輯:PAUSE/RESUME yield、pre-buffer、dB gate、turn_id
"""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bridge.vad import SileroVAD, SileroVADConfig, VadEventType


# ============================================================
# 工具:synth_audio_chunk() 產生 16-bit PCM bytes
# ============================================================

def synth_audio_chunk(
    samples: int = 512,
    amplitude: float = 0.5,
    sample_rate: int = 16000,
) -> bytes:
    """合成 N 個 sample 的 sine wave 16-bit PCM bytes(預設 512 = 32ms @ 16kHz)。

    amplitude=0.0 → 靜音(< -inf dB)
    amplitude=0.5 → ~-6 dB
    """
    t = np.arange(samples) / sample_rate
    wave_f = np.sin(2 * np.pi * 440.0 * t) * amplitude
    pcm = (wave_f * 32767).astype(np.int16)
    return pcm.tobytes()


# ============================================================
# Fixtures
# ============================================================

class FakeVADIterator:
    """可控的 VADIterator mock。

    測試可以 push events(queue)→ feed() 進到時依序吐出。
    """

    def __init__(self, *args, **kwargs):
        self._events: deque = deque()
        self.reset_count = 0

    def __call__(self, audio_np):
        """每次呼叫 pop 一個 event(若 queue 有)。"""
        if self._events:
            return self._events.popleft()
        return None

    def reset_states(self):
        self.reset_count += 1

    def push(self, event: dict):
        """測試用:把要觸發的 event push 進 queue。"""
        self._events.append(event)

    def push_start(self, sample_ts: int = 0):
        self._events.append({"start": sample_ts})

    def push_end(self, sample_ts: int = 0):
        self._events.append({"end": sample_ts})


@pytest.fixture
def fake_vad_iterator():
    return FakeVADIterator()


@pytest.fixture
def vad(fake_vad_iterator) -> SileroVAD:
    """建 SileroVAD(dB gate 關掉方便純測 state machine)。"""
    with patch("bridge.vad.silero.load_silero_vad") as mock_load:
        mock_load.return_value = MagicMock()
        with patch("bridge.vad.silero.VADIterator", return_value=fake_vad_iterator):
            cfg = SileroVADConfig(db_threshold=-100)  # 關 dB gate
            yield SileroVAD(cfg)


@pytest.fixture
def vad_with_db_gate(fake_vad_iterator) -> SileroVAD:
    """dB gate 預設 60dB。"""
    with patch("bridge.vad.silero.load_silero_vad") as mock_load:
        mock_load.return_value = MagicMock()
        with patch("bridge.vad.silero.VADIterator", return_value=fake_vad_iterator):
            yield SileroVAD()


# ============================================================
# 1. 基本結構測試
# ============================================================

def test_vad_imports():
    """VAD module 公開 API 對。"""
    from bridge.vad import SileroVAD, SileroVADConfig, VadEvent, VadEventType, VADInterface
    assert SileroVAD is not None
    assert SileroVADConfig is not None
    assert VadEvent is not None
    assert VadEventType is not None
    assert VADInterface is not None


def test_vad_default_config():
    """預設 config 對齊 design。"""
    cfg = SileroVADConfig()
    assert cfg.sample_rate == 16000
    assert cfg.chunk_samples == 512
    assert cfg.prob_threshold == 0.4
    assert cfg.db_threshold == 60
    assert cfg.pre_buffer_chunks == 20


def test_vad_invalid_chunk_samples_raises():
    """不合法的 chunk_samples raise。"""
    with pytest.raises(ValueError):
        SileroVADConfig(chunk_samples=999)


def test_partial_chunk_ignored(vad: SileroVAD):
    """< 32ms 的 partial chunk 不處理、沒 event。"""
    tiny = b"\x00" * 100  # 50 samples = 不夠 512
    events = list(vad.feed(tiny, turn_id=1))
    assert events == []


# ============================================================
# 2. 靜音 / 噪音測試
# ============================================================

def test_silence_no_event(vad_with_db_gate: SileroVAD):
    """靜音(< 60dB)不觸發 PAUSE(進 pre-buffer 但不觸發)。"""
    chunk = b"\x00\x00" * 512
    for _ in range(50):
        events = list(vad_with_db_gate.feed(chunk, turn_id=1))
        assert events == []


def test_low_amplitude_below_db_threshold_ignored(vad_with_db_gate: SileroVAD):
    """音量低於 db_threshold(60dB)不觸發。"""
    chunk = synth_audio_chunk(amplitude=0.0001)
    events = list(vad_with_db_gate.feed(chunk, turn_id=1))
    assert events == []


# ============================================================
# 3. Speech 開始 / 結束
# ============================================================

def test_speech_start_emits_pause(vad: SileroVAD, fake_vad_iterator: FakeVADIterator):
    """VADIterator 回 start → 觸發 PAUSE event + turn_id。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    fake_vad_iterator.push_start(sample_ts=0)
    events = list(vad.feed(chunk, turn_id=42))
    assert len(events) == 1
    assert events[0].type == VadEventType.PAUSE
    assert events[0].turn_id == 42


def test_speech_end_emits_resume(vad: SileroVAD, fake_vad_iterator: FakeVADIterator):
    """VADIterator 先 start 再 end → PAUSE + RESUME events。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    # 1. Speech 開始
    fake_vad_iterator.push_start(sample_ts=0)
    list(vad.feed(chunk, turn_id=1))
    # 2. 累積幾個 chunk 到 buffer
    for _ in range(5):
        list(vad.feed(chunk, turn_id=1))
    # 3. Speech 結束
    fake_vad_iterator.push_end(sample_ts=4800)
    resume_events = list(vad.feed(chunk, turn_id=1))
    assert len(resume_events) == 1
    assert resume_events[0].type == VadEventType.RESUME
    assert resume_events[0].turn_id == 1
    assert resume_events[0].audio is not None
    assert len(resume_events[0].audio) > 0
    assert resume_events[0].duration_ms is not None
    assert resume_events[0].duration_ms > 0


def test_pause_event_has_no_audio(vad: SileroVAD, fake_vad_iterator: FakeVADIterator):
    """PAUSE event 不帶 audio(audio 留到 RESUME 一起出)。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    fake_vad_iterator.push_start()
    events = list(vad.feed(chunk, turn_id=1))
    assert len(events) == 1
    assert events[0].type == VadEventType.PAUSE
    assert events[0].audio is None
    assert events[0].duration_ms is None


# ============================================================
# 4. turn_id 傳遞
# ============================================================

def test_turn_id_propagation(vad: SileroVAD, fake_vad_iterator: FakeVADIterator):
    """event.turn_id 跟輸入 turn_id 同步(同一 utterance 用 first turn_id)。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    fake_vad_iterator.push_start()
    events = list(vad.feed(chunk, turn_id=12345))
    assert events[0].turn_id == 12345

    # 累積幾個 chunk(turn_id 變了)
    for _ in range(3):
        list(vad.feed(chunk, turn_id=12346))
    # 結束時 RESUME 用 speech_start_turn_id(12345)
    fake_vad_iterator.push_end()
    resume = list(vad.feed(chunk, turn_id=12347))
    assert resume[0].turn_id == 12345  # 對齊開始時的 turn_id


# ============================================================
# 5. State machine 行為
# ============================================================

def test_reset_clears_state(vad: SileroVAD, fake_vad_iterator: FakeVADIterator):
    """reset() → VADIterator.reset_states() 被呼叫、speech buffer 清空。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    fake_vad_iterator.push_start()
    list(vad.feed(chunk, turn_id=1))
    assert fake_vad_iterator.reset_count == 0
    vad.reset()
    assert fake_vad_iterator.reset_count == 1


def test_no_event_when_vaditerator_returns_none(vad: SileroVAD):
    """VADIterator return None → 沒 event(只是 buffer 累積)。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    for _ in range(20):
        events = list(vad.feed(chunk, turn_id=1))
        assert events == []


def test_speech_buffer_accumulates_between_start_and_end(
    vad: SileroVAD, fake_vad_iterator: FakeVADIterator
):
    """start 後 VAD 還沒 end → buffer 累積 chunks。"""
    chunk = synth_audio_chunk(amplitude=0.3)
    fake_vad_iterator.push_start()
    list(vad.feed(chunk, turn_id=1))
    # 累積 5 個 chunk
    for _ in range(5):
        list(vad.feed(chunk, turn_id=1))
    # end → audio 應有 7 個 chunk * 1024 bytes = 7168 bytes
    fake_vad_iterator.push_end()
    resume = list(vad.feed(chunk, turn_id=1))
    assert resume[0].audio is not None
    # 6 chunks in buffer(1 進 + 5 累積)+ 1 final = 7 chunks * 1024 bytes
    assert len(resume[0].audio) == 7 * 1024


# ============================================================
# 6. 進階 / 整合
# ============================================================

def test_db_calculation_helper():
    """靜音的 dB 是 -inf。"""
    chunk = b"\x00\x00" * 512
    db = SileroVAD._calculate_db(chunk)
    assert db == float("-inf")


def test_db_calculation_loud():
    """滿載 sine wave dB 應該約 -3 dB(RMS = amplitude / sqrt(2))。"""
    chunk = synth_audio_chunk(amplitude=0.99)
    db = SileroVAD._calculate_db(chunk)
    # sine wave RMS = 0.99 / sqrt(2) = 0.7 → 20*log10(0.7) ≈ -3.1 dB
    assert -4 < db < -2


def test_duration_ms_calculation():
    """512 samples @ 16kHz = 32ms。"""
    duration = SileroVAD(SileroVADConfig())._estimate_duration_ms(num_chunks=5)
    assert duration == 5 * 32  # 160ms

    duration = SileroVAD(SileroVADConfig())._estimate_duration_ms(num_chunks=10)
    assert duration == 10 * 32  # 320ms
