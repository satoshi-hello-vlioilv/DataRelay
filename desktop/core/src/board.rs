//! 実行の黒板（2.38.0〜）。lib/navi_lanerun.py の LaneBoard・run_api_process_batch・_local_lane・run_lanes と同じ決まりで、
//! 1回の実行（何件かの対象）を最後まで回す。まだ使わない（実行の切り替えは 5e）。
//!
//! Python との違いは1つ: 手元の対象（テキスト・結合・クエリ）も、RNE と同じくワーカー（別プロセス）で流す（段 5c の local）。
//! そのため、スレッドを分けずに1本の輪（tick）で回せる。決まりはそのまま:
//!   - 何を・どの順で流すかは lane.rs（材料がそろった物から、RNE → テキスト・クエリ → 結合の順）
//!   - RNE は前回の 行×列 が大きい物から先に（全体の所要は一番重い対象で決まる）。起こすときは少しずつずらす
//!   - 材料が失敗した対象は走らせず、理由を付けて失敗にする。誰も動いていないのに材料がそろわない（輪）なら、先頭の1件の待ちを解く
//!   - 手元の対象は、別の実行・別の PC が材料を作っている間は待つ（待つ理由は呼ぶ側が渡す。待ちきれなければ走る）
//!   - 走っている間に入れた手動の実行は、同時に流す数（cap）まで合流させる
//!   - 実行の記録は親（黒板）だけが書く。画面の状態（parallel_lines・queue_* など）は Python と同じ鍵で作る
use crate::lane::{self, Entry};
use crate::runs::{self, JobRecord};
use crate::worker::{End, Spawn, Worker};
use crate::{pyish, routes::Core};
use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap};
use std::path::PathBuf;
use std::time::{Duration, Instant};

/// 黒板の決め事（1回の実行で変わらない物）。
pub struct Settings {
    pub python: PathBuf,
    pub program_root: PathBuf,
    /// 作業の置き場（ワーカーごとのフォルダーをこの下に作る）と、控えの置き場
    pub work: PathBuf,
    pub backup: PathBuf,
    pub cfg: Value,
    /// RNE のライン数・手元のライン数・同時に流す対象の上限（合流を含む）
    pub api_lines: usize,
    pub local_lines: usize,
    pub cap: usize,
    pub trigger: String,
    /// RNE のワーカーの時間切れ（None は無制限）と、起こすときのずらし
    pub worker_limit: Option<Duration>,
    pub stagger: Duration,
    /// Navigator の利用者とサーバー（RNE のワーカーへ渡す。パスワードはワーカーが自分で読む）。None なら RNE は失敗にする
    pub login: Option<(String, String)>,
    /// 材料を待つ設定（navi_order.wait_settings: 入・切、最大の秒、見直す間隔の秒）
    pub wait_enabled: bool,
    pub max_wait: Duration,
    pub poll: Duration,
}

/// 動いているワーカー1本。
struct Active {
    slot: usize,
    id: String,
    kind: String,
    worker: Worker,
}

/// 材料を待っている手元の対象（別の実行・別の PC が作っている間）。
struct Waiting {
    slot: usize,
    since: Instant,
    next_check: Instant,
    last: String,
}

/// 1回の実行の黒板。
pub struct Board {
    s: Settings,
    plan: Vec<Entry>,
    jobs: HashMap<String, Map<String, Value>>,
    done: Vec<String>,
    failed: Vec<String>,
    started: BTreeSet<String>,
    /// 実行中（入れた順）。id と名前
    running: Vec<(String, String)>,
    results: Vec<String>,
    failures: Vec<Value>,
    job_results: Vec<Value>,
    skipped: Vec<String>,
    lines: Vec<Map<String, Value>>,
    active: Vec<Active>,
    waiting: HashMap<String, Waiting>,
    /// RNE を流す順（重い物から）と、まだ起こしていない RNE
    rne_queue: Vec<String>,
    next_rne_at: Instant,
    rne_slots: BTreeSet<usize>,
    local_slots: BTreeSet<usize>,
    started_at: Instant,
    cancelled: bool,
    closed: bool,
    seq: usize,
}

fn id_of(j: &Map<String, Value>) -> String {
    j.get("id").map(pyish::py_str).unwrap_or_default()
}

fn name_of(j: &Map<String, Value>) -> String {
    j.get("name").map(pyish::py_str).unwrap_or_default()
}

fn round1(x: f64) -> f64 {
    format!("{x:.1}").parse().unwrap_or(x)
}

impl Board {
    /// jobs は流す順に並べた対象（order_jobs のあと）。deps は対象 id → 材料を作る対象 id。kinds は対象 id → 種類。
    /// cells は前回の 行×列（RNE を重い順に流すため。分からなければ入れない）。
    pub fn new(
        s: Settings,
        jobs: Vec<Map<String, Value>>,
        deps: &HashMap<String, BTreeSet<String>>,
        kinds: &HashMap<String, String>,
        cells: &HashMap<String, i64>,
    ) -> Board {
        let pairs: Vec<(String, String)> = jobs.iter().map(|j| (id_of(j), name_of(j))).collect();
        let plan = lane::build_plan(&pairs, deps, kinds);
        let mut rne: Vec<(usize, String)> = plan.iter().filter(|e| e.kind == "rne").map(|e| (e.order, e.id.clone())).collect();
        // 重い対象から先に（前回の実績が無い物は大きさが読めないので先に）。同じ重さは元の順
        rne.sort_by_key(|(n, id)| (std::cmp::Reverse(cells.get(id).copied().filter(|c| *c > 0).unwrap_or(i64::MAX)), *n));
        let api = if rne.is_empty() { 0 } else { s.api_lines.clamp(1, rne.len()) };
        let locals = plan.iter().filter(|e| lane::LOCAL_KINDS.contains(&e.kind.as_str())).count();
        let local = if locals == 0 { 0 } else { s.local_lines.clamp(1, locals) };
        let mut lines = Vec::new();
        for n in 1..=api {
            lines.push(line_card(n, "開始待ち"));
        }
        for n in 1..=local {
            lines.push(line_card(api + n, "手元のファイルから作ります"));
        }
        let now = Instant::now();
        Board {
            plan,
            jobs: jobs.into_iter().map(|j| (id_of(&j), j)).collect(),
            done: vec![],
            failed: vec![],
            started: BTreeSet::new(),
            running: vec![],
            results: vec![],
            failures: vec![],
            job_results: vec![],
            skipped: vec![],
            lines,
            active: vec![],
            waiting: HashMap::new(),
            rne_queue: rne.into_iter().map(|(_, id)| id).collect(),
            next_rne_at: now,
            rne_slots: (1..=api).collect(),
            local_slots: (api + 1..=api + local).collect(),
            started_at: now,
            cancelled: false,
            closed: false,
            seq: 0,
            s,
        }
    }

    fn settled(&self) -> BTreeSet<String> {
        self.done.iter().chain(self.failed.iter()).cloned().collect()
    }

    fn entry(&self, id: &str) -> Option<&Entry> {
        self.plan.iter().find(|e| e.id == id)
    }

    fn trigger_of(&self, id: &str) -> String {
        let t = self.jobs.get(id).and_then(|j| j.get("_trigger")).filter(|v| pyish::truthy(v)).map(pyish::py_str);
        t.unwrap_or_else(|| self.s.trigger.clone())
    }

    /// update_parallel_line（そのラインの札を置き換え、名前の順に並べる）。
    fn set_line(&mut self, line: &str, v: Map<String, Value>) {
        let mut card = Map::new();
        for (k, x) in [
            ("line", json!(line)),
            ("job", json!("")),
            ("state", json!("待機")),
            ("percent", json!(0)),
            ("elapsed", json!(0)),
            ("detail", json!("")),
        ] {
            card.insert(k.into(), x);
        }
        card.extend(v);
        // ラインの番号（slot）は札を置き換えても残す（ワーカーの言う様子には入っていない）
        let slot = self.lines.iter().find(|x| x.get("line") == Some(&json!(line))).and_then(|x| x.get("slot").cloned());
        if let (false, Some(n)) = (card.contains_key("slot"), slot) {
            card.insert("slot".into(), n);
        }
        self.lines.retain(|x| x.get("line") != Some(&json!(line)));
        self.lines.push(card);
        self.lines.sort_by(|a, b| pyish::py_str(&a["line"]).cmp(&pyish::py_str(&b["line"])));
    }

    fn record(&self, core: &Core, r: &JobRecord) {
        if runs::record_job_run(core, r).is_err() {
            core.log(&format!("JOB_RUN_RECORD_FAILED job={}", pyish::py_str(&r.job_name)));
        }
    }

    /// 1件を失敗として締める（_fail_locked。材料が失敗して走らせなかった物は skipped にも）。
    fn fail(&mut self, core: &Core, id: &str, why: &str, skipped: bool) {
        let name = self.entry(id).map(|e| e.name.clone()).unwrap_or_default();
        self.failed.push(id.into());
        self.running.retain(|(x, _)| x != id);
        self.failures.push(json!({"ok": false, "job": name, "error": why}));
        self.job_results.push(json!({"job": name, "job_id": id, "status": "failed", "detail": why}));
        if skipped {
            self.skipped.push(name);
        }
        if let Some(j) = self.jobs.get(id) {
            self.record(core, &JobRecord::note(j, "failed", &self.trigger_of(id), why));
        }
    }

    /// 材料が失敗したので、もう走れない手元の対象を、理由を付けて落とす（_drop_unreachable_locked）。
    fn drop_unreachable(&mut self, core: &Core) {
        let failed: BTreeSet<String> = self.failed.iter().cloned().collect();
        let done: BTreeSet<String> = self.done.iter().cloned().collect();
        let out: Vec<(String, BTreeSet<String>)> = lane::unreachable(&self.plan, &failed, &done)
            .into_iter()
            .filter(|e| !self.started.contains(&e.id))
            .map(|e| (e.id.clone(), e.needs.clone()))
            .collect();
        for (id, needs) in out {
            // 名指しするのは、実際に失敗した材料だけ（この輪の中で先に落とした物も含む）
            let failed: BTreeSet<String> = self.failed.iter().cloned().collect();
            let culprits = lane::names_of(&needs.intersection(&failed).cloned().collect(), &self.plan);
            let who = if culprits.is_empty() { "材料".to_string() } else { culprits.join("・") };
            self.started.insert(id.clone());
            self.waiting.remove(&id);
            self.fail(core, &id, &format!("材料の{who}が失敗したため実行しませんでした"), true);
        }
    }

    /// 1回ぶん進める。ワーカーの終わりを受け取り、空いたラインへ次を配る。まだ続くなら true。
    /// waiter は手元の対象が材料を待つ理由（別の実行・別の PC。空なら走ってよい）。
    pub fn tick(&mut self, core: &Core, waiter: &dyn Fn(&Map<String, Value>) -> Vec<Value>) -> bool {
        if self.closed {
            return false;
        }
        self.reap(core);
        if self.cancelled {
            self.stop_all(core);
            self.closed = true;
            return false;
        }
        self.drop_unreachable(core);
        self.start_rne(core);
        self.start_local(core, waiter);
        if self.active.is_empty() && self.waiting.is_empty() && self.rne_queue.is_empty() && self.unsettled_pending().is_empty() {
            self.closed = true;
            return false;
        }
        true
    }

    fn unsettled_pending(&self) -> Vec<&Entry> {
        let settled = self.settled();
        self.plan.iter().filter(|e| !settled.contains(&e.id) && !self.started.contains(&e.id)).collect()
    }

    /// 終わったワーカーを受け取って記録する（WORKER_END のあと・手元のラインの終わり）。
    fn reap(&mut self, core: &Core) {
        let mut i = 0;
        while i < self.active.len() {
            let limit = if self.active[i].kind == "rne" { self.s.worker_limit } else { None };
            let line = format!("ライン {}", self.active[i].slot);
            if let Some(st) = self.active[i].worker.status() {
                let elapsed = round1(self.active[i].worker.elapsed());
                let (pid, name, id) = (self.active[i].worker.pid(), self.active[i].worker.job_name.clone(), self.active[i].id.clone());
                // relay_worker_line（親が決めるのは所要時間と対象 id だけ。あとはワーカーの言うとおり）
                let mut relay: Map<String, Value> =
                    st.into_iter().filter(|(k, _)| !matches!(k.as_str(), "line" | "elapsed" | "updated_at" | "job_id")).collect();
                relay.entry("state").or_insert(json!("処理中"));
                relay.entry("percent").or_insert(json!(0));
                relay.entry("detail").or_insert(json!(""));
                if !relay.get("job").is_some_and(pyish::truthy) {
                    relay.insert("job".into(), json!(name));
                }
                relay.entry("pid").or_insert(json!(pid));
                relay.insert("job_id".into(), json!(id));
                relay.insert("elapsed".into(), json!(elapsed));
                self.set_line(&line, relay);
            }
            let Some(end) = self.active[i].worker.poll(limit) else {
                i += 1;
                continue;
            };
            let a = self.active.remove(i);
            self.finish(core, a, end);
        }
    }

    fn finish(&mut self, core: &Core, a: Active, end: End) {
        let line = format!("ライン {}", a.slot);
        let job = self.jobs.get(&a.id).cloned().unwrap_or_default();
        let ok = end.result.get("ok").is_some_and(pyish::truthy);
        let text = |k: &str| end.result.get(k).filter(|v| pyish::truthy(v)).map(pyish::py_str).unwrap_or_default();
        let detail = {
            let r = text("result");
            if r.is_empty() {
                text("error")
            } else {
                r
            }
        };
        let (one, rec) = if a.kind == "rne" {
            runs::from_rne_result(&job, &end.result, &self.s.trigger)
        } else {
            let one = end.result.get("job_result").cloned().unwrap_or_else(
                || json!({"job": name_of(&job), "job_id": a.id, "status": if ok { "ok" } else { "failed" }, "detail": detail}),
            );
            (one, runs::from_local_result(&job, &end.result, &self.s.trigger))
        };
        core.log(&format!(
            "WORKER_END line={line} pid={} job={} returncode={} ok={} elapsed={:.2}s",
            a.worker.pid(),
            name_of(&job),
            end.code.map_or_else(|| "None".to_string(), |c| c.to_string()),
            if ok { "True" } else { "False" },
            a.worker.elapsed()
        ));
        let mut card = Map::new();
        card.insert("job".into(), json!(name_of(&job)));
        card.insert("job_id".into(), json!(a.id));
        card.insert("state".into(), json!(if ok { "完了" } else { "失敗" }));
        card.insert("percent".into(), json!(100));
        card.insert("detail".into(), json!(detail));
        card.insert("elapsed".into(), json!(round1(a.worker.elapsed())));
        card.insert("slot".into(), json!(a.slot));
        self.set_line(&line, card);
        self.running.retain(|(x, _)| *x != a.id);
        if ok {
            self.done.push(a.id.clone());
            let said = text("result");
            if !said.is_empty() {
                self.results.push(said);
            }
        } else {
            self.failed.push(a.id.clone());
            self.failures.push(json!({"ok": false, "job": name_of(&job), "error": text("error")}));
        }
        self.job_results.push(one);
        self.record(core, &rec);
        if a.kind == "rne" {
            self.rne_slots.insert(a.slot);
        } else {
            self.local_slots.insert(a.slot);
        }
    }

    /// 空いた RNE のラインへ、次の RNE を起こす（少しずつずらす）。
    fn start_rne(&mut self, core: &Core) {
        while !self.rne_queue.is_empty()
            && !self.rne_slots.is_empty()
            && Instant::now() >= self.next_rne_at
            && self.live_count() < self.s.cap.max(1)
        {
            let id = self.rne_queue.remove(0);
            let slot = *self.rne_slots.iter().next().unwrap_or(&1);
            self.rne_slots.remove(&slot);
            let Some(job) = self.jobs.get(&id).cloned() else { continue };
            let Some((user, server)) = self.s.login.clone() else {
                self.started.insert(id.clone());
                self.fail(core, &id, "接続情報を読めませんでした", false);
                self.rne_slots.insert(slot);
                continue;
            };
            self.seq += 1;
            let index = self.seq;
            let dir = self.s.work.join(format!("line_{slot}_{index}"));
            let line = format!("ライン {slot}");
            let payload = json!({"job": job, "job_index": index, "total_jobs": self.plan.len(), "cfg": self.s.cfg, "user": user,
                                 "server": server, "dde_work": dir.join("work"), "backup": self.s.backup, "line": line});
            let _ = std::fs::create_dir_all(dir.join("work"));
            self.launch(core, slot, &id, "rne", index, &dir, &payload);
            self.next_rne_at = Instant::now() + self.s.stagger;
        }
    }

    /// 同時に流している対象の数（動いている・材料を待っている）。
    fn live_count(&self) -> usize {
        self.active.len() + self.waiting.len()
    }

    /// 空いた手元のラインへ、材料のそろった手元の対象を配る。別の実行・別の PC の材料を待つ物は、待ちきるまで札だけ出す。
    fn start_local(&mut self, core: &Core, waiter: &dyn Fn(&Map<String, Value>) -> Vec<Value>) {
        // 待っている物を見直す
        let ids: Vec<String> = self.waiting.keys().cloned().collect();
        for id in ids {
            let now = Instant::now();
            let w = &self.waiting[&id];
            if now < w.next_check {
                continue;
            }
            let (slot, since) = (w.slot, w.since);
            let job = self.jobs.get(&id).cloned().unwrap_or_default();
            let reasons = if self.s.wait_enabled { waiter(&job) } else { vec![] };
            let waited = since.elapsed();
            if reasons.is_empty() || waited >= self.s.max_wait {
                self.waiting.remove(&id);
                let held = round1(waited.as_secs_f64());
                if !reasons.is_empty() {
                    core.log(&format!(
                        "JOIN_WAIT_TIMEOUT job={} 待った時間={:.0}秒 まだ{}。これ以上は待たずに実行します（材料が1回ぶん古いかもしれません）",
                        name_of(&job),
                        waited.as_secs_f64(),
                        lane::reason_text(&reasons)
                    ));
                }
                self.launch_local(core, slot, &id, held);
            } else {
                let text = lane::reason_text(&reasons);
                let w = self.waiting.get_mut(&id).expect("待っている対象");
                w.next_check = now + self.s.poll;
                if w.last != text {
                    w.last = text.clone();
                    let mut card = Map::new();
                    card.insert("job".into(), json!(name_of(&job)));
                    card.insert("job_id".into(), json!(id));
                    card.insert("state".into(), json!("材料待ち"));
                    card.insert("percent".into(), json!(15));
                    card.insert("slot".into(), json!(slot));
                    card.insert("detail".into(), json!(text));
                    card.insert("elapsed".into(), json!(round1(waited.as_secs_f64())));
                    self.set_line(&format!("ライン {slot}"), card);
                }
            }
        }
        loop {
            if self.local_slots.is_empty() || self.live_count() >= self.s.cap.max(1) {
                return;
            }
            let done: BTreeSet<String> = self.done.iter().cloned().collect();
            let next = lane::ready(&self.plan, &done, &self.started, Some(&lane::LOCAL_KINDS)).first().map(|e| e.id.clone());
            let id = match next {
                Some(id) => id,
                None => {
                    // 誰も動いていないのに材料がそろわない（輪）。先頭の1件の待ちを解く（_break_cycle_locked）
                    let pending: Vec<&Entry> =
                        self.unsettled_pending().into_iter().filter(|e| lane::LOCAL_KINDS.contains(&e.kind.as_str())).collect();
                    let rne_open = !self.rne_queue.is_empty() || self.active.iter().any(|a| a.kind == "rne");
                    let inflight = self.started.difference(&self.settled()).count();
                    if pending.is_empty() || rne_open || inflight > 0 {
                        return;
                    }
                    let mut first: Vec<&Entry> = pending;
                    first.sort_by_key(|e| (e.tier, e.order));
                    let id = first[0].id.clone();
                    core.log(&format!(
                        "LANE_CYCLE job={} 材料={} の順番を決められないので、登録順のまま実行します",
                        first[0].name,
                        lane::blocking_names(first[0], &self.plan, &done).join("・")
                    ));
                    if let Some(e) = self.plan.iter_mut().find(|e| e.id == id) {
                        e.needs.clear();
                    }
                    continue;
                }
            };
            let slot = *self.local_slots.iter().next().expect("空いたライン");
            self.local_slots.remove(&slot);
            self.started.insert(id.clone());
            let name = self.entry(&id).map(|e| e.name.clone()).unwrap_or_default();
            self.running.push((id.clone(), name.clone()));
            let mut card = Map::new();
            card.insert("job".into(), json!(name));
            card.insert("job_id".into(), json!(id));
            card.insert("state".into(), json!("開始"));
            card.insert("percent".into(), json!(2));
            card.insert("slot".into(), json!(slot));
            card.insert("detail".into(), json!("手元のファイルから作ります"));
            card.insert("started_at".into(), json!(core.now().format("%Y-%m-%dT%H:%M:%S").to_string()));
            self.set_line(&format!("ライン {slot}"), card);
            let now = Instant::now();
            self.waiting.insert(id, Waiting { slot, since: now, next_check: now, last: String::new() });
        }
    }

    fn launch_local(&mut self, core: &Core, slot: usize, id: &str, held: f64) {
        let Some(job) = self.jobs.get(id).cloned() else { return };
        self.seq += 1;
        let index = self.seq;
        let dir = self.s.work.join(format!("local_{slot}_{index}"));
        let trig = self.trigger_of(id);
        let payload = json!({"local": {"trigger": trig, "slot": slot, "held": {"waited": held}}, "job": job, "cfg": self.s.cfg,
                             "job_index": index, "total_jobs": self.plan.len(), "work": self.s.work, "backup": self.s.backup});
        self.launch(core, slot, id, "local", index, &dir, &payload);
    }

    #[allow(clippy::too_many_arguments)]
    fn launch(&mut self, core: &Core, slot: usize, id: &str, kind: &str, index: usize, dir: &std::path::Path, payload: &Value) {
        let line = format!("ライン {slot}");
        let spawn = Spawn { python: &self.s.python, program_root: &self.s.program_root, dir, payload, line: &line };
        let name = self.entry(id).map(|e| e.name.clone()).unwrap_or_default();
        match Worker::spawn(&spawn) {
            Ok(worker) => {
                self.started.insert(id.into());
                if !self.running.iter().any(|(x, _)| x == id) {
                    self.running.push((id.into(), name.clone()));
                }
                if kind == "rne" {
                    let mut card = Map::new();
                    card.insert("job".into(), json!(name));
                    card.insert("job_id".into(), json!(id));
                    card.insert("state".into(), json!("起動"));
                    card.insert("percent".into(), json!(2));
                    card.insert("detail".into(), json!(format!("予約 {index}/{} / PID {}", self.plan.len(), worker.pid())));
                    card.insert("queue_index".into(), json!(index));
                    card.insert("slot".into(), json!(slot));
                    card.insert("started_at".into(), json!(core.now().format("%Y-%m-%dT%H:%M:%S").to_string()));
                    self.set_line(&line, card);
                }
                core.log(&format!("WORKER_START line={line} pid={} job={name} queue_index={index}/{}", worker.pid(), self.plan.len()));
                self.active.push(Active { slot, id: id.into(), kind: if kind == "rne" { "rne".into() } else { "local".into() }, worker });
            }
            Err(e) => {
                self.started.insert(id.into());
                self.fail(core, id, &format!("ワーカーを起こせませんでした: {e}"), false);
                if kind == "rne" {
                    self.rne_slots.insert(slot);
                } else {
                    self.local_slots.insert(slot);
                }
            }
        }
    }

    /// 中止（キャンセル）。次の tick で、動いているワーカーを子ごと止め、残りを中断として締める。
    pub fn cancel(&mut self) {
        self.cancelled = true;
    }

    fn stop_all(&mut self, core: &Core) {
        const WHY: &str = "ユーザーにより中断されました";
        for mut a in std::mem::take(&mut self.active) {
            a.worker.kill_tree(Duration::from_secs(5));
            let name = self.entry(&a.id).map(|e| e.name.clone()).unwrap_or_default();
            self.failures.push(json!({"ok": false, "job": name, "error": WHY, "elapsed": a.worker.elapsed()}));
            self.failed.push(a.id.clone());
            self.running.retain(|(x, _)| *x != a.id);
            if let Some(j) = self.jobs.get(&a.id) {
                self.record(core, &JobRecord::note(j, "cancelled", &self.trigger_of(&a.id), WHY));
            }
            let mut card = Map::new();
            card.insert("job".into(), json!(name));
            card.insert("job_id".into(), json!(a.id));
            card.insert("state".into(), json!("中断"));
            card.insert("percent".into(), json!(100));
            card.insert("detail".into(), json!(WHY));
            card.insert("elapsed".into(), json!(round1(a.worker.elapsed())));
            self.set_line(&format!("ライン {}", a.slot), card);
        }
        // まだ起こしていない RNE も中断として残す（待っている手元の対象は、まだ何もしていないので記録しない）
        for id in std::mem::take(&mut self.rne_queue) {
            if let Some(j) = self.jobs.get(&id) {
                self.record(core, &JobRecord::note(j, "cancelled", &self.trigger_of(&id), WHY));
            }
        }
        self.waiting.clear();
    }

    /// 走っている間に入れた対象を足す（join）。足せたら true。
    /// 足さないのは: 締めた・中止した、同じ対象がこの実行に入っている、足すと同時に流す数が cap を超える。
    /// deps は合わせた全体の材料の関係（引き直した物）。
    pub fn join(
        &mut self,
        core: &Core,
        jobs: Vec<Map<String, Value>>,
        deps: &HashMap<String, BTreeSet<String>>,
        kinds: &HashMap<String, String>,
        trigger: &str,
    ) -> bool {
        if self.closed || self.cancelled {
            return false;
        }
        if jobs.iter().any(|j| self.jobs.contains_key(&id_of(j))) {
            return false;
        }
        let settled = self.settled();
        let live = self.plan.iter().filter(|e| !settled.contains(&e.id)).count();
        if live + jobs.len() > self.s.cap.max(1) {
            return false;
        }
        let mut all: Vec<(String, String)> = self.plan.iter().map(|e| (e.id.clone(), e.name.clone())).collect();
        all.extend(jobs.iter().map(|j| (id_of(j), name_of(j))));
        let mut kinds_all: HashMap<String, String> = self.plan.iter().map(|e| (e.id.clone(), e.kind.clone())).collect();
        kinds_all.extend(kinds.iter().map(|(k, v)| (k.clone(), v.clone())));
        let combined = lane::build_plan(&all, deps, &kinds_all);
        let new: Vec<Entry> = combined[self.plan.len()..].to_vec();
        for mut j in jobs {
            // 合流した対象は分割しない。記録は、その実行の入れ方（手動）で残す
            j.insert("_trigger".into(), json!(trigger));
            j.insert("_split_budget".into(), json!(1));
            self.jobs.insert(id_of(&j), j);
        }
        // 合流ぶんは、空いているラインで足りなければ、足りないぶんだけラインを足して起こす（同時に流す数は cap が抑える）
        let new_rne = new.iter().filter(|e| e.kind == "rne").count();
        let new_local = new.len() - new_rne;
        self.rne_queue.extend(new.iter().filter(|e| e.kind == "rne").map(|e| e.id.clone()));
        for (count, rne) in
            [(new_rne.saturating_sub(self.rne_slots.len()), true), (new_local.saturating_sub(self.local_slots.len()), false)]
        {
            for _ in 0..count {
                let n = self.next_slot();
                self.lines.push(line_card(n, if rne { "開始待ち" } else { "手元のファイルから作ります" }));
                if rne {
                    self.rne_slots.insert(n);
                } else {
                    self.local_slots.insert(n);
                }
            }
        }
        // 手元の対象どうしの材料の関係は、合わせた全体で引き直す
        for e in &mut self.plan {
            if let Some(c) = combined.iter().find(|x| x.id == e.id) {
                if !self.started.contains(&e.id) {
                    e.needs = c.needs.clone();
                    e.tier = c.tier;
                }
            }
        }
        core.log(&format!(
            "LANE_JOIN jobs={:?} trigger={trigger} 実行中の対象={}/{}",
            new.iter().map(|e| e.name.as_str()).collect::<Vec<_>>(),
            live + new.len(),
            self.s.cap
        ));
        self.plan.extend(new);
        true
    }

    fn next_slot(&self) -> usize {
        self.lines.iter().filter_map(|x| x.get("slot").and_then(Value::as_u64)).max().unwrap_or(0) as usize + 1
    }

    /// 画面の状態（LaneBoard._publish_locked と同じ鍵）と、ラインの札（parallel_lines）。
    pub fn status(&self) -> Map<String, Value> {
        let uniq = |v: &[String]| -> Vec<String> {
            let mut seen = BTreeSet::new();
            v.iter().filter(|x| seen.insert((*x).clone())).cloned().collect()
        };
        let (done, failed) = (uniq(&self.done), uniq(&self.failed));
        let settled: BTreeSet<&String> = done.iter().chain(failed.iter()).collect();
        let running: Vec<String> = self.running.iter().map(|(i, _)| i.clone()).collect();
        let waiting: Vec<String> =
            self.plan.iter().filter(|e| !settled.contains(&e.id) && !running.contains(&e.id)).map(|e| e.id.clone()).collect();
        let total = self.plan.len();
        let names: Vec<&str> = self.running.iter().take(3).map(|(_, n)| n.as_str()).collect();
        let api_lines = self.lines.len();
        let mut v = Map::new();
        for (k, x) in [
            ("queue_total", json!(total)),
            ("queue_waiting", json!(waiting.len())),
            ("queue_active", json!(running.len())),
            ("queue_completed", json!(settled.len())),
            ("queue_completed_ids", json!(done)),
            ("queue_failed_ids", json!(failed)),
            ("queue_running_ids", json!(running)),
            ("queue_waiting_ids", json!(waiting)),
            ("completed_jobs", json!(settled.len())),
            ("failed_jobs", json!(failed.len())),
            ("current_index", json!((settled.len() + running.len()).min(total).max(1))),
            ("job_results", json!(self.job_results)),
            (
                "job_errors",
                json!(self.failures.iter().map(|x| json!({"job": x["job"], "error": pyish::py_str(&x["error"])})).collect::<Vec<_>>()),
            ),
            ("step", json!("save")),
            ("step_percent", json!(((100 * settled.len()) as f64 / total.max(1) as f64).round_ties_even() as i64)),
            ("step_label", json!(format!("実行 {}・待機 {}・完了 {}／{total}", running.len(), waiting.len(), settled.len()))),
            ("current_job_name", json!(if names.is_empty() { "順番待ち".to_string() } else { names.join("・") })),
            ("activity_detail", json!(format!("{api_lines}ラインで処理"))),
            ("activity_value", json!(format!("実行 {} / 待機 {} / 完了 {}/{total}", running.len(), waiting.len(), settled.len()))),
            ("parallel_lines", json!(self.lines)),
            ("parallel_max_lines", json!(api_lines)),
            ("parallel_mode", json!(true)),
        ] {
            v.insert(k.into(), x);
        }
        v
    }

    /// 実行の締め（run_lanes の答え）: 結果の文・失敗・走らせなかった物・件数・所要の秒。
    pub fn outcome(&self) -> Value {
        json!({"results": self.results, "failures": self.failures, "skipped": self.skipped, "total": self.plan.len(),
               "elapsed": self.started_at.elapsed().as_secs_f64(), "cancelled": self.cancelled})
    }
}

/// 開始前のラインの札。
fn line_card(slot: usize, detail: &str) -> Map<String, Value> {
    let mut m = Map::new();
    for (k, v) in [
        ("line", json!(format!("ライン {slot}"))),
        ("job", json!("")),
        ("state", json!("待機")),
        ("percent", json!(0)),
        ("elapsed", json!(0)),
        ("detail", json!(detail)),
        ("slot", json!(slot)),
    ] {
        m.insert(k.into(), v);
    }
    m
}
