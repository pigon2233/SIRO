// src/grpc.rs - siro-runtime gRPC module
//
// 從 build.rs 生成的 proto stubs 重新 export
// 加上 tonic 伺服器 trait 實作（Phase 3 開始時擴充）

// `mod generated { ... }` 把 build.rs 產生的程式碼包進來
// OUT_DIR 是 build script 設定的環境變數
pub mod generated {
    tonic::include_proto!("siro.runtime.v1");
}

// 重新 export 常用 types（避免 caller 寫兩層 grpc::generated::）
// 注意：build.rs 的 tonic::include_proto! 已經把 generated 模組 expose 出來
// 這裡不用 pub use（trait impl 用全路徑 generated::* 就好）

use tonic::{Request, Response, Status};

/// Phase 3 預留：gRPC server 實作
/// 現在只 stub GetStatus、回個 hello world
/// 之後會分模組（service_manager / hardware / kiosk / events）
pub struct SiroRuntimeServer {
    /// 啟動時間（unix seconds）— 健康檢查用
    pub started_at: i64,
}

impl SiroRuntimeServer {
    pub fn new() -> Self {
        Self {
            started_at: chrono::Utc::now().timestamp(),
        }
    }
}

impl Default for SiroRuntimeServer {
    fn default() -> Self {
        Self::new()
    }
}

#[tonic::async_trait]
impl generated::siro_runtime_server::SiroRuntime for SiroRuntimeServer {
    async fn get_status(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::SystemStatus>, Status> {
        // Phase 3 開始時、這裡要查各 service 狀態、組裝 SystemStatus
        // 現階段先回空 status
        let status = generated::SystemStatus {
            services: Default::default(),  // empty map、待 Phase 3 填
            metrics: None,
        };
        Ok(Response::new(status))
    }

    async fn get_hardware_info(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::HardwareInfo>, Status> {
        // Phase 3 用 sysinfo crate 抓 CPU/Memory/GPU
        // 現階段先回空
        Ok(Response::new(generated::HardwareInfo {
            cpu: None,
            memory: None,
            gpu: None,
            audio: vec![],
            display: None,
            cameras: vec![],
        }))
    }

    async fn restart_service(
        &self,
        _request: Request<generated::ServiceName>,
    ) -> Result<Response<generated::Ack>, Status> {
        Err(Status::unimplemented(
            "restart_service 還沒實作、Phase 3 會做"
        ))
    }

    async fn control_service(
        &self,
        _request: Request<generated::ServiceControl>,
    ) -> Result<Response<generated::Ack>, Status> {
        Err(Status::unimplemented(
            "control_service 還沒實作、Phase 3 會做"
        ))
    }

    async fn set_kiosk_mode(
        &self,
        _request: Request<generated::KioskRequest>,
    ) -> Result<Response<generated::Ack>, Status> {
        Err(Status::unimplemented(
            "set_kiosk_mode 還沒實作、Phase 3 會做"
        ))
    }

    async fn health(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::HealthStatus>, Status> {
        let now = chrono::Utc::now().timestamp();
        Ok(Response::new(generated::HealthStatus {
            healthy: true,
            version: env!("CARGO_PKG_VERSION").to_string(),
            uptime_seconds: now - self.started_at,
            issues: vec![],
        }))
    }

    async fn stream_logs(
        &self,
        _request: Request<generated::LogFilter>,
    ) -> Result<Response<Self::StreamLogsStream>, Status> {
        // Phase 3 用 tokio broadcast channel 串接 tracing subscriber
        Err(Status::unimplemented("stream_logs 還沒實作"))
    }

    type StreamLogsStream = tonic::codec::Streaming<generated::LogEntry>;

    async fn subscribe_events(
        &self,
        _request: Request<generated::EventFilter>,
    ) -> Result<Response<Self::SubscribeEventsStream>, Status> {
        Err(Status::unimplemented("subscribe_events 還沒實作"))
    }

    type SubscribeEventsStream = tonic::codec::Streaming<generated::SystemEvent>;
}
