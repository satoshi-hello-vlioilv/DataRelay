//! データビュワー（2.28.0〜）。lib/navi_web.py の data_viewer・data_viewer_jobs と、app.read_preview_data（CSV・TXT・SQLite3）と同じ答えを返す。
//!
//!   - GET /api/data-viewer/jobs     … ビュワーで選べる対象（形式・ファイルがあるか）
//!   - GET /api/data-viewer/<job_id> … 1つの出力ファイルの中身（公開先は直接開かず、手元へ写してから読む。localcopy.rs）
//!
//! CSV は CPython の _csv.c（excel の決まり: 区切り , か \t・囲み " ・"" は " ・strict でない）と同じ順で読む。
//! 文字コードは utf-8-sig → cp932 → utf-8 の順に、読み切れた物を使う（textread.rs と同じ読み方）。
//! 値ごとに分けて出す対象は、値ごとのファイルを並べる（variants.rs。2.29.0〜）。
//! EXCEL・ACCESS、1 欄が 131072 字を超える CSV、SQLite のバイト列・数でない小数は Python へ回す。
use crate::config::{self, Pass};
use crate::http::{Ask, Reply};
use crate::localcopy::{self, CopyError};
use crate::textread::{self, Enc};
use crate::{joinplan, naming, paths, pyish, routes::Core, schedule, variants};
use serde_json::{json, Map, Value};

type R<T> = Result<T, Pass>;

const VIEWER_MAX_CELLS: usize = 20_000_000;
const VIEWER_MAX_ROWS: usize = 100_000;
const FIELD_LIMIT: usize = 131_072;

/// viewer_row_budget（その列数のとき、画面へ何行まで渡すか）。
fn row_budget(columns: usize) -> usize {
    (VIEWER_MAX_CELLS / columns.max(1)).clamp(1, VIEWER_MAX_ROWS)
}

// ==== CSV（CPython の _csv.c と同じ順） =====================================

#[derive(PartialEq, Clone, Copy)]
enum St {
    StartRecord,
    StartField,
    InField,
    InQuoted,
    QuoteInQuoted,
    EatCrnl,
}

/// csv.reader(open(newline='')) の行（\r・\n・\r\n で分け、行の終わりの字は残す）。
fn raw_lines(s: &str) -> Vec<&str> {
    let b = s.as_bytes();
    let (mut out, mut start, mut i) = (Vec::new(), 0, 0);
    while i < b.len() {
        match b[i] {
            b'\n' => {
                out.push(&s[start..=i]);
                start = i + 1;
            }
            b'\r' => {
                let end = if b.get(i + 1) == Some(&b'\n') { i + 1 } else { i };
                out.push(&s[start..=end]);
                i = end;
                start = end + 1;
            }
            _ => {}
        }
        i += 1;
    }
    if start < b.len() {
        out.push(&s[start..]);
    }
    out
}

/// list(csv.reader(..., delimiter=d))。1 欄が上限を超えたら Pass（Python は csv.Error で落ちる）。
pub fn read_csv(s: &str, delim: char) -> R<Vec<Vec<String>>> {
    let mut rows = Vec::new();
    let (mut fields, mut field, mut st) = (Vec::<String>::new(), String::new(), St::StartRecord);
    let mut flen = 0usize;
    let add = |field: &mut String, flen: &mut usize, c: char| -> R<()> {
        if *flen >= FIELD_LIMIT {
            return Err(Pass);
        }
        field.push(c);
        *flen += 1;
        Ok(())
    };
    for line in raw_lines(s) {
        // 1字ずつ。最後に行の終わりの印（EOL）を1つ
        for c in line.chars().map(Some).chain(std::iter::once(None)) {
            let nl = matches!(c, Some('\n') | Some('\r'));
            loop {
                match st {
                    St::StartRecord => {
                        if c.is_none() {
                            break; // 空の行 → 下で [] を1件にする
                        } else if nl {
                            st = St::EatCrnl;
                            break;
                        }
                        st = St::StartField;
                        continue; // 同じ字を StartField で読み直す
                    }
                    St::StartField => {
                        if nl || c.is_none() {
                            fields.push(std::mem::take(&mut field));
                            flen = 0;
                            st = if c.is_none() { St::StartRecord } else { St::EatCrnl };
                        } else if c == Some('"') {
                            st = St::InQuoted;
                        } else if c == Some(delim) {
                            fields.push(std::mem::take(&mut field));
                            flen = 0;
                        } else {
                            add(&mut field, &mut flen, c.unwrap_or_default())?;
                            st = St::InField;
                        }
                    }
                    St::InField => {
                        if nl || c.is_none() {
                            fields.push(std::mem::take(&mut field));
                            flen = 0;
                            st = if c.is_none() { St::StartRecord } else { St::EatCrnl };
                        } else if c == Some(delim) {
                            fields.push(std::mem::take(&mut field));
                            flen = 0;
                            st = St::StartField;
                        } else {
                            add(&mut field, &mut flen, c.unwrap_or_default())?;
                        }
                    }
                    St::InQuoted => match c {
                        None => {}
                        Some('"') => st = St::QuoteInQuoted,
                        Some(ch) => add(&mut field, &mut flen, ch)?,
                    },
                    St::QuoteInQuoted => {
                        if c == Some('"') {
                            add(&mut field, &mut flen, '"')?;
                            st = St::InQuoted;
                        } else if c == Some(delim) {
                            fields.push(std::mem::take(&mut field));
                            flen = 0;
                            st = St::StartField;
                        } else if nl || c.is_none() {
                            fields.push(std::mem::take(&mut field));
                            flen = 0;
                            st = if c.is_none() { St::StartRecord } else { St::EatCrnl };
                        } else {
                            add(&mut field, &mut flen, c.unwrap_or_default())?;
                            st = St::InField;
                        }
                    }
                    St::EatCrnl => {
                        if nl {
                        } else if c.is_none() {
                            st = St::StartRecord;
                        } else {
                            return Err(Pass); // Python は csv.Error（newline='' で開いていれば起きない）
                        }
                    }
                }
                break;
            }
        }
        if st == St::StartRecord {
            rows.push(std::mem::take(&mut fields));
        }
    }
    // 終わりで囲みが閉じていない・欄が残っている → その欄で1件にする（strict でないとき）
    if flen != 0 || st == St::InQuoted {
        fields.push(field);
        rows.push(fields);
    }
    Ok(rows)
}

/// textread の is_junk_line を、1つの欄の字に（is_junk_row で使う）。
fn junk_text(v: &str) -> bool {
    let body = v.trim_matches(|c| c == ' ' || c == '\t' || c == '\u{3000}');
    !body.is_empty() && body.chars().all(|c| (c < '\u{20}' && c != '\t') || c == '\u{7f}' || c == '\u{fffd}')
}

/// navi_text.is_junk_row（空か読めない記号だけの欄でできていて、読めない記号の欄が1つはある）。
fn junk_row(cells: &[String]) -> bool {
    cells.iter().any(|v| junk_text(v))
        && cells.iter().all(|v| v.trim_matches(|c| c == ' ' || c == '\t' || c == '\u{3000}').is_empty() || junk_text(v))
}

/// 読み取りの答え（read_preview_data）: (形式, 見出し, 行, 件数, 切る前の列数)。
pub(crate) struct Data {
    pub(crate) fmt: &'static str,
    pub(crate) headers: Vec<String>,
    pub(crate) rows: Vec<Vec<String>>,
    pub(crate) total: usize,
}

/// 読めない理由（画面へ出す文。Python の例外の文と同じ）。
pub(crate) enum ReadFail {
    Message(String),
}

pub(crate) fn read_text_table(bytes: &[u8], fmt: &'static str, limit: usize) -> R<Result<Data, ReadFail>> {
    let delim = if fmt == "csv" { ',' } else { '\t' };
    let mut data = None;
    for enc in [Enc::Utf8Sig, Enc::Cp932, Enc::Utf8] {
        let (s, bad) = textread::decode(enc, bytes);
        if !bad {
            data = Some(read_csv(&s, delim)?);
            break;
        }
    }
    let Some(data) = data else { return Ok(Err(ReadFail::Message("文字コードを判定できません".into()))) };
    let data: Vec<Vec<String>> = data.into_iter().filter(|r| !junk_row(r)).collect();
    let headers = data.first().cloned().unwrap_or_default();
    let total = data.len().saturating_sub(1);
    let rows = data.into_iter().skip(1).take(limit).collect();
    Ok(Ok(Data { fmt, headers, rows, total }))
}

/// SQLite の値を str(v) に（None は空）。バイト列・数でない小数は Python と同じ字を作れないので Pass。
fn sql_text(v: rusqlite::types::ValueRef) -> R<String> {
    use rusqlite::types::ValueRef::*;
    match v {
        Null => Ok(String::new()),
        Integer(i) => Ok(i.to_string()),
        Real(f) => serde_json::Number::from_f64(f).map(|n| pyish::py_str(&Value::Number(n))).ok_or(Pass),
        Text(t) => std::str::from_utf8(t).map(String::from).map_err(|_| Pass),
        Blob(_) => Err(Pass),
    }
}

pub(crate) fn read_sqlite(path: &str, job: &Map<String, Value>, limit: usize) -> R<Result<Data, ReadFail>> {
    let c =
        rusqlite::Connection::open_with_flags(path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX)
            .map_err(|_| Pass)?;
    let names: Vec<String> = {
        let mut st =
            c.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_更新情報' ORDER BY name").map_err(|_| Pass)?;
        let it = st.query_map([], |r| r.get::<_, String>(0)).map_err(|_| Pass)?;
        it.collect::<Result<_, _>>().map_err(|_| Pass)?
    };
    let want = pyish::text_or_empty(job.get("table"));
    let table = if names.contains(&want) { want } else { names.first().cloned().unwrap_or_default() };
    if table.is_empty() {
        return Ok(Err(ReadFail::Message("表示できるテーブルがありません".into())));
    }
    let q = format!("\"{}\"", table.replace('"', "\"\""));
    let headers: Vec<String> = {
        let mut st = c.prepare(&format!("PRAGMA table_info({q})")).map_err(|_| Pass)?;
        let it = st.query_map([], |r| r.get::<_, String>(1)).map_err(|_| Pass)?;
        it.collect::<Result<_, _>>().map_err(|_| Pass)?
    };
    let total: i64 = c.query_row(&format!("SELECT COUNT(*) FROM {q}"), [], |r| r.get(0)).map_err(|_| Pass)?;
    let mut st = c.prepare(&format!("SELECT * FROM {q} LIMIT ?")).map_err(|_| Pass)?;
    let n = st.column_count();
    let mut rows = Vec::new();
    let mut it = st.query([limit as i64]).map_err(|_| Pass)?;
    while let Some(r) = it.next().map_err(|_| Pass)? {
        let mut row = Vec::with_capacity(n);
        for i in 0..n {
            row.push(sql_text(r.get_ref(i).map_err(|_| Pass)?)?);
        }
        rows.push(row);
    }
    Ok(Ok(Data { fmt: "sqlite3", headers, rows, total: total.max(0) as usize }))
}

/// 形式（normalize_output_format(job.output_format, 道の名前)）。ビュワーが Rust で読める形式でなければ None。
fn readable_format(job: &Map<String, Value>, name: &str) -> Option<&'static str> {
    match naming::normalize_output_format(job.get("output_format"), Some(&json!(name))) {
        f @ ("csv" | "txt" | "sqlite3") => Some(f),
        _ => None,
    }
}

fn jobs(cfg: &Map<String, Value>) -> &[Value] {
    cfg.get("jobs").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

fn is_file(p: &str) -> bool {
    std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
}

// ==== 受け口 ================================================================

/// GET /api/data-viewer/jobs
pub(crate) fn get_jobs(core: &Core, _: &Ask, _: &[String]) -> Reply {
    answer_jobs(core).unwrap_or_else(|_| Reply::pass())
}

fn answer_jobs(core: &Core) -> R<Reply> {
    let (c, runs) = config::read_with(core, |_, conn| schedule::job_runs(conn))?;
    let b = core.bases().ok_or(Pass)?;
    let mut items = Vec::new();
    for j in jobs(&c) {
        let Value::Object(j) = j else { return Err(Pass) };
        let (path, files) = if variants::active(j)? {
            let files = variants::viewer_files(core, &b, j, &c, &runs)?;
            if files.iter().any(|x| x.path.is_empty()) {
                return Err(Pass); // Path('') は今いるフォルダー（Python と同じ時刻を作れない）
            }
            let path = match files.first() {
                Some(x) => x.path.clone(),
                None => joinplan::viewer_output_path(core, &b, j, &c, &runs),
            };
            let list: Vec<Value> = files
                .iter()
                .map(|x| {
                    json!({"value": x.value, "file": paths::py_name(&x.path), "exists": is_file(&x.path), "rows": x.rows,
                                "modified": mtime_text(&x.path)})
                })
                .collect();
            (path, Some((files.iter().any(|x| is_file(&x.path)), list)))
        } else {
            (joinplan::viewer_output_path(core, &b, j, &c, &runs), None)
        };
        let fmt = naming::normalize_output_format(j.get("output_format"), Some(&json!(paths::py_name(&path))));
        let (exists, list) = files.unwrap_or_else(|| (is_file(&path), vec![]));
        items.push(json!({"id": j.get("id").cloned().unwrap_or(Value::Null), "name": j.get("name").cloned().unwrap_or(Value::Null),
                          "format": fmt, "exists": exists, "files": list}));
    }
    Ok(Reply::json(200, &json!({"items": items})))
}

/// GET /api/data-viewer/<job_id>
pub(crate) fn get_viewer(core: &Core, ask: &Ask, params: &[String]) -> Reply {
    answer_viewer(core, ask, &params[0]).unwrap_or_else(|_| Reply::pass())
}

/// 問い合わせの ?value=（無ければ None）。request.args.get('value') と同じく、& で区切り、+ を空白に、%XX を戻す（最初の値）。
/// 戻した字が UTF-8 でなければ Pass（Python は置き換えの字を入れる）。
fn query_value(ask: &Ask) -> R<Option<String>> {
    for kv in ask.query.split('&').filter(|x| !x.is_empty()) {
        let (k, v) = kv.split_once('=').unwrap_or((kv, ""));
        if unquote(k)? == "value" {
            return unquote(v).map(Some);
        }
    }
    Ok(None)
}

/// urllib.parse.unquote_plus（%XX の形でない % はそのまま残す）。
fn unquote(s: &str) -> R<String> {
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
    String::from_utf8(out).map_err(|_| Pass)
}

/// _mtime_text（'%m-%d %H:%M'。読めなければ空）。
fn mtime_text(p: &str) -> String {
    std::fs::metadata(p)
        .and_then(|m| m.modified())
        .map(|t| chrono::DateTime::<chrono::Local>::from(t).format("%m-%d %H:%M").to_string())
        .unwrap_or_default()
}

fn not_found(msg: String) -> R<Reply> {
    Ok(Reply::json(404, &json!({"ok": false, "error": msg})))
}

fn answer_viewer(core: &Core, ask: &Ask, job_id: &str) -> R<Reply> {
    let (c, runs) = config::read_with(core, |_, conn| schedule::job_runs(conn))?;
    let Some(Value::Object(job)) = jobs(&c).iter().find(|x| x.get("id").and_then(Value::as_str) == Some(job_id)) else {
        return not_found("対象が見つかりません".into());
    };
    let b = core.bases().ok_or(Pass)?;
    let want = query_value(ask)?;
    let (value, path) = if variants::active(job)? {
        let files = variants::viewer_files(core, &b, job, &c, &runs)?;
        let one = match &want {
            Some(w) => match files.iter().find(|x| &x.value == w) {
                Some(x) => Some(x),
                None => return not_found(format!("「{w}」は、この対象の値にありません")),
            },
            None => None,
        };
        if files.is_empty() {
            return not_found("まだ値ごとのファイルを作っていません。実行すると、出てきた値ごとのファイルを開けます".into());
        }
        let one = one.or_else(|| files.iter().find(|x| is_file(&x.path))).unwrap_or(&files[0]);
        if one.path.is_empty() {
            return Err(Pass); // Path('') は今いるフォルダー
        }
        (one.value.clone(), one.path.clone())
    } else {
        if let Some(w) = want.as_deref().filter(|w| !w.is_empty()) {
            return not_found(format!("「{w}」は、この対象の値にありません"));
        }
        (String::new(), joinplan::viewer_output_path(core, &b, job, &c, &runs))
    };
    if !is_file(&path) {
        return not_found(format!("出力ファイルが見つかりません: {path}"));
    }
    // ビュワーが Rust で読めない形式（EXCEL・ACCESS）は、写す前に Python へ回す（写しを2度作らない）
    let Some(fmt) = readable_format(job, &paths::py_name(&path)) else { return Err(Pass) };
    let name = job.get("name").cloned().unwrap_or(Value::Null);
    let log = |m: &str| core.log(m);
    let copy = match localcopy::read_copy(&path, &log) {
        Ok(p) => p,
        Err(CopyError::NotCopied(e)) => {
            core.log(&format!("DATA_VIEWER_NOT_COPIED job={} path={path} reason={}", pyish::py_str(&name), e.0));
            return Ok(Reply::json(200, &json!({"ok": false, "error": e.0, "kind": "copying"})));
        }
        Err(CopyError::Other) => return Err(Pass),
    };
    let read = if fmt == "sqlite3" {
        read_sqlite(&copy, job, VIEWER_MAX_ROWS)?
    } else {
        let bytes = std::fs::read(&copy).map_err(|_| Pass)?;
        read_text_table(&bytes, fmt, VIEWER_MAX_ROWS)?
    };
    let d = match read {
        Ok(d) => d,
        Err(ReadFail::Message(m)) => {
            core.log(&format!("DATA_VIEWER_FAILED job={} path={path}", pyish::py_str(&name)));
            return Ok(Reply::json(200, &json!({"ok": false, "error": m})));
        }
    };
    let n = d.headers.len();
    let mut rows: Vec<Vec<String>> = d.rows.into_iter().map(|r| r.into_iter().take(n).collect()).collect();
    let keep = row_budget(n);
    let limited = rows.len() > keep;
    rows.truncate(keep);
    let modified = std::fs::metadata(&path)
        .and_then(|m| m.modified())
        .map(|t| chrono::DateTime::<chrono::Local>::from(t).format("%Y-%m-%dT%H:%M:%S").to_string())
        .map_err(|_| Pass)?;
    Ok(Reply::json(
        200,
        &json!({"ok": true, "name": name, "value": value, "format": d.fmt, "path": path, "modified": modified,
                "headers": d.headers, "rows": rows, "total_rows": d.total, "preview_limit": rows.len(),
                "truncated": d.total > rows.len(), "total_columns": n, "row_budget": keep, "row_budget_limited": limited}),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn csv(s: &str) -> Vec<Vec<String>> {
        read_csv(s, ',').ok().unwrap_or_default()
    }

    #[test]
    fn csv_like_python() {
        assert_eq!(csv("a,b\r\nc,d\n"), vec![vec!["a", "b"], vec!["c", "d"]]);
        assert_eq!(csv("a,\"b,\"\"c\"\"\"x,d\n\n"), vec![vec!["a", "b,\"c\"x", "d"], vec![]]);
        assert_eq!(csv("\"multi\r\nline\",z"), vec![vec!["multi\r\nline", "z"]]);
        assert_eq!(csv("a,\"open"), vec![vec!["a", "open"]]);
        assert_eq!(csv("x\ry"), vec![vec!["x"], vec!["y"]]);
        assert_eq!(csv(",\n"), vec![vec!["", ""]]);
    }
}
