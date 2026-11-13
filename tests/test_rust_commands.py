"""実行の指令の待機キュー・知らせ・取り直しが、Python（app.py の enqueue_command・queue_snapshot・add_alert・schedule_retry・
due_retries・after_command と、navi_web の execution-queue・alerts・retries の受け口）と Rust（desktop/core の commands.rs）で
同じになるか（2.40.0・段 5e の1回目）。

同じ操作の並び（積む・流し始める・合流・締める・消す・動かす・空にする・知らせる・読む・取り直す・時刻が来る）を両方に当て、
答えを1つずつ比べる。id は作るたびに違うので、id の字だけ同じ印に置き換えて比べる。時刻は決めた時刻にする。
実行: python -m unittest tests.test_rust_commands -v
"""
import json,os,re,subprocess,sys,unittest

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
c=app.app.test_client();cfg=app.load();out=[]
for op in json.loads(sys.stdin.read()):
 CLOCK[0]=_dt.fromisoformat(op['now']).timestamp();k=op['op'];r=None
 qid=lambda:(app.command_queue[op['index']]['id'] if op.get('index') is not None and op['index']<len(app.command_queue) else 'nai')
 if k=='enqueue':
  try:item,pos=app.enqueue_command(op.get('job_ids'),op['trigger'],op.get('lines'),op.get('attempt',0));r={'position':pos}
  except ValueError as e:r={'error':str(e)}
 elif k=='start':app.active_command=app.command_queue.pop(0) if app.command_queue else None
 elif k=='join':
  app.active_command.setdefault('joined_ids',[]).extend(op['ids']);app.active_command.setdefault('joined_names',[]).extend(op['names'])
 elif k=='finish':
  item=dict(app.active_command or {});app.status.clear();app.status.update(op['status'])
  app.after_command(item,op.get('error',''),cancelled=op.get('cancelled',False));app.active_command=None
 elif k=='snapshot':r=app.queue_snapshot()
 elif k=='delete':r=c.delete('/api/execution-queue/'+qid()).status_code==200
 elif k=='move':r=c.post('/api/execution-queue/'+qid()+'/move',json={'direction':op.get('direction')}).status_code==200
 elif k=='clear':app.status['running']=False;r=c.post('/api/run/cancel').get_json()['queue_cleared']
 elif k=='alert':app.add_alert(op['kind'],op['title'],op['detail'],op.get('jobs'))
 elif k=='alerts':r=c.get('/api/alerts').get_json()
 elif k=='ack':
  ids=[app.alerts[i]['id'] for i in op['indexes'] if i<len(app.alerts)]
  r=c.post('/api/alerts/ack',json={'ids':ids}).get_json();r={'removed':r['removed'],'count':r['count']}
 elif k=='retry':
  due=app.schedule_retry(op['job_ids'],op['names'],op['lines'],op['attempt'],cfg)
  r=None if due is None else _dt.fromtimestamp(due).isoformat(timespec='seconds')
 elif k=='due':r=[{'job_ids':x['job_ids'],'names':x['names'],'lines':x['lines'],'attempt':x['attempt']} for x in app.due_retries()]
 elif k=='cancel_retries':r=c.post('/api/retries/cancel').get_json()['cancelled']
 elif k=='clamp':r=app.clamp_parallel_lines(op.get('value'),cfg)
 out.append(r)
print(json.dumps({'cfg':cfg,'out':out},ensure_ascii=False,default=str))
'''

HEX=re.compile(r'^[0-9a-f]{32}$')


def no_ids(v):
 if isinstance(v,dict):return {k:('ID' if isinstance(x,str) and HEX.match(x) else no_ids(x)) for k,x in v.items()}
 if isinstance(v,list):return [no_ids(x) for x in v]
 return v


def jobs():
 return [{'id':'j1','name':'受注','enabled':True},{'id':'j2','name':'在庫','enabled':1},{'id':'j3','name':'止めた','enabled':False},
         {'id':'j4','name':'出荷','enabled':True}]


class CommandsParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py'))

 def both(self,name,settings,ops):
  self.py(MAKE,name,json.dumps({'cfg':{'jobs':jobs(),'settings':settings}},ensure_ascii=False))
  py=self.py(PY,name,json.dumps(ops,ensure_ascii=False))
  r=subprocess.run([str(self.exe),'call'],input=json.dumps({'fn':'commands','args':{'cfg':py['cfg'],'ops':ops}},ensure_ascii=False)+'\n',
                   env=self.env(name),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  rs=json.loads(r.stdout.strip().split('\n')[-1])
  if not rs.get('ok'):raise AssertionError(rs)
  for i,(op,p,x) in enumerate(zip(ops,py['out'],rs['result'])):
   self.assertEqual(no_ids(x),no_ids(p),f'{i}: {op}')
  return py['out']

 def test_queue(self):
  T='2026-11-13T09:00:00'
  ops=[{'op':'clamp','now':T,'value':v} for v in (None,0,3,'2','9',2.7,'2.5',True,[1],-5)]
  ops+=[{'op':'enqueue','now':T,'job_ids':[],'trigger':'manual','lines':3},
        {'op':'enqueue','now':T,'job_ids':['j2','j3'],'trigger':'schedule:朝','lines':'50','attempt':1},
        {'op':'enqueue','now':T,'job_ids':['j3'],'trigger':'manual','lines':1},
        {'op':'enqueue','now':T,'job_ids':['無い'],'trigger':'manual','lines':1},
        {'op':'enqueue','now':'2026-11-13T09:01:02','job_ids':['j4'],'trigger':'manual-single','lines':None},
        {'op':'snapshot','now':T},
        {'op':'move','now':T,'index':2,'direction':'up'},{'op':'move','now':T,'index':0,'direction':'up'},
        {'op':'move','now':T,'index':2,'direction':'down'},{'op':'move','now':T,'index':9,'direction':'up'},
        {'op':'snapshot','now':T},
        {'op':'start','now':T},
        {'op':'join','now':T,'ids':['j4'],'names':['出荷']},
        {'op':'enqueue','now':T,'job_ids':['j1'],'trigger':'manual','lines':2},
        {'op':'snapshot','now':T},
        {'op':'delete','now':T,'index':0},{'op':'delete','now':T,'index':5},
        {'op':'snapshot','now':T},
        {'op':'clear','now':T},{'op':'snapshot','now':T}]
  out=self.both('cq',{'api_parallel_max_lines':4},ops)
  self.assertEqual(out[:10],[1,1,3,2,4,2,1,1,1,1])
  snap=out[15];self.assertEqual([x['job_ids'] for x in snap['items']],[['j1','j2','j4'],['j2'],['j4']])

 def test_alerts_and_retries(self):
  T='2026-11-13T09:00:00';T2='2026-11-13T09:10:00';T3='2026-11-13T09:20:00'
  ops=[{'op':'alert','now':T,'kind':'info','title':f'知らせ{i}','detail':'あ'*450 if i==3 else f'中身{i}','jobs':['受注'] if i%2 else None}
       for i in range(53)]
  ops+=[{'op':'alerts','now':T},{'op':'ack','now':T,'indexes':[0,2,49]},{'op':'ack','now':T,'indexes':[]},{'op':'alerts','now':T},
        {'op':'retry','now':T,'job_ids':['j1'],'names':['受注'],'lines':2,'attempt':1},
        {'op':'retry','now':T,'job_ids':['j2','j4'],'names':['在庫','出荷'],'lines':1,'attempt':2},
        {'op':'retry','now':T,'job_ids':['j2'],'names':['在庫'],'lines':1,'attempt':3},
        {'op':'alerts','now':T},
        {'op':'due','now':T2},{'op':'due','now':T3},{'op':'alerts','now':T3},
        {'op':'retry','now':T3,'job_ids':['j1'],'names':['受注'],'lines':1,'attempt':1},{'op':'cancel_retries','now':T3},{'op':'alerts','now':T3}]
  out=self.both('ca',{'retry_max':2,'retry_delay_minutes':10},ops)
  view=out[53];self.assertEqual((view['count'],view['worst'],view['alerts'][0]['title']),(50,'info','知らせ3'))
  self.assertEqual(len(view['alerts'][0]['detail']),400)
  self.assertEqual(out[57],'2026-11-13T09:10:00');self.assertIsNone(out[59],'回数を使い切ったら予約しない')
  self.assertEqual(len(out[61]),2);self.assertEqual(out[62],[])
  # 取り直しを止めた設定・数の無い設定
  self.both('cb',{'retry_enabled':False},[{'op':'retry','now':T,'job_ids':['j1'],'names':['受注'],'lines':1,'attempt':1},{'op':'alerts','now':T}])
  self.both('cc',{'retry_max':0,'retry_delay_minutes':0},[{'op':'retry','now':T,'job_ids':['j1'],'names':['受注'],'lines':1,'attempt':1},
                                                          {'op':'retry','now':T,'job_ids':['j1'],'names':['受注'],'lines':1,'attempt':0},
                                                          {'op':'alerts','now':T}])
  # 上限（待つのは 180 分まで・取り直しは 5 回まで）
  big=self.both('cd',{'retry_max':9,'retry_delay_minutes':999},[{'op':'retry','now':T,'job_ids':['j1'],'names':['受注'],'lines':1,'attempt':5},
                                                                 {'op':'retry','now':T,'job_ids':['j1'],'names':['受注'],'lines':1,'attempt':6},
                                                                 {'op':'alerts','now':T}])
  self.assertEqual(big[:2],['2026-11-13T12:00:00',None])

 def test_after_command(self):
  """実行の締め: 共有先へ反映できなかった対象・失敗の知らせ・自動実行だけの取り直し（合流した対象は外す）・中止は知らせない。"""
  T='2026-11-13T09:00:00'
  ok={'job_results':[{'job':'受注','job_id':'j1','status':'ok','published':True},{'job':'在庫','job_id':'j2','status':'ok','published':False,'pending':'x'},
                     {'job':'出荷','job_id':'j4','status':'failed','published':False}],'queue_failed_ids':[],'job_errors':[]}
  fail={'job_results':[],'queue_failed_ids':['j1','','j2'],'job_errors':[{'job':'受注','error':'え'*130},{'job':'','error':'無名'},{'error':'名なし'},'壊れた'],
        'error_detail':'詳しく','last_result':'異常終了'}
  bare={'queue_failed_ids':[],'job_errors':[],'error_detail':'','last_result':'異常終了: 接続できません'}
  def run(trigger,status,**kw):
   return [{'op':'enqueue','now':T,'job_ids':kw.pop('ids',['j1','j2']),'trigger':trigger,'lines':2,'attempt':kw.pop('attempt',0)},{'op':'start','now':T},
           *([{'op':'join','now':T,'ids':kw['joined'],'names':['出荷']}] if 'joined' in kw else []),
           {'op':'finish','now':T,'status':status,'error':kw.get('error',''),'cancelled':kw.get('cancelled',False)}]
  ops=[*run('manual',ok),*run('schedule:朝',ok,attempt=1),*run('schedule:朝',fail),*run('manual',fail),
       *run('schedule:朝',{**fail,'queue_failed_ids':['j1','j4']},joined=['j4']),
       *run('schedule:朝',bare,error='落ちた'),*run('schedule:朝',bare,ids=['j4'],error='落ちた'),
       *run('schedule:朝',fail,cancelled=True),*run('schedule:朝',{'queue_failed_ids':[],'job_errors':[]},attempt=2),
       {'op':'alerts','now':T}]
  out=self.both('cf',{'retry_max':3,'retry_delay_minutes':7},ops)
  view=out[-1];titles=[x['title'] for x in view['alerts']]
  self.assertIn('1件が共有先へ反映できていません',titles);self.assertIn('取り直しで成功しました',titles)
  self.assertEqual(len(view['retries']),4,'自動実行の失敗だけ（中止・手動・合流した対象だけの失敗は除く）')


if __name__=='__main__':unittest.main()
