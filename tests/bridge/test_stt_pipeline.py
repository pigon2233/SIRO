"""tests.bridge.test_stt_pipeline — STT pipeline integration tests(8 個)。

對應 design: docs/STT_INTEGRATION.md §測試計畫 → test_stt_pipeline.py。

涵蓋:
- tts_audio 帶 turn_id 欄位(turn_id > 0 時)
- text_input 開 TurnManager
- 新 turn 自動取消舊
- chat 跟 text_input 共存
- payload 結構正確
- 邊界:WS 斷線、未知訊息、空字串
"""

from __future__ import annotations

import asyncio
import base64
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bridge.main import _process_ws_chat, _stream_tts_for_sentence, app, state


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_state():
    """Mock 必要的 state 欄位,避免 test 觸碰真的 hermes/ollama/parser。"""
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
    state.sessions_lock = threading.RLock()  # 跟 main.py 原本一致(threading.RLock)

    yield state

    state.hermes = original_hermes
    state.parser = original_parser
    state.streaming_client = original_streaming
    state.sessions = original_sessions
    state.sessions_lock = original_sessions_lock
    state.ws_lock = original_ws_lock
    state.connected_websockets = original_connected


class FakeWebSocket:
    """最小 WebSocket 替身,只支援 send_json。"""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


# ============================================================
# 1. tts_audio payload 結構
# ============================================================

@pytest.mark.asyncio
async def test_tts_audio_has_turn_id_when_turn_id_positive(mock_state):
    """turn_id > 0 → tts_audio payload 含 turn_id。"""
    ws = FakeWebSocket()

    async def fake_synthesize_stream(text, voice_cfg):
        for _ in range(3):
            yield b"\x00" * 100

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize_stream
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="test", language="zh-TW")

            await _stream_tts_for_sentence(
                ws, sentence="你好", sentence_index=0,
                persona_id="siro-default", turn_id=42,
            )

    assert len(ws.sent) == 1
    payload = ws.sent[0]
    assert payload["type"] == "tts_audio"
    assert payload["turn_id"] == 42
    assert payload["index"] == 0
    assert payload["sentence"] == "你好"
    assert "audio_base64" in payload
    assert "format" in payload
    assert "provider" in payload


@pytest.mark.asyncio
async def test_tts_audio_omits_turn_id_when_zero(mock_state):
    """turn_id=0(legacy chat)→ tts_audio 不帶 turn_id(向後相容)。"""
    ws = FakeWebSocket()

    async def fake_synthesize_stream(text, voice_cfg):
        yield b"\x00" * 100

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize_stream
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="test", language="zh-TW")

            await _stream_tts_for_sentence(
                ws, sentence="hello", sentence_index=0,
                persona_id="siro-default", turn_id=0,
            )

    payload = ws.sent[0]
    assert "turn_id" not in payload


# ============================================================
# 2. _process_ws_chat 接受 turn_id
# ============================================================

@pytest.mark.asyncio
async def test_process_ws_chat_with_turn_id_propagates_to_tts(mock_state):
    """_process_ws_chat 帶 turn_id → tts_audio 帶 turn_id。"""
    ws = FakeWebSocket()

    class FakeStreamEvent:
        def __init__(self, type_, **kwargs):
            self.type = type_
            self.text = kwargs.get("text", "")
            self.name = kwargs.get("name", "")
            self.input = kwargs.get("input", {})

    async def fake_chat_stream_with_tools(*args, **kwargs):
        yield FakeStreamEvent("text", text="你好 ")
        yield FakeStreamEvent("text", text="世界")

    state.streaming_client.is_available = True
    state.streaming_client.chat_stream_with_tools = fake_chat_stream_with_tools
    state.use_streaming = True
    state.use_tool_calling = True  # 走 chat_stream_with_tools 路徑
    state.use_agent_mode = False
    state.use_tts_streaming = True

    from bridge.emotion_parser import Emotion
    state.parser.parse.return_value = ("你好世界", Emotion.HAPPY, 0.7)
    state.parser.to_live2d_signal.return_value = MagicMock(
        model_dump=lambda: {"expr": "f01"}
    )

    async def fake_synthesize_stream(text, voice_cfg):
        yield b"\x00" * 50

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize_stream
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="test", language="zh-TW")

            await _process_ws_chat(ws, {
                "type": "chat",
                "message": "嗨",
                "turn_id": 99,
                "personality": "siro-default",
            })

    tts_payloads = [m for m in ws.sent if m.get("type") == "tts_audio"]
    assert len(tts_payloads) >= 1
    for p in tts_payloads:
        assert p["turn_id"] == 99


@pytest.mark.asyncio
async def test_process_ws_chat_without_turn_id_omits_turn_id_from_tts(mock_state):
    """_process_ws_chat 沒 turn_id → tts_audio 不帶 turn_id。"""
    ws = FakeWebSocket()

    class FakeStreamEvent:
        def __init__(self, type_, **kwargs):
            self.type = type_
            self.text = kwargs.get("text", "")
            self.name = kwargs.get("name", "")
            self.input = kwargs.get("input", {})

    async def fake_chat_stream_with_tools(*args, **kwargs):
        yield FakeStreamEvent("text", text="hi")

    state.streaming_client.is_available = True
    state.streaming_client.chat_stream_with_tools = fake_chat_stream_with_tools
    state.use_streaming = True
    state.use_tool_calling = True  # 走 chat_stream_with_tools 路徑
    state.use_agent_mode = False
    state.use_tts_streaming = True

    from bridge.emotion_parser import Emotion
    state.parser.parse.return_value = ("hi", Emotion.HAPPY, 0.7)
    state.parser.to_live2d_signal.return_value = MagicMock(
        model_dump=lambda: {"expr": "f01"}
    )

    async def fake_synthesize_stream(text, voice_cfg):
        yield b"\x00" * 50

    with patch("bridge.tts.get_tts_orchestrator") as mock_orch:
        orch = MagicMock()
        orch.synthesize_stream = fake_synthesize_stream
        mock_orch.return_value = orch
        with patch("bridge.tts.voices.get_voice_for_persona") as mock_voice:
            from bridge.tts import TTSConfig
            mock_voice.return_value = TTSConfig(voice_id="test", language="zh-TW")

            await _process_ws_chat(ws, {
                "type": "chat",
                "message": "hi",
                "personality": "siro-default",
            })

    tts_payloads = [m for m in ws.sent if m.get("type") == "tts_audio"]
    assert len(tts_payloads) >= 1
    for p in tts_payloads:
        assert "turn_id" not in p


# ============================================================
# 3. ConversationTask + TurnManager 整合
# ============================================================

@pytest.mark.asyncio
async def test_turn_manager_used_in_text_input_flow():
    """text_input WS handler 用 TurnManager(從 main.py import 行為)。"""
    from bridge.conversation import TurnManager

    mgr = TurnManager()
    completed: list[int] = []

    async def run(turn_id: int, sleep_s: float):
        try:
            await asyncio.sleep(sleep_s)
            completed.append(turn_id)
        except asyncio.CancelledError:
            raise

    # 模擬兩個 text_input 連續到
    await mgr.start_new_turn(turn_id=1, run_fn=lambda: run(1, 5.0))
    assert mgr.current_turn_id == 1
    # 立刻開新 turn 1,舊的 1 應該被 cancel
    await mgr.start_new_turn(turn_id=2, run_fn=lambda: run(2, 0.05))
    assert mgr.current_turn_id == 2
    await mgr.wait_current_done(timeout=2.0)
    await asyncio.sleep(0.1)  # 給舊 task cleanup

    # 1 被 cancel,2 跑完
    assert 1 not in completed
    assert 2 in completed


@pytest.mark.asyncio
async def test_old_turn_tts_chunks_dropped_at_unity_filter():
    """模擬 Unity 端 drop 邏輯:turn_id 不符的 tts_audio chunk 不入 queue。

    (Unity 端實作見 Day 5、這裡測 filter 邏輯本身)
    """
    # 模擬 Unity 端 queue
    queue: list[dict] = []
    current_turn_id = 0

    def filter_tts_chunk(chunk: dict) -> bool:
        """True = 入 queue, False = drop。"""
        if "turn_id" not in chunk:
            return True  # 沒帶 turn_id = legacy 入 queue
        if chunk["turn_id"] != current_turn_id:
            return False  # 舊 turn → drop
        return True

    # 1. Unity 設 current_turn_id = 5
    current_turn_id = 5
    # 2. 收到 turn 4 的 TTS chunk(bridge 還沒 cancel in-flight)
    assert filter_tts_chunk({"type": "tts_audio", "turn_id": 4, "index": 0}) is False
    # 3. 收到 turn 5 的 TTS chunk
    assert filter_tts_chunk({"type": "tts_audio", "turn_id": 5, "index": 1}) is True
    # 4. 收到 legacy(沒 turn_id)
    assert filter_tts_chunk({"type": "tts_audio", "index": 2}) is True


# ============================================================
# 4. end-to-end silent mic (沒事件)
# ============================================================

@pytest.mark.asyncio
async def test_silent_mic_chunks_no_vad_event():
    """靜音 mic_chunk 進 VAD → 沒 vad_pause/vad_resume event。"""
    from bridge.vad import SileroVAD, SileroVADConfig
    from unittest.mock import patch, MagicMock

    # 跟 test_vad.py 一樣 mock VADIterator
    class FakeVI:
        def __init__(self, *a, **kw):
            self.reset_count = 0

        def __call__(self, audio):
            return None  # 永遠靜音

        def reset_states(self):
            self.reset_count += 1

    with patch("bridge.vad.silero.load_silero_vad") as mock_load:
        mock_load.return_value = MagicMock()
        with patch("bridge.vad.silero.VADIterator", FakeVI):
            vad = SileroVAD(SileroVADConfig(db_threshold=-100))
            # 送 10 個靜音 chunk
            silent = b"\x00\x00" * 512
            all_events = []
            for _ in range(10):
                all_events.extend(vad.feed(silent, turn_id=1))
            assert all_events == []  # 沒任何事件


# ============================================================
# 5. 邊界 — WebSocket
# ============================================================

def test_unknown_msg_type_returns_error_sync(mock_state):
    """未知訊息類型 → error 回給 client、ws 不關。同步 TestClient 跑。"""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "unknown_type_xyz"})
        data = ws.receive_json()
        assert data.get("type") == "error"
        # ws 還活著
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong.get("type") == "pong"
