"""配布の置き場（lib/navi_release.py）と起動アイコン（lib/navi_shortcut.py）を確かめる。

窓（desktop/src/release.rs）が読む形（manifest.json・release.json・install.json）を作るのはここ。形が食い違うと、
各PCが配る版へそろえられない。偽の ZIP で、置く → 配る → 戻す の道を通す。
実行: python -m unittest tests.test_release -v
"""
import hashlib,io,json,os,sys,tempfile,time,unittest,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_release as R
import navi_shortcut as S


def make_zip(path,version,body='print(1)\n',head='DataRelay/',drop=(),extra=None):
 files={'app.py':body,'sidecar.py':'#\n','lib/navi_version.py':f"APP_VERSION='{version}'; APP_VERSION_TITLE='x'\n",
        'templates/index.html':'<html>','DataRelay.exe':f'exe {version}','config/rne/A.RNE':'rne',
        'config/requirements.txt':'Flask\n','lib/__pycache__/x.pyc':'junk','README.md':'readme'}
 files.update(extra or {})
 with zipfile.ZipFile(path,'w') as z:
  for k,v in files.items():
   if k not in drop:z.writestr(head+k,v)
 return path


class PublishTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.t=Path(self.tmp.name);self.base=self.t/'share';self.base.mkdir()

 def test_publish_writes_a_manifest_the_window_can_check(self):
  out=R.publish_zip(make_zip(self.t/'a.zip','1.98.0'),self.base,uid='me@pc')
  self.assertTrue(out['ok'],out)
  man=json.loads((self.base/'versions'/'1.98.0'/'manifest.json').read_text(encoding='utf-8'))
  self.assertEqual(man['version'],'1.98.0')
  self.assertIn('config/rne',man['payload'],'config は1段下で数える（同じフォルダーの install.json を消さない）')
  self.assertNotIn('config',man['payload'])
  self.assertIn('DataRelay.exe',man['payload'])
  paths={f['path'] for f in man['files']}
  self.assertNotIn('lib/__pycache__/x.pyc',paths,'__pycache__ は配らない')
  for f in man['files']:
   data=(self.base/'versions'/'1.98.0'/f['path']).read_bytes()
   self.assertEqual((len(data),hashlib.sha256(data).hexdigest()),(f['size'],f['sha256']),f['path'])
  self.assertEqual(man['placedBy'],'me@pc')
  self.assertFalse(any(p.name.startswith('.') for p in (self.base/'versions').iterdir()),'途中のフォルダーを残さない')

 def test_refuses_the_same_version_and_broken_zips(self):
  R.publish_zip(make_zip(self.t/'a.zip','1.98.0'),self.base)
  again=R.publish_zip(make_zip(self.t/'b.zip','1.98.0',body='changed'),self.base)
  self.assertFalse(again['ok']);self.assertIn('もう置いてあります',again['error'])
  self.assertIn('欠かせない物',R.publish_zip(make_zip(self.t/'c.zip','1.99.0',drop=('DataRelay.exe',)),self.base)['error'])
  (self.t/'d.zip').write_bytes(b'not a zip')
  self.assertIn('ZIP ファイルとして読めません',R.publish_zip(self.t/'d.zip',self.base)['error'])
  bad=make_zip(self.t/'e.zip','../x')
  self.assertFalse(R.publish_zip(bad,self.base)['ok'],'道に混ぜられない版の字は断る')
  self.assertTrue(R.publish_zip(make_zip(self.t/'f.zip','1.99.0',head=''),self.base)['ok'],'頭の無い ZIP も読む')

 def test_release_entry_seed_and_rollback(self):
  R.publish_zip(make_zip(self.t/'a.zip','1.98.0'),self.base)
  R.publish_zip(make_zip(self.t/'b.zip','1.99.0'),self.base)
  self.assertEqual([v['version'] for v in R.versions(self.base)],['1.99.0','1.98.0'])
  self.assertFalse(R.set_release('2.0.0',self.base)['ok'],'置いていない版は選べない')
  out=R.set_release('1.99.0',self.base,uid='me')
  self.assertTrue(out['ok'],out);self.assertEqual(out['notes'],[])
  self.assertEqual((self.base/'DataRelay.exe').read_text(),'exe 1.99.0','配る入口はその版の exe')
  self.assertEqual(json.loads((self.base/'install.json').read_text(encoding='utf-8')),{},'2.0.0 から、新しいPCへデータの基準は渡さない（写しの data に持つ）')
  back=R.set_release('1.98.0',self.base)
  self.assertEqual((back['version'],back['previous']),('1.98.0','1.99.0'),'前の版へ戻す＝選び直すだけ（前の版を控える）')
  self.assertEqual((self.base/'DataRelay.exe').read_text(),'exe 1.98.0')

 def test_partial_folders_are_swept_only_when_old(self):
  part=self.base/'versions'/'.1.98.0.123.tmp';part.mkdir(parents=True)
  self.assertEqual(R.sweep_partial(self.base),0,'いま置いている最中かもしれない物は消さない')
  old=time.time()-R.STALE_SEC-10;os.utime(part,(old,old))
  self.assertEqual(R.sweep_partial(self.base),1)
  self.assertEqual(R.versions(self.base),[],'書きかけは版に数えない')

 def test_one_publish_at_a_time_and_progress(self):
  z=make_zip(self.t/'a.zip','1.98.0')
  self.assertTrue(R._RUN_LOCK.acquire(blocking=False))
  try:self.assertTrue(R.run_publish(z,self.base).get('busy'))
  finally:R._RUN_LOCK.release()
  out=R.run_publish(z,self.base)
  self.assertTrue(out['ok'])
  p=R.progress();self.assertEqual(p['state'],'done');self.assertEqual(p['done'],p['total'])


class NestingTest(unittest.TestCase):
 """versions の中に versions を作らない（1.99.1）。現場で起きたこと: アプリを置き場の versions\\1.98.0 から直に動かしていて、
 既定の置き場（＝アプリのフォルダー）が版のフォルダーになり、ZIP を置くと versions\\1.98.0\\versions\\1.99.0 ができた。"""
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.t=Path(self.tmp.name);self.share=self.t/'90_Releases'/'DataRelay';self.share.mkdir(parents=True)

 def test_release_root(self):
  s=self.share
  self.assertEqual(R.release_root(s),(s,''),'置き場の根はそのまま')
  root,why=R.release_root(s/'versions');self.assertEqual(root,s);self.assertIn('versions',why)
  root,why=R.release_root(s/'Versions'/'1.98.0');self.assertEqual(root,s,'大文字小文字は問わない');self.assertIn('1.98.0',why)
  self.assertEqual(R.release_root(s/'old'/'1.98.0')[0],s/'old'/'1.98.0','versions の下でなければ直さない')
  self.assertEqual(R.release_root(s/'versions'/'作業')[0],s/'versions'/'作業','版の字でなければ直さない')

 def test_running_from_a_version_folder_places_next_to_it(self):
  app=self.share/'versions'/'1.98.0';(app/'config').mkdir(parents=True)
  self.assertEqual(R.dir_choice(app,''),(self.share,'app'),'版のフォルダーから動かしたら2つ上が置き場')
  self.assertIn('2つ上',R.dir_note(app,''))
  self.assertEqual(R.dir_choice(app,str(self.share/'versions'))[0],self.share,'共有の設定が versions を指しても親')
  base=R.dir_choice(app,'')[0]
  out=R.publish_zip(make_zip(self.t/'a.zip','1.99.0'),base)
  self.assertTrue(out['ok'],out);self.assertEqual(out['warnings'],[])
  self.assertTrue((self.share/'versions'/'1.99.0'/'manifest.json').is_file(),'versions にきれいに並ぶ')
  self.assertFalse((app/'versions').exists(),'版のフォルダーの中に versions を作らない')
  out=R.publish_zip(make_zip(self.t/'b.zip','1.99.1'),self.share/'versions'/'1.99.0')
  self.assertTrue((self.share/'versions'/'1.99.1').is_dir(),'版のフォルダーを渡されても根へ置く')

 def test_nested_versions_are_reported(self):
  (self.share/'versions'/'1.98.0'/'versions'/'1.99.0').mkdir(parents=True)
  self.assertEqual([n['version'] for n in R.nested_versions(self.share)],['1.99.0'])
  st=R.status(self.share,self.share,'1.98.0')
  self.assertEqual([n['version'] for n in st['nested']],['1.99.0'],'画面に出す（動かしはしない）')
  self.assertEqual(st['versionsDir'],str(self.share/'versions'))

 def test_inspect_shows_destination_and_writes_nothing(self):
  x=R.inspect_zip(make_zip(self.t/'a.zip','1.99.0'),self.share/'versions')
  self.assertTrue(x['ok'],x);self.assertEqual(x['dest'],str(self.share/'versions'/'1.99.0'))
  self.assertEqual(x['warnings'],[],'Release の ZIP には注意が無い')
  self.assertFalse((self.share/'versions').exists(),'確かめるだけで書かない')
  R.publish_zip(make_zip(self.t/'a.zip','1.99.0'),self.share)
  x=R.inspect_zip(make_zip(self.t/'a.zip','1.99.0'),self.share)
  self.assertFalse(x['ok']);self.assertTrue(x['exists']);self.assertIn('もう置いてあります',x['error'])

 def test_zip_of_a_whole_app_folder_is_cleaned(self):
  """アプリのフォルダー（＝既定の置き場）をまるごと ZIP にすると、版・各PCの名乗り・配る版・PCの控え・設定のマスターまで入る。"""
  extra={'versions/1.98.0/lib/navi_version.py':"APP_VERSION='1.98.0'\n",'versions/1.98.0/app.py':'old','fleet/PC1.json':'{}',
         'release.json':'{}','install.json':'{}','config/install.json':'{}','Config/local.json':'{}','Config/app_settings.sqlite3':'db'}
  z=make_zip(self.t/'whole.zip','1.99.0',extra=extra)
  with zipfile.ZipFile(z,'a') as zz:zz.writestr('メモ.txt','外')
  x=R.inspect_zip(z,self.share)
  self.assertTrue(x['ok'],x)
  text='\n'.join(x['warnings'])
  self.assertIn('2 つ入っています',text,'入れ子の DataRelay を知らせる')
  self.assertIn('外にある 1 ファイル',text)
  self.assertIn('versions\\（2ファイル）',text);self.assertIn('fleet\\（1ファイル）',text)
  out=R.publish_zip(z,self.share)
  self.assertTrue(out['ok'],out)
  placed=sorted(str(p.relative_to(self.share/'versions'/'1.99.0')).replace('\\','/') for p in (self.share/'versions'/'1.99.0').rglob('*') if p.is_file())
  for bad in ('versions/1.98.0/app.py','fleet/PC1.json','release.json','install.json','config/install.json','Config/local.json','Config/app_settings.sqlite3'):
   self.assertNotIn(bad,placed,bad)
  self.assertIn('app.py',placed);self.assertIn('config/rne/A.RNE',placed,'配る物は入る')
  self.assertFalse((self.share/'versions'/'1.99.0'/'versions').exists(),'版の中に versions を作らない')

 def test_zip_of_the_release_dir_is_warned(self):
  """置き場をまるごと ZIP にした（DataRelay が versions/<版>/ の下にしか無い）。"""
  z=make_zip(self.t/'rel.zip','1.98.0',head='DataRelay/versions/1.98.0/')
  x=R.inspect_zip(z,self.share)
  self.assertTrue(x['ok']);self.assertTrue(any('置き場' in w for w in x['warnings']),x['warnings'])
  self.assertEqual(x['dest'],str(self.share/'versions'/'1.98.0'))


class PlaceTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.app=Path(self.tmp.name)/'app';(self.app/'config').mkdir(parents=True)

 def test_dir_choice_order(self):
  self.assertEqual(R.dir_choice(self.app,''),(self.app,'app'),'既定はアプリのフォルダーそのもの')
  (self.app/'config'/'install.json').write_text(json.dumps({'from':'/origin','data_root':'/d'}),encoding='utf-8')
  self.assertEqual(R.dir_choice(self.app,''),(Path('/origin'),'install'))
  self.assertEqual(R.dir_choice(self.app,'/shared'),(Path('/shared'),'shared'),'共有の設定が入れた元より先')
  (self.app/'config'/'local.json').write_text(json.dumps({'update_dir':'/mine'}),encoding='utf-8')
  self.assertEqual(R.dir_choice(self.app,'/shared'),(Path('/mine'),'local'),'このPCの上書きがいちばん先')
  self.assertTrue(R.installed(self.app))

 def test_remember_writes_only_on_change(self):
  self.assertFalse(R.remember(self.app,''),'覚えることが無ければ書かない')
  self.assertFalse((self.app/'config'/'update.json').exists())
  self.assertTrue(R.remember(self.app,'/shared'))
  self.assertFalse(R.remember(self.app,'/shared'),'同じなら書かない')
  self.assertTrue(R.remember(self.app,''),'消したことも窓へ伝える')
  self.assertEqual(json.loads((self.app/'config'/'update.json').read_text(encoding='utf-8')),{'update_dir':''})

 def test_unreachable_is_reported_quickly(self):
  ok,why=R.reachable(self.app/'nowhere')
  self.assertFalse(ok);self.assertIn('見つかりません',why)
  self.assertFalse((self.app/'nowhere').exists(),'見るだけで作らない')

 def test_status_fleet_and_watch(self):
  share=Path(self.tmp.name)/'share';share.mkdir()
  R.publish_zip(make_zip(Path(self.tmp.name)/'a.zip','1.98.0'),share)
  R.set_release('1.98.0',share)
  told=[]
  w=R.Watch()
  snap=w.check(self.app,share,'1.97.0',str(share),'installed',tell=told.append)
  self.assertTrue(snap['pending']);self.assertEqual(told,['1.98.0'])
  w.check(self.app,share,'1.97.0',str(share),'installed',tell=told.append)
  self.assertEqual(told,['1.98.0'],'同じ版は1回だけ知らせる')
  st=R.status(self.app,share,'1.97.0',str(share),'installed')
  self.assertEqual((st['dirSource'],st['reachable'],st['pending']),('shared',True,True))
  self.assertEqual(st['release']['version'],'1.98.0')
  self.assertEqual(st['entry']['path'],str(share/'DataRelay.exe'))
  self.assertEqual(len(st['fleet']),1,'このPCが名乗った')
  self.assertTrue(st['fleet'][0]['outdated'],'配る版と違うPCに印')
  self.assertEqual(st['fleet'][0]['version'],'1.97.0')


class FakeShell:
 def __init__(self,root):
  self.root=Path(root);self.links={}
  for k in ('desktop','programs'):(self.root/k).mkdir(parents=True,exist_ok=True)
 def folder(self,kind):return self.root/kind
 def target(self,link):return self.links.get(str(link),'')
 def make(self,link,target,workdir,description):
  Path(link).write_text('lnk');self.links[str(link)]=str(target)


class ShortcutTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.sh=FakeShell(self.tmp.name);self.exe=Path(self.tmp.name)/'home'/'DataRelay'/'DataRelay.exe'
  self.local=Path(self.tmp.name)/'local'

 def test_remake_after_deleting_or_declining(self):
  """消した・断ったあとも作り直せる（1.99.2）。これまでは、スタートメニューに1つ残っていると画面のボタンが出ず、
  デスクトップのアイコンを消したら作り直す手段が無かった。"""
  self.exe.parent.mkdir(parents=True);self.exe.write_text('exe')
  S.ensure(self.sh,self.exe,['desktop','programs'])
  st=S.state(self.sh,self.exe,self.local)
  self.assertEqual([(p['where'],len(p['links'])) for p in st['places']],[('desktop',1),('programs',1)])
  (self.sh.folder('desktop')/'DataRelay.lnk').unlink()                  # デスクトップから消した
  S.decline(self.local,self.exe)                                          # 帯で「今はしない」とも答えた
  st=S.state(self.sh,self.exe,self.local)
  self.assertEqual([len(p['links']) for p in st['places']],[0,1],'消した場所は「無い」、残っている場所は「ある」と場所ごとに答える')
  self.assertTrue(st['declined'])
  out=S.ensure(self.sh,self.exe,['desktop'])
  self.assertEqual(len(out['made']),1,'断ったあとでも、頼まれれば作る')
  self.assertEqual(S.ensure(self.sh,self.exe,['desktop','programs'])['made'],[],'ある場所には2つ並べない')
  S.undecline(self.local);self.assertFalse(S.declined(self.local,self.exe))

 def test_only_retarget_when_no_place_is_asked(self):
  self.exe.parent.mkdir(parents=True);self.exe.write_text('exe')
  old=self.sh.folder('programs')/'DataRelay.lnk';self.sh.make(old,'\\\\srv\\DataRelay\\DataRelay.exe','','')
  out=S.ensure(self.sh,self.exe,[])
  self.assertEqual((out['made'],out['retargeted']),([],[str(old)]),'向け直すだけ（デスクトップに勝手に作らない）')
  other=self.sh.folder('desktop')/'古い.lnk';self.sh.make(other,'C:\\old\\DataRelay.exe','','')
  out=S.ensure(self.sh,self.exe,['programs'],retarget=['programs'])
  self.assertEqual(out['retargeted'],[],'スタートメニューの物は向け直し済み。デスクトップの古い物は頼まれていないので触らない')
  self.assertEqual(self.sh.target(other),'C:\\old\\DataRelay.exe')
  self.assertEqual(S.ensure(self.sh,self.exe,['desktop'],retarget=['desktop'])['retargeted'],[str(other)],'その場所だけ向け直す')
  st=S.state(self.sh,self.exe,self.local)
  self.assertEqual([(p['where'],len(p['links']),len(p['old'])) for p in st['places']],[('desktop',1,0),('programs',1,0)])

 def test_target_exe_by_place(self):
  app=Path(self.tmp.name)/'app';app.mkdir()
  self.assertIsNone(S.target_exe(app,'dev','')[0],'作る途中の木では作らない')
  self.assertIn('写し',S.target_exe(app,'installed','')[1])
  (app/'DataRelay.exe').write_text('x')
  self.assertEqual(S.target_exe(app,'installed','')[0],app/'DataRelay.exe')
  mine=Path(self.tmp.name)/'bin'/'DataRelay.exe';mine.parent.mkdir();mine.write_text('x')
  self.assertEqual(S.target_exe(app,'app',str(mine))[0],mine,'exe だけ手元に置いた形は、動いている exe を指す')
  self.assertEqual(S.target_exe(app,'app','')[0],app/'DataRelay.exe','分からなければアプリのフォルダーの exe')
  self.assertEqual(S.target_exe(app,'app',str(Path(self.tmp.name)/'python.exe'))[0],app/'DataRelay.exe','DataRelay.exe でない物は指さない')

 def test_offer_make_and_decline(self):
  self.assertFalse(S.offer(self.sh,self.exe,self.local,installed=False)['show'],'写していないアプリでは聞かない')
  self.assertTrue(S.offer(self.sh,self.exe,self.local,installed=True)['show'])
  out=S.ensure(self.sh,self.exe)
  self.assertEqual(len(out['made']),1);self.assertTrue(out['made'][0].endswith('DataRelay.lnk'))
  self.assertFalse(S.offer(self.sh,self.exe,self.local,installed=True)['show'],'作ったら聞かない')
  self.assertEqual(S.ensure(self.sh,self.exe),{'made':[],'retargeted':[],'errors':[]},'2回目は何もしない')
  other=Path(self.tmp.name)/'other.exe'
  self.assertFalse(S.declined(self.local,other))
  S.decline(self.local,other)
  self.assertTrue(S.declined(self.local,other))
  self.assertFalse(S.offer(FakeShell(Path(self.tmp.name)/'b'),other,self.local,installed=True)['show'],'断ったら聞き直さない')

 def test_old_icons_are_retargeted_not_duplicated(self):
  old=self.sh.folder('desktop')/'共有の DataRelay.lnk'
  self.sh.make(old,'\\\\srv\\box\\DataRelay\\DataRelay.exe','','')
  menu=self.sh.folder('programs')/'DataRelay.lnk'
  self.sh.make(menu,'C:\\Users\\a\\AppData\\Local\\DataRelay\\bin\\DataRelay.exe','','')
  unrelated=self.sh.folder('desktop')/'Excel.lnk';self.sh.make(unrelated,'C:\\Office\\EXCEL.EXE','','')
  self.sh.make(self.sh.folder('desktop')/'DataRelay.lnk','C:\\x\\Other.exe','','')
  self.assertEqual(len(S.offer(self.sh,self.exe,self.local,installed=True)['old']),2,'行き先が DataRelay.exe の物だけ')
  out=S.ensure(self.sh,self.exe)
  self.assertEqual(sorted(out['retargeted']),sorted([str(old),str(menu)]))
  self.assertEqual(out['made'],[],'デスクトップに向け直したアイコンがあるので増やさない')
  self.assertEqual(self.sh.target(old),str(self.exe))
  self.assertEqual(self.sh.target(unrelated),'C:\\Office\\EXCEL.EXE','ほかのアイコンは触らない')

 def test_free_name_avoids_collisions(self):
  d=self.sh.folder('desktop');(d/'DataRelay.lnk').write_text('x')
  self.assertEqual(S.free_name(d).name,'DataRelay (2).lnk')


ROUTES=r"""
import json,sys,time
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib',sys.argv[1]+'/tests']
import app,navi_web
from test_release import make_zip
share=Path(sys.argv[2]);c=app.app.test_client();out={}
z=make_zip(share.parent/'a.zip','9.0.0')
out['dir_bad']=c.post('/api/release/dir',json={'value':str(share/'無い')}).status_code
r=c.post('/api/release/dir',json={'value':str(share)});out['dir']=r.get_json()
out['shared']=app.release_shared()
out['mirror']=json.loads((app.BASE/'config'/'update.json').read_text(encoding='utf-8'))
r=c.post('/api/release/dir',json={'value':str(share/'versions'),'dry':True});out['dry']=r.get_json()
r=c.post('/api/release/dir',json={'value':str(share/'versions'/'8.0.0')});out['dir_norm']=r.get_json()
out['shared_norm']=app.release_shared()
r=c.post('/api/release/dir',json={'value':str(share)})
out['inspect_none']=c.post('/api/release/inspect',json={}).status_code
out['inspect']=c.post('/api/release/inspect',json={'path':str(z)}).get_json()
out['pub_none']=c.post('/api/release/publish',json={}).status_code
r=c.post('/api/release/publish',json={'path':str(z)});out['pub']=r.status_code
for _ in range(100):
 p=c.get('/api/release/progress').get_json()
 if p['state']!='running':break
 time.sleep(0.05)
out['progress']=p['state']
out['set_bad']=c.post('/api/release/set',json={'version':'../x'}).status_code
r=c.post('/api/release/set',json={'version':'9.0.0'});out['set']=r.get_json()
st=c.get('/api/release/status').get_json()
out['status']={k:st[k] for k in ('dirSource','reachable','pending','place')}
out['versions']=[v['version'] for v in st['versions']]
out['restart']=c.get('/api/release/restart-check').get_json()
out['brief']=c.get('/api/release/brief').get_json()['version']
r=c.post('/api/release/dir',json={'value':''});out['dir_reset']=r.get_json()['value']
print(json.dumps(out,ensure_ascii=False))
"""


class RouteTest(unittest.TestCase):
 """画面の受け口（navi_web）を本物の app で通す。置き場は作業用のフォルダー、設定のマスターも作業用へ逃がす。"""
 def test_routes(self):
  import subprocess
  with tempfile.TemporaryDirectory() as d:
   share=Path(d)/'share';share.mkdir()
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_CONFIG_DIR=str(Path(d)/'config'),PYTHONIOENCODING='utf-8')
   mirror=ROOT/'config'/'update.json';had=mirror.read_bytes() if mirror.exists() else None
   try:
    r=subprocess.run([sys.executable,'-c',ROUTES,str(ROOT),str(share)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
   finally:
    # 作る途中の木の config\update.json は試験の跡なので元に戻す
    if had is None:mirror.unlink(missing_ok=True)
    else:mirror.write_bytes(had)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['dir_bad'],400,'届かない置き場は断る')
  self.assertEqual((v['dry']['dir'],v['dry']['versionsDir'],v['dry']['reachable']),(str(share),str(share/'versions'),True),'保存する前に実際の置き場を見せる')
  self.assertIn('versions',v['dry']['note'])
  self.assertEqual((v['dir_norm']['value'],v['shared_norm']),(str(share),str(share)),'版のフォルダーを選んでも根を書く')
  self.assertEqual(v['inspect_none'],400)
  self.assertEqual((v['inspect']['ok'],v['inspect']['dest']),(True,str(share/'versions'/'9.0.0')))
  self.assertTrue(v['dir']['changed']);self.assertEqual(v['shared'],str(share),'共有の設定（マスター）に入った')
  self.assertEqual(v['mirror'],{'update_dir':str(share)},'窓の読む控えも書いた')
  self.assertEqual((v['pub_none'],v['pub'],v['progress']),(400,200,'done'))
  self.assertEqual(v['set_bad'],400)
  self.assertTrue(v['set']['ok'],v['set'])
  self.assertEqual(v['status'],{'dirSource':'shared','reachable':True,'pending':True,'place':'dev'})
  self.assertEqual(v['versions'],['9.0.0'])
  self.assertEqual(v['restart'],{'ok':True,'reason':''})
  self.assertEqual(v['dir_reset'],'')


@unittest.skipUnless(S.available(),'Windows と pywin32 が要る（CI の Windows で流す）')
class RealShellTest(unittest.TestCase):
 """本物の Windows の部品で .lnk を作って読む（置き場所だけ作業用のフォルダーへ向ける。本物のデスクトップは触らない）。
 置き場所の名前もアイコンの名前も日本語にする（アカウント名が日本語の PC のデスクトップ・利用者が付けた名前）。"""
 def test_make_read_and_retarget(self):
  # 画面の問い合わせと同じく、別の糸で動かす（COM は糸ごとの初期化が要る）
  import threading
  err=[]
  def body():
   try:self._body()
   except BaseException as e:err.append(e)
  t=threading.Thread(target=body);t.start();t.join(60)
  if err:raise err[0]

 def _body(self):
  with tempfile.TemporaryDirectory() as d:
   class Shell(S.WindowsShell):
    def folder(self,kind):
     f=Path(d)/'利用者'/{'desktop':'デスクトップ','programs':'プログラム'}[kind];f.mkdir(parents=True,exist_ok=True);return f
   sh=Shell();exe=Path(sys.executable)
   old=sh.folder('desktop')/'共有の DataRelay.lnk'
   sh.make(old,Path(d)/'share'/'DataRelay.exe',Path(d),'古いアイコン')
   self.assertTrue(old.is_file())
   self.assertTrue(sh.target(old).lower().endswith('datarelay.exe'),sh.target(old))
   out=S.ensure(sh,exe)
   self.assertEqual(out['retargeted'],[str(old)],out)
   self.assertEqual(Path(sh.target(old)),exe,'日本語の名前のアイコンも向け直せる')
   self.assertFalse(S.offer(sh,exe,Path(d)/'local',installed=True)['show'])
   made=S.ensure(Shell(),Path(d)/'写し'/'DataRelay.exe')
   self.assertEqual(len(made['made'])+len(made['retargeted']),1,made)


if __name__=='__main__':
 unittest.main()
