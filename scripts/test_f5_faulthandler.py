"""catch native crash with faulthandler"""
import faulthandler
faulthandler.enable()
import sys
import time

t0 = time.time()
def log(msg):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

log("import torch OK already")
log("now: import f5_tts.infer.utils_infer")
import f5_tts.infer.utils_infer
log("DONE - utils_infer imported successfully")
