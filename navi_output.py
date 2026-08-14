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

def validate_output_contract(job,stage):
 configured=str(job.get('output_format') or '').lower(); filename=str(job.get('output_file') or '')
 effective=normalize_output_format(configured,filename); expected={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[effective]; actual=Path(filename).suffix.lower(); match=configured==effective and actual==expected
 log.info('出力形式確認 stage=%s job=%s configured=%s effective=%s file=%s actual_ext=%s expected_ext=%s match=%s',stage,job.get('name'),configured,effective,filename,actual or '(なし)',expected,match)
 if not match:raise ValueError(f'出力形式不一致: 設定={configured}, 実効={effective}, ファイル={filename}, 期待拡張子={expected}')
 return effective
