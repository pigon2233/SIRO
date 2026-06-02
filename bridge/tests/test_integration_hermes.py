"""
bridge/tests/test_integration_hermes.py

整合測試：bridge 跟真 Hermes 之間的通訊。
會跳過如果 hermes 沒裝，CI 不會壞。
"""

import os
import shutil
import time

import pytest

from bridge.hermes_client import HermesClient


# 找 hermes binary
HERMES_BIN_CANDIDATES = [
    os.environ.get("HERMES_BIN_PATH"),
    os.environ.get("HERMES_BIN"),
    os.path.expanduser("~/hermes-agent/.venv/Scripts/hermes.exe"),
    os.path.expanduser("~/hermes-agent/.venv/bin/hermes"),
    shutil.which("hermes"),
    os.path.expanduser("~/.local/bin/hermes"),
]


def find_hermes():
    for c in HERMES_BIN_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    return None


HAS_HERMES = find_hermes() is not None


@pytest.mark.skipif(not HAS_HERMES, reason="Hermes not installed")
class TestRealHermesIntegration:
    """真的跟 hermes CLI 對話"""

    def setup_method(self):
        self.hermes_path = find_hermes()
        self.client = HermesClient(binary_path=self.hermes_path, timeout=120)

    def test_hermes_version(self):
        version = self.client.get_version()
        assert version is not None
        assert "Hermes" in version

    def test_hermes_basic_chat(self):
        """最簡單的對話"""
        result = self.client.chat("Say 'hello' and nothing else")
        assert result.success, f"chat failed: {result.error}"
        assert "hello" in result.output.lower()

    def test_hermes_chat_with_chinese(self):
        """中文 prompt 應該能跑（不一定要回中文）"""
        result = self.client.chat("你好嗎？用一個字回答")
        assert result.success, f"chat failed: {result.error}"
        # 不要硬性要求內容，只是要能跑完

    def test_hermes_chat_duration_recorded(self):
        """duration 應該有被記錄"""
        result = self.client.chat("hi")
        assert result.duration_ms is not None
        assert result.duration_ms > 0

    @pytest.mark.slow
    @pytest.mark.skip(reason="跟 FastAPI lifespan 互動有複雜性，unit test 已覆蓋")
    def test_hermes_chat_through_bridge_api(self):
        """透過 bridge API 走完整鏈路（慢，跑完整個 FastAPI + Hermes）

        註：這個 case 因為跟 FastAPI lifespan 互動的複雜性，暫時跳過。
        test_main.py 已經有完整的單元測試覆蓋 API 行為。
        真實 E2E 測試建議用 scripts/test-bridge-e2e.sh 之類的 curl 腳本。
        """
        pass
