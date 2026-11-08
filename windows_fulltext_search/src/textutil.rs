//! Literal matching on stored NFC text.
//!
//! Case-insensitive hits are found on the case-folded string and mapped back
//! to original scalar offsets. A fold that expands (for example ß → ss) still
//! highlights the original character, not a shifted neighbor.

use unicode_normalization::UnicodeNormalization;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

pub fn nfc(s: &str) -> String {
    s.nfc().collect()
}

pub fn fold_case(s: &str) -> String {
    s.chars().flat_map(|c| c.to_lowercase()).collect()
}

struct FoldMap {
    text: String,
    /// Folded char index → original char index.
    map: Vec<u32>,
}

fn fold_map(s: &str) -> FoldMap {
    let mut text = String::new();
    let mut map = Vec::new();
    for (i, c) in s.chars().enumerate() {
        for lc in c.to_lowercase() {
            text.push(lc);
            map.push(i as u32);
        }
    }
    FoldMap { text, map }
}

pub fn find_substring(hay: &str, needle: &str, case_sensitive: bool) -> Vec<Span> {
    if needle.is_empty() || hay.is_empty() {
        return Vec::new();
    }
    if case_sensitive {
        find_literal(hay, needle)
    } else {
        find_folded(hay, needle)
    }
}

fn find_literal(hay: &str, needle: &str) -> Vec<Span> {
    let mut out = Vec::new();
    let mut from = 0usize;
    while from < hay.len() {
        let Some(rel) = hay[from..].find(needle) else {
            break;
        };
        let byte = from + rel;
        let start = hay[..byte].chars().count();
        let end = start + needle.chars().count();
        out.push(Span { start, end });
        let step = hay[byte..].chars().next().map(|c| c.len_utf8()).unwrap_or(1);
        from = byte + step;
    }
    out
}

fn find_folded(hay: &str, needle: &str) -> Vec<Span> {
    let hay_f = fold_map(hay);
    let needle_f = fold_case(needle);
    if needle_f.is_empty() {
        return Vec::new();
    }
    let needle_chars = needle_f.chars().count();
    let mut out = Vec::new();
    let mut from = 0usize;
    while from < hay_f.text.len() {
        let Some(rel) = hay_f.text[from..].find(&needle_f) else {
            break;
        };
        let byte = from + rel;
        let fold_start = hay_f.text[..byte].chars().count();
        let fold_end = fold_start + needle_chars;
        if fold_end == 0 || fold_end > hay_f.map.len() {
            break;
        }
        let start = hay_f.map[fold_start] as usize;
        let end = hay_f.map[fold_end - 1] as usize + 1;
        if out.last().map(|s: &Span| s.start == start && s.end == end) != Some(true) {
            out.push(Span { start, end });
        }
        let step = hay_f.text[byte..]
            .chars()
            .next()
            .map(|c| c.len_utf8())
            .unwrap_or(1);
        from = byte + step;
    }
    out
}

pub fn find_word(hay: &str, word: &str, case_sensitive: bool) -> Vec<Span> {
    if word.is_empty() {
        return Vec::new();
    }
    let want = if case_sensitive {
        word.to_string()
    } else {
        fold_case(word)
    };
    let mut spans = Vec::new();
    let mut char_i = 0usize;
    let mut chars = hay.chars().peekable();
    while let Some(c) = chars.next() {
        if c.is_alphanumeric() {
            let start = char_i;
            let mut token = String::new();
            token.push(c);
            char_i += 1;
            while let Some(n) = chars.peek().copied() {
                if n.is_alphanumeric() {
                    token.push(n);
                    chars.next();
                    char_i += 1;
                } else {
                    break;
                }
            }
            let end = char_i;
            let got = if case_sensitive {
                token
            } else {
                fold_case(&token)
            };
            if got == want {
                spans.push(Span { start, end });
            }
        } else {
            char_i += 1;
        }
    }
    spans
}

pub fn find_regex(hay: &str, pattern: &str, case_sensitive: bool) -> Result<Vec<Span>, String> {
    let mut builder = regex::RegexBuilder::new(pattern);
    builder.case_insensitive(!case_sensitive);
    builder.size_limit(8 * 1024 * 1024);
    builder.dfa_size_limit(8 * 1024 * 1024);
    let re = builder
        .build()
        .map_err(|e| format!("正则无法编译：{e}"))?;
    let mut out = Vec::new();
    // Char indexes of each byte boundary, built once.
    let mut byte_to_char = vec![0usize; hay.len() + 1];
    let mut ci = 0usize;
    for (b, _) in hay.char_indices() {
        byte_to_char[b] = ci;
        ci += 1;
    }
    byte_to_char[hay.len()] = ci;
    for m in re.find_iter(hay) {
        let start = byte_to_char[m.start()];
        let end = byte_to_char[m.end()];
        if end > start {
            out.push(Span { start, end });
        }
    }
    Ok(out)
}

pub fn snippet(content: &str, span: Span, radius: usize) -> (String, Vec<(usize, usize)>) {
    let chars: Vec<char> = content.chars().collect();
    if chars.is_empty() || span.start >= chars.len() {
        return (String::new(), Vec::new());
    }
    let end = span.end.min(chars.len());
    let start = span.start.min(end);
    let win_s = start.saturating_sub(radius);
    let win_e = (end + radius).min(chars.len());
    let text: String = chars[win_s..win_e].iter().collect();
    let local = (start - win_s, end - win_s);
    (text, vec![local])
}

pub fn ngrams(folded: &str) -> Vec<String> {
    let chars: Vec<char> = folded.chars().collect();
    if chars.is_empty() {
        return Vec::new();
    }
    if chars.len() == 1 {
        return vec![chars[0].to_string()];
    }
    let mut grams: Vec<String> = chars.windows(2).map(|w| w.iter().collect()).collect();
    // A shorter AND-list is still a superset of the documents that contain
    // every bigram, so capping cannot drop a true hit. Verification is exact.
    if grams.len() > 64 {
        let mut slim = grams[..32].to_vec();
        slim.extend(grams[grams.len() - 32..].iter().cloned());
        grams = slim;
    }
    grams
}

pub fn path_key(display: &str) -> String {
    let n = nfc(display);
    #[cfg(windows)]
    {
        n.to_lowercase()
    }
    #[cfg(not(windows))]
    {
        n
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chinese_substring_inside_longer_title() {
        let hay = "包装材料质量检测报告";
        let a = find_substring(hay, "质量检测", true);
        assert_eq!(a, vec![Span { start: 4, end: 8 }]);
        let b = find_substring(hay, "量检", true);
        assert_eq!(b, vec![Span { start: 5, end: 7 }]);
        assert!(find_substring(hay, "检", true).iter().any(|s| s.start == 6));
    }

    #[test]
    fn punctuation_blocks_joined_substring() {
        let hay = "质量，检测";
        assert!(find_substring(hay, "，", true).len() == 1);
        assert!(find_substring(hay, "质量，检测", true).len() == 1);
        assert!(find_substring(hay, "质量检测", true).is_empty());
    }

    #[test]
    fn case_fold_offsets_cover_original_chars() {
        // Rust lowercases İ to i plus a combining dot. The highlight must cover
        // the original character, not the expanded folded characters.
        let hay = "İ QUALITY";
        let expanded = find_substring(hay, "i\u{307}", false);
        assert_eq!(expanded, vec![Span { start: 0, end: 1 }]);
        let q = find_substring(hay, "quality", false);
        assert_eq!(q, vec![Span { start: 2, end: 9 }]);
        assert!(find_substring(hay, "quality", true).is_empty());
        assert_eq!(
            find_substring(hay, "QUALITY", true),
            vec![Span { start: 2, end: 9 }]
        );
    }

    #[test]
    fn whole_word_does_not_match_inside_token() {
        let hay = "quality qualitydetection Quality";
        assert_eq!(find_word(hay, "quality", true).len(), 1);
        assert_eq!(find_word(hay, "quality", false).len(), 2);
        assert!(find_word(hay, "qualitydetection", true).len() == 1);
    }

    #[test]
    fn nfc_matches_combining_form_after_normalize() {
        let composed = nfc("é");
        let decomposed = nfc("e\u{0301}");
        assert_eq!(composed, decomposed);
        assert!(!find_substring(&composed, &decomposed, true).is_empty());
    }
}
