"""
K8 量化測量：subsystem 死掉 → Mao 切 fallback 表情的時間
目標：< 3 秒

測量方式：
1. siro-runtime + bridge 跑起來
2. 用 WS 連 bridge、開始收 system_event
3. 用 gRPC kill bridge service
4. 量從 kill 到收到 service.restarted event 的時間

環境變數：
- BRIDGE_PORT（預設 8001）：bridge WS port
- SIRO_RUNTIME_PORT（預設 50051）：siro-runtime gRPC port
"""
import asyncio
import json
import os
import sys
import time
sys.path.insert(0, "c:/coconut chennel/SIRO/bridge/grpc_client/generated")
sys.path.insert(0, "c:/coconut chennel/SIRO")

import grpc
import siro_pb2
import siro_pb2_grpc
import websockets


async def collect_first_event(ws, timeout_sec):
    """從 WS 收第一個 system_event、回傳 latency"""
    t0 = time.time()
    try:
        async with asyncio.timeout(timeout_sec):
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("type") == "system_event":
                    return time.time() - t0, data
    except asyncio.TimeoutError:
        return None, None


async def main():
    print("=== K8 Performance Test ===")
    print("目標：subsystem 死掉 → Mao 切 fallback 表情 < 3 秒")
    print()
    print("（注意：Mao 切表情需要 Unity 接收到 system_event + 做動畫。")
    print(" 這裡只量「service.restarted event 到達 bridge WS」的時間。")
    print(" Unity 端動畫延遲另計。）")
    print()

    # 連 bridge WS
    bridge_port = os.environ.get("BRIDGE_PORT", "8001")
    runtime_port = os.environ.get("SIRO_RUNTIME_PORT", "50051")
    print(f"[step 1] 連 bridge WS ws://127.0.0.1:{bridge_port}/ws ...")
    async with websockets.connect(f"ws://127.0.0.1:{bridge_port}/ws") as ws:
        print("  ws connected")

        # 等 2 秒讓 consumer 完全 ready
        print("[step 2] 等 2s 讓 system_event consumer 就緒...")
        await asyncio.sleep(2)

        # 觸發 kill bridge service
        print("[step 3] 用 gRPC 觸發 kill bridge（ControlService stop）...")
        t0 = time.time()
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime_port}") as ch:
            stub = siro_pb2_grpc.SiroRuntimeStub(ch)
            # 用 hermes 來測（auto-restart 會觸發 event；bridge 真的 kill 會害自己掛掉）
            await stub.ControlService(
                siro_pb2.ServiceControl(name="hermes", action=2)  # 2 = Stop
            )
            print(f"  stop hermes sent at t={time.time()-t0:.3f}s")

        # 量到 service.restarted event 的時間
        print("[step 4] 等 service.restarted event（5s timeout）...")
        latency, event = await collect_first_event(ws, 5.0)

        if event:
            print(f"  收到 event at t={latency:.3f}s: {event['event_type']} {event['data']}")
            if latency < 3.0:
                print(f"\n[OK] K8 達標（{latency:.3f}s < 3s）")
                return 0
            else:
                print(f"\n[WARN] K8 略超 3s（{latency:.3f}s）")
                return 1
        else:
            print(f"  5s timeout、沒收到 service.restarted")
            print(f"\n[FAIL] K8 未達標（> 5s）")
            return 2


import sys
sys.exit(asyncio.run(main()))
