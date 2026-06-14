//! os-runtime/src/config.rs - 設定檔讀寫
//!
//! v0.4.0+：從 `/etc/siro/runtime.toml` 或 `--config` 指定的 TOML 讀設定。
//! 找不到檔案時用預設值（v0.3.0 行為），向後相容。
//!
//! 設定 schema（runtime.toml）：
//! ```toml
//! [server]
//! grpc_addr = "127.0.0.1:50051"
//! unix_socket = "/var/run/siro/runtime.sock"  # optional
//!
//! [supervisor]
//! check_interval_ms = 1000
//! max_restart_attempts = 5
//! restart_backoff_ms = 2000
//!
//! [hardware]
//! audio_device = "default"
//! camera_device = "/dev/video0"
//! display = ":0"
//!
//! [kiosk]
//! enabled = false
//! block_keyboard = true
//! escape_password = ""
//! ```

use std::path::Path;

use figment::providers::{Format, Toml};
use figment::Figment;
use serde::{Deserialize, Serialize};

use crate::services::ServiceDef;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    #[serde(default = "default_grpc_addr")]
    pub grpc_addr: String,
    #[serde(default)]
    pub unix_socket: Option<String>,
}

fn default_grpc_addr() -> String {
    "127.0.0.1:50051".to_string()
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            grpc_addr: default_grpc_addr(),
            unix_socket: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SupervisorConfig {
    #[serde(default = "default_check_interval")]
    pub check_interval_ms: u64,
    #[serde(default = "default_max_restart_attempts")]
    pub max_restart_attempts: u32,
    #[serde(default = "default_restart_backoff")]
    pub restart_backoff_ms: u64,
}

fn default_check_interval() -> u64 {
    1000
}
fn default_max_restart_attempts() -> u32 {
    5
}
fn default_restart_backoff() -> u64 {
    2000
}

impl Default for SupervisorConfig {
    fn default() -> Self {
        Self {
            check_interval_ms: default_check_interval(),
            max_restart_attempts: default_max_restart_attempts(),
            restart_backoff_ms: default_restart_backoff(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct HardwareConfig {
    #[serde(default)]
    pub audio_device: Option<String>,
    #[serde(default)]
    pub camera_device: Option<String>,
    #[serde(default)]
    pub display: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KioskConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_true")]
    pub block_keyboard: bool,
    #[serde(default)]
    pub escape_password: String,
}

fn default_true() -> bool {
    true
}

impl Default for KioskConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            block_keyboard: true,
            escape_password: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RuntimeConfig {
    #[serde(default)]
    pub server: ServerConfig,
    #[serde(default)]
    pub supervisor: SupervisorConfig,
    #[serde(default)]
    pub hardware: HardwareConfig,
    #[serde(default)]
    pub kiosk: KioskConfig,
    /// 自訂 services 列表（沒填就用 default_services 預設 3 個）
    #[serde(default)]
    pub services: Vec<ServiceDef>,
}

impl RuntimeConfig {
    /// 從指定路徑讀設定
    /// - 檔案不存在 → 用 Default（向後相容 v0.3.0）
    /// - 檔案存在但 parse 失敗 → 噴 error（fail-fast）
    /// - 部分 section 缺 → 用那 section 的 Default
    pub fn load(path: &Path) -> Result<Self, figment::Error> {
        if !path.exists() {
            tracing::info!(
                "config: {} 不存在、用預設值（向後相容 v0.3.0）",
                path.display()
            );
            return Ok(RuntimeConfig::default());
        }

        tracing::info!("config: 讀取 {}", path.display());
        let config: RuntimeConfig = Figment::new()
            .merge(Toml::file(path))
            .extract()?;
        Ok(config)
    }

    /// 寫範例設定檔（給第一次安裝時用、`siro-ctl init` 呼叫）
    #[allow(dead_code)]
    pub fn write_example(path: &Path) -> std::io::Result<()> {
        let example = r#"# SIRO runtime config（v0.4+）
# 安裝時可以 cp 這個範例到 /etc/siro/runtime.toml 再改

[server]
grpc_addr = "127.0.0.1:50051"
# unix_socket = "/var/run/siro/runtime.sock"  # optional

[supervisor]
check_interval_ms = 1000
max_restart_attempts = 5      # 0 = 無限
restart_backoff_ms = 2000

[hardware]
# audio_device = "default"
# camera_device = "/dev/video0"
# display = ":0"

[kiosk]
enabled = false
block_keyboard = true
# escape_password = "siro-admin-2026"

# 自訂 services（不填則用預設 3 個: bridge / hermes / unity）
# [[services]]
# name = "my-service"
# command = "/usr/bin/my-svc"
# args = ["--config", "/etc/my-svc.conf"]
# working_dir = "/var/lib/my-svc"
# [services.env]
# LOG_LEVEL = "info"
# auto_restart = true
# restart_delay_sec = 5
# health_check_interval_sec = 10
# max_restarts = 0
"#;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, example)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn default_config_has_sane_values() {
        let c = RuntimeConfig::default();
        assert_eq!(c.server.grpc_addr, "127.0.0.1:50051");
        assert_eq!(c.supervisor.check_interval_ms, 1000);
        assert_eq!(c.supervisor.max_restart_attempts, 5);
        assert_eq!(c.kiosk.block_keyboard, true);
        assert!(c.services.is_empty());
    }

    #[test]
    fn load_missing_file_returns_default() {
        let path = Path::new("/tmp/siro_nonexistent_config_xxx.toml");
        let c = RuntimeConfig::load(path).expect("missing file → default OK");
        assert_eq!(c.server.grpc_addr, "127.0.0.1:50051");
    }

    #[test]
    fn load_partial_toml_uses_defaults_for_missing_sections() {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(f, "[server]\ngrpc_addr = \"0.0.0.0:60000\"").unwrap();
        let c = RuntimeConfig::load(f.path()).expect("partial parse OK");
        assert_eq!(c.server.grpc_addr, "0.0.0.0:60000");
        assert_eq!(c.supervisor.check_interval_ms, 1000); // default
        assert_eq!(c.kiosk.block_keyboard, true); // default
    }

    #[test]
    fn load_full_toml() {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        writeln!(
            f,
            r#"
[server]
grpc_addr = "192.168.1.1:50051"

[supervisor]
check_interval_ms = 500
max_restart_attempts = 10
restart_backoff_ms = 1000

[kiosk]
enabled = true
block_keyboard = false
escape_password = "secret"
"#
        )
        .unwrap();
        let c = RuntimeConfig::load(f.path()).unwrap();
        assert_eq!(c.server.grpc_addr, "192.168.1.1:50051");
        assert_eq!(c.supervisor.check_interval_ms, 500);
        assert!(c.kiosk.enabled);
        assert!(!c.kiosk.block_keyboard);
        assert_eq!(c.kiosk.escape_password, "secret");
    }

    #[test]
    fn write_example_creates_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("runtime.toml");
        RuntimeConfig::write_example(&path).unwrap();
        let content = std::fs::read_to_string(&path).unwrap();
        assert!(content.contains("[server]"));
        assert!(content.contains("[kiosk]"));
    }
}
