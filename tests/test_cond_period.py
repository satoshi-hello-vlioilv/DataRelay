"""条件欄の日付へ相対の期間を当てる（2.14.0。lib/navi_period.py・app.apply_cond_period・navigator_api.apply_cond_period）。

時間型の管理ポイントが無く、条件欄に日付を直接入れてある RNE（例: 払出日: 2026/1/1 -->）で、実行のたびに
「3か月前から」「先月の1日から末日まで」のように日付を差し替える。見本は利用者の RNE（作成者名などを伏せた写し）。
・RNE の条件欄の日付（値・範囲の形）を読める
・日付の書き方は RNE に入っている日付にそろえる（2026/1/1 → 2026/7/27。0埋めの形なら 0埋め）
・範囲の形は 期間（両端）・以降（NAVI_OVER）・以前（NAVI_UNDER）。月を単位にすると月の1日～末日
・読み戻しで変わっていなければ記録する（止めるかは管理ポイントの期間と同じ PERIOD_STOP_ON_MISMATCH）
・実行の直前に戻っていれば当て直す
・昔の保存（target・range が無い）は「管理ポイント・期間」として読む。API は偽物
実行: python -m unittest tests.test_cond_period -v
"""
import json,os,subprocess,sys,tempfile,unittest
from datetime import date,datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
FIXTURE=ROOT/'tests'/'fixtures'/'cond_date.RNE'
CAST=ROOT/'tests'/'fixtures'/'cast_date.RNE'   # 鋳造分析値（実機 2026-10-28）: 条件欄は 登録日付 だけ
sys.path.insert(0,str(ROOT/'lib'))
import navi_crosstab as NC  # noqa: E402
import navi_period as NP  # noqa: E402

NOW=datetime(2026,10,27,9,0)


class RuleTest(unittest.TestCase):
 def test_old_saved_form_reads_as_point_between(self):
  p=NP.normalize({'enabled':True,'unit':'day','from_offset':-6,'to_offset':0,'control_point':'日'})
  self.assertEqual((p['target'],p['range'],p['cond_item']),('point','between',''))
  self.assertEqual(NP.normalize({'target':'point','range':'from'})['range'],'between','管理ポイントは両端が要る')
  self.assertEqual(NP.normalize({'target':'cond','range':'to'})['range'],'to')
  self.assertEqual(NP.normalize(None)['enabled'],False)

 def test_format_follows_the_rne(self):
  d=date(2026,7,5)
  self.assertEqual(NP.format_like('2026/1/1',d),'2026/7/5')
  self.assertEqual(NP.format_like('2026/01/01',d),'2026/07/05')
  self.assertEqual(NP.format_like('2026-01-01 00:00:00',d),'2026-07-05')
  self.assertEqual(NP.format_like('20260101',d),'20260705')
  self.assertEqual(NP.format_like('',d),'2026/7/5','手本が無ければ RNE と同じ 2026/1/1 の形')

 def test_cond_ranges(self):
  base={'enabled':True,'target':'cond','cond_item':'払出日','unit':'month','from_offset':-3,'to_offset':-1}
  s=NP.compute({**base,'range':'between'},NOW,'2026/1/1')
  self.assertEqual((s['kind'],s['lvalue'],s['rvalue']),('cond','2026/7/1','2026/9/30'),'月は1日～末日')
  self.assertEqual(s['summary'],'2026/7/1 ～ 2026/9/30')
  s=NP.compute({**base,'range':'from'},NOW,'2026/1/1')
  self.assertEqual((s['lvalue'],s['rvalue'],s['summary']),('2026/7/1','','2026/7/1 以降'))
  s=NP.compute({**base,'range':'to'},NOW,'2026/1/1')
  self.assertEqual((s['lvalue'],s['rvalue'],s['summary']),('','2026/9/30','2026/9/30 以前'))
  s=NP.compute({**base,'unit':'day','from_offset':-90,'to_offset':0,'range':'between'},NOW,'2026/01/01')
  self.assertEqual((s['lvalue'],s['rvalue']),('2026/07/29','2026/10/27'))
  s=NP.compute({**base,'unit':'day','from_offset':0,'to_offset':-7,'range':'between'},NOW,'')
  self.assertEqual((s['lvalue'],s['rvalue']),('2026/10/20','2026/10/27'),'前後が逆なら入れ替える')

 def test_point_form_unchanged(self):
  s=NP.compute({'enabled':True,'unit':'month','from_offset':-3,'to_offset':0},datetime(2026,10,13))
  self.assertEqual((s['kind'],s['condition'],s['from_time'],s['to_time']),('point',0,'20260700','20261000'))

 def test_resolve_item(self):
  one=[{'name':'登録設備','date':False},{'name':'登録日付','date':True,'value':'2026/1/1','range':4}]
  self.assertEqual(NP.resolve_cond_item('登録日付',one),('登録日付','saved'))
  self.assertEqual(NP.resolve_cond_item('払出日',one),('登録日付','replaced'),'別の RNE の名前が残っていても、日付の項目が1つなら使う')
  self.assertEqual(NP.resolve_cond_item('',one),('登録日付','auto'),'空は自動')
  self.assertEqual(NP.resolve_cond_item('払出日',None),('払出日','saved'),'RNE を読めなければ保存のまま')
  two=[{'name':'受入日','date':True,'value':'','range':0},{'name':'出荷日','date':True,'value':'2026/1/1','range':4}]
  self.assertEqual(NP.resolve_cond_item('',two),('出荷日','auto'),'複数なら、値の入っている物')
  both=[dict(x,value='2026/1/1',range=4) for x in two]
  self.assertEqual(NP.resolve_cond_item('払出日',both),(None,'ambiguous'),'絞れなければ決めない（黙って違う項目に当てない）')
  self.assertEqual(NP.resolve_cond_item('払出日',[{'name':'登録設備','date':False}]),(None,'none'))

 def test_readback(self):
  spec={'range':'between','lvalue':'2026/7/1','rvalue':'2026/9/30'}
  self.assertEqual(NP.cond_readback(spec,{'lvalue':'2026/07/01','rvalue':'2026/09/30'}),'match','書き方の違いは同じ')
  self.assertEqual(NP.cond_readback(spec,{'lvalue':'2026/1/1','rvalue':''}),'differs')
  self.assertEqual(NP.cond_readback(spec,None),'unknown')
  self.assertEqual(NP.cond_readback({'range':'from','lvalue':'2026/7/1'},{'lvalue':'2026/7/1','rvalue':''}),'match')


class RneTest(unittest.TestCase):
 def test_reads_the_date_condition(self):
  got=NC.read_conditions(FIXTURE)
  self.assertEqual(len(got),1)
  self.assertEqual((got[0]['name'],got[0]['value'],got[0]['range'],got[0]['date']),('払出日','2026/1/1',4,True),
                   '払出日: 2026/1/1 -->（以降 = NAVI_OVER の 4）')
  self.assertFalse(NC.read_rne_layout(FIXTURE)['crosstab'])

 def test_cast_rne(self):
  got=NC.read_conditions(CAST)
  self.assertEqual([(x['name'],x['value'],x['range'],x['date']) for x in got],[('登録日付','2026/1/1',4,True)],'登録日付: 2026/1/1 -->')

 def test_date_by_name_when_empty(self):
  got={x['name']:x for x in NC.read_conditions(ROOT/'samples'/'defaults'/'rne'/'SIKALOTDEF.RNE')}
  self.assertTrue(got['倉入完了_年月日']['date']);self.assertFalse(got['登録設備']['date'])


APPLY=r"""
import json,sys,logging
from datetime import datetime
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
lines=[]
class H(logging.Handler):
 def emit(self,r):
  m=r.getMessage()
  if m.startswith(('PERIOD_READBACK','PERIOD_NOT_CONFIRMED','DYNAMIC_PERIOD','COND_PERIOD_ITEM')):lines.append(m)
app.log.addHandler(H())
class Fake:
 '''mode: ok（変わる）／blind（読み出せない）／ignored（rc=OK でも変わらない）／reset（値ごとの付け替えで戻る）'''
 def __init__(self,mode):self.mode=mode;self.now={'condition':2,'range':4,'lvalue':'2026/1/1','rvalue':''};self.changes=[]
 def get_condition_di(self,h):return None if self.mode=='blind' else dict(self.now)
 def change_cond_period(self,h,spec):
  self.changes.append((spec['range'],spec['lvalue'],spec['rvalue']))
  if self.mode=='ignored':return True
  self.now={'condition':2,'range':{'between':2,'from':4,'to':1}[spec['range']],'lvalue':spec['lvalue'],'rvalue':spec['rvalue']}
  return True
 def apply_cond_period(self,h,item,compute):
  if item!='払出日':raise RuntimeError('条件欄に「'+item+'」がありません')
  before=self.get_condition_di(7);spec=compute((before or {}).get('lvalue') or '');self.change_cond_period(7,spec)
  return {'handle':7,'spec':spec,'before':before,'after':self.get_condition_di(7),'form':'x'}
 def variant_conditions(self):
  if self.mode=='reset':self.now={'condition':2,'range':4,'lvalue':'2026/1/1','rvalue':''}
job={'name':'返り材','rne_path':sys.argv[2],'period':{'enabled':True,'target':'cond','cond_item':'払出日','range':'between','unit':'month','from_offset':-3,'to_offset':-1}}
out={}
for mode in ('ok','blind','ignored','reset','missing','auto'):
 api=Fake(mode);lines.clear();err=''
 j=dict(job,period=dict(job['period'],cond_item={'missing':'受入日','auto':''}.get(mode,'払出日')))
 try:
  spec=app.apply_dynamic_period(api,1,j,datetime(2026,10,27),line='L1')
  api.variant_conditions()
  app.ensure_period_before_execute(api,spec,j,'L1')
 except Exception as e:err=str(e)
 out[mode]={'error':err,'now':api.now,'changes':api.changes,'log':list(lines)}
t=app.app.test_client()
out['targets']=t.post('/api/period-targets',json={'rne_path':sys.argv[2]}).get_json()
out['preview']=t.post('/api/period-preview',json={'target':'cond','cond_item':'払出日','range':'from','unit':'day','from_offset':-90,'to_offset':0,'sample':'2026/1/1'}).get_json()
c=app.load();c['jobs']=[dict(job,id='a',enabled=True,source='rne',rne='x.RNE',output_format='sqlite3',output_file='a.sqlite3',schedules=[])];app.save(c,quiet=True)
out['saved']=app.load()['jobs'][0]['period']
print(json.dumps(out,ensure_ascii=False,default=str))
"""


class ApplyTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d)
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
            NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',APPLY,str(ROOT),str(FIXTURE)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
   if r.returncode:raise AssertionError(r.stderr[-3000:])
   cls.v=json.loads(r.stdout.strip().splitlines()[-1])

 def test_applied_in_rne_format(self):
  v=self.v['ok']
  self.assertEqual(v['error'],'')
  self.assertEqual(v['changes'],[['between','2026/7/1','2026/9/30']])
  self.assertTrue(any('verdict=match' in x and 'stage=after' in x for x in v['log']),v['log'])

 def test_blind_uses_rne_sample(self):
  v=self.v['blind']
  self.assertEqual(v['error'],'');self.assertEqual(v['changes'],[['between','2026/7/1','2026/9/30']],'読み出せなくても RNE の日付の書き方')
  self.assertTrue(any('verdict=unknown' in x for x in v['log']))

 def test_ignored_is_recorded(self):
  v=self.v['ignored']
  self.assertEqual(v['error'],'','止めない（管理ポイントの期間と同じ扱い）')
  self.assertTrue(any(x.startswith('PERIOD_NOT_CONFIRMED') for x in v['log']),v['log'])

 def test_reset_is_reapplied(self):
  v=self.v['reset']
  self.assertEqual(len(v['changes']),2,'実行の直前に戻っていれば当て直す')
  self.assertEqual((v['now']['lvalue'],v['now']['rvalue']),('2026/7/1','2026/9/30'))

 def test_missing_item_is_replaced(self):
  v=self.v['missing']
  self.assertEqual(v['error'],'','保存した名前が RNE に無くても、日付の項目が1つならそれに当てる')
  self.assertEqual(v['changes'],[['between','2026/7/1','2026/9/30']])
  self.assertTrue(any(x.startswith('COND_PERIOD_ITEM') and 'saved=受入日' in x and 'used=払出日' in x for x in v['log']),v['log'])

 def test_empty_item_is_auto(self):
  v=self.v['auto'];self.assertEqual(v['error'],'');self.assertEqual(len(v['changes']),1)

 def test_routes_and_store(self):
  t=self.v['targets'];self.assertTrue(t['ok']);self.assertEqual(t['conditions'][0]['name'],'払出日')
  p=self.v['preview'];self.assertTrue(p['ok']);self.assertEqual((p['kind'],p['range'],p['rvalue']),('cond','from',''))
  s=self.v['saved'];self.assertEqual((s['target'],s['cond_item'],s['range']),('cond','払出日','between'),'保存して読み直しても同じ')


class ScreenTest(unittest.TestCase):
 """画面（§3 の J 案）: 上の帯（当てる先・RNE のいま）・形・いつ・時間の線・プレビューが揃い、中身と同じ受け口を呼ぶ。"""
 def test_parts(self):
  html=(ROOT/'templates'/'index.html').read_text(encoding='utf-8');js=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
  for i in ('pd-target-chip','pd-now','pd-target-change','pd-target-pick','pd-target-seg','pd-cond-list','pd-range-seg','period-unit-seg',
            'm-period-from','m-period-to','period-from-dir','period-to-dir','m-period-cp','m-period-detect','pd-line','m-period-preview'):
   self.assertIn(f'id="{i}"',html,i)
  for r in ('between','from','to'):self.assertIn(f'data-range="{r}"',html)
  for t in ('cond','point'):self.assertIn(f'data-target="{t}"',html)
  self.assertIn("'/api/period-targets'",js);self.assertIn("'/api/period-preview'",js)
  self.assertIn('target,cond_item:periodState.cond_item,range',js,'保存する形（target・cond_item・range）を画面が作る')


if __name__=='__main__':
 unittest.main()


class RealFormTest(unittest.TestCase):
 """2.14.1: 実機（2026-10-28）で NaviChangeConditionDI が NAVI_ERROR_VALUE（0x18）を返した（range=OVER l='2026/7/1'）。
 渡し方を1つに決め打ちせず、確からしい順に試して通った形を使う。どれも通らなければ、いまの条件と試した形を添えて止める。
 navigator_api.NavigatorApi.apply_cond_period を、DLL を偽物にして動かす。"""
 def api(self,accept,before={'condition':2,'range':4,'lvalue':'2026/1/1','rvalue':''}):
  import navigator_api as NA
  a=NA.NavigatorApi.__new__(NA.NavigatorApi);a.calls=[]
  a.supports_row_split=lambda:True
  a.get_data_item=lambda h,name,locate=None,order=0:7 if name=='払出日' else 0
  a.get_condition_di=lambda h:dict(before) if before is not None else None
  def change(h,condition,key='',search=0,nonmatch=0,rng=0,lcheck=0,lvalue='',rcheck=0,rvalue='',reserve=''):
   a.calls.append((rng,lvalue,rvalue))
   if not accept(rng,lvalue,rvalue):raise NA.NavigatorApiError('NaviChangeConditionDI',0x18,f'range=0x{rng:x} l={lvalue!r} r={rvalue!r}')
  a.change_condition_di=change
  return a

 def compute(self,rng='from'):
  return lambda sample:NP.compute({'enabled':True,'target':'cond','cond_item':'払出日','range':rng,'unit':'month','from_offset':-3,'to_offset':-1},NOW,sample)

 def test_tries_other_date_forms(self):
  a=self.api(lambda r,l,rv:l=='2026/07/01')
  info=a.apply_cond_period(1,'払出日',self.compute())
  self.assertEqual(a.calls[0],(4,'2026/7/1',''),'まず RNE と同じ書き方')
  self.assertEqual(a.calls[-1],(4,'2026/07/01',''),'通らなければ0埋めの形')
  self.assertEqual(info['spec']['lvalue'],'2026/07/01','通った形で読み戻しと当て直しをする')
  self.assertIn('2026/07/01',info['form'])

 def test_falls_back_to_between(self):
  a=self.api(lambda r,l,rv:r==2)
  info=a.apply_cond_period(1,'払出日',self.compute())
  self.assertEqual(a.calls[-1][0],2,'以降が断られたら、終わりを遠い先にした期間で渡す')
  self.assertTrue(a.calls[-1][2].startswith('9999'),a.calls[-1])
  a.calls.clear();a.change_cond_period(7,info['spec'])
  self.assertEqual(a.calls,[info['spec']['_form']],'当て直しも通った形で渡す')

 def test_all_fail_reports_current_and_tried(self):
  a=self.api(lambda r,l,rv:False)
  with self.assertRaises(Exception) as cm:a.apply_cond_period(1,'払出日',self.compute())
  m=str(cm.exception)
  self.assertIn("いまの条件: condition=0x2 range=0x4 l='2026/1/1'",m,'次の報告で正しい形が分かるように')
  self.assertIn('2026/07/01',m);self.assertIn('20260701',m)

 def test_item_follows_rne(self):
  import os
  code=r'''
import sys,json
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
from datetime import datetime
class Api:
 item=None
 def apply_cond_period(self,h,item,compute):
  Api.item=item;spec=compute('2026/1/1');assert spec['item']==item,spec;return {'handle':7,'spec':spec,'before':None,'after':None,'form':'x'}
out={}
real=app._rne_conditions
two=[{'name':n,'date':True,'value':'2026/1/1','range':4} for n in ('受入日','出荷日')]
for name,rne,item in (('cast',sys.argv[2],'払出日'),('ambiguous',sys.argv[2],'払出日')):
 Api.item=None
 app._rne_conditions=real if name=='cast' else (lambda j:two)   # 日付の項目が2つとも入っている RNE
 job={'name':'鋳造分析値','rne_path':rne,'period':{'enabled':True,'target':'cond','cond_item':item,'range':'from','unit':'month','from_offset':-3}}
 try:s=app.apply_dynamic_period(Api(),1,job,datetime(2026,10,28),'L1');out[name]={'err':'','item':Api.item,'lvalue':s['lvalue']}
 except Exception as e:out[name]={'err':str(e),'item':Api.item}
print(json.dumps(out,ensure_ascii=False))
'''
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'l'),NAVI_DATA_ROOT=str(d/'d'),NAVI_CONFIG_DIR=str(d/'d'/'C'),NAVI_SECRET_FILE=str(d/'l'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',code,str(ROOT),str(CAST)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['cast'],{'err':'','item':'登録日付','lvalue':'2026/7/1'},'実機 2026-10-28: 払出日が残っていても、RNE の 登録日付 に当てる')
  a=v['ambiguous']
  self.assertIsNone(a['item'],'日付の項目を絞れなければ、Navigator に頼む前に止める')
  self.assertIn('払出日',a['err']);self.assertIn('受入日（日付）',a['err']);self.assertIn('出荷日（日付）',a['err'])
