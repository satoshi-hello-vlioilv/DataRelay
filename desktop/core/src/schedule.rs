//! 予定の決まり（いつ実行するか）と、予定を読む受け口（2.21.0〜）。app.py の next_occurrence・expand_rule_occurrences・
//! job_schedule_preview・schedule_pause・last_run_info と、navi_web の /api/calendar・/api/schedule-preview・/api/job-trend と同じ答えを返す。
//!
//! 予定の型: daily（毎日）・weekdays（曜日。0=月）・monthly（月日。-1 は月末）・specific_dates（特定日）・interval（一定間隔・分）。
//! 予定を走らせる側（schedule_tick・鍵・取り直し）は、まだ Python が受け持つ（設定の書き込みと一緒にスケジューラーの段で移す）。
//!
//! Python の読み方に合わせる所: 曜日・日の値は数として等しければ当たる（1・1.0・True は同じ）。字の "1" は当たらない。
//! 時刻は "時:分" を int() で読み、読めなければ 6:00。読めても日時にできない値（25:00・-1:00）や、並べられない値（数の曜日）は、
//! Python が落ちる（500）ので Python へ回す。

use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{applog, pyish, routes::Core};
use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime, TimeZone};
use rusqlite::Connection;
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

// ==== ルールの読み方 ========================================================

fn kind(rule: &Value) -> Option<&str> {
    match rule.get("type") {
        None => Some("daily"),
        Some(v) => v.as_str(),
    }
}

fn enabled(rule: &Value, default: bool) -> bool {
    rule.get("enabled").map(pyish::truthy).unwrap_or(default)
}

/// `str(rule.get('time') or '06:00')` を "時:分" として int() で読む。読めなければ (6, 0)。
/// 大きすぎる数も Python は読める（日時を作るところで落ちる）ので、日時にできない値（i64::MAX）として持ち、作るときに Pass にする。
fn hour_minute(rule: &Value) -> R<(i64, i64)> {
    let tm = crate::naming::text_or(rule.get("time"), "06:00");
    let parts: Vec<&str> = tm.split(':').collect();
    if parts.len() != 2 {
        return Ok((6, 0));
    }
    let read = |p: &str| match pyish::int_text(p) {
        Ok(v) => v,
        Err(_) => Some(i64::MAX),
    };
    Ok(match (read(parts[0]), read(parts[1])) {
        (Some(h), Some(m)) => (h, m),
        _ => (6, 0),
    })
}

/// datetime(y, m, d, hh, mm)。日時にできなければ Python は ValueError（落ちる）→ Pass。
fn at(d: NaiveDate, hh: i64, mm: i64) -> R<NaiveDateTime> {
    if !(0..24).contains(&hh) || !(0..60).contains(&mm) {
        return Err(Pass);
    }
    d.and_hms_opt(hh as u32, mm as u32, 0).ok_or(Pass)
}

/// `max(1, int(rule.get('interval_minutes', 60) or 60))`。int() で読めなければ Python は落ちる → Pass。
fn interval_minutes(rule: &Value) -> R<i64> {
    let v = match rule.get("interval_minutes") {
        Some(v) if pyish::truthy(v) => v,
        _ => return Ok(60),
    };
    Ok(pyish::int_opt(v).map_err(|_| Pass)?.ok_or(Pass)?.max(1))
}

/// 数として等しいか（Python の == と hash: 1・1.0・True は同じ）。
fn num_eq(v: &Value, n: i64) -> bool {
    match v {
        Value::Bool(b) => i64::from(*b) == n,
        Value::Number(x) => x.as_i64().map(|i| i == n).unwrap_or_else(|| x.as_f64() == Some(n as f64)),
        _ => false,
    }
}

/// `set(v or [])`・`{… for x in v}` の要素。辞書の鍵にできない値（並び・辞書）があれば Python は落ちる → Pass。
fn hashable_items(v: Option<&Value>) -> R<Vec<Value>> {
    let items = pyish::py_iter(v).ok_or(Pass)?;
    if items.iter().any(|x| x.is_array() || x.is_object()) {
        return Err(Pass);
    }
    Ok(items)
}

/// 月日の決まり（-1 は月末）にこの日が当たるか。
fn month_day_hit(days: &[Value], d: NaiveDate) -> bool {
    let last = crate::period::last_day(i64::from(d.year()), d.month()) as i64;
    days.iter().any(|x| {
        let x = if num_eq(x, -1) { json!(last) } else { x.clone() };
        num_eq(&x, i64::from(d.day()))
    })
}

fn month_days(rule: &Value) -> R<Vec<Value>> {
    match rule.get("month_days") {
        Some(v) if pyish::truthy(v) => hashable_items(Some(v)),
        _ => Ok(vec![json!(1)]),
    }
}

/// 特定日の1つ（"YYYY-MM-DD" を int() で読む。読めなければ飛ばす＝None。読めても日付にできなければ Pass）。
fn specific_date(ds: &Value, hh: i64, mm: i64) -> R<Option<NaiveDateTime>> {
    let s = pyish::py_str(ds);
    let parts: Vec<&str> = s.split('-').collect();
    if parts.len() != 3 {
        return Ok(None);
    }
    let mut n = [0i64; 3];
    for (i, p) in parts.iter().enumerate() {
        match pyish::int_text(p) {
            Ok(Some(v)) => n[i] = v,
            Ok(None) => return Ok(None),
            Err(_) => return Err(Pass),
        }
    }
    let d = i32::try_from(n[0])
        .ok()
        .filter(|y| (1..=9999).contains(y))
        .and_then(|y| NaiveDate::from_ymd_opt(y, u32::try_from(n[1]).ok()?, u32::try_from(n[2]).ok()?))
        .ok_or(Pass)?;
    at(d, hh, mm).map(Some)
}

/// naive の日時を、この PC の時刻として通算秒にする（datetime.timestamp()）。
fn timestamp(dt: NaiveDateTime) -> R<i64> {
    chrono::Local.from_local_datetime(&dt).earliest().map(|t| t.timestamp()).ok_or(Pass)
}

fn from_timestamp(secs: i64) -> R<NaiveDateTime> {
    let t = chrono::Local.timestamp_opt(secs, 0).single().ok_or(Pass)?.naive_local();
    if (1..=9999).contains(&t.year()) {
        Ok(t)
    } else {
        Err(Pass)
    }
}

fn add_days(d: NaiveDateTime, n: i64) -> R<NaiveDateTime> {
    d.checked_add_signed(Duration::days(n)).filter(|x| (1..=9999).contains(&x.year())).ok_or(Pass)
}

/// next_occurrence（次に実行される日時。無効なルール・もう来ない予定は None）。
pub fn next_occurrence(rule: &Value, now: NaiveDateTime) -> R<Option<NaiveDateTime>> {
    if !enabled(rule, true) {
        return Ok(None);
    }
    let (hh, mm) = hour_minute(rule)?;
    match kind(rule) {
        Some("interval") => {
            let step = interval_minutes(rule)?.checked_mul(60).ok_or(Pass)?;
            let epoch = timestamp(now)?;
            from_timestamp((epoch.div_euclid(step) + 1).checked_mul(step).ok_or(Pass)?).map(Some)
        }
        Some("daily") => {
            let cand = at(now.date(), hh, mm)?;
            Ok(Some(if cand > now { cand } else { add_days(cand, 1)? }))
        }
        Some("weekdays") => {
            let days = match rule.get("weekdays") {
                Some(v) if pyish::truthy(v) => hashable_items(Some(v))?,
                _ => vec![],
            };
            if days.is_empty() {
                return Ok(None);
            }
            for add in 0..8 {
                let d = add_days(now, add)?;
                if days.iter().any(|x| num_eq(x, i64::from(d.weekday().num_days_from_monday()))) {
                    let cand = at(d.date(), hh, mm)?;
                    if cand > now {
                        return Ok(Some(cand));
                    }
                }
            }
            Ok(None)
        }
        Some("monthly") => {
            let days = month_days(rule)?;
            for add in 0..62 {
                let d = add_days(now, add)?.date();
                if month_day_hit(&days, d) {
                    let cand = at(d, hh, mm)?;
                    if cand > now {
                        return Ok(Some(cand));
                    }
                }
            }
            Ok(None)
        }
        Some("specific_dates") => {
            let mut best: Option<NaiveDateTime> = None;
            for ds in dates(rule)? {
                if let Some(cand) = specific_date(&ds, hh, mm)? {
                    if cand > now && best.is_none_or(|b| cand < b) {
                        best = Some(cand);
                    }
                }
            }
            Ok(best)
        }
        _ => Ok(None),
    }
}

fn dates(rule: &Value) -> R<Vec<Value>> {
    pyish::py_iter(rule.get("dates")).ok_or(Pass)
}

/// 一定間隔のルールの、日ごとの回数（カレンダーの要約）。
pub struct IntervalDay {
    pub date: NaiveDate,
    pub minutes: i64,
    pub count: i64,
}

/// expand_rule_occurrences（[start, end] の期間に実行される日時。一定間隔は日ごとの回数に集める）。
pub fn expand_rule_occurrences(
    rule: &Value,
    start: NaiveDateTime,
    end: NaiveDateTime,
    limit: usize,
) -> R<(Vec<NaiveDateTime>, Vec<IntervalDay>)> {
    if !enabled(rule, true) {
        return Ok((vec![], vec![]));
    }
    let (hh, mm) = hour_minute(rule)?;
    let (first, last) = (start.date(), end.date());
    let each_day = || first.iter_days().take_while(move |d| *d <= last);
    let mut points = Vec::new();
    match kind(rule) {
        Some("interval") => {
            let mins = interval_minutes(rule)?;
            let per_day = ((24 * 60) / mins).max(1);
            return Ok((vec![], each_day().map(|date| IntervalDay { date, minutes: mins, count: per_day }).collect()));
        }
        Some("weekdays") => {
            let wd = match rule.get("weekdays") {
                Some(v) if pyish::truthy(v) => hashable_items(Some(v))?,
                _ => vec![],
            };
            for d in each_day() {
                if wd.iter().any(|x| num_eq(x, i64::from(d.weekday().num_days_from_monday()))) {
                    points.push(at(d, hh, mm)?);
                }
            }
        }
        Some("daily") => {
            for d in each_day() {
                points.push(at(d, hh, mm)?);
            }
        }
        Some("monthly") => {
            let days = month_days(rule)?;
            for d in each_day() {
                if month_day_hit(&days, d) {
                    points.push(at(d, hh, mm)?);
                }
            }
        }
        Some("specific_dates") => {
            for ds in dates(rule)? {
                if let Some(cand) = specific_date(&ds, hh, mm)? {
                    if start <= cand && cand <= end {
                        points.push(cand);
                    }
                }
            }
        }
        _ => {}
    }
    points.truncate(limit);
    Ok((points, vec![]))
}

/// job_schedule_hint（一覧の「予定」の短い言い方）。
fn schedule_hint(rules: &[&Value]) -> R<Value> {
    let Some(r) = rules.first() else { return Ok(json!("手動のみ")) };
    if rules.len() > 1 {
        return Ok(json!(format!("複数指定 ({}件)", rules.len())));
    }
    let k = match r.get("type") {
        None => json!("daily"),
        Some(v) if v.is_array() || v.is_object() => return Err(Pass), // 辞書の鍵にできない（Python は落ちる）
        Some(v) => v.clone(),
    };
    Ok(match k.as_str() {
        Some("interval") => json!(format!("定期 ({}分ごと)", interval_minutes(r)?)),
        Some("daily") => json!("毎日"),
        Some("weekdays") => json!("曜日指定"),
        Some("monthly") => json!("月日指定"),
        Some("specific_dates") => json!("特定日"),
        _ => k,
    })
}

fn minutes_iso(dt: NaiveDateTime) -> String {
    dt.format("%Y-%m-%dT%H:%M").to_string()
}

/// job_schedule_preview（次に実行される日時と、予定の言い方）。
pub fn job_schedule_preview(job: &Value, now: NaiveDateTime) -> R<Map<String, Value>> {
    let id = job.get("id").cloned().unwrap_or(Value::Null);
    let mut out = Map::new();
    out.insert("id".into(), id);
    if !enabled(job, false) {
        out.insert("next_run".into(), Value::Null);
        out.insert("hint".into(), json!("対象が無効"));
        return Ok(out);
    }
    let rules: Vec<&Value> = schedules(job).iter().filter(|r| enabled(r, false)).collect();
    let mut next: Option<NaiveDateTime> = None;
    for r in &rules {
        if let Some(c) = next_occurrence(r, now)? {
            next = Some(next.map_or(c, |n: NaiveDateTime| n.min(c)));
        }
    }
    out.insert("next_run".into(), next.map(|n| json!(minutes_iso(n))).unwrap_or(Value::Null));
    out.insert("hint".into(), schedule_hint(&rules)?);
    Ok(out)
}

fn schedules(job: &Value) -> &[Value] {
    job.get("schedules").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

fn jobs(cfg: &Map<String, Value>) -> &[Value] {
    cfg.get("jobs").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

// ==== 一時停止と、前回の実行 ================================================

const PAUSE_KEY: &str = "__pause__";

/// datetime.fromisoformat のうち、一時停止の「再開する時刻」に書く形（YYYY-MM-DD・…THH:MM・…THH:MM:SS(.f)）。
/// ほかの形（時差付きなど）は Python と同じに読めると言えないので None（呼ぶ側が Pass にする）。
fn from_iso(s: &str) -> Option<Result<NaiveDateTime, ()>> {
    // YYYY-MM-DD と、区切りの無い YYYYMMDD（Python 3.11 から読める）
    for (f, n) in [("%Y-%m-%d", 10), ("%Y%m%d", 8)] {
        if let Ok(d) = NaiveDate::parse_from_str(s, f) {
            if s.len() == n {
                return Some(Ok(d.and_hms_opt(0, 0, 0)?));
            }
        }
    }
    for f in ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"] {
        if let Ok(t) = NaiveDateTime::parse_from_str(s, f) {
            return Some(Ok(t));
        }
    }
    // 年月日の形ですらない字は、Python も ValueError（読めない）
    if !s.bytes().take(4).all(|b| b.is_ascii_digit()) || s.len() < 4 {
        return Some(Err(()));
    }
    None
}

/// schedule_pause（いまの一時停止。再開する時刻を過ぎていれば paused=false・expired=true）。
pub fn schedule_pause(state: &Map<String, Value>, now: NaiveDateTime) -> R<Map<String, Value>> {
    let off = || {
        let mut m = Map::new();
        m.insert("paused".into(), json!(false));
        m.insert("since".into(), json!(""));
        m.insert("until".into(), json!(""));
        m.insert("expired".into(), json!(false));
        m
    };
    let raw = match state.get(PAUSE_KEY) {
        Some(v) if pyish::truthy(v) => v,
        _ => return Ok(off()),
    };
    let Value::String(text) = raw else { return Err(Pass) }; // json.loads(数) は TypeError（Python は落ちる）
    let p = match config::py_json(text) {
        config::Json::Ok(v) => v,
        config::Json::Bad => return Ok(off()),
        config::Json::Unsure => return Err(Pass),
    };
    let Some(p) = p.as_object().filter(|p| p.get("since").is_some_and(pyish::truthy)) else { return Ok(off()) };
    let mut until = pyish::text_or_empty(p.get("until"));
    let over = if until.is_empty() {
        false
    } else {
        match from_iso(&until) {
            Some(Ok(t)) => t <= now,
            Some(Err(())) => {
                until.clear();
                false
            }
            None => return Err(Pass),
        }
    };
    let mut m = Map::new();
    m.insert("paused".into(), json!(!over));
    m.insert("since".into(), json!(pyish::py_str(&p["since"])));
    m.insert("until".into(), json!(until));
    m.insert("expired".into(), json!(over));
    Ok(m)
}

/// last_run_info（一覧の「前回」の欄）。
pub fn last_run_info(run: Option<&Map<String, Value>>) -> R<Map<String, Value>> {
    let mut out = Map::new();
    let Some(run) = run else {
        for (k, v) in [
            ("last_run", Value::Null),
            ("last_status", json!("")),
            ("last_trigger", json!("")),
            ("last_output", json!("")),
            ("last_metrics", json!({})),
        ] {
            out.insert(k.into(), v);
        }
        return Ok(out);
    };
    let trig = pyish::text_or_empty(run.get("trigger"));
    let mut m = match run.get("metrics") {
        Some(v) if pyish::truthy(v) => crate::secret::py_dict(v).map_err(|_| Pass)?,
        _ => Map::new(),
    };
    for k in ["rows", "cols"] {
        if let Some(v) = run.get(k).filter(|v| !v.is_null()) {
            m.entry(k).or_insert(v.clone());
        }
    }
    let or_empty = |k: &str| run.get(k).filter(|v| pyish::truthy(v)).cloned().unwrap_or(json!(""));
    out.insert("last_run".into(), run.get("finished_at").cloned().unwrap_or(Value::Null));
    out.insert("last_status".into(), or_empty("status"));
    out.insert("last_trigger".into(), json!(if trig.starts_with("schedule") { "schedule" } else { "manual" }));
    out.insert("last_output".into(), or_empty("output_file"));
    out.insert("last_detail".into(), or_empty("detail"));
    out.insert("last_metrics".into(), Value::Object(m));
    Ok(out)
}

/// load_job_runs（対象ごとの最後の実行。鍵は job_id の値そのもの）。
fn job_runs(c: &Connection) -> R<Vec<(Value, Map<String, Value>)>> {
    let mut out = Vec::new();
    for r in config::rows(c, "SELECT * FROM job_runs", &[])? {
        let mut run = Map::new();
        for k in ["finished_at", "status", "trigger", "detail", "rows", "cols", "output_file"] {
            run.insert(k.into(), r.get(k).cloned().unwrap_or(Value::Null));
        }
        run.insert("metrics".into(), config::json_or_empty(Some(r.get("metrics").unwrap_or(&json!(""))))?);
        let key = r.get("job_id").cloned().unwrap_or(Value::Null);
        // 同じ鍵が2つあれば、後の行が勝つ（dict の内包と同じ）
        out.retain(|(k, _): &(Value, Map<String, Value>)| k != &key);
        out.push((key, run));
    }
    Ok(out)
}

fn scheduler_state(c: &Connection) -> R<Map<String, Value>> {
    let mut m = Map::new();
    for r in config::rows(c, "SELECT * FROM scheduler_state", &[])? {
        let Some(Value::String(k)) = r.get("state_key") else { return Err(Pass) };
        m.insert(k.clone(), r.get("state_value").cloned().unwrap_or(Value::Null));
    }
    Ok(m)
}

// ==== 受け口 ================================================================

/// GET /api/schedule-preview … 対象ごとの次回の予定と前回の実行、一時停止の状態。
pub(crate) fn get_schedule_preview(core: &Core, _: &Ask, _: &[String]) -> Reply {
    answer_preview(core).unwrap_or_else(|_| Reply::pass())
}

fn answer_preview(core: &Core) -> R<Reply> {
    let (cfg, (runs, state)) = config::read_with(core, |_, c| Ok((job_runs(c)?, scheduler_state(c)?)))?;
    let now = core.now();
    let mut items = Vec::new();
    for j in jobs(&cfg) {
        let mut item = job_schedule_preview(j, now)?;
        let run = runs.iter().find(|(k, _)| Some(k) == j.get("id")).map(|(_, r)| r);
        item.extend(last_run_info(run)?);
        items.push(Value::Object(item));
    }
    let mut pause = schedule_pause(&state, now)?;
    let live: Vec<&Value> = jobs(&cfg).iter().filter(|j| enabled(j, false) && schedules(j).iter().any(|r| enabled(r, false))).collect();
    pause.insert("jobs".into(), json!(live.len()));
    pause.insert("rules".into(), json!(live.iter().map(|j| schedules(j).iter().filter(|r| enabled(r, false)).count()).sum::<usize>()));
    Ok(Reply::json(200, &json!({"items": items, "pause": pause})))
}

/// カレンダーの一定間隔の要約の1日分（日付, 回数の合計, (対象とルールの鍵, 内訳) の並び）。
type DaySummary = (String, i64, Vec<(String, Value)>);

/// GET /api/calendar … 指定月の予定（scheduled・一定間隔の要約 interval）と実施の記録（executed）。
pub(crate) fn get_calendar(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_calendar(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_calendar(core: &Core, ask: &Ask) -> R<Reply> {
    let now = core.now();
    // int(request.args.get('year'))・int(…('month'))。どちらかが読めなければ、両方とも今月
    let num = |k: &str| -> R<Option<i64>> {
        match applog::query_arg(ask.query, k) {
            None => Ok(None),
            Some(s) => pyish::int_text(&s).map_err(|_| Pass),
        }
    };
    let (year, month) = match (num("year")?, num("month")?) {
        (Some(y), Some(m)) => (y, m),
        _ => (i64::from(now.year()), i64::from(now.month())),
    };
    let month = month.clamp(1, 12) as u32;
    let year = i32::try_from(year).ok().filter(|y| (1..=9999).contains(y)).ok_or(Pass)?;
    let first = NaiveDate::from_ymd_opt(year, month, 1).ok_or(Pass)?;
    let last_day = crate::period::last_day(i64::from(year), month);
    let start = first.and_hms_opt(0, 0, 0).ok_or(Pass)?;
    let end = NaiveDate::from_ymd_opt(year, month, last_day).and_then(|d| d.and_hms_opt(23, 59, 59)).ok_or(Pass)?;
    let range = (start.format("%Y-%m-%dT00:00:00").to_string(), end.format("%Y-%m-%dT23:59:59").to_string());
    let (cfg, history) = config::read_with(core, |_, c| {
        config::rows(
            c,
            "SELECT id,job_id,job_name,finished_at,status,trigger,rows,cols,output_file FROM run_history WHERE finished_at>=? AND finished_at<=? ORDER BY finished_at",
            &[rusqlite::types::Value::Text(range.0.clone()), rusqlite::types::Value::Text(range.1.clone())],
        )
    })?;
    let mut scheduled = Vec::new();
    // 日ごとの一定間隔の要約（日付の出てきた順。中は (対象, ルール) ごと）
    let mut interval: Vec<DaySummary> = Vec::new();
    for j in jobs(&cfg) {
        if !enabled(j, false) {
            continue;
        }
        for r in schedules(j) {
            if !enabled(r, false) {
                continue;
            }
            let (points, days) = expand_rule_occurrences(r, start, end, 400)?;
            for p in points {
                scheduled.push(json!({
                    "date": p.format("%Y-%m-%d").to_string(), "time": p.format("%H:%M").to_string(), "datetime": minutes_iso(p),
                    "job_id": j.get("id"), "job_name": j.get("name"), "rule_id": r.get("id"),
                    "rule_name": r.get("name").cloned().unwrap_or(json!("")), "rule_type": r.get("type").cloned().unwrap_or(json!("")),
                    "past": p < now,
                }));
            }
            for d in days {
                let key = d.date.format("%Y-%m-%d").to_string();
                let pos = match interval.iter().position(|(k, _, _)| *k == key) {
                    Some(i) => i,
                    None => {
                        interval.push((key, 0, vec![]));
                        interval.len() - 1
                    }
                };
                let rule_id = r.get("id").filter(|v| pyish::truthy(v)).cloned().unwrap_or(json!(""));
                let slot = format!("{}\u{0}{}", j.get("id").map(Value::to_string).unwrap_or_default(), rule_id);
                let entry = &mut interval[pos];
                if !entry.2.iter().any(|(k, _)| *k == slot) {
                    entry.2.push((
                        slot,
                        json!({"job_id": j.get("id"), "job_name": j.get("name"), "rule_name": r.get("name").cloned().unwrap_or(json!("")),
                               "minutes": d.minutes, "count": d.count}),
                    ));
                }
                entry.1 += d.count;
            }
        }
    }
    let interval: Vec<Value> = interval
        .into_iter()
        .map(|(date, total, items)| json!({"date": date, "total": total, "items": items.into_iter().map(|(_, v)| v).collect::<Vec<_>>()}))
        .collect();
    let mut executed = Vec::new();
    for row in history {
        let fa = pyish::text_or_empty(row.get("finished_at"));
        if fa.chars().count() < 10 {
            continue;
        }
        let trig = pyish::text_or_empty(row.get("trigger"));
        executed.push(json!({
            "id": row.get("id"), "date": pyish::slice(&fa, None, Some(10)), "time": pyish::slice(&fa, Some(11), Some(16)), "datetime": fa,
            "job_id": row.get("job_id"), "job_name": row.get("job_name"), "status": row.get("status"),
            "trigger": if trig.starts_with("schedule") { "schedule" } else { "manual" },
            "rows": row.get("rows"), "cols": row.get("cols"), "output_file": row.get("output_file"),
        }));
    }
    Ok(Reply::json(
        200,
        &json!({
            "year": year, "month": month, "days_in_month": last_day, "first_weekday": first.weekday().num_days_from_monday(),
            "today": now.format("%Y-%m-%d").to_string(), "scheduled": scheduled, "interval": interval, "executed": executed,
        }),
    ))
}

/// 実行の記録の detail から、かかった秒（「/ 12.3秒」）を拾う（正規表現 `/\s*([\d.]+)秒` と float()）。
pub fn seconds_in(detail: &str) -> Option<f64> {
    let chars: Vec<char> = detail.chars().collect();
    for (i, c) in chars.iter().enumerate() {
        if *c != '/' {
            continue;
        }
        let mut j = i + 1;
        while j < chars.len() && pyish::is_space(chars[j]) {
            j += 1;
        }
        let k0 = j;
        while j < chars.len() && (chars[j] == '.' || pyish::digit(chars[j]).is_some()) {
            j += 1;
        }
        if j > k0 && chars.get(j) == Some(&'秒') {
            let text: String = chars[k0..j].iter().map(|c| pyish::digit(*c).map(|d| char::from(b'0' + d as u8)).unwrap_or(*c)).collect();
            return text.parse::<f64>().ok().filter(|f| f.is_finite());
        }
    }
    None
}

/// GET /api/job-trend/<job_id> … 直近の実績の並び（件数・かかった秒の移り変わり）。
pub(crate) fn get_job_trend(core: &Core, ask: &Ask, params: &[String]) -> Reply {
    answer_trend(core, ask, params).unwrap_or_else(|_| Reply::pass())
}

fn answer_trend(core: &Core, ask: &Ask, params: &[String]) -> R<Reply> {
    let job_id = params.first().cloned().unwrap_or_default();
    // max(5, min(200, int(request.args.get('limit') or 30)))。読めない数は Python が落ちる（500）
    let limit = match applog::query_arg(ask.query, "limit").filter(|s| !s.is_empty()) {
        None => 30,
        Some(s) => match pyish::int_text(&s) {
            Ok(Some(v)) => v,
            Ok(None) => return Err(Pass),
            Err(_) => {
                if pyish::strip(&s).starts_with('-') {
                    5
                } else {
                    200
                }
            }
        },
    }
    .clamp(5, 200);
    let (_, rows) = config::read_with(core, |_, c| {
        config::rows(
            c,
            "SELECT finished_at,status,rows,cols,detail FROM run_history WHERE job_id=? ORDER BY id DESC LIMIT ?",
            &[rusqlite::types::Value::Text(job_id.clone()), rusqlite::types::Value::Integer(limit)],
        )
    })?;
    let mut items: Vec<Value> = rows
        .iter()
        .map(|r| {
            let sec = seconds_in(&pyish::text_or_empty(r.get("detail")));
            json!({"at": r.get("finished_at"), "status": r.get("status"), "rows": r.get("rows"), "cols": r.get("cols"), "seconds": sec})
        })
        .collect();
    items.reverse();
    let counts: Vec<i64> = items.iter().filter_map(|x| x["rows"].as_i64()).collect();
    let secs: Vec<f64> = items.iter().filter_map(|x| x["seconds"].as_f64()).collect();
    let failed = items.iter().filter(|x| x["status"] == json!("failed")).count();
    Ok(Reply::json(
        200,
        &json!({
            "ok": true, "count": items.len(), "items": items, "failed": failed,
            "rows_spread": spread(&counts.iter().map(|v| json!(v)).collect::<Vec<_>>(), counts.iter().map(|v| *v as f64).collect()),
            "seconds_spread": spread(&secs.iter().map(|v| json!(v)).collect::<Vec<_>>(), secs.clone()),
        }),
    ))
}

/// spread（2 件以上あるときの、最小・最大・最初・最後と、最初からの変わり方 %）。
fn spread(values: &[Value], nums: Vec<f64>) -> Value {
    if nums.len() < 2 {
        return json!({});
    }
    let (imin, imax) =
        (0..nums.len()).fold((0, 0), |(a, b), i| (if nums[i] < nums[a] { i } else { a }, if nums[i] > nums[b] { i } else { b }));
    let (first, last) = (nums[0], nums[nums.len() - 1]);
    json!({
        "min": values[imin], "max": values[imax], "first": values[0], "last": values[values.len() - 1],
        "change": if first != 0.0 { json!(applog::round1((last - first) / first * 100.0)) } else { Value::Null },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(s: &str) -> NaiveDateTime {
        NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M").unwrap()
    }

    #[test]
    fn next_like_python() {
        let now = t("2026-11-02T09:00"); // 月曜
        let r = |v: Value| next_occurrence(&v, now).unwrap().map(minutes_iso);
        assert_eq!(r(json!({"type": "daily", "time": "06:00", "enabled": true})), Some("2026-11-03T06:00".into()));
        assert_eq!(r(json!({"type": "weekdays", "time": "10:00", "weekdays": [0, 1.0]})), Some("2026-11-02T10:00".into()));
        assert_eq!(r(json!({"type": "weekdays", "weekdays": ["0"]})), None, "字の曜日は当たらない");
        assert_eq!(r(json!({"type": "monthly", "time": "07:30", "month_days": [-1]})), Some("2026-11-30T07:30".into()));
        assert_eq!(r(json!({"type": "specific_dates", "dates": ["2026-12-01", "x", "2026-11-01"]})), Some("2026-12-01T06:00".into()));
        assert_eq!(r(json!({"type": "daily", "time": "bad"})), Some("2026-11-03T06:00".into()), "読めない時刻は 6:00");
        assert!(next_occurrence(&json!({"type": "daily", "time": "25:00"}), now).is_err(), "日時にできない時刻は Python が落ちる");
        assert!(next_occurrence(&json!({"type": "weekdays", "weekdays": 3}), now).is_err());
    }

    #[test]
    fn seconds_like_python() {
        assert_eq!(seconds_in("120行 / 12.5秒"), Some(12.5));
        assert_eq!(seconds_in("a/ １２秒"), Some(12.0));
        assert_eq!(seconds_in("/1.2.3秒"), None);
        assert_eq!(seconds_in("/x / 3秒"), Some(3.0));
    }
}
