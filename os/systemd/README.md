# os/systemd/ - systemd 服務定義

> Phase 4 實作。定義 SIRO 各層服務的 systemd unit。

## 計畫的服務

| 服務 | 啟動順序 | 用途 |
|------|----------|------|
| `siro-runtime.service` | 1 | Rust daemon，監控其他服務 |
| `hermes.service` | 2 | Hermes Agent（背景跑，需要時被 bridge 叫） |
| `siro-bridge.service` | 3 | Python FastAPI，需要 siro-runtime 就緒 |
| `siro-unity.service` | 4 | Unity kiosk，需要 siro-bridge 健康 |

## 設計原則

1. **Type=notify** — 用 sd_notify 通知 systemd 服務狀態
2. **Restart=on-failure** — 自動重啟
3. **WatchdogSec=30** — watchdog 30 秒
4. **User=siro** — 不要用 root 跑
5. **ProtectSystem=strict** — 系統保護
6. **NoNewPrivileges=true** — 不允許提權
7. **PrivateTmp=true** — 私有 /tmp
8. **ReadWritePaths=/var/log/siro /var/lib/siro** — 限定可寫路徑

## 範例（待 Phase 4 實作）

```ini
# /etc/systemd/system/siro-runtime.service
[Unit]
Description=SIRO System Runtime
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

# Security
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

[Install]
WantedBy=multi-user.target
```
