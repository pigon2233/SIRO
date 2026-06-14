"""
tests/bridge/conftest.py - 測試 fixtures

提供：
- 載入 bridge 模組乾淨環境（清掉 sys.modules cache 避免互相干擾）
- emotion_parser / prompts / models 預先實例化
- 不打真網路 / 真 subprocess（所有 LLM client 都用 mock）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# 確保 repo root 在 sys.path 最前面（讓 `from bridge.xxx` 找得到）
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def repo_root() -> Path:
    """repo 根目錄"""
    return _REPO_ROOT


@pytest.fixture
def bridge_dir(repo_root: Path) -> Path:
    """bridge 模組目錄"""
    return repo_root / "bridge"


@pytest.fixture
def clean_env(monkeypatch):
    """清掉 SIRO_* env vars 避免測試互相污染

    每個 test 拿到的都是隔離的環境。要寫 env 就用 monkeypatch.setenv。
    """
    siro_vars = [k for k in os.environ if k.startswith("SIRO_") or k.startswith("HERMES_LLM_")]
    for k in siro_vars:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


# ============================================================
# v1.5.3 FakeOsRuntimeClient fixture
# ============================================================
# 給所有 v15 tool 測試用、避免需要真的 siro-runtime 跟 gRPC stubs
# 從 test_os_runtime_client.py 拿 FakeOsRuntimeClient class
from .test_os_runtime_client import FakeOsRuntimeClient  # noqa: E402


@pytest.fixture
def fake_os_runtime_client(monkeypatch, tmp_path):
    """v1.5.3 os-runtime gRPC client mock

    給 filesystem.py / shell.py 工具的測試用
    - filesystem / shell 用 lazy import `from .os_runtime_client import get_os_runtime_client`
      所以只要 patch 來源 module `bridge.tools.os_runtime_client.get_os_runtime_client` 就好
    - 自動建 sandbox tmpdir
    """
    sandbox = tmp_path / "siro_sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    fake = FakeOsRuntimeClient(sandbox)

    def _get_fake():
        return fake

    # 預先 import os_runtime_client、確保 sys.modules 有它
    import bridge.tools.os_runtime_client as _orc
    monkeypatch.setattr(_orc, "get_os_runtime_client", _get_fake)

    # filesystem / shell 有 top-level `from . import os_runtime_client`、
    # 所以 `bridge.tools.filesystem.os_runtime_client` 跟 `bridge.tools.shell.os_runtime_client`
    # 都是 module attribute、可以 patch
    import bridge.tools.filesystem as _fs
    import bridge.tools.shell as _sh
    monkeypatch.setattr(_fs.os_runtime_client, "get_os_runtime_client", _get_fake)
    monkeypatch.setattr(_sh.os_runtime_client, "get_os_runtime_client", _get_fake)

    yield fake
