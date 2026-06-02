"""
bridge/tests/test_hermes_client.py
"""

import subprocess

import pytest
from unittest.mock import patch, MagicMock

from bridge.hermes_client import HermesClient, HermesResult


class TestHermesClientResolveBinary:
    def test_explicit_binary_path(self, tmp_path):
        """明確指定路徑時，應該直接用"""
        fake_bin = tmp_path / "fake_hermes"
        fake_bin.write_text("#!/bin/sh\necho v0.0.0\n")
        client = HermesClient(binary_path=str(fake_bin))
        assert client.binary_path == str(fake_bin)

    def test_explicit_path_can_be_nonexistent(self):
        """明確指定不存在路徑時，build 不 raise（is_available 會回報）"""
        client = HermesClient(binary_path="/nonexistent/hermes")
        assert client.binary_path == "/nonexistent/hermes"

    def test_falls_back_to_env_var(self, monkeypatch, tmp_path):
        """環境變數 HERMES_BIN_PATH 設定時優先用"""
        fake_bin = tmp_path / "env_hermes"
        fake_bin.write_text("#!/bin/sh\n")
        monkeypatch.setenv("HERMES_BIN_PATH", str(fake_bin))
        client = HermesClient()
        assert client.binary_path == str(fake_bin)

    def test_falls_back_to_which(self, monkeypatch, tmp_path):
        """PATH 上找得到時用 which"""
        fake_bin = tmp_path / "hermes"
        fake_bin.write_text("#!/bin/sh\n")
        monkeypatch.setattr("shutil.which", lambda x: str(fake_bin) if x == "hermes" else None)
        client = HermesClient()
        assert client.binary_path == str(fake_bin)

    def test_falls_back_to_default_path(self, monkeypatch, tmp_path):
        """PATH 上找不到時，fallback 到 ~/.local/bin/hermes"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        default = tmp_path / ".local" / "bin" / "hermes"
        default.parent.mkdir(parents=True)
        default.write_text("#!/bin/sh\n")
        client = HermesClient()
        assert client.binary_path == str(default)

    def test_fallback_to_hermes_string(self, monkeypatch, tmp_path):
        """都找不到時，回傳 'hermes' 字串（執行會失敗但 build 不 raise）"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        client = HermesClient()
        assert client.binary_path == "hermes"


class TestHermesClientIsAvailable:
    @patch("bridge.hermes_client.subprocess.run")
    def test_available_when_version_works(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="v0.15.2", stderr="")
        client = HermesClient(binary_path="/fake/hermes")
        assert client.is_available() is True

    @patch("bridge.hermes_client.subprocess.run")
    def test_unavailable_when_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        client = HermesClient(binary_path="/fake/hermes")
        assert client.is_available() is False

    @patch("bridge.hermes_client.subprocess.run", side_effect=FileNotFoundError)
    def test_unavailable_when_binary_missing(self, mock_run):
        client = HermesClient(binary_path="/fake/hermes")
        assert client.is_available() is False

    @patch("bridge.hermes_client.subprocess.run", side_effect=Exception("boom"))
    def test_unavailable_on_unexpected_error(self, mock_run):
        client = HermesClient(binary_path="/fake/hermes")
        assert client.is_available() is False


class TestHermesClientChat:
    @patch("bridge.hermes_client.subprocess.run")
    def test_chat_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[emotion:happy] 你好！",
            stderr="",
        )
        client = HermesClient(binary_path="/fake/hermes", timeout=30)
        result = client.chat("hi")
        assert result.success is True
        assert "[emotion:happy] 你好！" in result.output
        assert result.exit_code == 0
        assert result.duration_ms is not None

    @patch("bridge.hermes_client.subprocess.run")
    def test_chat_nonzero_exit_returns_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout="",
            stderr="some error",
        )
        client = HermesClient(binary_path="/fake/hermes")
        result = client.chat("hi")
        assert result.success is False
        assert "some error" in (result.error or "")

    @patch("bridge.hermes_client.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=60))
    def test_chat_timeout(self, mock_run):
        client = HermesClient(binary_path="/fake/hermes", timeout=60)
        result = client.chat("hi")
        assert result.success is False
        assert "timeout" in (result.error or "").lower()
