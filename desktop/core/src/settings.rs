//! 設定の手元の写し（<このPC>\cache\app_settings.sqlite3）を読む（2.17.0〜。まだ読むだけ）。
//!
//! Python（app.py）は起動したときに1度だけ共有のマスターをこの写しへ取り込み、以降の読み書きはすべてこの写しで行う
//! （init_settings_db・save）。だから Rust はこの写しを読めば、Python と同じ値を見る。書くのはまだ Python だけ
//! （書き戻し・版・同期の決まりは、設定の保存を移す段で一緒に移す）。

use crate::pyish;
use rusqlite::{Connection, OpenFlags};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// 入力の種類（app.JOB_SOURCES）。知らない値は rne として読む。
pub const JOB_SOURCES: [&str; 4] = ["rne", "text", "join", "mquery"];

/// normalize_job_source。
pub fn job_source(v: &str) -> &'static str {
    let v = pyish::strip(v).to_lowercase();
    JOB_SOURCES.iter().find(|s| **s == v).copied().unwrap_or("rne")
}

/// 設定の手元の写しの置き場（app.SETTINGS_DB）。
pub fn local_db(local_root: &Path) -> PathBuf {
    local_root.join("cache").join("app_settings.sqlite3")
}

/// 設定の手元の写し（読むだけ）。写しがまだ無い（中身がまだ一度も起きていない）ときは、空の設定として答える。
pub struct Settings {
    conn: Option<Connection>,
}

impl Settings {
    pub fn open(path: &Path) -> Result<Settings, String> {
        if !path.is_file() {
            return Ok(Settings { conn: None });
        }
        let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
            .map_err(|e| format!("設定を開けません: {e}"))?;
        // Python と同じく、書いている最中なら 30 秒まで待つ
        conn.busy_timeout(Duration::from_secs(30)).map_err(|e| e.to_string())?;
        Ok(Settings { conn: Some(conn) })
    }

    /// 共通の値（app_settings の1行）を、保存の型どおりに戻す（app._decode_setting）。無ければ None。
    pub fn top(&self, key: &str) -> Result<Option<Value>, String> {
        let Some(c) = &self.conn else { return Ok(None) };
        let row: Option<(String, String)> = c
            .query_row("SELECT value,value_type FROM app_settings WHERE key=?1", [key], |r| Ok((r.get(0)?, r.get(1)?)))
            .map(Some)
            .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(e) })
            .map_err(|e| format!("設定を読めません: {e}"))?;
        let Some((v, t)) = row else { return Ok(None) };
        Ok(Some(match t.as_str() {
            "json" => serde_json::from_str(&v).map_err(|e| format!("設定 {key} を読めません: {e}"))?,
            "bool" => Value::Bool(v == "1"),
            "int" => match pyish::int_or(Some(&Value::String(v.clone())), i64::MIN) {
                Ok(i) if i != i64::MIN => Value::from(i),
                _ => return Err(format!("設定 {key} を読めません（数ではありません: {v}）")),
            },
            _ => Value::String(v),
        }))
    }

    /// 対象ごとの (有効か, 入力の種類)。並び順は問わない用途（「有効な RNE の対象があるか」など）向け。
    pub fn job_kinds(&self) -> Result<Vec<(bool, &'static str)>, String> {
        let Some(c) = &self.conn else { return Ok(vec![]) };
        let has_source = c
            .prepare("SELECT 1 FROM pragma_table_info('jobs') WHERE name='source'")
            .and_then(|mut s| s.exists([]))
            .map_err(|e| format!("設定を読めません: {e}"))?;
        let sql = if has_source { "SELECT enabled, COALESCE(source,'') FROM jobs" } else { "SELECT enabled, '' FROM jobs" };
        let mut st = c.prepare(sql).map_err(|e| format!("設定を読めません: {e}"))?;
        let rows = st
            .query_map([], |r| Ok((r.get::<_, i64>(0)? != 0, job_source(&r.get::<_, String>(1)?))))
            .map_err(|e| format!("設定を読めません: {e}"))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| format!("設定を読めません: {e}"))
    }
}
