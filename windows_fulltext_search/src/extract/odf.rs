use std::io::Read;
use std::path::Path;

use quick_xml::events::Event;
use quick_xml::Reader;

use super::{open_read, ExtractError, Limits};
use crate::model::{Extracted, Segment};
use crate::textutil::nfc;

pub fn parse_odf(path: &Path, limits: &Limits, ext: &str) -> Result<Extracted, ExtractError> {
    let file = open_read(path)?;
    let mut archive = zip::ZipArchive::new(file)
        .map_err(|err| ExtractError::Corrupt(format!("ODF 不是可读的 ZIP 包：{err}")))?;
    if archive.len() > limits.max_zip_entries {
        return Err(ExtractError::TooLarge(format!(
            "ZIP 条目 {} 超过上限 {}",
            archive.len(),
            limits.max_zip_entries
        )));
    }
    let mut doc = Extracted::empty();
    let content = read_part(&mut archive, "content.xml", limits)?;
    parse_content(&content, ext, &mut doc);
    if let Ok(styles) = read_part(&mut archive, "styles.xml", limits) {
        parse_styles(&styles, &mut doc);
    }
    Ok(doc)
}

fn read_part<R: std::io::Read + std::io::Seek>(
    archive: &mut zip::ZipArchive<R>,
    name: &str,
    limits: &Limits,
) -> Result<String, ExtractError> {
    let mut entry = archive
        .by_name(name)
        .map_err(|err| ExtractError::Corrupt(format!("缺少 {name}：{err}")))?;
    if entry.size() > limits.max_unzip_bytes {
        return Err(ExtractError::TooLarge(format!(
            "{name} 声明的解压大小超过上限"
        )));
    }
    let compressed = entry.compressed_size().max(1);
    if entry.size() / compressed > limits.max_ratio && entry.size() > 1_000_000 {
        return Err(ExtractError::TooLarge(format!(
            "{name} 压缩比异常，已拒绝解压"
        )));
    }
    let mut buf = Vec::new();
    entry
        .take(limits.max_unzip_bytes + 1)
        .read_to_end(&mut buf)
        .map_err(|err| ExtractError::Corrupt(format!("读取 {name} 失败：{err}")))?;
    if buf.len() as u64 > limits.max_unzip_bytes {
        return Err(ExtractError::TooLarge(format!("{name} 解压结果超过上限")));
    }
    Ok(String::from_utf8_lossy(&buf).into_owned())
}

struct CellBuf {
    sheet: String,
    row: u32,
    col: u32,
    formula: Option<String>,
    cached: Option<String>,
    text: String,
}

fn parse_content(xml: &str, ext: &str, doc: &mut Extracted) {
    let mut reader = Reader::from_str(xml);
    let mut buf = Vec::new();
    let mut sheet = String::from("表格");
    let mut in_table = false;
    let mut row = 0u32;
    let mut col = 0u32;
    let mut cell: Option<CellBuf> = None;
    let mut slide_no = 0u32;
    let mut slide_text: Option<String> = None;
    let mut body = String::new();

    loop {
        let event = match reader.read_event_into(&mut buf) {
            Ok(ev) => ev,
            Err(err) => {
                doc.warnings.push(format!("ODF XML 中断：{err}"));
                break;
            }
        };
        let is_empty = matches!(event, Event::Empty(_));
        match event {
            Event::Start(e) | Event::Empty(e) => {
                let name = local(e.name().as_ref());
                match name.as_str() {
                    "table" => {
                        in_table = true;
                        sheet = attr(&e, "name").unwrap_or_else(|| "表格".into());
                        row = 0;
                    }
                    "table-row" => {
                        row += 1;
                        col = 0;
                    }
                    "table-cell" | "covered-table-cell" => {
                        col += 1;
                        let repeat = attr(&e, "number-columns-repeated")
                            .and_then(|s| s.parse::<u32>().ok())
                            .unwrap_or(1)
                            .min(100_000);
                        cell = Some(CellBuf {
                            sheet: sheet.clone(),
                            row,
                            col,
                            formula: attr(&e, "formula"),
                            cached: attr(&e, "value").or_else(|| attr(&e, "date-value")),
                            text: String::new(),
                        });
                        if repeat > 1 {
                            col = col.saturating_add(repeat - 1);
                        }
                        if is_empty {
                            if let Some(done) = cell.take() {
                                emit_cell(doc, &done);
                            }
                        }
                    }
                    "page" if ext == "odp" => {
                        slide_no += 1;
                        slide_text = Some(String::new());
                        if is_empty {
                            slide_text = None;
                        }
                    }
                    _ => {}
                }
            }
            Event::Text(t) => {
                let piece = t.unescape().unwrap_or_default();
                if let Some(cell) = cell.as_mut() {
                    cell.text.push_str(&piece);
                } else if let Some(slide) = slide_text.as_mut() {
                    if !slide.is_empty() && !piece.trim().is_empty() {
                        slide.push('\n');
                    }
                    slide.push_str(piece.trim());
                } else if ext == "odt" && !in_table {
                    if !body.is_empty() && !piece.trim().is_empty() {
                        body.push('\n');
                    }
                    body.push_str(piece.trim());
                }
            }
            Event::End(e) => {
                let name = local(e.name().as_ref());
                match name.as_str() {
                    "table-cell" | "covered-table-cell" => {
                        if let Some(done) = cell.take() {
                            emit_cell(doc, &done);
                        }
                    }
                    "page" if ext == "odp" => {
                        if let Some(text) = slide_text.take() {
                            let text = nfc(text.trim());
                            if !text.is_empty() {
                                doc.segments.push(Segment {
                                    kind: "slide".into(),
                                    label: format!("幻灯片{slide_no}"),
                                    text,
                                    page: Some(slide_no),
                                    sheet: None,
                                    cell: None,
                                });
                            }
                        }
                    }
                    "table" => in_table = false,
                    _ => {}
                }
            }
            Event::Eof => break,
            _ => {}
        }
        buf.clear();
        if doc.segments.len() > 200_000 {
            doc.warnings
                .push("ODF 单元格过多，后续内容已停止".into());
            break;
        }
    }
    let body = nfc(body.trim());
    if !body.is_empty() {
        doc.segments.push(Segment {
            kind: "body".into(),
            label: "正文".into(),
            text: body,
            page: None,
            sheet: None,
            cell: None,
        });
    }
}

fn emit_cell(doc: &mut Extracted, cell: &CellBuf) {
    let displayed = cell.text.trim();
    let cached = cell.cached.as_deref().unwrap_or("").trim();
    let value = if !displayed.is_empty() {
        displayed.to_string()
    } else {
        cached.to_string()
    };
    if value.is_empty() {
        if cell.formula.is_some() {
            doc.warnings.push(format!(
                "{} 第{}行第{}列有公式但没有缓存结果，未计算公式",
                cell.sheet, cell.row, cell.col
            ));
        }
        return;
    }
    let letters = col_letters(cell.col.saturating_sub(1));
    let addr = format!("{letters}{}", cell.row);
    doc.segments.push(Segment {
        kind: "sheet_cell".into(),
        label: format!("{}!{addr}", cell.sheet),
        text: nfc(&value),
        page: None,
        sheet: Some(cell.sheet.clone()),
        cell: Some(addr),
    });
}

fn parse_styles(xml: &str, doc: &mut Extracted) {
    let mut reader = Reader::from_str(xml);
    let mut buf = Vec::new();
    let mut capture: Option<&'static str> = None;
    let mut text = String::new();
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => {
                let name = local(e.name().as_ref());
                if name == "header" || name == "footer" {
                    capture = Some(if name == "header" { "页眉" } else { "页脚" });
                    text.clear();
                }
            }
            Ok(Event::Text(t)) => {
                if capture.is_some() {
                    text.push_str(&t.unescape().unwrap_or_default());
                }
            }
            Ok(Event::End(e)) => {
                let name = local(e.name().as_ref());
                if (name == "header" || name == "footer") && capture.take().is_some() {
                    let label = if name == "header" { "页眉" } else { "页脚" };
                    let body = nfc(text.trim());
                    if !body.is_empty() {
                        doc.segments.push(Segment {
                            kind: if label == "页眉" { "header" } else { "footer" }.into(),
                            label: label.into(),
                            text: body,
                            page: None,
                            sheet: None,
                            cell: None,
                        });
                    }
                    text.clear();
                }
            }
            Ok(Event::Eof) => break,
            Err(err) => {
                doc.warnings.push(format!("ODF 样式读取中断：{err}"));
                break;
            }
            _ => {}
        }
        buf.clear();
    }
}

fn local(qname: &[u8]) -> String {
    let s = std::str::from_utf8(qname).unwrap_or("");
    s.rsplit(':').next().unwrap_or(s).to_string()
}

fn attr(e: &quick_xml::events::BytesStart<'_>, key: &str) -> Option<String> {
    for a in e.attributes().flatten() {
        if local(a.key.as_ref()) == key {
            return a.unescape_value().ok().map(|v| v.into_owned());
        }
    }
    None
}

fn col_letters(mut col: u32) -> String {
    let mut out = Vec::new();
    let mut n = col + 1;
    while n > 0 {
        n -= 1;
        out.push(b'A' + (n % 26) as u8);
        n /= 26;
    }
    out.reverse();
    String::from_utf8(out).unwrap_or_else(|_| format!("C{col}"))
}
