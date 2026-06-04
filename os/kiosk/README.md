# os/kiosk/ - Kiosk 模式設定

> **Phase 4 規劃**。把 Ubuntu 桌面變成全螢幕 Unity，只能跑 SIRO，鎖住鍵盤滑鼠。
> 詳細計畫見 [../README.md](../README.md) 高階安裝流程。

## 兩種 Kiosk 技術

### 選項 A: X11 + Openbox（v0.5，較熟悉）
- 開源、文件多、容易 debug
- `openbox` 是輕量 window manager
- 自動啟動 Unity：`~/.config/openbox/autostart`

### 選項 B: Wayland + Cage（v1+ 推薦）
- 現代、無 X11 歷史包袱
- `cage` 是專為 kiosk 設計的 Wayland compositor
- 啟動單一應用程式（Unity）

## v0.5 選 X11 + Openbox

理由：
- 文件多、踩坑少
- NVIDIA 驅動支援較成熟
- 之後要升級 Wayland 也容易

---

## 自動登入 + 自動啟動流程

```
GRUB → Linux kernel
  → systemd
    → getty@tty1 (siro 使用者自動登入)
      → ~/.bash_profile
        → startx
          → /etc/X11/Xsession
            → openbox
              → openbox autostart
                → siro-unity (全螢幕)
```

### 設定 1: getty 自動登入（`/etc/systemd/system/getty@tty1.service.d/override.conf`）

```ini
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin siro --noclear %I $TERM
Type=idle
```

### 設定 2: siro 使用者的 `~/.bash_profile`

```bash
# 不進 GUI 就會卡在這
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nolisten tcp
fi
```

### 設定 3: openbox autostart（`~/.config/openbox/autostart`）

```bash
#!/bin/bash

# 1. 隱藏滑鼠（觸控螢幕 5 秒沒動就隱藏）
unclutter --idle 5 -root &

# 2. 螢幕保護 — DPMS off / on
xset dpms 30 300 &     # 30 秒變暗、5 分鐘關
xset s 30 300 &        # X11 screen saver 同步

# 3. 啟動 Unity（單一應用、佔滿螢幕）
exec /opt/siro/unity/unity-runner.sh
```

### 設定 4: 鎖定輸入（`/etc/udev/rules.d/99-siro-kiosk.rules`）

```udev
# 鎖一般 USB 鍵盤（但保留觸控螢幕的 HID）
ACTION=="add", ATTRS{bInterfaceClass}=="03", ATTRS{idVendor}!="0eef", RUN+="/bin/sh -c 'echo 0 > /sys\$DEVPATH/../authorized'"

# 解鎖管理用鍵盤（管理員的特定型號）
ACTION=="add", ATTRS{idVendor}=="0eef", ATTRS{idProduct}=="0001", RUN+="/bin/sh -c 'echo 1 > /sys\$DEVPATH/../authorized'"
```

> 註：`idVendor=0eef idProduct=0001` 是預留的管理員鍵盤，量產前換成實際型號。

---

## 螢幕保護細節

| 觸發時間 | 動作 | 實作 |
|----------|------|------|
| 30 秒無互動 | 螢幕變暗（DPMS standby）| `xset dpms 30 300` |
| 5 分鐘無互動 | Live2D 切到待機動作 + 偶爾自言自語 | openbox hook → 發 D-Bus signal → Unity 收 |
| 10 分鐘無互動 | 螢幕關閉（DPMS off）| `xset dpms 30 300 600`（第三個參數是 off） |

### Unity 收 D-Bus signal 範例（Unity 端 Phase 4 實作）

```csharp
// 訂閱 com.siro.kiosk.IdleTimeout D-Bus signal
_sessionBus.Subscribe<IdleTimeoutSignal>(signal => {
    if (signal.Seconds >= 300) {
        Live2DModelController.Instance.PlayMotion("Idle");
    }
});
```

---

## Escape hatch（管理員解鎖）

| 解鎖方式 | 用途 | 觸發 |
|----------|------|------|
| 管理員鍵盤 | 維護 | USB 插入白名單型號自動解鎖 |
| 密碼輸入 | 緊急 | 在螢幕 4 角落按特定手勢（Phase 5 觸控校準後）|
| SSH 從另一台 | 遠端 | siro 帳號有 SSH key 認證，遠端改 kiosk 設定 |

---

## 驗證腳本 outline（Phase 4 實作）

```bash
#!/bin/bash
# os/kiosk/verify.sh

set -e

# 1. 確認 siro 使用者自動登入
sudo loginctl show-user siro | grep -q "State=active" || { echo "FAIL: siro not logged in"; exit 1; }

# 2. 確認 X11 跑起來
pgrep -x Xorg >/dev/null || { echo "FAIL: Xorg not running"; exit 1; }

# 3. 確認 openbox 跑起來
pgrep -x openbox >/dev/null || { echo "FAIL: openbox not running"; exit 1; }

# 4. 確認 Unity 是唯一全螢幕
wmctrl -l | grep -v "Unity" && { echo "FAIL: extra windows"; exit 1; }

# 5. 確認 30 秒後螢幕變暗
sleep 31
xset -q | grep -q "Standby: 30" || { echo "FAIL: DPMS not set"; exit 1; }

# 6. 確認管理員鍵盤能解鎖（用模擬事件）
echo "ALL PASS"
```

---

## 不在 Phase 4 範圍

- ❌ 觸控螢幕校準（Phase 5）
- ❌ 多螢幕支援（Phase 6+）
- ❌ 自動旋轉（直立 / 橫放，Phase 6+）
- ❌ 開機 splash / boot logo 客製（Phase 6+）

---

## Phase 4 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| getty 自動登入 + openbox autostart | 1 天 | 低（標準 Linux） |
| udev 鎖輸入 + 管理員白名單 | 1 天 | 中（udev 規則除錯） |
| DPMS 螢幕保護 + D-Bus 通知 | 1 天 | 中（Unity 端 hook） |
| 驗證腳本 | 0.5 天 | 低 |
| **總計** | **3.5 天** | — |
