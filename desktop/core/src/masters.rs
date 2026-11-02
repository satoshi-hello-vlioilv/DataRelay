//! 読取マスタ・結合マスタ・クエリの一覧と書き出し（2.20.0〜）。lib/navi_web.py の受け口と同じ答えを返す。
//!
//! 読むのは設定の写し（config::read。写しを替える場合・Python でしか同じに読めない値は Python へ回す）。
//! 書き出しの EXCEL（navi_book）と、クエリの一覧（M の式を読んで中のクエリ名を出す）は、まだ Python が受け持つ
//! （EXCEL は出力の段、M の式は Power Query の段で移す）。
//!
//! 画面の選択肢の言葉（下の表）は Python の navi_text・navi_output・navi_join と同じ字にする（tests/test_rust_masters.py が比べる）。

use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{applog, pyish, routes::Core, settings};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

// ==== 画面の選択肢の言葉（navi_text・navi_output・navi_join から写した） ====
pub const ENCODINGS: [(&str, &str); 7] = [
    ("cp932", "Shift-JIS（cp932）"),
    ("utf-8-sig", "UTF-8（BOM付き）"),
    ("utf-8", "UTF-8"),
    ("euc_jp", "EUC-JP"),
    ("shift_jis", "Shift-JIS（標準）"),
    ("utf-16", "UTF-16"),
    ("latin-1", "Latin-1"),
];
pub const UNITS: [(&str, &str); 2] = [("char", "文字数で数える"), ("byte", "バイト数で数える（全角は2）")];
pub const MODES: [(&str, &str); 2] = [("fixed", "固定長（位置で切る）"), ("delimited", "区切り（記号で分ける）")];
pub const DELIMITERS: [(&str, &str); 7] = [
    ("comma", "カンマ（,）"),
    ("tab", "タブ"),
    ("semicolon", "セミコロン（;）"),
    ("pipe", "縦線（|）"),
    ("space", "空白"),
    ("custom", "文字を指定"),
    ("regex", "正規表現（決まりで分ける）"),
];
pub const QUOTES: [(&str, &str); 3] = [("double", "ダブルクォート（\"）"), ("single", "シングルクォート（'）"), ("none", "囲みなし")];
pub const TRIMS: [(&str, &str); 4] =
    [("both", "前後の空白を取る"), ("right", "後ろの空白だけ取る"), ("left", "前の空白だけ取る"), ("none", "そのまま")];
pub const COLUMN_TYPES: [(&str, &str, &str); 6] = [
    ("text", "文字", "そのまま文字として出します（既定）。品番・コード・電話番号など、先頭の0に意味があるものはこれ。"),
    ("integer", "整数", "整数にします。前の0は落ちます（00123→123）。末尾の符号（123-）も読みます。"),
    (
        "numeric",
        "数値",
        "書いてあるとおりに数値にします（123.45→123.45、1234→1234）。小数点が値に入っているならこちら。桁の指定はありません。",
    ),
    (
        "real",
        "小数（桁指定）",
        "小数点が値に入っていないときに使います。右から何桁ぶんを小数にするかを「小数桁」で決めます（0012345 桁2→123.45）。",
    ),
    ("date", "日付", "日付にします。読み方は書式で決めます（既定 YYYYMMDD）。出力は 2026-08-14 の形。"),
    ("datetime", "日時", "日付と時刻にします（既定 YYYYMMDDHHMMSS）。出力は 2026-08-14 09:30:00 の形。"),
];
pub const STAMP_FORMAT_SAMPLES: [&str; 8] =
    ["YYYYMMDD", "YYMMDD", "YYYY/MM/DD", "YYYY-MM-DD", "YYYY年MM月DD日", "YYYYMMDDHHMMSS", "YYYYMMDDHHMM", "YYYY/MM/DD HH:MM:SS"];
pub const JOIN_TYPES: [(&str, &str, &str); 3] = [
    ("inner", "両方にあるものだけ", "キーが一致した行だけを出します"),
    ("left", "左を全部残す", "左に無い行は出ません。右に無いものは空欄で残ります"),
    ("full", "どちらも全部残す", "どちらか片方にしか無い行も、空欄付きで残します"),
];
pub const SOURCE_FORMATS: [(&str, &str); 6] = [
    ("csv", "CSV"),
    ("txt", "TXT（タブ区切り）"),
    ("xlsx", "EXCEL"),
    ("sqlite3", "SQLite3"),
    ("accdb", "ACCESS"),
    ("fixed", "固定長テキスト（読取マスタ）"),
];
/// 型をファイルの中に持てる形式（navi_output.format_keeps_types。並びは OUTPUT_FORMAT_LABEL）。
pub const TYPE_FORMATS: [(&str, bool); 5] = [("sqlite3", true), ("txt", false), ("csv", false), ("xlsx", true), ("accdb", true)];
const MAX_SCALE: i64 = 9;
const DATE_FORMAT_DEFAULT: &str = "YYYYMMDD";
const DATETIME_FORMAT_DEFAULT: &str = "YYYYMMDDHHMMSS";
const LAYOUT_EXPORT_KIND: &str = "symfonavi-text-layouts";
const RECIPE_EXPORT_KIND: &str = "symfonavi-join-recipes";
const QUERY_EXPORT_KIND: &str = "datarelay-m-queries";
const JOIN_MAX_SOURCES: i64 = 8;

fn options(table: &[(&str, &str)]) -> Value {
    Value::Array(table.iter().map(|(k, l)| json!({"value": k, "label": l})).collect())
}

fn label<'a>(table: &[(&'a str, &'a str)], key: &str) -> &'a str {
    table.iter().find(|(k, _)| *k == key).map(|(_, l)| *l).unwrap_or("")
}

// ==== 読取マスタの形（navi_text の layout_width・layout_shape・layout_overlaps・layout_gaps） ====

/// 列が占める範囲（固定長は位置、区切りは項目の番号）。
fn span(c: &Value, mode: &str) -> (i64, i64) {
    let n = |k: &str| c.get(k).and_then(Value::as_i64).unwrap_or(0);
    if mode == "delimited" {
        (n("field"), n("field"))
    } else {
        (n("start"), n("end"))
    }
}

fn columns(l: &Value) -> &[Value] {
    l.get("columns").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

fn mode(l: &Value) -> &str {
    l.get("mode").and_then(Value::as_str).unwrap_or("fixed")
}

/// layout_width（要る長さ。区切りではいちばん後ろの項目の番号）。
pub fn layout_width(l: &Value) -> i64 {
    columns(l).iter().map(|c| span(c, mode(l)).1).max().unwrap_or(0)
}

/// delimiter_label（区切りの呼び名。文字を指定・正規表現は中身まで）。
fn delimiter_label(l: &Value) -> String {
    let d = l.get("delimiter").and_then(Value::as_str).unwrap_or("comma");
    let text = l.get("delimiter_text").and_then(Value::as_str).unwrap_or("");
    match d {
        "custom" => format!("「{text}」"),
        "regex" => format!("正規表現 {text}"),
        _ => label(&DELIMITERS, d).split('（').next().unwrap_or("").to_string(),
    }
}

/// layout_shape（「12列 / 66バイト」「12列 / カンマ区切り」）。
pub fn layout_shape(l: &Value) -> String {
    let n = columns(l).len();
    if mode(l) == "delimited" {
        return format!("{n}列 / {}区切り", delimiter_label(l));
    }
    let unit = if l.get("unit").and_then(Value::as_str) == Some("byte") { "バイト" } else { "文字" };
    format!("{n}列 / {}{unit}", layout_width(l))
}

/// 範囲の順に並べた列（同じ範囲は元の順。Python の sorted と同じ）。
fn sorted_columns(l: &Value) -> Vec<&Value> {
    let mut cols: Vec<&Value> = columns(l).iter().collect();
    cols.sort_by_key(|c| span(c, mode(l)));
    cols
}

/// layout_overlaps（重なっている列の名前の組）。
pub fn layout_overlaps(l: &Value) -> Vec<Value> {
    let cols = sorted_columns(l);
    cols.windows(2)
        .filter(|w| span(w[1], mode(l)).0 <= span(w[0], mode(l)).1)
        .map(|w| json!([w[0].get("name").cloned().unwrap_or(Value::Null), w[1].get("name").cloned().unwrap_or(Value::Null)]))
        .collect()
}

/// layout_gaps（どの列にも入らない範囲）。
pub fn layout_gaps(l: &Value) -> Vec<Value> {
    let mut out = Vec::new();
    let mut pos = 1i64;
    for c in sorted_columns(l) {
        let (start, end) = span(c, mode(l));
        if start > pos {
            out.push(json!([pos, start - 1]));
        }
        pos = pos.max(end + 1);
    }
    out
}

/// 対象のうち、この入力の種類でこのマスタを使っている物の名前（text_layout_usage・join_recipe_usage）。
fn usage(cfg: &Map<String, Value>, source: &str, key: &str, id: &Value) -> Vec<Value> {
    let id = pyish::strip(&pyish::text_or_empty(Some(id))).to_string();
    if id.is_empty() {
        return vec![];
    }
    jobs(cfg)
        .iter()
        .filter(|j| settings::job_source(&pyish::text_or_empty(j.get("source"))) == source && pyish::text_or_empty(j.get(key)) == id)
        .map(|j| j.get("name").cloned().unwrap_or(json!("")))
        .collect()
}

fn jobs(cfg: &Map<String, Value>) -> &[Value] {
    cfg.get("jobs").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

fn list<'a>(cfg: &'a Map<String, Value>, key: &str) -> &'a [Value] {
    cfg.get(key).and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

/// GET /api/text-layouts … 読取マスタの一覧（形・使っている対象・重なり・隙間）と、画面の選択肢。
pub(crate) fn get_text_layouts(core: &Core, _: &Ask, _: &[String]) -> Reply {
    let Ok(cfg) = config::read(core) else { return Reply::pass() };
    let items: Vec<Value> = list(&cfg, "text_layouts")
        .iter()
        .map(|x| {
            let mut x = x.clone();
            let extra = json!({
                "width": layout_width(&x), "shape": layout_shape(&x), "used_by": usage(&cfg, "text", "layout_id", &x["id"]),
                "overlaps": layout_overlaps(&x), "gaps": layout_gaps(&x),
            });
            if let (Value::Object(m), Value::Object(e)) = (&mut x, extra) {
                m.extend(e);
            }
            x
        })
        .collect();
    Reply::json(
        200,
        &json!({
            "ok": true, "items": items,
            "encodings": options(&ENCODINGS), "units": options(&UNITS), "modes": options(&MODES),
            "delimiters": options(&DELIMITERS), "quotes": options(&QUOTES), "trims": options(&TRIMS),
            "types": COLUMN_TYPES.iter().map(|(k, l, n)| json!({"value": k, "label": l, "note": n})).collect::<Vec<_>>(),
            "stamp_formats": STAMP_FORMAT_SAMPLES, "max_scale": MAX_SCALE,
            "date_format_default": DATE_FORMAT_DEFAULT, "datetime_format_default": DATETIME_FORMAT_DEFAULT,
            "type_formats": TYPE_FORMATS.iter().map(|(k, v)| (k.to_string(), json!(v))).collect::<Map<_, _>>(),
        }),
    )
}

/// GET /api/join-recipes … 結合マスタの一覧（使っている対象）と、画面の選択肢。
/// 「どちらも全部残す」（FULL OUTER JOIN）は SQLite 3.39 から書ける。結合を走らせる Python の SQLite もそれ以降
/// （Python 3.12 の配布物は 3.42 以降）として、いつも出す。
pub(crate) fn get_join_recipes(core: &Core, _: &Ask, _: &[String]) -> Reply {
    let Ok(cfg) = config::read(core) else { return Reply::pass() };
    let items: Vec<Value> = list(&cfg, "join_recipes")
        .iter()
        .map(|x| {
            let mut x = x.clone();
            let used = usage(&cfg, "join", "recipe_id", &x["id"]);
            if let Value::Object(m) = &mut x {
                m.insert("used_by".into(), Value::Array(used));
            }
            x
        })
        .collect();
    let layouts: Vec<Value> = list(&cfg, "text_layouts").iter().map(|l| json!({"id": l["id"], "name": l["name"]})).collect();
    Reply::json(
        200,
        &json!({
            "ok": true, "items": items, "max_sources": JOIN_MAX_SOURCES,
            "types": JOIN_TYPES.iter().map(|(k, l, n)| json!({"value": k, "label": l, "note": n})).collect::<Vec<_>>(),
            "formats": options(&SOURCE_FORMATS), "layouts": layouts,
        }),
    )
}

// ==== 書き出し ==============================================================

/// json.dumps(v, ensure_ascii=False, indent=1) と同じ字。
fn dumps_indent1(v: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    let mut ser = serde_json::Serializer::with_formatter(&mut out, serde_json::ser::PrettyFormatter::with_indent(b" "));
    let _ = serde::Serialize::serialize(v, &mut ser);
    out
}

/// ?ids=a,b（空でない物。前後の空白は落とさずに比べる。Python と同じ）。
fn wanted(ask: &Ask) -> Vec<String> {
    applog::query_arg(ask.query, "ids").unwrap_or_default().split(',').filter(|x| !pyish::strip(x).is_empty()).map(String::from).collect()
}

fn pick(items: &[Value], want: &[String]) -> Vec<Value> {
    items
        .iter()
        .filter(|x| want.is_empty() || want.iter().any(|w| x.get("id").and_then(Value::as_str) == Some(w.as_str())))
        .cloned()
        .collect()
}

/// ?format=（無ければ json。小文字にして比べる）。
fn format_arg(ask: &Ask) -> String {
    applog::query_arg(ask.query, "format").filter(|s| !s.is_empty()).unwrap_or_else(|| "json".into()).to_lowercase()
}

/// 持ち出しの JSON（kind・version・exported_at・count と、id〈と drop の鍵〉を除いた中身）。
fn export_doc(core: &Core, kind: &str, list_key: &str, items: &[Value], drop: &[&str]) -> Value {
    let body: Vec<Value> = items
        .iter()
        .map(|x| {
            let mut m = x.as_object().cloned().unwrap_or_default();
            for k in drop {
                m.shift_remove(*k);
            }
            Value::Object(m)
        })
        .collect();
    let mut doc = Map::new();
    doc.insert("kind".into(), json!(kind));
    doc.insert("version".into(), json!(1));
    doc.insert("exported_at".into(), json!(core.now().format("%Y-%m-%dT%H:%M:%S").to_string()));
    doc.insert("count".into(), json!(items.len()));
    doc.insert(list_key.into(), Value::Array(body));
    Value::Object(doc)
}

fn file_reply(body: Vec<u8>, content_type: &str, disposition: String) -> Reply {
    Reply { status: 200, headers: vec![("Content-Type".into(), content_type.into()), ("Content-Disposition".into(), disposition)], body }
}

/// 持ち出しの JSON を、もう一度整えてから出す（Python も書き出す前に normalize を通す）。
fn renormalize(items: &[Value], f: fn(&Map<String, Value>) -> R<Value>) -> R<Vec<Value>> {
    items.iter().map(|x| f(x.as_object().ok_or(Pass)?)).collect()
}

/// GET /api/text-layouts/export … 読取マスタの持ち出し（JSON）。EXCEL は Python へ回す。
pub(crate) fn get_text_layouts_export(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    if format_arg(ask) == "xlsx" {
        return Reply::pass();
    }
    let Ok(cfg) = config::read(core) else { return Reply::pass() };
    let Ok(items) = renormalize(&pick(list(&cfg, "text_layouts"), &wanted(ask)), config::normalize_layout) else { return Reply::pass() };
    let stamp = core.now().format("%Y%m%d_%H%M%S");
    let name = format!("text-layouts-{stamp}.json");
    core.log(&format!("TEXT_LAYOUT_EXPORT format=json count={} file={name}", items.len()));
    file_reply(
        dumps_indent1(&export_doc(core, LAYOUT_EXPORT_KIND, "layouts", &items, &["id"])),
        "application/json; charset=utf-8",
        format!("attachment; filename=\"{name}\""),
    )
}

/// GET /api/join-recipes/export … 結合マスタの持ち出し（JSON）。EXCEL は Python へ回す。
pub(crate) fn get_join_recipes_export(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    if format_arg(ask) == "xlsx" {
        return Reply::pass();
    }
    let Ok(cfg) = config::read(core) else { return Reply::pass() };
    let Ok(items) = renormalize(&pick(list(&cfg, "join_recipes"), &wanted(ask)), config::normalize_recipe) else { return Reply::pass() };
    let stamp = core.now().format("%Y%m%d_%H%M%S");
    let name = format!("join-recipes-{stamp}.json");
    core.log(&format!("JOIN_RECIPE_EXPORT format=json count={} file={name}", items.len()));
    file_reply(
        dumps_indent1(&export_doc(core, RECIPE_EXPORT_KIND, "recipes", &items, &["id"])),
        "application/json; charset=utf-8",
        format!("attachment; filename=\"{name}\""),
    )
}

/// GET /api/m-queries/export … クエリの持ち出し（JSON。1件で format=m なら式そのもの .pq）。
pub(crate) fn get_m_queries_export(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    let Ok(cfg) = config::read(core) else { return Reply::pass() };
    let items = pick(list(&cfg, "m_queries"), &wanted(ask));
    let (name, body, ctype) = if format_arg(ask) == "m" && items.len() == 1 {
        let code = items[0].get("code").and_then(Value::as_str).unwrap_or("").as_bytes().to_vec();
        (format!("{}.pq", safe_file_label(&pyish::text_or_empty(items[0].get("name")), 60)), code, "text/plain; charset=utf-8")
    } else {
        let items: Vec<Value> = items.iter().filter_map(|x| x.as_object().map(config::normalize_query)).collect();
        let doc = export_doc(core, QUERY_EXPORT_KIND, "queries", &items, &["id", "updated_at"]);
        (format!("m-queries-{}.json", core.now().format("%Y%m%d_%H%M%S")), dumps_indent1(&doc), "application/json; charset=utf-8")
    };
    core.log(&format!("M_QUERY_EXPORT count={} file={name}", items.len()));
    file_reply(body, ctype, format!("attachment; filename*=UTF-8''{}", url_quote(&name)))
}

/// navi_web._safe_file_label（制御文字は空白、ファイル名に使えない字は _、続く空白は1つ、limit 字まで。空なら「登録内容」）。
pub fn safe_file_label(v: &str, limit: usize) -> String {
    let t: String = v
        .chars()
        .map(|c| match c {
            '\0'..='\x1f' | '\x7f' => ' ',
            '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            c => c,
        })
        .collect();
    let joined = t.split(pyish::is_space).filter(|x| !x.is_empty()).collect::<Vec<_>>().join(" ");
    let out = pyish::head(&joined, limit);
    if out.is_empty() {
        "登録内容".into()
    } else {
        out
    }
}

/// urllib.parse.quote（英数字と _.-~ と / はそのまま、ほかは UTF-8 の %XX）。
pub fn url_quote(s: &str) -> String {
    s.bytes()
        .map(|b| if b.is_ascii_alphanumeric() || b"_.-~/".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shapes_like_python() {
        let l = json!({"mode": "fixed", "unit": "byte", "columns": [
            {"name": "a", "start": 1, "end": 4}, {"name": "b", "start": 3, "end": 5}, {"name": "c", "start": 9, "end": 10}]});
        assert_eq!(layout_width(&l), 10);
        assert_eq!(layout_shape(&l), "3列 / 10バイト");
        assert_eq!(layout_overlaps(&l), vec![json!(["a", "b"])]);
        assert_eq!(layout_gaps(&l), vec![json!([6, 8])]);
        let d = json!({"mode": "delimited", "delimiter": "custom", "delimiter_text": "|", "columns": [{"field": 2}]});
        assert_eq!(layout_shape(&d), "1列 / 「|」区切り");
        assert_eq!(layout_gaps(&d), vec![json!([1, 1])]);
    }

    #[test]
    fn file_names_like_python() {
        assert_eq!(safe_file_label("a/b:\n  c\u{3000}d", 60), "a_b_ c d");
        assert_eq!(safe_file_label(" \t", 60), "登録内容");
        assert_eq!(url_quote("月次 クエリ.pq"), "%E6%9C%88%E6%AC%A1%20%E3%82%AF%E3%82%A8%E3%83%AA.pq");
        assert_eq!(
            String::from_utf8(dumps_indent1(&json!({"a": [1, {}], "b": []}))).unwrap(),
            "{\n \"a\": [\n  1,\n  {}\n ],\n \"b\": []\n}"
        );
    }
}
