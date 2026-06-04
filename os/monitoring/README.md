# os/monitoring/ - 監控

> **Phase 6 規劃**。每台裝置的健康狀態回報。
> Phase 4 不實作、Phase 6 量產前才需要。

## 監控什麼

### 服務健康
- siro-runtime 是否在跑
- siro-bridge 是否健康（`/health` 200 OK）
- siro-unity 是否在前景（X11 進程檢查）
- hermes 是否能 call LLM（subprocess 模擬 ping）

### 系統健康
- CPU 溫度（`/sys/class/thermal/thermal_zone*/temp`）
- RAM 使用（`free -m`）
- 磁碟空間（`df -h`）
- 網路延遲（`ping 8.8.8.8`）
- GPU 利用率（`nvidia-smi`，LLM 推論時）

### 業務健康
- 對話成功率（LLM 沒 timeout）
- Live2D 渲染 FPS（Unity 端吐 stat）
- 攝影機 / 麥克風是否正常（V4L2 / PulseAudio 列裝置）

## 上報機制

### 選項 A: 本地 only（Phase 4 預設，最簡單）
- log 留在 `/var/log/siro/`
- 用 `journalctl` 查詢
- 不對外

### 選項 B: 中央收集（Phase 6 推薦）
- `promtail` 收 log → `Loki` 集中
- 透過反向 SSH tunnel（安全）
- 圖形介面 `Grafana`

### 選項 C: 主動推送
- 異常事件主動推到 Telegram / Discord
- 用 hermes gateway 整合

---

## 監控工具選型

| 層 | 工具 | 用途 |
|---|------|------|
| 系統指標 | node_exporter (Prometheus) | CPU/RAM/disk/net |
| 服務健康 | blackbox_exporter | HTTP/TCP/ICMP probe |
| Log 收集 | promtail | log → Loki |
| 指標存儲 | Prometheus | 時序資料 |
| 圖形介面 | Grafana | dashboard |
| 警報 | Alertmanager | 規則 + Telegram 推播 |

---

## 監控架構（Phase 6）

```
[每台 SIRO 裝置]
  ├─ node_exporter ──┐
  ├─ promtail ───────┼──→ [中央 Loki + Prometheus]
  └─ hermes watchdog ┘         │
                               ├─ Grafana (dashboard)
                               └─ Alertmanager → Telegram bot
```

### siro-runtime watchdog（Phase 4 就寫好、Phase 6 接 Prometheus）

```rust
// os/siro-runtime/src/metrics.rs
use prometheus::{register_counter, register_histogram};

pub static SIRO_TASKS_TOTAL: Lazy<IntCounter> = Lazy::new(|| {
    register_counter!("siro_tasks_total", "Total tasks processed").unwrap()
});

pub static HERMES_LATENCY_SEC: Lazy<Histogram> = Lazy::new(|| {
    register_histogram!("siro_hermes_latency_seconds", "Hermes call latency").unwrap()
});
```

Siro-runtime 開 `:9090/metrics` endpoint 給 Prometheus scrape。

---

## Grafana dashboard 範例

四個 panel：

| Panel | 查詢 | 視覺 |
|-------|------|------|
| CPU / RAM | `100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)`、`node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100` | 折線圖 |
| 對話延遲 P50/P95 | `histogram_quantile(0.5, rate(siro_hermes_latency_seconds_bucket[5m]))` | 折線圖 |
| LLM 失敗率 | `rate(siro_llm_failures_total[5m]) / rate(siro_llm_calls_total[5m])` | 數字 panel |
| 磁碟空間 | `100 - (node_filesystem_avail_bytes{fstype!="tmpfs"} / node_filesystem_size_bytes * 100)` | gauge |

---

## 警報規則

| 觸發條件 | 嚴重 | 動作 |
|----------|------|------|
| 服務 crash（siro-bridge 連續 3 次 fail）| 🔴 | Telegram 立即推 + 自動重啟嘗試 |
| 磁碟滿（> 90%）| 🟠 | Telegram 推 + log rotate |
| 溫度過高（CPU > 85°C）| 🟠 | Telegram 推 + 降頻 |
| LLM API 失敗率 > 30%（5 分鐘內）| 🟠 | Telegram 推 |
| 連續 24 小時沒互動 | 🟢 | Telegram 推（可能是使用者不在） |

### Alertmanager 規則範例（`os/monitoring/alerts.yml`）

```yaml
groups:
- name: siro_health
  rules:
  - alert: siro_bridge_down
    expr: probe_success{job="siro_bridge"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "SIRO bridge is down on {{ $labels.instance }}"

  - alert: high_llm_failure_rate
    expr: |
      rate(siro_llm_failures_total[5m])
      / rate(siro_llm_calls_total[5m]) > 0.3
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "LLM failure rate > 30% on {{ $labels.instance }}"
```

---

## 驗證（Phase 6 寫）

```bash
# 1. 確認 node_exporter 跑起來
curl -sf http://127.0.0.1:9100/metrics | head -5

# 2. 確認 siro-runtime 吐指標
curl -sf http://127.0.0.1:9090/metrics | grep siro_

# 3. 確認 promtail 有在送 log
curl -sf http://127.0.0.1:9080/ready

# 4. 觸發測試警報（用 alertmanager 的 amtool）
amtool alert add --alertmanager.url=http://127.0.0.1:9093 \
  --label='severity=critical' --annotation='summary=Test alert'
# 應該收到 Telegram 推播
```

---

## 不在 Phase 6 範圍

- ❌ 自動修復（v2+）
- ❌ 預測性維護（v2+）
- ❌ AIOps 異常偵測（v2+）

---

## Phase 6 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| node_exporter + promtail 部署（每台）| 1 天 | 低 |
| 中央 Loki + Prometheus + Grafana 架設 | 3 天 | 中（HA 配置複雜） |
| Alertmanager + Telegram 整合 | 1 天 | 低 |
| Dashboard + 警報規則調校 | 2 天 | 中（要觀察一段時間才知道 threshold 對不對）|
| **總計** | **7 天** | — |
