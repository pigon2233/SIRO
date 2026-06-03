"""
tests/bridge/test_ollama_client.py - OllamaClient 單元測試

測 urllib.request 為基底的本地 LLM client。
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from bridge.ollama_client import OllamaClient, OllamaResult


# ==================== 初始化 / 設定 ====================

class TestInit:
    """測初始化預設值 + env 讀取"""

    def test_default_base_url_and_model(self, clean_env):
        c = OllamaClient()
        assert c.base_url == "http://localhost:11434"
        assert c.model == "llama3.2:3b-instruct-q4_0"
        assert c.timeout == 15  # 預設 15s

    def test_env_override(self, clean_env):
        clean_env.setenv("SIRO_FALLBACK_LLM_BASE_URL", "http://gpu-box:11434")
        clean_env.setenv("SIRO_FALLBACK_LLM_MODEL", "llama3.1:8b")
        c = OllamaClient()
        assert c.base_url == "http://gpu-box:11434"
        assert c.model == "llama3.1:8b"

    def test_trailing_slash_stripped(self):
        c = OllamaClient(base_url="http://localhost:11434/")
        assert c.base_url == "http://localhost:11434"

    def test_explicit_args(self):
        c = OllamaClient(
            base_url="http://x:1234",
            model="custom:7b",
            timeout=42,
        )
        assert c.base_url == "http://x:1234"
        assert c.model == "custom:7b"
        assert c.timeout == 42


# ==================== is_available ====================

class TestIsAvailable:
    """測 Ollama server 存活檢查"""

    @patch("bridge.ollama_client.urllib.request.urlopen")
    def test_available_when_200(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = OllamaClient()
        assert c.is_available() is True

    @patch("bridge.ollama_client.urllib.request.urlopen", side_effect=Exception("refused"))
    def test_unavailable_on_exception(self, mock_urlopen):
        c = OllamaClient()
        assert c.is_available() is False


# ==================== chat ====================

class TestChat:
    """測 Ollama 對話主路徑"""

    @patch("bridge.ollama_client.urllib.request.urlopen")
    def test_chat_success(self, mock_urlopen):
        # mock 回應
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "response": "[emotion:happy] 你好",
            "done": True,
        }).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = OllamaClient(base_url="http://fake:11434", model="test:1b")
        result = c.chat("hi")
        assert result.success is True
        assert result.output == "[emotion:happy] 你好"
        assert result.error is None
        assert result.duration_ms is not None and result.duration_ms >= 0

    @patch("bridge.ollama_client.urllib.request.urlopen")
    def test_chat_empty_response_fails(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "", "done": True}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = OllamaClient()
        result = c.chat("hi")
        assert result.success is False
        assert "空字串" in (result.error or "")

    @patch("bridge.ollama_client.urllib.request.urlopen")
    def test_chat_includes_system_prompt(self, mock_urlopen):
        """system_prompt 應該被合併進 prompt"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "ok"}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = OllamaClient()
        c.chat("user msg", system_prompt="sys prompt")

        # 抓 urlopen 收到的 Request 物件
        request_obj = mock_urlopen.call_args.args[0]
        body = json.loads(request_obj.data.decode("utf-8"))
        assert "sys prompt" in body["prompt"]
        assert "user msg" in body["prompt"]
        assert body["model"] == c.model
        assert body["stream"] is False

    @patch("bridge.ollama_client.urllib.request.urlopen", side_effect=ConnectionError("refused"))
    def test_chat_connection_error_returns_failure(self, mock_urlopen):
        c = OllamaClient()
        result = c.chat("hi")
        assert result.success is False
        assert "連線失敗" in (result.error or "") or "refused" in (result.error or "")

    @patch("bridge.ollama_client.urllib.request.urlopen")
    def test_chat_invalid_json_returns_failure(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json{"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        c = OllamaClient()
        result = c.chat("hi")
        assert result.success is False
        assert "非 JSON" in (result.error or "")


# ==================== Result 型別 ====================

class TestOllamaResult:
    def test_construction(self):
        r = OllamaResult(success=True, output="ok", duration_ms=42)
        assert r.success is True
        assert r.output == "ok"
        assert r.error is None
        assert r.duration_ms == 42
