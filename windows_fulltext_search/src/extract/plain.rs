use std::path::Path;

use super::{decode_bytes, push_text, read_limited, ExtractError, Limits};
use crate::model::Extracted;
use crate::textutil::nfc;

pub fn parse_text(path: &Path, limits: &Limits, ext: &str) -> Result<Extracted, ExtractError> {
    let bytes = read_limited(path, limits)?;
    let text = nfc(&decode_bytes(&bytes));
    let mut doc = Extracted::empty();
    let kind = if ext == "xml" { "xml" } else { "text" };
    let label = if ext == "xml" { "XML 文本" } else { "正文" };
    if ext == "xml" {
        doc.segments.push(crate::model::Segment {
            kind: kind.into(),
            label: label.into(),
            text: xml_text(&text),
            page: None,
            sheet: None,
            cell: None,
        });
    } else {
        push_text(&mut doc.segments, kind, label, &text);
    }
    Ok(doc)
}

fn xml_text(raw: &str) -> String {
    // Linear scan. Entities are decoded as data. External entities are not loaded.
    let mut out = String::new();
    let mut in_tag = false;
    let chars: Vec<char> = raw.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if !in_tag && chars[i] == '<' {
            if chars.get(i..i + 4) == Some(&['<', '!', '-', '-']) {
                i += 4;
                while i + 2 < chars.len() && !(chars[i] == '-' && chars[i + 1] == '-' && chars[i + 2] == '>') {
                    i += 1;
                }
                i = (i + 3).min(chars.len());
                continue;
            }
            in_tag = true;
            out.push('\n');
            i += 1;
            continue;
        }
        if in_tag {
            if chars[i] == '>' {
                in_tag = false;
            }
            i += 1;
            continue;
        }
        if chars[i] == '&' {
            if let Some(end) = chars[i + 1..].iter().position(|c| *c == ';') {
                let ent: String = chars[i + 1..i + 1 + end].iter().collect();
                if let Some(ch) = decode_basic_entity(&ent) {
                    out.push(ch);
                    i += end + 2;
                    continue;
                }
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    nfc(out.trim())
}

fn decode_basic_entity(ent: &str) -> Option<char> {
    match ent {
        "lt" => Some('<'),
        "gt" => Some('>'),
        "amp" => Some('&'),
        "quot" => Some('"'),
        "apos" => Some('\''),
        _ if ent.starts_with("#x") || ent.starts_with("#X") => {
            u32::from_str_radix(&ent[2..], 16).ok().and_then(char::from_u32)
        }
        _ => ent
            .strip_prefix('#')
            .and_then(|rest| rest.parse::<u32>().ok())
            .and_then(char::from_u32),
    }
}

pub fn parse_csv(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let bytes = read_limited(path, limits)?;
    let text = decode_bytes(&bytes);
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .has_headers(false)
        .from_reader(text.as_bytes());
    let mut doc = Extracted::empty();
    for (row_i, rec) in reader.records().enumerate() {
        let rec = match rec {
            Ok(r) => r,
            Err(err) => {
                doc.warnings.push(format!("CSV 第 {} 行无法读取：{err}", row_i + 1));
                continue;
            }
        };
        for (col_i, cell) in rec.iter().enumerate() {
            let cell = cell.trim();
            if cell.is_empty() {
                continue;
            }
            doc.segments.push(crate::model::Segment {
                kind: "csv".into(),
                label: format!("第{}行第{}列", row_i + 1, col_i + 1),
                text: nfc(cell),
                page: None,
                sheet: None,
                cell: Some(format!("R{}C{}", row_i + 1, col_i + 1)),
            });
        }
    }
    Ok(doc)
}
