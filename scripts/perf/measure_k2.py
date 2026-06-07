"""
K2 量化測量：使用者輸入 → 角色回應的時間
目標：< 2 秒（本地 LLM）/ < 5 秒（雲端）

測量方式：
1. siro-runtime + bridge 跑起來
2. 用 httpx 打 /chat endpoint
3. 量從送出 request 到拿到回應的時間
4. 連跑 5 次取中位數
"""
import asyncio
import statistics
import sys
import time
sys.path.insert(0, "c:/coconut chennel/SIRO")
import httpx


async def measure_once(client: httpx.AsyncClient, message: str) -> float:
    """量一次 chat 的回應時間（秒）"""
    t0 = time.time()
    resp = await client.post(
        "http://127.0.0.1:8001/chat",
        json={
            "message": message,
            "user_id": "k2_perf",
            "session_id": None,
            "personality": "default",
        },
        timeout=30.0,
    )
    elapsed = time.time() - t0
    resp.raise_for_status()
    return elapsed


async def main():
    print("=== K2 Performance Test ===")
    print("目標：使用者輸入 → 角色回應 < 2 秒（本地 LLM）")
    print()

    messages = [
        "你好",
        "今天天氣如何？",
        "你可以幫我寫一個 hello world 嗎？",
        "你最喜歡什麼顏色？",
        "講個笑話給我聽",
    ]

    async with httpx.AsyncClient() as client:
        # 健康檢查
        try:
            r = await client.get("http://127.0.0.1:8001/health", timeout=5.0)
            r.raise_for_status()
            print(f"bridge health: {r.json()}")
        except Exception as e:
            print(f"ERROR: bridge 沒回應 ({e})")
            print("請先啟動：siro-runtime + bridge.main")
            return

        # 暖機
        print("\n暖機 1 次...")
        try:
            t = await measure_once(client, "暖機測試")
            print(f"  暖機: {t*1000:.0f}ms")
        except Exception as e:
            print(f"  暖機失敗: {e}")
            return

        # 量 5 次
        print("\n量測 5 次：")
        times = []
        for msg in messages:
            try:
                t = await measure_once(client, msg)
                times.append(t)
                print(f"  '{msg[:20]}': {t*1000:.0f}ms")
            except Exception as e:
                print(f"  '{msg[:20]}': ERROR {e}")

        if times:
            print(f"\n統計：")
            print(f"  min:    {min(times)*1000:.0f}ms")
            print(f"  median: {statistics.median(times)*1000:.0f}ms")
            print(f"  mean:   {statistics.mean(times)*1000:.0f}ms")
            print(f"  max:    {max(times)*1000:.0f}ms")
            median = statistics.median(times)
            if median < 2.0:
                print(f"\n[OK] K2 達標（< 2s）")
            elif median < 5.0:
                print(f"\n[WARN] K2 未達 2s 但 < 5s（雲端 LLM 範圍）")
            else:
                print(f"\n[FAIL] K2 未達標（> 5s）")


asyncio.run(main())
