// unity/Assets/Editor/SetupChineseFont.cs
//
// 一鍵裝中文（或其他 .ttf）字型到所有 TMP 元件
//
// 流程：
//   1. 找 Assets/Fonts/ 下的 .ttf/.otf
//   2. 找不到跳出檔案選擇對話框
//   3. 用 TMP_FontAsset.CreateFontAsset 建立 font asset
//   4. 套到場景裡所有 TMP 元件
//
// 用法：Tools → SIRO → Setup Chinese Font

#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;

namespace Siro.EditorTools
{
    public static class SetupChineseFont
    {
        [MenuItem("Tools/SIRO/Setup Chinese Font")]
        public static void Setup()
        {
            // 1. 找字型檔
            string fontPath = FindFontFile();
            if (string.IsNullOrEmpty(fontPath))
            {
                // 跳檔案選擇對話框
                fontPath = EditorUtility.OpenFilePanel(
                    "選 CJK 字型檔（.ttf 或 .otf）",
                    Application.dataPath,
                    "ttf,otf"
                );
                if (string.IsNullOrEmpty(fontPath))
                {
                    Debug.LogWarning("[SetupChineseFont] 使用者取消");
                    return;
                }
                // 複製到 Assets/Fonts/
                string targetDir = Path.Combine(Application.dataPath, "Fonts");
                Directory.CreateDirectory(targetDir);
                string targetPath = Path.Combine(targetDir, Path.GetFileName(fontPath));
                File.Copy(fontPath, targetPath, true);
                fontPath = "Assets/Fonts/" + Path.GetFileName(fontPath);
                AssetDatabase.Refresh();
                Debug.Log($"[SetupChineseFont] 複製字型到 {fontPath}");
            }

            // 2. 載入字型
            Font font = AssetDatabase.LoadAssetAtPath<Font>(fontPath);
            if (font == null)
            {
                Debug.LogError($"[SetupChineseFont] ❌ 載入字型失敗：{fontPath}");
                return;
            }
            Debug.Log($"[SetupChineseFont] ✓ 載入字型：{font.name}");

            // 3. 建立 TMP font asset
            TMP_FontAsset fontAsset = TMP_FontAsset.CreateFontAsset(font);
            fontAsset.name = Path.GetFileNameWithoutExtension(fontPath) + " SDF";

            // 4. 存到 Assets/Fonts/
            string assetPath = $"Assets/Fonts/{fontAsset.name}.asset";
            // 刪除舊的（如果有）
            if (AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(assetPath) != null)
            {
                AssetDatabase.DeleteAsset(assetPath);
            }
            AssetDatabase.CreateAsset(fontAsset, assetPath);
            AssetDatabase.SaveAssets();
            Debug.Log($"[SetupChineseFont] ✓ 建立 font asset：{assetPath}");

            // 5. 套用到場景所有 TMP 元件
            int count = ApplyToAllTmpComponents(fontAsset);
            Debug.Log($"[SetupChineseFont] ✓ 套用 {count} 個 TMP 元件");

            // 6. 順便還原中文 placeholder（之前用 Englishify 改成英文）
            RestoreChinesePlaceholders();
        }

        private static string FindFontFile()
        {
            // 常見位置
            string[] searchDirs = {
                Path.Combine(Application.dataPath, "Fonts"),
                Path.Combine(Application.dataPath, "TextMesh Pro/Fonts"),
                Path.Combine(Application.dataPath, "TextMesh Pro/Resources/Fonts & Materials"),
            };

            string[] keywords = { "noto", "cjk", "han", "sourcehan", "chinese" };
            string[] exts = { "*.ttf", "*.otf" };

            foreach (var dir in searchDirs)
            {
                if (!Directory.Exists(dir)) continue;
                foreach (var ext in exts)
                {
                    var files = Directory.GetFiles(dir, ext, SearchOption.TopDirectoryOnly);
                    foreach (var f in files)
                    {
                        var name = Path.GetFileName(f).ToLower();
                        if (keywords.Any(k => name.Contains(k)))
                        {
                            return "Assets" + f.Substring(Application.dataPath.Length).Replace('\\', '/');
                        }
                    }
                }
            }
            return null;
        }

        private static int ApplyToAllTmpComponents(TMP_FontAsset fontAsset)
        {
            int count = 0;
            var tmps = UnityEngine.Object.FindObjectsByType<TMP_Text>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            foreach (var t in tmps)
            {
                Undo.RecordObject(t, "Apply Chinese Font");
                t.font = fontAsset;
                count++;
            }
            return count;
        }

        private static void RestoreChinesePlaceholders()
        {
            var tmps = UnityEngine.Object.FindObjectsByType<TMP_Text>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            foreach (var t in tmps)
            {
                string newText = t.text;
                if (newText == "Type message...") newText = "輸入訊息...";
                else if (newText == "(Waiting for connection...)") newText = "（等待連線...）";
                else if (newText == "Send") newText = "送出";  // Send 按鈕

                if (newText != t.text)
                {
                    Undo.RecordObject(t, "Restore Chinese Text");
                    t.text = newText;
                }
            }
            Debug.Log("[SetupChineseFont] ✓ 還原中文 placeholder");
        }
    }
}
#endif
