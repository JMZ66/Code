use std::path::Path;

use super::{push_text, read_limited, ExtractError, Limits};
use crate::model::Extracted;

pub fn parse_rtf(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let bytes = read_limited(path, limits)?;
    let text = rtf_to_text(&bytes, limits.max_extract_chars);
    let mut doc = Extracted::empty();
    push_text(&mut doc.segments, "rtf", "正文", &text);
    Ok(doc)
}

fn rtf_to_text(bytes: &[u8], max_chars: usize) -> String {
    let mut out = String::new();
    let mut i = 0usize;
    let mut depth = 0i32;
    let mut skip_until: Option<i32> = None;
    let mut uc = 1usize;
    let mut codepage = encoding_rs::UTF_8;
    let mut byte_run: Vec<u8> = Vec::new();

    let flush_bytes = |byte_run: &mut Vec<u8>, out: &mut String, codepage: &'static encoding_rs::Encoding| {
        if byte_run.is_empty() {
            return;
        }
        let (s, _, _) = codepage.decode(byte_run);
        out.push_str(&s);
        byte_run.clear();
    };

    while i < bytes.len() && out.chars().count() < max_chars {
        let b = bytes[i];
        if b == b'{' {
            flush_bytes(&mut byte_run, &mut out, codepage);
            depth += 1;
            if skip_until.is_none() && is_destination(&bytes[i..]) {
                skip_until = Some(depth);
            }
            i += 1;
            continue;
        }
        if b == b'}' {
            flush_bytes(&mut byte_run, &mut out, codepage);
            if let Some(stop) = skip_until {
                if depth <= stop {
                    skip_until = None;
                }
            }
            depth -= 1;
            i += 1;
            continue;
        }
        if skip_until.is_some() {
            i += 1;
            continue;
        }
        if b == b'\\' {
            flush_bytes(&mut byte_run, &mut out, codepage);
            i += 1;
            if i >= bytes.len() {
                break;
            }
            let n = bytes[i];
            if n == b'\\' || n == b'{' || n == b'}' {
                out.push(n as char);
                i += 1;
                continue;
            }
            if n == b'\'' && i + 2 < bytes.len() {
                let hex = &bytes[i + 1..i + 3];
                if let Ok(s) = std::str::from_utf8(hex) {
                    if let Ok(v) = u8::from_str_radix(s, 16) {
                        byte_run.push(v);
                        i += 3;
                        continue;
                    }
                }
            }
            if n == b'u' && i + 1 < bytes.len() && (bytes[i + 1].is_ascii_digit() || bytes[i + 1] == b'-') {
                i += 1;
                let start = i;
                if bytes[i] == b'-' {
                    i += 1;
                }
                while i < bytes.len() && bytes[i].is_ascii_digit() {
                    i += 1;
                }
                if let Ok(num) = std::str::from_utf8(&bytes[start..i]).unwrap_or("").parse::<i32>() {
                    let cp = if num < 0 { num + 65536 } else { num } as u32;
                    if let Some(ch) = char::from_u32(cp) {
                        out.push(ch);
                    }
                }
                if i < bytes.len() && bytes[i] == b' ' {
                    i += 1;
                }
                let mut skipped = 0;
                while skipped < uc && i < bytes.len() {
                    // Fallback is one byte, or a quoted hex / escaped char.
                    if bytes[i] == b'\\' && i + 1 < bytes.len() && bytes[i + 1] == b'\'' && i + 3 < bytes.len() {
                        i += 4;
                    } else {
                        i += 1;
                    }
                    skipped += 1;
                }
                continue;
            }
            if n.is_ascii_alphabetic() {
                let start = i;
                i += 1;
                while i < bytes.len() && bytes[i].is_ascii_alphabetic() {
                    i += 1;
                }
                let word = std::str::from_utf8(&bytes[start..i]).unwrap_or("");
                let mut arg = String::new();
                if i < bytes.len() && (bytes[i] == b'-' || bytes[i].is_ascii_digit()) {
                    if bytes[i] == b'-' {
                        arg.push('-');
                        i += 1;
                    }
                    while i < bytes.len() && bytes[i].is_ascii_digit() {
                        arg.push(bytes[i] as char);
                        i += 1;
                    }
                }
                if i < bytes.len() && bytes[i] == b' ' {
                    i += 1;
                }
                match word {
                    "par" | "line" => out.push('\n'),
                    "tab" => out.push('\t'),
                    "uc" => {
                        if let Ok(n) = arg.parse::<usize>() {
                            uc = n;
                        }
                    }
                    "ansicpg" => {
                        codepage = match arg.as_str() {
                            "936" => encoding_rs::GBK,
                            "950" => encoding_rs::BIG5,
                            "932" => encoding_rs::SHIFT_JIS,
                            "949" => encoding_rs::EUC_KR,
                            "65001" => encoding_rs::UTF_8,
                            "1252" => encoding_rs::WINDOWS_1252,
                            _ => encoding_rs::GBK,
                        };
                    }
                    _ => {}
                }
                continue;
            }
            i += 1;
            continue;
        }
        if b == b'\r' || b == b'\n' {
            i += 1;
            continue;
        }
        byte_run.push(b);
        i += 1;
    }
    flush_bytes(&mut byte_run, &mut out, codepage);
    crate::textutil::nfc(out.trim())
}

fn is_destination(bytes: &[u8]) -> bool {
    // {\fonttbl {\* ... and a few binary destinations.
    let rest = if bytes.starts_with(b"{\\") {
        &bytes[2..]
    } else if bytes.starts_with(b"{\\*\\") {
        return true;
    } else {
        return false;
    };
    const SKIP: &[&[u8]] = &[
        b"fonttbl",
        b"colortbl",
        b"stylesheet",
        b"info",
        b"pict",
        b"object",
        b"datastore",
        b"themedata",
        b"colorschememapping",
        b"latentstyles",
        b"generator",
        b"xmlnstbl",
        b"rsidtbl",
        b"operator",
    ];
    SKIP.iter().any(|name| rest.starts_with(name))
}
