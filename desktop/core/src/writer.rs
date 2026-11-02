//! 設定の保存と、共有のマスターへの書き戻し（2.22.0〜）。app._save_local・flush_local_to_master と navi_web.put_config と同じ結果にする。
//!
//! 書き手が2つ（Python と Rust）になっても壊れないように:
//!   - 版を確かめる・書く・版を上げる、を1つの取引（BEGIN IMMEDIATE）で行う。ほかの書き手は SQLite の錠で待つ
//!   - 書き戻しは SQLite のバックアップの仕組みで写す（写している最中に誰かが書けば最初からやり直すので、書きかけの写しにならない）。
//!     Python の書き戻しも同じ写し方にした（app.snapshot_db）
//!   - いま Python が読めば写しを替える場合（config::settled が偽）は、書かずに Python へ回す
//!
//! 書き戻しは保存の答えを返したあと裏で行う（共有の置き場は遅いことがある）。終わるとき（窓の終了・試験の答え口の終わり）は
//! `settle` で書き戻しの終わりを待ち、失敗して残っている変更があればもう一度書き戻す。

use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{applog, naming, paths, pyish, routes::Core, settings};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

type R<T> = Result<T, Pass>;

/// 裏の書き戻しの見張り（Core が持つ）。
#[derive(Default)]
pub struct Writes {
    /// 書き戻しの済んでいない変更がある（失敗した・まだ走っている）
    dirty: Arc<AtomicBool>,
    pending: Mutex<Vec<JoinHandle<()>>>,
}

/// 書き戻しは1つずつ（Python の master_write_lock に当たる。プロセスの中だけ）。
static MASTER_WRITE: Mutex<()> = Mutex::new(());

// ==== Python の json.dumps と str() ==========================================

/// json.dumps(v, ensure_ascii=False)（区切りは ", " と ": "。数は Python の書き方）。
pub fn py_dumps(v: &Value) -> String {
    let mut out = String::new();
    dump(v, &mut out);
    out
}

fn dump(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(_) => out.push_str(&pyish::py_str(v)),
        Value::String(s) => dump_str(s, out),
        Value::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump(x, out);
            }
            out.push(']');
        }
        Value::Object(o) => {
            out.push('{');
            for (i, (k, x)) in o.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump_str(k, out);
                out.push_str(": ");
                dump(x, out);
            }
            out.push('}');
        }
    }
}

fn dump_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// _encode_setting（真偽・整数・辞書と並び・それ以外の字）。
pub fn encode_setting(v: &Value) -> (String, &'static str) {
    match v {
        Value::Bool(b) => (if *b { "1" } else { "0" }.into(), "bool"),
        Value::Number(n) if n.is_i64() || n.is_u64() => (n.to_string(), "int"),
        Value::Array(_) | Value::Object(_) => (py_dumps(v), "json"),
        other => (pyish::py_str(other), "text"),
    }
}

/// Python の値を SQLite へ渡す（真偽は整数・None は NULL。並び・辞書は渡せない＝Python は落ちる）。
fn bind(v: &Value) -> R<rusqlite::types::Value> {
    use rusqlite::types::Value as S;
    Ok(match v {
        Value::Null => S::Null,
        Value::Bool(b) => S::Integer(i64::from(*b)),
        Value::Number(n) => match n.as_i64() {
            Some(i) => S::Integer(i),
            None if n.is_u64() => return Err(Pass), // 64 ビットを超える整数は Python も渡せない
            None => S::Real(n.as_f64().ok_or(Pass)?),
        },
        Value::String(s) => S::Text(s.clone()),
        _ => return Err(Pass),
    })
}

fn text(s: impl Into<String>) -> rusqlite::types::Value {
    rusqlite::types::Value::Text(s.into())
}

fn int(i: i64) -> rusqlite::types::Value {
    rusqlite::types::Value::Integer(i)
}

/// `d.get(k, default)`。
fn get_or<'a>(d: &'a Map<String, Value>, k: &str, default: &'a Value) -> &'a Value {
    d.get(k).unwrap_or(default)
}

fn truthy(v: Option<&Value>) -> bool {
    v.is_some_and(pyish::truthy)
}

/// `str(v)`（%s の書き方。無ければ None）。
fn s_of(v: Option<&Value>) -> String {
    v.map(pyish::py_str).unwrap_or_else(|| "None".into())
}

/// `str(v or '').strip().lower()` が allowed にあればそれ、無ければ既定。
fn choose(v: Option<&Value>, allowed: &[&'static str], default: &'static str, strip: bool) -> &'static str {
    let t = naming::text_or(v, if strip { "" } else { default });
    let t = if strip { pyish::strip(&t).to_lowercase() } else { t.to_lowercase() };
    allowed.iter().find(|a| **a == t).copied().unwrap_or(default)
}

/// job_table_name（空なら、手元のファイルから作る入力は DATA、RNE は 仕掛）。
pub fn job_table_name(j: &Map<String, Value>) -> String {
    let name = pyish::strip(&pyish::text_or_empty(j.get("table"))).to_string();
    if !name.is_empty() {
        return name;
    }
    if ["text", "join", "mquery"].contains(&settings::job_source(&pyish::text_or_empty(j.get("source")))) {
        "DATA".into()
    } else {
        "仕掛".into()
    }
}

/// normalize_interval_minutes（空は None、読めなければ 60、0 以下は 1）。
fn interval_minutes(v: Option<&Value>) -> R<rusqlite::types::Value> {
    let v = match v {
        None | Some(Value::Null) => return Ok(rusqlite::types::Value::Null),
        Some(Value::String(s)) if s.is_empty() => return Ok(rusqlite::types::Value::Null),
        Some(v) => v,
    };
    Ok(int(match pyish::int_opt(v) {
        Ok(Some(i)) => i.max(1),
        Ok(None) => 60,
        Err(_) => return Err(Pass), // Python は大きな数のまま渡して落ちる
    }))
}

fn new_id() -> String {
    uuid::Uuid::new_v4().to_string()
}

// ==== 保存 ==================================================================

/// 保存の結果。
pub enum Saved {
    Ok(i64),
    /// 画面の版と、いまの版が違う（ほかの画面で変わっている）
    Conflict(i64),
}

/// 設定の版を読む（app.settings_revision と同じ読み方。読めなければ 0）。
fn revision_in(c: &Connection) -> i64 {
    c.query_row("SELECT CAST(value AS TEXT) FROM schema_info WHERE key='settings_revision'", [], |r| r.get::<_, Option<String>>(0))
        .ok()
        .flatten()
        .and_then(|s| {
            let t = pyish::strip(&s).to_string();
            let body = t.trim_start_matches('-');
            (!body.is_empty() && body.bytes().all(|b| b.is_ascii_digit())).then(|| t.parse::<i64>().ok()).flatten()
        })
        .unwrap_or(0)
}

fn local_db() -> PathBuf {
    settings::local_db(Path::new(&paths::py_path(&paths::local_root().to_string_lossy())))
}

/// 設定を丸ごと置き換える（app._save_local）。want は画面が持っている版（None なら確かめない）。
pub fn save(core: &Core, v: &Map<String, Value>, want: Option<i64>, quiet: bool) -> R<Saved> {
    let local = local_db();
    if !local.is_file() {
        return Err(Pass);
    }
    let mut c =
        Connection::open_with_flags(&local, OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX).map_err(|_| Pass)?;
    c.busy_timeout(Duration::from_secs(30)).map_err(|_| Pass)?;
    c.execute_batch("PRAGMA foreign_keys=ON").map_err(|_| Pass)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|_| Pass)?;
    if !config::settled(core, &local, &tx) {
        return Err(Pass);
    }
    let now_rev = revision_in(&tx);
    if let Some(w) = want {
        if w != now_rev {
            return Ok(Saved::Conflict(now_rev));
        }
    }
    let now = core.now().format("%Y-%m-%dT%H:%M:%S").to_string();
    let mut lines = Vec::new();
    write_all(&tx, v, &now, quiet, &mut lines)?;
    let rev = now_rev + 1;
    tx.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('settings_revision',?)", [rev.to_string()]).map_err(|_| Pass)?;
    tx.commit().map_err(|_| Pass)?;
    for l in lines {
        core.log(&l);
    }
    Ok(Saved::Ok(rev))
}

const SKIP_TOP: [&str; 7] =
    ["jobs", "credential_status", "text_layouts", "join_recipes", "m_queries", "settings_revision", "setting_defaults"];

fn exec(c: &Connection, sql: &str, params: Vec<rusqlite::types::Value>) -> R<()> {
    c.execute(sql, rusqlite::params_from_iter(params)).map(|_| ()).map_err(|_| Pass)
}

fn write_all(c: &Connection, v: &Map<String, Value>, now: &str, quiet: bool, lines: &mut Vec<String>) -> R<()> {
    exec(c, "DELETE FROM app_settings", vec![])?;
    for (key, value) in v.iter().filter(|(k, _)| !SKIP_TOP.contains(&k.as_str())) {
        let (encoded, kind) = encode_setting(value);
        exec(c, "INSERT INTO app_settings VALUES(?,?,?,?)", vec![text(key.clone()), text(encoded), text(kind), text(now)])?;
    }
    let empty_list = json!([]);
    let jobs = get_or(v, "jobs", &empty_list).as_array().ok_or(Pass)?;
    let mut keep: Vec<rusqlite::types::Value> = Vec::new();
    for (order, j) in jobs.iter().enumerate() {
        let j = j.as_object().ok_or(Pass)?;
        let jid = match j.get("id") {
            Some(x) if pyish::truthy(x) => bind(x)?,
            _ => text(new_id()),
        };
        keep.push(jid.clone());
        let fmt = naming::normalize_output_format(j.get("output_format"), j.get("output_file"));
        let output_file = naming::canonical_output_file(j.get("output_file"), fmt);
        if !quiet {
            lines.push(format!(
                "設定保存 job={} requested_format={} saved_format={fmt} requested_file={} saved_file={output_file}",
                s_of(j.get("name")),
                s_of(j.get("output_format")),
                s_of(j.get("output_file"))
            ));
        }
        let mut with_fmt = j.clone();
        with_fmt.insert("output_format".into(), json!(fmt));
        let extra = naming::job_extra_formats(&with_fmt).ok_or(Pass)?;
        let mut idx: Vec<String> = Vec::new();
        for x in pyish::py_iter(j.get("index_columns")).ok_or(Pass)? {
            let t = pyish::strip(&pyish::py_str(&x)).to_string();
            if !t.is_empty() {
                idx.push(t);
            }
        }
        idx.truncate(4);
        let axis_index = match j.get("row_axis_index") {
            Some(x) if pyish::truthy(x) => match pyish::int_opt(x) {
                Ok(Some(i)) => i,
                Ok(None) => return Err(Pass),
                Err(_) => {
                    if pyish::py_str(x).trim_start().starts_with('-') {
                        1
                    } else {
                        200
                    }
                }
            },
            _ => 1,
        }
        .clamp(1, 200);
        let period = config::period_value(match j.get("period") {
            Some(x) if pyish::truthy(x) => x,
            _ => &Value::Null,
        })?;
        let (yes, page, kind, blank) = (json!(true), json!("Page1"), json!("詳細データ"), json!(""));
        exec(
            c,
            "INSERT OR REPLACE INTO jobs (id,display_order,enabled,name,rne,rne_path,output_folder,output_format,output_file,table_name,sheet_name,read_type,naming_mode,output_pattern,comment,split_mode,split_shape,row_axis_mode,row_axis_index,row_axis_name,extra_formats,index_columns,skip_if_unchanged,period_json,source,text_path,layout_id,recipe_id,query_id,query_out,variants_json,viewer_json,post_json,group_name,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            vec![
                jid.clone(),
                int(order as i64),
                int(i64::from(pyish::truthy(get_or(j, "enabled", &yes)))),
                bind(get_or(j, "name", &blank))?,
                bind(get_or(j, "rne", &blank))?,
                bind(get_or(j, "rne_path", &blank))?,
                bind(get_or(j, "output_folder", &blank))?,
                text(fmt),
                text(output_file),
                text(job_table_name(j)),
                bind(get_or(j, "sheet", &page))?,
                bind(get_or(j, "type", &kind))?,
                text(naming::text_or(j.get("naming_mode"), "fixed")),
                text(pyish::text_or_empty(j.get("output_pattern"))),
                text(pyish::text_or_empty(j.get("comment"))),
                text(choose(j.get("split_mode"), &["auto", "force", "race", "off"], "auto", true)),
                text(choose(j.get("split_shape"), &["auto", "column", "row", "grid"], "auto", true)),
                text(choose(j.get("row_axis_mode"), &["first", "index", "name", "balanced"], "first", false)),
                int(axis_index),
                text(pyish::text_or_empty(j.get("row_axis_name"))),
                text(py_dumps(&json!(extra))),
                text(py_dumps(&json!(idx))),
                int(i64::from(truthy(j.get("skip_if_unchanged")))),
                text(py_dumps(&period)),
                text(settings::job_source(&pyish::text_or_empty(j.get("source")))),
                text(pyish::text_or_empty(j.get("text_path"))),
                text(pyish::text_or_empty(j.get("layout_id"))),
                text(pyish::text_or_empty(j.get("recipe_id"))),
                text(pyish::text_or_empty(j.get("query_id"))),
                text(pyish::text_or_empty(j.get("query_out"))),
                text(py_dumps(&config::normalize_variants(j.get("variants").unwrap_or(&Value::Null))?)),
                text(py_dumps(&config::normalize_viewer(j.get("viewer").unwrap_or(&Value::Null))?)),
                text(py_dumps(&config::normalize_post(j.get("post").unwrap_or(&Value::Null))?)),
                text(config::normalize_group(j.get("group"))),
                text(now),
            ],
        )?;
        exec(c, "DELETE FROM schedules WHERE job_id=?", vec![jid.clone()])?;
        let rules = match j.get("schedules") {
            None => vec![],
            Some(Value::Array(a)) => a.clone(),
            Some(_) => return Err(Pass), // enumerate(字・数) は Python で落ちる（字は 1 字ずつの .get で落ちる）
        };
        for (ro, q) in rules.iter().enumerate() {
            let q = q.as_object().ok_or(Pass)?;
            let qid = match q.get("id") {
                Some(x) if pyish::truthy(x) => bind(x)?,
                _ => text(new_id()),
            };
            let dumped = |k: &str| q.get(k).map(|x| text(py_dumps(x))).unwrap_or(rusqlite::types::Value::Null);
            let (rule, daily, six) = (json!("実行ルール"), json!("daily"), json!("06:00"));
            exec(
                c,
                "INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                vec![
                    qid,
                    jid.clone(),
                    int(ro as i64),
                    int(i64::from(pyish::truthy(get_or(q, "enabled", &yes)))),
                    bind(get_or(q, "name", &rule))?,
                    bind(get_or(q, "type", &daily))?,
                    bind(get_or(q, "time", &six))?,
                    interval_minutes(q.get("interval_minutes"))?,
                    dumped("weekdays"),
                    dumped("month_days"),
                    dumped("dates"),
                    text(now),
                ],
            )?;
        }
    }
    if keep.is_empty() {
        exec(c, "DELETE FROM jobs", vec![])?;
        exec(c, "DELETE FROM job_runs", vec![])?;
    } else {
        let marks = vec!["?"; keep.len()].join(",");
        exec(c, &format!("DELETE FROM jobs WHERE id NOT IN ({marks})"), keep.clone())?;
        exec(c, &format!("DELETE FROM job_runs WHERE job_id NOT IN ({marks})"), keep)?;
    }
    Ok(())
}

// ==== 書き戻し ==============================================================

/// 写しを、ひとそろいの状態で写す（SQLite のバックアップの仕組み）。
fn snapshot(src: &Path, dst: &Path) -> rusqlite::Result<()> {
    let _ = std::fs::remove_file(dst);
    let s = Connection::open_with_flags(src, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    s.busy_timeout(Duration::from_secs(30))?;
    s.backup(rusqlite::MAIN_DB, dst, None)?;
    keep_mtime(src, dst);
    Ok(())
}

/// 更新時刻を src と同じにする（Python の shutil.copy2・copystat と同じ。版が両側とも無いとき、取り込みは更新時刻で新旧を決めるため）。
fn keep_mtime(src: &Path, dst: &Path) {
    if let Ok(t) = std::fs::metadata(src).and_then(|m| m.modified()) {
        if let Ok(f) = std::fs::OpenOptions::new().write(true).open(dst) {
            let _ = f.set_modified(t);
        }
    }
}

fn readable(p: &Path) -> bool {
    if std::fs::metadata(p).map(|m| m.len() == 0).unwrap_or(true) {
        return false;
    }
    Connection::open_with_flags(p, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .and_then(|c| c.query_row("PRAGMA quick_check", [], |r| r.get::<_, String>(0)))
        .map(|s| s.eq_ignore_ascii_case("ok"))
        .unwrap_or(false)
}

fn revision_of(p: &Path) -> i64 {
    Connection::open_with_flags(p, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX).map(|c| revision_in(&c)).unwrap_or(0)
}

/// os.replace を、相手が開いている間だけ少し待ってやり直す（app.replace_retry と同じ）。
fn replace_retry(src: &Path, dst: &Path) -> std::io::Result<()> {
    let mut last = None;
    for _ in 0..40 {
        match std::fs::rename(src, dst) {
            Ok(()) => return Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                last = Some(e);
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => return Err(e),
        }
    }
    Err(last.unwrap_or_else(|| std::io::Error::other("置き換えられません")))
}

fn warn(level: &str, msg: &str) {
    applog::write(&paths::local_root(), level, msg);
}

/// 写し → マスターへ書き戻す（app.flush_local_to_master）。→ 書き戻したか。
pub fn flush(local: &Path, master: &Path, reason: &str) -> bool {
    let _g = MASTER_WRITE.lock().unwrap_or_else(|e| e.into_inner());
    if !local.is_file() {
        return false;
    }
    if !readable(local) {
        warn("ERROR", &format!("SETTINGS_FLUSH_ABORTED reason={reason} detail=手元の控えが壊れているため書き戻しません"));
        return false;
    }
    let lrev = revision_of(local);
    let stem = local.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let stage = local.with_file_name(format!("{stem}.flush.rust.{}.tmp", std::process::id()));
    let done = (|| -> Result<bool, String> {
        snapshot(local, &stage).map_err(|e| e.to_string())?;
        let t = Instant::now();
        if let Some(dir) = master.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let mrev = if master.is_file() { revision_of(master) } else { 0 };
        if mrev > lrev {
            warn(
                "WARNING",
                &format!("SETTINGS_FLUSH_SKIPPED reason={reason} detail=別のPCの変更のほうが新しいため書き戻しません master_rev={mrev} local_rev={lrev} pulled_rev=-"),
            );
            return Ok(false);
        }
        let mstem = master.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
        let tmp = master.with_file_name(format!("{mstem}.rust.{}.wb.tmp", std::process::id()));
        let r = std::fs::copy(&stage, &tmp).and_then(|_| {
            keep_mtime(&stage, &tmp);
            replace_retry(&tmp, master)
        });
        let _ = std::fs::remove_file(&tmp);
        r.map_err(|e| e.to_string())?;
        let elapsed = t.elapsed().as_secs_f64();
        let size = std::fs::metadata(master).map(|m| m.len()).unwrap_or(0);
        warn("INFO", &format!("SETTINGS_FLUSH local->master reason={reason} elapsed={elapsed:.2}s size={size} rev={lrev}"));
        if elapsed > 5.0 {
            warn(
                "WARNING",
                &format!(
                    "SETTINGS_FLUSH_SLOW reason={reason} elapsed={elapsed:.1}s path={}（共有フォルダーの応答が遅くなっています）",
                    master.display()
                ),
            );
        }
        Ok(true)
    })();
    let _ = std::fs::remove_file(&stage);
    match done {
        Ok(b) => b,
        Err(e) => {
            warn("ERROR", &format!("SETTINGS_FLUSH_FAILED reason={reason} error={e}"));
            false
        }
    }
}

fn master_db(core: &Core) -> Option<PathBuf> {
    core.config_dir().map(|d| PathBuf::from(paths::join(&d, "app_settings.sqlite3")))
}

impl Writes {
    /// 保存のあと、裏で書き戻す（app.flush_local_to_master_async）。失敗したら、終わるときにもう一度書き戻す。
    pub fn flush_later(&self, local: PathBuf, master: PathBuf, reason: &'static str) {
        self.dirty.store(true, Ordering::SeqCst);
        let dirty = self.dirty.clone();
        let h = std::thread::spawn(move || {
            if flush(&local, &master, reason) {
                dirty.store(false, Ordering::SeqCst);
            }
        });
        self.pending.lock().unwrap_or_else(|e| e.into_inner()).push(h);
    }

    /// 裏の書き戻しの終わりを待ち、残っている変更があればもう一度書き戻す（終わるとき）。
    pub fn settle(&self, local: &Path, master: Option<&Path>, reason: &str) {
        let hs: Vec<JoinHandle<()>> = std::mem::take(&mut *self.pending.lock().unwrap_or_else(|e| e.into_inner()));
        for h in hs {
            let _ = h.join();
        }
        if let Some(m) = master {
            if self.dirty.load(Ordering::SeqCst) && flush(local, m, reason) {
                self.dirty.store(false, Ordering::SeqCst);
            }
        }
    }
}

impl Core {
    /// 終わるときに呼ぶ: 裏の書き戻しを待ち、残っている変更を書き戻す。
    pub fn settle_writes(&self, reason: &str) {
        let master = master_db(self);
        self.writes.settle(&local_db(), master.as_deref(), reason);
    }
}

// ==== 受け口 ================================================================

/// PUT /api/config … 設定を丸ごと保存する（画面の自動保存）。版が違えば 409。
pub(crate) fn put_config(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_put(core, ask).unwrap_or_else(|_| Reply::pass())
}

/// Flask の request.is_json（application/json か application/…+json）。
fn is_json(ask: &Ask) -> bool {
    ask.headers.iter().any(|(k, v)| {
        k.eq_ignore_ascii_case("content-type") && {
            let m = v.split(';').next().unwrap_or("").trim().to_ascii_lowercase();
            m == "application/json" || (m.starts_with("application/") && m.ends_with("+json"))
        }
    })
}

fn answer_put(core: &Core, ask: &Ask) -> R<Reply> {
    let shape = || Reply::json(400, &json!({"ok": false, "error": "設定の形が正しくありません（対象の一覧が含まれていません）"}));
    // request.get_json(silent=True): JSON の印が無い・読めない本文は None（→ 400）
    let data = if is_json(ask) {
        match std::str::from_utf8(ask.body).map(config::py_json) {
            Ok(config::Json::Ok(v)) => Some(v),
            Ok(config::Json::Unsure) => return Err(Pass),
            _ => None,
        }
    } else {
        None
    };
    let Some(Value::Object(data)) = data else { return Ok(shape()) };
    if !matches!(data.get("jobs"), Some(Value::Array(_))) {
        return Ok(shape());
    }
    let want = match data.get("settings_revision") {
        None | Some(Value::Null) => None,
        Some(v) => match pyish::int_opt(v) {
            Ok(x) => x,
            Err(_) => return Err(Pass),
        },
    };
    match save(core, &data, want, false)? {
        Saved::Conflict(now) => {
            core_warn(&format!(
                "CONFIG_PUT_CONFLICT client_rev={} server_rev={now}（ほかの画面の変更を上書きしません）",
                want.unwrap_or_default()
            ));
            Ok(Reply::json(
                409,
                &json!({"ok": false, "conflict": true, "settings_revision": now,
                        "error": "ほかの画面で設定が変わっています。最新の内容を読み直してから、もう一度保存してください"}),
            ))
        }
        Saved::Ok(rev) => {
            if let Some(m) = master_db(core) {
                core.writes.flush_later(local_db(), m, "config-save");
            }
            Ok(Reply::json(200, &json!({"ok": true, "settings_revision": rev})))
        }
    }
}

fn core_warn(msg: &str) {
    warn("WARNING", msg);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dumps_like_python() {
        assert_eq!(
            py_dumps(&json!({"a": [1, 2.5, 1e16, null, true], "b": "x\"\n\u{1}あ"})),
            r#"{"a": [1, 2.5, 1e+16, null, true], "b": "x\"\n\u0001あ"}"#
        );
        assert_eq!(py_dumps(&json!([])), "[]");
        assert_eq!(encode_setting(&json!(true)), ("1".into(), "bool"));
        assert_eq!(encode_setting(&json!(5)), ("5".into(), "int"));
        assert_eq!(encode_setting(&json!(2.0)), ("2.0".into(), "text"));
        assert_eq!(encode_setting(&json!(null)), ("None".into(), "text"));
        assert_eq!(encode_setting(&json!({"k": 1})), (r#"{"k": 1}"#.into(), "json"));
    }
}
