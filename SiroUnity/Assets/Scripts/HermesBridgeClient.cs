// unity/Assets/Scripts/HermesBridgeClient.cs
//
// WebSocket client，連到 SIRO bridge (預設 ws://127.0.0.1:8001/ws)。
//
// 訊息格式（送出）：
//   { "type": "chat", "message": "...", "user_id": "...", "personality": "..." }
//   { "type": "ping" }
//
// 訊息格式（接收）：
//   { "type": "response", "text": "...", "emotion": "happy", "intensity": 0.8,
//     "live2d": { "expression_id": "F02", "motion_group": "Idle", ... },
//     "session_id": "..." }
//   { "type": "delta", "text": "你" }        ← v0.3.1 SSE streaming（每個 chunk 一個）
//   { "type": "error", "detail": "..." }
//   { "type": "pong" }
//
// 使用：
//   - 掛在一個空 GameObject 上
//   - Inspector 設定 serverUrl
//   - 訂閱 OnBridgeResponse event
//
// v0.2: 加上自動重連（指數 backoff）
// v0.3.1: 加上 SSE streaming delta 訊息處理（Unity 端 incremental render）
//   - bridge 端 SIRO_STREAMING=true 時推 {"type":"delta","text":"..."} 增量
//   - 收到 N 個 delta 後推 {"type":"response",...} 最終（行為跟 v0.2 相同）
//   - 沒開 streaming 時只收 response、不收 delta（向下相容）
//

using System;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Siro
{
    [Serializable]
    public class Live2DSignal
    {
        public string expression_id;
        public string motion_group;
        public int motion_index;
        public float intensity;
        public int duration_ms;
    }

    [Serializable]
    public class BridgeResponse
    {
        public string type;
        public string text;
        public string emotion;
        public float intensity;
        public Live2DSignal live2d;
        public string session_id;
    }

    [Serializable]
    public class BridgeError
    {
        public string type;
        public string detail;
    }

    /// <summary>
    /// v0.3.1 SSE streaming delta 訊息
    /// bridge 端 SIRO_STREAMING=true 時每收到一個 LLM chunk 就推一個
    /// Unity 端用 OnBridgeDelta 累積文字，達到「邊生成邊 render」效果
    /// </summary>
    [Serializable]
    public class BridgeDelta
    {
        public string type;   // 永遠 "delta"
        public string text;   // 單一 chunk（例如 "你"、"好"、"，"）
    }

    public class HermesBridgeClient : MonoBehaviour
    {
        [Header("Server")]
        [Tooltip("bridge server URL，含 ws:// 與 /ws")]
        public string serverUrl = "ws://127.0.0.1:8001/ws";

        [Header("Identity")]
        public string userId = "unity_user";
        [Tooltip("目前使用的 persona ID，會被 PersonaManager runtime 切換")]
        public string personality = "default";

        /// <summary>
        /// v1+ 多角色切換：PersonaManager 切 persona 時呼叫，之後送出的 chat 都帶新 personality
        /// </summary>
        public void SetActivePersonality(string personaId)
        {
            if (string.IsNullOrEmpty(personaId)) return;
            personality = personaId;
            Debug.Log($"[HermesBridgeClient] 切換 personality: {personaId}");
        }

        [Header("Reconnect")]
        [Tooltip("啟用自動重連")]
        public bool autoReconnect = true;
        [Tooltip("初始重連延遲（秒）")]
        public float initialReconnectDelaySec = 1f;
        [Tooltip("最大重連延遲（秒）")]
        public float maxReconnectDelaySec = 30f;
        [Tooltip("重連失敗幾次後放棄")]
        public int maxReconnectAttempts = 0; // 0 = 無限重試

        [Header("Debug")]
        public bool verboseLogging = true;

        // 事件 - 訂閱者從這裡收訊息
        public event Action<BridgeResponse> OnBridgeResponse;
        public event Action<BridgeError> OnBridgeError;
        public event Action<BridgeDelta> OnBridgeDelta;   // v0.3.1 SSE streaming（每個 chunk 觸發）
        public event Action OnBridgeConnected;
        public event Action OnBridgeDisconnected;
        public event Action<int> OnReconnectAttempt;  // 參數：第 N 次嘗試
        public event Action OnReconnectGivingUp;     // 超過 maxReconnectAttempts

        // 內部狀態
        private ClientWebSocket _ws;
        private CancellationTokenSource _cts;
        private bool _isConnected = false;
        private bool _shouldRun = false;
        private int _reconnectAttempts = 0;
        private Coroutine _reconnectCoroutine;

        public bool IsConnected => _isConnected;
        public int ReconnectAttempts => _reconnectAttempts;

        // ==================== Unity Lifecycle ====================

        private async void Start()
        {
            await ConnectAsync();
        }

        private async void OnDestroy()
        {
            StopReconnect();
            await DisconnectAsync();
        }

        private void OnApplicationQuit()
        {
            _shouldRun = false;
            try { _cts?.Cancel(); } catch { }
        }

        // ==================== 公開 API ====================

        public async Task ConnectAsync()
        {
            _shouldRun = true;
            _cts = new CancellationTokenSource();
            _ws = new ClientWebSocket();

            try
            {
                if (verboseLogging) Debug.Log($"[HermesBridge] 連線中: {serverUrl}");
                await _ws.ConnectAsync(new Uri(serverUrl), _cts.Token);
                _isConnected = true;
                _reconnectAttempts = 0;  // 連線成功，重置計數
                if (verboseLogging) Debug.Log("[HermesBridge] ✓ 已連線");
                OnBridgeConnected?.Invoke();

                // 啟動接收 loop
                _ = ReceiveLoopAsync();
            }
            catch (Exception e)
            {
                _isConnected = false;
                if (verboseLogging) Debug.LogWarning($"[HermesBridge] 連線失敗: {e.Message}");
                OnBridgeError?.Invoke(new BridgeError
                {
                    type = "error",
                    detail = $"連線失敗: {e.Message}",
                });

                // 啟動重連
                if (autoReconnect) StartReconnect();
            }
        }

        public async Task DisconnectAsync()
        {
            _shouldRun = false;
            StopReconnect();
            _isConnected = false;
            _cts?.Cancel();

            if (_ws != null && _ws.State == WebSocketState.Open)
            {
                try
                {
                    await _ws.CloseAsync(
                        WebSocketCloseStatus.NormalClosure,
                        "client closing",
                        CancellationToken.None
                    );
                }
                catch (Exception e)
                {
                    if (verboseLogging) Debug.LogWarning($"[HermesBridge] 關閉時錯誤: {e.Message}");
                }
            }
        }

        public async Task SendChatAsync(string message)
        {
            if (!_isConnected || _ws == null)
            {
                Debug.LogWarning("[HermesBridge] 尚未連線，無法送出訊息");
                OnBridgeError?.Invoke(new BridgeError
                {
                    type = "error",
                    detail = "尚未連線到 bridge",
                });
                return;
            }

            var payload = new JObject
            {
                ["type"] = "chat",
                ["message"] = message,
                ["user_id"] = userId,
                ["personality"] = personality,
            };
            await SendJsonAsync(payload);
        }

        public async Task PingAsync()
        {
            var payload = new JObject { ["type"] = "ping" };
            await SendJsonAsync(payload);
        }

        // ==================== 重連邏輯 ====================

        private void StartReconnect()
        {
            if (_reconnectCoroutine != null) return;
            _reconnectCoroutine = StartCoroutine(ReconnectLoop());
        }

        private void StopReconnect()
        {
            if (_reconnectCoroutine != null)
            {
                StopCoroutine(_reconnectCoroutine);
                _reconnectCoroutine = null;
            }
        }

        private System.Collections.IEnumerator ReconnectLoop()
        {
            while (_shouldRun && autoReconnect)
            {
                _reconnectAttempts++;
                OnReconnectAttempt?.Invoke(_reconnectAttempts);

                if (maxReconnectAttempts > 0 && _reconnectAttempts > maxReconnectAttempts)
                {
                    if (verboseLogging) Debug.LogError(
                        $"[HermesBridge] 已重連 {_reconnectAttempts} 次，放棄"
                    );
                    OnReconnectGivingUp?.Invoke();
                    _reconnectCoroutine = null;
                    yield break;
                }

                // 指數 backoff: 1s, 2s, 4s, 8s, ... cap at max
                float delay = Mathf.Min(
                    initialReconnectDelaySec * Mathf.Pow(2, _reconnectAttempts - 1),
                    maxReconnectDelaySec
                );

                if (verboseLogging) Debug.Log(
                    $"[HermesBridge] 第 {_reconnectAttempts} 次重連嘗試，{delay:F1}s 後..."
                );

                yield return new WaitForSeconds(delay);

                // 嘗試重連
                var task = ConnectAsync();
                // 等待連線完成（同步等待）
                while (!task.IsCompleted) yield return null;

                if (_isConnected)
                {
                    if (verboseLogging) Debug.Log("[HermesBridge] ✓ 重連成功");
                    _reconnectCoroutine = null;
                    yield break;
                }
            }
            _reconnectCoroutine = null;
        }

        // ==================== 內部 ====================

        private async Task SendJsonAsync(JObject payload)
        {
            if (_ws == null || _ws.State != WebSocketState.Open)
            {
                Debug.LogWarning("[HermesBridge] WebSocket 不在 open 狀態");
                return;
            }

            try
            {
                var json = payload.ToString();
                var bytes = Encoding.UTF8.GetBytes(json);
                var segment = new ArraySegment<byte>(bytes);

                if (verboseLogging) Debug.Log($"[HermesBridge] 送出: {json}");

                await _ws.SendAsync(
                    segment,
                    WebSocketMessageType.Text,
                    true,
                    _cts.Token
                );
            }
            catch (Exception e)
            {
                Debug.LogError($"[HermesBridge] 送出失敗: {e.Message}");
                // 觸發重連
                _isConnected = false;
                OnBridgeDisconnected?.Invoke();
                if (autoReconnect) StartReconnect();
            }
        }

        private async Task ReceiveLoopAsync()
        {
            var buffer = new byte[4096];

            while (_shouldRun && _ws != null && _ws.State == WebSocketState.Open)
            {
                try
                {
                    var result = await _ws.ReceiveAsync(
                        new ArraySegment<byte>(buffer),
                        _cts.Token
                    );

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        if (verboseLogging) Debug.Log("[HermesBridge] 伺服器關閉連線");
                        break;
                    }

                    var json = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    if (verboseLogging) Debug.Log($"[HermesBridge] 收到: {json}");

                    HandleMessage(json);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception e)
                {
                    Debug.LogError($"[HermesBridge] 接收錯誤: {e.Message}");
                    break;
                }
            }

            // 連線中斷
            if (_isConnected)
            {
                _isConnected = false;
                OnBridgeDisconnected?.Invoke();
                if (verboseLogging) Debug.Log("[HermesBridge] 連線中斷");
                if (autoReconnect && _shouldRun) StartReconnect();
            }
        }

        private void HandleMessage(string json)
        {
            try
            {
                var j = JObject.Parse(json);
                var type = j["type"]?.ToString();

                switch (type)
                {
                    case "response":
                        var resp = j.ToObject<BridgeResponse>();
                        OnBridgeResponse?.Invoke(resp);
                        break;

                    case "delta":
                        // v0.3.1 SSE streaming — bridge SIRO_STREAMING=true 時推的 chunk
                        // 不論有沒有訂閱者都不丟（避免默默浪費 LLM 流量）
                        var d = j.ToObject<BridgeDelta>();
                        OnBridgeDelta?.Invoke(d);
                        break;

                    case "error":
                        var err = j.ToObject<BridgeError>();
                        OnBridgeError?.Invoke(err);
                        break;

                    case "pong":
                        if (verboseLogging) Debug.Log("[HermesBridge] pong");
                        break;

                    default:
                        Debug.LogWarning($"[HermesBridge] 未知訊息類型: {type}");
                        break;
                }
            }
            catch (Exception e)
            {
                Debug.LogError($"[HermesBridge] 解析訊息失敗: {e.Message}");
            }
        }
    }
}
