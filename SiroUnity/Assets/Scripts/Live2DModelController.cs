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
using UnityEngine.EventSystems;
using System;  // v0.2+ PlayMotion 用 try/catch

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
    public class Live2DModelController : MonoBehaviour, IPointerClickHandler
    {
        [Header("Debug")]
        public bool verboseLogging = true;

        [Header("Idle Motion (v0.2 待機動作)")]
        [Tooltip("待機動作。Start() 自動 loop 播放。" +
                 "Mao 預設拖入 mtn_01.anim（5.57s 呼吸 loop）。\n" +
                 "v0.2+ 可由 persona YAML 的 idle_motions 覆寫（待 v1 擴充）。")]
        public AnimationClip idleMotion;
        [Tooltip("Start 自動播放 idle")]
        public bool autoPlayIdle = true;

        [Header("Eye-Hiding Hack (workaround for Mao 閉眼設計不完整)")]
        [Tooltip("切到下列 expression 時，會把 eyeDrawableIndices 指到的 Drawable MeshRenderer 隱藏，" +
                 "避免閉眼但瞳孔露出的視覺問題。用 Tools/SIRO/Drawable Inspector 找出眼球的 index。\n\n" +
                 "v0.2+：可由 PersonaManager.SetQuirks() 在 persona 切換時 runtime 覆寫。")]
        public string[] hideEyeOnExpressions = new[] { "exp_02", "exp_03" };

        [Header("v1.2 Click Detection (SendTask OnClick)")]
        [Tooltip("啟用滑鼠點擊 Mao 觸發 OnMaoClicked event。" +
                 "需要 Mao prefab 有 2D Collider（給 OnPointerClick 用）。" +
                 "v1.2 MVP：只用單一 hit area = 'body'，不做 head/body 細分。\n" +
                 "v1.5+ 可改用 Cubism SDK 的 CubismHitDrawable 精確區分。")]
        public bool clickable = true;
        [Tooltip("眼球 Drawable 的 index（Mao 預設 [87, 92]，用 Tools/SIRO/Drawable Inspector 找出）\n\n" +
                 "v0.2+：可由 PersonaManager.SetQuirks() 在 persona 切換時 runtime 覆寫。")]
        public int[] eyeDrawableIndices = new[] { 87, 92 };

#if SIRO_HAS_CUBISM
        private CubismModel _model;
        private CubismExpressionController _expressionController;
        private CubismMotionController _motionController;
        private MeshRenderer[] _eyeRenderers;  // 預存的眼球 MeshRenderer（依 eyeDrawableIndices）
#endif

        // 暫存目前的 expression 名稱，避免重複觸發
        private string _currentExpressionId = "";
        private Coroutine _blendCoroutine;

        // ==================== v0.2 Persona 切換支援 ====================

        /// <summary>
        /// v0.2+：PersonaManager 切換 persona 時呼叫，覆寫 quirks 設定
        /// （hide_eye_on_expressions、eye_drawable_indices）。
        /// </summary>
        /// <remarks>
        /// 會在下一個 SetExpression 自動套用新設定。
        /// 對同 prefab 的「表情集不同」角色很有用 — 換 quirk 不用重 build prefab。
        /// </remarks>
        public void SetQuirks(string[] hideEyeOnExpressions, int[] eyeDrawableIndices)
        {
            this.hideEyeOnExpressions = hideEyeOnExpressions ?? new string[0];
            this.eyeDrawableIndices = eyeDrawableIndices ?? new int[0];

#if SIRO_HAS_CUBISM
            // 重新 cache eye renderers（如果 index 變了）
            if (_eyeRenderers != null)
            {
                CacheEyeRenderers();
                // 重新套用當前 expression 的 eye 隱藏邏輯
                if (!string.IsNullOrEmpty(_currentExpressionId))
                {
                    SetEyeRenderersVisible(ShouldHideEyeFor(_currentExpressionId));
                }
            }
#endif

            if (verboseLogging) Debug.Log(
                $"[Live2DModelController] SetQuirks: hide_eye_on={string.Join(",", this.hideEyeOnExpressions)}, " +
                $"eye_indices=[{string.Join(",", this.eyeDrawableIndices)}]"
            );
        }

#if SIRO_HAS_CUBISM
        private void Awake()
        {
            _model = GetComponent<CubismModel>();
            _expressionController = GetComponent<CubismExpressionController>();
            _motionController = GetComponent<CubismMotionController>();
            // 注意：CacheEyeRenderers() 移到 Start()，因為 Cubism Drawable
            // 在 Awake 階段不一定 ready（Cubism 內部需要 Awake 完整跑完）。
        }

        /// <summary>
        /// 預存 eyeDrawableIndices 指到的 MeshRenderer 引用，避免每次切表情都重找。
        /// 用 Tools/SIRO/Drawable Inspector 找出眼球 index 並填到 Inspector。
        /// </summary>
        private void CacheEyeRenderers()
        {
            if (_model == null || eyeDrawableIndices == null || eyeDrawableIndices.Length == 0)
            {
                _eyeRenderers = new MeshRenderer[0];
                return;
            }
            var drawables = _model.Drawables;
            var list = new System.Collections.Generic.List<MeshRenderer>();
            for (int i = 0; i < eyeDrawableIndices.Length; i++)
            {
                int idx = eyeDrawableIndices[i];
                if (idx < 0 || drawables == null || idx >= drawables.Length || drawables[idx] == null)
                {
                    if (verboseLogging) Debug.LogWarning(
                        $"[Live2DModelController] eyeDrawableIndices[{i}]={idx} 越界或為 null，跳過");
                    continue;
                }
                var mr = drawables[idx].GetComponent<MeshRenderer>();
                if (mr != null) list.Add(mr);
            }
            _eyeRenderers = list.ToArray();
            if (verboseLogging) Debug.Log(
                $"[Live2DModelController] 預存 {_eyeRenderers.Length} 個眼球 MeshRenderer 引用");
        }

        /// <summary>
        /// 切換眼球 MeshRenderer.enabled — 用來解決 exp_02/03 閉眼但瞳孔露出的問題。
        /// </summary>
        private void SetEyeRenderersVisible(bool visible)
        {
            if (_eyeRenderers == null) return;
            for (int i = 0; i < _eyeRenderers.Length; i++)
            {
                if (_eyeRenderers[i] != null) _eyeRenderers[i].enabled = visible;
            }
        }

        /// <summary>判斷某個 expressionId 是否在 hideEyeOnExpressions 清單裡。</summary>
        private bool ShouldHideEyeFor(string expressionId)
        {
            if (hideEyeOnExpressions == null || hideEyeOnExpressions.Length == 0) return false;
            string normalized = NormalizeExpressionName(expressionId);
            for (int i = 0; i < hideEyeOnExpressions.Length; i++)
            {
                if (NormalizeExpressionName(hideEyeOnExpressions[i]) == normalized) return true;
            }
            return false;
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
                // v0 預期 motion 是 disabled（DisableMaoAnimator 工具做了這件事）
                // 這不是錯，只 log 一次 info-level
                if (verboseLogging)
                {
                    Debug.Log("[Live2DModelController] CubismMotionController 是 null（預期行為：motion 停用）");
                }
            }

            // Cubism Drawable 在 Awake 之後才完全 ready，所以 cache 放這
            CacheEyeRenderers();

            // v0.2+：Start 自動播放 idle motion（loop）
            if (autoPlayIdle && idleMotion != null)
            {
                PlayMotion(idleMotion, isLoop: true, fadeInSeconds: 1.0f);
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
        /// v1.2 SendTask：使用者點 Mao 觸發（OnPointerClick 收到時 invoke）
        /// 參數：hit area name — v1.2 MVP 一律回傳 "body"（整體點擊）
        /// v1.5+ 改用 CubismHitDrawable 精確區分 "head"/"body"/自訂
        /// 訂閱者（PersonaClickHandler）會用 hitArea 查 persona YAML 的 clickable_areas
        /// </summary>
        public event Action<string> OnMaoClicked;

        /// <summary>
        /// Unity EventSystems IPointerClickHandler 實作 — 需要 Mao GameObject 上有 Collider2D
        /// 沒 Collider 不會觸發（這是 Unity 標準行為、不是 bug）
        /// </summary>
        public void OnPointerClick(PointerEventData eventData)
        {
            if (!clickable)
            {
                if (verboseLogging) Debug.Log("[Live2DModelController] clickable=false、忽略點擊");
                return;
            }
            // v1.2 MVP：不細分 hit area、整體點擊 = "body"
            // v1.5+ 可依 eventData.position + camera projection 算 local Y 判斷 head vs body
            const string hitArea = "body";
            if (verboseLogging) Debug.Log($"[Live2DModelController] Mao 點擊 (hitArea={hitArea})");
            OnMaoClicked?.Invoke(hitArea);
        }

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
            //
            // 比對策略（寬鬆，去前後常見後綴）：
            //   外部傳的 expressionId 可能是 "exp_06"（乾淨邏輯名）
            //   Cubism asset 的 .name 可能是 "exp_06.exp3"（importer 沒去 .exp3 後綴）
            //   兩邊先 NormalizeExpressionName 再比對，兼容兩種寫法。
            var expressions = _expressionController.ExpressionsList?.CubismExpressionObjects;
            int targetIndex = -1;
            string normalizedTarget = NormalizeExpressionName(expressionId);
            if (expressions != null)
            {
                for (int i = 0; i < expressions.Length; i++)
                {
                    if (expressions[i] == null) continue;
                    string assetName = NormalizeExpressionName(expressions[i].name);
                    if (assetName == normalizedTarget)
                    {
                        targetIndex = i;
                        break;
                    }
                }
            }

            if (targetIndex < 0)
            {
                if (verboseLogging)
                {
                    // 列出實際 asset 名字，方便對照 emotion_mapping.json 跟 EmotionDisplay
                    string available = "(無)";
                    if (expressions != null && expressions.Length > 0)
                    {
                        var names = new System.Text.StringBuilder();
                        for (int i = 0; i < expressions.Length; i++)
                        {
                            if (i > 0) names.Append(", ");
                            names.Append(expressions[i] != null ? expressions[i].name : "<null>");
                        }
                        available = names.ToString();
                    }
                    Debug.LogWarning(
                        $"[Live2DModelController] 找不到 expression: '{expressionId}' " +
                        $"(normalized: '{normalizedTarget}')。" +
                        $"模型實際有的 expressions: [{available}]"
                    );
                }
                return;
            }

            // 觸發 expression
            if (_blendCoroutine != null) StopCoroutine(_blendCoroutine);
            _blendCoroutine = StartCoroutine(BlendExpressionRoutine(targetIndex, blendDuration));

            // Eye-hiding hack（Mao 閉眼設計不完整，exp_02/03 切到時藏眼球 mesh）
            SetEyeRenderersVisible(!ShouldHideEyeFor(expressionId));

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
        /// 播放指定 motion 群組的某個 motion（向後相容舊 API，會 log 警告沒實作）。
        /// v0.2+：請用 PlayMotion(AnimationClip) 重載。
        /// </summary>
        public void PlayMotion(string group, int index = 0, int priority = 2)
        {
            // v0.2+：舊 string-based API 留為 stub — Cubism 5 SDK 用 AnimationClip
            // 不再用 group+index。新 API 是 PlayMotion(AnimationClip, isLoop, fadeInSeconds)
            if (verboseLogging)
            {
                Debug.LogWarning(
                    $"[Live2DModelController] PlayMotion(group='{group}', index={index}) 是舊 API，請改用 PlayMotion(AnimationClip) 重載"
                );
            }
        }

        /// <summary>
        /// v0.2+：直接播 AnimationClip。給 Mao 待機用 mtn_01.anim、tap body 用 mtn_03 之類。
        /// </summary>
        /// <param name="clip">要播的 .anim（AnimationClip）。null 就停掉所有 motion。</param>
        /// <param name="isLoop">是否 loop。idle 用 true、tap 用 false。</param>
        /// <param name="fadeInSeconds">淡入時間（避免突然切換）。預設 1s。</param>
        /// <param name="priority">Cubism priority，預設 Normal (=2)。Idle 設 IdlePriority (=1) 容易被 tap 打斷。</param>
        public void PlayMotion(AnimationClip clip, bool isLoop = true, float fadeInSeconds = 1.0f, int priority = 2)
        {
#if SIRO_HAS_CUBISM
            if (_motionController == null)
            {
                if (verboseLogging) Debug.LogWarning("[Live2DModelController] 無 motion controller，無法播 motion");
                return;
            }

            if (clip == null)
            {
                if (verboseLogging) Debug.Log("[Live2DModelController] PlayMotion(null) — 忽略（沒指定 clip）");
                return;
            }

            try
            {
                // Cubism 5 SDK 5-r.5 API
                _motionController.PlayAnimation(
                    clip,
                    layerIndex: 0,
                    priority: priority,
                    isLoop: isLoop,
                    speed: 1.0f
                );
                if (verboseLogging) Debug.Log(
                    $"[Live2DModelController] PlayMotion: {clip.name} (loop={isLoop}, fade={fadeInSeconds}s)"
                );
            }
            catch (Exception e)
            {
                Debug.LogError($"[Live2DModelController] PlayMotion 失敗: {e.Message}");
            }
#else
            if (verboseLogging)
            {
                Debug.LogWarning(
                    $"[Live2DModelController] PlayMotion({clip.name}) 被忽略，SIRO_HAS_CUBISM 未啟用"
                );
            }
#endif
        }

        /// <summary>
        /// 停止目前播放的 motion（會 fade out）
        /// </summary>
        public void StopMotion(float fadeOutSeconds = 1.0f)
        {
#if SIRO_HAS_CUBISM
            if (_motionController == null) return;
            try
            {
                // Cubism 5 沒有直接的 StopMotion，傳 null clip 會清掉
                _motionController.PlayAnimation(null);
            }
            catch { /* 忽略 — 沒在播就沒事 */ }
#else
            // 沒 SDK 就 no-op
#endif
        }

        // ==================== 內部 ====================

        /// <summary>
        /// 統一化 expression 名字，去掉 Cubism 命名慣例的後綴，方便比對。
        /// 範例：
        ///   "exp_06"        → "exp_06"
        ///   "exp_06.exp3"   → "exp_06"
        ///   "F02.exp3"      → "f02"
        ///   "Happy"         → "happy"
        /// </summary>
        private static string NormalizeExpressionName(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return "";
            string s = raw.Trim();
            // 去掉 Cubism importer 留下的 .exp3 後綴
            if (s.EndsWith(".exp3", System.StringComparison.OrdinalIgnoreCase))
            {
                s = s.Substring(0, s.Length - 5);
            }
            // 大小寫不敏感（emotion_mapping.json / EmotionDisplay 一律小寫，這裡保險）
            return s.ToLowerInvariant();
        }

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
