"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.30.0'; APP_VERSION_TITLE='結合の材料1つの見出しと件数を、Rust の中身が読むようにした'; APP_RELEASED_AT='2026-11-12'
BUILD_VERSION=f'{APP_VERSION}-web'
