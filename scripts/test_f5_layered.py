"""narrow down where f5_tts import crashes"""
import sys
import time

t0 = time.time()
def log(msg):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

log("step 1: import torch")
try:
    import torch
    log(f"  torch={torch.__version__}, cuda available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            log(f"  GPU {i}: {torch.cuda.get_device_name(i)}")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

log("step 2: import transformers")
try:
    import transformers
    log(f"  transformers={transformers.__version__}")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

log("step 3: import jieba / pypinyin")
try:
    import jieba
    import pypinyin
    log("  jieba + pypinyin OK")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

log("step 4: import vocos")
try:
    import vocos
    log(f"  vocos OK")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

log("step 5: import soundfile")
try:
    import soundfile
    log(f"  soundfile={soundfile.__version__}")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

log("step 6: import f5_tts")
try:
    import f5_tts
    log(f"  f5_tts module={f5_tts.__file__}")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

log("step 7: from f5_tts.api import F5TTS")
try:
    from f5_tts.api import F5TTS
    log(f"  F5TTS class loaded")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

log("step 8: F5TTS() instantiate")
try:
    f5 = F5TTS()
    log(f"  F5TTS() done")
except Exception as e:
    log(f"  FAIL: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

log("ALL OK")
