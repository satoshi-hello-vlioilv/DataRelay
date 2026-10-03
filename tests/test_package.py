"""配る zip（Release の DataRelay.zip）が、展開すればそのまま動く中身になっているか。版の数字が揃っているか。

zip は .github/scripts/release.py が git archive で作る（いまのコミットの中身）。入れないものは .gitattributes だけで決まる。
実行: python -m unittest tests.test_package -v
"""
import json,re,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_version

# 窓（desktop/src/locate.rs の is_program）がアプリのフォルダーと認める印と、起動に要るもの
NEEDED=['DataRelay.exe','install_local.cmd','app.py','sidecar.py','lib/navi_web.py','lib/navi_instance.py','static/app.js','templates/index.html',
        'config/requirements.txt','config/app_settings.template.sqlite3','assets/empty.accdb','README.md']
# 作る側・確かめる側だけが使うもの（.gitattributes の export-ignore）と、1.96.0 で外したブラウザ版の入口
NOT_SHIPPED=['tests/','desktop/','migration/','samples/','.github/','.gitattributes','.gitignore',
             'start.vbs','start.bat','start_app.py','stop_app.bat','loading.html']


class PackageTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not (ROOT/'.git').exists():raise unittest.SkipTest('git の作業場所でないので zip を作れない')
  cls.tmp=tempfile.TemporaryDirectory();d=Path(cls.tmp.name)
  (d/'DataRelay.exe').write_bytes(b'MZ-test')
  out=subprocess.run([sys.executable,str(ROOT/'.github'/'scripts'/'release.py'),'package','--exe',str(d/'DataRelay.exe'),'--out',str(d/'out')],
                     capture_output=True,text=True,encoding='utf-8',timeout=120)
  if out.returncode:raise AssertionError(out.stderr)
  cls.stdout=out.stdout
  cls.names=zipfile.ZipFile(d/'out'/'DataRelay.zip').namelist()
  cls.notes=(d/'out'/'notes.md').read_text(encoding='utf-8')
  cls.exe=(d/'out'/'DataRelay.exe').read_bytes()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def test_everything_needed_is_in_one_folder(self):
  self.assertTrue(all(n.startswith('DataRelay/') for n in self.names),'展開すると DataRelay フォルダーが1つできる')
  missing=[x for x in NEEDED if 'DataRelay/'+x not in self.names]
  self.assertEqual(missing,[])

 def test_build_and_test_files_are_not_shipped(self):
  shipped=[x for x in NOT_SHIPPED if any(n.startswith('DataRelay/'+x) for n in self.names)]
  self.assertEqual(shipped,[])

 def test_exe_and_notes(self):
  self.assertEqual(self.exe,b'MZ-test','exe だけの差し替え用にも同じものを置く')
  self.assertIn(f'version={navi_version.APP_VERSION}',self.stdout.splitlines()[-1])
  self.assertIn(f'## {navi_version.APP_VERSION} {navi_version.APP_VERSION_TITLE}',self.notes)
  self.assertNotRegex(self.notes,r'<(b|code)>','画面用のタグは Markdown に直す')
  outside='\n'.join(x for i,x in enumerate(self.notes.split('`')) if i%2==0)
  self.assertNotIn('<',outside,'コードの外の < は &lt; のまま（GitHub がタグとして消さないように）')

 def test_markdown_conversion(self):
  sys.path.insert(0,str(ROOT/'.github'/'scripts'))
  import doctest,release
  self.assertEqual(doctest.testmod(release,verbose=False).failed,0)   # verbose を決めないと unittest の -v に反応して出力を混ぜる


class InstallScriptTest(unittest.TestCase):
 """install_local.cmd（exe だけを手元に置く）を、Windows で動かす前に形の上で確かめる。動かすのは CI の自己診断（local の型）。"""
 @classmethod
 def setUpClass(cls):
  cls.raw=(ROOT/'install_local.cmd').read_bytes()
  cls.text=cls.raw.decode('utf-8')

 def test_crlf_utf8_without_bom(self):
  """LF だけの改行は goto のラベルを外すことがある。BOM は1行目の @echo off を壊す。"""
  self.assertFalse(self.raw.startswith(b'\xef\xbb\xbf'),'BOM が無い')
  self.assertEqual(self.raw.count(b'\n'),self.raw.count(b'\r\n'),'改行はすべて CRLF')
  self.assertIn('chcp 65001',self.text.splitlines()[2],'日本語を出す前に UTF-8 へ切り替える')

 def test_reads_its_own_folder_before_shift(self):
  """shift は %1 だけでなく %0 もずらす。%~dp0（このファイルのフォルダー）は引数を読む前に控える。
  （1.97.0 の初版は引数の繰り返しのあとで読み、/quiet を付けるとドライブの直下を指していた。Windows の CI で見つけた）"""
  lines=self.text.splitlines()
  first_shift=next(i for i,l in enumerate(lines) if re.match(r'\s*shift\b',l,re.I))
  uses=[i for i,l in enumerate(lines) if '%~dp0' in l and not re.match(r'\s*rem\b',l,re.I)]
  self.assertTrue(uses and max(uses)<first_shift,f'%~dp0 の行 {[u+1 for u in uses]} / 最初の shift {first_shift+1}')

 def test_every_goto_has_its_label(self):
  labels={l[1:].strip().lower() for l in self.text.splitlines() if l.startswith(':')}
  gotos={g.lower() for g in re.findall(r'\bgoto\s+(\w+)',self.text)}
  self.assertEqual(sorted(gotos-labels),[])

 def test_japanese_only_outside_blocks(self):
  """UTF-8 のバッチでは、括弧の塊の中の日本語が崩れることがある。日本語は echo・rem の1行にだけ書く。"""
  bad=[l for l in self.text.splitlines() if re.search(r'[^\x00-\x7f]',l) and re.search(r'[()]',l)
       and not re.match(r'\s*(rem|echo|>{1,2}\s*"[^"]*"\s*echo)\b',l,re.I)]
  self.assertEqual(bad,[])

 def test_writes_the_pointer_the_window_reads(self):
  """スクリプトが書くファイル名と、窓（locate.rs）が読むファイル名が同じ。"""
  name=re.search(r'POINTER_FILE: &str = "([^"]+)"',(ROOT/'desktop'/'src'/'locate.rs').read_text(encoding='utf-8')).group(1)
  self.assertIn(f'\\{name}"',self.text)


class VersionAgreementTest(unittest.TestCase):
 """exe（Cargo.toml・tauri.conf.json）と中身（navi_version）の版が同じ。Release のタグは中身の版で付ける。"""
 def test_versions_agree(self):
  cargo=re.search(r'^version\s*=\s*"([^"]+)"',(ROOT/'desktop'/'Cargo.toml').read_text(encoding='utf-8'),re.M).group(1)
  tauri=json.loads((ROOT/'desktop'/'tauri.conf.json').read_text(encoding='utf-8'))['version']
  lock=re.search(r'name = "datarelay-desktop"\nversion = "([^"]+)"',(ROOT/'desktop'/'Cargo.lock').read_text(encoding='utf-8')).group(1)
  self.assertEqual({'Cargo.toml':cargo,'tauri.conf.json':tauri,'Cargo.lock':lock},{k:navi_version.APP_VERSION for k in ('Cargo.toml','tauri.conf.json','Cargo.lock')})
