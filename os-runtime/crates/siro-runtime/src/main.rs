//! siro-runtime - SIRO 系統層主 daemon
//!
//! v0.1.0: 最小可運行版本，純 CLI 啟動 + 印版本。
//! v0.2.0 (Phase 3 前置): 加上 gRPC server 雛形、所有 RPC 接到 stub
//! Phase 3 開始才會擴充 supervisor、硬體抽象、process 監控等。

mod grpc;
pub use grpc::generated as proto;

use clap::Parser;
use tracing::info;
use tracing_subscriber::EnvFilter;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const NAME: &str = env!("CARGO_PKG_NAME");

#[derive(Parser, Debug)]
#[command(name = "siro-runtime", version, about = "SIRO 系統層主 daemon")]
struct Args {
    /// 設定檔路徑
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

    info!("{} v{} starting up", NAME, VERSION);
    info!("config path: {}", args.config);
    info!("dry_run: {}", args.dry_run);
    info!("grpc_addr: {}", args.grpc_addr);

    if args.dry_run {
        info!("[dry-run] 不會啟動任何服務");
        println!("siro-runtime v{} (dry-run)", VERSION);
        println!("  would listen gRPC on: {}", args.grpc_addr);
        return Ok(());
    }

    // Phase 3 前置：spawn gRPC server（用 tonic 跑在 tokio runtime）
    // 現階段所有 RPC 接到 stub、只 echo 訊息確認 protocol 通了
    // Phase 3 正式開始時把這段換成 supervisor + 實際 service 監控
    let grpc_addr = args.grpc_addr.clone();
    let server = grpc::SiroRuntimeServer::new();

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        let addr = grpc_addr.parse::<std::net::SocketAddr>()
            .expect("無法 parse grpc_addr");

        info!("gRPC server 啟動中、addr={}", addr);

        let svc = proto::siro_runtime_server::SiroRuntimeServer::new(server);

        tonic::transport::Server::builder()
            .add_service(svc)
            .serve(addr)
            .await?;

        Ok::<(), anyhow::Error>(())
    })?;

    Ok(())
}
