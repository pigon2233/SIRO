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

        private HermesBridgeClient _bridge;

        // v0.3.1 SSE streaming：累積 delta 用的 buffer
        // 每次「送出 chat」清空、第一個 delta 開始累積、最終 response 抵達時由 SetResponse 蓋掉
        // 不暴露給 inspector（純內部狀態）
        private System.Text.StringBuilder _streamingBuffer;

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
            _ = _bridge.SendChatAsync(text);

            if (clearAfterSend)
            {
                input.text = "";
            }
        }

        // ==================== 事件處理 ====================

        private void HandleResponse(BridgeResponse response)
        {
            if (response == null) return;
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
