# ADR 0001: STT / TTS 選型

- **狀態**: Proposed (Phase 3 開始時 review)
- **日期**: 2026-06-07
- **決策者**: SIRO Tech Lead
- **影響範圍**: Phase 3+ (Rust 音訊 I/O)、Phase 5 (STT/TTS 整合)

---

## 背景

SIRO 是本地 kiosk 部署的 Live2D AI agent、需要語音輸入（STT）和語音輸出（TTS）才能真正脫離鍵盤。

Phase 3 開始時需要在 Rust 端做：
- 音訊 capture (cpal/rubato)
- VAD（voice activity detection）
- STT pipeline
- TTS pipeline
- Audio device 管理

Phase 3 不實際做 STT/TTS、但要選好型別、預留 Rust 介面、避免 Phase 5 重來。

---

## 選型比較

### STT (Speech-to-Text)

| 方案 | 優點 | 缺點 | 本地可跑 | 授權 | 建議 |
|------|------|------|----------|------|------|
| **whisper.cpp** | OpenAI Whisper port、C++ 寫成、超快、quantized model 1-3GB VRAM | 要 build C++、模型大 | ✅ | MIT | ⭐⭐⭐ **首選** |
| whisper-cpp-rs (Rust binding) | 純 Rust 介面、跟 Rust runtime 整合 | 還要 build whisper.cpp | ✅ | MIT/Apache-2.0 | ⭐⭐ |
| Whisper API (OpenAI) | 品質最高 | 要網路、付費、隱私風險 | ❌ | 商業 | ❌（違反本地 kiosk 原則） |
| whisper-rs (HuggingFace) | 純 Rust | 性能比 whisper.cpp 差 | ✅ | MIT | ⭐ |
| Vosk | 輕量 (< 50MB)、流式 | 品質比 Whisper 差 | ✅ | Apache-2.0 | ⭐⭐（備援 / 雞蛋用） |

**決定**: **whisper.cpp**（透過 whisper-cpp-rs binding）
- 模型 GGML quantized、可以跑在 CPU（small: 466MB、medium: 1.5GB、large: 3GB）
- 流式支援、可以做 partial transcription
- 開源、可商用、Mit license
- 跟 SIRO 的「本地優先、隱私優先」哲學一致

**Fallback**: 詞彙太敏感、Whisper 辨識不好 → 用 Vosk 跑 keyword spotting

### TTS (Text-to-Speech)

| 方案 | 優點 | 缺點 | 本地可跑 | 授權 | 建議 |
|------|------|------|----------|------|------|
| **piper** (本地 TTS) | 品質高、支援中文、即時 (< 200ms first chunk) | 要 build C++、模型 ~60MB per voice | ✅ | Apache-2.0 | ⭐⭐⭐ **首選** |
| **edge-tts** (微軟雲端) | 品質最高、中文超自然 | 網路、隱私、可能限流 | ❌ | 商業 | ❌ |
| **Piper HTTP** (fastapi wrapper) | 跟 FastAPI 整合 | 額外 process | ✅ | Apache-2.0 | ⭐⭐ |
| Coqui TTS | 開源 | 模型大、慢 | ✅ | MPL-2.0 | ⭐ |
| gTTS (google) | 簡單 | 網路、品質普通 | ❌ | 商業 | ❌ |

**決定**: **piper** (本地)
- 支援中文（zh_CN 預訓練模型）
- ONNX runtime、CPU 可跑、GPU 加速
- Streaming、可以邊生邊播
- 跟 STT 選 whisper.cpp 一樣、本地優先

**SpeechBubble + TTS 串接**:
- LLM 回文字
- Bridge 收文字、同時:
  1. 立即推 response 給 Unity (chat bubble 顯示)
  2. 送文字到 TTS service (Piper HTTP 或 process)
  3. TTS 回 audio chunks → 推給 Unity / Rust audio device

### Audio I/O Library

| 方案 | 優點 | 缺點 | 平台 | 建議 |
|------|------|------|------|------|
| **cpal** | Rust audio 跨平台抽象 | API 稍低階 | Win/Mac/Linux | ⭐⭐⭐ **首選** |
| rodio | 高階、play/stream 簡單 | 還在快速演進 | Win/Mac/Linux | ⭐⭐ |
| portaudio FFI | 最底層、最彈性 | C 介面、複雜 | Win/Mac/Linux | ⭐ |
| Windows: WASAPI | Windows 原生 | 只 Windows | Win | ⭐⭐ |
| Linux: ALSA / PulseAudio | Linux 原生 | 只 Linux | Linux | ⭐⭐ |

**決定**: **cpal**（抽象層）+ 平台原生 backend (WASAPI/ALSA/CoreAudio)
- 跨平台、易測試
- 已穩定 v0.15+
- SIRO runtime 用 cpal 抓 mic input + 推 speaker output

### VAD (Voice Activity Detection)

| 方案 | 優點 | 缺點 | 建議 |
|------|------|------|------|
| webrtc-vad | 極輕量 (< 1MB)、即時、C++ port 多 | 只支援 8kHz/16kHz/32kHz/48kHz、容易誤觸(沒神經網路) | ⭐ |
| **Silero VAD** | 神經網路精準、ONNX model ~2MB、支援多語言 | 比 webrtc-vad 重一點、需 ONNX runtime | ⭐⭐⭐ **首選 (v2 改採)** |
| 自製 energy-based | 0 依賴 | 雜訊環境差 | ⭐ |

**決定（v2, 2026-06-17 更新）**: **Silero VAD**（透過 `silero-vad` Python package）
- 神經網路:準確率遠高於 webrtc-vad(尤其背景噪音 + 多人環境)
- ONNX model 2MB,載入 < 1s,CPU < 3%
- MIT license,跟 SIRO 哲學一致
- 內建 `VADIterator` 已經包好 state machine(hit/miss counter)+ min_silence_duration + speech_pad
- 設計書:docs/STT_INTEGRATION.md Pattern 1、source: O-LLVT vad/silero.py 概念
- 跟 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/open-llm-vtuber) 採同樣的 VAD 方案(該專案測試過)

**取代原因**:原本選 webrtc-vad 假設「極輕量 > 精準」,但 v2 實作時:
1. Silero ONNX model 才 2MB,載入速度跟 webrtc-vad 差異可忽略
2. Silero 在「真實噪音 + 多人交談」場景下 false positive 率比 webrtc-vad 低 50%+
3. 跟 O-LLVT 採用同樣 VAD → 可以直接 port 他們的 pre-buffer + state machine 設計

---

## 決定總結

| 元件 | 選型 | Python 套件 | 備註 |
|------|------|-----------|------|
| STT | faster-whisper (whisper.cpp CTranslate2 加速) | `faster-whisper` | CTranslate2 model, CPU/GPU 兩可 |
| TTS | F5-TTS / edge-tts (本機 + 雲端混合) | `f5-tts` / `edge-tts` | 見 docs/TTS_F5_INTEGRATION.md |
| Audio I/O | Unity Microphone + AudioSource (前端) | n/a | Phase 2 STT 用 Unity 端 |
| VAD | Silero VAD (v2 改) | `silero-vad` | 取代 webrtc-vad、神經網路 |

---

## 架構圖

```
[Unity Mic] → 32ms PCM chunks → WS mic_chunk
                                     ↓
                          [Bridge SileroVAD] (16kHz mono)
                                     ↓
                          VadEvent: PAUSE / RESUME
                                     ↓
                          [Bridge STT] faster-whisper
                                     ↓
                          text → TurnManager → LLM → TTS
                                     ↓
                          tts_audio {turn_id, ...} → Unity
```
                              ↓
                     whisper-rs (STT)
                              ↓
                       text → bridge → LLM
                              ↓
                       LLM response text
                              ↓
              ┌───────────────┴───────────────┐
              ↓                                ↓
        Unity 文字                       piper-rs (TTS)
        (chat bubble)                          ↓
                                       cpal::SinkStream
                                              ↓
                                          [Speaker]
```

---

## 風險 + 緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| whisper.cpp model 太大、吃 RAM | kiosk 硬體可能不夠 | 提供 tiny (39MB) / base (74MB) / small (466MB) 三種大小、user 選 |
| Piper 中文模型品質 | 聽起來不自然 | 先用官方 zh_CN model、之後訓練客製 |
| cpal Windows 平台行為 | 音訊卡頓 | Phase 3 先在 Linux 開發、Win 用 WASAPI fallback |
| 即時性 (TTFB < 500ms) | 使用者體驗差 | 串 streaming ASR (partial result) + streaming TTS (first chunk < 200ms) |

---

## 下一步

- [ ] Phase 3 開始時、實作 Rust 端 audio I/O (cpal)
- [ ] Phase 3 或 Phase 5: 整合 whisper-rs
- [ ] Phase 5: 整合 piper-rs
- [ ] 測量 STT/TTS 延遲、加進 K2/K5 KPI 量測
