//! Exact evaluation of a query against one stored document.

use crate::model::{Location, SegRange, Segment};
use crate::query::Ast;
use crate::textutil::{self, Span};

#[derive(Debug, Clone)]
pub struct FieldHit {
    pub matched: bool,
    pub spans: Vec<Span>,
    pub error: Option<String>,
}

pub fn eval_field(ast: &Ast, text: &str, case_sensitive: bool) -> Result<FieldHit, String> {
    let (matched, spans) = eval(ast, text, case_sensitive)?;
    Ok(FieldHit {
        matched,
        spans,
        error: None,
    })
}

fn eval(ast: &Ast, text: &str, case_sensitive: bool) -> Result<(bool, Vec<Span>), String> {
    match ast {
        Ast::Literal { text: needle, .. } => {
            let spans = textutil::find_substring(text, needle, case_sensitive);
            Ok((!spans.is_empty(), spans))
        }
        Ast::Word(word) => {
            let spans = textutil::find_word(text, word, case_sensitive);
            Ok((!spans.is_empty(), spans))
        }
        Ast::Regex(pat) => {
            let spans = textutil::find_regex(text, pat, case_sensitive)?;
            Ok((!spans.is_empty(), spans))
        }
        Ast::Not(inner) => {
            let (ok, _) = eval(inner, text, case_sensitive)?;
            Ok((!ok, Vec::new()))
        }
        Ast::And(xs) => {
            let mut all = Vec::new();
            for x in xs {
                let (ok, spans) = eval(x, text, case_sensitive)?;
                if !ok {
                    return Ok((false, Vec::new()));
                }
                all.extend(spans);
            }
            Ok((true, all))
        }
        Ast::Or(xs) => {
            let mut any = false;
            let mut all = Vec::new();
            for x in xs {
                let (ok, spans) = eval(x, text, case_sensitive)?;
                if ok {
                    any = true;
                    all.extend(spans);
                }
            }
            Ok((any, all))
        }
    }
}

pub fn locations_for(
    spans: &[Span],
    segments: &[Segment],
    ranges: &[SegRange],
    limit: usize,
) -> Vec<Location> {
    let mut out = Vec::new();
    for span in spans {
        if out.len() >= limit {
            break;
        }
        let Some(range) = ranges.iter().find(|r| span.start >= r.start && span.start < r.end) else {
            continue;
        };
        let seg = &segments[range.index];
        let chars: Vec<char> = seg.text.chars().collect();
        let local_start = span.start - range.start;
        let local_end = span.end.saturating_sub(range.start).min(chars.len());
        let excerpt = if local_start < chars.len() {
            chars[local_start..local_end.max(local_start)].iter().collect()
        } else {
            String::new()
        };
        out.push(Location {
            label: seg.label.clone(),
            kind: seg.kind.clone(),
            start: span.start,
            end: span.end,
            page: seg.page,
            sheet: seg.sheet.clone(),
            cell: seg.cell.clone(),
            text: excerpt,
        });
    }
    out
}

pub fn score_hit(filename_hit: bool, content_spans: &[Span]) -> i64 {
    let mut score = 0i64;
    if filename_hit {
        score += 10_000;
    }
    score += (content_spans.len().min(50) as i64) * 100;
    if let Some(first) = content_spans.iter().map(|s| s.start).min() {
        score -= first.min(10_000) as i64;
    }
    score
}
