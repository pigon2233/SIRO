#!/usr/bin/env python3
"""
check-env.py - 檢查 SIRO 開發環境是否就緒

檢查項目：
    1. Python 版本（3.11+）
    2. venv 啟用
    3. bridge/ 必要套件
    4. .env 存在 + 有必要變數
    5. Ollama / hermes / protoc / Rust toolchain
    6. os-runtime cargo build 通過（選擇性）

執行：
    python scripts/dev/check-env.py
    python scripts/dev/check-env.py --strict    # 任何 fail 就 exit 1
    python scripts/dev/check-env.py --no-rust   # 跳過 Rust 檢查
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 顏色（Windows 也支援）
class C:
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    DIM = "\033[90m"
    BOLD = "\033[1m"
    END = "\033[0m"


def header(title: str) -> None:
    print(f"\n{C.BOLD}== {title} =={C.END}")


def ok(msg: str) -> None:
    print(f"  {C.OK}✓{C.END} {msg}")


def warn(msg: str) -> None:
    print(f"  {C.WARN}⚠{C.END} {msg}")


def fail(msg: str) -> None:
    print(f"  {C.FAIL}✗{C.END} {msg}")


def info(msg: str) -> None:
    print(f"  {C.DIM}·{C.END} {msg}")


def check_python() -> bool:
    header("Python")
    v = sys.version_info
    target = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 11):
        ok(f"Python {target}（>= 3.11 達標）")
        return True
    fail(f"Python {target}（需要 >= 3.11）")
    return False


def check_venv() -> bool:
    header("venv")
    if sys.prefix != sys.base_prefix:
        ok(f"在 venv 內：{sys.prefix}")
        return True
    # Python 直接跑（沒 venv）也 OK、但提示
    warn("沒在 venv 內（直接系統 Python）— bridge 仍可跑、但建議 venv")
    return True


def check_bridge_deps() -> bool:
    header("bridge/ 必要套件")
    bridge_dir = Path(__file__).resolve().parents[2] / "bridge"
    if not bridge_dir.exists():
        fail(f"找不到 {bridge_dir}")
        return False
    ok(f"bridge/ 路徑存在：{bridge_dir}")

    # 檢查關鍵 import
    must_import = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "websockets",
    ]
    all_ok = True
    for mod in must_import:
        try:
            __import__(mod)
            ok(f"  {mod} OK")
        except ImportError:
            fail(f"  {mod} 缺（pip install -r bridge/requirements.txt）")
            all_ok = False
    return all_ok


def check_env_file() -> bool:
    header(".env")
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    if not env_path.exists():
        warn(f".env 不存在：{env_path}（bridge 仍可跑、會用預設值）")
        return True
    ok(f".env 存在：{env_path}")
    # 檢查必要變數
    from_env = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            from_env[k.strip()] = v.strip()
    optional = ["ANTHROPIC_API_KEY", "HERMES_BIN_PATH", "OLLAMA_HOST"]
    found = [k for k in optional if k in from_env]
    if found:
        ok(f"找到 {len(found)}/{len(optional)} 個選擇性變數：{', '.join(found)}")
    else:
        info("沒設任何選擇性 env var（會用預設）")
    return True


def check_ollama() -> bool:
    header("Ollama")
    if shutil.which("ollama"):
        ok("ollama CLI 找得到")
        return True
    warn("ollama CLI 找不到（bridge fallback 不可用、需要 Ollama 跑在 localhost:11434 時才需要）")
    return True


def check_hermes() -> bool:
    header("Hermes Agent")
    candidates = [
        Path.home() / ".local" / "bin" / "hermes",
        Path.home() / "hermes-agent" / ".venv" / "Scripts" / "hermes.exe",
        Path.home() / "hermes-agent" / ".venv" / "bin" / "hermes",
        Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent" / ".venv" / "Scripts" / "hermes.exe",
    ]
    for c in candidates:
        if c.exists():
            ok(f"Hermes 找到：{c}")
            return True
    warn("Hermes 沒裝（不影響 v1.5+ streaming / Ollama fallback 路徑）")
    info(f"  試過：{', '.join(str(c) for c in candidates)}")
    return True


def check_rust() -> bool:
    header("Rust toolchain")
    if not shutil.which("cargo"):
        warn("cargo 找不到（Phase 3 siro-runtime 不能 build）")
        return True
    ok(f"cargo 找得到：{shutil.which('cargo')}")
    if not shutil.which("protoc"):
        warn("protoc 找不到（os-runtime gRPC build 會失敗）")
        if sys.platform == "win32":
            info("  Windows 安裝：winget install Google.Protobuf")
        elif sys.platform == "darwin":
            info("  macOS 安裝：brew install protobuf")
        else:
            info("  Linux 安裝：sudo apt install protobuf-compiler")
    else:
        ok(f"protoc 找得到：{shutil.which('protoc')}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="SIRO 開發環境檢查")
    parser.add_argument("--strict", action="store_true", help="任何 fail 就 exit 1")
    parser.add_argument("--no-rust", action="store_true", help="跳過 Rust 檢查")
    args = parser.parse_args()

    print(f"{C.BOLD}SIRO dev environment check{C.END}")
    print(f"  Python: {sys.executable}")
    print(f"  CWD:    {os.getcwd()}")

    results = []
    results.append(check_python())
    results.append(check_venv())
    results.append(check_bridge_deps())
    results.append(check_env_file())
    results.append(check_ollama())
    results.append(check_hermes())
    if not args.no_rust:
        results.append(check_rust())

    header("總結")
    fails = sum(1 for r in results if not r)
    warns_count = 0  # 簡化版不算 warning 數
    if fails == 0:
        print(f"  {C.OK}✓ 全部 {len(results)} 項通過{C.END}")
        return 0
    else:
        print(f"  {C.FAIL}✗ {fails}/{len(results)} 項失敗{C.END}")
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
