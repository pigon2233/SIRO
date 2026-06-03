// unity/Assets/Scripts/PersonaSelectorUI.cs
//
// v1+ 多角色切換 UI — 「電腦滑鼠」UX 設計
//
// 預設：dropdown 隱藏，畫面上只看到一個小齒輪按鈕
// 要切角色：點齒輪 → dropdown 展開 → 選 → dropdown 自動收合
//
// 沒有任何複雜的彈窗、沒有「永遠顯示在畫面」的多餘元件。
// 預設 = siro-default 直接在 Inspector 配好，使用者什麼都不用做就能用。
//
// 場景接線（透過 Editor/PersonaSceneSetup.cs 一鍵）：
// 1. 選 MainScene
// 2. 工具列 Tools → SIRO → Setup Persona Manager
// 3. 自動新增 SIROPersonaRoot GameObject + 所有必要 component + UI

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Siro
{
    public class PersonaSelectorUI : MonoBehaviour
    {
        [Header("References")]
        public PersonaApiClient apiClient;
        public PersonaManager personaManager;
        public TMP_Dropdown dropdown;
        public Button settingsToggleButton;  // 小齒輪，預設永遠顯示
        public TMP_Text settingsButtonLabel; // 顯示「角色：SIRO」之類

        [Header("UX")]
        [Tooltip("預設 dropdown 隱藏（只在點齒輪時展開）")]
        public bool hideDropdownByDefault = true;
        [Tooltip("選完 persona 後自動收合 dropdown")]
        public bool autoCollapseAfterSelect = true;
        [Tooltip("settings 按鈕文字格式，{0} = persona name")]
        public string settingsButtonFormat = "⚙ {0}";

        [Header("Debug")]
        public bool verboseLogging = true;

        private List<PersonaSummary> _personas = new List<PersonaSummary>();
        private bool _isDropdownVisible = false;

        private void Start()
        {
            if (dropdown == null)
            {
                Debug.LogError("[PersonaSelectorUI] 沒有指派 TMP_Dropdown");
                return;
            }

            // 預設隱藏 dropdown — 跟電腦滑鼠一樣不擋畫面
            if (hideDropdownByDefault)
            {
                dropdown.gameObject.SetActive(false);
                _isDropdownVisible = false;
            }

            // 預設 dropdown placeholder
            dropdown.ClearOptions();
            dropdown.AddOptions(new List<string> { "（載入中...）" });
            dropdown.interactable = false;

            if (apiClient == null)
            {
                Debug.LogError("[PersonaSelectorUI] 沒有指派 apiClient");
                return;
            }

            // 訂閱 persona 切換事件，自動更新 UI
            if (personaManager != null)
            {
                personaManager.OnPersonaChanged += HandlePersonaChanged;
            }

            // 齒輪按鈕 → toggle dropdown
            if (settingsToggleButton != null)
            {
                settingsToggleButton.onClick.AddListener(ToggleDropdown);
            }

            // fetch persona 清單
            apiClient.FetchPersonaList(
                onSuccess: (resp) =>
                {
                    if (resp?.personas == null || resp.personas.Length == 0)
                    {
                        Debug.LogWarning("[PersonaSelectorUI] bridge 沒回任何 persona，隱藏切換 UI");
                        // 沒任何 persona 可切 → 隱藏齒輪按鈕
                        if (settingsToggleButton != null) settingsToggleButton.gameObject.SetActive(false);
                        return;
                    }

                    if (resp.personas.Length == 1)
                    {
                        // 只有一個 persona → 隱藏齒輪（根本沒得切）
                        if (verboseLogging) Debug.Log($"[PersonaSelectorUI] 只有 1 個 persona，隱藏切換 UI");
                        if (settingsToggleButton != null) settingsToggleButton.gameObject.SetActive(false);
                    }

                    PopulateDropdown(resp.personas);
                },
                onError: (err) => Debug.LogError($"[PersonaSelectorUI] 拿 persona 清單失敗: {err}")
            );
        }

        private void OnDestroy()
        {
            if (personaManager != null)
            {
                personaManager.OnPersonaChanged -= HandlePersonaChanged;
            }
            if (settingsToggleButton != null)
            {
                settingsToggleButton.onClick.RemoveListener(ToggleDropdown);
            }
            if (dropdown != null)
            {
                dropdown.onValueChanged.RemoveListener(OnDropdownValueChanged);
            }
        }

        // ==================== 公開 API ====================

        /// <summary>
        /// 切換 dropdown 顯示狀態（給齒輪按鈕用）
        /// </summary>
        public void ToggleDropdown()
        {
            _isDropdownVisible = !_isDropdownVisible;
            if (dropdown != null)
            {
                dropdown.gameObject.SetActive(_isDropdownVisible);
            }
            if (verboseLogging) Debug.Log($"[PersonaSelectorUI] dropdown → {(_isDropdownVisible ? "顯示" : "隱藏")}");
        }

        // ==================== 內部 ====================

        private void PopulateDropdown(PersonaSummary[] personas)
        {
            _personas.Clear();
            _personas.AddRange(personas);

            var labels = new List<string>();
            int currentIndex = 0;
            for (int i = 0; i < personas.Length; i++)
            {
                labels.Add(personas[i].name);
                if (personaManager != null && personas[i].id == personaManager.GetCurrentPersona()?.id)
                {
                    currentIndex = i;
                }
            }

            dropdown.ClearOptions();
            dropdown.AddOptions(labels);
            dropdown.value = currentIndex;
            dropdown.interactable = true;
            dropdown.onValueChanged.AddListener(OnDropdownValueChanged);

            if (verboseLogging) Debug.Log($"[PersonaSelectorUI] 載入 {personas.Length} 個 persona，預設 index={currentIndex}");
        }

        private void OnDropdownValueChanged(int index)
        {
            if (index < 0 || index >= _personas.Count) return;
            var persona = _personas[index];
            if (verboseLogging) Debug.Log($"[PersonaSelectorUI] 選了: {persona.name} ({persona.id})");
            if (personaManager != null)
            {
                personaManager.ApplyPersona(persona.id);
            }

            // 選完自動收合（跟 Windows 控制台一樣，選了就關）
            if (autoCollapseAfterSelect)
            {
                ToggleDropdown();  // 切回隱藏
            }
        }

        private void HandlePersonaChanged(PersonaConfig config)
        {
            if (config == null) return;

            // 同步 dropdown 顯示
            if (dropdown != null)
            {
                for (int i = 0; i < _personas.Count; i++)
                {
                    if (_personas[i].id == config.id)
                    {
                        dropdown.SetValueWithoutNotify(i);
                        break;
                    }
                }
            }

            // 更新齒輪按鈕文字（顯示「⚙ SIRO」之類）
            if (settingsButtonLabel != null)
            {
                settingsButtonLabel.text = string.Format(settingsButtonFormat, config.name);
            }
        }
    }
}
