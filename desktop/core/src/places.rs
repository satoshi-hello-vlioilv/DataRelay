//! 置き場とパスの受け口（2.16.0 で Rust へ）。決まりは paths.rs（navi_paths と同じ答え）。

use crate::http::{Ask, Reply};
use crate::paths::{self, Bases};
use crate::pyish;
use crate::routes::Core;
use serde_json::{json, Value};
use std::path::Path;

/// 本文を JSON の辞書として読む（Flask の `request.get_json(silent=True) or {}`）。読めない本文は空の辞書。
/// 辞書でない本文（並び・数）は Python が `.get` で失敗するので、同じく処理の失敗（500）。
fn body_silent(ask: &Ask) -> Result<serde_json::Map<String, Value>, Reply> {
    match serde_json::from_slice::<Value>(ask.body) {
        Ok(Value::Object(m)) => Ok(m),
        Ok(v) if pyish::truthy(&v) => Err(Reply::error(500, "問い合わせの本文が辞書ではありません")),
        _ => Ok(Default::default()),
    }
}

fn bases_or_500(core: &Core) -> Result<Bases, Reply> {
    core.bases().ok_or_else(|| Reply::error(500, "アプリの場所が分かりません"))
}

/// POST /api/path-convert … 欄の値を、絶対パスか相対パス（相対パスの基準から）へ直し、その在りかを添える。
/// 直し方の決まりは resolve_path だけが持つ（画面のファイル選択・フォルダー選択の初期の場所もここに聞く）。
pub(crate) fn post_path_convert(core: &Core, ask: &Ask, _: &[String]) -> Reply {
    let (data, b) = match (body_silent(ask), bases_or_500(core)) {
        (Ok(d), Ok(b)) => (d, b),
        (Err(r), _) | (_, Err(r)) => return r,
    };
    let value = pyish::strip(&pyish::text_or_empty(data.get("value"))).to_string();
    let relative = data.get("mode").and_then(Value::as_str) == Some("relative");
    let root = paths::resolve(&b.rel_root());
    // folder を添えると、名前だけの指定（X.RNE）をそのフォルダーの中として読む（RNE の欄。resolve_in と同じ決まり）
    let folder_raw = data.get("folder").filter(|v| !v.is_null());
    let folder = folder_raw.map(|v| pyish::text_or_empty(Some(v)));
    if value.is_empty() {
        return Reply::json(200, &json!({"value": "", "resolved": root, "base": root, "is_relative": false, "where": b.locate("", None)}));
    }
    let picked =
        if folder_raw.is_some_and(pyish::truthy) { b.resolve_in(&value, folder.as_deref()) } else { b.resolve_path(Some(&value), None) };
    let resolved = paths::resolve(&picked);
    let converted = if relative {
        match b.to_relative(&resolved, false) {
            Some(t) => t,
            None => {
                return Reply::json(
                    400,
                    &json!({"error": format!("相対パスの基準（{root}）から辿れない場所（別ドライブ・UNC）か、相対にすると別の場所の同じ名前の物を指すため、相対パスへ変換できません。絶対パスを使用してください。")}),
                )
            }
        }
    } else {
        resolved.clone()
    };
    let is_relative = paths::path_kind(&converted) == "rel";
    Reply::json(
        200,
        &json!({"value": converted, "resolved": resolved, "base": root, "is_relative": is_relative, "where": b.locate(&value, folder.as_deref())}),
    )
}

/// GET /api/users-root … ユーザーごとのデータの置き場と、そこに並ぶ人（data.json の印があるフォルダー）。
pub(crate) fn get_users_root(core: &Core, _: &Ask, _: &[String]) -> Reply {
    let b = match bases_or_500(core) {
        Ok(b) => b,
        Err(r) => return r,
    };
    let Some(place) = b.place.clone() else {
        return Reply::json(200, &json!({"ok": false, "error": "配布の置き場が分かりません"}));
    };
    let place_p = Path::new(&place);
    let conf = paths::read_json(&place_p.join("config").join(paths::SEED));
    let root = paths::users_root(place_p).to_string_lossy().into_owned();
    let name = paths::logon_name(&paths::real_env);
    let mut users: Vec<String> = std::fs::read_dir(&root)
        .map(|it| {
            it.filter_map(Result::ok)
                .filter(|d| d.path().is_dir() && d.path().join(paths::DATA_MARK).is_file())
                .map(|d| d.file_name().to_string_lossy().into_owned())
                .collect()
        })
        .unwrap_or_default();
    users.sort();
    let installed = core.program_root().is_some_and(paths::installed);
    Reply::json(
        200,
        &json!({
            "ok": true, "root": root, "defaultRoot": paths::join(&place, paths::USERS_DIR),
            "configured": pyish::text_or_empty(conf.get(paths::USERS_KEY)),
            "name": name, "mine": if name.is_empty() { String::new() } else { paths::join(&root, &name) },
            "inUse": b.data_source == "user", "dataRoot": b.data_root, "source": b.data_source,
            "users": users, "installed": installed,
        }),
    )
}
