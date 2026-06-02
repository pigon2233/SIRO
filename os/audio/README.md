# os/audio/ - 音訊設定

> Phase 5 實作。麥克風收音、喇叭播放、回音消除。

## 目標

- 內建麥克風：1-3 米清楚收音
- 內建喇叭：播放 TTS 清楚
- 避免回授：硬體 / 軟體 AEC

## 軟體堆疊

```
應用層: Unity (Live2D)
        ↓ PulseAudio / PipeWire
系統層: ALSA
        ↓
硬體:   內建 audio codec / 外接 USB audio
```

**Phase 5 決定**：用 PulseAudio（成熟）還是 PipeWire（現代）。
預設 **PulseAudio**，之後再升 PipeWire。

## 回音消除 (AEC)

選項：
- PulseAudio 內建的 `module-echo-cancel`（基於 WebRTC AEC）
- `speexdsp` 套件
- 硬體 AEC（如果音效晶片支援）

預設用 `module-echo-cancel`。

## 麥克風陣列

如果用 USB 麥克風陣列（如 ReSpeaker）：
- 4 麥克風做 beamforming
- 方向性收音
- 1-5 米範圍

Phase 5 評估。

## 不在 Phase 5 範圍

- 音樂播放（SIRO 是陪伴裝置不是音響）
- 多聲道 / 環繞
- 藍牙音訊（會增加延遲）
