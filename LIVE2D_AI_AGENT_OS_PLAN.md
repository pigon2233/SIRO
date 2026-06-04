# SIRO - Live2D AI Agent 專屬作業系統

## 完整開發計畫書

> **版本**：v3.0（2026-06-04 對齊 v0.3 實況）
> **目標讀者**：本計畫書是給**人類與 AI 協作開發**用的規格文件，每個 Phase 都有明確的交付物、驗收條件、可委派的工作項目。
> **狀態**（2026-06-04）：
>
> - ✅ Phase 0 完成（所有文件就位）
> - ✅ Phase 1 完成（2026-06-03 Unity Play 實測）
> - ✅ Phase 1.5 / 1.75 完成（runtime 驗收過）
> - 🟡 **Phase 2 進行中** — v0.4 完成（SIRO_USE_AGENT_OS 預設翻 true + 視覺設定檔 + K8 量化）、v0.4+ 完成（Unity incremental render，提前 v1+ 規劃做）
> - ⏳ Phase 3 / 4 / 5 / 6 為規劃
> - **v0.3.1 進度**：選 Q2 選項 B（hermes_client streaming shim + Unity 端 incremental render 都完成）

> **重要 cross-ref**：
>
> - 階段細節：見各 Phase section（下方）
> - **v0.x 進度子版本**：見本檔「§5.5 v0.x 進度子表」（v0.2 / v0.3 / v0.3.1 詳細狀態）
> - 修訂記錄：`docs/PLAN_REVIEW_v0.3.md` + `docs/PLAN_REVISION_v2.1.md`（v0.3 期間的修訂歷史）
> - KPI 驗收：`docs/SETUP.md` §9（K1-K7 對應 v0.3 範圍）
> - 戰略決策：`docs/STRATEGIC_NOTES.md`（Q1 Rust、Q2 streaming + cross-reference 段）

---

## 目錄

1. [願景與定位](#1-願景與定位)
2. [核心設計原則](#2-核心設計原則)
3. [架構總覽](#3-架構總覽)
4. [技術堆疊](#4-技術堆疊)
5. [階段規劃](#5-階段規劃)
6. [介面契約](#6-介面契約)
7. [資料流](#7-資料流)
8. [風險登記](#8-風險登記)
9. [時間軸](#9-時間軸)
10. [AI 協作開發指南](#10-ai-協作開發指南)

---

## 1. 願景與定位

### 1.1 最終形態

一台獨立裝置，**開機直接看到 Live2D AI 角色**，所有互動都透過角色進行：

```
[開機]
  ↓ (5 秒內)
[Live2D 角色出現，問候使用者]
  ↓
[使用者用文字 / 語音 / 眼神與角色互動]
  ↓
[角色理解意圖，調用工具（行事曆、提醒、查資料…）]
  ↓
[角色執行動作並回應]
```

**這不是「在 OS 上跑 AI 應用」**。**這是「AI 本身就是 OS 的 shell」**。

傳統 OS 元素（桌面、應用程式圖示、檔案總管、視窗）全部不存在。取而代之的是：

- **AI 角色 = 唯一的 UI**
- 對話 = 唯一的輸入方式
- 角色動作 = 唯一的視覺回饋
- 語音 + 文字 = 唯一的輸出方式

### 1.2 目標使用者

- **v0 開發期**：自己（單一開發者）
- **v1 試用期**：自己 + 親友（2-10 台）
- **v2 量產期**：一般消費者（暫不規劃，>1 年後的事）

### 1.3 目標硬體

- **v0 開發**：現在這台 Windows 筆電（有獨顯）
- **v1 Linux 化**：同一台筆電改裝 Ubuntu Server 24.04 LTS
- **v1+ 擴展**：2-10 台同款 / 類似規格筆電

**硬體最低需求**（規劃中）：

- CPU：4 核心以上
- RAM：16GB（本地 LLM 需要）
- GPU：NVIDIA 獨顯 ≥ 6GB VRAM（CUDA 推論）
- 儲存：256GB SSD
- 螢幕：1080p 觸控（選配）
- 音訊：內建 + 麥克風陣列（選配）
- 視訊：內建 + 廣角鏡頭（選配）

---

## 2. 核心設計原則

這 5 條原則**所有設計決策都會檢查**。違反任何一條的設計都要明確說明為什麼。


| # | 原則                               | 違反的後果                   |
| - | ---------------------------------- | ---------------------------- |
| 1 | **Python for AI, Rust for system** | 混亂的語言選型、技術債       |
| 2 | **Skeleton before features**       | 過早最佳化、做出不能跑的東西 |
| 3 | **Real over aspirational**         | 文件與現實脫節、無法 demo    |
| 4 | **Reversible over complete**       | 一旦選了就回不去的決策       |
| 5 | **AI-actionable specs**            | 文件看不懂、無法委派         |

### 2.1 為什麼 Python + Rust


| 考量           | Python          | Rust    | 結論          |
| -------------- | --------------- | ------- | ------------- |
| LLM SDK 成熟度 | 極佳            | 弱      | **Python 勝** |
| 開發速度       | 快              | 慢      | **Python 勝** |
| 啟動時間       | 1-3 秒          | 10-50ms | **Rust 勝**   |
| 記憶體佔用     | 100MB+          | 5-20MB  | **Rust 勝**   |
| 套件依賴       | 重（venv、pip） | 零      | **Rust 勝**   |
| 系統呼叫       | 不便            | 直接    | **Rust 勝**   |
| 24/7 穩定度    | 需注意          | 強      | **Rust 勝**   |
| AI 工具        | 極佳            | 普通    | **Python 勝** |

**結論**：Python 做 AI 邏輯（變動多、迭代快），Rust 做系統服務（要求穩、要求快）。

### 2.2 語言邊界


| 層                      | 語言                  | 為什麼                          |
| ----------------------- | --------------------- | ------------------------------- |
| AI 整合（bridge/）      | Python                | LLM SDK、Hermes 整合、快速迭代  |
| 系統服務（os-runtime/） | Rust                  | 24/7 穩定、零 runtime、硬體控制 |
| 前端呈現（unity/）      | C#                    | Live2D SDK、Unity 生態          |
| 系統設定（os/）         | Shell + systemd       | Linux 原生                      |
| 工具腳本（scripts/）    | Shell + Python + Rust | 依用途                          |

---

## 3. 架構總覽

### 3.1 四層架構

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: System (Linux)                                    │
│  - Ubuntu Server 24.04 LTS                                  │
│  - systemd                                                  │
│  - 唯讀 rootfs、kiosk 模式、安全政策                            │
└─────────────────────────────────────────────────────────────┘
            ▲
            │ systemd service / Unix socket
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: System Runtime (Rust)                             │
│  - siro-runtime: 監控所有服務、kiosk、硬體抽象                    │
│  - siro-ctl: CLI 工具                                       │
│  - 與 Layer 2 透過 gRPC / Unix socket 通訊                    │
└─────────────────────────────────────────────────────────────┘
            ▲
            │ gRPC / Unix socket
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: AI Bridge (Python)                                │
│  - FastAPI: HTTP / WebSocket                                │
│  - Hermes Agent 整合                                        │
│  - 情緒解析、session 管理                                     │
│  - 與 Layer 1 透過 WebSocket 通訊                            │
└─────────────────────────────────────────────────────────────┘
            ▲
            │ WebSocket
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Presentation (C# Unity)                           │
│  - Live2D 渲染                                              │
│  - 表情動作                                                  │
│  - UI（文字 / 語音輸入）                                       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 模組職責矩陣


| 模組                      | 語言   | 啟動順序          | 通訊對象                  | 失敗處理                     |
| ------------------------- | ------ | ----------------- | ------------------------- | ---------------------------- |
| `os-runtime/siro-runtime` | Rust   | 第一個（systemd） | systemd、bridge、硬體     | watchdog 自動重啟            |
| `agent/` (Hermes CLI)     | Python | 第二個            | LLM Provider              | subprocess 錯誤回傳給 bridge |
| `bridge/main.py`          | Python | 第三個            | hermes、unity、os-runtime | FastAPI 健康檢查             |
| `unity/` (Unity build)    | C#     | 第四個            | bridge                    | 重連機制                     |

### 3.3 部署拓樸

**v0 開發期（現在的 Windows 筆電）**：

```
[Windows 11]
  ├─ Unity Editor (Play 模式)
  ├─ Python venv + uvicorn (bridge)
  ├─ Hermes CLI (subprocess)
  └─ WSL2 (選用，模擬 Linux 環境)
```

**v1 Linux 化（同筆電改裝）**：

```
[Ubuntu Server 24.04 LTS]
  ├─ systemd: siro-runtime.service (第一個啟動)
  ├─ systemd: hermes.service
  ├─ systemd: siro-bridge.service
  ├─ systemd: siro-unity.service (最後啟動，kiosk 全螢幕)
  └─ X11 / Wayland kiosk session
```

---

## 4. 技術堆疊

### 4.1 Layer 1: Presentation (Unity)


| 元件      | 技術                    | 理由                             |
| --------- | ----------------------- | -------------------------------- |
| 引擎      | Unity 6 LTS             | Live2D SDK 最完整支援            |
| Live2D    | Cubism SDK for Unity    | 官方 SDK，expression/motion 完整 |
| WebSocket | `System.Net.WebSockets` | 內建，無需外部套件               |
| JSON      | `Newtonsoft.Json`       | 內建套件                         |
| UI        | UGUI + TextMeshPro      | 標準                             |
| 模型      | Hiyori (Cubism 官方)    | 免費可商用                       |

### 4.2 Layer 2: AI Bridge (Python)


| 元件      | 技術                          | 理由                     |
| --------- | ----------------------------- | ------------------------ |
| 框架      | FastAPI + uvicorn             | 簡單、async 原生、文件佳 |
| WebSocket | FastAPI 內建                  | 與 HTTP 同源             |
| LLM 整合  | Hermes Agent CLI (subprocess) | 不用自接 API key 管理    |
| 環境管理  | uv                            | 跟 Hermes 一致、快       |
| Schema    | Pydantic v2                   | 強型別、自動驗證         |
| 測試      | pytest + httpx                | 標準                     |
| 套件管理  | `bridge/requirements.txt`     | 簡單                     |

**Python 版本**：3.11+（與 Hermes 一致）

### 4.3 Layer 3: System Runtime (Rust)


| 元件      | 技術                                     | 理由              |
| --------- | ---------------------------------------- | ----------------- |
| Runtime   | tokio                                    | 標準 async 執行緒 |
| HTTP/gRPC | tonic (gRPC) + axum (HTTP)               | 業界標準          |
| CLI       | clap                                     | 主流 CLI 框架     |
| Systemd   | sd-notify + zbus                         | 原生整合          |
| Config    | figment + TOML                           | 多層 config 來源  |
| Logging   | tracing                                  | 結構化日誌        |
| Error     | thiserror + anyhow                       | 慣用模式          |
| Audio     | cpal + rubato                            | 跨平台音訊        |
| Display   | winit + wgpu                             | 視窗管理          |
| Camera    | v4l2 (Linux) / mediafoundation (Windows) | 跨平台            |
| GPU       | cuda-rs (未來)                           | 本地 LLM 推論     |
| Build     | cargo + cross                            | 跨編譯            |

**Rust 版本**：1.80+ stable
**目標平台**：`x86_64-unknown-linux-gnu` (Ubuntu)

### 4.4 Layer 4: System (Linux)


| 元件    | 技術                                        | 理由                     |
| ------- | ------------------------------------------- | ------------------------ |
| 發行版  | Ubuntu Server 24.04 LTS                     | 5 年支援、套件齊、文件多 |
| Init    | systemd                                     | Ubuntu 預設              |
| 桌面    | **無**（kiosk 全螢幕）                      | 設計目標                 |
| Display | X11 + openbox (v0.5) → Wayland + Cage (v1) | 從熟悉到現代             |
| 安全    | AppArmor + ufw                              | 標準 Ubuntu 工具         |
| 套件    | apt                                         | 標準                     |
| 監控    | systemd journal + promtail                  | 標準                     |

### 4.5 開發工具


| 用途           | 工具                                |
| -------------- | ----------------------------------- |
| 版本控制       | git + GitHub                        |
| Editor         | VS Code / Cursor                    |
| AI 助手        | Claude Code（本倉庫就是用 AI 寫的） |
| CI/CD          | GitHub Actions                      |
| Issue tracking | GitHub Issues                       |
| 文件           | Markdown (本倉庫)                   |
| 圖表           | Mermaid（在 Markdown 內）           |
| API 文件       | OpenAPI 自動生成（FastAPI）         |

---

## 5. 階段規劃

### Phase 0: 規劃與環境建立 ✅ 完成

**目標**：完成架構設計、建立 monorepo 結構、定下所有技術選型

**交付物**（2026-06-04 對齊）：

- [X]  主計畫書（本檔，v3.0）
- [X]  `docs/ARCHITECTURE.md`（v0.3 對齊、4 層架構、Layer 2 加 AgentOS + SSE streaming）
- [X]  `docs/DECISIONS.md`（19 個決策 + #001 v0.2 streaming 觀察）
- [X]  `os-runtime/` Rust workspace scaffold（Cargo.toml + crates + proto，**功能實作留 Phase 3**）
- [X]  `os/` Linux 設定目錄結構（10 子目錄、kiosk/systemd/monitoring/backup/security 有詳細規劃）
- [X]  `hardware/` 硬體規格文件（assembly/audio/video/detection + 自動驗證腳本）
- [X]  `docs/SECURITY.md`（v0.3 隱私路線圖）
- [X]  `docs/DEPLOYMENT.md`（Phase 4+ 部署指南）
- [X]  `docs/API.md`（bridge API 規格）
- [X]  `docs/TESTING.md`（測試 SOP）
- [X]  `docs/CONTRIBUTING.md`
- [ ]  `scripts/dev/` 開發輔助腳本（目前只有 `scripts/build-docs-html.py`、缺統一 dev helpers）

**驗收條件**：

- [X]  所有文件互引一致（v0.3 期間修訂過 PLAN_REVIEW / PLAN_REVISION / SETUP / ARCHITECTURE / STATUS / AGENT_OS / DECISIONS / STRATEGIC_NOTES）
- [ ]  `os-runtime/` 可以 `cargo build` 通過（**待 Phase 3**、scaffold 在但實作沒做）
- [X]  `bridge/` 可以 `python -m bridge.main` 啟動（v0.2+ 實測）

**預估時間**：~1 週（v0.3 期間多次修訂）
**依賴**：無
**風險**：低

---

### Phase 1: 核心大腦 (Python) — ✅ 完成

**目標**：完成 Hermes 整合、bridge 服務、純文字對話 + Live2D 表情切換

**範圍**：

- Python bridge 服務
- Hermes CLI 整合（subprocess）
- 情緒解析
- Unity 文字輸入 + 表情切換（+ 自動重連）
- 本地 LLM（Ollama + GPU）
- gRPC client stub（為 Phase 3 鋪路）

**交付物**：

- [X]  `bridge/` 完整實作
- [X]  `bridge/tests/` **93% 覆蓋率（78 active tests, 0 fail）**
- [X]  `unity/Assets/Scripts/` 完整實作（含 WebSocket 自動重連 + 指數 backoff）
- [X]  `agent/install.sh` 跑通（自動 fallback 到 clone+uv 模式）
- [X]  `agent/verify.sh` 跑通（5/5 通過）
- [X]  `docs/SETUP.md` 從零到能跑的完整步驟
- [X]  `bridge/runtime_client.py` Layer 3 gRPC client stub
- [X]  Hermes Agent 實際安裝：v0.15.1，clone+uv 模式
- [X]  LLM 設定：Ollama + llama3.2:3b-instruct-q4_0（128K context）
- [X]  **E2E 驗證**：bridge → Hermes → Ollama → 回應「HELLO!」
- [X]  Unity Play 模式實機測試（✓ 實測，2026-06-03，使用 Mao 模型 9 種情緒對應 8 個 expression）

**驗收條件**：

- [X]  `bash agent/install.sh` 自動偵測+安裝（✓ 實測）
- [X]  `bash agent/verify.sh` 5/5 通過（✓ 實測，2026-06-02）
- [X]  `python -m bridge.main` 啟動無錯誤（✓ 實測）
- [X]  `curl localhost:8001/health` 回 200 with `hermes_available: true`（✓ 實測）
- [X]  `curl localhost:8001/chat` 拿到含 LLM 回應（✓ 實測，回 "HELLO!"）
- [X]  `python -m pytest bridge/tests/ -v` 全綠（✓ 78/78 pass）
- [X]  覆蓋率 ≥ 80%（✓ 92%）
- [X]  Unity Play 模式能跟 Mao 打字對話（✓ 實測，2026-06-03，9 情緒切換 + 中文 + 眼球 hack）

**真實安裝紀錄**（這台筆電上的）：

- Hermes: v0.15.1 (2026.5.29) @ `~/hermes-agent/.venv/Scripts/hermes.exe`
- WSL Ubuntu 安裝失敗（`wsl.exe` WININET timeout），改用 clone+uv 模式成功
- LLM: Ollama + llama3.2:3b-instruct-q4_0（1.9GB VRAM，128K context）
- Hermes config: `~/.hermes/config.yaml` 設 `model.provider=custom`, `base_url=http://localhost:11434/v1`, `model.default=llama3.2:3b-instruct-q4_0`, `model.context_length=128000`
- E2E 對話測試回應：`"HELLO!"`、 `"Testing successful."`

**遇到的真實問題與解法**：

- 🔴 `wsl.exe` 內部 WININET timeout：繞過，直接 clone + uv
- 🔴 Hermes CLI 介面是 `-z` 不是 `-p`：修正 hermes_client.py
- 🔴 Hermes CLI 輸出格式 `{object : {text: "..."}}`：加 `_parse_hermes_output` 解析
- 🔴 Windows console cp950 編碼錯 UTF-8：subprocess.run 加 `encoding="utf-8" errors="replace"`
- 🟡 qwen2.5:3b 只有 32K context（Hermes 要 64K+）：改用 llama3.2:3b 128K，override context_length
- 🟡 hermes --version 在 `| head -1` 會 SIGPIPE：改用暫存變數

**預估時間**：✅ 實際 ~3 小時（從 v0.5 進度繼續，比預期快）
**依賴**：Phase 0
**風險**：

- ✅ Hermes 介面已驗證清楚（-z flag, 包裝輸出格式）
- ✅ Unity + Cubism SDK 已實機驗證（2026-06-03，9 情緒對 8 expression）

---

### Phase 1.5: GAPS 立刻補強 ✅ 完成（2026-06-03 runtime 驗收過）

**目標**：填補 [docs/GAPS.md](docs/GAPS.md) 中「不做會卡 Phase 2-3」的 5 項缺口。

**動機**：
Phase 1 把「能跟 Mao 文字對話」這件事跑通了，但發現幾個**架構性缺口**會影響後續所有 Phase：

- 角色 SIRO 性格直接 hardcode 在 [bridge/prompts.py](bridge/prompts.py)，未來換角色要重寫
- bridge / Hermes 掛掉時 Mao 直接沉默無回應，UX 很差
- 資料存哪、誰能讀、是否加密 — 完全沒寫
- Phase 結束標準靠主觀感覺，沒量化 KPI

不修這 5 項就硬上 Phase 2 polish，會做出「視覺美 + 結構爛」的成品，未來重構成本高。

**範圍**：

- Persona schema 抽離（資料與程式碼分離）
- 離線降級基礎（bridge + Unity 雙端）
- 隱私現況釐清（不做加密實作，先寫清楚現況 + 未來路線圖）
- KPI 量化（每 Phase 驗收要有數字）

**交付物**：

- [X]  [docs/PERSONA.md](docs/PERSONA.md) — Persona schema 規範
- [X]  `bridge/personas/siro-default.yaml` — SIRO 第一個 Persona
- [X]  [bridge/prompts.py](bridge/prompts.py) 改 — 從 YAML 讀，不再 hardcode
- [X]  bridge 端離線降級 — Hermes 死時走**兩段式 fallback**（Ollama llama3.2:3b → persona 靜態文字 + thinking）
- [X]  Unity 端降級 UX — bridgeClient 斷線時切 thinking 表情 + UI 提示「連線中...」
- [X]  [docs/SECURITY.md](docs/SECURITY.md) 加 §0 — 一頁釐清資料現況 + Phase 4-6 加密路線圖
- [X]  PLAN.md 加 KPI 章節 + 串進每個 Phase 驗收條件

**驗收條件**：

- [X]  [docs/SECURITY.md](docs/SECURITY.md) §0 回答：資料存哪 / 誰能讀 / 重啟後留多少 / v1 加密計畫
- [X]  PLAN.md 每個 Phase 有量化驗收（K1-K10 對應 — 見每 Phase 章節）
- [X]  PLAN.md Phase 2-6 都有 GAPS 對應子節（剩 5 項分散處理）
- [X]  **runtime**（2026-06-03）：Primary LLM 切到 MiniMax-M3，600s timeout 走 Ollama fallback — 實機驗證 Mao 中文回應、情緒表情切換、emoji 過濾、strong signal（難過/生氣/驚訝）、WebSocket 自動重連、Ctrl+C 乾淨關閉全通過
- [X]  **runtime**（2026-06-03）：Persona YAML 載入驗證 — bridge 啟動 log 顯示「✓ 載入 persona: siro-default (v0.1.0)」，Mao 回應符合 SIRO 性格
- [X]  **runtime**（2026-06-03）：Ollama soft fallback E2E 測試（`bridge/ollama_client.py` + `_try_ollama_fallback`）— 程式驗證 `你好` 真的拿到 `[emotion:happy]` 標籤的中文回應

**預估時間**：1 週（實際 2026-06-02 ~ 2026-06-03，含 runtime 驗收）
**依賴**：Phase 1 ✅
**風險**：

- 🟢 YAML schema 是純結構工作、低風險
- 🟡 離線降級要驗 edge case（bridge restart、Hermes timeout、Unity 斷線重連）— 2026-06-03 已實機驗證
- 🟢 文件工作，無技術風險

**為什麼不直接進 Phase 2**：
Phase 2 是視覺 polish（待機動作、平滑過渡）— 但 polish 之前要先有穩固的「能持續對話」基礎。Phase 1.5 把這基礎打好，Phase 2 才能專心做視覺。GAPS 剩下的 5 項（i18n / STT-TTS / 災難恢復 / OTA UX / 多人識別）依時機分散到 Phase 2-6，不阻塞 Phase 1.5。

**Runtime 驗收紀錄**（2026-06-03）：

- 改動 commits：`d406e69`（MiniMax-M3 路由 + 兩段式 fallback）、`25155f9`（修 get_version cp950 解碼 bug）
- 測試項：T1 啟動日誌 / T2 Unity 基本對話 / T3 強情緒（難過/生氣/驚訝）/ T4 emoji 過濾 / T5 WebSocket 重連（顯示「連線中...」+ thinking 表情）/ T6 Ctrl+C 乾淨關閉
- 結果：6/6 全通過，使用者確認「都沒有問題」

---

### Phase 2: 視覺呈現強化 (Unity + Live2D) — 🟡 進行中（v0.3.1）

**目標**：完善 Live2D 互動體驗、加上視覺效果、把 bridge 升級成「後台作業系統」

**GAPS 對應** ([docs/GAPS.md](docs/GAPS.md))：

- **#10 i18n**：UI 字串抽到 `i18n/zh-TW.json`，為未來換 Persona 換語言鋪路
- **#9 降級路徑（細化）**：Phase 1.5 只做了「連線中」提示，Phase 2 要做更細：subprocess 卡住 vs 完全斷線 vs LLM timeout 的不同 UI 表現

**範圍**：

- 表情平滑過渡
- 待機動作（呼吸、眨眼）— 注意跟 eye-hiding hack (`hideEyeOnExpressions`) 不要打架
- 點擊互動
- Loading 狀態視覺（接續 Phase 1.5 的「連線中...」做更細）
- 多個 Mao motion（idle, tap head, tap body）
- UI 字串抽出（i18n 基礎）
- **bridge 升級成後台作業系統（AgentOS）** — v0.2 骨架 / v0.3 接到 /chat /ws
- **SSE streaming 基礎建設** — v0.3.1 選項 B（MiniMaxStreamingClient）

**v0.x 進度子表**（v0.2 → v0.4+ 都屬 Phase 2，**v1.0+ 見「v1+ Roadmap」段**）：


| 子版本     | 狀態 | 重點                                                                      | 對應 commit                             |
| ---------- | ---- | ------------------------------------------------------------------------- | --------------------------------------- |
| **v0.2**   | ✅   | AgentOS 骨架（Task Queue + Event Bus + Worker Pool）                      | `f56c4e2`                               |
| **v0.3**   | ✅   | /chat /ws opt-in 走 AgentOS、Task.id、EventBus unsubscribe、wait_for_task | `73b78b8` `6698fa6` `da28d9f` `02c7381` |
| **v0.3.1** | ✅   | SSE streaming 基礎建設（MiniMaxStreamingClient + /ws 推 delta）           | `99de74c` `d96351b`                     |
| **v0.4**   | ✅   | `SIRO_USE_AGENT_OS` 預設翻 `true`（v0.3 觀察穩定後翻）、5 個新 TestUseAgentOSDefault 測試 | `c1a3dc5`                              |
| **v0.4+**  | ✅   | Unity 端 incremental render（接 /ws 的 delta 訊息，**提前於 v1+ 規劃做**— 詳見 STRATEGIC_NOTES.md Q2）| `0dd9da7`                              |
| **v1.2**   | ✅   | SendTask + OnClick：bridge 5 個 built-in task + registry + WS handler + Unity SendTaskAsync + OnMaoClicked + PersonaClickHandler | `7f2d4f7` `91b5dec` `5fc448d` `0a2ab7d` |

**交付物**（混合：v0.3 完成的 + 仍待做的）：

- [X]  i18n 基礎：`SiroUnity/Assets/Resources/i18n/zh-TW.json` + `Localization.cs` helper + `ChatInputUI` / `PersonaSelectorUI` 接入
- [X]  待機動作自動 loop（mtn_01）— `2d77361`
- [X]  AgentOS 骨架（v0.2）
- [X]  AgentOS 接到 /chat 跟 /ws（v0.3、opt-in via `SIRO_USE_AGENT_OS`）
- [X]  SSE streaming 基礎建設（v0.3.1、opt-in via `SIRO_STREAMING`）
- [X]  MiniMaxStreamingClient + 13 單元測試 + 2 整合測試
- [X]  視覺設定檔（亮度、縮放寫進 Persona YAML `model.visual`）— 視覺設定檔 v0.3 收尾
- [X]  K8 fallback 量化（< 3s assertion）
- [X]  `SIRO_USE_AGENT_OS` 預設翻 `true`（v0.4 翻預設、逃生 `=false`）
- [X]  Unity 端 incremental render 接 /ws delta 訊息（**v0.4+ 提前做**，原本規劃 v1+ 一起做 — 詳見 STRATEGIC_NOTES Q2）
- [X]  **v1.2** SendTask + OnClick（Unity 推 task 進 AgentOS、`Live2DModelController.OnMaoClicked` + `PersonaClickHandler` 串接、5 個 built-in：mood.set / motion.play / persona.switch / chat.say / chat.summon）
- [ ]  `Live2DModelController` 表情過渡動畫（⏸ 暫停）
- [ ]  點擊 Mao motion（⏸ 暫停 — v1.2 MVP 不分 hit area，v1.5+ 用 CubismHitDrawable）
- [ ]  Loading 狀態視覺（⏸ 暫停）
- [ ]  截圖功能（⏸ 暫停）

**驗收條件**（對應 KPI）：

- [X]  改 `i18n/zh-TW.json` UI 不用改 code 就變中文（zh-TW 預設、`en-US.json` 留 v1+）
- [X]  **K10**: bridge tests 覆蓋率 ≥ 80%（✅ 188+2 = 190 tests pass、v0.3 期間多次擴充）
- [ ]  角色不說話時有自然的待機動作（呼吸、眨眼週期不固定）— 待機動作 ✅、呼吸/眨眼 ⏸ 暫停
- [ ]  **K5**: 表情切換延遲 < 200ms（量測 `SetExpression` 到 Cubism render 完成）— 工具可量、視覺未動
- [ ]  表情切換有 0.3-0.5s 平滑過渡、不閃爍、不穿幫（⏸ 暫停）
- [ ]  點擊角色有反饋（Mao 看向滑鼠 / 切表情）（⏸ 暫停）
- [X]  **K2**: streaming UX 改善（TTFT < 5s、邊收邊 render）— wire ✅（v0.3.1） + Unity incremental render ✅（v0.4+ commit 0dd9da7）；KPI 量化（實際 TTFT 量測）留 v1+ production 觀察

**預估時間**：剩餘 ~1 週（4 個視覺項目）
**依賴**：Phase 1.5 ✅
**風險**：

- 🟡 Cubism SDK 的 motion 觸發需要 Animator 設定（要 Unity Editor 手動）
- 🟢 視覺效果問題可以延後處理
- 🟢 Unity incremental render（v0.4+）+ SendTask（v1.2）都完成；剩 4 個視覺項目 + 1 個 SendTask 細化（v1.5+ LLM tool calling、v2.0 持久化）

---

### Phase 3: Rust 系統層

**目標**：建立 Rust 系統 daemon，提供 OS 級服務管理

**GAPS 對應** ([docs/GAPS.md](docs/GAPS.md))：

- **#2 多模態（音訊基礎）**：Rust 端 audio pipeline 草案（cpal 採音 → STT pipe → bridge）。STT/TTS 模型選型（whisper.cpp / piper）。實際語音整合留 Phase 5（要硬體）
- **#4 離線降級（細化）**：siro-runtime 完整 health check pipeline — bridge 死 → siro-supervisor 偵測 → 重啟 → Unity 看到「siro reloading」
- **#9 降級路徑（per-subsystem）**：每個 subsystem 失敗都要定義「使用者會看到什麼」+「角色解釋話術」

**範圍**：

- `siro-runtime` daemon
- 監控 bridge、hermes、unity 進程
- 崩潰自動重啟
- 與 bridge 的 gRPC IPC
- 硬體抽象（音訊、視訊、顯示）
- 設定管理
- Logging
- **STT/TTS 選型 ADR** + Rust 端 audio I/O 接口

**交付物**：

- [ ]  `os-runtime/Cargo.toml` workspace
- [ ]  `os-runtime/crates/siro-runtime/` 主 daemon
- [ ]  `os-runtime/crates/siro-ctl/` CLI 工具
- [ ]  `os-runtime/crates/siro-ipc/` IPC protocol 定義
- [ ]  gRPC proto 檔（與 bridge 共用）
- [ ]  進程 supervisor（重啟時 Unity 收到 "siro reloading" event，不會看到突兀斷線）
- [ ]  硬體偵測
- [ ]  設定檔讀寫
- [ ]  `docs/STT_TTS_DECISION.md` — 選型 ADR（whisper.cpp / piper / 雲端）
- [ ]  `docs/SUBSYSTEM_FAILURE.md` — per-subsystem 失敗 → 角色話術對應表
- [ ]  `os-runtime/tests/` 80% 覆蓋率
- [ ]  `os-runtime/README.md` 開發指南

**驗收條件**（對應 KPI）：

- [ ]  `siro-runtime` 可以 `cargo build --release` 通過
- [ ]  `siro-ctl status` 顯示所有服務狀態
- [ ]  kill bridge 進程後 < 5 秒自動重啟（不是只「會重啟」，要量測時間）
- [ ]  gRPC 介面與 bridge 對接測試通過
- [ ]  **K2**: 使用者輸入 → 角色回應 < 2 秒（本地 LLM）
- [ ]  **K8**: 任意 subsystem 死掉 → Mao 在 < 3 秒切 fallback 表情
- [ ]  記憶體常駐 < 30MB
- [ ]  **K10**: os-runtime 覆蓋率 ≥ 80%

**預估時間**：3-4 週
**依賴**：Phase 1（bridge API）、Phase 1.5（fallback 概念）
**風險**：

- 🔴 Rust 學習曲線（第一次寫可能踩坑多）
- 🟡 gRPC proto 跨語言相容性
- 🟢 進程 supervisor 是常見 pattern，風險低

---

### Phase 4: Linux 客製化

**目標**：把現在的 Windows 開發機改成 Ubuntu Server 24.04 LTS 雙系統（或全替換）

**GAPS 對應** ([docs/GAPS.md](docs/GAPS.md))：

- **#1 隱私（加密實作）**：LUKS 全碟加密（安裝時開）+ age 應用層加密敏感資料 + SQLite 持久對話歷史（加密儲存）+「忘記我」按鈕
- **#10 i18n（系統層）**：LANG / LC_ALL 統一設 zh_TW.UTF-8，systemd journal 多語環境變數，IME 設定

**範圍**：

- Ubuntu Server 24.04 LTS 安裝
- NVIDIA 驅動 + CUDA 工具鏈
- 唯讀 rootfs
- systemd 服務整合
- 安全政策（AppArmor、ufw）
- Kiosk 模式（X11 + openbox）
- 自動登入 + 開機啟動
- **LUKS 全碟加密 + age 應用層加密**
- **持久對話歷史（SQLite + age 加密）**
- **i18n LANG 環境設定**

**交付物**：

- [ ]  `os/install/` 自動安裝腳本（含 LUKS prompt）
- [ ]  `os/systemd/*.service` 服務定義
- [ ]  `os/kiosk/` X11 / openbox 設定
- [ ]  `os/security/` AppArmor profiles
- [ ]  `os/network/` ufw rules
- [ ]  `os/README.md` 安裝步驟
- [ ]  `bridge/memory/` SQLite + age 對話歷史持久化（取代 Phase 1 的 RAM-only state.sessions）
- [ ]  「忘記我講過的話」UI 按鈕 + bridge DELETE endpoint
- [ ]  開機到 Live2D 角色出現 < 30 秒

**驗收條件**（對應 KPI）：

- [ ]  **K1**: 開機到對話就緒 < 30 秒
- [ ]  開機自動進入 kiosk，無手動操作
- [ ]  切換 Windows ↔ Linux 雙系統正常
- [ ]  **K2**: NVIDIA GPU CUDA 跑本地 LLM 推論 < 2 秒回應
- [ ]  重啟 10 次都正常
- [ ]  **K3**: 跑 7 天不 crash
- [ ]  **K4**: 角色記得 N ≥ 30 天前對話（SQLite 持久化）
- [ ]  **K7**: 預設無雲端外洩（封掉 ufw outgoing 仍能跑）
- [ ]  硬碟壞一個 sector 不影響運作（RAID 或定期備份）

**預估時間**：2-3 週
**依賴**：Phase 3（Rust 服務要先有）
**風險**：

- 🔴 NVIDIA 驅動安裝可能有相容性問題
- 🔴 雙系統 / 完整替換要決策
- 🟡 Kiosk 模式有眉角（keybind 鎖定、escape hatch）
- 🟡 systemd 服務啟動順序要 tune
- 🟡 LUKS + age key 管理（key 丟了資料解不出來，但這是設計）

---

### Phase 5: 硬體整合

**目標**：把系統打包到實際的硬體配置上

**GAPS 對應** ([docs/GAPS.md](docs/GAPS.md))：

- **#2 多模態（語音實裝）**：Phase 3 選好的 STT/TTS 模型在真實 mic/speaker 上整合 + 延遲量測
- **#1 隱私（硬體層）**：mic/camera 實體指示燈（系統用 ↔ LED 亮）+ 麥克風硬體開關

**範圍**：

- 音訊設定（內建麥克風、外接 USB 麥克風陣列）
- 視訊設定（內建視訊、外接 USB 視訊）
- 觸控螢幕支援（選配）
- 鍵盤滑鼠封鎖（kiosk 安全）
- 電源管理
- 散熱管理
- 實體按鈕（選配：重啟、靜音）
- **STT/TTS pipeline 真實硬體整合**
- **mic/camera 指示燈（GPIO LED 或軟體 overlay）**

**交付物**：

- [ ]  `hardware/specs.md` 推薦硬體清單
- [ ]  `hardware/audio.md` 音訊設定 + STT/TTS pipeline 量測
- [ ]  `hardware/camera.md` 視訊設定 + 指示燈電路
- [ ]  `hardware/assembly.md` 組裝指南（如果是改裝筆電）
- [ ]  `os/audio/` ALSA / PulseAudio 設定
- [ ]  `os/video/` V4L2 設定
- [ ]  `os/power/` power management
- [ ]  `os/indicators/` mic/camera LED 控制 service
- [ ]  熱監控 + 風扇控制

**驗收條件**（對應 KPI）：

- [ ]  麥克風收音清楚、距離 1 米可辨識
- [ ]  攝影機人臉偵測可抓到 1-3 米距離
- [ ]  觸控螢幕點擊準確（如果有的話）
- [ ]  鍵盤訊號被鎖（kiosk 模式生效）
- [ ]  **K6**: TTS 開始播放 < 1.5 秒（量測 LLM 結束 → 第一個 audio chunk）
- [ ]  mic 在用 → LED 亮，mic 沒在用 → LED 滅（兩者狀態 1 秒內同步）
- [ ]  散熱穩定，CPU 溫度 < 80°C
- [ ]  電源中斷恢復自動開機

**預估時間**：1-2 週
**依賴**：Phase 4
**風險**：

- 🟡 不同硬體相容性差異大
- 🟢 大部分是設定工作，風險可控

---

### Phase 6: 部署與營運

**目標**：可以快速複製到 2-10 台裝置、支援 OTA 更新

**目標**：可以快速複製到 2-10 台裝置、支援 OTA 更新

**GAPS 對應** ([docs/GAPS.md](docs/GAPS.md))：

- **#5 災難恢復**：4 級災難（角色記憶損毀 / 系統當機 / SSD 壞 / 整台丟）的恢復 SOP + 備份格式（角色 + 記憶 + 設定 + 對話歷史 + age 加密）
- **#6 OTA UX**：升級狀態 state machine、角色升級前主動告知、失敗自動回滾、避開使用者常用時段
- **#8 多人識別**：使用者 profile schema、預設裝置隔離、手動匯出匯入

**範圍**：

- 系統映像檔建立（Packer）
- 設定檔管理（每台裝置不同）
- OTA 更新機制 + UX state machine
- 遙測（log 集中、健康檢查）
- 備份 / 還原（含加密）
- 監控與警報
- **災難恢復 SOP（4 級）**
- **使用者 profile schema（裝置 = 帳號，v1 不做切換）**
- **一頁 Privacy Policy（給親友看）**

**交付物**：

- [ ]  `scripts/build-image.sh` Packer 腳本
- [ ]  `scripts/ota-update.sh` OTA 工具（含簽章驗證 + A/B partition）
- [ ]  `os/config-template/` 每台裝置的 config 範本
- [ ]  `os/backup/` 備份腳本（restic + age）
- [ ]  `os/monitoring/` 健康檢查 + 警報
- [ ]  `docs/DEPLOYMENT.md` 部署 SOP
- [ ]  `docs/OPERATIONS.md` 營運手冊
- [ ]  `docs/DISASTER_RECOVERY.md` — 4 級災難恢復 SOP
- [ ]  `docs/PRIVACY.md` — 給使用者的一頁版（從 SECURITY.md 提煉）
- [ ]  「桌面備份/還原」UI 按鈕（爸媽會按的等級）
- [ ]  OTA 升級 state machine 實作（升級中、回滾、失敗）
- [ ]  角色升級話術（「我需要重啟一下」「剛剛有點不適」）
- [ ]  第一台以外的測試（朋友 / 家人）

**驗收條件**（對應 KPI）：

- [ ]  **K1**: 從 0 到完成部屬一台裝置 < 30 分鐘
- [ ]  OTA 更新一輪 < 10 分鐘、不中斷服務（升級中角色說「我重啟一下」而非直接斷）
- [ ]  設定一台裝置只需要改一個 config 檔
- [ ]  log 集中可查詢
- [ ]  **L1 災難** (記憶損毀) 恢復 < 5 分鐘
- [ ]  **L2 災難** (系統當機) 恢復 < 2 分鐘（systemd 重啟）
- [ ]  **L3 災難** (SSD 壞) 恢復 < 1 小時（image restore）
- [ ]  **L4 災難** (整台丟) 恢復 < 1 天（雲端加密備份）
- [ ]  OTA 升級中斷 → 自動回滾、不磚機

**預估時間**：2-3 週
**依賴**：Phase 4 + 5
**風險**：

- 🟡 OTA 安全（要 code signing、避免磚機）
- 🟢 Packer 與 systemd 相容性 OK
- 🟢 小規模 fleet 不需要複雜管理工具
- 🟡 親友當小白鼠的 UX 反饋（要快速迭代）

---

### 成功指標 (KPI)

> 每個 Phase 結束時要量化驗收。沒 KPI = 永遠「還沒做完」。


| #   | 面向 | 指標                         | 目標                               | Phase      |
| --- | ---- | ---------------------------- | ---------------------------------- | ---------- |
| K1  | 啟動 | 開機到對話就緒               | < 30 秒                            | Phase 4    |
| K2  | 反應 | 使用者輸入到角色回應         | < 2 秒（本地 LLM）/ < 5 秒（雲端） | Phase 1, 3 |
| K3  | 穩定 | 24/7 連續運行                | 7 天無當機                         | Phase 4    |
| K4  | 記憶 | 角色記得 N 天前對話          | N ≥ 30                            | Phase 1.5+ |
| K5  | 表情 | 表情切換延遲                 | < 200ms                            | Phase 2    |
| K6  | 語音 | TTS 開始播放                 | < 1.5 秒                           | Phase 2-3  |
| K7  | 隱私 | 預設資料外洩風險             | 0（無雲端 default）                | Phase 1.5  |
| K8  | 降級 | 子系統失敗時角色保持「在線」 | < 3 秒切 fallback                  | Phase 1.5  |
| K9  | 可用 | 5 歲到 80 歲會用             | v2 驗證                            | v2         |
| K10 | 測試 | bridge 覆蓋率                | ≥ 80%                             | Phase 1+   |

每個 Phase 的「驗收條件」應該至少對應 1-3 個 KPI 的數字，**不是**靠「看起來能用」。

詳細：見 [docs/KPI.md](docs/KPI.md)（待寫）。

---

## 6. 介面契約

### 6.1 Bridge HTTP API（Layer 2）

**`GET /health`**

```json
{
  "status": "ok",
  "hermes_available": true,
  "hermes_version": "v0.15.2",
  "bridge_version": "0.1.0"
}
```

**`POST /chat`**

```json
// Request
{
  "message": "你好",
  "user_id": "test_user",
  "session_id": null,  // 自動產生
  "personality": "default"
}

// Response
{
  "text": "你好呀！",
  "emotion": "happy",
  "intensity": 0.8,
  "live2d": {
    "expression_id": "F02",
    "motion_group": "Idle",
    "motion_index": 0,
    "intensity": 0.8,
    "duration_ms": 500
  },
  "session_id": "test_user-abc12345",
  "user_id": "test_user"
}
```

**`WS /ws`**：見 [docs/API.md](docs/API.md)

### 6.2 Rust Runtime gRPC（Layer 2 ↔ Layer 3）

定義在 `os-runtime/crates/siro-ipc/proto/siro.proto`：

```protobuf
syntax = "proto3";
package siro;

service SiroControl {
  // 查詢所有服務狀態
  rpc GetStatus(Empty) returns (SystemStatus);
  // 重啟指定服務
  rpc RestartService(ServiceName) returns (Ack);
  // 取得硬體資訊
  rpc GetHardwareInfo(Empty) returns (HardwareInfo);
  // 切換 kiosk 模式
  rpc SetKioskMode(KioskRequest) returns (Ack);
  // 健康檢查
  rpc Health(Empty) returns (HealthStatus);
  // 串流 log（給 monitoring）
  rpc StreamLogs(LogFilter) returns (stream LogEntry);
}

message Empty {}

message SystemStatus {
  map<string, ServiceState> services = 1;
  SystemMetrics metrics = 2;
}

message ServiceState {
  string name = 1;
  enum Status { UNKNOWN = 0; RUNNING = 1; STOPPED = 2; FAILED = 3; STARTING = 4; STOPPING = 5; }
  Status status = 2;
  int32 pid = 3;
  int64 uptime_seconds = 4;
  string last_error = 5;
}

message ServiceName { string name = 1; }

message Ack { bool ok = 1; string message = 2; }

message HardwareInfo {
  CpuInfo cpu = 1;
  MemoryInfo memory = 2;
  GpuInfo gpu = 3;
  AudioInfo audio = 4;
  DisplayInfo display = 5;
}

message KioskRequest { bool enable = 1; }
```

### 6.3 Unity WebSocket（Layer 1 ↔ Layer 2）

見 `unity/Assets/Scripts/HermesBridgeClient.cs` 註解，訊息格式：

**送出**：

```json
{ "type": "chat", "message": "...", "user_id": "...", "personality": "..." }
{ "type": "ping" }
```

**接收**：

```json
{ "type": "response", "text": "...", "emotion": "happy", "intensity": 0.8,
  "live2d": { "expression_id": "F02", ... }, "session_id": "..." }
{ "type": "error", "detail": "..." }
{ "type": "pong" }
```

### 6.4 設定檔契約

**Python bridge 設定** (`bridge/.env`)：

```bash
BRIDGE_HOST=127.0.0.1
BRIDGE_PORT=8001
BRIDGE_LOG_LEVEL=INFO
HERMES_BIN_PATH=~/.local/bin/hermes
HERMES_TIMEOUT=60
```

**Rust runtime 設定** (`/etc/siro/runtime.toml`)：

```toml
[server]
grpc_port = 50051
unix_socket = "/var/run/siro/runtime.sock"

[supervisor]
check_interval_ms = 1000
max_restart_attempts = 5
restart_backoff_ms = 2000

[hardware]
audio_device = "default"
camera_device = "/dev/video0"
display = ":0"

[kiosk]
enabled = true
block_keyboard = true
escape_password = "..."
```

---

## 7. 資料流

### 7.1 對話流程（v0 簡化版）

```
[Unity 打字]  →  [WebSocket]  →  [Bridge]  →  [subprocess hermes -p]  →  [LLM]
                                                                              ↓
[Unity 表情]  ←  [WebSocket]  ←  [Bridge]  ←  [parse emotion]  ←  [回應文字]
```

### 7.2 系統管理流程（v1+）

```
[siro-ctl status]  →  [gRPC]  →  [siro-runtime]  →  [supervisor 查 PID]  →  [回報]
                                                                          ↓
[終端顯示]  ←  [gRPC]  ←  [siro-runtime]  ←  [ServiceState 結構]
```

### 7.3 硬體監控流程

```
[siro-runtime 啟動時]  →  [硬體偵測]  →  [cpu/mem/gpu/audio/video 模組]  →  [HardwareInfo]
                                                                              ↓
[Health Check API]  ←  [gRPC GetHardwareInfo]  ←  [siro-runtime]
```

---

## 8. 風險登記


| #   | 風險                           | 機率 | 影響 | 緩解                                                                |
| --- | ------------------------------ | ---- | ---- | ------------------------------------------------------------------- |
| R1  | Hermes CLI 介面跟預期不同      | 中   | 高   | agent/notes/hermes_api_surface.md 記錄、subprocess 容易 debug       |
| R2  | NVIDIA 驅動裝不起來            | 中   | 高   | 預先用 Live USB 試裝、文件化備用方案（AMD 顯卡）                    |
| R3  | Rust 學習曲線導致 Phase 3 卡關 | 中   | 中   | 從 supervisor 簡單的部分開始、保留 fallback（用 Python supervisor） |
| R4  | Cubism SDK 授權問題            | 低   | 高   | v0 用 Hiyori（明確可商用）、量產前再查                              |
| R5  | 本地 LLM 推論太慢              | 中   | 中   | 從小模型（7B）開始、量化到 4-bit、評估雲端 fallback                 |
| R6  | Kiosk 模式被使用者破解         | 中   | 中   | 密碼保護的 escape hatch、實體按鈕重啟、BIOS 設定                    |
| R7  | OTA 更新磚機                   | 中   | 高   | A/B partition、原子化更新、rollback 機制                            |
| R8  | 24/7 跑 3 個月後記憶體洩漏     | 中   | 中   | Rust 優勢、定期 watchdog 重啟、stress test                          |
| R9  | 多人多帳號混亂                 | 低   | 中   | v0 單人、之後加 multi-user 設計（保留 user_id 欄位）                |
| R10 | 隱私資料外洩                   | 低   | 高   | 本地處理優先、上傳需明確同意、log 過濾個資                          |

---

## v1+ Roadmap（Phase 2 內 sub-versions）

Phase 2 涵蓋 v0.2 → v0.4+ → **v1.0 → v1.1 → v1.2 → v1.5**（單機單 Mao 階段的細部擴充）。

**Single source of truth**：[docs/AGENT_OS.md](docs/AGENT_OS.md) 的「v1+ Roadmap」段（含 v1.2 SendTask + OnClick 完整規格 — WS message 格式、C# API、task 種類、驗收條件、實作順序）。

各 sub-version 簡述：

| Sub-version | 場景 | 預估時程 |
|---|---|---|
| **v1.0** | Telegram 整合（`bridge/telegram_bot.py`） | 3-5 天 |
| **v1.1** | 排程/cron（`bridge/scheduler.py`） | 2-3 天 |
| **v1.2** | Unity 點 Live2D → task（SendTask + OnClick） | 3 天（**規格見 AGENT_OS.md**） |
| **v1.5** | LLM tool calling（Mao 主動召喚任務） | 1-2 週 |

v0.x 進度（v0.2/v0.3/v0.3.1/v0.4/v0.4+）見「§5.5 v0.x 進度子表」。

---

## 9. 時間軸

```
2026
├── 6月:  Phase 0 (規劃) + Phase 1 開始 (Python bridge)
├── 7月:  Phase 1 完成 + Phase 2 (Live2D 強化)
├── 8月:  Phase 3 開始 (Rust runtime)
├── 9月:  Phase 3 完成 + Phase 4 開始 (Linux 化)
├── 10月: Phase 4 完成 + Phase 5 開始 (硬體)
├── 11月: Phase 5 完成 + Phase 6 開始 (部署)
└── 12月: Phase 6 完成 + v1 發布

2027
├── 1-3月: 2-10 台小型 fleet 試營運
└── 4月+:  看情況決定是否進入 v2 規劃
```

**這是高階時間軸**，實際會依進度調整。重點是**每個 Phase 結束都有一個可 demo 的東西**。

---

## 10. AI 協作開發指南

### 10.1 為什麼這份計畫書對 AI 友善

每個 Phase 都有：

- 明確的目標
- 具體的交付物清單
- 可驗收的條件
- 預估時間
- 風險與緩解

AI 拿到任何一個 Phase 的 spec，可以獨立完成其中的子任務。

### 10.2 怎麼用 AI 開發

**好的委派方式**：

```
「請完成 Phase 1.3: 實作 bridge/emotion_parser.py
- 解析 [emotion:xxx] 標籤
- 7 種情緒映射到 Hiyori expression F01-F06
- 80% 單元測試覆蓋率
- 參考 docs/DECISIONS.md 決策 #007」
```

**不好的委派方式**：

```
「幫我做情緒功能」
```

### 10.3 模組邊界

每個模組應該可以**獨立被 AI 重構**而不影響其他模組：


| 模組                                     | 改了什麼        | 影響範圍                |
| ---------------------------------------- | --------------- | ----------------------- |
| `bridge/hermes_client.py`                | Hermes 通訊方式 | 只有`bridge/main.py` 用 |
| `bridge/emotion_parser.py`               | 情緒解析邏輯    | 只有`bridge/main.py` 用 |
| `os-runtime/crates/siro-supervisor/`     | 進程監控        | 只有`siro-runtime` 用   |
| `unity/Assets/Scripts/EmotionDisplay.cs` | 表情切換邏輯    | 只有 Unity 內部         |

### 10.4 Coding conventions

詳見 [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)。重點：

- **Python**：black + ruff + type hints
- **Rust**：rustfmt + clippy
- **C#**：dotnet format
- **Shell**：shellcheck
- **Commits**：Conventional Commits
- **PR**：每個 PR 對應一個 Phase 內的小任務

### 10.5 測試策略

- **新功能必須帶測試**
- **Bug fix 必須有 regression test**
- **重構必須保持測試綠燈**
- **每個 Phase 結束要更新 E2E 測試**

詳見 [docs/TESTING.md](docs/TESTING.md)。

---

## 11. 變更紀錄


| 日期       | 版本   | 變更                                                                                                                                |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| 2026-06-04 | v3.3   | v1.2 SendTask + OnClick 實作：bridge 端 5 built-in + registry + WS handler + 12 個 test_sendtask.py 測試（210 過/1 skip）；Unity 端 `SendTaskAsync` + `OnTaskResult`/`OnTaskFailed` event + `Live2DModelController.OnMaoClicked` + `PersonaClickHandler`；v0.x 進度子表 v1.2 ✅ |
| 2026-06-04 | v3.2   | v1+ Roadmap 段：加 SendTask + OnClick 完整規格（WS message 格式、C# API、task 種類、驗收條件、實作順序）放 AGENT_OS.md、PLAN.md 引用 |
| 2026-06-04 | v3.1   | v0.4 翻預設：`SIRO_USE_AGENT_OS` 預設從 false 改 true（逃生 `=false`）、v0.x 子表 v0.4 ✅、視覺設定檔 v0.3 ✅、test count 190 → 198 |
| 2026-06-04 | v3.0   | 對齊 v0.3 實況：Phase 0 改 ✅ 完成、Phase 2 改 🟡 進行中（v0.3.1）、Phase 2 加 v0.x 進度子表、test count 78 → 190、加 cross-ref 段 |
| 2026-06-04 | v2.0.x | v0.3 期間的細部修訂（PLAN_REVIEW_v0.3、PLAN_REVISION_v2.1）— 見`docs/PLAN_REVIEW_v0.3.md`                                          |
| 2026-06-02 | v2.0   | 砍掉重寫。加入 Rust OS 層、4 層架構、6 個 Phase、完整文件清單、AI 協作指南                                                          |
| 2026-06-02 | v1.0   | 初版（過度樂觀，文件描述願景而非現實）                                                                                              |
