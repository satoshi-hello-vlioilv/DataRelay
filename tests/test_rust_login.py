"""Navigator の接続情報が、Python（navi_secret・/api/login）と Rust（desktop/core の secret.rs・login.rs）で同じか（2.17.0）。

接続情報は状態を持つ（保存する・消す・「使わない」と答える）。Python と Rust に別々の置き場を同じ初めの状態から用意し、
同じ手順を流して、1手ずつ答えを比べる。あわせて:
  - Rust が書いた置き場を Python（抽出のワーカーが使う navi_secret）が読めるか、その逆も
  - symnavim.conf の読み方（configparser と同じ決まり）を、いろいろな書き方で関数ごとに比べる
  - Windows では、本物の資格情報マネージャー（試験用の名前）で、Rust と Python が互いに書いた物を読めるか
実行: python -m unittest tests.test_rust_login -v
"""
import json,os,shutil,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402

UTF8_CONF='[Default]\nSymNaviServer = srv:2001\nSymNaviUSERID = 利用者\nSymNaviPASSWD = 秘密\n\n[ApiOracle]\nuser = ora\npasswd = orapw\nserver = oradb\n[Api Resource]\nresource = R1\nenabled = no\n'
CP932_CONF='[Connect_A]\nSymNaviServer=cp932srv\nSymNaviUSERID=担当者\nSymNaviPASSWD=ﾊﾟｽ\n'
SHORT_CONF='[X]\nSymNaviServer=s\n'
BROKEN_CONF='[A]\nSymNaviServer=s\n[A]\n'

INIT=r"""
import sys,json,sqlite3
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
app.load()
with sqlite3.connect(str(app.SETTINGS_DB)) as c:
 for k,v in json.loads(sys.argv[2]).items():
  c.execute("INSERT OR REPLACE INTO app_settings(key,value,value_type,updated_at) VALUES(?,?,'text','x')",(k,v))
 c.execute('DELETE FROM jobs')
 for i,(on,src) in enumerate(json.loads(sys.argv[3])):
  c.execute("INSERT INTO jobs(id,display_order,enabled,name,rne,rne_path,output_folder,output_format,output_file,table_name,sheet_name,read_type,updated_at,source) VALUES(?,?,?,?,'','','','sqlite3','','','','','x',?)",(f'j{i}',i,on,f'j{i}',src))
"""

STEPS=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
t=app.app.test_client();out=[]
for s in json.loads(sys.stdin.read()):
 kw={'data':s['raw'].encode('utf-8'),'content_type':'application/json'} if 'raw' in s else ({'json':s['body']} if 'body' in s else {})
 r=t.open(s['path'],method=s['method'],**kw)
 out.append({'status':r.status_code,'body':r.get_data(as_text=True)})
print(json.dumps(out,ensure_ascii=False))
"""

PROBE=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import navi_secret as S
out=[]
for q in json.loads(sys.stdin.read()):
 f,a=q['fn'],q['args']
 try:
  if f=='parse_conf':
   try:r={'ok':S.parse_conf(a['text'])}
   except ValueError as e:r={'syntax':True} if str(e).startswith('symnavim.conf の書き方を読めません') else {'error':str(e)}
  elif f=='read_conf_text':
   try:r={'ok':S.read_conf_text_bytes(bytes(a['bytes']))} if hasattr(S,'read_conf_text_bytes') else None
   except ValueError as e:r={'error':str(e)}
   if r is None:
    raw=bytes(a['bytes'])
    try:
     r=None
     for enc in ('utf-8-sig','cp932'):
      try:r={'ok':raw.decode(enc)};break
      except UnicodeDecodeError:continue
     if r is None:raise ValueError('symnavim.conf の文字コードを読めません（CP932 か UTF-8 で保存してください）')
    except ValueError as e:r={'error':str(e)}
  elif f=='win_vault':
   v=S.WindowsVault(a['target'])
   r={'save':lambda:v.save(a['data']),'load':v.load,'delete':v.delete}[a['op']]()
  out.append({'ok':True,'result':r})
 except Exception as e:out.append({'ok':False,'error':f'{type(e).__name__}: {e}'})
print(json.dumps(out,ensure_ascii=False))
"""


def side_env(d):
 env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
          NAVI_SECRET_FILE=str(d/'local'/'secrets'/'navigator.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',USERNAME='parity')
 env.pop('USER',None)
 return env


def run(cmd,env,stdin=''):
 r=subprocess.run(cmd,input=stdin,env=env,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
 if r.returncode:raise AssertionError(r.stderr[-3000:])
 return r.stdout


def norm(body,roots):
 """比べられる形へ。保存の時刻（秒）を外し、置き場の根（Python 側・Rust 側で違う）を同じ印へ。
 書き方の誤りの説明（configparser の例外の文言）は前置きだけにする。"""
 for r in roots:body=body.replace(json.dumps(str(r))[1:-1],'<ROOT>')
 v=json.loads(body)
 def walk(x):
  if isinstance(x,dict):
   x.pop('saved_at',None)
   if isinstance(x.get('error'),str) and x['error'].startswith('symnavim.conf の書き方を読めません'):x['error']='symnavim.conf の書き方を読めません'
   for y in x.values():walk(y)
  elif isinstance(x,list):
   for y in x:walk(y)
 walk(v);return v


class LoginParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.exe=core_exe()
  if not cls.exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.tmp=tempfile.TemporaryDirectory();cls.t=Path(cls.tmp.name).resolve()
  conf=cls.t/'shared';conf.mkdir()
  (conf/'utf8.conf').write_text(UTF8_CONF,encoding='utf-8')
  (conf/'bom.conf').write_bytes(b'\xef\xbb\xbf'+UTF8_CONF.encode('utf-8'))
  (conf/'cp932.conf').write_bytes(CP932_CONF.encode('cp932'))
  (conf/'short.conf').write_text(SHORT_CONF,encoding='utf-8')
  (conf/'broken.conf').write_text(BROKEN_CONF,encoding='utf-8')
  cls.conf=conf

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def scenario(self,name,settings,jobs,steps):
  """初めの状態を Python で作り（設定の手元の写し）、Rust 側へ同じ物を写してから、同じ手順を流して比べる。"""
  a=self.t/name/'py';b=self.t/name/'rs'
  run([sys.executable,'-c',INIT,str(ROOT),json.dumps(settings),json.dumps(jobs)],side_env(a))
  shutil.copytree(a,b)
  py=json.loads(run([sys.executable,'-c',STEPS,str(ROOT)],side_env(a),json.dumps(steps,ensure_ascii=False)).strip().splitlines()[-1])
  lines=[json.dumps({'method':s['method'],'path':s['path'],'query':'','body':s['raw'] if 'raw' in s else (json.dumps(s['body'],ensure_ascii=False) if 'body' in s else '')},ensure_ascii=False) for s in steps]
  rs=[json.loads(x) for x in run([str(self.exe),'answer','--base',str(ROOT)],side_env(b),'\n'.join(lines)+'\n').splitlines() if x.strip()]
  bad=[]
  for i,(s,p,r) in enumerate(zip(steps,py,rs)):
   if r['status']==0:bad.append(f'{i} {s["path"]}: Rust が答えない');continue
   if p['status']!=r['status']:bad.append(f'{i} {s["method"]} {s["path"]} {s.get("body")}: 番号 Python={p["status"]} Rust={r["status"]}\n  PY={p["body"][:300]}\n  RS={r["body"][:300]}');continue
   if s.get('compare','json')=='json':
    x,y=norm(p['body'],[a]),norm(r['body'],[b])
    if x!=y:bad.append(f'{i} {s["method"]} {s["path"]} {s.get("body")}:\n  PY={json.dumps(x,ensure_ascii=False)[:600]}\n  RS={json.dumps(y,ensure_ascii=False)[:600]}')
  self.assertEqual(len(rs),len(steps))
  self.assertEqual(bad,[],f'{name}: '+'\n'.join(bad))
  return a,b

 def test_register_change_delete(self):
  G={'method':'GET','path':'/api/login'}
  steps=[G,
   {'method':'POST','path':'/api/login/decline','body':{}},G,
   {'method':'POST','path':'/api/login/decline','body':{'yes':0}},G,
   {'method':'POST','path':'/api/login/decline','body':{'yes':False}},G,
   {'method':'POST','path':'/api/login/decline','raw':'{'},
   {'method':'POST','path':'/api/login','body':{'server':' srv ','user':'u1','password':'p1','section':5,'profiles':[{'kind':'oracle','user':'o','password':'op'},{'kind':'x'},'s',3]}},G,
   {'method':'POST','path':'/api/login','body':{'server':'srv2','user':'u1','password':''}},G,
   {'method':'POST','path':'/api/login','body':{'server':'srv3','user':'u2','password':' '}},
   {'method':'POST','path':'/api/login','body':{}},
   {'method':'POST','path':'/api/login','body':{'server':'s','user':'u','password':'p','profiles':'abc'}},
   {'method':'POST','path':'/api/login','body':{'server':'s','user':'u','password':'p','profiles':{'a':1}}},
   {'method':'POST','path':'/api/login','body':{'server':'s','user':'u','password':'p','profiles':7},'compare':'status'},
   {'method':'POST','path':'/api/login','body':['x']},
   # 本文が並びでも、Python は dict() で辞書へ直す（[鍵, 値]・2 文字の字・鍵が 2 つの辞書）。直せなければ 400、直し方が無ければ 500
   {'method':'POST','path':'/api/login','body':[['server','s0'],['user','u0'],['password','p0']]},G,
   {'method':'POST','path':'/api/login','body':['ab',['server','s'],[1,'x']]},
   {'method':'POST','path':'/api/login','body':[['a',1,2]]},
   {'method':'POST','path':'/api/login','body':[{'a':1,'b':2}]},
   {'method':'POST','path':'/api/login','body':[{'a':1}]},
   {'method':'POST','path':'/api/login','body':'ab'},
   {'method':'POST','path':'/api/login','body':[5],'compare':'status'},
   {'method':'POST','path':'/api/login','body':[[[1],'x']],'compare':'status'},
   {'method':'POST','path':'/api/login','body':7,'compare':'status'},
   {'method':'POST','path':'/api/login','body':{'server':'s'*3000,'user':'u','password':'p'}},
   {'method':'POST','path':'/api/login/delete'},G,
   {'method':'POST','path':'/api/login/delete'},
   {'method':'POST','path':'/api/login/import','body':{}},
   {'method':'POST','path':'/api/login/import','body':{'path':str(self.conf/'none.conf')}},
   {'method':'POST','path':'/api/login/import','body':{'path':str(self.conf/'short.conf')}},
   {'method':'POST','path':'/api/login/import','body':{'path':str(self.conf/'broken.conf')}},
   {'method':'POST','path':'/api/login/import','body':{'path':str(self.conf/'cp932.conf')}},G,
   {'method':'POST','path':'/api/login/import','body':{'path':str(self.conf/'utf8.conf')}},G,
   {'method':'POST','path':'/api/login','body':{'server':'s9','user':'利用者','password':''}},G]
  a,b=self.scenario('plain',{},[],steps)
  # Rust が書いた置き場を Python（抽出のワーカーと同じ navi_secret）が読める。中身は Python が書いた物と同じ（時刻を除く）
  pv=json.loads((a/'local'/'secrets'/'navigator.json').read_text(encoding='utf-8'))
  code="import sys,json;sys.path.insert(0,sys.argv[1]+'/lib');import navi_secret as S;print(json.dumps(S.FileVault(sys.argv[2]).load(),ensure_ascii=False))"
  rv=json.loads(run([sys.executable,'-c',code,str(ROOT),str(b/'local'/'secrets'/'navigator.json')],side_env(b)).strip())
  pv.pop('saved_at');rv.pop('saved_at')
  self.assertEqual(rv,pv)
  self.assertEqual((rv['server'],rv['password'],len(rv['profiles'])),('s9','秘密',1),'同じ利用者IDなら、空のパスワードは前のものを使う')

 def test_settings_conf_and_needed(self):
  """設定の symnavim.conf（相対・CP932・BOM）と、有効な RNE の対象があるか（要るか）。"""
  G={'method':'GET','path':'/api/login'}
  for name,conf,jobs in [('cp932',str(self.conf/'cp932.conf'),[[1,'rne']]),('bom',str(self.conf/'bom.conf'),[[0,'rne'],[1,'text']]),
                         ('short',str(self.conf/'short.conf'),[[1,'']]),('broken',str(self.conf/'broken.conf'),[[1,'RNE ']]),
                         ('missing',str(self.conf/'nope.conf'),[[1,'join']]),('blank','  ',[])]:
   self.scenario('conf_'+name,{'symnavim_conf':conf},jobs,[G,{'method':'POST','path':'/api/login/import','body':{}},G,{'method':'POST','path':'/api/login/import','body':{'path':' '}}])


class ConfReadTest(unittest.TestCase):
 """symnavim.conf の読み方を、いろいろな書き方で Python の navi_secret.parse_conf と比べる。"""
 TEXTS=[UTF8_CONF,CP932_CONF,SHORT_CONF,BROKEN_CONF,'','x=1\n','[A]\n','[A]\nnovalue\n','[A]\n=1\n',
        '[Default]\nSymNaviServer=s\nSymNaviUSERID=u\nSymNaviPASSWD=p\nsymnaviserver=t\n',
        '[DEFAULT]\nSymNaviServer=d\n[Default]\nSymNaviUSERID=u\nSymNaviPASSWD=p\n',
        '[Connect_B]\nSymNaviServer : s\nSymNaviUSERID=u\nSymNaviPASSWD=p\n[Connect_A]\nSymNaviServer=a\n',
        '[Z]\nSymNaviServer=s\n  continued\nSymNaviUSERID=u\n\n  after blank\nSymNaviPASSWD=p ; not a comment\n# c\n; c\n',
        '[A]]\nSymNaviServer=s\nSymNaviUSERID=u\nSymNaviPASSWD=p\n','[]\nx=1\n',' [S]\nSymNaviServer=s\n',
        '[S]\r\nSymNaviServer = s\r\nSymNaviUSERID = u\r\nSymNaviPASSWD = p\r\n',
        '[S]\nSymNaviServer=s\nSymNaviUSERID=u\nSymNaviPASSWD=p\n[ApiSQLServer]\nuserid=x\nopt=o\nresourcekind=2\n[api_postgres]\nenabled=OFF\n[API-RDA]\nresourcename=r\n',
        '[S]\nSymNaviServer=s\nSymNaviUSERID=u\nSymNaviPASSWD=p\n[ApiOracle]\nuser=a\n[ApiOracle]\nuser=b\n',
        '[S]\nA=1\na=2\n','[S]\nSymNaviServer=　s　\nSymNaviUSERID=u\nSymNaviPASSWD=p\n']

 def test_same_reading(self):
  exe=core_exe()
  if not exe:raise AssertionError('Rust の答え口がありません')
  calls=[{'fn':'parse_conf','args':{'text':t}} for t in self.TEXTS]
  for t in (UTF8_CONF,CP932_CONF):
   for enc in ('utf-8','cp932'):
    try:calls.append({'fn':'read_conf_text','args':{'bytes':list(t.encode(enc))}})
    except UnicodeEncodeError:pass
  calls+=[{'fn':'read_conf_text','args':{'bytes':list(b'\xef\xbb\xbf'+UTF8_CONF.encode('utf-8'))}},{'fn':'read_conf_text','args':{'bytes':[0x82]}},{'fn':'read_conf_text','args':{'bytes':[0xff,0xfe,0x41]}}]
  env=dict(os.environ,PYTHONIOENCODING='utf-8')
  py=json.loads(run([sys.executable,'-c',PROBE,str(ROOT)],env,json.dumps(calls,ensure_ascii=False)).strip().splitlines()[-1])
  rs=[json.loads(x) for x in run([str(exe),'call'],env,'\n'.join(json.dumps(c,ensure_ascii=False) for c in calls)+'\n').splitlines() if x.strip()]
  bad=[f"{json.dumps(c['args'],ensure_ascii=False)[:120]}\n  PY={p}\n  RS={r}" for c,p,r in zip(calls,py,rs) if p!=r]
  self.assertEqual(bad,[],'\n'.join(bad))


@unittest.skipUnless(sys.platform=='win32','資格情報マネージャーは Windows だけ')
class WindowsVaultCrossTest(unittest.TestCase):
 """本物の資格情報マネージャー（試験用の名前）で、Rust が書いた物を Python が読み、Python が書いた物を Rust が読む。"""
 def test_cross(self):
  exe=core_exe();target=f'DataRelay/Test/{os.getpid()}'
  data={'server':'s','user':'利用者','password':'秘密','section':'','profiles':[],'origin':'test'}
  env=dict(os.environ,PYTHONIOENCODING='utf-8')
  def py(op,**kw):
   r=json.loads(run([sys.executable,'-c',PROBE,str(ROOT)],env,json.dumps([{'fn':'win_vault','args':dict(op=op,target=target,**kw)}],ensure_ascii=False)).strip().splitlines()[-1])[0]
   self.assertTrue(r['ok'],r);return r['result']
  def rs(op,**kw):
   r=json.loads(run([str(exe),'call'],env,json.dumps({'fn':'win_vault','args':dict(op=op,target=target,**kw)},ensure_ascii=False)+'\n').strip())
   self.assertTrue(r['ok'],r);return r['result']
  try:
   rs('save',data=data);self.assertEqual(py('load'),data,'Rust が書いた物を Python が読める')
   py('save',data=dict(data,server='t'));self.assertEqual(rs('load'),dict(data,server='t'),'Python が書いた物を Rust が読める')
   self.assertTrue(rs('delete'));self.assertIsNone(py('load'));self.assertFalse(py('delete'))
  finally:
   try:py('delete')
   except Exception:pass
