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
