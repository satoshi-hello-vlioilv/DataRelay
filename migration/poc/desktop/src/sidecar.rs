//! アプリの中身（Python・migration/poc/sidecar.py）を子プロセスで起こし、パイプの枠で問い合わせる。**ポートは使わない**。
//! Defect-Pitch-Analyzer の desktop/src/sidecar.rs（版 2.0.0）を土台に、置き場の探し方だけ DataRelay に合わせた。
//!
//! - 問い合わせごとに番号（id）を付けて送り、答えは読み手の糸が番号で持ち主へ返す（長い問い合わせが短いものを待たせない）
//! - 窓が終わればこの値が捨てられ、標準入力が閉じる → Python は入力の終わりを見て自分で終わる
//!   （親が強制終了されてもパイプは OS が閉じるので、子は残らない）
//! - 子が途中で止まったら、待っている問い合わせへ失敗を返し、Supervisor が次の問い合わせで起こし直す

use crate::frame::{read_frame, write_frame};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufReader, BufWriter};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// 答え（HTTP の答えと同じ中身）。
#[derive(Debug, Clone)]
pub struct Reply {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

/// 問い合わせ（窓が受けた HTTP の問い合わせを、そのまま渡す形）。
pub struct Ask<'a> {
    pub method: &'a str,
    pub path: &'a str,
    pub query: &'a str,
    pub headers: Vec<(String, String)>,
    pub body: &'a [u8],
}

pub struct Sidecar {
    /// 書き口。終わるときに先に閉じる（閉じれば Python は入力の終わりを見て自分で終わる）
    stdin: Mutex<Option<BufWriter<ChildStdin>>>,
    pending: Arc<Mutex<HashMap<u64, Sender<Reply>>>>,
    next: AtomicU64,
    alive: Arc<AtomicBool>,
    child: Mutex<Child>,
    /// 準備できたときの知らせ（版・指紋・Python の場所・起動にかかった秒）
    pub ready: Value,
}

impl Sidecar {
    /// 起こして「準備できた」を待つ。起動できない理由（Python の誤り）はそのまま返す。
    pub fn spawn(py: &Python, program: &Path, log_dir: &Path, wait: Duration) -> Result<Sidecar, String> {
        std::fs::create_dir_all(log_dir).ok();
        let err_log = log_dir.join("sidecar_stderr.log");
        let stderr = std::fs::File::create(&err_log).map(Stdio::from).unwrap_or_else(|_| Stdio::null());
        let mut cmd = Command::new(&py.exe);
        cmd.args(&py.args)
            .arg("-X")
            .arg("utf8")
            .arg(program.join("migration").join("poc").join("sidecar.py"))
            .current_dir(program)
            .env("PYTHONIOENCODING", "utf-8")
            .env("DATARELAY_SHELL", "desktop")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(stderr);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd.spawn().map_err(|e| format!("Python を起動できません（{}）: {e}", py.exe.display()))?;
        let stdin = child.stdin.take().ok_or("標準入力を開けません")?;
        let mut out = BufReader::with_capacity(1 << 16, child.stdout.take().ok_or("標準出力を開けません")?);

        // 最初の枠は「準備できた」か「起動できない」。Python の読み込み（数秒）を待つ
        let (tx, rx) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            let first = read_frame(&mut out);
            let _ = tx.send(first.map(|f| f.map(|f| f.head)));
            out
        });
        let first = rx.recv_timeout(wait);
        let ready = match first {
            Ok(Ok(Some(head))) if head["event"] == "ready" => head,
            Ok(Ok(Some(head))) => {
                let _ = child.kill();
                return Err(format!("アプリの中身（Python）が起動できませんでした: {}", head["error"].as_str().unwrap_or("理由不明")));
            }
            Ok(Ok(None)) | Ok(Err(_)) => {
                let _ = child.wait();
                return Err(format!("アプリの中身（Python）がすぐに終わりました。\n{}", tail(&err_log, 12)));
            }
            Err(_) => {
                let _ = child.kill();
                return Err(format!("アプリの中身（Python）が {} 秒たっても準備できません。\n{}", wait.as_secs(), tail(&err_log, 12)));
            }
        };
        let out = reader.join().map_err(|_| "読み手の糸が止まりました")?;

        let pending: Arc<Mutex<HashMap<u64, Sender<Reply>>>> = Arc::default();
        let alive = Arc::new(AtomicBool::new(true));
        let (p2, a2) = (pending.clone(), alive.clone());
        std::thread::Builder::new().name("sidecar-reader".into()).spawn(move || read_loop(out, p2, a2)).map_err(|e| e.to_string())?;
        Ok(Sidecar {
            stdin: Mutex::new(Some(BufWriter::new(stdin))),
            pending,
            next: AtomicU64::new(1),
            alive,
            child: Mutex::new(child),
            ready,
        })
    }

    pub fn is_alive(&self) -> bool {
        self.alive.load(Ordering::SeqCst)
    }

    /// 1つ問い合わせて答えを待つ。送れない・止まった・時間切れは誤り（画面には 503/504 で返す）。
    pub fn request(&self, ask: &Ask, wait: Duration) -> Result<Reply, RequestError> {
        if !self.is_alive() {
            return Err(RequestError::Dead);
        }
        let id = self.next.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = mpsc::channel();
        self.pending.lock().unwrap().insert(id, tx);
        let mut headers = serde_json::Map::new();
        for (k, v) in &ask.headers {
            // 同じ名前が並ぶときは HTTP と同じく「, 」でつなぐ
            let joined = match headers.get(k).and_then(Value::as_str) {
                Some(prev) => format!("{prev}, {v}"),
                None => v.clone(),
            };
            headers.insert(k.clone(), Value::from(joined));
        }
        let head = json!({"id": id, "method": ask.method, "path": ask.path, "query": ask.query, "headers": headers});
        let sent = match self.stdin.lock().unwrap().as_mut() {
            Some(w) => write_frame(w, &head, ask.body),
            None => Err(std::io::Error::from(std::io::ErrorKind::BrokenPipe)),
        };
        if sent.is_err() {
            self.pending.lock().unwrap().remove(&id);
            self.alive.store(false, Ordering::SeqCst);
            return Err(RequestError::Dead);
        }
        match rx.recv_timeout(wait) {
            Ok(r) => Ok(r),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                self.pending.lock().unwrap().remove(&id);
                Err(RequestError::Timeout)
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(RequestError::Died),
        }
    }
}

impl Drop for Sidecar {
    /// 入力を閉じて自分で終わるのを少し待ち、終わらなければ止める。
    fn drop(&mut self) {
        if let Ok(mut w) = self.stdin.lock() {
            drop(w.take()); // 出し切ってから閉じる
        }
        let mut child = self.child.lock().unwrap();
        let end = Instant::now() + Duration::from_millis(3000);
        while Instant::now() < end {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            std::thread::sleep(Duration::from_millis(30));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[derive(Debug, PartialEq)]
pub enum RequestError {
    /// 送る前から止まっている（次の問い合わせで起こし直す）
    Dead,
    /// 答えを待つ間に止まった
    Died,
    Timeout,
}

fn read_loop(mut out: BufReader<std::process::ChildStdout>, pending: Arc<Mutex<HashMap<u64, Sender<Reply>>>>, alive: Arc<AtomicBool>) {
    while let Ok(Some(f)) = read_frame(&mut out) {
        let id = f.head["id"].as_u64().unwrap_or(0);
        if id == 0 {
            continue; // 知らせ（今は ready だけ。答えではない）
        }
        let headers = f.head["headers"]
            .as_array()
            .map(|a| a.iter().filter_map(|kv| Some((kv.get(0)?.as_str()?.to_string(), kv.get(1)?.as_str()?.to_string()))).collect())
            .unwrap_or_default();
        let reply = Reply { status: f.head["status"].as_u64().unwrap_or(500) as u16, headers, body: f.body };
        if let Some(tx) = pending.lock().unwrap().remove(&id) {
            let _ = tx.send(reply);
        }
    }
    // 止まった: 待っている問い合わせへ知らせる（送り手を捨てると受け手は Disconnected）
    alive.store(false, Ordering::SeqCst);
    pending.lock().unwrap().clear();
}

/// 記録の終わりの数行（起動できない理由を画面に出すため）。
pub fn tail(path: &PathBuf, lines: usize) -> String {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let v: Vec<&str> = text.lines().collect();
    v[v.len().saturating_sub(lines)..].join("\n")
}

/// 中身の Python を1つ持ち、止まっていたら次の問い合わせで起こし直す係。
pub struct Supervisor {
    py: Python,
    program: PathBuf,
    log_dir: PathBuf,
    current: Mutex<Option<Arc<Sidecar>>>,
    pub start_wait: Duration,
}

impl Supervisor {
    pub fn new(py: Python, program: PathBuf, log_dir: PathBuf) -> Self {
        Supervisor { py, program, log_dir, current: Mutex::new(None), start_wait: Duration::from_secs(90) }
    }

    /// 動いている中身（無ければ・止まっていれば起こす）。
    pub fn get(&self) -> Result<Arc<Sidecar>, String> {
        let mut cur = self.current.lock().unwrap();
        if let Some(s) = cur.as_ref() {
            if s.is_alive() {
                return Ok(s.clone());
            }
        }
        *cur = None; // 古いものを捨てる（Drop で後始末）
        let s = Arc::new(Sidecar::spawn(&self.py, &self.program, &self.log_dir, self.start_wait)?);
        *cur = Some(s.clone());
        Ok(s)
    }

    /// 終わるとき: 中身を捨てる（入力を閉じる → Python が自分で終わる）。
    pub fn stop(&self) {
        self.current.lock().unwrap().take();
    }
}

/// 中身を起こす Python（exe と前に付ける引数）。
#[derive(Debug, Clone)]
pub struct Python {
    pub exe: PathBuf,
    pub args: Vec<String>,
}

impl Python {
    /// DATARELAY_PYTHON があればそれ。無ければ Windows は pythonw（窓を出さない）、ほかは python3。
    /// 本番では start.vbs と同じ探し方（PATH・py ランチャー・標準の入れ場所）にする。
    pub fn find() -> Python {
        if let Some(p) = std::env::var_os("DATARELAY_PYTHON") {
            return Python { exe: PathBuf::from(p), args: vec![] };
        }
        Python { exe: PathBuf::from(if cfg!(windows) { "pythonw" } else { "python3" }), args: vec![] }
    }
}

/// アプリのフォルダ（app.py のある所）。DATARELAY_PROGRAM があればそれ、無ければ exe の場所から上へたどる。
pub fn program_dir() -> Result<PathBuf, String> {
    if let Some(p) = std::env::var_os("DATARELAY_PROGRAM") {
        return Ok(PathBuf::from(p));
    }
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    exe.ancestors()
        .find(|d| d.join("app.py").is_file() && d.join("lib").is_dir())
        .map(Path::to_path_buf)
        .ok_or_else(|| format!("app.py が見つかりません（{} から上へ探しました）", exe.display()))
}
