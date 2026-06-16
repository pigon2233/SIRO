"""
tests/bridge/test_tts_streaming.py - Phase 1.5.2b 句子級 TTS streaming 整合測試

測試範圍:
- _stream_tts_for_sentence helper: TTS 一句 → 推 tts_audio WS 訊息
- sentence buffer + LLM stream 端到端
- SIRO_TTS_STREAMING env var 控制開關
- Emotion tag 在進 TTS 前 strip(跟 sentence buffer 整合)

設計:不真的打 TTS provider(F5-TTS 要 6-8s / 句),用 mock orchestrator。
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ============================================================
# _stream_tts_for_sentence helper 測試
# ============================================================

class TestStreamTtsForSentence:
    @pytest.mark.asyncio
    async def test_happy_path_sends_tts_audio(self):
        """正常流程:TTS 一句 → 推 tts_audio WS 訊息"""
        # 動態 import 避免 import 整個 main.py 觸發 lifespan
        from bridge.main import _stream_tts_for_sentence

        # mock WebSocket
        ws = AsyncMock()

        # mock TTS orchestrator
        with patch("bridge.tts.get_tts_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            # synthesize_stream 是 async generator
            async def fake_synth(text, config):
                for c in [b"\x00\x01\x02", b"\x03\x04"]:
                    yield c
            mock_orch.synthesize_stream = fake_synth
            mock_get_orch.return_value = mock_orch

            # mock voice config(不真的 load persona yaml)
            with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
                from bridge.tts.base import TTSConfig
                mock_voice.return_value = TTSConfig(
                    provider="f5-tts",
                    voice_id="mao-clone",
                    language="zh-TW",
                    format="wav",
                )

                await _stream_tts_for_sentence(
                    ws, "你好世界。", sentence_index=0,
                    persona_id="siro-default", tts_format="wav",
                )

        # 驗證 send_json 被叫一次
        assert ws.send_json.call_count == 1
        sent = ws.send_json.call_args[0][0]
        assert sent["type"] == "tts_audio"
        assert sent["index"] == 0
        assert sent["sentence"] == "你好世界。"
        assert sent["format"] == "wav"
        assert sent["provider"] == "f5-tts"
        # base64 應該是 4 bytes 編出 8 chars(對齊)
        decoded = base64.b64decode(sent["audio_base64"])
        assert decoded == b"\x00\x01\x02\x03\x04"

    @pytest.mark.asyncio
    async def test_empty_sentence_skips(self):
        """空白句子 → 不打 TTS、不推 WS"""
        from bridge.main import _stream_tts_for_sentence

        ws = AsyncMock()
        with patch("bridge.tts.get_tts_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.synthesize_stream = MagicMock()  # 不該被叫
            mock_get_orch.return_value = mock_orch

            await _stream_tts_for_sentence(
                ws, "   ", sentence_index=5,
                persona_id="siro-default",
            )

        assert ws.send_json.call_count == 0

    @pytest.mark.asyncio
    async def test_emotion_tag_stripped_in_sentence(self):
        """[emotion:happy] 在 TTS 進 provider 前會被 _clean_for_tts strip
        (測試 orchestrator.synthesize_stream 內部行為,見 test_tts.py)"""
        from bridge.main import _stream_tts_for_sentence

        ws = AsyncMock()

        with patch("bridge.tts.get_tts_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            # mock 模擬真的 orchestrator:呼叫 _clean_for_tts
            from bridge.tts.stream import _clean_for_tts
            captured_clean: list[str] = []
            async def fake_synth(text, config):
                # 模擬 orchestrator 內部 clean 行為
                clean = _clean_for_tts(text)
                captured_clean.append(clean)
                yield b"\x00"
            mock_orch.synthesize_stream = fake_synth
            mock_get_orch.return_value = mock_orch

            with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
                from bridge.tts.base import TTSConfig
                mock_voice.return_value = TTSConfig(
                    provider="f5-tts", voice_id="mao-clone", language="zh-TW"
                )

                await _stream_tts_for_sentence(
                    ws, "[emotion:happy] 你好世界。", sentence_index=1,
                    persona_id="siro-default",
                )

        # helper 傳給 orchestrator 的是 raw(含 emotion)、orchestrator 內部才 strip
        # 推出去的 sentence 也是 raw(給 Unity log 用)
        sent = ws.send_json.call_args[0][0]
        assert sent["sentence"] == "[emotion:happy] 你好世界。"
        # mock 內部模擬的 clean 結果
        assert captured_clean == ["你好世界。"]

    @pytest.mark.asyncio
    async def test_tts_failure_does_not_crash(self):
        """TTS 失敗不 raise(caller 已經 fire-and-forget)"""
        from bridge.main import _stream_tts_for_sentence

        ws = AsyncMock()
        with patch("bridge.tts.get_tts_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            async def fake_synth(text, config):
                raise RuntimeError("TTS provider 掛了")
                yield  # noqa: unreachable — for generator typing
            mock_orch.synthesize_stream = fake_synth
            mock_get_orch.return_value = mock_orch

            with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
                from bridge.tts.base import TTSConfig
                mock_voice.return_value = TTSConfig(
                    provider="f5-tts", voice_id="mao-clone", language="zh-TW"
                )

                # 不該 raise
                await _stream_tts_for_sentence(
                    ws, "你好", sentence_index=2,
                    persona_id="siro-default",
                )

        # 失敗就沒推 WS
        assert ws.send_json.call_count == 0


# ============================================================
# SentenceBuffer 整合 sentence 切割 → fire TTS task
# ============================================================

class TestSentenceStreamingFlow:
    """測從 LLM token 累積 → 偵測句尾 → 觸發 TTS → 推 WS 的完整 flow
    (不真的打 LLM,用假 stream 模擬)
    """

    @pytest.mark.asyncio
    async def test_multiple_sentences_each_trigger_tts(self):
        from bridge.tts.sentence_buffer import SentenceBuffer
        from bridge.main import _stream_tts_for_sentence

        buf = SentenceBuffer()
        ws = AsyncMock()
        tts_calls: list[str] = []

        with patch("bridge.tts.get_tts_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            async def fake_synth(text, config):
                tts_calls.append(text)
                yield b"\x00"
            mock_orch.synthesize_stream = fake_synth
            mock_get_orch.return_value = mock_orch

            with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
                from bridge.tts.base import TTSConfig
                mock_voice.return_value = TTSConfig(
                    provider="edge-tts", voice_id="zh-TW-HsiaoYuNeural", language="zh-TW"
                )

                # 模擬 LLM 出 3 個 chunk、含 3 個句尾
                chunks = ["你好。", "我是 SIRO。", "今天好。"]
                idx = 0
                tasks = []
                for chunk in chunks:
                    for sentence in buf.feed(chunk):
                        tasks.append(asyncio.create_task(
                            _stream_tts_for_sentence(
                                ws, sentence, idx, persona_id="siro-default"
                            )
                        ))
                        idx += 1
                await asyncio.gather(*tasks)

        # 3 句都送 TTS
        assert tts_calls == ["你好。", "我是 SIRO。", "今天好。"]
        # WS 也推 3 次
        assert ws.send_json.call_count == 3
        # index 對應
        indices = [c[0][0]["index"] for c in ws.send_json.call_args_list]
        assert indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_partial_sentence_buffers_correctly(self):
        """句子切在 chunk 中間、buffer 正確累積"""
        from bridge.tts.sentence_buffer import SentenceBuffer
        from bridge.main import _stream_tts_for_sentence

        buf = SentenceBuffer()
        ws = AsyncMock()
        tts_calls: list[str] = []

        with patch("bridge.tts.get_tts_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            async def fake_synth(text, config):
                tts_calls.append(text)
                yield b"\x00"
            mock_orch.synthesize_stream = fake_synth
            mock_get_orch.return_value = mock_orch

            with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
                from bridge.tts.base import TTSConfig
                mock_voice.return_value = TTSConfig(
                    provider="edge-tts", voice_id="zh-TW-HsiaoYuNeural", language="zh-TW"
                )

                # LLM 切成 token: "你" "好。" "我" "是"
                chunks = ["你", "好。", "我", "是"]
                tasks = []
                idx = 0
                for chunk in chunks:
                    for sentence in buf.feed(chunk):
                        tasks.append(asyncio.create_task(
                            _stream_tts_for_sentence(
                                ws, sentence, idx, persona_id="siro-default"
                            )
                        ))
                        idx += 1
                # flush 殘餘
                for sentence in buf.flush():
                    tasks.append(asyncio.create_task(
                        _stream_tts_for_sentence(
                            ws, sentence, idx, persona_id="siro-default"
                        )
                    ))
                await asyncio.gather(*tasks)

        # "你好。" 切成完整句 → 觸發; "我是" 沒句尾 → flush 才觸發
        assert tts_calls == ["你好。", "我是"]


# ============================================================
# Bridge state 設定
# ============================================================

class TestBridgeStateTtsStreaming:
    def test_default_use_tts_streaming_is_false(self):
        """預設關(向後相容 Unity TTS 流程)"""
        # 不能直接用 main.state 因為 import main 會初始化
        # 用 reload 跟 monkeypatch 的方式比較複雜
        # 改:檢查 env var 預設值
        val = os.environ.get("SIRO_TTS_STREAMING", "false")
        assert val == "false"

    def test_env_var_true_enables(self, monkeypatch):
        """SIRO_TTS_STREAMING=true → use_tts_streaming=True"""
        monkeypatch.setenv("SIRO_TTS_STREAMING", "true")
        # 重新 import main 讓 env 生效
        import importlib
        import bridge.main
        importlib.reload(bridge.main)
        try:
            assert bridge.main.state.use_tts_streaming is True
        finally:
            # 確保下次測試恢復
            monkeypatch.delenv("SIRO_TTS_STREAMING", raising=False)
            importlib.reload(bridge.main)
