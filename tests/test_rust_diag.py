"""データの新しさと、場所の確かめ・直しが、Python（navi_diag・navi_web）と Rust（desktop/core の diag.rs）で同じ答えになるか（2.33.0）。

比べるルート: GET /api/freshness・POST /api/path-check・POST /api/apply-path-suggestion
- 新しさ: 予定の間隔（間隔・曜日・毎月・切ったルール・知らない種類）・実績の間隔（並びのずれた記録・読めない時刻・3回に満たない）・
  失敗・共有先へ反映できていない（理由と助言）・予定より遅れ・まだ無い・無効な対象で比べる
- 場所の確かめ: symnavim.conf（在る）・RNE（在る・置き場の名前だけ・値を差し替えて確かめる・無い対象・不正な確認対象）
- 場所の直し: 置き場の中の候補（.\… で持つ）・外の候補（絶対パス）・無い候補・不正な対象・無い対象。直したあとの設定の写しも比べる
- 見つからない物の近くを探す（find_nearby_file）・相対の候補は Python へ回す
実行: python -m unittest tests.test_rust_diag -v
"""
import json,os,sys,unittest

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_writes import ASK,Masker,dump,post  # noqa: E402
from test_rust_config import MAKE  # noqa: E402

NOW='2026-11-02T09:05:07.123456'
# 新しさの見方は navi_diag が自分の datetime で「いま」を取るので、そこも決まった日時にする
DIAG_ASK=ASK.replace('import app,navi_web,navi_textrun,navi_joinrun,navi_mrun','import app,navi_web,navi_textrun,navi_joinrun,navi_mrun,navi_diag').replace(
 'for m in (app,navi_web,navi_textrun,navi_joinrun,navi_mrun):','for m in (app,navi_web,navi_textrun,navi_joinrun,navi_mrun,navi_diag):')


def get(path):return {'method':'GET','path':path,'body':''}


class DiagParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,rust,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','rust','twin'))

 def make(self,name):
  sh=self.t/'shared';sh.mkdir(exist_ok=True)
  (sh/'symnavim.conf').write_text('x');(sh/'在庫.RNE').write_bytes(b'r');(sh/'候補.RNE').write_bytes(b'r')
  rule=lambda **k:dict({'enabled':True,'time':'06:00'},**k)
  jobs=[
   {'id':'f1','name':'毎時','enabled':True,'rne':'在庫.RNE','rne_path':str(sh/'在庫.RNE'),'schedules':[rule(type='interval',interval_minutes=30),rule(type='daily',enabled=False)]},
   {'id':'f2','name':'曜日','enabled':True,'rne':'','rne_path':str(sh/'無い.RNE'),'schedules':[rule(type='weekdays',weekdays=[0,3]),rule(type='monthly',day=1)]},
   {'id':'f3','name':'失敗','enabled':True,'schedules':[rule(type='specific_dates',dates=['2026-12-01'])]},
   {'id':'f4','name':'反映待ち','enabled':True,'schedules':[rule(type='知らない'),rule(type='interval',interval_minutes=0)]},
   {'id':'f5','name':'実績の間隔','enabled':True,'schedules':[]},
   {'id':'f6','name':'まだ無い','enabled':1},
   {'id':'f7','name':'切ってある','enabled':False},
   {'id':'f8','name':'古い','enabled':True,'rne':'在庫.RNE'},
  ]
  run=lambda i,at,st,metrics,rows=5:["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                    [i,i,at,st,'schedule:x','',rows,2,f'{i}.csv',at,json.dumps(metrics,ensure_ascii=False)]]
  hist=lambda i,at:['INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)',[i,i,at,'success','manual','',1,1,'']]
  sql=[run('f1','2026-11-02T08:50:00','success',{}),run('f2','2026-10-20T06:00:00','success',{'pending':3}),run('f3','2026-11-01T06:00:00','failed',{}),
       run('f4','2026-11-02T06:00:00','success',{'published':False,'hold_reason':'使用中','hold_waited':20,'hold_attempts':4,'hold_advice':'閉じて'},rows=None),
       run('f5','2026-11-01T09:00:00','success',{}),run('f8','2026-10-01T06:00:00','success',{'hold_advice':['a','b']}),
       *[hist('f5',t) for t in ['2026-11-01T09:00:00','2026-10-31T09:00:00','2026-10-29T21:30:00','2026-10-30T09:00:00','2026-10-28T09:00:00','壊れた']],
       *[hist('f8',t) for t in ['2026-10-01T06:00:00','2026-09-30T06:00:00']]]
  cfg={'rne_folder':str(sh),'symnavim_conf':str(sh/'symnavim.conf'),'accdb_template':str(sh/'無い.accdb'),'jobs':jobs}
  self.py(MAKE,name,json.dumps({'cfg':cfg,'sql':sql},ensure_ascii=False))
  return sh

 def test_freshness_and_paths(self):
  sh=self.make('dbase');self.twin('dbase','dpy','drs')
  for n in ('dpy','drs'):(self.t/n/'data'/'候補.conf').write_text('c')
  inside=lambda n:str(self.t/n/'data'/'候補.conf')
  pc=lambda **k:post('/api/path-check',k)
  ap=lambda **k:post('/api/apply-path-suggestion',k)
  def reqs(n):
   return [get('/api/freshness'),pc(item='symnavim_conf'),pc(item='rne',job_id='f1'),pc(item='rne',job_id='f2'),pc(item='rne',job_id='f1',value='在庫.RNE'),
           pc(item='rne',job_id='f2',value=str(sh/'候補.RNE'),expected_name=''),pc(item='rne',job_id='無い'),pc(item='bad'),pc(),
           ap(item='symnavim_conf',candidate=inside(n)),ap(item='rne',job_id='f2',candidate=str(sh/'候補.RNE')),ap(item='rne',job_id='無い',candidate=str(sh/'候補.RNE')),
           ap(item='bad',candidate=str(sh/'候補.RNE')),ap(item='rne',job_id='f2',candidate=str(sh/'無い.RNE')),ap(item='rne',job_id='f2'),get('/api/freshness')]
  py=self.py(DIAG_ASK,'dpy',json.dumps(reqs('dpy'),ensure_ascii=False),NOW)
  rs=self.rust('drs',reqs('drs'))
  same=lambda body,n:json.loads(body.replace(json.dumps(str(self.t/n))[1:-1],'ENV'))
  for q,p,x in zip(reqs('dpy'),py,rs):
   what=f'{q["method"]} {q["path"]} {q.get("body","")[:120]}'
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {what}')
   self.assertEqual((x['status'],same(x['body'],'drs')),(p['status'],same(p['body'],'dpy')),what)
  b=[json.loads(p['body']) for p in py]
  # 見本が中身を持っていること
  st={x['id']:x for x in b[0]['items']}
  self.assertEqual([x['id'] for x in b[0]['items']][:2],['f3','f4'])
  self.assertEqual({k:st[k]['state'] for k in st},{'f1':'ok','f2':'stale','f3':'failed','f4':'held','f5':'ok','f6':'never','f8':'stale'})
  self.assertEqual((st['f1']['expect_minutes'],st['f2']['expect_minutes'],st['f4']['expect_minutes'],st['f5']['expect_source'],st['f8']['expect_source']),
                   (30,4320,1,'observed','default'))
  self.assertEqual(st['f4']['hold_advice'],['閉', 'じ', 'て'])
  self.assertTrue(b[2]['ok'] and not b[3]['ok'] and b[3]['tried'] and b[5]['ok'])
  self.assertEqual(b[9]['path'],'.\\候補.conf');self.assertEqual(b[10]['path'],str(sh/'候補.RNE'))
  self.assertEqual([py[i]['status'] for i in (6,7,11,12,13,14)],[404,400,404,400,400,400])
  a,c=Masker()(dump(self.paths('dpy')[0])),Masker()(dump(self.paths('drs')[0]))
  for k in a:self.assertEqual(a[k],c[k],f'写しの {k} が違う')

 def test_python_only_cases(self):
  """見つからない物の近くを探す・相対の候補・本文が辞書でない・予定の値が int() で読めない、は Python へ回す。"""
  sh=self.make('donly')
  rs=self.rust('donly',[post('/api/path-check',{'item':'accdb_template'}),post('/api/path-check',{'item':'rne','job_id':'f8','value':'無い.RNE'}),
                        post('/api/apply-path-suggestion',{'item':'rne','job_id':'f2','candidate':'候補.RNE'}),post('/api/path-check','null'),
                        post('/api/apply-path-suggestion','[1]')])
  self.assertEqual([x['status'] for x in rs],[0,0,0,0,0])
  self.assertTrue(sh.is_dir())
  # 実行の時刻が Rust で同じに読めない形（小数の秒が1桁）なら、新しさは Python へ回す
  self.make('dfrac')
  self.py(MAKE,'dfrac',json.dumps({'sql':[["UPDATE job_runs SET finished_at='2026-10-01T06:00:00.5' WHERE job_id='f8'",[]]]}))
  self.assertEqual(self.rust('dfrac',[get('/api/freshness')])[0]['status'],0)


if __name__=='__main__':unittest.main()
