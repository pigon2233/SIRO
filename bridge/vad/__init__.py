"""bridge.vad — Voice Activity Detection (Phase 2 STT).

對應 design: docs/STT_INTEGRATION.md §`bridge/vad/silero.py` Pattern 1。

SIRO 採用 Silero VAD v6(`silero_vad` PyPI package)。內建 VADIterator 已經包了
state machine,我們再包一層 dB gate + pre-buffer + VadEvent API,讓 caller 收到
清楚的 PAUSE / RESUME 事件 + 對應的 turn_id + audio bytes。
"""

from .vad_interface import VADInterface
from .silero import SileroVAD, SileroVADConfig, VadEvent, VadEventType

__all__ = [
    "VADInterface",
    "SileroVAD",
    "SileroVADConfig",
    "VadEvent",
    "VadEventType",
]
