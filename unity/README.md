# unity/ - SIRO Live2D 客戶端

> Unity 6 LTS (6000.3.11f1) + Cubism SDK 的 Live2D 客戶端。
> 對應計畫書的 [Phase 1: 核心大腦](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-1-核心大腦-python)。

---

## 當前狀態

**Unity 6 LTS 已接手這個資料夾**（已驗證 2026-06-02）。

- ✅ `ProjectSettings/` 已由 Unity 自動生成
- ✅ `Packages/manifest.json` 是 Unity 標準範本
- ✅ `Library/`、`Logs/`、`Temp/`、`UserSettings/` 自動產生
- ✅ Scripts 都有 `.meta` 檔
- ⏸️ 還缺：Cubism SDK 套件 + Hiyori Live2D 模型 + 場景 + Animator 設定

---

## 直接打開

1. 開 **Unity Hub**
2. **Add** → 選擇 `c:\coconut chennel\SIRO\unity`
3. 選 **Unity 6 LTS (6000.3.11f1)** 開啟
4. 第一次開會跑 import（可能 1-3 分鐘）

> 如果 Unity Hub 顯示「不是有效的 Unity 專案」，檢查 `unity/ProjectSettings/ProjectVersion.txt` 是不是存在。

---

## 還要手動做的事

下面這些**不能**用 CLI 自動化，必須在 Unity Editor 內做：

### 1. 安裝 Cubism SDK for Unity

1. 到 [Live2D Cubism SDK 下載頁](https://www.live2d.com/en/sdk/download/cubism-sdk-for-unity/)
2. 註冊/登入 Live2D 帳號
3. 下載最新版的 `CubismSdkForUnity-*.unitypackage`
4. 雙擊 .unitypackage → Import All

### 2. 下載 Hiyori 模型

從 [Live2D 官方範例下載](https://www.live2d.com/en/download/sample-data/) 抓 Hiyori，
解壓後整包丟進 `unity/Assets/Models/Hiyori/`。

### 3. 建立 MainScene

1. `File > New Scene` → 存成 `Assets/Scenes/MainScene.unity`
2. 把 Hiyori 拖進場景
3. 建立 UI Canvas：
   - `GameObject > UI > Canvas`
   - 加 `InputField`（或 `TMP_InputField`）
   - 加 `Button`（命名 `SendButton`）
   - 加 `Text`（或 `TMP_Text`，命名 `ResponseText`）
4. 建立空 GameObject 命名 `Bridge`：
   - Add Component → `HermesBridgeClient` (Siro namespace)
5. 設定 Inspector：
   - `Bridge > HermesBridgeClient`：`serverUrl` = `ws://127.0.0.1:8001/ws`
   - `Hiyori` GameObject → Add Component → `Live2DModelController`
   - `Hiyori` GameObject → Add Component → `EmotionDisplay`，把 `Bridge` 拖到 `bridgeClient` 欄位
   - `Canvas > ChatInputUI` (Add Component)，把 UI 元素拖進欄位
6. 存場景

### 4. 驗證

1. 確認 `bridge/main.py` 正在跑
2. Unity Editor 按 **Play**
3. 在 InputField 輸入文字 → 按 Send
4. 預期：ResponseText 顯示 AI 回應 + Hiyori 切換表情

---

## 檔案結構

```
unity/
├── Assets/
│   ├── Models/                # Hiyori 模型（手動下載，不 commit）
│   ├── Scenes/                # Unity 場景
│   └── Scripts/               # 我們寫的 C# 腳本
│       ├── HermesBridgeClient.cs   # WebSocket client
│       ├── Live2DModelController.cs # Cubism 模型控制
│       ├── EmotionDisplay.cs        # 情緒 → 表情
│       └── ChatInputUI.cs           # 文字輸入 UI
├── Packages/
│   └── manifest.json          # Unity 套件清單（已由 Unity 自動填好）
├── ProjectSettings/           # Unity 專案設定（已由 Unity 自動生成）
├── README.md                  # 本檔
└── (.gitignore 涵蓋的)        # 不 commit：
    ├── Library/               #   - build cache
    ├── Logs/                  #   - log files
    ├── Temp/                  #   - temp files
    └── UserSettings/          #   - 個人設定
```

---

## C# 腳本說明

| 腳本 | 職責 |
|------|------|
| `HermesBridgeClient.cs` | WebSocket client，連 bridge，**含自動重連（指數 backoff）** |
| `Live2DModelController.cs` | 載入 Cubism 模型並提供切換 expression 的 API |
| `EmotionDisplay.cs` | 收到 bridge 訊息後呼叫 Live2DModelController |
| `ChatInputUI.cs` | UI 邏輯，InputField + 按鈕 + 顯示回應 |

## 已知問題

- v0 沒有自動重連 WebSocket 失敗時的重試 — **已修**（HermesBridgeClient 內建指數 backoff）
- v0 沒有 Loading 狀態視覺 — Hermes 回應要 5-30 秒，UI 看起來像當掉
- 表情切換是「瞬間切」，沒有過渡動畫 — 之後用 Cubism expression controller 的 Blend 模式

## 不在 v0 範圍

- 語音輸入（microphone）
- 語音輸出（TTS）
- 人臉追蹤、眼神追隨
- 口型動畫
- 多角色 / 換裝
