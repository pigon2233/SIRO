# SIRO 從零到 v0 能跑

> 這份文件描述「全新機器 + 全新環境」到「v0 骨架能跑通」的所有步驟。
> 如果你已經有部分環境，可以跳過對應步驟。

---

## 0. 前置需求

- **OS**：Windows 10+ / macOS 11+ / Linux / WSL2
- **Python 3.11+**（Hermes 內建 uv 會自己裝，bridge 也建議用 uv）
- **Git**
- **Unity 6 LTS**（Unity Hub 裝）
- **網路**：要能連 LLM API（除非用本地 Ollama）

如果用 Ollama（離線測試推薦）：
- 安裝 [Ollama](https://ollama.com/) 並 `ollama pull llama3.1:8b`

---

## 1. 取得 SIRO 程式碼

```bash
git clone <repo_url> SIRO
cd SIRO
```

或如果你是開發者、已經有程式碼：

```bash
cd <path-to-SIRO>
git pull
```

---

## 2. 安裝 Hermes Agent

**Linux / macOS / WSL2**：
```bash
bash agent/install.sh
```

**Windows PowerShell**：
```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

跑完後確認：

```bash
hermes --version
# 應該顯示類似：v0.15.2
```

如果 `hermes` 指令找不到，把這行加進 `~/.bashrc` / `~/.zshrc`：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

## 3. 設定 LLM Provider

選一個（推薦 Nous Portal，可一站管理多模型）：

### 選項 A：Nous Portal

1. 到 [portal.nousresearch.com](https://portal.nousresearch.com/) 註冊、拿 API key
2. 跑設定：
   ```bash
   hermes setup --portal
   ```
   貼上 API key，選模型（推薦 `hermes-3-llama-3.1-70b`）

### 選項 B：OpenRouter

1. 到 [openrouter.ai/keys](https://openrouter.ai/keys) 拿 API key
2. 編輯 `~/.hermes/.env`：
   ```bash
   HERMES_LLM_PROVIDER=openrouter
   HERMES_API_KEY=sk-or-v1-xxxxxxxx
   HERMES_LLM_MODEL=anthropic/claude-3.5-sonnet
   ```

### 選項 C：本地 Ollama（離線測試）

1. 安裝 [Ollama](https://ollama.com/)，跑：
   ```bash
   ollama pull llama3.1:8b
   ollama serve   # 跑在背景
   ```
2. 編輯 `~/.hermes/.env`：
   ```bash
   HERMES_LLM_PROVIDER=ollama
   HERMES_LLM_BASE_URL=http://localhost:11434
   HERMES_LLM_MODEL=llama3.1:8b
   ```

### 驗證

```bash
bash agent/verify.sh
```

這個腳本會：
- 確認 hermes CLI 可用
- 跑一次 `hermes -p "說一句你好"`
- 確認 `.env` 設定

如果失敗，看錯誤訊息修。

---

## 4. 啟動 Bridge

```bash
cd bridge

# 建 venv
python -m venv .venv
source .venv/bin/activate        # Linux/macOS/WSL
# .venv\Scripts\activate         # Windows PowerShell

# 裝依賴
pip install -r requirements.txt

# 跑起來
python -m bridge.main
```

應該看到：

```
╔════════════════════════════════════════╗
║  SIRO Bridge                            ║
║  http://127.0.0.1:8001
╚════════════════════════════════════════╝

INFO:     Started server process [12345]
INFO:     Waiting for application startup.
🚀 SIRO Bridge 啟動中...
✓ Hermes 可用: v0.15.2
✓ 情緒解析器就緒
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001
```

**開另一個 terminal 測試**：

```bash
# 健康檢查
curl localhost:8001/health
# 應該回 {"status":"ok","hermes_available":true,...}

# 單次對話
curl -X POST localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好！","user_id":"test"}'
# 應該回 {"text":"...","emotion":"happy","live2d":{...}}
```

如果 `hermes_available: false`，回去看 Step 3。

---

## 5. 設定 Unity 專案

### 5.1 建立 Unity 專案

1. 開 Unity Hub
2. 確認 Unity **6 LTS** 已安裝（沒裝就 Install）
3. Projects → New Project → 3D (URP)
4. Project name: `siro-unity`（隨意）
5. Location: 選個資料夾（**不要**放在 SIRO/unity 裡，會跟設定檔衝突）
6. Create Project

### 5.2 套用 SIRO 的 manifest.json

把你新專案的 `Packages/manifest.json` 用本倉庫的版本覆蓋：

```bash
cp <SIRO-repo>/unity/Packages/manifest.json <your-unity-project>/Packages/manifest.json
```

回 Unity Editor，會自動裝套件。

### 5.3 安裝 Cubism SDK

1. 到 [Live2D Cubism SDK for Unity 下載](https://www.live2d.com/en/sdk/download/cubism-sdk-for-unity/)
2. 註冊/登入 Live2D 帳號
3. 下載最新版的 `CubismSdkForUnity-*.unitypackage`
4. Unity Editor → 雙擊 `.unitypackage` → Import All

### 5.4 取得 Hiyori 模型

從 [Live2D 範例下載](https://www.live2d.com/en/download/sample-data/) 抓 Hiyori（或從 Cubism SDK 範例 import）。

把模型放進 Unity 專案的 `Assets/Models/Hiyori/`。

### 5.5 複製 SIRO Scripts

```bash
cp <SIRO-repo>/unity/Assets/Scripts/*.cs <your-unity-project>/Assets/Scripts/
```

回 Unity Editor，等編譯完（Console 不應該有紅色錯誤）。

### 5.6 建立 MainScene

1. `File > New Scene` → 存成 `Assets/Scenes/MainScene.unity`
2. 從 `Assets/Models/Hiyori/` 拖模型到場景
3. 建立 UI Canvas：
   - `GameObject > UI > Canvas`
   - 在 Canvas 下加：
     - `InputField`（或 `TMP_InputField`）
     - `Button`（命名 `SendButton`）
     - `Text`（或 `TMP_Text`，命名 `ResponseText`）
4. 建立空 GameObject 命名 `Bridge`：
   - Add Component → `HermesBridgeClient`（在 Siro namespace）
5. 設定每個 Component 的 Inspector 參照：
   - `Bridge > HermesBridgeClient`：`serverUrl` = `ws://127.0.0.1:8001/ws`
   - `Hiyori > Live2DModelController`（Add Component）
   - `Hiyori > EmotionDisplay`（Add Component）：把 `Bridge` 拖到 `bridgeClient` 欄位
   - `Canvas > ChatInputUI`（Add Component）：把 InputField、SendButton、ResponseText 拖進欄位
6. 存場景

---

## 6. 端到端測試

1. 確認 `bridge/main.py` 正在跑（看 terminal）
2. Unity Editor 按 **Play**
3. 應該看到 Hiyori 模型
4. UI 上 InputField 輸入「你好」→ 按 Send
5. 預期：
   - ResponseText 顯示 AI 回應文字
   - Hiyori 切換到對應 expression（F02 = 開心）

如果沒反應，看 Unity Console 跟 bridge terminal 的 log。

---

## 7. 跑測試

```bash
cd bridge
python -m pytest tests/ -v
```

應該全部通過（不依賴真的 hermes 連線）。

---

## 8. 常見錯誤

### `hermes: command not found`

PATH 沒設。見 Step 2 結尾。

### `Hermes 不可用` (bridge 啟動時)

跑 `bash agent/verify.sh` 確認 hermes CLI 跟 API key 都 OK。

### Unity Console 紅字 `CS0246: The type or namespace name 'Live2D' could not be found`

Cubism SDK 沒裝好。回 Step 5.3。

### Unity Play 模式沒看到模型

確認 Hiyori prefab 有拖到場景樹，Camera 角度對。

### `WebSocket 連線失敗`

- Bridge 沒啟動？
- URL 對嗎？（預設 `ws://127.0.0.1:8001/ws`）
- 防火牆擋了 8001 port？

### 表情沒切換

- 確認 `Hiyori` GameObject 上有 `Live2DModelController` 跟 `EmotionDisplay`
- `EmotionDisplay.bridgeClient` 有拖到 `Bridge` GameObject
- 確認 Hiyori 模型的 expression 檔名是 `F01.exp3.json` ~ `F06.exp3.json`

---

## 下一步

骨架能跑之後：

- 改 emotion mapping：`bridge/emotion_mapping.json`
- 改 system prompt：`bridge/prompts.py`
- 加更多 expression/motion：見 [unity/README.md](../unity/README.md)

完整 roadmap 見 [../LIVE2D_AI_AGENT_OS_PLAN.md](../LIVE2D_AI_AGENT_OS_PLAN.md)。
