//! 問い合わせと答えの形。窓が受けた HTTP の問い合わせを、そのまま渡し合う（Python のサイドカーへ送る形と同じ）。

use serde_json::Value;

/// 答え。
#[derive(Debug, Clone, PartialEq)]
pub struct Reply {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

/// 問い合わせ（窓が受けた HTTP の問い合わせを、そのまま渡す形）。
pub struct Ask<'a> {
    pub method: &'a str,
    pub path: &'a str,
    pub query: &'a str,
    pub headers: Vec<(String, String)>,
    pub body: &'a [u8],
}

impl Reply {
    /// JSON の答え（Flask の jsonify と同じ Content-Type）。
    pub fn json(status: u16, v: &Value) -> Reply {
        Reply { status, headers: vec![("Content-Type".into(), "application/json".into())], body: serde_json::to_vec(v).unwrap_or_default() }
    }

    /// Rust では答えない（Python へ回す）。`Core::handle` が None に直す。
    pub fn pass() -> Reply {
        Reply { status: 0, headers: vec![], body: vec![] }
    }

    /// 失敗の答え。Flask が組み立てる失敗（400 本文が JSON でない・500 処理の失敗）と同じ番号で返す。
    pub fn error(status: u16, message: &str) -> Reply {
        Reply::json(status, &serde_json::json!({"ok": false, "error": message}))
    }
}

/// 問い合わせの ?… を戻した字が UTF-8 でない（Python は置き換えの字を入れる）。
#[derive(Debug)]
pub struct BadQuery;

impl Ask<'_> {
    /// 本文を JSON として読む（Flask の `request.get_json(force=True) or {}` に当たる）。
    /// 空・JSON でない → Err（Flask は 400 を返す）。null・false・0・"" など偽の値は空の辞書として扱う。
    pub fn json_or_empty(&self) -> Result<Value, Reply> {
        let v: Value = serde_json::from_slice(self.body).map_err(|_| Reply::error(400, "問い合わせの本文を JSON として読めません"))?;
        Ok(if crate::pyish::truthy(&v) { v } else { Value::Object(Default::default()) })
    }

    /// 問い合わせの ?key=（無ければ None）。request.args.get(key) と同じく、& で区切り、+ を空白に、%XX を戻す（最初の値）。
    /// 戻した字が UTF-8 でなければ Err（Python は置き換えの字を入れるので、呼ぶ側が Python へ回す）。
    pub fn arg(&self, key: &str) -> Result<Option<String>, BadQuery> {
        for kv in self.query.split('&').filter(|x| !x.is_empty()) {
            let (k, v) = kv.split_once('=').unwrap_or((kv, ""));
            if unquote(k)? == key {
                return unquote(v).map(Some);
            }
        }
        Ok(None)
    }
}

/// urllib.parse.unquote_plus（%XX の形でない % はそのまま残す）。
fn unquote(s: &str) -> Result<String, BadQuery> {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        let hex = |c: u8| (c as char).to_digit(16);
        match b[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < b.len() => {
                if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                    out.push((h * 16 + l) as u8);
                    i += 3;
                    continue;
                }
                out.push(b'%');
            }
            c => out.push(c),
        }
        i += 1;
    }
    String::from_utf8(out).map_err(|_| BadQuery)
}
