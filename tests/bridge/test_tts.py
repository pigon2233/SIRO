"""
tests/bridge/test_tts.py - TTS 模組測試 (v1.0 Core Experience Phase 1)

測試範圍:
- TTSConfig.from_persona(): 從 persona YAML 載入設定
- _split_sentences(): 句子切割
- EdgeTTSProvider: provider 介面
- PiperTTSProvider: provider 介面
- TTSOrchestrator: 自動選擇 provider
- voices.get_voice_for_persona: persona → voice_id 對應
- main.py /tts/* routes: API endpoints

設計:不真的呼叫 edge-tts 雲端(會慢、會 rate limit、會 network dep),
全部用 mock + 假資料測邏輯。
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 確保 import 路徑正確
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bridge.tts.base import TTSConfig, Voice, TTSProvider
from bridge.tts.stream import TTSOrchestrator, _split_sentences, get_tts_orchestrator
from bridge.tts.voices import (
    DEFAULT_VOICES,
    get_voice_for_persona,
    list_available_voices,
    invalidate_voice_cache,
)


# ============================================================
# TTSConfig
# ============================================================

class TestTTSConfig:
    def test_from_persona_full(self):
        persona = {
            "id": "siro-test",
            "language": "zh-TW",
            "voice": {
                "provider": "edge-tts",
                "voice_id": "zh-TW-HsiaoChenNeural",
                "speed": 1.2,
                "pitch": 1.0,
            },
        }
        cfg = TTSConfig.from_persona(persona)
        assert cfg.provider == "edge-tts"
        assert cfg.voice_id == "zh-TW-HsiaoChenNeural"
        assert cfg.language == "zh-TW"
        assert cfg.speed == 1.2
        assert cfg.pitch == 1.0

    def test_from_persona_defaults(self):
        """persona 沒寫 voice 段、走預設"""
        persona = {"id": "siro-test", "language": "en-US"}
        cfg = TTSConfig.from_persona(persona)
        assert cfg.provider == "edge-tts"
        assert cfg.voice_id == "zh-TW-HsiaoChenNeural"  # 預設繁中
        assert cfg.language == "en-US"

    def test_from_persona_model_alias(self):
        """persona 寫 voice.model 而非 voice_id、也要 work(向後相容)"""
        persona = {
            "voice": {"provider": "piper", "model": "zh_TW-hsiaochen-medium"},
        }
        cfg = TTSConfig.from_persona(persona)
        assert cfg.provider == "piper"
        assert cfg.voice_id == "zh_TW-hsiaochen-medium"


# ============================================================
# 句子切割
# ============================================================

class TestSplitSentences:
    def test_chinese_period(self):
        text = "你好,我是 SIRO。今天天氣真好。晚安!"
        result = _split_sentences(text)
        assert result == ["你好,我是 SIRO。", "今天天氣真好。", "晚安!"]

    def test_english_period(self):
        text = "Hello. How are you? I am fine!"
        result = _split_sentences(text)
        assert result == ["Hello.", "How are you?", "I am fine!"]

    def test_mixed(self):
        text = "你好.Mao? 我很好!"
        result = _split_sentences(text)
        # 中英混合標點
        assert any("Mao?" in s for s in result)

    def test_empty(self):
        assert _split_sentences("") == []
        assert _split_sentences("   ") == []

    def test_no_punctuation(self):
        """沒標點就整段當一句"""
        text = "你好 SIRO"
        result = _split_sentences(text)
        assert result == ["你好 SIRO"]


# ============================================================
# voices.get_voice_for_persona
# ============================================================

class TestGetVoiceForPersona:
    def test_explicit_voice_id(self):
        persona = {
            "voice": {
                "provider": "edge-tts",
                "voice_id": "en-US-JennyNeural",
            }
        }
        cfg = get_voice_for_persona(persona, provider="edge-tts")
        assert cfg.voice_id == "en-US-JennyNeural"

    def test_default_lookup(self):
        """persona 沒寫 voice_id、走 DEFAULT_VOICES 表"""
        persona = {
            "language": "ja-JP",
            "voice": {"provider": "edge-tts", "gender": "female"},
        }
        cfg = get_voice_for_persona(persona)
        assert cfg.voice_id == "ja-JP-NanamiNeural"

    def test_legacy_model_field(self):
        """向後相容:persona 用 voice.model 而非 voice.voice_id"""
        persona = {
            "voice": {"provider": "piper", "model": "en_US-amy-low"},
        }
        cfg = get_voice_for_persona(persona)
        assert cfg.provider == "piper"
        assert cfg.voice_id == "en_US-amy-low"

    def test_unknown_provider_falls_back_to_default(self):
        """查 DEFAULT_VOICES 沒對應時、走通用 fallback"""
        persona = {
            "language": "ko-KR",
            "voice": {"provider": "edge-tts", "gender": "female"},
        }
        cfg = get_voice_for_persona(persona)
        # 沒有 ko-KR 對應、應 fallback 到繁中或預設
        assert cfg.voice_id  # 至少不為空


# ============================================================
# TTSOrchestrator
# ============================================================

class FakeTTSProvider:
    """測試用 fake TTS provider"""
    def __init__(self, name: str, available: bool = True, chunks: list[bytes] = None):
        self.name = name
        self._available = available
        self._chunks = chunks or [b"chunk1", b"chunk2", b"chunk3"]
        self.synthesize_call_count = 0
        self.synthesize_last_text = None
        self.synthesize_last_config = None

    async def synthesize(self, text, config):
        self.synthesize_call_count += 1
        self.synthesize_last_text = text
        self.synthesize_last_config = config
        for c in self._chunks:
            yield c

    async def list_voices(self, language=""):
        return [
            Voice(id="v1", name="V1", language="zh-TW", provider=self.name),
            Voice(id="v2", name="V2", language="en-US", provider=self.name),
        ]

    async def is_available(self) -> bool:
        return self._available


class TestTTSOrchestrator:
    def test_active_provider_selection(self):
        p1 = FakeTTSProvider("first", available=False)
        p2 = FakeTTSProvider("second", available=True)
        orch = TTSOrchestrator(providers=[p1, p2])
        active = asyncio.run(orch.get_active_provider())
        assert active.name == "second"

    def test_all_providers_unavailable_falls_back_to_first(self):
        p1 = FakeTTSProvider("first", available=False)
        p2 = FakeTTSProvider("second", available=False)
        orch = TTSOrchestrator(providers=[p1, p2])
        active = asyncio.run(orch.get_active_provider())
        # 全部不可用、還是回傳第一個(給 caller 拿到合理錯誤)
        assert active.name == "first"

    def test_synthesize_stream_yields_all_chunks(self):
        p = FakeTTSProvider("test", chunks=[b"a", b"b", b"c"])
        orch = TTSOrchestrator(providers=[p])
        cfg = TTSConfig(voice_id="test", language="zh-TW")

        async def collect():
            collected = []
            async for chunk in orch.synthesize_stream("hello", cfg):
                collected.append(chunk)
            return collected

        result = asyncio.run(collect())
        assert result == [b"a", b"b", b"c"]
        assert p.synthesize_call_count == 1
        assert p.synthesize_last_text == "hello"

    def test_synthesize_sentence_stream_segments_text(self):
        p = FakeTTSProvider("test")
        orch = TTSOrchestrator(providers=[p])
        cfg = TTSConfig(voice_id="test", language="zh-TW")

        async def collect():
            results = []
            async for sentence, chunk in orch.synthesize_sentence_stream(
                "你好.我是 SIRO.今天天氣好.", cfg
            ):
                results.append((sentence, chunk))
            return results

        result = asyncio.run(collect())
        # 應該切成 3 句
        sentences = [s for s, _ in result]
        assert "你好." in sentences
        assert "我是 SIRO." in sentences
        assert "今天天氣好." in sentences
        # 每句都應該有 audio chunk
        assert len([c for _, c in result if c]) >= 3

    def test_synthesize_stream_strips_emotion_tag(self):
        """Phase 1.5.2a: TTS 進 provider 前要清掉 [emotion:xxx]"""
        from bridge.tts.stream import _clean_for_tts
        assert _clean_for_tts("[emotion:happy] 你好！") == "你好！"
        assert _clean_for_tts("[emotion:neutral] 今天天氣真好") == "今天天氣真好"
        assert _clean_for_tts("我[emotion:sad]很難過") == "我很難過"
        # 沒標籤就原樣
        assert _clean_for_tts("你好世界") == "你好世界"

    def test_synthesize_stream_strips_emoji(self):
        """Phase 1.5.2a: 也要清掉 emoji(Unity TMP 顯示成 □、TTS 唸出來也怪)"""
        from bridge.tts.stream import _clean_for_tts
        # emoji 拿掉後 re.sub 會把連續空白壓成 1 個
        assert _clean_for_tts("你好 😀 世界") == "你好 世界"
        assert _clean_for_tts("完成 ✅ 任務") == "完成 任務"

    def test_synthesize_stream_passes_clean_text_to_provider(self):
        """整合測試:synthesize_stream 收到的 text 經過 strip 才送給 provider"""
        p = FakeTTSProvider("test")
        orch = TTSOrchestrator(providers=[p])
        cfg = TTSConfig(voice_id="test", language="zh-TW", provider="test")

        async def collect():
            chunks = []
            async for c in orch.synthesize_stream("[emotion:happy] 你好世界！", cfg):
                chunks.append(c)
            return chunks

        result = asyncio.run(collect())
        # provider 收到的 text 已經清過
        assert p.synthesize_last_text == "你好世界！"
        assert len(result) == 3  # 預設 chunks

    def test_synthesize_stream_skips_when_clean_is_empty(self):
        """只有 [emotion:xxx] tag、clean 後是空 → 跳過 provider、不噴 chunk"""
        p = FakeTTSProvider("test")
        orch = TTSOrchestrator(providers=[p])
        cfg = TTSConfig(voice_id="test", language="zh-TW", provider="test")

        async def collect():
            chunks = []
            async for c in orch.synthesize_stream("[emotion:happy]", cfg):
                chunks.append(c)
            return chunks

        result = asyncio.run(collect())
        assert result == []
        # provider 不該被叫
        assert p.synthesize_call_count == 0

    def test_synthesize_sentence_stream_strips_tags_before_splitting(self):
        """synthesize_sentence_stream 也要先 strip 再切句(避免 [emotion:xxx] 殘留)"""
        from bridge.tts.stream import _clean_for_tts
        # 直接測 _clean_for_tts 對多句 prefix 的處理
        raw = "[emotion:happy] 你好.我是 SIRO.[emotion:neutral] 今天好."
        cleaned = _clean_for_tts(raw)
        assert "[emotion:" not in cleaned
        # strip 後 tag 變空白、會被 [ \t]+ 壓成單一空白
        assert cleaned == "你好.我是 SIRO. 今天好."


# ============================================================
# EdgeTTSProvider (mock edge-tts)
# ============================================================

class TestEdgeTTSProvider:
    def test_synthesize_chunks_via_edge_tts(self):
        """mock edge-tts.Communicate.stream() 回傳 audio chunks"""
        from bridge.tts.edge_tts import EdgeTTSProvider

        # 建立 mock edge_tts module
        mock_edge_tts = MagicMock()
        mock_communicate = MagicMock()

        async def mock_stream():
            yield {"type": "audio", "data": b"audio_chunk_1"}
            yield {"type": "audio", "data": b"audio_chunk_2"}
            yield {"type": "SentenceBoundary"}

        # edge-tts.Communicate.stream() 是 async generator
        async def mock_stream_method():
            async for chunk in mock_stream():
                yield chunk

        mock_communicate.stream = mock_stream_method
        mock_edge_tts.Communicate = MagicMock(return_value=mock_communicate)
        mock_edge_tts.list_voices = MagicMock(return_value=[
            {
                "ShortName": "zh-TW-HsiaoChenNeural",
                "FriendlyName": "Microsoft HsiaoChen Online (Natural) - Chinese (Traditional, Taiwan)",
                "Locale": "zh-TW",
                "Gender": "Female",
            }
        ])

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            provider = EdgeTTSProvider()
            cfg = TTSConfig(
                provider="edge-tts",
                voice_id="zh-TW-HsiaoChenNeural",
                language="zh-TW",
            )

            async def collect():
                return [chunk async for chunk in provider.synthesize("hello", cfg)]

            chunks = asyncio.run(collect())
            assert chunks == [b"audio_chunk_1", b"audio_chunk_2"]

    def test_auto_voice_neural_suffix(self):
        """voice_id 沒 Neural 結尾、會自動補"""
        from bridge.tts.edge_tts import EdgeTTSProvider

        mock_edge_tts = MagicMock()
        mock_communicate = MagicMock()

        async def empty_stream():
            if False:
                yield None
            return

        mock_communicate.stream = empty_stream
        mock_edge_tts.Communicate = MagicMock(return_value=mock_communicate)

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            provider = EdgeTTSProvider()
            cfg = TTSConfig(
                provider="edge-tts",
                voice_id="zh-TW-HsiaoChen",  # 沒 Neural 結尾
                language="zh-TW",
            )
            asyncio.run(provider.synthesize("test", cfg).__aiter__() if False else _drain(provider, cfg))
            # Verify Communicate called with "zh-TW-HsiaoChenNeural"
            called_args = mock_edge_tts.Communicate.call_args
            assert called_args.kwargs["voice"] == "zh-TW-HsiaoChenNeural"


async def _drain(provider, cfg):
    """把 async generator 抽乾(測試用)"""
    async for _ in provider.synthesize("test", cfg):
        pass


# ============================================================
# PiperTTSProvider
# ============================================================

class TestPiperTTSProvider:
    def test_synthesize_file_not_found(self, tmp_path):
        from bridge.tts.piper_tts import PiperTTSProvider
        provider = PiperTTSProvider(models_dir=tmp_path)
        cfg = TTSConfig(
            provider="piper",
            voice_id="zh_TW-hsiaochen-medium",
            language="zh-TW",
        )
        with pytest.raises(FileNotFoundError, match="Piper 聲線模型找不到"):
            async def collect():
                return [chunk async for chunk in provider.synthesize("hello", cfg)]
            asyncio.run(collect())

    def test_list_voices_scans_models_dir(self, tmp_path):
        """list_voices 掃描 models_dir/ 找出 .onnx 檔"""
        from bridge.tts.piper_tts import PiperTTSProvider
        # 建假 .onnx 檔
        (tmp_path / "zh_TW-hsiaochen-medium.onnx").touch()
        (tmp_path / "en_US-amy-low.onnx").touch()
        # 雜檔
        (tmp_path / "README.md").touch()

        provider = PiperTTSProvider(models_dir=tmp_path)
        voices = asyncio.run(provider.list_voices())
        assert len(voices) == 2
        voice_ids = {v.id for v in voices}
        assert "zh_TW-hsiaochen-medium" in voice_ids
        assert "en_US-amy-low" in voice_ids
        # 語言 parse: 從 ID 第一段(zh_TW / en_US)
        zh_voice = next(v for v in voices if v.id.startswith("zh_TW"))
        assert zh_voice.language == "zh_TW"

    def test_is_available_with_models(self, tmp_path):
        from bridge.tts.piper_tts import PiperTTSProvider
        provider = PiperTTSProvider(models_dir=tmp_path)
        # 沒模型 → False
        assert asyncio.run(provider.is_available()) is False
        # 加模型 → True
        (tmp_path / "test.onnx").touch()
        assert asyncio.run(provider.is_available()) is True


# ============================================================
# Global orchestrator singleton
# ============================================================

class TestGetTTSOrchestrator:
    def test_returns_singleton(self):
        invalidate_voice_cache() if hasattr(invalidate_voice_cache, "__call__") else None
        # reset module-level singleton
        import bridge.tts.stream as stream_mod
        stream_mod._orchestrator = None
        o1 = get_tts_orchestrator()
        o2 = get_tts_orchestrator()
        assert o1 is o2


# ============================================================
# Default voices table consistency
# ============================================================

class TestDefaultVoicesConsistency:
    def test_all_default_voices_end_with_neural_or_low(self):
        """edge-tts 預設 voice_id 都該是 Neural 結尾"""
        neural_count = 0
        for (provider, lang, gender), vid in DEFAULT_VOICES.items():
            if provider == "edge-tts":
                assert vid.endswith("Neural"), \
                    f"edge-tts voice {vid} 沒 Neural 結尾"
                neural_count += 1
        assert neural_count >= 6  # 至少 6 個 edge-tts 預設(zh-TW/zh-CN/en-US/ja-JP × 2 性別)
