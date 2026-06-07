// unity/Assets/Editor/AutoSetupMaoMotionClips.cs
//
// 自動填 Mao GameObject 的 Live2DModelController.motionClips 欄位
// 給 LLM play_motion tool 用、避免手動拖 14 個欄位（7 name + 7 clip）
//
// 用法：
//   1. 場景或 prefab 編輯模式下選 Mao（或不選、會自動找）
//   2. Tools → SIRO → Auto Setup Mao Motion Clips
//   3. 完成、Inspector 會看到 7 筆 motionClips 已填好
//
// 重跑冇問題：會重設 Size=7、Group Name 重對應。

#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using Siro;  // for Live2DModelController + NamedMotionClip

namespace Siro.EditorTools
{
    public static class AutoSetupMaoMotionClips
    {
        private const string MOTION_DIR = "Assets/Live2D/Cubism/Samples/Models/Mao/motions";

        /// <summary>
        /// 7 個 LLM play_motion tool 可觸發的 motion
        /// 注意：mtn_01 是 idle（Start 自動 loop）、不能被 tool 觸發、故意不放進來
        /// </summary>
        private static readonly (string groupName, string fileName)[] MOTIONS = {
            ("mtn_02",     "mtn_02.anim"),
            ("mtn_03",     "mtn_03.anim"),
            ("mtn_04",     "mtn_04.anim"),
            ("sample_01",  "sample_01.anim"),
            ("special_01", "special_01.anim"),
            ("special_02", "special_02.anim"),
            ("special_03", "special_03.anim"),
        };

        [MenuItem("Tools/SIRO/Auto Setup Mao Motion Clips")]
        public static void AutoSetup()
        {
            GameObject mao = FindMao();
            if (mao == null)
            {
                Debug.LogError(
                    "[AutoSetupMaoMotionClips] 找不到 Mao GameObject。"
                    + "請確認 Mao 在場景裡、或 prefab 存在於 "
                    + "Assets/Live2D/Cubism/Samples/Models/Mao/Mao.prefab"
                );
                return;
            }

            Live2DModelController controller = mao.GetComponent<Live2DModelController>();
            if (controller == null)
            {
                Debug.LogError(
                    "[AutoSetupMaoMotionClips] Mao 沒有 Live2DModelController component"
                );
                return;
            }

            // 用 SerializedObject 處理（reflection-safe、未來欄位改名會報錯）
            SerializedObject so = new SerializedObject(controller);
            SerializedProperty motionClipsProp = so.FindProperty("motionClips");
            if (motionClipsProp == null)
            {
                Debug.LogError(
                    "[AutoSetupMaoMotionClips] 找不到 motionClips 欄位。"
                    + "請確認 Live2DModelController 有宣告 motionClips + NamedMotionClip。"
                );
                return;
            }

            // 重設 Size = 7
            motionClipsProp.arraySize = MOTIONS.Length;

            int successCount = 0;
            int missingCount = 0;
            for (int i = 0; i < MOTIONS.Length; i++)
            {
                var (groupName, fileName) = MOTIONS[i];
                string assetPath = $"{MOTION_DIR}/{fileName}";

                AnimationClip clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(assetPath);
                if (clip == null)
                {
                    Debug.LogWarning(
                        $"[AutoSetupMaoMotionClips] 找不到 {assetPath}、"
                        + $"Element {i} ({groupName}) 留空"
                    );
                    missingCount++;
                    continue;
                }

                SerializedProperty element = motionClipsProp.GetArrayElementAtIndex(i);
                element.FindPropertyRelative("groupName").stringValue = groupName;
                element.FindPropertyRelative("clip").objectReferenceValue = clip;
                successCount++;
            }

            so.ApplyModifiedProperties();
            EditorUtility.SetDirty(controller);

            // 如果在 prefab 編輯模式、記得存
            if (PrefabUtility.IsPartOfPrefabAsset(mao))
            {
                string prefabPath = AssetDatabase.GetAssetPath(mao);
                PrefabUtility.SavePrefabAsset(mao);
                Debug.Log(
                    $"[AutoSetupMaoMotionClips] prefab 已存：{prefabPath}"
                );
            }

            Debug.Log(
                $"[AutoSetupMaoMotionClips] 完成！{successCount} 個 motion clips 設定、"
                + $"{missingCount} 個 .anim 找不到（請檢查 MOTION_DIR 路徑）"
            );
        }

        /// <summary>
        /// 找 Mao GameObject：selection → scene → prefab
        /// </summary>
        private static GameObject FindMao()
        {
            // 1. 從當前 selection（user 已經選 Mao 的話最快）
            if (Selection.activeGameObject != null
                && Selection.activeGameObject.name.Contains("Mao"))
            {
                return Selection.activeGameObject;
            }

            // 2. 從當前 scene
            GameObject inScene = GameObject.Find("Mao");
            if (inScene != null)
            {
                return inScene;
            }

            // 3. 從 Mao prefab（如果有 prefab 在 AssetDatabase）
            string[] guids = AssetDatabase.FindAssets("Mao t:Prefab");
            if (guids.Length > 0)
            {
                string path = AssetDatabase.GUIDToAssetPath(guids[0]);
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab != null)
                {
                    // Prefab 編輯模式要回 prefab root
                    if (PrefabUtility.IsPartOfPrefabAsset(prefab))
                    {
                        return prefab;
                    }
                }
            }

            return null;
        }
    }
}
#endif
