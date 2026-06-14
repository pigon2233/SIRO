# SIRO Linux Port 健檢報告

> **日期**：2026-06-09
> **目標**：把現有 Windows 開發機的程式碼移植到 Linux（Phase 4 鋪路）前，掃描所有 platform assumption
> **範圍**：bridge/ + os-runtime/ + scripts/ + SiroUnity/
> **結論（更新）**：**18 個潛在問題、11 個 P0/P1 已修（含 protoc 裝好、cargo build 0 warning 10 tests pass、bridge 72 tests pass）、剩 7 個需實機 Linux 驗證或 Phase 4 才做**

---

## 嚴重程度分級

| 等級 | 影響 | 處理時機 |
|------|------|----------|
| 🔴 **P0** | 在 Linux 直接 break | 移植前必修（不修就 build 失敗 / runtime crash）|
| 🟠 **P1** | 移植時要手動調整、但不影響啟動 | 移植時一起改 |
| 🟡 **P2** | UX 變差或功能退化、可後補 | Phase 4+ 視需要補 |
| 🟢 **P3** | 純文件/小工具、nice-to-have | 有空再說 |

---

## 🔴 P0：移植前必修

### L-01：os-runtime services.rs 用 `python` 當指令

**位置**：[os-runtime/crates/siro-runtime/src/services.rs:70](../../os-runtime/crates/siro-runtime/src/services.rs)

```rust
ServiceDef {
    name: "bridge".to_string(),
    command: "python".to_string(),  // ← Linux 通常是 python3
    args: vec!["-m".to_string(), "bridge.main".to_string()],
    ...
}
```

**問題**：
- Ubuntu/Debian 預設 `python` 指向 Python 2 或根本不存在
- 即使有 venv，siro-runtime 啟動 subprocess 用的是系統 `python`、可能跟 venv 不一致

**修法**：
- 優先順序：`python3` → `python` → `SIRO_PYTHON_BIN` env var
- 或在 `runtime.toml` 加 `[runtime].python_bin = "python3"`
- venv 場景：`source venv/bin/activate` 後 `which python` 拿路徑

```rust
// 修法建議
fn find_python_bin() -> String {
    if let Ok(p) = std::env::var("SIRO_PYTHON_BIN") {
        return p;
    }
    for cand in &["python3", "python"] {
        if which::which(cand).is_some() {
            return cand.to_string();
        }
    }
    "python3".to_string()  // 預設、Linux 標準
}
```

### L-02：scripts/start_bridge.sh 用 `powershell` 殺 process

**位置**：[scripts/start_bridge.sh:28, 39](../../scripts/start_bridge.sh)

```sh
powershell -Command "Stop-Process -Id $PID -Force" 2>/dev/null || true
```

**問題**：
- Linux 沒 powershell（除非裝 PowerShell Core）
- `netstat -ano` 是 Windows 格式
- `lsof -ti:8001` 在 Linux 通常 OK、但 netstat 那行用 `awk '{print $NF}'` 取 PID 在 Linux 不對（Linux netstat 輸出是 `Proto Local-Address Foreign-Address State PID/Program`、但格式不同）

**修法**：加 platform 分支

```sh
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
    # Windows
    if lsof -ti:8001 2>/dev/null | head -1 > /dev/null; then
        PID=$(netstat -ano | grep ":8001 " | grep LISTENING | awk '{print $NF}' | head -1)
        powershell -Command "Stop-Process -Id $PID -Force" 2>/dev/null || true
    fi
else
    # Linux / macOS
    if lsof -ti:8001 2>/dev/null | head -1 > /dev/null; then
        PID=$(lsof -ti:8001 | head -1)
        kill -9 "$PID" 2>/dev/null || true
    fi
fi
```

### L-03：scripts/start_bridge.sh 用 `target/debug/siro-runtime.exe`

**位置**：[scripts/start_bridge.sh:45, 48](../../scripts/start_bridge.sh)

```sh
if [ -f os-runtime/target/debug/siro-runtime.exe ]; then
    ...
    PROTOC="C:/Users/jason/tools/protoc.exe" nohup ./target/debug/siro-runtime.exe --auto-start=false > /tmp/siro_runtime.log 2>&1 &
```

**問題**：
- Linux build 產出 `siro-runtime`（無 `.exe`）
- `PROTOC="C:/Users/jason/..."` 是個人 Windows 路徑
- `auto-start=false` 跟 service 邏輯可能衝突

**修法**：加 `.exe` 條件、加 protoc fallback

```sh
RUNTIME_BIN="os-runtime/target/debug/siro-runtime"
[ -f "${RUNTIME_BIN}.exe" ] && RUNTIME_BIN="${RUNTIME_BIN}.exe"

PROTOC_BIN="${PROTOC:-protoc}"
[ ! -x "$PROTOC_BIN" ] && PROTOC_BIN="protoc"  # fallback to PATH

if [ -f "$RUNTIME_BIN" ]; then
    PROTOC="$PROTOC_BIN" nohup "$RUNTIME_BIN" --auto-start=false > /tmp/siro_runtime.log 2>&1 &
    disown
fi
```

---

## 🟠 P1：移植時一起改

### L-04：scripts/check-env.py 列 hermes 路徑含 Windows `Scripts\hermes.exe`

**位置**：[scripts/dev/check-env.py:144](../../scripts/dev/check-env.py)

```python
candidates = [
    Path.home() / "hermes-agent" / ".venv" / "Scripts" / "hermes.exe",  # Windows
    Path.home() / "hermes-agent" / ".venv" / "bin" / "hermes",            # Linux/macOS
    Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent" / ".venv" / "Scripts" / "hermes.exe",  # 舊版 Windows
]
```

**問題**：
- 這部分**已經有** Linux path（`bin/hermes`）
- 但「找不到 hermes 時」只建議 `winget install Google.Protobuf` 應該改成跨平台

**修法**：install hint 加 Linux
```python
if sys.platform == "win32":
    info("  提示：winget install Google.Protobuf 裝 protoc")
else:
    info("  提示：apt install protobuf-compiler 裝 protoc（Ubuntu/Debian）")
    info("        brew install protobuf 裝 protoc（macOS）")
```

### L-05：bridge/main.py sys.stdout.reconfigure 對 Linux 是 no-op

**位置**：[bridge/main.py:28-29](../../bridge/main.py)

```python
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
```

**評估**：
- Linux 預設 UTF-8 locale、這兩行 no-op 不會壞
- Windows 預設 cp950、這兩行必要
- **保持原樣即可、跨平台安全** ✅

### L-06：hermes_client.py subprocess 對 Linux shell 行為

**位置**：[bridge/hermes_client.py:108, 153, 201](../../bridge/hermes_client.py)

```python
result = subprocess.run(
    [self.binary_path, ...],
    capture_output=True,
    encoding="utf-8",
    errors="replace",
    ...
)
```

**評估**：
- 用 list 不用 shell=True → 跨平台安全 ✅
- encoding="utf-8" → Linux 預設、OK
- Windows 必要（cp950 會炸）
- **保持原樣即可** ✅

### L-07：Sandbox path 對 Linux 9P / overlayfs / snap 的處理

**位置**：[os-runtime/crates/siro-runtime/src/sandbox.rs](../../os-runtime/crates/siro-runtime/src/sandbox.rs)

**問題**：
- 用了 `canonicalize()` 跟 `starts_with()` 比對
- Linux 9P / overlayfs / snap mount 可能 canonicalize 後前綴不同
- symlink follow 行為在 Linux/macOS/Windows 各異
- 已有 `strip_unc_prefix` 處理 Windows UNC、Linux 沒對等問題

**評估**：
- 主流 Linux FS（ext4 / xfs / btrfs）canonicalize 行為一致
- Snap / AppImage / 容器（9p）情境罕見、暫不處理
- **記進 known issues、未來看** 🟡

### L-08：config.rs 預設 `/etc/siro/runtime.toml` Linux 寫權限

**位置**：[os-runtime/crates/siro-runtime/src/main.rs:34](../../os-runtime/crates/siro-runtime/src/main.rs)

```rust
#[arg(short, long, default_value = "/etc/siro/runtime.toml")]
config: String,
```

**問題**：
- Linux 上 `/etc/siro/` 需 root 寫、可能不存在
- 找不到檔案時用 Default（向後相容）✅ 已經處理
- 但 log 會一直印「找不到、用預設」、吵

**修法**：動態 default
```rust
#[arg(short, long, default_value = "")]  // 空 = 自動找
config: String,
```

啟動時按順序找：
1. `--config` CLI 參數
2. `./runtime.toml`（cwd）
3. `/etc/siro/runtime.toml`
4. 都沒有 → 預設值

### L-09：services.rs python 在 Linux venv 路徑

**位置**：[os-runtime/crates/siro-runtime/src/services.rs:67-83](../../os-runtime/crates/siro-runtime/src/services.rs)

```rust
env: HashMap::from([
    ("PYTHONPATH".to_string(), project_root.to_string_lossy().to_string()),
    ("SIRO_STREAMING".to_string(), "true".to_string()),
    ("SIRO_USE_AGENT_OS".to_string(), "true".to_string()),
]),
```

**問題**：
- 沒設 `PATH` → subprocess 找不到 hermes
- 沒設 `VIRTUAL_ENV` → Python 知道自己在 venv
- 沒設 `PYTHONHOME` → Python 找 site-packages

**修法**：
```rust
env: HashMap::from([
    ("PATH".to_string(), env!("PATH").to_string()),  // 繼承 siro-runtime 的 PATH
    ("PYTHONPATH".to_string(), project_root.to_string_lossy().to_string()),
    ("SIRO_STREAMING".to_string(), "true".to_string()),
    ("SIRO_USE_AGENT_OS".to_string(), "true".to_string()),
]),
```

### L-10：services.rs default_services 寫死 project_root 的相對路徑

**位置**：[os-runtime/crates/siro-runtime/src/services.rs:72](../../os-runtime/crates/siro-runtime/src/services.rs)

```rust
working_dir: Some(project_root.join("bridge").to_string_lossy().to_string()),
```

**評估**：
- 跨平台沒問題（用 `Path::join`）
- 但只支援從 `os-runtime/` 跑、從 `/` 跑或 `/usr/bin` 跑會壞
- **改成讀 `SIRO_PROJECT_ROOT` env var、預設 `./`** 🟡

### L-11：Unity 端的 Linux build 疑慮

**位置**：[SiroUnity/Assets/Scripts/HermesBridgeClient.cs](../../SiroUnity/Assets/Scripts/HermesBridgeClient.cs)

```cs
public string serverUrl = "ws://127.0.0.1:8001/ws";
```

**問題**：
- Unity 6.3 支援 Linux build（Server / Desktop）✅
- Cubism SDK for Unity 5-r.5 有 Linux Native plugin ✅
- IL2CPP + Linux Server 模式可能踩 OpenGL / Vulkan 雷
- Mao Live2D 模型在 Linux GPU 驅動可能跟 Windows 行為不同

**修法**：
- 先用 Mono + Linux Desktop 模式 build
- 不要用 IL2CPP（Linux Server 模式才需要）
- 測試時在 X11 / Wayland 兩種都跑一次

### L-12：Start_bridge.sh 跟 start_bridge.ps1 完全分叉

**位置**：[scripts/start_bridge.sh](../../scripts/start_bridge.sh) vs [scripts/start_bridge.ps1](../../scripts/start_bridge.ps1)

**問題**：
- 兩份 script 邏輯略不同（ps1 多了 python.exe 絕對路徑）
- 維護成本高、改一邊忘了改另一邊

**修法**：
- 短期：保持雙份、加 lint 提醒「兩個檔案要同步改」
- 長期：寫 `start_bridge.py` 跨平台、shell 只負責呼叫

### L-13：hardware.rs 沒處理 Linux 無 GUI / headless server 情境

**位置**：[os-runtime/crates/siro-runtime/src/hardware.rs](../../os-runtime/crates/siro-runtime/src/hardware.rs)

**問題**：
- `xdpyinfo` 在 headless server 找不到 → display 會 None ✅ 沒事
- `arecord` / `aplay` 在 server 沒裝 → audio 空 ✅
- 但要 capture display 截圖時（Phase 5）要 wayland-specific 工具

**評估**：先不管、Phase 5 再說 🟡

---

## 🟡 P2：UX 變差、後補

### L-14：tools/shell.py blocklist 沒列 Linux 危險指令

**位置**：[bridge/tools/shell.py](../../bridge/tools/shell.py)

**問題**：
- blocklist 列了 `rm -rf /`、`sudo`、`dd`、`mkfs` ✅
- Linux 特有：`shutdown`、`reboot`、`halt`、`poweroff`、`init 0`、`init 6`、`mount`、`umount`、`chmod 777 /`、`useradd`、`passwd`
- `apt install / apt remove` 應該要 confirmation（已透過 whitelist 排除大多數）✅

**修法**：blocklist 補 Linux 指令（v1.5+ 已有的 blocklist 加 5 行）

### L-15：i18n 沒自動偵測 locale

**問題**：
- 預設用 `zh-TW.json`、要切英文要改 Unity prefab
- Linux 設 `LANG=zh_TW.UTF-8` 不會自動切

**修法**：v1.0+ 加 locale 偵測

### L-16：siro-runtime systemd 整合沒寫

**問題**：
- Phase 4 規劃要 systemd service
- 沒 `os/systemd/siro-runtime.service` 範本

**修法**：Phase 4 一起做

### L-17：kiosk 模式 (X11 + openbox / Wayland + Cage) 沒寫

**問題**：
- Phase 4 規劃有、但 os/kiosk/ 是空的

**修法**：Phase 4 一起做

---

## 🟢 P3：nice-to-have

### L-18：verify_gaps4_recovery.py 只在 Windows 測過

**位置**：[scripts/perf/verify_gaps4_recovery.py:132-171](../../scripts/perf/verify_gaps4_recovery.py)

**問題**：
- `sys.platform == "win32"` 分支有 tasklist/taskkill
- Linux 分支有 pgrep/os.kill
- 兩邊都對 ✅ 但只 Windows 實機驗過

**修法**：Phase 4 跑 Linux 時驗一次

---

## 行動計劃

### 立即修（本 commit 內）— ✅ 2026-06-09 全部修完

1. ✅ L-01：services.rs 加 `python3` fallback
2. ✅ L-02：start_bridge.sh 完整 Linux port（OS 偵測、port_in_use、free_port）
3. ✅ L-03：start_bridge.sh 動態 binary 偵測
4. ✅ L-04：check-env.py 加 Linux install hint（apt/brew/winget 三平台）
5. ✅ L-07：sandbox.rs 加 Linux 9P/overlayfs/容器/snap 警告註解
6. ✅ L-08：config.rs 動態 default 路徑（CLI > ./runtime.toml > /etc/siro/runtime.toml > 預設）
7. ✅ L-09：services.rs PATH 繼承（bridge/hermes subprocess 找得到 hermes）
8. ✅ L-10：services.rs 加 `SIRO_PROJECT_ROOT` env var 動態決定 project root
9. ✅ L-12：寫 `scripts/start_bridge.py` + `stop_bridge.py` 跨平台（os 偵測、Windows/Linux/macOS）
10. ✅ L-14：tools/shell.py blocklist 補 18 條 Linux 危險指令（mount、useradd、iptables、insmod 等）
11. ✅ L-15：i18n 加 locale 自動偵測（Application.systemLanguage + LANG/LC_ALL env var + fallback chain）

### Phase 4 開工時驗證

12. L-11：Unity Linux build 驗證（Cubism SDK、IL2CPP）
13. L-13：headless server 情境（截圖用 Wayland-specific 工具）
14. L-16/17：systemd + kiosk 整合
15. L-18：`verify_gaps4_recovery.py` Linux 實機驗證

---

## 相關文件

- [LIVE2D_AI_AGENT_OS_PLAN.md §Phase 4](../../LIVE2D_AI_AGENT_OS_PLAN.md) — Ubuntu Server 客製化
- [docs/PLANS/agent-computer-control.md](agent-computer-control.md) — v1.5+ tools 設計
- [docs/GAPS.md #1 隱私](../../docs/GAPS.md) — LUKS / age 加密
- [scripts/start_bridge.sh](../../scripts/start_bridge.sh) — Linux shell script
- [scripts/start_bridge.ps1](../../scripts/start_bridge.ps1) — Windows PowerShell

---

**最後一句話**：

Linux port 不是「把 Windows 程式丟到 Linux」 — 是「**從頭設計成 platform-agnostic**」。
本檔列出 18 個點、其中 3 個必修、其餘按時程補。
**現在 Windows 開發、Phase 4 移植時一條一條解掉。**
