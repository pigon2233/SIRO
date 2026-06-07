// src/event_bus.rs - siro-runtime event + log bus
//
// v0.3.0 給 stream_logs + subscribe_events 兩個 RPC 用的 broadcast bus
//
// 兩個 bus 共用 broadcast channel 架構：
// - LogBus: supervisor 推 service 狀態變化的 log entry（給 stream_logs 收）
// - EventBus: supervisor 推 service 狀態變化的事件（給 subscribe_events 收）
//
// 為什麼分兩個：
// - LogEntry 格式固定、給 monitoring / log aggregator 用
// - SystemEvent 比較泛用、未來要加新事件型別不用動 LogEntry
//
// 注意：broadcast channel 容量有限、慢的 subscriber 會 lag 掉。
// 1000 條對 supervisor log 應該夠（每秒約 1-2 條、最多 lag 8 分鐘）
// 真不夠再調高。

use std::sync::Arc;

use chrono::Utc;
use tokio::sync::broadcast;

/// 一條 log 給 stream_logs 推
#[derive(Debug, Clone)]
pub struct LogEntry {
    pub service: String,
    pub level: String,  // "debug" / "info" / "warn" / "error"
    pub message: String,
    pub timestamp_ms: i64,
}

impl LogEntry {
    pub fn now(service: impl Into<String>, level: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            service: service.into(),
            level: level.into(),
            message: message.into(),
            timestamp_ms: Utc::now().timestamp_millis(),
        }
    }
}

/// 內部用的強型別事件（會被轉成 SystemEvent proto 推出去）
#[derive(Debug, Clone)]
pub enum RuntimeEvent {
    ServiceStarted { name: String, pid: u32 },
    ServiceStopped { name: String },
    ServiceFailed { name: String, error: String },
    ServiceRestarted { name: String, pid: u32, count: u32 },
    KioskModeChanged { enabled: bool },
}

impl RuntimeEvent {
    /// 轉成 proto 的 SystemEvent
    /// 注意：data 是 map<string, string> 所以全部值都轉成字串
    pub fn to_system_event(&self) -> generated::SystemEvent {
        // 這裡用 generated crate — 但 generated 是 grpc.rs 的 pub mod
        // 為了不循環依賴、用 proto 模組（main.rs 有 pub use grpc::generated as proto）
        let (event_type, data) = match self {
            RuntimeEvent::ServiceStarted { name, pid } => (
                "service.started".to_string(),
                vec![
                    ("name".to_string(), name.clone()),
                    ("pid".to_string(), pid.to_string()),
                ],
            ),
            RuntimeEvent::ServiceStopped { name } => (
                "service.stopped".to_string(),
                vec![("name".to_string(), name.clone())],
            ),
            RuntimeEvent::ServiceFailed { name, error } => (
                "service.failed".to_string(),
                vec![
                    ("name".to_string(), name.clone()),
                    ("error".to_string(), error.clone()),
                ],
            ),
            RuntimeEvent::ServiceRestarted { name, pid, count } => (
                "service.restarted".to_string(),
                vec![
                    ("name".to_string(), name.clone()),
                    ("pid".to_string(), pid.to_string()),
                    ("count".to_string(), count.to_string()),
                ],
            ),
            RuntimeEvent::KioskModeChanged { enabled } => (
                if *enabled { "kiosk.enabled" } else { "kiosk.disabled" }.to_string(),
                vec![("enabled".to_string(), enabled.to_string())],
            ),
        };
        generated::SystemEvent {
            event_type,
            timestamp_ms: Utc::now().timestamp_millis(),
            data: data.into_iter().collect(),
        }
    }
}

// 因為 event_bus.rs 不直接 access grpc::generated，這裡重新宣告型別
// 用 proto 名稱對應，main.rs 內有 `pub use grpc::generated as proto`
// 為了不循環 import，用模組化名：
// 實際上 event_bus 也要拿 generated::SystemEvent — 我們讓 grpc.rs 把 generated re-export 出來

// 從 grpc.rs 的 pub mod generated 拿
use crate::grpc::generated;

const LOG_CHANNEL_CAPACITY: usize = 1000;
const EVENT_CHANNEL_CAPACITY: usize = 1000;

/// Log 推播 bus（給 stream_logs）
#[derive(Clone)]
pub struct LogBus {
    sender: broadcast::Sender<LogEntry>,
}

impl LogBus {
    pub fn new() -> Self {
        let (tx, _) = broadcast::channel(LOG_CHANNEL_CAPACITY);
        Self { sender: tx }
    }

    pub fn publish(&self, entry: LogEntry) {
        // 沒人收就 drop（不會 block supervisor）
        let _ = self.sender.send(entry);
    }

    pub fn subscribe(&self) -> broadcast::Receiver<LogEntry> {
        self.sender.subscribe()
    }
}

impl Default for LogBus {
    fn default() -> Self {
        Self::new()
    }
}

/// Event 推播 bus（給 subscribe_events）
#[derive(Clone)]
pub struct EventBus {
    sender: broadcast::Sender<generated::SystemEvent>,
}

impl EventBus {
    pub fn new() -> Self {
        let (tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        Self { sender: tx }
    }

    pub fn publish(&self, event: RuntimeEvent) {
        let _ = self.sender.send(event.to_system_event());
    }

    pub fn subscribe(&self) -> broadcast::Receiver<generated::SystemEvent> {
        self.sender.subscribe()
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}

/// 兩個 bus 包一起給 main.rs 用
#[derive(Clone)]
pub struct Buses {
    pub logs: Arc<LogBus>,
    pub events: Arc<EventBus>,
}

impl Buses {
    pub fn new() -> Self {
        Self {
            logs: Arc::new(LogBus::new()),
            events: Arc::new(EventBus::new()),
        }
    }
}

impl Default for Buses {
    fn default() -> Self {
        Self::new()
    }
}
