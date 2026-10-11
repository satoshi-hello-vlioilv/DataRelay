"""データビュワーの表示の設定（2.2.0）。対象ごとに持つ。

列の並び・表示・表示名、式で作る列（計算列）、条件（絞り込み）を、対象（jobs の viewer_json）に保存する。
値ごとに分けて出した対象は、どの値のファイルでも同じ設定を使う。登録内容の持ち出しにも一緒に入る。

式と条件の意味は画面の static/viewer-model.js が決める（WaveLog から移した作り）。ここは
「保存してよい形か」だけを見る: 形をそろえ、長さと数に上限を付け、知らない比べ方は落とす。
"""

OPS=('contains','not_contains','eq','neq','starts','ends','gt','gte','lt','lte','empty','not_empty')
MAX_COLS=500
MAX_CALC=50
MAX_FILTERS=30
FORMULA_MAX=2000


def _text(v,limit):
 return str(v if v is not None else '').strip()[:limit]


def normalize(v):
 """保存してよい形へ。壊れた物・知らない物は落とす（読み込みで画面を壊さない）。"""
 v=v if isinstance(v,dict) else {}
 cols,seen=[],set()
 for c in (v.get('cols') or [])[:MAX_COLS]:
  if not isinstance(c,dict):continue
  key=_text(c.get('key'),200)
  if not key or key in seen:continue
  seen.add(key)
  one={'key':key,'show':c.get('show') is not False}
  label=_text(c.get('label'),100)
  if label and label!=key:one['label']=label
  cols.append(one)
 calc,names=[],set()
 for c in (v.get('calc') or [])[:MAX_CALC]:
  if not isinstance(c,dict):continue
  name=_text(c.get('name'),100);formula=_text(c.get('formula'),FORMULA_MAX)
  if not name or not formula or name in names:continue
  names.add(name);calc.append({'name':name,'formula':formula})
 filters=[]
 for f in (v.get('filters') or [])[:MAX_FILTERS]:
  if not isinstance(f,dict):continue
  column=_text(f.get('column'),200);op=str(f.get('op') or '')
  if not column or op not in OPS:continue
  filters.append({'column':column,'op':op,'value':_text(f.get('value'),500)})
 out={}
 if cols:out['cols']=cols
 if calc:out['calc']=calc
 if filters:out['filters']=filters
 if filters and v.get('join')=='or':out['join']='or'
 return out
