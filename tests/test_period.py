"""抽出期間（動的日付）が、実行のときに本当に効いているかを確かめる（2.2.5）。

実機（2026-10-13）で、NaviChangePeriod は rc=OK を返すのに、出力は RNE に保存した期間のままだった。値ごとに分けて出す回では、
期間を変えたあとに条件欄のキーを外し、表側のカテゴリを読み直す。どこで元に戻っているのか（そもそも変わっていないのか）を
実機で見分けられるよう、変える前・変えた直後・実行の直前に期間を読み戻して記録する。変えた直後に変わっていなければ止め、
実行の直前に戻っていればもう一度当てる。それでも違えば止める（誤った期間のまま公開しない）。API は偽物。
実行: python -m unittest tests.test_period -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

CODE=r"""
import json,sys,logging
from datetime import datetime
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
lines=[]
class H(logging.Handler):
 def emit(self,r):
  m=r.getMessage()
  if m.startswith('PERIOD_READBACK'):lines.append(m)
app.log.addHandler(H())
SAVED={'condition':0,'from':'20250400','to':'20250600'}   # RNE に保存した期間
class Fake:
 '''mode: ok（変わる）／ignored（rc=OK でも変わらない）／blind（読み戻せない）／reset（値ごとの付け替えで戻る）／stuck（当て直しても戻る）'''
 def __init__(self,mode):self.mode=mode;self.now=dict(SAVED);self.changes=0
 def get_time_control_point(self,h,label):return 9,'条件'
 def get_period(self,h):return None if self.mode=='blind' else dict(self.now)
 def change_period(self,h,c,f,t,beginning=''):
  self.changes+=1
  if self.mode=='ignored' or (self.mode=='stuck' and self.changes>1):return 0
  self.now={'condition':c,'from':f,'to':t}
 def apply_period(self,h,label,c,f,t):
  hcp,loc=self.get_time_control_point(h,label);before=self.get_period(hcp);self.change_period(hcp,c,f,t)
  return {'handle':hcp,'locate':loc,'label':label,'before':before,'after':self.get_period(hcp)}
 def variant_conditions(self):
  if self.mode in ('reset','stuck'):self.now=dict(SAVED)
job={'name':'設備単位実績','period':{'enabled':True,'unit':'month','from_offset':-3,'to_offset':0,'control_point':'月度'}}
out={}
for mode in ('ok','ignored','blind','reset','stuck'):
 api=Fake(mode);lines.clear();err=''
 try:
  spec=app.apply_dynamic_period(api,1,job,datetime(2026,10,13),line='L1')
  api.variant_conditions()
  app.ensure_period_before_execute(api,spec,job,'L1')
 except Exception as e:err=str(e)
 out[mode]={'error':err,'period':api.now,'changes':api.changes,'log':list(lines)}
print(json.dumps(out,ensure_ascii=False))
"""


class PeriodReadbackTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d)
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
            NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',CODE,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
   assert r.returncode==0,r.stderr[-3000:]
   cls.v=json.loads(r.stdout.strip().splitlines()[-1])

 def test_applied_period_is_confirmed(self):
  v=self.v['ok']
  self.assertEqual(v['error'],'');self.assertEqual((v['period']['from'],v['period']['to']),('20260700','20261000'))
  self.assertEqual([x.split('stage=')[1].split()[0] for x in v['log']],['before','after','pre_execute'],'変える前・変えた直後・実行の直前に読み戻す')
  self.assertIn('verdict=match',v['log'][1]);self.assertIn('from=20250400',v['log'][0],'変える前は RNE に保存した期間')

 def test_ignored_change_stops_instead_of_publishing_the_saved_period(self):
  v=self.v['ignored']
  self.assertIn('抽出期間を 2026年7月度 ～ 2026年10月度 に変えられませんでした',v['error'])
  self.assertIn('20250400～20250600 のまま',v['error'],'読み戻した（RNE に保存した）期間を言う')
  self.assertIn('verdict=unchanged',v['log'][-1])

 def test_unreadable_dll_keeps_running(self):
  v=self.v['blind']
  self.assertEqual(v['error'],'','読み戻せない DLL では止めない（これまでどおり）')
  self.assertIn('verdict=unknown',v['log'][1])

 def test_reset_by_variant_conditions_is_reapplied(self):
  v=self.v['reset']
  self.assertEqual(v['error'],'');self.assertEqual(v['changes'],2,'実行の直前に戻っていたら、もう一度当てる')
  self.assertEqual((v['period']['from'],v['period']['to']),('20260700','20261000'))
  stages=[(x.split('stage=')[1].split()[0],x.split('verdict=')[1]) for x in v['log']]
  self.assertEqual(stages[2:],[('pre_execute','unchanged'),('reapplied','match')])

 def test_still_wrong_after_reapply_stops(self):
  v=self.v['stuck']
  self.assertIn('変えられませんでした',v['error']);self.assertEqual(v['changes'],2)


if __name__=='__main__':
 unittest.main()
