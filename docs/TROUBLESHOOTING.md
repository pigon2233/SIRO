# SIRO Troubleshooting — 常見問題排查手冊

> 從實際除錯經驗累積下來、依序檢查可以省下 30 分鐘到 1 小時的瞎試時間。
> 寫這個文件時 SIRO 還在 v0.x 階段、之後新的坑會陸續加進來。

---

## 1. 點擊 Mao 沒反應（OnPointerClick 沒觸發）

依序檢查、漏一就不 work：

### □ 1.1 EventSystem 在場景
- Hierarchy 找有沒有 `EventSystem` GameObject
- 沒有：右鍵 → **Create Empty** → 改名 `EventSystem` → Add Component → `Event System` + **`Input System UI Input Module`**（不是 `StandaloneInputModule`）
- 注意：**Project Settings → Player → Active Input Handling** 預設有 3 個選項
  - `Input System Package (New)` ← 對應 `InputSystemUIInputModule`
  - `Input Manager (Old)` ← 對應 `StandaloneInputModule`
  - 兩個 module 不能混用

### □ 1.2 Main Camera 有 `Physics 2D Raycaster`（Mao 不在 Canvas 下）
- Hierarchy 找 `Main Camera`
- Inspector 找 `Physics 2D Raycaster` component
- 沒加：Add Component → `Physics 2D Raycaster`

### □ 1.3 Mao 跟 Collider 在同一個 GameObject
- Unity EventSystem 找 `IPointerClickHandler` 是看「有 collider 又實作 handler」的 GameObject
- 兩個 component 必須在**同一個 GameObject**：
  - `Capsule Collider 2D` 或 `Box Collider 2D`（Mao 不在 Canvas）
  - `RawImage` / `Image` with `Raycast Target = true`（Mao 在 Canvas）
- 分開在不同 GameObject 會壞 — Unity 找 handler 不會跨 GameObject

### □ 1.4 `Live2DModelController.clickable = true`
- Inspector 預設是 `true`、但有人可能關掉
- 不然 `OnPointerClick` 會在第一行 return

### □ 1.5 PersonaClickHandler references 設對
- `Live2DController` 欄位指向 Mao 那個 GameObject 的 Live2DModelController
- `Bridge` 欄位指向 HermesBridgeClient 那個 GameObject
- 沒設會在 Start 印 `[PersonaClickHandler] 找不到 Live2DModelController`

### □ 1.6 `clickableAreas` 至少有一筆 + area 對得上
- `clickableAreas.Size` 是 0 的話點了不會送 task
- `area` 欄位（如 "body"）要跟 `OnMaoClicked` 傳入的字串對
- v1.2 MVP 一律傳 `"body"`（v1.5+ 才分 head/body）

### □ 1.7 UI 沒蓋住 Mao（最常被忽略）
- **Mao 在 Canvas 下、Canvas 內有全螢幕 Image** → Image 收 click、Mao 收不到
- 找 Canvas 下最大的 Image / Panel、取消 `Raycast Target`
- 或把 Mao 跟 UI 分兩個區域（不重疊）
- 測試法：暫時把整個 Canvas 設成 `enabled = false`、點 Mao → 如果這時候 work、UI 就是元凶

### □ 1.8 沒看到 log？
按 Play 點 Mao、Unity Console 應該有這些（缺哪行就回去查對應段）：
```
[Live2DModelController] Mao 點擊 (hitArea=body)
[PersonaClickHandler] 收到 OnMaoClicked: hitArea=body
[PersonaClickHandler] SendTask: mood.set args=...
```

---

## 2. 表情切換沒生效（mood.set 送了但 Mao 不動）

### □ 2.1 bridge 程式碼有 reload？
- 之前 commit d3a42f4 加的「mood.set 推 response 給 Unity」邏輯需要新版的 bridge
- **砍掉重啟 bridge**、Python module 不會自動 reload

### □ 2.2 Unity Console 有 `[EmotionDisplay] 收到情緒` 嗎？
- 沒有 → response 沒到 Unity
- 有 → 往下查

### □ 2.3 Live2DModelController reference 設對？
- Hierarchy 找 `EmotionDisplay` GameObject
- Inspector 找 `_modelController` 欄位
- 沒設：拖 Mao 那個 GameObject 進去

### □ 2.4 Cubism SDK 有 expression controller？
- Mao prefab 要有 `CubismExpressionController` component
- 沒的話 `SetExpression` 會 log "無 expression controller"

### □ 2.5 看到 `[Live2DModelController] 找不到 expression` warning？
- 意思是 bridge 推的 expression_id（如 `exp_06`）跟 Mao 模型實際的 expression asset 對不上
- 開 `Live2DModelController` 印出的「模型實際有的 expressions」清單、對照 persona YAML 的 `model.expressions`

---

## 3. bridge 響應時間過長

### □ 3.1 沒裝 hermes 的 dev box 場景
- `/chat` 走 Ollama fallback
- 預設 `OllamaClient.DEFAULT_TIMEOUT = 3s`（v1.2 從 15s 改 3s）
- 真的 Ollama 3B model 在 CPU 跑、可能要 5-10s 才回
- 解決法：裝 hermes（v0.x dev 不需要、但要明確知道 dev box 慢是 Ollama 本身）

### □ 3.2 有裝 hermes 的場景
- 第一次 hermes 啟動 2-3s（CLI cold start）
- LLM cold connect 3-5s
- LLM TTFT 3-5s（不可壓縮）
- 生成 ~150 tokens 5-8s
- **總共 13-20s** — 雲端 LLM 現實、無法消除
- 改善：開 SIRO_STREAMING=true → TTFT 之後 streaming 進來、Unity 端 incremental render
- 預期會看到的 bridge log（拆段計時）：
  ```
  ⏱ [chat] 段 is_available=...
  ⏱ [chat] 段 hermes_chat=...
  ```
  看到 `段 hermes_chat > 10s` 是 LLM 慢、看 `段 is_available > 1s` 是 hermes CLI 慢

### □ 3.3 量測方法
```bash
time curl -X POST http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hi","user_id":"speed"}'
```
- 看 `time` 輸出
- 看 bridge log 的 `⏱ 分段` 找瓶頸段

---

## 4. 連線斷 / 重連卡住

### □ 4.1 bridge 沒起來
- 看 Unity Console 是不是有 `[HermesBridge] 連線失敗`
- 確認 bridge 跑在預設 port（8001）或設定 `serverUrl` 對

### □ 4.2 重連卡住
- bridge client 有自動重連（指數 backoff 1s → 2s → 4s → ... cap 30s）
- 看到 `OnReconnectAttempt(int)` event 持續觸發 = 重連失敗
- 看 bridge 是不是真的有在跑、port 沒被別的程式佔

### □ 4.3 `SIRO_USE_AGENT_OS=true` 但 /chat 卡住
- AgentOS path 透過 `wait_for_task` 等 worker 跑
- bridge log 看有沒有 `[AgentOS]` worker 訊息
- 沒起來：lifespan 失敗、檢查先前的 lifespan log 錯誤

---

## 5. SendTask 沒回應 / 失敗

### □ 5.1 task_result 沒回
- bridge log 看 `接 task: ...` 有沒有出來
- 沒出來：Unity 沒送成功、檢查 `SendTaskAsync` 有沒有 throw

### □ 5.2 task_failed 回來
- bridge log 印 `error` 訊息
- 常見：
  - `unknown task` → task name 沒註冊、看 `list_tasks()` 確認
  - `mood.set: invalid emotion` → emotion 不在 9 個 persona emotion 之一
  - `mood.set: missing required arg` → args 缺欄位
  - `intensity out of range` → 0-1 之外

### □ 5.3 5 秒 timeout 觸發
- bridge handler 跑了但 >5s 沒回 result
- handler 內部 await 卡住（Ollama、LLM）或 raise 沒被接
- 看 bridge log 找 handler 自己的 logger 訊息

### □ 5.4 auto-revert 沒生效
- 確認 `duration_sec` 有在 args 裡（不是 `duration`）
- bridge log 看 `duration=Xs（X.X 秒後自動回 neutral）`
- 確認 bridge 是新版（commit f1b20d8 之後）

---

## 6. 測試

### □ 6.1 bridge 啟動失敗
```bash
cd "c:/coconut chennel/SIRO"
python -m bridge.main
```
- 看 traceback 第一行：通常是 import error 或 syntax error
- 修完再 `taskkill /F /PID <pid>` + 重啟

### □ 6.2 pytest 卡住 / 沒結束
- 通常是 WS test 用 `time.sleep` 等 `asyncio.create_task` — 但 time.sleep block event loop
- 解法：不要 sleep、改用 `await` 觸發 event loop

### □ 6.3 PersonaSelectorUI compile error `CS0103`
- `placeholderText` 沒定義 → 確認是 `dropdownPlaceholderKey` 欄位
- 參考 commit `e113d32` 的 fix 模式

---

## 7. 文件 vs 程式碼不一致

### □ 7.1 PLAN.md 寫的 v0.x 進度跟實際 commit 對不上
- 每次做完都更新 `LIVE2D_AI_AGENT_OS_PLAN.md` 的 v0.x 進度子表 + 變更紀錄
- 不要相信「記得」 — 一定 commit 時順便改文件

### □ 7.2 AGENT_OS.md 的規格跟實際 bridge 行為對不上
- v1.2 SendTask 規格在 AGENT_OS.md §6 範例
- 對照 commit hash 看實作是否照規格

---

## 8. UI 邏輯（v1+ 要重構）

> 2026-06-05 註：目前 UI 配置 ResponseText 全螢幕蓋住 Mao、click 永遠打到 UI。
> v1+ 預計重構：
> - Mao 顯示區跟 chat 對話框分開（左右 / 上下分區）
> - ResponseText 移到 Mao 區域外
> - 統一所有 input field 的 Raycast Target 行為

---

## 9. 其他常見錯誤

### □ 9.1 `RuntimeError: 未預期錯誤: timed out`（Ollama）
- Ollama 沒跑 / hang / CPU 滿載
- 看 `ollama ps` 確認 model 載入狀態
- 3s timeout 觸發後 bridge 走 hard fallback

### □ 9.2 `KeyError: 'emotion'` in log
- bridge log format string 用 `{emotion}` 但 result 沒這欄位
- 通常是 persona 切換後 state 沒更新、rebuild bridge 試試

### □ 9.3 `ImportError: cannot import name 'X'`
- Python 模組沒 load 或 commit 沒完成
- 砍掉重啟、檢查 `git status` 是不是有未 commit 的改動

---

## 10. 報告新坑

碰到新問題、想加進這份文件、附上：
- 問題描述
- 症狀（log 片段）
- 排查步驟
- 解法（哪個 commit 修的）
- 預防建議
