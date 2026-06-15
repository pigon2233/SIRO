"""
bridge/tts - TTS (Text-to-Speech) 抽象層 (Core Experience v1.0 Phase 1)

設計:Tier 1 edge-tts 雲端(預設) → Tier 2 Piper 本地(fallback) → Tier 3 GPT-SoVITS 動漫聲線

用法:
    from bridge.tts import get_tts_orchestrator, TTSConfig

    orchestrator = get_tts_orchestrator()
    config = TTSConfig.from_persona(persona)

    async for audio_chunk in orchestrator.synthesize_stream(
        text="你好,我是 SIRO。",
        config=config,
    ):
        # audio_chunk 是 MP3 bytes,推給 Unity 端播放
        ...

詳細設計見 docs/TTS_INTEGRATION.md
"""

from .base import TTSProvider, TTSConfig, Voice
from .stream import TTSOrchestrator, get_tts_orchestrator
from .voices import (
    get_voice_for_persona,
    list_available_voices,
    invalidate_voice_cache,
)

__all__ = [
    "TTSProvider",
    "TTSConfig",
    "Voice",
    "TTSOrchestrator",
    "get_tts_orchestrator",
    "get_voice_for_persona",
    "list_available_voices",
    "invalidate_voice_cache",
]
