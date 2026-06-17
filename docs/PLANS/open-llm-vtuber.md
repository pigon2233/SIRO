# Open-LLM-VTuber Feature Parity Plan

> **SIRO × Open-LLM-VTuber 差距補完計畫** — 把 SIRO 缺少的 Open-LLM-VTuber 功能補上(從 v1.0 demo 到 v2.0 完整度)
>
> **結構**:19 個 sub-feature 分 P0/P1/P2 三級。每個都附 **Open-LLM-VTuber 參考檔案(file:line)** + **SIRO 整合點** + **驗證方式**
> **可參考的源碼位置**:`C:\Users\jason\AppData\Local\Temp\vtuber-ref\`(已 clone,可直接讀)
> **SIRO 整合點位置**:`C:\coconut chennel\SIRO\`
> **產出時間**:2026-06-17

## Related Docs

- [GAPS.md](strategic-gaps.md) — 戰略層級的 10 個關鍵 gap(本文件的戰略對應)
- [ARCHITECTURE.md](ARCHITECTURE.md) — 4 層架構(Python bridge / Rust runtime / Linux / Unity)
- [STT_INTEGRATION.md](../integration/stt.md) — Phase 2 STT 設計書,已從 Open-LLM-VTuber 借鑑 4 patterns
- [TTS_INTEGRATION.md](../integration/tts.md) / [TTS_F5_INTEGRATION.md](../integration/tts-f5.md) — TTS 4-tier 架構
- [PERSONA.md](PERSONA.md) — persona YAML schema
- [LIVE2D_AI_AGENT_OS_PLAN.md](../LIVE2D_AI_AGENT_OS_PLAN.md#95-關鍵-open-source-參考) — 主計畫書的 Open-LLM-VTuber 參考段

---

## Context — 為什麼需要這個 plan

上一輪分析已盤點出 SIRO 在 Live2D 周邊生態(視覺、group chat、MCP、多語 TTS、直播串流)明顯落後 Open-LLM-VTuber。SIRO 的強項(Rust runtime、15 個 first-party tools、SQLite WAL、confirmation broker、VAD pre-buffer)對方沒有,但**橫向覆蓋度**(LLM/STT/TTS provider 數量、視覺感知、interrupt 完整度)SIRO 遠遠落後。

這個 plan 要把差距補上,讓 SIRO 不只是「有 Rust runtime 的單人 chatbot」,而是「有完整 Live2D 周邊 + 安全護欄 + 作業系統整合」的開源 VTuber 系統。

**實作順序建議**:P0-1 (MCP) → P0-2 (vision) → P0-3 (handle_interrupt) → P0-4 (TTS translation) → P0-5 (web tool) → P1-1 (group chat) → P1-2 (LLM providers) → P1-3 (TTS providers) → P1-4 (STT providers) → P1-5 (proactive speak) → P1-6 (desktop pet) → P1-7 (BiliBili) → P2(全部)。每個 P0 完成都要過一次 K2/K5 KPI 確保沒 regression。

---

## 全文件閱讀指南

**檔案路徑標記規則**:
- `vtuber/...` = `C:\Users\jason\AppData\Local\Temp\vtuber-ref\src\open_llm_vtuber\...`(Open-LLM-VTuber 源)
- `siro/...` = `C:\coconut chennel\SIRO\...`(SIRO 專案根)

**整合點摘要**(每個 feature 都會用到):
- HTTP/WS route: `siro/bridge/main.py:865-2433` 註冊新路由;`bridge/main.py:2267-2426` 加新 WS 訊息 type
- 工具註冊: `siro/bridge/tools/__init__.py:68-200`
- LLM client: `siro/bridge/minimax_streaming_client.py`(參考架構)
- 設定檔: `siro/bridge/personas/siro-default.yaml` + `siro/bridge/prompts.py:333`
- Unity 端: `siro/SiroUnity/Assets/Scripts/HermesBridgeClient.cs:641-786`(WS 訊息 dispatch)
- 測試 fixture: `siro/tests/bridge/conftest.py:26-58`

---

# P0 — 5 個必須補(v1.0 demo 前)

## P0-1: MCP 整合(讓 SIRO 用得到別人的 MCP server)

**目標**:SIRO 15 個 first-party tools 之餘,還能讀 `mcp_servers.json` 動態載入外部 MCP server(ddg-search、mcp-server-time 等),tool_use 走同一條 `bridge/tools/__init__.py:execute_tool_call` 路徑。

**參考檔案**(從 `C:\Users\jason\AppData\Local\Temp\vtuber-ref\`):
- `src/open_llm_vtuber/mcpp/server_registry.py:13-103` — `ServerRegistry` class 完整實作
- `src/open_llm_vtuber/mcpp/mcp_client.py:17-166` — `MCPClient` stdio transport + `AsyncExitStack`
- `src/open_llm_vtuber/mcpp/tool_adapter.py:11-232` — `ToolAdapter.get_tools()` 產 OpenAI + Claude + prompt-mode schema
- `src/open_llm_vtuber/mcpp/tool_executor.py:18-382` — `ToolExecutor.execute_tools()` async iterator
- `src/open_llm_vtuber/mcpp/json_detector.py:6-136` — `StreamJSONDetector` 給 prompt-mode 用
- `src/open_llm_vtuber/mcpp/types.py:7-93` — `MCPServer`, `FormattedTool`, `ToolCallObject` dataclass
- `mcp_servers.json:1-12` — 設定檔範例
- `src/open_llm_vtuber/service_context.py:95-188` — `_init_mcp_components` wiring 模板

**SIRO 整合點**:
- **新建** `siro/bridge/mcp/__init__.py`、`server_registry.py`、`mcp_client.py`、`tool_adapter.py`、`tool_executor.py`、`json_detector.py`、`types.py`(直接 port vtuber 的)
- **修改** `siro/bridge/main.py:421-565`(lifespan)加 `state.mcp_client = MCPClient(...)`、背景 task keep alive
- **修改** `siro/bridge/main.py:1631-1888`(`_process_ws_chat` 的 tool calling 路徑)把 `chat_stream_with_tools` 串到 MCP tool executor
- **修改** `siro/bridge/tools/__init__.py:153`(`execute_tool_call`)在 `mcp_` prefix 時 route 到 MCP
- **新增** `siro/mcp_servers.json`(預設 ddg-search + time)
- **新增** `siro/bridge/requirements.txt` 加 `mcp>=1.15.0`

**估時**:L(3-4 天,要處理 stdio 進程生命週期 + asyncio 整合)

**驗證**:
```python
# tests/bridge/test_mcp.py
async def test_load_ddg_search():
    state.mcp_client = MCPClient(...)
    tools = await state.mcp_adapter.get_tools(["ddg-search"])
    assert "ddg-search.search" in [t["name"] for t in tools["openai"]]
```
E2E:在 Unity 對角色說「幫我查 X」,LLM call ddg-search,結果正確回傳。

---

## P0-2: 視覺感知(camera/screen → LLM vision)

**目標**:角色可以「看見」使用者鏡頭、螢幕、剪貼簿圖片,把 base64 image 送進 LLM 對話。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/agent/input_types.py:6-94` — `ImageSource` enum + `ImageData` + `BatchInput` 完整 schema
- `vtuber/src/open_llm_vtuber/agent/agents/basic_memory_agent.py:242-288` — `_to_messages` 注入 `image_url` block
- `vtuber/src/open_llm_vtuber/agent/stateless_llm/claude_llm.py:43-82` — `_convert_message_format` 把 `image_url` 轉 Anthropic base64
- `vtuber/src/open_llm_vtuber/websocket_handler.py:48-58` — `WSMessage.images: Optional[List[str]]` 欄位
- `vtuber/src/open_llm_vtuber/conversations/conversation_handler.py:65-72` — `handle_conversation_trigger` 抓 `data.get("images")`
- `vtuber/src/open_llm_vtuber/conversations/conversation_utils.py:20-42` — `create_batch_input` 從 dict 還原 `ImageData`

**SIRO 整合點**:
- **修改** `siro/bridge/models.py:1-197` — 新增 `ImageSource` enum + `ImageData` model,加進 `ChatRequest.images: Optional[List[ImageData]]`
- **修改** `siro/bridge/main.py:1540-1708`(`_process_ws_chat` agent 路徑)把 `ChatRequest.images` 餵進 `MiniMaxStreamingClient._call_api_collect`
- **修改** `siro/bridge/minimax_streaming_client.py:728`(`_call_api_collect`)加 image_url 注入(Anthropic protocol 直接支援,Ollama 不支援就 skip)
- **新增** WS 訊息 type `image_data` in `siro/bridge/main.py:2267-2426`
- **新增** `siro/SiroUnity/Assets/Scripts/CameraCapture.cs` + `ScreenCapture.cs` — 用 `WebCamTexture` + `ScreenCapture.CaptureScreenshotAsTexture()` 週期性抓 frame,base64 編碼送 WS
- **修改** `siro/SiroUnity/Assets/Scripts/HermesBridgeClient.cs:641-786` — 加 `case "image_data":` 接收 server 端 trigger(可選,大多數情況是 client 主動推)

**估時**:L(4-5 天,Unity 端 camera API + base64 編碼 + vision LLM 測試)

**驗證**:Unity 開啟鏡頭 → 對角色說「這是什麼?」→ LLM 收到 image block 回答。

---

## P0-3: handle_interrupt 訊息改寫(history 不會斷)

**目標**:使用者打斷 AI 時,把聽到的半句存進 history,標 `[Interrupted by user]`,LLM 下次對話知道被打斷。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/agent/agents/agent_interface.py:31-43` — abstract `handle_interrupt(heard_response)`
- `vtuber/src/open_llm_vtuber/agent/agents/basic_memory_agent.py:195-223` — 完整實作(rewrite `_memory[-1]` + append sentinel)
- `vtuber/src/open_llm_vtuber/conversations/conversation_handler.py:112-143` — `handle_individual_interrupt`(cancel task + call agent.handle_interrupt + store_message)
- `vtuber/src/open_llm_vtuber/websocket_handler.py:369-392` — `_handle_interrupt` 接收 WS `interrupt-signal`
- `vtuber/src/open_llm_vtuber/agent/agents/basic_memory_agent.py:47` — `interrupt_method: Literal["system", "user"]` 預設 `"user"`

**SIRO 整合點**:
- **修改** `siro/bridge/conversation.py`(`TurnManager` class)加 `handle_interrupt(heard_response: str) -> None`,改寫 `TurnManager._current_turn.memory` 結構(目前 SIRO 沒有 in-memory agent 結構,要先設計 `TurnMemory` 資料類)
- **新建** `siro/bridge/agent_memory.py` — 抽象 `AgentMemory` Protocol + `SQLiteBackedMemory` 實作
- **修改** `siro/bridge/main.py:2300, 2334`(`agent_interrupt` 已發但目前只丟 WS 訊息)加 interrupt logic 呼叫 `turn_manager.handle_interrupt(last_heard)`
- **修改** `siro/bridge/main.py:1631-1708`(chat 路徑)interrupt 後 LLM 重啟時把 `[Interrupted by user]` 加進 system prompt
- **修改** `siro/SiroUnity/Assets/Scripts/UnityTTSPlayer.cs`(`_activeRefAudio` 等附近)記錄 last_heard 給 WS 回傳

**估時**:M(2 天,主要是設計 `AgentMemory` 介面 + SQLite schema 擴充)

**驗證**:
```python
# tests/bridge/test_handle_interrupt.py
async def test_interrupt_rewrites_memory():
    mem = AgentMemory()
    mem.add_assistant("今天天氣真好,我們去")
    mem.handle_interrupt("今天天氣真好,我們去...")
    messages = mem.snapshot()
    assert messages[-2]["content"] == "今天天氣真好,我們去..."
    assert "[Interrupted by user]" in messages[-1]["content"]
```

---

## P0-4: TTS 翻譯輸出(中文對話 → 日文/英文語音)

**目標**:LLM 用中文回答,但 TTS 用日文/英文唸出(角色用外語語音講中文稿)。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/translate/translate_interface.py:1-9` — `TranslateInterface` ABC
- `vtuber/src/open_llm_vtuber/translate/translate_factory.py:1-26` — `TranslateFactory.get_translator`
- `vtuber/src/open_llm_vtuber/translate/deeplx.py:7-28` — `DeepLXTranslate` 完整實作(28 行)
- `vtuber/src/open_llm_vtuber/translate/tencent.py:13-121` — `TencentTranslate` 完整 TC3-HMAC-SHA256(122 行)
- `vtuber/src/open_llm_vtuber/conversations/conversation_utils.py:84-113` — `handle_sentence_output` 翻譯 hook
- `vtuber/src/open_llm_vtuber/config_manager/tts_preprocessor.py:9-118` — `TranslatorConfig` Pydantic model

**SIRO 整合點**:
- **新建** `siro/bridge/translate/__init__.py`、`translate_interface.py`、`translate_factory.py`、`deeplx.py`、`tencent.py`(直接 port)
- **修改** `siro/bridge/tts/stream.py:120`(`TTSOrchestrator.synthesize_stream`)在 synthesize 前若 `translate_engine` 不為 None 就翻譯
- **修改** `siro/bridge/models.py:132`(`TTSRequest`)加 `translate_to_language: Optional[str]` + `translate_provider: Optional[str]`
- **修改** `siro/bridge/personas/siro-default.yaml` voice 區段加 `translate_audio: true`、`translate_to: "ja"`
- **修改** `siro/bridge/main.py:1081-1163`(`/tts/synthesize`)傳遞 translate 設定
- **新增** `siro/bridge/requirements.txt` 加 `httpx>=0.27.0`(若尚未有)

**估時**:S(1 天,vtuber 已經寫得很完整,直接 port)

**驗證**:
```python
# tests/bridge/test_translate.py
async def test_deeplx_chinese_to_japanese():
    t = DeepLXTranslate("http://127.0.0.1:1188/v2/translate", "JA")
    assert "こんにちは" in t.translate("你好")
```

---

## P0-5: Web tool 獨立頁(不開 Unity 也能驗 ASR/TTS)

**目標**:瀏覽器頁面 `/web-tool` 錄音 → POST `/asr` 轉文字;輸入文字 → WS `/tts-ws` 播放+下載。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/routes.py:73-254` — `init_webtool_routes`(`/web-tool`、`/asr` POST、`/tts-ws` WS)
- `vtuber/web_tool/index.html:1-141` — 完整 HTML
- `vtuber/web_tool/recorder.js:1-132` — `AudioRecorder` class(MediaRecorder + WAV header builder + 16kHz resampler)
- `vtuber/web_tool/main.js:1-398` — UI glue(POST /asr、WS /tts-ws、download combined WAV)
- `vtuber/src/open_llm_vtuber/server.py:93-98, 137-142` — router include + static mount

**SIRO 整合點**:
- **新建** `siro/bridge/webtool/__init__.py`、`routes.py`、`index.html`、`recorder.js`、`main.js`
- **修改** `siro/bridge/main.py` lifespan 後加 `app.include_router(init_webtool_routes(state))`
- **修改** `siro/bridge/main.py` 加 `app.mount("/web-tool", StaticFiles(directory="bridge/webtool"), name="webtool")`
- **新增** `siro/bridge/stt/faster_whisper_asr.py:92`(`FasterWhisperAsr.transcribe`)要支援 `audio: np.ndarray` 從 raw PCM(目前已有)

**估時**:S(半天,純 port,單元測試整合進 `test_main.py`)

**驗證**:`uvicorn bridge.main:app`,瀏覽 `http://localhost:8001/web-tool`,錄 5 秒中文,看 transcription 結果。

---

# P1 — 7 個重要功能(v1.5+ 之後)

## P1-1: Group conversation(兩隻角色對談)

**目標**:支援兩隻以上 AI 同台(可以是不同 persona),使用者訊息 broadcast 給全部,角色輪流發言(round-robin)。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/conversations/group_conversation.py:29-394` — `process_group_conversation` 完整 round-robin orchestrator
- `vtuber/src/open_llm_vtuber/conversations/chat_group.py:15-299` — `ChatGroupManager`、invite/remove、`broadcast_to_group`
- `vtuber/src/open_llm_vtuber/conversations/types.py:42-68` — `GroupConversationState` 帶 `group_queue: deque`、`memory_index: dict`
- `vtuber/src/open_llm_vtuber/conversations/conversation_handler.py:19-109, 146-213` — `handle_conversation_trigger` + `handle_group_interrupt`
- `vtuber/prompts/utils/group_conversation_prompt.txt:1-7` — prompt 模板

**SIRO 整合點**:
- **新建** `siro/bridge/conversations/__init__.py`、`group_conversation.py`、`chat_group.py`、`types.py`
- **修改** `siro/bridge/main.py:2267-2426`(WS dispatch)加 `group_text` type → 進 `process_group_conversation`
- **修改** `siro/bridge/personas/` 預期放兩個 persona yaml,例如 `siro-default.yaml` + `companion-2.yaml`
- **修改** `siro/bridge/agent_memory.py`(P0-3 建的)加 `memory_index: dict[uid, int]` 支援 per-member cursor
- **新增** `siro/SiroUnity/Assets/Scripts/PersonaApiClient.cs` 加 `GET /groups/{id}/members` 取名單

**估時**:L(3 天,要設計 WS broadcast protocol + 兩個 persona 共用 LLM 但不同 system prompt)

**驗證**:
```python
async def test_group_round_robin():
    state1, state2 = make_state("siro-default"), make_state("companion-2")
    manager = ChatGroupManager()
    manager.create_group("g1", [state1, state2])
    outputs = []
    async for out in process_group_conversation(manager, "g1", "今天天氣如何?"):
        outputs.append(out)
    assert len(outputs) >= 2  # 至少兩個角色都回應
```

---

## P1-2: LLM Provider 擴充(8 個 → 17 個)

**目標**:把 LLM provider 從 SIRO 現有的 3 個(Hermes CLI、MiniMax-M3/Anthropic protocol、Ollama)擴充到跟 vtuber 一樣 17 個。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/agent/stateless_llm_factory.py:14-78` — `LLMFactory` flat if/elif dispatch
- `vtuber/src/open_llm_vtuber/agent/stateless_llm/stateless_llm_interface.py:5-64` — `StatelessLLMInterface` 抽象
- `vtuber/src/open_llm_vtuber/agent/stateless_llm/openai_compatible_llm.py:48-190` — `AsyncOpenAI` 通用 client
- `vtuber/src/open_llm_vtuber/agent/stateless_llm/claude_llm.py:15-247` — `AsyncAnthropic` 專屬 client + streaming event
- `vtuber/src/open_llm_vtuber/agent/stateless_llm/llama_cpp_llm.py:13-77` — `llama_cpp.Llama` + thread executor
- `vtuber/src/open_llm_vtuber/config_manager/stateless_llm.py:7-285` — 每個 provider 的 Pydantic config model

**逐個 sub-feature**(每個都附 SIRO 整合點):

### P1-2a: Anthropic Claude(原生)
- **參考**: `vtuber/.../claude_llm.py:15-247`、`stateless_llm.py:186-209`(`ClaudeConfig`)
- **SIRO**: 雖然 SIRO 已經用 Anthropic protocol 透過 MiniMax-M3,但要支援**原生 claude.ai** API key。新建 `siro/bridge/llm/anthropic.py`(直接 port `claude_llm.py`)。`bridge/main.py:1331-1343` 加 `anthropic_native` 分支。
- **估時**:S

### P1-2b: OpenAI(原生)
- **參考**: `vtuber/.../openai_compatible_llm.py:48-190`、`stateless_llm.py:136-142`(`OpenAIConfig`)
- **SIRO**: 透過 `OpenAICompatibleLLM` 共用 client,只需 `siro/bridge/llm/openai.py` 設 base_url 預設 `https://api.openai.com/v1`。
- **估時**:XS(半小時)

### P1-2c: Gemini
- **參考**: `stateless_llm.py:145-153`(`GeminiConfig` base_url `https://generativelanguage.googleapis.com/v1beta/openai/`)
- **SIRO**: 走 OpenAI-compatible 路徑,`siro/bridge/llm/gemini.py` 設 base_url。
- **估時**:XS

### P1-2d: Mistral
- **參考**: `stateless_llm.py:156-162`(base_url `https://api.mistral.ai/v1`)
- **SIRO**: `siro/bridge/llm/mistral.py`,同 pattern。
- **估時**:XS

### P1-2e: DeepSeek
- **參考**: `stateless_llm.py:171-174`(base_url `https://api.deepseek.com/v1`)
- **SIRO**: `siro/bridge/llm/deepseek.py`,同 pattern。
- **估時**:XS

### P1-2f: Groq
- **參考**: `stateless_llm.py:177-183`、`vtuber/.../groq_whisper_asr.py:9-56`(同樣用 groq SDK)
- **SIRO**: `siro/bridge/llm/groq.py` + `bridge/requirements.txt` 加 `groq>=0.32.0`。
- **估時**:S

### P1-2g: Zhipu(智譜)
- **參考**: `stateless_llm.py:165-169`
- **SIRO**: `siro/bridge/llm/zhipu.py`,OpenAI-compatible 即可。
- **估時**:XS

### P1-2h: LM Studio
- **參考**: `stateless_llm.py:126-133`(本地 server,base_url 預設 `http://localhost:1234/v1`)
- **SIRO**: `siro/bridge/llm/lmstudio.py`。
- **估時**:XS

### P1-2i: llama.cpp(直接,不走 Ollama)
- **參考**: `vtuber/.../llama_cpp_llm.py:13-77`、`stateless_llm.py:212-229`(`LlamaCppConfig` 只要 `model_path`)
- **SIRO**: `siro/bridge/llm/llama_cpp.py`、`requirements.txt` 加 `llama-cpp-python>=0.3.0`。要注意 GPU VRAM(4GB 只能 3B Q4)。
- **估時**:S

**全部 P1-2 整合**:
- **修改** `siro/bridge/main.py:132-149`(env-driven state)加 `SIRO_LLM_PROVIDER` 支援所有新 provider
- **修改** `siro/.env.example` 加每個 provider 的 env vars(API key、base_url、model)
- **新增** `siro/bridge/llm/__init__.py` 統一 dispatch
- **新增** `siro/tests/bridge/test_llm_providers.py` 每個 provider 一個 test(用 mock HTTP,確保 routing 對)

**P1-2 總估時**:M(1.5 天,9 個 provider 大部分是 copy-paste + 測 routing)

---

## P1-3: TTS Provider 擴充(4 個 → 16 個)

**目標**:SIRO 目前 4 個 TTS(Edge、Piper、GPT-SoVITS、F5-TTS)擴充到 16 個。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/tts/tts_factory.py:5-215` — `TTSFactory` flat if/elif
- `vtuber/src/open_llm_vtuber/tts/tts_interface.py:1-...` — `TTSInterface` 抽象
- `vtuber/src/open_llm_vtuber/tts/stream.py:16-...` — TTSProvider pattern reference

**每個 backend**:

### P1-3a: Azure TTS
- **參考**: `vtuber/.../azure_tts.py:11-...`(`SpeechConfig` + `speech_synthesizer.speak_text_async`)
- **SIRO**: `siro/bridge/tts/azure.py`、加 `azure-cognitiveservices-speech>=1.40.0`
- **估時**:S

### P1-3b: pyttsx3(離線 fallback)
- **參考**: `vtuber/.../pyttsx3_tts.py`
- **SIRO**: `siro/bridge/tts/pyttsx3.py`(本地 TTS,不依賴網路)
- **估時**:XS

### P1-3c: MeloTTS
- **參考**: `vtuber/.../melo_tts.py:12-73`(`melo.api.TTS(language=..., device=...).tts_to_file`)
- **SIRO**: `siro/bridge/tts/melo.py`、`requirements.txt` 加 `melo-tts`
- **估時**:S

### P1-3d: Coqui TTS
- **參考**: `vtuber/.../coqui_tts.py:9-128`(`TTS.api.TTS(...).tts.tts_to_file`)
- **SIRO**: `siro/bridge/tts/coqui.py`、`requirements.txt` 加 `TTS>=0.22.0`(注意 model 很大,只 load 用的)
- **估時**:S

### P1-3e: Bark(Suno)
- **參考**: `vtuber/.../bark_tts.py:14-60`(`bark.preload_models()` + `generate_audio`)
- **SIRO**: `siro/bridge/tts/bark.py`、`requirements.txt` 加 `bark>=0.1.5`(VRAM 8GB+)
- **估時**:S

### P1-3f: CosyVoice / CosyVoice2
- **參考**: `vtuber/.../cosyvoice_tts.py:6-48`、`cosyvoice2_tts.py:6-54`(都是 Gradio HTTP client,非本地)
- **SIRO**: `siro/bridge/tts/cosyvoice.py`、`cosyvoice2.py`(打 Gradio endpoint)
- **估時**:S

### P1-3g: ElevenLabs
- **參考**: `vtuber/.../elevenlabs_tts.py:11-...`
- **SIRO**: `siro/bridge/tts/elevenlabs.py`、`requirements.txt` 加 `elevenlabs>=1.0.0`
- **估時**:XS

### P1-3h: Fish Audio
- **參考**: `vtuber/.../fish_api_tts.py:7-60`(`fish_audio_sdk.Session(apikey=...).tts(TTSRequest(...))`)
- **SIRO**: `siro/bridge/tts/fish.py`、`requirements.txt` 加 `fish-audio-sdk`
- **估時**:S

### P1-3i: SiliconFlow
- **參考**: `vtuber/.../siliconflow_tts.py:6-...`(`requests.post(api_url, json=payload, headers={"Authorization": ...})`)
- **SIRO**: `siro/bridge/tts/siliconflow.py`(純 HTTP,無 SDK)
- **估時**:XS

### P1-3j: Sherpa-ONNX TTS(離線)
- **參考**: `vtuber/.../sherpa_onnx_tts.py:13-...`(`sherpa_onnx.OfflineTtsConfig(vits=...)`)
- **SIRO**: `siro/bridge/tts/sherpa_onnx.py`(用 VITS Piper 模型)
- **估時**:S

### P1-3k: Spark TTS
- **參考**: `vtuber/.../spark_tts.py:7-60`(Gradio HTTP,`voice_clone`/`voice_creation` mode)
- **SIRO**: `siro/bridge/tts/spark.py`
- **估時**:S

### P1-3l: Cartesia Sonic-3
- **參考**: `vtuber/.../cartesia_tts.py:42-...`(`cartesia.Cartesia(api_key=...)`)
- **SIRO**: `siro/bridge/tts/cartesia.py`、`requirements.txt` 加 `cartesia>=1.0.0`
- **估時**:XS

### P1-3m: OpenAI-compat TTS(Kokoro 等)
- **參考**: `vtuber/.../openai_tts.py:16-...`(`client.audio.speech.create(model="kokoro", voice="af_sky+af_bella", base_url="http://localhost:8880/v1")`)
- **SIRO**: `siro/bridge/tts/openai_compat.py`(預設指向 Kokoro 本地 server)
- **估時**:S

**P1-3 整合**:
- **修改** `siro/bridge/tts/base.py:52-85`(`TTSProvider` Protocol)— 已有了,新增 backend 只要實作這個 Protocol
- **修改** `siro/bridge/tts/stream.py:82`(`TTSOrchestrator.__init__` default list)加新 provider
- **修改** `siro/bridge/main.py:1027-1080`(`/tts/voices` 列舉)支援新 provider
- **修改** `siro/bridge/personas/siro-default.yaml:voice.provider` 改成可選任何 provider
- **新增** `siro/tests/bridge/test_tts_providers.py` — 每個 provider 一個 availability test(用 mock 確保 import 對)

**P1-3 總估時**:L(3 天,12 個 backend 但大部分 < 100 行,主要是裝 SDK + 寫 mock test)

---

## P1-4: STT Provider 擴充(1 個 → 7 個)

**目標**:SIRO 目前只有 faster-whisper,擴充到 7 個。**特別推薦 FunASR(中文強)** 跟 sherpa-onnx(完全離線)。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/asr/asr_factory.py:5-62` — `ASRFactory` flat if/elif
- `vtuber/src/open_llm_vtuber/asr/asr_interface.py:6-58` — `ASRInterface` abstract
- `vtuber/src/open_llm_vtuber/asr/utils.py` — 自動下載模型 helper

### P1-4a: FunASR(**中文推薦**)
- **參考**: `vtuber/.../fun_asr.py:21-131` — `MODEL_ALIAS_TO_FULL_ID_MAP` 包含 `paraformer-zh`、`SenseVoiceSmall`、`conformer-en`、`fsmn-vad`、`ct-punc`;`AutoModel.generate()` + `re.sub(r"<\|.*?\|>", "", full_text)` 移除 SenseVoice tag
- **SIRO**: `siro/bridge/stt/funasr.py`、`requirements.txt` 加 `funasr>=1.1.0` + `modelscope>=1.18.0`
- **估時**:S(0.5 天,但要測試中文辨識率)

### P1-4b: Sherpa-ONNX(完全離線)
- **參考**: `vtuber/.../sherpa_onnx_asr.py:10-87` — 8 種 `model_type`:`transducer`/`paraformer`/`nemo_ctc`/`wenet_ctc`/`whisper`/`tdnn_ctc`/`sense_voice`/`fire_red_asr`
- **SIRO**: `siro/bridge/stt/sherpa_onnx.py`、`requirements.txt` 加 `sherpa-onnx>=1.12.0`
- **估時**:S

### P1-4c: Whisper.cpp
- **參考**: `vtuber/.../whisper_cpp_asr.py:8-37`(`pywhispercpp.model.Model`)
- **SIRO**: `siro/bridge/stt/whisper_cpp.py`、`requirements.txt` 加 `pywhispercpp>=1.2.0`
- **估時**:XS

### P1-4d: OpenAI Whisper API
- **參考**: `vtuber/.../openai_whisper_asr.py`
- **SIRO**: `siro/bridge/stt/openai_whisper.py`(走 OpenAI 客戶端)
- **估時**:XS

### P1-4e: Groq Whisper
- **參考**: `vtuber/.../groq_whisper_asr.py:9-56`(`groq.Groq(api_key=...).audio.transcriptions.create()`)
- **SIRO**: `siro/bridge/stt/groq_whisper.py`(同 P1-2f 共用 groq SDK)
- **估時**:XS

### P1-4f: Azure ASR
- **參考**: `vtuber/.../azure_asr.py:14-...`(`speechsdk.SpeechConfig` + auto language detect,預設 `["en-US", "zh-CN"]`)
- **SIRO**: `siro/bridge/stt/azure.py`
- **估時**:S

### P1-4g: Faster-Whisper(已有,留著)
- **參考**: `siro/bridge/stt/faster_whisper_asr.py:39-162` — 已有
- **SIRO**: 不動,作為 default。

**P1-4 整合**:
- **修改** `siro/bridge/main.py:2360-2382`(`run_stt_llm`)改成 `STTFactory.get_asr_system(SIRO_STT_PROVIDER)` 而不是 hardcode `FasterWhisperAsr`
- **修改** `siro/bridge/main.py:2362`(cache in state)加 LRU cache
- **修改** `siro/.env.example` 加 `SIRO_STT_PROVIDER=faster_whisper`
- **新增** `siro/bridge/stt/__init__.py`(`STTFactory` 直接 port)
- **新增** `siro/tests/bridge/test_stt_providers.py`

**P1-4 總估時**:M(1.5 天)

---

## P1-5: Proactive speak(AI 主動插話)

**目標**:背景 scheduler 偵測到 AI 應該說話的時機(例如使用者閒置 30 秒、視窗 focus 改變),主動送 prompt 觸發發言。

**參考檔案**:
- `vtuber/prompts/utils/proactive_speak_prompt.txt:1` — "Please say something that would be engaging and appropriate for the current context."
- `vtuber/src/open_llm_vtuber/conversations/conversation_handler.py:35-64` — `ai-speak-signal` handler,設 `metadata = {"proactive_speak": True, "skip_memory": True, "skip_history": True}`
- `vtuber/src/open_llm_vtuber/agent/agents/basic_memory_agent.py:277-284` — `_to_messages` 跳過 memory
- `vtuber/src/open_llm_vtuber/conversations/group_conversation.py:91-104, 302-303` — group 也跳過 history

**SIRO 整合點**:
- **新增** `siro/bridge/personas/siro-default.yaml` 加 `proactive_speak_prompt` 欄位
- **修改** `siro/bridge/free_exploration.py`(已有 24/7 scheduler)加 `trigger_proactive_speak()` 方法
- **修改** `siro/bridge/main.py:2267-2426`(WS dispatch)加 `ai_speak_signal` type handler → 觸發 LLM
- **修改** `siro/bridge/agent_memory.py`(P0-3 建的)加 `skip_memory` flag
- **修改** `siro/bridge/state/sqlite_backend.py:178`(`append_message`)加 `skip_history` 過濾
- **新增** WS out:`proactive_speak_started` / `proactive_speak_ended` 通知 Unity
- **修改** `siro/SiroUnity/Assets/Scripts/HermesBridgeClient.cs:641-786` 加對應 case

**估時**:S(1 天,大部分 SIRO 已有 scheduler 跟 metadata 機制)

**驗證**:
```python
async def test_proactive_does_not_persist():
    state.agent_memory.append(...)
    await trigger_proactive_speak(state, "你今天有什麼想說的?")
    assert state.agent_memory.last_message is None  # 沒寫進 memory
```

---

## P1-6: Desktop pet 模式(透明 click-through overlay)

**目標**:Unity 視窗設為透明背景 + 永遠置頂 + 滑鼠穿透,變成桌面寵物。

**注意**:這個 feature **100% 在 Unity 端**,Python 端 0 修改。

**參考檔案**:
- `vtuber/README.md:49, 69, 76` — 功能描述
- `vtuber/assets/i2_pet_vscode.jpg`、`i4_pet_desktop.jpg` — 截圖參考
- Frontend 在 `Open-LLM-VTuber-Web` 倉庫(沒 clone),Electron/Tauri 實作

**SIRO 整合點**:
- **修改** `siro/SiroUnity/Assets/Scripts/WindowModeController.cs`(新建)用 `user32.dll` 的 `SetWindowLong` + `WS_EX_LAYERED` + `WS_EX_TRANSPARENT` 設視窗樣式
- **修改** `siro/SiroUnity/ProjectSettings/PlayerSettings.asset` 設 `Display Resolution Dialog = Disabled`、`Run In Background = true`
- **新增** `siro/SiroUnity/Assets/Scripts/PetModeToggle.cs` — F11 切換 pet/normal 模式
- **修改** `siro/SiroUnity/Assets/Scripts/BackgroundController.cs` 加透明背景 option

**估時**:M(1.5 天,Windows API 呼叫 + 測試透明度)

**驗證**:F11 切到 pet 模式,角色變成透明 overlay 浮在桌面上,滑鼠可穿透。

---

## P1-7: BiliBili 直播串流(粉絲最愛)

**目標**:接 B 站直播,danmaku 轉成 LLM 輸入,AI 回覆透過 TTS 推回直播。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/live/live_interface.py:6-141` — `LivePlatformInterface` ABC + `MessageQueue`
- `vtuber/src/open_llm_vtuber/live/bilibili_live.py:33-351` — `BiliBiliLivePlatform`(包 `blivedm.BLiveClient` + `VtuberHandler` 處理 danmaku)
- `vtuber/src/open_llm_vtuber/proxy_handler.py:13-311` — `ProxyHandler`(多 client → 1 server WS)
- `vtuber/src/open_llm_vtuber/proxy_message_queue.py:7-164` — `ProxyMessageQueue`(producer-consumer)
- `vtuber/scripts/run_bilibili_live.py:1-63` — entrypoint
- `vtuber/requirements-bilibili.txt:1-37` — deps(`aiohttp==3.9.5`、`websocket-client==1.8.0`)

**SIRO 整合點**:
- **新建** `siro/bridge/live/__init__.py`、`live_interface.py`、`bilibili_live.py`
- **新建** `siro/bridge/proxy_handler.py`、`proxy_message_queue.py`
- **新建** `siro/scripts/run_bilibili_live.py` — entry,讀 `bilibili_live.room_ids` + `sessdata`
- **修改** `siro/bridge/main.py` 新增 WS route `/proxy-ws` → `ProxyHandler`
- **修改** `siro/bridge/main.py:421-565`(lifespan)加 bilibili_live background task(模式跟 `telegram_bot.py:73-126` 一樣)
- **新增** `siro/bridge/requirements-bilibili.txt`(獨立 deps,不要污染主 deps)
- **修改** `siro/bridge/models.py:32`(`ChatRequest`)加 `source: Literal["unity", "telegram", "bilibili"]` 用來標記訊息來源
- **修改** `siro/SiroUnity/Assets/Scripts/HermesBridgeClient.cs:189`(`serverUrl`)若有多 client 透過 proxy,要區分 `client_uid`

**估時**:L(4 天,blivedm API + proxy 架構 + 測試直播)

**驗證**:
```python
# tests/integration/test_bilibili_mock.py
async def test_danmaku_to_llm():
    platform = MockBilibiliPlatform(room_id=123)
    platform.simulate_danmaku("你好")
    outputs = []
    async for out in platform.stream_to_llm():
        outputs.append(out)
    assert "你好" in outputs[0]["user_input"]
```

---

# P2 — 7 個完善性(看時間)

## P2-1: think_tag / display_processor(AI 思考顯示)

**目標**:LLM 學會用 `<think>...</think>` 包內心戲,前端用 `(` `)` 顯示但不唸出來。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/agent/transformers.py:12-217` — 4-decorator stack:`tts_filter → display_processor → actions_extractor → sentence_divider`
- `vtuber/src/open_llm_vtuber/utils/sentence_divider.py:269-608` — `SentenceDivider` + `TagState` + `SentenceWithTags`
- `vtuber/prompts/utils/think_tag_prompt.txt:1-6` — 提示詞
- `vtuber/src/open_llm_vtuber/utils/tts_preprocessor.py:7-196` — `tts_filter` + `filter_*` 工具

**SIRO 整合點**:
- **新建** `siro/bridge/agent/transformers.py` — 4 個 decorator
- **新建** `siro/bridge/utils/sentence_divider.py` — port `SentenceDivider`
- **新建** `siro/bridge/utils/tts_preprocessor.py` — port `tts_filter`
- **修改** `siro/bridge/personas/siro-default.yaml` personality.system_prompt 加 `請用 <think> 標記內心想法`
- **修改** `siro/bridge/minimax_streaming_client.py:140`(`chat_stream`)把 transformer stack 套上
- **修改** `siro/bridge/tts/stream.py:174`(`synthesize_sentence_stream`)在 `_clean_for_tts` 跳過 think-tag 內文
- **修改** `siro/SiroUnity/Assets/Scripts/EmotionDisplay.cs` — `(`/`)` 顯示為 subtle 灰字體

**估時**:M(2 天,主要是 `SentenceDivider` 的 tag stack 邏輯)

---

## P2-2: TTS preprocessor 集中化

**目標**:把 TTS 文字清理(去括號、去星號、去特殊字元)集中到一個 module,所有 TTS provider 走同一個 filter。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/utils/tts_preprocessor.py:7-196` — `tts_filter` + `filter_brackets`/`filter_parentheses`/`filter_angle_brackets`/`filter_asterisks`/`remove_special_characters`
- `vtuber/src/open_llm_vtuber/config_manager/tts_preprocessor.py:9-118` — `TTSPreprocessorConfig` Pydantic model

**SIRO 整合點**:
- **新建** `siro/bridge/tts/preprocessor.py` — port `tts_filter`
- **修改** `siro/bridge/tts/stream.py:44`(`_clean_for_tts`)改用 `preprocessor.tts_filter(text, ...)`
- **修改** `siro/bridge/models.py:132`(`TTSRequest`)加 `remove_special_char: bool = True`、`ignore_brackets/parentheses/asterisks/angle_brackets: bool = True` 5 個 flags
- **修改** `siro/bridge/main.py:1081-1163`(`/tts/synthesize`)傳遞 flags
- **修改** `siro/bridge/personas/siro-default.yaml` voice 加 `preprocessor:` 區段

**估時**:S(0.5 天,vtuber 已經寫好)

---

## P2-3: Tap motions(點擊觸發動作,不經 LLM)

**目標**:點 Mao 的頭 → 直接播 motion(回應 < 100ms),不走 LLM 推理。

**注意**:這個 feature 跨 **Python 設定** + **Unity 處理**。

**參考檔案**:
- `vtuber/model_dict.json:21-28` — `tapMotions` schema:`{ "HitAreaHead": { "": 1 }, "HitAreaBody": { "": 1 } }`
- `vtuber/src/open_llm_vtuber/live2d_model.py` — `tapMotions` pass-through(無 Python 邏輯)
- Frontend(沒 clone):Live2D 攔截 click → 查 `tapMotions` → 播 motion

**SIRO 整合點**:
- **修改** `siro/bridge/personas/siro-default.yaml` model 區段加 `tap_motions: { HitAreaHead: 1, HitAreaBody: 2 }`(對應 Live2D motion_group index)
- **修改** `siro/bridge/main.py:2267-2426` 新增 WS 訊息 `tap_motion` 接收 Unity 上報 → bridge 直接 push `motion_play` 不等 LLM
- **修改** `siro/SiroUnity/Assets/Scripts/PersonaClickHandler.cs`(已有)— 點擊時若 persona 有 `tap_motions`,優先播 motion;若 LLM tool 設定要 trigger response,再走 SendTask
- **修改** `siro/SiroUnity/Assets/Scripts/Live2DModelController.cs` — 接受外部 `PlayMotionImmediately(group, index)` API

**估時**:S(1 天,主要在 Unity 端)

---

## P2-4: 嘴型同步 RMS 音量條

**目標**:TTS 串流的 audio payload 附帶 20ms RMS 音量陣列,Unity 用來做嘴型 sync。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/utils/stream_audio.py:8-82` — `_get_volume_by_chunks(audio, 20)` + `prepare_audio_payload` dict schema(`type, audio, volumes, slice_length, display_text, actions, forwarded`)
- `vtuber/src/open_llm_vtuber/conversations/tts_manager.py:16-182` — `TTSTaskManager` ordered delivery

**SIRO 整合點**:
- **新建** `siro/bridge/tts/stream_audio.py` — port `prepare_audio_payload` + `_get_volume_by_chunks`
- **修改** `siro/bridge/main.py:344-417`(`_stream_tts_for_sentence`)加 `volumes` 到 `tts_audio` payload
- **修改** `siro/SiroUnity/Assets/Scripts/UnityTTSPlayer.cs:108`(`BridgeTtsAudio`)加 `volumes: float[]` 欄位
- **修改** `siro/SiroUnity/Assets/Scripts/UnityTTSPlayer.cs:200+`(`HandleTtsAudio`)播放時根據 `volumes[i]` 調整 Live2D mouth open 參數
- **修改** `siro/SiroUnity/Assets/Scripts/Live2DModelController.cs` — 加 `SetMouthOpen(float)` API

**估時**:M(1.5 天,音訊處理 + Live2D 嘴型 parameter)

---

## P2-5: conf.yaml i18n 描述

**目標**:所有設定欄位有中英文 `Description`,Unity 端 UI 顯示對應語言。

**參考檔案**:
- `vtuber/src/open_llm_vtuber/config_manager/i18n.py:6-139` — `MultiLingualString` + `Description` + `I18nMixin` mixin
- `vtuber/src/open_llm_vtuber/config_manager/asr.py:7-25` — `AzureASRConfig(I18nMixin)` 範例

**SIRO 整合點**:
- **新建** `siro/bridge/config_i18n.py` — port `MultiLingualString` + `Description` + `I18nMixin`
- **修改** `siro/bridge/models.py:1-197`(所有 Pydantic models)— `class Foo(BaseModel, I18nMixin)` + 加 `DESCRIPTIONS: ClassVar[Dict[str, Description]]`
- **修改** `siro/bridge/prompts.py:333`(`PERSONALITIES`)加 description locale lookup
- **修改** `siro/SiroUnity/Assets/Scripts/PersonaSelectorUI.cs` — 顯示 `Description.get_text(Locale)`
- **新增** `siro/bridge/i18n/__init__.py` 翻譯字串

**估時**:M(1.5 天,主要是改每個 Pydantic model 加 DESCRIPTIONS dict)

---

## P2-6: conf 升級工具(版本遷移)

**目標**:`upgrade.py` 自動 merge 新版 `conf.yaml` 預設值,保留 user 設定。

**參考檔案**:
- `vtuber/upgrade.py:1-171` — top-level entry
- `vtuber/upgrade_codes/upgrade_manager.py:11-67` — `UpgradeManager`
- `vtuber/upgrade_codes/compare_yaml.py:1-101` — diff logic(用 `ruamel.yaml`)
- `vtuber/upgrade_codes/config_sync.py:22-313` — 4-step 流程
- `vtuber/upgrade_codes/version_manager.py:8-94` — version-specific migration
- `vtuber/upgrade_codes/from_version/v_1_1_1.py:5-50+` — `migration_map` 範例
- `vtuber/upgrade_codes/upgrade_core/{constants.py,language.py,upgrade_utils.py,comment_sync.py,comment_diff_fn.py}` — 共用工具

**SIRO 整合點**:
- **新建** `siro/upgrade.py`(top-level)
- **新建** `siro/upgrade_codes/`(整個目錄 port 過來)
- **修改** `siro/bridge/personas/` — 加 `from_version/` 處理 persona schema 變更
- **新增** `siro/.upgrade/` 放 migration 記錄

**估時**:L(2.5 天,主要是 `ruamel.yaml` 操作 + version map 設計)

---

## P2-7: 多語 README(EN/CN/JP/KR)

**目標**:四個 README.md,內容互譯,banner 圖片各語系。

**參考檔案**:
- `vtuber/README.md:1-15`(EN master)
- `vtuber/README.CN.md:1-15`(中文)
- `vtuber/README.JP.md:1-15`(日文)
- `vtuber/README.KR.md:1-15`(韓文)
- `vtuber/assets/banner*.jpg`(4 個 banner 圖)

**SIRO 整合點**:
- **翻譯** `siro/README.md` → `README.zh-TW.md`(主要讀者)、`README.en.md`(次要)、`README.ja.md`(選)
- **新建** `siro/assets/banner.zh-TW.jpg`(可選)

**估時**:XS(0.5 天,但要等內容穩定後再翻,提早翻會一直改)

---

# Cross-cutting: 跨 feature 共用 schema 改動

**P0-3、P1-1、P1-5 都會用到 AgentMemory,集中設計一次**:

```python
# siro/bridge/agent_memory.py (新建,P0-3 啟動)
@dataclass
class TurnMemory:
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[str] = None
    emotion: Optional[str] = None
    interrupted: bool = False  # P0-3
    skip_memory: bool = False  # P1-5 proactive
    timestamp_ms: int = 0

class AgentMemory(Protocol):
    def append(self, msg: TurnMemory) -> None: ...
    def snapshot(self) -> List[TurnMemory]: ...
    def handle_interrupt(self, heard: str) -> None: ...  # P0-3
    def set_skip(self, skip: bool) -> None: ...  # P1-5
```

**P0-2、P1-3、P1-4 會用到 Pydantic models 改動**:
- `siro/bridge/models.py` 加 `ImageData`、`TTSProviderChoice` enum(12 個)、`STTProviderChoice` enum(7 個)

**P1-2、P1-3、P1-4 都會用到 factory pattern**:
- `siro/bridge/llm/__init__.py`、`tts/__init__.py`、`stt/__init__.py` 三個 factory,統一風格跟 vtuber 對齊

---

# Verification(每個 feature 完成後怎麼測)

## 自動化測試

```bash
# 跑全部測試
cd C:/coconut chennel/SIRO
pytest tests/bridge/ -v

# 跑特定 feature
pytest tests/bridge/test_mcp.py -v
pytest tests/bridge/test_handle_interrupt.py -v
pytest tests/bridge/test_stt_providers.py -v
```

**每個 feature 對應的測試檔**:
- P0-1: `tests/bridge/test_mcp.py`(新建)
- P0-2: `tests/bridge/test_vision.py`(新建)
- P0-3: `tests/bridge/test_handle_interrupt.py`(新建)
- P0-4: `tests/bridge/test_translate.py`(新建)
- P0-5: `tests/bridge/test_webtool.py`(整合進 `test_main.py`)
- P1-1: `tests/bridge/test_group_conversation.py`(新建)
- P1-2: `tests/bridge/test_llm_providers.py`(新建)
- P1-3: `tests/bridge/test_tts_providers.py`(新建)
- P1-4: `tests/bridge/test_stt_providers.py`(新建)
- P1-5: `tests/bridge/test_proactive.py`(新建)
- P1-6: Unity 端手動測試
- P1-7: `tests/integration/test_bilibili_mock.py`(新建)
- P2-1 ~ P2-7: 各自小測試

## E2E 驗證(checklist)

- [ ] P0-1 完成:在 Unity 說「查天氣」,LLM call ddg-search,結果顯示
- [ ] P0-2 完成:開鏡頭對角色舉一張紙,LLM 描述內容
- [ ] P0-3 完成:角色講到一半,使用者打斷,SQLite history 有 `[Interrupted by user]`
- [ ] P0-4 完成:中文回應 + 設定日文 voice,音檔是日文發音
- [ ] P0-5 完成:`http://localhost:8001/web-tool` 錄音上傳,看到 transcription
- [ ] P1-1 完成:兩隻角色對同一訊息輪流發言
- [ ] P1-2 完成:`SIRO_LLM_PROVIDER=claude` 切到 Claude,正常對話
- [ ] P1-3 完成:persona yaml 改 `voice.provider: elevenlabs`,切過去
- [ ] P1-4 完成:中文 5 秒錄音,FunASR 正確辨識「你好嗎」
- [ ] P1-5 完成:閒置 30 秒,角色主動說一句話(但 history 沒新增)
- [ ] P1-6 完成:F11 切到 pet 模式,角色透明浮在桌面上
- [ ] P1-7 完成:接 B 站直播,danmaku 觸發 AI 回應
- [ ] P2-1 完成:LLM 輸出含 `<think>...</think>`,UI 顯示 `(...)` 但 TTS 不唸
- [ ] P2-2 完成:角色講「*笑*」不會唸出星號
- [ ] P2-3 完成:點 Mao 頭,0.1s 內播對應 motion
- [ ] P2-4 完成:TTS 播放時,Live2D 嘴型跟著音訊開合
- [ ] P2-5 完成:Unity UI 切英文,設定說明變英文
- [ ] P2-6 完成:`python upgrade.py` 自動 merge 新版 conf
- [ ] P2-7 完成:GitHub 顯示 4 個 README

## KPI 確認(避免 regression)

每個 P0/P1 feature 合併後跑:

```bash
# K2 反應時間(必須保持 < 5s)
python scripts/perf/measure_k2.py

# K5 表情切換延遲(必須保持 < 200ms)
python scripts/perf/measure_k8.py
```

參考 [docs/PHASE2_TEST_REPORT.md](docs/PHASE2_TEST_REPORT.md) 的 baseline(K2: 3.4-4.6s,K5: 63.7ms)。

---

# 實作順序總結(給 sprint planning 用)

| 週 | Feature | 估時 | 風險 |
|---|---|---|---|
| W1 | P0-1 (MCP) | 3-4d | stdio 進程管理 |
| W1 | P0-3 (handle_interrupt) | 2d | AgentMemory 設計 |
| W2 | P0-2 (vision) | 4-5d | Unity camera + 4GB VRAM |
| W2 | P0-4 (TTS translation) | 1d | 低 |
| W3 | P0-5 (web tool) | 0.5d | 低 |
| W3 | P1-1 (group chat) | 3d | 雙 persona state 同步 |
| W4 | P1-2 (LLM providers) | 1.5d | 低 |
| W4 | P1-4 (STT providers) | 1.5d | FunASR model 下載 |
| W5 | P1-3 (TTS providers) | 3d | SDK 安裝 + VRAM |
| W5 | P1-5 (proactive) | 1d | 低 |
| W6 | P1-6 (desktop pet) | 1.5d | Windows API |
| W6 | P1-7 (BiliBili) | 4d | blivedm + proxy |
| W7+ | P2-1 ~ P2-7 | ~10d | 分散 |

**P0 + P1 全部完成約 7 週(35 工作天)**,P2 約 2 週(10 工作天)。

---

# Open Questions(實作前要先決定)

1. **MCP server 預設要預裝哪幾個?** 建議 `time` + `ddg-search` 開箱即用,其他讓 user 自己加
2. **Group chat 預設幾隻角色?** 建議 2 隻(siro-default + companion-2),3 隻以上 context 會爆炸
3. **TTS provider 預設順序?** 目前 F5-TTS → Edge → Piper,擴充後要不要把 CosyVoice 排前面(中文品質好)?
4. **Vision 要不要做 face tracking(鏡頭偵測人臉)?** vtuber 也沒做,先不做
5. **Desktop pet 要不要也做 macOS/Linux?** 建議先 Windows(主力平台),其他用戶回報再說
6. **Bilibili sessdata 要不要支援無登入模式?** 無登入只能收公開直播,danmaku 限制較多

這些問題我建議在 W1 開始 P0-1 之前先決定。
