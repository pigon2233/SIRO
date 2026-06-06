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
                 "Mao 預設拖入 mtn_01.anim（Unity AnimationClip 格式、5.57s 呼吸 loop）。\n" +
                 "注意：是 .anim 檔（Unity AnimationClip）、不是 .fade 檔（Cubism fade motion）。" +
                 "兩個不同、fade 檔是給 Cubism Motion Controller 用的、這欄位吃 anim。\n" +
                 "沒設的話 enableBreathingFallback 會用 scale 模擬呼吸。\n" +
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

        [Header("Expression Blend（K5 KPI < 200ms）")]
        [Tooltip("v1.2 表情切換延遲 < 200ms（量測 SetExpression 到 Cubism render 完成）\n" +
                 "實作：SetExpression 立刻設 CurrentExpressionIndex（Cubism 內部 blend）\n" +
                 "      + 等 blendLockDuration 避免連點時表情亂跳。\n" +
                 "0 = 立即切換（不鎖、給快速 debug 用）。\n" +
                 "0.3-0.5s = 預設、視覺上不閃爍。")]
        public float blendLockDuration = 0.4f;

        [Header("v1.2+ 自然行為（呼吸 / 眨眼）")]
        [Tooltip("啟用自然隨機眨眼 — 每 3-7s 一次、短暫關眼 0.2s。\n" +
                 "30% 機率雙眨眼（自然、人類也會不慎連眨）。\n" +
                 "Mao 沒設定呼吸 mtn_01 時、這個更重要。")]
        public bool enableBlinking = true;
        [Tooltip("眨眼最短間隔（秒）")]
        public float blinkMinInterval = 3.0f;
        [Tooltip("眨眼最長間隔（秒）")]
        public float blinkMaxInterval = 7.0f;
        [Tooltip("單次眨眼總時間（秒）— 0.20 是成人正常眨眼節奏")]
        public float blinkDuration = 0.20f;

        [Tooltip("啟用 scale-based 呼吸 fallback（idleMotion 沒設時用）\n" +
                 "v1.2+ 預設 false：Mao 預設有 mtn_01.anim 設在 idleMotion、走動畫路徑。\n" +
                 "如果 mtn_01 沒設或壞掉、可以勾 true 用 scale 模擬呼吸。\n" +
                 "模擬真實呼吸曲線（吸氣快、hold、吐氣慢）。")]
        public bool enableBreathingFallback = false;
        [Tooltip("呼吸振幅（0.015 = ±1.5%、自然）")]
        public float breathingAmplitude = 0.015f;
        [Tooltip("呼吸週期（秒、預設 4s = 成人正常呼吸節奏）")]
        public float breathingPeriod = 4.0f;
        [Tooltip("加 ±5% 隨機微擾動（避免完美週期、像機器呼吸）")]
        public bool breathingAddJitter = true;

        // 跑 blink / breathing / headSway 的 coroutine handle
        private Coroutine _blinkCoroutine;
        private Coroutine _breathingCoroutine;
        private Coroutine _headSwayCoroutine;

        // v1.2+ 眨眼策略：
        // - 優先 Cubism 參數（用 reflection 抓、不用 SIRO_HAS_CUBISM）
        //   * ParamEyeLOpen / ParamEyeROpen：1 = 開、0 = 閉（標準）
        //   * ParamEyeLClose / ParamEyeRClose：0 = 開、1 = 閉（反向、有些 model 有）
        // - fallback：SetEyeRenderersVisible hide-pupils
        private UnityEngine.Object _eyeLOpenParam;  // 實際是 Cubism.Core.CubismParameter
        private UnityEngine.Object _eyeROpenParam;
        private UnityEngine.Object _eyeLCloseParam;  // 有的 model 才有
        private UnityEngine.Object _eyeRCloseParam;
        private bool _hasCubismBlinkParam = false;

        [Tooltip("啟用頭部微妙晃動 — 給 Mao 活的感覺（不是死的）\n" +
                 "每 4-8s 隨機一次小角度 Y 軸旋轉、模擬「自然擺頭」。\n" +
                 "預設 ±2 度、不影響點擊 hit area（Mao 是 2D Collider 不靠 rotation 命中）。")]
        public bool enableHeadSway = true;
        [Tooltip("頭部晃動最大角度（度）— v1.2 從 2 改 5（2 度 Live2D 平面幾乎看不到）")]
        public float headSwayAngle = 5.0f;
        [Tooltip("頭部晃動最短間隔（秒）")]
        public float headSwayMinInterval = 4.0f;
        [Tooltip("頭部晃動最長間隔（秒）")]
        public float headSwayMaxInterval = 8.0f;
        [Tooltip("眼球 Drawable 的 index（Mao 預設 [87, 92]，用 Tools/SIRO/Drawable Inspector 找出）\n\n" +
                 "v0.2+：可由 PersonaManager.SetQuirks() 在 persona 切換時 runtime 覆寫。")]
        public int[] eyeDrawableIndices = new[] { 87, 92 };

#if SIRO_HAS_CUBISM
        private CubismModel _model;
        private CubismExpressionController _expressionController;
        // v1.2+：Unity Animation component（PlayMotion fallback 用、沒 CubismMotionController 才用）
        // Awake 不抓、首次 PlayMotion 才 GetComponent、需要時自動 AddComponent
        private Animation _unityAnimation;
#if SIRO_HAS_CUBISM
        // v1.2+：PlayMotion 優先用 CubismMotionController（支援 .fade 跟 .anim 兩種）
        // Mao 沒 CubismMotionController 才掉 Unity Animation fallback
        private CubismMotionController _motionController;
#endif
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
#if SIRO_HAS_CUBISM
            _motionController = GetComponent<CubismMotionController>();
#endif
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
            if (verboseLogging)
            {
                // v1.2+ PlayMotion 優先用 CubismMotionController（.fade / .anim 都能播）
                if (_motionController != null)
                {
                    Debug.Log("[Live2DModelController] PlayMotion 用 CubismMotionController");
                }
                else
                {
                    Debug.LogWarning(
                        "[Live2DModelController] Mao 沒有 CubismMotionController、PlayMotion 會掉 " +
                        "Unity Animation fallback（需要 mtn_01.anim 設 Legacy rig 才能正常播）"
                    );
                }
            }

            // Cubism Drawable 在 Awake 之後才完全 ready，所以 cache 放這
            CacheEyeRenderers();

            // v0.2+：Start 自動播放 idle motion（loop）
            if (autoPlayIdle && idleMotion != null)
            {
                PlayMotion(idleMotion, isLoop: true, fadeInSeconds: 1.0f);
            }
            else if (autoPlayIdle && idleMotion == null && enableBreathingFallback)
            {
                // 沒設 mtn_01 但啟用 breathing fallback → 用 scale 模擬呼吸
                // log 提示 user 設 mtn_01 有更高品質
                if (verboseLogging) Debug.Log(
                    "[Live2DModelController] idleMotion 沒設、啟用 scale-based 呼吸 fallback。" +
                    "如果要更高品質、拖 mtn_01.anim 到 idleMotion slot。"
                );
            }

            // v1.2+：自然隨機眨眼
            // 用 reflection 找 Cubism ParamEyeLOpen/ROpen 參數（避免硬 SIRO_HAS_CUBISM 依賴）
            // 有 → 用參數動畫眨眼（真眼皮動）
            // 沒 → fallback hide-pupils
            if (enableBlinking && _model != null)
            {
                TryFindCubismEyeBlinkParams();
            }
            if (enableBlinking)
            {
                bool hasCubismBlink = _hasCubismBlinkParam;
                bool hasFallbackBlink = (_eyeRenderers != null && _eyeRenderers.Length > 0);
                if (hasCubismBlink || hasFallbackBlink)
                {
                    _blinkCoroutine = StartCoroutine(BlinkRoutine());
                    if (verboseLogging) Debug.Log(
                        $"[Live2DModelController] 眨眼 coroutine 啟動 (Cubism={hasCubismBlink}, fallback={hasFallbackBlink})"
                    );
                }
            }
            else if (enableBlinking)
            {
                if (verboseLogging) Debug.Log(
                    "[Live2DModelController] enableBlinking=true 但 eyeDrawableIndices 沒配好、跳過眨眼"
                );
            }

            // v1.2+：scale-based 呼吸 fallback（idleMotion 沒設或關 autoPlayIdle 時）
            if (enableBreathingFallback && (idleMotion == null || !autoPlayIdle))
            {
                _breathingCoroutine = StartCoroutine(BreathingRoutine());
            }

            // v1.2+：頭部微妙晃動
            if (enableHeadSway)
            {
                _headSwayCoroutine = StartCoroutine(HeadSwayRoutine());
                if (verboseLogging) Debug.Log(
                    $"[Live2DModelController] 頭部晃動 coroutine 啟動 (angle=±{headSwayAngle}°, interval={headSwayMinInterval}-{headSwayMaxInterval}s)"
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
        public void SetExpression(string expressionId, float blendDuration = -1f)
        {
            // blendDuration < 0 → 用 inspector blendLockDuration 預設值
            // blendDuration == 0 → 立即切換（不鎖、debug 用）
            // blendDuration > 0 → 切換後鎖定該秒數避免連點
            float effectiveDuration = blendDuration < 0f ? blendLockDuration : blendDuration;
            SetExpressionInternal(expressionId, effectiveDuration);
        }

        private void SetExpressionInternal(string expressionId, float blendDuration)
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
        /// <param name="priority">Cubism priority 預設 Normal (=2)。Idle 設 IdlePriority (=1) 容易被 tap 打斷。</param>
        public void PlayMotion(AnimationClip clip, bool isLoop = true, float fadeInSeconds = 1.0f, int priority = 2)
        {
            if (clip == null)
            {
                if (verboseLogging) Debug.Log("[Live2DModelController] PlayMotion(null) — 忽略（沒指定 clip）");
                return;
            }

            // v1.2+：優先用 CubismMotionController（.fade 跟 .anim 都能播、Cubism 官方路徑）
            // 之前 commit 1c7d8a6 把這拿掉是錯的、只是避開「無 motion controller」warning
            // 正確解法是 CubismMotionController 沒時才掉 Unity Animation
#if SIRO_HAS_CUBISM
            if (_motionController != null)
            {
                try
                {
                    _motionController.PlayAnimation(
                        clip,
                        layerIndex: 0,
                        priority: priority,
                        isLoop: isLoop,
                        speed: 1.0f
                    );
                    if (verboseLogging) Debug.Log(
                        $"[Live2DModelController] PlayMotion: {clip.name} (Cubism, loop={isLoop})"
                    );
                    return;
                }
                catch (Exception e)
                {
                    Debug.LogError($"[Live2DModelController] Cubism PlayMotion 失敗: {e.Message}");
                }
            }
#endif

            // 路徑 2: Unity Animation component（沒 CubismMotionController 時 fallback）
            // 只支援 Legacy .anim（Generic 會有 warning、但還是能播）
            if (_unityAnimation == null)
            {
                _unityAnimation = GetComponent<Animation>();
            }
            if (_unityAnimation == null)
            {
                _unityAnimation = gameObject.AddComponent<Animation>();
                if (verboseLogging) Debug.Log(
                    "[Live2DModelController] 自動加 Animation component（Mao 缺、補上）"
                );
            }

            if (_unityAnimation.GetClip(clip.name) == null)
            {
                _unityAnimation.AddClip(clip, clip.name);
            }
            _unityAnimation.clip = clip;
            _unityAnimation.wrapMode = isLoop ? WrapMode.Loop : WrapMode.Once;
            _unityAnimation.Play();
            if (verboseLogging) Debug.Log(
                $"[Live2DModelController] PlayMotion: {clip.name} (Unity Animation fallback, loop={isLoop})"
            );
        }

        /// <summary>
        /// 停止目前播放的 motion
        /// </summary>
        public void StopMotion(float fadeOutSeconds = 1.0f)
        {
            if (_unityAnimation != null && _unityAnimation.isPlaying)
            {
                _unityAnimation.Stop();
            }
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

        // ==================== v1.2+ 自然行為：眨眼 + 呼吸 ====================

        /// <summary>
        /// 自然隨機眨眼迴圈 — 每 3-7s 一次、短暫關眼 0.12s
        /// 30% 機率雙眨眼（自然、人類也會不慎連眨）
        /// 注意：眨眼時 _currentExpressionId 必須不是 hide_eye_on 的表情
        ///       否則 SetEyeRenderersVisible 已經 false、我們再 false 沒差
        /// </summary>
        private System.Collections.IEnumerator BlinkRoutine()
        {
            // 等一下讓 Mao 先出現（避免一啟動就閉眼怪怪的）
            yield return new WaitForSeconds(1.5f);

            while (true)
            {
                float wait = UnityEngine.Random.Range(blinkMinInterval, blinkMaxInterval);
                yield return new WaitForSeconds(wait);

                if (_hasCubismBlinkParam)
                {
                    // 真眨眼：Cubism 參數 snap 0 + 順便藏瞳孔
                    // 不 lerp（慢動作會很奇怪）、用 snap 直接 1.0 → 0.0
                    SetCubismEyeParam(_eyeLOpenParam, 0f);
                    SetCubismEyeParam(_eyeROpenParam, 0f);
                    SetCubismEyeParam(_eyeLCloseParam, 1f);
                    SetCubismEyeParam(_eyeRCloseParam, 1f);
                    SetEyeRenderersVisible(false);  // 雙保險：瞳孔也藏
                    yield return new WaitForSeconds(blinkDuration * 0.4f);  // hold closed (短)

                    // 開眼：snap 回 1.0
                    SetCubismEyeParam(_eyeLOpenParam, 1f);
                    SetCubismEyeParam(_eyeROpenParam, 1f);
                    SetCubismEyeParam(_eyeLCloseParam, 0f);
                    SetCubismEyeParam(_eyeRCloseParam, 0f);
                    SetEyeRenderersVisible(true);
                    yield return new WaitForSeconds(blinkDuration * 0.6f);  // open 期間
                }
                else
                {
                    // fallback：藏瞳孔
                    SetEyeRenderersVisible(false);
                    yield return new WaitForSeconds(blinkDuration);
                    SetEyeRenderersVisible(true);
                }

                // 30% 機率雙眨眼
                if (UnityEngine.Random.value < 0.3f)
                {
                    yield return new WaitForSeconds(0.08f);
                    if (_hasCubismBlinkParam)
                    {
                        SetCubismEyeParam(_eyeLOpenParam, 0f);
                        SetCubismEyeParam(_eyeROpenParam, 0f);
                        SetCubismEyeParam(_eyeLCloseParam, 1f);
                        SetCubismEyeParam(_eyeRCloseParam, 1f);
                        SetEyeRenderersVisible(false);
                        yield return new WaitForSeconds(blinkDuration * 0.4f);
                        SetCubismEyeParam(_eyeLOpenParam, 1f);
                        SetCubismEyeParam(_eyeROpenParam, 1f);
                        SetCubismEyeParam(_eyeLCloseParam, 0f);
                        SetCubismEyeParam(_eyeRCloseParam, 0f);
                        SetEyeRenderersVisible(true);
                    }
                    else
                    {
                        SetEyeRenderersVisible(false);
                        yield return new WaitForSeconds(blinkDuration);
                        SetEyeRenderersVisible(true);
                    }
                }
            }
        }

        /// <summary>
        /// 找 Cubism eye-blink 參數（用 reflection、不需要 SIRO_HAS_CUBISM）
        /// 找四個：ParamEyeLOpen / ParamEyeROpen / ParamEyeLClose / ParamEyeRClose
        /// 有的 model 兩組都有（Open + Close）、動畫要同步
        /// 設 _hasCubismBlinkParam flag 給 BlinkRoutine 用（有任一組就 true）
        ///
        /// SDK 5-r.5 的 CubismParameter[] 沒有 FindById method — 改用 IEnumerable
        /// 逐個比對 .Id 屬性、找到就拿
        /// </summary>
        private void TryFindCubismEyeBlinkParams()
        {
            try
            {
                // _model 是 CubismModel、透過 reflection 拿 .Parameters
                var modelType = _model.GetType();
                var parametersProp = modelType.GetProperty("Parameters");
                if (parametersProp == null) return;
                var parametersObj = parametersProp.GetValue(_model);
                if (parametersObj == null) return;

                // 把 parameters 當 IEnumerable 處理
                // SDK 5-r.5：CubismParameterStore 實作 IEnumerable<CubismParameter>
                var enumerable = parametersObj as System.Collections.IEnumerable;
                if (enumerable == null)
                {
                    // 也許是 array 本身、直接 cast
                    enumerable = parametersObj as System.Collections.IEnumerable;
                    if (enumerable == null)
                    {
                        if (verboseLogging) Debug.LogWarning(
                            "[Live2DModelController] parameters 不是 IEnumerable、無法列舉"
                        );
                        return;
                    }
                }

                // 列出所有參數、log 給 debug（順便找 blink 參數）
                var availableIds = new System.Collections.Generic.List<string>();
                foreach (var p in enumerable)
                {
                    if (p == null) continue;
                    var pType = p.GetType();
                    var idProp = pType.GetProperty("Id");
                    var nameProp = pType.GetProperty("Name");
                    string id = idProp?.GetValue(p) as string;
                    string name = nameProp?.GetValue(p) as string;
                    if (!string.IsNullOrEmpty(id)) availableIds.Add(id);
                    // 找目標參數（比對 Id 或 Name）
                    if (id == "ParamEyeLOpen" || name == "ParamEyeLOpen")
                        _eyeLOpenParam = p as UnityEngine.Object;
                    else if (id == "ParamEyeROpen" || name == "ParamEyeROpen")
                        _eyeROpenParam = p as UnityEngine.Object;
                    else if (id == "ParamEyeLClose" || name == "ParamEyeLClose")
                        _eyeLCloseParam = p as UnityEngine.Object;
                    else if (id == "ParamEyeRClose" || name == "ParamEyeRClose")
                        _eyeRCloseParam = p as UnityEngine.Object;
                }

                bool hasOpen = (_eyeLOpenParam != null && _eyeROpenParam != null);
                bool hasClose = (_eyeLCloseParam != null && _eyeRCloseParam != null);
                _hasCubismBlinkParam = (hasOpen || hasClose);

                if (verboseLogging)
                {
                    // 印所有找到的參數（給 debug 用）
                    string allIds = string.Join(", ", availableIds);
                    Debug.Log(
                        $"[Live2DModelController] model 有 {availableIds.Count} 個 Cubism 參數：" +
                        $"{allIds}"
                    );
                    if (_hasCubismBlinkParam)
                    {
                        Debug.Log(
                            $"[Live2DModelController] 找到 eye-blink 參數、Open={hasOpen}, Close={hasClose}"
                        );
                    }
                    else
                    {
                        Debug.LogWarning(
                            "[Live2DModelController] 找不到 ParamEyeLOpen/ROpen/LClose/RClose、" +
                            "掉 hide-pupils fallback"
                        );
                    }
                }
            }
            catch (Exception e)
            {
                if (verboseLogging) Debug.LogWarning(
                    $"[Live2DModelController] 找 Cubism 參數失敗（可能沒裝 SDK）: {e.Message}"
                );
                _hasCubismBlinkParam = false;
            }
        }

        /// <summary>
        /// 透過 reflection 設 Cubism eye-open 參數（不需要 SIRO_HAS_CUBISM）
        /// 同時試 property (.Value) 跟 field (.Value)、SDK 版本不同可能用不同方式
        /// 第一次 call 印 log 確認 reflection 成功
        /// </summary>
        private bool _eyeParamSetterLogged = false;
        private void SetCubismEyeParam(UnityEngine.Object param, float value)
        {
            if (param == null) return;
            var paramType = param.GetType();

            // 1. 試 property
            var prop = paramType.GetProperty("Value");
            if (prop != null && prop.CanWrite)
            {
                prop.SetValue(param, value);
                if (!_eyeParamSetterLogged && verboseLogging)
                {
                    Debug.Log(
                        $"[Live2DModelController] eye 參數 setter 成功（property reflection）、" +
                        $"設 {paramType.Name} = {value}"
                    );
                    _eyeParamSetterLogged = true;
                }
                return;
            }

            // 2. 試 field（SDK 某些版本用 public field 不是 property）
            var field = paramType.GetField("Value",
                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
            if (field != null)
            {
                field.SetValue(param, value);
                if (!_eyeParamSetterLogged && verboseLogging)
                {
                    Debug.Log(
                        $"[Live2DModelController] eye 參數 setter 成功（field reflection）、" +
                        $"設 {paramType.Name} = {value}"
                    );
                    _eyeParamSetterLogged = true;
                }
                return;
            }

            // 3. 都失敗 → log 印所有可寫的 property 跟 field（debug）
            if (!_eyeParamSetterLogged && verboseLogging)
            {
                var props = paramType.GetProperties();
                var propsStr = string.Join(", ",
                    System.Array.ConvertAll(props, p => $"{p.Name}({(p.CanWrite ? "rw" : "r")})"));
                var fields = paramType.GetFields(
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                var fieldsStr = string.Join(", ",
                    System.Array.ConvertAll(fields, f => $"{f.Name}"));
                Debug.LogWarning(
                    $"[Live2DModelController] eye 參數 setter 失敗 — 找不到 Value 屬性或欄位。" +
                    $"\n  找到的 properties: [{propsStr}]" +
                    $"\n  找到的 fields: [{fieldsStr}]"
                );
                _eyeParamSetterLogged = true;
            }
        }

        // v1.2+ AnimateEyeParam 已經改成 snap 模式、不需要 lerp 版本
        // BlinkRoutine 直接呼叫 SetCubismEyeParam 設 snap 0/1
        // 留這段註解避免下次又撿回來用

        /// <summary>
        /// scale-based 呼吸 fallback — 沒 mtn_01.anim 時的 backup
        /// 緩慢振盪 transform.localScale.y、模擬呼吸節奏
        /// 有 mtn_01.anim 時這個 coroutine 不啟動（避免雙重呼吸）
        /// </summary>
        private System.Collections.IEnumerator BreathingRoutine()
        {
            // 等 idle setup 結束
            yield return new WaitForSeconds(0.5f);

            Vector3 baseScale = transform.localScale;
            float cycleStart = Time.time;

            // 每個週期隨機微擾動（避免完美週期、像機器）
            float cycleJitter = 0f;
            float nextJitterChange = 0f;

            while (true)
            {
                float elapsed = Time.time - cycleStart;
                // 週期性 ±5% 隨機擾動（每 3-5 週期換一次、避免太頻繁）
                if (elapsed > nextJitterChange)
                {
                    cycleJitter = UnityEngine.Random.Range(-0.05f, 0.05f) * breathingPeriod;
                    nextJitterChange = elapsed + breathingPeriod * UnityEngine.Random.Range(3f, 5f);
                }
                float effectivePeriod = breathingPeriod + (breathingAddJitter ? cycleJitter : 0f);
                float t = (elapsed % effectivePeriod) / effectivePeriod;  // [0, 1]

                // 真實呼吸曲線（piecewise、不是對稱 sin）：
                // 0.00 - 0.40: 吸氣（線性上升到 1.0+amp）
                // 0.40 - 0.50: hold 滿
                // 0.50 - 0.90: 吐氣（線性下降到 1.0-amp）
                // 0.90 - 1.00: hold 底
                // 吸氣快、吐氣慢（自然）
                float breathValue;
                if (t < 0.40f)
                {
                    // 吸氣：t=0 → 0、t=0.4 → 1
                    float phase = t / 0.40f;
                    breathValue = phase;  // 線性（也可以用 sqrt 加速）
                }
                else if (t < 0.50f)
                {
                    breathValue = 1f;  // hold 滿
                }
                else if (t < 0.90f)
                {
                    // 吐氣：t=0.5 → 1、t=0.9 → 0（比吸氣慢 2 倍）
                    float phase = (t - 0.50f) / 0.40f;
                    breathValue = 1f - phase;
                }
                else
                {
                    breathValue = 0f;  // hold 底
                }

                // 從 [0, 1] 映射到 [1-amp, 1+amp]、加 jitter 到週期長度（已加過）
                float scaleMultiplier = 1.0f + (breathValue * 2f - 1f) * breathingAmplitude;
                transform.localScale = baseScale * scaleMultiplier;
                yield return null;  // 每 frame 更新
            }
        }

        /// <summary>
        /// 頭部微妙晃動 — 每 4-8s 隨機一個 Y 軸小角度、平滑 lerp 過去、停一下、再回 0
        /// 給 Mao 活的感覺（不是塑膠模型）
        /// 注意：rotation Y 是 3D 軸、對 Live2D 是「歪頭」效果（左/右）
        /// </summary>
        private System.Collections.IEnumerator HeadSwayRoutine()
        {
            // 等 Mao 出現
            yield return new WaitForSeconds(1.0f);
            float originalY = transform.eulerAngles.y;

            while (true)
            {
                float wait = UnityEngine.Random.Range(headSwayMinInterval, headSwayMaxInterval);
                yield return new WaitForSeconds(wait);

                // 隨機目標角度（±headSwayAngle 度）
                float targetAngle = UnityEngine.Random.Range(-headSwayAngle, headSwayAngle);
                float duration = 0.6f;  // 0.6s 平滑搖過去
                float elapsed = 0f;
                float startAngle = transform.eulerAngles.y;
                if (startAngle > 180f) startAngle -= 360f;  // 規範到 [-180, 180]

                // lerp 過去
                while (elapsed < duration)
                {
                    elapsed += Time.deltaTime;
                    float t = Mathf.Clamp01(elapsed / duration);
                    // smoothstep 平滑
                    float smoothT = t * t * (3f - 2f * t);
                    float currentAngle = Mathf.Lerp(startAngle, targetAngle, smoothT);
                    Vector3 euler = transform.eulerAngles;
                    euler.y = currentAngle;
                    transform.eulerAngles = euler;
                    yield return null;
                }

                // 停留 0.5-1.5s
                float hold = UnityEngine.Random.Range(0.5f, 1.5f);
                yield return new WaitForSeconds(hold);

                // lerp 回 0
                elapsed = 0f;
                while (elapsed < duration)
                {
                    elapsed += Time.deltaTime;
                    float t = Mathf.Clamp01(elapsed / duration);
                    float smoothT = t * t * (3f - 2f * t);
                    float currentAngle = Mathf.Lerp(targetAngle, originalY, smoothT);
                    Vector3 euler = transform.eulerAngles;
                    euler.y = currentAngle;
                    transform.eulerAngles = euler;
                    yield return null;
                }
            }
        }

        private void OnDisable()
        {
            // 停止 coroutine、避免 OnDisable 後還在跑
            if (_blinkCoroutine != null) { StopCoroutine(_blinkCoroutine); _blinkCoroutine = null; }
            if (_breathingCoroutine != null) { StopCoroutine(_breathingCoroutine); _breathingCoroutine = null; }
            if (_headSwayCoroutine != null) { StopCoroutine(_headSwayCoroutine); _headSwayCoroutine = null; }
        }
    }
}
