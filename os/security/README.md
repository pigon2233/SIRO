# os/security/ - 安全性設定

> Phase 4 實作。多層防禦：防火牆、SELinux/AppArmor、ssh 鎖定。

## 威脅模型

SIRO 是一個「永遠開機、有相機、有麥克風、連網路」的裝置。

| 威脅 | 機率 | 影響 | 緩解 |
|------|------|------|------|
| 駭客透過網路入侵 | 中 | 高 | ufw 預設拒絕、只開必要 port |
| 物理接觸（鍵盤滑鼠） | 中 | 中 | kiosk 鎖輸入、密碼 escape |
| 惡意套件（apt） | 低 | 高 | 只用 Ubuntu 官方 repo、gpg 驗證 |
| 偷取資料（log 內含對話） | 中 | 高 | log 過濾個資、本地優先 |
| 拒絕服務（網路） | 中 | 中 | rate limit、fail2ban |
| Side channel（時序、能源） | 低 | 中 | 接受風險 |

## AppArmor Profiles

每個 SIRO 服務都有自己的 AppArmor profile：
- `siro-runtime`：限制檔案存取
- `siro-bridge`：限制 Python import、檔案寫入
- `siro-unity`：限制 network（只能連 bridge）

AppArmor 比 SELinux 簡單，適合 SIRO 規模。

## ufw 規則

預設拒絕所有輸入，只開：
- 22/tcp (SSH, **限管理網段**)
- 其他都不開（SIRO 是 kiosk，不需要對外服務）

## ssh 鎖定

- 改 port 22 → 自訂 port
- 關閉密碼登入，只用 SSH key
- 限制可登入使用者
- fail2ban
- 不允許 root 登入

## 隱私

- 對話 log 預設只留在本機
- 上傳到雲端（如果有的話）需明確同意
- 攝影機 / 麥克風有實體指示燈（如果硬體支援）
- 任何錄影 / 錄音行為需在使用者面前告知

## OTA 更新安全

- 用 code signing（`cosign` 或 `minisign`）
- 更新前驗證簽章
- 失敗自動 rollback
- 更新過程原子化（A/B partition 或 OSTree）
