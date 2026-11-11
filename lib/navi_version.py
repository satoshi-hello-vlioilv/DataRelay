"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.27.0'; APP_VERSION_TITLE='結合マスタの組み立てを助ける受け口（つなぐ相手の候補・材料を作る対象・写しの片づけ）を Rust の中身が受け持つようにした'; APP_RELEASED_AT='2026-11-11'
BUILD_VERSION=f'{APP_VERSION}-web'
