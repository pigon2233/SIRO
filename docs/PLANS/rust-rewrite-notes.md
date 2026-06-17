# Rust 改寫 bridge 戰略筆記

> **狀態**：戰略決策（已決定）— 不在當前 v0.x / v1.x / v2.0 roadmap
> **決定日期**：2026-06-04（[STRATEGIC_NOTES.md Q1](STRATEGIC_NOTES.md#q1-rust-改寫-bridge)）
> **目標讀者**：未來考慮改寫的人、code reviewer

## 一句話結論

**bridge 在 v0.x / v1.x / v2.0 維持 Python，Phase 3+（v3 願景）才考慮 Rust 改寫。**

---

## 為什麼不現在改

| 考量 | 現實 |
|------|------|
| 痛點真實性 | Python GIL / 慢啟動 / 沒編譯期型別是真的，但**只在規模化才痛** |
| 當前規模 | 1 人本機單 Mao + 偶爾 dev 環境 demo |
| 改寫工時 | 1-2 週純工程（不算驗證、文件、測試） |
| 改寫風險 | 改寫時 bridge 不可用、停滯 v0.3+ 開發 |
| 改寫收益 | **當前 = 0 收益**（單人單 Mao 完全撐得住） |
| 替代方案 | Phase 3 已經把 system / supervisor / gRPC 層用 Rust — **AI 邏輯層可以永遠 Python** |

---

## 現在可以做的事（避免未來改寫地獄）

1. ✅ **bridge API 保持 language-agnostic**
   - HTTP/WS + JSON
   - 任何語言都能 client
   - gRPC 已經是 protobuf、language-agnostic

2. ✅ **Unity 端完全解耦**
   - MonoBehaviour 跟 bridge 通訊只看 WS protocol
   - bridge 換語言 Unity 不用改

3. ❌ **不要在 Python 寫太特別的東西**
   - 避免 metaclass、`__init_subclass__`、dynamic class creation
   - 避免 async generator type hint 過深巢狀
   - 避免 monkey patching 第三方套件

4. ❌ **不要用 Python-specific 套件（除非真的需要）**
   - ❌ SQLAlchemy（用 sqlite3 + 自寫 thin layer 即可）
   - ❌ Celery（用 asyncio.Queue + 我們自己的 AgentOS 即可）
   - ❌ Pydantic 在 hot path（v1 早期試過、序列化成本高）
   - ✅ FastAPI / httpx / websockets（標準、移植成本低）
   - ✅ pytest（業界標準）

---

## 什麼情況觸發 Rust 改寫

| 訊號 | 說明 |
|------|------|
| **單 process 撐不住併發** | CPU-bound task（embedding / TTS 大量請求）排隊變明顯 |
| **需要 cross-language 整合** | Rust 系統層 ↔ Python AI 層的 FFI 成本太高 |
| **需要 single binary 部署** | kiosk / container 不想帶 venv 部署 |
| **cold start < 100ms 需求** | 開機到角色出現要 < 5s（目前 Python ~3s 還撐得住） |
| **Python 套件 security issue** | 某個依賴有重大 CVE、要 fork / 重寫 |

**目前沒有任何一個訊號達標。**

---

## 改寫的範圍設計（先想好、未來動工才不浪費時間）

### Rust 改寫只動 Layer 2

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Presentation (C# Unity)                           │  ← 不動
└─────────────────────────────────────────────────────────────┘
            ▲ WebSocket (JSON, language-agnostic)
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: AI Bridge                                         │  ← Rust 改寫目標
│  - FastAPI  → axum                                          │
│  - Pydantic → serde                                         │
│  - 業務邏輯（emotion parser / AgentOS / task queue）          │
│  - LLM client（MiniMax-M3 / Ollama / hermes）                │
│  - Computer Control 15 tools（filesystem / shell / memory）  │
└─────────────────────────────────────────────────────────────┘
            ▲ gRPC (protobuf, language-agnostic)
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: System Runtime (Rust)                             │  ← 已 Rust
└─────────────────────────────────────────────────────────────┘
```

### 不在改寫範圍

- ❌ Unity C#（Live2D 沒有 Rust binding）
- ❌ os-runtime（已經 Rust）
- ❌ v1.5+ Computer Control 的 **policy**（blocklist / confirmation / trust_mode）— Rust 改寫時可選擇搬到 Rust 層或留 Python（個人偏好：留 Rust 層減少 IPC）

### 改寫順序（如果真的要動工）

1. **第一步：port emotion parser**（純函式、200 行、最容易驗證）
2. **第二步：port LLM clients**（HTTP client、3 個 provider）
3. **第三步：port AgentOS**（task queue + event bus + worker pool）
4. **第四步：port Computer Control tools**（15 個、用 Rust 重做 sandbox / shell / fs）
5. **第五步：port /chat + /ws endpoints**
6. **第六步：port v1.5+ confirmation broker + memory**
7. **第七步：bridge Rust 化、Python bridge 留為 fallback（run 1 個月驗證）**
8. **第八步：移除 Python bridge**

每一步都要：
- 對照 Python 行為做 parity test
- 跑 K2 / K8 / K10 驗證不退步
- 灰度發布（一段時間 50/50 切流量）

**預估總工時**：1-2 週純 port + 1 個月驗證 + 1 個月灰度。

---

## 跟 Phase 3 的關係

Phase 3（Rust system layer）是 **已經在做** 的 Rust 化：
- siro-runtime daemon 監控 bridge / hermes / unity
- gRPC IPC
- process supervisor
- Computer Control 5 個 system RPC（v1.5.3）

Phase 3 不等於「改寫 bridge」 — Phase 3 是「在 Python bridge 旁邊加 Rust 系統層」。兩者**不衝突**：
- Phase 3 已做：system 監控 + sandbox + shell/fs 操作（低階、要求 type-safe）
- 未來 Rust 改寫：AI 邏輯層（高階、迭代快）

---

## 給 reviewer 的提醒

看到 PR 想引入 Python-specific 玄學時，問：

1. 這個 feature 必須用 Python 才做得到嗎？
2. 有沒有更直白的寫法可以 port 到 Rust？
3. 這個依賴值得我們被綁在 Python 嗎？

舉例：
- ✅ `asyncio.to_thread` 包 sync call（直白、port 簡單）
- ❌ 動態 metaclass 註冊 task handler（直白 port 困難）
- ✅ `dataclass` + Pydantic v2（Rust 有 serde、port 簡單）
- ❌ `inspect.signature` 動態拿 type（Rust 沒有 runtime reflection）

---

## 相關文件

- [STRATEGIC_NOTES.md Q1](STRATEGIC_NOTES.md#q1-rust-改寫-bridge) — 原始決策
- [PLAN_REVISION_v2.1.md #2](../history/plan-revision-v2.1.md) — Rust 邊界
- [ARCHITECTURE.md §1.1](ARCHITECTURE.md) — 4 層架構
- [LIVE2D_AI_AGENT_OS_PLAN.md §2.1](LIVE2D_AI_AGENT_OS_PLAN.md) — 為什麼 Python + Rust
- [LIVE2D_AI_AGENT_OS_PLAN.md §8.5](LIVE2D_AI_AGENT_OS_PLAN.md) — LLM 廠商風險管理（不抽 protocol 抽象的同樣精神）

---

**最後一句話**：

Rust 改寫不是「會更好嗎」的問題，是「**值得現在花 2 週嗎**」的問題。
**現在不值得。**
