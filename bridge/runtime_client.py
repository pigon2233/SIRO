"""
bridge/runtime_client.py - Layer 3 (siro-runtime) 的 gRPC client

這個檔案是 v0 階段的 stub，定義介面但不實際連線。
Phase 3 開始實作 siro-runtime 時，會做：
  1. 用 grpc_tools.protoc 從 os-runtime/proto/siro.proto 生成 Python 程式碼
  2. 改寫本檔的底層實作為真正的 gRPC client
  3. 介面（RuntimeClient class 的 method）保持不變

為什麼先做 stub：
- 介面契約先定好 → Phase 1 的程式碼可以呼叫
- 避免 Phase 1 依賴 gRPC 套件（等真的要連線再裝）
- proto 變更時可以快速調整介面

設計：fallback 設計 — 沒有 runtime 時仍能運作
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# Stub 型別（之後會從 proto 生成）
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

class RuntimeClient:
    """
    Layer 3 (siro-runtime) 的 client。

    v0 stub：純本地，記錄呼叫但不打網路
    v1 實作：gRPC client 連 siro-runtime
    """

    def __init__(self, address: Optional[str] = None, enabled: bool = False):
        """
        Args:
            address: gRPC server address，預設 "127.0.0.1:50051"
            enabled: 是否啟用。False 時所有 method 都是 no-op
        """
        self.address = address or os.environ.get("SIRO_RUNTIME_ADDR", "127.0.0.1:50051")
        self.enabled = enabled
        self._stub = None  # 之後放 generated gRPC stub

        if self.enabled:
            logger.info(f"RuntimeClient enabled, target: {self.address}")
            # v1 實作：
            # import grpc
            # channel = grpc.insecure_channel(self.address)
            # from bridge.grpc_client.generated import siro_pb2_grpc
            # self._stub = siro_pb2_grpc.SiroRuntimeStub(channel)
        else:
            logger.debug("RuntimeClient 為 stub 模式（不連線）")

    def is_connected(self) -> bool:
        """檢查 runtime 是否可達（v0 永遠 False）"""
        if not self.enabled or self._stub is None:
            return False
        # v1 實作：
        # try:
        #     self._stub.Health(Empty(), timeout=2)
        #     return True
        # except grpc.RpcError:
        #     return False
        return False

    def get_status(self) -> dict:
        """查詢所有服務狀態"""
        if not self.is_connected():
            return {"connected": False, "services": {}}
        # v1 實作呼叫 self._stub.GetStatus(Empty())
        return {"connected": False, "services": {}}

    def get_hardware_info(self) -> dict:
        """查詢硬體資訊"""
        if not self.is_connected():
            return {"available": False}
        # v1 實作呼叫 self._stub.GetHardwareInfo(Empty())
        return {"available": False}

    def restart_service(self, name: str) -> tuple[bool, str]:
        """重啟指定服務

        Returns:
            (success, message)
        """
        if not self.is_connected():
            return False, "Runtime not connected"
        # v1 實作：
        # response = self._stub.RestartService(ServiceName(name=name))
        # return response.ok, response.message
        return False, "Runtime not connected (v0 stub)"

    def set_kiosk_mode(self, enable: bool) -> tuple[bool, str]:
        """切換 kiosk 模式"""
        if not self.is_connected():
            return False, "Runtime not connected"
        return False, "Runtime not connected (v0 stub)"

    def health(self) -> dict:
        """健康檢查"""
        if not self.is_connected():
            return {"healthy": False, "reason": "not_connected"}
        return {"healthy": False, "reason": "v0 stub"}

    def close(self) -> None:
        """關閉連線（v0 no-op）"""
        if self._stub is not None:
            # v1 實作：self._channel.close()
            self._stub = None


# ============================================================
# 全域 singleton（給 bridge 方便用）
# ============================================================

_runtime_client: Optional[RuntimeClient] = None


def get_runtime_client() -> RuntimeClient:
    """取得 RuntimeClient singleton"""
    global _runtime_client
    if _runtime_client is None:
        # v0 預設 disabled，Phase 3 開始設為 enabled
        enabled = os.environ.get("SIRO_RUNTIME_ENABLED", "false").lower() == "true"
        _runtime_client = RuntimeClient(enabled=enabled)
    return _runtime_client


# ============================================================
# 測試
# ============================================================

if __name__ == "__main__":
    # v0 stub 模式測試
    client = RuntimeClient(enabled=False)
    print("is_connected:", client.is_connected())
    print("health:", client.health())
    print("get_status:", client.get_status())
    print("get_hardware_info:", client.get_hardware_info())
    print("restart_service:", client.restart_service("bridge"))
    print("set_kiosk_mode:", client.set_kiosk_mode(True))
    print("\nv0 stub 模式所有呼叫都是 no-op，預期一切正常")
