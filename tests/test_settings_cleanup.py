"""使わなくなった設定の撤去（2.1.2）。DDE 方式の設定と、どこからも読まれていなかった設定を、読み込みで落とす。

古い版の設定（DDE の待ち時間・SymNavi.exe・窓の隠し方など）を持つ PC でも、読み込めば消え、
保存し直せば設定のファイル（app_settings）からも消える。残す設定には触らない。

実行: python -m unittest tests.test_settings_cleanup -v
"""
import json,os,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

SCRIPT=r"""
import json,sqlite3,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
c=app.load()
# 古い版が書いていた形を、設定のファイルへ直接入れる（今の版の保存は、もうこれらを書かない）
old_settings=dict(c['settings'],extract_engine='dde',dde_timeout_seconds=120,output_wait_seconds=300,symnavi_hide_profile='light',
                  symnavi_hide_action_duration_seconds=0.5,symnavi_hide_interval_seconds=2,stability_profile='balanced_api_parallel',
                  api_parallel_model='process',startup_run=False,backup_generation_limit_enabled=True,api_parallel_lines=9,backup_generations=7)
with app.settings_connection() as con:
 for k,v in (('settings',old_settings),('symnavi_exe','C:\\NAVICL\\bin\\SymNavi.exe'),('symnavim_def','.\\config\\symnavim.def'),('work_folder','.\\work')):
  enc,kind=app._encode_setting(v)
  con.execute("INSERT OR REPLACE INTO app_settings VALUES(?,?,?,?)",(k,enc,kind,'2026-01-01T00:00:00'))
c=app.load()
loaded={'settings':sorted(k for k in app.REMOVED_SETTINGS if k in c['settings']),'top':sorted(k for k in app.REMOVED_TOP_KEYS if k in c),
        'kept':{k:c['settings'][k] for k in ('api_parallel_lines','backup_generations','reject_zero_rows')}}
app.save(c,quiet=True)
with app.settings_connection() as con:
 rows={r['key']:app._decode_setting(r) for r in con.execute('SELECT key,value,value_type FROM app_settings')}
saved=rows['settings']
print(json.dumps({'loaded':loaded,'saved_settings':sorted(k for k in app.REMOVED_SETTINGS if k in saved),
                  'saved_top':sorted(k for k in app.REMOVED_TOP_KEYS if k in rows),
                  'saved_kept':{k:saved[k] for k in ('api_parallel_lines','backup_generations')}},ensure_ascii=False))
"""


class RemovedSettingsTest(unittest.TestCase):
 def test_dropped_on_load_and_save(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',SCRIPT,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['loaded']['settings'],[],'読み込んだ時点で、撤去した設定は無い')
  self.assertEqual(v['loaded']['top'],[],'SymNavi.exe・symnavim.def・work_folder も無い')
  self.assertEqual(v['loaded']['kept'],{'api_parallel_lines':9,'backup_generations':7,'reject_zero_rows':True},'残す設定はそのまま')
  self.assertEqual(v['saved_settings'],[],'保存し直すと設定のファイルからも消える')
  self.assertEqual(v['saved_top'],[])
  self.assertEqual(v['saved_kept'],{'api_parallel_lines':9,'backup_generations':7})

 def test_template_and_sample_are_clean(self):
  """初回に複製する雛形と、既定の設定の見本にも、撤去した設定を残さない。"""
  import ast
  tree=ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
  consts={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body
          if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('REMOVED_SETTINGS','REMOVED_TOP_KEYS')}
  con=sqlite3.connect(ROOT/'config'/'app_settings.template.sqlite3')
  try:rows={k:v for k,v in con.execute('SELECT key,value FROM app_settings')}
  finally:con.close()
  self.assertEqual([k for k in consts['REMOVED_TOP_KEYS'] if k in rows],[])
  self.assertEqual([k for k in consts['REMOVED_SETTINGS'] if k in json.loads(rows['settings'])],[])
  sample=json.loads((ROOT/'samples'/'defaults'/'settings.json').read_text(encoding='utf-8'))
  self.assertEqual([k for k in consts['REMOVED_TOP_KEYS'] if k in sample.get('top',{})],[])
  self.assertEqual([k for k in consts['REMOVED_SETTINGS'] if k in sample.get('settings',{})],[])



DEFAULTS=r"""
import json,re,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
t=app.app.test_client()
c=t.get('/api/config').get_json()
got=c.get('setting_defaults') or {}
# 推奨は画面へ渡すが、そのまま送り返されても設定として保存しない
r=t.put('/api/config',json=c)
with app.settings_connection() as con:
 keys=[r2[0] for r2 in con.execute('SELECT key FROM app_settings')]
js=open(sys.argv[1]+'/static/app.js',encoding='utf-8').read()
fields=sorted(set(re.findall(r"SF\('([a-z_]+)'",js)))
print(json.dumps({'defaults':got,'server':app.SETTING_DEFAULTS,'put':r.status_code,'saved_keys':keys,'fields':fields},ensure_ascii=False,default=str))
"""


class SettingDefaultsTest(unittest.TestCase):
 """画面の推奨（2.1.2）: 推奨の出どころはサーバーの SETTING_DEFAULTS 1つ。画面の一覧（SETTING_FIELDS）の設定は、すべてそこにある。"""
 def test_fields_have_defaults_and_not_saved(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',DEFAULTS,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['defaults'],json.loads(json.dumps(v['server'])),'/api/config が推奨をそのまま渡す')
  self.assertGreater(len(v['fields']),10)
  self.assertEqual([k for k in v['fields'] if k not in v['defaults']],[],'画面の一覧の設定は、すべてサーバーの推奨にある')
  self.assertEqual(v['put'],200)
  self.assertNotIn('setting_defaults',v['saved_keys'],'推奨は設定として保存しない')

if __name__=='__main__':
 unittest.main()
