"""移行先の割り当て（migration/route_plan.json）が、アプリの URL 表と食い違っていないか。

ルートを足した・消したのに割り当てを直し忘れると、移行のときに「行き先の決まっていないルート」が出る。
それをここで止める。実行: python -m unittest tests.test_route_plan -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PLAN=ROOT/'migration'/'route_plan.json'
DESTINATIONS={'python','rust','python+rust','remove'}

class RoutePlanTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.plan=json.loads(PLAN.read_text(encoding='utf-8'))['routes']
  code=("import sys,json;sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib'];import app;"
        "print(json.dumps(sorted(f'{m} {r.rule}' for r in app.app.url_map.iter_rules() "
        "for m in r.methods if m not in ('HEAD','OPTIONS'))))")
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_CONFIG_DIR=str(Path(d)/'config'),PYTHONIOENCODING='utf-8')
   out=subprocess.run([sys.executable,'-c',code,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
  cls.routes=set(json.loads(out.stdout.strip().splitlines()[-1]))

 def test_every_route_has_a_destination(self):
  self.assertEqual(sorted(self.routes-set(self.plan)),[],'URL表にあって割り当てに無いルート')

 def test_no_stale_entries(self):
  self.assertEqual(sorted(set(self.plan)-self.routes),[],'割り当てにあって URL表に無いルート')

 def test_destinations_are_known(self):
  bad={k:v['to'] for k,v in self.plan.items() if v.get('to') not in DESTINATIONS or not v.get('area')}
  self.assertEqual(bad,{})

 def test_moved_or_removed_routes_say_why(self):
  """Python のまま以外（窓へ移す・外す）は、理由を書いておく。"""
  bad=[k for k,v in self.plan.items() if v['to']!='python' and not v.get('note')]
  self.assertEqual(bad,[])
