# Persona Schema 規範

> **狀態**：Phase 1.5（2026-06-03 起草）
> **動機**：把角色性格、表情、聲音從 code 抽出來，做到「資料與程式碼分離」。
> 換角色 = 換一個 YAML 檔，不用改任何 .py / .cs。
>
> **問題出處**：[docs/GAPS.md](GAPS.md) #3

---

## 為什麼需要 Persona

Phase 1 的 SIRO 角色性格直接 hardcode 在 [bridge/prompts.py](../bridge/prompts.py)：

```python
SYSTEM_PROMPT_BASE = """你是一個溫暖、友善的陪伴型 AI 角色..."""
```

問題：
- 想換成「毒舌系」「冷酷系」「英文 only」要改 code、重 commit、重啟
- 表情清單散在 4 個檔（mapping JSON、EmotionDisplay.cs、Mao.prefab、prompts.py）
- 沒辦法做「同一台裝置兩個角色切換」
- 朋友想分享自製角色，要他 fork repo（門檻太高）

Persona 把這些集中到一個 YAML 檔。**換角色 = 換檔案**。

---

## Persona Schema (v0.1)

完整範例：[bridge/personas/siro-default.yaml](../bridge/personas/siro-default.yaml)

```yaml
# ----- 基本識別 -----
id: siro-default                    # 唯一 ID，URL-safe
name: SIRO                          # 顯示名（UI 上會看到）
version: 0.1.0
language: zh-TW                     # 主要語言（影響 LLM prompt、TTS）

# ----- 性格 -----
personality:
  system_prompt: |
    你是一個溫暖、友善的陪伴型 AI 角色...
    （多行 prompt，會跟使用者 message 串接送給 LLM）
  temperature: 0.7
  max_tokens: 300

# ----- 視覺模型 -----
model:
  type: cubism                      # 目前只支援 cubism (Live2D)
  prefab_path: Live2D/Cubism/Samples/Models/Mao/Mao.prefab
  # 模型特有 quirks
  quirks:
    # exp_02/03 閉眼但眼球露出，runtime 隱藏這些 Drawable
    hide_eye_on_expressions: [exp_02, exp_03]
    eye_drawable_indices: [87, 92]

# ----- 情緒 → expression 映射 -----
expressions:
  happy: exp_01
  joyful: exp_02
  proud: exp_03
  excited: exp_04
  sad: exp_05
  thinking: exp_06
  surprised: exp_07
  angry: exp_08
  neutral: exp_01                   # 借用 happy

# ----- 待機動作 (Phase 2 用) -----
idle_motions:
  - idle_breathing
  - idle_blink
idle_interval_seconds: [10, 30]

# ----- TTS 聲線 (Phase 2-3 用) -----
voice:
  provider: piper                   # piper / edge-tts / cloud
  model: zh_TW-female-medium
  speed: 1.0
  pitch: 0

# ----- 降級回應池 (Phase 1.5 用) -----
# Hermes 死掉 / 網路斷時用的預設回應
fallback_responses:
  thinking:
    - 嗯...
    - 我想想...
    - 等等喔...
  error:
    - 我有點不舒服，稍等
    - 抱歉，剛剛卡住了
    - 給我一點時間
```

---

## 欄位規範

### 必填

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | string (URL-safe) | 唯一識別，檔名一致 |
| `name` | string | UI 顯示名 |
| `language` | BCP-47 code | 主要語言（zh-TW / en-US / ja-JP） |
| `personality.system_prompt` | string | 餵給 LLM 的 prompt（會自動加情緒規則） |
| `model.type` | enum | 目前只 `cubism` |
| `model.prefab_path` | string | 相對於 SiroUnity/Assets/ 的路徑 |
| `expressions.{happy,sad,...}` | string | Cubism expression ID（不含 .exp3 後綴） |

### 選填

| 欄位 | 預設 | 說明 |
|---|---|---|
| `version` | "0.1.0" | semver |
| `personality.temperature` | 0.7 | LLM 創造性 |
| `personality.max_tokens` | 300 | 回應長度上限 |
| `model.quirks.hide_eye_on_expressions` | `[]` | 哪些 expression 要隱藏眼球（Mao 限定 hack） |
| `model.quirks.eye_drawable_indices` | `[]` | 眼球的 Drawable index |
| `idle_motions` | `[]` | Phase 2 用 |
| `idle_interval_seconds` | `[15, 45]` | Phase 2 用 |
| `voice` | (無 TTS) | Phase 2-3 用 |
| `fallback_responses` | 預設池 | Phase 1.5 離線降級用 |

---

## 載入規則

```
bridge/personas/
├── siro-default.yaml     ← 預設角色
├── tsundere.yaml         ← 毒舌系（範例）
└── english-companion.yaml  ← 英文版（範例）
```

選擇方式（優先序高 → 低）：
1. `POST /chat` request 的 `personality` 欄位（runtime 切換）
2. `bridge/.env` 的 `SIRO_DEFAULT_PERSONA` 環境變數
3. 找不到指定 → fallback 到 `siro-default.yaml`
4. 連 default 都沒 → bridge 啟動失敗

---

## 表情對應的 source of truth

> **重要**：當前 Phase 1 末狀態，表情對應**重複定義**在 3 個地方：
>
> 1. `bridge/emotion_mapping.json` — bridge 用
> 2. `SiroUnity/Assets/Scripts/EmotionDisplay.cs` 預設值 + `Mao.prefab` serialize 值 — Unity 用
> 3. Persona YAML（即將）
>
> Phase 1.5 計畫：**Persona YAML 變唯一 source of truth**，bridge 跟 Unity 都從它讀。
>
> 但 Unity 端讀 YAML 需要 Newtonsoft / YamlDotNet 套件 + serialize 一份到 Resources/ 給 runtime 用。這個 Phase 2 才做（暫時 EmotionDisplay 維持 Inspector 欄位）。

---

## 範例：自製角色

如果要做個「毒舌系」角色：

```yaml
id: tsundere
name: 小綾
language: zh-TW
personality:
  system_prompt: |
    你是一個傲嬌型角色，嘴上毒舌但心裡關心使用者。
    被誇獎會害羞、生氣的時候會反駁但其實沒生氣。
    講話常用「哼」「才不是」「你也太...」之類語氣。
  temperature: 0.9                  # 高一點，回應更鮮活
model:
  type: cubism
  prefab_path: Live2D/Cubism/Samples/Models/Mao/Mao.prefab   # 還是用 Mao 模型
  quirks:
    hide_eye_on_expressions: [exp_02, exp_03]
    eye_drawable_indices: [87, 92]
expressions:
  # 跟 default 一樣（共用 Mao）
  happy: exp_01
  joyful: exp_02
  # ... 略
voice:
  provider: piper
  model: zh_TW-female-medium
  pitch: 2                          # 高一點，傲嬌感
```

存成 `bridge/personas/tsundere.yaml`，重啟 bridge，`POST /chat {"personality": "tsundere", ...}` 就能切換。

---

## 未來擴充

- **v0.2**：加 `memory` 欄位（記得使用者名字、喜好等）
- **v0.3**：加 `triggers` 欄位（聽到「我餓了」自動切某個 motion）
- **v1**：加 `multi_model` 支援（一個 Persona 配多個 Live2D 模型）
- **v2**：Persona Marketplace（社群分享 .yaml）

---

## 相關文件

- [docs/GAPS.md](GAPS.md) #3 — 為什麼要 Persona
- [bridge/personas/](../bridge/personas/) — 範例 Persona
- [bridge/prompts.py](../bridge/prompts.py) — 載入 Persona 的程式碼
