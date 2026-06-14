"""
tests/bridge/test_security.py

v1.5+ Computer control 安全護欄測試

涵蓋：
- SandboxPath path traversal 阻擋
- RateLimiter 限流
- AuditLog 寫入
- guarded_action context manager
"""
import os
import json
import time
from pathlib import Path

import pytest

# SIRO_SANDBOX_DIR 在 import security 之前設（讓 security.get_sandbox_root 拿對的值）
TEST_SANDBOX = Path(__file__).parent / ".test_siro_sandbox"


@pytest.fixture(autouse=True, scope="module")
def setup_sandbox_env():
    """設定 sandbox 環境變數、清掉舊的測試 sandbox"""
    os.environ["SIRO_SANDBOX_DIR"] = str(TEST_SANDBOX)
    # 清掉之前的測試殘留
    import shutil
    if TEST_SANDBOX.exists():
        shutil.rmtree(TEST_SANDBOX, ignore_errors=True)
    TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
    yield
    # 不清掉、方便 debug


@pytest.fixture(autouse=True)
def reset_singletons():
    """每個 test 前 reset rate limiter + audit log singleton"""
    from bridge.security import reset_security_singletons
    reset_security_singletons()
    yield
    reset_security_singletons()


# ============================================================
# SandboxPath tests
# ============================================================

class TestSandboxPath:
    """測 path traversal 防護"""

    def test_relative_path_inside_sandbox(self):
        from bridge.security import SandboxPath
        sp = SandboxPath("notes/hello.txt")
        result = sp.resolve()
        assert result == TEST_SANDBOX / "notes" / "hello.txt"

    def test_dot_path_resolves_to_root(self):
        from bridge.security import SandboxPath
        sp = SandboxPath(".")
        result = sp.resolve()
        assert result == TEST_SANDBOX

    def test_empty_path_rejected(self):
        from bridge.security import SandboxPath, SecurityError
        with pytest.raises(SecurityError, match="不可為空"):
            SandboxPath("").resolve()

    def test_absolute_path_rejected(self):
        from bridge.security import SandboxPath, SecurityError
        # Windows 把 /etc/passwd 視為相對（join 到 sandbox 根後變成 C:/etc/passwd）
        # 也會被 path traversal 防護擋下（解析後不在 sandbox 內）
        with pytest.raises(SecurityError):
            SandboxPath("/etc/passwd").resolve()

    def test_parent_traversal_rejected(self):
        from bridge.security import SandboxPath, SecurityError
        with pytest.raises(SecurityError, match="path traversal"):
            SandboxPath("../etc/passwd").resolve()

    def test_deep_parent_traversal_rejected(self):
        from bridge.security import SandboxPath, SecurityError
        with pytest.raises(SecurityError, match="path traversal"):
            SandboxPath("../../../../etc/passwd").resolve()

    def test_parent_then_back_in_rejected(self):
        from bridge.security import SandboxPath, SecurityError
        # notes/../outside/foo.txt → 解析後不在 sandbox 內
        with pytest.raises(SecurityError, match="path traversal"):
            SandboxPath("notes/../../outside/foo.txt").resolve()

    def test_relative_to_sandbox(self):
        from bridge.security import SandboxPath
        sp = SandboxPath("notes/hello.txt")
        # Windows 用 \、Unix 用 /、都接受
        result = sp.relative_to_sandbox()
        assert result in ("notes/hello.txt", "notes\\hello.txt")

    def test_relative_to_sandbox_root(self):
        from bridge.security import SandboxPath
        sp = SandboxPath(".")
        assert sp.relative_to_sandbox() == "."


# ============================================================
# RateLimiter tests
# ============================================================

class TestRateLimiter:
    """測 rate limit"""

    def test_first_call_allowed(self):
        from bridge.security import RateLimiter
        rl = RateLimiter()
        allowed, reason = rl.check()
        assert allowed is True
        assert reason is None

    def test_record_increments(self):
        from bridge.security import RateLimiter
        rl = RateLimiter(max_per_minute=3)
        for _ in range(3):
            allowed, _ = rl.check()
            assert allowed
            rl.record()
        # 第 4 次應該被擋
        allowed, reason = rl.check()
        assert allowed is False
        assert "per minute" in reason

    def test_reset_clears(self):
        from bridge.security import RateLimiter
        rl = RateLimiter(max_per_minute=2)
        rl.check(); rl.record()
        rl.check(); rl.record()
        assert not rl.check()[0]
        rl.reset()
        assert rl.check()[0]

    def test_daily_limit(self):
        from bridge.security import RateLimiter
        rl = RateLimiter(max_per_minute=1000, max_per_day=3)
        # 直接塞 3 個「24 小時內」的時間戳（觸發 daily limit）
        rl._timestamps = [time.time() - 100] * 3  # 100 秒前、在 daily 窗口內
        allowed, reason = rl.check()
        assert allowed is False
        assert "per day" in reason


# ============================================================
# AuditLog tests
# ============================================================

class TestAuditLog:
    """測 audit log 寫入 + 讀取"""

    def test_write_creates_file(self, tmp_path):
        from bridge.security import AuditLog
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path=log_path)
        log.write(
            user_id="alice",
            tool="list_dir",
            args={"path": "."},
            result="ok",
        )
        assert log_path.exists()
        content = log_path.read_text()
        entry = json.loads(content.strip())
        assert entry["user_id"] == "alice"
        assert entry["tool"] == "list_dir"
        assert entry["result"] == "ok"
        assert entry["user_confirmed"] is False

    def test_write_with_error_field(self, tmp_path):
        from bridge.security import AuditLog
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path=log_path)
        log.write(
            user_id="bob",
            tool="run_shell_cmd",
            args={"cmd": "rm -rf /"},
            result="denied",
            error="blocklist match",
        )
        entry = json.loads(log_path.read_text().strip())
        assert entry["error"] == "blocklist match"

    def test_read_recent_returns_last_n(self, tmp_path):
        from bridge.security import AuditLog
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path=log_path)
        for i in range(10):
            log.write(
                user_id=f"user{i}",
                tool="list_dir",
                args={"i": i},
                result="ok",
            )
        recent = log.read_recent(limit=3)
        assert len(recent) == 3
        # 最後 3 筆
        assert recent[-1]["user_id"] == "user9"
        assert recent[-2]["user_id"] == "user8"
        assert recent[-3]["user_id"] == "user7"

    def test_read_recent_empty_log(self, tmp_path):
        from bridge.security import AuditLog
        log_path = tmp_path / "nonexistent.jsonl"
        log = AuditLog(log_path=log_path)
        assert log.read_recent(limit=10) == []


# ============================================================
# guarded_action tests
# ============================================================

class TestGuardedAction:
    """測 guarded_action context manager"""

    def test_normal_completion(self):
        from bridge.security import guarded_action, get_audit_log, get_rate_limiter
        audit = get_audit_log()
        rl = get_rate_limiter()

        with guarded_action(user_id="alice", tool="list_dir", args={"path": "."}) as guard:
            guard.set_result("ok")

        # audit log 應該有一筆
        recent = audit.read_recent(limit=1)
        assert len(recent) == 1
        assert recent[0]["result"] == "ok"
        assert recent[0]["tool"] == "list_dir"

    def test_error_marks_error(self):
        from bridge.security import guarded_action, get_audit_log

        with pytest.raises(RuntimeError):
            with guarded_action(user_id="alice", tool="write_file", args={"path": "x"}) as guard:
                raise RuntimeError("test error")
                # 永遠不會跑到這
                guard.set_result("ok")

        recent = get_audit_log().read_recent(limit=1)
        assert recent[0]["result"] == "error"
        assert "test error" in recent[0].get("error", "")

    def test_rate_limit_blocks(self):
        from bridge.security import guarded_action, SecurityError
        from bridge.security import get_rate_limiter
        rl = get_rate_limiter()
        # 填到上限
        rl.max_per_minute = 2
        rl.check(); rl.record()
        rl.check(); rl.record()

        with pytest.raises(SecurityError, match="rate_limit"):
            with guarded_action(user_id="alice", tool="list_dir", args={}):
                pytest.fail("不該跑到這")
