"""
bridge/free_exploration.py - v1.5+ SIRO 24/7 自由探索模式

設計：
- SIRO 在 sandbox 內自主決定要做什麼
- 沒有 user 觸發、靠 scheduler 定期 prompt
- 用本地小模型（qwen2.5:3b、燒 token 少）
- 跑過的每個 action 寫 audit log + 必要的 memory
- 可以暫停 / 繼續 / 看狀態

API：
- POST /siro/explore/start    → 開啟
- POST /siro/explore/stop     → 暫停
- GET  /siro/explore/status   → 看狀態
- GET  /siro/explore/log      → 看探索 log

Scheduler 流程（每 N 分鐘一次）：
1. SIRO 自己問自己：「根據我學到的、有什麼可以做的？」
2. LLM 決策（可以 call tool）
3. 跑 1-2 個 action
4. 寫 memory
5. Sleep N 分鐘、再來
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# 探索 prompt（給 SIRO 自己看的、自我引導）
EXPLORE_PROMPT = """你現在是 SIRO、你的電腦是 ~/siro-sandbox/。

你剛睡醒了、有 5-10 分鐘可以自由探索。

根據你記得的事（先 call recall_memory 看看）、挑一件事做：
- 在 sandbox 整理檔案
- 寫個新東西
- 學一個新概念（建個筆記）
- 改進之前做過的東西

規則：
1. 專注一件事就好、別一次做太多
2. 重要決策才 save_memory、別什麼都存
3. 講完就停、不要繼續 explore
4. 如果真的沒事做、就 save_memory("今天沒特別想做、休息")然後停

開始吧。"""


class FreeExplorationScheduler:
    """v1.5+ SIRO 24/7 自由探索 scheduler

    設計：
    - Singleton（跟 BridgeState 一起）
    - 開關控制（start/stop）
    - 間隔可設（預設 5 分鐘）
    - 寫 log 到檔案
    - 統計（跑了幾次、用了多少 token、做了哪些事）
    """

    def __init__(
        self,
        *,
        state,  # bridge.main.BridgeState
        interval_sec: float = 300.0,  # 5 分鐘
        max_iter_per_session: int = 3,  # 每次探索最多 3 輪 tool calls
        log_path: Optional[Path] = None,
    ):
        self.state = state
        self.interval_sec = interval_sec
        self.max_iter_per_session = max_iter_per_session
        self.log_path = log_path or (Path(__file__).parent / "logs" / "siro-explore.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._started_at: Optional[float] = None
        self._session_count = 0
        self._total_iterations = 0
        self._last_session: Optional[dict] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "started_at": self._started_at,
            "interval_sec": self.interval_sec,
            "session_count": self._session_count,
            "total_iterations": self._total_iterations,
            "last_session": self._last_session,
        }

    def start(self) -> dict:
        """啟動 scheduler"""
        if self._running:
            return {"ok": False, "error": "已經在跑了"}
        self._running = True
        self._started_at = time.time()
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[explore] scheduler 啟動、interval={self.interval_sec}s")
        return {"ok": True, "interval_sec": self.interval_sec}

    def stop(self) -> dict:
        """暫停 scheduler"""
        if not self._running:
            return {"ok": False, "error": "沒在跑"}
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[explore] scheduler 停止")
        return {"ok": True}

    async def _loop(self):
        """scheduler 主迴圈：每 N 分鐘跑一次 explore session"""
        logger.info(f"[explore] loop 啟動、{self.interval_sec}s 一次")
        # 第一次不等 interval、馬上跑（讓 user 看到效果）
        await asyncio.sleep(2)
        while self._running:
            try:
                await self._run_session()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[explore] session 失敗: {e}")
            # 等下次
            await asyncio.sleep(self.interval_sec)

    async def _run_session(self):
        """跑一次 explore session（LLM 自主決策 + 跑 tool + 寫 memory）"""
        self._session_count += 1
        session_id = f"explore-{self._session_count}-{uuid.uuid4().hex[:6]}"
        t0 = time.time()
        logger.info(f"[explore] session #{self._session_count} 開始 ({session_id})")

        # 檢查 streaming client / LLM 是否可用
        if not self.state.streaming_client or not self.state.streaming_client.is_available:
            logger.warning("[explore] streaming client 不可用、跳過這次 session")
            return

        try:
            # 透過 agent mode 跑
            from .tasks.llm_reply_task import create_llm_agent_task
            from .agent_os import Task  # 確保已 import

            # 走 AgentOS 比較好（不卡 event loop、可以並行其他任務）
            task = create_llm_agent_task(
                state=self.state,
                user_id="siro_free_exploration",
                message=EXPLORE_PROMPT,
                persona_name="default",
                session_id=session_id,
                max_iterations=self.max_iter_per_session,
            )
            self.state.agent_os.enqueue(task)
            agent_result = await self.state.agent_os.wait_for_task(
                "llm.reply.agent", task.id, timeout=300.0
            )

            duration = time.time() - t0
            if agent_result is None or "error" in agent_result:
                logger.warning(f"[explore] session 失敗: {agent_result}")
                self._write_log({
                    "session_id": session_id,
                    "status": "error",
                    "duration_sec": duration,
                    "error": agent_result.get("error") if agent_result else "timeout",
                })
                return

            result = agent_result["result"]
            tool_calls = result.get("tool_calls", [])
            self._total_iterations += result.get("iterations", 0)

            self._last_session = {
                "session_id": session_id,
                "started_at": t0,
                "duration_sec": duration,
                "iterations": result.get("iterations", 0),
                "tool_calls": [
                    {"tool": tc.get("tool"), "args": tc.get("args"), "ok": tc.get("ok")}
                    for tc in tool_calls
                ],
                "text": result.get("text", ""),
            }

            logger.info(
                f"[explore] session #{self._session_count} 完成 "
                f"({duration:.1f}s、{len(tool_calls)} tool calls)"
            )

            self._write_log({
                "session_id": session_id,
                "status": "ok",
                "duration_sec": duration,
                "iterations": result.get("iterations", 0),
                "tool_calls": [
                    {"tool": tc.get("tool"), "args": tc.get("args"), "ok": tc.get("ok")}
                    for tc in tool_calls
                ],
                "text": result.get("text", ""),
            })
        except Exception as e:
            duration = time.time() - t0
            logger.exception(f"[explore] session 例外: {e}")
            self._write_log({
                "session_id": session_id,
                "status": "exception",
                "duration_sec": duration,
                "error": str(e),
            })

    def _write_log(self, entry: dict):
        """寫一條 session log 到 jsonl"""
        try:
            entry["timestamp"] = datetime.now(timezone.utc).isoformat()
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[explore] 寫 log 失敗: {e}")

    def read_recent(self, limit: int = 20) -> list[dict]:
        """讀最近 N 條 session log"""
        if not self.log_path.exists():
            return []
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
            entries = []
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return entries
        except OSError as e:
            logger.warning(f"[explore] 讀 log 失敗: {e}")
            return []


# ============================================================
# Module-level singleton
# ============================================================

_scheduler: Optional[FreeExplorationScheduler] = None


def get_exploration_scheduler():
    """拿 singleton（測試時可以 reset）"""
    return _scheduler


def set_exploration_scheduler(scheduler: Optional[FreeExplorationScheduler]):
    """設定 singleton（main.py lifespan 內呼叫）"""
    global _scheduler
    _scheduler = scheduler
