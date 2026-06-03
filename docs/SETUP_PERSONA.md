# SIRO Persona 切換 — 場景接線 SOP

> 適用版本：v0.2+（commit `d8c9851` 之後）

## 設計原則

**預設完全隱藏** — 使用者打開 Play 模式直接看到 SIRO，什麼都不用點。
**想切換才看到 UI** — 跟電腦滑鼠一樣，藏在「設定」裡。

```
進場景 → 自動套用 siro-default（Mao = SIRO）
        ↓
點右上角「角色:SIRO」按鈕
        ↓
展開 persona dropdown
        ↓
選新角色 → 自動收合 + 切換
```

## 一鍵接線（推薦）

### 步驟

1. **Unity Hub 開啟 `SiroUnity/` 專案**
2. **開啟 `Assets/Scenes/MainScene.unity`**
3. **確認 Mao + ChatInputUI + HermesBridgeClient 都已存在場景**
   - 沒有的話先跑 [SETUP_NOTES.md](SETUP_NOTES.md) 的一般 setup
4. **選單 → Tools → SIRO → Setup Persona Manager**
   - 自動建好 `SIROPersonaRoot` GameObject（含所有 component）
   - 自動接到現有的 HermesBridgeClient + Live2DModelController
   - 自動加右上角**齒輪 icon 按鈕**（用 `Assets/picture/gear.png` 當 sprite）
   - 場景自動儲存
5. **進 Play 模式測試**
   - 應該看到 SIRO 的 Mao
   - 右上角看到齒輪 icon
   - 點下去 → dropdown 展開
   - 選不同 persona（如果有的話）

> **換 icon**：把 Sprite 放進 `Assets/`，然後改 [PersonaSceneSetup.cs:166](SiroUnity/Assets/Editor/PersonaSceneSetup.cs) 的 `AssetDatabase.LoadAssetAtPath<Sprite>(...)` 路徑。
> 想加文字標籤：在 Hierarchy 展開 `PersonaSettingsButton` → 啟用 `Label` GameObject。

### 移除

不想要了：選單 → **Tools → SIRO → Remove Persona Manager**

## 手動接線（如果一鍵工具出問題）

| Component | 掛哪 | 設什麼 |
|---|---|---|
| `PersonaApiClient` | `SIROPersonaRoot` GameObject | `bridgeBaseUrl` = `http://127.0.0.1:8001` |
| `PersonaManager` | `SIROPersonaRoot` GameObject | apiClient / bridgeClient / modelController / `defaultPersonaId` = `siro-default` |
| `PersonaSelectorUI` | `SIROPersonaRoot` GameObject | apiClient / personaManager / dropdown / settingsToggleButton / settingsButtonLabel |

UI 物件：
- 一個 **Button**（右上角當設定按鈕）+ 內含 **TMP_Text**（顯示 `角色:SIRO`）
- 一個 **TMP_Dropdown**（預設隱藏、anchor 到按鈕下方）

## 加新角色

1. 寫一份 `bridge/personas/新角色.yaml`（參考 [docs/PERSONA.md](PERSONA.md)）
2. 把新 prefab 放 `Assets/Resources/Characters/新角色/新角色.prefab`
3. 把 persona YAML 的 `prefab_path` 設成 `Characters/新角色/新角色`（**Resources 之後**的路徑，不含 `.prefab`）
4. **重啟 bridge**（讓新 persona YAML 被讀取）
5. **重啟 Unity**（讓 Resources cache 更新）
6. 進 Play 模式 → 點「角色:SIRO」按鈕 → 應該看到新角色在清單裡

> **siro-default 範例**：Mao 已經在 MainScene instantiate，所以 `prefab_path` 留空、沿用場景內 character。Manager 會自動套 quirks 到現有的 `Live2DModelController`。

## 疑難排解

| 問題 | 解法 |
|---|---|
| 設定按鈕沒出現 | 確認 `PersonaApiClient.FetchPersonaList` 成功 — 看 Console 有沒有 `[PersonaSelectorUI] 拿 persona 清單失敗` |
| 只有 1 個 persona，按鈕自動隱藏 | 正常行為。加第二份 persona YAML 就會顯示按鈕 |
| dropdown 選完沒切角色 | 看 `[PersonaManager]` log，確認 `ApplyPersona` 有跑到 |
| 切角色後 Mao 不見 / 變白色 | persona 的 `prefab_path` 寫錯 — 應該是 Resources 內的路徑（不含副檔名）|

## 進階：把 persona 跟背景綁定

v2+ 想做「換角色自動換背景」：

```yaml
# persona YAML 加 background 欄位
model:
  background: "default_room"  # 對應 BackgroundController.backgrounds[] 的索引
```

再讓 `PersonaManager._ApplyConfig` 在切換時呼叫 `BackgroundController.SwitchTo(...)`。

目前 v1 設計：背景跟 persona 沒綁定，獨立切換。
