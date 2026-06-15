"""
bridge/platform/paths.py - 跨平台路徑解析 (v0.5)

所有業務邏輯需要「SIRO 的 user data 目錄」、「runtime socket 路徑」等
都從這裡拿,不要直接寫 Path.home() / %LOCALAPPDATA% / /var/run。

底層用 platformdirs 套件 (已加進 bridge/requirements.txt)，
自動處理 Windows / Linux / macOS 差異。

回傳的 path 都用 pathlib.Path、不存在會自動建立(呼叫 ensure_user_dirs())。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# platformdirs 4.x 已經穩定、SIRO v0.5+ 鎖定 >=4.2
import platformdirs

# 應用程式識別 (平台 dirs 用這個命名)
APP_NAME = "SIRO"
APP_AUTHOR = "siro"  # Linux/macOS 會變成 ~/.local/share/siro/SIRO/ (author 子目錄)


def user_data_dir(ensure: bool = True) -> Path:
    """SIRO 使用者資料目錄 (DB / state / config)。

    - Windows: %LOCALAPPDATA%\\SIRO\\
    - Linux:   $XDG_DATA_HOME/siro/ (default ~/.local/share/siro/)
    - macOS:   ~/Library/Application Support/SIRO/
    """
    p = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR, roaming=False))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def user_config_dir(ensure: bool = True) -> Path:
    """SIRO 使用者設定目錄 (.env / runtime.yaml / 個人 persona override)。

    - Windows: %LOCALAPPDATA%\\SIRO\\
    - Linux:   $XDG_CONFIG_HOME/siro/ (default ~/.config/siro/)
    - macOS:   ~/Library/Application Support/SIRO/  (macOS 沒分 data/config)
    """
    p = Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR, roaming=False))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def user_log_dir(ensure: bool = True) -> Path:
    """SIRO 使用者 log 目錄 (bridge.log / siro-runtime.log / siro-actions.jsonl)。

    - Windows: %LOCALAPPDATA%\\SIRO\\logs\\
    - Linux:   $XDG_STATE_HOME/siro/log/ (default ~/.local/state/siro/log/)
    - macOS:   ~/Library/Logs/SIRO/
    """
    p = Path(platformdirs.user_log_dir(APP_NAME, APP_AUTHOR))
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def runtime_socket_path() -> Path:
    """siro-runtime gRPC unix socket / Windows named pipe 路徑。

    - Windows: 不用 socket (走 gRPC over TCP 127.0.0.1:50051),回傳 None 之前的 fallback
    - Linux:   $XDG_RUNTIME_DIR/siro/runtime.sock (or /tmp/siro-runtime.sock)
    - macOS:   ~/Library/Application Support/SIRO/runtime.sock
    """
    if os.name == "nt":
        # Windows 走 TCP、走 gRPC client env var SIRO_RUNTIME_ADDR (預設 127.0.0.1:50051)
        return Path(os.environ.get("SIRO_RUNTIME_SOCKET", "127.0.0.1:50051"))
    # Unix: 用 XDG_RUNTIME_DIR (systemd user session) 或 fallback /tmp
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        sock_dir = Path(xdg_runtime) / "siro"
        sock_dir.mkdir(parents=True, exist_ok=True)
        return sock_dir / "runtime.sock"
    return Path("/tmp/siro-runtime.sock")


def siro_sandbox_dir(ensure: bool = True) -> Path:
    """SIRO 預設 sandbox 目錄（LLM tool 操作範圍）。

    - 優先讀 env var SIRO_SANDBOX_DIR (測試常用)
    - 否則: %USERPROFILE%/siro-sandbox (Windows) 或 ~/siro-sandbox (Linux/macOS)

    注意：Phase 4 Linux 化時不強制改 XDG 路徑（要保留 home dir 簡潔），
          user 想要改路徑設 env var 即可。
    """
    env_path = os.environ.get("SIRO_SANDBOX_DIR")
    if env_path:
        p = Path(env_path).expanduser().resolve()
    else:
        p = Path.home() / "siro-sandbox"
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def personas_dir(install_root: Optional[Path] = None) -> Path:
    """Persona YAML 檔案目錄。

    persona 跟 install 一起 ship (不是 user-level) — 因為 persona 是 SIRO
    內建角色設定，user 不會自己改、所以放 install dir 才對。

    Args:
        install_root: SIRO 安裝根目錄 (%ProgramFiles%/SIRO Desktop on Windows、
                      /opt/siro on Linux)。預設從 SIRO_INSTALL_ROOT env var 讀、
                      fallback 推算(假設本檔在 bridge/platform/paths.py → 往上 2 層 = install root)。
    """
    if install_root is None:
        env_root = os.environ.get("SIRO_INSTALL_ROOT")
        if env_root:
            install_root = Path(env_root)
        else:
            # bridge/platform/paths.py → ../.. → install root
            install_root = Path(__file__).resolve().parent.parent.parent
    return install_root / "bridge" / "personas"


def bridge_install_root() -> Path:
    """SIRO 安裝根目錄（installer 用）。

    - 預設讀 SIRO_INSTALL_ROOT env var（service 安裝時由 post_install.ps1 設）
    - fallback 推算：bridge/platform/paths.py → 往上 2 層
    """
    env_root = os.environ.get("SIRO_INSTALL_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent.parent
