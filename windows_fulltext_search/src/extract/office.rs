use std::collections::HashSet;
use std::path::Path;

use office_oxide::ir::{inline_to_text, Element, HeaderFooter, Section};
use office_oxide::xlsx::CellValue;
use office_oxide::{Document, DocumentFormat};

use super::{classify_office_error, long_path, ExtractError, Limits};
use crate::model::{Extracted, Segment};
use crate::textutil::nfc;

static OFFICE_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

pub fn parse_word_or_ppt(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let _guard = OFFICE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    apply_limits(limits);
    let ext = ext_of(path);
    if ext == "pptx" {
        return parse_pptx(path);
    }
    let doc = Document::open(long_path(path)).map_err(|err| classify_office_error(&err.to_string()))?;
    let ir = doc.to_ir();
    let mut extracted = Extracted::empty();
    if ir.metadata.has_macros {
        extracted.has_macros = true;
        extracted
            .warnings
            .push("文件含宏，已忽略，未执行".into());
    }
    for line in &ir.metadata.warnings {
        extracted.warnings.push(line.clone());
    }
    if ext == "ppt" {
        for (i, section) in ir.sections.iter().enumerate() {
            let mut text = String::new();
            append_plain(&section.elements, &mut text);
            let text = nfc(text.trim());
            if !text.is_empty() {
                extracted.segments.push(Segment {
                    kind: "slide".into(),
                    label: format!("幻灯片{}", i + 1),
                    text,
                    page: Some((i + 1) as u32),
                    sheet: None,
                    cell: None,
                });
            }
            if let Some(notes) = &section.speaker_notes {
                let mut note = String::new();
                append_plain(notes, &mut note);
                let note = nfc(note.trim());
                if !note.is_empty() {
                    extracted.segments.push(Segment {
                        kind: "notes".into(),
                        label: format!("幻灯片{} 备注", i + 1),
                        text: note,
                        page: Some((i + 1) as u32),
                        sheet: None,
                        cell: None,
                    });
                }
            }
        }
        return Ok(extracted);
    }
    let mut header_seen = HashSet::new();
    for (si, section) in ir.sections.iter().enumerate() {
        push_word_elements(&section.elements, &mut extracted);
        take_header(&section.header, "header", "页眉", si, &mut header_seen, &mut extracted);
        take_header(&section.footer, "footer", "页脚", si, &mut header_seen, &mut extracted);
        take_header(
            &section.first_page_header,
            "header",
            "首页页眉",
            si,
            &mut header_seen,
            &mut extracted,
        );
        take_header(
            &section.first_page_footer,
            "footer",
            "首页页脚",
            si,
            &mut header_seen,
            &mut extracted,
        );
        take_header(
            &section.even_page_header,
            "header",
            "偶数页页眉",
            si,
            &mut header_seen,
            &mut extracted,
        );
        take_header(
            &section.even_page_footer,
            "footer",
            "偶数页页脚",
            si,
            &mut header_seen,
            &mut extracted,
        );
    }
    let _ = DocumentFormat::Docx;
    Ok(extracted)
}

pub fn parse_sheet(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let _guard = OFFICE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    apply_limits(limits);
    let ext = ext_of(path);
    if ext == "xls" {
        return parse_xls(path);
    }
    let doc = office_oxide::xlsx::XlsxDocument::open(long_path(path))
        .map_err(|err| classify_office_error(&err.to_string()))?;
    let mut extracted = Extracted::empty();
    if doc.has_macros {
        extracted.has_macros = true;
        extracted
            .warnings
            .push("文件含宏，已忽略，未执行".into());
    }
    for sheet in &doc.worksheets {
        let name = sheet.name.trim();
        if !name.is_empty() {
            extracted.segments.push(Segment {
                kind: "sheet_name".into(),
                label: format!("工作表 {name}"),
                text: nfc(name),
                page: None,
                sheet: Some(name.to_string()),
                cell: None,
            });
        }
        for row in &sheet.rows {
            for cell in &row.cells {
                let formula = cell.formula().map(|s| s.to_string());
                let empty = matches!(cell.value, CellValue::Empty);
                let addr = cell.reference.to_string();
                if empty {
                    if formula.is_some() {
                        extracted.warnings.push(format!(
                            "{name}!{addr} 含公式但无缓存结果，未计算公式"
                        ));
                    }
                    continue;
                }
                let text = doc.format_cell_value(cell);
                if text.trim().is_empty() || text.starts_with('=') && empty {
                    continue;
                }
                extracted.segments.push(Segment {
                    kind: "sheet_cell".into(),
                    label: format!("{name}!{addr}"),
                    text: nfc(text.trim()),
                    page: None,
                    sheet: Some(name.to_string()),
                    cell: Some(addr),
                });
            }
        }
    }
    Ok(extracted)
}

fn parse_xls(path: &Path) -> Result<Extracted, ExtractError> {
    let doc = office_oxide::xls::XlsDocument::open(long_path(path))
        .map_err(|err| classify_office_error(&err.to_string()))?;
    let mut extracted = Extracted::empty();
    for sheet in &doc.sheets {
        let name = if sheet.name.trim().is_empty() {
            "Sheet".to_string()
        } else {
            sheet.name.clone()
        };
        extracted.segments.push(Segment {
            kind: "sheet_name".into(),
            label: format!("工作表 {name}"),
            text: nfc(&name),
            page: None,
            sheet: Some(name.clone()),
            cell: None,
        });
        for (r, row) in sheet.rows.iter().enumerate() {
            for c in 0..row.len() {
                let Some(text) = sheet.display_text(r, c) else {
                    continue;
                };
                let text = text.trim();
                if text.is_empty() {
                    continue;
                }
                let addr = format!("{}{}", col_letters(c as u32), r + 1);
                extracted.segments.push(Segment {
                    kind: "sheet_cell".into(),
                    label: format!("{name}!{addr}"),
                    text: nfc(text),
                    page: None,
                    sheet: Some(name.clone()),
                    cell: Some(addr),
                });
            }
        }
    }
    Ok(extracted)
}

fn parse_pptx(path: &Path) -> Result<Extracted, ExtractError> {
    let doc = office_oxide::pptx::PptxDocument::open(long_path(path))
        .map_err(|err| classify_office_error(&err.to_string()))?;
    let mut extracted = Extracted::empty();
    for i in 0..doc.slides.len() {
        let Some(text) = doc.slide_plain_text(i) else {
            continue;
        };
        let text = nfc(text.trim());
        if text.is_empty() {
            continue;
        }
        let page = (i + 1) as u32;
        extracted.segments.push(Segment {
            kind: "slide".into(),
            label: format!("幻灯片{page}"),
            text,
            page: Some(page),
            sheet: None,
            cell: None,
        });
    }
    Ok(extracted)
}

fn push_word_elements(elements: &[Element], extracted: &mut Extracted) {
    for el in elements {
        match el {
            Element::Paragraph(p) => {
                push_body(&inline_to_text(&p.content), "body", "正文", extracted);
            }
            Element::Heading(h) => {
                push_body(&inline_to_text(&h.content), "body", "正文", extracted);
            }
            Element::CodeBlock(c) => push_body(&c.content, "body", "正文", extracted),
            Element::Table(table) => {
                for (ri, row) in table.rows.iter().enumerate() {
                    for (ci, cell) in row.cells.iter().enumerate() {
                        let mut buf = String::new();
                        append_plain(&cell.content, &mut buf);
                        let text = nfc(buf.trim());
                        if text.is_empty() {
                            continue;
                        }
                        extracted.segments.push(Segment {
                            kind: "table".into(),
                            label: format!("表格 第{}行第{}列", ri + 1, ci + 1),
                            text,
                            page: None,
                            sheet: None,
                            cell: Some(format!("R{}C{}", ri + 1, ci + 1)),
                        });
                    }
                }
            }
            Element::List(list) => {
                for item in &list.items {
                    push_word_elements(&item.content, extracted);
                    if let Some(nested) = &item.nested {
                        push_word_elements(
                            &[Element::List(nested.clone())],
                            extracted,
                        );
                    }
                }
            }
            Element::TextBox(tb) => {
                let mut buf = String::new();
                append_plain(&tb.content, &mut buf);
                push_body(&buf, "textbox", "文本框", extracted);
            }
            Element::Footnote(n) => {
                let mut buf = String::new();
                append_plain(&n.content, &mut buf);
                push_body(&buf, "footnote", "脚注", extracted);
            }
            Element::Endnote(n) => {
                let mut buf = String::new();
                append_plain(&n.content, &mut buf);
                push_body(&buf, "endnote", "尾注", extracted);
            }
            Element::Image(_)
            | Element::ThematicBreak
            | Element::PageBreak
            | Element::ColumnBreak
            | Element::Shape(_) => {}
            _ => {}
        }
    }
}

fn push_body(text: &str, kind: &str, label: &str, extracted: &mut Extracted) {
    let text = nfc(text.trim());
    if text.is_empty() {
        return;
    }
    extracted.segments.push(Segment {
        kind: kind.into(),
        label: label.into(),
        text,
        page: None,
        sheet: None,
        cell: None,
    });
}

fn take_header(
    hf: &Option<HeaderFooter>,
    kind: &str,
    label: &str,
    section_index: usize,
    seen: &mut HashSet<String>,
    extracted: &mut Extracted,
) {
    let Some(hf) = hf else {
        return;
    };
    let mut buf = String::new();
    append_plain(&hf.content, &mut buf);
    let text = nfc(buf.trim());
    if text.is_empty() {
        return;
    }
    let key = format!("{kind}\0{text}");
    if !seen.insert(key) {
        return;
    }
    let label = if section_index == 0 {
        label.to_string()
    } else {
        format!("{label}（节{}）", section_index + 1)
    };
    extracted.segments.push(Segment {
        kind: kind.into(),
        label,
        text,
        page: None,
        sheet: None,
        cell: None,
    });
}

fn append_plain(elements: &[Element], out: &mut String) {
    for el in elements {
        match el {
            Element::Paragraph(p) => {
                let t = inline_to_text(&p.content);
                if !t.trim().is_empty() {
                    if !out.is_empty() {
                        out.push('\n');
                    }
                    out.push_str(t.trim());
                }
            }
            Element::Heading(h) => {
                let t = inline_to_text(&h.content);
                if !t.trim().is_empty() {
                    if !out.is_empty() {
                        out.push('\n');
                    }
                    out.push_str(t.trim());
                }
            }
            Element::CodeBlock(c) => {
                if !c.content.trim().is_empty() {
                    if !out.is_empty() {
                        out.push('\n');
                    }
                    out.push_str(c.content.trim());
                }
            }
            Element::Table(table) => {
                for row in &table.rows {
                    for cell in &row.cells {
                        append_plain(&cell.content, out);
                    }
                }
            }
            Element::List(list) => {
                for item in &list.items {
                    append_plain(&item.content, out);
                    if let Some(nested) = &item.nested {
                        append_plain(&[Element::List(nested.clone())], out);
                    }
                }
            }
            Element::TextBox(tb) => append_plain(&tb.content, out),
            Element::Footnote(n) | Element::Endnote(n) => append_plain(&n.content, out),
            _ => {}
        }
    }
}

fn apply_limits(limits: &Limits) {
    office_oxide::limits::set_max_package_entries(limits.max_zip_entries);
    office_oxide::limits::set_max_package_bytes(limits.max_file_bytes);
    office_oxide::limits::set_max_part_bytes(limits.max_file_bytes.min(32 * 1024 * 1024));
    office_oxide::limits::set_max_inflate_ratio(limits.max_ratio);
    office_oxide::limits::set_max_text_chars(limits.max_extract_chars);
    office_oxide::limits::set_max_memory_bytes(512 * 1024 * 1024);
    office_oxide::limits::set_max_embedded_depth(1);
    office_oxide::limits::set_max_embedded_packages(4);
}

fn ext_of(path: &Path) -> String {
    path.extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
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
    String::from_utf8(out).unwrap_or_else(|_| "A".into())
}

#[allow(dead_code)]
fn _section_marker(section: &Section) {
    let _ = section.title.as_ref();
}
