"""PCごとに実体が変わる場所を、設定に固定しない。

設定は BOX 上のマスターを通じて別のPCへも配られる。そこへ絶対パスのまま
「C:/Users/<作った人>/AppData/Local/...」を書くと、別のPCでは他人のプロファイルを
指すことになり、作成すらできない（実測 2026-08-11: WinError 5 アクセス拒否）。
そこで、PCごとに変わる場所は <PC> という印で持ち、使うときに実体へ直す。

app.py から分けてある。パスの読み替えは全体から呼ばれる土台で、逆に本体の状態は
一切見ない。基準となる2つの場所（アプリの場所・このPCのローカル領域）だけを
setup で受け取る。外から見える名前は分ける前と同じ（app からも読める）。
"""
import os,re,shutil,threading,time
from datetime import datetime
from pathlib import Path

# ---- 名前を変えたときの引っ越し --------------------------------------------
# ローカル領域（%LOCALAPPDATA%\<名前>）には、公開前の控え・ログ・設定の控えが入る。
# アプリの名前を変えたときにここも変えないと、名前だけ新しくて中身が古い場所を
# 指し続けることになる。かといって黙って新しい場所を作ると、それまでの控えが
# 見えなくなる（消えはしないが、世代を戻せなくなる）。
#
# だから、名前を変えるときは中身も連れていく。移すのは中の棚ごとに1つずつ、
# 移し先に同じ棚が無いときだけ ―― 起動の途中で片方だけ先に作られていても、
# 上書きせずに済ませられる。
LOCAL_SUBDIRS=('backup','logs','cache','runtime','work')

# ローカル領域として使ってきた名前（新しい順）。名前を変えても、前の名前で
# 書かれた設定は残り続けるので、見分けるときは全部を候補にする。
APP_LOCAL_NAMES=('datarelay','symfonavidatahub','navitosqlite')

def migrate_local_root(new_root,old_names,parent=None):
 """旧名のローカル領域から、中身を新しい名前のほうへ移す。移した棚の名前を返す。

 まだログの用意ができていない時点で呼ぶので、ここでは記録しない（返した名前を
 呼んだ側が、ログの準備ができてから残す）。
 """
 new_root=Path(new_root);base=Path(parent) if parent else new_root.parent
 moved=[]
 for name in old_names:
  old=base/name
  if not old.is_dir() or old.resolve()==new_root.resolve():continue
  for sub in LOCAL_SUBDIRS:
   src=old/sub;dst=new_root/sub
   if not src.is_dir() or dst.exists():continue
   try:
    dst.parent.mkdir(parents=True,exist_ok=True)
    os.replace(src,dst)                 # 同じドライブなので一瞬で済む
    moved.append(f'{name}/{sub}')
   except OSError:
    try:
     shutil.move(str(src),str(dst));moved.append(f'{name}/{sub}')
    except Exception:pass
 return moved

BASE=None;LOCAL_ROOT=None
def setup(base,local_root):
 """基準になる2つの場所を決める。app.py から一度だけ呼ぶ。"""
 global BASE,LOCAL_ROOT
 BASE=Path(base);LOCAL_ROOT=Path(local_root)

# ==== PCごとに実体が変わる場所 ==========================================
# 設定は BOX 上のマスターを通じて別のPCへも配られる。そこへ絶対パスのまま
# 「C:/Users/<作った人>/AppData/Local/...」を書くと、別のPCでは他人のプロファイル
# を指すことになり、作成すらできない（実測 2026-08-11: WinError 5 アクセス拒否）。
# そこで、PCごとに変わる場所は <PC> という印で持ち、使うときに実体へ直す。
PC_TOKEN='<PC>'
def pc_path(*parts):
 """このPCのローカル領域を指す、持ち運べる書き方を作る。"""
 return '\\'.join([PC_TOKEN]+[str(x) for x in parts if str(x)])
def is_pc_path(value):
 return str(value or '').strip().startswith(PC_TOKEN)

PROFILE_DIR_NAMES=('users','ユーザー','documents and settings')
def _split_any(p):
 """区切りは / でも \ でもよい。Windowsで作った設定をLinuxで読むこともある。"""
 return [x for x in re.split(r'[\\/]+',str(p or '')) if x!='']

def _profile_root(p):
 r"""C:\Users\<誰か> のような、利用者プロファイルの根を返す（無ければ None）。"""
 parts=_split_any(p)
 for i,x in enumerate(parts):
  if x.lower() in PROFILE_DIR_NAMES and i+1<len(parts):
   return '\\'.join(parts[:i+2])
 return None

def foreign_profile_path(value):
 """別の利用者のプロファイル配下を指していないか。

 指していれば、そのPCでは読み書きできない（できてしまうと、それはそれで問題）。
 自分のプロファイル配下や、プロファイルと無関係の場所は None を返す。
 """
 raw=str(value or '').strip()
 if not raw or is_pc_path(raw):return None
 try:target=Path(os.path.expandvars(os.path.expanduser(raw)))
 except Exception:return None
 # Windowsの絶対パスは、Linux上では相対に見える（区切りが違う）。文字の形で見る。
 win_abs=bool(re.match(r'^[A-Za-z]:[\\/]',str(target))) or str(target).startswith('\\\\')
 if not (target.is_absolute() or win_abs):return None
 root=_profile_root(target)
 if not root:return None
 mine=_profile_root(Path.home()) or '\\'.join(_split_any(Path.home()))
 if str(root).lower()==str(mine).lower():return None
 return str(root)

def _looks_generated_backup(value):
 """アプリが自分で作った控え置き場（…/<アプリ名>/backup）かどうか。

 これを絶対パスのまま設定へ残すと、別のPCでは他人のフォルダーを指す。中身は
 このPCのローカルなので、どのPCで作られたものでも <PC> へ読み替えてよい。

 昔の名前で書かれた設定も見分ける ―― 名前を変えた時点で見分けられなくなると、
 他人のフォルダーを指した絶対パスが設定に残り、別のPCで実行できなくなる。
 """
 parts=[x.lower() for x in _split_any(value)]
 return len(parts)>=2 and parts[-1]=='backup' and parts[-2] in APP_LOCAL_NAMES

def resolve_path(value,base=None):
 """Resolve absolute, UNC, or app-relative paths without changing stored values.

 base の既定は setup で決めたアプリの場所。定義時ではなく呼ばれた時点で解決する
 （既定引数に入れると、setup より前の値で固定されてしまう）。"""
 if base is None:base=BASE
 if value is None:return base
 raw=str(value).strip()
 # <PC> は、いま動いているPCのローカル領域へ直す。設定にはPC固有の値を残さない。
 if raw.startswith(PC_TOKEN):
  rest=raw[len(PC_TOKEN):].strip().lstrip('\\/')
  return (LOCAL_ROOT/rest) if rest else LOCAL_ROOT
 raw=os.path.expandvars(os.path.expanduser(raw))
 p=Path(raw)
 if p.is_absolute() or raw.startswith('\\'):return p
 return (Path(base)/p).resolve()

# ==== このPCのローカル領域の後始末 =====================================
def clean_work_folder(work=None):
 """前回の作業フォルダーを片付ける。消し終わるのを待たずに起動する。

 中身は影実行のCSVで数百MBになることがあり、消すだけで数秒かかる。その数秒は
 そのまま起動時間になっていた。名前を変えるのは一瞬なので、空の work をすぐ作り、
 古いほうは裏で消す。前回の起動が消し終える前に落ちていた取り残しも一緒に片付ける。

 片付ける場所は、実際に使う作業場所を渡してもらう。ここで LOCAL_ROOT/work と決め打ち
 していたため、アカウント名が日本語のPC（%LOCALAPPDATA% も %TEMP% も非ASCIIになる）では
 実際の作業場所が C:\DataRelayWork になるのに、掃除だけは誰も居ない場所を見ていた。
 数百MBの中間ファイルが起動のたびに積み上がる。
 (経過秒, やり方) を返す。
 """
 t=time.perf_counter();work=Path(work) if work else (LOCAL_ROOT/'work');root=work.parent;mode='none'
 if work.exists():
  try:
   work.rename(root/f'{work.name}_old_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}');mode='rename'
  except Exception:
   # 名前を変えられない（前のプロセスが掴んだままなど）。そのときは従来どおり消す。
   shutil.rmtree(work,ignore_errors=True);mode='delete'
 work.mkdir(parents=True,exist_ok=True)
 def sweep():
  for d in sorted(root.glob(f'{work.name}_old_*')):shutil.rmtree(d,ignore_errors=True)
  # 旧い綴りの取り残しも一緒に片付ける（片付ける場所を渡すようにする前のもの）。
  for d in sorted(LOCAL_ROOT.glob('work_old_*')):shutil.rmtree(d,ignore_errors=True)
 threading.Thread(target=sweep,daemon=True,name='work-clean').start()
 return round(time.perf_counter()-t,2),mode
