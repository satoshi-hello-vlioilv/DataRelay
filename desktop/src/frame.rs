//! 窓口（sidecar.py）との枠。両方向とも同じ形:
//!   ヘッダー: JSON 1行（UTF-8・改行で終わる）。"len" が本文のバイト数
//!   本文    : len バイトそのまま（base64 にしない。大きな一覧でも膨らませない）
//! Defect-Pitch-Analyzer の desktop/src/frame.rs（版 2.0.0）と同じもの。Python 側の read_frame / Writer.send と対になる。

use serde_json::Value;
use std::io::{self, BufRead, Write};

pub struct Frame {
    pub head: Value,
    pub body: Vec<u8>,
}

/// 枠を1つ書く（head の "len" は本文から付け直す）。
pub fn write_frame<W: Write>(w: &mut W, head: &Value, body: &[u8]) -> io::Result<()> {
    let mut head = head.clone();
    if let Value::Object(m) = &mut head {
        m.insert("len".into(), Value::from(body.len()));
    }
    let mut line = serde_json::to_vec(&head)?;
    line.push(b'\n');
    w.write_all(&line)?;
    w.write_all(body)?;
    w.flush()
}

/// 枠を1つ読む。入力が閉じたら None。途中で切れた枠は誤り。
pub fn read_frame<R: BufRead>(r: &mut R) -> io::Result<Option<Frame>> {
    let mut line = Vec::new();
    if r.read_until(b'\n', &mut line)? == 0 {
        return Ok(None);
    }
    let head: Value =
        serde_json::from_slice(&line).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("枠のヘッダーが読めません: {e}")))?;
    let n = head.get("len").and_then(Value::as_u64).unwrap_or(0) as usize;
    let mut body = vec![0; n];
    r.read_exact(&mut body)?;
    Ok(Some(Frame { head, body }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Cursor;

    #[test]
    fn round_trip_with_binary_and_japanese() {
        let mut buf = Vec::new();
        let body = "集計表\n列\0".as_bytes();
        write_frame(&mut buf, &json!({"id": 3, "path": "/api/x"}), body).unwrap();
        write_frame(&mut buf, &json!({"id": 4}), b"").unwrap();
        let mut r = Cursor::new(buf);
        let a = read_frame(&mut r).unwrap().unwrap();
        assert_eq!(a.head["id"], 3);
        assert_eq!(a.head["len"], body.len());
        assert_eq!(a.body, body, "本文の改行・NUL でも枠がずれない");
        let b = read_frame(&mut r).unwrap().unwrap();
        assert_eq!((b.head["id"].as_u64(), b.body.len()), (Some(4), 0));
        assert!(read_frame(&mut r).unwrap().is_none(), "閉じたら None");
    }

    #[test]
    fn cut_body_is_an_error() {
        let mut r = Cursor::new(b"{\"id\":1,\"len\":10}\nabc".to_vec());
        assert!(read_frame(&mut r).is_err());
    }
}
