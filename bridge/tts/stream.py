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

Phase 1.5.2a: TTS 進 provider 前先清掉 LLM 情緒標籤 + emoji,
避免 F5-TTS / edge-tts 把 `[emotion:happy]` 唸出來。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

from .base import TTSConfig, TTSProvider
from .edge_tts import EdgeTTSProvider
from .f5_tts import F5TTSProvider
from .piper_tts import PiperTTSProvider

logger = logging.getLogger(__name__)


# 簡單的句子切割(中英文都支援)
# 完整版該用結巴 / spaCy / langdetect,先求 work 再求好
_SENTENCE_END = re.compile(r"(?<=[。！？!?\.])")


# Phase 1.5.2a: 從 emotion_parser 借 regex 清掉 LLM 標籤 + emoji
# 避免 F5-TTS / edge-tts 把 `[emotion:happy]` 唸出來
# 複用 emotion_parser 的常數、不重複定義
from ..emotion_parser import EMOTION_TAG_PATTERN, EMOJI_PATTERN


def _clean_for_tts(raw: str) -> str:
    """準備要送進 TTS provider 的純文字

    跟 emotion_parser._clean_for_display 一樣的邏輯、但放在 TTS 層
    確保「不管 caller 是誰」(HTTP route / WS streaming / 直接 call)都會清。
    """
    if not raw:
        return ""
    s = EMOTION_TAG_PATTERN.sub("", raw)
    s = EMOJI_PATTERN.sub("", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


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
            # 預設: F5-TTS (Tier 1.5 本地高品質) → edge-tts (Tier 1 雲端) → Piper (Tier 2 fallback)
            # F5-TTS is_available() 自動判斷,沒裝就 fallback edge-tts
            self.providers = [
                F5TTSProvider(),
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

        Fallback 語意(Phase 1.5.1b 修):
        - config.provider 明確指定(provider 存在於 providers 內)→ 只用那個,失敗 → 直接 raise
          (user/persona 已經選了 F5-TTS,不該偷偷換 edge-tts)
        - config.provider 是 "auto" / 沒指定 → 走 providers 順序,第一個 is_available 的
        """
        # Phase 1.5.2a: 進 TTS 前先清掉 emotion tag + emoji
        # 避免 F5-TTS / edge-tts 把 `[emotion:happy]` 唸出來
        clean_text = _clean_for_tts(text)
        if not clean_text:
            logger.warning("[tts] clean_for_tts 後是空字串、跳過")
            return

        # 判斷 config.provider 是不是「明確指定」特定 provider
        explicit_provider_names = {p.name for p in self.providers}
        if config.provider in explicit_provider_names:
            # 明確指定 → 只用那個,不要 fallback
            for p in self.providers:
                if p.name == config.provider:
                    logger.debug(
                        f"[tts] synthesize via {p.name} (explicit): "
                        f"voice={config.voice_id} text_len={len(clean_text)}"
                    )
                    async for chunk in p.synthesize(clean_text, config):
                        yield chunk
                    async with self._active_lock:
                        self._active_provider = p
                    return
            # 不該到這(理論上 in explicit_provider_names 一定找得到)
            raise RuntimeError(f"TTS provider {config.provider} 不存在於 providers list")

        # 沒明確指定 → 走 fallback chain
        provider = await self.get_active_provider()
        logger.debug(
            f"[tts] synthesize via {provider.name} (auto): voice={config.voice_id} "
            f"text_len={len(clean_text)}"
        )
        async for chunk in provider.synthesize(clean_text, config):
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
        # Phase 1.5.2a: 整段先清一次(防止 strip 後某句變空字串被誤切)
        clean_text = _clean_for_tts(text)
        if not clean_text:
            return
        provider = await self.get_active_provider()
        sentences = _split_sentences(clean_text)
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
