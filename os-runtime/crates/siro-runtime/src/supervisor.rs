// src/supervisor.rs - Process supervisor
//
// v0.3.0 MVP：
// - 監控 bridge / hermes / unity 三個 process
// - 死了自動重啟（依 ServiceDef.auto_restart + restart_delay_sec）
// - 暴露 start / stop / restart / get_status API
// - 背景 monitor task 定期 health check
//
// 對應 [ADR 0002](../docs/ADR/0002-subsystem-failure-對話對應.md) S1 (bridge) + S2 (hermes)

use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sysinfo::System;
use tokio::process::{Child, Command};
use tokio::sync::{Mutex, RwLock};
use tokio::time::{interval, sleep};
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::event_bus::{Buses, LogEntry, RuntimeEvent};
use crate::services::ServiceDef;

/// Service 當前狀態（runtime mutable state）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ServiceStatus {
    /// 沒跑（初始、或被 stop）
    Stopped,
    /// 啟動中（spawn 完、還沒進 health check）
    Starting,
    /// 跑著
    Running {
        pid: u32,
        /// 啟動時間
        started_at: DateTime<Utc>,
    },
    /// 死掉 + 還在等 restart_delay
    WaitingRestart {
        /// 上次死掉的錯誤訊息
        last_error: String,
        /// 下次重啟時間
        retry_at: DateTime<Utc>,
    },
    /// 死太多次、超過 max_restarts、放棄
    GaveUp {
        last_error: String,
        total_restarts: u32,
    },
}

impl ServiceStatus {
    /// 對應 gRPC proto 的 ServiceStatus enum
    /// 對應關係：Stopped=2 / Running=1 / Starting=4 / WaitingRestart=1+自定義 / GaveUp=3
    pub fn to_proto(&self) -> i32 {
        match self {
            ServiceStatus::Stopped => 2,                              // STOPPED
            ServiceStatus::Starting => 4,                             // STARTING
            ServiceStatus::Running { .. } => 1,                      // RUNNING
            ServiceStatus::WaitingRestart { .. } => 2,               // STOPPED（表面）
            ServiceStatus::GaveUp { .. } => 3,                       // FAILED
        }
    }

    // display_name 之前在這、沒人呼叫且註解誤指 ServiceAction。
    // siro-ctl 已在 main.rs:95-101 inline 把 ServiceStatus enum 轉字串，
    // 需要時再加回來。
}

/// 每個 service 的 runtime 狀態（被 supervisor 內部 mutate）
pub struct ServiceInfo {
    pub def: ServiceDef,
    pub status: ServiceStatus,
    pub restart_count: u32,
}

/// Supervisor 本身
pub struct Supervisor {
    /// 服務名 → ServiceInfo
    services: Arc<RwLock<HashMap<String, ServiceInfo>>>,
    /// 服務名 → child process handle（用來 kill）
    children: Arc<Mutex<HashMap<String, Child>>>,
    /// 背景 monitor task 的 cancel token
    cancel: CancellationToken,
    /// v0.3.0：event/log bus（給 stream_logs + subscribe_events 推播用）
    buses: Buses,
}

impl Supervisor {
    pub fn new(service_defs: Vec<ServiceDef>, buses: Buses) -> Self {
        let services = service_defs
            .into_iter()
            .map(|def| {
                let name = def.name.clone();
                (
                    name,
                    ServiceInfo {
                        def,
                        status: ServiceStatus::Stopped,
                        restart_count: 0,
                    },
                )
            })
            .collect();
        Self {
            services: Arc::new(RwLock::new(services)),
            children: Arc::new(Mutex::new(HashMap::new())),
            cancel: CancellationToken::new(),
            buses,
        }
    }

    /// 啟動 background monitor task
    /// 每個 service 各自有一個獨立 task、定期 health check + 必要時 restart
    /// 全取消：呼叫 `shutdown()` 把 cancel token fire 掉
    pub fn spawn_monitor(&self) {
        let services = self.services.clone();
        let children = self.children.clone();
        let cancel = self.cancel.clone();
        // v0.3.0：clone buses 進 closure（tick_once 用 buses 推 log/event）
        let buses = self.buses.clone();

        // 用 tokio::spawn 跑一個 task 巡所有 service
        tokio::spawn(async move {
            info!("[Supervisor] monitor loop 啟動");

            // 每個 service 一個獨立 health check interval
            // 簡化：每秒醒一次、看哪個 service 該 health check
            let mut ticker = interval(Duration::from_secs(1));
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            loop {
                tokio::select! {
                    _ = cancel.cancelled() => {
                        info!("[Supervisor] monitor loop 收到 cancel、退出");
                        break;
                    }
                    _ = ticker.tick() => {
                        Self::tick_once(&services, &children, &buses).await;
                    }
                }
            }
        });
    }

    /// 監控 tick：對每個 service 檢查該不該 health check / restart
    /// v0.3.0：static fn + 收 buses 當參數（spawn_monitor 才能 clone 進 closure）
    async fn tick_once(
        services: &Arc<RwLock<HashMap<String, ServiceInfo>>>,
        children: &Arc<Mutex<HashMap<String, Child>>>,
        buses: &Buses,
    ) {
        // 用 sysinfo 一次性查所有 PID（避免每 service 一次系統 call）
        let mut sys = System::new_all();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::All, true);

        let mut to_restart: Vec<(String, String)> = vec![];  // (name, error)

        {
            let services_read = services.read().await;
            for (name, info) in services_read.iter() {
                match &info.status {
                    ServiceStatus::Running { pid, started_at: _ } => {
                        // 檢查 PID 是否還活著
                        let elapsed = Utc::now() - chrono::Duration::seconds(info.def.health_check_interval_sec as i64);
                        if !sys.process(sysinfo::Pid::from_u32(*pid)).is_some() {
                            // 死掉了
                            warn!(
                                "[Supervisor] {} (pid={}) 死了、準備重啟",
                                name, pid
                            );
                            to_restart.push((
                                name.clone(),
                                format!("process {} died", pid),
                            ));
                        } else {
                            // 還活著、log
                            // （v0.3.0 不做 memory/CPU 監控、v0.4+ 加）
                            let _ = elapsed;  // 之後用
                        }
                    }
                    ServiceStatus::WaitingRestart { retry_at, last_error } => {
                        if Utc::now() >= *retry_at {
                            info!(
                                "[Supervisor] {} retry_at 到、重新啟動",
                                name
                            );
                            to_restart.push((name.clone(), last_error.clone()));
                        }
                    }
                    _ => {}  // Stopped / Starting / GaveUp：本 tick 不動
                }
            }
        }  // 釋放 read lock

        // 執行重啟（在 write lock 外做實際 spawn、避免 deadlock）
        for (name, error) in to_restart {
            if let Err(e) = Self::do_restart(services, children, buses, &name, &error).await {
                error!("[Supervisor] {} 重啟失敗: {}", name, e);
            }
        }
    }

    /// 實際 spawn 一個 process
    async fn spawn_process(def: &ServiceDef) -> Result<Child, String> {
        let mut cmd = Command::new(&def.command);
        cmd.args(&def.args);
        if let Some(wd) = &def.working_dir {
            cmd.current_dir(wd);
        }
        for (k, v) in &def.env {
            cmd.env(k, v);
        }
        // 標準 IO 處理（v0.3.0 簡化、v0.4 接 tracing log）
        cmd.stdout(Stdio::null());
        cmd.stderr(Stdio::null());
        cmd.stdin(Stdio::null());

        cmd.spawn().map_err(|e| format!("spawn 失敗: {}", e))
    }

    /// 真的重啟一個 service（給 monitor loop 呼叫 + 給 public start/restart 呼叫）
    /// v0.3.0：static fn + 收 buses 當參數（這樣 spawn_monitor 的 closure 才能呼叫）
    async fn do_restart(
        services: &Arc<RwLock<HashMap<String, ServiceInfo>>>,
        children: &Arc<Mutex<HashMap<String, Child>>>,
        buses: &Buses,
        name: &str,
        reason: &str,
    ) -> Result<(), String> {
        // 1. 從 children map 拿舊 child（如果還在）
        let old_child = {
            let mut children_lock = children.lock().await;
            children_lock.remove(name)
        };

        // 2. kill 舊 process（如果有）
        if let Some(mut child) = old_child {
            warn!("[Supervisor] {} kill 舊 process", name);
            let _ = child.kill().await;
            let _ = child.wait().await;
        }

        // 3. 拿 ServiceDef + 檢查 max_restarts
        let def_clone = {
            let services_read = services.read().await;
            services_read.get(name).map(|info| info.def.clone())
        };
        let def = match def_clone {
            Some(d) => d,
            None => return Err(format!("service {} 不存在", name)),
        };

        if !def.auto_restart {
            // supervisor 不管 lifecycle（service 自己負責、例如 Unity kiosk）
            // 不動 state、不留 last_error：service 維持原狀
            warn!("[Supervisor] {} 設為不自動重啟、supervisor 不管 lifecycle", name);
            return Ok(());
        }

        // 4. 檢查 max_restarts
        let restart_count = {
            let services_read = services.read().await;
            services_read.get(name).map(|i| i.restart_count).unwrap_or(0)
        };
        if def.max_restarts > 0 && restart_count >= def.max_restarts {
            error!(
                "[Supervisor] {} 重啟 {} 次、超過 max_restarts={}、放棄",
                name, restart_count, def.max_restarts
            );
            Self::mark_gave_up(services, name, reason.to_string(), restart_count).await;
            // 推 GaveUp event
            buses.logs.publish(LogEntry::now(
                name,
                "error",
                format!("{} 重啟 {} 次、放棄", name, restart_count),
            ));
            buses.events.publish(RuntimeEvent::ServiceFailed {
                name: name.to_string(),
                error: format!("gave up after {} restarts", restart_count),
            });
            return Ok(());
        }

        // 5. spawn 新 process
        let child = Self::spawn_process(&def).await?;

        // 6. 更新狀態
        let pid = child.id().unwrap_or(0);
        let new_count = restart_count + 1;
        {
            let mut services_lock = services.write().await;
            if let Some(info) = services_lock.get_mut(name) {
                info.status = ServiceStatus::Running {
                    pid,
                    started_at: Utc::now(),
                };
                info.restart_count = new_count;
            }
        }
        {
            let mut children_lock = children.lock().await;
            children_lock.insert(name.to_string(), child);
        }
        info!(
            "[Supervisor] {} 重啟成功、pid={}（第 {} 次）",
            name, pid, new_count
        );

        // v0.3.0：推 log + event 到 bus
        // 第一次啟動（restart_count=0）叫 service.started、第 N 次叫 service.restarted
        let was_restart = new_count > 1;
        buses.logs.publish(LogEntry::now(
            name,
            "info",
            format!("{} 重啟成功、pid={}（第 {} 次）", name, pid, new_count),
        ));
        if was_restart {
            buses.events.publish(RuntimeEvent::ServiceRestarted {
                name: name.to_string(),
                pid,
                count: new_count,
            });
        } else {
            buses.events.publish(RuntimeEvent::ServiceStarted {
                name: name.to_string(),
                pid,
            });
        }
        Ok(())
    }

    async fn mark_gave_up(
        services: &Arc<RwLock<HashMap<String, ServiceInfo>>>,
        name: &str,
        error: String,
        total: u32,
    ) {
        let mut services_lock = services.write().await;
        if let Some(info) = services_lock.get_mut(name) {
            info.status = ServiceStatus::GaveUp {
                last_error: error.clone(),
                total_restarts: total,
            };
        }
        // 注意：這個 static fn 拿不到 self.buses
        // 我們讓外面呼叫端自己 publish（看 do_restart 內的 call site）
    }

    // ========== Public API（給 gRPC handler 呼叫）==========

    /// 手動啟動一個 service（siro-ctl start bridge）
    pub async fn start(&self, name: &str) -> Result<(), String> {
        Self::do_restart(&self.services, &self.children, &self.buses, name, "manual start").await
    }

    /// 手動停止一個 service
    pub async fn stop(&self, name: &str) -> Result<(), String> {
        let child = {
            let mut children_lock = self.children.lock().await;
            children_lock.remove(name)
        };
        if let Some(mut child) = child {
            warn!("[Supervisor] {} 手動 stop", name);
            let _ = child.kill().await;
            let _ = child.wait().await;
        }
        let mut services_lock = self.services.write().await;
        if let Some(info) = services_lock.get_mut(name) {
            info.status = ServiceStatus::Stopped;
        }
        Ok(())
    }

    /// 手動重啟一個 service
    pub async fn restart(&self, name: &str) -> Result<(), String> {
        Self::do_restart(&self.services, &self.children, &self.buses, name, "manual restart").await
    }

    /// 拿所有 service 狀態（給 GetStatus RPC 用）
    pub async fn snapshot(&self) -> Vec<ServiceSnapshot> {
        let services_read = self.services.read().await;
        let mut sys = System::new_all();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::All, true);

        services_read
            .iter()
            .map(|(name, info)| {
                let (pid, uptime_sec, mem_bytes) = match &info.status {
                    ServiceStatus::Running { pid, started_at } => {
                        let uptime = (Utc::now() - *started_at).num_seconds().max(0) as i64;
                        let mem = sys
                            .process(sysinfo::Pid::from_u32(*pid))
                            .map(|p| p.memory() as i64)  // sysinfo 已經回 bytes
                            .unwrap_or(0);
                        (Some(*pid), uptime, mem)
                    }
                    _ => (None, 0, 0),
                };
                ServiceSnapshot {
                    name: name.clone(),
                    status: info.status.clone(),
                    restart_count: info.restart_count,
                    pid,
                    uptime_sec,
                    mem_bytes,
                }
            })
            .collect()
    }

    /// 關掉 supervisor：把所有 child kill 掉、cancel monitor task
    pub async fn shutdown(&self) {
        info!("[Supervisor] shutdown、kill 所有 child");
        let mut children_lock = self.children.lock().await;
        for (name, mut child) in children_lock.drain() {
            info!("[Supervisor] kill {}", name);
            let _ = child.kill().await;
            let _ = child.wait().await;
        }
        self.cancel.cancel();
        // 給 monitor task 一點時間收尾
        sleep(Duration::from_millis(100)).await;
    }
}

/// 對外的 service 快照（給 gRPC / CLI 用、不洩漏內部狀態）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceSnapshot {
    pub name: String,
    pub status: ServiceStatus,
    pub restart_count: u32,
    pub pid: Option<u32>,
    pub uptime_sec: i64,
    pub mem_bytes: i64,
}

impl ServiceSnapshot {
    /// 對應 gRPC proto 的 ServiceState
    pub fn to_proto_state(&self) -> crate::proto::ServiceState {
        use crate::proto;
        let status_enum = match self.status.to_proto() {
            1 => proto::service_state::ServiceStatus::Running as i32,
            2 => proto::service_state::ServiceStatus::Stopped as i32,
            3 => proto::service_state::ServiceStatus::Failed as i32,
            4 => proto::service_state::ServiceStatus::Starting as i32,
            _ => proto::service_state::ServiceStatus::Unknown as i32,
        };
        proto::ServiceState {
            name: self.name.clone(),
            status: status_enum,
            pid: self.pid.unwrap_or(0) as i32,
            uptime_seconds: self.uptime_sec,
            memory_bytes: self.mem_bytes,
            cpu_percent: 0.0,  // v0.4+ 實作
            last_error: match &self.status {
                ServiceStatus::WaitingRestart { last_error, .. } => last_error.clone(),
                ServiceStatus::GaveUp { last_error, .. } => last_error.clone(),
                _ => String::new(),
            },
        }
    }
}
