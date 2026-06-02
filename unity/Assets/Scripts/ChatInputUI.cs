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
            if (_bridge == null) _bridge = FindObjectOfType<HermesBridgeClient>();

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
            }
        }

        private void Update()
        {
            if (sendOnEnter && _bridge != null && _bridge.IsConnected)
            {
                // Enter 鍵送出（要 InputField 沒 focus 時才觸發，避免打字的 Enter 誤觸）
                if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
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

        private void HandleDisconnected()
        {
            SetResponse("（已斷線，請重啟 Play 模式）");
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
