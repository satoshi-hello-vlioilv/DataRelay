//! 実行の記録（2.36.0〜）。app.record_job_run と、ワーカーの答えから記録を作る決まり（navi_lanerun.run_api_process_batch の後半・
//! navi_textrun.local_outcome の record）と同じ物を作る。
//!
//! 実行の記録を書くのは親1本（ワーカーは書かない）。段 5d から Rust の実行役が親になるので、その書き口をここに置く。
//!   - job_runs … 対象ごとの最後の1回（INSERT OR REPLACE）
//!   - run_history … カレンダーの実施履歴（追記。直近 2000 件だけ残す）
use crate::config::Pass;
use crate::{pyish, routes::Core, writer};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

/// 実施履歴に残す件数（app.record_job_run の LIMIT 2000）。
const HISTORY_KEEP: i64 = 2000;

/// 1回ぶんの実行の記録（record_job_run の引数）。
#[derive(Debug, Clone, PartialEq)]
pub struct JobRecord {
    pub job_id: Value,
    pub job_name: Value,
    pub status: String,
    pub trigger: String,
    pub detail: String,
    pub rows: Value,
    pub cols: Value,
    pub output_file: String,
    pub metrics: Value,
}

impl JobRecord {
    /// 中身の無い記録（失敗・中断の知らせだけを残すとき。record_job_run(id, name, status, trigger, detail=…)）。
    pub fn note(job: &Map<String, Value>, status: &str, trigger: &str, detail: &str) -> JobRecord {
        JobRecord {
            job_id: job.get("id").cloned().unwrap_or(Value::Null),
            job_name: job.get("name").cloned().unwrap_or(Value::Null),
            status: status.into(),
            trigger: trigger.into(),
            detail: detail.into(),
            rows: Value::Null,
            cols: Value::Null,
            output_file: String::new(),
            metrics: json!({}),
        }
    }
}

/// SQLite へ渡す値（Python の sqlite3 と同じ型の決め方。字・整数・小数・None。ほかは Pass）。
fn bind(v: &Value) -> R<rusqlite::types::Value> {
    use rusqlite::types::Value as S;
    match v {
        Value::Null => Ok(S::Null),
        Value::Bool(b) => Ok(S::Integer(i64::from(*b))),
        Value::Number(n) => n.as_i64().map(S::Integer).or_else(|| n.as_f64().map(S::Real)).ok_or(Pass),
        Value::String(s) => Ok(S::Text(s.clone())),
        _ => Err(Pass),
    }
}

/// record_job_run（対象ごとの最後の1回と、実施履歴への追記）。id が空なら何もしない。
pub fn record_job_run(core: &Core, r: &JobRecord) -> R<()> {
    if !pyish::truthy(&r.job_id) {
        return Ok(());
    }
    let now = writer::stamp(core);
    let empty = json!({});
    let metrics = writer::py_dumps(if pyish::truthy(&r.metrics) { &r.metrics } else { &empty });
    let (id, name, rows, cols) = (bind(&r.job_id)?, bind(&r.job_name)?, bind(&r.rows)?, bind(&r.cols)?);
    let text = |s: &str| rusqlite::types::Value::Text(s.to_string());
    writer::transact(core, |tx, _| {
        let row = vec![
            id.clone(),
            name.clone(),
            text(&now),
            text(&r.status),
            text(&r.trigger),
            text(&r.detail),
            rows.clone(),
            cols.clone(),
            text(&r.output_file),
        ];
        let mut runs = row.clone();
        runs.extend([text(&now), text(&metrics)]);
        tx.execute(
            "INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) \
             VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            rusqlite::params_from_iter(runs),
        )
        .map_err(|_| Pass)?;
        tx.execute(
            "INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)",
            rusqlite::params_from_iter(row),
        )
        .map_err(|_| Pass)?;
        tx.execute("DELETE FROM run_history WHERE id NOT IN (SELECT id FROM run_history ORDER BY id DESC LIMIT ?)", [HISTORY_KEEP])
            .map_err(|_| Pass)?;
        Ok(())
    })?;
    writer::mark_dirty(core);
    Ok(())
}

fn text(v: Option<&Value>) -> String {
    match v {
        Some(v) if pyish::truthy(v) => pyish::py_str(v),
        _ => String::new(),
    }
}

/// Path(x).name（x が空なら空）。
fn file_name(v: Option<&Value>) -> String {
    crate::paths::py_name(&text(v))
}

/// RNE のワーカーの答えから、画面へ渡す1件（job_results の1行）と、実行の記録を作る（navi_lanerun の WORKER_END のあと）。
pub fn from_rne_result(job: &Map<String, Value>, result: &Map<String, Value>, trigger: &str) -> (Value, JobRecord) {
    let ok = result.get("ok").is_some_and(pyish::truthy);
    let detail = text(result.get("result").filter(|v| pyish::truthy(v)).or_else(|| result.get("error")));
    let get = |k: &str| result.get(k).cloned().unwrap_or(Value::Null);
    let elapsed = result.get("elapsed").and_then(Value::as_f64).unwrap_or(0.0);
    let published = result.get("published").map(pyish::truthy).unwrap_or(true);
    let mut one = json!({"job": job.get("name").cloned().unwrap_or(Value::Null), "job_id": job.get("id").cloned().unwrap_or(Value::Null),
                         "status": if ok { "ok" } else { "failed" }, "detail": detail, "rows": get("rows"), "cols": get("columns"),
                         "elapsed": round1(elapsed), "target": text(result.get("target")),
                         "published": published, "pending": text(result.get("pending"))});
    if let Some(v) = result.get("variant_results").filter(|v| pyish::truthy(v)) {
        one["variants"] = v.clone();
    }
    let mut metrics = Map::new();
    for k in [
        "elapsed",
        "execute_seconds",
        "save_seconds",
        "merge_seconds",
        "transfer_bytes",
        "transfer_kbs",
        "split_parts",
        "split_shape",
        "split_how",
        "row_axis",
        "axis_seconds",
        "race_winner",
        "format",
        "variant_results",
        "variant_method",
        "variant_lines",
    ] {
        if let Some(v) = result.get(k).filter(|v| !v.is_null()) {
            metrics.insert(k.into(), v.clone());
        }
    }
    metrics.insert("published".into(), json!(published));
    metrics.insert("pending".into(), json!(text(result.get("pending"))));
    metrics.insert("hold_reason".into(), json!(text(result.get("hold_reason"))));
    metrics.insert("hold_waited".into(), get("hold_waited"));
    metrics.insert("hold_attempts".into(), get("hold_attempts"));
    // list(x or [])（字は1字ずつ）
    let advice = match result.get("hold_advice") {
        Some(Value::Array(a)) => a.clone(),
        Some(Value::String(s)) => s.chars().map(|c| json!(c.to_string())).collect(),
        _ => vec![],
    };
    metrics.insert("hold_advice".into(), Value::Array(advice));
    let trig = text(job.get("_trigger"));
    let record = JobRecord {
        job_id: job.get("id").cloned().unwrap_or(Value::Null),
        job_name: job.get("name").cloned().unwrap_or(Value::Null),
        status: if ok { "ok" } else { "failed" }.into(),
        trigger: if trig.is_empty() { trigger.into() } else { trig },
        detail,
        rows: get("rows"),
        cols: get("columns"),
        output_file: file_name(result.get("target")),
        metrics: Value::Object(metrics),
    };
    (one, record)
}

/// 手元の対象のワーカーの答え（navi_textrun.run_local_in_worker）から、実行の記録を作る（答えの record をそのまま使う）。
pub fn from_local_result(job: &Map<String, Value>, result: &Map<String, Value>, trigger: &str) -> JobRecord {
    let empty = Map::new();
    let rec = result.get("record").and_then(Value::as_object).unwrap_or(&empty);
    let trig = text(job.get("_trigger"));
    JobRecord {
        job_id: job.get("id").cloned().unwrap_or(Value::Null),
        job_name: job.get("name").cloned().unwrap_or(Value::Null),
        status: Some(text(rec.get("status"))).filter(|s| !s.is_empty()).unwrap_or_else(|| "failed".into()),
        trigger: if trig.is_empty() { trigger.into() } else { trig },
        detail: text(rec.get("detail").or_else(|| result.get("error"))),
        rows: rec.get("rows").cloned().unwrap_or(Value::Null),
        cols: rec.get("cols").cloned().unwrap_or(Value::Null),
        output_file: text(rec.get("output_file")),
        metrics: rec.get("metrics").cloned().unwrap_or(json!({})),
    }
}

/// round(x, 1)（2進の値をそのまま10進で丸める。ちょうど半分は偶数へ）。
fn round1(x: f64) -> f64 {
    format!("{x:.1}").parse().unwrap_or(x)
}

// ==== RNE 単位の控え（app.record_rne_run・save_column_cache・save_rne_timing。2.39.0〜） ====
// 同じ RNE を複数の対象が使うことがあるので、鍵は対象ではなく RNE の場所（実体の道を OS の流儀で揃えた字）。

/// RNE の実績に残す件数（RNE ごと。record_rne_run の LIMIT 2000）。
const RNE_RUNS_KEEP: i64 = 2000;

/// _rne_key（os.path.normcase(os.path.normpath(Path(p).resolve()))）。
pub fn rne_key(p: &str) -> String {
    let n = crate::paths::normpath(&crate::paths::resolve(p));
    if cfg!(windows) {
        n.to_lowercase().replace('/', "\\")
    } else {
        n
    }
}

/// rne_signature（RNE の版の指紋: 更新日時のナノ秒の字と大きさ。読めなければ ('', 0)）。
pub fn rne_signature(p: &str) -> (String, i64) {
    // Path('') は今いるフォルダー（'.'）を指す
    let Ok(m) = std::fs::metadata(if p.is_empty() { "." } else { p }) else { return (String::new(), 0) };
    let ns = match m.modified() {
        Ok(t) => match t.duration_since(std::time::UNIX_EPOCH) {
            Ok(d) => d.as_nanos() as i128,
            Err(e) => -(e.duration().as_nanos() as i128),
        },
        Err(_) => return (String::new(), 0),
    };
    (ns.to_string(), m.len() as i64)
}

/// app.host_name（COMPUTERNAME、無ければこの PC の名前、それも無ければ '-'）。
fn machine_name() -> String {
    std::env::var("COMPUTERNAME").ok().filter(|s| !s.is_empty()).or_else(crate::paths::host_name).unwrap_or_else(|| "-".into())
}

/// os.cpu_count（論理 CPU の数。分からなければ 0）。Windows は全部のプロセッサー群、Linux は動いている CPU（/sys の online）。
pub fn cpu_count() -> i64 {
    #[cfg(windows)]
    {
        use windows_sys::Win32::System::Threading::{GetActiveProcessorCount, ALL_PROCESSOR_GROUPS};
        // SAFETY: 引数は数だけで、何も書き込まない
        i64::from(unsafe { GetActiveProcessorCount(ALL_PROCESSOR_GROUPS) })
    }
    #[cfg(not(windows))]
    {
        // 「0-3,6,8-9」の形
        let Ok(t) = std::fs::read_to_string("/sys/devices/system/cpu/online") else {
            return std::thread::available_parallelism().map(|n| n.get() as i64).unwrap_or(0);
        };
        t.trim()
            .split(',')
            .filter(|x| !x.is_empty())
            .map(|r| match r.split_once('-') {
                Some((a, b)) => b.parse::<i64>().unwrap_or(0) - a.parse::<i64>().unwrap_or(0) + 1,
                None => i64::from(r.parse::<i64>().is_ok()),
            })
            .sum()
    }
}

/// int(x or 0)（読めない値は Python が落ちて記録しないので Pass）。
fn int_or_zero(v: Option<&Value>) -> R<i64> {
    match v {
        Some(v) if pyish::truthy(v) => pyish::int_opt(v).ok().flatten().ok_or(Pass),
        _ => Ok(0),
    }
}

/// record_rne_run（1回の実行を、RNE 単位の実績として残す。時間帯・端末・分け方・内訳まで）。rne_path が空なら何もしない（false）。
#[allow(clippy::too_many_arguments)]
pub fn record_rne_run(
    core: &Core,
    rne_path: &str,
    job: &Map<String, Value>,
    status: &str,
    trigger: &str,
    m: &Map<String, Value>,
    engine: &str,
    fmt: &str,
) -> R<bool> {
    use chrono::{Datelike, Timelike};
    if rne_path.is_empty() {
        return Ok(false);
    }
    let now = core.now();
    let key = rne_key(rne_path);
    let s = |v: Option<&Value>| rusqlite::types::Value::Text(text(v));
    let raw = |k: &str| bind(m.get(k).unwrap_or(&Value::Null));
    let t = |x: &str| rusqlite::types::Value::Text(x.to_string());
    let n = rusqlite::types::Value::Integer;
    let format = Some(text(m.get("format"))).filter(|x| !x.is_empty()).unwrap_or_else(|| fmt.to_string());
    let row = vec![
        t(&key),
        t(rne_path),
        s(job.get("id")),
        s(job.get("name")),
        t(&now.format("%Y-%m-%dT%H:%M:%S").to_string()),
        n(i64::from(now.hour())),
        n(i64::from(now.weekday().num_days_from_monday())),
        t(status),
        t(trigger),
        t(engine),
        s(m.get("split_shape")),
        s(m.get("split_how")),
        n(int_or_zero(m.get("split_parts"))?),
        s(m.get("row_axis")),
        raw("rows")?,
        raw("cols")?,
        raw("elapsed")?,
        raw("execute_seconds")?,
        raw("save_seconds")?,
        raw("merge_seconds")?,
        raw("axis_seconds")?,
        raw("transfer_bytes")?,
        raw("transfer_kbs")?,
        n(int_or_zero(m.get("lines"))?),
        t(&machine_name()),
        n(cpu_count()),
        t(&format),
    ];
    writer::transact(core, |tx, _| {
        tx.execute(
            "INSERT INTO rne_runs(rne_key,rne_path,job_id,job_name,finished_at,hour,weekday,status,trigger,engine,\
             shape,how,parts,row_axis,rows,cols,elapsed,execute_seconds,save_seconds,merge_seconds,axis_seconds,\
             transfer_bytes,transfer_kbs,lines,host,cpu,format) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rusqlite::params_from_iter(row.clone()),
        )
        .map_err(|_| Pass)?;
        // 分析に要るのは傾向で、全履歴ではない。RNE ごとに直近 2000 件へ抑える
        tx.execute(
            "DELETE FROM rne_runs WHERE rne_key=? AND id NOT IN (SELECT id FROM rne_runs WHERE rne_key=? ORDER BY id DESC LIMIT ?)",
            rusqlite::params![key, key, RNE_RUNS_KEEP],
        )
        .map_err(|_| Pass)?;
        Ok(())
    })?;
    writer::mark_dirty(core);
    Ok(true)
}

/// save_column_cache（列名を RNE 単位で控える。列名が取れなかったときは何もしない＝空で上書きしない）。控えた列名を返す。
pub fn save_column_cache(
    core: &Core,
    rne_path: &str,
    columns: &Value,
    rows: &Value,
    source: &str,
    job: &Map<String, Value>,
) -> R<Option<Vec<String>>> {
    let cols: Vec<String> = match columns {
        Value::Array(a) => a.iter().map(pyish::py_str).filter(|x| !pyish::strip(x).is_empty()).collect(),
        v if !pyish::truthy(v) => vec![],
        _ => return Err(Pass),
    };
    if cols.is_empty() {
        return Ok(None);
    }
    let (mtime, size) = rne_signature(rne_path);
    let t = |x: &str| rusqlite::types::Value::Text(x.to_string());
    let row = vec![
        t(&rne_key(rne_path)),
        t(rne_path),
        t(&mtime),
        rusqlite::types::Value::Integer(size),
        t(&writer::py_dumps(&json!(cols))),
        rusqlite::types::Value::Integer(cols.len() as i64),
        bind(rows)?,
        t(source),
        t(&text(job.get("id"))),
        t(&text(job.get("name"))),
        t(&writer::stamp(core)),
    ];
    writer::transact(core, |tx, _| {
        tx.execute(
            "INSERT OR REPLACE INTO rne_columns(rne_key,rne_path,rne_mtime_ns,rne_size,columns_json,column_count,row_count,source,job_id,job_name,captured_at) \
             VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            rusqlite::params_from_iter(row.clone()),
        )
        .map_err(|_| Pass)?;
        Ok(())
    })?;
    writer::mark_dirty(core);
    core.log(&format!(
        "COLUMN_CACHE_SAVE rne={rne_path} columns={} rows={} source={source} mtime_ns={mtime} size={size}",
        cols.len(),
        pyish::py_str(rows)
    ));
    Ok(Some(cols))
}

/// save_rne_timing（1回の実行の内訳。実行・保存のどちらも 0 なら残さない）。
pub fn save_rne_timing(core: &Core, rne_path: &str, execute: &Value, save: &Value, total: &Value, rows: &Value, cols: &Value) -> R<bool> {
    if !(pyish::truthy(execute) || pyish::truthy(save)) {
        return Ok(false);
    }
    let t = |x: &str| rusqlite::types::Value::Text(x.to_string());
    let row = vec![
        t(&rne_key(rne_path)),
        t(rne_path),
        bind(execute)?,
        bind(save)?,
        bind(total)?,
        bind(rows)?,
        bind(cols)?,
        t(&writer::stamp(core)),
    ];
    writer::transact(core, |tx, _| {
        tx.execute(
            "INSERT OR REPLACE INTO rne_timing(rne_key,rne_path,execute_seconds,save_seconds,total_seconds,rows,cols,measured_at) VALUES(?,?,?,?,?,?,?,?)",
            rusqlite::params_from_iter(row.clone()),
        )
        .map_err(|_| Pass)?;
        Ok(())
    })?;
    writer::mark_dirty(core);
    Ok(true)
}
