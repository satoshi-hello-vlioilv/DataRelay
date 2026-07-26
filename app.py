from __future__ import annotations
import atexit, calendar, configparser, csv, gc, json, logging, os, shutil, sqlite3, subprocess, sys, tempfile, threading, time, traceback, uuid, webbrowser
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request

APP_VERSION='V34'; APP_VERSION_TITLE='ブラウザーとアプリ稼働状態の同期'; APP_RELEASED_AT='2026-07-25'
BUILD_VERSION=f'{APP_VERSION}-browser-lifecycle-sync'; BASE=Path(__file__).resolve().parent; SETTINGS_DB=BASE/'app_settings.sqlite3'; LEGACY_CFG=BASE/'config.json'; HOST='127.0.0.1'; PORT=5031
# アプリ内バージョン履歴。新しいリリースを配布する際は先頭へ1件追加する。
CHANGELOG=[
 {'version':'V34','date':APP_RELEASED_AT,'title':APP_VERSION_TITLE,'notes':[
  'コマンドプロンプトを表示しない start.vbs を追加しました（初回セットアップは引き続きstart.batを使用します）。',
  '実行中にブラウザーを閉じようとすると警告が表示されるようにし、「アプリを終了」ボタンからは確認のうえ実行を中断して終了できるようにしました。',
  '実行中のジョブと実行キューを中断するAPIを追加しました（並列(プロセス分離)ラインは即時終了、直列実行は安全な区切りまで進めてから停止します）。',
  'サーバーへの接続が失われた場合に、その旨をブラウザー画面へ明示し、タブを閉じるよう案内する通知を追加しました。',
 ]},
 {'version':'V33','date':'2026-07-25','title':'ハートビート監視によるゾンビプロセス防止','notes':[
  'ブラウザー側から10秒間隔でハートビートを送信し、バックエンドが生存を確認するようにしました。',
  '45秒以上ハートビートが途絶えた場合、実行中のジョブが無く、かつ有効な自動実行ルールも無いときに限り、アプリが自動的に終了するようにしました。',
  'タブを閉じ忘れた場合でもPythonプロセスが残り続けないようにする一方、自動実行スケジュールがある場合は無人稼働を継続します。',
 ]},
 {'version':'V32','date':'2026-07-25','title':'対象ファイル一覧への進捗統合表示','notes':[
  '対象ファイル一覧の「自動実行」列を「進捗・次回実行」列へ再設計し、直近の開始予定時刻と予定の種類（手動のみ／定期／複数指定など）を表示するようにしました。',
  '実行中・実行キュー待ちの対象は、一覧の該当行がそのまま進捗バーへ切り替わり、工程・経過時間を確認できるようにしました。',
  '進捗表示中の行をクリックすると、詳細な進捗モーダルを直接開けるようにしました。',
 ]},
 {'version':'V31','date':'2026-07-25','title':'ヘッダーと並列進捗表示のUIUX改善','notes':[
  'ヘッダーのバージョン表示をアプリ名の直後へ移動し、状態表示・操作ボタンを役割ごとに区切り線で整理しました。',
  '並列実行の進捗レーンを、ライン数に応じて自動的に列数が変わるグリッド表示へ変更し、最大8ラインでも縦に伸びすぎず見やすく収まるようにしました。',
  '並列実行時の進捗モーダル幅を拡張し、レーン数が多い場合でも余裕を持って表示できるようにしました。',
 ]},
 {'version':'V30','date':'2026-07-25','title':'設定画面の再構成とバージョン管理','notes':[
  '共通設定を「接続とパス／抽出方式／並列実行／DDE互換設定／安全性とバックアップ／バージョン情報」のカテゴリー別ナビゲーション構成へ再編しました。',
  'API方式選択時にもDDE専用項目（DDE接続待機・XLS生成待機）が常に表示されていた構成を見直し、選択中の抽出方式に応じて使用状況を明示するようにしました。',
  'ヘッダーのバージョン表示と共通設定内の「バージョン情報」から、アプリ内で更新履歴を確認できるようにしました。',
 ]},
 {'version':'V29','date':'','title':'進捗の縦積み表示とログ管理機能の強化','notes':[
  '並列実行の進捗表示を横並びから縦積みレイアウトへ変更しました。',
  '実行ログへ種別（実行処理／設定変更／実行キュー／性能計測／公開処理／エラー）の色分け表示を追加しました。',
  'ログの検索語・種別・レベルによるフィルター機能と、フィルター結果や選択行をまとめてコピーする機能を追加しました。',
  '保存期間を指定した古いログの一括削除、および選択行・表示結果の削除機能を追加しました。',
 ]},
 {'version':'V21','date':'','title':'実行キューの可視化','notes':['実行待ちの対象と処理順序を一覧表示し、順序変更・解除を行えるようにしました。']},
 {'version':'V17〜V20','date':'','title':'並列進捗モーダルの安定化','notes':['並列実行レーンの状態表示と、進捗モーダルの再表示導線を整備しました。']},
 {'version':'V13〜V16','date':'','title':'API並列実行の導入','notes':['API方式による複数ライン同時実行と、プロセス分離方式の予約キュー管理を追加しました。']},
 {'version':'V7〜V12','date':'','title':'基本レイアウトとログ基盤の整備','notes':['1画面に収まるレイアウトへ変更し、実行ログを工程単位でレポート化しました。']},
]
app=Flask(__name__); app.config['SEND_FILE_MAX_AGE_DEFAULT']=0; run_lock=threading.Lock(); stop_event=threading.Event(); status_lock=threading.Lock(); command_queue_lock=threading.RLock(); command_queue_event=threading.Event(); command_queue=[]; active_command=None
# ブラウザー側ハートビート監視。フロントからの生存信号が途絶えたら、ジョブ実行中でなく、
# かつ有効な自動実行ルールも無い場合にだけ自プロセスを終了し、閉じ忘れによるゾンビ化を防ぐ。
HEARTBEAT_TIMEOUT_SECONDS=45; heartbeat_lock=threading.Lock(); last_heartbeat_at=time.time()
# 実行中断（ユーザーによる明示キャンセル）。プロセス分離ワーカーはterminateで即時停止できるが、
# 直列(DDE/API)実行中の1件はCOM/DDE操作の途中で安全に打ち切れないため、次のジョブ開始前でのみ打ち切る。
cancel_requested=threading.Event(); active_workers_lock=threading.Lock(); active_workers={}
class RunCancelled(Exception):pass
status={'build_version':BUILD_VERSION,'running':False,'current':'','current_job_id':'','current_job_name':'','current_index':0,'total_jobs':0,'step':'idle','step_label':'待機中','step_percent':0,'completed_jobs':0,'failed_jobs':0,'started_at':'','elapsed_seconds':0,'symnavi_window':'未起動','last_result':'未実行','last_finished_at':'','error_detail':'','activity_detail':'','activity_value':'','heartbeat_at':'','parallel_lines':[],'batch_job_ids':[]}
log=logging.getLogger('navi'); log.setLevel(logging.INFO)
if not log.handlers:
 h=logging.FileHandler(BASE/'logs'/'app.log',encoding='utf-8'); h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')); log.addHandler(h)
# COMオブジェクトの明示解放が正常経路で数秒停止する環境があるため、
# Quit済みAccess.Applicationの参照だけをプロセス内に遅延保持する。
# データ作成・件数検査・Quit完了後なので、出力精度には影響させない。
_deferred_com_refs=[]
def defer_com_reference(label,obj,limit=20):
 try:
  if obj is not None:
   _deferred_com_refs.append((label,obj,time.time()))
   if len(_deferred_com_refs)>limit:del _deferred_com_refs[:len(_deferred_com_refs)-limit]
 except Exception:pass

def settings_connection():
 c=sqlite3.connect(SETTINGS_DB,timeout=30)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 return c

def init_settings_db():
 with settings_connection() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL,value_type TEXT NOT NULL DEFAULT 'text',updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,display_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,name TEXT NOT NULL,rne TEXT NOT NULL,rne_path TEXT NOT NULL,output_folder TEXT NOT NULL,output_format TEXT NOT NULL,output_file TEXT NOT NULL,table_name TEXT NOT NULL,sheet_name TEXT NOT NULL,read_type TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY,job_id TEXT NOT NULL,display_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,name TEXT NOT NULL,schedule_type TEXT NOT NULL,time_value TEXT,interval_minutes INTEGER,weekdays_json TEXT,month_days_json TEXT,dates_json TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
  CREATE TABLE IF NOT EXISTS scheduler_state (state_key TEXT PRIMARY KEY,state_value TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY,value TEXT NOT NULL);
  """)
  c.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('schema_version','1')")

def _decode_setting(row):
 v=row['value']; t=row['value_type']
 if t=='json':return json.loads(v)
 if t=='bool':return v=='1'
 if t=='int':return int(v)
 return v

def _encode_setting(value):
 if isinstance(value,bool):return ('1' if value else '0','bool')
 if isinstance(value,int):return (str(value),'int')
 if isinstance(value,(dict,list)):return (json.dumps(value,ensure_ascii=False),'json')
 return (str(value),'text')

def normalize_output_format(value,filename=''):
 fmt=str(value or '').strip().lower()
 aliases={'sqlite':'sqlite3','db':'sqlite3','access':'accdb','excel':'xlsx','xls':'xlsx'}
 fmt=aliases.get(fmt,fmt)
 ext=Path(str(filename or '')).suffix.lower()
 ext_map={'.sqlite':'sqlite3','.sqlite3':'sqlite3','.db':'sqlite3','.accdb':'accdb','.xlsx':'xlsx','.csv':'csv','.txt':'txt'}
 if fmt not in ('sqlite3','txt','csv','xlsx','accdb'):fmt=ext_map.get(ext,'sqlite3')
 return fmt

def canonical_output_file(filename,fmt):
 ext={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[fmt]
 stem=Path(str(filename or 'output')).stem
 for suffix in ('sqlite3','sqlite','accdb','xlsx','xls','csv','txt'):
  if stem.lower().endswith(suffix):stem=stem[:-len(suffix)]
 return (stem or 'output')+ext

def validate_output_contract(job,stage):
 configured=str(job.get('output_format') or '').lower(); filename=str(job.get('output_file') or '')
 effective=normalize_output_format(configured,filename); expected={'sqlite3':'.sqlite3','txt':'.txt','csv':'.csv','xlsx':'.xlsx','accdb':'.accdb'}[effective]; actual=Path(filename).suffix.lower(); match=configured==effective and actual==expected
 log.info('出力形式確認 stage=%s job=%s configured=%s effective=%s file=%s actual_ext=%s expected_ext=%s match=%s',stage,job.get('name'),configured,effective,filename,actual or '(なし)',expected,match)
 if not match:raise ValueError(f'出力形式不一致: 設定={configured}, 実効={effective}, ファイル={filename}, 期待拡張子={expected}')
 return effective

def load():
 init_settings_db()
 with settings_connection() as c:
  cfg={r['key']:_decode_setting(r) for r in c.execute('SELECT key,value,value_type FROM app_settings')}; jobs=[]
  for r in c.execute('SELECT * FROM jobs ORDER BY display_order,id'):
   rules=[]
   for x in c.execute('SELECT * FROM schedules WHERE job_id=? ORDER BY display_order,id',(r['id'],)):
    q={'id':x['id'],'enabled':bool(x['enabled']),'name':x['name'],'type':x['schedule_type'],'time':x['time_value'] or '06:00'}
    if x['interval_minutes'] is not None:q['interval_minutes']=x['interval_minutes']
    if x['weekdays_json']:q['weekdays']=json.loads(x['weekdays_json'])
    if x['month_days_json']:q['month_days']=json.loads(x['month_days_json'])
    if x['dates_json']:q['dates']=json.loads(x['dates_json'])
    rules.append(q)
   fmt=normalize_output_format(r['output_format'],r['output_file']); jobs.append({'id':r['id'],'enabled':bool(r['enabled']),'name':r['name'],'rne':r['rne'],'rne_path':r['rne_path'],'output_folder':r['output_folder'],'output_format':fmt,'output_file':canonical_output_file(r['output_file'],fmt),'table':r['table_name'],'sheet':r['sheet_name'],'type':r['read_type'],'schedules':rules})
  cfg['jobs']=jobs; cfg.setdefault('settings',{}); cfg['settings'].setdefault('extract_engine','api'); stable_migration='stability_profile' not in cfg['settings']; cfg['settings'].setdefault('stability_profile','stable_api_serial'); cfg['settings'].setdefault('api_parallel_lines',1); cfg['settings'].setdefault('api_parallel_max_lines',8); cfg['settings'].setdefault('api_parallel_model','process');
  if stable_migration: cfg['settings']['api_parallel_lines']=1
  cfg.setdefault('navigator_api_dll',r'C:\NAVIAP\debugdllVC14x64\SymNaviA.dll'); cfg.setdefault('accdb_template','.\\assets\\empty.accdb'); return cfg

def save(v):
 init_settings_db(); now=datetime.now().isoformat(timespec='seconds'); jobs=v.get('jobs',[]); top={k:x for k,x in v.items() if k not in ('jobs','credential_status')}
 with settings_connection() as c:
  c.execute('BEGIN IMMEDIATE'); c.execute('DELETE FROM app_settings')
  for key,value in top.items():
   encoded,kind=_encode_setting(value); c.execute('INSERT INTO app_settings VALUES(?,?,?,?)',(key,encoded,kind,now))
  keep=[]
  for order,j in enumerate(jobs):
   jid=j.get('id') or str(uuid.uuid4()); keep.append(jid)
   fmt=normalize_output_format(j.get('output_format'),j.get('output_file')); output_file=canonical_output_file(j.get('output_file'),fmt); log.info('設定保存 job=%s requested_format=%s saved_format=%s requested_file=%s saved_file=%s',j.get('name'),j.get('output_format'),fmt,j.get('output_file'),output_file); c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,order,int(bool(j.get('enabled',True))),j.get('name',''),j.get('rne',''),j.get('rne_path',''),j.get('output_folder',''),fmt,output_file,j.get('table','仕掛'),j.get('sheet','Page1'),j.get('type','詳細データ'),now))
   c.execute('DELETE FROM schedules WHERE job_id=?',(jid,))
   for ro,q in enumerate(j.get('schedules',[])):
    c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(q.get('id') or str(uuid.uuid4()),jid,ro,int(bool(q.get('enabled',True))),q.get('name','実行ルール'),q.get('type','daily'),q.get('time','06:00'),q.get('interval_minutes'),json.dumps(q.get('weekdays'),ensure_ascii=False) if 'weekdays' in q else None,json.dumps(q.get('month_days'),ensure_ascii=False) if 'month_days' in q else None,json.dumps(q.get('dates'),ensure_ascii=False) if 'dates' in q else None,now))
  if keep:c.execute('DELETE FROM jobs WHERE id NOT IN ('+','.join('?' for _ in keep)+')',keep)
  else:c.execute('DELETE FROM jobs')

def migrate_legacy_settings():
 init_settings_db()
 with settings_connection() as c:count=c.execute('SELECT COUNT(*) FROM app_settings').fetchone()[0]
 if count or not LEGACY_CFG.exists():return
 data=json.loads(LEGACY_CFG.read_text(encoding='utf-8')); save(data); backup=BASE/'config.migrated.json'
 if not backup.exists():shutil.copy2(LEGACY_CFG,backup)
 LEGACY_CFG.unlink(); log.info('config.jsonをapp_settings.sqlite3へ移行しました backup=%s',backup)

def load_scheduler_state():
 init_settings_db()
 with settings_connection() as c:return {r['state_key']:r['state_value'] for r in c.execute('SELECT * FROM scheduler_state')}

def save_scheduler_state(key,value):
 with settings_connection() as c:c.execute('INSERT OR REPLACE INTO scheduler_state VALUES(?,?,?)',(key,value,datetime.now().isoformat(timespec='seconds')))

def set_status(**v):
 with status_lock: status.update(v)

def update_parallel_line(line,**v):
 with status_lock:
  lines=[dict(x) for x in status.get('parallel_lines',[]) if x.get('line')!=line]
  current={'line':line,'job':'','state':'待機','percent':0,'elapsed':0,'detail':''}
  current.update(v); lines.append(current); lines.sort(key=lambda x:x.get('line',''))
  status['parallel_lines']=lines
  ipc_path=os.environ.get('NAVI_WORKER_STATUS')
  if ipc_path:
   try:
    payload=dict(current,updated_at=datetime.now().isoformat(timespec='milliseconds'),pid=os.getpid())
    tmp=Path(ipc_path+'.tmp'); tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,ipc_path)
   except Exception:pass


def resolve_path(value,base=BASE):
 """Resolve absolute, UNC, or app-relative paths without changing stored values."""
 if value is None:return base
 raw=os.path.expandvars(os.path.expanduser(str(value).strip()))
 p=Path(raw)
 if p.is_absolute() or raw.startswith('\\'):return p
 return (Path(base)/p).resolve()

def display_path(value):
 try:return str(resolve_path(value))
 except:return str(value)

def resolve_rne_path(job,cfg):
 """Canonical RNE resolution shared by diagnosis and execution."""
 value=str(job.get('rne_path') or job.get('rne') or '').strip()
 if not value:return resolve_path(job.get('rne',''),resolve_path(cfg.get('rne_folder','.\\rne')))
 raw=os.path.expandvars(os.path.expanduser(value))
 p=Path(raw)
 if p.is_absolute() or raw.startswith('\\\\'):return p
 # Explicit relative paths (./, ../, .\, ..\) are app-root relative.
 if raw.startswith(('.\\','..\\','./','../')):return resolve_path(raw,BASE)
 # Bare filename is relative to configured RNE base folder.
 return resolve_path(raw,resolve_path(cfg.get('rne_folder','.\\rne')))

def dde_staging_folder():
 """Use a short local ASCII-only folder for SymfoNavi DDE Save."""
 candidates=[Path(os.environ.get('LOCALAPPDATA',''))/'NaviToSQLite'/'dde_work',Path(tempfile.gettempdir())/'NaviToSQLiteDDE',Path('C:/NaviToSQLiteWork')]
 for p in candidates:
  try:
   text=str(p)
   if not text.isascii():continue
   p.mkdir(parents=True,exist_ok=True)
   test=p/'.write_test'; test.write_text('ok',encoding='ascii'); test.unlink()
   return p
  except Exception:continue
 raise RuntimeError('SymfoNavi用のローカル一時フォルダーを作成できません')

def api_data_source_profiles(path):
 # 公式APIサンプルにある追加データソース接続を、明示されたCONFセクションだけから構成する。
 cp=configparser.ConfigParser(interpolation=None); cp.optionxform=str.lower
 for enc in ('cp932','utf-8-sig','utf-8'):
  try:cp.read(path,encoding=enc);break
  except UnicodeDecodeError:continue
 profiles=[]
 supported={'apioracle':'oracle','apisqlserver':'sqlserver','apirda':'rda','apipostgres':'postgres','apiresource':'resource','apiresourcenoauth':'noauth'}
 for section in cp.sections():
  compact=''.join(ch for ch in section.lower() if ch.isalnum())
  kind=supported.get(compact)
  if not kind:continue
  d={k.lower():v.strip() for k,v in cp.items(section)}
  enabled=str(d.get('enabled','yes')).lower() not in ('0','no','false','off')
  if not enabled:continue
  profiles.append({'section':section,'kind':kind,'user':d.get('user',d.get('userid','')),'password':d.get('password',d.get('passwd','')),'server':d.get('server',''),'option':d.get('option',d.get('opt','')),'resource':d.get('resource',d.get('resourcename','')),'resource_kind':d.get('resource_kind',d.get('resourcekind','0'))})
 return profiles
def creds(path):
 cp=configparser.ConfigParser(interpolation=None); cp.optionxform=str.lower
 for enc in ('cp932','utf-8-sig','utf-8'):
  try: cp.read(path,encoding=enc); break
  except UnicodeDecodeError: continue
 if not cp.sections(): raise ValueError('symnavim.confを読み取れません')
 sec='Default' if cp.has_section('Default') else next((x for x in cp.sections() if x.lower().startswith('connect_')),cp.sections()[0])
 d={k.lower():v.strip() for k,v in cp.items(sec)}; a=(d.get('symnaviuserid',''),d.get('symnavipasswd',''),d.get('symnaviserver',''))
 if not all(a): raise ValueError(f'[{sec}]にSymNaviUSERID、SymNaviPASSWD、SymNaviServerが必要です')
 return *a,sec

_wmi_warning_reported=False
def symnavi_process_ids(root_pid):
 """Return the launched process and descendant process IDs using WMI."""
 global _wmi_warning_reported
 ids={root_pid}; pythoncom=None
 try:
  import pythoncom, win32com.client
  pythoncom.CoInitialize()
  svc=win32com.client.GetObject(r'winmgmts:\\.\root\cimv2')
  rows=list(svc.ExecQuery('SELECT ProcessId,ParentProcessId,Name FROM Win32_Process'))
  changed=True
  while changed:
   changed=False
   for item in rows:
    pid=int(item.ProcessId); ppid=int(item.ParentProcessId); name=str(item.Name or '').lower()
    if ppid in ids or name in ('symnavi.exe','symnavim.exe'):
     if pid not in ids:ids.add(pid); changed=True
 except Exception as e:
  if not _wmi_warning_reported:
   log.warning('SymfoNavi子プロセス列挙を省略し、PID・タイトル検出を継続します: %s',e); _wmi_warning_reported=True
 finally:
  if pythoncom:
   try:pythoncom.CoUninitialize()
   except:pass
 return ids

def hide_symnavi_windows(proc,wait_seconds=0.8):
 """Hide currently visible SymfoNavi windows and confirm that they became hidden."""
 try:
  import win32con, win32gui, win32process
  deadline=time.time()+max(.1,wait_seconds); hidden=set(); remaining=[]
  while time.time()<deadline:
   pids=symnavi_process_ids(proc.pid); candidates=[]
   def each(hwnd,_):
    try:
     _,pid=win32process.GetWindowThreadProcessId(hwnd)
     title=win32gui.GetWindowText(hwnd).lower(); cls=win32gui.GetClassName(hwnd).lower()
     if win32gui.IsWindowVisible(hwnd) and (pid in pids or 'symnavi' in title or 'navigator' in title or 'symnavi' in cls):candidates.append(hwnd)
    except:pass
   win32gui.EnumWindows(each,None)
   if not candidates:return len(hidden),[]
   for hwnd in candidates:
    try:
     win32gui.ShowWindow(hwnd,win32con.SW_HIDE)
     if not win32gui.IsWindowVisible(hwnd):hidden.add(hwnd)
    except:pass
   time.sleep(.08)
   remaining=[]
   def confirm(hwnd,_):
    try:
     _,pid=win32process.GetWindowThreadProcessId(hwnd)
     title=win32gui.GetWindowText(hwnd).lower(); cls=win32gui.GetClassName(hwnd).lower()
     if win32gui.IsWindowVisible(hwnd) and (pid in pids or 'symnavi' in title or 'navigator' in title or 'symnavi' in cls):remaining.append(hwnd)
    except:pass
   win32gui.EnumWindows(confirm,None)
   if not remaining:return len(hidden),[]
  return len(hidden),remaining
 except Exception as e:
  log.warning('SymfoNaviウィンドウ非表示失敗: %s',e); return 0,[]

def symnavi_hide_options(settings):
 profile=str(settings.get('symnavi_hide_profile','balanced'))
 presets={
  'action_only':{'watch':False,'watch_interval':0.0,'action_duration':0.35,'action_interval':0.35},
  'light':{'watch':True,'watch_interval':3.0,'action_duration':0.35,'action_interval':0.35},
  'balanced':{'watch':True,'watch_interval':2.0,'action_duration':0.5,'action_interval':0.5},
  'standard':{'watch':True,'watch_interval':1.0,'action_duration':0.6,'action_interval':0.5},
  'custom':{'watch':bool(settings.get('symnavi_hide_watch_enabled',True)),'watch_interval':max(1.0,float(settings.get('symnavi_hide_interval_seconds',2.0))),'action_duration':max(0.2,float(settings.get('symnavi_hide_action_duration_seconds',0.5))),'action_interval':max(0.2,float(settings.get('symnavi_hide_action_interval_seconds',0.5)))}
 }
 return profile,presets.get(profile,presets['balanced'])

def hide_after_action(proc,action,settings,settle_seconds=None):
 profile,opt=symnavi_hide_options(settings)
 duration=opt['action_duration'] if settle_seconds is None else min(float(settle_seconds),opt['action_duration'])
 started=time.time(); total=0; visible=[]
 while True:
  count,visible=hide_symnavi_windows(proc,min(.35,opt['action_interval'])); total+=count
  if time.time()-started>=duration or (count==0 and not visible):break
  time.sleep(opt['action_interval'])
 state='非表示確認済み' if not visible else f'次回監視待ち({len(visible)})'
 set_status(symnavi_window=state,activity_detail=f'{action}後の画面状態を確認',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
 log.info('SymfoNavi非表示 action=%s profile=%s hidden=%s remaining=%s',action,profile,total,len(visible))

def hide_after_action_async(proc,action,settings):
 # Periodic profiles already watch new windows. Running another WMI/window scan in parallel severely slows DDE and ACE.
 profile,opt=symnavi_hide_options(settings)
 if opt['watch']:
  log.info('SymfoNavi操作直後監視を省略 action=%s profile=%s reason=定期監視有効',action,profile); return
 def worker():
  try:hide_after_action(proc,action,settings)
  except Exception as e:log.warning('SymfoNavi非表示失敗 action=%s error=%s',action,e)
 threading.Thread(target=worker,daemon=True,name='hide-'+action.replace(' ','_')).start()

def start_hidden_symnavi(proc,settings):
 hide_after_action(proc,'DDE接続',settings)
 return None

def hide_window_watcher(proc,stop_flag,settings):
 try:
  import win32con,win32gui,win32process
  profile,opt=symnavi_hide_options(settings)
  interval=max(1.0,opt['watch_interval'])
  pids=symnavi_process_ids(proc.pid); refreshed=0.0; hidden=set()
  log.info('SymfoNavi定期監視開始 profile=%s interval=%.1fs',profile,interval)
  while not stop_flag.wait(interval):
   now=time.time()
   if now-refreshed>max(30.0,interval*10):pids=symnavi_process_ids(proc.pid);refreshed=now
   visible=[]
   def each(hwnd,_):
    try:
     _,pid=win32process.GetWindowThreadProcessId(hwnd); title=win32gui.GetWindowText(hwnd).lower(); cls=win32gui.GetClassName(hwnd).lower()
     if win32gui.IsWindowVisible(hwnd) and (pid in pids or 'symnavi' in title or 'navigator' in title or 'symnavi' in cls):visible.append(hwnd)
    except:pass
   win32gui.EnumWindows(each,None)
   for hwnd in visible:
    try:win32gui.ShowWindow(hwnd,win32con.SW_HIDE);hidden.add(hwnd)
    except:pass
   if visible:set_status(symnavi_window=f'非表示監視 / {interval:g}秒間隔 / {len(visible)}件処理',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
  log.info('SymfoNavi定期監視終了 hidden_handles=%s',len(hidden))
 except Exception as e:log.warning('SymfoNavi定期監視失敗: %s',e)

def start_window_watcher(proc,settings):
 profile,opt=symnavi_hide_options(settings)
 if not opt['watch']:
  log.info('SymfoNavi定期監視なし profile=%s',profile); return None,None
 flag=threading.Event(); thread=threading.Thread(target=hide_window_watcher,args=(proc,flag,settings),daemon=True); thread.start(); return flag,thread

def phase_log(phase,started=None,**values):
 parts=' '.join(f'{k}={v}' for k,v in values.items())
 if started is None:
  log.info('STEP_START phase=%s %s',phase,parts)
  for h in log.handlers:h.flush()
  return time.perf_counter()
 elapsed=time.perf_counter()-started
 log.info('STEP_END phase=%s elapsed=%.2fs %s',phase,elapsed,parts)
 for h in log.handlers:h.flush()
 return elapsed

def progress(step,label,percent,**extra):
 set_status(step=step,step_label=label,step_percent=percent,current=label,elapsed_seconds=max(0,int(time.time()-getattr(progress,'started',time.time()))),heartbeat_at=datetime.now().isoformat(timespec='seconds'),**extra)

def dde_connect(seconds):
 try: import win32ui, dde
 except Exception as e: raise RuntimeError('pywin32のDDE機能を読み込めません') from e
 srv=dde.CreateServer(); srv.Create('NaviToSQLiteClient'); conv=dde.CreateConversation(srv); end=time.time()+seconds; last=''
 while time.time()<end:
  try: conv.ConnectTo('SymNavi','Macro'); time.sleep(5); log.info('DDE接続完了'); return srv,conv
  except Exception as e: last=str(e); time.sleep(1)
 try:srv.Shutdown()
 except:pass
 raise TimeoutError('DDE接続タイムアウト: '+last)
def dde_exec(conv,name,text,expected_output=None):
 last=None
 for attempt in range(1,4):
  done=threading.Event(); started=time.time()
  def heartbeat():
   while not done.wait(5):
    elapsed=int(time.time()-started)
    set_status(activity_detail=f'DDE {name} 実行中',activity_value=f'{elapsed}秒経過。SymfoNaviの応答を待っています',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
    log.info('DDE待機中 command=%s attempt=%s elapsed=%ss',name,attempt,elapsed)
  threading.Thread(target=heartbeat,daemon=True,name='dde-heartbeat-'+name).start()
  try:
   log.info('DDE実行開始 command=%s attempt=%s text=%s',name,attempt,text)
   conv.Exec(text); done.set()
   elapsed=time.time()-started; log.info('DDE実行完了 command=%s attempt=%s elapsed=%.2fs',name,attempt,elapsed)
   time.sleep(.2); return
  except Exception as e:
   done.set(); last=e; elapsed=time.time()-started
   # SymfoNavi can return Exec failed after completing the Save. Do not repeat the full extraction when output exists.
   if expected_output:
    candidate=Path(expected_output)
    for _ in range(10):
     if candidate.exists() and candidate.stat().st_size>0:
      log.warning('DDE応答エラーだが出力ファイルを検出したため再実行を省略 command=%s attempt=%s elapsed=%.2fs file=%s size=%s error=%s',name,attempt,elapsed,candidate,candidate.stat().st_size,e); return
     time.sleep(.5)
   if name=='Open':
    log.warning('DDE Open応答タイムアウト。重複Openによる確認ダイアログを防ぐため再実行せず次工程で検証します elapsed=%.2fs error=%s',elapsed,e)
    set_status(activity_detail='RNE Open応答待ちを終了',activity_value='重複Openを防止し、XLS生成工程で実状態を検証します',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
    return
   log.warning('DDE失敗 command=%s attempt=%s elapsed=%.2fs error=%s',name,attempt,elapsed,e); time.sleep(2)
 raise RuntimeError(f'DDE {name}失敗: {last}; command={text}')

def validate_xls_complete(path,job):
 try:
  import xlrd
  book=xlrd.open_workbook(str(path),on_demand=True)
  try:
   sheet=book.sheet_by_name(job.get('sheet','Page1'))
   return sheet.nrows>0 and sheet.ncols>0, f'{sheet.nrows:,} rows / {sheet.ncols:,} columns'
  finally:book.release_resources()
 except Exception as e:return False,str(e)

def wait_file(p,seconds,job):
 end=time.time()+seconds; old=-1; stable=0; started=time.time(); last_validation='未検証'
 while time.time()<end:
  elapsed=int(time.time()-started)
  if p.exists():
   size=p.stat().st_size; stable=stable+1 if size>0 and size==old else 0; old=size
   if stable>=5:
    ok,last_validation=validate_xls_complete(p,job)
    if ok:
     set_status(activity_detail='中間XLSの完成を確認しました',activity_value=f'{size:,} bytes / {last_validation} / {elapsed}秒',heartbeat_at=datetime.now().isoformat(timespec='seconds')); return size
    stable=0
   set_status(activity_detail='中間XLSを書き込み中',activity_value=f'{size:,} bytes / 安定確認 {stable}/5 / {elapsed}秒 / {last_validation}',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
  else:set_status(activity_detail='SymfoNaviからの中間XLS生成を待機中',activity_value=f'未検出 / {elapsed}秒経過',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
  time.sleep(1)
 raise TimeoutError(f'一時XLSが完成しません: {p}; 最終サイズ={old:,} bytes; 検証={last_validation}')

def unique_headers(values):
 out=[]; used={}
 for i,x in enumerate(values,1):
  name=str(x or '').replace('\r','').replace('\n','').strip() or f'Column{i}'; used[name]=used.get(name,0)+1; out.append(name if used[name]==1 else f'{name}_{used[name]}')
 return out
def qi(s): return '"'+str(s).replace('"','""')+'"'
def read_extract(source,job,reject,expected_rows=None,expected_cols=None):
 source=Path(source); started=time.perf_counter()
 if source.suffix.lower()=='.csv':
  rows=None; encoding_used=''
  last_error=None
  for encoding in ('cp932','utf-8-sig','utf-8'):
   try:
    with source.open('r',encoding=encoding,errors='strict',newline='') as f:rows=list(csv.reader(f))
    encoding_used=encoding;break
   except UnicodeDecodeError as e:last_error=e
  if rows is None:raise UnicodeError(f'API中間CSVの文字コードを判定できません: {source}: {last_error}')
  source_kind='api_csv'
 else:
  import xlrd
  b=xlrd.open_workbook(str(source),on_demand=True)
  try: sh=b.sheet_by_name(job.get('sheet','Page1')); rows=[sh.row_values(i) for i in range(sh.nrows)]
  finally:b.release_resources()
  encoding_used='binary';source_kind='dde_xls'
 if job.get('type')=='集計表' and rows:rows=rows[1:]
 if not rows:raise ValueError(f'{source.suffix}にデータがありません')
 hs=unique_headers(rows[0]);body=[]
 for row in rows[1:]:body.append([str(x) if x is not None else '' for x in list(row[:len(hs)])+['']*max(0,len(hs)-len(row))])
 if reject and not body:raise ValueError('抽出0件のため出力を中止しました')
 row_match=expected_rows is None or len(body)==int(expected_rows)
 col_match=expected_cols is None or len(hs)==int(expected_cols)
 log.info('INTERMEDIATE_VALIDATION kind=%s file=%s encoding=%s size=%s rows=%s columns=%s expected_rows=%s expected_columns=%s row_match=%s column_match=%s elapsed=%.2fs',source_kind,source,encoding_used,source.stat().st_size,len(body),len(hs),expected_rows,expected_cols,row_match,col_match,time.perf_counter()-started)
 if not row_match or not col_match:raise RuntimeError(f'中間データ件数検査に失敗 expected={expected_rows}x{expected_cols} actual={len(body)}x{len(hs)}')
 return hs,body


def _xlsx_col_name(index):
 name=''
 while index:
  index,rem=divmod(index-1,26); name=chr(65+rem)+name
 return name or 'A'
def _xlsx_xml_text(value):
 s='' if value is None else str(value)
 s=''.join(ch for ch in s if ch in ('\t','\n','\r') or ord(ch)>=32)
 return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def write_xlsx_direct(dst,sheet_name,headers,body):
 # Write a minimal XLSX directly as ZIP/XML. All cells are inline strings to preserve values exactly.
 import zipfile
 sheet_name=(sheet_name or 'Page1')[:31]
 started=time.perf_counter(); rows_written=0; cell_count=0
 with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  z.writestr('[Content_Types].xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>''')
  z.writestr('_rels/.rels','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''')
  z.writestr('xl/_rels/workbook.xml.rels','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
  safe_sheet=sheet_name.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
  z.writestr('xl/workbook.xml',f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>''')
  z.writestr('xl/styles.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Yu Gothic"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>''')
  z.writestr('docProps/app.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>SymfoNavi Data Hub</Application></Properties>''')
  z.writestr('docProps/core.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>SymfoNavi Data Hub</dc:creator><cp:lastModifiedBy>SymfoNavi Data Hub</cp:lastModifiedBy></cp:coreProperties>''')
  def row_xml(row_index,row):
   nonlocal cell_count
   cells=[]
   for c,v in enumerate(row,1):
    ref=f'{_xlsx_col_name(c)}{row_index}'; cell_count+=1
    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_xml_text(v)}</t></is></c>')
   return f'<row r="{row_index}">'+''.join(cells)+'</row>'
  last_col=_xlsx_col_name(len(headers)); last_row=len(body)+1
  with z.open('xl/worksheets/sheet1.xml','w') as f:
   f.write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:{last_col}{last_row}"/><sheetData>'.encode('utf-8'))
   f.write(row_xml(1,headers).encode('utf-8'))
   for r,row in enumerate(body,2):
    f.write(row_xml(r,row).encode('utf-8')); rows_written+=1
   f.write(b'</sheetData></worksheet>')
 return {'sheet':sheet_name,'rows':rows_written,'columns':len(headers),'cells':cell_count,'elapsed':time.perf_counter()-started}
def verify_xlsx_direct(dst,expected_columns):
 import zipfile,re
 started=time.perf_counter()
 with zipfile.ZipFile(dst,'r') as z:
  bad=z.testzip();names=set(z.namelist());required={'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'};missing=sorted(required-names)
  head=z.read('xl/worksheets/sheet1.xml')[:65536].decode('utf-8',errors='ignore')
 if bad or missing:raise RuntimeError(f'XLSX ZIP構造検査失敗 bad={bad} missing={missing}')
 m=re.search(r'<row[^>]*r="1"[^>]*>(.*?)</row>',head,re.S); header_columns=len(re.findall(r'<c\b',m.group(1))) if m else 0
 log.info('XLSX_LIGHT_VERIFY_DIRECT header_columns=%s expected_columns=%s elapsed=%.2fs',header_columns,expected_columns,time.perf_counter()-started)
 if header_columns!=expected_columns:raise RuntimeError(f'XLSX列数検査失敗 expected={expected_columns} actual={header_columns}')
 log.info('XLSX_ZIP_TEST bad_entry=%s missing_required=%s entries=%s elapsed=%.2fs',bad,missing,len(names),time.perf_counter()-started)

def verify_xlsx_fast(dst,expected_columns):
 import zipfile,re
 started=time.perf_counter()
 with zipfile.ZipFile(dst,'r') as z:
  names=set(z.namelist());required={'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'};missing=sorted(required-names)
  if missing:raise RuntimeError(f'XLSX必須XML不足 missing={missing}')
  head=z.read('xl/worksheets/sheet1.xml')[:65536].decode('utf-8',errors='ignore')
 m=re.search(r'<row[^>]*r="1"[^>]*>(.*?)</row>',head,re.S); header_columns=len(re.findall(r'<c\b',m.group(1))) if m else 0
 log.info('XLSX_FAST_VERIFY header_columns=%s expected_columns=%s elapsed=%.2fs',header_columns,expected_columns,time.perf_counter()-started)
 if header_columns!=expected_columns:raise RuntimeError(f'XLSX列数検査失敗 expected={expected_columns} actual={header_columns}')
 return header_columns

def prewarm_access_async(reason='accdb'):
 def worker():
  pythoncom=None;access_app=None;started=time.perf_counter()
  log.info('ACCDB_PREWARM_START reason=%s',reason)
  try:
   import pythoncom,win32com.client
   pythoncom.CoInitialize()
   dispatch_started=time.perf_counter();access_app=win32com.client.DispatchEx('Access.Application');dispatch_elapsed=time.perf_counter()-dispatch_started
   try:access_app.Visible=False
   except Exception:pass
   quit_started=time.perf_counter()
   try:access_app.Quit(2)
   except TypeError:access_app.Quit()
   quit_elapsed=time.perf_counter()-quit_started
   log.info('ACCDB_PREWARM_END reason=%s dispatch_elapsed=%.2fs quit_elapsed=%.2fs total_elapsed=%.2fs',reason,dispatch_elapsed,quit_elapsed,time.perf_counter()-started)
  except Exception as e:
   log.warning('ACCDB_PREWARM_FAILED reason=%s error=%s elapsed=%.2fs',reason,e,time.perf_counter()-started)
  finally:
   access_app=None
   if pythoncom:
    try:pythoncom.CoUninitialize()
    except Exception:pass
 t=threading.Thread(target=worker,daemon=True,name='accdb-prewarm')
 t.start();return t

def export_data(source,dst,job,reject,expected_rows=None,expected_cols=None):
 parse_started=phase_log('intermediate_parse',job=job.get('name'),source=source);hs,body=read_extract(source,job,reject,expected_rows,expected_cols);phase_log('intermediate_parse',parse_started,job=job.get('name'),rows=len(body),columns=len(hs));fmt=validate_output_contract(job,'export'); log.info('出力開始 configured_format=%s effective_format=%s configured_file=%s work_file=%s rows=%s columns=%s',job.get('output_format'),fmt,job.get('output_file'),dst,len(body),len(hs))
 if dst.exists():dst.unlink()
 if fmt=='sqlite3':
  sqlite_started=time.perf_counter();c=sqlite3.connect(dst)
  try:
   c.execute('PRAGMA synchronous=FULL'); c.execute(f'CREATE TABLE {qi(job["table"])} ('+', '.join(qi(x)+' TEXT' for x in hs)+')')
   insert_started=time.perf_counter()
   if body:c.executemany(f'INSERT INTO {qi(job["table"])} VALUES ('+','.join('?' for _ in hs)+')',body)
   log.info('SQLITE_INSERT rows=%s columns=%s elapsed=%.2fs',len(body),len(hs),time.perf_counter()-insert_started)
   c.execute('CREATE TABLE _更新情報 (項目 TEXT PRIMARY KEY, 値 TEXT)'); c.executemany('INSERT INTO _更新情報 VALUES (?,?)',[('作成日時',datetime.now().isoformat(timespec='seconds')),('RNE',job['rne']),('件数',str(len(body)))])
   c.commit(); ck=c.execute('PRAGMA integrity_check').fetchone()[0]; ct=c.execute(f'SELECT COUNT(*) FROM {qi(job["table"])}').fetchone()[0]
   if ck!='ok' or ct!=len(body):raise RuntimeError('SQLite整合性検査に失敗')
   log.info('SQLITE_VALIDATION integrity=%s rows=%s expected_rows=%s total_elapsed=%.2fs',ck,ct,len(body),time.perf_counter()-sqlite_started)
  finally:c.close()
 elif fmt in ('csv','txt'):
  delimiter=',' if fmt=='csv' else '\t';write_started=time.perf_counter()
  with dst.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.writer(f,delimiter=delimiter,quoting=csv.QUOTE_MINIMAL);w.writerow(hs);w.writerows(body)
  log.info('DELIMITED_WRITE format=%s encoding=utf-8-sig rows=%s columns=%s size=%s elapsed=%.2fs',fmt,len(body),len(hs),dst.stat().st_size,time.perf_counter()-write_started)
 elif fmt=='xlsx':
  # openpyxlのセル逐次appendが環境により極端に遅くなるため、XLSXをZIP/XMLとして直接生成する。
  # すべてinline stringで保存し、中間CSVの内容を文字列として保持する。
  try:
   write_started=time.perf_counter();info=write_xlsx_direct(dst,job.get('sheet') or 'Page1',hs,body)
   log.info('XLSX_DIRECT_WRITE mode=zip_xml sheet=%s rows=%s columns=%s cells=%s size=%s elapsed=%.2fs',info['sheet'],info['rows'],info['columns'],info['cells'],dst.stat().st_size,time.perf_counter()-write_started)
   if info['rows']!=len(body):raise RuntimeError(f'XLSX書込み件数不一致 expected={len(body)} actual={info["rows"]}')
   verify_xlsx_direct(dst,len(hs))
  except Exception as e:
   try:
    if dst.exists():dst.unlink()
   except:pass
   raise RuntimeError('EXCEL(xlsx)出力失敗: '+str(e)) from e
 elif fmt=='accdb':
  pythoncom=None;access_app=None;current_db=None;dao_rs=None;conn=None;rs=None;bulk_dir=None
  template=Path(str(job.get('_accdb_template') or resolve_path('.\\assets\\empty.accdb')))
  if not template.is_file():raise FileNotFoundError(f'ACCDB空テンプレートがありません: {template}')
  if template.suffix.lower()!='.accdb':raise ValueError(f'ACCDBテンプレートの拡張子が不正です: {template}')
  if template.stat().st_size==0:raise ValueError(f'ACCDBテンプレートが空ファイルです: {template}')
  try:
   cache_started=time.perf_counter();cache_dir=dde_staging_folder()/'assets';cache_dir.mkdir(parents=True,exist_ok=True);cached_template=cache_dir/'empty.accdb'
   source_stat=template.stat();cache_hit=False
   if cached_template.is_file():
    cs=cached_template.stat();cache_hit=cs.st_size==source_stat.st_size and cs.st_mtime_ns==source_stat.st_mtime_ns
   if not cache_hit:
    tmp=cache_dir/'.empty.accdb.incoming';shutil.copy2(template,tmp);os.replace(tmp,cached_template)
   log.info('ACCDB_TEMPLATE_CACHE source=%s cache=%s hit=%s size=%s elapsed=%.2fs',template,cached_template,cache_hit,cached_template.stat().st_size,time.perf_counter()-cache_started)
   copy_started=time.perf_counter();shutil.copy2(cached_template,dst)
   if not dst.exists() or dst.stat().st_size!=cached_template.stat().st_size:raise IOError('ACCDBテンプレートのコピー検証に失敗しました')
   log.info('ACCDB_TEMPLATE_COPY file=%s size=%s elapsed=%.2fs',dst,dst.stat().st_size,time.perf_counter()-copy_started)
   bulk_dir=dst.parent/f'{dst.stem}_bulk';shutil.rmtree(bulk_dir,ignore_errors=True);bulk_dir.mkdir(parents=True,exist_ok=True)
   bulk_csv=bulk_dir/'bulk.csv';schema_file=bulk_dir/'schema.ini';prep_started=time.perf_counter()
   with bulk_csv.open('w',encoding='cp932',errors='strict',newline='') as f:
    w=csv.writer(f,lineterminator='\r\n',quoting=csv.QUOTE_MINIMAL);w.writerow(hs);w.writerows(body)
   schema_lines=['[bulk.csv]','Format=CSVDelimited','ColNameHeader=True','CharacterSet=932','MaxScanRows=0']
   for i,h in enumerate(hs,1):schema_lines.append(f'Col{i}="{str(h).replace(chr(34),chr(34)*2)}" LongChar')
   schema_file.write_text('\r\n'.join(schema_lines)+'\r\n',encoding='cp932',errors='strict')
   log.info('ACCDB_BULK_PREP csv=%s schema=%s encoding=cp932 bom=False rows=%s columns=%s size=%s elapsed=%.2fs',bulk_csv,schema_file,len(body),len(hs),bulk_csv.stat().st_size,time.perf_counter()-prep_started)
   import pythoncom,win32com.client
   com_started=time.perf_counter();pythoncom.CoInitialize();log.info('ACCDB_COM_INITIALIZE elapsed=%.2fs',time.perf_counter()-com_started)
   table_raw=str(job.get('table') or '仕掛');table=table_raw.replace(']',']]');cols=', '.join('['+str(h).replace(']',']]')+'] LONGTEXT' for h in hs)
   access_error=None
   try:
    dispatch_started=time.perf_counter();access_app=win32com.client.DispatchEx('Access.Application');dispatch_elapsed=time.perf_counter()-dispatch_started;access_app.Visible=False
    open_started=time.perf_counter();access_app.OpenCurrentDatabase(str(dst));open_elapsed=time.perf_counter()-open_started
    db_started=time.perf_counter();current_db=access_app.CurrentDb();db_elapsed=time.perf_counter()-db_started
    ddl_started=time.perf_counter()
    try:current_db.Execute(f'DROP TABLE [{table}]')
    except:pass
    current_db.Execute(f'CREATE TABLE [{table}] ({cols})');ddl_elapsed=time.perf_counter()-ddl_started
    set_status(activity_detail='ACCDB高速一括取込中',activity_value=f'{len(body):,}行 x {len(hs)}列をTransferTextで登録',heartbeat_at=datetime.now().isoformat(timespec='seconds'))
    transfer_started=time.perf_counter();access_app.DoCmd.TransferText(0,None,table_raw,str(bulk_csv),True);transfer_elapsed=time.perf_counter()-transfer_started
    verify_started=time.perf_counter();dao_rs=current_db.OpenRecordset(f'SELECT COUNT(*) AS C FROM [{table}]');actual=int(dao_rs.Fields(0).Value);dao_rs.Close();dao_rs=None;verify_elapsed=time.perf_counter()-verify_started
    if actual!=len(body):raise RuntimeError(f'ACCDB件数検査に失敗 expected={len(body)} actual={actual}')
    log.info('ACCDB_ACCESS_PIPELINE dispatch_elapsed=%.2fs open_elapsed=%.2fs currentdb_elapsed=%.2fs ddl_elapsed=%.2fs transfer_elapsed=%.2fs verify_elapsed=%.2fs rows=%s columns=%s',dispatch_elapsed,open_elapsed,db_elapsed,ddl_elapsed,transfer_elapsed,verify_elapsed,actual,len(hs))
    # Access終了待ちを短縮するため、DAO/COM参照を内側から順に明示解放する。
    release_started=time.perf_counter();access_pid=0;access_hwnd=0
    try:
     access_hwnd=int(access_app.hWndAccessApp)
     import ctypes
     pid_value=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(access_hwnd,ctypes.byref(pid_value));access_pid=int(pid_value.value)
    except Exception:pass
    log.info('ACCDB_ACCESS_PROCESS hwnd=%s pid=%s',access_hwnd,access_pid)
    try:
     if dao_rs:dao_rs.Close()
    except:pass
    dao_rs=None
    try:
     if current_db:current_db.Close()
    except Exception as e:log.info('ACCDB_DAO_DATABASE_CLOSE_SKIPPED detail=%s',e)
    current_db=None
    gc.collect()
    try:pythoncom.CoFreeUnusedLibraries()
    except Exception:pass
    log.info('ACCDB_COM_REFERENCE_RELEASE elapsed=%.2fs',time.perf_counter()-release_started)
    close_started=time.perf_counter();access_app.CloseCurrentDatabase();log.info('ACCDB_CLOSE_CURRENT_DATABASE elapsed=%.2fs',time.perf_counter()-close_started)
    gc.collect()
    try:pythoncom.CoFreeUnusedLibraries()
    except Exception:pass
    # acQuitSaveNone=2。Access UI/オブジェクト変更の保存確認を抑止する。
    quit_started=time.perf_counter();access_app.Quit(2);quit_elapsed=time.perf_counter()-quit_started;log.info('ACCDB_ACCESS_QUIT_CALL elapsed=%.2fs pid=%s',quit_elapsed,access_pid)
    clear_started=time.perf_counter();defer_com_reference('Access.Application.Quit済み',access_app);access_app=None;log.info('ACCDB_ACCESS_REFERENCE_DEFERRED elapsed=%.2fs deferred_refs=%s',time.perf_counter()-clear_started,len(_deferred_com_refs))
    # 全面GCはCOMファイナライザで長時間停止することがあるため、正常経路では実行しない。
    free_started=time.perf_counter()
    try:pythoncom.CoFreeUnusedLibraries()
    except Exception:pass
    log.info('ACCDB_COM_FREE_AFTER_QUIT elapsed=%.2fs',time.perf_counter()-free_started)
    process_alive='unknown';probe_elapsed=0.0
    if access_pid:
     probe_started=time.perf_counter()
     try:
      probe=subprocess.run(['tasklist','/FI',f'PID eq {access_pid}','/NH'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));process_alive=str(access_pid) in (probe.stdout or '')
     except Exception as e:process_alive=f'probe_error:{e}'
     probe_elapsed=time.perf_counter()-probe_started
    log.info('ACCDB_ACCESS_PROCESS_PROBE pid=%s process_alive=%s elapsed=%.2fs',access_pid,process_alive,probe_elapsed)
   except Exception as e:
    access_error=e;log.warning('ACCDB_ACCESS_PIPELINE_FAILED error=%s fallback=ADO.Recordset',e)
    try:
     if dao_rs:dao_rs.Close()
    except:pass
    try:
     if access_app:access_app.Quit()
    except:pass
    dao_rs=None;current_db=None;access_app=None
   if access_error is not None:
    # Access統合経路が失敗した場合だけ低速なADO互換経路を使用する。
    provider_errors=[];provider=None
    for candidate in ('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0'):
     provider_started=time.perf_counter();test=None
     try:
      test=win32com.client.Dispatch('ADODB.Connection');test.Open(f'Provider={candidate};Data Source={dst};Persist Security Info=False;');conn=test;provider=candidate;log.info('ACCDB_FALLBACK_PROVIDER_OPEN provider=%s elapsed=%.2fs',candidate,time.perf_counter()-provider_started);break
     except Exception as e:
      provider_errors.append(f'{candidate}: {e}')
    if not conn:raise RuntimeError('Access統合経路とADO接続がともに失敗: '+str(access_error)+' | '+' | '.join(provider_errors))
    try:conn.Execute(f'DROP TABLE [{table}]')
    except:pass
    conn.Execute(f'CREATE TABLE [{table}] ({cols})')
    fallback_started=time.perf_counter();rs=win32com.client.Dispatch('ADODB.Recordset');rs.CursorLocation=3;rs.Open(f'SELECT * FROM [{table}] WHERE 1=0',conn,3,4);field_names=[str(x) for x in hs]
    for index,row in enumerate(body,1):
     rs.AddNew(field_names,[str(v) if v is not None else '' for v in row])
     if index%250==0:rs.UpdateBatch();log.info('ACCDB_FALLBACK_PROGRESS rows=%s/%s elapsed=%.1fs',index,len(body),time.perf_counter()-fallback_started)
    rs.UpdateBatch();rs.Close();rs=None
    check=conn.Execute(f'SELECT COUNT(*) AS C FROM [{table}]')[0];actual=int(check.Fields(0).Value);check.Close();conn.Close();conn=None
    if actual!=len(body):raise RuntimeError(f'ACCDBフォールバック件数検査失敗 expected={len(body)} actual={actual}')
    log.info('ACCDB_FALLBACK_COMPLETE provider=%s rows=%s columns=%s elapsed=%.2fs',provider,actual,len(hs),time.perf_counter()-fallback_started)
  except Exception as e:
   for obj,method in ((dao_rs,'Close'),(rs,'Close'),(conn,'Close')):
    try:
     if obj:getattr(obj,method)()
    except:pass
   try:
    if access_app:access_app.Quit()
   except:pass
   try:
    if dst.exists():dst.unlink()
   except:pass
   raise RuntimeError('ACCESS(accdb)出力に失敗しました: '+str(e)) from e
  finally:
   if bulk_dir:shutil.rmtree(bulk_dir,ignore_errors=True)
   if pythoncom:
    try:pythoncom.CoUninitialize()
    except:pass
 else: raise ValueError('未対応の出力形式: '+fmt)
 if not dst.exists() or dst.stat().st_size==0:raise RuntimeError('出力ファイルの作成に失敗しました')
 log.info('出力検証完了 format=%s file=%s size=%s rows=%s columns=%s',fmt,dst,dst.stat().st_size,len(body),len(hs))
 return len(body),len(hs)

def _replace_once(src,dst):
 os.replace(src,dst)
 return True

def _pending_pattern(dst):
 return f'{dst.stem}.pending_*{dst.suffix}'

def apply_pending(dst,backup_root,generations):
 """Apply the newest deferred output before the next extraction, if the target is no longer locked."""
 pending=sorted(dst.parent.glob(_pending_pattern(dst)),key=lambda p:p.stat().st_mtime,reverse=True)
 if not pending:return None
 newest=pending[0]
 try:
  publish(newest,dst,backup_root,generations,from_pending=True)
  for old in pending[1:]:
   try:old.unlink()
   except OSError:pass
  log.info('保留ファイル適用完了 %s -> %s',newest,dst)
  return newest
 except PermissionError:
  return None

def publish(src,dst,backup_root,generations,from_pending=False):
 """Copy locally-created output, then atomically replace the public file.
 If another PC has the target open, keep the new correct file as *.pending_* and return immediately.
 """
 dst.parent.mkdir(parents=True,exist_ok=True)
 bdir=backup_root/dst.stem; bdir.mkdir(parents=True,exist_ok=True)
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
 incoming=dst.parent/f'.{dst.name}.{os.getpid()}.incoming'
 try:
  if from_pending:
   incoming=src
  else:
   copy_started=time.perf_counter();shutil.copy2(src,incoming);log.info('PUBLISH_INCOMING_COPY src=%s incoming=%s size=%s elapsed=%.2fs',src,incoming,incoming.stat().st_size,time.perf_counter()-copy_started)
   if incoming.stat().st_size!=src.stat().st_size:raise IOError('公開先へのコピーサイズが一致しません')
  deadline=time.time()+3.0; last=None
  while time.time()<deadline:
   try:
    if dst.exists():
     backup=bdir/f'{dst.stem}_{stamp}{dst.suffix}'
     try:
      backup_started=time.perf_counter();shutil.copy2(dst,backup);log.info('PUBLISH_BACKUP_COPY src=%s backup=%s elapsed=%.2fs',dst,backup,time.perf_counter()-backup_started)
     except (PermissionError,OSError) as e:log.warning('PUBLISH_BACKUP_SKIP error=%s',e)
    replace_started=time.perf_counter();os.replace(incoming,dst);log.info('PUBLISH_ATOMIC_REPLACE target=%s elapsed=%.2fs',dst,time.perf_counter()-replace_started)
    cleanup_started=time.perf_counter();old=sorted(bdir.glob(f'{dst.stem}_*{dst.suffix}'),key=lambda p:p.stat().st_mtime,reverse=True);removed=0
    for item in old[generations:]:
     try:item.unlink();removed+=1
     except OSError:pass
    log.info('PUBLISH_BACKUP_CLEANUP candidates=%s removed=%s elapsed=%.2fs',len(old),removed,time.perf_counter()-cleanup_started)
    verify_started=time.perf_counter();published_size=dst.stat().st_size
    if published_size!=src.stat().st_size:raise IOError(f'公開後サイズ不一致 source={src.stat().st_size} target={published_size}')
    log.info('PUBLISH_FINAL_VERIFY target=%s size=%s elapsed=%.2fs',dst,published_size,time.perf_counter()-verify_started)
    return {'published':True,'path':str(dst)}
   except PermissionError as e:last=e;time.sleep(.25)
   except OSError as e:
    if getattr(e,'winerror',None) in (5,32,33):last=e;time.sleep(.25)
    else:raise
  if from_pending:raise PermissionError(f'公開先が使用中です: {dst}') from last
  pending=dst.parent/f'{dst.stem}.pending_{stamp}{dst.suffix}'
  os.replace(incoming,pending)
  log.warning('公開先使用中。新しいファイルを更新保留として保存 %s',pending)
  return {'published':False,'path':str(dst),'pending':str(pending),'reason':'他のPCまたはアプリが公開先ファイルを使用中'}
 finally:
  if incoming.exists() and incoming!=src:
   try:incoming.unlink()
   except OSError:pass

def process_api_parallel_job(j,job_index,total_jobs,cfg,user,pw,server,dde_work,work,backup):
 from navigator_api import NavigatorApi
 line_name=os.environ.get('NAVI_WORKER_LINE') or threading.current_thread().name
 job_started=time.perf_counter();api_client=None;api_csv=None;xls=None;db=None
 try:
  fmt=validate_output_contract(j,'before-extraction')
  j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb')))
  rp=resolve_rne_path(j,cfg);out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']);target=out_dir/j['output_file']
  apply_pending(target,backup,int(cfg['settings']['backup_generations']))
  if not rp.is_file():raise FileNotFoundError('RNEがありません: '+str(rp))
  stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+f'_L{job_index}'
  xls=dde_work/f'navi_{job_index}_{stamp}.xls';local_export=dde_work/'export';local_export.mkdir(parents=True,exist_ok=True)
  db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'
  common_intermediate='API_DIRECT_XLSX' if fmt=='xlsx' else 'CSV'
  planned=db if fmt=='xlsx' else dde_work/f'navi_{job_index}_{stamp}.csv'
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='開始',percent=5,detail=fmt);log.info('PARALLEL_JOB_START line=%s job=%s index=%s/%s format=%s target=%s',line_name,j['name'],job_index,total_jobs,fmt,target)
  log.info('PIPELINE job=%s engine=api parallel_line=%s common_intermediate=%s format=%s planned_intermediate=%s converted=%s target=%s',j['name'],line_name,common_intermediate,fmt,planned,db,target)
  api_client=NavigatorApi(resolve_path(cfg['symnavi_exe']),log,cfg.get('navigator_api_dll'))
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='API接続',percent=10,detail='セッション接続');session_started=time.perf_counter();session_elapsed=api_client.open_session(user,pw,server);log.info('PARALLEL_API_SESSION line=%s job=%s dll=%s elapsed=%.2fs is_opened=1',line_name,j['name'],api_client.dll_path,session_elapsed)
  profiles=api_data_source_profiles(resolve_path(cfg['symnavim_conf']))
  if not any(p.get('kind')=='oracle' for p in profiles):
   profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0','credential_source':'navigator_session'})
   log.info('API Oracle接続設定未指定。Navigator認証を1回だけ流用 line=%s job=%s credential_source=navigator_session user_configured=%s password_configured=%s',line_name,j['name'],bool(user),bool(pw))
  for profile in profiles:
   source=profile.get('credential_source') or 'explicit_config'
   elapsed=api_client.connect_data_source(profile)
   log.info('APIデータソース接続完了 line=%s job=%s section=%s kind=%s credential_source=%s elapsed=%.2fs',line_name,j['name'],profile['section'],profile['kind'],source,elapsed)
  api_rne=rp.resolve();rne_stat=api_rne.stat();previous_cwd=os.getcwd()
  try:
   os.chdir(api_rne.parent)
   log.info('APIカタログ読込条件 line=%s dll=%s cwd=%s catalog_full=%s catalog_name=%s extension=%s size=%s mtime_ns=%s strategy=original_fullpath',line_name,api_client.dll_path,os.getcwd(),api_rne,api_rne.name,api_rne.suffix,rne_stat.st_size,rne_stat.st_mtime_ns)
   t=phase_log('api_open_catalog',job=j['name'],line=line_name);handle,api_elapsed=api_client.open_catalog(api_rne);phase_log('api_open_catalog',t,job=j['name'],line=line_name,handle=handle,api_elapsed=f'{api_elapsed:.2f}s',strategy='original_fullpath')
  finally:os.chdir(previous_cwd)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='問い合わせ実行',percent=35,detail='API execute');t=phase_log('api_execute_catalog',job=j['name'],line=line_name);api_number,api_elapsed=api_client.execute(handle);phase_log('api_execute_catalog',t,job=j['name'],line=line_name,number=api_number,api_elapsed=f'{api_elapsed:.2f}s')
  t=phase_log('api_get_dimensions',job=j['name'],line=line_name);expected_rows,expected_cols=api_client.dimensions(handle);phase_log('api_get_dimensions',t,job=j['name'],line=line_name,rows=expected_rows,columns=expected_cols)
  api_direct_output=False
  if fmt=='xlsx':
   update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='XLSX保存',percent=58,detail='直接出力')
   try:
    if db.exists():
     try:db.unlink()
     except:pass
    save_wall_started=time.perf_counter();t=phase_log('api_save_xlsx_direct',job=j['name'],line=line_name,target=db,repeat='NAVI_NONREPEAT',ftype='NAVI_XLSX');save_elapsed=api_client.save_xlsx(handle,db);save_wall_elapsed=time.perf_counter()-save_wall_started;phase_log('api_save_xlsx_direct',t,job=j['name'],line=line_name,api_elapsed=f'{save_elapsed:.2f}s',wall_elapsed=f'{save_wall_elapsed:.2f}s',size=db.stat().st_size if db.exists() else 0,throughput_kb_s=f'{(db.stat().st_size/1024/save_wall_elapsed):.1f}' if db.exists() and save_wall_elapsed>0 else '0')
    if not db.is_file() or db.stat().st_size<=0:raise RuntimeError(f'API直接XLSXが作成されませんでした: {db}')
    v=phase_log('api_direct_xlsx_validation',job=j['name'],line=line_name,file=db,mode='fast_header_only');verify_xlsx_fast(db,expected_cols);phase_log('api_direct_xlsx_validation',v,job=j['name'],line=line_name,mode='fast_header_only',rows=expected_rows,columns=expected_cols,size=db.stat().st_size)
    api_direct_output=True;intermediate=db;nr,nc=int(expected_rows),int(expected_cols)
    log.info('API_DIRECT_OUTPUT line=%s job=%s format=xlsx method=NaviSaveData(NAVI_XLSX) rows=%s columns=%s file=%s bytes_per_cell=%.2f',line_name,j['name'],expected_rows,expected_cols,db,(db.stat().st_size/max(1,(int(expected_rows)+1)*int(expected_cols))))
   except Exception as e:
    log.warning('API直接XLSX保存に失敗したためCSV経由へフォールバック line=%s job=%s error=%s',line_name,j['name'],e)
    try:
     if db.exists():db.unlink()
    except:pass
  if not api_direct_output:
   update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='CSV保存',percent=58,detail='API保存')
   api_csv=dde_work/f'navi_{job_index}_{stamp}.csv'
   t=phase_log('api_save_csv',job=j['name'],line=line_name);save_elapsed=api_client.save_csv(handle,api_csv);phase_log('api_save_csv',t,job=j['name'],line=line_name,api_elapsed=f'{save_elapsed:.2f}s',size=api_csv.stat().st_size if api_csv.exists() else 0)
   if not api_csv.is_file() or api_csv.stat().st_size<=0:raise RuntimeError(f'API中間CSVが作成されませんでした: {api_csv}')
   intermediate=api_csv
  t=phase_log('api_close_catalog',job=j['name'],line=line_name);api_client.close_catalog();phase_log('api_close_catalog',t,job=j['name'],line=line_name)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='変換・検証',percent=75,detail=fmt)
  if api_direct_output:
   t=phase_log('format_conversion',job=j['name'],line=line_name,format=fmt,mode='api_direct_xlsx');phase_log('format_conversion',t,job=j['name'],line=line_name,format=fmt,mode='api_direct_xlsx',rows=nr,columns=nc)
  else:
   t=phase_log('format_conversion',job=j['name'],line=line_name,format=fmt);nr,nc=export_data(intermediate,db,j,bool(cfg['settings']['reject_zero_rows']),expected_rows,expected_cols);phase_log('format_conversion',t,job=j['name'],line=line_name,format=fmt,rows=nr,columns=nc)
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='公開',percent=90,detail=str(target));t=phase_log('publish',job=j['name'],line=line_name);pub=publish(db,target,backup,int(cfg['settings']['backup_generations']));phase_log('publish',t,job=j['name'],line=line_name,published=pub['published'])
  total=time.perf_counter()-job_started
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='完了',percent=100,detail=f'{nr}件/{nc}列',elapsed=round(total,1));log.info('PARALLEL_JOB_RESULT line=%s job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s published=%s',line_name,j['name'],fmt,nr,nc,total,target,pub['published'])
  result=f'{j["name"]}: {nr}件/{nc}列 / {total:.1f}秒'+('' if pub['published'] else f' / 更新保留: {pub["pending"]}')
  return {'ok':True,'job':j['name'],'format':fmt,'rows':nr,'columns':nc,'elapsed':total,'target':str(target),'result':result}
 except Exception as e:
  total=time.perf_counter()-job_started
  update_parallel_line(line_name,job=j.get('name',''),job_id=j.get('id',''),state='失敗',percent=100,detail=str(e),elapsed=round(total,1));log.error('PARALLEL_JOB_ERROR line=%s job=%s elapsed=%.2fs error=%s\n%s',line_name,j.get('name'),total,e,traceback.format_exc())
  return {'ok':False,'job':j.get('name',''), 'elapsed':total, 'error':str(e)}
 finally:
  if api_client:
   try:api_client.close()
   except Exception as e:log.warning('Navigator API終了処理失敗 line=%s job=%s error=%s',line_name,j.get('name'),e)
  for p in (xls,api_csv,db):
   try:
    if p:p.unlink()
   except:pass


def _read_worker_json(path,default=None):
 try:return json.loads(Path(path).read_text(encoding='utf-8'))
 except Exception:return default

def run_api_process_batch(jobs,cfg,user,pw,server,dde_work,work,backup,max_lines,trigger):
 """Run each Navigator API session in an isolated Python process.
 Finished lines immediately pull the next queued query until the reservation queue is empty.
 """
 batch_id=datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8]
 runtime=dde_work/'parallel_runtime'/('parallel_'+batch_id);runtime.mkdir(parents=True,exist_ok=True)
 queue=deque(enumerate(jobs,1));active={};results=[];failures=[];completed=0
 with active_workers_lock:active_workers.clear()
 batch_started=time.perf_counter(); total=len(jobs); max_lines=max(1,min(int(max_lines),total))
 set_status(parallel_lines=[{'line':f'ライン {n}','job':'','state':'待機','percent':0,'elapsed':0,'detail':'開始待ち','slot':n} for n in range(1,max_lines+1)],queue_total=total,queue_waiting=total,queue_active=0,queue_completed=0,parallel_max_lines=max_lines,parallel_mode=True,symnavi_window=f'独立プロセス {max_lines}ライン')
 log.info('PARALLEL_BATCH_START model=process-isolated trigger=%s batch_id=%s runtime=%s jobs=%s max_lines=%s total_jobs=%s parent_pid=%s',trigger,batch_id,runtime,[j['rne'] for j in jobs],max_lines,total,os.getpid())
 def start_one(slot):
  index,job=queue.popleft();line=f'ライン {slot}'
  job_dir=runtime/f'line_{slot}_{index}';job_dir.mkdir(parents=True,exist_ok=True)
  payload={'job':job,'job_index':index,'total_jobs':total,'cfg':cfg,'user':user,'password':pw,'server':server,'dde_work':str(job_dir/'work'),'work':str(work),'backup':str(backup),'line':line}
  Path(payload['dde_work']).mkdir(parents=True,exist_ok=True)
  payload_path=job_dir/'payload.json';result_path=job_dir/'result.json';status_path=job_dir/'status.json'
  payload_path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
  env=os.environ.copy();env['NAVI_WORKER_LINE']=line;env['NAVI_WORKER_STATUS']=str(status_path);env['NAVI_WORKER_RESULT']=str(result_path)
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  proc=subprocess.Popen([sys.executable,str(BASE/'api_worker.py'),str(payload_path)],cwd=str(BASE),env=env,creationflags=flags)
  active[slot]={'proc':proc,'job':job,'index':index,'line':line,'status':status_path,'result':result_path,'started':time.perf_counter()}
  with active_workers_lock:active_workers[slot]=proc
  update_parallel_line(line,job=job['name'],job_id=job['id'],state='起動',percent=2,detail=f'予約 {index}/{total} / PID {proc.pid}',queue_index=index,slot=slot,started_at=datetime.now().isoformat(timespec='seconds'))
  log.info('WORKER_START batch_id=%s line=%s pid=%s job=%s queue_index=%s/%s',batch_id,line,proc.pid,job['name'],index,total)
 for slot in range(1,max_lines+1):
  if queue:start_one(slot)
 while active:
  if cancel_requested.is_set():
   log.info('PARALLEL_BATCH_CANCELLED batch_id=%s active=%s queued=%s',batch_id,len(active),len(queue))
   queue.clear()
   for slot,item in list(active.items()):
    try:item['proc'].terminate()
    except Exception:pass
   for slot,item in list(active.items()):
    try:item['proc'].wait(timeout=5)
    except Exception:
     try:item['proc'].kill()
     except Exception:pass
    failures.append({'ok':False,'job':item['job']['name'],'error':'ユーザーにより中断されました','elapsed':time.perf_counter()-item['started']})
    update_parallel_line(item['line'],job=item['job']['name'],job_id=item['job']['id'],state='中断',percent=100,detail='ユーザーにより中断されました',elapsed=round(time.perf_counter()-item['started'],1))
    with active_workers_lock:active_workers.pop(slot,None)
    del active[slot]
   break
  for slot,item in list(active.items()):
   worker_status=_read_worker_json(item['status'])
   if worker_status:
    update_parallel_line(item['line'],job=worker_status.get('job') or item['job']['name'],job_id=item['job']['id'],state=worker_status.get('state','処理中'),percent=worker_status.get('percent',0),detail=worker_status.get('detail',''),elapsed=round(time.perf_counter()-item['started'],1),pid=worker_status.get('pid',item['proc'].pid))
   rc=item['proc'].poll()
   if rc is None:continue
   result=_read_worker_json(item['result'],{'ok':False,'job':item['job']['name'],'error':f'Worker終了コード {rc}','elapsed':time.perf_counter()-item['started']})
   completed+=1
   (results if result.get('ok') else failures).append(result)
   log.info('WORKER_END batch_id=%s line=%s pid=%s job=%s returncode=%s ok=%s elapsed=%.2fs',batch_id,item['line'],item['proc'].pid,item['job']['name'],rc,result.get('ok'),result.get('elapsed',0))
   with active_workers_lock:active_workers.pop(slot,None)
   del active[slot]
   if queue and not cancel_requested.is_set():start_one(slot)
  waiting=len(queue);running=len(active)
  set_status(completed_jobs=completed,current_index=min(completed+running,total),current_job_name=f'予約キュー処理中: 実行 {running} / 待機 {waiting}',step='save',step_label=f'API並列処理 実行 {running}・待機 {waiting}・完了 {completed}',step_percent=round(100*completed/max(1,total)),activity_detail=f'{max_lines}ラインで予約クエリを処理',activity_value=f'実行 {running} / 待機 {waiting} / 完了 {completed}/{total}',queue_total=total,queue_waiting=waiting,queue_active=running,queue_completed=completed)
  time.sleep(.25)
 elapsed=time.perf_counter()-batch_started
 sequential_sum=sum(float(r.get('elapsed',0)) for r in results+failures);speedup=sequential_sum/elapsed if elapsed else 0
 summary='; '.join(f"{r.get('job')}={float(r.get('elapsed',0)):.1f}s" for r in results)
 log.info('PARALLEL_BATCH_END model=process-isolated total_jobs=%s succeeded=%s failed=%s max_lines=%s elapsed=%.2fs sequential_sum=%.2fs speedup=%.2fx job_elapsed_summary=%s',total,len(results),len(failures),max_lines,elapsed,sequential_sum,speedup,summary)
 set_status(parallel_speedup=round(speedup,2),queue_waiting=0,queue_active=0,queue_completed=completed,parallel_mode=True)
 return results,failures,elapsed

def process(job_ids=None,trigger='manual',parallel_lines_override=None,run_id=None):
 if not run_lock.acquire(False):raise RuntimeError('別の処理が実行中です')
 cancel_requested.clear()
 proc=srv=api_client=None; hide_done=None; window_watch_stop=None; window_watch_thread=None; access_prewarm_thread=None
 try:
  startup_started=time.perf_counter();cfg_started=time.perf_counter();cfg=load();log.info('STARTUP_PHASE phase=config_load elapsed=%.2fs',time.perf_counter()-cfg_started);jobs=[j for j in cfg['jobs'] if j.get('enabled') and (not job_ids or j['id'] in job_ids)]
  if not jobs:raise ValueError('実行対象がありません')
  selection_elapsed=time.perf_counter()-cfg_started;first_job=jobs[0]; first_fmt=normalize_output_format(first_job.get('output_format'),first_job.get('output_file')); first_target=resolve_path(first_job.get('output_folder') or cfg['default_output_folder'])/canonical_output_file(first_job.get('output_file'),first_fmt); progress.started=time.time(); requested_lines=max(1,int(parallel_lines_override or 1)); execution_mode='parallel' if str(cfg['settings'].get('extract_engine') or 'api').lower()=='api' and len(jobs)>1 and requested_lines>1 else 'serial'; set_status(run_id=run_id or uuid.uuid4().hex,execution_mode=execution_mode,requested_lines=requested_lines,parallel_mode=(execution_mode=='parallel'),parallel_lines=[],queue_total=0,queue_waiting=0,queue_active=0,queue_completed=0,parallel_max_lines=(requested_lines if execution_mode=='parallel' else 0),parallel_speedup=0,batch_job_ids=[j['id'] for j in jobs]); set_status(running=True,current='準備中',current_job_id=first_job['id'],current_job_name=first_job['name'],current_index=1,total_jobs=len(jobs),completed_jobs=0,failed_jobs=0,output_format=first_fmt,output_file=canonical_output_file(first_job.get('output_file'),first_fmt),output_target=str(first_target),started_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=0,symnavi_window='起動待ち',step='prepare',step_label='設定を確認しています',step_percent=3,last_result='実行中',error_detail=''); log.info('BUILD_VERSION=%s',BUILD_VERSION); log.info('処理開始 trigger=%s jobs=%s',trigger,[j['rne'] for j in jobs]);log.info('STARTUP_PHASE phase=config_and_job_selection elapsed=%.2fs',selection_elapsed)
  for k in ('symnavi_exe','symnavim_conf','symnavim_def'):
   if not resolve_path(cfg[k]).is_file():raise FileNotFoundError(f'{k}がありません: {cfg[k]}')
  cred_started=time.perf_counter();user,pw,server,_=creds(resolve_path(cfg['symnavim_conf']));log.info('STARTUP_PHASE phase=credential_load elapsed=%.2fs',time.perf_counter()-cred_started);path_started=time.perf_counter();rne_root=resolve_path(cfg['rne_folder']);work=resolve_path(cfg['work_folder']);backup=resolve_path(cfg['backup_folder']);work.mkdir(parents=True,exist_ok=True);dde_work=dde_staging_folder();log.info('STARTUP_PHASE phase=path_prepare elapsed=%.2fs total=%.2fs',time.perf_counter()-path_started,time.perf_counter()-startup_started);log.info('共通一時保存先: %s',dde_work)
  engine=str(cfg['settings'].get('extract_engine') or 'api').lower(); set_status(extract_engine=engine); log.info('抽出エンジン engine=%s stability_profile=%s',engine,cfg['settings'].get('stability_profile','stable_api_serial'))
  if any(normalize_output_format(j.get('output_format'),j.get('output_file'))=='accdb' for j in jobs):
   access_prewarm_thread=prewarm_access_async('process_contains_accdb')
  api_parallel_lines=max(1,min(int(cfg['settings'].get('api_parallel_max_lines',8) or 8),int(parallel_lines_override if parallel_lines_override is not None else cfg['settings'].get('api_parallel_lines',1) or 1)))
  log.info('PARALLEL_DECISION engine=%s selected_jobs=%s configured_lines=%s eligible=%s model=process-isolated',engine,len(jobs),api_parallel_lines,engine=='api' and len(jobs)>1 and api_parallel_lines>1)
  log.info('EXECUTION_MODE mode=%s requested_lines=%s selected_jobs=%s',('parallel-process' if engine=='api' and len(jobs)>1 and api_parallel_lines>1 else 'serial'),api_parallel_lines,len(jobs))
  if engine=='api' and len(jobs)>1 and api_parallel_lines>1:
   results,failures,batch_elapsed=run_api_process_batch(jobs,cfg,user,pw,server,dde_work,work,backup,api_parallel_lines,trigger)
   if cancel_requested.is_set():raise RunCancelled(f'{len(results)}/{len(jobs)}件完了後に中断されました')
   if failures:raise RuntimeError('API並列実行で失敗: '+' | '.join(f"{r['job']}: {r.get('error')}" for r in failures))
   msg='正常終了 | 全件%sファイル / %.1f秒 | '%(len(results),batch_elapsed)+' | '.join(r['result'] for r in results)
   progress('complete','すべての処理が完了しました',100);set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-progress.started));log.info(msg)
   return
  if engine=='api':
   from navigator_api import NavigatorApi
   progress('launch','Navigator APIを初期化しています',8); api_client=NavigatorApi(resolve_path(cfg['symnavi_exe']),log,cfg.get('navigator_api_dll')); set_status(symnavi_window='APIモード')
   progress('dde','Navigator ServerへAPI接続しています',15); t=time.perf_counter(); elapsed=api_client.open_session(user,pw,server); log.info('APIセッション接続完了 dll=%s elapsed=%.2fs is_opened=1',api_client.dll_path,elapsed)
   profiles=api_data_source_profiles(resolve_path(cfg['symnavim_conf']))
   # Oracle専用設定がなければ、Navigator認証情報をOracle接続へ1回だけ流用する。
   # 明示的なApiOracle設定を常に優先し、ユーザー名・パスワードの実値はログへ出さない。
   if not any(p.get('kind')=='oracle' for p in profiles):
    profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0','credential_source':'navigator_session'})
    log.info('API Oracle接続設定未指定。Navigator認証を1回だけ流用 credential_source=navigator_session user_configured=%s password_configured=%s',bool(user),bool(pw))
   for profile in profiles:
    source=profile.get('credential_source') or 'explicit_config'
    progress('dde',f'APIデータソースへ接続しています: {profile["kind"]}',18,activity_detail='公式API接続工程',activity_value=f'{profile["section"]} / {source}')
    try:
     elapsed=api_client.connect_data_source(profile)
     log.info('APIデータソース接続完了 section=%s kind=%s credential_source=%s elapsed=%.2fs',profile['section'],profile['kind'],source,elapsed)
    except Exception:
     log.error('APIデータソース接続失敗 section=%s kind=%s credential_source=%s retry=False',profile['section'],profile['kind'],source)
     raise
  elif engine=='dde':
   progress('launch','SymfoNaviを起動しています',8); proc=subprocess.Popen(f'"{str(resolve_path(cfg['symnavi_exe']))}" -d -u"{user}","{pw}","{server}"'); set_status(symnavi_window='起動済み'); progress('dde','SymfoNaviへのDDE接続を待っています',15); srv,conv=dde_connect(int(cfg['settings']['dde_timeout_seconds'])); hide_done=start_hidden_symnavi(proc,cfg['settings']); log.info('SymfoNavi定期監視を抽出中は停止 mode=pipeline-priority')
  else:raise ValueError('抽出エンジンが不正です: '+engine)
  progress('ready','処理の準備が完了しました',20); results=[]
  for job_index,j in enumerate(jobs,1):
   if cancel_requested.is_set():raise RunCancelled(f'{job_index-1}/{len(jobs)}件完了後に中断されました')
   set_status(current_index=job_index,current_job_id=j['id'],current_job_name=j['name'],output_format=normalize_output_format(j.get('output_format'),j.get('output_file')),output_file=canonical_output_file(j.get('output_file'),normalize_output_format(j.get('output_format'),j.get('output_file'))))
   preflight_started=phase_log('job_preflight',job=j['name']); progress('open',f'{j["name"]}: 入出力先を確認しています',22,activity_detail='事前確認',activity_value='出力先・保留ファイル・RNEを確認'); rp=resolve_rne_path(j,cfg); out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']); fmt=validate_output_contract(j,'before-extraction'); j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb'))); target=out_dir/j['output_file']; set_status(output_target=str(target)); log.info('実行設定 job=%s format=%s output_file=%s target=%s',j['name'],fmt,j['output_file'],target); apply_pending(target,backup,int(cfg['settings']['backup_generations'])); phase_log('job_preflight',preflight_started,job=j['name'],rne=rp,target=target)
   if not rp.is_file():raise FileNotFoundError('RNEがありません: '+str(rp))
   stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f'); xls=dde_work/f'navi_{job_index}_{stamp}.xls'; local_export=dde_work/'export'; local_export.mkdir(parents=True,exist_ok=True); db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'; log.info('変換作業先 local=%s configured_work=%s',db,work); esc=lambda x:str(x).replace('"','""')
   api_planned=(db if engine=='api' and fmt=='xlsx' else (dde_work/f'navi_{job_index}_{stamp}.csv' if engine=='api' else xls));common_intermediate=('API_DIRECT_XLSX' if engine=='api' and fmt=='xlsx' else ('CSV' if engine=='api' else 'XLS'))
   job_started=time.perf_counter(); log.info('PIPELINE job=%s engine=%s common_intermediate=%s format=%s planned_intermediate=%s converted=%s target=%s',j['name'],engine,common_intermediate,fmt,api_planned,db,target)
   if engine=='api':
    progress('open',f'{j["name"]}: APIでRNEを読み込んでいます',28,current_job_id=j['id'],activity_detail='Navigator API 1/3',activity_value=str(rp))
    # RNEを単体コピーすると、RNE内部の相対参照や同一フォルダー上の関連定義が切れる可能性がある。
    # API方式では元の配置を維持し、正規化した絶対パスをNaviOpenCatalogへ渡す。
    api_rne=rp.resolve()
    if not api_rne.is_file():raise FileNotFoundError(f'API用RNEがありません: {api_rne}')
    try:
     with api_rne.open('rb') as f:f.read(1)
    except OSError as e:raise PermissionError(f'API用RNEを読み取れません: {api_rne}: {e}') from e
    rne_stat=api_rne.stat()
    previous_cwd=os.getcwd()
    try:
     # cwdも元RNEフォルダーへ合わせ、RNE内部の相対参照とAPI側の探索条件を両立する。
     os.chdir(api_rne.parent)
     log.info('APIカタログ読込条件 dll=%s cwd=%s catalog_full=%s catalog_name=%s extension=%s size=%s mtime_ns=%s strategy=original_fullpath',api_client.dll_path,os.getcwd(),api_rne,api_rne.name,api_rne.suffix,rne_stat.st_size,rne_stat.st_mtime_ns)
     t=phase_log('api_open_catalog',job=j['name']); handle,api_elapsed=api_client.open_catalog(api_rne); phase_log('api_open_catalog',t,job=j['name'],handle=handle,api_elapsed=f'{api_elapsed:.2f}s',strategy='original_fullpath')
    finally:os.chdir(previous_cwd)
    progress('save',f'{j["name"]}: APIで問い合わせを実行しています',38,activity_detail='Navigator API 2/3',activity_value='問い合わせ実行・ダウンロード')
    t=phase_log('api_execute_catalog',job=j['name']); api_number,api_elapsed=api_client.execute(handle); phase_log('api_execute_catalog',t,job=j['name'],number=api_number,api_elapsed=f'{api_elapsed:.2f}s')
    t=phase_log('api_get_dimensions',job=j['name']);expected_rows,expected_cols=api_client.dimensions(handle);phase_log('api_get_dimensions',t,job=j['name'],rows=expected_rows,columns=expected_cols)
    api_direct_output=False;api_csv=None
    if fmt=='xlsx':
     progress('wait',f'{j["name"]}: APIからXLSXへ直接保存しています',50,activity_detail='Navigator API 3/3',activity_value=str(db))
     try:
      if db.exists():
       try:db.unlink()
       except:pass
      save_wall_started=time.perf_counter();t=phase_log('api_save_xlsx_direct',job=j['name'],target=db,repeat='NAVI_NONREPEAT',ftype='NAVI_XLSX');save_elapsed=api_client.save_xlsx(handle,db);save_wall_elapsed=time.perf_counter()-save_wall_started;phase_log('api_save_xlsx_direct',t,job=j['name'],api_elapsed=f'{save_elapsed:.2f}s',wall_elapsed=f'{save_wall_elapsed:.2f}s',size=db.stat().st_size if db.exists() else 0,throughput_kb_s=f'{(db.stat().st_size/1024/save_wall_elapsed):.1f}' if db.exists() and save_wall_elapsed>0 else '0')
      if not db.is_file() or db.stat().st_size<=0:raise RuntimeError(f'API直接XLSXが作成されませんでした: {db}')
      v=phase_log('api_direct_xlsx_validation',job=j['name'],file=db,mode='fast_header_only');verify_xlsx_fast(db,expected_cols);phase_log('api_direct_xlsx_validation',v,job=j['name'],mode='fast_header_only',rows=expected_rows,columns=expected_cols,size=db.stat().st_size)
      api_direct_output=True;intermediate=db
      log.info('API_DIRECT_OUTPUT job=%s format=xlsx method=NaviSaveData(NAVI_XLSX) rows=%s columns=%s file=%s bytes_per_cell=%.2f',j['name'],expected_rows,expected_cols,db,(db.stat().st_size/max(1,(int(expected_rows)+1)*int(expected_cols))))
     except Exception as e:
      log.warning('API直接XLSX保存に失敗したためCSV経由へフォールバック job=%s error=%s',j['name'],e)
      try:
       if db.exists():db.unlink()
      except:pass
    if not api_direct_output:
     api_csv=dde_work/f'navi_{job_index}_{stamp}.csv'
     progress('wait',f'{j["name"]}: API結果を高速CSVへ保存しています',50,activity_detail='Navigator API 3/3',activity_value=str(api_csv))
     t=phase_log('api_save_csv',job=j['name']);save_elapsed=api_client.save_csv(handle,api_csv);phase_log('api_save_csv',t,job=j['name'],api_elapsed=f'{save_elapsed:.2f}s',size=api_csv.stat().st_size if api_csv.exists() else 0)
     if not api_csv.is_file() or api_csv.stat().st_size<=0:raise RuntimeError(f'API中間CSVが作成されませんでした: {api_csv}')
     intermediate=api_csv
    progress('close',f'{j["name"]}: APIカタログを解放しています',62,activity_detail='API抽出完了',activity_value=f'期待値 {expected_rows}行 x {expected_cols}列');t=phase_log('api_close_catalog',job=j['name']);api_client.close_catalog();phase_log('api_close_catalog',t,job=j['name'])
   else:
    progress('open',f'{j["name"]}: RNEを開いています',28,current_job_id=j['id'],activity_detail='共通抽出工程 1/3',activity_value='全形式共通')
    t=phase_log('rne_open',job=j['name']); dde_exec(conv,'Open',f'[Open("{esc(rp)}")]'); phase_log('rne_open',t,job=j['name'])
    progress('save',f'{j["name"]}: 共通XLSを生成しています',38,activity_detail='共通抽出工程 2/3',activity_value=str(xls))
    t=phase_log('xls_save',job=j['name']); dde_exec(conv,'Save',f'[Save("{esc(xls)}", "EXCEL")]',expected_output=xls); phase_log('xls_save',t,job=j['name'])
    progress('wait',f'{j["name"]}: 共通XLSを検証しています',50,activity_detail='共通抽出工程 3/3',activity_value='ファイル安定・構造確認')
    t=phase_log('xls_stability',job=j['name']); wait_file(xls,int(cfg['settings']['output_wait_seconds']),j); phase_log('xls_stability',t,job=j['name'],size=xls.stat().st_size)
    intermediate=xls;expected_rows=None;expected_cols=None
    progress('close',f'{j["name"]}: 抽出画面を閉じています',62,activity_detail='共通抽出完了',activity_value=f'{xls.stat().st_size:,} bytes')
    t=phase_log('rne_close',job=j['name']); dde_exec(conv,'Close','[Close()]'); phase_log('rne_close',t,job=j['name'])
   if fmt=='accdb' and access_prewarm_thread is not None:
    join_started=time.perf_counter();alive_before=access_prewarm_thread.is_alive();access_prewarm_thread.join(timeout=2.0);log.info('ACCDB_PREWARM_JOIN alive_before=%s alive_after=%s elapsed=%.2fs',alive_before,access_prewarm_thread.is_alive(),time.perf_counter()-join_started)
   if engine=='api' and fmt=='xlsx' and locals().get('api_direct_output'):
    progress('export',f'{j["name"]}: API直接XLSXを検証しています',70,activity_detail='形式別変換工程',activity_value='CSV変換なし / API直接出力')
    t=phase_log('format_conversion',job=j['name'],format=fmt,mode='api_direct_xlsx');nr,nc=int(expected_rows),int(expected_cols);phase_log('format_conversion',t,job=j['name'],format=fmt,mode='api_direct_xlsx',rows=nr,columns=nc)
   else:
    progress('export',f'{j["name"]}: {fmt.upper()}へ変換しています',70,activity_detail='形式別変換工程',activity_value=f'{intermediate.suffix.upper()} -> {fmt.upper()}')
    t=phase_log('format_conversion',job=j['name'],format=fmt); nr,nc=export_data(intermediate,db,j,bool(cfg['settings']['reject_zero_rows']),expected_rows,expected_cols); phase_log('format_conversion',t,job=j['name'],format=fmt,rows=nr,columns=nc)
   progress('publish',f'{j["name"]}: 検査済みファイルを公開しています',90,activity_detail='公開工程',activity_value=str(target))
   t=phase_log('publish',job=j['name']); pub=publish(db,target,backup,int(cfg['settings']['backup_generations'])); phase_log('publish',t,job=j['name'],published=pub['published'])
   total=time.perf_counter()-job_started; results.append(f'{j["name"]}: {nr}件/{nc}列 / {total:.1f}秒'+('' if pub['published'] else f' / 更新保留: {pub["pending"]}')); set_status(completed_jobs=job_index); log.info('JOB_RESULT job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s',j['name'],fmt,nr,nc,total,target)
   # 元RNEはAPIが直接参照するため削除対象に含めない。生成物だけを後片付けする。
   for p in (xls,locals().get('api_csv'),db):
    try:
     if p:p.unlink()
    except:pass
  msg='正常終了 | '+' | '.join(results); progress('complete','すべての処理が完了しました',100); set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-progress.started)); log.info(msg)
 except RunCancelled as e:
  msg='中断されました: '+str(e); set_status(step='cancelled',step_label='ユーザーの操作により中断しました',step_percent=100,last_result=msg,error_detail='',last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-getattr(progress,'started',time.time()))); log.info('RUN_CANCELLED %s',msg)
 except Exception as e:
  msg='異常終了: '+str(e); set_status(step='error',step_label='処理を完了できませんでした',failed_jobs=1,step_percent=100,last_result=msg,error_detail=str(e),last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-getattr(progress,'started',time.time()))); log.error('%s\n%s',msg,traceback.format_exc()); raise
 finally:
  cancel_requested.clear()
  set_status(running=False,current='',current_job_id='',symnavi_window='終了済み')
  if window_watch_stop:window_watch_stop.set()
  if window_watch_thread:window_watch_thread.join(timeout=1.0)
  if hide_done:hide_done.set()
  if api_client:
   try:api_client.close()
   except Exception as e:log.warning('Navigator API終了処理失敗: %s',e)
  if srv:
   try:srv.Shutdown()
   except:pass
  if proc and proc.poll() is None:
   try:proc.terminate()
   except:pass
  run_lock.release()
def bg(ids,trigger,parallel_lines_override=None,run_id=None):
 try:process(ids,trigger,parallel_lines_override,run_id)
 except:pass


def queue_snapshot():
 with command_queue_lock:
  items=[]
  if active_command:
   x=dict(active_command);x['state']='running';x['position']=0;items.append(x)
  for i,item in enumerate(command_queue,1):
   x=dict(item);x['state']='waiting';x['position']=i;items.append(x)
  return {'items':items,'active_id':active_command.get('id') if active_command else None,'waiting_count':len(command_queue),'total_count':len(items)}

def enqueue_command(job_ids,trigger,parallel_lines):
 cfg=load(); selected=[j for j in cfg['jobs'] if j.get('enabled') and (not job_ids or j['id'] in job_ids)]
 if not selected:raise ValueError('実行対象がありません')
 item={'id':uuid.uuid4().hex,'job_ids':[j['id'] for j in selected],'job_names':[j['name'] for j in selected],'trigger':trigger,'parallel_lines':max(1,min(8,int(parallel_lines or 1))),'enqueued_at':datetime.now().isoformat(timespec='seconds'),'count':len(selected)}
 with command_queue_lock:
  command_queue.append(item);position=len(command_queue)+(1 if active_command else 0)
 command_queue_event.set();log.info('COMMAND_QUEUE_ENQUEUE id=%s position=%s jobs=%s lines=%s trigger=%s',item['id'],position,item['job_names'],item['parallel_lines'],trigger)
 return item,position

def command_dispatcher():
 global active_command
 while not stop_event.is_set():
  command_queue_event.wait(1.0)
  if stop_event.is_set():break
  with command_queue_lock:
   if active_command is not None:continue
   if not command_queue:
    command_queue_event.clear();continue
   active_command=command_queue.pop(0);item=dict(active_command)
  log.info('COMMAND_QUEUE_START id=%s remaining=%s jobs=%s lines=%s',item['id'],len(command_queue),item['job_names'],item['parallel_lines'])
  try:process(item['job_ids'],item['trigger'],item['parallel_lines'],item['id'])
  except Exception as e:log.error('COMMAND_QUEUE_FAILED id=%s error=%s',item['id'],e)
  finally:
   with command_queue_lock:active_command=None
   log.info('COMMAND_QUEUE_END id=%s remaining=%s',item['id'],len(command_queue))
   command_queue_event.set()

def schedule_key(job,rule,now):
 kind=rule.get('type','daily'); tm=rule.get('time','06:00'); hh,mm=map(int,tm.split(':')) if ':' in tm else (6,0)
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60))); return str(int(now.timestamp()//(mins*60))) if rule.get('enabled') else None
 if now.hour!=hh or now.minute!=mm:return None
 if kind=='daily':return now.strftime('%Y-%m-%d')+tm
 if kind=='weekdays' and now.weekday() in rule.get('weekdays',[]):return now.strftime('%Y-%m-%d')+tm
 if kind=='monthly' and now.day in rule.get('month_days',[1]):return now.strftime('%Y-%m-%d')+tm
 if kind=='specific_dates' and now.strftime('%Y-%m-%d') in rule.get('dates',[]):return now.strftime('%Y-%m-%d')+tm
 return None

def next_occurrence(rule,now):
 """予定一覧表示用に、ルール1件が次に実行される日時を1つ返す（過去日時・無効ルールはNone）。"""
 if not rule.get('enabled',True):return None
 kind=rule.get('type','daily'); tm=str(rule.get('time') or '06:00')
 try:hh,mm=map(int,tm.split(':'))
 except Exception:hh,mm=6,0
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60) or 60)); epoch=int(now.timestamp())
  return datetime.fromtimestamp((epoch//(mins*60)+1)*(mins*60))
 if kind=='daily':
  cand=now.replace(hour=hh,minute=mm,second=0,microsecond=0); return cand if cand>now else cand+timedelta(days=1)
 if kind=='weekdays':
  days=set(rule.get('weekdays') or [])
  if not days:return None
  for add in range(8):
   d=now+timedelta(days=add)
   if d.weekday() in days:
    cand=d.replace(hour=hh,minute=mm,second=0,microsecond=0)
    if cand>now:return cand
  return None
 if kind=='monthly':
  days=rule.get('month_days') or [1]
  for add in range(62):
   d=(now+timedelta(days=add)).date(); last=calendar.monthrange(d.year,d.month)[1]
   target={(last if x==-1 else x) for x in days}
   if d.day in target:
    cand=datetime(d.year,d.month,d.day,hh,mm)
    if cand>now:return cand
  return None
 if kind=='specific_dates':
  best=None
  for ds in (rule.get('dates') or []):
   try:y,mo,da=map(int,str(ds).split('-'))
   except Exception:continue
   cand=datetime(y,mo,da,hh,mm)
   if cand>now and (best is None or cand<best):best=cand
  return best
 return None

def job_schedule_hint(rules):
 if not rules:return '手動のみ'
 if len(rules)>1:return f'複数指定 ({len(rules)}件)'
 r=rules[0]; kind=r.get('type','daily')
 if kind=='interval':return f'定期 ({max(1,int(r.get("interval_minutes",60) or 60))}分ごと)'
 return {'daily':'毎日','weekdays':'曜日指定','monthly':'月日指定','specific_dates':'特定日'}.get(kind,kind)

def job_schedule_preview(job,now):
 if not job.get('enabled'):return {'id':job['id'],'next_run':None,'hint':'対象が無効'}
 rules=[r for r in job.get('schedules',[]) if r.get('enabled')]
 candidates=[c for c in (next_occurrence(r,now) for r in rules) if c]
 next_run=min(candidates) if candidates else None
 return {'id':job['id'],'next_run':next_run.isoformat(timespec='minutes') if next_run else None,'hint':job_schedule_hint(rules)}
def any_enabled_schedule_exists():
 try:
  cfg=load()
  return any(j.get('enabled') and any(r.get('enabled') for r in j.get('schedules',[])) for j in cfg['jobs'])
 except Exception:
  return True  # 判定に失敗した場合は自動実行を壊さない側へ倒し、終了させない。

def heartbeat_watchdog():
 time.sleep(10)  # 初回ページ読込み・最初のハートビート到達までの猶予。
 while not stop_event.wait(10):
  try:
   with heartbeat_lock:silence=time.time()-last_heartbeat_at
   if silence<=HEARTBEAT_TIMEOUT_SECONDS:continue
   if status['running']:
    log.info('HEARTBEAT_WATCHDOG silence=%.0fs だが実行中のため終了を見送りました',silence);continue
   if any_enabled_schedule_exists():
    log.info('HEARTBEAT_WATCHDOG silence=%.0fs だが有効な自動実行ルールがあるため常駐を継続します',silence);continue
   log.info('HEARTBEAT_WATCHDOG silence=%.0fsを検出し、ブラウザーが閉じられたと判断してアプリを終了します',silence)
   for h in log.handlers:h.flush()
   stop_event.set();os._exit(0)
  except Exception:
   log.exception('ハートビート監視エラー')

def scheduler():
 time.sleep(3)
 while not stop_event.wait(15):
  try:
   if status['running']:continue
   cfg=load(); now=datetime.now(); st=load_scheduler_state()
   due_ids=[]; due_rules=[]
   for j in cfg['jobs']:
    if not j.get('enabled'):continue
    for r in j.get('schedules',[]):
     if not r.get('enabled'):continue
     key=schedule_key(j,r,now); state_key=f'{j["id"]}:{r["id"]}'
     if key and st.get(state_key)!=key:
      st[state_key]=key; save_scheduler_state(state_key,key); due_ids.append(j['id']); due_rules.append(r.get('name',r['type'])); break
   if due_ids:
    log.info('SCHEDULE_BATCH_READY jobs=%s count=%s rules=%s',due_ids,len(due_ids),due_rules)
    enqueue_command(due_ids,f'schedule-batch:{len(due_ids)}',1); return
  except:log.exception('スケジュール判定エラー')

@app.get('/')
def index():
 response=app.make_response(render_template('index.html'));response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0';response.headers['Pragma']='no-cache';return response
@app.get('/favicon.ico')
def favicon():
 # favicon.icoの中身はSVG。拡張子と実体の食い違いでブラウザーが弾かないよう、明示的にimage/svg+xmlで返す。
 f=BASE/'favicon.ico'
 if not f.is_file():return ('',404)
 response=app.make_response(f.read_bytes());response.headers['Content-Type']='image/svg+xml';response.headers['Cache-Control']='public, max-age=86400';return response
@app.get('/api/config')
def get_config():
 c=load()
 try:*_,s=creds(resolve_path(c['symnavim_conf'])); c['credential_status']='読取可能 ['+s+']'
 except Exception as e:c['credential_status']='未確認: '+str(e)
 return jsonify(c)
@app.put('/api/config')
def put_config():save(request.get_json(force=True));return jsonify(ok=True)
@app.get('/api/schedule-preview')
def schedule_preview():
 c=load(); now=datetime.now()
 return jsonify(items=[job_schedule_preview(j,now) for j in c['jobs']])
@app.post('/api/run')
def run_all():
 try:
  data=request.get_json(silent=True) or {};requested=max(1,min(8,int(data.get('parallel_lines',1) or 1)))
  item,position=enqueue_command(data.get('job_ids'),'manual',requested)
  return jsonify(ok=True,queued=True,queue_id=item['id'],position=position,parallel_lines=requested,job_names=item['job_names'])
 except Exception as e:return jsonify(error=str(e)),400
@app.post('/api/run/<job_id>')
def run_one(job_id):
 try:
  item,position=enqueue_command([job_id],'manual-single',1)
  return jsonify(ok=True,queued=True,queue_id=item['id'],position=position,parallel_lines=1,job_names=item['job_names'])
 except Exception as e:return jsonify(error=str(e)),400
@app.post('/api/run/cancel')
def cancel_run():
 with command_queue_lock:
  queue_cleared=len(command_queue); command_queue.clear()
 if not status.get('running'):
  log.info('CANCEL_REQUESTED_IDLE queue_cleared=%s',queue_cleared)
  return jsonify(ok=True,was_running=False,workers_terminated=0,queue_cleared=queue_cleared)
 cancel_requested.set()
 with active_workers_lock:workers=list(active_workers.values())
 for p in workers:
  try:p.terminate()
  except Exception:pass
 log.info('CANCEL_REQUESTED workers_terminated=%s queue_cleared=%s',len(workers),queue_cleared)
 return jsonify(ok=True,was_running=True,workers_terminated=len(workers),queue_cleared=queue_cleared)
@app.get('/api/execution-queue')
def get_execution_queue():
 response=jsonify(queue_snapshot());response.headers['Cache-Control']='no-store';return response
@app.delete('/api/execution-queue/<queue_id>')
def delete_execution_queue(queue_id):
 with command_queue_lock:
  for i,item in enumerate(command_queue):
   if item['id']==queue_id:
    removed=command_queue.pop(i);log.info('COMMAND_QUEUE_DELETE id=%s jobs=%s',queue_id,removed['job_names']);return jsonify(ok=True)
 return jsonify(error='実行中または対象が見つかりません'),409
@app.post('/api/execution-queue/<queue_id>/move')
def move_execution_queue(queue_id):
 data=request.get_json(silent=True) or {};direction=data.get('direction')
 with command_queue_lock:
  idx=next((i for i,x in enumerate(command_queue) if x['id']==queue_id),None)
  if idx is None:return jsonify(error='待機キューにありません'),404
  dest=idx-1 if direction=='up' else idx+1
  if dest<0 or dest>=len(command_queue):return jsonify(ok=True)
  command_queue[idx],command_queue[dest]=command_queue[dest],command_queue[idx]
  log.info('COMMAND_QUEUE_MOVE id=%s direction=%s new_position=%s',queue_id,direction,dest+1)
 return jsonify(ok=True)
@app.get('/api/status')
def get_status():
 response=jsonify(status);response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0';return response
@app.get('/api/navigator-api-status')
def navigator_api_status():
 try:
  from navigator_api import NavigatorApi
  c=load(); api=NavigatorApi(resolve_path(c.get('symnavi_exe','')),log,c.get('navigator_api_dll')); info=api.info(); api.close(); return jsonify(info)
 except Exception as e:
  try:
   from navigator_api import candidate_dlls,pe_bits
   import struct
   pybits=struct.calcsize('P')*8; attempts=[{'path':str(p),'exists':p.is_file(),'dll_bits':pe_bits(p),'python_bits':pybits} for p in candidate_dlls(resolve_path(c.get('symnavi_exe','')),c.get('navigator_api_dll'))]
  except Exception:attempts=[]
  return jsonify(ok=False,error=str(e),mode='Navigator API',attempts=attempts),200

@app.get('/api/log')
def get_log():
 p=BASE/'logs'/'app.log'; return jsonify(text='\n'.join(p.read_text(encoding='utf-8',errors='replace').splitlines()[-1200:]) if p.exists() else '')
@app.post('/api/log/clear')
def clear_log():
 p=BASE/'logs'/'app.log'; p.parent.mkdir(exist_ok=True)
 p.write_text('',encoding='utf-8')
 return jsonify(ok=True)
@app.post('/api/log/delete-lines')
def delete_log_lines():
 data=request.get_json(silent=True) or {}; remove=set(data.get('lines') or [])
 p=BASE/'logs'/'app.log'
 if not p.exists():return jsonify(ok=True,removed=0)
 lines=p.read_text(encoding='utf-8',errors='replace').splitlines()
 kept=[x for x in lines if x not in remove]
 p.write_text('\n'.join(kept)+('\n' if kept else ''),encoding='utf-8')
 return jsonify(ok=True,removed=len(lines)-len(kept))

@app.post('/api/log/delete-old')
def delete_old_log():
 data=request.get_json(silent=True) or {}
 days=max(1,min(3650,int(data.get('days',30) or 30)))
 cutoff=datetime.now().timestamp()-(days*86400)
 p=BASE/'logs'/'app.log'
 if not p.exists():return jsonify(ok=True,removed=0,kept=0,days=days)
 lines=p.read_text(encoding='utf-8',errors='replace').splitlines()
 kept=[];removed=0
 for line in lines:
  try:
   ts=datetime.strptime(line[:23],'%Y-%m-%d %H:%M:%S,%f').timestamp()
   if ts<cutoff:
    removed+=1;continue
  except Exception:
   pass
  kept.append(line)
 p.write_text('\n'.join(kept)+('\n' if kept else ''),encoding='utf-8')
 log.info('LOG_RETENTION_DELETE days=%s removed=%s kept=%s',days,removed,len(kept))
 return jsonify(ok=True,removed=removed,kept=len(kept),days=days)

@app.post('/api/pick-file')
def pick_file():
 try:
  import tkinter as tk
  from tkinter import filedialog
  data=request.get_json(silent=True) or {}; initial=str(resolve_path(data.get('initial') or str(BASE))); types=data.get('types') or [['すべてのファイル','*.*']]
  root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
  path=filedialog.askopenfilename(initialdir=str(Path(initial).parent if Path(initial).suffix else Path(initial)),filetypes=[tuple(x) for x in types])
  root.destroy(); return jsonify(path=path)
 except Exception as e:return jsonify(error=str(e)),500
@app.post('/api/pick-folder')
def pick_folder():
 try:
  import tkinter as tk
  from tkinter import filedialog
  data=request.get_json(silent=True) or {}; initial=str(resolve_path(data.get('initial') or str(BASE))); root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True); path=filedialog.askdirectory(initialdir=initial); root.destroy(); return jsonify(path=path)
 except Exception as e:return jsonify(error=str(e)),500
@app.post('/api/path-convert')
def path_convert():
 data=request.get_json(silent=True) or {}; value=str(data.get('value') or '').strip(); mode=data.get('mode','absolute')
 if not value:return jsonify(value='',resolved=str(BASE),base=str(BASE),is_relative=False)
 resolved=resolve_path(value).resolve()
 if mode=='relative':
  try:converted='.\\'+str(resolved.relative_to(BASE.resolve())).replace('/','\\')
  except ValueError:
   try:converted=os.path.relpath(str(resolved),str(BASE.resolve())).replace('/','\\')
   except ValueError:return jsonify(error='別ドライブまたはUNC経路のため、このアプリ基準の相対パスへ変換できません。絶対パスを使用してください。'),400
 else:converted=str(resolved)
 return jsonify(value=converted,resolved=str(resolved),base=str(BASE.resolve()),is_relative=not Path(converted).is_absolute())

@app.get('/api/output-capabilities')
def output_capabilities():
 result={'sqlite3':{'ok':True,'detail':'Python標準機能'},'csv':{'ok':True,'detail':'Python標準機能'},'txt':{'ok':True,'detail':'Python標準機能'}}
 try:
  import openpyxl
  result['xlsx']={'ok':True,'detail':'openpyxl '+openpyxl.__version__}
 except Exception as e:result['xlsx']={'ok':False,'detail':'openpyxl未導入: '+str(e)}
 pythoncom=None
 try:
  import pythoncom, win32com.client
  pythoncom.CoInitialize(); conn=win32com.client.Dispatch('ADODB.Connection'); template=resolve_path(load().get('accdb_template','.\\assets\\empty.accdb')); result['accdb']={'ok':template.is_file(),'detail':('テンプレート方式: '+str(template)) if template.is_file() else ('ACCDBテンプレート未配置: '+str(template))}
 except Exception as e:result['accdb']={'ok':False,'detail':'pywin32 COM利用不可: '+str(e)}
 finally:
  if pythoncom:
   try:pythoncom.CoUninitialize()
   except:pass
 return jsonify(result)

def nearby_search_roots():
 roots=[]
 for p in (BASE,BASE.parent,BASE.parent.parent):
  if p.exists() and p not in roots:roots.append(p)
 for p in list(roots):
  try:
   for child in p.iterdir():
    if child.is_dir() and child not in roots:roots.append(child)
  except OSError:pass
 return roots

def find_nearby_file(filename,limit=8):
 if not filename:return []
 target=Path(filename).name.lower(); found=[]; seen=set()
 for root in nearby_search_roots():
  try:
   for p in root.rglob('*'):
    try:
     if p.is_file() and p.name.lower()==target:
      key=str(p.resolve()).lower()
      if key not in seen:seen.add(key); found.append(str(p.resolve()))
      if len(found)>=limit:return found
    except OSError:pass
  except OSError:pass
 return found

def check_path_item(value,kind='file',expected_name=''):
 p=resolve_path(value); ok=p.is_file() if kind=='file' else p.is_dir(); candidates=[]
 if not ok and kind=='file':candidates=find_nearby_file(expected_name or p.name)
 return {'ok':ok,'configured':str(value),'resolved':str(p),'candidates':candidates,'needs_reselect':not ok and not candidates}

@app.post('/api/path-check')
def path_check():
 d=request.get_json(force=True); item=d.get('item'); job_id=d.get('job_id'); c=load()
 if item in ('symnavim_conf','symnavim_def','accdb_template'):
  expected={'symnavim_conf':'symnavim.conf','symnavim_def':'symnavim.def','accdb_template':'empty.accdb'}[item]; result=check_path_item(c.get(item,''),'file',expected); result.update(item=item,label=expected)
 elif item=='rne':
  j=next((x for x in c['jobs'] if x['id']==job_id),None)
  if not j:return jsonify(error='対象が見つかりません'),404
  if d.get('value') is not None:j=dict(j,rne_path=d.get('value'),rne=d.get('expected_name') or j.get('rne'))
  rp=resolve_rne_path(j,c); result={'ok':rp.is_file(),'configured':str(j.get('rne_path') or j.get('rne')),'resolved':str(rp),'candidates':[],'needs_reselect':False}; result['candidates']=find_nearby_file(j.get('rne')) if not result['ok'] else []; result['needs_reselect']=not result['ok'] and not result['candidates']; result.update(item='rne',job_id=job_id,label=j.get('rne'))
 else:return jsonify(error='確認対象が不正です'),400
 return jsonify(result)

@app.post('/api/apply-path-suggestion')
def apply_path_suggestion():
 d=request.get_json(force=True); item=d.get('item'); candidate=d.get('candidate'); job_id=d.get('job_id')
 if not candidate or not Path(candidate).is_file():return jsonify(error='修正候補が存在しません'),400
 c=load()
 try:stored=str(Path(candidate).resolve().relative_to(BASE.resolve()))
 except ValueError:stored=str(Path(candidate).resolve())
 if not stored.startswith('.') and not Path(stored).is_absolute():stored='.\\'+stored.replace('/','\\')
 if item in ('symnavim_conf','symnavim_def','accdb_template'):c[item]=stored
 elif item=='rne':
  j=next((x for x in c['jobs'] if x['id']==job_id),None)
  if not j:return jsonify(error='対象が見つかりません'),404
  j['rne_path']=stored; j['rne']=Path(candidate).name
 else:return jsonify(error='修正対象が不正です'),400
 save(c); return jsonify(ok=True,path=stored)

@app.post('/api/validate')
def validate():
 c=load(); checks=[]
 for label,k,typ in [('SymNavi.exe','symnavi_exe','f'),('symnavim.conf','symnavim_conf','f'),('symnavim.def','symnavim_def','f'),('ACCDB空テンプレート','accdb_template','f'),('RNE基本フォルダー','rne_folder','d'),('作業フォルダー','work_folder','d')]:
  p=resolve_path(c[k]); ok=p.is_file() if typ=='f' else p.is_dir(); item=k if k in ('symnavim_conf','symnavim_def','accdb_template') else ''
  candidates=find_nearby_file(label) if not ok and item else []
  checks.append({'label':label,'ok':ok,'detail':str(p),'configured':c[k],'item':item,'candidates':candidates,'needs_reselect':not ok and item and not candidates})
 for j in c['jobs']:
  rp=resolve_rne_path(j,c); op=resolve_path(j.get('output_folder') or c['default_output_folder']); candidates=find_nearby_file(j['rne']) if not rp.is_file() else []
  checks.extend([{'label':j['name']+' RNE','ok':rp.is_file(),'detail':str(rp),'configured':j.get('rne_path'),'item':'rne','job_id':j['id'],'candidates':candidates,'needs_reselect':not rp.is_file() and not candidates},{'label':j['name']+' 出力先','ok':op.is_dir(),'detail':str(op),'item':''}])
 return jsonify(checks=checks,search_scope='アプリ基準: 上2階層・下1階層')

@app.get('/api/instance')
def instance_info():
 return jsonify(app='SymfoNaviDataHub',display_name='SymfoNavi Data Hub',build_version=BUILD_VERSION,pid=os.getpid(),port=PORT,path=str(BASE))

@app.get('/api/version')
def version_info():
 return jsonify(version=APP_VERSION,build_version=BUILD_VERSION,title=APP_VERSION_TITLE,released_at=APP_RELEASED_AT,changelog=CHANGELOG)

@app.post('/api/heartbeat')
def heartbeat():
 global last_heartbeat_at
 with heartbeat_lock:last_heartbeat_at=time.time()
 return jsonify(ok=True,timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS)

@app.post('/api/shutdown-app')
def shutdown_app():
 def stop():
  time.sleep(.4); stop_event.set(); os._exit(0)
 threading.Thread(target=stop,daemon=True).start(); return jsonify(ok=True)

@atexit.register
def shutdown():stop_event.set()
if __name__=='__main__':
 migrate_legacy_settings()
 threading.Thread(target=scheduler,daemon=True,name='scheduler').start(); threading.Thread(target=command_dispatcher,daemon=True,name='command-dispatcher').start(); threading.Thread(target=heartbeat_watchdog,daemon=True,name='heartbeat-watchdog').start()
 if os.environ.get('NAVI_LAUNCHED_BY_GUARD')!='1':threading.Timer(1.2,lambda:webbrowser.open(f'http://{HOST}:{PORT}')).start()
 app.run(host=HOST,port=PORT,debug=False,threaded=True)
