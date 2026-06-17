# GAPS #9 降級路徑細化 — 從「bridge 死掉 Mao 變 thinking」到「per-subsystem 精確 UI」

> **對應 GAPS**：[GAPS.md #9 降級路徑（失敗展示）](../../docs/strategic-gaps.md)
> **對應 ADR**：[ADR 0002-subsystem-failure-對話對應.md](../ADR/0002-subsystem-failure-對話對應.md)
> **目標版本**：v0.5+（在 v0.3.0 之上細化）

## 為什麼現在補

Phase 1.5 / 1.75 / 2 加起來的「失敗展示」是「**統一一個狀態**」：

```
bridge 連不上 → 顯示「連線中...」+ Mao 切 thinking 表情
LLM timeout → 顯示「思考中...」+ Mao 切 thinking 表情
LLM 死掉 → Mao 走 persona fallback 文字 + thinking 表情
subsystem X 死掉 → ... 跟上面一樣、Mao 變 thinking
```

問題：**使用者分不出來是 bridge 死、LLM 死、還是 Mao 在想**。
真實情境下，使用者需要知道「**該不該重打一次**」、「**等多久才放棄**」、「**Mao 是真的在思考還是真的掛了**」。

## 設計：6 種 subsystem × 4 種狀態

### 4 種 UI 狀態（v0.5+ 新增）

| 狀態 | UI 顯示 | 表情 | 行為 |
|------|---------|------|------|
| **thinking** | 正常 | thinking | 真的在等 LLM 回應 |
| **waiting** | 正常 | thinking | 等使用者輸入 / 正常運作 |
| **degraded:llm** | 「Mao 走簡化模式中...」 | thinking | LLM 死了、走 persona fallback |
| **degraded:bridge** | 「重新連線中...」 | thinking | bridge 死掉、siro-runtime 自動重啟中 |
| **degraded:hermes** | 「Mao 想了一下...」 | thinking | hermes 掛了、走 ollama fallback |
| **degraded:unity** | （角色從畫面消失） | — | Unity 自己當掉、需手動重啟 |
| **degraded:audio** | （icon 提示） | normal | mic/speaker 沒接好、純文字模式 |
| **degraded:network** | 「離線模式」 | normal | 完全沒網路、本地 LLM 跑 |

### Unity 端 status icon（v0.5+ 規劃）

右上角小 icon、4 種顏色：
- 🟢 green — 全部 subsystem 健康
- 🟡 yellow — 至少 1 個 subsystem degraded、但角色仍能對話
- 🔴 red — 至少 1 個 critical subsystem 死掉、角色不穩
- ⚪ gray — 完全不知道狀態（WS 斷線超過 30s）

點 icon → 展開「subsystem 狀態清單」（bridge / hermes / LLM / Unity / mic / speaker / network）。

### persona dialog 對話話術

當 subsystem 死掉時、Mao 主動告訴使用者：

| 場景 | Mao 講的話（persona 對應）|
|------|---------------------------|
| LLM 死 | 「嗯...我今天有點鈍、講簡單一點」（siro-default）|
| bridge 死（30s 沒回）| 「嗯？我這邊卡住了、讓我看一下...」（自動重啟中）|
| bridge 死（重啟失敗）| 「我需要重啟一下、等 5 秒鐘...」（5s 倒數）|
| hermes 死 | 「我想了一下...」（走 ollama fallback）|
| 沒網路 | 「現在沒網路、我用本地腦袋想」（本地 LLM 跑）|
| mic 壞 | 「我聽不到你說話、可以打字嗎？」|
| speaker 壞 | 「我這邊沒聲音、你看文字就好」|

> 話術在 persona YAML 配（`fallback_dialogs` 段落、v0.5+ 加）：

```yaml
fallback_dialogs:
  llm_down: "嗯...我今天有點鈍、講簡單一點"
  bridge_restarting: "嗯？我這邊卡住了、讓我看一下..."
  bridge_restart_failed: "我需要重啟一下、等 5 秒鐘..."
  hermes_down: "我想了一下..."
  network_offline: "現在沒網路、我用本地腦袋想"
  mic_broken: "我聽不到你說話、可以打字嗎？"
  speaker_broken: "我這邊沒聲音、你看文字就好"
```

## 狀態決策矩陣

| bridge | hermes | LLM | Unity | mic | speaker | network | → 狀態 | UI |
|--------|--------|-----|-------|-----|---------|---------|--------|-----|
| ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | healthy | 🟢 |
| ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | degraded:audio | 🟡 |
| ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | degraded:audio | 🟡 |
| ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | degraded:network | 🟡 |
| ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | degraded:bridge | 🔴 |
| ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | dead | ⚪ |

## 實作計劃

### v0.5.0（短期 1 週）

- [ ] bridge 加 `/health/subsystems` endpoint、回 7 個 subsystem 狀態
- [ ] siro-runtime 推 `system_event` WS 訊息、帶 subsystem + status + reason
- [ ] Unity 端訂 `system_event`、更新 status icon
- [ ] ChatInputUI 顯示「degraded:xxx」時的提示文字
- [ ] persona YAML 加 `fallback_dialogs` 段（siro-default 先寫）

### v0.5.1（1 週後）

- [ ] Mao 表情對應 `degraded:xxx` 各狀態（不只 thinking、可以分難過/疑惑/尷尬）
- [ ] mic/speaker 偵測（v0.4+ hardware 模組補的 audio devices 用起來）
- [ ] network 偵測（定期 ping LLM API）
- [ ] log 過濾 noisy 警告

### v1.0（中期）

- [ ] Unity 端 status icon 完整化（icon sprite + 動畫）
- [ ] user testing 驗證「使用者分得出來哪個 subsystem 壞」（K9 對齊）

## 測試

```python
# tests/bridge/test_subsystem_status.py
async def test_bridge_health_reports_all_subsystems():
    """get /health/subsystems 應該列 7 個 subsystem"""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BRIDGE_URL}/health/subsystems")
        assert r.status_code == 200
        body = r.json()
        assert set(body["subsystems"].keys()) == {
            "bridge", "hermes", "llm", "unity", "mic", "speaker", "network"
        }
        for s in body["subsystems"].values():
            assert s["status"] in ("healthy", "degraded", "down")
```

## 對應的 K9 驗證（5歲到80歲會用）

v2.0 啟動 user testing 時，特別驗證：
- 「如果 Mao 不回你、你知道要等還是該重打嗎？」
- 「如果 Mao 變奇怪（fallback 模式）、你知道是 Mao 變了還是系統壞了嗎？」

如果 v0.5 還沒做，user testing 會發現這是痛點、那時趕快補。

## 相關文件

- [GAPS.md #9](../../docs/strategic-gaps.md) — 原始 gap 描述
- [ADR 0002](../ADR/0002-subsystem-failure-對話對應.md) — 12 個 subsystem × Unity UX × persona dialog 對應表
- [LIVE2D_AI_AGENT_OS_PLAN.md §8 風險登記](LIVE2D_AI_AGENT_OS_PLAN.md) — R3 (降級路徑)
- [LIVE2D_AI_AGENT_OS_PLAN.md §11 使用者驗證](LIVE2D_AI_AGENT_OS_PLAN.md) — K9 對齊

---

**最後一句話**：

降級路徑是「**SIRO 對真實世界的應對**」 — 不是技術問題、是 UX 設計問題。
做對了、Mao 真的感覺「活著」、做錯了、Mao 變「會當機的 app」。
