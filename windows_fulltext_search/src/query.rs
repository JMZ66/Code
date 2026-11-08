//! Query language.
//!
//! Substring and phrase modes are contiguous literals. They are not an AND of
//! tokens. Boolean mode is the only mode that reads AND / OR / NOT.
//! A quoted string in boolean mode is a contiguous phrase. A bare term is a
//! substring. `NOT` is applied to the real stored text of each candidate, never
//! to a truncated top-N list.

use regex_syntax::hir::{Hir, HirKind};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Ast {
    /// Contiguous literal. `phrase` is true when the user asked for a phrase
    /// (the match rule is the same: the characters must occur in order).
    Literal { text: String, phrase: bool },
    Word(String),
    Regex(String),
    And(Vec<Ast>),
    Or(Vec<Ast>),
    Not(Box<Ast>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Tok {
    And,
    Or,
    Not,
    LParen,
    RParen,
    Phrase(String),
    Regex(String),
    Term(String),
}

pub fn parse_query(input: &str, mode: crate::model::QueryMode) -> Result<Option<Ast>, String> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    use crate::model::QueryMode::*;
    let ast = match mode {
        Substring => Ast::Literal {
            text: trimmed.to_string(),
            phrase: false,
        },
        Phrase => Ast::Literal {
            text: trimmed.to_string(),
            phrase: true,
        },
        Word => parse_words(trimmed)?,
        Boolean => parse_boolean(trimmed)?,
        Regex => Ast::Regex(trimmed.to_string()),
    };
    Ok(Some(ast))
}

fn parse_words(input: &str) -> Result<Ast, String> {
    let parts: Vec<Ast> = input
        .split_whitespace()
        .filter(|s| !s.is_empty())
        .map(|s| Ast::Word(s.to_string()))
        .collect();
    if parts.is_empty() {
        return Err("单词查询是空的".into());
    }
    if parts.len() == 1 {
        Ok(parts.into_iter().next().unwrap())
    } else {
        Ok(Ast::And(parts))
    }
}

fn parse_boolean(input: &str) -> Result<Ast, String> {
    let tokens = lex(input)?;
    if tokens.is_empty() {
        return Err("布尔查询是空的".into());
    }
    let mut i = 0;
    let ast = parse_or(&tokens, &mut i)?;
    if i != tokens.len() {
        return Err("布尔查询有无法解析的剩余内容".into());
    }
    Ok(ast)
}

fn lex(input: &str) -> Result<Vec<Tok>, String> {
    let chars: Vec<char> = input.chars().collect();
    let mut i = 0;
    let mut out = Vec::new();
    while i < chars.len() {
        if chars[i].is_whitespace() {
            i += 1;
            continue;
        }
        match chars[i] {
            '(' => {
                out.push(Tok::LParen);
                i += 1;
            }
            ')' => {
                out.push(Tok::RParen);
                i += 1;
            }
            '"' => {
                i += 1;
                let mut s = String::new();
                let mut closed = false;
                while i < chars.len() {
                    if chars[i] == '\\' && i + 1 < chars.len() {
                        s.push(chars[i + 1]);
                        i += 2;
                        continue;
                    }
                    if chars[i] == '"' {
                        closed = true;
                        i += 1;
                        break;
                    }
                    s.push(chars[i]);
                    i += 1;
                }
                if !closed {
                    return Err("短语缺少结束引号".into());
                }
                out.push(Tok::Phrase(s));
            }
            '/' => {
                i += 1;
                let mut s = String::new();
                let mut closed = false;
                while i < chars.len() {
                    if chars[i] == '\\' && i + 1 < chars.len() && chars[i + 1] == '/' {
                        s.push('/');
                        i += 2;
                        continue;
                    }
                    if chars[i] == '/' {
                        closed = true;
                        i += 1;
                        break;
                    }
                    s.push(chars[i]);
                    i += 1;
                }
                if !closed {
                    return Err("正则缺少结束斜杠 /".into());
                }
                out.push(Tok::Regex(s));
            }
            _ => {
                let start = i;
                while i < chars.len()
                    && !chars[i].is_whitespace()
                    && chars[i] != '('
                    && chars[i] != ')'
                {
                    i += 1;
                }
                let word: String = chars[start..i].iter().collect();
                if word == "AND" {
                    out.push(Tok::And);
                } else if word == "OR" {
                    out.push(Tok::Or);
                } else if word == "NOT" {
                    out.push(Tok::Not);
                } else if let Some(rest) = word.strip_prefix('-') {
                    if !rest.is_empty() && !rest.starts_with('-') {
                        out.push(Tok::Not);
                        out.push(Tok::Term(rest.to_string()));
                    } else {
                        out.push(Tok::Term(word));
                    }
                } else {
                    out.push(Tok::Term(word));
                }
            }
        }
    }
    Ok(out)
}

fn parse_or(toks: &[Tok], i: &mut usize) -> Result<Ast, String> {
    let mut items = vec![parse_and(toks, i)?];
    while matches!(toks.get(*i), Some(Tok::Or)) {
        *i += 1;
        items.push(parse_and(toks, i)?);
    }
    Ok(flatten_or(items))
}

fn parse_and(toks: &[Tok], i: &mut usize) -> Result<Ast, String> {
    let mut items = vec![parse_unary(toks, i)?];
    loop {
        if matches!(toks.get(*i), Some(Tok::And)) {
            *i += 1;
            items.push(parse_unary(toks, i)?);
            continue;
        }
        // Juxtaposition is AND, not a phrase. A phrase needs quotes.
        if matches!(
            toks.get(*i),
            Some(Tok::Term(_) | Tok::Phrase(_) | Tok::Regex(_) | Tok::Not | Tok::LParen)
        ) {
            items.push(parse_unary(toks, i)?);
            continue;
        }
        break;
    }
    Ok(flatten_and(items))
}

fn parse_unary(toks: &[Tok], i: &mut usize) -> Result<Ast, String> {
    if matches!(toks.get(*i), Some(Tok::Not)) {
        *i += 1;
        let inner = parse_unary(toks, i)?;
        return Ok(Ast::Not(Box::new(inner)));
    }
    parse_primary(toks, i)
}

fn parse_primary(toks: &[Tok], i: &mut usize) -> Result<Ast, String> {
    let Some(tok) = toks.get(*i) else {
        return Err("布尔查询意外结束".into());
    };
    *i += 1;
    match tok {
        Tok::LParen => {
            let inner = parse_or(toks, i)?;
            if !matches!(toks.get(*i), Some(Tok::RParen)) {
                return Err("布尔查询缺少右括号".into());
            }
            *i += 1;
            Ok(inner)
        }
        Tok::Phrase(s) => Ok(Ast::Literal {
            text: s.clone(),
            phrase: true,
        }),
        Tok::Regex(s) => Ok(Ast::Regex(s.clone())),
        Tok::Term(s) => Ok(Ast::Literal {
            text: s.clone(),
            phrase: false,
        }),
        Tok::And | Tok::Or | Tok::Not | Tok::RParen => Err("布尔查询的运算符位置不对".into()),
    }
}

fn flatten_and(items: Vec<Ast>) -> Ast {
    if items.len() == 1 {
        items.into_iter().next().unwrap()
    } else {
        Ast::And(items)
    }
}

fn flatten_or(items: Vec<Ast>) -> Ast {
    if items.len() == 1 {
        items.into_iter().next().unwrap()
    } else {
        Ast::Or(items)
    }
}

/// A literal that must occur in every match, used only as a superset prefilter.
#[derive(Debug, Clone)]
pub struct RequiredLiteral {
    pub text: String,
    pub case_sensitive: bool,
}

pub fn regex_required_literals(pattern: &str, case_sensitive: bool) -> Result<Vec<RequiredLiteral>, String> {
    let mut parser = regex_syntax::ParserBuilder::new()
        .case_insensitive(false)
        .build();
    let hir = parser
        .parse(pattern)
        .map_err(|e| format!("正则无法解析：{e}"))?;
    let mut lits = Vec::new();
    collect_required(&hir, &mut lits);
    if !case_sensitive {
        for lit in &mut lits {
            lit.case_sensitive = false;
        }
    }
    Ok(lits)
}

fn collect_required(hir: &Hir, out: &mut Vec<RequiredLiteral>) {
    match hir.kind() {
        HirKind::Literal(lit) => {
            if let Ok(s) = std::str::from_utf8(&lit.0) {
                if !s.is_empty() {
                    out.push(RequiredLiteral {
                        text: s.to_string(),
                        case_sensitive: true,
                    });
                }
            }
        }
        HirKind::Concat(xs) => {
            for x in xs {
                let before = out.len();
                collect_required(x, out);
                if out.len() == before && !hir_can_be_empty(x) {
                    // A required non-literal piece. Drop literals from this
                    // concat that are not independently required... keep the
                    // ones already found in earlier pieces; they still must
                    // occur if they came from a previous required literal.
                    // Stop so a later optional piece is not treated as required
                    // after an opaque required piece. Literals already pushed
                    // from earlier parts of the concat remain valid.
                    break;
                }
            }
        }
        HirKind::Alternation(xs) => {
            // Every branch must contribute something, otherwise no literal is
            // forced. If each branch has literals, any match hits one of them,
            // so the OR of those literals is a superset. Represent that by
            // returning no single literal here; the caller ORs per-branch
            // prefilters separately. See `regex_prefilter_plan`.
            let _ = xs;
        }
        HirKind::Repetition(rep) => {
            if rep.min >= 1 {
                collect_required(&rep.sub, out);
            }
        }
        HirKind::Capture(c) => collect_required(&c.sub, out),
        _ => {}
    }
}

fn hir_can_be_empty(hir: &Hir) -> bool {
    match hir.kind() {
        HirKind::Empty | HirKind::Look(_) => true,
        HirKind::Repetition(rep) => rep.min == 0 || hir_can_be_empty(&rep.sub),
        HirKind::Concat(xs) => xs.iter().all(hir_can_be_empty),
        HirKind::Alternation(xs) => xs.iter().any(hir_can_be_empty),
        HirKind::Capture(c) => hir_can_be_empty(&c.sub),
        _ => false,
    }
}

/// How a regex may be prefiltered without missing a match.
#[derive(Debug, Clone)]
pub enum RegexPlan {
    /// Every match contains this literal.
    Literal(String),
    /// Every match contains at least one of these literals.
    Any(Vec<String>),
    /// No safe literal. Scan stored text.
    Scan,
}

pub fn regex_plan(pattern: &str) -> Result<RegexPlan, String> {
    let mut parser = regex_syntax::ParserBuilder::new().build();
    let hir = parser
        .parse(pattern)
        .map_err(|e| format!("正则无法解析：{e}"))?;
    Ok(plan_hir(&hir))
}

fn plan_hir(hir: &Hir) -> RegexPlan {
    match hir.kind() {
        HirKind::Literal(lit) => match std::str::from_utf8(&lit.0) {
            Ok(s) if !s.is_empty() => RegexPlan::Literal(s.to_string()),
            _ => RegexPlan::Scan,
        },
        HirKind::Concat(xs) => {
            for x in xs {
                match plan_hir(x) {
                    RegexPlan::Literal(s) if s.chars().count() >= 1 => return RegexPlan::Literal(s),
                    RegexPlan::Any(v) if !v.is_empty() => return RegexPlan::Any(v),
                    _ => {
                        if !hir_can_be_empty(x) {
                            return RegexPlan::Scan;
                        }
                    }
                }
            }
            RegexPlan::Scan
        }
        HirKind::Alternation(xs) => {
            let mut any = Vec::new();
            for x in xs {
                match plan_hir(x) {
                    RegexPlan::Literal(s) => any.push(s),
                    RegexPlan::Any(v) => any.extend(v),
                    RegexPlan::Scan => return RegexPlan::Scan,
                }
            }
            if any.is_empty() {
                RegexPlan::Scan
            } else {
                RegexPlan::Any(any)
            }
        }
        HirKind::Repetition(rep) => {
            if rep.min >= 1 {
                plan_hir(&rep.sub)
            } else {
                RegexPlan::Scan
            }
        }
        HirKind::Capture(c) => plan_hir(&c.sub),
        _ => RegexPlan::Scan,
    }
}

pub fn ast_has_unaccelerated_regex(ast: &Ast, case_sensitive: bool) -> bool {
    match ast {
        Ast::Regex(pat) => match regex_plan(pat) {
            Ok(RegexPlan::Scan) => true,
            Ok(RegexPlan::Literal(_)) | Ok(RegexPlan::Any(_)) => {
                let _ = (case_sensitive, pat);
                false
            }
            Err(_) => true,
        },
        Ast::And(xs) | Ast::Or(xs) => xs.iter().any(|x| ast_has_unaccelerated_regex(x, case_sensitive)),
        Ast::Not(x) => ast_has_unaccelerated_regex(x, case_sensitive),
        _ => false,
    }
}

fn s_is_scan(pat: &str) -> bool {
    matches!(regex_plan(pat), Ok(RegexPlan::Scan) | Err(_))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::QueryMode;

    #[test]
    fn phrase_is_not_and() {
        let ast = parse_query("质量检测", QueryMode::Phrase).unwrap().unwrap();
        assert_eq!(
            ast,
            Ast::Literal {
                text: "质量检测".into(),
                phrase: true
            }
        );
        let boolean = parse_query("质量 AND 检测", QueryMode::Boolean)
            .unwrap()
            .unwrap();
        assert!(matches!(boolean, Ast::And(_)));
    }

    #[test]
    fn quotes_are_phrase_and_juxtaposition_is_and() {
        let ast = parse_query("\"质量检测\" 报告", QueryMode::Boolean)
            .unwrap()
            .unwrap();
        match ast {
            Ast::And(xs) => {
                assert!(matches!(xs[0], Ast::Literal { phrase: true, .. }));
                assert!(matches!(xs[1], Ast::Literal { phrase: false, .. }));
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn alternation_regex_has_any_plan() {
        match regex_plan("质量|zzzznot").unwrap() {
            RegexPlan::Any(v) => {
                assert!(v.iter().any(|s| s == "质量"));
                assert!(v.iter().any(|s| s == "zzzznot"));
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn dot_regex_keeps_required_literal() {
        match regex_plan("质.检").unwrap() {
            RegexPlan::Literal(text) => assert_eq!(text, "质"),
            other => panic!("expected the required literal 质, got {other:?}"),
        }
        assert!(matches!(regex_plan(r"\d+").unwrap(), RegexPlan::Scan));
    }
}
