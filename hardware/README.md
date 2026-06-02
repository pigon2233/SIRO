# hardware/ - 硬體規格與相容性

> SIRO 目標硬體的規格、Linux 相容性、特殊考量。
> 對應計畫書的 [Phase 4](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-4-linux-客製化) / [Phase 5](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-5-硬體整合)。

---

## 當前開發機：ASUS ROG Strix G713QC

這是計畫書 v0.1 開發的目標硬體。

### 規格

| 元件 | 規格 | SIRO 適合度 |
|------|------|------------|
| **CPU** | AMD Ryzen 9 5900HX (8 cores, 16 threads) | ⭐⭐⭐⭐⭐ 完美 |
| **RAM** | 16GB DDR4 | ⭐⭐⭐⭐ 足夠 |
| **GPU** | NVIDIA GeForce RTX 3050 4GB VRAM | ⭐⭐⭐ 跑小模型 OK，跑 7B Q4 會 OOM |
| **顯示** | 17.3" 1080p (估) | ⭐⭐⭐⭐ 適合 |
| **儲存** | (待確認) | - |
| **音效** | (待確認) | - |
| **網路** | Wi-Fi 6 + GbE (估) | ⭐⭐⭐⭐⭐ 完美 |
| **OS** | Windows 11 Home | ⭐⭐ 過渡，最終要 Linux |

### VRAM 4GB 的限制與對策

| 模型 | 量化 | VRAM 需求 | 跑得起來嗎 |
|------|------|-----------|------------|
| Llama 3.2 1B | Q4 | ~1.5GB | ✅ 輕鬆 |
| Llama 3.2 3B | Q4 | ~2.5GB | ✅ OK |
| Mistral 7B | Q4 | ~5GB | ❌ 會 OOM |
| Mistral 7B | Q2 | ~3.5GB | ⚠️ 勉強 |
| Llama 3 8B | Q4 | ~5.5GB | ❌ |
| Phi-3 Mini (3.8B) | Q4 | ~3GB | ✅ OK |

**建議**：
- **本地預設模型**：Llama 3.2 3B Q4（品質夠用、跑得動）
- **品質模式**（犧牲速度）：用 CPU 跑 7B Q4（10-20 秒回應）
- **最高品質**：走雲端 API（Nous Portal / OpenRouter / Anthropic）

**Phase 1 開始用 Ollama 跑 Llama 3.2 3B Q4，測試體驗後再決定**。

### Linux 相容性（Phase 4 規劃）

| 元件 | Ubuntu 24.04 狀態 | 備註 |
|------|-------------------|------|
| AMD Ryzen 9 5900HX | ✅ 完美 | 開箱即用 |
| NVIDIA RTX 3050 | ✅ 完美 | 需裝 proprietary driver |
| Wi-Fi 6 (MediaTek MT7921?) | ⚠️ 需測試 | 6E 晶片偶有問題 |
| 鍵盤 RGB (Aura Sync) | ❌ 無 Linux 支援 | 鍵盤能用，燈光不亮 |
| 觸控板 | ✅ 完美 | `libinput` 處理 |
| 視訊鏡頭 | ✅ 完美 | UVC 標準 |
| 內建麥克風 | ✅ 完美 | HDA codec |
| 內建喇叭 | ✅ 完美 | HDA codec |
| 電源管理 | ⚠️ 部分 | `tlp` 處理基本，特殊模式要調 |
| 風扇控制 | ⚠️ 需 asus-nb-wmi | 開源驅動，但效果有限 |

### 雙系統規劃

**選項 A：保留 Windows + 加 Ubuntu（推薦 v0 開發期）**
- 縮 Windows 分割區 200-300GB
- 用 Ubuntu 安裝光碟的「Install alongside Windows 10」
- GRUB 開機選單選系統
- 優點：Windows 還能用（緊急 debug、文書處理）
- 缺點：磁碟空間要分配

**選項 B：完全 Linux 化（v1 正式版）**
- 備份 Windows 分割區（如有需要）
- 全碟裝 Ubuntu
- 之後裝 dual boot 要用 WoeUSB 重做

**選項 C：兩顆 SSD（如果有第二顆 M.2）**
- 一顆 Windows、一顆 Linux
- BIOS 切換
- 最乾淨但需要硬體支援

**目前推薦**：選項 A，雙系統 + GRUB。

---

## 為什麼不選其他硬體

### 為什麼不用 Raspberry Pi
- 沒有 NVIDIA 顯卡 → 不能跑本地 LLM（要 CPU 推論超慢）
- 8GB RAM 對 SIRO 吃緊
- 雖然省電但 v0/v1 性能不夠

### 為什麼不用 Mac Mini
- Apple Silicon 上跑 Linux（Asahi）仍在發展
- 換硬體成本高
- Linux 套件對 ARM Mac 支援不完整

### 為什麼不用 Intel NUC
- 沒有獨顯（Intel UHD 不夠跑 LLM）
- 要外接 eGPU 太複雜

### 為什麼不用雲端 VM
- v0 階段要快速迭代
- 網路延遲影響體驗
- 雲端費用

---

## 推薦硬體清單（之後買給親友用）

如果之後要部署到 2-10 台，推薦同級或更好的：

| 等級 | 規格 | 預估價格 (TWD) |
|------|------|----------------|
| **最低** | Ryzen 7 / i7, 16GB, RTX 3060 6GB | ~30,000 |
| **推薦** | Ryzen 9 / i9, 32GB, RTX 4070 8GB | ~50,000 |
| **理想** | Ryzen 9, 64GB, RTX 4080 12GB+ | ~80,000 |

更高等級：能跑更大的本地模型（13B Q4、Mixtral）。

---

## 硬體相關 Phase 對應

| Phase | 硬體工作 |
|-------|----------|
| **Phase 1** | 用 Windows 開發，不動硬體 |
| **Phase 2** | 仍在 Windows |
| **Phase 3** | 仍在 Windows（Rust 可在 Windows 編譯） |
| **Phase 4** | 裝 Ubuntu Server 24.04 LTS（雙系統） |
| **Phase 5** | 配音訊 / 視訊 / 觸控（如果有） |
| **Phase 6** | 燒 base image、Packer 自動化 |

---

## 不在計畫範圍

- 觸控螢幕（v0 不考慮，要看 Phase 5 評估）
- 行動裝置 / 平板（v2+）
- VR / AR（永遠不做）
- 客製化硬體（永遠不做）
