"""記録の読み出し（GET /api/log）が、Python（navi_web.get_log・app.read_log_lines）と Rust（desktop/core の applog.rs）で同じか（2.18.0）。

Python の中身は動いている間も自分の app.log へ書き続けるので、同じファイルを読ませると答えがずれる。そこで、比べるための
記録の置き場（見本）を別に作り、Python には読む場所だけをそこへ向けさせ（app.LOG_PATH・navi_log の置き場）、
Rust には NAVI_LOCAL_ROOT でそこを渡して、同じ見本を読み比べる。行の区切り（\r・\x85・  など）・壊れた UTF-8・
4MB を超える記録・前の世代の並べ方・絞り込み・検索（正規表現と、読めない正規表現）・行数の上限を確かめる。
Rust が書く行が、Python の読み方（画面の「ログ」）で読めることも確かめる。
実行: python -m unittest tests.test_rust_log -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402

PY=r"""
import json,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_log
logs=Path(sys.argv[2])
app.LOG_PATH=logs/'app.log';navi_log.LOG_PATH=logs/'app.log';navi_log.LOCAL_LOGS=logs
t=app.app.test_client();out=[]
for q in json.loads(sys.stdin.read()):
 r=t.get('/api/log'+(('?'+q) if q else ''))
 out.append({'status':r.status_code,'body':r.get_data(as_text=True)})
print(json.dumps(out,ensure_ascii=False))
"""

LINES=['2026-11-01 09:00:00,001 [INFO] [pid 10] APP_START version=2.18.0',
       '2026-11-01 09:00:01,002 [WARNING] [pid 10] SLOW elapsed=3s',
       '2026-11-01 09:00:02,003 [ERROR] [pid 11] 抽出に失敗しました エラー',
       '2026-11-01 09:00:03,004 [INFO] [pid 11] SPLIT_PLAN rows=5',
       '2026-11-01 09:00:04,005 [INFO] [pid 12] COLUMN_SPLIT a+b (x)',
       '2026-11-01 09:00:05,006 [INFO] [pid 12] Error in lower Case']
QUERIES=['','limit=3','limit=0','limit=-5','limit=abc','limit=99999','limit=+2','limit=%201%20','filter=problem','filter=split','filter=unknown',
         'q=error','q=ERROR','q=%E3%82%A8%E3%83%A9%E3%83%BC','q=(','q=a%2Bb','q=a+b','q=(%3F%3D.*pid%2012)','q=%5B','q=pid+1[01]','q=++',
         'filter=problem&q=pid%2011','limit=1&filter=split','q=%E6%8A%BD%E5%87%BA&limit=1']


def fixture(root,name,make):
 d=root/name/'local'/'logs';d.mkdir(parents=True);make(d);return root/name/'local'


class LogReadParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.exe=core_exe()
  if not cls.exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.tmp=tempfile.TemporaryDirectory();cls.t=Path(cls.tmp.name).resolve()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def compare(self,name,make,queries=QUERIES):
  local=fixture(self.t,name,make)
  own=self.t/name/'python-own'   # Python 自身の記録の置き場（見本とは別）
  base=dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_DATA_ROOT=str(own/'data'),NAVI_CONFIG_DIR=str(own/'data'/'Config'),
            NAVI_SECRET_FILE=str(own/'s.json'))
  r=subprocess.run([sys.executable,'-c',PY,str(ROOT),str(local/'logs')],input=json.dumps(queries),env=dict(base,NAVI_LOCAL_ROOT=str(own/'local')),
                   cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  py=json.loads(r.stdout.strip().splitlines()[-1])
  lines='\n'.join(json.dumps({'method':'GET','path':'/api/log','query':q,'body':''}) for q in queries)+'\n'
  r=subprocess.run([str(self.exe),'answer','--base',str(ROOT)],input=lines,env=dict(base,NAVI_LOCAL_ROOT=str(local)),cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  rs=[json.loads(x) for x in r.stdout.splitlines() if x.strip()]
  bad=[]
  for q,p,x in zip(queries,py,rs):
   if x['status']!=p['status']:bad.append(f'{q!r}: 番号 Python={p["status"]} Rust={x["status"]}');continue
   a,b=json.loads(p['body']),json.loads(x['body'])
   if a!=b:bad.append(f'{q!r}:\n  PY={json.dumps({k:a[k] for k in a if a.get(k)!=b.get(k)},ensure_ascii=False)[:500]}\n  RS={json.dumps({k:b.get(k) for k in a if a.get(k)!=b.get(k)},ensure_ascii=False)[:500]}')
  self.assertEqual(len(rs),len(queries))
  self.assertEqual(bad,[],f'{name}: '+'\n'.join(bad))
  return py

 def test_lines_filters_and_search(self):
  def make(d):
   body=('\r\n'.join(LINES[:2])+'\r'+LINES[2]+'\x85'+LINES[3]+' '+LINES[4]+'\n\n'+LINES[5]+'\n').encode('utf-8')
   (d/'app.log').write_bytes(body+b'2026-11-01 09:00:06,007 [INFO] [pid 13] broken \xff\xfe bytes\n')
   for n,size in (('app.1.log',1000),('app.2.log',300000),('app.10.log',10),('app.x.log',5),('app.a3b.log',7)):(d/n).write_bytes(b'x'*size)
   (d/'app.log.bak').write_text('not a generation',encoding='utf-8');(d/'app.5.log').mkdir()
  py=self.compare('mixed',make)
  first=json.loads(py[0]['body'])
  self.assertEqual(first['total'],8,'\\r\\n・\\r・\\x85・\\u2028・空の行も Python と同じ数え方')
  self.assertEqual([o['name'] for o in first['older']],['app.x.log','app.1.log','app.2.log','app.a3b.log','app.10.log'],'前の世代は番号順（字の中の数字を拾う。数の無い名前は 0）・フォルダーは数えない')

 def test_big_log_is_clipped(self):
  """4MB を超える記録は末尾だけ。途中から読んだ最初の半端な行は捨てる。"""
  def make(d):
   line=('2026-11-01 10:00:00,000 [INFO] [pid 1] '+'あ'*60+'\n').encode('utf-8')
   (d/'app.log').write_bytes(b'head\n'+line*int(4.6*1024*1024/len(line)))
  py=self.compare('big',make,['','limit=5000','q=pid+1&limit=2'])
  v=json.loads(py[0]['body'])
  self.assertTrue(v['clipped']);self.assertGreater(v['size_mb'],4.0)

 def test_no_current_log(self):
  self.compare('none',lambda d:(d/'app.3.log').write_text('old',encoding='utf-8'),['','q=x'])


class LogWriteTest(unittest.TestCase):
 def test_rust_lines_read_like_python_lines(self):
  """Rust が書いた行（接続情報を消した記録）を、Python の読み方（画面の「ログ」の絞り込み）で読める。"""
  exe=core_exe()
  with tempfile.TemporaryDirectory() as d:
   d=Path(d)
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_SECRET_FILE=str(d/'s.json'),PYTHONIOENCODING='utf-8')
   r=subprocess.run([str(exe),'answer','--base',str(ROOT)],input=json.dumps({'method':'POST','path':'/api/login/delete','query':'','body':''})+'\n',
                    env=env,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=60)
   self.assertEqual(r.returncode,0,r.stderr)
   text=(d/'local'/'logs'/'app.log').read_text(encoding='utf-8')
  import re
  self.assertRegex(text,r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[INFO\] \[pid \d+\] LOGIN_DELETED removed=False vault=file\n$',
                   'Python の logging と同じ形（時刻・[LEVEL]・[pid N]）')
  # 古い記録を消す（/api/log/delete-old）が読む時刻の書き方とも合う
  from datetime import datetime
  datetime.strptime(text[:23],'%Y-%m-%d %H:%M:%S,%f')
  self.assertTrue(re.search(r'\[ERROR\]|\[WARNING\]','x [WARNING] y'))
