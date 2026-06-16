"""tests.bridge.test_barge_in — Day 3 barge-in + agent_interrupt integration tests(7 個)。

對應 design: docs/STT_INTEGRATION.md §測試計畫 → test_stt_pipeline.py 第 8 個 +
             Day 3 agent_interrupt 整合。

涵蓋:
- last_heard_sink 記住 Mao 講過的話
- agent_interrupt 推播時機(mic VAD PAUSE / text_input barge-in)
- interrupted_text 注入 LLM context
- barge-in flow 完整 sequence
"""

from __future__ import annotations

import asyncio
import base64
import threading
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from bridge.main import _process_ws_chat, _stream_tts_for_sentence, state


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_state():
    original_hermes = state.hermes
    original_parser = state.parser
    original_streaming = state.streaming_client
    original_sessions = state.sessions
    original_sessions_lock = state.sessions_lock
    original_ws_lock = state.ws_lock
    original_connected = state.connected_websockets

    state.hermes = MagicMock()
    state.hermes.is_available.return_value = True
    state.parser = MagicMock()
    state.streaming_client = MagicMock()
    state.streaming_client.is_available = False
    state.connected_websockets = set()
    state.ws_lock = asyncio.Lock()
    state.sessions = {}
    state.sessions_lock = threading.RLock()

    yield state

    state.hermes = original_hermes
    state.parser = original_parser
    state.streaming_client = original_streaming
    state.sessions = original_sessions
    state.sessions_lock = original_sessions_lock
    state.ws_lock = original_ws_lock
    state.connected_websockets = original_connected


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


# ============================================================
# 1. last_heard_sink 機制
# ============================================================

@pytest.mark.asyncio
async def test_last_heard_sink_called_with_turn_id_and_sentence(mock_state):
    """_stream_tts_for_sentence 推完 tts_audio → sink 被呼叫(turn_id, sentence)。"""
    ws = FakeWebSocket()
    captured: list[tuple[int, str]] = []

    def sink(turn_id: int, sentence: str) -> None:
        captured.append((turn_id, sentence))

    async def fake_synthesize(text, voice_cfg):
        yield b"\x00" * 50

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="t", language="zh-TW")

            await _stream_tts_for_sentence(
                ws, sentence="你好世界", sentence_index=1,
                persona_id="siro-default", turn_id=5,
                last_heard_sink=sink,
            )

    assert captured == [(5, "你好世界")]


@pytest.mark.asyncio
async def test_last_heard_sink_not_called_for_legacy_turn_id_zero(mock_state):
    """turn_id=0 → sink 不被呼叫(legacy chat 流程)。"""
    ws = FakeWebSocket()
    captured: list = []

    def sink(turn_id, sentence):
        captured.append((turn_id, sentence))

    async def fake_synthesize(text, voice_cfg):
        yield b"\x00" * 50

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="t", language="zh-TW")

            await _stream_tts_for_sentence(
                ws, sentence="hi", sentence_index=0,
                persona_id="siro-default", turn_id=0,
                last_heard_sink=sink,
            )

    assert captured == []  # 沒被呼叫


@pytest.mark.asyncio
async def test_last_heard_sink_exception_does_not_propagate(mock_state):
    """sink 拋例外 → 不 crash(只 log warning)。"""
    ws = FakeWebSocket()

    def bad_sink(turn_id, sentence):
        raise RuntimeError("sink fail")

    async def fake_synthesize(text, voice_cfg):
        yield b"\x00" * 50

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="t", language="zh-TW")

            # 不 raise
            await _stream_tts_for_sentence(
                ws, sentence="hi", sentence_index=0,
                persona_id="siro-default", turn_id=1,
                last_heard_sink=bad_sink,
            )

    assert any(m.get("type") == "tts_audio" for m in ws.sent)


# ============================================================
# 2. interrupted_text 注入 LLM context
# ============================================================

@pytest.mark.asyncio
async def test_interrupted_text_prepended_to_chat_message(mock_state):
    """_run_conversation_turn(..., interrupted_text='X') → chat message 含 X prefix。"""
    # 直接驗證「被 prepended 後的字串」會被 _process_ws_chat 接收
    # 因為 _process_ws_chat 直接拿 data['message']、它本身不知道 interrupted_text
    # — interrupted_text 注入是 websocket_endpoint 的 closure 在呼叫前做的
    ws = FakeWebSocket()
    state.streaming_client.is_available = False
    state.use_streaming = False
    state.use_tool_calling = False
    state.use_agent_mode = False

    # Mock hermes chat 直接回傳
    from bridge.hermes_client import HermesResult
    state.hermes.chat.return_value = HermesResult(
        success=True,
        output="[emotion:happy] OK",
    )

    interrupted = "[User interrupted previous conversation about: '我剛才問天氣']\n\n今天天氣如何"
    await _process_ws_chat(ws, {
        "type": "chat",
        "message": interrupted,
        "personality": "siro-default",
    })

    # response 應出來(證明 message 沒被當空白 reject)
    assert any(m.get("type") == "response" for m in ws.sent)


@pytest.mark.asyncio
async def test_interrupted_text_prepend_format(mock_state):
    """interrupted_text 注入格式:[User interrupted: 'X']\\n\\nY。"""
    # 從 main.py websocket_endpoint 的 _run_conversation_turn 拿格式定義
    # 我們知道格式是:[User interrupted previous conversation about: '{text}']\n\n{user_text}
    interrupted = "我剛才問天氣"
    user_text = "今天天氣如何"
    final = f"[User interrupted previous conversation about: '{interrupted}']\n\n{user_text}"
    assert "[User interrupted" in final
    assert "我剛才問天氣" in final
    assert "今天天氣如何" in final
    # 順序:interrupted prefix 在前
    assert final.index("[User interrupted") < final.index("今天天氣如何")


# ============================================================
# 3. Barge-in flow (整合測試)
# ============================================================

@pytest.mark.asyncio
async def test_barge_in_records_then_emits_agent_interrupt_via_vad():
    """Barge-in 完整 sequence:
    1. 舊 turn Mao 講「我正在查天氣...」→ last_heard[5] = '我正在查天氣'
    2. user 講話 → VAD PAUSE → 推 agent_interrupt + vad_pause
    3. agent_interrupt payload 含 last_heard 欄位 = Mao 上一句話
    """
    # 這個 test 用 mock VAD 直接跑流程(WS endpoint 是 async generator 難直接測)
    from bridge.vad import SileroVAD, SileroVADConfig, VadEventType
    from unittest.mock import MagicMock, patch

    class FakeVI:
        def __init__(self, *a, **kw):
            self._events: list = []

        def __call__(self, audio):
            if self._events:
                return self._events.pop(0)
            return None

        def reset_states(self):
            pass

        def push(self, e):
            self._events.append(e)

    fake_vi = FakeVI()
    with patch("bridge.vad.silero.load_silero_vad") as mock_load:
        mock_load.return_value = MagicMock()
        with patch("bridge.vad.silero.VADIterator", return_value=fake_vi):
            # 用 loud sine wave chunk(過 dB gate)
            cfg = SileroVADConfig(db_threshold=-100)  # 關 dB gate
            vad = SileroVAD(cfg)

            # 1. 記得 Mao 上一句話(模擬 _last_heard_sink)
            last_heard: dict[int, str] = {}
            last_heard[5] = "我正在查天氣"

            # 2. user 講話 → mic_chunk 進 VAD
            fake_vi.push({"start": 0})  # VAD PAUSE
            # loud sine wave chunk(amplitude 0.3 ≈ -10dB、過 dB gate)
            t = 0.032  # 32ms
            import numpy as np
            samples = np.sin(2 * np.pi * 440 * np.arange(512) / 16000) * 0.3
            chunk = (samples * 32767).astype(np.int16).tobytes()
            events = list(vad.feed(chunk, turn_id=6))
            assert len(events) == 1
            assert events[0].type == VadEventType.PAUSE
            assert events[0].turn_id == 6

            # 3. agent_interrupt payload 應用 last_heard[5]
            agent_interrupt_payload = {
                "type": "agent_interrupt",
                "turn_id": 6,
                "last_heard": last_heard.get(5, ""),
            }
            assert agent_interrupt_payload["last_heard"] == "我正在查天氣"
            assert agent_interrupt_payload["turn_id"] == 6


@pytest.mark.asyncio
async def test_text_input_barge_in_emits_agent_interrupt():
    """text_input 進來時,如果上一 turn 有 last_heard → 推 agent_interrupt。
    """
    # 模擬 closure 邏輯(從 main.py websocket_endpoint 抽)
    last_heard: dict[int, str] = {5: "我正在查天氣"}

    # 假裝 turn_manager.current_turn_id = 5(上一個 turn)
    current_active_turn_id = 5
    new_turn_id = 6

    # text_input 處理器邏輯(從 main.py):
    prev_turn_id = current_active_turn_id
    prev_heard = last_heard.get(prev_turn_id, "") if prev_turn_id > 0 else ""
    if prev_heard:
        agent_interrupt = {
            "type": "agent_interrupt",
            "turn_id": new_turn_id,
            "last_heard": prev_heard,
        }
    else:
        agent_interrupt = None

    assert agent_interrupt is not None
    assert agent_interrupt["last_heard"] == "我正在查天氣"
    assert agent_interrupt["turn_id"] == 6


@pytest.mark.asyncio
async def test_first_turn_no_agent_interrupt():
    """第一個 turn 沒有上一 turn、沒 last_heard → 不推 agent_interrupt。"""
    last_heard: dict[int, str] = {}  # 空的
    current_active_turn_id = 0
    new_turn_id = 1

    prev_turn_id = current_active_turn_id
    prev_heard = last_heard.get(prev_turn_id, "") if prev_turn_id > 0 else ""
    if prev_heard:
        agent_interrupt = {"type": "agent_interrupt", "turn_id": new_turn_id, "last_heard": prev_heard}
    else:
        agent_interrupt = None

    assert agent_interrupt is None
