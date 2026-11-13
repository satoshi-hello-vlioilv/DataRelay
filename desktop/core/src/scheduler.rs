//! 予定実行の巡回（2.42.0〜）。app.py の schedule_key・schedule_tick・missed_schedules と同じ決まり。
//! まだ使わない（受け口と巡回のスレッドを Rust へ移して切り替えるのは 5e-2c）。
//!
//! 巡回1回（tick）でやること:
//!   1. 一時停止の再開の時刻が過ぎていれば、一時停止を解いて知らせる
//!   2. 時刻が来た取り直しを先に流す（一時停止中は飛ばす）
//!   3. 対象ごとの予定（ルール）の鍵を作り、前回の鍵と違えば「時刻が来た」として鍵を進める
//!      （一定間隔の予定を初めて見たときは、いまの区切りを済んだことにして次の境界から動かす）
//!   4. 時刻が来た対象をまとめて1つの指令にして、待機キューへ入れる（一時停止中は飛ばす。鍵は進める）
//!
//! 実行中に時刻が過ぎて猶予も切れた予定は、手が空いたところで missed で洗い出して知らせる。
use crate::config::{self, Pass};
use crate::runner::Runner;
use crate::{commands, pyish, routes::Core, schedule, writer};
use chrono::{Datelike, NaiveDateTime, TimeZone};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

/// 一時停止の鍵（app.SCHEDULE_PAUSE_KEY）。
pub const PAUSE_KEY: &str = "__pause__";

fn text(v: Option<&Value>, default: &str) -> String {
    match v {
        None => default.into(),
        Some(v) => pyish::py_str(v),
    }
}

/// int(x)。読めなければ Pass（Python は例外で、その巡回を落とす）。
fn int(v: &Value) -> R<i64> {
    pyish::int_opt(v).ok().flatten().ok_or(Pass)
}

/// 'HH:MM' の時と分（':' が無ければ 6:00。読めなければ Pass）。
fn hour_minute(tm: &str) -> R<(u32, u32)> {
    let Some((h, m)) = tm.split_once(':') else { return Ok((6, 0)) };
    if m.contains(':') {
        return Err(Pass);
    }
    let h = int(&json!(h))?;
    let m = int(&json!(m))?;
    if !(0..24).contains(&h) || !(0..60).contains(&m) {
        return Err(Pass);
    }
    Ok((h as u32, m as u32))
}

/// datetime.timestamp()（その PC の時刻帯として読む）。
fn epoch(now: NaiveDateTime) -> i64 {
    chrono::Local.from_local_datetime(&now).earliest().map(|d| d.timestamp()).unwrap_or_else(|| now.and_utc().timestamp())
}

/// schedule_key（このルールの「いまの回」を表す鍵。時刻が来ていなければ None）。
/// 予定時刻からの猶予（grace 分。最低 1 分）のうちは同じ鍵を返すので、猶予中に何度見ても1日1回しか当たらない。日をまたいだ猶予はしない。
pub fn schedule_key(rule: &Map<String, Value>, now: NaiveDateTime, grace_minutes: i64) -> R<Option<String>> {
    let kind = text(rule.get("type"), "daily");
    // rule.get('time','06:00')。null は Python で ':' in None が例外になる
    let tm = match rule.get("time") {
        None => "06:00".to_string(),
        Some(Value::String(t)) => t.clone(),
        Some(_) => return Err(Pass),
    };
    let (hh, mm) = hour_minute(&tm)?;
    if kind == "interval" {
        let mins = int(rule.get("interval_minutes").unwrap_or(&json!(60)))?.max(1);
        return Ok(rule.get("enabled").is_some_and(pyish::truthy).then(|| (epoch(now).div_euclid(mins * 60)).to_string()));
    }
    let scheduled = now.date().and_hms_opt(hh, mm, 0).ok_or(Pass)?;
    let delay = (now - scheduled).num_microseconds().unwrap_or(0) as f64 / 1e6;
    if delay < 0.0 || delay >= (grace_minutes * 60).max(60) as f64 {
        return Ok(None);
    }
    let day = now.format("%Y-%m-%d").to_string();
    let key = Some(format!("{day}{tm}"));
    let list = |k: &str| rule.get(k).and_then(Value::as_array).cloned();
    Ok(match kind.as_str() {
        "daily" => key,
        "weekdays" => list("weekdays").unwrap_or_default().contains(&json!(now.weekday().num_days_from_monday())).then_some(key).flatten(),
        "monthly" => {
            let last = last_day(now.year(), now.month());
            let days = list("month_days").filter(|d| !d.is_empty()).unwrap_or_else(|| vec![json!(1)]);
            days.iter().any(|x| (if *x == json!(-1) { json!(last) } else { x.clone() }) == json!(now.day())).then_some(key).flatten()
        }
        "specific_dates" => list("dates").unwrap_or_default().contains(&json!(day)).then_some(key).flatten(),
        _ => None,
    })
}

fn last_day(y: i32, m: u32) -> u32 {
    let (ny, nm) = if m == 12 { (y + 1, 1) } else { (y, m + 1) };
    chrono::NaiveDate::from_ymd_opt(ny, nm, 1).and_then(|d| d.pred_opt()).map(|d| d.day()).unwrap_or(28)
}

/// save_scheduler_state（予定の鍵・一時停止を残す）。
pub fn save_state(core: &Core, key: &str, value: &str) -> R<()> {
    let at = writer::stamp(core);
    writer::transact(core, |tx, _| {
        tx.execute("INSERT OR REPLACE INTO scheduler_state VALUES(?,?,?)", rusqlite::params![key, value, at]).map_err(|_| Pass)?;
        Ok(())
    })?;
    writer::mark_dirty(core);
    Ok(())
}

fn jobs(cfg: &Map<String, Value>) -> Vec<Map<String, Value>> {
    cfg.get("jobs").and_then(Value::as_array).into_iter().flatten().filter_map(|j| j.as_object().cloned()).collect()
}

fn rules(job: &Map<String, Value>) -> Vec<Map<String, Value>> {
    job.get("schedules").and_then(Value::as_array).into_iter().flatten().filter_map(|r| r.as_object().cloned()).collect()
}

fn state_key(job: &Map<String, Value>, rule: &Map<String, Value>) -> String {
    format!("{}:{}", text(job.get("id"), ""), text(rule.get("id"), ""))
}

/// missed_schedules（実行中に時刻が過ぎ、猶予も切れた予定。(対象の名前, ルールの名前, 'YYYY-MM-DD HH:MM')）。
pub fn missed(
    cfg: &Map<String, Value>,
    st: &Map<String, Value>,
    since: NaiveDateTime,
    now: NaiveDateTime,
    catchup: i64,
) -> Vec<(String, String, String)> {
    let limit = (catchup * 60).max(60);
    let mut out = vec![];
    for j in jobs(cfg).iter().filter(|j| j.get("enabled").is_some_and(pyish::truthy)) {
        for r in rules(j) {
            if !r.get("enabled").is_some_and(pyish::truthy) || text(r.get("type"), "") == "interval" {
                continue;
            }
            let tm = r.get("time").filter(|v| pyish::truthy(v)).map(pyish::py_str).unwrap_or_else(|| "06:00".into());
            let Ok((points, _)) = schedule::expand_rule_occurrences(&Value::Object(r.clone()), since, now, 50) else { continue };
            for pt in points {
                if (now - pt).num_seconds() < limit {
                    continue;
                }
                if st.get(&state_key(j, &r)) == Some(&json!(format!("{}{tm}", pt.format("%Y-%m-%d")))) {
                    continue;
                }
                out.push((text(j.get("name"), ""), text(r.get("name").or(r.get("type")), ""), pt.format("%Y-%m-%d %H:%M").to_string()));
            }
        }
    }
    out
}

/// schedule_tick（予定の判定を1回まわす）。{'paused','enqueued','skipped','retries'}。st は予定の状態（鍵を進めると書き換える）。
pub fn tick(core: &Core, runner: &Runner, cfg: &Map<String, Value>, st: &mut Map<String, Value>, now: NaiveDateTime) -> R<Value> {
    let pause = schedule::schedule_pause(st, now)?;
    let paused = pause.get("paused").is_some_and(pyish::truthy);
    if pause.get("expired").is_some_and(pyish::truthy) {
        save_state(core, PAUSE_KEY, "{}")?;
        st.insert(PAUSE_KEY.into(), json!("{}"));
        let until = pyish::text_or_empty(pause.get("until")).replace('T', " ");
        core.log(&format!("SCHEDULE_PAUSE_ENDED reason=再開の時刻 until={until}"));
        runner.lock_cmds(|c| {
            c.add_alert("info", "自動実行を再開しました", &format!("{until} に再開する設定でした"), &[], now);
        });
    }
    let mut out = json!({"paused": paused, "enqueued": [], "skipped": [], "retries": 0});
    // 取り直しは予定より先に流す（待たせるほどデータが古いままになる）
    for r in runner.lock_cmds(|c| c.due_retries(now)) {
        if paused {
            out["retries"] = json!(out["retries"].as_i64().unwrap_or(0) + 1);
            core.log(&format!("RETRY_SKIPPED jobs={:?} attempt={} reason=自動実行の一時停止中", r.names, r.attempt));
            continue;
        }
        let ids: Vec<String> = r.job_ids.iter().map(pyish::py_str).collect();
        match runner.enqueue(core, &ids, &format!("schedule-retry:{}", r.attempt), Some(&r.lines), r.attempt) {
            Ok(_) => core.log(&format!("RETRY_ENQUEUED jobs={:?} attempt={}", r.names, r.attempt)),
            Err(e) => core.log(&format!("RETRY_ENQUEUE_FAILED jobs={:?} error={e}", r.names)),
        }
    }
    let s = cfg.get("settings").and_then(Value::as_object).cloned().unwrap_or_default();
    let catchup = catchup_of(&s)?;
    let (mut due_ids, mut due_rules): (Vec<String>, Vec<String>) = (vec![], vec![]);
    for j in jobs(cfg).iter().filter(|j| j.get("enabled").is_some_and(pyish::truthy)) {
        for r in rules(j) {
            if !r.get("enabled").is_some_and(pyish::truthy) {
                continue;
            }
            let Some(key) = schedule_key(&r, now, catchup)? else { continue };
            let sk = state_key(j, &r);
            if st.get(&sk) == Some(&json!(key)) {
                continue;
            }
            let first_seen = !st.contains_key(&sk);
            st.insert(sk.clone(), json!(key));
            save_state(core, &sk, &key)?;
            let rule_name = text(r.get("name").or(r.get("type")), "");
            if first_seen && text(r.get("type"), "") == "interval" {
                // いまの区切りを済んだことにして、次の境界から動かす（登録した直後に、予告の時刻を待たずに走り出さない）
                core.log(&format!("SCHEDULE_INTERVAL_ARMED job={} rule={rule_name}（次の区切りから動きます）", text(j.get("name"), "")));
                continue;
            }
            // 同じ対象は1回だけ入れる。鍵は当たったルールぶん全部進める（でないと次の巡回で二重に走る）
            let id = text(j.get("id"), "");
            if !due_ids.contains(&id) {
                due_ids.push(id);
                due_rules.push(rule_name);
            }
        }
    }
    if !due_ids.is_empty() && paused {
        out["skipped"] = json!(due_ids);
        core.log(&format!("SCHEDULE_PAUSED_SKIP jobs={due_ids:?} rules={due_rules:?}（一時停止中のため飛ばしました）"));
    } else if !due_ids.is_empty() {
        let lines = commands::clamp_lines(s.get("api_parallel_lines"), cfg, 1);
        core.log(&format!("SCHEDULE_BATCH_READY jobs={due_ids:?} count={} rules={due_rules:?} parallel_lines={lines}", due_ids.len()));
        out["enqueued"] = json!(due_ids);
        if let Err(e) = runner.enqueue(core, &due_ids, &format!("schedule-batch:{}", due_ids.len()), Some(&json!(lines)), 0) {
            core.log(&format!("SCHEDULE_ENQUEUE_FAILED jobs={due_ids:?} error={e}"));
        }
    }
    Ok(out)
}

/// 手が空いたところで、実行中に猶予の切れた予定を知らせる（scheduler の busy_since のところ）。知らせた数。
pub fn report_missed(
    core: &Core,
    runner: &Runner,
    cfg: &Map<String, Value>,
    st: &Map<String, Value>,
    since: NaiveDateTime,
    now: NaiveDateTime,
) -> usize {
    let s = cfg.get("settings").and_then(Value::as_object).cloned().unwrap_or_default();
    let Ok(catchup) = catchup_of(&s) else { return 0 };
    let gone = missed(cfg, st, since, now, catchup);
    if gone.is_empty() {
        return 0;
    }
    for (n, r, w) in &gone {
        core.log(&format!("SCHEDULE_MISSED job={n} rule={r} scheduled={w} reason=実行中に猶予切れ"));
    }
    let five = gone.iter().take(5).map(|(n, _, w)| format!("{n}（{w}）")).collect::<Vec<_>>().join("・");
    let names: Vec<Value> = gone.iter().map(|(n, _, _)| json!(n)).collect();
    runner.lock_cmds(|c| {
        c.add_alert(
            "warn",
            &format!("{}件の予定を実行できませんでした", gone.len()),
            &format!("{five}（別の処理が実行中のまま猶予時間を過ぎました。必要なら手で実行してください）"),
            &names,
            now,
        );
    });
    gone.len()
}

/// int(settings.get('schedule_catchup_minutes', 30) or 0)（予定時刻からの猶予の分）。
fn catchup_of(s: &Map<String, Value>) -> R<i64> {
    match s.get("schedule_catchup_minutes") {
        None => Ok(30),
        Some(v) if pyish::truthy(v) => int(v),
        _ => Ok(0),
    }
}

/// 予定の状態を読む（load_scheduler_state）。
pub fn load_state(core: &Core) -> R<Map<String, Value>> {
    Ok(config::read_with(core, |_, c| schedule::scheduler_state(c))?.1)
}
