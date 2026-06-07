// tests/supervisor_basic.rs
//
// Supervisor + event_bus 的基本單元測試（v0.3.0 Phase 3）
//
// 範圍：
// - new() 建立 service map
// - snapshot() 拿所有 service 狀態
// - start() / stop() 的 service 狀態轉換
// - to_proto() 對應關係
// - event_bus 基本的 publish/subscribe
//
// 不測：
// - monitor loop（需要 spawn 真的 process、太慢）
// - gRPC RPC（屬於 integration test 範圍）

use std::time::Duration;
use siro_runtime::supervisor::{Supervisor, ServiceStatus};
use siro_runtime::services::ServiceDef;
use siro_runtime::event_bus::{Buses, LogBus, EventBus, LogEntry, RuntimeEvent};
use tokio::time::timeout;

fn make_def(name: &str) -> ServiceDef {
    ServiceDef {
        name: name.to_string(),
        command: "echo".to_string(),
        args: vec![format!("test {}", name)],
        working_dir: None,
        env: Default::default(),
        // 測試要驗 start/stop/restart 真的 spawn、所以 auto_restart=true
        // （auto_restart=false 的 path 會在 do_restart 早 return、跳過 spawn）
        auto_restart: true,
        restart_delay_sec: 1,
        health_check_interval_sec: 10,
        max_restarts: 0,
    }
}

#[tokio::test]
async fn test_supervisor_new_initializes_all_stopped() {
    let buses = Buses::new();
    let defs = vec![make_def("a"), make_def("b"), make_def("c")];
    let sup = Supervisor::new(defs, buses);

    let snaps = sup.snapshot().await;
    assert_eq!(snaps.len(), 3);
    for snap in &snaps {
        assert!(matches!(snap.status, ServiceStatus::Stopped), "{}: {:?}", snap.name, snap.status);
        assert_eq!(snap.pid, None);
    }
}

#[tokio::test]
async fn test_supervisor_stop_unstarted_service_is_noop() {
    let buses = Buses::new();
    let defs = vec![make_def("a")];
    let sup = Supervisor::new(defs, buses);

    let result = sup.stop("a").await;
    assert!(result.is_ok());

    let snaps = sup.snapshot().await;
    assert!(matches!(snaps[0].status, ServiceStatus::Stopped));
}

#[tokio::test]
async fn test_supervisor_start_spawns_and_marks_running() {
    let buses = Buses::new();
    let defs = vec![make_def("a")];
    let sup = Supervisor::new(defs, buses);

    let result = sup.start("a").await;
    assert!(result.is_ok());

    let snaps = sup.snapshot().await;
    assert!(matches!(snaps[0].status, ServiceStatus::Running { .. }));
}

#[tokio::test]
async fn test_supervisor_stop_running_service_marks_stopped() {
    let buses = Buses::new();
    let defs = vec![make_def("a")];
    let sup = Supervisor::new(defs, buses);

    sup.start("a").await.unwrap();
    let snaps = sup.snapshot().await;
    assert!(matches!(snaps[0].status, ServiceStatus::Running { .. }));

    sup.stop("a").await.unwrap();
    let snaps = sup.snapshot().await;
    assert!(matches!(snaps[0].status, ServiceStatus::Stopped),
        "after stop, expected Stopped, got {:?}", snaps[0].status);
}

#[tokio::test]
async fn test_supervisor_restart_increments_count() {
    let buses = Buses::new();
    let defs = vec![make_def("a")];
    let sup = Supervisor::new(defs, buses);

    sup.start("a").await.unwrap();
    let snaps = sup.snapshot().await;
    assert_eq!(snaps[0].restart_count, 1);

    sup.start("a").await.unwrap();
    let snaps = sup.snapshot().await;
    assert_eq!(snaps[0].restart_count, 2,
        "restart_count should increment on each start");
}

#[tokio::test]
async fn test_supervisor_unknown_service_returns_error() {
    let buses = Buses::new();
    let defs = vec![make_def("a")];
    let sup = Supervisor::new(defs, buses);

    let result = sup.start("nonexistent").await;
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("不存在"));
}

#[tokio::test]
async fn test_to_proto_state_maps_correctly() {
    let running = ServiceStatus::Running { pid: 100, started_at: chrono::Utc::now() };
    let stopped = ServiceStatus::Stopped;
    let starting = ServiceStatus::Starting;
    let waiting = ServiceStatus::WaitingRestart {
        last_error: "x".to_string(),
        retry_at: chrono::Utc::now(),
    };
    let gave_up = ServiceStatus::GaveUp {
        last_error: "y".to_string(),
        total_restarts: 5,
    };

    assert_eq!(running.to_proto(), 1);
    assert_eq!(stopped.to_proto(), 2);
    assert_eq!(starting.to_proto(), 4);
    assert_eq!(waiting.to_proto(), 2);
    assert_eq!(gave_up.to_proto(), 3);
}

#[tokio::test]
async fn test_event_bus_log_publish_subscribe() {
    let log_bus = LogBus::new();
    let mut rx = log_bus.subscribe();
    log_bus.publish(LogEntry::now("test-svc", "info", "hello world"));
    let entry = timeout(Duration::from_secs(1), rx.recv())
        .await
        .expect("timeout")
        .expect("recv error");
    assert_eq!(entry.service, "test-svc");
    assert_eq!(entry.level, "info");
    assert_eq!(entry.message, "hello world");
    assert!(entry.timestamp_ms > 0);
}

#[tokio::test]
async fn test_event_bus_event_publish_subscribe() {
    let event_bus = EventBus::new();
    let mut rx = event_bus.subscribe();
    event_bus.publish(RuntimeEvent::KioskModeChanged { enabled: true });
    let event = timeout(Duration::from_secs(1), rx.recv())
        .await
        .expect("timeout")
        .expect("recv error");
    assert_eq!(event.event_type, "kiosk.enabled");
    assert_eq!(event.data.get("enabled"), Some(&"true".to_string()));

    event_bus.publish(RuntimeEvent::KioskModeChanged { enabled: false });
    let event = timeout(Duration::from_secs(1), rx.recv())
        .await
        .expect("timeout")
        .expect("recv error");
    assert_eq!(event.event_type, "kiosk.disabled");
    assert_eq!(event.data.get("enabled"), Some(&"false".to_string()));
}

#[tokio::test]
async fn test_event_bus_service_started_to_proto() {
    let event_bus = EventBus::new();
    let mut rx = event_bus.subscribe();
    event_bus.publish(RuntimeEvent::ServiceStarted {
        name: "bridge".to_string(),
        pid: 12345,
    });
    let event = timeout(Duration::from_secs(1), rx.recv())
        .await
        .expect("timeout")
        .expect("recv error");
    assert_eq!(event.event_type, "service.started");
    assert_eq!(event.data.get("name"), Some(&"bridge".to_string()));
    assert_eq!(event.data.get("pid"), Some(&"12345".to_string()));
}
