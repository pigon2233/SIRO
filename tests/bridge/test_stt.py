"""tests.bridge.test_stt — faster-whisper STT 測試(10 個 unit tests)。

對應 design: docs/STT_INTEGRATION.md §測試計畫 → test_stt.py。

策略:
- 真正的 faster-whisper 模型載入要 100MB+,CI 跑很慢 → 大部分 test 用 mock
- 1 個 integration test 真的載入(標記 slow、本地跑)
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bridge.stt import AsrResult, FasterWhisperAsr


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_whisper_model():
    """Mock faster_whisper.WhisperModel.transcribe() 回傳 mock segments。"""
    fake_segment = MagicMock()
    fake_segment.text = "你好"
    fake_segment.avg_logprob = -0.3  # confidence ≈ exp(-0.3) ≈ 0.74

    fake_info = MagicMock()
    fake_info.language = "zh"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([fake_segment]), fake_info)
    return mock_model


# ============================================================
# 1. 結構 / API
# ============================================================

def test_stt_module_imports():
    """STT module 公開 API 對。"""
    from bridge.stt import ASRInterface, AsrResult, FasterWhisperAsr
    assert ASRInterface is not None
    assert AsrResult is not None
    assert FasterWhisperAsr is not None


def test_asr_result_dataclass():
    """AsrResult 欄位齊全 + 預設值。"""
    r = AsrResult(text="hello", language="en", confidence=0.9)
    assert r.text == "hello"
    assert r.language == "en"
    assert r.confidence == 0.9

    r2 = AsrResult(text="")
    assert r2.text == ""
    assert r2.language is None
    assert r2.confidence == 0.0


# ============================================================
# 2. Mock transcribe
# ============================================================

def test_transcribe_chinese_mocked(mock_whisper_model):
    """Mock 出中文轉錄。"""

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_whisper_model):
            asr = FasterWhisperAsr(model_size="small")
            audio = np.zeros(16000, dtype=np.float32)  # 1s silence
            result = await asr.transcribe(audio, hint_language="zh")
            return result

    result = asyncio.run(run())
    assert result.text == "你好"
    assert result.language == "zh"
    assert 0.0 < result.confidence < 1.0


def test_transcribe_empty_audio_mocked():
    """空音訊 → AsrResult empty。"""
    fake_segment = MagicMock()
    fake_segment.text = ""
    fake_segment.avg_logprob = None
    fake_info = MagicMock()
    fake_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([fake_segment]), fake_info)

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperAsr(model_size="small")
            audio = np.zeros(100, dtype=np.float32)
            return await asr.transcribe(audio)

    result = asyncio.run(run())
    assert result.text == ""


def test_transcribe_multiple_segments_concat():
    """多個 segments 串接。"""
    seg1 = MagicMock(text="你好 ", avg_logprob=-0.5)
    seg2 = MagicMock(text="世界", avg_logprob=-0.4)
    fake_info = MagicMock(language="zh")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([seg1, seg2]), fake_info)

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperAsr(model_size="small")
            return await asr.transcribe(np.zeros(16000, dtype=np.float32), hint_language="zh")

    result = asyncio.run(run())
    assert "你好" in result.text
    assert "世界" in result.text


# ============================================================
# 3. Language handling
# ============================================================

def test_transcribe_auto_language_no_hint():
    """不指定 language → auto detect(info.language 由 whisper 回)。"""
    fake_segment = MagicMock(text="hello", avg_logprob=-0.2)
    fake_info = MagicMock(language="en")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([fake_segment]), fake_info)

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperAsr(model_size="small")
            return await asr.transcribe(np.zeros(8000, dtype=np.float32))

    result = asyncio.run(run())
    assert result.language == "en"
    # 確認 whisper.transcribe 收到 language=None(讓它 auto)
    call_kwargs = mock_model.transcribe.call_args.kwargs
    assert call_kwargs["language"] is None


def test_transcribe_with_hint_language():
    """指定 hint_language → 傳進 whisper.transcribe。"""
    fake_segment = MagicMock(text="你好", avg_logprob=-0.3)
    fake_info = MagicMock(language="zh")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([fake_segment]), fake_info)

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperAsr(model_size="small")
            await asr.transcribe(np.zeros(8000, dtype=np.float32), hint_language="zh")
            # Check call

    asyncio.run(run())
    call_kwargs = mock_model.transcribe.call_args.kwargs
    assert call_kwargs["language"] == "zh"


# ============================================================
# 4. error handling
# ============================================================

def test_transcribe_error_returns_empty():
    """whisper.transcribe 拋例外 → 回 AsrResult empty(不 crash)。"""
    mock_model = MagicMock()
    mock_model.transcribe.side_effect = RuntimeError("whisper fail")

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperAsr(model_size="small")
            return await asr.transcribe(np.zeros(100, dtype=np.float32))

    result = asyncio.run(run())
    assert result.text == ""
    assert result.confidence == 0.0


def test_init_failure_does_not_raise():
    """model 載入失敗不要 raise(讓 caller 還能 import + 知道 unavailable)。"""
    with patch("faster_whisper.WhisperModel", side_effect=RuntimeError("no model")):
        asr = FasterWhisperAsr(model_size="nonexistent")
        assert asr.is_available() is False
        assert asr.init_error is not None


def test_audio_dtype_conversion():
    """int16 audio 自動轉 float32。"""
    fake_segment = MagicMock(text="hi", avg_logprob=-0.1)
    fake_info = MagicMock(language="en")
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([fake_segment]), fake_info)

    async def run():
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperAsr(model_size="small")
            # 給 int16 音訊(不是 float32)
            audio_int = np.zeros(100, dtype=np.int16)
            return await asr.transcribe(audio_int)

    result = asyncio.run(run())
    assert result.text == "hi"
    # 確認 whisper 收到的是 float32
    call_args = mock_model.transcribe.call_args.args
    assert call_args[0].dtype == np.float32


def test_is_available_after_init(mock_whisper_model):
    """init 成功後 is_available() True。"""
    with patch("faster_whisper.WhisperModel", return_value=mock_whisper_model):
        asr = FasterWhisperAsr(model_size="small")
        assert asr.is_available() is True
