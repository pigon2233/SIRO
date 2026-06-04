# SIRO 系統架構

> **目前進度 v0.3**（2026-06-04）— Layer 1（Unity）+ Layer 2（Python）已實作，Layer 3（Rust）+ Layer 4（Linux）規劃中
> **終極願景 v2.0** — 4 層架構：Linux + Rust + Python + Unity
> 完整計畫見 [../LIVE2D_AI_AGENT_OS_PLAN.md](../LIVE2D_AI_AGENT_OS_PLAN.md)
> 介面契約見 [API.md](API.md)
> 設計決策見 [DECISIONS.md](DECISIONS.md)

### v0.3 範圍對照

| 層 | 內容 | v0.3 狀態 |
|---|------|-----------|
| Layer 1: Presentation (Unity) | Mao Live2D + Chat UI + Persona + i18n | ✅ 完成（Play 模式實測） |
| Layer 2: AI Bridge (Python) | FastAPI + Hermes + EmotionParser + AgentOS（骨架 v0.2 / 接到 /chat v0.3 opt-in）| ✅ 完成 |
| Layer 3: System Runtime (Rust) | siro-runtime daemon + supervisor | ⏳ v0.3 不做、Phase 3+ |
| Layer 4: System (Linux) | Ubuntu + systemd + kiosk + NVIDIA | ⏳ v0.3 不做、Phase 4 |

---

## 1. 高階架構

### 1.1 4 層架構

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Presentation (C# Unity)                           │
│  ├─ Live2D 渲染                                              │
│  ├─ 表情 / 動作驅動                                            │
│  ├─ 文字 / 語音輸入（v0 文字，v0.5 語音）                       │
│  └─ WebSocket Client → Layer 2                              │
└─────────────────────────────────────────────────────────────┘
            ↕ WebSocket (port 8001)
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: AI Bridge (Python)                                │
│  ├─ FastAPI HTTP / WebSocket                                 │
│  ├─ Hermes Agent 整合（subprocess）                            │
│  ├─ Ollama 本地 LLM（已整合，當 fallback）                      │
│  ├─ 情緒解析、session 管理、jieba 斷詞                          │
│  ├─ AgentOS（v0.3 進度）：Task Queue + Event Bus + Worker Pool│
│  │     + Task.id + wait_for_task() — /chat opt-in 走這條     │
│  └─ gRPC Client → Layer 3（Phase 3+ 才接，現階段走 subprocess）│
└─────────────────────────────────────────────────────────────┘
            ↕ gRPC (port 50051) / Unix socket
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: System Runtime (Rust)                             │
│  ├─ siro-runtime: 主 daemon                                   │
│  ├─ siro-ctl: CLI 工具                                       │
│  ├─ 進程 supervisor（bridge、hermes、unity）                    │
│  ├─ 硬體抽象（音訊、視訊、顯示、GPU）                             │
│  ├─ Kiosk 模式控制                                            │
│  └─ 設定管理                                                  │
└─────────────────────────────────────────────────────────────┘
            ↕ systemd / syscalls / /dev/*
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: System (Linux)                                    │
│  ├─ Ubuntu Server 24.04 LTS                                  │
│  ├─ systemd 服務                                             │
│  ├─ X11 / Wayland kiosk session                              │
│  ├─ NVIDIA 驅動 + CUDA                                       │
│  └─ AppArmor + ufw 安全                                      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 啟動順序

```
[BIOS / UEFI]
    ↓
[systemd (PID 1)]
    ↓
[siro-runtime.service] (Layer 3)   ← 第一個 user-space 服務
    ↓ (啟動並監控)
[hermes.service] (background)
    ↓
[siro-bridge.service] (Layer 2)    ← 等 siro-runtime 就緒
    ↓
[siro-unity.service] (Layer 1)     ← 等 siro-bridge 健康
    ↓
[Live2D 角色出現]
```

`siro-runtime` 啟動其他服務並監控，崩潰自動重啟。

### 1.3 失敗處理

| 失敗 | 誰處理 | 怎麼處理 |
|------|--------|----------|
| LLM API timeout | bridge | 5 秒 timeout，回傳錯誤給 Unity |
| bridge crash | siro-runtime | 自動重啟，最多 5 次，5 次後 halt |
| unity crash | siro-runtime | 自動重啟（kiosk 模式必須有 UI） |
| hermes CLI not responding | bridge | kill subprocess，回傳錯誤 |
| siro-runtime crash | systemd | systemd 重啟（最嚴重） |
| 硬體故障 | siro-runtime | 偵測到後降級模式（如無 GPU 用 CPU 推論） |
| 磁碟滿 | siro-runtime | log rotation、清理 cache、警報 |

---

## 2. 模組詳解

### 2.1 Layer 1: Presentation (Unity)

```
unity/
├── Assets/
│   ├── Models/                  # Live2D 模型（Hiyori，不 commit）
│   ├── Scenes/
│   │   └── MainScene.unity      # 主要場景
│   ├── Scripts/
│   │   ├── HermesBridgeClient.cs   # WebSocket client
│   │   ├── Live2DModelController.cs # Cubism 模型控制
│   │   ├── EmotionDisplay.cs        # 情緒 → 表情
│   │   ├── ChatInputUI.cs           # 文字輸入 UI
│   │   └── (v0.5+) AudioInputManager.cs # 語音輸入
│   └── UI/                      # Canvas prefabs
├── Packages/manifest.json
└── README.md
```

**職責**：
- 顯示 Live2D 模型
- 接收使用者輸入（v0 文字、v0.5 語音）
- 顯示回應文字
- 切換表情 / 動作

**依賴**：
- Cubism SDK for Unity
- `com.unity.nuget.newtonsoft-json`
- TextMeshPro

**對外介面**：
- WebSocket client（連 Layer 2）

**失敗模式**：
- WebSocket 斷線：嘗試重連（v1+），v0 顯示錯誤
- 表情 ID 找不到：fallback 到 F01 (default)

---

### 2.2 Layer 2: AI Bridge (Python)

```
bridge/
├── main.py                      # FastAPI 入口（含 /chat /ws /personas）
├── hermes_client.py             # Hermes CLI 封裝
├── ollama_client.py             # Ollama 本地 LLM（fallback）
├── agent_os.py                  # v0.3 AgentOS — Task Queue + Event Bus + Worker Pool
│                                # + Task.id + wait_for_task() + EventBus unsubscribe
├── tasks/                       # v0.3 任務模組
│   ├── __init__.py
│   └── llm_reply_task.py        # 第一個 task（封裝 /chat LLM 邏輯）
├── emotion_parser.py            # 情緒解析
├── emotion_mapping.json         # 情緒 → Live2D 映射
├── prompts.py                   # System prompts
├── models.py                    # Pydantic schemas
├── personas/                    # YAML persona 設定
├── grpc_client/                 # Layer 3 介接（Phase 3+ 才用，v0.3 走 subprocess）
│   ├── __init__.py
│   ├── client.py                # gRPC client wrapper
│   └── generated/               # protoc 產生的程式碼
├── tests/
└── requirements.txt
```

**職責**：
- 對 Unity 暴露 HTTP/WS API
- 對 LLM / Hermes / Ollama 暴露文字介面
- 情緒解析、session 管理、jieba 斷詞
- **v0.3 新增**：AgentOS 後台作業系統 — 接管 /chat 走 task queue + event bus（opt-in via `SIRO_USE_AGENT_OS`）
- 設定管理

**對外介面**：
- HTTP/WS：8001 port（v0.3 已有）
- gRPC：50051 port（**Phase 3+**才接 Layer 3，v0.3 不開）

**啟動**：
```bash
cd bridge
source .venv/bin/activate
python -m bridge.main
# v0.3 額外環境變數：
SIRO_USE_AGENT_OS=true python -m bridge.main   # /chat opt-in 走 AgentOS
```

---

### 2.3 Layer 3: System Runtime (Rust)

```
os-runtime/
├── Cargo.toml                   # Workspace
├── README.md
├── proto/
│   └── siro.proto               # gRPC 介面定義（與 bridge 共用）
├── crates/
│   ├── siro-ipc/                # gRPC types 與 generated code
│   ├── siro-runtime/            # 主 daemon
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── supervisor.rs    # 進程管理
│   │   │   ├── config.rs
│   │   │   ├── logging.rs
│   │   │   └── hardware/
│   │   │       ├── cpu.rs
│   │   │       ├── memory.rs
│   │   │       ├── gpu.rs
│   │   │       ├── audio.rs
│   │   │       └── display.rs
│   │   └── tests/
│   ├── siro-ctl/                # CLI 工具
│   │   ├── src/
│   │   │   └── main.rs
│   │   └── tests/
│   └── siro-kiosk/              # Kiosk 模式控制
│       ├── src/
│       │   ├── lib.rs
│       │   ├── x11.rs
│       │   ├── wayland.rs
│       │   └── input_block.rs
│       └── tests/
└── tests/                       # E2E 整合測試
```

**職責**：
- 監控並重啟 Layer 1、2 的服務
- 提供硬體抽象（CPU/GPU/音訊/視訊/顯示）
- 控制 Kiosk 模式
- 設定管理
- 集中 logging

**對外介面**：
- gRPC server（50051 port）
- Unix socket（`/var/run/siro/runtime.sock`）
- systemd `sd_notify` 整合

**依賴**：
- `tokio` (async runtime)
- `tonic` (gRPC)
- `axum` (HTTP 健康檢查)
- `clap` (CLI)
- `zbus` (D-Bus / systemd)
- `tracing` (logging)
- `cpal` (音訊)
- `v4l2` (視訊)
- `winit` + `wgpu` (顯示，v0.5+)

**資源需求**：
- 記憶體常駐 < 30MB
- CPU idle < 1%
- 啟動時間 < 500ms

---

### 2.4 Layer 4: System (Linux)

```
os/
├── README.md
├── install/                     # 安裝腳本
│   ├── 00-base.sh               # 基本系統設定
│   ├── 10-nvidia.sh             # NVIDIA 驅動 + CUDA
│   ├── 20-siro-user.sh          # 建 siro 使用者
│   ├── 30-siro-runtime.sh       # 編譯安裝 siro-runtime
│   ├── 40-bridge.sh             # 安裝 bridge 依賴
│   ├── 50-unity.sh              # 部署 Unity build
│   ├── 60-kiosk.sh              # Kiosk 模式
│   ├── 70-security.sh           # AppArmor + ufw
│   └── 99-verify.sh             # 驗證全部安裝
├── systemd/
│   ├── siro-runtime.service
│   ├── hermes.service
│   ├── siro-bridge.service
│   └── siro-unity.service
├── kiosk/
│   ├── x11/
│   │   ├── xorg.conf
│   │   └── openbox/
│   │       ├── autostart
│   │       └── rc.xml
│   ├── wayland/                 # v1+
│   │   └── cage-config.toml
│   └── input-block/
│       └── block-input.sh       # 鎖鍵盤滑鼠，保留觸控
├── security/
│   ├── apparmor/
│   │   ├── siro-bridge
│   │   └── siro-runtime
│   ├── ufw/
│   │   └── rules.sh
│   └── ssh/
│       └── sshd_config.hardened
├── network/
│   ├── netplan/                 # 網路設定
│   └── firewall-rules.sh
├── audio/
│   ├── alsa.conf
│   └── pulse/
│       └── default.pa
├── video/
│   └── v4l2-ctl-preset.sh
├── power/
│   ├── tlp.conf
│   └── wake-on-ac.sh
├── backup/
│   ├── backup.sh                # 備份
│   └── restore.sh
└── monitoring/
    ├── health-check.sh
    └── promtail-config.yaml
```

**職責**：
- 系統初始化、安裝
- 服務編排
- 安全性
- 網路 / 音訊 / 視訊設定
- 監控 / 備份

---

## 3. 介面契約

### 3.1 Unity → Bridge WebSocket

**`/ws` 端點**

訊息格式見 [API.md](API.md) § 3

### 3.2 Bridge → Runtime gRPC

定義在 `os-runtime/proto/siro.proto`：

```protobuf
syntax = "proto3";
package siro.runtime.v1;

service SiroRuntime {
  // 查詢系統狀態
  rpc GetStatus(Empty) returns (SystemStatus);
  // 查詢硬體資訊
  rpc GetHardwareInfo(Empty) returns (HardwareInfo);
  // 重啟服務
  rpc RestartService(ServiceName) returns (Ack);
  // 啟動 / 停止服務
  rpc ControlService(ServiceControl) returns (Ack);
  // Kiosk 模式切換
  rpc SetKioskMode(KioskRequest) returns (Ack);
  // 健康檢查
  rpc Health(Empty) returns (HealthStatus);
  // 串流 log
  rpc StreamLogs(LogFilter) returns (stream LogEntry);
  // 訂閱系統事件
  rpc SubscribeEvents(EventFilter) returns (stream SystemEvent);
}

// ... 訊息定義見 os-runtime/proto/siro.proto
```

### 3.3 Rust → systemd 整合

- 啟動時 `sd_notify::notify_ready()`
- 週期性 `sd_notify::notify_watchdog()`
- 優雅關機 `sd_notify::notify_stopping()`

### 3.4 設定檔

| 層 | 路徑 | 格式 | 誰讀 |
|----|------|------|------|
| Bridge | `bridge/.env` | dotenv | Python |
| Runtime | `/etc/siro/runtime.toml` | TOML | Rust |
| 每台裝置 | `/etc/siro/device.toml` | TOML | Rust |
| Unity | Player Prefs | binary | C# |
| System | `/etc/siro/*.conf` | 各式 | shell / systemd |

---

## 4. 資料流

### 4.1 對話（v0）

```
[Unity 打字]
  ↓ (WebSocket text)
[Bridge: /ws 接收]
  ↓
[Bridge: 加 session 上下文]
  ↓
[Bridge: subprocess hermes -p "..."]
  ↓
[Hermes CLI → LLM API]
  ↓ (回應文字)
[Bridge: parse [emotion:xxx] 標籤]
  ↓
[Bridge: map emotion → live2d signal]
  ↓ (WebSocket text)
[Unity: 顯示文字 + 切換表情]
```

### 4.2 服務監控（v1+）

```
[siro-runtime supervisor loop (1Hz)]
  ↓
[查 bridge PID, hermes PID, unity PID]
  ↓
[更新內部 ServiceState]
  ↓
[broadcast 到 gRPC subscribers]
  ↓
[siro-ctl status / bridge 查詢]
```

### 4.3 硬體管理

```
[siro-runtime 啟動]
  ↓
[硬體偵測模組]
  ├─ cpu.rs: lscpu, /proc/cpuinfo
  ├─ memory.rs: /proc/meminfo
  ├─ gpu.rs: nvidia-smi (NVIDIA only)
  ├─ audio.rs: arecord -l, pactl list
  └─ display.rs: xrandr / wlr-randr
  ↓
[HardwareInfo 結構]
  ↓
[gRPC GetHardwareInfo / HTTP /health]
```

---

## 5. 部署拓樸

### 5.1 v0 開發期（現在 Windows 筆電）

```
[Windows 11]
  ├─ Unity Editor (Play mode)
  ├─ WSL2 Ubuntu 24.04 (可選，用於測試 Layer 3)
  ├─ Python venv + uvicorn (bridge)
  ├─ Hermes CLI (subprocess)
  └─ (可選) Rust dev 環境
```

### 5.2 v1 Linux 化（同筆電）

```
[Ubuntu Server 24.04 LTS]
  ├─ systemd
  │   ├─ siro-runtime.service (Layer 3)
  │   ├─ hermes.service
  │   ├─ siro-bridge.service (Layer 2)
  │   └─ siro-unity.service (Layer 1, kiosk)
  ├─ X11 + openbox (kiosk session)
  ├─ NVIDIA Driver + CUDA
  └─ 自動登入 siro 使用者 → 自動啟動 X → siro-unity
```

**開機流程**：
1. BIOS → GRUB → Linux kernel
2. systemd 啟動
3. `siro-runtime` 第一個 user-space 服務
4. `siro-runtime` 啟動其他服務
5. `siro-bridge` 健康後，`siro-unity` 啟動
6. Unity 全螢幕，kiosk 模式
7. 開機到 Live2D 角色出現 < 30 秒

### 5.3 2-10 台 fleet

- 每台裝置有獨特的 `/etc/siro/device.toml`
- 共用 base image（從 Packer 產出）
- OTA 更新用 `scripts/ota-update.sh`
- 集中 log：每台 log 上送到中央 Loki（可選）

---

## 6. 資源與效能預算

| 元件 | 記憶體 | CPU idle | 啟動時間 |
|------|--------|----------|----------|
| systemd + 核心 | ~150MB | 1% | < 5s |
| siro-runtime | < 30MB | < 0.5% | < 500ms |
| hermes (subprocess) | ~100MB | 0% (sleeping) | 1-2s |
| bridge (Python) | ~150MB | < 0.5% | 2-3s |
| unity (Live2D) | ~800MB | 5-10% | 5-10s |
| Ollama + 7B LLM | ~5GB (VRAM) | 0% (idle) | 5-10s |
| **總計** | ~6.5GB | ~7% | 25-35s |

> 註：以上是 idle / 待機狀態。對話時 unity 跳到 30-50%、LLM 推論 100% GPU 數秒。

**硬體需求建議**：
- 16GB RAM
- 8GB VRAM（跑 7B Q4 模型）
- 256GB SSD
- 4 核心 CPU

---

## 7. 升級路徑

| 從 | 到 | 怎麼做 |
|----|----|----|
| v0 (Windows 開發) | v1 (Linux 同機) | 重灌 Ubuntu + 跑 os/install/* |
| v1 (單機) | v1.5 (雙 GPU 推論) | 加 GPU、siro-runtime 偵測多卡 |
| v1.5 | v2 (小型 fleet) | 加 OTA、log 集中、device config |
| subprocess hermes | MCP client | 改 bridge/hermes_client.py |
| Python bridge | Rust bridge | 重寫（業務邏輯移到 Rust）|
| Unity C# 客戶端 | Tauri Web 客戶端 | 重寫前端，bridge 介面不變 |
| 文字輸入 | 語音輸入 | 加 AudioInputManager.cs + STT |
| Hiyori | 自製模型 | 換 .moc3、檢查 expression 數量 |

---

## 8. 不在 v0/v1 範圍

- 多角色 / 換裝
- 多人多帳號
- 雲端 LLM 強制（保留可選）
- 多語言 UI（v0 繁中、英文 OK 即可）
- 行動 app（手機遠端控制 v2+）
- 雲端 dashboard
- 商業模式 / 計費
