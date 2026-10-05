//! 初回のインストールと入口（1.98.0・WaveLog の「アドレスだけ渡す」配り方を取り入れた）。
//!
//! 配る版を決めると、置き場の直下に**配る入口**（`<置き場>\DataRelay.exe`）が置かれる（lib/navi_release.py の
//! `place_entry()`）。既定の置き場はアプリのフォルダーそのものなので、皆が使ってきた共有の DataRelay.exe がそのまま入口になる。
//! 新しい PC にはこの exe のアドレスだけを渡す。起こされたら:
//!   1. 入口（共有）: この PC の写し（`install_root()`＝`%USERPROFILE%\DataRelay`）の DataRelay.exe を起こし、
//!      `--install-from <置き場>` を付けて渡して終わる（共有の exe を掴み続けない）。写しがまだ無ければ、配る版の
//!      exe だけを先に写してから渡す（`handoff()`）
//!   2. 写しの窓: 置き場の渡す設定を `config\install.json` へ写し（データの基準・入れた元）、配る版を写す
//!      ——写し方と確かめ方（sha256）は更新（`release::apply()`）と同じ道。中身がまだ無い版から配る版へそろえるだけ
//!   3. そのまま起動する。デスクトップの起動アイコンは、画面が「作りますか」と聞く（lib/navi_shortcut.py）
//!
//! 共有から直に動かしてきた形（exe が共有のアプリのフォルダーにある・install_local.cmd で exe だけ手元に置いた形）も、
//! 置き場に配る版があれば同じく写しへ渡す（配り始めた日から、ダブルクリックした PC は自分の写しへ移る）。
//!
//! **写す先を AppData の外にする理由**: Microsoft Store 版の Python は `AppData` への書込をその Python だけに見える写しへ
//! 回す。写しの `config\update.json` は Python が書いて窓が読むので、`AppData` の下に置くと窓から見えない（WaveLog で実測）。

use crate::{locate, release};
use std::fs::File;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

/// 配る入口・写しの exe の名前（lib/navi_release.py の `ENTRY_EXE` と同じ字）。
pub const ENTRY: &str = "DataRelay.exe";
/// 写しへ渡すときの引数（どの置き場から入れるか）。
pub const ARG: &str = "--install-from";
/// 前の窓が終わるのを待たせる引数（更新で exe が変わった・画面から開き直すとき）。
pub const AFTER_ARG: &str = "--after-pid";
/// 写す先を覚えておくファイル（この PC の作業場所・窓だけが書く）。
const REMEMBERED: &str = "install_root.txt";

/// 引数 `name <値>` の値。
fn arg_value(name: &str) -> Option<String> {
    let args: Vec<String> = std::env::args().collect();
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
}

/// 引数 `--install-from <置き場>` の値。
pub fn from_arg() -> Option<PathBuf> {
    arg_value(ARG).map(PathBuf::from)
}

/// `dir` が配る版のある置き場か（`release.json` と `versions` が並ぶ）。
pub fn is_release_dir(dir: &Path) -> bool {
    dir.join(release::RELEASE).is_file() && dir.join(release::VERSIONS).is_dir()
}

/// いま動いている exe が**配る入口**なら、その置き場。入口の印は「名前が DataRelay.exe で、同じフォルダーに配る版がある」こと。
/// 写したアプリの exe（`config\install.json` がある）は入口ではない。
pub fn shared_entry_dir(me: &Path) -> Option<PathBuf> {
    let name = me.file_name()?.to_str()?;
    if !name.eq_ignore_ascii_case(ENTRY) {
        return None;
    }
    let dir = me.parent()?;
    (is_release_dir(dir) && !release::installed(dir)).then(|| dir.to_path_buf())
}

/// 写す先として使えるか: 無い・空・すでに DataRelay の写し。
fn usable(dir: &Path) -> bool {
    !dir.exists() || release::installed(dir) || std::fs::read_dir(dir).map(|mut d| d.next().is_none()).unwrap_or(false)
}

/// 写す先（この PC の決まった場所）。`DATARELAY_INSTALL_ROOT`（試験・作る途中）→ 前に写した場所 →
/// `%USERPROFILE%\DataRelay`（ほかの物が入っていれば `DataRelay-2` … の空いている名前）。
pub fn install_root() -> PathBuf {
    if let Some(p) = std::env::var_os("DATARELAY_INSTALL_ROOT") {
        return PathBuf::from(p);
    }
    if let Some(p) = std::fs::read_to_string(locate::local_root().join(REMEMBERED)).ok().map(|s| PathBuf::from(s.trim())) {
        if release::installed(&p) {
            return p;
        }
    }
    let home =
        std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."));
    free_dir(&home, "DataRelay")
}

/// `parent` の下で写す先に使える名前（`name` → `name-2` …）。
pub fn free_dir(parent: &Path, name: &str) -> PathBuf {
    (1..100)
        .map(|n| parent.join(if n == 1 { name.to_string() } else { format!("{name}-{n}") }))
        .find(|d| usable(d))
        .unwrap_or_else(|| parent.join(name))
}

/// 写した場所を覚える（次に入口から起こされたとき、同じ写しへ渡すため）。
pub fn remember(root: &Path) {
    let file = locate::local_root().join(REMEMBERED);
    let text = root.display().to_string();
    if std::fs::read_to_string(&file).ok().as_deref() != Some(text.as_str()) {
        let _ = std::fs::create_dir_all(locate::local_root());
        let _ = std::fs::write(file, text);
    }
}

/// 「インターネットから来た」印（NTFS の別の流れ `Zone.Identifier`）を外す。外したら true。
/// **自分で写した物にだけ使う**（出どころは配った置き場）。Windows 以外には印が無い。
pub fn strip_mark(p: &Path) -> bool {
    if !cfg!(windows) {
        return false;
    }
    let mut s = p.as_os_str().to_owned();
    s.push(":Zone.Identifier");
    std::fs::remove_file(PathBuf::from(s)).is_ok()
}

/// `src` を `dst` へ置く（途中のファイルへ写し → 印を外す → 名前を変えて入れ替える）。途中で落ちても半端な exe を残さない。
pub fn place_exe(src: &Path, dst: &Path) -> Result<bool, String> {
    if let Some(d) = dst.parent() {
        std::fs::create_dir_all(d).map_err(|e| format!("置き場を作れません（{}）: {e}", d.display()))?;
    }
    let tmp = dst.with_extension("exe.tmp");
    std::fs::copy(src, &tmp).map_err(|e| format!("写せません（{} → {}）: {e}", src.display(), tmp.display()))?;
    let stripped = strip_mark(&tmp);
    std::fs::rename(&tmp, dst).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("置き換えられません（{}）: {e}", dst.display())
    })?;
    Ok(stripped)
}

/// 入口から起こされたときの行き先。
#[derive(Debug, PartialEq)]
pub enum Handoff {
    /// この PC の写しへ渡した（呼ぶ側はすぐ終わる）
    Done(PathBuf),
    /// 渡せない。理由（呼ぶ側はこのまま動く）
    Failed(String),
}

/// 置き場 `dir` からこの PC の写しへ渡す。写しの exe が無ければ、配る版の exe（無ければ自分）を先に写す。
/// 写しの exe には `--install-from <置き場>` を付ける（写しの窓が渡す設定と配る版を写す）。
pub fn handoff(dir: &Path, log: &dyn Fn(&str)) -> Handoff {
    let root = install_root();
    let exe = root.join(ENTRY);
    if !exe.is_file() {
        let want = release::release_version(dir, release::REACH).ok().flatten().filter(|v| release::safe_version(v));
        let from_release = want.map(|v| dir.join(release::VERSIONS).join(v).join(ENTRY)).filter(|p| p.is_file());
        let Some(src) = from_release.or_else(|| locate::exe().ok()) else {
            return Handoff::Failed("写す exe が見つかりません".into());
        };
        match place_exe(&src, &exe) {
            Ok(stripped) => log(&format!("INSTALL exe を写しました: {} → {}（印を外した: {stripped}）", src.display(), exe.display())),
            Err(e) => return Handoff::Failed(e),
        }
    }
    match std::process::Command::new(&exe).arg(ARG).arg(dir).current_dir(&root).spawn() {
        Ok(_) => {
            remember(&root);
            log(&format!("INSTALL 置き場から写しへ渡しました: {} → {}", dir.display(), exe.display()));
            Handoff::Done(exe)
        }
        Err(e) => Handoff::Failed(format!("写しを起こせません（{}）: {e}", exe.display())),
    }
}

// ---- 前の窓が終わるのを待つ（錠） ----
// 更新で exe が変わった・画面から開き直すとき、新しい窓を先に開くと「1つだけ起動」の仕組みが前の窓を前に出して、
// 新しい窓のほうが閉じてしまう。窓はどれも動いている間この PC の作業場所の錠を持ち、`--after-pid` で起こされた窓は
// 錠が空くまで（＝前の窓が終わるまで）待つ。錠は OS がプロセスの終わりに外すので、落ちても残らない。
static WINDOW_LOCK: OnceLock<File> = OnceLock::new();

fn lock_path() -> PathBuf {
    locate::local_root().join("runtime").join("window.lock")
}

fn open_lock() -> Option<File> {
    let p = lock_path();
    let _ = std::fs::create_dir_all(p.parent()?);
    std::fs::OpenOptions::new().create(true).truncate(false).write(true).open(p).ok()
}

/// 錠を取って持ち続ける（取れなければ何もしない——ほかの窓が動いている。1つだけ起動の仕組みが前の窓を前に出す）。
pub fn hold_window_lock() -> bool {
    let Some(f) = open_lock() else { return false };
    if f.try_lock().is_ok() {
        let _ = WINDOW_LOCK.set(f);
        true
    } else {
        false
    }
}

/// 前の窓から開き直された窓か（`--after-pid` が付いている）。
pub fn relaunched() -> bool {
    arg_value(AFTER_ARG).is_some()
}

/// `--after-pid` が付いていれば、前の窓が終わって錠が空くまで待つ（長くても `limit`）。→ 待った長さ。
pub fn wait_for_previous(limit: Duration) -> Option<Duration> {
    arg_value(AFTER_ARG)?;
    let t = Instant::now();
    let f = open_lock()?;
    while t.elapsed() < limit {
        if f.try_lock().is_ok() {
            let _ = f.unlock();
            return Some(t.elapsed());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Some(t.elapsed())
}

/// 起動のときに配る版へそろえたあと、新しい exe で開き直したとき「前の版 → 新しい版」を渡す環境変数（通知とアプリ監視に出す）。
pub const RELEASED_ENV: &str = "DATARELAY_RELEASED";

/// `exe` を `--after-pid <この窓>` 付きで起こす（呼ぶ側はこのあと終わる）。`note` は新しい窓へ渡す「前の版 → 新しい版」。
pub fn relaunch(exe: &Path, note: &str) -> Result<(), String> {
    let mut cmd = std::process::Command::new(exe);
    if note.is_empty() {
        cmd.env_remove(RELEASED_ENV);
    } else {
        cmd.env(RELEASED_ENV, note);
    }
    cmd.arg(AFTER_ARG)
        .arg(std::process::id().to_string())
        .current_dir(exe.parent().unwrap_or(Path::new(".")))
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("{} を起こせません: {e}", exe.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("dr-install-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn knows_the_shared_entry() {
        let t = tmp("entry");
        let share = t.join("share");
        fs::create_dir_all(share.join(release::VERSIONS)).unwrap();
        fs::write(share.join(ENTRY), b"x").unwrap();
        assert_eq!(shared_entry_dir(&share.join(ENTRY)), None, "配る版が決まるまで入口ではない（これまでどおり共有から動く）");
        fs::write(share.join(release::RELEASE), r#"{"version":"1.98.0"}"#).unwrap();
        assert_eq!(shared_entry_dir(&share.join(ENTRY)), Some(share.clone()), "置き場の直下の exe は入口");
        assert_eq!(shared_entry_dir(&share.join("datarelay.EXE")), Some(share.clone()), "大文字小文字は区別しない");
        assert_eq!(shared_entry_dir(&share.join("other.exe")), None, "別の名前は入口ではない");
        fs::create_dir_all(share.join("config")).unwrap();
        fs::write(share.join("config").join(release::SEED), "{}").unwrap();
        assert_eq!(shared_entry_dir(&share.join(ENTRY)), None, "写したアプリの exe は入口ではない");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn install_root_avoids_foreign_folders() {
        let t = tmp("root");
        assert_eq!(free_dir(&t, "DataRelay"), t.join("DataRelay"), "無ければその名前");
        fs::create_dir_all(t.join("DataRelay")).unwrap();
        assert_eq!(free_dir(&t, "DataRelay"), t.join("DataRelay"), "空なら使う");
        fs::write(t.join("DataRelay").join("自分の物.txt"), "x").unwrap();
        assert_eq!(free_dir(&t, "DataRelay"), t.join("DataRelay-2"), "ほかの物が入っていれば避ける");
        fs::create_dir_all(t.join("DataRelay").join("config")).unwrap();
        fs::write(t.join("DataRelay").join("config").join(release::SEED), "{}").unwrap();
        assert_eq!(free_dir(&t, "DataRelay"), t.join("DataRelay"), "DataRelay の写しならそこ");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn place_exe_replaces_without_leaving_a_half_file() {
        let t = tmp("place");
        let src = t.join("a.exe");
        fs::write(&src, b"new").unwrap();
        let dst = t.join("sub").join(ENTRY);
        place_exe(&src, &dst).unwrap();
        fs::write(&src, b"newer").unwrap();
        place_exe(&src, &dst).unwrap();
        assert_eq!(fs::read(&dst).unwrap(), b"newer");
        assert!(!dst.with_extension("exe.tmp").exists(), "途中のファイルを残さない");
        fs::remove_dir_all(&t).ok();
    }

    #[cfg(windows)]
    #[test]
    fn copied_exe_loses_the_internet_mark() {
        let t = tmp("mark");
        let src = t.join("a.exe");
        fs::write(&src, b"x").unwrap();
        let mut ads = src.as_os_str().to_owned();
        ads.push(":Zone.Identifier");
        fs::write(PathBuf::from(&ads), "[ZoneTransfer]\r\nZoneId=3\r\n").unwrap();
        let dst = t.join("b").join(ENTRY);
        assert!(place_exe(&src, &dst).unwrap(), "写した物から印を外した");
        let mut dads = dst.as_os_str().to_owned();
        dads.push(":Zone.Identifier");
        assert!(!PathBuf::from(dads).exists());
        assert!(PathBuf::from(ads).exists(), "元（配った物）の印は触らない");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn a_held_lock_is_seen_by_another_handle() {
        let t = tmp("lock");
        let p = t.join("w.lock");
        let a = fs::OpenOptions::new().create(true).truncate(false).write(true).open(&p).unwrap();
        a.try_lock().unwrap();
        let b = fs::OpenOptions::new().write(true).open(&p).unwrap();
        assert!(b.try_lock().is_err(), "持っている間はほかから取れない（前の窓が動いている）");
        drop(a);
        assert!(b.try_lock().is_ok(), "持ち主が終われば取れる");
        fs::remove_dir_all(&t).ok();
    }
}
