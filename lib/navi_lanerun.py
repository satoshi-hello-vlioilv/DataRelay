"""ラインを流す係 ―― RNEと手元の処理を同時に走らせる。

どれを先に流すかの判断は navi_lane.py にある（時計もスレッドも触らないので、机の上で
確かめられる）。こちらはその判断に従って、実際にワーカーを起こし、スレッドを回し、
画面へ様子を出す側。本体の名前を借りるので、navi_orderrun・navi_textrun と同じく
app.py の終わりで取り込む。

1.88.0まで、実行はこう並んでいた。

    テキスト・結合を1件ずつ全部 → そのあとRNEを並列で → 残った結合を1件ずつ

テキストを読んでいるあいだ、RNEのラインは6本とも空のまま待っていた。逆にRNEが
走っているあいだ、手元の処理は1件も進まなかった。待つ相手が違う（片方はNavigatorの
応答、片方は共有フォルダーの読み書き）のに、順番に並べていたぶんがそのまま所要時間に
乗っていた。

いまは1枚の黒板（LaneBoard）を2つの流れで共有する。RNEは独立プロセス、手元の処理は
スレッド ―― 走らせ方は違うが、「終わった」「失敗した」を書き込む先は同じ。結合は
その黒板を見て、材料がそろってから走り出す。
"""
import json,os,shutil,subprocess,sys,threading,time,uuid
from collections import deque
from datetime import datetime
from pathlib import Path
import app
import navi_lane
import navi_order
from app import BASE,log,status,cancel_requested,active_workers,active_workers_lock

def _borrow(name):
 """本体の関数は、取り込んだ時点の実体ではなく、呼ばれた時点で引く。"""
 def call(*a,**k):return getattr(app,name)(*a,**k)
 call.__name__=name;call.__qualname__='app.'+name
 return call

for _n in ('dde_staging_folder',
           'job_dependencies',
           'load_job_runs',
           'normalize_job_source',
           'record_job_run',
           'record_rne_run',
           'resolve_path',
           'run_one_local',
           'save_column_cache',
           'save_rne_timing',
           'set_status',
           'update_parallel_line'):globals()[_n]=_borrow(_n)
del _n

# 手元の処理が、いまどのあたりにいるか。ラインの帯に出す目安。
LOCAL_STAGE={'wait':(15,'材料待ち'),'read':(35,'読み取り'),'convert':(70,'変換'),
             'publish':(90,'公開'),'extras':(95,'同時出力'),'unchanged':(95,'変更なし')}


def relay_worker_line(line,job,worker_status,elapsed,pid=0):
 """ワーカーが書いた状態を、そのまま画面のラインへ渡す。

 決め打ちで項目を拾い直さないこと。以前ここで列挙していたため、あとから増えた項目
 （工程の点=phase、実測かどうか=measured）が画面まで届かず、点が光らなかった。
 親が決めるのは所要時間と対象IDだけで、あとはワーカーの言うとおりにする。
 """
 relay={k:v for k,v in (worker_status or {}).items() if k not in ('line','elapsed','updated_at','job_id')}
 relay.setdefault('state','処理中');relay.setdefault('percent',0);relay.setdefault('detail','')
 relay['job']=relay.get('job') or (job or {}).get('name','')
 if pid:relay.setdefault('pid',pid)
 update_parallel_line(line,job_id=(job or {}).get('id',''),elapsed=elapsed,**relay)
 return relay

def _read_worker_json(path,default=None):
 try:return json.loads(Path(path).read_text(encoding='utf-8'))
 except Exception:return default


class LaneBoard:
 """ラインの黒板。RNE側（別プロセス）と手元側（スレッド）が、同じ1枚に書き込む。

 実行中・完了・失敗の一覧は画面がそのまま読む。2つの流れが別々に set_status すると
 あとから書いたほうが前を消してしまう（片方の行だけ「順番待ち」に戻る）ので、
 書き込み口をここ1つに絞る。
 """
 def __init__(self,plan,api_lines,local_lines,trigger=''):
  self.cond=threading.Condition()
  self.plan=plan;self.trigger=trigger
  self.api_lines=max(0,int(api_lines or 0));self.local_lines=max(0,int(local_lines or 0))
  self.total=len(plan)
  self.done=[];self.failed=[];self.started=set();self.running={}
  self.results=[];self.failures=[];self.job_results=[]
  self.api_open=any(e['kind']=='rne' for e in plan)
  self.api_note={}          # RNE側が出す全体の様子。そのまま画面へ渡す。
  self.skipped=[]

 # ---- 取り出す ------------------------------------------------------------
 def begin(self):
  """走り出す前に、ラインの札を全部並べる。空きも「開始待ち」として見せる。"""
  lines=[]
  for n in range(1,self.api_lines+1):
   lines.append({'line':f'ライン {n}','job':'','state':'待機','percent':0,'elapsed':0,'detail':'開始待ち','slot':n})
  for n in range(1,self.local_lines+1):
   slot=self.api_lines+n
   lines.append({'line':f'ライン {slot}','job':'','state':'待機','percent':0,'elapsed':0,
                 'detail':'手元のファイルから作ります','slot':slot})
  set_status(parallel_lines=lines,parallel_max_lines=len(lines),parallel_mode=True,
             symnavi_window=f'独立プロセス {self.api_lines}ライン／手元 {self.local_lines}ライン'
                            if self.api_lines else f'手元 {self.local_lines}ライン')
  self.publish()

 def claim(self,kinds=navi_lane.LOCAL_KINDS):
  """次に流してよいものを1件取る。無ければ、出てくるまで待つ。終わりなら None。

  材料が失敗した対象は、ここで見つけて先に落とす ―― 来ない材料を待たせ続けると、
  ラインが1本ふさがったまま、誰も何も言わずに実行が終わる。
  """
  with self.cond:
   while True:
    if cancel_requested.is_set():return None
    if self._drop_unreachable_locked(kinds):continue
    ready=navi_lane.ready(self.plan,self.done,self.started,kinds)
    if ready:
     e=ready[0];self.started.add(e['id']);self.running[e['id']]=e['name']
     self._publish_locked();return e
    pending=[x for x in self.plan if x['kind'] in kinds and x['id'] not in self.started]
    if not pending:return None
    # まだ走れないが、動いているものがある（RNEの並列か、ほかのライン）。
    # どちらも止まっているなら、これ以上待っても何も変わらない。
    inflight=len(self.started-set(self.done)-set(self.failed))
    if not self.api_open and inflight<=0:
     self._break_cycle_locked(pending);continue
    self.cond.wait(0.5)

 def _drop_unreachable_locked(self,kinds):
  """材料が失敗したので、もう走れないもの。待たせずに、理由を付けて落とす。"""
  out=navi_lane.unreachable(self.plan,self.failed,self.done)
  hit=False
  for e in out:
   if e['id'] in self.started or e['kind'] not in kinds:continue
   # 名指しするのは、実際に失敗した材料だけ。まだ走っている材料まで並べると、
   # 読んだ人はそちらを直しに行ってしまう。
   culprits=navi_lane.names_of(e['needs']&set(self.failed),self.plan) or ['材料']
   why='材料の'+'・'.join(culprits)+'が失敗したため実行しませんでした'
   self.started.add(e['id']);hit=True
   self._fail_locked(e,why,skipped=True)
  return hit

 def _break_cycle_locked(self,pending):
  """誰も動いていないのに材料がそろわない ―― 互いに材料にし合っている（輪）。

  ここで全部落とすと1件も走らない。走らせないより、順番が決まらないと断ったうえで
  走らせるほうがよい（navi_order.order_jobs と同じ判断）。いちばん前の1件だけ
  待ち合わせを解き、あとは同じ手順で回す ―― これで必ず1件は進む。
  """
  e=sorted(pending,key=lambda x:(x['tier'],x['order']))[0]
  log.warning('LANE_CYCLE job=%s 材料=%s の順番を決められないので、登録順のまま実行します',
              e['name'],'・'.join(navi_lane.blocking_names(e,self.plan,self.done)))
  e['needs']=set()

 def _fail_locked(self,entry,why,skipped=False):
  self.failed.append(entry['id']);self.running.pop(entry['id'],None)
  self.failures.append({'ok':False,'job':entry['name'],'error':why})
  self.job_results.append({'job':entry['name'],'job_id':entry['id'],'status':'failed','detail':why})
  if skipped:self.skipped.append(entry['name'])
  record_job_run(entry['id'],entry['name'],'failed',self.trigger,detail=why)
  self._publish_locked();self.cond.notify_all()

 # ---- 書き込む ------------------------------------------------------------
 def note_running(self,job_id,name):
  """走り出した。RNE側は黒板から取るのではなく自分で配るので、始まりを教えてもらう。"""
  with self.cond:
   self.started.add(job_id);self.running[job_id]=name
   self._publish_locked();self.cond.notify_all()

 def note(self,job_id,name,ok,*,result_text='',job_result=None,error=''):
  """1件終わったことを黒板へ。ここを通ったものだけが「済んだ」と数えられる。"""
  with self.cond:
   self.running.pop(job_id,None)
   if ok:
    self.done.append(job_id)
    if result_text:self.results.append(result_text)
   else:
    self.failed.append(job_id);self.failures.append({'ok':False,'job':name,'error':str(error or '')})
   if job_result:self.job_results.append(job_result)
   self._publish_locked();self.cond.notify_all()

 def api_closed(self,job_ids,reason=''):
  """RNE側が終わった。名乗り出なかったものは失敗として締める（待たせ続けない）。

  ここを通さないと、材料をRNEが作る結合は永遠に順番待ちのまま残る ―― RNE側が
  途中で落ちたときこそ必要になるので、必ず finally から呼ぶ。
  """
  with self.cond:
   self.api_open=False
   seen=set(self.done)|set(self.failed)
   for e in self.plan:
    if e['kind']!='rne' or e['id'] in seen or e['id'] not in set(job_ids or ()):continue
    self.failed.append(e['id']);self.running.pop(e['id'],None)
    self.failures.append({'ok':False,'job':e['name'],'error':reason or '結果が返りませんでした'})
   self._publish_locked();self.cond.notify_all()

 def api_tick(self,**note):
  """RNE側の全体の様子（実行中/待機/完了）。画面の文言はそのまま使う。"""
  with self.cond:
   self.api_note=dict(note);self._publish_locked()

 def seed(self,batch_results):
  """RNE側が持っている一覧に、手元の処理のぶんを足して返す。"""
  with self.cond:return list(self.job_results)+list(batch_results)

 # ---- 画面へ --------------------------------------------------------------
 def publish(self,**extra):
  with self.cond:self._publish_locked(**extra)

 def _publish_locked(self,**extra):
  done=list(dict.fromkeys(self.done));failed=list(dict.fromkeys(self.failed))
  settled=set(done)|set(failed)
  running=list(self.running)
  waiting=[e['id'] for e in self.plan if e['id'] not in settled and e['id'] not in self.running]
  v={'queue_total':self.total,'queue_waiting':len(waiting),'queue_active':len(running),
     'queue_completed':len(settled),'queue_completed_ids':done,'queue_failed_ids':failed,
     'queue_running_ids':running,'queue_waiting_ids':waiting,
     'completed_jobs':len(settled),'failed_jobs':len(failed),
     'current_index':min(len(settled)+len(running),self.total) or 1,
     'job_results':list(self.job_results),
     'job_errors':[{'job':x.get('job'),'error':str(x.get('error') or '')} for x in self.failures],
     'step':'save','step_percent':round(100*len(settled)/max(1,self.total)),
     'step_label':f'実行 {len(running)}・待機 {len(waiting)}・完了 {len(settled)}／{self.total}',
     'current_job_name':'・'.join(list(self.running.values())[:3]) or '順番待ち',
     'activity_detail':self.api_note.get('activity_detail') or f'{self.api_lines+self.local_lines}ラインで処理',
     'activity_value':f'実行 {len(running)} / 待機 {len(waiting)} / 完了 {len(settled)}/{self.total}'}
  v.update(extra);set_status(**v)


# ---- RNE側（独立プロセス） ---------------------------------------------------
def run_api_process_batch(jobs,cfg,user,pw,server,dde_work,backup,max_lines,trigger,seed_results=None,board=None):
 """Run each Navigator API session in an isolated Python process.
 Finished lines immediately pull the next queued query until the reservation queue is empty.
 """
 batch_id=datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8]
 runtime=dde_work/'parallel_runtime'/('parallel_'+batch_id);runtime.mkdir(parents=True,exist_ok=True)
 # 重い対象から先に流す。バッチ全体の所要は一番重い対象で決まるため、それを最初に走らせないと
 # 後ろに回った分だけ全体が延びる。規模は前回実績の 行数×列数 を目安にする（実績が無い対象は
 # 大きさが読めないので先に始める）。並列実行では対象の順序自体に意味は無い。
 if len(jobs)>1:
  runs=load_job_runs()
  def _estimated_cells(job):
   run=runs.get(job.get('id')) or {}
   try:cells=int(run.get('rows') or 0)*int(run.get('cols') or 0)
   except Exception:cells=0
   return cells if cells>0 else float('inf')
  jobs=sorted(jobs,key=_estimated_cells,reverse=True)
  log.info('BATCH_ORDER strategy=heaviest_first order=%s',[(j['name'],'不明' if _estimated_cells(j)==float('inf') else int(_estimated_cells(j))) for j in jobs])
 queue=deque(enumerate(jobs,1));active={};results=[];failures=[];completed=0
 # 同じ実行で先に片付けたぶん（固定長テキスト）。一覧から消さないよう、先頭に置いておく。
 seed_list=list(seed_results or [])
 seed=board.seed if board else (lambda b:seed_list+list(b))
 # 各対象(ジョブ)の実状態を job_id 単位で保持し、完了後に「待機」へ戻る不具合を防ぐ。
 completed_ids=[];failed_ids=[];all_job_ids=[j['id'] for j in jobs]
 with active_workers_lock:active_workers.clear()
 batch_started=time.perf_counter(); total=len(jobs); configured_lines=max(1,int(max_lines)); max_lines=max(1,min(int(max_lines),total)); batch_results=[]
 # 列分割は同時プロセスを増やす。設定した並列数を超えないよう、1対象あたりの持ち分を先に決める。
 # 対象がラインを埋め切っているときは持ち分が1になり、分割は行われない。
 split_budget=max(1,configured_lines//total)
 log.info('SPLIT_BUDGET configured_lines=%s jobs=%s per_job=%s',configured_lines,total,split_budget)
 for _j in jobs:_j['_split_budget']=split_budget
 if board is None:
  set_status(parallel_lines=[{'line':f'ライン {n}','job':'','state':'待機','percent':0,'elapsed':0,'detail':'開始待ち','slot':n} for n in range(1,max_lines+1)],queue_total=total,queue_waiting=total,queue_active=0,queue_completed=0,queue_completed_ids=[],queue_failed_ids=[],queue_running_ids=[],queue_waiting_ids=list(all_job_ids),parallel_max_lines=max_lines,parallel_mode=True,symnavi_window=f'独立プロセス {max_lines}ライン')
 log.info('PARALLEL_BATCH_START model=process-isolated trigger=%s batch_id=%s runtime=%s jobs=%s max_lines=%s total_jobs=%s parent_pid=%s',trigger,batch_id,runtime,[j['rne'] for j in jobs],max_lines,total,os.getpid())
 def start_one(slot):
  index,job=queue.popleft();line=f'ライン {slot}'
  job_dir=runtime/f'line_{slot}_{index}';job_dir.mkdir(parents=True,exist_ok=True)
  payload={'job':job,'job_index':index,'total_jobs':total,'cfg':cfg,'user':user,'password':pw,'server':server,'dde_work':str(job_dir/'work'),'backup':str(backup),'line':line}
  Path(payload['dde_work']).mkdir(parents=True,exist_ok=True)
  payload_path=job_dir/'payload.json';result_path=job_dir/'result.json';status_path=job_dir/'status.json'
  payload_path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
  env=os.environ.copy();env['NAVI_WORKER_LINE']=line;env['NAVI_WORKER_STATUS']=str(status_path);env['NAVI_WORKER_RESULT']=str(result_path);env['NAVI_WORKER_SPAWN_AT']=repr(time.time())
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  proc=subprocess.Popen([sys.executable,str(BASE/'lib'/'api_worker.py'),str(payload_path)],cwd=str(BASE),env=env,creationflags=flags)
  active[slot]={'proc':proc,'job':job,'index':index,'line':line,'status':status_path,'result':result_path,'started':time.perf_counter()}
  with active_workers_lock:active_workers[slot]=proc
  if board:board.note_running(job['id'],job['name'])
  update_parallel_line(line,job=job['name'],job_id=job['id'],state='起動',percent=2,detail=f'予約 {index}/{total} / PID {proc.pid}',queue_index=index,slot=slot,started_at=datetime.now().isoformat(timespec='seconds'))
  log.info('WORKER_START batch_id=%s line=%s pid=%s job=%s queue_index=%s/%s',batch_id,line,proc.pid,job['name'],index,total)
 # ワーカーを一斉に起動すると、Navigator APIのセッション接続が競合して1本あたりの接続時間が
 # 数倍に伸びる（実測: 単独 約1.0秒 / 6本同時 2.3〜7.2秒）。少しずつずらして接続を重ねない。
 # 一番重い対象が先頭なので、遅れて起動する軽い対象は全体所要に影響しない。
 stagger=max(0,int(cfg['settings'].get('api_worker_stagger_ms',700) or 0))/1000.0
 for slot in range(1,max_lines+1):
  if not queue:break
  if slot>1 and stagger>0 and cancel_requested.wait(stagger):break
  start_one(slot)
 while active:
  if cancel_requested.is_set():
   log.info('PARALLEL_BATCH_CANCELLED batch_id=%s active=%s queued=%s',batch_id,len(active),len(queue))
   queue.clear()
   for slot,item in list(active.items()):
    try:item['proc'].terminate()
    except Exception:pass
   for slot,item in list(active.items()):
    try:item['proc'].wait(timeout=5)
    except Exception:
     try:item['proc'].kill()
     except Exception:pass
    failures.append({'ok':False,'job':item['job']['name'],'error':'ユーザーにより中断されました','elapsed':time.perf_counter()-item['started']})
    failed_ids.append(item['job']['id'])
    record_job_run(item['job']['id'],item['job']['name'],'cancelled',trigger,detail='ユーザーにより中断されました')
    if board:board.note(item['job']['id'],item['job']['name'],False,error='ユーザーにより中断されました')
    update_parallel_line(item['line'],job=item['job']['name'],job_id=item['job']['id'],state='中断',percent=100,detail='ユーザーにより中断されました',elapsed=round(time.perf_counter()-item['started'],1))
    with active_workers_lock:active_workers.pop(slot,None)
    del active[slot]
   break
  for slot,item in list(active.items()):
   worker_status=_read_worker_json(item['status'])
   if worker_status:
    relay_worker_line(item['line'],item['job'],worker_status,
                      round(time.perf_counter()-item['started'],1),item['proc'].pid)
   rc=item['proc'].poll()
   if rc is None:continue
   result=_read_worker_json(item['result'],{'ok':False,'job':item['job']['name'],'error':f'Worker終了コード {rc}','elapsed':time.perf_counter()-item['started']})
   completed+=1
   (results if result.get('ok') else failures).append(result)
   (completed_ids if result.get('ok') else failed_ids).append(item['job']['id'])
   log.info('WORKER_END batch_id=%s line=%s pid=%s job=%s returncode=%s ok=%s elapsed=%.2fs',batch_id,item['line'],item['proc'].pid,item['job']['name'],rc,result.get('ok'),result.get('elapsed',0))
   one={'job':item['job']['name'],'job_id':item['job']['id'],'status':'ok' if result.get('ok') else 'failed',
        'detail':str(result.get('result') or result.get('error') or ''),'rows':result.get('rows'),'cols':result.get('columns'),
        'elapsed':round(float(result.get('elapsed') or 0),1),'target':str(result.get('target') or ''),
        'published':bool(result.get('published',True)),'pending':str(result.get('pending') or '')}
   batch_results.append(one)
   if board:
    # 材料をこの対象が作る結合は、この1件が済んだ時点で走り出してよい。
    # バッチ全部の終わりまで待たせると、そのぶんラインが空く。
    board.note(item['job']['id'],item['job']['name'],bool(result.get('ok')),
               result_text=str(result.get('result') or ''),error=str(result.get('error') or ''))
   else:
    set_status(job_results=seed(batch_results))
   record_job_run(item['job']['id'],item['job']['name'],'ok' if result.get('ok') else 'failed',trigger,detail=(result.get('result') or result.get('error') or ''),rows=result.get('rows'),cols=result.get('columns'),output_file=Path(result.get('target') or '').name,
                  metrics={**{k:result.get(k) for k in ('elapsed','execute_seconds','save_seconds','merge_seconds','transfer_bytes','transfer_kbs','split_parts','split_shape','split_how','row_axis','axis_seconds','race_winner','format') if result.get(k) is not None},
                           # 公開できたか。鮮度の判定がこれを見る（実行できても差し替わっていない場合がある）
                           'published':bool(result.get('published',True)),'pending':str(result.get('pending') or ''),
                           # 差し替えられなかったなら、その理由と、粘った時間と、次にすること。
                           # 「使用中でした」だけでは、画面を見た人は何をすればよいのか分からない。
                           'hold_reason':str(result.get('hold_reason') or ''),
                           'hold_waited':result.get('hold_waited'),'hold_attempts':result.get('hold_attempts'),
                           'hold_advice':list(result.get('hold_advice') or [])})
   # RNE単位の実績。時間帯・端末・分け方まで残し、あとから条件別に見比べられるようにする。
   if result.get('rne_path'):
    record_rne_run(result['rne_path'],item['job'],'ok' if result.get('ok') else 'failed',trigger,
                   dict(result,rows=result.get('rows'),cols=result.get('columns'),lines=max_lines),engine='api')
   # ワーカーが持ち帰った列名をここで保存する。設定DBへの書き込みを親1本に集約して競合を避ける。
   if result.get('ok') and result.get('column_names'):
    save_column_cache(result.get('rne_path') or '',result['column_names'],rows=result.get('rows'),source='run',job=item['job'])
   # 所要時間の基準は「分割なし1本」の値でなければ意味がない。分割で取った回は記録しない。
   if result.get('ok') and result.get('rne_path') and not result.get('split_parts'):
    save_rne_timing(result['rne_path'],result.get('execute_seconds'),result.get('save_seconds'),
                    result.get('total_seconds'),result.get('rows'),result.get('columns'))
   if result.get('split_parts'):
    log.info('SPLIT_RUN_USED batch_id=%s job=%s 形=%s 片数=%s 軸=%s winner=%s elapsed=%.2fs',batch_id,item['job']['name'],
             result.get('split_how') or result.get('split_shape') or '-',result['split_parts'],
             result.get('row_axis') or '-',result.get('race_winner') or '-',result.get('elapsed') or 0)
   with active_workers_lock:active_workers.pop(slot,None)
   del active[slot]
   if queue and not cancel_requested.is_set():start_one(slot)
  waiting=len(queue);running=len(active)
  running_ids=[item['job']['id'] for item in active.values()]
  waiting_ids=[job['id'] for _,job in queue]
  if board:
   board.api_tick(activity_detail=f'{max_lines}ラインで予約クエリを処理')
  else:
   set_status(completed_jobs=completed,current_index=min(completed+running,total),current_job_name=f'予約キュー処理中: 実行 {running} / 待機 {waiting}',step='save',step_label=f'API並列処理 実行 {running}・待機 {waiting}・完了 {completed}',step_percent=round(100*completed/max(1,total)),activity_detail=f'{max_lines}ラインで予約クエリを処理',activity_value=f'実行 {running} / 待機 {waiting} / 完了 {completed}/{total}',queue_total=total,queue_waiting=waiting,queue_active=running,queue_completed=completed,queue_completed_ids=list(completed_ids),queue_failed_ids=list(failed_ids),queue_running_ids=running_ids,queue_waiting_ids=waiting_ids,failed_jobs=len(failed_ids),job_errors=[{'job':x.get('job'),'error':str(x.get('error') or '')} for x in failures])
  time.sleep(.25)
 elapsed=time.perf_counter()-batch_started
 sequential_sum=sum(float(r.get('elapsed',0)) for r in results+failures);speedup=sequential_sum/elapsed if elapsed else 0
 summary='; '.join(f"{r.get('job')}={float(r.get('elapsed',0)):.1f}s" for r in results)
 log.info('PARALLEL_BATCH_END model=process-isolated total_jobs=%s succeeded=%s failed=%s max_lines=%s elapsed=%.2fs sequential_sum=%.2fs speedup=%.2fx job_elapsed_summary=%s',total,len(results),len(failures),max_lines,elapsed,sequential_sum,speedup,summary)
 if board:board.publish(parallel_speedup=round(speedup,2),parallel_mode=True)
 else:set_status(parallel_speedup=round(speedup,2),queue_waiting=0,queue_active=0,queue_completed=completed,queue_completed_ids=list(completed_ids),queue_failed_ids=list(failed_ids),queue_running_ids=[],queue_waiting_ids=[],parallel_mode=True)
 shutil.rmtree(runtime,ignore_errors=True)
 log.info('PARALLEL_RUNTIME_CLEANUP path=%s exists_after=%s',runtime,runtime.exists())
 return results,failures,elapsed


# ---- 手元側（スレッド） -------------------------------------------------------
def _local_lane(slot,board,cfg,work,backup,trigger,progress_fn):
 """手元の処理を受け持つライン1本。黒板から次を取り、無くなるまで回す。"""
 line=f'ライン {slot}'
 while True:
  entry=board.claim()
  if entry is None:break
  j=entry['job'];started=time.perf_counter()
  update_parallel_line(line,job=j.get('name',''),job_id=j.get('id',''),state='開始',percent=2,
                       slot=slot,detail='手元のファイルから作ります',
                       started_at=datetime.now().isoformat(timespec='seconds'))
  base=app.local_progress_say(progress_fn,j)
  def say(stage,**kw):
   pct,label=LOCAL_STAGE.get(stage,(50,'処理中'))
   detail=str(kw.get('activity') or kw.get('source') or '')
   if stage=='wait':detail=navi_order.reason_text(kw.get('reasons') or [])
   update_parallel_line(line,job=j.get('name',''),job_id=j.get('id',''),state=label,percent=pct,
                        slot=slot,detail=detail,elapsed=round(time.perf_counter()-started,1))
   base(stage,**kw)
  # 同じ実行のなかの順番は黒板が見ている。ここでの待ち合わせは、別の実行や別のPCが
  # 同じファイルを触っているときのためのもの ―― 二重に待たせない。
  try:
   out=run_one_local(j,cfg,work,backup,trigger,entry['order']+1,board.total,say=say)
  except Exception as e:
   # run_one_local は例外を返さない約束だが、ここで落ちるとこの対象は「実行中」の
   # まま残り、材料を待っているほかのラインごと止まる。必ず報告して次へ進む。
   log.exception('LANE_LOCAL_FAILED job=%s',j.get('name'))
   out={'ok':False,'job':j.get('name',''),'error':str(e),'detail':str(e),
        'job_result':{'job':j.get('name',''),'job_id':j['id'],'status':'failed','detail':str(e)}}
  update_parallel_line(line,job=j.get('name',''),job_id=j.get('id',''),
                       state='完了' if out.get('ok') else '失敗',percent=100,slot=slot,
                       detail=str(out.get('detail') or out.get('error') or ''),
                       elapsed=round(time.perf_counter()-started,1))
  board.note(j['id'],j.get('name',''),bool(out.get('ok')),result_text=str(out.get('result') or ''),
             job_result=out.get('job_result'),error=str(out.get('error') or ''))
 update_parallel_line(line,job='',state='終了',percent=100,slot=slot,detail='このラインの割り当ては終わりました')


def run_lanes(ordered,local_jobs,api_jobs,cfg,user,pw,server,dde_work,backup,max_lines,trigger,progress):
 """RNEと手元の処理を同時に流す。返すのは (結果の文, 失敗, 所要秒)。

 走らせ方は違う（RNEは独立プロセス、手元はスレッド）が、終わりを書き込む先は同じ
 黒板。結合はその黒板を見て、材料がそろってから走り出す。
 """
 deps=job_dependencies(ordered,cfg)
 kinds={j['id']:normalize_job_source(j.get('source')) for j in ordered}
 plan=navi_lane.build_plan(ordered,deps,kinds)
 local_ids={j['id'] for j in local_jobs}
 local_plan=[e for e in plan if e['id'] in local_ids]
 api_lines=max(1,min(int(max_lines or 1),len(api_jobs))) if api_jobs else 0
 lanes=navi_lane.local_lines(cfg['settings'].get('local_parallel_lines'),max_lines,len(local_plan)) if local_plan else 0
 board=LaneBoard(plan,api_lines,lanes,trigger)
 log.info('LANE_PLAN 順番=%s',navi_lane.plan_text(plan))
 if navi_lane.wait_text(plan):log.info('LANE_WAIT 材料を待つ=%s',navi_lane.wait_text(plan))
 log.info('LANE_START RNE=%s件/%sライン 手元=%s件/%sライン 合計=%s件',
          len(api_jobs),api_lines,len(local_plan),lanes,len(plan))
 board.begin()
 started=time.perf_counter()
 threads=[]
 for n in range(1,lanes+1):
  t=threading.Thread(target=_local_lane,args=(api_lines+n,board,cfg,dde_work,backup,trigger,progress),
                     name=f'local-lane-{n}',daemon=True)
  t.start();threads.append(t)
 api_elapsed=0.0;api_error=''
 if api_jobs:
  # RNE側が落ちても、手元のラインは最後まで面倒を見る。ここで例外を素通しすると
  # 走っているスレッドを置き去りにしたまま抜け、結果も画面も途中で止まる。
  try:
   _res,_fail,api_elapsed=run_api_process_batch(api_jobs,cfg,user,pw,server,dde_work,backup,
                                                max_lines,trigger,board=board)
  except Exception as e:
   api_error=str(e);log.exception('LANE_API_FAILED error=%s',e)
  finally:
   board.api_closed([j['id'] for j in api_jobs],reason=api_error)
 for t in threads:t.join()
 # 対象1件ごとの失敗として残せなかったとき（全部報告済みのあとで落ちた等）は、
 # 実行そのものの失敗として残す。黙って正常終了にしない。
 if api_error and not any(str(x.get('error') or '')==api_error for x in board.failures):
  board.failures.append({'ok':False,'job':'RNEの実行','error':api_error})
 elapsed=time.perf_counter()-started
 log.info('LANE_END 完了=%s 失敗=%s 実行しなかった=%s 所要=%.2fs（RNEのみ %.2fs）',
          len(board.done),len(board.failed),len(board.skipped),elapsed,api_elapsed)
 board.publish(queue_running_ids=[],queue_waiting_ids=[],queue_active=0,queue_waiting=0)
 return {'results':list(board.results),'failures':list(board.failures),
         'elapsed':elapsed,'skipped':list(board.skipped)}


def finish_batch(res,total_jobs,progress):
 """実行の締め。失敗があれば止め、無ければ結果の1行を残す。"""
 if cancel_requested.is_set():
  raise app.RunCancelled(f'{len(res["results"])}/{total_jobs}件完了後に中断されました')
 if res['failures']:
  set_status(job_errors=[{'job':r.get('job'),'error':str(r.get('error') or '')} for r in res['failures']],
             failed_jobs=len(res['failures']))
  raise RuntimeError('%d件失敗しました\n'%len(res['failures'])
                     +'\n'.join('・%s: %s'%(r.get('job'),r.get('error')) for r in res['failures']))
 done=list(res['results'])
 msg='正常終了 | '+(done[0] if len(done)==1
                  else '全件%sファイル / %.1f秒 | '%(len(done),res['elapsed'])+' | '.join(done))
 progress('complete','すべての処理が完了しました',100)
 set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),
            elapsed_seconds=int(time.time()-progress.started))
 log.info(msg)
 return msg
