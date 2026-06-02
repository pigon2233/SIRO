# SIRO 部署指南

> 從 0 到完成部署一台 SIRO 裝置的完整 SOP。
> 對應計畫書的 [Phase 6: 部署與營運](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-6-部署與營運)。

---

## 1. 部署模式

### 模式 A: 從零手動部署（v0/v1，1-2 台）

適用於：
- 開發者自己的機器
- 親友的機器
- 任何 < 5 台的場景

時間：~2 小時 / 台

### 模式 B: 預燒 image + 設定（v1.5+）

適用於：
- 2-10 台小型 fleet
- 設定只有 hostname / SSH key 差異

時間：~10 分鐘 / 台

### 模式 C: OTA 自動更新（v2+）

適用於：
- 大量裝置
- 持續維護

時間：~5 分鐘 / 裝置

---

## 2. 模式 A: 從零手動部署

### 步驟 1: 準備 USB

下載 Ubuntu Server 24.04 LTS ISO，燒到 USB：

```bash
# Windows 用 Rufus
# macOS / Linux 用 balenaEtcher
# 或指令：
sudo dd if=ubuntu-24.04-live-server-amd64.iso of=/dev/sdX bs=4M status=progress
```

### 步驟 2: BIOS 設定

- 開機進入 BIOS（ASUS 通常 F2 或 Del）
- 關閉 Secure Boot（避免 NVIDIA driver 問題）
- 設定 AC 自動開機（如果有需要）
- 開機順序：USB 第一

### 步驟 3: 安裝 Ubuntu

- 選「Install Ubuntu Server」
- 語言：English
- 鍵盤：依使用者
- 網路：DHCP（之後可改）
- 代理：跳過
- Mirror：預設台灣 mirror
- 儲存設定：
  - **雙系統**：選「Install alongside Windows」或「Manual partitioning」
  - **全替換**：選「Use entire disk」
- 使用者設定：建立 `siro` 使用者（會用 sudo）
- SSH：勾選「Install OpenSSH server」
- Featured Snaps：都不要選
- 等安裝完，重開機

### 步驟 4: 基礎系統

```bash
# 更新
sudo apt update && sudo apt upgrade -y

# 基礎套件
sudo apt install -y git curl wget build-essential \
    linux-headers-$(uname -r) \
    network-manager \
    vim nano \
    htop iotop \
    net-tools

# 設定時區
sudo timedatectl set-timezone Asia/Taipei

# 設定 hostname
sudo hostnamectl set-hostname siro-001
```

### 步驟 5: NVIDIA 驅動

```bash
# 確認 GPU
lspci | grep -i nvidia

# 裝 NVIDIA driver（用 ubuntu-drivers 自動選）
sudo ubuntu-drivers autoinstall

# 或手動選版本
sudo apt install nvidia-driver-550  # 對應 CUDA 12.x

# 重開機
sudo reboot

# 驗證
nvidia-smi
nvcc --version  # 沒裝 CUDA 工具，先不裝
```

### 步驟 6: SIRO 使用者與權限

```bash
# siro 使用者（如果安裝時沒建）
sudo useradd -m -s /bin/bash siro
sudo passwd siro
sudo usermod -aG sudo,audio,video,render,dialout siro

# 切換到 siro
su - siro
```

### 步驟 7: 安裝 Ollama（本地 LLM，可選）

```bash
curl -fsSL https://ollama.com/install.sh | sh

# 拉模型（推薦 Llama 3.2 3B Q4）
ollama pull llama3.2:3b-instruct-q4_0

# 驗證
ollama run llama3.2:3b "你好"
```

### 步驟 8: 安裝 Hermes Agent

```bash
# 用 SIRO 的腳本（從 SIRO repo 複製過來）
git clone https://github.com/pigon2233/SIRO.git
cd SIRO
bash agent/install.sh
bash agent/verify.sh
```

### 步驟 9: 安裝 Rust（Phase 3 開始）

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env

rustc --version
cargo --version
```

### 步驟 10: 編譯並安裝 siro-runtime

```bash
cd SIRO/os-runtime
cargo build --release
sudo cp target/release/siro-runtime /usr/local/bin/
sudo cp target/release/siro-ctl /usr/local/bin/

# 驗證
siro-runtime --version
siro-ctl --help
```

### 步驟 11: 安裝 Python Bridge

```bash
# 系統 Python
sudo apt install -y python3.11 python3.11-venv python3-pip

# 建 venv
cd ~/SIRO/bridge
python3.11 -m venv .venv
source .venv/bin/activate

# 裝依賴
pip install -r requirements.txt

# 驗證
python -m bridge.main --help
```

### 步驟 12: 部署 Unity Build

Phase 2 之後才會有 Unity build。

```bash
# Unity 開發者在自己的 Windows 機器 build 出 Linux 版
# 複製 build artifact 到裝置

sudo mkdir -p /opt/siro/unity
sudo cp -r /path/to/unity-build/* /opt/siro/unity/
sudo chown -R siro:siro /opt/siro
```

### 步驟 13: 設定 systemd 服務

```bash
# 複製 unit files
sudo cp SIRO/os/systemd/*.service /etc/systemd/system/

# 重新載入
sudo systemctl daemon-reload

# 啟用
sudo systemctl enable siro-runtime.service
sudo systemctl enable siro-bridge.service
sudo systemctl enable siro-unity.service

# 啟動
sudo systemctl start siro-runtime.service
sudo systemctl status siro-runtime.service
```

### 步驟 14: 設定 Kiosk 模式

```bash
# 自動登入
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
cat <<EOF | sudo tee /etc/systemd/system/getty@tty1.service.d/override.conf
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin siro --noclear %I \$TERM
EOF

# 安裝 X11 + openbox
sudo apt install -y xorg openbox

# 設定 openbox 自動啟動 Unity
mkdir -p ~/.config/openbox
cat <<EOF > ~/.config/openbox/autostart
# SIRO kiosk 自動啟動
/opt/siro/unity/SiroUnity.x86_64 &
EOF
```

### 步驟 15: 設定 firewall

```bash
# 裝 ufw
sudo apt install -y ufw

# 預設政策
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 開 SSH（限管理網段）
sudo ufw allow from 192.168.1.0/24 to any port 22

# 啟用
sudo ufw enable
sudo ufw status
```

### 步驟 16: 驗證全部

```bash
bash SIRO/os/install/99-verify.sh
```

應該全部通過。

### 步驟 17: 重開機測試

```bash
sudo reboot
```

開機後應該：
1. 自動登入 siro 使用者
2. 自動啟動 X11
3. openbox 自動啟動 Unity
4. Live2D 角色出現
5. 可以打字對話

---

## 3. 模式 B: 預燒 Image

### 工具

- [Packer](https://www.packer.io/) - 自動化 image 建構
- 或 `dd` + 客製化腳本

### 流程

```
[Base Ubuntu 24.04 ISO]
  ↓ Packer build
[含 SIRO 套件的 image]
  ↓ 燒到 USB / clone 到多台
[完成部署的裝置]
```

### Packer 範本（簡化）

```hcl
# siro-image.pkr.hcl
source "virtualbox-iso" "ubuntu" {
  iso_url      = "ubuntu-24.04-live-server-amd64.iso"
  iso_checksum = "sha256:..."
  ssh_username = "siro"
  ssh_password = "..."
  shutdown_command = "sudo poweroff"
}

build {
  sources = ["source.virtualbox-iso.ubuntu"]

  provisioner "shell" {
    scripts = [
      "os/install/00-base.sh",
      "os/install/10-nvidia.sh",
      "os/install/30-siro-runtime.sh",
      "os/install/40-bridge.sh",
      "os/install/50-unity.sh",
      "os/install/60-kiosk.sh",
      "os/install/70-security.sh",
    ]
  }
}
```

### 第一次開機設定

```
[開機]
  → systemd siro-first-boot.service
    → 詢問 hostname
    → 詢問 SSH public key
    → 套用 /etc/siro/device.toml
    → 重開機
```

---

## 4. 模式 C: OTA 更新

### 工具

- 自製 OTA server（Phase 6 實作）
- 或用現成：`mender`、`swupdate`、`ostree`

### 流程

```
[Build]
  ↓ 編譯新版
  ↓ 簽章（minisign / cosign）
[OTA server]
  ↓ HTTPS
[裝置]
  ↓ 定期檢查更新
  ↓ 下載 + 驗章
  ↓ A/B 切換
  ↓ 驗證成功繼續
  ↓ 失敗 rollback
```

### 更新頻率

- 安全更新：每週檢查
- 功能更新：每月檢查
- 大改版：每季檢查

---

## 5. 多裝置管理

### 2-10 台小型 fleet

不需要複雜管理工具。建議：

#### 設定管理

每台裝置有自己的 `/etc/siro/device.toml`：
```toml
[device]
id = "siro-001"
name = "客廳 SIRO"
location = "taipei-home"

[user]
primary_user_id = "user-001"
llm_provider = "ollama"  # 或 "nous" / "openrouter"

[network]
hostname = "siro-001.local"
```

#### 集中 log

- 用 `rsyslog` 上送到中央 server
- 或 `promtail` → `Loki` → `Grafana`

#### 批次指令

```bash
# 用 ssh + 迴圈
for host in siro-001 siro-002 siro-003; do
  ssh $host "sudo systemctl status siro-runtime"
done
```

#### 部署清單

`deploy/inventory.yaml`：
```yaml
hosts:
  - name: siro-001
    mac: aa:bb:cc:dd:ee:ff
    location: taipei-living-room
    user: dad
  - name: siro-002
    mac: aa:bb:cc:dd:ee:00
    location: taipei-bedroom
    user: mom
```

---

## 6. 升級流程

### Minor update (0.1.0 → 0.1.1)

1. 開發者發版
2. 跑 `scripts/build-image.sh` 產新 image
3. 推到 OTA server
4. 裝置自動更新
5. 監看 24-48 小時

### Major update (0.x → 1.0)

1. 開發者發版
2. 寫升級指南
3. Phase-by-phase 推送（先 1 台測試，再 10%、50%、100%）
4. 監看 1 週

### Rollback

如果新版有問題：
1. 開發者撤回新版
2. 裝置自動 rollback
3. 修復 bug
4. 重新發版

---

## 7. 監控指標

每台裝置定期上報（或查詢）：

| 指標 | 重要性 | 警報閾值 |
|------|--------|----------|
| 服務健康 | 高 | 任一 service not running |
| CPU 溫度 | 中 | > 85°C |
| GPU 溫度 | 中 | > 90°C |
| 磁碟使用 | 中 | > 90% |
| 記憶體使用 | 低 | > 90% |
| LLM API 錯誤率 | 高 | > 10% |
| OTA 失敗 | 高 | 連續 3 次 |
| 離線時間 | 中 | > 24 小時沒互動 |

---

## 8. 疑難排解

### 開機沒看到 Live2D

1. 確認 X11 有跑：`echo $DISPLAY` 應該是 `:0`
2. 確認 openbox 有跑：`pgrep openbox`
3. 確認 Unity 有跑：`pgrep -f SiroUnity`
4. 看 `~/.xsession-errors` log

### 對話沒回應

1. 確認 bridge 有跑：`curl localhost:8001/health`
2. 確認 hermes 可用：`bash agent/verify.sh`
3. 確認 LLM API 可用（如果有雲端）

### 視訊 / 麥克風沒作用

1. 確認硬體：`arecord -l` / `ls /dev/video*`
2. 確認 PulseAudio：`pactl list sources`
3. 確認 AppArmor 沒擋：`sudo aa-status`

### OTA 更新失敗

1. 確認網路：`ping ota.siro.local`
2. 確認磁碟空間：`df -h`
3. 確認簽章：`siro-ctl ota verify`

---

## 9. 不在 v0/v1 部署範圍

- Kubernetes / Docker
- 雲端原生 (CI/CD in cloud)
- 跨區域部署
- 自動水平擴展
- AIOps 自動修補

這些是 v2+ 規模才需要。

---

## 10. 相關文件

- [SETUP.md](SETUP.md) - 開發環境設定
- [OPERATIONS.md](OPERATIONS.md) - 日常營運
- [SECURITY.md](SECURITY.md) - 安全性
- [os/install/README.md](../os/install/README.md) - 安裝腳本
