# os/security/ - 安全性設定

> **Phase 4 規劃**。多層防禦：防火牆、SELinux/AppArmor、ssh 鎖定。
> 對應 K7（隱私 0 預設外洩）+ K3（穩定 7 天無當機）。

## 威脅模型

SIRO 是一個「永遠開機、有相機、有麥克風、連網路」的裝置。

| 威脅 | 機率 | 影響 | 緩解 |
|------|------|------|------|
| 駭客透過網路入侵 | 中 | 高 | ufw 預設拒絕、只開必要 port |
| 物理接觸（鍵盤滑鼠）| 中 | 中 | kiosk 鎖輸入、密碼 escape |
| 惡意套件（apt）| 低 | 高 | 只用 Ubuntu 官方 repo、gpg 驗證 |
| 偷取資料（log 內含對話）| 中 | 高 | log 過濾個資、本地優先 |
| 拒絕服務（網路）| 中 | 中 | rate limit、fail2ban |
| Side channel（時序、能源）| 低 | 中 | 接受風險 |

---

## 1. ufw 防火牆

### 規則範例（`os/security/ufw-rules.sh`）

```bash
#!/bin/bash
set -e

# 預設拒絕所有輸入
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH（限定管理網段 — 量產時改成實際管理網段）
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp comment "SSH admin only"

# 不開對外服務（SIRO 是 kiosk、Unity 端只連 bridge）
# 如果 Phase 6 要中央監控，加 Loki port:
# sudo ufw allow from <monitoring-server> to any port 3100 proto tcp

# 啟用
sudo ufw enable

# 顯示規則
sudo ufw status verbose
```

### 驗證

```bash
# 對外 port 應該全部關閉
nmap -p 1-1000 <siro-ip>   # 應該看不到 22 從外部（只允許 192.168.1.0/24）
curl -m 3 http://<siro-ip>:8001/chat  # 應該 timeout（kiosk 對外不開）
```

---

## 2. ssh 鎖定

### `/etc/ssh/sshd_config` 修訂

```sshd_config
# Port
Port 2222                              # 預設 22 改 2222（避開自動掃描）

# 認證
PermitRootLogin no                     # 不准 root 登入
PasswordAuthentication no              # 關閉密碼登入
PubkeyAuthentication yes               # 只用 SSH key
AuthenticationMethods publickey        # 強制
MaxAuthTries 3
MaxSessions 3

# 使用者限制
AllowUsers siro                        # 只有 siro 可以登入

# 安全
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
PermitUserEnvironment no

# Timeout
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
```

### fail2ban 設定（`/etc/fail2ban/jail.local`）

```ini
[sshd]
enabled = true
port = 2222
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
findtime = 600
```

### 管理員 SSH key 部署

```bash
# 管理員的 public key 放
/home/siro/.ssh/authorized_keys
# 權限 600
chmod 600 /home/siro/.ssh/authorized_keys
chmod 700 /home/siro/.ssh
```

---

## 3. AppArmor Profiles

每個 SIRO 服務都有自己的 AppArmor profile，限制能讀寫的檔案、能用的 syscall。

### siro-bridge profile（`/etc/apparmor.d/siro-bridge`）

```
#include <tunables/global>

/usr/local/bin/siro-bridge {
  #include <abstractions/base>
  #include <abstractions/python>
  #include <abstractions/openssl>

  # 執行
  /usr/local/bin/siro-bridge rix,
  /opt/siro/bridge/.venv/bin/python3 rix,
  /opt/siro/bridge/** r,

  # 設定（唯讀）
  /opt/siro/bridge/.env r,
  /etc/siro/ r,
  /etc/siro/** r,

  # 寫入限定
  /var/log/siro/ w,
  /var/log/siro/** w,
  /var/lib/siro/ w,
  /var/lib/siro/** w,
  /tmp/siro-* rwk,

  # 網路
  network inet stream,
  network inet6 stream,
  network unix stream,

  # 拒絕
  deny /home/siro/** rwx,
  deny /etc/shadow r,
  deny /etc/passwd w,
  deny capability dac_override,
  deny capability dac_read_search,
}
```

啟用：

```bash
sudo apparmor_parser -r /etc/apparmor.d/siro-bridge
sudo aa-status  # 確認 enforce 模式
```

### siro-runtime / siro-unity profile 類似，照抄

---

## 4. 套件管理安全

### apt 來源限制（`/etc/apt/sources.list.d/ubuntu-official.list`）

```
# 只留 Ubuntu 官方 + 安全更新
deb http://archive.ubuntu.com/ubuntu noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu noble-security main restricted universe multiverse
```

### 不裝第三方 PPA

- 不加 PPA（避免供應鏈攻擊）
- 如果一定要裝，先 `apt-key` 驗證 → 改 `signed-by` 機制（apt 1.1+）

### unattended-upgrades 自動安全更新

```ini
# /etc/apt/apt.conf.d/50unattended-upgrades
Unattended-Upgrade::Allowed-Origins {
  "${distro_id}:${distro_codename}-security";
};

Unattended-Upgrade::Automatic-Reboot "false";  # 不自動重啟（kiosk 不能重啟）
Unattended-Upgrade::DevRelease "false";
```

---

## 5. 隱私

| 措施 | 實作 |
|------|------|
| 對話 log 預設只留本機 | 寫 `/var/log/siro/`、不上雲 |
| 上傳雲端需明確同意 | /opt/siro/bridge/.env 有 `SIRO_ALLOW_CLOUD_UPLOAD=false` 預設值 |
| 攝影機 / 麥克風實體指示燈 | Phase 5 硬體整合，硬體規格要求 |
| 錄影 / 錄音前告知 | Unity 端 UI 顯示「錄音中」狀態 |
| log 過濾個資 | 對話內容不寫 `/var/log/siro/bridge.log`、只寫 session_id + length |

---

## 6. OTA 更新安全（Phase 6）

- 用 code signing（`cosign` 或 `minisign`）
- 更新前驗證簽章
- 失敗自動 rollback
- 更新過程原子化（A/B partition 或 OSTree）

```bash
# 更新流程（si-runtime 內部）
os update --image siro-v0.4.0.sqsh
# 1. 下載 image
# 2. cosign verify --key cosign.pub siro-v0.4.0.sqsh
# 3. 寫入 B partition
# 4. 切 boot 到 B
# 5. 重啟
# 6. /health 通過 → commit（保留 A 為 fallback）
#    /health 失敗 → rollback（切回 A）
```

---

## 7. 對話 log 過濾

`/etc/siro/rsyslog.d/siro-privacy.conf`：

```
# 把對話內容從 syslog 拿掉
:msg, contains, "user_message" /dev/null
:msg, contains, "llm_response" /dev/null
:msg, contains, "raw_response" /dev/null
```

或 Python logger 端（`bridge/main.py`）：

```python
# 不 log 對話原文，只 log metadata
logger.info(f"chat session={session_id} user={user_id} len={len(user_message)}")
# 不 logger.info(f"chat user said: {user_message}")  ← 禁止
```

---

## 驗證（Phase 4 寫）

```bash
# 1. ufw 規則
sudo ufw status verbose
# 預期：22 限管理網段、其他關閉

# 2. ssh 鎖定
ssh -o BatchMode=yes -o ConnectTimeout=5 siro@<ip>  # 沒 key 應該被拒
ssh -p 22 siro@<ip>  # 應該 connection refused（改 port 2222）

# 3. AppArmor 啟用
sudo aa-status | grep siro
# 預期：siro-bridge / siro-runtime / siro-unity 都 enforce

# 4. root login
sudo grep "^PermitRootLogin" /etc/ssh/sshd_config
# 預期：PermitRootLogin no

# 5. 個資不 log
sudo grep -r "user_message\|llm_response" /var/log/siro/
# 預期：無輸出
```

---

## 不在 Phase 4 範圍

- ❌ 入侵偵測系統（IDS，Phase 6 — Suricata）
- ❌ SIEM（Phase 6+）
- ❌ 漏洞掃描（Phase 6+ 用 OpenVAS）

---

## Phase 4 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| ufw 規則 + sshd_config | 0.5 天 | 低 |
| fail2ban + SSH key 部署 | 0.5 天 | 低 |
| 3 個 AppArmor profile 撰寫 + 測試 | 2 天 | 中（profile 除錯容易踩坑）|
| 套件來源限制 + unattended-upgrades | 0.5 天 | 低 |
| 個資過濾 | 0.5 天 | 低 |
| **總計** | **4 天** | — |
