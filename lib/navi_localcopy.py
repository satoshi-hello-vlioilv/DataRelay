"""共有の上にあるファイルを、いったんこのPCのローカルへ写してから読む。

理由は2つある。

1つは速さ。結合の相手も、ビュワーで開くファイルも、たいてい共有フォルダーの上に
ある。組み立てている間はキーを1つ変えるたびに全部を読み直すので、8ファイルなら
8往復、共有が混んでいれば1回の下読みで何十秒も待たされる。

もう1つが本題で、こちらのほうが重い ―― 読むために開くと、そのファイルは
「使用中」になる。Windowsでは、誰かが開いているファイルは os.replace で差し替え
られない。つまり、自分のビュワーで見ているせいで、自分の公開が失敗しうる。
実際そうなっていた（SQLite3の出力を共有から直接開いていた）。写してから読めば、
共有のファイルには一度も触らない。見ている間に公開されても、見ている中身は壊れない。

写し方は形式で違う。
  CSV・TXT・固定長テキスト … 先頭だけを行の切れ目で切って写す（組み立てには十分）
  EXCEL・SQLite3・ACCESS   … 途中で切ると壊れるので、丸ごと。大きすぎるものは写さない

写しはあくまで「読むため」のもので、実行のときは使わない。本番は元のファイルを
最初から最後まで読む ―― ここを取り違えると、静かに中途半端なファイルが出来上がって
しまう。呼び分けは navi_joinrun 側で分けてある。

app.py から分けてある。本体の状態は一切見ない（受け取るのはローカル領域の場所だけ）。
"""
import hashlib,json,os,shutil,threading,time
from pathlib import Path
from navi_log import log

# 先頭だけ写す形式と、丸ごとでないと壊れる形式。
PREFIX_FORMATS=('csv','txt','fixed')
WHOLE_FORMATS=('xlsx','sqlite3','accdb')
# 先頭だけ写すときの上限。数千行は入るので、列を選ぶにもキーを見当付けるにも足りる。
PREFIX_BYTES=4*1024*1024
# 丸ごと写すときの上限。これを超えるものは写さない（写すほうが高くつく）。
WHOLE_BYTES=64*1024*1024
# 写しの置き場が際限なく太らないための上限。古いものから捨てる。
CACHE_TOTAL_BYTES=512*1024*1024

LOCAL_ROOT=None
def setup(local_root):
 """このPCのローカル領域を決める。app.py から一度だけ呼ぶ。"""
 global LOCAL_ROOT
 LOCAL_ROOT=Path(local_root)

def cache_dir():
 d=(LOCAL_ROOT or Path('.'))/'work'/'read-cache';d.mkdir(parents=True,exist_ok=True);return d

def _key(path,st,want):
 """同じ元ファイルには同じ名前。大きさと更新日時も混ぜるので、差し替われば別物になる。

 どこまで写すか（want）も混ぜる。上限を変えた版と古い写しが混ざると、切れている
 ものを切れていないものとして使い回してしまう。
 """
 h=hashlib.sha1(f'{str(path).lower()}|{st.st_size}|{int(st.st_mtime)}|{want}'.encode('utf-8')).hexdigest()[:16]
 return h+Path(path).suffix.lower()

def _size(n):
 """大きさの言い方。40KBを「0.0MB」と書くと、写せていないように見える。"""
 n=int(n or 0)
 if n<1024:return f'{n}バイト'
 if n<1048576:return f'{n/1024:.0f}KB'
 return f'{n/1048576:.1f}MB'

def _trim_to_line(data):
 """行の切れ目で切る。途中で切れた最後の1行は捨てる。

 CSVは引用符の中に改行を入れられるので、切ったところで引用符が開いたままなら、
 閉じるところまで行を戻す。開いたまま渡すと、その先の列が全部ずれる。
 """
 cut=data.rfind(b'\n')
 if cut<0:return b''                    # 1行も完結していない（極端に長い1行）
 out=data[:cut+1]
 while out.count(b'"')%2:
  cut=out.rfind(b'\n',0,len(out)-1)
  if cut<0:return b''
  out=out[:cut+1]
 return out

def plan_for(size,fmt,whole_limit=None):
 """その形式・大きさなら、どう写すか。('prefix'|'whole'|None, 写すバイト数, 理由)

 上限は引数で受け取る。以前はモジュールのグローバルを一時的に書き換えて渡していたが、
 画面は threaded=True で動くので、ビュワーの読み込みと結合の下読みが重なると
 互いに相手の上限を見てしまい、写すはずのものを写さない（＝公開先を直接開いて、
 自分の公開を自分で邪魔する）ことがあった。重なったまま終わると上限が戻らないこともある。
 """
 limit=int(WHOLE_BYTES if whole_limit is None else whole_limit)
 fmt=str(fmt or '').lower()
 if fmt in PREFIX_FORMATS:
  return ('prefix',min(int(size),PREFIX_BYTES),'')
 if fmt in WHOLE_FORMATS:
  if int(size)<=limit:return ('whole',int(size),'')
  return (None,0,f'{size/1048576:.0f}MBあるので写していません（途中で切ると壊れる形式です）。元のファイルを読みます')
 return (None,0,'この形式は写しません')

def _prune(keep):
 """置き場が上限を超えたら、古い写しから捨てる。いま使うものは残す。"""
 try:files=[(p,p.stat()) for p in cache_dir().glob('*') if p.is_file() and p.suffix!='.json']
 except Exception:return
 total=sum(s.st_size for _p,s in files)
 if total<=CACHE_TOTAL_BYTES:return
 for p,s in sorted(files,key=lambda x:x[1].st_mtime):
  if total<=CACHE_TOTAL_BYTES:break
  if p.name==keep:continue
  try:
   p.unlink();(p.with_suffix(p.suffix+'.json')).unlink(missing_ok=True)
   total-=s.st_size
   log.info('JOIN_CACHE_PRUNE file=%s size=%s',p.name,s.st_size)
  except Exception:pass

def sample(path,fmt,whole_limit=None):
 """1つのファイルをローカルへ写す。(写しの場所, 内訳) を返す。

 写さないと決めたときは (None, 内訳)。内訳には、なぜそうしたかが必ず入る ――
 「速くなった理由」も「速くならない理由」も、見えないところで起きるべきではない。
 """
 src=Path(path)
 info={'ok':False,'mode':None,'bytes':0,'total':0,'elapsed':0.0,'cached':False,'note':''}
 try:st=src.stat()
 except Exception as e:
  info['note']=f'読めませんでした: {e}';return None,info
 info['total']=st.st_size
 mode,want,why=plan_for(st.st_size,fmt,whole_limit)
 if not mode:
  info['note']=why;return None,info
 dst=cache_dir()/_key(src,st,want)
 meta=dst.with_suffix(dst.suffix+'.json')
 if dst.is_file() and meta.is_file():
  # すでに写してある。元の大きさと更新日時は名前に混ぜてあるので、在れば新しい。
  try:
   m=json.loads(meta.read_text(encoding='utf-8'))
   os.utime(dst,None)                   # 最近使ったものとして残す（捨てる順の材料）
   info.update(ok=True,cached=True,mode=m.get('mode') or mode,bytes=int(m.get('bytes') or 0),
               note=m.get('note') or '')
   return dst,info
  except Exception:pass
 started=time.perf_counter()
 try:
  if mode=='whole':
   shutil.copy2(src,dst);wrote=dst.stat().st_size
  else:
   with src.open('rb') as f:data=f.read(want)
   if st.st_size>want:
    data=_trim_to_line(data)
    if not data:
     info['note']='1行も切り出せませんでした（1行が長すぎます）。元のファイルを読みます'
     return None,info
   dst.write_bytes(data);wrote=len(data)
 except Exception as e:
  log.warning('JOIN_CACHE_COPY_FAILED src=%s error=%s',src,e)
  info['note']=f'写せませんでした: {e}（元のファイルを読みます）'
  return None,info
 elapsed=time.perf_counter()-started
 note=(f'まるごとローカルへ写しました（{_size(wrote)}）' if mode=='whole'
       else (f'先頭{_size(wrote)}をローカルへ写しました（元は{_size(st.st_size)}）' if st.st_size>wrote
             else f'ローカルへ写しました（{_size(wrote)}）'))
 try:meta.write_text(json.dumps({'source':str(src),'mode':mode,'bytes':wrote,'total':st.st_size,
                                 'note':note,'at':time.time()},ensure_ascii=False),encoding='utf-8')
 except Exception:pass
 info.update(ok=True,mode=mode,bytes=wrote,elapsed=round(elapsed,3),note=note)
 log.info('JOIN_CACHE_COPY src=%s mode=%s bytes=%s total=%s elapsed=%.2fs',src,mode,wrote,st.st_size,elapsed)
 _prune(dst.name)
 return dst,info

def stats():
 """写しの置き場のいまの様子。画面で「消す」を出すときの材料。"""
 try:files=[p for p in cache_dir().glob('*') if p.is_file() and p.suffix!='.json']
 except Exception:return {'count':0,'bytes':0,'dir':str(cache_dir())}
 return {'count':len(files),'bytes':sum(p.stat().st_size for p in files),'dir':str(cache_dir())}

def clear():
 """写しを全部捨てる。次に組み立てるとき、また写しに行くだけ。"""
 n=0
 for p in cache_dir().glob('*'):
  try:p.unlink();n+=1
  except Exception:pass
 log.info('JOIN_CACHE_CLEAR removed=%s',n)
 return n

# ==== 公開先を読むための写し（共有の写し方の約束・docs/SHARED_READ.md） ============================
# ビュワーと出力の列の読み取りは、自分（や別のPCのこのアプリ）が公開した出力を読む。公開先を開いていると、
# Windows では os.replace で差し替えられない ―― つまり、自分のビュワーで見ているせいで自分の公開が待たされる
# （20秒を超えると保留になる）。そこで WaveLog・Quality-Analysis と同じ作法で写してから読む:
#   R1 変わったかは（大きさ・更新時刻 ns）で見る。同じ版の写しがあれば共有を開かない（R2）
#   R3 写す前に書き手の目印（.<名前>.*.incoming・-journal・-wal）を見る。あれば写さない
#   R4 置き換えを許す開き方（open_shared_read）で、休まず丸ごと1回で写す
#   R5 写し終えたら大きさ・時刻と目印をもう一度見る。違えば捨てる
#   R6 SQLite3 は quick_check で確かめる
#   R7 写しは版ごとの名前（大きさ・時刻を名前に混ぜる）。書きかけは .tmp に置き、確かめてから名前を付ける
#   R8 **公開先を直接開かない**。写せなければ理由を言って断る（以前は大きすぎる・写せないと直接開いていた）
#   R9 同じ公開先を同時に2本写さない

# 従っている約束の版（docs/SHARED_READ.md の題。WaveLog・Quality-Analysis と同じ文）。
CONTRACT_VERSION=1
# 読むために写すときの上限。以前（256MB）を超えると写さずに直接開いていた（＝公開を止めうる）。いまは直接は
# 開かないので、ふつうの出力が入る大きさまで上げ、超えたら断る（理由と大きさを言う）。
READ_COPY_BYTES=2*1024*1024*1024
COPY_CHUNK=4*1024*1024

class NotCopiedYet(OSError):
 """公開先を、まだ手元へ写せていない（直接は開かない・R8）。文はそのまま画面へ出す。"""

_GENERIC_READ=0x80000000
_SHARE_ALL=0x1|0x2|0x4          # FILE_SHARE_READ | WRITE | DELETE
_OPEN_EXISTING=3
_SEQUENTIAL=0x08000000          # FILE_FLAG_SEQUENTIAL_SCAN

def open_shared_read(path):
 """読むために開く（with で閉じる）。Windows では、開いている間も書き手が置き換えられる開き方
 （FILE_SHARE_DELETE まで許す）にする。Python の open() はそれを付けない（R4）。ほかの OS は open()。"""
 if os.name!='nt':return open(path,'rb')
 import _winapi,msvcrt
 h=_winapi.CreateFile(str(path),_GENERIC_READ,_SHARE_ALL,0,_OPEN_EXISTING,_SEQUENTIAL,0)
 return open(msvcrt.open_osfhandle(h,os.O_RDONLY|getattr(os,'O_BINARY',0)),'rb')

def writer_marks(path):
 """書き手が作業中の印（公開先と同じフォルダー）。あれば名前の並び、無ければ []（R3）。
 公開の書きかけ（.<名前>.<番号>.incoming）と、SQLite の中を書き換える書き手の -journal・-wal。"""
 p=Path(path);low=p.name.lower()
 if not low:return []
 try:
  with os.scandir(p.parent) as it:names=[e.name for e in it]
 except OSError:return []
 return sorted(n for n in names if (n.lower().startswith(f'.{low}.') and n.lower().endswith('.incoming'))
               or n.lower() in (f'{low}-journal',f'{low}-wal'))

def _signature(path):
 st=Path(path).stat();return (st.st_size,st.st_mtime_ns)

def _read_key(path,sig):
 h=hashlib.sha1(f'read|{str(path).lower()}|{sig[0]}|{sig[1]}'.encode('utf-8')).hexdigest()[:16]
 return h+Path(path).suffix.lower()

def _verify(tmp,suffix):
 """使う前に中身を確かめる（R6）。だめなら理由、良ければ None。SQLite3 だけ中まで見る。"""
 if suffix.lower() not in ('.sqlite3','.sqlite','.db'):return None
 import sqlite3
 try:c=sqlite3.connect(f'file:{Path(tmp).as_posix()}?mode=ro',uri=True,timeout=10)
 except sqlite3.Error as e:return f'開けません: {e}'
 try:
  row=c.execute('PRAGMA quick_check(1)').fetchone()
  if not row or str(row[0]).lower()!='ok':return f'整合性検査に通りません: {row[0] if row else "(応答なし)"}'
 except sqlite3.Error as e:return f'読めません: {e}'
 finally:c.close()
 return None

_read_locks={};_read_locks_guard=threading.Lock()
def _lock_for(path):
 with _read_locks_guard:return _read_locks.setdefault(str(path).lower(),threading.Lock())

def read_copy(path):
 """公開先を読むための手元の写しの場所。**写せなければ NotCopiedYet**（公開先を直接開かない・R8）。

 呼ぶ側（ビュワー・列の読み取り）は例外の文をそのまま画面へ出す。写せない理由はたいてい「公開している途中」
 なので、数秒おいて開き直せば写せる。見ている最中に公開されても、見ている写しは壊れない。
 """
 src=Path(path)
 with _lock_for(src):                                     # R9
  try:sig=_signature(src)
  except OSError as e:raise NotCopiedYet(f'公開先を確かめられませんでした: {e}') from e
  dst=cache_dir()/_read_key(src,sig)
  if dst.is_file():                                       # R2: 同じ版の写しがあれば共有を開かない
   try:os.utime(dst,None)
   except OSError:pass
   return dst
  marks=writer_marks(src)                                 # R3
  if marks:
   raise NotCopiedYet(f'公開している途中のため、まだ手元へ写せません（{marks[0]}）。数秒おいてもう一度開いてください')
  if sig[0]>READ_COPY_BYTES:
   raise NotCopiedYet(f'{_size(sig[0])}あるので写せません（上限 {_size(READ_COPY_BYTES)}）。公開先は直接開きません（開くと公開が止まるため）')
  tmp=dst.with_name(dst.name+'.tmp')
  started=time.perf_counter()
  try:
   with open_shared_read(src) as f,open(tmp,'wb') as o:shutil.copyfileobj(f,o,COPY_CHUNK)   # R4
  except OSError as e:
   _drop(tmp);log.warning('READ_COPY_FAILED path=%s error=%s',src,e)
   raise NotCopiedYet(f'手元へ写せませんでした: {e}') from e
  try:after=_signature(src)
  except OSError:after=None
  if after!=sig:                                          # R5
   _drop(tmp);raise NotCopiedYet('写しているあいだに公開先が入れ替わりました。もう一度開いてください')
  marks=writer_marks(src)
  if marks:
   _drop(tmp);raise NotCopiedYet(f'写しているあいだに書き手が書き始めました（{marks[0]}）。数秒おいてもう一度開いてください')
  bad=_verify(tmp,src.suffix)                             # R6
  if bad:
   _drop(tmp);raise NotCopiedYet(f'写しが正しくないため使いません（{bad}）')
  os.replace(tmp,dst)                                     # R7
  log.info('READ_COPY src=%s bytes=%s elapsed=%.2fs',src,sig[0],time.perf_counter()-started)
  _prune(dst.name)
  return dst

def _drop(tmp):
 try:Path(tmp).unlink()
 except OSError:pass
