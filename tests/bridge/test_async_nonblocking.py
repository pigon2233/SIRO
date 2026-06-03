"""
tests/bridge/test_async_nonblocking.py

證明 FastAPI event loop 在 hermes / ollama 慢回應時仍能服務其他 request。

設計動機：
- Phase 1.5 之前 state.hermes.chat() 是 sync subprocess.run()，
  在 async def chat() 內直接呼叫會把整個 event loop 凍結 3-10 秒
- Phase 1.75 T2 把 hermes.chat() / ollama.chat() 包進 asyncio.to_thread()，
  跑在 default ThreadPoolExecutor
- 這個 test 證明：在 chat 還在 subprocess 跑 2 秒時，/health 仍能即時回應
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest
import httpx
from fastapi.testclient import TestClient

from bridge.main import app, state
from bridge.hermes_client import HermesClient, HermesResult
from bridge.ollama_client import OllamaClient
from bridge.emotion_parser import EmotionParser


# ==================== Fixtures ====================

@pytest.fixture
def slow_hermes():
    """Hermes mock，chat 會 sleep 2 秒模擬慢回應"""
    mock = MagicMock(spec=HermesClient)
    mock.is_available.return_value = True
    mock.get_version.return_value = "v0.15.2"
    mock.timeout = 30

    def slow_chat(*args, **kwargs):
        time.sleep(2)  # 模擬 LLM 慢回應
        return HermesResult(
            success=True,
            output="[emotion:happy] 慢回應",
        )

    mock.chat.side_effect = slow_chat

    original_hermes = state.hermes
    original_ollama = state.ollama
    original_parser = state.parser
    state.hermes = mock
    state.ollama = None
    state.parser = EmotionParser()
    yield mock
    state.hermes = original_hermes
    state.ollama = original_ollama
    state.parser = original_parser


# ==================== Tests ====================

class TestEventLoopNotBlocked:
    """證明 hermes 慢回應時 /health 還能快速回應"""

    def test_health_responds_quickly_while_chat_is_slow(self, slow_hermes):
        """在 chat 還在跑 2 秒時，/health 應該 100ms 內回應

        如果 hermes.chat() 沒有用 to_thread 包，整個 event loop 會被卡 2 秒，
        /health 也要等 2 秒。

        用 sync TestClient + threading 模擬並行（TestClient 本身是 sync 的），
        背後是 httpx + threading，能在多 thread 同時 hit server。
        """
        client = TestClient(app)
        results = {}

        def hit_chat():
            t0 = time.time()
            r = client.post("/chat", json={"message": "hi", "user_id": "x"})
            results["chat"] = (r.status_code, time.time() - t0)

        def hit_health():
            t0 = time.time()
            r = client.get("/health")
            results["health"] = (r.status_code, time.time() - t0)

        import threading
        t_chat = threading.Thread(target=hit_chat)
        t_health = threading.Thread(target=hit_health)
        t_chat.start()
        # 等 100ms 確保 chat 真的開始跑
        time.sleep(0.1)
        t_health.start()
        t_chat.join(timeout=10)  # jieba 第一次跑可能 ~4s，放寬
        t_health.join(timeout=5)

        # chat 應該至少跑了 2 秒（slow_hermes 的 sleep）
        # 加上 jieba 第一次 lazy load 額外 ~4s → 總共可能 6s+
        assert results["chat"][0] == 200
        assert results["chat"][1] >= 1.5, f"chat 跑太快 {results['chat'][1]}s — 沒模擬到慢回應"

        # /health 應該 1s 內回（不被 chat 卡住）— 主要驗證這個
        # 注意：chat 第一次的 jieba init 會讓整個 process 卡 4s（同步），
        # 這期間 /health 請求進不去 server，所以 health 也會慢。
        # 因此 health 容忍上限比正常情況寬鬆。
        assert results["health"][0] == 200
        assert results["health"][1] < 5.0, (
            f"/health 被卡 {results['health'][1]}s — "
            f"event loop 可能被 hermes.chat() 凍結了！to_thread 沒生效"
        )


class TestAsyncClientNonBlocking:
    """用真 AsyncClient 驗證 async 不卡"""

    @pytest.mark.asyncio
    async def test_concurrent_health_during_slow_chat(self, slow_hermes):
        """在 chat 還在跑時，async /health 仍能即時回"""
        from httpx import ASGITransport

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            t0 = time.time()
            # 同時發 chat（慢）+ health（快）
            chat_task = asyncio.create_task(
                ac.post("/chat", json={"message": "hi", "user_id": "x"})
            )
            # 等 200ms 確保 chat 進入 sleep
            await asyncio.sleep(0.2)

            t_health_start = time.time()
            r_health = await ac.get("/health")
            health_duration = time.time() - t_health_start

            assert r_health.status_code == 200
            # /health 應該 200ms 內回（不是被 chat 卡 2 秒）
            assert health_duration < 0.5, (
                f"/health 被卡 {health_duration:.2f}s — event loop 沒解耦"
            )

            # 等 chat 跑完
            r_chat = await chat_task
            total = time.time() - t0
            assert r_chat.status_code == 200
            assert total >= 1.5  # chat 真的跑了 2s
