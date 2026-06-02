# os-runtime/ - SIRO 系統層 (Rust)

> SIRO 系統 daemon，硬體抽象、進程 supervisor、kiosk 模式。
> 對應計畫書的 [Phase 3](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-3-rust-系統層)。

---

## 當前狀態

**v0.1.0 - Scaffold**：只有 workspace 結構 + 兩個最小的可運行 binary。

完整實作從 [Phase 3](../LIVE2D_AI_AGENT_OS_PLAN.md#phase-3-rust-系統層) 開始，預計 3-4 週。

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
    │   └── src/main.rs
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
- **protoc**（Protocol Buffers compiler）— gRPC 程式碼生成用

```bash
# 安裝 Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# 檢查版本
rustc --version  # >= 1.80
cargo --version

# 安裝 protoc (Ubuntu)
sudo apt install protobuf-compiler
```

### Build

```bash
cd os-runtime
cargo build
```

Debug build：
```bash
cargo run --bin siro-runtime -- --help
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

## 不在當前 v0.1.0 範圍

- ❌ gRPC server（proto 已定義，實作在 Phase 3）
- ❌ 進程 supervisor
- ❌ 硬體偵測
- ❌ Kiosk 模式
- ❌ systemd 整合
- ❌ 設定管理

這些是 Phase 3 的工作。現在只有 workspace 結構 + placeholder binary。
