// unity/Assets/Scripts/PersonaSelectorUI.cs
//
// v1+ 多角色架構：UI 端的 persona 切換 dropdown
//
// 使用：掛在一個有空 TMP_Dropdown 的 GameObject 上，Inspector 拖進去。
// 啟動時拉 persona 清單填選項，選某個 persona 就呼叫 PersonaManager.ApplyPersona。

using System.Collections.Generic;
using TMPro;
using UnityEngine;

namespace Siro
{
    public class PersonaSelectorUI : MonoBehaviour
    {
        [Header("References")]
        public PersonaApiClient apiClient;
        public PersonaManager personaManager;
        public TMP_Dropdown dropdown;

        [Header("UI")]
        [Tooltip("dropdown 沒拉到清單前顯示的預設文字")]
        public string placeholderText = "（載入中...）";

        [Header("Debug")]
        public bool verboseLogging = true;

        private List<PersonaSummary> _personas = new List<PersonaSummary>();

        private void Start()
        {
            if (dropdown == null)
            {
                Debug.LogError("[PersonaSelectorUI] 沒有指派 TMP_Dropdown");
                return;
            }

            dropdown.ClearOptions();
            dropdown.AddOptions(new List<string> { placeholderText });
            dropdown.interactable = false;

            if (apiClient == null)
            {
                Debug.LogError("[PersonaSelectorUI] 沒有指派 apiClient");
                return;
            }

            // 訂閱 persona 切換事件，更新 dropdown 顯示
            if (personaManager != null)
            {
                personaManager.OnPersonaChanged += HandlePersonaChanged;
            }

            // fetch 清單
            apiClient.FetchPersonaList(
                onSuccess: (resp) =>
                {
                    if (resp?.personas == null || resp.personas.Length == 0)
                    {
                        Debug.LogWarning("[PersonaSelectorUI] bridge 沒回任何 persona");
                        return;
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
            if (dropdown != null)
            {
                dropdown.onValueChanged.RemoveListener(OnDropdownValueChanged);
            }
        }

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
        }

        private void HandlePersonaChanged(PersonaConfig config)
        {
            if (config == null) return;
            // 同步 dropdown 顯示（API 切換時 dropdown 也要跟上）
            for (int i = 0; i < _personas.Count; i++)
            {
                if (_personas[i].id == config.id)
                {
                    dropdown.SetValueWithoutNotify(i);
                    return;
                }
            }
        }
    }
}
