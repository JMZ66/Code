use std::path::Path;

use super::{read_limited, ExtractError, Limits};
use crate::model::{Extracted, Segment};
use crate::textutil::nfc;

pub fn parse_pdf(path: &Path, limits: &Limits) -> Result<Extracted, ExtractError> {
    let bytes = read_limited(path, limits)?;
    let doc = lopdf::Document::load_mem(&bytes).map_err(|err| {
        let msg = err.to_string();
        let lower = msg.to_lowercase();
        if lower.contains("encrypt") || lower.contains("password") {
            ExtractError::Encrypted(format!("PDF 可能已加密，未抽取文本：{msg}"))
        } else {
            ExtractError::Corrupt(format!("PDF 无法打开：{msg}"))
        }
    })?;
    if doc.is_encrypted() {
        return Err(ExtractError::Encrypted(
            "PDF 已加密或需要密码，未抽取文本，也不尝试破解".into(),
        ));
    }
    let pages = doc.get_pages();
    let mut extracted = Extracted::empty();
    if pages.is_empty() {
        extracted.no_text = true;
        extracted
            .warnings
            .push("PDF 没有页面，未做 OCR".into());
        return Ok(extracted);
    }
    let mut any_text = false;
    for (page_no, _) in pages {
        let text = match doc.extract_text(&[page_no]) {
            Ok(t) => nfc(t.trim()),
            Err(err) => {
                extracted.warnings.push(format!("第{page_no}页抽取失败：{err}"));
                String::new()
            }
        };
        if text.is_empty() {
            extracted.warnings.push(format!(
                "第{page_no}页没有可抽取文本。若是扫描件，本软件不做 OCR，也不把空白当成已识别文字"
            ));
            extracted.segments.push(Segment {
                kind: "pdf_page".into(),
                label: format!("第{page_no}页"),
                text: String::new(),
                page: Some(page_no),
                sheet: None,
                cell: None,
            });
        } else {
            any_text = true;
            extracted.segments.push(Segment {
                kind: "pdf_page".into(),
                label: format!("第{page_no}页"),
                text,
                page: Some(page_no),
                sheet: None,
                cell: None,
            });
        }
    }
    extracted.no_text = !any_text;
    Ok(extracted)
}
