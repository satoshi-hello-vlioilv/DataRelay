"""共有の写し方の約束（docs/SHARED_READ.md）——書き手（公開・lib/navi_publish.py）と読み手（ビュワー・lib/navi_localcopy.py）。

WaveLog（tests/test_dbmirror.py）・Quality-Analysis（program/tests/test_mirror_writer.py）と同じ約束を、このアプリの側で確かめる。
Windows の「開いているファイルは置き換えられない」は Linux では起きないので、ここで見るのは**作法**（いつ開くか・
目印を出すか・何を使うか）。置き換えそのものの確かめは Windows の CI。

実行: python -m unittest tests.test_shared_read -v
"""
import os,shutil,sqlite3,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_localcopy as LC
import navi_publish as PB


def make_db(path,n):
 path=Path(path);tmp=path.with_name(path.name+'.build')
 c=sqlite3.connect(tmp);c.execute('CREATE TABLE V (n INTEGER)');c.execute('INSERT INTO V VALUES (?)',(n,));c.commit();c.close()
 os.replace(tmp,path)


class Base(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());(self.tmp/'share').mkdir()
  self.dst=self.tmp/'share'/'設備単位実績.sqlite3'
  make_db(self.dst,1)
  LC.setup(self.tmp/'local')
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)


class Contract(unittest.TestCase):
 def test_document_names_this_version(self):
  """約束の文書（3つのリポジトリに同じ文）が、書き手・読み手の実装の従う版を名乗り、決まりを全部持つ。"""
  doc=(ROOT/'docs'/'SHARED_READ.md').read_text(encoding='utf-8')
  self.assertEqual(LC.CONTRACT_VERSION,PB.CONTRACT_VERSION)
  self.assertIn(f'（第{LC.CONTRACT_VERSION}版）',doc.splitlines()[0])
  for r in [f'R{i}' for i in range(1,10)]+['W1','W2','W3']:self.assertIn(f'| {r} |',doc)


class Reader(Base):
 def test_copy_and_reuse_without_opening(self):
  """R1・R2・R7: 写して読み、同じ版のあいだは共有を開かない。版が変わったら別の名前の写し。"""
  a=LC.read_copy(self.dst)
  self.assertNotEqual(a,self.dst);self.assertTrue(str(a).startswith(str(LC.cache_dir())))
  with mock.patch.object(LC,'open_shared_read',side_effect=AssertionError('共有を開いた')):
   self.assertEqual(LC.read_copy(self.dst),a)
  make_db(self.dst,2)
  b=LC.read_copy(self.dst)
  self.assertNotEqual(a,b)
  with sqlite3.connect(f'file:{b.as_posix()}?mode=ro',uri=True) as c:self.assertEqual(c.execute('SELECT n FROM V').fetchone()[0],2)

 def test_does_not_open_while_publishing(self):
  """R3・R8: 公開の途中（.incoming）なら共有を開かず、理由を言って断る（直接開いた場所を返さない）。"""
  (self.dst.parent/f'.{self.dst.name}.4242.incoming').write_bytes(b'x')
  with mock.patch.object(LC,'open_shared_read',side_effect=AssertionError('共有を開いた')):
   with self.assertRaises(LC.NotCopiedYet) as cm:LC.read_copy(self.dst)
  self.assertIn('公開している途中',str(cm.exception))

 def test_too_big_is_refused_not_opened(self):
  """R8: 大きすぎる出力も直接は開かない（以前は 256MB を超えると直接開いていた）。"""
  with mock.patch.object(LC,'READ_COPY_BYTES',10),mock.patch.object(LC,'open_shared_read',side_effect=AssertionError('共有を開いた')):
   with self.assertRaises(LC.NotCopiedYet) as cm:LC.read_copy(self.dst)
  self.assertIn('直接開きません',str(cm.exception))

 def test_discards_when_source_moves_or_writer_starts(self):
  """R5: 写している間に公開先が変わった・書き手の印が出たら、その写しは使わない（.tmp も残さない）。"""
  real=LC.open_shared_read
  def touch_then_open(p):
   st=os.stat(p);os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns+5_000_000_000));return real(p)
  with mock.patch.object(LC,'open_shared_read',touch_then_open):
   with self.assertRaises(LC.NotCopiedYet) as cm:LC.read_copy(self.dst)
  self.assertIn('入れ替わりました',str(cm.exception))
  def journal_then_open(p):
   (self.dst.parent/f'{self.dst.name}-journal').write_bytes(b'j');return real(p)
  with mock.patch.object(LC,'open_shared_read',journal_then_open):
   with self.assertRaises(LC.NotCopiedYet) as cm:LC.read_copy(self.dst)
  self.assertIn('書き始めました',str(cm.exception))
  self.assertEqual([p.name for p in LC.cache_dir().glob('*.tmp')],[])

 def test_corrupt_is_refused(self):
  """R6: 壊れた SQLite3 からは写しを作らない。"""
  self.dst.write_bytes(b'SQLite format 3\x00'+b'\xff'*4096)
  with self.assertRaises(LC.NotCopiedYet) as cm:LC.read_copy(self.dst)
  self.assertIn('正しくない',str(cm.exception))

 def test_one_copy_at_a_time(self):
  """R9: 同じ公開先を同時に2本写さない（ビュワーは threaded=True で動く）。"""
  real=LC.open_shared_read;active=[0];peak=[0];lock=threading.Lock()
  class Slow:
   def __init__(s,f):s.f=f
   def __enter__(s):
    with lock:active[0]+=1;peak[0]=max(peak[0],active[0])
    time.sleep(0.1);return s.f.__enter__()
   def __exit__(s,*a):
    with lock:active[0]-=1
    return s.f.__exit__(*a)
  with mock.patch.object(LC,'open_shared_read',lambda p:Slow(real(p))):
   ths=[threading.Thread(target=LC.read_copy,args=(self.dst,)) for _ in range(3)]
   [t.start() for t in ths];[t.join() for t in ths]
  self.assertEqual(peak[0],1)

 def test_shared_open_allows_replace_on_windows(self):
  """R4: Windows では置き換えを許す開き方（FILE_SHARE_DELETE まで）で開く。"""
  import inspect
  src=inspect.getsource(LC.open_shared_read)
  self.assertIn('_SHARE_ALL',src);self.assertIn('CreateFile',src)
  self.assertEqual(LC._SHARE_ALL,0x7)


class Writer(Base):
 def setUp(self):
  super().setUp()
  PB.setup(self.tmp/'local',self.tmp/'local'/'backup')

 def publish(self,src,**kw):
  return PB.publish(src,self.dst,self.tmp/'backup',3,backup_enabled=False,**kw)

 def test_mark_is_out_before_replace_and_grace_is_kept(self):
  """W1・W2: 置き換える前に目印（.incoming）があり、目印を出してから3秒は置き換えない。"""
  built=self.tmp/'built.sqlite3';make_db(built,2)
  seen={};real=os.replace
  def watching(a,b):
   if Path(b)==self.dst:seen['mark']=Path(a).name;seen['marks']=LC.writer_marks(self.dst);seen['at']=time.time()
   return real(a,b)
  t0=time.time()
  with mock.patch.object(PB.os,'replace',watching):r=self.publish(built)
  self.assertTrue(r['published'])
  self.assertTrue(seen['mark'].startswith(f'.{self.dst.name}.') and seen['mark'].endswith('.incoming'),seen)
  self.assertEqual(seen['marks'],[seen['mark']],'読み手から目印が見える')
  self.assertGreaterEqual(seen['at']-t0,PB.MARK_GRACE_SECONDS-0.05,'目印を出してから3秒は置き換えない')

 def test_pending_is_applied_through_the_mark(self):
  """W1: 保留の版を入れるときも、目印の名前へ移してから置き換える。"""
  pending=self.dst.parent/f'{self.dst.stem}.pending_20261011_120000{self.dst.suffix}';make_db(pending,3)
  seen={};real=os.replace
  def watching(a,b):
   if Path(b)==self.dst:seen['from']=Path(a).name
   return real(a,b)
  with mock.patch.object(PB.os,'replace',watching):self.assertEqual(PB.apply_pending(self.dst,self.tmp/'backup',3,backup_enabled=False),pending)
  self.assertTrue(seen['from'].endswith('.incoming'),seen)
  self.assertFalse(pending.exists())

 def test_pending_survives_when_still_busy(self):
  """W1・W3: 保留の版を入れられなければ、保留の名前へ戻す（目印のまま消さない）。"""
  pending=self.dst.parent/f'{self.dst.stem}.pending_20261011_120000{self.dst.suffix}';make_db(pending,3)
  real=os.replace
  def busy(a,b):
   if Path(b)==self.dst:
    e=PermissionError(13,'使用中');e.winerror=32;raise e
   return real(a,b)
  with mock.patch.object(PB,'REPLACE_DEADLINE_SECONDS',0.3),mock.patch.object(PB,'MARK_GRACE_SECONDS',0.0),\
       mock.patch.object(PB.os,'replace',busy),mock.patch.object(PB,'_wait',lambda *a:time.sleep(0.05)):
   self.assertIsNone(PB.apply_pending(self.dst,self.tmp/'backup',3,backup_enabled=False))
  self.assertTrue(pending.exists(),'保留の版は残る')
  self.assertEqual(LC.writer_marks(self.dst),[],'目印は残さない')


if __name__=='__main__':
 unittest.main()
