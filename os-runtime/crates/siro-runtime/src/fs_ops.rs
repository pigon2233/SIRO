// src/fs_ops.rs - v1.5.3 ReadFile / WriteFile / ListDirectory / StatPath 實作
//
// 跟 bridge/tools/filesystem.py 對齊、但有 Rust type-safety
// 所有操作必須先過 sandbox.rs 路徑檢查

use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use thiserror::Error;

use crate::sandbox;

/// 檔案讀取結果
#[derive(Debug)]
pub struct FileReadResult {
    pub path: PathBuf,
    pub content: String,
    pub size_bytes: u64,
    pub truncated: bool,
    pub line_count: usize,
}

/// 檔案寫入結果
#[derive(Debug)]
pub struct FileWriteResult {
    pub bytes_written: u64,
}

/// 目錄 listing 結果
#[derive(Debug)]
pub struct DirListing {
    pub path: PathBuf,
    pub entries: Vec<String>,
    pub count: usize,
    pub truncated: bool,
}

/// 路徑 stat 結果
#[derive(Debug)]
pub struct PathStatResult {
    pub path: PathBuf,
    pub exists: bool,
    pub is_file: bool,
    pub is_dir: bool,
    pub size_bytes: u64,
    pub modified_ms: i64,
}

/// File system 錯誤
#[derive(Debug, Error)]
pub enum FsError {
    #[error("Sandbox 錯誤：{0}")]
    Sandbox(#[from] sandbox::SandboxError),

    #[error("檔案不存在：{0}")]
    NotFound(String),

    #[error("不是檔案：{0}")]
    NotAFile(String),

    #[error("不是目錄：{0}")]
    NotADir(String),

    #[error("讀檔失敗：{0}")]
    ReadFailed(String),

    #[error("寫檔失敗：{0}")]
    WriteFailed(String),

    #[error("建父目錄失敗：{0}")]
    MkdirFailed(String),

    #[error("列目錄失敗：{0}")]
    ListDirFailed(String),
}

const MAX_FILE_BYTES: u64 = 200_000;
const MAX_DIR_ENTRIES: usize = 1000;
const MAX_LINES_PER_READ: usize = 500;

/// 判斷 joined path 是否在 sandbox 內（處理 .. 跟 symlink）
///
/// 算法：
/// 1. 收集 joined 的 component 到 vec
/// 2. 把 `..` 套用掉（消耗前一個 normal component）
/// 3. 結果跟 sandbox_root component 比對
/// 4. 如果 joined 是 sandbox 的 prefix 或 equal → inside
fn is_within_sandbox(joined: &Path, sandbox_root: &Path) -> bool {
    use std::path::Component;

    // 把 joined 的 component 攤平（處理 ..）
    let mut normalized: Vec<Component<'_>> = Vec::new();
    for comp in joined.components() {
        match comp {
            Component::ParentDir => {
                // 嘗試消耗前一個 normal component
                if let Some(last) = normalized.last() {
                    if matches!(last, Component::Normal(_)) {
                        normalized.pop();
                        continue;
                    }
                }
                // 前面沒有可消耗的（Prefix / RootDir / CurDir）→ 已經在 root
                // 不加進 normalized
            }
            Component::CurDir => {
                // ignore
            }
            Component::Prefix(_) | Component::RootDir => {
                // 對 Windows 來說、C:\ 是 root
                normalized.push(comp);
            }
            Component::Normal(_) => {
                normalized.push(comp);
            }
        }
    }

    // sandbox_root 也攤平
    let mut sandbox_components: Vec<Component<'_>> = Vec::new();
    for comp in sandbox_root.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                if let Some(last) = sandbox_components.last() {
                    if matches!(last, Component::Normal(_)) {
                        sandbox_components.pop();
                        continue;
                    }
                }
            }
            Component::Prefix(_) | Component::RootDir => sandbox_components.push(comp),
            Component::Normal(_) => sandbox_components.push(comp),
        }
    }

    // joined 的 normalized 必須是 sandbox 的 prefix 或 equal
    if normalized.len() < sandbox_components.len() {
        return false;
    }
    for (a, b) in normalized.iter().take(sandbox_components.len()).zip(sandbox_components.iter()) {
        if a != b {
            return false;
        }
    }
    true
}

/// 讀檔
pub fn read_file(
    raw_path: &str,
    sandbox_root: &Path,
    max_lines: Option<usize>,
) -> Result<FileReadResult, FsError> {
    // 步驟 1: 拿到 lenient path（檔案可能還沒建出來）
    let lenient_path = sandbox::resolve_path_lenient(raw_path, sandbox_root)?;

    // 步驟 2: 檢查是否在 sandbox 內（用 component 比對）
    // 即使 strict canonicalize 失敗、lenient 也能判斷是否在 sandbox 內
    if !is_within_sandbox(&lenient_path, sandbox_root) {
        return Err(FsError::Sandbox(sandbox::SandboxError::PathTraversal(
            raw_path.to_string(),
        )));
    }

    // 步驟 3: 檢查檔案是否存在
    if !lenient_path.exists() {
        return Err(FsError::NotFound(raw_path.to_string()));
    }
    if !lenient_path.is_file() {
        return Err(FsError::NotAFile(raw_path.to_string()));
    }

    // 步驟 4: 嘗試 strict resolve（防 symlink attack）
    // 如果失敗但 lenient_path exists、就用 lenient_path 當最終路徑
    let path = sandbox::resolve_path(raw_path, sandbox_root)
        .unwrap_or(lenient_path);

    // 檢查大小
    let metadata = std::fs::metadata(&path)
        .map_err(|e| FsError::ReadFailed(format!("stat: {}", e)))?;
    if metadata.len() > MAX_FILE_BYTES {
        return Err(FsError::ReadFailed(format!(
            "檔案太大（{} bytes > {}）",
            metadata.len(),
            MAX_FILE_BYTES
        )));
    }

    // 讀
    let content = std::fs::read_to_string(&path)
        .map_err(|e| FsError::ReadFailed(format!("read: {}", e)))?;

    // 限制行數
    let max = max_lines.unwrap_or(200).min(MAX_LINES_PER_READ);
    let mut lines: Vec<&str> = content.lines().collect();
    let truncated = lines.len() > max;
    if truncated {
        lines.truncate(max);
    }
    let final_content = lines.join("\n");

    Ok(FileReadResult {
        path,
        content: final_content,
        size_bytes: metadata.len(),
        truncated,
        line_count: lines.len(),
    })
}

/// 寫檔
pub fn write_file(
    raw_path: &str,
    content: &str,
    sandbox_root: &Path,
) -> Result<FileWriteResult, FsError> {
    // 寫檔用寬鬆版（檔案可能還沒存在）
    let path = sandbox::resolve_path_lenient(raw_path, sandbox_root)?;

    // 自動建父目錄
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| FsError::MkdirFailed(format!("{}: {}", parent.display(), e)))?;
    }

    std::fs::write(&path, content)
        .map_err(|e| FsError::WriteFailed(format!("{}: {}", path.display(), e)))?;

    Ok(FileWriteResult {
        bytes_written: content.len() as u64,
    })
}

/// 列目錄
pub fn list_directory(
    raw_path: &str,
    sandbox_root: &Path,
    recursive: bool,
) -> Result<DirListing, FsError> {
    // 先 strict resolve — 偵測 path traversal
    let path = match sandbox::resolve_path(raw_path, sandbox_root) {
        Ok(p) => p,
        Err(sandbox::SandboxError::PathTraversal(_)) => {
            return Err(FsError::Sandbox(sandbox::SandboxError::PathTraversal(
                raw_path.to_string(),
            )));
        }
        Err(_) => {
            // 可能是目錄不存在、fallback 到 lenient
            let path = sandbox::resolve_path_lenient(raw_path, sandbox_root)?;
            if !path.exists() {
                return Err(FsError::NotFound(raw_path.to_string()));
            }
            path
        }
    };

    if !path.is_dir() {
        return Err(FsError::NotADir(raw_path.to_string()));
    }

    let mut entries: Vec<String> = Vec::new();
    let mut truncated = false;

    // 簡易 recursive：自己 recursive
    fn collect(
        dir: &Path,
        prefix: &Path,
        entries: &mut Vec<String>,
        limit: usize,
        truncated: &mut bool,
    ) -> std::io::Result<()> {
        if entries.len() >= limit {
            *truncated = true;
            return Ok(());
        }
        for entry in std::fs::read_dir(dir)? {
            let entry = entry?;
            let entry_path = entry.path();
            let rel_str = match entry_path.strip_prefix(prefix) {
                Ok(rel) => rel.to_string_lossy().to_string(),
                Err(_) => entry_path.to_string_lossy().to_string(),
            };
            let is_dir = entry.file_type()?.is_dir();
            let marker = if is_dir { "/" } else { "" };
            entries.push(format!("{}{}", rel_str, marker));
            if entries.len() >= limit {
                *truncated = true;
                return Ok(());
            }
            if is_dir {
                collect(&entry.path(), prefix, entries, limit, truncated)?;
                if entries.len() >= limit {
                    return Ok(());
                }
            }
        }
        Ok(())
    }

    if recursive {
        // 走整個 subtree
        collect(&path, &path, &mut entries, MAX_DIR_ENTRIES, &mut truncated)
            .map_err(|e| FsError::ListDirFailed(format!("recursive walk: {}", e)))?;
    } else {
        // 只列當層
        let read = std::fs::read_dir(&path)
            .map_err(|e| FsError::ListDirFailed(format!("read_dir: {}", e)))?;
        for entry in read {
            let entry = entry.map_err(|e| FsError::ListDirFailed(format!("entry: {}", e)))?;
            let is_dir = entry
                .file_type()
                .map_err(|e| FsError::ListDirFailed(format!("file_type: {}", e)))?
                .is_dir();
            let marker = if is_dir { "/" } else { "" };
            let name = entry.file_name().to_string_lossy().to_string();
            entries.push(format!("{}{}", name, marker));
            if entries.len() >= MAX_DIR_ENTRIES {
                truncated = true;
                break;
            }
        }
    }

    let count = entries.len();
    Ok(DirListing {
        path,
        entries,
        count,
        truncated,
    })
}

/// Path stat
pub fn stat_path(raw_path: &str, sandbox_root: &Path) -> Result<PathStatResult, FsError> {
    // 用寬鬆版（檔案可能不存在）
    let path = sandbox::resolve_path_lenient(raw_path, sandbox_root)?;

    let exists = path.exists();
    let is_file = path.is_file();
    let is_dir = path.is_dir();
    let size_bytes = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
    let modified_ms = std::fs::metadata(&path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0);

    Ok(PathStatResult {
        path,
        exists,
        is_file,
        is_dir,
        size_bytes,
        modified_ms,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_sandbox() -> PathBuf {
        // 用淺層 sandbox（C:\siro_fs_test_xxx）讓 .. 真的能逃出
        // temp dir 太深、test 邏輯會 fail
        let dir = PathBuf::from(format!(
            "C:\\siro_fs_test_{}",
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
    fn test_read_file_ok() {
        let root = temp_sandbox();
        std::fs::write(root.join("hello.txt"), "Hello Rust!").unwrap();

        let result = read_file("hello.txt", &root, None).unwrap();
        assert_eq!(result.content, "Hello Rust!");
        assert!(!result.truncated);
        assert_eq!(result.size_bytes, 11);
        assert_eq!(result.line_count, 1);
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_read_file_with_max_lines_truncates() {
        let root = temp_sandbox();
        let content = (0..100).map(|i| format!("line {}", i)).collect::<Vec<_>>().join("\n");
        std::fs::write(root.join("long.txt"), &content).unwrap();

        let result = read_file("long.txt", &root, Some(5)).unwrap();
        assert!(result.truncated);
        assert_eq!(result.line_count, 5);
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_read_nonexistent() {
        let root = temp_sandbox();
        let result = read_file("does_not_exist.txt", &root, None);
        assert!(matches!(result, Err(FsError::NotFound(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_read_path_traversal_rejected() {
        let root = temp_sandbox();
        let result = read_file("../etc/passwd", &root, None);
        assert!(matches!(result, Err(FsError::Sandbox(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_write_file_ok() {
        let root = temp_sandbox();
        let result = write_file("new_file.txt", "content here", &root).unwrap();
        assert_eq!(result.bytes_written, 12);
        assert_eq!(std::fs::read_to_string(root.join("new_file.txt")).unwrap(), "content here");
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_write_file_creates_parents() {
        let root = temp_sandbox();
        let result = write_file("a/b/c/deep.txt", "deep", &root).unwrap();
        assert_eq!(result.bytes_written, 4);
        assert!(root.join("a/b/c/deep.txt").exists());
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_write_path_traversal_rejected() {
        let root = temp_sandbox();
        let result = write_file("../../../../../escape.txt", "x", &root);
        assert!(matches!(result, Err(FsError::Sandbox(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_list_directory_ok() {
        let root = temp_sandbox();
        std::fs::write(root.join("a.txt"), "").unwrap();
        std::fs::create_dir(root.join("b_dir")).unwrap();
        std::fs::write(root.join("c.txt"), "").unwrap();

        let result = list_directory(".", &root, false).unwrap();
        assert_eq!(result.count, 3);
        let names: Vec<&str> = result.entries.iter().map(|s| s.as_str()).collect();
        assert!(names.contains(&"a.txt"));
        assert!(names.contains(&"b_dir/"));
        assert!(names.contains(&"c.txt"));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_list_directory_recursive() {
        let root = temp_sandbox();
        std::fs::create_dir_all(root.join("a/b/c")).unwrap();
        std::fs::write(root.join("a/b/c/deep.txt"), "").unwrap();
        std::fs::write(root.join("top.txt"), "").unwrap();

        let result = list_directory(".", &root, true).unwrap();
        let names: Vec<&str> = result.entries.iter().map(|s| s.as_str()).collect();
        assert!(names.iter().any(|n| n.contains("deep.txt")));
        assert!(names.iter().any(|n| n.contains("top.txt")));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_list_directory_not_found() {
        let root = temp_sandbox();
        let result = list_directory("nonexistent", &root, false);
        assert!(matches!(result, Err(FsError::NotFound(_))));
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_stat_existing_file() {
        let root = temp_sandbox();
        std::fs::write(root.join("file.txt"), "hello").unwrap();
        let result = stat_path("file.txt", &root).unwrap();
        assert!(result.exists);
        assert!(result.is_file);
        assert!(!result.is_dir);
        assert_eq!(result.size_bytes, 5);
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn test_stat_nonexistent() {
        let root = temp_sandbox();
        let result = stat_path("does_not_exist.txt", &root).unwrap();
        assert!(!result.exists);
        assert!(!result.is_file);
        assert!(!result.is_dir);
        std::fs::remove_dir_all(&root).ok();
    }
}
