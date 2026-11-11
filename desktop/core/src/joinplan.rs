//! 結合マスタの組み立てを助ける受け口のうち、設定から答えられる物（2.27.0〜）。
//! lib/navi_web.py の join_candidates_route・join_order_route・join_cache_clear_route と同じ答えを返す。
//!
//!   - GET  /api/join-candidates … 繋ぐ相手の候補（この アプリが作るファイルを先に、実物があって新しい順）と、ローカルの写しの様子
//!   - POST /api/join-order      … 結合の材料を、どの対象が作るのか（実行の順番の決め手）と、材料を待つ設定
//!   - POST /api/join-cache/clear … ローカルの写し（work\read-cache）を全部捨てる
//!
//! ファイルの中身を読む受け口（join-source・join-keys・join-preview）は、データビュワーと同じ読み手（CSV・EXCEL・SQLite・ACCESS）を
//! 使うので、出力の段で移す。
use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::paths::{self, Bases};
use crate::{naming, pyish, routes::Core, schedule, writer};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

fn jobs(cfg: &Map<String, Value>) -> &[Value] {
    cfg.get("jobs").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

/// resolve_path(job.get('output_folder') or cfg.get('default_output_folder'))。
pub(crate) fn output_folder(b: &Bases, job: &Map<String, Value>, cfg: &Map<String, Value>) -> String {
    let v = job.get("output_folder").filter(|v| pyish::truthy(v)).or_else(|| cfg.get("default_output_folder"));
    match v {
        None | Some(Value::Null) => b.resolve_path(None, None),
        Some(v) => b.resolve_path(Some(&pyish::py_str(v)), None),
    }
}

fn is_file(p: &str) -> bool {
    std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
}

/// _viewer_output_path（前回の実行が作ったファイル。無ければ、いまの名前で作るファイル。どちらも無ければ前回の名前）。
pub(crate) fn viewer_output_path(
    core: &Core,
    b: &Bases,
    job: &Map<String, Value>,
    cfg: &Map<String, Value>,
    runs: &[(Value, Map<String, Value>)],
) -> String {
    let run = runs.iter().find(|(k, _)| Some(k) == job.get("id")).map(|(_, r)| r);
    let filename = match run.and_then(|r| r.get("output_file")).filter(|v| pyish::truthy(v)) {
        Some(v) => pyish::py_str(v),
        None => pyish::text_or_empty(job.get("output_file")),
    };
    let folder = output_folder(b, job, cfg);
    let candidate = paths::join(&folder, &filename);
    if is_file(&candidate) {
        return candidate;
    }
    let rp = config::rne_path(core, job, cfg);
    if let Ok(name) = naming::resolve_output_filename(job, rp.as_deref(), core.now()) {
        let current = paths::join(&folder, &name);
        if is_file(&current) {
            return current;
        }
    }
    candidate
}

/// job_output_plan の各ファイルの場所（作れなければ空）。
fn plan(core: &Core, job: &Map<String, Value>, cfg: &Map<String, Value>) -> Vec<Value> {
    let rp = config::rne_path(core, job, cfg);
    match naming::job_output_plan(job, rp.as_deref(), core.now()) {
        Ok(Some(Value::Array(a))) => a,
        _ => vec![],
    }
}

/// resolve_join_path（結合で読むファイルの場所。書き方の決まりは RNE・テキストと同じ）。
fn join_path(b: &Bases, cfg: &Map<String, Value>, value: &Value) -> String {
    let raw = pyish::text_or_empty(Some(value));
    if pyish::strip(&raw).is_empty() {
        return ".".into();
    }
    let folder = naming::text_or(cfg.get("text_folder"), config::TEXT_FOLDER_DEFAULT);
    b.resolve_in(&raw, Some(&folder))
}

/// 道の見出し（navi_order._key: as_posix().lower()）。
fn owner_key(p: &str) -> String {
    let s = paths::py_path(p);
    let s = if cfg!(windows) { s.replace('\\', "/") } else { s };
    s.to_lowercase()
}

/// ローカルの写しの置き場（navi_localcopy.cache_dir。無ければ作る）。
fn cache_dir() -> String {
    let local = paths::py_path(&paths::local_root().to_string_lossy());
    let d = paths::join(&paths::join(&local, "work"), "read-cache");
    let _ = std::fs::create_dir_all(&d);
    d
}

/// navi_localcopy.stats（写しの数と大きさ。.json は写しの控えなので数えない）。
fn cache_stats() -> Value {
    let d = cache_dir();
    let Ok(rd) = std::fs::read_dir(&d) else { return json!({"count": 0, "bytes": 0, "dir": d}) };
    let (mut count, mut bytes) = (0u64, 0u64);
    for e in rd.flatten() {
        let Ok(m) = std::fs::metadata(e.path()) else { continue };
        if m.is_file() && paths::name_suffix(&e.file_name().to_string_lossy()) != ".json" {
            count += 1;
            bytes += m.len();
        }
    }
    json!({"count": count, "bytes": bytes, "dir": d})
}

// ==== 候補 ==================================================================

/// GET /api/join-candidates
pub(crate) fn get_candidates(core: &Core, _: &Ask, _: &[String]) -> Reply {
    answer_candidates(core).unwrap_or_else(|_| Reply::pass())
}

fn answer_candidates(core: &Core) -> R<Reply> {
    let (c, runs) = config::read_with(core, |_, conn| schedule::job_runs(conn))?;
    let b = core.bases().ok_or(Pass)?;
    let mut items: Vec<Map<String, Value>> = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    let mut add = |path: &str, job: &Value, job_id: &Value, format: Value, role: &str| {
        let p = paths::py_path(path);
        let key = p.to_lowercase();
        if pyish::strip(&p).is_empty() || seen.contains(&key) {
            return;
        }
        seen.push(key);
        let meta = std::fs::metadata(&p).ok();
        let exists = meta.as_ref().is_some_and(|m| m.is_file());
        let mtime =
            meta.as_ref().filter(|_| exists).and_then(|m| m.modified().ok()).map(|t| match t.duration_since(std::time::UNIX_EPOCH) {
                Ok(d) => d.as_secs() as i64,
                Err(e) => -(e.duration().as_secs() as i64), // int() は 0 の側へ切る
            });
        let mut m = Map::new();
        m.insert("path".into(), json!(p));
        m.insert("name".into(), json!(paths::py_name(&p)));
        m.insert("exists".into(), json!(exists));
        m.insert("size".into(), meta.as_ref().filter(|_| exists).map(|m| json!(m.len())).unwrap_or(Value::Null));
        m.insert("mtime".into(), mtime.map(|x| json!(x)).unwrap_or(Value::Null));
        m.insert("job".into(), job.clone());
        m.insert("job_id".into(), job_id.clone());
        m.insert("format".into(), format);
        m.insert("role".into(), json!(role));
        items.push(m);
    };
    for j in jobs(&c) {
        let Value::Object(j) = j else { return Err(Pass) };
        let name = j.get("name").cloned().unwrap_or(json!(""));
        let id = j.get("id").cloned().unwrap_or(json!(""));
        let folder = output_folder(&b, j, &c);
        let actual = viewer_output_path(core, &b, j, &c, &runs);
        let fmt = naming::normalize_output_format(j.get("output_format"), Some(&json!(paths::py_name(&actual))));
        add(&actual, &name, &id, json!(fmt), "primary");
        for x in plan(core, j, &c) {
            let file = x["file"].as_str().unwrap_or("");
            let role = if x["primary"] == json!(true) { "primary" } else { "extra" };
            add(&paths::join(&folder, file), &name, &id, x["format"].clone(), role);
        }
    }
    // ほかの結合マスタが既に使っているファイルも、確かめ済みの手がかりとして出す
    for r in c.get("join_recipes").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
        for s in r["sources"].as_array().map(Vec::as_slice).unwrap_or(&[]) {
            if !pyish::truthy(&s["path"]) {
                continue;
            }
            add(&join_path(&b, &c, &s["path"]), &r["name"], &json!(""), s["format"].clone(), "recipe");
        }
    }
    // 実物があるものが先。その中では新しい順、同じなら名前の順（大文字小文字は見ない）
    items.sort_by(|a, z| {
        let k = |m: &Map<String, Value>| {
            (
                if m["exists"] == json!(true) { 0 } else { 1 },
                -m["mtime"].as_i64().unwrap_or(0),
                m["name"].as_str().unwrap_or("").to_lowercase(),
            )
        };
        k(a).cmp(&k(z))
    });
    items.truncate(200);
    Ok(Reply::json(200, &json!({"items": items, "cache": cache_stats()})))
}

// ==== 材料の持ち主 ==========================================================

/// navi_order.wait_settings（材料を待つ設定。int() で読めない値は Python が落ちるので Pass）。
fn wait_settings(cfg: &Map<String, Value>) -> R<Value> {
    let s = cfg.get("settings").and_then(Value::as_object).cloned().unwrap_or_default();
    let int = |k: &str, default: i64, zero: i64| -> R<i64> {
        match s.get(k).unwrap_or(&json!(default)) {
            v if !pyish::truthy(v) => Ok(zero),
            v => pyish::int_opt(v).ok().flatten().ok_or(Pass),
        }
    };
    Ok(json!({
        "enabled": s.get("join_wait_enabled").map(pyish::truthy).unwrap_or(true),
        "lookahead": int("join_wait_lookahead_seconds", 60, 0)?.clamp(0, 3600),
        "max_wait": int("join_wait_max_seconds", 600, 0)?.clamp(0, 86400),
        "poll": int("join_wait_poll_seconds", 5, 5)?.clamp(1, 60),
    }))
}

/// POST /api/join-order
pub(crate) fn post_order(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    answer_order(core, ask).unwrap_or_else(|_| Reply::pass())
}

fn answer_order(core: &Core, ask: &Ask) -> R<Reply> {
    let d = match writer::body_json(ask, true)? {
        Some(Value::Object(m)) => m,
        Some(v) if pyish::truthy(&v) => return Err(Pass),
        _ => Map::new(),
    };
    let (c, runs) = config::read_with(core, |_, conn| schedule::job_runs(conn))?;
    let b = core.bases().ok_or(Pass)?;
    let raw = match d.get("recipe") {
        Some(Value::Object(m)) => m.clone(),
        Some(v) if pyish::truthy(v) => return Err(Pass),
        _ => Map::new(),
    };
    let recipe = config::normalize_recipe(&raw)?;
    // 出力ファイルの場所 → それを作る対象（いま在るファイルと、次に作る名前の両方）
    let mut owners: Vec<(String, Vec<&Map<String, Value>>)> = Vec::new();
    for j in jobs(&c) {
        let Value::Object(j) = j else { return Err(Pass) };
        let folder = output_folder(&b, j, &c);
        let mut ps = vec![viewer_output_path(core, &b, j, &c, &runs)];
        ps.extend(plan(core, j, &c).iter().map(|x| paths::join(&folder, x["file"].as_str().unwrap_or(""))));
        for p in ps {
            let k = owner_key(&p);
            let at = match owners.iter().position(|(x, _)| *x == k) {
                Some(i) => i,
                None => {
                    owners.push((k, vec![]));
                    owners.len() - 1
                }
            };
            if !owners[at].1.iter().any(|x| x.get("id") == j.get("id")) {
                owners[at].1.push(j);
            }
        }
    }
    let mut out = Vec::new();
    for sx in recipe["sources"].as_array().map(Vec::as_slice).unwrap_or(&[]) {
        if !pyish::truthy(&sx["path"]) {
            continue;
        }
        let path = join_path(&b, &c, &sx["path"]);
        let made: Vec<Value> = owners
            .iter()
            .find(|(k, _)| *k == owner_key(&path))
            .map(|(_, js)| {
                js.iter()
                    .map(|j| {
                        json!({"id": j.get("id").cloned().unwrap_or(Value::Null), "name": j.get("name").cloned().unwrap_or(json!("")),
                               "enabled": j.get("enabled").is_some_and(pyish::truthy)})
                    })
                    .collect()
            })
            .unwrap_or_default();
        out.push(json!({"alias": sx["alias"], "name": paths::py_name(&path), "path": path, "exists": is_file(&path), "made_by": made}));
    }
    let made_count = out.iter().filter(|x| x["made_by"].as_array().is_some_and(|a| !a.is_empty())).count();
    Ok(Reply::json(200, &json!({"ok": true, "sources": out, "made_count": made_count, "wait": wait_settings(&c)?})))
}

// ==== 写しを捨てる ==========================================================

/// POST /api/join-cache/clear（navi_localcopy.clear。消せない物は数えない）。
pub(crate) fn post_cache_clear(core: &Core, _: &Ask, _: &[String]) -> Reply {
    let d = cache_dir();
    let mut n = 0;
    if let Ok(rd) = std::fs::read_dir(&d) {
        for e in rd.flatten() {
            if std::fs::remove_file(e.path()).is_ok() {
                n += 1;
            }
        }
    }
    core.log(&format!("JOIN_CACHE_CLEAR removed={n}"));
    Reply::json(200, &json!({"ok": true, "removed": n, "cache": cache_stats()}))
}
