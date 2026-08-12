"""ログの機構 ―― 出す・省略する・末尾だけ読む・世代を押し出す。

app.py から分けてある。ログは全体から呼ばれる土台で、逆に本体の状態は一切見ない。
そのぶん、ここだけを読めば「どう記録されるか」が閉じて分かる。

「いま付け替えてよいか」（実行中か・ワーカーが残っていないか）は本体の都合なので、
判断は app.py 側に置き、ここは押し出す機構だけを持つ。
外から見える名前は分ける前と同じ（app からも読める）。
"""
import atexit,copy,logging,os,re,threading,time
from pathlib import Path

LOCAL_LOGS=None;LOG_PATH=None;log_dedup=None

def setup(local_logs):
 """ログの出力先を決めて、記録の準備をする。app.py から一度だけ呼ぶ。"""
 global LOCAL_LOGS,LOG_PATH,log_dedup
 LOCAL_LOGS=Path(local_logs);LOG_PATH=LOCAL_LOGS/'app.log'
 if not log.handlers:
  # 並列実行では複数プロセスが同じログへ追記するため、行だけを見るとどのプロセスの
  # 出来事か分からない。プロセスIDを常に出して、後からライン単位で追跡できるようにする
  # （先頭の日時と[LEVEL]の位置は画面側の解析に合わせて維持）。
  #
  # RotatingFileHandlerは使わない。並列実行では複数のワーカープロセスが同じファイルへ
  # 追記するため、どれか1つが勝手に付け替えると他のプロセスの書き先が消えたファイルを
  # 指したままになる（Windowsでは開いている最中のリネームがそもそも失敗する）。
  # 付け替えは、ワーカーが1つも居ない瞬間に本体だけが行う。
  h=logging.FileHandler(LOG_PATH,encoding='utf-8')
  h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [pid %(process)d] %(message)s'))
  log.addHandler(h)
  log_dedup=LogDedupFilter(h);h.addFilter(log_dedup)
  # 溜めたままプロセスが終わると最後の1行が消える。終了時には必ず書き出す。
  atexit.register(log_dedup.flush)
 return log

def rotate_files(keep):
 """いまのログを app.1.log へ送り、古いほうから押し出す。呼ぶ前に flush_log を済ませ、
 close_handlers で開いているファイルを手放しておくこと（呼び出し側の責任）。
 keep=0 なら残さず消す。"""
 for n in range(keep,1,-1):
  src=LOCAL_LOGS/f'app.{n-1}.log';dst=LOCAL_LOGS/f'app.{n}.log'
  if not src.exists():continue
  if dst.exists():
   try:dst.unlink()
   except OSError:pass
  try:os.replace(src,dst)
  except OSError as e:log.warning('LOG_ROTATE_MOVE_FAILED src=%s dst=%s error=%s',src,dst,e)
 if keep>=1:
  dst=LOCAL_LOGS/'app.1.log'
  if dst.exists():
   try:dst.unlink()
   except OSError:pass
  try:os.replace(LOG_PATH,dst)
  except OSError as e:log.warning('LOG_ROTATE_MOVE_FAILED src=%s dst=%s error=%s',LOG_PATH,dst,e)
 else:
  try:LOG_PATH.unlink()
  except OSError:pass
 for old in LOCAL_LOGS.glob('app.*.log'):
  try:
   if int(re.sub(r'\D','',old.stem.split('.')[-1]) or 0)>keep:old.unlink()
  except Exception:pass

def close_handlers():
 """付け替えの直前に、開いているファイルを手放す。"""
 for x in log.handlers:
  try:x.close()
  except Exception:pass

log=logging.getLogger('navi'); log.setLevel(logging.INFO)

# ==== 同じ内容が続いたときの省略 =========================================
# 短い間に同じことを言い続ける行（待機中・進捗・途絶の警告など）は、読むときの邪魔になるだけでなく
# ファイルを重くする。残すのは「変化した瞬間」だけにする。
#
# 省略しても時間が測れなくならないよう、次の3つを必ず守る。
#   1. 続きはじめの1行は、そのまま残す（いつ始まったか）
#   2. 最後の1行も残す（いつまで続いたか）。時刻はもとの発生時刻のまま出す
#   3. 最後の1行に「何行省略したか」「何秒間続いたか」を書き足す
# つまり区間の両端と長さは必ず残るので、後から所要時間を出せる。
#
# 「同じ内容」の判定では、経過秒・バイト数・進捗といった動く値を伏せてから比べる。
#   例) HEARTBEAT_DEGRADED silence=9s → HEARTBEAT_DEGRADED silence=*
# 伏せた値そのものは、最後の1行に実際の値が残るので失われない。
LOG_DEDUP_WINDOW=60.0        # これだけ間があいたら、同じ内容でも「また起きた」として残す
LOG_DEDUP_HOLD_SECONDS=30.0  # 続いている最中も、これだけ経ったら途中経過を1行出す
LOG_DEDUP_HOLD_COUNT=1000    # 行数でも同じく区切る（落ちたときに失う状態をこの数までに抑える）
LOG_DEDUP_ERROR_SECONDS=10.0 # エラーは短めに区切る（直っていないことが分かるように）
_DEDUP_KEYS=('elapsed','silence','secs','sec','seconds','ms','msec','bytes','size','percent','progress','prog',
             'age','age_days','age_hours','attempt','attempts','remaining','eta','speed','rate','uptime','grace',
             'count','total','rows','done','sent','received','read','written','at','since')
_DEDUP_VOLATILE=re.compile(r'((?:^|[\s\[(,|])(?:'+'|'.join(_DEDUP_KEYS)+r')\s*=\s*)[-+]?[0-9][0-9,._/]*[a-zA-Z%]*',re.I)
_DEDUP_UNITS=re.compile(r'[-+]?[0-9][0-9,._]*\s*(秒|ミリ秒|分間|バイト|KB|MB|GB|s\b)',re.I)
def _dedup_key(record):
 """動く値を伏せた「内容の形」。これが同じ行を「同じ内容」として扱う。"""
 try:msg=record.getMessage()
 except Exception:msg=str(record.msg)
 msg=_DEDUP_VOLATILE.sub(r'\1*',msg)
 msg=_DEDUP_UNITS.sub(r'*\1',msg)
 exc=''
 if record.exc_info and record.exc_info[0] is not None:
  # 同じ例外が繰り返しているのか、別の例外に変わったのかは区別する
  exc=f'|{record.exc_info[0].__name__}:{str(record.exc_info[1])[:120]}'
 return f'{record.levelno}|{msg}{exc}'

class LogDedupFilter(logging.Filter):
 """同じ内容が続く区間を1本にまとめる。区間の両端と長さは必ず残す。

 ふるいはハンドラー側に付ける。ハンドラーのロックの外で動くので、状態は自前の錠で守る。
 まとめた行を書くときだけハンドラーのロックを取る（emit はふるいを呼ばないので再帰しない）。
 """
 def __init__(self,handler):
  super().__init__()
  self.handler=handler;self.enabled=os.environ.get('NAVI_LOG_DEDUP','1')!='0'
  self.lock=threading.Lock()
  self.key=None;self.n=0;self.last=None;self.first_at=0.0;self.last_at=0.0;self.suppressed=0

 def _emit(self,record):
  self.handler.acquire()
  try:self.handler.emit(record)
  finally:self.handler.release()

 def _close(self,now=None):
  """溜めていた区間を書き出す。呼び出し側で self.lock を取っていること。"""
  if self.n<=0 or self.last is None:
   self.key=None;self.n=0;self.last=None;return
  last=self.last;n=self.n;span=max(0.0,self.last_at-self.first_at)
  self.n=0;self.last=None
  if n==1:
   # 1行だけなら、まとめる意味がないのでそのまま出す
   self._emit(last);return
  rec=copy.copy(last)
  try:body=last.getMessage()
  except Exception:body=str(last.msg)
  rec.msg=f'{body} ｜ LOG_DEDUP 同じ内容を{n}行省略（{span:.1f}秒間・これが最後の1行）'
  rec.args=None
  # rec.created / rec.msecs は複製元のまま＝最後に起きた時刻。時間の測り直しができる
  self.suppressed+=n-1
  self._emit(rec)

 def flush(self):
  with self.lock:self._close()

 def filter(self,record):
  if not self.enabled:return True
  now=record.created
  key=_dedup_key(record)
  with self.lock:
   if key==self.key:
    hold=LOG_DEDUP_ERROR_SECONDS if record.levelno>=logging.ERROR else LOG_DEDUP_HOLD_SECONDS
    # 区切る条件。①長く続きすぎた ②行数が多すぎる ③間があきすぎた（また起きた、とみなす）
    over=(now-self.first_at>hold or self.n+1>=LOG_DEDUP_HOLD_COUNT or now-self.last_at>LOG_DEDUP_WINDOW)
    if not over:
     self.n+=1;self.last=record;self.last_at=now;return False
   # 溜めていた区間を閉じてから、この行を新しい区間のはじまりとして出す
   self._close()
   self.key=key;self.n=0;self.last=None;self.first_at=now;self.last_at=now
   return True

def flush_log():
 """溜めている省略ぶんを書き出してから、ハンドラーを流す。終了経路と読み出しの前に呼ぶ。"""
 if log_dedup is not None:
  try:log_dedup.flush()
  except Exception:pass
 for x in log.handlers:
  try:x.flush()
  except Exception:pass
def log_files():
 """新しい順に、いま残っているログファイル。app.log → app.1.log → app.2.log …"""
 out=[LOG_PATH] if LOG_PATH.exists() else []
 out+= [p for p in sorted(LOCAL_LOGS.glob('app.*.log'),
        key=lambda p:int(re.sub(r'\D','',p.stem.split('.')[-1]) or 0)) if p.is_file()]
 return out

def tail_lines(path,max_bytes):
 """ファイルの末尾だけを読む。全文をメモリへ載せない。

 先頭が途中で切れることがあるので、最初の1行は捨てる（行の途中から始まった
 半端な行を、正しい1行として見せないため）。"""
 try:size=path.stat().st_size
 except OSError:return [],0,False
 start=max(0,size-max_bytes)
 with path.open('rb') as f:
  if start:f.seek(start)
  raw=f.read()
 text=raw.decode('utf-8',errors='replace')
 lines=text.splitlines()
 if start and lines:lines=lines[1:]
 return lines,size,bool(start)
