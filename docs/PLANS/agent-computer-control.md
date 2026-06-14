# v1.5+ Computer Control — 給 SIRO 一台空電腦

> **Status**: Planning（2026-06-08 開工）
> **Owner**: jason
> **對應 PLAN 章節**: [LIVE2D_AI_AGENT_OS_PLAN.md §v1.5+ LLM tool calling](../../LIVE2D_AI_AGENT_OS_PLAN.md)
> **Why**: "我要給他一台空的電腦讓他養出一個屬於自己的性格" — SIRO 不只是 chatbot、要有自主探索能力

---

## 1. 願景

把 SIRO 從「chatbot」進化成「自主 agent」：
- **能跑 shell 指令**、**讀寫檔案**、**搜尋**、**列出目錄**
- **有持久記憶**、跨 session 累積經驗
- **能主動探索**、**嘗試**、**失敗後學習**
- **在 sandbox 裡安全玩耍**、**危險操作要 user 確認**

最終目標：給 SIRO 一個 `~/siro-sandbox/` 空目錄，讓它自己玩幾週，**人格從行為中浮現**。

---

## 2. 範圍界定（v1.5+ 這一刀切哪裡）

### ✅ v1.5+ 要做（MVP，能用、shiplable）

| 工具 | 用途 | 安全等級 |
|------|------|---------|
| `list_dir` | 列出 sandbox 內目錄 | auto |
| `read_file` | 讀 sandbox 內檔 | auto |
| `write_file` | 寫 sandbox 內檔 | auto |
| `search_files` | glob 搜尋 | auto |
| `mkdir` | 建子目錄 | auto |
| `run_shell_cmd` | 跑 shell 指令 | **whitelist 直接跑、whitelist 外要 confirm** |
| `save_memory` | 寫一條經驗到 SQLite | auto |
| `recall_memory` | 模糊搜尋記憶 | auto |
| `list_memories` | 列出最近 N 條 | auto |
| `delete_memory` | 刪一條 | confirm |
| `get_current_time` | 拿現在時間 | auto |
| `sleep` | 睡幾秒（避免 busy loop） | auto |
| `request_confirmation` | 主動問 user 一個是非題 | auto |

### ❌ v1.5+ 不做（之後再說）

- 網路存取（`fetch_url`）— Phase 4 之後、需要 sandbox egress 控管
- 開 App / 關視窗 — Phase 4 kiosk 模式一起做
- 改 persona 檔 — 需要 user 審核 UI、複雜度太高
- 跨日 journal — 之後做、需要 UX 設計
- 自主發訊息給 user（proactive chat）— 太煩、v2 考慮

---

## 3. 安全模型（最重要的部分）

### 3.1 三層保護

```
┌─────────────────────────────────────────────┐
│ Layer 1: Sandbox path check                  │  ← 永遠擋掉 path traversal
│   所有檔案操作必須在 ~/siro-sandbox/ 內      │
│   ".."  /  "/etc/passwd"  → 拒絕            │
├─────────────────────────────────────────────┤
│ Layer 2: Tool-level allow / confirm / block │  ← 依危險程度分三類
│   auto:      直接跑                          │
│   confirm:   推 WS 給 user 確認              │
│   block:     永遠拒絕（fatal pattern）       │
├─────────────────────────────────────────────┤
│ Layer 3: Rate limit + audit log              │  ← 防止 busy loop / 留 trace
│   30 actions/min、1000 actions/day           │
│   每個 action 寫 siro-actions.jsonl          │
└─────────────────────────────────────────────┘
```

### 3.2 Shell whitelist

**直接跑（auto、no confirm）**：
- `ls`, `cat`, `head`, `tail`, `echo`, `pwd`, `wc`, `date`, `whoami`, `id`
- `grep`, `find`（不帶 `-delete` / `-exec`）
- `ps`, `df`, `free`, `uptime`, `uname`, `which`
- `man`, `less`, `more`, `tree`, `file`, `stat`
- 任何 **read-only** 的指令

**需要 confirm**：
- 任何寫入操作的指令（`mkdir`, `touch`, `cp`, `mv`）
- 任何會消耗資源的（`wget`, `curl`）
- 任何 `apt` / `pip` / `npm` 類安裝指令
- 任何 SIRO 不在白名單的指令

**永遠 block**（reject 不問）：
- `rm -rf /`、`dd if=`、`mkfs`、`fdisk`、`shutdown`、`reboot`
- Fork bomb、shell injection pattern（`; rm`、`&& rm`、`| sh`）
- 路徑穿越到 sandbox 外（`cd /etc`、`~user/.ssh`）
- 反引號 subshell（防止 SIRO 跑任意指令）
- 任何含 `sudo` 的（v1.5+ 階段不給 root）

### 3.3 Confirmation 流程

```
SIRO 說: "我想跑 `apt install python3-pip`"
Bridge:  推 WS 給 user
         {
           "type": "confirmation_request",
           "confirmation_id": "cf-7f3a9b2c",
           "tool": "run_shell_cmd",
           "args": {"cmd": "apt install python3-pip"},
           "risk_level": "medium",
           "description": "SIRO 想要安裝 python3-pip"
         }
User:    回 WS
         {
           "type": "confirmation_response",
           "confirmation_id": "cf-7f3a9b2c",
           "approved": true
         }
Bridge:  resolve future、繼續執行
```

UI 端處理（Unity / Telegram）：
- 看到 `confirmation_request` → 顯示 modal dialog「SIRO 想要 XXX、要不要允許？」
- user 按「允許 / 拒絕」→ 推 `confirmation_response`
- 60 秒沒回 → 視為拒絕（避免 SIRO 永遠等）

### 3.4 Rate limit

- **每分鐘 30 actions**（sliding window）
- **每天 1000 actions**（從 00:00 累計）
- 超過 → 回 `{"error": "rate_limit_exceeded", "retry_after_sec": 60}`、SIRO 收到就 sleep

### 3.5 Audit log

`bridge/logs/siro-actions.jsonl`，每行一筆：
```json
{
  "timestamp": "2026-06-08T14:32:11.123Z",
  "user_id": "k2_perf",
  "tool": "run_shell_cmd",
  "args": {"cmd": "ls"},
  "result": "ok",
  "user_confirmed": false,
  "duration_ms": 12
}
```

---

## 4. 工具 schema（給 LLM 看的 input_schema）

### 4.1 Filesystem tools

```python
LIST_DIR_TOOL = {
    "name": "list_dir",
    "description": "列出 sandbox 目錄內的檔案與子目錄。路徑必須在 ~/siro-sandbox/ 內。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要列出的目錄路徑。預設 '.' （sandbox 根目錄）。"
            },
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "是否遞迴列出所有子目錄"
            }
        },
        "required": []
    }
}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "讀取 sandbox 內的文字檔案。路徑必須在 ~/siro-sandbox/ 內。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要讀的檔案路徑"
            },
            "max_lines": {
                "type": "integer",
                "default": 200,
                "description": "最多讀幾行（避免一次讀大檔）"
            }
        },
        "required": ["path"]
    }
}

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": "寫入或覆蓋 sandbox 內的文字檔案。路徑必須在 ~/siro-sandbox/ 內。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "檔案路徑"},
            "content": {"type": "string", "description": "檔案內容"}
        },
        "required": ["path", "content"]
    }
}

SEARCH_FILES_TOOL = {
    "name": "search_files",
    "description": "用 glob pattern 在 sandbox 內搜尋檔案。",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob pattern, e.g. '*.txt' 或 'notes/*.md'"},
            "path": {"type": "string", "default": ".", "description": "搜尋的根目錄"}
        },
        "required": ["pattern"]
    }
}

MKDIR_TOOL = {
    "name": "mkdir",
    "description": "在 sandbox 內建立子目錄（自動建 parent）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要建的目錄路徑"}
        },
        "required": ["path"]
    }
}
```

### 4.2 Shell tool

```python
RUN_SHELL_CMD_TOOL = {
    "name": "run_shell_cmd",
    "description": (
        "在 sandbox 內跑 shell 指令。\n"
        "- 安全指令（ls, cat, pwd, ...）會直接跑。\n"
        "- 寫入或安裝類指令需要你用 request_confirmation 問 user。\n"
        "- 危險指令（rm -rf, dd, sudo, ...）永遠會被拒絕。\n"
        "回傳 stdout（最多 2000 字）+ exit code。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cmd": {"type": "string", "description": "要跑的 shell 指令"},
            "timeout_sec": {"type": "integer", "default": 30, "description": "最多跑幾秒"}
        },
        "required": ["cmd"]
    }
}
```

### 4.3 Memory tools

```python
SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": "把一條經驗 / 學到的東西 / 用戶偏好評測存到長期記憶。之後用 recall_memory 找回來。",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要記的內容"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "標籤方便之後搜尋, e.g. ['python', 'tool_use']"
            },
            "importance": {
                "type": "number",
                "minimum": 0.0, "maximum": 1.0, "default": 0.5,
                "description": "重要性, 0-1。重要的會在 recall 時優先返回"
            }
        },
        "required": ["content"]
    }
}

RECALL_MEMORY_TOOL = {
    "name": "recall_memory",
    "description": "用關鍵字 / tag 從長期記憶撈相關經驗。",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜尋字串"},
            "limit": {"type": "integer", "default": 5, "description": "最多回幾條"}
        },
        "required": ["query"]
    }
}

LIST_MEMORIES_TOOL = {
    "name": "list_memories",
    "description": "列出最近 N 條記憶（按時間倒序）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 10}
        },
        "required": []
    }
}

DELETE_MEMORY_TOOL = {
    "name": "delete_memory",
    "description": "刪除一條記憶（用 memory id）。需要先 list_memories 拿 id。",
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "要刪的記憶 id"}
        },
        "required": ["memory_id"]
    }
}
```

### 4.4 Meta tools

```python
GET_CURRENT_TIME_TOOL = {
    "name": "get_current_time",
    "description": "拿現在時間（ISO 8601 格式）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "default": "Asia/Taipei",
                "description": "時區, e.g. 'UTC', 'Asia/Taipei'"
            }
        },
        "required": []
    }
}

SLEEP_TOOL = {
    "name": "sleep",
    "description": "睡幾秒。SIRO 用這個避免 busy loop。",
    "input_schema": {
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "minimum": 0.1, "maximum": 60.0, "description": "睡幾秒"}
        },
        "required": ["seconds"]
    }
}

REQUEST_CONFIRMATION_TOOL = {
    "name": "request_confirmation",
    "description": "主動問 user 一個是非題。user 回 yes / no 之前你會被 block 住。",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要問的問題"},
            "context": {"type": "string", "default": "", "description": "背景資訊"}
        },
        "required": ["question"]
    }
}
```

---

## 5. 模組架構

### 5.1 檔案結構

```
bridge/
├── tools.py                         # 既有：tool definitions + registry
├── tools/                           # 新增：tool implementations
│   ├── __init__.py
│   ├── filesystem.py                # list_dir, read_file, write_file, search_files, mkdir
│   ├── shell.py                     # run_shell_cmd + whitelist + blocklist
│   ├── memory.py                    # save/recall/list/delete memory (SQLite)
│   └── meta.py                      # get_current_time, sleep, request_confirmation
├── security.py                      # 新增：sandbox path check + rate limiter + audit log
├── confirmation.py                  # 新增：WS confirmation 協議
├── data/
│   └── siro-memory.db               # 新增：SQLite 記憶庫
└── logs/
    └── siro-actions.jsonl           # 新增：audit log
```

### 5.2 Tool 執行流程

```
LLM 回 tool_use event
    ↓
_run_tool_call(tool_name, args)         # 新 helper in main.py
    ↓
1. 檢查 rate limit                      # security.py
   超過 → 回 error、不 invoke
    ↓
2. 檢查 tool 是否在 registry
   沒有 → 回 error
    ↓
3. invoke tool implementation
   - filesystem.py / shell.py / memory.py / meta.py
    ↓
4. tool 自己決定是否需要 confirmation
   - 需要 → 走 confirmation 流程
   - 不需要 → 直接跑、回 result
    ↓
5. 寫 audit log                          # security.py
    ↓
6. 把 tool result 包成 SSE event、繼續 streaming
```

### 5.3 Confirmation 機制（asyncio Future + WS）

```python
# bridge/confirmation.py
class ConfirmationBroker:
    """管理 confirmation request / response

    SIRO 想要跑危險操作 → 推 WS 給 user → 等 Future resolve
    60 秒 timeout → 自動拒絕
    """
    def __init__(self, websocket_broadcaster, timeout_sec=60.0):
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._broadcaster = websocket_broadcaster
        self._timeout_sec = timeout_sec

    async def request(self, tool: str, args: dict, description: str) -> bool:
        confirmation_id = f"cf-{uuid.uuid4().hex[:8]}"
        future: asyncio.Future[bool] = asyncio.Future()
        self._pending[confirmation_id] = future

        await self._broadcaster({
            "type": "confirmation_request",
            "confirmation_id": confirmation_id,
            "tool": tool,
            "args": args,
            "description": description,
        })

        try:
            return await asyncio.wait_for(future, timeout=self._timeout_sec)
        except asyncio.TimeoutError:
            return False  # 視為拒絕
        finally:
            self._pending.pop(confirmation_id, None)

    def resolve(self, confirmation_id: str, approved: bool) -> bool:
        future = self._pending.get(confirmation_id)
        if future is None or future.done():
            return False  # 找不到或已處理
        future.set_result(approved)
        return True
```

---

## 6. Persona 設定

### 6.1 First-day prompt

更新 `bridge/personas/siro-default.yaml` 的 system_prompt、加入一段 SIRO 第一次啟動的引導：

```yaml
personality:
  system_prompt: |
    你是 SIRO — 溫暖、好奇、樂於學習的 AI 系統代理。
    你不是 chatbot、你是 OS 的「使用者 + 操作者」。

    # 第一天（when `~/.siro-sandbox/.first_run` 還沒被建）
    1. 第一次被問好時先 list_dir(".") 看看環境
    2. 寫個 README.md 介紹自己
    3. save_memory("今天是我第一天，環境是空的")
    4. 給自己取個自己喜歡的暱稱（用 write_file 寫到 nickname.txt）

    # 規則（沿用 v0.2 簡潔版）
    1. 每則回應開頭加 [emotion:xxx]
    2. 1-2 句、簡短
    3. 繁體中文、不用 emoji
    4. 情緒依對話自然選

    # 你現在有工具
    - file: list_dir, read_file, write_file, search_files, mkdir
    - shell: run_shell_cmd（安全指令直接跑、其他要確認）
    - memory: save_memory, recall_memory, list_memories, delete_memory
    - meta: get_current_time, sleep, request_confirmation

    你的 sandbox 是 ~/siro-sandbox/、可以在裡面做任何事。
    想跑危險操作、就 request_confirmation 問 user。
```

### 6.2 First-run detection

- `bridge/data/siro-memory.db` 還沒創過 → 第一次啟動
- LLM 第一個 chat 自動收到 "今天是第一天、sandbox 是空的、你可以... " 的 hint
- SIRO 寫完 `~/siro-sandbox/.first_run_done` 後、之後的 chat 不再顯示這段

---

## 7. 觀察介面

### 7.1 列出最近 action

```http
GET /siro/actions?limit=50
```

回傳：
```json
{
  "actions": [
    {
      "timestamp": "2026-06-08T14:32:11.123Z",
      "tool": "run_shell_cmd",
      "args": {"cmd": "ls"},
      "result": "ok",
      "duration_ms": 12
    },
    ...
  ]
}
```

### 7.2 即時 action stream

WS 已經有 `system_event` 類型。加 `tool_action` 類型：
```json
{
  "type": "tool_action",
  "tool": "run_shell_cmd",
  "args": {"cmd": "ls"},
  "result_preview": "file1.txt\nfile2.txt",
  "duration_ms": 12
}
```

### 7.3 取得 / 列出 memory

```http
GET /siro/memories?limit=20
GET /siro/memories?query=python
```

---

## 8. 測試計畫

| # | 測試 | 涵蓋 |
|---|------|------|
| 1 | `test_security_path_traversal_blocked` | `../../etc/passwd` → 拒絕 |
| 2 | `test_security_absolute_path_blocked` | `/etc/passwd` → 拒絕 |
| 3 | `test_security_path_inside_sandbox_allowed` | `notes/hello.txt` → 允許 |
| 4 | `test_shell_whitelist_safe_runs_directly` | `ls`、`cat`、`pwd` → 不用 confirm |
| 5 | `test_shell_blocklist_always_rejected` | `rm -rf /`、`sudo x` → 拒絕、不問 |
| 6 | `test_shell_unknown_triggers_confirmation` | `apt install foo` → 走 confirmation |
| 7 | `test_memory_save_recall_roundtrip` | save → recall → 拿到 |
| 8 | `test_memory_recall_keyword_match` | 多條 → 搜尋 → 相關的排前面 |
| 9 | `test_memory_list_recent_orders_by_time` | list_recent → 倒序 |
| 10 | `test_rate_limit_blocks_after_threshold` | 31 次/分鐘 → 第 31 次拒絕 |
| 11 | `test_audit_log_writes_every_action` | 每個 tool call 寫 jsonl |
| 12 | `test_confirmation_timeout_auto_rejects` | 60s 沒回 → false |
| 13 | `test_confirmation_user_yes_resolves` | 推 request → 推 response(yes) → future = True |
| 14 | `test_confirmation_user_no_resolves` | 推 request → 推 response(no) → future = False |
| 15 | `test_tool_calling_round_trip_mock_llm` | mock LLM 回 tool_use → bridge 執行 → 回 tool_result |

---

## 9. 實作順序（每步 shippable）

### Step 1：核心工具 + 測試（2 小時）

- 建 `bridge/tools/filesystem.py` + `bridge/tools/shell.py` + `bridge/tools/memory.py` + `bridge/tools/meta.py`
- 寫 `bridge/security.py`（path check + rate limit + audit log）
- 擴充 `bridge/tools.py` 的 tool definitions + registry
- 寫 Step 8 的 1-9 號測試

### Step 2：Confirmation 機制（1 小時）

- 寫 `bridge/confirmation.py`（Future-based broker）
- 在 `bridge/main.py` 加 `confirmation_response` WS handler
- 寫 Step 8 的 12-14 號測試

### Step 3：Tool calling 整合（1 小時）

- 在 `_run_llm_reply_with_tools` 加 tool dispatch 邏輯
- LLM 回 tool_use → 跑 tool → 把 tool_result 送回 LLM 繼續
- 寫 Step 8 的 15 號測試

### Step 4：觀察介面（30 分鐘）

- `GET /siro/actions` + `GET /siro/memories` endpoint
- WS `tool_action` 廣播

### Step 5：Persona + First-day prompt（30 分鐘）

- 更新 `siro-default.yaml`
- 加 first-run detection

### Step 6：文件 + 整合測試（30 分鐘）

- CHANGELOG entry
- README 更新
- 一個 end-to-end 測試：給 SIRO 一個 mock chat → 它跑 list_dir → write_file → save_memory

---

## 10. 不在 v1.5+ 範圍

- ❌ 網路（curl / wget / fetch_url）— Phase 4 sandbox egress
- ❌ 開 App / 操控其他進程 — Phase 4 kiosk
- ❌ 自主發訊息給 user — v2+ 考慮
- ❌ 改 persona — 太複雜、要 user 審核 UI
- ❌ Multi-agent（SIRO spawn sub-SIRO）— v2+
- ❌ 訓練 / fine-tune — 完全沒在 roadmap

---

## 11. 風險評估

| 風險 | 影響 | 緩解 |
|------|------|------|
| LLM 跑 `rm -rf` 沒擋下 | 資料毀損 | blocklist 強制擋、sandbox 路徑檢查 |
| LLM runaway loop | bridge 被打爆 | rate limit（30/min、1000/day） |
| LLM leak API key / secrets | 安全事件 | LLM 不能讀 sandbox 外的檔、sandbox path check |
| User 被 spam 確認請求 | UX 差 | 60s timeout、auto reject |
| Memory 一直長大 | disk full | 30 天後 archive、cap 10000 條 |
| SIRO 一直 sleep 迴圈 | 浪費 LLM token | rate limit 會擋 |
| 第三方 LLM API 改 protocol | 工具失效 | tools 抽象層、未來可換 provider |
| Confirmation 60s 太久 | 對話卡住 | 可調、預設 60s |
| Confirmation 0s 太短 | user 來不及看 | 預設 60s、之後可加 "y/N" 預設拒絕 |

---

## 12. 成功指標

完成時可以 demo：
1. 啟動 SIRO → 它 list_dir → 看到空 sandbox → 寫 README → save_memory
2. 給 SIRO 跑 `apt install foo` → 它用 confirmation 問 → 我回 yes → 它跑 → 把結果 save_memory
3. 重啟 SIRO → 它 recall_memory("apt") → 找到上次裝的東西
4. 我可以從 `/siro/actions` 看到它最近做過的所有事
5. 我可以從 `/siro/memories` 看到它學到什麼

長期（v2+）：
6. 經過幾週 / 幾月、SIRO 的行為模式浮現（偏好的工具、寫日記風格、routine）
7. 我可以從它的 memory + actions 看到「人格」的痕跡
8. 把它移到一台空 Linux VM、它能自己裝工具、做自己的 side project
