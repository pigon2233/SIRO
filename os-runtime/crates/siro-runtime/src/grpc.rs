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

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use tokio_stream::wrappers::BroadcastStream;
use tonic::{Request, Response, Status};
use tracing::info;

use crate::event_bus::{Buses, LogEntry, RuntimeEvent};
use crate::supervisor::Supervisor;

/// 把 tracing level 字串轉成 number（給 min_level filter 用）
/// debug=0 / info=1 / warn=2 / error=3
/// 解析失敗的 level 當 info
fn level_to_number(level: &str) -> u8 {
    match level.to_lowercase().as_str() {
        "debug" | "trace" => 0,
        "info" => 1,
        "warn" | "warning" => 2,
        "error" => 3,
        _ => 1,  // 預設 info
    }
}

/// gRPC server 實作（v0.3.0：接到 supervisor）
pub struct SiroRuntimeServer {
    supervisor: Arc<Supervisor>,
    /// v0.3.0：event/log bus（給 stream_logs + subscribe_events 用）
    buses: Buses,
    /// v0.3.0：kiosk 模式 state（Phase 4 會接 X11/Wayland 真正切換）
    /// v0.3.0 階段：純 in-memory flag、set_kiosk_mode RPC 改這個值 + 推 event
    kiosk_enabled: Arc<AtomicBool>,
    /// siro-runtime 啟動時間（給 Health.uptime 用）
    started_at: std::time::Instant,
}

impl SiroRuntimeServer {
    pub fn new(supervisor: Arc<Supervisor>, buses: Buses) -> Self {
        Self {
            supervisor,
            buses,
            kiosk_enabled: Arc::new(AtomicBool::new(false)),
            started_at: std::time::Instant::now(),
        }
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
        request: Request<generated::KioskRequest>,
    ) -> Result<Response<generated::Ack>, Status> {
        let req = request.into_inner();
        let was_enabled = self.kiosk_enabled.swap(req.enable, Ordering::SeqCst);
        let now_enabled = req.enable;

        info!(
            "[kiosk] 切換 {} → {}（escape_password 設定: {}）",
            if was_enabled { "ON" } else { "OFF" },
            if now_enabled { "ON" } else { "OFF" },
            !req.escape_password.is_empty()
        );

        // 推 log + event 到 bus
        self.buses.logs.publish(LogEntry::now(
            "siro-runtime",
            "info",
            format!(
                "kiosk mode {} → {}",
                if was_enabled { "ON" } else { "OFF" },
                if now_enabled { "ON" } else { "OFF" }
            ),
        ));
        self.buses.events.publish(RuntimeEvent::KioskModeChanged { enabled: now_enabled });

        // v0.3.0 階段：純 in-memory flag、不真的切 X11/Wayland
        // Phase 4 會接 openbox / Cage、Phase 5 會加實體 escape 按鈕
        Ok(Response::new(generated::Ack {
            ok: true,
            message: format!(
                "kiosk mode 已{}（v0.3.0 純 in-memory、Phase 4 整合 X11/Wayland）",
                if now_enabled { "開啟" } else { "關閉" }
            ),
        }))
    }

    async fn health(
        &self,
        _request: Request<generated::Empty>,
    ) -> Result<Response<generated::HealthStatus>, Status> {
        // Health 回版本 + 實際 uptime（siro-runtime 啟動到現在過了幾秒）
        let uptime_seconds = self.started_at.elapsed().as_secs() as i64;
        Ok(Response::new(generated::HealthStatus {
            healthy: true,
            version: env!("CARGO_PKG_VERSION").to_string(),
            uptime_seconds,
            issues: vec![],
        }))
    }

    async fn stream_logs(
        &self,
        request: Request<generated::LogFilter>,
    ) -> Result<Response<StreamLogsStreamType>, Status> {
        let filter = request.into_inner();
        info!(
            "[stream_logs] 訂閱開始（service={:?} min_level={:?} pattern={:?}）",
            filter.service, filter.min_level, filter.pattern
        );

        // 訂閱 log bus、轉成 gRPC stream
        let receiver = self.buses.logs.subscribe();
        let stream = log_receiver_to_stream(receiver, filter);

        Ok(Response::new(stream))
    }

    type StreamLogsStream = StreamLogsStreamType;

    async fn subscribe_events(
        &self,
        request: Request<generated::EventFilter>,
    ) -> Result<Response<SubscribeEventsStreamType>, Status> {
        let filter = request.into_inner();
        info!(
            "[subscribe_events] 訂閱開始（event_types={:?}）",
            filter.event_types
        );

        let receiver = self.buses.events.subscribe();
        let stream = event_receiver_to_stream(receiver, filter);

        Ok(Response::new(stream))
    }

    type SubscribeEventsStream = SubscribeEventsStreamType;
}

// ============================================================
// Stream type aliases + helper functions（給 stream_logs / subscribe_events 用）
// 放在 impl 外面當 free function 避免 Self::TypeName 找不到的問題
// ============================================================

use tokio_stream::StreamExt;

type StreamLogsStreamType = std::pin::Pin<
    Box<dyn tokio_stream::Stream<Item = Result<generated::LogEntry, Status>> + Send + 'static>,
>;

type SubscribeEventsStreamType = std::pin::Pin<
    Box<dyn tokio_stream::Stream<Item = Result<generated::SystemEvent, Status>> + Send + 'static>,
>;

/// 把 LogBus 的 broadcast::Receiver 轉成 gRPC Stream<LogEntry>
/// 加上 filter 邏輯（service / min_level / pattern）
fn log_receiver_to_stream(
    receiver: tokio::sync::broadcast::Receiver<LogEntry>,
    filter: generated::LogFilter,
) -> StreamLogsStreamType {
    // 把 broadcast::Receiver 轉成 Stream<LogEntry>
    let inner = BroadcastStream::new(receiver).filter_map(|result| {
        match result {
            Ok(entry) => Some(entry),
            Err(e) => {
                tracing::debug!("[stream_logs] receiver lagged: {}", e);
                None
            }
        }
    });

    // 套 filter
    let service_filter = filter.service;
    let min_level = filter.min_level;
    let pattern = filter.pattern;

    let filtered = inner.filter_map(move |entry| {
        if !service_filter.is_empty() && entry.service != service_filter {
            return None;
        }
        if !min_level.is_empty() {
            let entry_level = level_to_number(&entry.level);
            let min = level_to_number(&min_level);
            if entry_level < min {
                return None;
            }
        }
        if !pattern.is_empty() && !entry.message.contains(&pattern) {
            return None;
        }
        Some(entry)
    });

    let proto_stream = filtered.map(|entry| {
        Ok(generated::LogEntry {
            service: entry.service,
            level: entry.level,
            message: entry.message,
            timestamp_ms: entry.timestamp_ms,
        })
    });

    Box::pin(proto_stream)
}

/// 把 EventBus 的 broadcast::Receiver 轉成 gRPC Stream<SystemEvent>
fn event_receiver_to_stream(
    receiver: tokio::sync::broadcast::Receiver<generated::SystemEvent>,
    filter: generated::EventFilter,
) -> SubscribeEventsStreamType {
    let inner = BroadcastStream::new(receiver).filter_map(|result| match result {
        Ok(event) => Some(event),
        Err(e) => {
            tracing::debug!("[subscribe_events] receiver lagged: {}", e);
            None
        }
    });

    let wanted_types: Vec<String> = filter.event_types;
    let filtered = inner.filter(move |event| {
        if wanted_types.is_empty() {
            return true;
        }
        wanted_types.contains(&event.event_type)
    });

    let proto_stream = filtered.map(Ok);
    Box::pin(proto_stream)
}
