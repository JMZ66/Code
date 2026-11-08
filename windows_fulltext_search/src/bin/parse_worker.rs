//! Out-of-process extractor. One JSON request per line, one JSON response per line.
//! Paths are JSON strings, never concatenated into a shell command.

use std::io::{BufRead, Write};

use local_search::extract::{self, Limits};
use local_search::model::Extracted;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
struct Req {
    id: u64,
    path: String,
    max_file_bytes: u64,
    max_extract_chars: usize,
    max_zip_entries: usize,
    max_unzip_bytes: u64,
    max_ratio: u64,
}

#[derive(Serialize)]
struct Resp {
    id: u64,
    ok: bool,
    error: Option<String>,
    kind: Option<String>,
    extracted: Option<Extracted>,
}

fn main() {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let req: Req = match serde_json::from_str(&line) {
            Ok(req) => req,
            Err(err) => {
                let _ = writeln!(
                    stdout,
                    "{}",
                    serde_json::to_string(&Resp {
                        id: 0,
                        ok: false,
                        error: Some(err.to_string()),
                        kind: Some("bad_request".into()),
                        extracted: None,
                    })
                    .unwrap_or_default()
                );
                let _ = stdout.flush();
                continue;
            }
        };
        let limits = Limits {
            max_file_bytes: req.max_file_bytes,
            max_extract_chars: req.max_extract_chars,
            max_zip_entries: req.max_zip_entries,
            max_unzip_bytes: req.max_unzip_bytes,
            max_ratio: req.max_ratio,
        };
        let resp = match extract::parse_file(std::path::Path::new(&req.path), &limits) {
            Ok(doc) => Resp {
                id: req.id,
                ok: true,
                error: None,
                kind: None,
                extracted: Some(doc),
            },
            Err(err) => Resp {
                id: req.id,
                ok: false,
                error: Some(err.to_string()),
                kind: Some(kind_of(&err).into()),
                extracted: None,
            },
        };
        if writeln!(stdout, "{}", serde_json::to_string(&resp).unwrap_or_default()).is_err() {
            break;
        }
        if stdout.flush().is_err() {
            break;
        }
    }
}

fn kind_of(err: &extract::ExtractError) -> &'static str {
    match err {
        extract::ExtractError::TooLarge(_) => "too_large",
        extract::ExtractError::Encrypted(_) => "encrypted",
        extract::ExtractError::Corrupt(_) => "corrupt",
        extract::ExtractError::Unsupported(_) => "unsupported",
        extract::ExtractError::Permission(_) => "permission",
        extract::ExtractError::Busy(_) => "busy",
        extract::ExtractError::Io(_) => "io",
    }
}
