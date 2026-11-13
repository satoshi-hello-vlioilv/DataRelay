//! ワーカー（lib/api_worker.py）を起こして見守る（2.36.0〜）。navi_lanerun.run_api_process_batch のワーカー1本ぶんと、
//! app.kill_process_tree と同じ決まり。
//!
//! ワーカーとのやり取りはファイルだけ:
//!   - 渡す: payload.json（対象・設定・行き先。パスワードは書かない ―― ワーカーが自分で置き場から読む）
//!   - 受け取る: NAVI_WORKER_STATUS（工程の様子。ワーカーが書き換え続ける）・NAVI_WORKER_RESULT（結果。最後に1回）
//!   - 終了コード: 成功 0・失敗 2（それ以外は落ちた）
//!
//! Navigator の DLL はワーカーの中だけで呼ぶ（同じプロセスで呼ぶと保存が約10倍遅くなり、DLL が落ちると親ごと消えるため）。
//! 分割・競争ではワーカーがさらにワーカーを起こすので、止めるときは子ごと止める（Windows は taskkill /T）。
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// 起こすワーカー1本の決め事。
pub struct Spawn<'a> {
    /// ワーカーを動かす Python（窓がサイドカーに使うのと同じ物）
    pub python: &'a Path,
    /// アプリの場所（lib/api_worker.py がある所。ワーカーの今いるフォルダーにもする）
    pub program_root: &'a Path,
    /// このワーカーの作業フォルダー（payload.json・status.json・result.json を置く）
    pub dir: &'a Path,
    pub payload: &'a Value,
    /// 画面のライン名（「ライン 2」など。ワーカーが工程の様子に書く）
    pub line: &'a str,
}

/// 見守っているワーカー1本。
pub struct Worker {
    child: Child,
    pub line: String,
    pub job_name: String,
    pub status_path: PathBuf,
    pub result_path: PathBuf,
    started: Instant,
}

/// 終わったワーカーの結果。
#[derive(Debug)]
pub struct End {
    /// result.json の中身（読めない・打ち切ったときは Python と同じ言い方の失敗）
    pub result: Map<String, Value>,
    /// 終了コード（打ち切ったあと読めなければ None）
    pub code: Option<i32>,
    pub timed_out: bool,
}

fn read_json(p: &Path) -> Option<Value> {
    serde_json::from_str(&std::fs::read_to_string(p).ok()?).ok()
}

/// 終了コード（Windows はそのまま。POSIX の合図で終わったときは、Python の Popen と同じく −合図）。
fn exit_code(s: std::process::ExitStatus) -> Option<i32> {
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        s.code().or_else(|| s.signal().map(|g| -g))
    }
    #[cfg(not(unix))]
    {
        s.code()
    }
}

/// 分の数を f'{x:g}' と同じ形に（有効数字6桁。小数の終わりの 0 は落とす。10^-4 未満・10^6 以上は指数で書く）。
fn minutes_g(x: f64) -> String {
    if x == 0.0 || !x.is_finite() {
        return format!("{x}");
    }
    let trim = |t: String| if t.contains('.') { t.trim_end_matches('0').trim_end_matches('.').to_string() } else { t };
    // 6桁に丸めてから桁の位置を決める（9.999995 は 10 になる）
    let sci = format!("{x:.5e}");
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    if !(-4..6).contains(&exp) {
        return format!("{}e{}{:02}", trim(mant.to_string()), if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    let keep = (5 - exp).max(0) as usize;
    trim(format!("{x:.keep$}"))
}

impl Worker {
    /// payload.json を書いて、ワーカーを起こす。
    pub fn spawn(s: &Spawn) -> std::io::Result<Worker> {
        std::fs::create_dir_all(s.dir)?;
        let payload = s.dir.join("payload.json");
        let status_path = s.dir.join("status.json");
        let result_path = s.dir.join("result.json");
        std::fs::write(&payload, serde_json::to_vec(s.payload).unwrap_or_default())?;
        let at = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
        let mut cmd = Command::new(s.python);
        cmd.arg(s.program_root.join("lib").join("api_worker.py"))
            .arg(&payload)
            .current_dir(s.program_root)
            .env("NAVI_WORKER_LINE", s.line)
            .env("NAVI_WORKER_STATUS", &status_path)
            .env("NAVI_WORKER_RESULT", &result_path)
            .env("NAVI_WORKER_SPAWN_AT", format!("{at}"))
            .stdin(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        let child = cmd.spawn()?;
        let job_name = s.payload.get("job").and_then(|j| j.get("name")).map(crate::pyish::py_str).unwrap_or_default();
        Ok(Worker { child, line: s.line.into(), job_name, status_path, result_path, started: Instant::now() })
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    /// 起こしてからの秒。
    pub fn elapsed(&self) -> f64 {
        self.started.elapsed().as_secs_f64()
    }

    /// いまの工程の様子（ワーカーが書いた status.json。まだ無ければ None）。
    pub fn status(&self) -> Option<Map<String, Value>> {
        match read_json(&self.status_path)? {
            Value::Object(m) => Some(m),
            _ => None,
        }
    }

    /// 終わっていれば結果。limit を過ぎても終わらなければ、子ごと止めて打ち切りとして返す。まだなら None。
    pub fn poll(&mut self, limit: Option<Duration>) -> Option<End> {
        let done = self.child.try_wait().ok().flatten();
        let timed_out = done.is_none() && limit.is_some_and(|l| self.started.elapsed() > l);
        if done.is_none() && !timed_out {
            return None;
        }
        let code = match done {
            Some(s) => exit_code(s),
            None => {
                self.kill_tree(Duration::from_secs(5));
                self.child.try_wait().ok().flatten().and_then(exit_code)
            }
        };
        let mut fallback = Map::new();
        fallback.insert("ok".into(), Value::Bool(false));
        fallback.insert("job".into(), Value::String(self.job_name.clone()));
        let why = if timed_out {
            format!("応答が返らないため{}分で打ち切りました", minutes_g(limit.unwrap_or_default().as_secs_f64() / 60.0))
        } else {
            format!("Worker終了コード {}", code.map_or_else(|| "None".to_string(), |c| c.to_string()))
        };
        fallback.insert("error".into(), Value::String(why));
        fallback.insert("elapsed".into(), serde_json::json!(self.elapsed()));
        // 打ち切った側の result.json は書きかけのことがある。信じずに、打ち切りとして締める
        let result = if timed_out {
            fallback
        } else {
            match read_json(&self.result_path) {
                Some(Value::Object(m)) => m,
                _ => fallback,
            }
        };
        Some(End { result, code, timed_out })
    }

    /// 子ごと止める（kill_process_tree）。Windows はまず taskkill /T で木ごと頼み、駄目なら止める。
    pub fn kill_tree(&mut self, wait: Duration) {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let _ = Command::new("taskkill")
                .args(["/PID", &self.child.id().to_string(), "/T", "/F"])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .creation_flags(0x0800_0000)
                .status();
        }
        let _ = self.child.kill();
        let until = Instant::now() + wait;
        while Instant::now() < until {
            if self.child.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn minutes_like_python_g() {
        assert_eq!(minutes_g(120.0), "120");
        assert_eq!(minutes_g(0.5), "0.5");
        assert_eq!(minutes_g(1.0 / 3.0), "0.333333");
        assert_eq!(minutes_g(90.25), "90.25");
        assert_eq!(minutes_g(0.025), "0.025");
        assert_eq!(minutes_g(1234567.0), "1.23457e+06");
        assert_eq!(minutes_g(0.00001), "1e-05");
    }
}
