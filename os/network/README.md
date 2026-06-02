# os/network/ - 網路設定

> Phase 4 實作。netplan + ufw + 監控。

## 設計

- **單網卡、DHCP 預設**（一般家庭網路）
- **靜態 IP 為選配**（想固定 IP 的話）
- **IPv6 預設關閉**（簡化）
- **DNS 用 systemd-resolved**（避免 dnsmasq 衝突）

## Netplan 範例

```yaml
# /etc/netplan/01-siro.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      dhcp4: true
      dhcp6: false
      optional: true
```

## 對外連線白名單

SIRO 對外只需要：
- LLM API（如果有雲端 LLM）
- OTA 更新 server
- NTP（時間同步）

其他都擋掉。實作在 ufw 的 output chain。

## 不在 Phase 4 範圍

- 多網卡 / VLAN（Phase 6+）
- WireGuard VPN（Phase 6+）
- 行動網路 / 5G（v2+）
