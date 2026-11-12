//! 結合の組み立ての下読みと、キーの見当付け（2.31.0〜）。lib/navi_join.py（read_source・load_sources・build_sql・join_stats・
//! run_recipe・preview_recipe・suggest_keys）と、lib/navi_joinrun.py（sampled_recipe・join_reader）、lib/navi_web.py の
//! join_keys_route・join_preview_route と同じ答えを返す。
//!
//!   - POST /api/join-keys    … つなぎ目1つぶんのキーの見当（実データの値の重なりで探し、強い順に）
//!   - POST /api/join-preview … 繋いだ結果と、つなぎ目ごとの一致の数（メモリ上の SQLite で、Python と同じ SQL を流す）
//!
//! 組み立てのあいだは、材料を手元の写し（localcopy::sample）から読む。本番の実行はこの道を通らない（写しは先頭だけのことがある）。
//! EXCEL・ACCESS の材料、「どちらも全部残す」（FULL OUTER JOIN。使えるかは Python の SQLite の版で決まる）は Python へ回す。
use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::paths::{self, Bases};
use crate::viewer::ReadFail;
use crate::{joinplan, localcopy, naming, pyish, routes::Core, textread, writer};
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};

type R<T> = Result<T, Pass>;

/// 下読みで各ファイルから読む行の上限（preview_recipe の source_limit）と、キーの見当に使う行の上限（KEY_SAMPLE_ROWS）。
const SOURCE_LIMIT: usize = 2000;
const KEY_SAMPLE_ROWS: usize = 2000;
const KEY_MAX_DISTINCT: usize = 4000;
const KEY_MIN_SCORE: f64 = 0.30;

/// 読めなかった理由。Message は Python の例外の文（画面へ出す）。
enum Fail {
    Message(String),
    Pass,
}

impl From<Pass> for Fail {
    fn from(_: Pass) -> Self {
        Fail::Pass
    }
}

type F<T> = Result<T, Fail>;

fn msg<T>(m: impl Into<String>) -> F<T> {
    Err(Fail::Message(m.into()))
}

/// SQLite の失敗の文（Python の str(sqlite3.Error) と同じ sqlite3_errmsg）。それ以外の失敗は Python へ回す。
fn sql_fail(e: rusqlite::Error) -> Fail {
    match e {
        rusqlite::Error::SqliteFailure(_, Some(m)) => Fail::Message(m),
        _ => Fail::Pass,
    }
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or("")
}

fn qi(name: &str) -> String {
    format!("\"{}\"", name.replace('"', "\"\""))
}

fn text_folder(c: &Map<String, Value>) -> String {
    naming::text_or(c.get("text_folder"), config::TEXT_FOLDER_DEFAULT)
}

fn is_file(p: &str) -> bool {
    std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
}

/// Rust で読めない材料（EXCEL・ACCESS）か。
fn foreign(src: &Value) -> bool {
    matches!(s(&src["format"]), "xlsx" | "accdb")
}

// ==== 組み立て中だけ、手元の写しを読む =======================================

/// sampled_recipe（各ファイルの場所を手元の写しへ差し替えた取り決めと、ファイルごとの内訳）。
fn sampled_recipe(core: &Core, b: &Bases, recipe: &Value, c: &Map<String, Value>) -> R<(Value, Vec<Value>)> {
    let mut r = recipe.clone();
    let mut out = Vec::new();
    let log = |m: &str| core.log(m);
    for src in r["sources"].as_array_mut().into_iter().flatten() {
        let raw = s(&src["path"]).to_string();
        let mut info = json!({"alias": src["alias"], "path": raw, "ok": false, "note": ""});
        let path = joinplan::join_path(b, c, &json!(raw));
        if !raw.is_empty() && is_file(&path) {
            let got = localcopy::sample(&path, s(&src["format"]), &log).map_err(|_| Pass)?;
            for k in ["ok", "mode", "bytes", "total", "elapsed", "cached", "note"] {
                info[k] = got.info.get(k).cloned().unwrap_or(Value::Null);
            }
            if let Some(local) = got.path {
                // 名前は元のまま持たせる（件数の内訳も画面の見出しも、写しの名前で出さない）
                if s(&src["name"]).is_empty() {
                    src["name"] = json!(paths::py_name(&raw));
                }
                src["path"] = json!(local);
            }
        } else {
            info["note"] = json!(if raw.is_empty() { "ファイルが決まっていません" } else { "ファイルがありません" });
        }
        out.push(info);
    }
    Ok((r, out))
}

// ==== 読み込み ==============================================================

/// read_source（1つのファイルを (見出し, 本体) で読む。CSV・TXT・SQLite3 はデータビュワーと同じ読み手、固定長は読取マスタ）。
fn read_source(b: &Bases, c: &Map<String, Value>, src: &Value, limit: usize) -> F<textread::Table> {
    let alias = s(&src["alias"]);
    let raw = s(&src["path"]);
    if s(&src["format"]) == "fixed" {
        let lid = s(&src["layout_id"]);
        let lay = c
            .get("text_layouts")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .find(|x| x.get("id").and_then(Value::as_str) == Some(lid));
        let Some(Value::Object(lay)) = lay else { return msg(format!("{alias}: 読取マスタが見つかりません")) };
        // Python は道をそのまま開く（相対なら Python の今いるフォルダーから）。手元の写し・絶対の道だけ Rust で読む
        if !paths::is_absolute(raw) || !is_file(raw) {
            return Err(Fail::Pass);
        }
        let l = config::normalize_layout(lay)?;
        return textread::text_rows(raw, &l, limit).map_err(|e| match e {
            Ok(m) => Fail::Message(m),
            Err(_) => Fail::Pass,
        });
    }
    let path = joinplan::join_path(b, c, &json!(raw));
    if !is_file(&path) {
        return msg(b.missing_message(&format!("{alias}: ファイル"), raw, Some(&text_folder(c))));
    }
    let fmt = naming::normalize_output_format(Some(&src["format"]), Some(&json!(paths::py_name(&path))));
    let job = Map::from_iter([("table".to_string(), json!(s(&src["table"])))]);
    let read = match fmt {
        "sqlite3" => crate::viewer::read_sqlite(&path, &job, limit)?,
        "csv" | "txt" => {
            let m = std::fs::metadata(&path).map_err(|_| Pass)?;
            if m.len() > 64 << 20 {
                return Err(Fail::Pass); // 大きなファイルは丸ごと読まない（Python へ回す）
            }
            crate::viewer::read_text_table(&std::fs::read(&path).map_err(|_| Pass)?, fmt, limit)?
        }
        _ => return Err(Fail::Pass),
    };
    match read {
        Ok(d) => {
            let n = d.headers.len();
            Ok((d.headers, d.rows.into_iter().map(|r| r.into_iter().take(n).collect()).collect()))
        }
        Err(ReadFail::Message(m)) => msg(m),
    }
}

/// 読み込んだ材料1つ（load_sources の meta）。
struct Meta {
    alias: String,
    table: String,
    columns: Vec<String>,
    rows: usize,
    format: String,
    name: String,
}

/// load_sources（全部のファイルをメモリ上の DB へ置く）。
fn load_sources(b: &Bases, c: &Map<String, Value>, recipe: &Value, limit: usize) -> F<(rusqlite::Connection, Vec<Meta>)> {
    let conn = rusqlite::Connection::open_in_memory().map_err(|_| Pass)?;
    let mut meta = Vec::new();
    for src in recipe["sources"].as_array().into_iter().flatten() {
        let (headers, rows) = read_source(b, c, src, limit)?;
        let alias = s(&src["alias"]).to_string();
        let path = s(&src["path"]);
        if headers.is_empty() {
            return msg(format!("{alias}（{}）に列がありません", paths::py_name(path)));
        }
        // 同じ名前の列は、後ろに番号を足して区別する
        let mut seen: HashMap<String, usize> = HashMap::new();
        let mut cols: Vec<String> = Vec::new();
        for h in headers {
            let mut h = if h.is_empty() { format!("列{}", cols.len() + 1) } else { h };
            match seen.get_mut(&h) {
                Some(n) => {
                    *n += 1;
                    h = format!("{h}_{n}");
                }
                None => {
                    seen.insert(h.clone(), 1);
                }
            }
            cols.push(h);
        }
        let t = format!("t_{alias}");
        let defs: Vec<String> = cols.iter().map(|x| format!("{} TEXT", qi(x))).collect();
        conn.execute(&format!("CREATE TABLE {} ({})", qi(&t), defs.join(",")), []).map_err(sql_fail)?;
        {
            let marks = vec!["?"; cols.len()].join(",");
            let tx = conn.unchecked_transaction().map_err(sql_fail)?;
            {
                let mut st = tx.prepare(&format!("INSERT INTO {} VALUES({marks})", qi(&t))).map_err(sql_fail)?;
                for row in &rows {
                    let vals: Vec<&str> = (0..cols.len()).map(|i| row.get(i).map(String::as_str).unwrap_or("")).collect();
                    st.execute(rusqlite::params_from_iter(vals)).map_err(sql_fail)?;
                }
            }
            tx.commit().map_err(sql_fail)?;
        }
        let name = if s(&src["name"]).is_empty() { paths::py_name(path) } else { s(&src["name"]).to_string() };
        meta.push(Meta { alias, table: t, columns: cols, rows: rows.len(), format: s(&src["format"]).to_string(), name });
    }
    Ok((conn, meta))
}

/// build_sql（組み立てた SELECT 文と、出す列の名前）。
fn build_sql(recipe: &Value, meta: &[Meta], limit: Option<usize>) -> F<(String, Vec<String>)> {
    let auto: Vec<Value>;
    let mut cols = recipe["columns"].as_array().map(Vec::as_slice).unwrap_or(&[]);
    if cols.is_empty() {
        // 出す列を決めていないときの既定（1つ目の全部と、2つ目以降の「まだ無い名前」）
        let mut used: HashSet<&str> = HashSet::new();
        auto = meta
            .iter()
            .flat_map(|m| m.columns.iter().map(move |c| (m, c)))
            .filter(|(_, c)| used.insert(c.as_str()))
            .map(|(m, c)| json!({"source": m.alias, "name": c, "as": ""}))
            .collect();
        cols = &auto;
    }
    let (mut select, mut names) = (Vec::new(), Vec::new());
    for c in cols {
        let m = meta.iter().find(|m| m.alias == s(&c["source"])).unwrap_or(&meta[0]);
        let name = s(&c["name"]);
        if !m.columns.iter().any(|x| x == name) {
            continue;
        }
        let out = if s(&c["as"]).is_empty() { name } else { s(&c["as"]) };
        select.push(format!("{}.{} AS {}", qi(&m.table), qi(name), qi(out)));
        names.push(out.to_string());
    }
    if select.is_empty() {
        return msg("出す列が1つもありません");
    }
    let mut sql = vec![format!("SELECT {}", select.join(", ")), format!("FROM {}", qi(&meta[0].table))];
    for (i, j) in recipe["joins"].as_array().into_iter().flatten().enumerate() {
        let (left, right) = (&meta[i], &meta[i + 1]);
        let mut on = Vec::new();
        for k in j["keys"].as_array().into_iter().flatten() {
            let (kl, kr) = (s(&k["left"]), s(&k["right"]));
            if kl.is_empty() || kr.is_empty() {
                continue;
            }
            // 左のキーは「そこまでの鎖のどこか」に在る。後ろから探す
            let lt = meta[..=i].iter().rev().find(|m| m.columns.iter().any(|x| x == kl)).unwrap_or(left);
            on.push(format!("{}.{} = {}.{}", qi(&lt.table), qi(kl), qi(&right.table), qi(kr)));
        }
        if on.is_empty() {
            return msg(format!("{}つ目のつなぎ目にキーがありません", i + 1));
        }
        let kind = match s(&j["type"]) {
            "left" => "LEFT JOIN",
            "full" => "FULL OUTER JOIN",
            _ => "INNER JOIN",
        };
        sql.push(format!("{kind} {} ON {}", qi(&right.table), on.join(" AND ")));
    }
    if let Some(n) = limit {
        sql.push(format!("LIMIT {n}"));
    }
    Ok((sql.join("\n"), names))
}

/// join_stats（つなぎ目ごとに、何件合ったか。数えられなければ null）。
fn join_stats(conn: &rusqlite::Connection, recipe: &Value, meta: &[Meta]) -> Vec<Value> {
    let mut out = Vec::new();
    for (i, j) in recipe["joins"].as_array().into_iter().flatten().enumerate() {
        let (left, right) = (&meta[i], &meta[i + 1]);
        let keys: Vec<(&str, &str)> = j["keys"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|k| (s(&k["left"]), s(&k["right"])))
            .filter(|(l, r)| !l.is_empty() && !r.is_empty())
            .collect();
        if keys.is_empty() {
            out.push(json!({"index": i, "ok": false, "why": "キーが決まっていません"}));
            continue;
        }
        let (lt, rt) = (qi(&left.table), qi(&right.table));
        let on: Vec<String> = keys.iter().map(|(l, r)| format!("{lt}.{} = {rt}.{}", qi(l), qi(r))).collect();
        let on = on.join(" AND ");
        let one = |sql: String| conn.query_row(&sql, [], |r| r.get::<_, i64>(0)).ok();
        let both = one(format!("SELECT COUNT(*) FROM {lt} WHERE EXISTS(SELECT 1 FROM {rt} WHERE {on})"));
        let lonly = one(format!("SELECT COUNT(*) FROM {lt} WHERE NOT EXISTS(SELECT 1 FROM {rt} WHERE {on})"));
        let ronly = one(format!("SELECT COUNT(*) FROM {rt} WHERE NOT EXISTS(SELECT 1 FROM {lt} WHERE {on})"));
        let paired = one(format!("SELECT COUNT(*) FROM {lt} INNER JOIN {rt} ON {on}"));
        let note = match (both, paired) {
            (Some(0), _) => "キーが1組も一致していません。突き合わせる列が合っているか確かめてください".to_string(),
            (Some(b), Some(p)) if p > b => format!("右に同じキーが複数あるため、行が{p}件へ増えます（左は{b}件）"),
            _ => String::new(),
        };
        out.push(json!({"index": i, "ok": both.is_some_and(|b| b != 0), "type": j["type"], "left": left.name, "right": right.name,
                        "left_rows": left.rows, "right_rows": right.rows, "both": both, "left_only": lonly, "right_only": ronly,
                        "paired": paired, "why": note}));
    }
    out
}

/// 1列ぶんの値（NULL は空。TEXT の列なので字のほかは来ない）。
fn cell(v: rusqlite::types::ValueRef) -> F<String> {
    use rusqlite::types::ValueRef::*;
    match v {
        Null => Ok(String::new()),
        Text(t) => std::str::from_utf8(t).map(String::from).map_err(|_| Fail::Pass),
        _ => Err(Fail::Pass),
    }
}

/// run_recipe（結合して (見出し, 本体, 内訳)）。
fn run_recipe(
    b: &Bases,
    c: &Map<String, Value>,
    recipe: &Value,
    limit: usize,
    source_limit: usize,
) -> F<(Vec<String>, Vec<Vec<String>>, Value)> {
    let (conn, meta) = load_sources(b, c, recipe, source_limit)?;
    let (sql, names) = build_sql(recipe, &meta, Some(limit))?;
    let mut rows = Vec::new();
    {
        let mut st = conn.prepare(&sql).map_err(sql_fail)?;
        let n = st.column_count();
        let mut it = st.query([]).map_err(sql_fail)?;
        while let Some(r) = it.next().map_err(sql_fail)? {
            rows.push((0..n).map(|i| cell(r.get_ref(i).map_err(|_| Fail::Pass)?)).collect::<F<Vec<String>>>()?);
        }
    }
    // できあがりの件数は、先頭だけ取ったときも全体で数える
    let mut total = rows.len() as i64;
    if rows.len() >= limit {
        let (whole, _) = build_sql(recipe, &meta, None)?;
        total = conn.query_row(&format!("SELECT COUNT(*) FROM ({whole})"), [], |r| r.get(0)).map_err(sql_fail)?;
    }
    let sources: Vec<Value> =
        meta.iter().map(|m| json!({"alias": m.alias, "name": m.name, "rows": m.rows, "columns": m.columns, "format": m.format})).collect();
    let stats = json!({"sources": sources, "joins": join_stats(&conn, recipe, &meta), "rows": total, "shown": rows.len(),
                       "columns": names.len(), "sql": sql});
    Ok((names, rows, stats))
}

// ==== キーの見当 ============================================================

/// 値の集合（入れた順を保つ）。
#[derive(Default)]
struct Distinct {
    order: Vec<String>,
    seen: HashSet<String>,
}

impl Distinct {
    fn add(&mut self, v: String) {
        if !self.seen.contains(&v) {
            self.seen.insert(v.clone());
            self.order.push(v);
        }
    }
    fn len(&self) -> usize {
        self.order.len()
    }
}

/// _key_sets（列ごとの「空でない値の集合」。1種類しか無い列は外す）。
fn key_sets(headers: &[String], rows: &[Vec<String>]) -> Vec<(usize, Distinct)> {
    let mut out = Vec::new();
    for i in 0..headers.len() {
        let mut vals = Distinct::default();
        for r in rows {
            if vals.len() >= KEY_MAX_DISTINCT {
                break;
            }
            let v = pyish::strip(r.get(i).map(String::as_str).unwrap_or(""));
            if !v.is_empty() {
                vals.add(v.to_string());
            }
        }
        if vals.len() >= 2 {
            out.push((i, vals));
        }
    }
    out
}

/// _name_score（名前の近さ。最後の決め手にだけ使う）。
fn name_score(a: &str, b: &str) -> f64 {
    let (a, b) = (pyish::strip(a).to_lowercase(), pyish::strip(b).to_lowercase());
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    if a == b {
        return 1.0;
    }
    if a.contains(&b) || b.contains(&a) {
        return 0.6;
    }
    let (sa, sb): (HashSet<char>, HashSet<char>) = (a.chars().collect(), b.chars().collect());
    0.3 * sa.intersection(&sb).count() as f64 / sa.union(&sb).count().max(1) as f64
}

/// round(x, 4)（Python と同じく、2進の値をそのまま10進で丸める。ちょうど半分は偶数へ）。
fn round4(x: f64) -> f64 {
    format!("{x:.4}").parse().unwrap_or(x)
}

/// suggest_keys（実データで重なっている列の組を、強い順に）。
/// 重なりの割合・種類の多さ・名前の近さがどれも同じ組の順は、Python では値の集合の並び（文字列のハッシュ）で決まり、起こすたびに変わりうる。
/// ここでは値が初めて出てきた順にする。
pub(crate) fn suggest_keys(lh: &[String], lr: &[Vec<String>], rh: &[String], rr: &[Vec<String>], limit: usize) -> Vec<Value> {
    let lrows = &lr[..lr.len().min(KEY_SAMPLE_ROWS)];
    let rrows = &rr[..rr.len().min(KEY_SAMPLE_ROWS)];
    let (lsets, rsets) = (key_sets(lh, lrows), key_sets(rh, rrows));
    if lsets.is_empty() || rsets.is_empty() {
        return vec![];
    }
    let mut index: HashMap<&str, Vec<usize>> = HashMap::new();
    for (k, (_, vals)) in lsets.iter().enumerate() {
        for v in &vals.order {
            index.entry(v.as_str()).or_default().push(k);
        }
    }
    let mut hits: Vec<((usize, usize), usize)> = Vec::new();
    let mut at: HashMap<(usize, usize), usize> = HashMap::new();
    for (kr, (_, vals)) in rsets.iter().enumerate() {
        for v in &vals.order {
            for kl in index.get(v.as_str()).into_iter().flatten() {
                match at.get(&(*kl, kr)) {
                    Some(p) => hits[*p].1 += 1,
                    None => {
                        at.insert((*kl, kr), hits.len());
                        hits.push(((*kl, kr), 1));
                    }
                }
            }
        }
    }
    let mut out: Vec<(Value, (f64, f64, f64))> = Vec::new();
    for ((kl, kr), n) in hits {
        let ((i, lv), (j, rv)) = (&lsets[kl], &rsets[kr]);
        let small = lv.len().min(rv.len());
        let score = if small > 0 { n as f64 / small as f64 } else { 0.0 };
        if score < KEY_MIN_SCORE {
            continue;
        }
        let (lname, rname) = (&lh[*i], &rh[*j]);
        // 右が1行に決まるか（読んだぶんの中での話）
        let rvals: Vec<&str> = rrows.iter().filter_map(|r| r.get(*j)).map(|v| pyish::strip(v)).filter(|v| !v.is_empty()).collect();
        let unique = rvals.len() == rvals.iter().collect::<HashSet<_>>().len();
        out.push((
            json!({"left": lname, "right": rname, "score": round4(score), "matched": n, "left_distinct": lv.len(),
                   "right_distinct": rv.len(), "unique": unique, "same_name": lname == rname}),
            (score, (small as f64 / 50.0).min(1.0), name_score(lname, rname)),
        ));
    }
    // 重なりの割合、次に種類の多さ、最後に名前（sort(reverse=True) は同じ順位の並びを保つ）
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let (mut seen_l, mut seen_r, mut picked) = (HashSet::new(), HashSet::new(), Vec::new());
    for (x, _) in out {
        let (l, r) = (s(&x["left"]).to_string(), s(&x["right"]).to_string());
        if seen_l.contains(&l) || seen_r.contains(&r) {
            continue;
        }
        seen_l.insert(l);
        seen_r.insert(r);
        picked.push(x);
        if picked.len() >= limit.max(1) {
            break;
        }
    }
    picked
}

// ==== 受け口 ================================================================

/// request.get_json(force=True) or {} と、その中の recipe（normalize_join_recipe）。
fn body_and_recipe(ask: &Ask) -> R<(Map<String, Value>, Value)> {
    let d = match writer::body_json(ask, true)? {
        Some(Value::Object(m)) => m,
        Some(v) if pyish::truthy(&v) => return Err(Pass),
        _ => Map::new(),
    };
    let raw = match d.get("recipe") {
        Some(Value::Object(m)) => m.clone(),
        Some(v) if pyish::truthy(v) => return Err(Pass),
        _ => Map::new(),
    };
    let recipe = config::normalize_recipe(&raw)?;
    Ok((d, recipe))
}

/// int(d.get(k) or default)（読めなければ Python が落ちるので Pass）。
fn int_of(d: &Map<String, Value>, k: &str, default: i64) -> R<i64> {
    match d.get(k).filter(|v| pyish::truthy(v)) {
        None => Ok(default),
        Some(v) => pyish::int_opt(v).ok().flatten().ok_or(Pass),
    }
}

/// POST /api/join-keys
pub(crate) fn post_keys(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_keys(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_keys(core: &Core, ask: &Ask) -> R<Reply> {
    let (d, recipe) = body_and_recipe(ask)?;
    let c = config::read(core)?;
    let b = core.bases().ok_or(Pass)?;
    let i = int_of(&d, "index", 0)?.max(0) as usize;
    let srcs = recipe["sources"].as_array().cloned().unwrap_or_default();
    let limit = int_of(&d, "limit", 5)?;
    // 読む2つが Rust で読めない形式なら、写す前に回す（写しを2度作らない）
    if srcs.get(i).is_some_and(foreign) || srcs.get(i + 1).is_some_and(foreign) {
        return Err(Pass);
    }
    let (recipe, _copies) = sampled_recipe(core, &b, &recipe, &c)?;
    let srcs = recipe["sources"].as_array().cloned().unwrap_or_default();
    if i + 1 >= srcs.len() {
        return Ok(Reply::json(400, &json!({"ok": false, "error": "つなぎ目がありません"})));
    }
    let both = read_source(&b, &c, &srcs[i], KEY_SAMPLE_ROWS).and_then(|l| Ok((l, read_source(&b, &c, &srcs[i + 1], KEY_SAMPLE_ROWS)?)));
    let ((lh, lr), (rh, rr)) = match both {
        Ok(x) => x,
        Err(Fail::Message(m)) => return Ok(Reply::json(400, &json!({"ok": false, "error": format!("読み取れませんでした: {m}")}))),
        Err(Fail::Pass) => return Err(Pass),
    };
    let items = suggest_keys(&lh, &lr, &rh, &rr, limit.max(1) as usize);
    let shown: Vec<String> =
        items.iter().map(|x| format!("{}={}({:.0}%)", s(&x["left"]), s(&x["right"]), x["score"].as_f64().unwrap_or(0.0) * 100.0)).collect();
    core.log(&format!(
        "JOIN_KEY_SUGGEST index={i} 左={}列/{}行 右={}列/{}行 候補={}",
        lh.len(),
        lr.len(),
        rh.len(),
        rr.len(),
        if shown.is_empty() { "なし".to_string() } else { shown.join(" | ") }
    ));
    Ok(Reply::json(
        200,
        &json!({"ok": true, "items": items, "left_rows": lr.len(), "right_rows": rr.len(),
                "sampled": lr.len() >= KEY_SAMPLE_ROWS || rr.len() >= KEY_SAMPLE_ROWS}),
    ))
}

/// POST /api/join-preview
pub(crate) fn post_preview(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_preview(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_preview(core: &Core, ask: &Ask) -> R<Reply> {
    let (d, recipe) = body_and_recipe(ask)?;
    let lines = int_of(&d, "lines", 12)?;
    let c = config::read(core)?;
    let b = core.bases().ok_or(Pass)?;
    let srcs = recipe["sources"].as_array().cloned().unwrap_or_default();
    // EXCEL・ACCESS を読む取り決め、「どちらも全部残す」は、写す前に回す
    if srcs.iter().any(foreign) || recipe["joins"].as_array().into_iter().flatten().any(|j| s(&j["type"]) == "full") {
        return Err(Pass);
    }
    let (recipe, copies) = sampled_recipe(core, &b, &recipe, &c)?;
    let mut out = json!({"ok": false, "headers": [], "rows": [], "stats": {}, "notes": []});
    // 名前は保存のための決まりで、繋ぎ方とは関係が無い（作りかけでも下読みできる）
    let mut named = recipe.clone();
    if s(&named["name"]).is_empty() {
        named["name"] = json!("下読み");
    }
    let bad = crate::masters::validate_recipe(&named)?;
    let result = if bad.is_empty() {
        run_recipe(&b, &c, &recipe, lines.clamp(1, 200) as usize, SOURCE_LIMIT)
    } else {
        Err(Fail::Message(bad.join("／")))
    };
    match result {
        Ok((names, rows, stats)) => {
            let partial = stats["sources"].as_array().into_iter().flatten().any(|m| m["rows"].as_u64().unwrap_or(0) >= SOURCE_LIMIT as u64);
            let mut notes: Vec<String> = Vec::new();
            if partial {
                notes.push("確かめのため、各ファイルの先頭2,000行だけを読んでいます。件数の内訳もその範囲での数字です".into());
            }
            for j in stats["joins"].as_array().into_iter().flatten() {
                if !s(&j["why"]).is_empty() {
                    notes.push(format!("{}→{}: {}", s(&j["left"]), s(&j["right"]), s(&j["why"])));
                }
            }
            let cut: Vec<&str> = copies
                .iter()
                .filter(|x| {
                    let (bytes, total) = (x["bytes"].as_u64().unwrap_or(0), x["total"].as_u64().unwrap_or(0));
                    x["mode"] == json!("prefix") && bytes > 0 && total > 0 && bytes < total
                })
                .map(|x| s(&x["alias"]))
                .collect();
            if !cut.is_empty() {
                notes.push(format!(
                    "ローカルへ写した先頭だけを読んでいます（{}）。件数はその範囲での数字で、実行のときは元のファイルを最初から最後まで読みます",
                    cut.join("、")
                ));
            }
            out = json!({"ok": true, "headers": names, "rows": rows, "stats": stats, "notes": notes, "partial": partial, "copies": copies});
            Ok(Reply::json(200, &out))
        }
        Err(Fail::Message(m)) => {
            if bad.is_empty() {
                core.log(&format!("JOIN_PREVIEW_FAILED error={m}"));
            }
            out["error"] = json!(m);
            out["copies"] = json!(copies);
            Ok(Reply::json(400, &out))
        }
        Err(Fail::Pass) => Err(Pass),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rows(v: &[&[&str]]) -> Vec<Vec<String>> {
        v.iter().map(|r| r.iter().map(|x| x.to_string()).collect()).collect()
    }

    #[test]
    fn keys_by_overlap() {
        let lh = vec!["品番".to_string(), "区分".to_string()];
        let lr = rows(&[&["A1", "x"], &["A2", "y"], &["A3", "x"]]);
        let rh = vec!["ITEM".to_string(), "名".to_string()];
        let rr = rows(&[&["A1", "p"], &["A2", "q"], &["A2", "r"], &["Z9", "s"]]);
        let k = suggest_keys(&lh, &lr, &rh, &rr, 5);
        assert_eq!(k.len(), 1);
        assert_eq!(
            (s(&k[0]["left"]), s(&k[0]["right"]), k[0]["score"].as_f64(), &k[0]["unique"]),
            ("品番", "ITEM", Some(0.6667), &json!(false))
        );
    }

    #[test]
    fn rounding_like_python() {
        assert_eq!(round4(17.0 / 32.0), 0.5312);
        assert_eq!(round4(19.0 / 32.0), 0.5938);
        assert_eq!(round4(2.0 / 3.0), 0.6667);
    }
}
