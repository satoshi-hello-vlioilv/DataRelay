"""置き場の既定の設定（lib/navi_defaults.py）と、それを各PCの手元へ当てる流れ（navi_web）を確かめる（2.0.0）。

見るところ:
  - 置き場の defaults\\ を作る・読む・項目を外す・消す（対象を外せば、その予定と使われなくなった RNE も外れる）
  - 手元との差（足りない・違う・同じ・手元だけ）と、3つの当て方
      上書き   … 既定にある物を既定の中身にする（手元だけの物は残す）
      差分追加 … 足りない物だけ足す（同じ名前の手元の物・手元の対象の予定は触らない）
      今のまま … 何も変えない（この既定はもう聞かない）
  - 新しく写した手元が空なら、聞かずに既定を入れる。当てる前に控えを取る
  - 共有の設定を使ってきた写しを手元へ移す支度（開き直す前に、手元の正本・RNE・印を作り、作業用の写しを退ける）
見本は samples\\defaults（2.0.0 で配る版から外した、雛形の対象6件と RNE 4つ）。

実行: python -m unittest tests.test_defaults -v
"""
import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SAMPLE=ROOT/'samples'
sys.path.insert(0,str(ROOT/'lib'))
import navi_defaults as D
import navi_bundle as B


def job(name,**kw):
 j={'name':name,'source':'rne','rne':f'{name}.RNE','rne_path':f'.\\rne\\{name}.RNE','output_file':f'{name}.csv','output_format':'csv','enabled':True}
 j.update(kw);return j


class FolderTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.t=Path(self.tmp.name);self.base=self.t/'share';self.base.mkdir()
  (self.t/'A.RNE').write_text('a');(self.t/'B.RNE').write_text('b')

 def put(self,jobs,schedules=None,rne=None,settings=None):
  payloads={'jobs':B.jobs_export(jobs),'schedules':B.schedules_export([dict(j,schedules=schedules.get(j['name'],[])) for j in jobs] if schedules else [])}
  return D.write(self.base,payloads,settings,rne if rne is not None else {'A.RNE':self.t/'A.RNE','B.RNE':self.t/'B.RNE'},uid='me',pc='PC1')

 def test_write_read_summary(self):
  self.assertIsNone(D.read(self.base),'無ければ None')
  man=self.put([job('A'),job('B')],{'A':[{'type':'daily','time':'06:00','enabled':True}]},settings={'top':{'text_folder':'\\\\srv\\t'},'settings':{'backup_generations':3}})
  d=D.read(self.base)
  self.assertEqual(d['manifest']['id'],man['id'])
  s=D.summary(d)
  self.assertEqual(s['counts'],{'jobs':2,'schedules':1,'layouts':0,'recipes':0,'rne':2})
  self.assertEqual((s['parts']['jobs'],s['parts']['rne'],s['settings']),(['A','B'],['A.RNE','B.RNE'],True))
  self.assertEqual(json.loads((self.base/'defaults'/'jobs.json').read_text(encoding='utf-8'))['kind'],B.JOBS_KIND,'持ち出しと同じ形（メモ帳で読める）')
  self.assertEqual(sorted(p.name for p in self.base.iterdir()),['defaults'],'途中のフォルダーを残さない')

 def test_without_drops_schedules_and_unused_rne(self):
  self.put([job('A'),job('B')],{'A':[{'type':'daily','time':'06:00','enabled':True}]})
  payloads,settings,rne=D.without(D.read(self.base),'jobs',['A'])
  self.assertEqual(D.names_of('jobs',payloads['jobs']),['B'])
  self.assertEqual(D.names_of('schedules',payloads['schedules']),[],'外した対象の予定も外す')
  self.assertEqual(sorted(rne),['B.RNE'],'使われなくなった RNE も外す')
  D.write(self.base,payloads,settings,rne)
  self.assertEqual(D.summary(D.read(self.base))['counts']['rne'],1)
  self.assertTrue(D.remove(self.base));self.assertIsNone(D.read(self.base));self.assertFalse(D.remove(self.base))

 def test_diff_and_picks(self):
  self.put([job('A'),job('B',output_file='new.csv'),job('C')])
  local={'jobs':B.jobs_export([job('A'),job('B'),job('X')])}
  (self.t/'rne').mkdir();(self.t/'rne'/'A.RNE').write_text('a');(self.t/'rne'/'B.RNE').write_text('old')
  dif=D.diff(D.read(self.base),local,self.t/'rne')
  self.assertEqual(dif['jobs'],{'add':['C'],'change':['B'],'same':['A'],'local':['X']})
  self.assertEqual(dif['rne'],{'add':[],'change':['B.RNE'],'same':['A.RNE'],'local':[]})
  self.assertEqual(D.picks('overwrite',dif)['jobs'],['C','B'],'上書き＝足りない物＋違う物')
  self.assertEqual(D.picks('add',dif)['jobs'],['C'],'差分追加＝足りない物だけ')
  self.assertEqual(D.picks('keep',dif)['jobs'],[],'今のまま＝何もしない')
  with self.assertRaises(ValueError):D.picks('replace-all',dif)
  self.assertTrue(D.has_data(local));self.assertFalse(D.has_data({'jobs':B.jobs_export([])}))

 def test_mark_and_backup(self):
  data=self.t/'data';data.mkdir()
  self.assertIsNone(D.read_mark(data))
  D.write_mark(data,origin='new');m=D.write_mark(data,ack='x')
  self.assertEqual((m['origin'],m['ack']),('new','x'),'前の値に重ねる')
  (data/'Config').mkdir();(data/'Config'/'app_settings.sqlite3').write_text('db')
  for i in range(D.BACKUP_KEEP+2):
   b=D.backup(data,{'app_settings.sqlite3':data/'Config'/'app_settings.sqlite3','rne':data/'rne'},f'l{i:02d}')
  self.assertTrue((b/'app_settings.sqlite3').is_file())
  self.assertEqual(len(list((data/'backup').iterdir())),D.BACKUP_KEEP,'古い控えは押し出す')

 def test_sample_defaults(self):
  """配る版から外した雛形の6件と RNE 4つは、見本として既定の設定の形で残っている。"""
  d=D.read(SAMPLE)
  self.assertIsNotNone(d,'samples\\defaults がある')
  s=D.summary(d)
  self.assertEqual((s['counts']['jobs'],s['counts']['rne']),(6,4))
  self.assertIn('SIKAODRNOW',s['parts']['jobs'])
  self.assertTrue(all(D.rne_name(j) for j in d['jobs']['jobs']),'RNE は .\\rne\\<名前> で指す')


# 本物の app で、手元へ当てる流れを通す。データの基準（NAVI_DATA_ROOT）と置き場は作業用のフォルダー。
# 配布から写した手元（installed・source=pc）として振る舞わせるため、受け口の場所の決め方だけ差し替える
APP=r"""
import json,sys,shutil
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_web,navi_defaults as D,navi_bundle as B
share=Path(sys.argv[2]);out={}
navi_web.release_place=lambda:'installed'
navi_web.DATA_ROOT_SOURCE='pc'
navi_web._defaults_where=lambda:(share,'install')
t=app.app.test_client()
# 1) 新しく写した手元は空。聞かずに既定を入れる（予定・RNE も）
out['offer0']=t.get('/api/defaults/offer').get_json()['show']
navi_web.defaults_tick()
c=app.load();out['first_jobs']=sorted(j['name'] for j in c['jobs'])
out['first_rne']=sorted(p.name for p in (app.DATA_ROOT/'rne').iterdir())
out['first_mark']=D.read_mark(app.DATA_ROOT).get('lastMode')
out['offer1']=t.get('/api/defaults/offer').get_json()['show']
# 2) 手元で1件を変え、手元だけの対象を足す。置き場の既定も1件変えて1件足す
c=app.load()
for j in c['jobs']:
 if j['name']=='SIKALOTDEF':j['comment']='手元で変えた'
c['jobs'].append(dict(c['jobs'][0],id='mine',name='手元だけ'));app.save(c)
d=D.read(share);pay={p:d[p] for p in D.PARTS}
for x in pay['jobs']['jobs']:
 if x['name']=='SIKALOTNOW':x['comment']='既定で変えた'
pay['jobs']['jobs'].append(dict(pay['jobs']['jobs'][0],name='既定に足した'))
pay['schedules']=B.schedules_export([{'name':'既定に足した','schedules':[{'type':'daily','time':'05:00','enabled':True}]},
                                     {'name':'SIKALOTDEF','schedules':[{'type':'daily','time':'07:00','enabled':True}]}])
D.write(share,pay,d['settings'],{k:str(v) for k,v in d['rne'].items()})
o=t.get('/api/defaults/offer').get_json()
out['offer2']={'show':o['show'],'kind':o['kind'],'add':o['diff']['jobs']['add'],'change':o['diff']['jobs']['change'],'local':o['diff']['jobs']['local']}
# 3) 差分追加: 足りない物だけ。手元で変えた物も、手元の対象の予定も触らない
r=t.post('/api/defaults/apply',json={'mode':'add'}).get_json()
c=app.load();by={j['name']:j for j in c['jobs']}
out['add']={'ok':r['ok'],'added':'既定に足した' in by,'kept_mine':by['SIKALOTDEF'].get('comment'),'kept_now':by['SIKALOTNOW'].get('comment') or '',
            'new_sched':len(by['既定に足した'].get('schedules') or []),'def_sched':len(by['SIKALOTDEF'].get('schedules') or []),'only_mine':'手元だけ' in by,
            'backup':Path(r['backup']).is_dir()}
out['offer3']=t.get('/api/defaults/offer').get_json()['show']
# 4) 既定をもう一度入れ替えて（新しい id）、上書き: 既定にある物は既定の中身へ。手元だけの物は残す
d=D.read(share);D.write(share,{p:d[p] for p in D.PARTS},d['settings'],{k:str(v) for k,v in d['rne'].items()})
r=t.post('/api/defaults/apply',json={'mode':'overwrite'}).get_json()
c=app.load();by={j['name']:j for j in c['jobs']}
out['over']={'ok':r['ok'],'def':by['SIKALOTDEF'].get('comment') or '','now':by['SIKALOTNOW'].get('comment') or '','only_mine':'手元だけ' in by,
             'def_sched':len(by['SIKALOTDEF'].get('schedules') or [])}
# 5) 今のまま: 変えずに、この既定はもう聞かない
d=D.read(share);D.write(share,{p:d[p] for p in D.PARTS},d['settings'],{})
before=json.dumps(app.load()['jobs'],sort_keys=True,default=str)
r=t.post('/api/defaults/apply',json={'mode':'keep'}).get_json()
out['keep']={'ok':r['ok'],'same':json.dumps(app.load()['jobs'],sort_keys=True,default=str)==before,'offer':t.get('/api/defaults/offer').get_json()['show']}
out['bad_mode']=t.post('/api/defaults/apply',json={'mode':'x'}).status_code
# 6) このPCの今の設定から、選んだ項目で既定を作る（RNE も入れ、道を .\rne\<名前> に直す）。項目を外す・消す
r=t.post('/api/defaults/save',json={'jobs':['SIKALOTDEF','SIKAODRNOW'],'layouts':[],'recipes':[],'settings':False,'note':'試験'}).get_json()
out['save']={'ok':r['ok'],'jobs':r['defaults']['parts']['jobs'],'rne':r['defaults']['parts']['rne'],'settings':r['defaults']['settings'],
             'path':json.loads((share/'defaults'/'jobs.json').read_text(encoding='utf-8'))['jobs'][0]['rne_path']}
out['save_ack']=D.read_mark(app.DATA_ROOT)['ack']==r['manifest']['id']
r=t.post('/api/defaults/remove-items',json={'part':'jobs','names':['SIKALOTDEF']}).get_json()
out['removed']={'jobs':r['defaults']['parts']['jobs'],'rne':r['defaults']['parts']['rne']}
out['delete']=t.post('/api/defaults/delete').get_json()['removed']
out['state']=t.get('/api/defaults').get_json()['defaults']['exists']
# 7) 共有の設定を使ってきた写し: 手元へ移す支度（今の設定と相対の RNE を写し、印に pending、作業用の写しを退ける）
copy=Path(sys.argv[3]);navi_web.BASE=copy;navi_web.DATA_ROOT_SOURCE='install'
D.write(share,pay,d['settings'],{p.name:str(p) for p in (Path(sys.argv[1])/'samples'/'defaults'/'rne').iterdir()})
o=t.get('/api/defaults/offer').get_json();out['migrate_offer']=(o['show'],o['kind'])
r=t.post('/api/defaults/apply',json={'mode':'add'}).get_json()
m=D.read_mark(copy/'data')
if not r.get('ok'):raise SystemExit('手元へ移す支度が失敗しました: %r'%r)
out['migrate']={'ok':r['ok'],'restart':r['restart'],'db':(copy/'data'/'Config'/'app_settings.sqlite3').is_file(),
                'rne':sorted(r['copied']),'pending':(m.get('pending') or {}).get('mode'),'origin':m['origin'],
                'cache_kept':app.SETTINGS_DB.exists()}   # 動いている最中は名前を替えない（開き直したとき app が退ける）
out['migrate_again']=t.post('/api/defaults/apply',json={'mode':'add'}).get_json()['ok']
print(json.dumps(out,ensure_ascii=False))
"""


# 同じPC（同じ cache）で設定のマスターが変わる: 1回目は A、2回目は空の B、3回目は A に戻す
BOOT=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
c=app.load()
if sys.argv[2]=='add':
 c['jobs'].append({'id':'a1','name':'Aの対象','source':'text','text_path':'x.txt','schedules':[]});app.save(c,quiet=True)
 app.flush_local_to_master('test')
print(json.dumps({'jobs':[j['name'] for j in app.load()['jobs']],'aside':app.SETTINGS_DB.with_name('app_settings.other.bak.sqlite3').is_file()},ensure_ascii=False))
"""


class ForeignCacheTest(unittest.TestCase):
 """データの基準が変わったら、前のマスターの作業用の写しを使わない（2.0.0 で共有の設定から手元へ移すとき）。
 起動時、まだ何も開いていないうちに退ける。動いている最中に名前を替えると Windows では失敗するため。"""
 def test_cache_follows_its_master(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d)
   def boot(master,what=''):
    env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/master),NAVI_CONFIG_DIR=str(d/master/'Config'),
             NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
    r=subprocess.run([sys.executable,'-c',BOOT,str(ROOT),what],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
    self.assertEqual(r.returncode,0,r.stderr[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])
   self.assertEqual(boot('A','add')['jobs'],['Aの対象'])
   b=boot('B')
   self.assertEqual(b['jobs'],[],'空のマスター B に、A の写しの対象が混ざらない')
   self.assertTrue(b['aside'],'前の写しは消さずに退ける')
   self.assertEqual(boot('A')['jobs'],['Aの対象'],'A に戻せば A のマスターから取り直す')


class AppFlowTest(unittest.TestCase):
 def test_flow(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);share=d/'share';share.mkdir();shutil.copytree(SAMPLE/'defaults',share/'defaults')
   data=d/'data';copy=d/'copy';copy.mkdir()
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(data),NAVI_CONFIG_DIR=str(data/'Config'),
            NAVI_SECRET_FILE=str(d/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',APP,str(ROOT),str(share),str(copy)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=240)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertFalse(v['offer0'],'空の手元には聞かない（そのまま入れる）')
  self.assertEqual(len(v['first_jobs']),6);self.assertEqual(v['first_rne'],['SIKAHIKINOW.RNE','SIKALOTDEF.RNE','SIKALOTNOW.RNE','SIKAODRNOW.RNE'])
  self.assertEqual(v['first_mark'],'first');self.assertFalse(v['offer1'],'入れた既定は、もう聞かない')
  self.assertEqual(v['offer2'],{'show':True,'kind':'update','add':['既定に足した'],'change':['SIKALOTDEF','SIKALOTNOW'],'local':['手元だけ']})
  self.assertEqual(v['add'],{'ok':True,'added':True,'kept_mine':'手元で変えた','kept_now':'','new_sched':1,'def_sched':0,'only_mine':True,'backup':True},
                   '差分追加: 足りない物だけ。手元で変えた物・手元の対象の予定は触らない')
  self.assertFalse(v['offer3'])
  self.assertEqual(v['over'],{'ok':True,'def':'','now':'既定で変えた','only_mine':True,'def_sched':1},
                   '上書き: 既定にある物は既定の中身（予定も）。手元だけの物は残す')
  self.assertEqual(v['keep'],{'ok':True,'same':True,'offer':False},'今のまま: 変えない・もう聞かない')
  self.assertEqual(v['bad_mode'],400)
  self.assertEqual(v['save'],{'ok':True,'jobs':['SIKALOTDEF','SIKAODRNOW'],'rne':['SIKALOTDEF.RNE','SIKAODRNOW.RNE'],'settings':False,'path':'.\\rne\\SIKALOTDEF.RNE'})
  self.assertTrue(v['save_ack'],'作ったPCは自分の既定を聞かない')
  self.assertEqual(v['removed'],{'jobs':['SIKAODRNOW'],'rne':['SIKAODRNOW.RNE']},'対象を外すと使われなくなった RNE も外れる')
  self.assertTrue(v['delete']);self.assertFalse(v['state'])
  self.assertEqual(v['migrate_offer'],[True,'migrate'])
  self.assertEqual(v['migrate'],{'ok':True,'restart':True,'db':True,'rne':['rne/SIKAHIKINOW.RNE','rne/SIKALOTDEF.RNE','rne/SIKALOTNOW.RNE','rne/SIKAODRNOW.RNE'],
                                 'pending':'add','origin':'shared','cache_kept':True},
                   '手元へ移す支度: 今の設定と相対の RNE を写し、差分追加は開き直したあとに当てる')
  self.assertFalse(v['migrate_again'],'二度は移さない')


if __name__=='__main__':
 unittest.main()
