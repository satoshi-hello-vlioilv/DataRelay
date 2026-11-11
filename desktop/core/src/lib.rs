//! DataRelay の中身（業務の処理）のうち、Rust へ移したもの。窓（Tauri）に依らない。
//!
//! Rust を主にする移行（2.15.0〜。migration/FEASIBILITY.md §14）は、画面の問い合わせ（ルート）を1本ずつここへ移す:
//!   - 窓（desktop/src/router.rs）は、まず `Core::handle` に聞く。答えられれば Rust が返し、答えられなければ Python へ回す
//!   - 移したルートの Python の受け口は、最後の段まで「振る舞いの基準」として残す。tests/test_rust_parity.py が
//!     同じ問い合わせを両方へ送って、答えが同じかを確かめる（`datarelay-core answer` がこの答え口）
//!   - 全部を移し終えたら、Python（サイドカー・pip・Python の検出）を外す
//!
//! 画面の JS は fetch('/api/...') のまま変えない。答えの形（JSON の鍵と値）も Python と同じにする。

pub mod applog;
pub mod config;
pub mod edits;
pub mod http;
pub mod joinplan;
pub mod localcopy;
mod login;
pub mod masters;
pub mod naming;
pub mod paths;
pub mod period;
mod places;
pub mod probe;
mod pyish;
pub mod routes;
pub mod schedule;
pub mod secret;
pub mod settings;
pub mod textread;
pub mod version;
pub mod viewer;
pub mod writer;

pub use http::{Ask, Reply};
pub use routes::{Core, ROUTES};
