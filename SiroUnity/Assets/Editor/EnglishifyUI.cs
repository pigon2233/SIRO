// unity/Assets/Editor/EnglishifyUI.cs
//
// 把 SIRO UI 上所有 TMP 文字暫時換成英文（v0 中文支援還沒裝好前用）
//
// 用法：Tools → SIRO → Englishify Chat UI

#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using TMPro;

namespace Siro.EditorTools
{
    public static class EnglishifyUI
    {
        [MenuItem("Tools/SIRO/Englishify Chat UI")]
        public static void Englishify()
        {
            int count = 0;
            // 找 Canvas 下所有 TMP 元件
            var canvases = Object.FindObjectsByType<Canvas>(FindObjectsSortMode.None);
            foreach (var canvas in canvases)
            {
                var tmps = canvas.GetComponentsInChildren<TMP_Text>(true);
                foreach (var t in tmps)
                {
                    string newText = t.text;
                    // 簡單的繁中 → 英 mapping
                    if (newText.Contains("輸入")) newText = "Type message...";
                    else if (newText.Contains("等待")) newText = "(Waiting for connection...)";
                    else if (newText == "Send") newText = "Send";  // 已經是英文

                    if (newText != t.text)
                    {
                        Undo.RecordObject(t, "Englishify TMP");
                        t.text = newText;
                        count++;
                    }
                }
            }
            Debug.Log($"[Englishify] ✓ 改了 {count} 個 TMP 文字");
        }
    }
}
#endif
