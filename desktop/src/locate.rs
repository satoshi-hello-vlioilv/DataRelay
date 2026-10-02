//! 置き場所を探す: アプリのフォルダ（app.py・sidecar.py がある所）・Python・この PC の作業場所。
//! 決まりはブラウザ版（start.vbs・start_app.py）に合わせる。同じ Python・同じ作業場所を使う。
//! Defect-Pitch-Analyzer の desktop/src/locate.rs（版 2.0.0）を土台にした。

use std::env;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// アプリのフォルダ。DATARELAY_PROGRAM があればそれ。無ければこの exe の場所から上へたどって
/// app.py と sidecar.py が並ぶ所（配る形: exe を app.py の隣に置く。作る途中: desktop/target/release/ から3つ上）。
pub fn program_dir() -> Result<PathBuf, String> {
    if let Some(p) = env::var_os("DATARELAY_PROGRAM") {
        let p = PathBuf::from(p);
        return if is_program(&p) { Ok(p) } else { Err(format!("DATARELAY_PROGRAM に app.py と sidecar.py がありません: {}", p.display())) };
    }
    let exe = env::current_exe().map_err(|e| e.to_string())?;
    find_program_from(&exe).ok_or_else(|| {
        format!(
            "アプリのフォルダ（app.py と sidecar.py がある所）が見つかりません。この exe を app.py と同じフォルダに置いてください。\n探し始めた場所: {}",
            exe.parent().unwrap_or(&exe).display()
        )
    })
}

fn is_program(d: &Path) -> bool {
    d.join("app.py").is_file() && d.join("sidecar.py").is_file() && d.join("lib").is_dir()
}

pub fn find_program_from(start: &Path) -> Option<PathBuf> {
    start.ancestors().skip(1).take(6).find(|d| is_program(d)).map(Path::to_path_buf)
}

/// この PC の作業場所（start_app.py と同じ決まり: NAVI_LOCAL_ROOT、無ければ %LOCALAPPDATA%\DataRelay）。
pub fn local_root() -> PathBuf {
    if let Some(p) = env::var_os("NAVI_LOCAL_ROOT") {
        return PathBuf::from(p);
    }
    let base = env::var_os("LOCALAPPDATA").or_else(|| env::var_os("TEMP")).map(PathBuf::from).unwrap_or_else(home);
    base.join("DataRelay")
}

fn home() -> PathBuf {
    env::var_os("USERPROFILE").or_else(|| env::var_os("HOME")).map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}

/// Python の起こし方（exe と、前に付ける引数）。
#[derive(Clone, Debug, PartialEq)]
pub struct Python {
    pub exe: PathBuf,
    pub args: Vec<String>,
}

fn plain(exe: PathBuf) -> Python {
    Python { exe, args: vec![] }
}

/// 起こし方の候補（先にあるほど優先）。
///   1. DATARELAY_PYTHON
///   2. ブラウザ版が前回の起動で使った Python（start.vbs が runtime\startup_cache.txt に残す PYTHON=…）
///   3. start.vbs と同じ順: py -3 → python
///   4. 標準の入れ場所（新しい版から）
/// pythonw は使わない（標準入出力が無い前提で動くため。窓は CREATE_NO_WINDOW で出さない）。
pub fn python_candidates(local: &Path) -> Vec<Python> {
    let mut out = Vec::new();
    if let Some(p) = env::var_os("DATARELAY_PYTHON") {
        out.push(plain(PathBuf::from(p)));
    }
    if let Some(cmd) = startup_cache_python(local) {
        out.push(command_to_python(&cmd));
    }
    if cfg!(windows) {
        let windir = env::var_os("WINDIR").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(r"C:\Windows"));
        out.push(Python { exe: windir.join("py.exe"), args: vec!["-3".into()] });
        out.push(plain(PathBuf::from("py")).with_args(&["-3"]));
    }
    out.push(plain(PathBuf::from(if cfg!(windows) { "python" } else { "python3" })));
    if cfg!(windows) {
        let mut installed = Vec::new();
        for root in [env::var_os("LOCALAPPDATA").map(|p| PathBuf::from(p).join("Programs").join("Python")), env::var_os("ProgramFiles").map(PathBuf::from)]
            .into_iter()
            .flatten()
        {
            if let Ok(rd) = std::fs::read_dir(&root) {
                for e in rd.flatten() {
                    let name = e.file_name().to_string_lossy().to_string();
                    if let Some(v) = python_dir_version(&name) {
                        installed.push((v, e.path().join("python.exe")));
                    }
                }
            }
        }
        installed.sort_by(|a, b| b.0.cmp(&a.0));
        out.extend(installed.into_iter().map(|(_, p)| plain(p)));
    }
    out
}

impl Python {
    fn with_args(mut self, a: &[&str]) -> Python {
        self.args = a.iter().map(|s| s.to_string()).collect();
        self
    }
}

/// start.vbs の起動記録から PYTHON=… を読む（"py -3"・"python"・フルパスのどれか）。
pub fn startup_cache_python(local: &Path) -> Option<String> {
    let text = std::fs::read(local.join("runtime").join("startup_cache.txt")).ok()?;
    let text = String::from_utf8_lossy(&text);
    text.lines().find_map(|l| l.trim().strip_prefix("PYTHON=").map(|v| v.trim().to_string())).filter(|v| !v.is_empty())
}

/// "py -3" → py と ["-3"]。"\"C:\\Python312\\python.exe\"" → そのパス。
pub fn command_to_python(cmd: &str) -> Python {
    let cmd = cmd.trim();
    if let Some(rest) = cmd.strip_prefix('"') {
        if let Some(end) = rest.find('"') {
            let args = rest[end + 1..].split_whitespace().map(str::to_string).collect();
            return Python { exe: PathBuf::from(&rest[..end]), args };
        }
    }
    if Path::new(cmd).is_file() {
        return plain(PathBuf::from(cmd));
    }
    let mut parts = cmd.split_whitespace();
    let exe = parts.next().unwrap_or("python");
    Python { exe: PathBuf::from(exe), args: parts.map(str::to_string).collect() }
}

/// 候補を順に試し、実体の python.exe の場所（sys.executable）を返す。
/// py ランチャーを挟んだまま起こすと、窓から止めたときに本体が残りうるので、本体を直接起こす。
pub fn python(local: &Path) -> Result<Python, String> {
    let cands = python_candidates(local);
    let mut tried = Vec::new();
    for c in &cands {
        match resolve(c) {
            Ok(p) => return Ok(p),
            Err(e) => tried.push(format!("  {} {} … {e}", c.exe.display(), c.args.join(" "))),
        }
    }
    Err(format!("Python が見つかりません。ブラウザ版（start.vbs）と同じ Python 3 を使います。\n試したもの:\n{}", tried.join("\n")))
}

fn resolve(c: &Python) -> Result<Python, String> {
    let mut cmd = Command::new(&c.exe);
    cmd.args(&c.args).args(["-c", "import sys;print(sys.executable)"]).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(format!("終了コード {:?}", out.status.code()));
    }
    let exe = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let p = PathBuf::from(&exe);
    if exe.is_empty() || !p.is_file() {
        return Err(format!("sys.executable が読めません（{exe}）"));
    }
    // pythonw.exe が返ったら隣の python.exe を使う（標準入出力を使うため）
    if p.file_name().map(|n| n.to_string_lossy().eq_ignore_ascii_case("pythonw.exe")).unwrap_or(false) {
        let sib = p.with_file_name("python.exe");
        if sib.is_file() {
            return Ok(plain(sib));
        }
    }
    Ok(plain(p))
}

/// "Python312" → Some(312)。"Python3" の後ろが数字でなければ None。
fn python_dir_version(name: &str) -> Option<u32> {
    let rest = name.strip_prefix("Python3").or_else(|| name.strip_prefix("python3"))?;
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        return None;
    }
    format!("3{digits}").parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_program_next_to_the_exe_or_above() {
        let tmp = env::temp_dir().join(format!("dr-locate-{}", std::process::id()));
        std::fs::create_dir_all(tmp.join("lib")).unwrap();
        std::fs::write(tmp.join("app.py"), "").unwrap();
        std::fs::write(tmp.join("sidecar.py"), "").unwrap();
        let deep = tmp.join("desktop").join("target").join("release");
        std::fs::create_dir_all(&deep).unwrap();
        assert_eq!(find_program_from(&tmp.join("DataRelay.exe")), Some(tmp.clone()), "配る形（exe を app.py の隣に置く）");
        assert_eq!(find_program_from(&deep.join("DataRelay.exe")), Some(tmp.clone()), "作る途中（3つ上）");
        assert_eq!(find_program_from(&env::temp_dir().join("nowhere").join("x.exe")), None);
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn reads_the_browser_versions_python() {
        let tmp = env::temp_dir().join(format!("dr-cache-{}", std::process::id()));
        std::fs::create_dir_all(tmp.join("runtime")).unwrap();
        std::fs::write(tmp.join("runtime").join("startup_cache.txt"), "PYTHON=py -3\r\nREQSIG=abc\r\n").unwrap();
        assert_eq!(startup_cache_python(&tmp).as_deref(), Some("py -3"));
        assert_eq!(command_to_python("py -3"), Python { exe: PathBuf::from("py"), args: vec!["-3".into()] });
        assert_eq!(command_to_python("\"C:\\Program Files\\Python312\\python.exe\""), plain(PathBuf::from("C:\\Program Files\\Python312\\python.exe")));
        assert_eq!(startup_cache_python(&tmp.join("none")), None);
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn resolves_the_real_interpreter() {
        // この試験を流している Python（PATH の python3/python）の実体が取れる
        let p = python(&env::temp_dir().join("dr-no-cache")).expect("python");
        assert!(p.exe.is_file(), "{}", p.exe.display());
        assert!(p.args.is_empty(), "本体を直接起こす（ランチャーを挟まない）");
    }

    #[test]
    fn python_folders_newest_first() {
        assert_eq!(python_dir_version("Python312"), Some(312));
        assert_eq!(python_dir_version("Python313-32"), Some(313));
        assert_eq!(python_dir_version("Python3"), None);
        assert!(python_dir_version("Python313").unwrap() > python_dir_version("Python39").unwrap());
    }
}
