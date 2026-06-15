// src/platform/linux.rs - Linux 路徑 STUB (Phase 4 補實作)
//
// Phase 4 補實作的待辦清單:
// - XDG paths via directories crate (XDG_DATA_HOME / XDG_CONFIG_HOME / XDG_STATE_HOME)
// - systemd service installer via zbus 或直接 systemctl --user
// - XDG autostart .desktop 寫到 $XDG_CONFIG_HOME/autostart/
//
// 對應 Python 端: bridge/platform/service_linux.py / autostart_linux.py
//
// 目前所有方法都 panic!()，因為 SIRO v0.5 target 是 Windows。
// 編譯時這檔只會被 cfg(target_os = "linux") 條件性 include。

use std::path::PathBuf;

use super::PlatformPaths;

pub struct LinuxPaths;

impl PlatformPaths for LinuxPaths {
    fn user_data_dir() -> PathBuf {
        unimplemented!(
            "Linux platform paths 待 Phase 4 實作\n\
             見 docs/PHASE4_LINUX.md 設計文件\n\
             對應 Python 端: bridge/platform/paths.py"
        )
    }

    fn user_config_dir() -> PathBuf {
        unimplemented!("Phase 4 — 見 user_data_dir()")
    }

    fn user_log_dir() -> PathBuf {
        unimplemented!("Phase 4 — 見 user_data_dir()")
    }

    fn runtime_socket_path() -> String {
        unimplemented!("Phase 4 — 見 user_data_dir()")
    }

    fn siro_sandbox_dir() -> PathBuf {
        unimplemented!("Phase 4 — 見 user_data_dir()")
    }
}
