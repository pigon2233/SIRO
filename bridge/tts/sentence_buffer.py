"""
bridge/tts/sentence_buffer.py - Sentence boundary detector for streaming TTS

Phase 1.5.2b: LLM streaming 出 token → 緩衝 → 偵測句尾 → yield 完整句子給 TTS

設計:
- LLM streaming 是 token 級的(可能一個 chunk 切在句中)
- 用 buffer 累積、掃描到句尾(中英文標點)就 yield
- 一個完整句子 yield 出去給 TTS invoke,後續 token 繼續累積
- TTS invoke 是 fire-and-forget 背景 task,不阻塞 LLM streaming
- Unity 端按收到順序播放(WS 保證 in-order)

句尾規則(中英文都支援):
- 中文: 。 ！ ？
- 英文: . ! ?
- 中英混合時優先中文句尾(LLM 繁中回應為主)

v1.0 polish 機會(之後):
- 用 jieba 斷詞 + spaCy 取代 regex(避免 "...3.14 ..." 誤切)
- 累積超長但沒句尾(例如 LLM 卡住)→ timeout 強制切
"""

from __future__ import annotations

import re
from typing import Iterator


# 句尾標點(中英文都包進同一個 regex)
# 順序很重要:中文標點放前面(避免 "。" 跟 ". " 衝突)
_SENTENCE_END_PATTERN = re.compile(r"([。！？!?\.][\s'\",)\]」』]*)")


class SentenceBuffer:
    """緩衝 token chunks、yield 完整句子

    用法:
        buf = SentenceBuffer()
        for chunk in llm_stream:
            for sentence in buf.feed(chunk):
                # sentence 是完整的一句(包含句尾標點)
                tts_invoke(sentence)
        # 收尾:殘餘文字也當一句(可能有、可能沒有句尾)
        for sentence in buf.flush():
            tts_invoke(sentence)
    """

    def __init__(self) -> None:
        self._buffer: str = ""

    def feed(self, chunk: str) -> list[str]:
        """喂一個 token chunk,回傳 0+ 個完整句子

        設計選擇:回傳 list 而不是 generator
        - caller 通常要 for-loop + fire TTS task,list 更順
        - 句子數量通常很少(一個 LLM 回應 1-10 句),list overhead 可忽略
        """
        if not chunk:
            return []
        self._buffer += chunk
        return self._extract_complete_sentences()

    def flush(self) -> list[str]:
        """收尾:殘餘 buffer(可能沒句尾)也當一句 yield"""
        if self._buffer.strip():
            sent = self._buffer.strip()
            self._buffer = ""
            return [sent]
        return []

    def _extract_complete_sentences(self) -> list[str]:
        """掃 buffer、找到所有完整句子的邊界、切成 list"""
        sentences: list[str] = []
        # 反覆找下一個句尾、直到沒了
        while True:
            m = _SENTENCE_END_PATTERN.search(self._buffer)
            if not m:
                break
            # 句尾結束位置(inclusive)
            end = m.end()
            sentence = self._buffer[:end].strip()
            if sentence:
                sentences.append(sentence)
            # 剩下的留 buffer 繼續累積
            self._buffer = self._buffer[end:]
        return sentences

    @property
    def pending(self) -> str:
        """目前 buffer 內未完成的文字(debug / 監控用)"""
        return self._buffer

    def __repr__(self) -> str:
        return f"SentenceBuffer(pending={len(self._buffer)} chars)"


# ============================================================
# Stream helper — 給 caller 一個更直覺的 for-loop 介面
# ============================================================
def iter_sentences(text_stream: Iterator[str]) -> Iterator[str]:
    """把任意 text stream 切成句子的 generator

    用法:
        for sent in iter_sentences(llm_stream):
            tts_invoke(sent)

    收尾會把殘餘 buffer 也 yield 出去。
    """
    buf = SentenceBuffer()
    for chunk in text_stream:
        for sent in buf.feed(chunk):
            yield sent
    for sent in buf.flush():
        yield sent
