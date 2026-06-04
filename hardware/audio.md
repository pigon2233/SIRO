# 音訊硬體設定（Phase 5）

> 麥克風、喇叭、回音消除。

---

## 這台 G713QC 的音訊

### 預期規格（待 Phase 5 驗證）

| 元件 | 預期 | 驗證方法 |
|------|------|----------|
| 音效晶片 | Realtek HDA | `lspci \| grep audio` |
| 內建喇叭 | 立體聲 2.0 | `aplay -l` |
| 內建麥克風 | 陣列式（2 個以上） | `arecord -l` |
| 3.5mm 耳機孔 | 有 | 實體測試 |
| HDMI 音訊 | 有 | 接 HDMI 螢幕測試 |
| USB 音訊 | 支援 | 插 USB DAC 測試 |

### 確認指令

```bash
# Linux
lspci | grep -i audio
arecord -l
aplay -l
pactl list sinks
pactl list sources
```

---

## 麥克風收音

### 目標

- **1-3 米**清楚收音
- 背景噪音抑制
- 自動增益 (AGC)
- 回音消除 (AEC)

### 軟體堆疊

```
應用: Unity (Live2D voice input) / bridge
  ↓ PortAudio / PulseAudio
系統: PulseAudio + module-echo-cancel
  ↓ ALSA
硬體: 內建 HDA codec / 外接 USB 麥克風
```

### PulseAudio 設定

`/etc/pulse/default.pa` 加：

```
### SIRO 音訊優化
load-module module-echo-cancel aec_method=webrtc source_name=echoCancelSource sink_name=echoCancelSink
set-default-source echoCancelSource
set-default-sink echoCancelSink
```

重啟 PulseAudio：

```bash
pulseaudio -k
pulseaudio --start
```

### 麥克風陣列（如果內建有 2 個以上）

用 `module-beamformer` 或寫 custom sink 做波束成形。
Phase 5 評估。

---

## 喇叭播放

### TTS 輸出

- PulseAudio 預設 sink 接到 Unity 的 AudioSource
- 音量管理：PulseAudio + 系統 mixer
- 防止爆音：套 `flat-volumes = no`

### 多媒體鍵

筆電通常有音量鍵，Linux 認成 XF86 鍵。
可以在 openbox keybind 設：
- XF86AudioRaiseVolume → `pactl set-sink-volume @DEFAULT_SINK@ +5%`
- XF86AudioLowerVolume → `pactl set-sink-volume @DEFAULT_SINK@ -5%`
- XF86AudioMute → `pactl set-sink-mute @DEFAULT_SINK@ toggle`

---

## 回音消除 (AEC) 細節

SIRO 的回音問題：
1. 喇叭播放 TTS → 麥克風收到
2. 麥克風送進 STT → 同一段語音被辨識
3. 重複處理、浪費 token

### WebRTC AEC 設定

`module-echo-cancel` 預設用 WebRTC 的 AEC3，效果不錯。

如果效果不好：
- 試 `aec_method=2` (AEC2) 或 `aec_method=3` (AEC3)
- 調 `aec_args` 參數
- 改硬體（分離喇叭和麥克風的距離）

### 硬體 AEC

部分音效晶片（如某些 Realtek）有硬體 AEC。
要開 kernel module 選項。
Phase 5 評估要不要開。

---

## 音訊測試

### Linux 測試指令

```bash
# 錄 5 秒測試
arecord -d 5 -f cd test.wav

# 播測試音
aplay /usr/share/sounds/alsa/Front_Center.wav

# 監聽麥克風（除錯用）
arecord -f cd | aplay

# 音量
pactl set-source-volume @DEFAULT_SOURCE@ 50%
pactl set-sink-volume @DEFAULT_SINK@ 50%
```

### 評估指標

- **SNR**（訊噪比）：> 20dB 算乾淨
- **THD**（失真）：< 1% 算 OK
- **延遲**：端到端 < 100ms 才不會干擾對話

---

## 不在 Phase 5 範圍

- 音樂播放優化（SIRO 是對話不是音響）
- 環繞音效
- 藍牙音訊（延遲高）
- 錄音 / 編輯功能

---

## STT / TTS 整合（Phase 5 規劃，K6 對應）

SIRO 的音訊目標是**雙向語音對話**：
- 麥克風 → STT → LLM（hermes）
- LLM → TTS → 喇叭

### STT（Speech-to-Text）候選

| 工具 | 語言 | 延遲 | 品質 | 推薦 |
|------|------|------|------|------|
| Whisper.cpp | 多語 | 1-2s | ⭐⭐⭐⭐ | ✅ 本地首選 |
| Vosk | 多語 | < 500ms | ⭐⭐⭐ | 🟡 低延遲備案 |
| OpenAI Whisper API | 多語 | 1-3s | ⭐⭐⭐⭐⭐ | 🟡 雲端 fallback |
| 瀏覽器 Web Speech | Chrome | 1-2s | ⭐⭐⭐ | ❌ 瀏覽器限定 |

**推薦**：本地 Whisper.cpp（base 或 small 模型）、雲端 fallback OpenAI Whisper。

### TTS（Text-to-Speech）候選

| 工具 | 語言 | 延遲 | 品質 | 推薦 |
|------|------|------|------|------|
| Piper | 多語 | < 500ms | ⭐⭐⭐ | ✅ 本地首選 |
| Edge TTS (msedge) | 中英日 | < 1s | ⭐⭐⭐⭐ | 🟡 雲端品質好 |
| OpenAI TTS API | 多語 | 1-2s | ⭐⭐⭐⭐⭐ | 🟡 雲端 fallback |
| espeak | 多語 | < 100ms | ⭐ | ❌ 太機械 |

**推薦**：本地 Piper（zh_TW 模型）、雲端 fallback Edge TTS。

### 音訊 pipeline（Phase 5 設計）

```
[使用者說話]
  ↓ VAD (voice activity detection, webrtcvad)
[麥克風] → PulseAudio echo-cancel source
  ↓ 16kHz mono PCM
[Whisper STT] → text
  ↓
[hermes LLM] → response text
  ↓
[Piper TTS] → 24kHz wav
  ↓
[PulseAudio echo-cancel sink]
[喇叭]
```

### 端到端延遲目標（K6 KPI）

- STT: < 1.5 秒（1-2 秒語音輸入）
- LLM: < 5 秒（雲端 MiniMax-M3）/< 10 秒（本地 Ollama）
- TTS: < 1 秒
- **總計**: < 8 秒（雲端）/< 13 秒（本地）

---

## 麥克風外接選項

| 選項 | 優點 | 缺點 | 推薦場景 |
|------|------|------|----------|
| **ReSpeaker USB Mic Array v2.0** | 4 麥克風 + DSP 處理、Linux 友善 | 貴（~NT$3500）| ✅ 推薦 v1 |
| ReSpeaker 4-Mic Array for Raspberry Pi | 便宜（~NT$2000）| 要接 Pi 中介 | 🟡 DIY |
| 內建 HDA 麥克風 | 免錢 | 收音距離短 | 🟡 開發期 |
| USB 會議麥克風 (e.g. Jabra) | 多人收音 | 貴 + driver 複雜 | ❌ v1 不考慮 |

### ReSpeaker 4-Mic Array 設定

```bash
# 1. 確認 USB 裝置
lsusb | grep "ReSpeaker"
arecord -l  # 應該看到 card 1 或 2

# 2. 設為預設 source
pactl set-default-source alsa_input.usb-ReSpeaker_4_Mic_Array_*

# 3. 測試
arecord -d 5 -f cd -D plughw:1,0 test.wav
# 用耳機聽或 aplay 撥放
aplay test.wav
```

---

## 音訊驗證 SOP（`hardware/verify-audio.sh`）

```bash
#!/bin/bash
set -e

# 1. 確認音效晶片
lspci | grep -i audio
# 預期：Realtek HDA

# 2. 確認麥克風收音（SNR 量測）
arecord -d 5 -f cd -r 16000 test.wav
sox test.wav -n stat  # 看 SNR / RMS
# 預期：SNR > 20dB

# 3. 確認 echo-cancel 啟用
pactl list modules | grep "module-echo-cancel"
# 預期：有 echo-cancel 模組載入

# 4. STT 端到端測試
arecord -d 3 -f cd test.wav
whisper test.wav --language Chinese --model base
# 預期：輸出文字（自己說什麼就出什麼）

# 5. TTS 端到端測試
echo "你好，我是 Mao" | piper --model zh_TW --output_file out.wav
aplay out.wav
# 預期：聽到中文語音

# 6. 端到端延遲
time (arecord -d 3 -f cd in.wav && whisper in.wav --language Chinese > text.txt && \
      cat text.txt | piper --model zh_TW --output_file out.wav && aplay out.wav)
# 預期：< 8 秒（雲端 LLM）/ < 13 秒（本地 LLM）

echo "ALL PASS"
```

---

## Phase 5 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| PulseAudio 設定 + AEC 驗證 | 1 天 | 中（AEC 除錯）|
| Whisper.cpp 整合 + 繁中模型 | 2 天 | 中（繁中辨識率）|
| Piper TTS 整合 + 繁中模型 | 1 天 | 低 |
| ReSpeaker 麥克風陣列設定 | 0.5 天 | 中（DSP 配置）|
| 端到端 pipeline 串接 + 延遲量測 | 2 天 | 高（要 tune 好幾個環節）|
| **總計** | **6.5 天** | — |
