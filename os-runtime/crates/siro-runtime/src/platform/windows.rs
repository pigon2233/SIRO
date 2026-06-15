// src/platform/windows.rs - Windows 路徑實作
//
// 用 `directories` crate 5.x 拿 OS 標準路徑。
// Windows 上 ProjectDirs 用 %LOCALAPPDATA% (CSIDL_LOCAL_APPDATA)。
// 對應 Python 端: bridge/platform/paths.py

use std::path::PathBuf;

use super::PlatformPaths;

pub struct WindowsPaths;

impl PlatformPaths for WindowsPaths {
    fn user_data_dir() -> PathBuf {
        directories::ProjectDirs::from("siro", "SIRO", "SIRO")
            .expect("Windows always has a ProjectDirs")
            .data_dir()
            .to_path_buf()
    }

    fn user_config_dir() -> PathBuf {
        directories::ProjectDirs::from("siro", "SIRO", "SIRO")
            .expect("Windows always has a ProjectDirs")
            .config_dir()
            .to_path_buf()
    }

    fn user_log_dir() -> PathBuf {
        directories::ProjectDirs::from("siro", "SIRO", "SIRO")
            .expect("Windows always has a ProjectDirs")
            .data_local_dir()
            .join("logs")
    }

    fn runtime_socket_path() -> String {
        // Windows 走 gRPC over TCP 127.0.0.1:50051 (default)
        // 用 env var 覆寫（SIRO_RUNTIME_SOCKET）
        std::env::var("SIRO_RUNTIME_SOCKET")
            .unwrap_or_else(|_| "127.0.0.1:50051".to_string())
    }

    fn siro_sandbox_dir() -> PathBuf {
        // SIRO_SANDBOX_DIR env var 覆寫 (測試常用)
        if let Ok(env_path) = std::env::var("SIRO_SANDBOX_DIR") {
            return PathBuf::from(env_path);
        }
        dirs_home().join("siro-sandbox")
    }
}

/// 跨 OS 拿 home dir（用 std::env 避免再 depend on `dirs` crate）
fn dirs_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}
