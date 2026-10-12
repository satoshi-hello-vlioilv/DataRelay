"""データの基準（lib/navi_paths.py の data_root）を確かめる。

1.98.0 からアプリを各PCへ写して動かせる（配布）。写すとプログラムの場所はこのPCになるが、設定に書いた相対パス
（.\\config\\symnavim.conf・.\\rne）と設定のマスター（Config\\app_settings.sqlite3）は、共有のアプリのフォルダーを
指したままでなければならない。ここが崩れると、同じ設定がPCごとに違う場所を指し、接続ファイルも RNE も見えなくなる。
実行: python -m unittest tests.test_data_root -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_paths


class DataRootOrderTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.app=Path(self.tmp.name)/'copy';(self.app/'config').mkdir(parents=True)

 def write(self,name,data,bom=False):
  text=json.dumps(data,ensure_ascii=False)
  (self.app/'config'/name).write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.encode('utf-8'))

 def test_order_env_local_install_app(self):
  self.assertEqual(navi_paths.data_root(self.app,env={}),(self.app,'app'),'何も無ければプログラムの場所（これまでと同じ）')
  self.write('install.json',{'data_root':'/share/DataRelay'},bom=True)
  self.assertEqual(navi_paths.data_root(self.app,env={}),(Path('/share/DataRelay'),'install'),'配布から写した印（BOM 付きでも読む）')
  self.write('local.json',{'data_root':'/mine'})
  self.assertEqual(navi_paths.data_root(self.app,env={}),(Path('/mine'),'local'),'このPCの上書きが先')
  self.assertEqual(navi_paths.data_root(self.app,env={'NAVI_DATA_ROOT':'/env'}),(Path('/env'),'env'),'環境変数がいちばん先')

 def test_broken_or_empty_files_are_skipped(self):
  (self.app/'config'/'local.json').write_text('{壊れている',encoding='utf-8')
  self.write('install.json',{'data_root':'  '})
  self.assertEqual(navi_paths.data_root(self.app,env={}),(self.app/'data','pc'),'読めない・空の値は無いのと同じ（写しなので手元の data）')

 def test_copies_keep_their_data_at_hand(self):
  """2.0.0: 写したPCは自分の手元（写しの data）にデータを持つ。共有の設定を使ってきたPCは、手元へ移すまで共有のまま。"""
  self.write('install.json',{'from':'/share'})
  self.assertEqual(navi_paths.data_root(self.app,env={}),(self.app/'data','pc'),'新しく写したPC＝手元の data（既定の設定から始める）')
  self.write('install.json',{'from':'/share','data_root':'/share/DataRelay'})
  self.assertEqual(navi_paths.data_root(self.app,env={}),(Path('/share/DataRelay'),'install'),'前から使っているPCは、選ぶまで共有の設定のまま')
  (self.app/'data').mkdir();(self.app/'data'/'data.json').write_text('{}',encoding='utf-8')
  self.assertEqual(navi_paths.data_root(self.app,env={}),(self.app/'data','pc'),'手元へ移した印があれば手元')
  self.write('local.json',{'data_root':'/mine'})
  self.assertEqual(navi_paths.data_root(self.app,env={})[1],'local','このPCの上書きはいつも先')

 def test_percent_variables_expand_everywhere(self):
  os.environ['DR_TEST_SHARE']='/srv/box'
  self.addCleanup(os.environ.pop,'DR_TEST_SHARE',None)
  self.write('install.json',{'data_root':'%DR_TEST_SHARE%/DataRelay'})
  self.assertEqual(navi_paths.data_root(self.app,env={})[0],Path('/srv/box/DataRelay'),'%NAME% は Windows 以外でも展開（窓と同じ）')
  self.assertEqual(navi_paths.expand('%DR_TEST_UNDEFINED%/x'),'%DR_TEST_UNDEFINED%/x','定義の無い名前は残す')


class ResolveAgainstDataRootTest(unittest.TestCase):
 def setUp(self):
  self.saved=(navi_paths.DATA_ROOT,navi_paths.LOCAL_ROOT,navi_paths.PROGRAM_ROOT,navi_paths.DATA_SOURCE)
  self.addCleanup(lambda:navi_paths.setup(*self.saved) if self.saved[0] else None)
  # 置き場（相対パスの基準）は app を読み込んだほかの試験が決めていることがある。この組の試験は置き場なしから始める
  self.addCleanup(navi_paths.set_place,navi_paths.PLACE_ROOT);navi_paths.set_place(None)

 def test_relative_paths_point_to_the_share_from_a_local_copy(self):
  # どの OS でも絶対の道（Windows で /share と書くと、いまのドライブの D:/share になる）
  base=Path(tempfile.gettempdir()).resolve()
  share,local=base/'share'/'DataRelay',base/'local'/'root'
  navi_paths.setup(share,local)
  self.assertEqual(navi_paths.resolve_path('.\\config\\symnavim.conf'.replace('\\','/')),share/'config'/'symnavim.conf')
  self.assertEqual(navi_paths.resolve_path('rne'),share/'rne')
  self.assertEqual(navi_paths.resolve_path('<PC>\\backup'),local/'backup','<PC> はこのPCのまま')

 def test_program_files_are_found_when_data_is_elsewhere(self):
  """データの基準が写しの data のとき、プログラムに付いてくる物（.\\assets\\empty.accdb など）はプログラムの場所から読む。"""
  with tempfile.TemporaryDirectory() as t:
   prog=Path(t).resolve()/'DataRelay';data=prog/'data'
   (prog/'assets').mkdir(parents=True);(prog/'assets'/'empty.accdb').write_bytes(b'x');data.mkdir()
   (data/'rne').mkdir();(data/'rne'/'A.RNE').write_text('r');(prog/'rne').mkdir();(prog/'rne'/'A.RNE').write_text('old')
   navi_paths.setup(data,Path(t)/'local',prog)
   self.assertEqual(navi_paths.resolve_path('assets/empty.accdb'),prog/'assets'/'empty.accdb','データの基準に無く、プログラムにある物')
   self.assertEqual(navi_paths.resolve_path('rne/A.RNE'),data/'rne'/'A.RNE','両方にあればデータの基準が先')
   self.assertEqual(navi_paths.resolve_path('rne/B.RNE'),data/'rne'/'B.RNE','どちらにも無ければデータの基準（作る物はそこへ）')


 def test_relative_paths_follow_the_release_place(self):
  """2.2.1: 相対パスは配布の置き場（入口の DataRelay.exe があるフォルダー）を先に見る。版のフォルダーから動かしても、
  写しから動かしても、基準は置き場のまま変わらない。置き場に無い物は、データの基準・プログラムの場所にあればそちらを使い、
  まだ無い物は置き場に作る。人が決めた基準（local.json・環境変数）は、これまでどおりデータの基準が先。"""
  import navi_release
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();place=root/'share'/'DataRelay';v1=place/'versions'/'2.2.0';v2=place/'versions'/'2.2.1'
   copy=root/'pc'/'DataRelay';old=root/'old-share'
   for d in (place/'rne',v1/'config',v2/'config',v2/'assets',copy/'config',copy/'data'/'rne',old/'rne'):d.mkdir(parents=True)
   (place/'rne'/'A.RNE').write_text('place');(v2/'assets'/'empty.accdb').write_bytes(b'x');(copy/'data'/'rne'/'C.RNE').write_text('pc')
   (v1/'config'/'x').write_text('');(old/'rne'/'A.RNE').write_text('old')
   # 置き場はどこから動かしても同じ（版のフォルダー → 置き場の根・写し → 入れた元・共有の設定の控え）
   self.assertEqual(navi_release.place_root(v1),place)
   self.assertEqual(navi_release.place_root(v2),place,'版が変わっても基準は同じ')
   (copy/'config'/'install.json').write_text(json.dumps({'from':str(place)}),encoding='utf-8')
   self.assertEqual(navi_release.place_root(copy),place,'写しは入れた元')
   (copy/'config'/'update.json').write_text(json.dumps({'update_dir':str(v2)}),encoding='utf-8')
   self.assertEqual(navi_release.place_root(copy),place,'共有の設定の控え（版のフォルダーを選んでも根へ直す）')
   for prog,src,data in ((v1,'app',v1),(v2,'app',v2),(copy,'pc',copy/'data'),(copy,'install',old)):
    navi_paths.setup(data,root/'local',prog,src);navi_paths.set_place(navi_release.place_root(prog))
    self.assertEqual(navi_paths.rel_root(),place,f'{prog.name} {src}: 相対パスの主な基準は置き場')
    self.assertEqual(navi_paths.resolve_path('.\\rne\\A.RNE'),place/'rne'/'A.RNE',f'{src}: 置き場の物を先に（前の共有・版のフォルダーを指さない）')
    self.assertEqual(navi_paths.resolve_path('.\\output'),place/'output','まだ無い物は置き場に作る')
   self.assertEqual(navi_paths.resolve_path('.\\rne\\C.RNE'),place/'rne'/'C.RNE','（install のときは写しの data は見ない）')
   navi_paths.setup(copy/'data',root/'local',copy,'pc');navi_paths.set_place(place)
   self.assertEqual(navi_paths.resolve_path('.\\rne\\C.RNE'),copy/'data'/'rne'/'C.RNE','置き場に無く写しの data にある物はそちら')
   navi_paths.setup(v2,root/'local',v2,'app');navi_paths.set_place(place)
   self.assertEqual(navi_paths.resolve_path('.\\assets\\empty.accdb'),v2/'assets'/'empty.accdb','プログラムに付いてくる物はプログラムの場所')
   self.assertEqual(navi_paths.resolve_path('X.RNE',old/'rne'),old/'rne'/'X.RNE','基準を渡したときは、その基準だけ')
   for src in ('local','env'):
    navi_paths.setup(old,root/'local',copy,src);navi_paths.set_place(place)
    self.assertEqual(navi_paths.resolve_path('.\\rne\\A.RNE'),old/'rne'/'A.RNE',f'{src}: 人が決めたデータの基準が先')
   # 置き場が分からないとき（set_place(None)）は 2.2.0 と同じ
   navi_paths.setup(old,root/'local',v2,'install');navi_paths.set_place(None)
   self.assertEqual(navi_paths.rel_root(),v2)

class RelativeEqualsAbsoluteTest(unittest.TestCase):
 """同じファイルを絶対パスと相対パス（.\\… ／ ./… ／ 名前だけ）で設定したとき、同じ実体に着くか。
 app.py を本当に読み込み、起動と同じ渡し方（navi_paths.setup(app.DATA_ROOT,…)）で、実際に読む関数（RNE・テキスト・結合・
 symnavim.conf）と、画面の「相対に直す」・候補の適用を通す。2.2.2 までは navi_paths.resolve_path だけを試していたため、
 .\\ で始まる RNE・テキスト・結合だけが置き場を見ずにデータの基準で読まれていたのを見逃した。"""
 def test_relative_and_absolute_reach_the_same_file(self):
  code=r'''
import json,os,sys,tempfile
from pathlib import Path
tmp=Path(sys.argv[2]).resolve();sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_paths,navi_joinrun,navi_web
place=tmp/'share'/'DataRelay';copy=tmp/'pc'/'DataRelay';data=copy/'data'
for d in (place/'rne',place/'text',place/'conf',data,copy/'assets'):d.mkdir(parents=True,exist_ok=True)
for f in (place/'rne'/'A.RNE',place/'text'/'T.txt',place/'conf'/'s.conf',copy/'assets'/'x.accdb'):f.write_text('x')
app.DATA_ROOT=Path(str(data))      # 起動と同じく、navi_paths とは別の物（中身は同じ）
navi_paths.setup(app.DATA_ROOT,tmp/'local',copy,'pc');navi_paths.set_place(place)
cfg={'rne_folder':'.\\rne','text_folder':'.\\text'}
read={'rne':lambda v:app.resolve_rne_path({'rne_path':v,'rne':'A.RNE'},cfg),'text':lambda v:app.resolve_text_path({'text_path':v},cfg),
      'join':lambda v:navi_joinrun.resolve_join_path(v,cfg),'conf':lambda v:app.legacy_conf_path({'symnavim_conf':v})}
cases=[('rne',place/'rne'/'A.RNE',['.\\rne\\A.RNE','./rne/A.RNE','A.RNE']),('text',place/'text'/'T.txt',['.\\text\\T.txt','./text/T.txt','T.txt']),
       ('join',place/'text'/'T.txt',['.\\text\\T.txt','./text/T.txt','T.txt']),('conf',place/'conf'/'s.conf',['.\\conf\\s.conf','./conf/s.conf'])]
out=[]
for kind,target,rels in cases:
 for v in [str(target)]+rels:out.append([kind,v,str(read[kind](v)),str(target)])
c=app.app.test_client()
r=c.post('/api/path-convert',json={'value':str(place/'rne'/'A.RNE'),'mode':'relative'}).get_json()
out.append(['convert',r['value'],str(navi_paths.resolve_path(r['value'])),str(place/'rne'/'A.RNE')])
# 事前診断: 置き場に無く写しの data にある RNE は「注意」（理由が先）、どこにも無い RNE は探した順を出す（2.2.4）
(data/'rne').mkdir(parents=True,exist_ok=True);(data/'rne'/'B.RNE').write_text('x')
J=lambda n,v:{'id':n,'name':n,'source':'rne','rne':n+'.RNE','rne_path':v,'output_folder':str(tmp),'output_format':'csv','output_file':n+'.csv','schedules':[]}
real_load=navi_web.load;navi_web.load=lambda:{**real_load(),'jobs':[J('A','.\\rne\\A.RNE'),J('B','.\\rne\\B.RNE'),J('C','.\\rne\\C.RNE')]}
checks={x['label']:x for x in c.post('/api/validate').get_json()['checks']}
out.append(['diag',checks['A RNE']['level'],checks['B RNE']['level'],checks['B RNE']['detail'],checks['C RNE']['level'],checks['C RNE']['detail']])
saved={};navi_web.save=lambda c_,*a,**k:saved.update(c_);navi_web.load=lambda:{'jobs':[]}
for cand in (place/'conf'/'s.conf',copy/'assets'/'x.accdb'):
 c.post('/api/apply-path-suggestion',json={'item':'symnavim_conf','candidate':str(cand)})
 out.append(['suggest',saved['symnavim_conf'],str(navi_paths.resolve_path(saved['symnavim_conf'])),str(cand)])
print(json.dumps(out,ensure_ascii=False))
'''
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'boot'),NAVI_CONFIG_DIR=str(Path(d)/'cfg'),PYTHONIOENCODING='utf-8')
   out=subprocess.run([sys.executable,'-c',code,str(ROOT),d],cwd=d,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(out.returncode,0,out.stderr[-2000:])
   rows=json.loads(out.stdout.strip().splitlines()[-1])
  diag=next(r for r in rows if r[0]=='diag');rows=[r for r in rows if r[0]!='diag']
  self.assertEqual(diag[1:3],['ok','warning'],'置き場にある RNE は OK、写しの data にだけある RNE は注意')
  self.assertTrue(diag[3].startswith('置き場に無いので、データの基準の物を使っています: '),diag[3])
  self.assertEqual(diag[4],'error');self.assertIn('探した順: 置き場 ',diag[5])
  for kind,value,got,want in rows:
   self.assertEqual(Path(got).resolve(),Path(want).resolve(),f'{kind}: {value} が {want} ではなく {got} を指す')
  stored={r[1] for r in rows if r[0]=='suggest'}
  self.assertIn('.\\conf\\s.conf',stored,'置き場の中の候補は相対で持つ（ほかのPCへ配っても同じ場所を指す）')
  self.assertEqual(next(r[1] for r in rows if r[0]=='convert'),'.\\rne\\A.RNE','画面の「相対に直す」は置き場からの道')

 def test_to_relative_refuses_paths_that_would_read_back_elsewhere(self):
  saved=(navi_paths.DATA_ROOT,navi_paths.LOCAL_ROOT,navi_paths.PROGRAM_ROOT,navi_paths.DATA_SOURCE)
  self.addCleanup(lambda:navi_paths.setup(*saved) if saved[0] else None)
  self.addCleanup(navi_paths.set_place,navi_paths.PLACE_ROOT)
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();place=root/'place';data=root/'data'
   (place/'rne').mkdir(parents=True);(data/'out').mkdir(parents=True)
   (place/'rne'/'A.RNE').write_text('x')
   navi_paths.setup(data,root/'local',root/'prog','pc');navi_paths.set_place(place)
   self.assertEqual(navi_paths.to_relative(place/'rne'/'A.RNE'),'.\\rne\\A.RNE')
   self.assertEqual(navi_paths.to_relative(root/'other'/'B.RNE'),'..\\other\\B.RNE','基準の外は ..\\ で')
   self.assertIsNone(navi_paths.to_relative(root/'other'/'B.RNE',inside_only=True))
   # .\out は置き場に無く、データの基準にある → 置き場の .\out（まだ無い）を相対にすると、読み直すとデータの基準の物を指す
   self.assertIsNone(navi_paths.to_relative(place/'out'),'読み直して別の物に着くなら相対にしない')
   self.assertEqual(navi_paths.resolve_in('',place/'rne'),place/'rne','空ならフォルダーそのもの')
   self.assertEqual(navi_paths.resolve_in(str(root/'x.RNE'),place/'rne'),root/'x.RNE','絶対パスはそのまま')


class PathKindAndLocateTest(unittest.TestCase):
 """2.2.4: 書き方の種類と在りか（画面の札・事前診断・見つからないときの知らせが使う答え）。判定は navi_paths だけが持つ。
 2.2.3 までは画面が「ドライブ名か \\\\ で始まらなければ相対」と見ていて、<PC>\\… も %USERPROFILE%\\… も相対と出していた。"""
 def setUp(self):
  saved=(navi_paths.DATA_ROOT,navi_paths.LOCAL_ROOT,navi_paths.PROGRAM_ROOT,navi_paths.DATA_SOURCE)
  self.addCleanup(lambda:navi_paths.setup(*saved) if saved[0] else None)
  self.addCleanup(navi_paths.set_place,navi_paths.PLACE_ROOT)

 def test_kinds(self):
  k=navi_paths.path_kind
  for v,want in (('','empty'),('<PC>\\backup','pc'),('%USERPROFILE%\\Box','env'),('~/x','env'),('$HOME/x','env'),
                 ('\\\\srv\\share','unc'),('C:\\x','abs'),('c:/x','abs'),('/x','abs'),('\\x','abs'),
                 ('.\\rne','rel'),('./rne','rel'),('..\\rne','rel'),('rne','rel'),('X.RNE','rel')):
   self.assertEqual(k(v),want,v)

 def test_locate_names_the_base_and_the_fallback(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();place=root/'place';data=root/'data';prog=root/'prog'
   for d in (place/'rne',data/'output',prog/'assets'):d.mkdir(parents=True)
   (place/'rne'/'A.RNE').write_text('x');(prog/'assets'/'e.accdb').write_text('x')
   navi_paths.setup(data,root/'local',prog,'pc');navi_paths.set_place(place)
   L=navi_paths.locate
   d=L('.\\rne\\A.RNE');self.assertEqual((d['kind'],d['base'],d['rest'],d['fell'],d['exists']),('rel','place','\\rne\\A.RNE',False,True))
   self.assertEqual(d['tried'][0],str(place/'rne'/'A.RNE'),'先に見るのは置き場')
   d=L('A.RNE','.\\rne');self.assertEqual((d['base'],d['rest'],d['exists']),('place','\\rne\\A.RNE',True),'名前だけはフォルダーの中')
   d=L('.\\output');self.assertEqual((d['base'],d['fell'],d['primary']),('data',True,'place'),'置き場に無く、データの基準にある')
   d=L('.\\assets\\e.accdb');self.assertEqual((d['base'],d['fell']),('app',True),'プログラムに付いてくる物')
   d=L('.\\nope');self.assertEqual((d['base'],d['fell'],d['exists'],len(d['tried'])),('place',False,False,3),'どこにも無ければ置き場（3か所を探した）')
   d=L('<PC>\\backup');self.assertEqual((d['kind'],d['base'],d['rest']),('pc','local','\\backup'))
   os.environ['DR_TEST_PLACE']=str(place);self.addCleanup(os.environ.pop,'DR_TEST_PLACE',None)
   d=L('%DR_TEST_PLACE%\\rne');self.assertEqual((d['kind'],d['exists']),('env',True),'%NAME% と \\ の区切りは、どの OS でも Windows と同じに読む')
   self.assertEqual(L('')['kind'],'empty')
   self.assertEqual(L('.\\output')['label'],'データの基準','言葉もサーバーが渡す（画面と知らせで同じ言葉）')

 def test_missing_message_lists_every_place_in_order(self):
  """見つからないときは、探した場所を先に見た順にすべて出す（2.2.3 までは最初の1か所だけ）。"""
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();place=root/'place';data=root/'data';prog=root/'prog'
   for d in (place,data,prog):d.mkdir()
   navi_paths.setup(data,root/'local',prog,'pc');navi_paths.set_place(place)
   m=navi_paths.missing_message('RNE','.\\rne\\X.RNE')
   self.assertTrue(m.startswith('RNEが見つかりません（設定: .\\rne\\X.RNE）。探した順: 置き場 '),m)
   order=[m.index(str(x/'rne'/'X.RNE')) for x in (place,data,prog)]
   self.assertEqual(order,sorted(order),'置き場 → データの基準 → アプリの場所の順')
   self.assertIn('データの基準 '+str(data/'rne'/'X.RNE'),m)
   m=navi_paths.missing_message('RNE','X.RNE','.\\rne')
   self.assertEqual(m,'RNEが見つかりません: 置き場 '+str(place/'rne'/'X.RNE'),'名前だけはフォルダーの中だけを探す（読む決まりと同じ）')

 def test_no_single_place_missing_messages_remain(self):
  """RNE・テキストが見つからない知らせは、どこからも rne_missing_message・text_missing_message・missing_message を通す。"""
  import re
  for f in [ROOT/'app.py',*sorted((ROOT/'lib').glob('*.py'))]:
   if f.name=='navi_changelog.py':continue
   text=f.read_text(encoding='utf-8')
   self.assertIsNone(re.search(r"RNEが見つかりません: \{rp\}|RNEがありません: '|テキストファイルがありません: '",text),f.name)


class PortableTest(unittest.TestCase):
 def test_own_profile_becomes_userprofile(self):
  home='C:\\Users\\alice'
  self.assertEqual(navi_paths.portable('C:\\Users\\alice\\Box\\DataRelay',home=home),'%USERPROFILE%\\Box\\DataRelay')
  self.assertEqual(navi_paths.portable('c:/users/ALICE/Box/x',home=home),'%USERPROFILE%\\Box\\x','大文字小文字・区切りの違いはならす')
  self.assertEqual(navi_paths.portable('C:\\Users\\bob\\Box\\x',home=home),'C:\\Users\\bob\\Box\\x','他人のプロファイルはそのまま')
  self.assertEqual(navi_paths.portable('\\\\srv\\share\\x',home=home),'\\\\srv\\share\\x','共有（UNC）はそのまま')
  self.assertEqual(navi_paths.portable('%USERPROFILE%\\Box',home=home),'%USERPROFILE%\\Box')


class AppFollowsDataRootTest(unittest.TestCase):
 """app.py を本当に読み込み、マスターの在りかと相対パスがデータの基準に付いていくか。"""
 def test_config_dir_and_relative_paths(self):
  with tempfile.TemporaryDirectory() as d:
   share=Path(d).resolve()/'share'      # Windows の短い名前（RUNNER~1）を長い名前へ（resolve_path が長い名前で答える）
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(share),PYTHONIOENCODING='utf-8')
   env.pop('NAVI_CONFIG_DIR',None)
   code=('import sys,json;sys.path.insert(0,"lib");import app;'
         'print(json.dumps({"config":str(app.CONFIG_DIR),"conf":str(app.resolve_path(".\\\\config\\\\symnavim.conf".replace("\\\\","/"))),'
         '"base":str(app.BASE),"source":app.DATA_ROOT_SOURCE}))')
   out=subprocess.run([sys.executable,'-c',code],cwd=str(ROOT),env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(out.returncode,0,out.stderr[-2000:])
   v=json.loads(out.stdout.strip().splitlines()[-1])
   self.assertEqual(Path(v['config']),share/'Config','設定のマスターは共有のアプリのフォルダーの Config')
   self.assertEqual(Path(v['conf']),share/'config'/'symnavim.conf','相対パスは共有のアプリのフォルダー基準')
   self.assertEqual(Path(v['base']),ROOT,'プログラムの場所は動いている写しのまま')
   self.assertEqual(v['source'],'env')


if __name__=='__main__':
 unittest.main()
