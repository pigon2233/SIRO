// src/grpc.rs - siro-runtime gRPC module
//
// v0.3.0: 從 stub 升級成實際調用 supervisor
// RPC 接到 service 真的做事（之前是回 unimplemented）

// `mod generated { ... }` 把 build.rs 產生的程式碼包進來
pub mod generated {
    tonic::include_proto!("siro.runtime.v1");
}

// 注意：這裡不 re-export generated::* — siro-ctl 走自己的 include_proto!，
// 這個 binary 不對外提供 types

use std::sync::Arc;

use tonic::{Request, Response, Status};

use crate::supervisor::Supervisor;

/// gRPC server 實作（v0.3.0：接到 supervisor）
pub struct SiroRuntimeServer {
    supervisor: Arc<Supervisor>,
}

impl SiroRuntimeServer {
    pub fn new(supervisor: Arc<Supervisor>) -> Self {
        Self { supervisor }
    }
}

#[tonic::async_trait]
impl generated::siro_runtime_server::SiroRuntime for SiroRuntimeServer {
    async fn get_status(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::SystemStatus>, Status> {
        // v0.3.0：直接從 supervisor 拿所有 service snapshot
        let snapshots = self.supervisor.snapshot().await;
        let mut services_map = std::collections::HashMap::new();
        for snap in snapshots {
            services_map.insert(snap.name.clone(), snap.to_proto_state());
        }
        Ok(Response::new(generated::SystemStatus {
            services: services_map,
            metrics: None,  // v0.4+ 加 CPU/Mem metrics
        }))
    }

    async fn get_hardware_info(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::HardwareInfo>, Status> {
        // v0.3.0 簡化：CPU/Mem 資訊用 sysinfo
        // GPU 跟 audio device 留 v0.4+ 實作
        use sysinfo::System;
        let sys = System::new_all();
        let cpu = generated::CpuInfo {
            model: sys
                .cpus()
                .first()
                .map(|c| c.brand().to_string())
                .unwrap_or_else(|| "unknown".to_string()),
            cores: sys.physical_core_count().unwrap_or(0) as i32,
            threads: sys.cpus().len() as i32,
            frequency_ghz: sys.cpus().first().map(|c| c.frequency() as f32 / 1000.0).unwrap_or(0.0),
        };
        let memory = generated::MemoryInfo {
            // sysinfo 已經回 bytes、不用再乘 1024
            total_bytes: sys.total_memory() as i64,
            available_bytes: sys.available_memory() as i64,
        };
        Ok(Response::new(generated::HardwareInfo {
            cpu: Some(cpu),
            memory: Some(memory),
            gpu: None,
            audio: vec![],
            display: None,
            cameras: vec![],
        }))
    }

    async fn restart_service(
        &self,
        request: Request<generated::ServiceName>,
    ) -> Result<Response<generated::Ack>, Status> {
        let name = request.into_inner().name;
        if name.is_empty() {
            return Err(Status::invalid_argument("service name 不可空白"));
        }
        match self.supervisor.restart(&name).await {
            Ok(()) => Ok(Response::new(generated::Ack {
                ok: true,
                message: format!("{} 重啟成功", name),
            })),
            Err(e) => Ok(Response::new(generated::Ack {
                ok: false,
                message: format!("{} 重啟失敗: {}", name, e),
            })),
        }
    }

    async fn control_service(
        &self,
        request: Request<generated::ServiceControl>,
    ) -> Result<Response<generated::Ack>, Status> {
        use crate::proto::service_control::ServiceAction;
        let ctrl = request.into_inner();
        let name = ctrl.name;
        let result = match ServiceAction::try_from(ctrl.action) {
            Ok(ServiceAction::Start) => self.supervisor.start(&name).await,
            Ok(ServiceAction::Stop) => self.supervisor.stop(&name).await,
            Ok(ServiceAction::Restart) => self.supervisor.restart(&name).await,
            Ok(ServiceAction::Unknown) | Err(_) => {
                return Ok(Response::new(generated::Ack {
                    ok: false,
                    message: format!("{} 未知 action", name),
                }));
            }
        };
        match result {
            Ok(()) => Ok(Response::new(generated::Ack {
                ok: true,
                message: format!("{} 動作成功", name),
            })),
            Err(e) => Ok(Response::new(generated::Ack {
                ok: false,
                message: format!("{} 失敗: {}", name, e),
            })),
        }
    }

    async fn set_kiosk_mode(
        &self,
        _request: Request<generated::KioskRequest>,
    ) -> Result<Response<generated::Ack>, Status> {
        // v0.3.0 預留：Phase 4+ 實作
        Err(Status::unimplemented(
            "set_kiosk_mode 還沒實作、Phase 4 會做"
        ))
    }

    async fn health(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::HealthStatus>, Status> {
        // Health 就是 v0.2.0 的版本資訊
        Ok(Response::new(generated::HealthStatus {
            healthy: true,
            version: env!("CARGO_PKG_VERSION").to_string(),
            uptime_seconds: 0,  // v0.4+ 改成 process 實際 uptime
            issues: vec![],
        }))
    }

    async fn stream_logs(
        &self,
        _request: Request<generated::LogFilter>,
    ) -> Result<Response<Self::StreamLogsStream>, Status> {
        // Phase 3 預留：Phase 4 整合 tracing subscriber 串流
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
