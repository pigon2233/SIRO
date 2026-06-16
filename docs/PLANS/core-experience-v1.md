# SIRO Core Experience v1.0 — Siri/Google Assistant 級核心體驗

> 整合設計書(對應 `LIVE2D_AI_AGENT_OS_PLAN.md` §5 v1+ Roadmap 的 v1.0 sub-version)
> 取代之前的「v0.5 Desktop Assistant 打包」計畫(留在 `.claude/plans/swift-coalescing-ritchie.md`、v1.0 ship 後再回來)

## Context (為什麼做這個)

跑完 v0.3 / v1.5+ / v1.5.3 整批(7 commits、281+38 個測試全綠、bridge / siro-runtime / 15 LLM tools / sandbox / 24-7 探索都就位)後,實際用起來發現**SIRO 不是桌面助理** — 只能打字、不能語音、視窗是死板的 Unity Editor 視窗、沒有對話歷史、沒有助理功能、Mao 不會主動講話。

**核心判斷**:打包成 installer 是「技術 debt」可以晚 2 個月;**核心體驗(語音、UI、助理功能)不做,Mao 永遠是個「能打字聊天的視窗」、不是「桌面助理」**。

## 設計原則 (Google Assistant / Siri 級 UX)

| 原則 | 實作 |
|---|---|
| **Proactive 主動** | 時間到了主動問好、提醒、追問 |
| **Always-listening 待機** | VAD + wake word(Phase 2.5 補) |
| **Multi-turn 對話** | 跨多輪 context、user 中途改主意跟得上 |
| **Multi-modal 輸出** | TTS 語音 + Live2D 表情 + 視覺狀態指示 |
| **Personalization** | 記得 user 名字/暱稱/偏好/生日/重要日期 |
| **Task automation** | Todo / Reminder / Calendar / Search / Open app |
| **Disambiguation** | 不確定時反問、給 user 修正機會 |
| **Graceful failure** | 失敗時清楚告知、給建議 |
| **Cross-session memory** | 已有 SQLite 長期記憶(要強化) |
| **System integration** | Windows toast / media control / 系統匣 |

## 架構

```
Unity 6 + Live2D Mao
├─ mic 收音 + AudioSource 播放
├─ 視窗縮放/拖曳/系統匣
├─ Live2D 表情 + hover/跟隨/點擊互動
├─ 對話歷史 sidebar
├─ listening/thinking/speaking 視覺 ring
└─ TTS audio streaming 播放
            ↓ WebSocket (chat / delta / tts_audio)
bridge (FastAPI + AgentOS)
├─ STT pipeline: mic → VAD → whisper.cpp → text
├─ LLM (Anthropic MiniMax-M3 + Ollama fallback)
├─ TTS pipeline: text → edge-tts/Piper/GPT-SoVITS → audio chunks
├─ Proactive engine (scheduler + persona state + user profile)
└─ Assistant tools (todo / reminder / calendar / weather / search / open app)
            ↓ gRPC
siro-runtime (Rust daemon)
├─ system services (process / hardware / sandbox)
├─ system_event pub/sub
└─ logging / monitoring / restart on crash
```

## 6 個 Phase

| Phase | 內容 | 預估 | 狀態 |
|---|---|---|---|
| 1 | TTS 整合(Mao 會說話) | 1.5-2 週 | 🟡 進行中 |
| 2 | STT 整合(Mao 會聽、whisper.cpp 本地) | 1.5-2 週 | ⏸ |
| 3 | UI 完善(視窗縮放/系統匣/對話歷史) | 1 週 | ⏸ |
| 4 | Live2D 豐富度(hover/跟隨/反應) | 0.5 週 | ⏸ |
| 5 | Assistant 功能(Todo/Reminder/天氣/開 App) | 1 週 | ⏸ |
| 6 | Proactive + Personalization(時段問好 + User Profile) | 1 週 | ⏸ |
| **Total** | | **6.5-8.5 週 (約 2 個月)** | |

## Commit 進度追蹤

| Commit | Phase | 摘要 |
|---|---|---|
| `90c9939` | v0.5 Phase A | 跨平台抽象層(bridge/platform + os-runtime platform)— v1.0 也要用 |
| (待) | Phase 1 | TTS 整合 |

## TTS / STT 選型

- **TTS**:
  - **Tier 1**(預設):edge-tts 雲端(免費、100+ 聲線、繁中「曉曉」/「曉伊」)
  - **Tier 2**(fallback):Piper 本地 ONNX(無網路時)
  - **Tier 3**(v1.0 polish):GPT-SoVITS 動漫聲線 clone(給 Mao 用動漫聲優音色)
- **STT**:whisper.cpp 本地(faster-whisper Python binding、`ggml-medium.bin` 模型、繁中品質)

## 重要 cross-ref

- **抽象層**(v0.5 Phase A 做完):`bridge/platform/paths.py` + `os-runtime/src/platform/` — 業務邏輯禁止寫死 path
- **v1.5+ Computer Control**:Phase 5 Assistant tools 跟 v1.5+ 15 tools 整合、不是新做
- **Persona YAML**:`bridge/personas/siro-default.yaml` 是 single source of truth、`tts.voice` 欄位
- **Siri/Google Assistant 對標**:Phase 6 Proactive 是「學 Google Assistant morning briefing」、Phase 4 Live2D 是「學 Animoji 動態」

## 不在 v1.0 範圍(延後)

- ❌ v0.5 打包計畫 Phase B/C/D/E(Windows Service / Unity Build / Inno Setup / Linux stub)— v1.1
- ❌ Phase 4 Linux 化 — v2.0
- ❌ Phase 5 硬體整合(mic LED / 觸控螢幕 / Kiosk)— v1.5
- ❌ 多人識別、OTA 更新 — v2.0

## 詳細規格

- TTS 詳細:`docs/TTS_INTEGRATION.md`
- STT 詳細:`docs/STT_INTEGRATION.md`(Phase 2 開工時寫)
- UI 詳細:`docs/UI_V1.md`(Phase 3 開工時寫)
- Assistant 詳細:`docs/ASSISTANT_TOOLS.md`(Phase 5 開工時寫)
- Proactive 詳細:`docs/PROACTIVE_V1.md`(Phase 6 開工時寫)
