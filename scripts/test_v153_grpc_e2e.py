"""
scripts/test_v153_grpc_e2e.py - 端到端測 v1.5.3 gRPC 整合

不靠真實 LLM、mock 掉 streaming client 的 _call_api_collect
但 agent loop 是真的、gRPC client 是真的、os-runtime 是真的
跑 list_dir 透過 gRPC 到 siro-runtime、回結果

Usage:
    1. 啟動 os-runtime: ./target/debug/siro-runtime.exe --auto-start=false
    2. python scripts/test_v153_grpc_e2e.py
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 確保 siro_pb2 stubs 找得到
sys.path.insert(0, str(REPO / "bridge" / "grpc_client" / "generated"))


def mock_call_api_collect_factory():
    """建一個 mock LLM: 第 1 輪 tool_use(list_dir)、第 2 輪 final text"""
    responses = [
        # iteration 1: LLM 說「給 list_dir 看一下」
        {
            "content": [
                {"type": "text", "text": "我先看看 sandbox。\n"},
                {"type": "tool_use", "id": "tu_1", "name": "list_dir", "input": {"path": "."}},
            ],
            "stop_reason": "tool_use",
        },
        # iteration 2: LLM 拿到 tool_result 後回 final
        {
            "content": [
                {"type": "text", "text": "sandbox 裡有 README.md 跟 hello.txt。"},
            ],
            "stop_reason": "end_turn",
        },
    ]
    iter_resp = iter(responses)
    async def _mock(*, messages, system_prompt=None, tools=None, **kw):
        try:
            return next(iter_resp)
        except StopIteration:
            return {"content": [{"type": "text", "text": "(no more)"}], "stop_reason": "end_turn"}
    return _mock


async def main():
    # 確認 os-runtime 連得到
    print("[1] 連 os-runtime gRPC...")
    from bridge.tools.os_runtime_client import get_os_runtime_client
    client = get_os_runtime_client()
    addr = client.address
    print(f"    address = {addr}")
    try:
        # 先建一個 dummy 檔、list_dir 會看到
        import os
        sandbox = Path(os.environ.get("SIRO_SANDBOX_DIR", str(Path.home() / "siro-sandbox")))
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "README.md").write_text("# SIRO sandbox")
        (sandbox / "hello.txt").write_text("hi")
        print(f"    setup: 在 {sandbox} 建了 README.md + hello.txt")
    except Exception as e:
        print(f"    setup failed: {e}")

    # 直接呼叫 gRPC list_dir
    print("\n[2] 直接呼叫 gRPC list_dir ...")
    result = client.list_directory(path=".", user_id="e2e_test")
    print(f"    result = {result}")
    if not result.get("ok"):
        print(f"    ERROR: {result.get('error')}")
        return
    print(f"    entries = {result.get('entries')}")
    print(f"    count = {result.get('count')}")

    # 跑 agent loop（mock LLM、用真的 gRPC）
    print("\n[3] 跑 agent loop (mock LLM + 真 gRPC)...")
    from bridge.minimax_streaming_client import MiniMaxStreamingClient
    sclient = MiniMaxStreamingClient()
    # 確保 is_available 回 True（測試用 mock LLM、不靠真 LLM）
    sclient.base_url = "https://mock.example.com"
    sclient.model = "mock-model"
    sclient.api_key = "mock-key"

    # 建一個假的 executor、跟 agent_loop 一樣 dispatch tool
    from bridge.tools import execute_tool_call

    async def executor(tool_name, tool_args, ctx):
        return await execute_tool_call(tool_name, tool_args, ctx)

    mock = mock_call_api_collect_factory()
    with patch.object(sclient, "_call_api_collect", side_effect=mock):
        result = await sclient.run_agent_loop(
            user_message="看 sandbox 內容",
            system_prompt="你是 SIRO",
            tools=[],
            executor=executor,
            max_iterations=3,
        )

    print(f"    finish_reason = {result.finish_reason}")
    print(f"    iterations = {result.iterations}")
    print(f"    text = {result.text}")
    print(f"    tool_calls = {[(tc.tool_name, tc.result.get('ok')) for tc in result.tool_calls]}")

    # 確認 tool_use 真的走過 gRPC
    if result.tool_calls:
        for tc in result.tool_calls:
            if tc.tool_name == "list_dir":
                entries = tc.result.get("entries", [])
                print(f"\n    [OK] gRPC list_dir 成功、entries: {entries}")
                if "README.md" in str(entries) and "hello.txt" in str(entries):
                    print(f"    [OK] 兩個檔案都看到了、整個 v1.5.3 gRPC path work!")
                else:
                    print(f"    [WARN] 沒看到預期檔案（可能 sandbox 不對）")

    print("\n[done]")


asyncio.run(main())
