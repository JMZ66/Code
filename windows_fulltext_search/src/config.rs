use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::model::{QueryMode, Scope, SortMode};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RootEntry {
    pub path: String,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub roots: Vec<RootEntry>,
    pub index_dir: Option<String>,
    pub threads: usize,
    pub max_file_mb: u64,
    pub extensions: Vec<String>,
    pub theme_dark: bool,
    pub close_to_tray: bool,
    pub history: Vec<String>,
    pub favorites: Vec<String>,
    pub rescan_secs: u64,
    pub case_sensitive: bool,
    pub mode: QueryMode,
    pub scope: Scope,
    pub sort: SortMode,
    pub page_size: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            roots: Vec::new(),
            index_dir: None,
            threads: 2,
            max_file_mb: 64,
            extensions: crate::model::supported_extensions()
                .iter()
                .map(|s| s.to_string())
                .collect(),
            theme_dark: false,
            close_to_tray: false,
            history: Vec::new(),
            favorites: Vec::new(),
            rescan_secs: 300,
            case_sensitive: false,
            mode: QueryMode::Substring,
            scope: Scope::Mixed,
            sort: SortMode::Relevance,
            page_size: 20,
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> Self {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".into());
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, text)?;
        std::fs::rename(tmp, path)
    }
}

pub fn default_data_dir() -> PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if dir.join("portable.marker").exists() {
                return dir.join("data");
            }
        }
    }
    directories::ProjectDirs::from("local", "LocalSearch", "LocalSearch")
        .map(|d| d.data_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("local-search-data"))
}

pub fn blocked_root(path: &Path) -> Option<&'static str> {
    let raw = path.to_string_lossy().replace('/', "\\");
    let lower = raw.trim_end_matches('\\').to_ascii_lowercase();
    let blocked = [
        r"c:\windows",
        r"c:\program files",
        r"c:\program files (x86)",
        "/",
        r"\windows",
    ];
    if lower == "c:" || lower == "d:" || lower == "e:" || lower == "/" || lower.is_empty() {
        return Some("为避免全盘扫描，请选择具体的资料文件夹，而不是磁盘根目录");
    }
    for item in blocked {
        if lower == item.trim_end_matches('\\') {
            return Some("系统目录不会被索引");
        }
    }
    #[cfg(unix)]
    {
        if path == Path::new("/")
            || path.starts_with("/proc")
            || path.starts_with("/sys")
            || path.starts_with("/dev")
        {
            return Some("系统目录不会被索引");
        }
    }
    None
}
