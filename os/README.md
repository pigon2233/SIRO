# os/ - Linux 系統設定

> 對應計畫書的 [Phase 4: Linux 客製化](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-4-linux-客製化)。

存放 Ubuntu Server 24.04 LTS 的安裝腳本、systemd 服務、kiosk 模式設定等。

**目前狀態**：目錄結構已建立，**所有腳本都是 stub**。Phase 4 開始才會實作。

---

## 目錄結構

```
os/
├── README.md                    ← 本檔
├── install/                     # 自動安裝腳本（Phase 4 實作）
├── systemd/                     # systemd 服務定義
├── kiosk/                       # Kiosk 模式設定
├── security/                    # AppArmor / ufw
├── network/                     # netplan / firewall
├── audio/                       # ALSA / PulseAudio
├── video/                       # V4L2 / camera
├── power/                       # 電源管理
├── backup/                      # 備份 / 還原
└── monitoring/                  # 健康檢查 / log 上送
```

每個子目錄都有自己的 README（Phase 4 加）。

---

## 設計原則

1. **Idempotent** — 同一個腳本可以重跑，不會壞掉
2. **可逆** — 每個 install 腳本對應一個 uninstall 腳本
3. **可審查** — 設定檔是 plain text，可用 git diff 檢視
4. **測試驅動** — install 腳本有對應的 verify 腳本

---

## 安裝流程（高階）

```
[Phase 4 - 同筆電雙系統]
  1. 製作 Ubuntu Server 24.04 LTS Live USB
  2. 開機進入 Live USB
  3. 跑 os/install/00-base.sh 裝基本系統
  4. 跑 os/install/10-nvidia.sh 裝 NVIDIA 驅動
  5. 跑 os/install/30-siro-runtime.sh 編譯安裝 Rust daemon
  6. 跑 os/install/40-bridge.sh 安裝 Python bridge
  7. 跑 os/install/50-unity.sh 部署 Unity build
  8. 跑 os/install/60-kiosk.sh 設 kiosk 模式
  9. 跑 os/install/70-security.sh 設 AppArmor + ufw
 10. 跑 os/install/99-verify.sh 驗證全部

[Phase 6 - 量產時]
  - 上面的步驟包進 Packer image
  - 第一次開機跑 first-boot script 設定 hostname / SSH key
```

---

## 不要直接 commit 的東西

- 任何含 API key / token / 密碼的設定
- 個人化的 hostname / SSH key
- 任何 binary (應該從 source build)

---

## 不在 Phase 4 範圍

- ❌ 量產 image（Phase 6）
- ❌ OTA 更新（Phase 6）
- ❌ 監控儀表板（Phase 6）
- ❌ 跨裝置設定同步（Phase 6+）
