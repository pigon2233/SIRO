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
        [Tooltip("TTS API timeout (秒)")]
        public int ttsTimeoutSec = 15;

        [Header("Fallback Voice")]
        [Tooltip("如果沒拿到 persona voice config, 用這個預設")]
        public string fallbackVoiceId = "zh-TW-HsiaoChenNeural";
        public string fallbackLanguage = "zh-TW";
        public string fallbackProvider = "edge-tts";

        // 從 persona 拿到的 voice config
        private string _activeVoiceId;
        private string _activeLanguage;
        private string _activeProvider;

        // 防重複 TTS 自己打的訊息
        private string _lastUserMessage = "";

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

        private void HandlePersonaChanged(PersonaConfig config)
        {
            if (config == null) return;
            // 從 persona 拿 voice 設定(透過 bridge 拉的 /personas/{id} response.voice)
            // Phase 1 簡化版:直接讀 config 裡的 voice(若 PersonaConfig 支援)
            // 目前 PersonaConfig 還沒有 voice 欄位(那是在 bridge 端)
            // 所以 fallback:用預設 voice
            // TODO Phase 1.5: 加 PersonaConfig.voice 欄位同步
            _activeVoiceId = fallbackVoiceId;
            _activeLanguage = config.language ?? fallbackLanguage;
            _activeProvider = fallbackProvider;
            Debug.Log($"[TTSPlayer] persona changed → voice={_activeVoiceId} lang={_activeLanguage}");
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
            string json = $@"{{
                ""text"": {textJson},
                ""voice_id"": ""{_activeVoiceId}"",
                ""language"": ""{_activeLanguage}"",
                ""provider"": ""{_activeProvider}"",
                ""speed"": 1.0,
                ""pitch"": 0.0,
                ""format"": ""mp3""
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
                if (string.IsNullOrEmpty(audioBase64))
                {
                    Debug.LogWarning("[TTSPlayer] 回應沒 audio_base64");
                    yield break;
                }

                // Decode base64 → mp3 bytes
                byte[] mp3Bytes;
                try
                {
                    mp3Bytes = Convert.FromBase64String(audioBase64);
                }
                catch (Exception e)
                {
                    Debug.LogError($"[TTSPlayer] base64 decode 失敗: {e.Message}");
                    yield break;
                }

                // mp3 → AudioClip (用 UnityWebRequestMultimedia 載 mp3)
                yield return LoadMp3AndPlay(mp3Bytes);
            }
        }

        private IEnumerator LoadMp3AndPlay(byte[] mp3Bytes)
        {
            // Unity 的 AudioClip 不直接支援 mp3、要走 UnityWebRequestMultimedia
            // 寫到暫存檔、再載入
            string tempPath = System.IO.Path.Combine(Application.temporaryCachePath, $"siro_tts_{DateTime.UtcNow.Ticks}.mp3");
            try
            {
                System.IO.File.WriteAllBytes(tempPath, mp3Bytes);
            }
            catch (Exception e)
            {
                Debug.LogError($"[TTSPlayer] 寫暫存 mp3 失敗: {e.Message}");
                yield break;
            }

            using (UnityWebRequest req = UnityWebRequestMultimedia.GetAudioClip(tempPath, AudioType.MPEG))
            {
                req.timeout = ttsTimeoutSec;
                yield return req.SendWebRequest();
                try { System.IO.File.Delete(tempPath); } catch { /* 忽略 */ }

                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"[TTSPlayer] mp3 decode 失敗: {req.error}");
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
