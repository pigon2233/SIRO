# SIRO Unity Scripts

把這四個 .cs 檔放進 `Assets/Scripts/`：

1. **HermesBridgeClient.cs** — WebSocket client，連 bridge
2. **Live2DModelController.cs** — 控制 Cubism 模型的 expression/motion
3. **EmotionDisplay.cs** — 收到 bridge 訊息後切換表情
4. **ChatInputUI.cs** — 簡單的聊天 UI

## 依賴

- `com.unity.nuget.newtonsoft-json` (JSON 處理，manifest.json 已列)
- Cubism SDK for Unity（要自己從 Live2D 官網下載 .unitypackage 匯入）
- `com.unity.ugui` + TextMeshPro（標準 Unity 套件）

## 不在這裡

- `Assets/Models/`：Hiyori 模型（從 Live2D 官網抓，不 commit）
- `Assets/Scenes/MainScene.unity`：場景要你在 Unity Editor 內手動建
- `ProjectSettings/`：Unity 自動產生

## 詳細設定

見 [unity/README.md](../../README.md)（即 unity/ 資料夾的 README.md）。
