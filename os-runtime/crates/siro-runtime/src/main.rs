//! siro-runtime - SIRO 系統層主 daemon
//!
//! v0.1.0: 最小可運行版本，純 CLI 啟動 + 印版本。
//! Phase 3 開始才會擴充 supervisor、gRPC、硬體抽象等。

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

    if args.dry_run {
        info!("[dry-run] 不會啟動任何服務");
        println!("siro-runtime v{} (dry-run)", VERSION);
        return Ok(());
    }

    // v0.1.0: 純 placeholder，印個訊息就結束
    // Phase 3 會擴充：
    //   - 載入設定
    //   - 啟動 supervisor
    //   - 啟動 gRPC server
    //   - 註冊 systemd watchdog
    println!("siro-runtime v{}", VERSION);
    println!("(v0.1.0 - placeholder, Phase 3 將實作 supervisor)");

    Ok(())
}
