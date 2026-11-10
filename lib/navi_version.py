"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.23.0'; APP_VERSION_TITLE='画面からの書き込み（列の並び・カレンダーからの実行・自動実行の一時停止・マスタの保存と削除）を Rust の中身が受け持つようにした'; APP_RELEASED_AT='2026-11-10'
BUILD_VERSION=f'{APP_VERSION}-web'
