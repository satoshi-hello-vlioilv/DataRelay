//! Navigator への接続情報（lib/navi_secret.py と同じ答え。2.17.0 で移した）。
//!
//! 置き場は Windows の「資格情報マネージャー」（汎用資格情報「DataRelay/Navigator」。中身は Windows が利用者ごとに暗号化する）。
//! 中身の形（JSON・UTF-8・つなぎの空白なし）は Python と同じにする ―― 抽出のワーカー（Python）が同じ置き場を読むため。
//! Windows 以外と試験（NAVI_SECRET_FILE）はファイルの置き場。symnavim.conf の読み方（configparser と同じ決まり）もここに置く。

use crate::pyish;
use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};

pub const TARGET: &str = "DataRelay/Navigator";
/// 汎用資格情報の中身の上限（CRED_MAX_CREDENTIAL_BLOB_SIZE）
pub const BLOB_LIMIT: usize = 5 * 512;
pub const DECLINED_FILE: &str = "login_declined.json";
/// 追加のデータソース（symnavim.conf の [ApiOracle] など）。名前の綴りの揺れは英数字だけで比べる
const PROFILE_KINDS: [(&str, &str); 6] = [
    ("apioracle", "oracle"),
    ("apisqlserver", "sqlserver"),
    ("apirda", "rda"),
    ("apipostgres", "postgres"),
    ("apiresource", "resource"),
    ("apiresourcenoauth", "noauth"),
];
const PROFILE_FIELDS: [&str; 8] = ["section", "kind", "user", "password", "server", "option", "resource", "resource_kind"];

/// 断る理由（Python の ValueError・OSError の文言と同じ。画面へそのまま出す）。
pub type Fail = String;

// ==== symnavim.conf の読み方（configparser.ConfigParser(interpolation=None)・optionxform=str.lower と同じ） ====

/// 読んだ INI。[DEFAULT] は別に持ち、どのセクションにも引き継ぐ（configparser と同じ）。
#[derive(Debug, Default)]
pub struct Ini {
    defaults: Vec<(String, String)>,
    sections: Vec<(String, Vec<(String, String)>)>,
}

/// 書き方の誤り（configparser の例外に当たる）。文言は Python と同じにできないので、種類だけ持つ。
#[derive(Debug, PartialEq)]
pub struct SyntaxError(pub String);

fn set(kv: &mut Vec<(String, String)>, k: &str, v: String) {
    match kv.iter_mut().find(|(x, _)| x == k) {
        Some(p) => p.1 = v,
        None => kv.push((k.to_string(), v)),
    }
}

impl Ini {
    /// RawConfigParser._read と同じ読み方（行頭の # ; は注記、= か : で区切る、字下げした行は前の値の続き、重なりは誤り）。
    pub fn parse(text: &str) -> Result<Ini, SyntaxError> {
        let mut ini = Ini::default();
        // 値は行の並び（続きの行は足す。空の行も値の中の改行として持つ）。最後に \n でつなぎ、末尾の空白を落とす
        type Raw = Vec<(String, Vec<String>)>;
        let mut defaults: Raw = Vec::new();
        let mut sections: Vec<(String, Raw)> = Vec::new();
        let mut cur: Option<usize> = None; // None = まだセクションが無い、Some(usize::MAX) = [DEFAULT]
        let mut optname: Option<String> = None;
        let mut indent_level = 0usize;
        let mut added: Vec<String> = Vec::new(); // 重なりを見るための "セクション" と "セクション\0鍵"
        let mut errors = false;
        for line in text.split_inclusive('\n') {
            let is_comment = ["#", ";"].iter().any(|p| pyish::strip(line).starts_with(p));
            let value = if is_comment { "" } else { pyish::strip(line) };
            if value.is_empty() {
                // 空の行: 値の途中なら値の中の改行（注記の行は数えない）。字下げの基準は外さない（empty_lines_in_values の既定）
                let target = match cur {
                    Some(usize::MAX) => Some(&mut defaults),
                    Some(i) => sections.get_mut(i).map(|s| &mut s.1),
                    None => None,
                };
                if let (false, Some(t), Some(o)) = (is_comment, target, &optname) {
                    if let Some(v) = t.iter_mut().find(|(k, _)| k == o) {
                        v.1.push(String::new());
                    }
                }
                continue;
            }
            let cur_indent = line.chars().take_while(|c| pyish::is_space(*c)).count();
            if cur.is_some() && optname.is_some() && cur_indent > indent_level {
                let o = optname.clone().unwrap_or_default();
                let t = if cur == Some(usize::MAX) { &mut defaults } else { &mut sections[cur.unwrap_or(0)].1 };
                if let Some(v) = t.iter_mut().find(|(k, _)| *k == o) {
                    v.1.push(value.to_string());
                }
                continue;
            }
            indent_level = cur_indent;
            // セクションの見出し: 正規表現 \[(?P<header>.+)\] を値の頭に当てる（.+ は貪欲・最後の ] まで）
            if let Some(header) = value.strip_prefix('[').and_then(|r| r.rfind(']').filter(|&i| i > 0).map(|i| &r[..i])) {
                if header == "DEFAULT" {
                    cur = Some(usize::MAX);
                } else if let Some(i) = sections.iter().position(|(n, _)| n == header) {
                    if added.iter().any(|x| x == header) {
                        return Err(SyntaxError(format!("セクション [{header}] が2回あります")));
                    }
                    cur = Some(i);
                } else {
                    sections.push((header.to_string(), Vec::new()));
                    cur = Some(sections.len() - 1);
                }
                added.push(header.to_string());
                optname = None;
                continue;
            }
            let Some(ci) = cur else { return Err(SyntaxError("セクションの見出しより前に値があります".into())) };
            // 鍵 = 値: (?P<option>.*?)\s*(?P<vi>=|:)\s*(?P<value>.*)$ 。区切りは最初の = か :
            let Some(pos) = value.find(['=', ':']) else {
                errors = true;
                continue;
            };
            let name = value[..pos].trim_end_matches(pyish::is_space);
            if name.is_empty() {
                errors = true;
                continue;
            }
            let key = name.to_lowercase();
            let sect = if ci == usize::MAX { "DEFAULT".to_string() } else { sections[ci].0.clone() };
            let mark = format!("{sect}\0{key}");
            if added.contains(&mark) {
                return Err(SyntaxError(format!("[{sect}] の {key} が2回あります")));
            }
            added.push(mark);
            let v = pyish::strip(&value[pos + 1..]).to_string();
            let t = if ci == usize::MAX { &mut defaults } else { &mut sections[ci].1 };
            match t.iter_mut().find(|(k, _)| *k == key) {
                Some(p) => p.1 = vec![v],
                None => t.push((key.clone(), vec![v])),
            }
            optname = Some(key);
        }
        if errors {
            return Err(SyntaxError("読めない行があります".into()));
        }
        let join =
            |raw: Raw| raw.into_iter().map(|(k, v)| (k, v.join("\n").trim_end_matches(pyish::is_space).to_string())).collect::<Vec<_>>();
        ini.defaults = join(defaults);
        ini.sections = sections.into_iter().map(|(n, raw)| (n, join(raw))).collect();
        Ok(ini)
    }

    pub fn section_names(&self) -> Vec<&str> {
        self.sections.iter().map(|(n, _)| n.as_str()).collect()
    }

    /// cp.items(section)（[DEFAULT] の値を引き継ぎ、セクションの値で上書き）。
    pub fn items(&self, section: &str) -> Vec<(String, String)> {
        let mut out = self.defaults.clone();
        if let Some((_, kv)) = self.sections.iter().find(|(n, _)| n == section) {
            for (k, v) in kv {
                set(&mut out, k, v.clone());
            }
        }
        out
    }
}

/// symnavim.conf を文字にする。UTF-8（BOM 可）か CP932。
pub fn read_conf_text(raw: &[u8]) -> Result<String, Fail> {
    let raw_u8 = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(raw);
    if let Ok(t) = std::str::from_utf8(raw_u8) {
        return Ok(t.to_string());
    }
    cp932(raw).ok_or_else(|| "symnavim.conf の文字コードを読めません（CP932 か UTF-8 で保存してください）".into())
}

/// Python の cp932（Microsoft の表）で読む。読めない並びがあれば None。
/// 1 バイトの字は自分で読む（0x80→U+0080、0xA0→U+F8F0、0xFD〜0xFF→U+F8F1〜F8F3 は WHATWG の Shift_JIS では誤りになるため）。
/// 2 バイトの字は encoding_rs の Shift_JIS（Windows-31J の表）に任せる。
pub fn cp932(raw: &[u8]) -> Option<String> {
    let mut out = String::with_capacity(raw.len());
    let mut i = 0;
    while i < raw.len() {
        let b = raw[i];
        match b {
            0x00..=0x80 => out.push(char::from(b)),
            0xA0 => out.push('\u{F8F0}'),
            0xA1..=0xDF => out.push(char::from_u32(0xFF61 + u32::from(b - 0xA1))?),
            0xFD..=0xFF => out.push(char::from_u32(0xF8F1 + u32::from(b - 0xFD))?),
            _ => {
                let pair = raw.get(i..i + 2)?;
                out.push_str(&encoding_rs::SHIFT_JIS.decode_without_bom_handling_and_without_replacement(pair)?);
                i += 2;
                continue;
            }
        }
        i += 1;
    }
    Some(out)
}

/// symnavim.conf の中身を、置き場に入れる形 {server, user, password, section, profiles} にする（navi_secret.parse_conf）。
/// 書き方の誤り（configparser の例外）は Err(Ok(SyntaxError))、決まりの不足は Err(Err(文言))。
pub fn parse_conf(text: &str) -> Result<Map<String, Value>, Result<SyntaxError, Fail>> {
    let ini = Ini::parse(text).map_err(Ok)?;
    let names = ini.section_names();
    if names.is_empty() {
        return Err(Err("symnavim.confを読み取れません".into()));
    }
    let sec = if names.contains(&"Default") {
        "Default".to_string()
    } else {
        names.iter().find(|x| x.to_lowercase().starts_with("connect_")).unwrap_or(&names[0]).to_string()
    };
    let d: Vec<(String, String)> = ini.items(&sec).into_iter().map(|(k, v)| (k.to_lowercase(), pyish::strip(&v).to_string())).collect();
    let get = |kv: &[(String, String)], k: &str| kv.iter().find(|(x, _)| x == k).map(|(_, v)| v.clone());
    let mut out = Map::new();
    out.insert("server".into(), json!(get(&d, "symnaviserver").unwrap_or_default()));
    out.insert("user".into(), json!(get(&d, "symnaviuserid").unwrap_or_default()));
    out.insert("password".into(), json!(get(&d, "symnavipasswd").unwrap_or_default()));
    out.insert("section".into(), json!(sec));
    if ["server", "user", "password"].iter().any(|k| out[*k].as_str().unwrap_or("").is_empty()) {
        return Err(Err(format!("[{sec}]にSymNaviUSERID、SymNaviPASSWD、SymNaviServerが必要です")));
    }
    let mut profiles = Vec::new();
    for section in ini.section_names() {
        let squashed: String = section.to_lowercase().chars().filter(|c| c.is_alphanumeric()).collect();
        let Some((_, kind)) = PROFILE_KINDS.iter().find(|(k, _)| *k == squashed) else { continue };
        let p: Vec<(String, String)> =
            ini.items(section).into_iter().map(|(k, v)| (k.to_lowercase(), pyish::strip(&v).to_string())).collect();
        let enabled = get(&p, "enabled").unwrap_or_else(|| "yes".into()).to_lowercase();
        if ["0", "no", "false", "off"].contains(&enabled.as_str()) {
            continue;
        }
        let pick = |a: &str, b: &str, dflt: &str| get(&p, a).or_else(|| get(&p, b)).unwrap_or_else(|| dflt.into());
        profiles.push(json!({
            "section": section, "kind": kind, "user": pick("user", "userid", ""), "password": pick("password", "passwd", ""),
            "server": get(&p, "server").unwrap_or_default(), "option": pick("option", "opt", ""),
            "resource": pick("resource", "resourcename", ""), "resource_kind": pick("resource_kind", "resourcekind", "0"),
        }));
    }
    out.insert("profiles".into(), Value::Array(profiles));
    Ok(out)
}

/// 書き方の誤りを、Python と同じ前置きの文言にする（中身の説明は Python と同じにはならない）。
pub fn conf_error(e: Result<SyntaxError, Fail>) -> Fail {
    match e {
        Ok(SyntaxError(m)) => format!("symnavim.conf の書き方を読めません: {m}"),
        Err(m) => m,
    }
}

/// symnavim.conf を読む（navi_secret.read_conf）。
pub fn read_conf(path: &Path) -> Result<Map<String, Value>, Fail> {
    let raw = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    parse_conf(&read_conf_text(&raw)?).map_err(conf_error)
}

// ==== 置き場に入れる形 ====

/// 画面や取り込みから来た値を、置き場に入れる形へそろえる。足りなければ理由を添えて断る（navi_secret.clean）。
/// Err(None) は Python が TypeError で落ちる形（profiles が数など）。
pub fn clean(data: &Value) -> Result<Map<String, Value>, Option<Fail>> {
    let Value::Object(d) = data else { return Err(Some("接続情報の形が正しくありません".into())) };
    let mut out = Map::new();
    for k in ["server", "user", "password"] {
        out.insert(k.into(), json!(pyish::strip(&pyish::text_or_empty(d.get(k)))));
    }
    let missing: Vec<&str> = [("server", "サーバー"), ("user", "利用者ID"), ("password", "パスワード")]
        .iter()
        .filter(|(k, _)| out[*k].as_str().unwrap_or("").is_empty())
        .map(|(_, w)| *w)
        .collect();
    if !missing.is_empty() {
        return Err(Some(format!("{}を入れてください", missing.join("、"))));
    }
    out.insert("section".into(), json!(pyish::strip(&pyish::text_or_empty(d.get("section")))));
    let items: Vec<Value> = match d.get("profiles") {
        Some(Value::Array(a)) => a.clone(),
        Some(v) if !pyish::truthy(v) => vec![],
        Some(Value::String(_)) | Some(Value::Object(_)) => vec![], // 文字・辞書は回すと字・鍵になり、どれも辞書ではない
        Some(_) => return Err(None),
        None => vec![],
    };
    let kinds: Vec<&str> = PROFILE_KINDS.iter().map(|(_, v)| *v).collect();
    let profiles: Vec<Value> = items
        .iter()
        .filter_map(|p| {
            let o = p.as_object()?;
            o.get("kind").and_then(Value::as_str).filter(|k| kinds.contains(k))?;
            Some(Value::Object(
                PROFILE_FIELDS.iter().map(|k| (k.to_string(), json!(pyish::strip(&pyish::text_or_empty(o.get(*k)))))).collect(),
            ))
        })
        .collect();
    out.insert("profiles".into(), Value::Array(profiles));
    Ok(out)
}

/// Python の dict(v)（並びを辞書へ直す決まり）。並びの要素は長さ 2 の物（[鍵, 値]・2 文字の字・鍵が 2 つの辞書）。
/// Err(Some(文言)) は ValueError（Python の文言と同じ）、Err(None) は TypeError（Python は落ちる）。
pub fn py_dict(v: &Value) -> Result<Map<String, Value>, Option<Fail>> {
    let key = |k: &Value| -> Option<String> {
        match k {
            Value::String(s) => Some(s.clone()),
            Value::Array(_) | Value::Object(_) => None, // 辞書の鍵にできない（unhashable）
            other => Some(format!("\u{0}{other}")),     // 字でない鍵は、字の鍵（server など）と重ならない印を付けて持つ
        }
    };
    match v {
        Value::Object(m) => Ok(m.clone()),
        Value::Null => Ok(Map::new()),
        Value::String(s) => match s.chars().next() {
            None => Ok(Map::new()),
            Some(_) => Err(Some("dictionary update sequence element #0 has length 1; 2 is required".into())),
        },
        Value::Array(a) => {
            let mut out = Map::new();
            for (i, e) in a.iter().enumerate() {
                let (k, val): (Value, Value) = match e {
                    Value::Array(p) if p.len() == 2 => (p[0].clone(), p[1].clone()),
                    Value::Array(p) => {
                        return Err(Some(format!("dictionary update sequence element #{i} has length {}; 2 is required", p.len())))
                    }
                    Value::String(t) => {
                        let c: Vec<char> = t.chars().collect();
                        if c.len() != 2 {
                            return Err(Some(format!("dictionary update sequence element #{i} has length {}; 2 is required", c.len())));
                        }
                        (Value::String(c[0].to_string()), Value::String(c[1].to_string()))
                    }
                    Value::Object(o) if o.len() == 2 => {
                        let ks: Vec<&String> = o.keys().collect();
                        (Value::String(ks[0].clone()), Value::String(ks[1].clone()))
                    }
                    Value::Object(o) => {
                        return Err(Some(format!("dictionary update sequence element #{i} has length {}; 2 is required", o.len())))
                    }
                    _ => return Err(None),
                };
                out.insert(key(&k).ok_or(None)?, val);
            }
            Ok(out)
        }
        Value::Bool(false) => Ok(Map::new()),
        Value::Number(n) if n.as_f64() == Some(0.0) => Ok(Map::new()),
        _ => Err(None),
    }
}

/// 画面から直すとき、パスワードを空のまま送れば前のものを使う（同じ利用者IDのときだけ。navi_secret.merge）。
pub fn merge(old: Option<&Value>, new: &Map<String, Value>) -> Map<String, Value> {
    let mut new = new.clone();
    let old = old.filter(|o| pyish::truthy(o)).and_then(Value::as_object);
    if let Some(old) = old {
        let pw_blank = pyish::strip(&pyish::text_or_empty(new.get("password"))).is_empty();
        let same_user = old.get("user").is_some_and(|u| *u == json!(pyish::strip(&pyish::text_or_empty(new.get("user")))));
        if pw_blank && same_user {
            new.insert("password".into(), old.get("password").cloned().unwrap_or(json!("")));
        }
        if !new.contains_key("profiles") {
            let p = old.get("profiles").filter(|p| pyish::truthy(p)).cloned().unwrap_or(json!([]));
            new.insert("profiles".into(), p);
        }
    }
    new
}

/// 画面へ返す形。パスワードは返さない（入っているかどうかだけ。navi_secret.public）。
pub fn public(data: Option<&Value>) -> Map<String, Value> {
    let mut out = Map::new();
    let Some(d) = data.filter(|d| pyish::truthy(d)) else {
        out.insert("saved".into(), json!(false));
        return out;
    };
    let g = |k: &str| d.get(k).cloned().unwrap_or(json!(""));
    out.insert("saved".into(), json!(true));
    for k in ["server", "user", "section", "saved_at", "origin"] {
        out.insert(k.into(), g(k));
    }
    out.insert("has_password".into(), json!(d.get("password").is_some_and(pyish::truthy)));
    let profiles: Vec<Value> = d
        .get("profiles")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .map(|p| json!({"section": p.get("section").cloned().unwrap_or(json!("")), "kind": p.get("kind").cloned().unwrap_or(json!("")), "server": p.get("server").cloned().unwrap_or(json!(""))}))
                .collect()
        })
        .unwrap_or_default();
    out.insert("profiles".into(), Value::Array(profiles));
    out
}

/// 置き場に入れるバイト列（JSON・UTF-8・つなぎの空白なし）。長すぎれば断る。
pub fn encode(data: &Map<String, Value>) -> Result<Vec<u8>, Fail> {
    let blob = serde_json::to_vec(data).map_err(|e| e.to_string())?;
    if blob.len() > BLOB_LIMIT {
        return Err(format!(
            "接続情報が長すぎて保存できません（{} バイト。上限 {BLOB_LIMIT} バイト）。追加のデータソースを減らしてください",
            blob.len()
        ));
    }
    Ok(blob)
}

/// いつ・どこから入れたかを足す（navi_secret.stamp）。
pub fn stamp(mut data: Map<String, Value>, source: &str) -> Map<String, Value> {
    data.insert("saved_at".into(), json!(chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()));
    data.insert("origin".into(), json!(source));
    data
}

// ==== 置き場 ====

pub enum Vault {
    File(PathBuf),
    #[cfg(windows)]
    Windows(String),
}

impl Vault {
    /// このPCでの置き場。試験は NAVI_SECRET_FILE でファイルへ向ける（navi_secret.default_vault）。
    pub fn default_for(local_root: &Path) -> Vault {
        if let Some(p) = std::env::var_os("NAVI_SECRET_FILE").filter(|p| !p.is_empty()) {
            return Vault::File(PathBuf::from(p));
        }
        #[cfg(windows)]
        {
            let _ = local_root;
            Vault::Windows(TARGET.into())
        }
        #[cfg(not(windows))]
        Vault::File(local_root.join("secrets").join("navigator.json"))
    }

    pub fn kind(&self) -> &'static str {
        match self {
            Vault::File(_) => "file",
            #[cfg(windows)]
            Vault::Windows(_) => "windows",
        }
    }

    pub fn place(&self) -> String {
        match self {
            Vault::File(p) => {
                format!("利用者のフォルダーのファイル（暗号化なし・試験用）: {}", crate::paths::py_path(&p.to_string_lossy()))
            }
            #[cfg(windows)]
            Vault::Windows(t) => format!("Windows の資格情報マネージャー（汎用資格情報「{t}」）"),
        }
    }

    pub fn load(&self) -> Result<Option<Value>, Fail> {
        match self {
            Vault::File(p) => match std::fs::read(p) {
                Ok(b) => {
                    let t = String::from_utf8(b).map_err(|e| e.to_string())?;
                    serde_json::from_str(&t).map(Some).map_err(|e| e.to_string())
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
                Err(e) => Err(e.to_string()),
            },
            #[cfg(windows)]
            Vault::Windows(t) => win::load(t),
        }
    }

    pub fn save(&self, data: &Map<String, Value>) -> Result<(), Fail> {
        let blob = encode(data)?;
        match self {
            Vault::File(p) => {
                if let Some(d) = p.parent() {
                    std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
                }
                let tmp = p.with_extension("tmp");
                write_private(&tmp, &blob).map_err(|e| e.to_string())?;
                std::fs::rename(&tmp, p).map_err(|e| e.to_string())
            }
            #[cfg(windows)]
            Vault::Windows(t) => win::save(t, &blob, data.get("user").and_then(Value::as_str).unwrap_or("")),
        }
    }

    pub fn delete(&self) -> Result<bool, Fail> {
        match self {
            Vault::File(p) => match std::fs::remove_file(p) {
                Ok(()) => Ok(true),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
                Err(e) => Err(e.to_string()),
            },
            #[cfg(windows)]
            Vault::Windows(t) => win::delete(t),
        }
    }
}

/// 持ち主だけが読める権限（0600）で書く（Windows 以外）。
fn write_private(path: &Path, blob: &[u8]) -> std::io::Result<()> {
    use std::io::Write;
    let mut o = std::fs::OpenOptions::new();
    o.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    o.open(path)?.write_all(blob)
}

// ==== 「Navigator を使わない」と答えたこと（このPC・利用者ごと） ====

fn declined_path(local_root: &Path) -> PathBuf {
    local_root.join("runtime").join(DECLINED_FILE)
}

pub fn declined(local_root: &Path) -> bool {
    declined_path(local_root).is_file()
}

pub fn decline(local_root: &Path, yes: bool) -> Result<(), Fail> {
    let p = declined_path(local_root);
    if !yes {
        return match std::fs::remove_file(&p) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
            _ => Ok(()),
        };
    }
    if let Some(d) = p.parent() {
        std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
    }
    let when = chrono::Local::now().format("%Y-%m-%dT%H:%M:%S");
    std::fs::write(&p, format!("{{\"declined_at\": \"{when}\"}}")).map_err(|e| e.to_string())
}

/// Windows の資格情報マネージャー（汎用資格情報・このPCに限る）。中身はバイト列のまま渡す（Python も ctypes で同じ）。
#[cfg(windows)]
mod win {
    use super::Fail;
    use serde_json::Value;
    use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND, FILETIME};
    use windows_sys::Win32::Security::Credentials::{
        CredDeleteW, CredFree, CredReadW, CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };
    use windows_sys::Win32::System::Diagnostics::Debug::{FormatMessageW, FORMAT_MESSAGE_FROM_SYSTEM, FORMAT_MESSAGE_IGNORE_INSERTS};

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Python の OSError(code, msg) の str（[Errno n] …）と同じ形。説明は ctypes.FormatError と同じく FormatMessageW。
    fn fail(what: &str) -> Fail {
        let code = unsafe { GetLastError() };
        let mut buf = [0u16; 512];
        let n = unsafe {
            FormatMessageW(
                FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                std::ptr::null(),
                code,
                0,
                buf.as_mut_ptr(),
                buf.len() as u32,
                std::ptr::null(),
            )
        };
        let msg = String::from_utf16_lossy(&buf[..n as usize]).trim().to_string();
        format!("[Errno {code}] {what}に失敗しました（Windows のエラー {code}: {msg}）")
    }

    pub fn load(target: &str) -> Result<Option<Value>, Fail> {
        let t = wide(target);
        let mut p: *mut CREDENTIALW = std::ptr::null_mut();
        if unsafe { CredReadW(t.as_ptr(), CRED_TYPE_GENERIC, 0, &mut p) } == 0 {
            if unsafe { GetLastError() } == ERROR_NOT_FOUND {
                return Ok(None);
            }
            return Err(fail("資格情報の読み取り"));
        }
        let blob = unsafe {
            let c = &*p;
            let b = std::slice::from_raw_parts(c.CredentialBlob, c.CredentialBlobSize as usize).to_vec();
            CredFree(p as *const _);
            b
        };
        let text = String::from_utf8(blob).map_err(|e| e.to_string())?;
        serde_json::from_str(&text).map(Some).map_err(|e| e.to_string())
    }

    pub fn save(target: &str, blob: &[u8], user: &str) -> Result<(), Fail> {
        let (mut t, mut comment, mut name) =
            (wide(target), wide("DataRelay: Navigator への接続情報（アプリの画面から登録・変更します）"), wide(user));
        let mut blob = blob.to_vec();
        let cred = CREDENTIALW {
            Flags: 0,
            Type: CRED_TYPE_GENERIC,
            TargetName: t.as_mut_ptr(),
            Comment: comment.as_mut_ptr(),
            LastWritten: FILETIME { dwLowDateTime: 0, dwHighDateTime: 0 },
            CredentialBlobSize: blob.len() as u32,
            CredentialBlob: blob.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount: 0,
            Attributes: std::ptr::null_mut(),
            TargetAlias: std::ptr::null_mut(),
            UserName: name.as_mut_ptr(),
        };
        if unsafe { CredWriteW(&cred, 0) } == 0 {
            return Err(fail("資格情報の保存"));
        }
        Ok(())
    }

    pub fn delete(target: &str) -> Result<bool, Fail> {
        let t = wide(target);
        if unsafe { CredDeleteW(t.as_ptr(), CRED_TYPE_GENERIC, 0) } == 0 {
            if unsafe { GetLastError() } == ERROR_NOT_FOUND {
                return Ok(false);
            }
            return Err(fail("資格情報の削除"));
        }
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conf_like_python() {
        let t =
            "[Default]\nSymNaviServer = srv:1\nSymNaviUSERID=u\nSymNaviPASSWD = p ;x\n\n[ApiOracle]\nuser = o\npasswd = op\nserver = ora\n";
        let d = parse_conf(t).unwrap();
        assert_eq!(
            (d["server"].clone(), d["user"].clone(), d["password"].clone()),
            (json!("srv:1"), json!("u"), json!("p ;x")),
            "行の途中の ; は注記ではない"
        );
        assert_eq!(d["profiles"][0]["kind"], "oracle");
        assert_eq!(d["profiles"][0]["password"], "op");
        let e = parse_conf("[A]\nx=1\n").unwrap_err();
        assert_eq!(conf_error(e), "[A]にSymNaviUSERID、SymNaviPASSWD、SymNaviServerが必要です");
        assert!(matches!(parse_conf("[A]\nx=1\n[A]\n"), Err(Ok(_))), "同じセクションが2回は誤り");
        assert!(matches!(parse_conf("x=1\n"), Err(Ok(_))), "見出しより前の値は誤り");
        assert_eq!(conf_error(parse_conf("").unwrap_err()), "symnavim.confを読み取れません");
    }

    #[test]
    fn continuation_and_defaults() {
        let ini = Ini::parse("[DEFAULT]\na = 1\n[S]\nb = x\n  y\n\n  z\n").unwrap();
        assert_eq!(ini.items("S"), vec![("a".into(), "1".into()), ("b".into(), "x\ny\n\nz".into())]);
    }

    #[test]
    fn clean_and_merge() {
        assert_eq!(clean(&json!({"server": " s ", "user": "u"})), Err(Some("パスワードを入れてください".into())));
        assert_eq!(clean(&json!({})), Err(Some("サーバー、利用者ID、パスワードを入れてください".into())));
        assert_eq!(clean(&json!({"server": "s", "user": "u", "password": "p", "profiles": 5})), Err(None));
        let old = json!({"server": "s", "user": "u", "password": "old", "profiles": [{"kind": "oracle"}]});
        let m = merge(Some(&old), json!({"server": "s2", "user": "u", "password": ""}).as_object().unwrap());
        assert_eq!((m["password"].clone(), m["profiles"][0]["kind"].clone()), (json!("old"), json!("oracle")));
        let m = merge(Some(&old), json!({"user": "other"}).as_object().unwrap());
        assert!(m.get("password").is_none(), "利用者IDが違えば前のパスワードは使わない");
    }

    #[test]
    fn file_vault_roundtrip() {
        let d = std::env::temp_dir().join(format!("dr-secret-{}", std::process::id()));
        let v = Vault::File(d.join("s").join("navigator.json"));
        assert_eq!(v.load(), Ok(None));
        let data = clean(&json!({"server": "s", "user": "ユーザー", "password": "p"})).unwrap();
        v.save(&data).unwrap();
        assert_eq!(v.load().unwrap().unwrap()["user"], "ユーザー");
        assert_eq!(v.delete(), Ok(true));
        assert_eq!(v.delete(), Ok(false));
        let big = clean(&json!({"server": "s".repeat(3000), "user": "u", "password": "p"})).unwrap();
        assert!(v.save(&big).unwrap_err().contains("長すぎて"));
        std::fs::remove_dir_all(&d).ok();
    }
}
