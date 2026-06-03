// unity/Assets/Editor/PersonaSceneSetup.cs
//
// Persona Manager 一鍵接線工具
//
// 使用方法（Unity 內）：
//   1. 開啟 MainScene
//   2. 選單 → Tools → SIRO → Setup Persona Manager
//   3. 自動接好：
//      - SIROPersonaRoot GameObject（含 PersonaManager + PersonaApiClient + PersonaSelectorUI）
//      - 場景右上角 Canvas（齒輪按鈕 + TMP_Dropdown 預設隱藏）
//      - 自動接到現有的 HermesBridgeClient + Live2DModelController（Mao）
//
// 「電腦滑鼠」UX：
//   - 預設 = 什麼都不顯示，Mao 直接是 SIRO
//   - 想換角色：點右上齒輪（顯示「⚙ SIRO」）→ dropdown 展開
//   - 選完 → dropdown 自動收合
//
// 怎麼裝這個檔：
//   - 必須放在 Assets/Editor/ 資料夾下（否則 Unity 編譯會報 Editor-only API 錯）
//   - 第一次放進去 Unity 會自動重新編譯
//   - 編譯完成後 Tools 選單就會出現 SIRO → Setup Persona Manager

#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using Siro;

namespace Siro.EditorTools
{
    public static class PersonaSceneSetup
    {
        private const string ROOT_GO_NAME = "SIROPersonaRoot";
        private const string CANVAS_GO_NAME = "PersonaUI";
        private const string SETTINGS_BTN_NAME = "PersonaSettingsButton";
        private const string DROPDOWN_NAME = "PersonaDropdown";

        [MenuItem("Tools/SIRO/Setup Persona Manager")]
        public static void Setup()
        {
            // 1. 找現有的 bridge / model / canvas
            var bridgeClient = Object.FindFirstObjectByType<HermesBridgeClient>();
            var modelController = Object.FindFirstObjectByType<Live2DModelController>();

            if (bridgeClient == null)
            {
                EditorUtility.DisplayDialog(
                    "Setup Persona Manager",
                    "找不到 HermesBridgeClient，請先確認場景內有接 bridge 的物件。",
                    "OK");
                return;
            }
            if (modelController == null)
            {
                EditorUtility.DisplayDialog(
                    "Setup Persona Manager",
                    "找不到 Live2DModelController，請先確認 Mao prefab 已 instantiate 到場景。",
                    "OK");
                return;
            }

            // 2. 建立/取得 SIROPersonaRoot
            var root = GameObject.Find(ROOT_GO_NAME);
            if (root == null)
            {
                root = new GameObject(ROOT_GO_NAME);
            }

            var apiClient = root.GetComponent<PersonaApiClient>();
            if (apiClient == null) apiClient = root.AddComponent<PersonaApiClient>();
            apiClient.bridgeBaseUrl = "http://127.0.0.1:8001";  // 跟 bridge 預設對齊

            var personaManager = root.GetComponent<PersonaManager>();
            if (personaManager == null) personaManager = root.AddComponent<PersonaManager>();
            personaManager.apiClient = apiClient;
            personaManager.bridgeClient = bridgeClient;
            personaManager.modelController = modelController;
            personaManager.defaultPersonaId = "siro-default";

            // 3. 建立 PersonaUI Canvas（含齒輪 + dropdown）
            var canvasGo = GameObject.Find(CANVAS_GO_NAME);
            if (canvasGo == null)
            {
                canvasGo = BuildPersonaUI();
            }

            var selectorUI = root.GetComponent<PersonaSelectorUI>();
            if (selectorUI == null) selectorUI = root.AddComponent<PersonaSelectorUI>();

            // 接 selectorUI 引用
            var dropdown = canvasGo.transform.Find(DROPDOWN_NAME)?.GetComponent<TMP_Dropdown>();
            var settingsBtn = canvasGo.transform.Find(SETTINGS_BTN_NAME)?.GetComponent<Button>();
            var settingsLabel = canvasGo.transform.Find(SETTINGS_BTN_NAME + "/Label")?.GetComponent<TMP_Text>();

            selectorUI.apiClient = apiClient;
            selectorUI.personaManager = personaManager;
            selectorUI.dropdown = dropdown;
            selectorUI.settingsToggleButton = settingsBtn;
            selectorUI.settingsButtonLabel = settingsLabel;
            selectorUI.hideDropdownByDefault = true;
            selectorUI.autoCollapseAfterSelect = true;

            // 4. 標記場景為髒、儲存
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
            EditorSceneManager.SaveOpenScenes();

            Debug.Log("[PersonaSceneSetup] ✓ 完成。SIROPersonaRoot 已建好，下次進 Play 模式就會自動套用 siro-default。");
            EditorUtility.DisplayDialog(
                "Setup Persona Manager",
                "✓ 完成！\n\n" +
                "下次進 Play 模式時：\n" +
                "1. 自動套用 siro-default（Mao 顯示 SIRO 表情）\n" +
                "2. 右上角看到小齒輪「⚙ SIRO」\n" +
                "3. 點齒輪 → dropdown 展開 → 選角色\n" +
                "4. 選完自動收合\n\n" +
                "想換預設角色：在 SIROPersonaRoot 改 defaultPersonaId。",
                "OK");
        }

        // ==================== UI 建構 ====================

        private static GameObject BuildPersonaUI()
        {
            // 找場景的 Canvas（ChatInputUI 用的那個）
            var existingCanvas = Object.FindFirstObjectByType<Canvas>();
            Canvas canvas;
            if (existingCanvas != null)
            {
                canvas = existingCanvas;
            }
            else
            {
                var canvasGo = new GameObject(CANVAS_GO_NAME, typeof(Canvas));
                canvas = canvasGo.GetComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                canvas.sortingOrder = 100;  // 蓋在 ChatInputUI 之上
                canvasGo.AddComponent<CanvasScaler>();
                canvasGo.AddComponent<GraphicRaycaster>();
            }

            // EventSystem（如果沒有就加）
            if (Object.FindFirstObjectByType<EventSystem>() == null)
            {
                var eventSystemGo = new GameObject("EventSystem", typeof(EventSystem));
                eventSystemGo.AddComponent<StandaloneInputModule>();
            }

            // 齒輪按鈕（右上角）
            var settingsGo = new GameObject(SETTINGS_BTN_NAME, typeof(RectTransform), typeof(Image), typeof(Button));
            settingsGo.transform.SetParent(canvas.transform, false);
            var settingsRect = settingsGo.GetComponent<RectTransform>();
            settingsRect.anchorMin = new Vector2(1, 1);
            settingsRect.anchorMax = new Vector2(1, 1);
            settingsRect.pivot = new Vector2(1, 1);
            settingsRect.anchoredPosition = new Vector2(-20, -20);  // 右上角內縮
            settingsRect.sizeDelta = new Vector2(140, 40);

            var settingsBtnImage = settingsGo.GetComponent<Image>();
            settingsBtnImage.color = new Color(0.2f, 0.2f, 0.2f, 0.7f);

            var settingsLabelGo = new GameObject("Label", typeof(RectTransform), typeof(TextMeshProUGUI));
            settingsLabelGo.transform.SetParent(settingsGo.transform, false);
            var labelRect = settingsLabelGo.GetComponent<RectTransform>();
            labelRect.anchorMin = Vector2.zero;
            labelRect.anchorMax = Vector2.one;
            labelRect.offsetMin = Vector2.zero;
            labelRect.offsetMax = Vector2.zero;
            var label = settingsLabelGo.GetComponent<TMP_Text>();
            label.text = "角色:...";
            label.alignment = TextAlignmentOptions.Center;
            label.fontSize = 16;
            label.color = Color.white;

            // Dropdown（預設隱藏）
            var dropdownGo = new GameObject(DROPDOWN_NAME, typeof(RectTransform), typeof(Image), typeof(TMP_Dropdown));
            dropdownGo.transform.SetParent(canvas.transform, false);
            var dropdownRect = dropdownGo.GetComponent<RectTransform>();
            dropdownRect.anchorMin = new Vector2(1, 1);
            dropdownRect.anchorMax = new Vector2(1, 1);
            dropdownRect.pivot = new Vector2(1, 1);
            dropdownRect.anchoredPosition = new Vector2(-20, -70);  // 齒輪下方
            dropdownRect.sizeDelta = new Vector2(200, 50);
            dropdownGo.GetComponent<Image>().color = new Color(0.2f, 0.2f, 0.2f, 0.9f);

            // TMP_Dropdown 預設組件會要求一個 template，這裡先給 placeholder
            var dropdown = dropdownGo.GetComponent<TMP_Dropdown>();
            // 簡化：runtime 時 dropdown 會自動加 template 跟 caption，這裡先不管
            // Template 設定可由 PersonaSelectorUI 自動處理

            dropdownGo.SetActive(false);  // 預設隱藏

            return canvas.gameObject;
        }

        // ==================== 移除 ====================

        [MenuItem("Tools/SIRO/Remove Persona Manager")]
        public static void Remove()
        {
            var root = GameObject.Find(ROOT_GO_NAME);
            var canvas = GameObject.Find(CANVAS_GO_NAME);
            if (root != null) Object.DestroyImmediate(root);
            // 注意：Canvas 物件可能被其他 UI 共用，這裡只刪我們加的 dropdown/button
            if (canvas != null)
            {
                var dropdown = canvas.transform.Find(DROPDOWN_NAME);
                var btn = canvas.transform.Find(SETTINGS_BTN_NAME);
                if (dropdown != null) Object.DestroyImmediate(dropdown.gameObject);
                if (btn != null) Object.DestroyImmediate(btn.gameObject);
            }
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
            EditorSceneManager.SaveOpenScenes();
            Debug.Log("[PersonaSceneSetup] 已移除 persona UI");
        }
    }
}
#endif
