"""
scripts/test_siro_full.py — SIRO 端到端功能測試

跑全部 7 個測試、報 pass/fail summary。
不需要任何參數、直接執行。

    PYTHONIOENCODING=utf-8 python scripts/test_siro_full.py
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== Config ====================
BRIDGE = os.environ.get("BRIDGE", "http://127.0.0.1:8001")
RUNTIME = os.environ.get("RUNTIME", "127.0.0.1:50051")
PYTHON = r"C:\Users\jason\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
TEST_USER = "test-user-001"
TEST_PERSONA = "siro-default"


# ==================== Test framework ====================
@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""
    duration_ms: int = 0


results: list[TestResult] = []


def record(name: str, passed: bool, detail: str = "", duration_ms: int = 0):
    results.append(TestResult(name, passed, detail, duration_ms))
    status = "✅" if passed else "❌"
    print(f"  {status} {name} ({duration_ms}ms) {detail}")


def section(title: str):
    print(f"\n━━━ {title} ━━━")


def http_get(url: str, timeout: float = 5.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def http_post_json(url: str, body: dict, timeout: float = 60.0,
                   headers: Optional[dict] = None) -> tuple[int, dict | str]:
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=h, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body_text = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(body_text)
            except json.JSONDecodeError:
                return r.status, body_text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


# ==================== Test 1: bridge /health ====================
def test_1_bridge_health():
    t0 = time.time()
    code, body = http_get(f"{BRIDGE}/health", timeout=3)
    elapsed = int((time.time() - t0) * 1000)
    if code == 200 and isinstance(body, dict) and body.get("status") in ("ok", "degraded"):
        record("bridge /health", True,
               f"status={body.get('status')} version={body.get('bridge_version')}", elapsed)
    else:
        record("bridge /health", False, f"code={code} body={body}", elapsed)


# ==================== Test 4: bridge /chat HTTP ====================
def test_4_bridge_chat():
    t0 = time.time()
    code, body = http_post_json(
        f"{BRIDGE}/chat",
        {"message": "hi 1 句話就好", "user_id": TEST_USER, "personality": TEST_PERSONA},
        timeout=180,  # CPU fp32 slow、給 3 分鐘
    )
    elapsed = int((time.time() - t0) * 1000)
    if code == 200 and isinstance(body, dict) and body.get("text"):
        record("bridge /chat HTTP", True,
               f"text={body.get('text','')[:60]!r} emotion={body.get('emotion')}", elapsed)
    else:
        record("bridge /chat HTTP", False, f"code={code} body={str(body)[:200]}", elapsed)


# ==================== Test 5: bridge /ws WebSocket ====================
async def test_5_bridge_ws():
    import websockets
    t0 = time.time()
    try:
        uri = f"ws://127.0.0.1:8001/ws"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "chat", "message": "hi 用一句話自我介紹",
                "user_id": TEST_USER, "personality": TEST_PERSONA,
            }))
            seen = []
            text_chunks = []
            start = time.time()
            # v1.5.3：CPU fp32 TTFT 36s+、max_tokens 1024 decode 又 30s+
            # 整個對話 90s 還不夠、給 180s
            while time.time() - start < 180:
                try:
                    r = await asyncio.wait_for(ws.recv(), timeout=60)
                    obj = json.loads(r)
                    seen.append(obj.get("type"))
                    if obj.get("type") == "delta":
                        text_chunks.append(obj.get("text", ""))
                    elif obj.get("type") == "response":
                        full_text = obj.get("text", "")
                        elapsed = int((time.time() - t0) * 1000)
                        ok = (
                            len(text_chunks) > 0
                            and full_text
                            and obj.get("emotion")
                        )
                        record("bridge /ws WebSocket", ok,
                               f"deltas={len(text_chunks)} emotion={obj.get('emotion')} "
                               f"text={full_text[:60]!r}",
                               elapsed)
                        return
                except asyncio.TimeoutError:
                    break
            record("bridge /ws WebSocket", False,
                   f"no response after {int((time.time()-t0)*1000)}ms, types={seen}", 0)
    except Exception as e:
        record("bridge /ws WebSocket", False, f"exception: {e}", 0)


# ==================== Test 6: WS multi-turn conversation ====================
async def test_6_multi_turn():
    """第二輪訊息應該引用到第一輪的 history

    v1.5.3 改：每輪一個 connection、避免 websockets 的 connection state race
    """
    import websockets
    t0 = time.time()
    user_id = "multi-turn-user"

    # Round 1
    try:
        async with websockets.connect("ws://127.0.0.1:8001/ws") as ws:
            await ws.send(json.dumps({
                "type": "chat", "message": "我最喜歡的水果是蘋果",
                "user_id": user_id, "personality": TEST_PERSONA,
            }))
            r1_text = None
            start = time.time()
            while time.time() - start < 180 and r1_text is None:
                r = await asyncio.wait_for(ws.recv(), timeout=60)
                obj = json.loads(r)
                if obj.get("type") == "response":
                    r1_text = obj.get("text", "")
        if r1_text is None:
            record("WS multi-turn (history)", False, "round 1 沒回應", 0)
            return
    except Exception as e:
        record("WS multi-turn (history)", False, f"round 1 exception: {e}", 0)
        return

    # 給 bridge 5s 消化上一個 connection（避免 race）
    await asyncio.sleep(5)

    # Round 2 — 用同 user_id（bridge 用 user_id 算 session_id）
    try:
        async with websockets.connect("ws://127.0.0.1:8001/ws") as ws:
            await ws.send(json.dumps({
                "type": "chat", "message": "我剛剛說我喜歡什麼水果?",
                "user_id": user_id, "personality": TEST_PERSONA,
            }))
            r2_text = None
            r2_emotion = None
            start = time.time()
            while time.time() - start < 180 and r2_text is None:
                r = await asyncio.wait_for(ws.recv(), timeout=60)
                obj = json.loads(r)
                if obj.get("type") == "response":
                    r2_text = obj.get("text", "")
                    r2_emotion = obj.get("emotion", "")

        elapsed = int((time.time() - t0) * 1000)
        if r2_text and "蘋果" in r2_text:
            record("WS multi-turn (history)", True,
                   f"round2 記得 '蘋果': {r2_text[:60]!r} emotion={r2_emotion}", elapsed)
        elif r2_text:
            record("WS multi-turn (history)", False,
                   f"round2 沒提到 '蘋果': {r2_text[:60]!r}", elapsed)
        else:
            record("WS multi-turn (history)", False, "round 2 沒回應", elapsed)
    except Exception as e:
        record("WS multi-turn (history)", False, f"round 2 exception: {e}", 0)


# ==================== Test 7: tools available ====================
def test_7_tools():
    t0 = time.time()
    code, body = http_get(f"{BRIDGE}/siro/tools", timeout=3)
    elapsed = int((time.time() - t0) * 1000)
    if code == 200 and isinstance(body, dict):
        tools = body.get("tools", [])
        count = body.get("count", len(tools))
        record("bridge /siro/tools", count > 0,
               f"count={count}", elapsed)
    else:
        record("bridge /siro/tools", False, f"code={code} body={str(body)[:200]}", elapsed)


# ==================== Main ====================
async def main():
    print("=" * 60)
    print("SIRO 端到端功能測試")
    print("=" * 60)
    print(f"  bridge      : {BRIDGE}")
    print(f"  persona     : {TEST_PERSONA}")
    print(f"  user        : {TEST_USER}")

    section("1. bridge HTTP")
    test_1_bridge_health()
    test_4_bridge_chat()
    test_7_tools()

    section("3. bridge WebSocket")
    await test_5_bridge_ws()

    section("4. session history")
    await test_6_multi_turn()

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    failed = total - passed
    print(f"結果: {passed}/{total} pass, {failed} fail")
    if failed:
        print("\n失敗的測試:")
        for r in results:
            if not r.passed:
                print(f"  ❌ {r.name}: {r.detail}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
