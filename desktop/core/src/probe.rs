//! 関数ごとの突き合わせの口（`datarelay-core call`）。tests/test_rust_paths.py が、いろいろなフォルダーの状態を作って
//! Python の関数（navi_paths・navi_release）と同じ問いを出し、答えを比べる。ルートの答えだけでは、フォルダーの状態で
//! 変わる決まり（データの基準の決める順など）を一通り確かめられないため。配る exe の動きには関わらない。

use crate::paths::{self, Bases};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};

fn s<'a>(a: &'a Value, k: &str) -> &'a str {
    a.get(k).and_then(Value::as_str).unwrap_or("")
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
        "resolve" => json!(paths::resolve(s(a, "value"))),
        "rel_bases" => json!(bases(a).rel_bases()),
        "resolve_path" => json!(bases(a).resolve_path(opt(a, "value"), opt(a, "base"))),
        "resolve_in" => json!(bases(a).resolve_in(s(a, "value"), opt(a, "folder"))),
        "locate" => Value::Object(bases(a).locate(s(a, "value"), opt(a, "folder"))),
        "to_relative" => json!(bases(a).to_relative(s(a, "path"), a["inside_only"].as_bool().unwrap_or(false))),
        _ => return Err(format!("知らない問い: {name}")),
    })
}
