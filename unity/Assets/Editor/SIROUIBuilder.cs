// unity/Assets/Editor/SIROUIBuilder.cs
//
// SIRO UI Builder - 一鍵建立 SIRO 需要的 UI 元件
//
// 使用方法（Unity 內）：
//   1. 選單 → Tools → SIRO → Build Chat UI
//   2. 自動生成：
//      - Canvas (含 EventSystem)
//      - TMP_InputField
//      - Button (SendButton)
//      - TMP_Text (ResponseText)
//      - ChatInputUI Component，自動連接上面三個引用
//
// 怎麼裝這個檔：
//   - 必須放在 Assets/Editor/ 資料夾下（否則 Unity 編譯會報 Editor-only API 錯）
//   - 第一次放進去 Unity 會自動重新編譯
//   - 編譯完成後 Tools 選單就會出現 SIRO → Build Chat UI
//

#if UNITY_EDITOR
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System.IO;

namespace Siro.EditorTools
{
    public static class SIROUIBuilder
    {
        private const string MENU_PATH = "Tools/SIRO/Build Chat UI";

        [MenuItem(MENU_PATH)]
        public static void BuildChatUI()
        {
            // 0. 檢查 TMP Essential Resources 是否有裝
            // 沒裝的話 TMP 沒字型，UI 會 NullRef
            if (!HasTMPEssentialResources())
            {
                bool import = EditorUtility.DisplayDialog(
                    "TMP Essential Resources 沒裝",
                    "SIRO UI 需要 TextMeshPro Essential Resources（含預設字型）。\n\n" +
                    "是否現在自動 import？\n\n" +
                    "（會下載字型到 Assets/TextMesh Pro/）",
                    "Import",
                    "取消"
                );
                if (import)
                {
                    // 從 PackageCache 找 TMP Essential Resources
                    string packageCache = Path.Combine(Application.dataPath, "..", "Library", "PackageCache");
                    string[] dirs = System.IO.Directory.GetDirectories(
                        packageCache, "com.unity.ugui@*", System.IO.SearchOption.TopDirectoryOnly);
                    if (dirs.Length > 0)
                    {
                        string essentials = Path.Combine(
                            dirs[0], "Runtime", "TMP Essential Resources.unitypackage");
                        if (System.IO.File.Exists(essentials))
                        {
                            AssetDatabase.ImportPackage(essentials, false);
                            Debug.Log("[SIRO UI Builder] 已 import TMP Essential Resources");
                        }
                        else
                        {
                            Debug.LogError(
                                "[SIRO UI Builder] 找不到 TMP Essential Resources，" +
                                "請手動 Window > TextMeshPro > Import TMP Essential Resources");
                            return;
                        }
                    }
                    else
                    {
                        Debug.LogError(
                            "[SIRO UI Builder] 找不到 com.unity.ugui package cache");
                        return;
                    }
                }
                else
                {
                    Debug.LogWarning(
                        "[SIRO UI Builder] ⚠ 沒裝 TMP Essential Resources，" +
                        "建出來的 UI 會 NullRef");
                }
            }

            // 1. 找或建 Canvas
            Canvas canvas = GameObject.FindObjectOfType<Canvas>();
            if (canvas == null)
            {
                // 不用建構子加 component（曾發生 CanvasScaler 沒加上的 bug）
                // 一個一個 AddComponent 最可靠
                GameObject canvasGO = new GameObject("Canvas");
                canvas = canvasGO.AddComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                CanvasScaler scaler = canvasGO.AddComponent<CanvasScaler>();
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                scaler.referenceResolution = new Vector2(1920, 1080);
                scaler.matchWidthOrHeight = 0.5f;
                canvasGO.AddComponent<GraphicRaycaster>();
                Undo.RegisterCreatedObjectUndo(canvasGO, "Create SIRO Canvas");
            }

            // 2. 找或建 EventSystem
            if (GameObject.FindObjectOfType<EventSystem>() == null)
            {
                GameObject eventSystemGO = new GameObject("EventSystem",
                    typeof(EventSystem),
                    typeof(StandaloneInputModule));
                Undo.RegisterCreatedObjectUndo(eventSystemGO, "Create EventSystem");
            }

            // 3. 建 InputField
            GameObject inputGO = FindOrCreateChild(canvas.transform, "ChatInputField");
            TMP_InputField inputField = EnsureTMPInputField(inputGO);

            // 4. 建 SendButton
            GameObject buttonGO = FindOrCreateChild(canvas.transform, "SendButton");
            Button button = EnsureButton(buttonGO);

            // 5. 建 ResponseText
            GameObject textGO = FindOrCreateChild(canvas.transform, "ResponseText");
            TMP_Text responseText = EnsureTMPText(textGO, 24);

            // 6. 自動排版（簡單垂直堆疊）
            SimpleVerticalLayout(new[] { textGO, inputGO, buttonGO });

            // 7. 加 ChatInputUI 並連接引用
            ChatInputUI chatUI = canvas.GetComponent<ChatInputUI>();
            if (chatUI == null)
            {
                chatUI = canvas.gameObject.AddComponent<ChatInputUI>();
            }

            // 用 SerializedObject 設定（讓 Undo 能運作）
            SerializedObject so = new SerializedObject(chatUI);
            so.FindProperty("tmpInputField").objectReferenceValue = inputField;
            so.FindProperty("sendButton").objectReferenceValue = button;
            so.FindProperty("tmpResponseText").objectReferenceValue = responseText;
            so.ApplyModifiedProperties();

            // 8. 標記場景為 dirty，提示存檔
            EditorSceneManager.MarkSceneDirty(canvas.gameObject.scene);

            Debug.Log("[SIRO UI Builder] ✓ UI 建好了！");
            Debug.Log($"  - Canvas: {canvas.gameObject.name}");
            Debug.Log($"  - InputField: {inputField.gameObject.name}");
            Debug.Log($"  - SendButton: {button.gameObject.name}");
            Debug.Log($"  - ResponseText: {responseText.gameObject.name}");
            Debug.Log($"  - ChatInputUI: 已加到 Canvas 上");

            // 9. 選中 Canvas 讓使用者看一下結果
            Selection.activeGameObject = canvas.gameObject;
            EditorGUIUtility.PingObject(canvas.gameObject);
        }

        // ==================== Helper ====================

        private static bool HasTMPEssentialResources()
        {
            // 看 Assets/TextMesh Pro/ 資料夾存不存在（TMP Essential Resources 解壓後會建這個）
            return AssetDatabase.IsValidFolder("Assets/TextMesh Pro");
        }

        private static GameObject FindOrCreateChild(Transform parent, string name)
        {
            // 先找有沒有同名的
            Transform existing = parent.Find(name);
            if (existing != null)
            {
                return existing.gameObject;
            }

            // 沒有就建
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            Undo.RegisterCreatedObjectUndo(go, $"Create {name}");
            return go;
        }

        private static TMP_InputField EnsureTMPInputField(GameObject go)
        {
            // 先看有沒有現成的
            var input = go.GetComponent<TMP_InputField>();
            if (input != null) return input;

            // 沒有就重建（一次建齊所有需要的 components）
            var image = go.AddComponent<Image>();
            image.color = new Color(0.1f, 0.1f, 0.1f, 0.8f);

            // 預設 text area (Viewport + Text Area)
            GameObject textArea = new GameObject("Text Area",
                typeof(RectTransform),
                typeof(RectMask2D));
            textArea.transform.SetParent(go.transform, false);

            GameObject placeholder = new GameObject("Placeholder",
                typeof(RectTransform));
            placeholder.transform.SetParent(textArea.transform, false);
            var phText = placeholder.AddComponent<TextMeshProUGUI>();
            phText.text = "輸入訊息...";
            phText.color = new Color(1, 1, 1, 0.5f);
            phText.fontSize = 24;

            GameObject inputText = new GameObject("Text",
                typeof(RectTransform));
            inputText.transform.SetParent(textArea.transform, false);
            var inText = inputText.AddComponent<TextMeshProUGUI>();
            inText.text = "";
            inText.color = Color.white;
            inText.fontSize = 24;

            // RectTransform 設定（撐滿父物件）
            StretchToParent(go.GetComponent<RectTransform>());
            StretchToParent(textArea.GetComponent<RectTransform>());
            StretchToParent(placeholder.GetComponent<RectTransform>());
            StretchToParent(inputText.GetComponent<RectTransform>());

            input = go.AddComponent<TMP_InputField>();
            input.textViewport = textArea.GetComponent<RectTransform>();
            input.textComponent = inText;
            input.placeholder = phText;

            return input;
        }

        private static Button EnsureButton(GameObject go)
        {
            var button = go.GetComponent<Button>();
            if (button != null) return button;

            var image = go.AddComponent<Image>();
            image.color = new Color(0.2f, 0.4f, 0.8f, 1f);

            GameObject labelGO = new GameObject("Text",
                typeof(RectTransform));
            labelGO.transform.SetParent(go.transform, false);
            var label = labelGO.AddComponent<TextMeshProUGUI>();
            label.text = "Send";
            label.color = Color.white;
            label.fontSize = 24;
            label.alignment = TextAlignmentOptions.Center;

            StretchToParent(go.GetComponent<RectTransform>());
            StretchToParent(labelGO.GetComponent<RectTransform>());

            // BUG 修正：之前寫 go.GetComponent<Button>() 但從來沒加過 Button，永遠回 null
            return go.AddComponent<Button>();
        }

        private static TMP_Text EnsureTMPText(GameObject go, int fontSize)
        {
            var text = go.GetComponent<TMP_Text>();
            if (text != null) return text;

            text = go.AddComponent<TextMeshProUGUI>();
            text.text = "（等待連線...）";
            text.color = Color.white;
            text.fontSize = fontSize;
            text.alignment = TextAlignmentOptions.TopLeft;
            return text;
        }

        private static void StretchToParent(RectTransform rt)
        {
            rt.anchorMin = new Vector2(0, 0);
            rt.anchorMax = new Vector2(1, 1);
            rt.offsetMin = new Vector2(10, 10);
            rt.offsetMax = new Vector2(-10, -10);
            rt.localScale = Vector3.one;
        }

        private static void SimpleVerticalLayout(GameObject[] items)
        {
            // 簡單垂直堆疊：ResponseText 佔上方 60%，InputField 中間 25%，Button 下方 15%
            float[] heights = { 0.6f, 0.25f, 0.15f };
            float yMax = 1f;
            for (int i = 0; i < items.Length; i++)
            {
                var rt = items[i].GetComponent<RectTransform>();
                if (rt == null) continue;
                rt.anchorMin = new Vector2(0, yMax - heights[i]);
                rt.anchorMax = new Vector2(1, yMax);
                rt.offsetMin = Vector2.zero;
                rt.offsetMax = Vector2.zero;
                yMax -= heights[i];
            }
        }
    }
}
#endif
