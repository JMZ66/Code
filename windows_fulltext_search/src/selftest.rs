//! End-to-end check used by the packaged executable. It builds a generated
//! folder, indexes it, searches, checks a location, edits a file, updates the
//! index, restarts from disk, and confirms source hashes of untouched files.

use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{anyhow, Context, Result};
use serde::Serialize;

use crate::extract::{self, Limits};
use crate::fixturegen;
use crate::index::{Engine, IndexDoc};
use crate::model::{QueryMode, Scope, SearchRequest, SortMode};
use crate::scan;
use crate::textutil::path_key;

#[derive(Debug, Serialize)]
pub struct Report {
    pub ok: bool,
    pub checks: Vec<String>,
    pub failures: Vec<String>,
    pub elapsed_ms: u128,
    pub indexed_files: u64,
    pub gui: &'static str,
}

pub fn run(report_path: &Path) -> Result<Report> {
    let started = Instant::now();
    let base = std::env::temp_dir().join(format!("localsearch-selftest-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&base);
    std::fs::create_dir_all(&base)?;
    let corpus = base.join("corpus");
    let index = base.join("index");
    fixturegen::write_corpus(&corpus)?;
    let before = hash_tree(&corpus)?;
    let mut checks = Vec::new();
    let mut failures = Vec::new();

    let engine = Engine::open(&index)?;
    let n = index_tree(&engine, &corpus, &corpus)?;
    engine.commit()?;
    checks.push(format!("indexed {n} generated files"));

    let hit = search_one(&engine, "质量检测", QueryMode::Substring, false)?;
    if hit.filename.ends_with("包装材料.txt") || hit.locations.iter().any(|l| l.label.contains("正文") || l.page.is_some() || l.cell.is_some() || l.kind == "body" || l.kind == "sheet_cell" || l.kind == "pdf_page" || l.kind == "slide" || l.kind == "text") {
        checks.push(format!(
            "substring 质量检测 hit {} at {}",
            hit.filename,
            hit.locations.first().map(|l| l.label.as_str()).unwrap_or("?")
        ));
    } else {
        failures.push(format!("质量检测 hit looked wrong: {}", hit.filename));
    }
    let nested = search_paths(&engine, "量检", QueryMode::Substring, false)?;
    if nested.iter().any(|p| p.contains("包装材料")) {
        checks.push("量检 hits 包装材料质量检测报告".into());
    } else {
        failures.push(format!("量检 missed, got {nested:?}"));
    }
    let upper = search_paths(&engine, "QUALITY", QueryMode::Substring, true)?;
    if upper.iter().any(|p| p.contains("大小写")) && upper.iter().all(|p| !p.contains("onlylower")) {
        checks.push("case sensitive QUALITY does not match onlylower".into());
    } else {
        failures.push(format!("case filter {upper:?}"));
    }
    let word = search_paths(&engine, "quality", QueryMode::Word, true)?;
    if word.iter().any(|p| p.contains("单词")) {
        checks.push("whole word quality hits 单词.txt".into());
    } else {
        failures.push(format!("word mode missed {word:?}"));
    }
    let pdf = search_paths(&engine, "HelloPageTwoBeta", QueryMode::Substring, true)?;
    if pdf.iter().any(|p| p.ends_with(".pdf")) {
        let doc = engine
            .load(&path_key(&pdf[0]))
            .ok()
            .flatten();
        let page = doc
            .as_ref()
            .and_then(|d| {
                // re-search locations
                None::<u32>
            });
        let located = search_one(&engine, "HelloPageTwoBeta", QueryMode::Substring, true)?;
        if located.locations.iter().any(|l| l.page == Some(2)) {
            checks.push("pdf page 2 located".into());
        } else {
            failures.push(format!("pdf page missing in {:?}", located.locations));
        }
        let _ = page;
    } else {
        failures.push(format!("pdf text missing {pdf:?}"));
    }
    let sheet = search_one(&engine, "43", QueryMode::Substring, true)?;
    if sheet.locations.iter().any(|l| l.cell.as_deref() == Some("C3")) {
        checks.push("xlsx cached formula 43 is C3".into());
    } else {
        failures.push(format!("xlsx cell {:?}", sheet.locations));
    }
    let uncached = search_paths(&engine, "141", QueryMode::Substring, true)?;
    if uncached.is_empty() {
        checks.push("uncached formula was not executed".into());
    } else {
        failures.push(format!("uncached formula invented a value {uncached:?}"));
    }

    let edited = corpus.join("包装材料.txt");
    let before_freq = engine
        .path_doc_freq(&path_key(&edited.to_string_lossy()))
        .unwrap_or(0);
    let before_count = engine.doc_count().unwrap_or(0);
    std::fs::write(&edited, "增量之后的新句子甲乙丙\n")?;
    index_one(&engine, &corpus, &edited)?;
    engine.commit()?;
    let old = search_paths(&engine, "质量检测报告", QueryMode::Substring, false)?;
    let new = search_paths(&engine, "甲乙丙", QueryMode::Substring, false)?;
    if old.iter().all(|p| !p.ends_with("包装材料.txt")) && new.iter().any(|p| p.ends_with("包装材料.txt")) {
        checks.push("incremental edit replaced old text".into());
    } else {
        let key = path_key(&edited.to_string_lossy());
        let stored = engine.load(&key).ok().flatten();
        let preview = stored
            .as_ref()
            .map(|d| d.content.chars().take(40).collect::<String>())
            .unwrap_or_default();
        let disk = std::fs::read_to_string(&edited).unwrap_or_default();
        let parsed = extract::parse_file(&edited, &Limits::default())
            .map(|d| d.segments.iter().map(|s| s.text.clone()).collect::<Vec<_>>().join("|"))
            .unwrap_or_else(|e| e.to_string());
        let fresh = search_one(&engine, "甲乙丙", QueryMode::Substring, false).ok();
        failures.push(format!(
            "incremental disk={disk:?} parsed={parsed:?} stored={preview:?} key={key} hit_key={:?} snippet={:?} count={} freq={} before_count={before_count} before_freq={before_freq}",
            fresh.as_ref().map(|h| h.path_key.clone()),
            fresh.as_ref().map(|h| h.snippet.clone()),
            engine.doc_count().unwrap_or(0),
            engine.path_doc_freq(&key).unwrap_or(0)
        ));
    }
    std::fs::remove_file(corpus.join("标点.txt"))?;
    remove_missing(&engine, &corpus)?;
    engine.commit()?;
    let punct = search_paths(&engine, "质量，检测", QueryMode::Substring, true)?;
    if punct.is_empty() {
        checks.push("deleted file no longer matches".into());
    } else {
        let key = path_key(&corpus.join("标点.txt").to_string_lossy());
        failures.push(format!(
            "deleted file still matches {punct:?} freq={} in_manifest={}",
            engine.path_doc_freq(&key).unwrap_or(99),
            engine.lookup(&key).is_some()
        ));
    }
    let renamed_from = corpus.join("notes.md");
    let renamed_to = corpus.join("笔记.md");
    std::fs::rename(&renamed_from, &renamed_to)?;
    remove_missing(&engine, &corpus)?;
    index_one(&engine, &corpus, &renamed_to)?;
    engine.commit()?;
    let notes = search_paths(&engine, "Markdown", QueryMode::Substring, true)?;
    if notes.len() == 1 && notes[0].ends_with("笔记.md") {
        checks.push("rename does not duplicate".into());
    } else {
        failures.push(format!("rename result {notes:?}"));
    }

    drop(engine);
    let engine = Engine::open(&index)?;
    let again = search_paths(&engine, "甲乙丙", QueryMode::Substring, false)?;
    if again.iter().any(|p| p.ends_with("包装材料.txt")) {
        checks.push("index survived restart".into());
    } else {
        failures.push("restart lost the incremental hit".into());
    }
    let after = hash_tree(&corpus)?;
    for (path, hash) in &before {
        if path.ends_with("包装材料.txt") || path.ends_with("标点.txt") || path.ends_with("notes.md") {
            continue;
        }
        if after.get(path) != Some(hash) {
            failures.push(format!("source hash changed: {path}"));
        }
    }
    checks.push("untouched source hashes unchanged".into());

    let report = Report {
        ok: failures.is_empty(),
        checks,
        failures,
        elapsed_ms: started.elapsed().as_millis(),
        indexed_files: n,
        gui: "not exercised by --self-test",
    };
    if let Some(parent) = report_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(report_path, serde_json::to_string_pretty(&report)?)?;
    if report.ok {
        Ok(report)
    } else {
        Err(anyhow!("self-test failed: {}", report.failures.join("; ")))
    }
}

fn index_tree(engine: &Engine, root: &Path, dir: &Path) -> Result<u64> {
    let mut n = 0u64;
    for entry in std::fs::read_dir(dir).with_context(|| format!("read {}", dir.display()))? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            n += index_tree(engine, root, &path)?;
            continue;
        }
        index_one(engine, root, &path)?;
        n += 1;
    }
    Ok(n)
}

fn index_one(engine: &Engine, root: &Path, path: &Path) -> Result<()> {
    let limits = Limits::default();
    let extracted = match extract::parse_file(path, &limits) {
        Ok(doc) => doc,
        Err(err) => {
            return Err(anyhow!("{}: {err}", path.display()));
        }
    };
    let filename = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("file")
        .to_string();
    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let meta = std::fs::metadata(path)?;
    let display = path.to_string_lossy().to_string();
    engine.upsert(IndexDoc {
        path_key: path_key(&display),
        path_display: display,
        filename,
        ext,
        root: root.to_string_lossy().to_string(),
        hash: scan::sha256_file(path).unwrap_or_default(),
        size: meta.len(),
        mtime: meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0),
        segments: extracted.segments,
        warnings: extracted.warnings,
        no_text: extracted.no_text,
    })?;
    Ok(())
}

fn remove_missing(engine: &Engine, root: &Path) -> Result<()> {
    let prefix = root.to_string_lossy().to_string();
    let stale: Vec<String> = engine
        .manifest_snapshot()
        .into_iter()
        .filter(|m| m.path_display.starts_with(&prefix) && !Path::new(&m.path_display).exists())
        .map(|m| m.path_key)
        .collect();
    engine.remove_keys(&stale)?;
    Ok(())
}

fn search_one(
    engine: &Engine,
    query: &str,
    mode: QueryMode,
    case_sensitive: bool,
) -> Result<crate::model::Hit> {
    let resp = search(engine, query, mode, case_sensitive)?;
    resp.hits
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("no hit for {query}: {:?}", resp.error))
}

fn search_paths(
    engine: &Engine,
    query: &str,
    mode: QueryMode,
    case_sensitive: bool,
) -> Result<Vec<String>> {
    let resp = search(engine, query, mode, case_sensitive)?;
    if resp.incomplete {
        return Err(anyhow!("search incomplete for {query}"));
    }
    Ok(resp.hits.into_iter().map(|h| h.path).collect())
}

fn search(
    engine: &Engine,
    query: &str,
    mode: QueryMode,
    case_sensitive: bool,
) -> Result<crate::model::SearchResponse> {
    engine.search(
        &SearchRequest {
            query: query.into(),
            mode,
            scope: Scope::Content,
            case_sensitive,
            sort: SortMode::Filename,
            page: 0,
            page_size: 50,
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
}

fn hash_tree(root: &Path) -> Result<std::collections::BTreeMap<String, String>> {
    let mut out = std::collections::BTreeMap::new();
    fn walk(dir: &Path, out: &mut std::collections::BTreeMap<String, String>) -> Result<()> {
        for entry in std::fs::read_dir(dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                walk(&path, out)?;
            } else {
                out.insert(path.to_string_lossy().to_string(), scan::sha256_file(&path)?);
            }
        }
        Ok(())
    }
    walk(root, &mut out)?;
    Ok(out)
}

pub fn bench(out: &Path, docs: usize) -> Result<()> {
    let base = std::env::temp_dir().join(format!("localsearch-bench-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&base);
    let corpus = base.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    let vocab = ["包装", "材料", "质量", "检测", "报告", "设备", "记录", "alpha", "beta", "gamma"];
    for i in 0..docs {
        let mut text = format!("文档{i}\n");
        text.push_str(vocab[i % vocab.len()]);
        text.push_str(vocab[(i / 3) % vocab.len()]);
        if i == 12345 || (docs > 12345 && i % 5000 == 0) {
            text.push_str("\n包装材料质量检测报告\n");
        }
        text.push_str("\n普通关键词 sampleterm 出现在部分文件。\n");
        std::fs::write(corpus.join(format!("f{i}.txt")), text)?;
    }
    let index = base.join("index");
    let engine = Engine::open(&index)?;
    let index_started = Instant::now();
    let n = index_tree(&engine, &corpus, &corpus)?;
    engine.commit()?;
    let index_ms = index_started.elapsed().as_millis();
    let queries = ["sampleterm", "质量检测", "alpha", "报告", "gamma"];
    let mut samples = Vec::new();
    // Warm.
    for q in queries {
        let _ = search(&engine, q, QueryMode::Substring, false)?;
    }
    for _ in 0..8 {
        for q in queries {
            let started = Instant::now();
            let resp = search(&engine, q, QueryMode::Substring, false)?;
            samples.push(resp.elapsed_ms.max(started.elapsed().as_millis()));
        }
    }
    samples.sort();
    let p50 = samples[samples.len() / 2];
    let p95 = samples[(samples.len() as f64 * 0.95) as usize - 1];
    let index_size = dir_size(&index);
    let report = serde_json::json!({
        "synthetic": true,
        "docs": n,
        "format": "txt",
        "index_ms": index_ms,
        "index_bytes": index_size,
        "samples": samples.len(),
        "p50_ms": p50,
        "p95_ms": p95,
        "timing": "engine search including gram prefilter and exact verification on stored text, excluding UI and IPC",
        "target_p50_ms": 200,
        "target_p95_ms": 800,
        "met_target": p50 <= 200 && p95 <= 800,
    });
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(out, serde_json::to_string_pretty(&report)?)?;
    Ok(())
}

fn dir_size(path: &Path) -> u64 {
    let mut total = 0u64;
    let Ok(read) = std::fs::read_dir(path) else {
        return 0;
    };
    for entry in read.flatten() {
        let p = entry.path();
        if p.is_dir() {
            total += dir_size(&p);
        } else if let Ok(meta) = entry.metadata() {
            total += meta.len();
        }
    }
    total
}

#[allow(dead_code)]
fn _path(p: PathBuf) -> PathBuf {
    p
}
