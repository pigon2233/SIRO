# Unity 設定踩雷紀錄

> 寫給未來的我們（或別人）— 把 SIRO 跑起來到「Mao 顯示 + 對話能切表情」中間踩到的所有雷。

## TL;DR

Cubism SDK 5-r.5 + Unity 6 LTS + URP 17 的整合**有** rough edges。我們寫了 4 個 Editor 工具幫忙踩過去，**沒這些工具根本看不到 Mao**：

- `SIROUIBuilder` — 一鍵建 UI
- `CubismReimport` — 強制觸發 Cubism importer
- `MaoDiagnostic` — 為什麼 Mao 看不見的診斷報告
- `FixMaoMaterials` — 把錯的 TransparentPicking 材質換成 UnlitBlendMode + 綁紋理

詳細在下面。

---

## 環境

| 元件 | 版本 |
|------|------|
| Unity | 6.3.11f1 (LTS) |
| Cubism SDK | 5-r.5 (從官網 .unitypackage) |
| URP | 17.0.3 (從 manifest 加) |
| Input System | 1.13.1 (從 manifest 加) |
| TextMeshPro | 內建 (UGUI 2.0.0) |
| 開發機 | ASUS ROG Strix G713QC, RTX 3050 4GB, Windows 11 |

---

## Phase 0：manifest.json 要加什麼

Cubism SDK 對 Unity 6 + URP 環境需要：
```json
{
  "com.unity.render-pipelines.universal": "17.0.3",
  "com.unity.inputsystem": "1.13.1"
}
```

沒 URP 會：`TextureHandle` not found（CubismRenderPassFeature 用到 Render Graph API）。
沒 Input System 會：Cubism samples 編譯失敗（CubismSampleController 用新 Input System）。

---

## Phase 1：Cubism 程式碼 API 在 SDK 5-r.5 改了

我們寫的 `Live2DModelController.cs` 原本用：

```csharp
// 舊 API（SDK 4.x）
for (int i = 0; i < expressions?.Count; i++) {
    if (expressions[i]?.name == expressionId) { ... }
}
```

SDK 5-r.5 `CubismExpressionList` 改用 array 結構：
```csharp
public class CubismExpressionList : ScriptableObject {
    public CubismExpressionData[] CubismExpressionObjects;
}
```

正確寫法：
```csharp
var expressions = _expressionController.ExpressionsList?.CubismExpressionObjects;
for (int i = 0; i < expressions.Length; i++) {
    if (expressions[i]?.name == expressionId) { ... }
}
```

而且 SDK 5-r.5 用 `for` loop 而不是 `foreach`（沒實作 IEnumerable）。

---

## Phase 2：UI 怎麼建（不要手動）

UI 結構複雜：
- Canvas 需要 CanvasScaler + GraphicRaycaster
- InputField 需要 Viewport + TextArea + Placeholder + Text 四個子物件
- Button 需要 Image + Text 標籤
- ChatInputUI 有 4 個引用要連

**不要手動建**。用 `Tools → SIRO → Build Chat UI`（`SIROUIBuilder.cs`）一鍵搞定。

它還會：
- 自動偵測 TMP Essential Resources，沒裝就跳出對話框問要不要自動 import
- 用 SerializedObject 設引用（可以 Undo）
- 預設 Layout：上 60% ResponseText、中 25% InputField、下 15% SendButton

---

## Phase 3：TMP 預設字型不支援中文

預設 `LiberationSans SDF` 只含英文字符。任何中文（U+4E00 以上）會被替換成 □（U+25A1）。

**v0 暫時解法**：UI 文字先用英文。
**正式解法**：下載 Noto Sans CJK（Google 開源），匯入 Unity，用 `Window → TextMeshPro → Font Asset Creator` 建立 TMP font asset，指派給所有 TMP 元件。

---

## Phase 4：Mao 為什麼看不到（最難搞的）

**症狀**：Scene view + Game view 都看不到 Mao，但 Mao GameObject 存在、Transform 正確、子物件有 mesh。

**真正原因**：Cubism importer 跑得不完整。**所有 262 個 ArtMesh 的 Renderer 都綁了 `TransparentPicking.mat`（alpha=0、沒紋理）而不是正確的 `UnlitBlendMode*.mat`**。

這是 SDK 5-r.5 + Unity 6.3.11f1 的**已知整合問題**。SDK 沒內建 "Refresh Materials" menu。

### 解法（已寫成工具 `FixMaoMaterials.cs`）

執行 `Tools → SIRO → Fix Mao Materials` 會：
1. 載入 `Mao.2048/texture_00.png` 紋理
2. 解析 `Mao.cdi3.json` 取得每個 ArtMesh 的 BlendMode
3. 為每個 ArtMesh：
   - 建立 instanced 材質（避免改 SDK 原始 .mat）
   - 設 `_MainTex` 為紋理 atlas
   - 設為 sharedMaterial
   - 把 disabled 的 renderer 啟用
4. 存 prefab（Mao.prefab）讓設定持久化

### 注意事項

- SDK 5-r.5 沒有 `UnlitBlendModeNormal.mat`，要用 `UnlitBlendModeNormalConjoint.mat`（標準 normal alpha blend）
- 其他 Normal 變體：`NormalAtop` (B over A)、`NormalDisjoint` (additive)、`NormalOver` (custom)

---

## Phase 5：Editor 工具清單

放在 `Assets/Editor/`：

| 工具 | 選單 | 用途 |
|------|------|------|
| `SIROUIBuilder` | `Tools/SIRO/Build Chat UI` | 一鍵建 Canvas + InputField + Button + Text + ChatInputUI |
| `CubismReimport` | `Tools/SIRO/Force Reimport Mao` / `Force Reimport All Cubism Models` | 強制觸發 CubismAssetProcessor |
| `MaoDiagnostic` | `Tools/SIRO/Diagnose Mao` | 跑 Mao 完整診斷報告（mesh、material、texture、bounds、camera 距離） |
| `FixMaoMaterials` | `Tools/SIRO/Fix Mao Materials` | 把 TransparentPicking 換成 UnlitBlendMode + 綁紋理 |

`Assets/Editor/` 是必要的位置（不然 Unity 報錯：Editor-only API 不能進 runtime build）。

---

## Phase 6：完整 E2E 流程（給未來的人）

### Step 0：前置
- 安裝 Unity 6 LTS (6000.x)
- Clone SIRO 專案
- 在 Unity Hub 開 `unity/` 資料夾
- Unity 接手會自動生成 ProjectSettings/、Library/、manifest.json

### Step 1：套 manifest
- 確認 `Packages/manifest.json` 有 URP 17.0.3 跟 Input System 1.13.1

### Step 2：裝 Cubism SDK
- 到 https://www.live2d.com/sdk/download/unity/
- 下載 `.unitypackage`、雙擊匯入
- 設 Scripting Define Symbols 加 `SIRO_HAS_CUBISM`

### Step 3：建場景
- File → New Scene → 存 `Assets/Scenes/MainScene.unity`
- 拖 `Assets/Live2D/Cubism/Samples/Models/Mao/Mao.prefab` 進場景
- （Hiyori 用戶自行下載完整版，預設範例用 Mao 因為最方便）

### Step 4：建 UI
- `Tools → SIRO → Build Chat UI`（會問要不要 import TMP Essentials，按 Import）

### Step 5：設 Components
- Hierarchy 拖 Mao → Add Component → `Live2DModelController`
- Mao → Add Component → `EmotionDisplay`
- 新建空 GameObject `Bridge` → Add Component → `HermesBridgeClient` (Siro namespace)
- EmotionDisplay.bridgeClient 拖 Bridge

### Step 6：修正 Mao 材質（最關鍵）
- `Tools → SIRO → Fix Mao Materials`
- Console 應該印「✓ 修正了 262 個 ArtMesh 材質」

### Step 7：Play
- 確認 bridge 跑著（背景 terminal）
- Unity Editor 按 Play
- 在 InputField 打訊息 → 按 Send
- 應該看到 Mao 切表情

---

## 給未來的我們的建議

1. **不要懷疑自己** — 14 個 Unity commit 才看到 Mao 不是你笨，是 Cubism SDK 5-r.5 + Unity 6 真的整合差
2. **診斷 > 猜** — MaoDiagnostic 一跑就找到問題，瞎猜 3 小時找不到
3. **Editor 工具救我** — FixMaoMaterials 30 秒解決，否則要手動改 262 個 mesh
4. **Unity 視覺化是 polish** — 真正的 E2E（bridge ↔ hermes ↔ ollama）在 commit `8d4ce23` 就 100% 完成了
5. **下次考慮** Unity 2022 LTS — Cubism SDK 可能相容性更好（沒實測）
