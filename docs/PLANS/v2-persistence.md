# v2.0 任務持久化設計

> **目標版本**：v2.0（2027 1-3 月規劃）
> **對應 PLAN 段**：[LIVE2D_AI_AGENT_OS_PLAN.md §v2.0](../../LIVE2D_AI_AGENT_OS_PLAN.md)
> **對應 GAPS**：[GAPS.md #4 離線、#5 災難恢復](../../docs/GAPS.md)
> **狀態**：v0.x 已 ship、v2.0 開工前 design doc

## 為什麼 v2.0 要做

v0.x 的 in-memory `state.sessions` 有 3 個致命問題：

1. **bridge 重啟 = 全部對話歷史不見**
   - 開發時 Ctrl+C 一下、昨天聊的 50 輪消失
   - production 24/7 systemd 服務也會 OOM kill、必須重啟
2. **v1.2 SendTask 沒法「pending → replay」**
   - Unity 推 `SendTask` 後、bridge 掛了、task 直接消失
   - user 不知道「SIRO 到底做了沒」
3. **無法水平擴展**
   - v1.x 想開多個 worker process 撐併發、in-memory state 不能跨 process 共享
   - 必須有 shared state backend

## 一句話結論

**bridge 改用 SQLite 取代 in-memory `state.sessions`**（對話歷史 + task queue + worker state 全部落盤）。
**SendTask 升級**：v1.2 的 `SendTaskAsync` 從「斷線 = 丟 task」變「斷線 = pending → 重連後 replay」。

---

## 設計原則

1. **漸進式替換**：v2.0 在 v1.x 之上加 SQLite 落盤，**介面不變**（`state.sessions` 仍存在、底下換 backend）
2. **先讀後寫**：對話歷史先讀 SQLite cache 進 RAM、寫入時同步落盤
3. **append-only**：對話歷史只 append、不修改（方便 debug / replay）
4. **task 狀態機明確**：`pending → running → done | failed | cancelled`，任何時候 crash 都能從 SQLite 撈回
5. **bridge 啟動時 recovery**：掃 `status IN ('pending', 'running')` 的 task、視情況 retry / fail

---

## 資料模型

### sessions 表（取代 `state.sessions`）

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    persona    TEXT NOT NULL DEFAULT 'siro-default',
    created_at INTEGER NOT NULL,  -- unix ms
    updated_at INTEGER NOT NULL,
    metadata   TEXT               -- JSON blob（client 額外資料）
);

CREATE INDEX idx_sessions_user ON sessions(user_id, updated_at DESC);
```

### messages 表（取代 `state.sessions[id] = [...]`）

```sql
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content     TEXT NOT NULL,
    emotion     TEXT,             -- happy / sad / ...
    expression  TEXT,             -- Live2D exp_01 等
    tool_name   TEXT,             -- v1.5+ tool_use
    tool_args   TEXT,             -- JSON
    tool_result TEXT,             -- JSON
    created_at  INTEGER NOT NULL
);

CREATE INDEX idx_messages_session ON messages(session_id, id DESC);
```

### tasks 表（取代 AgentOS in-memory queue）

```sql
CREATE TABLE tasks (
    id          TEXT PRIMARY KEY,           -- UUID
    name        TEXT NOT NULL,              -- 'llm.reply' / 'unity.sendtask' / ...
    payload     TEXT NOT NULL,              -- JSON 序列化
    status      TEXT NOT NULL CHECK(status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    result      TEXT,                       -- JSON（done 時填）
    error       TEXT,                       -- failed 時填
    worker_id   TEXT,                       -- running 時是哪個 worker
    enqueued_at INTEGER NOT NULL,
    started_at  INTEGER,
    finished_at INTEGER,
    attempts    INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3
);

CREATE INDEX idx_tasks_pending ON tasks(status, enqueued_at) WHERE status = 'pending';
CREATE INDEX idx_tasks_session ON tasks(json_extract(payload, '$.session_id'));
```

### audit_log 表（既有 v1.5+ actions 落盤）

```sql
CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id    TEXT,
    action     TEXT NOT NULL,    -- 'tool.execute' / 'memory.save' / ...
    target     TEXT,             -- sandbox path / shell cmd / ...
    result     TEXT,             -- 'ok' / 'denied' / 'error'
    detail     TEXT,             -- JSON
    created_at INTEGER NOT NULL
);
```

> **既有 v1.5+**：`bridge/data/siro-memory.db` 已經用 SQLite 做長期記憶。
> v2.0 把 audit log 也加進去、跟 memory 同一個 DB 檔（`siro-data.db`）。

---

## 模組結構

```
bridge/
  state/
    __init__.py
    schema.sql             # CREATE TABLE 全部
    backend.py             # StateBackend protocol
    sqlite_backend.py      # 實作
    memory_backend.py      # 內存實作（v2.0 之前、保留 fallback）
  agent_os.py              # 用 backend 取代 in-memory queue
  main.py                  # state.sessions 改用 backend.get_session()
  tools/memory.py          # 已經用 SQLite（v1.5+ 既有）
  data/siro-data.db        # v2.0 single source of truth
```

### `StateBackend` protocol

```python
class StateBackend(Protocol):
    # sessions
    async def get_or_create_session(self, session_id: str, user_id: str, persona: str) -> Session: ...
    async def list_sessions(self, user_id: str, limit: int = 20) -> list[Session]: ...
    async def delete_session(self, session_id: str) -> None: ...

    # messages
    async def append_message(self, session_id: str, message: Message) -> None: ...
    async def get_history(self, session_id: str, limit: int = 20) -> list[Message]: ...
    async def search_messages(self, user_id: str, query: str, limit: int = 20) -> list[Message]: ...

    # tasks
    async def enqueue_task(self, task: Task) -> None: ...
    async def claim_next_task(self, worker_id: str) -> Optional[Task]: ...
    async def update_task_status(self, task_id: str, status: str, **kwargs) -> None: ...
    async def list_pending_tasks(self) -> list[Task]: ...
    async def wait_for_task(self, task_id: str, timeout_sec: float) -> Task: ...

    # audit
    async def log_audit(self, audit: AuditEntry) -> None: ...
    async def get_audit(self, session_id: Optional[str], limit: int = 50) -> list[AuditEntry]: ...
```

兩個實作：
- `MemoryBackend`：v0.x 既有的 in-memory dict（保留給 unit test）
- `SQLiteBackend`：v2.0 production

---

## Bridge 啟動 Recovery 流程

```python
async def startup_recovery(backend: StateBackend):
    # 1. 撈所有 status=pending 的 task（bridge 掛之前還沒被 worker 拉走的）
    pending = await backend.list_tasks(status='pending')
    for task in pending:
        logger.info(f"recovery: task {task.id} still pending, keep for re-pickup")
    # 不做事、worker 會自然挑走

    # 2. 撈所有 status=running 的 task（bridge 掛時正在跑）
    running = await backend.list_tasks(status='running')
    for task in running:
        # 標記成 pending + attempts++、讓 worker 重試
        await backend.update_task_status(task.id, 'pending', error='bridge crashed during execution')
        logger.warn(f"recovery: task {task.id} was running, reset to pending for retry")

    # 3. sessions / messages 不用處理（已落盤）
```

**設計取捨**：running 狀態直接重試、不分「可冪等」vs「不可冪等」。
理由：
- v1.x 95% task 是 `llm.reply`（呼叫 LLM、冪等因為 LLM 自己有 retry）
- v2.0 真有不可冪等 task 應該自己寫 `task.pre_check()` hook
- 工程複雜度：直接 reset pending = 5 行 code

---

## SendTask 升級（v1.2 → v2.0）

### v1.2 行為
```python
# Unity 端
await bridge.SendTask("mood.set", {"mood": "happy"})

# bridge 端
async def handle_send_task(task: Task):
    if bridge_offline:  # Unity 跟 bridge 斷線
        return None     # task 丟失、Unity 不知道
```

### v2.0 行為
```python
# Unity 端
task_id = await bridge.SendTask("mood.set", {"mood": "happy"})

# bridge 端
async def handle_send_task(task: Task) -> str:
    # 1. task 寫入 SQLite (status=pending)
    await backend.enqueue_task(task)
    # 2. 立刻回 task_id 給 Unity（不等 worker 跑）
    return task.id

# Unity 收到 task_id 後可以：
#   - wait_for_task(task_id) 等結果（可選）
#   - 斷線後重連、query task_id 狀態

# worker 從 SQLite 撈 task、跑、寫 result
async def _worker_loop():
    while True:
        task = await backend.claim_next_task(worker_id)
        if task:
            result = await task.run()
            await backend.update_task_status(task.id, 'done', result=result)
        await asyncio.sleep(0.1)
```

**Unity 端 v2.0 改動**：
- `SendTaskAsync` 回傳 `string task_id`（不是 `void`）
- 加 `WaitForTaskAsync(task_id, timeout_sec) -> TaskResult`
- WS 訂閱 `task.done` / `task.failed` 訊息、可在背景等

---

## 測試策略

### 單元測試
- `tests/bridge/state/test_sqlite_backend.py` — 50 個 case
  - CRUD all 4 tables
  - 並發 claim_next_task（模擬多 worker）
  - Recovery 流程模擬

### 整合測試
- `tests/integration/test_bridge_restart_recovery.py`
  - 啟動 bridge → enqueue 10 task → kill bridge (SIGKILL) → 重啟 → 確認所有 task 跑完

### 壓力測試
- `scripts/stress/test_persistence_load.py`
  - 灌 10000 條 message
  - 灌 1000 個 task
  - 量 bridge latency (P50 / P95 / P99)
  - 量 SQLite 檔案大小成長率

### 災難恢復（[GAPS #5](../../docs/GAPS.md) 對齊）
- L1 損壞（SQLite 檔案 corrupt）→ 自動從備份還原（每 10 分鐘 snapshot）
- L2 bridge crash → recovery 流程驗證
- L3 SSD 壞 → image restore + SQLite 從備份還原

---

## 預估時程（2027 1-3 月）

| 週 | 任務 |
|----|------|
| W1 | schema.sql + SQLiteBackend 雛型 + 單元測試 |
| W2 | AgentOS 整合 SQLiteBackend（in-memory 切換靠 env flag）|
| W3 | SendTask 升級 + Unity wait_for_task API + 整合測試 |
| W4 | Recovery 流程 + 壓力測試 + 文件 + 灰度發布 |

**對 v0.x 的改動**：
- v0.x 不動、v0.x 仍用 in-memory backend
- v2.0 開發時同步在 v1.x 維護兩個 backend
- v2.0 ship 後保留 memory backend 6 個月（給 unit test 用、不給 production）

---

## 跟 K9 (5歲到80歲會用) 的關係

K9 啟動時程：v2.0 正式啟動（[PLAN §11.5](../../LIVE2D_AI_AGENT_OS_PLAN.md)）。

v2.0 persistence 是 K9 啟動的**基礎**：
- user testing 跨越多週、需要對話歷史不丟
- 觀察「5 歲到 80 歲」用戶最常卡的地方、要回看對話歷史分析
- L1 災難恢復 < 5 分鐘、靠 SQLite 從備份還原

---

## 不在 v2.0 範圍

- ❌ multi-process worker pool（v2.0 仍單 process；v2.1+ 水平擴展）
- ❌ SQLite → PostgreSQL migration（v2.0 用 SQLite 即可；v3+ 才考慮）
- ❌ distributed task queue（Celery / RQ）— v2.0 還不需要
- ❌ 對話歷史 encryption（v2.0+ 1 個季度做；目前 GAPS #1 路線圖）
- ❌ 自動 backup 到雲端（v2.1 規劃、本地備份先做）

---

## 相關文件

- [LIVE2D_AI_AGENT_OS_PLAN.md §v2.0](../../LIVE2D_AI_AGENT_OS_PLAN.md) — 原始規劃
- [AGENT_OS.md](../../docs/AGENT_OS.md) — AgentOS 架構（要被 SQLite 取代的部分）
- [GAPS.md #4 #5](../../docs/GAPS.md) — 對應的 gap
- [docs/PLANS/agent-computer-control.md](agent-computer-control.md) — v1.5+ 已經用了 SQLite 做 memory（v2.0 整合進去）
- [CHANGELOG.md 2026-06-08 v1.5+](../../docs/CHANGELOG.md) — memory SQLite 既有實作

---

**最後一句話**：

v2.0 持久化是「**SIRO 真的 24/7 跑起來**」的基礎。
沒做之前 SIRO 是個 dev demo、做完之後 SIRO 是個 production service。
