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
// v1.5.3 Computer Control
use crate::commands;
use crate::fs_ops;
use crate::sandbox;

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
        // v0.4+：用 hardware::detect_all() 統一偵測（CPU/memory/GPU/audio/display/cameras）
        // 失敗時回空、不 panic（production 24/7 跑）
        let hw = crate::hardware::detect_all();
        Ok(Response::new(hw.to_proto()))
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

    // ============================================================
    // v1.5.3 Computer Control — 5 個系統控制 RPC
    //
    // 給 bridge（透過 gRPC）呼叫、執行 OS 級操作
    // 所有操作都先過 sandbox.rs 路徑檢查
    // ============================================================

    async fn execute_command(
        &self,
        request: Request<generated::CommandRequest>,
    ) -> Result<Response<generated::CommandResponse>, Status> {
        let req = request.into_inner();
        let sandbox_root = sandbox::get_sandbox_root()
            .map_err(|e| Status::internal(format!("sandbox root 無效: {}", e)))?;

        // cwd 解析：如果是 "." 或 sandbox root 本身、直接用；其他要 validate 在 sandbox 內
        let cwd = if req.cwd.is_empty() || req.cwd == "." {
            sandbox_root.clone()
        } else {
            // 接受 absolute path（sandbox 內）或相對路徑
            let p = std::path::PathBuf::from(&req.cwd);
            if p.is_absolute() {
                // absolute → 檢查在 sandbox 內
                if !p.starts_with(&sandbox_root) {
                    return Err(Status::invalid_argument(format!(
                        "cwd 不在 sandbox 內：{}",
                        req.cwd
                    )));
                }
                p
            } else {
                sandbox::resolve_path_lenient(&req.cwd, &sandbox_root)
                    .map_err(|e| Status::invalid_argument(format!("cwd 解析失敗: {}", e)))?
            }
        };

        info!(
            "[execute_command] user={:?} trust={} cwd={} cmd={}",
            req.user_id, req.trust_mode, cwd.display(), req.cmd
        );

        // 推 log 給 audit
        self.buses.logs.publish(LogEntry::now(
            "siro-runtime",
            "info",
            format!(
                "[execute_command] user={} cmd={}",
                req.user_id, req.cmd
            ),
        ));

        let result = commands::execute_command(&req.cmd, &cwd, Some(req.timeout_sec.max(0) as u32))
            .await;

        match result {
            Ok(r) => Ok(Response::new(generated::CommandResponse {
                exit_code: r.exit_code,
                stdout: r.stdout,
                stderr: r.stderr,
                stdout_truncated: r.stdout_truncated,
                stderr_truncated: r.stderr_truncated,
                duration_ms: r.duration_ms,
                original_size_stdout: r.original_size_stdout as i32,
                original_size_stderr: r.original_size_stderr as i32,
                category: "auto".to_string(),  // v1.5.3 簡化：trust_mode 不擋（blocklist 在 bridge 層做）
                block_reason: String::new(),
            })),
            Err(e) => Err(Status::internal(format!("execute failed: {}", e))),
        }
    }

    async fn read_file(
        &self,
        request: Request<generated::PathRequest>,
    ) -> Result<Response<generated::FileContent>, Status> {
        let req = request.into_inner();
        let sandbox_root = sandbox::get_sandbox_root()
            .map_err(|e| Status::internal(format!("sandbox root 無效: {}", e)))?;

        let max_lines = if req.max_lines > 0 { Some(req.max_lines as usize) } else { None };

        info!(
            "[read_file] user={:?} trust={} path={} max_lines={:?}",
            req.user_id, req.trust_mode, req.path, max_lines
        );

        self.buses.logs.publish(LogEntry::now(
            "siro-runtime",
            "info",
            format!("[read_file] user={} path={}", req.user_id, req.path),
        ));

        match fs_ops::read_file(&req.path, &sandbox_root, max_lines) {
            Ok(r) => Ok(Response::new(generated::FileContent {
                path: r.path.to_string_lossy().to_string(),
                content: r.content,
                size_bytes: r.size_bytes as i64,
                truncated: r.truncated,
                line_count: r.line_count as i32,
            })),
            Err(e) => match e {
                fs_ops::FsError::NotFound(p) => Err(Status::not_found(p)),
                fs_ops::FsError::Sandbox(s) => Err(Status::invalid_argument(format!("{}", s))),
                _ => Err(Status::internal(format!("read_file failed: {}", e))),
            },
        }
    }

    async fn write_file(
        &self,
        request: Request<generated::WriteFileRequest>,
    ) -> Result<Response<generated::WriteFileResponse>, Status> {
        let req = request.into_inner();
        let sandbox_root = sandbox::get_sandbox_root()
            .map_err(|e| Status::internal(format!("sandbox root 無效: {}", e)))?;

        info!(
            "[write_file] user={:?} trust={} path={} bytes={}",
            req.user_id, req.trust_mode, req.path, req.content.len()
        );

        self.buses.logs.publish(LogEntry::now(
            "siro-runtime",
            "info",
            format!(
                "[write_file] user={} path={} bytes={}",
                req.user_id, req.path, req.content.len()
            ),
        ));

        match fs_ops::write_file(&req.path, &req.content, &sandbox_root) {
            Ok(r) => Ok(Response::new(generated::WriteFileResponse {
                ok: true,
                bytes_written: r.bytes_written as i64,
                error: String::new(),
            })),
            Err(e) => match e {
                fs_ops::FsError::Sandbox(s) => Err(Status::invalid_argument(format!("{}", s))),
                _ => Ok(Response::new(generated::WriteFileResponse {
                    ok: false,
                    bytes_written: 0,
                    error: format!("{}", e),
                })),
            },
        }
    }

    async fn list_directory(
        &self,
        request: Request<generated::PathRequest>,
    ) -> Result<Response<generated::DirectoryListing>, Status> {
        let req = request.into_inner();
        let sandbox_root = sandbox::get_sandbox_root()
            .map_err(|e| Status::internal(format!("sandbox root 無效: {}", e)))?;

        info!(
            "[list_directory] user={:?} path={} recursive={}",
            req.user_id, req.path, req.recursive
        );

        self.buses.logs.publish(LogEntry::now(
            "siro-runtime",
            "info",
            format!("[list_directory] user={} path={}", req.user_id, req.path),
        ));

        match fs_ops::list_directory(&req.path, &sandbox_root, req.recursive) {
            Ok(r) => Ok(Response::new(generated::DirectoryListing {
                path: r.path.to_string_lossy().to_string(),
                entries: r.entries,
                count: r.count as i32,
                truncated: r.truncated,
            })),
            Err(e) => match e {
                fs_ops::FsError::NotFound(p) => Err(Status::not_found(p)),
                fs_ops::FsError::Sandbox(s) => Err(Status::invalid_argument(format!("{}", s))),
                _ => Err(Status::internal(format!("list_directory failed: {}", e))),
            },
        }
    }

    async fn stat_path(
        &self,
        request: Request<generated::PathRequest>,
    ) -> Result<Response<generated::PathStat>, Status> {
        let req = request.into_inner();
        let sandbox_root = sandbox::get_sandbox_root()
            .map_err(|e| Status::internal(format!("sandbox root 無效: {}", e)))?;

        info!(
            "[stat_path] user={:?} path={}",
            req.user_id, req.path
        );

        match fs_ops::stat_path(&req.path, &sandbox_root) {
            Ok(r) => Ok(Response::new(generated::PathStat {
                path: r.path.to_string_lossy().to_string(),
                exists: r.exists,
                is_file: r.is_file,
                is_dir: r.is_dir,
                size_bytes: r.size_bytes as i64,
                modified_ms: r.modified_ms,
            })),
            Err(e) => match e {
                fs_ops::FsError::Sandbox(s) => Err(Status::invalid_argument(format!("{}", s))),
                _ => Err(Status::internal(format!("stat_path failed: {}", e))),
            },
        }
    }
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
