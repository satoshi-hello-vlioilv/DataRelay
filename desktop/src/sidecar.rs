//! アプリの中身（Python・sidecar.py）を子プロセスで起こし、パイプの枠で問い合わせる。**ポートは使わない**。
//! Defect-Pitch-Analyzer の desktop/src/sidecar.rs（版 2.0.0）を土台にした。DataRelay で変えたところ:
//!   - 中身が止まったら、次の問い合わせを待たずにすぐ起こし直す（Supervisor::watch）。
//!     スケジューラーが中身の中にあり、窓を隠して常駐しているあいだは問い合わせが来ないため
//!   - 起こせない理由に種類を付ける（busy = ブラウザ版がすでに動いている。起こし直しても無駄なので繰り返さない）
//!
//! - 問い合わせごとに番号（id）を付けて送り、答えは読み手の糸が番号で持ち主へ返す（長い問い合わせが短いものを待たせない）
//! - 窓が終わればこの値が捨てられ、標準入力が閉じる → Python は入力の終わりを見て自分で終わる
//!   （親が強制終了されてもパイプは OS が閉じるので、子は残らない）
//! - 子が途中で止まったら、待っている問い合わせへ失敗を返し、Supervisor が次の問い合わせで起こし直す

use crate::frame::{read_frame, write_frame};
use crate::locate::Python;
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
    pub fn spawn(py: &Python, program: &Path, log_dir: &Path, wait: Duration) -> Result<Sidecar, SpawnError> {
        std::fs::create_dir_all(log_dir).ok();
        let err_log = log_dir.join("sidecar_stderr.log");
        let stderr = std::fs::File::create(&err_log).map(Stdio::from).unwrap_or_else(|_| Stdio::null());
        let mut cmd = Command::new(&py.exe);
        cmd.args(&py.args)
            .arg("-X")
            .arg("utf8")
            .arg(program.join("sidecar.py"))
            .current_dir(program)
            .env("PYTHONIOENCODING", "utf-8")
            .env("DATARELAY_SHELL", "desktop")
            .env("NAVI_LOCAL_ROOT", crate::locate::local_root())
            .env("PYTHONPYCACHEPREFIX", crate::locate::local_root().join("pycache"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(stderr);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd.spawn().map_err(|e| SpawnError::other(format!("Python を起動できません（{}）: {e}", py.exe.display())))?;
        let stdin = child.stdin.take().ok_or_else(|| SpawnError::other("標準入力を開けません"))?;
        let mut out = BufReader::with_capacity(1 << 16, child.stdout.take().ok_or_else(|| SpawnError::other("標準出力を開けません"))?);

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
                let kind = head["kind"].as_str().unwrap_or("other").to_string();
                let msg = head["error"].as_str().unwrap_or("理由不明").to_string();
                return Err(SpawnError { kind, message: if msg.is_empty() { "理由不明".into() } else { msg } });
            }
            Ok(Ok(None)) | Ok(Err(_)) => {
                let _ = child.wait();
                return Err(SpawnError::other(format!("アプリの中身（Python）がすぐに終わりました。\n{}", tail(&err_log, 12))));
            }
            Err(_) => {
                let _ = child.kill();
                return Err(SpawnError::other(format!(
                    "アプリの中身（Python）が {} 秒たっても準備できません。\n{}",
                    wait.as_secs(),
                    tail(&err_log, 12)
                )));
            }
        };
        let out = reader.join().map_err(|_| SpawnError::other("読み手の糸が止まりました"))?;

        let pending: Arc<Mutex<HashMap<u64, Sender<Reply>>>> = Arc::default();
        let alive = Arc::new(AtomicBool::new(true));
        let (p2, a2) = (pending.clone(), alive.clone());
        std::thread::Builder::new()
            .name("sidecar-reader".into())
            .spawn(move || read_loop(out, p2, a2))
            .map_err(|e| SpawnError::other(e.to_string()))?;
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

impl Sidecar {
    /// 入力を閉じて自分で終わるのを少し待ち、終わらなければ止める。何度呼んでもよい。
    /// 窓が終わるときは、ほかの糸がまだこの値を持っていても（問い合わせの途中など）必ずここを通す。
    /// 値が捨てられるのを待つだけでは、持っている糸があると後始末が走らず、中身が残ることがあった。
    pub fn shutdown(&self) {
        if let Ok(mut w) = self.stdin.lock() {
            drop(w.take()); // 出し切ってから閉じる
        }
        self.alive.store(false, Ordering::SeqCst);
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

impl Drop for Sidecar {
    fn drop(&mut self) {
        self.shutdown();
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
pub fn tail(path: &Path, lines: usize) -> String {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let v: Vec<&str> = text.lines().collect();
    v[v.len().saturating_sub(lines)..].join("\n")
}

/// 起こせなかった理由。kind は Python 側の知らせ（busy・import・boot）か other。
#[derive(Debug, Clone)]
pub struct SpawnError {
    pub kind: String,
    pub message: String,
}

impl SpawnError {
    pub fn other(m: impl Into<String>) -> Self {
        SpawnError { kind: "other".into(), message: m.into() }
    }
    /// 起こし直しても同じ結果になる理由か（ブラウザ版が動いている・アプリの読み込みに失敗した）。
    pub fn is_permanent(&self) -> bool {
        matches!(self.kind.as_str(), "busy" | "import")
    }
}

impl std::fmt::Display for SpawnError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

/// 中身の Python を1つ持ち、止まっていたら起こし直す係。
/// 中身を起こすたびに呼ばれる（準備できたときの知らせ, 何回目か）。起こし直しがどの道で起きても残すため。
pub type OnSpawn = Box<dyn Fn(&Value, u32) + Send + Sync>;

pub struct Supervisor {
    py: Python,
    program: PathBuf,
    log_dir: PathBuf,
    current: Mutex<Option<Arc<Sidecar>>>,
    stopping: AtomicBool,
    spawned: AtomicU64,
    on_spawn: Mutex<Option<OnSpawn>>,
    pub start_wait: Duration,
}

/// 見張りから窓へ伝えること（通知領域の文言・通知に使う）。
pub enum Watch {
    Failed { error: SpawnError, retry_in: Duration },
}

impl Supervisor {
    pub fn new(py: Python, program: PathBuf, log_dir: PathBuf) -> Self {
        Supervisor {
            py,
            program,
            log_dir,
            current: Mutex::new(None),
            stopping: AtomicBool::new(false),
            spawned: AtomicU64::new(0),
            on_spawn: Mutex::new(None),
            start_wait: Duration::from_secs(90),
        }
    }

    pub fn on_spawn(&self, f: OnSpawn) {
        *self.on_spawn.lock().unwrap() = Some(f);
    }

    /// 動いている中身（無ければ・止まっていれば起こす）。
    pub fn get(&self) -> Result<Arc<Sidecar>, SpawnError> {
        if self.stopping.load(Ordering::SeqCst) {
            return Err(SpawnError::other("終了しています"));
        }
        let mut cur = self.current.lock().unwrap();
        if let Some(s) = cur.as_ref() {
            if s.is_alive() {
                return Ok(s.clone());
            }
        }
        *cur = None; // 古いものを捨てる（Drop で後始末）
        let s = Arc::new(Sidecar::spawn(&self.py, &self.program, &self.log_dir, self.start_wait)?);
        *cur = Some(s.clone());
        let n = self.spawned.fetch_add(1, Ordering::SeqCst) + 1;
        if let Some(f) = self.on_spawn.lock().unwrap().as_ref() {
            f(&s.ready, n as u32);
        }
        Ok(s)
    }

    pub fn is_alive(&self) -> bool {
        self.current.lock().unwrap().as_ref().map(|s| s.is_alive()).unwrap_or(false)
    }

    /// いまの中身の様子（画面の「アプリ監視」に出す）。起こさずに見るだけ。
    pub fn status(&self) -> Value {
        let cur = self.current.lock().unwrap();
        let alive = cur.as_ref().map(|s| s.is_alive()).unwrap_or(false);
        let spawned = self.spawned.load(Ordering::SeqCst);
        json!({
            "alive": alive,
            "spawned": spawned,
            "restarts": spawned.saturating_sub(1),
            "backend": cur.as_ref().filter(|_| alive).map(|s| s.ready.clone()),
        })
    }

    /// 中身が止まったら、問い合わせを待たずに起こし直す（1秒ごとに見る）。
    /// 起こせなければ 2・4・8 … 最長 60 秒の間を空けて試し続ける（自動実行を朝まで止めない）。
    /// ブラウザ版が動いている（busy）など、起こし直しても無駄な理由ならやめる。
    pub fn watch(self: &Arc<Self>, report: impl Fn(Watch) + Send + 'static) {
        let me = self.clone();
        std::thread::Builder::new()
            .name("sidecar-watch".into())
            .spawn(move || {
                let mut backoff = Duration::from_secs(2);
                loop {
                    std::thread::sleep(Duration::from_secs(1));
                    if me.stopping.load(Ordering::SeqCst) {
                        return;
                    }
                    if me.is_alive() {
                        backoff = Duration::from_secs(2);
                        continue;
                    }
                    match me.get() {
                        Ok(_) => {} // 起こし直したことは on_spawn が残す
                        Err(e) => {
                            let permanent = e.is_permanent();
                            report(Watch::Failed { error: e, retry_in: backoff });
                            if permanent {
                                return;
                            }
                            std::thread::sleep(backoff);
                            backoff = (backoff * 2).min(Duration::from_secs(60));
                        }
                    }
                }
            })
            .ok();
    }

    /// 終わるとき: 見張りを止め、中身を終わらせる（入力を閉じる → Python が自分で終わる。3 秒で終わらなければ止める）。
    pub fn stop(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        if let Some(s) = self.current.lock().unwrap().take() {
            s.shutdown();
        }
    }
}
