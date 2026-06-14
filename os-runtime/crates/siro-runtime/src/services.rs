// src/services.rs - SIRO subsystem 服務定義
//
// v0.3.0 MVP：hardcode 預設 services、未來從 runtime.toml 讀
//
// 對應 [ADR 0002](../docs/ADR/0002-subsystem-failure-對話對應.md) 12 個 subsystem。
// v0.3.0 先實作 supervisor 監控最關鍵的 3 個：bridge / hermes / unity。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

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
///
/// v0.4+ Linux 對應：
///   - Python 用 `python3` 優先（Ubuntu/Debian 預設）
///   - 沒 python3 才 fallback `python`
///   - 留 SIRO_PYTHON_BIN env var 覆蓋（venv 路徑）
pub fn find_python_bin() -> String {
    if let Ok(p) = std::env::var("SIRO_PYTHON_BIN") {
        return p;
    }
    // Linux 標準：python3
    #[cfg(target_os = "linux")]
    {
        for cand in &["python3", "python"] {
            if std::process::Command::new(cand)
                .arg("--version")
                .output()
                .is_ok()
            {
                return cand.to_string();
            }
        }
    }
    // Windows / macOS：python 通常指對
    #[cfg(not(target_os = "linux"))]
    {
        for cand in &["python", "python3"] {
            if std::process::Command::new(cand)
                .arg("--version")
                .output()
                .is_ok()
            {
                return cand.to_string();
            }
        }
    }
    // 預設（Linux 標準、因為 Phase 4 重點是 Linux）
    "python3".to_string()
}

/// 抓 siro-runtime 自己的 PATH（subprocess 需要繼承）
fn inherit_path() -> String {
    std::env::var("PATH").unwrap_or_default()
}

/// v0.4+：動態決定 project root（給 systemd / 容器用）
/// 順序：
/// 1. `SIRO_PROJECT_ROOT` env var（最精準）
/// 2. 從 cwd 推（開發時從 os-runtime/ 或 SIRO/ 跑）
pub fn resolve_project_root() -> PathBuf {
    // 1. env var 最高優先
    if let Ok(p) = std::env::var("SIRO_PROJECT_ROOT") {
        let p = PathBuf::from(p);
        if p.exists() {
            tracing::info!("project_root: 從 SIRO_PROJECT_ROOT={}", p.display());
            return p;
        }
        eprintln!(
            "warning: SIRO_PROJECT_ROOT={} 不存在、fallback 到 cwd 偵測",
            p.display()
        );
    }

    // 2. 從 cwd 推
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    // 如果 cwd 是 os-runtime/、parent 就是 SIRO/
    if cwd.file_name().map(|n| n == "os-runtime").unwrap_or(false) {
        if let Some(parent) = cwd.parent() {
            tracing::info!("project_root: 從 cwd.parent()={}", parent.display());
            return parent.to_path_buf();
        }
    }
    // 如果 cwd 是 SIRO/、cwd 就是 root
    if cwd.join("bridge").exists() && cwd.join("os-runtime").exists() {
        tracing::info!("project_root: 從 cwd={}", cwd.display());
        return cwd;
    }
    // Fallback：parent of cwd
    let fallback = cwd.parent().map(|p| p.to_path_buf()).unwrap_or(cwd);
    tracing::warn!(
        "project_root: 從 cwd.parent() fallback={}",
        fallback.display()
    );
    fallback
}

pub fn default_services(project_root: &Path) -> Vec<ServiceDef> {
    let python_bin = find_python_bin();
    let path = inherit_path();
    // v0.4+：project_root 支援 env var 覆蓋（給 systemd / 容器用）
    let project_root = if std::env::var("SIRO_PROJECT_ROOT").is_ok() {
        resolve_project_root()
    } else {
        project_root.to_path_buf()
    };
    vec![
        ServiceDef {
            name: "bridge".to_string(),
            command: python_bin.clone(),
            args: vec!["-m".to_string(), "bridge.main".to_string()],
            working_dir: Some(project_root.join("bridge").to_string_lossy().to_string()),
            env: HashMap::from([
                // v0.4+：subprocess 繼承 siro-runtime 的 PATH（找得到 hermes / 系統工具）
                ("PATH".to_string(), path),
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
            env: HashMap::from([
                // v0.4+：hermes 也繼承 PATH（find hermes 找得到）
                ("PATH".to_string(), inherit_path()),
            ]),
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
