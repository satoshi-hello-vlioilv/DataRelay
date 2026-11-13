//! Rust が答えるルートの表。ここに無い問い合わせは、窓が Python へ回す。
//!
//! 1本移すたびに、ここへ足し、migration/route_plan.json を "core" にし、tests/parity/cases.json に突き合わせる場合を足す
//! （tests/test_route_plan.py と tests/test_rust_parity.py が、どれかを忘れると止める）。

use crate::http::{Ask, Reply};
use crate::paths::{self, Bases};
use crate::{applog, config, diag, edits, joinplan, joinrun, login, masters, period, places, schedule, textread, version, viewer, writer};
use chrono::{Datelike, Local, NaiveDateTime};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

type Handler = fn(&Core, &Ask, &[String]) -> Reply;

/// (メソッド, 道筋の型, 答える係)。型の `<名前>` は1段ぶんの値に当たる（Flask の書き方と同じ）。
pub const ROUTES: &[(&str, &str, Handler)] = &[
    ("GET", "/api/version", get_version),
    ("POST", "/api/period-preview", post_period_preview),
    ("GET", "/api/docs", version::get_docs),
    ("GET", "/api/docs/<doc_id>", version::get_doc),
    ("POST", "/api/path-convert", places::post_path_convert),
    ("GET", "/api/users-root", places::get_users_root),
    ("GET", "/api/login", login::get_login),
    ("POST", "/api/login", login::post_login),
    ("POST", "/api/login/import", login::post_import),
    ("POST", "/api/login/delete", login::post_delete),
    ("POST", "/api/login/decline", login::post_decline),
    ("GET", "/api/log", applog::get_log),
    ("GET", "/api/config", config::get_config),
    ("PUT", "/api/config", writer::put_config),
    ("GET", "/api/text-layouts", masters::get_text_layouts),
    ("GET", "/api/text-layouts/export", masters::get_text_layouts_export),
    ("GET", "/api/join-recipes", masters::get_join_recipes),
    ("GET", "/api/join-recipes/export", masters::get_join_recipes_export),
    ("GET", "/api/m-queries/export", masters::get_m_queries_export),
    ("GET", "/api/schedule-preview", schedule::get_schedule_preview),
    ("GET", "/api/calendar", schedule::get_calendar),
    ("GET", "/api/job-trend/<job_id>", schedule::get_job_trend),
    ("POST", "/api/settings/columns", edits::post_columns),
    ("POST", "/api/schedule/quick-add", edits::post_quick_add),
    ("POST", "/api/schedule-pause", edits::post_schedule_pause),
    ("POST", "/api/text-layouts", masters::post_text_layout),
    ("POST", "/api/text-layouts/import", masters::post_text_layouts_import),
    ("DELETE", "/api/text-layouts/<layout_id>", masters::delete_text_layout),
    ("POST", "/api/join-recipes", masters::post_join_recipe),
    ("POST", "/api/join-recipes/import", masters::post_join_recipes_import),
    ("DELETE", "/api/join-recipes/<recipe_id>", masters::delete_join_recipe),
    ("DELETE", "/api/m-queries/<query_id>", masters::delete_m_query),
    ("POST", "/api/run-history/delete", edits::post_run_history_delete),
    ("POST", "/api/preview-filename", config::post_preview_filename),
    ("POST", "/api/text-preview", textread::post_preview),
    ("POST", "/api/text-sniff", textread::post_sniff),
    ("GET", "/api/join-candidates", joinplan::get_candidates),
    ("POST", "/api/join-order", joinplan::post_order),
    ("POST", "/api/join-cache/clear", joinplan::post_cache_clear),
    ("POST", "/api/join-source", joinplan::post_source),
    ("GET", "/api/freshness", diag::get_freshness),
    ("GET", "/api/machine-paths", diag::get_machine_paths),
    ("POST", "/api/path-check", diag::post_path_check),
    ("POST", "/api/apply-path-suggestion", diag::post_apply_path_suggestion),
    ("POST", "/api/join-keys", joinrun::post_keys),
    ("POST", "/api/join-preview", joinrun::post_preview),
    // jobs を先に（Flask は決まった道を <job_id> より先に当てる。こちらは上から順に当てる）
    ("GET", "/api/data-viewer/jobs", viewer::get_jobs),
    ("POST", "/api/data-viewer/export-pivot", viewer::post_export_pivot),
    ("GET", "/api/data-viewer/<job_id>", viewer::get_viewer),
];

/// 中身（Rust の側）。アプリの場所から、置き場・データの基準を Python と同じ決まりで知る。
#[derive(Default)]
pub struct Core {
    /// いまの日時を決め打ちにする（試験用）。None なら PC の時刻
    pub fixed_now: Option<NaiveDateTime>,
    /// アプリの場所（Python の BASE。app.py のあるフォルダー）。None なら場所を使うルートは答えない（Python へ回す）
    program_root: Option<PathBuf>,
    /// データの基準と出どころ。Python と同じく、はじめて要ったとき（中身の起動のあと）に1度だけ決める
    data: OnceLock<(String, String)>,
    /// 設定のマスターの版の控え（道・更新時刻・大きさが同じなら読み直さない。マスターは共有の置き場にあり、開くのが遅いため）
    master_seen: Mutex<Option<(PathBuf, std::time::SystemTime, u64, i64)>>,
    /// 設定の保存のあとの、裏の書き戻し（終わるときに settle_writes で待つ）
    pub(crate) writes: writer::Writes,
}

impl Core {
    pub fn new() -> Self {
        Self::default()
    }

    /// アプリの場所を知っている中身。
    pub fn with_program(program_root: &Path) -> Self {
        Core { program_root: Some(PathBuf::from(paths::resolve(&program_root.to_string_lossy()))), ..Self::default() }
    }

    /// 記録へ1行（このPCの app.log。Python が残していた行と同じ字・同じ形。画面の「ログ」に出る）。
    pub(crate) fn log(&self, line: &str) {
        applog::write(&paths::local_root(), "INFO", line);
    }

    pub fn program_root(&self) -> Option<&Path> {
        self.program_root.as_deref()
    }

    /// 基準になる場所（navi_paths の DATA_ROOT・LOCAL_ROOT・PROGRAM_ROOT・DATA_SOURCE・PLACE_ROOT）。
    /// 置き場は毎回、控え（config\update.json）から読む（Python は置き場を変えると控えを書き直してから決め直す）。
    pub fn bases(&self) -> Option<Bases> {
        let prog = self.program_root.as_deref()?;
        let (place, _) = paths::update_dir(prog);
        let (data_root, source) = self
            .data
            .get_or_init(|| {
                let (d, s) = paths::data_root(prog, &paths::real_env, Some(&place));
                (d.to_string_lossy().into_owned(), s.to_string())
            })
            .clone();
        Some(Bases {
            data_root,
            data_source: source,
            local_root: paths::py_path(&paths::local_root().to_string_lossy()),
            program_root: paths::py_path(&prog.to_string_lossy()),
            place: Some(paths::py_path(&place.to_string_lossy())),
        })
    }

    /// 設定のマスターの置き場（NAVI_CONFIG_DIR、無ければ <データの基準>\Config）。
    pub fn config_dir(&self) -> Option<String> {
        if let Ok(v) = std::env::var("NAVI_CONFIG_DIR") {
            if !v.is_empty() {
                return Some(paths::py_path(&v));
            }
        }
        Some(paths::join(&self.bases()?.data_root, "Config"))
    }

    /// 答えられる問い合わせなら答える。None は Python へ回す。HEAD は GET と同じ係が答える。
    /// アプリの場所を知らない中身（試験）は、場所を使うルートを答えない。
    pub fn handle(&self, ask: &Ask) -> Option<Reply> {
        let method = if ask.method == "HEAD" { "GET" } else { ask.method };
        // 最初に当たったルートだけが答える（Flask と同じ）。そのルートが Python へ回すと決めたら、表の残りは見ない
        // （/api/data-viewer/jobs を回したあとに /api/data-viewer/<job_id> が「jobs」という対象として受けないように）
        let (pattern, f, params) = ROUTES
            .iter()
            .filter(|(m, _, _)| *m == method)
            .find_map(|(_, pattern, f)| Some((*pattern, f, match_path(pattern, ask.path)?)))?;
        if self.program_root.is_none() && !matches!(pattern, "/api/version" | "/api/period-preview") {
            return None;
        }
        Some(f(self, ask, &params)).filter(|r| r.status != 0)
    }

    /// 設定のマスターの版。前に読んだときから更新時刻も大きさも変わっていなければ、控えを返す。
    pub(crate) fn master_revision(&self, path: &Path, meta: &std::fs::Metadata, read: fn(&Path) -> i64) -> i64 {
        let Ok(mtime) = meta.modified() else { return read(path) };
        let mut seen = self.master_seen.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((p, t, len, rev)) = seen.as_ref() {
            if p == path && *t == mtime && *len == meta.len() {
                return *rev;
            }
        }
        let rev = read(path);
        *seen = Some((path.to_path_buf(), mtime, meta.len(), rev));
        rev
    }

    pub(crate) fn now(&self) -> NaiveDateTime {
        self.fixed_now.unwrap_or_else(|| Local::now().naive_local())
    }
}

/// 道筋が型に当たれば、`<名前>` に当たった値を順に返す（%XX は戻す。Flask と同じ）。
pub fn match_path(pattern: &str, path: &str) -> Option<Vec<String>> {
    let (mut p, mut q) = (pattern.split('/'), path.split('/'));
    let mut params = Vec::new();
    loop {
        match (p.next(), q.next()) {
            (None, None) => return Some(params),
            (Some(a), Some(b)) if a.starts_with('<') && a.ends_with('>') && !b.is_empty() => params.push(percent_decode(b)),
            (Some(a), Some(b)) if a == b => {}
            _ => return None,
        }
    }
}

/// %XX を戻す（UTF-8 として読めなければ元の字のまま）。
fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() && b[i + 1].is_ascii_hexdigit() && b[i + 2].is_ascii_hexdigit() {
            let hex = |c: u8| (c as char).to_digit(16).unwrap_or(0) as u8;
            out.push(hex(b[i + 1]) * 16 + hex(b[i + 2]));
            i += 3;
            continue;
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8(out).unwrap_or_else(|_| s.to_string())
}

fn get_version(_: &Core, _: &Ask, _: &[String]) -> Reply {
    Reply::json(200, &version::info())
}

/// 相対期間の設定から、処理日時を基準に、実際に抽出される期間を試算して返す。条件欄の日付は sample（RNE に入っている日付）の書き方で並べる。
fn post_period_preview(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    let d = match ask.json_or_empty() {
        Ok(d) => d,
        Err(r) => return r,
    };
    // Python は {**d, 'enabled': True} で辞書を広げる。辞書でない本文（並び・数）はそこで失敗する
    let Value::Object(mut m) = d else { return Reply::error(500, "問い合わせの本文が辞書ではありません") };
    let sample = crate::pyish::text_or_empty(m.get("sample"));
    m.insert("enabled".into(), json!(true));
    let now = core.now();
    let Some(today) = period::Date::new(i64::from(now.year()), now.month(), now.day()) else {
        return Reply::error(500, "PC の日付を読めません");
    };
    let spec = match period::normalize(&m).and_then(|p| Ok((period::compute(&p, today, &sample)?, p))) {
        Ok((Some(spec), p)) => (spec, p),
        Ok((None, _)) => return Reply::error(400, "期間を計算できません"),
        Err(_) => return Reply::error(500, "期間を計算できません（日付が 1〜9999 年を出ます）"),
    };
    let (mut out, p) = spec;
    out.insert("ok".into(), json!(true));
    out.insert("now".into(), json!(now.format("%Y-%m-%d %H:%M:%S").to_string()));
    out.insert("control_point".into(), json!(p.control_point));
    Reply::json(200, &Value::Object(out))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    fn ask<'a>(method: &'a str, path: &'a str, body: &'a [u8]) -> Ask<'a> {
        Ask { method, path, query: "", headers: vec![], body }
    }
    fn json_of(r: &Reply) -> Value {
        serde_json::from_slice(&r.body).unwrap()
    }

    #[test]
    fn paths_match_like_flask() {
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/abc"), Some(vec!["abc".to_string()]));
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/%E4%BB%95%2F"), Some(vec!["仕/".to_string()]));
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/"), None);
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/a/b"), None);
        assert_eq!(match_path("/api/version", "/api/version"), Some(Vec::<String>::new()));
        assert_eq!(match_path("/api/version", "/api/version/"), None);
    }

    #[test]
    fn unknown_routes_go_to_python() {
        let c = Core::new();
        assert!(c.handle(&ask("GET", "/api/jobs", b"")).is_none());
        assert!(c.handle(&ask("GET", "/api/config", b"")).is_none(), "アプリの場所を知らない中身は設定を答えない");
        assert!(c.handle(&ask("POST", "/api/version", b"")).is_none(), "メソッドが違えば答えない");
        assert!(c.handle(&ask("HEAD", "/api/version", b"")).is_some());
    }

    #[test]
    fn first_matching_route_decides() {
        // 決まった道（jobs）が Python へ回しても、<job_id> の道が受け直さない
        let c = Core::with_program(Path::new("/nonexistent-datarelay"));
        assert!(c.handle(&ask("GET", "/api/data-viewer/jobs", b"")).is_none());
        let first = ROUTES.iter().position(|(m, p, _)| *m == "GET" && match_path(p, "/api/data-viewer/jobs").is_some());
        assert_eq!(first.map(|i| ROUTES[i].1), Some("/api/data-viewer/jobs"));
    }

    #[test]
    fn period_preview() {
        let c = Core { fixed_now: NaiveDate::from_ymd_opt(2026, 10, 27).and_then(|d| d.and_hms_opt(9, 5, 0)), ..Core::default() };
        let r = c
            .handle(&ask(
                "POST",
                "/api/period-preview",
                br#"{"target":"cond","range":"from","unit":"day","from_offset":-90,"sample":"2026/1/1","control_point":" x "}"#,
            ))
            .unwrap();
        let v = json_of(&r);
        assert_eq!(r.status, 200);
        assert_eq!(
            (v["ok"].clone(), v["kind"].clone(), v["lvalue"].clone(), v["now"].clone(), v["control_point"].clone()),
            (json!(true), json!("cond"), json!("2026/7/29"), json!("2026-10-27 09:05:00"), json!("x"))
        );
        assert_eq!(c.handle(&ask("POST", "/api/period-preview", b"")).unwrap().status, 400, "本文が JSON でない");
        assert_eq!(c.handle(&ask("POST", "/api/period-preview", b"null")).unwrap().status, 200, "偽の値は空の辞書");
        assert_eq!(c.handle(&ask("POST", "/api/period-preview", b"[1]")).unwrap().status, 500);
        assert_eq!(c.handle(&ask("POST", "/api/period-preview", br#"{"target":"cond","from_offset":-200000}"#)).unwrap().status, 500);
    }
}
