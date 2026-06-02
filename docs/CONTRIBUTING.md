# SIRO 貢獻指南

> 給人類 + AI 助手用的開發指南。
> 重點：**模組化**讓每個 sub-task 都可以獨立委派。

---

## 1. 工作流程概覽

```
[需求 / Issue]
  ↓
[拆解成 Sub-tasks]
  ↓
[AI / 人類實作]
  ↓
[PR + Review]
  ↓
[CI 通過]
  ↓
[Merged]
  ↓
[Phase Demo]
```

---

## 2. 模組結構（為什麼可以獨立委派）

每個模組的**對外介面**是固定的，**內部實作**可以隨意改：

| 模組 | 對外介面 | 內部可改 |
|------|----------|----------|
| `bridge/hermes_client.py` | `HermesClient` class | subprocess → MCP、錯誤處理等 |
| `bridge/emotion_parser.py` | `EmotionParser` class | regex、ML 模型等 |
| `bridge/main.py` | FastAPI routes | 業務邏輯 |
| `os-runtime/crates/siro-runtime/` | gRPC server | 內部實作 |
| `os-runtime/crates/siro-ctl/` | CLI commands | 內部實作 |
| `unity/Assets/Scripts/*.cs` | C# classes | 內部實作 |

**改一個模組，不應該需要改其他模組**（除非介面真的變了）。

---

## 3. 給人類開發者

### 3.1 設定環境

1. 裝 Python 3.11+
2. 裝 Rust 1.80+（Phase 3 之後）
3. 裝 Unity 6 LTS（Phase 2 之後）
4. Clone 倉庫
5. 跑 `bash agent/install.sh`
6. 跑 `bash agent/verify.sh`

### 3.2 開發循環

```bash
# 開新分支
git checkout -b feat/<phase>-<sub-task>

# 開發
# ... 改程式碼 ...

# 測試
cd bridge && python -m pytest tests/ -v
cd os-runtime && cargo test
cd unity && <unity test>

# Commit
git add .
git commit -m "feat(phase-1): add live2d expression mapping"

# Push & PR
git push origin feat/phase-1-live2d-mapping
gh pr create
```

### 3.3 Coding Style

#### Python
- `black` 自動格式化
- `ruff` lint
- 型別 hint 必填
- docstring 必填（公開 function）

#### Rust
- `rustfmt` 自動格式化
- `clippy` lint，沒有 warning
- 公開 API 必填 doc comment

#### C#
- `dotnet format` 自動格式化
- 命名空間：`Siro.*`

#### Shell
- `shellcheck` lint
- 開頭 `set -euo pipefail`
- 函式化（不要一坨）

### 3.4 Commit 規範

[Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type**：
- `feat` — 新功能
- `fix` — bug fix
- `docs` — 文件
- `style` — 格式（不改邏輯）
- `refactor` — 重構
- `test` — 測試
- `chore` — 雜事（build、CI）

**Scope**：
- `phase-1`, `phase-2`, ... — Phase 編號
- `bridge`, `unity`, `runtime`, `os`, `hardware` — 模組
- `docs`, `ci`, `deps` — 其他

**範例**：
```
feat(bridge): add MCP client option for hermes

Allow using MCP client instead of subprocess for hermes.
This enables streaming and tool calls.

Refs: #123
```

---

## 4. 給 AI 助手

### 4.1 好的委派

**好的 prompt**：

```
實作 bridge/hermes_client.py 中的 chat() 方法的串流支援：

需求：
- 新增 method `chat_stream(message, callback)` 回傳 Generator
- callback 收到每個 token（之後要支援 SSE）
- 內部從 subprocess 改用 hermes-acp 的 stream 模式
- 寫單元測試
- 參考 docs/DECISIONS.md 決策 #002

不要改：
- 對外介面（HermesClient class）
- 其他檔案

完成後輸出：
1. 改的檔案清單
2. 測試結果
3. 任何發現的問題
```

**不好的 prompt**：

```
幫我做 hermes 串流
```

### 4.2 每個委派任務的格式

```
【任務】<標題>
【目標】<一句話>
【範圍】
  - 要改的檔案
  - 不要動的檔案
【需求】<具體規格>
【驗收】<怎麼知道做完了>
【參考】<相關文件 / 程式碼>
【輸出】<AI 應該交付什麼>
```

### 4.3 AI 應該做的事

✅ 寫程式（遵循既有 style）
✅ 寫測試
✅ 跑測試確認通過
✅ 檢查 lint
✅ 更新文件（如有需要）
✅ 列出變更的檔案

### 4.4 AI 不應該做的事

❌ 改介面（除非明確同意）
❌ commit / push
❌ 安裝系統套件（sudo）
❌ 跑破壞性指令（rm -rf）
❌ 改其他模組
❌ 改 git config

### 4.5 驗收流程

1. AI 完成任務
2. 開發者看 diff
3. 開發者本地跑測試
4. 開發者 commit / push
5. CI 跑
6. Code review
7. Merge

---

## 5. 模組清單與可委派性

### 5.1 高度可委派（AI 可獨立完成）

- `bridge/hermes_client.py` — 改 subprocess 行為
- `bridge/emotion_parser.py` — 改解析邏輯
- `bridge/prompts.py` — 改 prompt 模板
- `os-runtime/crates/siro-runtime/src/supervisor.rs` — 改監控邏輯
- `os-runtime/crates/siro-runtime/src/hardware/*.rs` — 改硬體偵測
- `os-runtime/crates/siro-ctl/src/commands/*.rs` — 改 CLI 子命令
- `unity/Assets/Scripts/*.cs` — 改 Unity 腳本（除 Animator 設定）
- `docs/*.md` — 改文件
- `os/install/*.sh` — 寫安裝腳本
- `os/systemd/*.service` — 改 unit file

### 5.2 中度可委派（AI 完成、需要人類 review）

- 新模組（要先討論介面）
- 跨模組變更
- 效能改進
- 重構

### 5.3 不適合委派（人類做）

- 最終架構決策
- Unity Editor 操作（場景、Animator）
- 硬體實體改裝
- 安全性敏感變更
- 法律 / 法規相關

---

## 6. 程式碼審查 (Code Review)

### Reviewer Checklist

- [ ] 介面沒變（除非有正當理由）
- [ ] 測試覆蓋
- [ ] 文件更新
- [ ] 無 lint 警告
- [ ] 無 unused code
- [ ] 錯誤處理完整
- [ ] 沒有 hardcoded 密鑰
- [ ] commit message 遵循 conventional commits

### AI 寫的程式碼

- **一定要 review**
- AI 容易：
  - 忽略 edge case
  - 過度設計
  - 寫冗餘註解
  - 假設不存在的套件
  - 抄舊程式碼（可能過時）

---

## 7. 發版流程

### Semantic Versioning

- **0.x.y** — 開發中（v0.1.0 = Phase 1）
- **1.0.0** — 第一個 production-ready
- **x.y+1** — 新功能
- **x.y.z+1** — bug fix

### 發版 Checklist

- [ ] 所有 Phase 內的 issue closed
- [ ] CI 全綠
- [ ] 文件更新
- [ ] CHANGELOG 更新
- [ ] 標 git tag
- [ ] 通知（如果有訂閱者）

---

## 8. 衝突解決

### 程式碼衝突

- 小衝突：開發者自己解
- 大衝突：開會討論
- 永遠以「架構決策」為準

### 設計衝突

- 開 issue 討論
- 用 ADR (Architecture Decision Record) 記錄決定
- 更新 `docs/DECISIONS.md`

---

## 9. 安全漏洞回報

發現安全漏洞：
1. **不要**開 public issue
2. 私訊維護者
3. 給 90 天修復期
4. 修復後再公開

---

## 10. 相關資源

- [Conventional Commits](https://www.conventionalcommits.org/)
- [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Unity Coding Standards](https://docs.unity3d.com/Manual/codingStandards.html)
