# DataRelay の作業の決まり

## 1. push の前に、手元で typecheck / lint / test を green にする

次をすべて手元で通してから push する。1つでも赤なら push しない。
CI（Windows の `desktop.yml`）は確かめ直す場所で、手元の確認の代わりにはしない。

| 種類 | コマンド（リポジトリの直下から） | 中身 |
|---|---|---|
| typecheck | `cd desktop && cargo build --locked` | Rust はコンパイルが型検査。警告も 0 にする |
| | `python -m compileall -q -x desktop/target app.py sidecar.py lib tests .github/scripts desktop/selftest_runner.py` | Python の構文（Python の型検査の道具は入れていない） |
| | `node --check static/app.js` ／ `node --check desktop/src/selftest.js` | 画面と自己診断の JS の構文 |
| lint | `cd desktop && cargo fmt --check` | 整形（`desktop/rustfmt.toml`）。差分があれば `cargo fmt` |
| | `cd desktop && cargo clippy --locked --all-targets -- -D warnings` | 警告 0 |
| test | `python -m unittest discover -s tests -t .` | Python の試験（全ルートの突き合わせ・配る zip・install_local.cmd の形を含む） |
| | `cd desktop && cargo test --locked` | Rust の試験 |
| 自己診断 | `python desktop/selftest_runner.py desktop/target/debug/DataRelay --wrap "dbus-run-session -- xvfb-run -a" --modes full,close,restart,local` | `desktop/`・`static/`・`templates/`・`app.py`・`sidecar.py`・`lib/` を変えたとき。本物の WebView の中から確かめる |

- 自己診断の `update` の型は、入れ替えて起こし直した exe が画面を失わないよう、`xvfb-run` ではなく別に立てた Xvfb（`DISPLAY` を渡す）の上で流す。
- CI の失敗を直すときは、まず手元で同じ失敗を再現し、直したあと同じ確認が通ることを示してから push する。
- 手元で動かせないもの（Windows でしか動かない `install_local.cmd` など）は、静的な試験を足して手元で確かめられる部分を増やす。それでも確かめられない部分は、推測で直して push せず、確かめていないことを PR に書く。

## 2. レビュー指摘の修正は、まとめて1回で push する

- 指摘ごとに push しない。届いている指摘をすべて読み、すべて直し（直さないものは理由を決め）、上の 1 を green にしてから、1回で push する。
- コミットは指摘ごとに分けてよい。push を1回にする。
- push のあと、各スレッドに「どのコミットで何を直したか」を返す。直さないものは理由を返す。
- 理由: push のたびに Windows の CI（約 10 分）が回り、レビューする人も読み直しになるため。
