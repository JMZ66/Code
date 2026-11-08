use std::sync::mpsc::Receiver;
use std::time::Instant;

use eframe::egui;

use local_search::config::Config;
use local_search::model::{QueryMode, Scope, SearchRequest, SearchResponse, SortMode, StoredDoc};
use local_search::service::{Service, UiMsg};

pub struct SearchApp {
    service: std::sync::Arc<Service>,
    rx: Receiver<UiMsg>,
    query: String,
    mode: QueryMode,
    scope: Scope,
    sort: SortMode,
    case_sensitive: bool,
    path_filter: String,
    response: Option<SearchResponse>,
    page: usize,
    generation: u64,
    selected: Option<usize>,
    preview: Option<StoredDoc>,
    notice: String,
    dark: bool,
    started: Instant,
    focus_search: bool,
}

impl SearchApp {
    pub fn new(
        cc: &eframe::CreationContext<'_>,
        service: std::sync::Arc<Service>,
        rx: Receiver<UiMsg>,
    ) -> Self {
        install_fonts(&cc.egui_ctx);
        let cfg = service.config.read().map(|c| c.clone()).unwrap_or_default();
        if cfg.theme_dark {
            cc.egui_ctx.set_visuals(egui::Visuals::dark());
        } else {
            cc.egui_ctx.set_visuals(egui::Visuals::light());
        }
        Self {
            service,
            rx,
            query: String::new(),
            mode: cfg.mode,
            scope: cfg.scope,
            sort: cfg.sort,
            case_sensitive: cfg.case_sensitive,
            path_filter: String::new(),
            response: None,
            page: 0,
            generation: 0,
            selected: None,
            preview: None,
            notice: "选择文件夹后才会读取内容。索引只存在本机。".into(),
            dark: cfg.theme_dark,
            started: Instant::now(),
            focus_search: true,
        }
    }

    fn submit(&mut self) {
        let cfg = self.service.config.read().ok().map(|c| c.clone()).unwrap_or_default();
        let req = SearchRequest {
            query: self.query.clone(),
            mode: self.mode,
            scope: self.scope,
            case_sensitive: self.case_sensitive,
            sort: self.sort,
            page: self.page,
            page_size: cfg.page_size.max(10),
            exts: cfg.extensions,
            path_contains: self.path_filter.clone(),
            min_size: None,
            max_size: None,
            min_mtime: None,
            max_mtime: None,
            deadline_ms: None,
        };
        self.generation = self.service.search(req);
        self.notice = "正在搜索…".into();
    }

    fn poll(&mut self) {
        while let Ok(msg) = self.rx.try_recv() {
            match msg {
                UiMsg::Search { gen, response } => {
                    if gen == self.generation {
                        self.response = Some(response);
                        self.selected = None;
                        self.preview = None;
                        self.notice.clear();
                    }
                }
                UiMsg::Progress(p) => {
                    if p.running {
                        self.notice = format!("正在索引 {} · {}", p.root, p.current);
                    }
                }
                UiMsg::Notice(text) => self.notice = text,
            }
        }
    }
}

impl eframe::App for SearchApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.poll();
        if self.dark {
            ctx.set_visuals(egui::Visuals::dark());
        } else {
            ctx.set_visuals(egui::Visuals::light());
        }
        let mut submit = false;
        ctx.input(|input| {
            if input.key_pressed(egui::Key::Enter) {
                submit = true;
            }
            if input.key_pressed(egui::Key::Escape) {
                self.generation = self.generation.wrapping_add(1);
            }
            if input.modifiers.command && input.key_pressed(egui::Key::F) {
                self.focus_search = true;
            }
        });
        if submit {
            self.page = 0;
            self.submit();
        }

        egui::TopBottomPanel::top("searchbar").show(ctx, |ui| {
            ui.add_space(8.0);
            ui.horizontal(|ui| {
                ui.heading("本地全文搜索");
                ui.label(format!("v{}", local_search::VERSION));
            });
            ui.horizontal(|ui| {
                let editor = egui::TextEdit::singleline(&mut self.query)
                    .hint_text("搜索正文或文件名。子串和短语都是连续原文，不是 AND")
                    .desired_width(ui.available_width() - 90.0)
                    .font(egui::TextStyle::Heading);
                let response = ui.add(editor);
                if self.focus_search {
                    response.request_focus();
                    self.focus_search = false;
                }
                if ui.button("搜索").clicked() {
                    self.page = 0;
                    self.submit();
                }
            });
            ui.horizontal_wrapped(|ui| {
                ui.label("方式");
                for mode in QueryMode::all() {
                    if ui
                        .selectable_label(self.mode == *mode, mode.label())
                        .clicked()
                    {
                        self.mode = *mode;
                    }
                }
                ui.separator();
                ui.label("范围");
                for scope in Scope::all() {
                    if ui
                        .selectable_label(self.scope == *scope, scope.label())
                        .clicked()
                    {
                        self.scope = *scope;
                    }
                }
                ui.separator();
                ui.checkbox(&mut self.case_sensitive, "区分大小写");
                ui.label("排序");
                for sort in SortMode::all() {
                    if ui
                        .selectable_label(self.sort == *sort, sort.label())
                        .clicked()
                    {
                        self.sort = *sort;
                    }
                }
            });
            ui.add_space(6.0);
        });

        egui::TopBottomPanel::bottom("status").show(ctx, |ui| {
            ui.horizontal(|ui| {
                let progress = self.service.progress();
                if progress.paused {
                    ui.label("已暂停");
                } else if progress.running {
                    ui.label("索引进行中");
                } else {
                    ui.label("索引空闲");
                }
                if let Some(resp) = &self.response {
                    ui.label(format!(
                        "命中 {} · 候选 {} · {} ms",
                        resp.total, resp.candidates, resp.elapsed_ms
                    ));
                    if resp.incomplete {
                        ui.colored_label(egui::Color32::from_rgb(180, 90, 0), "结果不完整");
                    }
                }
                ui.label(&self.notice);
                ui.weak(format!("已运行 {} 秒", self.started.elapsed().as_secs()));
            });
        });

        egui::SidePanel::left("nav")
            .resizable(true)
            .default_width(280.0)
            .show(ctx, |ui| {
                ui.heading("资料文件夹");
                if ui.button("添加文件夹").clicked() {
                    if let Some(path) = rfd::FileDialog::new().pick_folder() {
                        if let Err(err) = self.service.add_root(path) {
                            self.notice = err;
                        }
                    }
                }
                let roots = self
                    .service
                    .config
                    .read()
                    .map(|c| c.roots.clone())
                    .unwrap_or_default();
                for root in roots {
                    ui.horizontal(|ui| {
                        ui.label(&root.path);
                        if ui.button("移除").clicked() {
                            if let Err(err) = self.service.remove_root(&root.path) {
                                self.notice = err.to_string();
                            }
                        }
                    });
                }
                ui.separator();
                ui.label("路径包含");
                ui.text_edit_singleline(&mut self.path_filter);
                ui.separator();
                ui.heading("格式");
                let mut cfg = self
                    .service
                    .config
                    .write()
                    .ok()
                    .map(|c| c.clone());
                if let Some(cfg) = cfg.as_mut() {
                    ui.horizontal_wrapped(|ui| {
                        for ext in local_search::model::supported_extensions() {
                            let mut on = cfg.extensions.iter().any(|e| e.eq_ignore_ascii_case(ext));
                            if ui.checkbox(&mut on, *ext).changed() {
                                if on {
                                    cfg.extensions.push((*ext).to_string());
                                } else {
                                    cfg.extensions.retain(|e| !e.eq_ignore_ascii_case(ext));
                                }
                            }
                        }
                    });
                    if ui.button("保存索引设置").clicked() {
                        if let Ok(mut live) = self.service.config.write() {
                            live.extensions = cfg.extensions.clone();
                            live.theme_dark = self.dark;
                            live.close_to_tray = cfg.close_to_tray;
                        }
                        self.service.save_config();
                    }
                    ui.checkbox(&mut cfg.close_to_tray, "关闭时留在托盘（Windows）");
                }
                ui.separator();
                if ui.button(if self.service.progress().paused { "继续索引" } else { "暂停索引" }).clicked() {
                    let paused = !self.service.progress().paused;
                    self.service.set_paused(paused);
                }
                if ui.button("重新扫描").clicked() {
                    self.service.set_paused(false);
                    self.service.request_reindex();
                }
                ui.separator();
                ui.label("搜索历史");
                let history = self
                    .service
                    .config
                    .read()
                    .map(|c| c.history.clone())
                    .unwrap_or_default();
                for item in history.iter().take(12) {
                    if ui.button(item).clicked() {
                        self.query = item.clone();
                        self.page = 0;
                        self.submit();
                    }
                }
                ui.separator();
                ui.checkbox(&mut self.dark, "深色");
                let _ = Config::default();
            });

        egui::SidePanel::right("preview")
            .resizable(true)
            .default_width(380.0)
            .show(ctx, |ui| {
                ui.heading("文本预览");
                ui.weak("这是抽取出的文本和命中上下文，不是 Word / Excel / PDF 的原生版式，也不执行脚本、宏或公式。");
                let Some(doc) = &self.preview else {
                    ui.label("点一条结果查看预览。");
                    return;
                };
                if doc.no_text {
                    ui.label("这个文件没有抽出可检索文本。扫描版 PDF 不会被当成已经 OCR。");
                }
                for warning in &doc.warnings {
                    ui.colored_label(egui::Color32::from_rgb(160, 90, 0), warning);
                }
                egui::ScrollArea::vertical().show(ui, |ui| {
                    for seg in &doc.segments {
                        if seg.text.is_empty() {
                            ui.weak(format!("{}：无文本", seg.label));
                            continue;
                        }
                        ui.strong(&seg.label);
                        ui.label(&seg.text);
                        ui.separator();
                    }
                });
            });

        egui::CentralPanel::default().show(ctx, |ui| {
            let Some(resp) = self.response.clone() else {
                ui.heading("输入关键词开始搜索");
                ui.label("默认按连续子串匹配。中文“质量检测”可以命中“包装材料质量检测报告”，“量检”也按连续字符匹配。");
                ui.label("布尔模式才识别大写的 AND、OR、NOT。引号里的内容是短语，不会被拆成 AND。");
                ui.label("没有必须字面量的正则会逐份核对已保存的文本，并标明无法用索引加速。");
                return;
            };
            if let Some(err) = &resp.error {
                ui.colored_label(egui::Color32::RED, err);
            }
            if let Some(warning) = &resp.warning {
                ui.colored_label(egui::Color32::from_rgb(170, 100, 0), warning);
            }
            let hit_count = resp.hits.len();
            egui::ScrollArea::vertical().show_rows(ui, 92.0, hit_count, |ui, range| {
                for row in range {
                if let Some(hit) = resp.hits.get(row) {
                    let selected = self.selected == Some(row);
                    let frame = egui::Frame::group(ui.style()).fill(if selected {
                        ui.visuals().selection.bg_fill.gamma_multiply(0.35)
                    } else {
                        ui.visuals().faint_bg_color
                    });
                    let inner = frame.show(ui, |ui| {
                        ui.horizontal(|ui| {
                            badge(ui, &hit.ext);
                            ui.strong(&hit.filename);
                            ui.weak(format_size(hit.size));
                            ui.weak(format!("mtime {}", hit.mtime));
                        });
                        ui.weak(&hit.path);
                        show_snippet(ui, &hit.snippet, &hit.snippet_spans);
                        ui.horizontal_wrapped(|ui| {
                            for loc in hit.locations.iter().take(6) {
                                ui.small(&loc.label);
                            }
                            if hit.match_count > hit.locations.len() as u32 {
                                ui.small(format!("共 {} 处", hit.match_count));
                            }
                        });
                    });
                    let response = inner.response.interact(egui::Sense::click());
                    if response.clicked() {
                        self.selected = Some(row);
                        self.preview = self.service.load_preview(&hit.path_key);
                    }
                    if response.double_clicked() {
                        let _ = open::that(&hit.path);
                    }
                    response.context_menu(|ui| {
                        if ui.button("打开文件").clicked() {
                            let _ = open::that(&hit.path);
                            ui.close_menu();
                        }
                        if ui.button("打开所在文件夹").clicked() {
                            if let Some(parent) = std::path::Path::new(&hit.path).parent() {
                                let _ = open::that(parent);
                            }
                            ui.close_menu();
                        }
                        if ui.button("复制路径").clicked() {
                            copy_text(&hit.path);
                            ui.close_menu();
                        }
                        if ui.button("复制匹配文本").clicked() {
                            let text = hit
                                .locations
                                .first()
                                .map(|l| l.text.clone())
                                .unwrap_or_else(|| hit.snippet.clone());
                            copy_text(&text);
                            ui.close_menu();
                        }
                    });
                }
                }
            });
            ui.horizontal(|ui| {
                if ui.button("上一页").clicked() && self.page > 0 {
                    self.page -= 1;
                    self.submit();
                }
                ui.label(format!("第 {} 页", self.page + 1));
                if ui.button("下一页").clicked() {
                    let page_size = self
                        .service
                        .config
                        .read()
                        .map(|c| c.page_size)
                        .unwrap_or(20)
                        .max(1);
                    if (self.page + 1) * page_size < resp.total as usize {
                        self.page += 1;
                        self.submit();
                    }
                }
            });
        });
        ctx.request_repaint_after(std::time::Duration::from_millis(200));
    }
}

fn badge(ui: &mut egui::Ui, ext: &str) {
    let color = match ext {
        "doc" | "docx" | "docm" | "odt" | "rtf" => egui::Color32::from_rgb(40, 90, 170),
        "xls" | "xlsx" | "xlsm" | "xlsb" | "ods" | "csv" => egui::Color32::from_rgb(30, 120, 70),
        "ppt" | "pptx" | "odp" => egui::Color32::from_rgb(180, 80, 30),
        "pdf" => egui::Color32::from_rgb(170, 40, 40),
        _ => egui::Color32::from_rgb(80, 80, 90),
    };
    let label = if ext.is_empty() { "FILE" } else { ext };
    egui::Frame::NONE
        .fill(color)
        .corner_radius(4)
        .inner_margin(egui::Margin::symmetric(6, 2))
        .show(ui, |ui| {
            ui.label(egui::RichText::new(label.to_uppercase()).color(egui::Color32::WHITE).small());
        });
}

fn show_snippet(ui: &mut egui::Ui, text: &str, spans: &[(usize, usize)]) {
    if text.is_empty() {
        return;
    }
    let chars: Vec<char> = text.chars().collect();
    ui.horizontal_wrapped(|ui| {
        let mut cursor = 0usize;
        for (start, end) in spans {
            let start = (*start).min(chars.len());
            let end = (*end).min(chars.len()).max(start);
            if cursor < start {
                let plain: String = chars[cursor..start].iter().collect();
                ui.label(plain);
            }
            let hit: String = chars[start..end].iter().collect();
            ui.colored_label(egui::Color32::from_rgb(180, 60, 20), egui::RichText::new(hit).strong());
            cursor = end;
        }
        if cursor < chars.len() {
            let rest: String = chars[cursor..].iter().collect();
            ui.label(rest);
        }
    });
}

fn format_size(size: u64) -> String {
    if size < 1024 {
        format!("{size} B")
    } else if size < 1024 * 1024 {
        format!("{:.1} KB", size as f64 / 1024.0)
    } else {
        format!("{:.1} MB", size as f64 / 1024.0 / 1024.0)
    }
}

fn copy_text(text: &str) {
    if let Ok(mut clipboard) = arboard::Clipboard::new() {
        let _ = clipboard.set_text(text.to_string());
    }
}

fn install_fonts(ctx: &egui::Context) {
    let Some(bytes) = load_cjk_font() else {
        return;
    };
    let mut fonts = egui::FontDefinitions::default();
    fonts.font_data.insert(
        "cjk".to_owned(),
        std::sync::Arc::new(egui::FontData::from_owned(bytes)),
    );
    if let Some(prop) = fonts.families.get_mut(&egui::FontFamily::Proportional) {
        prop.insert(0, "cjk".to_owned());
    }
    if let Some(mono) = fonts.families.get_mut(&egui::FontFamily::Monospace) {
        mono.insert(0, "cjk".to_owned());
    }
    ctx.set_fonts(fonts);
}

fn load_cjk_font() -> Option<Vec<u8>> {
    let mut candidates = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("fonts").join("DroidSansFallbackFull.ttf"));
        }
    }
    candidates.push(
        PathBufHack(std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")))
            .0
            .join("fonts")
            .join("DroidSansFallbackFull.ttf"),
    );
    candidates.push(std::path::PathBuf::from(
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ));
    for path in candidates {
        if let Ok(bytes) = std::fs::read(&path) {
            if bytes.len() > 16 && &bytes[0..4] != b"ttcf" {
                return Some(bytes);
            }
        }
    }
    None
}

struct PathBufHack(std::path::PathBuf);

pub fn gui_probe() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1100.0, 720.0])
            .with_title("本地全文搜索"),
        ..Default::default()
    };
    eframe::run_native(
        "本地全文搜索",
        options,
        Box::new(|cc| {
            let (tx, rx) = std::sync::mpsc::channel();
            let data = local_search::config::default_data_dir().join("probe");
            let cfg_path = data.join("config.json");
            let index = data.join("index");
            let service = local_search::service::Service::open(
                cfg_path,
                index,
                tx,
                local_search::service::worker_binary(),
            )
            .expect("probe service");
            let mut app = SearchApp::new(cc, service, rx);
            app.notice = "gui-probe".into();
            // Render one frame then close.
            cc.egui_ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            Ok(Box::new(app))
        }),
    )
}
