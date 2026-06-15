"""
tests/bridge/test_f5_tts.py - F5-TTS provider mock tests (Phase 1.5)

跟 Phase 1 風格:mock 套件、測邏輯、不真的下 1.5GB model
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.tts.base import TTSConfig
from bridge.tts.f5_tts import F5TTSProvider


# ==================== Fixtures ====================


@pytest.fixture
def f5_provider(tmp_path: Path) -> F5TTSProvider:
    """建一個 refs_dir 有 2 個 wav 的 F5TTSProvider"""
    refs_dir = tmp_path / "f5_refs"
    refs_dir.mkdir()
    (refs_dir / "mao_zh.wav").write_bytes(b"fake wav 1")
    (refs_dir / "user_zh.wav").write_bytes(b"fake wav 2")
    return F5TTSProvider(refs_dir=refs_dir)


@pytest.fixture
def f5_provider_empty(tmp_path: Path) -> F5TTSProvider:
    """refs_dir 空的 provider"""
    refs_dir = tmp_path / "f5_refs_empty"
    refs_dir.mkdir()
    return F5TTSProvider(refs_dir=refs_dir)


@pytest.fixture
def f5_provider_no_dir(tmp_path: Path) -> F5TTSProvider:
    """refs_dir 不存在的 provider"""
    return F5TTSProvider(refs_dir=tmp_path / "nonexistent")


@pytest.fixture
def valid_config(tmp_path: Path) -> TTSConfig:
    """一個有 ref_audio + ref_text 的有效 TTSConfig"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"fake wav")
    return TTSConfig(
        provider="f5-tts",
        voice_id="mao-clone",
        language="zh-TW",
        speed=1.0,
        extra={"ref_audio": str(ref), "ref_text": "你好測試"},
    )


# ==================== TestF5TTSIsAvailable ====================


class TestF5TTSIsAvailable:
    @pytest.mark.asyncio
    async def test_available_when_installed_with_refs(self, f5_provider):
        """F5TTS 套件裝了 + refs_dir 有 wav → True"""
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            assert await f5_provider.is_available() is True

    @pytest.mark.asyncio
    async def test_not_available_when_f5tts_missing(self, f5_provider):
        """F5TTS 套件沒裝 → False (不爆)"""
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=None):
            assert await f5_provider.is_available() is False

    @pytest.mark.asyncio
    async def test_not_available_when_refs_dir_empty(self, f5_provider_empty):
        """F5TTS 裝了但 refs_dir 沒 wav → False"""
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            assert await f5_provider_empty.is_available() is False

    @pytest.mark.asyncio
    async def test_not_available_when_refs_dir_missing(self, f5_provider_no_dir):
        """refs_dir 不存在 → False"""
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            assert await f5_provider_no_dir.is_available() is False


# ==================== TestF5TTSListVoices ====================


class TestF5TTSListVoices:
    @pytest.mark.asyncio
    async def test_list_refs(self, f5_provider):
        """refs_dir 裡的每個 wav 是一個 voice"""
        voices = await f5_provider.list_voices(language="zh-TW")
        ids = {v.id for v in voices}
        assert ids == {"mao_zh", "user_zh"}
        for v in voices:
            assert v.provider == "f5-tts"
            assert v.language == "zh-TW"

    @pytest.mark.asyncio
    async def test_list_empty_when_no_refs(self, f5_provider_empty):
        voices = await f5_provider_empty.list_voices()
        assert voices == []


# ==================== TestF5TTSSynthesizeValidation ====================


class TestF5TTSSynthesizeValidation:
    @pytest.mark.asyncio
    async def test_synthesize_empty_text_yields_nothing(self, f5_provider, valid_config):
        chunks = []
        async for c in f5_provider.synthesize("", valid_config):
            chunks.append(c)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_whitespace_only_yields_nothing(self, f5_provider, valid_config):
        chunks = []
        async for c in f5_provider.synthesize("   \n  ", valid_config):
            chunks.append(c)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_missing_ref_audio_raises(self, f5_provider):
        config = TTSConfig(provider="f5-tts", voice_id="mao", extra={"ref_text": "x"})
        with pytest.raises(ValueError, match="ref_audio"):
            async for _ in f5_provider.synthesize("你好", config):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_missing_ref_text_raises(self, f5_provider, tmp_path):
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"x")
        config = TTSConfig(provider="f5-tts", voice_id="mao", extra={"ref_audio": str(ref)})
        with pytest.raises(ValueError, match="ref_text"):
            async for _ in f5_provider.synthesize("你好", config):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_ref_audio_not_found_raises(self, f5_provider):
        config = TTSConfig(
            provider="f5-tts",
            voice_id="mao",
            extra={"ref_audio": "/nonexistent/path/ref.wav", "ref_text": "x"},
        )
        with pytest.raises(FileNotFoundError, match="ref_audio"):
            async for _ in f5_provider.synthesize("你好", config):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_f5tts_not_installed_raises(self, f5_provider, valid_config):
        """F5TTS 套件沒裝 → RuntimeError (不是 ImportError)"""
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=None):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=MagicMock()):
                with pytest.raises(RuntimeError, match="F5-TTS"):
                    async for _ in f5_provider.synthesize("你好", valid_config):
                        pass

    @pytest.mark.asyncio
    async def test_synthesize_soundfile_not_installed_raises(self, f5_provider, valid_config):
        """soundfile 沒裝 → RuntimeError"""
        with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=None):
            with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
                mock_f5tts_instance = MagicMock()
                with patch.object(f5_provider, "_get_f5tts", return_value=mock_f5tts_instance):
                    with pytest.raises(RuntimeError, match="soundfile"):
                        async for _ in f5_provider.synthesize("你好", valid_config):
                            pass


# ==================== TestF5TTSSynthesizeSuccess ====================


class TestF5TTSSynthesizeSuccess:
    @pytest.mark.asyncio
    async def test_synthesize_yields_wav_chunks(self, f5_provider, valid_config):
        """正常路徑:mock F5TTS.infer 回 wav,驗證 yield 出去是 WAV chunks"""
        # Mock F5TTS 整個 chain
        import numpy as np
        mock_wav = np.zeros(16000, dtype=np.float32)  # 1 秒靜音 16kHz
        mock_sr = 16000

        mock_f5_instance = MagicMock()
        mock_f5_instance.infer = MagicMock(
            return_value=(mock_wav, mock_sr, MagicMock())  # (wav, sr, spec)
        )

        # Mock soundfile.write 直接寫到 BytesIO
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile") as mock_sf_factory:
                mock_sf = MagicMock()
                mock_sf_factory.return_value = mock_sf

                def fake_write(buf, wav, sr, format):
                    buf.write(b"RIFF" + b"\x00" * 100)  # fake WAV bytes

                mock_sf.write.side_effect = fake_write
                with patch.object(f5_provider, "_get_f5tts", return_value=mock_f5_instance):
                    chunks = []
                    async for c in f5_provider.synthesize("你好,我是 Mao", valid_config):
                        chunks.append(c)

        # 驗證
        assert len(chunks) > 0
        all_bytes = b"".join(chunks)
        assert all_bytes.startswith(b"RIFF")
        # 驗證 infer 收到正確參數
        mock_f5_instance.infer.assert_called_once()
        call_kwargs = mock_f5_instance.infer.call_args.kwargs
        assert call_kwargs["ref_file"] == str(valid_config.extra["ref_audio"])
        assert call_kwargs["ref_text"] == valid_config.extra["ref_text"]
        assert call_kwargs["gen_text"] == "你好,我是 Mao"
        assert call_kwargs["speed"] == 1.0

    @pytest.mark.asyncio
    async def test_synthesize_passes_extra_params(self, f5_provider, tmp_path):
        """nfe_step / cfg_strength 從 extra 帶到 infer"""
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"x")
        config = TTSConfig(
            provider="f5-tts",
            voice_id="mao",
            extra={
                "ref_audio": str(ref),
                "ref_text": "x",
                "nfe_step": 64,
                "cfg_strength": 2.5,
            },
        )

        import numpy as np
        mock_wav = np.zeros(16000, dtype=np.float32)
        mock_f5_instance = MagicMock()
        mock_f5_instance.infer = MagicMock(return_value=(mock_wav, 16000, MagicMock()))

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile") as mock_sf_factory:
                mock_sf = MagicMock()
                mock_sf.write = MagicMock(side_effect=lambda buf, *a, **kw: buf.write(b"X" * 100))
                mock_sf_factory.return_value = mock_sf
                with patch.object(f5_provider, "_get_f5tts", return_value=mock_f5_instance):
                    async for _ in f5_provider.synthesize("test", config):
                        pass

        call_kwargs = mock_f5_instance.infer.call_args.kwargs
        assert call_kwargs["nfe_step"] == 64
        assert call_kwargs["cfg_strength"] == 2.5

    @pytest.mark.asyncio
    async def test_synthesize_speed_from_config(self, f5_provider, tmp_path):
        """config.speed 帶到 infer"""
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"x")
        config = TTSConfig(
            provider="f5-tts",
            voice_id="mao",
            speed=1.5,
            extra={"ref_audio": str(ref), "ref_text": "x"},
        )

        import numpy as np
        mock_f5_instance = MagicMock()
        mock_f5_instance.infer = MagicMock(return_value=(np.zeros(100, dtype=np.float32), 16000, MagicMock()))

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile") as mock_sf_factory:
                mock_sf = MagicMock()
                mock_sf.write = MagicMock(side_effect=lambda buf, *a, **kw: buf.write(b"X" * 100))
                mock_sf_factory.return_value = mock_sf
                with patch.object(f5_provider, "_get_f5tts", return_value=mock_f5_instance):
                    async for _ in f5_provider.synthesize("test", config):
                        pass

        assert mock_f5_instance.infer.call_args.kwargs["speed"] == 1.5


# ==================== TestF5TTSLazyLoad ====================


class TestF5TTSLazyLoad:
    def test_f5tts_not_loaded_at_init(self, f5_provider):
        """F5TTS() 不在 __init__ 跑(避免 import 時就下 1.5GB model)"""
        assert f5_provider._f5tts is None

    def test_f5tts_loaded_on_first_call(self, f5_provider):
        """第一次 _get_f5tts() 才 instantiate、第二次走 cache"""
        # 用 lambda 計數驗證 factory 真的只被 call 一次
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MagicMock()

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=factory):
            # 第一次: instantiate
            instance1 = f5_provider._get_f5tts()
            assert isinstance(instance1, MagicMock)
            assert call_count == 1
            # 第二次: 走 cache、不再 instantiate
            instance2 = f5_provider._get_f5tts()
            assert instance2 is instance1
            assert call_count == 1  # 沒增加 = cache 生效


# ==================== TestF5TTSProviderName ====================


def test_f5_tts_provider_name():
    """provider name 跟 persona YAML / voices.py DEFAULT_VOICES 對齊"""
    assert F5TTSProvider.name == "f5-tts"
