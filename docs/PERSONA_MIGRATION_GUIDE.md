# Persona 撰寫 / 遷移指南

> **目標讀者**：想加新角色、想改 SIRO 性格的開發者
> **適用版本**：v0.2+（[commit `d8c9851`](https://github.com/pigon2233/SIRO) 之後）
> **配套文件**：[PERSONA.md](PERSONA.md) — schema 規範（本檔是「怎麼用」、PERSONA.md 是「格式定義」）

---

## 一句話總覽

**Persona = 一個 YAML 檔**（資料） + **一個 prefab**（視覺）。改角色不用動 code。

```
bridge/personas/新角色.yaml        ← 性格 / 表情對應 / LLM prompt
SiroUnity/Assets/Resources/Characters/新角色/新角色.prefab  ← Live2D 模型
                                       ↕ 透過 persona.id 串起來
```

---

## 1. 角色檔結構（YAML）

最簡範例（[siro-default.yaml](../bridge/personas/siro-default.yaml)）：

```yaml
id: siro-default
name: SIRO
version: 0.1.0
description: 繁中 AI 桌寳（基於 Live2D 官方 Mao 範本）
language: zh-TW
prefab_path: ""            # 空 = 沿用場景內的 Mao（MainScene 預設）

personality: |
  溫柔、有點毒舌、會吐槽使用者熬夜、記得使用者說過的話
  講話簡潔、不用 emoji、用繁體中文

quirks:
  word_replacements: []    # e.g. "AI" → "阿伊"（可選）
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
  - "嗯嗯，我在想..."
  - "讓我看一下..."
  - "稍等我一下喔"

llm:
  system_prompt: |         # 完整 system prompt（v0.1 內嵌、未來可抽檔）
    你是 SIRO，一個有點毒舌的繁中 AI 桌寳...
  temperature: 0.7
  max_tokens: 500

model:
  visual:
    scale: 1.0             # 角色大小（v0.3+ 視覺設定檔）
    position: [0, 0]
    brightness: 1.0
```

完整 schema 見 [PERSONA.md](PERSONA.md)。

---

## 2. 加新角色的 SOP（5 步）

### Step 1: 寫 YAML

複製 `bridge/personas/siro-default.yaml` 改：
- `id`、`name`、`description` 換掉
- `personality` 改成新角色人設
- `expressions` 對應到新模型的 expression 名稱（Cubism 3 的 motion3.json ID）
- `prefab_path` 設成 `Characters/新角色/新角色`（**不含 `.prefab`**）

```bash
cp bridge/personas/siro-default.yaml bridge/personas/新角色.yaml
$EDITOR bridge/personas/新角色.yaml
```

### Step 2: 準備 Live2D prefab

把新角色資源放進：
```
SiroUnity/Assets/Resources/Characters/新角色/
  ├── 新角色.prefab         ← 預製體
  ├── 新角色.moc3           ← Live2D 模型
  ├── textures/             ← 貼圖
  └── motions/              ← motion3.json 檔
```

> **重要**：`Characters/` 必須在 `Resources/` 下，Unity 才找得到。Resources 是 Unity 內建的 runtime loader。

### Step 3: 配 expression 對應

開 Cubism Editor 看你新模型的 expression ID、對照填到 YAML `expressions:` 段：

```yaml
expressions:
  happy: MyChar_Exp_Happy    # 跟你 Cubism 裡的 expression 名字對齊
  sad: MyChar_Exp_Sad
  ...
```

### Step 4: 重啟 + 測試

```bash
# 1. 重啟 bridge（讓新 persona YAML 被讀取）
bash scripts/dev/dev.sh stop  # 或 Ctrl+C
bash scripts/dev/dev.sh start

# 2. 重啟 Unity（讓 Resources cache 更新）
# Unity Editor → 進 Play 模式

# 3. 點右上角「角色:SIRO」按鈕 → 看到新角色在清單
```

> 自動接線見 [SETUP_PERSONA.md](SETUP_PERSONA.md)（一鍵 Tools → SIRO → Setup Persona Manager）。

### Step 5: Debug

| 問題 | 解法 |
|------|------|
| 新角色不在 dropdown | 確認 YAML 在 `bridge/personas/` + bridge 有重啟 + 沒打錯 `id` |
| 點新角色 Mao 不見 | `prefab_path` 寫錯 — 應是 `Characters/新角色/新角色`（Resources 之後路徑、不含 `.prefab`）|
| 表情切換沒反應 | 確認 `expressions` 的 ID 跟 Cubism 內 expression 名字**完全一致**（case-sensitive）|
| 切回 SIRO 沒反應 | 看 [PersonaManager] log、確認 `ApplyPersona` 有跑、Console 有沒有 exception |

---

## 3. SIRO 角色「換 skin」不改 persona

如果你只是換**視覺**（同一個 SIRO 換個顏色 / 衣服），不一定要新 persona：
- 改 prefab 的貼圖、保留 `id: siro-default`
- YAML 完全不動

Persona 適合「**不同的人格**」、skin 適合「**同一個人換裝**」。

---

## 4. 多 persona 測試的 fallback 行為

v0.x 設計：使用者可以裝多個 persona 但**一次只用一個**。要切換才看到 UI（齒輪 icon）、不打擾單一人格體驗。

```
v0.x 設計:
  進場景 → 自動套用 siro-default
  點右上角齒輪 → dropdown 展開所有 persona
  選 → 切換
  
v1+ 設計（規劃）:
  可以「跟 SIRO 聊、跟 Mao 吵」— 切換時 SIRO 跟 Mao 互打招呼
```

v0.x 不做多 persona 對話、v1+ 才考慮。

---

## 5. 範例：加一個「Siro（English）」

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

中文 SIRO 跟 English SIRO **共用同一個 Mao prefab**（繁中、英文版可共用模型）、`prefab_path` 留空或指向 Mao 即可。

---

## 6. 進階：把 persona 跟其他東西綁定（v2+ 規劃）

```yaml
# 進階 YAML（v2+ 設計、目前 v0.x 不支援）
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

v0.x 範圍：只做 `expressions` + `personality` + `llm.system_prompt`。
v2.0+ 範圍：background / voice / idle_motions。

---

## 7. 檔案位置總結

| 檔案 | 路徑 | 說明 |
|------|------|------|
| **Persona YAML** | `bridge/personas/<id>.yaml` | 性格 + 表情對應 + LLM prompt |
| **Live2D prefab** | `SiroUnity/Assets/Resources/Characters/<id>/<id>.prefab` | 視覺模型 |
| **i18n 字串** | `SiroUnity/Assets/Resources/i18n/<lang>.json` | UI 文案（zh-TW / en-US） |
| **PersonaManager** | `SiroUnity/Assets/Scripts/PersonaManager.cs` | 切換邏輯 |

---

## 8. 不在 v0.x 範圍（避免 scope creep）

- ❌ 熱切換 personality（v1+ 規劃）
- ❌ LLM 動態載入 persona prompt（v0.x 啟動時一次讀完）
- ❌ Persona 熱更新（YAML 改完要重啟 bridge）
- ❌ 自動 A/B 測試不同 persona 效果（v2+ 規劃）
- ❌ Persona 編輯 UI（v2+ 規劃、現在改 YAML 即可）

---

## 9. 跟 SETUP_PERSONA.md 的關係

- **本檔（PERSONA_MIGRATION_GUIDE.md）**：怎麼**寫**新 persona（資料層）
- **SETUP_PERSONA.md**：怎麼在 **Unity 場景接線** persona 切換 UI（UI 層）

兩者一起讀。

---

## 相關文件

- [PERSONA.md](PERSONA.md) — Persona schema 規範
- [SETUP_PERSONA.md](SETUP_PERSONA.md) — Unity 場景接線 SOP
- [GAPS.md #3](GAPS.md) — Persona 設計原始 gap
- [SiroUnity/Assets/Scripts/PersonaManager.cs](../SiroUnity/Assets/Scripts/PersonaManager.cs) — 切換實作
- [bridge/prompts.py](../bridge/prompts.py) — 載入 YAML 邏輯
- [CHANGELOG.md 2026-06-03 段](CHANGELOG.md) — persona 抽象 v0.x 歷史

---

**最後一句話**：

Persona 是 SIRO 的「**靈魂**」、prefab 是「**身體**」。
換靈魂不用換身體、換身體也不用換靈魂。
**改 YAML 就能改 SIRO 是誰。**
