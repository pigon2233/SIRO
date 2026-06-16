// unity/Assets/Scripts/ChatInputUI.cs
//
// 簡單的聊天 UI 邏輯。
// - InputField 輸入文字
// - Send 按鈕 / Enter 送出
// - ResponseText 顯示 agent 回應
//
// 掛在一個有空 HermesBridgeClient、InputField、Button、Text 的 GameObject 上。
//

using UnityEngine;
using UnityEngine.UI;
using TMPro;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace Siro
{
    public class ChatInputUI : MonoBehaviour
    {
        [Header("UI References")]
        public InputField inputField;        // 舊版 UI
        public TMP_InputField tmpInputField; // TextMeshPro（推薦）
        public Button sendButton;
        public Text responseText;            // 舊版 UI
        public TMP_Text tmpResponseText;     // TextMeshPro

        [Header("Behavior")]
        public bool sendOnEnter = true;
        public bool clearAfterSend = true;

        [Header("Status")]
        public string placeholderText = "輸入訊息...";

        [Header("Phase 2 STT (optional)")]
        [Tooltip("如果設了,共用 UnityMicInput 的 turn_id counter(讓 chat box 跟 mic 共享 monotonic ID)")]
        public UnityMicInput micInput;
        [Tooltip("如果設了,送出時會呼叫 SetCurrentTurnId(立即停舊 TTS)")]
        public UnityTTSPlayer ttsPlayer;

        private HermesBridgeClient _bridge;

        // v0.3.1 SSE streaming：累積 delta 用的 buffer
        // 每次「送出 chat」清空、第一個 delta 開始累積、最終 response 抵達時由 SetResponse 蓋掉
        // 不暴露給 inspector（純內部狀態）
        private System.Text.StringBuilder _streamingBuffer;
        // v1.2+：送出 chat 後 disable input、避免連點 / 重送
        // 收到 response / error / 連線斷 才 re-enable
        private bool _isWaitingForResponse = false;
        // 動畫「思考中.」dots 的 coroutine handle
        private Coroutine _thinkingDotsCoroutine;

        private void Start()
        {
            // 找 bridge：自己身上、或同 parent
            _bridge = GetComponent<HermesBridgeClient>();
            if (_bridge == null) _bridge = GetComponentInParent<HermesBridgeClient>();
            if (_bridge == null) _bridge = FindFirstObjectByType<HermesBridgeClient>();

            if (_bridge == null)
            {
                Debug.LogError("[ChatInputUI] 找不到 HermesBridgeClient");
                return;
            }

            // 訂閱事件
            _bridge.OnBridgeResponse += HandleResponse;
            _bridge.OnBridgeError += HandleError;
            _bridge.OnBridgeDelta += HandleDelta;            // v0.3.1 SSE streaming
            _bridge.OnBridgeConnected += HandleConnected;
            _bridge.OnBridgeDisconnected += HandleDisconnected;
            _bridge.OnReconnectAttempt += HandleReconnectAttempt;

            // 按鈕
            if (sendButton != null)
            {
                sendButton.onClick.AddListener(OnSendClicked);
            }

            // 預設提示（i18n）
            SetResponse(Localization.Get("ui.connect.waiting"));
        }

        private void OnDestroy()
        {
            if (_bridge != null)
            {
                _bridge.OnBridgeResponse -= HandleResponse;
                _bridge.OnBridgeError -= HandleError;
                _bridge.OnBridgeDelta -= HandleDelta;
                _bridge.OnBridgeConnected -= HandleConnected;
                _bridge.OnBridgeDisconnected -= HandleDisconnected;
                _bridge.OnReconnectAttempt -= HandleReconnectAttempt;
            }
        }

        private void Update()
        {
            if (sendOnEnter && _bridge != null && _bridge.IsConnected)
            {
                bool enterPressed = false;
#if ENABLE_INPUT_SYSTEM
                // 新 Input System：Keyboard.current
                if (Keyboard.current != null)
                {
                    if (Keyboard.current.enterKey.wasPressedThisFrame ||
                        Keyboard.current.numpadEnterKey.wasPressedThisFrame)
                    {
                        enterPressed = true;
                    }
                }
#else
                // 舊 Input Manager
                if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
                {
                    enterPressed = true;
                }
#endif
                if (enterPressed)
                {
                    if (GetInputField() != null && !GetInputField().isFocused)
                    {
                        OnSendClicked();
                    }
                }
            }
        }

        // ==================== 公開 ====================

        public void OnSendClicked()
        {
            var input = GetInputField();
            if (input == null)
            {
                Debug.LogWarning("[ChatInputUI] 沒有 InputField");
                return;
            }

            var text = input.text?.Trim();
            if (string.IsNullOrEmpty(text))
            {
                return;
            }

            if (_bridge == null || !_bridge.IsConnected)
            {
                SetResponse(Localization.Get("ui.connect.disconnected"));
                return;
            }

            SetResponse(Localization.Get("ui.send.thinking"));
            // v0.3.1 SSE streaming：清空累積 buffer，等 delta 開始 append
            _streamingBuffer = new System.Text.StringBuilder();
            // v1.2+：disable input 防連點 + 啟動動畫 dots
            SetInputEnabled(false);
            _isWaitingForResponse = true;
            if (_thinkingDotsCoroutine != null) StopCoroutine(_thinkingDotsCoroutine);
            _thinkingDotsCoroutine = StartCoroutine(AnimateThinkingDots());

            // Phase 2 STT (Day 5):用 text_input 帶 turn_id
            // 跟 mic 共用 counter(透過 UnityMicInput.NextTurnId)→ 跟 mic chunk 用同個 ID 空間
            // 這樣 bridge 端 TurnManager 知道是「同一個對話脈絡」的 turn
            if (micInput != null)
            {
                int turnId = micInput.NextTurnId();
                if (ttsPlayer != null) ttsPlayer.SetCurrentTurnId(turnId);
                _ = _bridge.SendTextInputAsync(turnId, text, userId: "default", personality: "default");
            }
            else
            {
                // 沒接 mic、legacy chat 流程(沒 turn_id)
                _ = _bridge.SendChatAsync(text);
            }

            if (clearAfterSend)
            {
                input.text = "";
            }
        }

        // ==================== v1.2+ Loading 視覺 ====================

        private void SetInputEnabled(bool enabled)
        {
            var input = GetInputField();
            if (input != null) input.interactable = enabled;
            if (sendButton != null) sendButton.interactable = enabled;
        }

        /// <summary>
        /// 動畫「思考中.」dots 迴圈 — 0/1/2/3 個點循環、給使用者視覺「還在跑」的感覺
        /// 收到 response / error 就被 stop
        /// </summary>
        private System.Collections.IEnumerator AnimateThinkingDots()
        {
            string baseText = Localization.Get("ui.send.thinking").TrimEnd('.', ' ');
            // 拿掉尾巴的 "..."（避免疊加）
            if (baseText.EndsWith("...")) baseText = baseText.Substring(0, baseText.Length - 3);
            int dotCount = 0;
            while (_isWaitingForResponse)
            {
                dotCount = (dotCount % 4);  // 0, 1, 2, 3 → 視覺循環
                string dots = new string('.', dotCount);
                SetResponse($"{baseText}{dots}");
                yield return new WaitForSeconds(0.4f);
            }
        }

        // ==================== 事件處理 ====================

        private void HandleResponse(BridgeResponse response)
        {
            if (response == null) return;
            // v1.2+：response 收到、re-enable input + 停 dots
            _isWaitingForResponse = false;
            if (_thinkingDotsCoroutine != null) StopCoroutine(_thinkingDotsCoroutine);
            SetInputEnabled(true);
            // v0.3.1 SSE streaming：response 是 delta 累積完的最終結果
            // 蓋掉「thinking...」或中途累積的 streaming buffer，
            // 加上情緒標籤（delta 階段還不知道情緒 — 等 LLM 完整跑完才 parse）
            var text = string.IsNullOrEmpty(response.text) ? "（無回應）" : response.text;
            var mood = string.IsNullOrEmpty(response.emotion) ? "" : $" [{response.emotion}]";
            SetResponse($"{text}{mood}");
            // 清掉 buffer，給下一輪送出的 chat 用
            _streamingBuffer = null;
        }

        /// <summary>
        /// v0.3.1 SSE streaming delta handler
        /// bridge 端 SIRO_STREAMING=true 時每個 LLM chunk 觸發一次
        /// 累積到 _streamingBuffer、每次都刷新 UI 文字
        /// 沒開 streaming 時不會觸發（行為跟 v0.2 一樣）
        /// </summary>
        private void HandleDelta(BridgeDelta delta)
        {
            if (delta == null || string.IsNullOrEmpty(delta.text)) return;
            if (_streamingBuffer == null) _streamingBuffer = new System.Text.StringBuilder();
            _streamingBuffer.Append(delta.text);
            // 邊累積邊 render（不附加 emotion tag — 還沒跑完）
            SetResponse(_streamingBuffer.ToString());
        }

        private void HandleError(BridgeError error)
        {
            // v1.2+：error 也 re-enable input
            _isWaitingForResponse = false;
            if (_thinkingDotsCoroutine != null) StopCoroutine(_thinkingDotsCoroutine);
            SetInputEnabled(true);

            var prefix = Localization.Get("ui.send.error_prefix");
            var unknown = Localization.Get("ui.send.unknown_error");
            SetResponse($"{prefix} {error?.detail ?? unknown}");
        }

        private void HandleConnected()
        {
            SetResponse(Localization.Get("ui.connect.connected"));
        }

        // 斷線：bridge 進程死掉、port 改變、WebSocket 收到 close frame。
        // 不要說「重啟 Play」— bridge client 會自動重連，UI 顯示「連線中...」更精準。
        // EmotionDisplay 也會同步切 thinking 表情（GAPS.md #9 降級路徑 UX）。
        private void HandleDisconnected()
        {
            // v1.2+：斷線也要 re-enable input（不然永遠卡住）
            _isWaitingForResponse = false;
            if (_thinkingDotsCoroutine != null) StopCoroutine(_thinkingDotsCoroutine);
            // 斷線時 input 還是不能用（bridge 還沒回），但 disable state 要重置
            // 讓重連後可以重新送 — 由 SetInputEnabled 決定（看 IsConnected）
            SetInputEnabled(false);

            SetResponse(Localization.Get("ui.connect.reconnecting"));
        }

        // 重連嘗試：顯示第幾次嘗試，讓使用者看到「系統還在努力」
        private void HandleReconnectAttempt(int attemptNumber)
        {
            SetResponse(Localization.Get("ui.connect.reconnect_attempt", attemptNumber));
        }

        // ==================== Helper ====================

        private TMP_InputField GetInputField()
        {
            return tmpInputField != null ? tmpInputField : null;
        }

        private void SetResponse(string text)
        {
            if (tmpResponseText != null)
            {
                tmpResponseText.text = text;
            }
            else if (responseText != null)
            {
                responseText.text = text;
            }
        }
    }
}
