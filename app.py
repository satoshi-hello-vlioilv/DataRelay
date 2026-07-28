from __future__ import annotations
import atexit, calendar, configparser, csv, gc, json, logging, os, re, shutil, sqlite3, struct, subprocess, sys, tempfile, threading, time, traceback, uuid, webbrowser
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request

# 起動計測用: app.py の全モジュール取り込み完了時刻(wall clock)。
# Python はファイル全体をコンパイルしてから実行するため、この時点までに
# 「インタプリタ初期化＋app.pyのBOX読込＋コンパイル＋flask等の取り込み」が完了している。
_APP_IMPORT_DONE_AT=time.time()

APP_VERSION='1.18.2'; APP_VERSION_TITLE='データビュワーの3タブ化とExcel互換の階層ピボット・グラフ'; APP_RELEASED_AT='2026-07-28'
BUILD_VERSION=f'{APP_VERSION}-local-runtime-cleanup-launch-guard'; BASE=Path(__file__).resolve().parent; LOCAL_ROOT=Path(os.environ['NAVI_LOCAL_ROOT']) if os.environ.get('NAVI_LOCAL_ROOT') else Path(os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home())/'SymfoNaviDataHub'; LOCAL_RUNTIME=LOCAL_ROOT/'runtime'; LOCAL_LOGS=LOCAL_ROOT/'logs'; LOCAL_BACKUP=LOCAL_ROOT/'backup'; [x.mkdir(parents=True,exist_ok=True) for x in (LOCAL_RUNTIME,LOCAL_LOGS,LOCAL_BACKUP)]; CONFIG_DIR=BASE/'Config'; CONFIG_DIR.mkdir(parents=True,exist_ok=True); SETTINGS_DB=CONFIG_DIR/'app_settings.sqlite3'; OLD_SETTINGS_DB=BASE/'app_settings.sqlite3'; LEGACY_CFG=BASE/'config.json'; HOST='127.0.0.1'; PORT=5031
# アプリ内バージョン履歴。新しいリリースを配布する際は先頭へ1件追加する。
CHANGELOG=[
{'version':'1.18.2','date':APP_RELEASED_AT,'title':'データビュワーの集計表・グラフのレイアウト崩れ修正','notes':[
'集計表・グラフで、値・列・行のドロップゾーンが左側に縦積みになり、集計表やグラフの描画領域（メイン表示領域）が画面外へ回り込んでいた不具合を修正しました。',
'原因は、ページ全体のレイアウト用に定義していた素の main 要素のスタイル（grid-row:2 / overflow:hidden / 中央寄せ）が、分析パネルの描画領域（main要素）にも波及し、描画領域が左の狭い列（カラムリストの真下）へ押し込まれていたことです。',
'描画領域とカラムリストの要素を通常のブロック要素へ変更し、当該スタイルの波及を根本的に断ちました。あわせてグリッド配置を明示し、左＝カラムリスト／右＝描画領域（縦横のドロップゾーンと集計表・グラフ）が確実に表示されるようにしました。',
'この修正により、ドロップ配置した集計表・グラフが描画領域に正しく表示されるようになりました。',
]},
{'version':'1.18.1','date':APP_RELEASED_AT,'title':'データビュワーのタブ表示切替の修正（hidden属性の尊重）','notes':[
'「データ一覧」「集計表」「グラフ」「空状態」が同時に表示され、タブを切り替えても表示が変わらない不具合を修正しました。',
'原因は、パネルへ指定した display（!important）がブラウザ標準の hidden 属性（display:none）を上書きしていたことです。スコープ付きの指定で hidden を確実に有効化し、選択中のパネルだけを表示するようにしました。',
]},
{'version':'1.18.0','date':APP_RELEASED_AT,'title':'データビュワーの3タブ化とExcel互換の階層ピボット・グラフ','notes':[
'データビュワーを「データ一覧」「集計表」「グラフ」の3タブ構成へ再設計し、表示領域を最大限に使えるようにしました。まず初期画面のデータ一覧に読み取ったデータを表形式で表示します。',
'「集計表」「グラフ」では左側にカラムリストのメニューを配置し、残りの大部分を描画領域としました。描画領域には縦（行）・横（列）・値のドロップゾーンを用意し、カラムリストからドラッグして配置することで集計表やグラフを生成します。',
'行・列に複数カラムを配置すると、Excelのピボットテーブルと同様に階層化された集計になります。各階層の小計と総計（行方向・列方向の両方）を自動で付与します。',
'1つのカラムだけでも、カウント（グルーピング集計）または合計・平均・最小・最大の集計を選べます。カウント以外では値へ数値カラムを配置します。平均は非数値を除外して算出します。',
'グラフは縦棒・横棒・折れ線に対応し、列フィールドを配置した場合は系列として色分け表示します。',
'認知心理学(タブによるモードの明確な分離・近接・即時フィードバック) / 情報アーキテクチャ(一覧→集計→可視化の段階、カラムリスト→行列値ゾーン) / 色彩調和(既存ティール基調・行/列/値と小計/総計の階調)。',
]},
{'version':'1.15.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':['ハートビート状態をリアルタイム表示し、最終受信・通信遅延・連続失敗・再接続回数を確認できるようにしました。','一時的なWeb接続断ではFlask/Pythonを自動終了しない方式へ変更し、接続復旧後に同じ画面から自動再接続します。','設定DBをConfig\\app_settings.sqlite3へ移動し、旧配置から初回起動時に安全に移行します。','バックアップのON/OFFと保存期間を追加しました。既定はON、30日です。'],},
 {'version':'1.14.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':['対象一覧は出力先リンクだけでフォルダーを開き、それ以外の行ダブルクリックは編集へ統一。右クリックメニューを追加しました。','データビュワーのスライサーと表示列設定を廃止し、標準リストとドラッグ＆ドロップ式2軸集計を切替可能にしました。','DLL診断にPython/DLLのbit数と選定理由を表示。API並列の既定値を6、最大値を24へ拡張しました。']},
 {'version':'1.13.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':['ビュワー上部を一段のコンパクト操作バーへ統合し、データ表示行数を最大化しました。','スライサーを、選択カラムに含まれる値で絞り込む機能へ変更し、列の表示・非表示は専用モーダルへ分離しました。','C:\\NAVIAPのローカルDLLを最優先し、利用可能なDLLがない場合だけConfig\\NAVIAPを使用します。自動コピーは行いません。']},
 {'version':'1.12.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':['製品側C:\\NAVIAPの4フォルダーをConfig\\NAVIAPへ依存DLLごと同期し、そこから利用する方式へ変更しました。','データビュワーを高密度化し、最大10万行の読込、カラムスライサー、列見出しクリックによる並べ替えに対応しました。','進捗画面と処理結果へ対象別の詳しい失敗理由を表示します。']},
 {'version':'1.11.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':['DLL診断へ問題分類と対処方法を追加しました。','公開済みの抽出データを読み取り専用で確認できるデータビュワーを追加しました。SQLite3、CSV、TXT、XLSX、ACCDBに対応します。','検索、50行単位のページ切替、固定ヘッダーおよび行番号に対応しました。']},
 {'version':'1.10.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':[
  'SymNaviA.dllの自動検出をC:\\NAVIAP配下のdebugdllVC*/dllVC*へ拡張し、VC10～VC14および将来のVC番号、x64あり・なしの両方を検索対象にしました。',
  '設定したDLLパスを最優先しつつ、存在・DLL bit数・Python bit数を評価して利用可能な候補を選びます。',
  'Navigator APIの設定内へDLLパス、確認、参照、診断結果を集約し、共通診断にも候補探索結果を反映しました。',
  '情報の近接、一貫した状態色、設定から診断までの一本道を重視してUIを再設計しました。',
 ]},
 {'version':'1.9.0','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':[
  'ファイル名の変数タグを高度化しました。時（H）・分（I）・秒（S）にも桁数「1桁」を追加し、時刻に関するタグも1桁で指定できるようにしました（例: h→9、hh→09）。年・月・日と同様に、使う部分ごとに1桁/2桁（年は2桁/4桁）を選んで直感的に桁を調整できます（要望1）。',
  'ファイル出力管理単位の一覧を、ドラッグ&ドロップで並べ替えできるようにしました。並び順はそのまま問い合わせ（実行）順に反映され、変更は即時保存されます。並べ替えは「登録順」表示かつ検索・絞り込みを解除している状態で有効になり、各行のドラッグハンドルから操作します（要望2-①）。',
  '一覧の各管理単位に「削除」を追加しました。確認のうえ、その管理単位の登録内容と自動実行ルールを削除し、即時保存します（要望2-②）。',
  'カレンダーの実施記録（実績）を削除できるようにしました。日別ダイアログの各実績の「削除」で1件ずつ、または「この日の実績を全削除」でまとめて削除できます（対象の絞り込み中はその対象のみ）。削除後はカレンダーと一覧の直前実施履歴へ即時反映します（要望3）。',
  '認知心理学(操作アフォーダンスの明示・破壊操作の抑制的配色・即時フィードバック) / 情報アーキテクチャ(並び順=問い合わせ順の一貫性) / 色彩調和(既存パレット踏襲・削除は警告系で統一)。',
 ]},
 {'version':'1.8.0','date':APP_RELEASED_AT,'title':'日付変数タグの高度化（対象×桁数×日付計算の統合ビルダー）','notes':[
  '日付・時刻の変数タグビルダーを刷新し、「①日付の対象」「②日付の計算」「③使う部分と桁数」を1か所で組み合わせて1つのタグを作れるようにしました。専用タグの乱立をやめ、直感的な操作へ統合しました（要望1-①②③）。',
  '日付の計算（要望1-③）を追加しました。基準日（現在日時／対象ファイル更新日／対象ファイル作成日）を軸に、年・月・週・日・時・分・秒を前後へずらせます。ExcelのEDATE関数やVBAのDateAddのように「Nヶ月前」「N年後」などをタグへ組み込めます（例: 前月度、前年、過去7日基準）。月末を跨ぐ計算はEDATE同様に月末へ丸めます。',
  '対象と桁数の組み合わせ（要望1-①②）を強化しました。対象を選び、年/月/日/時/分/秒それぞれの桁数（Y/M/D の数）を選ぶだけで、YYYYMMDD→20260726、YYYYMD→2026726 のような微調整を、生成タグと実例を見ながら直感的に行えます。対象を切り替えても桁数・計算の設定は保持されます。',
  '生成されるタグに日付計算を反映しました（例: {now-1M:YYYYMM}、{rne_ctime+1Y:YYYYMMDD}）。命名パターンへ直接記入する場合も、対象名の直後へ +N/-N（Y=年 M=月 W=週 D=日 H=時 I=分 S=秒）を並べて指定できます。プレビューは処理日時を基準に実ファイル名を即時試算します。',
  '認知心理学(操作の統合・近接・即時フィードバック) / 情報アーキテクチャ(対象→計算→桁数の一貫した順序) / 色彩調和(既存パレット踏襲・日付計算は補助色で区別)。',
 ]},
 {'version':'1.7.0','date':APP_RELEASED_AT,'title':'RNE時間管理ポイントの相対期間（動的日付）指定に対応','notes':[
  'RNEに定義済みの時間型管理ポイントに対し、実行時の処理日時を基準にした相対期間（動的日付）で抽出範囲を自動指定できるようにしました。RNEやカラム指定は変更せず、期間だけをAPI実行直前に差し替えます（Navigator APIのNaviChangePeriodを使用）。',
  '対象ファイル設定モーダルの入出力タブに「抽出期間（動的日付）」セクションを新設しました。単位（月度／年月日）と、開始・終了の相対オフセット（当月／当日を基準に前後Nを指定）を、認知心理学の近接・一貫性に沿ったコンパクトなUIで設定できます。',
  '設定した相対期間から実際に抽出される期間を、その場でリアルタイムにプレビュー表示します（例: 2026年6月度 ～ 2026年7月度）。よく使う組み合わせ（前月・今月・当日・前日・過去7日・月初〜現在など）をワンクリックで適用できるプリセットも用意しました。',
  '対象RNE内の時間型管理ポイントを自動検出する「候補を取得」を追加しました（Navigator API方式で接続可能な場合）。検出できない環境でも管理ポイント名の手入力、または時間フィールドの自動選択で動作します。',
  '期間が有効なジョブでは、実行ログに適用した単位・開始終了・対象管理ポイントを記録し、定期実行でもどの期間で抽出したかを後から追跡できるようにしました。',
  '認知心理学(近接・即時フィードバック・一貫性) / 情報アーキテクチャ(入力データ内での期間条件の階層化) / 色彩調和(既存パレット踏襲・入力系の系統色)。',
 ]},
 {'version':'1.6.0','date':APP_RELEASED_AT,'title':'日付変数タグの対象選択と桁数調整の統合・変数由来の色分けを文字色のみへ','notes':[
  '日付・時刻の変数タグに「日付の対象」の選択を追加しました。現在日時／対象ファイル更新日／対象ファイル作成日の中から対象を選び、そのまま桁数（Y/M/D の数）の指定と組み合わせて1つのタグを生成できます。例: 対象ファイル更新日 + YYYYMD で {rne_mtime:YYYYMD} → 2026726。（認知心理学: 選択→桁調整の一連操作への統合）',
  '対象ごとに別々だった日付専用タグ（RNE更新日・RNE作成日など）を、上記のタグビルダーへ集約しました。専用タグの乱立をやめ、対象の切り替えと桁数調整を同じ場所で直感的に行えるようにしました（情報アーキテクチャ: 役割の一元化）。',
  '直接入力での桁数調整（YYYYMMDD→20260726、YYYYMD→2026726 のように Y/M/D の記号数がそのまま桁数）も従来どおり利用でき、タグビルダーの生成結果と一致します（一貫性）。',
  '出力ファイル名の一覧で、変数由来の部分の強調をマーカー（背景色）から文字色のみの区別へ変更しました。変数バッジとの視覚的な衝突を解消しました（色彩調和: 状態表現の役割分担）。',
  '認知心理学(操作の統合・近接・一貫性) / 情報アーキテクチャ(役割の一元化) / 色彩調和(強調手段の整理)。',
 ]},
 {'version':'1.5.0','date':APP_RELEASED_AT,'title':'複数キュー表示の是正・変数タグの刷新・変数由来の色分け・用途コメント欄','notes':[
  '複数キュー処理の表示不具合を修正しました。実行キュー要約バッジを「処理中／完了／失敗／待機」の対象(ファイル)単位の実状態へ連動させ、進捗と件数が一致するようにしました（状態の即時フィードバック）。',
  '一覧の進捗表示で、完了したはずの対象が「順番待ち」コメントへ戻り、進捗バーの色も待機色へ戻ってしまう不具合を修正しました。バックエンドが対象ごとの確定状態(完了/失敗)を保持し、完了は緑のまま最後まで固定します。',
  'ファイル名の変数扱い判定を是正しました。変数欄へ文字を入力しただけ（固定文字）では変数バッジを表示せず、実際に {変数} が使われている場合のみ変数として扱います（実処理での判定）。',
  '日付・時刻の変数タグを刷新しました。使う部分(年/月/日/時/分/秒)をONにして桁数を選ぶだけで、Excelの書式設定のように Y/M/D の数で桁が決まる分かりやすいタグへ変更しました。生成されるタグと実例をその場で確認できます。',
  '出力ファイル名の一覧・プレビューで、元が変数である部分に色を付けて識別できるようにしました（固定文字と変数の視覚的な区別）。',
  '出力対象ごとに用途・メモを記録できるコメント欄を追加しました。一覧にも表示され、検索の対象になります（情報の追跡性）。',
  '認知心理学(状態の即時フィードバック・近接・一貫性) / 情報アーキテクチャ(役割別階層) / 色彩調和(既存パレット踏襲・状態色の統一)。',
 ]},
 {'version':'1.4.0','date':APP_RELEASED_AT,'title':'自動実行スケジュールUIのプリセット(サジェスト)化と寸法安定化','notes':[
  '自動実行ルールの設定モーダルに「おすすめの組み合わせ」プリセット(サジェスト)を新設しました。平日始業前(月〜金 8:30)・平日昼休み・平日終業後・毎日夜間/早朝・1時間ごと・30分ごと・月初・月末など実務で多い組み合わせを、クリック1回で名称・時刻・実行パターンまで一括入力できます。適用後も各項目を個別に調整でき、カスタム性を保ちます（認知心理学: 選択肢のチャンク化と素早い開始点の提示）。',
  '現在のフォーム内容と一致するプリセットを自動でハイライトし、どの組み合わせが選ばれているかを一目で把握できるようにしました。手入力で条件を変えるとハイライトも即座に追従します（一貫性・フィードバックの明確化）。',
  '実行パターン（毎日／曜日／月の日付／一定間隔／特定日）を切り替えても、詳細条件エリアの高さを余裕を持って固定し、モーダルの寸法が変化しないようにしました。プリセット追加後も本文の高さに余白を確保し、ミニカレンダー表示時でも寸法が安定します（情報アーキテクチャ・レイアウトの一貫性）。',
  'プリセットの識別記号（週／毎／月／間）を実行パターン種別ごとの系統色（曜日=青、毎日=ティール、月=緑、間隔=紫）で色分けし、既存パレットと調和させました（色彩調和）。',
 ]},
 {'version':'1.3.0','date':APP_RELEASED_AT,'title':'自動実行UIの寸法安定化・命名パターンのコンパクト化＋カスタム・抽出方式への設定集約・カレンダー配色と余白調整','notes':[
  '自動実行スケジュールのルール設定モーダルで、実行パターン（毎日／曜日／月の日付／一定間隔／特定日）を切り替えても本文領域の高さを固定し、モーダルの寸法がころころ変化しないようにしました。あわせて、設定内容から実行タイミングを日本語で常時表示する確認欄を追加しました（一貫性の維持による認知負荷の低減）。',
  'ファイル命名パターンのUIを整理しました。散らかりやすいタグ形式のボタンは「よく使う組み合わせ／よく使う変数」に代表を絞ってコンパクトに常設し、細かい桁数調整や対象ファイル日付などの詳細は「カスタム」折りたたみへ集約しました。カスタム冒頭に変数の仕組み（{ } と : 書式）の説明を追加し、構造を理解しやすくしました（情報アーキテクチャの階層化）。',
  '共通設定を再編し、「抽出方式」を選ぶとその方式で必要な設定だけを同じ画面へ表示するようにしました。Navigator API選択時は並列処理（API専用）とDLL診断を、DDE互換選択時は待機時間と画面制御をまとめて表示します。関連する設定が一箇所に集まり、設定すべき項目が把握しやすくなりました（関連性のグルーピング）。',
  'カレンダービューの配色を「予定（時刻指定・一定間隔）」と「実績（完了・中断・失敗）」の2系統へ階層的に整理し、凡例もグループ表示にしました。一定間隔の色を予定系の寒色に合わせて調和させています。カレンダー表示領域の縦方向の余白を表示エリアに合わせて微調整し、下部の詰まりを解消しました（色彩調和と余白設計）。',
 ]},
 {'version':'1.2.0','date':APP_RELEASED_AT,'title':'自動実行スケジュールUIの刷新・記号数で桁調整できる命名・キュー内訳表示・カレンダービュー','notes':[
  '自動実行ルールの設定UIを刷新しました。実行パターンをカード型セグメントで選び、時刻はフローティングの時刻ピッカー、曜日はトグルチップ、月の日付は31日グリッド＋月末チップ、特定日はカレンダーから複数日を選択できるようにしました。文字サイズと余白を統一し視認性を高めました（認知心理学の近接・一貫性）。',
  'ファイル命名で年月日時分秒の桁数を「記号の数」で調整できるようにしました。YYYYMD・YYMMDD・h:s のように、Y/M/D/h/m/s の連続数がそのまま桁数（ゼロ埋め幅）になります。命名パターンへ直接入力する桁数ビルダーとチップを追加しました。',
  '実行キューの内訳を一覧化しました。ヘッダーのキュー要約に「定期 N件／即実行 M件／待機 K件」を常時表示し、種別ごとの件数が一目で分かるようにしました。',
  'カレンダービューを新設しました。予定（自動実行）と実施済みの履歴を月カレンダー上に色分け表示し、日クリックで当日の予定・実績の確認、対象編集への遷移、単発実行ルールの追加ができます（情報アーキテクチャ／色彩調和）。',
 ]},
 {'version':'1.1.0','date':'2026-07-26','title':'命名プレビューの近接配置・桁数調整・タブ切替時のモーダル寸法固定','notes':[
  '対象ファイル設定モーダルで「自動実行」タブへ切り替えても本文領域の高さを固定し、タブ切替時にモーダルの寸法が変化しないようにしました（一貫性の維持による認知負荷の低減）。',
  '変数命名のプレビューを命名パターン入力欄の直下へ移動し、入力（原因）と結果（プレビュー）を近接配置しました。パターンを打ち込んだ結果が即座に理解できます。',
  '日付・時刻の桁数を調整できるよう命名チップを拡充しました。YYYYMMDD／YYMMDD／YYYYMM／YYMM／HHMMSS／HHMM に加え、年4桁・年2桁・月・日・時・分・秒を個別に挿入できます（:などファイル名に使えない文字は自動除去する旨も明記）。',
  'ヘッダーのバージョンバッジの番号左側に「ver」を付与し、表示中のバージョンであることを明確にしました。',
 ]},
 {'version':'1.0.0','date':'2026-07-26','title':'出力形式の位置最適化・自動実行のタブ分離・バージョン体系の刷新','notes':[
  '出力形式（拡張子）の選択を出力ファイル名のすぐ隣へ移動し、形式を変えると最終ファイル名の拡張子が変わることを視覚的に把握できるようにしました。固定名の入力欄には拡張子を含めず、拡張子は出力形式から自動付与する方式へ統一しました（固定名と拡張子の競合を解消）。',
  '対象ファイル設定モーダルをタブ構成（「基本・入出力」と「自動実行」）へ再編し、スクロールレスで全項目を見渡せるようにしました。設定項目を役割ごとの階層へ整理し、認知負荷を下げました。',
  'バージョン番号をV表記からセマンティックバージョニング（1.0.0形式）へ全面刷新し、これまでの更新履歴を 1.0.0 に至る系譜として振り直しました。',
 ]},
 {'version':'0.12.0','date':'2026-07-26','title':'設定モーダル再構成・並列既定2・ハートビート誤検知修正','notes':[
  '対象ファイル設定モーダルを情報アーキテクチャに沿って再構成しました。出力ファイル名を管理名称の直下へ移動し、入力データ（RNE・読込シート・読込形式）と出力データ（出力形式・出力先・テーブル名）を階層で分離しました。',
  '並列実行の既定を2ラインへ変更しました。読込のたびに1ラインへ戻していた旧テスト実装の名残を除去し、ユーザーが変更した並列ライン数は即時保存され、次回起動以降も保持されます。',
  'ブラウザーのタブを切り替えて非アクティブにしただけの状態を「閉じられた」と誤検知してアプリを終了する不具合を修正しました。バックグラウンド抑制を考慮して無音判定を200秒へ拡大し、タブを実際に閉じた時だけビーコンで即時判定します（リロード・タブ切替では終了しません）。',
  '処理の都合で使わなくなった空フォルダー（.\\work）の自動生成を廃止しました。中間・変換ファイルは従来どおりローカル作業領域のみで作成します。',
 ]},
 {'version':'0.11.0','date':'2026-07-26','title':'一覧進捗の刷新と変数ファイル名','notes':[
  '対象ファイル一覧の進捗列を再設計し、進捗バーのはみ出しと列幅の不均衡を解消しました。列幅を役割ごとに最適化し、横スクロール依存を抑えました。',
  '各対象へ「直前の実施日時」と結果（完了／失敗／中断）・実行区分（手動／定期）を常時表示し、バッチ実行や定期実行が完了したかどうかを一覧で確認できるようにしました。',
  '出力ファイル名に変数（実行日時、対象RNEの更新日・作成日、RNE名の文字列操作など）を組み合わせて指定できる動的命名機能を追加しました。命名ビルダーとリアルタイムプレビューを搭載しています。',
  '実行のたびに変数を展開して命名するため、同一処理でも日付別などでファイルを蓄積できます。展開後の実ファイル名を実行ログへ記録します。',
 ]},
 {'version':'0.10.0','date':'2026-07-25','title':'ブラウザーとアプリ稼働状態の同期','notes':[
  'コマンドプロンプトを表示しない start.vbs を追加しました（初回セットアップは引き続きstart.batを使用します）。',
  '実行中にブラウザーを閉じようとすると警告が表示されるようにし、「アプリを終了」ボタンからは確認のうえ実行を中断して終了できるようにしました。',
  '実行中のジョブと実行キューを中断するAPIを追加しました（並列(プロセス分離)ラインは即時終了、直列実行は安全な区切りまで進めてから停止します）。',
  'サーバーへの接続が失われた場合に、その旨をブラウザー画面へ明示し、タブを閉じるよう案内する通知を追加しました。',
 ]},
 {'version':'0.9.0','date':'2026-07-25','title':'ハートビート監視によるゾンビプロセス防止','notes':[
  'ブラウザー側から10秒間隔でハートビートを送信し、バックエンドが生存を確認するようにしました。',
  '45秒以上ハートビートが途絶えた場合、実行中のジョブが無く、かつ有効な自動実行ルールも無いときに限り、アプリが自動的に終了するようにしました。',
  'タブを閉じ忘れた場合でもPythonプロセスが残り続けないようにする一方、自動実行スケジュールがある場合は無人稼働を継続します。',
 ]},
 {'version':'0.8.0','date':'2026-07-25','title':'対象ファイル一覧への進捗統合表示','notes':[
  '対象ファイル一覧の「自動実行」列を「進捗・次回実行」列へ再設計し、直近の開始予定時刻と予定の種類（手動のみ／定期／複数指定など）を表示するようにしました。',
  '実行中・実行キュー待ちの対象は、一覧の該当行がそのまま進捗バーへ切り替わり、工程・経過時間を確認できるようにしました。',
  '進捗表示中の行をクリックすると、詳細な進捗モーダルを直接開けるようにしました。',
 ]},
 {'version':'0.7.0','date':'2026-07-25','title':'ヘッダーと並列進捗表示のUIUX改善','notes':[
  'ヘッダーのバージョン表示をアプリ名の直後へ移動し、状態表示・操作ボタンを役割ごとに区切り線で整理しました。',
  '並列実行の進捗レーンを、ライン数に応じて自動的に列数が変わるグリッド表示へ変更し、最大8ラインでも縦に伸びすぎず見やすく収まるようにしました。',
  '並列実行時の進捗モーダル幅を拡張し、レーン数が多い場合でも余裕を持って表示できるようにしました。',
 ]},
 {'version':'0.6.0','date':'2026-07-25','title':'設定画面の再構成とバージョン管理','notes':[
  '共通設定を「接続とパス／抽出方式／並列実行／DDE互換設定／安全性とバックアップ／バージョン情報」のカテゴリー別ナビゲーション構成へ再編しました。',
  'API方式選択時にもDDE専用項目（DDE接続待機・XLS生成待機）が常に表示されていた構成を見直し、選択中の抽出方式に応じて使用状況を明示するようにしました。',
  'ヘッダーのバージョン表示と共通設定内の「バージョン情報」から、アプリ内で更新履歴を確認できるようにしました。',
 ]},
 {'version':'0.5.0','date':'2026-07-25','title':'進捗の縦積み表示とログ管理機能の強化','notes':[
  '並列実行の進捗表示を横並びから縦積みレイアウトへ変更しました。',
  '実行ログへ種別（実行処理／設定変更／実行キュー／性能計測／公開処理／エラー）の色分け表示を追加しました。',
  'ログの検索語・種別・レベルによるフィルター機能と、フィルター結果や選択行をまとめてコピーする機能を追加しました。',
  '保存期間を指定した古いログの一括削除、および選択行・表示結果の削除機能を追加しました。',
 ]},
 {'version':'0.4.0','date':'','title':'実行キューの可視化','notes':['実行待ちの対象と処理順序を一覧表示し、順序変更・解除を行えるようにしました。']},
 {'version':'0.3.0','date':'','title':'並列進捗モーダルの安定化','notes':['並列実行レーンの状態表示と、進捗モーダルの再表示導線を整備しました。（旧V17〜V20）']},
 {'version':'0.2.0','date':'','title':'API並列実行の導入','notes':['API方式による複数ライン同時実行と、プロセス分離方式の予約キュー管理を追加しました。（旧V13〜V16）']},
 {'version':'0.1.0','date':'','title':'基本レイアウトとログ基盤の整備','notes':['1画面に収まるレイアウトへ変更し、実行ログを工程単位でレポート化しました。（旧V7〜V12）']},
]
APP_ID='SymfoNaviDataHub'; INSTANCE_ID=str(uuid.uuid4()); app=Flask(__name__); app.config['SEND_FILE_MAX_AGE_DEFAULT']=0; run_lock=threading.Lock(); stop_event=threading.Event(); status_lock=threading.Lock(); command_queue_lock=threading.RLock(); command_queue_event=threading.Event(); command_queue=[]; active_command=None
# ブラウザー側ハートビート監視。フロントからの生存信号が途絶えたら、ジョブ実行中でなく、
# かつ有効な自動実行ルールも無い場合にだけ自プロセスを終了し、閉じ忘れによるゾンビ化を防ぐ。
# 0.12.0（旧V36）: 非アクティブ（タブ切替）でもブラウザーは生存しているため、バックグラウンド時のタイマー抑制（多くのブラウザーで最悪1分に1回程度まで低速化）を考慮し、
# ハートビート途絶の判定しきい値を余裕を持って200秒へ拡大する。加えてタブが実際に閉じられた場合は明示シグナルで即時判定する。
HEARTBEAT_TIMEOUT_SECONDS=200; CLOSE_GRACE_SECONDS=12; heartbeat_lock=threading.Lock(); last_heartbeat_at=time.time(); browser_closed_explicit=False; browser_closing_at=0.0; heartbeat_clients={}; heartbeat_total=0
# 実行中断（ユーザーによる明示キャンセル）。プロセス分離ワーカーはterminateで即時停止できるが、
# 直列(DDE/API)実行中の1件はCOM/DDE操作の途中で安全に打ち切れないため、次のジョブ開始前でのみ打ち切る。
cancel_requested=threading.Event(); active_workers_lock=threading.Lock(); active_workers={}
class RunCancelled(Exception):pass
status={'build_version':BUILD_VERSION,'running':False,'current':'','current_job_id':'','current_job_name':'','current_index':0,'total_jobs':0,'step':'idle','step_label':'待機中','step_percent':0,'completed_jobs':0,'failed_jobs':0,'started_at':'','elapsed_seconds':0,'symnavi_window':'未起動','last_result':'未実行','last_finished_at':'','error_detail':'','activity_detail':'','activity_value':'','heartbeat_at':'','parallel_lines':[],'batch_job_ids':[],'queue_completed_ids':[],'queue_failed_ids':[],'queue_running_ids':[],'queue_waiting_ids':[],'job_errors':[]}
log=logging.getLogger('navi'); log.setLevel(logging.INFO)
if not log.handlers:
 h=logging.FileHandler(LOCAL_LOGS/'app.log',encoding='utf-8'); h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')); log.addHandler(h)
# COMオブジェクトの明示解放が正常経路で数秒停止する環境があるため、
# Quit済みAccess.Applicationの参照だけをプロセス内に遅延保持する。
# データ作成・件数検査・Quit完了後なので、出力精度には影響させない。
_deferred_com_refs=[]
def defer_com_reference(label,obj,limit=20):
 try:
  if obj is not None:
   _deferred_com_refs.append((label,obj,time.time()))
   if len(_deferred_com_refs)>limit:del _deferred_com_refs[:len(_deferred_com_refs)-limit]
 except Exception:pass

def settings_connection():
 c=sqlite3.connect(SETTINGS_DB,timeout=30)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 return c

def init_settings_db():
 CONFIG_DIR.mkdir(parents=True,exist_ok=True)
 if not SETTINGS_DB.exists() and OLD_SETTINGS_DB.is_file():
  shutil.copy2(OLD_SETTINGS_DB,SETTINGS_DB)
  log.info('設定DBを移行しました old=%s new=%s',OLD_SETTINGS_DB,SETTINGS_DB)
 with settings_connection() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL,value_type TEXT NOT NULL DEFAULT 'text',updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,display_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,name TEXT NOT NULL,rne TEXT NOT NULL,rne_path TEXT NOT NULL,output_folder TEXT NOT NULL,output_format TEXT NOT NULL,output_file TEXT NOT NULL,table_name TEXT NOT NULL,sheet_name TEXT NOT NULL,read_type TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY,job_id TEXT NOT NULL,display_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,name TEXT NOT NULL,schedule_type TEXT NOT NULL,time_value TEXT,interval_minutes INTEGER,weekdays_json TEXT,month_days_json TEXT,dates_json TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
  CREATE TABLE IF NOT EXISTS scheduler_state (state_key TEXT PRIMARY KEY,state_value TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS job_runs (job_id TEXT PRIMARY KEY,job_name TEXT,finished_at TEXT,status TEXT,trigger TEXT,detail TEXT,rows INTEGER,cols INTEGER,output_file TEXT,updated_at TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS run_history (id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,job_name TEXT,finished_at TEXT,status TEXT,trigger TEXT,detail TEXT,rows INTEGER,cols INTEGER,output_file TEXT);
  CREATE INDEX IF NOT EXISTS idx_run_history_finished ON run_history(finished_at);
  """)
  c.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('schema_version','2')")
 ensure_schema_upgrades()

def ensure_schema_upgrades():
 # 既存DBへ後方互換で列を追加する。動的命名（naming_mode / output_pattern）・用途コメント（comment）用。
 with settings_connection() as c:
  cols=[r['name'] for r in c.execute('PRAGMA table_info(jobs)')]
  if 'naming_mode' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN naming_mode TEXT NOT NULL DEFAULT 'fixed'")
  if 'output_pattern' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN output_pattern TEXT NOT NULL DEFAULT ''")
  if 'comment' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN comment TEXT NOT NULL DEFAULT ''")
  if 'period_json' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN period_json TEXT NOT NULL DEFAULT ''")

def _decode_setting(row):
 v=row['value']; t=row['value_type']
 if t=='json':return json.loads(v)
 if t=='bool':return v=='1'
 if t=='int':return int(v)
 return v

def _encode_setting(value):
 if isinstance(value,bool):return ('1' if value else '0','bool')
 if isinstance(value,int):return (str(value),'int')
 if isinstance(value,(dict,list)):return (json.dumps(value,ensure_ascii=False),'json')
 return (str(value),'text')

def _decode_period(raw):
 # ジョブごとの相対期間（動的日付）設定を後方互換で読み出す。未設定は無効扱い。
 try:d=json.loads(raw) if raw else {}
 except Exception:d={}
 if not isinstance(d,dict):d={}
 unit=d.get('unit'); unit=unit if unit in ('month','day') else 'month'
 def _int(v,default=0):
  try:return int(v)
  except Exception:return default
 return {'enabled':bool(d.get('enabled',False)),'control_point':str(d.get('control_point') or '').strip(),'unit':unit,'from_offset':_int(d.get('from_offset',0)),'to_offset':_int(d.get('to_offset',0))}

def normalize_output_format(value,filename=''):
 fmt=str(value or '').strip().lower()
 aliases={'sqlite':'sqlite3','db':'sqlite3','access':'accdb','excel':'xlsx','xls':'xlsx'}
 fmt=aliases.get(fmt,fmt)
 ext=Path(str(filename or '')).suffix.lower()
 ext_map={'.sqlite':'sqlite3','.sqlite3':'sqlite3','.db':'sqlite3','.accdb':'accdb','.xlsx':'xlsx','.csv':'csv','.txt':'txt'}
 if fmt not in ('sqlite3','txt','csv','xlsx','accdb'):fmt=ext_map.get(ext,'sqlite3')
 return fmt

def output_extension(fmt):
 return {'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}.get(fmt,'.sqlite3')
def canonical_output_file(filename,fmt):
 ext={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[fmt]
 stem=Path(str(filename or 'output')).stem
 for suffix in ('sqlite3','sqlite','accdb','xlsx','xls','csv','txt'):
  if stem.lower().endswith(suffix):stem=stem[:-len(suffix)]
 return (stem or 'output')+ext

def validate_output_contract(job,stage):
 configured=str(job.get('output_format') or '').lower(); filename=str(job.get('output_file') or '')
 effective=normalize_output_format(configured,filename); expected={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[effective]; actual=Path(filename).suffix.lower(); match=configured==effective and actual==expected
 log.info('出力形式確認 stage=%s job=%s configured=%s effective=%s file=%s actual_ext=%s expected_ext=%s match=%s',stage,job.get('name'),configured,effective,filename,actual or '(なし)',expected,match)
 if not match:raise ValueError(f'出力形式不一致: 設定={configured}, 実効={effective}, ファイル={filename}, 期待拡張子={expected}')
 return effective

# ---- 動的ファイル名（変数命名）----------------------------------------------
# 出力ファイル名に変数を埋め込み、実行のたびに展開する。
#   日付系: {now:%Y%m%d} {exec:...} {datetime} {date} {time} {rne_mtime:%Y%m%d} {rne_ctime:%Y%m%d}
#   文字列系: {rne} {rne:left:4} {rne:right:3} {rne:mid:2:3} {rne:upper} {rne:replace:A:B} {name} {table}
_ILLEGAL_FILENAME=re.compile(r'[\\/:*?"<>|]')
# 記号の数で桁数を調整できる日付書式（%を使わない簡易パターン）。
# Y=年 / M=月 / D(またはd)=日 / H(またはh)=時(24h) / m=分 / s=秒。連続した同一記号の数がそのまま桁数（ゼロ埋め幅）になる。
# 例: {date:YYYYMD} -> 年4桁+月1桁+日1桁 / {date:YYMMDD} -> 年2桁+月2桁+日2桁 / {time:h:s} -> 時:秒。
_CUSTOM_DATE_TOKEN=re.compile(r'(Y+|M+|D+|d+|H+|h+|m+|s+|[^YMDHhmsd]+)')
def format_custom_datetime(dt,pattern):
 if dt is None:return ''
 out=[]
 for run in _CUSTOM_DATE_TOKEN.findall(str(pattern or '')):
  ch=run[0];n=len(run)
  if ch=='Y':out.append(str(dt.year%(10**n)).zfill(n) if n<4 else f'{dt.year:0{n}d}')
  elif ch=='M':out.append(f'{dt.month:0{n}d}')
  elif ch in ('D','d'):out.append(f'{dt.day:0{n}d}')
  elif ch in ('H','h'):out.append(f'{dt.hour:0{n}d}')
  elif ch=='m':out.append(f'{dt.minute:0{n}d}')
  elif ch=='s':out.append(f'{dt.second:0{n}d}')
  else:out.append(run)
 return ''.join(out)
def _looks_like_custom_pattern(arg):
 # %を含まず、Y/M/D/h/m/s のいずれかを含むものを桁数調整パターンとみなす。
 return bool(arg) and '%' not in arg and re.search(r'[YMDdHhms]',str(arg)) is not None
def _apply_text_op(value,arg):
 value=str(value)
 if not arg:return value
 parts=arg.split(':');op=parts[0].strip().lower()
 try:
  if op=='left':return value[:max(0,int(parts[1]))]
  if op=='right':n=max(0,int(parts[1]));return value[-n:] if n>0 else ''
  if op=='mid':start=int(parts[1]);length=int(parts[2]);return value[start:start+length]
  if op=='upper':return value.upper()
  if op=='lower':return value.lower()
  if op=='replace':return value.replace(parts[1],parts[2] if len(parts)>2 else '')
 except Exception:return value
 return value

# ---- 日付の計算（EDATE / DateAdd 相当）----------------------------------------
# 基準日（現在日時 / 対象ファイル更新日 / 対象ファイル作成日）を軸に、年・月・週・日・時・分・秒を
# 前後へずらしてから命名へ使えるようにする。トークンの対象名の直後へ +N / -N を並べて指定する。
#   例: {now-1M:YYYYMMDD}      -> 現在日時の1ヶ月前
#       {rne_ctime+2Y-1M:YYYYMM} -> 対象ファイル作成日の2年後かつ1ヶ月前（年→月→週→日→時→分→秒の順で適用）
#       {now-7D:YYYYMMDD}       -> 現在日時の7日前
# 単位: Y=年 / M=月 / W=週 / D(またはd)=日 / H(またはh)=時 / I=分 / S=秒。
_DATE_OFFSET_UNIT=re.compile(r'([+-]\d+)([YMWDdHhIS])')
_SOURCE_OFFSET=re.compile(r'^([A-Za-z_]+)((?:[+-]\d+[YMWDdHhIS])+)?$')
def _shift_months(dt,months):
 # 月・年のずらし。EDATEと同様に、日が存在しない場合は月末へ丸める。
 total=dt.year*12+(dt.month-1)+int(months);y,m=total//12,total%12+1
 last=calendar.monthrange(y,m)[1]
 return dt.replace(year=y,month=m,day=min(dt.day,last))
def apply_date_offset(dt,offset_text):
 # 対象名に付いた +N/-N の並びを、年→月→週→日→時→分→秒の順で適用する。
 if dt is None or not offset_text:return dt
 order={'Y':0,'M':1,'W':2,'D':3,'d':3,'H':4,'h':4,'I':5,'S':6}
 parts=sorted(_DATE_OFFSET_UNIT.findall(offset_text),key=lambda p:order.get(p[1],9))
 for sign_num,unit in parts:
  n=int(sign_num)
  if unit=='Y':dt=_shift_months(dt,n*12)
  elif unit=='M':dt=_shift_months(dt,n)
  elif unit=='W':dt=dt+timedelta(weeks=n)
  elif unit in ('D','d'):dt=dt+timedelta(days=n)
  elif unit in ('H','h'):dt=dt+timedelta(hours=n)
  elif unit=='I':dt=dt+timedelta(minutes=n)
  elif unit=='S':dt=dt+timedelta(seconds=n)
 return dt
def split_source_offset(key):
 # トークンの対象名から、基準名と日付計算(オフセット)を分離する。未指定なら (key,'') を返す。
 m=_SOURCE_OFFSET.match(str(key or ''))
 if not m:return str(key or ''),''
 return m.group(1),(m.group(2) or '')

def render_filename_template(template,job=None,rne_path=None,now=None):
 job=job or {};now=now or datetime.now()
 stem=Path(str(job.get('rne') or job.get('rne_path') or '')).stem
 mtime=ctime=None
 try:
  p=Path(rne_path) if rne_path else None
  if p and p.is_file():
   st=p.stat();mtime=datetime.fromtimestamp(st.st_mtime);ctime=datetime.fromtimestamp(getattr(st,'st_ctime',st.st_mtime))
 except Exception:pass
 date_tokens={'now':(now,'%Y%m%d_%H%M%S'),'exec':(now,'%Y%m%d_%H%M%S'),'datetime':(now,'%Y%m%d_%H%M%S'),'date':(now,'%Y%m%d'),'time':(now,'%H%M%S'),'rne_mtime':(mtime,'%Y%m%d'),'mtime':(mtime,'%Y%m%d'),'rne_ctime':(ctime,'%Y%m%d'),'ctime':(ctime,'%Y%m%d')}
 text_tokens={'rne':stem,'rne_name':stem,'rne_stem':stem,'name':str(job.get('name') or ''),'job':str(job.get('name') or ''),'table':str(job.get('table') or '')}
 def repl(m):
  raw=m.group(1).strip();key=raw.split(':',1)[0].strip();arg=raw.split(':',1)[1] if ':' in raw else ''
  base,offset=split_source_offset(key)
  if base in date_tokens:
   dt,default=date_tokens[base]
   if not dt:return ''
   dt=apply_date_offset(dt,offset)
   if _looks_like_custom_pattern(arg):return format_custom_datetime(dt,arg)
   try:return dt.strftime(arg or default)
   except Exception:return dt.strftime(default)
  if key in text_tokens:return _apply_text_op(text_tokens[key],arg)
  return m.group(0)
 rendered=re.sub(r'\{([^}]*)\}',repl,str(template or ''))
 rendered=_ILLEGAL_FILENAME.sub('',rendered);rendered=re.sub(r'\s+',' ',rendered).strip().strip('.')
 return rendered or 'output'

# 命名で使用できる既知トークンのキー一覧。実際に展開できる（＝本当に変数である）ものだけを判定に使う。
_KNOWN_TOKEN_KEYS={'now','exec','datetime','date','time','rne_mtime','mtime','rne_ctime','ctime','rne','rne_name','rne_stem','name','job','table'}
def _pattern_variable_keys(pattern):
 keys=set()
 for m in re.finditer(r'\{([^}]*)\}',str(pattern or '')):
  key=m.group(1).strip().split(':',1)[0].strip()
  base,_off=split_source_offset(key)
  if base in _KNOWN_TOKEN_KEYS:keys.add(base)
 return keys
def has_template_variables(pattern):
 # 単に変数入力欄へ文字を入れただけ（例: SIKALOTDEF）は変数扱いしない。既知トークン {..} が実在する場合だけTrue。
 return bool(_pattern_variable_keys(pattern))
def render_filename_segments(template,job=None,rne_path=None,now=None):
 """命名パターンを『固定部分』と『変数から展開された部分』へ分解する。
 一覧の出力ファイル名で、元が変数である箇所へ色を付けるために使用する。"""
 job=job or {};now=now or datetime.now()
 stem=Path(str(job.get('rne') or job.get('rne_path') or '')).stem
 mtime=ctime=None
 try:
  p=Path(rne_path) if rne_path else None
  if p and p.is_file():
   st=p.stat();mtime=datetime.fromtimestamp(st.st_mtime);ctime=datetime.fromtimestamp(getattr(st,'st_ctime',st.st_mtime))
 except Exception:pass
 date_tokens={'now':(now,'%Y%m%d_%H%M%S'),'exec':(now,'%Y%m%d_%H%M%S'),'datetime':(now,'%Y%m%d_%H%M%S'),'date':(now,'%Y%m%d'),'time':(now,'%H%M%S'),'rne_mtime':(mtime,'%Y%m%d'),'mtime':(mtime,'%Y%m%d'),'rne_ctime':(ctime,'%Y%m%d'),'ctime':(ctime,'%Y%m%d')}
 text_tokens={'rne':stem,'rne_name':stem,'rne_stem':stem,'name':str(job.get('name') or ''),'job':str(job.get('name') or ''),'table':str(job.get('table') or '')}
 def expand(raw):
  raw=raw.strip();key=raw.split(':',1)[0].strip();arg=raw.split(':',1)[1] if ':' in raw else ''
  base,offset=split_source_offset(key)
  if base in date_tokens:
   dt,default=date_tokens[base]
   if not dt:return '',True
   dt=apply_date_offset(dt,offset)
   if _looks_like_custom_pattern(arg):return format_custom_datetime(dt,arg),True
   try:return dt.strftime(arg or default),True
   except Exception:return dt.strftime(default),True
  if key in text_tokens:return _apply_text_op(text_tokens[key],arg),True
  return '{'+raw+'}',False
 pattern=str(template or '');segments=[];pos=0
 for m in re.finditer(r'\{([^}]*)\}',pattern):
  if m.start()>pos:segments.append({'text':pattern[pos:m.start()],'var':False})
  text,is_var=expand(m.group(1));segments.append({'text':text,'var':is_var});pos=m.end()
 if pos<len(pattern):segments.append({'text':pattern[pos:],'var':False})
 out=[]
 for s in segments:
  t=_ILLEGAL_FILENAME.sub('',s['text'])
  if t=='':continue
  if out and out[-1]['var']==s['var']:out[-1]['text']+=t
  else:out.append({'text':t,'var':s['var']})
 return out

def resolve_output_filename(job,cfg,now=None):
 fmt=normalize_output_format(job.get('output_format'),job.get('output_file'))
 mode=str(job.get('naming_mode') or 'fixed').lower()
 if mode=='template' and str(job.get('output_pattern') or '').strip():
  rp=None
  try:rp=resolve_rne_path(job,cfg)
  except Exception:rp=None
  base=render_filename_template(job.get('output_pattern'),job=job,rne_path=rp,now=now)
 else:
  base=Path(str(job.get('output_file') or 'output')).stem
 return canonical_output_file(base,fmt)

def record_job_run(job_id,job_name,status_value,trigger,detail='',rows=None,cols=None,output_file=''):
 if not job_id:return
 now=datetime.now().isoformat(timespec='seconds')
 try:
  with settings_connection() as c:
   c.execute('INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(job_id,job_name,now,status_value,trigger,detail,rows,cols,output_file,now))
   # カレンダーの実施履歴用に追記式でも保持する（job_runsは最新1件のみのため）。
   c.execute('INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)',(job_id,job_name,now,status_value,trigger,detail,rows,cols,output_file))
   # 実施履歴は直近2000件へ制限し、肥大化を防ぐ。
   c.execute('DELETE FROM run_history WHERE id NOT IN (SELECT id FROM run_history ORDER BY id DESC LIMIT 2000)')
 except Exception:
  log.exception('JOB_RUN_RECORD_FAILED job=%s',job_name)

def load_job_runs():
 try:
  with settings_connection() as c:
   return {r['job_id']:{'finished_at':r['finished_at'],'status':r['status'],'trigger':r['trigger'],'detail':r['detail'],'rows':r['rows'],'cols':r['cols'],'output_file':r['output_file']} for r in c.execute('SELECT * FROM job_runs')}
 except Exception:
  return {}

def last_run_info(run):
 if not run:return {'last_run':None,'last_status':'','last_trigger':'','last_output':''}
 trig=str(run.get('trigger') or '');kind='schedule' if trig.startswith('schedule') else 'manual'
 return {'last_run':run.get('finished_at'),'last_status':run.get('status') or '','last_trigger':kind,'last_output':run.get('output_file') or '','last_detail':run.get('detail') or ''}

def load():
 init_settings_db()
 with settings_connection() as c:
  cfg={r['key']:_decode_setting(r) for r in c.execute('SELECT key,value,value_type FROM app_settings')}; jobs=[]
  for r in c.execute('SELECT * FROM jobs ORDER BY display_order,id'):
   rules=[]
   for x in c.execute('SELECT * FROM schedules WHERE job_id=? ORDER BY display_order,id',(r['id'],)):
    q={'id':x['id'],'enabled':bool(x['enabled']),'name':x['name'],'type':x['schedule_type'],'time':x['time_value'] or '06:00'}
    if x['interval_minutes'] is not None:q['interval_minutes']=x['interval_minutes']
    if x['weekdays_json']:q['weekdays']=json.loads(x['weekdays_json'])
    if x['month_days_json']:q['month_days']=json.loads(x['month_days_json'])
    if x['dates_json']:q['dates']=json.loads(x['dates_json'])
    rules.append(q)
   fmt=normalize_output_format(r['output_format'],r['output_file']); jobs.append({'id':r['id'],'enabled':bool(r['enabled']),'name':r['name'],'rne':r['rne'],'rne_path':r['rne_path'],'output_folder':r['output_folder'],'output_format':fmt,'output_file':canonical_output_file(r['output_file'],fmt),'table':r['table_name'],'sheet':r['sheet_name'],'type':r['read_type'],'naming_mode':(r['naming_mode'] if 'naming_mode' in r.keys() else 'fixed'),'output_pattern':(r['output_pattern'] if 'output_pattern' in r.keys() else ''),'comment':(r['comment'] if 'comment' in r.keys() else ''),'period':_decode_period(r['period_json'] if 'period_json' in r.keys() else ''),'schedules':rules})
  cfg['jobs']=jobs; cfg.setdefault('settings',{}); cfg['settings'].setdefault('extract_engine','api'); cfg['settings'].setdefault('api_parallel_max_lines',24); cfg['settings'].setdefault('api_parallel_model','process')
  # 既定の並列ラインは6。旧テスト実装では stability_profile='stable_api_serial' の環境で読込のたびに api_parallel_lines を1へ強制していた（毎回1ラインへ戻る不具合の原因）。
  # その名残マーカーが残る環境（または初期状態）だけ一度2へ引き上げ、以降はユーザーが保存した値をそのまま尊重する。
  _prev_profile=cfg['settings'].get('stability_profile')
  if _prev_profile in (None,'stable_api_serial'):
   cfg['settings']['api_parallel_lines']=6; cfg['settings']['stability_profile']='balanced_api_parallel'
  cfg['settings'].setdefault('api_parallel_lines',6); cfg['settings'].setdefault('stability_profile','balanced_api_parallel'); cfg['settings'].setdefault('backup_enabled',True); _backup_mode_missing='backup_mode' not in cfg['settings']; cfg['settings'].setdefault('backup_mode','generations'); cfg['settings'].setdefault('backup_retention_days',30); cfg['settings'].setdefault('backup_generation_limit_enabled',True); cfg['settings'].setdefault('backup_generations',3)
  if _backup_mode_missing:cfg['settings']['backup_generations']=3
  if int(cfg['settings'].get('api_parallel_lines',6) or 6)==2:cfg['settings']['api_parallel_lines']=6
  cfg.setdefault('navigator_api_dll',r'.\Config\NAVIAP\debugdllVC14x64\SymNaviA.dll'); cfg.setdefault('accdb_template','.\\assets\\empty.accdb');
 if str(cfg.get('backup_folder') or '').strip().lower() in ('','.\\backup','backup','.\\config\\backup'):
  cfg['backup_folder']=str(LOCAL_BACKUP)
 return cfg

def save(v):
 init_settings_db(); now=datetime.now().isoformat(timespec='seconds'); jobs=v.get('jobs',[]); top={k:x for k,x in v.items() if k not in ('jobs','credential_status')}
 with settings_connection() as c:
  c.execute('BEGIN IMMEDIATE'); c.execute('DELETE FROM app_settings')
  for key,value in top.items():
   encoded,kind=_encode_setting(value); c.execute('INSERT INTO app_settings VALUES(?,?,?,?)',(key,encoded,kind,now))
  keep=[]
  for order,j in enumerate(jobs):
   jid=j.get('id') or str(uuid.uuid4()); keep.append(jid)
   fmt=normalize_output_format(j.get('output_format'),j.get('output_file')); output_file=canonical_output_file(j.get('output_file'),fmt); log.info('設定保存 job=%s requested_format=%s saved_format=%s requested_file=%s saved_file=%s',j.get('name'),j.get('output_format'),fmt,j.get('output_file'),output_file); c.execute('INSERT OR REPLACE INTO jobs (id,display_order,enabled,name,rne,rne_path,output_folder,output_format,output_file,table_name,sheet_name,read_type,naming_mode,output_pattern,comment,period_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,order,int(bool(j.get('enabled',True))),j.get('name',''),j.get('rne',''),j.get('rne_path',''),j.get('output_folder',''),fmt,output_file,j.get('table','仕掛'),j.get('sheet','Page1'),j.get('type','詳細データ'),str(j.get('naming_mode') or 'fixed'),str(j.get('output_pattern') or ''),str(j.get('comment') or ''),json.dumps(_decode_period(json.dumps(j.get('period') or {},ensure_ascii=False)),ensure_ascii=False),now))
   c.execute('DELETE FROM schedules WHERE job_id=?',(jid,))
   for ro,q in enumerate(j.get('schedules',[])):
    c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(q.get('id') or str(uuid.uuid4()),jid,ro,int(bool(q.get('enabled',True))),q.get('name','実行ルール'),q.get('type','daily'),q.get('time','06:00'),q.get('interval_minutes'),json.dumps(q.get('weekdays'),ensure_ascii=False) if 'weekdays' in q else None,json.dumps(q.get('month_days'),ensure_ascii=False) if 'month_days' in q else None,json.dumps(q.get('dates'),ensure_ascii=False) if 'dates' in q else None,now))
  if keep:c.execute('DELETE FROM jobs WHERE id NOT IN ('+','.join('?' for _ in keep)+')',keep);c.execute('DELETE FROM job_runs WHERE job_id NOT IN ('+','.join('?' for _ in keep)+')',keep)
  else:c.execute('DELETE FROM jobs');c.execute('DELETE FROM job_runs')

def migrate_legacy_settings():
 init_settings_db()
 with settings_connection() as c:count=c.execute('SELECT COUNT(*) FROM app_settings').fetchone()[0]
 if count or not LEGACY_CFG.exists():return
 data=json.loads(LEGACY_CFG.read_text(encoding='utf-8')); save(data); backup=BASE/'config.migrated.json'
 if not backup.exists():shutil.copy2(LEGACY_CFG,backup)
 LEGACY_CFG.unlink(); log.info('config.jsonをapp_settings.sqlite3へ移行しました backup=%s',backup)

def load_scheduler_state():
 init_settings_db()
 with settings_connection() as c:return {r['state_key']:r['state_value'] for r in c.execute('SELECT * FROM scheduler_state')}

def save_scheduler_state(key,value):
 with settings_connection() as c:c.execute('INSERT OR REPLACE INTO scheduler_state VALUES(?,?,?)',(key,value,datetime.now().isoformat(timespec='seconds')))

def set_status(**v):
 with status_lock: status.update(v)

def update_parallel_line(line,**v):
 with status_lock:
  lines=[dict(x) for x in status.get('parallel_lines',[]) if x.get('line')!=line]
  current={'line':line,'job':'','state':'待機','percent':0,'elapsed':0,'detail':''}
  current.update(v); lines.append(current); lines.sort(key=lambda x:x.get('line',''))
  status['parallel_lines']=lines
  ipc_path=os.environ.get('NAVI_WORKER_STATUS')
  if ipc_path:
   try:
    payload=dict(current,updated_at=datetime.now().isoformat(timespec='milliseconds'),pid=os.getpid())
    tmp=Path(ipc_path+'.tmp'); tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,ipc_path)
   except Exception:pass


def resolve_path(value,base=BASE):
 """Resolve absolute, UNC, or app-relative paths without changing stored values."""
 if value is None:return base
 raw=os.path.expandvars(os.path.expanduser(str(value).strip()))
 p=Path(raw)
 if p.is_absolute() or raw.startswith('\\'):return p
 return (Path(base)/p).resolve()

def display_path(value):
 try:return str(resolve_path(value))
 except:return str(value)

def resolve_rne_path(job,cfg):
 """Canonical RNE resolution shared by diagnosis and execution."""
 value=str(job.get('rne_path') or job.get('rne') or '').strip()
 if not value:return resolve_path(job.get('rne',''),resolve_path(cfg.get('rne_folder','.\\rne')))
 raw=os.path.expandvars(os.path.expanduser(value))
 p=Path(raw)
 if p.is_absolute() or raw.startswith('\\\\'):return p
 # Explicit relative paths (./, ../, .\, ..\) are app-root relative.
 if raw.startswith(('.\\','..\\','./','../')):return resolve_path(raw,BASE)
 # Bare filename is relative to configured RNE base folder.
 return resolve_path(raw,resolve_path(cfg.get('rne_folder','.\\rne')))

def dde_staging_folder():
 """Use the per-user local work folder for all temporary extraction files."""
 candidates=[LOCAL_ROOT/'work',Path(tempfile.gettempdir())/'SymfoNaviDataHub'/'work',Path('C:/SymfoNaviDataHubWork')]
 for p in candidates:
  try:
   text=str(p)
   if not text.isascii():continue
   p.mkdir(parents=True,exist_ok=True)
   test=p/'.write_test'; test.write_text('ok',encoding='ascii'); test.unlink()
   return p
  except Exception:continue
 raise RuntimeError('SymfoNavi用のローカル一時フォルダーを作成できません')

def api_data_source_profiles(path):
 # 公式APIサンプルにある追加データソース接続を、明示されたCONFセクションだけから構成する。
 cp=configparser.ConfigParser(interpolation=None); cp.optionxform=str.lower
 for enc in ('cp932','utf-8-sig','utf-8'):
  try:cp.read(path,encoding=enc);break
  except UnicodeDecodeError:continue
 profiles=[]
 supported={'apioracle':'oracle','apisqlserver':'sqlserver','apirda':'rda','apipostgres':'postgres','apiresource':'resource','apiresourcenoauth':'noauth'}
 for section in cp.sections():
  compact=''.join(ch for ch in section.lower() if ch.isalnum())
  kind=supported.get(compact)
  if not kind:continue
  d={k.lower():v.strip() for k,v in cp.items(section)}
  enabled=str(d.get('enabled','yes')).lower() not in ('0','no','false','off')
  if not enabled:continue
  profiles.append({'section':section,'kind':kind,'user':d.get('user',d.get('userid','')),'password':d.get('password',d.get('passwd','')),'server':d.get('server',''),'option':d.get('option',d.get('opt','')),'resource':d.get('resource',d.get('resourcename','')),'resource_kind':d.get('resource_kind',d.get('resourcekind','0'))})
 return profiles
def creds(path):
 cp=configparser.ConfigParser(interpolation=None); cp.optionxform=str.lower
 for enc in ('cp932','utf-8-sig','utf-8'):
  try: cp.read(path,encoding=enc); break
  except UnicodeDecodeError: continue
 if not cp.sections(): raise ValueError('symnavim.confを読み取れません')
 sec='Default' if cp.has_section('Default') else next((x for x in cp.sections() if x.lower().startswith('connect_')),cp.sections()[0])
 d={k.lower():v.strip() for k,v in cp.items(sec)}; a=(d.get('symnaviuserid',''),d.get('symnavipasswd',''),d.get('symnaviserver',''))
 if not all(a): raise ValueError(f'[{sec}]にSymNaviUSERID、SymNaviPASSWD、SymNaviServerが必要です')
 return *a,sec

_wmi_warning_reported=False
def symnavi_process_ids(root_pid):
 """Return the launched process and descendant process IDs using WMI."""
 global _wmi_warning_reported
 ids={root_pid}; pythoncom=None
 try:
  import pythoncom, win32com.client
  pythoncom.CoInitialize()
  svc=win32com.client.GetObject(r'winmgmts:\\.\root\cimv2')
  rows=list(svc.ExecQuery('SELECT ProcessId,ParentProcessId,Name FROM Win32_Process'))
  changed=True
  while changed:
   changed=False
   for item in rows:
    pid=int(item.ProcessId); ppid=int(item.ParentProcessId); name=str(item.Name or '').lower()
    if ppid in ids or name in ('symnavi.exe','symnavim.exe'):
     if pid not in ids:ids.add(pid); changed=True
 except Exception as e:
  if not _wmi_warning_reported:
   log.warning('SymfoNavi子プロセス列挙を省略し、PID・タイトル検出を継続します: %s',e); _wmi_warning_reported=True
 finally:
  if pythoncom:
   try:pythoncom.CoUninitialize()
   except:pass
 return ids

def hide_symnavi_windows(proc,wait_seconds=0.8):
 """Hide currently visible SymfoNavi windows and confirm that they became hidden."""
 try:
  import win32con, win32gui, win32process
  deadline=time.time()+max(.1,wait_seconds); hidden=set(); remaining=[]
  while time.time()<deadline:
   pids=symnavi_process_ids(proc.pid); candidates=[]
   def each(hwnd,_):
    try:
     _,pid=win32process.GetWindowThreadProcessId(hwnd)
     title=win32gui.GetWindowText(hwnd).lower(); cls=win32gui.GetClassName(hwnd).lower()
     if win32gui.IsWindowVisible(hwnd) and (pid in pids or 'symnavi' in title or 'navigator' in title or 'symnavi' in cls):candidates.append(hwnd)
    except:pass
   win32gui.EnumWindows(each,None)
   if not candidates:return len(hidden),[]
   for hwnd in candidates:
    try:
     win32gui.ShowWindow(hwnd,win32con.SW_HIDE)
     if not win32gui.IsWindowVisible(hwnd):hidden.add(hwnd)
    except:pass
   time.sleep(.08)
   remaining=[]
   def confirm(hwnd,_):
    try:
     _,pid=win32process.GetWindowThreadProcessId(hwnd)
     title=win32gui.GetWindowText(hwnd).lower(); cls=win32gui.GetClassName(hwnd).lower()
     if win32gui.IsWindowVisible(hwnd) and (pid in pids or 'symnavi' in title or 'navigator' in title or 'symnavi' in cls):remaining.append(hwnd)
    except:pass
   win32gui.EnumWindows(confirm,None)
   if not remaining:return len(hidden),[]
  return len(hidden),remaining
 except Exception as e:
  log.warning('SymfoNaviウィンドウ非表示失敗: %s',e); return 0,[]

def symnavi_hide_options(settings):
 profile=str(settings.get('symnavi_hide_profile','balanced'))
 presets={
  'action_only':{'watch':False,'watch_interval':0.0,'action_duration':0.35,'action_interval':0.35},
  'light':{'watch':True,'watch_interval':3.0,'action_duration':0.35,'action_interval':0.35},
  'balanced':{'watch':True,'watch_interval':2.0,'action_duration':0.5,'action_interval':0.5},
  'standard':{'watch':True,'watch_interval':1.0,'action_duration':0.6,'action_interval':0.5},
  'custom':{'watch':bool(settings.get('symnavi_hide_watch_enabled',True)),'watch_interval':max(1.0,float(settings.get('symnavi_hide_interval_seconds',2.0))),'action_duration':max(0.2,float(settings.get('symnavi_hide_action_duration_seconds',0.5))),'action_interval':max(0.2,float(settings.get('symnavi_hide_action_interval_seconds',0.5)))}
 }
 return profile,presets.get(profile,presets['balanced'])

def hide_after_action(proc,action,settings,settle_seconds=None):
 profile,opt=symnavi_hide_options(settings)
 duration=opt['action_duration'] if settle_seconds is None else min(float(settle_seconds),opt['action_duration'])
 started=time.time(); total=0; visible=[]
 while True:
  count,visible=hide_symnavi_windows(proc,min(.35,opt['action_interval'])); total+=count
  if time.time()-started>=duration or (count==0 and not visible):break
  time.sleep(opt['action_interval'])
 state='非表示確認済み' if not visible else f'次回監視待ち({len(visible)})'
 set_status(symnavi_window=state,activity_detail=f'{action}後の画面状態を確認',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
 log.info('SymfoNavi非表示 action=%s profile=%s hidden=%s remaining=%s',action,profile,total,len(visible))

def hide_after_action_async(proc,action,settings):
 # Periodic profiles already watch new windows. Running another WMI/window scan in parallel severely slows DDE and ACE.
 profile,opt=symnavi_hide_options(settings)
 if opt['watch']:
  log.info('SymfoNavi操作直後監視を省略 action=%s profile=%s reason=定期監視有効',action,profile); return
 def worker():
  try:hide_after_action(proc,action,settings)
  except Exception as e:log.warning('SymfoNavi非表示失敗 action=%s error=%s',action,e)
 threading.Thread(target=worker,daemon=True,name='hide-'+action.replace(' ','_')).start()

def start_hidden_symnavi(proc,settings):
 hide_after_action(proc,'DDE接続',settings)
 return None

def hide_window_watcher(proc,stop_flag,settings):
 try:
  import win32con,win32gui,win32process
  profile,opt=symnavi_hide_options(settings)
  interval=max(1.0,opt['watch_interval'])
  pids=symnavi_process_ids(proc.pid); refreshed=0.0; hidden=set()
  log.info('SymfoNavi定期監視開始 profile=%s interval=%.1fs',profile,interval)
  while not stop_flag.wait(interval):
   now=time.time()
   if now-refreshed>max(30.0,interval*10):pids=symnavi_process_ids(proc.pid);refreshed=now
   visible=[]
   def each(hwnd,_):
    try:
     _,pid=win32process.GetWindowThreadProcessId(hwnd); title=win32gui.GetWindowText(hwnd).lower(); cls=win32gui.GetClassName(hwnd).lower()
     if win32gui.IsWindowVisible(hwnd) and (pid in pids or 'symnavi' in title or 'navigator' in title or 'symnavi' in cls):visible.append(hwnd)
    except:pass
   win32gui.EnumWindows(each,None)
   for hwnd in visible:
    try:win32gui.ShowWindow(hwnd,win32con.SW_HIDE);hidden.add(hwnd)
    except:pass
   if visible:set_status(symnavi_window=f'非表示監視 / {interval:g}秒間隔 / {len(visible)}件処理',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
  log.info('SymfoNavi定期監視終了 hidden_handles=%s',len(hidden))
 except Exception as e:log.warning('SymfoNavi定期監視失敗: %s',e)

def start_window_watcher(proc,settings):
 profile,opt=symnavi_hide_options(settings)
 if not opt['watch']:
  log.info('SymfoNavi定期監視なし profile=%s',profile); return None,None
 flag=threading.Event(); thread=threading.Thread(target=hide_window_watcher,args=(proc,flag,settings),daemon=True); thread.start(); return flag,thread

def phase_log(phase,started=None,**values):
 parts=' '.join(f'{k}={v}' for k,v in values.items())
 if started is None:
  log.info('STEP_START phase=%s %s',phase,parts)
  for h in log.handlers:h.flush()
  return time.perf_counter()
 elapsed=time.perf_counter()-started
 log.info('STEP_END phase=%s elapsed=%.2fs %s',phase,elapsed,parts)
 for h in log.handlers:h.flush()
 return elapsed

def progress(step,label,percent,**extra):
 set_status(step=step,step_label=label,step_percent=percent,current=label,elapsed_seconds=max(0,int(time.time()-getattr(progress,'started',time.time()))),heartbeat_at=datetime.now().isoformat(timespec='seconds'),**extra)

# ---- 相対期間（動的日付）------------------------------------------------------
# RNEに定義済みの時間型管理ポイントへ、処理日時を基準にした相対期間を実行直前に適用する。
# 単位=month: 月度指定 (YYYYMM00 / NAVI_MONTH=0) / 単位=day: 年月日指定 (YYYYMMDD / NAVI_YMD=1)。
def _add_months(year,month,delta):
 idx=(year*12+(month-1))+int(delta); return idx//12, idx%12+1

def compute_period(period,now=None):
 now=now or datetime.now()
 if not period or not period.get('enabled'):return None
 unit=period.get('unit') if period.get('unit') in ('month','day') else 'month'
 try:fo=int(period.get('from_offset',0) or 0)
 except Exception:fo=0
 try:to=int(period.get('to_offset',0) or 0)
 except Exception:to=0
 if unit=='month':
  fy,fm=_add_months(now.year,now.month,fo); ty,tm=_add_months(now.year,now.month,to)
  from_time=f'{fy:04d}{fm:02d}00'; to_time=f'{ty:04d}{tm:02d}00'; condition=0
  summary=f'{fy}年{fm}月度 ～ {ty}年{tm}月度'
 else:
  fd=(now.date()+timedelta(days=fo)); td=(now.date()+timedelta(days=to))
  from_time=fd.strftime('%Y%m%d'); to_time=td.strftime('%Y%m%d'); condition=1
  summary=f'{fd:%Y-%m-%d} ～ {td:%Y-%m-%d}'
 return {'condition':condition,'from_time':from_time,'to_time':to_time,'summary':summary,'unit':unit,'from_offset':fo,'to_offset':to}

def apply_dynamic_period(api_client,handle,job,now=None,line=''):
 # ジョブに相対期間が設定されていれば、開いたカタログの時間型管理ポイントを差し替える。
 # 期間が有効なのに適用に失敗した場合は、誤った期間での公開を避けるため例外を送出して失敗させる。
 period=job.get('period') or {}
 if not period.get('enabled'):return None
 spec=compute_period(period,now or datetime.now())
 if not spec:return None
 label=str(period.get('control_point') or '').strip()
 t=phase_log('api_change_period',job=job.get('name'),line=line,unit=spec['unit'],condition=spec['condition'],from_time=spec['from_time'],to_time=spec['to_time'],control_point=(label or '(時間フィールド)'))
 info=api_client.apply_period(handle,label,spec['condition'],spec['from_time'],spec['to_time'])
 phase_log('api_change_period',t,job=job.get('name'),line=line,applied_to=info.get('label'),locate=info.get('locate'),summary=spec['summary'])
 log.info('DYNAMIC_PERIOD job=%s line=%s enabled=1 unit=%s condition=%s from=%s to=%s target=%s summary=%s',job.get('name'),line or '-',spec['unit'],spec['condition'],spec['from_time'],spec['to_time'],info.get('label'),spec['summary'])
 return {**spec,'target':info.get('label')}

def dde_connect(seconds):
 try: import win32ui, dde
 except Exception as e: raise RuntimeError('pywin32のDDE機能を読み込めません') from e
 srv=dde.CreateServer(); srv.Create('NaviToSQLiteClient'); conv=dde.CreateConversation(srv); end=time.time()+seconds; last=''
 while time.time()<end:
  try: conv.ConnectTo('SymNavi','Macro'); time.sleep(5); log.info('DDE接続完了'); return srv,conv
  except Exception as e: last=str(e); time.sleep(1)
 try:srv.Shutdown()
 except:pass
 raise TimeoutError('DDE接続タイムアウト: '+last)
def dde_exec(conv,name,text,expected_output=None):
 last=None
 for attempt in range(1,4):
  done=threading.Event(); started=time.time()
  def heartbeat():
   while not done.wait(5):
    elapsed=int(time.time()-started)
    set_status(activity_detail=f'DDE {name} 実行中',activity_value=f'{elapsed}秒経過。SymfoNaviの応答を待っています',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
    log.info('DDE待機中 command=%s attempt=%s elapsed=%ss',name,attempt,elapsed)
  threading.Thread(target=heartbeat,daemon=True,name='dde-heartbeat-'+name).start()
  try:
   log.info('DDE実行開始 command=%s attempt=%s text=%s',name,attempt,text)
   conv.Exec(text); done.set()
   elapsed=time.time()-started; log.info('DDE実行完了 command=%s attempt=%s elapsed=%.2fs',name,attempt,elapsed)
   time.sleep(.2); return
  except Exception as e:
   done.set(); last=e; elapsed=time.time()-started
   # SymfoNavi can return Exec failed after completing the Save. Do not repeat the full extraction when output exists.
   if expected_output:
    candidate=Path(expected_output)
    for _ in range(10):
     if candidate.exists() and candidate.stat().st_size>0:
      log.warning('DDE応答エラーだが出力ファイルを検出したため再実行を省略 command=%s attempt=%s elapsed=%.2fs file=%s size=%s error=%s',name,attempt,elapsed,candidate,candidate.stat().st_size,e); return
     time.sleep(.5)
   if name=='Open':
    log.warning('DDE Open応答タイムアウト。重複Openによる確認ダイアログを防ぐため再実行せず次工程で検証します elapsed=%.2fs error=%s',elapsed,e)
    set_status(activity_detail='RNE Open応答待ちを終了',activity_value='重複Openを防止し、XLS生成工程で実状態を検証します',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
    return
   log.warning('DDE失敗 command=%s attempt=%s elapsed=%.2fs error=%s',name,attempt,elapsed,e); time.sleep(2)
 raise RuntimeError(f'DDE {name}失敗: {last}; command={text}')

def validate_xls_complete(path,job):
 try:
  import xlrd
  book=xlrd.open_workbook(str(path),on_demand=True)
  try:
   sheet=book.sheet_by_name(job.get('sheet','Page1'))
   return sheet.nrows>0 and sheet.ncols>0, f'{sheet.nrows:,} rows / {sheet.ncols:,} columns'
  finally:book.release_resources()
 except Exception as e:return False,str(e)

def wait_file(p,seconds,job):
 end=time.time()+seconds; old=-1; stable=0; started=time.time(); last_validation='未検証'
 while time.time()<end:
  elapsed=int(time.time()-started)
  if p.exists():
   size=p.stat().st_size; stable=stable+1 if size>0 and size==old else 0; old=size
   if stable>=5:
    ok,last_validation=validate_xls_complete(p,job)
    if ok:
     set_status(activity_detail='中間XLSの完成を確認しました',activity_value=f'{size:,} bytes / {last_validation} / {elapsed}秒',heartbeat_at=datetime.now().isoformat(timespec='seconds')); return size
    stable=0
   set_status(activity_detail='中間XLSを書き込み中',activity_value=f'{size:,} bytes / 安定確認 {stable}/5 / {elapsed}秒 / {last_validation}',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
  else:set_status(activity_detail='SymfoNaviからの中間XLS生成を待機中',activity_value=f'未検出 / {elapsed}秒経過',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
  time.sleep(1)
 raise TimeoutError(f'一時XLSが完成しません: {p}; 最終サイズ={old:,} bytes; 検証={last_validation}')

def unique_headers(values):
 out=[]; used={}
 for i,x in enumerate(values,1):
  name=str(x or '').replace('\r','').replace('\n','').strip() or f'Column{i}'; used[name]=used.get(name,0)+1; out.append(name if used[name]==1 else f'{name}_{used[name]}')
 return out
def qi(s): return '"'+str(s).replace('"','""')+'"'
def read_extract(source,job,reject,expected_rows=None,expected_cols=None):
 source=Path(source); started=time.perf_counter()
 if source.suffix.lower()=='.csv':
  rows=None; encoding_used=''
  last_error=None
  for encoding in ('cp932','utf-8-sig','utf-8'):
   try:
    with source.open('r',encoding=encoding,errors='strict',newline='') as f:rows=list(csv.reader(f))
    encoding_used=encoding;break
   except UnicodeDecodeError as e:last_error=e
  if rows is None:raise UnicodeError(f'API中間CSVの文字コードを判定できません: {source}: {last_error}')
  source_kind='api_csv'
 else:
  import xlrd
  b=xlrd.open_workbook(str(source),on_demand=True)
  try: sh=b.sheet_by_name(job.get('sheet','Page1')); rows=[sh.row_values(i) for i in range(sh.nrows)]
  finally:b.release_resources()
  encoding_used='binary';source_kind='dde_xls'
 if job.get('type')=='集計表' and rows:rows=rows[1:]
 if not rows:raise ValueError(f'{source.suffix}にデータがありません')
 hs=unique_headers(rows[0]);body=[]
 for row in rows[1:]:body.append([str(x) if x is not None else '' for x in list(row[:len(hs)])+['']*max(0,len(hs)-len(row))])
 if reject and not body:raise ValueError('抽出0件のため出力を中止しました')
 row_match=expected_rows is None or len(body)==int(expected_rows)
 col_match=expected_cols is None or len(hs)==int(expected_cols)
 log.info('INTERMEDIATE_VALIDATION kind=%s file=%s encoding=%s size=%s rows=%s columns=%s expected_rows=%s expected_columns=%s row_match=%s column_match=%s elapsed=%.2fs',source_kind,source,encoding_used,source.stat().st_size,len(body),len(hs),expected_rows,expected_cols,row_match,col_match,time.perf_counter()-started)
 if not row_match or not col_match:raise RuntimeError(f'中間データ件数検査に失敗 expected={expected_rows}x{expected_cols} actual={len(body)}x{len(hs)}')
 return hs,body


def _xlsx_col_name(index):
 name=''
 while index:
  index,rem=divmod(index-1,26); name=chr(65+rem)+name
 return name or 'A'
def _xlsx_xml_text(value):
 s='' if value is None else str(value)
 s=''.join(ch for ch in s if ch in ('\t','\n','\r') or ord(ch)>=32)
 return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def write_xlsx_direct(dst,sheet_name,headers,body):
 # Write a minimal XLSX directly as ZIP/XML. All cells are inline strings to preserve values exactly.
 import zipfile
 sheet_name=(sheet_name or 'Page1')[:31]
 started=time.perf_counter(); rows_written=0; cell_count=0
 with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  z.writestr('[Content_Types].xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>''')
  z.writestr('_rels/.rels','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''')
  z.writestr('xl/_rels/workbook.xml.rels','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
  safe_sheet=sheet_name.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
  z.writestr('xl/workbook.xml',f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>''')
  z.writestr('xl/styles.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Yu Gothic"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>''')
  z.writestr('docProps/app.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>SymfoNavi Data Hub</Application></Properties>''')
  z.writestr('docProps/core.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>SymfoNavi Data Hub</dc:creator><cp:lastModifiedBy>SymfoNavi Data Hub</cp:lastModifiedBy></cp:coreProperties>''')
  def row_xml(row_index,row):
   nonlocal cell_count
   cells=[]
   for c,v in enumerate(row,1):
    ref=f'{_xlsx_col_name(c)}{row_index}'; cell_count+=1
    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_xml_text(v)}</t></is></c>')
   return f'<row r="{row_index}">'+''.join(cells)+'</row>'
  last_col=_xlsx_col_name(len(headers)); last_row=len(body)+1
  with z.open('xl/worksheets/sheet1.xml','w') as f:
   f.write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:{last_col}{last_row}"/><sheetData>'.encode('utf-8'))
   f.write(row_xml(1,headers).encode('utf-8'))
   for r,row in enumerate(body,2):
    f.write(row_xml(r,row).encode('utf-8')); rows_written+=1
   f.write(b'</sheetData></worksheet>')
 return {'sheet':sheet_name,'rows':rows_written,'columns':len(headers),'cells':cell_count,'elapsed':time.perf_counter()-started}
def verify_xlsx_direct(dst,expected_columns):
 import zipfile,re
 started=time.perf_counter()
 with zipfile.ZipFile(dst,'r') as z:
  bad=z.testzip();names=set(z.namelist());required={'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'};missing=sorted(required-names)
  head=z.read('xl/worksheets/sheet1.xml')[:65536].decode('utf-8',errors='ignore')
 if bad or missing:raise RuntimeError(f'XLSX ZIP構造検査失敗 bad={bad} missing={missing}')
 m=re.search(r'<row[^>]*r="1"[^>]*>(.*?)</row>',head,re.S); header_columns=len(re.findall(r'<c\b',m.group(1))) if m else 0
 log.info('XLSX_LIGHT_VERIFY_DIRECT header_columns=%s expected_columns=%s elapsed=%.2fs',header_columns,expected_columns,time.perf_counter()-started)
 if header_columns!=expected_columns:raise RuntimeError(f'XLSX列数検査失敗 expected={expected_columns} actual={header_columns}')
 log.info('XLSX_ZIP_TEST bad_entry=%s missing_required=%s entries=%s elapsed=%.2fs',bad,missing,len(names),time.perf_counter()-started)

def verify_xlsx_fast(dst,expected_columns):
 import zipfile,re
 started=time.perf_counter()
 with zipfile.ZipFile(dst,'r') as z:
  names=set(z.namelist());required={'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'};missing=sorted(required-names)
  if missing:raise RuntimeError(f'XLSX必須XML不足 missing={missing}')
  head=z.read('xl/worksheets/sheet1.xml')[:65536].decode('utf-8',errors='ignore')
 m=re.search(r'<row[^>]*r="1"[^>]*>(.*?)</row>',head,re.S); header_columns=len(re.findall(r'<c\b',m.group(1))) if m else 0
 log.info('XLSX_FAST_VERIFY header_columns=%s expected_columns=%s elapsed=%.2fs',header_columns,expected_columns,time.perf_counter()-started)
 if header_columns!=expected_columns:raise RuntimeError(f'XLSX列数検査失敗 expected={expected_columns} actual={header_columns}')
 return header_columns

def prewarm_access_async(reason='accdb'):
 def worker():
  pythoncom=None;access_app=None;started=time.perf_counter()
  log.info('ACCDB_PREWARM_START reason=%s',reason)
  try:
   import pythoncom,win32com.client
   pythoncom.CoInitialize()
   dispatch_started=time.perf_counter();access_app=win32com.client.DispatchEx('Access.Application');dispatch_elapsed=time.perf_counter()-dispatch_started
   try:access_app.Visible=False
   except Exception:pass
   quit_started=time.perf_counter()
   try:access_app.Quit(2)
   except TypeError:access_app.Quit()
   quit_elapsed=time.perf_counter()-quit_started
   log.info('ACCDB_PREWARM_END reason=%s dispatch_elapsed=%.2fs quit_elapsed=%.2fs total_elapsed=%.2fs',reason,dispatch_elapsed,quit_elapsed,time.perf_counter()-started)
  except Exception as e:
   log.warning('ACCDB_PREWARM_FAILED reason=%s error=%s elapsed=%.2fs',reason,e,time.perf_counter()-started)
  finally:
   access_app=None
   if pythoncom:
    try:pythoncom.CoUninitialize()
    except Exception:pass
 t=threading.Thread(target=worker,daemon=True,name='accdb-prewarm')
 t.start();return t

def export_data(source,dst,job,reject,expected_rows=None,expected_cols=None):
 parse_started=phase_log('intermediate_parse',job=job.get('name'),source=source);hs,body=read_extract(source,job,reject,expected_rows,expected_cols);phase_log('intermediate_parse',parse_started,job=job.get('name'),rows=len(body),columns=len(hs));fmt=validate_output_contract(job,'export'); log.info('出力開始 configured_format=%s effective_format=%s configured_file=%s work_file=%s rows=%s columns=%s',job.get('output_format'),fmt,job.get('output_file'),dst,len(body),len(hs))
 if dst.exists():dst.unlink()
 if fmt=='sqlite3':
  sqlite_started=time.perf_counter();c=sqlite3.connect(dst)
  try:
   c.execute('PRAGMA synchronous=FULL'); c.execute(f'CREATE TABLE {qi(job["table"])} ('+', '.join(qi(x)+' TEXT' for x in hs)+')')
   insert_started=time.perf_counter()
   if body:c.executemany(f'INSERT INTO {qi(job["table"])} VALUES ('+','.join('?' for _ in hs)+')',body)
   log.info('SQLITE_INSERT rows=%s columns=%s elapsed=%.2fs',len(body),len(hs),time.perf_counter()-insert_started)
   c.execute('CREATE TABLE _更新情報 (項目 TEXT PRIMARY KEY, 値 TEXT)'); c.executemany('INSERT INTO _更新情報 VALUES (?,?)',[('作成日時',datetime.now().isoformat(timespec='seconds')),('RNE',job['rne']),('件数',str(len(body)))])
   c.commit(); ck=c.execute('PRAGMA integrity_check').fetchone()[0]; ct=c.execute(f'SELECT COUNT(*) FROM {qi(job["table"])}').fetchone()[0]
   if ck!='ok' or ct!=len(body):raise RuntimeError('SQLite整合性検査に失敗')
   log.info('SQLITE_VALIDATION integrity=%s rows=%s expected_rows=%s total_elapsed=%.2fs',ck,ct,len(body),time.perf_counter()-sqlite_started)
  finally:c.close()
 elif fmt in ('csv','txt'):
  delimiter=',' if fmt=='csv' else '\t';write_started=time.perf_counter()
  with dst.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.writer(f,delimiter=delimiter,quoting=csv.QUOTE_MINIMAL);w.writerow(hs);w.writerows(body)
  log.info('DELIMITED_WRITE format=%s encoding=utf-8-sig rows=%s columns=%s size=%s elapsed=%.2fs',fmt,len(body),len(hs),dst.stat().st_size,time.perf_counter()-write_started)
 elif fmt=='xlsx':
  # openpyxlのセル逐次appendが環境により極端に遅くなるため、XLSXをZIP/XMLとして直接生成する。
  # すべてinline stringで保存し、中間CSVの内容を文字列として保持する。
  try:
   write_started=time.perf_counter();info=write_xlsx_direct(dst,job.get('sheet') or 'Page1',hs,body)
   log.info('XLSX_DIRECT_WRITE mode=zip_xml sheet=%s rows=%s columns=%s cells=%s size=%s elapsed=%.2fs',info['sheet'],info['rows'],info['columns'],info['cells'],dst.stat().st_size,time.perf_counter()-write_started)
   if info['rows']!=len(body):raise RuntimeError(f'XLSX書込み件数不一致 expected={len(body)} actual={info["rows"]}')
   verify_xlsx_direct(dst,len(hs))
  except Exception as e:
   try:
    if dst.exists():dst.unlink()
   except:pass
   raise RuntimeError('EXCEL(xlsx)出力失敗: '+str(e)) from e
 elif fmt=='accdb':
  pythoncom=None;access_app=None;current_db=None;dao_rs=None;conn=None;rs=None;bulk_dir=None
  template=Path(str(job.get('_accdb_template') or resolve_path('.\\assets\\empty.accdb')))
  if not template.is_file():raise FileNotFoundError(f'ACCDB空テンプレートがありません: {template}')
  if template.suffix.lower()!='.accdb':raise ValueError(f'ACCDBテンプレートの拡張子が不正です: {template}')
  if template.stat().st_size==0:raise ValueError(f'ACCDBテンプレートが空ファイルです: {template}')
  try:
   cache_started=time.perf_counter();cache_dir=dde_staging_folder()/'assets';cache_dir.mkdir(parents=True,exist_ok=True);cached_template=cache_dir/'empty.accdb'
   source_stat=template.stat();cache_hit=False
   if cached_template.is_file():
    cs=cached_template.stat();cache_hit=cs.st_size==source_stat.st_size and cs.st_mtime_ns==source_stat.st_mtime_ns
   if not cache_hit:
    tmp=cache_dir/'.empty.accdb.incoming';shutil.copy2(template,tmp);os.replace(tmp,cached_template)
   log.info('ACCDB_TEMPLATE_CACHE source=%s cache=%s hit=%s size=%s elapsed=%.2fs',template,cached_template,cache_hit,cached_template.stat().st_size,time.perf_counter()-cache_started)
   copy_started=time.perf_counter();shutil.copy2(cached_template,dst)
   if not dst.exists() or dst.stat().st_size!=cached_template.stat().st_size:raise IOError('ACCDBテンプレートのコピー検証に失敗しました')
   log.info('ACCDB_TEMPLATE_COPY file=%s size=%s elapsed=%.2fs',dst,dst.stat().st_size,time.perf_counter()-copy_started)
   bulk_dir=dst.parent/f'{dst.stem}_bulk';shutil.rmtree(bulk_dir,ignore_errors=True);bulk_dir.mkdir(parents=True,exist_ok=True)
   bulk_csv=bulk_dir/'bulk.csv';schema_file=bulk_dir/'schema.ini';prep_started=time.perf_counter()
   with bulk_csv.open('w',encoding='cp932',errors='strict',newline='') as f:
    w=csv.writer(f,lineterminator='\r\n',quoting=csv.QUOTE_MINIMAL);w.writerow(hs);w.writerows(body)
   schema_lines=['[bulk.csv]','Format=CSVDelimited','ColNameHeader=True','CharacterSet=932','MaxScanRows=0']
   for i,h in enumerate(hs,1):schema_lines.append(f'Col{i}="{str(h).replace(chr(34),chr(34)*2)}" LongChar')
   schema_file.write_text('\r\n'.join(schema_lines)+'\r\n',encoding='cp932',errors='strict')
   log.info('ACCDB_BULK_PREP csv=%s schema=%s encoding=cp932 bom=False rows=%s columns=%s size=%s elapsed=%.2fs',bulk_csv,schema_file,len(body),len(hs),bulk_csv.stat().st_size,time.perf_counter()-prep_started)
   import pythoncom,win32com.client
   com_started=time.perf_counter();pythoncom.CoInitialize();log.info('ACCDB_COM_INITIALIZE elapsed=%.2fs',time.perf_counter()-com_started)
   table_raw=str(job.get('table') or '仕掛');table=table_raw.replace(']',']]');cols=', '.join('['+str(h).replace(']',']]')+'] LONGTEXT' for h in hs)
   access_error=None
   try:
    dispatch_started=time.perf_counter();access_app=win32com.client.DispatchEx('Access.Application');dispatch_elapsed=time.perf_counter()-dispatch_started;access_app.Visible=False
    open_started=time.perf_counter();access_app.OpenCurrentDatabase(str(dst));open_elapsed=time.perf_counter()-open_started
    db_started=time.perf_counter();current_db=access_app.CurrentDb();db_elapsed=time.perf_counter()-db_started
    ddl_started=time.perf_counter()
    try:current_db.Execute(f'DROP TABLE [{table}]')
    except:pass
    current_db.Execute(f'CREATE TABLE [{table}] ({cols})');ddl_elapsed=time.perf_counter()-ddl_started
    set_status(activity_detail='ACCDB高速一括取込中',activity_value=f'{len(body):,}行 x {len(hs)}列をTransferTextで登録',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
    transfer_started=time.perf_counter();access_app.DoCmd.TransferText(0,None,table_raw,str(bulk_csv),True);transfer_elapsed=time.perf_counter()-transfer_started
    verify_started=time.perf_counter();dao_rs=current_db.OpenRecordset(f'SELECT COUNT(*) AS C FROM [{table}]');actual=int(dao_rs.Fields(0).Value);dao_rs.Close();dao_rs=None;verify_elapsed=time.perf_counter()-verify_started
    if actual!=len(body):raise RuntimeError(f'ACCDB件数検査に失敗 expected={len(body)} actual={actual}')
    log.info('ACCDB_ACCESS_PIPELINE dispatch_elapsed=%.2fs open_elapsed=%.2fs currentdb_elapsed=%.2fs ddl_elapsed=%.2fs transfer_elapsed=%.2fs verify_elapsed=%.2fs rows=%s columns=%s',dispatch_elapsed,open_elapsed,db_elapsed,ddl_elapsed,transfer_elapsed,verify_elapsed,actual,len(hs))
    # Access終了待ちを短縮するため、DAO/COM参照を内側から順に明示解放する。
    release_started=time.perf_counter();access_pid=0;access_hwnd=0
    try:
     access_hwnd=int(access_app.hWndAccessApp)
     import ctypes
     pid_value=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(access_hwnd,ctypes.byref(pid_value));access_pid=int(pid_value.value)
    except Exception:pass
    log.info('ACCDB_ACCESS_PROCESS hwnd=%s pid=%s',access_hwnd,access_pid)
    try:
     if dao_rs:dao_rs.Close()
    except:pass
    dao_rs=None
    try:
     if current_db:current_db.Close()
    except Exception as e:log.info('ACCDB_DAO_DATABASE_CLOSE_SKIPPED detail=%s',e)
    current_db=None
    gc.collect()
    try:pythoncom.CoFreeUnusedLibraries()
    except Exception:pass
    log.info('ACCDB_COM_REFERENCE_RELEASE elapsed=%.2fs',time.perf_counter()-release_started)
    close_started=time.perf_counter();access_app.CloseCurrentDatabase();log.info('ACCDB_CLOSE_CURRENT_DATABASE elapsed=%.2fs',time.perf_counter()-close_started)
    gc.collect()
    try:pythoncom.CoFreeUnusedLibraries()
    except Exception:pass
    # acQuitSaveNone=2。Access UI/オブジェクト変更の保存確認を抑止する。
    quit_started=time.perf_counter();access_app.Quit(2);quit_elapsed=time.perf_counter()-quit_started;log.info('ACCDB_ACCESS_QUIT_CALL elapsed=%.2fs pid=%s',quit_elapsed,access_pid)
    clear_started=time.perf_counter();defer_com_reference('Access.Application.Quit済み',access_app);access_app=None;log.info('ACCDB_ACCESS_REFERENCE_DEFERRED elapsed=%.2fs deferred_refs=%s',time.perf_counter()-clear_started,len(_deferred_com_refs))
    # 全面GCはCOMファイナライザで長時間停止することがあるため、正常経路では実行しない。
    free_started=time.perf_counter()
    try:pythoncom.CoFreeUnusedLibraries()
    except Exception:pass
    log.info('ACCDB_COM_FREE_AFTER_QUIT elapsed=%.2fs',time.perf_counter()-free_started)
    process_alive='unknown';probe_elapsed=0.0
    if access_pid:
     probe_started=time.perf_counter()
     try:
      probe=subprocess.run(['tasklist','/FI',f'PID eq {access_pid}','/NH'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));process_alive=str(access_pid) in (probe.stdout or '')
     except Exception as e:process_alive=f'probe_error:{e}'
     probe_elapsed=time.perf_counter()-probe_started
    log.info('ACCDB_ACCESS_PROCESS_PROBE pid=%s process_alive=%s elapsed=%.2fs',access_pid,process_alive,probe_elapsed)
   except Exception as e:
    access_error=e;log.warning('ACCDB_ACCESS_PIPELINE_FAILED error=%s fallback=ADO.Recordset',e)
    try:
     if dao_rs:dao_rs.Close()
    except:pass
    try:
     if access_app:access_app.Quit()
    except:pass
    dao_rs=None;current_db=None;access_app=None
   if access_error is not None:
    # Access統合経路が失敗した場合だけ低速なADO互換経路を使用する。
    provider_errors=[];provider=None
    for candidate in ('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0'):
     provider_started=time.perf_counter();test=None
     try:
      test=win32com.client.Dispatch('ADODB.Connection');test.Open(f'Provider={candidate};Data Source={dst};Persist Security Info=False;');conn=test;provider=candidate;log.info('ACCDB_FALLBACK_PROVIDER_OPEN provider=%s elapsed=%.2fs',candidate,time.perf_counter()-provider_started);break
     except Exception as e:
      provider_errors.append(f'{candidate}: {e}')
    if not conn:raise RuntimeError('Access統合経路とADO接続がともに失敗: '+str(access_error)+' | '+' | '.join(provider_errors))
    try:conn.Execute(f'DROP TABLE [{table}]')
    except:pass
    conn.Execute(f'CREATE TABLE [{table}] ({cols})')
    fallback_started=time.perf_counter();rs=win32com.client.Dispatch('ADODB.Recordset');rs.CursorLocation=3;rs.Open(f'SELECT * FROM [{table}] WHERE 1=0',conn,3,4);field_names=[str(x) for x in hs]
    for index,row in enumerate(body,1):
     rs.AddNew(field_names,[str(v) if v is not None else '' for v in row])
     if index%250==0:rs.UpdateBatch();log.info('ACCDB_FALLBACK_PROGRESS rows=%s/%s elapsed=%.1fs',index,len(body),time.perf_counter()-fallback_started)
    rs.UpdateBatch();rs.Close();rs=None
    check=conn.Execute(f'SELECT COUNT(*) AS C FROM [{table}]')[0];actual=int(check.Fields(0).Value);check.Close();conn.Close();conn=None
    if actual!=len(body):raise RuntimeError(f'ACCDBフォールバック件数検査失敗 expected={len(body)} actual={actual}')
    log.info('ACCDB_FALLBACK_COMPLETE provider=%s rows=%s columns=%s elapsed=%.2fs',provider,actual,len(hs),time.perf_counter()-fallback_started)
  except Exception as e:
   for obj,method in ((dao_rs,'Close'),(rs,'Close'),(conn,'Close')):
    try:
     if obj:getattr(obj,method)()
    except:pass
   try:
    if access_app:access_app.Quit()
   except:pass
   try:
    if dst.exists():dst.unlink()
   except:pass
   raise RuntimeError('ACCESS(accdb)出力に失敗しました: '+str(e)) from e
  finally:
   if bulk_dir:shutil.rmtree(bulk_dir,ignore_errors=True)
   if pythoncom:
    try:pythoncom.CoUninitialize()
    except:pass
 else: raise ValueError('未対応の出力形式: '+fmt)
 if not dst.exists() or dst.stat().st_size==0:raise RuntimeError('出力ファイルの作成に失敗しました')
 log.info('出力検証完了 format=%s file=%s size=%s rows=%s columns=%s',fmt,dst,dst.stat().st_size,len(body),len(hs))
 return len(body),len(hs)

def _replace_once(src,dst):
 os.replace(src,dst)
 return True

def _pending_pattern(dst):
 return f'{dst.stem}.pending_*{dst.suffix}'

def apply_pending(dst,backup_root,generations,backup_enabled=True,retention_days=30,generation_limit_enabled=True,backup_mode='generations'):
 """Apply the newest deferred output before the next extraction, if the target is no longer locked."""
 pending=sorted(dst.parent.glob(_pending_pattern(dst)),key=lambda p:p.stat().st_mtime,reverse=True)
 if not pending:return None
 newest=pending[0]
 try:
  publish(newest,dst,backup_root,generations,from_pending=True,backup_enabled=backup_enabled,retention_days=retention_days,generation_limit_enabled=generation_limit_enabled,backup_mode=backup_mode)
  for old in pending[1:]:
   try:old.unlink()
   except OSError:pass
  log.info('保留ファイル適用完了 %s -> %s',newest,dst)
  return newest
 except PermissionError:
  return None

def publish(src,dst,backup_root,generations,from_pending=False,backup_enabled=True,retention_days=30,generation_limit_enabled=True,backup_mode='generations'):
 """Copy locally-created output, then atomically replace the public file.
 If another PC has the target open, keep the new correct file as *.pending_* and return immediately.
 """
 dst.parent.mkdir(parents=True,exist_ok=True)
 bdir=backup_root/dst.stem
 if backup_enabled:bdir.mkdir(parents=True,exist_ok=True)
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
 incoming=dst.parent/f'.{dst.name}.{os.getpid()}.incoming'
 try:
  if from_pending:
   incoming=src
  else:
   copy_started=time.perf_counter();shutil.copy2(src,incoming);log.info('PUBLISH_INCOMING_COPY src=%s incoming=%s size=%s elapsed=%.2fs',src,incoming,incoming.stat().st_size,time.perf_counter()-copy_started)
   if incoming.stat().st_size!=src.stat().st_size:raise IOError('公開先へのコピーサイズが一致しません')
  deadline=time.time()+3.0; last=None
  while time.time()<deadline:
   try:
    if dst.exists() and backup_enabled:
     backup=bdir/f'{dst.stem}_{stamp}{dst.suffix}'
     try:
      backup_started=time.perf_counter();shutil.copy2(dst,backup);log.info('PUBLISH_BACKUP_COPY src=%s backup=%s elapsed=%.2fs',dst,backup,time.perf_counter()-backup_started)
     except (PermissionError,OSError) as e:log.warning('PUBLISH_BACKUP_SKIP error=%s',e)
    replace_started=time.perf_counter();os.replace(incoming,dst);log.info('PUBLISH_ATOMIC_REPLACE target=%s elapsed=%.2fs',dst,time.perf_counter()-replace_started)
    cleanup_started=time.perf_counter();old=sorted(bdir.glob(f'{dst.stem}_*{dst.suffix}'),key=lambda p:p.stat().st_mtime,reverse=True) if backup_enabled else [];removed=0
    cutoff=time.time()-max(1,int(retention_days))*86400
    for index,item in enumerate(old):
     keep_by_generation=index<int(generations)
     keep_by_days=item.stat().st_mtime>=cutoff
     mode=str(backup_mode or 'generations')
     keep=(keep_by_generation if mode=='generations' else keep_by_days if mode=='days' else (keep_by_generation and keep_by_days))
     if keep:continue
     try:item.unlink();removed+=1
     except OSError:pass
    log.info('PUBLISH_BACKUP_CLEANUP candidates=%s removed=%s elapsed=%.2fs',len(old),removed,time.perf_counter()-cleanup_started)
    verify_started=time.perf_counter();published_size=dst.stat().st_size
    if published_size!=src.stat().st_size:raise IOError(f'公開後サイズ不一致 source={src.stat().st_size} target={published_size}')
    log.info('PUBLISH_FINAL_VERIFY target=%s size=%s elapsed=%.2fs',dst,published_size,time.perf_counter()-verify_started)
    return {'published':True,'path':str(dst)}
   except PermissionError as e:last=e;time.sleep(.25)
   except OSError as e:
    if getattr(e,'winerror',None) in (5,32,33):last=e;time.sleep(.25)
    else:raise
  if from_pending:raise PermissionError(f'公開先が使用中です: {dst}') from last
  pending=dst.parent/f'{dst.stem}.pending_{stamp}{dst.suffix}'
  os.replace(incoming,pending)
  log.warning('公開先使用中。新しいファイルを更新保留として保存 %s',pending)
  return {'published':False,'path':str(dst),'pending':str(pending),'reason':'他のPCまたはアプリが公開先ファイルを使用中'}
 finally:
  if incoming.exists() and incoming!=src:
   try:incoming.unlink()
   except OSError:pass

def process_api_parallel_job(j,job_index,total_jobs,cfg,user,pw,server,dde_work,backup):
 from navigator_api import NavigatorApi
 line_name=os.environ.get('NAVI_WORKER_LINE') or threading.current_thread().name
 job_started=time.perf_counter();api_client=None;api_csv=None;xls=None;db=None
 try:
  j['output_file']=resolve_output_filename(j,cfg); log.info('OUTPUT_NAME line=%s job=%s mode=%s pattern=%s resolved_file=%s',line_name,j.get('name'),j.get('naming_mode','fixed'),j.get('output_pattern',''),j['output_file'])
  fmt=validate_output_contract(j,'before-extraction')
  j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb')))
  rp=resolve_rne_path(j,cfg);out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']);target=out_dir/j['output_file']
  apply_pending(target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations')))
  if not rp.is_file():raise FileNotFoundError('RNEがありません: '+str(rp))
  stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+f'_L{job_index}'
  xls=dde_work/f'navi_{job_index}_{stamp}.xls';local_export=dde_work/'export';local_export.mkdir(parents=True,exist_ok=True)
  db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'
  common_intermediate='API_DIRECT_XLSX' if fmt=='xlsx' else 'CSV'
  planned=db if fmt=='xlsx' else dde_work/f'navi_{job_index}_{stamp}.csv'
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='開始',percent=5,detail=fmt);log.info('PARALLEL_JOB_START line=%s job=%s index=%s/%s format=%s target=%s',line_name,j['name'],job_index,total_jobs,fmt,target)
  log.info('PIPELINE job=%s engine=api parallel_line=%s common_intermediate=%s format=%s planned_intermediate=%s converted=%s target=%s',j['name'],line_name,common_intermediate,fmt,planned,db,target)
  api_client=NavigatorApi(resolve_path(cfg['symnavi_exe']),log,resolve_path(cfg.get('navigator_api_dll')) if cfg.get('navigator_api_dll') else None,base_dir=BASE)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='API接続',percent=10,detail='セッション接続');session_started=time.perf_counter();session_elapsed=api_client.open_session(user,pw,server);log.info('PARALLEL_API_SESSION line=%s job=%s dll=%s elapsed=%.2fs is_opened=1',line_name,j['name'],api_client.dll_path,session_elapsed)
  profiles=api_data_source_profiles(resolve_path(cfg['symnavim_conf']))
  if not any(p.get('kind')=='oracle' for p in profiles):
   profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0','credential_source':'navigator_session'})
   log.info('API Oracle接続設定未指定。Navigator認証を1回だけ流用 line=%s job=%s credential_source=navigator_session user_configured=%s password_configured=%s',line_name,j['name'],bool(user),bool(pw))
  for profile in profiles:
   source=profile.get('credential_source') or 'explicit_config'
   elapsed=api_client.connect_data_source(profile)
   log.info('APIデータソース接続完了 line=%s job=%s section=%s kind=%s credential_source=%s elapsed=%.2fs',line_name,j['name'],profile['section'],profile['kind'],source,elapsed)
  api_rne=rp.resolve();rne_stat=api_rne.stat();previous_cwd=os.getcwd()
  try:
   os.chdir(api_rne.parent)
   log.info('APIカタログ読込条件 line=%s dll=%s cwd=%s catalog_full=%s catalog_name=%s extension=%s size=%s mtime_ns=%s strategy=original_fullpath',line_name,api_client.dll_path,os.getcwd(),api_rne,api_rne.name,api_rne.suffix,rne_stat.st_size,rne_stat.st_mtime_ns)
   t=phase_log('api_open_catalog',job=j['name'],line=line_name);handle,api_elapsed=api_client.open_catalog(api_rne);phase_log('api_open_catalog',t,job=j['name'],line=line_name,handle=handle,api_elapsed=f'{api_elapsed:.2f}s',strategy='original_fullpath')
  finally:os.chdir(previous_cwd)
  if (j.get('period') or {}).get('enabled'):update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='期間指定',percent=30,detail='相対期間を適用');apply_dynamic_period(api_client,handle,j,datetime.now(),line=line_name)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='問い合わせ実行',percent=35,detail='API execute');t=phase_log('api_execute_catalog',job=j['name'],line=line_name);api_number,api_elapsed=api_client.execute(handle);phase_log('api_execute_catalog',t,job=j['name'],line=line_name,number=api_number,api_elapsed=f'{api_elapsed:.2f}s')
  t=phase_log('api_get_dimensions',job=j['name'],line=line_name);expected_rows,expected_cols=api_client.dimensions(handle);phase_log('api_get_dimensions',t,job=j['name'],line=line_name,rows=expected_rows,columns=expected_cols)
  api_direct_output=False
  if fmt=='xlsx':
   update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='XLSX保存',percent=58,detail='直接出力')
   try:
    if db.exists():
     try:db.unlink()
     except:pass
    save_wall_started=time.perf_counter();t=phase_log('api_save_xlsx_direct',job=j['name'],line=line_name,target=db,repeat='NAVI_NONREPEAT',ftype='NAVI_XLSX');save_elapsed=api_client.save_xlsx(handle,db);save_wall_elapsed=time.perf_counter()-save_wall_started;phase_log('api_save_xlsx_direct',t,job=j['name'],line=line_name,api_elapsed=f'{save_elapsed:.2f}s',wall_elapsed=f'{save_wall_elapsed:.2f}s',size=db.stat().st_size if db.exists() else 0,throughput_kb_s=f'{(db.stat().st_size/1024/save_wall_elapsed):.1f}' if db.exists() and save_wall_elapsed>0 else '0')
    if not db.is_file() or db.stat().st_size<=0:raise RuntimeError(f'API直接XLSXが作成されませんでした: {db}')
    v=phase_log('api_direct_xlsx_validation',job=j['name'],line=line_name,file=db,mode='fast_header_only');verify_xlsx_fast(db,expected_cols);phase_log('api_direct_xlsx_validation',v,job=j['name'],line=line_name,mode='fast_header_only',rows=expected_rows,columns=expected_cols,size=db.stat().st_size)
    api_direct_output=True;intermediate=db;nr,nc=int(expected_rows),int(expected_cols)
    log.info('API_DIRECT_OUTPUT line=%s job=%s format=xlsx method=NaviSaveData(NAVI_XLSX) rows=%s columns=%s file=%s bytes_per_cell=%.2f',line_name,j['name'],expected_rows,expected_cols,db,(db.stat().st_size/max(1,(int(expected_rows)+1)*int(expected_cols))))
   except Exception as e:
    log.warning('API直接XLSX保存に失敗したためCSV経由へフォールバック line=%s job=%s error=%s',line_name,j['name'],e)
    try:
     if db.exists():db.unlink()
    except:pass
  if not api_direct_output:
   update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='CSV保存',percent=58,detail='API保存')
   api_csv=dde_work/f'navi_{job_index}_{stamp}.csv'
   t=phase_log('api_save_csv',job=j['name'],line=line_name);save_elapsed=api_client.save_csv(handle,api_csv);phase_log('api_save_csv',t,job=j['name'],line=line_name,api_elapsed=f'{save_elapsed:.2f}s',size=api_csv.stat().st_size if api_csv.exists() else 0)
   if not api_csv.is_file() or api_csv.stat().st_size<=0:raise RuntimeError(f'API中間CSVが作成されませんでした: {api_csv}')
   intermediate=api_csv
  t=phase_log('api_close_catalog',job=j['name'],line=line_name);api_client.close_catalog();phase_log('api_close_catalog',t,job=j['name'],line=line_name)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='変換・検証',percent=75,detail=fmt)
  if api_direct_output:
   t=phase_log('format_conversion',job=j['name'],line=line_name,format=fmt,mode='api_direct_xlsx');phase_log('format_conversion',t,job=j['name'],line=line_name,format=fmt,mode='api_direct_xlsx',rows=nr,columns=nc)
  else:
   t=phase_log('format_conversion',job=j['name'],line=line_name,format=fmt);nr,nc=export_data(intermediate,db,j,bool(cfg['settings']['reject_zero_rows']),expected_rows,expected_cols);phase_log('format_conversion',t,job=j['name'],line=line_name,format=fmt,rows=nr,columns=nc)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='公開',percent=90,detail=str(target));t=phase_log('publish',job=j['name'],line=line_name);pub=publish(db,target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations')));phase_log('publish',t,job=j['name'],line=line_name,published=pub['published'])
  total=time.perf_counter()-job_started
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='完了',percent=100,detail=f'{nr}件/{nc}列',elapsed=round(total,1));log.info('PARALLEL_JOB_RESULT line=%s job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s published=%s',line_name,j['name'],fmt,nr,nc,total,target,pub['published'])
  result=f'{j["name"]}: {nr}件/{nc}列 / {total:.1f}秒'+('' if pub['published'] else f' / 更新保留: {pub["pending"]}')
  return {'ok':True,'job':j['name'],'format':fmt,'rows':nr,'columns':nc,'elapsed':total,'target':str(target),'result':result}
 except Exception as e:
  total=time.perf_counter()-job_started
  update_parallel_line(line_name,job=j.get('name',''),job_id=j.get('id',''),state='失敗',percent=100,detail=str(e),elapsed=round(total,1));log.error('PARALLEL_JOB_ERROR line=%s job=%s elapsed=%.2fs error=%s\n%s',line_name,j.get('name'),total,e,traceback.format_exc())
  return {'ok':False,'job':j.get('name',''), 'elapsed':total, 'error':str(e)}
 finally:
  if api_client:
   try:api_client.close()
   except Exception as e:log.warning('Navigator API終了処理失敗 line=%s job=%s error=%s',line_name,j.get('name'),e)
  for p in (xls,api_csv,db):
   try:
    if p:p.unlink()
   except:pass


def _read_worker_json(path,default=None):
 try:return json.loads(Path(path).read_text(encoding='utf-8'))
 except Exception:return default

def run_api_process_batch(jobs,cfg,user,pw,server,dde_work,backup,max_lines,trigger):
 """Run each Navigator API session in an isolated Python process.
 Finished lines immediately pull the next queued query until the reservation queue is empty.
 """
 batch_id=datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8]
 runtime=dde_work/'parallel_runtime'/('parallel_'+batch_id);runtime.mkdir(parents=True,exist_ok=True)
 queue=deque(enumerate(jobs,1));active={};results=[];failures=[];completed=0
 # 各対象(ジョブ)の実状態を job_id 単位で保持し、完了後に「待機」へ戻る不具合を防ぐ。
 completed_ids=[];failed_ids=[];all_job_ids=[j['id'] for j in jobs]
 with active_workers_lock:active_workers.clear()
 batch_started=time.perf_counter(); total=len(jobs); max_lines=max(1,min(int(max_lines),total))
 set_status(parallel_lines=[{'line':f'ライン {n}','job':'','state':'待機','percent':0,'elapsed':0,'detail':'開始待ち','slot':n} for n in range(1,max_lines+1)],queue_total=total,queue_waiting=total,queue_active=0,queue_completed=0,queue_completed_ids=[],queue_failed_ids=[],queue_running_ids=[],queue_waiting_ids=list(all_job_ids),parallel_max_lines=max_lines,parallel_mode=True,symnavi_window=f'独立プロセス {max_lines}ライン')
 log.info('PARALLEL_BATCH_START model=process-isolated trigger=%s batch_id=%s runtime=%s jobs=%s max_lines=%s total_jobs=%s parent_pid=%s',trigger,batch_id,runtime,[j['rne'] for j in jobs],max_lines,total,os.getpid())
 def start_one(slot):
  index,job=queue.popleft();line=f'ライン {slot}'
  job_dir=runtime/f'line_{slot}_{index}';job_dir.mkdir(parents=True,exist_ok=True)
  payload={'job':job,'job_index':index,'total_jobs':total,'cfg':cfg,'user':user,'password':pw,'server':server,'dde_work':str(job_dir/'work'),'backup':str(backup),'line':line}
  Path(payload['dde_work']).mkdir(parents=True,exist_ok=True)
  payload_path=job_dir/'payload.json';result_path=job_dir/'result.json';status_path=job_dir/'status.json'
  payload_path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
  env=os.environ.copy();env['NAVI_WORKER_LINE']=line;env['NAVI_WORKER_STATUS']=str(status_path);env['NAVI_WORKER_RESULT']=str(result_path)
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  proc=subprocess.Popen([sys.executable,str(BASE/'api_worker.py'),str(payload_path)],cwd=str(BASE),env=env,creationflags=flags)
  active[slot]={'proc':proc,'job':job,'index':index,'line':line,'status':status_path,'result':result_path,'started':time.perf_counter()}
  with active_workers_lock:active_workers[slot]=proc
  update_parallel_line(line,job=job['name'],job_id=job['id'],state='起動',percent=2,detail=f'予約 {index}/{total} / PID {proc.pid}',queue_index=index,slot=slot,started_at=datetime.now().isoformat(timespec='seconds'))
  log.info('WORKER_START batch_id=%s line=%s pid=%s job=%s queue_index=%s/%s',batch_id,line,proc.pid,job['name'],index,total)
 for slot in range(1,max_lines+1):
  if queue:start_one(slot)
 while active:
  if cancel_requested.is_set():
   log.info('PARALLEL_BATCH_CANCELLED batch_id=%s active=%s queued=%s',batch_id,len(active),len(queue))
   queue.clear()
   for slot,item in list(active.items()):
    try:item['proc'].terminate()
    except Exception:pass
   for slot,item in list(active.items()):
    try:item['proc'].wait(timeout=5)
    except Exception:
     try:item['proc'].kill()
     except Exception:pass
    failures.append({'ok':False,'job':item['job']['name'],'error':'ユーザーにより中断されました','elapsed':time.perf_counter()-item['started']})
    failed_ids.append(item['job']['id'])
    record_job_run(item['job']['id'],item['job']['name'],'cancelled',trigger,detail='ユーザーにより中断されました')
    update_parallel_line(item['line'],job=item['job']['name'],job_id=item['job']['id'],state='中断',percent=100,detail='ユーザーにより中断されました',elapsed=round(time.perf_counter()-item['started'],1))
    with active_workers_lock:active_workers.pop(slot,None)
    del active[slot]
   break
  for slot,item in list(active.items()):
   worker_status=_read_worker_json(item['status'])
   if worker_status:
    update_parallel_line(item['line'],job=worker_status.get('job') or item['job']['name'],job_id=item['job']['id'],state=worker_status.get('state','処理中'),percent=worker_status.get('percent',0),detail=worker_status.get('detail',''),elapsed=round(time.perf_counter()-item['started'],1),pid=worker_status.get('pid',item['proc'].pid))
   rc=item['proc'].poll()
   if rc is None:continue
   result=_read_worker_json(item['result'],{'ok':False,'job':item['job']['name'],'error':f'Worker終了コード {rc}','elapsed':time.perf_counter()-item['started']})
   completed+=1
   (results if result.get('ok') else failures).append(result)
   (completed_ids if result.get('ok') else failed_ids).append(item['job']['id'])
   log.info('WORKER_END batch_id=%s line=%s pid=%s job=%s returncode=%s ok=%s elapsed=%.2fs',batch_id,item['line'],item['proc'].pid,item['job']['name'],rc,result.get('ok'),result.get('elapsed',0))
   record_job_run(item['job']['id'],item['job']['name'],'ok' if result.get('ok') else 'failed',trigger,detail=(result.get('result') or result.get('error') or ''),rows=result.get('rows'),cols=result.get('columns'),output_file=Path(result.get('target') or '').name)
   with active_workers_lock:active_workers.pop(slot,None)
   del active[slot]
   if queue and not cancel_requested.is_set():start_one(slot)
  waiting=len(queue);running=len(active)
  running_ids=[item['job']['id'] for item in active.values()]
  waiting_ids=[job['id'] for _,job in queue]
  set_status(completed_jobs=completed,current_index=min(completed+running,total),current_job_name=f'予約キュー処理中: 実行 {running} / 待機 {waiting}',step='save',step_label=f'API並列処理 実行 {running}・待機 {waiting}・完了 {completed}',step_percent=round(100*completed/max(1,total)),activity_detail=f'{max_lines}ラインで予約クエリを処理',activity_value=f'実行 {running} / 待機 {waiting} / 完了 {completed}/{total}',queue_total=total,queue_waiting=waiting,queue_active=running,queue_completed=completed,queue_completed_ids=list(completed_ids),queue_failed_ids=list(failed_ids),queue_running_ids=running_ids,queue_waiting_ids=waiting_ids,failed_jobs=len(failed_ids),job_errors=[{'job':x.get('job'),'error':str(x.get('error') or '')} for x in failures])
  time.sleep(.25)
 elapsed=time.perf_counter()-batch_started
 sequential_sum=sum(float(r.get('elapsed',0)) for r in results+failures);speedup=sequential_sum/elapsed if elapsed else 0
 summary='; '.join(f"{r.get('job')}={float(r.get('elapsed',0)):.1f}s" for r in results)
 log.info('PARALLEL_BATCH_END model=process-isolated total_jobs=%s succeeded=%s failed=%s max_lines=%s elapsed=%.2fs sequential_sum=%.2fs speedup=%.2fx job_elapsed_summary=%s',total,len(results),len(failures),max_lines,elapsed,sequential_sum,speedup,summary)
 set_status(parallel_speedup=round(speedup,2),queue_waiting=0,queue_active=0,queue_completed=completed,queue_completed_ids=list(completed_ids),queue_failed_ids=list(failed_ids),queue_running_ids=[],queue_waiting_ids=[],parallel_mode=True)
 shutil.rmtree(runtime,ignore_errors=True)
 log.info('PARALLEL_RUNTIME_CLEANUP path=%s exists_after=%s',runtime,runtime.exists())
 return results,failures,elapsed

def process(job_ids=None,trigger='manual',parallel_lines_override=None,run_id=None):
 if not run_lock.acquire(False):raise RuntimeError('別の処理が実行中です')
 cancel_requested.clear()
 proc=srv=api_client=None; hide_done=None; window_watch_stop=None; window_watch_thread=None; access_prewarm_thread=None
 try:
  startup_started=time.perf_counter();cfg_started=time.perf_counter();cfg=load();log.info('STARTUP_PHASE phase=config_load elapsed=%.2fs',time.perf_counter()-cfg_started);jobs=[j for j in cfg['jobs'] if j.get('enabled') and (not job_ids or j['id'] in job_ids)]
  if not jobs:raise ValueError('実行対象がありません')
  selection_elapsed=time.perf_counter()-cfg_started;first_job=jobs[0]; first_fmt=normalize_output_format(first_job.get('output_format'),first_job.get('output_file')); first_target=resolve_path(first_job.get('output_folder') or cfg['default_output_folder'])/canonical_output_file(first_job.get('output_file'),first_fmt); progress.started=time.time(); requested_lines=max(1,int(parallel_lines_override or 1)); execution_mode='parallel' if str(cfg['settings'].get('extract_engine') or 'api').lower()=='api' and len(jobs)>1 and requested_lines>1 else 'serial'; set_status(run_id=run_id or uuid.uuid4().hex,execution_mode=execution_mode,requested_lines=requested_lines,parallel_mode=(execution_mode=='parallel'),parallel_lines=[],queue_total=0,queue_waiting=0,queue_active=0,queue_completed=0,queue_completed_ids=[],queue_failed_ids=[],queue_running_ids=[],queue_waiting_ids=[j['id'] for j in jobs],parallel_max_lines=(requested_lines if execution_mode=='parallel' else 0),parallel_speedup=0,batch_job_ids=[j['id'] for j in jobs]); set_status(running=True,current='準備中',current_job_id=first_job['id'],current_job_name=first_job['name'],current_index=1,total_jobs=len(jobs),completed_jobs=0,failed_jobs=0,output_format=first_fmt,output_file=canonical_output_file(first_job.get('output_file'),first_fmt),output_target=str(first_target),started_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=0,symnavi_window='起動待ち',step='prepare',step_label='設定を確認しています',step_percent=3,last_result='実行中',error_detail='',job_errors=[]); log.info('BUILD_VERSION=%s',BUILD_VERSION); log.info('処理開始 trigger=%s jobs=%s',trigger,[j['rne'] for j in jobs]);log.info('STARTUP_PHASE phase=config_and_job_selection elapsed=%.2fs',selection_elapsed)
  for k in ('symnavi_exe','symnavim_conf','symnavim_def'):
   if not resolve_path(cfg[k]).is_file():raise FileNotFoundError(f'{k}がありません: {cfg[k]}')
  cred_started=time.perf_counter();user,pw,server,_=creds(resolve_path(cfg['symnavim_conf']));log.info('STARTUP_PHASE phase=credential_load elapsed=%.2fs',time.perf_counter()-cred_started);path_started=time.perf_counter();rne_root=resolve_path(cfg['rne_folder']);backup=resolve_path(cfg['backup_folder']);dde_work=dde_staging_folder();log.info('STARTUP_PHASE phase=path_prepare elapsed=%.2fs total=%.2fs',time.perf_counter()-path_started,time.perf_counter()-startup_started);log.info('共通一時保存先: %s',dde_work)
  engine=str(cfg['settings'].get('extract_engine') or 'api').lower(); set_status(extract_engine=engine); log.info('抽出エンジン engine=%s stability_profile=%s',engine,cfg['settings'].get('stability_profile','stable_api_serial'))
  if any(normalize_output_format(j.get('output_format'),j.get('output_file'))=='accdb' for j in jobs):
   access_prewarm_thread=prewarm_access_async('process_contains_accdb')
  api_parallel_lines=max(1,min(int(cfg['settings'].get('api_parallel_max_lines',24) or 24),int(parallel_lines_override if parallel_lines_override is not None else cfg['settings'].get('api_parallel_lines',1) or 1)))
  log.info('PARALLEL_DECISION engine=%s selected_jobs=%s configured_lines=%s eligible=%s model=process-isolated',engine,len(jobs),api_parallel_lines,engine=='api' and len(jobs)>1 and api_parallel_lines>1)
  log.info('EXECUTION_MODE mode=%s requested_lines=%s selected_jobs=%s',('parallel-process' if engine=='api' and len(jobs)>1 and api_parallel_lines>1 else 'serial'),api_parallel_lines,len(jobs))
  if engine=='api' and len(jobs)>1 and api_parallel_lines>1:
   results,failures,batch_elapsed=run_api_process_batch(jobs,cfg,user,pw,server,dde_work,backup,api_parallel_lines,trigger)
   if cancel_requested.is_set():raise RunCancelled(f'{len(results)}/{len(jobs)}件完了後に中断されました')
   if failures:
    set_status(job_errors=[{'job':r.get('job'),'error':str(r.get('error') or '')} for r in failures],failed_jobs=len(failures))
    raise RuntimeError('API並列実行で%d件失敗しました\n'%len(failures)+'\n'.join('・%s: %s'%(r.get('job'),r.get('error')) for r in failures))
   msg='正常終了 | 全件%sファイル / %.1f秒 | '%(len(results),batch_elapsed)+' | '.join(r['result'] for r in results)
   progress('complete','すべての処理が完了しました',100);set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-progress.started));log.info(msg)
   return
  if engine=='api':
   from navigator_api import NavigatorApi
   progress('launch','Navigator APIを初期化しています',8); api_client=NavigatorApi(resolve_path(cfg['symnavi_exe']),log,resolve_path(cfg.get('navigator_api_dll')) if cfg.get('navigator_api_dll') else None,base_dir=BASE); set_status(symnavi_window='APIモード')
   progress('dde','Navigator ServerへAPI接続しています',15); t=time.perf_counter(); elapsed=api_client.open_session(user,pw,server); log.info('APIセッション接続完了 dll=%s elapsed=%.2fs is_opened=1',api_client.dll_path,elapsed)
   profiles=api_data_source_profiles(resolve_path(cfg['symnavim_conf']))
   # Oracle専用設定がなければ、Navigator認証情報をOracle接続へ1回だけ流用する。
   # 明示的なApiOracle設定を常に優先し、ユーザー名・パスワードの実値はログへ出さない。
   if not any(p.get('kind')=='oracle' for p in profiles):
    profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0','credential_source':'navigator_session'})
    log.info('API Oracle接続設定未指定。Navigator認証を1回だけ流用 credential_source=navigator_session user_configured=%s password_configured=%s',bool(user),bool(pw))
   for profile in profiles:
    source=profile.get('credential_source') or 'explicit_config'
    progress('dde',f'APIデータソースへ接続しています: {profile["kind"]}',18,activity_detail='公式API接続工程',activity_value=f'{profile["section"]} / {source}')
    try:
     elapsed=api_client.connect_data_source(profile)
     log.info('APIデータソース接続完了 section=%s kind=%s credential_source=%s elapsed=%.2fs',profile['section'],profile['kind'],source,elapsed)
    except Exception:
     log.error('APIデータソース接続失敗 section=%s kind=%s credential_source=%s retry=False',profile['section'],profile['kind'],source)
     raise
  elif engine=='dde':
   progress('launch','SymfoNaviを起動しています',8); proc=subprocess.Popen(f'"{str(resolve_path(cfg['symnavi_exe']))}" -d -u"{user}","{pw}","{server}"'); set_status(symnavi_window='起動済み'); progress('dde','SymfoNaviへのDDE接続を待っています',15); srv,conv=dde_connect(int(cfg['settings']['dde_timeout_seconds'])); hide_done=start_hidden_symnavi(proc,cfg['settings']); log.info('SymfoNavi定期監視を抽出中は停止 mode=pipeline-priority')
  else:raise ValueError('抽出エンジンが不正です: '+engine)
  progress('ready','処理の準備が完了しました',20); results=[]; completed_ids=[]
  for job_index,j in enumerate(jobs,1):
   if cancel_requested.is_set():raise RunCancelled(f'{job_index-1}/{len(jobs)}件完了後に中断されました')
   j['output_file']=resolve_output_filename(j,cfg); log.info('OUTPUT_NAME job=%s mode=%s pattern=%s resolved_file=%s',j['name'],j.get('naming_mode','fixed'),j.get('output_pattern',''),j['output_file'])
   set_status(current_index=job_index,current_job_id=j['id'],current_job_name=j['name'],output_format=normalize_output_format(j.get('output_format'),j.get('output_file')),output_file=canonical_output_file(j.get('output_file'),normalize_output_format(j.get('output_format'),j.get('output_file'))))
   preflight_started=phase_log('job_preflight',job=j['name']); progress('open',f'{j["name"]}: 入出力先を確認しています',22,activity_detail='事前確認',activity_value='出力先・保留ファイル・RNEを確認'); rp=resolve_rne_path(j,cfg); out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']); fmt=validate_output_contract(j,'before-extraction'); j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb'))); target=out_dir/j['output_file']; set_status(output_target=str(target)); log.info('実行設定 job=%s format=%s output_file=%s target=%s',j['name'],fmt,j['output_file'],target); apply_pending(target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations'))); phase_log('job_preflight',preflight_started,job=j['name'],rne=rp,target=target)
   if not rp.is_file():raise FileNotFoundError('RNEがありません: '+str(rp))
   stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f'); xls=dde_work/f'navi_{job_index}_{stamp}.xls'; local_export=dde_work/'export'; local_export.mkdir(parents=True,exist_ok=True); db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'; log.info('変換作業先 local=%s',db); esc=lambda x:str(x).replace('"','""')
   api_planned=(db if engine=='api' and fmt=='xlsx' else (dde_work/f'navi_{job_index}_{stamp}.csv' if engine=='api' else xls));common_intermediate=('API_DIRECT_XLSX' if engine=='api' and fmt=='xlsx' else ('CSV' if engine=='api' else 'XLS'))
   job_started=time.perf_counter(); log.info('PIPELINE job=%s engine=%s common_intermediate=%s format=%s planned_intermediate=%s converted=%s target=%s',j['name'],engine,common_intermediate,fmt,api_planned,db,target)
   if engine=='api':
    progress('open',f'{j["name"]}: APIでRNEを読み込んでいます',28,current_job_id=j['id'],activity_detail='Navigator API 1/3',activity_value=str(rp))
    # RNEを単体コピーすると、RNE内部の相対参照や同一フォルダー上の関連定義が切れる可能性がある。
    # API方式では元の配置を維持し、正規化した絶対パスをNaviOpenCatalogへ渡す。
    api_rne=rp.resolve()
    if not api_rne.is_file():raise FileNotFoundError(f'API用RNEがありません: {api_rne}')
    try:
     with api_rne.open('rb') as f:f.read(1)
    except OSError as e:raise PermissionError(f'API用RNEを読み取れません: {api_rne}: {e}') from e
    rne_stat=api_rne.stat()
    previous_cwd=os.getcwd()
    try:
     # cwdも元RNEフォルダーへ合わせ、RNE内部の相対参照とAPI側の探索条件を両立する。
     os.chdir(api_rne.parent)
     log.info('APIカタログ読込条件 dll=%s cwd=%s catalog_full=%s catalog_name=%s extension=%s size=%s mtime_ns=%s strategy=original_fullpath',api_client.dll_path,os.getcwd(),api_rne,api_rne.name,api_rne.suffix,rne_stat.st_size,rne_stat.st_mtime_ns)
     t=phase_log('api_open_catalog',job=j['name']); handle,api_elapsed=api_client.open_catalog(api_rne); phase_log('api_open_catalog',t,job=j['name'],handle=handle,api_elapsed=f'{api_elapsed:.2f}s',strategy='original_fullpath')
    finally:os.chdir(previous_cwd)
    if (j.get('period') or {}).get('enabled'):
     progress('open',f'{j["name"]}: 相対期間を適用しています',34,activity_detail='Navigator API 期間指定',activity_value=(compute_period(j.get('period'),datetime.now()) or {}).get('summary',''));applied=apply_dynamic_period(api_client,handle,j,datetime.now())
     if applied:log.info('実行設定 job=%s dynamic_period=%s',j['name'],applied.get('summary'))
    progress('save',f'{j["name"]}: APIで問い合わせを実行しています',38,activity_detail='Navigator API 2/3',activity_value='問い合わせ実行・ダウンロード')
    t=phase_log('api_execute_catalog',job=j['name']); api_number,api_elapsed=api_client.execute(handle); phase_log('api_execute_catalog',t,job=j['name'],number=api_number,api_elapsed=f'{api_elapsed:.2f}s')
    t=phase_log('api_get_dimensions',job=j['name']);expected_rows,expected_cols=api_client.dimensions(handle);phase_log('api_get_dimensions',t,job=j['name'],rows=expected_rows,columns=expected_cols)
    api_direct_output=False;api_csv=None
    if fmt=='xlsx':
     progress('wait',f'{j["name"]}: APIからXLSXへ直接保存しています',50,activity_detail='Navigator API 3/3',activity_value=str(db))
     try:
      if db.exists():
       try:db.unlink()
       except:pass
      save_wall_started=time.perf_counter();t=phase_log('api_save_xlsx_direct',job=j['name'],target=db,repeat='NAVI_NONREPEAT',ftype='NAVI_XLSX');save_elapsed=api_client.save_xlsx(handle,db);save_wall_elapsed=time.perf_counter()-save_wall_started;phase_log('api_save_xlsx_direct',t,job=j['name'],api_elapsed=f'{save_elapsed:.2f}s',wall_elapsed=f'{save_wall_elapsed:.2f}s',size=db.stat().st_size if db.exists() else 0,throughput_kb_s=f'{(db.stat().st_size/1024/save_wall_elapsed):.1f}' if db.exists() and save_wall_elapsed>0 else '0')
      if not db.is_file() or db.stat().st_size<=0:raise RuntimeError(f'API直接XLSXが作成されませんでした: {db}')
      v=phase_log('api_direct_xlsx_validation',job=j['name'],file=db,mode='fast_header_only');verify_xlsx_fast(db,expected_cols);phase_log('api_direct_xlsx_validation',v,job=j['name'],mode='fast_header_only',rows=expected_rows,columns=expected_cols,size=db.stat().st_size)
      api_direct_output=True;intermediate=db
      log.info('API_DIRECT_OUTPUT job=%s format=xlsx method=NaviSaveData(NAVI_XLSX) rows=%s columns=%s file=%s bytes_per_cell=%.2f',j['name'],expected_rows,expected_cols,db,(db.stat().st_size/max(1,(int(expected_rows)+1)*int(expected_cols))))
     except Exception as e:
      log.warning('API直接XLSX保存に失敗したためCSV経由へフォールバック job=%s error=%s',j['name'],e)
      try:
       if db.exists():db.unlink()
      except:pass
    if not api_direct_output:
     api_csv=dde_work/f'navi_{job_index}_{stamp}.csv'
     progress('wait',f'{j["name"]}: API結果を高速CSVへ保存しています',50,activity_detail='Navigator API 3/3',activity_value=str(api_csv))
     t=phase_log('api_save_csv',job=j['name']);save_elapsed=api_client.save_csv(handle,api_csv);phase_log('api_save_csv',t,job=j['name'],api_elapsed=f'{save_elapsed:.2f}s',size=api_csv.stat().st_size if api_csv.exists() else 0)
     if not api_csv.is_file() or api_csv.stat().st_size<=0:raise RuntimeError(f'API中間CSVが作成されませんでした: {api_csv}')
     intermediate=api_csv
    progress('close',f'{j["name"]}: APIカタログを解放しています',62,activity_detail='API抽出完了',activity_value=f'期待値 {expected_rows}行 x {expected_cols}列');t=phase_log('api_close_catalog',job=j['name']);api_client.close_catalog();phase_log('api_close_catalog',t,job=j['name'])
   else:
    progress('open',f'{j["name"]}: RNEを開いています',28,current_job_id=j['id'],activity_detail='共通抽出工程 1/3',activity_value='全形式共通')
    t=phase_log('rne_open',job=j['name']); dde_exec(conv,'Open',f'[Open("{esc(rp)}")]'); phase_log('rne_open',t,job=j['name'])
    progress('save',f'{j["name"]}: 共通XLSを生成しています',38,activity_detail='共通抽出工程 2/3',activity_value=str(xls))
    t=phase_log('xls_save',job=j['name']); dde_exec(conv,'Save',f'[Save("{esc(xls)}", "EXCEL")]',expected_output=xls); phase_log('xls_save',t,job=j['name'])
    progress('wait',f'{j["name"]}: 共通XLSを検証しています',50,activity_detail='共通抽出工程 3/3',activity_value='ファイル安定・構造確認')
    t=phase_log('xls_stability',job=j['name']); wait_file(xls,int(cfg['settings']['output_wait_seconds']),j); phase_log('xls_stability',t,job=j['name'],size=xls.stat().st_size)
    intermediate=xls;expected_rows=None;expected_cols=None
    progress('close',f'{j["name"]}: 抽出画面を閉じています',62,activity_detail='共通抽出完了',activity_value=f'{xls.stat().st_size:,} bytes')
    t=phase_log('rne_close',job=j['name']); dde_exec(conv,'Close','[Close()]'); phase_log('rne_close',t,job=j['name'])
   if fmt=='accdb' and access_prewarm_thread is not None:
    join_started=time.perf_counter();alive_before=access_prewarm_thread.is_alive();access_prewarm_thread.join(timeout=2.0);log.info('ACCDB_PREWARM_JOIN alive_before=%s alive_after=%s elapsed=%.2fs',alive_before,access_prewarm_thread.is_alive(),time.perf_counter()-join_started)
   if engine=='api' and fmt=='xlsx' and locals().get('api_direct_output'):
    progress('export',f'{j["name"]}: API直接XLSXを検証しています',70,activity_detail='形式別変換工程',activity_value='CSV変換なし / API直接出力')
    t=phase_log('format_conversion',job=j['name'],format=fmt,mode='api_direct_xlsx');nr,nc=int(expected_rows),int(expected_cols);phase_log('format_conversion',t,job=j['name'],format=fmt,mode='api_direct_xlsx',rows=nr,columns=nc)
   else:
    progress('export',f'{j["name"]}: {fmt.upper()}へ変換しています',70,activity_detail='形式別変換工程',activity_value=f'{intermediate.suffix.upper()} -> {fmt.upper()}')
    t=phase_log('format_conversion',job=j['name'],format=fmt); nr,nc=export_data(intermediate,db,j,bool(cfg['settings']['reject_zero_rows']),expected_rows,expected_cols); phase_log('format_conversion',t,job=j['name'],format=fmt,rows=nr,columns=nc)
   progress('publish',f'{j["name"]}: 検査済みファイルを公開しています',90,activity_detail='公開工程',activity_value=str(target))
   t=phase_log('publish',job=j['name']); pub=publish(db,target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations'))); phase_log('publish',t,job=j['name'],published=pub['published'])
   total=time.perf_counter()-job_started; results.append(f'{j["name"]}: {nr}件/{nc}列 / {total:.1f}秒'+('' if pub['published'] else f' / 更新保留: {pub["pending"]}')); completed_ids.append(j['id']); set_status(completed_jobs=job_index,queue_completed_ids=list(completed_ids)); log.info('JOB_RESULT job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s',j['name'],fmt,nr,nc,total,target); record_job_run(j['id'],j['name'],'ok',trigger,detail=f'{nr}件/{nc}列 / {total:.1f}秒',rows=nr,cols=nc,output_file=j['output_file'])
   # 元RNEはAPIが直接参照するため削除対象に含めない。生成物だけを後片付けする。
   for p in (xls,locals().get('api_csv'),db):
    try:
     if p:p.unlink()
    except:pass
  msg='正常終了 | '+' | '.join(results); progress('complete','すべての処理が完了しました',100); set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-progress.started)); log.info(msg)
 except RunCancelled as e:
  msg='中断されました: '+str(e); set_status(step='cancelled',step_label='ユーザーの操作により中断しました',step_percent=100,last_result=msg,error_detail='',last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-getattr(progress,'started',time.time()))); log.info('RUN_CANCELLED %s',msg)
  if status.get('running') and status.get('current_job_id'):record_job_run(status['current_job_id'],status.get('current_job_name',''),'cancelled',trigger,detail=msg)
 except Exception as e:
  msg='異常終了: '+str(e); set_status(step='error',step_label='処理を完了できませんでした',failed_jobs=1,step_percent=100,last_result=msg,error_detail=str(e),last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-getattr(progress,'started',time.time()))); log.error('%s\n%s',msg,traceback.format_exc())
  if status.get('current_job_id'):record_job_run(status['current_job_id'],status.get('current_job_name',''),'failed',trigger,detail=str(e))
  if not status.get('job_errors'):set_status(job_errors=[{'job':status.get('current_job_name','') or '実行対象','error':str(e)}])
  raise
 finally:
  cancel_requested.clear()
  set_status(running=False,current='',current_job_id='',symnavi_window='終了済み')
  if window_watch_stop:window_watch_stop.set()
  if window_watch_thread:window_watch_thread.join(timeout=1.0)
  if hide_done:hide_done.set()
  if api_client:
   try:api_client.close()
   except Exception as e:log.warning('Navigator API終了処理失敗: %s',e)
  if srv:
   try:srv.Shutdown()
   except:pass
  if proc and proc.poll() is None:
   try:proc.terminate()
   except:pass
  run_lock.release()
def bg(ids,trigger,parallel_lines_override=None,run_id=None):
 try:process(ids,trigger,parallel_lines_override,run_id)
 except:pass


def queue_snapshot():
 with command_queue_lock:
  items=[]
  if active_command:
   x=dict(active_command);x['state']='running';x['position']=0;items.append(x)
  for i,item in enumerate(command_queue,1):
   x=dict(item);x['state']='waiting';x['position']=i;items.append(x)
  return {'items':items,'active_id':active_command.get('id') if active_command else None,'waiting_count':len(command_queue),'total_count':len(items)}

def enqueue_command(job_ids,trigger,parallel_lines):
 cfg=load(); selected=[j for j in cfg['jobs'] if j.get('enabled') and (not job_ids or j['id'] in job_ids)]
 if not selected:raise ValueError('実行対象がありません')
 item={'id':uuid.uuid4().hex,'job_ids':[j['id'] for j in selected],'job_names':[j['name'] for j in selected],'trigger':trigger,'parallel_lines':max(1,min(8,int(parallel_lines or 1))),'enqueued_at':datetime.now().isoformat(timespec='seconds'),'count':len(selected)}
 with command_queue_lock:
  command_queue.append(item);position=len(command_queue)+(1 if active_command else 0)
 command_queue_event.set();log.info('COMMAND_QUEUE_ENQUEUE id=%s position=%s jobs=%s lines=%s trigger=%s',item['id'],position,item['job_names'],item['parallel_lines'],trigger)
 return item,position

def command_dispatcher():
 global active_command
 while not stop_event.is_set():
  command_queue_event.wait(1.0)
  if stop_event.is_set():break
  with command_queue_lock:
   if active_command is not None:continue
   if not command_queue:
    command_queue_event.clear();continue
   active_command=command_queue.pop(0);item=dict(active_command)
  log.info('COMMAND_QUEUE_START id=%s remaining=%s jobs=%s lines=%s',item['id'],len(command_queue),item['job_names'],item['parallel_lines'])
  try:process(item['job_ids'],item['trigger'],item['parallel_lines'],item['id'])
  except Exception as e:log.error('COMMAND_QUEUE_FAILED id=%s error=%s',item['id'],e)
  finally:
   with command_queue_lock:active_command=None
   log.info('COMMAND_QUEUE_END id=%s remaining=%s',item['id'],len(command_queue))
   command_queue_event.set()

def schedule_key(job,rule,now):
 kind=rule.get('type','daily'); tm=rule.get('time','06:00'); hh,mm=map(int,tm.split(':')) if ':' in tm else (6,0)
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60))); return str(int(now.timestamp()//(mins*60))) if rule.get('enabled') else None
 if now.hour!=hh or now.minute!=mm:return None
 if kind=='daily':return now.strftime('%Y-%m-%d')+tm
 if kind=='weekdays' and now.weekday() in rule.get('weekdays',[]):return now.strftime('%Y-%m-%d')+tm
 if kind=='monthly' and now.day in rule.get('month_days',[1]):return now.strftime('%Y-%m-%d')+tm
 if kind=='specific_dates' and now.strftime('%Y-%m-%d') in rule.get('dates',[]):return now.strftime('%Y-%m-%d')+tm
 return None

def next_occurrence(rule,now):
 """予定一覧表示用に、ルール1件が次に実行される日時を1つ返す（過去日時・無効ルールはNone）。"""
 if not rule.get('enabled',True):return None
 kind=rule.get('type','daily'); tm=str(rule.get('time') or '06:00')
 try:hh,mm=map(int,tm.split(':'))
 except Exception:hh,mm=6,0
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60) or 60)); epoch=int(now.timestamp())
  return datetime.fromtimestamp((epoch//(mins*60)+1)*(mins*60))
 if kind=='daily':
  cand=now.replace(hour=hh,minute=mm,second=0,microsecond=0); return cand if cand>now else cand+timedelta(days=1)
 if kind=='weekdays':
  days=set(rule.get('weekdays') or [])
  if not days:return None
  for add in range(8):
   d=now+timedelta(days=add)
   if d.weekday() in days:
    cand=d.replace(hour=hh,minute=mm,second=0,microsecond=0)
    if cand>now:return cand
  return None
 if kind=='monthly':
  days=rule.get('month_days') or [1]
  for add in range(62):
   d=(now+timedelta(days=add)).date(); last=calendar.monthrange(d.year,d.month)[1]
   target={(last if x==-1 else x) for x in days}
   if d.day in target:
    cand=datetime(d.year,d.month,d.day,hh,mm)
    if cand>now:return cand
  return None
 if kind=='specific_dates':
  best=None
  for ds in (rule.get('dates') or []):
   try:y,mo,da=map(int,str(ds).split('-'))
   except Exception:continue
   cand=datetime(y,mo,da,hh,mm)
   if cand>now and (best is None or cand<best):best=cand
  return best
 return None

def expand_rule_occurrences(rule,start,end,limit=400):
 """カレンダー表示用に、ルール1件が[start,end]の期間に実行される日時をすべて返す。
 interval（一定間隔）は件数が膨大になり得るため、日ごとの回数へ集約した要約情報を別途返す。"""
 if not rule.get('enabled',True):return [],[]
 kind=rule.get('type','daily'); tm=str(rule.get('time') or '06:00')
 try:hh,mm=map(int,tm.split(':'))
 except Exception:hh,mm=6,0
 points=[]; interval_days=[]
 day=start.date(); last_day=end.date()
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60) or 60)); per_day=max(1,(24*60)//mins)
  d=day
  while d<=last_day:
   interval_days.append({'date':d.isoformat(),'minutes':mins,'count':per_day})
   d+=timedelta(days=1)
  return points,interval_days
 if kind=='weekdays':
  wd=set(rule.get('weekdays') or [])
  d=day
  while d<=last_day:
   if d.weekday() in wd:points.append(datetime(d.year,d.month,d.day,hh,mm))
   d+=timedelta(days=1)
 elif kind=='daily':
  d=day
  while d<=last_day:
   points.append(datetime(d.year,d.month,d.day,hh,mm)); d+=timedelta(days=1)
 elif kind=='monthly':
  days=rule.get('month_days') or [1]; d=day
  while d<=last_day:
   lastn=calendar.monthrange(d.year,d.month)[1]; target={(lastn if x==-1 else x) for x in days}
   if d.day in target:points.append(datetime(d.year,d.month,d.day,hh,mm))
   d+=timedelta(days=1)
 elif kind=='specific_dates':
  for ds in (rule.get('dates') or []):
   try:y,mo,da=map(int,str(ds).split('-'))
   except Exception:continue
   cand=datetime(y,mo,da,hh,mm)
   if start<=cand<=end:points.append(cand)
 return points[:limit],interval_days

def job_schedule_hint(rules):
 if not rules:return '手動のみ'
 if len(rules)>1:return f'複数指定 ({len(rules)}件)'
 r=rules[0]; kind=r.get('type','daily')
 if kind=='interval':return f'定期 ({max(1,int(r.get("interval_minutes",60) or 60))}分ごと)'
 return {'daily':'毎日','weekdays':'曜日指定','monthly':'月日指定','specific_dates':'特定日'}.get(kind,kind)

def job_schedule_preview(job,now):
 if not job.get('enabled'):return {'id':job['id'],'next_run':None,'hint':'対象が無効'}
 rules=[r for r in job.get('schedules',[]) if r.get('enabled')]
 candidates=[c for c in (next_occurrence(r,now) for r in rules) if c]
 next_run=min(candidates) if candidates else None
 return {'id':job['id'],'next_run':next_run.isoformat(timespec='minutes') if next_run else None,'hint':job_schedule_hint(rules)}
def any_enabled_schedule_exists():
 try:
  cfg=load()
  return any(j.get('enabled') and any(r.get('enabled') for r in j.get('schedules',[])) for j in cfg['jobs'])
 except Exception:
  return True  # 判定に失敗した場合は自動実行を壊さない側へ倒し、終了させない。

def heartbeat_watchdog():
 time.sleep(10)
 while not stop_event.wait(2):
  try:
   now=time.time()
   with heartbeat_lock:
    silence=now-last_heartbeat_at
    clients={k:dict(v) for k,v in heartbeat_clients.items()}
   # pagehide通知後も同じclient_idのハートビートが猶予時間内に戻れば、再読込・戻る/進む・BFCache復帰として終了を取り消す。
   closing=[(cid,v) for cid,v in clients.items() if v.get('closing_at') and now-float(v.get('closing_at') or 0)>=CLOSE_GRACE_SECONDS]
   active=[(cid,v) for cid,v in clients.items() if not v.get('closing_at')]
   if closing and not active:
    ids=','.join(cid for cid,_ in closing)
    log.info('APP_TABS_EMPTY_CONFIRMED closing_clients=%s active_app_tabs=0 grace=%ss action=python_exit',ids,CLOSE_GRACE_SECONDS)
    for h in log.handlers:h.flush()
    stop_event.set();os._exit(0)
   # ハートビート途絶だけでは終了しない。ネットワーク断、スリープ、ブラウザー破棄との誤判定を避ける。
   if silence>HEARTBEAT_TIMEOUT_SECONDS:
    log.warning('HEARTBEAT_DEGRADED silence=%.0fs server_kept_alive=1',silence)
  except Exception:
   log.exception('ハートビート監視エラー')

def scheduler():
 time.sleep(3)
 while not stop_event.wait(15):
  try:
   if status['running']:continue
   cfg=load(); now=datetime.now(); st=load_scheduler_state()
   due_ids=[]; due_rules=[]
   for j in cfg['jobs']:
    if not j.get('enabled'):continue
    for r in j.get('schedules',[]):
     if not r.get('enabled'):continue
     key=schedule_key(j,r,now); state_key=f'{j["id"]}:{r["id"]}'
     if key and st.get(state_key)!=key:
      st[state_key]=key; save_scheduler_state(state_key,key); due_ids.append(j['id']); due_rules.append(r.get('name',r['type'])); break
   if due_ids:
    log.info('SCHEDULE_BATCH_READY jobs=%s count=%s rules=%s',due_ids,len(due_ids),due_rules)
    enqueue_command(due_ids,f'schedule-batch:{len(due_ids)}',1); return
  except:log.exception('スケジュール判定エラー')

@app.get('/')
def index():
 response=app.make_response(render_template('index.html'));response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0';response.headers['Pragma']='no-cache';return response
@app.get('/favicon.ico')
def favicon():
 # favicon.icoの中身はSVG。拡張子と実体の食い違いでブラウザーが弾かないよう、明示的にimage/svg+xmlで返す。
 f=BASE/'favicon.ico'
 if not f.is_file():return ('',404)
 response=app.make_response(f.read_bytes());response.headers['Content-Type']='image/svg+xml';response.headers['Cache-Control']='public, max-age=86400';return response
@app.get('/api/config')
def get_config():
 c=load()
 try:*_,s=creds(resolve_path(c['symnavim_conf'])); c['credential_status']='読取可能 ['+s+']'
 except Exception as e:c['credential_status']='未確認: '+str(e)
 now=datetime.now()
 for j in c['jobs']:
  pattern=str(j.get('output_pattern') or '').strip()
  # 変数扱いは「命名モードがtemplate」かつ「既知の変数トークンが実在する」場合のみ。
  is_var=str(j.get('naming_mode') or 'fixed').lower()=='template' and has_template_variables(pattern)
  j['output_is_variable']=is_var
  if is_var:
   try:
    rp=None
    try:rp=str(resolve_rne_path(j,c))
    except Exception:rp=None
    fmt=normalize_output_format(j.get('output_format'),j.get('output_file'))
    j['output_file_preview']=resolve_output_filename(j,c,now)
    segs=render_filename_segments(pattern,job=j,rne_path=rp,now=now)
    segs.append({'text':output_extension(fmt),'var':False})
    j['output_file_segments']=segs
   except Exception:
    j['output_file_preview']='';j['output_file_segments']=[]
 return jsonify(c)
@app.put('/api/config')
def put_config():save(request.get_json(force=True));return jsonify(ok=True)
@app.post('/api/settings/parallel-lines')
def set_parallel_lines():
 # 並列ライン数だけを即時に保存する軽量エンドポイント。ユーザーが変更したら他の未保存編集に触れずその値を確定し、次回起動以降も保持する。
 data=request.get_json(silent=True) or {}
 try:lines=max(1,min(8,int(data.get('lines',2) or 2)))
 except Exception:lines=2
 c=load(); c['settings']['api_parallel_lines']=lines; c['settings']['stability_profile']='balanced_api_parallel'; save(c)
 log.info('設定保存 job=(共通) 並列ライン数を保存 api_parallel_lines=%s',lines)
 return jsonify(ok=True,api_parallel_lines=lines)
@app.get('/api/schedule-preview')
def schedule_preview():
 c=load(); now=datetime.now(); runs=load_job_runs()
 return jsonify(items=[{**job_schedule_preview(j,now),**last_run_info(runs.get(j['id']))} for j in c['jobs']])
@app.get('/api/calendar')
def calendar_view():
 # カレンダービュー用: 指定月の予定（scheduled）と実施履歴（executed）を日付ごとに返す。
 try:year=int(request.args.get('year')); month=int(request.args.get('month'))
 except Exception:
  now=datetime.now(); year,month=now.year,now.month
 month=max(1,min(12,month))
 first=datetime(year,month,1); last_day=calendar.monthrange(year,month)[1]; last=datetime(year,month,last_day,23,59,59)
 c=load(); now=datetime.now()
 scheduled=[]; interval_summary={}
 for j in c['jobs']:
  if not j.get('enabled'):continue
  for r in j.get('schedules',[]):
   if not r.get('enabled'):continue
   points,interval_days=expand_rule_occurrences(r,first,last)
   for p in points:
    scheduled.append({'date':p.strftime('%Y-%m-%d'),'time':p.strftime('%H:%M'),'datetime':p.isoformat(timespec='minutes'),'job_id':j['id'],'job_name':j['name'],'rule_id':r.get('id'),'rule_name':r.get('name',''),'rule_type':r.get('type',''),'past':p<now})
   for d in interval_days:
    key=d['date']; entry=interval_summary.setdefault(key,{'date':key,'jobs':{},'total':0})
    entry['jobs'].setdefault(j['id'],{'job_id':j['id'],'job_name':j['name'],'rule_name':r.get('name',''),'minutes':d['minutes'],'count':d['count']})
    entry['total']+=d['count']
 interval_list=[{'date':v['date'],'total':v['total'],'items':list(v['jobs'].values())} for v in interval_summary.values()]
 # 実施履歴（追記式run_history）から当月分を取得。
 executed=[]
 try:
  with settings_connection() as conn:
   for row in conn.execute("SELECT id,job_id,job_name,finished_at,status,trigger,rows,cols,output_file FROM run_history WHERE finished_at>=? AND finished_at<=? ORDER BY finished_at",(first.strftime('%Y-%m-%dT00:00:00'),last.strftime('%Y-%m-%dT23:59:59'))):
    fa=str(row['finished_at'] or '')
    if len(fa)<10:continue
    trig=str(row['trigger'] or ''); kind='schedule' if trig.startswith('schedule') else 'manual'
    executed.append({'id':row['id'],'date':fa[:10],'time':fa[11:16],'datetime':fa,'job_id':row['job_id'],'job_name':row['job_name'],'status':row['status'],'trigger':kind,'rows':row['rows'],'cols':row['cols'],'output_file':row['output_file']})
 except Exception:
  log.exception('CALENDAR_HISTORY_FAILED')
 return jsonify(year=year,month=month,days_in_month=last_day,first_weekday=first.weekday(),today=now.strftime('%Y-%m-%d'),scheduled=scheduled,interval=interval_list,executed=executed)
@app.post('/api/schedule/quick-add')
def schedule_quick_add():
 # カレンダーから特定日の1回実行ルールを素早く追加する。既存の対象へspecific_datesルールを1件加える。
 d=request.get_json(force=True) or {}; job_id=d.get('job_id'); date=str(d.get('date') or '').strip(); tm=str(d.get('time') or '06:00').strip()
 if not job_id or not date:return jsonify(error='対象と日付を指定してください'),400
 c=load(); j=next((x for x in c['jobs'] if x['id']==job_id),None)
 if not j:return jsonify(error='対象が見つかりません'),404
 rule={'id':uuid.uuid4().hex,'enabled':True,'name':d.get('name') or f'{date} 単発実行','type':'specific_dates','time':tm,'dates':[date]}
 j.setdefault('schedules',[]).append(rule); save(c)
 log.info('CALENDAR_QUICK_ADD job=%s date=%s time=%s',j['name'],date,tm)
 return jsonify(ok=True,rule=rule)
@app.post('/api/run-history/delete')
def delete_run_history():
 # カレンダーの実施記録（run_history）を削除する。id指定（複数可）または日付＋任意の対象指定に対応する。
 d=request.get_json(silent=True) or {}
 ids=[int(x) for x in (d.get('ids') or []) if str(x).strip().isdigit()]
 date=str(d.get('date') or '').strip(); job_id=str(d.get('job_id') or '').strip()
 removed=0
 try:
  with settings_connection() as conn:
   if ids:
    conn.execute('DELETE FROM run_history WHERE id IN ('+','.join('?' for _ in ids)+')',ids); removed=conn.total_changes
   elif date:
    if job_id and job_id!='all':
     cur=conn.execute("DELETE FROM run_history WHERE substr(finished_at,1,10)=? AND job_id=?",(date,job_id))
    else:
     cur=conn.execute("DELETE FROM run_history WHERE substr(finished_at,1,10)=?",(date,))
    removed=cur.rowcount if cur.rowcount is not None else conn.total_changes
   else:
    return jsonify(error='削除対象（idまたは日付）を指定してください'),400
 except Exception as e:
  log.exception('RUN_HISTORY_DELETE_FAILED'); return jsonify(error=str(e)),500
 log.info('RUN_HISTORY_DELETE ids=%s date=%s job_id=%s removed=%s',ids,date or '-',job_id or '-',removed)
 return jsonify(ok=True,removed=removed)
@app.post('/api/preview-filename')
def preview_filename():
 data=request.get_json(force=True) or {}; c=load(); now=datetime.now()
 job={'rne':data.get('rne') or '','rne_path':data.get('rne_path') or '','name':data.get('name') or '','table':data.get('table') or '','output_format':data.get('format') or 'sqlite3','output_file':data.get('output_file') or '','naming_mode':'template','output_pattern':data.get('pattern') or ''}
 rne_found=False; mtime=ctime=None
 try:
  rp=resolve_rne_path(job,c)
  if rp and Path(rp).is_file():
   rne_found=True; st=Path(rp).stat(); mtime=datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M'); ctime=datetime.fromtimestamp(getattr(st,'st_ctime',st.st_mtime)).strftime('%Y-%m-%d %H:%M')
 except Exception:pass
 try:filename=resolve_output_filename(job,c,now)
 except Exception as e:return jsonify(ok=False,error=str(e)),400
 pattern=str(job.get('output_pattern') or '').strip()
 is_var=has_template_variables(pattern)
 fmt=normalize_output_format(job.get('output_format'),job.get('output_file'))
 try:
  rp2=str(resolve_rne_path(job,c))
 except Exception:rp2=None
 segments=render_filename_segments(pattern,job=job,rne_path=rp2,now=now) if is_var else []
 if segments:segments.append({'text':output_extension(fmt),'var':False})
 return jsonify(ok=True,filename=filename,is_variable=is_var,segments=segments,rne_found=rne_found,rne_mtime=mtime,rne_ctime=ctime,now=now.strftime('%Y-%m-%d %H:%M:%S'))
@app.post('/api/period-preview')
def period_preview():
 # 相対期間設定から、処理日時基準で実際に抽出される期間を試算して返す。
 d=request.get_json(force=True) or {}
 period={'enabled':True,'unit':(d.get('unit') if d.get('unit') in ('month','day') else 'month'),'from_offset':d.get('from_offset',0),'to_offset':d.get('to_offset',0),'control_point':d.get('control_point') or ''}
 spec=compute_period(period,datetime.now())
 if not spec:return jsonify(ok=False,error='期間を計算できません'),400
 return jsonify(ok=True,now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),control_point=period['control_point'],**spec)
@app.post('/api/period-control-points')
def period_control_points():
 # 対象RNEを開いて時間型管理ポイントを自動検出する（Navigator API方式で接続可能な場合の補助機能）。
 data=request.get_json(force=True) or {}; c=load()
 if str(c['settings'].get('extract_engine') or 'api').lower()!='api':
  return jsonify(ok=False,error='この自動検出はNavigator API方式のときに使用できます。DDE方式では管理ポイント名を手入力してください'),200
 job=next((x for x in c['jobs'] if x['id']==data.get('job_id')),None) if data.get('job_id') else None
 rne_value=str(data.get('rne_path') or (job.get('rne_path') if job else '') or '').strip()
 if not rne_value:return jsonify(ok=False,error='RNEファイルを指定してください'),200
 tmp={'rne_path':rne_value,'rne':Path(rne_value).name}
 try:rp=resolve_rne_path(tmp,c)
 except Exception as e:return jsonify(ok=False,error=f'RNEパスの解決に失敗しました: {e}'),200
 if not Path(rp).is_file():return jsonify(ok=False,error=f'RNEが見つかりません: {rp}'),200
 from navigator_api import NavigatorApi
 api=None
 try:
  user,pw,server,_=creds(resolve_path(c['symnavim_conf']))
  api=NavigatorApi(resolve_path(c.get('symnavi_exe','')),log,resolve_path(c.get('navigator_api_dll')) if c.get('navigator_api_dll') else None,base_dir=BASE)
  if not api.supports_period_change():
   return jsonify(ok=False,error='このDLLは管理ポイント操作APIを公開していません。管理ポイント名を手入力してください'),200
  api.open_session(user,pw,server)
  profiles=api_data_source_profiles(resolve_path(c['symnavim_conf']))
  if not any(p.get('kind')=='oracle' for p in profiles):
   profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0'})
  for profile in profiles:api.connect_data_source(profile)
  prev=os.getcwd()
  try:
   os.chdir(Path(rp).parent); handle,_=api.open_catalog(Path(rp).resolve())
  finally:os.chdir(prev)
  points=api.list_time_control_points(handle); api.close_catalog()
  time_points=[p for p in points if p.get('is_time')]
  log.info('PERIOD_CP_DETECT rne=%s total=%s time=%s',rp,len(points),len(time_points))
  return jsonify(ok=True,points=points,time_points=time_points,count=len(points),time_count=len(time_points))
 except Exception as e:
  log.exception('PERIOD_CP_DETECT_FAILED rne=%s',rp)
  return jsonify(ok=False,error=str(e)),200
 finally:
  if api:
   try:api.close()
   except Exception:pass
@app.post('/api/run')
def run_all():
 try:
  data=request.get_json(silent=True) or {};requested=max(1,min(8,int(data.get('parallel_lines',1) or 1)))
  item,position=enqueue_command(data.get('job_ids'),'manual',requested)
  return jsonify(ok=True,queued=True,queue_id=item['id'],position=position,parallel_lines=requested,job_names=item['job_names'])
 except Exception as e:return jsonify(error=str(e)),400
@app.post('/api/run/<job_id>')
def run_one(job_id):
 try:
  item,position=enqueue_command([job_id],'manual-single',1)
  return jsonify(ok=True,queued=True,queue_id=item['id'],position=position,parallel_lines=1,job_names=item['job_names'])
 except Exception as e:return jsonify(error=str(e)),400
@app.post('/api/run/cancel')
def cancel_run():
 with command_queue_lock:
  queue_cleared=len(command_queue); command_queue.clear()
 if not status.get('running'):
  log.info('CANCEL_REQUESTED_IDLE queue_cleared=%s',queue_cleared)
  return jsonify(ok=True,was_running=False,workers_terminated=0,queue_cleared=queue_cleared)
 cancel_requested.set()
 with active_workers_lock:workers=list(active_workers.values())
 for p in workers:
  try:p.terminate()
  except Exception:pass
 log.info('CANCEL_REQUESTED workers_terminated=%s queue_cleared=%s',len(workers),queue_cleared)
 return jsonify(ok=True,was_running=True,workers_terminated=len(workers),queue_cleared=queue_cleared)
@app.get('/api/execution-queue')
def get_execution_queue():
 response=jsonify(queue_snapshot());response.headers['Cache-Control']='no-store';return response
@app.delete('/api/execution-queue/<queue_id>')
def delete_execution_queue(queue_id):
 with command_queue_lock:
  for i,item in enumerate(command_queue):
   if item['id']==queue_id:
    removed=command_queue.pop(i);log.info('COMMAND_QUEUE_DELETE id=%s jobs=%s',queue_id,removed['job_names']);return jsonify(ok=True)
 return jsonify(error='実行中または対象が見つかりません'),409
@app.post('/api/execution-queue/<queue_id>/move')
def move_execution_queue(queue_id):
 data=request.get_json(silent=True) or {};direction=data.get('direction')
 with command_queue_lock:
  idx=next((i for i,x in enumerate(command_queue) if x['id']==queue_id),None)
  if idx is None:return jsonify(error='待機キューにありません'),404
  dest=idx-1 if direction=='up' else idx+1
  if dest<0 or dest>=len(command_queue):return jsonify(ok=True)
  command_queue[idx],command_queue[dest]=command_queue[dest],command_queue[idx]
  log.info('COMMAND_QUEUE_MOVE id=%s direction=%s new_position=%s',queue_id,direction,dest+1)
 return jsonify(ok=True)
@app.get('/api/status')
def get_status():
 response=jsonify(status);response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0';return response
def dll_diagnostic_issues(attempts,python_bits=None):
 issues=[];existing=[x for x in attempts if x.get('exists')]
 if not existing:issues.append({'level':'error','title':'DLLが見つかりません','detail':'設定パスとC:\\NAVIAP配下の検索候補にSymNaviA.dllがありません。','action':'参照ボタンでDLLを指定するか、配置場所を確認してください。'})
 mismatches=[x for x in existing if x.get('dll_bits') and python_bits and int(x['dll_bits'])!=int(python_bits)]
 if mismatches:issues.append({'level':'error','title':'DLLとPythonのbit数が一致しません','detail':f'実行中のPythonは{python_bits}bitですが、異なるbit数のDLLが検出されました。','action':f'{python_bits}bit版DLLを指定するか、Pythonのbit数をDLLへ合わせてください。'})
 errors=[x for x in attempts if x.get('result')=='load_error' or x.get('error')]
 if errors:issues.append({'level':'error','title':'DLLは存在しますが読み込めません','detail':str(errors[0].get('error') or 'WindowsがDLLをロードできませんでした。'),'action':'同一フォルダーの依存DLL、Visual C++ランタイム、アクセス権を確認してください。'})
 loaded=[x for x in attempts if x.get('result')=='loaded']
 if loaded:issues.append({'level':'ok','title':'DLLを正常に読み込みました','detail':str(loaded[0].get('path') or ''),'action':'Navigator APIを利用できます。'})
 return issues

def _api_diag_cache_path():return LOCAL_RUNTIME/'api_diagnostic_cache.json'
def _dll_signature(path):
 try:
  p=Path(path);st=p.stat();return {'path':str(p),'size':st.st_size,'mtime_ns':st.st_mtime_ns}
 except OSError:return None
def _read_api_diag_cache():
 try:
  d=json.loads(_api_diag_cache_path().read_text(encoding='utf-8'));sig=_dll_signature(d.get('dll',''))
  if d.get('ok') and sig and d.get('signature')==sig and d.get('python_bits')==struct.calcsize('P')*8:return d
 except Exception:pass
 return None
def _write_api_diag_cache(info):
 try:
  payload=dict(info);payload['signature']=_dll_signature(info.get('dll',''));payload['cached_at']=datetime.now().isoformat(timespec='seconds')
  tmp=_api_diag_cache_path().with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8');os.replace(tmp,_api_diag_cache_path())
 except Exception:log.exception('API診断キャッシュ保存失敗')

@app.get('/api/navigator-api-status')
def navigator_api_status():
 c=load();force=request.args.get('full')=='1'
 if not force:
  cached=_read_api_diag_cache()
  if cached:
   log.info('API_DIAG cache_hit=1 dll=%s dll_bits=%s',cached.get('dll'),cached.get('dll_bits'))
   cached=dict(cached);cached['cached']=True;cached['issues']=dll_diagnostic_issues(cached.get('attempts') or [],cached.get('python_bits'));return jsonify(cached)
 try:
  from navigator_api import NavigatorApi
  started=time.perf_counter();api=NavigatorApi(resolve_path(c.get('symnavi_exe','')),log,resolve_path(c.get('navigator_api_dll')) if c.get('navigator_api_dll') else None,base_dir=BASE);info=api.info();api.close();info['elapsed']=round(time.perf_counter()-started,3);info['cached']=False;info['issues']=dll_diagnostic_issues(info.get('attempts') or [],info.get('python_bits'))
  # 起動後API診断の実測。DLLロード(BOXフォールバック時は特に遅い)の所要時間を可視化する。
  log.info('API_DIAG cache_hit=0 elapsed=%.3fs dll=%s dll_bits=%s attempts=%s selection=%s',info.get('elapsed'),info.get('dll'),info.get('dll_bits'),len(info.get('attempts') or []),info.get('selection_reason'))
  _write_api_diag_cache(info);return jsonify(info)
 except Exception as e:
  try:
   from navigator_api import candidate_dlls,pe_bits
   pybits=struct.calcsize('P')*8;attempts=[]
   for p in candidate_dlls(resolve_path(c.get('symnavi_exe','')),resolve_path(c.get('navigator_api_dll')) if c.get('navigator_api_dll') else None,[BASE/'Config'/'NAVIAP',BASE/'NAVIAP']):
    exists=p.is_file();bits=pe_bits(p) if exists else None;attempts.append({'path':str(p),'exists':exists,'dll_bits':bits,'python_bits':pybits,'result':'bit_mismatch' if exists and bits and bits!=pybits else 'not_found'})
  except Exception:pybits=None;attempts=[]
  return jsonify(ok=False,error=str(e),mode='Navigator API',cached=False,attempts=attempts,issues=dll_diagnostic_issues(attempts,pybits)),200

@app.get('/api/log')
def get_log():
 p=LOCAL_LOGS/'app.log'; return jsonify(text='\n'.join(p.read_text(encoding='utf-8',errors='replace').splitlines()[-1200:]) if p.exists() else '')
@app.post('/api/log/clear')
def clear_log():
 p=LOCAL_LOGS/'app.log'; p.parent.mkdir(exist_ok=True)
 p.write_text('',encoding='utf-8')
 return jsonify(ok=True)
@app.post('/api/log/delete-lines')
def delete_log_lines():
 data=request.get_json(silent=True) or {}; remove=set(data.get('lines') or [])
 p=LOCAL_LOGS/'app.log'
 if not p.exists():return jsonify(ok=True,removed=0)
 lines=p.read_text(encoding='utf-8',errors='replace').splitlines()
 kept=[x for x in lines if x not in remove]
 p.write_text('\n'.join(kept)+('\n' if kept else ''),encoding='utf-8')
 return jsonify(ok=True,removed=len(lines)-len(kept))

@app.post('/api/log/delete-old')
def delete_old_log():
 data=request.get_json(silent=True) or {}
 days=max(1,min(3650,int(data.get('days',30) or 30)))
 cutoff=datetime.now().timestamp()-(days*86400)
 p=LOCAL_LOGS/'app.log'
 if not p.exists():return jsonify(ok=True,removed=0,kept=0,days=days)
 lines=p.read_text(encoding='utf-8',errors='replace').splitlines()
 kept=[];removed=0
 for line in lines:
  try:
   ts=datetime.strptime(line[:23],'%Y-%m-%d %H:%M:%S,%f').timestamp()
   if ts<cutoff:
    removed+=1;continue
  except Exception:
   pass
  kept.append(line)
 p.write_text('\n'.join(kept)+('\n' if kept else ''),encoding='utf-8')
 log.info('LOG_RETENTION_DELETE days=%s removed=%s kept=%s',days,removed,len(kept))
 return jsonify(ok=True,removed=removed,kept=len(kept),days=days)

@app.post('/api/pick-file')
def pick_file():
 try:
  import tkinter as tk
  from tkinter import filedialog
  data=request.get_json(silent=True) or {}; initial=str(resolve_path(data.get('initial') or str(BASE))); types=data.get('types') or [['すべてのファイル','*.*']]
  root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
  path=filedialog.askopenfilename(initialdir=str(Path(initial).parent if Path(initial).suffix else Path(initial)),filetypes=[tuple(x) for x in types])
  root.destroy(); return jsonify(path=path)
 except Exception as e:return jsonify(error=str(e)),500
@app.post('/api/pick-folder')
def pick_folder():
 try:
  import tkinter as tk
  from tkinter import filedialog
  data=request.get_json(silent=True) or {}; initial=str(resolve_path(data.get('initial') or str(BASE))); root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True); path=filedialog.askdirectory(initialdir=initial); root.destroy(); return jsonify(path=path)
 except Exception as e:return jsonify(error=str(e)),500
@app.post('/api/open-path')
def open_path():
 # 出力先は社内共有パス(UNC)やローカルパスであり、Webアドレスではない。
 # ブラウザーを遷移させず、このサーバー(ローカルPC)側でエクスプローラーを開く。
 data=request.get_json(silent=True) or {}; raw=str(data.get('path') or '').strip()
 if not raw:return jsonify(ok=False,error='出力先が指定されていません'),400
 if os.name!='nt':return jsonify(ok=False,error='フォルダーを開けるのはWindowsのみです'),400
 try:
  target=resolve_path(raw)
  # ファイル指定ならその親フォルダーを開く。存在しない場合は明示エラー(Web遷移させない)。
  if target.is_file():target=target.parent
  if not target.exists():return jsonify(ok=False,error=f'出力先が見つかりません: {target}'),404
  os.startfile(str(target))  # type: ignore[attr-defined]
  log.info('OPEN_PATH path=%s resolved=%s',raw,target)
  return jsonify(ok=True,resolved=str(target))
 except Exception as e:
  log.exception('OPEN_PATH_FAILED path=%s',raw); return jsonify(ok=False,error=str(e)),500
@app.post('/api/path-convert')
def path_convert():
 data=request.get_json(silent=True) or {}; value=str(data.get('value') or '').strip(); mode=data.get('mode','absolute')
 if not value:return jsonify(value='',resolved=str(BASE),base=str(BASE),is_relative=False)
 resolved=resolve_path(value).resolve()
 if mode=='relative':
  try:converted='.\\'+str(resolved.relative_to(BASE.resolve())).replace('/','\\')
  except ValueError:
   try:converted=os.path.relpath(str(resolved),str(BASE.resolve())).replace('/','\\')
   except ValueError:return jsonify(error='別ドライブまたはUNC経路のため、このアプリ基準の相対パスへ変換できません。絶対パスを使用してください。'),400
 else:converted=str(resolved)
 return jsonify(value=converted,resolved=str(resolved),base=str(BASE.resolve()),is_relative=not Path(converted).is_absolute())

@app.get('/api/output-capabilities')
def output_capabilities():
 result={'sqlite3':{'ok':True,'detail':'Python標準機能'},'csv':{'ok':True,'detail':'Python標準機能'},'txt':{'ok':True,'detail':'Python標準機能'}}
 try:
  import openpyxl
  result['xlsx']={'ok':True,'detail':'openpyxl '+openpyxl.__version__}
 except Exception as e:result['xlsx']={'ok':False,'detail':'openpyxl未導入: '+str(e)}
 pythoncom=None
 try:
  import pythoncom, win32com.client
  pythoncom.CoInitialize(); conn=win32com.client.Dispatch('ADODB.Connection'); template=resolve_path(load().get('accdb_template','.\\assets\\empty.accdb')); result['accdb']={'ok':template.is_file(),'detail':('テンプレート方式: '+str(template)) if template.is_file() else ('ACCDBテンプレート未配置: '+str(template))}
 except Exception as e:result['accdb']={'ok':False,'detail':'pywin32 COM利用不可: '+str(e)}
 finally:
  if pythoncom:
   try:pythoncom.CoUninitialize()
   except:pass
 return jsonify(result)

def nearby_search_roots():
 roots=[]
 for p in (BASE,BASE.parent,BASE.parent.parent):
  if p.exists() and p not in roots:roots.append(p)
 for p in list(roots):
  try:
   for child in p.iterdir():
    if child.is_dir() and child not in roots:roots.append(child)
  except OSError:pass
 return roots

def find_nearby_file(filename,limit=8):
 if not filename:return []
 target=Path(filename).name.lower(); found=[]; seen=set()
 for root in nearby_search_roots():
  try:
   for p in root.rglob('*'):
    try:
     if p.is_file() and p.name.lower()==target:
      key=str(p.resolve()).lower()
      if key not in seen:seen.add(key); found.append(str(p.resolve()))
      if len(found)>=limit:return found
    except OSError:pass
  except OSError:pass
 return found

def check_path_item(value,kind='file',expected_name=''):
 p=resolve_path(value); ok=p.is_file() if kind=='file' else p.is_dir(); candidates=[]
 if not ok and kind=='file':candidates=find_nearby_file(expected_name or p.name)
 return {'ok':ok,'configured':str(value),'resolved':str(p),'candidates':candidates,'needs_reselect':not ok and not candidates}

@app.post('/api/path-check')
def path_check():
 d=request.get_json(force=True); item=d.get('item'); job_id=d.get('job_id'); c=load()
 if item in ('symnavim_conf','symnavim_def','accdb_template'):
  expected={'symnavim_conf':'symnavim.conf','symnavim_def':'symnavim.def','accdb_template':'empty.accdb'}[item]; result=check_path_item(c.get(item,''),'file',expected); result.update(item=item,label=expected)
 elif item=='rne':
  j=next((x for x in c['jobs'] if x['id']==job_id),None)
  if not j:return jsonify(error='対象が見つかりません'),404
  if d.get('value') is not None:j=dict(j,rne_path=d.get('value'),rne=d.get('expected_name') or j.get('rne'))
  rp=resolve_rne_path(j,c); result={'ok':rp.is_file(),'configured':str(j.get('rne_path') or j.get('rne')),'resolved':str(rp),'candidates':[],'needs_reselect':False}; result['candidates']=find_nearby_file(j.get('rne')) if not result['ok'] else []; result['needs_reselect']=not result['ok'] and not result['candidates']; result.update(item='rne',job_id=job_id,label=j.get('rne'))
 else:return jsonify(error='確認対象が不正です'),400
 return jsonify(result)

@app.post('/api/apply-path-suggestion')
def apply_path_suggestion():
 d=request.get_json(force=True); item=d.get('item'); candidate=d.get('candidate'); job_id=d.get('job_id')
 if not candidate or not Path(candidate).is_file():return jsonify(error='修正候補が存在しません'),400
 c=load()
 try:stored=str(Path(candidate).resolve().relative_to(BASE.resolve()))
 except ValueError:stored=str(Path(candidate).resolve())
 if not stored.startswith('.') and not Path(stored).is_absolute():stored='.\\'+stored.replace('/','\\')
 if item in ('symnavim_conf','symnavim_def','accdb_template'):c[item]=stored
 elif item=='rne':
  j=next((x for x in c['jobs'] if x['id']==job_id),None)
  if not j:return jsonify(error='対象が見つかりません'),404
  j['rne_path']=stored; j['rne']=Path(candidate).name
 else:return jsonify(error='修正対象が不正です'),400
 save(c); return jsonify(ok=True,path=stored)

def _viewer_output_path(job,cfg):
 run=(load_job_runs().get(job.get('id')) or {});filename=str(run.get('output_file') or job.get('output_file') or '')
 folder=resolve_path(job.get('output_folder') or cfg.get('default_output_folder'));candidate=folder/filename
 if candidate.is_file():return candidate
 try:
  current=folder/resolve_output_filename(job,cfg)
  if current.is_file():return current
 except Exception:pass
 return candidate

def read_preview_data(path,job,limit=500):
 fmt=normalize_output_format(job.get('output_format'),path.name);headers=[];rows=[];total=None
 if fmt=='sqlite3':
  with sqlite3.connect(path) as conn:
   table=str(job.get('table') or '');names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_更新情報' ORDER BY name")]
   if table not in names:table=names[0] if names else ''
   if not table:raise ValueError('表示できるテーブルがありません')
   headers=[x[1] for x in conn.execute(f'PRAGMA table_info({qi(table)})')];total=conn.execute(f'SELECT COUNT(*) FROM {qi(table)}').fetchone()[0];rows=conn.execute(f'SELECT * FROM {qi(table)} LIMIT ?',(limit,)).fetchall()
 elif fmt in ('csv','txt'):
  data=None;delimiter=',' if fmt=='csv' else '\t'
  for enc in ('utf-8-sig','cp932','utf-8'):
   try:
    with path.open('r',encoding=enc,newline='') as h:data=list(csv.reader(h,delimiter=delimiter))
    break
   except UnicodeDecodeError:continue
  if data is None:raise UnicodeError('文字コードを判定できません')
  headers=data[0] if data else [];rows=data[1:limit+1];total=max(0,len(data)-1)
 elif fmt=='xlsx':
  from openpyxl import load_workbook
  wb=load_workbook(path,read_only=True,data_only=True)
  try:
   ws=wb[job.get('sheet')] if job.get('sheet') in wb.sheetnames else wb[wb.sheetnames[0]];it=ws.iter_rows(values_only=True);headers=list(next(it,()))
   for _,row in zip(range(limit),it):rows.append(row)
   total=max(0,(ws.max_row or 1)-1)
  finally:wb.close()
 elif fmt=='accdb':
  if os.name!='nt':raise RuntimeError('ACCDBプレビューはWindowsでのみ利用できます')
  import pythoncom,win32com.client
  pythoncom.CoInitialize();conn=None;rs=None
  try:
   errs=[]
   for provider in ('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0'):
    try:conn=win32com.client.Dispatch('ADODB.Connection');conn.Open(f'Provider={provider};Data Source={path};Persist Security Info=False;');break
    except Exception as e:errs.append(str(e));conn=None
   if not conn:raise RuntimeError('ACE OLEDBで開けません: '+' / '.join(errs))
   table=str(job.get('table') or '').replace(']',']]');rs=win32com.client.Dispatch('ADODB.Recordset');rs.Open(f'SELECT TOP {int(limit)} * FROM [{table}]',conn,0,1);headers=[str(rs.Fields(i).Name) for i in range(rs.Fields.Count)]
   while not rs.EOF:rows.append([rs.Fields(i).Value for i in range(rs.Fields.Count)]);rs.MoveNext()
  finally:
   try:
    if rs:rs.Close()
   except:pass
   try:
    if conn:conn.Close()
   except:pass
   pythoncom.CoUninitialize()
 else:raise ValueError(f'未対応形式です: {fmt}')
 headers=['' if x is None else str(x) for x in headers][:200];rows=[['' if v is None else str(v) for v in list(row)[:len(headers)]] for row in rows]
 return fmt,headers,rows,total

@app.get('/api/data-viewer/jobs')
def data_viewer_jobs():
 c=load();items=[]
 for job in c['jobs']:
  path=_viewer_output_path(job,c);items.append({'id':job['id'],'name':job['name'],'format':normalize_output_format(job.get('output_format'),path.name),'exists':path.is_file()})
 return jsonify(items=items)

@app.get('/api/data-viewer/<job_id>')
def data_viewer(job_id):
 c=load();job=next((x for x in c['jobs'] if x['id']==job_id),None)
 if not job:return jsonify(ok=False,error='対象が見つかりません'),404
 path=_viewer_output_path(job,c)
 if not path.is_file():return jsonify(ok=False,error=f'出力ファイルが見つかりません: {path}'),404
 try:
  fmt,headers,rows,total=read_preview_data(path,job,limit=100000);return jsonify(ok=True,name=job['name'],format=fmt,path=str(path),modified=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds'),headers=headers,rows=rows,total_rows=total,preview_limit=100000,truncated=total is not None and total>len(rows))
 except Exception as e:log.exception('DATA_VIEWER_FAILED job=%s path=%s',job.get('name'),path);return jsonify(ok=False,error=str(e)),200

@app.post('/api/validate')
def validate():
 c=load();checks=[]
 def add(group,label,ok,detail,level=None,**extra):
  checks.append({'group':group,'label':label,'ok':bool(ok),'level':level or ('ok' if ok else 'error'),'detail':str(detail),**extra})
 engine=str(c.get('settings',{}).get('extract_engine') or 'api').lower()
 # 選択中の抽出方式に必要な構成だけを必須診断する。未使用方式の不足でNGにしない。
 if engine=='api':
  try:
   from navigator_api import candidate_dlls,pe_bits
   import struct
   pybits=struct.calcsize('P')*8
   dll_candidates=candidate_dlls(resolve_path(c.get('symnavi_exe','')),resolve_path(c.get('navigator_api_dll')) if c.get('navigator_api_dll') else None,[BASE/'Config'/'NAVIAP',BASE/'NAVIAP'])
   usable=[x for x in dll_candidates if x.is_file() and pe_bits(x)==pybits];selected=usable[0] if usable else None
   add('実行環境','Navigator API DLL',bool(selected),f'利用候補: {selected} / Python {pybits}bit' if selected else f'Python {pybits}bitで利用可能なDLLがありません',configured=c.get('navigator_api_dll',''),item='navigator_api_dll',candidates=[str(x) for x in dll_candidates if x.is_file()],needs_reselect=not bool(selected))
  except Exception as e:add('実行環境','Navigator API DLL',False,e,item='navigator_api_dll',candidates=[],needs_reselect=True)
 else:
  exe=resolve_path(c.get('symnavi_exe',''));add('実行環境','SymNavi.exe',exe.is_file(),exe,configured=c.get('symnavi_exe',''))
 # 共通接続ファイル。設定されているものだけを検査し、未設定の任意項目は警告にする。
 for label,key in [('symnavim.conf','symnavim_conf'),('symnavim.def','symnavim_def')]:
  raw=str(c.get(key) or '').strip();p=resolve_path(raw) if raw else None
  if raw:add('接続設定',label,bool(p and p.is_file()),p,configured=raw,item=key,candidates=find_nearby_file(label) if p and not p.is_file() else [],needs_reselect=bool(p and not p.is_file()))
  else:add('接続設定',label,True,'未設定（現在の処理方式で必須の場合のみ設定してください）',level='warning')
 # RNE基本フォルダーは補助設定。各ジョブの実ファイルが解決できればフォルダー不足をNGにしない。
 configured_root=resolve_path(c.get('rne_folder','.\\rne'))
 standard_roots=[configured_root,BASE/'Config'/'rne',BASE/'config'/'rne',BASE/'rne']
 existing_roots=[]
 for root in standard_roots:
  try:
   if root.is_dir() and str(root).lower() not in [str(x).lower() for x in existing_roots]:existing_roots.append(root)
  except OSError:pass
 job_results=[]
 for j in c.get('jobs',[]):
  rp=resolve_rne_path(j,c);exists=rp.is_file();job_results.append((j,rp,exists))
 all_jobs_ok=all(x[2] for x in job_results) if job_results else True
 root_ok=bool(existing_roots) or all_jobs_ok
 if existing_roots:root_detail='利用可能: '+' / '.join(str(x) for x in existing_roots)
 elif all_jobs_ok and job_results:root_detail='基本フォルダーは未検出ですが、登録済みRNEはすべて個別パスで解決できるため処理可能です。'
 elif not job_results:root_detail='対象未登録のため基本フォルダーは任意です。'
 else:root_detail=f'設定先がありません: {configured_root}。未解決RNEがあるため基本フォルダーまたは個別パスを修正してください。'
 add('RNE配置','RNE参照構成',root_ok,root_detail,level='ok' if root_ok else 'error',configured=c.get('rne_folder',''),item='rne_folder',needs_reselect=not root_ok)
 for j,rp,exists in job_results:
  candidates=find_nearby_file(j.get('rne') or rp.name) if not exists else []
  add('RNE配置',j.get('name','対象')+' RNE',exists,rp,configured=j.get('rne_path'),item='rne',job_id=j.get('id'),candidates=candidates,needs_reselect=not exists and not candidates)
  op=resolve_path(j.get('output_folder') or c.get('default_output_folder','.\\output'))
  add('出力先',j.get('name','対象')+' 出力先',op.is_dir(),op,item='')
 # 出力形式に応じて必要なテンプレートだけを検査。
 accdb_jobs=[j for j in c.get('jobs',[]) if normalize_output_format(j.get('output_format'),j.get('output_file'))=='accdb']
 if accdb_jobs:
  ap=resolve_path(c.get('accdb_template','.\\assets\\empty.accdb'));add('変換環境','ACCDB空テンプレート',ap.is_file(),ap,configured=c.get('accdb_template',''),item='accdb_template',needs_reselect=not ap.is_file())
 counts={'ok':sum(1 for x in checks if x['level']=='ok'),'warning':sum(1 for x in checks if x['level']=='warning'),'error':sum(1 for x in checks if x['level']=='error')}
 return jsonify(ok=counts['error']==0,checks=checks,counts=counts,engine=engine,summary=('実行可能です' if counts['error']==0 else '修正が必要な項目があります'),search_scope='設定値、標準配置 Config\\rne、個別RNEパスを統合して判定')

@app.get('/api/instance')
def instance_info():
 return jsonify(app=APP_ID,instance_id=INSTANCE_ID,display_name='SymfoNavi Data Hub',build_version=BUILD_VERSION,pid=os.getpid(),port=PORT,path=str(BASE))

@app.get('/api/version')
def version_info():
 return jsonify(version=APP_VERSION,build_version=BUILD_VERSION,title=APP_VERSION_TITLE,released_at=APP_RELEASED_AT,changelog=CHANGELOG)

@app.post('/api/heartbeat')
def heartbeat():
 global last_heartbeat_at,browser_closed_explicit,browser_closing_at,heartbeat_total
 data=request.get_json(silent=True) or {}; app_id=str(data.get('app_id') or ''); client_id=str(data.get('client_id') or request.headers.get('X-Heartbeat-Client') or '')[:80]
 if app_id!=APP_ID or not client_id:return jsonify(ok=False,error='アプリタブ識別情報が不正です'),400
 now=time.time()
 with heartbeat_lock:
  last_heartbeat_at=now;browser_closed_explicit=False;browser_closing_at=0.0;heartbeat_total+=1
  previous=heartbeat_clients.get(client_id,{})
  heartbeat_clients[client_id]={'app_id':APP_ID,'instance_id':INSTANCE_ID,'last_seen':now,'user_agent':request.headers.get('User-Agent','')[:160],'closing_at':0.0,'recovered_count':int(previous.get('recovered_count') or 0)+(1 if previous.get('closing_at') else 0)}
  stale=[k for k,v in heartbeat_clients.items() if v.get('closing_at') and now-v.get('closing_at',0)>86400]
  for k in stale:heartbeat_clients.pop(k,None)
 return jsonify(ok=True,app_id=APP_ID,instance_id=INSTANCE_ID,server_time=datetime.now().isoformat(timespec='milliseconds'),received_at=now,timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS,total=heartbeat_total)

@app.get('/api/heartbeat-status')
def heartbeat_status():
 now=time.time()
 with heartbeat_lock:
  age=max(0,now-last_heartbeat_at);clients=[{'client_id':k,'age_seconds':round(now-v['last_seen'],1),'closing':bool(v.get('closing_at'))} for k,v in heartbeat_clients.items()]
 return jsonify(ok=True,app_id=APP_ID,instance_id=INSTANCE_ID,state='healthy' if age<30 else ('delayed' if age<HEARTBEAT_TIMEOUT_SECONDS else 'disconnected'),last_received=datetime.fromtimestamp(last_heartbeat_at).isoformat(timespec='seconds'),age_seconds=round(age,1),timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS,active_clients=sum(1 for x in clients if not x['closing']),recent_clients=sum(1 for x in clients if not x['closing'] and x['age_seconds']<30),closing_clients=sum(1 for x in clients if x['closing']),clients=clients,total=heartbeat_total,server_time=datetime.now().isoformat(timespec='seconds'),auto_shutdown_on_disconnect=False,exit_when_app_tabs_empty=True,close_grace_seconds=CLOSE_GRACE_SECONDS)
@app.post('/api/browser-closing')
def browser_closing():
 # pagehideはタブ/ブラウザー終了だけでなく再読込等でも発生する。client_idごとに終了候補へ入れ、猶予中の復帰で取り消す。
 global browser_closed_explicit,browser_closing_at
 data=request.get_json(silent=True) or {};app_id=str(data.get('app_id') or '');client_id=str(data.get('client_id') or request.form.get('client_id') or request.headers.get('X-Heartbeat-Client') or '')[:80]
 if app_id!=APP_ID or not client_id:return jsonify(ok=False,error='アプリタブ識別情報が不正です'),400
 now=time.time()
 with heartbeat_lock:
  browser_closed_explicit=True;browser_closing_at=now
  previous=heartbeat_clients.get(client_id,{})
  heartbeat_clients[client_id]={'app_id':APP_ID,'instance_id':INSTANCE_ID,'last_seen':float(previous.get('last_seen') or now),'user_agent':request.headers.get('User-Agent','')[:160],'closing_at':now,'recovered_count':int(previous.get('recovered_count') or 0)}
 log.info('BROWSER_CLOSE_CANDIDATE client_id=%s grace=%ss',client_id,CLOSE_GRACE_SECONDS)
 return jsonify(ok=True,client_id=client_id,grace_seconds=CLOSE_GRACE_SECONDS)

@app.post('/api/shutdown-app')
def shutdown_app():
 def stop():
  time.sleep(.4); stop_event.set(); os._exit(0)
 threading.Thread(target=stop,daemon=True).start(); return jsonify(ok=True)

@atexit.register
def shutdown():stop_event.set()

# 起動計測用: Flaskが最初のHTTP要求を処理した時刻を1度だけ記録する。
# ランチャーのprobe()が最初に成功した=サーバー実質稼働開始のタイミングであり、
# 生成(spawn)からブラウザーに応答できるまでの総所要時間を可視化する。
_first_request_logged=False
@app.before_request
def _log_first_request():
 global _first_request_logged
 if _first_request_logged:return
 _first_request_logged=True
 try:spawn_at=float(os.environ.get('NAVI_APP_SPAWN_AT') or 0)
 except Exception:spawn_at=0
 ready_since_spawn=(time.time()-spawn_at) if spawn_at else -1
 log.info('APP_FIRST_REQUEST path=%s ready_since_spawn=%.2fs ready_since_import=%.2fs',request.path,ready_since_spawn,time.time()-_APP_IMPORT_DONE_AT)

if __name__=='__main__':
 if os.environ.get('NAVI_LAUNCHED_BY_GUARD')!='1':
  raise SystemExit('start.vbsから起動してください。app.pyの直接起動はサポートされていません。')
 # 生成(spawn)からモジュール取り込み完了までの所要時間。初回/アップデート時のBOX読込＋コンパイル費用の主因を可視化する。
 try:_spawn_at=float(os.environ.get('NAVI_APP_SPAWN_AT') or 0)
 except Exception:_spawn_at=0
 if _spawn_at:log.info('APP_IMPORT_ELAPSED spawn_to_import=%.2fs note=interpreter_init+module_import+source_compile(BOX)',_APP_IMPORT_DONE_AT-_spawn_at)
 startup_clock=time.perf_counter();log.info('APP_START source=%s local_root=%s pycache=%s',BASE,LOCAL_ROOT,os.environ.get('PYTHONPYCACHEPREFIX',''))
 _t=time.perf_counter()
 shutil.rmtree(LOCAL_ROOT/'work',ignore_errors=True)
 (LOCAL_ROOT/'work').mkdir(parents=True,exist_ok=True)
 log.info('APP_START_WORKCLEAN elapsed=%.2fs',time.perf_counter()-_t)
 _t=time.perf_counter();migrate_legacy_settings();log.info('APP_START_MIGRATION elapsed=%.2fs',time.perf_counter()-_t)
 _t=time.perf_counter();threading.Thread(target=scheduler,daemon=True,name='scheduler').start(); threading.Thread(target=command_dispatcher,daemon=True,name='command-dispatcher').start(); threading.Thread(target=heartbeat_watchdog,daemon=True,name='heartbeat-watchdog').start();log.info('APP_START_THREADS elapsed=%.2fs',time.perf_counter()-_t)
 log.info('APP_START_TOTAL boot_to_run=%.2fs total_since_spawn=%.2fs',time.perf_counter()-startup_clock,(time.time()-_spawn_at) if _spawn_at else -1)
 app.run(host=HOST,port=PORT,debug=False,threaded=True)
