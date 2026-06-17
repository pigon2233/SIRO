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
//   { "type": "task_ack", "task_id": "...", "status": "accepted" }  ← v1.2 SendTask
//   { "type": "task_result", "task_id": "...", "result": {...} }
//   { "type": "task_failed", "task_id": "...", "error": "..." }
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
// v1.2:  SendTask — Unity 主動推 task 進 AgentOS
//   - SendTaskAsync(name, args) fire-and-await → 回 JObject result 或 throw
//   - OnTaskResult / OnTaskFailed event 給 fire-and-forget 訂閱者
//   - 規格見 docs/AGENT_OS.md v1.2 段
//

using System;
using System.Collections.Generic;
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

    /// <summary>
    /// v1.5+ LLM tool calling 觸發的 motion 播放訊息
    /// bridge 端 LLM 透過 play_motion tool 決定觸發某個 motion、
    /// 推 {"type":"motion_play","motion_group":"mtn_02","motion_index":0} 給 Unity
    /// Unity 收到後呼叫 Live2DModelController.PlayMotion(group, index, isLoop=false)
    /// </summary>
    [Serializable]
    public class BridgeMotionPlay
    {
        public string type;         // 永遠 "motion_play"
        public string motion_group; // Cubism motion 群組名（如 "mtn_02"）
        public int motion_index;    // 群組內 motion 編號（預設 0）
    }

    /// <summary>
    /// Phase 1.5.2b: 句子級 TTS audio chunk
    /// bridge 端 SIRO_TTS_STREAMING=true 時、LLM streaming 出 token → 偵測到句尾 →
    /// 背景 TTS 該句 → 推 {"type":"tts_audio","index":N,"sentence":"...","format":"wav","audio_base64":"...","provider":"f5-tts"}
    /// Unity 端用 OnBridgeTtsAudio 收到、按 index 排序 queue、依序播放
    ///
    /// Phase 2 STT (Day 4):加 turn_id 欄位 — Unity 端用來過濾舊 turn 的 in-flight chunks
    /// </summary>
    [Serializable]
    public class BridgeTtsAudio
    {
        public string type;          // 永遠 "tts_audio"
        public int index;            // 句子編號(LLM 回應的第 N 句)
        public int turn_id;          // Phase 2 STT:Unity 端過濾(0 = legacy、不過濾)
        public string sentence;      // 該句文字(已 strip [emotion:xxx])
        public string format;        // wav | mp3 | opus
        public string audio_base64;  // base64 編碼的音檔 bytes
        public string provider;      // f5-tts | edge-tts | piper-tts | gpt-sovits
    }

    /// <summary>
    /// Phase 2 STT (Day 4):bridge 偵測到 VAD PAUSE(speech start)
    /// 推 {"type":"vad_pause","turn_id":N}
    /// Unity 端用 OnBridgeVadPause 觸發 AEC ducking + 視覺 ring 變色
    /// </summary>
    [Serializable]
    public class BridgeVadPause
    {
        public string type;     // 永遠 "vad_pause"
        public int turn_id;
    }

    /// <summary>
    /// Phase 2 STT (Day 4):bridge 偵測到 VAD RESUME(utterance end)
    /// 推 {"type":"vad_resume","turn_id":N,"duration_ms":N,"audio_base64":"..."}
    /// Unity 端用 OnBridgeVadResume 觸發 AEC restore + 顯示「處理中」
    /// </summary>
    [Serializable]
    public class BridgeVadResume
    {
        public string type;          // 永遠 "vad_resume"
        public int turn_id;
        public int duration_ms;      // speech 持續時間(ms)
        public string audio_base64;  // 16-bit PCM 音訊(給 Unity debug / record 用)
    }

    /// <summary>
    /// Phase 2 STT (Day 3):LLM 被打斷通知
    /// 推 {"type":"agent_interrupt","turn_id":N,"last_heard":"..."}
    /// Unity 端用 OnBridgeAgentInterrupt 顯示「Mao 被打斷」視覺 cue
    /// </summary>
    [Serializable]
    public class BridgeAgentInterrupt
    {
        public string type;       // 永遠 "agent_interrupt"
        public int turn_id;
        public string last_heard; // Mao 上一句講的話(被 user 打斷)
    }

    /// <summary>
    /// v1.2 SendTask result
    /// bridge 端 task 成功完成時推 {"type":"task_result","task_id":"...","result":{...}}
    /// Unity 端 SendTaskAsync 內部 await 這個、訂閱 OnTaskResult 自己收
    /// </summary>
    [Serializable]
    public class BridgeTaskResult
    {
        public string type;     // 永遠 "task_result"
        public string task_id;  // 對應 SendTaskAsync 送出的 task_id
        public JObject result;  // task 結果（handler 回傳的 dict）
    }

    /// <summary>
    /// v1.2 SendTask failure
    /// bridge 端 task 失敗時推 {"type":"task_failed","task_id":"...","error":"..."}
    /// SendTaskAsync 內部 throw exception、訂閱 OnTaskFailed 自己收
    /// </summary>
    [Serializable]
    public class BridgeTaskFailed
    {
        public string type;     // 永遠 "task_failed"
        public string task_id;
        public string error;    // 錯誤訊息（例如 "mood.set: invalid emotion 'foo'"）
    }

    /// <summary>
    /// v1.2 SendTask 失敗時拋（bridge 端回 task_failed 觸發）
    /// </summary>
    public class SendTaskException : Exception
    {
        public string TaskId { get; }
        public SendTaskException(string taskId, string error) : base(error)
        {
            TaskId = taskId;
        }
    }

    /// <summary>
    /// v1.5+ Computer control confirmation request
    /// bridge 端 SIRO 想跑危險操作時推 {"type":"confirmation_request",...}
    /// Unity 顯示 modal dialog、按「允許」/「拒絕」、推 confirmation_response 回 bridge
    /// </summary>
    [Serializable]
    public class BridgeConfirmationRequest
    {
        public string type;              // 永遠 "confirmation_request"
        public string confirmation_id;   // bridge 產生的 uuid, 回 response 要帶這個
        public string tool;              // e.g. "run_shell_cmd"、"request_confirmation"、"delete_memory"
        public JObject args;             // tool 參數（給 UI 顯示用, e.g. {"cmd":"apt install ..."}）
        public string description;       // 人話描述（給 user 看的）
        public float timeout_sec;        // 60s 沒回就 auto-reject
    }

    /// <summary>
    /// v1.5+ confirmation response ack
    /// bridge 收到 confirmation_response 後會推 {"type":"confirmation_acked",...}
    /// 告訴 Unity 這個 id 已經被處理（給 UI 關 dialog 用）
    /// </summary>
    [Serializable]
    public class BridgeConfirmationAcked
    {
        public string type;              // 永遠 "confirmation_acked"
        public string confirmation_id;
        public bool resolved;            // True = 找到並 resolve、False = id 不存在或重複
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
        // Day 8 fix:預設 false,避免 mic chunk 32ms 一個就刷一排 log 造成 console 洪水
        // 想看詳細時可以在 Inspector 改成 true
        public bool verboseLogging = false;

        // 事件 - 訂閱者從這裡收訊息
        public event Action<BridgeResponse> OnBridgeResponse;
        public event Action<BridgeError> OnBridgeError;
        public event Action<BridgeDelta> OnBridgeDelta;   // v0.3.1 SSE streaming（每個 chunk 觸發）
        public event Action<BridgeTaskResult> OnTaskResult;  // v1.2 SendTask 成功
        public event Action<BridgeTaskFailed> OnTaskFailed;  // v1.2 SendTask 失敗
        public event Action<BridgeMotionPlay> OnBridgeMotionPlay;  // v1.5+ LLM play_motion tool
        public event Action<BridgeConfirmationRequest> OnBridgeConfirmationRequest;  // v1.5+ 危險操作前詢問
        public event Action<BridgeConfirmationAcked> OnBridgeConfirmationAcked;     // v1.5+ confirmation_response 被收到
        public event Action<BridgeTtsAudio> OnBridgeTtsAudio;  // Phase 1.5.2b 句子級 TTS audio chunk
        public event Action<JObject> OnBridgeToolAction;  // v1.5+ agent loop 過程中每個 tool call 的即時 event
        public event Action OnBridgeConnected;
        public event Action OnBridgeDisconnected;
        public event Action<BridgeVadPause> OnBridgeVadPause;  // Phase 2 STT (Day 4):VAD speech start
        public event Action<BridgeVadResume> OnBridgeVadResume;  // Phase 2 STT (Day 4):VAD utterance end
        public event Action<BridgeAgentInterrupt> OnBridgeAgentInterrupt;  // Phase 2 STT (Day 3):LLM 被打斷
        public event Action<int> OnReconnectAttempt;  // 參數：第 N 次嘗試
        public event Action OnReconnectGivingUp;     // 超過 maxReconnectAttempts

        // 內部狀態
        private ClientWebSocket _ws;
        private CancellationTokenSource _cts;
        private bool _isConnected = false;
        private bool _shouldRun = false;
        private int _reconnectAttempts = 0;
        private Coroutine _reconnectCoroutine;

        // v1.2 SendTask：追蹤 pending task 的 TaskCompletionSource
        // SendTaskAsync 註冊一個 TCS、HandleMessage 收到 task_result / task_failed 時 SetResult / SetException
        // 連線斷時 CancelAll，呼叫端會收到 OperationCanceledException
        // 用 lock 保護多執行緒 access（WS receive loop + SendTaskAsync caller）
        private readonly Dictionary<string, TaskCompletionSource<JObject>> _pendingTasks = new Dictionary<string, TaskCompletionSource<JObject>>();
        private readonly object _pendingTasksLock = new object();

        public bool IsConnected => _isConnected;
        public int ReconnectAttempts => _reconnectAttempts;

        // ==================== Unity Lifecycle ====================

        private async void Start()
        {
            // Day 8.5 hotfix:印 verboseLogging 實際值、幫 debug 確認 Editor 有重編
            Debug.Log($"[HermesBridge] Start: verboseLogging={verboseLogging} (Day 8 default=false)");
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

        /// <summary>
        /// v1.2 SendTask — Unity 主動推 task 進 bridge AgentOS、等結果回來
        /// 規格見 docs/AGENT_OS.md v1.2 段
        ///
        /// Fire-and-await：生出 task_id、送出 message、等 task_result 或 task_failed 回來
        /// 訂 fire-and-forget 模式：不要 await、用訂閱 OnTaskResult / OnTaskFailed 自己收
        ///
        /// Args:
        ///   name: task name（"mood.set" / "motion.play" / "persona.switch" / "chat.say" / "chat.summon"）
        ///   args: task 參數 dict（依 task 而異）
        ///   timeoutSec: 等結果多久、default 5s（task 通常 < 1s，5s 給 LLM task 預留 buffer）
        ///
        /// Returns:
        ///   task handler 回傳的 result（JObject）
        ///
        /// Throws:
        ///   TimeoutException: 超過 timeoutSec 沒收到 result
        ///   InvalidOperationException: 尚未連線到 bridge
        ///   SendTaskException: bridge 端回 task_failed（error 訊息在 Message 裡）
        ///   OperationCanceledException: 連線中斷、pending task 被 cancel
        /// </summary>
        public async Task<JObject> SendTaskAsync(string name, JObject args, float timeoutSec = 5.0f)
        {
            if (!_isConnected || _ws == null)
            {
                throw new InvalidOperationException("[HermesBridge] 尚未連線，無法 SendTask");
            }
            if (string.IsNullOrEmpty(name))
            {
                throw new ArgumentException("[HermesBridge] SendTask name 不能空白", nameof(name));
            }

            // task_id：UUID4 hex[:8]（跟 Python 端 Task.id 同步格式 — UUID4 32 字 hex 取前 8）
            string taskId = Guid.NewGuid().ToString("N").Substring(0, 8);
            var tcs = new TaskCompletionSource<JObject>(TaskCreationOptions.RunContinuationsAsynchronously);

            lock (_pendingTasksLock)
            {
                _pendingTasks[taskId] = tcs;
            }

            try
            {
                // 送出 {"type":"task", "task_id":"...", "name":"...", "args":{...}, "user_id":"..."}
                var payload = new JObject
                {
                    ["type"] = "task",
                    ["task_id"] = taskId,
                    ["name"] = name,
                    ["args"] = args ?? new JObject(),
                    ["user_id"] = userId,
                };
                await SendJsonAsync(payload);
                if (verboseLogging) Debug.Log($"[HermesBridge] SendTask: {name} (task_id={taskId})");

                // 等 task_result / task_failed、或 timeout
                var timeoutTask = Task.Delay(TimeSpan.FromSeconds(timeoutSec));
                var completedTask = await Task.WhenAny(tcs.Task, timeoutTask);

                if (completedTask == timeoutTask)
                {
                    // 超時 — 從 pending 移除、拋 TimeoutException
                    lock (_pendingTasksLock)
                    {
                        _pendingTasks.Remove(taskId);
                    }
                    throw new TimeoutException(
                        $"[HermesBridge] SendTask {name!} (task_id={taskId}) 超過 {timeoutSec}s 沒回 result"
                    );
                }

                return await tcs.Task;  // task_result 時是 JObject；task_failed 會 throw SendTaskException
            }
            finally
            {
                // 不論成功失敗、確保 pending 移除（避免重複 SetResult）
                lock (_pendingTasksLock)
                {
                    _pendingTasks.Remove(taskId);
                }
            }
        }

        /// <summary>
        /// 連線中斷時 cancel 所有 pending SendTask
        /// 呼叫端會收到 OperationCanceledException、可以選擇 retry
        /// </summary>
        private void CancelAllPendingTasks(string reason)
        {
            List<TaskCompletionSource<JObject>> toCancel;
            lock (_pendingTasksLock)
            {
                toCancel = new List<TaskCompletionSource<JObject>>(_pendingTasks.Values);
                _pendingTasks.Clear();
            }
            foreach (var tcs in toCancel)
            {
                tcs.TrySetException(new OperationCanceledException(
                    $"[HermesBridge] SendTask cancelled: {reason}"
                ));
            }
            if (toCancel.Count > 0 && verboseLogging)
            {
                Debug.LogWarning($"[HermesBridge] 已 cancel {toCancel.Count} 個 pending SendTask（{reason}）");
            }
        }

        // ==================== 重連邏輯 ====================

        private void StartReconnect()
        {
            if (_reconnectCoroutine != null) return;
            _reconnectCoroutine = StartCoroutine(ReconnectLoop());
        }

        /// <summary>
        /// v1.5+ Computer control：回應 confirmation request
        /// 給 ConfirmationDialogUI 按鈕呼叫
        /// </summary>
        /// <param name="confirmationId">從 BridgeConfirmationRequest.confirmation_id 拿</param>
        /// <param name="approved">True=允許 SIRO 跑這個操作、False=拒絕</param>
        public async Task SendConfirmationResponse(string confirmationId, bool approved)
        {
            if (string.IsNullOrEmpty(confirmationId))
            {
                Debug.LogWarning("[HermesBridge] SendConfirmationResponse: confirmation_id 為空");
                return;
            }
            var payload = new JObject
            {
                ["type"] = "confirmation_response",
                ["confirmation_id"] = confirmationId,
                ["approved"] = approved,
            };
            await SendJsonAsync(payload);
            if (verboseLogging) Debug.Log(
                $"[HermesBridge] confirmation_response id={confirmationId} approved={approved}"
            );
        }

        /// <summary>
        /// Phase 2 STT (Day 4):送 mic 32ms chunk 給 bridge
        /// Unity 端 UnityMicInput 在 capture loop 裡呼叫
        /// bridge 收到 → 餵 SileroVAD → 偵測到 PAUSE/RESUME 會回 vad_pause / vad_resume
        ///
        /// 音訊格式:16kHz 16-bit mono PCM、1024 bytes(= 512 samples @ 16kHz = 32ms)
        /// turn_id:Unity 端自己產的 monotonic counter(每個 mic chunk +1)
        /// </summary>
        public async Task SendMicChunkAsync(int turnId, byte[] pcmBytes)
        {
            if (pcmBytes == null || pcmBytes.Length == 0) return;
            var payload = new JObject
            {
                ["type"] = "mic_chunk",
                ["turn_id"] = turnId,
                ["audio_base64"] = Convert.ToBase64String(pcmBytes),
            };
            await SendJsonAsync(payload);
        }

        /// <summary>
        /// Phase 2 STT (Day 4):送文字輸入(從 chat box)帶 turn_id
        /// 跟 chat 一樣的 LLM 流程,但走 TurnManager + 帶 turn_id
        /// </summary>
        public async Task SendTextInputAsync(int turnId, string text, string userId = "default", string personality = "default")
        {
            if (string.IsNullOrWhiteSpace(text)) return;
            var payload = new JObject
            {
                ["type"] = "text_input",
                ["turn_id"] = turnId,
                ["text"] = text,
                ["user_id"] = userId,
                ["personality"] = personality,
            };
            await SendJsonAsync(payload);
        }

        private void StopReconnect()
        {
            if (_reconnectCoroutine != null)
            {
                StopCoroutine(_reconnectCoroutine);
                _reconnectCoroutine = null;
            }
        }

        /// <summary>截斷 log 用的 JSON 預覽(避免 base64 audio 把 console 灌爆)。</summary>
        private static string TruncateForLog(string s, int maxLen = 200)
        {
            if (string.IsNullOrEmpty(s)) return s;
            if (s.Length <= maxLen) return s;
            return s.Substring(0, maxLen) + $"... (truncated, total {s.Length} chars)";
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
            // Day 8.9 fix:WS frame 可能 > 4096 bytes(bridge 推的 tts_audio / vad_resume
            // 帶 audio_base64 通常 10-200KB)。原本用 4096 buffer 直接讀就壞掉。
            // 修法:用 List<byte> 累積跨 frame,直到 result.EndOfMessage 才 parse。
            var buffer = new byte[4096];
            var messageBytes = new System.Collections.Generic.List<byte>();

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

                    // 累積這次 frame 的 bytes
                    messageBytes.AddRange(new System.ArraySegment<byte>(buffer, 0, result.Count));

                    if (result.EndOfMessage)
                    {
                        // Frame 完整收到才 parse JSON
                        var json = Encoding.UTF8.GetString(messageBytes.ToArray());
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] 收到 ({messageBytes.Count} bytes): {TruncateForLog(json)}"
                        );

                        HandleMessage(json);
                        messageBytes.Clear();
                    }
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
                // v1.2 SendTask：cancel 所有 pending、caller 收到 OperationCanceledException
                CancelAllPendingTasks("連線中斷");
                OnBridgeDisconnected?.Invoke();
                if (verboseLogging) Debug.Log("[HermesBridge] 連線中斷");
                if (autoReconnect && _shouldRun) StartReconnect();
            }
            else
            {
                // receive loop 結束但 _isConnected 早就是 false（被 DisconnectAsync 設的）
                // 仍然要 cancel pending、避免 caller 永遠等
                CancelAllPendingTasks("receive loop 結束");
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

                    case "task_ack":
                        // v1.2 SendTask：bridge 已收下 task、進 registry
                        // SendTaskAsync 本身不等 ack（直接等 result），所以這裡只給訂閱者 log
                        if (verboseLogging) Debug.Log($"[HermesBridge] task_ack: {j["task_id"]}");
                        break;

                    case "motion_play":
                        // v1.5+ LLM tool calling 觸發 motion 播放
                        // bridge 端 LLM 透過 play_motion tool 決定要播哪個 motion、
                        // 推 {"type":"motion_play","motion_group":"...","motion_index":N} 給 Unity
                        // Unity 訂閱 OnBridgeMotionPlay 處理（Live2DModelController 訂閱 → 呼叫 PlayMotion）
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] motion_play: {j["motion_group"]}[{j["motion_index"]}]"
                        );
                        var motionPlay = j.ToObject<BridgeMotionPlay>();
                        OnBridgeMotionPlay?.Invoke(motionPlay);
                        break;

                    case "tts_audio":
                        // Phase 1.5.2b: 句子級 TTS audio chunk
                        // bridge 推 {"type":"tts_audio","index":N,"turn_id":N,"sentence":"...","format":"wav","audio_base64":"...","provider":"f5-tts"}
                        // UnityTTSPlayer 訂閱 OnBridgeTtsAudio、decode base64 → AudioClip → 排隊播放
                        // Phase 2 STT (Day 4):ttsAudio.turn_id > 0 時,UnityTTSPlayer 會過濾不符 current turn 的 chunk
                        var ttsAudio = j.ToObject<BridgeTtsAudio>();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] tts_audio #{ttsAudio.index} turn={ttsAudio.turn_id}: "
                            + $"len={ttsAudio.sentence?.Length ?? 0} format={ttsAudio.format} provider={ttsAudio.provider}"
                        );
                        OnBridgeTtsAudio?.Invoke(ttsAudio);
                        break;

                    case "vad_pause":
                        // Phase 2 STT (Day 4):VAD 偵測到 speech start
                        var vadPause = j.ToObject<BridgeVadPause>();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] vad_pause turn_id={vadPause.turn_id}"
                        );
                        OnBridgeVadPause?.Invoke(vadPause);
                        break;

                    case "vad_resume":
                        // Phase 2 STT (Day 4):VAD 偵測到 utterance end
                        var vadResume = j.ToObject<BridgeVadResume>();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] vad_resume turn_id={vadResume.turn_id} duration={vadResume.duration_ms}ms"
                        );
                        OnBridgeVadResume?.Invoke(vadResume);
                        break;

                    case "agent_interrupt":
                        // Phase 2 STT (Day 3):LLM 被打斷通知
                        var agentInterrupt = j.ToObject<BridgeAgentInterrupt>();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] agent_interrupt turn_id={agentInterrupt.turn_id} "
                            + $"last_heard='{agentInterrupt.last_heard}'"
                        );
                        OnBridgeAgentInterrupt?.Invoke(agentInterrupt);
                        break;

                    case "task_result":
                        // v1.2 SendTask 成功 — 從 pending 移除、SetResult
                        var tRes = j.ToObject<BridgeTaskResult>();
                        lock (_pendingTasksLock)
                        {
                            if (_pendingTasks.TryGetValue(tRes.task_id, out var tcs))
                            {
                                _pendingTasks.Remove(tRes.task_id);
                                tcs.TrySetResult(tRes.result);
                            }
                            else
                            {
                                if (verboseLogging) Debug.LogWarning(
                                    $"[HermesBridge] 收到 task_result 但找不到 pending task: {tRes.task_id}"
                                );
                            }
                        }
                        OnTaskResult?.Invoke(tRes);
                        break;

                    case "task_failed":
                        // v1.2 SendTask 失敗 — SetException 讓 SendTaskAsync caller 收到 SendTaskException
                        var tFail = j.ToObject<BridgeTaskFailed>();
                        lock (_pendingTasksLock)
                        {
                            if (_pendingTasks.TryGetValue(tFail.task_id, out var tcs))
                            {
                                _pendingTasks.Remove(tFail.task_id);
                                tcs.TrySetException(new SendTaskException(tFail.task_id, tFail.error));
                            }
                            else
                            {
                                if (verboseLogging) Debug.LogWarning(
                                    $"[HermesBridge] 收到 task_failed 但找不到 pending task: {tFail.task_id}"
                                );
                            }
                        }
                        OnTaskFailed?.Invoke(tFail);
                        break;

                    case "confirmation_request":
                        // v1.5+ SIRO 想跑危險操作（shell install / delete memory / 任何 confirm 類 tool）
                        // 訂閱者（ConfirmationDialogUI）顯示 modal dialog、按按鈕後呼叫 SendConfirmationResponse
                        var confReq = j.ToObject<BridgeConfirmationRequest>();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] confirmation_request id={confReq.confirmation_id} tool={confReq.tool} desc={confReq.description}"
                        );
                        OnBridgeConfirmationRequest?.Invoke(confReq);
                        break;

                    case "confirmation_acked":
                        // v1.5+ bridge 收到 confirmation_response 後 ack — UI 可以關掉 dialog
                        var confAck = j.ToObject<BridgeConfirmationAcked>();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] confirmation_acked id={confAck.confirmation_id} resolved={confAck.resolved}"
                        );
                        OnBridgeConfirmationAcked?.Invoke(confAck);
                        break;

                    case "tool_action":
                        // v1.5+ agent mode：SIRO 跑每個 tool 時即時推（給 UI 做 tool-call feed）
                        var toolAct = (JObject)j.DeepClone();
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] tool_action: {toolAct["tool"]} ok={toolAct["ok"]} ({toolAct["duration_ms"]}ms)"
                        );
                        OnBridgeToolAction?.Invoke(toolAct);
                        break;

                    case "system_event":
                        // v0.3.0 Phase 3 siro-runtime → bridge → Unity WS 的 system event
                        // 留 default log 給既有訂閱者接（不在這檔處理細節）
                        if (verboseLogging) Debug.Log(
                            $"[HermesBridge] system_event: {j["event_type"]} data={j["data"]}"
                        );
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
