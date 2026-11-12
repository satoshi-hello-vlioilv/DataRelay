//! 公開先を読むための手元の写し（2.28.0〜）。lib/navi_localcopy.py の read_copy と同じ約束（docs/SHARED_READ.md）で写す。
//!
//!   R1 変わったかは（大きさ・更新時刻 ns）で見る。同じ版の写しがあれば共有を開かない（R2）
//!   R3 写す前に書き手の目印（.<名前>.*.incoming・-journal・-wal）を見る。あれば写さない
//!   R4 置き換えを許す開き方（Windows は FILE_SHARE_DELETE まで許す）で、丸ごと1回で写す
//!   R5 写し終えたら大きさ・時刻と目印をもう一度見る。違えば捨てる
//!   R6 SQLite3 は quick_check で確かめる
//!   R7 写しは版ごとの名前。書きかけは .tmp に置き、確かめてから名前を付ける
//!   R8 公開先を直接開かない。写せなければ理由を言って断る
//!   R9 同じ公開先を同時に2本写さない（このプロセスの中。Python とは書きかけの名前を分ける）
//!
//! 写しの名前は Python と同じ（sha1('read|<道の小文字>|<大きさ>|<時刻 ns>') の先頭16字＋拡張子）。
//! 同じ版の写しを、Python と Rust のどちらが作っても使い回せる。
use crate::paths;
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// 読むために写すときの上限（2GB）。
const READ_COPY_BYTES: u64 = 2 * 1024 * 1024 * 1024;
/// 写しの置き場の上限（古いものから捨てる）。
const CACHE_TOTAL_BYTES: u64 = 512 * 1024 * 1024;

/// まだ手元へ写せていない（文はそのまま画面へ出す）。
#[derive(Debug)]
pub struct NotCopiedYet(pub String);

/// 写せなかった理由。Python と同じ文を作れない物（OS の例外の文）は Other（呼ぶ側が Python へ回す）。
#[derive(Debug)]
pub enum CopyError {
    NotCopied(NotCopiedYet),
    Other,
}

// ==== SHA-1（写しの名前を Python の hashlib.sha1 と同じにするため） =========

pub fn sha1_hex(data: &[u8]) -> String {
    let mut h: [u32; 5] = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0];
    let mut msg = data.to_vec();
    let bits = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bits.to_be_bytes());
    for block in msg.chunks(64) {
        let mut w = [0u32; 80];
        for (i, word) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for (i, wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | (!b & d), 0x5A827999),
                20..=39 => (b ^ c ^ d, 0x6ED9EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1BBCDC),
                _ => (b ^ c ^ d, 0xCA62C1D6),
            };
            let t = a.rotate_left(5).wrapping_add(f).wrapping_add(e).wrapping_add(k).wrapping_add(*wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = t;
        }
        for (x, y) in h.iter_mut().zip([a, b, c, d, e]) {
            *x = x.wrapping_add(y);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

// ==== 置き場 ================================================================

/// navi_localcopy.cache_dir（このPCの work\read-cache。無ければ作る）。
pub fn cache_dir() -> String {
    let local = paths::py_path(&paths::local_root().to_string_lossy());
    let d = paths::join(&paths::join(&local, "work"), "read-cache");
    let _ = std::fs::create_dir_all(&d);
    d
}

/// 大きさの言い方（_size）。
pub(crate) fn size_text(n: u64) -> String {
    if n < 1024 {
        format!("{n}バイト")
    } else if n < 1048576 {
        format!("{:.0}KB", n as f64 / 1024.0)
    } else {
        format!("{:.1}MB", n as f64 / 1048576.0)
    }
}

/// (大きさ, 更新時刻 ns)（_signature）。
fn signature(p: &str) -> std::io::Result<(u64, i128)> {
    let m = std::fs::metadata(p)?;
    let t = m.modified()?;
    let ns = match t.duration_since(UNIX_EPOCH) {
        Ok(d) => d.as_nanos() as i128,
        Err(e) => -(e.duration().as_nanos() as i128),
    };
    Ok((m.len(), ns))
}

/// 写しの名前（_read_key）。
fn read_key(src: &str, sig: (u64, i128)) -> String {
    let h = sha1_hex(format!("read|{}|{}|{}", src.to_lowercase(), sig.0, sig.1).as_bytes());
    format!("{}{}", &h[..16], paths::py_suffix(src).to_lowercase())
}

/// 書き手が作業中の印（writer_marks。公開の書きかけ .<名前>.*.incoming と、SQLite の -journal・-wal）。
fn writer_marks(src: &str) -> Vec<String> {
    let low = paths::py_name(src).to_lowercase();
    if low.is_empty() {
        return vec![];
    }
    let Some(dir) = Path::new(src).parent() else { return vec![] };
    let Ok(rd) = std::fs::read_dir(dir) else { return vec![] };
    let mut out: Vec<String> = rd
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| {
            let l = n.to_lowercase();
            (l.starts_with(&format!(".{low}.")) && l.ends_with(".incoming")) || l == format!("{low}-journal") || l == format!("{low}-wal")
        })
        .collect();
    out.sort();
    out
}

/// 置き換えを許す開き方（R4）。
fn open_shared_read(p: &str) -> std::io::Result<std::fs::File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE、FILE_FLAG_SEQUENTIAL_SCAN
        std::fs::OpenOptions::new().read(true).share_mode(0x1 | 0x2 | 0x4).custom_flags(0x0800_0000).open(p)
    }
    #[cfg(not(windows))]
    {
        std::fs::File::open(p)
    }
}

/// 使う前に中身を確かめる（R6。SQLite3 だけ中まで見る）。だめなら理由。
fn verify(tmp: &str, suffix: &str) -> Option<String> {
    if !matches!(suffix.to_lowercase().as_str(), ".sqlite3" | ".sqlite" | ".db") {
        return None;
    }
    let c = match rusqlite::Connection::open_with_flags(
        tmp,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    ) {
        Ok(c) => c,
        Err(e) => return Some(format!("開けません: {e}")),
    };
    match c.query_row("PRAGMA quick_check(1)", [], |r| r.get::<_, String>(0)) {
        Ok(s) if s.eq_ignore_ascii_case("ok") => None,
        Ok(s) => Some(format!("整合性検査に通りません: {s}")),
        Err(e) => Some(format!("読めません: {e}")),
    }
}

/// 置き場が上限を超えたら、古い写しから捨てる（_prune。いま使うものは残す）。
fn prune(keep: &str, log: &dyn Fn(&str)) {
    let d = cache_dir();
    let Ok(rd) = std::fs::read_dir(&d) else { return };
    let mut files: Vec<(std::path::PathBuf, u64, SystemTime)> = rd
        .flatten()
        .filter_map(|e| {
            let m = std::fs::metadata(e.path()).ok()?;
            let name = e.file_name().to_string_lossy().into_owned();
            (m.is_file() && paths::name_suffix(&name) != ".json").then(|| (e.path(), m.len(), m.modified().unwrap_or(UNIX_EPOCH)))
        })
        .collect();
    let mut total: u64 = files.iter().map(|f| f.1).sum();
    if total <= CACHE_TOTAL_BYTES {
        return;
    }
    files.sort_by_key(|f| f.2);
    for (p, size, _) in files {
        if total <= CACHE_TOTAL_BYTES {
            break;
        }
        let name = p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        if name == keep {
            continue;
        }
        if std::fs::remove_file(&p).is_ok() {
            let _ = std::fs::remove_file(p.with_file_name(format!("{name}.json")));
            total -= size;
            log(&format!("JOIN_CACHE_PRUNE file={name} size={size}"));
        }
    }
}

fn locks() -> &'static Mutex<HashMap<String, Arc<Mutex<()>>>> {
    static L: OnceLock<Mutex<HashMap<String, Arc<Mutex<()>>>>> = OnceLock::new();
    L.get_or_init(|| Mutex::new(HashMap::new()))
}

fn not_copied(msg: String) -> CopyError {
    CopyError::NotCopied(NotCopiedYet(msg))
}

/// read_copy（公開先を読むための手元の写しの場所。写せなければ NotCopiedYet）。src は Python の str(Path) と同じ字。
pub fn read_copy(src: &str, log: &dyn Fn(&str)) -> Result<String, CopyError> {
    let lock = locks().lock().unwrap_or_else(|e| e.into_inner()).entry(src.to_lowercase()).or_default().clone();
    let _g = lock.lock().unwrap_or_else(|e| e.into_inner());
    let sig = signature(src).map_err(|_| CopyError::Other)?; // OS の例外の文は Python と同じに作れない
    let dir = cache_dir();
    let dst = paths::join(&dir, &read_key(src, sig));
    if std::fs::metadata(&dst).map(|m| m.is_file()).unwrap_or(false) {
        // R2: 同じ版の写しがあれば共有を開かない（使った印に時刻を進める）
        if let Ok(f) = std::fs::OpenOptions::new().write(true).open(&dst) {
            let now = SystemTime::now();
            let _ = f.set_times(std::fs::FileTimes::new().set_accessed(now).set_modified(now));
        }
        return Ok(dst);
    }
    let marks = writer_marks(src);
    if let Some(m) = marks.first() {
        return Err(not_copied(format!("公開している途中のため、まだ手元へ写せません（{m}）。数秒おいてもう一度開いてください")));
    }
    if sig.0 > READ_COPY_BYTES {
        return Err(not_copied(format!(
            "{}あるので写せません（上限 {}）。公開先は直接開きません（開くと公開が止まるため）",
            size_text(sig.0),
            size_text(READ_COPY_BYTES)
        )));
    }
    // 書きかけは Python（<名前>.tmp）と別の名前にする（別のプロセスなので、同じ名前だと書き合う）
    let tmp = format!("{dst}.rs{}.tmp", std::process::id());
    let started = Instant::now();
    let copied = open_shared_read(src).and_then(|mut f| {
        let mut o = std::fs::File::create(&tmp)?;
        std::io::copy(&mut f, &mut o)?;
        Ok(())
    });
    if copied.is_err() {
        let _ = std::fs::remove_file(&tmp);
        return Err(CopyError::Other);
    }
    let after = signature(src).ok();
    if after != Some(sig) {
        let _ = std::fs::remove_file(&tmp);
        return Err(not_copied("写しているあいだに公開先が入れ替わりました。もう一度開いてください".into()));
    }
    let marks = writer_marks(src);
    if let Some(m) = marks.first() {
        let _ = std::fs::remove_file(&tmp);
        return Err(not_copied(format!("写しているあいだに書き手が書き始めました（{m}）。数秒おいてもう一度開いてください")));
    }
    if let Some(bad) = verify(&tmp, &paths::py_suffix(src)) {
        let _ = std::fs::remove_file(&tmp);
        return Err(not_copied(format!("写しが正しくないため使いません（{bad}）")));
    }
    if std::fs::rename(&tmp, &dst).is_err() {
        let _ = std::fs::remove_file(&tmp);
        return Err(CopyError::Other);
    }
    log(&format!("READ_COPY src={src} bytes={} elapsed={:.2}s", sig.0, started.elapsed().as_secs_f64()));
    let name = paths::py_name(&dst);
    prune(&name, log);
    Ok(dst)
}

// ==== 組み立てのための見本の写し（navi_localcopy.sample。結合の材料を選ぶ間だけ使う） =========

/// 先頭だけ写す形式と、丸ごとでないと壊れる形式（PREFIX_FORMATS・WHOLE_FORMATS）。
const PREFIX_FORMATS: [&str; 3] = ["csv", "txt", "fixed"];
const WHOLE_FORMATS: [&str; 3] = ["xlsx", "sqlite3", "accdb"];
/// 先頭だけ写すときの上限（4MB）と、丸ごと写すときの上限（64MB）。
const PREFIX_BYTES: u64 = 4 * 1024 * 1024;
const WHOLE_BYTES: u64 = 64 * 1024 * 1024;

/// 見本の写し（sample の答え）。path が None なら写していない（元のファイルを読む）。info は画面へそのまま渡す内訳。
pub struct Sample {
    pub path: Option<String>,
    pub info: serde_json::Map<String, serde_json::Value>,
}

/// plan_for（その形式・大きさなら、どう写すか → (写し方, 写すバイト数, 理由)）。
fn plan_for(size: u64, fmt: &str) -> (Option<&'static str>, u64, String) {
    let fmt = fmt.to_lowercase();
    if PREFIX_FORMATS.contains(&fmt.as_str()) {
        return (Some("prefix"), size.min(PREFIX_BYTES), String::new());
    }
    if WHOLE_FORMATS.contains(&fmt.as_str()) {
        if size <= WHOLE_BYTES {
            return (Some("whole"), size, String::new());
        }
        let mb = format!("{:.0}", size as f64 / 1048576.0);
        return (None, 0, format!("{mb}MBあるので写していません（途中で切ると壊れる形式です）。元のファイルを読みます"));
    }
    (None, 0, "この形式は写しません".into())
}

/// 行の切れ目で切る（_trim_to_line。途中で切れた最後の1行は捨て、囲みが開いたままなら閉じるところまで戻す）。
pub fn trim_to_line(data: &[u8]) -> &[u8] {
    let Some(cut) = data.iter().rposition(|b| *b == b'\n') else { return &[] };
    let mut out = &data[..cut + 1];
    while out.iter().filter(|b| **b == b'"').count() % 2 == 1 {
        let Some(cut) = out[..out.len() - 1].iter().rposition(|b| *b == b'\n') else { return &[] };
        out = &out[..cut + 1];
    }
    out
}

/// st_mtime（秒の float）を int にした物。Python は 秒 + ナノ秒 * 1e-9 の float を作ってから切り捨てる。
fn mtime_int(m: &std::fs::Metadata) -> Option<i64> {
    let t = m.modified().ok()?;
    let (s, ns) = match t.duration_since(UNIX_EPOCH) {
        Ok(d) => (d.as_secs() as i64, d.subsec_nanos() as i64),
        Err(e) => {
            let d = e.duration();
            let (mut s, mut ns) = (-(d.as_secs() as i64), -(d.subsec_nanos() as i64));
            if ns < 0 {
                s -= 1;
                ns += 1_000_000_000;
            }
            (s, ns)
        }
    };
    Some((s as f64 + ns as f64 * 1e-9).trunc() as i64)
}

/// 写しの名前（_key: sha1('<道の小文字>|<大きさ>|<int(更新時刻)>|<写す量>') の先頭16字＋拡張子）。
fn sample_key(src: &str, size: u64, mtime: i64, want: u64) -> String {
    let h = sha1_hex(format!("{}|{size}|{mtime}|{want}", src.to_lowercase()).as_bytes());
    format!("{}{}", &h[..16], paths::py_suffix(src).to_lowercase())
}

/// 前に写した控え（.json）から内訳を作る。読めない・形が違えば None（Python は写し直す）。
fn cached_info(meta: &str, mode: &serde_json::Value) -> Result<Option<(serde_json::Value, i64, serde_json::Value)>, ()> {
    use serde_json::Value;
    let Ok(text) = std::fs::read(meta) else { return Ok(None) };
    let Ok(text) = String::from_utf8(text) else { return Ok(None) };
    // BOM 付きは json.loads が断る（Python は写し直す）
    let Ok(Value::Object(m)) = serde_json::from_str::<Value>(if text.starts_with('\u{feff}') { "" } else { &text }) else {
        return Ok(None);
    };
    let pick = |k: &str| m.get(k).filter(|v| crate::pyish::truthy(v)).cloned();
    let bytes = match pick("bytes") {
        None => 0,
        Some(v) => match crate::pyish::int_opt(&v) {
            Ok(Some(n)) => n,
            Ok(None) => return Ok(None),
            Err(_) => return Err(()),
        },
    };
    Ok(Some((pick("mode").unwrap_or_else(|| mode.clone()), bytes, pick("note").unwrap_or_else(|| Value::String(String::new())))))
}

/// 最近使ったものとして残す（os.utime(dst, None)）。
fn touch(p: &str) -> bool {
    let now = SystemTime::now();
    std::fs::OpenOptions::new()
        .write(true)
        .open(p)
        .and_then(|f| f.set_times(std::fs::FileTimes::new().set_accessed(now).set_modified(now)))
        .is_ok()
}

/// shutil.copy2（中身と、更新・参照の時刻を写す）。
fn copy2(src: &str, dst: &str) -> std::io::Result<u64> {
    std::fs::copy(src, dst)?;
    let m = std::fs::metadata(src)?;
    let mut t = std::fs::FileTimes::new().set_modified(m.modified()?);
    if let Ok(a) = m.accessed() {
        t = t.set_accessed(a);
    }
    std::fs::OpenOptions::new().write(true).open(dst)?.set_times(t)?;
    Ok(std::fs::metadata(dst)?.len())
}

/// sample（1つのファイルを手元へ写す）。Err（Other）は Python と同じ文を作れない失敗（OS の例外の文。呼ぶ側が Python へ回す）。
pub fn sample(src: &str, fmt: &str, log: &dyn Fn(&str)) -> Result<Sample, CopyError> {
    use serde_json::{json, Value};
    let mut info: serde_json::Map<String, Value> = serde_json::Map::new();
    for (k, v) in [
        ("ok", json!(false)),
        ("mode", Value::Null),
        ("bytes", json!(0)),
        ("total", json!(0)),
        ("elapsed", json!(0.0)),
        ("cached", json!(false)),
        ("note", json!("")),
    ] {
        info.insert(k.into(), v);
    }
    let st = std::fs::metadata(src).map_err(|_| CopyError::Other)?;
    let size = st.len();
    info.insert("total".into(), json!(size));
    let (mode, want, why) = plan_for(size, fmt);
    let Some(mode) = mode else {
        info.insert("note".into(), json!(why));
        return Ok(Sample { path: None, info });
    };
    let dst = paths::join(&cache_dir(), &sample_key(src, size, mtime_int(&st).ok_or(CopyError::Other)?, want));
    let meta = format!("{dst}.json");
    let is_file = |p: &str| std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false);
    if is_file(&dst) && is_file(&meta) {
        if let Some((m, bytes, note)) = cached_info(&meta, &json!(mode)).map_err(|_| CopyError::Other)? {
            if touch(&dst) {
                info.insert("ok".into(), json!(true));
                info.insert("cached".into(), json!(true));
                info.insert("mode".into(), m);
                info.insert("bytes".into(), json!(bytes));
                info.insert("note".into(), note);
                return Ok(Sample { path: Some(dst), info });
            }
        }
    }
    let started = Instant::now();
    let wrote = if mode == "whole" {
        copy2(src, &dst).map_err(|_| CopyError::Other)?
    } else {
        use std::io::Read;
        let mut data = Vec::new();
        std::fs::File::open(src).and_then(|f| f.take(want).read_to_end(&mut data)).map_err(|_| CopyError::Other)?;
        if size > want {
            let n = trim_to_line(&data).len();
            if n == 0 {
                info.insert("note".into(), json!("1行も切り出せませんでした（1行が長すぎます）。元のファイルを読みます"));
                return Ok(Sample { path: None, info });
            }
            data.truncate(n);
        }
        std::fs::write(&dst, &data).map_err(|_| CopyError::Other)?;
        data.len() as u64
    };
    let elapsed = started.elapsed().as_secs_f64();
    let note = if mode == "whole" {
        format!("まるごとローカルへ写しました（{}）", size_text(wrote))
    } else if size > wrote {
        format!("先頭{}をローカルへ写しました（元は{}）", size_text(wrote), size_text(size))
    } else {
        format!("ローカルへ写しました（{}）", size_text(wrote))
    };
    let at = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let m = json!({"source": src, "mode": mode, "bytes": wrote, "total": size, "note": note, "at": at});
    let _ = std::fs::write(&meta, m.to_string());
    info.insert("ok".into(), json!(true));
    info.insert("mode".into(), json!(mode));
    info.insert("bytes".into(), json!(wrote));
    info.insert("elapsed".into(), json!((elapsed * 1000.0).round() / 1000.0));
    info.insert("note".into(), json!(note));
    log(&format!("JOIN_CACHE_COPY src={src} mode={mode} bytes={wrote} total={size} elapsed={elapsed:.2}s"));
    prune(&paths::py_name(&dst), log);
    Ok(Sample { path: Some(dst), info })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha1_vectors() {
        assert_eq!(sha1_hex(b""), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(sha1_hex(b"abc"), "a9993e364706816aba3e25717850c26c9cd0d89d");
        assert_eq!(sha1_hex(&[b'a'; 1000]), "291e9a6c66994949b57ba5e650361e98fc36b1ba");
    }

    #[test]
    fn sizes() {
        assert_eq!(size_text(5), "5バイト");
        assert_eq!(size_text(1536), "2KB");
        assert_eq!(size_text(READ_COPY_BYTES), "2048.0MB");
    }
}
