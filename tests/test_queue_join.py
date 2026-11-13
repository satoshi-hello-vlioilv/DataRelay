"""1件ずつ入れた手動の実行が、並列ライン数に余裕があれば、走っている実行へ合流して同時に流れるか（2.40.1）。

不具合（2.40.0 まで）: 実行を入れてから黒板（合流を受け付ける所）ができるまでの数秒（設定・接続情報を読む間）に
次の実行を入れると、合流できずに待機キューへ並ぶ。いったん待機キューに並ぶと、あとから入れた実行も
「先に並んでいる物を追い越さない」決まりで全部並び、並んだ指令は走っている実行へ合流する機会が無い。
結果として、余裕があっても1件ずつ順に流れていた。

ここでは本物の command_dispatcher を動かし、process（実行そのもの）と join_live（黒板への合流）だけを差し替える。
黒板は、実行が始まってから少し遅れて合流を受け付けるようにし、そのあいだに実行を1件ずつ入れる。
実行: python -m unittest tests.test_queue_join -v
"""
import json,os,sys,unittest

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_config import MAKE  # noqa: E402

PY=r'''
import json,sys,threading,time
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_lanerun
spec=json.loads(sys.stdin.read())
live=threading.Event();done=threading.Event();runs=[];joined=[];here=[];cap=spec['cap'];lock=threading.Lock()
def fake_join(jobs,cfg,trigger):
 # 黒板ができるまでは断る。できてからは同時に流す数が cap に収まる間だけ受ける
 with lock:
  if not live.is_set():return False
  if 1+len(here)+len(jobs)>cap:return False
  here.extend(j['id'] for j in jobs);joined.extend(j['id'] for j in jobs);return True
def fake_process(ids,trigger,lines,run_id):
 runs.append(list(ids));here.clear();time.sleep(spec['board_after']);live.set()
 # 黒板が開いている間（合流を受け付ける間）
 time.sleep(spec['open_for']);live.clear()
 if len(runs)>=spec['expect_runs']:done.set()
navi_lanerun.join_live=fake_join;app.process=fake_process
app.after_command=lambda *a,**k:None
t=threading.Thread(target=app.command_dispatcher,daemon=True);t.start()
for i,(jid,gap) in enumerate(spec['enqueue']):
 time.sleep(gap);app.enqueue_command([jid],'manual-single',1)
done.wait(spec['timeout']);time.sleep(0.3);app.stop_event.set()
print(json.dumps({'runs':runs,'joined':joined,'queue':[x['job_ids'] for x in app.command_queue]},ensure_ascii=False))
'''


class QueueJoinTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py'))

 def run_case(self,name,**spec):
  jobs=[{'id':f'j{i}','name':f'対象{i}','enabled':True} for i in range(1,7)]
  self.py(MAKE,name,json.dumps({'cfg':{'jobs':jobs,'settings':{'api_parallel_lines':12}}},ensure_ascii=False))
  return self.py(PY,name,json.dumps(spec))

 def test_one_by_one_joins_the_running_run(self):
  """黒板ができる前に入れた実行も、できたら走っている実行へ合流する（1件ずつ順に流れない）。"""
  out=self.run_case('qj',cap=12,board_after=1.0,open_for=2.5,expect_runs=1,timeout=6,
                    enqueue=[['j1',0],['j2',0.2],['j3',0.2],['j4',0.2],['j5',1.5]])
  self.assertEqual(out['runs'],[['j1']],'実行は1回だけ（ほかは合流）')
  self.assertEqual(out['joined'],['j2','j3','j4','j5'],'入れた順に合流する')
  self.assertEqual(out['queue'],[])

 def test_queue_waits_when_full(self):
  """同時に流す数が上限に届いていれば、待機キューで待ち、先頭から順に流れる（追い越さない）。"""
  out=self.run_case('qf',cap=2,board_after=0.5,open_for=1.5,expect_runs=3,timeout=12,
                    enqueue=[['j1',0],['j2',0.1],['j3',0.1],['j4',0.1]])
  self.assertEqual(out['runs'][0],['j1']);self.assertEqual(out['joined'][0],'j2')
  self.assertEqual([r[0] for r in out['runs'][1:]],['j3','j4'][:len(out['runs'])-1],'並んだ順に流れる')


 def test_default_twelve_lines(self):
  """同時実行ラインの既定は 12（2.40.1）。古い既定の 6 のまま保存されていれば一度だけ 12 へ上げ、6 以外は触らない。"""
  code=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
app.load()
# 2.40.0 までの設定（移行の印が無い）を作る
with app.settings_connection() as c:c.execute("DELETE FROM schema_info WHERE key='migrated_parallel_lines_12'")
app.ensure_settings_migrations()
first=app.load()['settings'].get('api_parallel_lines')
c=app.load();c['settings']['api_parallel_lines']=6;app.save(c)   # 移行のあとで 6 を選び直す
app.ensure_settings_migrations()
print(json.dumps({'first':first,'again':app.load()['settings'].get('api_parallel_lines'),'default':app.SETTING_DEFAULTS['api_parallel_lines']}))
"""
  got={}
  for name,settings in (('d6',{'api_parallel_lines':6}),('d9',{'api_parallel_lines':9}),('dn',{})):
   self.py(MAKE,name,json.dumps({'cfg':{'jobs':[],'settings':settings}}))
   got[name]=self.py(code,name,'')
  self.assertEqual(got['d6'],{'first':12,'again':6,'default':12},'古い既定の 6 は 12 へ。選び直した 6 はそのまま')
  self.assertEqual(got['d9']['first'],9,'利用者が選んだ数は触らない')
  self.assertEqual(got['dn']['first'],12)

if __name__=='__main__':unittest.main()
