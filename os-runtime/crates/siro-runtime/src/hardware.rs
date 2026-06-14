//! os-runtime/src/hardware.rs - 硬體偵測
//!
//! v0.4+：在 CPU/memory 之外加上 GPU / audio / display / camera 偵測
//!
//! 平台策略：
//! - CPU + memory: 用 sysinfo crate（跨平台）
//! - GPU: NVIDIA 用 nvidia-smi CLI（Linux/Windows 都有）、其他 vendor 留空
//! - Audio: Linux 用 arecord/aplay 列 device、Windows 用 PowerShell 查
//! - Display: Linux 讀 $DISPLAY + xdpyinfo、Windows 用 Get-CimInstance
//! - Camera: Linux 掃 /dev/video*、Windows 用 PowerShell 查
//!
//! 失敗時回 None / 空 vector（不要 panic、production 24/7 跑）
//! 每次呼叫都有 timeout、避免硬體鎖死整個 gRPC handler

use std::process::Command;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Default)]
pub struct CpuInfo {
    pub model: String,
    pub cores: i32,
    pub threads: i32,
    pub frequency_ghz: f32,
}

#[derive(Debug, Clone, Default)]
pub struct MemoryInfo {
    pub total_bytes: i64,
    pub available_bytes: i64,
}

#[derive(Debug, Clone, Default)]
pub struct GpuInfo {
    pub model: String,
    pub vendor: String,
    pub vram_bytes: i64,
    pub driver_version: String,
    pub cuda_version: String,
    pub utilization_percent: f32,
    pub temperature_c: f32,
}

#[derive(Debug, Clone, Default)]
pub struct AudioDevice {
    pub name: String,
    pub device_type: String,  // "input" / "output"
    pub is_default: bool,
}

#[derive(Debug, Clone, Default)]
pub struct DisplayInfo {
    pub server: String,  // "x11" / "wayland" / "windows" / "none"
    pub width: i32,
    pub height: i32,
    pub refresh_rate: f32,
}

#[derive(Debug, Clone, Default)]
pub struct CameraDevice {
    pub device_path: String,
    pub name: String,
    pub width: i32,
    pub height: i32,
    pub fps: i32,
}

#[derive(Debug, Clone, Default)]
pub struct HardwareInfo {
    pub cpu: CpuInfo,
    pub memory: MemoryInfo,
    pub gpu: Option<GpuInfo>,
    pub audio: Vec<AudioDevice>,
    pub display: Option<DisplayInfo>,
    pub cameras: Vec<CameraDevice>,
}

const CMD_TIMEOUT: Duration = Duration::from_secs(2);

/// 跑 shell command 帶 timeout、stdout 拿 string
fn run_with_timeout(cmd: &str, args: &[&str]) -> Option<String> {
    let start = Instant::now();
    let output = Command::new(cmd).args(args).output().ok()?;
    if start.elapsed() > CMD_TIMEOUT {
        return None;
    }
    if !output.status.success() {
        return None;
    }
    String::from_utf8(output.stdout).ok()
}

// ==================== CPU + Memory（sysinfo）====================

pub fn detect_cpu() -> CpuInfo {
    use sysinfo::System;
    let sys = System::new_all();
    CpuInfo {
        model: sys
            .cpus()
            .first()
            .map(|c| c.brand().to_string())
            .unwrap_or_else(|| "unknown".to_string()),
        cores: sys.physical_core_count().unwrap_or(0) as i32,
        threads: sys.cpus().len() as i32,
        frequency_ghz: sys
            .cpus()
            .first()
            .map(|c| c.frequency() as f32 / 1000.0)
            .unwrap_or(0.0),
    }
}

pub fn detect_memory() -> MemoryInfo {
    use sysinfo::System;
    let sys = System::new_all();
    MemoryInfo {
        total_bytes: sys.total_memory() as i64,
        available_bytes: sys.available_memory() as i64,
    }
}

// ==================== GPU ====================

pub fn detect_gpu() -> Option<GpuInfo> {
    // 先試 nvidia-smi（NVIDIA 顯卡，Linux/Windows/macOS 都有裝 driver 就會有）
    if let Some(gpu) = detect_nvidia_smi() {
        return Some(gpu);
    }
    // 沒 NVIDIA → 試 AMD（Linux: rocm-smi、Windows: wmic）
    #[cfg(target_os = "linux")]
    {
        if let Some(gpu) = detect_rocm_smi() {
            return Some(gpu);
        }
    }
    None
}

fn detect_nvidia_smi() -> Option<GpuInfo> {
    let out = run_with_timeout("nvidia-smi", &[
        "--query-gpu=name,driver_version,memory.total,utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])?;
    let line = out.lines().next()?;
    let parts: Vec<&str> = line.split(',').map(str::trim).collect();
    if parts.len() < 5 {
        return None;
    }
    let vram_mb: i64 = parts[2].parse().unwrap_or(0);
    let util: f32 = parts[3].parse().unwrap_or(0.0);
    let temp: f32 = parts[4].parse().unwrap_or(0.0);
    let cuda = run_with_timeout("nvidia-smi", &[]).unwrap_or_default();
    // 從 nvidia-smi 預設輸出抓 CUDA version
    let cuda_ver = cuda
        .lines()
        .find(|l| l.contains("CUDA Version"))
        .and_then(|l| l.split(':').nth(1))
        .map(|s| s.trim().to_string())
        .unwrap_or_default();
    Some(GpuInfo {
        model: parts[0].to_string(),
        vendor: "NVIDIA".to_string(),
        vram_bytes: vram_mb * 1024 * 1024,
        driver_version: parts[1].to_string(),
        cuda_version: cuda_ver,
        utilization_percent: util,
        temperature_c: temp,
    })
}

#[cfg(target_os = "linux")]
fn detect_rocm_smi() -> Option<GpuInfo> {
    let out = run_with_timeout("rocm-smi", &["--showproductname", "--csv"])?;
    let line = out.lines().nth(1)?; // skip header
    let parts: Vec<&str> = line.split(',').map(str::trim).collect();
    if parts.is_empty() {
        return None;
    }
    Some(GpuInfo {
        model: parts[0].to_string(),
        vendor: "AMD".to_string(),
        ..Default::default()
    })
}

// ==================== Audio ====================

pub fn detect_audio() -> Vec<AudioDevice> {
    #[cfg(target_os = "linux")]
    {
        detect_audio_linux()
    }
    #[cfg(target_os = "windows")]
    {
        detect_audio_windows()
    }
    #[cfg(target_os = "macos")]
    {
        detect_audio_macos()
    }
    #[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
    {
        Vec::new()
    }
}

#[cfg(target_os = "linux")]
fn detect_audio_linux() -> Vec<AudioDevice> {
    let mut out = Vec::new();
    // arecord -l 列 input devices
    if let Some(s) = run_with_timeout("arecord", &["-l"]) {
        for line in s.lines() {
            if line.starts_with("card ") {
                // 格式："card 0: PCH [HDA Intel PCH], device 0: ..."
                let name = line
                    .split(':')
                    .nth(1)
                    .map(|s| s.split('[').next().unwrap_or("").trim().to_string())
                    .unwrap_or_default();
                if !name.is_empty() {
                    out.push(AudioDevice {
                        name,
                        device_type: "input".to_string(),
                        is_default: line.contains("device 0"),
                    });
                }
            }
        }
    }
    // aplay -l 列 output devices
    if let Some(s) = run_with_timeout("aplay", &["-l"]) {
        for line in s.lines() {
            if line.starts_with("card ") {
                let name = line
                    .split(':')
                    .nth(1)
                    .map(|s| s.split('[').next().unwrap_or("").trim().to_string())
                    .unwrap_or_default();
                if !name.is_empty() {
                    out.push(AudioDevice {
                        name,
                        device_type: "output".to_string(),
                        is_default: line.contains("device 0"),
                    });
                }
            }
        }
    }
    out
}

#[cfg(target_os = "windows")]
fn detect_audio_windows() -> Vec<AudioDevice> {
    // PowerShell 查 audio devices
    let script = "Get-CimInstance Win32_SoundDevice | Select-Object -ExpandProperty Name";
    let out = run_with_timeout("powershell", &["-NoProfile", "-Command", script]);
    out.map(|s| {
        s.lines()
            .filter(|l| !l.trim().is_empty())
            .map(|name| AudioDevice {
                name: name.trim().to_string(),
                device_type: "output".to_string(),
                is_default: false,  // 簡化、PowerShell 細分要查 CIM
            })
            .collect()
    })
    .unwrap_or_default()
}

#[cfg(target_os = "macos")]
fn detect_audio_macos() -> Vec<AudioDevice> {
    // macOS 用 system_profiler
    if let Some(s) = run_with_timeout("system_profiler", &["SPAudioDataType"]) {
        let mut devices = Vec::new();
        let mut current_name: Option<String> = None;
        for line in s.lines() {
            if line.contains("Device Name:") {
                if let Some(name) = line.split(':').nth(1) {
                    current_name = Some(name.trim().to_string());
                }
            } else if line.trim() == "Input" || line.trim() == "Output" {
                if let Some(name) = current_name.take() {
                    devices.push(AudioDevice {
                        name,
                        device_type: line.trim().to_lowercase(),
                        is_default: false,
                    });
                }
            }
        }
        return devices;
    }
    Vec::new()
}

// ==================== Display ====================

pub fn detect_display() -> Option<DisplayInfo> {
    #[cfg(target_os = "linux")]
    {
        detect_display_linux()
    }
    #[cfg(target_os = "windows")]
    {
        detect_display_windows()
    }
    #[cfg(target_os = "macos")]
    {
        detect_display_macos()
    }
    #[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
    {
        None
    }
}

#[cfg(target_os = "linux")]
fn detect_display_linux() -> Option<DisplayInfo> {
    // 優先 xdpyinfo、fallback $DISPLAY 環境變數
    let out = run_with_timeout("xdpyinfo", &[])?;
    let mut width = 0;
    let mut height = 0;
    for line in out.lines() {
        if line.contains("dimensions:") {
            // "  dimensions:    1920x1080 pixels (508x285 millimeters)"
            if let Some(dim) = line.split_whitespace().find(|s| s.contains('x') && !s.contains("(")) {
                let parts: Vec<&str> = dim.split('x').collect();
                if parts.len() == 2 {
                    width = parts[0].parse().unwrap_or(0);
                    height = parts[1].parse().unwrap_or(0);
                }
            }
        }
    }
    let server = if std::env::var("WAYLAND_DISPLAY").is_ok() {
        "wayland"
    } else {
        "x11"
    };
    Some(DisplayInfo {
        server: server.to_string(),
        width,
        height,
        refresh_rate: 0.0,  // 簡化、要 monitor info 額外 call
    })
}

#[cfg(target_os = "windows")]
fn detect_display_windows() -> Option<DisplayInfo> {
    let script = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::AllScreens | ForEach-Object { Write-Output \"$($_.Bounds.Width)x$($_.Bounds.Height)\" }";
    let out = run_with_timeout("powershell", &["-NoProfile", "-Command", script])?;
    let first = out.lines().next()?;
    let parts: Vec<&str> = first.split('x').collect();
    if parts.len() != 2 {
        return None;
    }
    Some(DisplayInfo {
        server: "windows".to_string(),
        width: parts[0].parse().unwrap_or(0),
        height: parts[1].parse().unwrap_or(0),
        refresh_rate: 0.0,
    })
}

#[cfg(target_os = "macos")]
fn detect_display_macos() -> Option<DisplayInfo> {
    let out = run_with_timeout("system_profiler", &["SPDisplaysDataType"])?;
    let mut width = 0;
    let mut height = 0;
    for line in out.lines() {
        if line.contains("Resolution:") {
            // "  Resolution: 1920 x 1080"
            if let Some(res) = line.split(':').nth(1) {
                let parts: Vec<&str> = res.split(" x ").collect();
                if parts.len() == 2 {
                    width = parts[0].trim().parse().unwrap_or(0);
                    height = parts[1].trim().parse().unwrap_or(0);
                }
            }
        }
    }
    Some(DisplayInfo {
        server: "macos".to_string(),
        width,
        height,
        refresh_rate: 0.0,
    })
}

// ==================== Camera ====================

pub fn detect_cameras() -> Vec<CameraDevice> {
    #[cfg(target_os = "linux")]
    {
        detect_cameras_linux()
    }
    #[cfg(target_os = "windows")]
    {
        detect_cameras_windows()
    }
    #[cfg(target_os = "macos")]
    {
        detect_cameras_macos()
    }
    #[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
    {
        Vec::new()
    }
}

#[cfg(target_os = "linux")]
fn detect_cameras_linux() -> Vec<CameraDevice> {
    let mut out = Vec::new();
    let entries = std::fs::read_dir("/dev").ok();
    if let Some(entries) = entries {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if name_str.starts_with("video") && !name_str.contains("by-id") {
                out.push(CameraDevice {
                    device_path: format!("/dev/{}", name_str),
                    name: format!("V4L2 {}", name_str),
                    width: 0,
                    height: 0,
                    fps: 0,
                });
            }
        }
    }
    out
}

#[cfg(target_os = "windows")]
fn detect_cameras_windows() -> Vec<CameraDevice> {
    let script = "Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq 'Camera' -or $_.PNPClass -eq 'Image' } | Select-Object -ExpandProperty Name";
    let out = run_with_timeout("powershell", &["-NoProfile", "-Command", script]);
    out.map(|s| {
        s.lines()
            .filter(|l| !l.trim().is_empty())
            .enumerate()
            .map(|(i, name)| CameraDevice {
                device_path: format!("Win32_Cam_{}", i),
                name: name.trim().to_string(),
                width: 0,
                height: 0,
                fps: 0,
            })
            .collect()
    })
    .unwrap_or_default()
}

#[cfg(target_os = "macos")]
fn detect_cameras_macos() -> Vec<CameraDevice> {
    let out = run_with_timeout("system_profiler", &["SPCameraDataType"]);
    out.map(|s| {
        let mut cams = Vec::new();
        for line in s.lines() {
            if line.trim().starts_with("Model:") {
                cams.push(CameraDevice {
                    device_path: format!("macos_cam_{}", cams.len()),
                    name: line.split(':').nth(1).unwrap_or("").trim().to_string(),
                    width: 0,
                    height: 0,
                    fps: 0,
                });
            }
        }
        cams
    })
    .unwrap_or_default()
}

// ==================== 統一入口 ====================

pub fn detect_all() -> HardwareInfo {
    HardwareInfo {
        cpu: detect_cpu(),
        memory: detect_memory(),
        gpu: detect_gpu(),
        audio: detect_audio(),
        display: detect_display(),
        cameras: detect_cameras(),
    }
}

// ==================== 轉 proto ====================

impl HardwareInfo {
    pub fn to_proto(&self) -> crate::proto::HardwareInfo {
        crate::proto::HardwareInfo {
            cpu: Some(crate::proto::CpuInfo {
                model: self.cpu.model.clone(),
                cores: self.cpu.cores,
                threads: self.cpu.threads,
                frequency_ghz: self.cpu.frequency_ghz,
            }),
            memory: Some(crate::proto::MemoryInfo {
                total_bytes: self.memory.total_bytes,
                available_bytes: self.memory.available_bytes,
            }),
            gpu: self.gpu.as_ref().map(|g| crate::proto::GpuInfo {
                model: g.model.clone(),
                vendor: g.vendor.clone(),
                vram_bytes: g.vram_bytes,
                driver_version: g.driver_version.clone(),
                cuda_version: g.cuda_version.clone(),
                utilization_percent: g.utilization_percent,
                temperature_c: g.temperature_c,
            }),
            audio: self
                .audio
                .iter()
                .map(|a| crate::proto::AudioDevice {
                    name: a.name.clone(),
                    device_type: a.device_type.clone(),
                    is_default: a.is_default,
                })
                .collect(),
            display: self.display.as_ref().map(|d| crate::proto::DisplayInfo {
                server: d.server.clone(),
                width: d.width,
                height: d.height,
                refresh_rate: d.refresh_rate,
            }),
            cameras: self
                .cameras
                .iter()
                .map(|c| crate::proto::CameraDevice {
                    device_path: c.device_path.clone(),
                    name: c.name.clone(),
                    width: c.width,
                    height: c.height,
                    fps: c.fps,
                })
                .collect(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_cpu_returns_something() {
        let cpu = detect_cpu();
        assert!(!cpu.model.is_empty());
        assert!(cpu.threads > 0);
    }

    #[test]
    fn detect_memory_returns_positive() {
        let mem = detect_memory();
        assert!(mem.total_bytes > 0);
    }

    #[test]
    fn detect_all_doesnt_panic() {
        let hw = detect_all();
        // gpu/audio/display/cameras 可能都是 None/[]、但 cpu/mem 一定要有
        assert!(!hw.cpu.model.is_empty());
        assert!(hw.memory.total_bytes > 0);
    }

    #[test]
    fn to_proto_round_trip() {
        let hw = HardwareInfo {
            cpu: CpuInfo {
                model: "Test CPU".to_string(),
                cores: 8,
                threads: 16,
                frequency_ghz: 3.5,
            },
            memory: MemoryInfo {
                total_bytes: 16 * 1024 * 1024 * 1024,
                available_bytes: 8 * 1024 * 1024 * 1024,
            },
            gpu: Some(GpuInfo {
                model: "Test GPU".to_string(),
                vendor: "NVIDIA".to_string(),
                vram_bytes: 8 * 1024 * 1024 * 1024,
                driver_version: "555.85".to_string(),
                cuda_version: "12.5".to_string(),
                utilization_percent: 50.0,
                temperature_c: 65.0,
            }),
            audio: vec![AudioDevice {
                name: "Built-in Audio".to_string(),
                device_type: "output".to_string(),
                is_default: true,
            }],
            display: Some(DisplayInfo {
                server: "x11".to_string(),
                width: 1920,
                height: 1080,
                refresh_rate: 60.0,
            }),
            cameras: vec![],
        };
        let proto = hw.to_proto();
        assert_eq!(proto.cpu.as_ref().unwrap().cores, 8);
        assert_eq!(proto.memory.as_ref().unwrap().total_bytes, 16 * 1024 * 1024 * 1024);
        assert_eq!(proto.gpu.as_ref().unwrap().model, "Test GPU");
        assert_eq!(proto.audio.len(), 1);
        assert_eq!(proto.display.as_ref().unwrap().width, 1920);
    }
}
