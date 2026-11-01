"""Rust へ移したルートが、Python と同じ答えを返すか（Rust を主にする移行の評価・2.15.0〜。migration/FEASIBILITY.md §14）。

移したルートの Python の受け口は、最後の段まで「振る舞いの基準」として残す。ここで同じ問い合わせを
Python（Flask の受け口をプロセスの中で呼ぶ）と Rust（desktop/core の datarelay-core answer）の両方へ送り、
番号と本文の JSON を比べる。場合は tests/parity/cases.json と、抽出期間の組み合わせ（ここで作る）。

Rust の答え口は `cd desktop && cargo build --locked` で desktop/target/debug/datarelay-core にできる
（CI は release）。見つからなければ止める（黙って飛ばすと、比べていないのに通ってしまう）。
実行: python -m unittest tests.test_rust_parity -v
"""
import itertools,json,os,re,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
CASES=ROOT/'tests'/'parity'/'cases.json'
EXE='datarelay-core'+('.exe' if os.name=='nt' else '')

def core_exe():
 if os.environ.get('DATARELAY_CORE'):return Path(os.environ['DATARELAY_CORE'])
 found=[p for p in (ROOT/'desktop'/'target'/k/EXE for k in ('debug','release')) if p.is_file()]
 return max(found,key=lambda p:p.stat().st_mtime) if found else None

def core_routes():
 """Rust が答えるルート（desktop/core/src/routes.rs の ROUTES）。"""
 src=(ROOT/'desktop'/'core'/'src'/'routes.rs').read_text(encoding='utf-8')
 table=src[src.index('pub const ROUTES'):]
 table=table[:table.index('];')]
 return [f'{m} {p}' for m,p in re.findall(r'\("(GET|POST|PUT|DELETE)", "(/[^"]*)", ',table)]

def matches(route,method,path):
 m,pat=route.split(' ',1)
 if m!=method:return False
 return re.fullmatch(re.sub(r'<[^>]+>','[^/]+',re.escape(pat).replace(r'\<','<').replace(r'\>','>')),path) is not None

def period_sweep():
 """抽出期間の組み合わせ（当てる先×範囲の形×単位×ずらし×日付の書き方）。月の末日・年をまたぐ・前後が逆を含む。"""
 out=[]
 samples=['2026/1/1','2026/01/01','20260101','2026-1-1','2026.01.01',' 2026/1/1 00:00:00','x','','2026/11','２０２６/１/１']
 for target,rng,unit in itertools.product(('cond','point'),('between','from','to'),('month','day')):
  for fo,to in ((-3,-1),(0,0),(-14,2),(5,-5),(-120,0),(-1000,13)):
   for s in samples[:3] if target=='point' else samples:
    out.append({'name':f'期間 {target}/{rng}/{unit} {fo}..{to} {s!r}','method':'POST','path':'/api/period-preview',
                'body':{'target':target,'range':rng,'unit':unit,'from_offset':fo,'to_offset':to,'sample':s,'control_point':'CP','cond_item':'日付'},'ignore':['now']})
 return out

PY=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
t=app.app.test_client();out=[]
for c in json.loads(sys.stdin.read()):
 kw={'data':c['raw'].encode('utf-8'),'content_type':'application/json'} if 'raw' in c else ({'json':c['body']} if 'body' in c else {})
 if 'body' in c and c['body'] is None:kw={'data':b'null','content_type':'application/json'}
 r=t.open(c['path'],method=c['method'],**kw)
 out.append({'status':r.status_code,'body':r.get_data(as_text=True)})
print(json.dumps(out,ensure_ascii=False))
"""

def ask_python(cases):
 with tempfile.TemporaryDirectory() as d:
  d=Path(d)
  env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
           NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
  r=subprocess.run([sys.executable,'-c',PY,str(ROOT)],input=json.dumps(cases,ensure_ascii=False),env=env,capture_output=True,text=True,encoding='utf-8',timeout=300)
 if r.returncode:raise AssertionError(r.stderr[-3000:])
 return json.loads(r.stdout.strip().splitlines()[-1])

def ask_rust(exe,cases):
 lines=[]
 for c in cases:
  body=c['raw'] if 'raw' in c else (json.dumps(c['body'],ensure_ascii=False) if 'body' in c else '')
  lines.append(json.dumps({'method':c['method'],'path':c['path'],'query':'','body':body},ensure_ascii=False))
 r=subprocess.run([str(exe),'answer'],input='\n'.join(lines)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=120)
 if r.returncode:raise AssertionError(r.stderr[-3000:])
 return [json.loads(x) for x in r.stdout.splitlines() if x.strip()]

def comparable(body,ignore):
 v=json.loads(body)
 if isinstance(v,dict):
  for k in ignore:v.pop(k,None)
 return v


class RustParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  exe=core_exe()
  if not exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.cases=json.loads(CASES.read_text(encoding='utf-8'))['cases']+period_sweep()
  cls.py=ask_python(cls.cases);cls.rs=ask_rust(exe,cls.cases)

 def test_same_answers(self):
  self.assertEqual(len(self.py),len(self.cases));self.assertEqual(len(self.rs),len(self.cases))
  bad=[]
  for c,p,r in zip(self.cases,self.py,self.rs):
   if r['status']==0:bad.append(f"{c['name']}: Rust が答えない（ROUTES に無い）");continue
   if p['status']!=r['status']:bad.append(f"{c['name']}: 番号 Python={p['status']} Rust={r['status']}");continue
   if c.get('compare','json')=='json':
    a,b=comparable(p['body'],c.get('ignore',[])),comparable(r['body'],c.get('ignore',[]))
    if a!=b:
     diff={k:(a.get(k),b.get(k)) for k in set(a)|set(b) if a.get(k)!=b.get(k)} if isinstance(a,dict) and isinstance(b,dict) else (a,b)
     bad.append(f"{c['name']}: {json.dumps(diff,ensure_ascii=False)[:400]}")
  self.assertEqual(bad,[],f'{len(bad)}件で Python と Rust の答えが違う')

 def test_every_core_route_is_compared(self):
  """Rust へ移したルートは、どれも1件以上の場合で比べている（移したのに比べ忘れることを防ぐ）。"""
  missing=[x for x in core_routes() if not any(matches(x,c['method'],c['path']) for c in self.cases)]
  self.assertEqual(missing,[])

 def test_sweep_is_wide(self):
  self.assertGreater(len(self.cases),300)

 def test_rust_lists_the_same_routes(self):
  """答え口が名乗るルートと、ROUTES の表（この試験と route_plan の試験が読む物）が同じ。"""
  r=subprocess.run([str(core_exe()),'routes'],capture_output=True,text=True,encoding='utf-8',timeout=60)
  self.assertEqual(json.loads(r.stdout),core_routes())
