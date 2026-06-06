# ADR 0002: Subsystem Failure 對話對應表

- **狀態**: Proposed (Phase 3 開始時 review)
- **日期**: 2026-06-07
- **決策者**: SIRO Tech Lead
- **影響範圍**: Phase 3+ Rust runtime、Unity UX、persona dialog

---

## 背景

SIRO 是本地 kiosk、AI agent 由多個 subsystem 組成。任何一個死了都會讓 Mao 變「啞巴」、「聽不到」、「不聰明」、UX 急劇下降。

Phase 3 開始時需要：
1. Rust runtime 監控每個 subsystem 狀態
2. Subsystem 死掉時、Unity 立刻收到通知
3. Mao 切到 fallback 表情 + 講對應的「角色解釋話術」、**不讓使用者覺得「壞了」**

這份 ADR 定義每個失敗模式對應：
- Unity 端 UX（Mao 表情 + 動畫）
- Persona dialog（角色會說什麼掩飾）
- 重啟策略（自動 / 半自動 / 手動）
- K8 KPI target（< 3s 切 fallback）

---

## Subsystem 清單

| ID | Subsystem | 死亡影響 | 重啟策略 | KPI 限制 |
|----|-----------|----------|----------|---------|
| S1 | bridge (Python FastAPI) | 整個對話死 | auto 重啟 | < 5s 復活 |
| S2 | hermes (LLM 代理) | LLM 慢/失敗 | auto 重試、fallback Ollama | < 3s 切 fallback |
| S3 | MiniMax-M3 API | LLM 慢/失敗 | retry 3 次、fallback Ollama | < 10s 切 fallback |
| S4 | Ollama (本地 LLM) | 慢/失敗 | retry、跳過 | 沒有 SLA |
| S5 | unity (Live2D 渲染) | Mao 不顯示 | auto 重啟 Unity | < 3s 復原 |
| S6 | WebSocket (bridge ↔ unity) | 雙方斷線 | auto reconnect (exponential backoff) | < 5s 復原 |
| S7 | gRPC (runtime ↔ bridge) | supervisor 通訊死 | auto reconnect | < 3s 復原 |
| S8 | Supervisor (Rust daemon) | 整個監控死 | systemd 重啟 | < 30s 復原 |
| S9 | Audio (mic + speaker) | 聽不到/無聲 | 提示使用者檢查硬體 | 沒有 |
| S10 | Display (kiosk) | 看不到 | 提示、重啟 X server | < 3s |
| S11 | STT (whisper) | 不能語音輸入 | 提示用鍵盤 | < 1s 切文字模式 |
| S12 | TTS (piper) | 不能語音輸出 | 靜默、繼續顯示文字 | < 1s |

---

## 失敗模式 × 對話對應

每個失敗模式都有：
- **Detection** — 怎麼知道壞了
- **Unity UX** — Mao 表情 / 動畫 / 視覺
- **Dialog** — 角色會說的話（**有 persona 變體**）
- **Backend** — 實際降級動作

### S1: bridge 死

**Detection**: Unity WebSocket 收到 `connection closed` 或 reconnect 失敗

**Unity UX**:
- 表情: `exp_06` thinking
- 動畫: 無
- 連線狀態顯示「（連線中...）」閃爍

**Dialog**（persona 變體）:
- siro-default: 「嗯... 我在想一些事情，請稍等我一下～」
- (其他 persona: 各自客製)

**Backend**:
- Rust supervisor 偵測到 bridge process 死
- 自動重啟 bridge
- 送 `{type: "reloading", subsystem: "bridge"}` 給 Unity
- Unity 顯示「（siro reloading）」

**K8 target**: < 5s 復活、KPI 量測從 S8 supervisor 計時

---

### S2: hermes 死

**Detection**: bridge 嘗試呼叫 hermes、subprocess 失敗

**Unity UX**:
- 表情: `exp_06` thinking (短暫) → `exp_01` happy
- 不通知使用者 (因為 persona dialog 會掩飾)

**Dialog**:
- siro-default: 「嗯... 嗯！讓我想想...（小停頓）我覺得呀...」→ 正常回答
- 角色用「嗯...」「讓我想想」拖延、Ollama fallback 同時回答

**Backend**:
- bridge 自動切 Ollama fallback
- log warning（debug 層級、不污染使用者 log）

**K8 target**: < 3s 切 fallback

---

### S3: MiniMax-M3 API 死（雲端 LLM 失敗）

**Detection**: bridge chat_stream 收到 HTTP 5xx 或 timeout

**Unity UX**:
- 表情: `exp_06` thinking
- 行為: LLM 延遲

**Dialog**:
- siro-default: 「網路有點不穩、我先用本地的腦袋想一下...」
- (當降到本地 LLM 時 persona 繼續正常回答)

**Backend**:
- bridge retry 3 次、間隔 1-2s
- 都失敗 → 切 Ollama 本地 LLM
- log warning

**K8 target**: < 10s 切 fallback

---

### S4: Ollama 死（本地 LLM 失敗）

**Detection**: bridge 收到 Ollama 連線錯誤

**Unity UX**:
- 表情: `exp_05` sad (短暫)
- 動畫: head sway 慢

**Dialog**:
- siro-default: 「嗯... 我的兩個腦袋都累了，現在先打字給你好嗎？」（然後 emoji-only 模式）
- 切到「純文字」模式、不嘗試 LLM

**Backend**:
- 直接回 fallback response（persona YAML 預設的）
- 不再 retry、避免阻塞

**K8 target**: < 3s 切 fallback

---

### S5: Unity 死

**Detection**: Rust supervisor 看 Unity process 死

**Unity UX**:
- （Unity 死了所以沒 UX、restart 後保留狀態）
- 重啟時 display 黑色 → 黑屏 1-2s → 正常

**Dialog**:
- （Unity 沒辦法顯示 dialog、要靠 supervisor log + 開機 splash）

**Backend**:
- systemd watchdog 重啟 Unity
- 重新載入 scene、恢復上一個狀態

**K8 target**: < 3s 復原

---

### S6: WebSocket 斷線

**Detection**: Unity `WebSocket.State != Open`

**Unity UX**:
- 表情: 不變（Mao 繼續 idle）
- 連線狀態: 顯示「（連線中...）」

**Dialog**: 無（連線中不需要對話）

**Backend**:
- Unity auto-reconnect、exponential backoff (1s → 2s → 4s → 8s → 30s)
- bridge 不需要動、只要 accept 新連線

**K8 target**: < 5s 復原（初次 reconnect）

---

### S7: gRPC 斷線 (bridge ↔ runtime)

**Detection**: bridge 收到 gRPC call exception

**Unity UX**:
- 表情: `exp_06` thinking
- （runtime 死了 supervisor 還在、Mao 看起來卡住）

**Dialog**:
- siro-default: 「（思考中...）」
- Unity 端 `_isWaitingForResponse` 設 true、UI 顯示「（思考中...）」

**Backend**:
- bridge auto-reconnect gRPC
- supervisor 重啟 runtime

**K8 target**: < 3s 復原

---

### S8: Supervisor (siro-runtime) 死

**Detection**: systemd 看 siro-runtime process 死

**Unity UX**:
- 表情: `exp_05` sad
- 動畫: 慢
- 連線狀態: 「（siro reloading）」

**Dialog**:
- siro-default: 「讓我重新整理一下思緒...」
- 角色進入「重啟中」模式、講重生相關的話

**Backend**:
- systemd 重啟 siro-runtime
- runtime 重啟後告訴 bridge 「我回來了」
- bridge 通知 Unity「siro back online」

**K8 target**: < 30s 復原（systemd restart 慢）

---

### S9: Audio 壞了（mic 或 speaker）

**Detection**: cpal 開啟 stream 失敗 / 沒收到音訊

**Unity UX**:
- 表情: `exp_05` sad
- 提示: 螢幕上顯示「（麥克風 / 喇叭沒接好）」

**Dialog**:
- siro-default: 「咦、我好像聽不到你的聲音（或我自己說不出話）... 試試用鍵盤打字給我？」
- 主動切到「純文字」模式

**Backend**:
- disable STT/TTS
- persona dialog 用 fallback 文字回應

**K8 target**: 沒有 SLA（硬體問題）

---

### S10: Display 壞了

**Detection**: X11/Wayland 沒回應

**Unity UX**:
- （黑屏、UX 沒意義）

**Dialog**:
- 無

**Backend**:
- 重啟 X server / display manager
- Unity 重啟

**K8 target**: < 3s 復原

---

### S11: STT 死

**Detection**: whisper-rs 載入失敗 / 推論錯誤

**Unity UX**:
- 表情: `exp_06` thinking
- 提示: 「（語音輸入暫停、請用鍵盤）」

**Dialog**:
- siro-default: 「語音輸入有點不順、暫時用打字的好嗎？」

**Backend**:
- 切到純文字輸入
- 不影響 TTS

**K8 target**: < 1s 切純文字

---

### S12: TTS 死

**Detection**: piper 載入失敗 / synthesis 失敗

**Unity UX**:
- 表情: 不變
- 提示: 文字繼續顯示、但不發聲

**Dialog**:
- 無（角色繼續打字、只是不朗讀）

**Backend**:
- 切到純文字輸出
- 不影響 STT

**K8 target**: < 1s 切純文字

---

## 共通設計

### 失敗通知的 protocol

Bridge 推 `{type: "system_event", subsystem: "...", state: "down"|"up", reason: "..."}`
給 Unity、Unity 訂閱並:
1. 切表情（如果 persona dialog 還沒自動切）
2. 顯示連線狀態（如果有對應 UI）
3. 訂閱者處理（per-subsystem）

### Subsystem 狀態 UI

Unity 端做一個簡單的 status icon（選單角落小點）：
- 🟢 全部 OK
- 🟡 1+ subsystem 降級
- 🔴 1+ subsystem 死掉
- ⚪ 連線中

點 icon 展開看到 detail（MVP: tooltip 文字即可）

### Persona dialog 客製

每個 persona YAML 應該有 `failure_dialogs` 段：
```yaml
failure_dialogs:
  bridge_down: "嗯... 我在想一些事情"
  hermes_down: "我的小幫手今天有點累"
  stt_down: "語音聽起來有點模糊"
  ...
```

v1.0+ 實作。Phase 3 預留欄位。

---

## K8 KPI 量測

**K8 target**: 任意 subsystem 死掉 → Mao 在 < 3 秒切 fallback 表情

**量測方法**:
1. 製造可控失敗（kill bridge / 斷網 / 停 Ollama）
2. 用 high-speed camera 拍 Mao 螢幕
3. 量測「故障發生 → 表情切到 fallback」的時間差
4. 目標 < 3s

**Phase 3 開始時**會寫一個 `k8_failure_recovery_test.rs` 跑這個量測。

---

## 跟 GAPS 的對應

| GAPS | 對應失敗模式 |
|------|--------------|
| GAPS#4 離線降級 | S1, S2, S3, S4 |
| GAPS#9 降級路徑（細化） | 整份 ADR |
| GAPS#2 多模態（音訊基礎） | S9, S11, S12 |

---

## 下一步

- [ ] Phase 3 開始時、把 persona YAML 加 `failure_dialogs` 段
- [ ] Unity 端加 status icon
- [ ] Bridge 加 `{type: "system_event", ...}` protocol
- [ ] Phase 3 supervisor 實作時、這份 ADR 當 spec
- [ ] K8 KPI 量測腳本（`tests/k8_failure_recovery_test.rs`）
