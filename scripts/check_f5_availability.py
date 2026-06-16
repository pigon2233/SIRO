"""check F5-TTS is_available() in dev env"""
import sys
sys.path.insert(0, r"C:\coconut chennel\SIRO")
import asyncio
from bridge.tts.f5_tts import F5TTSProvider

p = F5TTSProvider()
print("refs_dir:", p.refs_dir)
print("exists:", p.refs_dir.exists())
print("is_available:", asyncio.run(p.is_available()))

# Also try edge-tts path
from bridge.tts.edge_tts import EdgeTTSProvider
e = EdgeTTSProvider()
print("edge is_available:", asyncio.run(e.is_available()))
