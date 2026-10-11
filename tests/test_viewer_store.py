"""データビュワーの表示の設定の保存（2.2.0。lib/navi_viewer.py と jobs.viewer_json）。

実行: python -m unittest tests.test_viewer_store -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_viewer as NV

STORE=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_bundle
c=app.load()
c['jobs']=[{'id':'a','name':'設備単位実績','enabled':True,'source':'rne','rne':'A.RNE','rne_path':'.\\rne\\A.RNE','output_format':'sqlite3','output_file':'a.sqlite3','schedules':[],
  'viewer':{'cols':[{'key':'工程','show':True},{'key':'数量','show':False,'label':'数'}],'calc':[{'name':'着手日時（年月）','formula':'ym([着手日時])'}],
            'filters':[{'column':'工程','op':'eq','value':'研削'},{'column':'x','op':'evil','value':'1'}],'join':'or'}},
 {'id':'b','name':'仕掛ロット','enabled':True,'source':'rne','rne':'B.RNE','rne_path':'.\\rne\\B.RNE','output_format':'xlsx','output_file':'b.xlsx','schedules':[]}]
app.save(c,quiet=True)
got=app.load()
ex=navi_bundle.jobs_export(got['jobs'])
print(json.dumps({'a':got['jobs'][0]['viewer'],'b':got['jobs'][1]['viewer'],'export':[j.get('viewer') for j in (ex.get('jobs') if isinstance(ex,dict) else ex)]},ensure_ascii=False))
"""


class NormalizeTest(unittest.TestCase):
 def test_shape_and_limits(self):
  v=NV.normalize({'cols':[{'key':' 工程 ','show':True,'label':'工程'},{'key':'工程'},{'key':''},'x',{'key':'数量','show':False,'label':'数'}],
                  'calc':[{'name':'年月','formula':'ym([着手日時])'},{'name':'年月','formula':'1'},{'name':'空','formula':''},{'name':'長','formula':'x'*3000}],
                  'filters':[{'column':'工程','op':'eq','value':'研削'},{'column':'工程','op':'drop table','value':'1'},{'column':'','op':'eq'}],'join':'or'})
  self.assertEqual(v['cols'],[{'key':'工程','show':True},{'key':'数量','show':False,'label':'数'}],'同じ列は1つ。元の名前と同じ表示名は持たない')
  self.assertEqual([c['name'] for c in v['calc']],['年月','長'])
  self.assertEqual(len(v['calc'][1]['formula']),NV.FORMULA_MAX)
  self.assertEqual(v['filters'],[{'column':'工程','op':'eq','value':'研削'}],'知らない比べ方は落とす')
  self.assertEqual(v['join'],'or')
  self.assertEqual(NV.normalize(None),{})
  self.assertEqual(NV.normalize({'join':'or'}),{},'条件が無ければ「または」も持たない')

 def test_ops_match_the_screen(self):
  js=(ROOT/'static'/'viewer-model.js').read_text(encoding='utf-8')
  for op in NV.OPS:self.assertIn(f"['{op}',",js,f'画面の比べ方にも {op} がある')


class StoreTest(unittest.TestCase):
 def test_roundtrip_and_export(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',STORE,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['a'],{'cols':[{'key':'工程','show':True},{'key':'数量','show':False,'label':'数'}],'calc':[{'name':'着手日時（年月）','formula':'ym([着手日時])'}],
                           'filters':[{'column':'工程','op':'eq','value':'研削'}],'join':'or'},'保存して読み直しても同じ（壊れた条件は落ちる）')
  self.assertEqual(v['b'],{})
  self.assertEqual(v['export'],[v['a'],None],'持ち出しに入る。使っていない対象には書かない')


if __name__=='__main__':
 unittest.main()
