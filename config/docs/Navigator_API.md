# Navigator API リファレンス（Claude Code 用）

> **対象 DLL**: `SymNaviA`（すべての関数はこの DLL からエクスポートされる）
> **API バージョン**: Navigator Visual Basic Interface API 9.6.0（宣言ファイル基準）
> **原本製品**: FUJITSU Interstage Navigator Server V9.4.1
> **配布パッケージ**: Interstage Navigator API 9.6.0（ProductVersion 9.6.0 / 資料コード B5141JC-V-09601 / 既定インストール先 `C:\NAVIAP`）（§10）
> **改訂履歴**:
> - v2: `C:\NAVIAP\Samples` とインストール前 API フォルダのスキャン結果を反映。同梱 `SymNaviF.exe`（x86/x64）の .NET メタデータと IL を解析。
> - v3: `NAVIAP.cab` 全展開後の原本（`NaviAPI.vb`, `SymNaviApi.bas`, `naviapidef.h`, `symnaviapi.h`, `kvrctypes.h` ほか、サンプル全文、README 全文）と
>   `SymNaviA.dll` 4 種（x86/x64 × リリース/デバッグ）のエクスポート表・インポート表・機械語を解析。
>   v2 で `[解析]`/`[要確認]` だった項目のうち、原本または DLL 実装で確定したものを更新した。
> **本書の用途**: 既存の Excel/VBA・VB.NET 資産を Python 等へ移植する際に、Claude Code が
> 関数シグネチャ・定数・呼び出し順序を機械的に参照するための一次リファレンス。

---

## 0. AI エージェント向けの読み方（重要）

この文書は「そのままコード生成の根拠にしてよい情報」と「実機確認が必要な情報」を
明確に分けている。**推測でシグネチャを補完しないこと。**

| タグ | 意味 | コード生成での扱い |
|------|------|--------------------|
| `[原本]` | 富士通の宣言ファイル・ガイド・サンプルに明記 | そのまま利用可 |
| `[整理]` | 原本を今回の用途に合わせて組み立てた方針 | 実装方針として利用可。ただし断定しない |
| `[解析]` | 富士通配布物のバイナリ（`SymNaviA.dll` の機械語・エクスポート/インポート表、`SymNaviF.exe` の .NET メタデータ/IL）から機械的に読み取った事実 | 利用可。公式文書の記述ではないため、初回実機テストで挙動を確認する |
| `[要確認]` | 添付原本だけでは確定できない | **コードに埋め込む前に実機で検証** |

- 整数型は VB.NET が `Integer`、VBA が `Long`。どちらも **32bit 符号付き整数**。Python では `ctypes.c_int32` を明示的に使う。`[整理]`
- 文字列は **Shift-JIS（CP932）のみ**。Unicode インタフェースは無い（README「利用できる文字コード」、`SymNaviA.dll` に W 版関数なし）。`[原本][解析]`
- 入力文字列は `char*`、出力文字列（`ByRef ... As String`）は **ANSI 内容の `BSTR*`**。DLL が `SysFreeString`→`SysAllocStringByteLen` で書き込む（§2.1）。`[解析]`
- ハンドル（`hCatalog` / `hCPoint` / `hDItem`）は **x64 版でも 32bit 整数**。`[解析]`
- x86 版の呼び出し規約は **stdcall**、関数名は**装飾なし**（`NaviOpenSession` のまま）。`[解析]`
- Navigator API で開発したアプリは **マルチスレッド非対応**。`[原本]`

---

## 1. 処理フロー（標準シーケンス）

`[原本]` プログラマーズガイド記載の基本順序。

```
1. NaviOpenSession                 # サーバへログオン
2. （必要時）データソース接続       # NaviConnectOracle / SQLServer / RDA / Resource*
3. NaviOpenCatalog                 # 問い合わせ(RNE)ファイルをメモリへ読み込み
4. 問い合わせ内容の一時変更          # 管理ポイント/データ項目の変更・除外
5. NaviExecuteCatalog              # 実行＋ダウンロード
6. 結果取得                        # NaviGetRecordData / NaviSaveData など
7. NaviCloseCatalog                # カタログ解放
8. NaviCloseSession                # ログオフ
```

- 手順4の変更は**一時的**で、RNE ファイル自体には反映されない。`[原本]`
- 実行後に管理ポイント／データ項目を変更する場合は、先に `NaviInvalidateExecution` を呼ぶ。`[原本]`

### データ項目 列挙・除外パターン `[整理]`
```
NaviOpenSession
  → NaviOpenCatalog
  → NaviGetDataItemNumber(locate=NAVI_DATA)
  → NaviGetDataItem2(locate=NAVI_DATA, index)
  → NaviGetNameDI(hDItem)          # 見出し取得
  → NaviRemoveDataItem(hDItem)     # 不要項目のみ削除（条件フィールドは除外しない）
  → NaviExecuteCatalog
  → NaviSaveData
  → NaviCloseCatalog → NaviCloseSession
```

### 項目探索パターン（名前指定・サンプル実証済み）`[原本]`
`ExecNavi.bas` の `SearchItem` が示す、名前から項目ハンドルを得る実際の探索順序。
インデックス列挙ではなく **名前指定** で取得している点に注意。
```
NaviGetControlPoint(hCatalog, rc, 名前, NAVI_SIDE, 0)  # 表側の管理ポイント
  → 失敗なら NAVI_HEAD                                  # 表頭
  → 失敗なら NAVI_COND                                  # 条件の管理ポイント
  → 失敗なら NaviGetDataItem(hCatalog, rc, NAVI_COND, 名前, 0, reserve)  # 条件のデータ項目
  → 失敗なら NaviGetDataItem(hCatalog, rc, NAVI_DATA, 名前, 0, reserve)  # 表示データ項目（NaviAPISample2.vb）
  → すべて失敗なら PutNaviMessage（エラー表示）
```
- 管理ポイントが「年度／半期／四半期／月度／日」の場合は**時間型**として扱い、条件変更に `NaviChangePeriod` を使う（サンプルの分類ロジック）。`[原本]`
- `NaviAPISample2.vb` の `SearchItem` は見つかった項目を次の 3 種に分類し、処理関数を振り分ける。`[原本]`

| 種別 | 判定 | 呼び出す処理 |
|------|------|-------------|
| 1: 管理ポイント | `NaviGetControlPoint` が成功し、名前が時間型以外 | `ChangeCategory`（§3.5） |
| 2: 時間型管理ポイント | 名前が 年度/半期/四半期/月度/日 | `ChangePeriod`（§3.5, §4.11） |
| 3: データ項目 | `NaviGetDataItem` が成功（`NAVI_COND` または `NAVI_DATA`） | `ChangeConditionDI`（§3.6） |

- `NAVI_DATA`（表示データ項目）で見つかった項目に許される操作は `RM`（削除）のみ。それ以外は「条件に指定したデータ項目にのみ使用できます」エラー。`[原本]`

### バッチ実行の全体シーケンス（`NaviAPISample2.vb` / `SymNaviF.exe`）`[原本]`
同梱のバッチ実行サンプルが実際に行っている順序。移植時の最小参照実装として使える。
```
NaviOpenSession(rc, user, password, server)          # [Main] Login=user/password@server
 → （定義があれば）NaviConnectRDA / NaviConnectOracle / NaviConnectSQLServer
 → （POSTGRES 定義があれば）NaviConnectBaseDBMS(rc, NAVI_DBMS_ANYDB, user, password, "")
 → カタログごとに:
     NaviOpenCatalog(rc, path)
     → （CurrentMonth 指定時）NaviChangeCurrentMonth(hCatalog, rc, "YYYYMM")
     → Param1, Param2, ... を空になるまで順に処理（SearchItem → 種別ごとの変更関数）
     → NaviExecuteCatalog(hCatalog, rc, number, NAVI_DOWNLOADNOW, reserve)
     → NaviSaveData(hCatalog, rc, file, ftype, repeat)
     → NaviCloseCatalog(hCatalog); hCatalog = 0
 → 終了時: If NaviIsSessionOpened() = NAVI_OPENED Then (未クローズのカタログを閉じて) NaviCloseSession
```
- いずれかの API で `rc <> 0` になった時点で、そのカタログの処理を打ち切ってエラーを記録し（`PutNaviMessage`）、開いていたカタログを閉じて次のカタログへ進む。

---

## 2. 型対応表

| 概念 | VB.NET | VBA(PtrSafe) | Python ctypes |
|------|--------|--------------|----------------|
| 返却/件数/インデックス/ハンドル | `Integer` | `Long` | `c_int32` `[整理]` |
| 上記の参照渡し（ByRef） | `ByRef ... As Integer` | `... As Long` | `POINTER(c_int32)` `[整理]` |
| 入力文字列 | `ByVal ... As String` | `ByVal ... As String` | `c_char_p`（CP932 の NUL 終端バイト列）`[解析]` |
| 出力文字列 | `ByRef ... As String` | `... As String` | `POINTER(c_void_p)`（ANSI 内容の `BSTR*`）`[解析]` |

> Windows の `ctypes.c_long` も通常 32bit なので幅は一致するが、本書では 32bit を明示するため
> `c_int32` を推奨する。`c_long` が誤りという意味ではない。`[整理]`
> C 側の固定長整数型 `KVR_L32` は Windows x86/x64 とも `int`（4 バイト）と定義されている（`kvrctypes.h`）。`[原本]`

### 2.1 文字列の受け渡し方式 `[解析]`

2 つの独立した証拠から確定した。

**(a) 呼び出し側**: 同梱 `SymNaviF.exe`（`NaviAPISample2.vb` のビルド結果）に記録された P/Invoke 定義

| 項目 | 実際の定義 | DLL 側から見た型 |
|------|-----------|------------------|
| 呼び出し規約 | `CallConvWinapi`、`NoMangle`（A/W 接尾辞の自動付与なし） | x86 では stdcall |
| 文字セット | `CharSet.Ansi`（全 53 関数） | ANSI（CP932） |
| 入力文字列（宣言上 `ByVal As String`） | `ByRef String` + `MarshalAs(VBByRefStr)` | `char*`（NUL 終端の ANSI バッファ） |
| 出力文字列（宣言上 `ByRef As String`） | `ByRef String` + `MarshalAs(AnsiBStr)` | `BSTR*`（中身は ANSI バイト列） |
| 整数・ハンドル | `Integer`（x64 版でも `i4`） | 32bit 整数 |

**(b) 受け取り側**: `SymNaviA.dll` の実装
- インポートしている OLE 関数は `OLEAUT32` の序数 6（`SysFreeString`）と 150（`SysAllocStringByteLen`）の 2 つだけ。
- 出力文字列を返す箇所は、どれも次の処理になっている（x64 リリース版の機械語で確認）。
  ```
  if (*pOut != NULL) SysFreeString(*pOut);                       // 既存の BSTR を解放
  *pOut = SysAllocStringByteLen(cstrA.GetBuffer(), cstrA.GetLength());  // ANSI バイト列をそのまま BSTR 化
  ```
- したがって
  - 渡す `BSTR*` の中身は **NULL か、有効な BSTR** でなければならない（未初期化のごみ値は不可）。
  - 返った BSTR の長さは `SysStringByteLen` で得られる**バイト数**で、終端 NUL は含まない。CP932 でデコードする。
  - 返った BSTR は**呼び出し側が `SysFreeString` で解放**する（.NET の `AnsiBStr` 変換と同じ扱い）。同じ変数を再利用して次の呼び出しに渡せば、DLL 側が前の値を解放する。
- 入力文字列が `VBByRefStr` になるのは VB コンパイラの仕様（VB6 互換）であり、DLL に渡るのは `char*` 1 個。
- 本書 §3 の VB.NET 宣言と `SymNaviF.exe`・`SymNaviA.dll` のエクスポートは、53 関数すべての関数名が一致し、引数名・引数順も `SymNaviF.exe` と一致している。
- x86 リリース版の各関数の戻り命令（`ret N`）は、53 関数中 51 関数で「引数の数 × 4 バイト」と一致した（残り 2 関数は自動判定できなかっただけで、不一致ではない）。全引数が 4 バイト（`int` / `int*` / `char*` / `BSTR*`）であることと整合する。

---

## 3. 関数リファレンス

各関数は `[VB.NET]` / `[VBA]` / `[ctypes(参考)]` の順に宣言を示す。
`ctypes` 欄は原本の Integer/Long, ByVal/ByRef から対応付けた参考実装であり、富士通公式指定ではない。文字列の 2 行は DLL 実装で裏付け済み（§2.1）。`[整理/解析]`

### 3.1 エラー情報取得関数

#### NaviGetErrorMessage — エラーメッセージ取得
```vbnet
' [VB.NET]
Declare Sub NaviGetErrorMessage Lib "SymNaviA" (ByRef rc As Integer, ByRef errMessage As String)
' [VBA]
Declare PtrSafe Sub NaviGetErrorMessage Lib "SymNaviA" (rc As Long, errMessage As String)
```
- `rc` (out): `NAVI_OK` / `NAVI_ERROR` / `NAVI_NOMSG`
- `errMessage` (out): サーバまたは API が出力したメッセージ
- 呼び出しパターン: `rc=NAVI_NOMSG`（サーバ発メッセージ無し）のとき `NaviGetErrorCode` へフォールバックし、詳細コードからメッセージを組み立てる（`ExecNavi.bas` の `PutNaviMessage`）。`[原本]`

#### NaviGetErrorCode — エラー詳細コード取得
```vbnet
' [VB.NET]
Declare Sub NaviGetErrorCode Lib "SymNaviA" (ByRef rcode As Integer)
' [VBA]
Declare PtrSafe Sub NaviGetErrorCode Lib "SymNaviA" (rcode As Long)
```
- `rc` に `NAVI_ERROR` が返った後、詳細を得るために呼ぶ。

---

### 3.2 セッション操作関数

#### NaviOpenSession — ログオン
```vbnet
' [VB.NET]
Declare Sub NaviOpenSession Lib "SymNaviA" (ByRef rc As Integer, ByVal user As String, ByVal password As String, ByVal server As String)
' [VBA]
Declare PtrSafe Sub NaviOpenSession Lib "SymNaviA" (rc As Long, ByVal user As String, ByVal password As String, ByVal server As String)
```
- `server` (in): ホスト名 / FQDN / IP アドレス。`[原本]`
- 主な詳細コード: `NAVI_ERROR_SYMFOWARE`, `NAVI_ERROR_ORACLE`, `NAVI_ERROR_SERVERENV`, `NAVI_ERROR_LOGON`, `NAVI_ERROR_RECONNECT`

#### NaviOpenSessionWithApinfo — アプリ情報付きログオン
```vbnet
Declare Sub NaviOpenSessionWithApinfo Lib "SymNaviA" (ByRef rc As Integer, ByVal user As String, ByVal password As String, ByVal server As String, ByVal apinfo As String)
```

#### NaviCloseSession — ログオフ
```vbnet
Declare Sub NaviCloseSession Lib "SymNaviA" ()
```
- セッション未オープン時は何もしない。`[原本]`

#### NaviIsSessionOpened — 接続確認
```vbnet
' [VB.NET]
Declare Function NaviIsSessionOpened Lib "SymNaviA" () As Integer
' [VBA]
Declare PtrSafe Function NaviIsSessionOpened Lib "SymNaviA" () As Long
```
- 返り値: `NAVI_OPENED` / `NAVI_NOTOPENED`
- クローズ前の確認に使う（`If NaviIsSessionOpened() = NAVI_OPENED Then ... NaviCloseSession`）。`[原本]`

---

### 3.3 データソース接続関数

```vbnet
Declare Sub NaviConnectOracle    Lib "SymNaviA" (ByRef rc As Integer, ByVal user As String, ByVal password As String)
Declare Sub NaviConnectSQLServer Lib "SymNaviA" (ByRef rc As Integer, ByVal user As String, ByVal password As String)
Declare Sub NaviConnectRDA       Lib "SymNaviA" (ByRef rc As Integer, ByVal user As String, ByVal password As String, ByVal server As String)
Declare Sub NaviConnectBaseDBMS  Lib "SymNaviA" (ByRef rc As Integer, ByVal dbkind As Integer, ByVal user As String, ByVal password As String, ByVal opt As String)
Declare Sub NaviConnectResource  Lib "SymNaviA" (ByRef rc As Integer, ByVal resourcename As String, ByVal resourcekind As Integer, ByVal username As String, ByVal password As String, ByVal opt As String)
Declare Sub NaviConnectResourceNoAuth Lib "SymNaviA" (ByRef rc As Integer)   ' CSV/Shunsaku/Openインタフェース（認証不要）
```
- Symfoware Server はログオン時に自動接続されるため接続操作は不要。他サイト Symfoware は `NaviConnectRDA` が必要。`[原本]`
- `resourcekind` には `NAVI_DBMS_*` を指定。`opt` は将来拡張用で空文字必須。`[原本]`
- **PostgreSQL 系の接続**: `NaviAPISample2.vb` は定義キー `POSTGRES` が指定された場合に
  `NaviConnectBaseDBMS(rc, NAVI_DBMS_ANYDB, uid, pswd, "")` を呼ぶ。同梱のサンプル DB 構築スクリプトも PostgreSQL 用（§9.2）。`[原本]`
  - C 側ヘッダには `NAVI_DBMS_POSTGRESQL = 0x0007` もあるが、VB 宣言には無く、サンプルも使っていない。VB 系の移植では `NAVI_DBMS_ANYDB` を使う。`[原本]`
- `NaviConnectOracle` / `NaviConnectSQLServer` には `user/password` のみ、`NaviConnectRDA` には `server` も渡す。`[原本]`

---

### 3.4 カタログ（問い合わせファイル）操作関数

#### NaviOpenCatalog — RNE 読み込み
```vbnet
' [VB.NET]
Declare Function NaviOpenCatalog Lib "SymNaviA" (ByRef rc As Integer, ByVal path As String) As Integer
' [VBA]
Declare PtrSafe Function NaviOpenCatalog Lib "SymNaviA" (rc As Long, ByVal path As String) As Long
```
- 返り値: カタログハンドル。前提: 事前に `NaviOpenSession`。
- 主な詳細コード: `NAVI_ERROR_OPEN`, `NAVI_ERROR_SESSION`, `NAVI_ERROR_ITEM`

#### NaviCloseCatalog — カタログ解放
```vbnet
Declare Sub NaviCloseCatalog Lib "SymNaviA" (ByVal hCatalog As Integer)
```
- 不正ハンドル使用時は予期しない動作。ハンドルは 0 を「未取得」の番兵として扱う運用が一般的（`ExecNavi.bas`）。`[原本]`

#### NaviGetCatalogInfo — カタログ情報取得
```vbnet
Declare Sub NaviGetCatalogInfo Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByRef title As String, ByRef colsize As Integer, ByRef rowsize As Integer, ByRef creator As String, ByRef updatetime As String, ByRef server As String, ByRef timespan As Integer)
```
- `updatetime`: `YYYYMMDDHHmmss` 文字列。`colsize`/`rowsize` は現時点で何も返らない。`[原本]`

#### NaviExecuteCatalog — 実行
```vbnet
Declare Sub NaviExecuteCatalog Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByRef number As Integer, ByVal download As Integer, ByVal reserve As Integer)
```
- `number` (out): 集計/明細表のレコード行数（明細データは 0）。
- `download` (in): `NAVI_DOWNLOADNOW` / `NAVI_DOWNLOADLATER`。`reserve` は 0 固定。
- サンプルの呼び出し: `NaviExecuteCatalog(hCatalog, rc, number, NAVI_DOWNLOADNOW, reserve)`（`reserve` は 0）。`[原本]`

#### NaviSaveData — 結果保存
```vbnet
Declare Sub NaviSaveData Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal file As String, ByVal ftype As Integer, ByVal repeat As Integer)
```
- `ftype`: `NAVI_XLSX` 等（§4.5）。空白抑制・表題/脚注・マルチクロス結合は `Or` で組み合わせる。`[原本]`
- `repeat`: `NAVI_*_REPEAT` / `NAVI_NONREPEAT` / `NAVI_NOCHANGE`。
- サンプルでは一時 XLS へ保存 → 開いて印刷 → ブック集約、という後処理を行っている（`NAVI_XLS, NAVI_NONREPEAT`）。`[原本]`

#### NaviSaveCatalog — カタログ保存（列分割用途では呼ばない）`[整理]`
```vbnet
Declare Sub NaviSaveCatalog Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal path As String)
```

#### その他カタログ関数
```vbnet
Declare Sub NaviInvalidateExecution Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer)
Declare Sub NaviDownLoadData        Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal max As Integer, ByRef result As Integer)
Declare Sub NaviTerminateDL         Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer)
Declare Sub NaviGetFieldNumber      Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByRef number As Integer)
Declare Sub NaviGetRecordNumber     Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByRef number As Integer)
Declare Sub NaviGetRecordData       Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal number As Integer, ByVal reserve As Integer, ByRef record As String)
Declare Sub NaviChangeCurrentMonth  Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal cmonth As String)
Declare Sub NaviGetDocPageNumber    Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByRef number As Integer)
Declare Sub NaviGetActiveDocPage    Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByRef page As Integer)
Declare Sub NaviSetActiveDocPage    Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal page As Integer)
Declare Sub NaviChangePeriodKind    Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal kind As Integer)
```
- `NaviGetRecordData` の `number` は「1行目を 0」として指定。返却はタブ区切りテキスト。`[原本]`
- `NaviChangeCurrentMonth` の `cmonth` は `YYYYMM`（"199701"〜"203801"）。`[原本]`

---

### 3.5 管理ポイント操作関数

```vbnet
Declare Function NaviGetControlPoint Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal label As String, ByVal locate As Integer, ByVal order As Integer) As Integer
Declare Function NaviGetControlPointForTimeSpan Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer) As Integer
Declare Sub NaviRemoveControlPoint  Lib "SymNaviA" (ByVal hCatalog As Integer, ByVal hCPoint As Integer, ByRef rc As Integer)
Declare Sub NaviGetCategoryNumber   Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal locate As Integer, ByRef number As Integer)
Declare Sub NaviGetCategory         Lib "SymNaviA" (ByVal pCPoint As Integer, ByRef rc As Integer, ByVal locate As Integer, ByVal order As Integer, ByVal master As Integer, ByVal separator As String, ByRef category As String)
Declare Sub NaviReloadCategory      Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal master As Integer, ByVal key As String, ByVal search As Integer, ByVal nonmatch As Integer, ByVal separator As String)
Declare Sub NaviChangeCategory      Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal category As String, ByVal master As Integer, ByVal disp As Integer, ByVal order As Integer, ByVal separator As String)
Declare Sub NaviChangeConditionCP   Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal category As String, ByVal master As Integer, ByVal target As Integer)
Declare Sub NaviChangePeriod        Lib "SymNaviA" (ByVal hTCPoint As Integer, ByRef rc As Integer, ByVal condition As Integer, ByVal fromTime As String, ByVal toTime As String, ByVal beginning As String)
Declare Sub NaviSetBaseDateCP       Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal basedate As String)
Declare Sub NaviGetControlPointNumber Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal locate As Integer, ByRef number As Integer)
Declare Function NaviGetControlPoint2 Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal locate As Integer, ByVal index As Integer) As Integer
Declare Sub NaviGetNameCP           Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal master As Integer, ByRef name As String)
Declare Sub NaviGetControlPointType Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByRef control_type As Integer)
Declare Sub NaviGetMasterKind       Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal locate As Integer, ByVal index As Integer, ByRef kind As Integer)
Declare Sub NaviGetPeriod           Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal locate As Integer, ByRef conditon As Integer, ByRef fromTime As String, ByRef toTime As String, ByRef reserve As String)
```
- `NaviGetControlPoint` の `locate`: `NAVI_ALL`（表側→表頭→条件の順）/ `NAVI_SIDE` / `NAVI_HEAD` / `NAVI_COND`。`order` は同名時に「1個目を 0」。`[原本]`（`ExecNavi.bas` でも `order=0` で先頭取得を実証）
- `NaviChangePeriod` の `fromTime`/`toTime` は `YYYYMMDD`（"18000101"〜"21001231"）。月指定時 DD は "00"。`[原本]`
- **`NaviChangePeriod` の第3引数 `condition`** には期間種別定数を渡す。`ExecNavi.bas` では
  日付末尾が "00"（＝月指定）なら `NAVI_MONTH`、それ以外（＝年月日指定）なら `NAVI_YMD` を渡している。`[原本]`（→ §4.11）
- カテゴリの一括非表示→個別表示は 0 始まりループで行う（`For i=0 To number-1` → `NaviChangeCategory(..., i, ...)`）。`[原本]`
- **カテゴリ操作の実際の引数**（`NaviAPISample2.vb` の `ChangeCategory`。演算子は `IN` と `RM` のみ受け付ける）`[原本]`
  ```
  RM  → NaviRemoveControlPoint(hCatalog, hCPoint, rc)
  IN  → NaviGetCategoryNumber(hCPoint, rc, NAVI_IN_DISP, number)
        If ReloadCategory<>"NO" Or number=0 Then
            NaviReloadCategory(hCPoint, rc, NAVI_LABEL, "", NAVI_ALL, NAVI_MATCH, "")
            NaviGetCategoryNumber(hCPoint, rc, NAVI_IN_DISP, number)
        For i = 0 To number-1                                            ' 全カテゴリを非表示
            NaviGetCategory(hCPoint, rc, NAVI_IN_DISP, 0, NAVI_LABEL, "", category)
            NaviChangeCategory(hCPoint, rc, category, NAVI_LABEL, NAVI_IN_NONDISP, i, "")
        For k = 0 To 指定値数-1                                          ' 指定値だけ表示
            NaviChangeCategory(hCPoint, rc, 値k, NAVI_LABEL, NAVI_IN_DISP, k, "")
  ```
  - `NaviReloadCategory` の `search` は `NAVI_ALL`(0x1C)、`nonmatch` は `NAVI_MATCH`(1)（v2 で要確認としていた定数名が原本で確定）。
    `frmMain.vb` は同じ呼び出しで `nonmatch=0` を渡している（`NaviGetCategoryNumber` が 0 件のときだけ再読込）。
  - `NaviGetCategoryNumber` / `NaviGetCategory` の `locate` には `NAVI_IN_DISP`（表示中のカテゴリ）を渡す。
  - 単純な列挙は `frmMain.vb` の形が分かりやすい: `For i = 0 To n-1: NaviGetCategory(hCPoint, rc, NAVI_IN_DISP, i, NAVI_LABEL, "", category)`。
  - `NaviAPISample2.vb` の非表示ループは `NaviGetCategory` の `order` を常に 0 にしている。1 件ずつ非表示にすると表示中リストの先頭が繰り上がるため、と読めるが原本に説明は無い。移植時はこの形をそのまま再現する。`[整理]`
- **時間型（`ChangePeriod`）の扱い** `[原本]`
  - 演算子は `IN`（1 値。`fromTime = toTime = 値`）と `BETWEEN`（2 値）のみ。`RM` は `NaviRemoveControlPoint`。
  - `condition` は `fromTime` の末尾 2 桁が `"00"` なら `NAVI_MONTH`(0)、それ以外は `NAVI_YMD`(1)。`beginning` は `""`。

---

### 3.6 データ項目操作関数

```vbnet
Declare Function NaviGetDataItem  Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal locate As Integer, ByVal label As String, ByVal order As Integer, ByVal reserve As Integer) As Integer
Declare Sub NaviRemoveDataItem    Lib "SymNaviA" (ByVal hCatalog As Integer, ByVal hDItem As Integer, ByRef rc As Integer)
Declare Sub NaviChangeConditionDI Lib "SymNaviA" (ByVal hDItem As Integer, ByRef rc As Integer, ByVal condition As Integer, ByVal key As String, ByVal search As Integer, ByVal nonmatch As Integer, ByVal range As Integer, ByVal lcheck As Integer, ByVal lvalue As String, ByVal rcheck As Integer, ByVal rvalue As String, ByVal reserve As String)
Declare Sub NaviSetBaseDateDI     Lib "SymNaviA" (ByVal hCPoint As Integer, ByRef rc As Integer, ByVal basedate As String)
Declare Sub NaviGetDataItemNumber Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal locate As Integer, ByRef number As Integer)
Declare Function NaviGetDataItem2 Lib "SymNaviA" (ByVal hCatalog As Integer, ByRef rc As Integer, ByVal locate As Integer, ByVal index As Integer) As Integer
Declare Sub NaviGetNameDI         Lib "SymNaviA" (ByVal hDItem As Integer, ByRef rc As Integer, ByRef name As String)
Declare Sub NaviGetConditionDI    Lib "SymNaviA" (ByVal hDItem As Integer, ByRef rc As Integer, ByRef condition As Integer, ByRef key As String, ByRef search As Integer, ByRef nonmatch As Integer, ByRef range As Integer, ByRef lcheck As Integer, ByRef lvalue As String, ByRef rcheck As Integer, ByRef rvalue As String, ByRef reserve As String)
```

- `NaviGetDataItem` の `locate` は `NAVI_COND` または `NAVI_DATA`。`order` は同名時「1個目を 0」。`reserve` は 0。`[原本]`
- `NaviRemoveDataItem`: 項目間演算に使用中の項目は削除不可 → `NAVI_ERROR_USEDDATAITEM`。実行中は `NAVI_ERROR_EXECUTING`。実行後に変更する場合は先に `NaviInvalidateExecution`。`[原本]`
- `NaviGetDataItem2` の `index` が **0 始まりか 1 始まりか原本に明記なし**。`[要確認]`
  - **補足（傍証）**: 同じ API 群の列挙・順序引数は 0 始まりで運用されている。`NaviGetControlPoint` の
    `order=0` で先頭取得、`NaviGetCategory` を `For i=0 To number-1` で回すコードが `ExecNavi.bas` にある。`[原本]`
    これは `NaviGetDataItem2` も 0 始まりである可能性を高めるが、**当該関数自体の呼び出し例は無いため確定はしない**。`[要確認]`
- `NaviGetNameDI` の出力文字列の最大長・文字コード・終端方式は原本に記載なし。（v3 で解消。下記）
  - サンプル（`ExecNavi.bas`）にも当該関数の呼び出しは無く、VBA 自動マーシャリングに依存した使い方しか確認できないため、ctypes 用のバイト契約は導けない。`[要確認]`
  - **更新（v3）**: `name` は ANSI 内容の `BSTR*` で、DLL が `SysAllocStringByteLen` で必要な長さを確保して返すことを DLL 実装で確認した。
    呼び出し側でバッファ長や最大長を用意する必要は無い（§2.1, §5.1）。`[解析]`

#### 条件演算子 → `NaviChangeConditionDI` 引数の対応（`NaviAPISample2.vb`）`[原本]`
引数順: `(hDItem, rc, condition, key, search, nonmatch, range, lcheck, lvalue, rcheck, rvalue, reserve="")`

| 演算子 | condition | key | search | nonmatch | range | lcheck / lvalue | rcheck / rvalue |
|--------|-----------|-----|--------|----------|-------|-----------------|-----------------|
| `IN` | `NAVI_MATCH` | 値をカンマ連結 | `NAVI_COMPLETE` | `NAVI_MATCH` | - | - | - |
| `NOT IN` | `NAVI_MATCH` | 値をカンマ連結 | `NAVI_COMPLETE` | `NAVI_NONMATCH` | - | - | - |
| `LIKE` | `NAVI_MATCH` | 値をカンマ連結 | `NAVI_PARTIAL` | `NAVI_MATCH` | - | - | - |
| `NOT LIKE` | `NAVI_MATCH` | 値をカンマ連結 | `NAVI_PARTIAL` | `NAVI_NONMATCH` | - | - | - |
| `<` | `NAVI_RANGE` | - | - | - | `NAVI_UNDER` | `NAVI_NOTINCLUDE` / 値 | - |
| `<=` | `NAVI_RANGE` | - | - | - | `NAVI_UNDER` | `NAVI_INCLUDE` / 値 | - |
| `BETWEEN` | `NAVI_RANGE` | - | - | - | `NAVI_BETWEEN` | `NAVI_INCLUDE` / 値1 | `NAVI_INCLUDE` / 値2 |
| `>` | `NAVI_RANGE` | - | - | - | `NAVI_OVER` | - | `NAVI_NOTINCLUDE` / 値 |
| `>=` | `NAVI_RANGE` | - | - | - | `NAVI_OVER` | - | `NAVI_INCLUDE` / 値 |
| `RM` | `NaviRemoveDataItem(hCatalog, hDItem, rc)` を呼ぶ | | | | | | |

- 「-」の欄は変数の初期値（数値 0、文字列は空）のまま渡される。
- `key` の複数値は `"値1,値2,値3"` のカンマ区切り 1 文字列で渡す（末尾カンマは除去）。
- **`<` / `<=` は左側（`lcheck`/`lvalue`）、`>` / `>=` は右側（`rcheck`/`rvalue`）を使う。** 直感と逆に見えるが原本どおり。
  `frmMain.vb` も「〜以上」を `NAVI_RANGE, range=NAVI_OVER, rcheck=NAVI_INCLUDE, rvalue=値` で指定している。

---

## 4. 定数リファレンス

> `[原本]` `NaviAPI.vb` / `SymNaviApi.bas` に定義済み。Python では下記をそのまま定数化して使用可。

### 4.1 返却コード
```python
NAVI_OK    = 0x00  # 正常終了
NAVI_ERROR = 0x01  # エラー
NAVI_EOD   = 0x02  # データの最後
NAVI_NOMSG = 0x03  # メッセージなし
```

### 4.2 セッション状態
```python
NAVI_OPENED    = 0x01
NAVI_NOTOPENED = 0x00
```

### 4.3 位置情報（locate）
```python
NAVI_ALL  = 0x1C  # 全て（表側→表頭→条件）
NAVI_SIDE = 0x01  # 表側
NAVI_HEAD = 0x02  # 表頭
NAVI_COND = 0x03  # 条件
NAVI_DATA = 0x04  # データ項目
```

### 4.4 ダウンロード方法
```python
NAVI_DOWNLOADNOW   = 0x00
NAVI_DOWNLOADLATER = 0x01
```

### 4.5 保存形式（ftype）
```python
NAVI_CSV  = 0x01  # カンマ区切り
NAVI_TXT  = 0x02  # タブ区切り
NAVI_SYLK = 0x03  # SYLK
NAVI_WK3  = 0x04  # Lotus WK3
NAVI_XLSX = 0x05  # XLSX
NAVI_HTML = 0x07  # HTML
NAVI_FTXT = 0x08  # 罫線付きテキスト
NAVI_XLS  = 0x09  # Excel BIFF5(97-2003)
NAVI_XML  = 0x0A  # XML
# 組み合わせ用（Or）
NAVI_BLANK_NOSUPPRESS = 0x10   # 空白を取り除かない（既定）
NAVI_BLANK_SUPPRESS   = 0x20   # 空白を取り除く（WK3/CSV/TXTのみ有効）
NAVI_MULTI_UNITED     = 0x100  # マルチクロス結合出力（XLSと組合せ）
NAVI_MULTI_NOUNITED   = 0x200  # アクティブページのみ（既定）
NAVI_HEADER_OUTPUT    = 0x1000
NAVI_HEADER_NOOUTPUT  = 0x2000 # 既定
NAVI_FOOTER_OUTPUT    = 0x4000
NAVI_FOOTER_NOOUTPUT  = 0x8000 # 既定（VB 原本では -32768。下記）
```
- **`ftype` の解釈（`SymNaviA.dll` の `NaviSaveData` 実装）** `[解析]`

| ビット範囲 | 意味 | DLL が受け付ける値 | それ以外 |
|-----------|------|-------------------|---------|
| `0x0000000F` | 形式 | 0, 1(CSV), 2(TXT), 3(SYLK), 4(WK3), 5(XLSX), 7(HTML), 8(FTXT), 9(XLS), 15 | エラー |
| `0x000000F0` | 空白 | 0, 0x10, 0x20 | 0x30 などはエラー |
| `0x00000F00` | マルチクロス | 0, 0x100, 0x200 | 0x300 などはエラー |
| `0x00003000` | 表題 | 0（=出力しない）, 0x1000, 0x2000 | 0x3000 はエラー |
| `0x0000C000` | 脚注 | 0（既定）, 0x4000, 0x8000 | 0xC000 はエラー |
| `0xFFFF0000` | （未参照） | 無視される | - |

  - エラー時は `rc = NAVI_ERROR`、詳細コードは `NAVI_ERROR_SAVEDATA`(0x10)。
  - **`NAVI_FOOTER_NOOUTPUT` の符号**: VB.NET 原本は `As Integer = &H8000S`、VBA 原本は `As Long = &H8000`。どちらも 16bit リテラルとして
    **-32768（0xFFFF8000）** になる（`SymNaviF.exe` にも -32768 で埋め込まれている）。DLL は上位 16bit を見ずに `ftype And &HC000` で判定するため、
    `0x8000` と `0xFFFF8000` は**同じ結果**になる。Python で `0x8000` を使ってよい（v2 の「指定しない方が安全」は不要になった）。
  - XML(0x0A) や C 側ヘッダの `NAVI_CSV_ALLON`(0x0B)〜`NAVI_CSV_NOITEMNAME`(0x0E) は形式欄が受け付け対象外のため、この API では使えない。
- サンプルの出力形式マッピング: `XLSX→NAVI_XLSX, XLS→NAVI_XLS, CSV→NAVI_CSV, TXT→NAVI_TXT, WK3→NAVI_WK3, FTXT→NAVI_FTXT`、未知の文字列は `NAVI_FTXT`。`[原本]`
- **C 側ヘッダの同名定数と混同しないこと**: `naviapidef.h` の `NAVI_HEADER_OUTPUT=1 / NOOUTPUT=2`、`NAVI_FOOTER_OUTPUT=1 / NOOUTPUT=2` は
  C++ クラスライブラリ用の別の値で、`NaviSaveData` の `ftype` には使えない。`ftype` には VB 原本の値（0x1000/0x2000/0x4000/0x8000）を使う。DLL は内部でこれを 1/2 に変換している。`[原本][解析]`

### 4.6 繰り返し（repeat）
```python
NAVI_SIDE_REPEAT = 0x01
NAVI_HEAD_REPEAT = 0x02
NAVI_REPEAT      = 0x04
NAVI_NONREPEAT   = 0x08
NAVI_NOCHANGE    = 0x10
```

### 4.7 表示指定 / 項目種別 / 絞り込み
```python
# 表示の有無
NAVI_IN_DISP      = 0x00
NAVI_IN_NONDISP   = 0x01
NAVI_IN_OTHERS    = 0x02
NAVI_IN_TARGET    = 0x03
NAVI_IN_NONTARGET = 0x04
# マスタ型項目種類
NAVI_LABEL = 0x00
NAVI_CODE  = 0x01
# 絞り込み方法（search）
NAVI_COMPLETE   = 0x00
NAVI_FROMSTART  = 0x01
NAVI_PARTIAL    = 0x02
NAVI_FROMEND    = 0x03
NAVI_NOLOAD     = 0x04
NAVI_LIKESEARCH = 0x05
# データ項目条件（condition）
NAVI_MATCH      = 0x01
NAVI_RANGE      = 0x02
NAVI_NULL       = 0x04
NAVI_EXCEPTNULL = 0x08
# 範囲指定
NAVI_UNDER   = 0x01
NAVI_BETWEEN = 0x02
NAVI_OVER    = 0x04
# 境界値
NAVI_INCLUDE    = 0x00
NAVI_NOTINCLUDE = 0x01
# カテゴリロード
NAVI_NONMATCH = 0x02
```

### 4.8 管理ポイントの種類
```python
NAVI_CONTROLPOINT_MASTER   = 0x01
NAVI_CONTROLPOINT_ALLVALUE = 0x02
NAVI_CONTROLPOINT_CATEGORY = 0x03
NAVI_CONTROLPOINT_BOUND    = 0x04
NAVI_CONTROLPOINT_TIME     = 0x05
NAVI_CONTROLPOINT_TEMPLATE = 0x06
NAVI_CONTROLPOINT_UNKNOWN  = 0x07
NAVI_CONTROLPOINT_RULE     = 0x08
```

### 4.9 DBMS 種別 / 期間種別
```python
NAVI_DBMS_SYMFOWARE           = 0x00
NAVI_DBMS_ORACLE              = 0x01
NAVI_DBMS_INFORMIX            = 0x02
NAVI_DBMS_SQLSERVER           = 0x04
NAVI_DBMS_SYBASE              = 0x05
NAVI_DBMS_INGRES              = 0x06
NAVI_DBMS_ODBC                = 0x50
NAVI_DBMS_SYMFOWARE_OTHERSITE = 0x51
NAVI_DBMS_SHUNSAKU            = 0x08
NAVI_DBMS_ANYDB               = 0x08
# 期間種別（NaviChangePeriodKind）
NAVI_PERIOD_NOSPECIFY   = 0x01
NAVI_PERIOD_BEFORESTART = 0x02
NAVI_PERIOD_START       = 0x03
NAVI_PERIOD_STARTEND    = 0x04
NAVI_PERIOD_END         = 0x05
NAVI_PERIOD_AFTEREND    = 0x06
```

### 4.10 エラー詳細コード
```python
NAVI_ERROR_SYMFOWARE       = 0x03
NAVI_ERROR_ORACLE          = 0x04
NAVI_ERROR_SERVERENV       = 0x05
NAVI_ERROR_LOGON           = 0x06
NAVI_ERROR_CONNECT         = 0x07
NAVI_ERROR_SERVER          = 0x08
NAVI_ERROR_SESSION         = 0x09
NAVI_ERROR_OPEN            = 0x0A
NAVI_ERROR_CATALOG         = 0x0B
NAVI_ERROR_EXECMD          = 0x0C
NAVI_ERROR_EXECUTE         = 0x0D
NAVI_ERROR_DOWNLOAD        = 0x0E
NAVI_ERROR_READ            = 0x0F
NAVI_ERROR_SAVEDATA        = 0x10
NAVI_ERROR_CONTROLPOINT    = 0x11
NAVI_ERROR_DATAITEM        = 0x12
NAVI_ERROR_TYPE            = 0x13
NAVI_ERROR_CATEGORY        = 0x14
NAVI_ERROR_ZERO            = 0x15
NAVI_ERROR_OVER8000        = 0x16
NAVI_ERROR_NONMATCH        = 0x17
NAVI_ERROR_VALUE           = 0x18
NAVI_ERROR_RECONNECT       = 0x19
NAVI_ERROR_ITEM            = 0x1A
NAVI_ERROR_EXECUTING       = 0x1B
NAVI_ERROR_SQLSERVER       = 0x1C
NAVI_ERROR_INGRES          = 0x1D
NAVI_ERROR_DBKIND          = 0x1E
NAVI_ERROR_SAVE            = 0x1F
NAVI_ERROR_FILENOTFOUND    = 0x20
NAVI_ERROR_BADPATH         = 0x21
NAVI_ERROR_ACCESSDENIED    = 0x22
NAVI_ERROR_DISKFULL        = 0x23
NAVI_ERROR_SHARINGVIOLATION= 0x24
NAVI_ERROR_CANNOTUSE       = 0x46
NAVI_ERROR_CANNOT_SAVE     = 0x67
NAVI_ERROR_USEDDATAITEM    = 0x68
NAVI_ERROR_SHUNSAKU        = 0x96
NAVI_ERROR_NOSUPPORT       = 0x96
```

### 4.11 期間指定条件（NaviChangePeriod の condition 引数）`[原本]`
`NaviAPI.vb`（`Public Const NAVI_MONTH As Integer = &H0S` / `NAVI_YMD = &H1S`）、`SymNaviApi.bas`、`naviapidef.h` の 3 原本で一致。
```python
NAVI_MONTH = 0x00   # 月度の期間指定。日付が "YYYYMM00"（末尾 "00"）のとき使用
NAVI_YMD   = 0x01   # 年月日の期間指定。"YYYYMMDD" のとき使用
```
判定ロジック（サンプル実装）`[原本]`:
```vb
If Right(Param1$, 2) = "00" Then
    condition = NAVI_MONTH   ' 月末2桁が "00" → 月単位
Else
    condition& = NAVI_YMD    ' それ以外 → 日単位
End If
Call NaviChangePeriod(hItem&, rc&, condition&, Param1$, Param2$, "")
```

### 4.12 定数値の照合結果
- `SymNaviF.exe` に埋め込まれた `NAVI_*` 定数 123 個と本書 §4.1〜§4.11 を照合し、値はすべて一致（`NAVI_FOOTER_NOOUTPUT` は §4.5 の符号の違いのみ）。`[解析]`
- `NAVI_INCLUDE` / `NAVI_NOTINCLUDE` だけは VB 原本で `As Short` 定義（値 0 / 1。引数へは 32bit で渡して問題ない）。`[原本]`
- `SymNaviApi.bas` の `NAVI_LIKESEARCH = &5` は VBA エディタ上では `&O5`（8 進の 5）と表示される。値は 5 で同じ。`[原本]`

### 4.13 C 側ヘッダにだけある定数（参考）`[原本]`
`naviapidef.h` / `symnaviapi.h` には VB 宣言に無い定数がある。SymNaviA の 53 関数で意味を持ちうるものだけ抜粋する。
| 定数 | 値 | 備考 |
|------|----|------|
| `NAVI_TIMESPAN` | 0x0005 | 位置情報「時間フィールド」 |
| `NAVI_ERROR_PARAM` | 0x0026 | 指定されたパラメタが不正 |
| `NAVI_ERROR_RECORDDATE` | 0x0025 | （説明なし） |
| `NAVI_ERROR_CONVERT` | 0x009C | 結果加工出口で失敗（`symnaviapi.h` では同値が `NAVI_ERROR_DUPLICATE_CODE`） |
| `NAVI_ERROR_UNUSABLECHAR` | 0x00A0 | 使用できない文字が含まれる（`symnaviapi.h` では同値が `NAVI_ERROR_CPCTL_WHOAMI`） |
| `NAVI_ERROR_UNUSABLE_STRING` | 0x0098 | 使用できない文字列が含まれる |
| `NAVI_DBMS_POSTGRESQL` | 0x0007 | §3.3 参照 |
| `NAVI_CHARSET_SJIS` ほか | 501〜506 | C++ ライブラリ内部の文字コード設定。SymNaviA からは設定できない |

- 詳細コードは同じ値に複数の名前が付いている箇所がある。ログ出力では値（16 進）も併記すると切り分けやすい。`[整理]`

### エラーメッセージ対応表（`NaviAPISample2.vb` / `ExecNavi.bas` より）`[原本]`
| 詳細コード | メッセージ |
|-----------|-----------|
| `NAVI_ERROR_LOGON` | ログオンできませんでした |
| `NAVI_ERROR_CONNECT` | サーバ接続ができませんでした |
| `NAVI_ERROR_SERVER` | サーバ名に誤りがあります |
| `NAVI_ERROR_SESSION` | Navigator Server と接続されていません |
| `NAVI_ERROR_OPEN` | 問い合せファイルの読み込みに失敗しました |
| `NAVI_ERROR_CATALOG` | 指定された対象が問い合せファイルに読み込まれていません |
| `NAVI_ERROR_EXECMD` | 問い合せ（ファイル）の実行に失敗しました |
| `NAVI_ERROR_EXECUTE` | 問い合せファイルが実行されていません |
| `NAVI_ERROR_DOWNLOAD` | データのダウンロードに失敗しました |
| `NAVI_ERROR_READ` | データの読み込みに失敗しました |
| `NAVI_ERROR_SAVEDATA` | データの保存に失敗しました |
| `NAVI_ERROR_CONTROLPOINT` | 管理ポイントの参照に失敗しました |
| `NAVI_ERROR_DATAITEM` | データ項目の参照に失敗しました |
| `NAVI_ERROR_TYPE` | 扱えない型の管理ポイントまたはデータ項目です |
| `NAVI_ERROR_CATEGORY` | カテゴリの参照に失敗しました |
| `NAVI_ERROR_ZERO` | カテゴリが１件もありません |
| `NAVI_ERROR_OVER8000` | 8000件を超えるカテゴリは扱えません |
| `NAVI_ERROR_NONMATCH` | 一致するカテゴリがありません |
| `NAVI_ERROR_VALUE` | 入力された値に誤りがあります |
| `NAVI_ERROR_RECONNECT` | 既にログオンしています |
| `NAVI_ERROR_ITEM` | 使用できない管理ポイントまたはデータ項目があります |
| `NAVI_ERROR_USEDDATAITEM` | 項目間演算に使用されています |
| `NAVI_ERROR_SHUNSAKU` | Shunsaku で制限となる機能が指定されています |
| `NAVI_ERROR_EXECUTING` | 問い合せ実行中です |

---

## 5. Python ctypes 実装メモ（参考）

`[整理/解析]` 富士通公式の Python 宣言ではない。整数関数の対応、文字列の受け渡し方式（§2.1）は確度が高い。

```python
import ctypes
from ctypes import POINTER, c_int32

navi = ctypes.WinDLL("SymNaviA")   # bit数はアプリ側と一致させること

# NaviGetDataItemNumber(hCatalog, rc, locate, number)
navi.NaviGetDataItemNumber.argtypes = [c_int32, POINTER(c_int32), c_int32, POINTER(c_int32)]
navi.NaviGetDataItemNumber.restype  = None

# NaviGetDataItem2(hCatalog, rc, locate, index) -> hDItem
navi.NaviGetDataItem2.argtypes = [c_int32, POINTER(c_int32), c_int32, c_int32]
navi.NaviGetDataItem2.restype  = c_int32

# NaviRemoveDataItem(hCatalog, hDItem, rc)
navi.NaviRemoveDataItem.argtypes = [c_int32, c_int32, POINTER(c_int32)]
navi.NaviRemoveDataItem.restype  = None
```

### 5.1 文字列引数の実装 `[解析]`
```python
import ctypes
from ctypes import POINTER, byref, c_int32, c_char_p, c_void_p, c_uint

ENC = "cp932"
navi = ctypes.WinDLL("SymNaviA")          # x86 は stdcall → WinDLL
oleaut32 = ctypes.WinDLL("oleaut32")
oleaut32.SysStringByteLen.argtypes = [c_void_p]; oleaut32.SysStringByteLen.restype = c_uint
oleaut32.SysFreeString.argtypes    = [c_void_p]; oleaut32.SysFreeString.restype    = None

def s_in(text: str):
    """入力文字列 → char*（書き込み可能バッファで渡す）"""
    return ctypes.create_string_buffer(text.encode(ENC))

def s_out_new() -> c_void_p:
    """出力文字列用。必ず NULL で初期化する（DLL が非 NULL を SysFreeString するため）"""
    return c_void_p(None)

def s_out_take(bstr: c_void_p) -> str:
    """DLL が返した ANSI BSTR を str に変換して解放し、NULL に戻す"""
    if not bstr.value:
        return ""
    n = oleaut32.SysStringByteLen(bstr)               # バイト数（終端 NUL を含まない）
    text = ctypes.string_at(bstr.value, n).decode(ENC)
    oleaut32.SysFreeString(bstr)
    bstr.value = None
    return text

# NaviOpenSession(rc, user, password, server)
navi.NaviOpenSession.argtypes = [POINTER(c_int32), c_char_p, c_char_p, c_char_p]
navi.NaviOpenSession.restype  = None

# NaviGetErrorMessage(rc, errMessage)
navi.NaviGetErrorMessage.argtypes = [POINTER(c_int32), POINTER(c_void_p)]
navi.NaviGetErrorMessage.restype  = None

# NaviGetNameDI(hDItem, rc, name)
navi.NaviGetNameDI.argtypes = [c_int32, POINTER(c_int32), POINTER(c_void_p)]
navi.NaviGetNameDI.restype  = None

rc = c_int32(0); b = s_out_new()
navi.NaviGetNameDI(h_ditem, byref(rc), byref(b))
name = s_out_take(b)
```
- `NaviGetRecordData` の `record` も同じ方式（タブ区切り 1 行が返る）。
- 文字コードは Shift-JIS の範囲のみ。範囲外の文字（一部の環境依存文字や絵文字など）は `encode("cp932")` で例外になるため、呼び出し前に検出してエラーにする。`[原本]`（README 7.3）

### 5.2 一括定義の作り方 `[整理]`
§3 の VB.NET 宣言を機械変換する場合の規則:

| VB.NET 宣言 | ctypes |
|-------------|--------|
| `ByVal x As Integer` / `As Short` | `c_int32` |
| `ByRef x As Integer` | `POINTER(c_int32)` |
| `ByVal x As String` | `c_char_p`（`s_in()` で渡す） |
| `ByRef x As String` | `POINTER(c_void_p)`（`s_out_new()` / `s_out_take()`） |
| `Sub` | `restype = None` |
| `Function ... As Integer` | `restype = c_int32` |

### 5.3 DLL の選択と配置 `[原本][解析]`
| CAB 内のファイル | 中身 | 依存 | 用途 |
|-----------------|------|------|------|
| `symnavia.dll` | x86・デバッグ版（`debugdllVC14` のものと推定） | `mfc140d.dll`, `VCRUNTIME140D.dll`, `ucrtbased.dll` | 開発 PC でのデバッグのみ。配布不可 |
| `symnavia.dll1` | x64・デバッグ版（`debugdllVC14x64` と推定） | 同上 | 同上 |
| `symnavia.dll2` | **x86・リリース版**（`dllVC14` と推定） | `mfc140.dll`, `VCRUNTIME140.dll`, UCRT | 32bit アプリ / 32bit Excel |
| `symnavia.dll3` | **x64・リリース版**（`dllVC14x64` と推定） | 同上 | 64bit アプリ / 64bit Excel |

- bit 数（PE ヘッダ）とデバッグ/リリース（依存する MFC・VC ランタイムが `d` 付きか）は確定。どのフォルダ由来かは README の構成からの推定。
- 4 種ともエクスポートは同じ 53 関数（名前装飾なし）。CAB 内のファイル名末尾の数字は CAB 展開時の重複回避で付いたもので、インストール後はすべて `SymNaviA.dll`。
- リリース版は `KVR_A_9600.dll`, `KVR_D_9600.dll`, `KVR_O_9600.dll`, `kvrcmfc_9600.dll` などの同梱ランタイムにも依存する。
  **インストール先の `dllVC14` / `dllVC14x64` フォルダ一式を同じ場所に置き**、Visual C++ 2015-2019 再頒布可能パッケージ（`SystemVC14\vc_redist.x86/x64.exe`）を入れる。`[原本]`（README 7.2, 7.4）
- Python からは、Python 本体の bit 数と同じフォルダの DLL を使う。`os.add_dll_directory()` でそのフォルダを登録してから `WinDLL("SymNaviA")` を呼ぶ。`[整理]`

---

## 6. 実装前チェックリスト `[整理]`

- [ ] 使用する `SymNaviA.dll` を特定（`dllVC14`（32bit）/ `dllVC14x64`（64bit）のリリース版。§5.3）
- [ ] アプリと DLL の bit 数一致を確認
- [ ] `NaviOpenSession` の `rc` 確認
- [ ] `NaviOpenCatalog` の `rc` と戻りハンドル確認
- [ ] `NaviGetDataItem2` の index 開始値を実機で確認（傍証は 0 始まり）`[要確認]`
- [x] 文字列受け渡し方式 → `SymNaviA.dll` 実装で確定（§2.1）。実機では `NaviGetErrorMessage` → `NaviGetNameDI` の順に動作確認だけ行う
- [x] `NAVI_MONTH`(0) / `NAVI_YMD`(1) → 原本で確定（§4.11）
- [x] `NAVI_FOOTER_NOOUTPUT` の符号 → DLL は上位 16bit を無視するため影響なし（§4.5）
- [x] Unicode 版関数の有無 → 無し（§0, §10.2）
- [ ] 出力文字列の `BSTR*` は必ず NULL で初期化し、受け取り後に `SysFreeString` する（§5.1）
- [ ] 入力文字列が CP932 で表現できるか事前に検査する（§5.1）
- [ ] `dllVC14` / `dllVC14x64` 一式と VC++ 再頒布パッケージを配置する（§5.3）
- [ ] 日本語見出し・同名見出しの挙動確認
- [ ] 条件フィールドを削除対象から除外
- [ ] `NAVI_ERROR_USEDDATAITEM` を処理
- [ ] 全削除成功後に `NaviExecuteCatalog` を呼ぶ
- [ ] 列分割時、元 RNE を保存する `NaviSaveCatalog` を呼んでいないことを確認

---

## 7. 原本ファイルの役割

| ファイル | 役割 |
|---------|------|
| `NaviAPI.vb` | VB.NET 用 API 宣言（Integer / ByVal・ByRef）・定数・エラーコード |
| `SymNaviApi.bas` | Excel/VBA 用 API 宣言（PtrSafe / Long）・定数・エラーコード |
| `NaviAPISample2.vb` | 呼出し順序・`NAVI_COND`/`NAVI_DATA` 探索例・`RM` 除外例・エラー処理例 |
| `frmMain.vb` | GUI からの実行例（`NaviGetControlPoint`→`NaviChangePeriod`→`NaviExecuteCatalog`→`NaviSaveData`） |
| `ExecNavi.bas` | Excel/VBA サンプル。カタログ自動実行→印刷→ブック集約。`NaviChangePeriod` の `NAVI_MONTH`/`NAVI_YMD` 使い分け、名前指定の項目探索（`SearchItem`）、0 始まりのカテゴリ列挙、`NaviGetErrorMessage`→`NaviGetErrorCode` のフォールバックを実証 |
| プログラマーズガイド (Visual Basic編) | 公式の処理順序・各関数仕様・詳細エラー・配布手順 |
| サンプルプログラム説明書 (apisam) | サンプル構成・バッチ定義ファイル仕様・使用 API 一覧 |
| `naviapidef.h` | C 側の基本定数（`NAVI_MONTH`/`NAVI_YMD`、`NAVI_TIMESPAN`、`NAVI_CHARSET_*`、一部の詳細エラーコード） |
| `symnaviapi.h` | C++ クラスライブラリ用の追加定数（保存形式拡張、詳細エラー 0x25〜0x105、レイアウトエラー等）。SymNaviA の関数宣言は含まない |
| `kvrctypes.h` | 基本型定義（`KVR_L32` = 4 バイト `int` など） |
| `symnaviglobal.h` / `symnavie.h` / `naviapitrace.h` / `kvr__api.h` / `kvrc_api.h` | C++ ライブラリ内部（文字コード設定、例外クラス、トレース、リソース ID）。移植には不要 |
| `SymNaviA.dll`（4 種） | API 本体。エクスポート・呼び出し規約・文字列の受け渡し・`ftype` 解釈の一次証拠（§2.1, §4.5, §5.3） |
| `SymNaviF.exe`（`VB_Sample_2\x86`, `\x64`） | `NaviAPISample2.vb` のビルド済み実行ファイル。P/Invoke 定義の一次証拠（§2.1） |
| `SymNaviF.ini` | バッチ実行定義ファイルの記入例（§8） |
| `NaviAPIsample.vb`（`VB_Sample_1`） | `PutNaviMessage`（`NaviGetErrorMessage`→`NaviGetErrorCode` のフォールバック）を含む GUI サンプル用モジュール |
| `NaviAPIsample.xls`（`Excel_Sample`） | Excel 版サンプル。VBA は `ExecNavi.bas` と `SymNaviApi.bas` の 2 モジュールのみで、単体ファイルと内容同一 |
| `db_setup_postgres.bat` / `.sysin` / `NaviAPIsample.csv` | サンプル用 DB の構築一式（§9.2） |
| `Readme.txt` | 動作環境、フォルダ構成、配布方法、文字コード制限（§10） |

> 注: `Sheet1.cls` / `Sheet2.cls` は Excel の空シートクラスモジュールで、API 記述は含まない（参照不要）。

---

## 8. バッチ実行定義ファイル（`SymNaviF.ini`）仕様 `[原本]`

`SymNaviF.exe <定義ファイルのフルパス>` で起動する。`/?` でバージョン画面、引数なしはエラー。
INI 形式（`GetPrivateProfileStringA` で読むため ANSI/CP932）。値の区切りは **タブ**。

```ini
[Main]
CatalogList=本部<TAB>西部<TAB>中部     ; 実行するセクション名（タブ区切り、左から順に実行）
Login=UserID/Password@Server            ; 必須。NaviOpenSession
RDA=UserID/Password@Server              ; 任意。NaviConnectRDA
ORACLE=UserID/Password                  ; 任意。NaviConnectOracle
SQLServer=UserID/Password               ; 任意。NaviConnectSQLServer
POSTGRES=UserID/Password                ; 任意。NaviConnectBaseDBMS(NAVI_DBMS_ANYDB)
LogFile=c:\tmp\log.txt                  ; 既定 log.txt

[Default]
OutputType=FTXT                         ; CSV(既定)/XLSX/XLS/TXT/FTXT
Repeat=NOCHANGE                         ; SIDE_REPEAT/HEAD_REPEAT/REPEAT/NONREPEAT/NOCHANGE(既定)

[本部]
CatalogFile=c:\tmp\NaviAPIsample.rne    ; 必須。NaviOpenCatalog
OutputFile=c:\tmp\本社.csv              ; 既定 c:\temp\tmp.<OutputType>（XLS は c:\temp\tmp.xls）
OutputType=CSV                          ; 省略時 [Default]。WK3 も可
Repeat=REPEAT                           ; 省略時 [Default]
ReloadCategory=YES                      ; YES(既定)/NO。NO でもカテゴリ 0 件なら再読込
CurrentMonth=199706                     ; 任意。NaviChangeCurrentMonth（YYYYMM）
Param1=本部名<TAB>IN<TAB>本社            ; Param1 から連番。空になった番号で終了
Param2=商品分類<TAB>IN<TAB>ＡＶ<TAB>冷暖房
Param3=粗利益<TAB>>=<TAB>80000
Param4=月度<TAB>BETWEEN<TAB>19970400<TAB>19970600
Shell=コマンドライン                    ; 任意。保存後に実行（非同期）
Message=表示文字列                      ; 任意。保存後に MsgBox 表示
```

- `ParamN` の書式: `項目名<TAB>演算子<TAB>値1<TAB>値2...`。項目名と値は前後空白を除去、演算子は大文字化して判定。
- 演算子と項目種別の組み合わせ:

| 項目種別（§1 の SearchItem） | 使える演算子 |
|------------------------------|-------------|
| 管理ポイント | `IN`, `RM` |
| 時間型管理ポイント（年度/半期/四半期/月度/日） | `IN`, `BETWEEN`, `RM` |
| 条件データ項目（`NAVI_COND`） | `IN`, `NOT IN`, `LIKE`, `NOT LIKE`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `RM` |
| 表示データ項目（`NAVI_DATA`） | `RM` のみ |

- 時間型の値は `YYYYMMDD`。月単位は `YYYYMM00`（§4.11）。
- Login 系の書式は `ユーザ/パスワード@サーバ`。`@` が無ければ全体をユーザ部、`/` が無ければパスワード空として扱う。

---

## 9. サンプル一式の構成（`C:\NAVIAP\Samples`）

### 9.1 構成 `[解析]`
```
C:\NAVIAP\Samples
├─ Excel_Sample\NaviAPIsample.xls          Excel/VBA 版（VBA: ExecNavi, SymNaviApi）
├─ SampleData\db_setup_postgres.bat/.sysin サンプル DB 構築
├─ SampleData\NaviAPIsample.csv            サンプルデータ（CP932）
├─ VB_Sample_1\                            GUI サンプル（PrjNaviAPIsample.vbproj）
└─ VB_Sample_2\                            バッチ実行サンプル（prjNaviBatch.vbproj → SymNaviF.exe）
     ├─ SymNaviF.ini
     ├─ x86\SymNaviF.exe   PE32 / .NET 4.x / 32BITREQUIRED
     └─ x64\SymNaviF.exe   PE32+ (AMD64) / .NET 4.x
```
- `.vb` / `.bas` / `.h` はすべて **Shift_JIS（CP932）**、`.resx` / `.vbproj` は UTF-8。原本を読む際は文字コードを指定する。

### 9.2 サンプル DB（PostgreSQL 系）`[解析]`
- `db_setup_postgres.bat`: `psql -p 26500 -U postgres -h localhost -f ./db_setup_postgres.sysin postgres`
- `db_setup_postgres.sysin`: スキーマ `APISAMPLE`、表 `APISAMPLE`
  （`商品分類, 商品中分類, 本部名, 店舗名, 月度` は `char(10)`、`売上額, 個数, 粗利益` は `integer`）を作成し、
  `NaviAPIsample.csv` を `\copy` で投入。`PUBLIC` に `SELECT` 権限付与。
- CSV の `月度` は `1997/04`〜`1997/06`。サンプル定義の期間指定 `19970400`〜`19970600` と対応する。
- 移植後の結合テスト用 DB として流用できる（本番データに触れずに API 呼び出しを検証できる）。`[整理]`

---

## 10. 配布パッケージとインストール構成

### 10.1 インストール前 `API` フォルダ `[解析]`
| ファイル | 内容 |
|---------|------|
| `Readme.txt` | ソフトウェア説明書「Navigator API Visual Basic編, Visual C++編」資料コード B5141JC-V-09601 |
| `Disk1\setup.exe` / `Setup.ini` | InstallShield ランチャー。`Product=Interstage Navigator API`、`ProductVersion=9.6.0` |
| `Disk1\Interstage Navigator API.msi` | MSI 本体 |
| `Disk1\NAVIAP.cab` | 実ファイル本体（412 ファイル。同名ファイルは展開時に `.dll1` などの連番が付く） |

### 10.2 インストール後のフォルダ構成と注意事項 `[原本]`（README）
```
<インストールフォルダ>（既定 C:\NAVIAP）
├─ bas               Visual Basic 定義ファイル（NaviAPI.vb / SymNaviApi.bas）
├─ inc               C/C++ インクルードファイル
├─ dllVC14           ランタイム（32bit）       ← 配布・実行用
├─ dllVC14x64        ランタイム（64bit）       ← 配布・実行用
├─ debugdllVC14 / debugdllVC14x64   デバッグ版ランタイム
├─ libVC14 / libVC14x64 / debuglibVC14 / debuglibVC14x64   C++ 用ライブラリ
├─ Samples
├─ SystemVC14        vc_redist.x86.exe / vc_redist.x64.exe
└─ readme.txt
```
- 動作 OS: Windows 8.1 / 10（32/64bit）。開発環境: Visual Studio 2015/2017/2019、Excel 2013〜Microsoft 365。
- **扱える文字コードは Shift-JIS の範囲のみ。** Visual C++ でも Unicode 対応のプログラミングはできない。
  C++ ヘッダに Unicode 関連の改版履歴や `KVRC_WCHAR` があるのは内部実装のためで、公開 API（SymNaviA）は ANSI のみ。
- 他製品に同梱された Navigator API と同じシステムでは共存できない（すべてアンインストールしてから使う）。
- 配布時は Navigator API のランタイムモジュールと、アプリの bit 数に合った VC++ 再頒布可能パッケージが必要。
- Excel VBA から使う場合は Excel の bit 数に合わせて `dllVC14`（32bit）/ `dllVC14x64`（64bit）を選ぶ。
- Navigator API で作成したアプリは**マルチスレッド非対応**（§0）。

---

## 11. 未確認事項と追加で解析すべきもの `[整理]`

v3 時点で、移植に必要な宣言・定数・文字列の受け渡し・DLL 配置は原本または DLL 実装で確定した。残りは実機で確認する事項のみ。

| 優先 | 項目 | 確認方法 |
|------|------|---------|
| 1 | §5.1 の文字列実装で `NaviGetErrorMessage` と `NaviGetNameDI` が正しく日本語を返し、解放時に異常が無いこと | 実機テスト（サンプル DB で可） |
| 2 | `NaviGetDataItem2` / `NaviGetControlPoint2` の `index` が 0 始まりか（サンプルに使用例なし） | 実機で `index=0` と `index=number` を試す |
| 3 | `NaviAPISample2.vb` の非表示ループ（`order` 常に 0）の意図 | 実機でカテゴリ数の変化を確認、またはプログラマーズガイド（PDF） |
| 4 | 詳細エラーコードの重複値（0x9C, 0xA0 など）が SymNaviA でどの意味で返るか | プログラマーズガイド（PDF）の詳細エラー一覧 |

追加で入手すると確度が上がる資料: 「Navigator API プログラマーズガイド（Visual Basic 編）」「サンプルプログラム説明書」の PDF（README によればオンラインマニュアル CD-ROM に収録）。
これ以外の CAB 内ファイル（C++ 内部ヘッダ、その他の `kvr*_9600.dll`、`.msg`、`.lib`、`vc_redist`、`rn_new.xlsx_`）は移植には不要。

