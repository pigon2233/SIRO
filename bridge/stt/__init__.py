"""bridge.stt — Speech-to-Text(Phase 2 STT)。

對應 design: docs/STT_INTEGRATION.md §`bridge/stt/faster_whisper_asr.py`。

SIRO 採用 faster-whisper(CTranslate2 加速版 whisper,MIT)。
支援 auto language detect + persona hint language + async 包裝避免 block event loop。
"""

from .asr_interface import ASRInterface
from .faster_whisper_asr import FasterWhisperAsr, AsrResult

__all__ = ["ASRInterface", "FasterWhisperAsr", "AsrResult"]
