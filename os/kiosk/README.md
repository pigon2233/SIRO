# os/kiosk/ - Kiosk 模式設定

> Phase 4 實作。把 Ubuntu 桌面變成全螢幕 Unity，只能跑 SIRO，鎖住鍵盤滑鼠。

## 兩種 Kiosk 技術

### 選項 A: X11 + Openbox (v0.5，較熟悉)
- 開源、文件多、容易 debug
- `openbox` 是輕量 window manager
- 自動啟動 Unity：`~/.config/openbox/autostart`

### 選項 B: Wayland + Cage (v1+ 推薦)
- 現代、無 X11 歷史包袱
- `cage` 是專為 kiosk 設計的 Wayland compositor
- 啟動單一應用程式（Unity）

## v0.5 選 X11 + Openbox

理由：
- 文件多、踩坑少
- NVIDIA 驅動支援較成熟
- 之後要升級 Wayland 也容易

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

## 鎖定輸入

- 鍵盤：透過 systemd 屏蔽 USB 鍵盤（`udev` rule）
- 滑鼠：保留觸控螢幕功能，鎖一般 USB 滑鼠
- Escape hatch：密碼輸入可以解鎖（管理用）

## 螢幕保護

- 30 秒無互動 → 螢幕變暗（不鎖）
- 5 分鐘無互動 → Live2D 切到待機動作 + 偶爾自言自語（Hermes 排程）

## 不在 Phase 4 範圍

- 觸控螢幕校準（Phase 5）
- 多螢幕支援（Phase 6+）
- 自動旋轉（直立 / 橫放，Phase 6+）
