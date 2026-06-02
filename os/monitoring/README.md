# os/monitoring/ - 監控

> Phase 6 實作。每台裝置的健康狀態回報。

## 監控什麼

### 服務健康
- siro-runtime 是否在跑
- siro-bridge 是否健康
- siro-unity 是否在前景
- hermes 是否能 call LLM

### 系統健康
- CPU 溫度、RAM 使用、磁碟空間
- 網路延遲
- GPU 利用率（用 LLM 推論時）

### 業務健康
- 對話成功率（LLM 沒 timeout）
- Live2D 渲染 FPS
- 攝影機 / 麥克風是否正常

## 上報機制

### 選項 A: 本地 only（最簡單）
- log 留在 `/var/log/siro/`
- 用 `journalctl` 查詢
- 不對外

### 選項 B: 中央收集（推薦）
- `promtail` 收 log → `Loki` 集中
- 透過反向 SSH tunnel（安全）
- 圖形介面 `Grafana`

### 選項 C: 主動推送
- 異常事件主動推到 Telegram / Discord
- 用 hermes gateway 整合

v0 從 A 開始，Phase 6 加 B。

## 警報

什麼時候該發警報：
- 服務 crash
- 磁碟滿
- 溫度過高
- LLM API 失敗率高
- 連續 24 小時沒互動（可能是使用者不在 / 故障）

## 不在 Phase 6 範圍

- 自動修復（v2+）
- 預測性維護（v2+）
- AIOps 異常偵測（v2+）
