"""置き場・データの基準・道の読み方が、Python（navi_paths・navi_release）と Rust（desktop/core/src/paths.rs）で同じか（2.16.0）。

ルートの突き合わせ（test_rust_parity.py）だけでは、フォルダーの状態で答えが変わる決まり（データの基準の決める順・
相対パスの基準に無い物をほかの基準から使う・置き場の直し方）を一通り確かめられない。ここでいろいろなフォルダーの状態を作り、
同じ問いを Python の関数と Rust の関数（datarelay-core call）へ出して、答えを比べる。
実行: python -m unittest tests.test_rust_paths -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402

PY=r"""
import json,sys
sys.path[:0]=[sys.argv[1]+'/lib']
from pathlib import Path
import navi_paths as P,navi_release as R
def setup(b):
 P.setup(b['data_root'],b['local_root'],b['program_root'],b['data_source']);P.set_place(b.get('place'))
def s(x):return None if x is None else str(x)
out=[]
for q in json.loads(sys.stdin.read()):
 f,a=q['fn'],q['args']
 try:
  if f=='data_root':r=list(map(str,P.data_root(a['base'],a.get('env',{}),a.get('place'))))
  elif f=='update_dir':r=list(map(str,R.dir_choice(a['app_root'],a.get('shared') if a.get('shared') is not None else str(P.read_json(Path(a['app_root'])/'config'/R.MIRROR).get(R.CONFIG_KEY) or '').strip())))
  elif f=='release_root':r=str(R.release_root(Path(a['path']))[0])
  elif f=='path_kind':r=P.path_kind(a['value'])
  elif f=='expand':r=P.expand(a['value'])
  elif f=='portable':r=P.portable(a['value'],Path(a['home']) if a.get('home') else None)
  elif f=='users_root':r=str(P.users_root(a['place']))
  elif f=='user_dir':r=s(P.user_dir(a.get('place'),a.get('env',{})))
  elif f=='logon_name':r=P.logon_name(a.get('env',{}))
  elif f=='py_path':r=str(Path(a['value']))
  elif f=='resolve':r=str(Path(a['value']).resolve())
  else:
   setup(a['bases'])
   if f=='rel_bases':r=[str(x) for x in P.rel_bases()]
   elif f=='resolve_path':r=str(P.resolve_path(a.get('value'),a.get('base')))
   elif f=='resolve_in':r=str(P.resolve_in(a['value'],a.get('folder')))
   elif f=='locate':r=P.locate(a['value'],a.get('folder'))
   elif f=='to_relative':r=P.to_relative(a['path'],a.get('inside_only',False))
   else:raise KeyError(f)
  out.append({'ok':True,'result':r})
 except Exception as e:out.append({'ok':False,'error':f'{type(e).__name__}: {e}'})
print(json.dumps(out,ensure_ascii=False))
"""


def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')


class RustPathsTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  exe=core_exe()
  if not exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.tmp=tempfile.TemporaryDirectory();t=Path(cls.tmp.name).resolve()
  cls.calls=[];cls.build(t)
  env=dict(os.environ,DR_A=str(t/'envA'),DR_B='bee',PYTHONIOENCODING='utf-8');env.pop('NAVI_DATA_ROOT',None)
  def run(cmd,stdin):
   r=subprocess.run(cmd,input=stdin,env=env,cwd=str(t),capture_output=True,text=True,encoding='utf-8',timeout=120)
   if r.returncode:raise AssertionError(r.stderr[-3000:])
   return r.stdout
  cls.py=json.loads(run([sys.executable,'-c',PY,str(ROOT)],json.dumps(cls.calls,ensure_ascii=False)).strip().splitlines()[-1])
  rs=run([str(exe),'call'],'\n'.join(json.dumps({'fn':c['fn'],'args':c['args']},ensure_ascii=False) for c in cls.calls)+'\n')
  cls.rs=[json.loads(x) for x in rs.splitlines() if x.strip()]

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 @classmethod
 def add(cls,fn,**args):cls.calls.append({'fn':fn,'args':args})

 @classmethod
 def build(cls,t):
  """フォルダーの状態をいくつも作り、問いを並べる。"""
  me={'USERNAME':'tanaka'}
  # ---- データの基準の決める順（env／local／user／pc／install／app） ----
  def app(name,local=None,seed=None,mine_mark=False):
   a=t/name/'app';(a/'config').mkdir(parents=True,exist_ok=True)
   if local is not None:write(a/'config'/'local.json',local)
   if seed is not None:write(a/'config'/'install.json',seed)
   if mine_mark:write(a/'data'/'data.json','{}')
   return a
  place=t/'place';(place/'users').mkdir(parents=True)
  write(place/'users'/'tanaka'/'data.json','{}')
  place2=t/'place2';place2.mkdir()                          # 誰の印も無い置き場
  place3=t/'place3';write(place3/'config'/'install.json',json.dumps({'users_root':'%DR_A%\\people'}))
  for name,kw,pl,env in [
   ('env',{},None,{'NAVI_DATA_ROOT':' %DR_A%\\d '}),
   ('local',{'local':json.dumps({'data_root':'%DR_A%/x/'})},None,me),
   ('localbom',{'local':'\ufeff'+json.dumps({'data_root':'~/y'})},None,me),
   ('localbad',{'local':'{bad'},None,me),
   ('localnum',{'local':json.dumps({'data_root':5})},None,me),
   ('locallist',{'local':'[1]'},None,me),
   ('user_marked',{'seed':'{}'},place,me),
   ('user_new',{'seed':'{}'},place2,me),
   ('pc_marked',{'seed':'{}','mine_mark':True},place2,me),
   ('pc_vs_user',{'seed':'{}','mine_mark':True},place,me),
   ('install',{'seed':json.dumps({'data_root':'%DR_A%\\shared'})},place2,me),
   ('noplace_install',{'seed':json.dumps({'data_root':'\\\\srv\\share\\d'})},None,me),
   ('noplace_pc',{'seed':'{}'},None,me),
   ('noname',{'seed':'{}'},place,{}),
   ('badname',{'seed':'{}'},place,{'USERNAME':' ta:na*ka. '}),
   ('usersroot',{'seed':'{}'},place3,me),
   ('missingplace',{'seed':'{}'},t/'nowhere',me),
   ('plain',{},None,me),
  ]:
   cls.add('data_root',base=str(app(name,**kw)),env=env,place=str(pl) if pl else None)
  # ---- 置き場（local → 共有の設定 → 入れた元 → アプリ。versions は根へ直す） ----
  for name,files,shared in [
   ('u_local',{'local.json':json.dumps({'update_dir':str(t/'S'/'versions')}),'update.json':json.dumps({'update_dir':'x'})},None),
   ('u_mirror',{'update.json':json.dumps({'update_dir':str(t/'S'/'versions'/'1.98.0')})},None),
   ('u_shared',{'update.json':json.dumps({'update_dir':'x'})},'%DR_A%\\versions'),
   ('u_seed',{'install.json':json.dumps({'from':str(t/'S'/'versions'/'作業')})},None),
   ('u_none',{},None),
   ('u_blank',{'local.json':json.dumps({'update_dir':'  '})},' '),
  ]:
   a=t/name;(a/'config').mkdir(parents=True)
   for fn,text in files.items():write(a/'config'/fn,text)
   cls.add('update_dir',app_root=str(a),shared=shared)
  for p in ['/s/versions','/s/VERSIONS/1.2.3','/s/versions/x','/s/old/1.98.0','C:\\s\\versions\\2.0.0','versions']:cls.add('release_root',path=p)
  # ---- 書き方・展開・持ち運べる書き方 ----
  for v in ['','<PC>\\x','%DR_A%\\x','%NOPE%\\x','%%x','~','~/x','~x','$DR_B/x','${DR_B}x','$NOPE','\\\\s\\x','C:\\x','c:/x','/x','\\x','.\\rne','X.RNE',' 50% ',"'%DR_B%'"]:
   cls.add('path_kind',value=v);cls.add('expand',value=v)
  for v,h in [('C:\\Users\\me\\Box\\x','C:\\Users\\me'),('c:/users/ME/a','C:\\Users\\me'),('C:\\Users\\you\\Box','C:\\Users\\me'),('D:\\x','C:\\Users\\me'),('%APPDATA%\\x','C:\\Users\\me'),('',None)]:
   cls.add('portable',value=v,home=h)
  cls.add('users_root',place=str(place));cls.add('users_root',place=str(place3))
  for pl,env in [(place,me),(place2,{'USER':'u2'}),(t/'nowhere',me),(None,me),(place,{'USERNAME':'','USER':'fallback'})]:
   cls.add('user_dir',place=str(pl) if pl else None,env=env)
  for env in [me,{'USERNAME':'a/b\\c'},{'USER':'x'},{}]:cls.add('logon_name',env=env)
  for v in ['a//b/./c/','./','','a/../b','//a/b','///a','C:/a/b/','x\\y']:cls.add('py_path',value=v)
  # ---- 相対パスの基準と道の読み方 ----
  pl=t/'B'/'place';data=t/'B'/'data';prog=t/'B'/'prog';local=t/'B'/'local'
  write(pl/'rne'/'A.RNE','a');write(data/'rne'/'D.RNE','d');write(prog/'assets'/'empty.accdb','x');(local/'backup').mkdir(parents=True)
  (pl/'text').mkdir(parents=True)
  for src,place_ in [('user',pl),('pc',pl),('local',pl),('env',pl),('install',None),('pc',None),('app',None)]:
   b={'data_root':str(data),'data_source':src,'local_root':str(local),'program_root':str(prog),'place':str(place_) if place_ else None}
   cls.add('rel_bases',bases=b)
  b={'data_root':str(data),'data_source':'user','local_root':str(local),'program_root':str(prog),'place':str(pl)}
  same={'data_root':str(pl),'data_source':'user','local_root':str(local),'program_root':str(prog),'place':str(pl)}
  values=['.\\rne\\A.RNE','.\\rne\\D.RNE','rne/D.RNE','.\\assets\\empty.accdb','.\\rne\\none.RNE','..\\B\\data\\rne\\D.RNE','<PC>','<PC>\\backup','<PC>/backup/x',
          '%DR_A%\\q',str(pl/'rne'/'A.RNE'),'\\\\srv\\share\\x','','  ','.','X.RNE','text']
  for bb in (b,same):
   cls.add('resolve_path',bases=bb,value=None)
   for v in values:
    cls.add('resolve_path',bases=bb,value=v)
    cls.add('locate',bases=bb,value=v)
    for folder in (None,'','.\\rne','rne',str(data/'rne'),'<PC>\\backup'):cls.add('locate',bases=bb,value=v,folder=folder);cls.add('resolve_in',bases=bb,value=v,folder=folder)
   cls.add('resolve_path',bases=bb,value='A.RNE',base=str(pl/'rne'))
   for p in [pl/'rne'/'A.RNE',data/'rne'/'D.RNE',pl,pl/'none'/'x.txt',t/'elsewhere',prog/'assets'/'empty.accdb']:
    cls.add('to_relative',bases=bb,path=str(p));cls.add('to_relative',bases=bb,path=str(p),inside_only=True)

 def test_same_answers(self):
  self.assertEqual(len(self.py),len(self.calls));self.assertEqual(len(self.rs),len(self.calls))
  bad=[]
  for c,p,r in zip(self.calls,self.py,self.rs):
   if not p['ok']:bad.append(f"{c['fn']} {json.dumps(c['args'],ensure_ascii=False)[:200]}: Python が失敗 {p['error']}");continue
   if not r['ok'] or p['result']!=r['result']:
    bad.append(f"{c['fn']} {json.dumps({k:v for k,v in c['args'].items() if k!='bases'},ensure_ascii=False)[:200]}\n   Python={json.dumps(p['result'],ensure_ascii=False)[:500]}\n   Rust  ={json.dumps(r.get('result',r.get('error')),ensure_ascii=False)[:500]}")
  self.assertEqual(bad,[],f'{len(bad)}/{len(self.calls)}件で Python と Rust の答えが違う:\n'+'\n'.join(bad[:30]))

 def test_wide(self):
  self.assertGreater(len(self.calls),500)
