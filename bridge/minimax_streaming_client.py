"""
bridge/minimax_streaming_client.py - MiniMax-M3 Anthropic-compatible SSE streaming client

v0.3.1 實作：STRATEGIC_NOTES Q2 選項 B — 保持 MiniMax-M3、走 SSE streaming。

為什麼獨立檔（不直接加到 HermesClient）：
- HermesClient.chat() 走 hermes subprocess（無 streaming）
- hermes proxy 不支援 anthropic provider
- 這條路是「直打 MiniMax-M3 /anthropic API」，跟 hermes 是平行關係
- 分檔：保留 HermesClient 給 sync 路徑、避免污染

取捨（已記在 STRATEGIC_NOTES Q2）：
- 「hermes 抽象」變薄 — 但仍用同一組 env vars（HERMES_LLM_BASE_URL / _MODEL / _KEY）
- 之後換 provider 改這檔（不是 hermes）
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MiniMaxStreamingResult:
    """Streaming 結果（最後一次 yield 帶的所有資訊）"""
    success: bool
    text: str = ""                         # 完整文字（拼接所有 chunks）
    chunks: list[str] = field(default_factory=list)  # 收到的每個 chunk
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    ttft_ms: Optional[int] = None          # Time To First Token（第一個 chunk 從送出到收到）


@dataclass
class StreamEvent:
    """v1.5+ SSE event 結構化封裝

    chat_stream 原本只 yield text chunks。v1.5+ tool calling 引入後、
    LLM 回的 SSE 事件類型變多、要 yield 結構化 event 給 caller 處理。

    事件型別：
    - "text": 文字 chunk
    - "tool_use": LLM 想 invoke 一個 tool（Anthropic API 的 tool_use block）
    - "message_stop": 對話結束
    - "error": API 錯誤
    """
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    message: str = ""

    @classmethod
    def text_event(cls, text):
        return cls(type="text", text=text)

    @classmethod
    def tool_use_event(cls, id, name, input):
        return cls(type="tool_use", id=id, name=name, input=input)

    @classmethod
    def stop_event(cls):
        return cls(type="message_stop")

    @classmethod
    def error_event(cls, message):
        return cls(type="error", message=message)


class MiniMaxStreamingClient:
    """Anthropic / Ollama SSE streaming client

    支援兩種後端：
    - MiniMax-M3 (Anthropic format, /v1/messages) — 預設雲端路徑
    - Ollama (native /api/chat, NDJSON) — 本地 fallback

    Env 設定（HERMES_LLM_PROVIDER 決定走哪條路徑）：
    - HERMES_LLM_PROVIDER: anthropic | ollama  (預設 anthropic)
    - HERMES_LLM_BASE_URL: 依 provider 不同
        - anthropic: https://api.minimax.io/anthropic
        - ollama: http://localhost:11434
    - HERMES_LLM_MODEL: 依 provider 不同
    - HERMES_API_KEY: anthropic 需要；ollama 隨便填
    - SIRO_PRIMARY_LLM_TIMEOUT_SEC: 600s 預設
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
        provider: Optional[str] = None,
    ):
        self.provider = (provider or os.environ.get("HERMES_LLM_PROVIDER", "anthropic")).lower()
        self.base_url = (base_url or os.environ.get("HERMES_LLM_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("HERMES_LLM_MODEL", "")
        self.api_key = api_key or os.environ.get("HERMES_API_KEY", "")

        if timeout is None:
            try:
                timeout = int(os.environ.get("SIRO_PRIMARY_LLM_TIMEOUT_SEC", "600"))
            except (TypeError, ValueError):
                timeout = 600
        self.timeout = timeout

    @property
    def is_available(self) -> bool:
        """設定是否齊全（不一定代表 API 真的通，但至少能送 request）"""
        if not (self.base_url and self.model):
            return False
        # Ollama 隨便填 api_key 也行（Ollama 不檢查）
        # 其他 provider 需要 api_key
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def _is_ollama(self) -> bool:
        """Ollama 走 native /api/chat（NDJSON）、跟 Anthropic /v1/messages 不一樣

        偵測邏輯：顯式 HERMES_LLM_PROVIDER=ollama 或 endpoint 包含 11434
        """
        if self.provider == "ollama":
            return True
        # 沒顯式 provider 但 port 11434、視為 Ollama
        if ":11434" in self.base_url:
            return True
        return False

    async def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Streaming chat：每收到一個 text chunk 就 yield

        根據 provider dispatch 到不同後端：
        - ollama：native /api/chat NDJSON
        - anthropic (MiniMax-M3)：Anthropic SSE format（預設）

        Args:
            message: 使用者訊息
            system_prompt: system prompt（會放 messages 之前）
            max_tokens: 預設 1024

        Yields:
            str: text chunk（每次 yield 是一段 delta text）

        Raises:
            RuntimeError: 設定不齊 / API 錯誤 / timeout
        """
        if not self.is_available:
            raise RuntimeError(
                f"MiniMaxStreamingClient 設定不齊（provider={self.provider}）："
                f"base_url={bool(self.base_url)} model={bool(self.model)} api_key={bool(self.api_key)}"
            )

        messages = [{"role": "user", "content": message}]

        # v1.5.2：自動偵測 Ollama、用 native API
        if self._is_ollama():
            url = f"{self.base_url}/api/chat"
            headers = {"Content-Type": "application/json"}
            ollama_messages = []
            if system_prompt:
                ollama_messages.append({"role": "system", "content": system_prompt})
            ollama_messages.append({"role": "user", "content": message})
            # 把 temperature / repeat_penalty / num_predict 從 env 拉：
            # - 預設保守（temp 0.5 / repeat 1.1）— 想要更活潑 SIRO_OLLAMA_TEMPERATURE=0.7
            # - num_predict 預設 1024（跟 max_tokens 對齊）
            try:
                _ollama_temp = float(os.environ.get("SIRO_OLLAMA_TEMPERATURE", "0.5"))
                _ollama_repeat = float(os.environ.get("SIRO_OLLAMA_REPEAT_PENALTY", "1.1"))
                _ollama_num_predict = int(os.environ.get("SIRO_OLLAMA_NUM_PREDICT", str(max_tokens)))
            except (TypeError, ValueError):
                _ollama_temp, _ollama_repeat, _ollama_num_predict = 0.5, 1.1, max_tokens
            body = {
                "model": self.model,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": ollama_messages,
                "options": {
                    "temperature": _ollama_temp,
                    "repeat_penalty": _ollama_repeat,
                    "num_predict": _ollama_num_predict,
                },
            }
        else:
            url = f"{self.base_url}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "accept": "text/event-stream",
            }
            body = {
                "model": self.model,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": messages,
            }
            if system_prompt:
                body["system"] = system_prompt

        start = time.time()
        ttft: Optional[float] = None

        logger.debug(f"📡 POST {url} (model={self.model}, stream=true)")

        # （繼續原 Anthropic/Ollama 解析邏輯）

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code != 200:
                        # 把錯誤 body 讀完
                        err_body = await response.aread()
                        err_text = err_body.decode("utf-8", errors="replace")[:500]
                        raise RuntimeError(
                            f"MiniMax-M3 API error {response.status_code}: {err_text}"
                        )

                    # 解析 SSE event stream
                    event_type: Optional[str] = None
                    async for line in response.aiter_lines():
                        if not line:
                            # 空行 = event boundary
                            event_type = None
                            continue

                        # v1.5.3 fix：Ollama /api/chat stream 回的是 NDJSON（每行一個 JSON），
                        # 沒有 "data:" prefix。沒這個 early branch 的話，
                        # 整個 stream 會被忽略、TTFT=None / deltas=0、Unity 收到空字串。
                        if self._is_ollama() and line.startswith("{"):
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                logger.warning(f"Ollama NDJSON 解析失敗: {line[:100]}")
                                continue
                            msg = data.get("message", {})
                            text_chunk = msg.get("content", "")
                            if text_chunk:
                                if ttft is None:
                                    ttft = time.time() - start
                                    logger.debug(
                                        f"⚡ TTFT={ttft*1000:.0f}ms（Ollama 首個 chunk）"
                                    )
                                yield text_chunk
                            if data.get("done"):
                                return
                            continue

                        if line.startswith("event:"):
                            event_type = line[len("event:"):].strip()
                            continue

                        if line.startswith("data:"):
                            data_str = line[len("data:"):].strip()
                            if data_str == "[DONE]":
                                # 部分 SSE 實作用 [DONE] 收尾 — Anthropic 用 message_stop，
                                # 但保險起見也認這個
                                return
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                logger.warning(f"SSE 收到非 JSON data: {data_str[:100]}")
                                continue

                            # v1.5.2：Ollama 格式 {"message":{"content":"..."},"done":false}
                            if self._is_ollama():
                                msg = data.get("message", {})
                                text_chunk = msg.get("content", "")
                                if text_chunk:
                                    if ttft is None:
                                        ttft = time.time() - start
                                        logger.debug(
                                            f"⚡ TTFT={ttft*1000:.0f}ms（Ollama 首個 chunk）"
                                        )
                                    yield text_chunk
                                if data.get("done"):
                                    return
                                continue  # Ollama 沒有 event_type、不進下面 Anthropic 邏輯

                            # 只處理 content_block_delta（其他 event 不 yield）
                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text_chunk = delta.get("text", "")
                                    if text_chunk:
                                        if ttft is None:
                                            ttft = time.time() - start
                                            logger.debug(
                                                f"⚡ TTFT={ttft*1000:.0f}ms（首個 chunk）"
                                            )
                                        yield text_chunk

                            # message_stop = 結束
                            if event_type == "message_stop":
                                return

                            # error event
                            if event_type == "error":
                                err_msg = data.get("error", {}).get("message", "unknown")
                                raise RuntimeError(f"MiniMax-M3 SSE error: {err_msg}")

        except httpx.TimeoutException as e:
            raise RuntimeError(f"MiniMax-M3 streaming timeout ({self.timeout}s): {e}")
        except httpx.RequestError as e:
            raise RuntimeError(f"MiniMax-M3 streaming request error: {e}")

    async def chat_collect(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> MiniMaxStreamingResult:
        """便利方法：跑 chat_stream 收集所有 chunk、回傳完整結果

        用法跟 HermesClient.chat() 類似，差別是底層走 SSE。
        適用於「想用 SSE 但又要完整結果」的情境（例如 /chat HTTP）。
        """
        start = time.time()
        chunks: list[str] = []
        ttft_ms: Optional[int] = None

        try:
            async for chunk in self.chat_stream(message, system_prompt, max_tokens):
                if ttft_ms is None:
                    ttft_ms = int((time.time() - start) * 1000)
                chunks.append(chunk)

            text = "".join(chunks)
            duration_ms = int((time.time() - start) * 1000)
            return MiniMaxStreamingResult(
                success=True,
                text=text,
                chunks=chunks,
                duration_ms=duration_ms,
                ttft_ms=ttft_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"MiniMax streaming 失敗: {e}")
            return MiniMaxStreamingResult(
                success=False,
                text="",
                chunks=chunks,
                error=str(e),
                duration_ms=duration_ms,
                ttft_ms=ttft_ms,
            )

    # ================================================================
    # v1.5+ Tool Calling 路徑
    # ================================================================

    # 為了避免改既有 chat_stream 簽名破壞 caller、新增 chat_stream_with_tools
    # caller 想要 text-only 走 chat_stream、想要 tool 走 chat_stream_with_tools

    async def chat_stream_with_tools(
        self,
        message: str,
        system_prompt=None,
        max_tokens: int = 1024,
        tools: list = None,
    ):
        """v1.5+ LLM tool calling 的 streaming 版本

        跟 chat_stream 差別：
        - 多接 tools 參數（Anthropic tool_use 格式 list）
        - Yield StreamEvent 而非純 text chunk
        - 多解析 content_block_start + content_block_delta(input_json_delta) + content_block_stop 事件
        """
        if not self.is_available:
            raise RuntimeError(
                "MiniMaxStreamingClient 設定不齊："
                f"base_url={bool(self.base_url)} model={bool(self.model)} api_key={bool(self.api_key)}"
            )

        messages = [{"role": "user", "content": message}]

        # v1.5.2：自動偵測 Ollama、用 native API
        if self._is_ollama():
            url = f"{self.base_url}/api/chat"
            headers = {"Content-Type": "application/json"}
            ollama_messages = []
            if system_prompt:
                ollama_messages.append({"role": "system", "content": system_prompt})
            ollama_messages.append({"role": "user", "content": message})
            # 把 temperature / repeat_penalty / num_predict 從 env 拉：
            # - 預設保守（temp 0.5 / repeat 1.1）— 想要更活潑 SIRO_OLLAMA_TEMPERATURE=0.7
            # - num_predict 預設 1024（跟 max_tokens 對齊）
            try:
                _ollama_temp = float(os.environ.get("SIRO_OLLAMA_TEMPERATURE", "0.5"))
                _ollama_repeat = float(os.environ.get("SIRO_OLLAMA_REPEAT_PENALTY", "1.1"))
                _ollama_num_predict = int(os.environ.get("SIRO_OLLAMA_NUM_PREDICT", str(max_tokens)))
            except (TypeError, ValueError):
                _ollama_temp, _ollama_repeat, _ollama_num_predict = 0.5, 1.1, max_tokens
            body = {
                "model": self.model,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": ollama_messages,
                "options": {
                    "temperature": _ollama_temp,
                    "repeat_penalty": _ollama_repeat,
                    "num_predict": _ollama_num_predict,
                },
            }
        else:
            body = {
                "model": self.model,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": messages,
            }
            if system_prompt:
                body["system"] = system_prompt
            if tools:
                body["tools"] = tools

            url = f"{self.base_url}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "accept": "text/event-stream",
            }

        start = time.time()
        ttft = None
        pending_tool_use = None  # {id, name, input_json}

        logger.debug(f"[stream-tools] POST {url} (model={self.model}, tools={len(tools) if tools else 0})")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code != 200:
                        err_body = await response.aread()
                        err_text = err_body.decode("utf-8", errors="replace")[:500]
                        raise RuntimeError(
                            f"MiniMax-M3 API error {response.status_code}: {err_text}"
                        )

                    event_type = None
                    async for line in response.aiter_lines():
                        if not line:
                            event_type = None
                            continue

                        # v1.5.3 fix：Ollama NDJSON 早期分支（同 chat_stream 註解）
                        # 沒這個的話 Ollama stream-tools 整段會被忽略
                        if self._is_ollama() and line.startswith("{"):
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                logger.warning(f"Ollama NDJSON 解析失敗: {line[:100]}")
                                continue
                            msg = data.get("message", {})
                            text_chunk = msg.get("content", "")
                            if text_chunk:
                                if ttft is None:
                                    ttft = time.time() - start
                                    logger.debug(
                                        f"[stream-tools] TTFT={ttft*1000:.0f}ms（Ollama 首個 chunk）"
                                    )
                                yield StreamEvent.text_event(text_chunk)
                            if data.get("done"):
                                return
                            continue

                        if line.startswith("event:"):
                            event_type = line[len("event:"):].strip()
                            continue

                        if line.startswith("data:"):
                            data_str = line[len("data:"):].strip()
                            if data_str == "[DONE]":
                                return
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                logger.warning(f"SSE 收到非 JSON data: {data_str[:100]}")
                                continue

                            # content_block_start - LLM 開始一個 text 或 tool_use block
                            if event_type == "content_block_start":
                                block = data.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    pending_tool_use = {
                                        "id": block.get("id", ""),
                                        "name": block.get("name", ""),
                                        "input_json": "",
                                    }

                            # content_block_delta - 累積 text / tool_use input
                            elif event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                delta_type = delta.get("type")
                                if delta_type == "text_delta":
                                    text_chunk = delta.get("text", "")
                                    if text_chunk:
                                        if ttft is None:
                                            ttft = time.time() - start
                                            logger.debug(
                                                f"[stream-tools] TTFT={ttft*1000:.0f}ms（首個 chunk）"
                                            )
                                        yield StreamEvent.text_event(text_chunk)
                                elif delta_type == "input_json_delta" and pending_tool_use is not None:
                                    pending_tool_use["input_json"] += delta.get("partial_json", "")

                            # content_block_stop - tool_use 結束、解析累積的 JSON
                            elif event_type == "content_block_stop":
                                if pending_tool_use is not None:
                                    try:
                                        input_dict = json.loads(pending_tool_use["input_json"]) if pending_tool_use["input_json"] else {}
                                    except json.JSONDecodeError as e:
                                        logger.warning(
                                            f"[stream-tools] tool_use input JSON 解析失敗: {e}"
                                        )
                                        input_dict = {}
                                    yield StreamEvent.tool_use_event(
                                        id=pending_tool_use["id"],
                                        name=pending_tool_use["name"],
                                        input=input_dict,
                                    )
                                    pending_tool_use = None

                            # message_start / message_delta - debug 用
                            elif event_type == "message_start":
                                model = data.get("message", {}).get("model", "")
                                if model:
                                    logger.debug(f"[stream-tools] message_start model={model}")
                            elif event_type == "message_delta":
                                stop_reason = data.get("delta", {}).get("stop_reason")
                                if stop_reason:
                                    logger.debug(f"[stream-tools] stop_reason={stop_reason}")

                            # message_stop = 結束
                            if event_type == "message_stop":
                                return

                            # error event
                            if event_type == "error":
                                err_msg = data.get("error", {}).get("message", "unknown")
                                raise RuntimeError(f"MiniMax-M3 SSE error: {err_msg}")

        except httpx.TimeoutException as e:
            raise RuntimeError(f"MiniMax-M3 streaming timeout ({self.timeout}s): {e}")
        except httpx.RequestError as e:
            raise RuntimeError(f"MiniMax-M3 streaming request error: {e}")

    # ================================================================
    # v1.5+ Computer Control — multi-turn agent loop
    # ================================================================
    #
    # chat_stream_with_tools 是 single-turn：
    #   user message → LLM → (text + tool_use) → done
    #
    # 但 agent 模式需要 multi-turn：
    #   user → LLM (tool_use) → execute → tool_result → LLM → (text or more tool_use) → ...
    #
    # 用法：
    #   result = await client.run_agent_loop(
    #       user_message="幫我找出 *.txt 檔",
    #       system_prompt=...,
    #       tools=[...tool defs...],
    #       executor=my_tool_executor,  # async (tool_name, args) -> dict
    #       max_iterations=5,
    #   )
    #   result.text  # 最終文字
    #   result.tool_calls  # 過程中所有 tool_use 記錄
    #
    # 設計：直接打 HTTP（不走 SSE）、收集完整 result
    #   SSE 在 agent loop 用不上、因為 LLM 一次只回 tool_use 就要停下來執行
    #   用 non-streaming 比較簡單

    async def run_agent_loop(
        self,
        *,
        user_message: str,
        system_prompt=None,
        tools=None,
        executor=None,  # async (tool_name, args, ctx) -> dict
        max_iterations: int = 5,
        ctx: dict = None,
    ):
        """v1.5+ multi-turn agent loop

        Args:
            user_message: 起始 user message
            system_prompt: 給 LLM 的 system prompt
            tools: tool definitions (Anthropic tool_use format)
            executor: async function(tool_name, args, ctx) -> dict
            max_iterations: 最多跑幾輪 tool 呼叫（防 runaway）
            ctx: 給 executor 的 context

        Returns:
            AgentLoopResult: 包含 text / tool_calls / iterations

        Note:
            v1.5+ MVP: 不支援 parallel tool_use（一輪一個 tool）
            之後 v2.0 可加：parallel tool calls、error recovery、token budget
        """
        from dataclasses import dataclass, field

        @dataclass
        class ToolCallRecord:
            tool_name: str
            args: dict
            result: dict
            duration_ms: int

        @dataclass
        class AgentLoopResult:
            text: str = ""
            tool_calls: list = field(default_factory=list)
            iterations: int = 0
            finish_reason: str = "ok"  # ok / max_iterations / error

        if not self.is_available:
            raise RuntimeError("MiniMaxStreamingClient 設定不齊")

        if executor is None:
            raise ValueError("executor 必填（async (tool_name, args, ctx) -> dict）")

        ctx = ctx or {}
        result = AgentLoopResult()
        # Anthropic 多輪對話格式
        messages: list = [{"role": "user", "content": user_message}]

        for i in range(max_iterations):
            result.iterations = i + 1
            logger.info(f"[agent-loop] iteration #{i+1}")

            # 打 LLM
            try:
                turn = await self._call_api_collect(
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools,
                )
            except Exception as e:
                logger.error(f"[agent-loop] LLM call 失敗: {e}")
                result.finish_reason = "error"
                return result

            content_blocks = turn.get("content", [])

            # 拆 blocks：text 累積、tool_use 收集起來
            text_parts: list = []
            tool_uses: list = []
            for block in content_blocks:
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_uses.append({
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })

            # 累積 text
            new_text = "".join(text_parts)
            if new_text:
                result.text = (result.text + new_text) if result.text else new_text

            # 把 assistant 這一輪加到 messages（Anthropic 規定要把整個 content 回傳）
            messages.append({"role": "assistant", "content": content_blocks})

            # 沒 tool_use → LLM 收工
            if not tool_uses:
                logger.info(f"[agent-loop] iteration #{i+1} 沒 tool_use、收工")
                result.finish_reason = "ok"
                return result

            # 有 tool_use → 跑 executor、把 tool_result 加到 messages
            tool_results: list = []
            for tu in tool_uses:
                t0 = time.time()
                try:
                    tool_result = await executor(tu["name"], tu["input"], ctx)
                except Exception as e:
                    tool_result = {
                        "ok": False,
                        "error": f"executor 拋 exception: {type(e).__name__}: {e}",
                    }
                duration_ms = int((time.time() - t0) * 1000)

                result.tool_calls.append(ToolCallRecord(
                    tool_name=tu["name"],
                    args=tu["input"],
                    result=tool_result,
                    duration_ms=duration_ms,
                ))
                logger.info(
                    f"[agent-loop] tool_use {tu['name']}({tu['input']}) → "
                    f"{tool_result.get('ok', '?')} ({duration_ms}ms)"
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

            # 把 tool_results 加成 user message（Anthropic 多輪格式）
            messages.append({"role": "user", "content": tool_results})

        # 超過 max_iterations
        logger.warning(f"[agent-loop] 跑滿 {max_iterations} 輪、停止")
        result.finish_reason = "max_iterations"
        return result

    async def _call_api_collect(
        self,
        *,
        messages: list,
        system_prompt=None,
        tools=None,
        max_tokens: int = 1024,
    ) -> dict:
        """打 LLM API 一次、收完整 response（不 streaming）

        給 run_agent_loop 用。
        回傳：{"content": [...blocks], "stop_reason": "..."}
        """
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = tools

        # v1.5.2：自動偵測 Ollama、用 native API
        if self._is_ollama():
            url = f"{self.base_url}/api/chat"
            headers = {"Content-Type": "application/json"}
            # v1.5.3 fix：Ollama /api/chat 預設 stream=true 會回 NDJSON、
            # 這裡想要的是完整 single response、所以要 stream:false
            # 沒這個會 JSON parse 噴 "Extra data: line 2 column 1"
            body["stream"] = False
            # v1.5.3：跟 chat_stream 一致 — temperature / repeat_penalty / num_predict 從 env 拉
            try:
                _ollama_temp = float(os.environ.get("SIRO_OLLAMA_TEMPERATURE", "0.5"))
                _ollama_repeat = float(os.environ.get("SIRO_OLLAMA_REPEAT_PENALTY", "1.1"))
                _ollama_num_predict = int(os.environ.get("SIRO_OLLAMA_NUM_PREDICT", str(max_tokens)))
            except (TypeError, ValueError):
                _ollama_temp, _ollama_repeat, _ollama_num_predict = 0.5, 1.1, max_tokens
            body["options"] = {
                "temperature": _ollama_temp,
                "repeat_penalty": _ollama_repeat,
                "num_predict": _ollama_num_predict,
            }
        else:
            url = f"{self.base_url}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }

        logger.debug(f"[agent-loop] POST {url} (iter messages={len(messages)})")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            if response.status_code != 200:
                err_text = response.text[:500]
                raise RuntimeError(
                    f"MiniMax-M3 API error {response.status_code}: {err_text}"
                )
            data = response.json()

        # v1.5.2：Ollama 回傳 {"message":{"role":"assistant","content":"..."},"done":...}
        # 轉成 Anthropic-style {"content":[{"type":"text","text":"..."}], "stop_reason":"end_turn"}
        if self._is_ollama():
            msg = data.get("message", {})
            content_text = msg.get("content", "")
            return {
                "content": [{"type": "text", "text": content_text}] if content_text else [],
                "stop_reason": "end_turn" if data.get("done", True) else "max_tokens",
            }

        return {
            "content": data.get("content", []),
            "stop_reason": data.get("stop_reason", ""),
        }
