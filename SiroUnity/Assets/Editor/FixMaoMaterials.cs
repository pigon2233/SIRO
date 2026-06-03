// unity/Assets/Editor/FixMaoMaterials.cs
//
// 修正 Mao 的所有 ArtMesh 材質：把錯誤的 TransparentPicking 換成正確的
// UnlitBlendMode* 材質，並綁定 Mao.2048/texture_00.png 紋理。
//
// 用法：Tools → SIRO → Fix Mao Materials
//
// 來源資訊：
// - Mao.2048/texture_00.png (紋理 atlas)
// - Mao.cdi3.json (每個 ArtMesh 的 BlendMode)
// - UnlitBlendMode{Normal,Add,Multiply}.mat (SDK 預設材質)

#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Siro.EditorTools
{
    public static class FixMaoMaterials
    {
        private const string MAO_PATH = "Assets/Live2D/Cubism/Samples/Models/Mao";
        private const string TEXTURE_PATH = MAO_PATH + "/Mao.2048/texture_00.png";
        private const string CDI3_PATH = MAO_PATH + "/Mao.cdi3.json";

        [MenuItem("Tools/SIRO/Fix Mao Materials")]
        public static void Fix()
        {
            // 1. 載入紋理
            Texture2D texture = AssetDatabase.LoadAssetAtPath<Texture2D>(TEXTURE_PATH);
            if (texture == null)
            {
                Debug.LogError($"❌ 找不到紋理: {TEXTURE_PATH}");
                return;
            }
            Debug.Log($"✓ 載入紋理: {texture.name} ({texture.width}x{texture.height})");

            // 2. 載入 cdi3.json 取得每個 ArtMesh 的 blend mode
            Dictionary<string, string> blendModes = ParseCdi3(CDI3_PATH);
            Debug.Log($"✓ cdi3.json 解析完成: {blendModes.Count} 個 ArtMesh");

            // 3. 載入材質（SDK 5-r.5 新路徑：直接放在 Materials/ 下，沒 BlendMode 子資料夾）
            string basePath = "Assets/Live2D/Cubism/Rendering/Resources/Live2D/Cubism/Materials";
            Material normalMat = LoadMaterial($"{basePath}/Unlit.mat");
            Material addMat = LoadMaterial($"{basePath}/UnlitAdditive.mat");
            Material multiplyMat = LoadMaterial($"{basePath}/UnlitMultiply.mat");

            if (normalMat == null)
            {
                Debug.LogError("❌ 找不到 Unlit.mat");
                return;
            }
            Debug.Log($"✓ 載入材質: Normal, Add={addMat != null}, Multiply={multiplyMat != null}");

            // 4. 找場景的 Mao
            GameObject mao = GameObject.Find("Mao");
            if (mao == null)
            {
                Debug.LogError("❌ 場景裡找不到 Mao。拖 Mao.prefab 進場景再跑一次。");
                return;
            }

            // 5. 修正每個 ArtMesh
            var meshFilters = mao.GetComponentsInChildren<MeshFilter>(true);
            int fixedCount = 0, enabledCount = 0;

            foreach (var mf in meshFilters)
            {
                var go = mf.gameObject;
                var rend = go.GetComponent<MeshRenderer>();
                if (rend == null) continue;

                // 找對應的 blend mode
                string blend = "Normal";
                if (blendModes.TryGetValue(go.name, out var b)) blend = b;
                Material mat = normalMat;
                switch (blend)
                {
                    case "Additive": mat = addMat ?? normalMat; break;
                    case "Multiply": mat = multiplyMat ?? normalMat; break;
                    default: mat = normalMat; break;
                }

                // 設 _MainTex 紋理（用 instanced 材質避免改到原 .mat）
                Material instanced = new Material(mat);
                instanced.name = go.name + "_Fixed";
                if (instanced.HasProperty("_MainTex"))
                {
                    instanced.SetTexture("_MainTex", texture);
                }
                else if (instanced.HasProperty("cubism_MainTexture"))
                {
                    instanced.SetTexture("cubism_MainTexture", texture);
                }

                rend.sharedMaterial = instanced;

                // 啟用 renderer（之前有 4 個是 disabled）
                if (!rend.enabled)
                {
                    rend.enabled = true;
                    enabledCount++;
                }

                fixedCount++;
            }

            Debug.Log($"✓ 修正了 {fixedCount} 個 ArtMesh 材質（場景實例）");
            if (enabledCount > 0) Debug.Log($"  其中 {enabledCount} 個 renderer 從 disabled 改成 enabled");

            // 6. 標記 prefab 為 dirty
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(mao.scene);
            Debug.Log("✓ 場景已標記 dirty，記得存檔 Ctrl+S");

            // 7. 改 prefab 本身（重要：場景實例被刪掉或 Play mode 重 instantiate 時材質不能丟）
            // 直接編輯 prefab asset 的每個 ArtMesh，把材質 reference 寫進去
            var prefabPath = "Assets/Live2D/Cubism/Samples/Models/Mao/Mao.prefab";
            var prefabRoot = PrefabUtility.LoadPrefabContents(prefabPath);
            try
            {
                if (prefabRoot != null)
                {
                    int prefabFixed = 0;
                    var prefabMeshFilters = prefabRoot.GetComponentsInChildren<MeshFilter>(true);
                    foreach (var mf in prefabMeshFilters)
                    {
                        var go = mf.gameObject;
                        var rend = go.GetComponent<MeshRenderer>();
                        if (rend == null) continue;

                        string blend = "Normal";
                        if (blendModes.TryGetValue(go.name, out var b)) blend = b;
                        Material srcMat = normalMat;
                        switch (blend)
                        {
                            case "Additive": srcMat = addMat ?? normalMat; break;
                            case "Multiply": srcMat = multiplyMat ?? normalMat; break;
                            default: srcMat = normalMat; break;
                        }

                        Material instanced = new Material(srcMat);
                        instanced.name = go.name + "_Fixed";
                        if (instanced.HasProperty("_MainTex"))
                        {
                            instanced.SetTexture("_MainTex", texture);
                        }
                        else if (instanced.HasProperty("cubism_MainTexture"))
                        {
                            instanced.SetTexture("cubism_MainTexture", texture);
                        }

                        rend.sharedMaterial = instanced;
                        if (!rend.enabled) rend.enabled = true;
                        prefabFixed++;
                    }

                    PrefabUtility.SaveAsPrefabAsset(prefabRoot, prefabPath);
                    Debug.Log($"✓ 也修了 prefab 本身：{prefabPath}（{prefabFixed} 個 ArtMesh）");
                }
                else
                {
                    Debug.LogWarning($"⚠ 載入 prefab 失敗：{prefabPath}");
                }
            }
            finally
            {
                if (prefabRoot != null)
                {
                    PrefabUtility.UnloadPrefabContents(prefabRoot);
                }
            }
        }

        private static Material LoadMaterial(string path)
        {
            return AssetDatabase.LoadAssetAtPath<Material>(path);
        }

        private static Dictionary<string, string> ParseCdi3(string path)
        {
            var result = new Dictionary<string, string>();
            if (!File.Exists(path))
            {
                Debug.LogWarning($"找不到 {path}");
                return result;
            }

            string json = File.ReadAllText(path);
            // 簡單 regex 找 "Id": "...","Name": "...","BlendMode": "..."
            // （CDI 格式很複雜，但這個最簡單的方式就夠用）
            var partRegex = new System.Text.RegularExpressions.Regex(
                "\"Id\"\\s*:\\s*\"([^\"]+)\"[^}]*?\"BlendMode\"\\s*:\\s*\"([^\"]+)\"",
                System.Text.RegularExpressions.RegexOptions.Singleline
            );
            foreach (System.Text.RegularExpressions.Match m in partRegex.Matches(json))
            {
                result[m.Groups[1].Value] = m.Groups[2].Value;
            }
            return result;
        }
    }
}
#endif
