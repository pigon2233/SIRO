//! siro-runtime - SIRO 系統層主 daemon
//!
//! v0.1.0: 最小可運行版本，純 CLI 啟動 + 印版本。
//! v0.2.0: 加上 gRPC server 雛形、所有 RPC 接到 stub
//! v0.3.0 (Phase 3 supervisor 啟動): 加上 process supervisor
//!          監控 bridge / hermes / unity、auto-restart、暴露 gRPC API

mod config;
mod event_bus;
mod grpc;
mod hardware;
mod services;
mod supervisor;
// v1.5.3 Computer Control modules
mod sandbox;
mod commands;
mod fs_ops;
pub use grpc::generated as proto;

use std::path::PathBuf;
use std::sync::Arc;

use clap::Parser;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const NAME: &str = env!("CARGO_PKG_NAME");

#[derive(Parser, Debug)]
#[command(name = "siro-runtime", version, about = "SIRO 系統層主 daemon")]
struct Args {
    /// 設定檔路徑（v0.4+ 動態偵測、留空用 fallback 順序）
    /// 1. CLI 參數 `--config /path/to/runtime.toml`
    /// 2. cwd 下的 `./runtime.toml`
    /// 3. `/etc/siro/runtime.toml`（Linux 標準）
    /// 4. 都沒有 → 全部用預設值（向後相容 v0.3.0）
    #[arg(short, long, default_value = "")]
    config: String,

    /// 開啟 verbose log
    #[arg(short, long)]
    verbose: bool,

    /// 跑一次 dry-run，印出會做的事但不執行
    #[arg(long)]
    dry_run: bool,

    /// gRPC server 監聽位址
    #[arg(long, default_value = "127.0.0.1:50051")]
    grpc_addr: String,

    /// 是否啟動時自動 start 所有 services
    /// false = 只 monitor、不主動啟動（siro-ctl 手動控制）
    /// true = 啟動時自動跑所有 auto_restart 的 service（kiosk 模式）
    /// 預設 true；用 --auto-start=false 跳過
    #[arg(long, value_name = "BOOL", action = clap::ArgAction::Set)]
    auto_start: Option<bool>,
}

fn main() -> anyhow::Result<()> {
    // 初始化 logging
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .init();

    let args = Args::parse();
    let auto_start = args.auto_start.unwrap_or(true);

    // v0.4+：動態找設定檔（CLI > cwd > /etc/siro > 預設）
    let config_path = if !args.config.is_empty() {
        std::path::PathBuf::from(&args.config)
    } else {
        // 順序找
        let candidates = [
            std::path::PathBuf::from("./runtime.toml"),
            std::path::PathBuf::from("/etc/siro/runtime.toml"),
        ];
        candidates
            .into_iter()
            .find(|p| p.exists())
            .unwrap_or_else(|| std::path::PathBuf::from("/etc/siro/runtime.toml"))
    };
    let runtime_config = match config::RuntimeConfig::load(&config_path) {
        Ok(c) => c,
        Err(e) => {
            error!("config 解析失敗 {}: {}", config_path.display(), e);
            return Err(e.into());
        }
    };

    info!("{} v{} starting up", NAME, VERSION);
    info!("config path: {}", config_path.display());
    info!("dry_run: {}", args.dry_run);
    info!("grpc_addr: {} (from {})", args.grpc_addr,
        if runtime_config.server.grpc_addr == args.grpc_addr { "config" } else { "CLI override" });
    info!("auto_start: {}", auto_start);
    info!("kiosk.enabled: {}", runtime_config.kiosk.enabled);
    info!("supervisor.check_interval_ms: {}", runtime_config.supervisor.check_interval_ms);

    if args.dry_run {
        info!("[dry-run] 不會啟動任何服務");
        println!("siro-runtime v{} (dry-run)", VERSION);
        println!("  config: {}", config_path.display());
        println!("  would listen gRPC on: {}", args.grpc_addr);
        println!("  would monitor services:");
        let project_root = std::env::current_dir()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| PathBuf::from("."));
        let defs = if runtime_config.services.is_empty() {
            services::default_services(&project_root)
        } else {
            runtime_config.services.clone()
        };
        for def in defs {
            println!("    - {} ({} {:?})", def.name, def.command, def.args);
        }
        return Ok(());
    }

    // 計算 project root（os-runtime/ 的 parent、也就是 SIRO/）
    let project_root = std::env::current_dir()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));
    info!("project_root: {}", project_root.display());

    // v0.4+：優先用 config 裡的 services、沒有就用 default
    let service_defs = if runtime_config.services.is_empty() {
        services::default_services(&project_root)
    } else {
        runtime_config.services.clone()
    };
    info!("loaded {} services:", service_defs.len());
    for def in &service_defs {
        info!("  - {} (cmd={} args={:?})", def.name, def.command, def.args);
    }
    let grpc_addr = args.grpc_addr.clone();

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        // v0.3.0：建立 event/log bus（給 stream_logs + subscribe_events 用）
        let buses = event_bus::Buses::new();

        // supervisor 跟所有 tokio::spawn 都在 runtime 內建立
        // （修正原本 sync main 先 spawn 再建 runtime 會 panic 的 bug）
        let supervisor = Arc::new(supervisor::Supervisor::new(service_defs, buses.clone()));

        // 啟動 background monitor task
        supervisor.spawn_monitor();

        // 自動啟動所有 auto_restart 的 services
        if auto_start {
            let snapshots = supervisor.snapshot().await;
            let services_to_start: Vec<String> = snapshots
                .into_iter()
                .filter(|s| matches!(s.status, supervisor::ServiceStatus::Stopped))
                .map(|s| s.name)
                .collect();
            for name in services_to_start {
                let supervisor_clone = supervisor.clone();
                tokio::spawn(async move {
                    if let Err(e) = supervisor_clone.start(&name).await {
                        error!("[auto-start] {} 啟動失敗: {}", name, e);
                    } else {
                        info!("[auto-start] {} 啟動成功", name);
                    }
                });
            }
        }

        // 啟動 gRPC server
        let addr = grpc_addr.parse::<std::net::SocketAddr>()
            .expect("無法 parse grpc_addr");
        info!("gRPC server 啟動中、addr={}", addr);

        let server = grpc::SiroRuntimeServer::new(supervisor.clone(), buses.clone());
        let svc = proto::siro_runtime_server::SiroRuntimeServer::new(server);
        let server_handle = tokio::spawn(async move {
            if let Err(e) = tonic::transport::Server::builder()
                .add_service(svc)
                .serve(addr)
                .await
            {
                error!("gRPC server 錯誤: {}", e);
            }
        });

        // 等待 Ctrl+C 或 server 掛掉
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                info!("收到 Ctrl+C、開始 shutdown");
            }
            _ = server_handle => {
                warn!("gRPC server 意外結束");
            }
        }

        // 優雅 shutdown
        supervisor.shutdown().await;
        info!("shutdown 完成、bye");
    });

    Ok(())
}
