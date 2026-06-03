"""
tests/bridge/test_models.py - Pydantic schema 驗證測試

覆蓋：
- ChatRequest：必填、選填、長度限制
- ChatResponse：必填欄位、enum 驗證、intensity 範圍
- Live2DSignal：intensity clamp
- Emotion enum：所有 9 種值都存在
- HealthResponse：default 值
- ErrorResponse：選填 detail
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bridge.models import (
    ChatRequest,
    ChatResponse,
    Live2DSignal,
    HealthResponse,
    ErrorResponse,
    Emotion,
)


# ==================== Emotion enum ====================

class TestEmotionEnum:
    """測 9 種情緒值都存在且唯一"""

    def test_all_nine_emotions_present(self):
        expected = {
            "happy", "joyful", "proud", "excited", "sad",
            "thinking", "surprised", "angry", "neutral",
        }
        actual = {e.value for e in Emotion}
        assert actual == expected

    def test_emotion_values_unique(self):
        values = [e.value for e in Emotion]
        assert len(values) == len(set(values)), "情緒值有重複"

    def test_emotion_is_string_compatible(self):
        """Emotion 繼承 str enum，應該可以當 str 用"""
        assert Emotion.HAPPY == "happy"
        assert str(Emotion.HAPPY) == "Emotion.HAPPY"


# ==================== Live2DSignal ====================

class TestLive2DSignal:
    """測 Live2DSignal schema 驗證"""

    def test_required_fields(self):
        sig = Live2DSignal(expression_id="F02")
        assert sig.expression_id == "F02"
        assert sig.intensity == 0.7  # 預設值
        assert sig.duration_ms == 500  # 預設值
        assert sig.motion_group is None  # 選填
        assert sig.motion_index is None  # 選填

    def test_intensity_valid_range(self):
        sig = Live2DSignal(expression_id="F01", intensity=0.0)
        assert sig.intensity == 0.0
        sig = Live2DSignal(expression_id="F01", intensity=1.0)
        assert sig.intensity == 1.0

    def test_intensity_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            Live2DSignal(expression_id="F01", intensity=-0.1)

    def test_intensity_above_one_rejected(self):
        with pytest.raises(ValidationError):
            Live2DSignal(expression_id="F01", intensity=1.5)

    def test_duration_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            Live2DSignal(expression_id="F01", duration_ms=-100)

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            Live2DSignal()  # expression_id 必填


# ==================== ChatRequest ====================

class TestChatRequest:
    """測 ChatRequest 必填 + 選填 + 長度限制"""

    def test_minimal_valid_request(self):
        req = ChatRequest(message="hi")
        assert req.message == "hi"
        assert req.user_id == "default"  # 預設
        assert req.session_id is None
        assert req.personality is None

    def test_all_fields_provided(self):
        req = ChatRequest(
            message="hello",
            user_id="alice",
            session_id="alice-1234",
            personality="friendly_companion",
        )
        assert req.user_id == "alice"
        assert req.session_id == "alice-1234"
        assert req.personality == "friendly_companion"

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_message_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="x" * 2001)

    def test_message_at_max_length_accepted(self):
        req = ChatRequest(message="x" * 2000)
        assert len(req.message) == 2000

    def test_chinese_message_accepted(self):
        """中文不該被卡（max_length 是 char count 不是 byte）"""
        req = ChatRequest(message="你好世界")
        assert req.message == "你好世界"


# ==================== ChatResponse ====================

class TestChatResponse:
    """測 ChatResponse 必填 + enum 驗證"""

    def _make_signal(self) -> Live2DSignal:
        return Live2DSignal(expression_id="F01", intensity=0.5)

    def test_minimal_valid_response(self):
        resp = ChatResponse(
            text="你好",
            emotion=Emotion.HAPPY,
            live2d=self._make_signal(),
            session_id="s1",
            user_id="u1",
        )
        assert resp.text == "你好"
        assert resp.emotion == Emotion.HAPPY
        assert resp.intensity == 0.7  # 預設

    def test_emotion_must_be_valid_enum(self):
        with pytest.raises(ValidationError):
            ChatResponse(
                text="x",
                emotion="not_a_real_emotion",  # type: ignore[arg-type]
                live2d=self._make_signal(),
                session_id="s1",
                user_id="u1",
            )

    def test_all_emotions_accepted(self):
        """9 種情緒都該被接受"""
        for emo in Emotion:
            resp = ChatResponse(
                text="x",
                emotion=emo,
                live2d=self._make_signal(),
                session_id="s1",
                user_id="u1",
            )
            assert resp.emotion == emo

    def test_raw_response_optional(self):
        resp = ChatResponse(
            text="x",
            emotion=Emotion.NEUTRAL,
            live2d=self._make_signal(),
            session_id="s1",
            user_id="u1",
        )
        assert resp.raw_response is None

    def test_intensity_range_validated(self):
        with pytest.raises(ValidationError):
            ChatResponse(
                text="x",
                emotion=Emotion.NEUTRAL,
                intensity=2.0,  # 超過 1
                live2d=self._make_signal(),
                session_id="s1",
                user_id="u1",
            )


# ==================== HealthResponse ====================

class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse(status="ok", hermes_available=True)
        assert h.status == "ok"
        assert h.hermes_version is None
        assert h.bridge_version == "0.1.0"

    def test_with_hermes_version(self):
        h = HealthResponse(
            status="degraded",
            hermes_available=False,
            hermes_version="1.0.0",
        )
        assert h.hermes_version == "1.0.0"


# ==================== ErrorResponse ====================

class TestErrorResponse:
    def test_minimal(self):
        e = ErrorResponse(error="bad")
        assert e.error == "bad"
        assert e.detail is None

    def test_with_detail(self):
        e = ErrorResponse(error="bad", detail="more info")
        assert e.detail == "more info"
