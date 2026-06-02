"""
bridge/tests/test_prompts.py

測試 prompt 模板的結構完整性。
"""

from bridge.prompts import (
    SYSTEM_PROMPT_BASE,
    PERSONALITIES,
    get_personality,
)


class TestPrompts:
    def test_base_prompt_contains_emotion_tag_instruction(self):
        """Base prompt 必須明確要求 emotion 標籤"""
        assert "[emotion:" in SYSTEM_PROMPT_BASE

    def test_base_prompt_lists_all_emotions(self):
        """Base prompt 必須列出所有 7 種情緒"""
        for emotion in ["happy", "sad", "angry", "surprised", "thinking", "excited", "neutral"]:
            assert emotion in SYSTEM_PROMPT_BASE, f"prompt 缺少 {emotion}"

    def test_base_prompt_has_examples(self):
        """要有範例對話，讓 LLM 學習"""
        # 至少 3 個範例
        example_count = SYSTEM_PROMPT_BASE.count("[emotion:")
        assert example_count >= 4  # 1 個說明 + 至少 3 個範例

    def test_base_prompt_not_empty(self):
        assert len(SYSTEM_PROMPT_BASE) > 100

    def test_personalities_dict_has_default(self):
        assert "default" in PERSONALITIES

    def test_personalities_dict_has_friendly_companion(self):
        assert "friendly_companion" in PERSONALITIES

    def test_get_personality_returns_default_for_unknown(self):
        """未知名稱應該 fallback 到 base prompt"""
        result = get_personality("nonexistent-personality")
        assert result == SYSTEM_PROMPT_BASE

    def test_get_personality_returns_named_personality(self):
        result = get_personality("friendly_companion")
        assert result == SYSTEM_PROMPT_BASE  # v0 只有一個 personality

    def test_all_personalities_have_emotion_instructions(self):
        """所有 personality 都必須有 emotion 標籤規則"""
        for name, prompt in PERSONALITIES.items():
            assert "[emotion:" in prompt, f"personality '{name}' 缺 emotion 標籤規則"
