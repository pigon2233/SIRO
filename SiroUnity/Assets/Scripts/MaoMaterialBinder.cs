// unity/Assets/Scripts/MaoMaterialBinder.cs
//
// 在 Play mode 自動綁定 Mao 的 texture 到所有 ArtMesh 材質。
//
// 為什麼需要：
// FixMaoMaterials 用 new Material() 創 instanced 材質設 _MainTex。
// 但 instanced 材質是 runtime-only，Play 模式開始時 Unity 會 reset 材質
// 回 prefab 預設（SDK 的 UnlitBlendMode* source .mat，沒綁 texture）。
//
// 這個 MonoBehaviour 在 Awake 把 texture 綁到所有 ArtMesh 的 renderer，
// 確保 Edit mode + Play mode 都正常顯示。
//
// 用法：
//   1. 選 Mao GameObject（或任何子物件）
//   2. Add Component → Mao Material Binder
//   3. 設 Texture Field = Mao.2048/texture_00.png
//   4. Play
//

using UnityEngine;

namespace Siro
{
    public class MaoMaterialBinder : MonoBehaviour
    {
        [Tooltip("要綁的紋理（通常是 Mao.2048/texture_00.png）")]
        public Texture2D texture;

        [Tooltip("如果有 _Color 屬性，設成這個顏色（可選）")]
        public Color tint = Color.white;

        [Tooltip("設為 false 可關閉這個 binder（debug 用）")]
        public bool bindOnAwake = true;

        [Tooltip("也處理所有子物件（預設 true）")]
        public bool includeChildren = true;

        private void Awake()
        {
            if (bindOnAwake)
            {
                Bind();
            }
        }

        /// <summary>
        /// 公開方法：手動呼叫以重新綁定（用於在 ScriptableObject 設定改變等情況）。
        /// </summary>
        [ContextMenu("Bind Textures Now")]
        public void Bind()
        {
            if (texture == null)
            {
                Debug.LogWarning("[MaoMaterialBinder] texture 是 null，跳過綁定", this);
                return;
            }

            var renderers = includeChildren
                ? GetComponentsInChildren<MeshRenderer>(true)
                : GetComponents<MeshRenderer>();

            int bound = 0;
            foreach (var rend in renderers)
            {
                if (rend == null || rend.sharedMaterial == null) continue;

                var mat = rend.material; // 用 material（不是 sharedMaterial）拿 runtime instance
                if (mat == null) continue;

                // 設 _MainTex
                if (mat.HasProperty("_MainTex"))
                {
                    mat.SetTexture("_MainTex", texture);
                }
                else if (mat.HasProperty("cubism_MainTexture"))
                {
                    mat.SetTexture("cubism_MainTexture", texture);
                }

                // 設 _Color（如果 shader 有）
                if (mat.HasProperty("_Color"))
                {
                    mat.SetColor("_Color", tint);
                }

                bound++;
            }

            Debug.Log($"[MaoMaterialBinder] 綁定 {bound} 個 renderer", this);
        }
    }
}
