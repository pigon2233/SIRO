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
// v1.2+ 點擊限流：debounce (minClickIntervalSec) + in-flight 上限 (maxInFlightTasks)
//   防止狂點讓後端 TaskQueue 堆積。queue 是 FIFO + 單 worker（bridge/agent_os.py），
//   chat 慢的時候 click 會跟著等、響應會被拖到 100s+。
//
// 使用：
//   - 掛在一個空 GameObject 上（跟 Live2DModelController + HermesBridgeClient 同層）
//   - Inspector 設 live2DController、bridge、personaConfig references
//
// ==== TODO(v1.5+): 後端 TaskQueue 重構 ====
//   目前後端 asyncio.Queue 是 FIFO + 單 worker，導致：
//   1. chat 慢的時候 click 也跟著等
//   2. 狂點會把 queue 灌爆（log 看到 task_in_queue=100s+）
//   改法（見 bridge/agent_os.py）：
//   A) 多 worker（asyncio.gather 平行處理）
//   B) 任務分類：llm_reply vs motion/mood 即時任務走不同 queue
//   C) 優先級：click/motion 高優先、chat 低優先
//   D) Drop policy：queue 滿了丟舊的（保留最新意圖）
//   Unity 端這層 (debounce + maxInFlight) 只是 client-side 治標、真正治本在後端。
// =========================================
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

        [Tooltip(@"v1.2+ per-area timeout（秒）—
預設 5s 配 HermesBridgeClient.SendTaskAsync 預設值。
會觸發 LLM 的 task（chat.say、persona.switch、mood.set 帶情緒分析等）建議調 15-30s。
即時任務（motion.play、expression.set）3-5s 夠。
注意：timeout 太短會在 chat 響應期間誤判失敗（後端排隊中）；
太長會卡 UI、debug 時等更久。")]
        public float taskTimeoutSec = 5.0f;

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
                        $"[ClickableArea] 跳過格式錯誤的 arg {line!}（要 'key: value' 或 'key=value'）"
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

        [Header("v1.2 MVP: SendTask timeout（fallback）")]
        [Tooltip("每個 click task 預設等回應多久（秒）— " +
                 "v1.2+ 改成 per-area 設定（看 ClickableArea.taskTimeoutSec），" +
                 "這欄是 ClickableArea 沒設或 < 0 時的 fallback。\n" +
                 "5s 配 HermesBridgeClient.SendTaskAsync 預設值、" +
                 "即時任務（motion.play）夠用。\n" +
                 "會等 LLM 的 task 建議在 ClickableArea 設 15-30s、避免 chat 響應期間被誤判 timeout。")]
        public float defaultTaskTimeoutSec = 5.0f;

        [Header("v1.2+ 點擊限流（防 queue 爆炸）")]
        [Tooltip("同一 area 兩次點擊最小間隔（秒）— 防狂點同一個部位。\n" +
                 "0.5s = 連點最多每秒 2 次、夠防呆不影響正常互動。\n" +
                 "設 0 = 不限制。\n" +
                 "⚠️ 後端 TaskQueue 是 FIFO + 單 worker（bridge/agent_os.py），" +
                 "狂點會讓 chat 也跟著等、響應會被拖到 100s+。")]
        public float minClickIntervalSec = 0.5f;
        [Tooltip("最多同時 in-flight 的 task 數 — 超過直接丟棄新點擊、避免後端 queue 堆積。\n" +
                 "預設 3 = chat 在跑時還能 2 個 click 並行。\n" +
                 "⚠️ 不要調太高、queue 是 single-worker 順序處理。")]
        public int maxInFlightTasks = 3;

        // 點擊限流 state（runtime only）
        private readonly System.Collections.Generic.Dictionary<string, float> _lastClickTimeByArea
            = new System.Collections.Generic.Dictionary<string, float>();
        private int _inFlightTaskCount = 0;
        private readonly object _clickLock = new object();

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
        /// v1.2+ 加 debounce + in-flight 限流（防後端 TaskQueue 堆積炸掉）
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

            // v1.2+ 點擊限流檢查（在 SendTask 之前、避免無效進 queue）
            // 1) in-flight 上限檢查
            // 2) per-area debounce（防狂點同一個部位）
            lock (_clickLock)
            {
                if (_inFlightTaskCount >= maxInFlightTasks)
                {
                    Debug.LogWarning(
                        $"[PersonaClickHandler] in-flight 已滿 ({_inFlightTaskCount}/{maxInFlightTasks})、" +
                        $"忽略點擊 {entry.task!}（防 queue 堆積）"
                    );
                    return;
                }

                if (minClickIntervalSec > 0f
                    && _lastClickTimeByArea.TryGetValue(hitArea, out float lastClickTime))
                {
                    float elapsed = Time.unscaledTime - lastClickTime;
                    if (elapsed < minClickIntervalSec)
                    {
                        // 不 log warning、正常防呆、狂點會被吞掉（verbose log 也只 warn 一次）
                        if (verboseLogging) Debug.Log(
                            $"[PersonaClickHandler] debounce {hitArea!}: {elapsed*1000:.0f}ms < {minClickIntervalSec*1000:.0f}ms、忽略"
                        );
                        return;
                    }
                }

                // 通過檢查 → 記錄
                _lastClickTimeByArea[hitArea] = Time.unscaledTime;
                _inFlightTaskCount++;
            }

            // 叫 SendTaskAsync — fire-and-await
            // 注意：async void 只用在 event handler（這裡就是）
            try
            {
                var args = entry.ToArgs();
                // v1.2+ per-area timeout：ClickableArea.taskTimeoutSec 沒設或 < 0 才掉 defaultTaskTimeoutSec
                float timeout = entry.taskTimeoutSec > 0f ? entry.taskTimeoutSec : defaultTaskTimeoutSec;
                if (verboseLogging) Debug.Log(
                    $"[PersonaClickHandler] SendTask: {entry.task} args={args} (timeout={timeout}s, in-flight={_inFlightTaskCount})"
                );
                var result = await bridge.SendTaskAsync(entry.task, args, timeout);
                if (verboseLogging) Debug.Log(
                    $"[PersonaClickHandler] SendTask 完成: {result}"
                );
            }
            catch (TimeoutException)
            {
                float usedTimeout = entry.taskTimeoutSec > 0f ? entry.taskTimeoutSec : defaultTaskTimeoutSec;
                Debug.LogWarning(
                    $"[PersonaClickHandler] SendTask {entry.task!} 超過 {usedTimeout}s 沒回"
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
            finally
            {
                // 不論成功失敗、release in-flight slot
                lock (_clickLock)
                {
                    _inFlightTaskCount--;
                    if (_inFlightTaskCount < 0) _inFlightTaskCount = 0;  // 安全網
                }
            }
        }
    }
}
