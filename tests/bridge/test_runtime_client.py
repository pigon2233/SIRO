"""
tests/bridge/test_runtime_client.py

從 bridge/tests/ 搬過來 (Phase 1.75 — 統一放 tests/bridge/)
v0.3.0 Phase 3 — 加 enabled-mode 測試（mock gRPC channel 測 6 個 method）
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


# ============================================================
# v0.3.0 Phase 3：enabled mode + mock gRPC channel
# ============================================================

class TestRuntimeClientEnabledMode:
    """enabled=True 時應該實際走 gRPC、用 mock channel 測 6 個 method

    測試策略：patch grpc.insecure_channel + siro_pb2_grpc.SiroRuntimeStub，
    讓所有 RPC 走 MagicMock、可以設定 return value 或 raise。
    """

    def setup_method(self):
        import bridge.runtime_client as rc
        rc._runtime_client = None
        # 預設 mock：siro_pb2 跟 siro_pb2_grpc 是真 import 過的（生成 stub 存在）
        # 只需要 patch 產出 stub 的方式 + grpc.insecure_channel
        self.mock_channel = MagicMock()
        self.mock_stub = MagicMock()
        # patchers
        self.patcher_insecure = patch(
            "bridge.runtime_client.grpc.insecure_channel",
            return_value=self.mock_channel,
        )
        self.patcher_stub = patch(
            "bridge.runtime_client.siro_pb2_grpc.SiroRuntimeStub",
            return_value=self.mock_stub,
        )
        self.patcher_insecure.start()
        self.patcher_stub.start()

    def teardown_method(self):
        self.patcher_insecure.stop()
        self.patcher_stub.stop()

    # -------- is_connected / Health --------

    def test_enabled_is_connected_true(self):
        """Health RPC 回 healthy=True → is_connected True"""
        self.mock_stub.Health.return_value = MagicMock(healthy=True, version="0.1.0", uptime_seconds=10, issues=[])
        client = RuntimeClient(enabled=True, timeout_sec=0.5)
        assert client.is_connected() is True

    def test_enabled_is_connected_false_when_unhealthy(self):
        """Health RPC 回 healthy=False → is_connected False"""
        self.mock_stub.Health.return_value = MagicMock(healthy=False, version="0.1.0", uptime_seconds=0, issues=[])
        client = RuntimeClient(enabled=True, timeout_sec=0.5)
        assert client.is_connected() is False

    def test_enabled_is_connected_false_on_rpc_error(self):
        """RPC error（UNAVAILABLE）→ is_connected False（不 raise）"""
        import grpc
        err = grpc.RpcError()
        err.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        err.details = MagicMock(return_value="connection refused")
        self.mock_stub.Health.side_effect = err
        client = RuntimeClient(enabled=True, timeout_sec=0.5)
        assert client.is_connected() is False

    # -------- get_status --------

    def test_get_status_success(self):
        """GetStatus 回 system status → 解析成 dict"""
        # 模擬 services: map<string, ServiceState>
        mock_state = MagicMock()
        mock_state.status = 1  # RUNNING
        mock_state.pid = 12345
        mock_state.uptime_seconds = 60
        mock_state.memory_bytes = 5_000_000
        mock_state.last_error = ""
        mock_resp = MagicMock()
        mock_resp.services = {"bridge": mock_state}

        self.mock_stub.GetStatus.return_value = mock_resp
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        result = client.get_status()
        assert result["connected"] is True
        assert "bridge" in result["services"]
        assert result["services"]["bridge"]["status"] == "RUNNING"
        assert result["services"]["bridge"]["pid"] == 12345
        assert result["services"]["bridge"]["uptime_seconds"] == 60

    def test_get_status_empty_services(self):
        """GetStatus 回空 services map → 連得上但沒 service"""
        mock_resp = MagicMock()
        mock_resp.services = {}
        self.mock_stub.GetStatus.return_value = mock_resp
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        result = client.get_status()
        assert result["connected"] is True
        assert result["services"] == {}

    def test_get_status_rpc_error_returns_not_connected(self):
        """GetStatus RPC 失敗 → 降級回 connected=False"""
        import grpc
        err = grpc.RpcError()
        err.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        err.details = MagicMock(return_value="down")
        self.mock_stub.GetStatus.side_effect = err
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        result = client.get_status()
        assert result["connected"] is False
        assert "rpc_error" in result["reason"]

    # -------- get_hardware_info --------

    def test_get_hardware_info_success(self):
        """GetHardwareInfo 回 CPU + memory → 解析成 dict"""
        mock_cpu = MagicMock(model="AMD Ryzen 9", cores=8, threads=16, frequency_ghz=3.3)
        mock_mem = MagicMock(total_bytes=16_000_000_000, available_bytes=2_000_000_000)
        mock_resp = MagicMock(cpu=mock_cpu, memory=mock_mem, gpu=[], audio=[])
        self.mock_stub.GetHardwareInfo.return_value = mock_resp
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        result = client.get_hardware_info()
        assert result["available"] is True
        assert result["cpu"]["model"] == "AMD Ryzen 9"
        assert result["cpu"]["cores"] == 8
        assert result["memory"]["total_bytes"] == 16_000_000_000

    def test_get_hardware_info_rpc_error(self):
        """GetHardwareInfo RPC 失敗 → available=False"""
        import grpc
        err = grpc.RpcError()
        err.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        err.details = MagicMock(return_value="down")
        self.mock_stub.GetHardwareInfo.side_effect = err
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        result = client.get_hardware_info()
        assert result["available"] is False

    # -------- restart_service --------

    def test_restart_service_success(self):
        """RestartService 回 ok=True → (True, message)"""
        self.mock_stub.RestartService.return_value = MagicMock(ok=True, message="bridge 重啟成功")
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.restart_service("bridge")
        assert ok is True
        assert "重啟成功" in msg

    def test_restart_service_failure_response(self):
        """RestartService 回 ok=False → (False, message)"""
        self.mock_stub.RestartService.return_value = MagicMock(ok=False, message="service 不存在")
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.restart_service("nonexistent")
        assert ok is False
        assert "不存在" in msg

    def test_restart_service_rpc_error(self):
        """RestartService RPC 失敗 → (False, error message)"""
        import grpc
        err = grpc.RpcError()
        err.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        err.details = MagicMock(return_value="connection refused")
        self.mock_stub.RestartService.side_effect = err
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.restart_service("bridge")
        assert ok is False
        assert "UNAVAILABLE" in msg

    # -------- control_service (v0.3 新 method) --------

    def test_control_service_start(self):
        """ControlService action=1 (Start) → 成功"""
        self.mock_stub.ControlService.return_value = MagicMock(ok=True, message="bridge 動作成功")
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.control_service("bridge", "start")
        assert ok is True
        # 確認傳出的 action int 是 1 (Start)
        call_args = self.mock_stub.ControlService.call_args
        # call_args.args[0] 是 ServiceControl message
        assert call_args.args[0].name == "bridge"
        assert call_args.args[0].action == 1

    def test_control_service_stop(self):
        """ControlService action=2 (Stop) → 成功"""
        self.mock_stub.ControlService.return_value = MagicMock(ok=True, message="bridge 動作成功")
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.control_service("bridge", "stop")
        assert ok is True
        call_args = self.mock_stub.ControlService.call_args
        assert call_args.args[0].action == 2

    def test_control_service_restart(self):
        """ControlService action=3 (Restart) → 成功"""
        self.mock_stub.ControlService.return_value = MagicMock(ok=True, message="bridge 動作成功")
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.control_service("bridge", "restart")
        assert ok is True
        call_args = self.mock_stub.ControlService.call_args
        assert call_args.args[0].action == 3

    def test_control_service_unknown_action(self):
        """control_service('bridge', 'foo') → (False, 'unknown action') 不打 RPC"""
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.control_service("bridge", "frobnicate")
        assert ok is False
        assert "unknown action" in msg.lower() or "未知" in msg
        # 沒打 RPC
        self.mock_stub.ControlService.assert_not_called()

    # -------- set_kiosk_mode (siro-runtime 還沒實作) --------

    def test_set_kiosk_mode_unimplemented(self):
        """SetKioskMode 還沒實作 → siro-runtime 回 UNIMPLEMENTED"""
        import grpc
        err = grpc.RpcError()
        err.code = MagicMock(return_value=grpc.StatusCode.UNIMPLEMENTED)
        err.details = MagicMock(return_value="set_kiosk_mode 還沒實作、Phase 4 會做")
        self.mock_stub.SetKioskMode.side_effect = err
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        ok, msg = client.set_kiosk_mode(True)
        assert ok is False
        assert "UNIMPLEMENTED" in msg

    # -------- health --------

    def test_health_success(self):
        """Health RPC 回正常 → healthy=True + version"""
        self.mock_stub.Health.return_value = MagicMock(healthy=True, version="0.1.0", uptime_seconds=42, issues=[])
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        h = client.health()
        assert h["healthy"] is True
        assert h["version"] == "0.1.0"
        assert h["uptime_seconds"] == 42

    def test_health_rpc_error(self):
        """Health RPC 失敗 → healthy=False + reason"""
        import grpc
        err = grpc.RpcError()
        err.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        err.details = MagicMock(return_value="down")
        self.mock_stub.Health.side_effect = err
        client = RuntimeClient(enabled=True, timeout_sec=0.5)

        h = client.health()
        assert h["healthy"] is False
        assert "rpc_error" in h["reason"]

    # -------- close --------

    def test_close_releases_channel(self):
        """close() 會把 channel 關掉、stub 清成 None"""
        self.mock_stub.Health.return_value = MagicMock(healthy=True)
        client = RuntimeClient(enabled=True, timeout_sec=0.5)
        client.is_connected()  # 觸發 channel/stub 建立
        assert client._channel is not None

        client.close()
        self.mock_channel.close.assert_called_once()
        assert client._stub is None

    # -------- 初始化時降級：grpcio 沒裝 --------

    def test_enabled_falls_back_when_grpc_unavailable(self, monkeypatch):
        """grpcio ImportError 時 enabled 自動降級成 False"""
        import bridge.runtime_client as rc
        # 模擬 grpc = None 的狀態（grpcio 沒裝）
        with patch.object(rc, "_GRPC_AVAILABLE", False):
            client = RuntimeClient(enabled=True, timeout_sec=0.5)
            # 應該自動降級
            assert client.enabled is False

