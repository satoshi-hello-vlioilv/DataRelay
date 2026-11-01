//! PC ごとに実体が変わる場所の決まり（lib/navi_paths.py・navi_release.py の置き場の決め方と同じ答え。2.16.0 で移した）。
//!
//! 窓（desktop/src/release.rs・locate.rs）もここを使う（置き場・入れたかの見分けを2か所で持たない）。
//! Python の Path・os.path と同じ字になるよう、道の書き方（区切り・`.`・末尾の区切り）と、`resolve()`（在る所までは
//! 実体へ・無い所は字のまま）をここで真似る。Windows と Linux（手元の試験）で同じ決まりを、それぞれの OS の流儀で。

use crate::pyish;
use serde_json::{json, Map, Value};
use std::path::{Component, Path, PathBuf};

pub const CONFIG_KEY: &str = "update_dir";
pub const LOCAL: &str = "local.json";
pub const MIRROR: &str = "update.json";
pub const SEED: &str = "install.json";
pub const DATA_KEY: &str = "data_root";
pub const FROM_KEY: &str = "from";
pub const VERSIONS: &str = "versions";
/// 写しの中の、この PC のデータ（版の入れ替えでは触らない）
pub const DATA_DIR: &str = "data";
/// 手元のデータとして使い始めた印
pub const DATA_MARK: &str = "data.json";
pub const USERS_DIR: &str = "users";
pub const USERS_KEY: &str = "users_root";
pub const PC_TOKEN: &str = "<PC>";
/// 相対パスを「相対パスの基準から」と明示する書き出し
pub const EXPLICIT_RELATIVE: [&str; 4] = [".\\", "..\\", "./", "../"];
/// 人が決めたデータの基準（このときはデータの基準を置き場より先に見る）
pub const EXPLICIT_DATA: [&str; 2] = ["local", "env"];

const WINDOWS: bool = cfg!(windows);

// ==== 小さな設定ファイルと環境変数 ======================================

/// 小さな設定ファイル（JSON の辞書）を読む。BOM は外す。無い・読めない・辞書でないなら Null。
pub fn read_json(path: &Path) -> Value {
    std::fs::read(path)
        .ok()
        .and_then(|b| serde_json::from_slice::<Value>(b.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&b)).ok())
        .filter(Value::is_object)
        .unwrap_or(Value::Null)
}

/// `str(read_json(path).get(key) or '').strip()`。
fn json_text(path: &Path, key: &str) -> String {
    pyish::strip(&pyish::text_or_empty(read_json(path).get(key))).to_string()
}

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

fn home() -> PathBuf {
    let h = if WINDOWS { env("USERPROFILE").or_else(|| env("HOME")) } else { env("HOME").or_else(|| env("USERPROFILE")) };
    PathBuf::from(h.unwrap_or_else(|| ".".into()))
}

/// `%NAME%` と `$NAME` と `~` を展開する（navi_paths.expand）。`%NAME%` は Windows 以外でも展開する。定義されていない名前はそのまま残す。
pub fn expand(value: &str) -> String {
    let raw = expand_percent(pyish::strip(value));
    let raw = expand_user(&raw);
    if WINDOWS {
        expand_vars_nt(&raw)
    } else {
        expand_vars_posix(&raw)
    }
}

/// `%NAME%` だけを展開する（正規表現 `%([^%]+)%` と同じ当て方）。
pub fn expand_percent(s: &str) -> String {
    let mut out = String::new();
    let mut rest = s;
    while let Some(i) = rest.find('%') {
        out.push_str(&rest[..i]);
        let tail = &rest[i + 1..];
        match tail.find('%') {
            Some(0) => {
                // "%%" は名前が空なので当たらない。1文字進めて、2つ目の % から探し直す
                out.push('%');
                rest = tail;
            }
            Some(j) => {
                let name = &tail[..j];
                match env(name) {
                    Some(v) => out.push_str(&v),
                    None => out.push_str(&rest[i..i + j + 2]),
                }
                rest = &tail[j + 1..];
            }
            None => {
                out.push_str(&rest[i..]);
                rest = "";
            }
        }
    }
    out.push_str(rest);
    out
}

/// os.path.expanduser（先頭の `~` と、その直後が区切りか終わりのときだけ。`~名前` は変えない）。
fn expand_user(s: &str) -> String {
    let Some(rest) = s.strip_prefix('~') else { return s.to_string() };
    let sep_next = rest.is_empty() || rest.starts_with('/') || (WINDOWS && rest.starts_with('\\'));
    if !sep_next {
        return s.to_string();
    }
    let h = if WINDOWS {
        home().to_string_lossy().into_owned()
    } else {
        match env("HOME") {
            Some(h) => h,
            None => return s.to_string(),
        }
    };
    let h = if !WINDOWS && h != "/" { h.trim_end_matches('/').to_string() } else { h };
    let joined = format!("{h}{rest}");
    if joined.is_empty() {
        "/".into()
    } else {
        joined
    }
}

/// posixpath.expandvars: `$name`・`${name}`（name は ASCII の英数字と _）。無い名前はそのまま。
fn expand_vars_posix(s: &str) -> String {
    if !s.contains('$') {
        return s.to_string();
    }
    let b: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] != '$' {
            out.push(b[i]);
            i += 1;
            continue;
        }
        let (name, end) = if b.get(i + 1) == Some(&'{') {
            match b[i + 2..].iter().position(|&c| c == '}') {
                Some(j) => (b[i + 2..i + 2 + j].iter().collect::<String>(), i + 3 + j),
                None => (String::new(), i + 1),
            }
        } else {
            let n = b[i + 1..].iter().take_while(|c| c.is_ascii_alphanumeric() || **c == '_').count();
            (b[i + 1..i + 1 + n].iter().collect(), i + 1 + n)
        };
        match (name.is_empty(), env(&name)) {
            (false, Some(v)) => {
                out.push_str(&v);
                i = end;
            }
            _ => {
                // 当たらなければ、その $ をそのまま出して次の字から探し直す（Python と同じ）
                out.push('$');
                i += 1;
            }
        }
    }
    out
}

/// ntpath.expandvars: `'…'` の中はそのまま・`%%`→`%`・`%name%`・`$$`→`$`・`${name}`・`$name`（英数字・_・-）。
fn expand_vars_nt(s: &str) -> String {
    if !s.contains('$') && !s.contains('%') {
        return s.to_string();
    }
    let b: Vec<char> = s.chars().collect();
    let var_char = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '-';
    let mut out = String::new();
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        match c {
            '\'' => match b[i + 1..].iter().position(|&x| x == '\'') {
                Some(j) => {
                    out.extend(&b[i..=i + 1 + j]);
                    i += j + 2;
                }
                None => {
                    out.extend(&b[i..]);
                    i = b.len();
                }
            },
            '%' => {
                if b.get(i + 1) == Some(&'%') {
                    out.push('%');
                    i += 2;
                } else {
                    match b[i + 1..].iter().position(|&x| x == '%') {
                        Some(j) => {
                            let name: String = b[i + 1..i + 1 + j].iter().collect();
                            match env(&name) {
                                Some(v) => out.push_str(&v),
                                None => out.push_str(&format!("%{name}%")),
                            }
                            i += j + 2;
                        }
                        None => {
                            out.extend(&b[i..]);
                            i = b.len();
                        }
                    }
                }
            }
            '$' => {
                if b.get(i + 1) == Some(&'$') {
                    out.push('$');
                    i += 2;
                } else if b.get(i + 1) == Some(&'{') {
                    match b[i + 2..].iter().position(|&x| x == '}') {
                        Some(j) => {
                            let name: String = b[i + 2..i + 2 + j].iter().collect();
                            match env(&name) {
                                Some(v) => out.push_str(&v),
                                None => out.push_str(&format!("${{{name}}}")),
                            }
                            i += j + 3;
                        }
                        None => {
                            out.extend(&b[i..]);
                            i = b.len();
                        }
                    }
                } else {
                    let n = b[i + 1..].iter().take_while(|c| var_char(**c)).count();
                    let name: String = b[i + 1..i + 1 + n].iter().collect();
                    match (n, env(&name)) {
                        (0, _) => out.push('$'),
                        (_, Some(v)) => out.push_str(&v),
                        (_, None) => out.push_str(&format!("${name}")),
                    }
                    i += 1 + n;
                }
            }
            _ => {
                out.push(c);
                i += 1;
            }
        }
    }
    out
}

// ==== Python の Path と同じ字 ===========================================

/// `str(Path(s))`。区切りをそろえ（Windows は \）、重なった区切り・`.` の段・末尾の区切りを落とす。`..` は残す。
pub fn py_path(s: &str) -> String {
    if s.is_empty() {
        return ".".into();
    }
    if WINDOWS {
        let s = s.replace('/', "\\");
        let (prefix, rest) = split_root_nt(&s);
        let parts: Vec<&str> = rest.split('\\').filter(|x| !x.is_empty() && *x != ".").collect();
        let body = parts.join("\\");
        if prefix.is_empty() && body.is_empty() {
            ".".into()
        } else {
            format!("{prefix}{body}")
        }
    } else {
        let lead = if s.starts_with("//") && !s.starts_with("///") {
            "//"
        } else if s.starts_with('/') {
            "/"
        } else {
            ""
        };
        let parts: Vec<&str> = s.split('/').filter(|x| !x.is_empty() && *x != ".").collect();
        let body = parts.join("/");
        if lead.is_empty() && body.is_empty() {
            ".".into()
        } else {
            format!("{lead}{body}")
        }
    }
}

/// Windows の道を（ドライブか UNC の根, 残り）に分ける。根は区切りで終わる（`C:\`・`\\srv\share\`・`\`）。`C:x` の根は `C:`。
fn split_root_nt(s: &str) -> (String, &str) {
    if let Some(rest) = s.strip_prefix("\\\\") {
        // \\server\share\…
        let mut it = rest.splitn(3, '\\');
        let server = it.next().unwrap_or("");
        let share = it.next().unwrap_or("");
        let tail = it.next().unwrap_or("");
        if !server.is_empty() && !share.is_empty() {
            return (format!("\\\\{server}\\{share}\\"), tail);
        }
        return ("\\\\".into(), rest);
    }
    let b = s.as_bytes();
    if b.len() >= 2 && b[1] == b':' && b[0].is_ascii_alphabetic() {
        if b.get(2) == Some(&b'\\') {
            return (format!("{}\\", &s[..2]), &s[3..]);
        }
        return (s[..2].to_string(), &s[2..]);
    }
    if let Some(rest) = s.strip_prefix('\\') {
        return ("\\".into(), rest);
    }
    (String::new(), s)
}

fn sep() -> char {
    if WINDOWS {
        '\\'
    } else {
        '/'
    }
}

/// 道の字を比べる（Windows は大文字小文字を区別しない・Python の Path の == と同じ）。
pub fn same_text(a: &str, b: &str) -> bool {
    if WINDOWS {
        a.to_lowercase() == b.to_lowercase()
    } else {
        a == b
    }
}

/// `Path(a) / b`。b が絶対なら b。Windows で b が根だけ（`\x`）なら a のドライブに付け、別のドライブ（`D:x`）なら b。
pub fn join(a: &str, b: &str) -> String {
    let bp = py_path(b);
    if b.is_empty() {
        return py_path(a);
    }
    if a.is_empty() || a == "." {
        return bp;
    }
    if WINDOWS {
        let (root_b, rest_b) = split_root_nt(&bp);
        if root_b.len() > 1 && root_b.ends_with('\\') {
            return bp; // ドライブか UNC の付いた絶対
        }
        let (root_a, _) = split_root_nt(a);
        if root_b == "\\" {
            return py_path(&format!("{}\\{rest_b}", root_a.trim_end_matches('\\')));
        }
        if !root_b.is_empty() {
            // C:x（ドライブだけ）。同じドライブなら a に付け、違えば b
            if !same_text(&root_b, root_a.trim_end_matches('\\')) {
                return bp;
            }
            return py_path(&format!("{a}\\{rest_b}"));
        }
        return py_path(&format!("{a}\\{bp}"));
    }
    if bp.starts_with('/') {
        return bp;
    }
    py_path(&format!("{a}/{bp}"))
}

/// Path.is_absolute()（Windows は根とドライブの両方が要る。`\x` は絶対ではない）。
pub fn is_absolute(p: &str) -> bool {
    if WINDOWS {
        let (root, _) = split_root_nt(p);
        root.len() > 1 && root.ends_with('\\')
    } else {
        p.starts_with('/')
    }
}

/// os.path.abspath（いまのフォルダーに付けて、字のまま正規化する。`..` も字で畳む）。
fn abspath(p: &str) -> String {
    let full = if is_absolute(p) {
        p.to_string()
    } else {
        let cwd = std::env::current_dir().map(|c| c.to_string_lossy().into_owned()).unwrap_or_else(|_| ".".into());
        if WINDOWS && p.starts_with('\\') && !p.starts_with("\\\\") {
            let (root, _) = split_root_nt(&cwd);
            format!("{}{}", root.trim_end_matches('\\'), p)
        } else {
            format!("{cwd}{}{p}", sep())
        }
    };
    normpath(&full)
}

/// os.path.normpath（`..` を字で畳む）。
pub fn normpath(p: &str) -> String {
    let p = py_path(p);
    let (root, rest) = if WINDOWS {
        let (r, rest) = split_root_nt(&p);
        (r, rest.to_string())
    } else if let Some(r) = p.strip_prefix("//") {
        ("//".into(), r.to_string())
    } else if let Some(r) = p.strip_prefix('/') {
        ("/".into(), r.to_string())
    } else {
        (String::new(), p.clone())
    };
    let mut out: Vec<&str> = Vec::new();
    for part in rest.split(sep()).filter(|x| !x.is_empty() && *x != ".") {
        if part == ".." {
            if out.last().is_some_and(|x| *x != "..") {
                out.pop();
                continue;
            }
            if root.ends_with(sep()) {
                continue; // 根より上へは行かない
            }
        }
        out.push(part);
    }
    let body = out.join(&sep().to_string());
    if root.is_empty() && body.is_empty() {
        ".".into()
    } else {
        format!("{root}{body}")
    }
}

/// OS が答える実体の道（Windows は \\?\ を外す。UNC は \\?\UNC\ → \\）。
fn canonical(p: &Path) -> Option<String> {
    let c = std::fs::canonicalize(p).ok()?.to_string_lossy().into_owned();
    Some(if let Some(rest) = c.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else if let Some(rest) = c.strip_prefix(r"\\?\") {
        rest.to_string()
    } else {
        c
    })
}

/// `Path(p).resolve()`（strict でない）。Windows は先に字で畳み、在る所までを実体へ直して、残りを付ける。
/// Linux は段ごとに、在る段は実体へ（リンクをたどる）、無い段からは字のまま。
pub fn resolve(p: &str) -> String {
    if WINDOWS {
        let full = abspath(p);
        let mut head = full.clone();
        let mut tail: Vec<String> = Vec::new();
        loop {
            if let Some(c) = canonical(Path::new(&head)) {
                let mut out = c;
                for t in tail.iter().rev() {
                    out = format!("{}\\{}", out.trim_end_matches('\\'), t);
                }
                return out;
            }
            let (root, rest) = split_root_nt(&head);
            if rest.is_empty() {
                return full;
            }
            match rest.rfind('\\') {
                Some(i) => {
                    tail.push(rest[i + 1..].to_string());
                    head = format!("{root}{}", &rest[..i]);
                }
                None => {
                    tail.push(rest.to_string());
                    head = root;
                }
            }
        }
    } else {
        let start = if p.starts_with('/') { PathBuf::from("/") } else { std::env::current_dir().unwrap_or_else(|_| PathBuf::from("/")) };
        let mut cur = start;
        for comp in Path::new(&py_path(p)).components() {
            match comp {
                Component::RootDir | Component::Prefix(_) | Component::CurDir => {}
                Component::ParentDir => {
                    cur.pop();
                }
                Component::Normal(n) => {
                    cur.push(n);
                    // リンクなら実体へ（無い段・壊れたリンクは字のまま。Python の realpath と同じ）
                    if std::fs::symlink_metadata(&cur).is_ok_and(|m| m.file_type().is_symlink()) {
                        if let Ok(c) = std::fs::canonicalize(&cur) {
                            cur = c;
                        }
                    }
                }
            }
        }
        cur.to_string_lossy().into_owned()
    }
}

/// os.path.relpath(target, start)。別のドライブ・別の UNC の共有なら None（Python は ValueError）。
pub fn relpath(target: &str, start: &str) -> Option<String> {
    let (t, s) = (abspath(target), abspath(start));
    let split = |p: &str| -> (String, Vec<String>) {
        if WINDOWS {
            let (root, rest) = split_root_nt(p);
            (root, rest.split('\\').filter(|x| !x.is_empty()).map(String::from).collect())
        } else {
            ("/".into(), p.split('/').filter(|x| !x.is_empty()).map(String::from).collect())
        }
    };
    let (tr, tp) = split(&t);
    let (sr, sp) = split(&s);
    if !same_text(&tr, &sr) {
        return None;
    }
    let common = tp.iter().zip(sp.iter()).take_while(|(a, b)| same_text(a, b)).count();
    let mut parts: Vec<String> = std::iter::repeat_n("..".to_string(), sp.len() - common).collect();
    parts.extend(tp[common..].iter().cloned());
    Some(if parts.is_empty() { ".".into() } else { parts.join(&sep().to_string()) })
}

/// `Path(path).relative_to(root)`（どちらも resolve 済みの字）。外なら None。
fn relative_to(path: &str, root: &str) -> Option<String> {
    let (p, r) = (py_path(path), py_path(root));
    let s = sep();
    if same_text(&p, &r) {
        return Some(".".into());
    }
    let r2 = if r.ends_with(s) { r.clone() } else { format!("{r}{s}") };
    if p.len() > r2.len() && same_text(&p[..r2.len()], &r2) {
        Some(p[r2.len()..].to_string())
    } else {
        None
    }
}

fn exists(p: &str) -> bool {
    Path::new(p).exists()
}

// ==== 置き場（navi_release.dir_choice・place_root） ======================

/// 版の字として使えるか（数字で始まり、英数字・点・ハイフンだけ・41字まで）。道に混ぜる前に確かめる。
pub fn safe_version(v: &str) -> bool {
    !v.is_empty()
        && v.len() <= 41
        && v.starts_with(|c: char| c.is_ascii_digit())
        && v.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
}

/// 配布の置き場から写したアプリか（窓が `config\install.json` を書く）。
pub fn installed(app_root: &Path) -> bool {
    app_root.join("config").join(SEED).is_file()
}

/// 置き場として渡された場所を、`versions` が直下に並ぶ置き場の根へ直す（navi_release.release_root）。
/// `…\versions` → その親、`…\versions\<版>` → 2つ上。それ以外はそのまま。
pub fn release_root(p: &Path) -> PathBuf {
    // 親が空（相対の `versions` だけ）なら、Python の Path と同じく `.` とみなす
    let parent = |q: &Path| q.parent().map(|u| if u.as_os_str().is_empty() { PathBuf::from(".") } else { u.to_path_buf() });
    let named = |q: &Path, s: &str| q.file_name().and_then(|n| n.to_str()).is_some_and(|n| n.eq_ignore_ascii_case(s));
    if named(p, VERSIONS) {
        if let Some(up) = parent(p) {
            return up;
        }
    }
    if let (Some(name), Some(up)) = (p.file_name().and_then(|n| n.to_str()), parent(p)) {
        if safe_version(name) && named(&up, VERSIONS) {
            if let Some(root) = parent(&up) {
                return root;
            }
        }
    }
    p.to_path_buf()
}

/// 置き場と出どころ。`config\local.json`（この PC だけの上書き）→ 共有の設定（`shared`。None なら控えの `config\update.json`）→
/// `config\install.json` の `from`（この PC を入れた元）→ アプリのフォルダー（navi_release.dir_choice・place_root）。
pub fn update_dir_with(app_root: &Path, shared: Option<&str>) -> (PathBuf, &'static str) {
    let conf = app_root.join("config");
    let local = json_text(&conf.join(LOCAL), CONFIG_KEY);
    if !local.is_empty() {
        return (release_root(&PathBuf::from(py_path(&expand(&local)))), "local");
    }
    let shared = match shared {
        Some(s) => pyish::strip(s).to_string(),
        None => json_text(&conf.join(MIRROR), CONFIG_KEY),
    };
    if !shared.is_empty() {
        return (release_root(&PathBuf::from(py_path(&expand(&shared)))), "shared");
    }
    let origin = json_text(&conf.join(SEED), FROM_KEY);
    if !origin.is_empty() {
        return (release_root(&PathBuf::from(py_path(&expand(&origin)))), "install");
    }
    (release_root(app_root), "app")
}

/// 置き場と出どころ（共有の設定は控えの `config\update.json` から）。窓が Python を起こす前にも使う。
pub fn update_dir(app_root: &Path) -> (PathBuf, &'static str) {
    update_dir_with(app_root, None)
}

// ==== このPC・データの基準・ユーザーごとのデータ ========================

/// この PC の作業場所（NAVI_LOCAL_ROOT、無ければ %LOCALAPPDATA%\DataRelay、無ければ %TEMP%・ホーム）。
pub fn local_root() -> PathBuf {
    if let Some(p) = std::env::var_os("NAVI_LOCAL_ROOT") {
        return PathBuf::from(p);
    }
    let base = std::env::var_os("LOCALAPPDATA").or_else(|| std::env::var_os("TEMP")).map(PathBuf::from).unwrap_or_else(home);
    base.join("DataRelay")
}

/// 環境の読み口（試験で差し替える。Python の data_root(…, env=…) と同じ）。
pub type Env<'a> = &'a dyn Fn(&str) -> Option<String>;

/// 本物の環境変数。
pub fn real_env(name: &str) -> Option<String> {
    env(name)
}

/// Windows のログオン名（フォルダー名に使えない字は _ に）。分からなければ空。
pub fn logon_name(env: Env) -> String {
    let raw = env("USERNAME").filter(|v| !v.is_empty()).or_else(|| env("USER")).unwrap_or_default();
    let raw = pyish::strip(&raw);
    let mut out = String::new();
    let mut in_bad = false;
    for c in raw.chars() {
        if "\\/:*?\"<>|".contains(c) {
            if !in_bad {
                out.push('_');
            }
            in_bad = true;
        } else {
            out.push(c);
            in_bad = false;
        }
    }
    out.trim_matches(|c| c == '.' || c == ' ').to_string()
}

/// ユーザーごとのデータを置くフォルダー。置き場の `config\install.json` の users_root、無ければ `<置き場>\users`。
pub fn users_root(place: &Path) -> PathBuf {
    let value = json_text(&place.join("config").join(SEED), USERS_KEY);
    if value.is_empty() {
        PathBuf::from(join(&place.to_string_lossy(), USERS_DIR))
    } else {
        PathBuf::from(py_path(&expand(&value)))
    }
}

/// このユーザーのデータのフォルダー。置き場が届かない・ログオン名が分からないなら None。
pub fn user_dir(place: Option<&Path>, env: Env) -> Option<PathBuf> {
    let name = logon_name(env);
    let place = place.filter(|p| !p.as_os_str().is_empty())?;
    if name.is_empty() || !place.is_dir() {
        return None;
    }
    Some(PathBuf::from(join(&users_root(place).to_string_lossy(), &name)))
}

/// データの基準と出どころ（env／local／user／pc／install／app）。navi_paths.data_root と同じ決める順。
pub fn data_root(base: &Path, env: Env, place: Option<&Path>) -> (PathBuf, &'static str) {
    let b = base.to_string_lossy();
    if let Some(v) = env("NAVI_DATA_ROOT").filter(|v| !pyish::strip(v).is_empty()) {
        return (PathBuf::from(py_path(&expand(&v))), "env");
    }
    let conf = base.join("config");
    let value = json_text(&conf.join(LOCAL), DATA_KEY);
    if !value.is_empty() {
        return (PathBuf::from(py_path(&expand(&value))), "local");
    }
    if conf.join(SEED).is_file() {
        let mine = PathBuf::from(join(&b, DATA_DIR));
        let seed = json_text(&conf.join(SEED), DATA_KEY);
        if let Some(you) = user_dir(place, env) {
            if you.join(DATA_MARK).is_file() || !(mine.join(DATA_MARK).is_file() || !seed.is_empty()) {
                return (you, "user");
            }
        }
        if mine.join(DATA_MARK).is_file() {
            return (mine, "pc");
        }
        if !seed.is_empty() {
            return (PathBuf::from(py_path(&expand(&seed))), "install");
        }
        return (mine, "pc");
    }
    (PathBuf::from(py_path(&b)), "app")
}

/// 書き方の種類。'empty'・'pc'（<PC>\…）・'env'（%NAME%・~・$ で始まる）・'unc'（\\サーバー\…）・'abs'（C:\… ／ / ／ \…）・'rel'。
pub fn path_kind(value: &str) -> &'static str {
    let raw = pyish::strip(value);
    if raw.is_empty() {
        return "empty";
    }
    if raw.starts_with(PC_TOKEN) {
        return "pc";
    }
    let starts_env = raw.starts_with('~') || raw.starts_with('$') || (raw.starts_with('%') && raw[1..].find('%').is_some_and(|j| j > 0));
    if starts_env {
        return "env";
    }
    if raw.starts_with("\\\\") {
        return "unc";
    }
    let b = raw.as_bytes();
    let drive = b.len() >= 3 && b[0].is_ascii_alphabetic() && b[1] == b':' && (b[2] == b'\\' || b[2] == b'/');
    if drive || raw.starts_with('/') || raw.starts_with('\\') {
        return "abs";
    }
    "rel"
}

/// 利用者プロファイルの根（C:\Users\<誰か>）。無ければ None。
fn profile_root(p: &str) -> Option<String> {
    let parts: Vec<&str> = p.split(['\\', '/']).filter(|x| !x.is_empty()).collect();
    for (i, x) in parts.iter().enumerate() {
        if ["users", "ユーザー", "documents and settings"].contains(&x.to_lowercase().as_str()) && i + 1 < parts.len() {
            return Some(parts[..i + 2].join("\\"));
        }
    }
    None
}

/// 自分のプロファイルの下を指すパスを %USERPROFILE%\… へ直す（共有の設定・新しい PC へ渡す値に書く前に通す）。
pub fn portable(value: &str, home_dir: Option<&Path>) -> String {
    let raw = pyish::strip(value);
    if raw.is_empty() || raw.starts_with('%') {
        return raw.to_string();
    }
    let h = home_dir.map(Path::to_path_buf).unwrap_or_else(home);
    let hs = h.to_string_lossy();
    let mine = profile_root(&hs).unwrap_or_else(|| hs.split(['\\', '/']).filter(|x| !x.is_empty()).collect::<Vec<_>>().join("\\"));
    let Some(root) = profile_root(raw) else { return raw.to_string() };
    if root.to_lowercase() != mine.to_lowercase() {
        return raw.to_string();
    }
    let parts: Vec<&str> = raw.split(['\\', '/']).filter(|x| !x.is_empty()).collect();
    let n = root.split('\\').count();
    std::iter::once("%USERPROFILE%").chain(parts[n..].iter().copied()).collect::<Vec<_>>().join("\\")
}

// ==== 相対パスの基準と、道の読み方（navi_paths.setup・set_place のあと） ====

/// 基準になる場所。Python の navi_paths の DATA_ROOT・LOCAL_ROOT・PROGRAM_ROOT・DATA_SOURCE・PLACE_ROOT に当たる。
#[derive(Debug, Clone)]
pub struct Bases {
    pub data_root: String,
    pub data_source: String,
    pub local_root: String,
    pub program_root: String,
    pub place: Option<String>,
}

/// 画面・知らせの言葉（navi_paths.BASE_LABEL）。
pub fn base_label(key: &str) -> &'static str {
    match key {
        "place" => "置き場",
        "data" => "データの基準",
        "app" => "アプリの場所",
        "local" => "このPC",
        _ => "",
    }
}

impl Bases {
    /// 起動したときと同じ決め方で（アプリの場所から）。置き場は控え（update.json）から読む。
    pub fn detect(program_root: &Path) -> Bases {
        let (place, _) = update_dir(program_root);
        let (data, source) = data_root(program_root, &real_env, Some(&place));
        Bases {
            data_root: data.to_string_lossy().into_owned(),
            data_source: source.into(),
            local_root: py_path(&local_root().to_string_lossy()),
            program_root: py_path(&program_root.to_string_lossy()),
            place: Some(py_path(&place.to_string_lossy())),
        }
    }

    /// 相対パスを読む基準の順（先頭が主）。同じ場所は1度だけ。
    pub fn rel_bases(&self) -> Vec<String> {
        let (d, p) = (Some(self.data_root.clone()), Some(self.program_root.clone()));
        let order: Vec<Option<String>> = if EXPLICIT_DATA.contains(&self.data_source.as_str()) {
            vec![d, p]
        } else if self.place.is_some() {
            vec![self.place.clone(), d, p]
        } else if self.data_source == "install" {
            vec![p, d]
        } else {
            vec![d, p]
        };
        let mut out: Vec<String> = Vec::new();
        for x in order.into_iter().flatten() {
            if !out.iter().any(|o| same_text(o, &x)) {
                out.push(x);
            }
        }
        if out.is_empty() {
            out.push(self.data_root.clone());
        }
        out
    }

    pub fn rel_root(&self) -> String {
        self.rel_bases().remove(0)
    }

    /// 相対の道を基準の順に探す。→ (使う道, 見つかった基準の番号, 探した道)。どこにも無ければ主な基準の道。
    fn search(&self, p: &str) -> (String, usize, Vec<String>) {
        let tried: Vec<String> = self.rel_bases().iter().map(|b| resolve(&join(b, p))).collect();
        for (i, x) in tried.iter().enumerate() {
            if exists(x) {
                return (x.clone(), i, tried);
            }
        }
        (tried[0].clone(), 0, tried)
    }

    /// 設定の道を読む（navi_paths.resolve_path）。`base` を渡したときは、その基準だけを見る。`value` が None なら基準そのもの。
    pub fn resolve_path(&self, value: Option<&str>, base: Option<&str>) -> String {
        let default = base.is_none();
        let base = base.map(String::from).unwrap_or_else(|| self.rel_root());
        let Some(value) = value else { return base };
        let raw = pyish::strip(value);
        if let Some(rest) = raw.strip_prefix(PC_TOKEN) {
            let rest = pyish::strip(rest).trim_start_matches(['\\', '/']);
            return if rest.is_empty() { self.local_root.clone() } else { join(&self.local_root, rest) };
        }
        let mut raw = expand(raw);
        if raw.starts_with("\\\\") {
            return py_path(&raw);
        }
        if !WINDOWS {
            raw = raw.replace('\\', "/");
        }
        let p = py_path(&raw);
        if is_absolute(&p) || raw.starts_with('\\') {
            return p;
        }
        if !default {
            return resolve(&join(&base, &p));
        }
        self.search(&p).0
    }

    /// 基準の場所の名前（同じ場所なら置き場を先に名乗る）。
    fn base_key(&self, root: &str) -> &'static str {
        let r = resolve(root);
        for (key, x) in [("place", self.place.clone()), ("data", Some(self.data_root.clone())), ("app", Some(self.program_root.clone()))] {
            if let Some(x) = x {
                if same_text(&resolve(&x), &r) {
                    return key;
                }
            }
        }
        "place"
    }

    fn tail(&self, path: &str, root: &str) -> String {
        match relative_to(&resolve(path), &resolve(root)) {
            Some(rel) if rel == "." => "\\".into(),
            Some(rel) => format!("\\{}", rel.replace('/', "\\")),
            None => path.to_string(),
        }
    }

    /// 設定値が、どこの物を指すのか（navi_paths.locate）。`folder` を渡すと、名前だけの指定はそのフォルダーの中として読む。
    pub fn locate(&self, value: &str, folder: Option<&str>) -> Map<String, Value> {
        let mut out = self.locate_raw(value, folder);
        let label = base_label(out["base"].as_str().unwrap_or(""));
        let primary = base_label(out["primary"].as_str().unwrap_or(""));
        let fell = out["fell"].as_bool().unwrap_or(false);
        out.insert("label".into(), json!(label));
        out.insert("primary_label".into(), json!(primary));
        out.insert("note".into(), json!(if fell { format!("{primary}に無いので、{label}の物を使っています") } else { String::new() }));
        out
    }

    fn locate_raw(&self, value: &str, folder: Option<&str>) -> Map<String, Value> {
        let raw = pyish::strip(value);
        let kind = path_kind(raw);
        let mut out = Map::new();
        out.insert("kind".into(), json!(kind));
        out.insert("resolved".into(), json!(""));
        out.insert("exists".into(), json!(false));
        out.insert("base".into(), json!(""));
        out.insert("rest".into(), json!(""));
        out.insert("primary".into(), json!(self.base_key(&self.rel_root())));
        out.insert("fell".into(), json!(false));
        out.insert("tried".into(), json!([]));
        out.insert("tried_from".into(), json!([]));
        if kind == "empty" {
            return out;
        }
        if let (Some(folder), "rel") = (folder, kind) {
            if !EXPLICIT_RELATIVE.iter().any(|x| raw.starts_with(x)) {
                let inner = self.locate(folder, None);
                let root = inner["resolved"].as_str().unwrap_or("").to_string();
                let real = self.resolve_path(Some(raw), Some(if root.is_empty() { "." } else { &root }));
                let ib = inner["base"].as_str().unwrap_or("").to_string();
                let rest = if ib.is_empty() {
                    String::new()
                } else {
                    format!("{}\\{}", inner["rest"].as_str().unwrap_or("").trim_end_matches('\\'), raw.replace('/', "\\"))
                };
                out.insert("exists".into(), json!(exists(&real)));
                out.insert("resolved".into(), json!(real));
                out.insert("base".into(), json!(ib));
                out.insert("fell".into(), inner["fell"].clone());
                out.insert("tried".into(), json!([real]));
                out.insert("tried_from".into(), json!([base_label(&ib)]));
                out.insert("rest".into(), json!(rest));
                return out;
            }
        }
        if kind == "rel" {
            let e = expand(raw);
            let p = py_path(&if WINDOWS { e } else { e.replace('\\', "/") });
            let (got, i, tried) = self.search(&p);
            let bases = self.rel_bases();
            let key = self.base_key(&bases[i]);
            out.insert("resolved".into(), json!(got));
            out.insert("exists".into(), json!(exists(&got)));
            out.insert("base".into(), json!(key));
            out.insert("rest".into(), json!(self.tail(&got, &bases[i])));
            out.insert("fell".into(), json!(i > 0));
            out.insert("tried".into(), json!(tried));
            out.insert("tried_from".into(), json!(bases.iter().map(|b| base_label(self.base_key(b))).collect::<Vec<_>>()));
            return out;
        }
        let real = self.resolve_path(Some(raw), None);
        out.insert("resolved".into(), json!(real));
        out.insert("exists".into(), json!(exists(&real)));
        out.insert("tried".into(), json!([real]));
        out.insert("tried_from".into(), json!([""]));
        if kind == "pc" {
            out.insert("base".into(), json!("local"));
            out.insert("rest".into(), json!(self.tail(&real, &self.local_root)));
            out.insert("tried_from".into(), json!([base_label("local")]));
        }
        out
    }

    /// ファイルの指定を読む（RNE・テキスト・結合で同じ決まり。navi_paths.resolve_in）。
    pub fn resolve_in(&self, value: &str, folder: Option<&str>) -> String {
        let root = self.resolve_path(folder, None);
        let raw = expand(value);
        if raw.is_empty() {
            return root;
        }
        if EXPLICIT_RELATIVE.iter().any(|x| raw.starts_with(x)) {
            return self.resolve_path(Some(&raw), None);
        }
        self.resolve_path(Some(&raw), Some(&root))
    }

    /// 絶対パスを、相対パスの基準からの書き方（.\… ／ ..\…）へ直す。読み直して同じ物に着くときだけ。直せなければ None。
    pub fn to_relative(&self, path: &str, inside_only: bool) -> Option<String> {
        let root = resolve(&self.rel_root());
        let target = resolve(path);
        let rel = relpath(&target, &root)?.replace('/', "\\");
        let text = if rel.starts_with("..") {
            if inside_only {
                return None;
            }
            rel
        } else {
            format!(".\\{rel}")
        };
        same_text(&resolve(&self.resolve_path(Some(&text), None)), &target).then_some(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_path_text() {
        if WINDOWS {
            assert_eq!(py_path("C:/a//b/./c/"), "C:\\a\\b\\c");
            assert_eq!(py_path("\\\\srv\\share\\x\\"), "\\\\srv\\share\\x");
            assert_eq!(py_path("C:"), "C:");
        } else {
            assert_eq!(py_path("/a//b/./c/"), "/a/b/c");
            assert_eq!(py_path("//a/b"), "//a/b", "先頭のちょうど2つの / は残す");
            assert_eq!(py_path("///a"), "/a");
            assert_eq!(py_path("a/../b"), "a/../b", ".. は残す");
        }
        assert_eq!(py_path(""), ".");
        assert_eq!(py_path("./"), ".");
    }

    #[test]
    fn release_root_like_python() {
        assert_eq!(release_root(Path::new("/s/versions")), PathBuf::from("/s"));
        assert_eq!(release_root(Path::new("/s/versions/1.98.0")), PathBuf::from("/s"));
        assert_eq!(release_root(Path::new("/s/old/1.98.0")), PathBuf::from("/s/old/1.98.0"));
        assert_eq!(release_root(Path::new("/s/versions/作業")), PathBuf::from("/s/versions/作業"));
    }

    #[test]
    fn kinds() {
        for (v, k) in [
            ("", "empty"),
            ("<PC>\\x", "pc"),
            ("%USERPROFILE%\\x", "env"),
            ("~/x", "env"),
            ("$HOME", "env"),
            ("\\\\s\\x", "unc"),
            ("C:\\x", "abs"),
            ("/x", "abs"),
            ("\\x", "abs"),
            (".\\rne", "rel"),
            ("X.RNE", "rel"),
            ("%%x", "rel"),
        ] {
            assert_eq!(path_kind(v), k, "{v}");
        }
    }

    #[test]
    fn logon_names() {
        let e = |n: &'static str| move |k: &str| (k == "USERNAME").then(|| n.to_string());
        assert_eq!(logon_name(&e("a:b??c")), "a_b_c");
        assert_eq!(logon_name(&e(" .x. ")), "x");
        assert_eq!(logon_name(&|_: &str| None), "");
    }

    #[test]
    fn portable_profile() {
        let home = PathBuf::from("C:\\Users\\me");
        assert_eq!(portable("C:\\Users\\me\\Box\\x", Some(&home)), "%USERPROFILE%\\Box\\x");
        assert_eq!(portable("C:\\Users\\you\\Box", Some(&home)), "C:\\Users\\you\\Box");
        assert_eq!(portable("D:\\x", Some(&home)), "D:\\x");
        assert_eq!(portable("%APPDATA%\\x", Some(&home)), "%APPDATA%\\x");
    }

    #[test]
    fn relpath_like_python() {
        if !WINDOWS {
            assert_eq!(relpath("/a/b/c", "/a").as_deref(), Some("b/c"));
            assert_eq!(relpath("/a", "/a/b").as_deref(), Some(".."));
            assert_eq!(relpath("/a", "/a").as_deref(), Some("."));
        }
    }
}
