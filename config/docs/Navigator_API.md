# Navigator API リファレンス（Claude Code 用）

> **対象 DLL**: `SymNaviA`（すべての関数はこの DLL からエクスポートされる）
> **API バージョン**: Navigator Visual Basic Interface API 9.6.0（宣言ファイル基準）
> **原本製品**: FUJITSU Interstage Navigator Server V9.4.1
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
| `[要確認]` | 添付原本だけでは確定できない | **コードに埋め込む前に実機/C++ヘッダで検証** |

- 整数型は VB.NET が `Integer`、VBA が `Long`。どちらも **32bit 符号付き整数**。Python では `ctypes.c_int32` を明示的に使う。`[整理]`
- 文字列出力引数（`ByRef ... As String`）の Python からの受け渡し方法は **未確定**。`[要確認]`
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
```
- 管理ポイントが「年度／半期／四半期／月度／日」の場合は**時間型**として扱い、条件変更に `NaviChangePeriod` を使う（サンプルの分類ロジック）。`[原本]`

---

## 2. 型対応表

| 概念 | VB.NET | VBA(PtrSafe) | Python ctypes |
|------|--------|--------------|----------------|
| 返却/件数/インデックス/ハンドル | `Integer` | `Long` | `c_int32` `[整理]` |
| 上記の参照渡し（ByRef） | `ByRef ... As Integer` | `... As Long` | `POINTER(c_int32)` `[整理]` |
| 入力文字列 | `ByVal ... As String` | `ByVal ... As String` | `c_char_p`（要文字コード確認）`[要確認]` |
| 出力文字列 | `ByRef ... As String` | `... As String` | **未確定** `[要確認]` |

> Windows の `ctypes.c_long` も通常 32bit なので幅は一致するが、本書では 32bit を明示するため
> `c_int32` を推奨する。`c_long` が誤りという意味ではない。`[整理]`

---

## 3. 関数リファレンス

各関数は `[VB.NET]` / `[VBA]` / `[ctypes(参考)]` の順に宣言を示す。
`ctypes` 欄は原本の Integer/Long, ByVal/ByRef から対応付けた**参考実装**であり、富士通公式指定ではない。`[整理/要確認]`

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
- `NaviGetNameDI` の出力文字列の最大長・文字コード・終端方式は原本に記載なし。`[要確認]`
  - サンプル（`ExecNavi.bas`）にも当該関数の呼び出しは無く、VBA 自動マーシャリングに依存した使い方しか確認できないため、ctypes 用のバイト契約は導けない。`[要確認]`

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
NAVI_FOOTER_NOOUTPUT  = 0x8000 # 既定
```

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

### 4.11 期間指定条件（NaviChangePeriod の condition 引数）`[原本(使用)/要確認(値)]`
`ExecNavi.bas` で `NaviChangePeriod` の第3引数として使用が確認された定数。
**使用事実は確定しているが、数値定義は今回のファイル群に含まれていないため要確認。**
`NaviAPI.vb` / `SymNaviApi.bas` の定数定義部で値を確認して埋めること。
```python
# 値は未確認（NaviAPI.vb / SymNaviApi.bas で要確認）
NAVI_MONTH = 0x??   # 月指定。日付が "YYYYMM00"（末尾 "00"）のとき使用
NAVI_YMD   = 0x??   # 年月日指定。"YYYYMMDD" のとき使用
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

`[整理/要確認]` 富士通公式の Python 宣言ではない。整数関数の対応例のみ確度が高い。

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

> **文字列を返す関数（`NaviGetNameDI` 等）は上記方針で確定しない。**
> `c_char_p` / `create_string_buffer` への単純対応はバッファ長・文字コード・終端が
> 不明なため、実機検証または C/C++ 用インクルードファイル（`\inc`）の確認が必要。`[要確認]`

---

## 6. 実装前チェックリスト `[整理]`

- [ ] 使用する `SymNaviA.dll` を特定（`\dllVC10〜14` のどれか）
- [ ] アプリと DLL の bit 数一致を確認
- [ ] `NaviOpenSession` の `rc` 確認
- [ ] `NaviOpenCatalog` の `rc` と戻りハンドル確認
- [ ] `NaviGetDataItem2` の index 開始値を実機で確認（傍証は 0 始まり）`[要確認]`
- [ ] `NaviGetNameDI` の文字列受け渡しを実機で確認 `[要確認]`
- [ ] `NAVI_MONTH` / `NAVI_YMD` の数値を宣言ファイルで確認 `[要確認]`
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

> 注: `Sheet1.cls` / `Sheet2.cls` は Excel の空シートクラスモジュールで、API 記述は含まない（参照不要）。
