//! 設定の読み出し（GET /api/config。2.19.0〜）。app.load と navi_web.get_config と同じ答えを返す。
//!
//! 読むのは設定の手元の写し（<このPC>\cache\app_settings.sqlite3）。読み方の決まり（各欄の整え方・既定値・使わなくなった設定の
//! 落とし方・控えの置き場の読み替え・対象ごとの出力名の試算）を Python と同じにする。
//!
//! Python は読む前に init_settings_db を通す（起動して最初の1回だけ、共有のマスターを手元へ取り込み、表の形を整える）。Rust は
//! 写しへ書かない。だから「いま Python が読んでも、写しをそのまま読む」と言えるときだけ答え、そうでないとき（マスターのほうが新しい・
//! 写しが別のマスターの物・表の形が古い・設定の移行がまだ・マスターがまだ無い）は Python へ回す（`Pass`）。
//! 値が Python でしか同じに読めない形（壊れた JSON・字でない鍵・とても大きな数・バイナリ）のときも Python へ回す。
//!
//! 手元の写しの壊れの検査（PRAGMA quick_check）は、起動時に Python が行う。Rust は読めなければ Python へ回す。

use crate::http::Reply;
use crate::naming::{self, Tokens};
use crate::paths;
use crate::pyish;
use crate::routes::Core;
use crate::settings;
use chrono::NaiveDateTime;
use rusqlite::types::ValueRef;
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Rust では Python と同じに答えられると言えない。Python へ回す。
#[derive(Debug, PartialEq)]
pub struct Pass;

type R<T> = Result<T, Pass>;

/// JSON を Python の json.loads として読んだ結果。
pub enum Json {
    Ok(Value),
    /// Python も読めない（JSONDecodeError）
    Bad,
    /// Python と同じ値になるか分からない（NaN・Infinity・とても大きな数・サロゲート）
    Unsure,
}

/// json.loads と同じに読めたか。Python だけが読める書き方（NaN・Infinity・ひとりのサロゲート）と、
/// 64 ビットに収まらない数（19 桁以上の数字の並び）は Unsure。
pub fn py_json(text: &str) -> Json {
    let long_digits = text.as_bytes().split(|b| !b.is_ascii_digit()).any(|run| run.len() >= 19);
    match serde_json::from_str::<Value>(text) {
        Ok(_) if long_digits => Json::Unsure,
        Ok(v) => Json::Ok(v),
        Err(e) => {
            let msg = e.to_string();
            if long_digits || text.contains("NaN") || text.contains("Infinity") || msg.contains("out of range") || msg.contains("surrogate")
            {
                Json::Unsure
            } else {
                Json::Bad
            }
        }
    }
}

/// `json.loads(text)`。読めなければ Python は落ちる（500）→ Pass。字でない値も Python は落ちる。
fn loads_strict(v: &Value) -> R<Value> {
    match v {
        Value::String(s) => match py_json(s) {
            Json::Ok(v) => Ok(v),
            _ => Err(Pass),
        },
        _ => Err(Pass),
    }
}

/// `try: json.loads(text or default) except: fallback`（読めない・字でない値は fallback。Python と同じか分からない字は Pass）。
fn loads_or(v: Option<&Value>, default: &str, fallback: Value) -> R<Value> {
    let text = match v {
        Some(x) if pyish::truthy(x) => match x {
            Value::String(s) => s.as_str(),
            _ => return Ok(fallback), // json.loads(5) は TypeError（except で受ける）
        },
        _ => default,
    };
    match py_json(text) {
        Json::Ok(v) => Ok(v),
        Json::Bad => Ok(fallback),
        Json::Unsure => Err(Pass),
    }
}

// ==== 小さな読み方 ==========================================================

/// `str(v or '').strip()`。
fn txt(v: Option<&Value>) -> String {
    pyish::strip(&pyish::text_or_empty(v)).to_string()
}

/// `str(v if v is not None else '').strip()[:limit]`（navi_viewer・navi_post の _text）。
fn ptext(v: Option<&Value>, limit: usize) -> String {
    match v {
        None | Some(Value::Null) => String::new(),
        Some(v) => pyish::head(pyish::strip(&pyish::py_str(v)), limit),
    }
}

fn truthy(v: Option<&Value>) -> bool {
    v.is_some_and(pyish::truthy)
}

/// `(v or [])[:n]`（並びは先頭 n 個、字は先頭 n 字を1字ずつ。辞書・数は切り出せない＝Python の TypeError）。
fn slice_items(v: Option<&Value>, n: usize) -> R<Vec<Value>> {
    match v {
        Some(x) if pyish::truthy(x) => match x {
            Value::Array(a) => Ok(a.iter().take(n).cloned().collect()),
            Value::String(s) => Ok(s.chars().take(n).map(|c| Value::String(c.to_string())).collect()),
            _ => Err(Pass),
        },
        _ => Ok(vec![]),
    }
}

/// `v if isinstance(v, list) else []`。
fn list_or_empty(v: Option<&Value>) -> &[Value] {
    v.and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

/// `dict(v or {})`。
fn dict_of(v: Option<&Value>) -> R<Map<String, Value>> {
    match v {
        Some(x) if pyish::truthy(x) => crate::secret::py_dict(x).map_err(|_| Pass),
        _ => Ok(Map::new()),
    }
}

/// `v in ALLOWED`（字で等しい物）なら v。
fn pick<'a>(v: Option<&Value>, allowed: &[&'a str]) -> Option<&'a str> {
    v.and_then(Value::as_str).and_then(|s| allowed.iter().find(|a| **a == s).copied())
}

/// `int(str(v).strip())`、読めなければ default（navi_text の _int）。大きすぎる数は Pass。
fn int_text_or(v: Option<&Value>, default: i64) -> R<i64> {
    let s = pyish::py_str(v.unwrap_or(&Value::Null));
    match pyish::int_text(&s) {
        Ok(Some(i)) => Ok(i),
        Ok(None) => Ok(default),
        Err(_) => Err(Pass),
    }
}

// ==== 欄ごとの整え方 ========================================================

/// navi_groups.normalize_group（段ごとに、続く空白を1つにして前後を落とし、40 字まで。空の段は落とし、5 段まで）。
pub fn normalize_group(v: Option<&Value>) -> String {
    let Some(Value::String(name)) = v else { return String::new() };
    let parts: Vec<String> = name
        .split('/')
        .map(|p| {
            let mut s = String::new();
            let mut sp = false;
            for c in p.chars() {
                if pyish::is_space(c) {
                    if !sp {
                        s.push(' ');
                    }
                    sp = true;
                } else {
                    s.push(c);
                    sp = false;
                }
            }
            pyish::head(pyish::strip(&s), 40)
        })
        .filter(|p| !p.is_empty())
        .take(5)
        .collect();
    parts.join("/")
}

/// navi_variants.normalize（条件の値ごとに分けて出す）。
pub fn normalize_variants(v: &Value) -> R<Value> {
    let empty = Map::new();
    let m = v.as_object().unwrap_or(&empty);
    let mut values: Vec<String> = Vec::new();
    for x in pyish::py_iter(m.get("values")).ok_or(Pass)? {
        let s = if x.is_null() { String::new() } else { pyish::strip(&pyish::py_str(&x)).to_string() };
        if !s.is_empty() && !values.contains(&s) {
            values.push(s);
        }
    }
    values.truncate(50);
    let scope = pyish::text_or_empty(m.get("scope"));
    let method = pyish::text_or_empty(m.get("method"));
    Ok(json!({
        "enabled": truthy(m.get("enabled")),
        "item": txt(m.get("item")),
        "scope": if ["listed", "all"].contains(&scope.as_str()) { scope } else { "listed".into() },
        "values": values,
        "pattern": txt(m.get("pattern")),
        "folder": txt(m.get("folder")),
        "method": if ["combined", "parallel"].contains(&method.as_str()) { method } else { "default".into() },
    }))
}

const VIEWER_OPS: [&str; 12] = ["contains", "not_contains", "eq", "neq", "starts", "ends", "gt", "gte", "lt", "lte", "empty", "not_empty"];

/// navi_viewer.normalize（データビュワーの表示の設定）。
pub fn normalize_viewer(v: &Value) -> R<Value> {
    let empty = Map::new();
    let m = v.as_object().unwrap_or(&empty);
    let mut cols = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    for c in slice_items(m.get("cols"), 500)? {
        let Some(c) = c.as_object() else { continue };
        let key = ptext(c.get("key"), 200);
        if key.is_empty() || seen.contains(&key) {
            continue;
        }
        seen.push(key.clone());
        let mut one = json!({"key": key, "show": c.get("show") != Some(&Value::Bool(false))});
        let label = ptext(c.get("label"), 100);
        if !label.is_empty() && label != key {
            one["label"] = json!(label);
        }
        cols.push(one);
    }
    let mut calc = Vec::new();
    let mut names: Vec<String> = Vec::new();
    for c in slice_items(m.get("calc"), 50)? {
        let Some(c) = c.as_object() else { continue };
        let (name, formula) = (ptext(c.get("name"), 100), ptext(c.get("formula"), 2000));
        if name.is_empty() || formula.is_empty() || names.contains(&name) {
            continue;
        }
        names.push(name.clone());
        calc.push(json!({"name": name, "formula": formula}));
    }
    let mut filters = Vec::new();
    for f in slice_items(m.get("filters"), 30)? {
        let Some(f) = f.as_object() else { continue };
        let column = ptext(f.get("column"), 200);
        let op = pyish::text_or_empty(f.get("op"));
        if column.is_empty() || !VIEWER_OPS.contains(&op.as_str()) {
            continue;
        }
        filters.push(json!({"column": column, "op": op, "value": ptext(f.get("value"), 500)}));
    }
    let mut out = Map::new();
    let has_filters = !filters.is_empty();
    if !cols.is_empty() {
        out.insert("cols".into(), Value::Array(cols));
    }
    if !calc.is_empty() {
        out.insert("calc".into(), Value::Array(calc));
    }
    if has_filters {
        out.insert("filters".into(), Value::Array(filters));
        if m.get("join") == Some(&json!("or")) {
            out.insert("join".into(), json!("or"));
        }
    }
    Ok(Value::Object(out))
}

const POST_OPS: [&str; 9] = ["unpivot", "repeat", "pivot", "group", "select", "remove", "rename", "sort", "m"];
const POST_AGGS: [&str; 7] = ["sum", "count", "average", "min", "max", "first", "none"];
const GROUP_AGGS: [(&str, &str); 6] =
    [("count", "件数"), ("sum", "合計"), ("average", "平均"), ("min", "最小"), ("max", "最大"), ("count_distinct", "個別の件数")];

/// navi_post の _names（重ねない・空を落とす・200 まで）。
fn post_names(v: Option<&Value>) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for x in list_or_empty(v) {
        let n = ptext(Some(x), 200);
        if !n.is_empty() && !out.contains(&n) {
            out.push(n);
        }
    }
    out.truncate(200);
    out
}

/// navi_post.normalize_step（知らない手順は None）。
fn normalize_step(s: &Value) -> R<Option<Value>> {
    let s = dict_of(Some(s))?;
    let op = ptext(s.get("op"), 200);
    if !POST_OPS.contains(&op.as_str()) {
        return Ok(None);
    }
    let or = |v: String, d: &str| if v.is_empty() { d.to_string() } else { v };
    Ok(Some(match op.as_str() {
        "unpivot" => json!({
            "op": op, "mode": if s.get("mode") == Some(&json!("selected")) { "selected" } else { "other" },
            "columns": post_names(s.get("columns")),
            "attr": or(ptext(s.get("attr"), 200), "属性"), "value": or(ptext(s.get("value"), 200), "値"),
        }),
        "repeat" => normalize_repeat(&s)?,
        "pivot" => {
            let agg = ptext(s.get("agg"), 200);
            json!({"op": op, "column": ptext(s.get("column"), 200), "value": ptext(s.get("value"), 200),
                   "agg": if POST_AGGS.contains(&agg.as_str()) { agg } else { "sum".into() }})
        }
        "group" => {
            let mut aggs = Vec::new();
            for a in list_or_empty(s.get("aggs")).iter().take(200) {
                let a = dict_of(Some(a))?;
                let f = ptext(a.get("func"), 200);
                let (f, label) = GROUP_AGGS.iter().find(|(k, _)| *k == f).copied().unwrap_or(GROUP_AGGS[0]);
                let col = if f == "count" { String::new() } else { ptext(a.get("column"), 200) };
                let name = ptext(a.get("name"), 200);
                let name = if !name.is_empty() {
                    name
                } else if f == "count" {
                    label.to_string()
                } else {
                    format!("{col}の{label}")
                };
                aggs.push(json!({"func": f, "column": col, "name": name}));
            }
            if aggs.is_empty() {
                aggs.push(json!({"func": "count", "column": "", "name": "件数"}));
            }
            json!({"op": op, "keys": post_names(s.get("keys")), "aggs": aggs})
        }
        "select" | "remove" => json!({"op": op, "columns": post_names(s.get("columns"))}),
        "rename" => {
            let pairs: Vec<Value> = list_or_empty(s.get("pairs"))
                .iter()
                .take(200)
                .filter_map(|p| {
                    let p = p.as_array().filter(|p| p.len() == 2)?;
                    let (a, b) = (ptext(Some(&p[0]), 200), ptext(Some(&p[1]), 200));
                    (!a.is_empty() && !b.is_empty()).then(|| json!([a, b]))
                })
                .collect();
            json!({"op": op, "pairs": pairs})
        }
        "sort" => {
            let keys: Vec<Value> = list_or_empty(s.get("keys"))
                .iter()
                .take(200)
                .filter_map(|p| {
                    let p = p.as_array().filter(|p| !p.is_empty())?;
                    let k = ptext(Some(&p[0]), 200);
                    (!k.is_empty()).then(|| json!([k, if p.get(1) == Some(&json!("desc")) { "desc" } else { "asc" }]))
                })
                .collect();
            json!({"op": op, "keys": keys})
        }
        _ => json!({"op": op, "expr": pyish::head(&pyish::text_or_empty(s.get("expr")).replace("\r\n", "\n"), 20_000)}),
    }))
}

/// navi_post._normalize_repeat（繰り返し列の展開）。
fn normalize_repeat(s: &Map<String, Value>) -> R<Value> {
    let names: Vec<String> = list_or_empty(s.get("names")).iter().map(|x| ptext(Some(x), 200)).take(200).collect();
    let raw: Vec<&Vec<Value>> = list_or_empty(s.get("groups")).iter().filter_map(Value::as_array).take(500).collect();
    let width = if names.is_empty() { raw.iter().map(|g| g.len()).max().unwrap_or(0) } else { names.len() }.min(200);
    let groups: Vec<Value> = raw
        .iter()
        .map(|g| {
            let mut row: Vec<Value> = g
                .iter()
                .take(width)
                .map(|x| {
                    let t = ptext(Some(x), 200);
                    if t.is_empty() {
                        Value::Null
                    } else {
                        json!(t)
                    }
                })
                .collect();
            row.extend(std::iter::repeat_n(Value::Null, width.saturating_sub(g.len())));
            Value::Array(row)
        })
        .collect();
    let names = if names.is_empty() { vec![String::new(); width] } else { names };
    let mut nums: Vec<i64> = Vec::new();
    for x in list_or_empty(s.get("numbers")) {
        match pyish::int_opt(x) {
            Ok(Some(n)) => nums.push(n),
            Ok(None) => {
                nums.clear();
                break;
            }
            Err(_) => return Err(Pass),
        }
    }
    if nums.len() != groups.len() || nums.windows(2).any(|w| w[1] <= w[0]) {
        nums = (1..=groups.len() as i64).collect();
    }
    let index = ptext(s.get("index"), 200);
    Ok(json!({
        "op": "repeat", "groups": groups, "numbers": nums, "names": names,
        "index": if index.is_empty() { "番号".to_string() } else { index },
        "drop_empty": s.get("drop_empty") != Some(&Value::Bool(false)),
    }))
}

/// navi_post.normalize（後処理。使っていなければ {}）。
pub fn normalize_post(d: &Value) -> R<Value> {
    let empty = Map::new();
    let m = d.as_object().unwrap_or(&empty);
    let mut steps = Vec::new();
    for s in list_or_empty(m.get("steps")).iter().take(30) {
        if let Some(x) = normalize_step(s)? {
            steps.push(x);
        }
    }
    let mode = pick(m.get("mode"), &["steps", "query"]).unwrap_or("steps");
    let (enabled, query_id) = (truthy(m.get("enabled")), ptext(m.get("query_id"), 200));
    if !enabled && steps.is_empty() && query_id.is_empty() {
        return Ok(json!({}));
    }
    Ok(json!({"enabled": enabled, "mode": mode, "steps": steps, "query_id": query_id, "query_out": ptext(m.get("query_out"), 200)}))
}

const COLUMN_TYPES: [&str; 6] = ["text", "integer", "numeric", "real", "date", "datetime"];

/// navi_output.normalize_column_type。
fn normalize_column_type(v: Option<&Value>) -> &'static str {
    let v = txt(v).to_lowercase();
    let v = match v.as_str() {
        "str" | "string" | "char" => "text",
        "int" => "integer",
        "number" | "float" | "decimal" | "double" | "num" => "numeric",
        "time" | "timestamp" => "datetime",
        other => other,
    };
    COLUMN_TYPES.iter().find(|t| **t == v).copied().unwrap_or("text")
}

/// navi_text.normalize_column（開始＋長さに寄せる。区切りでは何番目の項目か）。
fn normalize_column(c: &Value, index: usize, mode: &str) -> R<Value> {
    let c = dict_of(Some(c))?;
    let start = int_text_or(c.get("start"), 1)?.max(1);
    let mut length = int_text_or(c.get("length"), 0)?;
    if length < 1 {
        let end = int_text_or(c.get("end"), 0)?;
        length = if end >= start { end.checked_sub(start).and_then(|x| x.checked_add(1)).ok_or(Pass)? } else { 0 };
    }
    let t = normalize_column_type(c.get("type"));
    let mut fmt = txt(c.get("format"));
    if (t == "date" || t == "datetime") && fmt.is_empty() {
        fmt = if t == "date" { "YYYYMMDD" } else { "YYYYMMDDHHMMSS" }.into();
    }
    if t != "date" && t != "datetime" {
        fmt.clear();
    }
    let name = txt(c.get("name"));
    let len = length.max(0);
    let field =
        if mode == "delimited" { int_text_or(c.get("field"), index as i64 + 1)?.max(1) } else { int_text_or(c.get("field"), 0)?.max(0) };
    Ok(json!({
        "name": if name.is_empty() { format!("列{}", index + 1) } else { name },
        "start": start, "length": len, "end": start.checked_add(len).ok_or(Pass)? - 1,
        "field": field, "type": t,
        "scale": if t == "real" { int_text_or(c.get("scale"), 0)?.clamp(0, 9) } else { 0 },
        "format": fmt, "note": txt(c.get("note")),
    }))
}

const TEXT_ENCODINGS: [&str; 7] = ["cp932", "utf-8-sig", "utf-8", "euc_jp", "shift_jis", "utf-16", "latin-1"];

/// navi_text.normalize_layout（読取マスタ1件）。
pub fn normalize_layout(d: &Map<String, Value>) -> R<Value> {
    let raw_enc = txt(d.get("encoding")).to_lowercase();
    let enc = match raw_enc.replace('-', "_").as_str() {
        "utf_8" => "utf-8".to_string(),
        "utf_8_sig" => "utf-8-sig".into(),
        "sjis" | "ms932" => "cp932".into(),
        "utf_16" => "utf-16".into(),
        "latin_1" => "latin-1".into(),
        _ => raw_enc.clone(),
    };
    let enc = if TEXT_ENCODINGS.contains(&enc.as_str()) { enc } else { "cp932".into() };
    let one = |k: &str, allowed: &[&'static str], default: &'static str| -> &'static str {
        let v = txt(d.get(k)).to_lowercase();
        allowed.iter().find(|a| **a == v).copied().unwrap_or(default)
    };
    let unit = one("unit", &["char", "byte"], "byte");
    let trim = one("trim", &["both", "right", "left", "none"], "both");
    let mode = one("mode", &["fixed", "delimited"], "fixed");
    let delim = one("delimiter", &["comma", "tab", "semicolon", "pipe", "space", "custom", "regex"], "comma");
    let quote = one("quote", &["double", "single", "none"], "double");
    let dtext = if delim == "custom" || delim == "regex" { pyish::text_or_empty(d.get("delimiter_text")) } else { String::new() };
    let mut cols = Vec::new();
    for (i, c) in pyish::py_iter(d.get("columns")).ok_or(Pass)?.iter().enumerate() {
        cols.push(normalize_column(c, i, mode)?);
    }
    let get_or = |k: &str, default: bool| d.get(k).map(pyish::truthy).unwrap_or(default);
    Ok(json!({
        "id": txt(d.get("id")), "name": txt(d.get("name")), "description": txt(d.get("description")),
        "mode": mode, "delimiter": delim, "delimiter_text": dtext, "quote": quote,
        "collapse": get_or("collapse", false),
        "encoding": enc, "unit": unit, "trim": trim,
        "skip_head": int_text_or(d.get("skip_head"), 0)?.clamp(0, 999),
        "skip_tail": int_text_or(d.get("skip_tail"), 0)?.clamp(0, 999),
        "skip_blank": get_or("skip_blank", true), "header_row": get_or("header_row", false),
        "columns": cols, "sample_path": txt(d.get("sample_path")),
        "updated_at": pyish::text_or_empty(d.get("updated_at")),
    }))
}

const SOURCE_FORMATS: [&str; 6] = ["csv", "txt", "xlsx", "sqlite3", "accdb", "fixed"];
const ALIASES: [char; 8] = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

/// navi_join.normalize_join（つなぎ目1つ）。
fn normalize_join(d: Option<&Value>) -> R<Value> {
    let d = dict_of(d)?;
    let t = txt(d.get("type")).to_lowercase();
    let t = if ["inner", "left", "full"].contains(&t.as_str()) { t } else { "inner".into() };
    let mut keys = Vec::new();
    for k in pyish::py_iter(d.get("keys")).ok_or(Pass)? {
        let k = match &k {
            Value::Object(m) => m.clone(),
            x if !pyish::truthy(x) => Map::new(),
            _ => return Err(Pass), // 'str'.get は AttributeError
        };
        let (l, r) = (txt(k.get("left")), txt(k.get("right")));
        if !l.is_empty() || !r.is_empty() {
            keys.push(json!({"left": l, "right": r}));
        }
    }
    keys.truncate(6);
    Ok(json!({"type": t, "keys": keys}))
}

/// navi_join.normalize_recipe（結合マスタ1件。左から右へ1本の鎖）。
pub fn normalize_recipe(d: &Map<String, Value>) -> R<Value> {
    let mut srcs = Vec::new();
    for (i, x) in pyish::py_iter(d.get("sources")).ok_or(Pass)?.iter().enumerate().take(8) {
        let s = dict_of(Some(x))?;
        let fmt = txt(s.get("format")).to_lowercase();
        let fmt = match fmt.as_str() {
            "sqlite" | "db" => "sqlite3".to_string(),
            "excel" | "xls" => "xlsx".into(),
            "text" => "fixed".into(),
            _ => fmt,
        };
        let fmt = if SOURCE_FORMATS.contains(&fmt.as_str()) {
            fmt
        } else {
            match paths::py_suffix(&pyish::text_or_empty(s.get("path"))).to_lowercase().as_str() {
                ".txt" => "txt",
                ".xlsx" => "xlsx",
                ".sqlite3" | ".sqlite" | ".db" => "sqlite3",
                ".accdb" => "accdb",
                _ => "csv",
            }
            .into()
        };
        srcs.push(json!({
            "alias": ALIASES[i].to_string(), "name": txt(s.get("name")), "path": txt(s.get("path")), "format": fmt,
            "table": txt(s.get("table")), "sheet": txt(s.get("sheet")), "layout_id": txt(s.get("layout_id")),
        }));
    }
    let mut joins = Vec::new();
    for x in pyish::py_iter(d.get("joins")).ok_or(Pass)? {
        joins.push(normalize_join(Some(&x))?);
    }
    let need = srcs.len().saturating_sub(1);
    while joins.len() < need {
        joins.push(normalize_join(None)?);
    }
    joins.truncate(need);
    let mut cols = Vec::new();
    for c in pyish::py_iter(d.get("columns")).ok_or(Pass)? {
        let c = dict_of(Some(&c))?;
        let name = txt(c.get("name"));
        if name.is_empty() {
            continue;
        }
        cols.push(json!({"source": pyish::strip(&naming::text_or(c.get("source"), "A")), "name": name, "as": txt(c.get("as"))}));
    }
    Ok(json!({
        "id": txt(d.get("id")), "name": txt(d.get("name")), "description": txt(d.get("description")),
        "sources": srcs, "joins": joins, "columns": cols, "updated_at": pyish::text_or_empty(d.get("updated_at")),
    }))
}

/// navi_mrun.normalize_query（クエリ1件。式の改行は \n にそろえる）。
pub fn normalize_query(d: &Map<String, Value>) -> Value {
    json!({
        "id": txt(d.get("id")), "name": txt(d.get("name")), "description": txt(d.get("description")),
        "code": pyish::text_or_empty(d.get("code")).replace("\r\n", "\n").replace('\r', "\n"),
        "output": txt(d.get("output")), "updated_at": pyish::text_or_empty(d.get("updated_at")),
    })
}

/// _decode_period（ジョブの相対期間。読めなければ無効の既定）。
fn decode_period(raw: Option<&Value>) -> R<Value> {
    let d = match raw {
        Some(x) if pyish::truthy(x) => match x {
            Value::String(s) => match py_json(s) {
                Json::Ok(v) => v,
                Json::Bad => json!({}),
                Json::Unsure => return Err(Pass),
            },
            _ => json!({}),
        },
        _ => json!({}),
    };
    let empty = Map::new();
    let p = crate::period::normalize(d.as_object().unwrap_or(&empty)).map_err(|_| Pass)?;
    Ok(json!({
        "enabled": p.enabled, "target": p.target, "control_point": p.control_point, "cond_item": p.cond_item,
        "range": p.range, "unit": p.unit, "from_offset": p.from_offset, "to_offset": p.to_offset,
    }))
}

/// _json_list（JSON の並びを、空でない字の一覧として読む）。
fn json_list(v: Option<&Value>) -> R<Value> {
    Ok(match loads_or(v, "[]", json!([]))? {
        Value::Array(a) => Value::Array(
            a.iter().map(|x| pyish::strip(&pyish::py_str(x)).to_string()).filter(|s| !s.is_empty()).map(Value::String).collect(),
        ),
        _ => json!([]),
    })
}

/// _json_or_empty（読めなければ・偽の値なら {}）。
fn json_or_empty(v: Option<&Value>) -> R<Value> {
    let x = loads_or(v, "{}", json!({}))?;
    Ok(if pyish::truthy(&x) { x } else { json!({}) })
}

/// navi_textrun._json_rows（JSON の並びのうち辞書だけ）。
fn json_rows(v: Option<&Value>) -> R<Value> {
    Ok(match loads_or(v, "[]", json!([]))? {
        Value::Array(a) => Value::Array(a.into_iter().filter(Value::is_object).collect()),
        _ => json!([]),
    })
}

// ==== 写しを読む ============================================================

type Row = Map<String, Value>;

fn sql_value(v: ValueRef) -> R<Value> {
    Ok(match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => json!(i),
        ValueRef::Real(f) => serde_json::Number::from_f64(f).map(Value::Number).unwrap_or(Value::Null),
        ValueRef::Text(t) => Value::String(String::from_utf8(t.to_vec()).map_err(|_| Pass)?),
        ValueRef::Blob(_) => return Err(Pass),
    })
}

fn to_sql(v: &Value) -> rusqlite::types::Value {
    match v {
        Value::Null => rusqlite::types::Value::Null,
        Value::Number(n) => {
            n.as_i64().map(rusqlite::types::Value::Integer).unwrap_or_else(|| rusqlite::types::Value::Real(n.as_f64().unwrap_or(0.0)))
        }
        Value::String(s) => rusqlite::types::Value::Text(s.clone()),
        other => rusqlite::types::Value::Text(other.to_string()),
    }
}

fn rows(c: &Connection, sql: &str, params: &[rusqlite::types::Value]) -> R<Vec<Row>> {
    let mut st = c.prepare(sql).map_err(|_| Pass)?;
    let names: Vec<String> = st.column_names().iter().map(|s| s.to_string()).collect();
    let mut q = st.query(rusqlite::params_from_iter(params.iter())).map_err(|_| Pass)?;
    let mut out = Vec::new();
    while let Some(r) = q.next().map_err(|_| Pass)? {
        let mut m = Map::new();
        for (i, n) in names.iter().enumerate() {
            m.insert(n.clone(), sql_value(r.get_ref(i).map_err(|_| Pass)?)?);
        }
        out.push(m);
    }
    Ok(out)
}

/// `r[k] if k in r.keys() else default`。
fn col<'a>(r: &'a Row, k: &str, default: &'a Value) -> &'a Value {
    r.get(k).unwrap_or(default)
}

/// _decode_setting（保存の型どおりに戻す）。
fn decode_setting(v: &Value, t: &Value) -> R<Value> {
    match t.as_str() {
        Some("json") => loads_strict(v),
        Some("bool") => Ok(Value::Bool(v.as_str() == Some("1"))),
        Some("int") => match pyish::int_opt(v) {
            Ok(Some(i)) => Ok(json!(i)),
            _ => Err(Pass),
        },
        _ => Ok(v.clone()),
    }
}

/// 共通設定の既定値（app.SETTING_DEFAULTS。navi_order.WAIT_DEFAULTS を含む）。
pub fn setting_defaults() -> Map<String, Value> {
    let v = json!({
        "api_parallel_lines": 6, "variant_method": "combined",
        "retry_enabled": true, "retry_delay_minutes": 5, "retry_max": 1, "schedule_catchup_minutes": 30,
        "api_worker_stagger_ms": 700, "local_parallel_lines": 0, "api_worker_timeout_minutes": 120,
        "log_max_mb": 10, "log_keep": 5, "reject_zero_rows": true,
        "backup_enabled": true, "backup_mode": "generations", "backup_generations": 3, "backup_retention_days": 30,
        "split_trial_timeout_seconds": 1800, "split_anchor_limit": 3, "split_min_part_mb": 2.0, "split_min_gain_seconds": 5.0,
        "split_min_speedup": 1.05, "split_fixed_seconds": 10.0, "split_run_enabled": true,
        "join_wait_enabled": true, "join_wait_lookahead_seconds": 60, "join_wait_max_seconds": 600, "join_wait_poll_seconds": 5,
    });
    v.as_object().cloned().unwrap_or_default()
}

/// 撤去した設定（app.REMOVED_SETTINGS・REMOVED_TOP_KEYS）。
const REMOVED_SETTINGS: [&str; 11] = [
    "extract_engine",
    "dde_timeout_seconds",
    "output_wait_seconds",
    "symnavi_hide_profile",
    "symnavi_hide_action_duration_seconds",
    "symnavi_hide_action_interval_seconds",
    "symnavi_hide_interval_seconds",
    "stability_profile",
    "api_parallel_model",
    "startup_run",
    "backup_generation_limit_enabled",
];
const REMOVED_TOP_KEYS: [&str; 3] = ["symnavi_exe", "symnavim_def", "work_folder"];
pub const TEXT_FOLDER_DEFAULT: &str = r"\\nlmfanago02d\QPMS";
const DEFAULT_DLL_SEARCH_ROOTS: [&str; 3] = [r"C:\NAVIAP", r".\Config\NAVIAP", r".\NAVIAP"];
const APP_LOCAL_NAMES: [&str; 3] = ["datarelay", "symfonavidatahub", "navitosqlite"];
const PC_BACKUP: &str = r"<PC>\backup";

/// 道の字を区切り（\ でも / でも）で分ける（navi_paths._split_any）。
fn split_any(p: &str) -> Vec<&str> {
    p.split(['\\', '/']).filter(|x| !x.is_empty()).collect()
}

/// navi_paths._profile_root（C:\Users\<誰か> のような利用者プロファイルの根）。
fn profile_root(p: &str) -> Option<String> {
    let parts = split_any(p);
    parts
        .iter()
        .enumerate()
        .find(|(i, x)| ["users", "ユーザー", "documents and settings"].contains(&x.to_lowercase().as_str()) && i + 1 < parts.len())
        .map(|(i, _)| parts[..i + 2].join("\\"))
}

/// navi_paths.foreign_profile_path（別の利用者のプロファイルの下を指していれば、その根）。
pub fn foreign_profile_path(value: &str) -> Option<String> {
    let raw = pyish::strip(value);
    if raw.is_empty() || raw.starts_with("<PC>") {
        return None;
    }
    let target = paths::py_path(&paths::expand_user_vars(raw));
    let b = target.as_bytes();
    let win_abs =
        (b.len() >= 3 && b[0].is_ascii_alphabetic() && b[1] == b':' && matches!(b[2], b'\\' | b'/')) || target.starts_with("\\\\");
    if !(paths::is_absolute(&target) || win_abs) {
        return None;
    }
    let root = profile_root(&target)?;
    let home = paths::py_path(&paths::expand_user("~"));
    let mine = profile_root(&home).unwrap_or_else(|| split_any(&home).join("\\"));
    (root.to_lowercase() != mine.to_lowercase()).then_some(root)
}

/// navi_paths._looks_generated_backup（アプリが自分で作った控えの置き場 …\<アプリ名>\backup）。
fn looks_generated_backup(value: &str) -> bool {
    let parts: Vec<String> = split_any(value).iter().map(|x| x.to_lowercase()).collect();
    parts.len() >= 2 && parts[parts.len() - 1] == "backup" && APP_LOCAL_NAMES.contains(&parts[parts.len() - 2].as_str())
}

/// app.load と同じ設定（jobs・text_layouts・join_recipes・m_queries・settings・settings_revision を含む）。
pub fn load(core: &Core, c: &Connection) -> R<Map<String, Value>> {
    let mut cfg = Map::new();
    for r in rows(c, "SELECT key,value,value_type FROM app_settings", &[])? {
        let Some(Value::String(k)) = r.get("key") else { return Err(Pass) };
        cfg.insert(k.clone(), decode_setting(&r["value"], &r["value_type"])?);
    }
    let null = Value::Null;
    let empty_text = json!("");
    let mut jobs = Vec::new();
    for r in rows(c, "SELECT * FROM jobs ORDER BY display_order,id", &[])? {
        let mut rules = Vec::new();
        for x in rows(c, "SELECT * FROM schedules WHERE job_id=? ORDER BY display_order,id", &[to_sql(col(&r, "id", &null))])? {
            let time = col(&x, "time_value", &null);
            let mut q = json!({
                "id": col(&x, "id", &null), "enabled": pyish::truthy(col(&x, "enabled", &null)), "name": col(&x, "name", &null),
                "type": col(&x, "schedule_type", &null), "time": if pyish::truthy(time) { time.clone() } else { json!("06:00") },
            });
            if !col(&x, "interval_minutes", &null).is_null() {
                q["interval_minutes"] = x["interval_minutes"].clone();
            }
            for (k, out) in [("weekdays_json", "weekdays"), ("month_days_json", "month_days"), ("dates_json", "dates")] {
                if pyish::truthy(col(&x, k, &null)) {
                    q[out] = loads_strict(&x[k])?;
                }
            }
            rules.push(q);
        }
        let g = |k: &str| r.get(k);
        let fmt = naming::normalize_output_format(g("output_format"), g("output_file"));
        let mut probe = Map::new();
        probe.insert("output_format".into(), json!(fmt));
        probe.insert("output_file".into(), col(&r, "output_file", &null).clone());
        probe.insert("extra_formats".into(), col(&r, "extra_formats", &empty_text).clone());
        let split = |k: &str, allowed: &[&str]| {
            let v = txt(g(k)).to_lowercase();
            if allowed.contains(&v.as_str()) {
                v
            } else {
                "auto".into()
            }
        };
        let axis = naming::text_or(g("row_axis_mode"), "first").to_lowercase();
        let axis_index = match g("row_axis_index") {
            None => 1,
            Some(v) if !pyish::truthy(v) => 1,
            Some(v) => pyish::int_opt(v).ok().flatten().ok_or(Pass)?,
        };
        let s = |k: &str| pyish::text_or_empty(g(k));
        jobs.push(json!({
            "id": col(&r, "id", &null), "enabled": pyish::truthy(col(&r, "enabled", &null)), "name": col(&r, "name", &null),
            "rne": col(&r, "rne", &null), "rne_path": col(&r, "rne_path", &null), "output_folder": col(&r, "output_folder", &null),
            "output_format": fmt, "output_file": naming::canonical_output_file(g("output_file"), fmt),
            "table": col(&r, "table_name", &null), "sheet": col(&r, "sheet_name", &null), "type": col(&r, "read_type", &null),
            "naming_mode": r.get("naming_mode").cloned().unwrap_or(json!("fixed")),
            "output_pattern": col(&r, "output_pattern", &empty_text), "comment": col(&r, "comment", &empty_text),
            "group": normalize_group(Some(col(&r, "group_name", &empty_text))),
            "split_mode": split("split_mode", &["auto", "force", "race", "off"]),
            "split_shape": split("split_shape", &["auto", "column", "row", "grid"]),
            "row_axis_mode": if ["first", "index", "name", "balanced"].contains(&axis.as_str()) { axis } else { "first".into() },
            "row_axis_index": axis_index, "row_axis_name": s("row_axis_name"),
            "extra_formats": naming::job_extra_formats(&probe).ok_or(Pass)?,
            "index_columns": json_list(g("index_columns"))?,
            "skip_if_unchanged": g("skip_if_unchanged").is_some_and(pyish::truthy),
            "source": settings::job_source(&s("source")),
            "text_path": s("text_path"), "layout_id": s("layout_id"), "recipe_id": s("recipe_id"),
            "query_id": s("query_id"), "query_out": s("query_out"),
            "period": decode_period(g("period_json"))?,
            "variants": normalize_variants(&json_or_empty(g("variants_json"))?)?,
            "viewer": normalize_viewer(&json_or_empty(g("viewer_json"))?)?,
            "post": normalize_post(&json_or_empty(g("post_json"))?)?,
            "schedules": rules,
        }));
    }
    cfg.insert("jobs".into(), Value::Array(jobs));
    let mut layouts = Vec::new();
    for r in rows(c, "SELECT * FROM text_layouts ORDER BY display_order,name", &[])? {
        let mut d = Map::new();
        if let Some(raw) = r.get("parse_json") {
            if let Value::Object(p) = loads_or(Some(raw), "{}", json!({}))? {
                for k in ["mode", "delimiter", "delimiter_text", "quote", "collapse"] {
                    if let Some(v) = p.get(k) {
                        d.insert(k.into(), v.clone());
                    }
                }
            }
        }
        for k in ["id", "name", "description", "encoding", "unit", "trim", "skip_head", "skip_tail", "sample_path", "updated_at"] {
            d.insert(k.into(), col(&r, k, &null).clone());
        }
        d.insert("skip_blank".into(), json!(pyish::truthy(col(&r, "skip_blank", &null))));
        d.insert("header_row".into(), json!(pyish::truthy(col(&r, "header_row", &null))));
        d.insert("columns".into(), json_rows(r.get("columns_json"))?);
        layouts.push(normalize_layout(&d)?);
    }
    cfg.insert("text_layouts".into(), Value::Array(layouts));
    let mut recipes = Vec::new();
    for r in rows(c, "SELECT * FROM join_recipes ORDER BY display_order,name", &[])? {
        let mut d = Map::new();
        for k in ["id", "name", "description", "updated_at"] {
            d.insert(k.into(), col(&r, k, &null).clone());
        }
        for (k, out) in [("sources_json", "sources"), ("joins_json", "joins"), ("columns_json", "columns")] {
            d.insert(out.into(), json_rows(r.get(k))?);
        }
        recipes.push(normalize_recipe(&d)?);
    }
    cfg.insert("join_recipes".into(), Value::Array(recipes));
    let mut queries = Vec::new();
    for r in rows(c, "SELECT * FROM m_queries ORDER BY display_order,name", &[])? {
        let mut d = Map::new();
        for k in ["id", "name", "description", "code", "updated_at"] {
            d.insert(k.into(), col(&r, k, &null).clone());
        }
        d.insert("output".into(), col(&r, "output_query", &null).clone());
        queries.push(normalize_query(&d));
    }
    cfg.insert("m_queries".into(), Value::Array(queries));
    // 設定の版（画面はこれを送り返し、ほかで変わっていれば保存を断る）
    let rev = rows(c, "SELECT value FROM schema_info WHERE key='settings_revision'", &[])?;
    let rev = match rev.first().map(|r| col(r, "value", &null)) {
        None => 0,
        Some(v) => {
            let s = pyish::py_str(v);
            let t = pyish::strip(&s).trim_start_matches('-');
            if t.is_empty() || !t.is_ascii() {
                if t.is_ascii() {
                    0
                } else {
                    return Err(Pass); // str.isdigit は Unicode の数字の仲間（²など）も数字と見る
                }
            } else if t.bytes().all(|b| b.is_ascii_digit()) {
                pyish::int_opt(v).ok().flatten().ok_or(Pass)?
            } else {
                0
            }
        }
    };
    cfg.insert("settings_revision".into(), json!(rev));
    let settings = cfg.entry("settings").or_insert_with(|| json!({}));
    let Value::Object(st) = settings else { return Err(Pass) };
    st.entry("api_parallel_max_lines").or_insert(json!(24));
    if st.get("stability_profile") == Some(&json!("stable_api_serial")) {
        st.insert("api_parallel_lines".into(), json!(6));
    }
    for k in REMOVED_SETTINGS {
        st.remove(k);
    }
    let backup_mode_missing = !st.contains_key("backup_mode");
    for (k, v) in setting_defaults() {
        st.entry(k).or_insert(v);
    }
    if backup_mode_missing {
        st.insert("backup_generations".into(), json!(3));
    }
    for k in REMOVED_TOP_KEYS {
        cfg.remove(k);
    }
    cfg.entry("navigator_api_dll").or_insert(json!(r".\Config\NAVIAP\debugdllVC14x64\SymNaviA.dll"));
    cfg.entry("accdb_template").or_insert(json!(r".\assets\empty.accdb"));
    cfg.entry("text_folder").or_insert(json!(TEXT_FOLDER_DEFAULT));
    if !matches!(cfg.get("navigator_api_search_roots"), Some(Value::Array(a)) if !a.is_empty()) {
        cfg.insert("navigator_api_search_roots".into(), json!(DEFAULT_DLL_SEARCH_ROOTS));
    }
    let depth = match cfg.get("navigator_api_search_depth") {
        None => 3,
        Some(v) if !pyish::truthy(v) => 3,
        Some(v) => match pyish::int_opt(v) {
            Ok(Some(i)) => i.clamp(1, 6),
            Ok(None) => 3,
            Err(_) => return Err(Pass),
        },
    };
    cfg.insert("navigator_api_search_depth".into(), json!(depth));
    // 控えの置き場は PC ごとに変わる場所。<PC> の印で持つ（別の PC で他人のフォルダーを指さないように）
    let bf = txt(cfg.get("backup_folder"));
    if ["", r".\backup", "backup", r".\config\backup"].contains(&bf.to_lowercase().as_str()) || looks_generated_backup(&bf) {
        cfg.insert("backup_folder".into(), json!(PC_BACKUP));
    } else if let Some(foreign) = foreign_profile_path(&bf) {
        crate::applog::write(
            &paths::local_root(),
            "WARNING",
            &format!("PATH_FOREIGN_PROFILE key=backup_folder value={bf} profile={foreign} → {PC_BACKUP} へ読み替えます"),
        );
        cfg.insert("backup_folder".into(), json!(PC_BACKUP));
    }
    let _ = core;
    Ok(cfg)
}

/// RNE の在りか（resolve_rne_path）。字でない値は Python と同じ字にしてから読む。
fn rne_path(core: &Core, job: &Map<String, Value>, cfg: &Map<String, Value>) -> Option<String> {
    let bases = core.bases()?;
    let v = job.get("rne_path").filter(|v| pyish::truthy(v)).or_else(|| job.get("rne"));
    let folder = naming::text_or(cfg.get("rne_folder"), r".\rne");
    Some(bases.resolve_in(&pyish::text_or_empty(v), Some(&folder)))
}

/// navi_web.get_config が load の答えに足す物（対象ごとの出力名の試算と、共通設定の既定値）。
pub fn add_previews(core: &Core, cfg: &mut Map<String, Value>, now: NaiveDateTime) {
    let snapshot = cfg.clone();
    let Some(Value::Array(jobs)) = cfg.get_mut("jobs") else { return };
    for j in jobs.iter_mut() {
        let Value::Object(job) = j else { continue };
        let pattern = txt(job.get("output_pattern"));
        let is_var =
            naming::text_or(job.get("naming_mode"), "fixed").to_lowercase() == "template" && naming::has_template_variables(&pattern);
        job.insert("output_is_variable".into(), json!(is_var));
        // RNE の在りか（置き場をいくつも探す）は、型で名前を作る対象だけが使う（Python も同じ所でだけ探す）
        let templated = naming::text_or(job.get("naming_mode"), "fixed").to_lowercase() == "template" && !pattern.is_empty();
        let rp = if templated { rne_path(core, job, &snapshot) } else { None };
        if is_var {
            let fmt = naming::normalize_output_format(job.get("output_format"), job.get("output_file"));
            let made = naming::resolve_output_filename(job, rp.as_deref(), now).and_then(|preview| {
                let mut segs = naming::render_filename_segments(&pattern, &Tokens::new(job, rp.as_deref(), now))?;
                segs.push((naming::output_extension(fmt).to_string(), false));
                Ok((preview, segs))
            });
            let (preview, segs) = match made {
                Ok((p, s)) => (json!(p), s.into_iter().map(|(t, v)| json!({"text": t, "var": v})).collect()),
                Err(_) => (json!(""), vec![]),
            };
            job.insert("output_file_preview".into(), preview);
            job.insert("output_file_segments".into(), Value::Array(segs));
        }
        let plan = naming::job_output_plan(job, rp.as_deref(), now).ok().flatten().unwrap_or(json!([]));
        job.insert("output_plan".into(), plan);
    }
    cfg.insert("setting_defaults".into(), Value::Object(setting_defaults()));
}

// ==== いま Rust が答えてよいか ==============================================

/// 設定の版（app.settings_revision。読めなければ 0）。
fn revision(path: &Path) -> i64 {
    let Ok(c) = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX) else { return 0 };
    let _ = c.busy_timeout(Duration::from_secs(5));
    let v: Option<String> = c.query_row("SELECT CAST(value AS TEXT) FROM schema_info WHERE key='settings_revision'", [], |r| r.get(0)).ok();
    v.and_then(|s| {
        let t = pyish::strip(&s);
        let body = t.trim_start_matches('-');
        (!body.is_empty() && body.bytes().all(|b| b.is_ascii_digit())).then(|| t.parse::<i64>().ok()).flatten()
    })
    .unwrap_or(0)
}

/// 写しがどのマスターの写しかの記録と比べる字（os.path.normcase(os.path.abspath(マスター))）。
fn owner_text(master: &str) -> String {
    let abs = if paths::is_absolute(master) {
        master.to_string()
    } else {
        paths::join(&std::env::current_dir().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default(), master)
    };
    let n = paths::normpath(&abs);
    if cfg!(windows) {
        n.to_lowercase().replace('/', "\\")
    } else {
        n
    }
}

/// いま Python が設定を読んでも、写しをそのまま読むか（init_settings_db が写しを替えない・形を直さない・移行しない）。
pub fn settled(core: &Core, local: &Path, c: &Connection) -> bool {
    let Some(master) = core.config_dir().map(|d| PathBuf::from(paths::join(&d, "app_settings.sqlite3"))) else { return false };
    // マスターがまだ無い → Python が雛形から作り、写しから書き戻す
    let (Ok(mmeta), Ok(lmeta)) = (std::fs::metadata(&master), std::fs::metadata(local)) else { return false };
    if !mmeta.is_file() || lmeta.len() == 0 {
        return false;
    }
    // 写しが別のマスターの物 → Python が退けて取り直す
    let owner = local.with_file_name("app_settings.master.txt");
    if let Ok(raw) = std::fs::read(&owner) {
        let Ok(had) = String::from_utf8(raw) else { return false };
        if pyish::strip(&had) != owner_text(&master.to_string_lossy()) {
            return false;
        }
    }
    // マスターのほうが新しい → Python が取り込む（版が両側とも無いときは更新時刻）
    let (mrev, lrev) = (core.master_revision(&master, &mmeta, revision), revision(local));
    let newer = if mrev != 0 || lrev != 0 { mrev > lrev } else { matches!((mmeta.modified(), lmeta.modified()), (Ok(m), Ok(l)) if m > l) };
    if newer {
        return false;
    }
    // 表の形が古い（列を足す）・設定の移行がまだ（値を書き換える）・古い config.json から移す
    let cols = |t: &str| -> Vec<String> {
        c.prepare(&format!("SELECT name FROM pragma_table_info('{t}')"))
            .and_then(|mut s| s.query_map([], |r| r.get::<_, String>(0)).and_then(|m| m.collect()))
            .unwrap_or_default()
    };
    let jobs = cols("jobs");
    let need = [
        "naming_mode",
        "output_pattern",
        "comment",
        "period_json",
        "split_mode",
        "row_axis_mode",
        "row_axis_index",
        "row_axis_name",
        "extra_formats",
        "index_columns",
        "skip_if_unchanged",
        "source",
        "text_path",
        "layout_id",
        "recipe_id",
        "query_id",
        "query_out",
        "variants_json",
        "post_json",
        "viewer_json",
        "group_name",
        "split_shape",
    ];
    if need.iter().any(|k| !jobs.iter().any(|x| x == k)) || !cols("text_layouts").iter().any(|x| x == "parse_json") {
        return false;
    }
    for t in ["app_settings", "schedules", "schema_info", "join_recipes", "m_queries"] {
        if cols(t).is_empty() {
            return false;
        }
    }
    let migrated: bool =
        c.query_row("SELECT 1 FROM schema_info WHERE key='migrated_parallel_max_lines_24'", [], |_| Ok(true)).unwrap_or(false);
    if !migrated {
        return false;
    }
    let count: i64 = c.query_row("SELECT COUNT(*) FROM app_settings", [], |r| r.get(0)).unwrap_or(0);
    if count == 0 {
        let Some(b) = core.bases() else { return false };
        if Path::new(&paths::join(&b.data_root, "config.json")).exists() {
            return false;
        }
    }
    true
}

/// GET /api/config。
pub(crate) fn get_config(core: &Core, _: &crate::http::Ask, _: &[String]) -> Reply {
    answer(core).unwrap_or_else(|_| Reply::pass())
}

fn answer(core: &Core) -> R<Reply> {
    let local = settings::local_db(Path::new(&paths::py_path(&paths::local_root().to_string_lossy())));
    if !local.is_file() {
        return Err(Pass);
    }
    let c = Connection::open_with_flags(&local, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX).map_err(|_| Pass)?;
    c.busy_timeout(Duration::from_secs(30)).map_err(|_| Pass)?;
    // 読むあいだに Python が書いても、ひとそろいの値を読む
    c.execute_batch("BEGIN").map_err(|_| Pass)?;
    if !settled(core, &local, &c) {
        return Err(Pass);
    }
    let mut cfg = load(core, &c)?;
    let _ = c.execute_batch("COMMIT");
    add_previews(core, &mut cfg, core.now());
    Ok(Reply::json(200, &Value::Object(cfg)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn groups_like_python() {
        assert_eq!(normalize_group(Some(&json!(" 営業 　部 / /a/b/c/d/e/f"))), "営業 部/a/b/c/d");
        assert_eq!(normalize_group(Some(&json!(3))), "");
    }

    #[test]
    fn json_like_python() {
        assert!(matches!(py_json("[1,2]"), Json::Ok(_)));
        assert!(matches!(py_json("{"), Json::Bad));
        assert!(matches!(py_json("[NaN]"), Json::Unsure));
        assert!(matches!(py_json("[12345678901234567890]"), Json::Unsure));
    }

    #[test]
    fn variants_like_python() {
        let v = normalize_variants(&json!({"values": "ab a", "scope": "all", "method": "x", "enabled": 1})).unwrap();
        assert_eq!(v["values"], json!(["a", "b"]));
        assert_eq!(v["scope"], json!("all"));
        assert_eq!(v["method"], json!("default"));
        assert_eq!(normalize_variants(&json!({"values": 5})), Err(Pass), "数は並べられない（Python は落ちる）");
    }

    #[test]
    fn post_repeat_like_python() {
        let v = normalize_post(&json!({"steps": [{"op": "repeat", "groups": [["a", "b", "c"], ["d"]], "numbers": [3, 2]}]})).unwrap();
        assert_eq!(v["steps"][0]["groups"], json!([["a", "b", "c"], ["d", null, null]]));
        assert_eq!(v["steps"][0]["numbers"], json!([1, 2]), "減っていく番号は並び順に振り直す");
        assert_eq!(normalize_post(&json!({"mode": "query"})).unwrap(), json!({}));
    }
}
