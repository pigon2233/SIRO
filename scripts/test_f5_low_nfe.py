"""test F5-TTS with nfe_step=8 (low) to check if it's VRAM/OOM issue"""
import sys
sys.path.insert(0, r"C:\coconut chennel\SIRO")
import time

t0 = time.time()
def log(msg):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

log("importing F5TTS...")
from f5_tts.api import F5TTS
log("F5TTS imported")

log("instantiating F5TTS()...")
try:
    f5 = F5TTS()
    log("F5TTS() done")
except Exception as e:
    log(f"F5TTS() failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check VRAM
try:
    import torch
    if torch.cuda.is_available():
        log(f"CUDA available: {torch.cuda.device_count()} devices")
        for i in range(torch.cuda.device_count()):
            free, total = torch.cuda.mem_get_info(i)
            log(f"  GPU {i} {torch.cuda.get_device_name(i)}: {free/1024**3:.2f}GB free / {total/1024**3:.2f}GB total")
except Exception as e:
    log(f"torch.cuda check failed: {e}")

ref_audio = r"C:\coconut chennel\SIRO\models\f5_tts\refs\mao_zh.wav"
ref_text = "你好,我是 Mao,接下來會用這個聲音跟你說話。"
gen_text = "你好,測試聲音。"

for nfe_step in [8, 16]:
    log(f"=== nfe_step={nfe_step} ===")
    try:
        wav, sr, _ = f5.infer(
            ref_file=ref_audio,
            ref_text=ref_text,
            gen_text=gen_text,
            speed=1.0,
            nfe_step=nfe_step,
            cfg_strength=2.0,
        )
        log(f"  infer done, wav shape={wav.shape}, sr={sr}")
    except Exception as e:
        log(f"  infer failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        continue

log("done")
