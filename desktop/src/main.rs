//! DataRelay デスクトップ版（Tauri）。ポートを使わず、ブラウザも使わない。
//!
//! 役割の分け方（migration/FEASIBILITY.md）:
//!   - Rust（この exe）: 窓・通知領域のアイコン・常駐（隠す・出す）・1つだけ起動・起動と終了・画面のひな形と静的ファイル・
//!                      ファイル/フォルダーの選択・保存ダイアログ・エクスプローラーで開く・中身（Python）の監督と起こし直し
//!   - Python（sidecar.py → app.py）: 業務の処理のすべて（いまの Flask のまま。WSGI を標準入出力で呼ぶ）
//!   - 画面（WebView2）: いまの HTML/JS/CSS。問い合わせは自前の仕組み（datarelay）で Rust が受ける
//!
//! × を押すと、Python に「常駐を続ける理由」（実行中・キュー・自動実行の予定・影実行）を聞き、
//! 理由があれば窓を隠して通知領域に残る（自動実行はそのまま動く）。理由が無ければ後始末をして終わる。
//! Defect-Pitch-Analyzer のデスクトップ版（版 2.0.0）と同じ枠・同じ振り分けを使う。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod frame;
mod locate;
mod router;
mod sidecar;

use router::{error_reply, Backend, Native, Router, Saver};
use serde_json::{json, Value};
use sidecar::{Ask, Reply, Supervisor, Watch};
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::webview::PageLoadEvent;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_notification::NotificationExt;

const SCHEME: &str = "datarelay";
const TITLE: &str = "DataRelay";
const SELFTEST_JS: &str = include_str!("selftest.js");
const SELFTEST_LIMIT: Duration = Duration::from_secs(150);
/// 後始末（実行中なら中断・ワーカーを止める・設定を書き出す）を待つ長さ。Python 側は 30 秒まで待つ。
const CLEANUP_WAIT: u64 = 30;

fn app_url(path: &str) -> Url {
    let base = if cfg!(windows) { "http://datarelay.localhost" } else { "datarelay://localhost" };
    Url::parse(&format!("{base}{path}")).expect("app url")
}

fn is_app_url(u: &Url) -> bool {
    u.scheme() == SCHEME || u.host_str() == Some("datarelay.localhost")
}

fn is_splash(u: &Url) -> bool {
    u.scheme() == "tauri" || u.host_str() == Some("tauri.localhost")
}

/// 窓の側の出来事を残す（%LOCALAPPDATA%\DataRelay\logs\desktop.log）。中身の記録（app.log）とは別。
fn rlog(msg: &str) {
    let dir = locate::local_root().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("desktop.log")) {
        let _ = writeln!(f, "{} [pid {}] {msg}", utc_now(), std::process::id());
    }
}

/// いまの時刻（UTC）を "2026-10-02 10:53:56Z" の形で。時刻の部品（クレート）を足さずに暦へ直す。
fn utc_now() -> String {
    let secs = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let (days, rem) = ((secs / 86_400) as i64, secs % 86_400);
    // 1970-01-01 からの日数 → 年月日（Howard Hinnant の civil_from_days）
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02} {:02}:{:02}:{:02}Z", rem / 3600, rem % 3600 / 60, rem % 60)
}

type AppRouter = Router<Arc<Supervisor>>;

#[derive(Default)]
struct Shell {
    router: OnceLock<AppRouter>,
    tray: Mutex<Option<TrayIcon>>,
    resident_reason: Mutex<String>,
    saved: Mutex<Vec<String>>,
    quitting: AtomicBool,
    splash_loaded: AtomicBool,
    splash_queue: Mutex<Vec<String>>,
}

impl Shell {
    fn backend(&self) -> Option<&Arc<Supervisor>> {
        self.router.get().map(|r| &r.backend)
    }

    fn ask_json(&self, method: &str, path: &str, body: &[u8]) -> Result<Value, String> {
        let b = self.backend().ok_or("起動中です")?;
        let headers = if body.is_empty() { vec![] } else { vec![("Content-Type".into(), "application/json".into())] };
        let r = b.ask(&Ask { method, path, query: "", headers, body });
        if r.status != 200 {
            return Err(format!("{path} が {} を返しました", r.status));
        }
        serde_json::from_slice(&r.body).map_err(|e| e.to_string())
    }

    /// 設定に書かれたパス（アプリフォルダー基準の相対・<PC>・環境変数）を実際の場所へ直す。
    /// 直し方の決まりは Python の resolve_path だけが持つ（/api/path-convert）。窓が別に真似ると食い違う。
    /// 中身がまだ答えられないときは、書かれたまま使う。
    fn resolve_path(&self, raw: &str) -> PathBuf {
        let body = json!({"value": raw, "mode": "absolute"}).to_string();
        self.ask_json("POST", "/api/path-convert", body.as_bytes())
            .ok()
            .and_then(|v| v["resolved"].as_str().filter(|s| !s.is_empty()).map(PathBuf::from))
            .unwrap_or_else(|| PathBuf::from(raw))
    }

    /// 常駐を続ける理由（Python の residency_reason）。無ければ空文字。
    fn residency_reason(&self) -> Result<String, String> {
        Ok(self.ask_json("GET", "/api/residency", b"")?["reason"].as_str().unwrap_or("").to_string())
    }

    fn set_tooltip(&self, text: &str) {
        if let Some(t) = self.tray.lock().unwrap().as_ref() {
            let _ = t.set_tooltip(Some(text));
        }
    }

    /// 起動画面へ伝える。読み終わる前の分はためておき、読み終わったら流す。
    fn splash(&self, app: &AppHandle, js: String) {
        if self.splash_loaded.load(Ordering::SeqCst) {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.eval(&js);
            }
        } else {
            self.splash_queue.lock().unwrap().push(js);
        }
    }
    fn step(&self, app: &AppHandle, id: &str, state: &str, detail: &str) {
        self.splash(app, format!("splash.step(...{})", json!([id, state, detail])));
    }
    fn fail(&self, app: &AppHandle, title: &str, detail: &str) {
        rlog(&format!("START_FAILED {title}: {detail}"));
        self.splash(app, format!("splash.fail(...{})", json!([title, detail])));
        selftest_finish(app, &json!({"ok": false, "error": format!("{title}: {detail}")}));
    }
}

fn notify(app: &AppHandle, title: &str, body: &str) {
    if std::env::var_os("DATARELAY_SELFTEST").is_some() {
        return; // 自己診断では通知を出さない（CI の画面に残るだけ）
    }
    let _ = app.notification().builder().title(title).body(body).show();
}

fn hide_to_tray(app: &AppHandle, shell: &Shell, reason: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.hide();
    }
    shell.set_tooltip(&format!("{TITLE}（常駐中: {reason}）"));
    *shell.resident_reason.lock().unwrap() = reason.to_string();
    rlog(&format!("RESIDENT_ENTER reason={reason}"));
    notify(app, &format!("{TITLE} は常駐しています"), &format!("{reason}のため、通知領域に残って実行を続けます。\n開く・終了するには通知領域のアイコンを使ってください。"));
}

fn show_main(app: &AppHandle, shell: &Shell) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
    if !shell.resident_reason.lock().unwrap().is_empty() {
        rlog("RESIDENT_LEAVE");
    }
    shell.resident_reason.lock().unwrap().clear();
    shell.set_tooltip(TITLE);
}

/// × を押したとき。常駐の理由があれば隠して通知領域に残る。無ければ後始末をして終わる。
/// 理由を聞けなければ（中身が止まっている等）終わる ―― 見えないまま残る方が困るため。
fn on_close_requested(app: &AppHandle, shell: &Arc<Shell>) {
    if shell.quitting.load(Ordering::SeqCst) {
        return;
    }
    match shell.residency_reason() {
        Ok(reason) if !reason.is_empty() => hide_to_tray(app, shell, &reason),
        Ok(_) => quit_app(app, shell, "close"),
        Err(e) => {
            rlog(&format!("CLOSE residency_unknown error={e} action=exit"));
            quit_app(app, shell, "close-unknown")
        }
    }
}

/// 終了。先に Python へ後始末を頼み（実行中なら中断・ワーカーと非表示の SymfoNavi を止める・設定を書き出す）、
/// 答えが返ってから終わる。終われば Python の入力が閉じ、Python は自分で終わる。
fn quit_app(app: &AppHandle, shell: &Arc<Shell>, source: &str) {
    if shell.quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    rlog(&format!("QUIT source={source}"));
    shell.set_tooltip(&format!("{TITLE}（終了しています…）"));
    let (app, shell, source) = (app.clone(), shell.clone(), source.to_string());
    std::thread::spawn(move || {
        if shell.backend().map(|b| b.is_alive()).unwrap_or(false) {
            let body = json!({"source": format!("desktop-{source}"), "wait_seconds": CLEANUP_WAIT}).to_string();
            match shell.ask_json("POST", "/api/app-cleanup", body.as_bytes()) {
                Ok(v) => rlog(&format!("CLEANUP done still_running={}", v["still_running"])),
                Err(e) => rlog(&format!("CLEANUP failed error={e}")),
            }
        }
        app.exit(0);
    });
}

/// 通知領域のアイコン。左クリックで開く。右のメニューに「画面を開く」「終了」。
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
            "quit" => quit_app(app, &s1, "tray"),
            _ => {}
        })
        .on_tray_icon_event(move |tray, e| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = e {
                show_main(tray.app_handle(), &s2);
            }
        })
        .build(app)
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

/// ファイル・フォルダーの選択。答えの形は {"path": "..."}（ブラウザ版の tkinter と同じ）。
/// 初期フォルダーは設定のパスなので、Python と同じ決まりで実際の場所へ直してから使う。
/// 自己診断ではダイアログを出せない（押す人がいない）ので、決めた場所と、直した初期フォルダーを返す。
fn pick(app: &AppHandle, shell: &Shell, folder: bool, body: &[u8]) -> Reply {
    let req: Value = serde_json::from_slice(body).unwrap_or(json!({}));
    let initial = req["initial"].as_str().map(str::trim).filter(|s| !s.is_empty()).map(|s| shell.resolve_path(s)).map(|p| {
        if p.is_file() || (!folder && p.extension().is_some()) { p.parent().map(PathBuf::from).unwrap_or(p) } else { p }
    });
    if let Some(dir) = selftest_dir() {
        let shown = initial.as_ref().map(|p| p.to_string_lossy().into_owned());
        return json_reply(&json!({"path": dir.to_string_lossy(), "initial": shown, "selftest": true}));
    }
    let mut d = app.dialog().file();
    if let Some(dir) = initial.filter(|d| d.is_dir()) {
        d = d.set_directory(dir);
    }
    if let Some(types) = req["types"].as_array() {
        for t in types {
            if let (Some(name), Some(pat)) = (t.get(0).and_then(Value::as_str), t.get(1).and_then(Value::as_str)) {
                let exts: Vec<&str> = pat.split(';').map(|x| x.trim().trim_start_matches("*.")).filter(|x| !x.is_empty() && *x != "*").collect();
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
        ("POST", "/api/pick-file") => Some(pick(&app, &shell, false, body)),
        ("POST", "/api/pick-folder") => Some(pick(&app, &shell, true, body)),
        // エクスプローラーで開く（ブラウザ版の os.startfile）。ファイルなら、そのファイルを選んだ状態でフォルダーを開く
        ("POST", "/api/open-path") => {
            use tauri_plugin_opener::OpenerExt;
            let req: Value = serde_json::from_slice(body).unwrap_or(json!({}));
            let raw = req["path"].as_str().unwrap_or("").trim();
            if raw.is_empty() {
                return Some(error_reply(400, "no_path", "出力先が指定されていません"));
            }
            // 出力先は相対（アプリフォルダー基準）・<PC> のことがある。窓の作業フォルダー基準で読むと別の場所になる
            let p = shell.resolve_path(raw);
            let target = p.to_string_lossy().into_owned();
            if !p.exists() {
                return Some(error_reply(404, "not_found", &format!("出力先が見つかりません: {target}")));
            }
            if selftest_dir().is_some() {
                return Some(json_reply(&json!({"ok": true, "selftest": true, "path": target})));
            }
            let r = if p.is_file() { app.opener().reveal_item_in_dir(&p) } else { app.opener().open_path(&target, None::<&str>) };
            Some(match r {
                Ok(_) => json_reply(&json!({"ok": true, "path": target})),
                Err(e) => error_reply(400, "open_failed", &format!("開けませんでした: {e}")),
            })
        }
        // 画面の「終了」: 答えてから、後始末を頼んで終わる
        ("POST", "/api/shutdown-app") => {
            let (app, shell) = (app.clone(), shell.clone());
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(150));
                quit_app(&app, &shell, "ui");
            });
            Some(json_reply(&json!({"ok": true, "status": "stopping"})))
        }
        // 画面の「タスクバーへ」: 窓を隠して通知領域に残る（アイコンは窓が持つので、いつでも引き受けられる）
        ("POST", "/api/stay-resident") => {
            let reason = shell.residency_reason().ok().filter(|r| !r.is_empty()).unwrap_or_else(|| "タスクバーへ入れるよう頼まれた".into());
            let (app2, shell2, r2) = (app.clone(), shell.clone(), reason.clone());
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(150));
                hide_to_tray(&app2, &shell2, &r2);
            });
            Some(json_reply(&json!({"ok": true, "tray_available": true, "reason": reason, "desktop": true})))
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
        // 自己診断: 窓を閉じる操作（×と同じ道）を起こす・通知領域から開く操作を起こす・結果を受け取る
        ("POST", "/__desktop/close") if std::env::var_os("DATARELAY_SELFTEST").is_some() => {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.close();
            }
            Some(json_reply(&json!({"requested": true})))
        }
        ("POST", "/__desktop/show") if std::env::var_os("DATARELAY_SELFTEST").is_some() => {
            show_main(&app, &shell);
            Some(json_reply(&json!({"shown": true})))
        }
        ("POST", "/__desktop/note") if std::env::var_os("DATARELAY_SELFTEST").is_some() => {
            if let Some(p) = std::env::var_os("DATARELAY_SELFTEST") {
                let _ = std::fs::write(PathBuf::from(p).with_extension("note.json"), body);
            }
            Some(json_reply(&json!({"noted": true})))
        }
        ("POST", "/__desktop/selftest") if std::env::var_os("DATARELAY_SELFTEST").is_some() => {
            let result: Value = serde_json::from_slice(body).unwrap_or_else(|e| json!({"ok": false, "error": e.to_string()}));
            selftest_finish(&app, &result);
            Some(json_reply(&json!({"received": true})))
        }
        _ => None,
    })
}

/// ダウンロードの受け止め（登録内容の ZIP・集計結果の EXCEL など）。窓の保存ダイアログで場所を聞き、書く。
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
        rlog(&format!("SAVED file={}", path.display()));
        shell.saved.lock().unwrap().push(path.to_string_lossy().into_owned());
        Ok(Some(path))
    })
}

fn window(app: &AppHandle, shell: Arc<Shell>) -> tauri::Result<WebviewWindow> {
    let nav = app.clone();
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title(TITLE)
        .inner_size(1600.0, 1000.0)
        .min_inner_size(1100.0, 700.0)
        .maximized(true)
        .background_color(tauri::window::Color(0xf3, 0xf6, 0xf8, 0xff))
        .on_navigation(move |u| {
            let inside = is_app_url(u) || is_splash(u) || matches!(u.scheme(), "about" | "blob" | "data");
            if !inside && matches!(u.scheme(), "http" | "https" | "mailto" | "file") {
                use tauri_plugin_opener::OpenerExt;
                let _ = nav.opener().open_url(u.as_str(), None::<&str>);
            }
            inside
        })
        .on_page_load(move |w, p| {
            if p.event() != PageLoadEvent::Finished {
                return;
            }
            if is_splash(p.url()) {
                shell.splash_loaded.store(true, Ordering::SeqCst);
                for js in shell.splash_queue.lock().unwrap().drain(..) {
                    let _ = w.eval(&js);
                }
            } else if is_app_url(p.url()) && p.url().path() == "/" && std::env::var_os("DATARELAY_SELFTEST").is_some() {
                let _ = w.eval(SELFTEST_JS);
            }
        })
        .build()
}

/// 中身（Python）を探して起こし、準備できたら画面へ切り替える（裏の糸で。窓とアイコンは先に出しておく）。
fn start(app: AppHandle, shell: Arc<Shell>) {
    let program = match locate::program_dir() {
        Ok(p) => p,
        Err(e) => return shell.fail(&app, "アプリのフォルダが見つかりません", &e),
    };
    let local = locate::local_root();
    let py = match locate::python(&local) {
        Ok(p) => p,
        Err(e) => {
            shell.step(&app, "python", "bad", if e.lacking { "Flask が入っていません" } else { "見つかりません" });
            return shell.fail(&app, e.title(), &e.message);
        }
    };
    shell.step(&app, "python", "ok", &py.exe.display().to_string());
    shell.step(&app, "backend", "now", "Python でアプリの中身を読み込んでいます…");
    rlog(&format!("START program={} python={}", program.display(), py.exe.display()));
    let sup = Arc::new(Supervisor::new(py.clone(), program.clone(), local.join("logs")));
    // 中身を起こすたびに残す。2回目からは起こし直し（見張りが起こしても、画面の問い合わせが起こしても同じ）
    {
        let app = app.clone();
        sup.on_spawn(Box::new(move |ready, n| {
            rlog(&format!("BACKEND_READY version={} pid={} elapsed={}s spawn={n}", ready["version"], ready["pid"], ready["elapsed"]));
            if n > 1 {
                rlog(&format!("BACKEND_RESTARTED spawn={n}"));
                notify(&app, TITLE, "アプリの中身（Python）が止まったため、起こし直しました。");
            }
        }));
    }
    let ready = match sup.get() {
        Ok(s) => s.ready.clone(),
        Err(e) if e.kind == "busy" => {
            shell.step(&app, "backend", "bad", "ほかの DataRelay が動いています");
            return shell.fail(&app, "ブラウザ版（または別の DataRelay）が動いています", &format!("{}\n\nブラウザ版を終了するには、画面右上の「終了」か、通知領域のアイコンの「終了」を使ってください。", e.message));
        }
        Err(e) => {
            shell.step(&app, "backend", "bad", "起動できません");
            return shell.fail(&app, "アプリの中身（Python）が起動できません", &format!("{}\n\n記録: {}", e.message, local.join("logs").join("sidecar_stderr.log").display()));
        }
    };
    let elapsed = ready["elapsed"].as_f64().unwrap_or(0.0);
    shell.step(&app, "backend", "ok", &format!("版 {} ・ {} bit ・ {:.1} 秒", ready["version"].as_str().unwrap_or("?"), ready["bits"], elapsed));
    let info = json!({"shell": "tauri", "shell_version": env!("CARGO_PKG_VERSION"), "program": program, "python": py.exe, "backend": ready, "local": local});
    // 止まったらすぐ起こし直す（常駐中は問い合わせが来ないので、待っていると自動実行が止まったままになる）
    {
        let (app, shell) = (app.clone(), shell.clone());
        sup.watch(move |w| match w {
            Watch::Failed { error, retry_in } => {
                rlog(&format!("BACKEND_RESTART_FAILED kind={} retry_in={}s error={}", error.kind, retry_in.as_secs(), error.message));
                if error.is_permanent() {
                    shell.set_tooltip(&format!("{TITLE}（中身を起こせません）"));
                    notify(&app, &format!("{TITLE}: 中身を起こせません"), &error.message);
                }
            }
        });
    }
    let index_file = program.join("templates").join("index.html");
    let r = Router { static_dir: program.join("static"), index_file, backend: sup, native: native(app.clone(), shell.clone(), info), saver: saver(app.clone(), shell.clone()) };
    let _ = shell.router.set(r);
    shell.step(&app, "open", "now", "画面を開いています…");
    // 通知領域の文言を、いまの状態（実行中 3/5・待機中など）に合わせて更新する
    {
        let shell = shell.clone();
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_secs(20));
            if shell.quitting.load(Ordering::SeqCst) {
                return;
            }
            if let Ok(v) = shell.ask_json("GET", "/api/residency", b"") {
                let text = v["status_text"].as_str().unwrap_or("");
                let resident = shell.resident_reason.lock().unwrap().clone();
                shell.set_tooltip(&if resident.is_empty() { format!("{TITLE}（{text}）") } else { format!("{TITLE}（常駐中: {text}）") });
            }
        });
    }
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.navigate(app_url("/"));
    }
}

fn main() {
    let shell: Arc<Shell> = Arc::default();
    let (proto, close_shell) = (shell.clone(), shell.clone());

    let app = tauri::Builder::default()
        // 2つめを起こしたら、前の窓を前に出すだけ（常駐で隠れていても出す）。ポートを見て止め直す仕組みが要らない
        .plugin(tauri_plugin_single_instance::init({
            let shell = shell.clone();
            move |app, _args, _cwd| show_main(app, &shell)
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        // 画面からの問い合わせ（datarelay）。1つずつ別の糸で答える（長い問い合わせが画面を止めない）
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
                if w.label() == "main" && !close_shell.quitting.load(Ordering::SeqCst) {
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
                window(&handle, shell.clone())?;
                match build_tray(&handle, shell.clone()) {
                    Ok(t) => *shell.tray.lock().unwrap() = Some(t),
                    Err(e) => rlog(&format!("TRAY_UNAVAILABLE error={e}")),
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
            // 中身の Python を止める（入力を閉じる → 自分で終わる。終わらなければ止める）
            if let Some(b) = shell.backend() {
                b.stop();
            }
            rlog("EXIT");
        }
    });
}

#[cfg(test)]
mod tests {
    #[test]
    fn utc_now_looks_like_a_date() {
        let t = super::utc_now();
        assert_eq!(t.len(), 20, "{t}");
        assert!(t.starts_with("20") && t.ends_with('Z'), "{t}");
    }
}
