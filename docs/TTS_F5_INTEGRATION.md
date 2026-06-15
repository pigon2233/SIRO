# TTS F5-TTS 整合 — Phase 1.5 polish

> 為什麼加 F5-TTS、怎麼裝、怎麼用、怎麼擴充
> Phase 1.5 polish:edge-tts 不夠好 → 換 F5-TTS 本地高品質問 TTS

## 為什麼做這個

Phase 1 完成後 user 反映「edge-tts 都只有這種類型的聲音、沒有辦法更好聽嗎」(2026-06-15)。

Edge-tts 是微軟雲端、免費、但品質天花板就在那(語調「機器感」明顯、不像真人在講話)。
F5-TTS 是 2024 上海交大開源的 zero-shot voice clone TTS,**「像真人在講話」**。

| 引擎 | 品質 | 速度 (CPU) | 速度 (GPU) | 費用 | 離線 |
|---|---|---|---|---|---|
| **edge-tts** (Phase 1 default) | 中 (機器感) | < 1s | < 1s | 免費 | ❌ |
| **F5-TTS** (Phase 1.5) | **高** (真人感) | 10-20s | 3-5s | 免費 | ✅ |
| ElevenLabs (備選) | 極高 | < 1s | < 1s | $5/月起 | ❌ |
| GPT-SoVITS (v1.0 polish 2) | 動漫聲線 clone | 5-10s | 1-2s | 免費 | ✅ |

**設計**:F5-TTS 進來當 **新的 Tier 1.5**(本地高品質),edge-tts 仍保留作 Tier 1 fallback(無 GPU 環境),Piper 仍作 Tier 2(無網路 fallback)。

## 安裝

### 1. 系統需求

- Python 3.10+(F5-TTS 要 3.10)
- 選配 GPU:有 NVIDIA GPU + CUDA 11.8+ → 跑得快(3-5s/句);只有 CPU 也行(10-20s/句,首次 warmup 慢)
- ~3GB 硬碟(model weights 1.5GB + deps)

### 2. PyTorch(必要)

```bash
# CPU only(開發機用)
pip install torch torchaudio

# GPU(有 NVIDIA 顯示卡、production 推薦)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### 3. F5-TTS 套件

```bash
# 從 PyPI 裝(2024 末 release)
pip install f5-tts

# 或從 source(最新、有最新 fix)
pip install git+https://github.com/SWivid/F5-TTS.git
```

### 4. 額外依賴

```bash
pip install vocos       # vocoder, F5-TTS 推論需要
pip install jieba       # 中文分詞(給中文 ref text 用)
pip install pypinyin    # 中文轉拼音(F5-TTS 給中文必備)
```

### 5. Reference audio(必要)

F5-TTS 是 zero-shot voice clone、需要一段 6-30 秒的參考音檔 + 對應文字。

**預設路徑**:`models/f5_tts/refs/default_zh.wav`(本機 gitignore、不 commit 大 wav)
**Reference text 範例**:
```
你好,我是 Mao,接下來會用這個聲音跟你說話。
```

**怎麼準備 reference wav**:
- 選項 A:**自己錄 30 秒** — 用 Windows Voice Recorder、講一段清晰中文(沒背景噪音)
- 選項 B:**抓 Mao 角色原聲** — 如果 Mao 有官方 voice pack(遊戲 / 動畫)
- 選項 C:**用 edge-tts 合成一個再拿去 clone** — meta 但 work

參考音檔放好後,寫到 persona YAML:

```yaml
voice:
  provider: f5-tts
  voice_id: mao-clone       # 任意命名
  ref_audio: models/f5_tts/refs/default_zh.wav
  ref_text: 你好,我是 Mao,接下來會用這個聲音跟你說話。
  language: zh-TW
  speed: 1.0
```

### 6. 驗證安裝

```python
# 在 hermes venv 跑
from f5_tts.api import F5TTS
f5tts = F5TTS()
print("F5-TTS loaded OK")
```

第一次會下載 model weights(~1.5GB)、下載完存在 `~/.cache/huggingface/`。

## 架構整合

```
bridge/tts/
├── __init__.py        # 加 F5TTSProvider export
├── base.py            # TTSProvider Protocol (已定義、不動)
├── edge_tts.py        # Tier 1: edge-tts 雲端 (default, 不動)
├── piper_tts.py       # Tier 2: Piper 本地 (no-network, 不動)
├── f5_tts.py          # ★ NEW: Tier 1.5: F5-TTS 本地高品質
├── gpt_sovits.py      # Tier 3: GPT-SoVITS 動漫聲線 (留 v1.0 polish 2)
├── stream.py          # orchestrator 加 F5TTSProvider 到 providers list
└── voices.py          # DEFAULT_VOICES 加 f5-tts 預設
```

**TTSOrchestrator 的 provider 順序**:
1. F5-TTS(若有 GPU / 想要品質)← Phase 1.5 default
2. edge-tts(若只有 CPU / 想要速度)← Phase 1 default
3. Piper(無網路時)← fallback
4. GPT-SoVITS(v1.0 polish 2)← 動漫聲線

依 `is_available()` 動態決定實際用哪個。

## TTSConfig 擴充

F5-TTS 需要 `ref_audio` 跟 `ref_text`,這兩個 edge-tts 沒有。透過 `TTSConfig.extra` dict 帶:

```python
@dataclass
class TTSConfig:
    provider: str = "edge-tts"
    voice_id: str = "zh-TW-HsiaoChenNeural"
    language: str = "zh-TW"
    speed: float = 1.0
    pitch: float = 0.0
    sample_rate: int = 16000
    format: str = "wav"             # F5-TTS 預設輸出 wav(不用 mp3 編碼)
    extra: dict = field(default_factory=dict)
    # F5-TTS 專用:
    # extra = {"ref_audio": "models/f5_tts/refs/mao_zh.wav",
    #          "ref_text": "你好,我是 Mao...",
    #          "nfe_step": 32,    # inference 步數(16-64,越高越慢越穩)
    #          "cfg_strength": 2.0}  # classifier-free guidance(1.0-3.0)
```

## Provider 實作: `bridge/tts/f5_tts.py`

```python
class F5TTSProvider(TTSProvider):
    name = "f5-tts"

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = models_dir or _default_models_dir()
        self._f5tts: F5TTS | None = None  # lazy load

    async def synthesize(self, text: str, config: TTSConfig) -> AsyncIterator[bytes]:
        if not await self.is_available():
            raise RuntimeError("F5-TTS 沒安裝或 ref_audio 找不到")
        ref_audio = config.extra.get("ref_audio")
        ref_text = config.extra.get("ref_text", "")
        if not ref_audio or not Path(ref_audio).exists():
            raise FileNotFoundError(f"F5-TTS ref_audio 找不到: {ref_audio}")
        f5 = self._get_f5tts()
        # 推論在 thread pool 跑(避免 block event loop)
        loop = asyncio.get_event_loop()
        wav, sr = await loop.run_in_executor(
            None, lambda: f5.infer(
                ref_file=ref_audio,
                ref_text=ref_text,
                gen_text=text,
                speed=config.speed,
                nfe_step=config.extra.get("nfe_step", 32),
                cfg_strength=config.extra.get("cfg_strength", 2.0),
            )[:2]  # (wav, sr, spec) → 只拿 wav, sr
        )
        # 整段 wav bytes yield 出去(切成 chunk 給串流用)
        import soundfile as sf
        import io
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV")
        wav_bytes = buf.getvalue()
        chunk_size = 4096
        for i in range(0, len(wav_bytes), chunk_size):
            yield wav_bytes[i : i + chunk_size]
```

**關鍵設計**:
- Lazy import `f5_tts` — 沒裝套件時 `is_available()` 回 False、orchestrator 自動 fallback
- Reference audio 從 persona config 帶進來(每個 persona 可以不同聲線)
- 推論在 thread pool 跑、不 block asyncio event loop
- 輸出 WAV bytes(比 mp3 簡單、不用 ffmpeg 編碼)

## Persona YAML 範例

```yaml
voice:
  provider: f5-tts
  voice_id: mao-clone
  ref_audio: models/f5_tts/refs/default_zh.wav
  ref_text: 你好,我是 Mao,接下來會用這個聲音跟你說話。
  language: zh-TW
  speed: 1.0
  # F5-TTS 專用 tuning(可選):
  # nfe_step: 32
  # cfg_strength: 2.0
```

切換回 edge-tts 只需要把 `provider: f5-tts` 改 `provider: edge-tts`、`ref_audio`/`ref_text` 拿掉。

## 測試策略

跟 Phase 1 一樣 — **mock 測邏輯、不真的下 1.5GB model**。

`tests/bridge/test_f5_tts.py`:
- `TestF5TTSIsAvailable`:F5TTS 沒裝時回 False、有裝時 check ref_audio
- `TestF5TTSMissing`:ref_audio 找不到時 raise FileNotFoundError
- `TestF5TTSMissingText`:ref_text 沒給時 raise
- `TestF5TTSInferMocked`:mock F5TTS.infer、驗證 synthesize 流程(chunk 切割、format)
- `TestF5TTSLazyImport`:mock `import f5_tts` 失敗時 is_available() 回 False、synthesize() raise RuntimeError
- `TestF5TTSConfig`:TTSConfig 帶 f5-tts 專用欄位序列化/deserialization

**不測**:
- F5-TTS model 推論正確性(那是 F5-TTS 自己的責任)
- Reference audio 品質(那是 user 自己的責任)
- GPU vs CPU 速度(那是硬體差異)

## Performance 預期

| 環境 | 一句話 latency(15 字中文) |
|---|---|
| NVIDIA RTX 3060 | 3-5s |
| NVIDIA RTX 4090 | 1-2s |
| CPU i7-12700 | 10-20s |
| CPU i5-8250U (laptop) | 20-40s |

Phase 1 的 1.5s TTFB 目標在 CPU 環境達不到、GPU 可達。Phase 2 會改 streaming sentence-level trigger 來降 TTFB。

## 限制

- **首次呼叫 cold start 慢** — model load 要 5-10s。解法:用 lru_cache 把 F5TTS() 物件 cache 起來(只 load 一次)
- **Reference audio 敏感** — wav 有噪音 / 雜訊 / 多聲音會 clone 出差品質。User 要選乾淨的 wav
- **中文用 pypinyin 預處理** — 沒裝 pypinyin 中文合成會爆。已列在 install 步驟
- **記憶體吃重** — model 在 GPU 吃 ~2GB VRAM。沒 GPU 就吃 RAM(~2GB)

## 下一步 (Phase 1.5 之後)

- **v1.0 polish 2**:**GPT-SoVITS 動漫聲線** — 用 Mao 角色樣本 clone 出真實動漫角色聲線,比 F5-TTS 更貼近「動漫角色」
- **Phase 1.5 streaming**:**Sentence-level streaming** — LLM 出第一個 sentence 立即觸 TTS、不等整段
- **語音緩存 (voice cache)** — 同樣 text + 同一 voice 不重複合成,直接 cache hit

## Rollback 計畫

如果 F5-TTS 整合有問題、要 rollback:
1. `git revert` Phase 1.5 commit
2. persona YAML 改 `provider: edge-tts`
3. 重啟 bridge

Provider 抽象層設計就是為了這個 — rollback 只是 YAML 一行的事。
