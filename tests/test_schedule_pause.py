"""自動実行の一時停止（2.13.0。app.schedule_pause / set_schedule_pause / schedule_tick と /api/schedule-pause）。

・止めている間に時刻の来た予定は、実行キューへ入れずに飛ばす（取り直しも）
・戻したとき、止めている間の予定をまとめて走らせない（飛ばした鍵は進めてある）
・ルールごとの入・切は1つも変えない（戻せば止める前と同じに動く）
・再開する時刻を決めれば、その時刻に自分で戻る。過ぎた時刻は断る
・設定の持ち出し（ZIP）には入らない（運転の状態なので scheduler_state に置く）

実行: python -m unittest tests.test_schedule_pause -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

RUN=r"""
import json,sys
from datetime import datetime,timedelta
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_bundle
got=[];app.enqueue_command=lambda ids,src,lines,**k:got.append((list(ids),src))
c=app.load()
rule={'id':'r1','enabled':True,'name':'毎朝','type':'daily','time':'06:00'}
off={'id':'r2','enabled':False,'name':'夜','type':'daily','time':'22:00'}
c['jobs']=[{'id':'a','name':'a','enabled':True,'source':'rne','rne':'a.RNE','rne_path':'.\\rne\\a.RNE','output_format':'sqlite3','output_file':'a.sqlite3','schedules':[rule,off]}]
app.save(c,quiet=True)
day=lambda n:(datetime.now()+timedelta(days=n)).replace(hour=6,minute=5,second=0,microsecond=0)
tick=lambda now:app.schedule_tick(app.load(),app.load_scheduler_state(),now)
out={}
out['run']=tick(day(1))
app.set_schedule_pause(True)
out['paused']=tick(day(2))
app.retry_waiting.append({'job_ids':['a'],'names':['a'],'lines':1,'attempt':1,'due_at':0})
out['retry_paused']=tick(day(2))['retries']
out['state']=app.schedule_pause()
app.set_schedule_pause(False)
out['after_resume']=tick(day(2))
out['next_day']=tick(day(3))
until=(datetime.now()+timedelta(minutes=30)).isoformat(timespec='minutes')
app.set_schedule_pause(True,until)
out['until']=app.schedule_pause()['until']
out['auto_resume']=tick(day(4))
out['state_after_auto']=app.schedule_pause()
try:app.set_schedule_pause(True,'2000-01-01T00:00');out['past']='通った'
except ValueError as e:out['past']=str(e)
try:app.set_schedule_pause(True,'あした');out['bad']='通った'
except ValueError as e:out['bad']=str(e)
out['rules']=[(r['id'],r['enabled']) for r in app.load()['jobs'][0]['schedules']]
out['queued']=got
t=app.app.test_client()
r=t.post('/api/schedule-pause',json={'paused':True})
out['api_on']=[r.status_code,r.get_json()['pause']]
out['preview']=t.get('/api/schedule-preview').get_json()['pause']
out['api_bad']=t.post('/api/schedule-pause',json={'paused':True,'until':'2000-01-01T00:00'}).status_code
out['api_off']=t.post('/api/schedule-pause',json={'paused':False}).get_json()['pause']['paused']
out['export']=json.dumps(navi_bundle.jobs_export(app.load()['jobs']),ensure_ascii=False)
print(json.dumps(out,ensure_ascii=False,default=str))
"""


class PauseTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',RUN,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
   if r.returncode:raise AssertionError(r.stderr[-3000:])
   cls.v=json.loads(r.stdout.strip().splitlines()[-1])

 def test_runs_when_not_paused(self):
  self.assertEqual(self.v['run']['enqueued'],['a'])
  self.assertFalse(self.v['run']['paused'])

 def test_paused_skips_schedule_and_retry(self):
  p=self.v['paused']
  self.assertTrue(p['paused']);self.assertEqual(p['enqueued'],[]);self.assertEqual(p['skipped'],['a'])
  self.assertEqual(self.v['retry_paused'],1,'取り直しも止める')
  self.assertTrue(self.v['state']['paused']);self.assertTrue(self.v['state']['since'])
  self.assertEqual(self.v['queued'][0][0],['a'],'止める前の1回だけがキューに入った')

 def test_resume_does_not_burst(self):
  self.assertEqual(self.v['after_resume']['enqueued'],[],'止めている間の予定は、戻してもまとめて走らない')
  self.assertEqual(self.v['next_day']['enqueued'],['a'],'次の予定からふだんどおり')

 def test_until_resumes_by_itself(self):
  self.assertTrue(self.v['until'])
  self.assertEqual(self.v['auto_resume']['enqueued'],['a'],'再開の時刻を過ぎれば、その回から走る')
  self.assertFalse(self.v['state_after_auto']['paused'])
  self.assertIn('過ぎています',self.v['past'])
  self.assertIn('読めません',self.v['bad'])

 def test_rules_untouched(self):
  self.assertEqual(self.v['rules'],[['r1',True],['r2',False]],'ルールごとの入・切は変えない')
  self.assertEqual([x[0] for x in self.v['queued']],[['a'],['a'],['a']])

 def test_api(self):
  code,p=self.v['api_on']
  self.assertEqual(code,200);self.assertTrue(p['paused']);self.assertEqual((p['jobs'],p['rules']),(1,1),'止まる物の数（有効なルールだけ）')
  self.assertTrue(self.v['preview']['paused'],'予定の一覧にも載る')
  self.assertEqual(self.v['api_bad'],400)
  self.assertFalse(self.v['api_off'])

 def test_not_in_export(self):
  self.assertNotIn('pause',self.v['export'])


if __name__=='__main__':
 unittest.main()
