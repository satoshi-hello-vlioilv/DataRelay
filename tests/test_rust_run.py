"""実行の受け付けと、指令1つを最後まで流す役（desktop/core の runner.rs。2.41.0・段 5e-2a）。

Python の process・command_dispatcher・join_running・absorb_waiting・finish_batch と同じ決まりで、本物の設定（見本の写し）と
偽のワーカー（対象のコメントに書いた秒数だけ待ち、決めた答えを書く）で、実行を入れてから締めるまでを流す。
確かめること: 正常終了の言い方と記録・あとから入れた手動の実行の合流（黒板ができる前に入れた物も）・自動実行の失敗の知らせと
取り直しの予約・接続情報が無いとき・中止（失敗として知らせない）・Power Query の対象があるときは引き受けない。
実行: python -m unittest tests.test_rust_run -v
"""
import json,os,sqlite3,subprocess,sys,unittest
from contextlib import closing

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_config import MAKE  # noqa: E402
from test_rust_parity import ROOT  # noqa: E402

# 偽のワーカー。対象のコメント（JSON）の sleep 秒だけ待ち、ok なら成功の答えを書く（RNE と手元で答えの形が違う）
FAKE=r'''
import json,os,sys,time
p=json.loads(open(sys.argv[1],encoding='utf-8').read());j=p['job']
f=json.loads(j.get('comment') or '{}')
time.sleep(float(f.get('sleep',0.2)))
def put(d):
 path=os.environ['NAVI_WORKER_RESULT'];open(path+'.tmp','w',encoding='utf-8').write(json.dumps(d,ensure_ascii=False));os.replace(path+'.tmp',path)
ok=f.get('ok',True)
if 'local' in p:
 put({'ok':ok,'job':j['name'],'result':j['name']+' OK' if ok else '','error':'' if ok else 'わざと失敗',
      'record':{'status':'ok' if ok else 'failed','detail':'1件' if ok else 'わざと失敗','rows':1 if ok else None,'cols':1 if ok else None,'output_file':'','metrics':{}}})
else:
 put({'ok':ok,'job':j['name'],'result':j['name']+' OK' if ok else '','error':'' if ok else 'わざと失敗','rows':1,'columns':1,'elapsed':0.2,'target':''})
sys.exit(0 if ok else 2)
'''

CONF='[Default]\nSymNaviServer = srv:2001\nSymNaviUSERID = 試験\nSymNaviPASSWD = 秘密\n'


def job(i,kind='rne',**fake):
 j={'id':i,'name':'名'+i,'enabled':True,'source':kind,'comment':json.dumps(fake),'output_file':i+'.csv','output_format':'csv'}
 if kind=='rne':j['rne']=i+'.RNE'
 return j


class RunTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py'))

 def run_ops(self,name,jobs,ops,login=True,settings=None,timeout=30):
  d=self.t/name;d.mkdir(parents=True,exist_ok=True)
  root=d/'fake';(root/'lib').mkdir(parents=True,exist_ok=True);(root/'lib'/'api_worker.py').write_text(FAKE,encoding='utf-8')
  cfg={'jobs':jobs,'settings':dict({'api_parallel_lines':4,'api_worker_stagger_ms':0,'retry_max':1,'retry_delay_minutes':5},**(settings or {}))}
  if login:(d/'symnavim.conf').write_text(CONF,encoding='utf-8');cfg['symnavim_conf']=str(d/'symnavim.conf')
  self.py(MAKE,name,json.dumps({'cfg':cfg},ensure_ascii=False))
  args={'base':str(ROOT),'python':sys.executable,'program_root':str(root),'work':str(d/'work'),'ops':ops,'timeout':timeout}
  r=subprocess.run([str(self.exe),'call'],input=json.dumps({'fn':'run_commands','args':args},ensure_ascii=False)+'\n',
                   env=self.env(name),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=timeout+60)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  out=json.loads(r.stdout.strip().split('\n')[-1])
  if not out.get('ok'):raise AssertionError(out)
  with closing(sqlite3.connect(str(self.paths(name)[0]))) as c:
   out['result']['runs']={r[0]:(r[1],r[2]) for r in c.execute('SELECT job_id,status,trigger FROM job_runs')}
  return out['result']

 def test_complete(self):
  """材料を作る RNE を先に、結合はそのあと。1回で締まり、正常終了の言い方は Python と同じ。"""
  o=self.run_ops('rok',[job('A'),job('B'),job('T','text')],[{'at':0,'op':'enqueue','ids':[],'trigger':'manual','lines':4}])
  st=o['status']
  self.assertEqual((st['step'],st['running'],st['step_percent']),('complete',False,100))
  self.assertTrue(st['last_result'].startswith('正常終了 | 全件3ファイル / '),st['last_result'])
  self.assertEqual(o['runs'],{'A':('ok','manual'),'B':('ok','manual'),'T':('ok','manual')})
  self.assertEqual((o['dispatched'],o['alerts']['count']),(1,0))

 def test_one_by_one_joins(self):
  """1件ずつ入れた手動の実行は、黒板ができる前に入れた物も含めて、走っている実行へ合流する（2.40.1 と同じ）。"""
  o=self.run_ops('rjoin',[job('A',sleep=1.5),job('B'),job('C'),job('D')],
                 [{'at':0,'op':'enqueue','ids':['A'],'trigger':'manual-single','lines':1},
                  {'at':0.01,'op':'enqueue','ids':['B'],'trigger':'manual-single','lines':1},
                  {'at':0.02,'op':'enqueue','ids':['C'],'trigger':'manual-single','lines':1},
                  {'at':0.6,'op':'enqueue','ids':['D'],'trigger':'manual-single','lines':1}])
  self.assertEqual(o['dispatched'],1,'実行は1回（ほかは合流）')
  self.assertTrue(o['enq'][3]['joined'],'走っている間に入れた物はその場で合流する')
  self.assertEqual(set(o['runs']),{'A','B','C','D'})
  self.assertEqual(o['status']['step'],'complete')

 def test_scheduled_failure_retries(self):
  """自動実行の失敗は知らせ、取り直しを予約する。言い方は finish_batch と同じ。"""
  o=self.run_ops('rfail',[job('A',ok=False),job('B')],[{'at':0,'op':'enqueue','ids':[],'trigger':'schedule:朝','lines':2}])
  st=o['status']
  self.assertEqual(st['step'],'error')
  self.assertEqual(st['last_result'],'異常終了: 1件失敗しました\n・名A: わざと失敗')
  self.assertEqual(st['job_errors'],[{'job':'名A','error':'わざと失敗'}])
  self.assertEqual([x['title'] for x in o['alerts']['alerts']],['1件の実行が失敗しました','5分後に取り直します'])
  self.assertEqual(o['alerts']['retries'][0]['jobs'],['名A'])
  self.assertEqual(o['runs'],{'A':('failed','schedule:朝'),'B':('ok','schedule:朝')})

 def test_no_login(self):
  o=self.run_ops('rnologin',[job('A')],[{'at':0,'op':'enqueue','ids':[],'trigger':'manual','lines':1}],login=False)
  self.assertEqual(o['status']['step'],'error')
  self.assertIn('接続情報が登録されていません',o['status']['last_result'])
  self.assertEqual(o['alerts']['alerts'][0]['title'],'1件の実行が失敗しました')

 def test_cancel(self):
  """中止は待機キューも空にし、走っている対象を止める。失敗として知らせない。"""
  o=self.run_ops('rcancel',[job('A',sleep=20),job('B')],
                 [{'at':0,'op':'enqueue','ids':['A'],'trigger':'schedule:朝','lines':1},
                  {'at':0.05,'op':'enqueue','ids':['B'],'trigger':'schedule:朝','lines':1},
                  {'at':0.8,'op':'cancel'}],timeout=20)
  self.assertEqual(o['enq'][2],{'cancel':True,'cleared':1})
  self.assertEqual(o['status']['step'],'cancelled')
  self.assertEqual(o['status']['last_result'],'中断されました: 0/1件完了後に中断されました')
  self.assertEqual((o['alerts']['count'],o['alerts']['retries']),(0,[]))
  self.assertEqual(o['runs'],{'A':('cancelled','schedule:朝')})

 def test_power_query_is_not_taken(self):
  """Power Query の対象が設定にあると、材料の関係を決められない（M の式を読むのは段 6）。走らせずに失敗として返す。"""
  o=self.run_ops('rmq',[job('A'),{'id':'Q','name':'クエリ','enabled':False,'source':'mquery','query_id':'q1','output_file':'q.csv'}],
                 [{'at':0,'op':'enqueue','ids':['A'],'trigger':'manual','lines':1}])
  self.assertEqual(o['status']['step'],'error')
  self.assertIn('Power Query',o['status']['last_result'])
  self.assertEqual(o['runs'],{})


if __name__=='__main__':unittest.main()
