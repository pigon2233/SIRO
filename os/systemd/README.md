# os/systemd/ - systemd 服務定義

> **Phase 4 規劃**。定義 SIRO 各層服務的 systemd unit。
> 對應計畫書 [Phase 4: Linux 客製化](../../LIVE2D_AI_AGENT_OS_PLAN.md#phase-4-linux-客製化)

## 服務總覽

| 服務 | 啟動順序 | 用途 | 啟動延遲容忍 |
|------|----------|------|--------------|
| `siro-runtime.service` | 1 | Rust daemon，監控其他服務 + 硬體抽象 | 5 秒 |
| `hermes.service` | 2 | Hermes Agent（背景跑，需要時被 bridge 叫） | 10 秒（hermes CLI 啟動慢） |
| `siro-bridge.service` | 3 | Python FastAPI，需要 siro-runtime 就緒 | 5 秒 |
| `siro-unity.service` | 4 | Unity kiosk，需要 siro-bridge 健康 | 30 秒（Unity 啟動慢） |

### 服務依賴圖

```
multi-user.target
    │
    ├─ siro-runtime.service (1)
    │       │ After=network-online.target
    │       │ Type=notify
    │       └─ sd_notify("READY=1") 觸發
    │
    ├─ hermes.service (2)
    │       │ After=siro-runtime.service
    │       └─ 持續跑，bridge 透過 subprocess 叫
    │
    ├─ siro-bridge.service (3)
    │       │ After=siro-runtime.service hermes.service
    │       │ Requires=siro-runtime.service
    │       └─ /health 端點就緒觸發後續
    │
    └─ siro-unity.service (4)
            │ After=siro-bridge.service
            │ Requires=siro-bridge.service
            └─ Unity 啟動、連上 /ws
```

---

## 設計原則

1. **Type=notify** — 用 sd_notify 通知 systemd 服務狀態
2. **Restart=on-failure** — 自動重啟
3. **RestartSec=5** — 5 秒後重試（避免 tight loop）
4. **WatchdogSec=30** — watchdog 30 秒
5. **User=siro** — 不要用 root 跑
6. **ProtectSystem=strict** — 系統保護
7. **NoNewPrivileges=true** — 不允許提權
8. **PrivateTmp=true** — 私有 /tmp
9. **ReadWritePaths=/var/log/siro /var/lib/siro** — 限定可寫路徑

---

## 4 個服務的完整 unit 範例

### 1. siro-runtime.service

```ini
# /etc/systemd/system/siro-runtime.service
[Unit]
Description=SIRO System Runtime (Rust daemon)
Documentation=https://github.com/pigon2233/SIRO
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/local/bin/siro-runtime --config /etc/siro/runtime.toml
WatchdogSec=30
Restart=on-failure
RestartSec=5
User=siro
Group=siro

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/siro /var/lib/siro
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictNamespaces=true
RestrictRealtime=true
SystemCallArchitectures=native
SystemCallFilter=@system-service

# Resource limits
MemoryMax=512M
TasksMax=256

[Install]
WantedBy=multi-user.target
```

### 2. hermes.service

```ini
# /etc/systemd/system/hermes.service
[Unit]
Description=Hermes Agent (background LLM CLI)
After=siro-runtime.service

[Service]
Type=simple
# Hermes 是 CLI，每次叫才 spawn，但 background 跑個 daemon-mode 給預熱
ExecStart=/home/siro/.local/bin/hermes --daemon --socket /var/run/hermes.sock
Restart=on-failure
RestartSec=5
User=siro
Group=siro

# Hermes 需要讀 .env
EnvironmentFile=/home/siro/.hermes/.env

# Security（比 siro-runtime 寬鬆 — Hermes 要 spawn LLM subprocess）
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/var/log/siro /var/lib/siro /home/siro/.hermes
ProtectHome=false

# 資源
MemoryMax=2G    # Hermes + LLM subprocess 可能佔多
TasksMax=512

[Install]
WantedBy=multi-user.target
```

### 3. siro-bridge.service

```ini
# /etc/systemd/system/siro-bridge.service
[Unit]
Description=SIRO AI Bridge (Python FastAPI)
After=siro-runtime.service hermes.service
Requires=siro-runtime.service

[Service]
Type=notify
ExecStart=/opt/siro/bridge/.venv/bin/python -m bridge.main
WorkingDirectory=/opt/siro/bridge
EnvironmentFile=/opt/siro/bridge/.env
WatchdogSec=30
Restart=on-failure
RestartSec=5
User=siro
Group=siro

# /health 端點 ready 後透過 sd_notify 通知
ExecStartPost=/bin/bash -c 'sleep 3 && curl -sf http://127.0.0.1:8001/health | grep -q "ok" && systemd-notify --ready'

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/siro /var/lib/siro
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallArchitectures=native
SystemCallFilter=@system-service

# 資源
MemoryMax=1G
TasksMax=512

[Install]
WantedBy=multi-user.target
```

### 4. siro-unity.service

```ini
# /etc/systemd/system/siro-unity.service
[Unit]
Description=SIRO Unity Kiosk (Live2D frontend)
After=siro-bridge.service
Requires=siro-bridge.service
# 不在 multi-user.target 啟動（會卡 X11），改在 graphical.target
After=graphical.target

[Service]
Type=simple
# 用 siro 使用者身份跑 Unity（X11 已經從 getty 啟動了）
ExecStart=/opt/siro/unity/unity-runner.sh
Restart=on-failure
RestartSec=10
User=siro
Group=siro

# Unity 需要 X11 / DRI / NVIDIA
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/siro/.Xauthority

# Security（比 bridge 寬鬆 — Unity 要寫 X server）
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/var/log/siro /home/siro/.config

# 資源（Unity 吃顯卡、不吃 RAM）
MemoryMax=4G
TasksMax=1024

[Install]
WantedBy=graphical.target
```

---

## 安裝流程

### 一次性安裝腳本（`os/install/40-bridge.sh` 範例）

```bash
#!/bin/bash
# 安裝 siro-bridge systemd unit
set -e

# 1. 複製 unit 檔
sudo cp os/systemd/siro-bridge.service /etc/systemd/system/

# 2. reload systemd
sudo systemctl daemon-reload

# 3. enable（開機自動啟動）
sudo systemctl enable siro-bridge.service

# 4. start（立即啟動）
sudo systemctl start siro-bridge.service

# 5. 驗證
sleep 2
systemctl is-active siro-bridge.service
curl -sf http://127.0.0.1:8001/health | grep -q "ok"
```

### 解除安裝（`os/install/40-bridge-uninstall.sh`）

```bash
#!/bin/bash
set -e
sudo systemctl stop siro-bridge.service || true
sudo systemctl disable siro-bridge.service || true
sudo rm /etc/systemd/system/siro-bridge.service
sudo systemctl daemon-reload
```

---

## 啟動順序驗證（K1 KPI 對應）

```bash
#!/bin/bash
# os/systemd/verify-boot-order.sh

# 從 systemd-analyze 看啟動時間 + 依賴圖
systemd-analyze
systemd-analyze dot | grep siro

# 預期：
# - siro-runtime.service 在 5 秒內 ready
# - siro-bridge.service 在 siro-runtime 後啟動
# - siro-unity.service 在 siro-bridge 健康後啟動
# 整體 K1 目標：開機到對話就緒 < 30 秒
```

---

## 故障排除 SOP

| 症狀 | 可能原因 | 排查 |
|------|----------|------|
| siro-bridge 一直 `activating` | siro-runtime 沒 notify READY | `journalctl -u siro-runtime -n 50` 看有沒有 `[siro-runtime] READY=1` |
| siro-unity 起來但畫面黑 | DISPLAY / XAUTHORITY 環境沒設 | `systemctl show siro-unity -p Environment` 確認有 `DISPLAY=:0` |
| Restart=on-failure 進入迴圈 | WatchdogSec 觸發 | `systemctl show siro-bridge -p WatchdogTimestamp` 看 watchdog 觸發時間 |
| 服務啟動順序錯亂 | Requires/After 沒設好 | `systemd-analyze verify /etc/systemd/system/siro-*.service` 驗證依賴 |

---

## Phase 4 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| 4 個 service unit 撰寫 + 測試 | 2 天 | 中（security hardening 容易踩坑） |
| install / uninstall 腳本 | 1 天 | 低 |
| 啟動順序驗證 + 故障排除 SOP | 1 天 | 中 |
| **總計** | **4 天** | — |

---

## 不在 Phase 4 範圍

- ❌ 量產 Packer image（Phase 6）
- ❌ OTA 更新（Phase 6）
- ❌ 監控儀表板（Phase 6）
- ❌ 跨裝置設定同步（Phase 6+）
