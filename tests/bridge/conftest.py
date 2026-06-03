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
