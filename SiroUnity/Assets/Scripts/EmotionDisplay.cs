// unity/Assets/Scripts/EmotionDisplay.cs
//
// 把 bridge 回傳的 emotion 翻譯成 Live2D 動作。
// 掛在跟 Live2DModelController 同一個 GameObject 上。
//

using UnityEngine;

namespace Siro
{
    [RequireComponent(typeof(Live2DModelController))]
    public class EmotionDisplay : MonoBehaviour
    {
        [Header("References")]
        public HermesBridgeClient bridgeClient;

        [Header("Emotion → Expression Mapping")]
        [Tooltip("Mao 8 個 expression 已用 ExpressionViewer 校準 (v0.3)。" +
                 "9 情緒對應 8 表情：happy/neutral 共用 exp_01，其他一對一。")]
        public string expressionHappy = "exp_01";      // 開心
        public string expressionJoyful = "exp_02";     // 快樂（哈哈大笑）
        public string expressionProud = "exp_03";      // 驕傲
        public string expressionExcited = "exp_04";    // 興奮
        public string expressionSad = "exp_05";        // 難過
        public string expressionThinking = "exp_06";   // 害羞 ≈ 思考
        public string expressionSurprised = "exp_07";  // 驚訝
        public string expressionAngry = "exp_08";      // 生氣
        public string expressionNeutral = "exp_01";    // 借用 happy（中性偏正面）

        [Header("Debug")]
        public bool verboseLogging = true;

        private Live2DModelController _modelController;

        private void Awake()
        {
            _modelController = GetComponent<Live2DModelController>();
        }

        private void Start()
        {
            if (bridgeClient != null)
            {
                bridgeClient.OnBridgeResponse += HandleBridgeResponse;
                bridgeClient.OnBridgeDisconnected += HandleBridgeDisconnected;
                bridgeClient.OnBridgeConnected += HandleBridgeConnected;
                if (verboseLogging) Debug.Log("[EmotionDisplay] 已訂閱 bridge response + connect/disconnect");
            }
            else
            {
                // 改成 info 等級（v0 開發期不阻擾，之後真正接 bridge 再警告）
                if (verboseLogging)
                {
                    Debug.Log("[EmotionDisplay] 沒有指派 bridgeClient（可在 Inspector 拖 HermesBridgeClient 進來）");
                }
            }
        }

        private void OnDestroy()
        {
            if (bridgeClient != null)
            {
                bridgeClient.OnBridgeResponse -= HandleBridgeResponse;
                bridgeClient.OnBridgeDisconnected -= HandleBridgeDisconnected;
                bridgeClient.OnBridgeConnected -= HandleBridgeConnected;
            }
        }

        // ==================== 內部 ====================

        // 斷線時自動切 thinking 表情（GAPS.md #9 降級路徑 UX）
        // 比「Mao 一動也不動」好 — 讓使用者感覺角色「在想/在等」
        private void HandleBridgeDisconnected()
        {
            if (verboseLogging) Debug.Log("[EmotionDisplay] bridge 斷線 → 切 thinking 表情");
            if (_modelController != null)
            {
                _modelController.SetExpression(expressionThinking);
            }
        }

        // 重連成功時切回 neutral（預設臉），等下一句對話再切真情緒
        private void HandleBridgeConnected()
        {
            if (verboseLogging) Debug.Log("[EmotionDisplay] bridge 連線 → 切 neutral");
            if (_modelController != null)
            {
                _modelController.SetExpression(expressionNeutral);
            }
        }

        private void HandleBridgeResponse(BridgeResponse response)
        {
            if (response == null || string.IsNullOrEmpty(response.emotion))
            {
                Debug.LogWarning("[EmotionDisplay] 收到空的 response");
                return;
            }

            var expressionId = MapEmotionToExpression(response.emotion);

            if (verboseLogging) Debug.Log(
                $"[EmotionDisplay] 收到情緒: {response.emotion} → expression: {expressionId}"
            );

            // 觸發 Live2D 表情切換
            if (_modelController != null)
            {
                _modelController.SetExpression(expressionId);
            }
        }

        private string MapEmotionToExpression(string emotion)
        {
            return emotion.ToLower() switch
            {
                "happy" => expressionHappy,
                "joyful" => expressionJoyful,
                "proud" => expressionProud,
                "sad" => expressionSad,
                "angry" => expressionAngry,
                "surprised" => expressionSurprised,
                "thinking" => expressionThinking,
                "excited" => expressionExcited,
                "neutral" => expressionNeutral,
                _ => expressionNeutral,
            };
        }
    }
}
