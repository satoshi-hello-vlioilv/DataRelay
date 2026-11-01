//! 版と更新履歴（lib/changelog.toml）。Python の lib/navi_changelog.py と同じものを読む。
//!
//! exe を作るときに取り込む（配る版と更新履歴がいつも同じになる）。版・題名・日付は先頭の1件
//! （tests/test_changelog.py が lib/navi_version.py と同じであることを見張る）。

use serde_json::{json, Map, Value};
use std::sync::OnceLock;

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
