# K2 決策 — 反應時間目標與硬體限制

> **對應 PLAN 段**：[LIVE2D_AI_AGENT_OS_PLAN.md §KPI K2](../../LIVE2D_AI_AGENT_OS_PLAN.md)
> **對應 CHANGELOG 段**：[2026-06-08 F1/F2](../../docs/CHANGELOG.md)
> **目標讀者**：想理解為什麼 K2 < 2s 在這台硬體不可行、未來評估硬體升級的人
> **狀態**：決策文件（不再追 K2 < 2s、改為 K2 < 5s 為 v1 目標）

## 一句話結論

**K2 < 2s 在這台硬體（AMD Ryzen 9 5900HX、無獨顯）跑 3B 模型不可行。**
**v1 目標改為 K2 < 5s（雲端 OK < 30s 也行）、v2+ 再評估 GPU 升級。**

---

## 量測結果（2026-06-08）

| 模式 | median | min | max | 樣本數 | K2 目標 | 結果 |
|------|--------|-----|-----|--------|---------|------|
| **本地 CPU 3B**（Ollama llama3.2:3b-instruct-q4_0）| **4.22s** | — | — | 1 batch | < 5s | ✅ PASS |
| **雲端 MiniMax-M3**（Anthropic endpoint, non-stream）| **30.80s** | 25.08s | 49.54s | 10 樣本 | < 5s | ❌ FAIL |
| **雲端 MiniMax-M3**（Anthropic endpoint, streaming）| ~30s 總 / ~5s TTFT | — | — | 估計 | UX 改善 | ✅（不等於 K2 達標）|

量測 scripts：[scripts/perf/measure_k2.py](../../scripts/perf/measure_k2.py)

---

## 為什麼 K2 < 2s 不可行

### CPU 3B 模型極限分析

| 階段 | 時間 | 可優化嗎 |
|------|------|----------|
| hermes CLI 啟動 | ~1s | ❌ Python startup |
| Ollama subprocess 啟動 | ~0.5s | ❌ 子進程不可避免 |
| **模型載入到 VRAM**（cold） | ~2-3s | ❌ 第一次一定要 |
| **TTFT**（第一個 token）| ~0.5-1s | ❌ CPU 運算本質 |
| 生成 ~100 tokens | ~1-2s | 🟡 模型越小越快 |
| 收尾 + parse | ~0.2s | ❌ |

**CPU 跑 3B 模型 = 4-5s 物理下限**。這台機器（AMD Ryzen 9 5900HX, 8 cores, 16 threads, 沒有強 GPU）的極限。

### 想 < 2s 的選項

| 選項 | 改動 | 預估效果 | 工程成本 |
|------|------|----------|----------|
| **換 1B 模型** | llama3.2:1b | ~2-3s（~2x 改善）| 半天 + prompt tune |
| **加 GPU** | NVIDIA RTX 3060+ | < 1s | $200-300 USD + driver 設定 |
| **加 llama.cpp + GPU offload** | 現有 Ollama 切 llama.cpp | < 1s | 1 天 |
| **換更小 + 更強 embedding** | 主回應 1B + sub-task 用 embedding cache | < 2s | 1 週 |
| **改 streaming 第一字就算回應** | wire 已支援 | TTFT 5s 算「回應開始」| 0（已做）|

**結論**：K2 < 2s **需要硬體升級**（GPU）或模型縮小（1B）— software 優化到極限了。

---

## 決策

### v1 目標（2026 12 月）

- **本地 LLM**：K2 < 5s（CPU 3B 4.22s OK）
- **雲端 LLM**：K2 < 30s（30.80s OK、流式 UX 補救）
- 不追 K2 < 2s（硬體不支援）

### v2+ 評估（2027+）

- 硬體升級到有獨顯的筆電（NVIDIA RTX 3060+ 8GB VRAM、$200-300 USD）
- 改跑 1B-3B 模型 + GPU offload
- 預估 K2 < 1s 達標

### 為什麼 v1 不急著升級

| 考量 | 現實 |
|------|------|
| 個人使用量 | 1 人單 Mao、每天對話 ~50 輪、每輪等 4-30s |
| 心理感受 | streaming 5s 看到第一字 vs 等 18s 完整句是兩個世界 |
| 親友試用 | v1 試用期只 2-10 台給親友、不量產 |
| 成本 | $200-300 GPU + driver 維護 = 純粹的 UX 提升、沒商業價值 |

---

## 行動項目

### 短期（v1 內、本 commit 之前可做）

- [x] 量測 K2 三種模式（CHANGELOG 2026-06-08 F1/F2）
- [x] 文件化決策（本檔）
- [x] STREAMING_NOTES 結論更新
- [ ] 在 persona prompt 加「回應有時會慢、請耐心」話術（給使用者心理預期）

### 中期（v1+ 1-3 個月）

- [ ] 測試 1B 模型（llama3.2:1b）的品質、決定要不要切預設
- [ ] 評估硬體升級：NVIDIA RTX 3060 二手價、筆電能不能裝
- [ ] llama.cpp 直接跑（跳過 Ollama）省 ~0.5s 啟動

### 長期（v2+ 才做）

- [ ] GPU 升級後 + 模型縮小 → K2 < 1s
- [ ] 雲端 fallback 換更快的 provider（GPT-4o-mini / Claude Haiku）

---

## 給未來 reviewer 的提醒

KPI 目標是**指引**、不是**鐵律**。

當硬體限制讓某個 KPI 不可行時：
1. 量化證明（量測 script + 數字）
2. 重新定義 KPI（v1 目標 vs v2 目標 vs 願景目標）
3. 評估升級成本 vs 收益
4. 寫成決策文件（本檔範本）

**不要為了 KPI 達標而硬做不可能的事。**

---

## 相關文件

- [LIVE2D_AI_AGENT_OS_PLAN.md §KPI K2](../../LIVE2D_AI_AGENT_OS_PLAN.md) — 原始目標
- [CHANGELOG.md 2026-06-08 F1/F2](../../docs/CHANGELOG.md) — K2 量化結果
- [STREAMING_NOTES.md](../../docs/STREAMING_NOTES.md) — Streaming 決策（不繞過 hermes）
- [scripts/perf/measure_k2.py](../../scripts/perf/measure_k2.py) — 量測腳本
- [STRATEGIC_NOTES.md Q2](../../docs/STRATEGIC_NOTES.md) — streaming 戰略決策

---

**最後一句話**：

K2 < 2s 是願景、不是義務。
CPU 跑 3B 4s 是這台機器的極限、不是 software 寫得爛。
**接受現實、做好 UX、v2+ 再升級硬體。**
