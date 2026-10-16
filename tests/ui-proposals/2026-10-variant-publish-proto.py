# 2026-10-variant-publish.py の子から exec で読む: 案を app に当てる use(app,cfg,st) と、試作の案（F・G）。
# A〜E は app の差し替え口（_variant_file_lines・_variant_convert_gate・_variant_share_limit）を使う。差し替え口が無い作り（いまの作り）では seq だけ動く。
import threading as _th,time as _t
from pathlib import Path as _P

def _width(j,n,l):
 b=int(j.get('_split_budget') or 1)
 return max(1,min(n,{'n':n,'budget':b,'budget2':b*2,'budget4':b*4}.get(l,l) if isinstance(l,str) else int(l)))

def use(app,cfg,st):
 if st.get('as_built'):return
 lines=st.get('lines',1)
 if hasattr(app,'_variant_file_lines'):
  B={'_split_budget':_BUDGET[0]}
  app._variant_file_lines=lambda n,_l=lines:_width(B,n,_l)
  # 共有の鍵: K（share_gate）はライン数まで。ほかの案は絞らない（上限を十分大きく）
  app._variant_share_limit=lambda j:_width(B,10**6,st['share_gate']) if st.get('share_gate') else 10**6
  if st.get('share_ops'):_share_ops(app,st['share_ops'])
  gate=_th.Lock()
  app._variant_convert_gate=lambda _g=gate,_s=bool(st.get('serial_convert')):_g if _s else None
 elif lines!=1:raise SystemExit('この作りには差し替え口がありません（seq・F・G だけ）')
 if st.get('scan_once'):_scan_once(app)
 if st.get('batch_grace'):_batch_grace(app)

def _scan_once(app):
 """G: 保留（*.pending_*）を探す一覧を、置き場ごとに1回だけにする。見つかった置き場の対象だけ、本物の apply_pending を通す。"""
 real=app.apply_pending;seen={}
 def apply_pending(dst,*a,**k):
  d=str(dst.parent)
  if d not in seen:seen[d]=[p.name for p in dst.parent.glob('*.pending_*')]
  if not any(n.startswith(dst.stem+'.pending_') for n in seen[d]):return None
  return real(dst,*a,**k)
 app.apply_pending=apply_pending

def _batch_grace(app):
 """F: 順のまま。公開では目印へ写すだけにし、全部の値を写し終えてから、猶予（3秒）を最後の目印から1回だけ待って、続けて差し替える。"""
 import navi_publish as np
 todo=[]
 def publish(src,dst,backup_root,generations,**k):
  dst.parent.mkdir(parents=True,exist_ok=True)
  inc=dst.parent/f'.{dst.name}.{len(todo)}.incoming';np.shutil.copy2(src,inc);todo.append((inc,dst,backup_root,generations,_t.time()))
  return {'published':True,'path':str(dst)}
 def flush():
  if not todo:return
  wait=np.MARK_GRACE_SECONDS-(_t.time()-todo[-1][4])
  if wait>0:_t.sleep(wait)
  for inc,dst,broot,gen,_ in todo:
   b=broot/dst.stem
   if dst.exists():b.mkdir(parents=True,exist_ok=True);np.shutil.copy2(dst,b/f'{dst.stem}_x{dst.suffix}')
   np.os.replace(inc,dst)
   if b.is_dir():list(b.glob(f'{dst.stem}_*{dst.suffix}'))
  todo.clear()
 real=app._variants_result
 def result(*a,**k):flush();return real(*a,**k)
 app.publish=publish;app._variants_result=result

def _share_ops(app,l):
 """H・I: 共有への複写と差し替えの1回ずつだけを、ライン数までの鍵で絞る（猶予・控えの整理・一覧は絞らない）。"""
 import navi_publish as np
 sem={};sh,os_=np.shutil,np.os
 def g(j=None):
  if 'x' not in sem:sem['x']=_th.BoundedSemaphore(_width({'_split_budget':_BUDGET[0]},10**6,l))
  return sem['x']
 class Sh:
  def __getattr__(self,n):
   f=getattr(sh,n)
   if n!='copy2':return f
   def copy2(*a,**k):
    with g():return f(*a,**k)
   return copy2
 class Os:
  def __getattr__(self,n):
   f=getattr(os_,n)
   if n!='replace':return f
   def replace(*a,**k):
    with g():return f(*a,**k)
   return replace
 np.shutil=Sh();np.os=Os()
_BUDGET=[6]
