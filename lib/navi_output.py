"""出力形式 ―― 何で出すのか、どんな名前になるのか。

形式の読み替え（sqlite/db→sqlite3 など）、拡張子の付け替え、同時に出す形式の
絞り込み、設定と実ファイル名の食い違い検査。処理の本筋から独立していて、
本体の状態を一切見ない。

app.py から分けてある。外から見える名前は分ける前と同じ（app からも読める）。
"""
import json,re,sqlite3
from pathlib import Path
from navi_log import log

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
OUTPUT_FORMAT_LABEL={'sqlite3':'SQLite3','txt':'TXT','csv':'CSV','xlsx':'EXCEL','accdb':'ACCESS'}
def parse_output_format(value):
 """形式名として読めたものだけを返す。読めなければ空（既定へ倒さない）。

 normalize_output_format は分からない値を sqlite3 として扱う。同時出力の一覧に
 使うと、打ち間違いが黙って sqlite3 として増えてしまうので、ここは厳密にする。"""
 fmt=str(value or '').strip().lower()
 fmt={'sqlite':'sqlite3','db':'sqlite3','access':'accdb','excel':'xlsx','xls':'xlsx'}.get(fmt,fmt)
 return fmt if fmt in OUTPUT_FORMAT_LABEL else ''

def job_extra_formats(job):
 """1回の抽出から、主の形式に加えて出す形式。主と重なるもの・読めないものは落とす。"""
 primary=normalize_output_format(job.get('output_format'),job.get('output_file'))
 raw=job.get('extra_formats')
 if isinstance(raw,str):
  try:raw=json.loads(raw or '[]')
  except Exception:raw=[x for x in re.split(r'[,\s]+',raw) if x]
 out=[]
 for v in (raw or []):
  f=parse_output_format(v)
  if f and f!=primary and f not in out:out.append(f)
 return out[:4]

def canonical_output_file(filename,fmt):
 ext={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[fmt]
 stem=Path(str(filename or 'output')).stem
 for suffix in ('sqlite3','sqlite','accdb','xlsx','xls','csv','txt'):
  if stem.lower().endswith(suffix):stem=stem[:-len(suffix)]
 return (stem or 'output')+ext

def sqlite_column_limit():
 """このPythonに入っているSQLiteが、1つの表に持てる列の数。

 決め打ちの数字を書かない。SQLITE_MAX_COLUMN は組み立てた人が変えられるので、
 動いている本人に聞くのが確実（既定は2000、上限は32767まで上げられる）。"""
 try:
  with sqlite3.connect(':memory:') as conn:return int(conn.getlimit(sqlite3.SQLITE_LIMIT_COLUMN))
 except Exception:return 2000

def output_column_limit(fmt):
 """その形式が受け取れる列の数。制限が無い形式は None。

 列の上限は「読み取り側の都合」ではなく「書き出す形式の都合」でしか決まらない。
 固定長のレイアウトが何百項目あろうと、CSVで出すなら何の問題も無い。逆に
 ACCESSは255項目で本当に入らない。だから制限はここ一箇所にだけ置いて、
 読み取り・プレビュー・結合の側では列を切らない。"""
 fmt=normalize_output_format(fmt)
 if fmt=='accdb':return 255      # Accessの1テーブルあたりフィールド数
 if fmt=='xlsx':return 16384     # Excelのシート列数(XFD)。見出し1行ぶんも同じ枠
 if fmt=='sqlite3':return sqlite_column_limit()
 return None                     # csv/txt は区切って並べるだけなので上限は無い

def check_output_columns(fmt,count,where=''):
 """列が多すぎて入らないなら、書き出す前に、数を添えて断る。

 黙って切ると出来上がった物が静かに欠ける。生のDBエラーを出すと何が起きたか
 分からない。どちらも避けて、形式名と両方の数を出す。"""
 limit=output_column_limit(fmt);count=int(count or 0)
 if limit is None or count<=limit:return count
 label=OUTPUT_FORMAT_LABEL.get(normalize_output_format(fmt),fmt)
 raise ValueError(f'{label}は{limit:,}列までです（いまは{count:,}列）。{where or "出力する列"}を減らすか、列数に上限の無いCSV／TXTで出してください')

# ---- 列の型 ----------------------------------------------------------------
# 固定長テキストは、どこまでいっても文字の並びでしかない。「00123」が数量なのか
# 品番なのかは、ファイルを見ても分からない ―― 読取マスタで決めてもらう。
# 決めてもらった型を活かせるかどうかは、書き出す形式の側で違う。
#   SQLite3 … TEXT / INTEGER / REAL（日付型は無いのでISO文字列。文字のまま正しく並ぶ）
#   ACCESS  … 長いテキスト / 長整数 / 倍精度 / 日付時刻
#   EXCEL   … 数値セルと日付セル（右寄せ・計算・並べ替えがそのまま効く）
#   CSV・TXT… 型は持てない。ただし値の形は揃う（20260814 → 2026-08-14 など）
# 型の名前をここに置いてあるのは、決める側（読取マスタ）と使う側（書き出し）で
# 語彙が2つに割れないようにするため。
COLUMN_TYPES=('text','integer','real','date','datetime')
COLUMN_TYPE_LABEL={'text':'文字','integer':'整数','real':'小数','date':'日付','datetime':'日時'}
COLUMN_TYPE_NOTE={'text':'そのまま文字として出します（既定）。品番・コード・電話番号など、先頭の0に意味があるものはこれ。',
                  'integer':'整数にします。前の0は落ちます（00123→123）。末尾の符号（123-）も読みます。',
                  'real':'小数にします。小数点が無いときは「小数桁」で入れる位置を決めます（0012345 桁2→123.45）。',
                  'date':'日付にします。読み方は書式で決めます（既定 YYYYMMDD）。出力は 2026-08-14 の形。',
                  'datetime':'日付と時刻にします（既定 YYYYMMDDHHMMSS）。出力は 2026-08-14 09:30:00 の形。'}

def normalize_column_type(value):
 v=str(value or '').strip().lower()
 v={'str':'text','string':'text','char':'text','int':'integer','number':'real','float':'real',
    'decimal':'real','double':'real','time':'datetime','timestamp':'datetime'}.get(v,v)
 return v if v in COLUMN_TYPES else 'text'

def format_keeps_types(fmt):
 """その形式が、型をファイルの中に持てるか。CSV・TXTは持てない（値の形は揃う）。"""
 return normalize_output_format(fmt) in ('sqlite3','accdb','xlsx')

def sqlite_column_type(t):
 return {'integer':'INTEGER','real':'REAL'}.get(normalize_column_type(t),'TEXT')

def accdb_column_type(t):
 """AccessのDDLで使う型。日付時刻はDATETIME、整数はLONG（-21億〜21億）。"""
 return {'integer':'LONG','real':'DOUBLE','date':'DATETIME','datetime':'DATETIME'}.get(normalize_column_type(t),'LONGTEXT')

def accdb_schema_type(t):
 """schema.ini（TransferTextの取込定義）で使う型名。DDLとは綴りが違う。"""
 return {'integer':'Long','real':'Double','date':'DateTime','datetime':'DateTime'}.get(normalize_column_type(t),'LongChar')

def job_column_types(job,headers=None):
 """この対象の列の型。決めていない列（RNEなど型の概念が無い入力）は文字。

 対象には名前で持たせる。並び順で持つと、列が1本増えただけで全部ずれる。"""
 raw=(job or {}).get('_column_types') or {}
 if isinstance(raw,str):
  try:raw=json.loads(raw or '{}')
  except Exception:raw={}
 if not isinstance(raw,dict):raw={}
 if headers is None:return {k:normalize_column_type(v) for k,v in raw.items()}
 return {h:normalize_column_type(raw.get(h)) for h in headers}

def validate_output_contract(job,stage):
 configured=str(job.get('output_format') or '').lower(); filename=str(job.get('output_file') or '')
 effective=normalize_output_format(configured,filename); expected={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[effective]; actual=Path(filename).suffix.lower(); match=configured==effective and actual==expected
 log.info('出力形式確認 stage=%s job=%s configured=%s effective=%s file=%s actual_ext=%s expected_ext=%s match=%s',stage,job.get('name'),configured,effective,filename,actual or '(なし)',expected,match)
 if not match:raise ValueError(f'出力形式不一致: 設定={configured}, 実効={effective}, ファイル={filename}, 期待拡張子={expected}')
 return effective
