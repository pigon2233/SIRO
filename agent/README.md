# agent/ - Hermes Agent 整合

> 處理 Hermes Agent 的安裝、設定、驗證。**不處理業務邏輯**（業務邏輯在 `bridge/`）。

---

## 快速開始

### 安裝 Hermes

**Linux / macOS / WSL2**：
```bash
bash agent/install.sh
```

**Windows PowerShell**（官方 install script）：
```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

### 設定 LLM Provider

```bash
hermes setup
```

依照互動指示設定 API key、選擇模型。預設用 Nous Portal，但你也可以選 OpenRouter、Anthropic、OpenAI 等。

或用 `.env`（推薦，gitignored）：
```bash
cp .env.example .env
# 編輯 .env，填入 API key
```

### 驗證安裝

```bash
bash agent/verify.sh
```

這個腳本會跑 5 個檢查：CLI 存在、版本、doctor、單次對話、`.env` 設定。

---

## 為什麼需要這個目錄？

Hermes Agent 是個獨立的 Python 套件，有自己的安裝流程、設定目錄（`~/.hermes/`）、CLI 慣例。SIRO 把它當外部依賴，**所有跟 Hermes 本身的相關東西集中在 `agent/`**，跟業務邏輯（bridge/）分離。

這樣的好處：
- Hermes 升級時，只動這個目錄
- 換成別的 LLM agent 框架時，只改 bridge/ 怎麼 call
- 跨平台差異（Windows / Linux / WSL）的安裝問題在這裡處理

---

## 目錄結構

```
agent/
├── README.md                    ← 本檔
├── install.sh                   ← 呼叫官方 install.sh + SIRO 後處理
├── verify.sh                    ← 驗證 hermes CLI 能用
└── notes/
    └── hermes_api_surface.md    ← 記錄 hermes 實際介面（給未來開發者）
```

---

## 常見問題

### Q: `hermes` 指令找不到

跑過 install.sh 之後，要把 `~/.local/bin` 加進 PATH：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Q: 怎麼確認 hermes 真的能呼叫 LLM？

```bash
hermes -p "說一句你好"
```

如果有輸出文字，代表 LLM 連線正常。

### Q: 怎麼換模型？

```bash
hermes model
```

或編輯 `~/.hermes/.env` 裡的 `HERMES_LLM_MODEL`。

### Q: 怎麼看現在用的是哪個 provider？

```bash
hermes config show  # 或 cat ~/.hermes/.env
```

---

## 相關資源

- [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent 官方文件](https://hermes-agent.nousresearch.com/docs)
- [Hermes API 介面筆記](./notes/hermes_api_surface.md) — 給開發者看的內部文件
