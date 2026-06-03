# SIRO - Live2D AI Agent 專屬作業系統

## 完整開發計畫書

> **版本**：v2.0（2026-06-02 重構）
> **目標讀者**：本計畫書是給**人類與 AI 協作開發**用的規格文件，每個 Phase 都有明確的交付物、驗收條件、可委派的工作項目。
> **狀態**：Phase 0 進行中、**Phase 1 ✅ 完成**（2026-06-03 含 Unity Play 實測），其餘為規劃

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

| # | 原則 | 違反的後果 |
|---|------|------------|
| 1 | **Python for AI, Rust for system** | 混亂的語言選型、技術債 |
| 2 | **Skeleton before features** | 過早最佳化、做出不能跑的東西 |
| 3 | **Real over aspirational** | 文件與現實脫節、無法 demo |
| 4 | **Reversible over complete** | 一旦選了就回不去的決策 |
| 5 | **AI-actionable specs** | 文件看不懂、無法委派 |

### 2.1 為什麼 Python + Rust

| 考量 | Python | Rust | 結論 |
|------|--------|------|------|
| LLM SDK 成熟度 | 極佳 | 弱 | **Python 勝** |
| 開發速度 | 快 | 慢 | **Python 勝** |
| 啟動時間 | 1-3 秒 | 10-50ms | **Rust 勝** |
| 記憶體佔用 | 100MB+ | 5-20MB | **Rust 勝** |
| 套件依賴 | 重（venv、pip） | 零 | **Rust 勝** |
| 系統呼叫 | 不便 | 直接 | **Rust 勝** |
| 24/7 穩定度 | 需注意 | 強 | **Rust 勝** |
| AI 工具 | 極佳 | 普通 | **Python 勝** |

**結論**：Python 做 AI 邏輯（變動多、迭代快），Rust 做系統服務（要求穩、要求快）。

### 2.2 語言邊界

| 層 | 語言 | 為什麼 |
|----|------|--------|
| AI 整合（bridge/） | Python | LLM SDK、Hermes 整合、快速迭代 |
| 系統服務（os-runtime/） | Rust | 24/7 穩定、零 runtime、硬體控制 |
| 前端呈現（unity/） | C# | Live2D SDK、Unity 生態 |
| 系統設定（os/） | Shell + systemd | Linux 原生 |
| 工具腳本（scripts/） | Shell + Python + Rust | 依用途 |

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

| 模組 | 語言 | 啟動順序 | 通訊對象 | 失敗處理 |
|------|------|----------|----------|----------|
| `os-runtime/siro-runtime` | Rust | 第一個（systemd） | systemd、bridge、硬體 | watchdog 自動重啟 |
| `agent/` (Hermes CLI) | Python | 第二個 | LLM Provider | subprocess 錯誤回傳給 bridge |
| `bridge/main.py` | Python | 第三個 | hermes、unity、os-runtime | FastAPI 健康檢查 |
| `unity/` (Unity build) | C# | 第四個 | bridge | 重連機制 |

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

| 元件 | 技術 | 理由 |
|------|------|------|
| 引擎 | Unity 6 LTS | Live2D SDK 最完整支援 |
| Live2D | Cubism SDK for Unity | 官方 SDK，expression/motion 完整 |
| WebSocket | `System.Net.WebSockets` | 內建，無需外部套件 |
| JSON | `Newtonsoft.Json` | 內建套件 |
| UI | UGUI + TextMeshPro | 標準 |
| 模型 | Hiyori (Cubism 官方) | 免費可商用 |

### 4.2 Layer 2: AI Bridge (Python)

| 元件 | 技術 | 理由 |
|------|------|------|
| 框架 | FastAPI + uvicorn | 簡單、async 原生、文件佳 |
| WebSocket | FastAPI 內建 | 與 HTTP 同源 |
| LLM 整合 | Hermes Agent CLI (subprocess) | 不用自接 API key 管理 |
| 環境管理 | uv | 跟 Hermes 一致、快 |
| Schema | Pydantic v2 | 強型別、自動驗證 |
| 測試 | pytest + httpx | 標準 |
| 套件管理 | `bridge/requirements.txt` | 簡單 |

**Python 版本**：3.11+（與 Hermes 一致）

### 4.3 Layer 3: System Runtime (Rust)

| 元件 | 技術 | 理由 |
|------|------|------|
| Runtime | tokio | 標準 async 執行緒 |
| HTTP/gRPC | tonic (gRPC) + axum (HTTP) | 業界標準 |
| CLI | clap | 主流 CLI 框架 |
| Systemd | sd-notify + zbus | 原生整合 |
| Config | figment + TOML | 多層 config 來源 |
| Logging | tracing | 結構化日誌 |
| Error | thiserror + anyhow | 慣用模式 |
| Audio | cpal + rubato | 跨平台音訊 |
| Display | winit + wgpu | 視窗管理 |
| Camera | v4l2 (Linux) / mediafoundation (Windows) | 跨平台 |
| GPU | cuda-rs (未來) | 本地 LLM 推論 |
| Build | cargo + cross | 跨編譯 |

**Rust 版本**：1.80+ stable
**目標平台**：`x86_64-unknown-linux-gnu` (Ubuntu)

### 4.4 Layer 4: System (Linux)

| 元件 | 技術 | 理由 |
|------|------|------|
| 發行版 | Ubuntu Server 24.04 LTS | 5 年支援、套件齊、文件多 |
| Init | systemd | Ubuntu 預設 |
| 桌面 | **無**（kiosk 全螢幕） | 設計目標 |
| Display | X11 + openbox (v0.5) → Wayland + Cage (v1) | 從熟悉到現代 |
| 安全 | AppArmor + ufw | 標準 Ubuntu 工具 |
| 套件 | apt | 標準 |
| 監控 | systemd journal + promtail | 標準 |

### 4.5 開發工具

| 用途 | 工具 |
|------|------|
| 版本控制 | git + GitHub |
| Editor | VS Code / Cursor |
| AI 助手 | Claude Code（本倉庫就是用 AI 寫的） |
| CI/CD | GitHub Actions |
| Issue tracking | GitHub Issues |
| 文件 | Markdown (本倉庫) |
| 圖表 | Mermaid（在 Markdown 內） |
| API 文件 | OpenAPI 自動生成（FastAPI） |

---

## 5. 階段規劃

### Phase 0: 規劃與環境建立 ✅ 進行中

**目標**：完成架構設計、建立 monorepo 結構、定下所有技術選型

**交付物**：
- [x] 主計畫書（本檔）
- [ ] `docs/ARCHITECTURE.md`（介面契約、資料流）
- [ ] `docs/DECISIONS.md`（所有重大決策 ADR）
- [ ] `os-runtime/` Rust workspace scaffold
- [ ] `os/` Linux 設定目錄結構
- [ ] `hardware/` 硬體規格文件
- [ ] `docs/SECURITY.md`
- [ ] `docs/DEPLOYMENT.md`
- [ ] `docs/API.md`
- [ ] `docs/TESTING.md`
- [ ] `docs/CONTRIBUTING.md`
- [ ] `scripts/dev/` 開發輔助腳本

**驗收條件**：
- 所有文件互引一致
- `os-runtime/` 可以 `cargo build` 通過
- `bridge/` 可以 `python -m bridge.main` 啟動

**預估時間**：1-2 週（剩餘）
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
- [x] `bridge/` 完整實作
- [x] `bridge/tests/` **93% 覆蓋率（78 active tests, 0 fail）**
- [x] `unity/Assets/Scripts/` 完整實作（含 WebSocket 自動重連 + 指數 backoff）
- [x] `agent/install.sh` 跑通（自動 fallback 到 clone+uv 模式）
- [x] `agent/verify.sh` 跑通（5/5 通過）
- [x] `docs/SETUP.md` 從零到能跑的完整步驟
- [x] `bridge/runtime_client.py` Layer 3 gRPC client stub
- [x] Hermes Agent 實際安裝：v0.15.1，clone+uv 模式
- [x] LLM 設定：Ollama + llama3.2:3b-instruct-q4_0（128K context）
- [x] **E2E 驗證**：bridge → Hermes → Ollama → 回應「HELLO!」
- [x] Unity Play 模式實機測試（✓ 實測，2026-06-03，使用 Mao 模型 9 種情緒對應 8 個 expression）

**驗收條件**：
- [x] `bash agent/install.sh` 自動偵測+安裝（✓ 實測）
- [x] `bash agent/verify.sh` 5/5 通過（✓ 實測，2026-06-02）
- [x] `python -m bridge.main` 啟動無錯誤（✓ 實測）
- [x] `curl localhost:8001/health` 回 200 with `hermes_available: true`（✓ 實測）
- [x] `curl localhost:8001/chat` 拿到含 LLM 回應（✓ 實測，回 "HELLO!"）
- [x] `python -m pytest bridge/tests/ -v` 全綠（✓ 78/78 pass）
- [x] 覆蓋率 ≥ 80%（✓ 92%）
- [x] Unity Play 模式能跟 Mao 打字對話（✓ 實測，2026-06-03，9 情緒切換 + 中文 + 眼球 hack）

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
- 🟡 Unity + Cubism SDK 還沒實機測過（需手動）

---

### Phase 2: 視覺呈現強化 (Unity + Live2D)

**目標**：完善 Live2D 互動體驗，加上視覺效果

**範圍**：
- 表情平滑過渡
- 待機動作（呼吸、眨眼）
- 點擊互動
- Loading 狀態視覺
- 多個 Hiyori 動作（idle, tap head, tap body）

**交付物**：
- [ ] `Live2DModelController` 支援 motion 播放
- [ ] `EmotionDisplay` 支援表情過渡動畫
- [ ] 待機動作自動 loop
- [ ] 視覺設定檔（亮度、縮放）
- [ ] 截圖功能（debug 用）

**驗收條件**：
- [ ] 角色不說話時有自然的待機動作
- [ ] 表情切換有 0.3-0.5s 平滑過渡
- [ ] 切換時不閃爍、不穿幫
- [ ] 點擊角色有反饋

**預估時間**：1-2 週
**依賴**：Phase 1
**風險**：
- 🟡 Cubism SDK 的 motion 觸發需要 Animator 設定（要 Unity Editor 手動）
- 🟢 視覺效果問題可以延後處理

---

### Phase 3: Rust 系統層

**目標**：建立 Rust 系統 daemon，提供 OS 級服務管理

**範圍**：
- `siro-runtime` daemon
- 監控 bridge、hermes、unity 進程
- 崩潰自動重啟
- 與 bridge 的 gRPC IPC
- 硬體抽象（音訊、視訊、顯示）
- 設定管理
- Logging

**交付物**：
- [ ] `os-runtime/Cargo.toml` workspace
- [ ] `os-runtime/crates/siro-runtime/` 主 daemon
- [ ] `os-runtime/crates/siro-ctl/` CLI 工具
- [ ] `os-runtime/crates/siro-ipc/` IPC protocol 定義
- [ ] gRPC proto 檔（與 bridge 共用）
- [ ] 進程 supervisor
- [ ] 硬體偵測
- [ ] 設定檔讀寫
- [ ] `os-runtime/tests/` 80% 覆蓋率
- [ ] `os-runtime/README.md` 開發指南

**驗收條件**：
- [ ] `siro-runtime` 可以 `cargo build --release` 通過
- [ ] `siro-ctl status` 顯示所有服務狀態
- [ ] kill bridge 進程後自動重啟
- [ ] gRPC 介面與 bridge 對接測試通過
- [ ] 記憶體常駐 < 30MB

**預估時間**：3-4 週
**依賴**：Phase 1（bridge 要先有 API 介面）
**風險**：
- 🔴 Rust 學習曲線（第一次寫可能踩坑多）
- 🟡 gRPC proto 跨語言相容性
- 🟢 進程 supervisor 是常見 pattern，風險低

---

### Phase 4: Linux 客製化

**目標**：把現在的 Windows 開發機改成 Ubuntu Server 24.04 LTS 雙系統（或全替換）

**範圍**：
- Ubuntu Server 24.04 LTS 安裝
- NVIDIA 驅動 + CUDA 工具鏈
- 唯讀 rootfs
- systemd 服務整合
- 安全政策（AppArmor、ufw）
- Kiosk 模式（X11 + openbox）
- 自動登入 + 開機啟動

**交付物**：
- [ ] `os/install/` 自動安裝腳本
- [ ] `os/systemd/*.service` 服務定義
- [ ] `os/kiosk/` X11 / openbox 設定
- [ ] `os/security/` AppArmor profiles
- [ ] `os/network/` ufw rules
- [ ] `os/README.md` 安裝步驟
- [ ] 開機到 Live2D 角色出現 < 30 秒
- [ ] 24/7 穩定度測試（72 小時不當機）

**驗收條件**：
- [ ] 開機自動進入 kiosk，無手動操作
- [ ] 切換 Windows ↔ Linux 雙系統正常
- [ ] NVIDIA GPU CUDA 跑本地 LLM 推論 < 5 秒回應
- [ ] 重啟 10 次都正常
- [ ] 跑 72 小時不 crash
- [ ] 硬碟壞一個 sector 不影響運作（用 RAID 或定期備份）

**預估時間**：2-3 週
**依賴**：Phase 3（Rust 服務要先有）
**風險**：
- 🔴 NVIDIA 驅動安裝可能有相容性問題
- 🔴 雙系統 / 完整替換要決策
- 🟡 Kiosk 模式有眉角（keybind 鎖定、escape hatch）
- 🟡 systemd 服務啟動順序要 tune

---

### Phase 5: 硬體整合

**目標**：把系統打包到實際的硬體配置上

**範圍**：
- 音訊設定（內建麥克風、外接 USB 麥克風陣列）
- 視訊設定（內建視訊、外接 USB 視訊）
- 觸控螢幕支援（選配）
- 鍵盤滑鼠封鎖（kiosk 安全）
- 電源管理
- 散熱管理
- 實體按鈕（選配：重啟、靜音）

**交付物**：
- [ ] `hardware/specs.md` 推薦硬體清單
- [ ] `hardware/audio.md` 音訊設定
- [ ] `hardware/camera.md` 視訊設定
- [ ] `hardware/assembly.md` 組裝指南（如果是改裝筆電）
- [ ] `os/audio/` ALSA / PulseAudio 設定
- [ ] `os/video/` V4L2 設定
- [ ] `os/power/` power management
- [ ] 熱監控 + 風扇控制

**驗收條件**：
- [ ] 麥克風收音清楚、距離 1 米可辨識
- [ ] 攝影機人臉偵測可抓到 1-3 米距離
- [ ] 觸控螢幕點擊準確（如果有的話）
- [ ] 鍵盤訊號被鎖（kiosk 模式生效）
- [ ] 散熱穩定，CPU 溫度 < 80°C
- [ ] 電源中斷恢復自動開機

**預估時間**：1-2 週
**依賴**：Phase 4
**風險**：
- 🟡 不同硬體相容性差異大
- 🟢 大部分是設定工作，風險可控

---

### Phase 6: 部署與營運

**目標**：可以快速複製到 2-10 台裝置、支援 OTA 更新

**範圍**：
- 系統映像檔建立（Packer）
- 設定檔管理（每台裝置不同）
- OTA 更新機制
- 遙測（log 集中、健康檢查）
- 備份 / 還原
- 監控與警報

**交付物**：
- [ ] `scripts/build-image.sh` Packer 腳本
- [ ] `scripts/ota-update.sh` OTA 工具
- [ ] `os/config-template/` 每台裝置的 config 範本
- [ ] `os/backup/` 備份腳本
- [ ] `os/monitoring/` 健康檢查 + 警報
- [ ] `docs/DEPLOYMENT.md` 部署 SOP
- [ ] `docs/OPERATIONS.md` 營運手冊
- [ ] 第一台以外的測試（朋友 / 家人）

**驗收條件**：
- [ ] 從 0 到完成部屬一台裝置 < 30 分鐘
- [ ] OTA 更新一輪 < 10 分鐘、不中斷服務
- [ ] 設定一台裝置只需要改一個 config 檔
- [ ] log 集中可查詢
- [ ] 硬碟故障可在 10 分鐘內還原

**預估時間**：2-3 週
**依賴**：Phase 4 + 5
**風險**：
- 🟡 OTA 安全（要 code signing、避免磚機）
- 🟢 Packer 與 systemd 相容性 OK
- 🟢 小規模 fleet 不需要複雜管理工具

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

| # | 風險 | 機率 | 影響 | 緩解 |
|---|------|------|------|------|
| R1 | Hermes CLI 介面跟預期不同 | 中 | 高 | agent/notes/hermes_api_surface.md 記錄、subprocess 容易 debug |
| R2 | NVIDIA 驅動裝不起來 | 中 | 高 | 預先用 Live USB 試裝、文件化備用方案（AMD 顯卡） |
| R3 | Rust 學習曲線導致 Phase 3 卡關 | 中 | 中 | 從 supervisor 簡單的部分開始、保留 fallback（用 Python supervisor） |
| R4 | Cubism SDK 授權問題 | 低 | 高 | v0 用 Hiyori（明確可商用）、量產前再查 |
| R5 | 本地 LLM 推論太慢 | 中 | 中 | 從小模型（7B）開始、量化到 4-bit、評估雲端 fallback |
| R6 | Kiosk 模式被使用者破解 | 中 | 中 | 密碼保護的 escape hatch、實體按鈕重啟、BIOS 設定 |
| R7 | OTA 更新磚機 | 中 | 高 | A/B partition、原子化更新、rollback 機制 |
| R8 | 24/7 跑 3 個月後記憶體洩漏 | 中 | 中 | Rust 優勢、定期 watchdog 重啟、stress test |
| R9 | 多人多帳號混亂 | 低 | 中 | v0 單人、之後加 multi-user 設計（保留 user_id 欄位） |
| R10 | 隱私資料外洩 | 低 | 高 | 本地處理優先、上傳需明確同意、log 過濾個資 |

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

| 模組 | 改了什麼 | 影響範圍 |
|------|----------|----------|
| `bridge/hermes_client.py` | Hermes 通訊方式 | 只有 `bridge/main.py` 用 |
| `bridge/emotion_parser.py` | 情緒解析邏輯 | 只有 `bridge/main.py` 用 |
| `os-runtime/crates/siro-supervisor/` | 進程監控 | 只有 `siro-runtime` 用 |
| `unity/Assets/Scripts/EmotionDisplay.cs` | 表情切換邏輯 | 只有 Unity 內部 |

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

| 日期 | 版本 | 變更 |
|------|------|------|
| 2026-06-02 | v2.0 | 砍掉重寫。加入 Rust OS 層、4 層架構、6 個 Phase、完整文件清單、AI 協作指南 |
| 2026-06-02 | v1.0 | 初版（過度樂觀，文件描述願景而非現實） |
