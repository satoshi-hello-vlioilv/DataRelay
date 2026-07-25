NaviToSQLite Minimal
====================

起動:
  start.bat をダブルクリックしてください。
  VBS起動は使用しません。コマンドプロンプトはアプリ稼働中だけ表示されます。
  2回目のstart.batでは新規サーバーを起動せず、既存画面を開きます。

必要ファイル:
  start.bat / start_app.py / app.py / requirements.txt
  app_settings.sqlite3 / templates / static

公開ファイルの更新方式:
  1. SymfoNaviの中間XLSはローカル一時フォルダーへ作成
  2. SQLite3、TXT、CSV、XLSX、ACCDBもローカルで完成・検査
  3. 公開先へ .incoming の一時名でコピー
  4. 3秒以内で原子的な置換を実行
  5. 他PCで開かれていて置換不能なら待ち続けず、同じ公開先に
     ファイル名.pending_YYYYMMDD_HHMMSS.拡張子 として新しい正しいファイルを保存
  6. 次回実行時、公開先のロックが解除されていれば最新pendingを先に適用

重要:
  Windowsのファイルロック中は、既存ファイルを安全に強制上書きできません。
  強制終了や既存ファイルの先行削除は破損・欠落につながるため行いません。
  pendingが作成された場合、使用中のPCでファイルを閉じると次回実行時に自動反映されます。

Path UX update:
- ファイル存在確認と候補検索中はWAITINGモーダルを表示します。
- 対象設定、ルール設定、候補表示は閉じた時に編集データとフォーム内容を初期化します。
- ブラウザーの戻る/復元時も開いたdialogを閉じます。
- 各パス欄へ「絶対へ」「相対へ」を追加し、アプリフォルダー基準で自動変換します。
- 相対パスを参照する場合、バックエンドで実在する絶対位置へ解決し、そのフォルダーから参照画面を開きます。
- 参照後は元が相対パスなら、選択結果を自動的に相対パスへ戻します。

SymfoNavi非表示監視チューニング:
- 操作直後のみ: 定期監視なし。最も軽量。
- 軽量監視: 3秒間隔。
- バランス: 2秒間隔。初期値・推奨。
- 標準監視: 1秒間隔。設定可能な最短間隔。
- カスタム: 1～10秒の定期監視間隔と、操作直後の監視時間を設定可能。
- 0.18秒間隔の定期監視は廃止しました。

Compact Path UI:
- 個別設定モーダル内で重複していた「絶対」「相対」と「絶対へ」「相対へ」を整理しました。
- 各パス欄は「確認」「参照」と、下段の単一切替ボタンだけで操作します。
- 単一切替ボタンは現在状態に応じて「絶対 → 相対」または「相対 → 絶対」と表示します。
- 現在のパス種別はボタン横へ簡潔に表示します。

ACCDBテンプレート方式:
1. 空のACCDBを assets\empty.accdb に配置してください。
2. 別の場所なら、共通設定「ACCDB空テンプレート」で参照指定してください。
3. 出力時はテンプレートをローカル作業ファイルへコピーします。
4. Microsoft.ACE.OLEDB.16.0、次に12.0の順で接続を試します。
5. 設定テーブルと同名のテーブルだけを作り直し、データ登録・件数検査後に公開します。
6. ADOX.Catalog.Createは使用しません。

FlowFix:
- RNE Open、XLS Save、RNE Close後のウィンドウ非表示処理をバックグラウンド化しました。
- ウィンドウ列挙やWMI確認が遅くても、DDE抽出フローは停止しません。
- DDE Open/Save/Closeの開始・5秒ごとの待機・完了・所要時間をログへ記録します。
- DDE応答待ちの間も進捗モーダルの活動内容と経過秒数を更新します。

Performance redesign:
- ACCDB/SQLite等の変換ファイルはBox配下ではなくLOCALAPPDATAのローカル作業領域で作成し、完成後だけ公開先へコピーします。
- ACCDB登録は、1セルずつCOM代入する方式を廃止し、1行を1回のAddNewで登録して500行単位でUpdateBatchします。
- 定期非表示監視が有効な場合、Open/Save/Close直後の重複ウィンドウ監視を実行しません。
- WMIによる子プロセス再確認は最短30秒間隔へ低減しました。
- SymfoNavi SaveがExec failedを返しても中間XLSが既に生成済みなら、重複Saveを行わず安定確認へ進みます。
- ACCDBの接続、テーブル作成、500行ごとの登録、全登録の所要時間をログへ記録します。

ACCDB data optimization:
- 非表示処理は変更していません。
- ACCDBへの主登録方式をRecordset AddNewから、CSV + schema.ini + ACE Text Driverの一括INSERTへ変更しました。
- 全列をLongCharとしてschema.iniへ定義し、型推測による欠損を防ぎます。
- 一括取込に失敗した環境では、従来のRecordset方式へ自動フォールバックします。
- CSV作成時間、一括取込時間、フォールバック有無、件数検査結果をログへ記録します。

Integrated fix:
- __pycache__、*.pyc、*.pyoは配布ZIPから除外しました。
- DDE Openがタイムアウトしても同じRNEを再Openせず、確認ダイアログの発生を防止します。
- 初期進捗モーダルは実行対象の保存済み形式・ファイル名・出力先をステータスから表示します。
- ログを実行指令単位、対象ファイル単位の2階層アコーディオンで表示します。
- 安全・待機設定をレスポンシブグリッド化し、カード内に収めます。
- ACCDB一括取込は非表示Access.ApplicationのTransferTextを第一方式、ACE Text SQLを第二方式、Recordsetを最終方式とします。

Navigator API main engine:
- 既定の抽出エンジンをNavigator APIへ変更しました。
- DDE互換方式は共通設定から選択可能なまま残しています。
- API方式は SymNaviA.dll をctypesで直接呼び、NaviOpenSession -> NaviOpenCatalog -> NaviExecuteCatalog -> NaviSaveData -> NaviCloseCatalog -> NaviCloseSession の順に処理します。
- API診断はDLL検出、Python bit数、ロード可否を表示します。bit数不一致やDLL未検出時はAPI実行前に明示的に失敗します。
- API方式からDDE方式への実行途中の自動フォールバックは行いません。重複問い合わせ防止のため、切替は設定で明示します。

API DLL auto detection:
- 4候補を自動検出: debugdllVC14x64, dllVC14x64, debugdllVC14, dllVC14。
- PEヘッダーからDLLの32/64bitを事前判定し、現在のPythonと一致する候補を優先します。
- 64bit Pythonの既定値は C:\NAVIAP\debugdllVC14x64\SymNaviA.dll です。
- API診断にDLL bit数、Python bit数、候補ごとの存在・ロード結果を追加しました。

WAITING / progress engine-aware display:
- WAITING画面に処理方式、処理内容、リアルタイム経過時間を追加しました。
- API診断は「NAVIGATOR API / DLL候補・ビット数・依存関係を確認」と表示します。
- API実行開始時は「APIセッションと実行対象を準備」と表示します。
- 進捗工程名をAPIとDDEで動的に切り替えます。
- API時はAPI初期化、APIセッション接続、RNE読込み、問い合わせ実行、API結果保存・検証、カタログ解放を表示します。
- DDE時は従来のSymfoNavi起動、DDE接続、RNE Open、XLS生成、画面Closeを表示します。


API RNE open correction (2026-07-25):
- NaviOpenCatalogへRNEの元配置を維持した正規化済み絶対パスを渡します。
- API用RNEの単体ローカルコピーを廃止し、RNE内部の相対参照や同一フォルダーの関連定義が切れる問題を防ぎます。
- API呼出し時のカレントフォルダーも元RNEフォルダーへ合わせます。
- 元RNEを一時ファイルとして削除しないよう、後片付け対象をXLSと変換ファイルだけに限定しました。
- API読込ログへcatalog_full、catalog_name、size、mtime_ns、strategy=original_fullpathを記録します。


Official API sample aligned revision (2026-07-25):
- NaviOpenSession後にNaviIsSessionOpenedを確認します。
- 公式VBA/VB.NETサンプルと同じ順で、明示設定された追加データソースへ接続してからNaviOpenCatalogを実行します。
- NaviGetErrorMessageを先に取得し、Navigator Serverの詳細メッセージをログへ記録します。メッセージがない場合もNaviGetErrorCodeを併記します。
- XLS中間保存の繰返し指定を公式Excel VBAサンプルと同じNAVI_NONREPEATへ変更しました。
- 同じ条件での自動再試行は行いません。

追加データソース接続の設定:
通常のNavigatorログインだけでRNEを開ける場合、追加設定は不要です。
symnavim.confへ以下のうち必要なセクションだけを追加してください。

[ApiRDA]
enabled=yes
user=ユーザー名
password=パスワード
server=サーバ名

[ApiOracle]
enabled=yes
user=ユーザー名
password=パスワード

[ApiSQLServer]
enabled=yes
user=ユーザー名
password=パスワード

[ApiPostgres]
enabled=yes
user=ユーザー名
password=パスワード
option=

[ApiResource]
enabled=yes
resource=リソース名
resource_kind=0
user=ユーザー名
password=パスワード
option=

[ApiResourceNoAuth]
enabled=yes

注意:
- 使用していない接続セクションは追加しないでください。
- パスワードは既存のsymnavim.confと同じ管理・アクセス権で保護してください。
- エラー時はログのserver_message_rcとserver_messageを確認してください。

