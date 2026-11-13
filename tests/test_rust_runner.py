"""実行の記録と、ワーカーの見守りが、Python（app.record_job_run・navi_lanerun.run_api_process_batch）と
Rust（desktop/core の runs.rs・worker.rs）で同じになるか（2.36.0・段 5d の1回目）。

- 記録: 同じ記録を Python と Rust で同じ見本の写しへ書き、job_runs・run_history（直近 2000 件だけ残す）が同じになる
- RNE のワーカーの答えから作る記録と画面の1行: Python の run_api_process_batch を、決まった答えを返す偽のワーカーで本当に流し、
  その記録・画面の job_results と、Rust が同じ答えから作る物が同じになる
- ワーカーの見守り: 偽のワーカー（成功・失敗・落ちる・応答しない）と、本物のワーカーで手元の対象を1件流す（段 5c の local）
実行: python -m unittest tests.test_rust_runner -v
"""
import json,os,shutil,sqlite3,subprocess,sys,tempfile,unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_config import MAKE  # noqa: E402
from test_rust_parity import ROOT  # noqa: E402

NOW='2026-11-02T09:05:07.123456'

PY_RECORD=r'''
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
app.datetime=Fixed
for r in json.loads(sys.stdin.read()):
 app.record_job_run(r['job_id'],r['job_name'],r['status'],r['trigger'],detail=r['detail'],rows=r['rows'],cols=r['cols'],
                    output_file=r['output_file'],metrics=r['metrics'])
print('{}')
'''

# Python の本物の並列の親（run_api_process_batch）を、決まった答えを返す偽のワーカーで流す
PY_BATCH=r'''
import json,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app,navi_lanerun
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
app.datetime=Fixed;navi_lanerun.datetime=Fixed
navi_lanerun.BASE=Path(sys.argv[3])
spec=json.loads(sys.stdin.read());cfg=app.load()
work=Path(sys.argv[4]);work.mkdir(parents=True,exist_ok=True)
navi_lanerun.run_api_process_batch(spec['jobs'],cfg,'u','p','s',work,work/'backup',2,'manual')
print(json.dumps({'job_results':app.status.get('job_results') or []},ensure_ascii=False))
'''

# 偽のワーカー。payload の job._fake で振る舞いを決める（決まった答え・失敗・落ちる・応答しない）
FAKE_WORKER=r'''
import json,os,sys,time
p=json.loads(open(sys.argv[1],encoding='utf-8').read());j=p['job'];f=j.get('_fake') or {}
def put(env,data):
 path=os.environ[env];tmp=path+'.tmp';open(tmp,'w',encoding='utf-8').write(json.dumps(data,ensure_ascii=False));os.replace(tmp,path)
for st in f.get('statuses') or []:put('NAVI_WORKER_STATUS',dict(st,line=os.environ['NAVI_WORKER_LINE']));time.sleep(0.15)
if f.get('sleep'):time.sleep(f['sleep'])
if 'result' in f:put('NAVI_WORKER_RESULT',f['result'])
sys.exit(f.get('code',0))
'''


def rows_of(db):
 with closing(sqlite3.connect(str(db))) as c:
  c.row_factory=sqlite3.Row
  runs=[dict(r) for r in c.execute('SELECT * FROM job_runs ORDER BY job_id')]
  hist=[{k:r[k] for k in r.keys() if k!='id'} for r in c.execute('SELECT * FROM run_history ORDER BY id')]
  n=c.execute('SELECT COUNT(*),MIN(id) FROM run_history').fetchone()
 return runs,hist,tuple(n)


class RunnerParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','twin'))

 def call(self,name,qs):
  """Rust の関数ごとの口（datarelay-core call）。"""
  lines=''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in qs)
  r=subprocess.run([str(self.exe),'call'],input=lines,env=dict(self.env(name),DATARELAY_FIXED_NOW=NOW),cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  out=[json.loads(x) for x in r.stdout.split('\n') if x.strip()]
  for x in out:
   if not x.get('ok'):raise AssertionError(x)
  return [x['result'] for x in out]

 def base(self,name,history=0):
  self.py(MAKE,name,json.dumps({'cfg':{'jobs':[]},'sql':[['INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)',
                                                          ['old','古い',f'2026-01-01T00:00:{i%60:02d}','ok','manual','',1,1,'']] for i in range(history)]},ensure_ascii=False))

 def test_record_job_run(self):
  self.base('rbase',history=2001);self.twin('rbase','rpy','rrs')
  recs=[{'job_id':'j1','job_name':'受注','status':'ok','trigger':'schedule:a','detail':'2件/3列 / 1.5秒','rows':2,'cols':3,'output_file':'受注.csv',
         'metrics':{'elapsed':1.5,'published':True,'pending':'','hold_advice':['閉じて'],'nested':{'a':[1,None,'x"y']},'f':0.1}},
        {'job_id':'j2','job_name':'失敗','status':'failed','trigger':'manual','detail':'読めません','rows':None,'cols':None,'output_file':'','metrics':{}},
        {'job_id':'j1','job_name':'受注','status':'cancelled','trigger':'manual','detail':'ユーザーにより中断されました','rows':None,'cols':None,'output_file':'','metrics':None},
        {'job_id':'','job_name':'id なし','status':'ok','trigger':'manual','detail':'','rows':None,'cols':None,'output_file':'','metrics':{}},
        {'job_id':5,'job_name':'数の id','status':'ok','trigger':'manual','detail':'','rows':1.5,'cols':2,'output_file':'','metrics':{'n':12345678901}}]
  self.py(PY_RECORD,'rpy',json.dumps(recs,ensure_ascii=False),NOW)
  out=self.call('rrs',[{'fn':'record_job_run','args':{'base':str(ROOT),'record':r}} for r in recs])
  self.assertEqual([x['written'] for x in out],[True]*5)
  a,b=rows_of(self.paths('rpy')[0]),rows_of(self.paths('rrs')[0])
  self.assertEqual(a,b)
  self.assertEqual(a[2][0],2000,'実施履歴は直近 2000 件だけ残す')
  self.assertEqual(len(a[0]),3)

 def fake_root(self):
  root=self.t/'fake';(root/'lib').mkdir(parents=True,exist_ok=True);(root/'lib'/'api_worker.py').write_text(FAKE_WORKER,encoding='utf-8')
  return root

 def test_rne_result_like_python_batch(self):
  root=self.fake_root()
  answers=[('r1',{'ok':True,'job':'受注','result':'受注: 120件/8列','rows':120,'columns':8,'elapsed':12.345,'target':'C:\\out\\受注.csv',
                  'execute_seconds':3.2,'save_seconds':1.1,'format':'csv','split_parts':None,'published':True,'pending':''},0),
           ('r2',{'ok':True,'job':'保留','result':'保留: 5件','rows':5,'columns':2,'elapsed':0.25,'target':'/srv/保留.sqlite3','published':False,
                  'pending':'保留.sqlite3.pending_1','hold_reason':'使用中','hold_waited':20.5,'hold_attempts':4,'hold_advice':'閉じて',
                  'variant_results':[{'value':'東京','ok':True}],'variant_method':'combined'},0),
           ('r3',{'ok':False,'job':'失敗','error':'RNEが見つかりません','elapsed':0.05},2),
           ('r4',{'ok':True,'job':'形なし','result':'','error':'','rows':None,'elapsed':0.15},0)]
  jobs=[{'id':i,'name':a['job'],'rne':i+'.RNE','_fake':{'result':a,'code':c},'_trigger':'schedule:x' if i=='r2' else ''} for i,a,c in answers]
  self.base('bbase');self.twin('bbase','bpy','brs')
  r=subprocess.run([sys.executable,'-c',PY_BATCH,str(ROOT),NOW,str(root),str(self.t/'bpy'/'work')],input=json.dumps({'jobs':jobs},ensure_ascii=False),
                   env=self.env('bpy'),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  py_results={x['job_id']:x for x in json.loads(r.stdout.strip().split('\n')[-1])['job_results']}
  out=self.call('brs',[{'fn':'record_rne_result','args':{'base':str(ROOT),'job':{k:v for k,v in j.items() if k!='_fake'},'result':a,'trigger':'manual'}}
                       for j,(_i,a,_c) in zip(jobs,answers)])
  for (i,_a,_c),x in zip(answers,out):self.assertEqual(x['one'],py_results[i],i)
  a,b=rows_of(self.paths('bpy')[0]),rows_of(self.paths('brs')[0])
  self.assertEqual(sorted(a[1],key=lambda x:x['job_id']),sorted(b[1],key=lambda x:x['job_id']))
  self.assertEqual(a[0],b[0])
  self.assertEqual(len(a[0]),4);self.assertEqual({x['job_id']:x['status'] for x in a[0]},{'r1':'ok','r2':'ok','r3':'failed','r4':'ok'})

 def test_worker_supervision(self):
  root=self.fake_root();w=self.t/'workers'
  def job(n,**fake):return {'job':{'id':n,'name':n,'_fake':fake}}
  st=[{'job':'a','state':'読み取り','percent':35},{'job':'a','state':'公開','percent':90}]
  qs=[('ok',job('a',statuses=st,result={'ok':True,'job':'a','result':'できた'}),None),
      ('fail',job('b',result={'ok':False,'job':'b','error':'だめ'},code=2),None),
      ('crash',job('c',code=3),None),
      ('hang',job('d',sleep=30,result={'ok':True}),1.5)]
  self.base('wrs')
  out=self.call('wrs',[{'fn':'run_worker','args':{'python':sys.executable,'program_root':str(root),'dir':str(w/n),'payload':p,'line':'ライン 3',
                                                   'limit_seconds':lim}} for n,p,lim in qs])
  ok,fail,crash,hang=out
  self.assertEqual((ok['code'],ok['result'],ok['timed_out']),(0,{'ok':True,'job':'a','result':'できた'},False))
  self.assertEqual([x['state'] for x in ok['statuses']],['読み取り','公開']);self.assertEqual(ok['statuses'][0]['line'],'ライン 3')
  self.assertEqual((fail['code'],fail['result']['error']),(2,'だめ'))
  self.assertEqual((crash['code'],crash['result']['error'],crash['result']['job'],crash['result']['ok']),(3,'Worker終了コード 3','c',False))
  self.assertTrue(hang['timed_out']);self.assertEqual(hang['result']['error'],'応答が返らないため0.025分で打ち切りました')
  self.assertLess(hang['result']['elapsed'],10,'応答しないワーカーは打ち切ってすぐ止める')
  self.assertTrue((w/'ok'/'payload.json').is_file())

 def test_real_local_worker_then_record(self):
  """本物のワーカー（lib/api_worker.py の local）で手元の対象を1件流し、その答えから Rust が記録を書く。"""
  self.base('lbase');self.twin('lbase','lpy','lrs')
  d=self.t/'lrs';src=d/'受注.csv';src.write_bytes('番号,品名\r\nA1,ボルト\r\nA2,ナット\r\n'.encode('cp932'))
  make=r'''
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
spec=json.loads(sys.stdin.read());c=app.app.test_client()
lid=c.post('/api/text-layouts',json={'name':'受注','mode':'delimited','delimiter':'comma','header_row':True,'encoding':'cp932',
           'columns':[{'name':'番号','field':1},{'name':'品名','field':2}]}).get_json()['layout']['id']
cfg=app.load();cfg['jobs']=[dict(spec['job'],layout_id=lid)];app.save(cfg)
print(json.dumps({'cfg':app.load()},ensure_ascii=False))
'''
  job={'id':'L1','name':'受注','enabled':True,'source':'text','text_path':str(src),'rne':'','rne_path':'','output_folder':str(d/'out'),
       'output_format':'csv','output_file':'受注.csv','naming_mode':'fixed','schedules':[]}
  cfg=self.py(make,'lrs',json.dumps({'job':job},ensure_ascii=False))['cfg']
  payload={'local':{'trigger':'manual','slot':1},'job':cfg['jobs'][0],'cfg':cfg,'job_index':1,'total_jobs':1,'work':str(d/'work'),'backup':str(d/'backup')}
  run,=self.call('lrs',[{'fn':'run_worker','args':{'python':sys.executable,'program_root':str(ROOT),'dir':str(d/'wk'),'payload':payload,'line':'ライン 1'}}])
  self.assertEqual(run['code'],0,run);self.assertTrue(run['result']['ok'],run)
  self.assertEqual((d/'out'/'受注.csv').read_text(encoding='utf-8-sig').splitlines(),['番号,品名','A1,ボルト','A2,ナット'])
  self.assertTrue(run['statuses'] and run['statuses'][-1]['job_id']=='L1')
  self.assertEqual(rows_of(self.paths('lrs')[0])[0],[],'ワーカーは記録を書かない')
  self.call('lrs',[{'fn':'record_local_result','args':{'base':str(ROOT),'job':cfg['jobs'][0],'result':run['result'],'trigger':'manual'}}])
  runs=rows_of(self.paths('lrs')[0])[0]
  self.assertEqual((runs[0]['job_id'],runs[0]['status'],runs[0]['rows'],runs[0]['cols'],runs[0]['output_file']),('L1','ok',2,2,'受注.csv'))
  self.assertEqual(json.loads(runs[0]['metrics'])['published'],True)
  self.assertTrue(runs[0]['detail'].startswith('2件/2列 / '))


if __name__=='__main__':unittest.main()
