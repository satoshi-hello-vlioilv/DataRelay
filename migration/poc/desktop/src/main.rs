//! 【検証用の試作】DataRelay デスクトップ版（Tauri）。実行では使わない（migration/FEASIBILITY.md の「検証2」）。
//!
//! Defect-Pitch-Analyzer のデスクトップ版（版 2.0.0）と同じ分け方:
//!   - Rust（この exe）: 窓・起動と終了・1つだけ起動・静的ファイル・中身（Python）の監督・外のリンク
//!   - Python（migration/poc/sidecar.py → app.py）: 画面と API のすべて（いまの Flask のまま）
//!   - 画面（WebView2）: いまの HTML/JS/CSS。問い合わせは自前の仕組み（datarelay）で Rust が受ける
//!
//! DataRelay で足すもの（DPA に無いもの）を、ここで確かめる:
//!   1. 通知領域のアイコン（開く・終了。状態をツールチップに出す）       … いまは pywin32 の tray_icon.py
//!   2. 窓を閉じたとき、常駐の理由（実行中・キュー・自動実行の予定）があれば隠して常駐、無ければ終了
//!                                                                       … いまはハートビートで推し量っている
//!   3. ファイル・フォルダーの選択、エクスプローラーで開く                 … いまは tkinter と os.startfile
//!   4. ダウンロード（登録内容のZIP・集計結果のEXCEL）を保存ダイアログで受ける
//!   5. アプリ内の「終了」                                                 … いまは Python が os._exit

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod frame;
mod router;
mod sidecar;

use router::{error_reply, Backend, Native, Router, Saver};
use serde_json::{json, Value};
use sidecar::{Ask, Python, Reply, Supervisor};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::DialogExt;

const SCHEME: &str = "datarelay";
const TITLE: &str = "DataRelay";
const SELFTEST_JS: &str = include_str!("selftest.js");
const SELFTEST_LIMIT: Duration = Duration::from_secs(150);

fn app_url(path: &str) -> Url {
    let base = if cfg!(windows) { "http://datarelay.localhost" } else { "datarelay://localhost" };
    Url::parse(&format!("{base}{path}")).expect("app url")
}

fn is_app_url(u: &Url) -> bool {
    u.scheme() == SCHEME || u.host_str() == Some("datarelay.localhost")
}

type AppRouter = Router<Supervisor>;

/// 窓の外から見える状態（自己診断と、閉じたときの判断の記録）。
#[derive(Default)]
struct Shell {
    router: OnceLock<AppRouter>,
    tray: Mutex<Option<TrayIcon>>,
    resident_reason: Mutex<String>,
    saved: Mutex<Vec<String>>,
    quitting: AtomicBool,
}

impl Shell {
    fn backend(&self) -> Option<&Supervisor> {
        self.router.get().map(|r| &r.backend)
    }

    /// 常駐を続ける理由（Python の residency_reason。実行中・キュー・自動実行の予定・影実行・頼まれた常駐）。
    /// 試作では既存の /api/heartbeat-status の residency_pending_reason を読む。本番では専用の問い合わせにする。
    fn residency_reason(&self) -> Result<String, String> {
        let b = self.backend().ok_or("起動中です")?;
        let r = b.ask(&Ask { method: "GET", path: "/api/heartbeat-status", query: "", headers: vec![], body: b"" });
        if r.status != 200 {
            return Err(format!("状態を聞けませんでした（{}）", r.status));
        }
        let v: Value = serde_json::from_slice(&r.body).map_err(|e| e.to_string())?;
        Ok(v["residency_pending_reason"].as_str().unwrap_or("").to_string())
    }

    fn set_tooltip(&self, text: &str) {
        if let Some(t) = self.tray.lock().unwrap().as_ref() {
            let _ = t.set_tooltip(Some(text));
        }
    }
}

/// 窓を閉じたとき: 常駐の理由があれば隠して通知領域に残る。無ければ終わる。
/// 理由を聞けなければ（中身が止まっている等）終わる ―― 見えないまま残る方が困るため。
fn on_close_requested(app: &AppHandle, shell: &Shell) {
    if shell.quitting.load(Ordering::SeqCst) {
        return app.exit(0);
    }
    match shell.residency_reason() {
        Ok(reason) if !reason.is_empty() => {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.hide();
            }
            shell.set_tooltip(&format!("{TITLE}（常駐中: {reason}）"));
            *shell.resident_reason.lock().unwrap() = reason;
        }
        _ => app.exit(0),
    }
}

fn show_main(app: &AppHandle, shell: &Shell) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
    shell.resident_reason.lock().unwrap().clear();
    shell.set_tooltip(TITLE);
}

/// 通知領域のアイコン。左クリックで開く。右のメニューに「開く」「終了」。
fn build_tray(app: &AppHandle, shell: Arc<Shell>) -> tauri::Result<TrayIcon> {
    let open = MenuItem::with_id(app, "open", "画面を開く", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "終了", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let (s1, s2) = (shell.clone(), shell);
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("icon"))
        .tooltip(TITLE)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, e| match e.id().as_ref() {
            "open" => show_main(app, &s1),
            "quit" => quit_app(app, &s1),
            _ => {}
        })
        .on_tray_icon_event(move |tray, e| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = e {
                show_main(tray.app_handle(), &s2);
            }
        })
        .build(app)
}

/// 終了: 本番では先に Python へ後始末（キューを空に・実行中なら中断・ワーカーを止める・設定を書き出す）を頼む。
/// 試作では入力を閉じるだけ（Python は入力の終わりを見て自分で終わる）。
fn quit_app(app: &AppHandle, shell: &Shell) {
    shell.quitting.store(true, Ordering::SeqCst);
    app.exit(0);
}

fn json_reply(v: &Value) -> Reply {
    Reply { status: 200, headers: vec![("Content-Type".into(), "application/json".into())], body: serde_json::to_vec(v).unwrap_or_default() }
}

fn selftest_finish(app: &AppHandle, result: &Value) {
    if let Some(path) = std::env::var_os("DATARELAY_SELFTEST") {
        let _ = std::fs::write(&path, serde_json::to_vec_pretty(result).unwrap_or_default());
        app.exit(if result["ok"] == true { 0 } else { 1 });
    }
}

fn selftest_dir() -> Option<PathBuf> {
    std::env::var_os("DATARELAY_SELFTEST").map(|p| PathBuf::from(p).with_extension("files"))
}

/// ファイル・フォルダーの選択。いまの /api/pick-file・/api/pick-folder（tkinter）と同じ答えの形 {"path": "..."}。
/// 自己診断ではダイアログを出せない（押す人がいない）ので、決めた場所を返す。
fn pick(app: &AppHandle, folder: bool, body: &[u8]) -> Reply {
    let req: Value = serde_json::from_slice(body).unwrap_or(json!({}));
    if let Some(dir) = selftest_dir() {
        return json_reply(&json!({"path": dir.to_string_lossy(), "selftest": true, "initial": req["initial"]}));
    }
    let mut d = app.dialog().file();
    if let Some(init) = req["initial"].as_str().filter(|s| !s.is_empty()) {
        let p = PathBuf::from(init);
        d = d.set_directory(if p.extension().is_some() { p.parent().map(PathBuf::from).unwrap_or(p) } else { p });
    }
    if let Some(types) = req["types"].as_array() {
        for t in types {
            if let (Some(name), Some(pat)) = (t.get(0).and_then(Value::as_str), t.get(1).and_then(Value::as_str)) {
                let exts: Vec<&str> = pat.split(';').map(|x| x.trim().trim_start_matches("*.")).filter(|x| *x != "*").collect();
                if !exts.is_empty() {
                    d = d.add_filter(name, &exts);
                }
            }
        }
    }
    let got = if folder { d.blocking_pick_folder() } else { d.blocking_pick_file() };
    let path = got.and_then(|p| p.into_path().ok()).map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
    json_reply(&json!({"path": path}))
}

/// 窓そのものが答える問い合わせ。
fn native(app: AppHandle, shell: Arc<Shell>, info: Value) -> Native {
    Box::new(move |method, path, body| match (method, path) {
        ("POST", "/api/pick-file") => Some(pick(&app, false, body)),
        ("POST", "/api/pick-folder") => Some(pick(&app, true, body)),
        // エクスプローラーで開く（いまの os.startfile）。ファイルなら、そのファイルを選んだ状態でフォルダーを開く
        ("POST", "/api/open-path") => {
            use tauri_plugin_opener::OpenerExt;
            let req: Value = serde_json::from_slice(body).unwrap_or(json!({}));
            let target = req["path"].as_str().unwrap_or("").to_string();
            if selftest_dir().is_some() {
                return Some(json_reply(&json!({"ok": true, "selftest": true, "path": target})));
            }
            let p = PathBuf::from(&target);
            let r = if p.is_file() { app.opener().reveal_item_in_dir(&p) } else { app.opener().open_path(&target, None::<&str>) };
            Some(match r {
                Ok(_) => json_reply(&json!({"ok": true, "path": target})),
                Err(e) => error_reply(400, "open_failed", &format!("開けませんでした: {e}")),
            })
        }
        // アプリ内の「終了」: 答えてから終わる
        ("POST", "/api/shutdown-app") => {
            let (app, shell) = (app.clone(), shell.clone());
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(150));
                quit_app(&app, &shell);
            });
            Some(json_reply(&json!({"ok": true, "status": "stopping"})))
        }
        ("GET", "/__desktop/info") => {
            let w = app.get_webview_window("main");
            Some(json_reply(&json!({
                "info": info,
                "mode": std::env::var("DATARELAY_SELFTEST_MODE").unwrap_or_default(),
                "tray": shell.tray.lock().unwrap().is_some(),
                "visible": w.as_ref().and_then(|w| w.is_visible().ok()),
                "resident_reason": *shell.resident_reason.lock().unwrap(),
                "saved": *shell.saved.lock().unwrap(),
            })))
        }
        // 自己診断: 窓を閉じる操作（×と同じ道）を起こす
        ("POST", "/__desktop/close") => {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.close();
            }
            Some(json_reply(&json!({"requested": true})))
        }
        ("POST", "/__desktop/show") => {
            show_main(&app, &shell);
            Some(json_reply(&json!({"shown": true})))
        }
        // 自己診断（閉じるだけの型）: 終わる前に、聞いた理由を書き残す（終わったあとに外から確かめる）
        ("POST", "/__desktop/note") => {
            if let Some(path) = std::env::var_os("DATARELAY_SELFTEST") {
                let _ = std::fs::write(PathBuf::from(path).with_extension("note.json"), body);
            }
            Some(json_reply(&json!({"noted": true})))
        }
        ("POST", "/__desktop/selftest") => {
            let result: Value = serde_json::from_slice(body).unwrap_or_else(|e| json!({"ok": false, "error": e.to_string()}));
            selftest_finish(&app, &result);
            Some(json_reply(&json!({"received": true})))
        }
        _ => None,
    })
}

/// ダウンロードの受け止め。窓の保存ダイアログで場所を聞き、書く。
fn saver(app: AppHandle, shell: Arc<Shell>) -> Saver {
    Box::new(move |name, body| {
        let path = if let Some(dir) = selftest_dir() {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            Some(dir.join(name))
        } else {
            app.dialog().file().set_file_name(name).blocking_save_file().and_then(|p| p.into_path().ok())
        };
        let Some(path) = path else { return Ok(None) };
        std::fs::write(&path, body).map_err(|e| e.to_string())?;
        shell.saved.lock().unwrap().push(path.to_string_lossy().into_owned());
        Ok(Some(path))
    })
}

fn window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    let nav = app.clone();
    WebviewWindowBuilder::new(app, "main", url)
        .title(TITLE)
        .inner_size(1600.0, 1000.0)
        .min_inner_size(1100.0, 700.0)
        .on_navigation(move |u| {
            let inside = is_app_url(u) || u.scheme() == "tauri" || u.host_str() == Some("tauri.localhost") || matches!(u.scheme(), "about" | "blob" | "data");
            if !inside && matches!(u.scheme(), "http" | "https" | "mailto" | "file") {
                use tauri_plugin_opener::OpenerExt;
                let _ = nav.opener().open_url(u.as_str(), None::<&str>);
            }
            inside
        })
        .on_page_load(|w, p| {
            if p.event() == tauri::webview::PageLoadEvent::Finished
                && is_app_url(p.url())
                && p.url().path() == "/"
                && std::env::var_os("DATARELAY_SELFTEST").is_some()
            {
                let _ = w.eval(SELFTEST_JS);
            }
        })
        .build()
}

/// 中身（Python）を起こし、準備できたら画面へ切り替える（裏の糸で。窓と常駐アイコンは先に出しておく）。
fn start(app: AppHandle, shell: Arc<Shell>) {
    let fail = |msg: String| {
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.eval(format!("document.body.innerText={}", json!(msg)));
        }
        selftest_finish(&app, &json!({"ok": false, "error": msg}));
    };
    let program = match sidecar::program_dir() {
        Ok(p) => p,
        Err(e) => return fail(e),
    };
    let py = Python::find();
    let local = std::env::var_os("NAVI_LOCAL_ROOT").map(PathBuf::from).unwrap_or_else(|| std::env::temp_dir().join("DataRelay"));
    let sup = Supervisor::new(py.clone(), program.clone(), local.join("logs"));
    let ready = match sup.get() {
        Ok(s) => s.ready.clone(),
        Err(e) => return fail(e),
    };
    let info = json!({"shell": "tauri", "shell_version": env!("CARGO_PKG_VERSION"), "program": program, "python": py.exe, "backend": ready});
    let r = Router { static_dir: program.join("static"), backend: sup, native: native(app.clone(), shell.clone(), info), saver: saver(app.clone(), shell.clone()) };
    let _ = shell.router.set(r);
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.navigate(app_url("/"));
    }
}

fn main() {
    let shell: Arc<Shell> = Arc::default();
    let (proto, close_shell) = (shell.clone(), shell.clone());

    let app = tauri::Builder::default()
        // 2つめを起こしたら、前の窓を前に出すだけ（常駐で隠れていても出す）
        .plugin(tauri_plugin_single_instance::init({
            let shell = shell.clone();
            move |app, _args, _cwd| show_main(app, &shell)
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .register_asynchronous_uri_scheme_protocol(SCHEME, move |_ctx, req, responder| {
            let shell = proto.clone();
            std::thread::spawn(move || {
                let resp = match shell.router.get() {
                    Some(r) => r.handle(&req),
                    None => {
                        let r = error_reply(503, "starting", "起動中です。");
                        let mut b = tauri::http::Response::builder().status(r.status);
                        for (k, v) in r.headers {
                            b = b.header(k, v);
                        }
                        b.body(r.body).unwrap()
                    }
                };
                responder.respond(resp);
            });
        })
        .on_window_event(move |w, e| {
            if let WindowEvent::CloseRequested { api, .. } = e {
                if w.label() == "main" {
                    api.prevent_close();
                    let (app, shell) = (w.app_handle().clone(), close_shell.clone());
                    // 中身へ聞くあいだ窓を止めないよう、裏の糸で判断する
                    std::thread::spawn(move || on_close_requested(&app, &shell));
                }
            }
        })
        .setup({
            let shell = shell.clone();
            move |app| {
                let handle = app.handle().clone();
                window(&handle, WebviewUrl::App("index.html".into()))?;
                match build_tray(&handle, shell.clone()) {
                    Ok(t) => *shell.tray.lock().unwrap() = Some(t),
                    Err(e) => eprintln!("TRAY_UNAVAILABLE {e}"),
                }
                if std::env::var_os("DATARELAY_SELFTEST").is_some() {
                    let h = handle.clone();
                    std::thread::spawn(move || {
                        std::thread::sleep(SELFTEST_LIMIT);
                        selftest_finish(&h, &json!({"ok": false, "error": format!("{} 秒で終わりませんでした", SELFTEST_LIMIT.as_secs())}));
                    });
                }
                std::thread::spawn(move || start(handle, shell));
                Ok(())
            }
        })
        .build(tauri::generate_context!())
        .expect("起動できません");

    app.run(move |_app, event| {
        if let RunEvent::Exit = event {
            if let Some(b) = shell.backend() {
                b.stop();
            }
        }
    });
}
