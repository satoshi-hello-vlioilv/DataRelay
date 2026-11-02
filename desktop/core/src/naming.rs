//! 出力ファイル名の型（変数命名）と、出力形式・拡張子（2.19.0〜）。app.py の動的ファイル名と lib/navi_output.py と同じ答えを返す。
//!
//! 型の `{…}` の中身1つを展開する:
//!   日付の変数 … {now} {exec} {datetime} {date} {time} {rne_mtime} {mtime} {rne_ctime} {ctime}
//!                対象名の直後に +N/-N（Y 年・M 月・W 週・D 日・H 時・I 分・S 秒）でずらせる（例 {now-1M:YYYYMM}）。
//!                書式は % の書式（strftime）か、記号の数で桁を決める書式（YYYYMMDD・h:s など）
//!   文字の変数 … {rne} {rne_name} {rne_stem} {name} {job} {table} {値} {value}。:left:4・:right:3・:mid:2:3・:upper・:lower・:replace:A:B で切る
//!   知らない変数は {…} のまま残す。
//!
//! 日付の計算が 1〜9999 年を出るときは失敗（`Fail`）にする。Python も ValueError・OverflowError で失敗し、画面の一覧では空になる。
//!
//! strftime は Python の datetime.strftime と同じ字にする。%f（マイクロ秒）・%z・%Z（日時に時差が無いので空）は Python が自分で
//! 置き換える分。残りは C の strftime（C ロケール）に渡る分で、Windows（UCRT）と Linux（glibc）で知っている書き方が違う:
//! Windows は知らない書き方を ValueError にし（型の既定の書式に戻る）、glibc はそのまま字として出す。%c も OS で字が違う。

use crate::paths;
use crate::pyish;
use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime, Timelike};
use serde_json::{json, Map, Value};

/// 日付の計算が 1〜9999 年を出た（Python の ValueError・OverflowError）。
#[derive(Debug, PartialEq)]
pub struct Fail;

/// 出力の形式（navi_output）。
pub const FORMATS: [&str; 5] = ["sqlite3", "txt", "csv", "xlsx", "accdb"];

fn format_alias(f: &str) -> &str {
    match f {
        "sqlite" | "db" => "sqlite3",
        "access" => "accdb",
        "excel" | "xls" => "xlsx",
        other => other,
    }
}

/// normalize_output_format(value, filename)。形式名で読めなければ、ファイル名の拡張子から。どちらも駄目なら sqlite3。
pub fn normalize_output_format(value: Option<&Value>, filename: Option<&Value>) -> &'static str {
    let fmt = pyish::strip(&pyish::text_or_empty(value)).to_lowercase();
    if let Some(f) = FORMATS.iter().find(|f| **f == format_alias(&fmt)) {
        return f;
    }
    match paths::py_suffix(&pyish::text_or_empty(filename)).to_lowercase().as_str() {
        ".accdb" => "accdb",
        ".xlsx" => "xlsx",
        ".csv" => "csv",
        ".txt" => "txt",
        _ => "sqlite3",
    }
}

/// output_extension。
pub fn output_extension(fmt: &str) -> &'static str {
    match fmt {
        "txt" => ".txt",
        "csv" => ".csv",
        "xlsx" => ".xlsx",
        "accdb" => ".accdb",
        _ => ".sqlite3",
    }
}

/// parse_output_format（形式名として読めた物だけ。読めなければ空）。
pub fn parse_output_format(v: &Value) -> &'static str {
    let fmt = pyish::strip(&pyish::text_or_empty(Some(v))).to_lowercase();
    FORMATS.iter().find(|f| **f == format_alias(&fmt)).copied().unwrap_or("")
}

/// job_extra_formats（主の形式と重なる物・読めない物を落とし、4 つまで）。並べられない値（数など）は None（Python は落ちる）。
pub fn job_extra_formats(job: &Map<String, Value>) -> Option<Vec<&'static str>> {
    let primary = normalize_output_format(job.get("output_format"), job.get("output_file"));
    let raw = job.get("extra_formats");
    let list = match raw {
        Some(Value::String(s)) => match crate::config::py_json(if s.is_empty() { "[]" } else { s }) {
            crate::config::Json::Ok(v) => pyish::py_iter(Some(&v))?,
            crate::config::Json::Bad => {
                s.split(|c: char| c == ',' || pyish::is_space(c)).filter(|x| !x.is_empty()).map(|x| json!(x)).collect()
            }
            crate::config::Json::Unsure => return None,
        },
        other => pyish::py_iter(other)?,
    };
    let mut out: Vec<&'static str> = Vec::new();
    for v in &list {
        let f = parse_output_format(v);
        if !f.is_empty() && f != primary && !out.contains(&f) {
            out.push(f);
        }
    }
    out.truncate(4);
    Some(out)
}

/// canonical_output_file（拡張子だけを形式に合わせる。二重の拡張子 勤怠.csv.csv だけは1つにする）。
pub fn canonical_output_file(filename: Option<&Value>, fmt: &str) -> String {
    let raw = pyish::text_or_empty(filename);
    let mut stem = paths::py_stem(if raw.is_empty() { "output" } else { &raw });
    if matches!(paths::py_suffix(&stem).to_lowercase().as_str(), ".sqlite3" | ".sqlite" | ".accdb" | ".xlsx" | ".xls" | ".csv" | ".txt") {
        stem = paths::py_stem(&stem);
    }
    format!("{}{}", if stem.is_empty() { "output" } else { &stem }, output_extension(fmt))
}

// ==== 日付の計算と書式 =====================================================

/// トークンの対象名から、基準名と日付のずらしを分ける（`^([A-Za-z_]+)((?:[+-]\d+[YMWDdHhIS])+)?$`）。当たらなければ (key, "")。
pub fn split_source_offset(key: &str) -> (String, String) {
    let base_len = key.chars().take_while(|c| c.is_ascii_alphabetic() || *c == '_').map(char::len_utf8).sum::<usize>();
    let (base, rest) = key.split_at(base_len);
    if base.is_empty() || !(rest.is_empty() || offsets(rest).is_some_and(|(_, all)| all)) {
        return (key.to_string(), String::new());
    }
    (base.to_string(), rest.to_string())
}

/// ずらしの並び（[+-]\d+ と単位）。→ (拾えた物, 全体がずらしだけでできているか)。数字は Unicode の数字も読む。
fn offsets(s: &str) -> Option<(Vec<(String, char)>, bool)> {
    let chars: Vec<char> = s.chars().collect();
    let (mut i, mut found, mut all) = (0, Vec::new(), true);
    while i < chars.len() {
        if matches!(chars[i], '+' | '-') {
            let mut j = i + 1;
            while j < chars.len() && pyish::digit(chars[j]).is_some() {
                j += 1;
            }
            if j > i + 1 && j < chars.len() && "YMWDdHhIS".contains(chars[j]) {
                found.push((chars[i..j].iter().collect(), chars[j]));
                i = j + 1;
                continue;
            }
        }
        all = false;
        i += 1;
    }
    Some((found, all))
}

/// 年月をずらす（EDATE と同じく、無い日は月末へ）。
fn shift_months(dt: NaiveDateTime, months: i64) -> Result<NaiveDateTime, Fail> {
    let total = i64::from(dt.year()).checked_mul(12).and_then(|v| v.checked_add(i64::from(dt.month0()) + months)).ok_or(Fail)?;
    let (y, m) = (total.div_euclid(12), total.rem_euclid(12) as u32 + 1);
    if !(1..=9999).contains(&y) {
        return Err(Fail);
    }
    let last = crate::period::last_day(y, m);
    let d = NaiveDate::from_ymd_opt(y as i32, m, dt.day().min(last)).ok_or(Fail)?;
    Ok(d.and_time(dt.time()))
}

fn in_range(dt: NaiveDateTime) -> Result<NaiveDateTime, Fail> {
    if (1..=9999).contains(&dt.year()) {
        Ok(dt)
    } else {
        Err(Fail)
    }
}

/// apply_date_offset（年→月→週→日→時→分→秒の順に当てる）。
pub fn apply_date_offset(dt: NaiveDateTime, offset: &str) -> Result<NaiveDateTime, Fail> {
    if offset.is_empty() {
        return Ok(dt);
    }
    let order = |u: char| match u {
        'Y' => 0,
        'M' => 1,
        'W' => 2,
        'D' | 'd' => 3,
        'H' | 'h' => 4,
        'I' => 5,
        _ => 6,
    };
    let mut parts = offsets(offset).map(|(f, _)| f).unwrap_or_default();
    parts.sort_by_key(|(_, u)| order(*u));
    let mut dt = dt;
    for (num, unit) in parts {
        let n = pyish::int_text(&num).ok().flatten().ok_or(Fail)?;
        // timedelta は ±999999999 日まで
        let span = |secs_per: i64| -> Result<Duration, Fail> {
            let secs = n.checked_mul(secs_per).ok_or(Fail)?;
            if secs.abs() / 86400 > 999_999_999 {
                return Err(Fail);
            }
            Duration::try_seconds(secs).ok_or(Fail)
        };
        dt = match unit {
            'Y' => shift_months(dt, n.checked_mul(12).ok_or(Fail)?)?,
            'M' => shift_months(dt, n)?,
            'W' => in_range(dt.checked_add_signed(span(7 * 86400)?).ok_or(Fail)?)?,
            'D' | 'd' => in_range(dt.checked_add_signed(span(86400)?).ok_or(Fail)?)?,
            'H' | 'h' => in_range(dt.checked_add_signed(span(3600)?).ok_or(Fail)?)?,
            'I' => in_range(dt.checked_add_signed(span(60)?).ok_or(Fail)?)?,
            _ => in_range(dt.checked_add_signed(span(1)?).ok_or(Fail)?)?,
        };
    }
    Ok(dt)
}

/// 記号の数で桁を決める書式か（% を含まず、Y M D d H h m s のどれかを含む）。
pub fn looks_like_custom_pattern(arg: &str) -> bool {
    !arg.is_empty() && !arg.contains('%') && arg.chars().any(|c| "YMDdHhms".contains(c))
}

/// format_custom_datetime（同じ記号の続く数が、そのまま 0 埋めの桁数）。
pub fn format_custom_datetime(dt: NaiveDateTime, pattern: &str) -> String {
    let chars: Vec<char> = pattern.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        let ch = chars[i];
        let letter = "YMDdHhms".contains(ch);
        let mut j = i + 1;
        while j < chars.len() && if letter { chars[j] == ch } else { !"YMDdHhms".contains(chars[j]) } {
            j += 1;
        }
        let n = j - i;
        let pad = |v: u32| format!("{v:0n$}");
        match ch {
            'Y' if n < 4 => {
                let y = dt.year() as u64 % 10u64.pow(n as u32);
                out.push_str(&format!("{y:0n$}"))
            }
            'Y' => out.push_str(&format!("{:0n$}", dt.year())),
            'M' => out.push_str(&pad(dt.month())),
            'D' | 'd' => out.push_str(&pad(dt.day())),
            'H' | 'h' => out.push_str(&pad(dt.hour())),
            'm' => out.push_str(&pad(dt.minute())),
            's' => out.push_str(&pad(dt.second())),
            _ => out.extend(&chars[i..j]),
        }
        i = j;
    }
    out
}

const DAYS: [&str; 7] = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS: [&str; 12] =
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/// strftime が書式を断った（Python の ValueError。Windows の知らない書き方・NUL 文字）。
#[derive(Debug, PartialEq)]
pub struct BadFormat;

/// datetime.strftime（C ロケール）。
pub fn strftime(dt: NaiveDateTime, fmt: &str) -> Result<String, BadFormat> {
    // NUL の入った書式: Python 3.12 は Windows では ValueError（字を幅広の文字へ直すところで断る）、
    // Linux ではバイト列にして C へ渡すので NUL の手前で切れる
    let fmt = match fmt.find('\0') {
        Some(_) if cfg!(windows) => return Err(BadFormat),
        Some(i) => &fmt[..i],
        None => fmt,
    };
    let chars: Vec<char> = fmt.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] != '%' {
            out.push(chars[i]);
            i += 1;
            continue;
        }
        let Some(&next) = chars.get(i + 1) else {
            // 末尾の % だけ
            if cfg!(windows) {
                return Err(BadFormat);
            }
            out.push('%');
            break;
        };
        // Python が自分で置き換える分（OS によらない）
        match next {
            'f' => {
                out.push_str(&format!("{:06}", dt.nanosecond() / 1000 % 1_000_000));
                i += 2;
                continue;
            }
            'z' | 'Z' => {
                i += 2;
                continue;
            }
            ':' if chars.get(i + 2) == Some(&'z') => {
                i += 3;
                continue;
            }
            _ => {}
        }
        let (flag, d, used) = if cfg!(windows) {
            if next == '#' {
                (Some('#'), chars.get(i + 2).copied(), 3)
            } else {
                (None, Some(next), 2)
            }
        } else if matches!(next, '-' | '_' | '0' | '^' | '#') {
            (Some(next), chars.get(i + 2).copied(), 3)
        } else {
            (None, Some(next), 2)
        };
        let Some(d) = d else {
            if cfg!(windows) {
                return Err(BadFormat);
            }
            out.extend(&chars[i..]);
            break;
        };
        match directive(dt, d, flag) {
            Some(s) => out.push_str(&s),
            None if cfg!(windows) => return Err(BadFormat),
            None => out.extend(&chars[i..i + used]),
        }
        i += used;
    }
    Ok(out)
}

/// 1つの書き方。知らない書き方は None。flag は Windows の #（数の前の 0 を落とす）と glibc の - _ 0 ^ #。
fn directive(dt: NaiveDateTime, d: char, flag: Option<char>) -> Option<String> {
    // 数（width 桁の 0 埋め。e だけは空白埋め）
    let num = |v: i64, width: usize, space: bool| -> String {
        match flag {
            Some('#') if cfg!(windows) => v.to_string(),
            Some('-') => v.to_string(),
            Some('_') => format!("{v:>width$}"),
            Some('0') => format!("{v:0width$}"),
            _ if space => format!("{v:>width$}"),
            _ => format!("{v:0width$}"),
        }
    };
    let text = |s: &str| -> String {
        if flag == Some('^') {
            s.to_uppercase()
        } else if flag == Some('#') && !cfg!(windows) {
            // glibc の # は字の大文字小文字を入れ替える（%p は小文字に、%a %A %b %B %h は大文字に）
            if d == 'p' {
                s.to_lowercase()
            } else {
                s.to_uppercase()
            }
        } else {
            s.to_string()
        }
    };
    let wday = dt.weekday().num_days_from_sunday() as i64;
    let yday = dt.ordinal0() as i64;
    let iso = dt.iso_week();
    let h12 = match dt.hour() % 12 {
        0 => 12,
        h => h,
    } as i64;
    let year = dt.year() as i64;
    let sub = |f: &str| strftime(dt, f).unwrap_or_default();
    Some(match d {
        'a' => text(&DAYS[wday as usize][..3]),
        'A' => text(DAYS[wday as usize]),
        'b' | 'h' => text(&MONTHS[dt.month0() as usize][..3]),
        'B' => text(MONTHS[dt.month0() as usize]),
        'C' => num(year / 100, if cfg!(windows) { 2 } else { 1 }, false),
        'd' => num(dt.day() as i64, 2, false),
        'e' => num(dt.day() as i64, 2, true),
        'D' => sub("%m/%d/%y"),
        'F' => sub("%Y-%m-%d"),
        'g' => num(i64::from(iso.year()) % 100, 2, false),
        'G' => num(i64::from(iso.year()), if cfg!(windows) { 4 } else { 1 }, false),
        'H' => num(dt.hour() as i64, 2, false),
        'I' => num(h12, 2, false),
        'j' => num(yday + 1, 3, false),
        'm' => num(dt.month() as i64, 2, false),
        'M' => num(dt.minute() as i64, 2, false),
        'n' => "\n".into(),
        'p' => text(if dt.hour() < 12 { "AM" } else { "PM" }),
        'r' => sub("%I:%M:%S %p"),
        'R' => sub("%H:%M"),
        'S' => num(dt.second() as i64, 2, false),
        't' => "\t".into(),
        'T' => sub("%H:%M:%S"),
        'u' => num(if wday == 0 { 7 } else { wday }, 1, false),
        'U' => num((yday + 7 - wday) / 7, 2, false),
        'V' => num(i64::from(iso.week()), 2, false),
        'w' => num(wday, 1, false),
        'W' => num((yday + 7 - (wday + 6) % 7) / 7, 2, false),
        'x' => sub("%m/%d/%y"),
        'X' => sub("%H:%M:%S"),
        'y' => num(year % 100, 2, false),
        'Y' => num(year, if cfg!(windows) { 4 } else { 1 }, false),
        'c' if cfg!(windows) => sub("%m/%d/%y %H:%M:%S"),
        'c' => sub("%a %b %e %H:%M:%S %Y"),
        '%' => "%".into(),
        // glibc だけが知っている書き方
        'k' if !cfg!(windows) => num(dt.hour() as i64, 2, true),
        'l' if !cfg!(windows) => num(h12, 2, true),
        'P' if !cfg!(windows) => (if dt.hour() < 12 { "am" } else { "pm" }).into(),
        // glibc の %s は、日時をこの PC の時刻として読んだ通算秒（mktime）
        's' if !cfg!(windows) => {
            use chrono::TimeZone;
            chrono::Local.from_local_datetime(&dt).earliest()?.timestamp().to_string()
        }
        _ => return None,
    })
}

/// _apply_text_op（:left:4・:right:3・:mid:2:3・:upper・:lower・:replace:A:B。読めなければ元の字）。
pub fn apply_text_op(value: &str, arg: &str) -> String {
    if arg.is_empty() {
        return value.to_string();
    }
    let parts: Vec<&str> = arg.split(':').collect();
    let op = pyish::strip(parts[0]).to_lowercase();
    // int(parts[i])（Python の大きな数は、切り出しでは端と同じ）
    let int = |i: usize| -> Option<i64> {
        match pyish::int_text(parts.get(i)?) {
            Ok(v) => v,
            Err(_) => {
                let neg = pyish::strip(parts[i]).starts_with('-');
                Some(if neg { i64::MIN / 4 } else { i64::MAX / 4 })
            }
        }
    };
    let r = match op.as_str() {
        "left" => int(1).map(|n| pyish::slice(value, None, Some(n.max(0)))),
        "right" => int(1).map(|n| if n.max(0) > 0 { pyish::slice(value, Some(-n), None) } else { String::new() }),
        "mid" => int(1).and_then(|s| int(2).map(|l| pyish::slice(value, Some(s), Some(s.saturating_add(l))))),
        "upper" => Some(value.to_uppercase()),
        "lower" => Some(value.to_lowercase()),
        "replace" => parts.get(1).map(|a| value.replace(a, parts.get(2).copied().unwrap_or(""))),
        _ => None,
    };
    r.unwrap_or_else(|| value.to_string())
}

// ==== 型の展開 =============================================================

/// 値ごとに分けて出すときの、その回の値の変数（navi_variants.TOKENS）。
pub const VALUE_TOKENS: [&str; 2] = ["値", "value"];
const DATE_KEYS: [&str; 9] = ["now", "exec", "datetime", "date", "time", "rne_mtime", "mtime", "rne_ctime", "ctime"];
const TEXT_KEYS: [&str; 6] = ["rne", "rne_name", "rne_stem", "name", "job", "table"];

/// 型で使える変数（_filename_tokens）。
pub struct Tokens {
    date: Vec<(&'static str, Option<NaiveDateTime>, &'static str)>,
    text: Vec<(&'static str, String)>,
}

/// ファイルの時刻（datetime.fromtimestamp と同じく、秒の小数をマイクロ秒へ偶数丸めしてから、この PC の時刻へ）。
fn local_stamp(t: std::time::SystemTime) -> Option<NaiveDateTime> {
    let secs = match t.duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => d.as_secs_f64(),
        Err(e) => -e.duration().as_secs_f64(),
    };
    let whole = secs.floor();
    let mut us = ((secs - whole) * 1e6).round_ties_even() as i64;
    let mut s = whole as i64;
    if us >= 1_000_000 {
        s += 1;
        us -= 1_000_000;
    }
    use chrono::TimeZone;
    chrono::Local.timestamp_opt(s, (us * 1000) as u32).single().map(|d| d.naive_local())
}

impl Tokens {
    pub fn new(job: &Map<String, Value>, rne_path: Option<&str>, now: NaiveDateTime) -> Tokens {
        let src = job.get("rne").filter(|v| pyish::truthy(v)).or_else(|| job.get("rne_path"));
        let stem = paths::py_stem(&pyish::text_or_empty(src));
        let (mut mtime, mut ctime) = (None, None);
        if let Some(p) = rne_path.filter(|p| !p.is_empty()) {
            if let Some(md) = std::fs::metadata(p).ok().filter(|m| m.is_file()) {
                mtime = md.modified().ok().and_then(local_stamp);
                ctime = created(&md).and_then(local_stamp).or(mtime);
            }
        }
        let name = pyish::text_or_empty(job.get("name"));
        let mut text = vec![
            ("rne", stem.clone()),
            ("rne_name", stem.clone()),
            ("rne_stem", stem),
            ("name", name.clone()),
            ("job", name),
            ("table", pyish::text_or_empty(job.get("table"))),
        ];
        for t in VALUE_TOKENS {
            text.push((t, pyish::text_or_empty(job.get("_variant_value"))));
        }
        let (n, m, c) = (Some(now), mtime, ctime);
        Tokens {
            date: vec![
                ("now", n, "%Y%m%d_%H%M%S"),
                ("exec", n, "%Y%m%d_%H%M%S"),
                ("datetime", n, "%Y%m%d_%H%M%S"),
                ("date", n, "%Y%m%d"),
                ("time", n, "%H%M%S"),
                ("rne_mtime", m, "%Y%m%d"),
                ("mtime", m, "%Y%m%d"),
                ("rne_ctime", c, "%Y%m%d"),
                ("ctime", c, "%Y%m%d"),
            ],
            text,
        }
    }

    /// {…} の中身1つを展開する（_expand_token）。→ (字, 変数だったか)。知らない変数は {…} ごと残す。
    pub fn expand(&self, raw: &str) -> Result<(String, bool), Fail> {
        let raw = pyish::strip(raw);
        let (key, arg) = match raw.split_once(':') {
            Some((k, a)) => (pyish::strip(k), a),
            None => (raw, ""),
        };
        let (base, offset) = split_source_offset(key);
        if let Some((_, dt, default)) = self.date.iter().find(|(k, _, _)| *k == base) {
            let Some(dt) = dt else { return Ok((String::new(), true)) };
            let dt = apply_date_offset(*dt, &offset)?;
            if looks_like_custom_pattern(arg) {
                return Ok((format_custom_datetime(dt, arg), true));
            }
            let fmt = if arg.is_empty() { default } else { arg };
            return Ok((strftime(dt, fmt).or_else(|_| strftime(dt, default)).unwrap_or_default(), true));
        }
        if let Some((_, v)) = self.text.iter().find(|(k, _)| *k == key) {
            return Ok((apply_text_op(v, arg), true));
        }
        Ok((format!("{{{raw}}}"), false))
    }
}

#[cfg(windows)]
fn created(md: &std::fs::Metadata) -> Option<std::time::SystemTime> {
    md.created().ok()
}

/// Linux の st_ctime は「属性を変えた時刻」（Python も同じ値を読む）。
#[cfg(unix)]
fn created(md: &std::fs::Metadata) -> Option<std::time::SystemTime> {
    use std::os::unix::fs::MetadataExt;
    let (s, ns) = (md.ctime(), md.ctime_nsec());
    let base = std::time::UNIX_EPOCH;
    if s >= 0 {
        base.checked_add(std::time::Duration::new(s as u64, ns as u32))
    } else {
        base.checked_sub(std::time::Duration::from_secs(s.unsigned_abs()))
            .and_then(|t| t.checked_add(std::time::Duration::from_nanos(ns as u64)))
    }
}

#[cfg(not(any(windows, unix)))]
fn created(_: &std::fs::Metadata) -> Option<std::time::SystemTime> {
    None
}

/// 型の `{…}` を順に拾う（正規表現 `\{([^}]*)\}` と同じ当て方）。→ (始まり, 終わり, 中身) のバイト位置。
fn braces(s: &str) -> Vec<(usize, usize, &str)> {
    let mut out = Vec::new();
    let mut pos = 0;
    while let Some(a) = s[pos..].find('{').map(|i| i + pos) {
        let Some(b) = s[a + 1..].find('}').map(|i| i + a + 1) else { break };
        out.push((a, b + 1, &s[a + 1..b]));
        pos = b + 1;
    }
    out
}

fn is_illegal(c: char) -> bool {
    matches!(c, '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|')
}

fn drop_illegal(s: &str) -> String {
    s.chars().filter(|c| !is_illegal(*c)).collect()
}

/// render_filename_template（ファイル名に使えない字を落とし、続く空白を1つに、前後の空白と . を落とす。空なら output）。
pub fn render_filename_template(template: &str, tokens: &Tokens) -> Result<String, Fail> {
    let mut rendered = String::new();
    let mut pos = 0;
    for (a, b, inner) in braces(template) {
        rendered.push_str(&template[pos..a]);
        rendered.push_str(&tokens.expand(inner)?.0);
        pos = b;
    }
    rendered.push_str(&template[pos..]);
    let mut squeezed = String::new();
    let mut in_space = false;
    for c in drop_illegal(&rendered).chars() {
        if pyish::is_space(c) {
            if !in_space {
                squeezed.push(' ');
            }
            in_space = true;
        } else {
            squeezed.push(c);
            in_space = false;
        }
    }
    let out = pyish::strip(&squeezed).trim_matches('.').to_string();
    Ok(if out.is_empty() { "output".into() } else { out })
}

/// render_filename_segments（固定の部分と、変数から展開した部分に分ける。一覧で変数の部分に色を付ける）。
pub fn render_filename_segments(template: &str, tokens: &Tokens) -> Result<Vec<(String, bool)>, Fail> {
    let mut segs: Vec<(String, bool)> = Vec::new();
    let mut pos = 0;
    for (a, b, inner) in braces(template) {
        if a > pos {
            segs.push((template[pos..a].to_string(), false));
        }
        segs.push(tokens.expand(inner)?);
        pos = b;
    }
    if pos < template.len() {
        segs.push((template[pos..].to_string(), false));
    }
    let mut out: Vec<(String, bool)> = Vec::new();
    for (text, var) in segs {
        let t = drop_illegal(&text);
        if t.is_empty() {
            continue;
        }
        match out.last_mut() {
            Some(last) if last.1 == var => last.0.push_str(&t),
            _ => out.push((t, var)),
        }
    }
    Ok(out)
}

/// has_template_variables（知っている変数 {…} が1つでもあるか。ただの字は変数にしない）。
pub fn has_template_variables(pattern: &str) -> bool {
    braces(pattern).iter().any(|(_, _, inner)| {
        let key = pyish::strip(pyish::strip(inner).split(':').next().unwrap_or(""));
        let (base, _) = split_source_offset(key);
        DATE_KEYS.contains(&base.as_str()) || TEXT_KEYS.contains(&base.as_str()) || VALUE_TOKENS.contains(&base.as_str())
    })
}

/// 型のファイル名（resolve_output_filename）。rne_path は RNE の在りか（読めなければ None）。
pub fn resolve_output_filename(job: &Map<String, Value>, rne_path: Option<&str>, now: NaiveDateTime) -> Result<String, Fail> {
    let fmt = normalize_output_format(job.get("output_format"), job.get("output_file"));
    let mode = text_or(job.get("naming_mode"), "fixed").to_lowercase();
    let pattern = pyish::text_or_empty(job.get("output_pattern"));
    let base = if mode == "template" && !pyish::strip(&pattern).is_empty() {
        render_filename_template(&pattern, &Tokens::new(job, rne_path, now))?
    } else {
        paths::py_stem(&text_or(job.get("output_file"), "output"))
    };
    Ok(canonical_output_file(Some(&Value::String(base)), fmt))
}

/// job_output_plan（1回の実行で作るファイル。先頭が主）。
pub fn job_output_plan(job: &Map<String, Value>, rne_path: Option<&str>, now: NaiveDateTime) -> Result<Option<Value>, Fail> {
    let base = resolve_output_filename(job, rne_path, now)?;
    let primary = normalize_output_format(job.get("output_format"), job.get("output_file"));
    let Some(extra) = job_extra_formats(job) else { return Ok(None) };
    let mut plan = vec![json!({"format": primary, "file": base, "primary": true})];
    for f in extra {
        plan.push(json!({"format": f, "file": canonical_output_file(Some(&Value::String(base.clone())), f), "primary": false}));
    }
    Ok(Some(Value::Array(plan)))
}

/// `str(v or default)`。
pub fn text_or(v: Option<&Value>, default: &str) -> String {
    match v {
        Some(v) if pyish::truthy(v) => pyish::py_str(v),
        _ => default.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(y: i32, m: u32, d: u32, h: u32, mi: u32, s: u32) -> NaiveDateTime {
        NaiveDate::from_ymd_opt(y, m, d).unwrap().and_hms_micro_opt(h, mi, s, 123456).unwrap()
    }

    #[test]
    fn offsets_like_python() {
        assert_eq!(split_source_offset("now-1M+2D"), ("now".into(), "-1M+2D".into()));
        assert_eq!(split_source_offset("now-1Mx"), ("now-1Mx".into(), "".into()));
        assert_eq!(split_source_offset("rne"), ("rne".into(), "".into()));
        let dt = at(2026, 3, 31, 9, 5, 7);
        assert_eq!(apply_date_offset(dt, "-1M").unwrap(), at(2026, 2, 28, 9, 5, 7), "無い日は月末");
        assert_eq!(apply_date_offset(dt, "+1D-1Y").unwrap(), at(2025, 4, 1, 9, 5, 7), "年が先");
        assert_eq!(apply_date_offset(dt, "+99999Y"), Err(Fail));
        assert_eq!(apply_date_offset(dt, "+１D").unwrap(), at(2026, 4, 1, 9, 5, 7), "全角の数字も読む");
    }

    #[test]
    fn formats_like_python() {
        let dt = at(2026, 1, 4, 15, 5, 7);
        assert_eq!(format_custom_datetime(dt, "YYYYMD"), "202614");
        assert_eq!(format_custom_datetime(dt, "YY-MM-DD h:m:ss"), "26-01-04 15:5:07");
        assert_eq!(strftime(dt, "%Y%m%d_%H%M%S.%f%z").unwrap(), "20260104_150507.123456");
        assert_eq!(strftime(dt, "%a %A %b %j %U %W %V %G %u %w %I%p").unwrap(), "Sun Sunday Jan 004 01 00 01 2026 7 0 03PM");
        assert_eq!(apply_text_op("ABCDEFG", "mid:-3:2"), "EF");
        assert_eq!(apply_text_op("ABCDEFG", "right:99"), "ABCDEFG");
        assert_eq!(apply_text_op("ABCDEFG", "left:x"), "ABCDEFG", "読めない数は元のまま");
        assert_eq!(apply_text_op("ABC", "replace:B"), "AC");
    }

    #[test]
    fn templates_like_python() {
        let mut job = Map::new();
        job.insert("rne".into(), json!("C:/rne/仕掛.RNE"));
        job.insert("name".into(), json!("日次"));
        let t = Tokens::new(&job, None, at(2026, 11, 1, 9, 5, 7));
        assert_eq!(render_filename_template("{rne}_{now-1D:YYYYMMDD}_{x}_{rne_mtime}", &t).unwrap(), "仕掛_20261031_{x}_");
        assert_eq!(
            render_filename_segments("a/{name}{date}:b", &t).unwrap(),
            vec![("a".to_string(), false), ("日次20261101".to_string(), true), ("b".to_string(), false)]
        );
        assert!(has_template_variables("x{now+1D}"));
        assert!(!has_template_variables("SIKALOTDEF{unknown}"));
        assert_eq!(render_filename_template(" .. ", &t).unwrap(), "output");
    }

    #[test]
    fn output_names_like_python() {
        assert_eq!(normalize_output_format(Some(&json!("Excel")), None), "xlsx");
        assert_eq!(normalize_output_format(Some(&json!("?")), Some(&json!("a.CSV"))), "csv");
        assert_eq!(canonical_output_file(Some(&json!("勤怠CSV.csv")), "csv"), "勤怠CSV.csv");
        assert_eq!(canonical_output_file(Some(&json!("勤怠.csv.csv")), "xlsx"), "勤怠.xlsx");
        assert_eq!(canonical_output_file(None, "txt"), "output.txt");
    }
}
