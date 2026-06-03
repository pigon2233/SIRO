// unity/Assets/Editor/AddCubismComponents.cs
//
// 給 Mao（事實上任何 Cubism model prefab）補上缺的 components：
//   - CubismModel (核心，沒它整個模型不運作)
//   - CubismRenderController (控制 render order)
//
// SDK 5-r.5 的 prefab 似乎匯出時漏了這兩個 component。
//
// 用法：Tools → SIRO → Add Missing Cubism Components

#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace Siro.EditorTools
{
    public static class AddCubismComponents
    {
        [MenuItem("Tools/SIRO/Add Missing Cubism Components")]
        public static void AddToMao()
        {
            var mao = GameObject.Find("Mao");
            if (mao == null)
            {
                Debug.LogError("[AddCubismComponents] ❌ 找不到 Mao");
                return;
            }

            AddToGameObject(mao, savePrefab: true);
        }

        public static void AddToGameObject(GameObject go, bool savePrefab = true)
        {
            // 用 reflection 找 CubismModel 跟 CubismRenderController 型別
            // （避免 hard-dependency on assembly references）

            System.Type modelType = null;
            System.Type renderControllerType = null;

            foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                if (modelType == null)
                    modelType = asm.GetType("Live2D.Cubism.Core.CubismModel");
                if (renderControllerType == null)
                    renderControllerType = asm.GetType("Live2D.Cubism.Rendering.CubismRenderController");
                if (modelType != null && renderControllerType != null) break;
            }

            if (modelType == null)
            {
                Debug.LogError("[AddCubismComponents] ❌ 找不到 CubismModel 型別（Cubism SDK 沒編譯？）");
                return;
            }
            if (renderControllerType == null)
            {
                Debug.LogError("[AddCubismComponents] ❌ 找不到 CubismRenderController 型別");
                return;
            }

            int added = 0;

            // 加 CubismModel
            if (go.GetComponent(modelType) == null)
            {
                Undo.AddComponent(go, modelType);
                added++;
                Debug.Log($"[AddCubismComponents] ✓ 加了 {modelType.Name} 到 {go.name}");
            }
            else
            {
                Debug.Log($"[AddCubismComponents] – {go.name} 已有 CubismModel");
            }

            // 加 CubismRenderController
            if (go.GetComponent(renderControllerType) == null)
            {
                Undo.AddComponent(go, renderControllerType);
                added++;
                Debug.Log($"[AddCubismComponents] ✓ 加了 {renderControllerType.Name} 到 {go.name}");
            }
            else
            {
                Debug.Log($"[AddCubismComponents] – {go.name} 已有 CubismRenderController");
            }

            if (added == 0)
            {
                Debug.Log("[AddCubismComponents] ✓ 都加好了（或已存在）");
            }

            // 存 prefab
            if (savePrefab)
            {
                string prefabPath = "Assets/Live2D/Cubism/Samples/Models/Mao/Mao.prefab";
                PrefabUtility.SaveAsPrefabAsset(go, prefabPath);
                Debug.Log($"[AddCubismComponents] ✓ 存了 prefab：{prefabPath}");
            }

            EditorSceneManager.MarkSceneDirty(go.scene);
        }
    }
}
#endif
