"""
bridge/tts/stream.py - TTS streaming orchestrator

負責:
- Provider 選擇(edge-tts 預設、Piper fallback)
- 句子切割(讓 TTS 跟 LLM streaming 並行跑、降低 TTFB)
- 串流 chunks 給上層(bridge → WS → Unity)

設計:
- LLM 出 token → 累積到完整句子 → 切給 TTS
- TTS synthesize_stream() 串流音檔 → yield 給 caller
- 一個 sentence 一個 TTS request(並行,不是 sequence)
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider
from .edge_tts import EdgeTTSProvider
from .piper_tts import PiperTTSProvider

logger = logging.getLogger(__name__)


# 簡單的句子切割(中英文都支援)
# 完整版該用結巴 / spaCy / langdetect,先求 work 再求好
import re

_SENTENCE_END = re.compile(r"(?<=[。！？!?\.])")


def _split_sentences(text: str) -> list[str]:
    """把文字切成句子(中英文標點都支援)

    >>> _split_sentences("你好!我是 SIRO。今天天氣真好。")
    ['你好!', '我是 SIRO。', '今天天氣真好。']
    """
    if not text.strip():
        return []
    # 用 lookbehind 保留標點
    parts = _SENTENCE_END.split(text)
    return [p.strip() for p in parts if p.strip()]


class TTSOrchestrator:
    """TTS 編排器

    用法:
        orchestrator = TTSOrchestrator()
        config = TTSConfig(provider="edge-tts", voice_id="zh-TW-HsiaoChenNeural", ...)
        async for chunk in orchestrator.synthesize_stream("你好,我是 SIRO。", config):
            # chunk 是 MP3 bytes
            ...
    """

    def __init__(self, providers: list[TTSProvider] | None = None) -> None:
        if providers is None:
            # 預設: edge-tts (Tier 1) + Piper (Tier 2 fallback)
            self.providers = [
                EdgeTTSProvider(),
                PiperTTSProvider(),
            ]
        else:
            self.providers = providers
        # 找第一個可用的、之後固定用
        self._active_provider: TTSProvider | None = None
        self._active_lock = asyncio.Lock()

    async def get_active_provider(self) -> TTSProvider:
        """取得目前可用的 provider(快取結果)"""
        if self._active_provider is not None:
            return self._active_provider

        async with self._active_lock:
            if self._active_provider is not None:
                return self._active_provider

            for p in self.providers:
                try:
                    if await p.is_available():
                        logger.info(f"[tts] active provider: {p.name}")
                        self._active_provider = p
                        return p
                except Exception as e:
                    logger.warning(f"[tts] provider {p.name} check failed: {e}")

            # 全部不可用、回傳第一個(讓 caller 拿到合理錯誤)
            logger.warning("[tts] 全部 provider 不可用、回傳第一個")
            self._active_provider = self.providers[0]
            return self._active_provider

    async def synthesize_stream(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        """串流合成 — 整段文字一個 provider request、串流 yield chunks

        Args:
            text: 完整文字(由 caller 負責 LLM streaming 累積到 sentence)
            config: TTS 設定

        Yields:
            audio chunks (bytes)

        Raises:
            RuntimeError: 全部 provider 都失敗
        """
        provider = await self.get_active_provider()
        logger.debug(
            f"[tts] synthesize via {provider.name}: voice={config.voice_id} "
            f"text_len={len(text)}"
        )
        async for chunk in provider.synthesize(text, config):
            yield chunk

    async def synthesize_sentence_stream(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[tuple[str, bytes]]:
        """串流 — 切成句子、每個句子一個 TTS request

        設計給「LLM 出完整回應後、一次合成多句」的情境。
        Yield 格式: (sentence, audio_chunk)

        Args:
            text: 完整文字
            config: TTS 設定

        Yields:
            (sentence, audio_chunk) tuples
        """
        provider = await self.get_active_provider()
        sentences = _split_sentences(text)
        logger.debug(
            f"[tts] synthesize {len(sentences)} sentences via {provider.name}"
        )

        # 平行跑多個句子(每個獨立 TTS request)
        # 不過實際上 sentence 之間還是 sequential(避免同時講兩段)、只是 yield 顆粒度更小
        for sent in sentences:
            if not sent.strip():
                continue
            async for chunk in provider.synthesize(sent, config):
                yield (sent, chunk)


# 全域 singleton
_orchestrator: TTSOrchestrator | None = None


def get_tts_orchestrator() -> TTSOrchestrator:
    """取得全域 TTS orchestrator

    Lazy initialization、第一次呼叫才建 provider(避免 import 階段就拉 edge-tts 套件)。
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TTSOrchestrator()
    return _orchestrator
