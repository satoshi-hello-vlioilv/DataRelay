"""予定実行の巡回が、Python（app.py の schedule_key・schedule_tick・missed_schedules）と Rust（desktop/core の scheduler.rs）で
同じになるか（2.42.0・段 5e-2b）。

同じ設定の写しに、同じ順で巡回・取り直しの予約・一時停止・洗い出しを当てて、巡回ごとの答え（入れた対象・飛ばした対象・
取り直しを飛ばした数）、待機キューへ入った指令（対象・入れ方・並列ライン数・取り直しの回数）、予定の状態（鍵）、知らせを比べる。
ルールの鍵（schedule_key）は、毎日・平日・毎月（月末）・日付・一定間隔と、猶予・読めない時刻で比べる。
実行: python -m unittest tests.test_rust_scheduler -v
"""
import json,os,subprocess,sys,unittest

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_config import MAKE  # noqa: E402
from test_rust_parity import ROOT  # noqa: E402

PY=r'''
import json,sys,time
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app
CLOCK=[0.0]
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromtimestamp(CLOCK[0])
app.datetime=Fixed;time.time=lambda:CLOCK[0]
out=[]
for op in json.loads(sys.stdin.read()):
 k=op['op'];r=None
 if 'now' in op:CLOCK[0]=_dt.fromisoformat(op['now']).timestamp()
 if k=='tick':
  cfg=app.load();st=app.load_scheduler_state()
  try:
   r=app.schedule_tick(cfg,st,_dt.fromisoformat(op['now']))
   r['queued']=[[x['job_ids'],x['trigger'],x['parallel_lines'],x['attempt']] for x in app.command_queue];app.command_queue.clear()
  except Exception:r={'pass':True}
 elif k=='retry':app.schedule_retry(op['job_ids'],op['names'],op['lines'],op['attempt'],app.load())
 elif k=='pause':app.save_scheduler_state(app.SCHEDULE_PAUSE_KEY,op['value'])
 elif k=='missed':
  r=[list(x) for x in app.missed_schedules(app.load(),app.load_scheduler_state(),_dt.fromisoformat(op['since']),_dt.fromisoformat(op['now']),op['catchup'])]
 elif k=='alerts':r=[[x['kind'],x['title'],x['detail']] for x in app.alerts]
 elif k=='key':
  try:r=app.schedule_key({},op['rule'],_dt.fromisoformat(op['now']),op['grace'])
  except Exception:r={'pass':True}
 out.append(r)
print(json.dumps({'out':out,'state':app.load_scheduler_state()},ensure_ascii=False))
'''


def rule(i,kind,**kw):
 return dict({'id':i,'enabled':True,'name':i,'type':kind,'time':'06:00'},**kw)


class SchedulerParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','twin'))

 def both(self,name,cfg,ops):
  self.py(MAKE,name,json.dumps({'cfg':cfg},ensure_ascii=False));self.twin(name,name+'py',name+'rs')
  py=self.py(PY,name+'py',json.dumps(ops,ensure_ascii=False))
  r=subprocess.run([str(self.exe),'call'],input=json.dumps({'fn':'scheduler','args':{'base':str(ROOT),'ops':ops}},ensure_ascii=False)+'\n',
                   env=self.env(name+'rs'),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  rs=json.loads(r.stdout.strip().split('\n')[-1])
  if not rs.get('ok'):raise AssertionError(rs)
  rs=rs['result']
  for i,(op,p,x) in enumerate(zip(ops,py['out'],rs['out'])):self.assertEqual(x,p,f'{i}: {op}')
  self.assertEqual(rs['state'],py['state'])
  return py['out']

 def test_keys(self):
  cases=[]
  rules=[rule('d','daily'),rule('w','weekdays',weekdays=[0,4]),rule('w2','weekdays',weekdays=[]),rule('m','monthly',month_days=[-1,15]),
         rule('m0','monthly',month_days=[]),rule('s','specific_dates',dates=['2026-11-13','2026-11-30']),rule('i','interval',interval_minutes=45),
         rule('i0','interval',interval_minutes=0),rule('ioff','interval',enabled=False),rule('t','daily',time='9'),rule('bad','daily',time='25:00'),
         rule('bad2','daily',time='a:b'),rule('bad3','daily',time='1:2:3'),rule('inone','interval',interval_minutes=None),rule('tn','daily',time=None),
         rule('x','unknown'),{'id':'nt','enabled':True}]
  for now in ('2026-11-13T05:59:59','2026-11-13T06:00:00','2026-11-13T06:00:59','2026-11-13T06:01:30','2026-11-13T06:29:59','2026-11-13T06:30:00','2026-11-30T06:10:00',
              '2026-11-15T06:00:30','2026-12-31T06:05:00'):
   for g in (0,30):
    for r in rules:cases.append({'op':'key','now':now,'rule':r,'grace':g})
  out=self.both('sk',{'jobs':[]},cases)
  self.assertIn({'pass':True},out);self.assertIn('2026-11-1306:00',out)

 def test_ticks(self):
  cfg={'settings':{'schedule_catchup_minutes':30,'api_parallel_lines':3,'retry_max':2,'retry_delay_minutes':5},
       'jobs':[{'id':'j1','name':'受注','enabled':True,'schedules':[rule('r1','daily'),rule('r2','interval',interval_minutes=60),rule('r3','weekdays',weekdays=[0,2])]},
               {'id':'j2','name':'在庫','enabled':True,'schedules':[rule('r4','monthly',month_days=[-1,15],time='09:30'),rule('r5','specific_dates',dates=['2026-11-13'])]},
               {'id':'j3','name':'止めた','enabled':False,'schedules':[rule('r6','daily')]},
               {'id':'j4','name':'ルール止め','enabled':True,'schedules':[rule('r7','daily',enabled=False)]}]}
  T=lambda t:'2026-11-'+t
  ops=[{'op':'tick','now':T('13T05:59:00')},{'op':'tick','now':T('13T06:00:30')},{'op':'tick','now':T('13T06:10:00')},
       {'op':'retry','now':T('13T06:20:00'),'job_ids':['j1'],'names':['受注'],'lines':2,'attempt':1},
       {'op':'tick','now':T('13T06:24:00')},{'op':'tick','now':T('13T06:25:00')},
       {'op':'pause','now':T('13T07:00:00'),'value':json.dumps({'since':'2026-11-13T07:00:00','until':'2026-11-13T08:00'})},
       {'op':'retry','now':T('13T07:05:00'),'job_ids':['j2'],'names':['在庫'],'lines':1,'attempt':1},
       {'op':'tick','now':T('13T07:30:00')},{'op':'tick','now':T('13T08:00:30')},{'op':'tick','now':T('13T09:00:10')},
       {'op':'missed','since':T('12T05:00:00'),'now':T('13T09:00:00'),'catchup':30},
       {'op':'missed','since':T('13T05:00:00'),'now':T('13T09:00:00'),'catchup':0},
       {'op':'tick','now':T('30T09:30:00')},{'op':'tick','now':'2026-12-15T09:31:00'},{'op':'alerts'}]
  out=self.both('st',cfg,ops)
  self.assertEqual(out[0]['queued'],[],'一定間隔は初めて見た区切りを済んだことにする')
  self.assertEqual(out[1]['queued'],[[['j1','j2'],'schedule-batch:2',3,0]])
  self.assertEqual(out[5]['queued'],[[['j1'],'schedule-retry:1',2,1]])
  self.assertEqual((out[8]['skipped'],out[8]['retries']),(['j1'],1),'一時停止中は、予定も取り直しも飛ばす')
  self.assertTrue(out[11],'前の日の予定は実行中に猶予切れ')
  self.assertIn('j2',out[13]['queued'][0][0],'月末（一定間隔の j1 も区切りが変わって入る）')


if __name__=='__main__':unittest.main()
