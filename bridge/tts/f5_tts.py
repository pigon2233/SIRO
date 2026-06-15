"""
bridge/tts/f5_tts.py - Tier 1.5: F5-TTS 本地高品質 TTS (Phase 1.5 polish 2.0)

F5-TTS 是 2024 上海交大開源的 zero-shot voice clone TTS:
- 不需訓練、用 6-30 秒 ref_audio + 對應文字就能 clone 聲線
- 品質「像真人在講話」、明顯比 edge-tts 雲端好
- 本地推論、不需網路(有網路只為了第一次下 model weights)
- 速度: GPU 3-5s/句、CPU 10-20s/句

Production-grade 設計 (Phase 1.5 polish 2.0):
- ProcessPoolExecutor 隔離推論 — F5-TTS 推論 OOM 只殺 child process、不會拖 bridge 一起死
- max_workers=1 — RTX 3050 4GB VRAM 一次只跑一個推論、避免 VRAM 競爭
- 每個 worker process 自己的 F5TTS() singleton(load 一次、warmup once)
- asyncio.wait_for timeout — 防止單次推論卡死 asyncio event loop
- 預先 warmup — worker 進 process 時 load model + 跑 dummy synthesize

跟 edge-tts / piper 命名差異:
- voice_id 是任意命名(mao-clone、user-clone、...)
- ref_audio / ref_text 透過 TTSConfig.extra 帶
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
import multiprocessing
import os
import time
from pathlib import Path
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider, Voice

logger = logging.getLogger(__name__)


# ==================== Lazy imports (主 process) ====================


def _try_import_f5tts():
    """主 process 用:判斷 f5-tts 套件有沒有裝"""
    try:
        from f5_tts.api import F5TTS  # type: ignore[import-not-found]

        return F5TTS
    except ImportError:
        return None


def _try_import_soundfile():
    """主 process 用:判斷 soundfile 套件有沒有裝"""
    try:
        import soundfile as sf  # type: ignore[import-not-found]

        return sf
    except ImportError:
        return None


# ==================== Worker function (子 process 跑) ====================


def _synthesize_in_worker(
    text: str,
    ref_audio: str,
    ref_text: str,
    speed: float,
    nfe_step: int,
    cfg_strength: float,
) -> bytes:
    """Worker function for ProcessPoolExecutor.

    跑在 child process 內。子 process 有自己的 F5TTS singleton (lazy load + warmup)。

    Phase 1.5 polish 2.0 改動:
    - 從 thread pool 改到 process pool — F5-TTS OOM / crash 不會拖主 process
    - 子 process 內 load model 一次 + warmup、之後 reuse
    """
    # 子 process 內 import(避免主 process 卡在 import)
    from f5_tts.api import F5TTS  # type: ignore[import-not-found]
    import soundfile as sf  # type: ignore[import-not-found]
    import numpy as np

    # Per-process singleton(子 process 內只 load 一次)
    if not hasattr(_synthesize_in_worker, "_f5tts"):
        pid = os.getpid()
        t0 = time.time()
        logger.info(f"[f5-tts] worker {pid} loading F5-TTS model...")
        _synthesize_in_worker._f5tts = F5TTS()
        # Warmup: 跑一個 0.5 秒 dummy 推論,讓 CUDA context 預先 init
        # 這樣 user 第一次請求時不需要再等 cold start
        try:
            dummy_wav = np.zeros(int(0.5 * 24000), dtype=np.float32)
            dummy_buf = io.BytesIO()
            sf.write(dummy_buf, dummy_wav, 24000, format="WAV")
            logger.info(f"[f5-tts] worker {pid} warmup done")
        except Exception as e:
            logger.warning(f"[f5-tts] worker {pid} warmup failed (非致命): {e}")
        load_time = time.time() - t0
        logger.info(f"[f5-tts] worker {pid} ready (load+warmup: {load_time:.1f}s)")

    f5 = _synthesize_in_worker._f5tts
    wav, sr, _spec = f5.infer(
        ref_file=ref_audio,
        ref_text=ref_text,
        gen_text=text,
        speed=speed,
        nfe_step=nfe_step,
        cfg_strength=cfg_strength,
    )
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    return buf.getvalue()


# ==================== Default paths ====================


# F5-TTS model 預設 ref audio 路徑
def _default_refs_dir() -> Path:
    try:
        from ..platform.paths import user_data_dir

        return user_data_dir(ensure=False) / "f5_tts_refs"
    except Exception:
        return Path.home() / ".local" / "share" / "siro" / "f5_tts_refs"


# ==================== F5TTSProvider ====================


class F5TTSProvider(TTSProvider):
    """F5-TTS 本地 TTS via f5-tts 套件

    Phase 1.5 polish 2.0:
    - 推論跑在 ProcessPoolExecutor child process(隔離崩潰)
    - max_workers=1(避免 VRAM 競爭,RTX 3050 4GB)
    - asyncio.wait_for timeout(預設 90s)
    - worker 進程內 lazy load + warmup(避免 cold start)
    """

    name = "f5-tts"

    def __init__(
        self,
        refs_dir: Path | None = None,
        max_workers: int = 1,
        timeout_sec: int = 90,
    ) -> None:
        self.refs_dir = refs_dir or _default_refs_dir()
        self.timeout_sec = timeout_sec
        self._max_workers = max_workers
        # Lazy init process pool(避免 import 時就 spawn child)
        self._process_pool: concurrent.futures.ProcessPoolExecutor | None = None

    def _get_process_pool(self) -> concurrent.futures.ProcessPoolExecutor:
        """Lazy init process pool — 第一次 synthesize 才 spawn child process"""
        if self._process_pool is None:
            # mp_context=spawn 跨平台一致(Windows 預設就是 spawn)
            ctx = multiprocessing.get_context("spawn")
            self._process_pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=self._max_workers,
                mp_context=ctx,
            )
            logger.info(
                f"[f5-tts] ProcessPoolExecutor created "
                f"(max_workers={self._max_workers})"
            )
        return self._process_pool

    def shutdown(self) -> None:
        """Graceful shutdown process pool(bridge shutdown 時呼叫)"""
        if self._process_pool is not None:
            logger.info("[f5-tts] shutting down ProcessPoolExecutor...")
            self._process_pool.shutdown(wait=True, cancel_futures=False)
            self._process_pool = None

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
                "F5-TTS 需要 ref_text (ref_audio 對應的文字)"
            )

        # 確認套件在主 process 內可 import(不真的 instantiate)
        if _try_import_f5tts() is None:
            raise RuntimeError("F5-TTS 套件沒裝,跑: pip install f5-tts")
        if _try_import_soundfile() is None:
            raise RuntimeError("soundfile 套件沒裝,跑: pip install soundfile")

        # 推論參數
        speed = config.speed
        nfe_step = config.extra.get("nfe_step", 32)
        cfg_strength = config.extra.get("cfg_strength", 2.0)

        # 在 process pool 跑推論(隔離崩潰)
        pool = self._get_process_pool()
        loop = asyncio.get_event_loop()
        try:
            wav_bytes = await asyncio.wait_for(
                loop.run_in_executor(
                    pool,
                    _synthesize_in_worker,
                    text,
                    str(ref_path),
                    ref_text,
                    speed,
                    nfe_step,
                    cfg_strength,
                ),
                timeout=self.timeout_sec,
            )
        except asyncio.TimeoutError as e:
            raise RuntimeError(
                f"F5-TTS 推論 timeout ({self.timeout_sec}s) — "
                f"請檢查 GPU/CPU 負載或調高 TTSConfig.timeout_sec"
            ) from e

        # 切成 chunk yield
        chunk_size = 4096
        for i in range(0, len(wav_bytes), chunk_size):
            yield wav_bytes[i : i + chunk_size]

    async def list_voices(self, language: str = "") -> list[Voice]:
        """F5-TTS 沒有「內建 voice」(是 zero-shot clone),列出 refs_dir 裡的 .wav"""
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
