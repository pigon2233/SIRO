// unity/Assets/Scripts/Live2DModelController.cs
//
// 控制 Cubism Live2D 模型的 component。
// - 切換 expression (F01-F06 對 Hiyori)
// - 播放 motion (Idle, FlickHead, TapBody...)
//
// 使用：
//   - 掛在 Live2D 模型的 GameObject 上（會自動抓 CubismModel 與 components）
//   - 從 EmotionDisplay 呼叫 SetExpression(expressionId)
//

using System.Collections;
using System.Collections.Generic;
using Live2D.Cubism.Framework.Expression;
using Live2D.Cubism.Framework.Motion;
using UnityEngine;

namespace Siro
{
    [RequireComponent(typeof(CubismModel))]
    public class Live2DModelController : MonoBehaviour
    {
        [Header("Debug")]
        public bool verboseLogging = true;

        private CubismModel _model;
        private CubismExpressionController _expressionController;
        private CubismMotionController _motionController;

        // 暫存目前的 expression 名稱，避免重複觸發
        private string _currentExpressionId = "";
        private Coroutine _blendCoroutine;

        private void Awake()
        {
            _model = GetComponent<CubismModel>();
            _expressionController = GetComponent<CubismExpressionController>();
            _motionController = GetComponent<CubismMotionController>();
        }

        private void Start()
        {
            if (_expressionController == null)
            {
                Debug.LogWarning(
                    "[Live2DModelController] 找不到 CubismExpressionController，" +
                    "請確認 Hiyori 模型的 prefab 包含 expression controller component"
                );
            }
            if (_motionController == null)
            {
                Debug.LogWarning(
                    "[Live2DModelController] 找不到 CubismMotionController"
                );
            }
        }

        // ==================== 公開 API ====================

        /// <summary>
        /// 切換 expression。
        /// </summary>
        /// <param name="expressionId">Cubism expression ID，如 "F02" (happy)</param>
        /// <param name="blendDuration">過渡時間（秒），預設 0.5s 平滑切換</param>
        public void SetExpression(string expressionId, float blendDuration = 0.5f)
        {
            if (_expressionController == null)
            {
                if (verboseLogging) Debug.LogWarning("[Live2DModelController] 無 expression controller");
                return;
            }

            if (string.IsNullOrEmpty(expressionId))
            {
                if (verboseLogging) Debug.LogWarning("[Live2DModelController] expressionId 為空");
                return;
            }

            if (expressionId == _currentExpressionId)
            {
                // 同一個 expression，不重複觸發
                return;
            }

            // 找到對應的 CubismExpressionData
            var expressions = _expressionController.ExpressionsList;
            int targetIndex = -1;
            for (int i = 0; i < expressions?.Count; i++)
            {
                if (expressions[i]?.name == expressionId)
                {
                    targetIndex = i;
                    break;
                }
            }

            if (targetIndex < 0)
            {
                if (verboseLogging) Debug.LogWarning(
                    $"[Live2DModelController] 找不到 expression: {expressionId}，" +
                    $"確認 Hiyori 模型的 .exp3.json 檔名是 {expressionId}"
                );
                return;
            }

            // 觸發 expression
            if (blendCoroutine != null) StopCoroutine(_blendCoroutine);
            _blendCoroutine = StartCoroutine(BlendExpressionRoutine(targetIndex, blendDuration));

            _currentExpressionId = expressionId;
            if (verboseLogging) Debug.Log($"[Live2DModelController] 切到 expression: {expressionId}");
        }

        /// <summary>
        /// 播放指定 motion 群組的某個 motion。
        /// </summary>
        /// <param name="group">motion 群組名，如 "Idle", "TapBody"</param>
        /// <param name="index">群組內的 motion index，預設 0</param>
        /// <param name="priority">優先級，預設 2 (CubismMotionPriority 標準)</param>
        public void PlayMotion(string group, int index = 0, int priority = 2)
        {
            if (_motionController == null)
            {
                if (verboseLogging) Debug.LogWarning("[Live2DModelController] 無 motion controller");
                return;
            }

            if (string.IsNullOrEmpty(group)) return;

            // Cubism SDK 內建 Animator 觸發
            var animator = GetComponent<Animator>();
            if (animator != null)
            {
                // 假設 motion 群組對應 Animator 的 trigger
                // 這部分要看實際 Hiyori 模型的 Animator 怎麼設
                Debug.Log($"[Live2DModelController] 想播 motion: {group}[{index}]，" +
                          "需要確認 Animator 設定");
            }
            else
            {
                if (verboseLogging) Debug.Log(
                    $"[Live2DModelController] 無 Animator，" +
                    $"想播 motion {group}[{index}] 但無法觸發"
                );
            }
        }

        // ==================== 內部 ====================

        private IEnumerator BlendExpressionRoutine(int targetIndex, float duration)
        {
            // 簡單的過渡：直接觸發 expression（Cubism Expression Controller 內部會 blend）
            if (duration <= 0)
            {
                _expressionController.CurrentExpressionIndex = targetIndex;
            }
            else
            {
                // 這裡可以加更細緻的 blend 控制，v0 先用預設行為
                _expressionController.CurrentExpressionIndex = targetIndex;

                // 等過渡時間過去（純粹視覺延遲，避免連點）
                yield return new WaitForSeconds(duration);
            }
        }
    }
}
