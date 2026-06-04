"""
bridge/ollama_client.py - 本地 Ollama LLM client（fallback 用）

用途：
- Primary Hermes (MiniMax-M3) timeout / 失敗時，這個 client 接手
- 走本地 Ollama llama3.2:3b-instruct-q4_0
- 純 HTTP（Ollama REST API），不依賴 hermes CLI
- 也是最後一道防線：Ollama 也掛了就回傳 None → bridge 走 static persona fallback

設計（Phase 1.5）：
- 簡單 REST POST /api/generate，stream=false
- 短 timeout（15s）避免 fallback 自己也卡住
- 解析情緒 tag 一樣透過 EmotionParser（與主路徑共用）

可測：可以注入 base_url 做 unit test
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OllamaResult:
    """Ollama 對話結果"""
    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class OllamaClient:
    """本地 Ollama 的 Python 封裝"""

    DEFAULT_TIMEOUT = 3  # fallback 自己也要有上限，否則 UI 會卡住
    # v1.2+ 縮短：原本 15s 太長，dev box 沒裝 hermes 時每個 chat 都要等 15s
    # 才掉到 hard fallback。降到 3s — 3s 內 Ollama 沒回就放棄、走 persona 靜態文字
    # production（Ollama 真的有跑、3-5s 回）剛好、慢一點也只多等幾秒
    # 從 .env SIRO_FALLBACK_LLM_TIMEOUT_SEC 讀、可調

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """
        Args:
            base_url: Ollama server URL。None 從 SIRO_FALLBACK_LLM_BASE_URL env 讀
                      （預設 http://localhost:11434）
            model: Ollama model 名稱。None 從 SIRO_FALLBACK_LLM_MODEL env 讀
                   （預設 llama3.2:3b-instruct-q4_0）
            timeout: 單次對話 timeout（秒）。None 用 DEFAULT_TIMEOUT=15s
        """
        self.base_url = (base_url or os.environ.get(
            "SIRO_FALLBACK_LLM_BASE_URL", "http://localhost:11434"
        )).rstrip("/")
        self.model = model or os.environ.get(
            "SIRO_FALLBACK_LLM_MODEL", "llama3.2:3b-instruct-q4_0"
        )
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT

        # v0.3 is_available cache — 5s TTL 拿掉 hot path sync urllib
        # 跟 HermesClient 一致，Ollama 狀態也不會每秒變
        self._avail_cache_ts: float = 0.0
        self._avail_cache_result: bool = False
        self._avail_cache_ttl: float = 5.0

    def is_available(self) -> bool:
        """檢查 Ollama server 是否活著

        v0.3 改：5s TTL cache（理由同 HermesClient）。
        """
        import time
        now = time.time()
        if now - self._avail_cache_ts < self._avail_cache_ttl:
            return self._avail_cache_result

        # cache miss — 真的去問 Ollama
        try:
            url = f"{self.base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                self._avail_cache_result = resp.status == 200
        except Exception as e:
            logger.debug(f"Ollama 不可用: {type(e).__name__}: {e}")
            self._avail_cache_result = False
        self._avail_cache_ts = now
        return self._avail_cache_result

    def chat(self, message: str, system_prompt: Optional[str] = None) -> OllamaResult:
        """
        跑一次 Ollama 對話。

        Args:
            message: 使用者訊息
            system_prompt: 系統提示詞（會合併到 prompt 開頭）

        Returns:
            OllamaResult: 包含輸出文字、錯誤、執行時間
        """
        # 合併 system_prompt 與 message（Ollama 沒有原生 system role，
        # 把 system 拼到 user 訊息前面最簡單也最通用）
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{message}"
        else:
            full_prompt = message

        # Ollama /api/generate 格式
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
        }

        url = f"{self.base_url}/api/generate"
        data = json.dumps(payload).encode("utf-8")

        start = time.time()
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                result = json.loads(body)
                output = result.get("response", "").strip()

            duration_ms = int((time.time() - start) * 1000)
            return OllamaResult(
                success=bool(output),
                output=output,
                error=None if output else "Ollama 回傳空字串",
                duration_ms=duration_ms,
            )

        except urllib.error.URLError as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"Ollama 連線失敗: {e}")
            return OllamaResult(
                success=False,
                output="",
                error=f"Ollama 連線失敗: {e}",
                duration_ms=duration_ms,
            )
        except urllib.error.HTTPError as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"Ollama HTTP {e.code}: {e.reason}")
            return OllamaResult(
                success=False,
                output="",
                error=f"Ollama HTTP {e.code}: {e.reason}",
                duration_ms=duration_ms,
            )
        except json.JSONDecodeError as e:
            return OllamaResult(
                success=False,
                output="",
                error=f"Ollama 回傳非 JSON: {e}",
            )
        except Exception as e:
            logger.exception("Ollama 未預期錯誤")
            return OllamaResult(
                success=False,
                output="",
                error=f"未預期錯誤: {e}",
            )
