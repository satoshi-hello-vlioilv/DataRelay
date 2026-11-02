"""読取マスタ・結合マスタ・クエリの一覧と書き出しが、Python（navi_web）と Rust（desktop/core の masters.rs）で同じか（2.20.0）。

設定の写しの見本を Python 自身に作らせ（tests/test_rust_config.py と同じ作り方）、同じ問い合わせを両方へ送って比べる。
一覧（JSON）は値で、書き出し（持ち出しのファイル）は中身のバイト列・Content-Type・Content-Disposition まで比べる。
EXCEL の書き出しは、Rust が答えず Python へ回すことを確かめる。
実行: python -m unittest tests.test_rust_masters -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402
from test_rust_paths import ref_python  # noqa: E402
from test_rust_config import MAKE,FIXED,full_cfg,layout_sql,canon  # noqa: E402

ASK=r"""
import base64,json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app,navi_web,navi_text,navi_join,navi_mrun
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
for m in (navi_web,navi_text,navi_join,navi_mrun):m.datetime=Fixed
t=app.app.test_client();out=[]
for path in json.loads(sys.stdin.read()):
 r=t.get(path)
 out.append({'status':r.status_code,'body':base64.b64encode(r.get_data()).decode(),
             'type':r.headers.get('Content-Type',''),'disposition':r.headers.get('Content-Disposition','')})
print(json.dumps(out))
"""

EXTRA_SQL=[
 ['INSERT INTO m_queries (id,display_order,name,description,code,output_query,updated_at) VALUES(?,?,?,?,?,?,?)',
  ['Q2',1,'月次/集計:\n"一覧"','説明','let\n x = "あ"\nin x','','2026-11-01T00:00:00']],
 ['INSERT INTO text_layouts (id,display_order,name,description,encoding,unit,trim,skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at,parse_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
  ['L3',2,'区切り・正規表現','','utf-8','char','both',0,0,1,0,json.dumps([{'name':'a','field':3},{'name':'b','field':3},{'name':'c','field':6}]),'','2026-11-01T00:00:00',
   json.dumps({'mode':'delimited','delimiter':'regex','delimiter_text':'\\s+'})]],
 ['INSERT INTO text_layouts (id,display_order,name,description,encoding,unit,trim,skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at,parse_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
  ['L4',3,'タブ区切り 改行入り\x01','','cp932','byte','both',0,0,1,0,json.dumps([{'name':'x','start':5,'length':3},{'name':'y','start':1,'length':2},{'name':'z','start':6,'length':4}]),'','2026-11-01T00:00:00','']],
]

PATHS=['/api/text-layouts','/api/join-recipes',
       '/api/text-layouts/export','/api/text-layouts/export?ids=L1','/api/text-layouts/export?ids=L1,%20L2,L3','/api/text-layouts/export?format=JSON&ids=,,',
       '/api/join-recipes/export','/api/join-recipes/export?ids=nothing',
       '/api/m-queries/export','/api/m-queries/export?format=m&ids=Q2','/api/m-queries/export?format=M&ids=Q1','/api/m-queries/export?format=m']
TO_PYTHON=['/api/text-layouts/export?format=xlsx','/api/join-recipes/export?format=XLSX']


class MastersParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.exe=core_exe()
  if not cls.exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.tmp=tempfile.TemporaryDirectory();cls.t=Path(cls.tmp.name).resolve()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def env(self,name):
  d=self.t/name
  return dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),
              NAVI_CONFIG_DIR=str(d/'data'/'Config'),NAVI_SECRET_FILE=str(d/'s.json'))

 def run_py(self,code,name,stdin,*args):
  r=subprocess.run([ref_python(),'-c',code,str(ROOT),*args],input=stdin,env=self.env(name),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().split('\n')[-1])

 def rust(self,name,paths):
  lines=''.join(json.dumps({'method':'GET','path':p.split('?')[0],'query':p.split('?',1)[1] if '?' in p else '','body':''})+'\n' for p in paths)
  r=subprocess.run([str(self.exe),'answer','--base',str(ROOT)],input=lines,env=dict(self.env(name),DATARELAY_FIXED_NOW=FIXED),cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return [json.loads(x) for x in r.stdout.split('\n') if x.strip()]

 def test_lists_and_exports(self):
  self.run_py(MAKE,'m',json.dumps({'cfg':full_cfg(''),'sql':layout_sql()+EXTRA_SQL},ensure_ascii=False))
  rs=self.rust('m',PATHS+TO_PYTHON)
  py=self.run_py(ASK,'m',json.dumps(PATHS),FIXED)
  import base64
  bad=[]
  for path,p,x in zip(PATHS,py,rs):
   head=dict(x['headers']) if isinstance(x['headers'],list) else {}
   if x['status']!=p['status']:bad.append(f'{path}: 番号 Python={p["status"]} Rust={x["status"]}');continue
   pb=base64.b64decode(p['body']).decode('utf-8')
   if p['type'].startswith('application/json') and not p['disposition']:
    if canon(json.loads(pb))!=canon(json.loads(x['body'])):
     a,b=json.loads(pb),json.loads(x['body'])
     bad.append(f'{path}: '+'; '.join(f'{k}: PY={canon(a.get(k))[:400]} RS={canon(b.get(k))[:400]}' for k in sorted(set(a)|set(b)) if canon(a.get(k))!=canon(b.get(k))))
   else:
    if pb!=x['body']:bad.append(f'{path}: 中身が違う\n  PY={pb[:600]!r}\n  RS={x["body"][:600]!r}')
    for k,v in (('Content-Type',p['type']),('Content-Disposition',p['disposition'])):
     if head.get(k)!=v:bad.append(f'{path}: {k} Python={v!r} Rust={head.get(k)!r}')
  self.assertEqual(bad,[],'\n'.join(bad))
  for path,x in zip(TO_PYTHON,rs[len(PATHS):]):
   self.assertEqual(x['status'],0,f'{path}: EXCEL の書き出しは Python へ回すはず')
  # 見本が中身を持っていること（空どうしを比べて合格にしない）
  first=json.loads(base64.b64decode(py[0]['body']))
  self.assertGreaterEqual(len(first['items']),4)
  self.assertTrue(any(x['overlaps'] for x in first['items']) and any(x['gaps'] for x in first['items']) and any(x['used_by'] for x in first['items']))
  self.assertIn('.pq',py[9]['disposition'])

 def test_not_settled_goes_to_python(self):
  """写しを替える場合（ここではマスターが無い）は、一覧も書き出しも Rust が答えない。"""
  paths=self.run_py(MAKE,'n',json.dumps({'cfg':{'jobs':[]}}))
  os.remove(paths['master'])
  for x in self.rust('n',PATHS):self.assertEqual(x['status'],0)


if __name__=='__main__':unittest.main()
