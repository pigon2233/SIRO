# Streaming 回應戰略筆記

> **狀態**：v0.3.1 結論已落地（MiniMaxStreamingClient + Unity incremental render）
> **決定日期**：2026-06-04（[STRATEGIC_NOTES.md Q2](STRATEGIC_NOTES.md#q2-streaming-回應)）
> **目標讀者**：想理解為什麼 streaming 走這條路、未來評估新 provider 的人

## 一句話結論

**透過 MiniMaxStreamingClient 直打 Anthropic SSE、不繞過 hermes 抽象**（但 hermes 介面目前不支援 streaming 所以走 shim）。v0.3.1 wire + v0.4+ Unity incremental render 都完成、UX 效果已可 demo。

---

## 瓶頸分析（v0.3 量測、2026-06-04）

從 18-20s hermes time 拆解：

| 階段 | 時間 | Streaming 救得了嗎 |
|------|------|-------------------|
| hermes CLI 啟動 | ~2-3s | ❌ hermes subprocess 必經（hermes 自己也要啟 Python） |
| Cloud LLM cold connect | ~3-5s | ❌ 雲端事 |
| **TTFT**（第一個 token） | ~3-5s | ❌ 雲端事 |
| 完整生成 ~150 tokens | ~5-8s | ✅ **streaming 救這個** |
| 收尾 + parse | ~1-2s | ❌ |

**TTFT 5-8s 是 cloud LLM 現實**。Streaming 救不了 TTFT、但救「感覺」：
- 沒 streaming：使用者等 18s 看到「你好~ 今天想聊什麼？」
- 有 streaming：使用者 5s 看到「你」、8s 看到「你好」、12s 看到「你好~ 今天」...

心理感受：5s vs 18s 是「等很久」vs「活著」。

---

## 決策過程

### 原始 4 個選項

| 選項 | 優點 | 缺點 | 結果 |
|------|------|------|------|
| A. 繞過 hermes 寫 MiniMaxClient | 真 SSE streaming | 失去 hermes 整合 | ❌ 否決（使用者 2026-06-04 決定 A 案）|
| B. hermes 介面加 streaming | 保留 hermes 抽象、sse via gateway/proxy | hermes 限制 | ❌ provider 不支援 anthropic（見下）|
| C. 接受現狀 18s | 0 工程 | user 繼續等 | v0.3 暫時 |
| D. 換更快的雲端模型 | TTFT 降到 1-2s | 找新 API、quota 風險 | v0.5+ 評估 |

### v0.3 hermes 能力探測結果

跑 `hermes --help` / `hermes proxy --help` / `hermes chat --help` 後：

| 介面 | 支援 MiniMax-M3 | 支援 streaming |
|------|----------------|----------------|
| `hermes chat`（subprocess、bridge 現用） | ✅ `HERMES_LLM_BASE_URL` 自訂 | ❌ 沒 `--stream` flag |
| `hermes proxy`（HTTP server） | ❌ **只支援 `nous` / `xai`** | ✅ OpenAI-compatible SSE |
| `hermes gateway` | — | —（messaging 用） |

**結論**：「走 hermes 介面 streaming」**被 hermes 限制擋住**：
- `hermes proxy` 雖然 OpenAI-compatible SSE，但只支援 Nous / xAI
- 我們用的是 anthropic + 自訂 base URL（`https://api.minimax.io/anthropic`）
- `hermes chat` 沒 streaming flag

### v0.3.1 新選項 + 決定

| 選項 | 優點 | 缺點 | 實作成本 |
|------|------|------|----------|
| A. 換 LLM provider 到 Nous Portal | 用 hermes proxy SSE | 換掉 MiniMax-M3（品質滿意）| 半天 + provider 風險 |
| **B. 保留 MiniMax-M3 + 寫 hermes_client streaming shim** | **保留 MiniMax-M3、sse via hermes-shaped 抽象** | 「hermes 介面」變薄 | 1 天 |
| C. 接受 v0.3 現狀 18s | 0 工程 | user 繼續等 | 0 |
| D. 換本地 Ollama | 0 雲端成本、0 延遲 | 7B Q4 跑不動、品質差 | 半天 tune |

**2026-06-04 決定：選 B** — 保留 MiniMax-M3 + 寫 hermes-shaped streaming shim。

---

## 實作結果（v0.3.1 + v0.4+）

### Wire 端（v0.3.1、commits `99de74c` `d96351b`）

- 新增 [bridge/minimax_streaming_client.py](../bridge/minimax_streaming_client.py)
  - 直打 `https://api.minimax.io/anthropic/v1/messages` 的 SSE endpoint
  - async generator 吐 delta chunk
  - 介面形狀跟 hermes client 對齊（讓 main.py 切換時 0 改動）
- bridge 加 `SIRO_STREAMING=true` env flag（opt-in、預設 false、向下相容）
- `/ws` 推 `{"type": "delta", "text": "..."}` 給 Unity

### Unity 端（v0.4+、commit `0dd9da7`）

- [ChatInputUI.cs](../SiroUnity/Assets/Scripts/ChatInputUI.cs) 訂閱 `OnBridgeDelta`
- 累積到 `_streamingBuffer`、每次 SetResponse 立即更新
- 沒開 streaming 時（預設）行為跟 v0.2 一樣、向下相容
- 提前做的原因：streaming UX 改善越早看得到越好

### K2 量化（v0.3+ 量測）

| 模式 | median | K2 目標 | 結果 |
|------|--------|---------|------|
| 雲端 MiniMax-M3（non-stream）| 30.80s | < 5s | ❌ FAIL |
| **雲端 MiniMax-M3（streaming）**| ~30s 總、TTFT ~5s | UX 改善 | ✅（不等於 K2 達標）|
| 本地 CPU 3B（Ollama）| 4.22s | < 5s | ✅（K2 < 5s PASS）|
| 本地 CPU 3B（target）| < 2s | < 2s | ❌ 需要 GPU 加速或更小模型 |

> K2 < 2s 目標在這台硬體（AMD Ryzen 9 5900HX、無強 GPU）跑 3B 模型**不可行**。
> 結論：硬體升級（GPU）或模型縮小（1B）是 K2 < 2s 的必要條件、不是 software 優化能解決的。

---

## 為什麼不抽 LLMClient protocol 抽象

2 個 client 並行（hermes subprocess sync + MiniMax streaming）跑了 2 個月、沒問題。
**保持直白**：
- ✅ `bridge/hermes_client.py` — subprocess 走 hermes CLI（sync）
- ✅ `bridge/minimax_streaming_client.py` — 直打 Anthropic SSE（streaming）
- ✅ `bridge/ollama_client.py` — 本地 Ollama fallback

**禁止事項**（即使沒 protocol 也要守）：
- ❌ 業務邏輯直接 `import hermes_sdk` / `import anthropic`
- ❌ 業務邏輯依賴特定 provider 功能（除非 opt-in flag）
- ❌ 業務邏輯處理 provider 認證（統一在 client 內部讀 `.env`）

**抽 protocol 的時機**：第 3 個 provider 進來時（SQLite 持久化、MCP 整合、Claude API 直連都有可能）。
預先寫好「v1+ 加新 provider 的策略」省得未來被 protocol 抽象反噬。

---

## 未來評估

| 場景 | 動作 |
|------|------|
| **Hermes 加 anthropic provider + streaming flag** | 把 `MiniMaxStreamingClient` 換成 `hermes proxy`（移除 shim） |
| **換 LLM provider** | 新增 `bridge/xxx_client.py`、跟現有兩個並存（不抽抽象）|
| **K2 < 2s 硬體升級** | GPU 跑 1B-3B 模型、target < 2s |
| **加 multi-modal（圖 / 音）**| 新增 `bridge/multimodal_client.py`、protocol 抽象屆時考慮 |

---

## 相關文件

- [STRATEGIC_NOTES.md Q2](STRATEGIC_NOTES.md#q2-streaming-回應) — 原始決策過程
- [PLAN_REVISION_v2.1.md #1](../history/plan-revision-v2.1.md) — Streaming 整個漏掉
- [PLAN_REVISION_v2.1.md #5](../history/plan-revision-v2.1.md) — 雲端 LLM 廠商鎖定
- [LIVE2D_AI_AGENT_OS_PLAN.md §8.5](LIVE2D_AI_AGENT_OS_PLAN.md) — LLM 廠商風險管理
- [CHANGELOG.md 2026-06-08 F1/F2 段](CHANGELOG.md) — K2 量化結果
- [bridge/minimax_streaming_client.py](../bridge/minimax_streaming_client.py) — 實作
- [SiroUnity/Assets/Scripts/ChatInputUI.cs](../SiroUnity/Assets/Scripts/ChatInputUI.cs) — Unity 端 incremental render

---

**最後一句話**：

TTFT 5-8s 是雲端 LLM 物理極限、software 救不了。
Streaming 救的是「**感覺**」不是「**速度**」 — 心理學上 5s 看到第一字 vs 18s 看到完整句是兩個世界。
