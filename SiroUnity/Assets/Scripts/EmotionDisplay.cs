// unity/Assets/Scripts/EmotionDisplay.cs
//
// v0.2 重構：emotion → expression 對照表不再 hardcode 在 Inspector。
// bridge 回應已經帶 `live2d.expression_id`（從 persona YAML 的 model.expressions
// 解析而來），這邊直接拿來用。
//
// v1+ 多角色：當 persona 切換時 PersonaManager 會去拿新 persona 的 quirk 設定
// 套用到 Live2DModelController（hide_eye_on_expressions、eye_drawable_indices）。

using UnityEngine;

namespace Siro
{
    [RequireComponent(typeof(Live2DModelController))]
    public class EmotionDisplay : MonoBehaviour
    {
        [Header("References")]
        public HermesBridgeClient bridgeClient;

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
        // v0.2：bridge 回傳的 expression_id 是 thinking 對應的 exp_06
        // 這裡寫死是因為「斷線狀態」不需要 persona 客製 — 用通用 exp_06
        private const string THINKING_EXPRESSION_ID = "exp_06";

        private void HandleBridgeDisconnected()
        {
            if (verboseLogging) Debug.Log("[EmotionDisplay] bridge 斷線 → 切 thinking 表情");
            if (_modelController != null)
            {
                _modelController.SetExpression(THINKING_EXPRESSION_ID);
            }
        }

        // 重連成功時切回 neutral（預設臉），等下一句對話再切真情緒
        private void HandleBridgeConnected()
        {
            if (verboseLogging) Debug.Log("[EmotionDisplay] bridge 連線 → 切 neutral");
            if (_modelController != null)
            {
                // v0.2：neutral 也用 exp_06（思考中），跟原本邏輯一致
                _modelController.SetExpression(THINKING_EXPRESSION_ID);
            }
        }

        // v0.2：bridge 已經把 emotion→expression_id 對照做完
        // 直接用 response.live2d.expression_id，不做本地對照
        private void HandleBridgeResponse(BridgeResponse response)
        {
            if (response == null || response.live2d == null)
            {
                Debug.LogWarning("[EmotionDisplay] 收到空的 response 或無 live2d 訊號");
                return;
            }

            var expressionId = response.live2d.expression_id;
            if (string.IsNullOrEmpty(expressionId))
            {
                Debug.LogWarning($"[EmotionDisplay] response.live2d.expression_id 是空（emotion={response.emotion}）");
                return;
            }

            if (verboseLogging) Debug.Log(
                $"[EmotionDisplay] 收到情緒: {response.emotion} → expression: {expressionId}"
            );

            if (_modelController != null)
            {
                _modelController.SetExpression(expressionId);
            }
        }
    }
}
