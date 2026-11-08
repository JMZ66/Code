//! Parser subprocess. Office, PDF, ODF and RTF run here so a panic or a zip
//! bomb dies with the child. This is not a full sandbox: there is no
//! AppContainer or seccomp policy. On Windows the child is placed in a Job
//! Object that caps memory and kills the process when the job handle closes.
//! On Unix the child is in its own session so the parent can signal the group.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::extract::Limits;
use crate::model::Extracted;

#[derive(Debug, Serialize, Deserialize)]
struct Req {
    id: u64,
    path: String,
    max_file_bytes: u64,
    max_extract_chars: usize,
    max_zip_entries: usize,
    max_unzip_bytes: u64,
    max_ratio: u64,
}

#[derive(Debug, Serialize, Deserialize)]
struct Resp {
    id: u64,
    ok: bool,
    error: Option<String>,
    kind: Option<String>,
    extracted: Option<Extracted>,
}

pub struct WorkerPool {
    tx: mpsc::Sender<Job>,
}

struct Job {
    path: PathBuf,
    limits: Limits,
    timeout: Duration,
    reply: mpsc::Sender<Result<Extracted, String>>,
}

impl WorkerPool {
    pub fn start(worker_bin: PathBuf, slots: usize) -> Self {
        let slots = slots.max(1);
        let mut txs = Vec::new();
        for _ in 0..slots {
            let (tx, rx) = mpsc::sync_channel::<Job>(1);
            txs.push(tx);
            let bin = worker_bin.clone();
            std::thread::spawn(move || worker_loop(bin, rx));
        }
        let (tx, incoming) = mpsc::channel::<Job>();
        std::thread::spawn(move || {
            let mut n = 0usize;
            while let Ok(job) = incoming.recv() {
                if txs.is_empty() {
                    break;
                }
                let slot = n % txs.len();
                n = n.wrapping_add(1);
                if txs[slot].send(job).is_err() {
                    break;
                }
            }
        });
        Self { tx }
    }

    pub fn parse(&self, path: &Path, limits: &Limits, timeout: Duration) -> Result<Extracted, String> {
        let (reply_tx, reply_rx) = mpsc::channel();
        self.tx
            .send(Job {
                path: path.to_path_buf(),
                limits: limits.clone(),
                timeout,
                reply: reply_tx,
            })
            .map_err(|_| "解析进程队列已关闭".to_string())?;
        reply_rx
            .recv_timeout(timeout + Duration::from_secs(5))
            .map_err(|_| "等待解析进程超时".to_string())?
    }
}

fn worker_loop(bin: PathBuf, rx: mpsc::Receiver<Job>) {
    let mut child = match spawn_worker(&bin) {
        Ok(c) => c,
        Err(err) => {
            while let Ok(job) = rx.recv() {
                let _ = job.reply.send(Err(err.clone()));
            }
            return;
        }
    };
    while let Ok(job) = rx.recv() {
        let req = Req {
            id: 1,
            path: job.path.to_string_lossy().to_string(),
            max_file_bytes: job.limits.max_file_bytes,
            max_extract_chars: job.limits.max_extract_chars,
            max_zip_entries: job.limits.max_zip_entries,
            max_unzip_bytes: job.limits.max_unzip_bytes,
            max_ratio: job.limits.max_ratio,
        };
        let payload = match serde_json::to_string(&req) {
            Ok(s) => s,
            Err(err) => {
                let _ = job.reply.send(Err(err.to_string()));
                continue;
            }
        };
        if child.stdin.as_mut().and_then(|stdin| writeln!(stdin, "{payload}").ok()).is_none()
            || child.stdin.as_mut().and_then(|stdin| stdin.flush().ok()).is_none()
        {
            let _ = job.reply.send(Err("解析进程已退出".into()));
            child = match spawn_worker(&bin) {
                Ok(c) => c,
                Err(err) => {
                    let _ = job.reply.send(Err(err));
                    break;
                }
            };
            continue;
        }
        let line = child.lines.recv_timeout(job.timeout);
        match line {
            Ok(Ok(line)) => match serde_json::from_str::<Resp>(&line) {
                Ok(resp) if resp.ok => {
                    let _ = job.reply.send(Ok(resp.extracted.unwrap_or_else(Extracted::empty)));
                }
                Ok(resp) => {
                    let _ = job.reply.send(Err(resp.error.unwrap_or_else(|| "解析失败".into())));
                }
                Err(err) => {
                    let _ = job.reply.send(Err(format!("解析进程返回无法识别：{err}")));
                }
            },
            _ => {
                kill_child(&mut child.child);
                let _ = job.reply.send(Err("解析超时或进程崩溃，已终止该解析进程".into()));
                child = match spawn_worker(&bin) {
                    Ok(c) => c,
                    Err(_) => break,
                };
            }
        }
    }
}

struct LiveChild {
    child: Child,
    stdin: Option<std::process::ChildStdin>,
    lines: Receiver<std::io::Result<String>>,
    #[cfg(windows)]
    job: Option<windows::Win32::Foundation::HANDLE>,
}

fn spawn_worker(bin: &Path) -> Result<LiveChild, String> {
    if !bin.exists() {
        return Err(format!("找不到解析进程 {}", bin.display()));
    }
    let mut cmd = Command::new(bin);
    cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    #[cfg(unix)]
    unsafe {
        use std::os::unix::process::CommandExt;
        cmd.pre_exec(|| {
            libc::setsid();
            let mem = libc::rlimit {
                rlim_cur: 2 * 1024 * 1024 * 1024,
                rlim_max: 2 * 1024 * 1024 * 1024,
            };
            libc::setrlimit(libc::RLIMIT_AS, &mem);
            Ok(())
        });
    }
    let mut child = cmd.spawn().map_err(|err| format!("启动解析进程失败：{err}"))?;
    #[cfg(windows)]
    let job = assign_job(child.id());
    let stdout = child.stdout.take().ok_or("解析进程没有标准输出")?;
    let stdin = child.stdin.take();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if tx.send(line).is_err() {
                break;
            }
        }
    });
    Ok(LiveChild {
        child,
        stdin,
        lines: rx,
        #[cfg(windows)]
        job,
    })
}

fn kill_child(child: &mut Child) {
    let _ = child.kill();
    #[cfg(unix)]
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    let _ = child.wait();
}

#[cfg(windows)]
fn assign_job(pid: u32) -> Option<windows::Win32::Foundation::HANDLE> {
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_LIMIT_PROCESS_MEMORY,
    };
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};
    unsafe {
        let job = CreateJobObjectW(None, None).ok()?;
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags =
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY;
        info.ProcessMemoryLimit = 2 * 1024 * 1024 * 1024;
        let _ = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, false, pid).ok()?;
        if AssignProcessToJobObject(job, process).is_err() {
            return None;
        }
        let _ = process;
        Some(job)
    }
}

#[cfg(windows)]
impl Drop for LiveChild {
    fn drop(&mut self) {
        kill_child(&mut self.child);
        if let Some(job) = self.job.take() {
            unsafe {
                let _ = windows::Win32::Foundation::CloseHandle(job);
            }
        }
    }
}

#[cfg(not(windows))]
impl Drop for LiveChild {
    fn drop(&mut self) {
        kill_child(&mut self.child);
    }
}
