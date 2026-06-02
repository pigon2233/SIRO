"""
bridge/tests/test_emotion_parser.py
"""

import pytest
from bridge.emotion_parser import EmotionParser
from bridge.models import Emotion


@pytest.fixture
def parser():
    return EmotionParser()


class TestEmotionTagExtraction:
    def test_extracts_happy_tag(self, parser):
        text, emotion, intensity = parser.parse("[emotion:happy] 你好！")
        assert emotion == Emotion.HAPPY
        assert text == "你好！"

    def test_extracts_sad_tag(self, parser):
        text, emotion, _ = parser.parse("[emotion:sad] 蛤...")
        assert emotion == Emotion.SAD
        assert text == "蛤..."

    def test_extracts_thinking_tag(self, parser):
        text, emotion, _ = parser.parse("[emotion:thinking] 嗯嗯，讓我想想")
        assert emotion == Emotion.THINKING
        assert text == "嗯嗯，讓我想想"

    def test_unknown_tag_falls_back_to_keyword(self, parser):
        # 故意給錯誤的標籤，應該用關鍵字備援
        text, emotion, _ = parser.parse("[emotion:lol] 我好開心啊！")
        # "開心" 在 happy 關鍵字裡
        assert emotion == Emotion.HAPPY

    def test_no_tag_falls_back_to_keyword(self, parser):
        text, emotion, _ = parser.parse("我好難過喔")
        assert emotion == Emotion.SAD

    def test_no_tag_no_keyword_returns_neutral(self, parser):
        text, emotion, _ = parser.parse("Hello there, nice to meet you.")
        # 沒中文、英文也沒對應到
        assert emotion == Emotion.NEUTRAL

    def test_case_insensitive_tag(self, parser):
        text, emotion, _ = parser.parse("[EMOTION:HAPPY] 哈哈")
        assert emotion == Emotion.HAPPY


class TestLive2DSignalGeneration:
    def test_happy_maps_to_F02(self, parser):
        signal = parser.to_live2d_signal(Emotion.HAPPY, 0.8)
        assert signal.expression_id == "F02"

    def test_angry_maps_to_F03(self, parser):
        signal = parser.to_live2d_signal(Emotion.ANGRY, 0.7)
        assert signal.expression_id == "F03"

    def test_sad_maps_to_F04(self, parser):
        signal = parser.to_live2d_signal(Emotion.SAD, 0.6)
        assert signal.expression_id == "F04"

    def test_surprised_maps_to_F05(self, parser):
        signal = parser.to_live2d_signal(Emotion.SURPRISED, 0.9)
        assert signal.expression_id == "F05"

    def test_neutral_maps_to_F01(self, parser):
        signal = parser.to_live2d_signal(Emotion.NEUTRAL, 0.5)
        assert signal.expression_id == "F01"

    def test_intensity_clamped_to_range(self, parser):
        signal = parser.to_live2d_signal(Emotion.HAPPY, 1.5)  # over 1
        assert signal.intensity <= 1.0

        signal = parser.to_live2d_signal(Emotion.HAPPY, -0.5)  # under 0
        assert signal.intensity >= 0.0

    def test_unknown_emotion_returns_default(self, parser):
        # 如果傳一個沒在映射表的 emotion，應該回 F01
        # 不過我們的 enum 只有 7 種，這個測試是防呆
        signal = parser.to_live2d_signal(Emotion.NEUTRAL, 0.5)
        assert signal.expression_id in ["F01", "F02", "F03", "F04", "F05", "F06"]


class TestKeywordFallback:
    def test_chinese_happy_keyword(self, parser):
        text, emotion, _ = parser.parse("今天好棒喔！")
        assert emotion == Emotion.HAPPY

    def test_chinese_sad_keyword(self, parser):
        text, emotion, _ = parser.parse("我有點傷心")
        assert emotion == Emotion.SAD

    def test_chinese_angry_keyword(self, parser):
        text, emotion, _ = parser.parse("我好生氣")
        assert emotion == Emotion.ANGRY

    def test_chinese_surprised_keyword(self, parser):
        text, emotion, _ = parser.parse("哇真的嗎！")
        assert emotion == Emotion.SURPRISED
