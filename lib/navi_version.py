"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.32.0'; APP_VERSION_TITLE='マスタの取り込み（JSON）と集計表の書き出し（CSV・TXT）を、Rust の中身が受け持つようにした'; APP_RELEASED_AT='2026-11-13'
BUILD_VERSION=f'{APP_VERSION}-web'
