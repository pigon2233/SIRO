//! siro-ctl - SIRO 控制 CLI
//!
//! v0.1.0: 純 CLI 框架，列出可用子命令。
//! Phase 3 會實作 gRPC client 跟 siro-runtime 通訊。

use clap::{Parser, Subcommand};
use tracing::info;
use tracing_subscriber::EnvFilter;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const NAME: &str = env!("CARGO_PKG_NAME");

#[derive(Parser, Debug)]
#[command(name = "siro-ctl", version, about = "SIRO 控制 CLI 工具")]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// 顯示所有服務狀態
    Status,

    /// 重啟指定服務
    Restart {
        /// 服務名稱（bridge, hermes, unity, runtime）
        service: String,
    },

    /// 顯示硬體資訊
    Hardware,

    /// 切換 kiosk 模式
    Kiosk {
        /// enable / disable
        action: String,
    },

    /// 健康檢查
    Health,
}

fn main() -> anyhow::Result<()> {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .init();

    let args = Args::parse();

    info!("{} v{}", NAME, VERSION);

    match args.command {
        Command::Status => {
            println!("[status] 尚未實作（Phase 3）");
        }
        Command::Restart { service } => {
            println!("[restart {}] 尚未實作（Phase 3）", service);
        }
        Command::Hardware => {
            println!("[hardware] 尚未實作（Phase 3）");
        }
        Command::Kiosk { action } => {
            println!("[kiosk {}] 尚未實作（Phase 3）", action);
        }
        Command::Health => {
            println!("[health] 尚未實作（Phase 3）");
        }
    }

    Ok(())
}
