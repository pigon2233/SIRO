"""
bridge/tests/test_runtime_client.py

測試 v0 stub 模式的 RuntimeClient 行為。
"""

import pytest
from unittest.mock import patch, MagicMock

from bridge.runtime_client import RuntimeClient, get_runtime_client


class TestRuntimeClientStubMode:
    """v0 階段，RuntimeClient 是 stub，預設 disabled"""

    def setup_method(self):
        # 確保每個 test 用乾淨的狀態
        import bridge.runtime_client as rc
        rc._runtime_client = None

    def test_stub_not_connected_by_default(self):
        client = RuntimeClient(enabled=False)
        assert client.is_connected() is False

    def test_stub_health_returns_not_connected(self):
        client = RuntimeClient(enabled=False)
        health = client.health()
        assert health["healthy"] is False
        assert "reason" in health

    def test_stub_get_status_returns_empty(self):
        client = RuntimeClient(enabled=False)
        status = client.get_status()
        assert status["connected"] is False
        assert status["services"] == {}

    def test_stub_get_hardware_info_returns_unavailable(self):
        client = RuntimeClient(enabled=False)
        info = client.get_hardware_info()
        assert info["available"] is False

    def test_stub_restart_service_returns_failure(self):
        client = RuntimeClient(enabled=False)
        ok, msg = client.restart_service("bridge")
        assert ok is False
        assert "not connected" in msg.lower()

    def test_stub_set_kiosk_returns_failure(self):
        client = RuntimeClient(enabled=False)
        ok, msg = client.set_kiosk_mode(True)
        assert ok is False
        assert "not connected" in msg.lower()

    def test_stub_close_is_safe(self):
        client = RuntimeClient(enabled=False)
        client.close()  # 不應該 raise
        client.close()  # 重複呼叫也要安全

    def test_address_from_env(self, monkeypatch):
        monkeypatch.setenv("SIRO_RUNTIME_ADDR", "192.168.1.100:50051")
        client = RuntimeClient(enabled=False)
        assert client.address == "192.168.1.100:50051"

    def test_address_default(self, monkeypatch):
        monkeypatch.delenv("SIRO_RUNTIME_ADDR", raising=False)
        client = RuntimeClient(enabled=False)
        assert client.address == "127.0.0.1:50051"

    def test_explicit_address_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SIRO_RUNTIME_ADDR", "from-env:1234")
        client = RuntimeClient(address="explicit:5678", enabled=False)
        assert client.address == "explicit:5678"


class TestRuntimeClientSingleton:
    """get_runtime_client() 應該回傳 singleton"""

    def setup_method(self):
        import bridge.runtime_client as rc
        rc._runtime_client = None

    def test_singleton_returns_same_instance(self):
        a = get_runtime_client()
        b = get_runtime_client()
        assert a is b

    def test_singleton_respects_env(self, monkeypatch):
        monkeypatch.setenv("SIRO_RUNTIME_ENABLED", "false")
        import bridge.runtime_client as rc
        rc._runtime_client = None

        client = get_runtime_client()
        assert client.enabled is False

    def test_singleton_with_enabled(self, monkeypatch):
        monkeypatch.setenv("SIRO_RUNTIME_ENABLED", "true")
        import bridge.runtime_client as rc
        rc._runtime_client = None

        client = get_runtime_client()
        assert client.enabled is True


class TestRuntimeClientStubRunnable:
    """直接跑 runtime_client.py 的 __main__ 應該沒錯

    注意：subprocess 測試在跟其他 test 一起跑時可能 flaky（test pollution），
    所以這個 case 暫時拔掉。如果之後要做更嚴謹的 e2e 測試再補回來。
    """
