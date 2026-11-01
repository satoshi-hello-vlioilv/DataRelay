//! Navigator への接続情報の受け口（2.17.0 で Rust へ。置き場と読み方は secret.rs）。
//! パスワードは画面へ返さない（入っているかどうかだけ）。記録にも出さない（出すのはサーバー・利用者ID・出どころ）。

use crate::http::{Ask, Reply};
use crate::routes::Core;
use crate::secret::{self, Vault};
use crate::settings::{self, Settings};
use crate::{paths, pyish};
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};

fn local_root() -> PathBuf {
    PathBuf::from(paths::py_path(&paths::local_root().to_string_lossy()))
}

fn vault() -> Vault {
    Vault::default_for(&local_root())
}

/// 本文を辞書として読む（Flask の get_json(silent=True) or {}）。読めない本文は空の辞書、辞書でない本文は Python が落ちる形（500）。
fn body(ask: &Ask) -> Result<Map<String, Value>, Reply> {
    match serde_json::from_slice::<Value>(ask.body) {
        Ok(Value::Object(m)) => Ok(m),
        Ok(v) if pyish::truthy(&v) => Err(Reply::error(500, "問い合わせの本文が辞書ではありません")),
        _ => Ok(Map::new()),
    }
}

fn fail(e: String) -> Reply {
    Reply::json(400, &json!({"ok": false, "error": e}))
}

/// 設定の symnavim.conf の実体（在れば。app.legacy_conf_path）。
fn legacy_conf_path(core: &Core, s: &Settings) -> Result<Option<PathBuf>, String> {
    let raw = pyish::strip(&pyish::text_or_empty(s.top("symnavim_conf")?.as_ref())).to_string();
    if raw.is_empty() {
        return Ok(None);
    }
    let Some(b) = core.bases() else { return Ok(None) };
    let p = PathBuf::from(b.resolve_path(Some(&raw), None));
    Ok(p.is_file().then_some(p))
}

/// 画面「Navigator の接続情報」と事前診断が見る答え（app.login_state）。パスワードは返さない。
fn login_state(core: &Core) -> Result<Map<String, Value>, Reply> {
    let lr = local_root();
    let s = Settings::open(&settings::local_db(&lr)).map_err(|e| Reply::error(500, &e))?;
    let needed = s.job_kinds().map_err(|e| Reply::error(500, &e))?.iter().any(|(on, src)| *on && *src == "rne");
    let v = vault();
    let mut out = Map::new();
    out.insert("where".into(), json!(v.place()));
    out.insert("vault".into(), json!(v.kind()));
    out.insert("needed".into(), json!(needed));
    out.insert("declined".into(), json!(secret::declined(&lr)));
    out.insert("conf".into(), Value::Null);
    out.insert("error".into(), json!(""));
    match v.load() {
        Ok(d) => out.extend(secret::public(d.as_ref())),
        Err(e) => {
            out.insert("saved".into(), json!(false));
            out.insert("error".into(), json!(format!("このPCの置き場を読めません: {e}")));
        }
    }
    if let Some(p) = legacy_conf_path(core, &s).map_err(|e| Reply::error(500, &e))? {
        let path = paths::py_path(&p.to_string_lossy());
        out.insert(
            "conf".into(),
            match secret::read_conf(&p) {
                Ok(d) => json!({"path": path, "ok": true, "server": d["server"], "user": d["user"], "section": d["section"], "profiles": d["profiles"].as_array().map(Vec::len).unwrap_or(0)}),
                Err(e) => json!({"path": path, "ok": false, "error": e}),
            },
        );
    }
    let saved = out.get("saved").is_some_and(|x| x == &json!(true));
    let conf_ok = out["conf"].get("ok").is_some_and(|x| x == &json!(true));
    out.insert(
        "source".into(),
        json!(if saved {
            "vault"
        } else if conf_ok {
            "conf"
        } else {
            ""
        }),
    );
    Ok(out)
}

fn with_state(core: &Core, mut head: Map<String, Value>) -> Reply {
    match login_state(core) {
        Ok(st) => {
            head.extend(st);
            Reply::json(200, &Value::Object(head))
        }
        Err(r) => r,
    }
}

fn ok_head() -> Map<String, Value> {
    let mut m = Map::new();
    m.insert("ok".into(), json!(true));
    m
}

/// 置き場へ入れ、「使わない」の答えを取り消す（app._login_saved）。
fn saved(core: &Core, data: Map<String, Value>, origin: &str) -> Reply {
    let v = vault();
    let n = data.get("profiles").and_then(Value::as_array).map(Vec::len).unwrap_or(0);
    let (server, user) = (data["server"].as_str().unwrap_or("").to_string(), data["user"].as_str().unwrap_or("").to_string());
    if let Err(e) = v.save(&secret::stamp(data, origin)) {
        return fail(e);
    }
    if let Err(e) = secret::decline(&local_root(), false) {
        return fail(e);
    }
    core.log(&format!("LOGIN_SAVED origin={origin} server={server} user={user} profiles={n} vault={}", v.kind()));
    with_state(core, ok_head())
}

/// GET /api/login
pub(crate) fn get_login(core: &Core, _: &Ask, _: &[String]) -> Reply {
    with_state(core, ok_head())
}

/// POST /api/login … 画面から登録・変更する。パスワードを空のまま送れば前のものを使う（同じ利用者IDのときだけ）。
pub(crate) fn post_login(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    // Python は本文を dict() で辞書にする（並びでも辞書へ直せれば通り、直せなければ ValueError の 400・TypeError の 500）
    let raw = serde_json::from_slice::<Value>(ask.body).ok().filter(pyish::truthy).unwrap_or(Value::Null);
    let old = match vault().load() {
        Ok(o) => o,
        Err(e) => return fail(e),
    };
    let b = match secret::py_dict(&raw) {
        Ok(b) => b,
        Err(Some(e)) => return fail(e),
        Err(None) => return Reply::error(500, "問い合わせの本文を辞書にできません"),
    };
    match secret::clean(&Value::Object(secret::merge(old.as_ref(), &b))) {
        Ok(data) => saved(core, data, "form"),
        Err(Some(e)) => fail(e),
        Err(None) => Reply::error(500, "接続情報の形が正しくありません"),
    }
}

/// POST /api/login/import … symnavim.conf の中身をこのPCの置き場へ取り込む。path が無ければ設定の symnavim.conf。ファイルは消さない。
pub(crate) fn post_import(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    let b = match body(ask) {
        Ok(b) => b,
        Err(r) => return r,
    };
    let raw = pyish::strip(&pyish::text_or_empty(b.get("path"))).to_string();
    let p = if raw.is_empty() {
        let s = match Settings::open(&settings::local_db(&local_root())) {
            Ok(s) => s,
            Err(e) => return Reply::error(500, &e),
        };
        match legacy_conf_path(core, &s) {
            Ok(p) => p,
            Err(e) => return Reply::error(500, &e),
        }
    } else {
        // Python の中身はアプリのフォルダーで動く。相対の道はそこから読む（窓のいまのフォルダーとは限らない）
        let given = Path::new(&raw);
        Some(if given.is_absolute() {
            given.to_path_buf()
        } else {
            core.program_root().map(|r| r.join(given)).unwrap_or_else(|| given.to_path_buf())
        })
    };
    let Some(p) = p.filter(|p| p.is_file()) else {
        let tail = if raw.is_empty() { "（設定の symnavim.conf がありません）".to_string() } else { format!(": {raw}") };
        return fail(format!("取り込む symnavim.conf が見つかりません{tail}"));
    };
    let data = match secret::read_conf(&p).and_then(|d| secret::clean(&Value::Object(d)).map_err(|e| e.unwrap_or_default())) {
        Ok(d) => d,
        Err(e) => return fail(e),
    };
    saved(core, data, "conf")
}

/// POST /api/login/delete … このPCの置き場から消す（PCを人に譲る・利用者IDを変える前など）。
pub(crate) fn post_delete(core: &Core, _: &Ask, _: &[String]) -> Reply {
    let v = vault();
    let removed = match v.delete() {
        Ok(r) => r,
        Err(e) => return fail(e),
    };
    core.log(&format!("LOGIN_DELETED removed={} vault={}", if removed { "True" } else { "False" }, v.kind()));
    let mut head = ok_head();
    head.insert("removed".into(), json!(removed));
    with_state(core, head)
}

/// POST /api/login/decline … 初めて開いたときの「登録しますか」に「Navigator は使わない」と答えたこと。yes=false で取り消す。
pub(crate) fn post_decline(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    let b = match body(ask) {
        Ok(b) => b,
        Err(r) => return r,
    };
    let yes = b.get("yes") != Some(&Value::Bool(false));
    if let Err(e) = secret::decline(&local_root(), yes) {
        return Reply::error(500, &e);
    }
    with_state(core, ok_head())
}
