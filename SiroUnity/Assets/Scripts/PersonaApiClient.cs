// unity/Assets/Scripts/PersonaApiClient.cs
//
// v1+ 多角色架構：bridge HTTP client
//
// 跟 bridge 拿 persona 資料：
// - GET  /personas         → PersonaListResponse（清單）
// - GET  /personas/{id}    → PersonaDetail（單一完整設定）
//
// 用 UnityWebRequest（非 async/await，避免跟 Unity 既有 code style 衝突）

using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

namespace Siro
{
    public class PersonaApiClient : MonoBehaviour
    {
        [Header("Server")]
        [Tooltip("bridge server base URL，例如 http://127.0.0.1:8001")]
        public string bridgeBaseUrl = "http://127.0.0.1:8001";

        [Header("Debug")]
        public bool verboseLogging = true;

        /// <summary>
        /// 取所有 persona 清單
        /// </summary>
        public void FetchPersonaList(Action<PersonaListResponse> onSuccess, Action<string> onError)
        {
            StartCoroutine(_Get<PersonaListResponse>($"{bridgeBaseUrl}/personas", onSuccess, onError));
        }

        /// <summary>
        /// 取單一 persona 完整資料
        /// </summary>
        public void FetchPersonaDetail(string personaId, Action<PersonaConfig> onSuccess, Action<string> onError)
        {
            StartCoroutine(_Get($"{bridgeBaseUrl}/personas/{personaId}", (raw) =>
            {
                if (string.IsNullOrEmpty(raw))
                {
                    onError?.Invoke("Empty response from bridge");
                    return;
                }
                try
                {
                    var config = JsonUtility.FromJson<PersonaConfig>(raw);
                    onSuccess?.Invoke(config);
                }
                catch (Exception e)
                {
                    onError?.Invoke($"JSON parse error: {e.Message}");
                }
            }, onError));
        }

        private IEnumerator _Get<T>(string url, Action<T> onSuccess, Action<string> onError) where T : class
        {
            if (verboseLogging) Debug.Log($"[PersonaApiClient] GET {url}");

            using (var req = UnityWebRequest.Get(url))
            {
                req.timeout = 5;  // 5s timeout，bridge 沒跑就別等太久
                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    var err = $"HTTP {req.responseCode}: {req.error}";
                    if (verboseLogging) Debug.LogError($"[PersonaApiClient] {url} 失敗: {err}");
                    onError?.Invoke(err);
                    yield break;
                }

                var body = req.downloadHandler.text;
                try
                {
                    var parsed = JsonUtility.FromJson<T>(body);
                    onSuccess?.Invoke(parsed);
                }
                catch (Exception e)
                {
                    onError?.Invoke($"JSON parse error: {e.Message} (body={body.Substring(0, Math.Min(200, body.Length))})");
                }
            }
        }
    }
}
