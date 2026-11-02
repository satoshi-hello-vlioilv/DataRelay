"""設定の保存（PUT /api/config）と共有のマスターへの書き戻しが、Python（app._save_local・flush_local_to_master）と
Rust（desktop/core の writer.rs）で同じ結果になるか（2.22.0）。

同じ設定の写しを2つ用意し（片方を Python、片方を Rust が受け持つ）、同じ保存の手順（変わった値・対象の追加と削除・
古い版・形の違う本文）を同じ順で流して、答えと、写しの中身（設定・対象・実行ルール・前回の実行・版）と、
書き戻したマスターの中身を比べる。新しく振る id（uuid）は、出てきた順の印に置き換えて比べる。
いま Python が読めば写しを替える場合と、Python が落ちる値は、Rust が書かずに Python へ回すことも確かめる。
書き戻しを SQLite のバックアップの仕組みにしたので、書いている最中に写しても、ひとそろいの写しになることも確かめる。
実行: python -m unittest tests.test_rust_save -v
"""
import json,os,shutil,sqlite3,subprocess,sys,tempfile,threading,unittest
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402
from test_rust_paths import ref_python  # noqa: E402
from test_rust_config import MAKE,full_cfg,layout_sql  # noqa: E402

NOW='2026-11-02T09:05:07.123456'

PUT=r"""
import json,sys,time
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app,navi_web
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
app.datetime=Fixed;navi_web.datetime=Fixed
t=app.app.test_client();out=[]
for q in json.loads(sys.stdin.read()):
 if q['method']=='GET':r=t.get(q['path'])
 else:r=t.put(q['path'],data=q['body'].encode('utf-8'),headers={'Content-Type':q.get('type','application/json')})
 out.append({'status':r.status_code,'body':r.get_data(as_text=True)})
deadline=time.time()+60
while app.settings_flush_pending() and time.time()<deadline:time.sleep(0.05)
print(json.dumps(out))
"""


def dump(db):
 """写しの中身（比べる物だけ）。jobs は並び順、schedules は対象の並び順とルールの並び順。"""
 with closing(sqlite3.connect(str(db))) as c:
  c.row_factory=sqlite3.Row
  order={r['id']:r['display_order'] for r in c.execute('SELECT id,display_order FROM jobs')}
  out={'app_settings':[tuple(r) for r in c.execute('SELECT key,value,value_type,updated_at FROM app_settings ORDER BY key')],
       'jobs':[dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY display_order')],
       'schedules':sorted([dict(r) for r in c.execute('SELECT * FROM schedules')],key=lambda r:(order.get(r['job_id'],999),r['display_order'])),
       'job_runs':[dict(r) for r in c.execute('SELECT job_id,status FROM job_runs ORDER BY job_id')],
       'revision':c.execute("SELECT value FROM schema_info WHERE key='settings_revision'").fetchone()[0]}
 return out


def mask_ids(d,known):
 """新しく振った id を、出てきた順の印へ（Python と Rust で乱数が違うので）。"""
 m={}
 def f(x):
  if x in known or x is None:return x
  m.setdefault(x,f'<new{len(m)+1}>');return m[x]
 for j in d['jobs']:j['id']=f(j['id'])
 for s in d['schedules']:s['id']=f(s['id']);s['job_id']=f(s['job_id'])
 return d


class SaveParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.exe=core_exe()
  if not cls.exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.tmp=tempfile.TemporaryDirectory();cls.t=Path(cls.tmp.name).resolve()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def env(self,name):
  d=self.t/name
  return dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),
              NAVI_CONFIG_DIR=str(d/'data'/'Config'),NAVI_SECRET_FILE=str(d/'s.json'))

 def paths(self,name):
  d=self.t/name
  return d/'local'/'cache'/'app_settings.sqlite3',d/'data'/'Config'/'app_settings.sqlite3'

 def py(self,code,name,stdin,*args):
  r=subprocess.run([ref_python(),'-c',code,str(ROOT),*args],input=stdin,env=self.env(name),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().split('\n')[-1])

 def rust(self,name,reqs):
  lines=''.join(json.dumps({'method':q['method'],'path':q['path'],'query':'','body':q.get('body',''),
                            'headers':{'Content-Type':q.get('type','application/json')}},ensure_ascii=False)+'\n' for q in reqs)
  r=subprocess.run([str(self.exe),'answer','--base',str(ROOT)],input=lines,env=dict(self.env(name),DATARELAY_FIXED_NOW=NOW),cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return [json.loads(x) for x in r.stdout.split('\n') if x.strip()]

 def twin(self,base,a,b):
  """見本 base を a・b へ写す。写しがどのマスターの写しかの記録は、それぞれのマスターへ書き直す（写した先で別のマスターの写しにならないように）。"""
  for n in (a,b):
   shutil.copytree(self.t/base,self.t/n)
   local,master=self.paths(n)
   local.with_name('app_settings.master.txt').write_text(os.path.normcase(os.path.abspath(str(master))),encoding='utf-8')

 def make_base(self,name):
  self.py(MAKE,name,json.dumps({'cfg':full_cfg(''),'sql':layout_sql()+[
   ["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j2','固定名','t','ok','manual','',1,1,'','t','')",[]],
   ["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j1','日次','t','ok','manual','',1,1,'','t','')",[]]]},ensure_ascii=False))
  return self.py(PUT,name,json.dumps([{'method':'GET','path':'/api/config'}]),NOW)[0]

 def test_save_sequence(self):
  cfg=json.loads(self.make_base('base')['body'])
  known={j['id'] for j in cfg['jobs']}|{s['id'] for j in cfg['jobs'] for s in j['schedules']}
  self.twin('base','py','rs')
  b1=json.loads(json.dumps(cfg))
  b1['jobs'][0]['name']='日次（変更）'
  del b1['jobs'][1]                                    # j2 を消す → 前回の実行（job_runs）も消える
  b1['jobs'].append({'name':'新しい対象','rne':'n.RNE','output_format':'Excel','output_file':'n.csv','extra_formats':'csv, txt',
                     'index_columns':[' a ',1,None,'b','c','d','e'],'row_axis_index':'5','row_axis_mode':' Name ','split_mode':' FORCE ',
                     'period':{'enabled':True,'target':'cond','from_offset':'-7'},'variants':{'values':['東京','東京',' 大阪 ']},'group':' 新 / 月次 ',
                     'schedules':[{'type':'weekly','weekdays':[1,3]},{'name':'間隔','type':'interval','interval_minutes':'0'},{'type':'dates','dates':['2026-12-01'],'interval_minutes':'x'}]})
  b1['jobs'][0]['schedules'].append({'type':'monthly','month_days':[-1],'interval_minutes':7.9})
  b1.update({'note':None,'num':2.5,'flag':False,'list':[1,'a',{'k':'v'}],'text':'改行\n"引用"','big':12345})
  b2=dict(b1,settings_revision=1)                      # 古い版 → 409
  b3=json.loads(json.dumps(b1));b3.pop('settings_revision')
  b3['jobs']=b3['jobs'][:1];b3['jobs'][0]['enabled']=0  # 版を載せない（古い画面）→ 確かめずに保存
  reqs=[{'method':'PUT','path':'/api/config','body':json.dumps(b1,ensure_ascii=False)},
        {'method':'PUT','path':'/api/config','body':json.dumps(b2,ensure_ascii=False)},
        {'method':'PUT','path':'/api/config','body':json.dumps({'settings':{}},ensure_ascii=False)},
        {'method':'PUT','path':'/api/config','body':'[1]'},
        {'method':'PUT','path':'/api/config','body':'{bad'},
        {'method':'PUT','path':'/api/config','body':json.dumps(b1,ensure_ascii=False),'type':'text/plain'},
        {'method':'PUT','path':'/api/config','body':json.dumps(b3,ensure_ascii=False)}]
  py=self.py(PUT,'py',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('rs',reqs)
  for q,p,x in zip(reqs,py,rs):
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {q["body"][:80]}')
   self.assertEqual((x['status'],json.loads(x['body'])),(p['status'],json.loads(p['body'])),q['body'][:120])
  self.assertEqual([p['status'] for p in py],[200,409,400,400,400,400,200])
  a,b=(mask_ids(dump(self.paths(n)[0]),known) for n in ('py','rs'))
  for k in a:self.assertEqual(a[k],b[k],f'写しの {k} が違う')
  self.assertEqual(a['job_runs'],[{'job_id':'j1','status':'ok'}],'消した対象の前回の実行は消える')
  # 書き戻したマスターは、写しと同じ中身
  for n in ('py','rs'):
   local,master=self.paths(n)
   self.assertEqual(mask_ids(dump(master),known),mask_ids(dump(local),known),f'{n}: マスターが写しと同じでない')
   # 更新時刻も写しと同じ（版が両側とも無いとき、取り込みは更新時刻で新旧を決めるため。shutil.copy2 と同じ）
   self.assertEqual(os.stat(master).st_mtime_ns,os.stat(local).st_mtime_ns,f'{n}: マスターの更新時刻が写しと違う')
  # Python は Rust が書いた写しをそのまま読める（画面の読み出しが同じ）
  ga=self.py(PUT,'py',json.dumps([{'method':'GET','path':'/api/config'}]),NOW)[0]
  gb=self.py(PUT,'rs',json.dumps([{'method':'GET','path':'/api/config'}]),NOW)[0]
  ja,jb=json.loads(ga['body']),json.loads(gb['body'])
  self.assertEqual(len(ja['jobs']),len(jb['jobs']));self.assertEqual(ja['settings'],jb['settings'])

 def test_python_only_cases(self):
  """Python が落ちる値（名前が辞書・実行ルールが字）と、写しを替える場合（マスターが無い）は、Rust は書かずに Python へ回す。"""
  cfg=json.loads(self.make_base('base2')['body'])
  self.twin('base2','p2','r2')
  before=dump(self.paths('r2')[0])
  bad1=dict(cfg,jobs=[dict(cfg['jobs'][0],name={'x':1})])
  bad2=dict(cfg,jobs=[dict(cfg['jobs'][0],schedules='abc')])
  bad3=dict(cfg,jobs=[dict(cfg['jobs'][0],row_axis_index='x')])
  reqs=[{'method':'PUT','path':'/api/config','body':json.dumps(b,ensure_ascii=False)} for b in (bad1,bad2,bad3)]
  self.assertEqual([x['status'] for x in self.rust('r2',reqs)],[0,0,0])
  self.assertEqual(dump(self.paths('r2')[0]),before,'回したときは何も書かない')
  self.assertEqual([p['status'] for p in self.py(PUT,'p2',json.dumps(reqs,ensure_ascii=False),NOW)],[500,500,500])
  os.remove(self.paths('r2')[1])
  self.assertEqual(self.rust('r2',[{'method':'PUT','path':'/api/config','body':json.dumps(cfg,ensure_ascii=False)}])[0]['status'],0)

 def test_flush_snapshot_while_writing(self):
  """Python の書き戻しの写し方（snapshot_db）は、ほかの接続が書いている最中でも、ひとそろいの写しになる。"""
  with tempfile.TemporaryDirectory() as d:
   src,dst=Path(d)/'s.sqlite3',Path(d)/'d.sqlite3'
   with closing(sqlite3.connect(str(src))) as c,c:
    c.execute('CREATE TABLE t(n INTEGER)');c.execute('CREATE TABLE u(n INTEGER)')
   stop=threading.Event()
   def writer():
    with closing(sqlite3.connect(str(src),timeout=30)) as c:
     i=0
     while not stop.is_set():
      i+=1
      with c:c.execute('INSERT INTO t VALUES(?)',(i,));c.execute('INSERT INTO u VALUES(?)',(i,))
   th=threading.Thread(target=writer);th.start()
   code="import sys;sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib'];import app;[app.snapshot_db(sys.argv[2],sys.argv[3]) for _ in range(30)];print('[]')"
   try:self.py(code,'snap','',str(src),str(dst))
   finally:stop.set();th.join()
   with closing(sqlite3.connect(str(dst))) as c:
    self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0],'ok')
    self.assertEqual(c.execute('SELECT COUNT(*) FROM t').fetchone()[0],c.execute('SELECT COUNT(*) FROM u').fetchone()[0],'2つの表が同じ取引の途中で写っていない')


if __name__=='__main__':unittest.main()
