// src/platform/macos.rs - macOS 路徑 STUB (Phase 4+ 補實作)
//
// macOS 支援不在 SIRO v0.5 / Phase 4 範圍，但保留 stub 讓 trait 完整。
// 對應 Python 端: bridge/platform/ 整套抽象層。

use std::path::PathBuf;

use super::PlatformPaths;

pub struct MacosPaths;

impl PlatformPaths for MacosPaths {
    fn user_data_dir() -> PathBuf {
        unimplemented!(
            "macOS platform paths 待未來補實作 (Phase 4+ 之後)\n\
             見 docs/PHASE4_LINUX.md 設計文件 (macOS section 待補)"
        )
    }

    fn user_config_dir() -> PathBuf {
        unimplemented!("macOS — 見 user_data_dir()")
    }

    fn user_log_dir() -> PathBuf {
        unimplemented!("macOS — 見 user_data_dir()")
    }

    fn runtime_socket_path() -> String {
        unimplemented!("macOS — 見 user_data_dir()")
    }

    fn siro_sandbox_dir() -> PathBuf {
        unimplemented!("macOS — 見 user_data_dir()")
    }
}
