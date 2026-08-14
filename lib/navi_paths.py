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
 """アプリが自分で作った控え置き場（…/SymfoNaviDataHub/backup）かどうか。

 これを絶対パスのまま設定へ残すと、別のPCでは他人のフォルダーを指す。中身は
 このPCのローカルなので、どのPCで作られたものでも <PC> へ読み替えてよい。
 """
 parts=[x.lower() for x in _split_any(value)]
 return len(parts)>=2 and parts[-1]=='backup' and parts[-2]=='symfonavidatahub'

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
def clean_work_folder():
 """前回の作業フォルダーを片付ける。消し終わるのを待たずに起動する。

 中身は影実行のCSVで数百MBになることがあり、消すだけで数秒かかる。その数秒は
 そのまま起動時間になっていた。名前を変えるのは一瞬なので、空の work をすぐ作り、
 古いほうは裏で消す。前回の起動が消し終える前に落ちていた取り残しも一緒に片付ける。
 (経過秒, やり方) を返す。
 """
 t=time.perf_counter();work=LOCAL_ROOT/'work';mode='none'
 if work.exists():
  try:
   work.rename(LOCAL_ROOT/f'work_old_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}');mode='rename'
  except Exception:
   # 名前を変えられない（前のプロセスが掴んだままなど）。そのときは従来どおり消す。
   shutil.rmtree(work,ignore_errors=True);mode='delete'
 work.mkdir(parents=True,exist_ok=True)
 def sweep():
  for d in sorted(LOCAL_ROOT.glob('work_old_*')):shutil.rmtree(d,ignore_errors=True)
 threading.Thread(target=sweep,daemon=True,name='work-clean').start()
 return round(time.perf_counter()-t,2),mode
