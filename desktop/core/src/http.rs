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

    /// 失敗の答え。Flask が組み立てる失敗（400 本文が JSON でない・500 処理の失敗）と同じ番号で返す。
    pub fn error(status: u16, message: &str) -> Reply {
        Reply::json(status, &serde_json::json!({"ok": false, "error": message}))
    }
}

impl Ask<'_> {
    /// 本文を JSON として読む（Flask の `request.get_json(force=True) or {}` に当たる）。
    /// 空・JSON でない → Err（Flask は 400 を返す）。null・false・0・"" など偽の値は空の辞書として扱う。
    pub fn json_or_empty(&self) -> Result<Value, Reply> {
        let v: Value = serde_json::from_slice(self.body).map_err(|_| Reply::error(400, "問い合わせの本文を JSON として読めません"))?;
        Ok(if crate::pyish::truthy(&v) { v } else { Value::Object(Default::default()) })
    }
}
