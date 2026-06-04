# SIRO Agent OS — 架構文件

> v0.2+ 設計：把 bridge 從「純 HTTP server」升級成「**像作業系統一樣的後台 + 1 個前台 Mao**」
>
> v0.3 進度（2026-06-04）：骨架就緒 → `/chat` opt-in 走 AgentOS（`SIRO_USE_AGENT_OS=true`）。Task 加 `id`、EventBus `subscribe()` 回傳 `unsubscribe()`、新增 `wait_for_task()` helper。預設仍走 v0.2 sync 路徑（165 既有測試不動）。
> v0.4 進度（2026-06-04）：`SIRO_USE_AGENT_OS` 預設翻 `true`（v0.3 觀察穩定後翻）。設 `SIRO_USE_AGENT_OS=false` 可降回 v0.2 sync 路徑（逃生用）。

## 目標

使用者需求：「1 個人用、1 個 Mao、本機、開發可測試。後台像正常作業系統一樣有任務序列、多 LLM 並行、事件匯流。」

具體場景：使用者跟 Mao 對話的**同時**，後台可以：
- 跑時間排程（cron）
- 收 Telegram 訊息查股票
- 處理 Unity 點 Live2D 角色觸發的任務

這些都不應該卡 Mao 主對話。

## 架構

```
┌─ Frontend (Unity) ─┐         ┌─ Backend (bridge) ─────────────────────┐
│  - Mao (Live2D)     │         │  - HTTP/WS API (FastAPI)               │
│  - Chat input UI    │  WS     │  - Task Queue (asyncio.Queue)           │
│  - Click handlers   │ ←─────→│  - Event Bus (in-process pub/sub)      │
│                    │         │  - Triggers:                           │
│                    │         │    - UI click → enqueue task           │
│                    │         │    - Schedule (cron) → enqueue task    │
│                    │         │    - Telegram webhook → enqueue task   │
│                    │         │  - Workers:                            │
│                    │         │    - LLM worker (concurrent)            │
│                    │         │    - Schedule worker (loop)            │
│                    │         │    - Telegram worker (polling)         │
│                    │         │  - Handlers:                           │
│                    │         │    - LLM reply → emit to Mao WS        │
│                    │         │    - Stock query → emit to Telegram    │
│                    │         │    - Mao click → enqueue custom task   │
└────────────────────┘         └────────────────────────────────────────────┘
```

## 核心元件

### 1. AgentOS (`bridge/agent_os.py`)

```python
class AgentOS:
    def __init__(self):
        self.task_queue: asyncio.Queue[Task]  # 背景任務 FIFO
        self.event_bus = EventBus()  # pub/sub
        self._workers: List[asyncio.Task]  # worker pool

    async def start(self, num_workers=3): ...
    async def stop(self): ...  # graceful shutdown
    def enqueue(self, task: Task): ...  # 同步介面
    @property
    def event_bus: EventBus
    @property
    def queue_size: int
    @property
    def processed_count: int
```

### 2. Task / Event 資料結構

```python
@dataclass
class Task:
    name: str  # "llm.reply", "telegram.stock_query", "schedule.daily_weather"
    coro_factory: Callable[..., Awaitable[Any]]
    args: tuple
    kwargs: dict

@dataclass
class Event:
    type: str  # "task.completed", "task.failed", "llm.reply", ...
    data: dict
    source: str  # "worker-1", "telegram-bot", "schedule-loop"
```

### 3. EventBus (in-process pub/sub)

- 訂閱：`bus.subscribe("event.type", handler)`
- 萬用：`bus.subscribe("*", handler)` 收所有事件
- 同步 / async handler 都支援
- handler 拋 exception 不影響其他訂閱者
- `bus.emit(event)` 觸發

## 觸發源 → 任務 → Handler 範例

| 觸發源 | Task name | Handler 動作 |
|---|---|---|
| Unity 送 WS `chat` message | `llm.reply` | 跑 hermes、回 LLM 結果 + 情緒標籤給 Unity |
| Unity 點 Live2D 角色 | `mao.click` | 播對應 motion、發回應 text |
| Telegram 收到「查 2330」 | `telegram.stock_query` | 抓股價、Telegram bot 回 |
| 排程早上 8 點 | `schedule.daily_weather` | 抓天氣、推給 Mao WS 顯示 |

每個觸發源都是「**enqueue task → worker 跑 → 發 event → handler 收**」。

## 設計原則

### 單 process、單 Mao（明確選擇）
- 使用者明確「永遠只有 1 個 Mao」→ Unity 不做 multi-Mao manager
- 不需要 Redis / 多 process — 1 個 Python process 用 `asyncio` 就能並行
- 1 台機器 = 1 個 bridge = 多個 Unity clients（如果要的話）

### Bridge 是「後台 OS」、不是 stateless API
- 之前把 bridge 當 stateless server — 任何 state 都丟前端
- v0.2+ 開始有 in-process state：AgentOS、event bus、session 歷史
- 設計文件見各 task 的 source file

### 不要過度工程
- v0.2 只做最小可用骨架：AgentOS + EventBus + 第一個 task
- v0.3 把 `/chat` 接上 AgentOS（opt-in via `SIRO_USE_AGENT_OS` env flag）— 證明「task 進得了 queue、等得到 result」
- Telegram / 排程 / LLM tool calling 等 v1+ 才加
- 不做 state persistence（v2 才加 SQLite）

## 怎麼寫新任務

`bridge/tasks/<task_name>.py`：

```python
from ..agent_os import Task

def create_my_task(*, state, **kwargs) -> Task:
    return Task(
        name="my.task",
        coro_factory=_run_my_task,
        kwargs={"state": state, **kwargs},
    )

async def _run_my_task(*, state, **kwargs):
    # 你的邏輯
    result = ...
    return result
```

在 endpoint / 觸發源內：
```python
state.agent_os.enqueue(create_my_task(state=state, foo="bar"))
```

訂閱完成事件（如果要推回 Unity）：
```python
async def on_completed(event: Event):
    if event.data["task"] == "my.task":
        await websocket.send_json({...})

state.agent_os.event_bus.subscribe("task.completed", on_completed)
```

## 範圍演進

### v0.2 — 骨架

**已做**：
- ✅ `bridge/agent_os.py` — Task Queue + Event Bus + Worker Pool
- ✅ `bridge/tasks/llm_reply_task.py` — 第一個任務（API 存在，但 endpoint 還沒呼叫）
- ✅ `bridge/main.py` lifespan 啟動 AgentOS（3 個 worker）
- ✅ `state.sessions_lock` — RLock 保護 sessions 並行讀寫
- ✅ 14 個單元測試

### v0.3 — 接到 endpoint（opt-in）

**新增**：
- ✅ `Task.id` 欄位（UUID4 hex[:8]）— 給 event 比對用
- ✅ `EventBus.subscribe()` 回傳 `unsubscribe()` — 避免 handler 殘留
- ✅ `AgentOS.wait_for_task(name, id, timeout)` — endpoint 等特定 task 完成
- ✅ `bridge/tasks/llm_reply_task.py` — 真的被 `/chat` 呼叫了（透過 `create_llm_reply_task()` factory）
- ✅ `state.use_agent_os` — v0.3 預設 false（opt-in），**v0.4 翻預設 true**（default-on）
- ✅ `state.use_agent_os` 設 `false` 可降回 v0.2 sync 路徑（逃生用、v0.4 翻預設後重要）
- ✅ 6 個 EventBus 測試（unsubscribe 不影響別人）+ 4 個 wait_for_task 測試（completed / failed / timeout / id 過濾）+ 3 個 Task.id 測試（唯一性 / 預設長度 / override）+ 4 個 /chat 整合測試
- ✅ 總計 23 個 AgentOS 測試 + 4 個整合測試 = 27 個

**設計決策**：
- 預設關閉（v0.2 sync 路徑保留）— 165 既有測試不用改、production 行為不變
- v0.4 觀察穩定後預設改 true
- `wait_for_task` timeout 不 cancel task（worker 仍會跑完）— 避免「client timeout → task 半完成」的競態

**未做**（v1+）：
- ❌ Telegram bot
- ❌ 排程/cron
- ❌ Unity WS `task` message type
- ❌ `HermesBridgeClient.SendTask()`
- ❌ `Live2DModelController.OnClick()` 觸發 task
- ❌ LLM tool calling（Mao 自己召喚任務）
- ❌ 任務持久化（SQLite / Redis）

## v1+ Roadmap

| Phase | 場景 | 改動 |
|---|---|---|
| **v1.0** | Telegram 整合 | `bridge/telegram_bot.py`（polling 模式），handler 把訊息 enqueue `telegram_msg` task |
| **v1.1** | 排程 | `bridge/scheduler.py`，asyncio loop + cron parser |
| **v1.2** | Unity 點 Live2D → task | Unity 端 `OnClick()`、`HermesBridgeClient.SendTask()`、WS 支援 `task` message type（**規格見下「v1.2 SendTask + OnClick 規格」**） |
| **v1.5** | LLM tool calling | bridge 支援 function calling schema，Mao 可以召喚任務（查股票、設提醒） |
| **v2.0** | 任務持久化 | SQLite、bridge 重啟可恢復；multi-process / K8s 部署就緒 |

---

## v1.2 SendTask + OnClick 規格（v1.2 規劃文件 — 2026-06-04 寫）

> 目的：Unity 不只能「等回應」（`/chat` response 訊息），還能「**主動推 task 進 AgentOS**」做後續操作。
> 場景：點 Mao 頭 → 觸發 `mood.set happy` → bridge 設 Mao 情緒、下次 chat 用新 mood。
> 跟 v0.4+ commit 0dd9da7（incremental render）方向相反 — incremental render 是 bridge → Unity 推文字；SendTask 是 Unity → bridge 推 task。

### 1. WS message types（bridge ↔ Unity）

**Unity → bridge 送 task**（fire-and-forget 模式，可選等 result）：
```json
{ "type": "task", "task_id": "abc12345", "name": "mood.set", "args": { "emotion": "happy" } }
```

**bridge → Unity 三種 reply**：
```json
// 1. 已收下（task 進 queue）
{ "type": "task_ack", "task_id": "abc12345", "status": "accepted" }

// 2. 完成（success）
{ "type": "task_result", "task_id": "abc12345", "result": { "ok": true } }

// 3. 失敗
{ "type": "task_failed", "task_id": "abc12345", "error": "mood.set: invalid emotion 'foo'" }
```

**task_id 規範**：Unity 端生 UUID4 hex[:8]（跟 Python `Task.id` 同步格式），避免跟 bridge 內部 task id 撞。

### 2. Unity C# API

**`HermesBridgeClient`**：
```csharp
// fire-and-await：包好 task_id、發送、等 task_result 或 task_failed 回來
public async Task<JObject> SendTaskAsync(string name, JObject args, float timeoutSec = 5.0f);

// subscribe pattern：訂閱這兩個 event、自己做 correlation（用 task_id）
public event Action<TaskResult> OnTaskResult;
public event Action<TaskError> OnTaskFailed;
```

**`Live2DModelController`**（Cubism hit detection）：
```csharp
// Cubism SDK 點擊 Mao 任一 hit area 觸發（head/body/自訂）
// 內部組 { hit_area: "head", event: "click" } 推 SendTask
// persona YAML 配 clickable_areas: [{ area: "head", task: "mood.set", args: {emotion: "happy"} }]
public event Action<string> OnMaoClicked;  // 參數：hit area name
```

### 3. 預設 task 種類（v1.2 第一波）

| task name | args | 用途 | Mao 行為 |
|---|---|---|---|
| `mood.set` | `{emotion, intensity?}` | 設當前 mood、emotion_parser 後續 chat 用 | 立即切表情 |
| `motion.play` | `{motion_group, motion_index}` | 播指定 motion | 立即播 |
| `persona.switch` | `{persona_id}` | 切換 persona | 重載 Live2D model + 更新 UI |
| `chat.say` | `{text}` | Mao 主動說話（不需 user 觸發） | TTS + 表情（v1.5+ 才有 TTS） |
| `chat.summon` | `{}` | Mao 召回對話（「嘿、在嗎？」） | Mao 開口的視覺 + log |

### 4. 連線中斷處理

- Unity 送 task 後連線斷 → 記在 Unity 端 pending queue、重連後 batch 查詢
- 或：v1.2 先接受「斷線 = 丟 task」、console warning；v2.0 持久化再開 queue

### 5. 驗收條件

- [ ] Unity 點 Mao 頭 → 100ms 內 task 進 bridge queue
- [ ] task 結果 1s 內回 Unity（不含 LLM task — LLM task 可等幾秒）
- [ ] task 失敗 → Unity console 印 error、不閃退
- [ ] 連線中斷時 task silently lost 有 console warning（v1.2 不要求持久化）
- [ ] 8 個單元測試：
  - SendTaskAsync 產生合法 task_id（UUID4 hex[:8]）
  - bridge 收到 `task` → enqueue AgentOS → 推 `task_ack`
  - task 成功 → 推 `task_result`（correlation 對）
  - task 失敗 → 推 `task_failed`（error message 帶到 Unity）
  - Unity 訂閱 event 沒收 ack → 5s timeout raise exception
  - 連線斷時 SendTaskAsync raise、pending task 標 retry-pending
  - 未知 task name → `task_failed` error="unknown task"
  - 同 task_id 送兩次 → 第二個被 reject（避免 race）

### 6. 實作順序（建議）

1. bridge 端 WS message handler（接 `task`、推 ack/result/failed）— 0.5 天
2. AgentOS 內建 `task` registry（內建 mood.set / motion.play / persona.switch / chat.say / chat.summon）— 0.5 天
3. Unity `HermesBridgeClient.SendTaskAsync` + event — 0.5 天
4. Unity `Live2DModelController` Cubism hit area 偵測 + persona YAML `clickable_areas` 對應 — 0.5 天
5. 8 個單元測試 — 0.5 天
6. Unity Play 模式手動驗證 + persona YAML example — 0.5 天

**總計 ~3 天**（半天細項不計）

### 7. 跟現有 WS protocol 的關係

- 純 additive（加新 type、不改既有 message）
- 跟 v0.4+ commit 0dd9da7（incremental render）**互不影響** — 方向相反
- 跟 v0.3 `task` 在 AgentOS 內部已存在（`create_llm_reply_task`）— WS `task` 是新介面、內部還是 `state.agent_os.enqueue(InternalTask)`

## 跟 Mao 對話的內部流程（v0.2 vs v0.3）

### v0.2 — 預設路徑（SIRO_USE_AGENT_OS 未設或 =false）

```
Unity WebSocket 送 {"type": "chat", "message": "..."}
        ↓
bridge /ws 端點
        ↓
hermes.chat() via asyncio.to_thread (不卡 event loop)
        ↓
parser.parse() 取 emotion
        ↓
state.sessions[session_id] (RLock 保護)
        ↓
WebSocket 回 {"type": "response", "text": "...", "emotion": "..."}
        ↓
Unity EmotionDisplay 切表情
```

### v0.3 — opt-in 路徑（SIRO_USE_AGENT_OS=true）

```
Unity WebSocket 送 {"type": "chat", "message": "..."}
        ↓
bridge /ws 端點（或 /chat HTTP — 兩條都走同個 handler）
        ↓
create_llm_reply_task(state, user_id, message, persona, session)
        ↓
state.agent_os.enqueue(task)  ← task.id 進 queue
        ↓
Worker 從 queue 拉 task 跑：
   - asyncio.to_thread(hermes.chat) — 不卡 worker event loop
   - parser.parse() 取 emotion
   - state.sessions[session_id] 寫入（task 內做，endpoint 不重複寫）
   - emit "task.completed" event 帶 task_id + result dict
        ↓
endpoint await state.agent_os.wait_for_task("llm.reply", task.id, 600s)
        ↓
拿 result 組 ChatResponse 回 Unity
```

**v0.3 跟 v0.2 行為差異**：
- v0.2: 單一 request 走 asyncio.to_thread，event loop 讓出 1 次
- v0.3: enqueue → 切去 worker → endpoint 用 event bus 等 callback，request handler 跟 worker 完全解耦
- 失敗處理：v0.2 直接 raise；v0.3 task.failed event 帶 error 字串 → 走 fallback
- Timeout：v0.2 沒有；v0.3 有 600s 預設（任務仍在 worker 跑、不 cancel）

## 驗收測試

`tests/bridge/test_agent_os.py`（**23 個**）：
- 6 個 EventBus 測試（subscribe/emit、wildcard、multi-subscriber、exception 隔離、sync handler、no-subscriber）
- 2 個 EventBus unsubscribe 測試（v0.3：subscribe 回傳 unsub / 不影響別人）
- 4 個 AgentOS Workers 測試（start/stop、enqueue、並行、failure 隔離、event firing）+ wait_for_task 測試放在下面
- 3 個 sessions_lock 併發測試（concurrent append、RLock nested、100 thread stress）
- 4 個 `wait_for_task` 測試（v0.3：completed / failed / timeout / 同名不同 id 過濾）
- 3 個 `Task.id` 測試（v0.3：唯一性 / 預設 8 字 hex / 可 override）

`tests/bridge/test_agent_os_integration.py`（**4 個**，v0.3 新增）：
- flag=true 時 /chat 確實 enqueue + 拿 result 組 ChatResponse
- hermes.chat 失敗 → 走 fallback（200 而非 502）
- flag 預設 false（沒設 env）
- env=true 觸發 flag

執行：
```bash
python -m pytest tests/bridge/test_agent_os.py tests/bridge/test_agent_os_integration.py -v
```

## 怎麼看 AgentOS 跑起來

啟動 bridge 會看到：
```
AgentOS 啟動（3 個 worker，task queue + event bus 就緒）
```

之後每個 enqueue 會 log（**v0.3 格式帶 [id=xxx]**）：
```
[AgentOS] worker 1 跑 llm.reply[id=a3f8b2c1] (queue 等待 5ms)
[AgentOS] llm.reply[id=a3f8b2c1] 完成 (12ms)
```

v0.3 多了：
- `[id=xxx]` — Task.id（UUID4 hex[:8]）— endpoint 對應 task 用
- 失敗時 log 改 `logger.exception` 帶 stack trace
- 失敗會 emit `task.failed` event 帶 `task_id` + `error` + `traceback`

可以從這看出 task 排隊 / 執行 / 完成時間，方便除錯效能問題。
