// unity/Assets/Scripts/PersonaClickHandler.cs
//
// v1.2 SendTask OnClick handler — 橋接 Live2DModelController.OnMaoClicked + persona YAML
// 的 clickable_areas + HermesBridgeClient.SendTaskAsync。
//
// 流程：
//   1. Start 找 Live2DModelController + HermesBridgeClient
//   2. 訂閱 OnMaoClicked(hitArea) event
//   3. 從 persona YAML 讀 clickable_areas（透過 PersonaConfig + PersonaApiClient）
//   4. 點 Mao → 查 persona 的 clickable_areas[hitArea] → 拿 {task, args}
//   5. 叫 SendTaskAsync(task, args) → 結果從 OnTaskResult / OnTaskFailed event 收
//
// v1.2 MVP：persona YAML 的 clickable_areas 是手寫靜態（PersonaConfig 暴露
// 到 inspector）。v1.5+ 可改成 runtime 從 PersonaApiClient 拉最新 persona。
//
// 使用：
//   - 掛在一個空 GameObject 上（跟 Live2DModelController + HermesBridgeClient 同層）
//   - Inspector 設 live2DController、bridge、personaConfig references
//

using System;
using System.Collections.Generic;
using UnityEngine;
using Newtonsoft.Json.Linq;

namespace Siro
{
    /// <summary>
    /// persona 的一筆 clickable area 設定
    /// inspector 設的（v1.2 MVP）、之後 v1.5+ 改 runtime 從 PersonaApiClient 拿
    ///
    /// v1.2 簡化版 args：每行一個 "key: value" 字串、自動推斷型別
    ///   emotion: happy             → JValue "happy" (string)
    ///   intensity: 0.8              → JValue 0.8 (double)
    ///   motion_index: 0             → JValue 0 (int)
    ///   is_loop: true               → JValue true (bool)
    /// 比之前 key + 4 種 type + 對應 value 欄位簡單太多
    /// </summary>
    [Serializable]
    public class ClickableArea
    {
        [Tooltip("Hit area name — 對應 Live2DModelController.OnMaoClicked 傳入的字串")]
        public string area;

        [Tooltip(@"要觸發的 task name（mood.set / motion.play / chat.say 等）")]
        public string task;

        [Tooltip(@"args 一行一個 key: value、自動推斷型別。範例：
  emotion: happy
  intensity: 0.8
  motion_index: 0
  is_loop: true
支援 string / int / float / bool、推斷規則：true/false → bool、能 int 解析 → int、能 float 解析 → float、其餘 → string")]
        public List<string> args = new List<string>();

        /// <summary>
        /// 從 args 字串 list 解析成 JObject
        /// 推斷規則：true/false → bool、整數 → int、浮點 → float、其餘 → string
        /// 壞行 log warning 跳過（不 crash、單筆壞不影響其他）
        /// </summary>
        public JObject ToArgs()
        {
            var obj = new JObject();
            if (args == null) return obj;
            foreach (var raw in args)
            {
                if (string.IsNullOrWhiteSpace(raw)) continue;
                var line = raw.Trim();
                // 支援 "key: value" 跟 "key=value" 兩種寫法
                int sep = line.IndexOfAny(new[] { ':', '=' });
                if (sep < 0)
                {
                    Debug.LogWarning(
                        $"[ClickableArea] 跳過格式錯誤的 arg {line!r}（要 'key: value' 或 'key=value'）"
                    );
                    continue;
                }
                var key = line.Substring(0, sep).Trim();
                var value = line.Substring(sep + 1).Trim();
                if (string.IsNullOrEmpty(key))
                {
                    Debug.LogWarning($"[ClickableArea] 跳過空 key 的 arg: {line}");
                    continue;
                }
                obj[key] = ParseValue(value);
            }
            return obj;
        }

        private static JToken ParseValue(string raw)
        {
            // bool
            if (raw.Equals("true", StringComparison.OrdinalIgnoreCase)) return true;
            if (raw.Equals("false", StringComparison.OrdinalIgnoreCase)) return false;
            // int
            if (int.TryParse(raw, System.Globalization.NumberStyles.Integer,
                             System.Globalization.CultureInfo.InvariantCulture, out int i))
            {
                return i;
            }
            // float
            if (float.TryParse(raw, System.Globalization.NumberStyles.Float,
                               System.Globalization.CultureInfo.InvariantCulture, out float f))
            {
                return f;
            }
            // string fallback
            return raw;
        }
    }

    public class PersonaClickHandler : MonoBehaviour
    {
        [Header("References")]
        [Tooltip("點擊偵測來源（同一個 Mao GameObject）")]
        public Live2DModelController live2DController;

        [Tooltip("WS 連線 — 拿來呼叫 SendTaskAsync")]
        public HermesBridgeClient bridge;

        [Header("v1.2 MVP: persona clickable_areas（手填）")]
        [Tooltip("persona 定義的 clickable_areas — v1.5+ 改 runtime 從 PersonaApiClient 拉")]
        public List<ClickableArea> clickableAreas = new List<ClickableArea>();

        [Header("Debug")]
        public bool verboseLogging = true;

        [Header("v1.2 MVP: SendTask timeout")]
        [Tooltip("每個 click task 等回應多久（秒）")]
        public float taskTimeoutSec = 3.0f;

        private void Start()
        {
            // 自動找 references（同 GameObject / 同 parent / 全場景）
            if (live2DController == null)
            {
                live2DController = GetComponent<Live2DModelController>()
                    ?? GetComponentInParent<Live2DModelController>()
                    ?? FindFirstObjectByType<Live2DModelController>();
            }
            if (bridge == null)
            {
                bridge = GetComponent<HermesBridgeClient>()
                    ?? GetComponentInParent<HermesBridgeClient>()
                    ?? FindFirstObjectByType<HermesBridgeClient>();
            }

            if (live2DController == null)
            {
                Debug.LogError("[PersonaClickHandler] 找不到 Live2DModelController");
                return;
            }
            if (bridge == null)
            {
                Debug.LogError("[PersonaClickHandler] 找不到 HermesBridgeClient");
                return;
            }

            // 訂閱點擊事件
            live2DController.OnMaoClicked += HandleMaoClicked;
            if (verboseLogging) Debug.Log("[PersonaClickHandler] 已訂閱 OnMaoClicked");
        }

        private void OnDestroy()
        {
            if (live2DController != null)
            {
                live2DController.OnMaoClicked -= HandleMaoClicked;
            }
        }

        /// <summary>
        /// Mao 點擊事件 → 查 clickableAreas → SendTaskAsync
        /// </summary>
        private async void HandleMaoClicked(string hitArea)
        {
            if (verboseLogging) Debug.Log($"[PersonaClickHandler] 收到 OnMaoClicked: hitArea={hitArea}");

            // 找對應的 clickable_areas entry
            var entry = clickableAreas.Find(c => c.area == hitArea);
            if (entry == null)
            {
                if (verboseLogging) Debug.Log(
                    $"[PersonaClickHandler] hitArea={hitArea!} 沒對應 clickable_areas entry（忽略）"
                );
                return;
            }
            if (string.IsNullOrEmpty(entry.task))
            {
                Debug.LogWarning($"[PersonaClickHandler] hitArea={hitArea!} 沒設 task（忽略）");
                return;
            }

            // 叫 SendTaskAsync — fire-and-await
            // 注意：async void 只用在 event handler（這裡就是）
            try
            {
                var args = entry.ToArgs();
                if (verboseLogging) Debug.Log(
                    $"[PersonaClickHandler] SendTask: {entry.task} args={args}"
                );
                var result = await bridge.SendTaskAsync(entry.task, args, taskTimeoutSec);
                if (verboseLogging) Debug.Log(
                    $"[PersonaClickHandler] SendTask 完成: {result}"
                );
            }
            catch (TimeoutException)
            {
                Debug.LogWarning(
                    $"[PersonaClickHandler] SendTask {entry.task!} 超過 {taskTimeoutSec}s 沒回"
                );
            }
            catch (SendTaskException ex)
            {
                Debug.LogWarning(
                    $"[PersonaClickHandler] SendTask {entry.task!} 失敗: {ex.Message}"
                );
            }
            catch (OperationCanceledException)
            {
                // 連線中斷、不算 error（已是 reconnect 中）
                if (verboseLogging) Debug.Log(
                    $"[PersonaClickHandler] SendTask {entry.task!} 因連線中斷取消"
                );
            }
            catch (Exception e)
            {
                Debug.LogError($"[PersonaClickHandler] 未知錯誤: {e}");
            }
        }
    }
}
