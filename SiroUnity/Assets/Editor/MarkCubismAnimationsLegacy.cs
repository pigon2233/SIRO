// unity/Assets/Editor/MarkCubismAnimationsLegacy.cs
//
// 把 Cubism SDK sample 的 .anim 標記為 Legacy、
// 這樣 Unity 舊的 Animation component 才能播。
//
// 為什麼需要：
//   Cubism SDK 匯入的 .anim 預設 m_Legacy=0（Generic），
//   但 Live2DModelController.PlayMotion 用的是 legacy Animation component。
//   強行 AddClip 會跳 warning：
//     "The AnimationClip 'mtn_xx' used by the Animation component 'Mao'
//      must be marked as Legacy."
//
// 用法（Unity 選單）：
//   Tools → SIRO → Mark Cubism .anim as Legacy
//
// 何時需要跑：
//   1. 第一次拉 Cubism SDK 進專案
//   2. 更新 Cubism SDK 版本（.anim 會被覆蓋、m_Legacy 回到 0）
//   3. Force Reimport Mao 之後 .anim 被 SDK importer 重新產出

#if UNITY_EDITOR
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

namespace Siro.EditorTools
{
    public static class MarkCubismAnimationsLegacy
    {
        private const string CUBISM_SAMPLES_ROOT = "Assets/Live2D/Cubism/Samples/Models";

        [MenuItem("Tools/SIRO/Mark Cubism .anim as Legacy")]
        public static void MarkAllAsLegacy()
        {
            if (!Directory.Exists(CUBISM_SAMPLES_ROOT))
            {
                Debug.LogError($"[MarkCubismAnimationsLegacy] 找不到 {CUBISM_SAMPLES_ROOT}");
                return;
            }

            // 找所有 */motions/*.anim
            string[] animPaths = Directory.GetFiles(
                CUBISM_SAMPLES_ROOT, "*.anim", SearchOption.AllDirectories
            );

            int fixedCount = 0;
            int alreadyLegacyCount = 0;
            int skippedCount = 0;

            try
            {
                AssetDatabase.StartAssetEditing();

                foreach (string absPath in animPaths)
                {
                    // 只處理 motions 子資料夾裡的 .anim（避免動到其他用途的）
                    string normalized = absPath.Replace('\\', '/');
                    if (!normalized.Contains("/motions/"))
                    {
                        skippedCount++;
                        continue;
                    }

                    string text = File.ReadAllText(absPath);
                    if (text.Contains("m_Legacy: 1"))
                    {
                        alreadyLegacyCount++;
                        continue;
                    }

                    // 走 regex 精準替換 m_Legacy 行（不是字串 replace、避免誤觸）
                    string updated = Regex.Replace(
                        text,
                        @"^(\s*)m_Legacy:\s*0\s*$",
                        "$1m_Legacy: 1",
                        RegexOptions.Multiline
                    );

                    if (updated == text)
                    {
                        Debug.LogWarning(
                            $"[MarkCubismAnimationsLegacy] {absPath} 沒找到 m_Legacy: 0（格式不對？）"
                        );
                        continue;
                    }

                    File.WriteAllText(absPath, updated);
                    // 重新 import 讓 Unity 讀到新的 m_Legacy 值
                    string assetPath = "Assets" + absPath.Substring(Application.dataPath.Length);
                    AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
                    fixedCount++;
                }
            }
            finally
            {
                AssetDatabase.StopAssetEditing();
                AssetDatabase.SaveAssets();
            }

            Debug.Log(
                $"[MarkCubismAnimationsLegacy] 完成：修了 {fixedCount} 個、已經是 Legacy 的 {alreadyLegacyCount} 個、跳過 {skippedCount} 個"
            );
        }
    }
}
#endif
