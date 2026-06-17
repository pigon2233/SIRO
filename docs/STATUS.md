# SIRO 專案狀態總覽

> **更新時間**：2026-06-09
> **目的**：一眼看完「做到哪、有什麼、文件在哪、下一步是什麼」

## 一句話總結

SIRO 是「**Mao Live2D 角色 + bridge 後台作業系統 + Rust 系統層**」的 AI agent OS。
目前 v0.4+ 狀態：**1 人本機單 Mao、跟 Mao 中文對話可通、MiniMax-M3 雲端 LLM、本地 Ollama fallback、9 種情緒、待機動作、繁體中文 UI、AgentOS 預設開、v1.5+ Computer Control 15 tools、v1.5.3 走 gRPC、v2.0 持久化 SQLite 雛型就位**。Phase 0-3 所有 plan 內代辦清光、準備進 v1.0 試用期。

### 版本演進

- **v0.2**（已完成）：AgentOS 骨架 — Task Queue + Event Bus + Worker Pool + 14 個測試
- **v0.3**（2026-06-04）：`/chat` opt-in 走 AgentOS（`SIRO_USE_AGENT_OS=true`）。Task 加 `id`、EventBus 改回傳 `unsubscribe()`、新增 `wait_for_task()`。23 個 AgentOS 測試 + 4 個 /chat 整合測試 = 27 個新測試（總計 188）。預設仍走 v0.2 sync 路徑，觀察穩定後 v0.4 預設改 true。
- **v0.4**（2026-06-04）：`SIRO_USE_AGENT_OS` 預設翻 `true`（v0.3 觀察穩定後翻）。設 `SIRO_USE_AGENT_OS=false` 可降回 v0.2 sync。新增 5 個 TestUseAgentOSDefault 測試（總計 198 通過）。
- **v0.4+**（2026-06-09）：os-runtime 設定檔讀寫（figment + TOML）、硬體偵測 GPU/audio/display/cameras 補完、en-US.json i18n、scripts/dev/、K2 決策重定義。23 個新 SQLite 測試、3 個新 PLANS doc、3 個新 docs。

---

## 現狀快照

| 項目 | 狀態 | 備註 |
|---|---|---|
| **Phase 0** (manifest + dev scripts) | ✅ | 含 `scripts/dev/` 收尾、check-env.py / dev.sh / dev.ps1 |
| **Phase 1** (Unity + Cubism + bridge 對話) | ✅ | Play 模式實測通過 |
| **Phase 1.5** (Persona 抽象 + 降級 + 隱私 + KPI) | ✅ | runtime 驗收 2026-06-03 |
| **Phase 1.75** (技術債清理) | ✅ | 138→165 tests、async thread pool |
| **Phase 2** (視覺強化 + AgentOS + Computer Control) | ✅ | v0.2 → v0.4+ → v1.2 → v1.5+ → v1.5.3 全 ship |
| **Phase 3** (Rust 系統層) | ✅ | v0.3.0 MVP + v0.4+ 設定檔 + 硬體偵測 |

---

## 重要文件索引

### 計畫 / 架構
- [`LIVE2D_AI_AGENT_OS_PLAN.md`](../LIVE2D_AI_AGENT_OS_PLAN.md) — 原始完整計畫書（v2.0）
- [`docs/AGENT_OS.md`](reference/agent-os.md) — **v0.3 後台作業系統架構（最近更新）**
- [`docs/PERSONA.md`](PERSONA.md) — Persona YAML schema
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — 系統架構
- [`docs/GAPS.md`](PLANS/strategic-gaps.md) — 10 個 GAPS 缺口
- [`docs/DECISIONS.md`](history/decisions.md) — 重大決策紀錄

### 設定 / 操作
- [`SiroUnity/SETUP_NOTES.md`](../SiroUnity/SETUP_NOTES.md) — Unity 13 個坑的踩雷紀錄
- [`docs/SETUP.md`](SETUP.md) — 整體 setup
- [`docs/SETUP_PERSONA.md`](integration/persona-guide.md) — Persona 切換場景接線
- [`docs/API.md`](API.md) — bridge API 規格
- [`docs/TESTING.md`](TESTING.md) — 測試 SOP
- [`docs/SECURITY.md`](SECURITY.md) — 隱私現況 + 加密 roadmap
- [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) — 部署指南

### 計畫 / 規劃
- `~/.claude/plans/stateless-herding-nova.md` — v0.2 AgentOS 計畫（plan mode 寫的）
- `~/.claude/plans/` — 還有其他歷史 plan
- `docs/PLANS/agent-computer-control.md` — v1.5+ 完整設計
- `docs/PLANS/v2-persistence.md` — v2.0 SQLite 持久化設計
- `docs/PLANS/gaps-9-degradation.md` — GAPS #9 降級路徑細化
- `docs/PLANS/k2-decision.md` — K2 反應時間決策（v1 目標改 < 5s）
- `docs/RUST_REWRITE_NOTES.md` — Q1 Rust 改寫戰略
- `docs/STREAMING_NOTES.md` — Q2 streaming 戰略
- `docs/PERSONA_MIGRATION_GUIDE.md` — 怎麼寫新 persona

---

## 完成的 Phase 詳細

### ✅ Phase 0 — 環境 (2026-05)
- Unity 6.3 LTS + Cubism SDK 5-r.5 + URP 17
- `manifest.json` 加 Newtonsoft.Json
- Python venv + bridge 基礎

### ✅ Phase 1 — Mao 對話 (2026-06-03)
- Mao prefab 在 MainScene
- `HermesBridgeClient.cs`（WebSocket 連 bridge）
- `Live2DModelController.cs`（Cubism 表情切換 + eye-hiding hack）
- `EmotionDisplay.cs`（9 種情緒 → 8 個 expression）
- `ChatInputUI.cs`（TMP 輸入框 + 回應顯示）
- `bridge/main.py`（FastAPI 端點 /chat、/ws、/health）
- `bridge/hermes_client.py` + `ollama_client.py`（LLM 客戶端）
- 8 個 Editor 工具（FixMaoMaterials、ExpressionViewer、DisableMaoAnimator...）

### ✅ Phase 1.5 — GAPS 補強 (2026-06-03)
- Persona YAML schema（personality / model.expressions / quirks / fallback_responses）
- `bridge/prompts.py` 從 YAML 讀、不再 hardcode
- 兩段式 fallback：Ollama 失敗 → persona 靜態文字 + thinking 表情
- `docs/SECURITY.md` §0 隱私現況說明
- PLAN.md 加 KPI 章節（K1-K10）
- PLAN.md Phase 2-6 都有 GAPS 對應子節

### ✅ Phase 1.75 — 技術債清理 (2026-06-03)
- **測試**（K10 0% → 83%）：165 tests、conftest、pytest.ini
  - 138 + 1 xfail → 143（jieba 修好）→ 151（v0.2 prompt 改）→ 165（+14 AgentOS）
- **async thread pool**：hermes/ollama 用 `asyncio.to_thread` 不卡 event loop
- **效能優化**：3x 改善（60s → 18s 對話回應）
  - per-persona EmotionParser cache
  - /chat 跟 /ws 加 `⏱ hermes=Xms parse=Xms total=Xms` timing log
  - SIRO persona prompt 縮簡 1.2KB → 250 bytes
- **jieba 修 bug**：用戶輸入「天氣」誤判 angry — jieba 斷詞 + add_word 16 個情緒詞

### 🟡 Phase 2 — 視覺強化 + AgentOS（進行中）
| # | 項目 | Commit |
|---|---|---|
| 1 | 待機動作 loop（mtn_01 自動 loop） | `2d77361` |
| 2 | i18n zh-TW.json + Localization.cs | `36604ea`、`3e3d1f2` |
| 3 | **AgentOS 骨架**（v0.2，Task Queue + Event Bus + Worker Pool） | `f56c4e2` |
| 4 | **AgentOS 接到 /chat**（v0.3，opt-in via `SIRO_USE_AGENT_OS`） | `73b78b8`、`6698fa6`、`da28d9f` |
| 5 | 表情平滑過渡 | ⏳ 暫停 |
| 6 | 點擊 Mao 觸發 motion | ⏳ 暫停 |
| 7 | Loading 狀態視覺 | ⏳ 暫停 |
| 8 | 視覺設定檔 | ⏳ 暫停 |
| 9 | 截圖功能 | ⏳ 暫停 |

### ✅ Phase 2 → v0.3 收尾（已完成）
- ✅ PLAN_REVISION_v2.1.md（15 項計畫書修訂補完）| `8936d54`
- ✅ `AGENT_OS.md` 補 v0.3 現況 | `0066b56` |

---

## 架構現況

```
┌─ Frontend: Unity 6 + Cubism 5-r.5 ─────────────────────────┐
│  - Mao (Live2D) 表情 8 個 (exp_01-08)、待機動作 loop         │
│  - ChatInputUI (TMP 輸入框)                                   │
│  - PersonaManager (目前 1 個 persona = siro-default)           │
│  - PersonaSelectorUI (齒輪 icon 切角色、電腦滑鼠 UX)           │
│  - i18n: Resources/i18n/zh-TW.json                            │
└─────────────────────────────────────────────────────────────┘
        ↕ WebSocket (JSON) / HTTP REST
┌─ Backend: bridge (Python FastAPI) ──────────────────────────┐
│  - /chat 跟 /ws 端點（v0.2 sync 預設 / v0.3 opt-in AgentOS）    │
│  - /personas API（多角色切換）                              │
│  - LLM client：HermesClient（雲端 MiniMax-M3）+ OllamaClient   │
│  - EmotionParser（9 情緒 → Live2D signal，per-persona cache）   │
│  - AgentOS（v0.3）：Task Queue + Event Bus + Worker Pool      │
│                    + Task.id + wait_for_task()                │
│  - persona YAML 載入、jieba 斷詞、表情 tag 解析                 │
└─────────────────────────────────────────────────────────────┘
```

---

## LLM 配置

| 項目 | 值 |
|---|---|
| **Primary LLM** | `MiniMax-M3` @ `https://api.minimax.io/anthropic` |
| **Primary timeout** | 600 秒 |
| **Fallback LLM** | 本地 Ollama `llama3.2:3b-instruct-q4_0` |
| **API key** | 存在 `.env`（gitignored，**不要 commit**）|
| **Hermes CLI** | `~/hermes-agent/.venv/Scripts/hermes.exe` |
| **venv 安裝位置** | `C:\Users\jason\AppData\Local\hermes\hermes-agent\venv\`（Python 3.11）|
| **回應時間** | 18-20s（cold start 30-60s 之後穩定）|

---

## 程式碼入口

| 角色 | 檔案 | 進入點 |
|---|---|---|
| Unity 對話輸入 | `SiroUnity/Assets/Scripts/ChatInputUI.cs` | `OnSendClicked()` |
| Unity 表情切換 | `SiroUnity/Assets/Scripts/EmotionDisplay.cs` | `HandleBridgeResponse()` |
| Unity 角色控制 | `SiroUnity/Assets/Scripts/Live2DModelController.cs` | `SetExpression(id)`、`PlayMotion(clip)`、`SetQuirks(...)` |
| Unity Persona 切換 | `SiroUnity/Assets/Scripts/PersonaManager.cs` | `ApplyPersona(id)` |
| bridge 啟動 | `bridge/main.py` | `lifespan()` 啟動 AgentOS + parser cache |
| bridge chat 端點 | `bridge/main.py:303-` | `/chat` (v0.2 sync / v0.3 opt-in AgentOS via `SIRO_USE_AGENT_OS`) |
| bridge WS 端點 | `bridge/main.py:415-` | `/ws` (WebSocket) |
| bridge 排程任務 | `bridge/agent_os.py` | `AgentOS.enqueue(Task(...))` |
| 第一個範例任務 | `bridge/tasks/llm_reply_task.py` | `create_llm_reply_task()` |

---

## 測試現況（K10 進度）

| 指標 | 值 |
|---|---|
| 測試總數 | 188 passed（165 → 188：v0.3 AgentOS 加 9 個 + /chat 整合加 4 個）|
| 覆蓋率 | 83% |
| 測試目錄 | `tests/bridge/` |
| 跑測試 | `python -m pytest tests/bridge/ -q` |

各模組覆蓋率：
- `emotion_parser.py`: 85%
- `hermes_client.py`: 88%
- `ollama_client.py`: 90%
- `prompts.py`: 88%
- `runtime_client.py`: 76%
- `main.py`: 71%
- `models.py`: 100%

---

## 進行中 / 暫停項目

### v0.2 + v0.3 完成的
- ✅ AgentOS 骨架（v0.2，task queue、event bus、worker pool）
- ✅ 第一個 task：`llm_reply_task`（v0.2 封裝 /chat 邏輯、v0.3 真的被 /chat 呼叫）
- ✅ v0.3 增強：Task.id、EventBus `unsubscribe()`、`wait_for_task()`、`SIRO_USE_AGENT_OS` flag
- ✅ 23 個 AgentOS 測試（v0.2 14 個 + v0.3 9 個：unsubscribe 2 + wait_for_task 4 + Task.id 3）
- ✅ 4 個 /chat 整合測試（v0.3 新增）
- ✅ `docs/AGENT_OS.md` 架構文件（v0.2 寫、v0.3 更新到 commit 0066b56）

### v1+ 還沒做（按優先度）
| 項目 | 原因 | 預估 |
|---|---|---|
| Unity `SendTask()` API | AgentOS 是後端，Unity 端還沒接 | 半天 |
| Unity `OnClick()` → task | 點 Live2D 觸發任務 | 半天 |
| WS `task` message type | Unity ↔ bridge 的任務通訊 | 半天 |

### Phase 2 暫停（視覺強化）
- 表情平滑過渡動畫
- 點擊 Mao 觸發 motion（idle 之類）
- Loading 狀態視覺
- 視覺設定檔（亮度、縮放）
- 截圖功能

---

## v1+ Roadmap

來源：`docs/AGENT_OS.md` + plan mode 規劃

| Phase | 場景 | 改動 |
|---|---|---|
| **v1.0** | Telegram 整合 | `telegram_bot.py`（polling）、handler 把訊息 enqueue `telegram_msg` task |
| **v1.1** | 排程 | `scheduler.py`，asyncio loop + cron parser |
| **v1.2** | Unity 點 Live2D → task | `SendTask()` + WS `task` message type + `OnClick()` |
| **v1.5** | LLM tool calling | bridge 支援 function calling schema |
| **v2.0** | 任務持久化 | SQLite、bridge 重啟可恢復 |
| **Phase 3+** | **Rust 改寫 bridge** | 單 binary、高效能、型別安全（詳見下）|

---

## 戰略決策待辦

1. **Streaming 回應**：要不要繞過 hermes 直接打 MiniMax-M3 API？
   - 瓶頸：TTFT 5-8s（雲端 LLM 現實）vs total 18s
   - 選項 A：寫 `MiniMaxClient` 直連 Anthropic SSE（半天）
   - 選項 B：接受現狀
   - 詳見 `docs/STREAMING_NOTES.md`（待寫）

2. **Rust 改寫**：
   - 階段：Phase 3+（v0.2-v2 Python 完全 OK）
   - 預先措施：bridge API 保持 HTTP/WS + JSON（已是 language-agnostic）
   - 待寫 `docs/RUST_REWRITE_NOTES.md` 記錄要保持 language-agnostic 的介面

---

## 怎麼跑

### 開發者日常
```bash
# 1. 啟動 bridge (terminal 1)
cd "/c/coconut chennel/SIRO"
python -m bridge.main

# 2. Unity Editor 開 SiroUnity/，進 Play 模式
# 3. 跟 Mao 對話、看齒輪 icon、按 ChatInputUI 輸入
```

### 跑測試
```bash
python -m pytest tests/bridge/ -v          # 全跑
python -m pytest tests/bridge/test_agent_os.py -v  # 只跑 AgentOS
python -m pytest tests/bridge/ --cov=bridge --cov-report=term  # 含覆蓋率
```

### 切換 persona
1. 寫一份 `bridge/personas/新角色.yaml`
2. prefab 放 `Assets/Resources/Characters/新角色/`（v1+）
3. 重啟 bridge + Unity
4. 點齒輪 → 看到新角色

---

## 最近的 commit（最近 12 個）

```
0066b56 docs(AGENT_OS): 補 v0.3 現況 — /chat opt-in 走 AgentOS
da28d9f test(bridge): /chat AgentOS 整合測試 — flag=true 路徑
6698fa6 feat(bridge): /chat 走 AgentOS via SIRO_USE_AGENT_OS env flag (v0.3 opt-in)
73b78b8 feat(bridge): AgentOS Task.id + EventBus unsubscribe + wait_for_task
8936d54 docs(plan): 寫 PLAN_REVISION_v2.1.md — v2.0 計畫書 15 項修訂補完
7aa135b docs(STRATEGIC_NOTES): Q2 改結論 — 不繞過 hermes，走 hermes 介面 streaming
fa9bf63 fix(perf): is_available() 5s TTL cache 拿掉 hot path sync subprocess
d70d637 docs: 寫 PLAN_REVIEW_v0.3.md — v2.1 之外的增補 + 跨文件衝突
088f7f3 diag(bridge): /chat + /ws 加 5 段细粒度計時診斷 60s 瓶頸
46f3625 docs: 寫 STATUS.md 總覽 + STRATEGIC_NOTES.md 戰略決策
f56c4e2 feat(bridge): v0.2 AgentOS 骨架 — Task Queue + Event Bus + Worker Pool
acc5a9a fix(unity): 修 C# 編譯錯誤
```

要看完整： `git log --oneline -30`

---

## 給未來自己的提醒

- **原計畫書 `LIVE2D_AI_AGENT_OS_PLAN.md` 的 Phase 6 規劃已經偏離**（使用者改成「個人 AI Agent OS」方向）。要對齊原本的話去看那份，但要記得我們已經 pivot 到更小的 scope（1 人本機單 Mao + 個人作業系統）
- **Phase 1.5 runtime 驗收已過**（2026-06-03 測試 T1-T6 全綠）
- **安全性**：API key 跟個資不能 commit，現在都在 `.env` + gitignored
- **測試文化**：每次 commit 前 `python -m pytest tests/bridge/`
- **i18n 改字串**：改 `Resources/i18n/zh-TW.json`、不要 hardcode 在 .cs

---

## 還沒寫但應該寫的

- [ ] `docs/RUST_REWRITE_NOTES.md` — 戰略決策（Q1 Rust）
- [ ] `docs/STREAMING_NOTES.md` — 戰略決策（Q2 streaming）
- [ ] `docs/PERSONA_MIGRATION_GUIDE.md` — 寫新 persona 的 SOP（partial 散在 SETUP_PERSONA）
- [ ] `docs/RUST_REWRITE_NOTES.md` 提到的「介面契約」可以從 `docs/API.md` 抽出

---

## 文件更新政策

- 重大 commit 同步更新 STATUS.md（加新 commit hash）
- Phase 完成更新「完成的 Phase 詳細」區塊
- 決策變動更新「戰略決策待辦」區塊
- 任何時候 `git log --oneline | head -10` 都能對照 STATUS.md 看現在哪裡
