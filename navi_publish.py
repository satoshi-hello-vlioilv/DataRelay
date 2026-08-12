"""公開 ―― できあがったファイルを、読み手の場所へ安全に差し替える。

公開先（多くはネットワーク共有）は、他のアプリが読んでいる最中かもしれない。
そこで、いったん隠しファイルへ書き切り、大きさを照合してから os.replace で
一気に差し替える。差し替えられなければ *.pending_* として残し、次の実行の
はじめに適用する（保留は常に最新の1件だけ）。

前回と中身が同じかどうかは、出力ファイル同士では判定できない。SQLite3の出力には
作成日時を書き込んでいるため、中身が同じでもバイト列が毎回変わる。判定は抽出結果
（中間データ）側の指紋で行う。

app.py から分けてある。本体の状態は一切見ない。必要な2つの場所だけを setup で
受け取る。外から見える名前は分ける前と同じ（app からも読める）。
"""
import datetime as _dt,hashlib,json,os,shutil,time
from datetime import datetime
from pathlib import Path
from navi_log import log

LOCAL_ROOT=None;LOCAL_BACKUP=None
def setup(local_root,local_backup):
 """このPCのローカル領域と、控えの逃がし先を決める。app.py から一度だけ呼ぶ。"""
 global LOCAL_ROOT,LOCAL_BACKUP
 LOCAL_ROOT=Path(local_root);LOCAL_BACKUP=Path(local_backup)

def _fingerprint_dir():
 d=LOCAL_ROOT/'cache'/'fingerprints';d.mkdir(parents=True,exist_ok=True);return d

def _fingerprint_path(target):
 import hashlib
 return _fingerprint_dir()/(hashlib.sha1(str(target).lower().encode('utf-8',errors='replace')).hexdigest()[:16]+'.json')

def intermediate_fingerprint(path):
 """抽出した中身の指紋。前回と同じかどうかだけを見る。

 出力ファイル側では判定できない。SQLite3の出力には作成日時を書き込んでいるため、
 中身が同じでもバイト列は毎回変わる。判定するなら抽出結果（中間データ）側。"""
 import hashlib
 h=hashlib.sha1()
 try:
  with Path(path).open('rb') as f:
   for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 except OSError:return ''
 return h.hexdigest()

def unchanged_since_last(target,digest):
 """前回公開したものと中身が同じで、公開先も当時のまま残っているか。"""
 if not digest:return False
 p=_fingerprint_path(target)
 try:
  saved=json.loads(p.read_text(encoding='utf-8'))
 except Exception:return False
 if saved.get('digest')!=digest:return False
 try:
  st=Path(target).stat()
 except OSError:return False   # 公開先が消えていれば作り直す
 return int(saved.get('size') or -1)==st.st_size

def remember_published(target,digest,rows=0,cols=0):
 if not digest:return
 try:
  st=Path(target).stat()
  _fingerprint_path(target).write_text(json.dumps(
   {'target':str(target),'digest':digest,'size':st.st_size,'rows':rows,'cols':cols,
    'at':datetime.now().isoformat(timespec='seconds')},ensure_ascii=False),encoding='utf-8')
 except Exception as e:log.warning('FINGERPRINT_SAVE_FAILED target=%s error=%s',target,e)

def _replace_once(src,dst):
 os.replace(src,dst)
 return True

def _pending_pattern(dst):
 return f'{dst.stem}.pending_*{dst.suffix}'

def apply_pending(dst,backup_root,generations,backup_enabled=True,retention_days=30,generation_limit_enabled=True,backup_mode='generations'):
 """Apply the newest deferred output before the next extraction, if the target is no longer locked."""
 # globは公開先フォルダー（多くはネットワーク共有）を丸ごと列挙する。並列ラインの数だけ
 # 同時に走るため、共有が重い環境では抽出開始前の待ち時間になり得る。実測を必ず残す。
 _scan_started=time.perf_counter()
 pending=sorted(dst.parent.glob(_pending_pattern(dst)),key=lambda p:p.stat().st_mtime,reverse=True)
 scan_elapsed=time.perf_counter()-_scan_started
 log.info('PENDING_SCAN dir=%s pattern=%s matched=%s elapsed=%.2fs',dst.parent,_pending_pattern(dst),len(pending),scan_elapsed)
 if not pending:return None
 newest=pending[0]
 try:
  publish(newest,dst,backup_root,generations,from_pending=True,backup_enabled=backup_enabled,retention_days=retention_days,generation_limit_enabled=generation_limit_enabled,backup_mode=backup_mode)
  for old in pending[1:]:
   try:old.unlink()
   except OSError:pass
  log.info('保留ファイル適用完了 %s -> %s',newest,dst)
  return newest
 except (PermissionError,OSError) as e:
  # 保留ファイルの適用は最善努力。ここで失敗しても保留は残るので、これから行う抽出は止めない。
  log.warning('PENDING_APPLY_DEFERRED pending=%s target=%s error=%s',newest,dst,e)
  return None

def publish(src,dst,backup_root,generations,from_pending=False,backup_enabled=True,retention_days=30,generation_limit_enabled=True,backup_mode='generations'):
 """Copy locally-created output, then atomically replace the public file.
 If another PC has the target open, keep the new correct file as *.pending_* and return immediately.
 """
 dst.parent.mkdir(parents=True,exist_ok=True)
 bdir=backup_root/dst.stem
 if backup_enabled:
  # 控えが取れないことは、公開そのものを止める理由にはならない。使えない場所を
  # 指していたら、このPCのローカルへ逃がして続ける（理由はログに残す）。
  try:bdir.mkdir(parents=True,exist_ok=True)
  except Exception as be:
   fallback=LOCAL_BACKUP/dst.stem
   log.warning('BACKUP_DIR_UNUSABLE path=%s error=%s → %s へ切り替えます',bdir,be,fallback)
   try:
    fallback.mkdir(parents=True,exist_ok=True);bdir=fallback
   except Exception as be2:
    log.warning('BACKUP_DISABLED_THIS_RUN error=%s 控えを取らずに公開します',be2);backup_enabled=False
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
 incoming=dst.parent/f'.{dst.name}.{os.getpid()}.incoming'
 try:
  if from_pending:
   incoming=src
  else:
   copy_started=time.perf_counter();shutil.copy2(src,incoming);log.info('PUBLISH_INCOMING_COPY src=%s incoming=%s size=%s elapsed=%.2fs',src,incoming,incoming.stat().st_size,time.perf_counter()-copy_started)
   if incoming.stat().st_size!=src.stat().st_size:raise IOError('公開先へのコピーサイズが一致しません')
  # 照合用サイズはincomingを動かす前に確定させる。
  # from_pending時のincomingはsrcそのもののため、os.replace後にsrc.stat()はできない。
  expected_size=incoming.stat().st_size
  deadline=time.time()+3.0; last=None; backed_up=False
  while time.time()<deadline:
   try:
    if dst.exists() and backup_enabled and not backed_up:
     backup=bdir/f'{dst.stem}_{stamp}{dst.suffix}'
     try:
      # 成功したバックアップは取り直さない。公開先ロック時のリトライで同じコピーを繰り返さないため。
      backup_started=time.perf_counter();shutil.copy2(dst,backup);backed_up=True;log.info('PUBLISH_BACKUP_COPY src=%s backup=%s elapsed=%.2fs',dst,backup,time.perf_counter()-backup_started)
     except (PermissionError,OSError) as e:log.warning('PUBLISH_BACKUP_SKIP error=%s',e)
    replace_started=time.perf_counter();os.replace(incoming,dst);log.info('PUBLISH_ATOMIC_REPLACE target=%s elapsed=%.2fs',dst,time.perf_counter()-replace_started)
    cleanup_started=time.perf_counter();old=sorted(bdir.glob(f'{dst.stem}_*{dst.suffix}'),key=lambda p:p.stat().st_mtime,reverse=True) if backup_enabled else [];removed=0
    cutoff=time.time()-max(1,int(retention_days))*86400
    for index,item in enumerate(old):
     keep_by_generation=index<int(generations)
     keep_by_days=item.stat().st_mtime>=cutoff
     mode=str(backup_mode or 'generations')
     keep=(keep_by_generation if mode=='generations' else keep_by_days if mode=='days' else (keep_by_generation and keep_by_days))
     if keep:continue
     try:item.unlink();removed+=1
     except OSError:pass
    log.info('PUBLISH_BACKUP_CLEANUP candidates=%s removed=%s elapsed=%.2fs',len(old),removed,time.perf_counter()-cleanup_started)
    verify_started=time.perf_counter();published_size=dst.stat().st_size
    if published_size!=expected_size:raise IOError(f'公開後サイズ不一致 source={expected_size} target={published_size}')
    log.info('PUBLISH_FINAL_VERIFY target=%s size=%s elapsed=%.2fs',dst,published_size,time.perf_counter()-verify_started)
    return {'published':True,'path':str(dst)}
   except PermissionError as e:last=e;time.sleep(.25)
   except OSError as e:
    if getattr(e,'winerror',None) in (5,32,33):last=e;time.sleep(.25)
    else:raise
  if from_pending:raise PermissionError(f'公開先が使用中です: {dst}') from last
  # 保留ファイルは「次に公開できるようになるまでの1枚」であればよい。公開先が
  # ずっと使用中のままだと、実行のたびに新しい保留ファイルが増えていき、古いものは
  # このあと一度も読まれずに残り続けていた（apply_pendingは常に最新の1件しか見ない）。
  # 新しい保留を作る前に、同じ公開先に対する古い保留を消してから作る。
  old_pending=sorted(dst.parent.glob(_pending_pattern(dst)),key=lambda p:p.stat().st_mtime)
  removed_old=0
  for item in old_pending:
   try:item.unlink();removed_old+=1
   except OSError:pass
  pending=dst.parent/f'{dst.stem}.pending_{stamp}{dst.suffix}'
  os.replace(incoming,pending)
  log.warning('公開先使用中。新しいファイルを更新保留として保存 %s%s',pending,
              f'（古い保留 {removed_old}件を整理）' if removed_old else '')
  return {'published':False,'path':str(dst),'pending':str(pending),'reason':'他のPCまたはアプリが公開先ファイルを使用中'}
 finally:
  if incoming.exists() and incoming!=src:
   try:incoming.unlink()
   except OSError:pass
