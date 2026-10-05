//! 配る版へそろえる（1.98.0・WaveLog の配布の仕組みを取り入れた）。
//!
//! 置き場（`update_dir()`・既定はアプリのフォルダーそのもの＝共有から直に動かしてきたフォルダー）:
//!   `release.json`        … 配る版（`{"version": "1.98.0", …}`）。決めるのはメンテナンスする人（画面「配布と更新」・lib/navi_release.py）
//!   `versions\<版>\`       … 版ごとの中身と `manifest.json`（全ファイルの道・大きさ・sha256・入れ替える項目 `payload`）
//!   `install.json`        … 新しい PC へ渡す設定（データの基準＝共有のアプリのフォルダー）
//!
//! 窓が起動画面の中で、**中身（Python）を起こす前に**行う（動いている Python のファイルを入れ替えない）。
//! そろえるのは**配布の置き場から写したアプリ**（`config\install.json` がある）だけ。共有から直に動かしている
//! アプリのフォルダーは皆が使っている置き場そのものなので、1台の PC が入れ替えてはいけない。
//!   1. `release.json` を読む（届かなければ `REACH` で打ち切ってそのまま起動・共有が無い日も開ける）
//!   2. 手元の版（`lib\navi_version.py` の `APP_VERSION`）と同じなら何もしない
//!   3. 違えば `<アプリ>\.update\<版>.stage\` へ写して **大きさと sha256 を全部確かめる**
//!   4. `payload` の項目ごとに入れ替える（今の物は `<アプリ>\.update\<前の版>.old\` へ）。途中で失敗したら**戻す**
//!
//! **データは `payload` に入らないので触らない**（設定のマスター・接続ファイル・登録した RNE は共有のアプリの
//! フォルダーにあり、写しは `config\install.json` の `data_root` でそこを指す）。前の版へ戻すのも同じ道
//! （配る版を選び直すだけ）。開発の作業ツリー（`.git` が在る）は入れ替えない。

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;

/// 置き場を変える鍵（Python の navi_release と同じ字）。`config\local.json`（この PC だけ）と `config\update.json`（共有の設定の控え）が持つ。
pub const CONFIG_KEY: &str = "update_dir";
/// この PC だけの上書き（書くのは人）。
pub const LOCAL: &str = "local.json";
/// 共有の設定の控え。窓は Python を起こす前に置き場を知る必要があり、マスター（SQLite）は読まないので、Python が写しておく。
pub const MIRROR: &str = "update.json";
/// 写しの印と、入れた元・データの基準（書くのは窓だけ・`mirror_seed()`）。置き場の同じ名前のファイルは新しい PC へ渡す設定。
pub const SEED: &str = "install.json";
pub const DATA_KEY: &str = "data_root";
pub const FROM_KEY: &str = "from";
pub const RELEASE: &str = "release.json";
pub const VERSIONS: &str = "versions";
pub const MANIFEST: &str = "manifest.json";
/// 共有に届くのを待つ長さ。届かない UNC は OS が数十秒待たせることがある（起動を待たせない）。
pub const REACH: Duration = Duration::from_secs(3);
/// 手元の作業場所（`<アプリ>\.update`）。
pub const WORK: &str = ".update";
/// 最後にそろえた版の目録の控え（次にそろえるとき、前の版にだけあった項目も片付けるため）。
const APPLIED: &str = "applied.json";
/// データと配る物が同居するフォルダー。項目は1段下で数える（Python の `MIXED` と同じ）。
const MIXED: &str = "config";
/// 入れ替えの項目にしてはいけない名前。
const FORBIDDEN: [&str; 3] = [WORK, ".git", "__pycache__"];

/// 何が起きたか（起動画面と記録が言う）。
#[derive(Debug, PartialEq)]
pub enum Outcome {
    /// そろえた。exe も変わったか（変わったら新しい exe で開き直す）
    Applied { from: String, to: String, exe_changed: bool },
    /// そろえられなかった（前の版のまま起動する）
    Failed(String),
}

/// 配る版と手元の版を比べた答え（入れ替える前）。
#[derive(Debug, PartialEq)]
pub enum Peek {
    /// 配る版と同じ
    Same(String),
    /// 確かめなかった理由（写したアプリではない・届かない・配る版が無い・開発の作業ツリー）
    Skip(String),
    /// 配る版の字が正しくない
    Bad(String),
    /// 違う（そろえる）
    Differs { have: String, want: String, dir: PathBuf },
}

/// JSON の辞書を読む（BOM は外す・無い／読めない／辞書でないなら Null）。
pub fn read_json(path: &Path) -> Value {
    std::fs::read(path)
        .ok()
        .and_then(|b| serde_json::from_slice::<Value>(b.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&b)).ok())
        .filter(Value::is_object)
        .unwrap_or(Value::Null)
}

/// JSON ファイルの `key`（前後の空白を除き `%VAR%` を展開・無ければ空文字）。
fn config_value(path: &Path, key: &str) -> String {
    read_json(path)[key].as_str().map(|s| expand_vars(s.trim())).unwrap_or_default()
}

/// `%NAME%` を環境変数で展開する（無ければそのまま残す・Python の navi_paths.expand と同じ扱い）。
pub fn expand_vars(s: &str) -> String {
    let mut out = String::new();
    let mut rest = s;
    while let Some(i) = rest.find('%') {
        out.push_str(&rest[..i]);
        let tail = &rest[i + 1..];
        match tail.find('%') {
            Some(j) => {
                let name = &tail[..j];
                match std::env::var(name) {
                    Ok(v) if !name.is_empty() => out.push_str(&v),
                    _ => out.push_str(&rest[i..i + j + 2]),
                }
                rest = &tail[j + 1..];
            }
            None => {
                out.push_str(&rest[i..]);
                rest = "";
            }
        }
    }
    out.push_str(rest);
    out
}

/// 配布の置き場から写したアプリか（窓が `config\install.json` を書く）。
pub fn installed(app_root: &Path) -> bool {
    app_root.join("config").join(SEED).is_file()
}

/// 置き場と出どころ。`config\local.json`（この PC だけの上書き）→ `config\update.json`（共有の設定の控え）→
/// `config\install.json` の `from`（この PC を入れた元）→ アプリのフォルダー。順は Python の `navi_release.dir_choice()` と同じ。
/// どれも `release_root()` を通す（版のフォルダーから直に動かしても、`versions` の中に `versions` を作らない・1.99.1）。
pub fn update_dir(app_root: &Path) -> (PathBuf, &'static str) {
    let conf = app_root.join("config");
    for (file, key, source) in [(LOCAL, CONFIG_KEY, "local"), (MIRROR, CONFIG_KEY, "shared"), (SEED, FROM_KEY, "install")] {
        let v = config_value(&conf.join(file), key);
        if !v.is_empty() {
            return (release_root(&PathBuf::from(v)), source);
        }
    }
    (release_root(app_root), "app")
}

/// 置き場として渡された場所を、`versions` が直下に並ぶ置き場の根へ直す（Python の `navi_release.release_root()` と同じ）。
/// `…\versions` → その親、`…\versions\<版>` → 2つ上。それ以外はそのまま。
pub fn release_root(p: &Path) -> PathBuf {
    let named = |q: &Path, s: &str| q.file_name().and_then(|n| n.to_str()).is_some_and(|n| n.eq_ignore_ascii_case(s));
    if named(p, VERSIONS) {
        if let Some(up) = p.parent() {
            return up.to_path_buf();
        }
    }
    if let (Some(name), Some(up)) = (p.file_name().and_then(|n| n.to_str()), p.parent()) {
        if safe_version(name) && named(up, VERSIONS) {
            if let Some(root) = up.parent() {
                return root.to_path_buf();
            }
        }
    }
    p.to_path_buf()
}

/// 手元の版（`lib\navi_version.py` の `APP_VERSION`）。読めなければ空文字（まだ写していない）。
pub fn local_version(app_root: &Path) -> String {
    crate::update::program_version(app_root).unwrap_or_default()
}

/// 版の字として使えるか（数字で始まり、英数字・点・ハイフンだけ・Python と同じ）。道に混ぜる前に確かめる。
pub fn safe_version(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 41
        && v.starts_with(|c: char| c.is_ascii_digit())
        && v.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
}

/// `f` を別の糸で動かし、`wait` で打ち切る（届かない共有で起動を止めない）。
fn within<T: Send + 'static>(wait: Duration, f: impl FnOnce() -> T + Send + 'static) -> Option<T> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(f());
    });
    rx.recv_timeout(wait).ok()
}

/// 配る版を読む。`Ok(None)`＝決めていない、`Err`＝届かない・読めない。
/// 「無い」は**置き場のフォルダーが在るときだけ**「決めていない」と読む（届かない UNC も「無い」と答えるので）。
pub fn release_version(dir: &Path, wait: Duration) -> Result<Option<String>, String> {
    let file = dir.join(RELEASE);
    let shown = file.display().to_string();
    let (folder, folder_shown) = (dir.to_path_buf(), dir.display().to_string());
    match within(wait, move || std::fs::read(&file).map_err(|e| (e.kind() == std::io::ErrorKind::NotFound && !folder.is_dir(), e))) {
        None => Err(format!("{} 秒待っても置き場に届きません（{shown}）", wait.as_secs())),
        Some(Err((true, e))) => Err(format!("置き場が見つかりません（{folder_shown}）: {e}")),
        Some(Err((_, e))) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Some(Err((_, e))) => Err(format!("配る版を読めません（{shown}）: {e}")),
        Some(Ok(b)) => {
            let v: Value = serde_json::from_slice(b.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&b))
                .map_err(|e| format!("配る版の形が違います（{shown}）: {e}"))?;
            Ok(v["version"].as_str().map(str::to_owned).filter(|s| !s.is_empty()))
        }
    }
}

/// 置き場の「新しい PC へ渡す設定」を、写しの `config\install.json`（`data_root`・`from`）へ写す。**書き手は窓だけ**。
/// データの基準は置き場の `install.json` の値、無ければ置き場そのもの（既定の置き場＝共有のアプリのフォルダー）。
/// 届かない・置き場の設定が読めないときは前の写しのまま（触らない）。変わったときだけ書く。→ 書いたか。
pub fn mirror_seed(app_root: &Path, dir: &Path) -> Result<bool, String> {
    let src = dir.join(SEED);
    let seed = match std::fs::read(&src) {
        Ok(_) => read_json(&src),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound && dir.is_dir() => Value::Null,
        Err(e) => return Err(format!("置き場の渡す設定を読めません（{}）: {e}", src.display())),
    };
    let data_root =
        seed[DATA_KEY].as_str().map(str::trim).filter(|s| !s.is_empty()).map(str::to_owned).unwrap_or_else(|| dir.display().to_string());
    let text =
        serde_json::to_string_pretty(&serde_json::json!({ DATA_KEY: data_root, FROM_KEY: dir.display().to_string() })).unwrap_or_default();
    let conf = app_root.join("config");
    let dst = conf.join(SEED);
    if std::fs::read_to_string(&dst).ok().as_deref() == Some(text.as_str()) {
        return Ok(false);
    }
    std::fs::create_dir_all(&conf).map_err(|e| format!("{} を作れません: {e}", conf.display()))?;
    let tmp = dst.with_extension("json.tmp");
    std::fs::write(&tmp, &text).and_then(|_| std::fs::rename(&tmp, &dst)).map_err(|e| format!("{} を書けません: {e}", dst.display()))?;
    Ok(true)
}

pub fn sha256_of(p: &Path) -> std::io::Result<String> {
    let mut f = std::fs::File::open(p)?;
    let mut h = Sha256::new();
    std::io::copy(&mut f, &mut h)?;
    Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
}

/// `/` 区切りの道を部品へ（空・`..`・ドライブの `:` を含むなら None）。
fn parts(rel: &str) -> Option<Vec<&str>> {
    let p: Vec<&str> = rel.split('/').collect();
    (!rel.is_empty() && p.iter().all(|x| !x.is_empty() && *x != ".." && *x != "." && !x.contains(':') && !x.contains('\\'))).then_some(p)
}

/// 入れ替えの項目として正しいか: 1段（最上位の名前）か、`config/<名前>` の2段。`config` そのもの・作業場所は不可。
fn valid_item(item: &str) -> bool {
    let Some(p) = parts(item) else { return false };
    let first_mixed = p[0].eq_ignore_ascii_case(MIXED);
    let forbidden = p.iter().any(|x| FORBIDDEN.iter().any(|f| x.eq_ignore_ascii_case(f)));
    !forbidden
        && match p.len() {
            1 => !first_mixed,
            2 => first_mixed,
            _ => false,
        }
}

/// 道 `rel` が項目 `item` の中か（部品の頭がそろう）。
fn under(rel: &[&str], item: &str) -> bool {
    let it: Vec<&str> = item.split('/').collect();
    rel.len() >= it.len() && rel.iter().zip(&it).all(|(a, b)| a == b)
}

fn join(root: &Path, rel: &str) -> PathBuf {
    rel.split('/').fold(root.to_path_buf(), |a, p| a.join(p))
}

/// 目録の入れ替える項目（`payload`）。正しくなければ理由。
fn payload_of(man: &Value) -> Result<Vec<String>, String> {
    let payload: Vec<String> = man["payload"].as_array().into_iter().flatten().filter_map(|v| v.as_str().map(str::to_owned)).collect();
    if payload.is_empty() || !payload.iter().all(|p| valid_item(p)) {
        return Err(format!("入れ替える項目が正しくありません: {payload:?}"));
    }
    Ok(payload)
}

/// 版のフォルダーを `stage` へ写し、manifest どおりか（大きさ・sha256）を全部確かめる。戻り値は入れ替える項目。
pub fn stage(src: &Path, stage: &Path, progress: &dyn Fn(&str)) -> Result<Vec<String>, String> {
    let man: Value =
        serde_json::from_slice(&std::fs::read(src.join(MANIFEST)).map_err(|e| format!("版の目録（manifest.json）を読めません: {e}"))?)
            .map_err(|e| format!("版の目録の形が違います: {e}"))?;
    let payload = payload_of(&man)?;
    let files = man["files"].as_array().ok_or("版の目録にファイルの並びがありません")?;
    let _ = std::fs::remove_dir_all(stage);
    let total = files.len();
    for (i, f) in files.iter().enumerate() {
        let rel = f["path"].as_str().unwrap_or("");
        match parts(rel) {
            Some(p) if payload.iter().any(|it| under(&p, it)) => {}
            _ => return Err(format!("目録に正しくない道があります: {rel}")),
        }
        let (from, to) = (join(src, rel), join(stage, rel));
        if let Some(d) = to.parent() {
            std::fs::create_dir_all(d).map_err(|e| format!("写す先を作れません（{}）: {e}", d.display()))?;
        }
        std::fs::copy(&from, &to).map_err(|e| format!("写せません（{rel}）: {e}"))?;
        let size = std::fs::metadata(&to).map(|m| m.len()).unwrap_or(u64::MAX);
        let sum = sha256_of(&to).map_err(|e| format!("確かめられません（{rel}）: {e}"))?;
        if Some(size) != f["size"].as_u64() || Some(sum.as_str()) != f["sha256"].as_str() {
            return Err(format!("写した物が目録と合いません（{rel}）。置き場の版が壊れているか、写す途中で切れました"));
        }
        if i % 25 == 0 || i + 1 == total {
            progress(&format!("写して確かめています {}/{total}", i + 1));
        }
    }
    Ok(payload)
}

/// 「使用中」で断られた名前の付け替えを待つ長さ（合計）。Windows は Python が終わった直後にもフォルダーを掴んだままの
/// ことがある（ウイルス対策の検査・終わる途中のプロセス）。断りが続くなら本当に使われているので、待つのはこの長さまで。
const BUSY_WAIT: Duration = Duration::from_millis(3000);
const BUSY_STEP: Duration = Duration::from_millis(150);

/// 名前の付け替え。「使用中」（32・33）と「拒否」（5）だけは `BUSY_WAIT` まで待ってやり直す。待った回数を返す。
fn rename_patiently(from: &Path, to: &Path) -> std::io::Result<u32> {
    if let Some(d) = to.parent() {
        std::fs::create_dir_all(d)?;
    }
    let mut tries = 0u32;
    loop {
        match std::fs::rename(from, to) {
            Ok(()) => return Ok(tries),
            Err(e) if matches!(e.raw_os_error(), Some(5 | 32 | 33)) && BUSY_STEP * (tries + 1) <= BUSY_WAIT => {
                tries += 1;
                std::thread::sleep(BUSY_STEP);
            }
            Err(e) => return Err(e),
        }
    }
}

/// `payload` の項目を `stage` の物へ入れ替え、`retire`（前の版にだけあった項目）は片付ける。今の物は `old` へ。
/// **途中で失敗したら全部戻す**。返すのは「使用中」で待った回数（記録に残し、待ちが効いているかを後から読めるように）。
pub fn swap(app_root: &Path, stage: &Path, old: &Path, payload: &[String], retire: &[String]) -> Result<u32, String> {
    let _ = std::fs::remove_dir_all(old);
    std::fs::create_dir_all(old).map_err(|e| format!("前の版の控えを作れません: {e}"))?;
    let mut done: Vec<(&String, bool)> = Vec::new(); // (項目, 前の物が在ったか)
    let mut waited = 0u32;
    let result = (|| {
        for name in payload.iter().chain(retire) {
            let (cur, new, keep) = (join(app_root, name), join(stage, name), join(old, name));
            let had = cur.exists();
            if had {
                waited += rename_patiently(&cur, &keep)
                    .map_err(|e| format!("入れ替えられません（{name} が使用中・{}秒待ちました）: {e}", BUSY_WAIT.as_secs()))?;
            }
            done.push((name, had));
            if new.exists() {
                waited += rename_patiently(&new, &cur).map_err(|e| format!("新しい {name} を置けません: {e}"))?;
            }
        }
        Ok(())
    })();
    if let Err(e) = result {
        for (name, had) in done.iter().rev() {
            let (cur, new, keep) = (join(app_root, name), join(stage, name), join(old, name));
            if cur.exists() && !new.exists() {
                let _ = rename_patiently(&cur, &new);
            }
            if *had {
                let _ = rename_patiently(&keep, &cur);
            }
        }
        return Err(e);
    }
    Ok(waited)
}

/// exe が変わったかは**中身**で見る（大きさ＋更新時刻だと、同じ大きさの exe が同じ秒に置かれたときに見落とす）。
fn exe_stamp(app_root: &Path) -> Option<String> {
    sha256_of(&app_root.join(crate::install::ENTRY)).ok()
}

/// 配る版を読んで手元と比べる（入れ替えない）。届かなければ `REACH` で打ち切る。
/// 置き場に届いたら、写しの `config\install.json`（データの基準・入れた元）も新しくする。
pub fn peek(app_root: &Path) -> Peek {
    if app_root.join(".git").exists() && std::env::var_os("DATARELAY_UPDATE_FORCE").is_none() {
        return Peek::Skip("開発の作業ツリーなので更新しません".into());
    }
    if !installed(app_root) {
        return Peek::Skip("共有から直に動かしています（そろえるのは配布の置き場から写したアプリだけ）".into());
    }
    let (dir, _) = update_dir(app_root);
    let want = match release_version(&dir, REACH) {
        Ok(Some(v)) => v,
        Ok(None) => return Peek::Skip(format!("配る版が決まっていません（{}）", dir.display())),
        Err(e) => return Peek::Skip(e),
    };
    let _ = mirror_seed(app_root, &dir);
    if !safe_version(&want) {
        return Peek::Bad(format!("配る版の字が正しくありません: {want:?}"));
    }
    let have = local_version(app_root);
    if have == want {
        Peek::Same(have)
    } else {
        Peek::Differs { have, want, dir }
    }
}

/// 配る版へそろえる（`peek()` が Differs と答えたとき・**Python が動いていないときに**呼ぶ）。
pub fn apply(app_root: &Path, dir: &Path, have: &str, want: &str, log: &dyn Fn(&str), progress: &dyn Fn(&str)) -> Outcome {
    progress(&format!("{} → {want} にそろえています", if have.is_empty() { "（まだ無い）" } else { have }));
    let work = app_root.join(WORK);
    let stage_dir = work.join(format!("{want}.stage"));
    let old = work.join(format!("{}.old", if safe_version(have) { have } else { "unknown" }));
    let before = exe_stamp(app_root);
    let payload = match stage(&dir.join(VERSIONS).join(want), &stage_dir, progress) {
        Ok(p) => p,
        Err(e) => {
            let _ = std::fs::remove_dir_all(&stage_dir);
            return Outcome::Failed(e);
        }
    };
    // 前の版にだけあった項目（その版の目録の控え）も片付ける。控えが無い（初めて写した）なら何もしない
    let retire: Vec<String> =
        payload_of(&read_json(&work.join(APPLIED))).unwrap_or_default().into_iter().filter(|p| !payload.contains(p)).collect();
    progress("入れ替えています");
    match swap(app_root, &stage_dir, &old, &payload, &retire) {
        Ok(0) => {}
        Ok(n) => log(&format!("UPDATE 使用中で {n} 回待ってから入れ替えました（{}ms ごと）", BUSY_STEP.as_millis())),
        Err(e) => {
            let _ = std::fs::remove_dir_all(&stage_dir);
            return Outcome::Failed(e);
        }
    }
    let _ = std::fs::remove_dir_all(&stage_dir);
    let _ = std::fs::write(work.join(APPLIED), serde_json::json!({"version": want, "payload": payload}).to_string());
    // 前の版の控えは1つだけ残す（直前の版。それより古い控えは消す）
    for e in std::fs::read_dir(&work).into_iter().flatten().flatten() {
        if e.path() != old && e.file_name().to_string_lossy().ends_with(".old") {
            let _ = std::fs::remove_dir_all(e.path());
        }
    }
    log(&format!("UPDATE {have} → {want}（{}）retired={retire:?}", dir.display()));
    Outcome::Applied { from: have.to_string(), to: want.to_string(), exe_changed: exe_stamp(app_root) != before }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use std::fs;

    pub(crate) fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("dr-release-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    /// 版のフォルダーと目録を作る（Python の `navi_release._manifest` と同じ形）。`extra` は足すファイル。
    pub(crate) fn version(share: &Path, v: &str, body: &str, extra: &[(&str, &str)]) {
        let root = share.join(VERSIONS).join(v);
        let mut files: Vec<(String, String)> = vec![
            ("lib/navi_version.py".into(), format!("APP_VERSION='{v}'; APP_VERSION_TITLE='x'\n")),
            ("app.py".into(), body.to_string()),
            ("sidecar.py".into(), "#\n".into()),
            ("DataRelay.exe".into(), format!("exe {v}")),
            ("config/rne/A.RNE".into(), format!("rne {v}")),
        ];
        files.extend(extra.iter().map(|(a, b)| (a.to_string(), b.to_string())));
        let mut list = vec![];
        let mut payload = std::collections::BTreeSet::new();
        for (p, text) in &files {
            let f = join(&root, p);
            fs::create_dir_all(f.parent().unwrap()).unwrap();
            fs::write(&f, text).unwrap();
            list.push(serde_json::json!({"path": p, "size": text.len(), "sha256": sha256_of(&f).unwrap()}));
            let ps: Vec<&str> = p.split('/').collect();
            payload.insert(if ps[0] == "config" { ps[..2].join("/") } else { ps[0].to_string() });
        }
        let man = serde_json::json!({"version": v, "payload": payload, "files": list});
        fs::write(root.join(MANIFEST), man.to_string()).unwrap();
    }

    /// 写したアプリ（`config\install.json` で置き場を指す）を作る。
    fn app(root: &Path, v: &str, share: &Path) {
        fs::create_dir_all(root.join("lib")).unwrap();
        fs::create_dir_all(root.join("config").join("rne")).unwrap();
        fs::write(root.join("lib/navi_version.py"), format!("APP_VERSION='{v}'\n")).unwrap();
        fs::write(root.join("lib/old_only.py"), "old").unwrap();
        fs::write(root.join("app.py"), "old app").unwrap();
        fs::write(root.join("DataRelay.exe"), format!("exe {v}")).unwrap();
        fs::write(root.join("config/local.json"), "{}").unwrap();
        fs::write(root.join("config/rne/A.RNE"), "old rne").unwrap();
        let seed = serde_json::json!({DATA_KEY: share, FROM_KEY: share});
        fs::write(root.join("config").join(SEED), seed.to_string()).unwrap();
    }

    fn release(share: &Path, v: &str) {
        fs::write(share.join(RELEASE), format!(r#"{{"version":"{v}"}}"#)).unwrap();
    }

    fn check_and_apply(root: &Path) -> Result<Outcome, Peek> {
        match peek(root) {
            Peek::Differs { have, want, dir } => Ok(apply(root, &dir, &have, &want, &|_| {}, &|_| {})),
            other => Err(other),
        }
    }

    #[test]
    fn missing_folder_is_not_an_undecided_release() {
        let d = tmp("rv");
        assert_eq!(release_version(&d, REACH), Ok(None), "置き場は在り配る版が無い＝決めていない");
        let e = release_version(&d.join("nowhere"), REACH).unwrap_err();
        assert!(e.contains("置き場が見つかりません"), "置き場ごと無い・届かない UNC は「決めていない」と取り違えない: {e}");
        fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn place_order_matches_python() {
        let t = tmp("place");
        fs::create_dir_all(t.join("config")).unwrap();
        assert_eq!(update_dir(&t), (t.clone(), "app"), "何も無ければアプリのフォルダーそのもの");
        fs::write(t.join("config").join(SEED), r#"{"from":"/origin"}"#).unwrap();
        assert_eq!(update_dir(&t), (PathBuf::from("/origin"), "install"));
        fs::write(t.join("config").join(MIRROR), "\u{feff}{\"update_dir\":\"/shared\"}").unwrap();
        assert_eq!(update_dir(&t), (PathBuf::from("/shared"), "shared"), "共有の設定の控え（BOM 付きでも読む）");
        fs::write(t.join("config").join(LOCAL), r#"{"update_dir":"/mine"}"#).unwrap();
        assert_eq!(update_dir(&t), (PathBuf::from("/mine"), "local"), "この PC の上書きがいちばん先");
        fs::write(t.join("config").join(LOCAL), r#"{"update_dir":"  "}"#).unwrap();
        assert_eq!(update_dir(&t).1, "shared", "空は無いのと同じ");
        assert!(safe_version("1.98.0") && safe_version("1.98.0-st2") && !safe_version("../x") && !safe_version(""));
        // 版のフォルダーから直に動かしても、versions の中に versions を作らない（Python の release_root と同じ答え）
        let v = t.join("versions").join("1.98.0");
        fs::create_dir_all(v.join("config")).unwrap();
        assert_eq!(update_dir(&v), (t.clone(), "app"), "versions\\<版> から動かしたら2つ上が置き場");
        fs::write(v.join("config").join(LOCAL), r#"{"update_dir":"/rel/Versions"}"#).unwrap();
        assert_eq!(update_dir(&v), (PathBuf::from("/rel"), "local"), "versions そのものを指したら親（大文字小文字は問わない）");
        fs::write(v.join("config").join(LOCAL), r#"{"update_dir":"/rel/versions/1.99.0"}"#).unwrap();
        assert_eq!(update_dir(&v).0, PathBuf::from("/rel"), "版のフォルダーを指したら2つ上");
        fs::write(v.join("config").join(LOCAL), r#"{"update_dir":"/rel/old/1.99.0"}"#).unwrap();
        assert_eq!(update_dir(&v).0, PathBuf::from("/rel/old/1.99.0"), "versions の下でなければそのまま");
        std::env::set_var("DR_RELEASE_TEST", "/srv");
        assert_eq!(expand_vars("%DR_RELEASE_TEST%/a %NOPE_X%"), "/srv/a %NOPE_X%");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn items_are_checked() {
        for ok in ["lib", "app.py", "config/rne", "config/README.md", "DataRelay.exe"] {
            assert!(valid_item(ok), "{ok}");
        }
        for bad in ["config", "Config", "a/b", "config/a/b", "..", "", ".update", "lib/__pycache__", "c:x", "a\\b"] {
            assert!(!valid_item(bad), "{bad}");
        }
    }

    #[test]
    fn applies_the_release_keeps_data_and_rolls_back() {
        let t = tmp("apply");
        let (root, share) = (t.join("app"), t.join("share"));
        app(&root, "1.97.0", &share);
        version(&share, "1.98.0", "new app", &[("templates/index.html", "<html>")]);
        release(&share, "1.98.0");
        let out = check_and_apply(&root).unwrap();
        assert_eq!(out, Outcome::Applied { from: "1.97.0".into(), to: "1.98.0".into(), exe_changed: true });
        assert_eq!(local_version(&root), "1.98.0");
        assert_eq!(fs::read_to_string(root.join("app.py")).unwrap(), "new app");
        assert_eq!(fs::read_to_string(root.join("config/rne/A.RNE")).unwrap(), "rne 1.98.0", "config の配る物は入れ替える");
        assert!(root.join("config/local.json").exists(), "同じ config の人が書いた物は残す（項目は1段下）");
        assert!(installed(&root), "写しの印（install.json）は残す");
        assert!(!root.join("lib/old_only.py").exists(), "前の版だけに在った物は残らない（項目ごと入れ替える）");
        assert!(root.join(".update/1.97.0.old/lib/old_only.py").exists(), "前の版は控えに残る");
        assert_eq!(peek(&root), Peek::Same("1.98.0".into()));
        // 次の版で templates が無くなった → 前の版の目録の控えから片付ける
        version(&share, "1.99.0", "newer", &[]);
        release(&share, "1.99.0");
        assert!(matches!(check_and_apply(&root), Ok(Outcome::Applied { .. })));
        assert!(!root.join("templates").exists(), "前の版にだけあった項目も片付ける");
        assert!(!root.join(".update/1.97.0.old").exists(), "控えは直前の版の1つだけ");
        // 前の版へ戻す＝配る版を選び直すだけ
        release(&share, "1.98.0");
        assert!(matches!(check_and_apply(&root), Ok(Outcome::Applied { .. })));
        assert_eq!(fs::read_to_string(root.join("app.py")).unwrap(), "new app");
        assert!(root.join("templates/index.html").exists());
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn a_broken_version_changes_nothing() {
        let t = tmp("broken");
        let (root, share) = (t.join("app"), t.join("share"));
        app(&root, "1.97.0", &share);
        version(&share, "1.98.0", "new", &[]);
        fs::write(share.join("versions/1.98.0/app.py"), "tampered").unwrap();
        release(&share, "1.98.0");
        let out = check_and_apply(&root).unwrap();
        assert!(matches!(&out, Outcome::Failed(e) if e.contains("合いません")), "{out:?}");
        assert_eq!(local_version(&root), "1.97.0", "確かめられなければ1つも入れ替えない");
        assert!(root.join("lib/old_only.py").exists());
        assert!(!root.join(WORK).join("1.98.0.stage").exists(), "途中の物を残さない");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn only_installed_copies_are_aligned() {
        let t = tmp("skip");
        let (root, share) = (t.join("app"), t.join("share"));
        app(&root, "1.97.0", &share);
        fs::remove_file(root.join("config").join(SEED)).unwrap();
        assert!(matches!(peek(&root), Peek::Skip(e) if e.contains("共有から直に")), "共有のアプリのフォルダーは入れ替えない");
        app(&root, "1.97.0", &t.join("nowhere"));
        assert!(matches!(peek(&root), Peek::Skip(_)), "置き場に届かなければそのまま起動");
        fs::create_dir_all(&share).unwrap();
        app(&root, "1.97.0", &share);
        assert!(matches!(peek(&root), Peek::Skip(e) if e.contains("決まっていません")));
        fs::create_dir_all(root.join(".git")).unwrap();
        assert!(matches!(peek(&root), Peek::Skip(e) if e.contains("開発")));
        assert!(within(Duration::from_millis(50), || std::thread::sleep(Duration::from_secs(2))).is_none(), "待ちは打ち切る");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn seed_follows_the_place() {
        let t = tmp("seed");
        let (root, share) = (t.join("app"), t.join("share"));
        fs::create_dir_all(&share).unwrap();
        assert_eq!(mirror_seed(&root, &share), Ok(true));
        let v = read_json(&root.join("config").join(SEED));
        assert_eq!(v[DATA_KEY], share.display().to_string(), "置き場に渡す設定が無ければ、置き場そのものがデータの基準");
        assert_eq!(v[FROM_KEY], share.display().to_string());
        assert_eq!(mirror_seed(&root, &share), Ok(false), "同じなら書かない");
        fs::write(share.join(SEED), r#"{"data_root":"%USERPROFILE%\\Box\\DataRelay"}"#).unwrap();
        assert_eq!(mirror_seed(&root, &share), Ok(true));
        assert_eq!(read_json(&root.join("config").join(SEED))[DATA_KEY], "%USERPROFILE%\\Box\\DataRelay", "書いたまま写す（展開は読む側）");
        assert!(mirror_seed(&root, &t.join("届かない")).is_err(), "届かなければ前の写しのまま");
        assert_eq!(read_json(&root.join("config").join(SEED))[DATA_KEY], "%USERPROFILE%\\Box\\DataRelay");
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn rename_waits_only_for_busy() {
        let t = tmp("busy");
        let t0 = std::time::Instant::now();
        assert!(rename_patiently(&t.join("none"), &t.join("x")).is_err());
        assert!(t0.elapsed() < BUSY_STEP, "使用中でない失敗で待っている");
        fs::create_dir_all(t.join("a")).unwrap();
        assert_eq!(rename_patiently(&t.join("a"), &t.join("deep/b")).unwrap(), 0, "置く先の親は作る");
        assert!(t.join("deep/b").exists());
        fs::remove_dir_all(&t).ok();
    }

    #[test]
    fn swap_rolls_back_when_a_step_fails() {
        let t = tmp("swap");
        let (root, st, old) = (t.join("app"), t.join("stage"), t.join("old"));
        fs::create_dir_all(root.join("lib")).unwrap();
        fs::write(root.join("lib/navi_version.py"), "APP_VERSION='1.97.0'\n").unwrap();
        fs::write(root.join("lib/old_only.py"), "old").unwrap();
        fs::write(root.join("config"), "フォルダーではなくファイル").unwrap();
        fs::create_dir_all(st.join("lib")).unwrap();
        fs::write(st.join("lib/navi_version.py"), "APP_VERSION='9'\n").unwrap();
        fs::create_dir_all(st.join("config/rne")).unwrap();
        let payload = vec!["lib".to_string(), "config/rne".to_string()];
        assert!(swap(&root, &st, &old, &payload, &[]).is_err(), "2つ目は置く先の親（config）を作れず失敗する");
        assert_eq!(local_version(&root), "1.97.0", "1つ目に入れ替えた物も元へ戻す");
        assert!(root.join("lib/old_only.py").exists());
        assert!(st.join("lib/navi_version.py").exists(), "新しい物は写した先へ戻る（半端に混ざらない）");
        fs::remove_dir_all(&t).ok();
    }
}
