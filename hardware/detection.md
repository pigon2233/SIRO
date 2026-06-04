# 硬體偵測與驗證腳本

> 用於確認目標硬體是否符合 SIRO 需求。

---

## Windows 偵測（當前環境）

開 PowerShell，貼上：

```powershell
# 系統
Get-ComputerInfo -Property CsManufacturer,CsModel,CsSystemType

# CPU
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors

# RAM
Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum

# GPU
nvidia-smi
# 或
Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion

# 音效
Get-CimInstance Win32_SoundDevice | Select-Object Name,Status

# 視訊
Get-CimInstance Win32_PnPEntity | Where-Object {$_.PNPClass -eq "Camera"} | Select-Object Name

# 儲存
Get-PhysicalDisk | Select-Object FriendlyName,MediaType,Size

# 網路
Get-NetAdapter | Select-Object Name,InterfaceDescription,LinkSpeed
```

預期輸出（這台 G713QC）：

```
系統: ASUSTeK COMPUTER INC. ROG Strix G713QC_G713QC
CPU:  AMD Ryzen 9 5900HX with Radeon Graphics, 8 cores, 16 threads
RAM:  ~16 GB
GPU:  NVIDIA GeForce RTX 3050, 4096 MB VRAM, Driver 595.79, CUDA 13.2
```

---

## Linux 偵測（Phase 4 用）

裝好 Ubuntu 後跑：

```bash
# 系統
sudo lshw -short
# 或
sudo dmidecode -t system

# CPU
lscpu

# RAM
free -h
cat /proc/meminfo

# GPU
lspci | grep -i vga
nvidia-smi  # 需要 NVIDIA driver

# 音效
aplay -l   # 列出輸出
arecord -l # 列出輸入
lspci | grep -i audio

# 視訊
ls /dev/video*
v4l2-ctl --list-devices  # 需要 v4l-utils

# 儲存
lsblk
df -h

# 網路
ip link
iw dev  # Wi-Fi

# 溫度
sensors  # 需要 lm-sensors
```

把輸出存到 `hardware/reports/<date>-<hostname>.txt`，方便比對。

---

## 相容性檢查清單

裝 Ubuntu 24.04 LTS 後，跑這個清單確認能跑 SIRO：

### 基本
- [ ] 開機到登入畫面
- [ ] 網路連線（ping 8.8.8.8）
- [ ] Wi-Fi 連線（如果用無線）
- [ ] 音效輸入（arecord 5 秒測試）
- [ ] 音效輸出（aplay 測試音）
- [ ] 視訊鏡頭（cheese 軟體打開能看）
- [ ] 觸控板手勢
- [ ] 鍵盤輸入
- [ ] 螢幕亮度可調
- [ ] suspend / resume

### GPU
- [ ] `nvidia-smi` 顯示 GPU
- [ ] 解析度正確
- [ ] Vulkan / OpenGL 測試（`glxinfo` 或 `vulkaninfo`）
- [ ] CUDA 範例跑得起來

### 進階（Phase 5 才需要）
- [ ] 麥克風 1-3 米收音（用 audacity 錄一段比對）
- [ ] 視訊 1-3 米人臉偵測（用 OpenCV 範例）
- [ ] 觸控螢幕（如果有）多點觸控
- [ ] 風扇曲線（sensors 監控 + 手動轉速）
- [ ] 電池充放電（如果有）

---

## 已知問題與 workaround

### 1. ASUS ROG 鍵盤 RGB 在 Linux 不亮

不影響功能。BIOS 設成「Static」可繞過。

### 2. NVIDIA Optimus 切換

筆電有內顯 + 獨顯，Ubuntu 24.04 預設用內顯。
- 想強制獨顯：`__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia <command>`
- 或設 `nvidia-prime` 預設

Phase 4 評估要不要強制獨顯（影響 LLM 推論效能）。

### 3. 風扇很吵

- `tlp` + `thinkpad_acpi`（ASUS 不完全支援）
- 或用 `fancontrol`（lm-sensors 設定）
- 接受噪音也是選項

### 4. 觸控板手勢

`libinput` 支援大部分手勢。三指、四指手勢要單獨設定。

### 5. suspend 耗電

預設 s2idle，開機恢復快但有耗電。
- 改 s3 deep sleep：`mem_sleep_default=deep` kernel param
- 但有些硬體 s3 不穩

### 6. 視訊鏡頭隱私

Linux 沒有 webcam 燈強制開啟的軟體。
- 實體貼紙遮住（推薦）
- 或在硬體設定裡看有沒有 LED 控制

---

## 不在偵測範圍

- 螢幕色準（不重要，SIRO 是 UI 不是印刷）
- 音訊 DAC 品質（內建足夠）
- 鍵盤機械軸壽命（普通使用沒問題）
- 電池循環次數（如果只用 AC）

---

## 自動驗證腳本（`hardware/verify-hardware.sh`）

把上面的相容性清單變成可跑的 shell script，回傳 0 = 全部過、非 0 = 有失敗。

```bash
#!/bin/bash
# hardware/verify-hardware.sh
# SIRO 硬體相容性自動驗證
# 回傳：0 = 全部過、1 = 有失敗
# 輸出：human-readable log + JSON report

set -uo pipefail

REPORT_DIR="hardware/reports/$(date +%Y%m%d-%H%M%S)-$(hostname)"
mkdir -p "$REPORT_DIR"
LOG="$REPORT_DIR/verify.log"
JSON="$REPORT_DIR/verify.json"

PASS=0
FAIL=0
WARN=0
declare -A RESULTS

log() { echo "$@" | tee -a "$LOG"; }
pass() { log "✅ $1"; RESULTS["$1"]="pass"; PASS=$((PASS+1)); }
fail() { log "❌ $1 — $2"; RESULTS["$1"]="fail: $2"; FAIL=$((FAIL+1)); }
warn() { log "⚠️  $1 — $2"; RESULTS["$1"]="warn: $2"; WARN=$((WARN+1)); }

log "=== SIRO 硬體驗證 $(date) ==="
log "主機: $(hostname)"
log "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"

# ===== 基本 =====
log ""
log "--- 基本 ---"

# 網路
if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
    pass "network_connectivity"
else
    fail "network_connectivity" "ping 8.8.8.8 失敗"
fi

# Wi-Fi
if iw dev 2>/dev/null | grep -q "Interface"; then
    pass "wifi_available"
else
    warn "wifi_available" "沒 Wi-Fi 介面（用有線也 OK）"
fi

# 音效輸入
if arecord -l 2>/dev/null | grep -q "card"; then
    pass "audio_input"
    arecord -l >> "$LOG" 2>&1
else
    fail "audio_input" "找不到麥克風裝置"
fi

# 音效輸出
if aplay -l 2>/dev/null | grep -q "card"; then
    pass "audio_output"
    aplay -l >> "$LOG" 2>&1
else
    fail "audio_output" "找不到喇叭裝置"
fi

# 視訊
if ls /dev/video* >/dev/null 2>&1; then
    pass "video_device"
    v4l2-ctl --list-devices >> "$LOG" 2>&1
else
    fail "video_device" "找不到 /dev/video* 裝置"
fi

# suspend / resume
if command -v systemctl >/dev/null && systemctl suspend-test 2>/dev/null; then
    pass "suspend_resume"
else
    warn "suspend_resume" "需要手動測（systemctl suspend → wake）"
fi

# ===== GPU =====
log ""
log "--- GPU ---"

if command -v nvidia-smi >/dev/null 2>&1; then
    VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
    if [ "$VRAM" -ge 4096 ]; then
        pass "nvidia_gpu_vram_4gb+"
    else
        warn "nvidia_gpu_vram_4gb+" "VRAM 只有 ${VRAM}MB（推薦 >= 4096）"
    fi
    nvidia-smi >> "$LOG" 2>&1
else
    fail "nvidia_gpu" "nvidia-smi 找不到（NVIDIA driver 沒裝？）"
fi

# Vulkan / OpenGL
if command -v vulkaninfo >/dev/null 2>&1; then
    pass "vulkan"
elif command -v glxinfo >/dev/null 2>&1; then
    pass "opengl"
else
    warn "gpu_api" "vulkaninfo / glxinfo 都找不到"
fi

# ===== 進階（Phase 5）=====
log ""
log "--- 進階 (Phase 5) ---"

# 麥克風 1-3 米收音
if [ -f hardware/test-mic-quality.sh ]; then
    if bash hardware/test-mic-quality.sh >> "$LOG" 2>&1; then
        pass "mic_long_range"
    else
        warn "mic_long_range" "需要手動驗（1-3 米距離說話）"
    fi
fi

# 視訊 1-3 米人臉偵測
if [ -f hardware/test-face-detection.sh ]; then
    if bash hardware/test-face-detection.sh >> "$LOG" 2>&1; then
        pass "face_detection_long_range"
    else
        warn "face_detection_long_range" "需要手動驗"
    fi
fi

# 溫度感測器
if command -v sensors >/dev/null 2>&1; then
    CPU_TEMP=$(sensors 2>/dev/null | grep -E "Tdie|Tctl|Package" | head -1 | grep -oE "[0-9]+\.[0-9]+°C" | head -1)
    if [ -n "$CPU_TEMP" ]; then
        pass "temperature_sensor"
        log "  當前 CPU 溫度: $CPU_TEMP"
    fi
else
    warn "temperature_sensor" "lm-sensors 沒裝（sudo apt install lm-sensors）"
fi

# ===== 總結 =====
log ""
log "=== 結果 ==="
log "Pass: $PASS"
log "Fail: $FAIL"
log "Warn: $WARN"

# 寫 JSON report
cat > "$JSON" <<EOF
{
  "host": "$(hostname)",
  "timestamp": "$(date -Iseconds)",
  "pass": $PASS,
  "fail": $FAIL,
  "warn": $WARN,
  "results": {
$(for key in "${!RESULTS[@]}"; do
    echo "    \"$key\": \"${RESULTS[$key]}\","
done | sed '$ s/,$//')
  }
}
EOF

log ""
log "Report 寫入: $REPORT_DIR"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
```

執行：
```bash
chmod +x hardware/verify-hardware.sh
sudo bash hardware/verify-hardware.sh
# 輸出在 hardware/reports/<timestamp>-<hostname>/verify.log
```

---

## 報告存檔 SOP

每次跑 verify-hardware.sh 會自動建一個目錄：

```
hardware/reports/
├── 20260604-143000-siro-dev/
│   ├── verify.log          # 人讀的 log
│   ├── verify.json         # machine-readable
│   └── nvidia-smi.txt      # 額外資訊（自動收集）
├── 20260604-180000-siro-test/
│   ├── ...
```

### 跨機器比較

```bash
# 看所有機器的驗證結果
for d in hardware/reports/*/; do
    echo "=== $(basename $d) ==="
    cat "$d/verify.json" | python3 -m json.tool
done
```

---

## 跟 PLAN.md KPI 對應

| 驗證項目 | 對應 KPI | 失敗影響 |
|----------|----------|----------|
| `nvidia_gpu_vram_4gb+` | 對話品質（K2 K9）| 本地 LLM 跑不起來 |
| `audio_input` + `audio_output` | 雙向對話（K6）| 沒語音功能 |
| `video_device` | 人臉追蹤（Phase 5）| 沒主動喚醒 |
| `temperature_sensor` | 穩定（K3）| 沒過熱監控 |
| `network_connectivity` | 所有 LLM 呼叫（K2）| 沒雲端 LLM |

---

## Phase 5 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| verify-hardware.sh 撰寫 | 1 天 | 低 |
| test-mic-quality.sh 子腳本 | 0.5 天 | 中（SNR 自動判斷難）|
| test-face-detection.sh 子腳本 | 0.5 天 | 中（要 Python + OpenCV）|
| 報告存檔 + 跨機器比較工具 | 0.5 天 | 低 |
| CI 整合（每次新機跑一次）| 1 天 | 低 |
| **總計** | **3.5 天** | — |

完整硬體 / OS / 監控 / 備份 / 安全 / 改裝的總時程（os/ + hardware/）：

- **Phase 4 (Linux 客製化)**：kiosk 3.5 + systemd 4 + security 4 = **11.5 天**
- **Phase 5 (硬體整合)**：assembly 4.5 + audio 6.5 + video 6.5 + detection 3.5 = **21 天**
- **Phase 6 (部署與營運)**：monitoring 7 + backup 3 = **10 天**
- **總計**：**42.5 天實作**（不含 v2+ / 客製硬體）|
