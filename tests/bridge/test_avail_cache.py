"""
tests/bridge/test_avail_cache.py - v0.3 is_available 5s TTL cache 測試

動機：v0.2 之前 is_available() 在 async path 同步跑，每次 request
額外卡 0.5-10s（hermes subprocess）or 3s（Ollama urllib）。
100 個 request 進來就有 100 次重複檢查。

v0.3 加 5s TTL cache，100 個 request 5s 內只查 1 次。
"""

from __future__ import annotations

import subprocess
import time
from unittest.mock import patch, MagicMock

import pytest

from bridge.hermes_client import HermesClient
from bridge.ollama_client import OllamaClient


# ==================== HermesClient ====================

class TestHermesIsAvailableCache:
    def test_first_call_invokes_subprocess(self, tmp_path):
        """第一次呼叫會真的跑 subprocess"""
        fake_hermes = tmp_path / "fake_hermes.sh"
        fake_hermes.write_text("#!/bin/sh\necho v0.0.0\n")
        fake_hermes.chmod(0o755)

        client = HermesClient(binary_path=str(fake_hermes))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert client.is_available() is True
            assert mock_run.call_count == 1

    def test_cache_hit_skips_subprocess_within_ttl(self, tmp_path):
        """5s 內重複呼叫只跑 1 次 subprocess"""
        fake_hermes = tmp_path / "fake_hermes.sh"
        fake_hermes.write_text("#!/bin/sh\necho v0.0.0\n")

        client = HermesClient(binary_path=str(fake_hermes))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # 5s 內 5 次呼叫
            for _ in range(5):
                assert client.is_available() is True
            assert mock_run.call_count == 1, f"預期 1 次 subprocess，跑了 {mock_run.call_count} 次"

    def test_cache_expires_after_ttl(self, tmp_path):
        """超過 TTL 後 cache 失效，會再跑一次"""
        fake_hermes = tmp_path / "fake_hermes.sh"
        fake_hermes.write_text("#!/bin/sh\necho v0.0.0\n")

        client = HermesClient(binary_path=str(fake_hermes))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert client.is_available() is True  # 第 1 次
            # 模擬時間過 6 秒
            future_ts = client._avail_cache_ts + 6.0
            with patch("time.time", return_value=future_ts):
                assert client.is_available() is True  # 第 2 次（cache expired）
            assert mock_run.call_count == 2, f"預期 2 次，跑了 {mock_run.call_count} 次"

    def test_cache_stores_failure_too(self, tmp_path):
        """失敗結果也會被 cache 住（避免每次都重試連死的 subprocess）"""
        fake_hermes = tmp_path / "fake_hermes.sh"
        fake_hermes.write_text("#!/bin/sh\necho v0.0.0\n")

        client = HermesClient(binary_path=str(fake_hermes))
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("not found")
            assert client.is_available() is False  # 第 1 次（失敗 cache）
            for _ in range(4):
                assert client.is_available() is False  # cache hit
            assert mock_run.call_count == 1

    def test_ttl_is_5_seconds(self, tmp_path):
        """預設 TTL 是 5 秒（防止有人改壞）"""
        fake_hermes = tmp_path / "fake_hermes.sh"
        fake_hermes.write_text("#!/bin/sh\necho v0.0.0\n")
        client = HermesClient(binary_path=str(fake_hermes))
        assert client._avail_cache_ttl == 5.0


# ==================== OllamaClient ====================

class TestOllamaIsAvailableCache:
    def test_first_call_invokes_http(self):
        client = OllamaClient(base_url="http://fake:11434")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = MagicMock(return_value=MagicMock(status=200))
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            assert client.is_available() is True
            assert mock_urlopen.call_count == 1

    def test_cache_hit_skips_http_within_ttl(self):
        client = OllamaClient(base_url="http://fake:11434")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = MagicMock(return_value=MagicMock(status=200))
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            for _ in range(10):
                assert client.is_available() is True
            assert mock_urlopen.call_count == 1

    def test_ttl_is_5_seconds(self):
        client = OllamaClient(base_url="http://fake:11434")
        assert client._avail_cache_ttl == 5.0

    def test_cache_stores_failure_too(self):
        client = OllamaClient(base_url="http://fake:11434")
        with patch("urllib.request.urlopen", side_effect=Exception("refused")):
            assert client.is_available() is False
            # 5s 內 10 次
            with patch("urllib.request.urlopen", side_effect=Exception("refused")):
                for _ in range(10):
                    assert client.is_available() is False


# ==================== 整合：兩個 client 互不影響 ====================

class TestClientsCacheIsolation:
    """HermesClient 跟 OllamaClient 各自的 cache 不互相干擾"""

    def test_hermes_available_does_not_cache_ollama(self):
        hermes = HermesClient(binary_path="/nonexistent")
        ollama = OllamaClient(base_url="http://fake:11434")

        # Hermes fail（檔案不存在）— cache False
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert hermes.is_available() is False

        # Ollama 應該還是獨立查詢
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = MagicMock(return_value=MagicMock(status=200))
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            assert ollama.is_available() is True
