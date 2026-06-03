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

### 決定
**等 v0.3 量測實際 TTFT vs total time 再決定**。

### 瓶頸分析
從 2026-06-04 觀察的 18-20s hermes time 拆解：

| 階段 | 時間 | Streaming 救得了嗎 |
|---|---|---|
| hermes CLI 啟動 | ~2-3s | ❌ 跳過 hermes 才救得了 |
| Cloud LLM cold connect | ~3-5s | ❌ 雲端事 |
| **TTFT**（第一個 token） | ~3-5s | ❌ 雲端事 |
| 完整生成 ~150 tokens | ~5-8s | ✅ 邊生成邊推 |
| 收尾 + parse | ~1-2s | ❌ |

**TTFT 5-8s 是 cloud LLM 現實**。Streaming 救不了 TTFT，但能救「感覺」：
- 沒 streaming：使用者等 18s 看到「你好~ 今天想聊什麼？」
- 有 streaming：使用者 5s 看到「你」、8s 看到「你好」、12s 看到「你好~ 今天」...

### 選項
| 解法 | 優點 | 缺點 |
|---|---|---|
| **A. 繞過 hermes 寫 MiniMaxClient** | 真的 SSE streaming、TTFT 開始就能推 chunk | 失去 hermes 的會話 / tool calling（SIRO 沒用） |
| **B. 接受現狀 18s** | 0 工程 | user 繼續等 |
| **C. 換更快的雲端模型** | TTFT 降到 1-2s | 要找新 API、可能有 quota 問題 |

### 怎麼決定
1. **量測**（v0.3）：
   - 改 hermes 加 streaming flag 看能不能用
   - 改 `MiniMax-M3` API 直接打，看 SSE 是否真的改善 perceived UX
2. **評估**：
   - 改善 > 30% perceived → 做 A
   - 改善 < 30% → 不值得
3. **實作**（如果做）：
   - 新檔 `bridge/streaming_client.py`：直連 MiniMax-M3，用 httpx + SSE
   - bridge 加 `chat_stream(message) -> AsyncIterator[chunk]`
   - /ws 改用 `chat_stream` 邊收邊推 Unity
   - Unity 端 incremental text rendering

### v0.2 行動
- 寫這份文件 ✅
- **不**先動 streaming 程式碼（避免 premature optimization）
- v0.3 之後量測、看數據決定
