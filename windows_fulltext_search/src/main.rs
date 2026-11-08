mod ui;

use std::path::PathBuf;

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn")).init();
    let args: Vec<String> = std::env::args().skip(1).collect();
    if let Some(report) = flag_value(&args, "--self-test-report") {
        match local_search::selftest::run(std::path::Path::new(&report)) {
            Ok(result) => {
                println!("{}", serde_json::to_string(&result).unwrap_or_default());
                std::process::exit(0);
            }
            Err(err) => {
                eprintln!("{err}");
                std::process::exit(1);
            }
        }
    }
    if args.iter().any(|a| a == "--self-test") {
        let report = std::env::temp_dir().join("localsearch-selftest.json");
        match local_search::selftest::run(&report) {
            Ok(_) => std::process::exit(0),
            Err(err) => {
                eprintln!("{err}");
                std::process::exit(1);
            }
        }
    }
    if let Some(out) = flag_value(&args, "--bench-out") {
        let docs = flag_value(&args, "--docs")
            .and_then(|s| s.parse().ok())
            .unwrap_or(1000);
        if let Err(err) = local_search::selftest::bench(std::path::Path::new(&out), docs) {
            eprintln!("{err}");
            std::process::exit(1);
        }
        std::process::exit(0);
    }
    if args.iter().any(|a| a == "--gui-probe") {
        if let Err(err) = ui::gui_probe() {
            eprintln!("gui-probe failed: {err}");
            std::process::exit(1);
        }
        std::process::exit(0);
    }
    if args.iter().any(|a| a == "--version") {
        println!("local-search {}", local_search::VERSION);
        return;
    }

    let data = local_search::config::default_data_dir();
    let config_path = data.join("config.json");
    let mut config = local_search::config::Config::load(&config_path);
    let index_dir = config
        .index_dir
        .clone()
        .map(PathBuf::from)
        .unwrap_or_else(|| data.join("index"));
    config.index_dir = Some(index_dir.to_string_lossy().to_string());
    let _ = config.save(&config_path);
    let (tx, rx) = std::sync::mpsc::channel();
    let service = match local_search::service::Service::open(
        config_path,
        index_dir,
        tx,
        local_search::service::worker_binary(),
    ) {
        Ok(service) => service,
        Err(err) => {
            eprintln!("无法打开索引：{err}");
            std::process::exit(1);
        }
    };
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 800.0])
            .with_min_inner_size([900.0, 600.0])
            .with_title("本地全文搜索"),
        ..Default::default()
    };
    if let Err(err) = eframe::run_native(
        "本地全文搜索",
        options,
        Box::new(move |cc| Ok(Box::new(ui::SearchApp::new(cc, service, rx)))),
    ) {
        eprintln!("界面启动失败：{err}");
        std::process::exit(1);
    }
}

fn flag_value(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1))
        .cloned()
}
