# SIRO 計畫審查 v0.3

> **產出時間**：2026-06-04
> **對應**：
> - 主計畫書 `LIVE2D_AI_AGENT_OS_PLAN.md`（v2.0 2026-06-02）— **不動**
> - 修訂建議 `docs/PLAN_REVISION_v2.1.md`（2026-06-04，15 項）
> - 架構文件 `docs/ARCHITECTURE.md` v2.0、`docs/AGENT_OS.md` v0.2、`docs/STRATEGIC_NOTES.md` v0.2
> **本檔目的**：v2.1 之外補 4 個問題 + 6 個跨文件衝突 + Phase 3 詳細規劃
> **方法論**：使用者 2026-06-04 看完 PLAN_REVISION_v2.1 後說「我們小看作業系統了」+「整理完現有的內容再做更動」

---

## 你的回饋（2026-06-04）

| 項 | 回饋 | 對 v2.1 的影響 |
|---|---|---|
| **A** | **不繞過 hermes** | v2.1 #1（Streaming）跟 #5（廠商鎖定）都建議繞過 hermes — **v0.3 不採用**。hermes 是 LLM 抽象層，保留。Streaming 如果要，透過 hermes 的另一介面（gateway）做 |
| **B** | **OS 沒錯** | 撤回 v2.1 #11「v0.x 只是 app」立場。**SIRO 從一開始就是 OS，不是「先做 app v2.0 才轉 OS」**。這影響 v2.1 的 1.5 節、判斷標準清單 — 全部刪掉 |
| **C** | 同意 | v0.3 路線圖先走「整理 → 修訂文件 → 動 code」 |
| **D** | 同意 | `STATUS.md` 跟 v2.1 phase 編號對齊 |
| **E** | `os/` 跟 `hardware/` 只有 README 是對的（Phase 3 還沒做），**但要先把 Phase 3 詳細規劃寫出來** | v0.3 補：Phase 3 詳細規劃（見下方） |
| **F** | 主計畫書不直接動 | 所有修訂都先寫在 review 文件，通過了再說 |

---

## v2.1 修訂 v0.3 增補

### #16 — AgentOS 寫了但沒被任何 endpoint 用 🟠 高

**問題**：
v0.2 寫了 `bridge/agent_os.py` 跟 `bridge/tasks/llm_reply_task.py`（commit `f56c4e2`），但 `main.py` 的 `/chat` 跟 `/ws` 還是用**舊的 sync 流程**。

AgentOS 是「待機」狀態沒人用 — 之後接 Telegram / 排程時會發現「task 寫了但 endpoint 不會 enqueue」。

**修訂**：
- v0.3 立刻把 `/chat` 改成：
  1. 建 `llm_reply_task` 物件
  2. `state.agent_os.enqueue(task)`
  3. await `event_bus.wait_for("task.completed", task_name="llm.reply")` 等結果
  4. 用結果回 Unity
- `/ws` 同樣
- **保留向後相容**：也保留舊 sync 路徑，env flag `SIRO_USE_AGENT_OS=true` 才走新路徑
- 修訂文件 `docs/AGENT_OS.md` 「現況」段

### #17 — `is_available()` 同步卡 event loop 🟠 高

**問題**：
`main.py:359, 456, 563` 都有 sync `state.hermes.is_available()` 跟 `state.ollama.is_available()` 在 async path 跑。每次 request 都額外卡 0.5-10s 同步 subprocess / urllib。

**這就是「60s 中間卡住」的元凶之一** — hermes 直接 CLI 很快是因為 hermes 沒這層重複 is_available。

**修訂**：
- v0.2.1 立刻修：5 秒 TTL cache 拿掉 sync 呼叫
  - `HermesClient._cached_available` + `_last_check_ts`（5 秒）
  - `OllamaClient._cached_available` + `_last_check_ts`（5 秒）
- 預期改善：第一次 1-2s、接下來 4.99 秒內 0s overhead

### #18 — `STRATEGIC_NOTES.md` 跟 v2.1 對齊 🟡 中

**問題**：
STRATEGIC_NOTES.md 提的「Q2 Streaming 繞過 hermes 直接打 MiniMax-M3」跟 v2.1 #1 + #5 重疊但沒交叉引用。**而且你 A 案已否決繞過 hermes**，STRATEGIC_NOTES 還停留在舊結論。

**修訂**：
- 刪 STRATEGIC_NOTES 「Q2 Streaming 繞過 hermes」這條
- 改成「Q2 透過 hermes gateway 做 streaming」（如果 hermes 支援的話；現況待確認）
- 加 cross-reference 區塊指向 PLAN_REVIEW_v0.3

### #19 — `AGENT_OS.md` v0.2 範圍過時 🟡 中

**問題**：
AGENT_OS.md 寫的「v0.2 範圍」沒寫「現在的 /chat 還沒接 AgentOS」這個關鍵現況。讀文件的人會以為 AgentOS 已經 production。

**修訂**：
- AGENT_OS.md 加「**現況**」段：AgentOS 是骨架，第一個 task `llm_reply_task` 還沒被任何 endpoint 用
- v0.3 補做 #16 才有 production 級的 AgentOS 整合

---

## 跨文件衝突修訂

### A. `DECISIONS.md #001` Hermes 鎖定問題 🟡 中

**衝突**：
- DECISIONS.md #001 寫「選 Hermes Agent 因為不鎖 LLM、支援 300+ 模型」
- v2.1 #5 說 Hermes CLI 不支援 streaming = 廠商鎖定
- 你的 A 案：保留 hermes 不繞過

**修訂**：
- DECISIONS.md #001 加註：「v0.2 觀察 — Hermes CLI 雖支援多模型但缺少 streaming。Streaming 走 hermes gateway（v0.3 評估）。」

### B. `ARCHITECTURE.md` v2.0 vs v0.3 🟠 高

**衝突**：
- ARCHITECTURE.md 還在 v2.0 規劃「Linux + Rust + Python + Unity」4 層
- 你的 B 案：OS 願景保留
- 但 v0.2 還沒做 Linux 雙系統

**修訂**：
- ARCHITECTURE.md 標頭改「v0.3 願景 — 4 層架構保留 OS 願景，v0.x 簡化實作為 2 層 (Unity + Python)，Phase 3+ 補齊其他層」
- 註腳：`os/`、`hardware/` 內容是 v2.0+ 願景，v0.x 不會動

### C. `STATUS.md` 跟 v2.1 phase 編號 🟡 中

**衝突**：
- STATUS.md 寫「Phase 2 進行中」是 PLAN.md v2.0 編號
- v2.1 改 Phase 順序

**修訂**：
- STATUS.md 改用新編號：
  - v0.2 AgentOS 骨架 ✅
  - v0.2.1 is_available cache（#17）
  - v0.3 第一個 task 接 endpoint（#16）
  - v0.4 Streaming（透過 hermes gateway）
  - v0.5 視覺強化
  - v1.0+ 多工觸發源（Telegram / 排程）
  - v2.0+ Rust OS

### D. `SETUP_NOTES.md` 各 Phase 缺 KPI 🟡 中

**修訂**：
- SETUP_NOTES 各 Phase 加「驗證命令」段（KPI 量化）
- 引用 v2.1 #4 + STATUS.md 的 K1-K7

### E. `os/` `hardware/` Phase 3 詳細規劃 🟠 高

**現況**：
- `os/` 11 個子目錄（systemd、kiosk、audio、video、network、power、security、backup、monitoring、install）都只有 README
- `hardware/` 5 個檔（README、assembly、audio、detection、video）

**Phase 3 詳細規劃（要做什麼、不做什麼）：**

```yaml
phase_3_os_layer:
  v0.x 範圍: 純 v0.x 不做（v2.0+ 才做）
  
  範圍拆解:
    os-runtime/siro-runtime:        # Rust supervisor
      功能: 監控所有服務、bridge watchdog、硬體抽象
      不做: systemd unit、IPC server
      v0.x: 只在 WSL2 試跑 siro-runtime binary，不部署
      v1.x: Rust 重寫 siro-runtime，systemd 整合
      v2.0: 取代 systemd，siro-runtime 為唯一 supervisor
    
    os/systemd:                    # systemd unit
      v1.x: 寫 bridge.service、unity.service
      v2.0+: systemd 被 siro-runtime 取代（保留向後相容）
      
    os/kiosk:                     # 全螢幕 kiosk
      v1.x: Ubuntu + LightDM + Mao 開機自動全螢幕
      v2.0+: Wayland + 自家 compositor（不靠 X11/Wayland 標準）
      
    os/audio:                     # 音訊抽象
      v1.x: PulseAudio / PipeWire wrapper
      v2.0+: 自家音訊 daemon（低延遲給 TTS）
      
    os/video:                     # 視訊抽象
      v1.x: OpenGL 直通、VAAPI
      v2.0+: 自家 compositor 整合
      
    os/network:                   # 網路管理
      v1.x: NetworkManager wrapper、kiosk 網路設定
      v2.0+: 自家 netd
      
    os/power:                     # 電源管理
      v1.x: systemd-logind 整合
      v2.0+: 自家 powerd（與硬體溝通）
      
    os/security:                  # 安全性
      v1.x: AppArmor、SELinux profile
      v2.0+: 自家 sandbox（Rust）
      
    os/backup:                    # 備份
      v1.x: btrfs snapshot + 雲端 sync
      v2.0+: 自家 backupd（增量 + 加密）
      
    os/monitoring:                # 監控
      v1.x: Prometheus + Grafana
      v2.0+: 自家 observability daemon
    
    os/install:                   # 安裝
      v1.x: Packer image + cloud-init
      v2.0+: 增量 OTA（自家 protocol）
  
  hardware/:
    hardware/assembly:            # 硬體組裝指南
      v1.x: 寫 SIRO Box v1 組裝手冊（kiosk 機殼 + 觸控螢幕 + 喇叭 + 麥克風）
      v2.0+: SIRO Box v2（自製 PCB、整合喇叭）
    
    hardware/audio:               # 音訊硬體
      v1.x: USB DAC + 喇叭清單
      v2.0+: I2S 整合
    
    hardware/video:               # 視訊硬體
      v1.x: 觸控螢幕清單
      v2.0+: eDP 整合
    
    hardware/detection:           # 硬體偵測
      v1.x: udev rules、PCI/USB 自動偵測
      v2.0+: 自家硬體 discovery
```

**STATUS 區分**：
- v0.x：`os/` 跟 `hardware/` 只放 README 說明 Phase 3 規劃
- v1.x：補上 systemd unit、Packer 設定、硬體清單
- v2.0+：自寫 daemon（siro-runtime、compositor、netd 等）

### F. 主計畫書不直接動 🟠 高（**你決定**）

**修訂**：
- **不動** `LIVE2D_AI_AGENT_OS_PLAN.md`
- 所有修訂（v2.1 + v0.3 增補）整理在 `docs/PLAN_REVIEW_v0.3.md`（本檔）
- 經過你 review 通過後，再決定要不要 merge 回主計畫書
- 主計畫書的更新策略：v3.0 才合併（一次大改版）

---

## 給未來自己的修訂清單（整理完才動手）

| 優先 | 項目 | 動作 | commit 名 |
|---|---|---|---|
| 🔴 | #17 is_available cache 5s | 修 `bridge/hermes_client.py` + `bridge/ollama_client.py` | `fix(perf): is_available 5s cache 拿掉 hot path sync subprocess` |
| 🔴 | A. STRATEGIC_NOTES 改 Q2 結論 | 改文件 | `docs: STRATEGIC_NOTES Q2 改走 hermes gateway 不繞過` |
| 🟠 | #19 AGENT_OS.md 補現況段 | 改文件 | `docs: AGENT_OS.md 加現況 — task 還沒被 endpoint 用` |
| 🟠 | C. STATUS.md 改 v0.x 編號 | 改文件 | `docs: STATUS.md 改用 v0.x 編號對齊 v2.1 路線圖` |
| 🟠 | D. SETUP_NOTES 各 Phase 加 KPI | 改文件 | `docs: SETUP_NOTES 各 Phase 加驗證命令 (K1-K7)` |
| 🟠 | B. ARCHITECTURE.md 改 v0.3 標頭 | 改文件 | `docs: ARCHITECTURE.md 標頭改 v0.3 願景保留 OS` |
| 🟠 | E. os/ 跟 hardware/ 補 Phase 3 規劃 | 寫 README 補章節 | `docs: os/ hardware/ 補 Phase 3 詳細規劃` |
| 🟠 | A. DECISIONS.md #001 加 v0.2 觀察 | 改文件 | `docs: DECISIONS #001 加 v0.2 streaming 觀察` |
| 🟠 | #16 AgentOS 接 endpoint | 改 `main.py` 跟測試 | `feat(bridge): /chat /ws 改走 AgentOS enqueue` |
| 🟢 | #18 STRATEGIC_NOTES 加 cross-ref | 改文件 | `docs: STRATEGIC_NOTES 加 v2.1 cross-reference` |
| 🟢 | F. 等 v3.0 合併 | 留著不動 | — |

---

## 怎麼用這份檔

1. **先看本檔**，確認我整理的 v0.3 增補合理
2. **修訂清單**逐項 commit（小 commit、好 review）
3. **動 code**（#17、#16）才動
4. **動文件**（其他）只是「對齊」，風險低
5. **不動主計畫書**（per F）

---

## 跟之前文件的關係

- v2.1 是「v0.2 實作後的回顧」— 15 項
- v0.3（本檔）是「v2.1 + 你 6/4 回饋 + 跨文件檢查」— v2.1 沒看見的 4 項 + 6 個衝突 + Phase 3 規劃
- 之後 v1.0 實作完再做 v1.0 修訂（再補 15+ 項）
- v3.0 才把 v2.1 + v0.3 + v1.0 + v1.5 + v2.0 修訂合併回主計畫書

> **給未來自己的提醒**：
> 不要倒回來追求 v2.0 完美計畫書。當下 v0.x 跑通最重要、文件對齊是 v0.3 的事、合併是 v3.0 的事。
> STATUS.md 是現實，PLAN.md 是願景，v0.3 review 是「中間過渡文件」三層結構。
