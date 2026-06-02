# SIRO

> **Live2D AI Agent 專屬作業系統** — 透過 Hermes Agent 驅動的 Live2D 陪伴裝置。
> v2.0（2026-06-02）— 加入 Rust 系統層、4 層架構、6 個 Phase 完整規劃。

---

## 願景

開機即見 Live2D 角色，所有互動透過角色，沒有傳統桌面。
AI 本身就是 OS 的 shell，不是「在 OS 上跑 AI 應用」。

```
[開機]
  ↓ (< 30 秒)
[Live2D 角色出現，問候使用者]
  ↓
[使用者用文字 / 語音 / 眼神與角色互動]
  ↓
[角色理解意圖，調用工具、執行動作、回應]
```

---

## 4 層架構

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Presentation (C# Unity)                           │
│  └─ unity/                                                   │
└─────────────────────────────────────────────────────────────┘
            ↕ WebSocket
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: AI Bridge (Python)                                │
│  └─ bridge/                                                  │
└─────────────────────────────────────────────────────────────┘
            ↕ gRPC
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: System Runtime (Rust)                             │
│  └─ os-runtime/                                              │
└─────────────────────────────────────────────────────────────┘
            ↕ systemd
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: System (Linux)                                    │
│  └─ os/                                                      │
└─────────────────────────────────────────────────────────────┘
```

詳細架構見 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 開發階段

| Phase | 重點 | 狀態 |
|-------|------|------|
| **Phase 0** | 規劃設計、建立結構 | 進行中 |
| **Phase 1** | Python AI 整合（Hermes + bridge + 文字對話 + Live2D 表情） | 待開始 |
| **Phase 2** | Live2D 視覺強化（待機動作、表情過渡） | 待開始 |
| **Phase 3** | Rust 系統層（supervisor、gRPC、硬體抽象） | 待開始 |
| **Phase 4** | Linux 客製化（Ubuntu Server 24.04 LTS 雙系統） | 待開始 |
| **Phase 5** | 硬體整合（音訊、視訊、kiosk 模式） | 待開始 |
| **Phase 6** | 部署與營運（Packer image、OTA、備份） | 待開始 |

完整規劃見 [LIVE2D_AI_AGENT_OS_PLAN.md](LIVE2D_AI_AGENT_OS_PLAN.md)。

---

## 專案結構

```
SIRO/
├── agent/                # Hermes CLI 整合（shell + 設定）
├── bridge/               # Python FastAPI（Layer 2）
├── os-runtime/           # Rust 系統層（Layer 3）
├── unity/                # C# Unity 客戶端（Layer 1）
├── os/                   # Linux 系統設定（Layer 4）
├── hardware/             # 硬體規格、偵測、改裝
├── docs/                 # 完整文件
├── scripts/              # 跨模組腳本
├── .env.example          # 環境變數範本
├── LICENSE               # MIT
└── README.md             # 本檔
```

---

## 從零開始

完整步驟見 [docs/SETUP.md](docs/SETUP.md)。

### 簡要流程

1. **安裝 Hermes Agent**
   ```bash
   bash agent/install.sh
   bash agent/verify.sh
   ```

2. **設定 LLM**（推薦用本地 Ollama，已有）
   ```bash
   ollama pull llama3.2:3b-instruct-q4_0
   ```

3. **啟動 Bridge**
   ```bash
   cd bridge
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m bridge.main
   ```

4. **建置並測試 Rust 系統層**（Phase 3 開始才需要）
   ```bash
   cd os-runtime
   cargo build
   cargo test
   ```

5. **開啟 Unity 客戶端**
   - Unity Hub 開新專案
   - 套 `unity/Packages/manifest.json`
   - 裝 Cubism SDK + Hiyori 模型
   - 複製 `unity/Assets/Scripts/*.cs`
   - Play 模式測試

---

## 開發硬體

**目前使用**：ASUS ROG Strix G713QC
- CPU: AMD Ryzen 9 5900HX (8C/16T)
- RAM: 16GB
- GPU: NVIDIA RTX 3050 4GB VRAM
- 限制：本機 LLM 只能跑 3B Q4，7B+ 要走雲端

詳細硬體分析見 [hardware/README.md](hardware/README.md)。

---

## 模組速覽

| 模組 | 語言 | 用途 | 文件 |
|------|------|------|------|
| `agent/` | Shell | Hermes CLI 安裝、驗證 | [agent/README.md](agent/README.md) |
| `bridge/` | Python | FastAPI 服務，串接 Hermes 與 Unity | [bridge/README.md](bridge/README.md) |
| `os-runtime/` | Rust | 系統 daemon，硬體抽象、supervisor | [os-runtime/README.md](os-runtime/README.md) |
| `unity/` | C# | Live2D 客戶端 | [unity/README.md](unity/README.md) |
| `os/` | Shell | Linux 系統設定（kiosk、systemd、安全） | [os/README.md](os/README.md) |
| `hardware/` | Markdown | 硬體規格、相容性、改裝 | [hardware/README.md](hardware/README.md) |
| `docs/` | Markdown | 架構、API、安全、測試、決策 | [docs/](docs/) |

---

## 文件地圖

| 文件 | 用途 |
|------|------|
| [LIVE2D_AI_AGENT_OS_PLAN.md](LIVE2D_AI_AGENT_OS_PLAN.md) | **主計畫書** — 願景、6 個 Phase、技術堆疊 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統架構、模組職責、介面契約 |
| [docs/SETUP.md](docs/SETUP.md) | 從零到能跑的步驟 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 設計決策紀錄（20+ ADR） |
| [docs/API.md](docs/API.md) | API 契約（HTTP、gRPC、WebSocket） |
| [docs/SECURITY.md](docs/SECURITY.md) | 安全性設計 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 部署 SOP |
| [docs/TESTING.md](docs/TESTING.md) | 測試策略 |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | 開發指南（給 AI 助手） |

---

## 為什麼 Python + Rust

| 層 | 語言 | 理由 |
|----|------|------|
| AI 整合 | **Python** | LLM SDK 成熟、開發快、迭代快 |
| 系統服務 | **Rust** | 24/7 穩定、零 runtime、記憶體安全 |
| 視覺呈現 | C# (Unity) | Live2D SDK 最完整支援 |

詳細分析見 [docs/DECISIONS.md#011](docs/DECISIONS.md)。

---

## 當前進度

- ✅ 規劃設計（Phase 0）
- ⏳ Phase 1 準備開始
- ❌ Phase 2-6 待規劃

---

## 授權

MIT — 見 [LICENSE](LICENSE)。
