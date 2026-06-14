"""
bridge/tools/os_runtime_client.py - v1.5.3 os-runtime gRPC client helper

提供 bridge/tools/* 模組呼叫 os-runtime 的 5 個 system control RPC:
- ExecuteCommand
- ReadFile
- WriteFile
- ListDirectory
- StatPath

設計：
- Lazy connection（第一次用才 connect、避免 bridge 啟動就連不上 os-runtime 整個炸）
- 共用 channel（不要每個 RPC 都建）
- 處理 connection error、回傳 dict 給 caller（跟其他 tool 一致）
- 從 env var SIRO_RUNTIME_ADDR 讀位置（預設 127.0.0.1:50051）

替代 v1.5+ 的 Python subprocess 直接跑 — 統一走 gRPC
之後 Phase 4 Linux 部署只要改 env var 就 work
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


def get_runtime_addr() -> str:
    """拿 os-runtime gRPC address（從 env var、預設 127.0.0.1:50051）"""
    return os.environ.get("SIRO_RUNTIME_ADDR", "127.0.0.1:50051")


class OsRuntimeClient:
    """v1.5.3 os-runtime gRPC client

    Lazy connection + 共享 channel
    給 bridge/tools/* 的 executor 用
    """

    def __init__(self, address: Optional[str] = None, timeout_sec: float = 5.0):
        self.address = address or get_runtime_addr()
        self.timeout_sec = timeout_sec
        self._channel = None
        self._stub = None
        self._lock = threading.Lock()

    def _ensure_stub(self):
        """Lazy init：第一次用才 import + connect"""
        if self._stub is not None:
            return self._stub

        with self._lock:
            if self._stub is not None:
                return self._stub

            try:
                import grpc
                # 加 sys.path 處理：siro_pb2 跟 siro_pb2_grpc 是相對 import
                import sys
                from pathlib import Path
                gen_dir = Path(__file__).parent.parent / "grpc_client" / "generated"
                if str(gen_dir) not in sys.path:
                    sys.path.insert(0, str(gen_dir))
                import siro_pb2
                import siro_pb2_grpc
            except ImportError as e:
                logger.error(f"[os_runtime_client] import failed: {e}")
                raise

            self._channel = grpc.insecure_channel(self.address)
            self._stub = siro_pb2_grpc.SiroRuntimeStub(self._channel)
            logger.info(f"[os_runtime_client] connected to {self.address}")
            return self._stub

    def close(self):
        if self._channel is not None:
            self._channel.close()
            self._channel = None
            self._stub = None

    # ============================================================
    # 5 個 system control RPC
    # ============================================================

    def execute_command(
        self,
        cmd: str,
        cwd: str = ".",
        timeout_sec: int = 30,
        trust_mode: bool = False,
        user_id: str = "bridge",
    ) -> dict:
        """ExecuteCommand RPC

        Args:
            cmd: 完整指令字串
            cwd: 工作目錄（".") 或 sandbox 內絕對路徑
            timeout_sec: 最多跑幾秒
            trust_mode: 從 SIRO_TRUST_MODE env 傳過來（純 log 用）
            user_id: 觸發的 user（給 audit log）

        Returns:
            dict 形如 {"ok": bool, "exit_code": int, "stdout": str, "stderr": str,
                       "stdout_truncated": bool, "stderr_truncated": bool,
                       "duration_ms": int, "category": str, "block_reason": str}
        """
        try:
            import siro_pb2
            stub = self._ensure_stub()
            req = siro_pb2.CommandRequest(
                cmd=cmd,
                cwd=cwd,
                timeout_sec=timeout_sec,
                trust_mode=trust_mode,
                user_id=user_id,
            )
            resp = stub.ExecuteCommand(req, timeout=self.timeout_sec + timeout_sec)
            return {
                "ok": resp.exit_code == 0,
                "exit_code": resp.exit_code,
                "stdout": resp.stdout,
                "stderr": resp.stderr,
                "stdout_truncated": resp.stdout_truncated,
                "stderr_truncated": resp.stderr_truncated,
                "duration_ms": resp.duration_ms,
                "original_size_stdout": resp.original_size_stdout,
                "original_size_stderr": resp.original_size_stderr,
                "category": resp.category,
                "block_reason": resp.block_reason,
            }
        except Exception as e:
            logger.error(f"[os_runtime_client] execute_command failed: {e}")
            return {
                "ok": False,
                "error": f"gRPC call failed: {type(e).__name__}: {e}",
            }

    def read_file(
        self,
        path: str,
        max_lines: int = 200,
        trust_mode: bool = False,
        user_id: str = "bridge",
    ) -> dict:
        """ReadFile RPC"""
        try:
            import siro_pb2
            stub = self._ensure_stub()
            req = siro_pb2.PathRequest(
                path=path,
                trust_mode=trust_mode,
                user_id=user_id,
                max_lines=max_lines,
            )
            resp = stub.ReadFile(req, timeout=self.timeout_sec)
            return {
                "ok": True,
                "path": resp.path,
                "content": resp.content,
                "size_bytes": resp.size_bytes,
                "truncated": resp.truncated,
                "line_count": resp.line_count,
            }
        except Exception as e:
            err_str = str(e)
            if "NotFound" in err_str or "not found" in err_str.lower():
                return {"ok": False, "error": f"檔案不存在：{path}"}
            if "InvalidArgument" in err_str or "traversal" in err_str.lower():
                return {"ok": False, "error": err_str}
            logger.error(f"[os_runtime_client] read_file failed: {e}")
            return {"ok": False, "error": f"gRPC call failed: {type(e).__name__}: {e}"}

    def write_file(
        self,
        path: str,
        content: str,
        trust_mode: bool = False,
        user_id: str = "bridge",
    ) -> dict:
        """WriteFile RPC"""
        try:
            import siro_pb2
            stub = self._ensure_stub()
            req = siro_pb2.WriteFileRequest(
                path=path,
                content=content,
                trust_mode=trust_mode,
                user_id=user_id,
            )
            resp = stub.WriteFile(req, timeout=self.timeout_sec)
            if resp.ok:
                return {
                    "ok": True,
                    "path": path,
                    "bytes_written": resp.bytes_written,
                }
            return {"ok": False, "error": resp.error or "write failed"}
        except Exception as e:
            err_str = str(e)
            if "InvalidArgument" in err_str or "traversal" in err_str.lower():
                return {"ok": False, "error": err_str}
            logger.error(f"[os_runtime_client] write_file failed: {e}")
            return {"ok": False, "error": f"gRPC call failed: {type(e).__name__}: {e}"}

    def list_directory(
        self,
        path: str,
        recursive: bool = False,
        trust_mode: bool = False,
        user_id: str = "bridge",
    ) -> dict:
        """ListDirectory RPC"""
        try:
            import siro_pb2
            stub = self._ensure_stub()
            req = siro_pb2.PathRequest(
                path=path,
                trust_mode=trust_mode,
                user_id=user_id,
                recursive=recursive,
            )
            resp = stub.ListDirectory(req, timeout=self.timeout_sec)
            return {
                "ok": True,
                "path": resp.path,
                "entries": list(resp.entries),
                "count": resp.count,
                "truncated": resp.truncated,
            }
        except Exception as e:
            err_str = str(e)
            if "NotFound" in err_str or "not found" in err_str.lower():
                return {"ok": False, "error": f"目錄不存在：{path}"}
            if "InvalidArgument" in err_str or "traversal" in err_str.lower():
                return {"ok": False, "error": err_str}
            logger.error(f"[os_runtime_client] list_directory failed: {e}")
            return {"ok": False, "error": f"gRPC call failed: {type(e).__name__}: {e}"}

    def stat_path(
        self,
        path: str,
        trust_mode: bool = False,
        user_id: str = "bridge",
    ) -> dict:
        """StatPath RPC"""
        try:
            import siro_pb2
            stub = self._ensure_stub()
            req = siro_pb2.PathRequest(
                path=path,
                trust_mode=trust_mode,
                user_id=user_id,
            )
            resp = stub.StatPath(req, timeout=self.timeout_sec)
            return {
                "ok": True,
                "path": resp.path,
                "exists": resp.exists,
                "is_file": resp.is_file,
                "is_dir": resp.is_dir,
                "size_bytes": resp.size_bytes,
                "modified_ms": resp.modified_ms,
            }
        except Exception as e:
            err_str = str(e)
            if "InvalidArgument" in err_str or "traversal" in err_str.lower():
                return {"ok": False, "error": err_str}
            logger.error(f"[os_runtime_client] stat_path failed: {e}")
            return {"ok": False, "error": f"gRPC call failed: {type(e).__name__}: {e}"}


# ============================================================
# Module-level singleton（lazy）
# ============================================================

_client: Optional[OsRuntimeClient] = None
_client_lock = threading.Lock()


def get_os_runtime_client() -> OsRuntimeClient:
    """拿 singleton client（測試時可以 reset）"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OsRuntimeClient()
    return _client


def reset_os_runtime_client() -> None:
    """重設 singleton（測試 fixture 用）"""
    global _client
    if _client is not None:
        _client.close()
    _client = None
