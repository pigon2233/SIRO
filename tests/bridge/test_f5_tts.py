"""
tests/bridge/test_f5_tts.py - F5-TTS provider mock tests (Phase 1.5 polish 2.0)

Production-grade F5TTSProvider:
- ProcessPoolExecutor 隔離推論
- worker 內 lazy load + warmup
- asyncio.wait_for timeout
- shutdown() graceful

跟 Phase 1 風格:mock 套件、測邏輯、不真的下 1.5GB model 或 spawn process
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bridge.tts.base import TTSConfig
from bridge.tts.f5_tts import F5TTSProvider


# ==================== Fixtures ====================


@pytest.fixture
def f5_provider(tmp_path: Path) -> F5TTSProvider:
    refs_dir = tmp_path / "f5_refs"
    refs_dir.mkdir()
    (refs_dir / "mao_zh.wav").write_bytes(b"fake wav 1")
    (refs_dir / "user_zh.wav").write_bytes(b"fake wav 2")
    return F5TTSProvider(refs_dir=refs_dir, timeout_sec=90)


@pytest.fixture
def f5_provider_fast_timeout(tmp_path: Path) -> F5TTSProvider:
    refs_dir = tmp_path / "f5_refs"
    refs_dir.mkdir()
    (refs_dir / "mao_zh.wav").write_bytes(b"fake wav")
    return F5TTSProvider(refs_dir=refs_dir, timeout_sec=1)


@pytest.fixture
def f5_provider_empty(tmp_path: Path) -> F5TTSProvider:
    refs_dir = tmp_path / "f5_refs_empty"
    refs_dir.mkdir()
    return F5TTSProvider(refs_dir=refs_dir)


@pytest.fixture
def f5_provider_no_dir(tmp_path: Path) -> F5TTSProvider:
    return F5TTSProvider(refs_dir=tmp_path / "nonexistent")


@pytest.fixture
def valid_config(tmp_path: Path) -> TTSConfig:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"fake wav")
    return TTSConfig(
        provider="f5-tts",
        voice_id="mao-clone",
        language="zh-TW",
        speed=1.0,
        extra={"ref_audio": str(ref), "ref_text": "你好測試"},
    )


def make_fake_pool(return_value):
    """建一個 fake ProcessPoolExecutor — submit 回 Future 內含 fn(*args) 結果

    用來避免真的 spawn child process + pickling mock 失敗。
    """
    class FakePool:
        def submit(self, fn, *args, **kwargs):
            f = concurrent.futures.Future()
            f.set_result(fn(*args, **kwargs))
            return f

        def shutdown(self, wait=True, cancel_futures=False):
            pass

    return FakePool()


# ==================== TestF5TTSIsAvailable ====================


class TestF5TTSIsAvailable:
    @pytest.mark.asyncio
    async def test_available_when_installed_with_refs(self, f5_provider):
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            assert await f5_provider.is_available() is True

    @pytest.mark.asyncio
    async def test_not_available_when_f5tts_missing(self, f5_provider):
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=None):
            assert await f5_provider.is_available() is False

    @pytest.mark.asyncio
    async def test_not_available_when_refs_dir_empty(self, f5_provider_empty):
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            assert await f5_provider_empty.is_available() is False

    @pytest.mark.asyncio
    async def test_not_available_when_refs_dir_missing(self, f5_provider_no_dir):
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            assert await f5_provider_no_dir.is_available() is False


# ==================== TestF5TTSListVoices ====================


class TestF5TTSListVoices:
    @pytest.mark.asyncio
    async def test_list_refs(self, f5_provider):
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
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=None):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=MagicMock()):
                with pytest.raises(RuntimeError, match="F5-TTS"):
                    async for _ in f5_provider.synthesize("你好", valid_config):
                        pass

    @pytest.mark.asyncio
    async def test_synthesize_soundfile_not_installed_raises(self, f5_provider, valid_config):
        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=None):
                with pytest.raises(RuntimeError, match="soundfile"):
                    async for _ in f5_provider.synthesize("你好", valid_config):
                        pass


# ==================== TestF5TTSSynthesizeSuccess ====================


class TestF5TTSSynthesizeSuccess:
    @pytest.mark.asyncio
    async def test_synthesize_yields_wav_chunks(self, f5_provider, valid_config):
        expected_wav = b"RIFF" + b"\x00" * 100
        fake_pool = make_fake_pool(expected_wav)

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=MagicMock()):
                with patch(
                    "bridge.tts.f5_tts._synthesize_in_worker",
                    return_value=expected_wav,
                ) as mock_worker:
                    with patch(
                        "concurrent.futures.ProcessPoolExecutor",
                        return_value=fake_pool,
                    ):
                        chunks = []
                        async for c in f5_provider.synthesize("你好,我是 Mao", valid_config):
                            chunks.append(c)

        assert len(chunks) > 0
        all_bytes = b"".join(chunks)
        assert all_bytes == expected_wav
        mock_worker.assert_called_once()
        call_args = mock_worker.call_args.args
        assert call_args[0] == "你好,我是 Mao"
        assert call_args[1] == str(valid_config.extra["ref_audio"])
        assert call_args[2] == valid_config.extra["ref_text"]
        assert call_args[3] == 1.0
        assert call_args[4] == 32
        assert call_args[5] == 2.0

    @pytest.mark.asyncio
    async def test_synthesize_passes_extra_params(self, f5_provider, tmp_path):
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

        fake_pool = make_fake_pool(b"X" * 100)

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=MagicMock()):
                with patch(
                    "bridge.tts.f5_tts._synthesize_in_worker",
                    return_value=b"X" * 100,
                ) as mock_worker:
                    with patch(
                        "concurrent.futures.ProcessPoolExecutor",
                        return_value=fake_pool,
                    ):
                        async for _ in f5_provider.synthesize("test", config):
                            pass

        call_args = mock_worker.call_args.args
        assert call_args[4] == 64
        assert call_args[5] == 2.5

    @pytest.mark.asyncio
    async def test_synthesize_speed_from_config(self, f5_provider, tmp_path):
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"x")
        config = TTSConfig(
            provider="f5-tts",
            voice_id="mao",
            speed=1.5,
            extra={"ref_audio": str(ref), "ref_text": "x"},
        )

        fake_pool = make_fake_pool(b"X" * 100)

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=MagicMock()):
                with patch(
                    "bridge.tts.f5_tts._synthesize_in_worker",
                    return_value=b"X" * 100,
                ) as mock_worker:
                    with patch(
                        "concurrent.futures.ProcessPoolExecutor",
                        return_value=fake_pool,
                    ):
                        async for _ in f5_provider.synthesize("test", config):
                            pass

        assert mock_worker.call_args.args[3] == 1.5


# ==================== TestF5TTSSynthesizeTimeout ====================


class TestF5TTSSynthesizeTimeout:
    @pytest.mark.asyncio
    async def test_synthesize_timeout_raises_runtime_error(self, f5_provider_fast_timeout, valid_config):
        """推論超時 → RuntimeError (不是 asyncio.TimeoutError)"""
        class SlowPool:
            def submit(self, fn, *args, **kwargs):
                f = concurrent.futures.Future()
                # 故意不 set_result,模擬 hang。asyncio.wait_for 會 timeout
                return f

            def shutdown(self, wait=True, cancel_futures=False):
                pass

        with patch("bridge.tts.f5_tts._try_import_f5tts", return_value=MagicMock()):
            with patch("bridge.tts.f5_tts._try_import_soundfile", return_value=MagicMock()):
                with patch(
                    "concurrent.futures.ProcessPoolExecutor",
                    return_value=SlowPool(),
                ):
                    with pytest.raises(RuntimeError, match="timeout"):
                        async for _ in f5_provider_fast_timeout.synthesize("test", valid_config):
                            pass


# ==================== TestF5TTSProcessPoolLazyInit ====================


class TestF5TTSProcessPoolLazyInit:
    def test_process_pool_not_created_at_init(self, f5_provider):
        assert f5_provider._process_pool is None

    def test_process_pool_created_on_first_call(self, f5_provider):
        with patch(
            "concurrent.futures.ProcessPoolExecutor"
        ) as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool_class.return_value = mock_pool
            pool1 = f5_provider._get_process_pool()
            assert pool1 is mock_pool
            assert mock_pool_class.call_count == 1
            pool2 = f5_provider._get_process_pool()
            assert pool2 is pool1
            assert mock_pool_class.call_count == 1


# ==================== TestF5TTSShutdown ====================


class TestF5TTSShutdown:
    def test_shutdown_when_no_pool(self, f5_provider):
        f5_provider.shutdown()

    def test_shutdown_graceful(self, f5_provider):
        mock_pool = MagicMock()
        f5_provider._process_pool = mock_pool
        f5_provider.shutdown()
        mock_pool.shutdown.assert_called_once_with(wait=True, cancel_futures=False)
        assert f5_provider._process_pool is None


# ==================== TestF5TTSProviderName ====================


def test_f5_tts_provider_name():
    assert F5TTSProvider.name == "f5-tts"
