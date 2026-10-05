"""Navigator への接続情報（lib/navi_secret.py と、それを使う app・画面の受け口・ワーカー）。

1.99.0 から、接続先・利用者ID・パスワードは共有の symnavim.conf（平文）ではなく、このPCの置き場（Windows の資格情報
マネージャー）に置く。ここで見るのは次の決まり:
  - symnavim.conf の読み方はこれまでの creds()／api_data_source_profiles() と同じ答えになる（取り込みで値が変わらない）
  - 出どころは このPCの置き場 → まだ取り込んでいないPCだけ symnavim.conf。どちらも無ければ、どこで登録するかを言って止める
  - パスワードは画面へもワーカーの payload.json へも出ない
  - 本物の資格情報マネージャーへ書いて読み戻せる（Windows の CI だけ。試験用の名前で書き、終わったら消す）

実行: python -m unittest tests.test_secret -v
"""
import json,os,subprocess,sys,tempfile,unittest,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_secret as S

CONF="""; 見本
[Connect_本番]
SymNaviServer=NAVISV01
SymNaviUSERID=利用者01
SymNaviPASSWD=p@ss;word
CatalogDBMSList=SYMFOWARE/RDB

[ApiOracle]
enabled=yes
user=ora
password=orapw
server=ORCL

[Api SQL Server]
enabled=no
user=x
"""


class ConfTest(unittest.TestCase):
 def test_reads_like_before(self):
  d=S.parse_conf(CONF)
  self.assertEqual((d['server'],d['user'],d['password'],d['section']),('NAVISV01','利用者01','p@ss;word','Connect_本番'))
  self.assertEqual([(p['kind'],p['user'],p['password'],p['server']) for p in d['profiles']],[('oracle','ora','orapw','ORCL')],
                   'enabled=no は外す・綴りの揺れ（空白）は英数字だけで比べる')

 def test_default_section_wins(self):
  d=S.parse_conf('[Connect_a]\nSymNaviServer=a\nSymNaviUSERID=a\nSymNaviPASSWD=a\n[Default]\nSymNaviServer=d\nSymNaviUSERID=d\nSymNaviPASSWD=d\n')
  self.assertEqual((d['server'],d['section']),('d','Default'))

 def test_missing_fields_are_refused(self):
  with self.assertRaisesRegex(ValueError,'SymNaviPASSWD'):S.parse_conf('[Connect_a]\nSymNaviServer=a\nSymNaviUSERID=a\n')
  with self.assertRaisesRegex(ValueError,'読み取れません'):S.parse_conf('')

 def test_cp932_and_utf8_files(self):
  with tempfile.TemporaryDirectory() as t:
   for enc in ('cp932','utf-8-sig','utf-8'):
    p=Path(t)/f'{enc}.conf';p.write_bytes(CONF.encode(enc))
    self.assertEqual(S.read_conf(p)['user'],'利用者01',enc)


class ShapeTest(unittest.TestCase):
 def test_clean_refuses_blanks(self):
  with self.assertRaisesRegex(ValueError,'パスワード'):S.clean({'server':'s','user':'u','password':' '})

 def test_merge_keeps_password_only_for_same_user(self):
  old={'server':'s','user':'u','password':'pw','profiles':[{'kind':'oracle'}]}
  self.assertEqual(S.merge(old,{'server':'s2','user':'u','password':''})['password'],'pw','サーバーだけ直すのに打ち直させない')
  self.assertEqual(S.merge(old,{'server':'s2','user':'u'})['profiles'],old['profiles'],'画面から直しても追加のデータソースは残す')
  self.assertEqual(S.merge(old,{'server':'s','user':'other','password':''})['password'],'','別の利用者IDに前のパスワードを使わない')

 def test_public_never_has_password(self):
  d=S.stamp(S.clean(S.parse_conf(CONF)),'conf')
  pub=S.public(d)
  self.assertNotIn('p@ss;word',json.dumps(pub,ensure_ascii=False))
  self.assertNotIn('orapw',json.dumps(pub,ensure_ascii=False))
  self.assertTrue(pub['saved'] and pub['has_password'])
  self.assertEqual(pub['origin'],'conf')

 def test_blob_limit(self):
  with self.assertRaisesRegex(ValueError,'長すぎ'):S.encode({'password':'x'*S.BLOB_LIMIT})


class FileVaultTest(unittest.TestCase):
 def test_round_trip(self):
  with tempfile.TemporaryDirectory() as t:
   v=S.FileVault(Path(t)/'s'/'n.json')
   self.assertIsNone(v.load())
   v.save({'user':'u','password':'pw','server':'s'})
   self.assertEqual(v.load()['password'],'pw')
   if os.name=='posix':self.assertEqual(os.stat(v.path).st_mode&0o777,0o600,'持ち主だけが読める')
   self.assertTrue(v.delete());self.assertFalse(v.delete());self.assertIsNone(v.load())

 def test_decline_is_remembered_per_pc(self):
  with tempfile.TemporaryDirectory() as t:
   self.assertFalse(S.declined(t));S.decline(t);self.assertTrue(S.declined(t))
   S.decline(t,False);self.assertFalse(S.declined(t))


@unittest.skipUnless(sys.platform=='win32','Windows の資格情報マネージャー（CI の Windows で流す）')
class WindowsVaultTest(unittest.TestCase):
 """本物の資格情報マネージャー。試験用の名前で書き、終わったら必ず消す（本物の DataRelay/Navigator は触らない）。"""
 def test_round_trip(self):
  v=S.WindowsVault('DataRelay/test-'+uuid.uuid4().hex[:8])
  try:
   self.assertIsNone(v.load(),'無ければ None')
   d=S.stamp(S.clean(S.parse_conf(CONF)),'conf')
   v.save(d)
   self.assertEqual(v.load(),d,'日本語・記号・追加のデータソースまで、そのまま読み戻せる')
   d2=dict(d,password='新しい')
   v.save(d2)
   self.assertEqual(v.load()['password'],'新しい','上書きできる')
  finally:
   v.delete()
  self.assertIsNone(v.load());self.assertFalse(v.delete(),'無いものを消しても失敗にしない')


# 本物の app で、出どころの決め方・画面の受け口・ワーカーへの渡し方を通す（置き場は作業用のファイル）
APP="""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_secret
conf=sys.argv[2];out={}
c=app.load();c['symnavim_conf']='';app.save(c,quiet=True)
try:app.navi_login();out['none']='通った'
except ValueError as e:out['none']=str(e)
out['state_none']={k:app.login_state()[k] for k in ('saved','source','needed','declined')}
c=app.load();c['symnavim_conf']=conf;app.save(c,quiet=True)
out['conf']=list(app.navi_login())
out['profiles_conf']=[(p['kind'],p.get('credential_source','')) for p in app.data_source_profiles(c,'u','pw')]
t=app.app.test_client()
out['get_conf']=t.get('/api/login').get_json()
out['save_bad']=t.post('/api/login',json={'server':'s'}).status_code
r=t.post('/api/login',json={'server':'SV2','user':'u2','password':'secret2'});out['save']=r.status_code
out['vault']=list(app.navi_login())
out['profiles_vault']=[(p['kind'],p.get('credential_source','')) for p in app.data_source_profiles(c,'u2','secret2')]
r=t.post('/api/login',json={'server':'SV3','user':'u2','password':''});out['keep']=app.navi_login()[1]
out['get_vault']=t.get('/api/login').get_json()
out['raw_get']=t.get('/api/login').get_data(as_text=True)
out['validate']=[x for x in t.post('/api/validate',json={}).get_json()['checks'] if x.get('item')=='login']
out['roles']={k:app.path_setting_roles(c)[k][0] for k in ('symnavim_conf','symnavim_def')}
r=t.post('/api/login/import',json={});out['import']=r.status_code;out['after_import']=list(app.navi_login())
out['import_missing']=t.post('/api/login/import',json={'path':conf+'.none'}).status_code
import api_worker
out['worker']=list(api_worker.login({'cfg':c,'user':'x','server':'y'}))
out['delete']=t.post('/api/login/delete').get_json()['removed']
out['after_delete']=app.navi_login()[3]
out['decline']=t.post('/api/login/decline',json={'yes':True}).get_json()['declined']
out['undecline']=t.post('/api/login/decline',json={'yes':False}).get_json()['declined']
print(json.dumps(out,ensure_ascii=False))
"""


class AppTest(unittest.TestCase):
 def test_sources_routes_and_worker(self):
  with tempfile.TemporaryDirectory() as d:
   conf=Path(d)/'共有'/'symnavim.conf';conf.parent.mkdir();conf.write_bytes(CONF.encode('cp932'))
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_CONFIG_DIR=str(Path(d)/'config'),PYTHONIOENCODING='utf-8',
            NAVI_SECRET_FILE=str(Path(d)/'local'/'secrets'/'navigator.json'),DATARELAY_NO_BOOT='1')
   r=subprocess.run([sys.executable,'-c',APP,str(ROOT),str(conf)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=180)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertIn('接続とパス',v['none'],'どこにも無ければ、どこで登録するかを言って止める')
  self.assertEqual(v['state_none'],{'saved':False,'source':'','needed':True,'declined':False},'雛形には RNE の対象があるので要る')
  self.assertEqual(v['conf'],['利用者01','p@ss;word','NAVISV01','conf'],'まだ取り込んでいないPCは symnavim.conf から読む')
  self.assertEqual(v['profiles_conf'],[['oracle','']],'明示した ApiOracle を使う（流用しない）')
  self.assertEqual((v['get_conf']['source'],v['get_conf']['conf']['user']),('conf','利用者01'))
  self.assertEqual((v['save_bad'],v['save']),(400,200))
  self.assertEqual(v['vault'],['u2','secret2','SV2','vault'],'登録したらこのPCの置き場を先に使う')
  self.assertEqual(v['profiles_vault'],[['oracle','navigator_session']],'画面から登録した接続は Oracle に Navigator の認証を流用する')
  self.assertEqual(v['keep'],'secret2','パスワードを空のまま直せば前のものを使う')
  self.assertEqual((v['get_vault']['saved'],v['get_vault']['server'],v['get_vault']['source']),(True,'SV3','vault'))
  for secret in ('secret2','p@ss;word','orapw'):
   self.assertNotIn(secret,v['raw_get'],'画面へパスワードを返さない')
  self.assertEqual([x['ok'] for x in v['validate']],[True],'事前診断に接続情報の行がある')
  self.assertEqual(v['roles'],{'symnavim_conf':'unused','symnavim_def':'unused'},'登録済みなら symnavim.conf は読まない／API方式では def は要らない')
  self.assertEqual(v['import'],200)
  self.assertEqual(v['after_import'],['利用者01','p@ss;word','NAVISV01','vault'],'取り込んだ値はファイルと同じ')
  self.assertEqual(v['import_missing'],400)
  self.assertEqual(v['worker'],['利用者01','p@ss;word','NAVISV01'],'ワーカーはパスワードを置き場から自分で読む')
  self.assertTrue(v['delete'])
  self.assertEqual(v['after_delete'],'conf','消したら symnavim.conf に戻る')
  self.assertEqual((v['decline'],v['undecline']),(True,False))


class NoPasswordInPayloadTest(unittest.TestCase):
 """ワーカーへ渡す payload.json にパスワードを書かない（書くと平文の一時ファイルが残る）。書く場所は3つ。"""
 def test_sources(self):
  bad=[]
  for f in ('app.py','lib/navi_lanerun.py'):
   src=(ROOT/f).read_text(encoding='utf-8')
   for line in src.splitlines():
    if 'payload' in line and "'password':pw" in line:bad.append(f'{f}: {line.strip()[:100]}')
  self.assertEqual(bad,[])


if __name__=='__main__':
 unittest.main()
