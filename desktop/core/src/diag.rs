//! 設定が本当に使えるか・データが新しいかを読む受け口のうち、設定と記録とファイルから答えられる物（2.33.0〜）。
//! lib/navi_diag.py（freshness_view・fresh_expectation・observed_gap_minutes・check_path_item）と、app.schedule_gap_minutes、
//! lib/navi_web.py の freshness・path_check・apply_path_suggestion と同じ答えを返す。
//!
//!   - GET  /api/freshness             … 有効な対象ごとに、いまのデータがいつのものか（予定・実績の間隔から「古い」を見分ける）
//!   - POST /api/path-check            … symnavim.conf・ACCDB の空テンプレート・対象の RNE が在るか（探した場所の並びも）
//!   - POST /api/apply-path-suggestion … 見つけた候補を設定へ書く（置き場の中なら .\… の書き方で持つ）
//!
//! 見つからない物の近くを探す（find_nearby_file。フォルダーを深く歩く順が Python の版で違う）は Python へ回す。
use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{paths, pyish, routes::Core, schedule, writer};
use chrono::NaiveDateTime;
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

/// 予定も実績の間隔も無い対象の「新しいと言える」目安（3日・分）。
const MANUAL_FRESH_DEFAULT: i64 = 4320;

fn jobs(cfg: &Map<String, Value>) -> &[Value] {
    cfg.get("jobs").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

/// int(v)（読めなければ Python が落ちるので Pass）。
fn int(v: &Value) -> R<i64> {
    pyish::int_opt(v).ok().flatten().ok_or(Pass)
}

/// len(v)（数・真偽・None は Python が落ちるので Pass）。
fn py_len(v: &Value) -> R<usize> {
    match v {
        Value::String(s) => Ok(s.chars().count()),
        Value::Array(a) => Ok(a.len()),
        Value::Object(m) => Ok(m.len()),
        _ => Err(Pass),
    }
}

/// schedule_gap_minutes（この対象が新しくなる間隔の目安。予定が無ければ None）。
fn schedule_gap_minutes(job: &Map<String, Value>) -> R<Option<i64>> {
    let rules = match job.get("schedules") {
        None => return Ok(None),
        Some(Value::Array(a)) => a,
        Some(_) => return Err(Pass),
    };
    let mut best: Option<i64> = None;
    for r in rules {
        let Value::Object(r) = r else { return Err(Pass) };
        if !r.get("enabled").is_some_and(pyish::truthy) {
            continue;
        }
        // 辞書の式は全部の種類のぶんを先に数える（読めない値は種類に関わらず Python が落ちる）
        let interval = match r.get("interval_minutes").unwrap_or(&json!(60)) {
            v if !pyish::truthy(v) => 60,
            v => int(v)?,
        }
        .max(1);
        let wd = match r.get("weekdays") {
            Some(v) if pyish::truthy(v) => py_len(v)?,
            _ => 1,
        };
        let weekdays = 1440 * (7 / wd.max(1) as i64).max(1);
        let m = match r.get("type").unwrap_or(&json!("daily")) {
            Value::String(k) => match k.as_str() {
                "interval" => interval,
                "daily" => 1440,
                "weekdays" => weekdays,
                "monthly" | "specific_dates" => 1440 * 30,
                _ => 1440,
            },
            Value::Array(_) | Value::Object(_) => return Err(Pass), // 辞書の鍵にできない（Python は落ちる）
            _ => 1440,
        };
        best = Some(best.map_or(m, |b| b.min(m)));
    }
    Ok(best)
}

/// datetime.fromisoformat（Rust で同じに読めない形は Pass。暦に無い値と、年の4桁で始まらない字は None ―― Python も ValueError）。
fn iso(s: &str) -> R<Option<NaiveDateTime>> {
    if !s.as_bytes().get(..4).is_some_and(|b| b.iter().all(u8::is_ascii_digit)) {
        return Ok(None);
    }
    match schedule::from_iso(s) {
        Some(Ok(t)) => Ok(Some(t)),
        Some(Err(())) => Ok(None),
        None => Err(Pass),
    }
}

/// (後 − 先) の分（int(td.total_seconds()//60)。小数の秒の切り捨ては負の側へ）。
fn minutes_between(later: NaiveDateTime, earlier: NaiveDateTime) -> i64 {
    let us = (later - earlier).num_microseconds().unwrap_or(i64::MAX);
    us.div_euclid(60_000_000)
}

/// observed_gap_minutes（これまで実際に実行してきた間隔の中央値。間隔が2つ取れないうちは None）。
fn observed_gap_minutes(c: &rusqlite::Connection, job_id: &Value) -> R<Option<i64>> {
    let id = match job_id {
        Value::String(s) => rusqlite::types::Value::Text(s.clone()),
        Value::Number(n) if n.is_i64() => rusqlite::types::Value::Integer(n.as_i64().unwrap_or(0)),
        _ => return Err(Pass),
    };
    let rows = config::rows(c, "SELECT finished_at FROM run_history WHERE job_id=? ORDER BY id DESC LIMIT 12", &[id])?;
    let mut ts = Vec::new();
    for r in rows {
        let v = r.get("finished_at").cloned().unwrap_or(Value::Null);
        if let Some(t) = iso(&pyish::py_str(&v))? {
            ts.push(t);
        }
    }
    if ts.len() < 3 {
        return Ok(None);
    }
    // 取り出した順ではなく時刻で並べ直す（ずれた1件で間隔が全部負にならないように）
    ts.sort_by(|a, b| b.cmp(a));
    let mut gaps: Vec<i64> = ts.windows(2).map(|w| minutes_between(w[0], w[1])).filter(|g| *g > 0).collect();
    gaps.sort();
    if gaps.len() < 2 {
        return Ok(None);
    }
    Ok(Some(gaps[gaps.len() / 2]))
}

/// list(v)（字は1字ずつ、辞書は鍵。数・真偽は Python が落ちる）。
fn py_list(v: Option<&Value>) -> R<Vec<Value>> {
    match v {
        None => Ok(vec![]),
        Some(v) if !pyish::truthy(v) => Ok(vec![]),
        Some(Value::Array(a)) => Ok(a.clone()),
        Some(Value::String(s)) => Ok(s.chars().map(|c| json!(c.to_string())).collect()),
        Some(Value::Object(m)) => Ok(m.keys().map(|k| json!(k)).collect()),
        Some(_) => Err(Pass),
    }
}

// ==== 受け口 ================================================================

/// GET /api/freshness
pub(crate) fn get_freshness(core: &Core, _: &Ask, _: &[String]) -> Reply {
    answer_freshness(core).unwrap_or_else(|_| Reply::pass())
}

fn answer_freshness(core: &Core) -> R<Reply> {
    let now = core.now();
    let (_, mut items) = config::read_with(core, |c, conn| {
        let runs = schedule::job_runs(conn)?;
        let mut items: Vec<(Value, i64, i64)> = Vec::new();
        for j in jobs(c) {
            let Value::Object(job) = j else { return Err(Pass) };
            if !job.get("enabled").is_some_and(pyish::truthy) {
                continue;
            }
            let (Some(id), Some(name)) = (job.get("id"), job.get("name")) else { return Err(Pass) };
            if matches!(id, Value::Array(_) | Value::Object(_)) {
                return Err(Pass); // 辞書の鍵にできない
            }
            let run = runs.iter().find(|(k, _)| k == id).map(|(_, r)| r).filter(|r| !r.is_empty());
            let info = schedule::last_run_info(run)?;
            let last = info.get("last_run").filter(|v| pyish::truthy(v)).cloned().unwrap_or(json!(""));
            let age = match &last {
                Value::String(s) if !s.is_empty() => iso(s)?.map(|t| minutes_between(now, t)),
                _ => None, // 字でない値は fromisoformat が落ち、Python は None にする
            };
            let prev = schedule::job_schedule_preview(j, now)?;
            let (gap, from) = match schedule_gap_minutes(job)? {
                Some(g) => (g, "schedule"),
                None => match observed_gap_minutes(conn, id)? {
                    Some(g) => (g, "observed"),
                    None => (MANUAL_FRESH_DEFAULT, "default"),
                },
            };
            let overdue = gap != 0 && age.is_some_and(|a| a > gap * 2);
            let metrics = match run.and_then(|r| r.get("metrics")) {
                Some(Value::Object(m)) => m.clone(),
                Some(v) if pyish::truthy(v) => return Err(Pass),
                _ => Map::new(),
            };
            let held = metrics.get("published") == Some(&json!(false));
            let status = info.get("last_status").cloned().unwrap_or(json!(""));
            let state = if status == json!("failed") {
                "failed"
            } else if !pyish::truthy(&last) {
                "never"
            } else if held {
                "held"
            } else if overdue {
                "stale"
            } else {
                "ok"
            };
            let text = |k: &str| metrics.get(k).filter(|v| pyish::truthy(v)).map(pyish::py_str).unwrap_or_default();
            let item = json!({"id": id, "name": name, "state": state, "last_run": last, "age_minutes": age,
                              "next_run": prev.get("next_run").cloned().unwrap_or(Value::Null),
                              "hint": prev.get("hint").cloned().unwrap_or(json!("")), "expect_minutes": gap, "expect_source": from,
                              "status": status, "rows": run.map(|r| r.get("rows").cloned().unwrap_or(Value::Null)).unwrap_or(Value::Null),
                              "output": info.get("last_output").cloned().unwrap_or(json!("")), "held": held,
                              "pending": text("pending"), "hold_reason": text("hold_reason"),
                              "hold_waited": metrics.get("hold_waited").cloned().unwrap_or(Value::Null),
                              "hold_attempts": metrics.get("hold_attempts").cloned().unwrap_or(Value::Null),
                              "hold_advice": py_list(metrics.get("hold_advice"))?});
            let rank = match state {
                "failed" => 0,
                "held" => 1,
                "stale" => 2,
                "never" => 3,
                _ => 4,
            };
            items.push((item, rank, -age.unwrap_or(0)));
        }
        Ok(items)
    })?;
    // 失敗、共有先が古い（読み手がいま騙されている）、予定より遅れ、まだ無い、の順。同じ順位は古い物から
    items.sort_by_key(|(_, rank, age)| (*rank, *age));
    let items: Vec<Value> = items.into_iter().map(|(x, _, _)| x).collect();
    let bad = items.iter().filter(|x| x["state"] != json!("ok")).count();
    let held = items.iter().filter(|x| x["state"] == json!("held")).count();
    let summary = if held > 0 {
        let rest = if bad > held { format!("／ほか{}件が確認待ち", bad - held) } else { String::new() };
        format!("{held}件が共有先へ反映できていません{rest}")
    } else if bad > 0 {
        format!("{bad}件が確認待ちです")
    } else {
        format!("{}件すべて新しい状態です", items.len())
    };
    Ok(Reply::json(200, &json!({"ok": bad == 0, "items": items, "attention": bad, "held": held, "summary": summary})))
}

/// request.get_json(force=True)（辞書でなければ Python が落ちるので Pass）。
fn body(ask: &Ask) -> R<Map<String, Value>> {
    match writer::body_json(ask, true)? {
        Some(Value::Object(m)) => Ok(m),
        _ => Err(Pass),
    }
}

fn is_file(p: &str) -> bool {
    std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
}

/// str(v)（None は 'None'）。
fn py_text(v: Option<&Value>) -> String {
    pyish::py_str(v.unwrap_or(&Value::Null))
}

/// 設定の値で決まる場所（resolve_path）。
fn resolved(b: &paths::Bases, v: Option<&Value>) -> String {
    match v {
        None | Some(Value::Null) => b.resolve_path(None, None),
        Some(v) => b.resolve_path(Some(&pyish::py_str(v)), None),
    }
}

/// POST /api/path-check
pub(crate) fn post_path_check(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_path_check(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_path_check(core: &Core, ask: &Ask) -> R<Reply> {
    let d = body(ask)?;
    let c = config::read(core)?;
    let b = core.bases().ok_or(Pass)?;
    let item = d.get("item").cloned().unwrap_or(Value::Null);
    let job_id = d.get("job_id").cloned().unwrap_or(Value::Null);
    let result = match item.as_str() {
        Some(k @ ("symnavim_conf" | "accdb_template")) => {
            let expected = if k == "symnavim_conf" { "symnavim.conf" } else { "empty.accdb" };
            let value = c.get(k).cloned().unwrap_or(json!(""));
            let p = resolved(&b, Some(&value));
            if !is_file(&p) {
                return Err(Pass); // 近くを探す（find_nearby_file）は Python が受け持つ
            }
            json!({"ok": true, "configured": py_text(Some(&value)), "resolved": p, "candidates": [], "needs_reselect": false,
                   "item": k, "label": expected})
        }
        Some("rne") => {
            let Some(Value::Object(job)) = jobs(&c).iter().find(|x| x.get("id") == Some(&job_id)) else {
                return Ok(Reply::json(404, &json!({"error": "対象が見つかりません"})));
            };
            let mut j = job.clone();
            if let Some(v) = d.get("value").filter(|v| !v.is_null()) {
                j.insert("rne_path".into(), v.clone());
                let expected =
                    d.get("expected_name").filter(|v| pyish::truthy(v)).or_else(|| job.get("rne")).cloned().unwrap_or(Value::Null);
                j.insert("rne".into(), expected);
            }
            let raw = j.get("rne_path").filter(|v| pyish::truthy(v)).or_else(|| j.get("rne")).cloned();
            let rp = config::rne_path(core, &j, &c).ok_or(Pass)?;
            let ok = is_file(&rp);
            if !ok && j.get("rne").is_some_and(pyish::truthy) {
                return Err(Pass); // 近くを探す（find_nearby_file）は Python が受け持つ
            }
            let folder = crate::naming::text_or(c.get("rne_folder"), r".\rne");
            let w = b.locate(&pyish::text_or_empty(raw.as_ref()), Some(&folder));
            let list = |k: &str| w.get(k).and_then(Value::as_array).cloned().unwrap_or_default();
            let tried: Vec<Value> =
                list("tried").into_iter().zip(list("tried_from")).map(|(p, lb)| json!({"path": p, "label": lb})).collect();
            json!({"ok": ok, "configured": py_text(raw.as_ref()), "resolved": rp, "candidates": [], "needs_reselect": !ok,
                   "item": "rne", "job_id": job_id, "label": j.get("rne").cloned().unwrap_or(Value::Null), "tried": tried})
        }
        _ => return Ok(Reply::json(400, &json!({"error": "確認対象が不正です"}))),
    };
    Ok(Reply::json(200, &result))
}

/// POST /api/apply-path-suggestion
pub(crate) fn post_apply_path_suggestion(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_apply(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_apply(core: &Core, ask: &Ask) -> R<Reply> {
    let d = body(ask)?;
    let item = d.get("item").cloned().unwrap_or(Value::Null);
    let job_id = d.get("job_id").cloned().unwrap_or(Value::Null);
    let candidate = match d.get("candidate") {
        Some(v) if !pyish::truthy(v) => None,
        None => None,
        Some(Value::String(s)) => Some(s.clone()),
        Some(_) => return Err(Pass), // Path(数) は Python が落ちる
    };
    let Some(candidate) = candidate.filter(|p| {
        // 相対の道は Python の今いるフォルダーから読むので、Rust では決めない
        !paths::is_absolute(p) || is_file(p)
    }) else {
        return Ok(Reply::json(400, &json!({"error": "修正候補が存在しません"})));
    };
    if !paths::is_absolute(&candidate) {
        return Err(Pass);
    }
    let b = core.bases().ok_or(Pass)?;
    // 相対パスの基準（置き場）の中なら .\… で持つ（読み直して同じ物に着くときだけ）。外なら絶対パス
    let stored = b.to_relative(&candidate, true).unwrap_or_else(|| paths::resolve(&candidate));
    let done = writer::transact(core, |tx, lines| {
        let mut c = config::load(core, tx)?;
        match item.as_str() {
            Some(k @ ("symnavim_conf" | "accdb_template")) => {
                c.insert(k.into(), json!(stored));
            }
            Some("rne") => {
                let Some(Value::Array(jobs)) = c.get_mut("jobs") else { return Err(Pass) };
                let Some(Value::Object(j)) = jobs.iter_mut().find(|x| x.get("id") == Some(&job_id)) else { return Ok(Err(404)) };
                j.insert("rne_path".into(), json!(stored));
                j.insert("rne".into(), json!(paths::py_name(&candidate)));
            }
            _ => return Ok(Err(400)),
        }
        writer::save_in(core, tx, &c, true, lines)?;
        Ok(Ok(()))
    })?;
    match done {
        Err(404) => Ok(Reply::json(404, &json!({"error": "対象が見つかりません"}))),
        Err(_) => Ok(Reply::json(400, &json!({"error": "修正対象が不正です"}))),
        Ok(()) => {
            writer::flush_soon(core, "config-save");
            Ok(Reply::json(200, &json!({"ok": true, "path": stored})))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(s: &str) -> NaiveDateTime {
        NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f").unwrap()
    }

    #[test]
    fn gap_from_rules() {
        let job = |v: Value| v.as_object().cloned().unwrap();
        let g = |v: Value| schedule_gap_minutes(&job(v)).ok().flatten();
        assert_eq!(g(json!({"schedules": [{"enabled": true, "type": "interval", "interval_minutes": 0}]})), Some(60));
        assert_eq!(g(json!({"schedules": [{"enabled": true, "type": "weekdays", "weekdays": [1, 2, 3]}]})), Some(2880));
        assert_eq!(g(json!({"schedules": [{"enabled": true}, {"enabled": true, "type": "monthly"}]})), Some(1440));
        assert_eq!(g(json!({"schedules": [{"enabled": false, "type": "interval"}]})), None);
        assert!(schedule_gap_minutes(&job(json!({"schedules": [{"enabled": true, "interval_minutes": "x"}]}))).is_err());
    }

    #[test]
    fn minutes_floor_like_python() {
        assert_eq!(minutes_between(at("2026-11-02T09:05:07.1"), at("2026-11-02T09:00:00")), 5);
        assert_eq!(minutes_between(at("2026-11-02T09:00:00"), at("2026-11-02T09:00:30")), -1);
    }

    #[test]
    fn list_like_python() {
        assert_eq!(py_list(Some(&json!("ab"))).ok(), Some(vec![json!("a"), json!("b")]));
        assert_eq!(py_list(Some(&json!({"k": 1}))).ok(), Some(vec![json!("k")]));
        assert!(py_list(Some(&json!(3))).is_err());
    }
}
