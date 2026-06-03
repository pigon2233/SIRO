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

## Phase 7：中文字型（**不要**踩 Variable Font）

打中文進去 ResponseText 一直變 □ 方框 — Noto Sans TC 沒進去。流程踩雷如下：

### 雷 1：Google Fonts 預設給的是 Variable Font，跟 Unity TMP 不相容

下載 `Noto_Sans_TC.zip` 解開有兩個資料夾：
- `NotoSansTC-VariableFont_wght.ttf` ← Variable Font，Unity FontEngine 對它的 axis 有 bug，Dynamic Atlas 抓不到 glyph
- `static/NotoSansTC-Regular.ttf` ← ★ **要用這個**

### 雷 2：Atlas Population Mode 預設可能是 Static

右鍵 Create → TextMeshPro → Font Asset 在某些 TMP 版本預設是 **Static**，不是 Dynamic。要手動切：
- Inspector → Atlas Population Mode → **Dynamic**
- Source Font File：保持指向 .ttf
- Atlas Width/Height：1024 × 1024（起手）
- Multi Atlas Textures：勾起來
- Source 字型超過 4K-28K glyph 時，**不要**用 Font Asset Creator 預烤 Static atlas（會吐「Callback unregistration failed」誤導訊息，真正原因是 atlas 塞不下）

### 雷 3：TMP Settings Default Font 沒換

`Assets/TextMesh Pro/Resources/TMP Settings.asset` → Default Font Asset 拖 NotoSansTC SDF 進去。**也記得**把它加到 LiberationSans SDF 的 Fallback Font Assets（救已存在的 TMP 元件）。

### 工具

`Tools/SIRO/Setup Chinese Font`（`SetupChineseFont.cs`）自動掃 `Assets/Fonts/`、建 TMP Asset、套到所有 TMP 元件。

---

## Phase 8：情緒系統 — 8 個坑連環踩

整套 bridge ↔ Unity 情緒鏈路在「打『難過』Mao 切到 exp_04（興奮）」這條 bug 上裂開，回頭追了 8 層。

### 坑 1：LLM 永遠回 neutral（system_prompt 沒進 LLM）

`hermes_client.py` 原本用 `env["HERMES_SYSTEM_PROMPT"]` 注 system prompt — **Hermes 根本不認識這個 env var**。結果 LLM 看不到「請輸出 `[emotion:xxx]` tag」規則，emotion_parser fallback 永遠走 neutral。

**修法**：把 system_prompt 直接拼到 message 前面：
```python
full_prompt = f"{system_prompt}\n\n---\n\n{message}"
cmd = [hermes, "-z", full_prompt]
```

LLM 100% 看得到，emotion_parser regex 抓 tag 不在乎位置。

### 坑 2：Live2DModelController 找不到 expression

對照 emotion_mapping.json 用 `exp_06` 跟 Cubism asset `.name = "exp_06.exp3"` 不 match（Cubism importer 沒去 `.exp3` 後綴）。

**修法**：normalize 比對兩邊都去 `.exp3` 後綴 + 轉小寫。並在找不到時 log 列出實際 expression 名字清單，下次 debug 一眼看出 mapping 哪裡爛。

### 坑 3：場景 / prefab serialize 著舊預設值

改 `EmotionDisplay.cs` 的 public field 預設值**對已存在 instance 完全沒用**。場景或 prefab 已 serialize 的值會 win。

具體：Mao.prefab 裡 EmotionDisplay component 序列化了 `expressionSad: exp_04`，所以 LLM 回 sad → 切到 exp_04，跟 cs 預設值無關。

**修法**：要直接改 .prefab 或 .scene 的 propertyPath override，或在 Unity Inspector 手動 reset。

### 坑 4：Mao.prefab 有 3 份重複 EmotionDisplay + 3 份 Live2DModelController

SETUP 過程不小心累積（AddCubismComponents 工具跑了多次）。只有第一份 subscribe bridge event 切表情，其他兩份背景跑、互相干擾。

**修法**：grep `expressionSad: exp_04` replace_all 一次改 3 份。長期應該手動清掉 prefab 重複 component。

### 坑 5：「難過」LLM 判 excited（小模型不穩）

llama3.2:3b 對中文情緒判斷不可靠。明明說「難過」回 `[emotion:excited]`。

**修法**：emotion_parser 加 `STRONG_USER_SIGNALS` 字典，user_input 明確情緒詞（難過/傷心/沮喪/哭/...）→ 直接 override 弱 LLM 的標籤。

```python
if user_input:
    strong = self._strong_user_signal(user_input)
    if strong is not None:
        return clean_text, strong, intensity  # override LLM
```

刻意**不把 happy 放進 STRONG_USER_SIGNALS** — 招呼語太多元、易誤判，留給 LLM 自己決定。

### 坑 6：emoji 顯示成 □

LLM 偶爾吐 🐱 🎉，Noto Sans TC 沒含 emoji glyph → 變方框。雙層解：
- **Prompt 層**：明確規則「不要使用 emoji，情緒交給 Live2D 臉部表現」
- **Parser 層**：`_clean_for_display()` regex 過濾 U+1F000-1FFFF / Misc Symbols / Dingbats / VS / ZWJ

### 坑 7：Mao exp_02/03「閉眼但眼球露出」

Cubism SDK 範例 Mao 的閉眼 deformation 不完整 — `ParamEyeLOpen=0` 關了眼皮 mesh，但眼球 sprite 還是露出來。試 `ParamEyeBallForm=1` 跟 `ParamEyeEffect=1` 都沒效。

**修法**：runtime hack — 切到 exp_02/03 時用 `MeshRenderer.enabled = false` 直接把眼球 mesh 藏掉。眼球的 Drawable array index 是 `[87, 92]`（用 `Tools/SIRO/Drawable Inspector` 找出來的，不是 ArtMesh 編號 250/255）。

```csharp
[Header("Eye-Hiding Hack")]
public string[] hideEyeOnExpressions = { "exp_02", "exp_03" };
public int[] eyeDrawableIndices = { 87, 92 };
// SetExpression 時：SetEyeRenderersVisible(!ShouldHideEyeFor(expressionId));
```

用 `MeshRenderer.enabled` 而非 `Drawable.Opacity` — Cubism LateUpdate 會 reset Opacity，但不會碰 Unity 原生的 enabled flag。

### 坑 8：ExpressionViewer 繞過 Live2DModelController

我寫的 `ExpressionViewer` 工具直接設 `CubismExpressionController.CurrentExpressionIndex = i`，**繞過** `Live2DModelController.SetExpression()`，hide-eye hack 不會跑。結果：透過 chat 切到 exp_02 後 hack 把 87/92 disable；用 Viewer 切回 exp_01，hack 沒重新觸發 enable → 看起來每個表情都閉眼。

**修法**：ExpressionViewer.Apply() 優先呼叫 `siroController.SetExpression(name)`，找不到才退回直接設 index。

---

## Phase 9：擴充到 9 種情緒（一對一 8 個 expression）

校準完 Mao 8 個 expression 真實外觀後，加 `joyful` (exp_02 哈哈大笑) 跟 `proud` (exp_03 驕傲) 兩個情緒，讓所有 8 個 expression 都有對應（happy 跟 neutral 共用 exp_01）。

要改 5 個檔案：
- `bridge/models.py` — `Emotion` enum 加 `JOYFUL`, `PROUD`
- `bridge/emotion_mapping.json` — `emotion_map` 加新 entry
- `bridge/prompts.py` — system prompt 可選情緒清單 + 範例對話
- `bridge/emotion_parser.py` — `EMOTION_KEYWORDS` + `STRONG_USER_SIGNALS` 加新關鍵字
- `SiroUnity/.../EmotionDisplay.cs` — 加 `expressionJoyful` / `expressionProud` 欄位 + switch case
- `SiroUnity/.../Mao.prefab` — 3 份 EmotionDisplay 都加序列化值

最終 9 → 8 mapping：

| 情緒 | Mao expression | 校準後外觀 |
|---|---|---|
| happy | exp_01 | 開心 |
| joyful | exp_02 | 快樂（哈哈大笑、眼球 hack 隱藏） |
| proud | exp_03 | 驕傲（眼球 hack 隱藏） |
| excited | exp_04 | 興奮 |
| sad | exp_05 | 難過 |
| thinking | exp_06 | 害羞（借用為思考） |
| surprised | exp_07 | 驚訝 |
| angry | exp_08 | 生氣 |
| neutral | exp_01 | 借用 happy（中性偏正面） |

---

## Phase 10：Editor 工具完整清單

| 工具 | 選單 | 用途 |
|------|------|------|
| `SIROUIBuilder` | `Tools/SIRO/Build Chat UI` | 一鍵建 Canvas + InputField + Button + Text |
| `CubismReimport` | `Tools/SIRO/Force Reimport Mao` | 強制觸發 CubismAssetProcessor |
| `MaoDiagnostic` | `Tools/SIRO/Diagnose Mao` | Mao 完整診斷報告 |
| `FixMaoMaterials` | `Tools/SIRO/Fix Mao Materials` | 修 262 個 ArtMesh 材質 |
| `AddCubismComponents` | `Tools/SIRO/Add Cubism Components` | Mao 加上 Live2DModelController + EmotionDisplay |
| `DisableMaoAnimator` | `Tools/SIRO/Disable Mao Animator` | 關掉 default Animator（避免擋住 expression） |
| `ResizeMao` | `Tools/SIRO/Setup Mao For Display` | Mao 位置 / scale / camera / canvas 排序 |
| `EnglishifyUI` | `Tools/SIRO/Englishify Chat UI` | UI 文字暫時換英文（中文沒裝好時） |
| `SetupChineseFont` | `Tools/SIRO/Setup Chinese Font` | 自動掃 Fonts/、建 TMP Asset、套到所有 TMP |
| **`ExpressionViewer`** | **`Tools/SIRO/Expression Viewer`** | **校準 Mao 8 個 expression 真實外觀** |
| **`DrawableInspector`** | **`Tools/SIRO/Drawable Inspector`** | **找眼球/特定部位 Drawable index 用** |

新加 5 個工具（粗體那些是 Phase 7-9 新加的）。

---

## 給未來的我們的建議

1. **不要懷疑自己** — 14 個 Unity commit 才看到 Mao 不是你笨，是 Cubism SDK 5-r.5 + Unity 6 真的整合差
2. **診斷 > 猜** — MaoDiagnostic 一跑就找到問題，瞎猜 3 小時找不到
3. **Editor 工具救我** — FixMaoMaterials 30 秒解決，否則要手動改 262 個 mesh
4. **Unity 視覺化是 polish** — 真正的 E2E（bridge ↔ hermes ↔ ollama）在 commit `8d4ce23` 就 100% 完成了
5. **下次考慮** Unity 2022 LTS — Cubism SDK 可能相容性更好（沒實測）
6. **Variable Font 是個坑** — 永遠用 static .ttf 版本給 Unity TMP，省下半小時 debug
7. **system_prompt inline 比注 env var 可靠** — Hermes CLI 設計、其他 LLM wrapper 也常常一樣
8. **prefab 序列化值 > .cs default** — 改 .cs default 對已存在 instance 沒用，直接編輯 .prefab YAML 才會生效
9. **找眼球用 Drawable Inspector 的 Isolate 按鈕** — 比 Hide 直觀（看到剩下什麼就是這個 mesh 的形狀）
10. **Cubism Drawable 屬性別動 (Opacity 等)** — runtime 想藏 mesh 用 Unity 原生 `MeshRenderer.enabled`，不會被 Cubism LateUpdate 蓋過

