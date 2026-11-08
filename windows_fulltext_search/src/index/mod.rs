//! Persistent Tantivy index.
//!
//! Substring prefilters are overlapping character bigrams (unigrams when the
//! needle is one character) of the case-folded text. That set is a superset of
//! the true hits: a real contiguous match always contains those grams. Exact
//! verification then runs on the stored original NFC text. `NOT` is applied
//! during that verification, not as a lossy MustNot against the gram superset.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{anyhow, Context, Result};
use tantivy::query::{AllQuery, BooleanQuery, Occur, Query, TermQuery};
use tantivy::schema::{IndexRecordOption, Schema, TextFieldIndexing, TextOptions, Value, FAST, INDEXED, STORED, STRING};
use tantivy::tokenizer::{LowerCaser, NgramTokenizer, SimpleTokenizer, TextAnalyzer};
use tantivy::{DocAddress, Index, IndexReader, IndexWriter, TantivyDocument, Term, TERMINATED};
use tantivy::query::EnableScoring;

use crate::matchdoc::{self, eval_field};
use crate::model::{
    join_segments, Hit, Scope, SearchRequest, SearchResponse, Segment, SortMode, StoredDoc,
};
use crate::query::{self, regex_plan, Ast, RegexPlan};
use crate::textutil::{self, Span};

struct Fields {
    path_key: tantivy::schema::Field,
    path_display: tantivy::schema::Field,
    filename: tantivy::schema::Field,
    ext: tantivy::schema::Field,
    root: tantivy::schema::Field,
hash: tantivy::schema::Field,
        size: tantivy::schema::Field,
    mtime: tantivy::schema::Field,
    content: tantivy::schema::Field,
    content_ng: tantivy::schema::Field,
    name_ng: tantivy::schema::Field,
    content_words: tantivy::schema::Field,
    content_words_ci: tantivy::schema::Field,
    name_words: tantivy::schema::Field,
    name_words_ci: tantivy::schema::Field,
    segments: tantivy::schema::Field,
    warnings: tantivy::schema::Field,
    no_text: tantivy::schema::Field,
    generation: tantivy::schema::Field,
}

pub struct IndexDoc {
    pub path_key: String,
    pub path_display: String,
    pub filename: String,
    pub ext: String,
    pub root: String,
    pub hash: String,
    pub size: u64,
    pub mtime: i64,
    pub segments: Vec<Segment>,
    pub warnings: Vec<String>,
    pub no_text: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Meta {
    pub path_key: String,
    pub path_display: String,
    pub filename: String,
    pub ext: String,
    pub root: String,
    pub hash: String,
    pub size: u64,
    pub mtime: i64,
    pub failed: bool,
    /// Bumped on every rewrite of this path. Search ignores older copies that
    /// a term delete failed to remove.
    #[serde(default)]
    pub generation: u64,
}

pub struct Engine {
    dir: PathBuf,
    index: Index,
    reader: IndexReader,
    writer: std::sync::Mutex<IndexWriter>,
    fields: Fields,
    manifest: std::sync::RwLock<HashMap<String, Meta>>,
}

impl Engine {
    pub fn open(dir: &Path) -> Result<Self> {
        std::fs::create_dir_all(dir)?;
        let schema = build_schema();
        let meta_path = dir.join("meta.json");
        let index = if meta_path.exists() {
            Index::open_in_dir(dir).context("打开已有索引失败，可删除索引目录后重建")?
        } else {
            Index::create_in_dir(dir, schema.clone())?
        };
        register_tokenizers(&index);
        let fields = fields_of(index.schema())?;
        // One indexing thread keeps each commit in a single segment. With several
// worker threads, term deletes sometimes do not hit every segment.
let writer = index.writer_with_num_threads(1, 128 * 1024 * 1024)?;
        writer.set_merge_policy(Box::new(tantivy::merge_policy::NoMergePolicy));
        let reader = index.reader()?;
        let manifest_path = dir.join("manifest.json");
        let manifest = if manifest_path.exists() {
            load_manifest(&manifest_path).unwrap_or_default()
        } else {
            HashMap::new()
        };
        let engine = Self {
            dir: dir.to_path_buf(),
            index,
            reader,
            writer: std::sync::Mutex::new(writer),
            fields,
            manifest: std::sync::RwLock::new(manifest),
        };
        let docs = engine.doc_count().unwrap_or(0);
        if !manifest_path.exists() && docs > 0 {
            if let Ok(rebuilt) = engine.rebuild_manifest() {
                if let Ok(mut guard) = engine.manifest.write() {
                    *guard = rebuilt;
                }
                let _ = engine.save_manifest();
            }
        }
        Ok(engine)
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    pub fn doc_count(&self) -> Result<u64> {
        self.reader.reload()?;
        Ok(self.reader.searcher().num_docs())
    }

    pub fn path_doc_freq(&self, path_key: &str) -> Result<u64> {
        self.reader.reload()?;
        let term = Term::from_field_text(self.fields.path_key, path_key);
        Ok(self.reader.searcher().doc_freq(&term)?)
    }

    pub fn segment_count(&self) -> Result<usize> {
        self.reader.reload()?;
        Ok(self.reader.searcher().segment_readers().len())
    }

    pub fn clear_all(&self) -> Result<()> {
        let writer = self.writer.lock().unwrap_or_else(|e| e.into_inner());
        writer.delete_all_documents()?;
        drop(writer);
        self.commit()?;
        Ok(())
    }

    pub fn manifest_snapshot(&self) -> Vec<Meta> {
        self.manifest
            .read()
            .map(|g| g.values().cloned().collect())
            .unwrap_or_default()
    }

    pub fn lookup(&self, path_key: &str) -> Option<Meta> {
        self.manifest
            .read()
            .ok()
            .and_then(|g| g.get(path_key).cloned())
    }

    pub fn upsert(&self, doc: IndexDoc) -> Result<()> {
        let (content, _) = join_segments(&doc.segments);
        let content_nfc = textutil::nfc(&content);
        let folded = textutil::fold_case(&content_nfc);
        let name_nfc = textutil::nfc(&doc.filename);
        let name_folded = textutil::fold_case(&name_nfc);
        let segments_json = serde_json::to_string(&doc.segments)?;
        let warnings = doc.warnings.join("\n");
        let mut tantivy_doc = TantivyDocument::default();
        tantivy_doc.add_text(self.fields.path_key, &doc.path_key);
        tantivy_doc.add_text(self.fields.path_display, &doc.path_display);
        tantivy_doc.add_text(self.fields.filename, &name_nfc);
        tantivy_doc.add_text(self.fields.ext, &doc.ext);
        tantivy_doc.add_text(self.fields.root, &doc.root);
        tantivy_doc.add_text(self.fields.hash, &doc.hash);
        tantivy_doc.add_u64(self.fields.size, doc.size);
        tantivy_doc.add_i64(self.fields.mtime, doc.mtime);
        tantivy_doc.add_text(self.fields.content, &content_nfc);
        tantivy_doc.add_text(self.fields.content_ng, &folded);
        tantivy_doc.add_text(self.fields.name_ng, &name_folded);
        tantivy_doc.add_text(self.fields.content_words, &content_nfc);
        tantivy_doc.add_text(self.fields.content_words_ci, &content_nfc);
        tantivy_doc.add_text(self.fields.name_words, &name_nfc);
        tantivy_doc.add_text(self.fields.name_words_ci, &name_nfc);
        tantivy_doc.add_text(self.fields.segments, &segments_json);
        tantivy_doc.add_text(self.fields.warnings, &warnings);
        tantivy_doc.add_u64(self.fields.no_text, if doc.no_text { 1 } else { 0 });
        let generation = self
            .lookup(&doc.path_key)
            .map(|meta| meta.generation.saturating_add(1))
            .unwrap_or(1);
        tantivy_doc.add_u64(self.fields.generation, generation);
        let mut writer = self.writer.lock().unwrap_or_else(|e| e.into_inner());
        if generation > 1 {
            writer.delete_term(Term::from_field_text(self.fields.path_key, &doc.path_key));
        }
        writer.add_document(tantivy_doc)?;
        drop(writer);
        if let Ok(mut guard) = self.manifest.write() {
            guard.insert(
                doc.path_key.clone(),
                Meta {
                    path_key: doc.path_key,
                    path_display: doc.path_display,
                    filename: doc.filename,
                    ext: doc.ext,
                    root: doc.root,
                    hash: doc.hash,
                    size: doc.size,
                    mtime: doc.mtime,
                    failed: false,
                    generation,
                },
            );
        }
        Ok(())
    }

    pub fn mark_failed(&self, meta: Meta) -> Result<()> {
        let failed = meta.clone();
        self.upsert(IndexDoc {
            path_key: meta.path_key,
            path_display: meta.path_display,
            filename: meta.filename,
            ext: meta.ext,
            root: meta.root,
            hash: meta.hash,
            size: meta.size,
            mtime: meta.mtime,
            segments: Vec::new(),
            warnings: vec!["内容未能抽取".into()],
            no_text: true,
        })?;
        if let Ok(mut guard) = self.manifest.write() {
            if let Some(slot) = guard.get_mut(&failed.path_key) {
                slot.failed = true;
            }
        }
        Ok(())
    }

    pub fn remove_keys(&self, keys: &[String]) -> Result<()> {
        let mut writer = self.writer.lock().unwrap_or_else(|e| e.into_inner());
        for key in keys {
            writer.delete_term(Term::from_field_text(self.fields.path_key, key));
        }
        drop(writer);
        if let Ok(mut guard) = self.manifest.write() {
            for key in keys {
                guard.remove(key);
            }
        }
        Ok(())
    }

    pub fn remove_root(&self, root: &str) -> Result<()> {
        let keys: Vec<String> = self
            .manifest
            .read()
            .map(|g| {
                g.values()
                    .filter(|m| m.root == root)
                    .map(|m| m.path_key.clone())
                    .collect()
            })
            .unwrap_or_default();
        self.remove_keys(&keys)?;
        self.commit()
    }

    pub fn commit(&self) -> Result<()> {
        let mut writer = self.writer.lock().unwrap_or_else(|e| e.into_inner());
        writer.commit()?;
        drop(writer);
        self.reader.reload()?;
        self.save_manifest()?;
        Ok(())
    }

    pub fn load(&self, path_key: &str) -> Result<Option<StoredDoc>> {
        self.reader.reload()?;
        let searcher = self.reader.searcher();
        let term = Term::from_field_text(self.fields.path_key, path_key);
        let query = TermQuery::new(term, IndexRecordOption::Basic);
        let weight = query.weight(EnableScoring::disabled_from_searcher(&searcher))?;
        for (ord, reader) in searcher.segment_readers().iter().enumerate() {
            let mut scorer = weight.scorer(reader, 1.0)?;
            let doc_id = scorer.doc();
            if doc_id != TERMINATED {
                let doc: TantivyDocument = searcher.doc(DocAddress::new(ord as u32, doc_id))?;
                return Ok(Some(stored_from_doc(&self.fields, &doc, path_key)));
            }
        }
        Ok(None)
    }

    pub fn search(&self, req: &SearchRequest, stop: &dyn Fn() -> bool) -> Result<SearchResponse> {
        let started = Instant::now();
        let ast = match query::parse_query(&req.query, req.mode) {
            Ok(v) => v,
            Err(err) => return Ok(SearchResponse::failed(err)),
        };
        if ast.is_none() {
            return Ok(self.list_filtered(req, started));
        }
        let ast = ast.unwrap();
        if let Err(err) = validate_regex(&ast) {
            return Ok(SearchResponse::failed(err));
        }
        let unaccelerated = query::ast_has_unaccelerated_regex(&ast, req.case_sensitive);
        self.reader.reload()?;
        let searcher = self.reader.searcher();
        let pre = build_prefilter(&self.fields, &ast, req)?;
        let weight = pre.weight(EnableScoring::disabled_from_searcher(&searcher))?;
        let mut addresses = Vec::new();
        for (ord, reader) in searcher.segment_readers().iter().enumerate() {
            if stop() {
                break;
            }
            let mut scorer = weight.scorer(reader, 1.0)?;
            let mut doc_id = scorer.doc();
            while doc_id != TERMINATED {
                addresses.push(DocAddress::new(ord as u32, doc_id));
                doc_id = scorer.advance();
            }
        }
        let candidates = addresses.len() as u64;
        let live: HashMap<String, u64> = self
            .manifest
            .read()
            .map(|guard| {
                guard
                    .iter()
                    .map(|(key, meta)| (key.clone(), meta.generation))
                    .collect()
            })
            .unwrap_or_default();
        let mut verified = Vec::new();
        let mut scanned = 0u64;
        let mut incomplete = false;
        let mut cancelled = false;
        for addr in addresses {
            if stop() {
                cancelled = true;
                incomplete = true;
                break;
            }
            if let Some(limit) = req.deadline_ms {
                if started.elapsed().as_millis() > limit {
                    incomplete = true;
                    break;
                }
            }
            scanned += 1;
            let doc: TantivyDocument = searcher.doc(addr)?;
            let stored = stored_from_doc(&self.fields, &doc, "");
            if live.get(&stored.path_key) != Some(&stored.generation) {
                continue;
            }
            if !passes_filters(req, &stored) {
                continue;
            }
            match verify(req, &ast, &stored) {
                Ok(Some(hit)) => verified.push(hit),
                Ok(None) => {}
                Err(err) => {
                    return Ok(SearchResponse {
                        error: Some(err),
                        unaccelerated_regex: unaccelerated,
                        elapsed_ms: started.elapsed().as_millis(),
                        candidates,
                        scanned,
                        incomplete: true,
                        ..SearchResponse::failed("")
                    });
                }
            }
        }
        sort_hits(&mut verified, req.sort);
        let total = verified.len() as u64;
        let page_size = req.page_size.max(1);
        let start = req.page.saturating_mul(page_size);
        let hits = verified.into_iter().skip(start).take(page_size).collect();
        let mut warning = None;
        if unaccelerated {
            warning = Some(
                "这个正则抽不出必须出现的字面量，已在索引里保存的文本上逐份验证，没有重新扫描原文件。这种查询不能保证被倒排索引加速。"
                    .into(),
            );
        }
        if incomplete {
            let extra = if cancelled {
                "查询已取消，下面不是完整结果。"
            } else {
                "查询超时，下面不是完整结果。收窄关键词或取消正则里的任意匹配后重试。"
            };
            warning = Some(match warning {
                Some(w) => format!("{w} {extra}"),
                None => extra.into(),
            });
        }
        Ok(SearchResponse {
            hits,
            total,
            scanned,
            candidates,
            incomplete,
            cancelled,
            unaccelerated_regex: unaccelerated,
            elapsed_ms: started.elapsed().as_millis(),
            warning,
            error: None,
        })
    }

    fn list_filtered(&self, req: &SearchRequest, started: Instant) -> SearchResponse {
        let metas = self.manifest_snapshot();
        let mut hits = Vec::new();
        for meta in metas {
            if meta.failed && req.scope == Scope::Content && !req.query.trim().is_empty() {
                continue;
            }
            let stored = StoredDoc {
                path_key: meta.path_key.clone(),
                path: meta.path_display.clone(),
                filename: meta.filename.clone(),
                ext: meta.ext.clone(),
                root: meta.root.clone(),
                hash: meta.hash.clone(),
                size: meta.size,
                mtime: meta.mtime,
                generation: meta.generation,
                content: String::new(),
                segments: Vec::new(),
                warnings: Vec::new(),
                no_text: false,
            };
            if !passes_filters(req, &stored) {
                continue;
            }
            hits.push(Hit {
                path_key: meta.path_key,
                path: meta.path_display,
                filename: meta.filename,
                ext: meta.ext,
                size: meta.size,
                mtime: meta.mtime,
                score: 0,
                snippet: String::new(),
                snippet_spans: Vec::new(),
                locations: Vec::new(),
                match_count: 0,
                in_filename: false,
                in_content: false,
            });
        }
        sort_hits(&mut hits, req.sort);
        let total = hits.len() as u64;
        let page_size = req.page_size.max(1);
        let start = req.page.saturating_mul(page_size);
        let page = hits.into_iter().skip(start).take(page_size).collect();
        SearchResponse {
            hits: page,
            total,
            scanned: total,
            candidates: total,
            incomplete: false,
            cancelled: false,
            unaccelerated_regex: false,
            elapsed_ms: started.elapsed().as_millis(),
            warning: None,
            error: None,
        }
    }

    fn save_manifest(&self) -> Result<()> {
        let list = self.manifest_snapshot();
        let text = serde_json::to_string(&list)?;
        let tmp = self.dir.join("manifest.json.tmp");
        let final_path = self.dir.join("manifest.json");
        std::fs::write(&tmp, text)?;
        std::fs::rename(tmp, final_path)?;
        Ok(())
    }

    fn rebuild_manifest(&self) -> Result<HashMap<String, Meta>> {
        self.reader.reload()?;
        let searcher = self.reader.searcher();
        let weight = AllQuery.weight(EnableScoring::disabled_from_searcher(&searcher))?;
        let mut map = HashMap::new();
        for (ord, reader) in searcher.segment_readers().iter().enumerate() {
            let mut scorer = weight.scorer(reader, 1.0)?;
            let mut doc_id = scorer.doc();
            while doc_id != TERMINATED {
                let doc: TantivyDocument = searcher.doc(DocAddress::new(ord as u32, doc_id))?;
                let stored = stored_from_doc(&self.fields, &doc, "");
                if map.get(&stored.path_key).is_some_and(|meta: &Meta| meta.generation >= stored.generation) {
                    doc_id = scorer.advance();
                    continue;
                }
                map.insert(
                    stored.path_key.clone(),
                    Meta {
                        path_key: stored.path_key,
                        path_display: stored.path,
                        filename: stored.filename,
                        ext: stored.ext,
                        root: stored.root,
                        hash: stored.hash,
                        size: stored.size,
                        mtime: stored.mtime,
                        failed: stored.warnings.iter().any(|w| w.contains("未能抽取")),
                        generation: stored.generation,
                    },
                );
                doc_id = scorer.advance();
            }
        }
        Ok(map)
    }
}

fn validate_regex(ast: &Ast) -> Result<(), String> {
    match ast {
        Ast::Regex(pat) => {
            regex::RegexBuilder::new(pat)
                .size_limit(8 * 1024 * 1024)
                .build()
                .map_err(|e| format!("正则无法编译：{e}"))?;
            Ok(())
        }
        Ast::And(xs) | Ast::Or(xs) => {
            for x in xs {
                validate_regex(x)?;
            }
            Ok(())
        }
        Ast::Not(x) => validate_regex(x),
        _ => Ok(()),
    }
}

fn verify(req: &SearchRequest, ast: &Ast, stored: &StoredDoc) -> Result<Option<Hit>, String> {
    let content_hit = if req.scope != Scope::Filename {
        eval_field(ast, &stored.content, req.case_sensitive)?
    } else {
        crate::matchdoc::FieldHit {
            matched: false,
            spans: Vec::new(),
            error: None,
        }
    };
    let name_hit = if req.scope != Scope::Content {
        eval_field(ast, &stored.filename, req.case_sensitive)?
    } else {
        crate::matchdoc::FieldHit {
            matched: false,
            spans: Vec::new(),
            error: None,
        }
    };
    let ok = match req.scope {
        Scope::Content => content_hit.matched,
        Scope::Filename => name_hit.matched,
        Scope::Mixed => content_hit.matched || name_hit.matched,
    };
    if !ok {
        return Ok(None);
    }
    let (_, ranges) = join_segments(&stored.segments);
    let mut locations = matchdoc::locations_for(&content_hit.spans, &stored.segments, &ranges, 32);
    if name_hit.matched {
        locations.insert(
            0,
            crate::model::Location {
                label: "文件名".into(),
                kind: "filename".into(),
                start: name_hit.spans.first().map(|s| s.start).unwrap_or(0),
                end: name_hit.spans.first().map(|s| s.end).unwrap_or(0),
                page: None,
                sheet: None,
                cell: None,
                text: stored.filename.clone(),
            },
        );
    }
    let (snippet, snippet_spans) = if let Some(span) = content_hit.spans.first() {
        textutil::snippet(&stored.content, *span, 40)
    } else if name_hit.matched {
        (stored.filename.clone(), name_hit.spans.iter().map(|s| (s.start, s.end)).collect())
    } else {
        (String::new(), Vec::new())
    };
    let score = matchdoc::score_hit(name_hit.matched, &content_hit.spans);
    Ok(Some(Hit {
        path_key: stored.path_key.clone(),
        path: stored.path.clone(),
        filename: stored.filename.clone(),
        ext: stored.ext.clone(),
        size: stored.size,
        mtime: stored.mtime,
        score,
        snippet,
        snippet_spans,
        locations,
        match_count: (content_hit.spans.len() + name_hit.spans.len()) as u32,
        in_filename: name_hit.matched,
        in_content: content_hit.matched,
    }))
}

fn passes_filters(req: &SearchRequest, stored: &StoredDoc) -> bool {
    if !req.exts.is_empty()
        && !req
            .exts
            .iter()
            .any(|e| e.eq_ignore_ascii_case(&stored.ext))
    {
        return false;
    }
    if let Some(min) = req.min_size {
        if stored.size < min {
            return false;
        }
    }
    if let Some(max) = req.max_size {
        if stored.size > max {
            return false;
        }
    }
    if let Some(min) = req.min_mtime {
        if stored.mtime < min {
            return false;
        }
    }
    if let Some(max) = req.max_mtime {
        if stored.mtime > max {
            return false;
        }
    }
    if !req.path_contains.trim().is_empty() {
        let needle = textutil::fold_case(&textutil::nfc(req.path_contains.trim()));
        let hay = textutil::fold_case(&textutil::nfc(&stored.path));
        if !hay.contains(&needle) {
            return false;
        }
    }
    true
}

fn sort_hits(hits: &mut [Hit], sort: SortMode) {
    match sort {
        SortMode::Relevance => hits.sort_by(|a, b| {
            b.score
                .cmp(&a.score)
                .then_with(|| b.mtime.cmp(&a.mtime))
                .then_with(|| a.filename.to_lowercase().cmp(&b.filename.to_lowercase()))
        }),
        SortMode::Mtime => hits.sort_by(|a, b| {
            b.mtime
                .cmp(&a.mtime)
                .then_with(|| a.filename.to_lowercase().cmp(&b.filename.to_lowercase()))
        }),
        SortMode::Filename => {
            hits.sort_by(|a, b| a.filename.to_lowercase().cmp(&b.filename.to_lowercase()))
        }
    }
}

fn build_prefilter(fields: &Fields, ast: &Ast, req: &SearchRequest) -> Result<Box<dyn Query>> {
    let content = req.scope != Scope::Filename;
    let name = req.scope != Scope::Content;
    let mut parts: Vec<Box<dyn Query>> = Vec::new();
    if content {
        parts.push(prefilter_field(
            ast,
            req.case_sensitive,
            fields.content_ng,
            fields.content_words,
            fields.content_words_ci,
        )?);
    }
    if name {
        parts.push(prefilter_field(
            ast,
            req.case_sensitive,
            fields.name_ng,
            fields.name_words,
            fields.name_words_ci,
        )?);
    }
    Ok(any_of(parts))
}

fn prefilter_field(
    ast: &Ast,
    case_sensitive: bool,
    ng: tantivy::schema::Field,
    words: tantivy::schema::Field,
    words_ci: tantivy::schema::Field,
) -> Result<Box<dyn Query>> {
    // NOT is intentionally ignored here. Dropping candidates with a gram-level
    // MustNot would reject documents that only false-positive the gram filter.
    match ast {
        Ast::Not(_) => Ok(Box::new(AllQuery)),
        Ast::Literal { text, .. } => Ok(gram_query(ng, text)),
        Ast::Word(word) => {
            let (field, term) = if case_sensitive {
                (words, word.clone())
            } else {
                (words_ci, textutil::fold_case(word))
            };
            Ok(Box::new(TermQuery::new(
                Term::from_field_text(field, &term),
                IndexRecordOption::Basic,
            )))
        }
        Ast::Regex(pat) => regex_query(ng, pat, case_sensitive).map_err(|err| anyhow!(err)),
        Ast::And(xs) => {
            let mut parts = Vec::new();
            for x in xs {
                if matches!(x, Ast::Not(_)) {
                    continue;
                }
                parts.push(prefilter_field(x, case_sensitive, ng, words, words_ci)?);
            }
            Ok(all_of(parts))
        }
        Ast::Or(xs) => {
            let mut parts = Vec::new();
            for x in xs {
                parts.push(prefilter_field(x, case_sensitive, ng, words, words_ci)?);
            }
            Ok(any_of(parts))
        }
    }
}

fn regex_query(
    ng: tantivy::schema::Field,
    pat: &str,
    case_sensitive: bool,
) -> Result<Box<dyn Query>, String> {
    let plan = regex_plan(pat)?;
    let fold = |s: &str| {
        if case_sensitive {
            // Still fold for the gram prefilter. Verification keeps case.
            textutil::fold_case(&textutil::nfc(s))
        } else {
            textutil::fold_case(&textutil::nfc(s))
        }
    };
    match plan {
        RegexPlan::Literal(s) => Ok(gram_query(ng, &fold(&s))),
        RegexPlan::Any(list) => Ok(any_of(
            list.into_iter().map(|s| gram_query(ng, &fold(&s))).collect(),
        )),
        RegexPlan::Scan => Ok(Box::new(AllQuery)),
    }
}

fn gram_query(field: tantivy::schema::Field, literal: &str) -> Box<dyn Query> {
    let folded = textutil::fold_case(&textutil::nfc(literal));
    let grams = textutil::ngrams(&folded);
    if grams.is_empty() {
        return Box::new(AllQuery);
    }
    let parts = grams
        .into_iter()
        .map(|g| {
            Box::new(TermQuery::new(
                Term::from_field_text(field, &g),
                IndexRecordOption::Basic,
            )) as Box<dyn Query>
        })
        .collect();
    all_of(parts)
}

fn all_of(parts: Vec<Box<dyn Query>>) -> Box<dyn Query> {
    match parts.len() {
        0 => Box::new(AllQuery),
        1 => parts.into_iter().next().unwrap(),
        _ => {
            let clauses = parts.into_iter().map(|q| (Occur::Must, q)).collect();
            Box::new(BooleanQuery::new(clauses))
        }
    }
}

fn any_of(parts: Vec<Box<dyn Query>>) -> Box<dyn Query> {
    match parts.len() {
        0 => Box::new(AllQuery),
        1 => parts.into_iter().next().unwrap(),
        _ => {
            let clauses = parts.into_iter().map(|q| (Occur::Should, q)).collect();
            Box::new(BooleanQuery::new(clauses))
        }
    }
}

fn stored_from_doc(fields: &Fields, doc: &TantivyDocument, fallback_key: &str) -> StoredDoc {
    let path_key = text_field(doc, fields.path_key).unwrap_or_else(|| fallback_key.to_string());
    let segments = text_field(doc, fields.segments)
        .and_then(|s| serde_json::from_str::<Vec<Segment>>(&s).ok())
        .unwrap_or_default();
    let (joined, _) = join_segments(&segments);
    let content = text_field(doc, fields.content).unwrap_or(joined);
    StoredDoc {
        path_key,
        path: text_field(doc, fields.path_display).unwrap_or_default(),
        filename: text_field(doc, fields.filename).unwrap_or_default(),
        ext: text_field(doc, fields.ext).unwrap_or_default(),
        root: text_field(doc, fields.root).unwrap_or_default(),
        hash: text_field(doc, fields.hash).unwrap_or_default(),
        size: u64_field(doc, fields.size),
        mtime: i64_field(doc, fields.mtime),
        content,
        segments,
        warnings: text_field(doc, fields.warnings)
            .map(|s| {
                s.lines()
                    .filter(|l| !l.is_empty())
                    .map(|l| l.to_string())
                    .collect()
            })
            .unwrap_or_default(),
        no_text: u64_field(doc, fields.no_text) == 1,
        generation: u64_field(doc, fields.generation),
    }
}

fn text_field(doc: &TantivyDocument, field: tantivy::schema::Field) -> Option<String> {
    doc.get_first(field).and_then(|v| v.as_str().map(|s| s.to_string()))
}

fn u64_field(doc: &TantivyDocument, field: tantivy::schema::Field) -> u64 {
    doc.get_first(field).and_then(|v| v.as_u64()).unwrap_or(0)
}

fn i64_field(doc: &TantivyDocument, field: tantivy::schema::Field) -> i64 {
    doc.get_first(field).and_then(|v| v.as_i64()).unwrap_or(0)
}

fn load_manifest(path: &Path) -> Result<HashMap<String, Meta>> {
    let text = std::fs::read_to_string(path)?;
    let list: Vec<Meta> = serde_json::from_str(&text)?;
    Ok(list.into_iter().map(|m| (m.path_key.clone(), m)).collect())
}

fn build_schema() -> Schema {
    let mut builder = Schema::builder();
    let stored_text = TextOptions::default().set_stored();
    let ng = TextOptions::default().set_indexing_options(
        TextFieldIndexing::default()
            .set_tokenizer("ng12")
            .set_index_option(IndexRecordOption::WithFreqs),
    );
    let words = TextOptions::default().set_indexing_options(
        TextFieldIndexing::default()
            .set_tokenizer("words_cs")
            .set_index_option(IndexRecordOption::Basic),
    );
    let words_ci = TextOptions::default().set_indexing_options(
        TextFieldIndexing::default()
            .set_tokenizer("words_ci")
            .set_index_option(IndexRecordOption::Basic),
    );
    builder.add_text_field("path_key", STRING | STORED);
    builder.add_text_field("path_display", stored_text.clone());
    builder.add_text_field("filename", STRING | STORED);
    builder.add_text_field("ext", STRING | STORED | FAST);
    builder.add_text_field("root", STRING | STORED);
builder.add_text_field("hash", STRING | STORED);
        builder.add_u64_field("size", INDEXED | STORED | FAST);
    builder.add_i64_field("mtime", INDEXED | STORED | FAST);
    builder.add_text_field("content", stored_text.clone());
    builder.add_text_field("content_ng", ng.clone());
    builder.add_text_field("name_ng", ng);
    builder.add_text_field("content_words", words.clone());
    builder.add_text_field("content_words_ci", words_ci.clone());
    builder.add_text_field("name_words", words);
    builder.add_text_field("name_words_ci", words_ci);
    builder.add_text_field("segments", stored_text.clone());
    builder.add_text_field("warnings", stored_text);
    builder.add_u64_field("no_text", STORED);
    builder.add_u64_field("generation", STORED);
    let _ = FAST;
    builder.build()
}

fn fields_of(schema: Schema) -> Result<Fields> {
    let f = |name: &str| {
        schema
            .get_field(name)
            .map_err(|_| anyhow!("索引缺少字段 {name}，请删除索引后重建"))
    };
    Ok(Fields {
        path_key: f("path_key")?,
        path_display: f("path_display")?,
        filename: f("filename")?,
        ext: f("ext")?,
        root: f("root")?,
        hash: f("hash")?,
        size: f("size")?,
        mtime: f("mtime")?,
        content: f("content")?,
        content_ng: f("content_ng")?,
        name_ng: f("name_ng")?,
        content_words: f("content_words")?,
        content_words_ci: f("content_words_ci")?,
        name_words: f("name_words")?,
        name_words_ci: f("name_words_ci")?,
        segments: f("segments")?,
        warnings: f("warnings")?,
        no_text: f("no_text")?,
        generation: f("generation")?,
    })
}

fn register_tokenizers(index: &Index) {
    let ng = TextAnalyzer::builder(NgramTokenizer::all_ngrams(1, 2).expect("ngram"))
        .build();
    let words_cs = TextAnalyzer::builder(SimpleTokenizer::default()).build();
    let words_ci = TextAnalyzer::builder(SimpleTokenizer::default())
        .filter(LowerCaser)
        .build();
    index.tokenizers().register("ng12", ng);
    index.tokenizers().register("words_cs", words_cs);
    index.tokenizers().register("words_ci", words_ci);
}

#[cfg(test)]
mod replace_tests {
    use super::*;
    use crate::model::{QueryMode, Scope, SearchRequest, Segment, SortMode};

    #[test]
    fn replace_removes_previous_text() {
        let dir = std::env::temp_dir().join(format!("ls-replace-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let engine = Engine::open(&dir).unwrap();
        let segment = |text: &str| Segment {
            kind: "text".into(),
            label: "正文".into(),
            text: text.into(),
            page: None,
            sheet: None,
            cell: None,
        };
        engine
            .upsert(IndexDoc {
                path_key: "/tmp/包装材料.txt".into(),
                path_display: "/tmp/包装材料.txt".into(),
                filename: "包装材料.txt".into(),
                ext: "txt".into(),
                root: "/tmp".into(),
                hash: "1".into(),
                size: 1,
                mtime: 1,
                segments: vec![segment("旧句子质量检测")],
                warnings: Vec::new(),
                no_text: false,
            })
            .unwrap();
        engine.commit().unwrap();
        assert_eq!(engine.doc_count().unwrap(), 1);
        for i in 0..30 {
            engine
                .upsert(IndexDoc {
                    path_key: format!("/tmp/other{i}.txt"),
                    path_display: format!("/tmp/other{i}.txt"),
                    filename: format!("other{i}.txt"),
                    ext: "txt".into(),
                    root: "/tmp".into(),
                    hash: format!("h{i}"),
                    size: 1,
                    mtime: 1,
                    segments: vec![segment("其他内容")],
                    warnings: Vec::new(),
                    no_text: false,
                })
                .unwrap();
        }
        engine.commit().unwrap();
        engine
            .upsert(IndexDoc {
                path_key: "/tmp/包装材料.txt".into(),
                path_display: "/tmp/包装材料.txt".into(),
                filename: "包装材料.txt".into(),
                ext: "txt".into(),
                root: "/tmp".into(),
                hash: "2".into(),
                size: 2,
                mtime: 2,
                segments: vec![segment("新句子甲乙丙")],
                warnings: Vec::new(),
                no_text: false,
            })
            .unwrap();
        engine.commit().unwrap();
        assert_eq!(engine.doc_count().unwrap(), 31, "document count changed");
        let req = |q: &str| SearchRequest {
            query: q.into(),
            mode: QueryMode::Substring,
            scope: Scope::Content,
            case_sensitive: true,
            sort: SortMode::Filename,
            page: 0,
            page_size: 10,
            exts: Vec::new(),
            path_contains: String::new(),
            min_size: None,
            max_size: None,
            min_mtime: None,
            max_mtime: None,
            deadline_ms: None,
        };
        let old = engine.search(&req("质量检测"), &|| false).unwrap();
        let new = engine.search(&req("甲乙丙"), &|| false).unwrap();
        assert!(old.hits.is_empty(), "old={:?}", old.hits.len());
        assert_eq!(new.hits.len(), 1);
    }

    #[test]
    fn delete_real_corpus_path() {
        let dir = std::env::temp_dir().join(format!("ls-realdel-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let corpus = dir.join("corpus");
        crate::fixturegen::write_corpus(&corpus).unwrap();
        let engine = Engine::open(&dir.join("idx")).unwrap();
        for entry in std::fs::read_dir(&corpus).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().and_then(|s| s.to_str()) != Some("txt") {
                continue;
            }
            let extracted = crate::extract::parse_file(&path, &crate::extract::Limits::default()).unwrap();
            let display = path.to_string_lossy().to_string();
            engine
                .upsert(IndexDoc {
                    path_key: crate::textutil::path_key(&display),
                    path_display: display,
                    filename: path.file_name().unwrap().to_string_lossy().to_string(),
                    ext: path.extension().unwrap_or_default().to_string_lossy().to_string(),
                    root: corpus.to_string_lossy().to_string(),
                    hash: "h".into(),
                    size: 1,
                    mtime: 1,
                    segments: extracted.segments,
                    warnings: extracted.warnings,
                    no_text: extracted.no_text,
                })
                .unwrap();
            engine.commit().unwrap();
        }
        let target = corpus.join("包装材料.txt");
        let key = crate::textutil::path_key(&target.to_string_lossy());
        assert_eq!(engine.path_doc_freq(&key).unwrap(), 1);
        engine.remove_keys(&[key.clone()]).unwrap();
        engine.commit().unwrap();
        assert_eq!(engine.path_doc_freq(&key).unwrap(), 0, "delete did not apply");
    }

    #[test]
    fn delete_after_single_batch() {
        let dir = std::env::temp_dir().join(format!("ls-batchdel-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let engine = Engine::open(&dir).unwrap();
        let segment = |text: &str| Segment {
            kind: "text".into(),
            label: "正文".into(),
            text: text.into(),
            page: None,
            sheet: None,
            cell: None,
        };
        for i in 0..5 {
            engine
                .upsert(IndexDoc {
                    path_key: format!("/tmp/f{i}.txt"),
                    path_display: format!("/tmp/f{i}.txt"),
                    filename: format!("f{i}.txt"),
                    ext: "txt".into(),
                    root: "/tmp".into(),
                    hash: format!("{i}"),
                    size: 1,
                    mtime: 1,
                    segments: vec![segment("Quality is not quality. QUALITY stays distinct.\nStraße\n包装材料质量检测报告")],
                    warnings: Vec::new(),
                    no_text: false,
                })
                .unwrap();
            engine.commit().unwrap();
        }
        assert_eq!(engine.path_doc_freq("/tmp/f1.txt").unwrap(), 1);
        engine.remove_keys(&["/tmp/f1.txt".into()]).unwrap();
        engine.commit().unwrap();
        assert_eq!(engine.path_doc_freq("/tmp/f1.txt").unwrap(), 0);
        assert_eq!(engine.doc_count().unwrap(), 4);
    }
}

#[allow(dead_code)]
fn _span(span: Span) -> Span {
    span
}
