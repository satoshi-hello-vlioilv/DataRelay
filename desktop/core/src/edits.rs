//! 画面からの小さな書き込み（2.23.0〜）。navi_web の set_columns・schedule_quick_add・schedule_pause_set と同じ結果にする。
//!
//! どれも writer::transact の1つの取引の中で「読む → 直す → 書く」を行う（Python は settings_sync_lock の中で同じ順に行う）。
//!   - 一覧の列の決め方・カレンダーからの1回実行ルール … 設定を丸ごと保存し、版を1つ進め、裏で書き戻す（app.save）
//!   - 自動実行の一時停止 … 運転の状態（scheduler_state）だけを書く。版は進めず、書き戻しは終わるときに回す
//!     （app.save_scheduler_state は _mark_settings_dirty だけで、すぐには書き戻さない）

use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::{pyish, routes::Core, schedule, writer};
use chrono::{NaiveDate, NaiveDateTime};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

// ==== 一覧の列の決め方 ======================================================

/// navi_web.normalize_column_layout（形と大きさだけ整える。どんな列があるかは画面が決める）。
pub fn normalize_column_layout(v: &Map<String, Value>) -> Value {
    let keys = |x: Option<&Value>| -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for k in x.and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]).iter().take(32) {
            let k = pyish::head(&pyish::py_str(k), 32);
            if !k.is_empty() && !out.contains(&k) {
                out.push(k);
            }
        }
        out
    };
    let mut opt = Map::new();
    if let Some(Value::Object(o)) = v.get("opt") {
        for (k, one_in) in o.iter().take(32) {
            let Value::Object(one_in) = one_in else { continue };
            let mut one = Map::new();
            for (name, value) in one_in.iter().take(16) {
                let kept = match value {
                    Value::Null | Value::Bool(_) | Value::Number(_) => value.clone(),
                    Value::String(s) => json!(pyish::head(s, 64)),
                    Value::Array(a) => json!(a.iter().take(16).map(|x| pyish::head(&pyish::py_str(x), 32)).collect::<Vec<_>>()),
                    Value::Object(_) => continue,
                };
                // 切った名前が重なれば、後の値で上書きする（並びは先に入れた位置のまま。Python の辞書と同じ）
                one.insert(pyish::head(name, 32), kept);
            }
            opt.insert(pyish::head(k, 32), Value::Object(one));
        }
    }
    json!({"order": keys(v.get("order")), "hidden": keys(v.get("hidden")), "opt": opt})
}

/// POST /api/settings/columns … 一覧の列の決め方だけをすぐ保存する（ほかの未保存の編集には触らない）。
pub(crate) fn post_columns(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_columns(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_columns(core: &Core, ask: &Ask) -> R<Reply> {
    // request.get_json(silent=True) or {} … 辞書でない真の値（並び・数）は .get で落ちる（Python は 500）
    let data = match writer::body_json(ask, false)? {
        Some(Value::Object(m)) => m,
        Some(v) if pyish::truthy(&v) => return Err(Pass),
        _ => Map::new(),
    };
    let Some(Value::Object(raw)) = data.get("layout") else {
        return Ok(Reply::json(400, &json!({"ok": false, "error": "列の決め方(layout)がありません"})));
    };
    let layout = normalize_column_layout(raw);
    writer::transact(core, |tx, lines| {
        let mut c = config::load(core, tx)?;
        let Some(Value::Object(settings)) = c.get_mut("settings") else { return Err(Pass) };
        settings.insert("column_layout".into(), layout.clone());
        writer::save_in(core, tx, &c, true, lines)?;
        lines.push(format!(
            "設定保存 job=(共通) 一覧の列 並び={} 隠す={} 見せ方={}",
            pyish::py_repr(&layout["order"]),
            pyish::py_repr(&layout["hidden"]),
            pyish::py_repr(&layout["opt"])
        ));
        Ok(())
    })?;
    writer::flush_soon(core, "config-save");
    Ok(Reply::json(200, &json!({"ok": true, "column_layout": layout})))
}

// ==== カレンダーからの1回実行ルール ==========================================

/// 1つの欄の候補（長さ, 当たるか）。Python の _strptime が組む正規表現の選択肢と同じ並び。
type Alt = (usize, fn(&[u8]) -> bool);

fn nz(c: u8) -> bool {
    (b'1'..=b'9').contains(&c)
}

const YEAR: &[Alt] = &[(4, |b| b.iter().all(u8::is_ascii_digit))];
const MONTH: &[Alt] = &[(2, |b| b[0] == b'1' && (b'0'..=b'2').contains(&b[1])), (2, |b| b[0] == b'0' && nz(b[1])), (1, |b| nz(b[0]))];
const DAY: &[Alt] = &[
    (2, |b| b[0] == b'3' && (b[1] == b'0' || b[1] == b'1')),
    (2, |b| (b[0] == b'1' || b[0] == b'2') && b[1].is_ascii_digit()),
    (2, |b| b[0] == b'0' && nz(b[1])),
    (1, |b| nz(b[0])),
    (2, |b| b[0] == b' ' && nz(b[1])),
];
const HOUR: &[Alt] = &[
    (2, |b| b[0] == b'2' && (b'0'..=b'3').contains(&b[1])),
    (2, |b| (b[0] == b'0' || b[0] == b'1') && b[1].is_ascii_digit()),
    (1, |b| b[0].is_ascii_digit()),
];
const MINUTE: &[Alt] = &[(2, |b| (b'0'..=b'5').contains(&b[0]) && b[1].is_ascii_digit()), (1, |b| b[0].is_ascii_digit())];

/// 書式の1歩（欄・決まった字・続く空白）。
enum Step {
    Field(&'static [Alt]),
    Lit(u8),
    Spaces,
}

/// '%Y-%m-%d %H:%M' の正規表現（書式の空白は \s+）。
const PLAN: [Step; 9] = [
    Step::Field(YEAR),
    Step::Lit(b'-'),
    Step::Field(MONTH),
    Step::Lit(b'-'),
    Step::Field(DAY),
    Step::Spaces,
    Step::Field(HOUR),
    Step::Lit(b':'),
    Step::Field(MINUTE),
];

/// 正規表現と同じ順（選択肢は左から、\s+ は長いほうから）でたどり、はじめて最後の歩まで当たった並びを返す（re.match）。
fn walk(s: &[u8], pos: usize, step: usize, got: &mut Vec<(usize, usize)>) -> Option<usize> {
    let Some(st) = PLAN.get(step) else { return Some(pos) };
    match st {
        Step::Lit(c) => (s.get(pos) == Some(c)).then_some(()).and_then(|_| walk(s, pos + 1, step + 1, got)),
        Step::Spaces => {
            let n = s[pos.min(s.len())..].iter().take_while(|c| matches!(c, b' ' | b'\t' | b'\n' | b'\r' | b'\x0b' | b'\x0c')).count();
            (1..=n).rev().find_map(|k| walk(s, pos + k, step + 1, got))
        }
        Step::Field(alts) => alts.iter().find_map(|(len, hit)| {
            let part = s.get(pos..pos + len)?;
            if !hit(part) {
                return None;
            }
            got.push((pos, pos + len));
            let end = walk(s, pos + len, step + 1, got);
            if end.is_none() {
                got.pop();
            }
            end
        }),
    }
}

/// datetime.strptime(s, '%Y-%m-%d %H:%M')。Ok(None) は Python の ValueError（形が違う・暦に無い・余りがある）。
/// ASCII でない字があれば Pass（Python の \d・\s は全角の数字や空白にも当たり、同じに読めると言えない）。
pub fn strptime_date_time(s: &str) -> R<Option<NaiveDateTime>> {
    if !s.is_ascii() {
        return Err(Pass);
    }
    let b = s.as_bytes();
    let mut got = Vec::new();
    if walk(b, 0, 0, &mut got) != Some(b.len()) {
        return Ok(None);
    }
    let n: Vec<u32> = got.iter().map(|&(a, z)| pyish::strip(&s[a..z]).parse().unwrap_or(0)).collect();
    let [y, mo, d, hh, mm] = n[..] else { return Ok(None) };
    if y < 1 {
        return Ok(None); // 0 年は datetime が作れない
    }
    Ok(NaiveDate::from_ymd_opt(y as i32, mo, d).and_then(|x| x.and_hms_opt(hh, mm, 0)))
}

/// POST /api/schedule/quick-add … カレンダーから、ある日の1回実行ルール（specific_dates）を対象へ1件足す。
pub(crate) fn post_quick_add(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_quick_add(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn bad(msg: &str) -> Reply {
    Reply::json(400, &json!({"error": msg}))
}

fn answer_quick_add(core: &Core, ask: &Ask) -> R<Reply> {
    // request.get_json(force=True) or {}
    let d = match writer::body_json(ask, true)? {
        Some(Value::Object(m)) => m,
        Some(v) if pyish::truthy(&v) => return Err(Pass),
        _ => Map::new(),
    };
    let job_id = d.get("job_id").cloned().unwrap_or(Value::Null);
    let date = pyish::strip(&pyish::text_or_empty(d.get("date"))).to_string();
    let tm = match d.get("time") {
        Some(v) if pyish::truthy(v) => pyish::strip(&pyish::py_str(v)).to_string(),
        _ => "06:00".to_string(),
    };
    if !pyish::truthy(&job_id) || date.is_empty() {
        return Ok(bad("対象と日付を指定してください"));
    }
    let when = format!("{date} {}", if tm.is_empty() { "06:00" } else { &tm });
    let Some(when) = strptime_date_time(&when)? else {
        return Ok(bad("日付は YYYY-MM-DD、時刻は HH:MM で指定してください"));
    };
    if when <= core.now() {
        return Ok(bad(&format!("{date} {tm} はすでに過ぎています。これから来る日時を指定してください")));
    }
    let name = match d.get("name") {
        Some(v) if pyish::truthy(v) => v.clone(),
        _ => json!(format!("{date} 単発実行")),
    };
    let rule = json!({"id": uuid::Uuid::new_v4().simple().to_string(), "enabled": true, "name": name,
                      "type": "specific_dates", "time": tm, "dates": [date]});
    let found = writer::transact(core, |tx, lines| {
        let mut c = config::load(core, tx)?;
        let Some(Value::Array(jobs)) = c.get_mut("jobs") else { return Err(Pass) };
        let Some(j) = jobs.iter_mut().find(|x| x.get("id") == Some(&job_id)) else { return Ok(None) };
        let Value::Object(j) = j else { return Err(Pass) };
        let job_name = j.get("name").map(pyish::py_str).unwrap_or_default();
        match j.entry("schedules").or_insert_with(|| json!([])) {
            Value::Array(rules) => rules.push(rule.clone()),
            _ => return Err(Pass),
        }
        writer::save_in(core, tx, &c, true, lines)?;
        lines.push(format!("CALENDAR_QUICK_ADD job={job_name} date={date} time={tm}"));
        Ok(Some(()))
    })?;
    if found.is_none() {
        return Ok(Reply::json(404, &json!({"error": "対象が見つかりません"})));
    }
    writer::flush_soon(core, "config-save");
    Ok(Reply::json(200, &json!({"ok": true, "rule": rule})))
}

// ==== 自動実行の一時停止 ====================================================

/// POST /api/schedule-pause … 自動実行をまとめて一時停止する・戻す（ルールごとの入・切は変えない）。
pub(crate) fn post_schedule_pause(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_pause(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_pause(core: &Core, ask: &Ask) -> R<Reply> {
    // request.get_json(silent=True) or {}
    let d = match writer::body_json(ask, false)? {
        Some(Value::Object(m)) => m,
        Some(v) if pyish::truthy(&v) => return Err(Pass),
        _ => Map::new(),
    };
    let paused = d.get("paused").is_some_and(pyish::truthy);
    let now = core.now();
    // set_schedule_pause: 再開する時刻を確かめる（読めない・過ぎている → 400）
    let mut until = pyish::strip(&pyish::text_or_empty(d.get("until"))).to_string();
    if paused && !until.is_empty() {
        let at = match schedule::from_iso(&until) {
            Some(Ok(t)) => t,
            Some(Err(())) => return Ok(bad("再開する時刻を読めません")),
            None => return Err(Pass),
        };
        if at <= now {
            return Ok(bad("再開する時刻が過ぎています"));
        }
        until = at.format("%Y-%m-%dT%H:%M").to_string();
    }
    let view = writer::transact(core, |tx, lines| {
        let value = if paused {
            let cur = schedule::schedule_pause(&schedule::scheduler_state(tx)?, now)?;
            let since =
                if cur["paused"] == json!(true) { pyish::py_str(&cur["since"]) } else { now.format("%Y-%m-%dT%H:%M:%S").to_string() };
            // json.dumps（ensure_ascii=True）。ASCII でない字は \uXXXX になるので、同じに書けると言えない
            if !since.is_ascii() {
                return Err(Pass);
            }
            writer::py_dumps(&json!({"since": since, "until": until}))
        } else {
            "{}".to_string()
        };
        tx.execute("INSERT OR REPLACE INTO scheduler_state VALUES(?,?,?)", [schedule::PAUSE_KEY, &value, &writer::stamp(core)])
            .map_err(|_| Pass)?;
        let state = schedule::scheduler_state(tx)?;
        let p = schedule::schedule_pause(&state, now)?;
        let view = schedule::pause_view(&config::load(core, tx)?, &state, now)?;
        lines.push(format!(
            "SCHEDULE_PAUSE {} until={}",
            if p["paused"] == json!(true) { format!("ON since={}", pyish::py_str(&p["since"])) } else { "OFF".into() },
            match pyish::py_str(&p["until"]) {
                u if u.is_empty() => "-".to_string(),
                u => u,
            }
        ));
        Ok(view)
    })?;
    writer::mark_dirty(core);
    Ok(Reply::json(200, &json!({"pause": view})))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(s: &str) -> Option<String> {
        strptime_date_time(s).ok().flatten().map(|t| t.format("%Y-%m-%d %H:%M").to_string())
    }

    #[test]
    fn strptime_like_python() {
        assert_eq!(at("2026-12-01 06:00").as_deref(), Some("2026-12-01 06:00"));
        assert_eq!(at("2026-1-5 6:7").as_deref(), Some("2026-01-05 06:07"));
        assert_eq!(at("2026-01- 5 06:00").as_deref(), Some("2026-01-05 06:00"));
        assert_eq!(at("2026-01-05 \t 23:59").as_deref(), Some("2026-01-05 23:59"));
        assert_eq!(at("2026-02-30 06:00"), None, "暦に無い日");
        assert_eq!(at("0000-01-01 06:00"), None, "0 年");
        assert_eq!(at("2026-01-05 24:00"), None);
        assert_eq!(at("2026-01-05 06:00x"), None, "余り");
        assert_eq!(at("2026-01-0506:00"), None, "空白が無い");
        assert_eq!(at("26-01-05 06:00"), None);
        assert!(strptime_date_time("２０２６-01-05 06:00").is_err(), "全角の数字は Python へ回す");
    }

    #[test]
    fn column_layout_shape() {
        let v = json!({"order": ["a", "a", "", 1, "x".repeat(40)], "opt": {"c": {"w": 1.5, "s": "y".repeat(70), "l": [1, null], "d": {}}, "n": 3}});
        let out = normalize_column_layout(v.as_object().unwrap());
        assert_eq!(out["order"], json!(["a", "1", "x".repeat(32)]));
        assert_eq!(out["hidden"], json!([]));
        assert_eq!(out["opt"], json!({"c": {"w": 1.5, "s": "y".repeat(64), "l": ["1", "None"]}}));
    }
}
