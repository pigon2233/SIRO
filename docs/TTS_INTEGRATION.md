# TTS 整合設計 — SIRO Core Experience v1.0 Phase 1

> 給未來自己 / 別人看「為什麼 TTS 這樣設計、怎麼用、怎麼擴充」
> 對應 commit 還沒出 — Phase 1 開工後補上

## 為什麼做 TTS

`LIVE2D_AI_AGENT_OS_PLAN.md` §1.1 明確說「語音 + 文字 = 唯一的輸出方式」。沒有 TTS = Mao 永遠是啞巴文字視窗,不是「AI 助理」。

User 對 TTS 的要求是「想要更好的」(不滿意 edge-tts 的品質),所以設計走 Tier 1 (edge-tts) + Tier 2 (Piper) + Tier 3 (GPT-SoVITS) 三層。

## 目標

- 輸入「你好 Mao」→ Mao 文字回應 **+ 用中文語音播出**(Unity 聽得到)
- LLM 出 token 立即觸發 TTS(TTFB < 1.5s)
- edge-tts 雲端 → Piper 本地 自動 fallback(網路斷時不沉默)
- Persona 切換時自動切聲線
- i18n 雙語(中/英)TTS

## 架構

```
bridge/tts/
├── __init__.py        # 統一對外介面:get_provider() / synthesize_stream() / TTSConfig
├── base.py            # TTSProvider 抽象 Protocol + TTSConfig dataclass
├── edge_tts.py        # Tier 1: edge-tts 雲端 (default)
├── piper_tts.py       # Tier 2: Piper 本地 (fallback, no-network)
├── gpt_sovits.py      # Tier 3: GPT-SoVITS 動漫聲線 (v1.0 polish, optional)
├── stream.py          # TTS streaming orchestrator (sentence segmentation + chunking)
└── voices.py          # voice_id 列表 + persona → voice_id mapping + 聲線 cache
```

## TTS 抽象介面

```python
class TTSProvider(Protocol):
    name: str
    async def synthesize(self, text: str, voice_id: str, language: str) -> AsyncIterator[bytes]:
        """Yield PCM/MP3 audio chunks (16kHz mono, streaming)"""
    async def list_voices(self, language: str) -> list[Voice]:
        """列出可用聲線 (供 persona 切換 / UI dropdown)"""
    async def is_available(self) -> bool:
        """檢查 provider 能不能用 (網路 / 本地 binary / API key)"""
```

## 設計決策

### 為什麼 Tier 1 用 edge-tts (而不是 ElevenLabs / OpenAI TTS)

- 免費(其他都要訂閱)
- 100+ 聲線(中/英/日/韓都有,繁中「曉曉」/「曉伊」自然)
- 不需 API key(Microsoft Edge 公開 endpoint)
- 跟 Anthropic 雲端路線一致
- 缺點:商用 license 要查

### 為什麼 Tier 2 走 Piper 本地

- ONNX 推論、CPU 跑、不需 GPU
- 模型 ~100MB
- 無網路時 fallback
- 跟 Live2D Mao 視覺風格一致(中性聲線)

### 為什麼 Tier 3 走 GPT-SoVITS

- 動漫聲線 clone(5 秒樣本就能模仿)
- 中文品質好
- 開源、本地跑、不依賴雲端
- 5GB VRAM 需求(配合 user 的 NVIDIA 顯卡)
- 跟 Mao 動漫風視覺一致

### 為什麼用 `bridge/minimax_streaming_client` 串流整合

- LLM 出第一個 token 就 trigger TTS sentence 切割
- TTS 跟 LLM streaming 並行跑、降低 TTFB
- 不用等 LLM 完整回應才開始唸
- 對齊 v0.3.1 SSE streaming 設計

### 為什麼 persona → voice_id 透過 `bridge/tts/voices.py` 集中管理

- 未來加 persona 不用動 TTS 邏輯
- 跨 provider 統一 voice_id 命名(用 edge-tts 的 `zh-TW-HsiaoChenNeural`、Piper 的 `zh_TW-hsiaochen-medium`、GPT-SoVITS 的 `mao-clone`)
- persona YAML 只需寫「我要繁中女聲」、TTS layer 自動 translate 到具體 provider 的 voice_id

## 用法 (給業務邏輯用)

```python
from bridge.tts import get_tts_orchestrator, TTSConfig

# 自動選擇 provider (edge-tts 預設、Piper fallback)
orchestrator = get_tts_orchestrator()

# 從 persona 拿 voice config
persona = load_persona("siro-default")
tts_config = TTSConfig.from_persona(persona)
# tts_config.provider = "edge-tts" / "piper" / "gpt-sovits"
# tts_config.voice_id = "zh-TW-HsiaoChenNeural"
# tts_config.language = "zh-TW"

# 串流合成(LLM 完整回應)
async for audio_chunk in orchestrator.synthesize_stream(
    text="你好,我是 SIRO。",
    config=tts_config,
):
    # 透過 WS push 給 Unity
    await ws.send_json({"type": "tts_audio", "data": base64.b64encode(audio_chunk).decode()})
```

## Provider 選擇策略 (auto-detect)

1. 預設用 edge-tts
2. 偵測 `edge-tts.is_available()` 失敗(網路不通/Edge endpoint 掛了)→ 自動切 Piper
3. persona 設 `tts.provider: gpt-sovits` → 強制用 GPT-SoVITS(可選)

## WebSocket 訊息格式 (Unity 端要加)

**送出**:
```json
{ "type": "tts_config", "voice_id": "zh-TW-HsiaoChenNeural", "language": "zh-TW" }
```

**接收**:
```json
{ "type": "tts_audio", "data": "<base64 mp3/opus bytes>" }
{ "type": "tts_end", "text": "..." }
{ "type": "tts_error", "detail": "..." }
```

## 測試

- `tests/bridge/test_tts.py`:
  - `test_edge_tts_synthesize_basic`:mock edge-tts 測串流 chunks
  - `test_piper_fallback`:edge-tts 不可用時自動切
  - `test_voice_cache`:voice list cache 正常
  - `test_persona_voice_mapping`:persona 切換時 voice_id 對應正確
  - `test_streaming_orchestrator`:LLM 串流 + TTS 串流並行
  - `test_ttfb_perf`:TTFB < 1.5s 量測

## 跨 OS 注意事項

- Windows:edge-tts 需要 Microsoft Edge 已安裝(用 `msedge.exe` 當 subprocess,後來新版不需 Edge 2024+ 直接走 endpoint)
- Linux:edge-tts 透過 `edge-tts` Python 套件直接 HTTP、不需 Edge
- Piper:本地 ONNX 模型放 `models/piper/`(~100MB)、`python -m piper` 推論
- GPT-SoVITS:本地 API server 跑在 `localhost:9880`、需要先 `python api_v2.py`

## 已知限制 / TODO

- 商用 license:edge-tts 商用要 Microsoft 同意、目前 user 是個人用
- 聲線 clone:GPT-SoVITS 需要 Mao 角色配音 5-10 分鐘樣本(user 沒做、留 v1.0 polish)
- 情緒對應聲線:Phase 1 不做(同一 persona 同一聲線講所有情緒)、v1.5 補

## Future hooks (給 Phase 2-6 留)

- Phase 2 STT:`bridge/tts/__init__.py` 加 `tts_via_stt` 整合(語音輸入 → STT → LLM → TTS)
- Phase 4 Live2D:講話時 `UnityTTSPlayer.cs` 觸發 Live2D 嘴巴動畫
- Phase 5 Assistant:Assistant tools 可以用 TTS 播報結果(查天氣 → TTS 播)
- Phase 6 Proactive:時段問好用 TTS 主動播
