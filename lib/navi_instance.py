"""このアプリの中身（スケジューラーを持つプロセス）を、利用者ごとに1つだけにする。

中身が2つ動くと、スケジューラーも2つになって同じ自動実行が二重に走る。起動のいちばん最初（boot_app）で
この錠を取り、取れなければ起動しない。窓（DataRelay.exe）は1つだけ起動する仕組みを持つが、古い版のフォルダーに
残ったブラウザ版（1.95.0 まで。start.vbs → app.py）や、別の場所に置いた exe から起こされた中身もここで止まる。

錠は OS のファイルロック（Windows は msvcrt.locking、ほかは fcntl.flock）。プロセスが落ちても
OS が外すので、「錠だけが残って二度と起動できない」ことは起きない。
錠の持ち主（どちらの形か・pid・いつから）は隣の JSON に書く。錠を掛けた範囲は他のプロセスから
読めない（Windows）ので、知らせる中身は別のファイルにしてある。

DBも画面も触らない。ファイルを受け取って答えるだけなので、実機なしで確かめられる。
"""
import json,os,time
from pathlib import Path

LOCK_NAME='app.lock'


class InstanceBusy(RuntimeError):
 """ほかの形（またはもう1つ）がすでに動いている。holder は錠の持ち主の記録（読めなければ {}）。"""
 def __init__(self,holder):
  self.holder=holder or {}
  mode={'browser':'古い版のブラウザ版（1.95.0 まで）','desktop':'DataRelay'}.get(self.holder.get('mode'),'もう1つの DataRelay')
  since=self.holder.get('since') or ''
  super().__init__(f'{mode}がすでに動いています（pid {self.holder.get("pid","?")}・{since} から）。'
                   'そちらを終了してから起動してください。同時に動かすと、自動実行が二重に走ります。')


class InstanceLock:
 def __init__(self,fh,path):
  self.fh=fh;self.path=path

 def release(self):
  try:
   if os.name=='nt':
    import msvcrt
    self.fh.seek(0);msvcrt.locking(self.fh.fileno(),msvcrt.LK_UNLCK,1)
   else:
    import fcntl
    fcntl.flock(self.fh.fileno(),fcntl.LOCK_UN)
  except OSError:
   pass
  try:self.fh.close()
  except OSError:pass


def _try_lock(fh):
 try:
  if os.name=='nt':
   import msvcrt
   fh.seek(0);msvcrt.locking(fh.fileno(),msvcrt.LK_NBLCK,1)
  else:
   import fcntl
   fcntl.flock(fh.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  return True
 except OSError:
  return False


def holder(runtime_dir):
 try:return json.loads((Path(runtime_dir)/(LOCK_NAME+'.json')).read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}


def acquire(runtime_dir,mode):
 """錠を取る。取れたら InstanceLock（プロセスが終わるまで持っておく）、取れなければ InstanceBusy。"""
 d=Path(runtime_dir);d.mkdir(parents=True,exist_ok=True)
 fh=open(d/LOCK_NAME,'a+b')
 if not _try_lock(fh):
  fh.close()
  raise InstanceBusy(holder(d))
 info={'mode':mode,'pid':os.getpid(),'since':time.strftime('%Y-%m-%d %H:%M:%S')}
 try:(d/(LOCK_NAME+'.json')).write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
 except OSError:pass
 return InstanceLock(fh,d/LOCK_NAME)
