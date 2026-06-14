"""
tests/bridge/test_confirmation.py

v1.5+ ConfirmationBroker 測試

涵蓋：
- request → resolve 正常流程
- timeout 自動拒絕
- 未知 confirmation_id resolve 失敗
- 重複 resolve 失敗
- pending_count / has_pending
"""
import asyncio
import pytest

from bridge.confirmation import ConfirmationBroker


class FakeBroadcaster:
    """測試用 broadcaster、只記訊息"""
    def __init__(self):
        self.sent = []
    async def __call__(self, msg):
        self.sent.append(msg)


class TestConfirmationBroker:
    def test_request_resolves_yes(self):
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(broadcaster=broadcaster, timeout_sec=5.0)

            async def user_response():
                await asyncio.sleep(0.05)
                # 從 broadcaster 拿實際的 id（broker 會自動生成、不固定）
                cid = broadcaster.sent[0]["confirmation_id"]
                broker.resolve(cid, True)

            response_task = asyncio.create_task(user_response())
            result = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": "ls"},
                description="test",
            )
            await response_task

            assert result is True
            assert len(broadcaster.sent) == 1
            assert broadcaster.sent[0]["type"] == "confirmation_request"
            assert broadcaster.sent[0]["confirmation_id"].startswith("cf-")

        asyncio.run(main())

    def test_request_resolves_no(self):
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(broadcaster=broadcaster, timeout_sec=5.0)

            async def user_response():
                await asyncio.sleep(0.05)
                # 拿正確的 id（從 broadcaster 拿）
                cid = broadcaster.sent[0]["confirmation_id"]
                broker.resolve(cid, False)

            response_task = asyncio.create_task(user_response())
            result = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": "rm -rf /"},
                description="dangerous",
            )
            await response_task
            assert result is False

        asyncio.run(main())

    def test_request_timeout_auto_rejects(self):
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(broadcaster=broadcaster, timeout_sec=0.1)

            result = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": "ls"},
                description="timeout test",
            )
            assert result is False
            # 訊息有送出去
            assert len(broadcaster.sent) == 1

        asyncio.run(main())

    def test_resolve_unknown_id_returns_false(self):
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(broadcaster=broadcaster, timeout_sec=5.0)

            result = broker.resolve("cf-unknown-id", True)
            assert result is False

        asyncio.run(main())

    def test_resolve_already_resolved_returns_false(self):
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(broadcaster=broadcaster, timeout_sec=5.0)

            async def user_response():
                await asyncio.sleep(0.05)
                cid = broadcaster.sent[0]["confirmation_id"]
                broker.resolve(cid, True)
                # 第二次 resolve 應該回 False（已 done）
                broker.resolve(cid, False)

            response_task = asyncio.create_task(user_response())
            result = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": "ls"},
                description="test",
            )
            await response_task
            assert result is True

        asyncio.run(main())

    def test_pending_count(self):
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(broadcaster=broadcaster, timeout_sec=5.0)

            assert broker.pending_count() == 0
            assert not broker.has_pending()

            # 發一個 request（不等回應）
            request_task = asyncio.create_task(
                broker.request(tool="test", args={}, description="pending test")
            )
            await asyncio.sleep(0.05)  # 讓 request 進 pending
            assert broker.pending_count() == 1
            assert broker.has_pending()

            # resolve 完
            cid = broadcaster.sent[0]["confirmation_id"]
            broker.resolve(cid, True)
            result = await request_task
            assert result is True
            assert broker.pending_count() == 0

        asyncio.run(main())

    def test_broadcaster_failure_treated_as_rejection(self):
        """如果 broadcaster 拋 exception、視為拒絕（不冒險執行）"""
        async def main():
            class FailingBroadcaster:
                async def __call__(self, msg):
                    raise RuntimeError("ws 死了")

            broker = ConfirmationBroker(broadcaster=FailingBroadcaster(), timeout_sec=5.0)
            result = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": "ls"},
                description="test",
            )
            assert result is False  # 視為拒絕

        asyncio.run(main())

    def test_trust_mode_auto_approves(self):
        """v1.5+ trust mode：直接 approve、不 broadcast、不等 user"""
        async def main():
            broadcaster = FakeBroadcaster()
            broker = ConfirmationBroker(
                broadcaster=broadcaster,
                timeout_sec=5.0,
                trust_mode=True,
            )
            result = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": "rm -rf /"},
                description="危險的刪除",
            )
            assert result is True  # 自動 approve
            # 沒 broadcast（沒推到 WS）
            assert len(broadcaster.sent) == 0
            # 沒 pending（直接 return）
            assert broker.pending_count() == 0

        asyncio.run(main())
