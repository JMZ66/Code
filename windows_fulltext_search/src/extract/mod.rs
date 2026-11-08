//! Read-only text extraction. Office, PDF, ODF and RTF entry points are used
//! by the parser worker. The worker is what enforces the process boundary.

mod markup;
mod odf;
mod office;
mod pdf;
mod plain;
mod rtf;

use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

use crate::model::{is_supported_ext, Extracted};

#[derive(Debug, Clone)]
pub struct Limits {
    pub max_file_bytes: u64,
    pub max_extract_chars: usize,
    pub max_zip_entries: usize,
    pub max_unzip_bytes: u64,
    pub max_ratio: u64,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_file_bytes: 64 * 1024 * 1024,
            max_extract_chars: 1_000_000,
            max_zip_entries: 8_000,
            max_unzip_bytes: 128 * 1024 * 1024,
            max_ratio: 80,
        }
    }
}

#[derive(Debug)]
pub enum ExtractError {
    Io(String),
    TooLarge(String),
    Encrypted(String),
    Corrupt(String),
    Unsupported(String),
    Permission(String),
    Busy(String),
}

impl std::fmt::Display for ExtractError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(s)
            | Self::TooLarge(s)
            | Self::Encrypted(s)
            | Self::Corrupt(s)
            | Self::Unsupported(s)
            | Self::Permission(s)
            | Self::Busy(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for ExtractError {}

pub fn parse_file(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !is_supported_ext(&ext) {
        return Err(ExtractError::Unsupported(format!(
            "不支持的扩展名 .{ext}（不声称支持 WPS 专用格式）"
        )));
    }
    let meta = std::fs::metadata(path).map_err(map_io)?;
    if meta.len() > limits.max_file_bytes {
        return Err(ExtractError::TooLarge(format!(
            "文件 {} 字节，超过上限 {} 字节，未读取内容",
            meta.len(),
            limits.max_file_bytes
        )));
    }
    let mut extracted = match ext.as_str() {
        "txt" | "md" | "json" | "xml" => plain::parse_text(path, limits, &ext)?,
        "csv" => plain::parse_csv(path, limits)?,
        "html" | "htm" => markup::parse_html(path, limits)?,
        "rtf" => rtf::parse_rtf(path, limits)?,
        "pdf" => pdf::parse_pdf(path, limits)?,
        "odt" | "ods" | "odp" => odf::parse_odf(path, limits, &ext)?,
        "doc" | "docx" | "docm" | "ppt" | "pptx" => office::parse_word_or_ppt(path, limits)?,
        "xls" | "xlsx" | "xlsm" | "xlsb" => office::parse_sheet(path, limits)?,
        _ => {
            return Err(ExtractError::Unsupported(format!(
                "没有 .{ext} 的解析器"
            )))
        }
    };
    truncate_extracted(&mut extracted, limits.max_extract_chars);
    Ok(extracted)
}

fn truncate_extracted(doc: &mut Extracted, max_chars: usize) {
    let mut used = 0usize;
    let mut cut = false;
    for seg in &mut doc.segments {
        let count = seg.text.chars().count();
        if used >= max_chars {
            seg.text.clear();
            cut = true;
            continue;
        }
        if used + count > max_chars {
            let keep = max_chars - used;
            seg.text = seg.text.chars().take(keep).collect();
            cut = true;
            used = max_chars;
        } else {
            used += count;
        }
    }
    if cut {
        doc.warnings
            .push(format!("抽出的文本已截断到 {max_chars} 个字符"));
    }
}

pub(crate) fn map_io(err: std::io::Error) -> ExtractError {
    match err.kind() {
        std::io::ErrorKind::PermissionDenied => {
            ExtractError::Permission(format!("没有读取权限：{err}"))
        }
        std::io::ErrorKind::TimedOut => ExtractError::Busy(format!("读取超时：{err}")),
        _ => {
            let msg = err.to_string();
            let lower = msg.to_lowercase();
            if lower.contains("being used")
                || lower.contains("used by another")
                || lower.contains("sharing violation")
                || lower.contains("locked")
            {
                ExtractError::Busy(format!("文件被占用：{msg}"))
            } else {
                ExtractError::Io(msg)
            }
        }
    }
}

pub(crate) fn open_read(path: &Path) -> Result<std::fs::File, ExtractError> {
    OpenOptions::new()
        .read(true)
        .write(false)
        .open(long_path(path))
        .map_err(map_io)
}

pub(crate) fn long_path(path: &Path) -> std::path::PathBuf {
    #[cfg(windows)]
    {
        use std::path::PathBuf;
        let abs = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(path)
        };
        let raw = abs.to_string_lossy().replace('/', "\\");
        if raw.starts_with(r"\\?\") {
            return abs;
        }
        if let Some(rest) = raw.strip_prefix(r"\\") {
            PathBuf::from(format!(r"\\?\UNC\{rest}"))
        } else {
            PathBuf::from(format!(r"\\?\{raw}"))
        }
    }
    #[cfg(not(windows))]
    {
        path.to_path_buf()
    }
}

pub(crate) fn read_limited(path: &Path, limits: &Limits) -> Result<Vec<u8>, ExtractError> {
    let mut file = open_read(path)?;
    read_limited_file(&mut file, limits)
}

pub(crate) fn read_limited_file(
    file: &mut std::fs::File,
    limits: &Limits,
) -> Result<Vec<u8>, ExtractError> {
    let len = file.seek(SeekFrom::End(0)).map_err(map_io)?;
    file.seek(SeekFrom::Start(0)).map_err(map_io)?;
    if len > limits.max_file_bytes {
        return Err(ExtractError::TooLarge(format!(
            "文件 {len} 字节，超过上限"
        )));
    }
    let mut buf = Vec::new();
    file.take(limits.max_file_bytes + 1)
        .read_to_end(&mut buf)
        .map_err(map_io)?;
    if buf.len() as u64 > limits.max_file_bytes {
        return Err(ExtractError::TooLarge("读取超过大小上限".into()));
    }
    Ok(buf)
}

pub(crate) fn decode_bytes(bytes: &[u8]) -> String {
    if bytes.starts_with(&[0xEF, 0xBB, 0xBF]) {
        return String::from_utf8_lossy(&bytes[3..]).into_owned();
    }
    if bytes.starts_with(&[0xFF, 0xFE]) {
        let (s, _, _) = encoding_rs::UTF_16LE.decode(&bytes[2..]);
        return s.into_owned();
    }
    if bytes.starts_with(&[0xFE, 0xFF]) {
        let (s, _, _) = encoding_rs::UTF_16BE.decode(&bytes[2..]);
        return s.into_owned();
    }
    if std::str::from_utf8(bytes).is_ok() {
        return String::from_utf8_lossy(bytes).into_owned();
    }
    let mut det = chardetng::EncodingDetector::new();
    det.feed(bytes, true);
    let enc = det.guess(Some(b"cn"), true);
    let (s, _, _) = enc.decode(bytes);
    s.into_owned()
}

pub(crate) fn classify_office_error(err: &str) -> ExtractError {
    let lower = err.to_lowercase();
    if lower.contains("password")
        || lower.contains("encrypt")
        || lower.contains("encrypted")
        || err.contains("密码")
    {
        ExtractError::Encrypted(format!("文件可能已加密或受密码保护，已跳过：{err}"))
    } else {
        ExtractError::Corrupt(format!("无法解析文档：{err}"))
    }
}

pub(crate) fn push_text(
    segments: &mut Vec<crate::model::Segment>,
    kind: &str,
    label: &str,
    text: &str,
) {
    let text = text.trim();
    if text.is_empty() {
        return;
    }
    segments.push(crate::model::Segment {
        kind: kind.to_string(),
        label: label.to_string(),
        text: crate::textutil::nfc(text),
        page: None,
        sheet: None,
        cell: None,
    });
}
