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
  self.assertEqual(v,{'enabled':True,'item':'BOX実績_設備名','values':['LS3','LS4','DL2'],'pattern':'{値}_実績','folder':'','method':'default'},
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
   p.write_text('仕掛区分,BOX実績_設備名,ﾛｯﾄ番号\r\nA,LS4,1\r\nA,,2\r\nB,LS3,3\r\nB,PSW,4\r\nC,LS3,5\r\n',encoding='cp932')
   sp=V.split_csv(p,'BOX実績_設備名',['LS3','LS4','KEN'],Path(d)/'parts')
   self.assertFalse(sp['missing_column']);self.assertEqual(sp['rows'],5)
   self.assertEqual(sp['found'],['LS4','LS3','PSW'],'出てきた値（頼んでいない PSW も数える）')
   self.assertEqual({k:v['rows'] for k,v in sp['parts'].items()},{'LS3':2,'LS4':2,'KEN':0},'空のマスは上の行の値を引き継ぐ')
   with open(sp['parts']['LS4']['path'],encoding='cp932',newline='') as f:rows=list(csv.reader(f))
   self.assertEqual(rows,[['仕掛区分','BOX実績_設備名','ﾛｯﾄ番号'],['A','LS4','1'],['A','LS4','2']],'同じ見出し・その値の行だけ・空のマスは値で埋める')
   self.assertTrue(V.split_csv(p,'無い列',['LS3'],Path(d)/'p2')['missing_column'])

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
  calls.append(('relax',item));self.relaxed=(mode!='norelax');return {'form':'NULL以外（キーの絞り込みを外す）','tried':[]}
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
res=app.process_api_parallel_job(job,1,1,cfg,'u','p','srv',work/'dde',work/'backup')
files={}
for p in sorted(out.rglob('*.csv')):
 rows=list(__import__('csv').reader(open(p,encoding='utf-8-sig')))   # 公開する CSV は UTF-8（BOM 付き）
 files[str(p.relative_to(out)).replace('\\','/')]=sorted({r[1] for r in rows[1:]})
print(json.dumps({'ok':res.get('ok'),'error':res.get('error',''),'result':res.get('result',''),'files':files,'calls':calls,
                  'saved':job.get('variants'),'lines':lines,'racers':racers,
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
print(json.dumps(out,ensure_ascii=False))
"""


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
  値ごとの様子（variants）を一緒に渡す: 作成済みは ok、作っている値は run、残りは wait（一覧の行と進捗の窓の区切りバーが読む）。"""
  v=self.run_flow('four')
  states=[x['state'] for x in v['lines']]
  done=[i for i,s2 in enumerate(states) if s2 in ('完了','一部失敗','失敗')]
  self.assertEqual(done,[len(states)-1],'完了は最後の1回だけ')
  made=[x for x in v['lines'] if str(x['state']).startswith('ファイル ')]
  self.assertEqual(sorted({x['state'] for x in made}),[f'ファイル {k}/4 済' for k in range(0,4)])
  for x in made:
   k=int(x['state'].split()[1].split('/')[0]);got=[y['state'] for y in x['variants']]
   self.assertEqual(got,['ok']*k+['run']+['wait']*(3-k),x)
  self.assertEqual([(y['value'],y['state'],y['rows']) for y in v['lines'][-1]['variants']],[(n,'ok',2) for n in ('LS3','LS4','DL2','KEN')],'最後は全部 ok と件数')
  self.assertFalse(any(x['variants'] for x in v['lines'] if x['state'] in ('開始','API接続','問い合わせ実行','受信・保存')),
                   'まとめて1回では、問い合わせ中は値ごとの進みが無いので区切りを出さない（ふつうのバー）')
  pct=[x['percent'] for x in v['lines'] if x['percent'] is not None]
  self.assertEqual(pct,sorted(pct),'進み具合は戻らない')

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

if __name__=='__main__':
 unittest.main()
