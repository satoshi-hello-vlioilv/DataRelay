//! 実行の指令の待機キュー・知らせ・取り直し（2.40.0〜）。app.py の enqueue_command・queue_snapshot・
//! execution-queue の受け口・add_alert・schedule_retry・due_retries・retry_view・after_command と同じ決まり。
//! まだ使わない（受け口とスケジューラーを Rust へ移して実行を切り替えるのは 5e-2）。
//!
//! どれも実行役（黒板）の外側にある、指令1つ単位の決まり:
//!   - 待機キュー … 実行の指令（対象・入れ方・並列ライン数・取り直しの回数）を積み、1つずつ流す。いま流している指令は active
//!   - 知らせ … 画面の常設バッジと OS の通知が読む。直近 50 件だけ残す
//!   - 取り直し … 自動実行で失敗した対象だけを、少し待ってから流し直す予約（手動は人が見ているので取り直さない）
//!
//! 時刻は呼ぶ側が渡す（試験で決めた時刻にできるように）。id は uuid4 の16進。
use crate::config::Pass;
use crate::pyish;
use chrono::NaiveDateTime;
use serde_json::{json, Map, Value};

/// 並列ライン数の上限の既定（PARALLEL_LINES_SUPPORTED_MAX）。
pub const LINES_MAX_DEFAULT: i64 = 24;
/// 残す知らせの数。
const ALERTS_KEEP: usize = 50;

/// int(x)（字・数・真偽。読めなければ None ＝ Python は例外）。
fn py_int(v: &Value) -> Option<i64> {
    pyish::int_opt(v).ok().flatten()
}

fn settings(cfg: &Map<String, Value>) -> Map<String, Value> {
    cfg.get("settings").and_then(Value::as_object).cloned().unwrap_or_default()
}

/// parallel_lines_cap（並列ライン数の上限。設定の api_parallel_max_lines を1つの基準にする）。
pub fn lines_cap(cfg: &Map<String, Value>) -> i64 {
    let s = settings(cfg);
    let v = s.get("api_parallel_max_lines").filter(|v| pyish::truthy(v)).cloned().unwrap_or(json!(LINES_MAX_DEFAULT));
    py_int(&v).unwrap_or(LINES_MAX_DEFAULT).max(1)
}

/// clamp_parallel_lines（1 〜 上限。読めなければ default）。
pub fn clamp_lines(value: Option<&Value>, cfg: &Map<String, Value>, default: i64) -> i64 {
    let n = match value {
        None | Some(Value::Null) => default,
        Some(v) => py_int(v).unwrap_or(default),
    };
    n.min(lines_cap(cfg)).max(1)
}

fn stamp(now: NaiveDateTime) -> String {
    now.format("%Y-%m-%dT%H:%M:%S").to_string()
}

fn new_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}

fn strs(v: Option<&Value>) -> Vec<Value> {
    v.and_then(Value::as_array).cloned().unwrap_or_default()
}

/// 取り直しの予約1件。
#[derive(Debug, Clone)]
pub struct Retry {
    pub due_at: NaiveDateTime,
    pub job_ids: Vec<Value>,
    pub names: Vec<Value>,
    pub lines: Value,
    pub attempt: i64,
}

/// 待機キュー・知らせ・取り直しの持ち物。
#[derive(Default)]
pub struct Commands {
    pub queue: Vec<Map<String, Value>>,
    pub active: Option<Map<String, Value>>,
    pub alerts: Vec<Map<String, Value>>,
    pub retries: Vec<Retry>,
}

impl Commands {
    /// enqueue_command の前半（指令を作る）。有効な対象のうち、job_ids に入っている物（空なら全部）。無ければ断る。
    pub fn new_item(
        cfg: &Map<String, Value>,
        job_ids: &[String],
        trigger: &str,
        lines: Option<&Value>,
        attempt: i64,
        now: NaiveDateTime,
    ) -> Result<Map<String, Value>, String> {
        let selected: Vec<&Map<String, Value>> = cfg
            .get("jobs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_object)
            .filter(|j| j.get("enabled").is_some_and(pyish::truthy))
            .filter(|j| job_ids.is_empty() || job_ids.iter().any(|i| j.get("id").and_then(Value::as_str) == Some(i.as_str())))
            .collect();
        if selected.is_empty() {
            return Err("実行対象がありません".into());
        }
        let field = |k: &str| selected.iter().map(|j| j.get(k).cloned().unwrap_or(Value::Null)).collect::<Vec<_>>();
        let mut item = Map::new();
        item.insert("id".into(), json!(new_id()));
        item.insert("job_ids".into(), json!(field("id")));
        item.insert("job_names".into(), json!(field("name")));
        item.insert("trigger".into(), json!(trigger));
        item.insert("parallel_lines".into(), json!(clamp_lines(lines, cfg, 1)));
        item.insert("attempt".into(), json!(attempt));
        item.insert("enqueued_at".into(), json!(stamp(now)));
        item.insert("count".into(), json!(selected.len()));
        Ok(item)
    }

    /// enqueue_command の後半（待機キューの後ろへ積む）。返すのは順番（流している指令があれば、その次から数える）。
    pub fn enqueue(&mut self, item: Map<String, Value>) -> usize {
        self.queue.push(item);
        self.queue.len() + usize::from(self.active.is_some())
    }

    /// queue_snapshot（流している指令を先頭に、合流した対象もその行に並べる）。
    pub fn snapshot(&self) -> Value {
        let mut items = Vec::new();
        if let Some(a) = &self.active {
            let mut x = a.clone();
            x.insert("state".into(), json!("running"));
            x.insert("position".into(), json!(0));
            let mut names = strs(x.get("job_names"));
            names.extend(strs(x.get("joined_names")));
            let mut ids = strs(x.get("job_ids"));
            ids.extend(strs(x.get("joined_ids")));
            x.insert("job_names".into(), json!(names));
            x.insert("count".into(), json!(ids.len()));
            x.insert("job_ids".into(), json!(ids));
            items.push(Value::Object(x));
        }
        for (i, item) in self.queue.iter().enumerate() {
            let mut x = item.clone();
            x.insert("state".into(), json!("waiting"));
            x.insert("position".into(), json!(i + 1));
            items.push(Value::Object(x));
        }
        let total = items.len();
        json!({"items": items, "active_id": self.active.as_ref().and_then(|a| a.get("id").cloned()),
               "waiting_count": self.queue.len(), "total_count": total})
    }

    /// DELETE /api/execution-queue/<id>（待っている指令だけ消せる）。消した指令。
    pub fn delete(&mut self, id: &str) -> Option<Map<String, Value>> {
        let i = self.queue.iter().position(|x| x.get("id").and_then(Value::as_str) == Some(id))?;
        Some(self.queue.remove(i))
    }

    /// POST /api/execution-queue/<id>/move（up なら1つ前へ、それ以外は1つ後ろへ。端なら何もしない）。待機キューに無ければ None。
    pub fn move_item(&mut self, id: &str, direction: &Value) -> Option<()> {
        let i = self.queue.iter().position(|x| x.get("id").and_then(Value::as_str) == Some(id))?;
        let dest = if direction.as_str() == Some("up") { i as i64 - 1 } else { i as i64 + 1 };
        if dest >= 0 && (dest as usize) < self.queue.len() {
            self.queue.swap(i, dest as usize);
        }
        Some(())
    }

    /// 中止のときに待機キューを空にする。消した数。
    pub fn clear_queue(&mut self) -> usize {
        std::mem::take(&mut self.queue).len()
    }

    /// add_alert（知らせを1件積む。直近 50 件だけ残す）。
    pub fn add_alert(&mut self, kind: &str, title: &str, detail: &str, jobs: &[Value], now: NaiveDateTime) -> Map<String, Value> {
        let mut item = Map::new();
        item.insert("id".into(), json!(new_id()));
        item.insert("kind".into(), json!(kind));
        item.insert("title".into(), json!(title));
        item.insert("detail".into(), json!(detail.chars().take(400).collect::<String>()));
        item.insert("jobs".into(), json!(jobs));
        item.insert("at".into(), json!(stamp(now)));
        self.alerts.push(item.clone());
        if self.alerts.len() > ALERTS_KEEP {
            self.alerts.drain(..self.alerts.len() - ALERTS_KEEP);
        }
        item
    }

    /// GET /api/alerts（未確認の知らせ・いちばん重い種類・待っている取り直し）。
    pub fn alerts_view(&self) -> Value {
        let has = |k: &str| self.alerts.iter().any(|x| x.get("kind").and_then(Value::as_str) == Some(k));
        let worst = if has("error") {
            "error"
        } else if has("warn") {
            "warn"
        } else if !self.alerts.is_empty() {
            "info"
        } else {
            ""
        };
        json!({"ok": true, "alerts": self.alerts, "count": self.alerts.len(), "worst": worst, "retries": self.retry_view()})
    }

    /// POST /api/alerts/ack（指定した id を消す。指定が無ければ全部）。(消した数, 残りの数)。
    pub fn ack(&mut self, ids: &[Value]) -> (usize, usize) {
        let before = self.alerts.len();
        if ids.is_empty() {
            self.alerts.clear();
        } else {
            self.alerts.retain(|x| !x.get("id").is_some_and(|i| ids.contains(i)));
        }
        (before - self.alerts.len(), self.alerts.len())
    }

    /// schedule_retry（少し待ってから、失敗した対象だけを取り直す予約）。回数を使い切ったら知らせだけ出す。予約した時刻。
    /// 設定の数が読めないとき（Python は例外で取り直さない）は Err。
    pub fn schedule_retry(
        &mut self,
        job_ids: &[Value],
        names: &[Value],
        lines: &Value,
        attempt: i64,
        cfg: &Map<String, Value>,
        now: NaiveDateTime,
    ) -> Result<Option<NaiveDateTime>, Pass> {
        let s = settings(cfg);
        if !s.get("retry_enabled").map(pyish::truthy).unwrap_or(true) {
            return Ok(None);
        }
        let num = |k: &str, default: i64, zero: i64| -> Result<i64, Pass> {
            match s.get(k).cloned().unwrap_or(json!(default)) {
                v if !pyish::truthy(&v) => Ok(zero),
                v => py_int(&v).ok_or(Pass),
            }
        };
        let limit = num("retry_max", 1, 0)?.clamp(0, 5);
        let names5 = names.iter().take(5).map(pyish::py_str).collect::<Vec<_>>().join("・");
        if attempt > limit {
            let detail = format!("{}件が{limit}回の取り直しでも成功しませんでした: {names5}", job_ids.len());
            self.add_alert("error", "取り直しても失敗しました", &detail, names, now);
            return Ok(None);
        }
        let wait = num("retry_delay_minutes", 5, 5)?.clamp(1, 180);
        let due = now + chrono::Duration::minutes(wait);
        self.retries.push(Retry { due_at: due, job_ids: job_ids.to_vec(), names: names.to_vec(), lines: lines.clone(), attempt });
        let detail = format!("{}件が失敗しました（{attempt}回目の取り直し / 最大{limit}回）: {names5}", job_ids.len());
        self.add_alert("warn", &format!("{wait}分後に取り直します"), &detail, names, now);
        Ok(Some(due))
    }

    /// due_retries（時刻が来た取り直しを取り出す）。
    pub fn due_retries(&mut self, now: NaiveDateTime) -> Vec<Retry> {
        let (due, keep): (Vec<Retry>, Vec<Retry>) = std::mem::take(&mut self.retries).into_iter().partition(|r| r.due_at <= now);
        self.retries = keep;
        due
    }

    /// retry_view（画面へ出す、待っている取り直し）。
    pub fn retry_view(&self) -> Vec<Value> {
        self.retries.iter().map(|r| json!({"jobs": r.names, "attempt": r.attempt, "due_at": stamp(r.due_at)})).collect()
    }

    /// POST /api/retries/cancel。取り消した数。
    pub fn cancel_retries(&mut self) -> usize {
        std::mem::take(&mut self.retries).len()
    }

    /// after_command（1つの実行が終わったところ）。共有先へ反映できなかった対象と失敗を知らせ、自動実行の失敗だけ取り直しを予約する。
    /// status はその実行の締めの状態（job_results・queue_failed_ids・job_errors・error_detail・last_result）。
    pub fn after_command(
        &mut self,
        item: &Map<String, Value>,
        status: &Map<String, Value>,
        error: &str,
        cancelled: bool,
        cfg: &Map<String, Value>,
        now: NaiveDateTime,
    ) {
        // 保留は失敗ではないので、成功した実行でも必ず見る
        let held: Vec<Map<String, Value>> = strs(status.get("job_results"))
            .into_iter()
            .filter_map(|x| x.as_object().cloned())
            .filter(|x| x.get("status").and_then(Value::as_str) == Some("ok") && x.get("published") == Some(&json!(false)))
            .collect();
        if !held.is_empty() {
            let names: Vec<Value> = held.iter().map(|x| json!(pyish::text_or_empty(x.get("job")))).collect();
            let five = names.iter().take(5).map(pyish::py_str).collect::<Vec<_>>().join("・");
            let detail = format!("{five}（公開先が使用中でした。新しいデータは横に控えてあり、次の実行で自動的に反映します）");
            self.add_alert("warn", &format!("{}件が共有先へ反映できていません", held.len()), &detail, &names, now);
        }
        if cancelled {
            // 中止は人が選んだこと。失敗として知らせない（自動実行なら勝手にもう一度走らせることにもなる）
            return;
        }
        // failed_jobs_of_run
        let mut ids: Vec<Value> = strs(status.get("queue_failed_ids")).into_iter().filter(pyish::truthy).collect();
        let errs: Vec<Map<String, Value>> = strs(status.get("job_errors")).into_iter().filter_map(|x| x.as_object().cloned()).collect();
        let mut names: Vec<Value> =
            errs.iter().filter(|x| x.get("job").is_some_and(pyish::truthy)).map(|x| json!(pyish::py_str(&x["job"]))).collect();
        let why = errs
            .iter()
            .filter(|x| x.get("error").is_some_and(pyish::truthy))
            .map(|x| {
                let e: String = pyish::text_or_empty(x.get("error")).chars().take(120).collect();
                format!("{}: {e}", x.get("job").map(pyish::py_str).unwrap_or_else(|| "None".into()))
            })
            .collect::<Vec<_>>()
            .join(" / ");
        let item_names = strs(item.get("job_names"));
        if ids.is_empty() && error.is_empty() {
            if py_int(item.get("attempt").unwrap_or(&json!(0))).unwrap_or(0) > 0 {
                let detail: String = item_names.iter().map(pyish::py_str).collect::<Vec<_>>().join("・").chars().take(200).collect();
                self.add_alert("info", "取り直しで成功しました", &detail, &item_names, now);
            }
            return;
        }
        if names.is_empty() {
            names = item_names;
        }
        if ids.is_empty() {
            ids = strs(item.get("job_ids"));
        }
        let detail = [why.as_str(), error]
            .into_iter()
            .find(|x| !x.is_empty())
            .map(String::from)
            .or_else(|| status.get("error_detail").filter(|v| pyish::truthy(v)).map(pyish::py_str))
            .or_else(|| status.get("last_result").filter(|v| pyish::truthy(v)).map(pyish::py_str))
            .unwrap_or_default();
        let five = names.iter().take(5).map(pyish::py_str).collect::<Vec<_>>().join("・");
        let text = if detail.is_empty() { five } else { format!("{five} / {detail}") };
        self.add_alert("error", &format!("{}件の実行が失敗しました", ids.len()), &text, &names, now);
        // 取り直すのは自動実行だけ。自動実行に手動で合流した対象も外す
        if pyish::text_or_empty(item.get("trigger")).starts_with("schedule") {
            let joined = strs(item.get("joined_ids"));
            let (ids2, names2): (Vec<Value>, Vec<Value>) = if ids.len() == names.len() {
                let keep: Vec<(Value, Value)> =
                    ids.iter().cloned().zip(names.iter().cloned()).filter(|(i, _)| !joined.contains(i)).collect();
                let ns: Vec<Value> = keep.iter().map(|(_, n)| n.clone()).filter(pyish::truthy).collect();
                (keep.into_iter().map(|(i, _)| i).collect(), ns)
            } else {
                (ids.iter().filter(|i| !joined.contains(i)).cloned().collect(), vec![])
            };
            let names2 = if names2.is_empty() { names } else { names2 };
            if !ids2.is_empty() {
                let lines = item.get("parallel_lines").filter(|v| pyish::truthy(v)).cloned().unwrap_or(json!(1));
                let attempt = py_int(item.get("attempt").unwrap_or(&json!(0))).unwrap_or(0) + 1;
                let _ = self.schedule_retry(&ids2, &names2, &lines, attempt, cfg, now);
            }
        }
    }
}
