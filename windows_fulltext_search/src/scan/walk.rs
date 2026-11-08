use std::path::{Path, PathBuf};

use crate::model::is_supported_ext;
use crate::textutil::{self, path_key};

use super::cloud::{self, is_link_reparse, FILE_ATTRIBUTE_REPARSE_POINT};

#[derive(Debug, Clone)]
pub struct FoundFile {
    pub path: PathBuf,
    pub path_key: String,
    pub path_display: String,
    pub filename: String,
    pub ext: String,
    pub size: u64,
    pub mtime: i64,
    pub skip_reason: Option<String>,
}

#[derive(Debug, Clone)]
pub struct WalkOutcome {
    pub root_accessible: bool,
    pub complete: bool,
    pub access_error: Option<String>,
    pub files: Vec<FoundFile>,
}

pub fn walk_root(root: &Path) -> WalkOutcome {
    let meta = match std::fs::metadata(root) {
        Ok(m) => m,
        Err(err) => {
            return WalkOutcome {
                root_accessible: false,
                complete: false,
                access_error: Some(format!("根目录暂时不可访问，已保留已有索引：{err}")),
                files: Vec::new(),
            };
        }
    };
    if !meta.is_dir() {
        return WalkOutcome {
            root_accessible: false,
            complete: false,
            access_error: Some("选择的路径不是文件夹".into()),
            files: Vec::new(),
        };
    }
    let mut files = Vec::new();
    let mut complete = true;
    walk_dir(root, root, 0, &mut files, &mut complete);
    WalkOutcome {
        root_accessible: true,
        complete,
        access_error: None,
        files,
    }
}

fn walk_dir(dir: &Path, root: &Path, depth: u32, files: &mut Vec<FoundFile>, complete: &mut bool) {
    if depth > 64 {
        *complete = false;
        return;
    }
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => {
            *complete = false;
            return;
        }
    };
    for entry in entries {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => {
                *complete = false;
                continue;
            }
        };
        let path = entry.path();
        let file_type = match entry.file_type() {
            Ok(t) => t,
            Err(_) => {
                *complete = false;
                continue;
            }
        };
        if file_type.is_symlink() {
            continue;
        }
        if let Some(tag) = reparse_tag(&path) {
            if is_link_reparse(tag) {
                continue;
            }
        }
        if file_type.is_dir() {
            if is_reparse_dir(&path) && reparse_tag(&path).map(is_link_reparse).unwrap_or(false) {
                continue;
            }
            walk_dir(&path, root, depth + 1, files, complete);
            continue;
        }
        if !file_type.is_file() {
            continue;
        }
        let Some(filename) = path.file_name().and_then(|s| s.to_str()).map(|s| s.to_string()) else {
            continue;
        };
        if filename.starts_with("~$") {
            continue;
        }
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if !is_supported_ext(&ext) {
            continue;
        }
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => {
                *complete = false;
                continue;
            }
        };
        let display = display_path(&path);
        let key = path_key(&display);
        let mtime = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        let skip_reason = cloud::probe_path(&path)
            .as_ref()
            .and_then(cloud::should_skip_content)
            .map(|s| s.to_string());
        let _ = root;
        files.push(FoundFile {
            path,
            path_key: key,
            path_display: display,
            filename: textutil::nfc(&filename),
            ext,
            size: meta.len(),
            mtime,
            skip_reason,
        });
    }
}

fn display_path(path: &Path) -> String {
    let text = path.to_string_lossy().replace('/', "\\");
    #[cfg(windows)]
    {
        text.strip_prefix(r"\\?\").unwrap_or(&text).to_string()
    }
    #[cfg(not(windows))]
    {
        path.to_string_lossy().to_string()
    }
}

fn is_reparse_dir(path: &Path) -> bool {
    cloud::probe_path(path)
        .map(|p| p.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0)
        .unwrap_or(false)
}

fn reparse_tag(path: &Path) -> Option<u32> {
    cloud::probe_path(path).and_then(|p| p.reparse_tag)
}
