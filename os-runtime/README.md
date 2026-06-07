# os-runtime/ - SIRO 系統層 (Rust)

> SIRO 系統 daemon，硬體抽象、進程 supervisor、kiosk 模式。
> 對應計畫書的 [Phase 3](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-3-rust-系統層)。

---

## 當前狀態

**v0.2.0 - Phase 3 前置作業完成**：
- ✅ gRPC 依賴 enable（tonic + prost + tonic-prost-build）
- ✅ build.rs 從 `proto/siro.proto` 生成 Rust stubs
- ✅ `src/grpc.rs` skeleton：所有 RPC 接到 stub、GetStatus + Health 簡單實作
- ✅ chrono dep（給 health started_at 用）
- ⏳ 實際 supervisor / hardware / kiosk 實作 → Phase 3 正式開始時

---

## Workspace 結構

```
os-runtime/
├── Cargo.toml                   # Workspace 根
├── README.md
├── proto/
│   └── siro.proto               # gRPC 介面（與 bridge 共用）
└── crates/
    ├── siro-runtime/            # 主 daemon
    │   ├── Cargo.toml
    │   ├── build.rs             # 從 proto/ 生成 Rust stubs
    │   └── src/
    │       ├── main.rs          # CLI + 啟動 gRPC server
    │       └── grpc.rs          # tonic server trait 實作（stub）
    └── siro-ctl/                # CLI 工具
        ├── Cargo.toml
        └── src/main.rs
```

未來會加：
- `crates/siro-ipc/` 共用 gRPC types
- `crates/siro-supervisor/` 進程監控
- `crates/siro-hardware/` 硬體抽象
- `crates/siro-kiosk/` kiosk 模式控制

---

## 開發

### 前置需求

- **Rust 1.80+**（[rustup.rs](https://rustup.rs/)）
- **protoc 3.x**（Protocol Buffers compiler）— gRPC 程式碼生成用

```bash
# 安裝 Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# 檢查版本
rustc --version  # >= 1.80
cargo --version

# 安裝 protoc
# Ubuntu/Debian
sudo apt install protobuf-compiler

# macOS
brew install protobuf

# Windows（用 choco 或 scoop）
choco install protoc
# 或
scoop install protobuf
```

確認 `protoc --version` 顯示 3.x。

### Build

```bash
cd os-runtime
cargo build
```

**Windows + MinGW**：如果 cargo 報 `link.exe not found` 或 `dbghelp.lib not found`，
表示需要切到 GNU toolchain（詳見下面「Windows 開發指南」）。
```powershell
# 1. 下載 WinLibs MinGW（POSIX + UCRT）
Invoke-WebRequest -Uri "https://github.com/brechtsanders/winlibs_mingw/releases/download/16.1.0posix-14.0.0-ucrt-r2/winlibs-x86_64-posix-seh-gcc-16.1.0-mingw-w64ucrt-14.0.0-r2.zip" -OutFile "$env:TEMP\winlibs.zip"

# 2. 解壓到 user 目錄（避免需要 admin）
Expand-Archive -Path "$env:TEMP\winlibs.zip" -DestinationPath "$env:USERPROFILE\tools\winlibs" -Force

# 3. 切到 GNU toolchain
rustup default stable-gnu

# 4. 加 MinGW 到 PATH（current PowerShell session）
$env:PATH = "$env:USERPROFILE\tools\winlibs\mingw64\bin;$env:PATH"
where.exe gcc   # 應該顯示 mingw64\bin\gcc.exe

# 5. build
cd "C:\coconut chennel\SIRO\os-runtime"
Remove-Item -Recurse -Force target
cargo build
```

Debug build：
```bash
cargo run --bin siro-runtime -- --help
cargo run --bin siro-runtime -- --grpc-addr 127.0.0.1:50051
cargo run --bin siro-ctl -- --help
```

Release build（Phase 3 正式用）：
```bash
cargo build --release
ls target/release/{siro-runtime,siro-ctl}
```

### 測試

```bash
cargo test
```

### Lint

```bash
cargo clippy -- -D warnings
cargo fmt --check
```

### 故障排除

#### `error: failed to load manifest` 或 `protoc not found`

表示 protoc 沒裝好或 PATH 找不到。試：
```bash
which protoc
protoc --version   # 應顯示 3.x
```

如果 protoc 在但 cargo 找不到、設 `PROTOC` 環境變數：
```bash
export PROTOC=/usr/local/bin/protoc
cargo build
```

#### `error: tonic-prost-build not found`

表示 workspace Cargo.toml 沒 enable 那個 dep。確認 [Cargo.toml](Cargo.toml) 有 `tonic-prost-build = "0.12"` 在 `[workspace.dependencies]`。

---

## 設計原則

1. **Zero-cost abstractions** — 用 Rust 的強型別編譯期檢查
2. **Memory safety** — 24/7 跑不 segfault
3. **Async by default** — tokio runtime
4. **Graceful degradation** — 硬體缺失時降級，不 panic
5. **Observable** — structured logging（tracing）
6. **Testable** — 每個模組獨立可測

---

## 與其他層的介接

```
[Layer 3 - siro-runtime (this)]
  ↕ gRPC (50051)
[Layer 2 - bridge (Python)]
  ↕ WebSocket (8001)
[Layer 1 - Unity (C#)]
  ↕ systemd
[Layer 4 - Linux kernel]
```

完整介面契約見 [proto/siro.proto](proto/siro.proto)。
Phase 3 設計決策見 [../docs/ADR/0001-stt-tts-選型.md](../docs/ADR/0001-stt-tts-選型.md)、
[../docs/ADR/0002-subsystem-failure-對話對應.md](../docs/ADR/0002-subsystem-failure-對話對應.md)。

---

## 編譯目標

- **Primary**: `x86_64-unknown-linux-gnu` (Ubuntu 24.04)
- **Phase 6+**: `aarch64-unknown-linux-gnu` (ARM, for Raspberry Pi 部署)

Cross-compile：
```bash
rustup target add aarch64-unknown-linux-gnu
cargo build --release --target aarch64-unknown-linux-gnu
```

---

## 不在當前 v0.2.0 範圍

- ❌ 進程 supervisor（Phase 3 開始時）
- ❌ 硬體偵測（Phase 3 開始時）
- ❌ Kiosk 模式
- ❌ systemd 整合
- ❌ 設定管理
- ❌ 實際 STT/TTS（Phase 5、ADR 0001 已選型）

v0.2.0 已經有：workspace + proto + gRPC server skeleton + 所有 RPC 接到 stub。
Phase 3 正式開始時、就是把 stub 換成實際實作。
