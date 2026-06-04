# 改裝與組裝指南（Phase 5）

> 怎麼把筆電變成 SIRO 陪伴裝置。

---

## 改裝目標

把 ASUS ROG Strix G713QC 從「一般筆電」變成「SIRO 裝置」：

- 隱藏 / 移除不需要的輸入設備
- 固定成直立式
- 美觀整合
- 散熱優化

---

## 硬體改造選項

### 選項 A：保留筆電外觀，軟體鎖輸入

- **最簡單**：不改硬體，靠 OS 鎖鍵盤滑鼠
- **優點**：可逆、便宜、零風險
- **缺點**：鍵盤燈光還在、視覺上像筆電
- **推薦 v0.5 / v1 開發期用**

### 選項 B：直立式支架

- 買個筆電直立架（Amazon 很多）
- 把筆電直立放置，HDMI / 螢幕線接外接螢幕
- 蓋上螢幕（用外接螢幕操作）
- 鍵盤自然被擋住
- 散熱要注意（直立可能影響進氣口）
- **推薦 v1 試用期用**

### 選項 C：拆機改裝（進階）

- 拆開筆電，移除鍵盤排線
- 移除觸控板排線
- 移除螢幕（用外接）
- 整台塞進自製外殼
- **優點**：最像「裝置」、最簡潔
- **缺點**：破壞保固、不可逆、需要技術
- **不推薦 v0/v1**

### 選項 D：外殼 3D 列印

- 設計專屬外殼（CAD 軟體）
- 留出進氣口、視訊鏡頭孔
- 內建喇叭開口
- 隱藏所有按鍵
- **v2+ 才考慮**

---

## 推薦直立架規格

Amazon / 蝦皮搜尋「直立筆電架」：

- 高度：12 吋筆電都能放
- 寬度：17 吋要確認
- 通風：底部 / 後方要有開孔
- 材質：金屬（散熱佳）> 塑膠

範例需求：
- 預算：NT$500-1500
- 散熱：被動散熱座優先

---

## 散熱管理

### 問題

筆電高負載（Unity + LLM 推論）會：
- CPU 90°C+ 
- 風扇全速（吵）
- 熱節流（效能下降）

### 解法

| 解法 | 成本 | 效果 |
|------|------|------|
| 散熱膏升級 | NT$300 | ⭐⭐ 降 5-10°C |
| 散熱底座（風扇） | NT$500-2000 | ⭐⭐⭐ 降 10-15°C |
| 改水冷（進階） | NT$3000+ | ⭐⭐⭐⭐ 降 20°C+ |
| 降頻 + 限制功耗 | NT$0 | ⭐⭐ 不過熱 |
| 直立 + 開側蓋 | NT$0 | ⭐⭐ 通風改善 |

**推薦 v1**：散熱底座 + 軟體限制（不要 100% 跑滿）。

### 軟體限制

```bash
# 限制 CPU 頻率
echo 80 > /sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq

# NVIDIA 限制
sudo nvidia-smi -pl 60  # 限制 60W（原本 95W）

# systemd service
cat > /etc/systemd/system/siro-power-limit.service <<EOF
[Unit]
Description=SIRO power limit
After=nvidia-persistenced.service

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-smi -pl 60

[Install]
WantedBy=multi-user.target
EOF
```

---

## 視訊鏡頭

內建視訊朝螢幕方向。
直立放置時，視訊鏡頭可能朝側面或下方。

### 解決方案

- 旋轉筆電方向讓視訊鏡頭朝使用者
- 或外接 USB 視訊

外接視訊推薦：
- Logitech C920 / C922（Linux 友善）
- 或 ReSpeaker 系列（帶麥克風陣列）

---

## 音效

內建喇叭朝下或側面，直立後效果可能變差。

### 測試

- 播放音樂測試音量
- 用 `pavucontrol` 檢查輸出

### 解決方案

- 外接藍牙喇叭（注意延遲）
- 外接 USB 喇叭
- 接受音量小的事實

---

## 電源與線材

### 必備

- 變壓器（原本就有）
- HDMI / DP 線（接外接螢幕）
- USB 線（接外接視訊 / 麥克風）

### 線材整理

- 用 cable tie 整理
- 桌面鑽孔（如果永久裝置）
- 走線槽（牆面用）

### 開機自動

BIOS 設成「AC 接上自動開機」：
- ASUS 筆電：`Advanced → AC Power Recovery → Power On`
- 或 `ErP Ready` 設為 Disabled

---

## 環境擺放

### 桌面擺放

- 螢幕：眼睛平視高度（避免脖子痠）
- 距離：1-1.5 米
- 光源：避免背光（會讓視訊鏡頭看不清楚）
- 麥克風：對著嘴巴方向

### 牆面 / 嵌入

Phase 6+ 才考慮。固定架 + 美觀整合。

---

## 不在 Phase 5 改裝範圍

- ❌ 換主機板 / CPU
- ❌ 加 RAM 到 32GB+（之後再說）
- ❌ 換更大的 SSD
- ❌ 客製 PCB
- ❌ 加電池（如果原本是純 AC）

這些都是 Phase 6+ 或 v2+ 才考慮。

---

## 推薦硬體型號（具體可買）

| 項目 | 型號 | 價位 (TWD) | 理由 |
|------|------|-----------|------|
| 直立筆電架 | ACCURITE 金屬直立架 17 吋 | ~800 | 通風好、穩固、支援 17 吋 |
| 散熱底座 | Cooler Master NotePal X-Slim | ~1500 | 大風扇、安靜、17 吋相容 |
| 散熱膏 | Thermal Grizzly Kryonaut | ~500 | 導熱係數高、CPU 降 5-10°C |
| 外接視訊 | Logitech C920 / C922 | ~2000 | Linux 友善、UVC 標準、1080p |
| 外接麥克風 | ReSpeaker USB Mic Array v2.0 | ~3500 | 4 麥克風陣列 + DSP 處理 |
| 外接喇叭 | Creative Pebble V3 (USB) | ~1500 | USB 供電 + 3.5mm，省桌面空間 |

---

## Phase 5 改裝 SOP（v1 推薦路徑：選項 B 直立架 + 散熱底座）

### Day 1: 硬體擺放

1. 筆電關機、拔電
2. 裝進直立架
3. HDMI 線接外接螢幕（如果有，沒有的話蓋上筆電螢幕）
4. USB 線接外接視訊 / 麥克風
5. 變壓器接上

### Day 2: BIOS 設定

1. 開機進 BIOS（F2 / Del）
2. `Advanced → AC Power Recovery → Power On`
3. `ErP Ready → Disabled`
4. 存檔重啟

### Day 3: 軟體限制

```bash
# 限制 NVIDIA 功耗
sudo nvidia-smi -pl 60

# 安裝 siro-power-limit systemd service
sudo cp os/systemd/siro-power-limit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now siro-power-limit.service

# 確認
systemctl status siro-power-limit.service
nvidia-smi -q -d POWER | grep "Power Limit"
```

### Day 4: 散熱膏升級（選配）

> ⚠️ 開筆電會破壞保固、量產前不要做

1. 拆後蓋（螺絲起子）
2. 舊散熱膏擦掉（酒精 + 紙巾）
3. 塗新散熱膏（薄薄一層、十字或點狀）
4. 鎖回後蓋

---

## 驗證腳本（`hardware/verify-assembly.sh`）

```bash
#!/bin/bash
set -e

# 1. 確認 AC Power Recovery 啟用
sudo dmidecode -s bios-version
# 確認 BIOS 有「Power On after AC loss」設定

# 2. 確認 NVIDIA 功耗限制
nvidia-smi -q -d POWER | grep "Power Limit" | grep "60.00 W"
# 預期：Power Limit 顯示 60W（原本 95W）

# 3. 確認 systemd service
systemctl is-active siro-power-limit.service

# 4. 監控溫度（跑 5 分鐘 Unity + LLM 推論）
timeout 300 watch -n 5 'sensors | grep "Tdie\|Tctl"'
# 預期：CPU 溫度 < 85°C（沒降頻）

echo "ALL PASS"
```

---

## Phase 5 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| 直立架 + 散熱底座 + BIOS 設定 | 1 天 | 低 |
| 軟體限制（NVIDIA + systemd）| 0.5 天 | 低 |
| 散熱膏升級（選配）| 1 天 | 中（破保固 + 拆機風險）|
| 外接視訊 / 麥克風 / 喇叭 整合 | 1 天 | 中（V4L2 + PulseAudio 設定）|
| 驗證腳本 + 燒機測試 | 1 天 | 低 |
| **總計** | **4.5 天** | — |
