"""予定の決まりと、予定を読む受け口が、Python（app.py・navi_web）と Rust（desktop/core の schedule.rs）で同じか（2.21.0）。

  1) 関数ごと … next_occurrence・expand_rule_occurrences・job_schedule_preview・schedule_pause・last_run_info と、
                実績の「/ 12.3秒」の拾い方へ、決まった種で作ったいろいろなルール（型・時刻・曜日・月日・特定日に数・字・真偽・並びが
                混ざる物）と日時を入れて比べる。Python が落ちる値では、Rust は答えない（Python へ回す）。
  2) ルート   … 設定の見本（予定・実行の記録・前回の実行・一時停止）を Python 自身に作らせ、/api/schedule-preview・/api/calendar・
                /api/job-trend/<job_id> の答えを、決まった日時で読み比べる。
実行: python -m unittest tests.test_rust_schedule -v
"""
import json,os,random,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402
from test_rust_paths import ref_python  # noqa: E402
from test_rust_config import MAKE,FIXED,canon  # noqa: E402

PY_FN=r"""
import json,re,sys
from datetime import datetime
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
def dt(a,k='dt'):return datetime.fromisoformat(a[k])
def iso(x):return x.isoformat(timespec='seconds') if x else None
def seconds(detail):
 m=re.search(r'/\s*([\d.]+)秒',str(detail or ''))
 if not m:return None
 try:return float(m.group(1))
 except Exception:return None
def expand(a):
 p,d=app.expand_rule_occurrences(a['rule'],dt(a,'start'),dt(a,'end'))
 return [[iso(x) for x in p],d]
F={'next_occurrence':lambda a:iso(app.next_occurrence(a['rule'],dt(a))),
   'expand_rule_occurrences':expand,
   'job_schedule_preview':lambda a:app.job_schedule_preview(a['job'],dt(a)),
   'schedule_pause':lambda a:app.schedule_pause(a['state'],dt(a)),
   'last_run_info':lambda a:app.last_run_info(a['run']),
   'seconds_in':lambda a:seconds(a['detail'])}
out=[]
for q in json.loads(sys.stdin.read()):
 try:out.append({'ok':True,'result':F[q['fn']](q['args'])})
 except Exception as e:out.append({'ok':False,'error':f'{type(e).__name__}: {e}'})
print(json.dumps(out))
"""

TIMES=['06:00','23:59','00:00','7:5',' 9:30 ','０８:１５','25:00','12:60','-1:00','bad','12','1:2:3','',None,'99999999999999999999:00']
NOWS=['2026-11-02T09:00:00','2026-11-30T23:59:59','2026-12-31T22:00:00','2024-02-28T06:00:00','2026-01-01T00:00:00.500000','2026-03-15T06:00:00']


def gen_rule(r):
 kind=r.choice(['daily','weekdays','monthly','specific_dates','interval','interval','weird',None])
 rule={'enabled':r.choice([True,True,True,False,1,0,'x']),'time':r.choice(TIMES)}
 if kind is not None:rule['type']=kind
 if r.random()<0.6:rule['weekdays']=r.choice([[0,1,2,3,4],[5,6],[1.0,True],['0','1'],[],'135',3,[[1]],{'2':1},None,[False]])
 if r.random()<0.6:rule['month_days']=r.choice([[1,15],[-1],[-1.0,31],[29,30,31],['1'],[],7,[[1]],None,[True]])
 if r.random()<0.6:rule['dates']=r.choice([['2026-12-01','2026-11-03'],['2026-1-5','x','2027-02-29'],['２０２６-１２-２５'],['2026-13-01'],'2026-12-01',[20261201],[],None,['2026-11-02','2026-11-02'],['99999999999999999999-1-1']])
 if r.random()<0.5:rule['interval_minutes']=r.choice([15,60,0,1,1441,7.9,'30','x',None,True,-5])
 return rule


def cases(seed=20261103):
 r=random.Random(seed);out=[]
 def add(fn,**a):out.append({'fn':fn,'args':a})
 for _ in range(700):add('next_occurrence',rule=gen_rule(r),dt=r.choice(NOWS))
 for _ in range(400):
  y,m=r.choice([(2026,11),(2026,2),(2024,2),(2026,12),(2027,1)])
  import calendar
  last=calendar.monthrange(y,m)[1]
  add('expand_rule_occurrences',rule=gen_rule(r),start=f'{y:04d}-{m:02d}-01T00:00:00',end=f'{y:04d}-{m:02d}-{last:02d}T23:59:59')
 for _ in range(300):
  job={'id':r.choice(['j1',5,None]),'enabled':r.choice([True,False,1]),'schedules':[gen_rule(r) for _ in range(r.randint(0,3))]}
  add('job_schedule_preview',job=job,dt=r.choice(NOWS))
 pauses=['','{}','{"since":"2026-11-01T08:00"}','{"since":"2026-11-01T08:00","until":"2026-11-02T08:00"}','{"since":"x","until":"2026-12-01"}',
         '{"since":"x","until":"bad"}','{"since":"x","until":"2026-11-02T09:00:00"}','{"since":0}','[1]','{','{"since":"s","until":"2026-11-03 10:00"}',
         '{"since":["a"],"until":null}','{"since":"s","until":20261201}']
 for p in pauses:
  for now in NOWS[:3]:add('schedule_pause',state={'__pause__':p} if p else {},dt=now)
 add('schedule_pause',state={'other':'1'},dt=NOWS[0])
 runs=[None,{'finished_at':'2026-11-01T06:00:00','status':'ok','trigger':'schedule:r1','detail':'5行','rows':5,'cols':2,'output_file':'a.csv','metrics':{'rows':9}},
       {'finished_at':None,'status':'','trigger':None,'detail':None,'rows':None,'cols':None,'output_file':None,'metrics':{}},
       {'finished_at':'x','status':'failed','trigger':'manual','detail':'d','rows':0,'cols':None,'output_file':'','metrics':[['k','v']]},
       {'finished_at':'x','status':'failed','trigger':5,'detail':'d','rows':1,'cols':1,'output_file':'o','metrics':[1]}]
 for run in runs:add('last_run_info',run=run)
 for d in ['120行 / 12.5秒','a/ １２秒','/1.2.3秒','/x / 3秒','/ .5秒','/ 5.秒','/ .秒','/　７秒','秒/3','/3 秒','',None,5,'/1/2秒']:add('seconds_in',detail=d)
 return out


def run_fn(qs):
 exe=core_exe()
 if not exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
 with tempfile.TemporaryDirectory() as t:
  e=dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(Path(t)/'l'),NAVI_DATA_ROOT=str(Path(t)/'d'),
         NAVI_CONFIG_DIR=str(Path(t)/'d'/'C'),NAVI_SECRET_FILE=str(Path(t)/'s.json'))
  r=subprocess.run([ref_python(),'-c',PY_FN,str(ROOT)],input=json.dumps(qs),env=e,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=600)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  py=json.loads(r.stdout.strip().split('\n')[-1])
  # seconds_in の detail は字でなければ str() にしてから渡す（Python の str(detail or '') と同じ）
  qs2=[dict(q,args=dict(q['args'],detail=(str(q['args']['detail']) if q['args']['detail'] else ''))) if q['fn']=='seconds_in' else q for q in qs]
  r=subprocess.run([str(exe),'call'],input='\n'.join(json.dumps(q) for q in qs2)+'\n',env=e,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=600)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  rs=[json.loads(x) for x in r.stdout.split('\n') if x.strip()]
 return py,rs


class ScheduleFunctionParityTest(unittest.TestCase):
 def test_functions(self):
  qs=cases();py,rs=run_fn(qs)
  self.assertEqual((len(py),len(rs)),(len(qs),len(qs)))
  bad=[];passed={};answered=0
  for q,p,x in zip(qs,py,rs):
   if not x.get('ok'):bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}: Rust が失敗 {x.get("error")}');continue
   got=x['result']
   if got=={'pass':True}:
    passed[q['fn']]=passed.get(q['fn'],0)+(1 if p['ok'] else 0);continue
   if not p['ok']:bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}: Python は落ちる（{p["error"]}）のに Rust が答えた {got!r}'[:600]);continue
   answered+=1
   if canon(p['result'])!=canon(got):bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}:\n  PY={canon(p["result"])[:400]}\n  RS={canon(got)[:400]}')
  self.assertEqual(bad,[],f'{len(bad)} 件の食い違い:\n'+'\n'.join(bad[:40]))
  self.assertGreater(answered,len(qs)//2,'半分以上は Rust が答えて比べられている')
  self.assertLessEqual(sum(passed.values()),len(qs)//50,f'Python が答えるのに Rust が回した数: {passed}')
  print(f'\n  予定の関数の突き合わせ: {len(qs)} 件（比べた {answered}・Python が答えるのに Rust が回した {passed or 0}）')


# ==== ルート ================================================================

ASK=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app,navi_web
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
navi_web.datetime=Fixed;app.datetime=Fixed
t=app.app.test_client();out=[]
for path in json.loads(sys.stdin.read()):
 r=t.get(path);out.append({'status':r.status_code,'body':r.get_data(as_text=True)})
print(json.dumps(out))
"""

NOW='2026-11-02T09:05:07.123456'
JOBS=[{'id':'j1','name':'毎朝','rne':'a.RNE','output_format':'csv','output_file':'a.csv','schedules':[
        {'id':'r1','name':'朝','type':'daily','time':'06:00'},{'id':'r2','name':'週','type':'weekdays','time':'10:30','weekdays':[0,2,4]},
        {'id':'r3','name':'止め','type':'daily','time':'07:00','enabled':False}]},
      {'id':'j2','name':'月末','rne':'b.RNE','output_format':'csv','output_file':'b.csv','schedules':[
        {'id':'r4','name':'月末','type':'monthly','time':'23:00','month_days':[-1,15]},{'id':'r5','name':'特定','type':'specific_dates','time':'12:00','dates':['2026-11-20','2026-12-24','2025-01-01']}]},
      {'id':'j3','name':'間隔','rne':'c.RNE','output_format':'csv','output_file':'c.csv','schedules':[
        {'id':'r6','name':'15分','type':'interval','interval_minutes':15},{'id':'r7','name':'2時間','type':'interval','interval_minutes':120}]},
      {'id':'j4','name':'無効の対象','enabled':False,'rne':'d.RNE','output_format':'csv','output_file':'d.csv','schedules':[{'id':'r8','type':'daily'}]},
      {'id':'j5','name':'手動だけ','rne':'e.RNE','output_format':'csv','output_file':'e.csv','schedules':[]}]


def history_sql():
 out=[]
 rows=[('j1','毎朝','2026-11-01T06:00:12','ok','schedule:r1','120行 / 12.5秒',120,5,'a.csv'),
       ('j1','毎朝','2026-11-02T06:00:10','ok','schedule:r1','118行 / 13.0秒',118,5,'a.csv'),
       ('j1','毎朝','2026-11-02T08:00:00','failed','manual','失敗',None,None,''),
       ('j2','月末','2026-10-31T23:00:05','ok','schedule','40行 / 3秒',40,2,'b.csv'),
       ('j1','毎朝','2026-11-30T23:59:59','ok','manual:x','0行 / 1.0秒',0,5,'a.csv'),
       ('j1','毎朝','short','ok','manual','',None,None,''),
       ('j3','間隔','2026-11-15T12:00:00',None,None,None,7.5,'x',None)]
 for x in rows:out.append(['INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)',list(x)])
 for i in range(40):out.append(['INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)',
                                 ['j2','月末',f'2026-09-{(i%28)+1:02d}T10:00:00','ok' if i%5 else 'failed','schedule',f'{100+i}行 / {2.0+i/10}秒',100+i,2,'b.csv']])
 out.append(["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j1','毎朝','2026-11-02T06:00:10','ok','schedule:r1','118行',118,5,'a.csv','t','{\"rows\":118,\"seconds\":13.0}')",[]])
 out.append(["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j2','月末','2026-10-31T23:00:05','failed','manual','e',NULL,NULL,'','t','')",[]])
 return out


PATHS=['/api/schedule-preview','/api/calendar','/api/calendar?year=2026&month=11','/api/calendar?year=2026&month=12','/api/calendar?year=2026&month=9',
       '/api/calendar?year=2024&month=2','/api/calendar?year=2026&month=13','/api/calendar?year=2026','/api/calendar?year=x&month=1','/api/calendar?year=%202026%20&month=0',
       '/api/job-trend/j1','/api/job-trend/j2?limit=10','/api/job-trend/j2?limit=999','/api/job-trend/j2?limit=1','/api/job-trend/j3','/api/job-trend/none','/api/job-trend/j2?limit=',
       '/api/job-trend/%E6%AF%8E']


class ScheduleRouteParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.exe=core_exe()
  cls.tmp=tempfile.TemporaryDirectory();cls.t=Path(cls.tmp.name).resolve()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def env(self,name):
  d=self.t/name
  return dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),
              NAVI_CONFIG_DIR=str(d/'data'/'Config'),NAVI_SECRET_FILE=str(d/'s.json'))

 def py(self,code,name,stdin,*args):
  r=subprocess.run([ref_python(),'-c',code,str(ROOT),*args],input=stdin,env=self.env(name),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().split('\n')[-1])

 def rust(self,name,paths):
  lines=''.join(json.dumps({'method':'GET','path':p.split('?')[0],'query':p.split('?',1)[1] if '?' in p else '','body':''})+'\n' for p in paths)
  r=subprocess.run([str(self.exe),'answer','--base',str(ROOT)],input=lines,env=dict(self.env(name),DATARELAY_FIXED_NOW=NOW),cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return [json.loads(x) for x in r.stdout.split('\n') if x.strip()]

 def compare(self,name,cfg,sql,paths=PATHS):
  self.py(MAKE,name,json.dumps({'cfg':cfg,'sql':sql},ensure_ascii=False))
  rs=self.rust(name,paths);py=self.py(ASK,name,json.dumps(paths),NOW)
  bad=[]
  for path,p,x in zip(paths,py,rs):
   if x['status']==0:bad.append(f'{path}: Rust が答えなかった');continue
   if x['status']!=p['status']:bad.append(f'{path}: 番号 Python={p["status"]} Rust={x["status"]}');continue
   a,b=json.loads(p['body']),json.loads(x['body'])
   if canon(a)!=canon(b):bad.append(f'{path}: '+'; '.join(f'{k}: PY={canon(a.get(k))[:500]} RS={canon(b.get(k))[:500]}' for k in sorted(set(a)|set(b)) if canon(a.get(k))!=canon(b.get(k))))
  self.assertEqual(bad,[],'\n'.join(bad))
  return [json.loads(p['body']) for p in py]

 def test_routes(self):
  pause=["INSERT OR REPLACE INTO scheduler_state VALUES('__pause__','{\"since\":\"2026-11-01T08:00\",\"until\":\"2026-11-05T08:00\"}','t')",[]]
  out=self.compare('s',{'jobs':JOBS},history_sql()+[pause])
  prev=out[0]
  self.assertTrue(prev['pause']['paused']);self.assertEqual(prev['pause']['rules'],6)
  self.assertTrue(any(i.get('next_run') for i in prev['items']))
  cal=out[2]
  self.assertTrue(cal['scheduled'] and cal['interval'] and cal['executed'],'見本が予定・一定間隔・実施の記録を持っている')
  self.assertTrue(out[11]['rows_spread'] and out[11]['seconds_spread'])

 def test_bad_rule_goes_to_python(self):
  """日時にできない時刻（25:00）の予定は Python が落ちる（500）。Rust は答えない。"""
  self.py(MAKE,'bad',json.dumps({'cfg':{'jobs':[{'id':'x','name':'x','schedules':[{'type':'daily','time':'25:00'}]}]}}))
  for x in self.rust('bad',['/api/schedule-preview','/api/calendar']):self.assertEqual(x['status'],0)
  self.assertEqual([p['status'] for p in self.py(ASK,'bad',json.dumps(['/api/schedule-preview','/api/calendar']),NOW)],[500,500])


if __name__=='__main__':unittest.main()
