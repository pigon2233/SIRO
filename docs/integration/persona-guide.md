# Persona 完整指南 — 撰寫 / 遷移 / 場景接線

> **目標讀者**:想加新角色、想改 SIRO 性格的開發者
> **適用版本**:v0.2+([commit `d8c9851`](https://github.com/pigon2233/SIRO) 之後)
> **配套文件**:[PERSONA.md](../PERSONA.md) — schema 規範(本檔是「怎麼用」、PERSONA.md 是「格式定義」)
>
> **本檔前身**:整合自 `PERSONA_MIGRATION_GUIDE.md`(資料層)+ `SETUP_PERSONA.md`(UI 層)兩份文件

---

## 一句話總覽

**Persona = 一個 YAML 檔**(資料) + **一個 prefab**(視覺)。改角色不用動 code。

```
bridge/personas/新角色.yaml        ← 性格 / 表情對應 / LLM prompt
SiroUnity/Assets/Resources/Characters/新角色/新角色.prefab  ← Live2D 模型
                                       ↕ 透過 persona.id 串起來
```

---

## Part A — 資料層(寫新 persona)

### A1. 角色檔結構(YAML)

最簡範例([siro-default.yaml](../../bridge/personas/siro-default.yaml)):

```yaml
id: siro-default
name: SIRO
version: 0.1.0
description: 繁中 AI 桌寳(基於 Live2D 官方 Mao 範本)
language: zh-TW
prefab_path: ""            # 空 = 沿用場景內的 Mao(MainScene 預設)

personality: |
  溫柔、有點毒舌、會吐槽使用者熬夜、記得使用者說過的話
  講話簡潔、不用 emoji、用繁體中文

quirks:
  word_replacements: []    # e.g. "AI" → "阿伊"(可選)
  speech_patterns: []      # e.g. 句尾加 "喔"、偶爾說 "嗯..."

expressions:
  default: idle
  happy: exp_01
  sad: exp_03
  angry: exp_05
  surprised: exp_06
  thinking: exp_04
  tired: exp_02
  shy: exp_07
  proud: exp_08

fallback_responses:        # 全離線 fallback
  - "嗯嗯,我在想..."
  - "讓我看一下..."
  - "稍等我一下喔"

llm:
  system_prompt: |         # 完整 system prompt(v0.1 內嵌、未來可抽檔)
    你是 SIRO,一個有點毒舌的繁中 AI 桌寳...
  temperature: 0.7
  max_tokens: 500

model:
  visual:
    scale: 1.0             # 角色大小(v0.3+ 視覺設定檔)
    position: [0, 0]
    brightness: 1.0
```

完整 schema 見 [PERSONA.md](../PERSONA.md)。

### A2. 加新角色的 SOP(5 步)

#### Step 1: 寫 YAML

複製 `bridge/personas/siro-default.yaml` 改:
- `id`、`name`、`description` 換掉
- `personality` 改成新角色人設
- `expressions` 對應到新模型的 expression 名稱(Cubism 3 的 motion3.json ID)
- `prefab_path` 設成 `Characters/新角色/新角色`(**不含 `.prefab`**)

```bash
cp bridge/personas/siro-default.yaml bridge/personas/新角色.yaml
$EDITOR bridge/personas/新角色.yaml
```

#### Step 2: 準備 Live2D prefab

把新角色資源放進:
```
SiroUnity/Assets/Resources/Characters/新角色/
  ├── 新角色.prefab         ← 預製體
  ├── 新角色.moc3           ← Live2D 模型
  ├── textures/             ← 貼圖
  └── motions/              ← motion3.json 檔
```

> **重要**:`Characters/` 必須在 `Resources/` 下,Unity 才找得到。Resources 是 Unity 內建的 runtime loader。

#### Step 3: 配 expression 對應

開 Cubism Editor 看你新模型的 expression ID、對照填到 YAML `expressions:` 段:

```yaml
expressions:
  happy: MyChar_Exp_Happy    # 跟你 Cubism 裡的 expression 名字對齊
  sad: MyChar_Exp_Sad
  ...
```

#### Step 4: 重啟 + 測試

```bash
# 1. 重啟 bridge(讓新 persona YAML 被讀取)
bash scripts/dev/dev.sh stop  # 或 Ctrl+C
bash scripts/dev/dev.sh start

# 2. 重啟 Unity(讓 Resources cache 更新)
# Unity Editor → 進 Play 模式

# 3. 點右上角「角色:SIRO」按鈕 → 看到新角色在清單
```

> 自動接線見下方 Part B(一鍵 Tools → SIRO → Setup Persona Manager)。

#### Step 5: Debug

| 問題 | 解法 |
|------|------|
| 新角色不在 dropdown | 確認 YAML 在 `bridge/personas/` + bridge 有重啟 + 沒打錯 `id` |
| 點新角色 Mao 不見 | `prefab_path` 寫錯 — 應是 `Characters/新角色/新角色`(Resources 之後路徑、不含 `.prefab`)|
| 表情切換沒反應 | 確認 `expressions` 的 ID 跟 Cubism 內 expression 名字**完全一致**(case-sensitive)|
| 切回 SIRO 沒反應 | 看 [PersonaManager] log、確認 `ApplyPersona` 有跑、Console 有沒有 exception |

### A3. SIRO 角色「換 skin」不改 persona

如果你只是換**視覺**(同一個 SIRO 換個顏色 / 衣服),不一定要新 persona:
- 改 prefab 的貼圖、保留 `id: siro-default`
- YAML 完全不動

Persona 適合「**不同的人格**」、skin 適合「**同一個人換裝**」。

### A4. 多 persona 測試的 fallback 行為

v0.x 設計:使用者可以裝多個 persona 但**一次只用一個**。要切換才看到 UI(齒輪 icon)、不打擾單一人格體驗。

```
v0.x 設計:
  進場景 → 自動套用 siro-default
  點右上角齒輪 → dropdown 展開所有 persona
  選 → 切換

v1+ 設計(規劃):
  可以「跟 SIRO 聊、跟 Mao 吵」— 切換時 SIRO 跟 Mao 互打招呼
```

v0.x 不做多 persona 對話、v1+ 才考慮。

### A5. 範例:加一個「Siro(English)」

```yaml
# bridge/personas/siro-en.yaml
id: siro-en
name: SIRO (EN)
version: 0.1.0
description: SIRO in English
language: en-US
prefab_path: "Characters/siro-en/siro-en"

personality: |
  Gentle, slightly sassy, remembers what the user said
  Speaks in English, concise, no emoji

expressions:
  default: idle
  happy: exp_01
  sad: exp_03
  angry: exp_05
  surprised: exp_06
  thinking: exp_04
  tired: exp_02
  shy: exp_07
  proud: exp_08

llm:
  system_prompt: |
    You are SIRO, a gentle, slightly sassy AI companion...
  temperature: 0.7
  max_tokens: 500
```

中文 SIRO 跟 English SIRO **共用同一個 Mao prefab**(繁中、英文版可共用模型)、`prefab_path` 留空或指向 Mao 即可。

### A6. 進階:把 persona 跟其他東西綁定(v2+ 規劃)

```yaml
# 進階 YAML(v2+ 設計、目前 v0.x 不支援)
model:
  background: "default_room"   # 切角色自動切背景
  voice:
    provider: piper
    model: zh_TW-female-medium
  idle_motions:
    - breathing
    - blink
    - look_around
  idle_interval_seconds: [10, 30]
```

v0.x 範圍:只做 `expressions` + `personality` + `llm.system_prompt`。
v2.0+ 範圍:background / voice / idle_motions。

### A7. 檔案位置總結

| 檔案 | 路徑 | 說明 |
|------|------|------|
| **Persona YAML** | `bridge/personas/<id>.yaml` | 性格 + 表情對應 + LLM prompt |
| **Live2D prefab** | `SiroUnity/Assets/Resources/Characters/<id>/<id>.prefab` | 視覺模型 |
| **i18n 字串** | `SiroUnity/Assets/Resources/i18n/<lang>.json` | UI 文案(zh-TW / en-US) |
| **PersonaManager** | `SiroUnity/Assets/Scripts/PersonaManager.cs` | 切換邏輯 |

### A8. 不在 v0.x 範圍(避免 scope creep)

- ❌ 熱切換 personality(v1+ 規劃)
- ❌ LLM 動態載入 persona prompt(v0.x 啟動時一次讀完)
- ❌ Persona 熱更新(YAML 改完要重啟 bridge)
- ❌ 自動 A/B 測試不同 persona 效果(v2+ 規劃)
- ❌ Persona 編輯 UI(v2+ 規劃、現在改 YAML 即可)

---

## Part B — UI 層(Unity 場景接線)

### B1. 設計原則

**預設完全隱藏** — 使用者打開 Play 模式直接看到 SIRO,什麼都不用點。
**想切換才看到 UI** — 跟電腦滑鼠一樣,藏在「設定」裡。

```
進場景 → 自動套用 siro-default(Mao = SIRO)
        ↓
點右上角「角色:SIRO」按鈕
        ↓
展開 persona dropdown
        ↓
選新角色 → 自動收合 + 切換
```

### B2. 一鍵接線(推薦)

#### 步驟

1. **Unity Hub 開啟 `SiroUnity/` 專案**
2. **開啟 `Assets/Scenes/MainScene.unity`**
3. **確認 Mao + ChatInputUI + HermesBridgeClient 都已存在場景**
   - 沒有的話先跑 [SETUP_NOTES.md](../../SiroUnity/SETUP_NOTES.md) 的一般 setup
4. **選單 → Tools → SIRO → Setup Persona Manager**
   - 自動建好 `SIROPersonaRoot` GameObject(含所有 component)
   - 自動接到現有的 HermesBridgeClient + Live2DModelController
   - 自動加右上角**齒輪 icon 按鈕**(用 `Assets/picture/gear.png` 當 sprite)
   - 場景自動儲存
5. **進 Play 模式測試**
   - 應該看到 SIRO 的 Mao
   - 右上角看到齒輪 icon
   - 點下去 → dropdown 展開
   - 選不同 persona(如果有的話)

> **換 icon**:把 Sprite 放進 `Assets/`,然後改 [PersonaSceneSetup.cs:166](../../SiroUnity/Assets/Editor/PersonaSceneSetup.cs) 的 `AssetDatabase.LoadAssetAtPath<Sprite>(...)` 路徑。
> 想加文字標籤:在 Hierarchy 展開 `PersonaSettingsButton` → 啟用 `Label` GameObject。

#### 移除

不想要了:選單 → **Tools → SIRO → Remove Persona Manager**

### B3. 手動接線(如果一鍵工具出問題)

| Component | 掛哪 | 設什麼 |
|---|---|---|
| `PersonaApiClient` | `SIROPersonaRoot` GameObject | `bridgeBaseUrl` = `http://127.0.0.1:8001` |
| `PersonaManager` | `SIROPersonaRoot` GameObject | apiClient / bridgeClient / modelController / `defaultPersonaId` = `siro-default` |
| `PersonaSelectorUI` | `SIROPersonaRoot` GameObject | apiClient / personaManager / dropdown / settingsToggleButton / settingsButtonLabel |

UI 物件:
- 一個 **Button**(右上角當設定按鈕)+ 內含 **TMP_Text**(顯示 `角色:SIRO`)
- 一個 **TMP_Dropdown**(預設隱藏、anchor 到按鈕下方)

### B4. 疑難排解

| 問題 | 解法 |
|---|---|
| 設定按鈕沒出現 | 確認 `PersonaApiClient.FetchPersonaList` 成功 — 看 Console 有沒有 `[PersonaSelectorUI] 拿 persona 清單失敗` |
| 只有 1 個 persona,按鈕自動隱藏 | 正常行為。加第二份 persona YAML 就會顯示按鈕 |
| dropdown 選完沒切角色 | 看 `[PersonaManager]` log,確認 `ApplyPersona` 有跑到 |
| 切角色後 Mao 不見 / 變白色 | persona 的 `prefab_path` 寫錯 — 應該是 Resources 內的路徑(不含副檔名)|

### B5. 進階:把 persona 跟背景綁定

v2+ 想做「換角色自動換背景」:

```yaml
# persona YAML 加 background 欄位
model:
  background: "default_room"  # 對應 BackgroundController.backgrounds[] 的索引
```

再讓 `PersonaManager._ApplyConfig` 在切換時呼叫 `BackgroundController.SwitchTo(...)`。

目前 v1 設計:背景跟 persona 沒綁定,獨立切換。

---

## 相關文件

- [PERSONA.md](../PERSONA.md) — Persona schema 規範
- [PLANS/strategic-gaps.md](../PLANS/strategic-gaps.md) #3 — Persona 設計原始 gap
- [SiroUnity/Assets/Scripts/PersonaManager.cs](../../SiroUnity/Assets/Scripts/PersonaManager.cs) — 切換實作
- [bridge/prompts.py](../../bridge/prompts.py) — 載入 YAML 邏輯
- [CHANGELOG.md](../CHANGELOG.md) 2026-06-03 段 — persona 抽象 v0.x 歷史

---

**最後一句話**:

Persona 是 SIRO 的「**靈魂**」、prefab 是「**身體**」。
換靈魂不用換身體、換身體也不用換靈魂。
**改 YAML 就能改 SIRO 是誰。**
