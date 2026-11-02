"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.21.0'; APP_VERSION_TITLE='予定の一覧・カレンダー・実行の傾向を Rust の中身が受け持ち、予定の決まり（次の実行・月の予定）を Rust へ移した'; APP_RELEASED_AT='2026-11-02'
BUILD_VERSION=f'{APP_VERSION}-web'
