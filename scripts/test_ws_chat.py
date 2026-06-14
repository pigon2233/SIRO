"""
scripts/test_ws_chat.py - quick test of bridge WS with agent mode
"""
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("need websockets: pip install websockets")
    sys.exit(1)


async def test():
    uri = "ws://127.0.0.1:8001/ws"
    async with websockets.connect(uri) as ws:
        msg = {
            "type": "chat",
            "message": "列出 sandbox 內容",
            "user_id": "test",
            "personality": "default",
        }
        print(f"[send] {msg}")
        await ws.send(json.dumps(msg))

        for i in range(50):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
            except asyncio.TimeoutError:
                print("[timeout]")
                break

            data = json.loads(raw)
            t = data.get("type")
            if t == "response":
                print(f"\n[final response] {data.get('text')}")
                print(f"  emotion={data.get('emotion')} intensity={data.get('intensity')}")
                break
            elif t == "tool_action":
                print(f"[tool_action] {data.get('tool')}({data.get('args')}) ok={data.get('ok')} ({data.get('duration_ms')}ms)")
            elif t == "delta":
                sys.stdout.write(data.get("text", ""))
                sys.stdout.flush()
            elif t == "error":
                print(f"[error] {data}")
                break
            else:
                print(f"[{t}] {data}")


asyncio.run(test())
