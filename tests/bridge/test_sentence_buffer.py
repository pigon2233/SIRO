"""
tests/bridge/test_sentence_buffer.py - Phase 1.5.2b sentence boundary detection

測試範圍:
- SentenceBuffer.feed() 切句邏輯
- 跨 chunk 累積
- 中英文標點
- flush() 收尾
- 數字裡的 . 誤切(已知限制、記錄行為)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bridge.tts.sentence_buffer import SentenceBuffer, iter_sentences


class TestSentenceBufferBasic:
    def test_empty_feed_returns_empty_list(self):
        buf = SentenceBuffer()
        assert buf.feed("") == []
        assert buf.feed("") == []

    def test_single_chinese_period_terminates(self):
        buf = SentenceBuffer()
        r = buf.feed("你好。")
        assert r == ["你好。"]
        assert buf.pending == ""

    def test_single_english_period_terminates(self):
        buf = SentenceBuffer()
        r = buf.feed("Hello world.")
        assert r == ["Hello world."]

    def test_no_terminator_yields_nothing(self):
        buf = SentenceBuffer()
        r = buf.feed("沒有句尾")
        assert r == []
        assert buf.pending == "沒有句尾"

    def test_flush_yields_remainder(self):
        buf = SentenceBuffer()
        buf.feed("沒有句尾")
        r = buf.flush()
        assert r == ["沒有句尾"]
        assert buf.pending == ""

    def test_flush_with_empty_buffer(self):
        buf = SentenceBuffer()
        assert buf.flush() == []


class TestSentenceBufferSplitting:
    def test_two_sentences_one_chunk(self):
        buf = SentenceBuffer()
        r = buf.feed("你好。我是 Mao。")
        assert r == ["你好。", "我是 Mao。"]
        assert buf.pending == ""

    def test_three_sentences_one_chunk(self):
        buf = SentenceBuffer()
        r = buf.feed("你好。我是 SIRO。今天天氣好。")
        assert r == ["你好。", "我是 SIRO。", "今天天氣好。"]

    def test_sentence_split_across_chunks(self):
        """LLM streaming 把一句切成多個 token,要能正確累積切句"""
        buf = SentenceBuffer()
        all_sents: list[str] = []
        all_sents.extend(buf.feed("你"))
        all_sents.extend(buf.feed("好"))
        all_sents.extend(buf.feed("。我是"))
        all_sents.extend(buf.feed(" SIRO。"))
        all_sents.extend(buf.flush())
        assert all_sents == ["你好。", "我是 SIRO。"]

    def test_period_at_chunk_boundary(self):
        """句尾標點剛好是 chunk 最後一個字"""
        buf = SentenceBuffer()
        r1 = buf.feed("你好")
        r2 = buf.feed("。")
        assert r1 == []
        assert r2 == ["你好。"]

    def test_mixed_cn_en_punctuation(self):
        """中英文混雜標點"""
        buf = SentenceBuffer()
        r = buf.feed("Hello!我是 Mao.天氣真好!")
        # 應該 3 句(包含 ! 跟 . 跟 !)
        assert len(r) == 3
        assert "Hello!" in r
        assert "我是 Mao." in r
        assert "天氣真好!" in r

    def test_chinese_question_and_exclamation(self):
        buf = SentenceBuffer()
        r = buf.feed("你好嗎？我很好！")
        assert r == ["你好嗎？", "我很好！"]


class TestSentenceBufferEdgeCases:
    def test_known_limit_number_with_dot(self):
        """已知 regex 限制:數字裡的 . 會被誤切成句尾

        記錄這個行為、未來用 jieba/spaCy 取代 regex 修
        (見 bridge/tts/sentence_buffer.py 註解)
        """
        buf = SentenceBuffer()
        r = buf.feed("PI 是 3.14 喔。")
        # 目前會切成 ["PI 是 3.", "14 喔。"] — 不理想但可預期
        assert r[0] == "PI 是 3."
        # 重要:有切、所以 caller 知道有「句尾」事件
        assert len(r) >= 1

    def test_consecutive_terminators(self):
        buf = SentenceBuffer()
        r = buf.feed("你好！！")
        # 兩個 ! 連在一起、目前 regex 只切第一個
        # 行為: ["你好！", "！"] — 不理想但可預期
        assert "你好" in r[0]

    def test_whitespace_handling(self):
        buf = SentenceBuffer()
        r = buf.feed("  你好。世界。  ")
        # strip 後該有的還是有
        assert any("你好。" in s for s in r)
        assert any("世界。" in s for s in r)

    def test_unicode_emoji_not_a_terminator(self):
        buf = SentenceBuffer()
        r = buf.feed("你好 😀 世界。")
        # emoji 不該觸發切句
        assert r == ["你好 😀 世界。"]


class TestIterSentencesHelper:
    def test_simple_stream(self):
        chunks = ["你好。", "我是 SIRO。", "今天好。"]
        sents = list(iter_sentences(iter(chunks)))
        assert sents == ["你好。", "我是 SIRO。", "今天好。"]

    def test_split_stream(self):
        chunks = ["你", "好。", "我是 SIRO", "。", "今天好"]
        sents = list(iter_sentences(iter(chunks)))
        assert sents == ["你好。", "我是 SIRO。", "今天好"]

    def test_empty_stream(self):
        sents = list(iter_sentences(iter([])))
        assert sents == []

    def test_stream_without_terminator(self):
        chunks = ["沒有句尾的文字"]
        sents = list(iter_sentences(iter(chunks)))
        # flush 會 yield
        assert sents == ["沒有句尾的文字"]


class TestSentenceBufferRepr:
    def test_repr_shows_pending_length(self):
        buf = SentenceBuffer()
        buf.feed("未完成")
        r = repr(buf)
        assert "SentenceBuffer" in r
        assert "3" in r  # 3 chars

    def test_pending_property(self):
        buf = SentenceBuffer()
        assert buf.pending == ""
        buf.feed("未完")
        assert buf.pending == "未完"
        buf.feed("成。")
        assert buf.pending == ""
