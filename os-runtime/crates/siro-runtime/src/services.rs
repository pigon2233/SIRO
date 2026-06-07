// src/services.rs - SIRO subsystem 服務定義
//
// v0.3.0 MVP：hardcode 預設 services、未來從 runtime.toml 讀
//
// 對應 [ADR 0002](../docs/ADR/0002-subsystem-failure-對話對應.md) 12 個 subsystem。
// v0.3.0 先實作 supervisor 監控最關鍵的 3 個：bridge / hermes / unity。

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

/// 一個 service 的靜態定義（從 config 載入、不會變）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceDef {
    /// 服務名字（siro-ctl status 用、也當 gRPC key）
    pub name: String,

    /// 啟動指令（binary 或腳本）
    pub command: String,

    /// 命令列參數
    #[serde(default)]
    pub args: Vec<String>,

    /// 工作目錄（None = 繼承 siro-runtime cwd）
    #[serde(default)]
    pub working_dir: Option<String>,

    /// 環境變數
    #[serde(default)]
    pub env: HashMap<String, String>,

    /// 死了是否自動重啟
    #[serde(default = "default_true")]
    pub auto_restart: bool,

    /// 重啟冷卻時間（秒）
    #[serde(default = "default_restart_delay")]
    pub restart_delay_sec: u32,

    /// 健康檢查間隔（秒、sysinfo 抓 PID 是否還活著）
    #[serde(default = "default_health_interval")]
    pub health_check_interval_sec: u32,

    /// 最多重啟次數（0 = 無限）
    #[serde(default)]
    pub max_restarts: u32,
}

fn default_true() -> bool {
    true
}
fn default_restart_delay() -> u32 {
    5
}
fn default_health_interval() -> u32 {
    10
}

/// 預設 services（v0.3.0 MVP：bridge + hermes + unity = 3 個）
/// 注意：路徑是從 os-runtime/ 跑時的相對路徑
///   - bridge.main 在 ../bridge/main.py
///   - hermes binary 假設在 PATH
///   - unity 透過 launch 腳本（未來 Phase 4 改成 kiosk 整合）
pub fn default_services(project_root: &PathBuf) -> Vec<ServiceDef> {
    vec![
        ServiceDef {
            name: "bridge".to_string(),
            command: "python".to_string(),
            args: vec!["-m".to_string(), "bridge.main".to_string()],
            working_dir: Some(project_root.join("bridge").to_string_lossy().to_string()),
            env: HashMap::from([
                // Python 找得到 SIRO 模組
                ("PYTHONPATH".to_string(), project_root.to_string_lossy().to_string()),
                // v0.3.0 預設 streaming 開（跟 run-bridge.ps1 一致）
                ("SIRO_STREAMING".to_string(), "true".to_string()),
                ("SIRO_USE_AGENT_OS".to_string(), "true".to_string()),
            ]),
            auto_restart: true,
            restart_delay_sec: 3,
            health_check_interval_sec: 10,
            max_restarts: 0,  // 永遠重啟
        },
        ServiceDef {
            name: "hermes".to_string(),
            command: "hermes".to_string(),
            args: vec![],
            working_dir: None,  // 用 siro-runtime 的 cwd
            env: HashMap::new(),
            auto_restart: true,
            restart_delay_sec: 10,
            health_check_interval_sec: 30,
            max_restarts: 0,
        },
        ServiceDef {
            name: "unity".to_string(),
            // v0.3.0：Unity 自己有 auto-restart（kiosk 模式）、
            // 這裡只 log + 提供查詢介面
            // 真正的 Unity launcher 寫在未來 Phase 4
            command: "echo".to_string(),
            args: vec!["Unity supervisor placeholder - see ADR 0002".to_string()],
            working_dir: None,
            env: HashMap::new(),
            auto_restart: false,  // v0.3.0 placeholder
            restart_delay_sec: 5,
            health_check_interval_sec: 30,
            max_restarts: 0,
        },
    ]
}
