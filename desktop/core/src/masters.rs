//! 読取マスタ・結合マスタ・クエリの一覧と書き出し（2.20.0〜）。lib/navi_web.py の受け口と同じ答えを返す。
//!
//! 読むのは設定の写し（config::read。写しを替える場合・Python でしか同じに読めない値は Python へ回す）。
//! 書き出しの EXCEL（navi_book）と、クエリの一覧（M の式を読んで中のクエリ名を出す）は、まだ Python が受け持つ
//! （EXCEL は出力の段、M の式は Power Query の段で移す）。
//!
//! 画面の選択肢の言葉（下の表）は Python の navi_text・navi_output・navi_join と同じ字にする（tests/test_rust_masters.py が比べる）。

use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{applog, pyish, routes::Core, settings, writer};
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

// ==== 保存と削除（2.23.0〜） ================================================
//
// app の save_text_layout・save_join_recipe・delete_text_layout・delete_join_recipe・delete_m_query と同じに書く。
// どれも設定の版は進めない（マスタは版の外。Python も _mark_settings_dirty と裏の書き戻しだけ）。
// クエリの保存は M の式を読んで確かめる（navi_m）ので、Power Query の段まで Python が受け持つ。

/// navi_text._stamp_plan の役割だけ（YYYY/YY/MM/DD/HH/MI(NN)/SS を順に拾う。ほかの字は区切り）。→ (役割, 桁数)。
fn stamp_plan(pattern: &str) -> Vec<(Option<char>, usize)> {
    const TOKENS: [(&str, char); 8] =
        [("YYYY", 'Y'), ("YY", 'y'), ("MM", 'M'), ("DD", 'D'), ("HH", 'h'), ("MI", 'm'), ("NN", 'm'), ("SS", 's')];
    let p: Vec<char> = pattern.chars().collect();
    let (mut plan, mut i, mut seen_hour) = (Vec::new(), 0, false);
    while i < p.len() {
        let hit = TOKENS.iter().find(|(t, _)| p[i..].starts_with(&t.chars().collect::<Vec<_>>()));
        match hit {
            Some((tok, role)) => {
                // 時より後ろの MM は分（YYYYMMDDHHMMSS をそのまま書けるように）
                let role = if *tok == "MM" && seen_hour { 'm' } else { *role };
                if role == 'h' {
                    seen_hour = true;
                }
                plan.push((Some(role), tok.len()));
                i += tok.len();
            }
            None => {
                plan.push((None, 1));
                i += 1;
            }
        }
    }
    plan
}

/// f'{n:,}'（3 桁ごとのカンマ）。
fn grouped(n: usize) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

/// 重なっている名前（出てきた順、5 つまで）を「、」でつなぐ。無ければ None。
fn dupes<'a>(names: impl Iterator<Item = &'a str>) -> Option<String> {
    let mut seen: Vec<(&str, usize)> = Vec::new();
    for n in names {
        match seen.iter_mut().find(|(k, _)| *k == n) {
            Some((_, c)) => *c += 1,
            None => seen.push((n, 1)),
        }
    }
    let d: Vec<&str> = seen.iter().filter(|(_, c)| *c > 1).map(|(k, _)| *k).take(5).collect();
    (!d.is_empty()).then(|| d.join("、"))
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or("")
}

/// navi_text.validate_layout（整えた読取マスタを、このままでは使えない理由）。正規表現の区切りは Python の re で確かめるので Pass。
fn validate_layout(l: &Value) -> R<Vec<String>> {
    let mut bad = Vec::new();
    let cols = columns(l);
    if s(&l["name"]).is_empty() {
        bad.push("マスタ名を入れてください".to_string());
    }
    if cols.is_empty() {
        bad.push("列を1つ以上決めてください".into());
    }
    if cols.len() > 4096 {
        bad.push(format!("列が多すぎます（{}本）。{}本までにしてください", grouped(cols.len()), grouped(4096)));
    }
    if mode(l) == "delimited" {
        let (delim, text) = (s(&l["delimiter"]), s(&l["delimiter_text"]));
        if (delim == "custom" || delim == "regex") && text.is_empty() {
            bad.push(
                if delim == "custom" {
                    "区切りの文字を入れてください"
                } else {
                    "区切りの決まり（正規表現）を入れてください"
                }
                .into(),
            );
        } else if delim == "regex" {
            return Err(Pass);
        }
    }
    for (i, c) in cols.iter().enumerate() {
        let (i, name) = (i + 1, s(&c["name"]));
        let length = c["length"].as_i64().unwrap_or(0);
        if mode(l) == "fixed" && length < 1 {
            bad.push(format!("{i}番目「{name}」の長さが0です。長さか終了位置を入れてください"));
        }
        let t = s(&c["type"]);
        if t == "date" || t == "datetime" {
            let fmt = s(&c["format"]);
            let plan = stamp_plan(fmt);
            let roles: Vec<char> = plan.iter().filter_map(|(r, _)| *r).collect();
            if roles.is_empty() {
                bad.push(format!("{i}番目「{name}」の書式が空です（例 {DATE_FORMAT_DEFAULT}）"));
            } else if !roles.contains(&'Y') && !roles.contains(&'y') {
                bad.push(format!("{i}番目「{name}」の書式に年がありません（YYYY か YY を入れてください）: {fmt}"));
            } else if t == "datetime" && !roles.iter().any(|r| matches!(r, 'h' | 'm' | 's')) {
                bad.push(format!("{i}番目「{name}」は日時ですが、書式に時刻がありません（HH・MM・SS）: {fmt}"));
            } else if mode(l) == "fixed" {
                let need: usize = plan.iter().map(|(_, n)| n).sum();
                if need as i64 > length {
                    bad.push(format!("{i}番目「{name}」の書式は{need}桁必要ですが、切り出す長さが{length}しかありません"));
                }
            }
        }
    }
    if let Some(d) = dupes(cols.iter().map(|c| s(&c["name"]))) {
        bad.push(format!("同じ名前の列があります（{d}）。列名は重ならないようにしてください"));
    }
    Ok(bad)
}

/// navi_join.validate_recipe。「どちらも全部残す」は Python の SQLite が書けるかで決まるので Pass。
fn validate_recipe(r: &Value) -> R<Vec<String>> {
    let mut bad = Vec::new();
    let arr = |k: &str| r[k].as_array().map(Vec::as_slice).unwrap_or(&[]);
    if s(&r["name"]).is_empty() {
        bad.push("結合マスタ名を入れてください".to_string());
    }
    if arr("sources").len() < 2 {
        bad.push("ファイルを2つ以上選んでください（結合するものが1つでは繋げません）".into());
    }
    for (i, x) in arr("sources").iter().enumerate() {
        if s(&x["path"]).is_empty() {
            bad.push(format!("{}つ目のファイルの場所を入れてください", i + 1));
        }
        if s(&x["format"]) == "fixed" && s(&x["layout_id"]).is_empty() {
            bad.push(format!("{}つ目は固定長テキストです。読取マスタを選んでください", i + 1));
        }
    }
    for (i, j) in arr("joins").iter().enumerate() {
        let keys = j["keys"].as_array().map(Vec::as_slice).unwrap_or(&[]);
        if !keys.iter().any(|k| !s(&k["left"]).is_empty() && !s(&k["right"]).is_empty()) {
            bad.push(format!("{}つ目のつなぎ目に、突き合わせる列（キー）を1組以上決めてください", i + 1));
        }
        if s(&j["type"]) == "full" {
            return Err(Pass);
        }
    }
    let outs = arr("columns").iter().map(|c| if s(&c["as"]).is_empty() { s(&c["name"]) } else { s(&c["as"]) });
    if let Some(d) = dupes(outs) {
        bad.push(format!("出す列の名前が重なっています（{d}）。別名を付けてください"));
    }
    Ok(bad)
}

/// request.get_json(force=True) or {} を辞書として（辞書でない真の値は Python が落ちる）。
fn body_dict(ask: &Ask) -> R<Map<String, Value>> {
    match writer::body_json(ask, true)? {
        Some(Value::Object(m)) => Ok(m),
        Some(v) if pyish::truthy(&v) => Err(Pass),
        _ => Ok(Map::new()),
    }
}

type Sql = rusqlite::types::Value;

fn text(v: impl Into<String>) -> Sql {
    Sql::Text(v.into())
}

/// 1件を登録・更新する（INSERT OR REPLACE。並び順は、あれば元のまま、無ければ末尾）。
/// row は (id, 並び順, 更新時刻) から列の値を、列の並び（cols）どおりに組む。line は記録の1行（id を受ける）。→ (id, 更新時刻)。
fn upsert(
    core: &Core,
    table: &str,
    id: &str,
    cols: &str,
    row: impl FnOnce(&str, Sql, &str) -> Vec<Sql>,
    line: impl FnOnce(&str) -> String,
) -> R<(String, String)> {
    let id = if id.is_empty() { uuid::Uuid::new_v4().to_string() } else { id.to_string() };
    let now = writer::stamp(core);
    writer::transact(core, |tx, log| {
        let order: Sql =
            tx.query_row(&format!("SELECT COALESCE(MAX(display_order),-1)+1 n FROM {table}"), [], |r| r.get(0)).map_err(|_| Pass)?;
        let cur: Option<Sql> = match tx.query_row(&format!("SELECT display_order FROM {table} WHERE id=?"), [&id], |r| r.get(0)) {
            Ok(v) => Some(v),
            Err(rusqlite::Error::QueryReturnedNoRows) => None,
            Err(_) => return Err(Pass),
        };
        let params = row(&id, cur.unwrap_or(order), &now);
        let marks = vec!["?"; params.len()].join(",");
        tx.execute(&format!("INSERT OR REPLACE INTO {table} ({cols}) VALUES({marks})"), rusqlite::params_from_iter(params))
            .map_err(|_| Pass)?;
        log.push(line(&id));
        Ok(())
    })?;
    writer::flush_soon(core, if table == "text_layouts" { "text-layout-save" } else { "join-recipe-save" });
    Ok((id, now))
}

fn refused(bad: &[String]) -> Reply {
    Reply::json(400, &json!({"ok": false, "error": bad.join("／")}))
}

/// 整えた1件に id と更新時刻を入れる（dict(l, id=…, updated_at=…)）。
fn stamped(mut v: Value, id: &str, now: &str) -> Value {
    if let Value::Object(m) = &mut v {
        m.insert("id".into(), json!(id));
        m.insert("updated_at".into(), json!(now));
    }
    v
}

/// POST /api/text-layouts … 読取マスタ1件を登録・更新する（id が無ければ新規）。
pub(crate) fn post_text_layout(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_save_layout(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_save_layout(core: &Core, ask: &Ask) -> R<Reply> {
    let l = config::normalize_layout(&body_dict(ask)?)?;
    let bad = validate_layout(&l)?;
    if !bad.is_empty() {
        return Ok(refused(&bad));
    }
    let cols = columns(&l);
    let parse: Map<String, Value> =
        ["mode", "delimiter", "delimiter_text", "quote", "collapse"].iter().map(|k| (k.to_string(), l[*k].clone())).collect();
    let int = |k: &str| Sql::Integer(l[k].as_i64().unwrap_or(0));
    let flag = |k: &str| Sql::Integer(i64::from(l[k] == json!(true)));
    let line = |id: &str| {
        format!(
            "TEXT_LAYOUT_SAVE id={id} name={} 読み方={} 列={} 単位={} 文字コード={} 幅={}",
            s(&l["name"]),
            mode(&l),
            cols.len(),
            s(&l["unit"]),
            s(&l["encoding"]),
            layout_width(&l)
        )
    };
    let (id, now) = upsert(
        core,
        "text_layouts",
        s(&l["id"]),
        "id,display_order,name,description,encoding,unit,trim,skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at,parse_json",
        |id, order, now| {
            vec![
                text(id),
                order,
                text(s(&l["name"])),
                text(s(&l["description"])),
                text(s(&l["encoding"])),
                text(s(&l["unit"])),
                text(s(&l["trim"])),
                int("skip_head"),
                int("skip_tail"),
                flag("skip_blank"),
                flag("header_row"),
                text(writer::py_dumps(&l["columns"])),
                text(s(&l["sample_path"])),
                text(now),
                text(writer::py_dumps(&Value::Object(parse.clone()))),
            ]
        },
        line,
    )?;
    let mut saved = stamped(l.clone(), &id, &now);
    let extra = json!({"width": layout_width(&saved), "shape": layout_shape(&saved)});
    if let (Value::Object(m), Value::Object(e)) = (&mut saved, extra) {
        m.extend(e);
    }
    Ok(Reply::json(200, &json!({"ok": true, "layout": saved})))
}

/// POST /api/join-recipes … 結合マスタ1件を登録・更新する（id が無ければ新規）。
pub(crate) fn post_join_recipe(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_save_recipe(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_save_recipe(core: &Core, ask: &Ask) -> R<Reply> {
    let r = config::normalize_recipe(&body_dict(ask)?)?;
    let bad = validate_recipe(&r)?;
    if !bad.is_empty() {
        return Ok(refused(&bad));
    }
    let n = |k: &str| r[k].as_array().map(Vec::len).unwrap_or(0);
    let line = |id: &str| {
        let cols = n("columns");
        format!(
            "JOIN_RECIPE_SAVE id={id} name={} ファイル={} つなぎ目={} 出す列={}",
            s(&r["name"]),
            n("sources"),
            n("joins"),
            if cols == 0 { "（自動）".to_string() } else { cols.to_string() }
        )
    };
    let (id, now) = upsert(
        core,
        "join_recipes",
        s(&r["id"]),
        "id,display_order,name,description,sources_json,joins_json,columns_json,updated_at",
        |id, order, now| {
            vec![
                text(id),
                order,
                text(s(&r["name"])),
                text(s(&r["description"])),
                text(writer::py_dumps(&r["sources"])),
                text(writer::py_dumps(&r["joins"])),
                text(writer::py_dumps(&r["columns"])),
                text(now),
            ]
        },
        line,
    )?;
    Ok(Reply::json(200, &json!({"ok": true, "recipe": stamped(r.clone(), &id, &now)})))
}

/// navi_mrun.m_query_usage（入力に使う対象と、後処理に使う対象の両方）。
fn query_usage(cfg: &Map<String, Value>, qid: &str) -> R<Vec<Value>> {
    if qid.is_empty() {
        return Ok(vec![]);
    }
    let mut out = Vec::new();
    for j in jobs(cfg) {
        let as_input =
            settings::job_source(&pyish::text_or_empty(j.get("source"))) == "mquery" && pyish::text_or_empty(j.get("query_id")) == qid;
        let post = config::normalize_post(j.get("post").unwrap_or(&Value::Null))?;
        if as_input || (post["mode"] == json!("query") && post["query_id"] == json!(qid)) {
            out.push(j.get("name").cloned().unwrap_or(json!("")));
        }
    }
    Ok(out)
}

/// 削除の共通（使っている対象があるうちは消さない → 409。無ければ ok=false の 200）。
fn delete_one(core: &Core, raw_id: &str, what: &Kind) -> R<Reply> {
    let id = pyish::strip(raw_id).to_string();
    let gone = writer::transact(core, |tx, log| {
        let cfg = config::load(core, tx)?;
        let used = match what.table {
            "text_layouts" => usage(&cfg, "text", "layout_id", &json!(id)),
            "join_recipes" => usage(&cfg, "join", "recipe_id", &json!(id)),
            _ => query_usage(&cfg, &id)?,
        };
        if !used.is_empty() {
            let names: Vec<String> = used.iter().take(3).map(pyish::py_str).collect();
            return Ok(Err(format!(
                "この{}は{}件の対象が使っています（{}）。先に対象側を切り替えてください",
                what.label,
                used.len(),
                names.join("、")
            )));
        }
        let n = tx.execute(&format!("DELETE FROM {} WHERE id=?", what.table), [&id]).map_err(|_| Pass)?;
        log.push(format!("{} id={id} deleted={n}", what.log));
        Ok(Ok(n > 0))
    })?;
    let gone = match gone {
        Err(msg) => return Ok(Reply::json(409, &json!({"ok": false, "error": msg}))),
        Ok(g) => g,
    };
    writer::flush_soon(core, what.reason);
    Ok(Reply::json(200, &json!({"ok": gone, "error": if gone { String::new() } else { format!("その{}はありません", what.label) }})))
}

struct Kind {
    table: &'static str,
    label: &'static str,
    log: &'static str,
    reason: &'static str,
}

const LAYOUT: Kind = Kind { table: "text_layouts", label: "読取マスタ", log: "TEXT_LAYOUT_DELETE", reason: "text-layout-delete" };
const RECIPE: Kind = Kind { table: "join_recipes", label: "結合マスタ", log: "JOIN_RECIPE_DELETE", reason: "join-recipe-delete" };
const QUERY: Kind = Kind { table: "m_queries", label: "クエリ", log: "M_QUERY_DELETE", reason: "m-query-delete" };

/// DELETE /api/text-layouts/<layout_id>
pub(crate) fn delete_text_layout(core: &Core, _: &Ask, p: &[String]) -> Reply {
    delete_one(core, &p[0], &LAYOUT).unwrap_or_else(|_| Reply::pass())
}

/// DELETE /api/join-recipes/<recipe_id>
pub(crate) fn delete_join_recipe(core: &Core, _: &Ask, p: &[String]) -> Reply {
    delete_one(core, &p[0], &RECIPE).unwrap_or_else(|_| Reply::pass())
}

/// DELETE /api/m-queries/<query_id>
pub(crate) fn delete_m_query(core: &Core, _: &Ask, p: &[String]) -> Reply {
    delete_one(core, &p[0], &QUERY).unwrap_or_else(|_| Reply::pass())
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
