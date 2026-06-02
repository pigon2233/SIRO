# SIRO API 參考

> 所有介面的完整契約：HTTP、gRPC、WebSocket。

---

## 1. 總覽

| 介面 | 端口 | 協議 | 用途 |
|------|------|------|------|
| Bridge HTTP | 8001 | HTTP/1.1 | REST API |
| Bridge WS | 8001 | WebSocket | 即時對話 |
| Runtime gRPC | 50051 | gRPC | 系統管理 |
| Runtime HTTP | 50052 | HTTP/1.1 | 健康檢查 |

> **所有介面預設只 bind 到 127.0.0.1**（localhost only）。對外暴露需要顯式設定。

---

## 2. Bridge HTTP API

Base URL: `http://127.0.0.1:8001`

### 2.1 `GET /health`

健康檢查。

**Response 200**:
```json
{
  "status": "ok",
  "hermes_available": true,
  "hermes_version": "v0.15.2",
  "bridge_version": "0.1.0"
}
```

**Response 503** (Hermes 不可用):
```json
{
  "status": "degraded",
  "hermes_available": false,
  "hermes_version": null,
  "bridge_version": "0.1.0"
}
```

### 2.2 `POST /chat`

單次對話。

**Request**:
```json
{
  "message": "你好",
  "user_id": "test_user",
  "session_id": null,
  "personality": "default"
}
```

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `message` | string | 是 | 使用者訊息 (1-2000 chars) |
| `user_id` | string | 否 | 使用者 ID，預設 `"default"` |
| `session_id` | string \| null | 否 | Session ID，留空自動產生 |
| `personality` | string \| null | 否 | 角色人格，預設 `"default"` |

**Response 200**:
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

**Response 502** (Hermes 失敗):
```json
{
  "detail": "Hermes 對話失敗: timeout"
}
```

**Response 503** (Service unavailable):
```json
{
  "detail": "Hermes 不可用"
}
```

### 2.3 `WS /ws`

WebSocket 即時對話。

**URL**: `ws://127.0.0.1:8001/ws`

**Client → Server**：

```json
// 聊天
{
  "type": "chat",
  "message": "你好",
  "user_id": "test_user",
  "personality": "default"
}

// ping
{
  "type": "ping"
}
```

**Server → Client**：

```json
// 成功回應
{
  "type": "response",
  "text": "你好呀！",
  "emotion": "happy",
  "intensity": 0.8,
  "live2d": {
    "expression_id": "F02",
    "motion_group": "Idle",
    "motion_index": 0,
    "intensity": 0.8,
    "duration_ms": 500
  },
  "session_id": "test_user-ws"
}

// 錯誤
{
  "type": "error",
  "detail": "Hermes 對話失敗: ..."
}

// pong
{
  "type": "pong"
}
```

### 2.4 錯誤碼

| HTTP Code | 意義 |
|-----------|------|
| 200 | 成功 |
| 400 | 請求格式錯誤 |
| 422 | Pydantic 驗證失敗 |
| 500 | 內部錯誤 |
| 502 | 上游（Hermes）失敗 |
| 503 | 服務不可用 |

---

## 3. Runtime gRPC API

定義在 `os-runtime/proto/siro.proto`。

預設位址: `http://127.0.0.1:50051`

### 3.1 `GetStatus(Empty) → SystemStatus`

查詢所有服務狀態。

```protobuf
message SystemStatus {
  map<string, ServiceState> services = 1;
  SystemMetrics metrics = 2;
}

message ServiceState {
  string name = 1;
  ServiceStatus status = 2;
  int32 pid = 3;
  int64 uptime_seconds = 4;
  int64 memory_bytes = 5;
  float cpu_percent = 6;
  string last_error = 7;
}

enum ServiceStatus {
  UNKNOWN = 0;
  RUNNING = 1;
  STOPPED = 2;
  FAILED = 3;
  STARTING = 4;
  STOPPING = 5;
}
```

### 3.2 `GetHardwareInfo(Empty) → HardwareInfo`

查詢硬體資訊（CPU、RAM、GPU、音訊、視訊、顯示）。

```protobuf
message HardwareInfo {
  CpuInfo cpu = 1;
  MemoryInfo memory = 2;
  GpuInfo gpu = 3;
  repeated AudioDevice audio = 4;
  DisplayInfo display = 5;
  repeated CameraDevice cameras = 6;
}
```

### 3.3 `RestartService(ServiceName) → Ack`

重啟指定服務。

```protobuf
message ServiceName { string name = 1; }
```

`name` 可為 `"bridge"`, `"hermes"`, `"unity"`, `"runtime"`。

### 3.4 `ControlService(ServiceControl) → Ack`

啟動 / 停止 / 重啟服務。

```protobuf
message ServiceControl {
  string name = 1;
  ServiceAction action = 2;
  enum ServiceAction { UNKNOWN = 0; START = 1; STOP = 2; RESTART = 3; }
}
```

### 3.5 `SetKioskMode(KioskRequest) → Ack`

切換 kiosk 模式。

```protobuf
message KioskRequest {
  bool enable = 1;
  string escape_password = 2;  // 可選
}
```

### 3.6 `Health(Empty) → HealthStatus`

健康檢查。

```protobuf
message HealthStatus {
  bool healthy = 1;
  string version = 2;
  int64 uptime_seconds = 3;
  repeated string issues = 4;
}
```

### 3.7 `StreamLogs(LogFilter) → stream LogEntry`

串流 log（server streaming）。

```protobuf
message LogFilter {
  string service = 1;       // 過濾特定 service
  string min_level = 2;     // "debug" / "info" / "warn" / "error"
  string pattern = 3;       // 關鍵字
}

message LogEntry {
  string service = 1;
  string level = 2;
  string message = 3;
  int64 timestamp_ms = 4;
}
```

### 3.8 `SubscribeEvents(EventFilter) → stream SystemEvent`

訂閱系統事件。

```protobuf
message EventFilter {
  repeated string event_types = 1;  // 訂閱的事件類型
}

message SystemEvent {
  string event_type = 1;
  int64 timestamp_ms = 2;
  map<string, string> data = 3;
}
```

事件類型：
- `service.started`
- `service.stopped`
- `service.failed`
- `service.restarted`
- `kiosk.enabled`
- `kiosk.disabled`
- `hardware.changed` (USB 插拔等)
- `config.updated`

### 3.9 gRPC 範例（Python）

```python
import grpc
from siro.runtime.v1 import siro_pb2, siro_pb2_grpc

channel = grpc.insecure_channel('127.0.0.1:50051')
stub = siro_pb2_grpc.SiroRuntimeStub(channel)

# 查狀態
status = stub.GetStatus(siro_pb2.Empty())
print(status.services)

# 重啟 bridge
ack = stub.RestartService(siro_pb2.ServiceName(name="bridge"))
print(ack.ok, ack.message)
```

### 3.10 gRPC 範例（Rust）

```rust
use siro_ipc::siro::{siro_runtime_client::SiroRuntimeClient, Empty};

let client = SiroRuntimeClient::connect("http://127.0.0.1:50051").await?;
let status = client.get_status(Empty {}).await?;
println!("{:?}", status);
```

---

## 4. 訊息格式

### 4.1 情緒標籤

LLM 必須輸出 `[emotion:xxx]` 開頭的標籤，bridge 會自動解析並移除。

支援的情緒：
- `happy`
- `sad`
- `angry`
- `surprised`
- `thinking`
- `excited`
- `neutral`

範例：
```
[emotion:happy] 早安！今天天氣真好呢
[emotion:sad] 蛤...怎麼了嗎？
[emotion:thinking] 嗯...讓我想想
```

### 4.2 Live2D 訊號

```json
{
  "expression_id": "F02",
  "motion_group": "Idle",
  "motion_index": 0,
  "intensity": 0.8,
  "duration_ms": 500
}
```

| 欄位 | 說明 |
|------|------|
| `expression_id` | Cubism expression 檔 ID (Hiyori: F01-F06) |
| `motion_group` | Cubism motion 群組名稱 |
| `motion_index` | 群組內的 motion 編號 |
| `intensity` | 強度 0-1 |
| `duration_ms` | 過渡時間 |

---

## 5. 設定檔

### 5.1 Bridge `.env`

```bash
# 網路
BRIDGE_HOST=127.0.0.1
BRIDGE_PORT=8001
BRIDGE_LOG_LEVEL=INFO

# Hermes
HERMES_BIN_PATH=~/.local/bin/hermes
HERMES_TIMEOUT=60

# LLM（透過 hermes .env 設定，不在這裡）
```

### 5.2 Runtime TOML

`/etc/siro/runtime.toml`：

```toml
[server]
grpc_host = "127.0.0.1"
grpc_port = 50051
http_host = "127.0.0.1"
http_port = 50052
unix_socket = "/var/run/siro/runtime.sock"

[supervisor]
check_interval_ms = 1000
max_restart_attempts = 5
restart_backoff_ms = 2000
startup_timeout_s = 30

[hardware]
audio_input = "default"
audio_output = "default"
camera = "/dev/video0"
display = ":0"

[kiosk]
enabled = true
block_keyboard = true
block_mouse = false  # 保留觸控
escape_password_hash = "$argon2id$..."  # 加密後

[logging]
level = "info"
format = "json"  # 或 "pretty"
destination = "journald"  # 或 "file:/var/log/siro/runtime.log"
```

### 5.3 Device TOML（每台裝置）

`/etc/siro/device.toml`：

```toml
[device]
id = "siro-001"
name = "客廳 SIRO"
location = "taipei-home"
created_at = "2026-06-02T00:00:00Z"

[user]
primary_user_id = "user-001"
llm_provider = "ollama"  # 或 "nous" / "openrouter" / "anthropic"

[network]
hostname = "siro-001.local"
```

---

## 6. 認證

**v0 不做認證**（單機本機使用）。

**v1+**：
- Bridge HTTP/WS：HTTP Basic Auth + token
- Runtime gRPC：mTLS
- SSH：key-only

---

## 7. Rate Limiting

**v0 不做**。

**v1+**：
- Bridge：每分鐘 60 次 chat
- Runtime：每分鐘 1000 次 gRPC

---

## 8. 版本控制

API 變更遵循 [Semantic Versioning](https://semver.org/)。

- **MAJOR**：不相容變更（breaking）
- **MINOR**：向後相容的新功能
- **PATCH**：bug fix

Bridge 與 Runtime 各自有 version。Client 應該檢查 version 相容性。

---

## 9. 變更紀錄

- 2026-06-02 v0.1.0 初版
