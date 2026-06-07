//! siro-runtime - SIRO 系統層主 daemon
//!
//! v0.1.0: 最小可運行版本，純 CLI 啟動 + 印版本。
//! v0.2.0: 加上 gRPC server 雛形、所有 RPC 接到 stub
//! v0.3.0 (Phase 3 supervisor 啟動): 加上 process supervisor
//!          監控 bridge / hermes / unity、auto-restart、暴露 gRPC API

mod event_bus;
mod grpc;
mod services;
mod supervisor;
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
    /// 設定檔路徑（v0.3.0 還沒實作讀檔、用預設 services）
    #[arg(short, long, default_value = "/etc/siro/runtime.toml")]
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

    info!("{} v{} starting up", NAME, VERSION);
    info!("config path: {}", args.config);
    info!("dry_run: {}", args.dry_run);
    info!("grpc_addr: {}", args.grpc_addr);
    info!("auto_start: {}", auto_start);

    if args.dry_run {
        info!("[dry-run] 不會啟動任何服務");
        println!("siro-runtime v{} (dry-run)", VERSION);
        println!("  would listen gRPC on: {}", args.grpc_addr);
        println!("  would monitor services:");
        let project_root = std::env::current_dir()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| PathBuf::from("."));
        for def in services::default_services(&project_root) {
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

    // 建立 supervisor（內含 3 個預設 services）
    let service_defs = services::default_services(&project_root);
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
