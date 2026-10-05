"""デスクトップ版（DataRelay.exe）の自己診断を、外から流して確かめる係。手元（Linux・Xvfb）でも CI（Windows）でも同じものを使う。

  full    … 本物の WebView の中から、画面・保存・ファイル選択・常駐・タスクバーへ・心拍なし などを確かめる（selftest.js）
  close   … 常駐の理由が無いまま × → 後始末（/api/app-cleanup）をしてから窓も Python も終わる
  restart … 中身（Python）を外から強制終了 → 窓が問い合わせを待たずに起こし直す
  local   … exe だけを手元に置いた形（隣の DataRelay.program.txt が共有のアプリのフォルダーを指す）で full を流す。
             Windows では本物の install_local.cmd で置く（それ以外では同じ形を作る）
  update  … 手元の exe に古い版のふりをさせて起動 → 自分を入れ替えて起こし直し、入れ替わった exe が full を流す
  release … 配布（1.98.0）。作業ツリーから配る zip を作って置き場へ2つの版を置き、
             入口（置き場の DataRelay.exe）から写す → 次の版へそろえる（exe も変わるので開き直す）→ 前の版へ戻す、を
             本物の exe で通す。写しの中では selftest.js の release の型が、データの基準・各PCの名乗りを確かめる

使い方:
  python desktop/selftest_runner.py <exe> [--wrap "dbus-run-session -- xvfb-run -a"] [--modes full,close,restart,local,update,release]
update と release は、起こし直した・渡した先の exe が画面を失わないよう、Linux では xvfb-run ではなく別に立てた Xvfb の上で流す。
各型は新しい置き場（NAVI_LOCAL_ROOT・NAVI_CONFIG_DIR）で動かし、終わったあと Python が残っていないことも見る。
"""
import argparse,json,os,re,shlex,shutil,signal,subprocess,sys,tempfile,time,zipfile
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


def build_zip(exe,out,version=None,exe_tail=b''):
 """配る zip（Release の DataRelay.zip と同じ形: DataRelay/ の下にアプリのフォルダー一式＋DataRelay.exe）を作業ツリーから作る。
 git archive は commit した物しか入らないので、手元の変更も入るよう ls-files（追跡している物＋まだ追跡していない物）から
 .gitattributes の export-ignore を外して詰める。version を渡すと navi_version.py の版を差し替える（次の版のふり）。
 exe_tail は exe の後ろに足す（中身の違う exe にする。後ろに足した物は読み込まれない）。"""
 ignore={l.split()[0].strip('/') for l in (ROOT/'.gitattributes').read_text(encoding='utf-8').splitlines()
         if 'export-ignore' in l and not l.lstrip().startswith('#')}
 names=subprocess.run(['git','-C',str(ROOT),'ls-files','-co','--exclude-standard','-z'],capture_output=True,check=True).stdout.decode('utf-8').split('\0')
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for n in sorted(set(names)):
   if not n or n.split('/')[0] in ignore or not (ROOT/n).is_file():continue
   data=(ROOT/n).read_bytes()
   if version and n=='lib/navi_version.py':data=re.sub(rb"APP_VERSION='[^']*'",f"APP_VERSION='{version}'".encode(),data,count=1)
   z.writestr('DataRelay/'+n,data)
  info=zipfile.ZipInfo('DataRelay/DataRelay.exe',time.localtime()[:6]);info.external_attr=0o755<<16;info.compress_type=zipfile.ZIP_DEFLATED
  z.writestr(info,exe.read_bytes()+exe_tail)
 return out


def run_release(exe,wrap,work):
 """配布の型。置き場に2つの版を置き、入口から写す → 次の版へそろえる → 前の版へ戻す。"""
 sys.path.insert(0,str(ROOT/'lib'))
 import navi_release as R
 checks=[]
 work=work.resolve()                     # Windows の短い名前（RUNNER~1）を長い名前へ（画面が道を比べる）
 share=work/'share';share.mkdir()
 local=work/'local';root=work/'home'/'DataRelay'
 v1=R.version_in((ROOT/'lib'/'navi_version.py').read_text(encoding='utf-8'));v2=v1+'-st2'
 for v,tail in ((v1,b''),(v2,b'\0'*64)):
  out=R.publish_zip(build_zip(exe,work/f'{v}.zip',None if v==v1 else v,tail),share,uid='selftest')
  checks.append((f'版 {v} を置き場に置けた',out.get('ok'),out.get('error') or f"{out.get('files')}ファイル"))
 dlog_path=local/'logs'/'desktop.log'

 def phase(name,launch,want,expect,note=None,mode='release'):
  result=work/f'result-{name}.json'
  start=dlog_path.stat().st_size if dlog_path.exists() else 0
  env=dict(os.environ,NAVI_LOCAL_ROOT=str(local),DATARELAY_INSTALL_ROOT=str(root),DATARELAY_SELFTEST=str(result),
           DATARELAY_SELFTEST_MODE=mode)
  for k in ('DATARELAY_PROGRAM','NAVI_CONFIG_DIR','NAVI_DATA_ROOT','DATARELAY_NO_BOOT','DATARELAY_UPDATE_FORCE'):env.pop(k,None)
  cmd=shlex.split(wrap)+[str(launch)] if wrap else [str(launch)]
  p=subprocess.Popen(cmd,env=env,cwd=str(launch.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:code=p.wait(240)
  except subprocess.TimeoutExpired:p.kill();code='時間切れ'
  # 入口・開き直す前の窓はすぐ終わる。渡した先の窓（子ではない）が結果を書いて終わるのを待つ
  end=time.time()+240
  while not result.exists() and time.time()<end:time.sleep(0.5)
  time.sleep(2.5)
  r=json.loads(result.read_text(encoding='utf-8')) if result.exists() else {'ok':False,'checks':[],'error':'結果のファイルがありません'}
  for c in r.get('checks',[]):checks.append((f'[{name}] {c["name"]}',c['ok'],c['detail']))
  if r.get('error'):checks.append((f'[{name}] 自己診断',False,r['error']))
  checks.append((f'[{name}] 最初に起こした exe の終了コード 0',code==0,code))
  vf=root/'lib'/'navi_version.py'
  have=R.version_in(vf.read_text(encoding='utf-8')) if vf.exists() else '(写していない)'
  checks.append((f'[{name}] 写しの版は {want}',have==want,have))
  if name!='install':checks.append((f'[{name}] アプリ監視の exe は写しの DataRelay.exe（退いた先ではない）',f"exe={root/'DataRelay.exe'} " in ' '.join(c['detail']+' ' for c in r.get('checks',[])),root/'DataRelay.exe'))
  dlog=dlog_path.read_text(encoding='utf-8',errors='replace')[start:] if dlog_path.exists() else ''
  for label,needle in expect:checks.append((f'[{name}] {label}',needle in dlog,needle))
  if not r.get('ok'):
   for line in dlog.splitlines()[-12:]:checks.append((f'[{name}]   desktop.log',False,line[:300]))
  if note is not None:
   n=result.with_suffix('.note.json')
   got=json.loads(n.read_text(encoding='utf-8')).get('release_note') if n.exists() else None
   checks.append((f'[{name}] そろえたことを画面が知っている（アプリ監視・通知）',got==note,repr(got)))
  left=[x for x in backend_pids(local) if alive(x)]
  checks.append((f'[{name}] 終わったあと Python が残っていない',not left,f'残り {left}'))

 out=R.set_release(v1,share,share,uid='selftest')
 checks.append((f'配る版を {v1} に決めた',out.get('ok') and not out.get('notes'),out.get('notes') or out.get('error') or ''))
 checks.append(('配る入口が置き場の直下にある',(share/'DataRelay.exe').is_file(),share/'DataRelay.exe'))
 phase('install',share/'DataRelay.exe',v1,[('入口から写しへ渡した','INSTALL 置き場から写しへ渡しました'),
                                           ('中身の無い所へ配る版を写した',f'RELEASE_APPLIED from= to={v1} exe_changed=false')],note='')
 seed=json.loads((root/'config'/'install.json').read_text(encoding='utf-8')) if (root/'config'/'install.json').exists() else {}
 # データの基準は、置き場が利用者のプロファイルの下なら %USERPROFILE%\… の形で渡る（BOX Drive は利用者ごとに場所が違う・
 # navi_paths.portable）。字のままではなく、展開して同じ場所かを比べる（Windows の CI で、字のまま比べて落ちた）
 import navi_paths
 same=lambda a,b:bool(a) and os.path.normcase(os.path.abspath(navi_paths.expand(a)))==os.path.normcase(os.path.abspath(str(b)))
 checks.append(('写しはデータの基準と入れた元を知っている（config/install.json）',same(seed.get('data_root'),share) and same(seed.get('from'),share),seed))
 checks.append(('設定のマスターは共有のアプリのフォルダーに作られる',(share/'Config'/'app_settings.sqlite3').is_file(),share/'Config'))
 checks.append(('写しの中に設定のマスターを作らない',not any((root/d/'app_settings.sqlite3').exists() for d in ('Config','config')),root))

 R.set_release(v2,share,share,uid='selftest')
 phase('update',root/'DataRelay.exe',v2,[('配る版へそろえた（exe も変わった）',f'RELEASE_APPLIED from={v1} to={v2} exe_changed=true'),
                                         ('新しい exe が、前の窓の終わりを待ってから開いた','AFTER_PREVIOUS waited=')],note=f'{v1} → {v2}')
 checks.append(('前の版は写しの控えに残る',(root/'.update'/f'{v1}.old'/'app.py').is_file(),root/'.update'))
 checks.append(('exe も配る版の物になった',(root/'DataRelay.exe').read_bytes()==(share/'versions'/v2/'DataRelay.exe').read_bytes(),root/'DataRelay.exe'))

 R.set_release(v1,share,share,uid='selftest')
 phase('rollback',root/'DataRelay.exe',v1,[('前の版へ戻した（配る版を選び直しただけ）',f'RELEASE_APPLIED from={v2} to={v1}')],note=f'{v2} → {v1}')
 # 画面の「開き直して新しい版にする」と同じ道（配る版は変えない。開き直した窓が確かめを流す）
 phase('restart',root/'DataRelay.exe',v1,[('画面から開き直しを頼まれ、後始末をしてから開き直した','QUIT source=ui-restart restart=true'),
                                         ('新しい自分を起こした','RESTART relaunched'),('開き直した窓が、前の窓の終わりを待った','AFTER_PREVIOUS waited=')],
       mode='release-restart')
 fleet=R.fleet(share,v1)
 checks.append(('置き場の各PCの版に、このPCが配る版で載る',any(f['version']==v1 and not f['outdated'] for f in fleet),[(f['pc'],f['version']) for f in fleet]))
 return checks


def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('exe');ap.add_argument('--wrap',default='');ap.add_argument('--modes',default='full,close,restart,local,update,release')
 a=ap.parse_args();bad=0
 for mode in a.modes.split(','):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(a.exe).resolve()
   checks=run_release(exe,a.wrap,Path(d)) if mode=='release' else run(exe,a.wrap,mode,Path(d))
  print(f'■ {mode}')
  for name,ok,detail in checks:
   print(f"  {'合格' if ok else '★不合格'} {name} | {str(detail)[:160]}")
   bad+=0 if ok else 1
 print('すべて合格' if not bad else f'不合格 {bad} 件')
 return 1 if bad else 0

if __name__=='__main__':sys.exit(main())
