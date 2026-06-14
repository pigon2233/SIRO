#!/usr/bin/env python3
"""
stop_bridge.py - 跨平台 SIRO 停止腳本（v0.4+）

對應 start_bridge.py。砍掉 siro-runtime + bridge process。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"


def info(msg: str) -> None:
    print(f"[stop_bridge] {msg}")


def kill_by_name_substr(substr: str) -> int:
    """砍掉 command line 含 substr 的 process"""
    killed = 0
    if IS_WINDOWS:
        # Windows: 用 wmic / tasklist
        try:
            out = subprocess.run(
                ["wmic", "process", "where",
                 f"CommandLine like '%{substr}%'",
                 "get", "ProcessId"],
                capture_output=True, text=True, timeout=10,
            )
            for line in out.stdout.splitlines()[1:]:
                line = line.strip()
                if line.isdigit():
                    info(f"  taskkill /F /PID {line}")
                    subprocess.run(
                        ["taskkill", "/F", "/PID", line],
                        capture_output=True, timeout=5,
                    )
                    killed += 1
        except Exception as e:
            info(f"  wmic 失敗: {e}")
    else:
        # Linux / macOS: 用 pgrep
        try:
            out = subprocess.run(
                ["pgrep", "-f", substr],
                capture_output=True, text=True, timeout=5,
            )
            for pid in out.stdout.split():
                pid = pid.strip()
                if pid:
                    info(f"  kill -9 {pid}")
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        killed += 1
                    except (ProcessLookupError, PermissionError):
                        pass
        except Exception as e:
            info(f"  pgrep 失敗: {e}")
    return killed


def main() -> int:
    print("[stop_bridge] v0.4+ cross-platform")

    info("砍 siro-runtime...")
    n = kill_by_name_substr("siro-runtime")
    info(f"  砍了 {n} 個 siro-runtime process")

    info("砍 bridge...")
    n = kill_by_name_substr("bridge.main")
    info(f"  砍了 {n} 個 bridge process")

    info("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
