"""条件の値ごとに分けて出す（2.1.0。lib/navi_variants.py と app.process_api_parallel_job）。

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
  self.assertEqual(v,{'enabled':True,'item':'BOX実績_設備名','values':['LS3','LS4','DL2'],'pattern':'{値}_実績','folder':''},
                   '前後の空白を落とし、重ねず、空は捨てる')
  self.assertEqual(V.normalize(None)['values'],[])
  self.assertEqual(len(V.normalize({'values':[str(i) for i in range(200)]})['values']),V.MAX_VALUES)

 def test_active(self):
  self.assertFalse(V.active({'variants':{'enabled':True,'item':'x','values':[]}}),'値が無ければ分けない')
  self.assertFalse(V.active({'variants':{'enabled':False,'item':'x','values':['a']}}),'切ってあれば分けない')
  self.assertTrue(V.active({'variants':{'enabled':True,'item':'x','values':['a']}}))

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

 def test_check_rows(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.csv'
   p.write_text('仕掛区分,BOX実績_設備名,ﾛｯﾄ番号\nA,LS4,1\nA,,2\nB,LS4,3\n',encoding='cp932')
   self.assertEqual(V.check_rows(p,'BOX実績_設備名','LS4'),{'checked':True,'rows':3,'other':[]},'空のマスは「上と同じ」を省いた書き方なので数えない')
   p.write_text('仕掛区分,BOX実績_設備名\nA,LS4\nA,LS3\nB,DL2\nC,LS3\n',encoding='cp932')
   self.assertEqual(V.check_rows(p,'BOX実績_設備名','LS4')['other'],['LS3','DL2'])
   self.assertEqual(V.check_rows(p,'無い列','LS4'),{'checked':False,'rows':4,'other':[]},'列が無ければ確かめられない（止めない）')

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


class KeyConditionTest(unittest.TestCase):
 """NaviChangeConditionDI へ渡す形。項目は条件欄から引き、NAVI_MATCH＋完全一致でキーを1つにする。"""
 def setUp(self):
  import navigator_api as N
  self.N=N;self._ansi=N._ansi;N._ansi=lambda v:str(v).encode('cp932')   # mbcs は Windows だけ
 def tearDown(self):self.N._ansi=self._ansi

 def make(self,fail_first=False,handle=7):
  N=self.N;calls=[]
  class Dll:
   NaviGetDataItem=True
   def NaviChangeConditionDI(self,h,rc,cond,key,search,nonmatch,rng,lc,lv,rcck,rv,res):
    calls.append({'h':h,'cond':cond,'key':key.decode('cp932'),'search':search,'nonmatch':nonmatch})
    rc._obj.value=1 if (fail_first and len(calls)==1) else 0
  api=object.__new__(N.NavigatorApi);api.dll=Dll()
  api.error_message=lambda:(0,'');api.error_code=lambda:0
  located=[]
  def get_data_item(h,label,locate=N.NAVI_DATA,order=0):
   located.append((label,locate));return handle
  api.get_data_item=get_data_item
  return api,calls,located

 def test_match_complete(self):
  api,calls,located=self.make()
  got=api.apply_key_condition(1,'BOX実績_設備名','LS3')
  self.assertEqual(located,[('BOX実績_設備名',self.N.NAVI_COND)],'条件欄から引く（データ欄に付けても絞られない）')
  self.assertEqual(calls,[{'h':7,'cond':self.N.NAVI_MATCH,'key':'LS3','search':self.N.NAVI_COMPLETE,'nonmatch':0}])
  self.assertEqual(got['form'],'一致・完全一致')

 def test_second_form_and_missing_item(self):
  api,calls,_=self.make(fail_first=True)
  self.assertEqual(api.apply_key_condition(1,'x','LS3')['form'],'一致・完全一致(該当なしのカテゴリも読む)')
  self.assertEqual([c['nonmatch'] for c in calls],[0,self.N.NAVI_NONMATCH])
  api,_,_=self.make(handle=0)
  with self.assertRaisesRegex(self.N.NavigatorApiError,'条件欄に「x」がありません'):api.apply_key_condition(1,'x','LS3')


# 本物の app で、値ごとの実行を最後（公開）まで通す。API は偽物
FLOW=r"""
import json,shutil,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navigator_api
work=Path(sys.argv[2]);mode=sys.argv[3]
ALL=['LS3','LS4','DL2','KEN']
calls=[]
class Fake:
 dll_path='fake.dll'
 def __init__(self,*a,**k):self.key=None
 def open_session(self,*a):return 0.01
 def connect_data_source(self,p):return 0.01
 def open_catalog(self,p):calls.append(('open',Path(p).name));return 1,0.01
 def apply_period(self,*a):return {}
 def apply_key_condition(self,h,item,value):
  if value=='BAD':raise navigator_api.NavigatorApiError('値ごとの出力:条件の設定',1,'試験: 通らない値')
  calls.append(('key',item,value));self.key=value;return {'form':'一致・完全一致','tried':[]}
 def _rows(self):
  keys=ALL if (mode=='ineffective' or self.key is None) else [self.key]
  return [['A',k,str(i)] for k in keys for i in range(2)]
 def execute(self,h):return len(self._rows()),0.01
 def dimensions(self,h):return len(self._rows()),3
 def save_csv(self,h,path,repeat_labels=False):
  head=['仕掛区分','BOX実績_設備名' if mode!='nocolumn' else '設備','ﾛｯﾄ番号']
  with open(path,'w',encoding='cp932',newline='') as f:
   f.write(','.join(head)+'\r\n')
   for r in self._rows():f.write(','.join(r)+'\r\n')
  return 0.01
 def close_catalog(self):pass
 def close(self):pass
navigator_api.NavigatorApi=Fake
rne=work/'LOTACH.RNE';shutil.copy(Path(sys.argv[1])/'samples'/'rne'/'LOTACH.RNE',rne)
out=work/'out';out.mkdir()
cfg=app.load()
v={'enabled':True,'item':'BOX実績_設備名','values':ALL}
if mode=='folders':v.update(pattern='{値}_実績',folder=str(out/'{値}'))
if mode=='same':v.update(pattern='実績')
if mode=='partial':v['values']=['LS3','BAD','KEN']
job={'id':'j1','name':'LOT実績','enabled':True,'source':'rne','rne':'LOTACH.RNE','rne_path':str(rne),'output_folder':str(out),
     'output_format':'csv','output_file':'LOTACH.csv','naming_mode':'fixed','type':'詳細データ','sheet':'Page1','table':'t',
     'schedules':[],'variants':v if mode!='plain' else {}}
cfg['jobs']=[job];app.save(cfg,quiet=True);job=app.load()['jobs'][0]
res=app.process_api_parallel_job(job,1,1,cfg,'u','p','srv',work/'dde',work/'backup')
files={}
for p in sorted(out.rglob('*.csv')):
 rows=list(__import__('csv').reader(open(p,encoding='utf-8-sig')))   # 公開する CSV は UTF-8（BOM 付き）
 files[str(p.relative_to(out)).replace('\\','/')]=sorted({r[1] for r in rows[1:]})
print(json.dumps({'ok':res.get('ok'),'error':res.get('error',''),'result':res.get('result',''),'files':files,'calls':calls,
                  'saved':job.get('variants'),
                  'variants':[{k:x[k] for k in ('value','ok','rows','checked')} for x in res.get('variant_results') or []]},ensure_ascii=False))
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

 def test_four_files(self):
  v=self.run_flow('four')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH_LS3.csv':['LS3'],'LOTACH_LS4.csv':['LS4'],'LOTACH_DL2.csv':['DL2'],'LOTACH_KEN.csv':['KEN']},
                   '値ごとに1ファイル、中身はその値の行だけ')
  self.assertEqual([c for c in v['calls'] if c[0]=='key'],[['key','BOX実績_設備名',x] for x in ('LS3','LS4','DL2','KEN')])
  self.assertEqual(sum(1 for c in v['calls'] if c[0]=='open'),4,'値ごとにカタログを開き直す（前の値の条件を持ち越さない）')
  self.assertEqual([(x['value'],x['ok'],x['rows'],x['checked']) for x in v['variants']],
                   [(x,True,2,True) for x in ('LS3','LS4','DL2','KEN')])
  self.assertIn('4/4ファイル',v['result'])
  self.assertEqual(v['saved']['values'],['LS3','LS4','DL2','KEN'],'設定に保存して読み戻せる')

 def test_name_and_folder_patterns(self):
  v=self.run_flow('folders')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(sorted(v['files']),['DL2/DL2_実績.csv','KEN/KEN_実績.csv','LS3/LS3_実績.csv','LS4/LS4_実績.csv'],
                   'ファイル名と置き場の両方に {値} を使える（置き場が無ければ作る）')

 def test_ineffective_condition_is_not_published(self):
  v=self.run_flow('ineffective')
  self.assertFalse(v['ok'])
  self.assertEqual(v['files'],{},'絞れていない結果は、値ごとの名前で公開しない')
  self.assertIn('条件が効いていません',v['error'])

 def test_unverifiable_is_published_but_marked(self):
  v=self.run_flow('nocolumn')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual([x['checked'] for x in v['variants']],[False]*4,'出力に同じ名前の列が無ければ、確かめられなかったと残す')

 def test_partial_failure_keeps_the_rest(self):
  v=self.run_flow('partial')
  self.assertFalse(v['ok'])
  self.assertEqual(sorted(v['files']),['LOTACH_KEN.csv','LOTACH_LS3.csv'],'1つの値が失敗しても、残りの値は出す')
  self.assertIn('失敗: BAD',v['error'])

 def test_same_name_is_refused(self):
  v=self.run_flow('same')
  self.assertFalse(v['ok']);self.assertEqual(v['files'],{})
  self.assertIn('同じファイル名',v['error'])

 def test_plain_job_is_unchanged(self):
  v=self.run_flow('plain')
  self.assertTrue(v['ok'],v['error'])
  self.assertEqual(v['files'],{'LOTACH.csv':['DL2','KEN','LS3','LS4']},'分けない対象は、これまでどおり1ファイル')
  self.assertFalse([c for c in v['calls'] if c[0]=='key'],'条件は差し替えない')

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


if __name__=='__main__':
 unittest.main()
