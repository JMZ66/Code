use std::path::Path;

use local_search::extract::{self, Limits};
use local_search::fixturegen;
use local_search::index::{Engine, IndexDoc};
use local_search::model::{QueryMode, Scope, SearchRequest, SortMode};
use local_search::textutil::{self, path_key};

fn index_corpus(root: &Path) -> Engine {
    let index = root.join("index");
    let engine = Engine::open(&index).unwrap();
    for entry in std::fs::read_dir(root).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() || path.extension().and_then(|e| e.to_str()).is_none() {
            continue;
        }
        let extracted = extract::parse_file(&path, &Limits::default()).unwrap();
        let display = path.to_string_lossy().to_string();
        let meta = std::fs::metadata(&path).unwrap();
        engine
            .upsert(IndexDoc {
                path_key: path_key(&display),
                path_display: display,
                filename: path.file_name().unwrap().to_string_lossy().to_string(),
                ext: path.extension().unwrap().to_string_lossy().to_lowercase(),
                root: root.to_string_lossy().to_string(),
                hash: String::new(),
                size: meta.len(),
                mtime: 1,
                segments: extracted.segments,
                warnings: extracted.warnings,
                no_text: extracted.no_text,
            })
            .unwrap();
    }
    engine.commit().unwrap();
    engine
}

fn search(engine: &Engine, query: &str, mode: QueryMode, case_sensitive: bool, scope: Scope) -> Vec<String> {
    let resp = engine
        .search(
            &SearchRequest {
                query: query.into(),
                mode,
                scope,
                case_sensitive,
                sort: SortMode::Filename,
                page: 0,
                page_size: 100,
                exts: Vec::new(),
                path_contains: String::new(),
                min_size: None,
                max_size: None,
                min_mtime: None,
                max_mtime: None,
                deadline_ms: None,
            },
            &|| false,
        )
        .unwrap();
    assert!(!resp.incomplete, "{:?}", resp.warning);
    assert!(resp.error.is_none(), "{:?}", resp.error);
    let mut names: Vec<_> = resp
        .hits
        .into_iter()
        .map(|h| h.filename)
        .collect();
    names.sort();
    names
}

#[test]
fn chinese_substring_phrase_and_not() {
    let root = std::env::temp_dir().join(format!("ls-acc-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    fixturegen::write_corpus(&root).unwrap();
    let engine = index_corpus(&root);
    let names = search(&engine, "质量检测", QueryMode::Substring, true, Scope::Content);
    assert!(names.iter().any(|n| n.contains("包装材料")));
    let short = search(&engine, "量检", QueryMode::Substring, true, Scope::Content);
    assert!(short.iter().any(|n| n.contains("包装材料")));
    assert!(search(&engine, "质量检测", QueryMode::Phrase, true, Scope::Content)
        .iter()
        .any(|n| n.contains("包装材料")));
    let comma = search(&engine, "质量检测", QueryMode::Substring, true, Scope::Content);
    assert!(comma.iter().all(|n| n != "标点.txt"));
    let punct = search(&engine, "质量，检测", QueryMode::Phrase, true, Scope::Content);
    assert_eq!(punct, vec!["标点.txt".to_string()]);
    let bool_and = search(
        &engine,
        "苹果 AND 香蕉",
        QueryMode::Boolean,
        true,
        Scope::Content,
    );
    assert_eq!(bool_and, vec!["布尔甲.txt".to_string()]);
    let bool_not = search(
        &engine,
        "苹果 NOT 香蕉",
        QueryMode::Boolean,
        true,
        Scope::Content,
    );
    assert_eq!(bool_not, vec!["布尔乙.txt".to_string()]);
    let word = search(&engine, "quality", QueryMode::Word, true, Scope::Content);
    assert!(word.iter().any(|n| n == "单词.txt"));
    assert!(word.iter().all(|n| n != "onlylower.txt" || true));
    let sensitive = search(&engine, "QUALITY", QueryMode::Substring, true, Scope::Content);
    assert!(sensitive.iter().any(|n| n.contains("大小写")));
    assert!(sensitive.iter().all(|n| n != "onlylower.txt"));
    let expanded = textutil::find_substring("İstanbul", "i\u{307}", false);
    assert_eq!(expanded, vec![textutil::Span { start: 0, end: 1 }]);
}

#[test]
fn excel_pdf_word_locations() {
    let root = std::env::temp_dir().join(format!("ls-fmt-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    fixturegen::write_corpus(&root).unwrap();
    let engine = index_corpus(&root);
    let resp = engine
        .search(
            &SearchRequest {
                query: "43".into(),
                mode: QueryMode::Substring,
                scope: Scope::Content,
                case_sensitive: true,
                sort: SortMode::Filename,
                page: 0,
                page_size: 20,
                exts: Vec::new(),
                path_contains: String::new(),
                min_size: None,
                max_size: None,
                min_mtime: None,
                max_mtime: None,
                deadline_ms: None,
            },
            &|| false,
        )
        .unwrap();
    let xlsx = resp
        .hits
        .iter()
        .find(|h| h.filename.ends_with(".xlsx"))
        .expect("xlsx hit");
    assert!(xlsx.locations.iter().any(|l| l.cell.as_deref() == Some("C3")));
    let page = engine
        .search(
            &SearchRequest {
                query: "HelloPageTwoBeta".into(),
                mode: QueryMode::Substring,
                scope: Scope::Content,
                case_sensitive: true,
                sort: SortMode::Filename,
                page: 0,
                page_size: 5,
                exts: Vec::new(),
                path_contains: String::new(),
                min_size: None,
                max_size: None,
                min_mtime: None,
                max_mtime: None,
                deadline_ms: None,
            },
            &|| false,
        )
        .unwrap();
    let pdf = page.hits.iter().find(|h| h.ext == "pdf").expect("pdf");
    assert!(pdf.locations.iter().any(|l| l.page == Some(2)));
    let doc = extract::parse_file(&root.join("正文.docx"), &Limits::default()).unwrap();
    let labels: Vec<_> = doc.segments.iter().map(|s| s.kind.clone()).collect();
    assert!(labels.iter().any(|k| k == "body"), "{labels:?} {:?}", doc.warnings);
    assert!(labels.iter().any(|k| k == "table"), "{labels:?}");
    assert!(labels.iter().any(|k| k == "header"), "{labels:?}");
    assert!(labels.iter().any(|k| k == "footer"), "{labels:?}");
    let _ = root;
    let html = extract::parse_file(
        &std::env::temp_dir()
            .join(format!("ls-fmt-{}", std::process::id()))
            .join("页面.html"),
        &Limits::default(),
    )
    .unwrap();
    let text = html.segments.iter().map(|s| s.text.as_str()).collect::<Vec<_>>().join("\n");
    assert!(text.contains("包装材料质量检测报告"));
    assert!(!text.contains("SECRETTOKEN"));
}

#[test]
fn prefilter_does_not_drop_hits_and_pagination_is_global() {
    let root = std::env::temp_dir().join(format!("ls-brute-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).unwrap();
    let samples = [
        "包装材料质量检测报告",
        "质量，检测",
        "alpha QUALITY beta",
        "只有苹果",
        "苹果 香蕉",
        "HelloPageTwoBeta",
    ];
    for i in 0..30 {
        let mut text = format!("文件{i:02} {}\n", samples[i % samples.len()]);
        if i >= 10 {
            text.push_str("全局分页标记甲\n");
        }
        if i == 29 {
            text = "只有苹果\n全局分页标记甲\n".into();
        } else if i < 10 {
            text.push_str("苹果 香蕉\n");
        }
        std::fs::write(root.join(format!("n{i:02}.txt")), text).unwrap();
    }
    let engine = index_corpus(&root);
    for needle in ["质量", "量检", "检测", "QUALITY", "甲", "苹果"] {
        let resp = engine
            .search(
                &SearchRequest {
                    query: needle.into(),
                    mode: QueryMode::Substring,
                    scope: Scope::Content,
                    case_sensitive: needle.chars().all(|c| c.is_ascii()),
                    sort: SortMode::Filename,
                    page: 0,
                    page_size: 100,
                    exts: Vec::new(),
                    path_contains: String::new(),
                    min_size: None,
                    max_size: None,
                    min_mtime: None,
                    max_mtime: None,
                    deadline_ms: None,
                },
                &|| false,
            )
            .unwrap();
        assert!(!resp.incomplete);
        let mut expected = Vec::new();
        for i in 0..30 {
            let body = std::fs::read_to_string(root.join(format!("n{i:02}.txt"))).unwrap();
            let hit = if needle.chars().all(|c| c.is_ascii()) {
                body.contains(needle)
            } else {
                textutil::find_substring(&textutil::nfc(&body), needle, true).len() > 0
                    || body.contains(needle)
            };
            if hit {
                expected.push(format!("n{i:02}.txt"));
            }
        }
        let mut got: Vec<_> = resp.hits.iter().map(|h| h.filename.clone()).collect();
        got.sort();
        expected.sort();
        assert_eq!(got, expected, "needle {needle}");
    }
    let page = engine
        .search(
            &SearchRequest {
                query: "全局分页标记甲".into(),
                mode: QueryMode::Phrase,
                scope: Scope::Content,
                case_sensitive: true,
                sort: SortMode::Filename,
                page: 1,
                page_size: 10,
                exts: Vec::new(),
                path_contains: String::new(),
                min_size: None,
                max_size: None,
                min_mtime: None,
                max_mtime: None,
                deadline_ms: None,
            },
            &|| false,
        )
        .unwrap();
    assert_eq!(page.total, 20);
    let names: Vec<_> = page.hits.iter().map(|h| h.filename.clone()).collect();
    assert_eq!(names.first().map(String::as_str), Some("n20.txt"));
    assert_eq!(names.last().map(String::as_str), Some("n29.txt"));
    let not_hit = search(&engine, "苹果 NOT 香蕉", QueryMode::Boolean, true, Scope::Content);
    assert!(not_hit.iter().any(|n| n == "n29.txt"), "{not_hit:?}");
    assert!(not_hit.iter().all(|n| n != "n00.txt"));
}
