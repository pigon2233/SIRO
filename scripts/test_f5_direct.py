"""test F5-TTS directly, see actual error"""
import sys
sys.path.insert(0, r"C:\coconut chennel\SIRO")
import time

t0 = time.time()
print(f"[{time.time()-t0:.1f}s] importing F5TTS...")
from f5_tts.api import F5TTS
print(f"[{time.time()-t0:.1f}s] F5TTS imported")

print(f"[{time.time()-t0:.1f}s] instantiating F5TTS()...")
try:
    f5 = F5TTS()
    print(f"[{time.time()-t0:.1f}s] F5TTS() done")
except Exception as e:
    print(f"[{time.time()-t0:.1f}s] F5TTS() failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

ref_audio = r"C:\coconut chennel\SIRO\models\f5_tts\refs\mao_zh.wav"
ref_text = "你好,我是 Mao,接下來會用這個聲音跟你說話。"
gen_text = "你好,我是 Mao,今天天氣真好。"

print(f"[{time.time()-t0:.1f}s] starting infer()...")
try:
    wav, sr, spec = f5.infer(
        ref_file=ref_audio,
        ref_text=ref_text,
        gen_text=gen_text,
        speed=1.0,
        nfe_step=32,
        cfg_strength=2.0,
    )
    print(f"[{time.time()-t0:.1f}s] infer() done, wav shape={wav.shape}, sr={sr}")
except Exception as e:
    print(f"[{time.time()-t0:.1f}s] infer() failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
