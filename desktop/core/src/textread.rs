//! テキストの読み取り（2.26.0〜）。lib/navi_text.py の read_text_rows・preview_text・sniff_delimited と同じ結果にする。
//!
//! 読取マスタの画面の「下読み」（POST /api/text-preview）と「区切りの見当付け」（POST /api/text-sniff）に答える。
//! 実行（中間 CSV を作る）は、まだ Python が受け持つ（出力の段で移す）。
//!
//! Python と同じに読むための決まり:
//!   - 文字コードは Python の codecs と同じ字にする。cp932 は CPython の _codecs_jp.c と同じ順で読み、
//!     読めないバイトは1バイトずつ U+FFFD にする（2バイトの字の対応は encoding_rs の Shift_JIS の表。
//!     全部の組み合わせを tests/test_rust_text.py が Python と比べる）
//!   - 字で数える・区切りは、ファイルを字で開いたときと同じく \r・\n・\r\n で行を分ける。
//!     バイトで数えるときは、バイトで開いたときと同じく \n だけで分ける
//!   - Python と同じに読めると言えない物は Python へ回す: euc_jp・shift_jis・utf-16、正規表現の区切り、
//!     数や日付の欄の全角の数字（isdigit が真で int が落ちることがある）、float() が読むかもしれない字
use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{masters, pyish, routes::Core, writer};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

// ==== 文字コード ============================================================

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Enc {
    Cp932,
    Utf8,
    Utf8Sig,
    Latin1,
}

/// 読取マスタの文字コード（normalize 済み）。Python と同じに読めると言えない物は None。
pub fn enc_of(name: &str) -> Option<Enc> {
    match name {
        "cp932" => Some(Enc::Cp932),
        "utf-8" => Some(Enc::Utf8),
        "utf-8-sig" => Some(Enc::Utf8Sig),
        "latin-1" => Some(Enc::Latin1),
        _ => None,
    }
}

/// cp932 の2バイトの字（読めない組なら None）。
fn cp932_pair(c: u8, c2: u8) -> Option<char> {
    let pair = [c, c2];
    let (s, had) = encoding_rs::SHIFT_JIS.decode_without_bom_handling(&pair);
    let mut it = s.chars();
    match (had, it.next(), it.next()) {
        (false, Some(ch), None) => Some(ch),
        _ => None,
    }
}

/// bytes.decode(enc, errors='replace')。→ (字, 読めないバイトがあったか)。
pub fn decode(enc: Enc, b: &[u8]) -> (String, bool) {
    match enc {
        Enc::Latin1 => (b.iter().map(|&x| x as char).collect(), false),
        Enc::Utf8 => {
            let (s, had) = encoding_rs::UTF_8.decode_without_bom_handling(b);
            (s.into_owned(), had)
        }
        Enc::Utf8Sig => decode(Enc::Utf8, b.strip_prefix(b"\xef\xbb\xbf").unwrap_or(b)),
        Enc::Cp932 => {
            // CPython の cp932 の読み方（Modules/cjkcodecs/_codecs_jp.c）と同じ順
            let (mut out, mut bad, mut i) = (String::with_capacity(b.len()), false, 0);
            while i < b.len() {
                let c = b[i];
                if c <= 0x80 {
                    out.push(c as char);
                    i += 1;
                } else if (0xa0..=0xdf).contains(&c) {
                    out.push(if c == 0xa0 { '\u{f8f0}' } else { char::from_u32(0xfec0 + u32::from(c)).unwrap_or('\u{fffd}') });
                    i += 1;
                } else if c >= 0xfd {
                    out.push(char::from_u32(0xf8f1 - 0xfd + u32::from(c)).unwrap_or('\u{fffd}'));
                    i += 1;
                } else if let Some(ch) = b.get(i + 1).and_then(|&c2| cp932_pair(c, c2)) {
                    out.push(ch);
                    i += 2;
                } else {
                    // 読めない（または最後で切れた）先頭のバイトだけを置き換え、次のバイトから読み直す
                    out.push('\u{fffd}');
                    bad = true;
                    i += 1;
                }
            }
            (out, bad)
        }
    }
}

/// 字で開いたファイルの行（\r・\n・\r\n で分け、行の終わりの印は落とす）。
fn text_lines(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut it = s.chars().peekable();
    while let Some(c) = it.next() {
        match c {
            '\n' => out.push(std::mem::take(&mut cur)),
            '\r' => {
                if it.peek() == Some(&'\n') {
                    it.next();
                }
                out.push(std::mem::take(&mut cur));
            }
            c => cur.push(c),
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// バイトで開いたファイルの行（\n だけで分け、後ろの \r と \n を落とす）。
fn byte_lines(b: &[u8]) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    for chunk in b.split_inclusive(|&x| x == b'\n') {
        let mut end = chunk.len();
        while end > 0 && (chunk[end - 1] == b'\n' || chunk[end - 1] == b'\r') {
            end -= 1;
        }
        out.push(chunk[..end].to_vec());
    }
    out
}

// ==== 1行の値 ==============================================================

#[derive(Clone, Debug)]
enum Line {
    Text(String),
    Bytes(Vec<u8>),
}

const JUNK_TEXT: fn(char) -> bool = |c| (c < '\u{20}' && c != '\t') || c == '\u{7f}' || c == '\u{fffd}';

/// is_junk_line（読めない記号だけの行。空白・タブだけの行は空行なので数えない）。
fn is_junk(line: &Line) -> bool {
    match line {
        Line::Bytes(b) => {
            let body = trim_bytes(b, b" \t");
            !body.is_empty() && body.iter().all(|&c| (c < 0x20 && c != 0x09) || c == 0x7f)
        }
        Line::Text(s) => {
            let body = s.trim_matches(|c| c == ' ' || c == '\t' || c == '\u{3000}');
            !body.is_empty() && body.chars().all(JUNK_TEXT)
        }
    }
}

fn trim_bytes<'a>(b: &'a [u8], set: &[u8]) -> &'a [u8] {
    let s = b.iter().position(|c| !set.contains(c)).unwrap_or(b.len());
    let e = b.iter().rposition(|c| !set.contains(c)).map(|x| x + 1).unwrap_or(s);
    &b[s..e.max(s)]
}

/// 前後の空白の取り方（_trim）。
fn trim(v: &str, mode: &str) -> String {
    match mode {
        "both" => pyish::strip(v).to_string(),
        "right" => v.trim_end_matches(pyish::is_space).to_string(),
        "left" => v.trim_start_matches(pyish::is_space).to_string(),
        _ => v.to_string(),
    }
}

// ==== 区切り ================================================================

/// 1件を値の並びへ分ける（splitter。正規表現の区切りは Python の re で分けるので、呼ぶ側が Pass にする）。
struct Splitter {
    sep: Vec<char>,
    quote: Option<char>,
    collapse: bool,
}

impl Splitter {
    fn new(l: &Value) -> R<Splitter> {
        let delim = l["delimiter"].as_str().unwrap_or("comma");
        let sep: String = match delim {
            "regex" => return Err(Pass),
            "custom" => l["delimiter_text"].as_str().unwrap_or("").to_string(),
            "tab" => "\t".into(),
            "semicolon" => ";".into(),
            "pipe" => "|".into(),
            "space" => " ".into(),
            _ => ",".into(),
        };
        // 区切りの字が空のときは、Python の str.split('') が落ちる（呼ぶ側は確かめてから来るが、念のため）
        if sep.is_empty() {
            return Err(Pass);
        }
        let quote = match l["quote"].as_str().unwrap_or("double") {
            "single" => Some('\''),
            "none" => None,
            _ => Some('"'),
        };
        Ok(Splitter { sep: sep.chars().collect(), quote, collapse: l["collapse"] == json!(true) })
    }

    fn drop_empty(&self, xs: Vec<String>) -> Vec<String> {
        if !self.collapse {
            return xs;
        }
        let kept: Vec<String> = xs.into_iter().filter(|x| !x.is_empty()).collect();
        if kept.is_empty() {
            vec![String::new()]
        } else {
            kept
        }
    }

    /// → (値の並び, 囲みが閉じないまま終わったか)。
    fn scan(&self, s: &str) -> (Vec<String>, bool) {
        let c: Vec<char> = s.chars().collect();
        let n = self.sep.len();
        let starts = |i: usize| c.len() >= i + n && c[i..i + n] == self.sep[..];
        let Some(q) = self.quote else {
            // 囲みなし: str.split(sep)
            let (mut out, mut buf, mut i) = (Vec::new(), String::new(), 0);
            while i < c.len() {
                if starts(i) {
                    out.push(std::mem::take(&mut buf));
                    i += n;
                } else {
                    buf.push(c[i]);
                    i += 1;
                }
            }
            out.push(buf);
            return (self.drop_empty(out), false);
        };
        let (mut out, mut buf, mut i, mut start, mut opened) = (Vec::new(), String::new(), 0, true, false);
        loop {
            if i >= c.len() {
                out.push(buf);
                break;
            }
            if start && c[i] == q {
                // 囲まれた値。閉じの囲みまで読む。閉じの後ろから区切りまでの字は、そのまま値に足す
                i += 1;
                opened = true;
                while i < c.len() {
                    if c[i] == q {
                        if i + 1 < c.len() && c[i + 1] == q {
                            buf.push(q);
                            i += 2;
                            continue;
                        }
                        i += 1;
                        opened = false;
                        break;
                    }
                    buf.push(c[i]);
                    i += 1;
                }
                start = false;
                continue;
            }
            if starts(i) {
                out.push(std::mem::take(&mut buf));
                i += n;
                start = true;
                continue;
            }
            buf.push(c[i]);
            i += 1;
            start = false;
        }
        (self.drop_empty(out), opened)
    }

    fn split(&self, s: &str) -> Vec<String> {
        self.scan(s).0
    }
}

const MAX_RECORD_LINES: usize = 1000;

/// 区切りの1件ずつ（_read_records。囲みの中の改行は値の一部なので、閉じるまで次の行を足して1件にする）。→ (件, 使った行の数)。
fn records(lines: Vec<String>, sp: &Splitter) -> Vec<(String, usize)> {
    let mut out = Vec::new();
    let mut hold: Vec<String> = Vec::new();
    for line in lines {
        if !hold.is_empty() {
            hold.push(line);
            let rec = hold.join("\n");
            if sp.scan(&rec).1 && hold.len() < MAX_RECORD_LINES {
                continue;
            }
            out.push((rec, hold.len()));
            hold.clear();
            continue;
        }
        if sp.scan(&line).1 {
            hold = vec![line];
            continue;
        }
        out.push((line, 1));
    }
    if !hold.is_empty() {
        out.push((hold.join("\n"), hold.len()));
    }
    out
}

// ==== 型 ====================================================================

/// _to_number（数として読む。読めなければ None、空なら ""）。Python と同じに読めると言えない字は Pass。
fn to_number(text: &str, scale: usize, integer_only: bool) -> R<Option<String>> {
    let s: String = pyish::strip(text).replace([',', '\u{3000}'], "");
    if s.is_empty() {
        return Ok(Some(String::new()));
    }
    if !s.is_ascii() {
        // 全角の数字・上付きの数字・全角の空白などは、isdigit・int・float が読むかどうかが字で違う → Python へ回す。
        // それ以外の字（漢字など）が混じれば、isdigit も float も読めない
        if s.chars().any(|c| !c.is_ascii() && (c.is_numeric() || pyish::is_space(c))) {
            return Err(Pass);
        }
        return Ok(None);
    }
    let mut s = s;
    let mut sign = "";
    if s.ends_with('+') || s.ends_with('-') {
        sign = if s.ends_with('-') { "-" } else { "" };
        s.pop();
        s = pyish::strip(&s).to_string();
    }
    if s.starts_with('+') || s.starts_with('-') {
        sign = if s.starts_with('-') { "-" } else { sign };
        s.remove(0);
    }
    if s.is_empty() {
        return Ok(None);
    }
    let digits = |x: &str| !x.is_empty() && x.bytes().all(|b| b.is_ascii_digit());
    // str(int(x))（前の 0 を落とす）
    let int_text = |x: &str| {
        let t = x.trim_start_matches('0');
        if t.is_empty() {
            "0".to_string()
        } else {
            t.to_string()
        }
    };
    if integer_only {
        return Ok(digits(&s).then(|| format!("{sign}{}", int_text(&s))));
    }
    if digits(&s) {
        if scale > 0 {
            let w = s.len().max(scale + 1);
            let p = format!("{s:0>w$}");
            let (a, b) = p.split_at(p.len() - scale);
            return Ok(Some(format!("{sign}{}.{b}", int_text(a))));
        }
        return Ok(Some(format!("{sign}{}", int_text(&s))));
    }
    if let Some((head, tail)) = s.split_once('.') {
        if (head.is_empty() || digits(head)) && (tail.is_empty() || digits(tail)) {
            let h = if head.is_empty() { "0".to_string() } else { int_text(head) };
            return Ok(Some(format!("{sign}{h}.{}", if tail.is_empty() { "0" } else { tail })));
        }
    }
    // float(s) が読むかもしれない字（指数・inf・nan・桁の _・空白）だけでできていれば、Python へ回す
    if s.chars().all(|c| c.is_ascii_digit() || ".eE+-_ \t\n\r\x0b\x0cinfINFtyTYaA".contains(c)) {
        return Err(Pass);
    }
    Ok(None)
}

/// _parse_stamp（書式どおりに読めたら (年,月,日,時,分,秒)）。
fn parse_stamp(value: &str, pattern: &str, want_time: bool) -> R<Option<[u32; 6]>> {
    let s: Vec<char> = pyish::strip(value).chars().collect();
    if s.is_empty() {
        return Ok(None);
    }
    let (mut got, mut pos): (Vec<(char, u32)>, usize) = (Vec::new(), 0);
    for (role, n) in masters::stamp_plan(pattern) {
        let Some(role) = role else {
            pos += 1;
            continue;
        };
        let chunk: Vec<char> = s.iter().skip(pos).take(n).copied().collect();
        pos += n;
        if chunk.iter().any(|c| !c.is_ascii() && c.is_numeric()) {
            return Err(Pass); // 全角の数字（isdigit と int が字で違う）
        }
        if chunk.len() != n || !chunk.iter().all(char::is_ascii_digit) {
            return Ok(None);
        }
        let v: u32 = chunk.iter().collect::<String>().parse().map_err(|_| Pass)?;
        match got.iter_mut().find(|(r, _)| *r == role) {
            Some(x) => x.1 = v, // 同じ役割が2度あれば後の値（辞書へ入れ直すのと同じ）
            None => got.push((role, v)),
        }
    }
    if pos < s.len() {
        return Ok(None);
    }
    let get = |r: char| got.iter().find(|(x, _)| *x == r).map(|(_, v)| *v);
    let y = get('Y').or_else(|| get('y').map(|y| if y <= 69 { 2000 + y } else { 1900 + y }));
    let Some(y) = y else { return Ok(None) };
    let (mo, d, h, mi, se) =
        (get('M').unwrap_or(1), get('D').unwrap_or(1), get('h').unwrap_or(0), get('m').unwrap_or(0), get('s').unwrap_or(0));
    let ok = (1..=9999).contains(&y) && chrono::NaiveDate::from_ymd_opt(y as i32, mo, d).is_some() && h < 24 && mi < 60 && se < 60;
    if !ok {
        return Ok(None);
    }
    Ok(Some(if want_time { [y, mo, d, h, mi, se] } else { [y, mo, d, 0, 0, 0] }))
}

/// 列1本ぶんの型のあてはめ（_converter）。→ Some(新しい値) / None（型に読めない）。
fn convert(col: &Value, v: &str) -> R<Option<String>> {
    let t = col["type"].as_str().unwrap_or("text");
    match t {
        "text" => Ok(Some(v.to_string())),
        "integer" => to_number(v, 0, true),
        "numeric" => to_number(v, 0, false),
        "real" => to_number(v, col["scale"].as_u64().unwrap_or(0) as usize, false),
        _ => {
            let want_time = t == "datetime";
            if pyish::strip(v).is_empty() {
                return Ok(Some(String::new()));
            }
            let fmt = col["format"].as_str().filter(|f| !f.is_empty()).unwrap_or(if want_time { "YYYYMMDDHHMMSS" } else { "YYYYMMDD" });
            Ok(parse_stamp(v, fmt, want_time)?.map(|[y, mo, d, h, mi, se]| {
                if want_time {
                    format!("{y:04}-{mo:02}-{d:02} {h:02}:{mi:02}:{se:02}")
                } else {
                    format!("{y:04}-{mo:02}-{d:02}")
                }
            }))
        }
    }
}

// ==== 表にする ==============================================================

/// read_text_rows の答え。
struct Read {
    headers: Vec<Value>,
    body: Vec<Vec<String>>,
    raws: Vec<String>,
    stat: Map<String, Value>,
}

fn columns(l: &Value) -> &[Value] {
    l["columns"].as_array().map(Vec::as_slice).unwrap_or(&[])
}

fn int(l: &Value, k: &str) -> i64 {
    l[k].as_i64().unwrap_or(0)
}

/// read_text_rows（limit 件まで。keep_raw は常に付ける）。l は整えた読取マスタ。
fn read_rows(bytes: &[u8], l: &Value, limit: usize) -> R<Read> {
    let enc = enc_of(l["encoding"].as_str().unwrap_or("")).ok_or(Pass)?;
    let cols = columns(l);
    let mode = l["mode"].as_str().unwrap_or("fixed");
    let unit = l["unit"].as_str().unwrap_or("byte");
    let trim_mode = l["trim"].as_str().unwrap_or("both");
    let delimited = mode == "delimited";
    let width = masters::layout_width(l);
    let headers: Vec<Value> = cols.iter().map(|c| c["name"].clone()).collect();
    let typed = cols.iter().any(|c| c["type"].as_str().unwrap_or("text") != "text");
    let mut types = Map::new();
    for c in cols {
        types.insert(c["name"].as_str().unwrap_or("").to_string(), c["type"].clone());
    }
    let (mut lines_n, mut rows, mut sk_blank, mut sk_head, mut sk_junk, mut short, mut broken, mut fields_max, mut type_errors) =
        (0usize, 0usize, 0usize, 0usize, 0usize, 0usize, 0usize, 0usize, 0usize);
    let mut samples = Map::new();
    let sp = if delimited { Some(Splitter::new(l)?) } else { None };
    // 行（区切りは件）を作る
    let source: Vec<(Line, usize)> = if delimited {
        let (s, _) = decode(enc, bytes);
        records(text_lines(&s), sp.as_ref().ok_or(Pass)?).into_iter().map(|(r, n)| (Line::Text(r), n)).collect()
    } else if unit == "byte" {
        byte_lines(bytes).into_iter().map(|b| (Line::Bytes(b), 1)).collect()
    } else {
        let (s, _) = decode(enc, bytes);
        text_lines(&s).into_iter().map(|t| (Line::Text(t), 1)).collect()
    };
    let skip_head = int(l, "skip_head").max(0) as usize;
    let tail = int(l, "skip_tail").max(0) as usize;
    let header_row = l["header_row"] == json!(true);
    let skip_blank = l["skip_blank"] == json!(true);
    let mut header_seen = false;
    let mut hold: std::collections::VecDeque<Line> = std::collections::VecDeque::new();
    let (mut body, mut raws) = (Vec::new(), Vec::new());
    for (line, used) in source {
        lines_n += used;
        if lines_n <= skip_head {
            sk_head += 1;
            continue;
        }
        if is_junk(&line) {
            sk_junk += 1;
            continue;
        }
        // 最後の行の後ろに付いた終わりの印（0x1A）は、印だけを外して行は残す
        let line = match line {
            Line::Text(s) => Line::Text(s.trim_end_matches('\u{1a}').to_string()),
            Line::Bytes(b) => Line::Bytes(b[..b.iter().rposition(|&c| c != 0x1a).map(|x| x + 1).unwrap_or(0)].to_vec()),
        };
        if skip_blank {
            let blank = match &line {
                Line::Text(s) => pyish::strip(s).is_empty(),
                Line::Bytes(b) => trim_bytes(b, b" \t\n\r\x0b\x0c").is_empty(),
            };
            if blank {
                sk_blank += 1;
                continue;
            }
        }
        if header_row && !header_seen {
            header_seen = true;
            sk_head += 1;
            continue;
        }
        hold.push_back(line);
        if hold.len() <= tail {
            continue;
        }
        let Some(use_) = hold.pop_front() else { continue };
        let mut out: Vec<String> = match &use_ {
            Line::Text(s) if delimited => {
                let vals = sp.as_ref().ok_or(Pass)?.split(s);
                fields_max = fields_max.max(vals.len());
                if (vals.len() as i64) < width {
                    short += 1;
                }
                cols.iter()
                    .map(|c| {
                        let k = int(c, "field") - 1;
                        if k >= 0 && (k as usize) < vals.len() {
                            trim(&vals[k as usize], trim_mode)
                        } else {
                            String::new()
                        }
                    })
                    .collect()
            }
            Line::Bytes(b) => {
                if (b.len() as i64) < width {
                    short += 1;
                }
                cols.iter()
                    .map(|c| {
                        let (st, en) = ((int(c, "start") - 1).max(0) as usize, int(c, "end").max(0) as usize);
                        let chunk = if st < b.len() { &b[st..en.min(b.len()).max(st)] } else { &[][..] };
                        let (s, bad) = decode(enc, chunk);
                        if bad {
                            broken += 1;
                        }
                        trim(&s, trim_mode)
                    })
                    .collect()
            }
            Line::Text(s) => {
                let ch: Vec<char> = s.chars().collect();
                if (ch.len() as i64) < width {
                    short += 1;
                }
                cols.iter()
                    .map(|c| {
                        let (st, en) = ((int(c, "start") - 1).max(0) as usize, int(c, "end").max(0) as usize);
                        let part: String = if st < ch.len() { ch[st..en.min(ch.len()).max(st)].iter().collect() } else { String::new() };
                        trim(&part, trim_mode)
                    })
                    .collect()
            }
        };
        if typed {
            for (i, c) in cols.iter().enumerate() {
                if c["type"].as_str().unwrap_or("text") == "text" {
                    continue;
                }
                match convert(c, &out[i])? {
                    Some(v) => out[i] = v,
                    None => {
                        type_errors += 1;
                        let name = c["name"].as_str().unwrap_or("").to_string();
                        samples.entry(name).or_insert_with(|| json!(out[i]));
                        out[i] = String::new();
                    }
                }
            }
        }
        body.push(out);
        raws.push(match use_ {
            Line::Text(s) => s,
            Line::Bytes(b) => decode(enc, &b).0,
        });
        rows += 1;
        if rows >= limit {
            break;
        }
    }
    let stat = json!({
        "lines": lines_n, "rows": rows, "skipped_blank": sk_blank, "skipped_head": sk_head, "skipped_tail": 0,
        "skipped_junk": sk_junk, "short_rows": short, "broken_cells": broken, "width": width, "unit": unit,
        "encoding": l["encoding"], "mode": mode, "fields_max": fields_max, "types": types,
        "type_errors": type_errors, "type_samples": samples,
    });
    let Value::Object(stat) = stat else { return Err(Pass) };
    Ok(Read { headers, body, raws, stat })
}

// ==== 受け口 ================================================================

/// request.get_json(force=True) or {}（辞書でない真の値は Python が落ちる）。
fn body(ask: &Ask) -> R<Map<String, Value>> {
    match writer::body_json(ask, true)? {
        Some(Value::Object(m)) => Ok(m),
        Some(v) if pyish::truthy(&v) => Err(Pass),
        _ => Ok(Map::new()),
    }
}

/// 画面から来た読取マスタ（normalize_text_layout(d.get('layout') or {})）と、読むファイル（resolve_text_path）。
fn layout_and_path(core: &Core, d: &Map<String, Value>) -> R<(Value, String, Map<String, Value>)> {
    let raw = match d.get("layout") {
        Some(Value::Object(m)) => m.clone(),
        Some(v) if pyish::truthy(v) => return Err(Pass),
        _ => Map::new(),
    };
    let l = config::normalize_layout(&raw)?;
    let path = pyish::strip(&match d.get("path").filter(|v| pyish::truthy(v)) {
        Some(v) => pyish::py_str(v),
        None => pyish::text_or_empty(l.get("sample_path")),
    })
    .to_string();
    let c = config::read(core)?;
    Ok((l, path, c))
}

fn resolve_text(core: &Core, c: &Map<String, Value>, raw: &str) -> R<String> {
    let folder = crate::naming::text_or(c.get("text_folder"), config::TEXT_FOLDER_DEFAULT);
    Ok(core.bases().ok_or(Pass)?.resolve_in(raw, Some(&folder)))
}

/// ファイルの中身（無ければ None）。読めない（権限など）ときは Python の例外の字を作れないので Pass。
fn file_bytes(path: &str) -> R<Option<Vec<u8>>> {
    match std::fs::metadata(path) {
        // 大きなファイルは Python へ回す（Python は必要な行まで読んで止まる。こちらは丸ごと読むため）
        Ok(m) if m.is_file() && m.len() > 64 << 20 => Err(Pass),
        Ok(m) if m.is_file() => std::fs::read(path).map(Some).map_err(|_| Pass),
        _ => Ok(None),
    }
}

/// POST /api/text-preview … 下読み（生の行と、切り出した結果を並べる）。
pub(crate) fn post_preview(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_preview(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_preview(core: &Core, ask: &Ask) -> R<Reply> {
    let d = body(ask)?;
    let (l, raw, c) = layout_and_path(core, &d)?;
    if raw.is_empty() {
        return Ok(Reply::json(400, &json!({"ok": false, "error": "下読みするファイルを選んでください"})));
    }
    let lines = match d.get("lines").filter(|v| pyish::truthy(v)) {
        None => 12,
        Some(v) => pyish::int_opt(v).ok().flatten().ok_or(Pass)?,
    };
    let path = resolve_text(core, &c, &raw)?;
    let mut out = preview_text(&l, &path, lines)?;
    out["width"] = json!(masters::layout_width(&l));
    Ok(Reply::json(if out["ok"] == json!(true) { 200 } else { 400 }, &out))
}

/// navi_text.preview_text（下読み。生の行と、切り出した結果を並べる。読めなければ ok: false と error）。l は整えた読取マスタ。
pub(crate) fn preview_text(l: &Value, path: &str, lines: i64) -> R<Value> {
    let mut out = json!({"ok": false, "path": path, "headers": [], "rows": [], "raw": [], "stat": {},
                         "overlaps": masters::layout_overlaps(l), "gaps": masters::layout_gaps(l), "notes": []});
    let fail = |mut out: Value, msg: String| {
        out["error"] = json!(msg);
        Ok(out)
    };
    // 名前は保存のための決まりで、切り方とは関係が無い（作りかけでも下読みできる）
    let mut named = l.clone();
    if named["name"].as_str().unwrap_or("").is_empty() {
        named["name"] = json!("下読み");
    }
    let bad = masters::validate_layout(&named)?;
    if !bad.is_empty() {
        return fail(out, bad.join("／"));
    }
    let Some(bytes) = file_bytes(path)? else { return fail(out, format!("ファイルがありません: {path}")) };
    let limit = lines.clamp(1, 100) as usize;
    let r = read_rows(&bytes, l, limit)?;
    let width = masters::layout_width(l);
    let mode = r.stat["mode"].as_str().unwrap_or("").to_string();
    let n = |k: &str| r.stat[k].as_u64().unwrap_or(0);
    let mut notes: Vec<String> = Vec::new();
    if n("skipped_junk") > 0 {
        notes.push(format!("読めない記号だけの行（ファイルの終わりの印など）{}行は、データにせず外しました", n("skipped_junk")));
    }
    if n("short_rows") > 0 {
        if mode == "delimited" {
            notes.push(format!(
                "{}行は項目が{}個に足りず、足りない列は空になりました（区切りか囲み文字が合っていない可能性があります）",
                n("short_rows"),
                width
            ));
        } else {
            notes.push(format!(
                "{}行が取り決めより短く、足りない列は空になりました（この取り決めは{}{}必要です）",
                n("short_rows"),
                width,
                if r.stat["unit"] == json!("byte") { "バイト" } else { "文字" }
            ));
        }
    }
    if n("broken_cells") > 0 {
        notes.push(format!(
            "{}か所で、切れ目が文字の途中に来ました。位置の数え方（文字／バイト）か、開始位置が合っていない可能性があります",
            n("broken_cells")
        ));
    }
    if n("type_errors") > 0 {
        let ex: Vec<String> = r.stat["type_samples"]
            .as_object()
            .map(|m| m.iter().take(3).map(|(k, v)| format!("{k}「{}」", v.as_str().unwrap_or(""))).collect())
            .unwrap_or_default();
        notes.push(format!(
            "{}か所が、決めた型に読めませんでした（空にしています）: {}。型や書式・小数桁、または開始位置を確かめてください",
            n("type_errors"),
            ex.join("、")
        ));
    }
    let overlaps = masters::layout_overlaps(l);
    if !overlaps.is_empty() {
        let ps: Vec<String> =
            overlaps.iter().take(3).map(|p| format!("{}↔{}", p[0].as_str().unwrap_or(""), p[1].as_str().unwrap_or(""))).collect();
        notes.push(format!("重なっている列があります: {}", ps.join("、")));
    }
    out["ok"] = json!(true);
    out["headers"] = Value::Array(r.headers);
    out["rows"] = json!(r.body);
    out["raw"] = json!(r.raws);
    out["stat"] = Value::Object(r.stat);
    out["size"] = json!(bytes.len());
    out["types"] = Value::Array(columns(l).iter().map(|c| c["type"].clone()).collect());
    if mode == "delimited" {
        if let Some(first) = out["raw"].as_array().and_then(|a| a.first()).and_then(Value::as_str) {
            out["fields"] = json!(Splitter::new(l)?.split(first));
        }
    }
    out["notes"] = json!(notes);
    Ok(out)
}

const SNIFF_DELIMITERS: [&str; 4] = ["tab", "comma", "semicolon", "pipe"];
const SNIFF_LINES: usize = 30;

/// POST /api/text-sniff … 区切りの見当付け（見本のファイルから、区切りと列を出す）。
pub(crate) fn post_sniff(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_sniff(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_sniff(core: &Core, ask: &Ask) -> R<Reply> {
    let d = body(ask)?;
    let (l0, raw, c) = layout_and_path(core, &d)?;
    if raw.is_empty() {
        return Ok(Reply::json(400, &json!({"ok": false, "error": "見本のファイルを選んでください"})));
    }
    let path = resolve_text(core, &c, &raw)?;
    // normalize_layout(dict(layout, mode='delimited'))
    let mut m = l0.as_object().cloned().ok_or(Pass)?;
    m.insert("mode".into(), json!("delimited"));
    let l = config::normalize_layout(&m)?;
    let enc = enc_of(l["encoding"].as_str().unwrap_or("")).ok_or(Pass)?;
    let Some(bytes) = file_bytes(&path)? else {
        return Ok(Reply::json(400, &json!({"ok": false, "error": format!("ファイルがありません: {path}")})));
    };
    let skip_head = int(&l, "skip_head").max(0) as usize;
    let given = matches!(l["delimiter"].as_str(), Some("custom" | "regex")) && !l["delimiter_text"].as_str().unwrap_or("").is_empty();
    // 読むのは、利用者が決めた区切り（無ければ整えた既定）で1件ずつ
    let sp0 = Splitter::new(&l)?;
    let (s, _) = decode(enc, &bytes);
    let mut recs: Vec<String> = records(text_lines(&s), &sp0).into_iter().take(SNIFF_LINES + skip_head).map(|(r, _)| r).collect();
    recs = recs.into_iter().skip(skip_head).filter(|r| !pyish::strip(r).is_empty()).collect();
    if recs.is_empty() {
        return Ok(Reply::json(
            400,
            &json!({"ok": false, "error": "中身のある行が見つかりませんでした（文字コードと、先頭を読み飛ばす行数を確かめてください）"}),
        ));
    }
    let chosen: Value = if given {
        l.clone()
    } else {
        let mut best: Option<((usize, usize), Value)> = None;
        for dlm in SNIFF_DELIMITERS {
            let mut cand = l.clone();
            cand["delimiter"] = json!(dlm);
            cand["collapse"] = json!(false);
            let sp = Splitter::new(&cand)?;
            let counts: Vec<usize> = recs.iter().map(|r| sp.split(r).len()).collect();
            // max(set(counts), key=counts.count): いちばん多い数（同じ回数の数が2つ以上あると、選ぶ数が set の並びで決まる → Python へ回す）
            let mut freq: Vec<(usize, usize)> = Vec::new();
            for &x in &counts {
                match freq.iter_mut().find(|(v, _)| *v == x) {
                    Some(f) => f.1 += 1,
                    None => freq.push((x, 1)),
                }
            }
            let most = freq.iter().map(|f| f.1).max().unwrap_or(0);
            let tops: Vec<usize> = freq.iter().filter(|f| f.1 == most).map(|f| f.0).collect();
            if tops.len() > 1 {
                return Err(Pass);
            }
            let top = tops[0];
            if top < 2 {
                continue;
            }
            let score = (most, top); // 割合は件数が同じなので回数で比べる
            if best.as_ref().is_none_or(|(b, _)| score > *b) {
                best = Some((score, cand));
            }
        }
        match best {
            Some(((most, _), cand)) if most * 10 >= recs.len() * 8 => cand,
            _ => {
                let mut cand = l.clone();
                cand["delimiter"] = json!("space");
                cand["collapse"] = json!(true);
                cand["quote"] = json!("none");
                cand
            }
        }
    };
    let sp = Splitter::new(&chosen)?;
    let first = sp.split(&recs[0]);
    let second = if recs.len() > 1 { sp.split(&recs[1]) } else { vec![] };
    let head = l["header_row"] == json!(true);
    let mut names: Vec<String> = first
        .iter()
        .enumerate()
        .map(|(i, x)| {
            let t = pyish::strip(x);
            if head && !t.is_empty() {
                t.to_string()
            } else {
                format!("列{}", i + 1)
            }
        })
        .collect();
    let sample = if head { &second } else { &first };
    let mut seen: Vec<(String, usize)> = Vec::new();
    for n in names.iter_mut() {
        let k = match seen.iter_mut().find(|(x, _)| x == n) {
            Some(e) => {
                e.1 += 1;
                e.1
            }
            None => {
                seen.push((n.clone(), 1));
                1
            }
        };
        if k > 1 {
            *n = format!("{n}_{k}");
        }
    }
    let mut cols: Vec<Value> = names
        .iter()
        .enumerate()
        .map(|(i, n)| json!({"name": n, "field": i + 1, "sample": pyish::head(sample.get(i).map(String::as_str).unwrap_or(""), 60)}))
        .collect();
    cols.truncate(4096);
    core.log(&format!(
        "TEXT_SNIFF path={path} delimiter={} collapse={} 列={} 見た件={} 見出し={}",
        chosen["delimiter"].as_str().unwrap_or(""),
        if chosen["collapse"] == json!(true) { "True" } else { "False" },
        cols.len(),
        recs.len(),
        if head { "True" } else { "False" }
    ));
    Ok(Reply::json(
        200,
        &json!({"ok": true, "delimiter": chosen["delimiter"], "delimiter_text": chosen["delimiter_text"], "collapse": chosen["collapse"],
                "quote": chosen["quote"], "columns": cols, "records": recs.len(), "label": masters::delimiter_label(&chosen)}),
    ))
}

/// 見出しと本体（行は字の並び）。
pub(crate) type Table = (Vec<String>, Vec<Vec<String>>);

/// navi_text.read_text_rows の見出しと本体（結合の材料に使う）。Err(Ok(文)) は Python の ValueError の文、Err(Err(Pass)) は Python へ回す。
pub(crate) fn text_rows(path: &str, l: &Value, limit: usize) -> Result<Table, R<String>> {
    if columns(l).is_empty() {
        return Err(Ok("読取マスタに列がありません".into()));
    }
    let Some(bytes) = file_bytes(path).map_err(Err)? else { return Err(Err(Pass)) };
    let r = read_rows(&bytes, l, limit).map_err(Err)?;
    Ok((r.headers.iter().map(pyish::py_str).collect(), r.body))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cp932_like_cpython() {
        assert_eq!(decode(Enc::Cp932, b"\x82\xa0A\x80\xa0\xb1\xfd").0, "あA\u{80}\u{f8f0}ｱ\u{f8f1}");
        // 読めない先頭のバイトは1バイトだけ置き換え、次のバイトから読み直す
        assert_eq!(decode(Enc::Cp932, b"\x81\x20x"), ("\u{fffd} x".to_string(), true));
        assert_eq!(decode(Enc::Cp932, b"a\x82"), ("a\u{fffd}".to_string(), true));
    }

    #[test]
    fn lines_like_python_files() {
        assert_eq!(text_lines("a\r\nb\rc\n\nd"), vec!["a", "b", "c", "", "d"]);
        assert_eq!(text_lines("a\n"), vec!["a"]);
        assert_eq!(byte_lines(b"a\r\rb\rc\r\n\n"), vec![b"a\r\rb\rc".to_vec(), b"".to_vec()]);
    }

    #[test]
    fn numbers_like_python() {
        let n = |s: &str, sc: usize, i: bool| to_number(s, sc, i).ok().flatten();
        assert_eq!(n(" 0012345 ", 2, false).as_deref(), Some("123.45"));
        assert_eq!(n("123-", 0, true).as_deref(), Some("-123"));
        assert_eq!(n("1,234", 0, true).as_deref(), Some("1234"));
        assert_eq!(n("0012.50", 0, false).as_deref(), Some("12.50"));
        assert_eq!(n(".5", 0, false).as_deref(), Some("0.5"));
        assert_eq!(n("5", 3, false).as_deref(), Some("0.005"));
        assert_eq!(n("abc", 0, false), None);
        assert!(to_number("1e5", 0, false).is_err());
        assert!(to_number("１２", 0, true).is_err());
        assert_eq!(n("", 0, true).as_deref(), Some(""));
    }

    #[test]
    fn quoted_split() {
        let sp = Splitter { sep: vec![','], quote: Some('"'), collapse: false };
        assert_eq!(sp.split(r#"a,"b,""c""",x"y",d"#), vec!["a", "b,\"c\"", "x\"y\"", "d"]);
        assert!(sp.scan("a,\"open").1);
    }
}
