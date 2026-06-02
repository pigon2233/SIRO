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
            // 簡單做法：直接 ForceUpdate reimport Mao.moc3
            // CubismAssetProcessor 會被 OnPostprocessAllAssets 觸發
            // 自動重建 prefab / asset / expression list 並重新綁定紋理
            string moc3Path = "Assets/Live2D/Cubism/Samples/Models/Mao/Mao.moc3";
            string model3Path = "Assets/Live2D/Cubism/Samples/Models/Mao/Mao.model3.json";

            Debug.Log("[Cubism Reimport] 強制 reimport Mao.moc3 跟 .model3.json ...");
            Debug.Log("這會觸發 CubismAssetProcessor 重新跑 importer：");
            Debug.Log("  - 重建 Mao.prefab");
            Debug.Log("  - 重建 Mao.asset");
            Debug.Log("  - 重建所有 expression list / motion list");
            Debug.Log("  - 重新綁定材質的 _MainTex 紋理");

            if (File.Exists(moc3Path))
            {
                AssetDatabase.ImportAsset(moc3Path, ImportAssetOptions.ForceUpdate);
            }
            else
            {
                Debug.LogError($"找不到 {moc3Path}");
            }

            if (File.Exists(model3Path))
            {
                AssetDatabase.ImportAsset(model3Path, ImportAssetOptions.ForceUpdate);
            }

            // 也 reimport motions 跟 expressions 子資料夾
            string[] subdirs = { "motions", "expressions" };
            foreach (var sub in subdirs)
            {
                string subPath = $"Assets/Live2D/Cubism/Samples/Models/Mao/{sub}";
                if (Directory.Exists(subPath))
                {
                    AssetDatabase.ImportAsset(subPath, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ImportRecursive);
                }
            }

            AssetDatabase.Refresh();

            Debug.Log("[Cubism Reimport] 完成了。檢查 Mao.prefab 跟材質 _MainTex 是否有 texture");
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
