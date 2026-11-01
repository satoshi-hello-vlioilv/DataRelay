//! 記録（<このPC>\logs\app.log）を読む・Rust の中身の行を書く（2.18.0〜）。
//!
//! 書き手はまだ主に Python（lib/navi_log.py の FileHandler）。Rust の中身の行も同じファイルへ、同じ形
//! （`2026-11-01 12:00:00,123 [INFO] [pid 1234] …`）で書く ―― 画面の「ログ」と事前診断が同じ読み方で読めるように。
//! 書くたびに開いて閉じる（開いたままにすると、Python がワーカーの居ない間に行う付け替え〈名前の変更〉を Windows が断る）。
//!
//! 読む側（GET /api/log）は navi_web.get_log・app.read_log_lines と同じ答え。末尾 4MB だけを読み、行の区切りは
//! Python の str.splitlines と同じにする。違いが1つある: Python は読む前に「同じ内容の行の省略」で溜めている最後の行を
//! 書き出してから読む。Rust は Python の中に溜まった行には触れないので、省略が続いている最中の最後の1行は、その区間が
//! 閉じたとき（別の行が来る・30 秒たつ）に出る。

use crate::http::{Ask, Reply};
use crate::{paths, pyish, routes::Core};
use serde_json::{json, Value};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

/// 末尾 4MB。178 列のログでも数万行ぶんある（app.LOG_READ_BYTES）
pub const READ_BYTES: u64 = 4 * 1024 * 1024;

/// 画面の絞り込み（app.LOG_FILTERS。並びも同じ）。
pub const FILTERS: [(&str, &str, &str); 3] = [
    ("split", r"SPLIT_|AXIS_|ROW_|COLUMN_|CONDITION_ITEMS|SPLIT_BASELINE", "分割まわり"),
    ("problem", r"\[ERROR\]|\[WARNING\]", "エラーと警告"),
    ("all", "", "すべて"),
];

pub fn log_dir(local_root: &Path) -> PathBuf {
    local_root.join("logs")
}

/// 1行を書く（Python の logging と同じ形。時刻はミリ秒まで、プロセス番号はこの窓）。書けなければ黙って捨てる（記録のために本業を止めない）。
pub fn write(local_root: &Path, level: &str, msg: &str) {
    let dir = log_dir(local_root);
    let _ = std::fs::create_dir_all(&dir);
    let now = chrono::Local::now();
    let line =
        format!("{},{:03} [{level}] [pid {}] {msg}\n", now.format("%Y-%m-%d %H:%M:%S"), now.timestamp_subsec_millis(), std::process::id());
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("app.log")) {
        let _ = f.write_all(line.as_bytes());
    }
}

/// Python の str.splitlines（\n・\r・\r\n・\v・\f・\x1c〜\x1e・\x85・ ・  で分ける。区切りは残さない）。
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if matches!(c, '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}') {
            out.push(&s[start..i]);
            let mut next = i + c.len_utf8();
            if c == '\r' {
                if let Some((j, '\n')) = it.peek().copied() {
                    it.next();
                    next = j + 1;
                }
            }
            start = next;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// 末尾だけを読む（navi_log.tail_lines）。途中から読んだときは、最初の半端な1行を捨てる。→ (行, 大きさ, 途中からか)
pub fn tail_lines(path: &Path, max_bytes: u64) -> (Vec<String>, u64, bool) {
    let Ok(size) = std::fs::metadata(path).map(|m| m.len()) else { return (vec![], 0, false) };
    let start = size.saturating_sub(max_bytes);
    let mut raw = Vec::new();
    let ok = std::fs::File::open(path).and_then(|mut f| {
        f.seek(SeekFrom::Start(start))?;
        f.read_to_end(&mut raw)
    });
    if ok.is_err() {
        return (vec![], size, start > 0);
    }
    let text = String::from_utf8_lossy(&raw);
    let mut lines: Vec<String> = splitlines(&text).into_iter().map(String::from).collect();
    if start > 0 && !lines.is_empty() {
        lines.remove(0);
    }
    (lines, size, start > 0)
}

/// 新しい順に、いま残っている記録（navi_log.log_files）。app.log → app.1.log → app.2.log …
pub fn log_files(dir: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let main = dir.join("app.log");
    if main.exists() {
        out.push(main);
    }
    let mut olds: Vec<(i64, PathBuf)> = std::fs::read_dir(dir)
        .map(|it| {
            it.filter_map(Result::ok)
                .filter_map(|e| {
                    let name = e.file_name().to_string_lossy().into_owned();
                    let lower = if cfg!(windows) { name.to_lowercase() } else { name.clone() };
                    // glob('app.*.log'): app. で始まり .log で終わり、間に1字以上（app.log 自身は当たらない）
                    if !(lower.starts_with("app.") && lower.ends_with(".log") && lower.len() >= "app..log".len()) {
                        return None;
                    }
                    let stem = &name[..name.len() - 4];
                    let last = stem.rsplit('.').next().unwrap_or("");
                    let digits: String = last.chars().filter(char::is_ascii_digit).collect();
                    let n = digits.parse::<i64>().unwrap_or(0);
                    e.path().is_file().then(|| (n, e.path()))
                })
                .collect()
        })
        .unwrap_or_default();
    olds.sort_by_key(|(n, _)| *n);
    out.extend(olds.into_iter().map(|(_, p)| p));
    out
}

/// round(x, 1)（Python の丸め＝表せる値どおりに、ちょうど半分なら偶数へ）。
fn round1(x: f64) -> f64 {
    format!("{x:.1}").parse().unwrap_or(x)
}

fn mb(bytes: u64) -> f64 {
    round1(bytes as f64 / 1024.0 / 1024.0)
}

/// 問い合わせ文字（a=1&b=2）の最初の値（Flask の request.args.get。+ は空白、%XX は戻す）。
pub fn query_arg(query: &str, key: &str) -> Option<String> {
    query.split('&').find_map(|kv| {
        let (k, v) = kv.split_once('=').unwrap_or((kv, ""));
        (decode(k) == key).then(|| decode(v))
    })
}

fn decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < b.len() && b[i + 1].is_ascii_hexdigit() && b[i + 2].is_ascii_hexdigit() => {
                let h = |c: u8| (c as char).to_digit(16).unwrap_or(0) as u8;
                out.push(h(b[i + 1]) * 16 + h(b[i + 2]));
                i += 2;
            }
            c => out.push(c),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// 記録の行を読む（app.read_log_lines）。→ (残った行, 読んだ行数, 大きさ, 途中からか)
pub fn read_lines(path: &Path, limit: i64, q: &str, preset: &str) -> (Vec<String>, usize, u64, bool) {
    if !path.exists() {
        return (vec![], 0, 0, false);
    }
    let (mut lines, size, clipped) = tail_lines(path, READ_BYTES);
    let total = lines.len();
    let pat = FILTERS.iter().find(|(id, _, _)| *id == preset).map(|(_, p, _)| *p).unwrap_or("");
    if !pat.is_empty() {
        if let Ok(rx) = fancy_regex::Regex::new(pat) {
            lines.retain(|x| rx.is_match(x).unwrap_or(false));
        }
    }
    let q = pyish::strip(q);
    if !q.is_empty() {
        // 正規表現として読めれば正規表現（大文字小文字を区別しない）、読めなければそのままの字を探す
        match fancy_regex::RegexBuilder::new(q).case_insensitive(true).build() {
            Ok(rq) => lines.retain(|x| rq.is_match(x).unwrap_or(false)),
            Err(_) => {
                let lq = q.to_lowercase();
                lines.retain(|x| x.to_lowercase().contains(&lq));
            }
        }
    }
    let n = limit.clamp(1, 5000) as usize;
    let keep = lines.split_off(lines.len().saturating_sub(n));
    (keep, total, size, clipped)
}

/// GET /api/log … 記録の末尾（絞り込み・検索・行数の上限）と、残っている前の世代。
pub(crate) fn get_log(_: &Core, ask: &Ask, _: &[String]) -> Reply {
    let local = PathBuf::from(paths::py_path(&paths::local_root().to_string_lossy()));
    let dir = log_dir(&local);
    // int(request.args.get('limit') or 1200)、読めなければ 1200。0 も 1200（limit or 1200）
    let limit = match query_arg(ask.query, "limit").filter(|s| !s.is_empty()) {
        Some(s) => match pyish::int_or(Some(&Value::String(s)), i64::MIN) {
            Ok(v) if v != i64::MIN => v,
            _ => 1200,
        },
        None => 1200,
    };
    let limit = if limit == 0 { 1200 } else { limit };
    let q = query_arg(ask.query, "q").unwrap_or_default();
    let preset = query_arg(ask.query, "filter").unwrap_or_default();
    let (lines, total, size, clipped) = read_lines(&dir.join("app.log"), limit, &q, &preset);
    let older: Vec<Value> = log_files(&dir)
        .into_iter()
        .skip(1)
        .map(|p| json!({"name": p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default(), "mb": mb(std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0))}))
        .collect();
    Reply::json(
        200,
        &json!({
            "text": lines.join("\n"), "total": total, "matched": lines.len(), "size_mb": mb(size), "clipped": clipped,
            "window_mb": mb(READ_BYTES), "older": older,
            "filters": FILTERS.iter().map(|(id, _, label)| json!({"id": id, "label": label})).collect::<Vec<_>>(),
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_like_python() {
        assert_eq!(splitlines("a\r\nb\rc\nd\u{85}e\u{2028}f\x0cg"), vec!["a", "b", "c", "d", "e", "f", "g"]);
        assert_eq!(splitlines("a\n\nb\n"), vec!["a", "", "b"]);
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("\r\n"), vec![""]);
    }

    #[test]
    fn query_like_flask() {
        assert_eq!(query_arg("limit=5&q=a+b%E3%81%82&q=x", "q").as_deref(), Some("a bあ"));
        assert_eq!(query_arg("limit", "limit").as_deref(), Some(""));
        assert_eq!(query_arg("", "q"), None);
    }

    #[test]
    fn round_like_python() {
        assert_eq!(round1(0.05), 0.1, "0.05 は 0.05000000000000000277… なので上へ");
        assert_eq!(round1(2.25), 2.2, "ちょうど半分は偶数へ");
        assert_eq!(round1(4.0), 4.0);
    }
}
