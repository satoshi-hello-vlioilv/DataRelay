//! 中身（Rust の側）を、窓なしで呼ぶ口。突き合わせの試験（tests/test_rust_parity.py）と移行の記録の見張り
//! （tests/test_route_plan.py）が使う。配る exe には入れない（窓は同じ部品をプロセスの中で直接呼ぶ）。
//!
//!   datarelay-core routes   … Rust が答えるルートを JSON の並び（"GET /api/version" など）で出す
//!   datarelay-core answer [--base <アプリの場所>]
//!                           … 標準入力の1行1件の問い合わせ {"method","path","query","body"} に、
//!                             1行1件の答え {"status","headers","body"} で返す（本文は UTF-8 の文字。Rust が答えないルートは status 0）
//!   datarelay-core call     … 標準入力の1行1件の問い {"fn","args"} に、{"ok","result"|"error"} で返す（関数ごとの突き合わせ。probe.rs）

use datarelay_core::{Ask, Core, ROUTES};
use serde_json::{json, Value};
use std::io::{BufRead, Write};
use std::process::ExitCode;

fn main() -> ExitCode {
    match std::env::args().nth(1).as_deref() {
        Some("routes") => {
            let list: Vec<String> = ROUTES.iter().map(|(m, p, _)| format!("{m} {p}")).collect();
            println!("{}", json!(list));
            ExitCode::SUCCESS
        }
        Some("answer") => answer(),
        Some("call") => call(),
        _ => {
            eprintln!("使い方: datarelay-core routes | answer | call");
            ExitCode::from(2)
        }
    }
}

fn answer() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mut core = match args.iter().position(|a| a == "--base").and_then(|i| args.get(i + 1)) {
        Some(base) => Core::with_program(std::path::Path::new(base)),
        None => Core::new(),
    };
    // 試験だけ: いまの日時を決め打ちにする（2026-11-01T09:05:07.123456 の形。Python の側も同じ日時にして比べる）
    if let Ok(t) = std::env::var("DATARELAY_FIXED_NOW") {
        core.fixed_now = chrono::NaiveDateTime::parse_from_str(&t, "%Y-%m-%dT%H:%M:%S%.f").ok();
    }
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for line in std::io::stdin().lock().lines() {
        let Ok(line) = line else { return ExitCode::FAILURE };
        if line.trim().is_empty() {
            continue;
        }
        let q: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("問い合わせを読めません: {e}");
                return ExitCode::FAILURE;
            }
        };
        let s = |k: &str| q.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        let (method, path, query, body) = (s("method"), s("path"), s("query"), s("body"));
        let ask = Ask { method: &method, path: &path, query: &query, headers: vec![], body: body.as_bytes() };
        let reply = match core.handle(&ask) {
            Some(r) => json!({"status": r.status, "headers": r.headers, "body": String::from_utf8_lossy(&r.body)}),
            None => json!({"status": 0, "headers": [], "body": ""}),
        };
        if writeln!(out, "{reply}").and_then(|_| out.flush()).is_err() {
            return ExitCode::FAILURE;
        }
    }
    ExitCode::SUCCESS
}

fn call() -> ExitCode {
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for line in std::io::stdin().lock().lines() {
        let Ok(line) = line else { return ExitCode::FAILURE };
        if line.trim().is_empty() {
            continue;
        }
        let q: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("問いを読めません: {e}");
                return ExitCode::FAILURE;
            }
        };
        let reply = match datarelay_core::probe::call(q["fn"].as_str().unwrap_or(""), &q["args"]) {
            Ok(v) => json!({"ok": true, "result": v}),
            Err(e) => json!({"ok": false, "error": e}),
        };
        if writeln!(out, "{reply}").and_then(|_| out.flush()).is_err() {
            return ExitCode::FAILURE;
        }
    }
    ExitCode::SUCCESS
}
