"""
bridge/runtime_client.py - Layer 3 (siro-runtime) 的 gRPC client

v0.3.0 實作：實際 gRPC client 連 siro-runtime
- 用 grpc_tools.protoc 從 os-runtime/proto/siro.proto 生成 Python 程式碼
- 介面（RuntimeClient class 的 method）保持向後相容
- 沒裝 grpcio 或 siro-runtime 沒跑時，優雅降級成 no-op（Phase 1.5 風格）

設計重點：
- Lazy import grpc：模組 load 時不強制需要 grpcio（不裝也能 import 整個 bridge）
- sys.path 處理：grpc_tools 生成的 siro_pb2_grpc.py 用 `import siro_pb2`
  （絕對 import），需要在 import 前把 generated/ 加進 sys.path
- Connection caching：同一個 client 物件共用 channel
- timeout：每次 gRPC call 預設 2 秒（KPI K2 < 2 秒對齊）
- Fallback 設計：siro-runtime 沒起來 / 連不上 / call 失敗 → 降級成 "not connected"
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 把 bridge/grpc_client/generated 加到 sys.path
# 因為 grpc_tools.protoc 產生的 *_pb2_grpc.py 用 `import siro_pb2`（絕對 import）
# 不加這行會 ImportError
_GENERATED_DIR = Path(__file__).parent / "grpc_client" / "generated"
if str(_GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(_GENERATED_DIR))


# ============================================================
# Lazy import grpc（不裝 grpcio 也能 import 整個 bridge）
# ============================================================

try:
    import grpc  # type: ignore
    _GRPC_AVAILABLE = True
except ImportError:
    grpc = None  # type: ignore
    _GRPC_AVAILABLE = False
    logger.debug("grpcio 沒裝，RuntimeClient 走降級路徑")

try:
    # 這兩個只有在 enabled=True 時才會被真的用
    import siro_pb2  # type: ignore  # noqa: F401
    import siro_pb2_grpc  # type: ignore  # noqa: F401
    _PROTO_AVAILABLE = True
except ImportError:
    _PROTO_AVAILABLE = False
    logger.debug("siro_pb2 沒生成或 import 失敗，RuntimeClient 走降級路徑")


# ============================================================
# Stub 型別（向後相容 — Phase 1 程式碼可能 import 這個）
# ============================================================

class ServiceState:
    """對應 proto 的 ServiceState"""
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    UNKNOWN = "UNKNOWN"


# ============================================================
# Runtime Client
# ============================================================

DEFAULT_TIMEOUT_SEC = 2.0  # 對齊 KPI K2（使用者輸入到角色回應 < 2s）


class RuntimeClient:
    """
    Layer 3 (siro-runtime) 的 client。

    用法：
        client = RuntimeClient(enabled=True)
        if client.is_connected():
            print(client.health())
            print(client.get_status())

    沒裝 grpcio 或 siro-runtime 沒跑時，所有 method 都走降級路徑：
    - is_connected() → False
    - get_status() → {"connected": False, "services": {}}
    - restart_service() → (False, "Runtime not connected")
    """

    def __init__(
        self,
        address: Optional[str] = None,
        enabled: bool = False,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ):
        """
        Args:
            address: gRPC server address，預設 "127.0.0.1:50051"
            enabled: 是否啟用。False 時所有 method 都是 no-op
            timeout_sec: 每次 gRPC call 的 timeout（秒）
        """
        self.address = address or os.environ.get("SIRO_RUNTIME_ADDR", "127.0.0.1:50051")
        self.enabled = enabled
        self.timeout_sec = timeout_sec
        self._channel = None
        self._stub = None

        if self.enabled:
            if not _GRPC_AVAILABLE:
                logger.warning(
                    "RuntimeClient enabled 但 grpcio 沒裝，自動降級為 disabled。"
                    "請跑 `uv pip install grpcio grpcio-tools`。"
                )
                self.enabled = False
            elif not _PROTO_AVAILABLE:
                logger.warning(
                    "RuntimeClient enabled 但 siro_pb2 沒生成，自動降級為 disabled。"
                    "請跑 os-runtime/proto/ 的 codegen（見 os-runtime/README.md）。"
                )
                self.enabled = False
            else:
                logger.info(f"RuntimeClient enabled, target: {self.address}, timeout: {timeout_sec}s")
                # channel lazy 建立（第一次 call 才連線）

    def _ensure_stub(self):
        """Lazy 建立 channel + stub（第一次實際 call 才做）"""
        if self._stub is not None:
            return self._stub
        if not self.enabled:
            return None
        try:
            self._channel = grpc.insecure_channel(self.address)
            self._stub = siro_pb2_grpc.SiroRuntimeStub(self._channel)
            return self._stub
        except Exception as e:
            logger.warning(f"建立 gRPC channel 失敗: {e}")
            return None

    def is_connected(self) -> bool:
        """檢查 runtime 是否可達（用 Health RPC 探測，2s timeout）"""
        if not self.enabled:
            return False
        stub = self._ensure_stub()
        if stub is None:
            return False
        try:
            # Empty() 是 proto 的空訊息
            resp = stub.Health(siro_pb2.Empty(), timeout=self.timeout_sec)
            return bool(resp.healthy)
        except grpc.RpcError as e:
            logger.debug(f"Health RPC 失敗: {e.code().name}: {e.details()}")
            return False
        except Exception as e:
            logger.debug(f"Health RPC 未預期錯誤: {e}")
            return False

    def get_status(self) -> dict:
        """查詢所有服務狀態

        Returns:
            {
                "connected": bool,
                "services": {
                    "bridge": {
                        "status": "RUNNING" | "STOPPED" | "FAILED" | "STARTING" | "UNKNOWN",
                        "pid": int,
                        "uptime_seconds": int,
                        "memory_bytes": int,
                        "last_error": str,
                    },
                    ...
                }
            }
        """
        if not self.enabled:
            return {"connected": False, "services": {}, "reason": "disabled"}
        stub = self._ensure_stub()
        if stub is None:
            return {"connected": False, "services": {}, "reason": "no_stub"}
        try:
            resp = stub.GetStatus(siro_pb2.Empty(), timeout=self.timeout_sec)
            services = {}
            status_name_map = {
                0: ServiceState.UNKNOWN,
                1: ServiceState.RUNNING,
                2: ServiceState.STOPPED,
                3: ServiceState.FAILED,
                4: ServiceState.STARTING,
                5: ServiceState.STOPPING,
            }
            for name, state in resp.services.items():
                services[name] = {
                    "status": status_name_map.get(state.status, ServiceState.UNKNOWN),
                    "pid": state.pid,
                    "uptime_seconds": state.uptime_seconds,
                    "memory_bytes": state.memory_bytes,
                    "last_error": state.last_error,
                }
            return {"connected": True, "services": services}
        except grpc.RpcError as e:
            logger.debug(f"GetStatus RPC 失敗: {e.code().name}: {e.details()}")
            return {"connected": False, "services": {}, "reason": f"rpc_error:{e.code().name}"}
        except Exception as e:
            logger.warning(f"GetStatus 未預期錯誤: {e}")
            return {"connected": False, "services": {}, "reason": f"unexpected:{e}"}

    def get_hardware_info(self) -> dict:
        """查詢硬體資訊

        Returns:
            {
                "available": bool,
                "cpu": {"model": str, "cores": int, "threads": int, "frequency_ghz": float},
                "memory": {"total_bytes": int, "available_bytes": int},
                "gpu": [...],    # v0.4+ 實作
                "audio": [...],  # v0.4+ 實作
            }
        """
        if not self.enabled:
            return {"available": False, "reason": "disabled"}
        stub = self._ensure_stub()
        if stub is None:
            return {"available": False, "reason": "no_stub"}
        try:
            resp = stub.GetHardwareInfo(siro_pb2.Empty(), timeout=self.timeout_sec)
            result = {"available": True}
            if resp.cpu.model or resp.cpu.cores:
                result["cpu"] = {
                    "model": resp.cpu.model,
                    "cores": resp.cpu.cores,
                    "threads": resp.cpu.threads,
                    "frequency_ghz": resp.cpu.frequency_ghz,
                }
            if resp.memory.total_bytes or resp.memory.available_bytes:
                result["memory"] = {
                    "total_bytes": resp.memory.total_bytes,
                    "available_bytes": resp.memory.available_bytes,
                }
            # v0.4+ 才有 gpu / audio
            # proto 定義：gpu 是 single GpuInfo（不是 repeated）
            if resp.gpu and resp.gpu.model:
                result["gpu"] = {
                    "model": resp.gpu.model,
                    "vendor": resp.gpu.vendor,
                    "vram_bytes": resp.gpu.vram_bytes,
                    "driver_version": resp.gpu.driver_version,
                    "cuda_version": resp.gpu.cuda_version,
                }
            if resp.audio:
                result["audio"] = [
                    {
                        "name": a.name,
                        "device_type": a.device_type,
                        "is_default": a.is_default,
                    }
                    for a in resp.audio
                ]
            return result
        except grpc.RpcError as e:
            logger.debug(f"GetHardwareInfo RPC 失敗: {e.code().name}: {e.details()}")
            return {"available": False, "reason": f"rpc_error:{e.code().name}"}

    def restart_service(self, name: str) -> tuple[bool, str]:
        """重啟指定服務

        Returns:
            (success, message)
        """
        if not self.enabled:
            return False, "Runtime not connected (disabled)"
        stub = self._ensure_stub()
        if stub is None:
            return False, "Runtime not connected (no stub)"
        try:
            resp = stub.RestartService(
                siro_pb2.ServiceName(name=name),
                timeout=self.timeout_sec,
            )
            return bool(resp.ok), resp.message
        except grpc.RpcError as e:
            logger.warning(f"RestartService RPC 失敗: {e.code().name}: {e.details()}")
            return False, f"gRPC error: {e.code().name}: {e.details()}"
        except Exception as e:
            logger.warning(f"RestartService 未預期錯誤: {e}")
            return False, f"unexpected: {e}"

    def control_service(self, name: str, action: str) -> tuple[bool, str]:
        """啟動/停止/重啟服務

        Args:
            name: service name
            action: "start" | "stop" | "restart"

        Returns:
            (success, message)
        """
        if not self.enabled:
            return False, "Runtime not connected (disabled)"
        stub = self._ensure_stub()
        if stub is None:
            return False, "Runtime not connected (no stub)"
        # ServiceAction enum: 0=Unknown, 1=Start, 2=Stop, 3=Restart
        action_map = {"start": 1, "stop": 2, "restart": 3}
        action_int = action_map.get(action.lower())
        if action_int is None:
            return False, f"unknown action: {action}（只接受 start/stop/restart）"
        try:
            resp = stub.ControlService(
                siro_pb2.ServiceControl(name=name, action=action_int),
                timeout=self.timeout_sec,
            )
            return bool(resp.ok), resp.message
        except grpc.RpcError as e:
            logger.warning(f"ControlService RPC 失敗: {e.code().name}: {e.details()}")
            return False, f"gRPC error: {e.code().name}: {e.details()}"

    def set_kiosk_mode(self, enable: bool) -> tuple[bool, str]:
        """切換 kiosk 模式（v0.3.0 還沒實作、siro-runtime 會回 unimplemented）"""
        if not self.enabled:
            return False, "Runtime not connected (disabled)"
        stub = self._ensure_stub()
        if stub is None:
            return False, "Runtime not connected (no stub)"
        try:
            resp = stub.SetKioskMode(
                siro_pb2.KioskRequest(enable=enable),
                timeout=self.timeout_sec,
            )
            return bool(resp.ok), resp.message
        except grpc.RpcError as e:
            # unimplemented 是預期的（Phase 4 才做）
            logger.debug(f"SetKioskMode RPC: {e.code().name}: {e.details()}")
            return False, f"gRPC: {e.code().name}: {e.details()}"

    def health(self) -> dict:
        """健康檢查

        Returns:
            {"healthy": bool, "version": str, "uptime_seconds": int, "issues": [...]}
        """
        if not self.enabled:
            return {"healthy": False, "reason": "disabled"}
        stub = self._ensure_stub()
        if stub is None:
            return {"healthy": False, "reason": "no_stub"}
        try:
            resp = stub.Health(siro_pb2.Empty(), timeout=self.timeout_sec)
            return {
                "healthy": bool(resp.healthy),
                "version": resp.version,
                "uptime_seconds": resp.uptime_seconds,
                "issues": list(resp.issues),
            }
        except grpc.RpcError as e:
            return {"healthy": False, "reason": f"rpc_error:{e.code().name}"}

    def close(self) -> None:
        """關閉連線"""
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception as e:
                logger.debug(f"channel.close() 失敗: {e}")
            self._channel = None
            self._stub = None


# ============================================================
# 全域 singleton（給 bridge 方便用）
# ============================================================

_runtime_client: Optional[RuntimeClient] = None


def get_runtime_client() -> RuntimeClient:
    """取得 RuntimeClient singleton

    預設行為（Phase 3）：
    - 如果 env SIRO_RUNTIME_ENABLED=true → enabled
    - 否則 → disabled（向後相容 Phase 1.5 行為）
    """
    global _runtime_client
    if _runtime_client is None:
        enabled = os.environ.get("SIRO_RUNTIME_ENABLED", "false").lower() == "true"
        _runtime_client = RuntimeClient(enabled=enabled)
    return _runtime_client


# ============================================================
# 測試
# ============================================================

if __name__ == "__main__":
    # 直接跑這個檔：先測 disabled 模式，再測 enabled 模式（如果有 siro-runtime 在跑）
    import json

    print("=== 測試 1: disabled 模式 ===")
    client = RuntimeClient(enabled=False)
    assert not client.is_connected()
    assert client.get_status()["connected"] is False
    assert client.health()["healthy"] is False
    ok, msg = client.restart_service("bridge")
    assert not ok and "not connected" in msg.lower()
    print("✓ disabled 模式降級正常")

    print("\n=== 測試 2: enabled 模式（需要 siro-runtime 在 127.0.0.1:50051） ===")
    client = RuntimeClient(enabled=True)
    if client.is_connected():
        print("✓ 連到 siro-runtime")
        print("health:", json.dumps(client.health(), indent=2))
        print("get_status:", json.dumps(client.get_status(), indent=2, ensure_ascii=False))
        print("get_hardware_info:", json.dumps(client.get_hardware_info(), indent=2))
    else:
        print("✗ 連不上 siro-runtime（預期如果沒跑的話）")
    client.close()
