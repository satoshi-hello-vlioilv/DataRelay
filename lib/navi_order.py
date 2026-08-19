"""結合の材料がそろってから走らせる ―― 順番と、待ち合わせ。

結合は、ほかの対象が作ったファイルを材料にすることがある。そうなると2つ困ることが
起きる。

1つは順番。同じ実行にまとめて選んだとき、材料を作る側があとに回ると、結合は
「1回前のファイル」を繋いでしまう。しかも出来上がりは正しい形をしているので、
中身が古いことに誰も気づかない。

もう1つは擦れ違い。材料の更新と結合が同じ時間帯に重なると、片方が書いている
最中にもう片方が読む。差し替えそのものは一瞬（os.replace）なので壊れたファイルは
読まないが、「更新の直前に読んでしまい、1回ぶん古いまま出す」ことは起きる。

だから、走る前に材料の様子を見る。
  ・いま作っている最中か（このアプリで実行中／公開の途中）
  ・もうすぐ作り始めるか（先読みの時間内に予定があるか）
どちらかなら待つ。どちらでもなければ走る。

判断はここに閉じてある（本体の状態は見ない）。実行中かどうかも予定も、呼ぶ側が
渡す ―― そうしておくと、実際に走らせずに、机の上で全部確かめられる。
"""
import time
from datetime import datetime,timedelta
from pathlib import Path
from navi_log import log

# 先読みの既定。「実行しようとした時刻から1分後まで」の予定を見る。
# 短すぎると擦れ違い、長すぎると毎回待たされる ―― 1分は、公開が始まってから
# 差し替わるまでの往復にちょうど収まる長さ。
LOOKAHEAD_SECONDS_DEFAULT=60
# 待ちきれなくなるまで。ここを超えたら、待つのをやめて走る（古いままかもしれないと
# 断ったうえで）。止め続けるより、古いと言って出すほうが直しようがある。
MAX_WAIT_SECONDS_DEFAULT=600
# 様子を見に行く間隔。
POLL_SECONDS_DEFAULT=5
# 書きかけの印（.名前.pid.incoming）の賞味期限。強制終了で残ることがあり、そのままだと
# 「誰かが書いている最中」と読み続けて、それを材料にする結合が以後ずっと待たされる。
# 実際の書き込みは長くても数十秒なので、それより十分に長く取る。
INCOMING_STALE_SECONDS=900

# 設定の既定。決める場所と読む場所を分けると、片方だけ直したときに食い違う。
WAIT_DEFAULTS={'join_wait_enabled':True,
               'join_wait_lookahead_seconds':LOOKAHEAD_SECONDS_DEFAULT,
               'join_wait_max_seconds':MAX_WAIT_SECONDS_DEFAULT,
               'join_wait_poll_seconds':POLL_SECONDS_DEFAULT}

WAIT_REASON_LABEL={'running':'いま作成中です','queued':'実行の順番待ちです',
                   'scheduled':'まもなく作成が始まります','writing':'公開先へ書き込み中です'}

def _key(p):
 return str(Path(str(p or '')).as_posix()).lower()

def output_owners(cfg,resolve):
 """出力ファイルの場所 → それを作る対象。結合の材料がどこから来るかを引く表。

 実行のたびに名前が変わる対象（変数命名）もあるので、いま在るファイルと次に作る
 名前の両方を載せる ―― どちらで指されても、作り手にたどり着けるようにする。
 """
 out={}
 for j in (cfg.get('jobs') or []):
  for p in (resolve(j) or []):
   if not p:continue
   k=_key(p);have=out.setdefault(k,[])
   if not any(x['id']==j['id'] for x in have):have.append(j)
 return out

def recipe_sources(recipe,resolve_source):
 """この結合が読むファイルの場所。"""
 return [resolve_source(s) for s in (recipe.get('sources') or []) if (s or {}).get('path')]

def job_inputs(job,cfg,find_recipe,resolve_source):
 """この対象が材料として読むファイル。結合以外は空（材料は自分の外に無い）。"""
 if str(job.get('source') or '')!='join':return []
 r=find_recipe(job.get('recipe_id'))
 if not r:return []
 return recipe_sources(r,resolve_source)

def dependencies(jobs,cfg,find_recipe,resolve_source,resolve_outputs):
 """対象id → その材料を作る対象idの集合。

 自分で自分の材料を作っている（出力を自分で読む）ときは、依存に数えない ――
 数えると永遠に自分を待つことになる。積み増しの結合はそういう作りになりうる。
 """
 owners=output_owners(cfg,resolve_outputs)
 deps={}
 for j in jobs:
  need=set()
  for p in job_inputs(j,cfg,find_recipe,resolve_source):
   for owner in owners.get(_key(p),[]):
    if owner['id']!=j['id']:need.add(owner['id'])
  deps[j['id']]=need
 return deps

def order_jobs(jobs,deps):
 """材料を作る側が先に来るように並べ替える。

 並べ替えるだけで、増やしも減らしもしない。決められないもの（互いに材料にし合って
 いる＝輪になっている）は、元の順のまま後ろへ置く ―― 走らせないより、順番が
 決まらないと言って走らせるほうがよい。
 """
 by={j['id']:j for j in jobs}
 want={i:{d for d in deps.get(i,set()) if d in by} for i in by}
 out=[];done=set()
 rest=[j['id'] for j in jobs]
 while rest:
  ready=[i for i in rest if not (want[i]-done)]
  if not ready:
   # 輪になっている。ここで止めると1件も走らないので、残りは元の順のまま流す。
   log.warning('JOB_ORDER_CYCLE 対象=%s 順番を決められないので、登録順のまま実行します',
               [by[i]['name'] for i in rest])
   out.extend(by[i] for i in rest);break
  for i in ready:
   out.append(by[i]);done.add(i)
  rest=[i for i in rest if i not in done]
 return out

def upstream_of(job_id,deps,depth=6):
 """その対象より前に済ませておくべき対象。並べ替えの説明に使う。"""
 seen=set();front={job_id}
 for _ in range(max(1,depth)):
  nxt=set()
  for i in front:nxt|= (deps.get(i) or set())
  nxt-=seen|{job_id}
  if not nxt:break
  seen|=nxt;front=nxt
 return seen

# ---- 待ち合わせ ------------------------------------------------------------
def publishing_now(path):
 """その場所へ、いま公開の書き込みが来ているか。

 公開はいったん隠しファイル（.名前.pid.incoming）へ書き切ってから差し替える。
 その隠しファイルが在るということは、誰かが（別のPCでも）書いている最中という印
 ―― こちらのアプリの状態を見なくても分かる、いちばん確かな手がかり。
 """
 p=Path(str(path or ''))
 if not str(p).strip():return False
 try:
  # 書きかけの印には賞味期限を置く。強制終了（中止・アプリ終了・停止バッチ）で
  # 隠しファイルが残ることがあり、そのままだと「誰かが書いている最中」と読み続けて、
  # それを材料にする結合が以後ずっと（既定10分）待たされることになる。
  # 実際の書き込みは長くても数十秒なので、それより十分に長い時間で切る。
  limit=time.time()-INCOMING_STALE_SECONDS
  for x in p.parent.glob(f'.{p.name}.*.incoming'):
   try:
    if x.stat().st_mtime>=limit:return True
   except OSError:continue
  return False
 except Exception:
  return False

def wait_reasons(job,cfg,now,*,deps,running_ids,queued_ids,next_run_of,inputs,
                 lookahead_seconds=LOOKAHEAD_SECONDS_DEFAULT,name_of=None):
 """いま走ってよいか。待つ理由の一覧を返す（空なら走ってよい）。

 呼ぶ側から「いま何が動いているか」「次はいつか」を渡してもらう。ここで本体の
 状態を覗きにいくと、机の上で確かめられなくなる。
 """
 name=name_of or (lambda i:i)
 out=[]
 limit=now+timedelta(seconds=max(0,int(lookahead_seconds or 0)))
 for owner in sorted(deps.get(job['id']) or set()):
  if owner in (running_ids or set()):
   out.append({'kind':'running','job_id':owner,'job':name(owner)});continue
  if owner in (queued_ids or set()):
   out.append({'kind':'queued','job_id':owner,'job':name(owner)});continue
  nxt=next_run_of(owner)
  if nxt and now<=nxt<=limit:
   out.append({'kind':'scheduled','job_id':owner,'job':name(owner),'at':nxt.isoformat(timespec='seconds')})
 # 予定にも実行中にも出てこないが、いま書き込まれている場合（別のPCの公開など）。
 for p in (inputs or []):
  if publishing_now(p):
   out.append({'kind':'writing','path':str(p),'job':Path(str(p)).name})
 return out

def reason_text(reasons):
 """待つ理由を、そのまま読める1行にする。"""
 if not reasons:return ''
 parts=[]
 for r in reasons[:4]:
  label=WAIT_REASON_LABEL.get(r['kind'],r['kind'])
  at=f'（{str(r.get("at") or "").replace("T"," ")}）' if r.get('at') else ''
  parts.append(f'{r.get("job") or ""}: {label}{at}')
 more=f' ほか{len(reasons)-4}件' if len(reasons)>4 else ''
 return '／'.join(parts)+more

def wait_settings(cfg):
 s=(cfg or {}).get('settings') or {}
 return {'enabled':bool(s.get('join_wait_enabled',True)),
         'lookahead':max(0,min(3600,int(s.get('join_wait_lookahead_seconds',LOOKAHEAD_SECONDS_DEFAULT) or 0))),
         'max_wait':max(0,min(86400,int(s.get('join_wait_max_seconds',MAX_WAIT_SECONDS_DEFAULT) or 0))),
         'poll':max(1,min(60,int(s.get('join_wait_poll_seconds',POLL_SECONDS_DEFAULT) or POLL_SECONDS_DEFAULT)))}
