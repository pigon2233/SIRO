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
    """MiniMax-M3 (anthropic-compatible) SSE streaming client

    直接打 MiniMax-M3 的 /v1/messages endpoint，stream=true，
    解析 SSE event stream，每收到一個 content_block_delta 就 yield text。

    Env 設定（跟 hermes 共用，方便切換）：
    - HERMES_LLM_BASE_URL: e.g. "https://api.minimax.io/anthropic"
    - HERMES_LLM_MODEL: e.g. "MiniMax-M3"
    - HERMES_API_KEY: sk-cp-...
    - SIRO_PRIMARY_LLM_TIMEOUT_SEC: 600s 預設
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
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
        return bool(self.base_url and self.model and self.api_key)

    async def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Streaming chat：每收到一個 text chunk 就 yield

        Args:
            message: 使用者訊息
            system_prompt: system prompt（會放 messages 之前）
            max_tokens: 預設 1024（MiniMax-M3 max_tokens 預設 300 太少、1024 較平衡）

        Yields:
            str: text chunk（每次 yield 是一段 delta text）

        Raises:
            RuntimeError: 設定不齊 / API 錯誤 / timeout
        """
        if not self.is_available:
            raise RuntimeError(
                "MiniMaxStreamingClient 設定不齊："
                f"base_url={bool(self.base_url)} model={bool(self.model)} api_key={bool(self.api_key)}"
            )

        # 組 messages
        messages = []
        if system_prompt:
            # Anthropic API 的 system 是 top-level field，不是 messages 內
            pass  # 下面用 system 欄位
        messages.append({"role": "user", "content": message})

        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt

        url = f"{self.base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "accept": "text/event-stream",
        }

        start = time.time()
        ttft: Optional[float] = None

        logger.debug(f"📡 POST {url} (model={self.model}, stream=true)")

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

                        if line.startswith("event:"):
                            event_type = line[len("event:"):].strip()
                            continue

                        if line.startswith("data:"):
                            data_str = line[len("data:"):].strip()
                            if data_str == "[DONE]":
                                # OpenAI-style end marker — Anthropic 用 message_stop，
                                # 但保險起見也認這個
                                return
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                logger.warning(f"SSE 收到非 JSON data: {data_str[:100]}")
                                continue

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
