# os/power/ - 電源管理

> Phase 5 實作。AC 電源、電池（選配）、省電模式。

## 目標硬體

- **v0/v1**：AC 供電（筆電接變壓器）
- **v2+**：可選電池（如果做行動裝置）

## 策略

### AC 供電
- 不進入 suspend / hibernate
- 螢幕可關（省電）
- CPU governor: `performance`（延遲敏感）
- 永遠連網

### 電池供電（Phase 5+）
- 充電策略：80% 上限（延長電池壽命）
- 低電量警告
- 極低電量自動關機（保護電池）

## 散熱

- 監控 CPU/GPU 溫度
- 過熱自動降頻（thermal throttling）
- 風扇曲線（如果有風扇）
- 鋁殼被動散熱（推薦）

## Wake-on-LAN / Wake-on-AC

- AC 接上自動開機（如果 BIOS 支援）
- Wake-on-LAN 給遠端管理用
- 休眠喚醒測試

## 不在 Phase 5 範圍

- UPS 整合
- 太陽能 / 替代能源
- 智慧電網整合
