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
        [Tooltip("預設值對應 Hiyori 的 expression 檔名 (F01-F06)")]
        public string expressionHappy = "F02";
        public string expressionHappy = "exp_02";
        public string expressionSad = "exp_04";
        public string expressionAngry = "exp_03";
        public string expressionSurprised = "exp_08";
        public string expressionThinking = "exp_01";
        public string expressionExcited = "exp_05";
        public string expressionNeutral = "exp_01";

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
                if (verboseLogging) Debug.Log("[EmotionDisplay] 已訂閱 bridge response");
            }
            else
            {
                Debug.LogWarning("[EmotionDisplay] 沒有指派 bridgeClient，" +
                                 "Inspector 上拖 HermesBridgeClient 進來");
            }
        }

        private void OnDestroy()
        {
            if (bridgeClient != null)
            {
                bridgeClient.OnBridgeResponse -= HandleBridgeResponse;
            }
        }

        // ==================== 內部 ====================

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
