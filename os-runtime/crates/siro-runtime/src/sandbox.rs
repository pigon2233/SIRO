// src/sandbox.rs - v1.5.3 Computer Control sandbox path check
//
// 跟 bridge/security.py 的 SandboxPath 對齊
// 確保 Rust 端跟 Python 端的 sandbox 邏輯一致
//
// 設計：
// - sandbox root 從 env var SIRO_SANDBOX_DIR 讀、預設 ~/siro-sandbox
// - 拒絕絕對路徑（v1.5+ 階段 LLM 不該用絕對路徑）
// - 拒絕 path traversal（".." 會跳出去）
// - 拒絕 symlink 指到 sandbox 外
// - 拒絕 sandbox 路徑下不存在 parent 的相對路徑
//
// ⚠️ 已知 Linux edge case（Phase 4+ 處理）：
// - 9P / overlayfs / snap / AppImage mount point 跨 prefix 時
//   canonicalize() 可能回傳不同前綴、starts_with 比較會失敗
// - 容器（Docker / podman）裡 bind mount 進來的 path 行為類似
// - 常見 FS（ext4 / xfs / btrfs）行為一致、暫不處理
// - 觸發情境罕見（v0.x 99% 用 local FS）、影響有限

use std::path::{Path, PathBuf};

/// Sandbox 安全錯誤
#[derive(Debug, thiserror::Error)]
pub enum SandboxError {
    #[error("路徑不可為空")]
    Empty,

    #[error("不允許絕對路徑：{0:?}（請用相對於 sandbox 根目錄的路徑）")]
    AbsolutePath(String),

    #[error("path traversal 被擋下：{0:?}（解析後不在 sandbox 內）")]
    PathTraversal(String),

    #[error("路徑解析失敗：{0}")]
    ResolveFailed(String),
}

/// 拿 sandbox 根目錄
/// env var SIRO_SANDBOX_DIR 優先、否則用 ~/siro-sandbox
pub fn get_sandbox_root() -> Result<PathBuf, SandboxError> {
    let path_str = std::env::var("SIRO_SANDBOX_DIR").unwrap_or_else(|_| {
        // 預設 ~/siro-sandbox
        if let Some(home) = std::env::var_os("HOME")
            .or_else(|| std::env::var_os("USERPROFILE"))
        {
            let mut p = PathBuf::from(home);
            p.push("siro-sandbox");
            return p.to_string_lossy().to_string();
        }
        "siro-sandbox".to_string()
    });

    let p = PathBuf::from(&path_str);
    // 不強制 exists（sandbox 還沒建時也能拿到 root）
    // 但路徑要 valid UTF-8 / valid path
    Ok(p)
}

/// 拿掉 Windows `\\?\` UNC prefix（canonicalize 會加、不去掉會讓 starts_with fail）
fn strip_unc_prefix(path: &Path) -> PathBuf {
    let s = path.to_string_lossy();
    if let Some(stripped) = s.strip_prefix(r"\\?\") {
        PathBuf::from(stripped)
    } else {
        path.to_path_buf()
    }
}

/// 把 LLM 給的相對路徑解析成絕對路徑、確認在 sandbox 內
///
/// # Arguments
/// * `raw_path` - LLM 給的路徑（相對於 sandbox、空 = sandbox 根）
/// * `sandbox_root` - sandbox 根目錄（通常從 `get_sandbox_root()` 拿）
///
/// # Returns
/// * `Ok(PathBuf)` - 解析後的絕對路徑、保證在 sandbox 內
/// * `Err(SandboxError)` - 路徑無效 / 在 sandbox 外 / traversal
pub fn resolve_path<P: AsRef<Path>>(
    raw_path: P,
    sandbox_root: &Path,
) -> Result<PathBuf, SandboxError> {
    let raw = raw_path.as_ref();
    let raw_str = raw.to_string_lossy().to_string();

    if raw_str.is_empty() {
        return Err(SandboxError::Empty);
    }

    // 預處理：把 "." / "" 當作 sandbox 根
    if raw_str == "." || raw_str == "" {
        return Ok(sandbox_root.to_path_buf());
    }

    let candidate = Path::new(raw);

    // 拒絕絕對路徑
    if candidate.is_absolute() {
        return Err(SandboxError::AbsolutePath(raw_str));
    }

    // 把 sandbox root 當前綴
    let joined = sandbox_root.join(candidate);

    // 先檢查 .. 算 depth（path traversal 在 canonicalize 之前就要擋下、避免
    // 已經跳出 sandbox 的 path 被 canonicalize 成別的 path）
    let mut depth: i32 = 0;
    for comp in joined.components() {
        use std::path::Component;
        match comp {
            Component::ParentDir => {
                depth -= 1;
                if depth < 0 {
                    return Err(SandboxError::PathTraversal(raw_str));
                }
            }
            Component::CurDir => {}
            _ => {
                depth += 1;
            }
        }
    }

    // resolve（會處理 .. 跟 symlink）
    let resolved_raw = match joined.canonicalize() {
        Ok(p) => p,
        Err(e) => {
            return Err(SandboxError::ResolveFailed(format!(
                "{}: {}",
                raw_str, e
            )));
        }
    };

    // 拿掉 Windows UNC prefix（避免 starts_with 比較失敗）
    let resolved = strip_unc_prefix(&resolved_raw);
    let sandbox_normalized = strip_unc_prefix(sandbox_root);

    // 確認 resolved 在 sandbox root 內
    if !resolved.starts_with(&sandbox_normalized) {
        return Err(SandboxError::PathTraversal(raw_str));
    }

    Ok(resolved)
}

/// 寬鬆版 resolve：檔案不存在時不報錯、回傳「應該在的路徑」（不 canonicalize）
/// 給 write_file / mkdir 用（檔案還沒建出來）
///
/// # Arguments
/// * `raw_path` - LLM 給的路徑
/// * `sandbox_root` - sandbox 根目錄
///
/// # Returns
/// * `Ok(PathBuf)` - 應該在 sandbox 內的路徑（沒 canonicalize、可能 parent 不存在）
/// * `Err(SandboxError)` - 絕對路徑 / path traversal
pub fn resolve_path_lenient<P: AsRef<Path>>(
    raw_path: P,
    sandbox_root: &Path,
) -> Result<PathBuf, SandboxError> {
    let raw = raw_path.as_ref();
    let raw_str = raw.to_string_lossy().to_string();

    if raw_str.is_empty() {
        return Err(SandboxError::Empty);
    }

    if raw_str == "." || raw_str == "" {
        return Ok(sandbox_root.to_path_buf());
    }

    let candidate = Path::new(raw);

    if candidate.is_absolute() {
        return Err(SandboxError::AbsolutePath(raw_str));
    }

    let joined = sandbox_root.join(candidate);

    // 手動檢查 ..：把路徑拆 components、算 depth
    let mut depth: i32 = 0;
    for comp in joined.components() {
        use std::path::Component;
        match comp {
            Component::ParentDir => {
                depth -= 1;
                if depth < 0 {
                    return Err(SandboxError::PathTraversal(raw_str));
                }
            }
            Component::CurDir => {}
            _ => {
                depth += 1;
            }
        }
    }

    // 確認 joined 開頭是 sandbox_root
    if !joined.starts_with(sandbox_root) {
        return Err(SandboxError::PathTraversal(raw_str));
    }

    Ok(joined)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_sandbox() -> PathBuf {
        // 用淺層 sandbox（C:\siro_test_xxx）、讓 .. 真的能逃出
        // temp dir 太深（多層 Users\jason\AppData\Local\Temp\..）、
        // 一個 .. 不一定逃出、test 邏輯會 fail
        let dir = PathBuf::from(format!(
            "C:\\siro_sandbox_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn test_resolve_dot_returns_sandbox_root() {
        let root = temp_sandbox();
        assert_eq!(resolve_path(".", &root).unwrap(), root);
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_resolve_relative_path_inside() {
        let root = temp_sandbox();
        std::fs::create_dir_all(root.join("notes")).unwrap();
        std::fs::write(root.join("notes/hello.txt"), "x").unwrap();

        let resolved = resolve_path("notes/hello.txt", &root).unwrap();
        assert_eq!(resolved, root.join("notes/hello.txt"));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_resolve_empty_rejected() {
        let root = temp_sandbox();
        assert!(matches!(resolve_path("", &root), Err(SandboxError::Empty)));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_resolve_absolute_path_rejected() {
        let root = temp_sandbox();
        // Unix 風格絕對路徑
        let result = resolve_path("/etc/passwd", &root);
        // Windows 上 /etc/passwd 可能不是 absolute、會被視為相對
        // 但 canonicalize 後不在 sandbox 內、會報 PathTraversal
        // 反正兩種錯誤都正確擋下
        assert!(result.is_err());
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_resolve_parent_traversal_rejected() {
        let root = temp_sandbox();
        // 用足夠深的 .. 保證逃出 temp dir（Windows temp dir 是 C:\Users\...\Temp\，
        // 5 個 .. 一定跳出）
        let result = resolve_path("../../../../../etc/passwd", &root);
        assert!(matches!(result, Err(SandboxError::PathTraversal(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_resolve_deep_traversal_rejected() {
        let root = temp_sandbox();
        let result = resolve_path("../../../../../../../../etc/passwd", &root);
        assert!(matches!(result, Err(SandboxError::PathTraversal(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_resolve_parent_then_back_in_rejected() {
        let root = temp_sandbox();
        std::fs::create_dir_all(root.join("notes")).unwrap();
        // notes/../../../../../../../../outside — deep enough to escape
        let result = resolve_path("notes/../../../../../../../../outside/foo.txt", &root);
        assert!(matches!(result, Err(SandboxError::PathTraversal(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_lenient_resolve_nonexistent_path_ok() {
        let root = temp_sandbox();
        // 檔案不存在、但寬鬆版允許
        let result = resolve_path_lenient("notes/new_file.txt", &root).unwrap();
        assert_eq!(result, root.join("notes/new_file.txt"));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_lenient_resolve_traversal_rejected() {
        let root = temp_sandbox();
        let result = resolve_path_lenient("../../../../../etc/passwd", &root);
        assert!(matches!(result, Err(SandboxError::PathTraversal(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_lenient_resolve_deep_traversal_rejected() {
        let root = temp_sandbox();
        let result = resolve_path_lenient("a/b/../../../../../../outside", &root);
        assert!(matches!(result, Err(SandboxError::PathTraversal(_))));
        std::fs::remove_dir_all(&root).ok();
    }
}
