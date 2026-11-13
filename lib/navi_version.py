"""このアプリの版。

ここは処理からも画面からも見られる小さな定数だけ。更新履歴と同梱仕様書は
changelog.toml（navi_changelog.py が読む）にある ―― 3000行余りの読みものなので、それを必要としない経路
（抽出ワーカー）が読み込まずに済むように分けてある。
"""
APP_VERSION='2.40.1'; APP_VERSION_TITLE='あとから入れた実行が、空いているラインで同時に流れるようにした'; APP_RELEASED_AT='2026-11-13'
BUILD_VERSION=f'{APP_VERSION}-web'
