"""デスクトップ版（DataRelay.exe）の自己診断を、外から流して確かめる係。手元（Linux・Xvfb）でも CI（Windows）でも同じものを使う。

  full    … 本物の WebView の中から、画面・保存・ファイル選択・常駐・タスクバーへ・心拍なし などを確かめる（selftest.js）
  close   … 常駐の理由が無いまま × → 後始末（/api/app-cleanup）をしてから窓も Python も終わる
  restart … 中身（Python）を外から強制終了 → 窓が問い合わせを待たずに起こし直す
  local   … exe だけを手元に置いた形（隣の DataRelay.program.txt が共有のアプリのフォルダーを指す）で full を流す。
             Windows では本物の install_local.cmd で置く（それ以外では同じ形を作る）
  update  … 手元の exe に古い版のふりをさせて起動 → 自分を入れ替えて起こし直し、入れ替わった exe が full を流す

使い方:
  python desktop/selftest_runner.py <exe> [--wrap "dbus-run-session -- xvfb-run -a"] [--modes full,close,restart,local,update]
各型は新しい置き場（NAVI_LOCAL_ROOT・NAVI_CONFIG_DIR）で動かし、終わったあと Python が残っていないことも見る。
"""
import argparse,json,os,shlex,shutil,signal,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def alive(pid):
 if not pid:return False
 if os.name=='nt':
  out=subprocess.run(['tasklist','/FI',f'PID eq {pid}','/NH'],capture_output=True,text=True).stdout
  return str(pid) in out
 try:os.kill(int(pid),0);return True
 except OSError:return False


def kill(pid):
 if os.name=='nt':subprocess.run(['taskkill','/PID',str(pid),'/F'],capture_output=True)
 else:os.kill(int(pid),signal.SIGKILL)


def backend_pids(local):
 """窓の記録（desktop.log）に残った中身の pid（起こし直しのたびに増える）。"""
 out=[]
 for line in (local/'logs'/'desktop.log').read_text(encoding='utf-8',errors='replace').splitlines() if (local/'logs'/'desktop.log').exists() else []:
  if 'BACKEND_READY' in line and ' pid=' in line:out.append(int(line.split(' pid=')[1].split()[0]))
 return out


def place_locally(exe,work,checks):
 """exe だけを手元に置く（install_local.cmd と同じ形）。置いた exe の場所を返す。"""
 if os.name=='nt':
  lad=work/'localappdata'
  env=dict(os.environ,LOCALAPPDATA=str(lad),DATARELAY_EXE_SOURCE=str(exe))
  r=subprocess.run(['cmd','/c',str(ROOT/'install_local.cmd'),'/quiet','/noshortcut'],env=env,capture_output=True,timeout=120)
  placed=lad/'DataRelay'/'bin'/exe.name
  ok=r.returncode==0 and placed.is_file()
  checks.append(('install_local.cmd で手元に置けた',ok,f'終了コード {r.returncode} {placed}'))
  if not ok:
   # 置けなかった理由はスクリプトの出力にしか残らない。行ごとに残す（文字コードが合わなくても ASCII の部分は読める）
   for line in (r.stdout+r.stderr).decode('utf-8','replace').splitlines():
    if line.strip():checks.append(('  install_local.cmd の出力',False,line.strip()))
 else:
  placed=work/'bin'/exe.name;placed.parent.mkdir(parents=True)
  shutil.copy2(exe,placed)
  (placed.parent/'DataRelay.program.txt').write_text(f'# install_local.cmd と同じ形\n{ROOT}\n',encoding='utf-8')
 pointer=placed.parent/'DataRelay.program.txt'
 text=pointer.read_text(encoding='utf-8') if pointer.exists() else ''
 checks.append(('隣の DataRelay.program.txt がアプリのフォルダーを指す',str(ROOT) in text,text.strip().splitlines()[-1:] or '無い'))
 return placed


def run(exe,wrap,mode,work):
 local=work/'local';result=work/'result.json';checks=[]
 env=dict(os.environ,DATARELAY_PROGRAM=str(ROOT),NAVI_LOCAL_ROOT=str(local),NAVI_CONFIG_DIR=str(work/'config'),
          DATARELAY_SELFTEST=str(result),DATARELAY_SELFTEST_MODE='' if mode in ('full','local','update') else mode)
 env.pop('DATARELAY_NO_BOOT',None)
 if mode in ('local','update'):
  # アプリのフォルダーは exe の隣の DataRelay.program.txt で知る（DATARELAY_PROGRAM は使わない）
  env.pop('DATARELAY_PROGRAM',None)
  exe=place_locally(exe,work,checks)
  if not exe.is_file():return checks   # 置けなかった。起動しない（理由は上の出力）
  if mode=='update':
   env.update(DATARELAY_SELFTEST_PRETEND_VERSION='0.0.1',DATARELAY_SELFTEST_UPDATE_SOURCE=str(exe.with_name('source-'+exe.name)))
   shutil.copy2(exe,exe.with_name('source-'+exe.name))
 cmd=shlex.split(wrap)+[str(exe)] if wrap else [str(exe)]
 t=time.time();p=subprocess.Popen(cmd,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 note=result.with_suffix('.note.json')
 if mode=='restart':
  end=time.time()+90
  while not note.exists() and time.time()<end and p.poll() is None:time.sleep(0.2)
  if not note.exists():checks.append(('起こし直しの型が始まった',False,'記録が出ません'))
  else:
   pid=json.loads(note.read_text(encoding='utf-8'))['pid']
   kill(pid);checks.append(('中身（Python）を外から強制終了した',True,f'pid {pid}'))
 try:code=p.wait(180)
 except subprocess.TimeoutExpired:p.kill();code='時間切れ'
 if mode=='update':
  # 最初の exe は入れ替えて起こし直したらすぐ終わる。入れ替わった exe（子ではない）が結果を書くのを待つ
  end=time.time()+180
  while not result.exists() and time.time()<end:time.sleep(0.5)
  time.sleep(2)
 took=time.time()-t
 time.sleep(1.5)
 left=[x for x in backend_pids(local) if alive(x)]
 checks.append(('終わったあと Python が残っていない',not left,f'残り {left}'))
 if mode in ('full','restart','local','update'):
  r=json.loads(result.read_text(encoding='utf-8')) if result.exists() else {'ok':False,'checks':[],'error':'結果のファイルがありません'}
  for c in r.get('checks',[]):checks.append((c['name'],c['ok'],c['detail']))
  if r.get('error'):checks.append(('自己診断',False,r['error']))
  checks.append(('窓の終了コード 0',code==0,code))
 dlog=(local/'logs'/'desktop.log').read_text(encoding='utf-8',errors='replace') if (local/'logs'/'desktop.log').exists() else ''
 if mode in ('local','update'):
  checks.append(('手元の exe が共有のアプリのフォルダーを使った',f'program={ROOT} place=local' in dlog,'desktop.log の START'))
 if mode=='update':
  checks.append(('古い版と分かって、共有の exe で入れ替えた','EXE_UPDATED from=0.0.1' in dlog,'desktop.log の EXE_UPDATED'))
  told=[c for c in (r.get('checks') or []) if c['name'].startswith('exe の置き場')]
  checks.append(('入れ替わった exe が、入れ替えたことを知っている（通知・アプリ監視）',bool(told) and 'updated_from=0.0.1' in told[0]['detail'],told[0]['detail'] if told else '無い'))
  checks.append(('入れ替えたあとは、もう一度は入れ替えない',dlog.count('EXE_UPDATED from=')==1,f'{dlog.count("EXE_UPDATED from=")}回'))
  checks.append(('入れ替わった exe は共有の exe と同じ中身',exe.read_bytes()==exe.with_name('source-'+exe.name).read_bytes(),exe))
 if mode=='restart':
  pids=backend_pids(local)
  checks.append(('窓の記録に起こし直しが残る',len(pids)>=2,f'中身の pid {pids}'))
 if mode=='close':
  reason=json.loads(note.read_text(encoding='utf-8')).get('reason') if note.exists() else None
  checks.append(('常駐の理由が無い（× で終わってよい）',reason=='',repr(reason)))
  checks.append(('× で窓が終わる（終了コード 0）',code==0,f'{code}・{took:.1f}秒'))
  log=(local/'logs'/'app.log').read_text(encoding='utf-8',errors='replace') if (local/'logs'/'app.log').exists() else ''
  checks.append(('終わる前に後始末を頼んだ',('APP_EXIT_PREPARE source=desktop-close' in log),'app.log の APP_EXIT_PREPARE'))
 return checks


def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('exe');ap.add_argument('--wrap',default='');ap.add_argument('--modes',default='full,close,restart,local,update')
 a=ap.parse_args();bad=0
 for mode in a.modes.split(','):
  with tempfile.TemporaryDirectory() as d:
   checks=run(Path(a.exe).resolve(),a.wrap,mode,Path(d))
  print(f'■ {mode}')
  for name,ok,detail in checks:
   print(f"  {'合格' if ok else '★不合格'} {name} | {str(detail)[:160]}")
   bad+=0 if ok else 1
 print('すべて合格' if not bad else f'不合格 {bad} 件')
 return 1 if bad else 0

if __name__=='__main__':sys.exit(main())
