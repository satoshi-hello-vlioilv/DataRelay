"""結合マスタの組み立てを助ける受け口のうち、設定から答える物が、Python（navi_web・navi_joinrun・navi_order・navi_localcopy）と
Rust（desktop/core の joinplan.rs）で同じ答えになるか（2.27.0）。

比べるルート: GET /api/join-candidates・POST /api/join-order・POST /api/join-cache/clear
見本の設定: 決まった名前で出す対象（追加の形式つき）・名前を型で作る対象（今日の名前のファイルがある）・出力先を共通の既定から取る対象
（前回の実行の記録に別の名前のファイルが残っている）・相対の出力先・結合マスタ（自分の対象が作るファイル・読取フォルダーの名前だけの指定・無いファイル）。
写しの置き場（work\\read-cache）には、写し・控えの .json・フォルダーを置いて、数え方と消し方を比べる。
実行: python -m unittest tests.test_rust_join -v
"""
import json,os,shutil,sys,unittest

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_writes import ASK,post  # noqa: E402
from test_rust_config import MAKE  # noqa: E402

NOW='2026-11-02T09:05:07.123456'


def get(path):return {'method':'GET','path':path,'body':''}


class JoinPlanParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,rust,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','rust','twin'))

 def make(self,name,settings=None):
  a=self.t/'outA';b=self.t/'outB';a.mkdir(exist_ok=True);b.mkdir(exist_ok=True)
  for p,t in ((a/'a.csv',1767225600),(a/'日次_20261102.sqlite3',1767312000),(b/'old.txt',1767398400),(b/'在庫.csv',1767225600)):
   p.write_bytes(b'x'*7);os.utime(p,(t,t))
  cfg={'default_output_folder':str(b),'text_folder':str(b),'settings':dict({'join_wait_lookahead_seconds':'30','join_wait_poll_seconds':0},**(settings or {})),
       'jobs':[
        {'id':'j1','name':'受注','output_folder':str(a),'output_format':'csv','output_file':'a.csv','extra_formats':['xlsx'],'naming_mode':'fixed','enabled':True},
        {'id':'j2','name':'日次','output_folder':str(a),'output_format':'sqlite','naming_mode':'template','output_pattern':'{name}_{now:YYYYMMDD}','enabled':False},
        {'id':'j3','name':'在庫','output_folder':'','output_format':'txt','output_file':'b.txt'},
        {'id':'j4','name':'相対','output_folder':'.\\out','output_format':'xlsx','output_file':'r.xlsx'},
       ]}
  recipe=['INSERT INTO join_recipes (id,display_order,name,description,sources_json,joins_json,columns_json,updated_at) VALUES(?,?,?,?,?,?,?,?)',
          ['R1',0,'受注と在庫','',json.dumps([{'path':str(a/'a.csv')},{'path':'在庫.csv'},{'path':'無い.csv','format':'txt'},{'path':''}]),'[]','[]','t']]
  runs=["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j3','在庫','t','ok','manual','',1,1,'old.txt','t','')",[]]
  self.py(MAKE,name,json.dumps({'cfg':cfg,'sql':[recipe,runs]},ensure_ascii=False))
  cache=self.t/name/'local'/'work'/'read-cache';cache.mkdir(parents=True,exist_ok=True)
  (cache/'0123456789abcdef.csv').write_bytes(b'12345');(cache/'fedcba9876543210.json').write_bytes(b'{}');(cache/'sub').mkdir(exist_ok=True)
  return a,b

 def test_candidates_order_and_cache(self):
  a,_b=self.make('jbase');self.twin('jbase','jpy','jrs')
  reqs=[get('/api/join-candidates'),
        post('/api/join-order',{'recipe':{'sources':[{'path':str(a/'a.csv')},{'path':'在庫.csv'},{'path':str(a/'日次_20261102.sqlite3')},{'path':str(a/'a.xlsx')},{'path':''},{'path':'無い.csv'}]}}),
        post('/api/join-order',{}),
        post('/api/join-order','null'),
        post('/api/join-cache/clear',{}),
        get('/api/join-candidates')]
  py=self.py(ASK,'jpy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('jrs',reqs)
  for q,p,x in zip(reqs,py,rs):
   what=f'{q["method"]} {q["path"]} {q.get("body","")[:100]}'
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {what}')
   # 写しの置き場（jpy・jrs）の中を指す道は、置き場の名前だけ同じ字に直して比べる（相対の出力先・写しの置き場）
   a1,b1=(json.loads(t.replace('/jpy/','/J/').replace('/jrs/','/J/').replace('\\\\jpy\\\\','\\\\J\\\\').replace('\\\\jrs\\\\','\\\\J\\\\')) for t in (p['body'],x['body']))
   self.assertEqual((x["status"],b1),(p["status"],a1),what)
  first=json.loads(py[0]['body']);order=json.loads(py[1]['body'])
  # 見本が中身を持っていること
  self.assertGreaterEqual(len(first['items']),6);self.assertTrue(any(i['exists'] for i in first['items']) and any(i['role']=='recipe' for i in first['items']))
  self.assertEqual(first['cache']['count'],1)
  self.assertEqual(order['made_count'],3);self.assertEqual(order['wait'],{'enabled':True,'lookahead':30,'max_wait':600,'poll':5})
  self.assertEqual(json.loads(py[4]['body'])['removed'],2,'写しと控えを消し、フォルダーは消さない')

 def test_python_only_cases(self):
  """待つ設定が int() で読めない値（Python は落ちる）・辞書でない本文は、Python へ回す。"""
  self.make('jbad',settings={'join_wait_max_seconds':'abc'})
  rs=self.rust('jbad',[post('/api/join-order',{'recipe':{}}),post('/api/join-order','[1]'),post('/api/join-order',{'recipe':[1]})])
  self.assertEqual([x['status'] for x in rs],[0,0,0])
  os.remove(self.paths('jbad')[1])
  self.assertEqual(self.rust('jbad',[get('/api/join-candidates')])[0]['status'],0,'写しを替える場合は回す')


if __name__=='__main__':unittest.main()
