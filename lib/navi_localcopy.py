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
import hashlib,json,os,shutil,time
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

def plan_for(size,fmt):
 """その形式・大きさなら、どう写すか。('prefix'|'whole'|None, 写すバイト数, 理由)"""
 fmt=str(fmt or '').lower()
 if fmt in PREFIX_FORMATS:
  return ('prefix',min(int(size),PREFIX_BYTES),'')
 if fmt in WHOLE_FORMATS:
  if int(size)<=WHOLE_BYTES:return ('whole',int(size),'')
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

def sample(path,fmt):
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
 mode,want,why=plan_for(st.st_size,fmt)
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

# 読むために写すときの上限。結合の組み立て（64MB）より大きく取ってある ――
# あちらは速さのための写しなので、写さなくても困らない。こちらは「公開先を開かない」
# ためのもので、写せないと公開が止まりうるので、もっと粘る値にしている。
READ_COPY_BYTES=256*1024*1024

def whole(path,limit=None):
 """丸ごと写して、その場所を返す。写せなければ元の場所。(場所, 内訳) を返す。

 読むため専用。先頭だけの写しでは表として読めない（SQLite3もEXCELも途中で切ると
 壊れる）ので、形式によらず丸ごと写す道を分けてある。

 写せなかったときは元の場所を返す ―― そのときは公開先を直接開くことになるので、
 あとで公開が「使用中」で失敗したときに繋がるよう、警告として残す。
 """
 src=Path(path);cap=int(limit or READ_COPY_BYTES)
 try:size=src.stat().st_size
 except Exception as e:
  return src,{'ok':False,'mode':None,'note':f'読めませんでした: {e}'}
 if size>cap:
  log.warning('LOCAL_COPY_SKIPPED_TOO_BIG path=%s size=%s cap=%s '
              '（写さずに直接開きます。この間、この公開先は差し替えられません）',src,size,cap)
  return src,{'ok':False,'mode':None,'total':size,
              'note':f'{_size(size)}あるので写していません。元のファイルを直接開きます'}
 keep=globals()['WHOLE_BYTES']
 try:
  globals()['WHOLE_BYTES']=cap
  local,info=sample(src,'sqlite3')      # 形式の別は見ない。丸ごとなら同じことをすればよい
 finally:
  globals()['WHOLE_BYTES']=keep
 return (local or src),info

def read_copy(path):
 """読むためにローカルへ写した場所。写せなければ元の場所をそのまま返す。

 公開先のファイルを直接開かないための入口。開くとそのファイルは「使用中」になり、
 Windowsでは os.replace で差し替えられない ―― つまり、自分のビュワーで見ている
 せいで、自分の公開が失敗する。実際そうなっていた（SQLite3の出力を共有から直接
 開いていた）。写してから読めば、共有のファイルには一度も触らない。

 ついでに、見ている最中に公開されても、見ている中身は壊れない。
 """
 try:
  local,_info=whole(path)
  return Path(local)
 except Exception as e:
  # 写せないことは、読めない理由にはしない。これまでどおり直接読む。
  log.warning('READ_COPY_FAILED path=%s error=%s（元のファイルを直接読みます）',path,e)
  return Path(path)
