"""
tests/bridge/test_emotion_parser.py - EmotionParser 單元測試

覆蓋：
- [emotion:xxx] 標籤解析（含大小寫、無效 tag）
- 強信號 override（user_input 含明確情緒詞 > LLM 判斷）
- 備援關鍵字比對
- emoji 過濾
- tag 移除
- to_live2d_signal 強度 clamp
"""

from __future__ import annotations

import pytest

from bridge.emotion_parser import (
    EmotionParser,
    EMOTION_TAG_PATTERN,
    EMOJI_PATTERN,
    STRONG_USER_SIGNALS,
    EMOTION_KEYWORDS,
)
from bridge.models import Emotion, Live2DSignal


# ==================== Fixtures ====================

@pytest.fixture
def parser() -> EmotionParser:
    """預設 EmotionParser（讀 bridge/emotion_mapping.json）"""
    return EmotionParser()


@pytest.fixture
def parser_no_mapping() -> EmotionParser:
    """沒有 mapping 檔的 parser — 用 empty mapping"""
    return EmotionParser(mapping_file="/nonexistent/emotion_mapping.json")


# ==================== Emotion tag 解析 ====================

class TestEmotionTagParsing:
    """測 [emotion:xxx] 標籤抽取"""

    def test_parses_valid_tag(self, parser: EmotionParser):
        text = "[emotion:happy] 你好！"
        clean, emotion, intensity = parser.parse(text)
        assert emotion == Emotion.HAPPY
        assert "你好" in clean
        assert "[emotion:happy]" not in clean

    def test_parses_lowercase_tag(self, parser: EmotionParser):
        text = "[emotion:sad] 我好難過"
        _, emotion, _ = parser.parse(text)
        assert emotion == Emotion.SAD

    def test_parses_mixed_case_tag(self, parser: EmotionParser):
        text = "[Emotion:EXCITED] 太棒了！"
        _, emotion, _ = parser.parse(text)
        assert emotion == Emotion.EXCITED

    def test_unknown_tag_falls_back_to_keyword(self, parser: EmotionParser):
        """無效 tag 應該 fallback 到關鍵字比對，不該 crash"""
        text = "[emotion:xyzinvalid] 我好難過嗚嗚"
        _, emotion, _ = parser.parse(text)
        # 關鍵字命中 SAD（"難過"）
        assert emotion == Emotion.SAD

    def test_no_tag_no_keyword_returns_neutral(self, parser: EmotionParser):
        # 避開情緒詞 substring：「天氣」含「氣」會誤判 angry
        # 「氣球」也含「氣」、「開心」含「開」... 寫中性句要小心
        text = "今天星期三下午兩點"
        _, emotion, _ = parser.parse(text)
        assert emotion == Emotion.NEUTRAL

    def test_tag_anywhere_in_text(self, parser: EmotionParser):
        """tag 不一定要在開頭 — regex 找第一個"""
        text = "我覺得 [emotion:thinking] 嗯..."
        _, emotion, _ = parser.parse(text)
        assert emotion == Emotion.THINKING


# ==================== 強信號 override ====================

class TestStrongUserSignal:
    """測 STRONG_USER_SIGNALS 對 user_input 的 override 邏輯"""

    def test_strong_signal_overrides_llm_tag(self, parser: EmotionParser):
        """user 說「難過」就算 LLM 回 excited 也該走 sad"""
        llm_output = "[emotion:excited] 來玩遊戲吧！"
        clean, emotion, _ = parser.parse(llm_output, user_input="我好難過")
        assert emotion == Emotion.SAD

    def test_strong_signal_when_no_llm_tag(self, parser: EmotionParser):
        llm_output = "嗯嗯好的"
        _, emotion, _ = parser.parse(llm_output, user_input="我超生氣")
        assert emotion == Emotion.ANGRY

    def test_strong_signal_surprised(self, parser: EmotionParser):
        llm_output = "好的沒問題"
        _, emotion, _ = parser.parse(llm_output, user_input="真的嗎?!")
        assert emotion == Emotion.SURPRISED

    def test_no_strong_signal_lets_llm_decide(self, parser: EmotionParser):
        """user 沒講情緒詞時，聽 LLM 的 tag"""
        llm_output = "[emotion:happy] 早安"
        _, emotion, _ = parser.parse(llm_output, user_input="你好")
        assert emotion == Emotion.HAPPY

    def test_no_strong_signal_no_llm_tag_uses_keyword(self, parser: EmotionParser):
        """都沒就 fallback 關鍵字"""
        llm_output = "哈哈真的太好笑了"
        _, emotion, _ = parser.parse(llm_output, user_input="嗯")
        assert emotion == Emotion.JOYFUL

    def test_all_strong_signal_emotions_present(self):
        """STRONG_USER_SIGNALS 字典至少涵蓋 SAD/ANGRY/SURPRISED/EXCITED/THINKING/JOYFUL/PROUD"""
        required = [Emotion.SAD, Emotion.ANGRY, Emotion.SURPRISED, Emotion.EXCITED,
                    Emotion.THINKING, Emotion.JOYFUL, Emotion.PROUD]
        for emo in required:
            assert emo in STRONG_USER_SIGNALS, f"缺少 {emo} 的強信號關鍵字"


# ==================== Emoji + tag 過濾 ====================

class TestCleaning:
    """測 _clean_for_display（tag + emoji 過濾）"""

    def test_strips_emotion_tag(self, parser: EmotionParser):
        text = "[emotion:happy] 你好世界"
        clean, _, _ = parser.parse(text)
        assert "[emotion:happy]" not in clean
        assert "你好世界" in clean

    def test_strips_emoji(self, parser: EmotionParser):
        """Emoji 應該被清掉（Noto Sans TC 沒 glyph → □）"""
        text = "[emotion:happy] 你好 😀👍🌟"
        clean, _, _ = parser.parse(text)
        # EMOJI_PATTERN 涵蓋 U+1F000-1FFFF，所以 😀 (U+1F600) 應該被清
        assert "😀" not in clean
        assert "👍" not in clean
        assert "你好" in clean

    def test_collapses_extra_spaces_after_emoji_removal(self, parser: EmotionParser):
        """emoji 拿掉後不該留兩個空白"""
        text = "你好 😀 世界"
        clean, _, _ = parser.parse(text)
        assert "  " not in clean  # 不該有連續空白
        assert clean == "你好 世界"

    def test_keeps_chinese_punctuation(self, parser: EmotionParser):
        """中文標點（，。！？）不該被當 emoji 誤刪"""
        text = "你好，世界！今天怎麼樣？"
        clean, _, _ = parser.parse(text)
        assert clean == "你好，世界！今天怎麼樣？"


# ==================== Fallback 關鍵字 ====================

class TestFallbackKeyword:
    """測備援關鍵字比對"""

    def test_keyword_match_happy(self, parser: EmotionParser):
        text = "我今天好開心啊"
        emotion = parser._fallback_keyword(text)
        assert emotion == Emotion.HAPPY

    def test_keyword_match_sad(self, parser: EmotionParser):
        text = "唉 我很沮喪"
        emotion = parser._fallback_keyword(text)
        assert emotion == Emotion.SAD

    def test_keyword_no_match_returns_neutral(self, parser: EmotionParser):
        text = "今天星期一"
        emotion = parser._fallback_keyword(text)
        assert emotion == Emotion.NEUTRAL

    def test_keyword_count_picks_highest(self, parser: EmotionParser):
        """多個情緒詞出現時，選分數最高的"""
        # "哈哈哈" 是 JOYFUL 強信號，但 "好笑" 也是 JOYFUL — 應該 JOYFUL 勝
        text = "哈哈哈 太好笑了 lol"
        emotion = parser._fallback_keyword(text)
        assert emotion == Emotion.JOYFUL

    def test_keyword_substring_false_positive_known_bug(self, parser: EmotionParser):
        """jieba 斷詞後比對，「天氣」不會誤觸「氣」(angry)

        之前用純 substring matching 會誤判：
        - 「天氣」含「氣」→ 誤判 angry
        - 「氣球」、「開心」（含「開」）... 都有類似問題

        修法：jieba 斷詞後比對 token set，「天氣」斷成 [今天, 天氣, 還, 不錯]，
        token set 沒有獨立「氣」，不誤判。
        """
        emotion = parser._fallback_keyword("今天天氣還不錯")
        assert emotion == Emotion.NEUTRAL

    def test_keyword_balloon_no_false_positive(self, parser: EmotionParser):
        """「氣球」含「氣」也不該誤判 angry — jieba 切 [氣球]"""
        emotion = parser._fallback_keyword("我有一個紅色氣球")
        assert emotion == Emotion.NEUTRAL

    def test_keyword_angry_still_works(self, parser: EmotionParser):
        """「生氣」要能被正確抓到 angry — jieba 不切開"""
        emotion = parser._fallback_keyword("我好生氣")
        assert emotion == Emotion.ANGRY

    def test_strong_signal_user_chinese_angry(self, parser: EmotionParser):
        """user 說「我超生氣」要走 angry（jieba 不會切開「生氣」）"""
        _, emotion, _ = parser.parse("好的", user_input="我超生氣")
        assert emotion == Emotion.ANGRY

    def test_strong_signal_user_chinese_surprised(self, parser: EmotionParser):
        """user 說「真的嗎」要走 surprised（jieba 不會切開「真的嗎」）"""
        _, emotion, _ = parser.parse("好的", user_input="真的嗎?!")
        assert emotion == Emotion.SURPRISED


# ==================== to_live2d_signal ====================

class TestLive2DSignal:
    """測 to_live2d_signal 強度 clamp + 預設值"""

    def test_intensity_clamp_high(self, parser_no_mapping: EmotionParser):
        """intensity > 1 應該被 clamp 到 1.0"""
        sig = parser_no_mapping.to_live2d_signal(Emotion.HAPPY, intensity=2.5)
        assert sig.intensity == 1.0

    def test_intensity_clamp_low(self, parser_no_mapping: EmotionParser):
        """intensity < 0 應該被 clamp 到 0.0"""
        sig = parser_no_mapping.to_live2d_signal(Emotion.HAPPY, intensity=-0.5)
        assert sig.intensity == 0.0

    def test_default_intensity_when_no_mapping(self, parser_no_mapping: EmotionParser):
        sig = parser_no_mapping.to_live2d_signal(Emotion.HAPPY, intensity=0.5)
        # 沒有 mapping 時，duration_ms 預設 500
        assert sig.duration_ms == 500

    def test_signal_returns_live2d_signal_type(self, parser: EmotionParser):
        sig = parser.to_live2d_signal(Emotion.SAD, intensity=0.8)
        assert isinstance(sig, Live2DSignal)


# ==================== 載入 mapping 失敗處理 ====================

class TestMappingLoadFailure:
    """測 mapping 檔壞掉時不該 crash"""

    def test_nonexistent_mapping_file(self):
        """mapping 檔不存在 → 不 crash，給空 mapping"""
        parser = EmotionParser(mapping_file="/nonexistent.json")
        assert parser.mapping == {"emotion_map": {}}
        # 還是可以 parse（會用 keyword fallback）
        clean, emotion, _ = parser.parse("我好難過")
        assert emotion == Emotion.SAD


# ==================== Regex 自身 ====================

class TestRegex:
    """直接測 regex pattern（不透過 parser）"""

    def test_emotion_tag_pattern_matches(self):
        assert EMOTION_TAG_PATTERN.search("[emotion:happy]") is not None
        assert EMOTION_TAG_PATTERN.search("[EMOTION:SAD]") is not None
        assert EMOTION_TAG_PATTERN.search("no tag here") is None

    def test_emoji_pattern_matches_common_emoji(self):
        # 😀 U+1F600, 👍 U+1F44D, 🎉 U+1F389 — 都在 U+1F000-1FFFF 範圍
        assert EMOJI_PATTERN.search("😀")
        assert EMOJI_PATTERN.search("👍")
        assert EMOJI_PATTERN.search("🎉")
        # 中文不該被當 emoji
        assert EMOJI_PATTERN.search("你好") is None
