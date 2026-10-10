# DataRelay の作業の決まり

## 0. 返答・報告・解説は、常に日本語で書く

利用者への返答は、どんなに短くても日本語で書く。英語に戻さない。対象は次のすべて:

- 返答と解説
- 途中の一言（いま何をしているか）
- 状況報告（CI の結果、PR の状態、定期確認の結果、マージ、exe の配置）
- PR の説明

## 1. push の前に、手元で typecheck / lint / test を green にする

次をすべて手元で通してから push する。1つでも赤なら push しない。文書だけの変更でも同じ。
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

- 窓の Windows 向けの部分（`#[cfg(windows)]`）を変えたときは、`rustup target add x86_64-pc-windows-msvc` のうえで
  `cd desktop && cargo clippy --locked --target x86_64-pc-windows-msvc --all-targets -- -D warnings` も通す（Linux の確かめでは、その部分をコンパイルしない）。
  `GNU compiler is not supported for this target` は build script が資源（アイコン）を組めないという cargo の知らせで、clippy の警告ではない。
- 窓（`desktop/`。Tauri）を Linux で作るには WebKitGTK などが要る（`libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev`、自己診断には `xvfb dbus-x11`）。
- 自己診断の `update` の型は、入れ替えて起こし直した exe が画面を失わないよう、`xvfb-run` ではなく別に立てた Xvfb（`DISPLAY` を渡す）の上で流す。
- CI の失敗を直すときは、まず手元で同じ失敗を再現し、直したあと同じ確認が通ることを示してから push する。
- 手元で動かせないもの（Windows でしか動かない `install_local.cmd` など）は、静的な試験を足して手元で確かめられる部分を増やす。それでも確かめられない部分は、推測で直して push せず、確かめていないことを PR に書く。

## 2. レビュー指摘の修正は、まとめて1回で push する

- 指摘ごとに push しない。届いている指摘をすべて読み、すべて直し（直さないものは理由を決め）、上の 1 を green にしてから、1回で push する。
- コミットは指摘ごとに分けてよい。push を1回にする。
- push のあと、各スレッドに「どのコミットで何を直したか」を返す。直さないものは理由を返す。
- 理由: push のたびに Windows の CI（約 10 分）が回り、レビューする人も読み直しになるため。

## 3. UI/UX を変えるときは、7 案を画像で直接比べ、自分で 1 案に決めて作る

画面の見た目・使い方（UI/UX）を改良するときは、必ず次の順で設計する。案を文章だけで採点しない。
利用者に選んでもらわず、2 回目の評価で 1 案に決めて作る（作ったあと、比べた画像を比較のページで見せる）。

1. 今の画面を撮り、画像を見て評価する。何が使いにくいか・分かりにくいかを、画像で見えたことを根拠に挙げる
2. 改良案を **5 案**出す
3. 5 案のアイデアを見直し、考えが偏っていないか確かめる。**方向性の違う解決策を 2 案**足して **7 案**にする（例: 5 案がどれも「並べ方」の違いなら、「手順を分ける」「既定で済ませて例外だけ出す」のような別の解き方）
4. 7 案の画面を撮り、画像を直接見比べて採点する（1 回目）
5. 1 回目の 1 位が**低い**（85 点未満）か、1 位と 2 位が**僅差**（11 点より近い）なら、まだ決めない。各案の良いところ（エッセンス）を抜き出し、効きそうなアイデアにまとめ直した**組合せ案を 4 案**作る。**1 回目の上位 3 案**と合わせた 7 案を、また画像にして採点する（2 回目）
6. 2 回目の 1 位を作る。2 回目も僅差なら、「状態が一目で分かる」「次にすることが分かる」の合計が高い案を選ぶ（それも同じなら、押し間違えにくい案）。選んだ理由は記録に書く
7. 選んだ案を作ったら、作る前と後を撮って、画像と数で確かめる。比べた画像（1 回目・2 回目の全案と採点、作る前と後）は比較のページ（Artifact）で見せる

- 撮る大きさは利用者の PC（1728×1152・倍率 1.25。2160×1440 を 125% で使う）と、フル HD・125%（1536×864）。上位の案はダークでも見る（いまの画面にダークがあれば）
- 全案を並べた一覧で全体を見る。細部（隠れる・切れる・折り返す・空く）は 1 枚ずつの画像で見る
- 案の定義と採点は `tests/ui-proposals/` に比較ごとに残す（例: `2026-10-shortcut.js` と `2026-10-shortcut.json`。どの案をなぜ選んだかを、あとから読めるように。`tests/` は配る zip に入らない）
- **まだ無いもの**: 撮る・並べる・採点する道具（他のリポジトリにある `ui-check.mjs`・`ui-variants.mjs`・`ui_score.py` に当たる物）はこのリポジトリにまだ無い。
  それまでは Playwright で撮り、採点の基準（何を何点で見るか）は比較ごとに書いて残す。道具を入れたら、この節をその使い方に差し替える
