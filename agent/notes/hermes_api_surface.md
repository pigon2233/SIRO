# Hermes Agent - 實際 API 介面筆記

> **目的**：記錄 Hermes Agent 對外暴露的真實介面，給未來的開發者（或未來的自己）參考。
> **資料來源**：[Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)（截至 2026-06-02，v0.15.2）

---

## TL;DR

**Hermes Agent 沒有對外的 HTTP API**。它的對外介面只有：
1. CLI 指令（`hermes`）
2. TUI 互動終端
3. Messaging Gateway（daemon，給 Telegram/Discord 等用）
4. MCP Server（`mcp_serve.py` 啟動，可被 MCP client 連）

**SIRO v0 怎麼用**：透過 subprocess 跑 `hermes` CLI 的 prompt 模式。

---

## CLI 介面

### 進入點

`hermes` 指令由 `pyproject.toml` 的 `[project.scripts]` 定義：
- `hermes` → `hermes_cli.main:main`
- `hermes-agent` → `run_agent:main`
- `hermes-acp` → `acp_adapter.entry:main`

### 主要指令

| 指令 | 用途 |
|------|------|
| `hermes` | 啟動 TUI 互動對話 |
| `hermes setup` | 互動式設定 LLM provider、API key |
| `hermes config set <KEY> <VALUE>` | 設定個別 config 項目 |
| `hermes config show` | 顯示目前設定 |
| `hermes model` | 切換 LLM 模型 |
| `hermes tools` | 列出/設定啟用的工具 |
| `hermes gateway install` | 安裝 gateway daemon（systemd / nohup） |
| `hermes gateway start` | 啟動 gateway |
| `hermes gateway stop` | 停止 gateway |
| `hermes update` | 升級 Hermes |
| `hermes doctor` | 診斷問題 |

### Prompt 模式

```bash
hermes -p "你的訊息"
```

這會跑一次對話並輸出結果，**不會進入 TUI**。SIRO bridge 會用這個模式。

⚠️ **未驗證**：streaming 模式、批次對話、tool call 的 CLI 介面 — 這些可能要進階測試才知道。

---

## TUI 互動指令

TUI 模式下的 slash 指令：

- `/new` / `/reset` — 開始新對話
- `/model <name>` — 切換模型
- `/personality <name>` — 切換角色人格
- `/skills` — 列出已安裝技能
- `/<skill-name>` — 執行技能
- `/compress` — 壓縮上下文
- `/usage` — 顯示 token 用量
- `/retry` — 重試上次
- `/undo` — 撤銷

---

## Messaging Gateway

`hermes gateway` 啟動的 daemon，負責：
- 維護跟 Telegram / Discord / Slack / WhatsApp / Signal / Email 的長連線
- 跑 cron 排程任務

**重要**：gateway 是給**訊息平台**用的，不是給本地 HTTP client 用的。SIRO v0 不會用 gateway。

---

## MCP Server

`mcp_serve.py` 是 Hermes 的 MCP server 入口。**理論上**外部程式可以當 MCP client 連進去操作 Hermes。

**SIRO 現狀**：v0 還沒實作 MCP client 整合，目前用 subprocess 跑 `hermes -p` 比較單純。

**升級路徑**（v1+）：
```
Bridge (Python)
  ↓ (MCP client)
Hermes mcp_serve.py
```
好處：支援串流、tool call、更好的錯誤處理。

---

## 設定檔

Hermes 的設定分散在三個地方：

| 位置 | 內容 |
|------|------|
| `~/.hermes/.env` | API key、provider 設定 |
| `~/.hermes/config.yaml` | 一般 config |
| `~/.hermes/skills/` | 自定義技能（Python 模組） |
| `~/.hermes/memory.db` | SQLite，記憶資料庫 |
| `~/.hermes/sessions/` | 對話 session 存檔 |
| `~/.hermes/logs/` | 各種 log |

---

## SIRO Bridge 怎麼跟 Hermes 互動（v0 規劃）

```python
# bridge/hermes_client.py
import subprocess

def chat(message: str) -> str:
    result = subprocess.run(
        ["hermes", "-p", message],
        capture_output=True,
        text=True,
        timeout=60
    )
    return result.stdout.strip()
```

**已知風險**：
- `hermes -p` 是不是真的支援所有對話特性（不確定）
- 串流可能不支援 → Bridge v0 用輪詢或一次性回應
- Token 用量、session 管理不確定怎麼做

**待驗證**：
- [ ] `hermes -p` 的 exit code
- [ ] 錯誤訊息格式
- [ ] session 怎麼延續
- [ ] system prompt 怎麼帶入

---

## 升級或換框架時怎麼辦

如果以後要：
- **Hermes 大改 API** → 改 `bridge/hermes_client.py` 裡的 subprocess 邏輯
- **換成 LangChain / CrewAI / 其他** → 實作 `bridge/<framework>_client.py`，main.py 換 import
- **要串流** → 升級到 MCP client 模式

`agent/` 跟 `bridge/` 的分離是這個彈性的基礎。
