"""値ごとに分けて出す: 1回で受け取ったあとの「値ごとの 変換 → 公開」を速くする案の計測（評価関数）。

画面に出ない改良なので、案を文章ではなく動かした数で比べる（CLAUDE.md の 3）。本物の app の
process_api_parallel_job を、偽物の API（値の数・行数・列数を決めて返す）で最後の公開まで通し、次を測る。
  post  … 受け取ったあと（値ごとに分け始めてから）終わるまでの秒数。この改良が縮めたいところ
  total … 対象1つの全体の秒数
  ok    … 出たファイルの中身が、いまの作り（順に1つずつ）と行まで同じか・全部の値が出たか
  progress … 進み具合が戻らない・完了は最後の1回だけ・最後は全部の値が ok
共有フォルダー（公開先）の遅さは、ここに無いので型で置く（--latency・--bandwidth）:
  ・共有への1回の操作（複写の開始・名前替え・一覧）に latency 秒
  ・複写の中身は、1本の回線を分け合う（同時に写しても、合わせて bandwidth バイト/秒より速くならない）
目印のあとの猶予（navi_publish.MARK_GRACE_SECONDS＝3秒）は本物のまま待つ。

使い方（リポジトリの直下から）:
  python tests/ui-proposals/2026-10-variant-publish.py                 # 全案 × 全場面
  python tests/ui-proposals/2026-10-variant-publish.py --only seq,B    # 一部の案
結果は標準出力の最後の行に JSON で出す（案ごと・場面ごとの数）。
"""
import argparse,json,os,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

# 案。lines: 同時に作る値の数（'n'＝値の数だけ・'budget'＝この対象に回せるライン数）。serial_convert: 変換は1本ずつ
STRATEGIES={
 'seq':{'name':'いまの作り（順に1つずつ）','lines':1},
 'A':{'name':'全部同時（値の数だけ同時に 変換→公開）','lines':'n'},
 'B':{'name':'ライン数まで同時（この対象に回せるライン数）','lines':'budget'},
 'C':{'name':'4本まで同時','lines':4},
 'D':{'name':'流れ作業（変換は1本ずつ・公開はライン数まで同時）','lines':'budget','serial_convert':True},
 'E':{'name':'流れ作業（変換は1本ずつ・公開は全部同時）','lines':'n','serial_convert':True},
 'F':{'name':'待ちをまとめる（順のまま、全部の目印を置いてから猶予を1回だけ待ち、続けて差し替える）','lines':1,'batch_grace':True},
 'G':{'name':'共有の一覧を減らす（順のまま、保留の探しを置き場ごとに1回）','lines':1,'scan_once':True},
 # 2回目の組合せ案（1回目の 1位 D・2位 B・3位 E と合わせて採点する）
 'H':{'name':'変換は1本ずつ・公開は32本まで重ね、共有への複写と差し替えだけをライン数までに絞る','lines':32,'serial_convert':True,'share_ops':'budget'},
 'I':{'name':'変換は1本ずつ・公開はライン数×4まで重ね、共有への複写と差し替えだけをライン数までに絞る','lines':'budget4','serial_convert':True,'share_ops':'budget'},
 'J':{'name':'変換は1本ずつ・公開はライン数×2まで同時','lines':'budget2','serial_convert':True},
 'K':{'name':'変換は1本ずつ・公開は32本まで重ね、公開のうち待ち（猶予・再試行の間）以外をライン数までに絞る','lines':32,'serial_convert':True,'share_gate':'budget'},
 # 作ったあと: 差し替えをせず、app の既定のまま動かす（選んだ K を作った物）
 'built':{'name':'作ったあと（app の既定のまま）','as_built':True},
}
SCENES={
 'many':{'name':'20値 × 3000行 × 20列 CSV','values':20,'rows':3000,'cols':20,'fmt':'csv'},
 'xlsx':{'name':'20値 × 3000行 × 20列 EXCEL','values':20,'rows':3000,'cols':20,'fmt':'xlsx'},
 'small':{'name':'40値 × 300行 × 20列 CSV','values':40,'rows':300,'cols':20,'fmt':'csv'},
 'fail':{'name':'8値 × 3000行 × 20列 CSV・V03 だけ変換で失敗','values':8,'rows':3000,'cols':20,'fmt':'csv','fail':'V03'},
 'extra':{'name':'20値 × 3000行 × 20列 CSV ＋ 同時出力 TXT','values':20,'rows':3000,'cols':20,'fmt':'csv','extras':['txt']},
}

CHILD=r"""
import csv,hashlib,json,os,shutil,sys,threading,time
from pathlib import Path
root,work,arg=sys.argv[1],Path(sys.argv[2]),json.loads(sys.argv[3])
sys.path[:0]=[root,root+'/lib']
import app,navigator_api,navi_publish,navi_variants
sc,st=arg['scene'],arg['strategy'];K,R,C=sc['values'],sc['rows'],sc['cols']
VALUES=[f'V{k:02d}' for k in range(K)]
share=(work/'share').resolve();share.mkdir()
LAT=float(arg['latency']);BW=float(arg['bandwidth']);link=threading.Lock();ops={'copy':0,'replace':0,'glob':0,'peak':0};busy=[0];bl=threading.Lock()
class on_op:
 def __enter__(self):
  with bl:busy[0]+=1;ops['peak']=max(ops['peak'],busy[0])
 def __exit__(self,*a):
  with bl:busy[0]-=1
def on_share(*ps):return any(str(Path(p).resolve()).startswith(str(share)) for p in ps if p is not None)
# 共有の型: 操作ごとの遅れ（同時に重なる）と、回線の分け合い（複写の中身は1本ずつしか流れない）
_copy2,_replace,_glob=shutil.copy2,os.replace,Path.glob
def copy2(src,dst,*a,**k):
 if on_share(src,dst):
  with on_op():
   ops['copy']+=1;time.sleep(LAT)
   with link:time.sleep(Path(src).stat().st_size/BW)
 return _copy2(src,dst,*a,**k)
def replace(src,dst,*a,**k):
 if on_share(src,dst):
  with on_op():ops['replace']+=1;time.sleep(LAT)
 return _replace(src,dst,*a,**k)
def glob(self,pat):
 if on_share(self):
  with on_op():ops['glob']+=1;time.sleep(LAT)
 return _glob(self,pat)
class _Sh:
 def __getattr__(self,n):return copy2 if n=='copy2' else getattr(shutil,n)
class _Os:
 def __getattr__(self,n):return replace if n=='replace' else getattr(os,n)
navi_publish.shutil=_Sh();navi_publish.os=_Os();Path.glob=glob

class Fake:
 dll_path='fake.dll'
 def __init__(self,*a,**k):pass
 def open_session(self,*a):return 0.01
 def connect_data_source(self,p):return 0.01
 def open_catalog(self,p):return 1,0.01
 def apply_period(self,*a):return {}
 def relax_condition(self,h,item,hint=''):return {'form':'NULL以外','tried':[]}
 def apply_row_categories(self,h,spec):return {'form':'試験','values':K,'others':0}
 def execute(self,h):return K*R,0.01
 def dimensions(self,h):return K*R,C
 def save_csv(self,h,path,repeat_labels=False):
  head=['仕掛区分','BOX実績_設備名']+[f'項目{i}' for i in range(C-2)]
  with open(path,'w',encoding='cp932',newline='') as f:
   f.write(','.join(head)+'\r\n')
   for v in VALUES:
    for i in range(R):f.write(','.join(['A',v]+[f'{v}-{i}-{c}' for c in range(C-2)])+'\r\n')
  return 0.01
 def close_catalog(self):pass
 def close(self):pass
navigator_api.NavigatorApi=Fake
rne=work/'LOTACH.RNE';shutil.copy(Path(root)/'samples'/'rne'/'LOTACH.RNE',rne)
cfg=app.load();cfg['settings']['reject_zero_rows']=True;app.save(cfg,quiet=True);cfg=app.load()
v={'enabled':True,'item':'BOX実績_設備名','values':[] if sc.get('all',True) else VALUES,'scope':'all' if sc.get('all',True) else 'list','method':'combined'}
job={'id':'j1','name':'LOT実績','enabled':True,'source':'rne','rne':'LOTACH.RNE','rne_path':str(rne),'output_folder':str(share),
     'output_format':sc['fmt'],'output_file':'LOTACH.'+sc['fmt'],'extra_formats':sc.get('extras',[]),'naming_mode':'fixed','type':'詳細データ','sheet':'Page1','table':'t','schedules':[],'variants':v}
cfg['jobs']=[job];app.save(cfg,quiet=True);job=app.load()['jobs'][0]
cfg=app.load()
# 案を当てる（app の差し替え口。prototype の案はここで組む）
exec(open(arg['proto'],encoding='utf-8').read())   # 試作の案（F・G）と、案の当て方
_BUDGET[0]=int(arg['budget']);use(app,cfg,st)
if sc.get('fail'):
 _exp=app.export_data
 def export_data(src,dst,job,*a,**k):
  if job.get('_variant_value')==sc['fail']:raise RuntimeError('試験: この値だけ失敗')
  return _exp(src,dst,job,*a,**k)
 app.export_data=export_data
lines=[];_upd=app.update_parallel_line;mark={}
def spy(line,**kw):
 lines.append({k:kw.get(k) for k in ('state','percent','variants','detail')})
 if kw.get('phase')=='convert' and 'post' not in mark:mark['post']=time.perf_counter()
 return _upd(line,**kw)
app.update_parallel_line=spy
_split=navi_variants.split_csv
def split(*a,**k):mark['post']=time.perf_counter();return _split(*a,**k)
navi_variants.split_csv=split
job['_split_budget']=int(arg['budget'])
t0=time.perf_counter()
res=app.process_api_parallel_job(job,1,1,cfg,'u','p','srv',work/'dde',work/'backup')
t1=time.perf_counter()
files={}
for p in sorted(share.glob('*.'+sc['fmt'])):
 if sc['fmt']=='csv':rows=list(csv.reader(open(p,encoding='utf-8-sig')))
 else:
  import openpyxl;wb=openpyxl.load_workbook(p,read_only=True);rows=[[('' if c is None else str(c)) for c in r] for r in wb.active.iter_rows(values_only=True)];wb.close()
 files[p.name]=hashlib.sha1(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()
pct=[x['percent'] for x in lines if x['percent'] is not None]
fin=[i for i,x in enumerate(lines) if x['state'] in ('完了','一部失敗','失敗')]
left=[p.name for p in share.iterdir() if p.name.startswith('.') or '.pending_' in p.name]
import resource
print(json.dumps({'details':[d for w in ('変換中','変換待ち','公開中') for d in list(dict.fromkeys(x['detail'] for x in lines if w in str(x.get('detail') or '')))[:2]],'mem_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),'per_value':[[x['value'],x['ok']] for x in res.get('variant_results') or []],'ok':bool(res.get('ok')),'error':res.get('error',''),'post':round(t1-mark.get('post',t1),2),'total':round(t1-t0,2),
 'files':files,'extra_files':len(list(share.glob('*.txt'))),'ops':ops,'left':left,
 'progress':{'monotonic':pct==sorted(pct),'finish_once':fin==[len(lines)-1],
             'last_all_ok':bool(lines) and [y['state'] for y in lines[-1]['variants'] or []]==[('ng' if f'V{k:02d}'==sc.get('fail') else 'ok') for k in range(K)],
             'max_running':max([sum(1 for y in (x['variants'] or []) if y['state']=='run') for x in lines] or [0])}},ensure_ascii=False))
"""

def run(strategy,scene,args):
 with tempfile.TemporaryDirectory() as d:
  d=Path(d);(d/'dde').mkdir();(d/'backup').mkdir()
  env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
           NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
  arg={'scene':SCENES[scene],'strategy':STRATEGIES[strategy],'latency':args.latency,'bandwidth':args.bandwidth,'budget':args.budget,
       'proto':str(Path(__file__).with_name('2026-10-variant-publish-proto.py'))}
  r=subprocess.run([sys.executable,'-c',CHILD,str(ROOT),str(d),json.dumps(arg,ensure_ascii=False)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=1800)
  if r.returncode:return {'ok':False,'error':r.stderr[-2000:]}
  return json.loads(r.stdout.strip().splitlines()[-1])

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--only',default=','.join(STRATEGIES));ap.add_argument('--scenes',default=','.join(SCENES))
 ap.add_argument('--latency',type=float,default=0.03,help='共有への1回の操作の遅れ（秒）')
 ap.add_argument('--bandwidth',type=float,default=30e6,help='共有への回線の速さ（バイト/秒。同時に写しても合わせてこの速さ）')
 ap.add_argument('--budget',type=int,default=6,help='この対象に回せるライン数（_split_budget。並列ライン数6・対象1つ）')
 args=ap.parse_args();out={}
 for sc in args.scenes.split(','):
  ref=None
  for s in args.only.split(','):
   r=run(s,sc,args)
   if s=='seq':ref=r.get('files')
   r['same_as_seq']=None if ref is None else (r.get('files')==ref)
   r['files']=len(r.get('files') or {})
   out.setdefault(sc,{})[s]=r
   print(f'{sc:6} {s:4} ok={r.get("ok")} post={r.get("post")}s total={r.get("total")}s files={r["files"]} same={r["same_as_seq"]} '
         f'progress={r.get("progress")} ops={r.get("ops")} left={r.get("left")} {str(r.get("error") or "")[:300]}',file=sys.stderr,flush=True)
 print(json.dumps({'latency':args.latency,'bandwidth':args.bandwidth,'budget':args.budget,'scenes':SCENES,'strategies':STRATEGIES,'results':out},ensure_ascii=False))

if __name__=='__main__':main()
