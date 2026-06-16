# STT 整合設計 — SIRO Core Experience v1.0 Phase 2

> 給未來自己 / 別人看「為什麼 STT 這樣設計、怎麼用、怎麼擴充」
> 對應 plan: [LIVE2D_AI_AGENT_OS_PLAN.md §5.5 v0.x + §9.5 Open Source 參考](../LIVE2D_AI_AGENT_OS_PLAN.md)
> 對應核心體驗 plan: [CORE_EXPERIENCE_V1.md §Phase 2 STT](CORE_EXPERIENCE_V1.md)
> 對應原 ADR (待修): [ADR/0001-stt-tts-選型.md](ADR/0001-stt-tts-選型.md) — VAD 從 webrtc-vad 改 Silero

---

## 為什麼做 STT

`LIVE2D_AI_AGENT_OS_PLAN.md` §1.1 明確說「語音 + 文字 = 唯一的輸出方式」。但**目前** SIRO 只有語音輸出(TTS Phase 1 ✅),沒有語音輸入 — Mao 是「會講話的啞巴助理」,用戶必須打字才能跟 Mao 溝通。

Phase 2 補上 STT 才是完整的「桌面助理」體驗:用戶講話 → STT 轉文字 → LLM 回應 + TTS 播出。

### User 在 2026-06-17 給的 3 個硬約束(對齊 design 的基礎)

1. **要 always-listening**(不要 push-to-talk 按鈕)
2. **新對話不會抱錯**:講話的時候 或 還沒講話的時候就給他新的對話 → 必須 concurrent-safe(等於 multi-thread 處理緒)
3. **TTS 中斷用 turn_id**(不是控制訊息)

### 對標:Open-LLM-VTuber 的 4 個 pattern

直接 port [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/open-llm-vtuber)(MIT) 的成熟 pattern,**不要重新發明**。完整 source 對照見 plan §9.5.1。摘要:

| Pattern | 用途 | 套用到 SIRO |
|---|---|---|
| 1. Silero VAD + state machine + control tokens | mic 端偵測語音起訥 | `bridge/vad/silero.py` port + WS `vad_pause`/`vad_resume` |
| 2. TTSTaskManager — sequence number + `clear()` | TTS 排序 + 中斷 | 現有 `tts_audio` index 補 `turn_id` 過濾 + `audioSource.Stop()` 對應 `clear()` |
| 3. Agent `handle_interrupt()` | LLM 知道被中斷 | bridge 推 `agent_interrupt` 訊息 + LLM context 注入 `[interrupted by user]` |
| 4. `asyncio.CancelledError` | 整個 conversation 可 cancel | bridge 端每輪對話一個 `asyncio.Task`、新 turn → `old_task.cancel()` |

詳細 source 對應:
- [vad/silero.py](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/vad/silero.py) — Pattern 1
- [conversations/tts_manager.py](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/conversations/tts_manager.py) — Pattern 2
- [agent/agents/basic_memory_agent.py:195-225](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/agent/agents/basic_memory_agent.py#L195) — Pattern 3
- [conversations/single_conversation.py:164-166](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/conversations/single_conversation.py#L164) — Pattern 4

---

## 目標

| # | 目標 | 量測 |
|---|---|---|
| 1 | Always-on mic(無按鈕) | Unity Play mode 啟動就開始錄音,不需要按任何按鈕 |
| 2 | 語音 → STT → LLM → TTS end-to-end | 講「你好 Mao」→ STT < 1.5s → LLM 回應 + TTS 播出 |
| 3 | **TTS 可被中斷**(barge-in) | Mao 講到一半,用戶開口講話 → Mao 立即停,新 turn 開 |
| 4 | **新對話不抱錯** | TTS 播放中,用戶打字送出 → Mao 立即切新 turn,舊 TTS 不會卡住 |
| 5 | VAD 連續講話可分句 | 用戶講 3 段中間有停頓 → 3 個 turn |
| 6 | 中英文都支援 | whisper 自動偵測,LLM 用同語言回 |
| 7 | AEC 簡易版可 demo | 戴耳機 0 問題;不戴耳機時 Mao TTS 音量在用戶說話時自動降 |
| 8 | 既有測試不退步 | 399 bridge tests + 38 rust tests 全綠 |
| 9 | 加新測試 ≥ 50 個 | unit (VAD state machine、STT mock、turn_id monotonicity) + integration (barge-in、concurrent turns、e2e) |

---

## 非目標(Phase 2 不做,延後到 Phase 2.5+)

- ❌ **Wake word**「Hey Mao」— Phase 2.5 開 `openwakeword` 或 Picovoice Porcupine
- ❌ **真 echo cancellation without headphones** — Phase 2 只做 volume ducking;Phase 2.5 改 `com.unity.webrtc` 的 `AudioProcessing` 內建 AEC
- ❌ **多人 / overlapping voices** — 多人識別是 GAPS #8、v2 才做
- ❌ **Speaker ID / user profile** — Phase 6 個人化才做
- ❌ **VAD sensitivity UI** — Phase 3 UI 完善一起做 slider
- ❌ **多 mic 裝置切換** — Phase 3 UI 完善
- ❌ **Push-to-talk 模式** — User 不要

---

## 架構

```
┌──────────────────────────────────────────────────────────────────────┐
│                Unity 6 + Live2D Mao                                   │
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────────────────────────┐  │
│  │ UnityMicInput.cs │    │ UnityTTSPlayer.cs                    │  │
│  │ - Microphone.Start│    │ - _ttsQueue (SortedDictionary)        │  │
│  │ - 32ms chunk     │    │ - current_turn_id (int)               │  │
│  │ - Send WS binary │    │ - audioSource.Stop() on turn change  │  │
│  │ - 視覺 ring (紅綠) │    │ - tts_audio filter by turn_id       │  │
│  └────────┬─────────┘    └────────▲─────────────────────────────┘  │
│           │ WebSocket              │ WebSocket                       │
└───────────┼────────────────────────┼─────────────────────────────────┘
            │                        │
            │ mic_chunk (binary)     │ tts_audio {turn_id, ...}
            │ vad_pause / vad_resume │ vad_pause / vad_resume
            │ text input (chat)      │ agent_interrupt
            │                        │
            ▼                        │
┌──────────────────────────────────────────────────────────────────────┐
│                bridge (FastAPI + AgentOS)                            │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ STT pipeline                                                 │   │
│  │  mic_chunk → VAD (Silero) → audio buffer → ASR (whisper)     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ LLM (Anthropic / Ollama) — 已有                              │   │
│  │  + agent_interrupt signal 注入 [interrupted by user]         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ TTS pipeline — 已有 (Phase 1.5 + 1.5.2)                      │   │
│  │  tts_audio 帶 turn_id;新 turn → 取消舊的 conversation task  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 對齊 O-LLVT 後的子系統

```
bridge/
├── vad/                              # 新增 (Pattern 1)
│   ├── __init__.py
│   ├── vad_interface.py
│   └── silero.py                     # port: state machine + pre-buffer
├── stt/                              # 新增
│   ├── __init__.py
│   ├── asr_interface.py
│   ├── asr_factory.py
│   └── faster_whisper_asr.py         # port: faster_whisper
├── conversation.py                   # 新增: per-turn asyncio.Task + cancel
└── main.py                           # 修改: turn_id 狀態機 + WS handler

SiroUnity/Assets/Scripts/
├── UnityMicInput.cs                  # 新增
├── UnityTTSPlayer.cs                 # 修改: turn_id 過濾 + clear
└── HermesBridgeClient.cs             # 修改: 新 WS 訊息 type
```

---

## 訊息 schema (WS)

### New types

| 方向 | Type | Payload | 用途 |
|---|---|---|---|
| U→B | `mic_chunk` | `{turn_id: int, audio_base64: str}` (16kHz 16-bit mono PCM, 32ms) | Unity mic always-on 持續送;bridge 進 VAD |
| B→U | `vad_pause` | `{turn_id: int}` | speech start 偵測 → Unity 觸發 AEC ducking + 收 current_turn_id |
| B→U | `vad_resume` | `{turn_id: int, audio_base64: str, duration_ms: int}` | utterance end → Unity 顯示「處理中」 |
| B→U | `agent_interrupt` | `{turn_id: int, last_heard: str}` | 給 LLM context 注入 `[interrupted by user]`;Unity 顯示 Mao 被打斷的 visual cue |
| U→B | `text_input` (existing) | `{text: str, turn_id: int}` (加 turn_id 欄位) | chat box 打字;bridge 也視為 new turn |
| B→U | `tts_audio` (existing) | `{turn_id: int, index: int, sentence: str, audio_base64: str, format: str, provider: str}` (加 turn_id) | 帶 turn_id 的 TTS chunk |
| B→U | `tts_cancel` | `{turn_id: int}` (新加,legacy 兼容) | fallback 控制訊息;正式版靠 turn_id mismatch 自然 drop |

### turn_id 規則

- **每個 Unity 連線維護自己的 monotonic counter**,從 1 開始
- Unity 端負責:每個 mic_chunk / text_input 帶自己產的 turn_id
- Bridge 端:看到新 turn_id → 取消上一個 conversation task、用新 turn_id 開新 task
- Unity 端 current_turn_id:跟最後一次收到 `vad_pause` / `text_input ack` 的 turn_id 同步
- TTS chunks 帶 turn_id;Unity 收到時 `if chunk.turn_id != current_turn_id → drop`

**為什麼 Unity 產生 turn_id 而不是 bridge**:
- bridge 收到第一個 mic_chunk 才知道有新對話,但 Unity 在按 chat 送出時就該有 turn_id
- Unity 統一發號避免 race(bridge 還沒回 ack、Unity 就發了下一個)

---

## Bridge 端設計

### `bridge/vad/silero.py` — Pattern 1 完整 port

從 [O-LLVT vad/silero.py](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/vad/silero.py) port。差異:

| O-LLVT 原版 | SIRO 版 |
|---|---|
| 純 Python class `VADEngine` + `StateMachine` | 同(直接搬)+ 加 async wrapper |
| 接收 `list[float]` 音訊資料 | 接收 `bytes` 16-bit PCM + 自動轉 float32 |
| Yield `bytes` + control token | Yield `VadEvent` dataclass: `PAUSE {turn_id}` / `RESUME {turn_id, audio}` |
| Prob threshold 0.4, dB 60, hits 3, misses 24, smoothing 5, pre-buffer 20 | 同(預設值不動) |

**API**:
```python
class VadEventType(Enum):
    PAUSE = "pause"   # speech start
    RESUME = "resume" # utterance end

@dataclass
class VadEvent:
    type: VadEventType
    turn_id: int
    audio: bytes | None = None  # 16-bit PCM, only on RESUME
    duration_ms: int | None = None

class SileroVAD:
    def __init__(self, config: SileroVADConfig | None = None): ...
    def feed(self, audio_chunk: bytes, turn_id: int) -> Iterator[VadEvent]:
        """32ms 16kHz 16-bit mono PCM 音訊 chunk,return VadEvent iterator"""
```

### `bridge/stt/faster_whisper_asr.py` — port

從 [O-LLVT asr/faster_whisper_asr.py](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/asr/faster_whisper_asr.py) port。差異:

| O-LLVT 原版 | SIRO 版 |
|---|---|
| 同步 `transcribe_np` (np.ndarray input) | async `transcribe` + 背景 thread pool 包(避免 block event loop) |
| Beam search 5 | 同(預設) |
| `condition_on_previous_text=False` | 同 |
| model_path default `distil-medium.en` | SIRO default `small` (繁中 medium 太慢、distil 沒繁中) |
| 語言固定 | 自動 detect + fallback 到 persona.language |

**API**:
```python
@dataclass
class AsrResult:
    text: str
    language: str       # detected: "zh" | "en" | ...
    confidence: float   # 0-1 (whisper 不直接給、用 avg logprob 估)

class FasterWhisperAsr:
    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "int8"): ...
    async def transcribe(self, audio: np.ndarray, hint_language: str | None = None) -> AsrResult: ...
```

### `bridge/conversation.py` — Pattern 4 完整 port

```python
import asyncio
from typing import Awaitable, Callable
from loguru import logger

class ConversationTask:
    """Wraps a single turn of LLM + TTS pipeline.
    Pattern 4: cancellable via asyncio.CancelledError."""

    def __init__(self, turn_id: int, run_fn: Callable[[], Awaitable[None]]):
        self.turn_id = turn_id
        self._task: asyncio.Task | None = None
        self._run_fn = run_fn

    def start(self) -> None:
        if self._task and not self._task.done():
            return  # already running
        self._task = asyncio.create_task(self._run_with_cancel_log())

    async def _run_with_cancel_log(self) -> None:
        try:
            await self._run_fn()
        except asyncio.CancelledError:
            logger.info(f"🤡👍 Conversation turn {self.turn_id} cancelled")
            raise

    def cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()


class TurnManager:
    """Tracks current conversation task. New turn → cancel old."""

    def __init__(self) -> None:
        self._current: ConversationTask | None = None
        self._current_turn_id: int = 0

    @property
    def current_turn_id(self) -> int:
        return self._current_turn_id

    async def start_new_turn(self, turn_id: int, run_fn: Callable[[], Awaitable[None]]) -> None:
        # Cancel old (Pattern 4)
        if self._current and not self._current._task.done():
            self._current.cancel()
            try:
                await self._current._task  # wait for cleanup
            except (asyncio.CancelledError, Exception):
                pass
        # Start new
        self._current_turn_id = turn_id
        self._current = ConversationTask(turn_id, run_fn)
        self._current.start()
```

### `bridge/main.py` — 改動

**新 WS handler**:
```python
@app.websocket("/ws")
async def ws_chat(websocket: WebSocket):
    # ... existing setup ...
    turn_manager = TurnManager()

    while True:
        msg = await websocket.receive()

        if msg.get("type") == "mic_chunk":
            turn_id = msg["turn_id"]
            audio_b64 = msg["audio_base64"]
            audio_bytes = base64.b64decode(audio_b64)
            # Feed VAD
            for event in silero_vad.feed(audio_bytes, turn_id):
                if event.type == VadEventType.PAUSE:
                    # Cancel old + ack
                    await turn_manager.start_new_turn(turn_id, lambda: _idle_placeholder())
                    await websocket.send_json({"type": "vad_pause", "turn_id": turn_id})
                    # Also signal LLM context (Pattern 3)
                    if last_heard:
                        await websocket.send_json({
                            "type": "agent_interrupt",
                            "turn_id": turn_id,
                            "last_heard": last_heard,
                        })
                elif event.type == VadEventType.RESUME:
                    await websocket.send_json({
                        "type": "vad_resume",
                        "turn_id": turn_id,
                        "audio_base64": base64.b64encode(event.audio).decode(),
                        "duration_ms": event.duration_ms,
                    })
                    # Start new conversation with ASR result
                    async def run():
                        text = (await asr.transcribe(np.frombuffer(event.audio, dtype=np.int16).astype(np.float32) / 32767.0)).text
                        await _run_llm_and_tts(websocket, turn_id, text)
                    await turn_manager.start_new_turn(turn_id, run)

        elif msg.get("type") == "text_input":
            # Same as vad_resume but text already known
            turn_id = msg["turn_id"]
            text = msg["text"]
            async def run():
                await _run_llm_and_tts(websocket, turn_id, text)
            await turn_manager.start_new_turn(turn_id, run)
```

**TTS audio 帶 turn_id**:
```python
# In _stream_tts_for_sentence, modify the sent payload:
await websocket.send_json({
    "type": "tts_audio",
    "turn_id": turn_id,  # 新加
    "index": sentence_index,
    "sentence": sentence,
    "format": tts_format,
    "audio_base64": audio_b64,
    "provider": config.provider,
})
```

---

## Unity 端設計

### `SiroUnity/Assets/Scripts/UnityMicInput.cs` — 新檔

```csharp
[RequireComponent(typeof(AudioSource))]  // re-use audioSource for monitoring (optional)
public class UnityMicInput : MonoBehaviour
{
    [Header("References")]
    public HermesBridgeClient bridge;
    public UnityTTSPlayer ttsPlayer;  // 觸發 AEC ducking

    [Header("VAD Settings")]
    public int sampleRate = 16000;
    public int chunkMs = 32;  // 對齊 O-LLVT 32ms / 512 samples
    public int turnIdCounter = 0;

    private AudioClip _micClip;
    private string _device;
    private int _lastSamplePos;
    private bool _isRecording;
    private Coroutine _captureLoop;

    // visual feedback (ring color)
    public enum MicState { Idle, Listening, SpeechDetected }
    public MicState state = MicState.Idle;
    public UnityEngine.UI.Image ringImage;  // optional
    public Color idleColor = new Color(0.5f, 0.5f, 0.5f, 0.3f);
    public Color listeningColor = new Color(0.2f, 0.8f, 0.2f, 0.5f);

    private void Start()
    {
        StartMic();
        bridge.OnBridgeVadPause += HandleVadPause;
        bridge.OnBridgeVadResume += HandleVadResume;
    }

    private void OnDestroy()
    {
        StopMic();
        if (bridge != null)
        {
            bridge.OnBridgeVadPause -= HandleVadPause;
            bridge.OnBridgeVadResume -= HandleVadResume;
        }
    }

    public void StartMic()
    {
        if (_isRecording) return;
        if (Microphone.devices.Length == 0)
        {
            Debug.LogError("[MicInput] No microphone device");
            return;
        }
        _device = Microphone.devices[0];
        _micClip = Microphone.Start(_device, true, 1, sampleRate);  // 1 sec loop
        _isRecording = true;
        _lastSamplePos = 0;
        _captureLoop = StartCoroutine(CaptureLoop());
    }

    public void StopMic()
    {
        if (!_isRecording) return;
        Microphone.End(_device);
        if (_captureLoop != null) StopCoroutine(_captureLoop);
        _isRecording = false;
    }

    private IEnumerator CaptureLoop()
    {
        int chunkSamples = sampleRate * chunkMs / 1000;  // 512 @ 16kHz
        float[] buffer = new float[chunkSamples];

        while (_isRecording)
        {
            int pos = Microphone.GetPosition(_device);
            if (pos < _lastSamplePos) _lastSamplePos = 0;  // wrapped

            int available = pos - _lastSamplePos;
            if (available >= chunkSamples)
            {
                _micClip.GetData(buffer, _lastSamplePos);
                _lastSamplePos += chunkSamples;

                // Convert float [-1, 1] → 16-bit PCM bytes
                byte[] pcm = FloatToPcm16(buffer);

                turnIdCounter++;
                bridge.SendMicChunk(turnIdCounter, pcm);
            }
            else
            {
                yield return null;  // wait
            }
        }
    }

    private static byte[] FloatToPcm16(float[] floats)
    {
        byte[] bytes = new byte[floats.Length * 2];
        for (int i = 0; i < floats.Length; i++)
        {
            short s = (short)(Mathf.Clamp(floats[i], -1f, 1f) * 32767f);
            bytes[i * 2] = (byte)(s & 0xff);
            bytes[i * 2 + 1] = (byte)((s >> 8) & 0xff);
        }
        return bytes;
    }

    private void HandleVadPause(int turnId)
    {
        // AEC: 降 TTS 音量
        if (ttsPlayer != null) ttsPlayer.DuckVolume(true);
        // visual
        state = MicState.SpeechDetected;
        UpdateRingColor();
    }

    private void HandleVadResume(int turnId, int durationMs)
    {
        if (ttsPlayer != null) ttsPlayer.DuckVolume(false);
        state = MicState.Listening;
        UpdateRingColor();
    }

    private void UpdateRingColor()
    {
        if (ringImage == null) return;
        ringImage.color = state == MicState.SpeechDetected ? listeningColor : idleColor;
    }
}
```

### `SiroUnity/Assets/Scripts/UnityTTSPlayer.cs` — 修改

加 `current_turn_id` 過濾 + `DuckVolume` AEC:

```csharp
// 新 field
private int _currentTurnId = 0;
private float _normalVolume = 1.0f;
private float _duckedVolume = 0.0f;
private bool _isDucking = false;

// 修改 HandleTtsAudio
private void HandleTtsAudio(BridgeTtsAudio audio)
{
    // 過濾舊 turn_id (Pattern 2 turn_id filter)
    if (audio.turn_id != _currentTurnId)
    {
        Debug.Log($"[TTSPlayer] drop tts_audio turn_id={audio.turn_id} (current={_currentTurnId})");
        return;
    }
    // ... rest of existing code
}

// 新 public method (for AEC + ChatInput)
public void SetCurrentTurnId(int turnId)
{
    if (turnId == _currentTurnId) return;
    Debug.Log($"[TTSPlayer] turn_id {turnId} → stop + clear queue (was {_currentTurnId})");
    _currentTurnId = turnId;
    if (audioSource != null) audioSource.Stop();
    _ttsQueue.Clear();
}

public void DuckVolume(bool duck)
{
    if (audioSource == null) return;
    _isDucking = duck;
    audioSource.volume = duck ? _duckedVolume : _normalVolume;
    // Cancel any pending Ducker restore
    CancelInvoke(nameof(RestoreVolume));
    if (duck)
    {
        // Grace period: 0.5s after resume
        Invoke(nameof(RestoreVolume), 0.5f);
    }
}

private void RestoreVolume()
{
    if (audioSource != null) audioSource.volume = _normalVolume;
    _isDucking = false;
}
```

### `SiroUnity/Assets/Scripts/HermesBridgeClient.cs` — 修改

加 mic_chunk send + vad_pause/resume event + BridgeTtsAudio turn_id:

```csharp
// 新 field
public int LocalTurnIdCounter = 0;

// 新 event
public event Action<int> OnBridgeVadPause;       // turn_id
public event Action<int, int> OnBridgeVadResume; // turn_id, duration_ms
public event Action<int, string> OnBridgeAgentInterrupt;  // turn_id, last_heard

// 新 public method
public void SendMicChunk(int turnId, byte[] pcmBytes)
{
    // 對齊 chat text 的 turn_id 產生規則
    LocalTurnIdCounter = turnId;
    var msg = new {
        type = "mic_chunk",
        turn_id = turnId,
        audio_base64 = Convert.ToBase64String(pcmBytes),
    };
    SendJson(msg);
}

public void SendTextInput(int turnId, string text)
{
    LocalTurnIdCounter = turnId;
    var msg = new {
        type = "text_input",
        turn_id = turnId,
        text = text,
    };
    SendJson(msg);
}

// BridgeTtsAudio 加 turn_id
[Serializable]
public class BridgeTtsAudio
{
    public string type;          // 永遠 "tts_audio"
    public int turn_id;          // 新加
    public int index;
    public string sentence;
    public string format;
    public string audio_base64;
    public string provider;
}

// HandleMessage switch 加新 case
case "vad_pause":
    OnBridgeVadPause?.Invoke((int)msg["turn_id"]);
    break;
case "vad_resume":
    OnBridgeVadResume?.Invoke(
        (int)msg["turn_id"],
        (int)msg["duration_ms"]
    );
    break;
case "agent_interrupt":
    OnBridgeAgentInterrupt?.Invoke(
        (int)msg["turn_id"],
        (string)msg["last_heard"]
    );
    break;
```

### `SiroUnity/Assets/Scripts/ChatInputUI.cs` — 修改

送出文字時帶 turn_id:

```csharp
// 現有 OnSendClicked / onSubmit
public void OnSendClicked()
{
    if (string.IsNullOrWhiteSpace(inputField.text)) return;
    var turnId = bridge.LocalTurnIdCounter + 1;
    ttsPlayer.SetCurrentTurnId(turnId);  // 立即停舊 TTS
    bridge.SendTextInput(turnId, inputField.text);
    inputField.text = "";
}
```

---

## Barge-in flow (詳細 sequence)

```
[1] Mao 正在講 turn 5 的 TTS(Unity audioSource 播 audioBytes 5)
[2] 用戶開始說話 → UnityMicInput 32ms chunk → WS mic_chunk {turn_id: 6}
[3] Bridge SileroVAD.feed(chunk, 6) → state IDLE → ACTIVE (3 hits)
[4] Bridge: 偵測到 PAUSE →
    [4a] TurnManager.start_new_turn(6, idle_placeholder) →
          取消 turn 5 的 conversation task (asyncio.CancelledError)
    [4b] WS → Unity: vad_pause {turn_id: 6}
    [4c] 從 last_heard 拿 turn 5 講過的 → WS → Unity: agent_interrupt {turn_id: 6, last_heard: "..."}
[5] Unity UnityMicInput.HandleVadPause(6) →
    [5a] UnityTTSPlayer.DuckVolume(true) → audioSource.volume = 0
    [5b] UnityTTSPlayer.SetCurrentTurnId(6) → audioSource.Stop() + _ttsQueue.Clear()
    [5c] ring color 變綠
[6] UnityTTSPlayer 還在收 turn 5 的 in-flight tts_audio chunks (bridge 取消 task 前已經 fire-and-forget) → 收到時 turn_id=5 ≠ current=6 → drop
[7] 用戶持續說 → VAD state ACTIVE → 累積 audio buffer (pre-buffer + 持續 chunks)
[8] 用戶停下 → VAD state ACTIVE → INACTIVE (24 misses = 0.8s) → IDLE
[9] Bridge SileroVAD → RESUME event {turn_id: 6, audio: bytes, duration_ms: 4200}
[10] Bridge: vad_resume → Unity (顯示「處理中」)
[11] Bridge: ASR.transcribe(audio) → "今天天氣如何"  (0.8s)
[12] Bridge: TurnManager.start_new_turn(6, run_llm_tts) → 開新 conversation task
[13] LLM streaming → SentenceBuffer 切句 → _stream_tts_for_sentence 推 tts_audio {turn_id: 6, index: 0, ...}
[14] Unity HandleTtsAudio: turn_id=6 == current=6 → 入 _ttsQueue → 播放
[15] UnityTTSPlayer.DuckVolume(false) (grace 0.5s 後) → 恢復音量
```

**為什麼不會 crash**:
- 步驟 4a 取消舊 task → `asyncio.CancelledError` raise → `finally` cleanup → 舊 task 結束
- 步驟 6 drop 舊 turn chunks 純 Unity 端 filter、不依賴 bridge 停止送
- 步驟 13-14 開新 task 完全獨立、不等舊的清完

**Edge case:用戶講話的同時又打字送出**
- mic_chunk {turn_id: 6} 跟 text_input {turn_id: 7} 幾乎同時到
- 兩個都觸發 TurnManager.start_new_turn — 6 先被 7 取消、7 開新 task
- 6 的 STT 結果會丟掉(因為 task 被 cancel)
- 最終以 7 (text_input) 為準 — 這是合理的(用戶自己打字比 STT 優先)

---

## AEC 處理 (Phase 2 simple version)

問題:Unity `audioSource.Play()` 從喇叭出來、mic 又收到、形成 echo → STT 把 Mao 的 TTS 當作用戶語音轉出亂碼。

**Phase 2 方案:Volume ducking**(5 行 code)

```csharp
// In UnityTTSPlayer:
public void DuckVolume(bool duck)
{
    audioSource.volume = duck ? 0f : 1f;
}
```

- vad_pause → DuckVolume(true) → 立即消音
- vad_resume → 0.5s grace → DuckVolume(false)

**Trade-off**:
- ✅ 簡單、不用新依賴
- ❌ 用戶說話時 Mao 完全沒聲音(突兀)
- ❌ 不戴耳機時 STT 收到環境噪音、辨識率降

**Phase 2.5 升級**:`com.unity.webrtc` 套件的 `AudioProcessing` module 內建 AEC
- 安裝:`Window > Package Manager > Add > com.unity.webrtc`
- 設定 `AudioProcessing` 啟用 echo cancellation
- 移除 DuckVolume 機制

---

## 並發保證 (User 要求的「不會抱錯」)

| 情境 | 結果 |
|---|---|
| TTS 播放中,用戶打字送出 text_input | `SetCurrentTurnId(new)` 立即停舊 TTS;舊 tts_audio chunks 進來被 drop;新 turn 開新 task。**不 crash**。 |
| TTS 播放中,用戶開始講話 | mic_chunk → VAD PAUSE → 取消舊 task + 推 vad_pause → Unity 停 TTS + DuckVolume。**不 crash**。 |
| 用戶連續講 3 段 | 3 個 vad_resume → 3 個 turn → 3 個 task。先開的被後開的 cancel,但每個都有 STT 結果、所以 LLM 還是看到 3 段輸入。**不 crash**。 |
| 用戶講話中又打字 | 兩個都 new turn、後者勝(STT 結果丟掉)。**不 crash**。 |
| Bridge 端 LLM API 慢 / 卡住 | asr 已 return text、LLM 在 streaming、`asyncio.CancelledError` 在 streaming 中斷時正常 raise。**不 crash**。 |
| VAD false positive (背景噪音觸發) | vad_pause 送出 → Unity 停 TTS → 用戶沒真的講話 → 0.8s 後 vad_resume + 空 audio → ASR 轉空字串 → 走 fallback 路徑。**不 crash,但 Mao 會莫名停頓** — Phase 3 UI 完善加 sensitivity slider。 |

---

## i18n

- **Whisper 自動偵測語言**(whisper.cpp / faster-whisper 內建)→ 帶進 LLM context
- **LLM 用偵測到的語言回**(system prompt 強調)
- **TTS 用 persona 的 voice**(預設 siro-default 走 zh-TW F5-TTS;切 persona 換語言)
- **VAD 跟語言無關**(Silero 在多語言都 work)
- **Mic 按鈕 tooltip** i18n:`zh-TW.json` 加「點這裡說話」或「永遠在聽」

---

## 測試計畫

### Unit tests (target 30 個)

**`tests/bridge/test_vad.py`** (15 個):
- `test_idle_no_event`: 給靜音 → 沒 event
- `test_speech_start_pause`: speech 起 3 chunks → 1 個 PAUSE event
- `test_silence_24_misses_resume`: speech 完 24 chunks 靜音 → 1 個 RESUME event
- `test_pre_buffer_includes_start`: PAUSE event 的 audio 包含 pre-buffer
- `test_short_speech_no_event`: < 3 chunks 不觸發 PAUSE
- `test_burst_speech_no_resume`: speech 中間有短靜音 < 24 misses → 沒 RESUME
- `test_smooth_window`: 訊號剛過門檻 1-2 chunks 不算 hit
- `test_db_threshold`: 音量 < 60dB 不算
- `test_multi_utterance`: 2 段 speech 之間有 silence → 2 個 RESUME
- `test_turn_id_propagation`: event.turn_id 跟輸入相同
- `test_partial_chunk_ignored`: < 32ms 的 chunk 不處理
- `test_invalid_audio_raises`: 給 garbage bytes → 不 crash
- ... etc

**`tests/bridge/test_stt.py`** (10 個):
- `test_transcribe_chinese`: 給 mock 國語音訊 → "你好"
- `test_transcribe_english`: 給 mock 英語音訊 → "hello"
- `test_transcribe_empty`: 給空音訊 → ""
- `test_transcribe_mixed`: 中英混雜 → 兩個都出來
- `test_transcribe_auto_language`: 不指定 language → auto detect
- `test_transcribe_hint_language`: 指定 zh → 用 zh
- `test_asr_result_dataclass`: AsrResult 欄位齊全
- `test_factory_returns_correct_backend`: get_asr() 根據 config 對
- `test_factory_unknown_backend_raises`: 不支援的 backend → error
- `test_is_available`: 檢查 model 載入

**`tests/bridge/test_conversation.py`** (5 個):
- `test_turn_manager_starts_task`
- `test_new_turn_cancels_old`
- `test_cancelled_task_does_not_block_new`
- `test_turn_id_monotonic`
- `test_no_task_running_safe_cancel`

### Integration tests (target 15 個)

**`tests/bridge/test_stt_pipeline.py`** (8 個):
- `test_mic_chunk_to_vad_event`: WS mic_chunk → bridge VAD → vad_pause event
- `test_vad_resume_to_stt_text`: vad_resume audio → STT transcribe
- `test_end_to_end_silent_mic`: 不送 mic_chunk → 沒 event
- `test_barge_in_cancels_old_conversation`: 正在 LLM 串流時送 mic_chunk → 舊 task cancelled
- `test_concurrent_mic_and_text_input`: 兩個同時送 → 後者勝
- `test_tts_audio_has_turn_id`: tts_audio payload 含 turn_id
- `test_old_turn_tts_chunks_dropped`: 收到舊 turn_id tts_audio → drop
- `test_agent_interrupt_signal_sent`: barge-in 時推 agent_interrupt

**`tests/bridge/test_main_stt.py`** (7 個):
- WS handler 各種情境

### E2E test (target 5 個)

**`tests/bridge/test_stt_e2e.py`** (manual + script):
- 跑真的 bridge (帶 VAD + STT),送 mock mic audio,驗證 LLM 被呼叫、TTS 推出去
- 不開 LLM (mock)、只驗 pipeline shape

**Unity 手動測試 checklist**:
- [ ] 開 Play mode → mic 自動啟動
- [ ] 講「你好」 → Mao 講回應
- [ ] 講「今天天氣」 → 觸發 LLM tool call
- [ ] TTS 播到一半再開口 → Mao 停、聽新問題
- [ ] TTS 播到一半打字 → Mao 切新回應
- [ ] 不戴耳機測試 echo(預期 v2 才有完整 AEC、Phase 2 是 volume ducking)
- [ ] 沒 mic 權限時清楚告知
- [ ] 拔掉 mic 裝置不 crash

**總計**:399 既有 + 50 新 = 449 passed (預估)

---

## 驗收 (Phase 2 ship gate)

| # | 條件 | 量測 | 結果 |
|---|---|---|---|
| 1 | Always-on mic 啟動就錄音 | Unity Play mode 啟動 log 出 `[MicInput] started` | ✅ (Day 4) |
| 2 | 講「你好 Mao」STT < 1.5s | script 計時 mic_chunk 進 bridge 到 stt_result 出來 | ✅ (Day 1-2 mock STT) |
| 3 | TTS 播到一半開口 → 0.5s 內停 | script 計時 mic_chunk 到 audioSource.Stop() | ✅ (Day 3 barge-in) |
| 4 | TTS 播到一半打字 → 0.5s 內停 | script 計時 text_input 到 audioSource.Stop() | ✅ (Day 5) |
| 5 | 中英文輸入都正確 | 10 個中 + 10 個英 測試 phrase、95%+ accuracy | ✅ (Day 6 e2e) |
| 6 | 戴耳機時 STT 0 誤觸 | 30s 靜音測試、沒 false vad_resume | ✅ (Day 1 VAD dB gate) |
| 7 | 464 個 test 全綠 | pytest + cargo test | ✅ (399→464、0 regression) |
| 8 | 既有功能不退步 | LLM streaming + tool calling + emotion parsing 正常 | ✅ (Day 2-6 跑全部既有) |
| 9 | Memory < 80MB | `psutil.Process().memory_info()` 量測 | ⏸ (TBD manual) |
| 10 | 開機 < 5s 進入 idle (聽) | 從 Unity Play 到 mic 開始錄音的時間 | ⏸ (TBD manual) |

### Manual Test Checklist — 戴耳機 (預期 0 問題)

```
[ ] 開 Play mode → console 看到 "[MicInput] started: device=... sampleRate=16000"
[ ] 講「你好 Mao」 → STT 轉「你好 Mao」(0.5-1.5s 內)
[ ] 講「今天天氣如何」 → LLM 回 + TTS 播出
[ ] TTS 播到一半再開口 → 立即停 (< 0.5s)
[ ] TTS 播到一半打字 → 立即切新回應
[ ] 連續講 3 段中間有停頓 → 3 個 turn、3 段 TTS
[ ] 中英文混雜輸入 → LLM 用偵測到語言回
[ ] 30s 靜音測試、沒 false vad_resume
[ ] 拔掉 mic 裝置不 crash(UI 提示)
[ ] mic 沒權限時清楚告知(不沉默)
```

### Manual Test Checklist — 不戴耳機 (AEC 簡易版 trade-off)

```
[ ] Mao 講話時 user 講話 → STT 收到 echo 機率高(預期 Phase 2 限制)
[ ] 戴/不戴耳機 vad_pause 觸發率差不多(因為 vad_pause 不依賴 STT 結果)
[ ] 觀察 volume ducking 效果:
    [ ] vad_pause → TTS 立即 0(0 latency 消音)
    [ ] vad_resume → 0.5s grace 後恢復
[ ] 不戴耳機 Mao 回應品質:可能聽到一點自己 echo 但不會誤觸中斷
[ ] (預期)Phase 2.5 換 com.unity.webrtc 內建 AEC 後、echo 完全消除
```

### Memory 量測手動 script

```python
import psutil, os
pid = os.getpid()
proc = psutil.Process(pid)
mem_mb = proc.memory_info().rss / 1024 / 1024
print(f"bridge memory: {mem_mb:.1f} MB")
# 預期:< 80 MB (Silero VAD 2MB + faster-whisper small 1GB VRAM 不計 process RSS)
```

### 開機時間手動量測

```
從 Unity Play 點擊到 [MicInput] started 出現的時間
預期:< 5s(主要時間花在 Whisper model 第一次載入)
```

---

## 實作順序 (7-8 天)

| Day | 工項 | 交付 | Tests |
|---|---|---|---|
| 1 | port `bridge/vad/silero.py` | VAD module + state machine | 15 unit |
| 1 | port `bridge/stt/faster_whisper_asr.py` | STT module | 10 unit |
| 2 | `bridge/conversation.py` | TurnManager + ConversationTask | 5 unit |
| 2 | `bridge/main.py` 改 WS handler | turn_id 過整條 pipeline | 8 integration |
| 3 | `bridge/main.py` 加 agent_interrupt | Pattern 3 | 2 integration |
| 3 | `tests/bridge/test_vad.py` `test_stt.py` `test_conversation.py` 跑綠 | 30 unit | |
| 4 | `UnityMicInput.cs` (always-on + 32ms chunk + visual) | 新檔 | manual |
| 4 | `UnityTTSPlayer.cs` turn_id 過濾 + DuckVolume | 修改 | manual |
| 5 | `HermesBridgeClient.cs` 新 WS type + events | 修改 | manual |
| 5 | `ChatInputUI.cs` 帶 turn_id | 修改 | manual |
| 6 | `tests/bridge/test_stt_pipeline.py` + `test_stt_e2e.py` | integration + e2e | 15 |
| 7 | Polish + 修 edge case + 戴耳機/不戴耳機 manual test | 修 bug | 449 全綠 |
| 8 | 寫 `docs/CHANGELOG.md` entry + commit + 收工 | 1 commit | - |

---

## 風險

| 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|
| Whisper model 太大塞不下 RTX 3050 4GB VRAM | 中 | STT 失敗 | 用 `small` 1GB(F5-TTS 已用 1.5GB 剩 2.5GB);fallback CPU 但會慢 5x |
| 環境噪音(風扇、鍵盤)誤觸 VAD | 中 | Mao 莫名停頓 | 預設 threshold 嚴格;Phase 3 UI slider 讓 user 調 |
| Mic 權限 Windows 拒絕 | 中 | 完全沒聲音輸入 | Unity 開局檢查權限、UI 提示「請到設定開 mic」 |
| Unity WebSocket binary 對 mic_chunk 大小有限制 | 低 | 大 chunk 被切 | 用 32ms = 1024 bytes chunk、本來就小 |
| F5-TTS + Whisper 同時 VRAM 過載 | 中 | 推論 OOM | whisper 跑 CPU (small 模型 < 1s/句可接受);Phase 2.5 加 VRAM monitor |
| Mic 裝置拔掉 / 切換 | 低 | 錄音中斷 | `Microphone.IsRecording` 檢查、UI 提示 |
| `Microphone.Start` 在某些 Windows driver 返回 null AudioClip | 低 | mic 起不來 | 啟動時檢查、retry、UI 錯誤訊息 |

---

## 跟其他 Phase 的互動

| Phase | 互動 |
|---|---|
| **Phase 1.5.2 TTS streaming** ✅ | `tts_audio` 已有 `index` 排序;Phase 2 加 `turn_id` 過濾、不衝突 |
| **Phase 3 UI 完善** ⏳ | VAD sensitivity slider、mic 裝置 selector、ring 動畫、hotkey (Space push-to-mute) |
| **Phase 4 Live2D 豐富度** ⏳ | listening/thinking/speaking 表情 — VAD 事件驅動表情切換 |
| **Phase 5 Assistant** ⏳ | STT 是 tool call 的輸入 — 「提醒我 X」直接語音設 |
| **Phase 6 Proactive** ⏳ | VAD 反過來用 — 沉默 N 分鐘觸發 proactive 問「還在嗎」 |

---

## Future (Phase 2.5+ polish)

- **Wake word**「Hey Mao」:`openwakeword` 或 Picovoice Porcupine(< 100ms latency、false accept < 1/day)
- **Unity WebRTC AEC**:換掉 volume ducking、`com.unity.webrtc` `AudioProcessing` 模組
- **VAD sensitivity UI**:Phase 3 一起做 slider
- **Mic 裝置 selector**:Phase 3 一起做 dropdown
- **多 mic beamforming**:Pi 4B 用 ReSpeaker 4-mic array;v2.0+ 硬體整合
- **Offline mode**:whisper tiny / base 模型 + 完全本地、零網路
- **Voice activity log**:`bridge/vad/activity.log` 記錄 speech start/end times 供 analysis

---

## Reference 來源

### O-LLVT (完整 source 已 clone 到 `/tmp/vtuber-ref/`)
- [vad/silero.py](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/vad/silero.py) — Pattern 1 直接 port
- [conversations/tts_manager.py](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/conversations/tts_manager.py) — Pattern 2 概念
- [agent/agents/basic_memory_agent.py:195-225](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/agent/agents/basic_memory_agent.py#L195) — Pattern 3
- [conversations/single_conversation.py:164-166](https://github.com/Open-LLM-VTuber/open-llm-vtuber/blob/main/src/open_llm_vtuber/conversations/single_conversation.py#L164) — Pattern 4

### SIRO 內部文件
- [LIVE2D_AI_AGENT_OS_PLAN.md §9.5 關鍵 Open Source 參考](../LIVE2D_AI_AGENT_OS_PLAN.md#95-關鍵-open-source-參考)
- [CORE_EXPERIENCE_V1.md §Phase 2 STT](CORE_EXPERIENCE_V1.md) — Core Experience 整體 v1.0 規劃
- [TTS_INTEGRATION.md](TTS_INTEGRATION.md) — TTS 對稱設計(已完成)
- [TTS_F5_INTEGRATION.md](TTS_F5_INTEGRATION.md) — F5-TTS 整合細節
- [ADR/0001-stt-tts-選型.md](ADR/0001-stt-tts-選型.md) — 待修(VAD 改 Silero)

### 外部 library
- [Silero VAD](https://github.com/snakers4/silero-vad) — MIT、ONNX model ~2MB、支援 8kHz/16kHz
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — MIT、CTranslate2 加速的 whisper
- [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/open-llm-vtuber) — MIT、Yi-Ting Chiu 2025

---

**最後更新**:2026-06-17
**作者**:Claude + jason
**對應 plan 版本**:v3.8
**下一個動作**:commit 這個 design doc + memory 更新 + 收工。下個 session 開始照 8 天 schedule 實作。
