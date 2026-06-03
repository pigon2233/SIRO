# SIRO Agent OS — 架構文件

> v0.2+ 設計：把 bridge 從「純 HTTP server」升級成「**像作業系統一樣的後台 + 1 個前台 Mao**」

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

## v0.2 範圍

**已做**：
- ✅ `bridge/agent_os.py` — Task Queue + Event Bus + Worker Pool
- ✅ `bridge/tasks/llm_reply_task.py` — 第一個任務（但還沒被 endpoint 呼叫，只是 API 存在）
- ✅ `bridge/main.py` lifespan 啟動 AgentOS（3 個 worker）
- ✅ `state.sessions_lock` — RLock 保護 sessions 並行讀寫
- ✅ 14 個單元測試

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
| **v1.2** | Unity 點 Live2D → task | Unity 端 `OnClick()`、`HermesBridgeClient.SendTask()`、WS 支援 `task` message type |
| **v1.5** | LLM tool calling | bridge 支援 function calling schema，Mao 可以召喚任務（查股票、設提醒） |
| **v2.0** | 任務持久化 | SQLite、bridge 重啟可恢復；multi-process / K8s 部署就緒 |

## 跟 Mao 對話的內部流程（v0.2+）

```
Unity WebSocket 送 {"type": "chat", "message": "..."}
        ↓
bridge /ws 端點
        ↓
（v0.2 仍用 sync hermes — 為了保持 UX 一致；未來可改 enqueue）
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

AgentOS worker pool 同步跑（但目前**還沒**被 /chat 呼叫 — 是「待機」狀態，等 v1+ Telegram / schedule 來用）。

## 驗收測試

`tests/bridge/test_agent_os.py`：
- 6 個 EventBus 測試（subscribe/emit、wildcard、multi-subscriber、exception 隔離、sync handler、no-subscriber）
- 5 個 AgentOS Workers 測試（start/stop、enqueue、並行、failure 隔離、event firing）
- 3 個 sessions_lock 併發測試（concurrent append、RLock nested、100 thread stress）

執行：
```bash
python -m pytest tests/bridge/test_agent_os.py -v
```

## 怎麼看 AgentOS 跑起來

啟動 bridge 會看到：
```
AgentOS 啟動（3 個 worker，task queue + event bus 就緒）
```

之後每個 enqueue 會 log：
```
[AgentOS] enqueue my.task (queue size: 0)
[AgentOS] worker 1 跑 my.task (queue 等待 5ms)
[AgentOS] my.task 完成 (12ms)
```

可以從這看出 task 排隊 / 執行 / 完成時間，方便除錯效能問題。
