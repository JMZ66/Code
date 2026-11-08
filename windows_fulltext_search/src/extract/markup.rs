use std::path::Path;

use super::{decode_bytes, push_text, read_limited, ExtractError, Limits};
use crate::model::Extracted;

pub fn parse_html(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let bytes = read_limited(path, limits)?;
    let raw = decode_bytes(&bytes);
    let text = html_visible_text(&raw);
    let mut doc = Extracted::empty();
    push_text(&mut doc.segments, "html", "正文（已去除脚本和样式，不执行）", &text);
    doc.warnings
        .push("HTML 只抽取可见文本，不执行脚本，也不是浏览器渲染".into());
    Ok(doc)
}

fn html_visible_text(raw: &str) -> String {
    let chars: Vec<char> = raw.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '<' {
            if starts_with(&chars, i, "<!--") {
                i = find_seq(&chars, i + 4, "-->").unwrap_or(chars.len());
                continue;
            }
            let tag = read_tag(&chars, i);
            i = tag.end;
            let name = tag.name.to_ascii_lowercase();
            if name == "script" || name == "style" || name == "noscript" {
                let close = format!("</{name}");
                if let Some(pos) = find_seq_ci(&chars, i, &close) {
                    i = chars[pos..]
                        .iter()
                        .position(|c| *c == '>')
                        .map(|p| pos + p + 1)
                        .unwrap_or(chars.len());
                } else {
                    break;
                }
                continue;
            }
            if matches!(
                name.as_str(),
                "p" | "div" | "br" | "li" | "tr" | "h1" | "h2" | "h3" | "h4" | "section" | "table"
            ) {
                out.push('\n');
            } else {
                out.push(' ');
            }
            continue;
        }
        if chars[i] == '&' {
            if let Some(end) = chars[i + 1..].iter().position(|c| *c == ';') {
                let ent: String = chars[i + 1..i + 1 + end].iter().collect();
                if let Some(decoded) = decode_entity(&ent) {
                    out.push_str(&decoded);
                    i += end + 2;
                    continue;
                }
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    crate::textutil::nfc(&collapse_ws(&out))
}

struct Tag {
    name: String,
    end: usize,
}

fn read_tag(chars: &[char], start: usize) -> Tag {
    let mut i = start + 1;
    if chars.get(i) == Some(&'/') {
        i += 1;
    }
    let name_start = i;
    while i < chars.len() && (chars[i].is_ascii_alphanumeric()) {
        i += 1;
    }
    let name: String = chars[name_start..i].iter().collect();
    while i < chars.len() && chars[i] != '>' {
        i += 1;
    }
    if i < chars.len() {
        i += 1;
    }
    Tag { name, end: i }
}

fn starts_with(chars: &[char], i: usize, s: &str) -> bool {
    let t: Vec<char> = s.chars().collect();
    chars.get(i..i + t.len()) == Some(t.as_slice())
}

fn find_seq(chars: &[char], from: usize, seq: &str) -> Option<usize> {
    let t: Vec<char> = seq.chars().collect();
    if t.is_empty() {
        return Some(from);
    }
    chars[from..]
        .windows(t.len())
        .position(|w| w == t.as_slice())
        .map(|p| from + p + t.len())
}

fn find_seq_ci(chars: &[char], from: usize, seq: &str) -> Option<usize> {
    let t: Vec<char> = seq.chars().flat_map(|c| c.to_lowercase()).collect();
    if t.is_empty() || from >= chars.len() {
        return None;
    }
    let lower: Vec<char> = chars[from..].iter().copied().flat_map(|c| c.to_lowercase()).collect();
    // Lowercasing can expand, so search on a parallel map.
    let mut map = Vec::new();
    for (idx, c) in chars[from..].iter().enumerate() {
        for _ in c.to_lowercase() {
            map.push(from + idx);
        }
    }
    lower
        .windows(t.len())
        .position(|w| w == t.as_slice())
        .map(|p| map[p])
}

fn decode_entity(ent: &str) -> Option<String> {
    match ent {
        "lt" => Some("<".into()),
        "gt" => Some(">".into()),
        "amp" => Some("&".into()),
        "quot" => Some("\"".into()),
        "apos" => Some("'".into()),
        "nbsp" => Some(" ".into()),
        _ if ent.starts_with("#x") || ent.starts_with("#X") => {
            char::from_u32(u32::from_str_radix(&ent[2..], 16).ok()?).map(|c| c.to_string())
        }
        _ => ent
            .strip_prefix('#')
            .and_then(|n| n.parse::<u32>().ok())
            .and_then(char::from_u32)
            .map(|c| c.to_string()),
    }
}

fn collapse_ws(s: &str) -> String {
    let mut out = String::new();
    let mut blank = false;
    for line in s.lines() {
        let t = line.split_whitespace().collect::<Vec<_>>().join(" ");
        if t.is_empty() {
            blank = true;
            continue;
        }
        if !out.is_empty() {
            out.push(if blank { '\n' } else { ' ' });
        }
        blank = false;
        out.push_str(&t);
    }
    out
}
