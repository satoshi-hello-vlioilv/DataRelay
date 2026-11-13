//! 関数ごとの突き合わせの口（`datarelay-core call`）。tests/test_rust_paths.py が、いろいろなフォルダーの状態を作って
//! Python の関数（navi_paths・navi_release）と同じ問いを出し、答えを比べる。ルートの答えだけでは、フォルダーの状態で
//! 変わる決まり（データの基準の決める順など）を一通り確かめられないため。配る exe の動きには関わらない。

use crate::naming;
use crate::paths::{self, Bases};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};

fn s<'a>(a: &'a Value, k: &str) -> &'a str {
    a.get(k).and_then(Value::as_str).unwrap_or("")
}

/// 値を字に（id・名前は字のことがほとんど。数でもそのまま字にする）。
fn s_of_val(v: &Value) -> String {
    v.as_str().map(String::from).unwrap_or_else(|| crate::pyish::py_str(v))
}

fn opt<'a>(a: &'a Value, k: &str) -> Option<&'a str> {
    a.get(k).and_then(Value::as_str)
}

fn p2s(p: PathBuf) -> String {
    p.to_string_lossy().into_owned()
}

fn bases(a: &Value) -> Bases {
    let b = &a["bases"];
    Bases {
        data_root: paths::py_path(s(b, "data_root")),
        data_source: s(b, "data_source").into(),
        local_root: paths::py_path(s(b, "local_root")),
        program_root: paths::py_path(s(b, "program_root")),
        place: opt(b, "place").map(paths::py_path),
    }
}

fn passed(r: Result<Value, crate::config::Pass>) -> Value {
    r.unwrap_or_else(|_| json!({"pass": true}))
}

/// 引数の日時（"2026-11-01T09:05:07.123456"）。
fn when(a: &Value) -> Result<chrono::NaiveDateTime, String> {
    chrono::NaiveDateTime::parse_from_str(s(a, "dt"), "%Y-%m-%dT%H:%M:%S%.f").map_err(|e| format!("日時を読めません: {e}"))
}

/// 問い（関数の名前と引数）に答える。
pub fn call(name: &str, a: &Value) -> Result<Value, String> {
    let env_map: Map<String, Value> = a.get("env").and_then(Value::as_object).cloned().unwrap_or_default();
    let env = move |k: &str| env_map.get(k).and_then(Value::as_str).map(String::from);
    Ok(match name {
        "data_root" => {
            let place = opt(a, "place").map(PathBuf::from);
            let (root, src) = paths::data_root(Path::new(s(a, "base")), &env, place.as_deref());
            json!([p2s(root), src])
        }
        "update_dir" => {
            let (root, src) = paths::update_dir_with(Path::new(s(a, "app_root")), opt(a, "shared"));
            json!([p2s(root), src])
        }
        "release_root" => json!(p2s(paths::release_root(Path::new(&paths::py_path(s(a, "path")))))),
        "path_kind" => json!(paths::path_kind(s(a, "value"))),
        "expand" => json!(paths::expand(s(a, "value"))),
        "portable" => json!(paths::portable(s(a, "value"), opt(a, "home").map(Path::new))),
        "users_root" => json!(p2s(paths::users_root(Path::new(s(a, "place"))))),
        "user_dir" => json!(paths::user_dir(opt(a, "place").map(Path::new), &env).map(p2s)),
        "logon_name" => json!(paths::logon_name(&env)),
        "py_path" => json!(paths::py_path(s(a, "value"))),
        // Windows の流儀（OS によらず）: Linux の試験でも Python の PureWindowsPath・ntpath と比べる
        "py_path_nt" => json!(paths::py_path_nt(s(a, "value"))),
        "expand_user_nt" => json!(paths::expand_user_nt(s(a, "value"), &env)),
        "resolve" => json!(paths::resolve(s(a, "value"))),
        "rel_bases" => json!(bases(a).rel_bases()),
        "resolve_path" => json!(bases(a).resolve_path(opt(a, "value"), opt(a, "base"))),
        "resolve_in" => json!(bases(a).resolve_in(s(a, "value"), opt(a, "folder"))),
        "locate" => Value::Object(bases(a).locate(s(a, "value"), opt(a, "folder"))),
        "to_relative" => json!(bases(a).to_relative(s(a, "path"), a["inside_only"].as_bool().unwrap_or(false))),
        // symnavim.conf の読み方（configparser と同じ決まり）。書き方の誤りは種類だけ（Python の例外の文言は同じにならない）
        "parse_conf" => match crate::secret::parse_conf(s(a, "text")) {
            Ok(d) => json!({"ok": d}),
            Err(Ok(_)) => json!({"syntax": true}),
            Err(Err(m)) => json!({"error": m}),
        },
        "read_conf_text" => match crate::secret::read_conf_text(
            &a["bytes"].as_array().map(|v| v.iter().filter_map(|x| x.as_u64()).map(|x| x as u8).collect::<Vec<u8>>()).unwrap_or_default(),
        ) {
            Ok(t) => json!({"ok": t}),
            Err(m) => json!({"error": m}),
        },
        // Windows の資格情報マネージャー（試験用の名前で）。Rust が書いた物を Python が読めるか、その逆も
        #[cfg(windows)]
        "win_vault" => {
            let v = crate::secret::Vault::Windows(s(a, "target").into());
            match s(a, "op") {
                "save" => json!(v.save(a["data"].as_object().ok_or("data が辞書ではありません")?).map_err(|e| e.to_string())?),
                "load" => v.load()?.unwrap_or(Value::Null),
                "delete" => json!(v.delete()?),
                op => return Err(format!("知らない操作: {op}")),
            }
        }
        // 設定の読み出し（config.rs・naming.rs）。Python だけが読める形のときは {"pass": true}
        "py_str" => json!(crate::pyish::py_str(&a["v"])),
        "normalize_variants" => passed(crate::config::normalize_variants(&a["v"])),
        "normalize_viewer" => passed(crate::config::normalize_viewer(&a["v"])),
        "normalize_post" => passed(crate::config::normalize_post(&a["v"])),
        "normalize_group" => json!(crate::config::normalize_group(a.get("v"))),
        "normalize_layout" => passed(crate::config::normalize_layout(a["d"].as_object().ok_or("d が辞書ではありません")?)),
        "normalize_recipe" => passed(crate::config::normalize_recipe(a["d"].as_object().ok_or("d が辞書ではありません")?)),
        "normalize_query" => crate::config::normalize_query(a["d"].as_object().ok_or("d が辞書ではありません")?),
        "normalize_output_format" => json!(naming::normalize_output_format(a.get("value"), a.get("filename"))),
        "canonical_output_file" => json!(naming::canonical_output_file(a.get("filename"), s(a, "fmt"))),
        "job_extra_formats" => match naming::job_extra_formats(a["job"].as_object().ok_or("job が辞書ではありません")?) {
            Some(v) => json!(v),
            None => json!({"pass": true}),
        },
        "strftime" => match naming::strftime(when(a)?, s(a, "fmt")) {
            Ok(t) => json!(t),
            Err(_) => json!({"error": true}),
        },
        "format_custom_datetime" => json!(naming::format_custom_datetime(when(a)?, s(a, "pattern"))),
        "apply_date_offset" => match naming::apply_date_offset(when(a)?, s(a, "offset")) {
            Ok(t) => json!(t.format("%Y-%m-%dT%H:%M:%S%.6f").to_string()),
            Err(_) => json!({"error": true}),
        },
        "apply_text_op" => json!(naming::apply_text_op(s(a, "value"), s(a, "arg"))),
        "split_source_offset" => json!(naming::split_source_offset(s(a, "key"))),
        "has_template_variables" => json!(naming::has_template_variables(s(a, "pattern"))),
        "render_filename_template" | "render_filename_segments" => {
            let job = a["job"].as_object().cloned().unwrap_or_default();
            let t = naming::Tokens::new(&job, opt(a, "rne_path"), when(a)?);
            let r = if name == "render_filename_template" {
                naming::render_filename_template(s(a, "template"), &t).map(|x| json!(x))
            } else {
                naming::render_filename_segments(s(a, "template"), &t)
                    .map(|v| json!(v.into_iter().map(|(t, v)| json!({"text": t, "var": v})).collect::<Vec<_>>()))
            };
            r.unwrap_or_else(|_| json!({"error": true}))
        }
        "render_path_template" => {
            let job = a["job"].as_object().cloned().unwrap_or_default();
            let t = naming::Tokens::new(&job, opt(a, "rne_path"), when(a)?);
            crate::variants::render_path_template(s(a, "template"), &t).map(|x| json!(x)).unwrap_or_else(|_| json!({"error": true}))
        }
        "suggest_keys" => {
            let strs =
                |v: &Value| -> Vec<String> { v.as_array().into_iter().flatten().map(|x| x.as_str().unwrap_or("").to_string()).collect() };
            let rows = |v: &Value| -> Vec<Vec<String>> { v.as_array().into_iter().flatten().map(strs).collect() };
            json!(crate::joinrun::suggest_keys(&strs(&a["lh"]), &rows(&a["lr"]), &strs(&a["rh"]), &rows(&a["rr"]), 5))
        }
        "csv_row" => {
            let row: Vec<String> = a["row"].as_array().into_iter().flatten().map(|x| x.as_str().unwrap_or("").to_string()).collect();
            json!(crate::viewer::csv_row(&row, if s(a, "delimiter") == "\t" { '\t' } else { ',' }))
        }
        // 実行の記録（runs.rs）。設定の写しへ書く。日時は DATARELAY_FIXED_NOW で決める
        "record_job_run" | "record_rne_result" | "record_local_result" => {
            let mut core = crate::routes::Core::with_program(Path::new(s(a, "base")));
            if let Ok(t) = std::env::var("DATARELAY_FIXED_NOW") {
                core.fixed_now = chrono::NaiveDateTime::parse_from_str(&t, "%Y-%m-%dT%H:%M:%S%.f").ok();
            }
            let job = a["job"].as_object().cloned().unwrap_or_default();
            let result = a["result"].as_object().cloned().unwrap_or_default();
            let trigger = s(a, "trigger");
            let (one, rec) = match name {
                "record_rne_result" => {
                    let (one, rec) = crate::runs::from_rne_result(&job, &result, trigger);
                    (one, rec)
                }
                "record_local_result" => (Value::Null, crate::runs::from_local_result(&job, &result, trigger)),
                _ => {
                    let r = &a["record"];
                    let rec = crate::runs::JobRecord {
                        job_id: r["job_id"].clone(),
                        job_name: r["job_name"].clone(),
                        status: s(r, "status").into(),
                        trigger: s(r, "trigger").into(),
                        detail: s(r, "detail").into(),
                        rows: r["rows"].clone(),
                        cols: r["cols"].clone(),
                        output_file: s(r, "output_file").into(),
                        metrics: r["metrics"].clone(),
                    };
                    (Value::Null, rec)
                }
            };
            let written = crate::runs::record_job_run(&core, &rec).is_ok();
            core.settle_writes("probe");
            json!({"one": one, "written": written})
        }
        // RNE 単位の控え（runs.rs）と、その鍵・指紋・端末
        "rne_notes" => {
            let mut core = crate::routes::Core::with_program(Path::new(s(a, "base")));
            if let Ok(t) = std::env::var("DATARELAY_FIXED_NOW") {
                core.fixed_now = chrono::NaiveDateTime::parse_from_str(&t, "%Y-%m-%dT%H:%M:%S%.f").ok();
            }
            let mut out = vec![];
            for op in a["ops"].as_array().into_iter().flatten() {
                let job = op["job"].as_object().cloned().unwrap_or_default();
                let rp = s(op, "rne_path");
                let r = match s(op, "fn") {
                    "record_rne_run" => crate::runs::record_rne_run(
                        &core,
                        rp,
                        &job,
                        s(op, "status"),
                        s(op, "trigger"),
                        &op["metrics"].as_object().cloned().unwrap_or_default(),
                        s(op, "engine"),
                        s(op, "fmt"),
                    )
                    .map(|x| json!(x)),
                    "save_column_cache" => {
                        crate::runs::save_column_cache(&core, rp, &op["columns"], &op["rows"], s(op, "source"), &job).map(|x| json!(x))
                    }
                    _ => crate::runs::save_rne_timing(&core, rp, &op["execute"], &op["save"], &op["total"], &op["rows"], &op["cols"])
                        .map(|x| json!(x)),
                };
                out.push(r.unwrap_or_else(|_| json!({"pass": true})));
            }
            core.settle_writes("probe");
            json!({"results": out, "keys": a["paths"].as_array().into_iter().flatten().map(|p| {
                let p = s_of_val(p);
                json!([crate::runs::rne_key(&p), crate::runs::rne_signature(&p)])
            }).collect::<Vec<_>>(), "cpu": crate::runs::cpu_count()})
        }
        // 材料の関係（joinplan::dependencies）。クエリの対象が入っていれば Python へ回す
        "job_dependencies" => {
            let mut core = crate::routes::Core::with_program(Path::new(s(a, "base")));
            if let Ok(t) = std::env::var("DATARELAY_FIXED_NOW") {
                core.fixed_now = chrono::NaiveDateTime::parse_from_str(&t, "%Y-%m-%dT%H:%M:%S%.f").ok();
            }
            let b = core.bases().ok_or("置き場が分からない")?;
            let Ok((c, runs)) = crate::config::read_with(&core, |_, conn| crate::schedule::job_runs(conn)) else {
                return Ok(json!({"pass": true}));
            };
            let want: Vec<String> = a["ids"].as_array().into_iter().flatten().map(s_of_val).collect();
            let run_jobs: Vec<Map<String, Value>> = c
                .get("jobs")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|j| j.as_object().cloned())
                .filter(|j| want.is_empty() || want.contains(&j.get("id").map(s_of_val).unwrap_or_default()))
                .collect();
            match crate::joinplan::dependencies(&core, &b, &c, &runs, &run_jobs, &|_| None) {
                Ok(d) => json!(d.into_iter().collect::<std::collections::BTreeMap<_, _>>()),
                Err(_) => json!({"pass": true}),
            }
        }
        // ワーカーを起こして終わりまで見守る（worker.rs）。見えた工程の様子を順に返す
        "run_worker" => {
            let payload = a["payload"].clone();
            let spawn = crate::worker::Spawn {
                python: Path::new(s(a, "python")),
                program_root: Path::new(s(a, "program_root")),
                dir: Path::new(s(a, "dir")),
                payload: &payload,
                line: s(a, "line"),
            };
            let mut w = crate::worker::Worker::spawn(&spawn).map_err(|e| e.to_string())?;
            let limit = a["limit_seconds"].as_f64().map(std::time::Duration::from_secs_f64);
            let mut seen: Vec<Value> = Vec::new();
            let end = loop {
                if let Some(st) = w.status() {
                    let st = Value::Object(st);
                    if seen.last() != Some(&st) {
                        seen.push(st);
                    }
                }
                if let Some(end) = w.poll(limit) {
                    break end;
                }
                std::thread::sleep(std::time::Duration::from_millis(30));
            };
            json!({"result": end.result, "code": end.code, "timed_out": end.timed_out, "statuses": seen, "line": w.line})
        }
        // 実行の指令の待機キュー・知らせ・取り直し（commands.rs）。ops を順に当て、それぞれの答えを返す。
        // 消す・動かす・読んだ知らせは、いまの並びの何番目かで指す（id は作るたびに違うので）
        "commands" => {
            let cfg = a["cfg"].as_object().cloned().unwrap_or_default();
            let mut c = crate::commands::Commands::default();
            let mut out = vec![];
            for op in a["ops"].as_array().into_iter().flatten() {
                let now = chrono::NaiveDateTime::parse_from_str(s(op, "now"), "%Y-%m-%dT%H:%M:%S").map_err(|e| e.to_string())?;
                let qid = |c: &crate::commands::Commands| {
                    op["index"]
                        .as_u64()
                        .and_then(|i| c.queue.get(i as usize))
                        .and_then(|x| x["id"].as_str().map(String::from))
                        .unwrap_or_default()
                };
                let r = match s(op, "op") {
                    "enqueue" => {
                        let ids: Vec<String> = op["job_ids"].as_array().into_iter().flatten().map(s_of_val).collect();
                        let lines = op.get("lines");
                        match crate::commands::Commands::new_item(
                            &cfg,
                            &ids,
                            s(op, "trigger"),
                            lines,
                            op["attempt"].as_i64().unwrap_or(0),
                            now,
                        ) {
                            Ok(item) => json!({"position": c.enqueue(item)}),
                            Err(e) => json!({"error": e}),
                        }
                    }
                    "start" => {
                        c.active = if c.queue.is_empty() { None } else { Some(c.queue.remove(0)) };
                        Value::Null
                    }
                    "join" => {
                        if let Some(x) = c.active.as_mut() {
                            for (k, v) in [("joined_ids", &op["ids"]), ("joined_names", &op["names"])] {
                                let mut cur = x.get(k).and_then(Value::as_array).cloned().unwrap_or_default();
                                cur.extend(v.as_array().cloned().unwrap_or_default());
                                x.insert(k.into(), json!(cur));
                            }
                        }
                        Value::Null
                    }
                    "finish" => {
                        let item = c.active.take().unwrap_or_default();
                        let st = op["status"].as_object().cloned().unwrap_or_default();
                        c.after_command(&item, &st, s(op, "error"), op["cancelled"].as_bool().unwrap_or(false), &cfg, now);
                        Value::Null
                    }
                    "snapshot" => c.snapshot(),
                    "delete" => {
                        let id = qid(&c);
                        json!(c.delete(&id).is_some())
                    }
                    "move" => {
                        let id = qid(&c);
                        json!(c.move_item(&id, &op["direction"]).is_some())
                    }
                    "clear" => json!(c.clear_queue()),
                    "alert" => {
                        let jobs = op["jobs"].as_array().cloned().unwrap_or_default();
                        c.add_alert(s(op, "kind"), s(op, "title"), s(op, "detail"), &jobs, now);
                        Value::Null
                    }
                    "alerts" => c.alerts_view(),
                    "ack" => {
                        let ids: Vec<Value> = op["indexes"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .filter_map(|i| c.alerts.get(i.as_u64().unwrap_or(0) as usize).map(|x| x["id"].clone()))
                            .collect();
                        let (removed, count) = c.ack(&ids);
                        json!({"removed": removed, "count": count})
                    }
                    "retry" => {
                        let ids = op["job_ids"].as_array().cloned().unwrap_or_default();
                        let names = op["names"].as_array().cloned().unwrap_or_default();
                        match c.schedule_retry(&ids, &names, &op["lines"], op["attempt"].as_i64().unwrap_or(0), &cfg, now) {
                            Ok(due) => json!(due.map(|d| d.format("%Y-%m-%dT%H:%M:%S").to_string())),
                            Err(_) => json!({"pass": true}),
                        }
                    }
                    "due" => json!(c
                        .due_retries(now)
                        .into_iter()
                        .map(|r| json!({"job_ids": r.job_ids, "names": r.names, "lines": r.lines, "attempt": r.attempt}))
                        .collect::<Vec<_>>()),
                    "cancel_retries" => json!(c.cancel_retries()),
                    "clamp" => json!(crate::commands::clamp_lines(op.get("value"), &cfg, 1)),
                    other => return Err(format!("知らない op: {other}")),
                };
                out.push(r);
            }
            json!(out)
        }
        // 実行の黒板（board.rs）を偽のワーカーで最後まで回す。札の移り変わり・締め・記録を返す
        "run_board" => {
            use std::collections::{BTreeSet, HashMap};
            use std::time::{Duration, Instant};
            let mut core = crate::routes::Core::with_program(Path::new(s(a, "base")));
            if let Ok(t) = std::env::var("DATARELAY_FIXED_NOW") {
                core.fixed_now = chrono::NaiveDateTime::parse_from_str(&t, "%Y-%m-%dT%H:%M:%S%.f").ok();
            }
            let strs = |v: &Value| -> BTreeSet<String> { v.as_array().into_iter().flatten().map(s_of_val).collect() };
            let map_sets = |v: &Value| -> HashMap<String, BTreeSet<String>> {
                v.as_object().into_iter().flatten().map(|(k, v)| (k.clone(), strs(v))).collect()
            };
            let map_strs = |v: &Value| -> HashMap<String, String> {
                v.as_object().into_iter().flatten().map(|(k, v)| (k.clone(), s_of_val(v))).collect()
            };
            let objs = |v: &Value| -> Vec<Map<String, Value>> {
                v.as_array().into_iter().flatten().filter_map(|j| j.as_object().cloned()).collect()
            };
            let secs = |k: &str, d: f64| Duration::from_secs_f64(a[k].as_f64().unwrap_or(d));
            let settings = crate::board::Settings {
                python: PathBuf::from(s(a, "python")),
                program_root: PathBuf::from(s(a, "program_root")),
                work: PathBuf::from(s(a, "work")),
                backup: PathBuf::from(s(a, "work")).join("backup"),
                cfg: a["cfg"].clone(),
                api_lines: a["api_lines"].as_u64().unwrap_or(2) as usize,
                local_lines: a["local_lines"].as_u64().unwrap_or(1) as usize,
                cap: a["cap"].as_u64().unwrap_or(4) as usize,
                trigger: s(a, "trigger").into(),
                worker_limit: a["limit_seconds"].as_f64().map(Duration::from_secs_f64),
                stagger: secs("stagger_seconds", 0.0),
                login: a["login"].as_array().map(|x| (s_of_val(&x[0]), s_of_val(&x[1]))),
                wait_enabled: a["wait_enabled"].as_bool().unwrap_or(true),
                max_wait: secs("max_wait_seconds", 30.0),
                poll: secs("poll_seconds", 0.05),
            };
            let cells: HashMap<String, i64> =
                a["cells"].as_object().into_iter().flatten().map(|(k, v)| (k.clone(), v.as_i64().unwrap_or(0))).collect();
            let mut board = crate::board::Board::new(settings, objs(&a["jobs"]), &map_sets(&a["deps"]), &map_strs(&a["kinds"]), &cells);
            // 待つ理由: 対象 id → 何回見直すまで待たせるか
            let waits = std::cell::RefCell::new(
                a["waits"]
                    .as_object()
                    .into_iter()
                    .flatten()
                    .map(|(k, v)| (k.clone(), v.as_i64().unwrap_or(0)))
                    .collect::<HashMap<String, i64>>(),
            );
            let waiter = |j: &Map<String, Value>| -> Vec<Value> {
                let id = j.get("id").map(s_of_val).unwrap_or_default();
                let mut w = waits.borrow_mut();
                match w.get_mut(&id) {
                    Some(n) if *n > 0 => {
                        *n -= 1;
                        vec![json!({"kind": "running", "job": "上流", "job_id": "up"})]
                    }
                    _ => vec![],
                }
            };
            let t0 = Instant::now();
            let mut joins = objs(&a["joins"]);
            let cancel_at = a["cancel_after_seconds"].as_f64();
            let mut joined: Vec<Value> = vec![];
            let mut seen: Vec<Value> = vec![];
            let mut peak = 0usize;
            loop {
                let t = t0.elapsed().as_secs_f64();
                while joins.first().is_some_and(|j| j["after_seconds"].as_f64().unwrap_or(0.0) <= t) {
                    let j = joins.remove(0);
                    joined.push(json!(board.join(
                        &core,
                        objs(&j["jobs"]),
                        &map_sets(&j["deps"]),
                        &map_strs(&j["kinds"]),
                        s(&Value::Object(j.clone()), "trigger")
                    )));
                }
                if cancel_at.is_some_and(|c| c <= t) {
                    board.cancel();
                }
                let more = board.tick(&core, &waiter);
                let st = board.status();
                peak = peak.max(st["queue_active"].as_u64().unwrap_or(0) as usize);
                let brief =
                    json!({"running": st["queue_running_ids"], "done": st["queue_completed_ids"], "failed": st["queue_failed_ids"]});
                if seen.last() != Some(&brief) {
                    seen.push(brief);
                }
                if !more || t > a["give_up_seconds"].as_f64().unwrap_or(60.0) {
                    break;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            core.settle_writes("probe");
            json!({"status": board.status(), "outcome": board.outcome(), "steps": seen, "peak": peak, "joined": joined})
        }
        // ラインの割り当ての決まり（lane.rs）をまとめて1回で
        "lane_all" => {
            use std::collections::{BTreeSet, HashMap};
            let strs = |v: &Value| -> BTreeSet<String> { v.as_array().into_iter().flatten().map(s_of_val).collect() };
            let jobs: Vec<(String, String)> =
                a["jobs"].as_array().into_iter().flatten().map(|j| (s_of_val(&j["id"]), s_of_val(&j["name"]))).collect();
            let deps: HashMap<String, BTreeSet<String>> =
                a["deps"].as_object().into_iter().flatten().map(|(k, v)| (k.clone(), strs(v))).collect();
            let kinds: HashMap<String, String> =
                a["kinds"].as_object().into_iter().flatten().map(|(k, v)| (k.clone(), s_of_val(v))).collect();
            let (done, started, failed) = (strs(&a["done"]), strs(&a["started"]), strs(&a["failed"]));
            let plan = crate::lane::build_plan(&jobs, &deps, &kinds);
            let ids = |v: Vec<&crate::lane::Entry>| json!(v.iter().map(|e| e.id.clone()).collect::<Vec<_>>());
            let ids_vec: Vec<String> = jobs.iter().map(|(i, _)| i.clone()).collect();
            let (order, _cycle) = crate::lane::order_jobs(&ids_vec, &deps);
            json!({
                "plan": plan.iter().map(|e| json!({"id": e.id, "kind": e.kind, "tier": e.tier, "order": e.order, "needs": e.needs})).collect::<Vec<_>>(),
                "ready": ids(crate::lane::ready(&plan, &done, &started, None)),
                "ready_local": ids(crate::lane::ready(&plan, &done, &started, Some(&crate::lane::LOCAL_KINDS))),
                "unreachable": ids(crate::lane::unreachable(&plan, &failed, &done)),
                "names": crate::lane::names_of(&strs(&a["some"]), &plan),
                "blocking": plan.iter().map(|e| crate::lane::blocking_names(e, &plan, &done)).collect::<Vec<_>>(),
                "plan_text": crate::lane::plan_text(&plan),
                "wait_text": crate::lane::wait_text(&plan),
                "order": order,
                "upstream": jobs.iter().map(|(i, _)| crate::lane::upstream_of(i, &deps, 6)).collect::<Vec<_>>(),
                "local_lines": crate::lane::local_lines(&a["configured"], a["batch_lines"].as_i64().unwrap_or(0), a["local_count"].as_i64().unwrap_or(0)),
                "reason_text": crate::lane::reason_text(a["reasons"].as_array().map(Vec::as_slice).unwrap_or(&[])),
            })
        }
        "wait_reasons" => {
            use std::collections::{BTreeSet, HashMap};
            let strs = |v: &Value| -> BTreeSet<String> { v.as_array().into_iter().flatten().map(s_of_val).collect() };
            let deps: HashMap<String, BTreeSet<String>> =
                a["deps"].as_object().into_iter().flatten().map(|(k, v)| (k.clone(), strs(v))).collect();
            let next = a["next"].as_object().cloned().unwrap_or_default();
            let at = |v: &Value| chrono::NaiveDateTime::parse_from_str(v.as_str().unwrap_or(""), "%Y-%m-%dT%H:%M:%S").ok();
            let inputs: Vec<String> = a["inputs"].as_array().into_iter().flatten().map(s_of_val).collect();
            json!(crate::lane::wait_reasons(
                s(a, "job"),
                &deps,
                &strs(&a["running"]),
                &strs(&a["queued"]),
                |o| next.get(o).and_then(at),
                &inputs,
                when(a)?,
                a["lookahead"].as_i64().unwrap_or(60),
                |o| format!("名{o}"),
            ))
        }
        "trim_to_line" => {
            let b: Vec<u8> = a["bytes"].as_array().into_iter().flatten().map(|x| x.as_u64().unwrap_or(0) as u8).collect();
            json!(crate::localcopy::trim_to_line(&b))
        }
        "variants_has_token" => json!(crate::variants::has_token(s(a, "text"))),
        "variants_plan" => {
            let job = a["job"].as_object().cloned().unwrap_or_default();
            let v = match crate::config::normalize_variants(job.get("variants").unwrap_or(&Value::Null)) {
                Ok(v) => v,
                Err(_) => return Ok(json!({"pass": true})),
            };
            let at = when(a)?;
            let tokens = |value: &str| {
                let mut j = job.clone();
                j.insert("_variant_value".into(), json!(value));
                naming::Tokens::new(&j, None, at)
            };
            let values: Vec<String> = a["values"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|x| x.as_str().map(String::from).unwrap_or_else(|| crate::pyish::py_str(x)))
                .collect();
            match crate::variants::plan(&job, &v, tokens, s(a, "base"), s(a, "folder"), &values) {
                Ok(xs) => json!(xs.into_iter().map(|x| json!({"value": x.value, "stem": x.stem, "folder": x.folder})).collect::<Vec<_>>()),
                Err(_) => json!({"error": true}),
            }
        }
        "py_name" => json!(paths::py_name(s(a, "value"))),
        "py_name_nt" => json!(paths::py_name_nt(s(a, "value"))),
        "py_stem" => json!(paths::py_stem(s(a, "value"))),
        "py_suffix" => json!(paths::py_suffix(s(a, "value"))),
        "foreign_profile_path" => json!(crate::config::foreign_profile_path(s(a, "value"))),
        // 予定の決まり（schedule.rs）。Python が落ちる値は {"pass": true}
        "next_occurrence" => match crate::schedule::next_occurrence(&a["rule"], when(a)?) {
            Ok(v) => json!(v.map(|t| t.format("%Y-%m-%dT%H:%M:%S").to_string())),
            Err(_) => json!({"pass": true}),
        },
        "expand_rule_occurrences" => {
            let at = |k: &str| chrono::NaiveDateTime::parse_from_str(s(a, k), "%Y-%m-%dT%H:%M:%S").map_err(|e| e.to_string());
            match crate::schedule::expand_rule_occurrences(&a["rule"], at("start")?, at("end")?, 400) {
                Ok((p, d)) => json!([
                    p.iter().map(|t| t.format("%Y-%m-%dT%H:%M:%S").to_string()).collect::<Vec<_>>(),
                    d.iter()
                        .map(|x| json!({"date": x.date.format("%Y-%m-%d").to_string(), "minutes": x.minutes, "count": x.count}))
                        .collect::<Vec<_>>()
                ]),
                Err(_) => json!({"pass": true}),
            }
        }
        "job_schedule_preview" => passed(crate::schedule::job_schedule_preview(&a["job"], when(a)?).map(Value::Object)),
        "schedule_pause" => passed(
            crate::schedule::schedule_pause(a["state"].as_object().ok_or("state が辞書ではありません")?, when(a)?).map(Value::Object),
        ),
        // datetime.fromisoformat(v).isoformat()。Python も断る形は null、Python へ回す形は "pass"
        "from_iso" => match crate::schedule::from_iso(s(a, "value")) {
            Some(Ok(t)) => json!(t
                .format(if t.and_utc().timestamp_subsec_nanos() == 0 { "%Y-%m-%dT%H:%M:%S" } else { "%Y-%m-%dT%H:%M:%S%.6f" })
                .to_string()),
            Some(Err(())) => Value::Null,
            None => json!("pass"),
        },
        // bytes.decode(enc, errors='replace')。hex は16進の並び。Python と同じに読めると言えない文字コードは "pass"
        "decode" => {
            let hex = s(a, "hex");
            let b: Vec<u8> = (0..hex.len() / 2).filter_map(|i| u8::from_str_radix(&hex[2 * i..2 * i + 2], 16).ok()).collect();
            match crate::textread::enc_of(s(a, "enc")) {
                Some(e) => json!(crate::textread::decode(e, &b).0),
                None => json!("pass"),
            }
        }
        // list(csv.reader(io.StringIO(text, newline=''), delimiter=d))。Python と同じに読めると言えない物は "pass"
        "csv" => match crate::viewer::read_csv(s(a, "text"), s(a, "delimiter").chars().next().unwrap_or(',')) {
            Ok(rows) => json!(rows),
            Err(_) => json!("pass"),
        },
        "last_run_info" => passed(crate::schedule::last_run_info(a["run"].as_object()).map(Value::Object)),
        "seconds_in" => json!(crate::schedule::seconds_in(s(a, "detail"))),
        _ => return Err(format!("知らない問い: {name}")),
    })
}
