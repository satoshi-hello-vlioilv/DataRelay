//! 画面（WebView）からの問い合わせの振り分け。得意なほうが答える:
//!   - /・/static/…        … Rust がディスクから直接返す（画面のひな形・JS・CSS。Python の起動を待たずに画面が出る）
//!   - 窓そのものの操作      … Rust（終了・ファイル選択・フォルダーを開く・自己診断。main.rs が native として渡す）
//!   - それ以外（画面・API） … Python（サイドカー）へそのまま渡す。答えはいまと同じ
//!   - Python の答えが「保存してください」（Content-Disposition: attachment）なら、窓の保存ダイアログで受ける
//!
//! Defect-Pitch-Analyzer の desktop/src/router.rs（版 2.0.0）を土台に、ダウンロードの受け止めを足した。
//!
//! 画面の JS は fetch("/api/...") のまま（同じ置き場への問い合わせ）で、ポートも CORS も要らない。

use crate::sidecar::{Ask, Reply, RequestError, Supervisor};
use serde_json::json;
use std::path::{Component, Path, PathBuf};
use std::time::Duration;
use tauri::http::{Request, Response};

/// 問い合わせを答えに変える係（試験では作り物に差し替える）。
pub trait Backend: Send + Sync {
    fn ask(&self, ask: &Ask) -> Reply;
}

/// 長い問い合わせ（RNEの調査・影実行の開始など）を待てる長さ。抽出そのものは裏で走り、画面は進み具合を聞きに来る。
const ASK_WAIT: Duration = Duration::from_secs(600);

impl Backend for Supervisor {
    fn ask(&self, ask: &Ask) -> Reply {
        // 送る前に止まっていた（Dead）なら起こし直して1度だけ送り直す。送った後に止まったものは送り直さない（二重に書かない）
        for attempt in 0..2 {
            let side = match self.get() {
                Ok(s) => s,
                Err(e) => return error_reply(503, if e.kind == "busy" { "busy" } else { "backend_unavailable" }, &e.message),
            };
            match side.request(ask, ASK_WAIT) {
                Ok(r) => return r,
                Err(RequestError::Dead) if attempt == 0 => continue,
                Err(RequestError::Timeout) => {
                    return error_reply(504, "backend_timeout", &format!("アプリの中身が {} 秒たっても答えません。", ASK_WAIT.as_secs()))
                }
                Err(_) => {
                    return error_reply(
                        503,
                        "backend_stopped",
                        "アプリの中身（Python）が途中で止まりました。もう一度お試しください（自動で起こし直します）。",
                    )
                }
            }
        }
        error_reply(503, "backend_stopped", "アプリの中身（Python）を起こし直せませんでした。")
    }
}

/// 窓は監督を見張りの糸とも分け合うので、Arc に包んだまま渡せるようにする。
impl<T: Backend> Backend for std::sync::Arc<T> {
    fn ask(&self, ask: &Ask) -> Reply {
        (**self).ask(ask)
    }
}

pub fn error_reply(status: u16, kind: &str, message: &str) -> Reply {
    Reply {
        status,
        headers: vec![("Content-Type".into(), "application/json".into())],
        body: serde_json::to_vec(&json!({"error": message, "kind": kind})).unwrap_or_default(),
    }
}

/// 窓そのものが答える問い合わせ（method, path, 本文）→ 答え。None ならほかへ回す。
pub type Native = Box<dyn Fn(&str, &str, &[u8]) -> Option<Reply> + Send + Sync>;

/// ダウンロードの受け止め（保存名, 中身）→ 保存した場所。None は利用者が取り消した。
pub type Saver = Box<dyn Fn(&str, &[u8]) -> Result<Option<PathBuf>, String> + Send + Sync>;

pub struct Router<B: Backend> {
    pub static_dir: PathBuf,
    /// 画面のひな形（templates/index.html）。差し込みが1つも無い静的な HTML なので Rust が返す
    pub index_file: PathBuf,
    pub backend: B,
    pub native: Native,
    pub saver: Saver,
}

impl<B: Backend> Router<B> {
    pub fn handle(&self, req: &Request<Vec<u8>>) -> Response<Vec<u8>> {
        let uri = req.uri();
        let path = uri.path();
        let query = uri.query().unwrap_or("");
        let method = req.method().as_str();
        let (reply, by) = if let Some(r) = (self.native)(method, path, req.body()) {
            (r, "shell")
        } else if (method == "GET" || method == "HEAD") && path == "/" {
            (index_page(&self.index_file), "shell")
        } else if let (true, Some(rest)) = (method == "GET" || method == "HEAD", path.strip_prefix("/static/")) {
            (static_file(&self.static_dir, rest, query), "shell")
        } else {
            let headers = req.headers().iter().filter_map(|(k, v)| Some((k.as_str().to_string(), v.to_str().ok()?.to_string()))).collect();
            let reply = self.backend.ask(&Ask { method, path, query, headers, body: req.body() });
            (self.save_if_attachment(reply), "python")
        };
        to_response(reply, by)
    }

    /// 「保存してください」の答えは、窓の保存ダイアログで受けてファイルに書く。画面へは 204（移動しない）で返す。
    /// WebView2 の既定のダウンロード（自前の仕組みの答え）に任せると、保存先も通知も WebView 次第になるため。
    fn save_if_attachment(&self, reply: Reply) -> Reply {
        let disp = reply.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case("content-disposition")).map(|(_, v)| v.clone());
        let Some(name) = disp.as_deref().and_then(attachment_name) else { return reply };
        match (self.saver)(&name, &reply.body) {
            Ok(Some(path)) => {
                Reply { status: 204, headers: vec![("X-DR-Saved".into(), percent_encode(&path.to_string_lossy()))], body: Vec::new() }
            }
            Ok(None) => Reply { status: 204, headers: vec![("X-DR-Saved".into(), String::new())], body: Vec::new() },
            Err(e) => error_reply(500, "save_failed", &format!("保存できませんでした: {e}")),
        }
    }
}

fn to_response(r: Reply, by: &str) -> Response<Vec<u8>> {
    let mut b = Response::builder().status(r.status);
    for (k, v) in &r.headers {
        b = b.header(k.as_str(), v.as_str());
    }
    // どちらが答えたか（自己診断・不具合の切り分けに使う）
    b = b.header("X-DR-By", by);
    b.body(r.body).unwrap_or_else(|_| Response::builder().status(500).body(Vec::new()).unwrap())
}

/// 画面のひな形。Flask の / と同じく、毎回読み直させる（版を入れ替えた直後に古い画面を見せない）。
pub fn index_page(file: &Path) -> Reply {
    match std::fs::read(file) {
        Ok(body) => Reply {
            status: 200,
            headers: vec![
                ("Content-Type".into(), "text/html; charset=utf-8".into()),
                ("Cache-Control".into(), "no-store, no-cache, must-revalidate, max-age=0".into()),
            ],
            body,
        },
        Err(e) => error_reply(500, "index_missing", &format!("画面のひな形が読めません（{}）: {e}", file.display())),
    }
}

/// 保存名（filename*=UTF-8''… を優先。Flask の send_file は日本語の名前をこの形で付ける）。attachment でなければ None。
pub fn attachment_name(disp: &str) -> Option<String> {
    let lower = disp.to_ascii_lowercase();
    if !lower.trim_start().starts_with("attachment") {
        return None;
    }
    let mut plain = None;
    for part in disp.split(';').map(str::trim) {
        if let Some(v) = part.strip_prefix("filename*=") {
            let v = v.trim_matches('"');
            let v = v.splitn(3, '\'').nth(2).unwrap_or(v);
            return Some(percent_decode(v));
        }
        if let Some(v) = part.strip_prefix("filename=") {
            plain = Some(v.trim_matches('"').to_string());
        }
    }
    Some(plain.unwrap_or_else(|| "download".into()))
}

fn percent_encode(s: &str) -> String {
    s.bytes()
        .map(|b| if b.is_ascii_alphanumeric() || b"-_.~/:\\".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") })
        .collect()
}

/// /static/ の下のファイル。アプリの static の外へは出ない（.. や絶対パスは断る）。
pub fn static_file(root: &Path, rest: &str, query: &str) -> Reply {
    let decoded = percent_decode(rest);
    let rel = Path::new(&decoded);
    if rel.components().any(|c| !matches!(c, Component::Normal(_))) {
        return error_reply(404, "not_found", "ありません。");
    }
    match std::fs::read(root.join(rel)) {
        Ok(body) => {
            // 版の付いた URL（?v=指紋。Flask の url_for が付ける）は中身が変わらないので長く使い回す
            let cache = if query.split('&').any(|kv| kv.starts_with("v=")) { "public, max-age=31536000, immutable" } else { "no-cache" };
            Reply {
                status: 200,
                headers: vec![("Content-Type".into(), mime(&decoded).into()), ("Cache-Control".into(), cache.into())],
                body,
            }
        }
        Err(_) => error_reply(404, "not_found", "ありません。"),
    }
}

pub fn mime(path: &str) -> &'static str {
    let ext = path.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "html" | "htm" => "text/html; charset=utf-8",
        "json" | "map" => "application/json",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "ico" => "image/x-icon",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "wasm" => "application/wasm",
        "txt" | "md" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

fn percent_decode(s: &str) -> String {
    let hex = |c: u8| (c as char).to_digit(16).map(|d| d as u8);
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h << 4 | l);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    struct Echo(Mutex<Vec<String>>);
    impl Backend for Echo {
        fn ask(&self, a: &Ask) -> Reply {
            self.0.lock().unwrap().push(format!("{} {}?{} {}", a.method, a.path, a.query, String::from_utf8_lossy(a.body)));
            Reply { status: 201, headers: vec![("Content-Type".into(), "text/plain".into())], body: b"py".to_vec() }
        }
    }

    fn router(dir: &Path) -> Router<Echo> {
        Router {
            static_dir: dir.to_path_buf(),
            index_file: dir.join("index.html"),
            backend: Echo(Mutex::default()),
            native: Box::new(|m, p, _| (m == "POST" && p == "/api/shutdown").then(|| error_reply(200, "stopping", "終了します"))),
            saver: Box::new(|name, body| Ok(Some(PathBuf::from(format!("/saved/{name}/{}", body.len()))))),
        }
    }

    fn req(method: &str, uri: &str, body: &[u8]) -> Request<Vec<u8>> {
        Request::builder().method(method).uri(uri).body(body.to_vec()).unwrap()
    }

    #[test]
    fn each_kind_goes_to_its_place() {
        let dir = std::env::temp_dir().join(format!("dr-router-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("js")).unwrap();
        std::fs::write(dir.join("js").join("app.js"), "x=1").unwrap();
        std::fs::write(dir.join("js").join("日本.css"), "a{}").unwrap();
        let r = router(&dir);

        let s = r.handle(&req("GET", "datarelay://localhost/static/js/app.js?v=abc", b""));
        assert_eq!((s.status().as_u16(), s.body().as_slice()), (200, b"x=1".as_slice()));
        assert_eq!(s.headers()["content-type"], "text/javascript; charset=utf-8");
        assert_eq!(s.headers()["x-dr-by"], "shell", "静的ファイルは Rust");
        assert!(s.headers()["cache-control"].to_str().unwrap().contains("immutable"), "版付きは使い回す");
        assert_eq!(r.handle(&req("GET", "datarelay://localhost/static/js/app.js", b"")).headers()["cache-control"], "no-cache");
        assert_eq!(r.handle(&req("GET", "datarelay://localhost/static/js/%E6%97%A5%E6%9C%AC.css", b"")).status(), 200, "日本語の名前");

        for bad in ["/static/../secret.txt", "/static/js/%2e%2e/%2e%2e/x", "/static//etc/passwd", "/static/js/none.js"] {
            assert_eq!(r.handle(&req("GET", &format!("datarelay://localhost{bad}"), b"")).status(), 404, "{bad}");
        }

        let p = r.handle(&req("POST", "http://datarelay.localhost/api/calculate?a=1", "本文".as_bytes()));
        assert_eq!((p.status().as_u16(), p.headers()["x-dr-by"].to_str().unwrap()), (201, "python"));
        assert_eq!(r.backend.0.lock().unwrap().last().unwrap(), "POST /api/calculate?a=1 本文", "本文・問い合わせ文字はそのまま");

        let n = r.handle(&req("POST", "datarelay://localhost/api/shutdown", b""));
        assert_eq!((n.status().as_u16(), n.headers()["x-dr-by"].to_str().unwrap()), (200, "shell"), "窓の操作は Rust");
        std::fs::write(dir.join("index.html"), "<!doctype html>画面").unwrap();
        let top = r.handle(&req("GET", "datarelay://localhost/", b""));
        assert_eq!((top.status().as_u16(), top.headers()["x-dr-by"].to_str().unwrap()), (200, "shell"), "画面のひな形は Rust");
        assert!(top.headers()["cache-control"].to_str().unwrap().contains("no-store"), "毎回読み直させる");
        assert_eq!(r.handle(&req("GET", "datarelay://localhost/api/config", b"")).headers()["x-dr-by"], "python", "API は Python");
        std::fs::remove_dir_all(&dir).ok();
    }

    struct Attach;
    impl Backend for Attach {
        fn ask(&self, _a: &Ask) -> Reply {
            Reply {
                status: 200,
                headers: vec![
                    ("Content-Type".into(), "application/zip".into()),
                    (
                        "Content-Disposition".into(),
                        "attachment; filename=DataRelay.zip; filename*=UTF-8''DataRelay_%E4%B8%80%E5%BC%8F.zip".into(),
                    ),
                ],
                body: vec![1, 2, 3],
            }
        }
    }

    #[test]
    fn attachment_goes_to_save_dialog() {
        let r = Router {
            static_dir: PathBuf::from("."),
            index_file: PathBuf::from("index.html"),
            backend: Attach,
            native: Box::new(|_, _, _| None),
            saver: Box::new(|name, body| Ok(Some(PathBuf::from(format!("/saved/{name}/{}", body.len()))))),
        };
        let s = r.handle(&req("GET", "http://datarelay.localhost/api/bundle/export", b""));
        assert_eq!(s.status(), 204, "画面は移動しない");
        assert_eq!(percent_decode(s.headers()["x-dr-saved"].to_str().unwrap()), "/saved/DataRelay_一式.zip/3", "日本語の保存名と中身");
    }

    #[test]
    fn attachment_names() {
        assert_eq!(attachment_name("attachment; filename=a.zip").as_deref(), Some("a.zip"));
        assert_eq!(attachment_name("attachment; filename*=UTF-8''%E9%9B%86%E8%A8%88.xlsx").as_deref(), Some("集計.xlsx"));
        assert_eq!(attachment_name("inline; filename=a.zip"), None, "表示用は保存しない");
        assert_eq!(attachment_name("attachment").as_deref(), Some("download"));
    }

    #[test]
    fn decode() {
        assert_eq!(percent_decode("a%20b%E6%97%A5"), "a b日");
        assert_eq!(percent_decode("100%"), "100%");
        assert_eq!(percent_decode("%zz"), "%zz");
        assert_eq!(percent_decode("%日本"), "%日本", "% の後ろが文字でも落ちない");
        assert_eq!(percent_decode("a%4"), "a%4");
    }
}
