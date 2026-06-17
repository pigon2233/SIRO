# SIRO Documentation Index

> **2026-06-17 重組**:從 28 個散落頂層 .md 整理為「**13 頂層(含 INDEX) + 5 子目錄**」結構。所有 cross-references 已更新。
> **對應主計畫書**:[../LIVE2D_AI_AGENT_OS_PLAN.md](../LIVE2D_AI_AGENT_OS_PLAN.md)(v3.0)

---

## 頂層文件(快速入口)

| 文件 | 用途 | 適用場景 |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 4 層架構總覽 | **新成員 onboarding 第一份文件** |
| [API.md](API.md) | HTTP / gRPC / WS 介面契約 | 寫 client / 串接第三方時 |
| [SETUP.md](SETUP.md) | 從 0 到 v0 能跑的完整步驟 | **首次安裝 / 換機器** |
| [PERSONA.md](PERSONA.md) | Persona YAML schema 規範 | 改角色或加新角色時 |
| [SECURITY.md](SECURITY.md) | 隱私現況 + 加密 roadmap | 評估隱私風險 / 規劃加密 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 常見問題排查 | **出問題先看這份** |
| [STATUS.md](STATUS.md) | 專案狀態總覽 | 想知道現在做到哪 |
| [CHANGELOG.md](CHANGELOG.md) | 重要里程碑記錄 | 看歷史演進 |
| [TESTING.md](TESTING.md) | 測試策略 | 寫 test / CI 整合 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 部署 SOP | 部署到新機器 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 貢獻指南 | 給人類 + AI 助手 |
| [PHASE2_TEST_REPORT.md](PHASE2_TEST_REPORT.md) | Phase 2 測試報告 | 看 KPI 量化結果 |

---

## 子目錄(分類整理)

### [ADR/](ADR/) — 架構決策紀錄(新格式)
- `0001-stt-tts-選型.md` — STT/TTS 選型決策
- `0002-subsystem-failure-對話對應.md` — 子系統失敗 → Mao 表情對應

### [PLANS/](PLANS/) — 主題計畫文件
**當前進行中 / 未來規劃**:
- [open-llm-vtuber.md](PLANS/open-llm-vtuber.md) — **19-feature 補完計畫(P0/P1/P2)**
- [strategic-gaps.md](PLANS/strategic-gaps.md) — 10 個戰略層級 gap
- [core-experience-v1.md](PLANS/core-experience-v1.md) — v1.0 Core Experience 設計
- [rust-rewrite-notes.md](PLANS/rust-rewrite-notes.md) — Rust 改寫 bridge 戰略
- [motion-synthesis-research.md](PLANS/motion-synthesis-research.md) — Live2D 動作生成研究

**已 ship 的設計決策**:
- `agent-computer-control.md` — v1.5+ 15-tool 設計
- `k2-decision.md` — K2 反應時間決策(< 2s 不可行 → < 5s)
- `v2-persistence.md` — v2.0 SQLite 持久化設計
- `gaps-9-degradation.md` — 降級路徑(6 子系統 × 4 狀態)
- `linux-port-issues.md` — Linux port 18 個問題

### [integration/](integration/) — 各功能模組整合設計
- [persona-guide.md](integration/persona-guide.md) — **Persona 完整指南**(資料層 + Unity 場景接線)
- [stt.md](integration/stt.md) — STT 整合設計(Phase 2)
- [tts.md](integration/tts.md) — TTS 整合設計(Phase 1)
- [tts-f5.md](integration/tts-f5.md) — F5-TTS 整合細節
- [streaming.md](integration/streaming.md) — Streaming 回應戰略筆記

### [reference/](reference/) — 深度技術參考
- [agent-os.md](reference/agent-os.md) — Agent OS 架構(v0.3 後台作業系統)

### [history/](history/) — 歷史 / 已歸檔(留作 audit trail)
- `decisions.md` — v0 設計決策紀錄(legacy 格式,新決策走 ADR/)
- `strategic-notes.md` — v0.3 戰略決策筆記(Q1/Q2)
- `plan-review-v0.3.md` — v0.3 計畫審查
- `plan-revision-v2.1.md` — v2.1 修訂 — 補完規劃不嚴謹處

---

## 閱讀路徑建議

### 路線 A:新成員(0 → 能貢獻)
1. [README.md](../README.md) — 30 秒概覽
2. [ARCHITECTURE.md](ARCHITECTURE.md) — 系統架構
3. [SETUP.md](SETUP.md) — 跑起來
4. [PLANS/strategic-gaps.md](PLANS/strategic-gaps.md) — 目前還缺什麼
5. [STATUS.md](STATUS.md) — 現在做到哪

### 路線 B:加新角色
1. [integration/persona-guide.md](integration/persona-guide.md) — Part A (資料層)
2. [PERSONA.md](PERSONA.md) — schema 細節
3. [integration/persona-guide.md](integration/persona-guide.md) — Part B (Unity 接線)

### 路線 C:加新功能(P0/P1/P2 任一)
1. [PLANS/open-llm-vtuber.md](PLANS/open-llm-vtuber.md) — 找對應 feature 段
2. 該段的 **vtuber 參考檔案** + **SIRO 整合點** 開始實作
3. [TESTING.md](TESTING.md) — 寫 pytest
4. 跑 `scripts/perf/measure_k2.py` + `measure_k8.py` 確認沒 regression

### 路線 D:出問題了
1. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 9 成問題這裡有
2. [STATUS.md](STATUS.md) — 確認版本/狀態
3. [bridge/security.py] / [bridge/confirmation.py] 程式碼查 audit log

### 路線 E:戰略 / 規劃決策
1. [PLANS/strategic-gaps.md](PLANS/strategic-gaps.md) — 10 個未解 gap
2. [PLANS/open-llm-vtuber.md](PLANS/open-llm-vtuber.md) — 19 個補完 feature
3. [history/decisions.md](history/decisions.md) + [history/strategic-notes.md](history/strategic-notes.md) — 過去怎麼決策
4. [ADR/](ADR/) — 較新的架構決策格式

---

## 統計

- **頂層 .md**:13 個(含 INDEX.md,都是高頻存取入口)
- **子目錄**:5 個(ADR / PLANS / integration / reference / history)
- **總 .md 數**:35 個(2026-06-17 重組後)
- **cross-references 已更新**:49 條(自動批改,涵蓋 17 個檔案)
