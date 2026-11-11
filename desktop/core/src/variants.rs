//! 条件の値ごとに分けて出す対象の、値ごとのファイルの決め方（2.29.0〜）。
//! lib/navi_variants.py の plan・has_token と、app.py の render_path_template・variant_jobs・viewer_files と同じ答えを返す。
//!
//! 値ごとの名前: 値ごとの型があればそれ、無ければ対象の名前の型に {値} があればそれ、どちらにも無ければ「ふだんの名前_{値}」。
//! 値ごとの置き場: 値ごとの置き場の型があればそれ（道の区切りは残す）、無ければ対象の出力先。
//! 同じ置き場・同じ名前になる値があれば、どの値の道も決めない（Python の ValueError。あとの値が前の値のファイルを上書きするため）。
use crate::config::{self, Pass};
use crate::naming::{self, Fail, Tokens, VALUE_TOKENS};
use crate::paths::{self, Bases};
use crate::{pyish, routes::Core};
use chrono::NaiveDateTime;
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

/// navi_variants.has_token（型に、その回の値 {値}・{値:upper} などが入っているか）。
pub fn has_token(text: &str) -> bool {
    VALUE_TOKENS.iter().any(|t| text.contains(&format!("{{{t}}}")) || text.contains(&format!("{{{t}:")))
}

/// render_path_template（置き場の型を展開する。道の区切りは残し、変数から展開した部分からだけファイル名に使えない字を落とす。
/// 点だけになった部分は、道の上で「ここ」「1つ上」にならないよう _ にする）。
pub fn render_path_template(template: &str, tokens: &Tokens) -> Result<String, Fail> {
    let mut out = String::new();
    let mut pos = 0;
    for (a, b, inner) in naming::braces(template) {
        out.push_str(&template[pos..a]);
        let (text, is_var) = tokens.expand(inner)?;
        if is_var {
            let text = naming::drop_illegal(&text);
            let text = pyish::strip(&text);
            out.push_str(if !text.is_empty() && text.trim_matches(['.', ' ']).is_empty() { "_" } else { text });
        } else {
            out.push_str(&text);
        }
        pos = b;
    }
    out.push_str(&template[pos..]);
    Ok(pyish::strip(&out).to_string())
}

/// 値ごとの出し先1つ（plan の1行）。
pub struct Planned {
    pub value: String,
    pub stem: String,
    pub folder: String,
}

/// navi_variants.plan。Err は Python の例外（名前の展開に失敗した・同じ名前になる値がある）。
pub fn plan(
    job: &Map<String, Value>,
    v: &Value,
    tokens: impl Fn(&str) -> Tokens,
    base_name: &str,
    base_folder: &str,
    values: &[String],
) -> Result<Vec<Planned>, Fail> {
    let text = |k: &str| v[k].as_str().unwrap_or("").to_string();
    let (pattern, folder_t) = (text("pattern"), text("folder"));
    let job_pattern = if naming::text_or(job.get("naming_mode"), "") == "template" {
        naming::text_or(job.get("output_pattern"), "")
    } else {
        String::new()
    };
    let mut out: Vec<Planned> = Vec::new();
    let mut seen: Vec<((String, String), String)> = Vec::new();
    for value in values {
        let t = tokens(value);
        let stem = if !pattern.is_empty() {
            naming::render_filename_template(&pattern, &t)?
        } else if has_token(&job_pattern) {
            naming::render_filename_template(&job_pattern, &t)?
        } else {
            naming::render_filename_template(&format!("{base_name}_{{値}}"), &t)?
        };
        let folder = if folder_t.is_empty() { base_folder.to_string() } else { render_path_template(&folder_t, &t)? };
        let key = (folder.to_lowercase(), stem.to_lowercase());
        if seen.iter().any(|(k, _)| *k == key) {
            return Err(Fail);
        }
        seen.push((key, value.clone()));
        out.push(Planned { value: value.clone(), stem, folder });
    }
    Ok(out)
}

fn with_value(job: &Map<String, Value>, value: &str) -> Map<String, Value> {
    let mut j = job.clone();
    j.insert("_variant_value".into(), json!(value));
    j
}

/// 値ごとの「1回ぶんの対象」のうち、ファイルの道を決める分（値・置き場の型を展開した物・ファイル名）。
pub struct OneJob {
    pub value: String,
    pub folder: String,
    pub file: String,
}

/// variant_jobs（値ごとの「1回ぶんの対象」）。ここでは名前と置き場だけを返す。
pub fn variant_jobs(
    core: &Core,
    job: &Map<String, Value>,
    cfg: &Map<String, Value>,
    now: NaiveDateTime,
    values: &[String],
) -> R<Result<Vec<OneJob>, Fail>> {
    let v = config::normalize_variants(job.get("variants").unwrap_or(&Value::Null))?;
    let rp = config::rne_path(core, job, cfg);
    let base = match naming::resolve_output_filename(&with_value(job, ""), rp.as_deref(), now) {
        Ok(name) => paths::py_stem(&name),
        Err(e) => return Ok(Err(e)),
    };
    let fmt = naming::normalize_output_format(job.get("output_format"), job.get("output_file"));
    let base_folder = naming::text_or(job.get("output_folder"), "");
    let tokens = |value: &str| Tokens::new(&with_value(job, value), rp.as_deref(), now);
    Ok(plan(job, &v, tokens, &base, &base_folder, values).map(|xs| {
        xs.into_iter()
            .map(|x| {
                let file = naming::canonical_output_file(Some(&Value::String(x.stem)), fmt);
                OneJob { value: x.value, folder: x.folder, file }
            })
            .collect()
    }))
}

/// navi_variants.active（値ごとに分けて出すか）。
pub fn active(job: &Map<String, Value>) -> R<bool> {
    let v = config::normalize_variants(job.get("variants").unwrap_or(&Value::Null))?;
    let has_values = v["values"].as_array().is_some_and(|a| !a.is_empty());
    Ok(v["enabled"] == json!(true) && pyish::truthy(&v["item"]) && (has_values || v["scope"] == json!("all")))
}

/// ビュワーで開けるファイル1つ（viewer_files の1行）。path が空なら Path('')（どこにも無い）。
pub struct ViewerFile {
    pub value: String,
    pub path: String,
    pub rows: Value,
}

/// 入れた順を保つ辞書（Python の dict）。
type Ordered<T> = Vec<(String, T)>;

/// 実行記録の値ごとの結果（metrics.variant_results）。→ (作った道, 件数)。形が違えば Pass（Python は落ちる）。
fn made(run: Option<&Map<String, Value>>) -> R<(Ordered<String>, Ordered<Value>)> {
    let (mut made, mut rows): (Ordered<String>, Ordered<Value>) = (Vec::new(), Vec::new());
    let metrics = match run.and_then(|r| r.get("metrics")) {
        Some(Value::Object(m)) => m,
        Some(x) if pyish::truthy(x) => return Err(Pass),
        _ => return Ok((made, rows)),
    };
    let results = match metrics.get("variant_results") {
        Some(Value::Array(a)) => a,
        Some(x) if pyish::truthy(x) => return Err(Pass),
        _ => return Ok((made, rows)),
    };
    for r in results {
        let Value::Object(r) = r else { return Err(Pass) };
        let Some(value) = r.get("value").filter(|x| !x.is_null()) else { continue };
        let value = pyish::py_str(value);
        if let Some(t) = r.get("target").filter(|x| pyish::truthy(x)) {
            put(&mut made, value.clone(), paths::py_path(&pyish::py_str(t)));
        }
        if r.get("ok").is_some_and(pyish::truthy) {
            put(&mut rows, value, r.get("rows").cloned().unwrap_or(Value::Null));
        }
    }
    Ok((made, rows))
}

/// dict へ入れる（同じ鍵は、最初の位置のまま値だけ替える）。
fn put<T>(list: &mut Vec<(String, T)>, k: String, x: T) {
    match list.iter_mut().find(|(key, _)| *key == k) {
        Some(slot) => slot.1 = x,
        None => list.push((k, x)),
    }
}

fn is_file(p: &str) -> bool {
    !p.is_empty() && std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
}

/// viewer_files の、値ごとに分けて出す対象の分（前回の実行が作ったファイルを先に、無ければ今の設定から決まる道）。
pub fn viewer_files(
    core: &Core,
    b: &Bases,
    job: &Map<String, Value>,
    cfg: &Map<String, Value>,
    runs: &[(Value, Map<String, Value>)],
) -> R<Vec<ViewerFile>> {
    let run = runs.iter().find(|(k, _)| Some(k) == job.get("id")).map(|(_, r)| r);
    let (made, rows) = made(run)?;
    let v = config::normalize_variants(job.get("variants").unwrap_or(&Value::Null))?;
    let values: Vec<String> = if v["scope"] == json!("all") {
        made.iter().map(|(k, _)| k.clone()).collect()
    } else {
        v["values"].as_array().into_iter().flatten().filter_map(|x| x.as_str().map(String::from)).collect()
    };
    let planned: Vec<(String, String)> = match variant_jobs(core, job, cfg, core.now(), &values)? {
        Ok(xs) => xs
            .into_iter()
            .map(|x| {
                let one = Map::from_iter([("output_folder".to_string(), json!(x.folder))]);
                (x.value, paths::join(&crate::joinplan::output_folder(b, &one, cfg), &x.file))
            })
            .collect(),
        Err(Fail) => Vec::new(),
    };
    let find = |list: &[(String, String)], k: &str| list.iter().find(|(key, _)| key == k).map(|(_, p)| p.clone());
    Ok(values
        .iter()
        .map(|value| {
            let got = find(&made, value);
            let path = match (got, find(&planned, value)) {
                (Some(g), _) if is_file(&g) => g,
                (_, Some(p)) => p,
                (Some(g), None) => g,
                (None, None) => String::new(),
            };
            let rows = rows.iter().find(|(k, _)| k == value).map(|(_, r)| r.clone()).unwrap_or(Value::Null);
            ViewerFile { value: value.clone(), path, rows }
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_in_text() {
        assert!(has_token("a_{値}") && has_token("{value:upper}") && has_token("x{値:replace:a:b}"));
        assert!(!has_token("{値 }") && !has_token("値") && !has_token("{name}"));
    }

    #[test]
    fn path_keeps_separators_and_guards_dots() {
        let now = chrono::NaiveDate::from_ymd_opt(2026, 11, 2).unwrap().and_hms_opt(9, 5, 7).unwrap();
        let tok = |v: &str| Tokens::new(&with_value(&Map::new(), v), None, now);
        assert_eq!(render_path_template(r"D:\出力\{値}", &tok("a/b:c")).ok(), Some(r"D:\出力\abc".into()));
        assert_eq!(render_path_template(r"D:\出力\{値}\x", &tok("..")).ok(), Some(r"D:\出力\_\x".into()));
        assert_eq!(render_path_template(r" D:\{知らない}\{date} ", &tok("")).ok(), Some(r"D:\{知らない}\20261102".into()));
    }
}
