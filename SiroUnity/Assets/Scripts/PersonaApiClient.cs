// unity/Assets/Scripts/PersonaApiClient.cs
//
// v1+ 多角色架構：bridge HTTP client
//
// 跟 bridge 拿 persona 資料：
// - GET  /personas         → PersonaListResponse（清單）
// - GET  /personas/{id}    → PersonaDetail（單一完整設定）
//
// 用 UnityWebRequest（非 async/await，避免跟 Unity 既有 code style 衝突）
//
// v1.1 fix：_Get 改回傳 raw string（不再泛型），JSON parse 移到 call site。
// 原因：原本 `_Get<T>` 的 lambda 參數是 string，沒用到 T，
// 編譯器 CS0411 推不出 T。

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
            _Get($"{bridgeBaseUrl}/personas", (raw) =>
            {
                var resp = JsonUtility.FromJson<PersonaListResponse>(raw);
                onSuccess?.Invoke(resp);
            }, onError);
        }

        /// <summary>
        /// 取單一 persona 完整資料
        /// </summary>
        public void FetchPersonaDetail(string personaId, Action<PersonaConfig> onSuccess, Action<string> onError)
        {
            _Get($"{bridgeBaseUrl}/personas/{personaId}", (raw) =>
            {
                if (string.IsNullOrEmpty(raw))
                {
                    onError?.Invoke("Empty response from bridge");
                    return;
                }
                var config = JsonUtility.FromJson<PersonaConfig>(raw);
                onSuccess?.Invoke(config);
            }, onError);
        }

        /// <summary>
        /// 內部 helper：抓 raw body 丟給 onSuccess，錯誤丟 onError。
        /// 不泛型 — JSON parse 在 call site 各自處理。
        /// </summary>
        private void _Get(string url, Action<string> onSuccess, Action<string> onError)
        {
            StartCoroutine(_GetRoutine(url, onSuccess, onError));
        }

        private IEnumerator _GetRoutine(string url, Action<string> onSuccess, Action<string> onError)
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
                    onSuccess?.Invoke(body);
                }
                catch (Exception e)
                {
                    // 解析失敗時 log 原始 body 方便 debug
                    onError?.Invoke($"Parse error: {e.Message} (body={(body ?? "").Substring(0, Math.Min(200, (body ?? "").Length))})");
                }
            }
        }
    }
}
