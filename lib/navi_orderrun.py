"""結合の順番と待ち合わせに、本体の「いまの様子」を渡す係。

判断そのものは navi_order.py にある（本体の状態を見ないので、机の上で確かめられる）。
こちらは、実行中の対象・順番待ち・次の予定・出力の場所を集めて渡す側 ――
本体の名前を借りるので、navi_joinrun・navi_textrun と同じく app.py の終わりで取り込む。
"""
from datetime import datetime
from pathlib import Path
import time
import app
import navi_order
from app import log,status,cancel_requested

def _borrow(name):
 """本体の関数は、取り込んだ時点の実体ではなく、呼ばれた時点で引く。"""
 def call(*a,**k):return getattr(app,name)(*a,**k)
 call.__name__=name;call.__qualname__='app.'+name
 return call

for _n in ('_viewer_output_path',
           'dde_staging_folder',
           'find_join_recipe',
           'job_output_plan',
           'job_schedule_preview',
           'load',
           'queue_snapshot',
           'resolve_join_path',
           'resolve_path',
           'run_local_jobs',
           'set_status'):globals()[_n]=_borrow(_n)
del _n

# 結合はほかの対象が作ったファイルを材料にする。判断そのものは navi_order.py に
# 置いてあり（本体の状態を見ないので机の上で確かめられる）、ここはその判断へ
# 「いまの様子」を渡す係。

def job_output_paths(job,cfg=None):
 """この対象が作るファイルの場所。いま在るものと、次に作る名前の両方。

 実行のたびに名前が変わる対象（変数命名）では、この2つが違う。どちらで指されても
 作り手にたどり着けるよう、両方を材料の持ち主として登録しておく。
 """
 c=cfg or load();out=[]
 try:out.append(_viewer_output_path(job,c))
 except Exception:pass
 folder=resolve_path(job.get('output_folder') or c.get('default_output_folder'))
 try:
  for x in job_output_plan(job,c):out.append(folder/x['file'])
 except Exception:pass
 return [p for p in out if p]

def job_dependencies(jobs,cfg=None):
 """対象id → その材料を作る対象idの集合。"""
 c=cfg or load()
 return navi_order.dependencies(jobs,c,find_join_recipe,
                                lambda s:resolve_join_path(s.get('path'),c),
                                lambda j:job_output_paths(j,c))

def order_jobs_by_dependency(jobs,cfg=None):
 """材料を作る側が先に来るように並べ替える。中身は増やさない。"""
 c=cfg or load()
 deps=job_dependencies(jobs,c)
 ordered=navi_order.order_jobs(jobs,deps)
 if [j['id'] for j in ordered]!=[j['id'] for j in jobs]:
  log.info('JOB_ORDER 並べ替えました %s → %s',[j['name'] for j in jobs],[j['name'] for j in ordered])
 return ordered,deps

def job_wait_reasons(job,cfg=None,now=None,deps=None):
 """いま走ってよいか。待つ理由の一覧（空なら走ってよい）。"""
 c=cfg or load();now=now or datetime.now()
 opt=navi_order.wait_settings(c)
 if not opt['enabled']:return []
 deps=deps if deps is not None else job_dependencies(c.get('jobs') or [],c)
 snap=queue_snapshot()
 queued=set()
 snap_running=any(str(x.get('state') or '')=='running' for x in (snap.get('items') or []))
 for item in snap.get('items') or []:
  # いま走っている実行のなかの順番は、ライン側（navi_lane）が見ている。ここで同じ実行の
  # 対象まで「まだ順番待ち」と数えると、自分と同じ実行に入っている材料を待ち続け、
  # 待ちきれなくなるまで（既定10分）画面が止まったように見える ―― v1.88.0まで実際に
  # そうなっていた。材料と結合を一緒に選んで実行すると、必ずこれを踏んだ。
  if str(item.get('state') or '')=='running':continue
  # 実行は1件ずつしか走らない。すでに1件走っている＝いま材料を待っているのがその
  # 実行なのだから、キューに積まれた指令はこちらが終わるまで絶対に始まらない。
  # それを「順番待ち」と数えると、来ない材料を既定10分待ち、結局そのまま実行する
  # ことになる（その間アプリ全体が止まる）。走っているものがあるなら後ろは待たない。
  if snap_running:continue
  for i in (item.get('job_ids') or []):queued.add(i)
 running=set(status.get('queue_running_ids') or [])
 names={j['id']:j.get('name','') for j in (c.get('jobs') or [])}
 def next_run_of(job_id):
  j=next((x for x in (c.get('jobs') or []) if x['id']==job_id),None)
  if not j:return None
  nxt=job_schedule_preview(j,now).get('next_run')
  try:return datetime.fromisoformat(nxt) if nxt else None
  except Exception:return None
 inputs=navi_order.job_inputs(job,c,find_join_recipe,lambda s:resolve_join_path(s.get('path'),c))
 return navi_order.wait_reasons(job,c,now,deps=deps,running_ids=running-{job['id']},
                                queued_ids=queued-{job['id']},next_run_of=next_run_of,inputs=inputs,
                                lookahead_seconds=opt['lookahead'],name_of=lambda i:names.get(i,i))

def wait_for_sources(job,cfg=None,deps=None,say=None):
 """材料がそろうまで待つ。待った秒数と、最後まで残った理由を返す。

 待ちきれなくなったら走る ―― 止め続けるより、古いかもしれないと言って出すほうが
 直しようがある。差し替えは一瞬（os.replace）なので、途中の壊れたファイルは読まない。
 """
 c=cfg or load();opt=navi_order.wait_settings(c)
 if not opt['enabled']:return {'waited':0.0,'reasons':[],'timed_out':False}
 started=time.perf_counter();last=[]
 while True:
  reasons=job_wait_reasons(job,c,datetime.now(),deps)
  if not reasons:
   waited=time.perf_counter()-started
   if waited>=1:log.info('JOIN_WAIT_DONE job=%s 待った時間=%.0f秒 待った理由=%s',
                         job.get('name'),waited,navi_order.reason_text(last))
   return {'waited':round(waited,1),'reasons':[],'timed_out':False}
  waited=time.perf_counter()-started
  if waited>=opt['max_wait']:
   log.warning('JOIN_WAIT_TIMEOUT job=%s 待った時間=%.0f秒 まだ%s。'
               'これ以上は待たずに実行します（材料が1回ぶん古いかもしれません）',
               job.get('name'),waited,navi_order.reason_text(reasons))
   return {'waited':round(waited,1),'reasons':reasons,'timed_out':True}
  if navi_order.reason_text(reasons)!=navi_order.reason_text(last):
   log.info('JOIN_WAIT job=%s 待っています: %s（最大%s秒）',
            job.get('name'),navi_order.reason_text(reasons),opt['max_wait'])
   if say:say('wait',reasons=reasons)
  last=reasons
  cancel_requested.wait(opt['poll'])
  if cancel_requested.is_set():
   return {'waited':round(time.perf_counter()-started,1),'reasons':reasons,'timed_out':False}

def run_deferred_local(after_api,cfg,trigger,progress,total_all,seed_results):
 """材料をNavigator側の対象が作る結合を、そのあとで走らせる。

 先に走らせると、まだ作られていないファイルを繋ぐことになる。出来上がりは正しい形を
 しているので、中身が古いことに誰も気づかない ―― だから順番のほうを直す。
 """
 if not after_api:return [],[]
 log.info('LOCAL_AFTER_API_RUN jobs=%s',[j['name'] for j in after_api])
 _work=dde_staging_folder();_backup=resolve_path(cfg['backup_folder'])
 res,fails,job_res=run_local_jobs(after_api,cfg,_work,_backup,trigger,progress,
                                  max(0,total_all-len(after_api)),total_all)
 if fails:
  set_status(job_errors=[{'job':r.get('job'),'error':str(r.get('error') or '')} for r in fails],
             failed_jobs=len(fails))
  raise RuntimeError('材料の作成後の結合で%d件失敗しました\n'%len(fails)
                     +'\n'.join('・%s: %s'%(r.get('job'),r.get('error')) for r in fails))
 return res,job_res


def split_batch(jobs,cfg):
 """実行する対象を、流す順に振り分ける。(並べ替えた全体, 材料が要らない手元のもの, RNE, 材料がRNEのもの)

 手元のファイルから作る対象（固定長テキスト・結合）はNavigatorへ問い合わせないので、
 RNEと同時に流せる。ただし材料をRNE側が作る結合だけは、その材料ができるまで走れない
 ―― 先に走らせると、まだ作られていないファイルを繋ぐことになる。出来上がりは正しい形を
 しているので、中身が古いことに誰も気づかない。

 どちらも「手元のもの」であることに変わりはないので、API方式では navi_lanerun が
 まとめて受け取り、材料がそろった順に流す。DDE方式（1つの画面を操作する方式）だけが
 前半・後半の二段構えで走る。
 """
 ordered,deps=order_jobs_by_dependency(jobs,cfg)
 kind=lambda j:app.normalize_job_source(j.get('source'))
 api=[j for j in ordered if kind(j)=='rne']
 api_ids={j['id'] for j in api}
 local=[j for j in ordered if kind(j) in ('text','join')]
 first=[j for j in local if not (deps.get(j['id']) or set())&api_ids]
 later=[j for j in local if (deps.get(j['id']) or set())&api_ids]
 if later:
  log.info('LOCAL_AFTER_API jobs=%s（材料をNavigator側の対象が作るため、その材料ができてから実行します）',
           [j['name'] for j in later])
 return ordered,first,api,later
