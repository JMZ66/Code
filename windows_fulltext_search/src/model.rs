//! Shared document and search types. Offsets are Unicode scalar indexes into
//! the NFC text that was stored, which is also the text the preview shows.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Segment {
    pub kind: String,
    pub label: String,
    pub text: String,
    #[serde(default)]
    pub page: Option<u32>,
    #[serde(default)]
    pub sheet: Option<String>,
    #[serde(default)]
    pub cell: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Extracted {
    pub segments: Vec<Segment>,
    pub warnings: Vec<String>,
    /// True when a PDF (or similar) had no extractable text. Not OCR.
    pub no_text: bool,
    pub has_macros: bool,
}

impl Extracted {
    pub fn empty() -> Self {
        Self {
            segments: Vec::new(),
            warnings: Vec::new(),
            no_text: false,
            has_macros: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum QueryMode {
    Substring,
    Phrase,
    Word,
    Boolean,
    Regex,
}

impl QueryMode {
    pub fn label(self) -> &'static str {
        match self {
            Self::Substring => "子串",
            Self::Phrase => "短语",
            Self::Word => "单词",
            Self::Boolean => "布尔",
            Self::Regex => "正则",
        }
    }

    pub fn all() -> &'static [QueryMode] {
        &[
            Self::Substring,
            Self::Phrase,
            Self::Word,
            Self::Boolean,
            Self::Regex,
        ]
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Scope {
    Content,
    Filename,
    Mixed,
}

impl Scope {
    pub fn label(self) -> &'static str {
        match self {
            Self::Content => "正文",
            Self::Filename => "文件名",
            Self::Mixed => "混合",
        }
    }

    pub fn all() -> &'static [Scope] {
        &[Self::Content, Self::Filename, Self::Mixed]
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SortMode {
    Relevance,
    Mtime,
    Filename,
}

impl SortMode {
    pub fn label(self) -> &'static str {
        match self {
            Self::Relevance => "相关度",
            Self::Mtime => "修改时间",
            Self::Filename => "文件名",
        }
    }

    pub fn all() -> &'static [SortMode] {
        &[Self::Relevance, Self::Mtime, Self::Filename]
    }
}

#[derive(Debug, Clone)]
pub struct SearchRequest {
    pub query: String,
    pub mode: QueryMode,
    pub scope: Scope,
    pub case_sensitive: bool,
    pub sort: SortMode,
    pub page: usize,
    pub page_size: usize,
    pub exts: Vec<String>,
    pub path_contains: String,
    pub min_size: Option<u64>,
    pub max_size: Option<u64>,
    pub min_mtime: Option<i64>,
    pub max_mtime: Option<i64>,
    /// Wall-clock budget. `None` means run until the candidate set is finished.
    pub deadline_ms: Option<u128>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Location {
    pub label: String,
    pub kind: String,
    pub start: usize,
    pub end: usize,
    pub page: Option<u32>,
    pub sheet: Option<String>,
    pub cell: Option<String>,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hit {
    pub path_key: String,
    pub path: String,
    pub filename: String,
    pub ext: String,
    pub size: u64,
    pub mtime: i64,
    pub score: i64,
    pub snippet: String,
    pub snippet_spans: Vec<(usize, usize)>,
    pub locations: Vec<Location>,
    pub match_count: u32,
    pub in_filename: bool,
    pub in_content: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResponse {
    pub hits: Vec<Hit>,
    pub total: u64,
    pub scanned: u64,
    pub candidates: u64,
    pub incomplete: bool,
    pub cancelled: bool,
    pub unaccelerated_regex: bool,
    pub elapsed_ms: u128,
    pub warning: Option<String>,
    pub error: Option<String>,
}

impl SearchResponse {
    pub fn failed(message: impl Into<String>) -> Self {
        Self {
            hits: Vec::new(),
            total: 0,
            scanned: 0,
            candidates: 0,
            incomplete: false,
            cancelled: false,
            unaccelerated_regex: false,
            elapsed_ms: 0,
            warning: None,
            error: Some(message.into()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredDoc {
    pub path_key: String,
    pub path: String,
    pub filename: String,
    pub ext: String,
    pub root: String,
    pub hash: String,
    pub size: u64,
    pub mtime: i64,
    pub generation: u64,
    pub content: String,
    pub segments: Vec<Segment>,
    pub warnings: Vec<String>,
    pub no_text: bool,
}

/// Char range of one non-empty segment inside the joined content string.
#[derive(Debug, Clone, Copy)]
pub struct SegRange {
    pub index: usize,
    pub start: usize,
    pub end: usize,
}

pub fn join_segments(segments: &[Segment]) -> (String, Vec<SegRange>) {
    let mut content = String::new();
    let mut ranges = Vec::new();
    for (index, seg) in segments.iter().enumerate() {
        if seg.text.is_empty() {
            continue;
        }
        if !content.is_empty() {
            content.push('\n');
        }
        let start = content.chars().count();
        content.push_str(&seg.text);
        let end = content.chars().count();
        ranges.push(SegRange { index, start, end });
    }
    (content, ranges)
}

pub fn supported_extensions() -> &'static [&'static str] {
    &[
        "doc", "docx", "docm", "xls", "xlsx", "xlsm", "xlsb", "ppt", "pptx", "pdf", "txt", "md",
        "csv", "json", "xml", "html", "htm", "rtf", "odt", "ods", "odp",
    ]
}

pub fn is_supported_ext(ext: &str) -> bool {
    supported_extensions()
        .iter()
        .any(|e| e.eq_ignore_ascii_case(ext))
}

/// Risky parsers run out of process. Plain text stays in-process.
pub fn needs_worker(ext: &str) -> bool {
    matches!(
        ext.to_ascii_lowercase().as_str(),
        "doc" | "docx"
            | "docm"
            | "xls"
            | "xlsx"
            | "xlsm"
            | "xlsb"
            | "ppt"
            | "pptx"
            | "pdf"
            | "odt"
            | "ods"
            | "odp"
            | "rtf"
    )
}
