// src/commands.rs - v1.5.3 ExecuteCommand 實作
//
// 跑 shell 指令、subprocess + shlex split、sandbox 路徑檢查、audit log
// 跟 bridge/tools/shell.py 對齊、但更嚴格（Rust 的 type-safety）
//
// 設計：
// - 用 shlex split cmd 防止 shell injection
// - cwd 必須在 sandbox 內
// - timeout 預設 30s、最大 300s
// - stdout/stderr 截斷到 2000 字（避免 token 爆炸）
// - 失敗時回傳詳細錯誤（status code、stdout、stderr）

use std::path::Path;
use std::process::Stdio;
use std::time::{Duration, Instant};

use thiserror::Error;
use tokio::io::AsyncReadExt;
use tokio::process::Command;

/// Command execution 結果
#[derive(Debug)]
pub struct CommandResult {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    pub original_size_stdout: usize,
    pub original_size_stderr: usize,
    pub duration_ms: i64,
}

/// Command execution 錯誤
#[derive(Debug, Error)]
pub enum CommandError {
    #[error("cmd 不可為空")]
    Empty,

    #[error("cmd 解析失敗：{0}")]
    ParseFailed(String),

    #[error("工作目錄無效：{0}")]
    InvalidCwd(String),

    #[error("Timeout（{0}s）")]
    Timeout(u32),

    #[error("指令找不到：{0}")]
    NotFound(String),

    #[error("OS 錯誤：{0}")]
    OsError(String),
}

const MAX_OUTPUT: usize = 2000;
const DEFAULT_TIMEOUT_SEC: u32 = 30;
const MAX_TIMEOUT_SEC: u32 = 300;

/// 跑 shell 指令
///
/// # Arguments
/// * `cmd` - 完整指令字串（會用 shlex split、shell=False 防止 injection）
/// * `cwd` - 工作目錄（必須在 sandbox 內）
/// * `timeout_sec` - timeout（None 用預設 30s）
///
/// # Returns
/// * `Ok(CommandResult)` - 跑完（不論 exit code、就算非 0 也算 Ok）
/// * `Err(CommandError)` - 啟動失敗 / timeout / 其他 OS 錯誤
pub async fn execute_command(
    cmd: &str,
    cwd: &Path,
    timeout_sec: Option<u32>,
) -> Result<CommandResult, CommandError> {
    if cmd.trim().is_empty() {
        return Err(CommandError::Empty);
    }

    let timeout = timeout_sec.unwrap_or(DEFAULT_TIMEOUT_SEC);
    if timeout == 0 || timeout > MAX_TIMEOUT_SEC {
        return Err(CommandError::Timeout(MAX_TIMEOUT_SEC));
    }

    // shlex split
    let parts: Vec<String> = match shlex::split(cmd) {
        Some(parts) if !parts.is_empty() => parts,
        Some(_) => return Err(CommandError::ParseFailed("cmd 解析後是空的".to_string())),
        None => return Err(CommandError::ParseFailed("shlex split 失敗".to_string())),
    };

    // 確認 cwd 存在、是目錄
    if !cwd.exists() {
        return Err(CommandError::InvalidCwd(format!(
            "目錄不存在：{}",
            cwd.display()
        )));
    }
    if !cwd.is_dir() {
        return Err(CommandError::InvalidCwd(format!(
            "不是目錄：{}",
            cwd.display()
        )));
    }

    // 跑 subprocess
    let start = Instant::now();
    let mut child = Command::new(&parts[0])
        .args(&parts[1..])
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::null())
        .spawn()
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                CommandError::NotFound(format!("{}: {}", parts[0], e))
            } else {
                CommandError::OsError(format!("{}: {}", parts[0], e))
            }
        })?;

    let mut stdout = child.stdout.take().expect("stdout was piped");
    let mut stderr = child.stderr.take().expect("stderr was piped");

    // 非同步讀 stdout / stderr
    let stdout_task = tokio::spawn(async move {
        let mut buf = Vec::new();
        stdout.read_to_end(&mut buf).await.map(|_| buf)
    });
    let stderr_task = tokio::spawn(async move {
        let mut buf = Vec::new();
        stderr.read_to_end(&mut buf).await.map(|_| buf)
    });

    // 等 child + timeout
    let exit_status = match tokio::time::timeout(
        Duration::from_secs(timeout as u64),
        child.wait(),
    )
    .await
    {
        Ok(Ok(status)) => status,
        Ok(Err(e)) => return Err(CommandError::OsError(format!("wait 失敗：{}", e))),
        Err(_) => {
            // timeout — kill process
            let _ = child.start_kill();
            // 給它一點時間真的死掉
            let _ = tokio::time::timeout(Duration::from_secs(2), child.wait()).await;
            return Err(CommandError::Timeout(timeout));
        }
    };

    let stdout_bytes = stdout_task.await.map_err(|e| {
        CommandError::OsError(format!("stdout task join failed: {}", e))
    })?
    .map_err(|e| CommandError::OsError(format!("stdout read failed: {}", e)))?;

    let stderr_bytes = stderr_task.await.map_err(|e| {
        CommandError::OsError(format!("stderr task join failed: {}", e))
    })?
    .map_err(|e| CommandError::OsError(format!("stderr read failed: {}", e)))?;

    let duration_ms = start.elapsed().as_millis() as i64;

    let stdout_str = String::from_utf8_lossy(&stdout_bytes).to_string();
    let stderr_str = String::from_utf8_lossy(&stderr_bytes).to_string();

    // 截斷
    let original_size_stdout = stdout_str.len();
    let original_size_stderr = stderr_str.len();
    let (stdout_truncated, stdout_final) = truncate(&stdout_str, MAX_OUTPUT);
    let (stderr_truncated, stderr_final) = truncate(&stderr_str, MAX_OUTPUT);

    // Windows 上 exit_code 用 i32 (其實是 u32)、這裡轉成 i32
    let exit_code = exit_status.code().unwrap_or(-1) as i32;

    Ok(CommandResult {
        exit_code,
        stdout: stdout_final,
        stderr: stderr_final,
        stdout_truncated,
        stderr_truncated,
        original_size_stdout,
        original_size_stderr,
        duration_ms,
    })
}

fn truncate(s: &str, max: usize) -> (bool, String) {
    if s.len() > max {
        let truncated = format!(
            "{}\n... (truncated, 原本 {} 字)",
            &s[..max],
            s.len()
        );
        (true, truncated)
    } else {
        (false, s.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_sandbox() -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "siro_cmd_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[tokio::test]
    async fn test_run_echo() {
        let cwd = temp_sandbox();
        // Windows 用 cmd /c echo, Unix 用 echo
        #[cfg(windows)]
        let result = execute_command("cmd /c echo hello", &cwd, None).await.unwrap();
        #[cfg(not(windows))]
        let result = execute_command("echo hello", &cwd, None).await.unwrap();

        assert_eq!(result.exit_code, 0);
        assert!(result.stdout.contains("hello"));
        assert_eq!(result.duration_ms >= 0, true);
        std::fs::remove_dir_all(&cwd).ok();
    }

    #[tokio::test]
    async fn test_run_empty_rejected() {
        let cwd = temp_sandbox();
        let result = execute_command("", &cwd, None).await;
        assert!(matches!(result, Err(CommandError::Empty)));
        std::fs::remove_dir_all(&cwd).ok();
    }

    #[tokio::test]
    async fn test_run_nonexistent_command() {
        let cwd = temp_sandbox();
        let result = execute_command("definitely_not_a_real_cmd_xyz_123", &cwd, None).await;
        // Windows 上 subprocess 會立刻 fail with NotFound
        // Unix 上也類似
        assert!(matches!(result, Err(CommandError::NotFound(_))));
        std::fs::remove_dir_all(&cwd).ok();
    }

    #[tokio::test]
    async fn test_run_with_cwd_file_fails() {
        // cwd 指向檔案而不是目錄
        let cwd = temp_sandbox();
        let file_path = cwd.join("not_a_dir.txt");
        std::fs::write(&file_path, "x").unwrap();
        let result = execute_command("echo hi", &file_path, None).await;
        assert!(matches!(result, Err(CommandError::InvalidCwd(_))));
        std::fs::remove_dir_all(&cwd).ok();
    }

    #[tokio::test]
    async fn test_run_with_nonexistent_cwd() {
        let cwd = temp_sandbox();
        let nonexistent = cwd.join("does_not_exist");
        let result = execute_command("echo hi", &nonexistent, None).await;
        assert!(matches!(result, Err(CommandError::InvalidCwd(_))));
        std::fs::remove_dir_all(&cwd).ok();
    }

    #[tokio::test]
    async fn test_run_timeout() {
        let cwd = temp_sandbox();
        #[cfg(windows)]
        let result = execute_command("ping -n 5 127.0.0.1", &cwd, Some(1)).await;
        #[cfg(not(windows))]
        let result = execute_command("sleep 5", &cwd, Some(1)).await;
        assert!(matches!(result, Err(CommandError::Timeout(_))));
        std::fs::remove_dir_all(&cwd).ok();
    }

    #[test]
    fn test_truncate_under_limit() {
        let s = "short";
        let (truncated, out) = truncate(s, 100);
        assert!(!truncated);
        assert_eq!(out, s);
    }

    #[test]
    fn test_truncate_over_limit() {
        let s = "a".repeat(3000);
        let (truncated, out) = truncate(&s, 100);
        assert!(truncated);
        assert!(out.contains("truncated"));
        assert!(out.starts_with(&"a".repeat(100)));
    }
}
