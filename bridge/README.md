# bridge/ - SIRO Bridge 服務

> Python FastAPI 服務，介接 Hermes Agent（subprocess）與 Unity（WebSocket）。

---

## 快速開始

```bash
cd bridge

# 1. 建 venv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. 裝依賴
pip install -r requirements.txt

# 3. 跑起來
python -m bridge.main
# 或：
uvicorn bridge.main:app --reload --host 127.0.0.1 --port 8001
```

看到 `Uvicorn running on http://127.0.0.1:8001` 就是成功。

---

## 模組組成

| 檔案 | 用途 |
|------|------|
| `main.py` | FastAPI 入口，含 `/health`、`/chat`、`/ws` 端點 |
| `hermes_client.py` | 封裝 Hermes CLI 為 Python client（subprocess） |
| `emotion_parser.py` | 解析 `[emotion:xxx]` 標籤 + 備援關鍵字 |
| `emotion_mapping.json` | 情緒 → Live2D (Hiyori) 動作映射 |
| `prompts.py` | 系統提示詞（讓 Hermes 帶標籤輸出） |
| `models.py` | Pydantic schemas |
| `runtime_client.py` | Layer 3 (siro-runtime) gRPC client stub |
| `tests/` | 單元測試（69 個案例，91% 覆蓋率） |

---

## API

### `GET /health`

```bash
curl localhost:8001/health
```

回傳：
```json
{
  "status": "ok",
  "hermes_available": true,
  "hermes_version": "v0.15.2",
  "bridge_version": "0.1.0"
}
```

### `POST /chat`

```bash
curl -X POST localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好！",
    "user_id": "test_user"
  }'
```

回傳：
```json
{
  "text": "你好呀！今天過得如何？",
  "emotion": "happy",
  "intensity": 0.8,
  "live2d": {
    "expression_id": "F02",
    "motion_group": "Idle",
    "motion_index": 0,
    "intensity": 0.8,
    "duration_ms": 500
  },
  "session_id": "test_user-abc12345",
  "user_id": "test_user",
  "raw_response": "[emotion:happy] 你好呀！今天過得如何？"
}
```

### `WS /ws`

```javascript
const ws = new WebSocket("ws://localhost:8001/ws");
ws.send(JSON.stringify({
  type: "chat",
  message: "你好",
  user_id: "test"
}));
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === "response") {
    console.log(data.text, data.emotion, data.live2d);
  }
};
```

---

## 測試

```bash
# 從 bridge/ 資料夾
cd bridge
python -m pytest tests/ -v
```

或：
```bash
python -m pytest tests/ -v
```

### 測試覆蓋

- `test_hermes_client.py`: binary 解析、可用性檢查、對話成功/失敗/timeout
- `test_emotion_parser.py`: 標籤提取、關鍵字備援、Live2D 映射

### 沒測到的（v0 範圍）

- 真的 Hermes 對話（需要 API key，CI 跑不起來）
- WebSocket 端對端（之後補）
- 大量並發（之後補）

---

## 環境變數

從 `.env` 讀取（或直接 export）：

| 變數 | 預設 | 用途 |
|------|------|------|
| `BRIDGE_HOST` | `127.0.0.1` | 綁定 IP |
| `BRIDGE_PORT` | `8001` | 綁定 port |
| `BRIDGE_LOG_LEVEL` | `INFO` | log 等級 |
| `HERMES_BIN_PATH` | `~/.local/bin/hermes` | hermes binary 路徑 |
| `HERMES_TIMEOUT` | `60` | 對話 timeout（秒） |

LLM 相關設定（`HERMES_LLM_PROVIDER`、`HERMES_API_KEY` 等）由 Hermes 自己的 `~/.hermes/.env` 處理，bridge 不直接管。

---

## 已知限制

- v0 沒有串流（subprocess 跑完才回傳完整回應）— 之後升級 MCP client 才有真串流
- 對話歷史只在記憶體中（重啟 Bridge 就掉）— 之後接 Honcho 才持久化
- 沒有 rate limiting — 之後 v1 補
- 沒有使用者認證 — 之後 v1 補

---

## 升級路徑

| 從 | 到 | 怎麼做 |
|----|----|----|
| subprocess CLI | MCP client | 改 `hermes_client.py`，其他檔不動 |
| 沒串流 | 串流 | MCP client 支援串流 token，main.py 加 streaming 邏輯 |
| 沒記憶 | Honcho 整合 | 加 `honcho_client.py`，chat() 注入記憶上下文 |
| 沒人臉 | 視覺整合 | 加 `/vision` 端點，emotion_parser 接受視覺輸入 |
