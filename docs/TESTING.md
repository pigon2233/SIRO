# SIRO 測試策略

> 確保每個 Phase 的交付物都有對應的測試。

---

## 1. 測試金字塔

```
        ╱╲
       ╱  ╲         E2E（少量）
      ╱ UI ╲        - Play 模式截圖比對
     ╱──────╲       - 完整對話流程
    ╱        ╲      整合測試（中量）
   ╱ Service  ╲     - API 端到端
  ╱────────────╲    - 服務互動
 ╱              ╲   單元測試（大量）
╱   Unit Tests   ╲  - 邏輯、解析、映射
──────────────────
```

| 類型 | 比例 | 速度 | 維護成本 |
|------|------|------|----------|
| 單元 | 70% | 快 (ms) | 低 |
| 整合 | 20% | 中 (s) | 中 |
| E2E | 10% | 慢 (min) | 高 |

---

## 2. 單元測試

### 2.1 Python (bridge/)

**工具**：`pytest` + `pytest-asyncio` + `pytest-cov`

**覆蓋目標**：80%+

**測試對象**：
- `emotion_parser.py` — 標籤提取、關鍵字備援、Live2D 映射
- `hermes_client.py` — binary 解析、可用性、對話成功/失敗
- `models.py` — Pydantic schema 驗證
- `prompts.py` — 模板完整性

**範例**：

```python
# bridge/tests/test_emotion_parser.py
def test_happy_tag_extraction():
    parser = EmotionParser()
    text, emotion, _ = parser.parse("[emotion:happy] 你好")
    assert emotion == Emotion.HAPPY
    assert text == "你好"
```

**執行**：
```bash
cd bridge
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

### 2.2 Rust (os-runtime/)

**工具**：`cargo test` 內建

**覆蓋目標**：80%+

**測試對象**：
- supervisor 邏輯
- config 解析
- hardware 偵測
- kiosk 狀態機

**範例**：

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_service_state_serialization() {
        let state = ServiceState { /* ... */ };
        let json = serde_json::to_string(&state).unwrap();
        assert!(json.contains("\"status\":\"RUNNING\""));
    }
}
```

**執行**：
```bash
cd os-runtime
cargo test --all
cargo tarpaulin  # 覆蓋率
```

### 2.3 C# (unity/)

**工具**：Unity Test Framework (UTF)

**測試對象**：
- `EmotionDisplay.MapEmotionToExpression` 邏輯
- JSON 解析

**注意**：Unity PlayMode 測試需要 Editor 環境，CI 跑要裝 Unity 授權。

**執行**：在 Unity Editor 內跑，或 CI with `unity-ci`。

---

## 3. 整合測試

### 3.1 Bridge 整合測試

測 bridge 跟 hermes 互動（**需要 hermes CLI**）：

```python
# bridge/tests/integration/test_hermes_integration.py
@pytest.mark.skipif(not has_hermes(), reason="hermes not installed")
def test_real_hermes_chat():
    client = HermesClient()
    result = client.chat("說一句你好")
    assert result.success
    assert len(result.output) > 0
```

**標記**：`@pytest.mark.integration`，CI 可以選擇性跳過。

### 3.2 Runtime 整合測試

測 siro-runtime 啟動 + service 監控：

```rust
#[tokio::test]
async fn test_supervisor_starts_service() {
    let supervisor = Supervisor::new_for_test();
    let service = Service::new("test-service", "echo hello");
    supervisor.add_service(service).await;
    
    tokio::time::sleep(Duration::from_secs(2)).await;
    
    let state = supervisor.get_state("test-service").await.unwrap();
    assert_eq!(state.status, ServiceStatus::Running);
}
```

### 3.3 Bridge ↔ Runtime gRPC 測試

Python 跟 Rust 互動測試：

```python
# bridge/tests/integration/test_runtime_grpc.py
def test_grpc_status_call():
    channel = grpc.insecure_channel("127.0.0.1:50051")
    stub = siro_pb2_grpc.SiroRuntimeStub(channel)
    
    status = stub.GetStatus(siro_pb2.Empty(), timeout=5)
    
    assert "bridge" in status.services
```

---

## 4. 端到端 (E2E) 測試

### 4.1 Bridge E2E

啟動 bridge + 用 httpx 模擬 client：

```python
# bridge/tests/e2e/test_chat_flow.py
async def test_full_chat_flow():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        # 健康檢查
        r = await client.get("/health")
        assert r.status_code == 200
        
        # 對話
        r = await client.post("/chat", json={
            "message": "你好",
            "user_id": "test"
        })
        assert r.status_code == 200
        data = r.json()
        assert "text" in data
        assert "emotion" in data
        assert "live2d" in data
```

### 4.2 Unity PlayMode 測試

需要 Unity 環境，手動跑或 CI：

1. 啟動 bridge（背景）
2. Unity Play 模式
3. 模擬使用者輸入（PlayMode 測試 API）
4. 驗證收到 response + 表情切換

**挑戰**：Unity 測試在 CI 很慢，不建議每個 PR 跑。

### 4.3 System E2E（Phase 4+）

完整系統測試：

```
[開機]
  → systemd 啟動 siro-runtime
  → siro-runtime 啟動其他服務
  → siro-bridge 健康
  → siro-unity 啟動
  → 視窗出現
  → 打字測試
  → 收到回應
  → 表情切換
  → 截圖比對
```

可以用 `pyautogui` 或 `xdotool` 自動化。

---

## 5. 性能測試

### 5.1 對話延遲

**目標**：P95 < 5 秒（用本地 LLM 7B Q4）

測量：
```python
import time

start = time.time()
result = client.post("/chat", json={"message": "..."})
duration = time.time() - start

assert duration < 5.0, f"延遲過高: {duration}s"
```

### 5.2 記憶體使用

**目標**：
- siro-runtime < 30MB
- bridge < 200MB
- unity < 1GB

測量：
```bash
ps -o rss= -p $(pgrep siro-runtime)
```

### 5.3 開機時間

**目標**：開機到 Live2D 角色 < 30 秒

測量：
```bash
systemd-analyze
```

### 5.4 24/7 穩定度

**目標**：跑 72 小時不 crash

```bash
# stress test script
while true; do
    curl -s localhost:8001/chat -d '{"message":"ping"}'
    sleep 60
done
# 72 小時後看 log 有沒有 crash
```

---

## 6. 視覺回歸測試

### 6.1 截圖比對

**目標**：確保 UI 沒意外改變

工具：`Pillow` + `pixelmatch`

```python
from PIL import Image
import pixelmatch

actual = Image.open("actual.png")
expected = Image.open("expected.png")

diff = pixelmatch(expected, actual, threshold=0.1)
assert diff < 0.01  # < 1% 像素差異
```

### 6.2 Live2D 表情

截圖各表情，確認正確的 expression 觸發。

---

## 7. 持續整合 (CI)

### 7.1 GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r bridge/requirements.txt
      - run: cd bridge && python -m pytest tests/unit/ -v --cov
      
  rust:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - run: cd os-runtime && cargo test --all
      - run: cd os-runtime && cargo clippy -- -D warnings
```

### 7.2 不在 CI 跑的

- 真的 Hermes 對話（需要 API key）
- Unity PlayMode（需要 Unity 授權）
- System E2E（需要實體硬體）
- 24/7 穩定度（時間太長）

這些在本地或 staging 跑。

---

## 8. 測試資料

### Fixture 範例

`bridge/tests/fixtures/hermes_responses.json`：
```json
[
  {
    "input": "你好",
    "expected_emotion": "happy",
    "expected_expression": "F02"
  },
  {
    "input": "我好難過",
    "expected_emotion": "sad",
    "expected_expression": "F04"
  }
]
```

### 對話測試資料

不放真實對話。用合成資料：

```python
test_conversations = [
    ("hi", "happy"),
    ("謝謝", "happy"),
    ("怎麼辦", "thinking"),
    ("生氣", "angry"),
]
```

---

## 9. Bug Bash

每個 Phase 結束做一次 bug bash：
- 開發者自己跑 1 小時
- 找親友（Phase 6+）跑 1 天
- 收集 bug → 排程 → 修

---

## 10. 不在 v0 範圍

- Load testing（2-10 台 fleet 不需要）
- Chaos testing（v2+）
- Fuzzing（v2+）
- Security penetration testing（v2+）

---

## 11. 測試 Checklist（每個 PR）

- [ ] 新功能有對應的單元測試
- [ ] 測試通過
- [ ] 覆蓋率沒掉
- [ ] 整合測試（如適用）
- [ ] 沒有 flakiness（重跑 3 次都過）

---

## 12. 相關工具

| 工具 | 用途 |
|------|------|
| `pytest` | Python 測試 |
| `pytest-cov` | Python 覆蓋率 |
| `pytest-asyncio` | Python async 測試 |
| `httpx` | Python HTTP client（測試用） |
| `pytest-mock` | Python mocking |
| `cargo test` | Rust 測試（內建） |
| `cargo tarpaulin` | Rust 覆蓋率 |
| `mockall` | Rust mocking |
| `Unity Test Framework` | Unity 測試 |
| `pixelmatch` | 圖片比對 |
| `systemd-analyze` | 開機時間分析 |
| `valgrind` | 記憶體錯誤檢測 |
