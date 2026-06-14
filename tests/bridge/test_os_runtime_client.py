"""
tests/bridge/test_os_runtime_client.py

v1.5.3 os-runtime gRPC client mock — 給其他 v15 tool 測試用

注意：FakeOsRuntimeClient 跟 fake_os_runtime_client fixture 在
conftest.py 裡、這檔只 export class
"""

import subprocess
import shlex
from pathlib import Path


class FakeOsRuntimeClient:
    """Mock OsRuntimeClient、繞過 gRPC 直接操作 sandbox

    給 filesystem.py / shell.py 工具的測試用、避免需要真的 siro-runtime
    跟 siro_pb2 模組（測試環境不一定能 import grpc stubs）
    """

    def __init__(self, sandbox_root: Path):
        self.sandbox_root = sandbox_root
        self.calls: list[dict] = []  # 記所有 RPC call、debug 用

    # ---- 5 個 RPC 對應的方法（v1.5.3 介面）----

    def execute_command(
        self, *, cmd, cwd=".", timeout_sec=30, trust_mode=False, user_id="bridge"
    ) -> dict:
        import subprocess
        import shlex
        self.calls.append({
            "rpc": "ExecuteCommand",
            "cmd": cmd, "cwd": cwd, "timeout_sec": timeout_sec,
            "trust_mode": trust_mode, "user_id": user_id,
        })
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            return {"ok": False, "error": f"cmd 解析失敗：{e}"}
        if not parts:
            return {"ok": False, "error": "cmd 解析後是空的"}
        try:
            result = subprocess.run(
                parts, shell=False, cwd=str(self.sandbox_root),
                capture_output=True, text=True, timeout=timeout_sec,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout（{timeout_sec}s）"}
        except FileNotFoundError as e:
            return {"ok": False, "error": f"指令找不到：{e}"}
        # 截斷
        MAX = 2000
        out = result.stdout or ""
        err = result.stderr or ""
        out_t = len(out) > MAX
        err_t = len(err) > MAX
        if out_t:
            out = out[:MAX] + f"\n... (truncated, 原本 {len(result.stdout)} 字)"
        if err_t:
            err = err[:MAX] + f"\n... (truncated, 原本 {len(result.stderr)} 字)"
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": out, "stderr": err,
            "stdout_truncated": out_t, "stderr_truncated": err_t,
            "duration_ms": 10,
            "original_size_stdout": len(result.stdout or ""),
            "original_size_stderr": len(result.stderr or ""),
            "category": "auto",
            "block_reason": "",
        }

    def read_file(self, *, path, max_lines=200, trust_mode=False, user_id="bridge") -> dict:
        from bridge.tools.filesystem import MAX_LINES_PER_READ  # noqa
        import os
        self.calls.append({"rpc": "ReadFile", "path": path, "max_lines": max_lines})

        # 解析路徑（用 lenient、跟 Rust fs_ops 一樣）
        from bridge.security import SandboxPath, SecurityError
        try:
            target = SandboxPath(path).resolve()
        except SecurityError as e:
            return {"ok": False, "error": str(e)}

        if not target.exists():
            return {"ok": False, "error": f"檔案不存在：{path}"}
        if not target.is_file():
            return {"ok": False, "error": f"不是檔案：{path}"}

        size = target.stat().st_size
        MAX = 200_000
        if size > MAX:
            return {"ok": False, "error": f"檔案太大（{size} bytes）"}

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            truncated = False
            for i, line in enumerate(f):
                if i >= max_lines:
                    truncated = True
                    break
                lines.append(line.rstrip("\n"))
        return {
            "ok": True,
            "path": path,
            "content": "\n".join(lines),
            "size_bytes": size,
            "truncated": truncated,
            "line_count": len(lines),
        }

    def write_file(self, *, path, content, trust_mode=False, user_id="bridge") -> dict:
        from bridge.security import SandboxPath, SecurityError
        self.calls.append({"rpc": "WriteFile", "path": path, "bytes": len(content)})
        try:
            target = SandboxPath(path).resolve()
        except SecurityError as e:
            return {"ok": False, "error": str(e)}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"建父目錄失敗：{e}"}
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return {"ok": False, "error": f"寫檔失敗：{e}"}
        return {
            "ok": True,
            "path": path,
            "bytes_written": len(content.encode("utf-8")),
        }

    def list_directory(self, *, path, recursive=False, trust_mode=False, user_id="bridge") -> dict:
        from bridge.security import SandboxPath, SecurityError
        self.calls.append({"rpc": "ListDirectory", "path": path, "recursive": recursive})
        try:
            target = SandboxPath(path).resolve()
        except SecurityError as e:
            return {"ok": False, "error": str(e)}
        if not target.exists():
            return {"ok": False, "error": f"目錄不存在：{path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"不是目錄：{path}"}
        from bridge.tools.filesystem import MAX_DIR_ENTRIES

        entries = []
        truncated = False
        try:
            if recursive:
                for p in sorted(target.rglob("*")):
                    rel = p.relative_to(target)
                    marker = "/" if p.is_dir() else ""
                    entries.append(f"{rel}{marker}")
                    if len(entries) >= MAX_DIR_ENTRIES:
                        truncated = True
                        break
            else:
                for p in sorted(target.iterdir()):
                    marker = "/" if p.is_dir() else ""
                    entries.append(f"{p.name}{marker}")
                    if len(entries) >= MAX_DIR_ENTRIES:
                        truncated = True
                        break
        except OSError as e:
            return {"ok": False, "error": f"list 失敗：{e}"}
        return {
            "ok": True,
            "path": path,
            "entries": entries,
            "count": len(entries),
            "truncated": truncated,
        }

    def stat_path(self, *, path, trust_mode=False, user_id="bridge") -> dict:
        from bridge.security import SandboxPath, SecurityError
        self.calls.append({"rpc": "StatPath", "path": path})
        try:
            target = SandboxPath(path).resolve()
        except SecurityError as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "path": path,
            "exists": target.exists(),
            "is_file": target.is_file(),
            "is_dir": target.is_dir(),
            "size_bytes": target.stat().st_size if target.exists() else 0,
            "modified_ms": 0,
        }

    def close(self):
        pass


# fixture 移到 conftest.py（讓所有 bridge test 都拿得到）
