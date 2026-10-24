"""実行中の処理に、あとから入れた実行を合流させる（2.9.1）。

並列ライン数を 6 にしていても、何かが走っている間に行の［実行］を押すと、その実行は実行キューで
前の実行が全部終わるまで待っていた ―― ラインが 5 本空いていても。実行の指令は1つずつしか
動かさず（active_command は1つ）、走り出した実行のライン数もその時の対象の数で決まっていたため。

ここでは本物の実行キュー（enqueue_command・command_dispatcher）と実行本体（process・run_lanes）を通し、
Navigator への問い合わせだけを「決めた秒数だけ待って結果を書く偽のワーカー」に差し替えて、
あとから入れた実行が「入れてから何秒で走り出したか」を測る。

実行: python -m unittest tests.test_live_join -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 偽のワーカー: 対象の comment に書いた秒数だけ待ち、本物と同じ形の result.json を書く。始まりと終わりを events に残す
FAKE = r'''
import json,os,sys,time
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));job=p['job']
ev=Path(os.environ['LJ_EVENTS'])
def say(kind):
 with open(ev,'a',encoding='utf-8') as f:f.write(json.dumps({'t':time.time(),'job':job['name'],'kind':kind,'side':'rne','split':job.get('_split_budget'),'trigger':job.get('_trigger')})+'\n')
say('start')
Path(os.environ['NAVI_WORKER_STATUS']).write_text(json.dumps({'state':'受信','percent':50,'detail':'偽のワーカー'}),encoding='utf-8')
time.sleep(float(job.get('comment') or 1))
if job.get('table')=='fail':
 Path(os.environ['NAVI_WORKER_RESULT']).write_text(json.dumps({'ok':False,'job':job['name'],'error':'わざと失敗','elapsed':0.1}),encoding='utf-8')
else:
 Path(os.environ['NAVI_WORKER_RESULT']).write_text(json.dumps({'ok':True,'job':job['name'],'result':job['name']+' OK','elapsed':float(job.get('comment') or 1),'rows':1,'columns':1,'target':''}),encoding='utf-8')
say('end')
'''

CODE = r'''
import json,os,subprocess,sys,threading,time
from pathlib import Path
root,tmp,mode=sys.argv[1],Path(sys.argv[2]).resolve(),sys.argv[3]
sys.path[:0]=[root,root+'/lib']
import app,navi_lanerun
ev=tmp/'events.jsonl';os.environ['LJ_EVENTS']=str(ev)
fake=tmp/'fake_worker.py';fake.write_text(sys.argv[4],encoding='utf-8')
_popen=subprocess.Popen
def popen(args,*a,**k):
 if len(args)>=3 and str(args[1]).endswith('api_worker.py'):args=[args[0],str(fake),args[2]]
 return _popen(args,*a,**k)
navi_lanerun.subprocess.Popen=popen
logins=[]
def login(cfg):logins.append(time.time());return ('u','p','s','試験')
app.navi_login=login
def say(name,kind,side,trigger=''):
 with open(ev,'a',encoding='utf-8') as f:f.write(json.dumps({'t':time.time(),'job':name,'kind':kind,'side':side,'trigger':trigger})+'\n')
def fake_local(j,cfg,work,backup,trigger,idx,total,say=None):
 say_(j['name'],'start','local',trigger);time.sleep(float(j.get('comment') or 1));say_(j['name'],'end','local',trigger)
 return {'ok':True,'job':j['name'],'result':j['name']+' OK','detail':'OK','job_result':{'job':j['name'],'job_id':j['id'],'status':'ok','detail':'OK'}}
say_=say
app.run_one_local=fake_local
out=tmp/'out';out.mkdir(exist_ok=True)
rne=tmp/'X.RNE';rne.write_text('x',encoding='utf-8')
def job(i,name,secs,kind='rne',fail=False):
 j={'id':i,'name':name,'enabled':True,'source':kind,'rne':'X.RNE','rne_path':str(rne),'output_folder':str(out),'output_format':'csv',
    'output_file':name+'.csv','naming_mode':'fixed','type':'詳細データ','sheet':'Page1','table':'fail' if fail else 't','schedules':[],'comment':str(secs)}
 if kind=='text':j.update(text_path=str(rne),text_layout_id='')
 return j
cap=2 if mode=='over_cap' else 6
cfg=app.load();cfg['settings'].update(api_parallel_lines=cap,api_worker_stagger_ms=0);
first_kind='text' if mode in ('local_local','local_rne') else 'rne'
second_kind='text' if mode in ('local_local','rne_local') else 'rne'
cfg['jobs']=[job('A','A',3,first_kind),job('B','B',1,second_kind,fail=(mode=='fail')),job('C','C',1,'rne'),job('D','D',1,'rne')]
app.save(cfg,quiet=True)
done=[]
_after=app.after_command
def after(item,error='',cancelled=False):done.append({'item':item,'error':error});return _after(item,error,cancelled)
app.after_command=after
threading.Thread(target=app.command_dispatcher,daemon=True).start()
enq={}
def put(ids,trigger='manual'):
 item,pos=app.enqueue_command(ids,trigger,cap);enq['+'.join(ids)+'@'+trigger]={'t':time.time(),'position':pos,'joined':bool(item.get('joined'))};return item
if mode=='over_cap':
 put(['A','B']);time.sleep(1.0);put(['C'])
elif mode=='same_job':
 put(['A']);time.sleep(1.0);put(['A'])
elif mode=='schedule':
 put(['A']);time.sleep(1.0);put(['B'],'schedule:毎朝')
elif mode=='into_schedule':
 put(['A'],'schedule:毎朝');time.sleep(1.0);put(['B'])
elif mode=='cancel':
 put(['A']);time.sleep(1.0);app.cancel_requested.set();time.sleep(0.2);put(['B'])
else:
 put(['A']);time.sleep(1.0);put(['B'])
mid=dict(app.status)
deadline=time.time()+40
while time.time()<deadline:
 time.sleep(0.3)
 with app.command_queue_lock:busy=bool(app.command_queue) or app.active_command is not None
 if not busy and len(done)>=1:break
if mode=='cancel':app.cancel_requested.clear()
events=[json.loads(x) for x in ev.read_text(encoding='utf-8').splitlines()] if ev.exists() else []
runs=app.load_job_runs()
print(json.dumps({'events':events,'enq':enq,'done':[{'ids':d['item'].get('job_ids'),'joined':d['item'].get('joined_ids'),'trigger':d['item'].get('trigger'),'error':d['error'][:200]} for d in done],
 'status':{k:app.status.get(k) for k in ('queue_total','queue_completed','queue_completed_ids','queue_failed_ids','batch_job_ids','step','last_result')},
 'mid_batch':mid.get('batch_job_ids'),'runs':{k:{'status':v.get('status'),'trigger':v.get('trigger')} for k,v in runs.items()},'logins':len(logins),
 'lines':[x.get('line') for x in app.status.get('parallel_lines') or []]},ensure_ascii=False))
'''


def run(mode):
 with tempfile.TemporaryDirectory() as t:
  d = Path(t)
  env = dict(os.environ, NAVI_LOCAL_ROOT=str(d / 'local'), NAVI_DATA_ROOT=str(d / 'data'), NAVI_CONFIG_DIR=str(d / 'data' / 'Config'),
             PYTHONIOENCODING='utf-8')
  r = subprocess.run([sys.executable, '-c', CODE, str(ROOT), str(d), mode, FAKE], env=env, capture_output=True, text=True,
                     encoding='utf-8', timeout=120)
  if r.returncode:
   raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().splitlines()[-1])


def at(o, job, kind, n=0):
 hits = [e['t'] for e in o['events'] if e['job'] == job and e['kind'] == kind]
 return hits[n] if len(hits) > n else None


def wait_of(o, job, key):
 """入れてから走り出すまでの秒数"""
 return at(o, job, 'start') - o['enq'][key]['t']


class LiveJoinTest(unittest.TestCase):
 """並列ライン数の内なら、実行中でもあとから入れた実行がすぐ走り出す"""

 def assertJoinedAndFast(self, o, job='B', key='B@manual'):
  self.assertTrue(o['enq'][key]['joined'], o['enq'])
  self.assertEqual(o['enq'][key]['position'], 0, '合流したら順番待ちの番号は付かない')
  self.assertLess(wait_of(o, job, key), 1.5, f'すぐ走り出す: {o["events"]}')
  self.assertLess(at(o, job, 'start'), at(o, 'A', 'end'), '先の実行が終わるのを待たない')

 def assertOneCommand(self, o, joined=('B',)):
  self.assertEqual(len(o['done']), 1, '合流した実行は、先の実行の一部として1回で締まる')
  self.assertEqual(o['done'][0]['ids'], ['A'])
  self.assertEqual(o['done'][0]['joined'], list(joined))
  self.assertEqual(sorted(o['status']['queue_completed_ids'] + o['status']['queue_failed_ids']), sorted(['A', *joined]))
  self.assertEqual(o['status']['queue_total'], 1 + len(joined))
  self.assertEqual(o['mid_batch'], ['A', *joined], '画面の「この実行の対象」にも足す')

 def test_rne_joins_running_rne(self):
  o = run('rne_rne')
  self.assertJoinedAndFast(o)
  self.assertOneCommand(o)
  self.assertEqual(o['runs']['B'], {'status': 'ok', 'trigger': 'manual'})
  self.assertEqual([e['split'] for e in o['events'] if e['job'] == 'B' and e['kind'] == 'start'], [1],
                   '合流した対象は分割しない（先の対象が持ち分を使っているので、ライン数を超えない）')
  self.assertEqual(o['lines'], ['ライン 1', 'ライン 2'], '空いたラインの番号を足して見せる')

 def test_text_joins_running_text(self):
  o = run('local_local')
  self.assertJoinedAndFast(o)
  self.assertOneCommand(o)

 def test_rne_joins_running_text(self):
  o = run('local_rne')
  self.assertJoinedAndFast(o)
  self.assertOneCommand(o)
  self.assertEqual(o['logins'], 1, 'RNE が入ってきた時点で接続情報を読む（先の実行が手元の処理だけでも）')

 def test_text_joins_running_rne(self):
  o = run('rne_local')
  self.assertJoinedAndFast(o)
  self.assertOneCommand(o)

 def test_failure_of_joined_job_is_reported(self):
  o = run('fail')
  self.assertJoinedAndFast(o)
  self.assertEqual(o['runs']['B']['status'], 'failed')
  self.assertIn('B', o['status']['queue_failed_ids'])
  self.assertIn('失敗', o['done'][0]['error'])

 def test_over_the_line_count_waits_in_the_queue(self):
  o = run('over_cap')
  key = 'C@manual'
  self.assertFalse(o['enq'][key]['joined'], '並列ライン数（2）を超えるぶんは、これまでどおり実行キューで待つ')
  self.assertGreaterEqual(at(o, 'C', 'start'), min(at(o, 'A', 'end'), at(o, 'B', 'end')) - 0.05)
  self.assertEqual(len(o['done']), 2)

 def test_same_job_is_not_run_twice_at_once(self):
  o = run('same_job')
  self.assertFalse(o['enq']['A@manual']['joined'], '2回目の A は合流しない')
  self.assertGreaterEqual(at(o, 'A', 'start', 1), at(o, 'A', 'end', 0) - 0.05, '同じ対象は重ねて走らせない（同じ出力を2本で書く）')

 def test_scheduled_run_does_not_join(self):
  o = run('schedule')
  self.assertFalse(o['enq']['B@schedule:毎朝']['joined'], '自動実行は取り直しの単位を崩さないよう、これまでどおり並ぶ')
  self.assertGreaterEqual(at(o, 'B', 'start'), at(o, 'A', 'end') - 0.05)

 def test_manual_joins_scheduled_run_and_keeps_its_own_trigger(self):
  o = run('into_schedule')
  self.assertJoinedAndFast(o)
  self.assertEqual(o['runs']['B']['trigger'], 'manual', '合流しても、記録はその実行の入れ方（手動）で残す')
  self.assertEqual(o['done'][0]['joined'], ['B'], '自動実行の取り直しから、手動で足した対象を外せるように')

 def test_no_join_after_cancel(self):
  o = run('cancel')
  self.assertFalse(o['enq']['B@manual']['joined'], '中止した実行には足さない')


if __name__ == '__main__':
 unittest.main()
