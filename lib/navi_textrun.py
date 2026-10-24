"""読取マスタの出し入れと、手元のファイルから作る対象の実行。

切り方そのもの（位置で切る・下読み・書き出し用のJSON）は navi_text.py にある。
こちらは、それを控えDBへ出し入れし、対象1件を最後まで通す側 ―― 本体の名前を
借りるので、navi_split と同じく app.py の終わりで取り込む。

扱うのは、Navigatorへ問い合わせない3つの入力 ―― 固定長テキスト（1つのファイルを位置で
切る）と、複数ファイルの結合（キーで繋ぐ）と、クエリ（Power Query の M の式。2.4.0）。どれもRNEとの違いは
「中間CSVをどう作るか」だけで、仕上げ（変換・公開・控え・同時出力）は
finish_one_job をそのまま通す。別に書くと、片方にしか直しが入らない壊れ方を繰り返す
（v1.65.1・v1.66.0・v1.68.0で実際に起きた）。
"""
import json,time
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
           'apply_pending',
           'canonical_output_file',
           'extra_format_note',
           'finish_one_job',
           'flush_local_to_master_async',
           'init_settings_db',
           'job_extra_formats',
           'load',
           'normalize_job_source',
           'normalize_text_layout',
           'phase_log',
           'record_job_run',
           'resolve_output_filename',
           'resolve_path',
           'resolve_text_path',
           'serial_run_metrics',
           'set_status',
           'wait_for_sources',
           'settings_connection',
           'text_layout_column_types',
           'text_layout_width',
           'validate_output_contract',
           'validate_text_layout',
           'write_text_intermediate',
           'find_join_recipe',
           'join_layouts',
           'join_reader',
           'validate_join_recipe',
           'text_missing_message',
           'write_join_intermediate',
           'find_m_query',
           'validate_m_query',
           'write_m_intermediate',
           'post_note'):globals()[_n]=_borrow(_n)
del _n

def _uuid4():
 import uuid;return str(uuid.uuid4())

def _json_rows(text):
 """控えDBのJSON配列を、辞書の一覧として読む（_json_list は文字列の一覧なので使えない）。"""
 try:v=json.loads(text or '[]')
 except Exception:return []
 return [x for x in v if isinstance(x,dict)] if isinstance(v,list) else []
# 読み方（固定長／区切り）は1つの JSON の列に入れる。区切りの設定は今後も増えうるので、
# 増えるたびに列を足さずに済むようにする。
PARSE_KEYS=('mode','delimiter','delimiter_text','quote','collapse')
def _parse_of(r):
 try:v=json.loads(r['parse_json'] or '{}') if 'parse_json' in r.keys() else {}
 except Exception:v={}
 return {k:v[k] for k in PARSE_KEYS if isinstance(v,dict) and k in v}
def _layout_row(r):
 return normalize_text_layout({**_parse_of(r),'id':r['id'],'name':r['name'],'description':r['description'],
                               'encoding':r['encoding'],'unit':r['unit'],'trim':r['trim'],
                               'skip_head':r['skip_head'],'skip_tail':r['skip_tail'],
                               'skip_blank':bool(r['skip_blank']),'header_row':bool(r['header_row']),
                               'columns':_json_rows(r['columns_json']),'sample_path':r['sample_path'],
                               'updated_at':r['updated_at']})
def _load_text_layouts(c):
 try:return [_layout_row(r) for r in c.execute('SELECT * FROM text_layouts ORDER BY display_order,name')]
 except Exception:
  log.exception('TEXT_LAYOUT_LOAD_FAILED');return []
def load_text_layouts():
 init_settings_db()
 with settings_connection() as c:return _load_text_layouts(c)
def find_text_layout(layout_id):
 lid=str(layout_id or '').strip()
 if not lid:return None
 return next((x for x in load_text_layouts() if x['id']==lid),None)
def save_text_layout(layout):
 """1件を登録・更新する。idが無ければ新規。保存できない理由があれば例外。"""
 l=normalize_text_layout(layout)
 bad=validate_text_layout(l)
 if bad:raise ValueError('／'.join(bad))
 init_settings_db();lid=l['id'] or _uuid4();now=datetime.now().isoformat(timespec='seconds')
 with settings_sync_lock, settings_connection() as c:
  order=c.execute('SELECT COALESCE(MAX(display_order),-1)+1 n FROM text_layouts').fetchone()['n']
  cur=c.execute('SELECT display_order FROM text_layouts WHERE id=?',(lid,)).fetchone()
  c.execute('INSERT OR REPLACE INTO text_layouts (id,display_order,name,description,encoding,unit,trim,'
            'skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at,parse_json)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (lid,cur['display_order'] if cur else order,l['name'],l['description'],l['encoding'],l['unit'],
             l['trim'],l['skip_head'],l['skip_tail'],int(l['skip_blank']),int(l['header_row']),
             json.dumps(l['columns'],ensure_ascii=False),l['sample_path'],now,
             json.dumps({k:l[k] for k in PARSE_KEYS},ensure_ascii=False)))
  _mark_settings_dirty()
 flush_local_to_master_async('text-layout-save')
 log.info('TEXT_LAYOUT_SAVE id=%s name=%s 読み方=%s 列=%s 単位=%s 文字コード=%s 幅=%s',
          lid,l['name'],l['mode'],len(l['columns']),l['unit'],l['encoding'],text_layout_width(l))
 return dict(l,id=lid,updated_at=now)
def text_layout_usage(layout_id,cfg=None):
 """このマスタを使っている対象の名前。消してよいかの判断に要る。"""
 lid=str(layout_id or '').strip()
 if not lid:return []
 jobs=(cfg or load()).get('jobs') or []
 return [j.get('name','') for j in jobs if normalize_job_source(j.get('source'))=='text' and str(j.get('layout_id') or '')==lid]
def delete_text_layout(layout_id):
 """使っている対象があるうちは消さない。消すと、その対象は読み方を失って必ず失敗する。"""
 lid=str(layout_id or '').strip()
 used=text_layout_usage(lid)
 if used:raise ValueError('この読取マスタは'+str(len(used))+'件の対象が使っています（'+'、'.join(used[:3])+'）。先に対象側を切り替えてください')
 init_settings_db()
 with settings_sync_lock, settings_connection() as c:
  n=c.execute('DELETE FROM text_layouts WHERE id=?',(lid,)).rowcount
  _mark_settings_dirty()
 flush_local_to_master_async('text-layout-delete')
 log.info('TEXT_LAYOUT_DELETE id=%s deleted=%s',lid,n)
 return bool(n)

def process_local_job(j,cfg,work,backup,trigger,job_index,total_jobs,say=None):
 """手元のファイルから作る対象1件（固定長テキスト・結合・クエリ）を、読み取り → 変換 → 公開まで通す。

 RNEと違うのは「中間CSVの作り方」だけ。そこから先は finish_one_job にそのまま渡す。
 別に書くと、形式や公開の直しが片方にしか入らない ―― 過去に何度も起きた壊れ方なので、
 仕上げは1本のままにしておく。

 Navigatorへは一切つながない。接続も資格情報も要らないので、テキストだけを選んだ
 実行は、Navigatorの設定が無くても走る。
 """
 job_started=time.perf_counter()
 def report(stage,**kw):
  if say:say(stage,**kw)
 j['output_file']=resolve_output_filename(j,cfg)
 fmt=validate_output_contract(j,'before-local-read')
 j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb')))
 # 中間CSVはUTF-8（BOM付き）で書く。読み手の推測順はcp932が先なので、
 # 何で書いたかを対象に持たせて渡す（推測に任せると、化けたまま通ることがある）。
 j['_intermediate_encoding']='utf-8-sig'
 # 読込形式（詳細データ／集計表）はRNEの読み方。ここで作る中間CSVは必ず見出し1行なので、
 # 集計表のまま持ち込まれると見出しを1行読み飛ばして列が全部ずれる。入口で揃えておく。
 j['type']='詳細データ'
 kind=normalize_job_source(j.get('source'))
 # 使えないと分かっている取り決めで走り出さない。ここで断れば、公開先にも控えにも触らない。
 layout=recipe=query=None;src=None
 if kind=='mquery':
  query=find_m_query(j.get('query_id'))
  if not query:
   raise ValueError('クエリが選ばれていません（または削除されています）。対象の設定で、どのクエリで作るかを選んでください')
  bad=validate_m_query(query)
  if bad:raise ValueError(f'クエリ「{query["name"]}」が使えません: '+'／'.join(bad))
 elif kind=='join':
  recipe=find_join_recipe(j.get('recipe_id'))
  if not recipe:
   raise ValueError('結合マスタが選ばれていません。対象の設定で、どの繋ぎ方で作るかを選んでください')
  bad=validate_join_recipe(recipe)
  if bad:raise ValueError(f'結合マスタ「{recipe["name"]}」が使えません: '+'／'.join(bad))
 else:
  src=resolve_text_path(j,cfg)
  layout=find_text_layout(j.get('layout_id'))
  if not layout:
   raise ValueError('読取マスタが選ばれていません。対象の設定で、どの読み方で切るかを選んでください')
  bad=validate_text_layout(layout)
  if bad:raise ValueError(f'読取マスタ「{layout["name"]}」が使えません: '+'／'.join(bad))
  if not src.is_file():raise FileNotFoundError(text_missing_message(j,cfg))
  # 列の型は、読み方の側（読取マスタ）で決まり、書き出す側で使う。中間CSVは文字しか
  # 運べないので、名前で対応づけて対象に持たせて渡す（並び順で渡すと1本ずれる）。
  j['_column_types']=text_layout_column_types(layout)
 out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']);target=out_dir/j['output_file']
 apply_pending(target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),backup_mode=str(cfg['settings'].get('backup_mode','generations')))
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+f'_L{job_index}'
 local_export=work/'export';local_export.mkdir(parents=True,exist_ok=True)
 db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'
 intermediate=work/f'{kind}_{job_index}_{stamp}.csv'
 extras=job_extra_formats(j)
 zero=bool(cfg['settings']['reject_zero_rows'])
 if kind=='mquery':
  log.info('PIPELINE job=%s engine=mquery query=%s output=%s common_intermediate=CSV format=%s target=%s',
           j['name'],query['name'],j.get('query_out') or query.get('output') or '(既定)',fmt,target)
  report('read',source=query['name'],layout=j.get('query_out') or query.get('output') or '',kind='mquery')
  t=phase_log('m_query_read',job=j['name'],query=query['name'])
  rows,cols,stat=write_m_intermediate(query,cfg,intermediate,job=j,reject_zero=zero)
  # 列の型は、式の中で決めた型（Table.TransformColumnTypes）と、決めていない列は中身から（navi_mrun.column_type）
  j['_column_types']=stat['types']
  phase_log('m_query_read',t,job=j['name'],rows=rows,columns=cols,error_cells=stat['error_cells'])
 elif kind=='join':
  files=[f'{x["alias"]}:{Path(x["path"]).name}' for x in recipe['sources']]
  log.info('PIPELINE job=%s engine=join recipe=%s ファイル=%s common_intermediate=CSV format=%s target=%s',
           j['name'],recipe['name'],files,fmt,target)
  report('read',source='・'.join(files),layout=recipe['name'],kind='join')
  t=phase_log('join_read',job=j['name'],recipe=recipe['name'],sources=len(recipe['sources']))
  rows,cols,stat=write_join_intermediate(recipe,join_reader(cfg),intermediate,join_layouts(),reject_zero=zero)
  phase_log('join_read',t,job=j['name'],rows=rows,columns=cols)
 else:
  log.info('PIPELINE job=%s engine=text source=%s layout=%s common_intermediate=CSV format=%s target=%s',
           j['name'],src,layout['name'],fmt,target)
  report('read',source=src,layout=layout['name'])
  t=phase_log('text_read',job=j['name'],source=src,layout=layout['name'])
  rows,cols,stat=write_text_intermediate(src,layout,intermediate,reject_zero=zero)
  phase_log('text_read',t,job=j['name'],rows=rows,columns=cols,short_rows=stat['short_rows'],broken_cells=stat['broken_cells'])
 try:
  fin=finish_one_job(j,cfg,intermediate=intermediate,db=db,target=target,backup=backup,out_dir=out_dir,
                     local_export=local_export,stamp=stamp,expected_rows=rows,expected_cols=cols,
                     fmt=fmt,extras=extras,api_direct_output=False,job_started=job_started,report=report)
 finally:
  for p in (intermediate,db):
   try:
    if p and p.exists():p.unlink()
   except Exception:pass
 return fin,target,rows,cols,stat,fmt,extras

def local_progress_say(progress_fn,j):
 """1件の進み具合を、実行中の画面へ言葉で出す係。どの工程にいるかを日本語で。"""
 def say(stage,**kw):
  if not progress_fn:return
  if stage=='wait':
   import navi_order
   progress_fn('prepare',f'{j["name"]}: 材料がそろうのを待っています',20,current_job_id=j['id'],
               activity_detail='材料の作成待ち',activity_value=navi_order.reason_text(kw.get('reasons') or []))
  elif stage=='read':
   what={'mquery':('クエリを評価しています','Power Query'),'join':('ファイルを結合しています','ファイル結合')}.get(kw.get('kind') or '',('テキストを読み取っています','固定長テキスト'))
   progress_fn('save',f'{j["name"]}: {what[0]}',35,current_job_id=j['id'],activity_detail=what[1],activity_value=str(kw.get('source') or ''))
  elif stage=='post':progress_fn('export',f'{j["name"]}: 後処理（Power Query）で表を整えています',55,activity_detail='後処理')
  elif stage=='unchanged':progress_fn('publish',f'{j["name"]}: 前回と同じ内容のため更新しませんでした',95,activity_detail='変更なし')
  elif stage=='convert':progress_fn('export',f'{j["name"]}: 形式を変換しています',70,activity_detail='形式別変換工程')
  elif stage=='publish':progress_fn('publish',f'{j["name"]}: 検査済みファイルを公開しています',90,activity_detail='公開工程')
  elif stage=='extras':progress_fn('publish',f'{j["name"]}: 同じデータからあと{len(kw.get("extras") or [])}形式を作成しています',95,activity_detail='同時出力')
 return say

def run_one_local(j,cfg,work,backup,trigger,index,total_all,say=None):
 """手元のファイルから作る対象を1件、最後まで通す。結果は辞書で返す（例外は投げない）。

 1件ずつ順に流すときも、ラインに分けて同時に流すときも、通す道はここ1本にする ――
 別々に書くと、片方にしか直しが入らない壊れ方をまた繰り返す。
 画面の状態（どれが実行中か・完了か）は呼ぶ側が持つ。ここで書くと、同時に流したとき
 あとから書いたほうが前を消してしまう。
 """
 kind=normalize_job_source(j.get('source'))
 try:
  # 走り出す前に材料の様子を見る。作っている最中か、もうすぐ作り始めるなら待つ
  # ―― 擦れ違うと、正しい形をした「1回ぶん古いファイル」が出来上がる。
  held=wait_for_sources(j,cfg,say=say)
  fin,target,rows,cols,stat,fmt,extras=process_local_job(j,cfg,work,backup,trigger,index,total_all,say)
 except Exception as e:
  log.exception('LOCAL_JOB_FAILED job=%s kind=%s',j.get('name'),kind)
  record_job_run(j['id'],j['name'],'failed',trigger,detail=str(e))
  return {'ok':False,'job':j.get('name',''),'error':str(e),'detail':str(e),
          'job_result':{'job':j['name'],'job_id':j['id'],'status':'failed','detail':str(e)}}
 total=fin['total']
 if fin['unchanged']:
  detail=f'前回と同じ内容のため更新しませんでした / {total:.1f}秒'
 else:
  detail=(f'{fin["rows"]}件/{fin["cols"]}列 / {total:.1f}秒'
          +('' if fin['published'] else f' / 更新保留: {fin["pending"]}')+extra_format_note(fin['extra_results'])
          +post_note(fin.get('post')))
  if stat.get('error_cells'):
   detail+=f' / 誤りのセル {stat["error_cells"]}か所を空で出しました（'+'、'.join(f'{k}: {v}' for k,v in list(stat['error_samples'].items())[:2])+'）'
 metrics=serial_run_metrics(kind,fmt,total,fin['rows'],fin['cols'])
 metrics.update(published=bool(fin['published']),pending=str(fin.get('pending') or ''))
 # 内訳は入力の種類で違う。無いものを0として残すと、後から読むとき嘘になる。
 if 'short_rows' in stat:
  metrics.update(text_rows=stat['rows'],text_short_rows=stat['short_rows'],text_broken_cells=stat['broken_cells'])
 elif 'error_cells' in stat:
  metrics.update(m_query=stat['query'],m_output=stat['output'],m_error_cells=stat['error_cells'],m_elapsed=stat['elapsed'])
 elif 'joins' in stat:
  metrics.update(join_sources=len(stat['sources']),
                 join_matched=[x.get('both') for x in stat['joins']])
 if fin.get('post'):metrics.update(post=fin['post']['summary'],post_rows_in=fin['post']['rows_in'],post_error_cells=fin['post']['error_cells'])
 if held.get('waited'):metrics.update(wait_seconds=held['waited'])
 record_job_run(j['id'],j['name'],'ok',trigger,detail=detail,rows=fin['rows'],cols=fin['cols'],
                output_file=j['output_file'],metrics=metrics)
 # 何で作ったかを、作った方法どおりに残す。1.88.0まで結合でも engine=text と書いていて、
 # ログを読み返すと「テキストから作った」ようにしか見えなかった。
 log.info('JOB_RESULT job=%s engine=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s',
          j['name'],kind,fmt,fin['rows'],fin['cols'],total,target)
 return {'ok':True,'job':j['name'],'result':f'{j["name"]}: '+detail,'detail':detail,'elapsed':total,
         'job_result':{'job':j['name'],'job_id':j['id'],'status':'ok','detail':detail,'rows':fin['rows'],
                       'cols':fin['cols'],'elapsed':round(total,1),'target':str(target),
                       'published':bool(fin['published']),'pending':str(fin.get('pending') or ''),
                       'unchanged':bool(fin['unchanged'])}}
