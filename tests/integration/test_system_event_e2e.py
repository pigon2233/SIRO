"""
tests/integration/test_system_event_e2e.py

End-to-end integration test: siro-runtime -> bridge -> Unity WS

驗證場景：
1. 啟動 siro-runtime + bridge（用 port 8005 避免 orphan 衝突）
2. WS client 連上 bridge
3. 用 gRPC 觸發 service.stopped event
4. 驗證 WS 收到 {"type": "system_event", "event_type": "service.stopped", ...}
5. 額外：siro-runtime 重啟後 bridge 應該自動 reconnect（驗 consumer retry loop）

注意：
- 這是 integration test、需要真的 spawn subprocess
- 需要 hermes 二進制在路徑上
- 預期執行時間 ~30 秒（每次 spawn 5s+ + 事件傳遞）
- 標記 @pytest.mark.integration 讓預設 pytest 不跑（要 -m integration 才跑）
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# 跳過預設 pytest run（要 -m integration 才跑）
pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SIRO_RUNTIME = REPO_ROOT / "os-runtime" / "target" / "debug" / "siro-runtime.exe"
BRIDGE_PORT = "8005"  # 避免 8001 orphan
RUNTIME_PORT = "50055"  # 避免 50051 siro-runtime 默認 port
LOG_DIR = REPO_ROOT / "tests" / "integration" / ".logs"
LOG_DIR.mkdir(exist_ok=True)


def _wait_for_port(host: str, port: str, timeout: float = 15.0) -> bool:
    """等 TCP port 開啟（用 Python stdlib、避免額外依賴）"""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


def _wait_for_health(port: str, timeout: float = 20.0) -> bool:
    """等 bridge /health 回（ok 或 degraded 都算、只要有回應就好）"""
    import urllib.request
    import json
    deadline = time.time() + timeout
    url = "http://127.0.0.1:{0}/health".format(port)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                data = json.loads(r.read())
                if "status" in data:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def siro_runtime():
    """啟動 siro-runtime（module scope、整個 test module 共用一個）"""
    if not SIRO_RUNTIME.exists():
        pytest.skip("siro-runtime not built: {0}（先跑 cargo build）".format(SIRO_RUNTIME))
    env = os.environ.copy()
    # log 寫到檔案、不是 PIPE（4KB block 問題）
    log_handle = open(LOG_DIR / "siro-runtime.log", "wb")
    proc = subprocess.Popen(
        [str(SIRO_RUNTIME), "--auto-start=false", "--grpc-addr=0.0.0.0:{0}".format(RUNTIME_PORT)],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        if not _wait_for_port("127.0.0.1", RUNTIME_PORT, timeout=15):
            proc.terminate()
            pytest.fail("siro-runtime 沒起來（{0} timeout）".format(RUNTIME_PORT))
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_handle.close()


@pytest.fixture(scope="module")
def bridge(siro_runtime):
    """啟動 bridge（module scope、需要 siro_runtime 先起）"""
    env = os.environ.copy()
    env["BRIDGE_PORT"] = BRIDGE_PORT
    env["SIRO_RUNTIME_ENABLED"] = "true"
    env["SIRO_RUNTIME_ADDR"] = "127.0.0.1:{0}".format(RUNTIME_PORT)  # 重要：bridge runtime_client 預設是 50051
    env["PYTHONPATH"] = str(REPO_ROOT)
    log_handle = open(LOG_DIR / "bridge.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "bridge.main"],
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        if not _wait_for_health(BRIDGE_PORT, timeout=25):
            proc.terminate()
            pytest.fail("bridge 沒起來（{0} timeout）".format(BRIDGE_PORT))
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_handle.close()


@pytest.mark.asyncio
async def test_service_stopped_event_reaches_ws(siro_runtime, bridge):
    """service.stopped event 從 siro-runtime -> bridge -> Unity WS 的端到端測試"""
    import asyncio
    import json
    import sys
    sys.path.insert(0, str(REPO_ROOT / "bridge" / "grpc_client" / "generated"))
    import grpc
    import grpc.aio
    import siro_pb2
    import siro_pb2_grpc
    import websockets

    async with websockets.connect("ws://127.0.0.1:{0}/ws".format(BRIDGE_PORT)) as ws:
        # 給 consumer thread + 第一次 subscribe 至少 6 秒
        # （含 retry loop 第一次連線時間）
        await asyncio.sleep(6)

        # 觸發 hermes stop（auto_restart=true 會自動 restart -> 可能兩個 events）
        async with grpc.aio.insecure_channel("127.0.0.1:{0}".format(RUNTIME_PORT)) as ch:
            stub = siro_pb2_grpc.SiroRuntimeStub(ch)
            await stub.ControlService(
                siro_pb2.ServiceControl(name="hermes", action=2)  # 2 = Stop
            )

        # 等 8 秒內收到 system_event
        deadline = asyncio.get_event_loop().time() + 8.0
        events_received = []
        while len(events_received) < 2 and asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                if data.get("type") == "system_event":
                    events_received.append(data)
            except asyncio.TimeoutError:
                break

        assert len(events_received) >= 1, (
            "沒收到 system_event（hermes stop 應該觸發 service.stopped）\n"
            "看 tests/integration/.logs/bridge.log debug"
        )

        event_types = [e["event_type"] for e in events_received]
        assert "service.stopped" in event_types, (
            "預期收到 service.stopped，實際收到 {0}".format(event_types)
        )


@pytest.mark.asyncio
async def test_consumer_thread_survives_siro_runtime_restart(siro_runtime, bridge):
    """測穩定性：siro-runtime 重啟後 consumer 應該自動 reconnect

    模擬情境：siro-runtime 當機 -> 重啟 -> bridge 應該自動看到新 events
    """
    import asyncio
    import json
    import sys
    sys.path.insert(0, str(REPO_ROOT / "bridge" / "grpc_client" / "generated"))
    import grpc
    import grpc.aio
    import siro_pb2
    import siro_pb2_grpc
    import websockets

    async with websockets.connect("ws://127.0.0.1:{0}/ws".format(BRIDGE_PORT)) as ws:
        await asyncio.sleep(6)  # consumer ready

        # 第一次觸發
        async with grpc.aio.insecure_channel("127.0.0.1:{0}".format(RUNTIME_PORT)) as ch:
            stub = siro_pb2_grpc.SiroRuntimeStub(ch)
            await stub.ControlService(siro_pb2.ServiceControl(name="hermes", action=2))

        # 收第一個 event
        first_event = None
        try:
            async with asyncio.timeout(8.0):
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("type") == "system_event":
                        first_event = data
                        break
        except asyncio.TimeoutError:
            pass
        assert first_event is not None, "第一次事件沒收到"

        # 殺掉 siro-runtime
        siro_runtime.terminate()
        siro_runtime.wait(timeout=5)

        # 等 6 秒讓 bridge 看到 siro-runtime 死 + consumer 進入 retry
        await asyncio.sleep(6)

        # 重新啟動 siro-runtime
        env = os.environ.copy()
        new_log = open(LOG_DIR / "siro-runtime-restart.log", "wb")
        new_proc = subprocess.Popen(
            [str(SIRO_RUNTIME), "--auto-start=false", "--grpc-addr=0.0.0.0:{0}".format(RUNTIME_PORT)],
            stdout=new_log,
            stderr=subprocess.STDOUT,
            env=env,
        )

        try:
            if not _wait_for_port("127.0.0.1", RUNTIME_PORT, timeout=15):
                pytest.fail("siro-runtime 重啟失敗")

            # 給 bridge consumer 8 秒 retry（retry 間隔 5s + connect time）
            await asyncio.sleep(8)

            # 觸發第二次 event
            async with grpc.aio.insecure_channel("127.0.0.1:{0}".format(RUNTIME_PORT)) as ch:
                stub = siro_pb2_grpc.SiroRuntimeStub(ch)
                await stub.ControlService(siro_pb2.ServiceControl(name="hermes", action=2))

            # 收第二個 event
            second_event = None
            try:
                async with asyncio.timeout(10.0):
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if data.get("type") == "system_event":
                            second_event = data
                            break
            except asyncio.TimeoutError:
                pass
            assert second_event is not None, (
                "siro-runtime 重啟後、bridge 沒 reconnect 收到第二個 event（consumer retry 沒生效）\n"
                "看 tests/integration/.logs/bridge.log debug"
            )
        finally:
            new_proc.terminate()
            try:
                new_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                new_proc.kill()
            new_log.close()
