"""画面からの書き込み（列の決め方・カレンダーからの1回実行ルール・自動実行の一時停止・読取マスタと結合マスタの保存・
マスタ3種の削除）が、Python（navi_web・navi_textrun・navi_joinrun・navi_mrun）と Rust（desktop/core の edits.rs・masters.rs）で
同じ結果になるか（2.23.0）。

tests/test_rust_save.py と同じく、同じ設定の写しを2つ用意し（片方を Python、片方を Rust が受け持つ）、同じ問い合わせを
同じ順で流して、答えと、写しの中身（設定・実行ルール・マスタ・運転の状態・版）と、書き戻したマスターの中身を比べる。
新しく振る id（uuid）は、出てきた順の印に置き換えて比べる。
Python でしか同じに決められない場合（正規表現の区切り・FULL JOIN・全角の数字・時差付きの時刻など）と、
いま Python が読めば写しを替える場合は、Rust が書かずに Python へ回すことも確かめる。
比べるルート: POST /api/settings/columns・POST /api/schedule/quick-add・POST /api/schedule-pause・POST /api/text-layouts・
DELETE /api/text-layouts/<layout_id>・POST /api/join-recipes・DELETE /api/join-recipes/<recipe_id>・DELETE /api/m-queries/<query_id>
実行: python -m unittest tests.test_rust_writes -v
"""
import json,os,re,sqlite3,subprocess,sys,unittest
from contextlib import closing

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_config import MAKE,full_cfg,layout_sql  # noqa: E402

NOW='2026-11-02T09:05:07.123456'

ASK=r"""
import json,sys,time
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app,navi_web,navi_textrun,navi_joinrun,navi_mrun
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
for m in (app,navi_web,navi_textrun,navi_joinrun,navi_mrun):m.datetime=Fixed
t=app.app.test_client();out=[]
for q in json.loads(sys.stdin.read()):
 r=t.open(q['path'],method=q['method'],data=q.get('body','').encode('utf-8'),headers={'Content-Type':q.get('type','application/json')})
 out.append({'status':r.status_code,'body':r.get_data(as_text=True)})
deadline=time.time()+60
while app.settings_flush_pending() and time.time()<deadline:time.sleep(0.05)
print(json.dumps(out))
"""

NEW_ID=re.compile(r'^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$')


class Masker:
 """新しく振った id を、出てきた順の印へ（Python と Rust で乱数が違うので）。"""
 def __init__(self):self.m={}
 def __call__(self,v):
  if isinstance(v,dict):return {k:self(x) for k,x in v.items()}
  if isinstance(v,list):return [self(x) for x in v]
  if isinstance(v,str) and NEW_ID.match(v):
   self.m.setdefault(v,f'<new{len(self.m)+1}>');return self.m[v]
  if isinstance(v,str) and v[:1] in '[{':
   try:return json.dumps(self(json.loads(v)),ensure_ascii=False)
   except ValueError:return v
  return v


def dump(db):
 """写しの中身（比べる物）。並びは並び順と id。"""
 with closing(sqlite3.connect(str(db))) as c:
  c.row_factory=sqlite3.Row
  rows=lambda sql:[dict(r) for r in c.execute(sql)]
  return {'app_settings':rows('SELECT key,value,value_type,updated_at FROM app_settings ORDER BY key'),
          'jobs':rows('SELECT * FROM jobs ORDER BY display_order'),
          'schedules':rows('SELECT * FROM schedules ORDER BY job_id,display_order'),
          'text_layouts':rows('SELECT * FROM text_layouts ORDER BY display_order,name'),
          'join_recipes':rows('SELECT * FROM join_recipes ORDER BY display_order,name'),
          'm_queries':rows('SELECT * FROM m_queries ORDER BY display_order,name'),
          'scheduler_state':rows('SELECT * FROM scheduler_state ORDER BY state_key'),
          'revision':c.execute("SELECT value FROM schema_info WHERE key='settings_revision'").fetchone()[0]}


def post(path,body,**k):return {'method':'POST','path':path,'body':body if isinstance(body,str) else json.dumps(body,ensure_ascii=False),**k}
def delete(path):return {'method':'DELETE','path':path,'body':''}


LAYOUT={'name':' 受注 ','encoding':'SJIS','unit':'CHAR','trim':'x','skip_head':'2','skip_tail':-1,'skip_blank':0,
        'columns':[{'name':'日付','start':1,'length':8,'type':'date'},{'name':'時刻','start':9,'end':24,'type':'datetime','format':'YYYY/MM/DD HH:MI'},
                   {'start':'x','length':'3','type':'real','scale':12},{'name':'数','start':30,'length':4,'type':'int'}],
        'sample_path':' s.txt ','note':'余計な鍵'}
BAD_LAYOUT={'name':'','columns':[{'name':'a','start':1,'length':0},{'name':'a','start':2,'length':2,'type':'date','format':'MMDD'},
                                 {'name':'b','start':5,'length':4,'type':'datetime','format':'YYYYMMDD'},{'name':'c','start':9,'length':4,'type':'date','format':'YYYYMMDD'},
                                 {'name':'d','type':'date','format':'/-'}]}
DELIM={'name':'区切り','mode':'delimited','delimiter':'custom','delimiter_text':' | ','quote':'single','collapse':1,
       'columns':[{'name':'x'},{'name':'y','field':5},{'name':'z','field':5}]}
RECIPE={'name':' 受注と品目 ','sources':[{'path':'a.csv'},{'path':'b.xlsx','sheet':'S'},{'path':'t.txt','format':'text','layout_id':'L1'}],
        'joins':[{'type':'LEFT','keys':[{'left':'k','right':'k'},{'left':'','right':' '}]},{'keys':[{'left':'k','right':'品番'}]}],'columns':[{'name':'k'},{'name':'v','as':'値','source':'B'},{'name':''}]}
BAD_RECIPE={'name':'','sources':[{'path':''},{'format':'fixed'}],'joins':[{'keys':[{'left':'a'}]}],'columns':[{'name':'x'},{'name':'y','as':'x'}]}


class WritesParityTest(unittest.TestCase):
 # 写しの用意と、両方への問い合わせは test_rust_save の道具を借りる（保存の試験そのものは借りない）
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,rust,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','rust','twin'))

 def make(self,name):
  cfg=full_cfg('')
  cfg['jobs'][4]['post']={'enabled':True,'mode':'query','query_id':'Q3'}   # 後処理で使うクエリも「使っている」
  self.py(MAKE,name,json.dumps({'cfg':cfg,'sql':layout_sql()+[
   ['INSERT INTO m_queries (id,display_order,name,description,code,output_query,updated_at) VALUES(?,?,?,?,?,?,?)',['Q2',1,'使わない','','let a=1 in a','','t']],
   ['INSERT INTO m_queries (id,display_order,name,description,code,output_query,updated_at) VALUES(?,?,?,?,?,?,?)',['Q3',2,'後処理','','let a=1 in a','','t']],
   ["INSERT INTO scheduler_state VALUES('other','x','t')",[]]]},ensure_ascii=False))

 def test_write_sequence(self):
  self.make('wbase');self.twin('wbase','wpy','wrs')
  reqs=[
   post('/api/settings/columns',{'layout':{'order':['name','name','',1,'x'*40],'hidden':'abc','opt':{'name':{'w':120,'s':'y'*70,'l':[1,None,'z'],'d':{}},'bad':3}}}),
   post('/api/settings/columns',{'other':1}),
   post('/api/settings/columns',{'layout':{}},type='text/plain'),
   post('/api/settings/columns',{'layout':{}}),                     # 全部既定に戻す
   post('/api/schedule/quick-add',{'job_id':'j1','date':' 2026-12-24 ','time':'9:5'},type='text/plain'),
   post('/api/schedule/quick-add',{'job_id':'j2','date':'2026-11-03','time':' ','name':'臨時'}),
   post('/api/schedule/quick-add',{'job_id':'j1','date':'2026-11-02','time':'09:05'}),     # 過ぎている（同じ分）
   post('/api/schedule/quick-add',{'job_id':'j1','date':'2026-02-30'}),
   post('/api/schedule/quick-add',{'job_id':'j1','date':'2026/12/01'}),
   post('/api/schedule/quick-add',{'job_id':'nothing','date':'2026-12-01'}),
   post('/api/schedule/quick-add',{'job_id':'j1'}),
   post('/api/schedule/quick-add','null'),
   post('/api/schedule-pause',{'paused':True,'until':'2026-11-20T08:30:59'}),
   post('/api/schedule-pause',{'paused':1,'until':''}),                                    # 止めたまま → 止めた時刻は前のまま
   post('/api/schedule-pause',{'paused':True,'until':'2026-11-01'}),
   post('/api/schedule-pause',{'paused':True,'until':'あした'}),
   post('/api/schedule-pause',{'paused':True,'until':'2026-13-01T00:00'}),
   post('/api/schedule-pause',{'paused':False,'until':'x'}),
   post('/api/schedule-pause',{'paused':True},type='text/plain'),                        # JSON の印が無い → 戻す
   post('/api/schedule-pause',{'paused':'yes','until':'2026-12-01'}),
   post('/api/text-layouts',LAYOUT),
   post('/api/text-layouts',BAD_LAYOUT),
   post('/api/text-layouts',DELIM),
   post('/api/text-layouts',dict(DELIM,delimiter_text='',name='空の区切り')),
   post('/api/text-layouts',dict(LAYOUT,id=' L1 ',name='更新した固定',columns=[{'name':'a','start':1,'length':3}])),
   post('/api/text-layouts','""'),
   post('/api/join-recipes',RECIPE),
   post('/api/join-recipes',BAD_RECIPE),
   post('/api/join-recipes',dict(RECIPE,id='R1',name='更新した結合')),
   delete('/api/text-layouts/L1'),                  # j2 が使っている → 409
   delete('/api/text-layouts/%20L2'),
   delete('/api/text-layouts/nothing'),
   delete('/api/join-recipes/R1'),                  # j3 が使っている → 409
   delete('/api/join-recipes/zzz'),
   delete('/api/m-queries/Q1'),                     # j4 が入力に使っている → 409
   delete('/api/m-queries/Q3'),                     # j5 が後処理に使っている → 409
   delete('/api/m-queries/Q2'),
   {'method':'GET','path':'/api/schedule-preview'},
  ]
  py=self.py(ASK,'wpy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('wrs',reqs)
  mp,mr=Masker(),Masker()
  for q,p,x in zip(reqs,py,rs):
   what=f'{q["method"]} {q["path"]} {q.get("body","")[:100]}'
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {what}')
   self.assertEqual((x['status'],mr(json.loads(x['body']))),(p['status'],mp(json.loads(p['body']))),what)
  self.assertEqual([p['status'] for p in py],[200,400,400,200,200,200,400,400,400,404,400,400,200,200,400,400,400,200,200,200,
                                              200,400,200,400,200,400,200,400,200,409,200,200,409,200,409,409,200,200])
  a,b=mp(dump(self.paths('wpy')[0])),mr(dump(self.paths('wrs')[0]))
  for k in a:self.assertEqual(a[k],b[k],f'写しの {k} が違う')
  # 見本が中身を持っていること（空どうしを比べて合格にしない）
  self.assertEqual(len(a['text_layouts']),3);self.assertEqual(len(a['join_recipes']),2);self.assertEqual([x['id'] for x in a['m_queries']],['Q1','Q3'])
  self.assertEqual(json.loads(a['scheduler_state'][0]['state_value']),{'since':'2026-11-02T09:05:07','until':'2026-12-01T00:00'})
  # 書き戻したマスターは、写しと同じ中身（最後の書き込みはマスタの削除で、すぐ書き戻す）
  for n,m in (('wpy',mp),('wrs',mr)):
   local,master=self.paths(n)
   self.assertEqual(m(dump(master)),m(dump(local)),f'{n}: マスターが写しと同じでない')

 def test_python_only_cases(self):
  """Python でしか同じに決められない場合は、Rust は書かずに Python へ回す。写しを替える場合（マスターが無い）も同じ。"""
  self.make('obase');self.twin('obase','opy','ors')
  before=dump(self.paths('ors')[0])
  reqs=[post('/api/text-layouts',dict(DELIM,delimiter='regex',delimiter_text=r'\s+')),
        post('/api/join-recipes',dict(RECIPE,sources=RECIPE['sources'][:2],joins=[{'type':'full','keys':[{'left':'k','right':'k'}]}])),
        post('/api/schedule/quick-add',{'job_id':'j1','date':'２０２６-12-01'}),
        post('/api/schedule-pause',{'paused':True,'until':'2026-12-01T08:00+09:00'}),
        post('/api/schedule-pause',{'paused':True,'until':'2026-12-01T08'}),
        post('/api/settings/columns','[1]'),
        post('/api/text-layouts','{bad'),
        post('/api/schedule/quick-add',{'job_id':'j1','date':'2026-12-01','name':{'x':1}})]
  self.assertEqual([x['status'] for x in self.rust('ors',reqs)],[0]*len(reqs))
  self.assertEqual(dump(self.paths('ors')[0]),before,'回したときは何も書かない')
  py=[p['status'] for p in self.py(ASK,'opy',json.dumps(reqs,ensure_ascii=False),NOW)]
  self.assertEqual(py[:2],[200,200],'Python は正規表現の区切りも FULL JOIN も確かめて保存する')
  os.remove(self.paths('ors')[1])
  self.assertEqual([x['status'] for x in self.rust('ors',[post('/api/settings/columns',{'layout':{}}),delete('/api/m-queries/Q2')])],[0,0])

 def test_from_iso_matches_python(self):
  """一時停止の「再開する時刻」の読み方（schedule.rs の from_iso）が、Python の datetime.fromisoformat と食い違わない。
  Rust が読んだ形は、Python も同じ時刻に読む。Rust が断った形は、Python も断る（形の判らない物は Python へ回す）。"""
  vals=['2026-11-20','20261120','2026-11-20T08:30','2026-11-20 08:30','2026-11-20T08:30:59','2026-11-20T08:30:59.123','2026-11-20T08:30:59.123456',
        '2026-1-20T08:30','2026-11-20T8:30','2026-11-20T08:30:60','2026-11-20T24:00','2026-02-29','0000-01-01','2026-11-20T08:30:59.1',
        'abc','20','2026','2026-11-20T08','2026-11-20T08:30Z','2026-11-20X08:30','2026-11-20T08:30:59.1234567','202611','2026-W47-1']
  code=("import json,sys\nfrom datetime import datetime\nout=[]\nfor v in json.loads(sys.stdin.read()):\n"
        " try:out.append(datetime.fromisoformat(v).isoformat())\n except ValueError:out.append(None)\nprint(json.dumps(out))")
  py=self.py(code,'iso',json.dumps(vals))
  r=subprocess.run([str(self.exe),'call'],input=''.join(json.dumps({'fn':'from_iso','args':{'value':v}})+'\n' for v in vals),
                   capture_output=True,text=True,encoding='utf-8',timeout=60)
  self.assertEqual(r.returncode,0,r.stderr)
  rs=[json.loads(x)['result'] for x in r.stdout.split('\n') if x.strip()]
  self.assertEqual(len(rs),len(vals))
  for v,p,x in zip(vals,py,rs):
   if x!='pass':self.assertEqual(x,p,v)
  self.assertGreaterEqual(sum(x!='pass' for x in rs),12,'ほとんどの形は Rust が自分で決める')


if __name__=='__main__':unittest.main()
