// unity/Assets/Editor/MaoDiagnostic.cs
//
// Mao 模型診斷工具：找出為什麼看不見
//
// 用法：Tools → SIRO → Diagnose Mao
// 輸出每個 MeshFilter 的：
//   - 名稱、位置、scale
//   - Mesh 頂點數、bounds（是否合理）
//   - MeshRenderer 的 enabled 狀態、material
//   - 任何「找不到 mesh」、「scale 太小」等異常

#if UNITY_EDITOR
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Siro.EditorTools
{
    public static class MaoDiagnostic
    {
        [MenuItem("Tools/SIRO/Diagnose Mao")]
        public static void Diagnose()
        {
            var sb = new StringBuilder();
            sb.AppendLine("=== SIRO Mao 診斷 ===\n");

            // 找場景裡的 Mao（用名字找）
            GameObject mao = GameObject.Find("Mao");
            if (mao == null)
            {
                sb.AppendLine("❌ 找不到 GameObject 'Mao'。檢查 Hierarchy。");
                Debug.Log(sb.ToString());
                return;
            }

            sb.AppendLine($"✓ 找到 Mao: {mao.name}");
            sb.AppendLine($"  Position: {mao.transform.position}");
            sb.AppendLine($"  Scale:    {mao.transform.localScale}");
            sb.AppendLine($"  Children: {mao.transform.childCount}\n");

            // 找所有 MeshFilter
            var meshFilters = mao.GetComponentsInChildren<MeshFilter>(true);
            sb.AppendLine($"--- MeshFilters: {meshFilters.Length} 個 ---");

            int healthy = 0, noMesh = 0, tinyScale = 0, hiddenRenderer = 0;
            Vector3 minPos = Vector3.positiveInfinity;
            Vector3 maxPos = Vector3.negativeInfinity;

            foreach (var mf in meshFilters)
            {
                var go = mf.gameObject;
                var mesh = mf.sharedMesh;
                var rend = go.GetComponent<MeshRenderer>();

                bool noMeshHere = mesh == null;
                bool hidden = rend != null && !rend.enabled;
                Vector3 scale = go.transform.lossyScale;
                bool tiny = scale.x < 0.01f || scale.y < 0.01f || scale.z < 0.01f;

                if (noMeshHere) noMesh++;
                if (hidden) hiddenRenderer++;
                if (tiny) tinyScale++;
                if (!noMeshHere && !hidden && !tiny) healthy++;

                if (!noMeshHere)
                {
                    // MeshFilter 沒 bounds 屬性，要從 Renderer 拿 world-space bounds
                    var rendForBounds = go.GetComponent<Renderer>();
                    if (rendForBounds != null)
                    {
                        minPos = Vector3.Min(minPos, rendForBounds.bounds.min);
                        maxPos = Vector3.Max(maxPos, rendForBounds.bounds.max);
                    }
                }

                string status = "OK";
                if (noMeshHere) status = "❌ NO MESH";
                else if (hidden) status = "❌ RENDERER DISABLED";
                else if (tiny) status = "⚠️  TINY SCALE";

                sb.AppendLine($"  {go.name,-40} {status,-22} vertices={mesh?.vertexCount ?? 0}  scale={scale}");
                if (rend != null)
                {
                    var mat = rend.sharedMaterial;
                    string colorStr = "n/a";
                    if (mat != null)
                    {
                        // 不是每個 shader 都有 _Color，用 HasProperty 檢查
                        if (mat.HasProperty("_Color"))
                        {
                            try { colorStr = mat.color.ToString(); }
                            catch { colorStr = "(error reading)"; }
                        }
                        else
                        {
                            colorStr = "(no _Color)";
                        }
                    }
                    sb.AppendLine($"    Material: {(mat != null ? mat.name : "NULL")}, " +
                                  $"enabled={rend.enabled}, color={colorStr}");
                    if (mat != null && mat.HasProperty("_MainTex"))
                    {
                        var tex = mat.GetTexture("_MainTex");
                        sb.AppendLine($"    _MainTex: {(tex != null ? tex.name : "❌ NULL - 紋理沒綁")}");
                    }
                }
            }

            // 整體 bounds
            if (minPos != Vector3.positiveInfinity)
            {
                Vector3 size = maxPos - minPos;
                Vector3 center = (minPos + maxPos) / 2f;
                sb.AppendLine($"\n--- 整體 bounds ---");
                sb.AppendLine($"  Center: {center}");
                sb.AppendLine($"  Size:   {size}");
                if (size.magnitude < 0.1f) sb.AppendLine($"  ⚠️ Size < 0.1 — 模型超小");
                if (size.magnitude > 1000f) sb.AppendLine($"  ⚠️ Size > 1000 — 模型超大");
            }

            // 統計
            sb.AppendLine($"\n--- 統計 ---");
            sb.AppendLine($"  健康 mesh: {healthy}");
            sb.AppendLine($"  ❌ 沒 mesh: {noMesh}");
            sb.AppendLine($"  ❌ renderer 關掉: {hiddenRenderer}");
            sb.AppendLine($"  ⚠️  太小 scale: {tinyScale}");

            // Camera 距離
            Camera cam = Camera.main;
            if (cam != null && minPos != Vector3.positiveInfinity)
            {
                Vector3 center = (minPos + maxPos) / 2f;
                float dist = Vector3.Distance(cam.transform.position, center);
                sb.AppendLine($"\n--- Camera 距離 ---");
                sb.AppendLine($"  Camera pos: {cam.transform.position}");
                sb.AppendLine($"  Mao center: {center}");
                sb.AppendLine($"  Distance:   {dist:F2}");
                sb.AppendLine($"  Near clip:  {cam.nearClipPlane}");
                sb.AppendLine($"  Far clip:   {cam.farClipPlane}");
                if (dist < cam.nearClipPlane) sb.AppendLine($"  ❌ Mao 在 near clip 內（< {cam.nearClipPlane}）");
                if (dist > cam.farClipPlane) sb.AppendLine($"  ❌ Mao 在 far clip 外（> {cam.farClipPlane}）");
            }

            string result = sb.ToString();
            Debug.Log(result);
        }
    }
}
#endif
