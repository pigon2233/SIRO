"""
bridge/platform - 跨平台抽象層 (v0.5 Desktop Assistant)

業務邏輯禁止直接寫死 OS-specific path / 直接呼叫 platform-specific API。
請一律從這裡 import 對應的抽象介面。

模組:
- paths: 路徑解析 (user_data_dir / user_config_dir / user_log_dir / runtime_socket_path / siro_sandbox_dir)
- service: Windows Service / systemd unit 安裝/啟動/停止/解除 (Protocol + Windows 實作 + Linux stub)
- autostart: 開機自動啟動 (Scheduled Task / XDG autostart .desktop / LaunchAgent)
- env_resolver: 把 .env 裡的相對/縮寫路徑展開成絕對路徑

Phase 4 Linux 化時,只需要補 service_linux.py / autostart_linux.py 實作,
業務邏輯 0 改動。
"""

from .paths import (
    user_data_dir,
    user_config_dir,
    user_log_dir,
    runtime_socket_path,
    siro_sandbox_dir,
    personas_dir,
    bridge_install_root,
)

__all__ = [
    "user_data_dir",
    "user_config_dir",
    "user_log_dir",
    "runtime_socket_path",
    "siro_sandbox_dir",
    "personas_dir",
    "bridge_install_root",
]
