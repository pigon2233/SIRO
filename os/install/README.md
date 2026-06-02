# os/install/ - 自動安裝腳本

> Phase 4 實作。本檔是 placeholder 與計畫。

## 計畫的腳本

| 腳本 | 用途 | 順序 |
|------|------|------|
| `00-base.sh` | 基本系統：時區、locale、套件更新 | 1 |
| `10-nvidia.sh` | NVIDIA 驅動 + CUDA + cuDNN | 2 |
| `20-siro-user.sh` | 建 `siro` 使用者、加 sudo 權限 | 3 |
| `30-siro-runtime.sh` | 編譯 `siro-runtime`、安裝到 `/usr/local/bin` | 4 |
| `40-bridge.sh` | 安裝 Python venv + bridge 依賴 | 5 |
| `50-unity.sh` | 部署 Unity build 到 `/opt/siro/unity` | 6 |
| `60-kiosk.sh` | X11 + openbox + 自動登入 | 7 |
| `70-security.sh` | AppArmor profiles + ufw rules | 8 |
| `99-verify.sh` | 跑完整驗證（health check + 端到端測試） | 最後 |

## 設計

每個腳本：
- 有 `#!/usr/bin/env bash` + `set -euo pipefail`
- 開頭檢查 root 權限
- 結尾印 "✓ <name> done"
- 失敗時印 "✗ <name> failed" 並 exit 1

可以被 `installer.sh` 串起來依序執行，也可以單獨跑。

## 對應的反安裝腳本

每個 install 腳本對應一個 uninstall 腳本，存放在 `os/install/uninstall/`。

（目前不實作，Phase 4 才開始。）
