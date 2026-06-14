#!/usr/bin/env python3
"""
start_bridge.py - 跨平台 SIRO 啟動腳本（v0.4+）

取代原本的 start_bridge.sh + start_bridge.ps1、用同一份 code 處理 Windows / Linux / macOS。

功能：
    1. 載入 .env
    2. 清掉佔 port 8001 / 50051 的 orphan process
    3. 啟動 siro-runtime（os-runtime 的 Rust daemon）
    4. 啟動 bridge（Python FastAPI）
    5. 驗證 health check OK、印 status

執行：
    python scripts/start_bridge.py
    python scripts/start_bridge.py --no-runtime   # 跳過 siro-runtime
    python scripts/start_bridge.py --clean-only   # 只清 port、不啟動

未來規劃（v1+）：
    - systemd service mode（Linux 開機啟動）
    - launchd plist（macOS 開機啟動）
    - Windows Service（pywin32）
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# ==================== 顏色 ====================

class C:
    OK = "\033[92m"
    FAIL = "\033[91m"
    WARN = "\033[93m"
    DIM = "\033[90m"
    BOLD = "\033[1m"
    END = "\033[0m"


def info(msg: str) -> None:
    print(f"{C.DIM}[start_bridge]{C.END} {msg}")


def ok(msg: str) -> None:
    print(f"  {C.OK}✓{C.END} {msg}")


def fail(msg: str) -> None:
    print(f"  {C.FAIL}✗{C.END} {msg}")


def warn(msg: str) -> None:
    print(f"  {C.WARN}⚠{C.END} {msg}")


# ==================== Platform ====================

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# ==================== 工具函式 ====================

def project_root() -> Path:
    """回傳 SIRO project root（start_bridge.py 在 scripts/ 下）"""
    return Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """簡單 .env 載入（沒裝 python-dotenv 也可跑）"""
    if not path.exists():
        return
    info(f"載入 .env: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 不覆蓋已存在的 env（給 CI / systemd 用的 override）
        if key not in os.environ:
            os.environ[key] = value


def find_python() -> str:
    """決定 Python 指令（跨平台 + venv aware）

    順序：
        1. SIRO_PYTHON_BIN env var
        2. venv 內的 python（看 VIRTUAL_ENV）
        3. python3（Linux / macOS 標準）
        4. python（Windows 標準）
    """
    if p := os.environ.get("SIRO_PYTHON_BIN"):
        return p

    # 找 venv
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        if IS_WINDOWS:
            candidate = Path(venv) / "Scripts" / "python.exe"
        else:
            candidate = Path(venv) / "bin" / "python"
        if candidate.exists():
            return str(candidate)

    if IS_LINUX or IS_MACOS:
        for cand in ("python3", "python"):
            if shutil.which(cand):
                return cand
    else:
        for cand in ("python", "python3", "py"):
            if shutil.which(cand):
                return cand
    return sys.executable  # 最後 fallback


def find_runtime_binary(root: Path) -> Path | None:
    """找 siro-runtime binary（自動加 .exe for Windows）"""
    candidates = [
        root / "os-runtime" / "target" / "release" / "siro-runtime",
        root / "os-runtime" / "target" / "debug" / "siro-runtime",
    ]
    if IS_WINDOWS:
        candidates = [c.with_suffix(".exe") for c in candidates] + candidates
    for c in candidates:
        if c.exists():
            return c
    return None


def find_protoc() -> str | None:
    """找 protoc（給 siro-runtime build script 用）"""
    for cand in (["protoc.exe"] if IS_WINDOWS else []) + ["protoc"]:
        if shutil.which(cand):
            return cand
    return None


# ==================== Port 管理 ====================

def port_in_use(port: int) -> bool:
    """檢查 port 是否有人 listen"""
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    return True
        except Exception:
            pass
        return False
    else:
        # Linux / macOS：lsof 優先、fallback ss
        try:
            out = subprocess.run(
                ["lsof", "-ti:" + str(port)],
                capture_output=True, text=True, timeout=5,
            )
            if out.stdout.strip():
                return True
        except FileNotFoundError:
            pass
        try:
            out = subprocess.run(
                ["ss", "-tln"],
                capture_output=True, text=True, timeout=5,
            )
            if f":{port} " in out.stdout:
                return True
        except FileNotFoundError:
            pass
        return False


def free_port(port: int) -> bool:
    """砍掉佔 port 的 process"""
    if not port_in_use(port):
        return False

    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        info(f"  port {port} 被 PID {pid} 佔、taskkill /F")
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            capture_output=True, timeout=5,
                        )
                        return True
        except Exception as e:
            fail(f"  free port {port} 失敗: {e}")
    else:
        try:
            out = subprocess.run(
                ["lsof", "-ti:" + str(port)],
                capture_output=True, text=True, timeout=5,
            )
            for pid in out.stdout.split():
                info(f"  port {port} 被 PID {pid} 佔、kill -9")
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            return True
        except FileNotFoundError:
            warn("  lsof 沒裝、改用 fuser")
            try:
                subprocess.run(
                    ["fuser", "-k", "-9", f"{port}/tcp"],
                    capture_output=True, timeout=5,
                )
            except FileNotFoundError:
                fail("  沒 lsof 也沒 fuser、無法 free port")
    return False


# ==================== 啟動子進程 ====================

def start_siro_runtime(root: Path) -> subprocess.Popen | None:
    """啟動 siro-runtime（背景）"""
    bin_path = find_runtime_binary(root)
    if not bin_path:
        warn("siro-runtime binary 不存在、跳過（bridge 會標 disabled）")
        return None

    protoc = find_protoc()
    if not protoc:
        warn("protoc 沒裝、siro-runtime build 會失敗（但 runtime 不需要）")
        protoc = "protoc"  # 留 fallback

    info(f"啟動 siro-runtime: {bin_path}")
    log_path = root / "logs" / "siro_runtime.log"
    log_path.parent.mkdir(exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")

    env = os.environ.copy()
    env["PROTOC"] = protoc

    try:
        proc = subprocess.Popen(
            [str(bin_path), "--auto-start=false"],
            cwd=str(root / "os-runtime"),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=not IS_WINDOWS,  # Linux/Mac 用 process group
        )
    except Exception as e:
        fail(f"啟動 siro-runtime 失敗: {e}")
        return None

    # 等 2 秒看有沒有起來
    time.sleep(2)
    if port_in_use(50051):
        ok("siro-runtime 啟動成功 (port 50051)")
        return proc
    else:
        warn("siro-runtime 沒起來、看 logs/siro_runtime.log")
        return proc


def start_bridge(root: Path, python: str) -> subprocess.Popen | None:
    """啟動 bridge（背景）"""
    info(f"啟動 bridge (python={python})")
    log_path = root / "logs" / "bridge.log"
    log_path.parent.mkdir(exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")

    env = os.environ.copy()
    env["SIRO_RUNTIME_ENABLED"] = "true"
    env["SIRO_USE_AGENT_MODE"] = "true"
    env["SIRO_TRUST_MODE"] = "true"

    try:
        proc = subprocess.Popen(
            [python, "-m", "bridge.main"],
            cwd=str(root),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=not IS_WINDOWS,
        )
    except Exception as e:
        fail(f"啟動 bridge 失敗: {e}")
        return None

    # 等 4 秒
    time.sleep(4)
    if port_in_use(8001):
        ok("bridge 啟動成功 (port 8001)")
        # 印 /health
        try:
            import urllib.request
            import json
            with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=2) as r:
                health = json.loads(r.read().decode())
                info(f"  /health = {health.get('status', '?')}")
        except Exception as e:
            warn(f"  /health 拉不到: {e}")
        return proc
    else:
        warn("bridge 沒起來、看 logs/bridge.log")
        return proc


# ==================== Main ====================

def main() -> int:
    parser = argparse.ArgumentParser(description="SIRO 跨平台啟動腳本")
    parser.add_argument("--no-runtime", action="store_true", help="跳過 siro-runtime")
    parser.add_argument("--clean-only", action="store_true", help="只清 port、不啟動")
    parser.add_argument("--no-bridge", action="store_true", help="只啟動 siro-runtime、不啟動 bridge")
    args = parser.parse_args()

    print(f"{C.BOLD}SIRO start_bridge.py{C.END} (v0.4+ cross-platform)")
    info(f"platform: {sys.platform} ({platform.machine()})")

    root = project_root()
    info(f"project root: {root}")
    os.chdir(root)

    # 1. 載入 .env
    load_dotenv(root / ".env")

    # 2. Free port
    info("檢查 port 8001...")
    if port_in_use(8001):
        info("  port 8001 被佔、清掉...")
        free_port(8001)
    info("檢查 port 50051...")
    if port_in_use(50051):
        info("  port 50051 被佔、清掉...")
        free_port(50051)

    if args.clean_only:
        ok("clean-only 模式、退出")
        return 0

    procs: list[subprocess.Popen] = []

    # 3. 啟動 siro-runtime
    if not args.no_runtime:
        runtime_proc = start_siro_runtime(root)
        if runtime_proc:
            procs.append(runtime_proc)

    # 4. 啟動 bridge
    if not args.no_bridge:
        python_bin = find_python()
        bridge_proc = start_bridge(root, python_bin)
        if bridge_proc:
            procs.append(bridge_proc)

    if not procs:
        warn("沒有任何 process 啟動、退出")
        return 1

    print()
    print(f"  {C.OK}✅ SIRO 已啟動{C.END}")
    print(f"  - logs: {root / 'logs'}")
    print(f"  - 停掉: Ctrl+C 然後跑 {C.BOLD}python scripts/stop_bridge.py{C.END}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
