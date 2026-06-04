# SIRO 計畫書 v2.1 修訂 — 補完規劃不嚴謹處

> **產出時間**：2026-06-04
> **對應計畫書**：`LIVE2D_AI_AGENT_OS_PLAN.md` v2.0（2026-06-02）
> **產出原因**：v0.2 實作後回頭審視計畫書，找出 15 項規劃不嚴謹之處
> **本檔定位**：可直接 merge 回主計畫書的修訂補完文件
> **方法論**：邊做邊想、不動手找不到問題（v0.2 → v1.0 期間持續更新）

---

## 修訂總覽（15 項）

| # | 問題 | 嚴重度 | 影響章節 | 處理方式 |
|---|------|--------|----------|----------|
| 1 | Streaming 整個漏掉 | 🔴 致命 | 風險登記、Phase 1 | 補章節 |
| 2 | Rust 邊界沒講清楚 | 🟠 高 | 架構、技術堆疊 | 補章節 |
| 3 | AgentOS 多工順序顛倒 | 🟠 高 | 階段規劃 | 補章節 |
| 4 | TTFT / KPI 沒量化 | 🟠 高 | 風險登記、新章節 | 補章節 |
| 5 | 雲端 LLM 廠商鎖定 | 🟠 高 | 風險登記 | 補章節 |
| 6 | Persona 抽象太晚 | 🟡 中 | 階段規劃、Phase 1 | 補章節 |
| 7 | Unity ↔ bridge 通訊沒詳細設計 | 🟡 中 | 介面契約 | 補章節 |
| 8 | 測試策略太晚 | 🟡 中 | 階段規劃 | 補章節 |
| 9 | 部署 / OS 客製化寫太早 | 🟡 中 | 階段規劃 | 補章節 |
| 10 | 失敗處理 / 降級路徑沒寫 | 🟡 中 | 風險登記 | 補章節 |
| 11 | 「OS」定義模糊 | 🟡 中 | 願景、架構 | 補章節 |
| 12 | 開發者 = 使用者盲點 | 🟡 中 | 新章節 | 補章節 |
| 13 | 時間預估太樂觀 | 🟡 中 | 時間軸 | 補章節 |
| 14 | 沒有「什麼不做」清單 | 🟢 低 | 新章節 | 補章節 |
| 15 | 文件先寫完再寫 code | 🟢 低 | AI 協作開發指南 | 補章節 |

---

## 各項詳述

### 1. Streaming 整個漏掉 🔴 致命

**問題：**
LLM 是 SIRO 核心，但計畫書從未討論「LLM 怎麼呼叫」「回應如何送到 UI」。

v0.2 實作時使用 Hermes CLI 當中介，發現：
- Hermes CLI 一次性返回完整 response（無 streaming）
- TTFT (Time To First Token) 5-8 秒
- 完整生成 18-20 秒
- 使用者感覺「按下去要等 1 分鐘」

**修訂內容：**

新增章節 **6.5 LLM Streaming 設計**：

```yaml
llm_streaming:
  default: streaming
  protocol: SSE (Server-Sent Events)
  endpoint:
    primary: https://api.minimax.io/anthropic/v1/messages
    fallback_ollama: http://localhost:11434/api/chat
  request:
    model: MiniMax-M3
    stream: true
    max_tokens: 1024
  response_format:
    type: event-stream
    events:
      - message_start
      - content_block_start
      - content_block_delta    # 一個字一個字來
      - content_block_stop
      - message_stop
      - error
  ux:
    first_token_target: < 5 秒
    total_response_target: < 15 秒
    緩衝策略: 立即推送，不累積
```

**Bridge 端實作要求：**

```python
async for chunk in minimax_stream(...):
    # 立刻送 Unity，不累積
    await unity_ws.send({
        "type": "stream_chunk",
        "text": chunk.delta.text
    })
```

**Phase 1 補做：**
- [ ] 寫 `MiniMaxClient`（直打 API，繞過 Hermes）
- [ ] 改成 SSE streaming
- [ ] Unity 端支援逐字顯示
- [ ] 移除 Hermes CLI 中介（或保留為 fallback）

**備註：**
Hermes CLI 不支援 streaming 是廠商限制。**SIRO 不應被單一 LLM 工具綁架。** LLM 抽象層要設計成「可繞過任何中介」。

---

### 2. Rust 邊界沒講清楚 🟠 高

**問題：**
計畫書願景是「OS 用 Rust 寫」，但：
- v0.2 整套 bridge 用 Python 寫完
- 哪些層 Rust？哪些 Python？何時 pivot？完全沒寫
- 計畫書寫「bridge API 保持 language-agnostic」但 code 不是

**修訂內容：**

新增章節 **3.5 語言邊界細節**：

```yaml
語言分工:
  rust:
    時機: Phase 3+ (v0.3 之後)
    範圍:
      - os-runtime/siro-runtime (systemd supervisor)
      - 硬體抽象層 (音訊/視訊/GPIO)
      - 系統呼叫封裝
      - IPC server (gRPC/Unix socket)
    不做:
      - LLM 整合
      - WebSocket handler
      - 業務邏輯
  
  python:
    時機: Phase 1-2 (現在)
    範圍:
      - bridge LLM 整合
      - WebSocket handler
      - 情緒解析
      - 工具註冊
      - 多工 (AgentOS)
    不做:
      - systemd 服務
      - 系統層 supervisor
      - 硬體直接驅動
  
  csharp:
    時機: 全程
    範圍:
      - Unity Live2D 客戶端
      - 表情動作播放
      - WebSocket 連 bridge
    不做:
      - 任何 OS 邏輯
      - 任何 LLM 整合

介面契約 (不變原則):
  - bridge 對外: HTTP REST + WebSocket + JSON
  - 對 Rust 層: gRPC 或 Unix socket
  - 對 Unity: WebSocket + JSON
  - 內部模組間: language-agnostic 介面
```

**Rust 啟動時機決策樹：**

```
[v0.2 - v0.3]
  └─ Python 繼續
  └─ Rust 層為空（systemd 仍用 bash 啟動 Python）

[v0.4 - v0.5]
  └─ 寫 siro-runtime (Rust supervisor)
  └─ siro-runtime 監管 Python bridge
  └─ Python 掛了 siro-runtime 重啟

[v0.6+]
  └─ 視需求改寫 bridge 部分模組到 Rust
  └─ 不強求全 Rust
```

---

### 3. AgentOS 多工順序顛倒 🟠 高

**問題：**
計畫書把「多工」放在 Phase 2 才做，但 v0.2 實作時才發現：

- 對話是單線沒問題
- 但 Unity 點擊、cron 觸發、視訊事件、Telegram 整合**全是多工場景**
- Phase 1 沒設計 task 抽象，到 Phase 2 才補 → code 要回頭改

**修訂內容：**

**修訂原則：「task-shaped from day 1」**

即使 Phase 1 只做單線對話，code 也要寫成「task 物件」：

```python
# 即使是簡單對話，也包成 task
class ChatTask:
    type: "chat"
    priority: int
    payload: dict
    state: "queued" | "running" | "done" | "failed"

# 不寫死 procedure call
# 不寫同步 if-else
```

**Phase 順序調整：**

| 原本 | 改成 |
|------|------|
| Phase 1: 對話 | Phase 1: 對話 + **task 抽象雛形** |
| Phase 2: 多工 | Phase 1.5: 多工基礎設施 |
| Phase 3+: 工具 | Phase 2: 工具 + 多工場景 |

**現況補做：**
- v0.2 已做 AgentOS 骨架（Task Queue + Event Bus + Worker Pool）✅
- v0.3 需要做：Unity 端 `SendTask()` API
- v0.3 需要做：WS `task` message type

---

### 4. TTFT / KPI 沒量化 🟠 高

**問題：**
計畫書說「開機 5 秒內看到角色」「對話回應 < X 秒」，但：
- 沒寫誰來量、怎麼量
- 沒寫失敗的標準
- 結果：18-20s 沒人覺得不對

**修訂內容：**

新增章節 **9.5 KPI 量化指標**：

```yaml
KPI 必須可量測:
  
  K1 開機時間:
    目標: 開機到 Mao 出現問候 < 5 秒
    量測: systemd-analyze + Unity 啟動 log
    失敗標準: > 10 秒
    
  K2 對話 TTFT:
    目標: 使用者發送到第一個字出現 < 5 秒
    量測: bridge timing log (`⏱ hermes=Xms parse=Xms total=Xms`)
    失敗標準: > 8 秒
    
  K3 對話完整回應:
    目標: 使用者發送到完整回應 < 15 秒
    量測: bridge timing log
    失敗標準: > 20 秒
    
  K4 24/7 穩定度:
    目標: 連續 7 天無當機
    量測: systemd watchdog + bridge heartbeat
    失敗標準: 24 小時內當機 > 1 次
    
  K5 測試覆蓋率:
    目標: bridge/ 模組 > 80%
    量測: pytest --cov
    失敗標準: < 70%
    
  K6 表情切換:
    目標: emotion signal 到 Live2D 切換 < 200ms
    量測: Unity log + bridge log
    失敗標準: > 500ms
    
  K7 語音 TTS:
    目標: TTS 開始播放 < 1.5 秒
    量測: TTS client timing
    失敗標準: > 3 秒
```

**驗收機制：**
- 每個 Phase 結束跑 K1-K7 全部
- 任一 K 失敗標準 = Phase 沒完成
- 結果寫進 STATUS.md

---

### 5. 雲端 LLM 廠商鎖定 🟠 高

**問題：**
計畫書寫「Hermes Agent 整合」就沒了，沒考慮：
- 廠商不支援的功能怎麼辦 (e.g. streaming)
- 廠商停止服務怎麼辦
- 廠商漲價怎麼辦
- 廠商改 API 怎麼辦

**v0.2 實例：** Hermes CLI 不支援 streaming → 18-20s 卡住。

**修訂內容：**

新增章節 **8.5 廠商風險管理**：

```yaml
llm_provider_風險:
  識別:
    - 單一 provider 鎖定
    - 工具鏈過度依賴
    - 隱私條款變動
    - API breaking change
  
  緩解:
    抽象層:
      - LLM client 介面統一 (LLMClient protocol)
      - 多 provider 支援 (OpenAI, Anthropic, Ollama, Hermes)
      - 切換 provider 不改業務 code
    
    fallback 策略:
      - 雲端 LLM 掛 → 自動切本地 Ollama
      - Ollama 掛 → 預設回應池
      - 完全掛 → 角色「思考中」表情
    
    抽象層位置: bridge/llm/
      - llm_client.py (abstract)
      - minimax_client.py (SSE streaming)
      - ollama_client.py (local fallback)
      - hermes_client.py (legacy)
      - response_pool.py (default fallback)
  
  不可接受:
    - 業務邏輯直接 import provider SDK
    - 業務邏輯依賴 provider 特定功能
    - 業務邏輯處理 provider 認證
```

**Phase 1 補做：**
- [ ] 抽象 LLMClient 介面
- [ ] 寫 MiniMaxClient (直打 Anthropic SSE)
- [ ] 把 Hermes 從主路徑降級為備援
- [ ] 移除 `from hermes_sdk import ...` 散落

---

### 6. Persona 抽象太晚 🟡 中

**問題：**
v0.1 角色（人設、prompt、表情）寫死，v0.2 才補 Persona YAML schema。
- 1.5 還要回去重構 prompt 系統
- 重構成本 < 第一次就做對

**修訂內容：**

**修訂原則：「persona-shaped from day 1」**

即使 v0.1 只有 1 個角色，code 也要設計成 persona-driven：

```python
# v0.1 寫法 (錯)
SYSTEM_PROMPT = "你是 Mao，溫柔的角色..."
EXPRESSIONS = {"happy": "exp_01", "sad": "exp_02"}

# v0.1 寫法 (對)
persona = Persona.load("siro-default")
# 從 YAML 載入
# 之後加新角色 = 寫新 YAML，不改 code
```

**Phase 1 順序調整：**
- v0.1 起：Persona 抽象、YAML 載入
- v0.2 才有：多角色切換 UI

**現況補做：**
- ✅ v0.2 已做 Persona YAML
- 還要做：Persona hot reload（不重啟 bridge 切角色）
- 還要做：Persona 預設值（避免某欄位空）

---

### 7. Unity ↔ bridge 通訊沒詳細設計 🟡 中

**問題：**
計畫書寫「WebSocket + JSON」就沒了，沒寫：
- message type 怎麼分
- task vs event 怎麼傳
- 錯誤怎麼回
- heartbeat / 重連
- 訊息大小限制

**v0.2 補做：** WS task message type

**修訂內容：**

新增章節 **6.2 WebSocket 通訊協定**：

```yaml
ws_protocol:
  base:
    transport: WebSocket
    encoding: JSON
    url: ws://localhost:8000/ws
    heartbeat: 30s ping/pong
  
  message_format:
    common:
      - type: string (required)
      - id: string (optional, 用於 request/response 配對)
      - timestamp: int (ms epoch)
      - data: object (optional)
  
  client_to_server:
    - type: "chat"
      data: {text: string, persona_id?: string}
    
    - type: "task"
      data: {task_type: string, payload: object}
    
    - type: "ping"
    
  server_to_client:
    - type: "stream_chunk"   # LLM streaming
      data: {text: string, done: bool}
    
    - type: "emotion"        # 表情切換
      data: {emotion: string, intensity: float}
    
    - type: "motion"         # 動作播放
      data: {motion_id: string, loop: bool}
    
    - type: "task_result"
      data: {task_id: string, status, result}
    
    - type: "error"
      data: {code: string, message: string}
    
    - type: "pong"
  
  error_handling:
    客戶端斷線:
      - bridge 緩衝最後 N 條訊息 (1 分鐘)
      - 客戶端重連後 replay
    bridge 重啟:
      - 客戶端自動重連 (exponential backoff)
      - 重連後重新發送 last_id
    訊息過大:
      - > 64KB 拒絕並 error
    未知 type:
      - 忽略不回 error (向前相容)
  
  任務 vs 事件:
    task: 客戶端發起，server 處理後回 task_result
    event: server 主動推送 (emotion, motion, system)
```

---

### 8. 測試策略太晚 🟡 中

**問題：**
Phase 1 寫完才 138 tests、覆蓋率 0%。
v0.2 還要做 1.75 技術債清理才拉到 83%。

**修訂內容：**

**修訂原則：「code 寫完就測，不留 Phase 1.75 還債」**

```yaml
testing_policy:
  before_coding:
    - 寫 test stub (TDD 紅燈)
    - 或至少寫 test plan
  
  after_coding:
    - 跑 unit test
    - 跑覆蓋率 (目標 > 80%)
    - 寫 integration test (跨模組)
  
  before_commit:
    - python -m pytest tests/bridge/ -v 全綠
    - git diff 看有沒有改 test 配套
  
  禁止:
    - 寫完 code 不寫 test
    - "之後再補"的心態
    - Phase 結束才統一測試
  
  metric:
    - 每次 commit 前覆蓋率不能降
    - < 70% 視為技術債
```

**Phase 1 補做：**
- v0.2 已達 83% 覆蓋 ✅
- 之後維持 > 80%

---

### 9. 部署 / OS 客製化寫太早 🟡 中

**問題：**
計畫書 Phase 4-6 規劃了：
- Ubuntu Server 24.04 LTS 雙系統
- systemd kiosk 模式
- Packer image
- OTA

這些是「最遠的東西先寫」。當下 v0.2 還在：
- Windows 跑 Unity
- Python bridge
- 18-20s 回應

**修訂內容：**

**修訂原則：「近的先寫，遠的先不寫」**

```
[近] v0.x:  Windows + Python + MiniMax API
  ├─ Streaming 解決
  ├─ AgentOS 端到端
  ├─ 工具系統雛形
  └─ (這層不動 OS 客製化)

[中] v1.x:  Linux 嘗試 (用 VM / WSL2 模擬)
  ├─ 不用裝 Ubuntu 主機
  ├─ 在 WSL2 試 systemd
  └─ 試 kiosk 模式

[遠] v2.0+: 真的做雙系統
  ├─ 真的裝 Ubuntu
  ├─ Rust siro-runtime
  └─ Packer image + OTA
```

**刪除/降級 Phase 4-6 細節：**
- 不要詳細寫 Packer image 怎麼做
- 不要詳細寫 OTA 升級怎麼實作
- 寫「v2.0+ 啟動」就好

**新增章節 5.5 階段規劃原則：**

```
優先級排序（由近到遠）：
  1. 當下卡住的問題 (e.g. Streaming)
  2. v0.x 結束前會用到的
  3. v1.x 啟動前要準備的
  4. v2.0+ 願景 (寫輕一點)

絕對不要：
  - 把 v2.0+ 願景寫得比 v0.x 還詳細
  - 把 v1.x 沒做的事寫進 v0.x
  - 為了計畫書漂亮而擴大 scope
```

---

### 10. 失敗處理 / 降級路徑沒寫 🟡 中

**問題：**
計畫書風險登記只有「失敗處理」四個字。
v0.2 一個一個踩雷：LLM 死、Unity 死、網路斷、磁碟滿。

**修訂內容：**

新增章節 **8.6 降級路徑設計**：

```yaml
failure_scenarios:
  LLM 死:
    現象: API 5xx 或 timeout
    檢測: 30 秒無回應
    動作: 
      - 切換 Ollama 本地
      - 角色表情轉「思考中」
      - 不讓使用者卡在 UI
    
  Ollama 也死:
    現象: 本地 LLM 也掛
    動作:
      - 用 persona YAML 預設回應池
      - 角色保持「思考中」
      - log 詳細錯誤
    
  Bridge 死:
    現象: Python process crash
    檢測: systemd watchdog (10 秒)
    動作: 
      - systemd 重啟
      - Unity 自動重連 WS
      - 對話歷史持久化 (SQLite)
    
  Unity 死:
    現象: Unity crash / 卡住
    動作:
      - systemd 重啟 Unity kiosk session
      - 角色「重啟中」說明
      - 對話不中斷 (bridge 緩衝)
    
  網路斷:
    現象: 雲端 API 不可達
    動作:
      - 切本地 Ollama
      - 工具呼叫離線降級 (calendar 失敗但可以查本地)
      - UI 顯示「離線模式」icon
    
  磁碟滿:
    現象: log 寫不下
    動作:
      - logrotate
      - 對話歷史移到 USB / 雲端
      - 桌面通知使用者
    
  VRAM 爆:
    現象: 本地 LLM OOM
    動作:
      - 自動切更小模型 (7B → 3B)
      - 切雲端 fallback
    
使用者視角:
  - 桌寳絕對不「突然消失」
  - 永遠有回應 (即使 AI 笨了)
  - 失敗有「人話」說明 (不是 error code)
```

---

### 11. 「OS」定義模糊 🟡 中

**問題：**
計畫書一邊說「OS = 開機看到角色」「沒有傳統桌面」，
一邊又說「在 Windows 跑 Unity」「雙系統」。

**到底要做 OS 還是 app？** 沒定論，影響 Phase 4-6。

**修訂內容：**

新增章節 **1.5 OS 定義釐清**：

```yaml
os_定義:
  
  v0.x (現在):
    定位: 桌寳 app (跑在 Windows)
    理由: 
      - Ubuntu 雙系統要硬體、磁碟分割
      - v0.x 還在 debug 對話，不適合底層
      - 1 人本機測試不需要 OS 等級
    限制: 知道不是「OS」是 app
  
  v1.x (中期):
    定位: Linux app (跑在 WSL2 / 雙系統)
    理由:
      - 測試 systemd 整合
      - 測試 kiosk 模式
      - 不切磁碟分割
    限制: 仍是 app，只是 host 是 Linux
  
  v2.0+ (願景):
    定位: AI Agent OS
    理由:
      - Rust siro-runtime
      - 開機直接是 Live2D
      - 沒有傳統桌面
    限制: 這是願景，不是 v0.x 目標

判斷標準 (什麼時候算 OS):
  1. 開機到角色 < 5 秒 ✅ 還沒達到
  2. 沒有傳統桌面 (取代) ❌ 還沒取代
  3. systemd 管理 SIRO 全棧 ❌ 還沒做
  4. 24/7 穩定跑 7 天 ❌ 還沒驗證
  5. OTA 升級不中斷 ❌ 還沒做

結論: v0.x 是「桌寳 app」，不是 OS。
     v2.0+ 才開始追求 OS 等級。
```

**實務影響：**
- v0.x 不要被「OS」這個詞綁架
- 該用 Windows 就用 Windows
- 該用 app pattern 就用 app pattern
- v2.0+ 再來談 OS

---

### 12. 開發者 = 使用者盲點 🟡 中

**問題：**
你一個人寫，一個人用。
- 你以為合理的，使用者不一定合理
- 計畫書缺「非工程師會怎麼用」這層考量
- 沒 user testing

**修訂內容：**

新增章節 **11 使用者驗證**：

```yaml
user_testing:
  
  v0.x 階段 (單人):
    開發者 = 使用者
    - 自己做 user testing
    - 寫 user diary (每天跟 Mao 講話的紀錄)
    - 找 1-2 個親友試用 (錄影回饋)
  
  v1.x 階段 (小眾):
    找 2-5 個非工程師試用
    - 設定時間 (1 週)
    - 每天記錄: 用什麼、卡什麼、放棄什麼
    - 不能問「為什麼不用」(會被合理化)
    - 觀察: 用幾次、什麼情境、卡多久就放棄
    
  user_questions:
    每次 user test 問:
      - 你想讓 Mao 做什麼？
      - 為什麼想這樣做？
      - 卡在哪？
      - 放棄了嗎？為什麼？
      - 跟其他 AI 比較？
  
  觀察指標:
    - 啟用率: 收到後 7 天內還會用
    - 留存: 第 30 天還會用
    - 失敗模式: 卡多久放棄
    - 真實需求: 跟「使用者以為需要」的落差

  重要: 開發者假設永遠錯。
       唯一驗證方式: 看別人用。
```

**Phase 1 補做：**
- [ ] 寫 user diary
- [ ] 找 1-2 個親友試用
- [ ] 錄影觀察

---

### 13. 時間預估太樂觀 🟡 中

**問題：**
Phase 1 寫 2-3 週，實際 v0.x 已經搞了一個多月。
**每個 Phase 都被低估，沒 buffer 沒保險。**

**修訂內容：**

**修訂原則：「3x 經驗法則」**

```
原本估的時間 × 3 = 實際時間

理由:
  - debug 一定超時
  - 套件版本衝突
  - 文件不齊
  - 環境差異
  - 自己擺爛幾天
```

**時間軸重寫：**

```yaml
# 原本
phase_1: 2-3 週
phase_2: 1-2 週
phase_3: 3-4 週

# 改成
phase_1: 6-8 週 (含 1.5/1.75 補完)
phase_2: 4-6 週
phase_3: 8-12 週

加 buffer:
  buffer: 30% 額外時間
  理由: 突發狀況、家人朋友來找
```

**驗證方式：**
- 每次 Phase 開始記「開始時間」
- 結束記「結束時間」+「實際花費」
- 對比「原本預估」
- 調整下次預估

---

### 14. 沒有「什麼不做」清單 🟢 低

**問題：**
計畫書都在寫「要做什麼」，
沒寫「不做什麼」（不做 Linux、kiosk、OTA 之類）。

**修訂內容：**

新增章節 **1.6 範圍邊界**：

```yaml
v0.x 不做:
  - 真正的作業系統 (v2.0+)
  - Ubuntu 雙系統
  - 開機直接是角色
  - 取代傳統桌面
  - 沒有視窗管理員
  - Rust siro-runtime
  - OTA 升級
  - Packer image
  - 多裝置 (家人朋友版)
  - 雲端同步
  - 多用戶
  - 帳號系統
  - 付款 / 訂閱
  - App Store
  - i18n 多語 (只有繁中)

v0.x 只做:
  - 桌寳 app (Windows)
  - 1 個角色 (Mao)
  - 中文對話
  - 雲端 LLM (MiniMax)
  - 基本表情切換
  - WebSocket 通訊
  - 文字輸入
  - (選配) TTS / STT
```

**為什麼重要：**
- 防止 scope creep
- 讓自己聚焦
- 給未來的你「當初決定不做」的理由

---

### 15. 文件先寫完再寫 code 🟢 低

**問題：**
計畫書 8000+ 行 HTML，實際 code 跟計畫書對不上。
**Agile 應該是「先做、做中想、做完補」。**
你順序顛倒：先寫完文件再開工。

**修訂內容：**

**修訂原則：「code-first, doc-second」**

```yaml
新工作流程:
  1. 先寫小 code (半天)
  2. 跑起來確認方向
  3. 覺得對了再寫文件
  4. 文件不超過 1 頁 A4
  5. code 變了再改文件
  
  禁止:
    - 沒寫 code 就寫詳細文件
    - 文件 8000 行 code 0 行
    - 文件當成「給別人看」的心態
    - 文件當成「拖時間」的工具
  
  文件原則:
    - 短而準
    - 跟著 code 走
    - STATUS.md 是主文件
    - 計畫書是參考不是聖經
```

**v0.2 已驗證：**
- STATUS.md 寫得很紮實（事後整理）
- 計畫書寫得很完整（事先規劃）
- **事後整理的 STATUS.md 比事先規劃的計畫書有用**
- 這就是驗證

---

## 修訂合併建議

**回主計畫書 `LIVE2D_AI_AGENT_OS_PLAN.md` 改動：**

```diff
# 風險登記章節新增
+ 8.5 廠商風險管理 (對應 #5)
+ 8.6 降級路徑設計 (對應 #10)

# 介面契約章節新增
+ 6.2 WebSocket 通訊協定 (對應 #7)
+ 6.5 LLM Streaming 設計 (對應 #1)

# 架構總覽章節新增
+ 1.5 OS 定義釐清 (對應 #11)
+ 1.6 範圍邊界 (對應 #14)
+ 3.5 語言邊界細節 (對應 #2)

# 階段規劃章節修改
~ 5.x 階段規劃原則 (對應 #9)
~ 各 Phase 預估時間 ×3 (對應 #13)

# 新增章節
+ 9.5 KPI 量化指標 (對應 #4)
+ 11 使用者驗證 (對應 #12)
+ 12 測試策略 (對應 #8)
+ 13 Persona 設計原則 (對應 #6)
+ 14 AgentOS 設計原則 (對應 #3)
+ 15 文件原則 (對應 #15)
```

---

## 給未來自己的提醒

1. **這份 v2.1 是 v0.2 實作後的回顧，不是新計畫。**
2. **v0.3-v1.0 期間繼續累積問題，v3.0 再做下次修訂。**
3. **不要倒回來追求 v2.0 完美，當下 v0.x 跑通最重要。**
4. **計畫書 = 願景，STATUS.md = 現實，兩者要分開看。**

---

**最後一句話：**

**這 15 項不嚴謹，是 v0.x 發現的「正常的代價」。** 不是計畫書失敗，是「先寫完再開工」的副作用。**接下來 v0.3 開始，每次踩雷都回來補這份清單，v3.0 計畫書才會真的嚴謹。**

---

> 修訂紀錄：
> - v2.1（2026-06-04）：新增 15 項不嚴謹處 + 修訂方案
> - v2.0（2026-06-02）：原始規劃
