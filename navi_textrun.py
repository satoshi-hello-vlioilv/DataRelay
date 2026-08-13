"""読取マスタの出し入れと、固定長テキストの実行。

切り方そのもの（位置で切る・下読み・書き出し用のJSON）は navi_text.py にある。
こちらは、それを控えDBへ出し入れし、対象1件を最後まで通す側 ―― 本体の名前を
借りるので、navi_split と同じく app.py の終わりで取り込む。

RNEとの違いは「中間CSVをどう作るか」だけ。仕上げ（変換・公開・控え・同時出力）は
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
           'settings_connection',
           'text_layout_width',
           'validate_output_contract',
           'validate_text_layout',
           'write_text_intermediate'):globals()[_n]=_borrow(_n)
del _n

def _uuid4():
 import uuid;return str(uuid.uuid4())

def _json_rows(text):
 """控えDBのJSON配列を、辞書の一覧として読む（_json_list は文字列の一覧なので使えない）。"""
 try:v=json.loads(text or '[]')
 except Exception:return []
 return [x for x in v if isinstance(x,dict)] if isinstance(v,list) else []
def _layout_row(r):
 return normalize_text_layout({'id':r['id'],'name':r['name'],'description':r['description'],
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
            'skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (lid,cur['display_order'] if cur else order,l['name'],l['description'],l['encoding'],l['unit'],
             l['trim'],l['skip_head'],l['skip_tail'],int(l['skip_blank']),int(l['header_row']),
             json.dumps(l['columns'],ensure_ascii=False),l['sample_path'],now))
  _mark_settings_dirty()
 flush_local_to_master_async('text-layout-save')
 log.info('TEXT_LAYOUT_SAVE id=%s name=%s 列=%s 単位=%s 文字コード=%s 幅=%s',
          lid,l['name'],len(l['columns']),l['unit'],l['encoding'],text_layout_width(l))
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

def process_text_job(j,cfg,work,backup,trigger,job_index,total_jobs,say=None):
 """固定長テキスト1件を、読み取り → 変換 → 公開まで通す。

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
 fmt=validate_output_contract(j,'before-text-read')
 j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb')))
 # 中間CSVはUTF-8（BOM付き）で書く。読み手の推測順はcp932が先なので、
 # 何で書いたかを対象に持たせて渡す（推測に任せると、化けたまま通ることがある）。
 j['_intermediate_encoding']='utf-8-sig'
 src=resolve_text_path(j,cfg)
 layout=find_text_layout(j.get('layout_id'))
 if not layout:
  raise ValueError('読取マスタが選ばれていません。対象の設定で、どの読み方で切るかを選んでください')
 bad=validate_text_layout(layout)
 if bad:raise ValueError(f'読取マスタ「{layout["name"]}」が使えません: '+'／'.join(bad))
 if not src.is_file():raise FileNotFoundError('テキストファイルがありません: '+str(src))
 out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']);target=out_dir/j['output_file']
 apply_pending(target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations')))
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+f'_T{job_index}'
 local_export=work/'export';local_export.mkdir(parents=True,exist_ok=True)
 db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'
 intermediate=work/f'text_{job_index}_{stamp}.csv'
 extras=job_extra_formats(j)
 log.info('PIPELINE job=%s engine=text source=%s layout=%s common_intermediate=CSV format=%s target=%s',
          j['name'],src,layout['name'],fmt,target)
 report('read',source=src,layout=layout['name'])
 t=phase_log('text_read',job=j['name'],source=src,layout=layout['name'])
 rows,cols,stat=write_text_intermediate(src,layout,intermediate,reject_zero=bool(cfg['settings']['reject_zero_rows']))
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

def run_text_jobs(jobs,cfg,work,backup,trigger,progress_fn=None,offset=0,total_all=0):
 """固定長テキストの対象をまとめて片付ける。(結果の文, 失敗, 一覧用の結果) を返す。

 1件ずつ順に処理する。読むのは手元のファイルで、待たされるのは変換と公開だけなので、
 ラインを分けても得にならない（分けるほど公開先の取り合いが増える）。
 """
 results=[];failures=[];job_results=[];completed_ids=[]
 total_all=total_all or len(jobs)
 for n,j in enumerate(jobs,1):
  index=offset+n
  set_status(current=j['name'],current_job_id=j['id'],current_job_name=j['name'],current_index=index,
             queue_running_ids=[j['id']])
  def say(stage,**kw):
   if not progress_fn:return
   if stage=='read':progress_fn('save',f'{j["name"]}: テキストを読み取っています',35,current_job_id=j['id'],activity_detail='固定長テキスト',activity_value=str(kw.get('source') or ''))
   elif stage=='unchanged':progress_fn('publish',f'{j["name"]}: 前回と同じ内容のため更新しませんでした',95,activity_detail='変更なし')
   elif stage=='convert':progress_fn('export',f'{j["name"]}: 形式を変換しています',70,activity_detail='形式別変換工程')
   elif stage=='publish':progress_fn('publish',f'{j["name"]}: 検査済みファイルを公開しています',90,activity_detail='公開工程')
   elif stage=='extras':progress_fn('publish',f'{j["name"]}: 同じデータからあと{len(kw.get("extras") or [])}形式を作成しています',95,activity_detail='同時出力')
  try:
   fin,target,rows,cols,stat,fmt,extras=process_text_job(j,cfg,work,backup,trigger,index,total_all,say)
  except Exception as e:
   log.exception('TEXT_JOB_FAILED job=%s',j.get('name'))
   failures.append({'job':j.get('name'),'error':str(e)})
   record_job_run(j['id'],j['name'],'failed',trigger,detail=str(e))
   job_results.append({'job':j['name'],'job_id':j['id'],'status':'failed','detail':str(e)})
   set_status(queue_failed_ids=list(dict.fromkeys(list(app.status.get('queue_failed_ids') or [])+[j['id']])),
              queue_running_ids=[],job_results=list((app.status.get('job_results') or [])+job_results[-1:]))
   continue
  total=fin['total']
  if fin['unchanged']:
   detail=f'前回と同じ内容のため更新しませんでした / {total:.1f}秒'
  else:
   detail=(f'{fin["rows"]}件/{fin["cols"]}列 / {total:.1f}秒'
           +('' if fin['published'] else f' / 更新保留: {fin["pending"]}')+extra_format_note(fin['extra_results']))
  results.append(f'{j["name"]}: '+detail);completed_ids.append(j['id'])
  metrics=serial_run_metrics('text',fmt,total,fin['rows'],fin['cols'])
  metrics.update(published=bool(fin['published']),pending=str(fin.get('pending') or ''),
                 text_rows=stat['rows'],text_short_rows=stat['short_rows'],text_broken_cells=stat['broken_cells'])
  record_job_run(j['id'],j['name'],'ok',trigger,detail=detail,rows=fin['rows'],cols=fin['cols'],
                 output_file=j['output_file'],metrics=metrics)
  job_results.append({'job':j['name'],'job_id':j['id'],'status':'ok','detail':detail,'rows':fin['rows'],
                      'cols':fin['cols'],'elapsed':round(total,1),'target':str(target),
                      'published':bool(fin['published']),'pending':str(fin.get('pending') or ''),
                      'unchanged':bool(fin['unchanged'])})
  set_status(completed_jobs=index,queue_completed_ids=list(completed_ids),queue_running_ids=[],
             job_results=list((app.status.get('job_results') or [])[:offset]+job_results))
  log.info('JOB_RESULT job=%s engine=text format=%s rows=%s columns=%s elapsed=%.2fs target=%s',
           j['name'],fmt,fin['rows'],fin['cols'],total,target)
  if app.cancel_requested.is_set():break
 return results,failures,job_results
