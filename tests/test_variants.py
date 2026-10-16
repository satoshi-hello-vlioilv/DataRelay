"""条件の値ごとに分けて出す（2.1.0／2.1.1。lib/navi_variants.py と app.process_api_parallel_job）。

本物の Navigator は無いので、API を偽物に差し替えて、値ごとの実行・ファイル名・置き場・絞れたかの確かめ・公開までを通す。
偽物は「いまの条件のキー」だけの行を返す（条件が効かない偽物は、全部の値の行を返す）。
条件の差し替えそのもの（NaviChangeConditionDI へ何を渡すか）は、DLL を偽物にして引数を確かめる。

実行: python -m unittest tests.test_variants -v
"""
import csv,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_variants as V


class RulesTest(unittest.TestCase):
 def test_normalize(self):
  v=V.normalize({'enabled':1,'item':' BOX実績_設備名 ','values':['LS3',' LS4','LS3','',None,'DL2'],'pattern':' {値}_実績 '})
  self.assertEqual(v,{'enabled':True,'item':'BOX実績_設備名','scope':'listed','values':['LS3','LS4','DL2'],'pattern':'{値}_実績','folder':'','method':'default'},
                   '前後の空白を落とし、重ねず、空は捨てる')
  self.assertEqual(V.normalize(None)['values'],[])
  self.assertEqual(len(V.normalize({'values':[str(i) for i in range(200)]})['values']),V.MAX_VALUES)

 def test_active(self):
  self.assertFalse(V.active({'variants':{'enabled':True,'item':'x','values':[]}}),'値が無ければ分けない')
  self.assertFalse(V.active({'variants':{'enabled':False,'item':'x','values':['a']}}),'切ってあれば分けない')
  self.assertTrue(V.active({'variants':{'enabled':True,'item':'x','values':['a']}}))

 def test_method(self):
  """取り方: 対象で選んでいればそれ、「既定に従う」なら共通設定の既定、どちらも無ければまとめて1回。"""
  self.assertEqual(V.normalize({'method':'parallel'})['method'],'parallel')
  self.assertEqual(V.normalize({'method':'どれか'})['method'],'default','知らない値は既定に従う')
  self.assertEqual(V.default_method({}),'combined')
  self.assertEqual(V.default_method({'variant_method':'parallel'}),'parallel')
  self.assertEqual(V.default_method({'variant_method':'x'}),'combined')
  job=lambda m:{'variants':{'enabled':True,'item':'x','values':['a'],'method':m}}
  self.assertEqual(V.method(job('default'),{'variant_method':'parallel'}),'parallel','既定に従う')
  self.assertEqual(V.method(job('combined'),{'variant_method':'parallel'}),'combined','対象の選択が勝つ')
  self.assertEqual(V.method(job('parallel'),{}),'parallel')

 def test_plan_names(self):
  render=lambda t,v:t.replace('{値}',v).replace('{value}',v)
  job={'variants':{'enabled':True,'item':'x','values':['LS3','LS4']}}
  self.assertEqual([x['stem'] for x in V.plan(job,render,'LOTACH','out')],['LOTACH_LS3','LOTACH_LS4'],'型が無ければ「ふだんの名前_値」')
  job={'naming_mode':'template','output_pattern':'実績_{値}','variants':{'enabled':True,'item':'x','values':['LS3']}}
  self.assertEqual(V.plan(job,render,'実績_','out')[0]['stem'],'実績_LS3','対象の名前の型に {値} があればそれを使う')
  job={'variants':{'enabled':True,'item':'x','values':['LS3'],'pattern':'{value}設備','folder':'D:\\出力\\{値}'}}
  self.assertEqual(V.plan(job,render,'LOTACH','out'),[{'value':'LS3','stem':'LS3設備','folder':'D:\\出力\\LS3'}])

 def test_plan_refuses_same_name(self):
  render=lambda t,v:t.replace('{値}',v)
  job={'variants':{'enabled':True,'item':'x','values':['LS3','LS4'],'pattern':'実績'}}
  with self.assertRaisesRegex(ValueError,'同じファイル名'):V.plan(job,render,'LOTACH','out')
  job['variants']['folder']='out\\{値}'
  self.assertEqual(len(V.plan(job,render,'LOTACH','out')),2,'置き場が値ごとに違えば同じ名前でよい')

 def test_split_csv(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.csv'
   # write_bytes で書く（write_text は Windows で \n を \r\n に変え、\r\r\n になって空の行が挟まる）
   p.write_bytes('仕掛区分,BOX実績_設備名,ﾛｯﾄ番号\r\nA,LS4,1\r\nA,,2\r\nB,LS3,3\r\nB,PSW,4\r\nC,LS3,5\r\n'.encode('cp932'))
   sp=V.split_csv(p,'BOX実績_設備名',['LS3','LS4','KEN'],Path(d)/'parts')
   self.assertFalse(sp['missing_column']);self.assertEqual(sp['rows'],5)
   self.assertEqual(sp['found'],['LS4','LS3','PSW'],'出てきた値（頼んでいない PSW も数える）')
   self.assertEqual({k:v['rows'] for k,v in sp['parts'].items()},{'LS3':2,'LS4':2,'KEN':0},'空のマスは上の行の値を引き継ぐ')
   with open(sp['parts']['LS4']['path'],encoding='cp932',newline='') as f:rows=list(csv.reader(f))
   self.assertEqual(rows,[['仕掛区分','BOX実績_設備名','ﾛｯﾄ番号'],['A','LS4','1'],['A','LS4','2']],'同じ見出し・その値の行だけ・空のマスは値で埋める')
   self.assertTrue(V.split_csv(p,'無い列',['LS3'],Path(d)/'p2')['missing_column'])
   # 空の行（\r\r\n や末尾の空行）は数えず、上の値のファイルにも入れない
   q=Path(d)/'b.csv';q.write_bytes('仕掛区分,BOX実績_設備名,ﾛｯﾄ番号\r\r\nA,LS4,1\r\r\n\r\n,,\r\nB,LS3,3\r\n\r\n'.encode('cp932'))
   sq=V.split_csv(q,'BOX実績_設備名',['LS3','LS4'],Path(d)/'p3')
   self.assertEqual((sq['rows'],{k:v['rows'] for k,v in sq['parts'].items()}),(2,{'LS3':1,'LS4':1}))

 def test_split_csv_all_found(self):
  """出てきた値すべて（2.5.0）: 値を渡さず、出てきた順にファイルを作る。値が空の行は blank に数え、どこにも入れない。上限を超えたら断る。"""
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.csv'
   p.write_bytes('仕掛区分,BOX実績_設備名,ﾛｯﾄ番号\r\nZ,,0\r\nA,LS4,1\r\nA,,2\r\nB,LS3,3\r\nB,PSW,4\r\nC,LS3,5\r\n'.encode('cp932'))
   sp=V.split_csv(p,'BOX実績_設備名',None,Path(d)/'parts')
   self.assertEqual(list(sp['parts']),['LS4','LS3','PSW'],'出てきた順')
   self.assertEqual({k:v['rows'] for k,v in sp['parts'].items()},{'LS4':2,'LS3':2,'PSW':1})
   self.assertEqual((sp['rows'],sp['blank']),(6,1),'先頭の値が空の行は、どの値にも入れず blank に数える')
   with open(sp['parts']['PSW']['path'],encoding='cp932',newline='') as f:rows=list(csv.reader(f))
   self.assertEqual(rows,[['仕掛区分','BOX実績_設備名','ﾛｯﾄ番号'],['B','PSW','4']])
   with self.assertRaisesRegex(ValueError,'2 を超えました'):V.split_csv(p,'BOX実績_設備名',None,Path(d)/'p2',limit=2)
   # UTF-8 の中間CSV（cp932 で読めない）も、書きかけを残さず読み直す
   u=Path(d)/'u.csv';u.write_bytes('区分,設備\r\n甲,ＬＳ３\r\n乙,🙂\r\n'.encode('utf-8'))
   su=V.split_csv(u,'設備',None,Path(d)/'p3')
   self.assertEqual((su['encoding'],list(su['parts'])),('utf-8-sig',['ＬＳ３','🙂']))

 def test_count_csv(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.csv'
   p.write_bytes('仕掛区分,BOX実績_設備名\r\nA,LS4\r\nA,\r\nB,LS3\r\n\r\n'.encode('cp932'))
   c=V.count_csv(p,'BOX実績_設備名')
   self.assertEqual((c['values'],c['rows'],c['blank'],c['missing_column']),([{'value':'LS4','rows':2},{'value':'LS3','rows':1}],3,0,False))
   self.assertEqual(list(Path(d).iterdir()),[p],'ファイルは作らない')
   self.assertTrue(V.count_csv(p,'無い列')['missing_column'])

 def test_scope(self):
  """出てきた値すべて: 値が無くても入る。取り方はいつもまとめて1回。名前に {値} が無ければ先に断る。"""
  allj=lambda **k:{'variants':{'enabled':True,'item':'x','scope':'all',**k}}
  self.assertEqual(V.normalize({'scope':'?'})['scope'],'listed','知らない値・古い設定は指定した値だけ')
  self.assertTrue(V.active(allj()))
  self.assertFalse(V.active(allj(item='')),'項目は要る')
  self.assertTrue(V.everything(allj()));self.assertTrue(V.everything(allj()['variants']))
  self.assertEqual(V.method(allj(method='parallel'),{'variant_method':'parallel'}),'combined','値が先に分からないので並列にできない')
  self.assertEqual(V.normalize(allj(values=['a'])['variants'])['values'],['a'],'切り替えて戻ったときのために値は残す')
  render=lambda t,v:t.replace('{値}',v)
  self.assertEqual([x['stem'] for x in V.plan(allj(),render,'LOTACH','out',values=['P','Q'])],['LOTACH_P','LOTACH_Q'],'出てきた値を渡して名前を決める')
  self.assertIn('{値} がありません',V.name_error(allj(pattern='実績')))
  self.assertEqual(V.name_error(allj(pattern='実績',folder='o\\{値}')),'','置き場に {値} があればよい')
  self.assertEqual(V.name_error(allj()),'','型が空なら「ふだんの名前_値」なので重ならない')
  self.assertEqual(V.name_error({'variants':{'item':'x','values':['a'],'pattern':'実績'}}),'','指定した値だけは plan が確かめる')

 def test_relax_rules(self):
  self.assertTrue(V.need_relax([],['LS4'],True),'出てきた値すべて: RNE がキーで絞っていれば外す')
  self.assertFalse(V.need_relax([],[],True),'絞っていなければ外さない')
  self.assertFalse(V.need_relax(['LS4'],['LS4']));self.assertTrue(V.need_relax(['LS3'],['LS4']))
  self.assertEqual((V.relax_hint(['LS3'],['LS4']),V.relax_hint([],['LS4']),V.relax_hint([],[])),('LS3','LS4',''))
  self.assertFalse(V.relaxed(['LS4'],['LS4'],[],True),'キーの値しか返らなければ、外せていないかもしれない')
  self.assertTrue(V.relaxed(['LS4','LS3'],['LS4'],[],True))

 def test_count_state(self):
  rec=V.count_record({'values':[{'value':'a','rows':1}],'rows':1},'x',(123,9),{'enabled':True,'unit':'month'},'2026-10-16T10:00:00')
  self.assertEqual(V.count_state(rec,'x',(123,9),{'enabled':True,'unit':'month'}),'fresh')
  self.assertEqual(V.count_state(rec,'x',(124,9),{'enabled':True,'unit':'month'}),'stale','RNE が変わった')
  self.assertEqual(V.count_state(rec,'x',(123,9),{'enabled':True,'unit':'day'}),'stale','期間指定が変わった')
  self.assertEqual(V.count_state(rec,'y',(123,9),{}),'none','項目が違えば使わない')
  self.assertEqual(V.count_state(None,'x',(123,9),{}),'none')

 def test_relaxed(self):
  self.assertTrue(V.relaxed(['LS4','LS3'],['LS4'],['LS3','LS4']),'RNE のキー以外の値が返っていれば外せている')
  self.assertFalse(V.relaxed(['LS4'],['LS4'],['LS3','LS4']),'LS4 しか返らないのに LS3 を頼んでいれば、外せていない')
  self.assertTrue(V.relaxed(['LS4'],['LS4'],['LS4']),'RNE のキーの中だけを頼んだなら外す必要が無い')
  self.assertTrue(V.relaxed([],[],['LS3']),'RNE に条件のキーが無ければ確かめようがない（止めない）')

 def test_summary(self):
  t=V.summary([{'value':'LS3','ok':True,'rows':1200},{'value':'KEN','ok':False,'error':'抽出0件'}])
  self.assertEqual(t,'1/2ファイル（LS3 1,200件） / 失敗: KEN（抽出0件）')


class BundleTest(unittest.TestCase):
 def test_unused_variants_are_not_exported(self):
  """使っていない対象は、持ち出し・既定の設定に variants を書かない（2.0.0 の既定の設定と比べて「中身が違う」にしない）。"""
  import navi_bundle as B
  self.assertNotIn('variants',B.job_export_one({'name':'a','variants':V.normalize({})}))
  v=V.normalize({'enabled':True,'item':'x','values':['LS3']})
  self.assertEqual(B.job_export_one({'name':'a','variants':v})['variants'],v,'使っている対象は持ち出す')


class RelaxConditionTest(unittest.TestCase):
 """条件欄の絞り込みを外す形（2.1.1）。項目は条件欄から引き、まず NULL以外、通らなければ一致＋キー1つ。"""
 def setUp(self):
  import navigator_api as N
  self.N=N;self._ansi=N._ansi;N._ansi=lambda v:str(v).encode('cp932')   # mbcs は Windows だけ
 def tearDown(self):self.N._ansi=self._ansi

 def make(self,fail_first=False,handle=7):
  N=self.N;calls=[]
  class Dll:
   NaviGetDataItem=True
   def NaviChangeConditionDI(self,h,rc,cond,key,search,nonmatch,rng,lc,lv,rcck,rv,res):
    calls.append({'h':h,'cond':cond,'key':key.decode('cp932'),'search':search})
    rc._obj.value=1 if (fail_first and len(calls)==1) else 0
  api=object.__new__(N.NavigatorApi);api.dll=Dll()
  api.error_message=lambda:(0,'');api.error_code=lambda:0
  located=[]
  def get_data_item(h,label,locate=N.NAVI_DATA,order=0):
   located.append((label,locate));return handle
  api.get_data_item=get_data_item
  return api,calls,located

 def test_except_null_first(self):
  api,calls,located=self.make()
  got=api.relax_condition(1,'BOX実績_設備名','LS3')
  self.assertEqual(located,[('BOX実績_設備名',self.N.NAVI_COND)],'条件欄から引く')
  self.assertEqual(calls,[{'h':7,'cond':self.N.NAVI_EXCEPTNULL,'key':'','search':self.N.NAVI_COMPLETE}])
  self.assertEqual(got['form'],'NULL以外（キーの絞り込みを外す）')

 def test_second_form_and_missing_item(self):
  api,calls,_=self.make(fail_first=True)
  self.assertEqual(api.relax_condition(1,'x','LS3')['form'],'一致＋キー1つ（実機でほぼ全件が返った形）')
  self.assertEqual([(c['cond'],c['key']) for c in calls],[(self.N.NAVI_EXCEPTNULL,''),(self.N.NAVI_MATCH,'LS3')])
  api,_,_=self.make(handle=0)
  with self.assertRaisesRegex(self.N.NavigatorApiError,'条件欄に「x」がありません'):api.relax_condition(1,'x','LS3')


# 本物の app で、値ごとの実行を最後（公開）まで通す。API は偽物
FLOW=r"""
import json,shutil,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navigator_api
work=Path(sys.argv[2]);mode=sys.argv[3]
ALL=['LS3','LS4','DL2','KEN']
SERVER=['LS3','LS4','DL2','KEN','PSW','ST2']   # サーバーにある設備。RNE の条件は LS4
if mode=='all40':SERVER=['LS4']+[f'S{i:02d}' for i in range(39)]   # 値の数が、同時に進める上限（32）より多い
calls=[]
class Fake:
 # 実機（2026-10-11）に寄せる: 条件欄を外すと全部の設備が返る。表側のカテゴリを絞るとその設備だけ。外さなければ LS4 だけ
 dll_path='fake.dll'
 def __init__(self,*a,**k):self.relaxed=False;self.shown=None
 def open_session(self,*a):return 0.01
 def connect_data_source(self,p):return 0.01
 def open_catalog(self,p):calls.append(('open',Path(p).name));return 1,0.01
 def apply_period(self,*a):return {}
 def relax_condition(self,h,item,hint=''):
  calls.append(('relax',item,hint));self.relaxed=(mode not in ('norelax','allnorelax'));return {'form':'NULL以外（キーの絞り込みを外す）','tried':[]}
 def apply_row_categories(self,h,spec):
  calls.append(('categories',spec['column'],spec['index'],tuple(spec['values']),spec['part'],spec['parts']))
  if mode=='norestrict':raise navigator_api.NavigatorApiError('行分割:カテゴリ',1,'試験: 絞れない')
  self.shown=[v for v in SERVER if v in spec['values']];return {'form':'まとめて外して担当ぶんを戻す','values':len(self.shown),'others':len(SERVER)-len(self.shown)}
 def _rows(self):
  keys=['LS4'] if (not self.relaxed and mode!='plain') else (self.shown if self.shown is not None else SERVER)
  if mode=='plain':keys=['LS4']
  return [['A',k,str(i)] for k in keys for i in range(2)]
 def execute(self,h):calls.append(('execute',));return len(self._rows()),0.01
 def dimensions(self,h):return len(self._rows()),3
 def save_csv(self,h,path,repeat_labels=False):
  calls.append(('save','repeat' if repeat_labels else 'nonrepeat'))
  head=['仕掛区分','BOX実績_設備名' if mode!='nocolumn' else '設備','ﾛｯﾄ番号']
  with open(path,'w',encoding='cp932',newline='') as f:
   f.write(','.join(head)+'\r\n');last=None
   for r in self._rows():
    cell=r[1] if (repeat_labels or r[1]!=last) else ''   # NAVI_NONREPEAT は上と同じ値を空にする
    last=r[1];f.write(','.join([r[0],cell,r[2]])+'\r\n')
  return 0.01
 def close_catalog(self):pass
 def close(self):pass
navigator_api.NavigatorApi=Fake
rne=work/'LOTACH.RNE';shutil.copy(Path(sys.argv[1])/'samples'/'rne'/'LOTACH.RNE',rne)
out=work/'out';out.mkdir()
cfg=app.load();cfg['settings']['reject_zero_rows']=True;app.save(cfg,quiet=True);cfg=app.load()
v={'enabled':True,'item':'BOX実績_設備名','values':ALL}
if mode=='folders':v.update(pattern='{値}_実績',folder=str(out/'{値}'))
if mode=='same':v.update(pattern='実績')
if mode=='partial':v['values']=['LS3','ZERO','KEN']
if mode=='onlykey':v['values']=['LS4']
if mode in ('parallel','parallelfail'):v['method']='parallel'
if mode=='defaultparallel':cfg['settings']['variant_method']='parallel'
if mode=='jobcombined':cfg['settings']['variant_method']='parallel';v['method']='combined'
if mode=='parallelfail':v['values']=['LS3','ZERO','KEN']
if mode.startswith('all'):v={'enabled':True,'item':'BOX実績_設備名','scope':'all','values':[],'method':'parallel'}
if mode=='allsame':v['pattern']='実績'
job={'id':'j1','name':'LOT実績','enabled':True,'source':'rne','rne':'LOTACH.RNE','rne_path':str(rne),'output_folder':str(out),
     'output_format':'csv','output_file':'LOTACH.csv','naming_mode':'fixed','type':'詳細データ','sheet':'Page1','table':'t',
     'schedules':[],'variants':v if mode!='plain' else {}}
cfg['jobs']=[job];app.save(cfg,quiet=True);job=app.load()['jobs'][0]
lines=[]
_upd=app.update_parallel_line
def spy(line,**kw):lines.append({'line':line,**{k:kw.get(k) for k in ('state','percent','detail','variants')}});return _upd(line,**kw)
app.update_parallel_line=spy
racers=[]
def fake_racers(job,cfg_,user,pw,server,work_,specs,timeout=1800,stop_when=None,on_tick=None,payload_of=None,limit=None):
 # ワーカーを起こす代わりに、同じプロセスで1つずつ動かす（中身は api_worker.py の既定の道と同じ呼び方）
 racers.append({'limit':limit,'timeout':timeout,'labels':[x['label'] for x in specs]});done=[]
 for k,spec in enumerate(specs):
  d=work_/f'part{k}';d.mkdir(parents=True,exist_ok=True);pl=json.loads(json.dumps(payload_of(spec,d),ensure_ascii=False))
  racers[-1].setdefault('jobs',[]).append({'values':pl['job']['_cond_override']['values'],'file':pl['job']['output_file'],'has_password':'password' in pl})
  st=[{'spec':x,'done':i<k,'started':i<=k,'result':done[i] if i<k else None,'status':{'state':'問い合わせ実行','percent':50} if i==k else {}} for i,x in enumerate(specs)]
  on_tick(1.0,st)
  r=app.process_api_parallel_job(pl['job'],pl['job_index'],pl['total_jobs'],pl['cfg'],'u','p',pl['server'],Path(pl['dde_work']),Path(pl['backup']))
  done.append(json.loads(json.dumps(r,ensure_ascii=False,default=str)))
 return done
app._spawn_racers=fake_racers
job['_split_budget']=3
seen={'export':0,'export_max':0,'sleep':0,'sleep_max':0,'share':0,'share_max':0,'order':[]}
if mode=='fourextra':job['extra_formats']=['txt']   # 同時出力つき（同時出力も、変換は鍵の中・公開は共有の鍵の中）
if mode in ('four','all','fourextra','all40'):
 # 値ごとの 変換 → 公開 を同時に進めたときの重なりを数える（変換・猶予の待ち・共有を触る鍵の中）
 import threading as th,time as tm,navi_publish
 lk=th.Lock()
 def count(k,d):
  with lk:seen[k]+=d;seen[k+'_max']=max(seen[k+'_max'],seen[k])
 _exp=app.export_data
 def export_data(*a,**k):
  count('export',1);seen['order'].append(a[2].get('_variant_value'));tm.sleep(0.05)
  try:return _exp(*a,**k)
  finally:count('export',-1)
 app.export_data=export_data
 class T:
  def __getattr__(self,n):return getattr(tm,n)
  def sleep(self,x):
   count('sleep',1)
   try:tm.sleep(x)
   finally:count('sleep',-1)
 navi_publish.time=T()
 class SG(app._ShareGate):
  def __enter__(self):super().__enter__();count('share',1)
  def __exit__(self,*a):count('share',-1);return super().__exit__(*a)
 app._ShareGate=SG
res=app.process_api_parallel_job(job,1,1,cfg,'u','p','srv',work/'dde',work/'backup')
files={}
for p in sorted(out.rglob('*.csv')):
 rows=list(__import__('csv').reader(open(p,encoding='utf-8-sig')))   # 公開する CSV は UTF-8（BOM 付き）
 files[str(p.relative_to(out)).replace('\\','/')]=sorted({r[1] for r in rows[1:]})
print(json.dumps({'ok':res.get('ok'),'error':res.get('error',''),'result':res.get('result',''),'files':files,'calls':calls,
                  'saved':job.get('variants'),'lines':lines,'racers':racers,'seen':seen,'txt':sorted(p.name for p in out.rglob('*.txt')),
                  'variants':[{k:x[k] for k in ('value','ok','rows')} for x in res.get('variant_results') or []]},ensure_ascii=False))
"""


PREVIEW=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
t=app.app.test_client();rne=sys.argv[1]+'/samples/rne/LOTACH.RNE'
base={'rne':'LOTACH.RNE','rne_path':rne,'name':'LOT実績','output_format':'xlsx','output_file':'LOTACH.xlsx','output_folder':sys.argv[2]}
out={}
out['empty']=t.post('/api/variants/preview',json=base).get_json()
out['four']=t.post('/api/variants/preview',json={**base,'variants':{'item':'BOX実績_設備名','values':['LS3','LS4'],'pattern':'{値}_{date:YYYYMM}'}}).get_json()
out['same']=t.post('/api/variants/preview',json={**base,'variants':{'item':'x','values':['a','b'],'pattern':'固定'}}).get_json()
# 出てきた値すべて: 数える前はファイルの見込みが空。数える（ワーカーは偽物）と控え、見込みに数えた値と行数が並ぶ
allv={'item':'BOX実績_設備名','scope':'all'}
base2={**base,'id':'j9','period':{'enabled':False}}
out['all_before']=t.post('/api/variants/preview',json={**base2,'variants':allv}).get_json()
seen=[]
def fake_worker(job,cfg,user,pw,server,want,timeout=180):
 seen.append({'want':want,'item':job['variants']['item'],'id':job.get('id')})
 return {'ok':True,'elapsed':1.0,'variant_count':{'values':[{'value':'LS4','rows':5},{'value':'PSW','rows':2}],'rows':7,'blank':0,
         'missing_column':False,'header':[],'encoding':'cp932','relax':'NULL以外','relax_unsure':False,'rne_keys':['LS4']}}
import navi_web;navi_web.run_inspect_worker=fake_worker
app.navi_login=navi_web.navi_login=lambda c:('u','p','s',None)
out['count']=t.post('/api/variants/count',json={**base2,'variants':allv}).get_json()
out['seen']=seen
out['all_after']=t.post('/api/variants/preview',json={**base2,'variants':allv}).get_json()
out['other_item']=t.post('/api/variants/preview',json={**base2,'variants':{**allv,'item':'別の項目'}}).get_json()
out['period_changed']=t.post('/api/variants/preview',json={**base2,'period':{'enabled':True,'unit':'day'},'variants':allv}).get_json()
out['listed_rows']=t.post('/api/variants/preview',json={**base2,'variants':{'item':'BOX実績_設備名','values':['PSW','KEN']}}).get_json()
out['all_noname']=t.post('/api/variants/preview',json={**base2,'variants':{**allv,'pattern':'実績'}}).get_json()
out['no_item']=t.post('/api/variants/count',json={**base2,'variants':{'scope':'all'}}).get_json()
print(json.dumps(out,ensure_ascii=False))
"""


# ワーカーの中で数える（process_catalog_inspect の variant_count）。API は偽物: 条件を外すと6設備、外さなければ LS4 だけ
COUNT=r"""
import json,shutil,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
work=Path(sys.argv[2]);mode=sys.argv[3];calls=[]
class Fake:
 relaxed=False
 def relax_condition(self,h,item,hint=''):calls.append(['relax',item,hint]);self.relaxed=mode!='norelax';return {'form':'NULL以外（キーの絞り込みを外す）'}
 def apply_row_categories(self,h,spec):calls.append(['categories'])
 def execute(self,h):calls.append(['execute']);return 0,0.01
 def save_csv(self,h,path,repeat_labels=False):
  calls.append(['save',repeat_labels]);keys=['LS3','LS4','DL2','KEN','PSW','ST2'] if self.relaxed else ['LS4']
  Path(path).write_bytes(('仕掛区分,BOX実績_設備名\r\n'+''.join(f'A,{k}\r\n'*(i+1) for i,k in enumerate(keys))).encode('cp932'));return 0.01
 def supports_column_split(self):return True
 def close_catalog(self):pass
 def close(self):pass
app.open_api_catalog=lambda c,rp:(Fake(),1)
rne=work/'LOTACH.RNE';shutil.copy(Path(sys.argv[1])/'samples'/'rne'/'LOTACH.RNE',rne)
job={'id':'c1','name':'LOT実績','rne':'LOTACH.RNE','rne_path':str(rne),'source':'rne','variants':{'item':'BOX実績_設備名','scope':'all'}}
out=app.process_catalog_inspect(job,app.load(),'u','p','s',['variant_count'])
left=sorted(x.name for x in app.LOCAL_RUNTIME.glob('variant_count_*.csv'))
print(json.dumps({'out':out,'calls':calls,'left':left},ensure_ascii=False))
"""


class CountTest(unittest.TestCase):
 def run_count(self,mode):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d)
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
            NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',COUNT,str(ROOT),str(d),mode],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   return json.loads(r.stdout.strip().splitlines()[-1])

 def test_counts_found_values(self):
  """本番の「出てきた値すべて」と同じ条件（RNE の LS4 を外し、表側は絞らない）で1回問い合わせ、値ごとの行数を数える。中間CSVは残さない。"""
  v=self.run_count('relax')
  self.assertTrue(v['out']['ok'],v['out'])
  c=v['out']['variant_count']
  self.assertEqual([(x['value'],x['rows']) for x in c['values']],[('LS3',1),('LS4',2),('DL2',3),('KEN',4),('PSW',5),('ST2',6)])
  self.assertEqual((c['rows'],c['relax_unsure'],c['rne_keys']),(21,False,['LS4']))
  self.assertEqual(v['calls'],[['relax','BOX実績_設備名','LS4'],['execute'],['save',True]])
  self.assertEqual(v['left'],[],'数えたら中間CSVは消す')

 def test_relax_unsure(self):
  c=self.run_count('norelax')['out']['variant_count']
  self.assertEqual(([x['value'] for x in c['values']],c['relax_unsure']),(['LS4'],True),'キーの値しか出なければ、外せていないかもしれないと返す')


class FlowTest(unittest.TestCase):
 def run_flow(self,mode):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);(d/'dde').mkdir();(d/'backup').mkdir()
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
            NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',FLOW,str(ROOT),str(d),mode],env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   return json.loads(r.stdout.strip().splitlines()[-1])

 def test_four_files_in_one_query(self):
  v=self.run_flow('four')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH_LS3.csv':['LS3'],'LOTACH_LS4.csv':['LS4'],'LOTACH_DL2.csv':['DL2'],'LOTACH_KEN.csv':['KEN']},
                   '値ごとに1ファイル、中身はその値の行だけ')
  self.assertEqual([c[0] for c in v['calls']],['open','relax','categories','execute','save'],
                   '問い合わせは1回だけ（条件欄の LS4 を外し、表側のカテゴリを指定の4値だけにしてから実行）')
  self.assertEqual(v['calls'][2],['categories','BOX実績_設備名',1,['LS3','LS4','DL2','KEN'],0,1],
                   '表側の2番目（0から数えて1）の管理ポイント。part=0 にして、指定に無い値を引き取らない')
  self.assertEqual(v['calls'][4],['save','repeat'],'表側の値を毎行書く（省くと、分けたとき行が何の設備か分からなくなる）')
  self.assertEqual([(x['value'],x['ok'],x['rows']) for x in v['variants']],[(x,True,2) for x in ('LS3','LS4','DL2','KEN')])
  self.assertIn('4/4ファイル',v['result'])
  self.assertEqual(v['saved']['values'],['LS3','LS4','DL2','KEN'],'設定に保存して読み戻せる')

 def test_progress_does_not_finish_early(self):
  """進捗: 途中の値で「完了」「失敗」を出さない（一覧の行がそこで終わったことになる）。「ファイル k/N 済」で進み、最後に1回だけ完了。
  値ごとの様子（variants）を一緒に渡す: 作成済みは ok、作っている値は run、残りは wait（一覧の行と進捗の窓の区切りバーが読む）。
  値ごとのファイルは同時に作るので、作っている値（run）は1つとは限らない。済んだ数は「ファイル k/N 済」の k と同じ。"""
  v=self.run_flow('four')
  states=[x['state'] for x in v['lines']]
  done=[i for i,s2 in enumerate(states) if s2 in ('完了','一部失敗','失敗')]
  self.assertEqual(done,[len(states)-1],'完了は最後の1回だけ')
  made=[x for x in v['lines'] if str(x['state']).startswith('ファイル ')]
  ks=[int(x['state'].split()[1].split('/')[0]) for x in made]
  self.assertEqual(ks,sorted(ks),'済んだ数は戻らない');self.assertEqual((ks[0],ks[-1]),(0,4))
  for k,x in zip(ks,made):
   got=[y['state'] for y in x['variants']]
   self.assertEqual(got.count('ok'),k,x);self.assertTrue(set(got)<={'ok','run','wait'},x)
  self.assertEqual([(y['value'],y['state'],y['rows']) for y in v['lines'][-1]['variants']],[(n,'ok',2) for n in ('LS3','LS4','DL2','KEN')],'最後は全部 ok と件数')
  self.assertFalse(any(x['variants'] for x in v['lines'] if x['state'] in ('開始','API接続','問い合わせ実行','受信・保存')),
                   'まとめて1回では、問い合わせ中は値ごとの進みが無いので区切りを出さない（ふつうのバー）')
  pct=[x['percent'] for x in v['lines'] if x['percent'] is not None]
  self.assertEqual(pct,sorted(pct),'進み具合は戻らない')

 def test_files_are_published_together(self):
  """受け取りは1回のまま、値ごとの公開を同時に進める（指定した値・出てきた値すべての両方）。
  変換は1本ずつ（ACCDB は Access を COM で動かすので、同時に起動しない）。目印のあとの猶予（3秒）は重ねて待つ。
  共有を触るところ（一覧・写す・差し替える）は、この対象に回せるライン数（_split_budget=3）までに絞る。"""
  for mode,n in (('four',4),('all',6),('fourextra',4),('all40',40)):
   v=self.run_flow(mode)
   self.assertTrue(v['ok'],v['error'])
   self.assertEqual([c[0] for c in v['calls']].count('execute'),1,'問い合わせは1回')
   self.assertEqual(v['seen']['export_max'],1,f'{mode}: 変換は1本ずつ')
   if mode!='fourextra':self.assertEqual(v['seen']['order'],[x['value'] for x in v['variants']],f'{mode}: 変換は値の並びの順（済む順を予想できる）')
   self.assertTrue(all(x['ok'] for x in v['variants']),f'{mode}: 値の数が同時の上限より多くても全部出る')
   self.assertGreaterEqual(v['seen']['sleep_max'],2,f'{mode}: 猶予の待ちは重なる')
   self.assertTrue(1<=v['seen']['share_max']<=3,f'{mode}: 共有を触るのはライン数まで（同時出力も） {v["seen"]}')
   self.assertTrue(any(str(x['detail']).startswith(('変換中','変換待ち','公開中')) for x in v['lines']),'一言に、何本が何をしているかの内訳')
   self.assertEqual(len(v['files']),n,v['files'])
   self.assertEqual(len(v['txt']),4 if mode=='fourextra' else 0,'同時出力も値ごとに出る')

 def test_parallel_one_value_per_worker(self):
  """値ごとに並列: 値ごとに1本のワーカー。各ワーカーは表側をその値1つに絞って問い合わせ、まとめて1回と同じ道で出す。
  同時に動かす数は、この対象に回せるライン数（_split_budget）まで。パスワードはワーカーへ書かない。"""
  v=self.run_flow('parallel')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH_LS3.csv':['LS3'],'LOTACH_LS4.csv':['LS4'],'LOTACH_DL2.csv':['DL2'],'LOTACH_KEN.csv':['KEN']},
                   '出るファイルはまとめて1回と同じ')
  r=v['racers'][0]
  self.assertEqual(r['limit'],3,'_split_budget=3 なら 4値でも同時は3本')
  self.assertEqual([x['values'] for x in r['jobs']],[['LS3'],['LS4'],['DL2'],['KEN']],'ワーカーごとに値1つ')
  self.assertEqual([x['file'] for x in r['jobs']],['LOTACH_LS3.csv','LOTACH_LS4.csv','LOTACH_DL2.csv','LOTACH_KEN.csv'])
  self.assertFalse(any(x['has_password'] for x in r['jobs']),'パスワードは payload.json に書かない')
  cats=[c for c in v['calls'] if c[0]=='categories']
  self.assertEqual([c[3] for c in cats],[['LS3'],['LS4'],['DL2'],['KEN']],'表側のカテゴリをその値だけに絞る')
  self.assertEqual([c[0] for c in v['calls']].count('execute'),4,'値の数だけ問い合わせる')
  self.assertEqual([(x['value'],x['ok'],x['rows']) for x in v['variants']],[(x,True,2) for x in ('LS3','LS4','DL2','KEN')])
  self.assertIn('4/4ファイル',v['result'])

 def test_parallel_progress(self):
  """値ごとに並列の進み具合: 親のラインに、値ごとの済・作成中・待ちと、全体の割合（済=100・作成中はワーカーの割合・待ち=0 の平均）。"""
  v=self.run_flow('parallel')
  mine=[x for x in v['lines'] if x['line']!=v['racers'][0]['labels'][0] and x['variants'] and str(x['state']).startswith('ファイル ')]
  firsts=[x for x in mine if x['detail'] and '本同時' in x['detail']]
  self.assertEqual([y['state'] for y in firsts[1]['variants']],['ok','run','wait','wait'])
  self.assertEqual(firsts[1]['percent'],round((100+50)/4,1))
  self.assertIn('LS4 問い合わせ実行',firsts[1]['detail'])
  last=v['lines'][-1]
  self.assertEqual(last['state'],'完了')
  self.assertEqual([y['state'] for y in last['variants']],['ok']*4)

 def test_parallel_partial_failure(self):
  """値ごとに並列で1つの値が失敗しても、残りは出す。最後は一部失敗で、失敗した値は ng。"""
  v=self.run_flow('parallelfail')
  self.assertFalse(v['ok'])
  self.assertEqual(sorted(v['files']),['LOTACH_KEN.csv','LOTACH_LS3.csv'])
  self.assertEqual([(x['value'],x['ok']) for x in v['variants']],[('LS3',True),('ZERO',False),('KEN',True)])
  self.assertEqual(v['lines'][-1]['state'],'一部失敗')
  self.assertEqual([y['state'] for y in v['lines'][-1]['variants']],['ok','ng','ok'])

 def test_default_method_switch(self):
  """共通設定の既定を「値ごとに並列」にすると、既定に従う対象は並列で動き、まとめて1回を選んだ対象はそのまま。"""
  self.assertEqual(len(self.run_flow('defaultparallel')['racers']),1)
  v=self.run_flow('jobcombined')
  self.assertEqual(v['racers'],[])
  self.assertEqual([c[0] for c in v['calls']].count('execute'),1)

 def test_name_and_folder_patterns(self):
  v=self.run_flow('folders')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(sorted(v['files']),['DL2/DL2_実績.csv','KEN/KEN_実績.csv','LS3/LS3_実績.csv','LS4/LS4_実績.csv'],
                   'ファイル名と置き場の両方に {値} を使える（置き場が無ければ作る）')

 def test_cannot_restrict_on_server_still_correct(self):
  v=self.run_flow('norestrict')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH_LS3.csv':['LS3'],'LOTACH_LS4.csv':['LS4'],'LOTACH_DL2.csv':['DL2'],'LOTACH_KEN.csv':['KEN']},
                   'サーバー側で絞れず全部の設備が返っても、手元で振り分けるのでほかの設備（PSW・ST2）は混ざらない')
  self.assertIn('サーバー側では絞れず',v['result'])

 def test_relax_not_effective_is_not_published(self):
  v=self.run_flow('norelax')
  self.assertFalse(v['ok'])
  self.assertEqual(v['files'],{},'LS4 しか返らないのに LS3 などを0件のファイルにしない')
  self.assertIn('RNE の条件（BOX実績_設備名 = LS4）を外せず',v['error'])

 def test_no_column_is_refused(self):
  v=self.run_flow('nocolumn')
  self.assertFalse(v['ok']);self.assertEqual(v['files'],{})
  self.assertIn('列が無いため',v['error'])

 def test_all_found_values(self):
  """出てきた値すべて（2.5.0）: RNE の条件（LS4）を外し、表側は絞らず1回だけ問い合わせ、出てきた6設備を6ファイルにする。
  値は先に分からないので、並列を選んでいてもまとめて1回で動く。"""
  v=self.run_flow('all')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{f'LOTACH_{k}.csv':[k] for k in ('LS3','LS4','DL2','KEN','PSW','ST2')},'出てきた値ごとに1ファイル、中身はその値の行だけ')
  self.assertEqual([c[0] for c in v['calls']],['open','relax','execute','save'],'表側のカテゴリは絞らない（全部の値が欲しい）')
  self.assertEqual(v['calls'][1],['relax','BOX実績_設備名','LS4'],'2つ目の形に渡すキーは RNE のいまのキー')
  self.assertEqual(v['racers'],[],'値ごとに並列にはしない')
  self.assertIn('6/6ファイル',v['result'])
  self.assertEqual(v['saved']['scope'],'all','設定に保存して読み戻せる')
  last=v['lines'][-1]
  self.assertEqual((last['state'],[y['value'] for y in last['variants']]),('完了',['LS3','LS4','DL2','KEN','PSW','ST2']))
  self.assertTrue(any('出てきた値すべて' in str(x['detail']) for x in v['lines']),'問い合わせ中の一言')

 def test_all_found_relax_unsure(self):
  """条件を外せず LS4 しか返らなかったら、LS4 の1ファイルを出し、外せていないかもしれないと知らせる（0件のファイルは作らない）。"""
  v=self.run_flow('allnorelax')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH_LS4.csv':['LS4']})
  self.assertIn('条件を外せていないかもしれません',v['result'])

 def test_all_found_same_name_is_refused_before_query(self):
  v=self.run_flow('allsame')
  self.assertFalse(v['ok']);self.assertEqual(v['files'],{})
  self.assertIn('{値} がありません',v['error'])
  self.assertEqual(v['calls'],[],'問い合わせる前に断る')

 def test_only_rne_key_needs_no_relax(self):
  v=self.run_flow('onlykey')
  self.assertTrue(v['ok'],v['error'])
  self.assertNotIn('relax',[c[0] for c in v['calls']],'RNE のキー（LS4）だけなら条件欄は外さない')
  self.assertEqual(v['files'],{'LOTACH_LS4.csv':['LS4']})

 def test_partial_failure_keeps_the_rest(self):
  v=self.run_flow('partial')
  self.assertFalse(v['ok'])
  self.assertEqual(sorted(v['files']),['LOTACH_KEN.csv','LOTACH_LS3.csv'],'1つの値が失敗（0件）しても、残りの値は出す')
  self.assertIn('失敗: ZERO',v['error'])

 def test_same_name_is_refused(self):
  v=self.run_flow('same')
  self.assertFalse(v['ok']);self.assertEqual(v['files'],{})
  self.assertIn('同じファイル名',v['error'])

 def test_plain_job_is_unchanged(self):
  v=self.run_flow('plain')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH.csv':['','LS4']},'分けない対象は、これまでどおり1ファイル（表側は上と同じ値を省く）')
  self.assertFalse([c for c in v['calls'] if c[0] in ('relax','categories')],'条件は変えない')
  self.assertIn(['save','nonrepeat'],v['calls'])

 def test_preview_route(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d)
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
            NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',PREVIEW,str(ROOT),str(d/'out')],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual([(x['name'],x['keys']) for x in v['empty']['conditions']],[('BOX実績_設備名',['LS4'])],'RNE の条件欄の項目といまのキーを返す')
  self.assertEqual(v['empty']['files'],[])
  import datetime
  ym=datetime.date.today().strftime('%Y%m')
  self.assertEqual([x['file'] for x in v['four']['files']],[f'LS3_{ym}.xlsx',f'LS4_{ym}.xlsx'],'値と日付の変数を展開し、形式の拡張子を付ける')
  self.assertTrue(v['four']['files'][0]['path'].endswith(f'LS3_{ym}.xlsx'))
  self.assertFalse(v['same']['ok']);self.assertIn('同じファイル名',v['same']['error'])
  # 数える（2.5.0）
  self.assertEqual((v['all_before']['files'],v['all_before']['counted']),([],None),'数える前は見込みが無い')
  self.assertEqual([(x['value'],x['file']) for x in v['all_before']['sample']],[('LS4','LOTACH_LS4.xlsx')],'数える前は、RNE のいまの値を例にした名前の見本')
  self.assertEqual(v['all_after']['sample'],[],'数えたら見本は出さない')
  self.assertTrue(v['count']['ok'],v['count'])
  self.assertEqual(v['seen'],[{'want':['variant_count'],'item':'BOX実績_設備名','id':'j9'}],'ワーカーで数える')
  self.assertEqual([(x['value'],x['rows']) for x in v['count']['counted']['values']],[('LS4',5),('PSW',2)])
  a=v['all_after']
  self.assertEqual(a['counted']['state'],'fresh')
  self.assertEqual([(x['value'],x['file'],x['rows']) for x in a['files']],[('LS4','LOTACH_LS4.xlsx',5),('PSW','LOTACH_PSW.xlsx',2)],
                   '出てきた値すべては、数えた値でファイルの見込みを並べる')
  self.assertIsNone(v['other_item']['counted'],'項目を変えたら、前の数は使わない')
  self.assertEqual(v['period_changed']['counted']['state'],'stale','期間指定を変えたら、数え直しを促す')
  self.assertEqual([(x['value'],x['rows']) for x in v['listed_rows']['files']],[('PSW',2),('KEN',None)],'指定した値だけでも、数えた行数を添える')
  self.assertFalse(v['all_noname']['ok']);self.assertIn('{値} がありません',v['all_noname']['error'])
  self.assertFalse(v['no_item']['ok'])



# _spawn_racers の同時に動かす数（limit）と、渡す中身の差し替え（payload_of）。プロセスは偽物
RACERS=r"""
import json,os,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
work=Path(sys.argv[2]);running=[];peak=[0];started=[]
class P:
 def __init__(self,cmd,cwd=None,env=None,creationflags=0):
  self.env=env;self.left=3;self.pid=0;running.append(self);started.append(json.loads(Path(cmd[-1]).read_text(encoding='utf-8')))
  peak[0]=max(peak[0],len(running))
 def poll(self):
  self.left-=1
  if self.left>0:return None
  if self in running:
   running.remove(self);Path(self.env['NAVI_WORKER_RESULT']).write_text(json.dumps({'ok':True,'part':self.env['NAVI_WORKER_LINE']}),encoding='utf-8')
  return 0
app.subprocess.Popen=P;app.time.sleep=lambda s:None
specs=[{'index':i,'label':f'v{i}'} for i in range(5)];ticks=[]
r=app._spawn_racers({},{},'u','',None,work,specs,60,payload_of=lambda spec,d:{'job':{'n':spec['index']}},limit=2,
                    on_tick=lambda el,st:ticks.append(sum(1 for x in st if x['started'] and not x['done'])))
r2=app._spawn_racers({'name':'x'},{},'u','',None,work/'b',[{'index':0,'label':'a','out_csv':'a.csv','drop':[]}],60)
print(json.dumps({'peak':peak[0],'order':[x['job']['n'] for x in started[:5]],'ok':[x['ok'] for x in r],'labels':[x['part'] for x in r],
                  'ticks_max':max(ticks),'default_payload':sorted(started[5]),'split_part':started[5].get('split_part',{}).get('out_csv')},ensure_ascii=False))
"""


class RacersTest(unittest.TestCase):
 def test_limit_and_payload(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',RACERS,str(ROOT),d],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['peak'],2,'同時に動くのは limit=2 本まで')
  self.assertEqual(v['ticks_max'],2)
  self.assertEqual(v['order'],[0,1,2,3,4],'終わった数だけ、並べた順に次を起こす')
  self.assertEqual(v['ok'],[True]*5);self.assertEqual(v['labels'],['v0','v1','v2','v3','v4'],'結果は並べた順')
  self.assertEqual(v['default_payload'],['cfg','job','server','split_part','user'],'payload_of を省けば、これまでどおり分割の1片（パスワードは書かない）')
  self.assertEqual(v['split_part'],'a.csv')



# 値ごとの変換の鍵（_TurnGate）: 値の並びの順に1本ずつ。変換に入らずに済んだ値が番を返せば、後ろの値は止まらない
TURN=r"""
import json,sys,threading,time
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
g=app._variant_convert_gate();order=[];inside=[0];peak=[0];lk=threading.Lock()
def work(k,skip=False):
 if skip:time.sleep(0.05);g.done(k);return   # 前回と同じなどで、変換に入らずに済んだ値
 t=g.turn(k)
 for _ in range(2):   # 2回目は同時出力の変換（番は待たず、1本ずつにするだけ）
  with t:
   with lk:inside[0]+=1;peak[0]=max(peak[0],inside[0]);order.append(k)
   time.sleep(0.01)
   with lk:inside[0]-=1
 g.done(k)   # one_file は済んだあとにも番を返す（2回返しても害は無い）
ts=[threading.Thread(target=work,args=(k,k==1)) for k in (4,3,2,1,0)]   # 起こす順は逆、値 1 は変換に入らない
for t in ts:t.start()
for t in ts:t.join(10)
print(json.dumps({'alive':any(t.is_alive() for t in ts),'first':[k for i,k in enumerate(order) if k not in order[:i]],'peak':peak[0]}))
"""


class TurnGateTest(unittest.TestCase):
 def test_order_and_skip(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',TURN,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
  self.assertEqual(r.returncode,0,r.stderr[-3000:])
  v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertFalse(v['alive'],'変換に入らない値（1）があっても止まらない')
  self.assertEqual(v['first'],[0,2,3,4],'はじめの変換は値の並びの順（起こした順によらない）')
  self.assertEqual(v['peak'],1,'同時に変換するのは1本だけ（同時出力の変換も）')


# データビュワー（2.1.2）: 値ごとに分けて出す対象は、値ごとのファイルを選んで開ける
VIEWER=r"""
import json,sqlite3,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
work=Path(sys.argv[2]);out=work/'out';out.mkdir()
def db(name,rows):
 with sqlite3.connect(out/name) as c:
  c.execute('CREATE TABLE t(設備 TEXT, n INTEGER)');c.executemany('INSERT INTO t VALUES(?,?)',rows)
db('実績_LS4.sqlite3',[('LS4',1),('LS4',2)]);db('実績_LS3_前回.sqlite3',[('LS3',1)])
cfg=app.load()
job={'id':'v1','name':'設備単位実績','enabled':True,'source':'rne','rne':'LOTACH.RNE','rne_path':'x.RNE','output_folder':str(out),
     'output_format':'sqlite3','output_file':'実績.sqlite3','naming_mode':'fixed','type':'詳細データ','sheet':'Page1','table':'t','schedules':[],
     'variants':{'enabled':True,'item':'BOX実績_設備名','values':['LS4','LS3','DL2']}}
cfg['jobs']=[job];app.save(cfg,quiet=True)
# 前回の実行: LS3 は前回の名前（日付つきの型など）で作ってある。記録の道を先に見る
app.record_job_run('v1','設備単位実績','success','manual',metrics={'variant_results':[{'value':'LS3','ok':True,'target':str(out/'実績_LS3_前回.sqlite3')}]})
t=app.app.test_client()
res={'jobs':t.get('/api/data-viewer/jobs').get_json()['items'],
     'ls4':t.get('/api/data-viewer/v1?value=LS4').get_json(),'ls3':t.get('/api/data-viewer/v1?value=LS3').get_json(),
     'dl2':t.get('/api/data-viewer/v1?value=DL2').get_json(),'first':t.get('/api/data-viewer/v1').get_json(),
     'bad':t.get('/api/data-viewer/v1?value=XXX').status_code}
# 出てきた値すべて: 前回の実行で作った値を並べる。まだ実行していなければ空で、開くと断る
job2={**job,'id':'v2','variants':{'enabled':True,'item':'BOX実績_設備名','scope':'all','values':[]}}
job3={**job,'id':'v3','variants':{'enabled':True,'item':'BOX実績_設備名','scope':'all','values':[]}}
cfg=app.load();cfg['jobs']=[job,job2,job3];app.save(cfg,quiet=True)
app.record_job_run('v2','設備単位実績','success','manual',metrics={'variant_results':[{'value':'LS4','ok':True,'target':str(out/'実績_LS4.sqlite3')},
                                                                                 {'value':'PSW','ok':True,'target':str(out/'実績_PSW.sqlite3')}]})
items={x['id']:x for x in t.get('/api/data-viewer/jobs').get_json()['items']}
res['all']=items['v2'];res['all_none']=items['v3']
r3=t.get('/api/data-viewer/v3');res['all_open']=[r3.status_code,r3.get_json()]
print(json.dumps(res,ensure_ascii=False,default=str))
"""


class ViewerTest(unittest.TestCase):
 def test_files_per_value(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',VIEWER,str(ROOT),d],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  job=v['jobs'][0]
  self.assertEqual([(x['value'],x['file'],x['exists']) for x in job['files']],
                   [('LS4','実績_LS4.sqlite3',True),('LS3','実績_LS3_前回.sqlite3',True),('DL2','実績_DL2.sqlite3',False)],
                   '値ごとに1つずつ。前回作ったファイルの道を先に見る。まだ無い値は exists=False')
  self.assertTrue(job['exists'],'1つでもあれば選べる')
  self.assertEqual((v['ls4']['value'],v['ls4']['total_rows'],v['ls4']['rows']),('LS4',2,[['LS4','1'],['LS4','2']]),'その値のファイルの中身（ビュワーは文字で渡す）')
  self.assertEqual((v['ls3']['value'],v['ls3']['total_rows']),('LS3',1))
  self.assertFalse(v['dl2']['ok']);self.assertIn('見つかりません',v['dl2']['error'])
  self.assertEqual(v['first']['value'],'LS4','値を省けば、ある最初の値')
  self.assertEqual([(x['value'],x['exists']) for x in v['all']['files']],[('LS4',True),('PSW',False)],'出てきた値すべては、前回作った値を並べる')
  self.assertEqual(v['all_none']['files'],[],'まだ実行していなければ空')
  self.assertEqual(v['all_open'][0],404);self.assertIn('まだ値ごとのファイルを作っていません',v['all_open'][1]['error'])
  self.assertEqual(v['bad'],404,'対象に無い値は断る')

if __name__=='__main__':
 unittest.main()
