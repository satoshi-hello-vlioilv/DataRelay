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
