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
            _bridge.OnBridgeConnected += HandleConnected;
            _bridge.OnBridgeDisconnected += HandleDisconnected;
            _bridge.OnReconnectAttempt += HandleReconnectAttempt;

            // 按鈕
            if (sendButton != null)
            {
                sendButton.onClick.AddListener(OnSendClicked);
            }

            // 預設提示
            SetResponse("（等待連線...）");
        }

        private void OnDestroy()
        {
            if (_bridge != null)
            {
                _bridge.OnBridgeResponse -= HandleResponse;
                _bridge.OnBridgeError -= HandleError;
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
                SetResponse("（尚未連線到 bridge，請確認 bridge/main.py 啟動了）");
                return;
            }

            SetResponse("（思考中...）");
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
            var text = string.IsNullOrEmpty(response.text) ? "（無回應）" : response.text;
            var mood = string.IsNullOrEmpty(response.emotion) ? "" : $" [{response.emotion}]";
            SetResponse($"{text}{mood}");
        }

        private void HandleError(BridgeError error)
        {
            SetResponse($"[錯誤] {error?.detail ?? "未知錯誤"}");
        }

        private void HandleConnected()
        {
            SetResponse("（已連線，輸入訊息開始對話）");
        }

        // 斷線：bridge 進程死掉、port 改變、WebSocket 收到 close frame。
        // 不要說「重啟 Play」— bridge client 會自動重連，UI 顯示「連線中...」更精準。
        // EmotionDisplay 也會同步切 thinking 表情（GAPS.md #9 降級路徑 UX）。
        private void HandleDisconnected()
        {
            SetResponse("（連線中...）");
        }

        // 重連嘗試：顯示第幾次嘗試，讓使用者看到「系統還在努力」
        private void HandleReconnectAttempt(int attemptNumber)
        {
            SetResponse($"（連線中... 第 {attemptNumber} 次嘗試）");
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
