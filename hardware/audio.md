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
