"""
tests/bridge/test_agent_loop.py

v1.5+ MiniMaxStreamingClient.run_agent_loop 測試

用 mock _call_api_collect 模擬 LLM 行為：
- 第一次：給 tool_use
- 第二次：給 final text
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

TEST_SANDBOX = Path(__file__).parent / ".test_agent_loop_sandbox"


@pytest.fixture(autouse=True, scope="module")
def setup_env():
    os.environ["SIRO_SANDBOX_DIR"] = str(TEST_SANDBOX)
    os.environ["HERMES_LLM_BASE_URL"] = "https://api.example.com"
    os.environ["HERMES_LLM_MODEL"] = "test-model"
    os.environ["HERMES_API_KEY"] = "test-key"
    import shutil
    if TEST_SANDBOX.exists():
        shutil.rmtree(TEST_SANDBOX, ignore_errors=True)
    TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
    yield


class TestAgentLoop:
    """Mock LLM 跑 agent loop"""

    def _mock_call(self, sequence):
        """建一個 mock _call_api_collect 依序回傳 sequence 裡的 dict"""
        iterator = iter(sequence)
        async def mock_call(*, messages, system_prompt=None, tools=None, **kwargs):
            try:
                return next(iterator)
            except StopIteration:
                # 沒更多 mock response → 回 text only
                return {
                    "content": [{"type": "text", "text": "no more"}],
                    "stop_reason": "end_turn",
                }
        return mock_call

    def test_single_tool_use_then_text(self):
        """LLM 第一輪給 tool_use、第二輪給 final text"""
        from bridge.minimax_streaming_client import MiniMaxStreamingClient
        from bridge.tools import execute_tool_call

        # 設定 client（用 test env vars）
        client = MiniMaxStreamingClient()

        # 第一次回 tool_use + text → 跑 list_dir → 第二次回 final text
        mock_call = self._mock_call([
            {
                "content": [
                    {"type": "text", "text": "我看看 sandbox 有什麼\n"},
                    {"type": "tool_use", "id": "toolu_123", "name": "list_dir", "input": {"path": "."}},
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "我看到了一些檔案"},
                ],
                "stop_reason": "end_turn",
            },
        ])

        async def main():
            with patch.object(client, "_call_api_collect", side_effect=mock_call):
                # executor 把 set_mood/play_motion 走 SendTask、其他走 registry
                async def executor(tool_name, tool_args, ctx):
                    return await execute_tool_call(tool_name, tool_args, ctx)

                # 預先建 fake 的 sandbox 檔（execute_tool_call 會走 list_dir）
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / "test.txt").write_text("hi")
                    import bridge.tools.os_runtime_client as _orc
                    import bridge.tools.filesystem as _fs
                    import bridge.tools.shell as _sh

                    class _FakeR:
                        def __init__(self, root):
                            self.sandbox_root = Path(root)
                        def list_directory(self, **kw):
                            return {"ok": True, "path": ".", "entries": ["test.txt"], "count": 1, "truncated": False}
                    fake = _FakeR(tmp)
                    _orc.get_os_runtime_client = lambda: fake
                    _fs.os_runtime_client.get_os_runtime_client = lambda: fake
                    _sh.os_runtime_client.get_os_runtime_client = lambda: fake

                    result = await client.run_agent_loop(
                        user_message="列出 sandbox 內容",
                        system_prompt="你是 SIRO",
                        tools=[],
                        executor=executor,
                        max_iterations=3,
                    )

            assert result.finish_reason == "ok"
            assert "我看到了一些檔案" in result.text
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0].tool_name == "list_dir"
            assert result.tool_calls[0].result["ok"] is True
            assert result.iterations == 2

        asyncio.run(main())

    def test_no_tool_use_returns_text_immediately(self):
        """LLM 第一輪就給 text、loop 收工"""
        from bridge.minimax_streaming_client import MiniMaxStreamingClient
        from bridge.tools import execute_tool_call

        client = MiniMaxStreamingClient()

        mock_call = self._mock_call([
            {
                "content": [{"type": "text", "text": "我直接回答你"}],
                "stop_reason": "end_turn",
            },
        ])

        async def main():
            with patch.object(client, "_call_api_collect", side_effect=mock_call):
                async def executor(tool_name, tool_args, ctx):
                    pytest.fail("executor 不該被呼叫")

                result = await client.run_agent_loop(
                    user_message="hi",
                    system_prompt="",
                    tools=[],
                    executor=executor,
                    max_iterations=3,
                )

            assert result.finish_reason == "ok"
            assert result.text == "我直接回答你"
            assert len(result.tool_calls) == 0
            assert result.iterations == 1

        asyncio.run(main())

    def test_max_iterations_stops_loop(self):
        """跑滿 max_iterations 就停"""
        from bridge.minimax_streaming_client import MiniMaxStreamingClient
        from bridge.tools import execute_tool_call

        client = MiniMaxStreamingClient()

        # 每次都回 tool_use、不停
        def always_tool_use(*, messages, system_prompt=None, tools=None, **kwargs):
            async def _inner():
                return {
                    "content": [
                        {"type": "tool_use", "id": "tu_x", "name": "list_dir", "input": {"path": "."}},
                    ],
                    "stop_reason": "tool_use",
                }
            return _inner()

        call_count = 0

        async def main():
            nonlocal call_count

            async def fake_call(*, messages, system_prompt=None, tools=None, **kwargs):
                nonlocal call_count
                call_count += 1
                return {
                    "content": [
                        {"type": "tool_use", "id": f"tu_{call_count}", "name": "list_dir", "input": {"path": "."}},
                    ],
                    "stop_reason": "tool_use",
                }

            with patch.object(client, "_call_api_collect", side_effect=fake_call):
                async def executor(tool_name, tool_args, ctx):
                    return await execute_tool_call(tool_name, tool_args, ctx)

                result = await client.run_agent_loop(
                    user_message="loop test",
                    system_prompt="",
                    tools=[],
                    executor=executor,
                    max_iterations=3,
                )

            assert result.finish_reason == "max_iterations"
            assert result.iterations == 3
            assert len(result.tool_calls) == 3

        asyncio.run(main())

    def test_executor_exception_caught(self):
        """executor 拋 exception → 包成 error result、不中斷 loop"""
        from bridge.minimax_streaming_client import MiniMaxStreamingClient

        client = MiniMaxStreamingClient()

        async def main():
            async def fake_call(*, messages, system_prompt=None, tools=None, **kwargs):
                if len([m for m in messages if m["role"] == "user"]) == 1:
                    # 第一次：tool_use
                    return {
                        "content": [
                            {"type": "tool_use", "id": "tu_1", "name": "list_dir", "input": {"path": "."}},
                        ],
                        "stop_reason": "tool_use",
                    }
                else:
                    # 第二次：final text
                    return {
                        "content": [{"type": "text", "text": "完成"}],
                        "stop_reason": "end_turn",
                    }

            async def bad_executor(tool_name, tool_args, ctx):
                raise RuntimeError("boom")

            with patch.object(client, "_call_api_collect", side_effect=fake_call):
                result = await client.run_agent_loop(
                    user_message="test",
                    system_prompt="",
                    tools=[],
                    executor=bad_executor,
                    max_iterations=3,
                )

            assert result.finish_reason == "ok"
            assert result.text == "完成"
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0].result["ok"] is False
            assert "boom" in result.tool_calls[0].result["error"]

        asyncio.run(main())
