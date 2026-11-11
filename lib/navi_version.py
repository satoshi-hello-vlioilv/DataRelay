"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.29.0'; APP_VERSION_TITLE='データビュワーで、値ごとに分けて出す対象も Rust の中身が開くようにした'; APP_RELEASED_AT='2026-11-11'
BUILD_VERSION=f'{APP_VERSION}-web'
