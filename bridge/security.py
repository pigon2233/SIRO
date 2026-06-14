"""
bridge/security.py - v1.5+ SIRO 自主操作的安全護欄

三層保護（詳見 docs/PLANS/agent-computer-control.md §3.1）：
1. Sandbox path check — 所有檔案操作必須在 sandbox 內
2. Rate limiter — 防止 busy loop
3. Audit log — 留下每個 action 的 trace

模組結構：
- SandboxPath: 把路徑 resolve 成絕對路徑、確認在 sandbox 內
- RateLimiter: sliding window 計數
- AuditLog: append-only JSONL writer
- SecurityError: 例外類別、SIRO tool 收到可以轉成 error result
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# 安全例外
# ============================================================

class SecurityError(Exception):
    """SIRO tool 操作被安全機制擋下時丟這個

    設計：tool 實作遇到 sandbox 違規 / rate limit / blocklist 規則、
    拋 SecurityError。caller（tool dispatch）會把 exception message
    包成 tool_result 回給 LLM、LLM 看到 error 就知道「不行、重想」。
    """


# ============================================================
# Layer 1: Sandbox path check
# ============================================================

# Sandbox 預設路徑（用 env var 覆寫方便測試）
DEFAULT_SANDBOX = Path.home() / "siro-sandbox"


def get_sandbox_root() -> Path:
    """拿 sandbox 根目錄（從 env var 讀、可被測試覆寫）

    設計：環境變數 SIRO_SANDBOX_DIR 存在就用、不存在就 fallback 到
    ~/siro-sandbox/。測試時設 tmpdir、避免污染真實 home。
    """
    env_path = os.environ.get("SIRO_SANDBOX_DIR")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_SANDBOX.expanduser().resolve()


class SandboxPath:
    """sandbox 內路徑驗證

    用法：
        sp = SandboxPath("notes/hello.txt")
        sp.resolve()  # → /home/user/siro-sandbox/notes/hello.txt
        sp.relative_to_sandbox()  # → notes/hello.txt

        # path traversal
        SandboxPath("../etc/passwd").resolve()  # 拋 SecurityError

    設計：
    - LLM 給的是相對路徑（"notes/foo.txt"）→ 解析到 sandbox 內
    - 給絕對路徑（"/etc/passwd"）→ 拒絕（不是 sandbox 內）
    - 給 ".." 開頭 → 解析後還是不在 sandbox → 拒絕
    - 給 symlink 指到 sandbox 外 → resolve() 後還是會在 sandbox 外 → 拒絕
    """

    def __init__(self, raw_path: str, sandbox_root: Optional[Path] = None):
        self.raw = raw_path
        self.sandbox_root = sandbox_root or get_sandbox_root()

    def resolve(self) -> Path:
        """解析成絕對路徑、確認在 sandbox 內

        Returns:
            Path: 解析後的絕對路徑（保證在 sandbox 內）

        Raises:
            SecurityError: 路徑在 sandbox 外、或是 path traversal
        """
        if not self.raw:
            raise SecurityError("path 不可為空")

        # 把空 / 點路徑當作 sandbox 根
        if self.raw in (".", "", "/"):
            return self.sandbox_root

        # 先 expanduser、但不 resolve 絕對（sandbox 內相對路徑要相對於 sandbox root）
        candidate = Path(self.raw)

        # 如果給的是絕對路徑（Unix / Windows 都行）→ 拒絕
        # 設計：v1.5+ 階段 LLM 不該用絕對路徑（不該知道自己的路徑結構）
        if candidate.is_absolute():
            raise SecurityError(
                f"不允許絕對路徑：{self.raw!r}。"
                f"請用相對路徑（相對於 sandbox 根目錄）"
            )

        # 把 sandbox root 當前綴
        joined = self.sandbox_root / candidate

        # resolve（會處理 .. 跟 symlink）
        try:
            resolved = joined.resolve(strict=False)
        except (OSError, RuntimeError) as e:
            raise SecurityError(f"路徑解析失敗：{self.raw!r}: {e}")

        # 確認 resolved 在 sandbox root 內
        # 用 is_relative_to（Python 3.9+）或 try/except ValueError
        try:
            resolved.relative_to(self.sandbox_root)
        except ValueError:
            raise SecurityError(
                f"path traversal 被擋下：{self.raw!r} "
                f"（解析後 {resolved} 不在 sandbox {self.sandbox_root} 內）"
            )

        return resolved

    def relative_to_sandbox(self) -> str:
        """解析後、轉成相對 sandbox 的字串

        用於 display / log（不暴露 user 的 home 絕對路徑）
        """
        abs_path = self.resolve()
        try:
            return str(abs_path.relative_to(self.sandbox_root))
        except ValueError:
            return str(abs_path)


def ensure_sandbox() -> Path:
    """確認 sandbox 目錄存在、不存在就建

    Returns:
        Path: sandbox 根目錄
    """
    root = get_sandbox_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


# ============================================================
# Layer 2: Rate limiter
# ============================================================

class RateLimiter:
    """sliding window rate limiter

    設計：
    - 兩個 window：per-minute (30) + per-day (1000)
    - 用 deque 存 timestamps、超過 window 的丟掉
    - 兩個 window 都通過才 allow
    - 用 lock 保護（SIRO 工具可能在多 thread 跑）
    """

    def __init__(
        self,
        max_per_minute: int = 30,
        max_per_day: int = 1000,
    ):
        self.max_per_minute = max_per_minute
        self.max_per_day = max_per_day
        self._timestamps: list[float] = []  # 全 action 時間戳
        self._lock = threading.Lock()

    def check(self) -> tuple[bool, Optional[str]]:
        """檢查現在能不能跑一個 action

        Returns:
            (allowed, reason_if_blocked)
        """
        now = time.time()
        with self._lock:
            # 清掉過期的
            self._timestamps = [t for t in self._timestamps if now - t < 86400]

            # 過去一分鐘有幾次
            minute_ago = now - 60
            recent_minute = sum(1 for t in self._timestamps if t >= minute_ago)
            if recent_minute >= self.max_per_minute:
                return False, (
                    f"rate_limit_exceeded: {recent_minute}/{self.max_per_minute} actions per minute, "
                    f"等一下再試"
                )

            # 過去一天有幾次
            day_ago = now - 86400
            recent_day = sum(1 for t in self._timestamps if t >= day_ago)
            if recent_day >= self.max_per_day:
                return False, (
                    f"rate_limit_exceeded: {recent_day}/{self.max_per_day} actions per day"
                )

            return True, None

    def record(self) -> None:
        """記錄一次 action（check 通過後呼叫）"""
        with self._lock:
            self._timestamps.append(time.time())

    def reset(self) -> None:
        """重設計數（測試用）"""
        with self._lock:
            self._timestamps.clear()


# ============================================================
# Layer 3: Audit log
# ============================================================

class AuditLog:
    """append-only JSONL audit log

    設計：
    - 每行一個 JSON object
    - 寫入失敗也不能讓 bridge crash（用 try/except 吃掉、log warning）
    - 檔案在 bridge/logs/siro-actions.jsonl
    - 用 file lock 避免 multi-process 寫入交錯（append mode 通常已經 serial、
      但 Windows 行為不太一樣、保險一點用 lock）
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or (
            Path(__file__).parent / "logs" / "siro-actions.jsonl"
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(
        self,
        *,
        user_id: str,
        tool: str,
        args: dict,
        result: str,
        user_confirmed: bool = False,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """寫一條 audit entry

        Args:
            user_id: 觸發這個 action 的 user
            tool: tool name (e.g. "run_shell_cmd")
            args: tool 的輸入參數
            result: "ok" / "denied" / "error"
            user_confirmed: 是否有 user 確認（危險操作）
            duration_ms: 執行時間
            error: 錯誤訊息（如果有）
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "tool": tool,
            "args": args,
            "result": result,
            "user_confirmed": user_confirmed,
            "duration_ms": duration_ms,
        }
        if error:
            entry["error"] = error

        try:
            with self._lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # 寫 audit 失敗不能讓 bridge 掛掉、log warning
            logger.warning(f"[audit] 寫 audit log 失敗: {e}")

    def read_recent(self, limit: int = 50) -> list[dict]:
        """讀最近 N 條 entry（給 /siro/actions endpoint 用）"""
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as e:
            logger.warning(f"[audit] 讀 audit log 失敗: {e}")
            return []

        entries = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries


# ============================================================
# 便利函式：組合三層保護
# ============================================================

# Module-level singleton（給 tool implementations 用）
# v1.5+ 階段 SIRO 跑在單 process、singleton 沒問題
_rate_limiter: Optional[RateLimiter] = None
_audit_log: Optional[AuditLog] = None


def get_rate_limiter() -> RateLimiter:
    """拿 singleton rate limiter（測試時可以 reset）"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def get_audit_log() -> AuditLog:
    """拿 singleton audit log"""
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log


def reset_security_singletons() -> None:
    """重設 singleton（測試 fixture 用）"""
    global _rate_limiter, _audit_log
    _rate_limiter = None
    _audit_log = None


@contextmanager
def guarded_action(
    *,
    user_id: str,
    tool: str,
    args: dict,
    user_confirmed: bool = False,
):
    """context manager：包住 tool 執行、處理 rate limit + audit

    用法：
        with guarded_action(user_id=user_id, tool="run_shell_cmd", args={"cmd": "ls"}) as guard:
            result = subprocess.run(...)
            guard.set_result("ok")
    """
    rate_limiter = get_rate_limiter()
    audit = get_audit_log()

    allowed, reason = rate_limiter.check()
    if not allowed:
        audit.write(
            user_id=user_id,
            tool=tool,
            args=args,
            result="denied",
            user_confirmed=user_confirmed,
            error=reason,
        )
        raise SecurityError(reason or "rate limit exceeded")

    rate_limiter.record()
    t0 = time.time()
    guard = _Guard(audit=audit, user_id=user_id, tool=tool, args=args, t0=t0, user_confirmed=user_confirmed)
    try:
        yield guard
    except Exception as e:
        guard.mark_error(str(e))
        raise
    finally:
        if not guard._finalized:
            guard.mark_error("context exited without set_result or mark_error")
            guard._finalized = True
            guard._write_if_needed()


class _Guard:
    """guarded_action 內部的 helper、追蹤 action 結果"""

    def __init__(self, *, audit, user_id, tool, args, t0, user_confirmed):
        self._audit = audit
        self._user_id = user_id
        self._tool = tool
        self._args = args
        self._t0 = t0
        self._user_confirmed = user_confirmed
        self._result: Optional[str] = None
        self._error: Optional[str] = None
        self._finalized = False

    def set_result(self, result: str = "ok") -> None:
        """記 action 成功（或其他正常 result）"""
        if self._finalized:
            return
        self._result = result
        self._finalized = True
        self._write_if_needed()

    def mark_error(self, error: str) -> None:
        """記 action 失敗"""
        if self._finalized:
            return
        self._result = "error"
        self._error = error
        self._finalized = True
        self._write_if_needed()

    def mark_denied(self) -> None:
        """記 action 被 user 拒絕"""
        if self._finalized:
            return
        self._result = "denied"
        self._finalized = True
        self._write_if_needed()

    def _write_if_needed(self) -> None:
        """寫 audit log（只在 finalize 後調用一次）"""
        duration_ms = int((time.time() - self._t0) * 1000)
        self._audit.write(
            user_id=self._user_id,
            tool=self._tool,
            args=self._args,
            result=self._result or "ok",
            user_confirmed=self._user_confirmed,
            duration_ms=duration_ms,
            error=self._error,
        )
