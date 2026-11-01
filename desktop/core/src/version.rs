//! 版と更新履歴（lib/changelog.toml）。Python の lib/navi_changelog.py と同じものを読む。
//!
//! exe を作るときに取り込む（配る版と更新履歴がいつも同じになる）。版・題名・日付は先頭の1件
//! （tests/test_changelog.py が lib/navi_version.py と同じであることを見張る）。

use crate::http::{Ask, Reply};
use crate::paths;
use crate::routes::Core;
use serde_json::{json, Map, Value};
use std::path::Path;
use std::sync::OnceLock;
use std::time::SystemTime;

const SOURCE: &str = include_str!("../../../lib/changelog.toml");

/// 更新履歴（[[release]]）と仕様書の一覧（[[doc]]）を JSON の形で。
pub fn data() -> &'static Map<String, Value> {
    static DATA: OnceLock<Map<String, Value>> = OnceLock::new();
    DATA.get_or_init(|| match SOURCE.parse::<toml::Table>() {
        Ok(t) => t.into_iter().map(|(k, v)| (k, to_json(v))).collect(),
        Err(_) => Map::new(), // 試験（changelog_parses）で止めるので、配る版で読めないことは無い
    })
}

fn to_json(v: toml::Value) -> Value {
    match v {
        toml::Value::String(s) => Value::String(s),
        toml::Value::Integer(i) => json!(i),
        toml::Value::Float(f) => json!(f),
        toml::Value::Boolean(b) => json!(b),
        toml::Value::Datetime(d) => Value::String(d.to_string()),
        toml::Value::Array(a) => Value::Array(a.into_iter().map(to_json).collect()),
        toml::Value::Table(t) => Value::Object(t.into_iter().map(|(k, v)| (k, to_json(v))).collect()),
    }
}

pub fn changelog() -> &'static [Value] {
    data().get("release").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

fn latest(key: &str) -> &'static str {
    changelog().first().and_then(|e| e.get(key)).and_then(Value::as_str).unwrap_or("")
}

/// いまの版（例 2.15.0）。
pub fn version() -> &'static str {
    latest("version")
}

/// GET /api/version の答え（Python の version_info と同じ鍵）。
pub fn info() -> Value {
    json!({
        "version": version(),
        // 1.95.0 までのブラウザ版の名残の書き方。画面の「ビルド」に出る
        "build_version": format!("{}-web", version()),
        "title": latest("title"),
        "released_at": latest("date"),
        "changelog": changelog(),
    })
}

/// 仕様書の一覧（[[doc]]）。画面からはこの id しか受け取らないので、任意のパスは読ませない。
pub fn docs() -> &'static [Value] {
    data().get("doc").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

/// 仕様書の置き場（app.docs_dir）。Windows では Config と config は同じ場所。Linux での確かめのときだけ綴りが分かれるので両方見る。
fn docs_dir(core: &Core) -> Option<String> {
    let conf = core.config_dir()?;
    let prog = core.program_root()?.to_string_lossy().into_owned();
    let first = paths::join(&conf, "docs");
    for d in [first.clone(), paths::join(&paths::join(&prog, "config"), "docs")] {
        if Path::new(&d).is_dir() {
            return Some(d);
        }
    }
    Some(first)
}

/// ファイルの時刻を PC の時刻帯で（Python の datetime.fromtimestamp(...).strftime(fmt)）。
pub(crate) fn local_time(t: SystemTime, fmt: &str) -> String {
    chrono::DateTime::<chrono::Local>::from(t).format(fmt).to_string()
}

fn text(d: &Value, k: &str) -> String {
    d.get(k).and_then(Value::as_str).unwrap_or("").to_string()
}

/// GET /api/docs … 同梱の仕様書の一覧（置き場・大きさ・更新日時）。
pub(crate) fn get_docs(core: &Core, _: &Ask, _: &[String]) -> Reply {
    let Some(dir) = docs_dir(core) else { return Reply::error(500, "アプリの場所が分かりません") };
    let out: Vec<Value> = docs()
        .iter()
        .map(|d| {
            let path = paths::join(&dir, &text(d, "file"));
            let st = std::fs::metadata(&path).ok();
            json!({
                "id": text(d, "id"), "title": text(d, "title"), "summary": text(d, "summary"), "source": text(d, "source"),
                "file": text(d, "file"), "path": path, "available": st.is_some(),
                "bytes": st.as_ref().map(|m| m.len()).unwrap_or(0),
                "updated_at": st.and_then(|m| m.modified().ok()).map(|t| local_time(t, "%Y-%m-%d %H:%M")).unwrap_or_default(),
            })
        })
        .collect();
    Reply::json(200, &json!({"ok": true, "docs": out}))
}

/// GET /api/docs/<doc_id> … 仕様書の中身（改行は Python の読み方と同じく \n にそろえる）。
pub(crate) fn get_doc(core: &Core, _: &Ask, params: &[String]) -> Reply {
    let id = params.first().map(String::as_str).unwrap_or("");
    let Some(d) = docs().iter().find(|d| d.get("id").and_then(Value::as_str) == Some(id)) else {
        return Reply::error(404, "登録されていない仕様書です");
    };
    let Some(dir) = docs_dir(core) else { return Reply::error(500, "アプリの場所が分かりません") };
    let path = paths::join(&dir, &text(d, "file"));
    if !Path::new(&path).is_file() {
        return Reply::error(404, &format!("{path} が見つかりません。配布物に含まれているか確認してください。"));
    }
    let body = match std::fs::read(&path).map_err(|e| e.to_string()).and_then(|b| String::from_utf8(b).map_err(|e| e.to_string())) {
        Ok(t) => t.replace("\r\n", "\n").replace('\r', "\n"),
        Err(e) => return Reply::error(500, &e),
    };
    Reply::json(
        200,
        &json!({"ok": true, "id": text(d, "id"), "title": text(d, "title"), "summary": text(d, "summary"), "source": text(d, "source"), "path": path, "text": body}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn changelog_parses() {
        SOURCE.parse::<toml::Table>().expect("lib/changelog.toml を読めない");
        assert!(changelog().len() > 100);
        assert!(!version().is_empty() && !latest("title").is_empty());
        let e = &changelog()[0];
        assert!(e["notes"].as_array().is_some_and(|n| n.iter().all(Value::is_string)));
        assert_eq!(data()["doc"][0]["id"], "navigator-api");
    }
}
