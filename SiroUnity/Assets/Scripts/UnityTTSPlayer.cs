// unity/Assets/Scripts/UnityTTSPlayer.cs
//
// v1.0 Core Experience Phase 1: Unity 端 TTS 播放
//
// 設計:主動打 bridge /tts/synthesize API、拿到 base64 mp3 → 轉 AudioClip → 播放。
// Phase 1.5 polish 會改成「LLM streaming sentence-level trigger」(降 TTFB)。
//
// 用法:
// 1. 掛在一個有空 GameObject 上
// 2. Inspector 設 audioSource (AudioSource component)
// 3. 訂閱 HermesBridgeClient.OnBridgeResponse event
// 4. 收到 response 時自動觸發 TTS
//
// 可選:
// - 訂閱 PersonaManager.OnPersonaChanged 自動重載 voice config
// - 訂閱 ChatInputUI 收到 user 訊息時不要 TTS(自己講話自己不必複頌)
//
// Phase 1.5.2b: 訂閱 HermesBridgeClient.OnBridgeTtsAudio 支援「句子級 TTS streaming」
// - bridge 端 SIRO_TTS_STREAMING=true 時推 {"type":"tts_audio","index":N,"audio_base64":"..."}
// - Unity 收到後按 index 排隊、依序播放(WS 雖然 in-order 但 TTS 完成時間不固定)
// - 沒開 streaming 時(預設)走原本 Speak() → /tts/synthesize 整段流程
//

using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Siro
{
    [RequireComponent(typeof(AudioSource))]
    public class UnityTTSPlayer : MonoBehaviour
    {
        [Header("References")]
        public HermesBridgeClient bridge;
        public AudioSource audioSource;
        public ChatInputUI chatInputUI;       // 可選:不 TTS 自己的訊息
        public PersonaManager personaManager; // 可選:persona 切換時自動重載 voice

        [Header("Behavior")]
        [Tooltip("收到 bridge response 時自動觸發 TTS")]
        public bool autoSpeak = true;
        [Tooltip("Mute on start (用戶可隨時按按鈕取消)")]
        public bool muted = false;
        [Tooltip("TTS API timeout (秒)。edge-tts < 5s;F5-TTS 第一次 cold start 145s(RTX 3050 4GB)+ 後續推論 5-10s/句,設 180s 比較保險")]
        public int ttsTimeoutSec = 180;

        [Header("Fallback Voice")]
        [Tooltip("如果沒拿到 persona voice config, 用這個預設")]
        public string fallbackVoiceId = "zh-TW-HsiaoChenNeural";
        public string fallbackLanguage = "zh-TW";
        public string fallbackProvider = "edge-tts";

        // 從 persona 拿到的 voice config
        private string _activeVoiceId;
        private string _activeLanguage;
        private string _activeProvider;
        // F5-TTS 專用(Phase 1.5.1d): 從 persona.voice 帶 ref_audio / ref_text
        private string _activeRefAudio;
        private string _activeRefText;
        private int _activeNfeStep = 0;     // 0 = 用 persona 預設 / bridge 預設
        private float _activeCfgStrength = 0f;
        private string _activePersonaId = "siro-default";

        // 防重複 TTS 自己打的訊息
        // 設計:ChatInputUI 在 user 送出訊息時設 _lastUserMessage、HandleBridgeResponse
        // 檢查 response 是否包含同樣訊息、是就不 TTS(避免 Mao 複頌自己講的話)
        // 還沒接上 ChatInputUI、暫時 suppress warning(Phase 2 STT 一起做)
#pragma warning disable CS0414  // 暫時未用、Phase 2 接 ChatInputUI
        private string _lastUserMessage = "";
#pragma warning restore CS0414

        // Phase 1.5.2b: 句子級 TTS audio queue
        // 收到 tts_audio WS 訊息時,按 index 順序塞進 queue
        // 當前音檔播完才 dequeue 下一個(避免同時講兩段)
        // 設計:用 sorted list 而不是 queue,因為 TTS 完成時間不固定、
        // 句子 2 可能比句子 1 先到(parallel TTS)、但播放必須按 1→2 順序
        private readonly SortedDictionary<int, BridgeTtsAudio> _ttsQueue =
            new SortedDictionary<int, BridgeTtsAudio>();
        private int _nextExpectedIndex = 0;  // 下一個要播放的 index
        private bool _isPlayingSentence = false;  // 防止 overlap

        // Awake
        private void Awake()
        {
            if (audioSource == null)
            {
                audioSource = GetComponent<AudioSource>();
            }
            if (audioSource != null)
            {
                // TTS 用 play-on-demand、不打 loop
                audioSource.loop = false;
                audioSource.playOnAwake = false;
            }
            // 預設 voice config
            _activeVoiceId = fallbackVoiceId;
            _activeLanguage = fallbackLanguage;
            _activeProvider = fallbackProvider;
        }

        // Start
        private void Start()
        {
            // 自動找 bridge
            if (bridge == null)
            {
                bridge = GetComponent<HermesBridgeClient>();
                if (bridge == null) bridge = GetComponentInParent<HermesBridgeClient>();
                if (bridge == null) bridge = FindFirstObjectByType<HermesBridgeClient>();
            }

            if (bridge != null)
            {
                bridge.OnBridgeResponse += HandleBridgeResponse;
                bridge.OnBridgeError += HandleBridgeError;
                // Phase 1.5.2b: 訂閱句子級 TTS audio
                bridge.OnBridgeTtsAudio += HandleTtsAudio;
            }

            // 訂閱 persona 切換 → 重載 voice
            if (personaManager != null)
            {
                personaManager.OnPersonaChanged += HandlePersonaChanged;
                // 初次載入(如果 persona 已經在)
                var current = personaManager.GetCurrentPersona();
                if (current != null)
                {
                    HandlePersonaChanged(current);
                }
            }
        }

        private void OnDestroy()
        {
            if (bridge != null)
            {
                bridge.OnBridgeResponse -= HandleBridgeResponse;
                bridge.OnBridgeError -= HandleBridgeError;
                bridge.OnBridgeTtsAudio -= HandleTtsAudio;
            }
            if (personaManager != null)
            {
                personaManager.OnPersonaChanged -= HandlePersonaChanged;
            }
        }

        // ==================== Public API ====================

        /// <summary>
        /// 主動觸發 TTS 播放(外部呼叫、例如 ChatInputUI 在收到 response 時)
        /// </summary>
        public void Speak(string text)
        {
            if (muted || string.IsNullOrEmpty(text))
            {
                return;
            }
            // 啟動 coroutine 真的打 API
            StartCoroutine(SynthesizeAndPlay(text));
        }

        /// <summary>
        /// 切換靜音狀態(給 UI 按鈕用)
        /// </summary>
        public void ToggleMute()
        {
            muted = !muted;
            if (muted && audioSource != null && audioSource.isPlaying)
            {
                audioSource.Stop();
            }
            Debug.Log($"[TTSPlayer] muted={muted}");
        }

        // ==================== Event Handlers ====================

        private void HandleBridgeResponse(BridgeResponse response)
        {
            if (!autoSpeak || response == null || string.IsNullOrEmpty(response.text))
            {
                return;
            }
            Speak(response.text);
        }

        private void HandleBridgeError(BridgeError error)
        {
            // 錯誤訊息不 TTS(避免吵到 user)
        }

        // Phase 1.5.2b: 收到 bridge 句子級 TTS audio chunk
        // 設計:按 index 排隊,依序播放(WS 雖然 in-order 但 TTS 完成時間不固定)
        private void HandleTtsAudio(BridgeTtsAudio audio)
        {
            if (audio == null || string.IsNullOrEmpty(audio.audio_base64))
            {
                Debug.LogWarning("[TTSPlayer] tts_audio 是空、跳過");
                return;
            }
            if (muted)
            {
                Debug.Log("[TTSPlayer] muted → 跳過 TTS audio");
                return;
            }
            // 放進 sorted queue
            _ttsQueue[audio.index] = audio;
            Debug.Log($"[TTSPlayer] 收到 tts_audio #{audio.index} " +
                      $"len={audio.sentence?.Length ?? 0} format={audio.format} " +
                      $"queue_size={_ttsQueue.Count}");

            // 如果還沒在播放、啟動 queue 消費
            if (!_isPlayingSentence)
            {
                StartCoroutine(ConsumeTtsQueue());
            }
        }

        // Queue 消費:取最小的 index、decode、播放、播完繼續下一個
        private IEnumerator ConsumeTtsQueue()
        {
            _isPlayingSentence = true;
            try
            {
                while (_ttsQueue.Count > 0)
                {
                    // 取最小的 index(第一個 key)
                    int firstIdx = -1;
                    foreach (var k in _ttsQueue.Keys)
                    {
                        firstIdx = k;
                        break;
                    }
                    if (firstIdx < 0) break;

                    var audio = _ttsQueue[firstIdx];
                    _ttsQueue.Remove(firstIdx);

                    Debug.Log($"[TTSPlayer] 播放 tts_audio #{firstIdx} " +
                              $"(剩 {_ttsQueue.Count} 個在 queue)");

                    // decode base64 → audio bytes
                    byte[] audioBytes;
                    try
                    {
                        audioBytes = Convert.FromBase64String(audio.audio_base64);
                    }
                    catch (Exception e)
                    {
                        Debug.LogError($"[TTSPlayer] tts_audio base64 decode 失敗: {e.Message}");
                        continue;
                    }

                    // 寫暫存 + 載入 AudioClip + 播放
                    // 用 IEnumerator 不會 block、其他事件可以照樣處理
                    yield return LoadAudioAndPlay(audioBytes, audio.format ?? "wav");
                }
            }
            finally
            {
                _isPlayingSentence = false;
                if (_ttsQueue.Count > 0)
                {
                    Debug.LogWarning($"[TTSPlayer] queue 還有 {_ttsQueue.Count} 個沒播、繼續");
                    StartCoroutine(ConsumeTtsQueue());
                }
            }
        }

        private void HandlePersonaChanged(PersonaConfig config)
        {
            if (config == null) return;
            _activePersonaId = config.id ?? "siro-default";
            // Phase 1.5.1d: 從 persona.voice 拿 TTS 設定,而不是 hard-code edge-tts
            if (config.voice != null)
            {
                _activeProvider = string.IsNullOrEmpty(config.voice.provider) ? fallbackProvider : config.voice.provider;
                _activeVoiceId = string.IsNullOrEmpty(config.voice.voice_id) ? fallbackVoiceId : config.voice.voice_id;
                _activeLanguage = string.IsNullOrEmpty(config.voice.language) ? (config.language ?? fallbackLanguage) : config.voice.language;
                _activeRefAudio = config.voice.ref_audio;
                _activeRefText = config.voice.ref_text;
                _activeNfeStep = config.voice.nfe_step;
                _activeCfgStrength = config.voice.cfg_strength;
                Debug.Log($"[TTSPlayer] persona changed → provider={_activeProvider} voice={_activeVoiceId} lang={_activeLanguage} ref_audio={_activeRefAudio ?? "(none)"}");
            }
            else
            {
                _activeVoiceId = fallbackVoiceId;
                _activeLanguage = config.language ?? fallbackLanguage;
                _activeProvider = fallbackProvider;
                _activeRefAudio = null;
                _activeRefText = null;
                Debug.LogWarning($"[TTSPlayer] persona '{config.id}' 沒有 voice 設定,fallback edge-tts");
            }
        }

        // ==================== Internal: API Call ====================

        private IEnumerator SynthesizeAndPlay(string text)
        {
            if (bridge == null)
            {
                Debug.LogWarning("[TTSPlayer] bridge null、跳過 TTS");
                yield break;
            }

            // 從 bridge.serverUrl 推 base http url
            // 範例: ws://127.0.0.1:8001/ws → http://127.0.0.1:8001
            string httpBase = WsUrlToHttpBase(bridge.serverUrl);

            string url = $"{httpBase}/tts/synthesize";
            // 用 Newtonsoft.Json 序列化 text(Unity 預設的 .NET API 不含 System.Text.Json)
            string textJson = JsonConvert.SerializeObject(text);
            // Phase 1.5.1d: 帶 ref_audio / ref_text / nfe_step / cfg_strength / persona_id
            // escape double quote 避免 yaml 路徑內有 " 炸 JSON
            string refAudioEscaped = _activeRefAudio == null ? "" : _activeRefAudio.Replace("\\", "\\\\").Replace("\"", "\\\"");
            string refTextEscaped = _activeRefText == null ? "" : _activeRefText.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n");
            string extraFields = "";
            if (!string.IsNullOrEmpty(_activeRefAudio)) extraFields += $", \"ref_audio\": \"{refAudioEscaped}\"";
            if (!string.IsNullOrEmpty(_activeRefText)) extraFields += $", \"ref_text\": \"{refTextEscaped}\"";
            if (_activeNfeStep > 0) extraFields += $", \"nfe_step\": {_activeNfeStep}";
            if (_activeCfgStrength > 0f) extraFields += $", \"cfg_strength\": {_activeCfgStrength.ToString(System.Globalization.CultureInfo.InvariantCulture)}";
            extraFields += $", \"persona_id\": \"{_activePersonaId}\"";
            string json = $@"{{
                ""text"": {textJson},
                ""voice_id"": ""{_activeVoiceId}"",
                ""language"": ""{_activeLanguage}"",
                ""provider"": ""{_activeProvider}"",
                ""speed"": 1.0,
                ""pitch"": 0.0,
                ""format"": ""wav""{extraFields}
            }}";

            using (UnityWebRequest req = new UnityWebRequest(url, "POST"))
            {
                byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(json);
                req.uploadHandler = new UploadHandlerRaw(bodyRaw);
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                req.timeout = ttsTimeoutSec;

                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"[TTSPlayer] TTS API 失敗: {req.error} (code={req.responseCode})");
                    yield break;
                }

                // Parse JSON response
                string responseJson = req.downloadHandler.text;
                JObject respObj = JObject.Parse(responseJson);
                string audioBase64 = (string)respObj["audio_base64"];
                string audioFormat = (string)respObj["format"] ?? "mp3";
                if (string.IsNullOrEmpty(audioBase64))
                {
                    Debug.LogWarning("[TTSPlayer] 回應沒 audio_base64");
                    yield break;
                }

                // Decode base64 → audio bytes
                byte[] audioBytes;
                try
                {
                    audioBytes = Convert.FromBase64String(audioBase64);
                }
                catch (Exception e)
                {
                    Debug.LogError($"[TTSPlayer] base64 decode 失敗: {e.Message}");
                    yield break;
                }

                // 寫暫存檔 + Unity 載 (Phase 1.5.1d 支援 wav | mp3)
                yield return LoadAudioAndPlay(audioBytes, audioFormat);
            }
        }

        private IEnumerator LoadAudioAndPlay(byte[] audioBytes, string format)
        {
            // Phase 1.5.1d: 支援 wav | mp3 | opus(依 bridge response 的 format 決定)
            // wav 是 F5-TTS 預設;mp3 是 edge-tts 預設
            string ext = format.ToLower() switch
            {
                "wav" => "wav",
                "mp3" => "mp3",
                "opus" => "ogg",
                _ => "wav",
            };
            AudioType audioType = format.ToLower() switch
            {
                "wav" => AudioType.WAV,
                "mp3" => AudioType.MPEG,
                "opus" => AudioType.OGGVORBIS,
                _ => AudioType.WAV,
            };
            string tempPath = System.IO.Path.Combine(
                Application.temporaryCachePath, $"siro_tts_{DateTime.UtcNow.Ticks}.{ext}");
            try
            {
                System.IO.File.WriteAllBytes(tempPath, audioBytes);
            }
            catch (Exception e)
            {
                Debug.LogError($"[TTSPlayer] 寫暫存音檔失敗: {e.Message}");
                yield break;
            }

            using (UnityWebRequest req = UnityWebRequestMultimedia.GetAudioClip(tempPath, audioType))
            {
                req.timeout = ttsTimeoutSec;
                yield return req.SendWebRequest();
                try { System.IO.File.Delete(tempPath); } catch { /* 忽略 */ }

                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"[TTSPlayer] {format} decode 失敗: {req.error}");
                    yield break;
                }

                AudioClip clip = DownloadHandlerAudioClip.GetContent(req);
                if (clip == null)
                {
                    Debug.LogWarning("[TTSPlayer] AudioClip 是 null");
                    yield break;
                }

                if (audioSource != null)
                {
                    audioSource.clip = clip;
                    audioSource.Play();
                    Debug.Log($"[TTSPlayer] 播放 TTS 音檔 {clip.length:F1}s");
                }
            }
        }

        private static string WsUrlToHttpBase(string wsUrl)
        {
            // 從 ws://127.0.0.1:8001/ws 推 http://127.0.0.1:8001
            if (string.IsNullOrEmpty(wsUrl)) return "http://127.0.0.1:8001";
            string s = wsUrl;
            if (s.StartsWith("ws://")) s = "http://" + s.Substring(5);
            else if (s.StartsWith("wss://")) s = "https://" + s.Substring(6);
            // 去掉 /ws 路徑結尾
            int slashIdx = s.IndexOf("/ws", StringComparison.OrdinalIgnoreCase);
            if (slashIdx > 0) s = s.Substring(0, slashIdx);
            return s;
        }
    }
}
