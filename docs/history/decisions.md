# SIRO 設計決策紀錄

> 記錄 SIRO v0 的重要設計決策，以及「為什麼這樣選」。
> 當未來要改設計時，先看這份確認當時為什麼這樣選。

---

## 決策 #001 — 為什麼用 Hermes Agent 當核心大腦

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) LangChain + 自己組 agent
- B) LlamaIndex Agents
- C) Hermes Agent (Nous Research)
- D) 自己寫

**選 C 的原因**：
- 開箱即用：CLI、gateway、記憶、技能系統都內建
- 不鎖 LLM：支援 300+ 模型
- MIT 授權
- 維護活躍（176k stars）

**取捨**：
- ❌ 沒對外 HTTP API — 必須用 subprocess 或 MCP
- ❌ 介面可能隨版本變動
- ✅ 之後要換：只需改 `bridge/hermes_client.py`，業務邏輯不動

---

## v0.2 觀察（2026-06-04）

**v0.2 用了 Hermes 一個月，發現什麼**：

### 觀察 1 — Streaming 限制（影響體驗）

- Hermes CLI 一次返回完整 response、**不支援 token-by-token streaming**
- 實測延遲（v0.2 MiniMax-M3 雲端 LLM）：
  - TTFT（Time To First Token）：5-8 秒（雲端 LLM 現實）
  - 完整生成：18-20 秒
  - 給使用者感覺「按下去要等 1 分鐘」
- 這違反 v0.1 願景「即時互動」

### 觀察 2 — 鎖定代價浮現

- 起初以為「換 LLM provider 簡單」（決策 #001 寫的「不鎖 LLM」）
- 但實際上是「換 LLM 呼叫方式**難**」 — subprocess 介面本身就是鎖定
- 想加 streaming，三條路：
  - A) 繞過 hermes、直接打 MiniMax-M3 HTTP API（1 天實作）
  - B) 升級到 MCP（協議複雜度上升）
  - C) 接受現狀
- 詳見 `docs/STRATEGIC_NOTES.md` Q2 結論

### 觀察 3 — 改用 hermes 介面 streaming（2026-06-04 決定）

- commit 7aa135b 結論：**走 hermes 介面 streaming、不繞過 hermes**
- 理由：保留 hermes 的「LLM provider 抽象」優勢、用 hermes 的 streaming 介面
- 修正後取捨：streaming 還是可以達到（透過 hermes 介面）、但成本是要多寫一層 hermes_client 包裝
- 觀察 1 的體驗問題要等這層寫完才能驗證

### 修正 #001 的「取捨」

原本寫的：
- ❌ 沒對外 HTTP API
- ❌ 介面可能隨版本變動
- ✅ 之後要換：只需改 `bridge/hermes_client.py`

v0.2 後的修正：
- ❌ 沒原生 streaming（要透過 hermes 介面包裝）
- ❌ 介面可能隨版本變動（驗證：hermes 0.15.2 → 0.x 介面有 breaking change 過一次）
- ✅ 換 LLM provider 仍簡單（hermes 抽象）
- 🟡 換「呼叫方式」成本高（要看 hermes 有沒有對應介面）

### 後續觀察

- 等 hermes_client streaming 寫完，再來更新本節
- 如果 hermes 介面又 breaking change，要記錄具體影響
- 持續追蹤 MiniMax-M3 API 直連的成本（如果 < 半天實作就值得繞過）

---

## 決策 #002 — 為什麼 v0 用 subprocess 而不是 MCP

**日期**：2026-06-02
**狀態**：採用

**問題**：bridge 要怎麼跟 Hermes 通訊？

**選項**：
- A) subprocess 跑 `hermes -p "message"`
- B) MCP client 連 `mcp_serve.py`
- C) 改 Hermes 源碼加 HTTP API

**選 A 的原因**：
- v0 範圍只需要「單次問答」，subprocess 夠用
- 不需要懂 MCP 協議
- 失敗時容易 debug（直接看 subprocess 輸出）
- 介面契約簡單：input = string, output = string

**升級觸發**：
- 開始需要串流（token by token 輸出）→ 換 B
- 開始需要 tool call / subagent → 換 B
- Hermes 介面變動導致 subprocess 不穩 → 換 B

**如何升級**：改 `bridge/hermes_client.py`，其他檔不動。

---

## 決策 #003 — 為什麼需要 Bridge（而不是 Unity 直接打 Hermes）

**日期**：2026-06-02
**狀態**：採用

**問題**：Unity 可不可以直接 call Hermes，跳過 Bridge？

**答案**：不行，三個原因：

1. **語言障礙**：Hermes 是 Python，Unity C# 沒辦法直接 import
2. **PTY 需求**：Hermes TUI 模式需要 pseudo-terminal，subprocess 在 Windows 上很難處理
3. **業務邏輯集中**：情緒解析、session 管理、prompt 注入都該在 server side

**Bridge 的最小職責**：
- 把 Hermes 的 string 介面包成 WebSocket/HTTP
- 解析情緒標籤
- 注入 system prompt
- 記 session

**未來可能加**：
- STT/TTS pipeline
- Honcho 整合
- Token 用量統計
- Rate limiting

---

## 決策 #004 — 為什麼用 FastAPI + WebSocket

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) FastAPI + WebSocket
- B) Flask + Socket.IO
- C) Django Channels
- D) gRPC

**選 A 的原因**：
- FastAPI 簡單，async 原生
- WebSocket 適合即時情緒推播（比 HTTP 輪詢好）
- 客戶端 SDK 簡單（瀏覽器、Unity、Node 都有 WebSocket 函式庫）
- 之後要加 streaming HTTP（SSE）也容易

**v0 不做的**：
- 串流（subprocess 跑完才回，不是 stream token by token）
- HTTP/2

---

## 決策 #005 — 為什麼用 Unity + Cubism SDK（不是 Tauri 或純 Web）

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) Unity + Cubism SDK
- B) Tauri + Cubism Web Framework
- C) 純 Web (瀏覽器全螢幕)
- D) Electron + Cubism Web Framework

**選 A 的原因**：
- Cubism SDK for Unity 是 Live2D 官方最完整支援
- 之後加複雜功能（人臉追蹤、口型動畫、shader effects）最容易
- Unity Asset Store 與社群資源多
- Windows / macOS / Linux 都支援

**取捨**：
- ❌ Build size 大（~1GB）
- ❌ 開發需要 Unity Editor
- ❌ v0 階段 setup 比較重

**如果未來要降複雜度**：
- Web 展示型 prototype → 換 B 或 C
- 多平台發布 → 維持 A

---

## 決策 #006 — 為什麼 v0 用 Hiyori（不用自製模型）

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) Live2D 官方 Hiyori 範例
- B) 自製 / 委託繪師做
- C) 從素材網站買

**選 A 的原因**：
- 免費、可商用（檢查授權邊界）
- 開箱即用，expression/motion 完整
- 社區教學資源多（如何觸發 F01-F06）

**升級觸發**：
- 角色個性需要跟計畫書匹配（v1+）
- 角色要中文配音口型（v2+）
- 硬體載體有特殊設計需求（v2+）

**自製時的注意事項**：
- Cubism Editor 學習曲線
- 表情（expression）拆解要設計好，影響後續動畫切換
- 授權問題要查清楚

---

## 決策 #007 — 為什麼情緒偵測用 LLM 自己輸出標籤（不做 NLP）

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) 訓練情緒分類模型
- B) 用 LLM API 額外做情緒分類
- C) LLM 自己輸出 `[emotion:xxx]` 標籤 + regex 解析
- D) 用現成的情緒分析 API（如 AWS Comprehend）

**選 C 的原因**：
- 零額外成本（不呼叫額外 LLM/API）
- 延遲低（不增加 LLM 呼叫）
- 規則簡單（regex 解析 + 關鍵字備援）
- LLM 本來就懂情緒，不需要再訓練模型

**風險**：
- LLM 不一定每次都乖乖加標籤 → system prompt 強制要求
- LLM 選的標籤可能太單一（總是 neutral）→ prompt 給明確對應規則

**備援**：
- 沒標籤 → 用關鍵字比對
- 標籤無效 → 退回 neutral

---

## 決策 #008 — 為什麼 session 暫存在記憶體（不做持久化）

**日期**：2026-06-02
**狀態**：採用

**問題**：對話歷史要存在哪？

**選項**：
- A) 記憶體（dict）
- B) SQLite 本地檔
- C) Honcho 服務
- D) 雲端資料庫

**選 A 的原因**：
- v0 範圍是「能跑通」，不是「能記住」
- 零基礎設施成本
- 重啟 Bridge 等於清空 session（明確的 v0 行為）
- 之後要升級 → 改 `main.py` 的 `state.sessions` 邏輯

**升級觸發**：
- 開始需要跨 session 記憶（Honcho）
- 需要對話歷史查詢
- 多使用者

---

## 決策 #009 — 為什麼 7 種情緒（不是 50 種）

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) 4 種（happy/sad/angry/neutral）— Ekman 基礎
- B) 7 種（加 surprised/thinking/excited）
- C) 20+ 種（含羞愧、嫉妒、期待、困惑等）
- D) 連續情緒空間（valence + arousal 二維）

**選 B 的原因**：
- 覆蓋 80% 場景，避免 enum 爆炸
- 對應 Hiyori 模型的 F01-F06 expression（5-6 種實際可用）
- 之後要加細粒度情緒 → 改 `emotion_mapping.json` 跟 Cubism expression 數量

**升級路徑**：
- 中期：加 valence/arousal 二維，mapping 到 expression 強度
- 長期：訓練自訂 expression 集，支援微表情

---

## 決策 #010 — 為什麼不做 v0 的視覺/音訊輸入

**日期**：2026-06-02
**狀態**：採用

**明確排除 v0 範圍**：

- **STT**（語音轉文字）：要先選 STT provider（Whisper / ElevenLabs / Azure），加音訊設備管理，debug 成本高
- **TTS**（文字轉語音）：同上，還要處理音訊串流播放
- **人臉追蹤**：要 OpenCV / MediaPipe 整合，計算量
- **口型動畫**：要 audio-to-viseme mapping
- **眼神追隨**：要 3D 座標計算

**v0 只做最純粹的「文字 → LLM → 文字 + 表情」鏈路**，驗證整個架構可運作後再一層層加。

**加功能的順序**（在 [LIVE2D_AI_AGENT_OS_PLAN.md](../LIVE2D_AI_AGENT_OS_PLAN.md) 有 v0.5+ 規劃）：
1. v0.5: TTS（先輸出聲音）
2. v0.5: STT（再輸入聲音）
3. v1: 人臉追蹤 + 眼神
4. v1: 口型動畫

每加一個都要驗證鏈路穩定 1-2 週才進下一個。

---

## 之後怎麼用這份文件

- 開新功能前先看，確認不違反現有決策
- 推翻決策時，更新「狀態」為「撤銷」+ 寫新決策
- 用 `決策 #XXX` 編號方便引用

---

# v2.0 新增決策（2026-06-02 重構）

v2 重新評估整體架構，新增以下決策。

---

## 決策 #011 — 為什麼分層用 Python + Rust

**日期**：2026-06-02
**狀態**：採用

**問題**：SIRO 包含 AI 邏輯、系統服務、視覺呈現，要用什麼語言？

**決定**：
- AI 邏輯（bridge/）— **Python**
- 系統服務（os-runtime/）— **Rust**
- 視覺呈現（unity/）— **C#**

**為什麼不全部用 Python**：
- ❌ 24/7 跑的 daemon 不適合 Python（GC 暫停、memory overhead、依賴管理複雜）
- ❌ 系統服務要快速啟動、低資源佔用
- ❌ 硬體控制用 Python 不便

**為什麼不全部用 Rust**：
- ❌ LLM SDK、生態 Python 完勝
- ❌ AI 整合需要快速迭代
- ❌ Rust 對 prompt engineering 工具鏈不友善

**為什麼不全部用 Go**：
- Go 也是選項之一，但 Rust 在 system programming 領域更強
- Go 有 GC（雖然短），Rust 完全無 GC

**分界線**：
- 變動多、迭代快、需要生態 → Python
- 穩定要求、效能要求、底層 → Rust
- UI、動畫 → C# (Unity)

**升級觸發**：
- Python 變成瓶頸 → 把部分邏輯移 Rust（透過 gRPC 介接）
- Rust 拖累開發速度 → 評估用 Go 重寫部分

---

## 決策 #012 — 為什麼 OS 層選 Rust 不選 Go

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) Rust
- B) Go

**選 A 的原因**：
- ✅ 零 runtime、零 GC 暫停（24/7 daemon 重要）
- ✅ 記憶體安全（編譯期保證，沒有 segfault）
- ✅ tokio async 成熟
- ✅ 跨編譯友善（之後給 Pi 部署用）
- ✅ 與 systemd 整合完善（sd-notify crate）
- ✅ 直接 syscalls，硬體控制方便

**Go 的優勢但這次不選**：
- ✅ 開發速度更快
- ✅ goroutine 簡潔
- ✅ 也單一二進位

**選 Rust 的關鍵因素**：
- 24/7 daemon 不能有 GC 暫停（會影響 systemd watchdog）
- 記憶體安全對生產環境重要
- 之後要 cross-compile 到 ARM（Pi）
- Rust 對 cpal/v4l2/wayland 等 crate 支援完整

**升級觸發**：
- Rust 開發速度真的卡住 → 評估混合（Go 寫工具，Rust 寫 daemon）

---

## 決策 #013 — 為什麼 Bridge ↔ Runtime 用 gRPC，不直接用 HTTP

**日期**：2026-06-02
**狀態**：採用

**問題**：Layer 2 (Python bridge) 跟 Layer 3 (Rust runtime) 怎麼通訊？

**選項**：
- A) HTTP REST
- B) gRPC
- C) Unix socket + 自訂 protocol
- D) Message queue (Redis, RabbitMQ)

**選 B 的原因**：
- ✅ 強型別（proto 檔是 source of truth）
- ✅ 雙向串流（之後 log streaming 用）
- ✅ 跨語言原生支援（Python + Rust 都有官方 lib）
- ✅ 內建 deadline、cancellation
- ✅ 工具鏈完善（grpcurl、grpcui 可 debug）
- ✅ 之後加版本控制容易（`package siro.runtime.v1;`）

**為什麼不選 A（HTTP）**：
- ❌ 沒強型別
- ❌ 串流要 SSE 自己搞
- ❌ 兩個 client 各自解析 JSON，難對齊

**為什麼不選 C（Unix socket）**：
- ❌ 自訂 protocol 維護成本高
- ❌ 跨語言要自己寫 codec
- ✅ 優點是 low latency，但對 SIRO 規模 overkill

**proto 檔位置**：
- `os-runtime/proto/siro.proto` — source of truth
- Bridge 與 Runtime 都從這裡生成程式碼

**升級觸發**：
- gRPC overhead 太大（不太可能）→ 換 C
- 簡化需求只做健康檢查 → 換 A

---

## 決策 #014 — 為什麼 v0.5 / v1 留在 Windows 開發，Phase 4 才裝 Linux

**日期**：2026-06-02
**狀態**：採用

**問題**：什麼時候把開發機從 Windows 改成 Linux？

**決定**：
- v0 / v1 / v2 / v3 (Phase 1-3) — 都在 Windows 開發
- v3 結束後（Phase 3 done）才裝 Linux

**為什麼不早點裝**：
- Unity Editor 在 Windows 比較穩定
- 開發工具（VS Code / Cursor）Windows 也 OK
- Rust / Python 都跨平台，Windows 也能寫
- 太早裝 Linux 會拖慢 v0 開發

**為什麼不能永遠 Windows**：
- Unity Linux build 跟 Windows build 行為不同
- systemd / udev 一定要 Linux
- NVIDIA Optimus Linux 設定複雜，要時間
- 最終用戶體驗是 Linux，遲早要面對

**Phase 4 規劃**：
- 雙系統（保留 Windows）
- 先在 Linux 環境跑 v3 的 siro-runtime
- 之後所有體驗在 Linux

**升級觸發**：
- 想要更多 Linux 工具（Wireshark for Unity traffic）→ 早點裝
- Windows 硬體問題 → 提早切

---

## 決策 #015 — 為什麼選 Ubuntu Server 24.04 LTS（不是 Desktop / 其他發行版）

**日期**：2026-06-02
**狀態**：採用

**選項**：
- A) Ubuntu Server 24.04 LTS
- B) Ubuntu Desktop 24.04 LTS
- C) Debian 12 (Bookworm)
- D) Fedora Server
- E) Arch Linux
- F) NixOS
- G) 客製化（Yocto / Buildroot）

**選 A 的原因**：
- ✅ LTS 5 年支援（到 2029）
- ✅ 套件多、文件多、社群大
- ✅ NVIDIA 官方支援最佳
- ✅ snap 對 CUDA / 第三方套件友善
- ✅ 預設是 server（沒 desktop 累贅）
- ✅ systemd 標準

**為什麼不選 B（Desktop）**：
- 預裝 GNOME，要手動移除
- 桌面服務佔資源
- 反正最後要 kiosk 模式，不如直接 server

**為什麼不選 C（Debian）**：
- 套件比 Ubuntu 舊一點
- NVIDIA driver 不在官方 repo（要加 non-free）

**為什麼不選 F（NixOS）**：
- 學習曲線
- v0/v1 不需要 declarative 優勢
- 之後評估

**為什麼不選 G（客製化）**：
- v0 不需要
- Build chain 維護成本高

**升級觸發**：
- 之後要量產、需要 declarative config → 考慮 NixOS
- 需要更精簡 image → 考慮 Yocto
- 預算 / 時程允許 → 重新評估

---

## 決策 #016 — 為什麼本機預設用 Llama 3.2 3B Q4（不是 7B）

**日期**：2026-06-02
**狀態**：採用

**問題**：本機 LLM 預設跑哪個模型？

**硬體限制**：RTX 3050 4GB VRAM

**選項**：
- A) Llama 3.2 1B Q4 — 1.5GB VRAM
- B) Llama 3.2 3B Q4 — 2.5GB VRAM ✅ 推薦
- C) Mistral 7B Q4 — 5GB VRAM（會 OOM）
- D) Mistral 7B Q2 — 3.5GB VRAM（勉強）
- E) Phi-3 Mini 3.8B Q4 — 3GB VRAM
- F) 雲端 LLM API

**選 B 的原因**：
- ✅ 品質夠用（中文 / 英文都 OK）
- ✅ 跑得動（4GB VRAM 內）
- ✅ 推論快（< 3 秒回應）
- ✅ Llama 3.2 家族穩定

**其他選項評估**：
- A：品質較差，但可以作為 fallback
- C/D：會 OOM 或勉強，不推薦
- E：品質不錯，可以替代
- F：品質好但要付費

**設定**：
```bash
ollama pull llama3.2:3b-instruct-q4_0
```

**升級觸發**：
- 換顯卡（VRAM 8GB+）→ 升級到 7B Q4
- 想要更好品質 → 走雲端
- 需要更快回應 → 用更小模型

---

## 決策 #017 — 為什麼用 Kismet / Catch-all YAML 而不是靜態配置

**日期**：2026-06-02
**狀態**：採用

> 註：這個決策被撤銷，因為我們選 figment + TOML 而非 YAML。

撤銷詳情見 [PR #XXX](https://github.com/pigon2233/SIRO/pull/XXX)。

實際選 figment + TOML（見 Cargo.toml 註解）。

---

## 決策 #018 — 為什麼 OS Runtime 拆成多個 crate（一個 binary 也可以）

**日期**：2026-06-02
**狀態**：採用

**問題**：`siro-runtime` 要全部寫在一個 binary 還是拆 crate？

**決定**：拆成多個 crate：
- `siro-ipc`（共用 types）
- `siro-runtime`（主 daemon）
- `siro-ctl`（CLI）
- 之後可能加：`siro-supervisor`、`siro-hardware`、`siro-kiosk`

**為什麼拆**：
- ✅ 編譯時間：改一個 crate 不會全部重編
- ✅ 測試：可以單獨測某個 crate
- ✅ 重用：`siro-ipc` 可被 bridge 用（透過 generated code）
- ✅ 學習：每個 crate 範圍小，新人易上手
- ✅ workspace 共用 dependency，版本一致

**為什麼不寫單一 binary**：
- ❌ 編一個小改動要 5 分鐘
- ❌ 測試全混在一起
- ❌ binary 變大

**trade-off**：
- ❌ 程式碼分散，要切換資料夾
- ❌ 介面要小心設計

**升級觸發**：
- 真的不需要拆 → 合併
- 之後加更多 daemon → 繼續拆

---

## 決策 #019 — 為什麼目標硬體是「現在這台筆電」（不是另買新機）

**日期**：2026-06-02
**狀態**：採用

**硬體**：ASUS ROG Strix G713QC (Ryzen 9 5900HX + RTX 3050 4GB + 16GB RAM)

**選項**：
- A) 用現有筆電
- B) 另買新機（Intel NUC / Mac Mini / Raspberry Pi）
- C) 用雲端 VM

**選 A 的原因**：
- ✅ 零成本
- ✅ 已經熟悉硬體
- ✅ 顯卡可以跑小模型
- ✅ 之後 Phase 6 部署時可以參考（同一型號買多台）

**為什麼不選 B**：
- ❌ 另買要花錢（NT$30,000+）
- ❌ 學習新硬體要時間
- ❌ 換硬體可能發現相容性問題

**為什麼不選 C**：
- ❌ 網路延遲影響體驗
- ❌ 雲端費用
- ❌ 隱私疑慮

**限制**：
- 4GB VRAM 不能跑大模型
- 16GB RAM 對 LLM 推論略小
- 筆電風扇可能吵

**緩解**：
- 用 3B Q4 模型
- Phase 5 改散熱
- 之後部署到親友再買好一點的

**升級觸發**：
- 顯卡壞了 → 必須買新機
- 想跑大模型 → 升級硬體

---

## 決策 #020 — 為什麼 Phase 6 暫不做完整 OTA（先手動更新）

**日期**：2026-06-02
**狀態**：採用

**問題**：要不要做完整 OTA 更新系統？

**決定**：v0.5 之前不做完整 OTA，用：
- 開發者手動 ssh 進去更新
- 或 USB 隨身碟更新

**為什麼不做**：
- ❌ OTA 系統複雜（A/B partition、簽章、rollback）
- ❌ 2-10 台 fleet 不需要（手動也行）
- ❌ v0/v1 階段不該花時間在 OTA

**Phase 6 簡化版 OTA**：
- 一個 bash script + 簽章
- 從 server 下載 tarball
- 套用 + 重啟服務
- 不做 A/B partition（接受失敗要手動修）

**升級觸發**：
- 部署到 10+ 台 → 做完整 OTA
- 有人裝在遠端（無法實體 access）→ 必須 OTA
- 出過磚機事件 → 投資 A/B partition

