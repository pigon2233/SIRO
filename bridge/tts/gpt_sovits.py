"""
bridge/tts/gpt_sovits.py - Tier 3: GPT-SoVITS (動漫聲線 clone、v1.0 polish)

GPT-SoVITS 是開源 TTS、用 5-10 秒樣本就能 clone 動漫聲線。
中文品質好、跟 Live2D Mao 視覺風格一致。

API 呼叫:GPT-SoVITS 的 API server (預設 localhost:9880)
- POST / 帶 text + speaker audio reference
- 回傳 WAV bytes

預期用法:
1. user 準備 Mao 角色配音 5-10 分鐘樣本
2. 跑 GPT-SoVITS training、export 模型到 models/gpt-sovits/mao/
3. 啟動 GPT-SoVITS API server:`python api_v2.py -dr models/gpt-sovits/mao/mao`
4. 設 persona.voice.provider: gpt-sovits
5. 設 persona.voice.voice_id: mao-clone

Phase 1 不做(沒訓練資料)、Tier 3 留作 v1.0 polish
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider, Voice

logger = logging.getLogger(__name__)


class GPTSoVITSProvider(TTSProvider):
    """GPT-SoVITS API client (localhost:9880)"""

    name = "gpt-sovits"
    DEFAULT_API_URL = "http://127.0.0.1:9880"

    def __init__(self, api_url: str | None = None) -> None:
        self.api_url = api_url or self.DEFAULT_API_URL

    async def synthesize(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        """GPT-SoVITS 推論

        API contract (GPT-SoVITS 2025+):
        POST {api_url}/
        - text: 要唸的文字
        - text_language: zh|jp|en|...
        - refer_wav_path: 參考音檔路徑(給聲線 reference 用)
        - prompt_text: 參考音檔對應文字

        Returns: WAV bytes
        """
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError(
                "httpx 套件沒裝、bridge 應該已經有依賴"
            ) from e

        # 從 config 拿 prompt 路徑(如果沒設、v1.0 polish 會補)
        refer_wav = config.extra.get("refer_wav_path", "")
        prompt_text = config.extra.get("prompt_text", "")

        if not refer_wav:
            raise RuntimeError(
                "GPT-SoVITS 需要 refer_wav_path (persona.voice.extra.refer_wav_path)\n"
                "請準備 Mao 角色配音 5-10 秒樣本、放 models/gpt-sovits/mao/ref.wav"
            )

        text_lang = "zh" if config.language.startswith("zh") else config.language.split("-")[0]

        logger.info(
            f"[gpt_sovits] synthesize api={self.api_url} text_len={len(text)} "
            f"refer_wav={refer_wav}"
        )

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.api_url}/",
                json={
                    "text": text,
                    "text_language": text_lang,
                    "refer_wav_path": refer_wav,
                    "prompt_text": prompt_text,
                    "prompt_language": text_lang,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"GPT-SoVITS API 錯誤 {response.status_code}: "
                    f"{response.text[:200]}"
                )
            wav_bytes = response.content

        # 整段 yield(切成 4KB chunks 避免太大 buffer)
        chunk_size = 4096
        for i in range(0, len(wav_bytes), chunk_size):
            yield wav_bytes[i : i + chunk_size]

    async def list_voices(self, language: str = "") -> list[Voice]:
        """GPT-SoVITS 沒有中央 API、靠本地模型掃

        慣例:models/gpt-sovits/{voice_id}/ 底下有參考音檔
        """
        from pathlib import Path
        models_dir = Path("models/gpt-sovits")
        voices: list[Voice] = []
        if models_dir.exists():
            for voice_dir in models_dir.iterdir():
                if voice_dir.is_dir() and (voice_dir / "ref.wav").exists():
                    voices.append(
                        Voice(
                            id=voice_dir.name,
                            name=voice_dir.name,
                            language=language or "zh",
                            gender="unknown",
                            provider=self.name,
                        )
                    )
        return voices

    async def is_available(self) -> bool:
        """GPT-SoVITS API server 跑起來了嗎"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.api_url}/")
                # GPT-SoVITS / endpoint 不一定回 200、有時是 405 但 server 有在聽
                return response.status_code < 500
        except Exception as e:
            logger.debug(f"[gpt_sovits] API unavailable: {e}")
            return False
