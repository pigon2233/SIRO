# SIRO 戰略決策筆記

> 2026-06-04 使用者提出的兩個長期戰略問題
> 這份文件是「**決定 + 理由 + 行動**」的快照，未來實際要做時直接對照

---

## Q1: Rust 改寫 bridge？

### 決定
**Phase 3+ 才做**（v0.2-v2 維持 Python）。

### 理由
- Python 痛點是真的（GIL、慢啟動、沒編譯期型別檢查）但只在規模化階段才痛
- v0.2-v2：1 人本機單 Mao — Python 完全 OK
- Phase 3+：kiosk / 雲端 SaaS — Rust 改寫有感
- 改寫工時 1-2 週，現在做 0 收益

### 現在可以做的（避免未來改寫地獄）
1. ✅ bridge API 已經是 HTTP/WS + JSON — language-agnostic
2. ✅ Unity 端 MonoBehaviour 跟 bridge 完全分離 — 重寫 bridge 不影響 Unity
3. ❌ 不要在 Python 寫太特別的東西（metaclass、`__init_subclass__`、async generator type hints）— 讓 Rust 對應簡單
4. ❌ 不要用 Python-specific 套件（SQLAlchemy、Celery）除非真的需要

### 怎麼知道 Phase 3 到了
- 單 process 已經撐不住併發（CPU-bound 任務）
- 需要 cross-language 整合（Rust 寫系統層、Python 寫 AI 層）
- 需要 single binary 部署（不用 venv 麻煩）
- 需要 < 100ms cold start

### v0.2 行動
- 寫這份文件 ✅
- Phase 2+ 改東西時保持「Rust 對應簡單」心態
- 實際改寫留到 Phase 3

---

## Q2: Streaming 回應？

### 決定（2026-06-04 更新）
**透過 hermes 介面做 streaming，不繞過 hermes**。等 hermes gateway / proxy 子命令支援 SSE 後接入。

### 為什麼改變
原本結論是「繞過 hermes 寫 MiniMaxClient 直連 MiniMax-M3 API」，
但 2026-06-04 使用者決策 A：hermes 是 SIRO 的 LLM 抽象層，**不繞過**。
Streaming 要走 hermes 內部介面（gateway / proxy）來做。

### 瓶頸分析（不變）
從 2026-06-04 觀察的 18-20s hermes time 拆解：

| 階段 | 時間 | Streaming 救得了嗎 |
|---|---|---|
| hermes CLI 啟動 | ~2-3s | ❌ 跳過 hermes 才救得了（但不能跳過） |
| Cloud LLM cold connect | ~3-5s | ❌ 雲端事 |
| **TTFT**（第一個 token） | ~3-5s | ❌ 雲端事 |
| 完整生成 ~150 tokens | ~5-8s | ✅ 邊生成邊推（透過 hermes streaming 介面） |
| 收尾 + parse | ~1-2s | ❌ |

**TTFT 5-8s 是 cloud LLM 現實**。Streaming 救不了 TTFT，但能救「感覺」：
- 沒 streaming：使用者等 18s 看到「你好~ 今天想聊什麼？」
- 有 streaming：使用者 5s 看到「你」、8s 看到「你好」、12s 看到「你好~ 今天」...

### 選項（更新）
| 解法 | 優點 | 缺點 | 狀態 |
|---|---|---|---|
| ~~A. 繞過 hermes 寫 MiniMaxClient~~ | ~~真 SSE streaming~~ | ~~失去 hermes 整合~~ | ❌ **不採用**（使用者 A 案否決） |
| **B. hermes 介面加 streaming** | 保留 hermes 抽象、sse via gateway/proxy | hermes 限制（要查 gateway 支援） | ✅ **v0.4+ 路線** |
| C. 接受現狀 18s | 0 工程 | user 繼續等 | v0.2 現實 |
| D. 換更快的雲端模型 | TTFT 降到 1-2s | 要找新 API、可能有 quota 問題 | v0.5+ 評估 |

### 怎麼決定（更新）
1. **查 hermes 能力**（v0.3）：
   - `hermes proxy` 子命令是不是 OpenAI-compatible HTTP server？能不能 SSE？
   - `hermes gateway` 是 polling 還是 webhook？能不能推 streaming？
2. **量測**（v0.3）：
   - 找 hermes 能做 streaming 的介面
   - 量測 actual TTFT vs total time 確認 streaming 改善程度
3. **實作**（v0.4+）：
   - bridge 加 `chat_stream(message) -> AsyncIterator[chunk]`
   - 走 hermes 介面（不是直連 MiniMax）
   - /ws 改用 `chat_stream` 邊收邊推 Unity
   - Unity 端 incremental text rendering

### v0.3 hermes 能力探測結果（2026-06-04）

跑 `hermes --help` / `hermes proxy --help` / `hermes chat --help` 後的發現：

| 介面 | 是否支援 MiniMax-M3 | 是否支援 streaming |
|---|---|---|
| `hermes chat` (subprocess，bridge 現用) | ✅ 用 `HERMES_LLM_BASE_URL` 自訂 anthropic provider | ❌ 沒 `--stream` flag |
| `hermes proxy` (HTTP server) | ❌ **只支援 `nous`（Nous Portal）跟 `xai`（xAI Grok OAuth）** | ✅ OpenAI-compatible SSE |
| `hermes gateway` | — | (messaging 用、不是 LLM 介面) |

**結論**：「走 hermes 介面 streaming」**被 provider 限制擋住**。

- `hermes proxy` 是 OpenAI-compatible HTTP + SSE，本來是理想解
- 但 proxy 只支援 `nous` 跟 `xai`，不支援 SIRO 目前的 `HERMES_LLM_PROVIDER=anthropic` + 自訂 `HERMES_LLM_BASE_URL=https://api.minimax.io/anthropic`
- `hermes chat` (subprocess) 沒 streaming flag

### v0.3.1 新選項

| 解法 | 優點 | 缺點 | 實作成本 |
|---|---|---|---|
| A. **換 LLM provider 到 Nous Portal** | 直接用 `hermes proxy` 拿 SSE streaming | 換掉 MiniMax-M3（目前品質滿意）、要重新 tune persona prompt | 半天 + provider 切換風險 |
| B. **保持 MiniMax-M3 + 寫 hermes_client streaming shim** | 保留 MiniMax-M3、走 hermes 介面抽象、SS 仍 SSE | 「hermes 介面」這層變薄（要呼叫 anthropic /messages API 而非 hermes proxy）| 1 天 |
| C. **保持 MiniMax-M3 + 接受 v0.3 現實 18s** | 0 工程 | user 繼續等 | 0 |
| D. **換本地 Ollama** | 0 雲端成本、0 延遲 | 本地 7B Q4 跑不動（VRAM 4GB 限制）、品質比 MiniMax-M3 差 | 半天 tune |

**推薦**：先選 C（接受現狀）留 v0.3 不動，v0.4 看使用體驗再決定。
如果真的想動：B 是最務實的解（保留 MiniMax-M3 + 走 hermes 抽象 + streaming），
但「hermes 介面」會從 subprocess 變成直接打 anthropic API（要評估 hermes 抽象是否仍有意義）。

### v0.3.1 決策：選 B（2026-06-04）

實作完成（commits）：
- `99de74c` feat(bridge): 加 MiniMaxStreamingClient
- `d96351b` feat(bridge): /ws 接 MiniMax-M3 SSE streaming

新增 env flag：
- `SIRO_STREAMING=true` → /ws 走 SSE streaming 推 delta 訊息給 Unity
- 預設 false、既有 188+2 測試不動

基礎建設 vs UX 差異：
- v0.3.1 完成了「delta 訊息在 wire 上了」（Unity 收得到 `{"type":"delta","text":"你"}`）
- **2026-06-04 v0.4+ 提前做**：Unity 端 commit 0dd9da7 接了 incremental render
  - ChatInputUI 訂閱 OnBridgeDelta、累積到 _streamingBuffer、每次 SetResponse 立即更新
  - 沒開 streaming 時（預設）行為跟 v0.2 一樣、向下相容
  - 提前做的原因：streaming UX 改善越早看得到越好；wire 變動純 additive（加新 case），不破壞既有 protocol
  - **脫離原 PLAN 推薦**：PLAN 寫「v0.4+ Unity incremental render 要跟 v1+ SendTask 一起做、避免重複改 protocol」— 沒等 SendTask 是 trade-off：
    - 優點：早看 UX 效果
    - 缺點：未來 v1+ SendTask 改 protocol 時，要再 audit 一次 delta/response 互動
  - 結論：v1+ SendTask + OnClick 仍是獨立 work item、不會 reuse commit 0dd9da7 的 C# code（方向不同 — SendTask 是 Unity → AgentOS 推 task、incremental render 是 AgentOS → Unity 推文字）

### 待你決策

1. ~~Unity 端什麼時候接 incremental render？~~ — **2026-06-04 v0.4+ 提前完成**（commit 0dd9da7）
2. **v1+ SendTask + OnClick** 仍是待做項目（讓 Unity 推 task 進 AgentOS、不是 incremental render）— 時程留 v1.0 roadmap 規劃
3. **選 B 之後的 hermes 抽象評估**：
   - 現在的 LLM 呼叫有 2 條路（hermes subprocess sync + 直接 anthropic SSE streaming）
   - 之後如果再加 LLM provider，會在這 2 條路各加一個 client
   - 評估：是否要把這 2 條路抽象成統一介面（`LLMClient` protocol）？
   - 決定：目前不抽象、保持直白（2 個 client、各自獨立）；真有第 3 個 provider 再重構

### v0.2 行動
- 寫這份文件 ✅
- v0.3 查 hermes 能力 + 量測 → 決定要不要做
- **不**繞過 hermes（per 使用者 A 案）

---

## 跟 PLAN_REVIEW_v0.3.md 的對齊

本檔（STRATEGIC_NOTES）在使用者 6/4 看完 PLAN_REVISION_v2.1 後寫，
但 v2.1 跟使用者的 A 案衝突（v2.1 建議繞過、使用者說不繞過）。

PLAN_REVIEW_v0.3.md（2026-06-04 修訂）已對齊 A 案，把本檔 Q2 結論同步更新。

未來 v1.0+ 修訂會再加：
- 真的做 hermes streaming 介面評估的結果
- B (hermes 介面) 路線圖細節
- C/D (接受現狀 / 換模型) 決策依據

---

## 相關文件 cross-reference

本檔是「決策快照」，相關細節在以下文件：

| 本檔 | 對應文件 | 對應章節 |
|------|----------|----------|
| Q1 Rust 改寫 | [ARCHITECTURE.md](ARCHITECTURE.md) | §1.1 4 層架構（Layer 3 Rust / Layer 4 Linux）|
| Q1 Rust 改寫 | [PLAN_REVISION_v2.1.md](plan-revision-v2.1.md) | #2 Rust 邊界沒講清楚 🟠 |
| Q1 Rust 改寫 | [PLAN_REVISION_v2.1.md](plan-revision-v2.1.md) | #11 「OS」定義模糊 🟡 |
| Q2 Streaming | [DECISIONS.md](decisions.md) | 決策 #001「為什麼用 Hermes Agent」v0.2 觀察段 |
| Q2 Streaming | [PLAN_REVISION_v2.1.md](plan-revision-v2.1.md) | #1 Streaming 整個漏掉 🔴 |
| Q2 Streaming | [PLAN_REVISION_v2.1.md](plan-revision-v2.1.md) | #5 雲端 LLM 廠商鎖定 🟠 |
| Q2 Streaming | [PLAN_REVISION_v2.1.md](plan-revision-v2.1.md) | #4 TTFT / KPI 沒量化 🟠 |
| v0.3 進度 | [STATUS.md](STATUS.md) | 版本演進段（v0.2 → v0.3）|
| v0.3 進度 | [AGENT_OS.md](../reference/agent-os.md) | 範圍演進段（v0.3 接到 /chat）|
| v0.3 進度 | [ARCHITECTURE.md](ARCHITECTURE.md) | v0.3 範圍對照表 |
| v0.3 進度 | [SETUP.md](SETUP.md) | §9 KPI 驗收（K1 K2 K4 K5 K7 K8 K10）|

### 決策追溯鏈

使用者原始決策 → 本檔 → 對應文件：

```
2026-06-02 決策 #001 選 Hermes
  → 2026-06-04 v0.2 實作發現 streaming 限制
    → 2026-06-04 本檔 Q2 結論：走 hermes 介面 streaming
      → 2026-06-04 commit 7aa135b STRATEGIC_NOTES Q2 改結論
      → 2026-06-04 commit f5d795e DECISIONS #001 加 v0.2 觀察
      → 2026-06-04 commit 8936d54 PLAN_REVISION_v2.1 修訂（15 項含 #1 Streaming 漏掉）
      → 2026-06-04 commit 8ffa8f0 SETUP.md §9 KPI 驗收（K2 包含 streaming latency）

2026-06-02 決策 Q1 Rust 改寫
  → 2026-06-04 本檔 Q1 結論：Phase 3+ 才做
    → 2026-06-04 commit 9e21653 ARCHITECTURE v0.3 標頭（Layer 3 標 Phase 3+）
    → 2026-06-04 commit 8936d54 PLAN_REVISION_v2.1 修訂（#2 Rust 邊界）
    → v0.3 不實作、留到 Phase 3+
```

### 為什麼要 cross-ref

1. **決策不再孤立**：未來想改某個決策時，先看其他文件有沒有引用、會不會影響別處
2. **commit 追溯**：每個決策都有具體 commit hash、可 git log 看完整脈絡
3. **避免決策飄移**：Q2 結論在 STRATEGIC_NOTES / DECISIONS / PLAN_REVISION / SETUP 四份文件都同步過、單一改動會被其他文件的 reviewer 抓出來

### cross-ref 維護責任

- 任何**新決策**加到本檔 → 必須同步更新 DECISIONS.md（如果該決策有 #001 那種「為什麼」的價值）
- 任何**重大結論改變**（像 Q2 從「繞過」改「不繞過」）→ 必須走完整追溯鏈：STRATEGIC_NOTES + DECISIONS + PLAN_REVISION + SETUP KPI 一起更新
- 任何**commit** 涉及決策 → commit message 引用 STRATEGIC_NOTES 段落、方便未來 `git log --grep`
