"""
bridge/tts/voices.py - 聲線 cache + persona → voice_id mapping

集中管理:
- 跨 provider 統一 voice_id 命名(用 provider 自己的格式)
- persona YAML 寫「我要繁中女聲」、TTS layer 自動 translate 到具體 provider 的 voice_id
- voice list cache(避免重複呼叫 edge-tts list_voices API)
"""

from __future__ import annotations

import logging
from typing import Any

from .base import TTSConfig, Voice

logger = logging.getLogger(__name__)


# 預設聲線表(persona YAML 沒指定時用)
# 命名 = (provider, language, gender, quality) → voice_id
DEFAULT_VOICES: dict[tuple[str, str, str], str] = {
    # edge-tts (雲端、預設)
    ("edge-tts", "zh-TW", "female"): "zh-TW-HsiaoChenNeural",
    ("edge-tts", "zh-TW", "male"): "zh-TW-HsiaoJhenNeural",
    ("edge-tts", "zh-CN", "female"): "zh-CN-XiaoxiaoNeural",
    ("edge-tts", "zh-CN", "male"): "zh-CN-YunxiNeural",
    ("edge-tts", "en-US", "female"): "en-US-JennyNeural",
    ("edge-tts", "en-US", "male"): "en-US-GuyNeural",
    ("edge-tts", "ja-JP", "female"): "ja-JP-NanamiNeural",
    ("edge-tts", "ja-JP", "male"): "ja-JP-KeitaNeural",
    # Piper (本地 fallback)
    ("piper", "zh-TW", "female"): "zh_TW-hsiaochen-medium",
    ("piper", "zh-TW", "male"): "zh_TW-hsiaochen-medium",
    ("piper", "en-US", "female"): "en_US-amy-low",
    ("piper", "en-US", "male"): "en_US-ryan-low",
    # GPT-SoVITS (v1.0 polish)
    ("gpt-sovits", "zh-TW", "female"): "mao-clone",
    # F5-TTS (Phase 1.5 本地高品質、zero-shot voice clone)
    ("f5-tts", "zh-TW", "female"): "mao-clone",
    ("f5-tts", "zh-TW", "male"): "user-clone",
}


def get_voice_for_persona(
    persona_config: dict[str, Any], provider: str = "edge-tts"
) -> TTSConfig:
    """從 persona YAML 取得 TTS 設定

    Logic:
    1. persona.voice.voice_id 寫了具體 ID → 用
    2. persona.voice.provider 寫了但 voice_id 空 → 用 DEFAULT_VOICES 預設
    3. 什麼都沒寫 → 預設繁中女聲
    """
    voice = persona_config.get("voice", {})
    explicit_id = voice.get("voice_id") or voice.get("model")
    explicit_provider = voice.get("provider", provider)
    language = persona_config.get("language", "zh-TW")
    gender = voice.get("gender", "female")  # 預設女聲、Mao 是女的

    if explicit_id and explicit_id != "none":
        voice_id = explicit_id
    else:
        # 查預設表
        key = (explicit_provider, language.split("-")[0] + "-" + language.split("-")[1] if "-" in language else language, gender)
        voice_id = DEFAULT_VOICES.get(key) or DEFAULT_VOICES.get(
            (explicit_provider, language, "female"), "zh-TW-HsiaoChenNeural"
        )

    return TTSConfig(
        provider=explicit_provider,
        voice_id=voice_id,
        language=language,
        speed=voice.get("speed", 1.0),
        pitch=voice.get("pitch", 0.0),
    )


_voice_cache: dict[str, list[Voice]] = {}


async def list_available_voices(
    provider_name: str = "edge-tts", language: str = ""
) -> list[Voice]:
    """列出可用聲線(快取 5 分鐘)

    Args:
        provider_name: edge-tts / piper / gpt-sovits
        language: 過濾語言(空 = 全部)
    """
    cache_key = f"{provider_name}:{language}"
    if cache_key in _voice_cache:
        return _voice_cache[cache_key]

    # 找 provider
    from .stream import get_tts_orchestrator
    orchestrator = get_tts_orchestrator()
    for p in orchestrator.providers:
        if p.name == provider_name:
            voices = await p.list_voices(language=language)
            _voice_cache[cache_key] = voices
            return voices
    return []


def invalidate_voice_cache() -> None:
    """手動清聲線 cache(測試用、或 persona 切換大量時)"""
    _voice_cache.clear()
    logger.info("[voices] cache invalidated")
