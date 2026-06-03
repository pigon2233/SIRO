// SiroUnity/Assets/Editor/ExpressionViewer.cs
//
// SIRO Expression Viewer — 校準 Mao（或其他 Cubism 模型）表情用的小工具
//
// 動機：emotion_mapping.json 與 EmotionDisplay 把 exp_01-exp_08 對應到情緒名
// （happy = exp_02 等），但這些對應是「猜測」。本工具讓你一個一個按按鈕，
// 直接看每個 exp_XX 在 Mao 上長什麼樣，然後把結果記回 mapping。
//
// 使用：
//   1. 場景裡要有 Mao（或任何掛了 CubismExpressionController 的物件）
//   2. 進 Play 模式（Cubism expression blending 在 LateUpdate 才生效，Edit 模式靜止）
//   3. 選單 → Tools → SIRO → Expression Viewer
//   4. 按右側「Refresh Expressions」掃一次
//   5. 點 [Try exp_01] 看 Mao 表情，在底下文字框記下你看到什麼
//   6. 全部試完，把對應抄回 bridge/emotion_mapping.json 跟場景的 EmotionDisplay
//
// 為什麼要 Play：Cubism Expression Controller 用 LateUpdate 套用 expression。
// Edit 模式 Unity 不 tick LateUpdate，所以設了 CurrentExpressionIndex 也看不到變化。
//

#if UNITY_EDITOR
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

#if SIRO_HAS_CUBISM
using Live2D.Cubism.Framework.Expression;
#endif

namespace Siro.EditorTools
{
    public class ExpressionViewer : EditorWindow
    {
        private const string MENU_PATH = "Tools/SIRO/Expression Viewer";

        [MenuItem(MENU_PATH)]
        public static void Open()
        {
            var w = GetWindow<ExpressionViewer>("SIRO Expression Viewer");
            w.minSize = new Vector2(380, 480);
        }

#if SIRO_HAS_CUBISM
        private CubismExpressionController _controller;
        private string[] _expressionNames = new string[0];
        private int _currentIndex = -1;
        private Vector2 _scroll;

        // 使用者記下的對應（key = expression asset name，含 .exp3 後綴）
        private Dictionary<string, string> _userNotes = new Dictionary<string, string>();

        private void OnEnable()
        {
            RefreshTarget();
        }

        private void OnGUI()
        {
            EditorGUILayout.LabelField("SIRO Expression Viewer", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "幫你校準 emotion → expression 對應。\n" +
                "1. 進 Play 模式（Edit 模式 Cubism 不會套用 expression）\n" +
                "2. 按 Refresh 掃出模型的 expressions\n" +
                "3. 一個個試，記下哪個 exp_XX 是哪種情緒\n" +
                "4. 抄回 bridge/emotion_mapping.json + 場景 EmotionDisplay",
                MessageType.Info);

            EditorGUILayout.Space();

            // ---------------- Refresh / Status ----------------
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Refresh Expressions", GUILayout.Height(30)))
            {
                RefreshTarget();
            }
            string status = !Application.isPlaying
                ? "⚠ 不在 Play 模式，切換無視覺效果"
                : (_controller == null ? "❌ 找不到 CubismExpressionController" : "✅ Ready");
            EditorGUILayout.LabelField(status, GUILayout.Height(30));
            EditorGUILayout.EndHorizontal();

            if (_controller == null)
            {
                EditorGUILayout.HelpBox(
                    "找不到 CubismExpressionController。\n" +
                    "確認場景裡有 Mao (或其他 Cubism 模型)，且 Mao 上掛了 CubismExpressionController。",
                    MessageType.Warning);
                return;
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField(
                $"模型: {_controller.gameObject.name}   |   " +
                $"找到 {_expressionNames.Length} 個 expression   |   " +
                $"目前: {(_currentIndex >= 0 ? _expressionNames[_currentIndex] : "(無)")}",
                EditorStyles.miniLabel);

            // ---------------- Expression Buttons ----------------
            EditorGUILayout.Space();
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            for (int i = 0; i < _expressionNames.Length; i++)
            {
                EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);

                bool isCurrent = (i == _currentIndex);
                var btnStyle = new GUIStyle(GUI.skin.button);
                if (isCurrent) btnStyle.normal.textColor = Color.green;

                // 按鈕：試這個 expression
                if (GUILayout.Button(
                    isCurrent ? $"● {_expressionNames[i]}" : $"Try  {_expressionNames[i]}",
                    btnStyle,
                    GUILayout.Width(160), GUILayout.Height(24)))
                {
                    Apply(i);
                }

                // 文字框：使用者寫對應
                string key = _expressionNames[i];
                _userNotes.TryGetValue(key, out string note);
                string newNote = EditorGUILayout.TextField(note ?? "", GUILayout.Height(22));
                if (newNote != note)
                {
                    _userNotes[key] = newNote;
                }

                EditorGUILayout.EndHorizontal();
            }
            EditorGUILayout.EndScrollView();

            // ---------------- Bottom Actions ----------------
            EditorGUILayout.Space();
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Cycle All (2s each)", GUILayout.Height(28)))
            {
                StartCycle();
            }
            if (GUILayout.Button("Print Notes → Console", GUILayout.Height(28)))
            {
                PrintNotes();
            }
            EditorGUILayout.EndHorizontal();

            if (_cycleActive)
            {
                EditorGUILayout.HelpBox(
                    $"循環中... {_cycleIndex + 1}/{_expressionNames.Length}   " +
                    $"(現在: {_expressionNames[_cycleIndex]})",
                    MessageType.Info);
                if (GUILayout.Button("Stop Cycle"))
                {
                    _cycleActive = false;
                }
            }
        }

        // ==================== 內部 ====================

        private void RefreshTarget()
        {
            _controller = FindFirstObjectByType<CubismExpressionController>();
            if (_controller == null)
            {
                _expressionNames = new string[0];
                _currentIndex = -1;
                return;
            }

            var list = _controller.ExpressionsList?.CubismExpressionObjects;
            if (list == null)
            {
                _expressionNames = new string[0];
                _currentIndex = -1;
                return;
            }

            var names = new List<string>();
            for (int i = 0; i < list.Length; i++)
            {
                names.Add(list[i] != null ? list[i].name : "<null>");
            }
            _expressionNames = names.ToArray();
            _currentIndex = _controller.CurrentExpressionIndex;
            Repaint();
        }

        private void Apply(int index)
        {
            if (_controller == null || index < 0 || index >= _expressionNames.Length) return;

            if (!Application.isPlaying)
            {
                EditorUtility.DisplayDialog(
                    "需要 Play 模式",
                    "Cubism expression 是 runtime 套用的（LateUpdate）。\n" +
                    "請先按 Play 模式再試。",
                    "OK");
                return;
            }

            // 優先走 Live2DModelController.SetExpression，這樣 hide-eye hack
            // 等 SIRO 客製邏輯會跟著跑。找不到 Live2DModelController 才退回直接設 index。
            var siroController = _controller.GetComponent<Siro.Live2DModelController>();
            if (siroController != null)
            {
                siroController.SetExpression(_expressionNames[index]);
            }
            else
            {
                _controller.CurrentExpressionIndex = index;
            }
            _currentIndex = index;
            Repaint();
        }

        // ---------------- Cycle All ----------------

        private bool _cycleActive = false;
        private int _cycleIndex = 0;
        private double _cycleNextTime = 0;
        private const double CYCLE_INTERVAL = 2.0;

        private void StartCycle()
        {
            if (!Application.isPlaying)
            {
                EditorUtility.DisplayDialog(
                    "需要 Play 模式",
                    "請先進 Play 模式再 Cycle。",
                    "OK");
                return;
            }
            if (_expressionNames.Length == 0) return;
            _cycleActive = true;
            _cycleIndex = 0;
            _cycleNextTime = EditorApplication.timeSinceStartup + CYCLE_INTERVAL;
            Apply(0);
            EditorApplication.update -= CycleTick;
            EditorApplication.update += CycleTick;
        }

        private void CycleTick()
        {
            if (!_cycleActive)
            {
                EditorApplication.update -= CycleTick;
                return;
            }
            if (EditorApplication.timeSinceStartup < _cycleNextTime) return;

            _cycleIndex++;
            if (_cycleIndex >= _expressionNames.Length)
            {
                _cycleActive = false;
                EditorApplication.update -= CycleTick;
                return;
            }
            Apply(_cycleIndex);
            _cycleNextTime = EditorApplication.timeSinceStartup + CYCLE_INTERVAL;
            Repaint();
        }

        // ---------------- Print Notes ----------------

        private void PrintNotes()
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("=== Expression Notes ===");
            for (int i = 0; i < _expressionNames.Length; i++)
            {
                string name = _expressionNames[i];
                _userNotes.TryGetValue(name, out string note);
                sb.AppendLine($"  {name}: {(string.IsNullOrEmpty(note) ? "(未記)" : note)}");
            }
            sb.AppendLine();
            sb.AppendLine("提示：把這份記錄抄回 bridge/emotion_mapping.json 跟場景 EmotionDisplay。");
            Debug.Log(sb.ToString());
        }

#else  // !SIRO_HAS_CUBISM

        private void OnGUI()
        {
            EditorGUILayout.HelpBox(
                "SIRO_HAS_CUBISM 未啟用。\n" +
                "請到 Project Settings → Player → Other Settings → " +
                "Scripting Define Symbols 加 SIRO_HAS_CUBISM",
                MessageType.Error);
        }
#endif
    }
}
#endif
