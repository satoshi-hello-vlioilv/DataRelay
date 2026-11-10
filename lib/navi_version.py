"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.26.0'; APP_VERSION_TITLE='読取マスタの下読みと区切りの見当付けを Rust の中身が受け持ち、数の列が符号だけのときに下読みと実行が止まる不具合を直した'; APP_RELEASED_AT='2026-11-10'
BUILD_VERSION=f'{APP_VERSION}-web'
