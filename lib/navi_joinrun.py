"""結合マスタの出し入れと、結合で読むファイルの読み手。

繋ぎ方そのもの（SQLの組み立て・一致の数え方・持ち出し用のJSON）は navi_join.py にある。
こちらは、それを控えDBへ出し入れし、実際のファイルを読む側 ―― 本体の名前を借りるので、
navi_split・navi_textrun と同じく app.py の終わりで取り込む。

読み手はデータビュワーと同じ read_preview_data を使う。同じファイルを2通りに読むと、
画面で見えているものと結合の中身がずれる。
"""
import json
from datetime import datetime
from pathlib import Path
import app
from app import log, settings_sync_lock

def _borrow(name):
 """本体の関数は、取り込んだ時点の実体ではなく、呼ばれた時点で引く（navi_split と同じ約束）。"""
 def call(*a,**k):return getattr(app,name)(*a,**k)
 call.__name__=name;call.__qualname__='app.'+name
 return call

for _n in ('_mark_settings_dirty',
           '_json_rows',
           '_viewer_output_path',
           'find_text_layout',
           'flush_local_to_master_async',
           'init_settings_db',
           'job_output_plan',
           'load',
           'load_text_layouts',
           'normalize_job_source',
           'normalize_join_recipe',
           'normalize_output_format',
           'read_preview_data',
           'resolve_path',
           'settings_connection',
           'validate_join_recipe'):globals()[_n]=_borrow(_n)
del _n

# 読み込みの上限。ここを超える表は、そもそもメモリ上で突き合わせる形に向かない。
JOIN_SOURCE_MAX_ROWS=2_000_000

def _uuid4():
 import uuid;return str(uuid.uuid4())

def _recipe_row(r):
 return normalize_join_recipe({'id':r['id'],'name':r['name'],'description':r['description'],
                               'sources':_json_rows(r['sources_json']),
                               'joins':_json_rows(r['joins_json']),
                               'columns':_json_rows(r['columns_json']),
                               'updated_at':r['updated_at']})
def _load_join_recipes(c):
 try:return [_recipe_row(r) for r in c.execute('SELECT * FROM join_recipes ORDER BY display_order,name')]
 except Exception:
  log.exception('JOIN_RECIPE_LOAD_FAILED');return []
def load_join_recipes():
 init_settings_db()
 with settings_connection() as c:return _load_join_recipes(c)
def find_join_recipe(recipe_id):
 rid=str(recipe_id or '').strip()
 if not rid:return None
 return next((x for x in load_join_recipes() if x['id']==rid),None)
def save_join_recipe(recipe):
 """1件を登録・更新する。idが無ければ新規。保存できない理由があれば例外。"""
 r=normalize_join_recipe(recipe)
 bad=validate_join_recipe(r)
 if bad:raise ValueError('／'.join(bad))
 init_settings_db();rid=r['id'] or _uuid4();now=datetime.now().isoformat(timespec='seconds')
 with settings_sync_lock, settings_connection() as c:
  order=c.execute('SELECT COALESCE(MAX(display_order),-1)+1 n FROM join_recipes').fetchone()['n']
  cur=c.execute('SELECT display_order FROM join_recipes WHERE id=?',(rid,)).fetchone()
  c.execute('INSERT OR REPLACE INTO join_recipes (id,display_order,name,description,sources_json,'
            'joins_json,columns_json,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (rid,cur['display_order'] if cur else order,r['name'],r['description'],
             json.dumps(r['sources'],ensure_ascii=False),json.dumps(r['joins'],ensure_ascii=False),
             json.dumps(r['columns'],ensure_ascii=False),now))
  _mark_settings_dirty()
 flush_local_to_master_async('join-recipe-save')
 log.info('JOIN_RECIPE_SAVE id=%s name=%s ファイル=%s つなぎ目=%s 出す列=%s',
          rid,r['name'],len(r['sources']),len(r['joins']),len(r['columns']) or '（自動）')
 return dict(r,id=rid,updated_at=now)
def join_recipe_usage(recipe_id,cfg=None):
 rid=str(recipe_id or '').strip()
 if not rid:return []
 jobs=(cfg or load()).get('jobs') or []
 return [j.get('name','') for j in jobs
         if normalize_job_source(j.get('source'))=='join' and str(j.get('recipe_id') or '')==rid]
def delete_join_recipe(recipe_id):
 """使っている対象があるうちは消さない（消すと、その対象は繋ぎ方を失って必ず失敗する）。"""
 rid=str(recipe_id or '').strip()
 used=join_recipe_usage(rid)
 if used:raise ValueError('この結合マスタは'+str(len(used))+'件の対象が使っています（'+'、'.join(used[:3])+'）。先に対象側を切り替えてください')
 init_settings_db()
 with settings_sync_lock, settings_connection() as c:
  n=c.execute('DELETE FROM join_recipes WHERE id=?',(rid,)).rowcount
  _mark_settings_dirty()
 flush_local_to_master_async('join-recipe-delete')
 log.info('JOIN_RECIPE_DELETE id=%s deleted=%s',rid,n)
 return bool(n)

def resolve_join_path(value,cfg):
 """結合で読むファイルの場所。書き方の決まりはRNE・テキストと同じ。"""
 raw=str(value or '').strip()
 if not raw:return Path('')
 import os
 raw=os.path.expandvars(os.path.expanduser(raw))
 p=Path(raw)
 if p.is_absolute() or raw.startswith('\\\\'):return p
 if raw.startswith(('.\\','..\\','./','../')):return resolve_path(raw,app.BASE)
 return resolve_path(raw,resolve_path(str((cfg or {}).get('text_folder') or app.TEXT_FOLDER_DEFAULT)))

def join_reader(cfg):
 """navi_join へ渡す読み手。これまでの出力形式は、データビュワーと同じ経路で読む。"""
 def reader(src,limit=None):
  path=resolve_join_path(src['path'],cfg)
  if not path.is_file():raise FileNotFoundError(f'{src["alias"]}: ファイルがありません: {path}')
  job={'output_format':src['format'],'table':src.get('table') or '','sheet':src.get('sheet') or ''}
  # max_columns=None ―― ここはデータとして読む。表示の都合で切ると列が消えたまま結合される。
  _fmt,headers,rows,_total,_cols=read_preview_data(path,job,limit=int(limit or JOIN_SOURCE_MAX_ROWS),max_columns=None)
  return headers,rows
 return reader

def join_layouts():
 """固定長テキストを混ぜるときのための読取マスタ。id で引ける形にして渡す。"""
 return {x['id']:x for x in load_text_layouts()}

# ---- 組み立て中だけ、ローカルの写しを読む --------------------------------
# 下読みは、キーを1つ変えるたびに全部のファイルを読み直す。相手が共有フォルダーなら
# そのたびに往復することになるので、写しがあるならそちらを読む。
#
# 実行（write_intermediate_csv）はこの道を通さない。写しは先頭だけのことがあり、
# それで本番を作ると、静かに中途半端なファイルが出来上がる。分けてあるのはそのため。

def sampled_recipe(recipe,cfg):
 """下読み用に、各ファイルの場所を「ローカルの写し」へ差し替えた取り決めを返す。

 (差し替えた取り決め, ファイルごとの内訳) を返す。写せなかったものは元のまま
 ―― 写しは速さのためのものなので、無ければ無いで、これまでどおり読むだけ。
 """
 import navi_localcopy
 r=normalize_join_recipe(recipe);out=[];srcs=[]
 for s in r['sources']:
  s=dict(s);raw=s['path']
  info={'alias':s['alias'],'path':raw,'ok':False,'note':''}
  path=resolve_join_path(raw,cfg)
  if raw and path.is_file():
   local,detail=navi_localcopy.sample(path,s['format'])
   info.update({k:detail[k] for k in ('ok','mode','bytes','total','elapsed','cached','note')})
   if local:
    # 名前は元のまま持たせる。ここを写しの名前にすると、件数の内訳も画面の
    # 見出しも、身に覚えのないファイル名で出てしまう。
    s['name']=s['name'] or Path(raw).name
    s['path']=str(local)
  else:
   info['note']='ファイルがありません' if raw else 'ファイルが決まっていません'
  srcs.append(s);out.append(info)
 return dict(r,sources=srcs),out

def join_sample_reader(cfg):
 """下読み専用の読み手。差し替え済みの場所をそのまま読む（本番の読み手とは別）。"""
 return join_reader(cfg)

# ---- 候補にするファイル ----------------------------------------------------
def join_candidates(cfg=None,limit=200):
 """繋ぐ相手として、まず出すべきファイルの一覧。

 いちばん確からしいのは、このアプリ自身が作ったファイル ―― 場所も形式も分かって
 いて、列も決まっている。だから登録済みの対象の出力先を先に並べ、実物があるものを
 上へ持ってくる。手で打つのは、そこに無いものを指したいときだけでよい。
 """
 c=cfg or load();items=[];seen=set()
 def add(path,**kw):
  p=Path(path)
  key=str(p).lower()
  if not str(p).strip() or key in seen:return
  seen.add(key)
  try:st=p.stat();exists=p.is_file()
  except Exception:st=None;exists=False
  items.append(dict({'path':str(p),'name':p.name,'exists':exists,
                     'size':(st.st_size if st and exists else None),
                     'mtime':(int(st.st_mtime) if st and exists else None)},**kw))
 for j in (c.get('jobs') or []):
  folder=resolve_path(j.get('output_folder') or c.get('default_output_folder'))
  # 実行のたびに名前が変わる対象（変数命名）では、いま在るファイルと次に作る名前が
  # 違う。両方出す ―― 在るほうは繋げる、次の名前は繋ぎ先として登録しておける。
  try:actual=_viewer_output_path(j,c)
  except Exception:actual=None
  if actual is not None:
   add(actual,job=j.get('name',''),job_id=j.get('id',''),
       format=normalize_output_format(j.get('output_format'),actual.name),role='primary')
  try:plan=job_output_plan(j,c)
  except Exception:plan=[]
  for x in plan:
   add(folder/x['file'],job=j.get('name',''),job_id=j.get('id',''),
       format=x['format'],role=('primary' if x.get('primary') else 'extra'))
 # ほかの結合マスタが既に使っているファイルも、確かめ済みの手がかりとして出す。
 for r in _load_join_recipes_safe():
  for s in r['sources']:
   if not s['path']:continue
   add(resolve_join_path(s['path'],c),job=r['name'],job_id='',format=s['format'],role='recipe')
 # 実物があるものが先。その中では新しい順（さっき作ったものが、たいてい繋ぎたいもの）。
 items.sort(key=lambda x:(0 if x['exists'] else 1,-(x['mtime'] or 0),x['name'].lower()))
 return items[:max(1,int(limit or 200))]

def _load_join_recipes_safe():
 try:return load_join_recipes()
 except Exception:return []
