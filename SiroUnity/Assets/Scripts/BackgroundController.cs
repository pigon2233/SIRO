// unity/Assets/Scripts/BackgroundController.cs
//
// v1+ 多角色架構：背景動態切換
//
// 簡單實作：把背景圖（SpriteRenderer / UI Image / Mesh）放成 sibling 集合，
// SwitchTo(index) 啟用指定的、其他全關。
//
// 設計：背景跟 persona 沒強綁定（v0），可以獨立切換。
// 之後 v2+ 想綁可以擴充 — persona YAML 加 `background: "default_room"` 欄位。

using UnityEngine;

namespace Siro
{
    public class BackgroundController : MonoBehaviour
    {
        [Header("References")]
        [Tooltip("所有候選背景 GameObject，啟動時第一個被啟用")]
        public GameObject[] backgrounds;

        [Header("Debug")]
        public bool verboseLogging = true;

        private int _currentIndex = -1;

        private void Start()
        {
            if (backgrounds == null || backgrounds.Length == 0)
            {
                if (verboseLogging) Debug.LogWarning("[BackgroundController] 沒給任何 background");
                return;
            }

            SwitchTo(0);
        }

        /// <summary>
        /// 切到第 N 個背景（0-indexed）
        /// </summary>
        public void SwitchTo(int index)
        {
            if (backgrounds == null || index < 0 || index >= backgrounds.Length)
            {
                Debug.LogWarning($"[BackgroundController] index {index} 超出範圍");
                return;
            }

            for (int i = 0; i < backgrounds.Length; i++)
            {
                if (backgrounds[i] != null)
                {
                    backgrounds[i].SetActive(i == index);
                }
            }
            _currentIndex = index;
            if (verboseLogging) Debug.Log($"[BackgroundController] 切到背景 #{index}");
        }

        /// <summary>
        /// 拿當前背景的 index
        /// </summary>
        public int GetCurrentIndex() => _currentIndex;

        /// <summary>
        /// 切到下一個背景（loop）
        /// </summary>
        public void SwitchToNext()
        {
            if (backgrounds == null || backgrounds.Length == 0) return;
            int next = (_currentIndex + 1) % backgrounds.Length;
            SwitchTo(next);
        }
    }
}
