// unity/Assets/Editor/CubismReimport.cs
//
// 一鍵強制重跑 Cubism importer
//
// 用法（Unity 選單）：
//   Tools → SIRO → Force Reimport Mao
//   Tools → SIRO → Force Reimport All Cubism Models
//
// 為什麼需要：
// 對 Mao 資料夾按 Reimport 沒用時，importer 可能因為 asset 已經被
// 認為"import 過"而跳過。這個工具用 AssetDatabase.ImportAsset
// 帶 ForceUpdate 強制重 import，確保 CubismAssetProcessor.OnPostprocessAllAssets
// 會被觸發。

#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Siro.EditorTools
{
    public static class CubismReimport
    {
        private const string MAO_PATH = "Assets/Live2D/Cubism/Samples/Models/Mao";

        [MenuItem("Tools/SIRO/Force Reimport Mao")]
        public static void ForceReimportMao()
        {
            if (!Directory.Exists(MAO_PATH))
            {
                Debug.LogError($"找不到 {MAO_PATH}");
                return;
            }

            Debug.Log("[Cubism Reimport] 開始強制 reimport Mao...");

            // 刪除所有 .meta + importer 產生的 asset (prefab, asset, expression list 等)
            // 留原始檔 (.moc3, .model3.json, .2048, .png, .cdi3.json, .pose3.json, .physics3.json, .motion3.json)
            string[] toKeep = {
                ".moc3", ".model3.json", ".motion3.json", ".exp3.json",
                ".pose3.json", ".physics3.json", ".cdi3.json",
                ".png", ".2048"  // .2048 是目錄
            };

            var dir = new DirectoryInfo(MAO_PATH);
            int deleted = 0;
            foreach (var file in dir.GetFiles("*", SearchOption.AllDirectories))
            {
                if (file.Extension == ".meta") continue;
                bool shouldKeep = false;
                foreach (var ext in toKeep)
                {
                    if (ext == ".2048") // 是目錄
                    {
                        if (file.Directory?.Name == "Mao.2048") { shouldKeep = true; break; }
                    }
                    else if (file.Name.EndsWith(ext, System.StringComparison.OrdinalIgnoreCase))
                    {
                        shouldKeep = true; break;
                    }
                }

                if (!shouldKeep)
                {
                    Debug.Log($"[Cubism Reimport] 刪除: {file.FullName}");
                    AssetDatabase.DeleteAsset(file.FullName.Replace(Application.dataPath, "Assets").Replace('\\', '/'));
                    deleted++;
                }
            }

            // 也刪掉 .meta 檔
            foreach (var meta in dir.GetFiles("*.meta", SearchOption.AllDirectories))
            {
                AssetDatabase.DeleteAsset(meta.FullName.Replace(Application.dataPath, "Assets").Replace('\\', '/'));
            }

            AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);

            Debug.Log($"[Cubism Reimport] 刪了 {deleted} 個檔 + 全部 .meta");
            Debug.Log("[Cubism Reimport] 接下來 Unity 會自動 reimport 觸發 CubismAssetProcessor");
        }

        [MenuItem("Tools/SIRO/Force Reimport All Cubism Models")]
        public static void ForceReimportAllModels()
        {
            string[] modelDirs = {
                "Assets/Live2D/Cubism/Samples/Models/Mao",
                "Assets/Live2D/Cubism/Samples/Models/Ren",
                "Assets/Live2D/Cubism/Samples/Models/Koharu",
                "Assets/Live2D/Cubism/Samples/Models/Natori",
                "Assets/Live2D/Cubism/Samples/Models/Rice",
                "Assets/Live2D/Cubism/Samples/Models/Clipping",
            };

            foreach (var d in modelDirs)
            {
                if (Directory.Exists(d))
                {
                    Debug.Log($"[Cubism Reimport] Reimport {d}");
                    AssetDatabase.ImportAsset(d, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ImportRecursive);
                }
            }
            AssetDatabase.Refresh();
        }
    }
}
#endif
