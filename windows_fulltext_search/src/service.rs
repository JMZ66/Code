//! Index and search coordinator. Searches carry a generation id so a slow
//! older query cannot overwrite the results of a newer one.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;

use crate::config::{blocked_root, Config};
use crate::extract::{self, Limits};
use crate::index::{Engine, IndexDoc, Meta};
use crate::model::{needs_worker, Extracted, SearchRequest, SearchResponse};
use crate::scan::{self, WorkerPool};

#[derive(Debug, Clone)]
pub enum UiMsg {
    Progress(Progress),
    Search { gen: u64, response: SearchResponse },
    Notice(String),
}

#[derive(Debug, Clone, Default)]
pub struct Progress {
    pub running: bool,
    pub paused: bool,
    pub root: String,
    pub seen: u64,
    pub indexed: u64,
    pub skipped: u64,
    pub current: String,
    pub error: Option<String>,
}

pub struct Service {
    pub config: Arc<RwLock<Config>>,
    pub config_path: PathBuf,
    engine: Arc<Engine>,
    tx: Sender<UiMsg>,
    pause: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
    kick: Arc<AtomicBool>,
    epoch: Arc<AtomicU64>,
    progress: Arc<Mutex<Progress>>,
    workers: Arc<WorkerPool>,
    limits: Limits,
}

impl Service {
    pub fn open(config_path: PathBuf, index_dir: PathBuf, tx: Sender<UiMsg>, worker_bin: PathBuf) -> anyhow::Result<Arc<Self>> {
        let config = Config::load(&config_path);
        let threads = config.threads.clamp(1, 8);
        let engine = Arc::new(Engine::open(&index_dir)?);
        let workers = Arc::new(WorkerPool::start(worker_bin, threads));
        let limits = limits_from(&config);
        let svc = Arc::new(Self {
            config: Arc::new(RwLock::new(config)),
            config_path,
            engine,
            tx,
            pause: Arc::new(AtomicBool::new(false)),
            stop: Arc::new(AtomicBool::new(false)),
            kick: Arc::new(AtomicBool::new(true)),
            epoch: Arc::new(AtomicU64::new(1)),
            progress: Arc::new(Mutex::new(Progress::default())),
            workers,
            limits,
        });
        let background = Arc::clone(&svc);
        std::thread::spawn(move || background.index_loop());
        let watch = Arc::clone(&svc);
        std::thread::spawn(move || watch_loop(watch));
        Ok(svc)
    }

    pub fn engine(&self) -> Arc<Engine> {
        Arc::clone(&self.engine)
    }

    pub fn progress(&self) -> Progress {
        self.progress.lock().map(|g| g.clone()).unwrap_or_default()
    }

    pub fn save_config(&self) {
        if let Ok(cfg) = self.config.read() {
            let _ = cfg.save(&self.config_path);
        }
    }

    pub fn set_paused(&self, paused: bool) {
        self.pause.store(paused, Ordering::SeqCst);
        if !paused {
            self.kick.store(true, Ordering::SeqCst);
        }
    }

    pub fn request_reindex(&self) {
        self.kick.store(true, Ordering::SeqCst);
    }

    pub fn search(&self, mut req: SearchRequest) -> u64 {
        let gen = self.epoch.fetch_add(1, Ordering::SeqCst) + 1;
        let epoch = Arc::clone(&self.epoch);
        let engine = Arc::clone(&self.engine);
        let tx = self.tx.clone();
        if req.deadline_ms.is_none() {
            req.deadline_ms = Some(if req.mode == crate::model::QueryMode::Regex {
                60_000
            } else {
                15_000
            });
        }
        let req_for_thread = req.clone();
        std::thread::spawn(move || {
            let my = gen;
            let stop = move || epoch.load(Ordering::SeqCst) != my;
            let response = engine
                .search(&req_for_thread, &stop)
                .unwrap_or_else(|err| SearchResponse::failed(err.to_string()));
            let _ = tx.send(UiMsg::Search { gen: my, response });
        });
        if let Ok(mut cfg) = self.config.write() {
            let q = req.query.trim().to_string();
            if !q.is_empty() {
                cfg.history.retain(|h| h != &q);
                cfg.history.insert(0, q);
                cfg.history.truncate(40);
                cfg.mode = req.mode;
                cfg.scope = req.scope;
                cfg.sort = req.sort;
                cfg.case_sensitive = req.case_sensitive;
            }
        }
        self.save_config();
        gen
    }

    pub fn add_root(&self, path: PathBuf) -> Result<(), String> {
        if let Some(reason) = blocked_root(&path) {
            return Err(reason.into());
        }
        if !path.is_dir() {
            return Err("请选择一个存在的文件夹".into());
        }
        let text = path.to_string_lossy().to_string();
        if let Ok(mut cfg) = self.config.write() {
            if cfg.roots.iter().any(|r| r.path == text) {
                return Err("这个文件夹已经在列表里".into());
            }
            cfg.roots.push(crate::config::RootEntry {
                path: text,
                enabled: true,
            });
        }
        self.save_config();
        self.kick.store(true, Ordering::SeqCst);
        Ok(())
    }

    pub fn remove_root(&self, path: &str) -> anyhow::Result<()> {
        if let Ok(mut cfg) = self.config.write() {
            cfg.roots.retain(|r| r.path != path);
        }
        self.save_config();
        self.engine.remove_root(path)?;
        Ok(())
    }

    pub fn load_preview(&self, path_key: &str) -> Option<crate::model::StoredDoc> {
        self.engine.load(path_key).ok().flatten()
    }

    fn index_loop(self: Arc<Self>) {
        let mut last_full = std::time::Instant::now() - Duration::from_secs(3600);
        while !self.stop.load(Ordering::SeqCst) {
            let paused = self.pause.load(Ordering::SeqCst);
            let kick = self.kick.swap(false, Ordering::SeqCst);
            let rescan = self
                .config
                .read()
                .map(|c| c.rescan_secs)
                .unwrap_or(300);
            let due = last_full.elapsed() > Duration::from_secs(rescan.max(30));
            if !paused && (kick || due) {
                self.reconcile_all(false);
                last_full = std::time::Instant::now();
            }
            std::thread::sleep(Duration::from_millis(400));
        }
    }

    pub fn reconcile_all(&self, force: bool) {
        let roots: Vec<String> = self
            .config
            .read()
            .map(|c| {
                c.roots
                    .iter()
                    .filter(|r| r.enabled)
                    .map(|r| r.path.clone())
                    .collect()
            })
            .unwrap_or_default();
        let exts: HashSet<String> = self
            .config
            .read()
            .map(|c| c.extensions.iter().map(|e| e.to_ascii_lowercase()).collect())
            .unwrap_or_default();
        for root in roots {
            if self.pause.load(Ordering::SeqCst) || self.stop.load(Ordering::SeqCst) {
                break;
            }
            self.reconcile_root(Path::new(&root), &exts, force);
        }
    }

    fn reconcile_root(&self, root: &Path, exts: &HashSet<String>, force: bool) {
        let root_text = root.to_string_lossy().to_string();
        self.set_progress(|p| {
            p.running = true;
            p.root = root_text.clone();
            p.error = None;
        });
        let outcome = scan::walk_root(root);
        if !outcome.root_accessible {
            self.set_progress(|p| {
                p.running = false;
                p.error = outcome.access_error.clone();
            });
            let _ = self.tx.send(UiMsg::Notice(
                outcome
                    .access_error
                    .unwrap_or_else(|| "根目录不可访问，索引已保留".into()),
            ));
            return;
        }
        let mut seen = HashSet::new();
        let mut indexed = 0u64;
        let mut skipped = 0u64;
        for file in &outcome.files {
            if self.pause.load(Ordering::SeqCst) || self.stop.load(Ordering::SeqCst) {
                self.set_progress(|p| p.running = false);
                return;
            }
            if !exts.is_empty() && !exts.contains(&file.ext) {
                continue;
            }
            seen.insert(file.path_key.clone());
            self.set_progress(|p| {
                p.seen += 1;
                p.current = file.path_display.clone();
            });
            if file.skip_reason.is_some() {
                skipped += 1;
                let meta = Meta {
                    path_key: file.path_key.clone(),
                    path_display: file.path_display.clone(),
                    filename: file.filename.clone(),
                    ext: file.ext.clone(),
                    root: root_text.clone(),
                    hash: String::new(),
                    size: file.size,
                    mtime: file.mtime,
                    failed: true,
                    generation: 0,
                };
                let _ = self.engine.upsert(IndexDoc {
                    path_key: meta.path_key.clone(),
                    path_display: meta.path_display.clone(),
                    filename: meta.filename.clone(),
                    ext: meta.ext.clone(),
                    root: meta.root.clone(),
                    hash: meta.hash.clone(),
                    size: meta.size,
                    mtime: meta.mtime,
                    segments: Vec::new(),
                    warnings: vec![file.skip_reason.clone().unwrap_or_default()],
                    no_text: true,
                });
                continue;
            }
            let previous = self.engine.lookup(&file.path_key);
            if !force {
                if let Some(prev) = &previous {
                    if !prev.failed && prev.size == file.size && prev.mtime == file.mtime {
                        skipped += 1;
                        continue;
                    }
                }
            }
            let hash = match scan::sha256_file(&file.path) {
                Ok(h) => h,
                Err(err) => {
                    let _ = self.engine.upsert(IndexDoc {
                        path_key: file.path_key.clone(),
                        path_display: file.path_display.clone(),
                        filename: file.filename.clone(),
                        ext: file.ext.clone(),
                        root: root_text.clone(),
                        hash: String::new(),
                        size: file.size,
                        mtime: file.mtime,
                        segments: Vec::new(),
                        warnings: vec![format!("无法读取：{err}")],
                        no_text: true,
                    });
                    continue;
                }
            };
            if !force {
                if let Some(prev) = &previous {
                    if !prev.failed && prev.hash == hash {
                        skipped += 1;
                        continue;
                    }
                }
            }
            let extracted = self.extract_one(&file.path, &file.ext);
            match extracted {
                Ok(doc) => {
                    let _ = self.engine.upsert(IndexDoc {
                        path_key: file.path_key.clone(),
                        path_display: file.path_display.clone(),
                        filename: file.filename.clone(),
                        ext: file.ext.clone(),
                        root: root_text.clone(),
                        hash,
                        size: file.size,
                        mtime: file.mtime,
                        segments: doc.segments,
                        warnings: doc.warnings,
                        no_text: doc.no_text,
                    });
                    indexed += 1;
                }
                Err(err) => {
                    let _ = self.engine.upsert(IndexDoc {
                        path_key: file.path_key.clone(),
                        path_display: file.path_display.clone(),
                        filename: file.filename.clone(),
                        ext: file.ext.clone(),
                        root: root_text.clone(),
                        hash,
                        size: file.size,
                        mtime: file.mtime,
                        segments: Vec::new(),
                        warnings: vec![err],
                        no_text: true,
                    });
                    if let Ok(mut guard) = self.engine_manifest_failed(&file.path_key) {
                        let _ = guard;
                    }
                }
            }
            if indexed % 200 == 0 {
                let _ = self.engine.commit();
            }
        }
        if outcome.complete && !self.pause.load(Ordering::SeqCst) {
            let stale: Vec<String> = self
                .engine
                .manifest_snapshot()
                .into_iter()
                .filter(|m| m.root == root_text && !seen.contains(&m.path_key))
                .map(|m| m.path_key)
                .collect();
            if !stale.is_empty() {
                let _ = self.engine.remove_keys(&stale);
            }
        } else if !outcome.complete {
            let _ = self.tx.send(UiMsg::Notice(
                "有的子目录读不了，这次没有把没看到的文件从索引里删除".into(),
            ));
        }
        let _ = self.engine.commit();
        self.set_progress(|p| {
            p.running = false;
            p.indexed += indexed;
            p.skipped += skipped;
            p.current.clear();
        });
    }

    fn engine_manifest_failed(&self, key: &str) -> Result<(), ()> {
        if let Some(mut meta) = self.engine.lookup(key) {
            meta.failed = true;
            let _ = meta;
        }
        Ok(())
    }

    fn extract_one(&self, path: &Path, ext: &str) -> Result<Extracted, String> {
        if needs_worker(ext) {
            self.workers
                .parse(path, &self.limits, Duration::from_secs(20))
        } else {
            extract::parse_file(path, &self.limits).map_err(|err| err.to_string())
        }
    }

    fn set_progress(&self, f: impl FnOnce(&mut Progress)) {
        if let Ok(mut guard) = self.progress.lock() {
            f(&mut guard);
            let _ = self.tx.send(UiMsg::Progress(guard.clone()));
        }
    }
}

fn watch_loop(service: Arc<Service>) {
    use notify::Watcher;
    let (tx, rx) = std::sync::mpsc::channel();
    let mut watcher = match notify::recommended_watcher(tx) {
        Ok(watcher) => watcher,
        Err(err) => {
            let _ = service
                .tx
                .send(UiMsg::Notice(format!("文件监控不可用，将只按周期复查：{err}")));
            return;
        }
    };
    let mut watched: Vec<PathBuf> = Vec::new();
    loop {
        if service.stop.load(Ordering::SeqCst) {
            break;
        }
        let roots = service.config.read().map(|cfg| {
            cfg.roots
                .iter()
                .filter(|root| root.enabled)
                .map(|root| PathBuf::from(&root.path))
                .collect::<Vec<_>>()
        });
        if let Ok(roots) = roots {
            for old in watched.drain(..) {
                let _ = watcher.unwatch(&old);
            }
            for root in &roots {
                let _ = watcher.watch(root, notify::RecursiveMode::Recursive);
            }
            watched = roots;
        }
        match rx.recv_timeout(Duration::from_secs(2)) {
            Ok(_) => {
                std::thread::sleep(Duration::from_millis(700));
                while rx.try_recv().is_ok() {}
                service.kick.store(true, Ordering::SeqCst);
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}

fn limits_from(config: &Config) -> Limits {
    Limits {
        max_file_bytes: config.max_file_mb.saturating_mul(1024 * 1024).max(1024 * 1024),
        ..Limits::default()
    }
}

pub fn worker_binary() -> PathBuf {
    let mut path = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("local-search-parse"));
    path.pop();
    let name = if cfg!(windows) {
        "local-search-parse.exe"
    } else {
        "local-search-parse"
    };
    path.join(name)
}
