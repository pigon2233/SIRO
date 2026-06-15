// src/platform/mod.rs - 跨平台抽象層 (v0.5 Desktop Assistant)
//
// 業務邏輯禁止直接呼叫 directories::UserDirs 或寫死 OS-specific path。
// 統一從這裡拿路徑，跟 bridge/platform/paths.py 對齊。
//
// 對應 Python 端: bridge/platform/paths.py
// Linux 化時補:   src/platform/linux.rs
// macOS 化時補:   src/platform/macos.rs

use std::path::PathBuf;

#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
pub use windows::WindowsPaths as PlatformPathsImpl;

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::LinuxPaths as PlatformPathsImpl;

#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "macos")]
pub use macos::MacosPaths as PlatformPathsImpl;

/// SIRO 跨平台路徑抽象介面
///
/// 業務邏輯應透過 `PlatformPaths::xxx()` 拿路徑，不要直接呼叫
/// `directories::ProjectDirs::from(...)` 或寫死 `~/.local/share/siro/`。
pub trait PlatformPaths {
    /// SIRO 使用者資料目錄 (DB / state / config 預設放這)
    /// - Windows: %LOCALAPPDATA%\SIRO\
    /// - Linux:   $XDG_DATA_HOME/siro/ (default ~/.local/share/siro/)
    /// - macOS:   ~/Library/Application Support/SIRO/
    fn user_data_dir() -> PathBuf;

    /// SIRO 使用者設定目錄
    /// - Windows: %LOCALAPPDATA%\SIRO\
    /// - Linux:   $XDG_CONFIG_HOME/siro/ (default ~/.config/siro/)
    /// - macOS:   ~/Library/Application Support/SIRO/
    fn user_config_dir() -> PathBuf;

    /// SIRO 使用者 log 目錄
    /// - Windows: %LOCALAPPDATA%\SIRO\logs\
    /// - Linux:   $XDG_STATE_HOME/siro/log/ (default ~/.local/state/siro/log/)
    /// - macOS:   ~/Library/Logs/SIRO/
    fn user_log_dir() -> PathBuf;

    /// siro-runtime 的 IPC 路徑（gRPC socket / named pipe）
    /// - Windows: 走 gRPC over TCP 127.0.0.1:50051,回傳 host:port 字串
    /// - Linux:   $XDG_RUNTIME_DIR/siro/runtime.sock 或 /tmp/siro-runtime.sock
    /// - macOS:   ~/Library/Application Support/SIRO/runtime.sock
    fn runtime_socket_path() -> String;

    /// SIRO 預設 sandbox 目錄（LLM tool 操作範圍）
    /// - 全部 OS: ~/siro-sandbox
    fn siro_sandbox_dir() -> PathBuf;
}

// 業務邏輯用法範例:
//   use crate::platform::{PlatformPaths, PlatformPathsImpl};
//   let data_dir = PlatformPathsImpl::user_data_dir();
//
// `PlatformPathsImpl` 已經透過上面的 `cfg` 條件 `pub use ... as PlatformPathsImpl`
// expose 出來,業務邏輯可直接 `use crate::platform::PlatformPathsImpl;` 使用。
