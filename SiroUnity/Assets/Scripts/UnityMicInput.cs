// UnityMicInput.cs — Phase 2 STT always-on mic
// 對應 design: docs/STT_INTEGRATION.md §`SiroUnity/Assets/Scripts/UnityMicInput.cs`
//
// 設計:
// - Unity Microphone API 啟動 + 1s loop buffer
// - Coroutine CaptureLoop 32ms 切 chunk → 16-bit PCM → SendMicChunkAsync
// - 訂閱 OnBridgeVadPause / OnBridgeVadResume 觸發 AEC + visual
// - turnIdCounter monotonic(每個 chunk +1)
//
// 注意:Unity Mic 啟動需要 player 權限(Windows 通常自動、macOS/iOS 要 prompt)

using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace Siro
{
    /// <summary>
    /// Always-on 麥克風擷取 → 32ms chunks 送 bridge SileroVAD
    /// </summary>
    [DisallowMultipleComponent]
    public class UnityMicInput : MonoBehaviour
    {
        [Header("References")]
        public HermesBridgeClient bridge;        // WS client
        public UnityTTSPlayer ttsPlayer;          // (optional)觸發 AEC ducking

        [Header("Audio Settings")]
        [Tooltip("取樣率,固定 16kHz(對齊 Silero VAD)")]
        public int sampleRate = 16000;
        [Tooltip("每個 chunk 的 ms,32ms = 512 samples @ 16kHz(對齊 O-LLVT + Silero)")]
        public int chunkMs = 32;
        [Tooltip("Microphone loop buffer 長度,1 秒夠 capture loop 用")]
        public int micBufferSeconds = 1;

        [Header("Visual Feedback (optional)")]
        [Tooltip("mic 狀態 ring 圖示(可選,沒設就跳過)")]
        public Image ringImage;
        public Color idleColor = new Color(0.5f, 0.5f, 0.5f, 0.3f);       // 灰
        public Color listeningColor = new Color(0.2f, 0.8f, 0.2f, 0.6f);  // 綠(VAD 偵測到 speech)
        public Color errorColor = new Color(0.8f, 0.2f, 0.2f, 0.6f);      // 紅(mic 沒起)

        [Header("Debug")]
        public bool verboseLogging = false;

        // 內部 state
        private AudioClip _micClip;
        private string _device;
        private int _lastSamplePos;
        private bool _isRecording;
        private Coroutine _captureLoop;
        private int _turnIdCounter = 0;
        // Phase 2 STT (Day 8 fix):整段 mic 期間共用一個 utterance_turn_id
        // mic 啟動時 ++ 一次,所有 chunk 都帶這個 id。
        // 修原 bug:CaptureLoop 每 32ms NextTurnId() 會讓 _currentTurnId 一直跳
        // → bridge 推回來的 tts_audio (用 pause 時的 turn_id) 跟 Unity 已經是 +30 的 _currentTurnId 不符 → 永遠被 drop
        private int _utteranceTurnId = 0;
        private int _chunkSeqCounter = 0;

        public enum MicState { Idle, Listening, SpeechDetected, Error }
        public MicState state { get; private set; } = MicState.Idle;

        // ============================================================
        // Unity lifecycle
        // ============================================================

        private void Start()
        {
            if (bridge == null)
            {
                Debug.LogError("[MicInput] bridge 參考未設");
                state = MicState.Error;
                UpdateRingColor();
                return;
            }

            // 訂閱 VAD events
            bridge.OnBridgeVadPause += HandleVadPause;
            bridge.OnBridgeVadResume += HandleVadResume;

            StartMic();
        }

        private void OnDestroy()
        {
            StopMic();
            if (bridge != null)
            {
                bridge.OnBridgeVadPause -= HandleVadPause;
                bridge.OnBridgeVadResume -= HandleVadResume;
            }
        }

        // ============================================================
        // Public API
        // ============================================================

        /// <summary>Unity 端產的 turn_id counter(對齊 chat box 文字輸入用)。</summary>
        public int LocalTurnIdCounter => _turnIdCounter;

        /// <summary>取得下一個 turn_id 並遞增(供 ChatInputUI 等其他元件同步用)。</summary>
        public int NextTurnId()
        {
            _turnIdCounter++;
            return _turnIdCounter;
        }

        /// <summary>外部設定 turn_id(例如 ChatInputUI 用了某個 id、後續 mic 從這接續)。</summary>
        public void SyncTurnIdCounter(int value)
        {
            if (value > _turnIdCounter) _turnIdCounter = value;
        }

        public void StartMic()
        {
            if (_isRecording) return;
            if (Microphone.devices == null || Microphone.devices.Length == 0)
            {
                Debug.LogError("[MicInput] No microphone device — mic 沒起");
                state = MicState.Error;
                UpdateRingColor();
                return;
            }

            // Day 8 fix:mic 啟動時遞增 1 個 utterance_turn_id
            // 之後所有 mic chunk 共用這個 id,直到下次 StartMic
            // (跟 ChatInputUI 的 NextTurnId 共用同一個 _turnIdCounter)
            _utteranceTurnId = NextTurnId();
            _chunkSeqCounter = 0;

            _device = Microphone.devices[0];
            try
            {
                _micClip = Microphone.Start(_device, true, micBufferSeconds, sampleRate);
            }
            catch (Exception e)
            {
                Debug.LogError($"[MicInput] Microphone.Start 失敗: {e.Message}");
                state = MicState.Error;
                UpdateRingColor();
                return;
            }

            if (_micClip == null)
            {
                Debug.LogError("[MicInput] Microphone.Start 回傳 null — driver 不支援?");
                state = MicState.Error;
                UpdateRingColor();
                return;
            }

            _isRecording = true;
            _lastSamplePos = 0;
            state = MicState.Idle;
            UpdateRingColor();
            _captureLoop = StartCoroutine(CaptureLoop());
            Debug.Log($"[MicInput] started: device={_device} sampleRate={sampleRate}");
        }

        public void StopMic()
        {
            if (!_isRecording) return;
            try
            {
                Microphone.End(_device);
            }
            catch (Exception) { /* ignore */ }
            if (_captureLoop != null)
            {
                StopCoroutine(_captureLoop);
                _captureLoop = null;
            }
            _isRecording = false;
            state = MicState.Idle;
            UpdateRingColor();
            Debug.Log("[MicInput] stopped");
        }

        // ============================================================
        // Capture loop:32ms chunk 送 bridge
        // ============================================================

        private IEnumerator CaptureLoop()
        {
            int chunkSamples = sampleRate * chunkMs / 1000;  // 512 @ 16kHz 32ms
            float[] buffer = new float[chunkSamples];

            while (_isRecording)
            {
                if (Microphone.IsRecording(_device))
                {
                    int pos = Microphone.GetPosition(_device);
                    if (pos < _lastSamplePos) _lastSamplePos = 0;  // wrapped around

                    int available = pos - _lastSamplePos;
                    if (available >= chunkSamples)
                    {
                        _micClip.GetData(buffer, _lastSamplePos);
                        _lastSamplePos += chunkSamples;

                        // float [-1, 1] → 16-bit PCM bytes
                        byte[] pcm = FloatToPcm16(buffer);

                        // Day 8 fix:整段 mic 期間共用 _utteranceTurnId(不每 chunk ++)
                        // chunk_seq 給 bridge 內部 trace 用(可選)
                        _chunkSeqCounter++;
                        // fire-and-forget:不要 await capture loop
                        _ = bridge.SendMicChunkAsync(_utteranceTurnId, pcm);
                    }
                    else
                    {
                        yield return null;  // 還沒 32ms
                    }
                }
                else
                {
                    Debug.LogWarning("[MicInput] mic stopped unexpectedly");
                    state = MicState.Error;
                    UpdateRingColor();
                    yield break;
                }
            }
        }

        // ============================================================
        // VAD event handlers
        // ============================================================

        private void HandleVadPause(BridgeVadPause evt)
        {
            if (verboseLogging) Debug.Log($"[MicInput] vad_pause turn_id={evt.turn_id}");

            // Phase 2 STT:同步 TTSPlayer 的 current_turn_id
            // → 立即停舊 TTS + 清 queue(barge-in flow)
            if (ttsPlayer != null) ttsPlayer.SetCurrentTurnId(evt.turn_id);

            // AEC:降 TTS 音量避免 echo
            if (ttsPlayer != null) ttsPlayer.DuckVolume(true);

            state = MicState.SpeechDetected;
            UpdateRingColor();
        }

        private void HandleVadResume(BridgeVadResume evt)
        {
            if (verboseLogging) Debug.Log(
                $"[MicInput] vad_resume turn_id={evt.turn_id} duration={evt.duration_ms}ms"
            );

            // AEC:0.5s grace 後恢復 TTS 音量
            if (ttsPlayer != null) ttsPlayer.DuckVolume(false);

            state = MicState.Listening;
            UpdateRingColor();
        }

        // ============================================================
        // Utilities
        // ============================================================

        private void UpdateRingColor()
        {
            if (ringImage == null) return;
            Color c = idleColor;
            if (state == MicState.SpeechDetected) c = listeningColor;
            else if (state == MicState.Error) c = errorColor;
            ringImage.color = c;
        }

        /// <summary>float [-1, 1] → 16-bit PCM bytes(little-endian)</summary>
        private static byte[] FloatToPcm16(float[] floats)
        {
            byte[] bytes = new byte[floats.Length * 2];
            for (int i = 0; i < floats.Length; i++)
            {
                short s = (short)(Mathf.Clamp(floats[i], -1f, 1f) * 32767f);
                bytes[i * 2] = (byte)(s & 0xff);
                bytes[i * 2 + 1] = (byte)((s >> 8) & 0xff);
            }
            return bytes;
        }
    }
}
