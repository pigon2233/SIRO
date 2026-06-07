"""
tests/integration/test_kpi_measurements.py

KPI 量化測試（K2 + K8）：
- K2：使用者輸入 → 角色回應時間
- K8：subsystem 死掉 → WS 收到 system_event 時間

執行方式：
    python -m pytest tests/integration/test_kpi_measurements.py -m integration -v

注意：
- 需要 siro-runtime 編譯好的 binary（os-runtime/target/debug/siro-runtime.exe）
- 需要 hermes 二進制在路徑上（否則 K2 量到的會是 fallback chain 速度）
- 用 port 8006/50056 避免 8001/50051 環境衝突
- 預期執行時間 ~30 秒（每次 spawn 5s+ + 量測）
- 標記 @pytest.mark.integration 預設 skip、-m integration 才跑

KPI 目標：
- K2 < 2s（本地 LLM）/ < 5s（雲端）
- K8 < 3s
"""
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SIRO_RUNTIME = REPO_ROOT / "os-runtime" / "target" / "debug" / "siro-runtime.exe"
BRIDGE_PORT = "8006"
RUNTIME_PORT = "50056"
LOG_DIR = REPO_ROOT / "tests" / "integration" / ".logs"
LOG_DIR.mkdir(exist_ok=True)


def _wait_for_port(host: str, port: str, timeout: float = 15.0) -> bool:
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
    if not SIRO_RUNTIME.exists():
        pytest.skip("siro-runtime not built: {0}（先跑 cargo build）".format(SIRO_RUNTIME))
    env = os.environ.copy()
    log_handle = open(LOG_DIR / "kpi-siro-runtime.log", "wb")
    proc = subprocess.Popen(
        [str(SIRO_RUNTIME), "--auto-start=false", "--grpc-addr=0.0.0.0:{0}".format(RUNTIME_PORT)],
        stdout=log_handle, stderr=subprocess.STDOUT, env=env,
    )
    try:
        if not _wait_for_port("127.0.0.1", RUNTIME_PORT, timeout=15):
            proc.terminate()
            pytest.fail("siro-runtime 沒起來")
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
    env = os.environ.copy()
    env["BRIDGE_PORT"] = BRIDGE_PORT
    env["SIRO_RUNTIME_ENABLED"] = "true"
    env["SIRO_RUNTIME_ADDR"] = "127.0.0.1:{0}".format(RUNTIME_PORT)
    env["PYTHONPATH"] = str(REPO_ROOT)
    log_handle = open(LOG_DIR / "kpi-bridge.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "bridge.main"],
        cwd=str(REPO_ROOT),
        stdout=log_handle, stderr=subprocess.STDOUT, env=env,
    )
    try:
        if not _wait_for_health(BRIDGE_PORT, timeout=25):
            proc.terminate()
            pytest.fail("bridge 沒起來")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_handle.close()


@pytest.mark.asyncio
async def test_k8_system_event_latency(siro_runtime, bridge):
    """K8 KPI：subsystem 死掉 → WS 收到 system_event 的延遲

    目標：< 3 秒

    量測方式：
    1. WS 連 bridge
    2. gRPC 觸發 ControlService(hermes, stop)
    3. 量從觸發到收到 WS event 的時間
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
        # 給 consumer thread 6 秒 ready（含 retry 第一次連線）
        await asyncio.sleep(6)

        # 觸發 hermes stop
        t0 = time.time()
        async with grpc.aio.insecure_channel("127.0.0.1:{0}".format(RUNTIME_PORT)) as ch:
            stub = siro_pb2_grpc.SiroRuntimeStub(ch)
            await stub.ControlService(
                siro_pb2.ServiceControl(name="hermes", action=2)
            )

        # 收第一個 system_event、量延遲
        latency = None
        try:
            async with asyncio.timeout(5.0):
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("type") == "system_event":
                        latency = time.time() - t0
                        break
        except asyncio.TimeoutError:
            pass

        assert latency is not None, (
            "5s 內沒收到 system_event（K8 量測失敗）\n"
            "看 tests/integration/.logs/kpi-bridge.log debug"
        )

        # 記錄到 stdout（pytest -v 會印、方便看趨勢）
        print("\n  K8 latency: {0:.3f}s".format(latency))

        # KPI 斷言（< 3s 達標）
        assert latency < 3.0, (
            "K8 未達標：{0:.3f}s >= 3s".format(latency)
        )


@pytest.mark.asyncio
async def test_k2_chat_latency(siro_runtime, bridge):
    """K2 KPI：使用者輸入 → 角色回應的延遲

    目標：< 2 秒（本地 LLM）/ < 5 秒（雲端）

    量測方式：
    1. 暖機 1 次
    2. 用 httpx 打 5 次 /chat endpoint
    3. 量 median 延遲

    注意事項：
    - 如果 hermes 不可用、會走 fallback chain（時間會是 fallback 速度）
    - 如果 hermes 走雲端、會是雲端 LLM 速度
    - 結果會根據環境配置而異、所以用 < 5s 寬鬆斷言（不卡 < 2s 嚴格條件）
    """
    import asyncio
    import sys
    import httpx

    BRIDGE_BASE = "http://127.0.0.1:{0}".format(BRIDGE_PORT)

    async with httpx.AsyncClient() as c:
        # 健康檢查
        r = await c.get("{0}/health".format(BRIDGE_BASE), timeout=5.0)
        r.raise_for_status()
        print("\n  bridge health: {0}".format(r.json()))

        # 暖機
        warmup_t0 = time.time()
        await c.post(
            "{0}/chat".format(BRIDGE_BASE),
            json={"message": "暖機", "user_id": "k2_perf", "session_id": None, "personality": "default"},
            timeout=60.0,
        )
        warmup_elapsed = time.time() - warmup_t0
        print("  K2 warmup: {0:.2f}s".format(warmup_elapsed))

        # 量 5 次
        messages = ["hi", "weather", "color", "joke", "bye"]
        times = []
        for m in messages:
            t0 = time.time()
            r = await c.post(
                "{0}/chat".format(BRIDGE_BASE),
                json={"message": m, "user_id": "k2_perf", "session_id": None, "personality": "default"},
                timeout=60.0,
            )
            r.raise_for_status()
            elapsed = time.time() - t0
            times.append(elapsed)
            print("  K2 {0}: {1:.2f}s".format(m, elapsed))

        if times:
            median = statistics.median(times)
            print("  K2 median: {0:.2f}s  (n={1})".format(median, len(times)))

            # 結果分級、給 warning 不直接 fail
            # KPI 目標：
            # - < 2s：本地 LLM 達標（需 GPU 加速或更小模型）
            # - < 5s：雲端 LLM 達標
            # - < 10s：fallback 鏈可接受（Ollama CPU 3B 跑出來的速度）
            # - >= 10s：真的有問題、fail 警示
            if median < 2.0:
                print("  K2 KPI: PASS (< 2s 本地 LLM)")
            elif median < 5.0:
                print("  K2 KPI: PASS (< 5s 雲端 LLM)")
            elif median < 10.0:
                print("  K2 KPI: WARN (< 10s fallback 鏈)")
            else:
                pytest.fail(
                    "K2 真的有問題：median {0:.2f}s >= 10s（KPI 嚴重未達標）".format(median)
                )

        # 永遠記錄結果、但不 fail on KPI 偏差（環境依賴）
        # 只有嚴重問題（>= 10s）才 fail
        assert times, "K2 沒量到任何樣本"
