// unity/Assets/Scripts/Live2DModelController.cs
//
// 控制 Cubism Live2D 模型的 component。
// - 切換 expression (F01-F06 對 Hiyori)
// - 播放 motion (Idle, FlickHead, TapBody...)
//
// 重要：此腳本依賴 Cubism SDK for Unity。
// 沒裝 SDK 時，所有 Cubism 相關程式碼會被 #if guard 跳過，
// Unity 仍能正常編譯開啟專案（只是功能不會作用）。
//
// 裝完 SDK 後，到 Unity → Project Settings → Player → Other Settings
// → Scripting Define Symbols 加 `SIRO_HAS_CUBISM` 才能啟用完整功能。
//

using UnityEngine;

// 這兩個 namespace 在裝 Cubism SDK 後才存在。
// 用 #if guard 避免沒裝 SDK 時編譯錯誤。
#if SIRO_HAS_CUBISM
using Live2D.Cubism.Core;
using Live2D.Cubism.Framework.Expression;
using Live2D.Cubism.Framework.Motion;
#endif

namespace Siro
{
#if SIRO_HAS_CUBISM
    [RequireComponent(typeof(CubismModel))]
#endif
    public class Live2DModelController : MonoBehaviour
    {
        [Header("Debug")]
        public bool verboseLogging = true;

#if SIRO_HAS_CUBISM
        private CubismModel _model;
        private CubismExpressionController _expressionController;
        private CubismMotionController _motionController;
#endif

        // 暫存目前的 expression 名稱，避免重複觸發
        private string _currentExpressionId = "";
        private Coroutine _blendCoroutine;

#if SIRO_HAS_CUBISM
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
#else
        // 沒 SDK 時的占位 Awake，用來 log 提醒
        private void Awake()
        {
            if (verboseLogging)
            {
                Debug.LogWarning(
                    "[Live2DModelController] SIRO_HAS_CUBISM 未啟用，" +
                    "請到 Project Settings → Player → Other Settings → " +
                    "Scripting Define Symbols 加 `SIRO_HAS_CUBISM` " +
                    "（並先安裝 Cubism SDK for Unity）"
                );
            }
        }
#endif

        // ==================== 公開 API ====================

        /// <summary>
        /// 切換 expression。
        /// </summary>
        /// <param name="expressionId">Cubism expression ID，如 "F02" (happy)</param>
        /// <param name="blendDuration">過渡時間（秒），預設 0.5s 平滑切換</param>
        public void SetExpression(string expressionId, float blendDuration = 0.5f)
        {
#if SIRO_HAS_CUBISM
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
            // SDK 5-r.5 的 CubismExpressionList 是一個 ScriptableObject，
            // 真正存資料的是 .CubismExpressionObjects 這個 array。
            var expressions = _expressionController.ExpressionsList?.CubismExpressionObjects;
            int targetIndex = -1;
            if (expressions != null)
            {
                for (int i = 0; i < expressions.Length; i++)
                {
                    if (expressions[i] != null && expressions[i].name == expressionId)
                    {
                        targetIndex = i;
                        break;
                    }
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
            if (_blendCoroutine != null) StopCoroutine(_blendCoroutine);
            _blendCoroutine = StartCoroutine(BlendExpressionRoutine(targetIndex, blendDuration));

            _currentExpressionId = expressionId;
            if (verboseLogging) Debug.Log($"[Live2DModelController] 切到 expression: {expressionId}");
#else
            if (verboseLogging)
            {
                Debug.LogWarning(
                    $"[Live2DModelController] SetExpression({expressionId}) 被忽略，" +
                    "因為 SIRO_HAS_CUBISM 未啟用"
                );
            }
#endif
        }

        /// <summary>
        /// 播放指定 motion 群組的某個 motion。
        /// </summary>
        /// <param name="group">motion 群組名，如 "Idle", "TapBody"</param>
        /// <param name="index">群組內的 motion index，預設 0</param>
        /// <param name="priority">優先級，預設 2 (CubismMotionPriority 標準)</param>
        public void PlayMotion(string group, int index = 0, int priority = 2)
        {
#if SIRO_HAS_CUBISM
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
#else
            if (verboseLogging)
            {
                Debug.LogWarning(
                    $"[Live2DModelController] PlayMotion({group}) 被忽略，" +
                    "因為 SIRO_HAS_CUBISM 未啟用"
                );
            }
#endif
        }

        // ==================== 內部 ====================

#if SIRO_HAS_CUBISM
        private System.Collections.IEnumerator BlendExpressionRoutine(int targetIndex, float duration)
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
#endif
    }
}
