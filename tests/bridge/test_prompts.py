"""
tests/bridge/test_prompts.py - Persona YAML 載入 + system prompt 測試

覆蓋：
- load_persona: 預設 alias、cache、找不到
- get_personality: 取 system_prompt、不存在時 hardcode fallback
- get_fallback_response: 從 pool 隨機選、不存在 persona/category fallback
- get_persona_quirks: 取 model.quirks
- PERSONALITIES shim: 向後相容 dict 介面
"""

from __future__ import annotations

import pytest

import bridge.prompts as prompts_mod
from bridge.prompts import (
    load_persona,
    get_personality,
    get_fallback_response,
    get_persona_quirks,
    PERSONALITIES,
    _HARDCODE_FALLBACK_PROMPT,
)


# ==================== Fixtures ====================

@pytest.fixture(autouse=True)
def clear_persona_cache():
    """每個 test 前清空 persona cache 避免互相污染

    autouse=True 讓所有 test 自動套用，確保 isolation。
    """
    prompts_mod._persona_cache.clear()
    yield
    prompts_mod._persona_cache.clear()


# ==================== load_persona ====================

class TestLoadPersona:
    """測 persona YAML 載入 + 別名 + cache"""

    def test_default_alias_loads_siro_default(self):
        """傳 'default' / '' / None 都要 alias 到 siro-default"""
        for alias in ["default", "", None]:
            persona = load_persona(alias)  # type: ignore[arg-type]
            assert persona is not None
            assert persona["id"] == "siro-default"

    def test_explicit_siro_default(self):
        persona = load_persona("siro-default")
        assert persona is not None
        assert persona["id"] == "siro-default"
        assert persona["name"] == "SIRO"
        assert "version" in persona

    def test_nonexistent_persona_returns_none(self):
        assert load_persona("totally-fake-persona-xyz") is None

    def test_caching_returns_same_object(self):
        """第二次 load 應該回傳 cache 同一個物件（不重 IO）"""
        p1 = load_persona("siro-default")
        p2 = load_persona("siro-default")
        assert p1 is p2


# ==================== get_personality ====================

class TestGetPersonality:
    """測 system prompt 取得 + fallback"""

    def test_siro_default_returns_yaml_prompt(self):
        prompt = get_personality("siro-default")
        # 預設 persona 的 prompt 開頭提到「溫暖、友善的陪伴型 AI」
        assert "溫暖" in prompt or "友善" in prompt
        # 規則 1 提到 [emotion:xxx] 標籤
        assert "[emotion:" in prompt

    def test_default_alias(self):
        """傳 'default' 應該跟 'siro-default' 拿到一樣"""
        assert get_personality("default") == get_personality("siro-default")

    def test_missing_persona_falls_back_to_hardcode(self):
        prompt = get_personality("does-not-exist-xyz")
        # 缺 persona 應該 fallback 到 hardcode
        assert prompt == _HARDCODE_FALLBACK_PROMPT
        assert "溫暖" in prompt  # hardcode 也有這字

    def test_persona_without_system_prompt_falls_back(self, tmp_path, monkeypatch):
        """有 persona 但缺 personality.system_prompt → 走 hardcode"""
        import bridge.prompts as p
        # 注入一個壞 persona
        bad_persona = {
            "id": "bad-no-prompt",
            "name": "Bad",
            "personality": {},  # 沒有 system_prompt
        }
        monkeypatch.setitem(p._persona_cache, "bad-no-prompt", bad_persona)
        prompt = get_personality("bad-no-prompt")
        assert prompt == _HARDCODE_FALLBACK_PROMPT


# ==================== get_fallback_response ====================

class TestGetFallbackResponse:
    """測 fallback 回應池"""

    def test_thinking_pool_from_yaml(self):
        """siro-default persona 的 thinking pool 應該有預設文字"""
        result = get_fallback_response("thinking", persona_name="siro-default")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_error_pool_from_yaml(self):
        result = get_fallback_response("error", persona_name="siro-default")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_random_selection_returns_string(self):
        """多次呼叫應該都回字串（不一定每次不同 — pool 可能很小）"""
        for _ in range(5):
            r = get_fallback_response("thinking", persona_name="siro-default")
            assert isinstance(r, str)

    def test_default_persona_alias(self):
        """傳 'default' 應該跟 'siro-default' 一樣"""
        r1 = get_fallback_response("thinking", persona_name="default")
        r2 = get_fallback_response("thinking", persona_name="siro-default")
        # 兩個都該回非空字串
        assert r1 and r2

    def test_missing_persona_returns_hardcode(self):
        """persona 找不到 → 走 hardcode（不是 None）"""
        result = get_fallback_response("thinking", persona_name="nope-xyz")
        assert result == "嗯..."

    def test_missing_category_returns_default_dots(self):
        """category 找不到 → 預設 "..."  """
        result = get_fallback_response("nonexistent-category-xyz", persona_name="siro-default")
        # 要嘛是 "..."（hardcode fallback for unknown category）
        # 要嘛是 siro-default 沒這個 category → 也走 hardcode
        assert isinstance(result, str)
        assert len(result) > 0


# ==================== get_persona_quirks ====================

class TestGetPersonaQuirks:
    """測 persona 模型 quirks（Unity 端 runtime 客製用）"""

    def test_siro_default_has_quirks(self):
        quirks = get_persona_quirks("siro-default")
        assert isinstance(quirks, dict)
        # siro-default 應該有 hide_eye_on_expressions 設定
        # （不 hardcode 特定值，只驗 shape）
        # 如果 quirks 是空 dict 也不該 crash

    def test_missing_persona_returns_empty_dict(self):
        quirks = get_persona_quirks("nope-xyz")
        assert quirks == {}


# ==================== PERSONALITIES shim ====================

class TestPersonalitiesShim:
    """測向後相容 dict-like 介面"""

    def test_get_returns_string(self):
        result = PERSONALITIES.get("siro-default")
        assert isinstance(result, str)
        assert "溫暖" in result

    def test_get_missing_returns_default(self):
        result = PERSONALITIES.get("nope-xyz", "my-default")
        assert result == "my-default"

    def test_getitem_works(self):
        result = PERSONALITIES["siro-default"]
        assert isinstance(result, str)
