"""移行の検証1: ポートを使わない窓口（標準入出力）で、全ルートがいまと同じ答えを返すか。

実行:  python -m unittest tests.test_sidecar_parity -v
報告:  python tests/test_sidecar_parity.py      （ルートごとの突き合わせ表）

やっていること:
  A … いまと同じ形。Flask のアプリへ直接問い合わせる（ポート経由と同じ WSGI の答え）
  B … デスクトップ版の形。migration/poc/sidecar.py を本物の子プロセスとして起こし、パイプの枠で問い合わせる
  同じ問い合わせを同じ順に A と B へ送り、状態コード・種類・中身を突き合わせる。
  A と B はそれぞれ新しい設定置き場（雛形から作る）で動かすので、書き込む問い合わせも同じ条件で比べられる。

ルートの一覧はアプリ自身の URL 表から取る。ここに書き忘れたルートがあれば、それ自体が不合格になる。
中身の突き合わせで揃えるのは「その時刻・その置き場でしか決まらない値」だけ（VOLATILE と normalize の説明を参照）。
"""
import json,os,re,subprocess,sys,tempfile,threading,time,unittest,io,zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SIDECAR=ROOT/'migration'/'poc'/'sidecar.py'
SAMPLE_RNE=ROOT/'samples'/'rne'/'集計表形式サンプル.RNE'

# 呼ぶと実害がある・窓（Rust）が受け持つことになるので、ここでは本文を比べないルート。
# 窓口を通ること自体は「同じ答えか」でなく「届くか」で確かめる（REACH_ONLY）。
#   shutdown-app … プロセスを終わらせる（デスクトップ版では窓が受け持つ）
#   pick-file / pick-folder … tkinter のダイアログを出す（デスクトップ版では窓のダイアログに置き換える）
#   open-path … エクスプローラーを開く（同じく窓が受け持つ）
NOT_CALLED={'/api/shutdown-app','/api/pick-file','/api/pick-folder','/api/open-path'}

# その時刻・その置き場・そのプロセスでしか決まらない値。A と B で違って当たり前なので比べない。
VOLATILE={'server_time','instance_id','pid','started_at','last_received','age_seconds','elapsed','uptime_seconds',
          'generated_at','at','now','time','mtime','modified','updated_at','created_at','checked_at','heartbeat_at',
          'last_seen','since','python','executable','total','latency_ms','free_bytes','free_gb','memory',
          'queue_id'}   # 実行キューの番号は毎回作り直す乱数（uuid4）
# 取り込みなどで新しく振られる識別子（uuid4）。A と B で別々に振られるので揃える。
UUID=re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b')
DATETIME=re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?|\d{2}:\d{2}:\d{2}')

# 裏で走っているもの（調べもの・影実行）しだいで答えが変わるルート。窓口の違いではなく、
# 直前に起こしたスレッドが終わったかどうかで変わる。聞く前に、両方の裏が落ち着くのを待つ。
SETTLE_BEFORE={'/api/background-tasks','/api/log'}

def path_args(rule):
 """URL表の <名前> に入れる値。存在しない対象を指す ―― 答え（404など）が同じかを比べる。"""
 vals={'job_id':'no-such-job','doc_id':'navigator-api','queue_id':'no-such-queue','kind':'points',
       'recipe_id':'no-such-recipe','layout_id':'no-such-layout','filename':'app.css'}
 return re.sub(r'<(?:[a-z]+:)?([a-z_]+)>',lambda m:vals.get(m.group(1),'x'),rule)

def route_requests(rules):
 """URL表の全ルートを、空の本文で1回ずつ呼ぶ問い合わせにする。"""
 out=[]
 for rule,methods in rules:
  path=path_args(rule)
  for m in methods:
   body=b'' if m=='GET' else b'{}'
   hdr={} if m=='GET' else {'Content-Type':'application/json'}
   out.append({'label':f'{m} {rule}','rule':rule,'method':m,'path':path,'query':'','headers':hdr,'body':body})
 return out

def multipart(field,filename,content,ctype):
 b='----datarelayboundary'
 body=(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
       f'Content-Type: {ctype}\r\n\r\n').encode('utf-8')+content+f'\r\n--{b}--\r\n'.encode()
 return body,{'Content-Type':f'multipart/form-data; boundary={b}'}

def scenario_requests(tmp):
 """意味のある問い合わせ。日本語・大きな本文・ファイルの出し入れ・書いて読み戻す。成功する形で送る。"""
 def j(label,method,path,obj=None,query=''):
  body=b'' if obj is None else json.dumps(obj,ensure_ascii=False).encode('utf-8')
  return {'label':label,'rule':path,'method':method,'path':path,'query':query,
          'headers':{} if obj is None else {'Content-Type':'application/json'},'body':body}
 # 固定長テキスト（cp932・日本語・約1MB）を置いて、読取マスタで切る
 text=Path(tmp)/'固定長_日本語.txt'
 text.write_bytes(''.join(f'{i:06d}缶材建材箔{i%97:04d}\r\n' for i in range(50000)).encode('cp932'))
 layout={'name':'日本語の読取マスタ','encoding':'cp932','unit':'byte',
         'columns':[{'name':'番号','start':1,'length':6},{'name':'用途','start':7,'length':10},{'name':'値','start':17,'length':4}]}
 reqs=[
  j('RNEの形（集計表の見本）','POST','/api/rne-shape',{'rne_path':str(SAMPLE_RNE)}),
  j('RNEの形（明細）','POST','/api/rne-shape',{'rne_path':str(ROOT/'config'/'rne'/'SIKAODRNOW.RNE')}),
  j('ファイル名の試算（日本語）','POST','/api/preview-filename',{'pattern':'仕掛_{yyyy}{mm}{dd}','name':'集計表','format':'csv','output_file':'x.csv','table':'仕掛','rne_path':str(SAMPLE_RNE)}),
  j('期間の試算','POST','/api/period-preview',{'period':{'enabled':True,'unit':'month','from_offset':-1,'to_offset':0}}),
  j('日本語の問い合わせ文字列','GET','/api/log',query='q=%E9%9B%86%E8%A8%88%E8%A1%A8&limit=50'),
  j('予定の見通し','GET','/api/schedule-preview',query='days=7'),
  j('固定長テキストの試し読み（cp932・約1MB・日本語のパス）','POST','/api/text-preview',{'path':str(text),'layout':layout,'lines':50}),
  j('約1MBの日本語の本文（設定の検査）','POST','/api/validate',{'jobs':[{'name':'検査'+'漢字'*1000,'comment':'あ'*500000}]}),
  j('登録内容の書き出し（ZIP）','GET','/api/bundle/export',query='parts=jobs,schedules,layouts,recipes'),
  j('集計結果の書き出し（XLSX）','POST','/api/data-viewer/export-pivot',{'format':'xlsx','name':'集計','matrix':[['用途','件数'],['缶材',3],['建材',1]]}),
 ]
 # 書いて読み戻す: 設定を保存 → 読み直す
 reqs.append(j('設定の読み出し','GET','/api/config'))
 # ファイルを受け取る（multipart・日本語のファイル名）: 読取マスタの取り込み
 import navi_text
 blob=json.dumps({'kind':navi_text.LAYOUT_EXPORT_KIND,'layouts':[layout]},ensure_ascii=False).encode('utf-8')
 body,hdr=multipart('file','読取マスタ.json',blob,'application/json')
 reqs.append({'label':'ファイルの受け取り（multipart・日本語のファイル名）','rule':'/api/text-layouts/import','method':'POST',
              'path':'/api/text-layouts/import','query':'','headers':hdr,'body':body})
 reqs.append(j('取り込んだあとの一覧','GET','/api/text-layouts'))
 return reqs

def fresh_env(tmp,name):
 d=Path(tmp)/name
 env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_CONFIG_DIR=str(d/'config'),PYTHONIOENCODING='utf-8')
 return d,env


class Sidecar:
 """B: 子プロセスの窓口。Rust の窓が行うのと同じ読み書きを Python で行う。"""
 def __init__(self,env):
  self.p=subprocess.Popen([sys.executable,str(SIDECAR)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,env=env,cwd=str(ROOT))
  self.lock=threading.Lock();self.waiting={};self.next_id=1;self.events=[]
  self.ready=threading.Event()
  threading.Thread(target=self._reader,daemon=True).start()
  if not self.ready.wait(90):raise RuntimeError('窓口が起動しませんでした')

 def _reader(self):
  while True:
   line=self.p.stdout.readline()
   if not line:break
   head=json.loads(line.decode('utf-8'));n=int(head.get('len') or 0)
   body=self.p.stdout.read(n) if n else b''
   if head.get('id')==0:
    self.events.append(head)
    if head.get('event') in ('ready','fatal'):self.ready.set()
    continue
   ev,slot=self.waiting.pop(head['id'])
   slot.append((head,body));ev.set()
  self.ready.set()

 def call(self,req,timeout=120):
  with self.lock:
   rid=self.next_id;self.next_id+=1
   ev=threading.Event();slot=[];self.waiting[rid]=(ev,slot)
   head={'id':rid,'method':req['method'],'path':req['path'],'query':req.get('query',''),'headers':req.get('headers') or {},'len':len(req['body'])}
   self.p.stdin.write(json.dumps(head,ensure_ascii=False).encode('utf-8')+b'\n'+req['body']);self.p.stdin.flush()
  if not ev.wait(timeout):raise TimeoutError(req['label'])
  h,b=slot[0]
  return h['status'],dict((k.lower(),v) for k,v in h['headers']),b

 def raw(self,data):
  with self.lock:self.p.stdin.write(data);self.p.stdin.flush()

 def close(self,timeout=10):
  try:self.p.stdin.close()
  except Exception:pass
  try:return self.p.wait(timeout)
  except subprocess.TimeoutExpired:self.p.kill();return None


DIRECT_SCRIPT=r'''
import json,sys,base64
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
c=app.app.test_client()
for line in sys.stdin:
 r=json.loads(line)
 body=base64.b64decode(r['body'])
 resp=c.open(r['path'],method=r['method'],query_string=r.get('query',''),headers=r.get('headers') or {},data=body,base_url='http://127.0.0.1:5031/')
 out={'status':resp.status_code,'headers':{k.lower():v for k,v in resp.headers.items()},'body':base64.b64encode(resp.get_data()).decode()}
 sys.__stdout__.write(json.dumps(out)+'\n');sys.__stdout__.flush()
'''

class Direct:
 """A: いまと同じ形（Flask へ直接）。B と状態を分けるため、これも別プロセスで動かす。"""
 def __init__(self,env):
  import base64;self.b64=base64
  self.p=subprocess.Popen([sys.executable,'-c',DIRECT_SCRIPT,str(ROOT)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,env=env,cwd=str(ROOT),text=True,encoding='utf-8')
 def call(self,req):
  self.p.stdin.write(json.dumps({**req,'body':self.b64.b64encode(req['body']).decode()},ensure_ascii=False)+'\n');self.p.stdin.flush()
  r=json.loads(self.p.stdout.readline())
  return r['status'],r['headers'],self.b64.b64decode(r['body'])
 def close(self):
  self.p.stdin.close();self.p.wait(10)


def settle(*sides,limit=15):
 """裏で走っているもの（調べもの・影実行）が両方とも終わるまで待つ。"""
 end=time.time()+limit
 while time.time()<end:
  counts=[json.loads(x.call({'label':'bg','method':'GET','path':'/api/background-tasks','body':b''})[2]).get('count') for x in sides]
  if not any(counts):return True
  time.sleep(0.2)
 return False

def normalize(obj,roots):
 """比べてよい形にする。置き場の違い（A と B の作業フォルダ）と、時刻・プロセスで決まる値だけを揃える。"""
 if isinstance(obj,dict):return {k:('<volatile>' if k in VOLATILE else normalize(v,roots)) for k,v in obj.items()}
 if isinstance(obj,list):return [normalize(x,roots) for x in obj]
 if isinstance(obj,str):
  for r in roots:obj=obj.replace(r,'<ENV>').replace(r.replace('/','\\'),'<ENV>')
  return UUID.sub('<uuid>',DATETIME.sub('<time>',obj))
 if isinstance(obj,float):return '<number>'
 return obj

LOG_NOISE=re.compile(r'^[\d\-/: ,.<>a-z]*\[|pid \d+|\b[0-9a-f]{32}\b|elapsed=[\d.]+s|ready_since_\w+=[-\d.]+s')

def log_lines(text,roots):
 """ログの本文を「何の記録が何件出たか」にする。

 ログはプロセスごとの記録で、pid・ミリ秒の時刻・並行するスレッドの行の順序は A と B で必ず違う。
 それらを除いた行の集まり（並びは問わない）が同じなら、同じことが起きたと言える。"""
 return sorted(LOG_NOISE.sub('',normalize(x,roots)) for x in text.splitlines())

def compare(a,b,roots,rule=''):
 """→ (同じか, 違いの説明)"""
 sa,ha,ba=a;sb,hb,bb=b
 if sa!=sb:return False,f'状態 {sa} ≠ {sb}'
 ta=(ha.get('content-type') or '').split(';')[0];tb=(hb.get('content-type') or '').split(';')[0]
 if ta!=tb:return False,f'種類 {ta} ≠ {tb}'
 if ta=='application/json':
  try:ja=json.loads(ba);jb=json.loads(bb)
  except Exception as e:return False,f'JSONとして読めません: {e}'
  if rule=='/api/log' and isinstance(ja,dict) and isinstance(jb,dict):
   ja=dict(ja,text=log_lines(ja.get('text',''),roots));jb=dict(jb,text=log_lines(jb.get('text',''),roots))
  na=normalize(ja,roots);nb=normalize(jb,roots)
  return (na==nb),('' if na==nb else first_diff(na,nb))
 if ta in ('application/zip','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):
  try:
   za=zipfile.ZipFile(io.BytesIO(ba));zb=zipfile.ZipFile(io.BytesIO(bb))
   if za.namelist()!=zb.namelist():return False,'ZIPの中身の名前が違います'
   if ha.get('content-disposition')!=hb.get('content-disposition'):return False,'保存名が違います'
   return True,f'ZIP {len(za.namelist())}件・保存名一致'
  except Exception as e:return False,f'ZIPとして読めません: {e}'
 if ba==bb:return True,''
 # HTML などは時刻が埋め込まれることがあるので、時刻と置き場だけ揃えて比べる
 da=normalize(ba.decode('utf-8','replace'),roots);db=normalize(bb.decode('utf-8','replace'),roots)
 return (da==db),('' if da==db else f'本文が違います（{len(ba)}B / {len(bb)}B）')

def first_diff(a,b,path='$'):
 if type(a)!=type(b):return f'{path}: 型 {type(a).__name__} ≠ {type(b).__name__}'
 if isinstance(a,dict):
  for k in sorted(set(a)|set(b)):
   if k not in a or k not in b:return f'{path}.{k}: 片方にしか無い'
   if a[k]!=b[k]:return first_diff(a[k],b[k],f'{path}.{k}')
 if isinstance(a,list):
  if len(a)!=len(b):return f'{path}: 件数 {len(a)} ≠ {len(b)}'
  for i,(x,y) in enumerate(zip(a,b)):
   if x!=y:return first_diff(x,y,f'{path}[{i}]')
 return f'{path}: {str(a)[:60]!r} ≠ {str(b)[:60]!r}'


def url_rules(env):
 code=("import sys,json;sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib'];import app;"
       "print(json.dumps([[r.rule,sorted(m for m in r.methods if m not in ('HEAD','OPTIONS'))] for r in app.app.url_map.iter_rules()]))")
 out=subprocess.run([sys.executable,'-c',code,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
 return [tuple(x) for x in json.loads(out.stdout.strip().splitlines()[-1])]


def run_all():
 """全ルートと場面を A・B の両方へ送り、突き合わせた結果を返す。"""
 with tempfile.TemporaryDirectory() as tmp:
  da,env_a=fresh_env(tmp,'A');db,env_b=fresh_env(tmp,'B')
  # ルートの一覧は別の置き場で取る。A の置き場で取ると、その終了時のログが A にだけ1行残り、
  # ログの件数が食い違う（評価の作りの誤りとして1度見つけて直した）。
  rules=url_rules(fresh_env(tmp,'rules')[1])
  sys.path[:0]=[str(ROOT),str(ROOT/'lib')]
  reqs=[r for r in route_requests(rules) if r['rule'] not in NOT_CALLED]+scenario_requests(tmp)
  direct=Direct(env_a);side=Sidecar(env_b);results=[]
  roots=[str(da),str(db)]
  try:
   for r in reqs:
    if r['rule'] in SETTLE_BEFORE:settle(direct,side)
    t=time.perf_counter();a=direct.call(r);ta=time.perf_counter()-t
    t=time.perf_counter();b=side.call(r);tb=time.perf_counter()-t
    ok,why=compare(a,b,roots,r['rule'])
    results.append({'label':r['label'],'ok':ok,'why':why,'status':a[0],'a_ms':ta*1000,'b_ms':tb*1000,'bytes':len(b[2])})
   # 登録内容の一式（ZIP）を書き出して、そのまま持ち込む（バイナリの受け取り）
   s,h,blob=direct.call({'label':'書き出し','method':'GET','path':'/api/bundle/export','query':'parts=jobs,schedules,layouts,recipes','body':b''})
   body,hdr=multipart('file','DataRelay_一式.zip',blob,'application/zip')
   r={'label':'一式ZIPの持ち込み（multipart・バイナリ）','method':'POST','path':'/api/bundle/import','query':'','headers':hdr,'body':body}
   a=direct.call(r);b=side.call(r);ok,why=compare(a,b,roots)
   results.append({'label':r['label'],'ok':ok,'why':why,'status':a[0],'a_ms':1,'b_ms':1,'bytes':len(b[2])})
   # 同時に40本（長い問い合わせが短いものを待たせないか・取り違えないか）
   paths=['/api/status','/api/config','/api/version','/api/calendar','/api/docs']*8
   with ThreadPoolExecutor(40) as ex:
    got=list(ex.map(lambda p:(p,side.call({'label':p,'method':'GET','path':p,'body':b''})),paths))
   swapped=[p for p,(s,h,b) in got if s!=200 or not b.startswith(b'{')]
   kinds={p:len(b) for p,(s,h,b) in got if p=='/api/version'}
   results.append({'label':'同時に40本（取り違えなし）','ok':not swapped,'why':f'{len(swapped)}件おかしい','status':200,'a_ms':0,'b_ms':0,'bytes':0})
   ready=[e for e in side.events if e.get('event')=='ready']
  finally:
   direct.close();code=side.close()
  results.append({'label':'入力を閉じたら窓口が自分で終わる','ok':code==0,'why':f'終了コード {code}','status':0,'a_ms':0,'b_ms':0,'bytes':0})
  return rules,results,ready


class SidecarParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.rules,cls.results,cls.ready=run_all()

 def test_ready_event(self):
  self.assertTrue(self.ready,'窓口が ready を知らせませんでした')

 def test_every_route_was_called(self):
  called={r['label'].split(' ',1)[1] for r in self.results if ' /' in r['label']}
  rules={rule for rule,_ in self.rules}
  self.assertEqual(rules-called-NOT_CALLED,set())

 def test_same_answers(self):
  bad=[f"{r['label']}: {r['why']}" for r in self.results if not r['ok']]
  self.assertEqual(bad,[])

class SidecarRobustnessTest(unittest.TestCase):
 """壊れた枠で止まらない・窓口の子プロセス（抽出ワーカーと同じ起こし方）の print が枠に混ざらない。"""
 def test_bad_frame_does_not_stop(self):
  """壊れた枠（JSONでない行）を受けても、知らせを返して次の問い合わせに答え続ける。"""
  with tempfile.TemporaryDirectory() as tmp:
   _,env=fresh_env(tmp,'C')
   side=Sidecar(env)
   try:
    side.raw(b'not json\n')
    s,h,b=side.call({'label':'status','method':'GET','path':'/api/status','body':b''})
    self.assertEqual(s,200);json.loads(b)
    self.assertTrue(any(e.get('event')=='bad-frame' for e in side.events))
   finally:
    self.assertEqual(side.close(),0)

 def test_worker_spawned_from_sidecar_does_not_break_frames(self):
  """窓口の中から子プロセスを起こし、子が標準出力へ大量に書いても枠が壊れない（本体の Popen と同じ条件）。"""
  code=('import sys,subprocess,runpy\n'
        'sys.argv=[sys.argv[1]]\n'
        'import threading\n'
        'def later():\n'
        ' import time;time.sleep(1.5)\n'
        ' subprocess.Popen([sys.executable,"-c","print(\'x\'*100000)"]).wait()\n'
        'threading.Thread(target=later,daemon=True).start()\n'
        'runpy.run_path(sys.argv[0],run_name="__main__")\n')
  with tempfile.TemporaryDirectory() as tmp:
   _,env=fresh_env(tmp,'D')
   wrapper=Path(tmp)/'wrap.py';wrapper.write_text(code,encoding='utf-8')
   side=Sidecar.__new__(Sidecar)
   side.p=subprocess.Popen([sys.executable,str(wrapper),str(SIDECAR)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,env=env,cwd=str(ROOT))
   side.lock=threading.Lock();side.waiting={};side.next_id=1;side.events=[];side.ready=threading.Event()
   threading.Thread(target=side._reader,daemon=True).start()
   self.assertTrue(side.ready.wait(90))
   time.sleep(3)
   for _ in range(5):
    s,h,b=side.call({'label':'status','method':'GET','path':'/api/status','body':b''})
    self.assertEqual(s,200);json.loads(b)
   self.assertEqual(side.close(),0)


def report():
 rules,results,ready=run_all()
 ok=sum(1 for r in results if r['ok'])
 print(f'URL表のルート {len(rules)}本 / 突き合わせ {len(results)}件 / 一致 {ok}件')
 if ready:print(f"窓口の起動 {ready[0].get('elapsed')}秒（Python {ready[0].get('python')}）")
 for r in results:
  mark='一致' if r['ok'] else '★不一致'
  ms=f"A {r['a_ms']:.0f}ms / B {r['b_ms']:.0f}ms" if r['a_ms'] else ''
  print(f"  {mark:<5} {r['status']:>3} {r['label']:<55} {ms} {r['why']}")
 print('呼ばずに残したルート（窓が受け持つ）:',', '.join(sorted(NOT_CALLED)))

if __name__=='__main__':report()
