# os/backup/ - 備份 / 還原

> **Phase 6 規劃**。SIRO 故障時能在 10 分鐘內還原。
> 對應 K3（7 天無當機）+ 災難演練。

## 備份策略

### 什麼要備份

| 對象 | 重要性 | 頻率 | 工具 |
|------|--------|------|------|
| 使用者對話歷史（`/var/lib/siro/sessions/`）| 🔴 高 | 即時（每次對話後）| restic + inotify |
| 個人化設定（`/etc/siro/personas/`, `/home/siro/.config/siro/`）| 🟠 中 | 每天 | restic |
| 系統 log（`/var/log/siro/`）| 🟢 低 | 每天 + logrotate | restic |
| 系統設定（`/etc/siro/`、`/etc/systemd/system/siro-*.service`）| 🟠 中 | 改動時 + 每天 | restic + git |
| 系統 image | 🟠 中 | 每月 + 改 OS 設定時 | Packer |

### 備份目標

- **本地**：另一個分割區（防止同碟故障）— 預設 `/mnt/backup/`
- **遠端**：可選，自己的 NAS 或雲端（Backblaze B2 / S3）
- **加密**：restic 預設 AES-256，密碼從 `~/.config/restic/passphrase` 讀
- **保留**：本地 7 天、7 週、12 月、永久（10%）；遠端 30 天、12 月

### 備份工具選擇

| 工具 | 優點 | 缺點 | 推薦 |
|------|------|------|------|
| `rsync` | 簡單 | 無版本化 | ❌ |
| `rsnapshot` | 簡單、差異 | 慢 | 🟡 個人用 |
| `borgbackup` | 加密、壓縮、版本化 | 早期 Go 缺點（已修）| 🟡 進階 |
| **`restic`** | **Go 單檔、S3 原生、加密、版本化** | **無 GUI** | **✅ 推薦** |

---

## restic 設定範例

### 初始化（一次性）

```bash
# 本地 repo
sudo -u siro restic init -r /mnt/backup/siro

# 遠端 repo（Backblaze B2 範例）
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
sudo -u siro restic init -r s3:s3.us-west-002.backblazeb2.com/siro-backup
```

### 備份指令（`os/backup/backup.sh`）

```bash
#!/bin/bash
set -euo pipefail

export RESTIC_REPOSITORY=/mnt/backup/siro
export RESTIC_PASSWORD_FILE=/home/siro/.config/restic/passphrase

# 1. 對話歷史（即時 — 每天多次）
sudo -u siro restic backup \
  /var/lib/siro/sessions/ \
  --tag sessions \
  --exclude-caches

# 2. 設定 + log（每天 cron）
sudo -u siro restic backup \
  /etc/siro/ \
  /var/log/siro/ \
  /home/siro/.config/siro/ \
  --tag daily-config

# 3. retention 套用
sudo -u siro restic forget \
  --keep-daily 7 \
  --keep-weekly 7 \
  --keep-monthly 12 \
  --keep-yearly 10 \
  --prune
```

### Cron 設定（`/etc/cron.d/siro-backup`）

```cron
# 每小時備份對話歷史
0 * * * * siro /opt/siro/os/backup/backup-sessions.sh

# 每天 03:00 備份設定
0 3 * * * siro /opt/siro/os/backup/backup-config.sh

# 每月 1 號驗證備份
0 4 1 * * siro /opt/siro/os/backup/verify-backup.sh
```

### 對話即時備份（inotify 觸發）

```bash
# /opt/siro/os/backup/sessions-watcher.sh
inotifywait -m /var/lib/siro/sessions/ -e create -e modify |
while read path event file; do
    restic backup "$path$file" --tag sessions-immediate
done
```

---

## 還原策略

### 情境 1: 對話歷史誤刪

```bash
# 列出 snapshot
sudo -u siro restic snapshots -r /mnt/backup/siro --tag sessions

# 還原最新 snapshot
sudo -u siro restic restore latest \
  --target /tmp/restore \
  --tag sessions \
  --include /var/lib/siro/sessions/

# 驗證後覆蓋
diff -r /var/lib/siro/sessions /tmp/restore/var/lib/siro/sessions
sudo cp -r /tmp/restore/var/lib/siro/sessions/* /var/lib/siro/sessions/
```

### 情境 2: 整個 OS 故障

```bash
# 1. USB 開機 → 跑 Packer image 還原 base system
# 2. 掛載 /mnt/backup
mount /dev/sdb1 /mnt/backup

# 3. restic 還原
RESTIC_REPOSITORY=/mnt/backup/siro \
RESTIC_PASSWORD_FILE=/tmp/passphrase \
restic restore latest --target /

# 4. 重啟 + 驗證
reboot
```

### 情境 3: 從零還原（新機器）

```bash
# 1. 燒 Packer image USB + 開機
# 2. 網路設定
# 3. mount 遠端備份（Backblaze B2）
restic restore latest \
  -r s3:s3.us-west-002.backblazeb2.com/siro-backup \
  --target / --include /etc/siro --include /var/lib/siro

# 4. 第一次開機 setup（hostname / SSH key / persona）
# 5. 驗證
systemctl status siro-bridge siro-unity
curl localhost:8001/health
```

---

## 災難演練 checklist

每季做一次（Phase 6 才開始）：

| 情境 | 測試指令 | 預期時間 |
|------|----------|----------|
| 對話歷史誤刪還原 | `restic restore latest --tag sessions` | < 1 分鐘 |
| 設定檔損壞還原 | `restic restore latest --tag daily-config --include /etc/siro` | < 2 分鐘 |
| 整台磁碟故障（從 USB）| 重灌 + restic restore latest | < 10 分鐘 |
| 從零（換新機器）| Packer + restic from S3 | < 30 分鐘 |

---

## 驗證腳本（`os/backup/verify-backup.sh`）

```bash
#!/bin/bash
set -e

# 1. 確認最近 24 小時內有 snapshot
LATEST=$(sudo -u siro restic snapshots -r /mnt/backup/siro --json | jq -r '.[0].time')
NOW=$(date +%s)
SNAPSHOT_TS=$(date -d "$LATEST" +%s)
[ $((NOW - SNAPSHOT_TS)) -lt 86400 ] || { echo "FAIL: no snapshot in 24h"; exit 1; }

# 2. 確認 repo 完整性
sudo -u siro restic check -r /mnt/backup/siro

# 3. 隨機還原一個檔案驗證
TMPDIR=$(mktemp -d)
sudo -u siro restic restore latest --target "$TMPDIR" --include /etc/siro/runtime.toml
test -f "$TMPDIR/etc/siro/runtime.toml" || { echo "FAIL: restore broken"; exit 1; }
rm -rf "$TMPDIR"

echo "ALL PASS"
```

---

## 不在 Phase 6 範圍

- ❌ 自動 failover（多機叢集）
- ❌ 雲端原生備份（K8s 之類）
- ❌ 區塊層級備份（DRBD 之類，太複雜）

---

## Phase 6 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| restic repo 初始化 + 設定 | 0.5 天 | 低 |
| backup / restore 腳本 + cron | 1 天 | 低 |
| inotify 即時備份 | 0.5 天 | 中（inotify event 處理 edge case）|
| 還原 SOP 撰寫 + 演練 | 1 天 | 中（要實際跑才知道哪裡卡）|
| **總計** | **3 天** | — |
