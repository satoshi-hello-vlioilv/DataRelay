//! 実行の受け付けと、指令1つを最後まで流す役（2.41.0〜）。app.py の process・command_dispatcher・join_running・
//! absorb_waiting・command_absorber・finish_batch と同じ決まり。まだ使わない（受け口を移して切り替えるのは 5e-2c）。
//!
//! 持ち物は1か所（Runner の中の State）にまとめ、受け口のスレッド・流す役のスレッド・合流の見張りが同じ物を見る:
//!   - 待機キュー・知らせ・取り直し（commands.rs）
//!   - 実行の状態（画面の /api/status が読む。Python の status と同じ鍵）
//!   - いま走っている実行の黒板（board.rs。あとから入れた手動の実行を合流させる先）
//!
//! 引き受けない実行（Err(Pass)）: 材料の関係を Rust で決められないとき（Power Query の対象が設定にある。M の式を読むのは段 6）。
//! 呼ぶ側（5e-2c）は、そのとき Python の実行役へ回す。
use crate::board::{Board, Settings};
use crate::commands::{self, Commands};
use crate::config::{self, Pass};
use crate::paths::Bases;
use crate::{joinplan, lane, naming, pyish, routes::Core, schedule, secret};
use chrono::NaiveDateTime;
use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

type R<T> = Result<T, Pass>;
type Deps = HashMap<String, BTreeSet<String>>;

/// 接続情報が無いときの言い方（app.NO_LOGIN_MESSAGE）。
pub const NO_LOGIN_MESSAGE: &str =
    "Navigator の接続情報が登録されていません。共通設定 →「接続」の「Navigator の接続情報」で登録してください";

/// 実行の外から決まる物（ワーカーを動かす Python・アプリの場所・作業の置き場）。
#[derive(Clone)]
pub struct Env {
    pub python: PathBuf,
    pub program_root: PathBuf,
    /// 作業の置き場（app.dde_staging_folder）
    pub work: PathBuf,
    /// 輪を回す間隔
    pub tick: Duration,
}

/// 受け口・流す役・見張りが共有する持ち物。
#[derive(Default)]
pub struct State {
    pub cmds: Commands,
    pub status: Map<String, Value>,
    /// 中止が押された（次の輪で黒板を止める）
    pub cancel: bool,
    pub live: Option<Arc<Mutex<Board>>>,
}

/// 実行の受け付けと、流す役。
#[derive(Default)]
pub struct Runner {
    pub st: Mutex<State>,
}

/// 画面の状態の最初の形（app.status の初期値）。
pub fn idle_status(build: &str) -> Map<String, Value> {
    let v = json!({"build_version": build, "running": false, "current": "", "current_job_id": "", "current_job_name": "", "current_index": 0,
                   "total_jobs": 0, "step": "idle", "step_label": "待機中", "step_percent": 0, "completed_jobs": 0, "failed_jobs": 0,
                   "started_at": "", "elapsed_seconds": 0, "last_result": "未実行", "last_finished_at": "", "error_detail": "",
                   "activity_detail": "", "activity_value": "", "heartbeat_at": "", "parallel_lines": [], "batch_job_ids": [],
                   "queue_completed_ids": [], "queue_failed_ids": [], "queue_running_ids": [], "queue_waiting_ids": [],
                   "job_errors": [], "job_results": []});
    v.as_object().cloned().unwrap_or_default()
}

fn stamp(now: NaiveDateTime) -> String {
    now.format("%Y-%m-%dT%H:%M:%S").to_string()
}

fn id_of(j: &Map<String, Value>) -> String {
    j.get("id").map(pyish::py_str).unwrap_or_default()
}

fn jobs_of(cfg: &Map<String, Value>) -> Vec<Map<String, Value>> {
    cfg.get("jobs").and_then(Value::as_array).into_iter().flatten().filter_map(|j| j.as_object().cloned()).collect()
}

fn kind_of(j: &Map<String, Value>) -> String {
    crate::settings::job_source(&pyish::text_or_empty(j.get("source"))).to_string()
}

/// 設定の全部の対象の材料の関係（navi_orderrun.job_dependencies(cfg['jobs'])）。Power Query の対象があれば Pass。
fn all_deps(core: &Core, b: &Bases, cfg: &Map<String, Value>, runs: &[(Value, Map<String, Value>)]) -> R<Deps> {
    joinplan::dependencies(core, b, cfg, runs, &jobs_of(cfg), &|_| None)
}

/// navi_connection（利用者ID・サーバー。パスワードはワーカーが自分で置き場から読むので持たない）。
fn login_of(core: &Core, cfg: &Map<String, Value>) -> Result<Option<(String, String)>, String> {
    let vault = secret::Vault::default_for(&PathBuf::from(crate::paths::py_path(&crate::paths::local_root().to_string_lossy())));
    let pick = |d: &Value| Some((pyish::text_or_empty(d.get("user")), pyish::text_or_empty(d.get("server"))));
    match vault.load() {
        Ok(Some(d)) if pyish::truthy(&d) => return Ok(pick(&d)),
        Ok(_) => {}
        Err(e) => return Err(e.to_string()),
    }
    let raw = pyish::strip(&pyish::text_or_empty(cfg.get("symnavim_conf"))).to_string();
    if raw.is_empty() {
        return Ok(None);
    }
    let Some(b) = core.bases() else { return Ok(None) };
    let p = PathBuf::from(b.resolve_path(Some(&raw), None));
    if !p.is_file() {
        return Ok(None);
    }
    secret::read_conf(&p).map(|d| pick(&Value::Object(d))).map_err(|e| e.to_string())
}

/// 設定の数（int(x or 既定)。読めなければ既定）。
fn num(s: &Map<String, Value>, k: &str, default: f64) -> f64 {
    match s.get(k) {
        Some(v) if pyish::truthy(v) => v.as_f64().or_else(|| pyish::text_or_empty(Some(v)).trim().parse().ok()).unwrap_or(default),
        _ => default,
    }
}

impl Runner {
    pub fn new(build: &str) -> Arc<Runner> {
        Arc::new(Runner { st: Mutex::new(State { status: idle_status(build), ..State::default() }) })
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, State> {
        self.st.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// set_status。
    pub fn set_status(&self, v: Map<String, Value>) {
        self.lock().status.extend(v);
    }

    pub fn status(&self) -> Map<String, Value> {
        self.lock().status.clone()
    }

    /// enqueue_command（手動なら、走っている実行へまず合流を試す。合流できなければ待機キューの後ろへ）。(指令, 順番)。
    pub fn enqueue(
        &self,
        core: &Core,
        job_ids: &[String],
        trigger: &str,
        lines: Option<&Value>,
        attempt: i64,
    ) -> Result<(Map<String, Value>, usize), String> {
        let cfg = config::read(core).map_err(|_| "設定を読めませんでした".to_string())?;
        let mut item = Commands::new_item(&cfg, job_ids, trigger, lines, attempt, core.now())?;
        if trigger.starts_with("manual") {
            let mut st = self.lock();
            if st.cmds.active.is_some() && st.cmds.queue.is_empty() && self.join_live(core, &mut st, &cfg, &item) {
                item.insert("joined".into(), json!(true));
                item.insert("joined_to".into(), st.cmds.active.as_ref().and_then(|a| a.get("id").cloned()).unwrap_or(Value::Null));
                core.log(&format!("COMMAND_QUEUE_JOIN id={} jobs={:?} trigger={trigger}", item["id"], item["job_names"]));
                return Ok((item, 0));
            }
        }
        let pos = self.lock().cmds.enqueue(item.clone());
        core.log(&format!("COMMAND_QUEUE_ENQUEUE id={} position={pos} jobs={:?} trigger={trigger}", item["id"], item["job_names"]));
        Ok((item, pos))
    }

    /// 走っている実行の黒板へ、指令の対象を足す（join_live）。足せたら流している指令に joined_ids・joined_names を足して true。
    fn join_live(&self, core: &Core, st: &mut State, cfg: &Map<String, Value>, item: &Map<String, Value>) -> bool {
        let Some(board) = st.live.clone() else { return false };
        let ids: Vec<String> = item.get("job_ids").and_then(Value::as_array).into_iter().flatten().map(pyish::py_str).collect();
        let jobs: Vec<Map<String, Value>> =
            jobs_of(cfg).into_iter().filter(|j| j.get("enabled").is_some_and(pyish::truthy) && ids.contains(&id_of(j))).collect();
        if jobs.is_empty() {
            return false;
        }
        let Some(b) = core.bases() else { return false };
        let Ok((_, runs)) = config::read_with(core, |_, c| schedule::job_runs(c)) else { return false };
        let Ok(deps) = all_deps(core, &b, cfg, &runs) else { return false };
        let kinds: HashMap<String, String> = jobs.iter().map(|j| (id_of(j), kind_of(j))).collect();
        let trigger = pyish::text_or_empty(item.get("trigger"));
        let ok = board.lock().unwrap_or_else(|e| e.into_inner()).join(core, jobs, &deps, &kinds, &trigger);
        if ok {
            if let Some(a) = st.cmds.active.as_mut() {
                for (k, src) in [("joined_ids", "job_ids"), ("joined_names", "job_names")] {
                    let mut cur = a.get(k).and_then(Value::as_array).cloned().unwrap_or_default();
                    cur.extend(item.get(src).and_then(Value::as_array).cloned().unwrap_or_default());
                    a.insert(k.into(), json!(cur));
                }
            }
        }
        ok
    }

    /// absorb_waiting（待機キューの先頭から、手動の指令を走っている実行へ合流させる。追い越さない）。合流させた数。
    pub fn absorb_waiting(&self, core: &Core) -> usize {
        let Ok(cfg) = config::read(core) else { return 0 };
        let mut n = 0;
        loop {
            let mut st = self.lock();
            let Some(head) = st.cmds.queue.first().cloned() else { return n };
            if st.cmds.active.is_none() || !pyish::text_or_empty(head.get("trigger")).starts_with("manual") {
                return n;
            }
            if !self.join_live(core, &mut st, &cfg, &head) {
                return n;
            }
            st.cmds.queue.remove(0);
            n += 1;
            core.log(&format!("COMMAND_QUEUE_JOIN_WAITING id={} jobs={:?}", head["id"], head["job_names"]));
        }
    }

    /// POST /api/run/cancel（待機キューを空にし、走っていれば止める）。(走っていたか, 空にした数)。
    pub fn cancel(&self) -> (bool, usize) {
        let mut st = self.lock();
        let cleared = st.cmds.clear_queue();
        let running = st.status.get("running").is_some_and(pyish::truthy);
        if running {
            st.cancel = true;
        }
        (running, cleared)
    }

    /// command_dispatcher の1回ぶん（流している指令が無く、待機キューに指令があれば、先頭を最後まで流して締める）。流したら true。
    pub fn dispatch_one(&self, core: &Core, env: &Env) -> bool {
        let item = {
            let mut st = self.lock();
            if st.cmds.active.is_some() || st.cmds.queue.is_empty() {
                return false;
            }
            let item = st.cmds.queue.remove(0);
            st.cmds.active = Some(item.clone());
            item
        };
        core.log(&format!("COMMAND_QUEUE_START id={} jobs={:?}", item["id"], item["job_names"]));
        let err = match self.process(core, env, &item) {
            Ok(()) => String::new(),
            Err(e) => e,
        };
        let cfg = config::read(core).unwrap_or_default();
        let mut st = self.lock();
        let done = st.cmds.active.take().unwrap_or(item);
        let status = st.status.clone();
        let cancelled = status.get("step").and_then(Value::as_str) == Some("cancelled");
        st.cmds.after_command(&done, &status, &err, cancelled, &cfg, core.now());
        core.log(&format!("COMMAND_QUEUE_END id={} remaining={}", done["id"], st.cmds.queue.len()));
        true
    }

    /// 時刻が来た取り直しを、待機キューへ積む（スケジューラーの巡回が呼ぶ。scheduler の due_retries のところ）。
    pub fn enqueue_due_retries(&self, core: &Core) -> usize {
        let due = self.lock().cmds.due_retries(core.now());
        let n = due.len();
        for r in due {
            let ids: Vec<String> = r.job_ids.iter().map(pyish::py_str).collect();
            if let Err(e) = self.enqueue(core, &ids, "schedule:retry", Some(&r.lines), r.attempt) {
                core.log(&format!("RETRY_ENQUEUE_FAILED jobs={:?} error={e}", r.names));
            }
        }
        n
    }

    /// process（指令1つを最後まで流す）。中止は正常に戻る（status の step が cancelled）。失敗は Err(画面へ出す文)。
    fn process(&self, core: &Core, env: &Env, item: &Map<String, Value>) -> Result<(), String> {
        let started = Instant::now();
        self.lock().cancel = false;
        let ids: Vec<String> = item.get("job_ids").and_then(Value::as_array).into_iter().flatten().map(pyish::py_str).collect();
        let trigger = pyish::text_or_empty(item.get("trigger"));
        let Ok((cfg, runs)) = config::read_with(core, |_, c| schedule::job_runs(c)) else {
            return self.finish_error(core, started, "設定を読めませんでした".into());
        };
        let Some(b) = core.bases() else { return self.finish_error(core, started, "置き場が分かりません".into()) };
        let jobs: Vec<Map<String, Value>> = jobs_of(&cfg)
            .into_iter()
            .filter(|j| j.get("enabled").is_some_and(pyish::truthy) && (ids.is_empty() || ids.contains(&id_of(j))))
            .collect();
        if jobs.is_empty() {
            return self.finish_error(core, started, "実行対象がありません".into());
        }
        let deps = all_deps(core, &b, &cfg, &runs);
        let Ok(deps) = deps else {
            return self.finish_error(core, started, "材料の関係を決められません（Power Query の対象があります）".into());
        };
        let s = cfg.get("settings").and_then(Value::as_object).cloned().unwrap_or_default();
        let lines = commands::clamp_lines(item.get("parallel_lines"), &cfg, 1);
        let api_lines = (lines).min(commands::lines_cap(&cfg)).max(1);
        let cap = api_lines.max(commands::clamp_lines(s.get("api_parallel_lines"), &cfg, 1));
        // 状態の初め（process の2つの set_status）
        let first = &jobs[0];
        let fmt = naming::normalize_output_format(first.get("output_format"), first.get("output_file"));
        let file = naming::canonical_output_file(first.get("output_file"), fmt);
        let now = core.now();
        let mut v = Map::new();
        for (k, x) in [
            ("run_id", item.get("id").cloned().unwrap_or(json!(""))),
            ("execution_mode", json!("parallel")),
            ("requested_lines", json!(lines.min(jobs.len() as i64).max(1))),
            ("parallel_mode", json!(true)),
            ("parallel_lines", json!([])),
            ("queue_total", json!(0)),
            ("queue_waiting", json!(0)),
            ("queue_active", json!(0)),
            ("queue_completed", json!(0)),
            ("queue_completed_ids", json!([])),
            ("queue_failed_ids", json!([])),
            ("queue_running_ids", json!([])),
            ("queue_waiting_ids", json!(jobs.iter().map(id_of).collect::<Vec<_>>())),
            ("job_results", json!([])),
            ("parallel_max_lines", json!(lines.min(jobs.len() as i64).max(1))),
            ("parallel_speedup", json!(0)),
            ("batch_job_ids", json!(jobs.iter().map(id_of).collect::<Vec<_>>())),
            ("running", json!(true)),
            ("current", json!("準備中")),
            ("current_job_id", json!(id_of(first))),
            ("current_job_name", first.get("name").cloned().unwrap_or(json!(""))),
            ("current_index", json!(1)),
            ("total_jobs", json!(jobs.len())),
            ("completed_jobs", json!(0)),
            ("failed_jobs", json!(0)),
            ("output_format", json!(fmt)),
            ("output_file", json!(file)),
            ("output_target", json!(crate::paths::join(&joinplan::output_folder(&b, first, &cfg), &file))),
            ("started_at", json!(stamp(now))),
            ("elapsed_seconds", json!(0)),
            ("step", json!("prepare")),
            ("step_label", json!("設定を確認しています")),
            ("step_percent", json!(3)),
            ("last_result", json!("実行中")),
            ("error_detail", json!("")),
            ("job_errors", json!([])),
        ] {
            v.insert(k.into(), x);
        }
        self.set_status(v);
        // 流す順（材料を作る側を先に）と、接続情報（RNE があるときだけ）
        let order: Vec<String> = lane::order_jobs(&jobs.iter().map(id_of).collect::<Vec<_>>(), &deps).0;
        let by: HashMap<String, Map<String, Value>> = jobs.iter().map(|j| (id_of(j), j.clone())).collect();
        let ordered: Vec<Map<String, Value>> = order.iter().filter_map(|i| by.get(i).cloned()).collect();
        let kinds: HashMap<String, String> = ordered.iter().map(|j| (id_of(j), kind_of(j))).collect();
        let has_rne = kinds.values().any(|k| k == "rne");
        let login = match login_of(core, &cfg) {
            Ok(Some(l)) => Some(l),
            Ok(None) if has_rne => return self.finish_error(core, started, NO_LOGIN_MESSAGE.into()),
            Ok(None) => None,
            Err(e) if has_rne => return self.finish_error(core, started, e),
            Err(_) => None,
        };
        let cells: HashMap<String, i64> = runs
            .iter()
            .map(|(k, r)| {
                (pyish::py_str(k), r.get("rows").and_then(Value::as_i64).unwrap_or(0) * r.get("cols").and_then(Value::as_i64).unwrap_or(0))
            })
            .collect();
        let local_count = kinds.values().filter(|k| lane::LOCAL_KINDS.contains(&k.as_str())).count() as i64;
        let wait = joinplan::wait_settings_of(&cfg).unwrap_or(json!({"enabled": true, "max_wait": 600, "poll": 5, "lookahead": 60}));
        let limit = num(&s, "api_worker_timeout_minutes", 120.0);
        let settings = Settings {
            python: env.python.clone(),
            program_root: env.program_root.clone(),
            work: env.work.join("parallel_runtime").join(format!("run_{}", pyish::py_str(item.get("id").unwrap_or(&json!("x"))))),
            backup: PathBuf::from(b.resolve_path(cfg.get("backup_folder").map(pyish::py_str).as_deref(), None)),
            cfg: Value::Object(cfg.clone()),
            api_lines: api_lines as usize,
            local_lines: lane::local_lines(s.get("local_parallel_lines").unwrap_or(&Value::Null), api_lines, local_count).max(0) as usize,
            cap: cap as usize,
            trigger: trigger.clone(),
            worker_limit: (limit > 0.0).then(|| Duration::from_secs_f64(limit * 60.0)),
            stagger: Duration::from_millis(num(&s, "api_worker_stagger_ms", 700.0).max(0.0) as u64),
            login,
            wait_enabled: wait["enabled"].as_bool().unwrap_or(true),
            max_wait: Duration::from_secs(wait["max_wait"].as_u64().unwrap_or(600)),
            poll: Duration::from_secs(wait["poll"].as_u64().unwrap_or(5)),
        };
        let board = Arc::new(Mutex::new(Board::new(settings, ordered, &deps, &kinds, &cells)));
        self.lock().live = Some(board.clone());
        // 材料の待ち（別の実行・別の PC が作っている間。自分の実行の中の材料は黒板が見る）
        let lookahead = wait["lookahead"].as_i64().unwrap_or(60);
        let names: HashMap<String, String> = jobs_of(&cfg).iter().map(|j| (id_of(j), pyish::text_or_empty(j.get("name")))).collect();
        // 黒板を握っている間（tick の中）に状態の鍵を取らない（受け口は 状態 → 黒板 の順に取るので、逆にすると止まり合う）
        let running_now = std::cell::RefCell::new(BTreeSet::<String>::new());
        let waiter = |job: &Map<String, Value>| -> Vec<Value> {
            let me = id_of(job);
            let running: BTreeSet<String> = running_now.borrow().iter().filter(|x| **x != me).cloned().collect();
            let next_run_of = |id: &str| {
                let j = jobs_of(&cfg).into_iter().find(|j| id_of(j) == id)?;
                let p = schedule::job_schedule_preview(&Value::Object(j), core.now()).ok()?;
                NaiveDateTime::parse_from_str(p.get("next_run")?.as_str()?, "%Y-%m-%dT%H:%M").ok()
            };
            let inputs = joinplan::job_inputs(&b, &cfg, job);
            lane::wait_reasons(&me, &deps, &running, &BTreeSet::new(), next_run_of, &inputs, core.now(), lookahead, |i| {
                names.get(i).cloned().unwrap_or_else(|| i.to_string())
            })
        };
        loop {
            if std::mem::take(&mut self.lock().cancel) {
                board.lock().unwrap_or_else(|e| e.into_inner()).cancel();
            }
            *running_now.borrow_mut() =
                self.status().get("queue_running_ids").and_then(Value::as_array).into_iter().flatten().map(pyish::py_str).collect();
            let more = board.lock().unwrap_or_else(|e| e.into_inner()).tick(core, &waiter);
            let mut v = board.lock().unwrap_or_else(|e| e.into_inner()).status();
            v.insert("elapsed_seconds".into(), json!(started.elapsed().as_secs()));
            v.insert("heartbeat_at".into(), json!(stamp(core.now())));
            self.set_status(v);
            if !more {
                break;
            }
            self.absorb_waiting(core);
            std::thread::sleep(env.tick);
        }
        self.lock().live = None;
        let out = board.lock().unwrap_or_else(|e| e.into_inner()).outcome();
        self.finish(core, started, &out)
    }

    /// finish_batch と process の締め（正常終了・失敗・中断）。
    fn finish(&self, core: &Core, started: Instant, out: &Value) -> Result<(), String> {
        let results: Vec<String> = out["results"].as_array().into_iter().flatten().map(pyish::py_str).collect();
        let failures = out["failures"].as_array().cloned().unwrap_or_default();
        let total = out["total"].as_u64().unwrap_or(0);
        let now = core.now();
        let mut v = Map::new();
        let r = if out["cancelled"] == json!(true) {
            let msg = format!("中断されました: {}/{total}件完了後に中断されました", results.len());
            for (k, x) in [
                ("step", json!("cancelled")),
                ("step_label", json!("ユーザーの操作により中断しました")),
                ("step_percent", json!(100)),
                ("last_result", json!(msg)),
                ("error_detail", json!("")),
                ("queue_running_ids", json!([])),
            ] {
                v.insert(k.into(), x);
            }
            Ok(())
        } else if !failures.is_empty() {
            let lines: Vec<String> = failures
                .iter()
                .map(|f| format!("・{}: {}", pyish::text_or_empty(f.get("job")), pyish::text_or_empty(f.get("error"))))
                .collect();
            let msg = format!("{}件失敗しました\n{}", failures.len(), lines.join("\n"));
            for (k, x) in [
                (
                    "job_errors",
                    json!(failures
                        .iter()
                        .map(|f| json!({"job": f["job"], "error": pyish::text_or_empty(f.get("error"))}))
                        .collect::<Vec<_>>()),
                ),
                ("failed_jobs", json!(failures.len())),
                ("step", json!("error")),
                ("step_label", json!("処理を完了できませんでした")),
                ("step_percent", json!(100)),
                ("last_result", json!(format!("異常終了: {msg}"))),
                ("error_detail", json!(msg)),
            ] {
                v.insert(k.into(), x);
            }
            Err(msg)
        } else {
            let msg = if results.len() == 1 {
                format!("正常終了 | {}", results[0])
            } else {
                format!(
                    "正常終了 | 全件{}ファイル / {:.1}秒 | {}",
                    results.len(),
                    out["elapsed"].as_f64().unwrap_or(0.0),
                    results.join(" | ")
                )
            };
            for (k, x) in [
                ("step", json!("complete")),
                ("step_label", json!("すべての処理が完了しました")),
                ("step_percent", json!(100)),
                ("current", json!("すべての処理が完了しました")),
                ("last_result", json!(msg)),
            ] {
                v.insert(k.into(), x);
            }
            core.log(&msg);
            Ok(())
        };
        v.insert("last_finished_at".into(), json!(stamp(now)));
        v.insert("elapsed_seconds".into(), json!(started.elapsed().as_secs()));
        v.insert("running".into(), json!(false));
        v.insert("current".into(), json!(""));
        v.insert("current_job_id".into(), json!(""));
        self.set_status(v);
        r
    }

    /// 黒板に入る前の失敗（接続情報が無いなど）の締め。
    fn finish_error(&self, core: &Core, started: Instant, msg: String) -> Result<(), String> {
        let mut v = Map::new();
        for (k, x) in [
            ("step", json!("error")),
            ("step_label", json!("処理を完了できませんでした")),
            ("failed_jobs", json!(1)),
            ("step_percent", json!(100)),
            ("last_result", json!(format!("異常終了: {msg}"))),
            ("error_detail", json!(msg)),
            ("last_finished_at", json!(stamp(core.now()))),
            ("elapsed_seconds", json!(started.elapsed().as_secs())),
            ("running", json!(false)),
            ("current", json!("")),
            ("current_job_id", json!("")),
        ] {
            v.insert(k.into(), x);
        }
        let name = self.status().get("current_job_name").cloned().unwrap_or(json!("実行対象"));
        v.insert("job_errors".into(), json!([{"job": name, "error": msg}]));
        self.set_status(v);
        Err(msg)
    }
}
