// unity/Assets/Editor/ResizeMao.cs
//
// 完整版 Mao 設定工具：位置、scale、Camera、Canvas 排序。
//
// 用法：Tools → SIRO → Setup Mao For Display

#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;

namespace Siro.EditorTools
{
    public static class ResizeMao
    {
        private const float DEFAULT_SCALE = 3.0f;
        private static readonly Vector3 DEFAULT_CAMERA_POS = new Vector3(0, 0, -10);

        [MenuItem("Tools/SIRO/Setup Mao For Display")]
        public static void Resize()
        {
            var mao = GameObject.Find("Mao");
            if (mao == null)
            {
                Debug.LogError("[ResizeMao] ❌ 找不到 Mao");
                return;
            }

            // 1. 設 Mao transform
            Undo.RecordObject(mao.transform, "Resize Mao");
            mao.transform.position = Vector3.zero;
            mao.transform.rotation = Quaternion.identity;
            mao.transform.localScale = Vector3.one * DEFAULT_SCALE;
            Debug.Log($"[ResizeMao] ✓ Mao: pos=(0,0,0), scale=({DEFAULT_SCALE})");

            // 設 Mao 為 Default layer
            mao.layer = 0;  // Default
            Debug.Log("[ResizeMao] ✓ Mao layer = Default");

            // 2. 設 Camera
            var cam = Camera.main;
            if (cam == null) cam = Object.FindFirstObjectByType<Camera>();
            if (cam != null)
            {
                Undo.RecordObject(cam.transform, "Position Camera");
                cam.transform.position = DEFAULT_CAMERA_POS;
                cam.transform.rotation = Quaternion.identity;
                cam.nearClipPlane = 0.01f;
                cam.farClipPlane = 100f;
                cam.orthographic = false;
                // Culling Mask = Everything（不漏 Mao）
                cam.cullingMask = ~0;
                Debug.Log($"[ResizeMao] ✓ Camera: pos={DEFAULT_CAMERA_POS}, culling=Everything");
            }

            // 3. 修 Canvas 排序（讓 UI 蓋在 Mao 上）
            var canvases = Object.FindObjectsByType<Canvas>(FindObjectsSortMode.None);
            foreach (var canvas in canvases)
            {
                if (canvas.renderMode == RenderMode.ScreenSpaceOverlay)
                {
                    // Screen Space - Overlay 預設就會蓋在 3D 上，不用改
                    Debug.Log($"[ResizeMao] ✓ Canvas '{canvas.name}' 是 Overlay（自動在最上層）");
                }
                else
                {
                    // 如果不是 Overlay，改成 Screen Space - Camera
                    Undo.RecordObject(canvas, "Fix Canvas");
                    canvas.renderMode = RenderMode.ScreenSpaceCamera;
                    canvas.worldCamera = cam;
                    canvas.planeDistance = 1f;  // 在 Camera 前 1 單位
                    canvas.sortingOrder = 100;  // 確保比 3D 晚 render
                    Debug.Log($"[ResizeMao] ✓ Canvas '{canvas.name}' 改成 Screen Space - Camera");
                }
            }

            // 4. 修 CubismRenderController SortingMode
            // 2D 模型沒 Z 深度差，用 BackToFrontOrder（按 cdi3.json 宣告順序）
            // 最穩定，避免 Play 模式下部位 render order 跑掉
            var renderController = mao.GetComponent("Live2D.Cubism.Rendering.CubismRenderController");
            if (renderController != null)
            {
                var ctrlType = renderController.GetType();
                var sortingModeProp = ctrlType.GetProperty("SortingMode");
                if (sortingModeProp != null)
                {
                    var enumType = sortingModeProp.PropertyType;
                    var backToFrontOrder = System.Enum.Parse(enumType, "BackToFrontOrder");
                    Undo.RecordObject(renderController, "Set CubismSortingMode");
                    sortingModeProp.SetValue(renderController, backToFrontOrder);
                    Debug.Log("[ResizeMao] ✓ CubismRenderController.SortingMode = BackToFrontOrder（按宣告順序，避免 Play 模式部位順序跑掉）");
                }
                else
                {
                    Debug.LogWarning("[ResizeMao] ⚠ 找不到 SortingMode 屬性");
                }
            }
            else
            {
                Debug.LogWarning("[ResizeMao] ⚠ Mao 上找不到 CubismRenderController");
            }

            EditorSceneManager.MarkSceneDirty(mao.scene);
            Debug.Log("[ResizeMao] ✓ 場景已 dirty，記得存檔 Ctrl+S");
        }
    }
}
#endif
