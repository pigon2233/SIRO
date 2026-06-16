// unity/Assets/Scripts/K5ExpressionLatencyProbe.cs
//
// K5 KPI 量測工具：表情切換延遲 < 200ms
// 規格：量測 SetExpression 到 Cubism render 完成
//
// 用法：
//   1. 掛在 Mao GameObject 上（同 Live2DModelController）
//   2. Inspector 設定 testExpressions（persona 實際有的 expression ID）
//   3. 進 Play mode
//   4. 自動跑完 N 次切換、log 結果
//   5. 看到 "K5 Probe === Result === avg=Xms PASS/FAIL" 就完成
//   6. 把 component 移除
//
// 量測邏輯：
//   t0 = 呼叫 SetExpression 前
//   yield return new WaitForEndOfFrame() — 等到 frame 結束、render 完成
//   t1 = render 完成後
//   latency = t1 - t0
//
// 包含：
//   - SetExpression 的 SDK 內部處理時間
//   - Cubism blend 計算
//   - LateUpdate 套用到 mesh
//   - 該 frame 渲染到 GPU
//
// 不包含：frame 之間的等待（下一個 frame 才 render）

using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Siro
{
    public class K5ExpressionLatencyProbe : MonoBehaviour
    {
        [Header("Target")]
        [Tooltip("要量測的 controller — 留空自動 GetComponent")]
        public Live2DModelController controller;

        [Header("Test Config")]
        [Tooltip("要循環切換的 expression ID 清單（persona 實際有的）\n" +
                 "Mao 預設 exp_01~exp_06（對應 happy/sad/angry/surprised/neutral/relaxed）")]
        public string[] testExpressions = new[] { "exp_01", "exp_02", "exp_03", "exp_04", "exp_05", "exp_06" };

        [Tooltip("每個 expression 之間的等待時間（秒、給 Cubism 套用）\n" +
                 "預設 0.5s = Cubism 預設 blendLockDuration、避免量到 blend 中間狀態")]
        public float intervalSec = 0.5f;

        [Tooltip("總共量測幾輪（每輪跑完所有 testExpressions）")]
        public int totalIterations = 10;

        [Header("KPI Target")]
        [Tooltip("K5 目標：表情切換延遲 < 200ms（average）")]
        public float targetLatencyMs = 200f;

        [Header("Debug")]
        public bool verboseLogging = true;
        public bool stopOnFirstFrame = true;  // 預設備好就停、避免干擾其他測試

        private readonly List<float> _latencies = new List<float>();
        // 測試結束旗標,給外部 stopOnFirstFrame 邏輯用(目前只在 OnDestroy 後讀)
        // 還沒被其他 component 查詢、暫時 suppress warning
#pragma warning disable CS0414  // 預留給 stopOnFirstFrame / OnDestroy 整合
        private bool _done = false;
#pragma warning restore CS0414

        private void Start()
        {
            if (controller == null)
            {
                controller = GetComponent<Live2DModelController>();
            }
            if (controller == null)
            {
                Debug.LogError("[K5 Probe] ❌ 找不到 Live2DModelController");
                enabled = false;
                return;
            }
            if (testExpressions == null || testExpressions.Length < 2)
            {
                Debug.LogError("[K5 Probe] ❌ testExpressions 至少要 2 個（同 expression 不觸發）");
                enabled = false;
                return;
            }
            StartCoroutine(RunProbe());
        }

        private IEnumerator RunProbe()
        {
            // 等 Mao 初始化 + 第一個 expression 套用
            yield return new WaitForSeconds(1.0f);

            if (verboseLogging)
            {
                Debug.Log($"[K5 Probe] 開始量測 — {testExpressions.Length} 個 expression × {totalIterations} 輪 = {testExpressions.Length * totalIterations} 次切換");
                Debug.Log($"[K5 Probe] K5 target = < {targetLatencyMs}ms（average）");
            }

            int totalSamples = 0;
            for (int iter = 0; iter < totalIterations; iter++)
            {
                for (int exprIdx = 0; exprIdx < testExpressions.Length; exprIdx++)
                {
                    string expr = testExpressions[exprIdx];
                    // 跳過同 expression（SetExpression 會 early return）
                    // 確保每次量測都是真的切換
                    if (expr == controller.GetCurrentExpressionId()) continue;

                    // t0 = 切換前
                    float t0 = Time.realtimeSinceStartup * 1000f;

                    // blendDuration = 0 = 立即切換（不鎖、debug 用、量測真實延遲）
                    controller.SetExpression(expr, 0.0f);

                    // 等到 frame 結束（render 完成）
                    yield return new WaitForEndOfFrame();

                    // t1 = render 完成後
                    float t1 = Time.realtimeSinceStartup * 1000f;

                    float latencyMs = t1 - t0;
                    _latencies.Add(latencyMs);
                    totalSamples++;

                    if (verboseLogging)
                    {
                        Debug.Log($"[K5 Probe] iter {iter + 1}/{totalIterations} expr={expr} latency={latencyMs:F2}ms");
                    }

                    // 給 Cubism blend 一點時間再切下一個
                    yield return new WaitForSeconds(intervalSec);
                }
            }

            // 統計
            if (_latencies.Count > 0)
            {
                float avg = _latencies.Average();
                float max = _latencies.Max();
                float min = _latencies.Min();
                float p50 = Percentile(_latencies, 0.50f);
                float p95 = Percentile(_latencies, 0.95f);
                bool pass = avg < targetLatencyMs;

                Debug.Log("=== K5 Probe Result ===");
                Debug.Log($"  Samples:  {_latencies.Count} 次切換");
                Debug.Log($"  Min:      {min:F2}ms");
                Debug.Log($"  P50:      {p50:F2}ms");
                Debug.Log($"  P95:      {p95:F2}ms");
                Debug.Log($"  Max:      {max:F2}ms");
                Debug.Log($"  Average:  {avg:F2}ms");
                Debug.Log($"  K5 target: < {targetLatencyMs}ms");
                Debug.Log($"  Result:   {(pass ? "✓ PASS" : "✗ FAIL")}");
            }
            else
            {
                Debug.LogWarning("[K5 Probe] 沒量到任何 latency（可能 controller 拒絕切換？）");
            }

            _done = true;
            if (stopOnFirstFrame && verboseLogging)
            {
                Debug.Log("[K5 Probe] 量測結束、請移除此 component");
            }
        }

        private static float Percentile(List<float> sorted, float p)
        {
            if (sorted == null || sorted.Count == 0) return 0f;
            var arr = sorted.OrderBy(x => x).ToArray();
            int idx = Mathf.Clamp(Mathf.RoundToInt(p * (arr.Length - 1)), 0, arr.Length - 1);
            return arr[idx];
        }
    }
}
