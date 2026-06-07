//! siro-ctl - SIRO 控制 CLI
//!
//! v0.3.0 (Phase 3 supervisor 啟動):
//! - gRPC client 連 siro-runtime
//! - subcommand 對應 proto ServiceControl (start/stop/restart)
//! - status / hardware / health / kiosk 對應 proto RPC

use clap::{Parser, Subcommand};
use std::time::Duration;
use tonic::transport::Channel;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

pub mod proto {
    tonic::include_proto!("siro.runtime.v1");
}

use proto::siro_runtime_client::SiroRuntimeClient;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const NAME: &str = env!("CARGO_PKG_NAME");

#[derive(Parser, Debug)]
#[command(name = "siro-ctl", version, about = "SIRO 控制 CLI 工具")]
struct Args {
    /// siro-runtime gRPC 位址
    #[arg(long, default_value = "http://127.0.0.1:50051")]
    addr: String,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// 顯示所有服務狀態
    Status,

    /// 啟動指定服務
    Start {
        service: String,
    },

    /// 停止指定服務
    Stop {
        service: String,
    },

    /// 重啟指定服務
    Restart {
        service: String,
    },

    /// 顯示硬體資訊
    Hardware,

    /// 健康檢查
    Health,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .init();

    let args = Args::parse();

    info!("{} v{} connecting to {}", NAME, VERSION, args.addr);

    // 連 siro-runtime（設 5 秒 timeout 避免卡住）
    let endpoint = Channel::from_shared(args.addr.clone())?
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(10));
    let channel = endpoint.connect().await?;
    let mut client = SiroRuntimeClient::new(channel);

    match args.command {
        Command::Status => {
            let req = tonic::Request::new(proto::Empty {});
            match client.get_status(req).await {
                Ok(resp) => {
                    let status = resp.into_inner();
                    println!("=== SIRO System Status ===");
                    if status.services.is_empty() {
                        println!("(no services registered)");
                    }
                    let mut names: Vec<&String> = status.services.keys().collect();
                    names.sort();
                    for name in names {
                        let s = &status.services[name];
                        let status_str = match s.status {
                            x if x == proto::service_state::ServiceStatus::Running as i32 => "running",
                            x if x == proto::service_state::ServiceStatus::Stopped as i32 => "stopped",
                            x if x == proto::service_state::ServiceStatus::Failed as i32 => "failed",
                            x if x == proto::service_state::ServiceStatus::Starting as i32 => "starting",
                            x if x == proto::service_state::ServiceStatus::Stopping as i32 => "stopping",
                            _ => "unknown",
                        };
                        let pid = if s.pid > 0 { format!("pid={}", s.pid) } else { String::new() };
                        let mem = if s.memory_bytes > 0 {
                            format!(", mem={} MB", s.memory_bytes / 1024 / 1024)
                        } else { String::new() };
                        let err = if !s.last_error.is_empty() {
                            format!(", err={}", s.last_error)
                        } else { String::new() };
                        println!("  {:12} {:10} {}{}{}",
                            name, status_str, pid, mem, err);
                    }
                }
                Err(e) => {
                    error!("get_status 失敗: {}", e);
                    std::process::exit(1);
                }
            }
        }
        Command::Start { service } => {
            use proto::service_control::ServiceAction;
            let req = tonic::Request::new(proto::ServiceControl {
                name: service.clone(),
                action: ServiceAction::Start as i32,
            });
            match client.control_service(req).await {
                Ok(resp) => {
                    let ack = resp.into_inner();
                    println!("[{}] {}", if ack.ok { "OK" } else { "FAIL" }, ack.message);
                    if !ack.ok { std::process::exit(1); }
                }
                Err(e) => { error!("start 失敗: {}", e); std::process::exit(1); }
            }
        }
        Command::Stop { service } => {
            use proto::service_control::ServiceAction;
            let req = tonic::Request::new(proto::ServiceControl {
                name: service.clone(),
                action: ServiceAction::Stop as i32,
            });
            match client.control_service(req).await {
                Ok(resp) => {
                    let ack = resp.into_inner();
                    println!("[{}] {}", if ack.ok { "OK" } else { "FAIL" }, ack.message);
                    if !ack.ok { std::process::exit(1); }
                }
                Err(e) => { error!("stop 失敗: {}", e); std::process::exit(1); }
            }
        }
        Command::Restart { service } => {
            let req = tonic::Request::new(proto::ServiceName { name: service.clone() });
            match client.restart_service(req).await {
                Ok(resp) => {
                    let ack = resp.into_inner();
                    println!("[{}] {}", if ack.ok { "OK" } else { "FAIL" }, ack.message);
                    if !ack.ok { std::process::exit(1); }
                }
                Err(e) => { error!("restart 失敗: {}", e); std::process::exit(1); }
            }
        }
        Command::Hardware => {
            let req = tonic::Request::new(proto::Empty {});
            match client.get_hardware_info(req).await {
                Ok(resp) => {
                    let hw = resp.into_inner();
                    println!("=== Hardware ===");
                    if let Some(cpu) = hw.cpu {
                        println!("CPU: {} ({} cores, {} threads, {:.2} GHz)",
                            cpu.model, cpu.cores, cpu.threads, cpu.frequency_ghz);
                    }
                    if let Some(mem) = hw.memory {
                        println!("Memory: {} MB total, {} MB available",
                            mem.total_bytes / 1024 / 1024,
                            mem.available_bytes / 1024 / 1024);
                    }
                    println!("(GPU / audio / display: v0.4+ 實作)");
                }
                Err(e) => { error!("get_hardware_info 失敗: {}", e); std::process::exit(1); }
            }
        }
        Command::Health => {
            let req = tonic::Request::new(proto::Empty {});
            match client.health(req).await {
                Ok(resp) => {
                    let h = resp.into_inner();
                    println!("healthy={}, version={}, uptime={}s",
                        h.healthy, h.version, h.uptime_seconds);
                    if !h.healthy { std::process::exit(1); }
                }
                Err(e) => { error!("health 失敗: {}", e); std::process::exit(1); }
            }
        }
    }

    Ok(())
}
