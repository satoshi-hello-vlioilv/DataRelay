"""更新履歴と、同梱する仕様書の一覧（中身は lib/changelog.toml）。

版ごとに増える一方の読みもので、処理には一切関わらない。画面の「バージョン情報」と
仕様書ビューアだけが使う。抽出ワーカーは読み込まない（読む面積を減らすため）。
2.15.0 で、Rust の中身（desktop/core）と同じものを読めるよう、Python のコードから TOML のデータへ移した。
"""
from pathlib import Path

SOURCE=Path(__file__).with_name('changelog.toml')


def _load():
 try:
  import tomllib   # Python 3.11 から標準。無い古い Python では、バージョン情報の画面が空になるだけ（処理は止めない）
  with SOURCE.open('rb') as f:return tomllib.load(f)
 except (ImportError,OSError):return {}


_DATA=_load()
# アプリに同梱する仕様書。ここに登録したものだけが画面から開ける。
# 画面からはこのidしか受け取らないので、任意のパスを読ませることはできない。
DOCS=_DATA.get('doc',[])
CHANGELOG=_DATA.get('release',[])
