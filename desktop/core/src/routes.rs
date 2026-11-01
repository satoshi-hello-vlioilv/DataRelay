//! Rust が答えるルートの表。ここに無い問い合わせは、窓が Python へ回す。
//!
//! 1本移すたびに、ここへ足し、migration/route_plan.json を "core" にし、tests/parity/cases.json に突き合わせる場合を足す
//! （tests/test_route_plan.py と tests/test_rust_parity.py が、どれかを忘れると止める）。

use crate::http::{Ask, Reply};
use crate::{period, version};
use chrono::{Datelike, Local, NaiveDateTime};
use serde_json::{json, Value};

type Handler = fn(&Core, &Ask, &[&str]) -> Reply;

/// (メソッド, 道筋の型, 答える係)。型の `<名前>` は1段ぶんの値に当たる（Flask の書き方と同じ）。
pub const ROUTES: &[(&str, &str, Handler)] = &[("GET", "/api/version", get_version), ("POST", "/api/period-preview", post_period_preview)];

/// 中身（Rust の側）。いまは持ち物が無い。設定の置き場などを移すときに、ここへ足す。
#[derive(Default)]
pub struct Core {
    /// いまの日時を決め打ちにする（試験用）。None なら PC の時刻
    pub fixed_now: Option<NaiveDateTime>,
}

impl Core {
    pub fn new() -> Self {
        Self::default()
    }

    /// 答えられる問い合わせなら答える。None は Python へ回す。HEAD は GET と同じ係が答える。
    pub fn handle(&self, ask: &Ask) -> Option<Reply> {
        let method = if ask.method == "HEAD" { "GET" } else { ask.method };
        ROUTES.iter().find_map(|(m, pattern, f)| {
            if *m != method {
                return None;
            }
            let params = match_path(pattern, ask.path)?;
            Some(f(self, ask, &params))
        })
    }

    fn now(&self) -> NaiveDateTime {
        self.fixed_now.unwrap_or_else(|| Local::now().naive_local())
    }
}

/// 道筋が型に当たれば、`<名前>` に当たった値を順に返す。
pub fn match_path<'a>(pattern: &str, path: &'a str) -> Option<Vec<&'a str>> {
    let (mut p, mut q) = (pattern.split('/'), path.split('/'));
    let mut params = Vec::new();
    loop {
        match (p.next(), q.next()) {
            (None, None) => return Some(params),
            (Some(a), Some(b)) if a.starts_with('<') && a.ends_with('>') && !b.is_empty() => params.push(b),
            (Some(a), Some(b)) if a == b => {}
            _ => return None,
        }
    }
}

fn get_version(_: &Core, _: &Ask, _: &[&str]) -> Reply {
    Reply::json(200, &version::info())
}

/// 相対期間の設定から、処理日時を基準に、実際に抽出される期間を試算して返す。条件欄の日付は sample（RNE に入っている日付）の書き方で並べる。
fn post_period_preview(core: &Core, ask: &Ask, _: &[&str]) -> Reply {
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
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/abc"), Some(vec!["abc"]));
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/"), None);
        assert_eq!(match_path("/api/docs/<doc_id>", "/api/docs/a/b"), None);
        assert_eq!(match_path("/api/version", "/api/version"), Some(vec![]));
        assert_eq!(match_path("/api/version", "/api/version/"), None);
    }

    #[test]
    fn unknown_routes_go_to_python() {
        let c = Core::new();
        assert!(c.handle(&ask("GET", "/api/config", b"")).is_none());
        assert!(c.handle(&ask("POST", "/api/version", b"")).is_none(), "メソッドが違えば答えない");
        assert!(c.handle(&ask("HEAD", "/api/version", b"")).is_some());
    }

    #[test]
    fn period_preview() {
        let c = Core { fixed_now: NaiveDate::from_ymd_opt(2026, 10, 27).and_then(|d| d.and_hms_opt(9, 5, 0)) };
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
