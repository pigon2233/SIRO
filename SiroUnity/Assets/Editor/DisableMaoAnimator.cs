// unity/Assets/Editor/DisableMaoAnimator.cs
//
// 禁用 Mao 的 Animator 讓 Play 模式靜態（解決 render order 不穩問題）
//
// 為什麼需要：Mao 的 Animator 跑 Cubism motion（呼吸、眨眼、idle），
// 這會在 Play 模式動態改變 parts 的 z-order，導致 render order 跑掉。
// v0 測試階段先禁用，之後真的要做 idle motion 再開。
//
// 用法：Tools → SIRO → Disable Mao Animator

#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace Siro.EditorTools
{
    public static class DisableMaoAnimator
    {
        [MenuItem("Tools/SIRO/Disable Mao Animator")]
        public static void Disable()
        {
            var mao = GameObject.Find("Mao");
            if (mao == null)
            {
                Debug.LogError("[DisableMaoAnimator] ❌ 找不到 Mao");
                return;
            }

            // 找所有 Animator（含子物件）
            var animators = mao.GetComponentsInChildren<Animator>(true);
            int disabled = 0;
            foreach (var anim in animators)
            {
                Undo.RecordObject(anim, "Disable Animator");
                anim.enabled = false;
                anim.runtimeAnimatorController = null;  // 拿掉 controller 引用
                disabled++;
                Debug.Log($"[DisableMaoAnimator] ✓ 禁用 Animator: {anim.gameObject.name}");
            }

            // 也禁用 CubismMotionController（SDK 內建的 motion 系統）
            System.Type motionControllerType = null;
            foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                motionControllerType = asm.GetType("Live2D.Cubism.Framework.Motion.CubismMotionController");
                if (motionControllerType != null) break;
            }
            if (motionControllerType != null)
            {
                var motions = mao.GetComponentsInChildren(motionControllerType, true);
                foreach (var m in motions)
                {
                    var asBehaviour = m as Behaviour;
                    if (asBehaviour != null)
                    {
                        Undo.RecordObject(asBehaviour, "Disable MotionController");
                        asBehaviour.enabled = false;
                        disabled++;
                        Debug.Log($"[DisableMaoAnimator] ✓ 禁用 CubismMotionController: {(asBehaviour as MonoBehaviour).gameObject.name}");
                    }
                }
            }

            // 存 prefab 讓設定持久
            string prefabPath = "Assets/Live2D/Cubism/Samples/Models/Mao/Mao.prefab";
            PrefabUtility.SaveAsPrefabAsset(mao, prefabPath);
            EditorSceneManager.MarkSceneDirty(mao.scene);

            Debug.Log($"[DisableMaoAnimator] ✓ 共禁用 {disabled} 個元件，prefab 已存");
        }
    }
}
#endif
