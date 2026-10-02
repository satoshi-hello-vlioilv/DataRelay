//! 置き場所を探す: アプリのフォルダ（app.py・sidecar.py がある所）・Python・この PC の作業場所。
//! 決まりは 1.95.0 までのブラウザ版（start.vbs・start_app.py）を引き継いだ。同じ Python・同じ作業場所を使う。
//! Defect-Pitch-Analyzer の desktop/src/locate.rs（版 2.0.0）を土台にした。

use std::env;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// exe を手元に置いた形の印。exe の隣のこのファイルに、共有のアプリのフォルダーを1行で書く（install_local.cmd が書く）。
/// `#` で始まる行と空の行は読まない。UTF-8 で書く。
pub const POINTER_FILE: &str = "DataRelay.program.txt";

/// アプリのフォルダーをどこで知ったか。
#[derive(Clone, Debug, PartialEq)]
pub enum Place {
    /// DATARELAY_PROGRAM（試験・作る途中）
    Env,
    /// exe を手元に置いた形。exe の隣の DataRelay.program.txt が共有のアプリのフォルダーを指す
    Local { pointer: PathBuf },
    /// exe がアプリのフォルダーの中（配る zip を展開した形・作る途中の desktop/target/…）
    Beside,
}

impl Place {
    pub fn label(&self) -> &'static str {
        match self {
            Place::Env => "env",
            Place::Local { .. } => "local",
            Place::Beside => "beside",
        }
    }
}

/// アプリのフォルダー（app.py・sidecar.py・lib がある所）と、どこで知ったか。探す順:
///   1. DATARELAY_PROGRAM
///   2. exe の隣の DataRelay.program.txt（exe を手元に置いた形。中身は共有から読む）
///   3. exe の場所から上へたどって app.py と sidecar.py が並ぶ所（配る形: exe を app.py の隣に置く。作る途中: desktop/target/release/ から3つ上）
pub fn program_dir() -> Result<(PathBuf, Place), String> {
    if let Some(p) = env::var_os("DATARELAY_PROGRAM") {
        let p = PathBuf::from(p);
        return if is_program(&p) { Ok((p, Place::Env)) } else { Err(format!("DATARELAY_PROGRAM に app.py と sidecar.py がありません: {}", p.display())) };
    }
    let exe = env::current_exe().map_err(|e| e.to_string())?;
    let pointer = exe.with_file_name(POINTER_FILE);
    if let Some(p) = read_pointer(&pointer)? {
        return if is_program(&p) {
            Ok((p, Place::Local { pointer }))
        } else {
            Err(format!(
                "共有のアプリのフォルダーに届きません（または app.py がありません）: {}\n\
                 BOX Drive が動いているか・ネットワークにつながっているかを確かめてください。\n\
                 場所を変えたときは、アプリのフォルダーの install_local.cmd をもう一度実行するか、次のファイルを書き直してください: {}",
                p.display(),
                pointer.display()
            ))
        };
    }
    find_program_from(&exe).map(|p| (p, Place::Beside)).ok_or_else(|| {
        format!(
            "アプリのフォルダ（app.py と sidecar.py がある所）が見つかりません。この exe を app.py と同じフォルダに置くか、\n\
             アプリのフォルダの install_local.cmd で手元に置き直してください。\n探し始めた場所: {}",
            exe.parent().unwrap_or(&exe).display()
        )
    })
}

/// DataRelay.program.txt を読む。無ければ None。あるのに読めない・何も書いていないときは理由を返す。
pub fn read_pointer(file: &Path) -> Result<Option<PathBuf>, String> {
    let Ok(bytes) = std::fs::read(file) else { return Ok(None) };
    let bytes = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes);
    let text = std::str::from_utf8(bytes).map_err(|_| format!("{} が UTF-8 で書かれていません。install_local.cmd をもう一度実行してください。", file.display()))?;
    text.lines()
        .map(|l| l.trim().trim_matches('"').trim())
        .find(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| Some(PathBuf::from(l)))
        .ok_or_else(|| format!("{} にアプリのフォルダーが書かれていません。install_local.cmd をもう一度実行してください。", file.display()))
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

/// 起こし方の候補（先にあるほど優先）。この中から Flask を読める最初のものを使う（`python`）。
///   1. DATARELAY_PYTHON
///   2. start.vbs と同じ順: py -3 → python
///   3. 標準の入れ場所（新しい版から）
/// pythonw は使わない（標準入出力が無い前提で動くため。窓は CREATE_NO_WINDOW で出さない）。
pub fn python_candidates() -> Vec<Python> {
    let mut out = Vec::new();
    if let Some(p) = env::var_os("DATARELAY_PYTHON") {
        out.push(plain(PathBuf::from(p)));
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

/// 起動に欠かせない部品。start.vbs と同じく Flask だけ（ほかは使う場面で知らせる）。
pub const REQUIRED_MODULE: &str = "flask";

/// 使える Python が無かったわけ。窓はこれを最初の画面にそのまま出す。
#[derive(Debug)]
pub struct NoPython {
    /// 起こせる Python はあったが、どれにも Flask が入っていない
    pub lacking: bool,
    /// 部品を入れる先（起こせた最初の Python。start.vbs が pip を走らせる先と同じ）
    pub candidate: Option<Python>,
    pub message: String,
}

impl NoPython {
    pub fn title(&self) -> &'static str {
        if self.lacking { "Python に必要な部品（Flask）が入っていません" } else { "Python が見つかりません" }
    }
}

/// 一つの候補を試した結果。
#[derive(Debug, PartialEq)]
enum Probe {
    /// 起こせて、Flask も読める
    Ready(Python),
    /// 起こせるが、Flask が読めない（本体の場所は分かる）
    Lacks(Python),
}

/// 候補を順に試し、Flask を読める最初の Python の実体（sys.executable）を返す。
/// 起こせるだけで選ぶと、Python が複数ある PC では Flask の無い方を掴みうる（py -3 は最新版を指すため）。
/// py ランチャーを挟んだまま起こすと、窓から止めたときに本体が残りうるので、本体を直接起こす。
pub fn python() -> Result<Python, NoPython> {
    pick(&python_candidates())
}

fn pick(cands: &[Python]) -> Result<Python, NoPython> {
    let mut tried = Vec::new();
    let mut lacking: Option<Python> = None;
    for c in cands {
        let label = format!("  {} {}", c.exe.display(), c.args.join(" "));
        match resolve(c) {
            Ok(Probe::Ready(p)) => return Ok(p),
            Ok(Probe::Lacks(p)) => {
                tried.push(format!("{} … {} が入っていません（{}）", label.trim_end(), REQUIRED_MODULE, p.exe.display()));
                lacking.get_or_insert(p);
            }
            Err(e) => tried.push(format!("{} … {e}", label.trim_end())),
        }
    }
    let tried = tried.join("\n");
    Err(match lacking {
        Some(p) => NoPython {
            lacking: true,
            message: format!(
                "起こせる Python はありますが、どれにも Flask が入っていません。\n\
                 次を実行すると入ります:\n  \"{}\" -m pip install --user -r config\\requirements.txt\n試したもの:\n{tried}",
                p.exe.display()
            ),
            candidate: Some(p),
        },
        None => NoPython {
            lacking: false,
            candidate: None,
            message: format!("Python が見つかりません。Python 3（python.org の版）を入れてください。\n試したもの:\n{tried}"),
        },
    })
}

fn resolve(c: &Python) -> Result<Probe, String> {
    // 1回で両方を聞く: 本体の場所を先に出してから Flask を読む（読めなければ終了コード 3）
    let script = format!("import sys;print(sys.executable,flush=True)\ntry:\n import {REQUIRED_MODULE}\nexcept Exception:\n sys.exit(3)");
    let mut cmd = Command::new(&c.exe);
    cmd.args(&c.args).args(["-c", &script]).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    let ready = match out.status.code() {
        Some(0) => true,
        Some(3) => false,
        code => return Err(format!("終了コード {code:?}")),
    };
    let exe = String::from_utf8_lossy(&out.stdout).lines().next().unwrap_or("").trim().to_string();
    let mut p = PathBuf::from(&exe);
    if exe.is_empty() || !p.is_file() {
        return Err(format!("sys.executable が読めません（{exe}）"));
    }
    // pythonw.exe が返ったら隣の python.exe を使う（標準入出力を使うため）
    if p.file_name().map(|n| n.to_string_lossy().eq_ignore_ascii_case("pythonw.exe")).unwrap_or(false) {
        let sib = p.with_file_name("python.exe");
        if sib.is_file() {
            p = sib;
        }
    }
    // 本体を直接起こす形では前に付ける引数を持ち越さない（-3 などはランチャー向け）
    Ok(if ready { Probe::Ready(plain(p)) } else { Probe::Lacks(plain(p)) })
}

/// アプリの部品の一覧（config\requirements.txt）。
pub fn requirements_file(program: &Path) -> Option<PathBuf> {
    ["config", "Config"].iter().map(|d| program.join(d).join("requirements.txt")).find(|p| p.is_file())
}

/// 部品（config\requirements.txt）を入れる。Flask が無いときに一度だけ走らせる（start.vbs がしていたこと）。
/// 管理者権限が要らないよう --user で入れる。仮想環境の Python は --user を受け付けないので、そのときだけ付けない。
/// pip の出力は log に足していく（入らなかったときの手がかり）。limit を過ぎたら止めて失敗にする。
pub fn install_requirements(py: &Python, requirements: &Path, log: &Path, limit: Duration) -> Result<(), String> {
    let script = "import subprocess,sys\n\
                  a=[sys.executable,'-m','pip','install','--disable-pip-version-check','-r',sys.argv[1]]\n\
                  if sys.prefix==sys.base_prefix:a.insert(4,'--user')\n\
                  sys.exit(subprocess.call(a))";
    if let Some(dir) = log.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let out = std::fs::OpenOptions::new().create(true).append(true).open(log).map_err(|e| format!("記録を開けません: {e}"))?;
    let err = out.try_clone().map_err(|e| e.to_string())?;
    let mut cmd = Command::new(&py.exe);
    cmd.args(&py.args).args(["-c", script]).arg(requirements).stdin(Stdio::null()).stdout(out).stderr(err);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = cmd.spawn().map_err(|e| format!("pip を起こせません: {e}"))?;
    let end = Instant::now() + limit;
    loop {
        match child.try_wait().map_err(|e| e.to_string())? {
            Some(st) if st.success() => return Ok(()),
            Some(st) => return Err(format!("pip が終了コード {:?} で終わりました", st.code())),
            None if Instant::now() >= end => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("{} 秒たっても終わらないため止めました", limit.as_secs()));
            }
            None => std::thread::sleep(Duration::from_millis(200)),
        }
    }
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
    fn reads_the_pointer_to_the_shared_folder() {
        let tmp = env::temp_dir().join(format!("dr-pointer-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let f = tmp.join(POINTER_FILE);
        assert_eq!(read_pointer(&f), Ok(None), "無ければ手元に置いた形ではない");
        // install_local.cmd が書く形（コメント行・CRLF）と、メモ帳で BOM 付きにされた形の両方
        std::fs::write(&f, "# DataRelay.exe（この隣）が読むアプリのフォルダー\r\nC:\\Users\\山田\\Box\\R&D (共有)\\DataRelay\r\n").unwrap();
        assert_eq!(read_pointer(&f), Ok(Some(PathBuf::from("C:\\Users\\山田\\Box\\R&D (共有)\\DataRelay"))));
        std::fs::write(&f, b"\xef\xbb\xbf\"D:\\share\\DataRelay\"\n").unwrap();
        assert_eq!(read_pointer(&f), Ok(Some(PathBuf::from("D:\\share\\DataRelay"))));
        std::fs::write(&f, "# だけ\n\n").unwrap();
        assert!(read_pointer(&f).unwrap_err().contains("書かれていません"));
        std::fs::write(&f, b"\x82\xa0\n").unwrap(); // CP932 の「あ」
        assert!(read_pointer(&f).unwrap_err().contains("UTF-8"));
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn resolves_the_real_interpreter() {
        // この試験を流している Python（PATH の python3/python）の実体が取れる
        let p = python().expect("python");
        assert!(p.exe.is_file(), "{}", p.exe.display());
        assert!(p.args.is_empty(), "本体を直接起こす（ランチャーを挟まない）");
    }

    /// 試験を流している Python（Flask 入り）を、site-packages を見ない形（-S）で起こすと「Flask の無い Python」になる。
    fn this_python() -> Python {
        python().expect("python")
    }

    #[test]
    fn skips_a_python_without_flask() {
        let ok = this_python();
        let without = Python { exe: ok.exe.clone(), args: vec!["-S".into()] };
        assert_eq!(resolve(&without), Ok(Probe::Lacks(ok.clone())), "起こせるが Flask が読めない");
        // 先頭に Flask の無い Python があっても、読める方を選ぶ（CI 機で py -3 が別の Python を指した件）
        assert_eq!(pick(&[without.clone(), ok.clone()]).expect("pick"), ok);
    }

    #[test]
    fn says_what_is_missing_when_no_python_has_flask() {
        let ok = this_python();
        let without = Python { exe: ok.exe.clone(), args: vec!["-S".into()] };
        let missing = Python { exe: PathBuf::from("dr-no-such-python"), args: vec![] };
        let e = pick(&[missing.clone(), without]).expect_err("Flask の無い Python しか無い");
        assert!(e.lacking && e.title().contains("Flask"), "{e:?}");
        assert!(e.message.contains("pip install") && e.message.contains(&ok.exe.display().to_string()), "{}", e.message);
        let e = pick(&[missing]).expect_err("起こせる Python が無い");
        assert!(!e.lacking && e.title() == "Python が見つかりません", "{e:?}");
    }

    #[test]
    fn installs_requirements_and_reports_failure() {
        // ネットを使わずに確かめる: 空の一覧は入れるものが無く成功する／無い場所を指す一覧は失敗し、記録に理由が残る
        let py = this_python();
        let tmp = env::temp_dir().join(format!("dr-pip-{}", std::process::id()));
        std::fs::create_dir_all(tmp.join("config")).unwrap();
        let req = tmp.join("config").join("requirements.txt");
        std::fs::write(&req, "").unwrap();
        assert_eq!(requirements_file(&tmp), Some(req.clone()));
        let log = tmp.join("logs").join("pip_install.log");
        install_requirements(&py, &req, &log, Duration::from_secs(120)).expect("空の一覧");
        std::fs::write(&req, "./dr-no-such-package\n").unwrap();
        let e = install_requirements(&py, &req, &log, Duration::from_secs(120)).expect_err("無い場所");
        assert!(e.contains("終了コード"), "{e}");
        assert!(std::fs::read_to_string(&log).unwrap().contains("dr-no-such-package"), "pip の出力が記録に残る");
        assert_eq!(requirements_file(&tmp.join("none")), None);
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn python_folders_newest_first() {
        assert_eq!(python_dir_version("Python312"), Some(312));
        assert_eq!(python_dir_version("Python313-32"), Some(313));
        assert_eq!(python_dir_version("Python3"), None);
        assert!(python_dir_version("Python313").unwrap() > python_dir_version("Python39").unwrap());
    }
}
