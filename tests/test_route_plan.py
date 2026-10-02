"""移行先の割り当て（migration/route_plan.json）が、中身（Python）の URL 表と窓（Rust）の振り分けの両方と食い違っていないか。

ルートを足した・消したのに割り当てを直し忘れると「行き先の決まっていないルート」が出る。窓へ移したのに中身にも
残っている受け口は、誰も呼ばない古い処理（tkinter・os._exit など）として残り続ける。それをここで止める。
実行: python -m unittest tests.test_route_plan -v
"""
import json,os,re,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PLAN=ROOT/'migration'/'route_plan.json'
DESTINATIONS={'python','rust','python+rust','remove'}

def shell_routes():
 """窓（desktop/src）が自分で答えるルート。main.rs の native の ("POST", "/api/…") と、router.rs の / と /static/。"""
 src=ROOT/'desktop'/'src'
 main=(src/'main.rs').read_text(encoding='utf-8');router=(src/'router.rs').read_text(encoding='utf-8')
 out={f'{m} {p}' for m,p in re.findall(r'\("(GET|POST)", "(/api/[^"]+)"\)',main)}
 if 'path == "/"' in router:out.add('GET /')
 if 'strip_prefix("/static/")' in router:out.add('GET /static/<path:filename>')
 return out


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
  cls.shell=shell_routes()

 def test_every_route_has_a_destination(self):
  self.assertEqual(sorted(self.routes-set(self.plan)),[],'URL表にあって割り当てに無いルート')

 def test_python_routes_are_served_by_python(self):
  bad=[k for k,v in self.plan.items() if v['to'] in ('python','python+rust') and k not in self.routes]
  self.assertEqual(bad,[],'中身が答えるはずなのに URL表に無いルート')

 def test_rust_routes_are_served_by_the_window_only(self):
  """窓へ移したルートは窓の振り分けにあり、中身からは外してある（呼ばれない古い処理を残さない）。"""
  rust=[k for k,v in self.plan.items() if v['to'] in ('rust','python+rust')]
  self.assertEqual([k for k in rust if k not in self.shell],[],'窓へ移したはずなのに窓の振り分けに無いルート')
  self.assertEqual([k for k,v in self.plan.items() if v['to']=='rust' and k in self.routes],[],'窓へ移したのに中身にも残っているルート')

 def test_removed_routes_are_gone(self):
  gone=[k for k,v in self.plan.items() if v['to']=='remove' and (k in self.routes or k in self.shell)]
  self.assertEqual(gone,[],'外したはずなのに残っているルート')

 def test_window_routes_are_in_the_plan(self):
  """窓が自分で答える /api/… も、割り当てに載っている（窓だけに足して記録し忘れることを防ぐ）。"""
  self.assertEqual(sorted(k for k in self.shell if k not in self.plan),[])

 def test_destinations_are_known(self):
  bad={k:v['to'] for k,v in self.plan.items() if v.get('to') not in DESTINATIONS or not v.get('area')}
  self.assertEqual(bad,{})

 def test_moved_or_removed_routes_say_why(self):
  """Python のまま以外（窓へ移す・外す）は、理由を書いておく。"""
  bad=[k for k,v in self.plan.items() if v['to']!='python' and not v.get('note')]
  self.assertEqual(bad,[])
