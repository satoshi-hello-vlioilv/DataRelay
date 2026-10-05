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
  self.assertEqual(navi_paths.data_root(self.app,env={}),(self.app,'app'),'読めない・空の値は無いのと同じ')

 def test_percent_variables_expand_everywhere(self):
  os.environ['DR_TEST_SHARE']='/srv/box'
  self.addCleanup(os.environ.pop,'DR_TEST_SHARE',None)
  self.write('install.json',{'data_root':'%DR_TEST_SHARE%/DataRelay'})
  self.assertEqual(navi_paths.data_root(self.app,env={})[0],Path('/srv/box/DataRelay'),'%NAME% は Windows 以外でも展開（窓と同じ）')
  self.assertEqual(navi_paths.expand('%DR_TEST_UNDEFINED%/x'),'%DR_TEST_UNDEFINED%/x','定義の無い名前は残す')


class ResolveAgainstDataRootTest(unittest.TestCase):
 def setUp(self):
  self.saved=(navi_paths.DATA_ROOT,navi_paths.LOCAL_ROOT)
  self.addCleanup(lambda:navi_paths.setup(*self.saved) if self.saved[0] else None)

 def test_relative_paths_point_to_the_share_from_a_local_copy(self):
  # どの OS でも絶対の道（Windows で /share と書くと、いまのドライブの D:/share になる）
  base=Path(tempfile.gettempdir()).resolve()
  share,local=base/'share'/'DataRelay',base/'local'/'root'
  navi_paths.setup(share,local)
  self.assertEqual(navi_paths.resolve_path('.\\config\\symnavim.conf'.replace('\\','/')),share/'config'/'symnavim.conf')
  self.assertEqual(navi_paths.resolve_path('rne'),share/'rne')
  self.assertEqual(navi_paths.resolve_path('<PC>\\backup'),local/'backup','<PC> はこのPCのまま')


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
