//! DataRelay デスクトップ版（Tauri）。ポートを使わず、ブラウザも使わない。
//!
//! 役割の分け方（migration/FEASIBILITY.md）:
//!   - Rust（この exe）: 窓・通知領域のアイコン・常駐（隠す・出す）・1つだけ起動・起動と終了・画面のひな形と静的ファイル・
//!     ファイル/フォルダーの選択・保存ダイアログ・エクスプローラーで開く・中身（Python）の監督と起こし直し
//!   - Python（sidecar.py → app.py）: 業務の処理のすべて（いまの Flask のまま。WSGI を標準入出力で呼ぶ）
//!   - 画面（WebView2）: いまの HTML/JS/CSS。問い合わせは自前の仕組み（datarelay）で Rust が受ける
//!
//! × を押すと、Python に「常駐を続ける理由」（実行中・キュー・自動実行の予定・影実行）を聞き、
//! 理由があれば窓を隠して通知領域に残る（自動実行はそのまま動く）。理由が無ければ後始末をして終わる。
//! Defect-Pitch-Analyzer のデスクトップ版（版 2.0.0）と同じ枠・同じ振り分けを使う。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod frame;
mod install;
mod locate;
mod release;
mod router;
mod sidecar;
mod update;

use router::{error_reply, Backend, Native, Router, Saver};
use serde_json::{json, Value};
use sidecar::{Ask, Reply, Supervisor, Watch};
use std::io::Write;
use std::path::{Path, PathBuf};
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
    /// 最後に中身を起こし直した時刻（UTC）。画面の「アプリ監視」に出す
    last_restart: Mutex<String>,
    /// 窓と中身の名乗り（版・置き場・Python）。準備できたら入る
    info: OnceLock<Value>,
    /// 起動のときに配る版へそろえたなら「前の版 → 新しい版」（画面の「アプリ監視」と通知に出す）
    release_note: Mutex<String>,
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

/// まだ OS へ出していない知らせ（/api/alerts の alerts のうち、info 以外）。題と本文の組を返す。
/// seen は「いま中身が持っている知らせ」で置き換える（読んで消えた知らせを覚え続けない）。
fn fresh_alerts(seen: &mut std::collections::HashSet<String>, v: &Value) -> Vec<(String, String)> {
    let items = v["alerts"].as_array().cloned().unwrap_or_default();
    let mut out = Vec::new();
    let mut now = std::collections::HashSet::new();
    for a in &items {
        let Some(id) = a["id"].as_str() else { continue };
        now.insert(id.to_string());
        if seen.contains(id) || a["kind"].as_str() == Some("info") {
            continue;
        }
        let title = a["title"].as_str().unwrap_or(TITLE).to_string();
        let detail: String = a["detail"].as_str().filter(|d| !d.is_empty()).unwrap_or(&title).chars().take(200).collect();
        out.push((title, detail));
    }
    *seen = now;
    out
}

fn hide_to_tray(app: &AppHandle, shell: &Shell, reason: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.hide();
    }
    shell.set_tooltip(&format!("{TITLE}（常駐中: {reason}）"));
    *shell.resident_reason.lock().unwrap() = reason.to_string();
    rlog(&format!("RESIDENT_ENTER reason={reason}"));
    notify(
        app,
        &format!("{TITLE} は常駐しています"),
        &format!("{reason}のため、通知領域に残って実行を続けます。\n開く・終了するには通知領域のアイコンを使ってください。"),
    );
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
    quit_or_restart(app, shell, source, false)
}

/// 開き直す（画面の「開き直して新しい版にする」）。後始末は終了と同じ。終わる前に新しい自分を `--after-pid` 付きで起こす
/// ——新しい窓はこの窓が終わるのを待ってから開き、起動のときに配る版へそろう（写していない形なら写しへ渡る）。
fn quit_or_restart(app: &AppHandle, shell: &Arc<Shell>, source: &str, restart: bool) {
    if shell.quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    rlog(&format!("QUIT source={source} restart={restart}"));
    shell.set_tooltip(&format!("{TITLE}（{}しています…）", if restart { "開き直" } else { "終了" }));
    let (app, shell, source) = (app.clone(), shell.clone(), source.to_string());
    std::thread::spawn(move || {
        if shell.backend().map(|b| b.is_alive()).unwrap_or(false) {
            let body = json!({"source": format!("desktop-{source}"), "wait_seconds": CLEANUP_WAIT}).to_string();
            match shell.ask_json("POST", "/api/app-cleanup", body.as_bytes()) {
                Ok(v) => rlog(&format!("CLEANUP done still_running={}", v["still_running"])),
                Err(e) => rlog(&format!("CLEANUP failed error={e}")),
            }
        }
        if restart {
            match install::relaunch(&own_exe(), "") {
                Ok(()) => rlog("RESTART relaunched"),
                Err(e) => rlog(&format!("RESTART_FAILED error={e}")),
            }
        }
        app.exit(0);
    });
}

/// 起こし直すときの exe。写したアプリなら写しの DataRelay.exe（入れ替えたあとも同じ道に新しい exe がある）、
/// ほかはいま動いている exe。
fn own_exe() -> PathBuf {
    let me = locate::exe().unwrap_or_else(|_| PathBuf::from(install::ENTRY));
    match me.parent() {
        Some(root) if release::installed(root) => root.join(install::ENTRY),
        _ => me,
    }
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
    Reply {
        status: 200,
        headers: vec![("Content-Type".into(), "application/json".into())],
        body: serde_json::to_vec(v).unwrap_or_default(),
    }
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
        if p.is_file() || (!folder && p.extension().is_some()) {
            p.parent().map(PathBuf::from).unwrap_or(p)
        } else {
            p
        }
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
                let exts: Vec<&str> =
                    pat.split(';').map(|x| x.trim().trim_start_matches("*.")).filter(|x| !x.is_empty() && *x != "*").collect();
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
        // 画面の「開き直して新しい版にする」: 中身に開き直してよいかを聞き（実行中・キューがあれば断る）、後始末を頼んで開き直す
        ("POST", "/api/restart-app") => {
            match shell.ask_json("GET", "/api/release/restart-check", b"") {
                Ok(v) if v["ok"].as_bool() == Some(false) => {
                    let why = v["reason"].as_str().unwrap_or("いまは開き直せません");
                    return Some(error_reply(409, "busy", &format!("{why}。終わってからもう一度押してください")));
                }
                Err(e) => rlog(&format!("RESTART check_unknown error={e}（中身が答えないので開き直します）")),
                _ => {}
            }
            let (app, shell) = (app.clone(), shell.clone());
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(150));
                quit_or_restart(&app, &shell, "ui-restart", true);
            });
            Some(json_reply(&json!({"ok": true, "status": "restarting"})))
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
        // 画面の「アプリ監視」: 窓と中身（Python）のつながり。中身が止まっていても窓が答える
        ("GET", "/api/desktop-status") => {
            let mut v = shell.backend().map(|b| b.status()).unwrap_or_else(|| json!({"alive": false, "spawned": 0, "restarts": 0}));
            v["shell_version"] = json!(env!("CARGO_PKG_VERSION"));
            v["python"] = shell.info.get().map(|i| i["python"].clone()).unwrap_or(Value::Null);
            v["program"] = shell.info.get().map(|i| i["program"].clone()).unwrap_or(Value::Null);
            v["last_restart"] = json!(*shell.last_restart.lock().unwrap());
            v["release_note"] = json!(*shell.release_note.lock().unwrap());
            for k in ["exe", "place", "pointer", "updated_from"] {
                v[k] = shell.info.get().map(|i| i[k].clone()).unwrap_or(Value::Null);
            }
            v["resident_reason"] = json!(*shell.resident_reason.lock().unwrap());
            Some(json_reply(&v))
        }
        ("GET", "/__desktop/info") => {
            let w = app.get_webview_window("main");
            Some(json_reply(&json!({
                "info": info,
                "mode": std::env::var("DATARELAY_SELFTEST_MODE").unwrap_or_default(),
                "relaunched": install::relaunched(),
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

/// Flask を読める Python を探す。どれにも無ければ部品（config\requirements.txt）を入れて探し直す
/// （1.95.0 までは start.vbs がしていたこと。初回だけ）。見つからなければ起動画面に理由を出して None。
fn find_python(app: &AppHandle, shell: &Shell, program: &Path, local: &Path) -> Option<locate::Python> {
    let e = match locate::python() {
        Ok(p) => return Some(p),
        Err(e) => e,
    };
    let (Some(target), Some(req)) = (e.candidate.clone().filter(|_| e.lacking), locate::requirements_file(program)) else {
        shell.step(app, "python", "bad", if e.lacking { "Flask が入っていません" } else { "見つかりません" });
        shell.fail(app, e.title(), &e.message);
        return None;
    };
    shell.step(app, "python", "now", "Flask などの部品を入れています（初回だけ。数分かかることがあります）");
    let log = local.join("logs").join("pip_install.log");
    rlog(&format!("INSTALL_REQUIREMENTS python={} requirements={}", target.exe.display(), req.display()));
    let t = std::time::Instant::now();
    let done =
        locate::install_requirements(&target, &req, &log, Duration::from_secs(900)).and_then(|_| locate::python().map_err(|e| e.message));
    rlog(&format!("INSTALL_REQUIREMENTS_DONE ok={} elapsed={:.1}s", done.is_ok(), t.elapsed().as_secs_f64()));
    match done {
        Ok(p) => Some(p),
        Err(why) => {
            shell.step(app, "python", "bad", "部品を入れられませんでした");
            let detail = format!(
                "{why}\n\n社内のネットワークから PyPI に届かないと入りません。次を実行するか、管理者に頼んでください:\n  \"{}\" -m pip install --user -r \"{}\"\n\npip の記録（最後の部分）: {}\n{}",
                target.exe.display(),
                req.display(),
                log.display(),
                sidecar::tail(&log, 12)
            );
            shell.fail(app, "必要な部品（Flask）を入れられませんでした", &detail);
            None
        }
    }
}

/// 中身（Python）を探して起こし、準備できたら画面へ切り替える（裏の糸で。窓とアイコンは先に出しておく）。
fn start(app: AppHandle, shell: Arc<Shell>) {
    if align_release(&app, &shell) {
        return;
    }
    shell.step(&app, "python", "now", "Flask を読める Python を探しています…");
    let (program, place) = match locate::program_dir() {
        Ok(p) => p,
        Err(e) => return shell.fail(&app, "アプリのフォルダが見つかりません", &e),
    };
    let local = locate::local_root();
    let Some(py) = find_python(&app, &shell, &program, &local) else { return };
    shell.step(&app, "python", "ok", &py.exe.display().to_string());
    shell.step(&app, "backend", "now", "Python でアプリの中身を読み込んでいます…");
    let pointer = match &place {
        locate::Place::Local { pointer } => pointer.display().to_string(),
        _ => String::new(),
    };
    rlog(&format!("START program={} place={} pointer={pointer} python={}", program.display(), place.label(), py.exe.display()));
    let sup = Arc::new(Supervisor::new(py.clone(), program.clone(), local.join("logs")));
    // 中身を起こすたびに残す。2回目からは起こし直し（見張りが起こしても、画面の問い合わせが起こしても同じ）
    {
        let (app, shell) = (app.clone(), shell.clone());
        sup.on_spawn(Box::new(move |ready, n| {
            rlog(&format!("BACKEND_READY version={} pid={} elapsed={}s spawn={n}", ready["version"], ready["pid"], ready["elapsed"]));
            if n > 1 {
                *shell.last_restart.lock().unwrap() = utc_now();
                rlog(&format!("BACKEND_RESTARTED spawn={n}"));
                notify(&app, TITLE, "アプリの中身（Python）が止まったため、起こし直しました。");
            }
        }));
    }
    let ready = match sup.get() {
        Ok(s) => s.ready.clone(),
        Err(e) if e.kind == "busy" => {
            shell.step(&app, "backend", "bad", "ほかの DataRelay が動いています");
            return shell.fail(
                &app,
                "もう1つの DataRelay が動いています",
                &format!("{}\n\n古い版のブラウザ版（start.vbs で起動するもの）なら、その画面右上の「終了」か、通知領域のアイコンの「終了」で終わらせてください。", e.message),
            );
        }
        Err(e) => {
            shell.step(&app, "backend", "bad", "起動できません");
            return shell.fail(
                &app,
                "アプリの中身（Python）が起動できません",
                &format!("{}\n\n記録: {}", e.message, local.join("logs").join("sidecar_stderr.log").display()),
            );
        }
    };
    let elapsed = ready["elapsed"].as_f64().unwrap_or(0.0);
    shell.step(
        &app,
        "backend",
        "ok",
        &format!("版 {} ・ {} bit ・ {:.1} 秒", ready["version"].as_str().unwrap_or("?"), ready["bits"], elapsed),
    );
    let exe = locate::exe().map(|p| p.display().to_string()).unwrap_or_default();
    let updated_from = std::env::var("DATARELAY_UPDATED").unwrap_or_default();
    let info = json!({"shell": "tauri", "shell_version": env!("CARGO_PKG_VERSION"), "program": program, "python": py.exe, "backend": ready, "local": local,
                      "exe": exe, "place": place.label(), "pointer": pointer, "updated_from": updated_from});
    let release_note = shell.release_note.lock().unwrap().clone();
    if !release_note.is_empty() {
        notify(&app, TITLE, &format!("配られた版にそろえました（{release_note}）。"));
    }
    if !updated_from.is_empty() {
        notify(
            &app,
            TITLE,
            &format!(
                "手元の DataRelay.exe を、共有のアプリに合わせて {updated_from} から {} に入れ替えました。",
                env!("CARGO_PKG_VERSION")
            ),
        );
    }
    let _ = shell.info.set(info.clone());
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
    let r = Router {
        static_dir: program.join("static"),
        index_file,
        backend: sup,
        native: native(app.clone(), shell.clone(), info),
        saver: saver(app.clone(), shell.clone()),
    };
    let _ = shell.router.set(r);
    shell.step(&app, "open", "now", "画面を開いています…");
    // 見回り: 5 秒ごとに中身の知らせ（抽出の失敗・取り直しなど）を OS の通知へ出し、20 秒ごとに通知領域の文言
    // （実行中 3/5・待機中など）を更新する。知らせは 1.95.0 までは Python が pywin32 のアイコンから出していた
    {
        let (app, shell) = (app.clone(), shell.clone());
        std::thread::spawn(move || {
            let mut seen = std::collections::HashSet::new();
            for tick in 1u64.. {
                std::thread::sleep(Duration::from_secs(5));
                if shell.quitting.load(Ordering::SeqCst) {
                    return;
                }
                if let Ok(v) = shell.ask_json("GET", "/api/alerts", b"") {
                    for (title, detail) in fresh_alerts(&mut seen, &v) {
                        rlog(&format!("ALERT_NOTIFY title={title}"));
                        notify(&app, &title, &detail);
                    }
                }
                if tick % 4 == 0 {
                    if let Ok(v) = shell.ask_json("GET", "/api/residency", b"") {
                        let text = v["status_text"].as_str().unwrap_or("");
                        let resident = shell.resident_reason.lock().unwrap().clone();
                        shell.set_tooltip(&if resident.is_empty() {
                            format!("{TITLE}（{text}）")
                        } else {
                            format!("{TITLE}（常駐中: {text}）")
                        });
                    }
                }
            }
        });
    }
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.navigate(app_url("/"));
    }
}

/// 配る版へそろえる（配布の置き場から写したアプリ・初回のインストール・release.rs）。中身（Python）を起こす前に、起動画面の中で。
/// → true なら起動を続けない（新しい exe で開き直す・初回に写せなかった）。
fn align_release(app: &AppHandle, shell: &Arc<Shell>) -> bool {
    let Some(root) = locate::exe().ok().and_then(|e| e.parent().map(Path::to_path_buf)) else { return false };
    let fresh = !root.join("app.py").is_file(); // まだ中身が無い（初回のインストール）
    if let Some(dir) = install::from_arg() {
        match release::mirror_seed(&root, &dir) {
            Ok(changed) => rlog(&format!("INSTALL_SEED dir={} changed={changed}", dir.display())),
            Err(e) if fresh => {
                shell.step(app, "update", "bad", "配布の置き場に届きません");
                shell.fail(
                    app,
                    "配布の置き場に届きません",
                    &format!("{e}\n\nBOX Drive が動いているか・ネットワークにつながっているかを確かめて、もう一度入口を開いてください。"),
                );
                return true;
            }
            Err(e) => rlog(&format!("INSTALL_SEED_FAILED dir={} error={e}（前の写しのまま）", dir.display())),
        }
    }
    if !release::installed(&root) {
        shell.step(app, "update", "skip", "配布の置き場から写したアプリではないので、確かめません");
        return false;
    }
    shell.step(app, "update", "now", "配る版を確かめています…");
    let stop_fresh = |why: &str| {
        shell.step(app, "update", "bad", "このPCへ写せませんでした");
        shell.fail(app, "アプリをこのPCへ写せませんでした", why);
        true
    };
    match release::peek(&root) {
        release::Peek::Same(v) => {
            // 前の窓がそろえてから新しい exe で開き直した: 前の窓が渡した「前の版 → 新しい版」を引き継ぐ
            if let Some(note) = std::env::var(install::RELEASED_ENV).ok().filter(|n| !n.is_empty()) {
                *shell.release_note.lock().unwrap() = note;
            }
            shell.step(app, "update", "ok", &format!("版 {v}（配る版と同じ）"));
            false
        }
        release::Peek::Skip(why) | release::Peek::Bad(why) if fresh => stop_fresh(&why),
        release::Peek::Skip(why) => {
            rlog(&format!("RELEASE_SKIPPED {why}"));
            shell.step(app, "update", "skip", &why);
            false
        }
        release::Peek::Bad(why) => {
            rlog(&format!("RELEASE_BAD {why}"));
            shell.step(app, "update", "bad", &why);
            false
        }
        release::Peek::Differs { have, want, dir } => {
            let progress = |m: &str| shell.step(app, "update", "now", m);
            match release::apply(&root, &dir, &have, &want, &|m: &str| rlog(m), &progress) {
                release::Outcome::Applied { from, to, exe_changed } => {
                    rlog(&format!("RELEASE_APPLIED from={from} to={to} exe_changed={exe_changed} dir={}", dir.display()));
                    let note = if from.is_empty() { String::new() } else { format!("{from} → {to}") };
                    *shell.release_note.lock().unwrap() = note.clone();
                    if exe_changed {
                        // 窓（exe）も変わった: 新しい exe で開き直す（この窓が終わるのを待ってから開く）
                        match install::relaunch(&root.join(install::ENTRY), &note) {
                            Ok(()) => {
                                shell.step(app, "update", "ok", &format!("版 {to} にそろえました。新しい窓で開き直します"));
                                app.exit(0);
                                return true;
                            }
                            Err(e) => rlog(&format!("RELEASE_RELAUNCH_FAILED error={e}（いまの窓で続けます）")),
                        }
                    }
                    shell.step(app, "update", "ok", &format!("版 {to} にそろえました"));
                    false
                }
                release::Outcome::Failed(e) if fresh => stop_fresh(&e),
                release::Outcome::Failed(e) => {
                    rlog(&format!("RELEASE_FAILED want={want} error={e}"));
                    shell.step(app, "update", "bad", &format!("そろえられませんでした（版 {have} のまま開きます）"));
                    notify(app, TITLE, &format!("配られた版 {want} にそろえられませんでした。版 {have} のまま開きます。\n{e}"));
                    false
                }
            }
        }
    }
}

/// 窓を作る前にすること（1つだけ起動の仕組みに登録する前）。この exe はここで終わるなら Some(終了コード)。
///   1. 入口・共有から直に動かす形で、置き場に配る版があれば、この PC の写しへ渡して終わる（install.rs）
///   2. 開き直しで起こされた（`--after-pid`）なら、前の窓が終わるのを待つ
///   3. 窓の錠を持つ（次に開き直す窓が、この窓の終わりを待てるように）
///   4. exe だけを手元に置いた形の自己更新（update.rs・配る版が無いときのこれまでの道）
fn early() -> Option<i32> {
    let _ = locate::exe(); // 退く前の exe の道を、何よりも先に覚える（release.rs が入れ替えると OS の答えが変わる）
    if install::from_arg().is_none() {
        if let Some(dir) = handoff_target() {
            match install::handoff(&dir, &|m: &str| rlog(m)) {
                install::Handoff::Done(_) => return Some(0),
                install::Handoff::Failed(e) => rlog(&format!("INSTALL_HANDOFF_FAILED dir={} error={e}（このまま動きます）", dir.display())),
            }
        }
    }
    if let Some(waited) = install::wait_for_previous(Duration::from_secs(45)) {
        rlog(&format!("AFTER_PREVIOUS waited={:.1}s", waited.as_secs_f64()));
    }
    install::hold_window_lock();
    self_update()
}

/// 写しへ渡す置き場（渡さないなら None）。入口（置き場の直下の DataRelay.exe）か、共有から直に動かしている形
/// （共有のアプリのフォルダーの exe・install_local.cmd の手元の exe）で、置き場に配る版があるとき。
fn handoff_target() -> Option<PathBuf> {
    let exe = locate::exe().ok()?;
    if let Some(dir) = install::shared_entry_dir(&exe) {
        return Some(dir);
    }
    let (program, place) = locate::program_dir().ok()?;
    if !matches!(place, locate::Place::Beside | locate::Place::Local { .. }) || program.join(".git").exists() {
        return None;
    }
    let (dir, _) = release::update_dir(&program);
    (install::is_release_dir(&dir) && matches!(release::release_version(&dir, release::REACH), Ok(Some(_)))).then_some(dir)
}

/// exe を手元に置いた形のとき、共有のアプリの版と食い違っていれば共有の exe で自分を入れ替えて起こし直す（update.rs）。
/// 起こし直したら Some(終了コード)。窓を作る前に呼ぶ（1つだけ起動の仕組みに登録する前なので、新しい exe とぶつからない）。
fn self_update() -> Option<i32> {
    let exe = locate::exe().ok()?;
    let (program, place) = locate::program_dir().ok()?;
    if !matches!(place, locate::Place::Local { .. }) {
        return None;
    }
    update::cleanup(&exe);
    if std::env::var_os("DATARELAY_UPDATED").is_some() {
        return None; // 入れ替えたあとの起動。もう一度は入れ替えない（版が食い違う置き方でも回り続けない）
    }
    let selftest = std::env::var_os("DATARELAY_SELFTEST").is_some();
    // 自己診断だけ: 古い版のふりをする・写す元を決める（入れ替えの道を本物の exe で通すため）
    let own = std::env::var("DATARELAY_SELFTEST_PRETEND_VERSION")
        .ok()
        .filter(|_| selftest)
        .unwrap_or_else(|| env!("CARGO_PKG_VERSION").to_string());
    let source = std::env::var_os("DATARELAY_SELFTEST_UPDATE_SOURCE")
        .filter(|_| selftest)
        .map(PathBuf::from)
        .unwrap_or_else(|| program.join(exe.file_name().unwrap_or_default()));
    let shared = update::program_version(&program);
    match update::decide(&own, shared.as_deref(), source.is_file()) {
        update::Decision::Keep => None,
        update::Decision::NoSource => {
            rlog(&format!(
                "EXE_UPDATE_SKIPPED own={own} shared={} detail=共有に exe がありません: {}",
                shared.unwrap_or_default(),
                source.display()
            ));
            None
        }
        update::Decision::Update => {
            let shared = shared.unwrap_or_default();
            if let Err(e) = update::swap(&exe, &source) {
                rlog(&format!("EXE_UPDATE_FAILED own={own} shared={shared} error={e}"));
                return None; // 入れ替えられなくても、いまの exe で動く
            }
            rlog(&format!("EXE_UPDATED from={own} to={shared} source={}", source.display()));
            let relaunch = std::process::Command::new(&exe)
                .args(std::env::args_os().skip(1))
                .arg(install::AFTER_ARG)
                .arg(std::process::id().to_string())
                .env("DATARELAY_UPDATED", &own)
                .spawn();
            match relaunch {
                Ok(_) => Some(0),
                Err(e) => {
                    rlog(&format!("EXE_RELAUNCH_FAILED error={e}"));
                    None
                }
            }
        }
    }
}

fn main() {
    if let Some(code) = early() {
        std::process::exit(code);
    }
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
    use super::fresh_alerts;
    use serde_json::json;

    #[test]
    fn alerts_are_notified_once_and_info_is_not() {
        let mut seen = std::collections::HashSet::new();
        let v = json!({"alerts": [
            {"id": "a", "kind": "error", "title": "抽出に失敗", "detail": "対象 X"},
            {"id": "b", "kind": "info", "title": "完了", "detail": ""},
            {"id": "c", "kind": "warn", "title": "取り直し待ち", "detail": ""}
        ]});
        assert_eq!(
            fresh_alerts(&mut seen, &v),
            vec![("抽出に失敗".into(), "対象 X".into()), ("取り直し待ち".into(), "取り直し待ち".into())]
        );
        assert!(fresh_alerts(&mut seen, &v).is_empty(), "同じ知らせは2回出さない");
        let v2 = json!({"alerts": [{"id": "c", "kind": "warn", "title": "取り直し待ち"}, {"id": "d", "kind": "error", "title": "公開に失敗", "detail": "共有が使用中"}]});
        assert_eq!(fresh_alerts(&mut seen, &v2), vec![("公開に失敗".into(), "共有が使用中".into())]);
        assert!(!seen.contains("a"), "読んで消えた知らせは覚え続けない");
    }

    #[test]
    fn utc_now_looks_like_a_date() {
        let t = super::utc_now();
        assert_eq!(t.len(), 20, "{t}");
        assert!(t.starts_with("20") && t.ends_with('Z'), "{t}");
    }
}
