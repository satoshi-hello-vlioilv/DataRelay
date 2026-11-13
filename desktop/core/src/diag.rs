//! 設定が本当に使えるか・データが新しいかを読む受け口のうち、設定と記録とファイルから答えられる物（2.33.0〜）。
//! lib/navi_diag.py（freshness_view・fresh_expectation・observed_gap_minutes・check_path_item）と、app.schedule_gap_minutes、
//! lib/navi_web.py の freshness・path_check・apply_path_suggestion と同じ答えを返す。
//!
//!   - GET  /api/freshness             … 有効な対象ごとに、いまのデータがいつのものか（予定・実績の間隔から「古い」を見分ける）
//!   - POST /api/path-check            … symnavim.conf・ACCDB の空テンプレート・対象の RNE が在るか（探した場所の並びも）
//!   - POST /api/apply-path-suggestion … 見つけた候補を設定へ書く（置き場の中なら .\… の書き方で持つ）
//!   - GET  /api/machine-paths         … 場所の設定が、このPCではどこを指し、いまの構成で要るのか（2.34.0〜）
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

// ==== このPCでの場所（machine_path_view） ====================================

/// 場所の設定（PATH_SETTING_LABEL・PATH_SETTING_KIND。並びもこのまま）。
const PATH_SETTINGS: [(&str, &str, &str); 7] = [
    ("rne_folder", "RNE基本フォルダー", "folder"),
    ("text_folder", "テキストの基本フォルダー", "folder"),
    ("default_output_folder", "既定の出力先", "folder"),
    ("backup_folder", "バックアップ先", "folder"),
    ("symnavim_conf", "symnavim.conf", "file"),
    ("accdb_template", "ACCDB空テンプレート", "file"),
    ("navigator_api_dll", "Navigator API DLL", "file"),
];

/// データの基準をどこで決めたか（DATA_ROOT_NOTES）。
fn data_root_note(source: &str) -> &'static str {
    match source {
        "app" => "相対パスと設定のマスターの基準。共有から直に動かしているので、アプリの場所と同じ",
        "user" => "設定のマスターの基準。共有のユーザーのフォルダー（<ユーザーの置き場>\\<ログオン名>）。PC が変わっても、共有からインストールすればこのデータで起動します",
        "pc" => "相対パスと設定のマスターの基準。このPCの手元（写しの data）。共有のユーザーのフォルダーが届かないときの形。置き場の「既定の設定」から作りました",
        "install" => "設定のマスターの基準。共有の設定を使っています（2.0.0 より前に写したPC。手元へ移すかを画面で選べます）。相対パスは「相対パスの基準」（配布の置き場）を先に見ます",
        "local" => "相対パスと設定のマスターの基準。このPCだけの上書き（config\\local.json）",
        "env" => "相対パスと設定のマスターの基準。環境変数 NAVI_DATA_ROOT（確かめるとき）",
        _ => "",
    }
}

/// leans_on_rne_root・leans_on_text_root（名前だけの指定か。個別の道（絶対・UNC・.\ 始まり）なら基本フォルダーを見ない）。
fn leans_on_root(raw: &str) -> bool {
    let expanded = paths::expand_user_vars(raw);
    if paths::is_absolute(&expanded) || expanded.starts_with("\\\\") {
        return false;
    }
    !["./", "../", ".\\", "..\\"].iter().any(|x| raw.starts_with(x))
}

fn text_of(v: Option<&Value>) -> String {
    pyish::strip(&crate::naming::text_or(v, "")).to_string()
}

/// path_setting_roles（それぞれの場所の設定が、いまの構成で要るのか → (required・fallback・unused, 理由)）。
fn path_setting_roles(core: &Core, c: &Map<String, Value>) -> R<Map<String, Value>> {
    let jobs = jobs(c);
    let job = |j: &Value| j.as_object().cloned().ok_or(Pass);
    let n_jobs = jobs.len();
    let nobody = |kind: &str| {
        if n_jobs == 0 {
            "対象がまだ無いため、いまは使いません".to_string()
        } else {
            format!("登録済みの{n_jobs}件はすべて{kind}")
        }
    };
    let (mut rne_users, mut out_users, mut text_users, mut accdb) = (0, 0, 0, 0);
    for j in jobs {
        let j = job(j)?;
        let rne = j.get("rne_path").filter(|v| pyish::truthy(v)).or_else(|| j.get("rne"));
        let raw = text_of(rne);
        if raw.is_empty() || leans_on_root(&raw) {
            rne_users += 1;
        }
        if text_of(j.get("output_folder")).is_empty() {
            out_users += 1;
        }
        let tp = text_of(j.get("text_path"));
        if crate::naming::text_or(j.get("source"), "") == "text" && !tp.is_empty() && leans_on_root(&tp) {
            text_users += 1;
        }
        let extra = crate::naming::job_extra_formats(&j).ok_or(Pass)?;
        if crate::naming::normalize_output_format(j.get("output_format"), j.get("output_file")) == "accdb" || extra.contains(&"accdb") {
            accdb += 1;
        }
    }
    let mut join_users = 0;
    for r in c.get("join_recipes").and_then(Value::as_array).into_iter().flatten() {
        for x in r.get("sources").and_then(Value::as_array).into_iter().flatten() {
            let p = text_of(x.get("path"));
            if !p.is_empty() && leans_on_root(&p) {
                join_users += 1;
            }
        }
    }
    let role = |r: &str, why: String| json!([r, why]);
    let mut out = Map::new();
    out.insert(
        "rne_folder".into(),
        if rne_users > 0 {
            role("required", format!("{rne_users}件の対象がこの場所を基準にします"))
        } else {
            role("fallback", nobody("個別のパスで解決できるため、この設定は使っていません"))
        },
    );
    out.insert(
        "default_output_folder".into(),
        if out_users > 0 {
            role("required", format!("{out_users}件の対象がこの場所へ出力します"))
        } else {
            role("fallback", nobody("出力先を個別に持っています"))
        },
    );
    let mut who = Vec::new();
    if text_users > 0 {
        who.push(format!("{text_users}件の対象"));
    }
    if join_users > 0 {
        who.push(format!("結合マスタの{join_users}ファイル"));
    }
    out.insert(
        "text_folder".into(),
        if who.is_empty() {
            role("fallback", "ファイル名だけで登録したときの基準です。いまはすべて個別のパスで解決できています".into())
        } else {
            role("required", format!("{}がこの場所を基準にします", who.join("、")))
        },
    );
    let local_root = std::path::PathBuf::from(core.bases().ok_or(Pass)?.local_root);
    let saved = crate::secret::Vault::default_for(&local_root).load().ok().flatten().is_some_and(|v| pyish::truthy(&v));
    out.insert(
        "symnavim_conf".into(),
        if saved {
            role("unused", "接続情報はこのPCに登録済みのため、このファイルは読みません。共有に置いたままなら消してかまいません".into())
        } else {
            role(
                "fallback",
                "接続情報がこのPCに未登録のあいだだけ、ここから読みます。「Navigator の接続情報」で取り込めば要らなくなります".into(),
            )
        },
    );
    out.insert("navigator_api_dll".into(), role("fallback", "手動で指定したときだけ使います。空なら探す範囲から自動で選びます".into()));
    out.insert(
        "accdb_template".into(),
        if accdb > 0 {
            role("required", format!("{accdb}件の対象がACCDBで出力します"))
        } else {
            role("unused", "ACCDBで出力する対象がないため使いません".into())
        },
    );
    // backup_enabled が False（0 も同じ）のときだけ控えを取らない
    let backup = c.get("settings").and_then(Value::as_object).and_then(|s| s.get("backup_enabled")).cloned();
    let off = matches!(&backup, Some(Value::Bool(false))) || backup.as_ref().and_then(Value::as_f64) == Some(0.0);
    out.insert(
        "backup_folder".into(),
        if off {
            role("unused", "控えを取らない設定のため使いません".into())
        } else {
            role("required", "出力を差し替える前に、いまのファイルをここへ控えます".into())
        },
    );
    Ok(out)
}

/// path_writable（書けるかは、実際に書いてみないと分からない。フォルダーでなければ None）。
fn path_writable(p: &str) -> Option<bool> {
    if !std::fs::metadata(p).map(|m| m.is_dir()).unwrap_or(false) {
        return None;
    }
    let probe = paths::join(p, &format!(".probe_{}", std::process::id()));
    Some(std::fs::write(&probe, b"x").and_then(|_| std::fs::remove_file(&probe)).is_ok())
}

/// GET /api/machine-paths
pub(crate) fn get_machine_paths(core: &Core, _: &Ask, _: &[String]) -> Reply {
    answer_machine_paths(core).unwrap_or_else(|_| Reply::pass())
}

fn answer_machine_paths(core: &Core) -> R<Reply> {
    let c = config::read(core)?;
    let b = core.bases().ok_or(Pass)?;
    let roles = path_setting_roles(core, &c)?;
    let mut rows = Vec::new();
    for (key, label, kind) in PATH_SETTINGS {
        let raw = crate::naming::text_or(c.get(key), "");
        let (role, why) = match &roles[key] {
            Value::Array(a) => (a[0].as_str().unwrap_or("").to_string(), a[1].as_str().unwrap_or("").to_string()),
            _ => ("required".into(), String::new()),
        };
        let real = b.resolve_path(Some(&raw), None);
        let exists = !raw.is_empty() && std::fs::metadata(&real).is_ok();
        let foreign = config::foreign_profile_path(&raw);
        let writable = if kind == "folder" && exists { path_writable(&real) } else { None };
        let pc = pyish::strip(&raw).starts_with(paths::PC_TOKEN);
        let (mut state, mut note) = ("ok", String::new());
        if let Some(f) = &foreign {
            // 他人のフォルダーは、使う予定が無くても直す価値がある（別のPCで必ず詰まる）
            state = "ng";
            note = format!("別の利用者のフォルダー（{f}）を指しています。このPCでは使えません");
        } else if exists {
            if pc {
                note = "このPCのローカル領域（PCごとに実体が変わります）".into();
            }
            if writable == Some(false) {
                state = "warn";
                note = "書き込めません（権限を確認してください）".into();
            } else if key == "symnavim_conf" {
                if role == "unused" {
                    state = "warn";
                    note =
                        "接続情報はこのPCに登録済みです。このファイルには平文のパスワードが入っているので、共有から消してください".into();
                } else {
                    // 値そのものは出さない ―― どのセクションを使うかだけを言う。読めない理由の文（OS の例外）は Python へ
                    let bytes = std::fs::read(&real).map_err(|_| Pass)?;
                    // 書き方の誤り（configparser の例外の文）は Python と同じ文を作れないので Python へ回す
                    let read = crate::secret::read_conf_text(&bytes).and_then(|t| match crate::secret::parse_conf(&t) {
                        Ok(m) => Ok(m),
                        Err(Err(m)) => Err(m),
                        Err(Ok(_)) => Err(String::new()),
                    });
                    if read.as_ref().is_err_and(String::is_empty) {
                        return Err(Pass);
                    }
                    match read {
                        Ok(m) => {
                            note = format!(
                                "読み取れます（[{}] の利用者ID・パスワード・サーバー）。{why}",
                                pyish::text_or_empty(m.get("section"))
                            )
                        }
                        Err(e) => {
                            state = "ng";
                            note = format!("ファイルはありますが、読み取れません: {e}");
                        }
                    }
                }
            }
        } else if role == "required" {
            state = "ng";
            note = if kind == "folder" {
                format!("フォルダーがありません。{why}")
            } else {
                format!("ファイルがありません。{why}")
            };
        } else if role == "unused" {
            note = format!("{why}{}", if raw.is_empty() { "（未設定）" } else { "" });
        } else if raw.is_empty() {
            note = why.clone();
        } else if key == "default_output_folder" {
            note = format!("いまはありません（{why}）。出力するときに作られます");
        } else {
            note = format!("いまはありませんが、{why}");
        }
        let portable = raw.is_empty() || pc || !paths::is_absolute(&raw);
        rows.push(json!({"key": key, "label": label, "kind": kind, "configured": raw, "resolved": real, "where": b.locate(&raw, None),
                         "exists": exists, "writable": writable, "role": role, "why": why, "portable": portable,
                         "foreign": foreign.unwrap_or_default(), "state": state, "note": note}));
    }
    let local = b.local_root.clone();
    let master = core.config_dir().map(|d| paths::join(&d, "app_settings.sqlite3")).ok_or(Pass)?;
    let local_db = paths::py_path(&crate::settings::local_db(std::path::Path::new(&local)).to_string_lossy());
    let fixed = json!([
        {"label": "アプリの場所", "path": b.program_root, "note": "動いているプログラムの実体"},
        {"label": "データの基準", "path": b.data_root, "note": data_root_note(&b.data_source)},
        {"label": "相対パスの基準", "path": b.rel_root(), "note": "相対パス（.\\rne\\… など）を先に見る場所＝配布の置き場（入口の DataRelay.exe があるフォルダー。版が変わっても動きません）。ここに無い物は、データの基準・アプリの場所にあればそちらを使います"},
        {"label": "このPCのローカル領域", "path": local, "note": "<PC> が指す先。作業・控え・ログ・キャッシュの親"},
        {"label": "作業フォルダー", "path": paths::join(&local, "work"), "note": "抽出の途中ファイル。起動時に空にします"},
        {"label": "ログ", "path": paths::join(&local, "logs"), "note": "実行ログの実体"},
        {"label": "設定の控え（このPC）", "path": local_db, "note": "マスターから写した作業用"},
        {"label": "設定のマスター", "path": master, "note": "BOX上の正本。全PCで共有"},
    ]);
    let count = |s: &str| rows.iter().filter(|x| x["state"] == json!(s)).count();
    let (bad, warn) = (count("ng"), count("warn"));
    let used = rows.iter().filter(|x| x["role"] != json!("unused")).count();
    let summary = if bad > 0 {
        format!("{bad}件がこのPCでは使えません")
    } else if warn > 0 {
        format!("{warn}件に注意があります")
    } else {
        format!("いま使う{used}件はすべてこのPCで解決できます")
    };
    let env = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty());
    let user = env("USERNAME").or_else(|| env("USER")).unwrap_or_default();
    let profile = paths::py_path(&paths::home_dir().ok_or(Pass)?);
    let host = paths::host_name().ok_or(Pass)?;
    Ok(Reply::json(
        200,
        &json!({"ok": bad == 0, "rows": rows, "fixed": fixed, "profile": profile, "user": user, "host": host, "summary": summary}),
    ))
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
