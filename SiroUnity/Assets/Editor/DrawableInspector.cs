// SiroUnity/Assets/Editor/DrawableInspector.cs
//
// SIRO Drawable Inspector — 找出 Cubism 模型上「眼球」mesh 是哪個 Drawable 用的工具
//
// 動機：Mao 的 exp_02 / exp_03 閉眼設計不完整，眼皮 mesh 蓋不住瞳孔。
//      要 runtime hide 眼球 mesh 解決，但不知道眼球是哪個 Drawable Id。
//      這個工具列出所有 Drawable，每個給個 Hide/Show only/Isolate 按鈕。
//      使用者拉一下就能找出眼球並記下 Id。
//
// 使用：
//   1. 進 Play 模式（Cubism Drawable 是 runtime 物件）
//   2. 選單 → Tools → SIRO → Drawable Inspector
//   3. 按 Refresh 掃出 Mao 的所有 Drawable
//   4. 一個個按 [Hide] 看 Mao 哪個部位消失。找到眼球後記下 Id。
//   5. 按 Restore All 恢復全部
//   6. 把眼球 Id 告訴 Claude，我會改 Live2DModelController 自動隱藏。
//
// 隱藏機制：用 MeshRenderer.enabled = false，比改 Drawable.Opacity 可靠
// （Cubism LateUpdate 會 reset Opacity，但不會碰 MeshRenderer.enabled）。
//

#if UNITY_EDITOR
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

#if SIRO_HAS_CUBISM
using Live2D.Cubism.Core;
#endif

namespace Siro.EditorTools
{
    public class DrawableInspector : EditorWindow
    {
        [MenuItem("Tools/SIRO/Drawable Inspector")]
        public static void Open()
        {
            var w = GetWindow<DrawableInspector>("SIRO Drawable Inspector");
            w.minSize = new Vector2(450, 600);
        }

#if SIRO_HAS_CUBISM
        private CubismModel _model;
        private CubismDrawable[] _drawables;
        private MeshRenderer[] _renderers;
        private string _filter = "";
        private Vector2 _scroll;

        private void OnEnable()
        {
            Refresh();
        }

        private void OnGUI()
        {
            EditorGUILayout.LabelField("SIRO Drawable Inspector", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "找眼球 mesh 用的工具。\n" +
                "1. 進 Play 模式\n" +
                "2. 按 Refresh\n" +
                "3. [Hide] = 隱藏這個 Drawable，看 Mao 哪邊消失\n" +
                "4. [Isolate] = 只顯示這個（其他全藏），確認形狀\n" +
                "5. 找到眼球 → 把 Id 告訴 Claude",
                MessageType.Info);

            EditorGUILayout.Space();

            // ---------- Refresh / Status ----------
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Refresh", GUILayout.Height(28), GUILayout.Width(100)))
            {
                Refresh();
            }
            if (GUILayout.Button("Restore All", GUILayout.Height(28), GUILayout.Width(110)))
            {
                RestoreAll();
            }
            if (GUILayout.Button("Print All Ids", GUILayout.Height(28), GUILayout.Width(110)))
            {
                PrintAllIds();
            }
            string status = !Application.isPlaying
                ? "⚠ Edit 模式（按 Play 才能找）"
                : (_model == null ? "❌ 找不到 CubismModel" : $"✅ {_drawables.Length} drawables");
            EditorGUILayout.LabelField(status);
            EditorGUILayout.EndHorizontal();

            if (_model == null) return;

            // ---------- Filter ----------
            EditorGUILayout.Space();
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField("Filter (Id contains):", GUILayout.Width(140));
            _filter = EditorGUILayout.TextField(_filter);
            EditorGUILayout.EndHorizontal();

            // ---------- Drawable List ----------
            EditorGUILayout.Space();
            _scroll = EditorGUILayout.BeginScrollView(_scroll);

            int visibleCount = 0;
            for (int i = 0; i < _drawables.Length; i++)
            {
                var d = _drawables[i];
                if (d == null) continue;
                string id = d.Id ?? d.name;
                if (!string.IsNullOrEmpty(_filter) &&
                    id.IndexOf(_filter, System.StringComparison.OrdinalIgnoreCase) < 0)
                {
                    continue;
                }
                visibleCount++;

                EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);

                // ID
                EditorGUILayout.LabelField($"[{i:D3}] {id}", GUILayout.Width(200));

                // 顯示狀態
                bool isEnabled = _renderers[i] != null && _renderers[i].enabled;
                EditorGUILayout.LabelField(isEnabled ? "✓" : "—", GUILayout.Width(20));

                // Toggle / Hide
                if (GUILayout.Button(isEnabled ? "Hide" : "Show", GUILayout.Width(60)))
                {
                    if (_renderers[i] != null) _renderers[i].enabled = !isEnabled;
                }

                // Isolate (只顯示這個)
                if (GUILayout.Button("Isolate", GUILayout.Width(70)))
                {
                    Isolate(i);
                }

                EditorGUILayout.EndHorizontal();
            }

            EditorGUILayout.EndScrollView();

            EditorGUILayout.LabelField($"顯示 {visibleCount} / {_drawables.Length} drawables", EditorStyles.miniLabel);
        }

        // ==================== 內部 ====================

        private void Refresh()
        {
            _model = FindFirstObjectByType<CubismModel>();
            if (_model == null)
            {
                _drawables = new CubismDrawable[0];
                _renderers = new MeshRenderer[0];
                return;
            }

            _drawables = _model.Drawables;
            _renderers = new MeshRenderer[_drawables.Length];
            for (int i = 0; i < _drawables.Length; i++)
            {
                if (_drawables[i] == null) continue;
                _renderers[i] = _drawables[i].GetComponent<MeshRenderer>();
            }
            Repaint();
        }

        private void RestoreAll()
        {
            if (_renderers == null) return;
            for (int i = 0; i < _renderers.Length; i++)
            {
                if (_renderers[i] != null) _renderers[i].enabled = true;
            }
            Repaint();
        }

        private void Isolate(int onlyIndex)
        {
            if (_renderers == null) return;
            for (int i = 0; i < _renderers.Length; i++)
            {
                if (_renderers[i] != null) _renderers[i].enabled = (i == onlyIndex);
            }
            Repaint();
        }

        private void PrintAllIds()
        {
            if (_drawables == null) return;
            var sb = new System.Text.StringBuilder();
            sb.AppendLine($"=== Mao Drawables ({_drawables.Length}) ===");
            for (int i = 0; i < _drawables.Length; i++)
            {
                string id = _drawables[i] != null ? (_drawables[i].Id ?? _drawables[i].name) : "<null>";
                sb.AppendLine($"  [{i:D3}] {id}");
            }
            Debug.Log(sb.ToString());
        }

#else  // !SIRO_HAS_CUBISM

        private void OnGUI()
        {
            EditorGUILayout.HelpBox(
                "SIRO_HAS_CUBISM 未啟用。" +
                "請到 Project Settings → Player → Scripting Define Symbols 加 SIRO_HAS_CUBISM",
                MessageType.Error);
        }
#endif
    }
}
#endif
