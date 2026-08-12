from __future__ import annotations
import atexit, calendar, configparser, contextlib, copy, csv, gc, json, logging, os, re, shutil, socket, sqlite3, struct, subprocess, sys, tempfile, threading, time, traceback, uuid, webbrowser
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
# 並列実行のワーカー(api_worker.py)は抽出処理だけを行い、HTTP層は一切使わない。
# それでも従来は app.py の取り込みに引きずられて Flask まで読み込んでおり、
# 1ジョブごとに約90msの無駄な起動時間が発生していた（ジョブ数に比例して積み上がる）。
# ワーカーではFlaskを取り込まず、経路定義のデコレーターだけを無害化する。
WORKER_MODE=os.environ.get('NAVI_WORKER_MODE')=='1'
if WORKER_MODE:
 class _UnusedWebLayer:
  """ワーカーでは呼ばれないHTTP層の代替。@app.get 等を素通しにするだけの器。"""
  config={}
  def __getattr__(self,name):
   def decorator(*a,**k):
    def keep(fn):return fn
    return keep
   return decorator
 def _web_layer_unavailable(*a,**k):raise RuntimeError('ワーカープロセスではHTTP層を使用できません')
 Flask=_web_layer_unavailable; jsonify=_web_layer_unavailable; render_template=_web_layer_unavailable; request=None
else:
 from flask import Flask, jsonify, render_template, request
# 起動計測用: app.py の全モジュール取り込み完了時刻(wall clock)。
# ここまでに『インタプリタ初期化＋app.pyのBOX読込＋コンパイル＋flask等の取り込み』が完了している。
_APP_IMPORT_DONE_AT=time.time()

# 版は navi_version.py（小さな定数だけ）。更新履歴と同梱仕様書は navi_changelog.py。
from navi_version import APP_VERSION,APP_VERSION_TITLE,APP_RELEASED_AT,BUILD_VERSION
if WORKER_MODE:
 # ワーカーは抽出しかしない。800行ぶんの読みものを読み込む必要がないので飛ばす。
 DOCS=[];CHANGELOG=[]
else:
 from navi_changelog import DOCS,CHANGELOG
BASE=Path(__file__).resolve().parent; LOCAL_ROOT=Path(os.environ['NAVI_LOCAL_ROOT']) if os.environ.get('NAVI_LOCAL_ROOT') else Path(os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home())/'SymfoNaviDataHub'; LOCAL_RUNTIME=LOCAL_ROOT/'runtime'; LOCAL_LOGS=LOCAL_ROOT/'logs'; LOCAL_BACKUP=LOCAL_ROOT/'backup'; [x.mkdir(parents=True,exist_ok=True) for x in (LOCAL_RUNTIME,LOCAL_LOGS,LOCAL_BACKUP)]; CONFIG_DIR=Path(os.environ['NAVI_CONFIG_DIR']) if os.environ.get('NAVI_CONFIG_DIR') else BASE/'Config'; CONFIG_DIR.mkdir(parents=True,exist_ok=True); MASTER_SETTINGS_DB=CONFIG_DIR/'app_settings.sqlite3'; SETTINGS_LOCAL_DIR=LOCAL_ROOT/'cache'; SETTINGS_LOCAL_DIR.mkdir(parents=True,exist_ok=True); SETTINGS_DB=SETTINGS_LOCAL_DIR/'app_settings.sqlite3'; OLD_SETTINGS_DB=BASE/'app_settings.sqlite3'; LEGACY_CFG=BASE/'config.json'; HOST='127.0.0.1'; PORT=5031
def docs_dir():
 # Windowsでは Config と config は同じ場所を指す。Linuxでの検証時だけ綴りが分かれるので両方見る。
 for d in (CONFIG_DIR/'docs',BASE/'config'/'docs'):
  if d.is_dir():return d
 return CONFIG_DIR/'docs'

# 設定のマスター（Config/app_settings.sqlite3）はアプリの置き場所に固定されている。
# NAVI_LOCAL_ROOT を別の場所へ向けても、マスターだけは本物を指したままだった。
# 実測 2026-08-18: 確認用の実行が本物のマスターへ書き込み、登録済みの対象6件が
# 消えて確認用の3件に置き換わった。確認のときだけ NAVI_CONFIG_DIR で逃がせるようにする。
# 運用では設定しない（設定しなければこれまでと同じ Config/ を使う）。
APP_ID='SymfoNaviDataHub'; INSTANCE_ID=str(uuid.uuid4()); app=_UnusedWebLayer() if WORKER_MODE else Flask(__name__)
if not WORKER_MODE:app.config['SEND_FILE_MAX_AGE_DEFAULT']=0
run_lock=threading.Lock(); stop_event=threading.Event(); status_lock=threading.Lock(); command_queue_lock=threading.RLock(); command_queue_event=threading.Event(); command_queue=[]; active_command=None
# ブラウザー側ハートビート監視。フロントからの生存信号が途絶えたら、ジョブ実行中でなく、
# かつ有効な自動実行ルールも無い場合にだけ自プロセスを終了し、閉じ忘れによるゾンビ化を防ぐ。
# 0.12.0（旧V36）: 非アクティブ（タブ切替）でもブラウザーは生存しているため、バックグラウンド時のタイマー抑制（多くのブラウザーで最悪1分に1回程度まで低速化）を考慮し、
# ハートビート途絶の判定しきい値を余裕を持って200秒へ拡大する。加えてタブが実際に閉じられた場合は明示シグナルで即時判定する。
HEARTBEAT_TIMEOUT_SECONDS=200; CLOSE_GRACE_SECONDS=12; heartbeat_lock=threading.Lock(); last_heartbeat_at=time.time(); browser_closed_explicit=False; browser_closing_at=0.0; heartbeat_clients={}; heartbeat_total=0
# 実行中断（ユーザーによる明示キャンセル）。プロセス分離ワーカーはterminateで即時停止できるが、
# 直列(DDE/API)実行中の1件はCOM/DDE操作の途中で安全に打ち切れないため、次のジョブ開始前でのみ打ち切る。
cancel_requested=threading.Event(); active_workers_lock=threading.Lock(); active_workers={}
# カレントディレクトリはプロセス全体で共有される。Flaskは threaded=True で動くため、
# 直列実行と管理ポイント自動検出などが重なると復元順序が入れ違い、cwdが誤った場所に固定される
# （Windowsでは後続のDLL探索にも影響する）。chdirを伴う区間はこのロックで直列化する。
chdir_lock=threading.RLock()
# 並列ライン数として動作を確認している上限。既定値・移行・クランプはすべてこの値を基準にする。
PARALLEL_LINES_SUPPORTED_MAX=24
# SymNaviA.dllを探す既定の範囲。製品側の標準配置 → アプリ同梱 の順。設定画面から増減できる。
DEFAULT_DLL_SEARCH_ROOTS=(r'C:\NAVIAP','.\\Config\\NAVIAP','.\\NAVIAP')
class RunCancelled(Exception):pass
status={'build_version':BUILD_VERSION,'running':False,'current':'','current_job_id':'','current_job_name':'','current_index':0,'total_jobs':0,'step':'idle','step_label':'待機中','step_percent':0,'completed_jobs':0,'failed_jobs':0,'started_at':'','elapsed_seconds':0,'symnavi_window':'未起動','last_result':'未実行','last_finished_at':'','error_detail':'','activity_detail':'','activity_value':'','heartbeat_at':'','parallel_lines':[],'batch_job_ids':[],'queue_completed_ids':[],'queue_failed_ids':[],'queue_running_ids':[],'queue_waiting_ids':[],'job_errors':[],'job_results':[]}
# ログの機構（出す・省略する・末尾だけ読む・世代を押し出す）は navi_log.py にある。
# ここに残すのは「いま付け替えてよいか」の判断だけ ―― それは本体の都合なので。
import navi_log
from navi_log import LogDedupFilter,flush_log,log_files,tail_lines,LOG_DEDUP_WINDOW,LOG_DEDUP_HOLD_SECONDS,LOG_DEDUP_HOLD_COUNT,LOG_DEDUP_ERROR_SECONDS
log=navi_log.setup(LOCAL_LOGS)
log_dedup=navi_log.log_dedup
LOG_PATH=navi_log.LOG_PATH
def rotate_log_if_needed(cfg=None,force=False):
 """大きくなったログを付け替えてよいか判断し、よければ navi_log へ任せる。

 これまでは付け替えが一切なく、app.log が際限なく育っていた。読み出しも毎回
 全文を読んでいたため、育つほど画面が重くなり、いずれ読めなくなる。

 付け替えるのは本体だけ、しかもワーカーが1つも居ない瞬間だけ。並列実行中に
 やると、他のプロセスが書き先を見失う（Windowsでは開いている最中のリネームが
 失敗する）。実行が終わるまで少し育つが、それは安全側。
 ここにあるのはこの判断だけで、押し出す機構そのものは navi_log.rotate_files。"""
 if WORKER_MODE:return None
 if not force:
  if status.get('running'):return None
  with active_workers_lock:
   if active_workers:return None
 try:
  s=(cfg or load()).get('settings') or {}
 except Exception:s={}
 limit=max(1,min(500,int(s.get('log_max_mb',10) or 10)))*1024*1024
 keep=max(0,min(20,int(s.get('log_keep',5) or 0)))
 try:
  if not LOG_PATH.exists() or (LOG_PATH.stat().st_size<limit and not force):return None
  size=LOG_PATH.stat().st_size
  flush_log();navi_log.close_handlers()
  navi_log.rotate_files(keep)
  log.info('LOG_ROTATED size=%s limit_mb=%s keep=%s note=ワーカーが居ない間に付け替えました',size,limit//1024//1024,keep)
  return size
 except Exception:
  log.exception('LOG_ROTATE_FAILED');return None

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

# ==== 設定DBのローカルキャッシュ＋書き戻し ==============================
# BOX上の app_settings.sqlite3 を『マスター』、%LOCALAPPDATA%配下を『ローカル作業DB』とする。
# 起動時にマスター→ローカルへ一度だけ取り込み、以降の読み書きは高速なローカルへ行う。
# 設定変更(save)時のみローカル→マスターへ書き戻す（バックグラウンド、非ブロッキング）。
# 運用データ(実行履歴・スケジュール状態)は都度BOXへ書かず、変更時と終了時にまとめて反映する。
settings_sync_lock=threading.RLock(); _settings_initialized=False; _settings_dirty=False
def _mark_settings_dirty():
 global _settings_dirty; _settings_dirty=True
def flush_local_to_master(reason=''):
 # ローカル作業DB → BOX上マスター へ原子的に書き戻す。書き込み中のコピー破損を避けるためロックで保護する。
 global _settings_dirty
 with settings_sync_lock:
  try:
   if not SETTINGS_DB.is_file():return False
   MASTER_SETTINGS_DB.parent.mkdir(parents=True,exist_ok=True)
   _t=time.perf_counter(); tmp=MASTER_SETTINGS_DB.with_suffix('.wb.tmp'); shutil.copy2(SETTINGS_DB,tmp); os.replace(tmp,MASTER_SETTINGS_DB)
   _settings_dirty=False; log.info('SETTINGS_FLUSH local->master reason=%s elapsed=%.2fs size=%s',reason,time.perf_counter()-_t,MASTER_SETTINGS_DB.stat().st_size); return True
  except Exception:
   log.exception('SETTINGS_FLUSH_FAILED reason=%s',reason); return False
def flush_local_to_master_async(reason=''):
 threading.Thread(target=flush_local_to_master,args=(reason,),daemon=True,name='settings-flush').start()
def _flush_settings_on_exit(reason=''):
 # 終了直前に、未反映の変更があるときだけBOXへ書き戻す（不要なBOX書き込みを避ける）。
 try:
  if _settings_dirty:flush_local_to_master(reason)
 except Exception:pass
# =====================================================================
def settings_connection():
 c=sqlite3.connect(SETTINGS_DB,timeout=30)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 return c

def init_settings_db():
 # 起動時に一度だけ: BOXマスター→ローカルへ取り込み、スキーマ整備はローカルに対して行う（BOXのfsync遅延を回避）。
 global _settings_initialized
 if _settings_initialized:return
 with settings_sync_lock:
  if _settings_initialized:return
  CONFIG_DIR.mkdir(parents=True,exist_ok=True); SETTINGS_LOCAL_DIR.mkdir(parents=True,exist_ok=True)
  # 旧配置(アプリ直下)のDBがあれば、一度だけBOXマスター(Config)へ引き上げる。
  if not MASTER_SETTINGS_DB.exists() and OLD_SETTINGS_DB.is_file():
   try:shutil.copy2(OLD_SETTINGS_DB,MASTER_SETTINGS_DB);log.info('設定DBを移行しました old=%s master=%s',OLD_SETTINGS_DB,MASTER_SETTINGS_DB)
   except Exception:log.exception('SETTINGS_MASTER_SEED_FAILED')
  # BOXマスター → ローカル作業DB（マスターが新しい、またはローカルが無いときだけ取り込む）。
  _t=time.perf_counter()
  try:
   need=(not SETTINGS_DB.is_file()) or (MASTER_SETTINGS_DB.is_file() and MASTER_SETTINGS_DB.stat().st_mtime_ns>SETTINGS_DB.stat().st_mtime_ns)
   if MASTER_SETTINGS_DB.is_file() and need:
    tmp=SETTINGS_DB.with_suffix('.pull.tmp'); shutil.copy2(MASTER_SETTINGS_DB,tmp); os.replace(tmp,SETTINGS_DB); log.info('SETTINGS_PULL master->local elapsed=%.2fs size=%s',time.perf_counter()-_t,SETTINGS_DB.stat().st_size)
   else:
    log.info('SETTINGS_PULL skip(local up-to-date) elapsed=%.2fs',time.perf_counter()-_t)
  except Exception:log.exception('SETTINGS_PULL_FAILED')
  with settings_connection() as c:
   c.executescript("""
  CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL,value_type TEXT NOT NULL DEFAULT 'text',updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,display_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,name TEXT NOT NULL,rne TEXT NOT NULL,rne_path TEXT NOT NULL,output_folder TEXT NOT NULL,output_format TEXT NOT NULL,output_file TEXT NOT NULL,table_name TEXT NOT NULL,sheet_name TEXT NOT NULL,read_type TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY,job_id TEXT NOT NULL,display_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,name TEXT NOT NULL,schedule_type TEXT NOT NULL,time_value TEXT,interval_minutes INTEGER,weekdays_json TEXT,month_days_json TEXT,dates_json TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
  CREATE TABLE IF NOT EXISTS scheduler_state (state_key TEXT PRIMARY KEY,state_value TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS job_runs (job_id TEXT PRIMARY KEY,job_name TEXT,finished_at TEXT,status TEXT,trigger TEXT,detail TEXT,rows INTEGER,cols INTEGER,output_file TEXT,updated_at TEXT NOT NULL DEFAULT '',metrics TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS run_history (id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,job_name TEXT,finished_at TEXT,status TEXT,trigger TEXT,detail TEXT,rows INTEGER,cols INTEGER,output_file TEXT);
  CREATE TABLE IF NOT EXISTS split_trials (id INTEGER PRIMARY KEY AUTOINCREMENT,rne_key TEXT NOT NULL,rne_path TEXT NOT NULL DEFAULT '',job_id TEXT NOT NULL DEFAULT '',job_name TEXT NOT NULL DEFAULT '',parts INTEGER NOT NULL,rows INTEGER,cols INTEGER,normal_elapsed REAL,split_elapsed REAL,observed_speedup REAL,identical INTEGER NOT NULL DEFAULT 0,detail TEXT NOT NULL DEFAULT '',metrics TEXT NOT NULL DEFAULT '',tried_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_split_trials_rne ON split_trials(rne_key);
  CREATE TABLE IF NOT EXISTS split_plans (rne_key TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'column',parts INTEGER NOT NULL,rne_path TEXT NOT NULL DEFAULT '',rne_mtime_ns TEXT NOT NULL DEFAULT '',rne_size INTEGER NOT NULL DEFAULT 0,columns_json TEXT NOT NULL,plan_json TEXT NOT NULL,keys_json TEXT NOT NULL,anchors_json TEXT NOT NULL DEFAULT '[]',row_json TEXT NOT NULL DEFAULT '',observed_speedup REAL,rows INTEGER,cols INTEGER,source TEXT NOT NULL DEFAULT '',proven_at TEXT NOT NULL,PRIMARY KEY(rne_key,mode,parts));
  CREATE TABLE IF NOT EXISTS rne_timing (rne_key TEXT PRIMARY KEY,rne_path TEXT NOT NULL DEFAULT '',execute_seconds REAL,save_seconds REAL,total_seconds REAL,rows INTEGER,cols INTEGER,measured_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS rne_columns (rne_key TEXT PRIMARY KEY,rne_path TEXT NOT NULL,rne_mtime_ns TEXT NOT NULL DEFAULT '',rne_size INTEGER NOT NULL DEFAULT 0,columns_json TEXT NOT NULL,column_count INTEGER NOT NULL DEFAULT 0,row_count INTEGER,source TEXT NOT NULL DEFAULT '',job_id TEXT NOT NULL DEFAULT '',job_name TEXT NOT NULL DEFAULT '',captured_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_run_history_finished ON run_history(finished_at);
  CREATE TABLE IF NOT EXISTS rne_axis_blocks (rne_key TEXT NOT NULL,axis_name TEXT NOT NULL,rne_path TEXT NOT NULL DEFAULT '',parts INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',server_message TEXT NOT NULL DEFAULT '',values_count INTEGER NOT NULL DEFAULT 0,blocked_at TEXT NOT NULL,PRIMARY KEY(rne_key,axis_name));
  CREATE TABLE IF NOT EXISTS rne_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,rne_key TEXT NOT NULL,rne_path TEXT NOT NULL DEFAULT '',job_id TEXT NOT NULL DEFAULT '',job_name TEXT NOT NULL DEFAULT '',finished_at TEXT NOT NULL,hour INTEGER NOT NULL DEFAULT 0,weekday INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT '',trigger TEXT NOT NULL DEFAULT '',engine TEXT NOT NULL DEFAULT '',shape TEXT NOT NULL DEFAULT '',how TEXT NOT NULL DEFAULT '',parts INTEGER NOT NULL DEFAULT 0,row_axis TEXT NOT NULL DEFAULT '',rows INTEGER,cols INTEGER,elapsed REAL,execute_seconds REAL,save_seconds REAL,merge_seconds REAL,axis_seconds REAL,transfer_bytes INTEGER,transfer_kbs REAL,lines INTEGER NOT NULL DEFAULT 0,host TEXT NOT NULL DEFAULT '',cpu INTEGER NOT NULL DEFAULT 0,format TEXT NOT NULL DEFAULT '');
  CREATE INDEX IF NOT EXISTS idx_rne_runs_key ON rne_runs(rne_key,finished_at);
  """)
   c.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('schema_version','2')")
  ensure_schema_upgrades()
  ensure_settings_migrations()
  # マスターがまだ無ければ、初期状態のローカルをBOXへ書き戻して作成する。
  if not MASTER_SETTINGS_DB.exists():flush_local_to_master('initial-seed')
  _settings_initialized=True


def ensure_settings_migrations():
 # 設定値そのものの移行。schema_infoへ実施済みを記録し、一度だけ適用する。
 # 以後ユーザーが意図的に変更した値を、起動のたびに上書きし返さないための記録である。
 try:
  with settings_connection() as c:
   done={r['key'] for r in c.execute("SELECT key FROM schema_info WHERE key LIKE 'migrated_%'")}
   if 'migrated_parallel_max_lines_24' in done:return
   row=c.execute("SELECT value,value_type FROM app_settings WHERE key='settings'").fetchone()
   if row:
    settings=_decode_setting(row) or {}
    current=int(settings.get('api_parallel_max_lines',0) or 0)
    # 旧版の上限8が保存されたままだと、対応済みの24を選んでも黙って8へ切り詰められる。
    if 0<current<PARALLEL_LINES_SUPPORTED_MAX:
     settings['api_parallel_max_lines']=PARALLEL_LINES_SUPPORTED_MAX
     encoded,kind=_encode_setting(settings)
     c.execute("UPDATE app_settings SET value=?,value_type=?,updated_at=? WHERE key='settings'",(encoded,kind,datetime.now().isoformat(timespec='seconds')))
     log.info('SETTINGS_MIGRATION api_parallel_max_lines %s -> %s',current,PARALLEL_LINES_SUPPORTED_MAX)
   c.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('migrated_parallel_max_lines_24','1')")
  _mark_settings_dirty()
 except Exception:
  log.exception('SETTINGS_MIGRATION_FAILED key=api_parallel_max_lines')

def ensure_schema_upgrades():
 # 既存DBへ後方互換で列を追加する。動的命名（naming_mode / output_pattern）・用途コメント（comment）用。
 with settings_connection() as c:
  cols=[r['name'] for r in c.execute('PRAGMA table_info(jobs)')]
  if 'naming_mode' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN naming_mode TEXT NOT NULL DEFAULT 'fixed'")
  if 'output_pattern' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN output_pattern TEXT NOT NULL DEFAULT ''")
  if 'comment' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN comment TEXT NOT NULL DEFAULT ''")
  if 'period_json' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN period_json TEXT NOT NULL DEFAULT ''")
  if 'split_mode' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN split_mode TEXT NOT NULL DEFAULT 'auto'")
  # 行分割で使う軸の決め方。本番の実行には画面が無いので、対象ごとに覚えておく。
  if 'row_axis_mode' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN row_axis_mode TEXT NOT NULL DEFAULT 'first'")
  if 'row_axis_index' not in cols:c.execute('ALTER TABLE jobs ADD COLUMN row_axis_index INTEGER NOT NULL DEFAULT 1')
  if 'row_axis_name' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN row_axis_name TEXT NOT NULL DEFAULT ''")
  # 同時に出す形式。抽出は1回のままで、変換と公開だけを形式のぶん繰り返す。
  if 'extra_formats' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN extra_formats TEXT NOT NULL DEFAULT ''")
  # SQLite3出力に付ける索引の列。読み手が絞り込みで使う列を対象ごとに覚えておく。
  if 'index_columns' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN index_columns TEXT NOT NULL DEFAULT ''")
  # 前回と中身が同じなら公開しない（対象ごとに選ぶ。既定は従来どおり毎回公開する）。
  if 'skip_if_unchanged' not in cols:c.execute('ALTER TABLE jobs ADD COLUMN skip_if_unchanged INTEGER NOT NULL DEFAULT 0')
  rc=[r['name'] for r in c.execute('PRAGMA table_info(rne_columns)')]
  if rc and 'classify_json' not in rc:c.execute("ALTER TABLE rne_columns ADD COLUMN classify_json TEXT NOT NULL DEFAULT ''")
  # 条件欄のデータ項目。絞り込みの条件が付くのはここにある項目だけなので、行分割の判断に要る。
  if rc and 'condition_json' not in rc:c.execute("ALTER TABLE rne_columns ADD COLUMN condition_json TEXT NOT NULL DEFAULT ''")
  st=[r['name'] for r in c.execute('PRAGMA table_info(split_trials)')]
  if st and 'metrics' not in st:c.execute("ALTER TABLE split_trials ADD COLUMN metrics TEXT NOT NULL DEFAULT ''")
  jr=[r['name'] for r in c.execute('PRAGMA table_info(job_runs)')]
  if jr and 'metrics' not in jr:c.execute("ALTER TABLE job_runs ADD COLUMN metrics TEXT NOT NULL DEFAULT ''")
  if 'split_shape' not in cols:c.execute("ALTER TABLE jobs ADD COLUMN split_shape TEXT NOT NULL DEFAULT 'auto'")
  # 割り当ては分け方（列/行/行×列）ごとに持つ。以前は片数だけを鍵にしていたため、
  # 「列2分割」と「行2分割」が同じ行を奪い合い、あとから測った方で上書きされていた。
  # 鍵は作り直すしかないので、古い表の中身を列分割として移し替える。
  sp=[r['name'] for r in c.execute('PRAGMA table_info(split_plans)')]
  if sp and 'mode' not in sp:
   c.execute("ALTER TABLE split_plans RENAME TO split_plans_old")
   c.execute("CREATE TABLE split_plans (rne_key TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'column',parts INTEGER NOT NULL,rne_path TEXT NOT NULL DEFAULT '',rne_mtime_ns TEXT NOT NULL DEFAULT '',rne_size INTEGER NOT NULL DEFAULT 0,columns_json TEXT NOT NULL,plan_json TEXT NOT NULL,keys_json TEXT NOT NULL,anchors_json TEXT NOT NULL DEFAULT '[]',row_json TEXT NOT NULL DEFAULT '',observed_speedup REAL,rows INTEGER,cols INTEGER,source TEXT NOT NULL DEFAULT '',proven_at TEXT NOT NULL,PRIMARY KEY(rne_key,mode,parts))")
   c.execute("INSERT INTO split_plans(rne_key,mode,parts,rne_path,rne_mtime_ns,rne_size,columns_json,plan_json,keys_json,anchors_json,row_json,observed_speedup,rows,cols,source,proven_at) SELECT rne_key,'column',parts,rne_path,rne_mtime_ns,rne_size,columns_json,plan_json,keys_json,anchors_json,'',observed_speedup,rows,cols,source,proven_at FROM split_plans_old")
   c.execute("DROP TABLE split_plans_old")
   log.info('SCHEMA_UPGRADE split_plans 分け方ごとに保存できるようにしました（既存は列分割として引き継ぎ）')
  elif sp and 'row_json' not in sp:
   c.execute("ALTER TABLE split_plans ADD COLUMN row_json TEXT NOT NULL DEFAULT ''")

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

def _decode_period(raw):
 # ジョブごとの相対期間（動的日付）設定を後方互換で読み出す。未設定は無効扱い。
 try:d=json.loads(raw) if raw else {}
 except Exception:d={}
 if not isinstance(d,dict):d={}
 unit=d.get('unit'); unit=unit if unit in ('month','day') else 'month'
 def _int(v,default=0):
  try:return int(v)
  except Exception:return default
 return {'enabled':bool(d.get('enabled',False)),'control_point':str(d.get('control_point') or '').strip(),'unit':unit,'from_offset':_int(d.get('from_offset',0)),'to_offset':_int(d.get('to_offset',0))}

# 出力形式の読み替え・拡張子・同時出力の絞り込み・食い違い検査は navi_output.py。
from navi_output import (OUTPUT_FORMAT_LABEL,normalize_output_format,output_extension,
                         parse_output_format,job_extra_formats,canonical_output_file,
                         validate_output_contract)

# job_output_plan だけはここに残す。名前の組み立て（resolve_output_filename）と
# 組で動くもので、形式の話だけでは完結しないため。
def job_output_plan(job,cfg,now=None):
 """この対象が1回の実行で作るファイルの一覧。先頭が主で、名前は拡張子だけが違う。

 抽出は共通の中間データ（CSV）まで一度で済むので、形式を増やしても増えるのは
 変換と公開だけ。取り直しは発生しない。"""
 base=resolve_output_filename(job,cfg,now)
 primary=normalize_output_format(job.get('output_format'),job.get('output_file'))
 plan=[{'format':primary,'file':base,'primary':True}]
 for f in job_extra_formats(job):
  plan.append({'format':f,'file':canonical_output_file(base,f),'primary':False})
 return plan
# ---- 動的ファイル名（変数命名）----------------------------------------------
# 出力ファイル名に変数を埋め込み、実行のたびに展開する。
#   日付系: {now:%Y%m%d} {exec:...} {datetime} {date} {time} {rne_mtime:%Y%m%d} {rne_ctime:%Y%m%d}
#   文字列系: {rne} {rne:left:4} {rne:right:3} {rne:mid:2:3} {rne:upper} {rne:replace:A:B} {name} {table}
_ILLEGAL_FILENAME=re.compile(r'[\\/:*?"<>|]')
# 記号の数で桁数を調整できる日付書式（%を使わない簡易パターン）。
# Y=年 / M=月 / D(またはd)=日 / H(またはh)=時(24h) / m=分 / s=秒。連続した同一記号の数がそのまま桁数（ゼロ埋め幅）になる。
# 例: {date:YYYYMD} -> 年4桁+月1桁+日1桁 / {date:YYMMDD} -> 年2桁+月2桁+日2桁 / {time:h:s} -> 時:秒。
_CUSTOM_DATE_TOKEN=re.compile(r'(Y+|M+|D+|d+|H+|h+|m+|s+|[^YMDHhmsd]+)')
def format_custom_datetime(dt,pattern):
 if dt is None:return ''
 out=[]
 for run in _CUSTOM_DATE_TOKEN.findall(str(pattern or '')):
  ch=run[0];n=len(run)
  if ch=='Y':out.append(str(dt.year%(10**n)).zfill(n) if n<4 else f'{dt.year:0{n}d}')
  elif ch=='M':out.append(f'{dt.month:0{n}d}')
  elif ch in ('D','d'):out.append(f'{dt.day:0{n}d}')
  elif ch in ('H','h'):out.append(f'{dt.hour:0{n}d}')
  elif ch=='m':out.append(f'{dt.minute:0{n}d}')
  elif ch=='s':out.append(f'{dt.second:0{n}d}')
  else:out.append(run)
 return ''.join(out)
def _looks_like_custom_pattern(arg):
 # %を含まず、Y/M/D/h/m/s のいずれかを含むものを桁数調整パターンとみなす。
 return bool(arg) and '%' not in arg and re.search(r'[YMDdHhms]',str(arg)) is not None
def _apply_text_op(value,arg):
 value=str(value)
 if not arg:return value
 parts=arg.split(':');op=parts[0].strip().lower()
 try:
  if op=='left':return value[:max(0,int(parts[1]))]
  if op=='right':n=max(0,int(parts[1]));return value[-n:] if n>0 else ''
  if op=='mid':start=int(parts[1]);length=int(parts[2]);return value[start:start+length]
  if op=='upper':return value.upper()
  if op=='lower':return value.lower()
  if op=='replace':return value.replace(parts[1],parts[2] if len(parts)>2 else '')
 except Exception:return value
 return value

# ---- 日付の計算（EDATE / DateAdd 相当）----------------------------------------
# 基準日（現在日時 / 対象ファイル更新日 / 対象ファイル作成日）を軸に、年・月・週・日・時・分・秒を
# 前後へずらしてから命名へ使えるようにする。トークンの対象名の直後へ +N / -N を並べて指定する。
#   例: {now-1M:YYYYMMDD}      -> 現在日時の1ヶ月前
#       {rne_ctime+2Y-1M:YYYYMM} -> 対象ファイル作成日の2年後かつ1ヶ月前（年→月→週→日→時→分→秒の順で適用）
#       {now-7D:YYYYMMDD}       -> 現在日時の7日前
# 単位: Y=年 / M=月 / W=週 / D(またはd)=日 / H(またはh)=時 / I=分 / S=秒。
_DATE_OFFSET_UNIT=re.compile(r'([+-]\d+)([YMWDdHhIS])')
_SOURCE_OFFSET=re.compile(r'^([A-Za-z_]+)((?:[+-]\d+[YMWDdHhIS])+)?$')
def _shift_months(dt,months):
 # 月・年のずらし。EDATEと同様に、日が存在しない場合は月末へ丸める。
 total=dt.year*12+(dt.month-1)+int(months);y,m=total//12,total%12+1
 last=calendar.monthrange(y,m)[1]
 return dt.replace(year=y,month=m,day=min(dt.day,last))
def apply_date_offset(dt,offset_text):
 # 対象名に付いた +N/-N の並びを、年→月→週→日→時→分→秒の順で適用する。
 if dt is None or not offset_text:return dt
 order={'Y':0,'M':1,'W':2,'D':3,'d':3,'H':4,'h':4,'I':5,'S':6}
 parts=sorted(_DATE_OFFSET_UNIT.findall(offset_text),key=lambda p:order.get(p[1],9))
 for sign_num,unit in parts:
  n=int(sign_num)
  if unit=='Y':dt=_shift_months(dt,n*12)
  elif unit=='M':dt=_shift_months(dt,n)
  elif unit=='W':dt=dt+timedelta(weeks=n)
  elif unit in ('D','d'):dt=dt+timedelta(days=n)
  elif unit in ('H','h'):dt=dt+timedelta(hours=n)
  elif unit=='I':dt=dt+timedelta(minutes=n)
  elif unit=='S':dt=dt+timedelta(seconds=n)
 return dt
def split_source_offset(key):
 # トークンの対象名から、基準名と日付計算(オフセット)を分離する。未指定なら (key,'') を返す。
 m=_SOURCE_OFFSET.match(str(key or ''))
 if not m:return str(key or ''),''
 return m.group(1),(m.group(2) or '')

def render_filename_template(template,job=None,rne_path=None,now=None):
 job=job or {};now=now or datetime.now()
 stem=Path(str(job.get('rne') or job.get('rne_path') or '')).stem
 mtime=ctime=None
 try:
  p=Path(rne_path) if rne_path else None
  if p and p.is_file():
   st=p.stat();mtime=datetime.fromtimestamp(st.st_mtime);ctime=datetime.fromtimestamp(getattr(st,'st_ctime',st.st_mtime))
 except Exception:pass
 date_tokens={'now':(now,'%Y%m%d_%H%M%S'),'exec':(now,'%Y%m%d_%H%M%S'),'datetime':(now,'%Y%m%d_%H%M%S'),'date':(now,'%Y%m%d'),'time':(now,'%H%M%S'),'rne_mtime':(mtime,'%Y%m%d'),'mtime':(mtime,'%Y%m%d'),'rne_ctime':(ctime,'%Y%m%d'),'ctime':(ctime,'%Y%m%d')}
 text_tokens={'rne':stem,'rne_name':stem,'rne_stem':stem,'name':str(job.get('name') or ''),'job':str(job.get('name') or ''),'table':str(job.get('table') or '')}
 def repl(m):
  raw=m.group(1).strip();key=raw.split(':',1)[0].strip();arg=raw.split(':',1)[1] if ':' in raw else ''
  base,offset=split_source_offset(key)
  if base in date_tokens:
   dt,default=date_tokens[base]
   if not dt:return ''
   dt=apply_date_offset(dt,offset)
   if _looks_like_custom_pattern(arg):return format_custom_datetime(dt,arg)
   try:return dt.strftime(arg or default)
   except Exception:return dt.strftime(default)
  if key in text_tokens:return _apply_text_op(text_tokens[key],arg)
  return m.group(0)
 rendered=re.sub(r'\{([^}]*)\}',repl,str(template or ''))
 rendered=_ILLEGAL_FILENAME.sub('',rendered);rendered=re.sub(r'\s+',' ',rendered).strip().strip('.')
 return rendered or 'output'

# 命名で使用できる既知トークンのキー一覧。実際に展開できる（＝本当に変数である）ものだけを判定に使う。
_KNOWN_TOKEN_KEYS={'now','exec','datetime','date','time','rne_mtime','mtime','rne_ctime','ctime','rne','rne_name','rne_stem','name','job','table'}
def _pattern_variable_keys(pattern):
 keys=set()
 for m in re.finditer(r'\{([^}]*)\}',str(pattern or '')):
  key=m.group(1).strip().split(':',1)[0].strip()
  base,_off=split_source_offset(key)
  if base in _KNOWN_TOKEN_KEYS:keys.add(base)
 return keys
def has_template_variables(pattern):
 # 単に変数入力欄へ文字を入れただけ（例: SIKALOTDEF）は変数扱いしない。既知トークン {..} が実在する場合だけTrue。
 return bool(_pattern_variable_keys(pattern))
def render_filename_segments(template,job=None,rne_path=None,now=None):
 """命名パターンを『固定部分』と『変数から展開された部分』へ分解する。
 一覧の出力ファイル名で、元が変数である箇所へ色を付けるために使用する。"""
 job=job or {};now=now or datetime.now()
 stem=Path(str(job.get('rne') or job.get('rne_path') or '')).stem
 mtime=ctime=None
 try:
  p=Path(rne_path) if rne_path else None
  if p and p.is_file():
   st=p.stat();mtime=datetime.fromtimestamp(st.st_mtime);ctime=datetime.fromtimestamp(getattr(st,'st_ctime',st.st_mtime))
 except Exception:pass
 date_tokens={'now':(now,'%Y%m%d_%H%M%S'),'exec':(now,'%Y%m%d_%H%M%S'),'datetime':(now,'%Y%m%d_%H%M%S'),'date':(now,'%Y%m%d'),'time':(now,'%H%M%S'),'rne_mtime':(mtime,'%Y%m%d'),'mtime':(mtime,'%Y%m%d'),'rne_ctime':(ctime,'%Y%m%d'),'ctime':(ctime,'%Y%m%d')}
 text_tokens={'rne':stem,'rne_name':stem,'rne_stem':stem,'name':str(job.get('name') or ''),'job':str(job.get('name') or ''),'table':str(job.get('table') or '')}
 def expand(raw):
  raw=raw.strip();key=raw.split(':',1)[0].strip();arg=raw.split(':',1)[1] if ':' in raw else ''
  base,offset=split_source_offset(key)
  if base in date_tokens:
   dt,default=date_tokens[base]
   if not dt:return '',True
   dt=apply_date_offset(dt,offset)
   if _looks_like_custom_pattern(arg):return format_custom_datetime(dt,arg),True
   try:return dt.strftime(arg or default),True
   except Exception:return dt.strftime(default),True
  if key in text_tokens:return _apply_text_op(text_tokens[key],arg),True
  return '{'+raw+'}',False
 pattern=str(template or '');segments=[];pos=0
 for m in re.finditer(r'\{([^}]*)\}',pattern):
  if m.start()>pos:segments.append({'text':pattern[pos:m.start()],'var':False})
  text,is_var=expand(m.group(1));segments.append({'text':text,'var':is_var});pos=m.end()
 if pos<len(pattern):segments.append({'text':pattern[pos:],'var':False})
 out=[]
 for s in segments:
  t=_ILLEGAL_FILENAME.sub('',s['text'])
  if t=='':continue
  if out and out[-1]['var']==s['var']:out[-1]['text']+=t
  else:out.append({'text':t,'var':s['var']})
 return out

def resolve_output_filename(job,cfg,now=None):
 fmt=normalize_output_format(job.get('output_format'),job.get('output_file'))
 mode=str(job.get('naming_mode') or 'fixed').lower()
 if mode=='template' and str(job.get('output_pattern') or '').strip():
  rp=None
  try:rp=resolve_rne_path(job,cfg)
  except Exception:rp=None
  base=render_filename_template(job.get('output_pattern'),job=job,rne_path=rp,now=now)
 else:
  base=Path(str(job.get('output_file') or 'output')).stem
 return canonical_output_file(base,fmt)

def _json_list(text):
 """控えDBに入っているJSON配列を、文字列の一覧として読む。"""
 try:v=json.loads(text or '[]')
 except Exception:return []
 return [str(x).strip() for x in v if str(x).strip()] if isinstance(v,list) else []

def _json_or_empty(text):
 try:return json.loads(text or '{}') or {}
 except Exception:return {}

def record_job_run(job_id,job_name,status_value,trigger,detail='',rows=None,cols=None,output_file='',metrics=None):
 if not job_id:return
 now=datetime.now().isoformat(timespec='seconds')
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(job_id,job_name,now,status_value,trigger,detail,rows,cols,output_file,now,json.dumps(metrics or {},ensure_ascii=False)))
   # カレンダーの実施履歴用に追記式でも保持する（job_runsは最新1件のみのため）。
   c.execute('INSERT INTO run_history(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file) VALUES(?,?,?,?,?,?,?,?,?)',(job_id,job_name,now,status_value,trigger,detail,rows,cols,output_file))
   # 実施履歴は直近2000件へ制限し、肥大化を防ぐ。
   c.execute('DELETE FROM run_history WHERE id NOT IN (SELECT id FROM run_history ORDER BY id DESC LIMIT 2000)'); _mark_settings_dirty()
 except Exception:
  log.exception('JOB_RUN_RECORD_FAILED job=%s',job_name)

def load_job_runs():
 try:
  with settings_connection() as c:
   return {r['job_id']:{'finished_at':r['finished_at'],'status':r['status'],'trigger':r['trigger'],'detail':r['detail'],'rows':r['rows'],'cols':r['cols'],'output_file':r['output_file'],'metrics':_json_or_empty(r['metrics'] if 'metrics' in r.keys() else '')} for r in c.execute('SELECT * FROM job_runs')}
 except Exception:
  return {}

# ---- RNEの列定義キャッシュ ------------------------------------------------
# 列名はRNEを開いただけでは取れない（公式APIに列を列挙する関数が無い）。実行結果からしか分からないので、
# 一度得た列名をRNE単位で保存し、次からはそれを使う。RNEが更新されたら作り直す。
# 同じRNEを複数の対象が使うことがあるため、キーは対象IDではなくRNEのパスにしている。

def rne_signature(path):
 """RNEの版を表す指紋。更新されたかどうかの判定にだけ使う。"""
 try:
  st=Path(path).stat();return str(st.st_mtime_ns),int(st.st_size)
 except OSError:
  return '',0

def _rne_key(path):
 try:return os.path.normcase(os.path.normpath(str(Path(path).resolve())))
 except Exception:return os.path.normcase(os.path.normpath(str(path)))

def load_column_cache(rne_path):
 """RNEの列定義キャッシュを返す。RNEが更新されていれば stale=True を付けて返す。"""
 key=_rne_key(rne_path)
 try:
  with settings_connection() as c:
   row=c.execute('SELECT * FROM rne_columns WHERE rne_key=?',(key,)).fetchone()
 except Exception:
  return None
 if not row:return None
 mtime,size=rne_signature(rne_path)
 stale=bool(mtime) and (mtime!=row['rne_mtime_ns'] or size!=row['rne_size'])
 try:columns=json.loads(row['columns_json'])
 except Exception:columns=[]
 try:classify=json.loads(row['classify_json'] or '[]')
 except Exception:classify=[]
 try:condition=json.loads((row['condition_json'] if 'condition_json' in row.keys() else '') or '[]')
 except Exception:condition=[]
 return {'rne_path':row['rne_path'],'columns':columns,'column_count':row['column_count'],'row_count':row['row_count'],
         'source':row['source'],'job_id':row['job_id'],'job_name':row['job_name'],'captured_at':row['captured_at'],
         'stale':stale,'classify':classify,'condition':condition}

def save_condition_items(rne_path,names):
 """条件欄のデータ項目名を覚えておく。行分割で条件を付けられるのはここにある項目だけで、
 出力される列（データ欄）に同じ条件を設定しても1行も絞られない（2026-08-10の実測）。"""
 names=[str(x) for x in (names or []) if str(x).strip()!='']
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('UPDATE rne_columns SET condition_json=? WHERE rne_key=?',(json.dumps(names,ensure_ascii=False),_rne_key(rne_path)))
   _mark_settings_dirty()
 except Exception:
  log.exception('CONDITION_ITEMS_SAVE_FAILED rne=%s',rne_path);return False
 log.info('CONDITION_ITEMS_SAVE rne=%s count=%s names=%s',rne_path,len(names),' | '.join(names[:20]))
 return True

def save_column_classification(rne_path,classify):
 """列の分類結果（削除できる / 必ず残る）をキャッシュへ書き足す。列名の一覧は触らない。"""
 key=_rne_key(rne_path)
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('UPDATE rne_columns SET classify_json=? WHERE rne_key=?',(json.dumps(classify,ensure_ascii=False),key));_mark_settings_dirty()
 except Exception:
  log.exception('COLUMN_CLASSIFY_SAVE_FAILED rne=%s',rne_path);return False
 removable=sum(1 for x in classify if x.get('removable'))
 log.info('COLUMN_CLASSIFY_SAVE rne=%s total=%s removable=%s fixed=%s',rne_path,len(classify),removable,len(classify)-removable)
 return True

def save_column_cache(rne_path,columns,rows=None,source='run',job=None):
 """列定義をRNE単位で保存する。列名が取れなかったときは何もしない（空で上書きしない）。"""
 columns=[str(x) for x in (columns or []) if str(x).strip()!='']
 if not columns:return None
 key=_rne_key(rne_path);mtime,size=rne_signature(rne_path);now=datetime.now().isoformat(timespec='seconds')
 job=job or {}
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('INSERT OR REPLACE INTO rne_columns(rne_key,rne_path,rne_mtime_ns,rne_size,columns_json,column_count,row_count,source,job_id,job_name,captured_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
             (key,str(rne_path),mtime,size,json.dumps(columns,ensure_ascii=False),len(columns),rows,source,str(job.get('id') or ''),str(job.get('name') or ''),now))
   _mark_settings_dirty()
 except Exception:
  log.exception('COLUMN_CACHE_SAVE_FAILED rne=%s',rne_path);return None
 log.info('COLUMN_CACHE_SAVE rne=%s columns=%s rows=%s source=%s mtime_ns=%s size=%s',rne_path,len(columns),rows,source,mtime,size)
 return columns

def column_cache_state(rne_path):
 """キャッシュの状態を hit / stale / miss の3値で返す。ログとUIの表示に使う。"""
 hit=load_column_cache(rne_path)
 if not hit:return 'miss',None
 return ('stale' if hit['stale'] else 'hit'),hit

def read_header_names(path,job):
 """出力ファイルの見出し行だけを読む。中身は読まないので大きなファイルでも軽い。"""
 path=Path(path);fmt=normalize_output_format(job.get('output_format'),path.name)
 if fmt=='sqlite3':
  with sqlite3.connect(path) as conn:
   table=str(job.get('table') or '')
   names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_更新情報' ORDER BY name")]
   if table not in names:table=names[0] if names else ''
   if not table:return []
   return [x[1] for x in conn.execute(f'PRAGMA table_info({qi(table)})')]
 if fmt in ('csv','txt'):
  delimiter=',' if fmt=='csv' else '\t'
  for enc in ('utf-8-sig','cp932','utf-8'):
   try:
    with path.open('r',encoding=enc,newline='') as h:
     return next(csv.reader(h,delimiter=delimiter),[])
   except UnicodeDecodeError:continue
  return []
 if fmt=='xlsx':
  from openpyxl import load_workbook
  wb=load_workbook(path,read_only=True,data_only=True)
  try:
   ws=wb[job.get('sheet')] if job.get('sheet') in wb.sheetnames else wb[wb.sheetnames[0]]
   return [x for x in next(ws.iter_rows(values_only=True),()) if x is not None]
  finally:wb.close()
 # ACCDBはCOM経由で開くコストが高いので、列定義の取得元には使わない。
 return []

# ---- 列分割 --------------------------------------------------------------
# 1つのRNEを複数プロセスで開き、各プロセスが担当外の列を外して問い合わせ、結果を横に結合する。
# 削除できない列（管理ポイント由来）は全パートに残るので、そのまま結合キーになる。

class SplitRowsetMismatch(ValueError):
 """パートごとに返る行が違う。列を外すと行も変わる問い合わせで起きる。"""
 def __init__(self,message,first_rows=0,other_rows=0,part=''):
  super().__init__(message);self.first_rows=first_rows;self.other_rows=other_rows;self.part=part

def merge_row_parts(part_files,dest,encoding='cp932'):
 """行分割の結果を縦に積む。見出しは1回だけ書く。

 列分割の突き合わせと違い、こちらは値を照合しない。行は重複しないので、順に足すだけでよい。
 そのぶん安い（実測で3.65〜5.54秒かかっていた結合が、ほぼ只になる）。
 ただし見出しが1つでも食い違えば、列の対応が崩れているので必ず例外にする。
 """
 files=[Path(x) for x in part_files]
 if not files:raise ValueError('結合するパートがありません')
 head=None;rows=0
 dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
 with dest.open('w',encoding=encoding,newline='') as out:
  w=csv.writer(out)
  for i,f in enumerate(files):
   with f.open('r',encoding=encoding,newline='') as h:
    rd=csv.reader(h);hd=next(rd,None)
    if hd is None:raise ValueError(f'{f.name} が空です')
    if head is None:
     head=hd;w.writerow(head)
    elif hd!=head:
     raise ValueError(f'{f.name} の見出しが1つ目と違います（{len(hd)}列 対 {len(head)}列）。'
                      '行分割では全パートが同じ列を返すはずです')
    for r in rd:
     w.writerow(r);rows+=1
 return rows,len(head or [])

# 「分割なし」の測定結果は取っておく。毎回セットで走らせると1回あたり2倍の時間がかかるうえ、
# 回線の混み具合が違う時間帯の値を比べることになる。基準は基準として1回測り、あとで使い回す。
def split_baseline_dir(rne_path):
 # _rne_key はフルパスなので、そのままではフォルダー名に使えない。短く畳んで名前にする。
 import hashlib
 name=hashlib.sha1(_rne_key(rne_path).encode('utf-8',errors='replace')).hexdigest()[:16]
 d=LOCAL_RUNTIME/'split_baseline'/f'{Path(rne_path).stem}_{name}';d.mkdir(parents=True,exist_ok=True);return d

def save_split_baseline(rne_path,job,csv_path,base,columns,elapsed):
 d=split_baseline_dir(rne_path)
 try:shutil.copy2(str(csv_path),str(d/'normal.csv'))
 except Exception:
  log.exception('SPLIT_BASELINE_COPY_FAILED rne=%s',rne_path);return None
 meta={'rne':str(rne_path),'job':str((job or {}).get('name') or ''),'rows':base.get('rows'),'cols':base.get('cols'),
       'size':base.get('size'),'elapsed':round(float(elapsed or 0),2),
       'execute':base.get('execute_elapsed'),'save':base.get('save_elapsed'),
       'columns':list(columns or []),'taken_at':datetime.now().isoformat(timespec='seconds')}
 (d/'meta.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
 log.info('SPLIT_BASELINE_SAVE rne=%s rows=%s cols=%s size=%s elapsed=%.2fs path=%s',
          rne_path,meta['rows'],meta['cols'],meta['size'],meta['elapsed'],d/'normal.csv')
 return meta

def load_split_baseline(rne_path):
 d=split_baseline_dir(rne_path);m=d/'meta.json';f=d/'normal.csv'
 if not (m.is_file() and f.is_file()):return None
 try:meta=json.loads(m.read_text(encoding='utf-8'))
 except Exception:
  log.warning('SPLIT_BASELINE_BROKEN rne=%s',rne_path);return None
 meta['file']=str(f)
 try:meta['age_days']=round((datetime.now()-datetime.fromisoformat(meta.get('taken_at') or '')).total_seconds()/86400,1)
 except Exception:meta['age_days']=None
 return meta

def save_axis_survey(rne_path,axes,parts):
 """「分け方を探す」で読んだ軸の一覧を覚えておく。

 影実行のたびに同じ問い合わせ（20秒前後）を繰り返さないためのもの。あくまで目安で、
 分割点は実行の直前に読み直した値から決める（resolve_axis_now）。
 """
 if not axes:return None
 d=split_baseline_dir(rne_path);mtime,size=rne_signature(rne_path)
 rec={'rne':str(rne_path),'axes':axes,'parts':int(parts or 0),'rne_mtime_ns':mtime,'rne_size':size,
      'taken_at':datetime.now().isoformat(timespec='seconds')}
 try:(d/'axes.json').write_text(json.dumps(rec,ensure_ascii=False),encoding='utf-8')
 except Exception:
  log.exception('AXIS_SURVEY_SAVE_FAILED rne=%s',rne_path);return None
 log.info('AXIS_SURVEY_SAVE rne=%s 軸=%s本',rne_path,len(axes))
 return rec

def read_axis_survey_raw(rne_path):
 """控えをそのまま読む。古いかどうかの判断はしない（状態を画面へ出すために要る）。"""
 f=split_baseline_dir(rne_path)/'axes.json'
 if not f.is_file():return None
 try:rec=json.loads(f.read_text(encoding='utf-8'))
 except Exception:
  log.warning('AXIS_SURVEY_BROKEN rne=%s',rne_path);return None
 mtime,size=rne_signature(rne_path)
 rec['fresh']=bool(mtime) and str(mtime)==str(rec.get('rne_mtime_ns')) and int(size or 0)==int(rec.get('rne_size') or 0)
 try:rec['age_hours']=(datetime.now()-datetime.fromisoformat(rec.get('taken_at') or '')).total_seconds()/3600
 except Exception:rec['age_hours']=None
 return rec

def load_axis_survey(rne_path,max_age_hours=None):
 """覚えておいた軸の一覧。RNEが更新されていたら使わない。

 同じファイルであるかぎり、何日前のものでも使う。分割点は実行の直前に読み直すので
 （resolve_axis_now）、この控えは「どんな軸があるか」の目安にしかならない。
 時間で捨てていたころは、ファイルが1バイトも変わっていなくても翌日には20〜100秒かけて
 読み直しになっていた。max_age_hours を渡したときだけ、時間でも捨てる。
 """
 rec=read_axis_survey_raw(rne_path)
 if not rec:return None
 if not rec.get('fresh'):
  log.info('AXIS_SURVEY_STALE rne=%s RNEが更新されているので読み直します',rne_path);return None
 age=rec.get('age_hours')
 if max_age_hours is not None and age is not None and age>float(max_age_hours):
  log.info('AXIS_SURVEY_OLD rne=%s %.1f時間前のものなので読み直します',rne_path,age);return None
 return rec

SPLIT_MEASURE=('both','split','normal')
def normalize_measure(value,race=False):
 """何を測るか。both=分割なしと分割ありを続けて / split=分割だけ / normal=分割なしだけ。

 競争は「同じ回線を奪い合わせて決着を見る」測り方そのものなので、必ず両方を同時に走らせる。
 """
 v=str(value or 'both').lower()
 if race:return 'both'
 return v if v in SPLIT_MEASURE else 'both'

def split_how_label(mode,col_parts,row_parts):
 """何をどう分けているかの呼び名。列と行を取り違えないよう、表示はすべてここを通す。"""
 if mode=='row':return f'行{row_parts}分割'
 if mode=='grid':return f'行{row_parts}×列{col_parts}（{row_parts*col_parts}片）'
 return f'列{col_parts}分割'

def split_expected_share(mode,columns,removable,col_parts,row_parts=1,weights=None):
 """1片が運ぶ量が、分割なしの何割になるかの見込み。進み具合の分母に使う。

 列分割 … 固定列が全パートに複製されるので、1片は 1/列数 より大きい（transfer_ratio）。
          合計は分割なしより増える。
 行分割 … 行を分けるだけなので1片は 1/行数。合計は分割なしと同じ。
 行×列 … 両方が効いて 1片は transfer_ratio/行数。合計は列分割と同じだけ増える。
 """
 rp=max(1,int(row_parts or 1));cp=max(1,int(col_parts or 1))
 if mode=='row':return 1.0/rp
 ratio=split_transfer_ratio(columns,removable,cp,weights)
 return ratio/rp if mode=='grid' else ratio

# ---- 行分割の軸（管理ポイント）--------------------------------------------
# 出力される列（データ欄）に条件を付けても1行も絞れない。絞れるのは管理ポイントで、
# 明細データの問い合わせなら表側に必ず1つ以上ある。どのRNEでも使える道はこれだけ。
AXIS_PRIORITY={'表側':0,'表頭':1,'条件':2}

# 行を絞るときは「担当しない値」をぜんぶ条件式へ並べる。値が多いほど式が長くなり、
# ある長さを超えるとデータベースが受け付けない。
#   実測 2026-08-10:
#     登録設備   73種 →  36種を外す（約  150字） 成功（3.42倍）
#     製品単重 1746種 → 876種を外す（約 7,000字） 成功（1.89倍）
#     ﾛｯﾄ番号  7282種 → 3641種を外す（約29,000字） 失敗
#       KVR52020 データベースに対する検索条件式が長すぎるため問い合わせができません
# 通った実績（約7,000字）に少しだけ余裕を持たせた値を上限にする。ここを緩めると
# 「2分かけて条件を組み立てたあとに拒否される」という、いちばん高くつく失敗になる。
ROW_FILTER_MAX_CHARS=9000
# 値を1件ずつ外すのはAPI呼び出しがその数だけ走る。3641件で114秒かかった実測がある。
# 長さの上限より先にこちらへ当たることは少ないが、目安として持っておく。
ROW_FILTER_MAX_VALUES=2500

def row_filter_cost(axis,parts=2):
 """その軸でN分割したとき、1片が条件式へ並べる値の「数」と「文字数」の見積もり。

 見本しか読めていない軸でも平均の長さから見積もる。実行してから拒否されるより、
 走り出す前に「この軸では無理」と分かるほうが安い。
 """
 vals=[str(x) for x in (axis.get('categories') or [])]
 n=int(axis.get('category_count') or len(vals) or 0)
 parts=max(2,int(parts or 2))
 if n<2:return 0,0
 avg=(sum(len(v) for v in vals)/len(vals)) if vals else 8.0
 excluded=int(n*(parts-1)/parts)          # 1片が外す値の数
 return excluded,int(excluded*(avg+1))    # +1 は区切り文字ぶん

def axis_filter_too_long(axis,parts=2):
 """条件式が長くなりすぎる軸か。なるなら理由を返す。"""
 if axis.get('is_time'):return ''         # 期間は from〜to の2つだけ。長さの心配は無い
 cnt,chars=row_filter_cost(axis,parts)
 if chars>ROW_FILTER_MAX_CHARS:
  return (f'値が{int(axis.get("category_count") or 0)}種あり、{parts}分割すると1片で{cnt}種を'
          f'条件式へ並べます（約{chars:,}字）。データベースが受け付ける長さを超えるため使えません')
 if cnt>ROW_FILTER_MAX_VALUES:
  return f'値が多すぎます（{parts}分割で1片が{cnt}種を外すことになります）'
 return ''

def axis_usable(a,parts=2):
 """その軸で行を分けられるか。理由も返す。"""
 if a.get('is_time'):
  pr=a.get('period') or {}
  if pr.get('from') and pr.get('to'):return True,'期間で区切る'
  return False,'期間が設定されていません'
 if a.get('over8000'):
  # DLLが一覧にできる上限（8000件）を超えている。この軸は値で分けられない。
  return False,'値が8000件を超えるため一覧にできません'
 n=a.get('category_count')
 if n is None:return False,(a.get('category_error') or '値の数を読めません')
 if int(n)<2:
  return False,(f'値が{n}種しかありません'+(f'（{a.get("category_error")}）' if a.get('category_error') else ''))
 # 値が多すぎる軸は、条件式が長すぎてデータベースに拒否される。実行する前に外す。
 toolong=axis_filter_too_long(a,parts)
 if toolong:return False,toolong
 return True,f'{n}種の値を組に分ける'

# 行の軸をどうやって決めるか。用途に応じて4通り。
#   first    … 表側の1番目を決め打ち（調査不要）。明細のRNEなら必ず1本はあるので、これが既定。
#   index    … 表側の指定番号を決め打ち（調査不要）。使う軸が分かっているとき。
#   name     … 名前で指定（「分け方を探す」で選んだもの）。番号が動いても追随する。
#   balanced … 表側のうち、行の散らばりが最もよいものを自動で選ぶ。直近の出力から実際の
#              分布を測るので、いちばん重い片が小さくなる＝いちばん速くなる軸を選べる。
ROW_AXIS_MODES=('first','index','name','balanced')
ROW_AXIS_MODE_LABEL={'first':'表側の1番目（調査不要）','index':'番号で指定（調査不要）',
                     'name':'名前で指定（調べて選ぶ）','balanced':'偏りが少ないものを自動で選ぶ'}
def normalize_row_axis_mode(v):
 v=str(v or 'first').lower()
 return v if v in ROW_AXIS_MODES else 'first'

def row_axis_choice(data,job=None):
 """軸の決め方を1か所で組み立てる。

 その場の指定（画面）＞ 対象に保存された設定 ＞ 既定（表側の1番目）の順に効かせる。
 本番の実行には画面が無いので、対象に保存された設定がそのまま使われる。
 """
 d=data or {};j=job or {}
 mode=d.get('row_axis_mode') if d.get('row_axis_mode') is not None else j.get('row_axis_mode')
 name=d.get('row_axis_name') if d.get('row_axis_name') is not None else j.get('row_axis_name')
 idx=d.get('row_axis_index') if d.get('row_axis_index') is not None else j.get('row_axis_index')
 # 「分け方を探す」で選んだ名前を直接渡された場合は、名前指定として扱う
 if not mode and str(d.get('row_column') or '').strip():mode='name';name=d.get('row_column')
 try:idx=max(1,min(200,int(idx or 1)))
 except Exception:idx=1
 return {'mode':normalize_row_axis_mode(mode),'index':idx,'name':str(name or '').strip()}

def axis_balance_scores(job,cfg,names):
 """直近の出力から、軸ごとに「いちばん多い値が全体の何割を占めるか」を測る。

 割合が小さいほど均等に分けられる。出力が無い/その列が無いものは None（測れない）。
 読むのは1回だけ。何十本も別々に読むと、それだけで待たされる。
 """
 names=[str(x) for x in (names or []) if str(x).strip()!='']
 if not names:return {}
 try:
  op=_viewer_output_path(job,cfg)
  if not op.is_file():return {}
  got=column_samples(op,job,names)
 except Exception:
  log.exception('AXIS_BALANCE_FAILED job=%s',(job or {}).get('name'));return {}
 out={}
 for nm in names:
  counts=((got.get('columns') or {}).get(nm) or {}).get('counts') or None
  if not counts:continue
  total=sum(counts.values())
  if total<=0:continue
  blank=sum(n for v,n in counts.items() if str(v).strip()=='')
  # 出力に無い列は「全行が空」として返ってくる。測れなかったものとして黙って外す
  # （そのままだと「1つの値で100%」＝いちばん偏った軸に見えてしまう）。
  if blank>=total:continue
  out[nm]={'top_share':max(counts.values())/total,'distinct':len(counts),'rows':total,'blank_rows':blank}
 return out

def block_row_axis(rne_path,axis_name,reason,server_message='',parts=0,values=0):
 """サーバーに拒否された軸を覚えておく。次からはこの軸を選ばない。

 「実行してみないと分からない」ものは、一度分かった時点で残さないと同じ失敗を繰り返す。
 KVR52020（検索条件式が長すぎる）がこれに当たる。
 """
 if not axis_name:return False
 init_settings_db()
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('INSERT OR REPLACE INTO rne_axis_blocks(rne_key,axis_name,rne_path,parts,reason,server_message,values_count,blocked_at) VALUES(?,?,?,?,?,?,?,?)',
             (_rne_key(rne_path),str(axis_name),str(rne_path),int(parts or 0),str(reason),str(server_message)[:400],
              int(values or 0),datetime.now().isoformat(timespec='seconds')))
   _mark_settings_dirty()
 except Exception:
  log.exception('ROW_AXIS_BLOCK_SAVE_FAILED rne=%s axis=%s',rne_path,axis_name);return False
 log.warning('ROW_AXIS_BLOCKED rne=%s 軸=%s 値=%s種 %s分割 理由=%s サーバー=%s（次からこの軸は選びません）',
             rne_path,axis_name,values,parts,reason,str(server_message)[:120])
 return True

def blocked_row_axes(rne_path):
 """このRNEで使えないと分かっている軸。{名前: 理由} を返す。"""
 init_settings_db()
 try:
  with settings_connection() as c:
   rows=list(c.execute('SELECT axis_name,reason,values_count,parts,blocked_at FROM rne_axis_blocks WHERE rne_key=?',
                       (_rne_key(rne_path),)))
 except Exception:
  return {}
 return {r['axis_name']:{'reason':r['reason'],'values':r['values_count'],'parts':r['parts'],'at':r['blocked_at']}
         for r in rows}

def clear_row_axis_blocks(rne_path):
 init_settings_db()
 try:
  with settings_sync_lock, settings_connection() as c:
   n=c.execute('DELETE FROM rne_axis_blocks WHERE rne_key=?',(_rne_key(rne_path),)).rowcount;_mark_settings_dirty()
  return n
 except Exception:
  log.exception('ROW_AXIS_BLOCK_CLEAR_FAILED rne=%s',rne_path);return 0

def axis_loses_rows(name,scores):
 """その軸で分けると行が落ちるか。落ちるなら落ちる行数を返す（落ちなければ0）。

 値が空の行は、どのカテゴリにも当てはまらない。カテゴリで絞ると、そういう行はどの片にも
 入らず結果から消える。2026-08-10の実測では、検査番号が空の36行が毎回そうして欠けた
 （分割なし14485行 に対し 結合14449行）。NaviReloadCategory の nonmatch で拾おうとしたが
 このDLLには拒否された（rc=0x15）。したがって、空のある軸は最初から使わないのが唯一の手。
 """
 sc=(scores or {}).get(str(name or ''))
 return int((sc or {}).get('blank_rows') or 0)

def pick_row_axis_by_mode(axes,parts=2,mode='first',index=1,name='',scores=None,blocked=None):
 """決められた方針で軸を1本選ぶ。選べなければ理由を付けて返す。

 どの方針でも、最後は pick_row_axis を通す（使えない軸を掴まないため）。
 値が空の行がある軸は、行が落ちるので既定では選ばない（名前で名指しされたときだけ通す）。
 blocked には、過去にサーバーが拒否した軸を渡す。同じ失敗を繰り返さないため。
 """
 mode=normalize_row_axis_mode(mode)
 blocked=blocked or {}
 usable=[a for a in (axes or []) if axis_usable(a,parts)[0] and a.get('name') not in blocked]
 # 空の行がある軸は結果が合わなくなるので、選ぶ対象から外す。
 # ただし全部が該当するときは外さない（1本も選べなくなるほうが困る）。
 safe=[a for a in usable if not axis_loses_rows(a.get('name'),scores)]
 if scores and safe:usable=safe
 note=''
 if mode=='name' and str(name or '').strip():
  best,ranked=pick_row_axis(axes,parts,str(name).strip(),blocked)
  if best and best.get('name')==str(name).strip():
   return best,ranked,f'名前で指定された「{name}」を使います'
  note=f'指定された「{name}」は使えないので、表側の1番目に戻します'
 elif mode=='index':
  want=max(1,int(index or 1))
  hit=next((a for a in usable if a.get('location')=='表側' and int(a.get('index') or 0)+1==want),None)
  if hit:
   best,ranked=pick_row_axis(axes,parts,hit.get('name',''),blocked)
   if best and best.get('name')==hit.get('name'):
    return best,ranked,f'指定された表側#{want}「{hit.get("name")}」を使います'
  note=f'指定された表側#{want}は使えないので、表側の1番目に戻します'
 elif mode=='balanced':
  sc=scores or {}
  cand=[(sc[a['name']]['top_share'],int(a.get('index') or 0),a) for a in usable
        if a.get('location')=='表側' and a.get('name') in sc]
  cand.sort(key=lambda x:(x[0],x[1]))
  if cand:
   share,_,a=cand[0]
   best,ranked=pick_row_axis(axes,parts,a.get('name',''),blocked)
   if best and best.get('name')==a.get('name'):
    return best,ranked,(f'表側のうち最も散らばっている「{a.get("name")}」を選びました'
                        f'（いちばん多い値が{share:.0%}。候補{len(cand)}本から）')
  note='直近の出力から散らばりを測れないので、表側の1番目に戻します'
 # first、および上の方針で決まらなかった場合。表側の1番目から順に、使える軸を探す。
 # usable は空の行がある軸を外したあとなので、ここでも行の落ちない軸が先に来る。
 # 過去に拒否された軸は、理由を添えて一覧にも残す（なぜ飛ばしたのかが追えるように）。
 order=sorted(usable,key=lambda a:(AXIS_PRIORITY.get(a.get('location'),9),int(a.get('index') or 0)))
 head=order[0].get('name','') if order else ''
 best,ranked=pick_row_axis(axes,parts,head,blocked)
 if best:
  skipped=''
  if scores and best.get('name')!=(sorted([a for a in (axes or []) if axis_usable(a,parts)[0]],
                                          key=lambda a:(AXIS_PRIORITY.get(a.get('location'),9),
                                                        int(a.get('index') or 0)))[:1] or [{}])[0].get('name'):
   skipped='（手前の軸は値が空の行があり、分けると行が落ちるので飛ばしました）'
  return best,ranked,(note+'。' if note else '')+f'表側から順に見て「{best.get("name")}」を使います'+skipped
 return None,ranked,note or '使える軸がありません'

def pick_row_axis(axes,parts=2,prefer='',blocked=None):
 """行分割に使う軸を選ぶ。表側の先頭を最優先にする（明細データなら必ず在る）。

 名前を指定されたときはそれを優先する。使えない軸は理由を付けて外す。
 """
 blocked=blocked or {}
 ranked=[]
 for a in (axes or []):
  ok,why=axis_usable(a,parts)
  if ok and a.get('name') in blocked:
   ok=False;why='前回サーバーに拒否されました（%s）'%(blocked[a['name']].get('reason') or '理由不明')
  n=int(a.get('category_count') or 0)
  ranked.append(dict(a,usable=ok,reason=why,
                     rank=(0 if prefer and a.get('name')==prefer else 1,
                           AXIS_PRIORITY.get(a.get('location'),9),int(a.get('index') or 0)),
                     enough=(a.get('is_time') or n>=parts)))
 ranked.sort(key=lambda x:x['rank'])
 best=next((x for x in ranked if x['usable'] and x['enough']),None)
 return best,ranked

def resolve_axis_now(job,cfg,rne_path,parts,prefer='',hint=None,line='',choice=None):
 """実行の直前に、軸と値をサーバーから読み直す。分割点は必ずこの結果から決める。

 事前に調べた一覧は目安にしかならない。仕掛のように件数が動くものは、調べた時点と
 実行する時点で値の顔ぶれが変わる。使うのは常に「いま返ってきた値」。
 hint に事前の軸を渡すと、変化のぐあいをログに残す。
 choice に軸の決め方（mode/index/name）を渡すと、その方針で選ぶ。
 """
 out={'axis':None,'ranked':[],'error':'','parts':0,'drift':None,'why':''}
 try:
  user,pw,server,_=creds(resolve_path(cfg['symnavim_conf']))
  ins=run_inspect_worker(dict(job,_read_names=True),cfg,user,pw,server,['axes'],
                         timeout=int(cfg['settings'].get('split_trial_timeout_seconds',1800) or 1800))
 except Exception as e:
  out['error']=str(e);log.exception('AXIS_NOW_FAILED rne=%s',rne_path);return out
 if not ins.get('ok'):
  out['error']=ins.get('error') or '管理ポイントを読み取れませんでした';return out
 # 「2つに割れるか」で選び、頼まれた数に届くかは選んだあとに落として合わせる（axis_usable_parts）。
 # ここで parts を要求すると、4分割に届かないだけの良い軸を捨てて悪い軸へ流れてしまう。
 got=ins.get('axes') or []
 ch=dict(choice or {})
 if prefer:ch={'mode':'name','name':prefer}      # 名前を直接渡されたらそれが最優先
 mode=normalize_row_axis_mode(ch.get('mode'))
 # 散らばりは常に測る。どの決め方でも「値が空の行がある軸」を避けたいので必ず要る。
 # 直近の出力を1回読むだけなので、費用は無視できる。
 scores=axis_balance_scores(job,cfg,[a.get('name') for a in got])
 # 過去にサーバーが拒否した軸は選ばない。条件式の長さは実行してみるまで分からないので、
 # 一度分かったものは覚えておく（KVR52020 検索条件式が長すぎる）。
 blocked=blocked_row_axes(rne_path)
 axis,ranked,why=pick_row_axis_by_mode(got,max(2,int(parts or 2)),mode,ch.get('index') or 1,ch.get('name') or '',scores,blocked)
 if blocked:log.info('ROW_AXIS_BLOCKS rne=%s 使わない軸=%s',rne_path,'、'.join(blocked))
 out['ranked']=ranked;out['why']=why
 if scores:
  for a in sorted(scores.items(),key=lambda x:x[1]['top_share'])[:6]:
   log.info('AXIS_BALANCE 軸=%s いちばん多い値=%.1f%% 種類=%s 空=%s行%s',
            a[0],a[1]['top_share']*100,a[1]['distinct'],a[1]['blank_rows'],
            '（空の行があるので分けると落ちます。この軸は使いません）' if a[1]['blank_rows'] else '')
 lost=axis_loses_rows((axis or {}).get('name'),scores)
 if lost:
  log.warning('AXIS_BLANK_RISK rne=%s 軸=%s 値が空の行が%s行あります。この軸で分けるとその行が結果から落ちます',
              rne_path,(axis or {}).get('name'),lost)
  out['blank_rows']=lost
 if not axis:
  out['error']=('いま行を分けられる管理ポイントがありません。表側・表頭・条件のどれかに'
                '「2種類以上の値を持つ管理ポイント」または「期間が設定された時間型」が要ります。'
                +('（読み取れた軸: '+'、'.join(f"{x['location']}/{x['name']}（{x['reason']}）" for x in ranked[:6])+'）'
                  if ranked else '（管理ポイントを1つも読み取れませんでした）'))
  return out
 # 使う軸が決まってから、その1本の値を読み切る。ここで全部そろわなければ分けない
 # （一部だけで組を作ると、読めなかった値の行がどこにも入らず落ちる）。
 if not axis.get('is_time'):
  try:
   vs=run_inspect_worker(dict(job,_read_names=True,_axis={'column':axis['name'],'locate':axis['locate'],
                                                          'location':axis['location'],'index':axis['index']}),
                         cfg,user,pw,server,['axis_values'],
                         timeout=int(cfg['settings'].get('split_trial_timeout_seconds',1800) or 1800))
  except Exception as e:
   out['error']=f'軸の値を読めませんでした: {e}';return out
  av=(vs.get('axis_values') or {}) if vs.get('ok') else {}
  if not vs.get('ok'):
   out['error']=vs.get('error') or '軸の値を読めませんでした';return out
  axis=dict(axis,categories=av.get('values') or [],category_count=av.get('count'),
            category_error=av.get('error') or '',load_form=av.get('load_form') or '')
  if not av.get('complete'):
   out['error']=(f'「{axis["name"]}」の値を全部は読めませんでした'
                 f'（{av.get("count")}種のうち{len(av.get("values") or [])}種）。'
                 '一部だけで分けると、読めなかった値の行が結果から落ちるため中止します')
   out['axis']=axis;return out
  log.info('AXIS_NOW_VALUES 軸=%s 値=%s種 読み込み=%s',axis['name'],len(axis['categories']),axis.get('load_form'))
 out['axis']=axis
 out['parts']=axis_usable_parts(axis,parts)
 if hint:
  # 事前調査は見本を数件しか読んでいない（64本ぶんの値を全部読むと待たされるため）。
  # 顔ぶれの差を出せるのは事前も全部読めていたときだけ。ふだんは「種類の数」どうしを比べる。
  before=int(hint.get('category_count') or 0) if not hint.get('is_time') else 0
  after=int(axis.get('category_count') or 0) if not axis.get('is_time') else 0
  hs=set(hint.get('categories') or []);ns=set(axis.get('categories') or [])
  full=bool(not hint.get('is_time') and before and len(hs)>=before)
  gone=sorted(hs-ns) if full else []
  added=sorted(ns-hs) if full else []
  out['drift']={'before':before,'after':after,'added':len(added),'gone':len(gone),'diff':after-before,
                'compared':'values' if full else 'count','added_sample':added[:8],'gone_sample':gone[:8],
                'same_axis':hint.get('name')==axis.get('name')}
  how=(f'増={len(added)} 減={len(gone)}' if full else
       ('差なし' if after==before else f'差={after-before:+d}（事前は見本のみ）'))
  log.info('AXIS_NOW%s rne=%s 軸=%s 事前=%s種 → いま=%s種（%s）分割数=%s%s',
           f' line={line}' if line else '',rne_path,axis['name'],before,after,how,out['parts'],
           '' if out['parts']==parts else f'（頼まれた{parts}分割には足りないので{out["parts"]}分割にします）')
 else:
  log.info('AXIS_NOW%s rne=%s 軸=%s（%s %s番目 / %s）いまの値=%s種 分割数=%s',
           f' line={line}' if line else '',rne_path,axis['name'],axis['location'],axis['index']+1,
           axis['type_name'],axis.get('category_count'),out['parts'])
 log.info('AXIS_NOW_CHOICE rne=%s 決め方=%s → %s',rne_path,normalize_row_axis_mode((choice or {}).get('mode')),out['why'])
 return out

def axis_usable_parts(axis,want):
 """その軸で実際に何分割できるか。頼まれた数に届かなければ、届く数まで落とす。

 仕掛のように中身が動くものは、事前に調べた値の数と実行時の値の数が違う。
 実行の直前に読み直した値で決め直すための計算。
 """
 want=max(1,int(want or 2))
 if axis.get('is_time'):
  for n in range(want,1,-1):
   if split_period_range((axis.get('period') or {}).get('from'),(axis.get('period') or {}).get('to'),n):return n
  return 1
 return max(1,min(want,len(axis.get('categories') or [])))

def balance_values(values,parts,weights=None):
 """値を parts 組へ配る。重み（その値の行数の目安）があれば、重みの合計が均等になるように配る。

 重みが分からない値は「よくある大きさ」＝中央値として扱う。実行時に増えていた値がここに入る。
 平均ではなく中央値を使う。ひとつの値が全体の9割を占めるような軸では、平均が実態から大きく
 離れるためで、2026-08-10の実測では 614種で全14279行を説明できているのに、重みの無い255種へ
 平均(23.3)を配って合計を42%も水増しし、片寄りを実際より軽く見せていた。
 重みそのものが目安なので、狙うのは完全な均等ではなく、極端な偏りを避けること。
 """
 vals=[str(v) for v in (values or [])]
 parts=max(1,int(parts))
 if len(vals)<parts or parts<1:return None
 w={str(k):float(v) for k,v in (weights or {}).items() if str(k) in set(vals)}
 fill=1.0
 if w:
  s=sorted(w.values());m=len(s)
  fill=max(1.0,(s[m//2] if m%2 else (s[m//2-1]+s[m//2])/2))
 items=sorted(((float(w.get(v,fill)),v) for v in vals),key=lambda x:(-x[0],x[1]))
 bins=[[0.0,[]] for _ in range(parts)]
 for wt,v in items:
  b=min(bins,key=lambda x:(x[0],len(x[1])))
  b[0]+=wt;b[1].append(v)
 if any(not b[1] for b in bins):return None
 return [{'values':b[1],'weight':round(b[0],1)} for b in bins]

def axis_value_weights(job,cfg,name):
 """直近の出力から、その軸の値ごとの行数を数える。あくまで配り方の目安。

 出力が無い / その列が出力に含まれない場合は None を返し、値の数だけで均す。
 数字そのものは古くなるが、「どの値が重いか」の傾向は当たることが多い。
 """
 if not name:return None
 try:
  op=_viewer_output_path(job,cfg)
  if not op.is_file():return None
  got=column_samples(op,job,[name])
  info=(got.get('columns') or {}).get(name) or {}
  counts=info.get('counts') or None
  if counts:log.info('AXIS_WEIGHTS 軸=%s 直近の出力から %s種の重みを得ました（合計%s行 / 目安）',
                     name,len(counts),sum(counts.values()))
  return counts
 except Exception as e:
  log.info('AXIS_WEIGHTS 軸=%s 重みを取れませんでした（%s）。値の数だけで均します',name,e);return None

def plan_axis_split(axis,parts,weights=None,total_rows=0):
 """軸をパートへ割り当てる。時間型は期間を等分し、それ以外は値を組に配る。

 ここへ渡す軸は、実行の直前にサーバーから読み直したものを使うこと。
 事前に調べた一覧のまま配ると、仕掛のように中身が動くものでは取りこぼす。
 """
 parts=max(1,int(parts))
 if parts<2:return None
 if axis.get('is_time'):
  pr=axis.get('period') or {}
  cuts=split_period_range(pr.get('from'),pr.get('to'),parts)
  if not cuts:return None
  each=int(total_rows/parts) if total_rows else 0
  return [{'index':i+1,'row_axis':{'kind':'period','column':axis['name'],'locate':axis['locate'],
                                   'location':axis['location'],'index':axis['index'],'part':i+1,'parts':parts,
                                   'from':f,'to':t,'total_rows':int(total_rows or 0),'expect_rows':each}}
          for i,(f,t) in enumerate(cuts)]
 vals=[str(x) for x in (axis.get('categories') or [])]
 groups=balance_values(vals,parts,weights)
 if not groups:return None
 # 行数の見込み。所要時間の記録がまだ無いRNEでは total_rows=0 で渡ってくるため、
 # 直近の出力から数えた重みの合計で代える。0のままだと「見込み0行」とだけ出て何も分からない。
 if not total_rows and weights:
  try:total_rows=int(sum(weights.values()))
  except Exception:total_rows=0
 total_w=sum(g['weight'] for g in groups) or 0.0
 out=[]
 for i,g in enumerate(groups):
  mine=set(g['values'])
  expect=int(round(total_rows*g['weight']/total_w)) if (total_rows and total_w) else 0
  # part は「何番目の片か」。実行時に増えていた値を最後の片が引き取るために要る
  # （どの片にも入らない値があると、その行が結果から落ちる）。index は管理ポイントの並び順。
  out.append({'index':i+1,'row_axis':{'kind':'category','column':axis['name'],'locate':axis['locate'],
                                      'location':axis['location'],'index':axis['index'],
                                      'part':i+1,'parts':parts,
                                      'values':g['values'],'others':[v for v in vals if v not in mine],
                                      'total_rows':int(total_rows or 0),'expect_rows':expect,
                                      'weight':g['weight']}})
 return out

def axis_skew(plan,weights=None):
 """割り当てた片の重さの片寄り。並列で待たされるのは一番重い片なので、そこを見る。

 1つの値だけで全体の大半を占める軸は、何組に分けても一番重い片が縮まない。
 分割してもさほど速くならないとき、その理由がここに出る。
 """
 if not plan or len(plan)<2:return None
 ws=[float((x.get('row_axis') or {}).get('weight') or 0) for x in plan]
 rows=[int((x.get('row_axis') or {}).get('expect_rows') or 0) for x in plan]
 base=rows if sum(rows)>0 else ws
 total=sum(base)
 if total<=0:return None
 n=len(base);even=total/n;mx=max(base)
 # 占有率は、行数の見込みと同じ物差しで出す。別々の分母で出すと
 # 「単独で9割なのに一番重い片は6割」のような、噛み合わない数字が並ぶ。
 top=None
 solo=[(b,len((x.get('row_axis') or {}).get('values') or [])) for b,x in zip(base,plan)]
 one=[r for r,k in solo if k==1]
 if one:top=max(one)/total
 if top is None and weights:
  try:top=max(float(v) for v in weights.values())/float(sum(float(v) for v in weights.values()) or 1)
  except Exception:top=None
 return {'parts':n,'max_rows':int(round(mx)),'even_rows':int(round(even)),
         'ratio':round(mx/even,2) if even else 0,'total_rows':int(round(total)),
         'top_share':round(top,4) if top else None,
         'ceiling':round(total/mx,2) if mx else 0}

def split_period_range(start,end,parts):
 """YYYYMMDD の期間を parts 等分する。月度指定（末尾00）はその形のまま返す。"""
 start=str(start or '');end=str(end or '')
 if len(start)!=8 or len(end)!=8 or not start.isdigit() or not end.isdigit():return None
 month=start.endswith('00') and end.endswith('00')
 try:
  if month:
   a=int(start[:4])*12+int(start[4:6])-1;b=int(end[:4])*12+int(end[4:6])-1
   if b<=a:return None
   step=(b-a+1)/parts
   out=[]
   for i in range(parts):
    lo=a+int(round(i*step));hi=a+int(round((i+1)*step))-1
    if i==parts-1:hi=b
    if hi<lo:return None
    out.append((f'{lo//12:04d}{lo%12+1:02d}00',f'{hi//12:04d}{hi%12+1:02d}00'))
   return out
  a=datetime.strptime(start,'%Y%m%d');b=datetime.strptime(end,'%Y%m%d')
  days=(b-a).days
  if days<parts:return None
  out=[]
  for i in range(parts):
   lo=a+timedelta(days=int(round(i*days/parts)))
   hi=(a+timedelta(days=int(round((i+1)*days/parts))-1)) if i<parts-1 else b
   if hi<lo:return None
   out.append((lo.strftime('%Y%m%d'),hi.strftime('%Y%m%d')))
  return out
 except Exception:
  return None

def plan_grid_split(cand,row_parts,column_plan):
 """行×列の組み合わせ。行の各組について、列の各パートを作る。

 片の数は row_parts × 列パート数。1片が運ぶ量は「行の割合 × 列の割合」まで小さくなるが、
 固定列は列パートごとに複製されるので、合計で運ぶ量は列分割と同じだけ増える。
 そこが行だけで分けたときとの違いで、まさにそれを測りたい。
 """
 rows=plan_row_split(cand,row_parts)
 if not rows or not column_plan:return None
 out=[]
 for r in rows:
  for c in column_plan:
   out.append({'index':len(out)+1,'row_group':r['index'],'col_group':c['index'],
               'row':r['row'],'drop':list(c.get('drop') or []),'keep':list(c.get('keep') or [])})
 return out

def plan_row_split(cand,parts):
 """行分割の割り当て。候補（範囲の区切り）から、パートごとの条件を作る。"""
 calls=(row_condition_calls(cand) or {}).get('calls') or []
 if len(calls)!=parts:return None
 # 全体の行数も持たせる。条件が効かず全件が返ったことを、実行側で見破るために使う。
 total=int(cand.get('rows') or 0)
 for c in calls:c['total_rows']=total
 return [{'index':i+1,'row':c,'expect_rows':c['rows']} for i,c in enumerate(calls)]


def duplicate_columns(columns):
 """同じ名前が2回以上現れる列を返す。

 列分割は列名を同一性の手がかりにしている（担当外を名前で外し、結合で名前を突き合わせる）。
 同名の列があると、外す対象を取り違えたり、結合で片方が消えたりする。
 見つけたら分割は行わない。
 """
 seen={}
 for c in columns or []:seen[c]=seen.get(c,0)+1
 return [{'name':n,'count':k} for n,k in seen.items() if k>1]

def column_weights(path,job,columns):
 """直近の出力ファイルから、列ごとの「データ量」と「値の入っている割合」を1回の走査で数える。

 分割の効き目を決めるのは列数ではなくデータ量。また、担当列が全部空の行は問い合わせ結果から
 落ちるため、どの列が常に埋まっているかも同時に調べる（各パートへ1本入れる錨にする）。
 """
 path=Path(path);fmt=normalize_output_format(job.get('output_format'),path.name)
 names=list(columns);n=len(names)
 size=[0]*n;filled=[0]*n;rows=0
 # 錨を選ぶには件数だけでなく「どの行が埋まっているか」が要る。列ごとに1バイト/行で持つ。
 mask=[bytearray() for _ in range(n)]
 if fmt=='sqlite3':
  with sqlite3.connect(path) as conn:
   table=str(job.get('table') or '')
   tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_更新情報' ORDER BY name")]
   if table not in tables:table=tables[0] if tables else ''
   if not table:return None
   cols=[x[1] for x in conn.execute(f'PRAGMA table_info({qi(table)})')]
   # RNEを差し替えた直後は、出力ファイルにまだ無い列がある。あるぶんだけ測って先へ進む。
   pos={c:cols.index(c) for c in names if c in cols}
   if not pos:return None
   missing=[c for c in names if c not in pos]
   if missing:log.info('COLUMN_WEIGHTS_PARTIAL 出力ファイルにまだ無い列 %s 件（例: %s）',len(missing),missing[:5])
   idx=[pos.get(c) for c in names]
   for r in conn.execute(f'SELECT * FROM {qi(table)}'):
    rows+=1
    for k,i in enumerate(idx):
     v=None if i is None else r[i]
     if v is None or v=='':mask[k].append(0);continue
     mask[k].append(1);filled[k]+=1;size[k]+=len(str(v))
 elif fmt in ('csv','txt'):
  delimiter=',' if fmt=='csv' else '\t'
  data=None
  for enc in ('utf-8-sig','cp932','utf-8'):
   try:
    with path.open('r',encoding=enc,newline='') as h:data=csv.reader(h,delimiter=delimiter);hdr=next(data,[]);break
   except UnicodeDecodeError:continue
  if data is None:return None
  with path.open('r',encoding=enc,newline='') as h:
   rd=csv.reader(h,delimiter=delimiter);hdr=next(rd,[])
   pos={c:hdr.index(c) for c in names if c in hdr}
   if not pos:return None
   idx=[pos.get(c) for c in names]
   for r in rd:
    rows+=1
    for k,i in enumerate(idx):
     v=(r[i] if i<len(r) else '') if i is not None else ''
     if not v:mask[k].append(0);continue
     mask[k].append(1);filled[k]+=1;size[k]+=len(v)
 else:
  return None
 if not rows:return None
 total=sum(size) or 1
 return {'rows':rows,'total_bytes':total,'masks':{names[k]:mask[k] for k in range(n)},
         'columns':{names[k]:{'bytes':size[k],'share':size[k]/total,'filled':filled[k],'fill_ratio':filled[k]/rows} for k in range(n)}}

# ---- 行分割の下調べ --------------------------------------------------------
# 行を分けるには、サーバーへ渡せる<述語>が要る。APIに「k行目からm行目」は無いので
# （NaviDownLoadData は前へ進むだけのカーソルで、開始位置の引数が無い）、
# 「この列がこの値の行」という条件で分けるしかない。
# ただし分割点を人が決める必要は無い。直前の出力ファイルを1回読めば、どの列をどう割ると
# 最も均等になるかは、サーバーに触らずに分かる。列の重みを測るのと同じやり方。

def column_samples(path,job,columns,exact_limit=5000,sample_limit=4000):
 """直近の出力から、列ごとの値の分布を1回の走査で集める。

 値の種類が exact_limit までなら正確に数える。それを超えた列は、その時点から
 一定数の標本だけを残す（種類が多い列こそ範囲条件で半分に割るのに向くので、諦めない）。
 標本から求めた区切りは1%程度ずれ得るが、実際の行数はサーバー側で数え直して確かめる。
 """
 import random as _rnd
 path=Path(path);fmt=normalize_output_format(job.get('output_format'),path.name)
 names=list(columns);n=len(names)
 counts=[{} for _ in range(n)];sample=[None]*n;seen=[0]*n;rows=0;rng=_rnd.Random(20260808)
 def feed(vals):
  nonlocal rows
  rows+=1
  for i,v in enumerate(vals):
   v='' if v is None else str(v)
   seen[i]+=1
   if sample[i] is None:
    c=counts[i]
    if v in c:c[v]+=1
    elif len(c)<exact_limit:c[v]=1
    else:
     # 種類が多すぎた。ここからは標本に切り替える（それまでの値も種として入れておく）。
     sample[i]=list(c.keys())[:sample_limit];c.clear();sample[i].append(v)
   else:
    sm=sample[i]
    if len(sm)<sample_limit:sm.append(v)
    else:
     k=rng.randrange(seen[i])
     if k<sample_limit:sm[k]=v
 if fmt=='sqlite3':
  with sqlite3.connect(path) as conn:
   table=str(job.get('table') or '')
   tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_更新情報' ORDER BY name")]
   if table not in tables:table=tables[0] if tables else ''
   if not table:return None
   cols=[x[1] for x in conn.execute(f'PRAGMA table_info({qi(table)})')]
   pos={c:cols.index(c) for c in names if c in cols}
   if not pos:return None
   idx=[pos.get(c) for c in names]
   for r in conn.execute(f'SELECT * FROM {qi(table)}'):
    feed([(r[i] if i is not None and i<len(r) else None) for i in idx])
 elif fmt in ('csv','txt'):
  delimiter=',' if fmt=='csv' else '\t'
  done=False
  for enc in ('utf-8-sig','cp932','utf-8'):
   try:
    with path.open('r',encoding=enc,newline='') as h:
     rd=csv.reader(h,delimiter=delimiter);head=next(rd,[])
     pos={c:head.index(c) for c in names if c in head}
     if not pos:return None
     idx=[pos.get(c) for c in names]
     for row in rd:feed([(row[i] if i is not None and i<len(row) else None) for i in idx])
    done=True;break
   except UnicodeDecodeError:continue
  if not done:return None
 else:
  return None
 out={}
 for i,name in enumerate(names):
  if sample[i] is not None:out[name]={'exact':False,'values':sample[i],'distinct':None}
  elif counts[i]:out[name]={'exact':True,'counts':counts[i],'distinct':len(counts[i])}
 return {'rows':rows,'columns':out}

_NUMERIC_RE=re.compile(r'^-?\d{1,18}(\.\d+)?$')
def _looks_numeric(v):
 return bool(_NUMERIC_RE.match(str(v).strip()))

def range_cuts(info,rows,parts):
 """値を大小で並べ、行数が揃うところで parts 個へ区切る。

 区切りは「この値以下」「この値より大きい」の形にする（NaviChangeConditionDI の
 lvalue / rvalue にそのまま渡せる形）。並び順は文字列として比べる。サーバー側が
 数値として比べる列では境目がずれ得るので、実際の行数は必ず数え直して確かめること。
 """
 # 数字だけの列は、数として並べないと境目が狂う（'999' と '1898' は文字順では逆）。
 # ただしサーバーが数として比べるか文字として比べるかは分からないので、どちらで並べたかを持ち帰る。
 src=list(info['counts'].items()) if info.get('exact') else [(v,1) for v in info['values']]
 numeric=bool(src) and all(_looks_numeric(v) for v,_ in src if v!='')
 key=(lambda kv:(kv[0]=='',float(kv[0] or 0))) if numeric else (lambda kv:kv[0])
 if info.get('exact'):
  items=sorted(src,key=key)
  total=sum(c for _,c in items)
 else:
  vals=sorted(src,key=key);total=len(vals)
  items=[];prev=None
  for v,_ in vals:
   if v==prev:items[-1]=(v,items[-1][1]+1)
   else:items.append((v,1));prev=v
 if len(items)<parts or total<=0:return None
 want=total/parts;cuts=[];acc=0;got=[]
 for v,c in items:
  acc+=c
  if len(cuts)<parts-1 and acc>=want*(len(cuts)+1):
   cuts.append(v);got.append(acc)
 if len(cuts)<parts-1:return None
 got.append(total)
 sizes=[got[0]]+[got[i]-got[i-1] for i in range(1,len(got))]
 scale=(rows/total) if total else 1                          # 標本のときは全体の行数へ引き伸ばす
 sizes=[int(round(x*scale)) for x in sizes]
 lo=items[0][0];hi=items[-1][0]
 bounds=[]
 for k in range(parts):
  left=lo if k==0 else cuts[k-1]
  right=cuts[k] if k<parts-1 else hi
  bounds.append({'from':left,'to':right,'from_open':k>0,'rows':sizes[k],
                 'share':round(sizes[k]/max(1,sum(sizes)),4)})
 return {'cuts':cuts,'groups':bounds,'balance':round(max(sizes)/(sum(sizes)/parts),3),
         'exact':bool(info.get('exact')),'distinct':info.get('distinct'),
         'order':'numeric' if numeric else 'text'}

def row_condition_calls(cand,include_empty_in=0):
 """区切りの値から、NaviChangeConditionDI へ渡す実際の引数を組み立てる。

 定数は SymNaviApi.bas より:
   condition … NAVI_RANGE(0x2)。空値も拾う組だけ NAVI_NULL(0x4) を足す
   range     … 先頭は NAVI_UNDER(0x1)、最後は NAVI_OVER(0x4)、間は NAVI_BETWEEN(0x2)
   lcheck/rcheck … NAVI_INCLUDE(0x0) / NAVI_NOTINCLUDE(0x1)

 境目を二重に数えないため、2組目以降の下限は「含まない」にする。
 これで全組の和がちょうど全体になる（重なりも抜けも無い）。空値はどこにも入らないので、
 include_empty_in で指定した組へ NAVI_NULL を足して拾う。
 """
 if not cand or cand.get('method')!='range':return None
 NAVI_RANGE,NAVI_NULL=0x2,0x4
 NAVI_BETWEEN=0x2
 INCLUDE,NOTINCLUDE=0x0,0x1
 g=cand['groups'];n=len(g);calls=[]
 lo=str(g[0]['from']);hi=str(g[-1]['to'])      # 列全体の最小と最大。端の組もこれで挟む。
 for i,part in enumerate(g):
  first,last=(i==0),(i==n-1)
  cond=NAVI_RANGE|(NAVI_NULL if cand.get('has_empty') and i==include_empty_in else 0)
  left=lo if first else str(part['from'])
  right=hi if last else str(part['to'])
  calls.append({'part':i+1,'column':cand['column'],'condition':cond,'range':NAVI_BETWEEN,
                'lcheck':(INCLUDE if first else NOTINCLUDE),'lvalue':left,
                'rcheck':INCLUDE,'rvalue':right,
                'rows':part['rows'],
                'text':('≧ ' if first else '＞ ')+left+' かつ ≦ '+right
                       +(' または 空値' if cond&NAVI_NULL else '')})
 return {'column':cand['column'],'calls':calls,'low':lo,'high':hi,
         'covers_empty':bool(cand.get('has_empty')),'expected_rows':sum(x['rows'] for x in calls)}

def balance_groups(counts,parts):
 """値を parts 個の組へ、行数がなるべく揃うように配る。重い値から順に軽い組へ入れる。"""
 groups=[[] for _ in range(parts)];load=[0]*parts
 for v,c in sorted(counts.items(),key=lambda kv:-kv[1]):
  k=load.index(min(load));groups[k].append(v);load[k]+=c
 return groups,load

def row_split_candidates(path,job,columns,removable,parts=2,max_values=200,top=8):
 """行を parts 個へ分ける候補を、直近の出力から探して良い順に返す。サーバーには触れない。

 分け方は列の素性で2通りある。
   データ項目（分割して取れる列） … NaviChangeConditionDI に範囲条件がある（lvalue/rvalue）。
                                    値の種類が多い列ほど、中央付近で正確に半分にできる。
   管理ポイント（必ず残る列）     … NaviChangeConditionCP はカテゴリ指定なので、値の組分けになる。
 """
 got=column_samples(path,job,columns)
 if not got or not got.get('rows'):return None
 rows=got['rows'];rem=set(removable);out=[]
 for name,info in (got.get('columns') or {}).items():
  if name in rem:
   r=range_cuts(info,rows,parts)
   if not r:continue
   x={'column':name,'method':'range','balance':r['balance'],'exact':r['exact'],
               'distinct':r['distinct'],'cuts':r['cuts'],'groups':r['groups'],'rows':rows,
               'order':r['order'],'empty_rows':(info.get('counts') or {}).get('',0)}
   x['has_empty']=bool(x['empty_rows']);x['api']=row_condition_calls(x)
   out.append(x)
  else:
   if not info.get('exact'):continue                         # 種類が多すぎる管理ポイントは列挙できない
   counts=info['counts']
   if len(counts)<parts or len(counts)>max_values:continue
   groups,load=balance_groups(counts,parts)
   if min(load)<=0:continue
   out.append({'column':name,'method':'category','balance':round(max(load)/(rows/parts),3),'exact':True,
               'distinct':len(counts),'rows':rows,'empty_rows':counts.get('',0),
               'groups':[{'values':g,'rows':l,'share':round(l/rows,4)} for g,l in zip(groups,load)]})
 for x in out:x['has_empty']=bool(x.get('empty_rows'))
 # 均等な順。同じなら、範囲条件で書ける方（データ項目）を優先する。
 out.sort(key=lambda x:(x['balance'],0 if x['method']=='range' else 1,0 if x.get('order')!='numeric' else 1))
 return {'rows':rows,'parts':parts,'candidates':out[:top],'examined':len(got.get('columns') or {})}

def pick_anchor_columns(removable,weights,limit=3):
 """全パートに残す「錨」の列を選ぶ。担当列がすべて空の行は結果から落ちるため、
 残した列のどれかに必ず値が入るようにして、行集合を揃える。

 1本で全行を覆えればそれが最善。覆えない場合は、覆う行が多い列から貪欲に足していく。
 limit 本まで足しても全行を覆えないなら、錨は立てない（中途半端に足しても行は落ちる）。
 錨は全パートに複製されるので、本数が増えるほど転送量の得は減る。
 """
 if not weights:return [],0.0
 cw=weights.get('columns') or {};rows=int(weights.get('rows') or 0)
 cand=[c for c in removable if c in cw]
 if not rows or not cand:return [],0.0
 best=max(cand,key=lambda c:cw[c].get('fill_ratio',0))
 if cw[best].get('fill_ratio',0)>=0.999:return [best],1.0
 masks=weights.get('masks') or {}
 if not masks:return [],cw[best].get('fill_ratio',0)
 # 貪欲な集合被覆。まだ覆えていない行を最も多く埋める列を足していく。
 uncovered=bytearray(b'\x01')*rows
 chosen=[]
 for _ in range(max(1,int(limit))):
  pick,gain=None,0
  for c in cand:
   m=masks.get(c)
   if not m or c in chosen:continue
   g=sum(1 for i in range(rows) if uncovered[i] and m[i])
   if g>gain:pick,gain=c,g
  if not pick or not gain:break
  chosen.append(pick);m=masks[pick]
  for i in range(rows):
   if m[i]:uncovered[i]=0
  if not any(uncovered):return chosen,1.0
 covered=1.0-(sum(uncovered)/rows if rows else 0)
 return ([],covered) if covered<0.999 else (chosen,1.0)


def plan_column_split(columns,removable,parts,weights=None,anchors=None):
 """出力列を parts 個の担当に分ける。列の並び順は元のまま保つ。

 分けるのは列数ではなくデータ量。列数で均等に割ると、スカスカな列ばかりのパートができて
 転送量が偏り、分割した意味がなくなる（実測: 34/34に割ってバイトは89%対11%）。
 anchor は全パートに残す列。担当列が全部空の行は結果から落ちるため、
 常に値の入る列を1本ずつ持たせて行集合を揃える。
 """
 parts=max(1,int(parts))
 rem=[c for c in columns if c in set(removable)]
 keys=[c for c in columns if c not in set(removable)]
 anchors=[c for c in (anchors or []) if c in set(rem)]
 rem=[c for c in rem if c not in set(anchors)]
 if parts<2 or len(rem)<parts:
  return [{'index':1,'keep':list(rem),'drop':[],'anchors':list(anchors)}],keys
 cw=(weights or {}).get('columns') or {}
 def w(c):return max(1,int(cw.get(c,{}).get('bytes',0))) if cw else 1
 # 重い列から順に、いちばん軽いパートへ入れる。データ量が揃うように配る。
 groups=[[] for _ in range(parts)];load=[0]*parts
 for c in sorted(rem,key=w,reverse=True):
  k=load.index(min(load));groups[k].append(c);load[k]+=w(c)
 groups=[[c for c in columns if c in set(g)] for g in groups if g]   # 元の並び順へ戻す
 out=[]
 for i,g in enumerate(groups):
  own=set(g)
  out.append({'index':i+1,'keep':list(g),'drop':[c for c in rem if c not in own],'anchors':list(anchors),
              'bytes':sum(w(c) for c in g) if cw else None})
 return out,keys

def split_payload_profile(columns,removable,weights=None):
 """データ量が「全パートに複製される固定列」と「分割できる列」にどう分かれているかを返す。

 分割の効き目の上限を決めるのは固定列の割合。ここが大きいRNEは、何分割しても速くならない。
 RNEを調整して速くしたいときに、まず見るべき数字。
 """
 rem=set(removable);cw=(weights or {}).get('columns') or {}
 if cw:
  rb=sum(cw.get(c,{}).get('bytes',0) for c in columns if c in rem)
  kb=sum(cw.get(c,{}).get('bytes',0) for c in columns if c not in rem)
  unit='bytes'
 else:
  rb=len([c for c in columns if c in rem]);kb=len(columns)-rb;unit='columns'
 total=rb+kb or 1
 return {'unit':unit,'fixed':kb,'splittable':rb,'total':total,
         'fixed_share':round(kb/total,4),'splittable_share':round(rb/total,4)}

def split_transfer_ratio(columns,removable,parts,weights=None):
 """1パートが運ぶデータ量の、分割なしに対する割合。

 列数ではなくデータ量で測る。固定列は全パートが運ぶため、ここが下限になる。
 """
 pf=split_payload_profile(columns,removable,weights)
 if parts<2 or not pf['splittable']:return 1.0
 return (pf['fixed']+pf['splittable']/parts)/pf['total']

def split_speedup_estimate(parts,trials=None,link=None):
 """パート数に対する並列転送の効き目。実測があればそれを優先する。"""
 parts=max(1,int(parts))
 if parts==1:return 1.0
 h=(link or {}).get('headroom')
 if h:return min(float(parts),float(h))     # 回線の空き以上には伸びない
 return 1.0+1.5*(1.0-1.0/parts)             # 実測が無いときの控えめな見積もり

def predict_split_gain(columns,removable,parts,trials=None,timing=None,weights=None,link=None):
 """分割したときの所要時間の見込み（1.0=変わらない、0.6なら4割短縮）。

 肝心なのは、分割で縮むのは「結果の転送・保存」だけだということ。サーバ側の問い合わせ実行は
 行数で決まるため列を減らしても縮まず、しかも各パートが満額払う。
 実測の内訳（timing）があれば、それを使って正直に見積もる。無ければ転送が支配的と仮定する。
 """
 if parts<2 or not [c for c in columns if c in set(removable)]:return 1.0
 ratio=split_transfer_ratio(columns,removable,parts,weights)   # 1パートが運ぶデータ量の割合
 if timing and (timing.get('execute') or 0)>0:
  ex=float(timing['execute']);sv=float(timing.get('save') or 0)
  other=max(0.0,float(timing.get('total') or (ex+sv))-ex-sv)
  base=ex+sv+other
  if base<=0:return 1.0
  # 各パート = サーバ実行(満額) + 転送 + その他。並列なのでこれが全体の所要。
  # 転送は「列の割合」だけでなく「回線がどれだけ伸びるか」でも決まる。
  sp=split_speedup_estimate(parts,trials,link)
  transfer=sv*ratio*parts/sp if sp else sv*ratio
  return round((ex+transfer+other)/base,3)
 return ratio/split_speedup_estimate(parts,trials,link)

def split_gain_reason(columns,removable,parts,timing=None,weights=None):
 """見込みの内訳を、そのまま画面へ出せる形で返す。"""
 pf=split_payload_profile(columns,removable,weights)
 ratio=split_transfer_ratio(columns,removable,max(1,parts),weights)
 if not (timing and (timing.get('execute') or 0)>0):
  return {'measured':False,'ratio':round(ratio,3),'payload':pf}
 ex=float(timing['execute']);sv=float(timing.get('save') or 0)
 other=max(0.0,float(timing.get('total') or (ex+sv))-ex-sv);base=ex+sv+other
 return {'measured':True,'ratio':round(ratio,3),'execute':round(ex,1),'save':round(sv,1),'other':round(other,1),
         'total':round(base,1),'execute_share':round(ex/base,3) if base else 0,
         'floor':round((ex+other+sv*pf['fixed_share'])/base,3) if base else 1.0,'payload':pf}

def split_volume_cap(weights=None,timing=None,min_part_mb=2.0,min_gain_seconds=5.0):
 """データ量から見た、分割数の上限。

 パートを1本増やすたびに、セッション接続・カタログ読込・プロセス起動の固定費がかかる。
 小さなデータを細かく割ると、その固定費が得を食い潰す。運ぶ量が少ないほど上限を低くする。
 """
 total=(weights or {}).get('total_bytes') or 0
 if not total:return None,'データ量が不明'
 mb=total/1024/1024
 cap=max(1,int(mb//max(0.1,float(min_part_mb))))
 note=f'総データ量 {mb:.1f}MB / 1パートあたり最低 {min_part_mb}MB とすると上限 {cap}分割'
 if timing and (timing.get('save') or 0)>0:
  # 転送が短いと、何割縮めても実時間の得が小さい。得が閾値未満なら分割しない。
  if float(timing['save'])<float(min_gain_seconds)*2:
   return 1,note+f' / 転送が {float(timing["save"]):.0f}秒しかなく、分割しても実時間の得が小さい'
 return cap,note

def recommend_split_parts(columns,removable,max_parts=4,trials=None,timing=None,weights=None,settings=None,link=None):
 """効果が最大になるパート数を選ぶ。得にならなければ1（分割しない）を返す。

 判断の軸は3つ。
   ① データ量の内訳  … 固定列の割合が大きいほど分割は効かない
   ② 実測の裏付け    … 測れていない分割数へは進まない。遅かった数以上は選ばない
   ③ データ量の規模  … 小さいデータを細かく割ると、パートごとの固定費で損をする
 """
 st=settings or {}
 rem=len([c for c in columns if c in set(removable)])
 trials=trials or []
 measured={int(t['parts']):float(t['observed_speedup']) for t in trials if t.get('observed_speedup')}
 proven=[n for n,sp in measured.items() if sp>1.0]
 slow=[n for n,sp in measured.items() if sp<=1.0]
 ceiling=min(int(max_parts),max(2,(max(proven) if proven else 1)+1))
 if slow:ceiling=min(ceiling,min(slow)-1)
 vcap,vnote=split_volume_cap(weights,timing,float(st.get('split_min_part_mb',2.0) or 2.0),
                             float(st.get('split_min_gain_seconds',5.0) or 5.0))
 if vcap:ceiling=min(ceiling,max(1,vcap))
 # 回線に空きが無ければ、本数を増やしても合計は伸びない。ここが実際にいちばん効く。
 lcap=split_useful_parts(link)
 if lcap:ceiling=min(ceiling,max(1,lcap))
 best,best_gain=1,1.0;details=[]
 for n in range(1,max(1,int(max_parts))+1):
  if n>1 and rem<n*2:break                      # 1パートあたり2列未満になる分割はしない
  g=predict_split_gain(columns,removable,n,trials,timing,weights,link)
  details.append({'parts':n,'predicted':round(g,3),'transfer_ratio':round(split_transfer_ratio(columns,removable,n,weights),3),
                  'measured':round(measured[n],2) if n in measured else None,'allowed':n<=ceiling})
  # わずかな差では分割しない。実時間での得が小さいときも同じ。
  gain_seconds=(1-g)*float((timing or {}).get('total') or 0)
  worth=g<best_gain-0.10 and (not timing or gain_seconds>=float(st.get('split_min_gain_seconds',5.0) or 5.0))
  if n<=ceiling and worth:best,best_gain=n,g
 return best,round(best_gain,3),details

def merge_column_parts(part_files,dest,key_columns=None,column_order=None,encoding='cp932'):
 """列分割の結果を横に結合する。

 突き合わせに使う列は、全パートに共通して現れる列（＝削除できなかった固定列と錨）を
 パート自身の見出しから求める。位置や事前の想定に頼らないので、RNEを差し替えて列が
 増えていても成立する。食い違いは必ず例外にする。黙って埋めると欠けた列が空値で出てしまう。
 """
 parts=[]
 for pf in part_files:
  with Path(pf).open('r',encoding=encoding,newline='') as f:rows=list(csv.reader(f))
  if not rows:raise ValueError(f'分割結果が空です: {pf}')
  parts.append((Path(pf).name,rows[0],rows[1:]))
 # 同名の列があると、突き合わせにも並べ直しにも列名が使えない。先に弾いて理由を明確にする。
 for name,hdr,_b in parts:
  d=duplicate_columns(hdr)
  if d:raise ValueError(f'{name} に同じ名前の列があります: '+'、'.join(f"{x['name']}×{x['count']}" for x in d[:5]))
 if column_order:
  d=duplicate_columns(column_order)
  if d:raise ValueError('出力に同じ名前の列があるため結合できません: '+'、'.join(f"{x['name']}×{x['count']}" for x in d[:5]))
 common=set(parts[0][1])
 for _n,hdr,_b in parts[1:]:common&=set(hdr)
 keys=[c for c in parts[0][1] if c in common]
 if not keys:raise ValueError('全パートに共通する列がないため、突き合わせられません')
 if key_columns and not set(key_columns)<=common:
  missing=[c for c in key_columns if c not in common]
  log.info('SPLIT_MERGE_KEYS 想定していた固定列のうち %s 件が全パートには無いため、共通列 %s 件で突き合わせます（不足例: %s）',
           len(missing),len(keys),missing[:5])
 order=None;base=None;header=None
 for name,hdr,body in parts:
  ki=[hdr.index(c) for c in keys]
  rest=[i for i in range(len(hdr)) if i not in set(ki)]
  m={tuple(r[i] for i in ki):[r[i] for i in rest] for r in body}
  if len(m)!=len(body):raise ValueError(f'キーが一意ではありません: {name}')
  if base is None:
   order=[tuple(r[i] for i in ki) for r in body];base={k:list(v) for k,v in m.items()}
   header=list(keys)+[hdr[i] for i in rest]
  else:
   if set(m)!=set(base):
    raise SplitRowsetMismatch(f'分割間で行集合が一致しません（1つ目 {len(base)}行 / {name} {len(m)}行）。'
                              'データ項目を外すと返ってくる行が変わる問い合わせのため、列分割は使えません。',
                              first_rows=len(base),other_rows=len(m),part=name)
   # 既に取り込んだ列は足さない（錨の列は全パートに現れるため）
   keep=[j for j,i in enumerate(rest) if hdr[i] not in set(header)]
   header+=[hdr[rest[j]] for j in keep]
   for k in order:base[k]+=[m[k][j] for j in keep]
 merged=[list(k)+base[k] for k in order]
 # 元の列順へ戻す。並びが違うだけで内容が同じでも、比較で不一致になるため必ず復元する。
 if column_order:
  pos={name:i for i,name in enumerate(header)}
  missing=[c for c in column_order if c not in pos]
  if missing:raise ValueError(f'結合後に足りない列があります: {missing[:5]}')
  if len(header)!=len(column_order):
   extra=[c for c in header if c not in set(column_order)]
   raise ValueError(f'結合後の列数が違います: {len(header)} != {len(column_order)}'+(f'（余分: {extra[:5]}）' if extra else ''))
  idx=[pos[c] for c in column_order];header=list(column_order)
  merged=[[r[i] for i in idx] for r in merged]
 dup=[n for n,k in {c:header.count(c) for c in header}.items() if k>1]
 if dup:raise ValueError(f'結合後に同じ名前の列が残っています: {dup[:5]}')
 with Path(dest).open('w',encoding=encoding,newline='') as f:
  w=csv.writer(f,quoting=csv.QUOTE_MINIMAL);w.writerow(header);w.writerows(merged)
 return len(merged),len(header)

def compare_csv_content(a_path,b_path,key_columns,encoding='cp932',samples=5,axis_column=''):
 """2つのCSVを内容で比べる。バイト比較では「どこがどう違うか」が分からないため。

 行の並び順だけの違いと、中身の違いを区別する。生きているデータを別々に問い合わせている以上、
 並び順まで一致する保証は無いので、そこを分けて見ないと判断できない。
 """
 def read(p):
  with Path(p).open('r',encoding=encoding,newline='') as f:
   rows=list(csv.reader(f))
  return (rows[0] if rows else []),rows[1:]
 ha,ra=read(a_path);hb,rb=read(b_path)
 out={'header_match':ha==hb,'rows_a':len(ra),'rows_b':len(rb),'columns_a':len(ha),'columns_b':len(hb)}
 if ha!=hb:
  diff=[i for i,(x,y) in enumerate(zip(ha,hb)) if x!=y]
  out['header_diff']=[{'index':i,'a':ha[i],'b':hb[i]} for i in diff[:samples]]
  out['identical']=False;out['reason']='列の並びまたは名前が違います';return out
 kn=len(key_columns)
 keys=[c for c in key_columns if c in ha]
 if len(keys)!=kn:
  # 想定した固定列が出力に無い場合は、先頭の列で突き合わせる（並び順の判定にのみ使う）
  keys=ha[:1];kn=1
 ki=[ha.index(c) for c in keys]
 out['byte_identical']=Path(a_path).read_bytes()==Path(b_path).read_bytes()
 out['order_match']=[[r[i] for i in ki] for r in ra]==[[r[i] for i in ki] for r in rb]
 ma={tuple(r[i] for i in ki):r for r in ra};mb={tuple(r[i] for i in ki):r for r in rb}
 only_a=set(ma)-set(mb);only_b=set(mb)-set(ma)
 out['only_in_a']=len(only_a);out['only_in_b']=len(only_b)
 # 欠けた行が「どの軸の値」に偏っているかを残す。ひとつの値に集中していれば絞り方の取りこぼし、
 # ばらけていれば実行中にデータが動いただけ、と切り分けられる。
 if only_a and axis_column and axis_column in ha:
  ai=ha.index(axis_column)
  tally={}
  for k in only_a:
   v=ma[k][ai] if ai<len(ma[k]) else ''
   tally[v]=tally.get(v,0)+1
  top=sorted(tally.items(),key=lambda x:-x[1])
  blank=sum(n for v,n in tally.items() if str(v).strip()=='')
  out['missing_axis']={'column':axis_column,'distinct':len(tally),
                       'top':[{'value':v,'rows':n} for v,n in top[:8]],
                       'blank_rows':blank,'all_blank':bool(blank and blank==len(only_a)),
                       'concentrated':bool(top and top[0][1]>=len(only_a)*0.8)}
 diff_rows=[];diff_cells=0;changed=0
 for k in ma:
  if k in only_a:continue
  x,y=ma[k],mb[k]
  if x==y:continue
  changed+=1
  cols=[i for i in range(min(len(x),len(y))) if x[i]!=y[i]]
  diff_cells+=len(cols)
  if len(diff_rows)<samples:
   diff_rows.append({'key':list(k),'columns':[{'name':ha[i],'a':x[i],'b':y[i]} for i in cols[:samples]]})
 out['diff_rows']=changed;out['diff_cells']=diff_cells;out['samples']=diff_rows
 # 行数そのものも見る。突き合わせは固定列の値をキーにした辞書で行うため、同じ行が
 # 何度も入っていても片方に潰れてしまう。行の条件が効かず全パートが全件を返したとき、
 # 2倍3倍に膨れた結合結果を「内容は一致」と報告していた（2026-08-10の実測で発覚）。
 out['count_match']=(len(ra)==len(rb))
 out['duplicated_rows']=max(0,len(rb)-len(ra))
 same=not only_a and not only_b and diff_cells==0 and out['count_match']
 out['content_identical']=same
 out['identical']=bool(out.get('byte_identical'))
 out['reason']=('完全に一致' if out['identical'] else
                ('行の並び順だけが違います（内容は一致）' if same else
                 f'行数が違います（分割なし {len(ra)}行 に対し 結合 {len(rb)}行。'
                 f'同じ行が {len(rb)/len(ra):.2f}倍 に増えています）' if not out['count_match'] and len(ra) else
                 f'{changed}行の中身が違います（{diff_cells}セル）' if diff_cells else
                 f'行の過不足があります（分割なしのみ {len(only_a)}行 / 結合のみ {len(only_b)}行）'))
 return out

def record_split_trial(rne_path,job,parts,rows,cols,normal_elapsed,split_elapsed,identical,detail='',metrics=None):
 """分割と未分割の実測を残す。パート数の判断を経験で補正するための材料。"""
 speedup=(normal_elapsed/split_elapsed) if split_elapsed and normal_elapsed else None
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('INSERT INTO split_trials(rne_key,rne_path,job_id,job_name,parts,rows,cols,normal_elapsed,split_elapsed,observed_speedup,identical,detail,metrics,tried_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
             (_rne_key(rne_path),str(rne_path),str((job or {}).get('id') or ''),str((job or {}).get('name') or ''),int(parts),rows,cols,
              normal_elapsed,split_elapsed,speedup,1 if identical else 0,detail,json.dumps(metrics or {},ensure_ascii=False),
              datetime.now().isoformat(timespec='seconds')))
   _mark_settings_dirty()
 except Exception:
  log.exception('SPLIT_TRIAL_RECORD_FAILED rne=%s',rne_path);return None
 log.info('SPLIT_TRIAL rne=%s parts=%s rows=%s cols=%s normal=%.2fs split=%.2fs speedup=%s identical=%s',
          rne_path,parts,rows,cols,normal_elapsed or 0,split_elapsed or 0,f'{speedup:.2f}' if speedup else '-',identical)
 return speedup

def save_rne_timing(rne_path,execute_seconds,save_seconds,total_seconds,rows=None,cols=None):
 """1回の実行の内訳を残す。分割で縮むのは転送(保存)の部分だけなので、その比率が判断の要になる。"""
 if not (execute_seconds or save_seconds):return
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('INSERT OR REPLACE INTO rne_timing(rne_key,rne_path,execute_seconds,save_seconds,total_seconds,rows,cols,measured_at) VALUES(?,?,?,?,?,?,?,?)',
             (_rne_key(rne_path),str(rne_path),execute_seconds,save_seconds,total_seconds,rows,cols,datetime.now().isoformat(timespec='seconds')))
   _mark_settings_dirty()
 except Exception:
  log.exception('RNE_TIMING_SAVE_FAILED rne=%s',rne_path);return
 log.info('RNE_TIMING rne=%s execute=%.2fs save=%.2fs total=%.2fs',rne_path,execute_seconds or 0,save_seconds or 0,total_seconds or 0)

def load_rne_timing(rne_path):
 try:
  with settings_connection() as c:
   r=c.execute('SELECT * FROM rne_timing WHERE rne_key=?',(_rne_key(rne_path),)).fetchone()
 except Exception:
  return None
 if not r:return None
 return {'execute':r['execute_seconds'] or 0,'save':r['save_seconds'] or 0,'total':r['total_seconds'] or 0,
         'rows':r['rows'],'cols':r['cols'],'measured_at':r['measured_at']}

def split_link_profile(rne_path=None):
 """回線の様子を実測から求める。分割が効くかどうかは、ここでほぼ決まる。

 1本で出せる速度が回線の上限に近いと、本数を増やしても合計は伸びない（分割しても損）。
 逆に1本では上限まで使い切れていないとき（遅延律速）だけ、並列にする意味がある。
   capacity_kbs … これまでに観測した合計スループットの最大値。回線の上限とみなす。
   base_kbs     … 直近の「分割なし」1本の速度
   headroom     … capacity ÷ base。何本ぶんの余地があるか。σ(n) ≒ min(n, headroom)
 """
 try:
  with settings_connection() as c:
   q="SELECT parts,metrics,tried_at FROM split_trials WHERE metrics<>''"
   rows=list(c.execute(q+' AND rne_key=? ORDER BY id',(_rne_key(rne_path),))) if rne_path else list(c.execute(q+' ORDER BY id'))
 except Exception:
  return {'samples':0,'capacity_kbs':None,'base_kbs':None,'headroom':None,'points':[]}
 pts=[];cap=0.0;base=None;at=''
 for r in rows:
  try:m=json.loads(r['metrics'] or '{}')
  except Exception:continue
  # 競争中の値は使えない。単一速度が奪い合いで沈む一方、上限は過去の最大が残るため、
  # 伸びしろが跳ね上がる（実測値で試すと 1.44倍 → 2.56倍）。分割しすぎる方向へ狂う。
  if m.get('race'):continue
  nb,ns=m.get('normal_bytes'),m.get('normal_save');parts=m.get('parts') or []
  if not (nb and ns and parts):continue
  b=nb/1024/ns
  slowest=max((p.get('save') or 0) for p in parts)
  if slowest<=0:continue
  agg=sum((p.get('bytes') or 0) for p in parts)/1024/slowest
  cap=max(cap,agg,b);base=b;at=r['tried_at']
  pts.append({'parts':int(r['parts']),'base_kbs':round(b),'aggregate_kbs':round(agg),'sigma':round(agg/b,2)})
 if not pts:return {'samples':0,'capacity_kbs':None,'base_kbs':None,'headroom':None,'points':[]}
 return {'samples':len(pts),'capacity_kbs':round(cap),'base_kbs':round(base),'measured_at':at,
         'headroom':round(cap/base,2) if base else None,'points':pts}

def split_useful_parts(link):
 """回線の空きから見た、意味のある分割数の上限。余地が無ければ1（分割しない）。"""
 h=(link or {}).get('headroom')
 if not h:return None
 # 切り捨てない。伸びしろ1.8倍は「2本目がほぼ丸ごと効く」という意味で、分割する価値がある。
 # 逆に1.3倍なら2本目は3割しか効かず、各パートが運ぶ量を上回れないので1本のままにする。
 return max(1,int(round(float(h))))


def split_breakeven_share(slope):
 """分割が転送で得になる「固定列の割合」の上限。

 σ(n)=1+k(n-1) と見ると、得になる条件は f < k。k は回線の空き（headroom-1）に相当する。
 """
 if not slope or slope<=0:return None
 return round(min(1.0,max(0.0,slope)),3)

def split_incompatible(rne_path):
 """このRNEは列分割に向かないと確定しているか（行集合が食い違った実績があるか）。"""
 try:
  with settings_connection() as c:
   r=c.execute("SELECT COUNT(*) n FROM split_trials WHERE rne_key=? AND identical=0 AND detail LIKE 'rowset%'",(_rne_key(rne_path),)).fetchone()
  return bool(r and r['n'])
 except Exception:
  return False

def load_split_trials(rne_path=None):
 """記録済みの実測。パート数ごとに、一致した試行の平均速度比を返す。

 競争させた回（detail が 'race:' で始まる）は除く。奪い合いは分割なしの側をより強く痛めるため
 （運ぶ量が多いぶん、細った帯域の影響を大きく受ける）、速度比はかえって高く出る。
 実測では 単独1.11倍 に対し 競争1.29倍。混ぜると分割を実際より有利に見せてしまう。
 """
 try:
  with settings_connection() as c:
   q=("SELECT parts,observed_speedup FROM split_trials WHERE identical=1 AND observed_speedup IS NOT NULL"
      " AND detail NOT LIKE 'race:%' AND detail NOT LIKE 'row:%' AND detail NOT LIKE 'grid:%'")
   rows=list(c.execute(q+' AND rne_key=?',(_rne_key(rne_path),))) if rne_path else list(c.execute(q))
 except Exception:
  return []
 agg={}
 for r in rows:agg.setdefault(int(r['parts']),[]).append(float(r['observed_speedup']))
 return [{'parts':k,'observed_speedup':sum(v)/len(v),'samples':len(v)} for k,v in sorted(agg.items())]

# ---- 実運用での分割（確定した割り当てを保存して使い回す） --------------------
# 実行のたびに列の重みを測り直すと、それだけで数秒かかる（11MBで約3秒）。分割で稼げるのが
# 数秒なのだから、そこで使い切ってしまう。そこで、影実行で「一致した・速かった」と確認できた
# 割り当てだけを保存し、実行時はそれを読むだけにする。測り直しは影実行の側の仕事にする。

SPLIT_MODES=('auto','force','race','off')
# 分け方（どう切るか）。動作（SPLIT_MODES＝いつ使うか）とは別の軸。
# 'auto' は「影実行で実測した中でいちばん速かった形」を意味する。利用者に形を選ばせない。
SPLIT_SHAPES=('auto','column','row','grid')
SPLIT_SHAPE_LABEL={'auto':'自動（実測で速かった形）','column':'列分割','row':'行分割','grid':'行×列'}

def normalize_split_mode(value):
 v=str(value or '').strip().lower()
 return v if v in SPLIT_MODES else 'auto'

def normalize_split_shape(value):
 v=str(value or '').strip().lower()
 return v if v in SPLIT_SHAPES else 'auto'

def split_shape_label(shape,pieces=0,row_parts=0):
 """保存済みの割り当てを1語で表す。画面にもログにも同じことばを使う。

 pieces は「実際に走らせる片の数」。行×列では 行数×列数 なので、列の数はここから割り戻す。
 保存も判断もこの片数を単位にしているため、表示だけ別の数を持ち回らない。
 """
 shape=normalize_split_shape(shape)
 pieces=int(pieces or 0);row_parts=int(row_parts or 0)
 if shape=='row':return f'行{row_parts or pieces}分割'
 if shape=='grid':
  cols=max(1,pieces//row_parts) if row_parts else pieces
  return f'行{row_parts}×列{cols}（{pieces}片）'
 return f'列{pieces}分割'

def save_split_plan(rne_path,columns,parts,plan,keys,anchors,speedup=None,rows=None,cols=None,source='trial',mode='column',row=None):
 """影実行で裏付けの取れた割り当てを保存する。次からの実行はこれを読むだけで済む。

 行分割・行×列では、値の一覧そのものは保存しない。カテゴリは日々増減するので
 （実測 1746種 → 1754種）、保存した値で分けると新しい値の行が落ちる。保存するのは
 「どの軸で何分割するか」だけで、値の割り当ては実行の直前に読み直して作る。
 """
 key=_rne_key(rne_path);mtime,size=rne_signature(rne_path);now=datetime.now().isoformat(timespec='seconds')
 body=[{'index':p['index'],'keep':list(p.get('keep') or []),'drop':list(p.get('drop') or [])} for p in plan]
 mode=normalize_split_shape(mode)
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute('INSERT OR REPLACE INTO split_plans(rne_key,mode,parts,rne_path,rne_mtime_ns,rne_size,columns_json,plan_json,keys_json,anchors_json,row_json,observed_speedup,rows,cols,source,proven_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
             (key,mode,int(parts),str(rne_path),mtime,size,json.dumps(list(columns),ensure_ascii=False),
              json.dumps(body,ensure_ascii=False),json.dumps(list(keys),ensure_ascii=False),
              json.dumps(list(anchors or []),ensure_ascii=False),
              json.dumps(row or {},ensure_ascii=False),
              float(speedup) if speedup else None,rows,cols,source,now))
   _mark_settings_dirty()
 except Exception:
  log.exception('SPLIT_PLAN_SAVE_FAILED rne=%s mode=%s parts=%s',rne_path,mode,parts);return False
 log.info('SPLIT_PLAN_SAVE rne=%s mode=%s parts=%s columns=%s keys=%s anchors=%s 軸=%s speedup=%s',
          rne_path,mode,parts,len(columns),len(keys),anchors or '(なし)',
          (row or {}).get('axis_name') or '-',f'{speedup:.2f}' if speedup else '-')
 return True

def load_split_plans(rne_path):
 """保存済みの割り当て。RNEが更新されていれば stale を付けて返す（採用しない）。"""
 try:
  with settings_connection() as c:
   rows=list(c.execute('SELECT * FROM split_plans WHERE rne_key=? ORDER BY mode,parts',(_rne_key(rne_path),)))
 except Exception:
  return []
 mtime,size=rne_signature(rne_path);out=[]
 for r in rows:
  try:
   body=json.loads(r['plan_json']);cols=json.loads(r['columns_json']);keys=json.loads(r['keys_json'])
  except Exception:
   continue
  try:rowspec=json.loads((r['row_json'] if 'row_json' in r.keys() else '') or '{}')
  except Exception:rowspec={}
  out.append({'parts':int(r['parts']),'plan':body,'columns':cols,'keys':keys,
              'mode':normalize_split_shape(r['mode'] if 'mode' in r.keys() else 'column'),'row':rowspec,
              'anchors':json.loads(r['anchors_json'] or '[]'),'observed_speedup':r['observed_speedup'],
              'rows':r['rows'],'cols':r['cols'],'source':r['source'],'proven_at':r['proven_at'],
              'stale':bool(mtime) and (mtime!=r['rne_mtime_ns'] or size!=r['rne_size'])})
 return out

def drop_split_plans(rne_path,reason=''):
 """割り当てを取り下げる。実行で失敗した割り当てを次も使わないための後始末。"""
 try:
  with settings_sync_lock, settings_connection() as c:
   n=c.execute('DELETE FROM split_plans WHERE rne_key=?',(_rne_key(rne_path),)).rowcount;_mark_settings_dirty()
 except Exception:
  log.exception('SPLIT_PLAN_DROP_FAILED rne=%s',rne_path);return 0
 if n:log.warning('SPLIT_PLAN_DROP rne=%s removed=%s reason=%s',rne_path,n,reason)
 return n

_HOST_NAME=''
def host_name():
 """このPCの名前。同じRNEでも端末が違えば速さが違うので、実績に添える。"""
 global _HOST_NAME
 if not _HOST_NAME:
  try:_HOST_NAME=os.environ.get('COMPUTERNAME') or socket.gethostname() or '-'
  except Exception:_HOST_NAME='-'
 return _HOST_NAME

def record_rne_run(rne_path,job,status_value,trigger,metrics,engine='api',fmt=''):
 """1回の実行を、RNE単位の実績として残す。あとから条件別に見比べるために使う。

 job_runs は「対象ごとの最新1件」、run_history は「実施したかどうか」。
 どちらも速さの分析には足りない。ここには時間帯・端末・分け方・内訳まで残す。
 """
 if not rne_path:return False
 init_settings_db()
 m=dict(metrics or {})
 now=datetime.now()
 try:
  with settings_sync_lock, settings_connection() as c:
   c.execute("""INSERT INTO rne_runs(rne_key,rne_path,job_id,job_name,finished_at,hour,weekday,status,trigger,engine,
                shape,how,parts,row_axis,rows,cols,elapsed,execute_seconds,save_seconds,merge_seconds,axis_seconds,
                transfer_bytes,transfer_kbs,lines,host,cpu,format)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (_rne_key(rne_path),str(rne_path),str((job or {}).get('id') or ''),str((job or {}).get('name') or ''),
              now.isoformat(timespec='seconds'),now.hour,now.weekday(),str(status_value),str(trigger or ''),str(engine or ''),
              str(m.get('split_shape') or ''),str(m.get('split_how') or ''),int(m.get('split_parts') or 0),
              str(m.get('row_axis') or ''),m.get('rows'),m.get('cols'),m.get('elapsed'),
              m.get('execute_seconds'),m.get('save_seconds'),m.get('merge_seconds'),m.get('axis_seconds'),
              m.get('transfer_bytes'),m.get('transfer_kbs'),int(m.get('lines') or 0),
              host_name(),int(os.cpu_count() or 0),str(m.get('format') or fmt or '')))
   # 分析に要るのは傾向で、全履歴ではない。RNEごとに直近2000件へ抑える。
   c.execute('DELETE FROM rne_runs WHERE rne_key=? AND id NOT IN (SELECT id FROM rne_runs WHERE rne_key=? ORDER BY id DESC LIMIT 2000)',
             (_rne_key(rne_path),_rne_key(rne_path)))
   _mark_settings_dirty()
 except Exception:
  log.exception('RNE_RUN_RECORD_FAILED rne=%s',rne_path);return False
 return True

def rne_run_stats(rne_path,limit=400):
 """RNE単位の実績を、条件別にまとめる。どの条件が速いのかを数字で示すためのもの。"""
 init_settings_db()
 try:
  with settings_connection() as c:
   rows=[dict(r) for r in c.execute(
     'SELECT * FROM rne_runs WHERE rne_key=? ORDER BY id DESC LIMIT ?',(_rne_key(rne_path),int(limit)))]
 except Exception:
  return {'runs':[],'total':0,'groups':{}}
 ok=[r for r in rows if r.get('status')=='ok' and (r.get('elapsed') or 0)>0]
 def group(key,label):
  g={}
  for r in ok:
   k=str(r.get(key) or '')
   if key=='hour':k='%02d時台'%int(r.get('hour') or 0)
   if not k:k='（記録なし）'
   g.setdefault(k,[]).append(float(r['elapsed']))
  out=[{'key':k,'runs':len(v),'avg':round(sum(v)/len(v),1),'min':round(min(v),1),'max':round(max(v),1)}
       for k,v in g.items()]
  out.sort(key=lambda x:x['avg'])
  return {'label':label,'items':out}
 return {'total':len(rows),'ok':len(ok),
         'runs':[{k:r.get(k) for k in ('finished_at','status','trigger','how','shape','parts','row_axis',
                                       'rows','cols','elapsed','execute_seconds','save_seconds','merge_seconds',
                                       'axis_seconds','transfer_bytes','transfer_kbs','host','cpu','format','engine')}
                 for r in rows[:60]],
         'groups':{'how':group('how','分け方'),'hour':group('hour','時間帯'),
                   'host':group('host','PC'),'trigger':group('trigger','きっかけ'),
                   'format':group('format','出力形式')}}

def rne_master_view(job,cfg):
 """このRNEについて控えてあるもの一式。画面はこれ1本を見れば足りる。

 調べ直すかどうかの判断に要るのは1つだけ ―― 控えを取った時のファイルと、いまのファイルが
 同じかどうか。RNEの更新日時と大きさで見る。同じなら調べ直す必要はない。
 """
 rp=resolve_rne_path(job,cfg)
 mtime,size=rne_signature(rp)
 exists=Path(rp).is_file()
 cached=load_column_cache(rp) or {}
 survey=read_axis_survey_raw(rp) or {}
 timing=load_rne_timing(rp) or {}
 plans=load_split_plans(rp)
 blocks=blocked_row_axes(rp)
 axes=survey.get('axes') or []
 # 「同じファイルか」は控えごとに持っている指紋で判定する。片方だけ古いこともある。
 col_fresh=bool(cached) and not cached.get('stale')
 axis_fresh=bool(axes) and str(survey.get('rne_mtime_ns') or '')==str(mtime) and int(survey.get('rne_size') or 0)==int(size or 0)
 have=bool(cached.get('columns')) and bool(axes)
 if not exists:state,why='missing','RNEファイルが見つかりません'
 elif not have:state,why='none','まだ調査していません'
 elif col_fresh and axis_fresh:state,why='fresh','調査したときと同じファイルです。調べ直す必要はありません'
 else:state,why='stale','RNEが更新されています。調べ直してください'
 return {'rne':str(rp),'exists':exists,'state':state,'why':why,
         'file':{'mtime_ns':mtime,'size':size,
                 'modified':(datetime.fromtimestamp(Path(rp).stat().st_mtime).isoformat(timespec='seconds') if exists else '')},
         'columns':{'have':bool(cached.get('columns')),'count':len(cached.get('columns') or []),
                    'removable':len([x for x in (cached.get('classify') or []) if x.get('removable')]),
                    'fixed':len([x for x in (cached.get('classify') or []) if not x.get('removable')]),
                    'condition':len(cached.get('condition') or []),
                    'captured_at':cached.get('captured_at',''),'fresh':col_fresh,'source':cached.get('source',''),
                    # 索引に使う列を選ぶための候補。打ち間違いを減らす。
                    'list':[str(x) for x in (cached.get('columns') or [])][:400]},
         'axes':{'have':bool(axes),'count':len(axes),
                 'usable':len([a for a in axes if axis_usable(a,2)[0]]),
                 # 使える軸の一覧そのものを返す。控えがあるのに画面が
                 # 「先に『RNEを調査』」と出すのは、ここを渡していなかったため。
                 'list':[{'name':a.get('name',''),'location':a.get('location',''),
                          'index':a.get('index',0),'type_name':a.get('type_name',''),
                          'is_time':bool(a.get('is_time')),
                          'category_count':a.get('category_count'),
                          'usable':bool(axis_usable(a,2)[0]),'enough':bool(a.get('enough',True))}
                         for a in axes if axis_usable(a,2)[0]][:200],
                 'captured_at':survey.get('taken_at',''),'fresh':axis_fresh,
                 'blocked':[{'name':k,'reason':v.get('reason',''),'values':v.get('values'),'at':v.get('at','')}
                            for k,v in blocks.items()]},
         'timing':{'have':bool(timing),'total':timing.get('total'),'execute':timing.get('execute'),
                   'save':timing.get('save'),'rows':timing.get('rows'),'cols':timing.get('cols'),
                   'measured_at':timing.get('measured_at','')},
         'plans':[split_plan_view(x) for x in sorted(plans,key=lambda x:-(x['observed_speedup'] or 0))]}

def split_plan_view(p,chosen=None):
 """保存済みの割り当て1件を、そのまま画面へ出せる形にする。

 画面とログで同じことばを使う。「列3分割」「行2分割」「行2×列3」の3通りしかない。
 """
 row=p.get('row') or {}
 return {'shape':p['mode'],'how':split_shape_label(p['mode'],p['parts'],row.get('parts',0)),
         'pieces':p['parts'],'speedup':p['observed_speedup'],'raw_speedup':row.get('raw_speedup'),
         'axis':row.get('axis_name',''),'axis_seconds':row.get('axis_seconds'),
         'row_parts':row.get('parts',0),'skew':row.get('skew'),
         'proven_at':p['proven_at'],'stale':p['stale'],'columns':len(p['columns']),'source':p.get('source',''),
         'rows':p.get('rows'),'cols':p.get('cols'),
         'chosen':bool(chosen and chosen.get('mode')==p['mode'] and chosen.get('parts')==p['parts'])}

def runtime_split_view(rne_path,job,cfg,chosen,why,budget):
 """「次に実行したらどうなるか」を1か所にまとめる。画面はこれをそのまま並べるだけ。

 判断に要るのは3つだけ。何を使うか／なぜそれか／ほかに何が確認済みか。
 """
 plans=load_split_plans(rne_path)
 row=(chosen or {}).get('row') or {}
 return {'mode':normalize_split_mode(job.get('split_mode')),'shape':normalize_split_shape(job.get('split_shape')),
         'budget':int(budget),'active':bool(chosen),'reason':why,
         'shape_used':(chosen or {}).get('mode',''),
         'how':split_shape_label(chosen['mode'],chosen['parts'],row.get('parts',0)) if chosen else '',
         'pieces':(chosen or {}).get('parts',0),'parts':(chosen or {}).get('parts',0),
         'axis':row.get('axis_name',''),'axis_seconds':row.get('axis_seconds'),
         'proven_at':(chosen or {}).get('proven_at',''),'observed_speedup':(chosen or {}).get('observed_speedup'),
         'saved':[split_plan_view(p,chosen) for p in sorted(plans,key=lambda x:-(x['observed_speedup'] or 0))],
         'shapes':[{'id':k,'label':v} for k,v in SPLIT_SHAPE_LABEL.items()],
         'min_speedup':float((cfg.get('settings') or {}).get('split_min_speedup',1.05) or 1.05)}

def pick_split_plan(rne_path,columns,max_parts,min_speedup=None,shape='auto'):
 """使える割り当てを1つ選ぶ。無ければ (None, 理由)。

 どの割り当ても「結果が分割なしと一致した」ことは保存の時点で確認済み。
 min_speedup を渡すと、そのうえで実際に速かったものだけに絞る。
 競争させる使い方では速さの裏付けは要らない（遅ければ競争に負けて捨てられるだけ）ので、
 一致さえしていれば使う。
 shape を指定すると、その分け方の中から選ぶ。'auto' は分け方を問わず、いちばん速かったもの。
 """
 shape=normalize_split_shape(shape)
 plans=load_split_plans(rne_path)
 if not plans:return None,'確認済みの割り当てがありません（影実行で結果の一致を確認すると保存されます）'
 fresh=[p for p in plans if not p['stale']]
 if not fresh:return None,'RNEが更新されたため、保存済みの割り当ては使えません'
 same=[p for p in fresh if list(p['columns'])==list(columns or [])]
 if not same:return None,f'列の顔ぶれが当時と違います（保存時 {len(fresh[0]["columns"])}列 / 現在 {len(columns or [])}列）'
 if shape!='auto':
  want=[p for p in same if p['mode']==shape]
  if not want:
   have='、'.join(sorted({split_shape_label(p['mode'],p['parts'],(p.get('row') or {}).get('parts',0)) for p in same}))
   return None,f'「{SPLIT_SHAPE_LABEL[shape]}」の裏付けがありません（確認済みなのは {have}）'
  same=want
 fits=[p for p in same if p['parts']<=max(1,int(max_parts))]
 if not fits:return None,f'保存済みは{min(p["parts"] for p in same)}片以上ですが、使えるラインは{max_parts}本です'
 if min_speedup is not None:
  fast=[p for p in fits if (p['observed_speedup'] or 0)>=float(min_speedup)]
  if not fast:
   got=max((p['observed_speedup'] or 0) for p in fits)
   return None,f'保存済みの割り当ては速さの基準に届いていません（実測 {got:.2f}倍 / 基準 {float(min_speedup):.2f}倍）'
  fits=fast
 best=max(fits,key=lambda p:(p['observed_speedup'] or 0,p['parts']))
 return best,''

def last_run_info(run):
 if not run:return {'last_run':None,'last_status':'','last_trigger':'','last_output':'','last_metrics':{}}
 trig=str(run.get('trigger') or '');kind='schedule' if trig.startswith('schedule') else 'manual'
 m=dict(run.get('metrics') or {})
 if run.get('rows') is not None:m.setdefault('rows',run.get('rows'))
 if run.get('cols') is not None:m.setdefault('cols',run.get('cols'))
 return {'last_run':run.get('finished_at'),'last_status':run.get('status') or '','last_trigger':kind,'last_output':run.get('output_file') or '','last_detail':run.get('detail') or '','last_metrics':m}

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
   fmt=normalize_output_format(r['output_format'],r['output_file']); jobs.append({'id':r['id'],'enabled':bool(r['enabled']),'name':r['name'],'rne':r['rne'],'rne_path':r['rne_path'],'output_folder':r['output_folder'],'output_format':fmt,'output_file':canonical_output_file(r['output_file'],fmt),'table':r['table_name'],'sheet':r['sheet_name'],'type':r['read_type'],'naming_mode':(r['naming_mode'] if 'naming_mode' in r.keys() else 'fixed'),'output_pattern':(r['output_pattern'] if 'output_pattern' in r.keys() else ''),'comment':(r['comment'] if 'comment' in r.keys() else ''),'split_mode':normalize_split_mode(r['split_mode'] if 'split_mode' in r.keys() else ''),'split_shape':normalize_split_shape(r['split_shape'] if 'split_shape' in r.keys() else ''),'row_axis_mode':normalize_row_axis_mode(r['row_axis_mode'] if 'row_axis_mode' in r.keys() else ''),'row_axis_index':int((r['row_axis_index'] if 'row_axis_index' in r.keys() else 1) or 1),'row_axis_name':str((r['row_axis_name'] if 'row_axis_name' in r.keys() else '') or ''),'extra_formats':job_extra_formats({'output_format':fmt,'output_file':r['output_file'],'extra_formats':(r['extra_formats'] if 'extra_formats' in r.keys() else '')}),'index_columns':_json_list(r['index_columns'] if 'index_columns' in r.keys() else ''),'skip_if_unchanged':bool(r['skip_if_unchanged'] if 'skip_if_unchanged' in r.keys() else 0),'period':_decode_period(r['period_json'] if 'period_json' in r.keys() else ''),'schedules':rules})
  cfg['jobs']=jobs; cfg.setdefault('settings',{}); cfg['settings'].setdefault('extract_engine','api'); cfg['settings'].setdefault('api_parallel_max_lines',PARALLEL_LINES_SUPPORTED_MAX); cfg['settings'].setdefault('api_parallel_model','process')
  # 既定の並列ラインは6。旧テスト実装では stability_profile='stable_api_serial' の環境で読込のたびに api_parallel_lines を1へ強制していた（毎回1ラインへ戻る不具合の原因）。
  # その名残マーカーが残る環境（または初期状態）だけ一度2へ引き上げ、以降はユーザーが保存した値をそのまま尊重する。
  _prev_profile=cfg['settings'].get('stability_profile')
  if _prev_profile in (None,'stable_api_serial'):
   cfg['settings']['api_parallel_lines']=6; cfg['settings']['stability_profile']='balanced_api_parallel'
  cfg['settings'].setdefault('api_parallel_lines',6); cfg['settings'].setdefault('stability_profile','balanced_api_parallel'); cfg['settings'].setdefault('backup_enabled',True); _backup_mode_missing='backup_mode' not in cfg['settings']; cfg['settings'].setdefault('backup_mode','generations'); cfg['settings'].setdefault('backup_retention_days',30); cfg['settings'].setdefault('backup_generation_limit_enabled',True); cfg['settings'].setdefault('backup_generations',3); cfg['settings'].setdefault('schedule_catchup_minutes',30); cfg['settings'].setdefault('api_worker_stagger_ms',700); cfg['settings'].setdefault('split_trial_timeout_seconds',1800); cfg['settings'].setdefault('split_anchor_limit',3); cfg['settings'].setdefault('split_min_part_mb',2.0); cfg['settings'].setdefault('split_min_gain_seconds',5.0); cfg['settings'].setdefault('split_min_speedup',1.05); cfg['settings'].setdefault('split_run_enabled',True); cfg['settings'].setdefault('retry_enabled',True); cfg['settings'].setdefault('retry_max',1); cfg['settings'].setdefault('retry_delay_minutes',5); cfg['settings'].setdefault('log_max_mb',10); cfg['settings'].setdefault('log_keep',5)
  if _backup_mode_missing:cfg['settings']['backup_generations']=3
  if int(cfg['settings'].get('api_parallel_lines',6) or 6)==2:cfg['settings']['api_parallel_lines']=6
  cfg.setdefault('navigator_api_dll',r'.\Config\NAVIAP\debugdllVC14x64\SymNaviA.dll'); cfg.setdefault('accdb_template','.\\assets\\empty.accdb');
  # DLLを探す範囲。別のPCへ移すとNAVIAPの置き場所が変わることがあるため、範囲そのものを設定にする。
  if not isinstance(cfg.get('navigator_api_search_roots'),list) or not cfg.get('navigator_api_search_roots'):
   cfg['navigator_api_search_roots']=list(DEFAULT_DLL_SEARCH_ROOTS)
  try:cfg['navigator_api_search_depth']=max(1,min(6,int(cfg.get('navigator_api_search_depth',3) or 3)))
  except (TypeError,ValueError):cfg['navigator_api_search_depth']=3
 # バックアップ先はPCごとに変わる場所。絶対パスで持つと別のPCで他人のフォルダーを
 # 指してしまうので、<PC> の印で持つ（実測 2026-08-11 の WinError 5 はこれが原因）。
 bf=str(cfg.get('backup_folder') or '').strip()
 if bf.lower() in ('','.\\backup','backup','.\\config\\backup') or _looks_generated_backup(bf):
  cfg['backup_folder']=pc_path('backup')
 else:
  foreign=foreign_profile_path(bf)
  if foreign:
   log.warning('PATH_FOREIGN_PROFILE key=backup_folder value=%s profile=%s → %s へ読み替えます',
               bf,foreign,pc_path('backup'))
   cfg['backup_folder']=pc_path('backup')
 return cfg

def _save_local(v):
 init_settings_db(); now=datetime.now().isoformat(timespec='seconds'); jobs=v.get('jobs',[]); top={k:x for k,x in v.items() if k not in ('jobs','credential_status')}
 with settings_connection() as c:
  c.execute('BEGIN IMMEDIATE'); c.execute('DELETE FROM app_settings')
  for key,value in top.items():
   encoded,kind=_encode_setting(value); c.execute('INSERT INTO app_settings VALUES(?,?,?,?)',(key,encoded,kind,now))
  keep=[]
  for order,j in enumerate(jobs):
   jid=j.get('id') or str(uuid.uuid4()); keep.append(jid)
   fmt=normalize_output_format(j.get('output_format'),j.get('output_file')); output_file=canonical_output_file(j.get('output_file'),fmt); log.info('設定保存 job=%s requested_format=%s saved_format=%s requested_file=%s saved_file=%s',j.get('name'),j.get('output_format'),fmt,j.get('output_file'),output_file); c.execute('INSERT OR REPLACE INTO jobs (id,display_order,enabled,name,rne,rne_path,output_folder,output_format,output_file,table_name,sheet_name,read_type,naming_mode,output_pattern,comment,split_mode,split_shape,row_axis_mode,row_axis_index,row_axis_name,extra_formats,index_columns,skip_if_unchanged,period_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,order,int(bool(j.get('enabled',True))),j.get('name',''),j.get('rne',''),j.get('rne_path',''),j.get('output_folder',''),fmt,output_file,j.get('table','仕掛'),j.get('sheet','Page1'),j.get('type','詳細データ'),str(j.get('naming_mode') or 'fixed'),str(j.get('output_pattern') or ''),str(j.get('comment') or ''),normalize_split_mode(j.get('split_mode')),normalize_split_shape(j.get('split_shape')),normalize_row_axis_mode(j.get('row_axis_mode')),max(1,min(200,int(j.get('row_axis_index') or 1))),str(j.get('row_axis_name') or ''),json.dumps(job_extra_formats({**j,'output_format':fmt}),ensure_ascii=False),json.dumps([str(x).strip() for x in (j.get('index_columns') or []) if str(x).strip()][:4],ensure_ascii=False),int(bool(j.get('skip_if_unchanged'))),json.dumps(_decode_period(json.dumps(j.get('period') or {},ensure_ascii=False)),ensure_ascii=False),now))
   c.execute('DELETE FROM schedules WHERE job_id=?',(jid,))
   for ro,q in enumerate(j.get('schedules',[])):
    c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(q.get('id') or str(uuid.uuid4()),jid,ro,int(bool(q.get('enabled',True))),q.get('name','実行ルール'),q.get('type','daily'),q.get('time','06:00'),q.get('interval_minutes'),json.dumps(q.get('weekdays'),ensure_ascii=False) if 'weekdays' in q else None,json.dumps(q.get('month_days'),ensure_ascii=False) if 'month_days' in q else None,json.dumps(q.get('dates'),ensure_ascii=False) if 'dates' in q else None,now))
  if keep:c.execute('DELETE FROM jobs WHERE id NOT IN ('+','.join('?' for _ in keep)+')',keep);c.execute('DELETE FROM job_runs WHERE job_id NOT IN ('+','.join('?' for _ in keep)+')',keep)
  else:c.execute('DELETE FROM jobs');c.execute('DELETE FROM job_runs')

def save(v):
 # ローカル作業DBへ保存し、設定変更時のみBOX上マスターへバックグラウンドで書き戻す。
 with settings_sync_lock:
  _save_local(v)
 _mark_settings_dirty(); flush_local_to_master_async('config-save')

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
 with settings_sync_lock, settings_connection() as c:c.execute('INSERT OR REPLACE INTO scheduler_state VALUES(?,?,?)',(key,value,datetime.now().isoformat(timespec='seconds')))
 _mark_settings_dirty()

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


# PCごとに実体が変わる場所（<PC> の読み替え・他人のプロファイル検出）は navi_paths.py。
import navi_paths
navi_paths.setup(BASE,LOCAL_ROOT)
from navi_paths import PC_TOKEN,pc_path,is_pc_path,foreign_profile_path,resolve_path,_split_any,_profile_root,_looks_generated_backup


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
 """Use the per-user local work folder for all temporary extraction files."""
 candidates=[LOCAL_ROOT/'work',Path(tempfile.gettempdir())/'SymfoNaviDataHub'/'work',Path('C:/SymfoNaviDataHubWork')]
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
 """DDE接続の直後に、SymfoNaviの画面をどれだけ念入りに隠すか。

 以前は「定期監視」――抽出中も数秒おきに窓を探して隠す――も持っていたが、
 WMIと窓の列挙が並行して走るとDDEとExcel生成が目立って遅くなるため、
 接続直後に隠しきる方式へ変えて定期監視は止めた。それにもかかわらず設定画面には
 「軽量監視（3秒）」「バランス（2秒）」「標準監視（1秒）」と、動いていない監視の
 間隔が並んだままだった。実際に効くのは下の2つだけなので、それだけを持つ。
   action_duration … 接続直後、隠す試行を続ける時間
   action_interval … その中で隠しなおす間隔
 """
 profile=str(settings.get('symnavi_hide_profile','balanced'))
 presets={
  # light は action_only と同じ。古い設定がそのまま動くように残してある。
  'action_only':{'action_duration':0.35,'action_interval':0.35},
  'light':{'action_duration':0.35,'action_interval':0.35},
  'balanced':{'action_duration':0.5,'action_interval':0.5},
  'standard':{'action_duration':0.6,'action_interval':0.5},
  'custom':{'action_duration':max(0.2,float(settings.get('symnavi_hide_action_duration_seconds',0.5))),'action_interval':max(0.2,float(settings.get('symnavi_hide_action_interval_seconds',0.5)))}
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

def start_hidden_symnavi(proc,settings):
 hide_after_action(proc,'DDE接続',settings)
 return None

# 定期監視（抽出中も数秒おきに窓を探して隠す）は持たない。WMIと窓の列挙が並行して
# 走るとDDEとExcel生成が目立って遅くなるため、接続直後に隠しきる方式に一本化した。
# 設定画面の選択肢からも、動いていない監視間隔の表記を外してある。

# 1対象ぶんの工程内訳。STEP_START/ENDは並列実行だと他プロセスの行と混ざって追いにくいので、
# 完了時に「どの工程が何秒・何%だったか」を1行へまとめ、対象ごとの傾向を後から比較できるようにする。
_phase_profile={'started':0.0,'depth':0,'phases':{}}

def phase_profile_reset():
 _phase_profile['started']=time.perf_counter();_phase_profile['depth']=0;_phase_profile['phases']={}

def phase_profile_add(phase,elapsed):
 """phase_logを通さない実測値（APIセッション接続など）も内訳へ含める。

 これを入れないとJOB_PROFILEのother=が膨らみ、小さい対象では時間の8割が
 内訳不明のまま残ってしまう。
 """
 _phase_profile['phases'][phase]=_phase_profile['phases'].get(phase,0.0)+float(elapsed)

def serial_run_metrics(engine,fmt,total,rows,cols,intermediate=None,dde_save_seconds=None):
 """直列実行1件ぶんの実績。並列ワーカーが返すものと同じ形に揃える。

 形が違うと一覧の実績欄・所要の比較・ログの読み方が方式ごとに分かれてしまう。
 DDEの[Save]は問い合わせと転送を一度に行うため、その1回を execute_seconds として扱う。
 """
 phases=phase_profile_seconds()
 def sec(*names):
  for n in names:
   v=phases.get(n)
   if v:return round(float(v),2)
  return None
 execute=sec('xls_save','api_execute_catalog') if engine=='dde' else sec('api_execute_catalog')
 transfer_seconds=(float(dde_save_seconds) if engine=='dde' and dde_save_seconds else None) or sec('api_save_xlsx_direct','api_save_csv')
 m={'elapsed':round(float(total),2),'rows':rows,'cols':cols,'format':fmt,'engine':engine,
    'execute_seconds':execute,'save_seconds':sec('api_save_xlsx_direct','api_save_csv') if engine!='dde' else sec('xls_stability'),
    'convert_seconds':sec('format_conversion'),'publish_seconds':sec('publish'),'lines':1}
 try:
  p=Path(intermediate) if intermediate else None
  if p and p.exists():
   size=p.stat().st_size;m['transfer_bytes']=size
   if transfer_seconds:m['transfer_kbs']=round(size/1024/transfer_seconds,1)
 except OSError:pass
 return {k:v for k,v in m.items() if v is not None}

def phase_profile_seconds():
 """いま測り終わっている工程の秒数。実績としてDBへ残すときに使う。"""
 return dict(_phase_profile['phases'])

def phase_profile_summary():
 total=time.perf_counter()-_phase_profile['started']
 if total<=0:return 'total=0.00s'
 ranked=sorted(_phase_profile['phases'].items(),key=lambda kv:-kv[1])
 measured=sum(_phase_profile['phases'].values())
 parts=['%s=%.2fs(%.1f%%)'%(k,v,100*v/total) for k,v in ranked]
 parts.append('other=%.2fs(%.1f%%)'%(max(0.0,total-measured),100*max(0.0,total-measured)/total))
 return 'total=%.2fs '%total+' '.join(parts)

def phase_log(phase,started=None,**values):
 parts=' '.join(f'{k}={v}' for k,v in values.items())
 if started is None:
  _phase_profile['depth']+=1
  log.info('STEP_START phase=%s %s',phase,parts)
  flush_log()
  return time.perf_counter()
 elapsed=time.perf_counter()-started
 _phase_profile['depth']=max(0,_phase_profile['depth']-1)
 # 入れ子の工程（format_conversion内のintermediate_parseなど）は二重計上しない。
 if _phase_profile['depth']==0:_phase_profile['phases'][phase]=_phase_profile['phases'].get(phase,0.0)+elapsed
 log.info('STEP_END phase=%s elapsed=%.2fs %s',phase,elapsed,parts)
 flush_log()
 return elapsed

def save_metrics(path,elapsed,rows):
 """NaviSaveDataの実効速度。経路や環境ごとの差を実機ログだけで比較できるようにする。"""
 size=path.stat().st_size if path.exists() else 0
 return {'size':size,'throughput_kb_s':f'{size/1024/elapsed:.1f}' if elapsed>0 else '0','ms_per_row':f'{elapsed*1000/int(rows):.2f}' if rows else '0'}

def _memory_status():
 if os.name!='nt':return ''
 try:
  import ctypes
  class _MS(ctypes.Structure):
   _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
  s=_MS();s.dwLength=ctypes.sizeof(_MS);ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
  return ' mem_load=%d%% mem_avail_mb=%d'%(s.dwMemoryLoad,s.ullAvailPhys//(1024*1024))
 except Exception:return ''

def log_run_environment(work_dir,rne_root):
 """実行環境の実測値。抽出が遅いとき「APIが遅い」のか「この端末が遅い」のかを切り分けるために残す。

 work_write_mb_s は中間CSVの書き出し先そのものの速度。
 rne_scan_ms はRNE置き場（BOX等）の応答。起動が極端に遅い日はここが伸びる。
 """
 try:
  write_mb_s=0.0;probe=Path(work_dir)/f'.probe_{os.getpid()}.bin'
  try:
   chunk=b'0'*(1024*1024);t=time.perf_counter()
   with probe.open('wb') as f:
    for _ in range(4):f.write(chunk)
    f.flush();os.fsync(f.fileno())
   d=time.perf_counter()-t;write_mb_s=4/d if d>0 else 0
  except OSError as e:log.warning('RUN_ENVIRONMENT_WRITE_PROBE_SKIP error=%s',e)
  finally:
   try:probe.unlink()
   except OSError:pass
  scan_ms=0.0;files=0
  try:
   t=time.perf_counter();files=sum(1 for p in Path(rne_root).iterdir() if p.is_file());scan_ms=(time.perf_counter()-t)*1000
  except OSError as e:log.warning('RUN_ENVIRONMENT_SCAN_SKIP error=%s',e)
  log.info('RUN_ENVIRONMENT cpu=%s%s work_write_mb_s=%.1f rne_scan_ms=%.0f rne_files=%s work=%s rne=%s base=%s',os.cpu_count() or 0,_memory_status(),write_mb_s,scan_ms,files,work_dir,rne_root,BASE)
 except Exception as e:
  log.warning('RUN_ENVIRONMENT_FAILED error=%s',e)

def progress(step,label,percent,**extra):
 set_status(step=step,step_label=label,step_percent=percent,current=label,elapsed_seconds=max(0,int(time.time()-getattr(progress,'started',time.time()))),heartbeat_at=datetime.now().isoformat(timespec='seconds'),**extra)

# ---- 相対期間（動的日付）------------------------------------------------------
# RNEに定義済みの時間型管理ポイントへ、処理日時を基準にした相対期間を実行直前に適用する。
# 単位=month: 月度指定 (YYYYMM00 / NAVI_MONTH=0) / 単位=day: 年月日指定 (YYYYMMDD / NAVI_YMD=1)。
def _add_months(year,month,delta):
 idx=(year*12+(month-1))+int(delta); return idx//12, idx%12+1

def compute_period(period,now=None):
 now=now or datetime.now()
 if not period or not period.get('enabled'):return None
 unit=period.get('unit') if period.get('unit') in ('month','day') else 'month'
 try:fo=int(period.get('from_offset',0) or 0)
 except Exception:fo=0
 try:to=int(period.get('to_offset',0) or 0)
 except Exception:to=0
 if unit=='month':
  fy,fm=_add_months(now.year,now.month,fo); ty,tm=_add_months(now.year,now.month,to)
  from_time=f'{fy:04d}{fm:02d}00'; to_time=f'{ty:04d}{tm:02d}00'; condition=0
  summary=f'{fy}年{fm}月度 ～ {ty}年{tm}月度'
 else:
  fd=(now.date()+timedelta(days=fo)); td=(now.date()+timedelta(days=to))
  from_time=fd.strftime('%Y%m%d'); to_time=td.strftime('%Y%m%d'); condition=1
  summary=f'{fd:%Y-%m-%d} ～ {td:%Y-%m-%d}'
 return {'condition':condition,'from_time':from_time,'to_time':to_time,'summary':summary,'unit':unit,'from_offset':fo,'to_offset':to}

def apply_dynamic_period(api_client,handle,job,now=None,line=''):
 # ジョブに相対期間が設定されていれば、開いたカタログの時間型管理ポイントを差し替える。
 # 期間が有効なのに適用に失敗した場合は、誤った期間での公開を避けるため例外を送出して失敗させる。
 period=job.get('period') or {}
 if not period.get('enabled'):return None
 spec=compute_period(period,now or datetime.now())
 if not spec:return None
 label=str(period.get('control_point') or '').strip()
 t=phase_log('api_change_period',job=job.get('name'),line=line,unit=spec['unit'],condition=spec['condition'],from_time=spec['from_time'],to_time=spec['to_time'],control_point=(label or '(時間フィールド)'))
 info=api_client.apply_period(handle,label,spec['condition'],spec['from_time'],spec['to_time'])
 phase_log('api_change_period',t,job=job.get('name'),line=line,applied_to=info.get('label'),locate=info.get('locate'),summary=spec['summary'])
 log.info('DYNAMIC_PERIOD job=%s line=%s enabled=1 unit=%s condition=%s from=%s to=%s target=%s summary=%s',job.get('name'),line or '-',spec['unit'],spec['condition'],spec['from_time'],spec['to_time'],info.get('label'),spec['summary'])
 return {**spec,'target':info.get('label')}

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
def _stream_csv_extract(source,encoding,skip_first):
 """中間CSVを1行ずつ読み、見出しと本体だけを残す。

 以前は list(csv.reader(f)) で生の行をすべて抱えたうえで、1セルずつ str() を通して
 本体をもう1つ作っていた。csv.readerが返すのは元から文字列なので、この str() は
 何も変えていない（同じ文字列オブジェクトが返るだけ）。桁数が合っている行は
 そのまま使い、合わない行だけ整える。

 実測 6万行x178列(103MB) 中央値5回:
   解析     4.60s → 2.84s（-38%）
   ピークRSS 859MB → 768MB（-11%）
 メモリの減りが1割ほどなのは、重いのは文字列そのもので、それは元から共有されて
 いたため。減るのは生の行のリストぶん。ワーカーは対象ごとに別プロセスなので、
 大きい対象が並列で重なるとこの差もライン数ぶん効く。
 """
 hs=None;n=0;body=[]
 with source.open('r',encoding=encoding,errors='strict',newline='') as f:
  reader=csv.reader(f)
  if skip_first:next(reader,None)
  for row in reader:
   if hs is None:
    hs=unique_headers(row);n=len(hs);continue
   c=len(row)
   if c==n:body.append(row)
   elif c<n:body.append(row+['']*(n-c))
   else:body.append(row[:n])
 return hs,body

def read_extract(source,job,reject,expected_rows=None,expected_cols=None):
 source=Path(source); started=time.perf_counter()
 skip_first=(job.get('type')=='集計表')
 if source.suffix.lower()=='.csv':
  hs=None;body=None;encoding_used=''
  last_error=None
  for encoding in ('cp932','utf-8-sig','utf-8'):
   try:
    hs,body=_stream_csv_extract(source,encoding,skip_first);encoding_used=encoding;break
   except UnicodeDecodeError as e:last_error=e;hs=None;body=None
  if body is None:raise UnicodeError(f'API中間CSVの文字コードを判定できません: {source}: {last_error}')
  source_kind='api_csv'
 else:
  import xlrd
  b=xlrd.open_workbook(str(source),on_demand=True)
  try: sh=b.sheet_by_name(job.get('sheet','Page1')); rows=[sh.row_values(i) for i in range(sh.nrows)]
  finally:b.release_resources()
  encoding_used='binary';source_kind='dde_xls'
  if skip_first and rows:rows=rows[1:]
  hs=unique_headers(rows[0]) if rows else None
  body=[]
  if hs is not None:
   for row in rows[1:]:body.append([str(x) if x is not None else '' for x in list(row[:len(hs)])+['']*max(0,len(hs)-len(row))])
  rows=None
 if hs is None:raise ValueError(f'{source.suffix}にデータがありません')
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

def export_data(source,dst,job,reject,expected_rows=None,expected_cols=None,data=None):
 """中間データを、指定の形式へ書き出す。

 data を渡すと、中間データの読み直しをしない。同時出力では形式のぶんだけ同じCSVを
 解析し直していた（実測 6万行x178列で1回2.84s。3形式なら2回ぶんが同じ作業のやり直しで、
 対象が大きいほど効く）。書き出し側は hs / body を読むだけで書き換えないため、
 全形式で共有して問題ない。"""
 if data is not None:
  hs,body=data
  log.info('INTERMEDIATE_REUSE job=%s source=%s rows=%s columns=%s note=解析済みの中間データを使い回します',job.get('name'),source,len(body),len(hs))
 else:
  parse_started=phase_log('intermediate_parse',job=job.get('name'),source=source);hs,body=read_extract(source,job,reject,expected_rows,expected_cols);phase_log('intermediate_parse',parse_started,job=job.get('name'),rows=len(body),columns=len(hs))
 fmt=validate_output_contract(job,'export'); log.info('出力開始 configured_format=%s effective_format=%s configured_file=%s work_file=%s rows=%s columns=%s',job.get('output_format'),fmt,job.get('output_file'),dst,len(body),len(hs))
 if dst.exists():dst.unlink()
 if fmt=='sqlite3':
  sqlite_started=time.perf_counter();c=sqlite3.connect(dst)
  try:
   c.execute('PRAGMA synchronous=FULL'); c.execute(f'CREATE TABLE {qi(job["table"])} ('+', '.join(qi(x)+' TEXT' for x in hs)+')')
   insert_started=time.perf_counter()
   if body:c.executemany(f'INSERT INTO {qi(job["table"])} VALUES ('+','.join('?' for _ in hs)+')',body)
   log.info('SQLITE_INSERT rows=%s columns=%s elapsed=%.2fs',len(body),len(hs),time.perf_counter()-insert_started)
   # 読み手（BI・アプリ）は絞り込んで読む。索引が1つも無いと毎回すべての行を走査する。
   # どの列で絞るかはこのアプリからは分からないので、対象ごとに指定してもらう。
   want=[x for x in (job.get('index_columns') or []) if x in hs]
   for n,col in enumerate(want[:4],1):
    idx_started=time.perf_counter()
    c.execute(f'CREATE INDEX {qi("idx_"+str(n))} ON {qi(job["table"])} ({qi(col)})')
    log.info('SQLITE_INDEX column=%s rows=%s elapsed=%.2fs',col,len(body),time.perf_counter()-idx_started)
   missing=[x for x in (job.get('index_columns') or []) if x not in hs]
   if missing:log.warning('SQLITE_INDEX_SKIPPED columns=%s reason=出力に無い列です',missing)
   c.execute('CREATE TABLE _更新情報 (項目 TEXT PRIMARY KEY, 値 TEXT)'); c.executemany('INSERT INTO _更新情報 VALUES (?,?)',[('作成日時',datetime.now().isoformat(timespec='seconds')),('RNE',job['rne']),('件数',str(len(body)))]+([('索引',' / '.join(want))] if want else []))
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

# 公開（隠しファイルへ書き切って一気に差し替える・保留・控え・指紋）は navi_publish.py。
import navi_publish
navi_publish.setup(LOCAL_ROOT,LOCAL_BACKUP)
from navi_publish import (publish,apply_pending,_replace_once,_pending_pattern,
                          intermediate_fingerprint,unchanged_since_last,remember_published)

def publish_extra_formats(j,cfg,intermediate,out_dir,work_dir,backup,stamp,line='',data=None):
 """主の形式を公開したあと、同じ中間データから残りの形式も作って公開する。

 抽出（Navigatorへの問い合わせと転送）は済んでいるので、ここで増えるのは変換と
 公開だけ。取り直しは一切しない。1つ転んでも残りは続ける ―― 追加の形式のために
 主の出力まで落とすと、本末転倒になるため。

 data には解析済みの中間データを渡す。渡さなければここで1回だけ読み、形式のぶん
 だけ読み直すことはしない。"""
 extras=job_extra_formats(j)
 if not extras or not intermediate:return []
 s=cfg['settings'];made=[]
 if data is None:
  parse_started=phase_log('intermediate_parse',job=j.get('name'),line=line,source=intermediate)
  data=read_extract(intermediate,j,bool(s['reject_zero_rows']))
  phase_log('intermediate_parse',parse_started,job=j.get('name'),line=line,rows=len(data[1]),columns=len(data[0]))
 for fmt in extras:
  started=time.perf_counter();name=canonical_output_file(j['output_file'],fmt)
  target=out_dir/name;work=work_dir/f'{Path(name).stem}_{stamp}{Path(name).suffix}'
  row={'format':fmt,'file':name,'target':str(target),'ok':False,'published':False,'error':''}
  try:
   sub=dict(j);sub['output_format']=fmt;sub['output_file']=name
   apply_pending(target,backup,int(s['backup_generations']),backup_enabled=bool(s.get('backup_enabled',True)),
                 retention_days=int(s.get('backup_retention_days',30)),
                 generation_limit_enabled=bool(s.get('backup_generation_limit_enabled',True)),
                 backup_mode=str(s.get('backup_mode','generations')))
   t=phase_log('extra_format_conversion',job=j['name'],line=line,format=fmt)
   nr,nc=export_data(intermediate,work,sub,bool(s['reject_zero_rows']),data=data)
   phase_log('extra_format_conversion',t,job=j['name'],line=line,format=fmt,rows=nr,columns=nc)
   pub=publish(work,target,backup,int(s['backup_generations']),backup_enabled=bool(s.get('backup_enabled',True)),
               retention_days=int(s.get('backup_retention_days',30)),
               generation_limit_enabled=bool(s.get('backup_generation_limit_enabled',True)),
               backup_mode=str(s.get('backup_mode','generations')))
   row.update({'ok':True,'published':pub['published'],'pending':pub.get('pending',''),
               'rows':nr,'columns':nc,'elapsed':round(time.perf_counter()-started,2)})
   log.info('EXTRA_FORMAT_PUBLISHED line=%s job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s published=%s',
            line,j['name'],fmt,nr,nc,time.perf_counter()-started,target,pub['published'])
  except Exception as e:
   row['error']=str(e)
   log.warning('EXTRA_FORMAT_FAILED line=%s job=%s format=%s error=%s（主の出力は公開済みのため実行は続けます）',
               line,j['name'],fmt,e)
  finally:
   try:
    if work.exists():work.unlink()
   except OSError:pass
  made.append(row)
 return made

def extra_format_note(extras):
 """結果の1行に足す、同時出力のまとめ。"""
 if not extras:return ''
 done=[x for x in extras if x['ok']];bad=[x for x in extras if not x['ok']]
 text=f' / 同時出力 {len(done)}/{len(extras)}形式（'+'・'.join(OUTPUT_FORMAT_LABEL.get(x['format'],x['format']) for x in done)+'）' if done else ''
 if bad:text+=f' / 失敗 '+'・'.join(OUTPUT_FORMAT_LABEL.get(x['format'],x['format']) for x in bad)
 return text

def process_catalog_inspect(j,cfg,user,pw,server,want=None):
 """RNEを開いて中身を読み取る。ワーカープロセスから呼ばれる。

 DLLは外部のネイティブコードで、読み取り中の異常はPythonの例外にならずプロセスごと落ちる。
 本体のFlaskと同じプロセスで動かすと画面まで巻き添えになるため、ここを独立プロセスに閉じ込める。
 """
 started=time.perf_counter();api=None;out={'ok':False}
 want=want or ['points','items']
 read_names=bool(j.get('_read_names',True))
 known=list(j.get('_known_columns') or [])
 try:
  api,handle=open_api_catalog(cfg,resolve_rne_path(j,cfg))
  if 'points' in want:
   pts=api.list_time_control_points(handle,read_names=read_names)
   out['points']=pts;out['time_points']=[p for p in pts if p.get('is_time')]
  if 'axes' in want:
   # 行を絞れるのは管理ポイントだけ。どこに何が置かれているか（表側／表頭／条件）と、
   # その軸が取り得る値まで読む。直近の出力ファイルが無くても行分割の下調べができる。
   # ここでは値の「数」と見本だけを読む。64本×8000件を全部読むのは現実的でないため。
   axes=api.list_control_points(handle,read_names=read_names,with_categories=6)
   out['axes']=axes
   for a in axes:
    log.info('ROW_AXIS %s#%s 名前=%s 型=%s 値の数=%s 読み込み=%s 期間=%s%s%s',a['location'],a['index']+1,a['name'],
             a['type_name'],a.get('category_count'),a.get('load_form') or '(未)',a.get('period'),
             (' 読めた値='+' | '.join((a.get('categories') or [])[:8])[:120]) if a.get('categories') else
             (' 値の読み取り='+a['category_error'] if a.get('category_error') else ''),
             (' 先頭一致の下見='+json.dumps(a['prefix'],ensure_ascii=False)) if a.get('prefix') else '')
    for t in (a.get('load_tried') or []):
     log.info('ROW_AXIS_LOAD %s#%s %s %s',a['location'],a['index']+1,a['name'],t)
  if 'items' in want:
   lay=api.column_layout(handle,columns=known,read_names=read_names)
   out['layout']={'removable':[x['name'] for x in lay['removable']],'fixed':[x['name'] for x in lay['fixed']],
                  'condition':[x['name'] for x in lay['condition_items']],
                  'data_item_count':len(lay['data_items']),'control_point_count':len(lay['control_points'])}
   out['data_items']=lay['data_items'];out['di_diag']=getattr(api,'di_diag','')
   fields,why=api.field_number(handle);out['field_count']=fields;out['field_why']=why
  if 'axis_values' in want:
   # 実際に使う軸1本だけ、値を読み切る。分割の割り当てはこの結果から作る。
   spec=(j.get('_axis') or {})
   lim=int((cfg.get('settings') or {}).get('row_axis_category_limit',8000) or 8000)
   out['axis_values']=api.axis_categories(handle,spec,limit=lim)
   av=out['axis_values']
   log.info('AXIS_VALUES 軸=%s つかみ方=%s 値の数=%s 読めた=%s 完全=%s 読み込み=%s%s',
            av.get('name'),av.get('how'),av.get('count'),len(av.get('values') or []),av.get('complete'),
            av.get('load_form'),(' error='+av['error']) if av.get('error') else '')
   for t in (av.get('load_tried') or []):log.info('AXIS_VALUES_TRIED %s',t)
  if 'timing' in want:
   # 転送せずに問い合わせだけを実行し、サーバー側で結果を作るのにかかる時間を測る。
   # 通常の実行(DOWNLOADNOW)との差が、そのまま転送に費やされている時間になる。
   # 行分割が効くかどうかは、この内訳でほぼ決まる（実行が主なら行を減らせば縮む見込みがあり、
   # 転送が主なら縮むのは転送だけで、回線の上限に頭を押さえられる）。
   if (j.get('period') or {}).get('enabled'):
    try:apply_dynamic_period(api,handle,j,datetime.now(),line='probe')
    except Exception as pe:out['period_error']=str(pe)
   n,el=api.execute_deferred(handle)
   api.terminate_download(handle)
   out['deferred']={'rows':int(n),'execute_seconds':round(el,2)}
  out['column_split_ready']=api.supports_column_split()
  try:api.close_catalog()
  except Exception:pass
  out['ok']=True;out['elapsed']=round(time.perf_counter()-started,2)
  return out
 except Exception as e:
  return {'ok':False,'error':str(e),'elapsed':round(time.perf_counter()-started,2)}
 finally:
  if api:
   try:api.close()
   except Exception:pass

def run_inspect_worker(job,cfg,user,pw,server,want,timeout=180):
 """RNEの読み取りを独立プロセスで行う。落ちても本体は生き残る。"""
 work=LOCAL_RUNTIME/('inspect_'+uuid.uuid4().hex[:8]);work.mkdir(parents=True,exist_ok=True)
 try:
  payload={'job':job,'cfg':cfg,'user':user,'password':pw,'server':server,'inspect':{'want':want}}
  pp=work/'payload.json';pp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
  rp=work/'result.json'
  env=os.environ.copy();env['NAVI_WORKER_RESULT']=str(rp);env['NAVI_WORKER_LINE']='調査'
  env['NAVI_WORKER_SPAWN_AT']=repr(time.time())
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  t=time.perf_counter()
  proc=subprocess.Popen([sys.executable,str(BASE/'api_worker.py'),str(pp)],cwd=str(BASE),env=env,creationflags=flags)
  try:rc=proc.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   proc.kill();log.warning('INSPECT_WORKER_TIMEOUT job=%s timeout=%ss',job.get('name'),timeout)
   return {'ok':False,'error':f'読み取りが{timeout}秒を超えたため中止しました'}
  res=_read_worker_json(rp,None)
  log.info('INSPECT_WORKER job=%s returncode=%s ok=%s read_names=%s elapsed=%.2fs',job.get('name'),rc,bool(res and res.get('ok')),job.get('_read_names',True),time.perf_counter()-t)
  if res is None:
   # 結果を書く前に落ちた＝DLL側での異常終了。名前の読み取りが原因のことがあるので、
   # 一度だけ名前なしでやり直す。件数と分割の判定は名前が無くても出せる。
   if job.get('_read_names',True):
    log.warning('INSPECT_WORKER_RETRY_WITHOUT_NAMES job=%s returncode=%s',job.get('name'),rc)
    return run_inspect_worker(dict(job,_read_names=False),cfg,user,pw,server,want,timeout)
   return {'ok':False,'error':f'RNEの読み取り中に読み取りプロセスが異常終了しました（終了コード {rc}）。'
                             'このRNEでは読み取りを行えません。通常の実行には影響しません。','crashed':True,'returncode':rc}
  if not job.get('_read_names',True):res['names_skipped']=True
  return res
 finally:
  try:shutil.rmtree(work,ignore_errors=True)
  except Exception:pass

# ---- 実行中のラインを動かし続ける ----------------------------------------
# 問い合わせ実行(NaviExecuteCatalog)と保存(NaviSaveData)は、DLLの中で数十秒止まる。
# その間、呼び出した側は1行も進めないので、画面は固まって見える。
# そこで別スレッドから状態だけを書き出す。ctypesはDLL呼び出しのあいだGILを手放すので、
# 本体が止まっていてもこのスレッドは動ける。抽出そのものには一切触れない。

LINE_STATE={'session':'API接続','execute':'問い合わせ実行','transfer':'受信・保存','convert':'変換・検証','publish':'公開'}
LINE_PHASES={'session':(5,20),'execute':(20,55),'transfer':(55,80),'convert':(80,92),'publish':(92,100)}
LINE_STEPS=['session','execute','transfer','convert','publish']

def line_percent(phase,progress=0.0):
 lo,hi=LINE_PHASES.get(phase,(0,100))
 return round(lo+(hi-lo)*max(0.0,min(1.0,float(progress or 0))),1)

def fmt_mb(n):
 n=float(n or 0)
 return f'{n/1024/1024:.1f}MB' if n>=1024*1024 else f'{max(0,int(n))//1024}KB'

def _line_tick(line,job,phase,make,elapsed,note=''):
 """別プロセスを待っている側から、1回ぶんの進み具合を書き出す。"""
 try:
  prog,detail=make(elapsed)
  guess=prog is None
  if guess:prog=min(0.9,elapsed/60.0)
  update_parallel_line(line,job=job.get('name'),job_id=job.get('id'),state=LINE_STATE.get(phase,phase),
                       percent=line_percent(phase,prog),detail=(detail+(' · '+note if note else '')),
                       elapsed=round(elapsed,1),phase=phase,measured=not guess)
 except Exception:pass

def _split_expect_bytes(job,cfg,rne_path):
 """分割なしで取ったときのバイト数の見込み。分割の分母を作るのに使う。"""
 try:
  m=(load_job_runs().get(job.get('id')) or {}).get('metrics') or {}
  if m.get('transfer_bytes') and not m.get('split_parts'):return int(m['transfer_bytes'])
 except Exception:pass
 try:return split_expected_bytes(rne_path,job,cfg)
 except Exception:return 0

@contextlib.contextmanager
def line_ticker(line,job,phase,make,interval=0.4):
 """DLLが返ってくるまでの間、0.4秒ごとに進み具合を書き出す。

 make(elapsed) は (0..1の進み具合, 画面に出す文字) を返す。測れないときは進み具合に
 None を返すこと。呼び出し側は「見当」として扱い、工程の9割で頭打ちにする。
 """
 stop=threading.Event();started=time.perf_counter()
 def run():
  while not stop.wait(interval):
   try:
    el=time.perf_counter()-started
    prog,detail=make(el)
    guess=prog is None
    if guess:prog=min(0.9,el/60.0)
    update_parallel_line(line,job=job.get('name'),job_id=job.get('id'),state=LINE_STATE.get(phase,phase),
                         percent=line_percent(phase,prog),detail=detail,elapsed=round(el,1),
                         phase=phase,measured=not guess)
   except Exception:pass
 t=threading.Thread(target=run,daemon=True,name=f'tick-{phase}');t.start()
 try:yield
 finally:
  stop.set()
  try:t.join(timeout=1.0)
  except Exception:pass

def growing_file_tick(path,expected_bytes,label='受信'):
 """書き出され続けているファイルの大きさから、進み具合と速さを出す。

 これが唯一の実測。ファイルがまだ無い＝サーバー側の準備中なので、そこは測れないと返す。
 path はリストでもよい（分割のときは全パートを合算する）。
 """
 paths=[path] if isinstance(path,(str,Path)) else list(path or [])
 def make(elapsed):
  got=0
  for x in paths:
   try:got+=Path(x).stat().st_size
   except Exception:pass
  if not got:return None,f'{label}待ち {elapsed:.0f}秒'
  kbs=got/1024/max(0.1,elapsed)
  if expected_bytes:
   prog=min(0.99,got/float(expected_bytes))
   rest=max(0.0,(expected_bytes-got)/1024/max(1.0,kbs))
   return prog,f'{fmt_mb(got)} / 約{fmt_mb(expected_bytes)} · {kbs:,.0f}KB/s · 残り{rest:.0f}秒'
  return None,f'{fmt_mb(got)} · {kbs:,.0f}KB/s'
 return make

def elapsed_tick(expected_seconds,label,note=''):
 """測れない工程。前回の実績と見比べて出す。進み具合は None（＝見当）で返す。"""
 def make(elapsed):
  if expected_seconds and expected_seconds>0:
   return min(0.9,elapsed/float(expected_seconds)),f'{label} {elapsed:.0f}秒 / 前回 {float(expected_seconds):.0f}秒'+(f' · {note}' if note else '')
  return None,f'{label} {elapsed:.0f}秒'+(f' · {note}' if note else '')
 return make

# データベースが「検索条件式が長すぎる」と断ってきたときの印。値の数を減らす以外に手はない。
#   KVR52020 データベースに対する検索条件式が長すぎるため問い合わせができません
SPLIT_FILTER_TOO_LONG_MARKS=('KVR52020','NAVI_ERROR_EXECMD')

def split_filter_too_long(err):
 """その失敗が「条件式が長すぎる」ものかどうか。"""
 t=str(err or '')
 return 'KVR52020' in t or ('NAVI_ERROR_EXECMD' in t and '長すぎる' in t)

def process_split_part(j,cfg,user,pw,server,out_csv,drop_columns,part_label='',row_condition=None,row_axis=None):
 """1パートを実行してCSVへ保存する。担当外の列を外し、担当する行だけに絞る。

 drop_columns も row_condition も空なら、分割なしの実行になる。
 両方を指定すれば「行も列も分けた1片」になり、行×列の組み合わせがそのまま作れる。

 通常の実行経路とは分けてある。ここは比較のための素の実行だけを行い、
 出力形式の変換も公開も行わない。RNEファイルは変更しない。
 """
 from navigator_api import NavigatorApi
 started=time.perf_counter();api=None;rp=resolve_rne_path(j,cfg)
 stage={'part':part_label,'dropped':0}
 # 親は書きかけのファイルの大きさしか見られない。どの工程にいるかはここから知らせる。
 status_path=os.environ.get('NAVI_WORKER_STATUS') or ''
 def step(name,**extra):
  stage['step']=name
  if not status_path:return
  try:
   d=dict({'part':part_label,'step':name,'elapsed':round(time.perf_counter()-started,2),
           'at':time.time()},**extra)
   tmp=Path(status_path).with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
   os.replace(tmp,status_path)
  except Exception:pass
 try:
  step('接続')
  api=NavigatorApi(resolve_path(cfg.get('symnavi_exe','')),log,resolve_path(cfg.get('navigator_api_dll')) if cfg.get('navigator_api_dll') else None,base_dir=BASE,search_roots=dll_search_roots(cfg))
  api.open_session(user,pw,server)
  profiles=api_data_source_profiles(resolve_path(cfg['symnavim_conf']))
  if not any(p.get('kind')=='oracle' for p in profiles):
   profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0'})
  for profile in profiles:api.connect_data_source(profile)
  with chdir_lock:
   prev=os.getcwd()
   try:
    os.chdir(Path(rp).parent);handle,_=api.open_catalog(Path(rp).resolve())
   finally:os.chdir(prev)
  step('RNEを開く')
  if (j.get('period') or {}).get('enabled'):apply_dynamic_period(api,handle,j,datetime.now(),line=part_label)
  if drop_columns:
   step('担当外の列を外す')
   t=time.perf_counter();removed=api.apply_column_split(handle,drop_columns);stage['dropped']=len(removed)
   log.info('SPLIT_PART_REMOVE part=%s removed=%s elapsed=%.2fs',part_label,len(removed),time.perf_counter()-t)
  if row_axis:
   # 管理ポイントで絞る。出力される列（データ欄）と違い、ここは実際に行が減る。
   step('行の軸で絞る')
   t=time.perf_counter()
   applied=(api.apply_row_period(handle,row_axis) if row_axis.get('kind')=='period'
            else api.apply_row_categories(handle,row_axis))
   stage['row_condition']=applied
   log.info('SPLIT_PART_ROWAXIS part=%s 軸=%s(%s %s番目) 種類=%s 通った形=%s つかみ方=%s %s elapsed=%.2fs',
            part_label,applied['column'],row_axis.get('location'),int(row_axis.get('index') or 0)+1,
            row_axis.get('kind'),applied.get('form'),applied.get('how'),
            (f"期間={applied.get('from')}〜{applied.get('to')}" if row_axis.get('kind')=='period'
             else (f"このプロセスへ読み込めた={applied.get('loaded')}種({applied.get('load_form')}) "
                   f"担当={applied.get('values')}種 / 外した={applied.get('others')}種"
                   +(f" / 調べた時点に無かった値={applied.get('unknown')}種"
                     +('をこの片が引き取りました' if applied.get('took_unknown') else 'は後ろの片が引き取ります')
                     if applied.get('unknown') else ''))),
            time.perf_counter()-t)
   for x in (applied.get('tried') or []):log.info('SPLIT_PART_ROWAXIS_TRIED part=%s %s',part_label,x)
  if row_condition:
   # 担当する行だけに絞る。ここが効かないと同じ行を何度も取ってしまうので、失敗は必ず例外にする。
   step('行の条件を設定')
   t=time.perf_counter();applied=api.apply_row_condition(handle,row_condition);stage['row_condition']=applied
   log.info('SPLIT_PART_ROWCOND part=%s 列=%s 見つけた場所=%s 通った形=%s condition=0x%x range=0x%x 下限=%r(%s) 上限=%r(%s) 見込み行数=%s elapsed=%.2fs',
            part_label,applied['column'],applied.get('locate','?'),applied.get('form','?'),applied['condition'],applied['range'],
            applied.get('lvalue',''),'含む' if not row_condition.get('lcheck') else '含まない',
            applied.get('rvalue',''),'含む' if not row_condition.get('rcheck') else '含まない',
            row_condition.get('rows'),time.perf_counter()-t)
   for x in (applied.get('tried') or []):log.info('SPLIT_PART_ROWCOND_TRIED part=%s %s',part_label,x)
  step('問い合わせを実行')
  t=time.perf_counter();rows,_=api.execute(handle);exec_elapsed=time.perf_counter()-t
  expected_rows,expected_cols=api.dimensions(handle)
  step('CSVへ保存',rows=expected_rows,cols=expected_cols)
  t=time.perf_counter();api.save_csv(handle,Path(out_csv));save_elapsed=time.perf_counter()-t
  api.close_catalog()
  size=Path(out_csv).stat().st_size if Path(out_csv).is_file() else 0
  total=time.perf_counter()-started
  # 実行(DOWNLOADNOW)にはサーバー側の処理とダウンロードの両方が含まれる。保存は手元の整形。
  want=(row_condition or {}).get('rows') or (row_axis or {}).get('expect_rows')
  log.info('SPLIT_PART_DONE part=%s dropped=%s rows=%s%s cols=%s size=%s(%.1fMB) '
           '実行=%.2fs(サーバー+受信 %.0fKB/s) 保存=%.2fs(整形 %.0fKB/s) 合計=%.2fs',
           part_label,stage['dropped'],expected_rows,
           (f'(見込み{want} 差{int(expected_rows)-int(want):+d})' if want else ''),
           expected_cols,size,size/1024/1024,
           exec_elapsed,(size/1024/exec_elapsed) if exec_elapsed>0 else 0,
           save_elapsed,(size/1024/save_elapsed) if save_elapsed>0 else 0,total)
  step('完了',rows=expected_rows,cols=expected_cols,size=size)
  # 行の条件が本当に効いたかを、返ってきた行数で確かめる。rc=OK でも1行も絞られないことがあり
  # （データ欄の項目に条件を付けた場合）、そのまま結合すると同じ行を分割数ぶん重複させてしまう。
  applied_row=stage.get('row_condition') or {}
  # 軸で絞ったつもりが全件返っていないか。データ欄への条件が空振りした前例があるので必ず確かめる。
  if row_axis and not row_condition:
   full=int(row_axis.get('total_rows') or 0)
   if full and int(expected_rows)>=full*0.95:
    return {'ok':False,'part':part_label,'row_condition_ineffective':True,
            'rows':expected_rows,'expected_rows':int(row_axis.get('expect_rows') or full/max(1,int(row_axis.get('parts') or 2))),
            'row_column':applied_row.get('column',''),'row_locate':row_axis.get('location',''),
            'row_form':applied_row.get('form',''),
            'error':f'行の軸「{applied_row.get("column","")}」で絞れませんでした。'
                    f'{applied_row.get("form","?")} で設定できたのに、全体{full}行に対して{expected_rows}行'
                    '（ほぼ全件）が返っています。',
            'elapsed':round(total,2)}
  if row_condition and want:
   full=int(row_condition.get('total_rows') or 0)
   if int(expected_rows)>=int(want)*1.5 and (not full or int(expected_rows)>=full*0.95):
    return {'ok':False,'part':part_label,'row_condition_ineffective':True,
            'rows':expected_rows,'expected_rows':want,'row_column':applied_row.get('column',''),
            'row_locate':applied_row.get('locate',''),'row_form':applied_row.get('form',''),
            'error':f'行の条件が効きませんでした。「{applied_row.get("column","")}」に条件を設定できた'
                    f'（{applied_row.get("locate","?")} / {applied_row.get("form","?")}）にもかかわらず、'
                    f'見込み{want}行に対して{expected_rows}行（ほぼ全件）が返っています。'
                    'この列では行を絞れないため、結合すると同じ行が重複します。',
            'elapsed':round(total,2)}
  return {'ok':True,'part':part_label,'file':str(out_csv),'rows':expected_rows,'cols':expected_cols,'size':size,
          'execute_elapsed':round(exec_elapsed,2),'save_elapsed':round(save_elapsed,2),'elapsed':round(total,2),
          'dropped':stage['dropped'],'row_condition':bool(row_condition),
          'expected_rows':(want or (row_axis or {}).get('expect_rows')),
          'row_locate':applied_row.get('locate','') or (row_axis or {}).get('location',''),
          'row_form':applied_row.get('form','')}
 except Exception as e:
  # 「条件式が長すぎる」は、この軸では何度やっても同じ結果になる種類の失敗。
  # 呼び出し側がその軸を覚えて次から避けられるよう、印を付けて返す。
  toolong=split_filter_too_long(e)
  log.error('SPLIT_PART_FAILED part=%s step=%s%s error=%s',part_label,stage.get('step',''),
            ' 種別=条件式が長すぎる' if toolong else '',e)
  step('失敗',error=str(e))
  return {'ok':False,'part':part_label,'error':str(e),'step':stage.get('step',''),
          'filter_too_long':bool(toolong),'row_axis_name':(row_axis or {}).get('column',''),
          'row_axis_values':len((row_axis or {}).get('values') or [])+len((row_axis or {}).get('others') or []),
          'elapsed':round(time.perf_counter()-started,2)}
 finally:
  if api:
   try:api.close()
   except Exception:pass

def plan_run_split(rne_path,job,cfg,fmt,budget_lines,line=''):
 """本番の実行を分割で取るかどうかを決める。分割しないときは (None, 理由)。

 ここは実行の直前に通る道なので、測定も問い合わせもしない。判断材料は保存済みのものだけ。
 結果の一致が確認済みの割り当てが有り、RNEも列の顔ぶれも当時のままで、使えるラインが
 足りているときだけ分割する。ひとつでも欠けたら、そのまま1本で取る。
 「自動」はさらに、実際に速かったという裏付けも求める。
 「競争」は速さの裏付けを求めない代わりに、分割なしを1本ぶん余分に使う（負けたら捨てる）。
 """
 mode=normalize_split_mode(job.get('split_mode'))
 shape=normalize_split_shape(job.get('split_shape'))
 if not bool((cfg.get('settings') or {}).get('split_run_enabled',True)):return None,'共通設定で分割を使わない設定です'
 if mode=='off':return None,'この対象は分割を使わない設定です'
 need=3 if mode=='race' else 2                 # 競争は「分割なし1本 ＋ パート2本」が最小
 if int(budget_lines or 1)<need:
  return None,(f'競争には最低{need}本のラインが要りますが、いまは{budget_lines}本です' if mode=='race'
               else f'同時に使えるラインが{budget_lines}本しかありません')
 if fmt=='xlsx' and mode not in ('force','race'):
  # XLSXはAPIが直接書き出せる。分割するとCSV経由＋結合＋変換になり、速さの前提が変わる。
  return None,'XLSXはAPIが直接書き出す方が速いため、自動では分割しません（常に分割を選ぶと分割します）'
 state,cached=column_cache_state(rne_path)
 if state!='hit':return None,('RNEが更新されています。もう一度実行すると列定義が取り直されます' if state=='stale' else '列定義がまだありません')
 columns=cached['columns']
 # 同じ名前の列が困るのは、列名で担当を決めて突き合わせる形だけ。行分割はどの片も全列を持ち、
 # 縦に積むだけなので取り違えようがない。同名があるときに成立するのは行分割だけ、と決める。
 dupes=duplicate_columns(columns);dupe_note=''
 if dupes:
  names='、'.join(d['name'] for d in dupes[:3])+('ほか' if len(dupes)>3 else '')
  if shape in ('column','grid'):
   return None,f'同じ名前の列があります（{names}）。列名で担当を決める形なので、この分け方は使えません'
  dupe_note=f'同じ名前の列があります（{names}）。列を使う形は成立しないため、行分割だけを見ます'
  shape='row'
 # 競争するときは分割なしが1本を占めるので、パートに回せるのは残り。
 room=(int(budget_lines)-1) if mode=='race' else int(budget_lines)
 gate=None if mode in ('race','force') else float((cfg.get('settings') or {}).get('split_min_speedup',1.05) or 1.05)
 chosen,why=pick_split_plan(rne_path,columns,room,gate,shape)
 if not chosen:return None,(dupe_note+' → '+why) if dupe_note else why
 kind=chosen['mode']
 if kind!='row':
  if len(chosen['plan'])<2 or not chosen['keys']:return None,'保存済みの割り当てが不完全です'
 if kind in ('row','grid'):
  rowspec=chosen.get('row') or {}
  if int(rowspec.get('parts') or 0)<2:return None,'保存済みの行の割り当てが不完全です'
  if not rowspec.get('axis_name'):return None,'保存済みの行の軸が分かりません'
 chosen=dict(chosen,run_mode=mode,race=(mode=='race'))
 log.info('SPLIT_RUN_PLAN line=%s job=%s rne=%s 形=%s 片数=%s 動作=%s 指定=%s budget=%s 裏付け=%s倍(%s) 軸=%s',
          line,job.get('name'),rne_path,split_shape_label(kind,len(chosen['plan']) or chosen['parts'],(chosen.get('row') or {}).get('parts',0)),
          chosen['parts'],mode,shape,budget_lines,
          f"{chosen['observed_speedup']:.2f}" if chosen['observed_speedup'] else '-',chosen['proven_at'],
          (chosen.get('row') or {}).get('axis_name') or '-')
 return chosen,''

def _prepare_row_parts(j,cfg,rp,chosen,line=''):
 """行の軸を実行の直前に読み直し、担当する値をその場で割り振る。

 保存できるのは「どの軸で何分割するか」まで。値そのものは日々増減するので
 （実測 1746種 → 1754種）、保存した値で分けると新しい値の行がどの片にも入らず落ちる。
 読み直しはサーバーへ1回問い合わせる。その秒数は本番の所要にそのまま乗るので、
 速さの裏付け（observed_speedup）からは影実行の時点で差し引いてある。
 """
 rowspec=chosen.get('row') or {}
 parts=max(2,int(rowspec.get('parts') or 2))
 choice={'mode':rowspec.get('choice_mode') or 'first','index':int(rowspec.get('choice_index') or 1),
         'name':str(rowspec.get('choice_name') or '')}
 hint={'name':rowspec.get('axis_name',''),'location':rowspec.get('axis_location',''),
       'index':rowspec.get('axis_index',0),'type_name':rowspec.get('axis_type','')}
 update_parallel_line(line,job=j['name'],job_id=j['id'],state='行の軸を読み直し',percent=line_percent('execute',0),
                      detail=f"「{rowspec.get('axis_name','')}」のいまの値を読みます",phase='execute')
 started=time.perf_counter()
 now=resolve_axis_now(j,cfg,rp,parts,'',hint=hint,choice=choice,line=line)
 elapsed=time.perf_counter()-started
 if not now.get('axis'):
  raise RuntimeError(f"行の軸を読み直せませんでした: {now.get('error')}")
 axis=now['axis']
 used=max(1,int(now.get('parts') or 0))
 if used<2:
  raise RuntimeError(f"いま「{axis['name']}」で分けられるのは{used}つだけです（実行の時点で値が足りません）")
 ap=plan_axis_split(axis,used,axis_value_weights(j,cfg,axis['name']),int((load_rne_timing(rp) or {}).get('rows') or 0))
 if not ap:
  raise RuntimeError(f"「{axis['name']}」を{used}つに分けられませんでした")
 saved_name=str(rowspec.get('axis_name') or '')
 if saved_name and axis['name']!=saved_name:
  # 軸が入れ替わったら、裏付けを取った条件と違う。落とさずに進めるが、必ず記録に残す。
  log.warning('SPLIT_RUN_AXIS_CHANGED line=%s job=%s 裏付けは「%s」で取りましたが、いまは「%s」が選ばれています',
              line,j.get('name'),saved_name,axis['name'])
 log.info('SPLIT_RUN_ROWAXIS line=%s job=%s 軸=%s（%s %s番目）いまの値=%s種 → %s分割 読み直し=%.2fs',
          line,j.get('name'),axis['name'],axis.get('location'),int(axis.get('index') or 0)+1,
          axis.get('category_count'),used,elapsed)
 for x in ap:
  log.info('SPLIT_RUN_ROWPART line=%s %s/%s %s 見込み%s行',line,x['index'],used,
           (f"期間 {x['row_axis']['from']}〜{x['row_axis']['to']}" if x['row_axis']['kind']=='period'
            else f"値{len(x['row_axis']['values'])}種"),x['row_axis'].get('expect_rows'))
 return axis,ap,elapsed

def _split_part_specs(kind,chosen,ap,work):
 """走らせる片の一覧。列だけ・行だけ・行×列の3通りを1か所で組み立てる。

 影実行と本番で組み立て方が分かれていると、測った形と走る形がずれる。ここに集約する。
 """
 plan=chosen.get('plan') or []
 if kind=='row':
  total=len(ap or [])
  specs=[{'index':x['index'],'label':f'行{x["index"]}/{total}','drop':[],'row_axis':x['row_axis'],
          'row_group':x['index'],'out_csv':Path(work)/f'row{x["index"]}.csv'} for x in (ap or [])]
  return specs,total,f'行{total}分割'
 if kind=='grid':
  specs=[]
  for x in (ap or []):
   for cp in plan:
    specs.append({'index':len(specs)+1,'label':f'行{x["index"]}×列{cp["index"]}','drop':list(cp.get('drop') or []),
                  'row_axis':x['row_axis'],'row_group':x['index'],'col_group':cp['index'],
                  'out_csv':Path(work)/f'g{x["index"]}_{cp["index"]}.csv'})
  return specs,len(specs),f'行{len(ap or [])}×列{len(plan)}'
 specs=[{'index':p['index'],'label':f'パート{p["index"]}/{len(plan)}','drop':list(p['drop']),
         'out_csv':Path(work)/f'part{p["index"]}.csv'} for p in plan]
 return specs,len(plan),f'列{len(plan)}分割'

def _merge_split_results(kind,specs,results,chosen,work,dest_csv):
 """片を1本へまとめる。行は縦に積み、列は横につなぐ。行×列はその両方。"""
 files=[r['file'] for r in results]
 if kind=='row':
  return merge_row_parts(files,Path(dest_csv))
 if kind=='grid':
  byrow={}
  for spec,r in zip(specs,results):byrow.setdefault(spec['row_group'],[]).append(r['file'])
  stitched=[]
  for g in sorted(byrow):
   out=Path(work)/f'rowgroup{g}.csv';merge_column_parts(byrow[g],out,chosen['keys'],chosen['columns']);stitched.append(out)
  return merge_row_parts(stitched,Path(dest_csv))
 return merge_column_parts(files,Path(dest_csv),chosen['keys'],chosen['columns'])

def run_split_extraction(j,cfg,user,pw,server,work,chosen,dest_csv,line='',stats=None):
 """保存済みの割り当てで分割抽出し、1本のCSVへ結合する。戻り値は (行数, 列数)。

 失敗したら例外を投げる。呼び出し側は分割なしでやり直す。公開するファイルを落とさないため、
 ここで無理に結果を作らない。行が食い違ったときは、その割り当てを以後使わないよう取り下げる。
 """
 rp=resolve_rne_path(j,cfg)
 kind=normalize_split_shape(chosen.get('mode'))
 started=time.perf_counter();axis_elapsed=0.0;row_axis=None
 if kind in ('row','grid'):
  # 値は日々増減する。保存した値で分けると新しい値の行が落ちるので、実行の直前に読み直す。
  row_axis,ap,axis_elapsed=_prepare_row_parts(j,cfg,rp,chosen,line)
 specs,total,shape_text=_split_part_specs(kind,chosen,locals().get('ap'),Path(work))
 timeout=int((cfg.get('settings') or {}).get('split_trial_timeout_seconds',1800) or 1800)
 update_parallel_line(line,job=j['name'],job_id=j['id'],state=f'{shape_text}で受信',percent=line_percent('transfer',0),
                      detail=f'{total}プロセス同時',phase='transfer')
 t=phase_log('split_extract',job=j['name'],line=line,mode=kind,parts=total)
 # パートのファイルを合算して進み具合を出す。1パートが運ぶ割合は分かっているので、見込みも出せる。
 # 行で分けた片は列を外さないので、合計は分割なしとほぼ同じ量になる。
 ratio=1.0 if kind=='row' else split_transfer_ratio(chosen['columns'],[],max(1,len(chosen['plan'])))
 want=int((_split_expect_bytes(j,cfg,rp) or 0)*ratio) or 0
 tick=growing_file_tick([str(x['out_csv']) for x in specs],want)
 extract_started=time.perf_counter()
 results=_spawn_racers(j,cfg,user,pw,server,Path(work),specs,timeout,
                       on_tick=lambda el,st:_line_tick(line,j,'transfer',tick,el,
                                                       f'{sum(1 for x in st if x["done"])}/{total}片'))
 bad=[r for r in results if not r.get('ok')]
 if bad:
  # 条件式が長すぎる＝この軸では二度と通らない。覚えておき、割り当ても取り下げる。
  # そのまま残すと毎回2分かけて拒否されるだけになる。
  toolong=[r for r in bad if r.get('filter_too_long')]
  if toolong and row_axis:
   block_row_axis(rp,row_axis.get('name',''),'本番の実行で検索条件式が長すぎるとサーバーに拒否されました',
                  server_message=str(toolong[0].get('error') or ''),parts=len(specs),
                  values=int(row_axis.get('category_count') or 0))
   drop_split_plans(rp,f'行の軸「{row_axis.get("name")}」が拒否されました（条件式が長すぎます）')
  raise RuntimeError('分割抽出に失敗: '+'; '.join(f'{r.get("part")}: {r.get("error")}' for r in bad))
 run_elapsed=time.perf_counter()-extract_started
 phase_log('split_extract',t,job=j['name'],line=line,mode=kind,parts=total,
           rows=max((r.get('rows') or 0) for r in results),bytes=sum((r.get('size') or 0) for r in results))
 update_parallel_line(line,job=j['name'],job_id=j['id'],state='結合',percent=68,
                      detail=('%d片を縦に積む'%total if kind=='row' else f'{total}片を結合'))
 t=phase_log('split_merge',job=j['name'],line=line,mode=kind)
 merge_started=time.perf_counter()
 try:
  rows,cols=_merge_split_results(kind,specs,results,chosen,Path(work),Path(dest_csv))
 except SplitRowsetMismatch as me:
  drop_split_plans(rp,f'実行時に行集合が食い違いました: {me}')
  raise
 phase_log('split_merge',t,job=j['name'],line=line,mode=kind,rows=rows,columns=cols)
 merge_elapsed=time.perf_counter()-merge_started
 # サーバ側の実行はパートごとに満額かかるので、内訳は「一番遅いパート」で見るのが実態に近い。
 slowest=max(results,key=lambda r:r.get('elapsed') or 0)
 if stats is not None:
  stats.update(transfer_bytes=sum((r.get('size') or 0) for r in results),
               transfer_seconds=round(max((r.get('save_elapsed') or 0) for r in results),2),
               execute_seconds=round(max((r.get('execute_elapsed') or 0) for r in results),2),
               merge_seconds=round(merge_elapsed,2),parts=total,split_shape=kind,
               axis_seconds=round(axis_elapsed,2) if axis_elapsed else None,
               row_axis=(row_axis or {}).get('name',''))
 log.info('SPLIT_RUN_DONE line=%s job=%s rne=%s 形=%s 片数=%s rows=%s cols=%s 軸読み=%.2fs 抽出=%.2fs 結合=%.2fs 最遅=%s(実行%.2fs+保存%.2fs) 合計転送=%.1fMB',
          line,j['name'],rp,shape_text,total,rows,cols,axis_elapsed,run_elapsed,merge_elapsed,slowest.get('part'),
          slowest.get('execute_elapsed') or 0,slowest.get('save_elapsed') or 0,
          sum((r.get('size') or 0) for r in results)/1024/1024)
 return rows,cols

def run_race_extraction(j,cfg,user,pw,server,work,chosen,dest_csv,line='',stats=None):
 """分割なし1本と、分割Nパートを同時に走らせ、先に使える形になった方を採る。

 分割側は結合まで終えて初めて「使える形」になる。パートが出そろった時点では勝ちではない。
 そこで、パートが先に出そろったら結合へ進みつつ、分割なしはそのまま走らせておく。
 結合が終わった時点で分割なしも終わっていたら、実際に早かった方を採る。

 負けた側は NaviTerminateDL 相当（プロセスの中断）で降ろし、成果物は捨てる。
 戻り値は (行数, 列数, 勝者, 記録) 。勝者は 'normal' か 'split'。
 """
 rp=resolve_rne_path(j,cfg)
 kind=normalize_split_shape(chosen.get('mode'))
 axis_elapsed=0.0;row_axis=None;ap=None
 if kind in ('row','grid'):
  row_axis,ap,axis_elapsed=_prepare_row_parts(j,cfg,rp,chosen,line)
 part_specs,total,shape_text=_split_part_specs(kind,chosen,ap,Path(work))
 normal_csv=Path(work)/'normal.csv'
 specs=[{'index':0,'label':'分割なし','group':'normal','drop':[],'out_csv':normal_csv}]
 for x in part_specs:specs.append(dict(x,group='split'))
 timeout=int((cfg.get('settings') or {}).get('split_trial_timeout_seconds',1800) or 1800)
 started=time.perf_counter()
 update_parallel_line(line,job=j['name'],job_id=j['id'],state=f'競争（1本 対 {shape_text}）',percent=40,
                      detail=f'{total+1}プロセス同時')
 log.info('RACE_START line=%s job=%s rne=%s racers=%s（分割なし1本 ＋ %s）',line,j['name'],rp,total+1,shape_text)
 racetick=growing_file_tick([str(x['out_csv']) for x in specs],0)
 # どちらかの側が出そろった時点で決着。負けた側はそこで降ろす。
 # 分割側はこのあと結合の時間（実測で3〜6秒）を払う。それでも待たせないのは、
 # パートが出そろった時点で分割なしはまだ大きく遅れているため（負けた側だから遅れている）。
 def settled(done):
  if any(r.get('group')=='normal' and r.get('ok') for r in done):return True
  return sum(1 for r in done if r.get('group')=='split' and r.get('ok'))>=total
 t=phase_log('race_extract',job=j['name'],line=line,racers=total+1)
 results=_spawn_racers(j,cfg,user,pw,server,Path(work),specs,timeout,stop_when=settled,
                       on_tick=lambda el,st:_line_tick(line,j,'transfer',racetick,el,
                                                       f'{sum(1 for x in st if x["done"])}/{total+1}本 決着'))
 run_elapsed=time.perf_counter()-started
 normal=next((r for r in results if r.get('group')=='normal'),{})
 # 結合は投入順に依存する（行×列はどの行の組かで束ねる）。返ってきた順ではなく、投入順に並べ直す。
 order={x['label']:i for i,x in enumerate(part_specs)}
 pres=sorted([r for r in results if r.get('group')=='split'],key=lambda r:order.get(r.get('part'),0))
 phase_log('race_extract',t,job=j['name'],line=line,racers=total+1,
           normal='ok' if normal.get('ok') else 'x',parts_ok=sum(1 for r in pres if r.get('ok')))
 order=' / '.join(f"{r.get('part')}={r.get('finished_at')}s" + ('' if r.get('ok') else '(中断)' if r.get('aborted') else '(失敗)')
                  for r in sorted(results,key=lambda r:r.get('finished_at') or 0))
 log.info('RACE_ORDER line=%s job=%s %s',line,j['name'],order)
 if normal.get('ok'):
  # 分割なしが先着。パートは中断済み。結合の手間もかからない分、ここが最短。
  log.info('RACE_WINNER line=%s job=%s winner=normal 所要=%.2fs rows=%s パートは中断',
           line,j['name'],run_elapsed,normal.get('rows'))
  shutil.copyfile(normal['file'],Path(dest_csv))
  if stats is not None:
   stats.update(transfer_bytes=normal.get('size') or 0,transfer_seconds=round(normal.get('save_elapsed') or 0,2),
                execute_seconds=round(normal.get('execute_elapsed') or 0,2),merge_seconds=0,parts=total,winner='normal',
                split_shape=kind,axis_seconds=round(axis_elapsed,2) if axis_elapsed else None)
  return normal.get('rows'),normal.get('cols'),'normal',{'elapsed':round(run_elapsed,2),'results':results}
 bad=[r for r in pres if not r.get('ok')]
 if bad:raise RuntimeError('競争の両方が失敗しました: '+'; '.join(f'{r.get("part")}: {r.get("error")}' for r in bad)
                           +f'; 分割なし: {normal.get("error")}')
 update_parallel_line(line,job=j['name'],job_id=j['id'],state='結合',percent=68,
                      detail=('%d片を縦に積む'%total if kind=='row' else f'{total}片を結合'))
 t=phase_log('split_merge',job=j['name'],line=line,mode=kind)
 try:
  # 走らせた順と結果の順は同じ。行×列の結合は「どの行の組か」を要るので、片の指定を添える。
  rows,cols=_merge_split_results(kind,part_specs,pres,chosen,Path(work),Path(dest_csv))
 except SplitRowsetMismatch as me:
  drop_split_plans(rp,f'実行時に行集合が食い違いました: {me}')
  raise
 phase_log('split_merge',t,job=j['name'],line=line,mode=kind,rows=rows,columns=cols)
 total_elapsed=time.perf_counter()-started
 if stats is not None:
  stats.update(transfer_bytes=sum((r.get('size') or 0) for r in pres),
               transfer_seconds=round(max((r.get('save_elapsed') or 0) for r in pres),2),
               execute_seconds=round(max((r.get('execute_elapsed') or 0) for r in pres),2),
               merge_seconds=round(total_elapsed-run_elapsed,2),parts=total,winner='split',
               split_shape=kind,axis_seconds=round(axis_elapsed,2) if axis_elapsed else None,
               row_axis=(row_axis or {}).get('name',''))
 log.info('RACE_WINNER line=%s job=%s winner=split 所要=%.2fs（抽出%.2fs＋結合%.2fs） rows=%s cols=%s 分割なしは中断',
          line,j['name'],total_elapsed,run_elapsed,total_elapsed-run_elapsed,rows,cols)
 return rows,cols,'split',{'elapsed':round(total_elapsed,2),'results':results}

def finish_one_job(j,cfg,*,intermediate,db,target,backup,out_dir,local_export,stamp,
                   expected_rows,expected_cols,fmt,extras,api_direct_output,job_started,
                   line='',report=None,on_published=None):
 """1つの対象を仕上げる後半。中間データを受け取り、変換 → 公開 → 同時出力 までを行う。

 ここは以前、直列（process）と並列（process_api_parallel_job）に同じ手順が二重に
 書かれていた。片方だけ直った不具合が繰り返し出ていたのが、分けておく理由より重かった。
   ・「前回と同じなら更新しない」がAPI経路にしか無く、DDE互換方式では黙って無視されていた（v1.65.1）
   ・ACCDBのAccess起動待ちの先読みが直列にしか無く、並列ワーカーで抜けていた（v1.66.0）
   ・公開できたか（published／pending）を、v1.68.0では2か所へ別々に足す必要があった
 方式によって違うのは「進み具合の見せ方」だけなので、そこは report() に預ける。

 report(段階, **詳細) で呼ぶ段階:
   convert_start … 変換に入る直前（並列はここでラインの状態を更新する）
   unchanged     … 前回と同じ内容だったので、変換も公開もしなかった
   convert       … 変換の直前（直列はここで進捗を出す）
   publish       … 公開の直前
   extras        … 同時出力の直前
 on_published() は公開の直後に呼ぶ（並列はここでACCDBの温めスレッドを待ち合わせる）。

 返すもの:
   unchanged … 前回と同じ内容で、何も書き換えなかった
   rows/cols … 実際に書き出した件数・列数
   published … 共有先を差し替えられたか
   pending   … 差し替えられなかったときの控えの場所
   extra_results／total／digest
 """
 def say(stage,**kw):
  if report:report(stage,**kw)
 def plog(*a,**kw):
  # ログの見え方を方式で変えない。並列だけが line= を持つのは従来どおり。
  if line:kw['line']=line
  return phase_log(*a,**kw)
 say('convert_start')
 # 前回と中身が同じなら、変換も公開もしない。公開先（多くはネットワーク共有）への
 # 書き込みが消え、ロック衝突の窓そのものが無くなり、控えの世代が同じ中身で埋まらない。
 # ただし出力の「作成日時」は進まなくなるので、対象ごとに選んでもらう（既定は従来どおり）。
 digest=intermediate_fingerprint(intermediate) if j.get('skip_if_unchanged') else ''
 if digest and not extras and unchanged_since_last(target,digest):
  total=time.perf_counter()-job_started
  if line:log.info('PUBLISH_SKIPPED_UNCHANGED line=%s job=%s target=%s digest=%s elapsed=%.2fs',line,j['name'],target,digest[:12],total)
  else:log.info('PUBLISH_SKIPPED_UNCHANGED job=%s target=%s digest=%s elapsed=%.2fs',j['name'],target,digest[:12],total)
  say('unchanged',total=total)
  return {'unchanged':True,'rows':int(expected_rows or 0),'cols':int(expected_cols or 0),
          'published':True,'pending':'','extra_results':[],'total':total,'digest':digest}
 # 同時出力があるときは、中間データの解析をここで1回だけ行い、全形式で使い回す。
 shared=None
 if extras and not api_direct_output:
  parse_started=plog('intermediate_parse',job=j['name'],source=intermediate,shared_by=len(extras)+1)
  shared=read_extract(intermediate,j,bool(cfg['settings']['reject_zero_rows']),expected_rows,expected_cols)
  plog('intermediate_parse',parse_started,job=j['name'],rows=len(shared[1]),columns=len(shared[0]),shared_by=len(extras)+1)
 say('convert',direct=api_direct_output)
 if api_direct_output:
  t=plog('format_conversion',job=j['name'],format=fmt,mode='api_direct_xlsx');nr,nc=int(expected_rows),int(expected_cols);plog('format_conversion',t,job=j['name'],format=fmt,mode='api_direct_xlsx',rows=nr,columns=nc)
 else:
  t=plog('format_conversion',job=j['name'],format=fmt);nr,nc=export_data(intermediate,db,j,bool(cfg['settings']['reject_zero_rows']),expected_rows,expected_cols,data=shared);plog('format_conversion',t,job=j['name'],format=fmt,rows=nr,columns=nc)
 say('publish')
 t=plog('publish',job=j['name']);pub=publish(db,target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations')));plog('publish',t,job=j['name'],published=pub['published'])
 if digest:remember_published(target,digest,nr,nc)
 if on_published:on_published()
 extra_results=[]
 if extras:
  say('extras')
  extra_results=publish_extra_formats(j,cfg,intermediate,out_dir,local_export,backup,stamp,line,data=shared)
 shared=None   # 大きい対象では中間データだけで数百MBになる。次の対象へ持ち越さない。
 return {'unchanged':False,'rows':nr,'cols':nc,
         'published':bool(pub['published']),'pending':str(pub.get('pending') or ''),
         'extra_results':extra_results,'total':time.perf_counter()-job_started,'digest':digest}

def process_api_parallel_job(j,job_index,total_jobs,cfg,user,pw,server,dde_work,backup):
 from navigator_api import NavigatorApi
 line_name=os.environ.get('NAVI_WORKER_LINE') or threading.current_thread().name
 job_started=time.perf_counter();api_client=None;api_csv=None;xls=None;db=None
 phase_profile_reset()
 # ワーカー1本ぶんの起動代。app.pyはBOX上にあるため、環境によってはここだけで数秒かかる。
 try:_worker_spawn_at=float(os.environ.get('NAVI_WORKER_SPAWN_AT') or 0)
 except Exception:_worker_spawn_at=0
 # 版も出す。BOX上のapp.pyを差し替えた直後は、親と子で違う版が動き得る
 # （親は差し替え前に読み込み済み、子はこれから読む）。後から突き合わせられるようにする。
 if _worker_spawn_at:log.info('WORKER_READY line=%s job=%s version=%s spawn_to_import=%.2fs import_to_job=%.2fs note=interpreter_init+module_import(BOX)',line_name,j.get('name'),BUILD_VERSION,_APP_IMPORT_DONE_AT-_worker_spawn_at,time.time()-_APP_IMPORT_DONE_AT)
 try:
  _preflight_started=time.perf_counter()
  j['output_file']=resolve_output_filename(j,cfg); log.info('OUTPUT_NAME line=%s job=%s mode=%s pattern=%s resolved_file=%s',line_name,j.get('name'),j.get('naming_mode','fixed'),j.get('output_pattern',''),j['output_file'])
  fmt=validate_output_contract(j,'before-extraction')
  j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb')))
  rp=resolve_rne_path(j,cfg);out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']);target=out_dir/j['output_file']
  # 保留ファイルの確認・適用は公開先(ネットワーク共有)への操作。抽出前の待ちとして別枠で計上する。
  _pending_started=time.perf_counter()
  apply_pending(target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations')))
  _pending_elapsed=time.perf_counter()-_pending_started;phase_profile_add('pending_apply',_pending_elapsed)
  if not rp.is_file():raise FileNotFoundError('RNEがありません: '+str(rp))
  stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+f'_L{job_index}'
  xls=dde_work/f'navi_{job_index}_{stamp}.xls';local_export=dde_work/'export';local_export.mkdir(parents=True,exist_ok=True)
  db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'
  # 同時に出す形式があるなら、共通の中間データ(CSV)を必ず通す。XLSXの直接受信は速いが、
  # 受け取ったXLSXからは他の形式へ作り直せないので、1回の抽出で複数形式を出せなくなる。
  extras=job_extra_formats(j)
  # ACCDBはAccessを起動して書き込む。その起動だけで数秒かかる（実測 2026-08-12: 2.21s）。
  # 抽出（十数秒）と同時に温めておけば、変換に入るころには終わっている。
  # 直列の経路では以前からやっていたが、並列ワーカーでは抜けていた。
  accdb_prewarm=prewarm_access_async('parallel_worker_accdb') if (fmt=='accdb' or 'accdb' in extras) else None
  allow_direct_xlsx=(fmt=='xlsx' and not extras)
  common_intermediate='API_DIRECT_XLSX' if allow_direct_xlsx else 'CSV'
  planned=db if allow_direct_xlsx else dde_work/f'navi_{job_index}_{stamp}.csv'
  if extras:
   log.info('MULTI_FORMAT job=%s primary=%s extras=%s intermediate=CSV note=抽出は1回のまま変換と公開だけを繰り返します',j['name'],fmt,','.join(extras))
  phase_profile_add('job_preflight',max(0.0,time.perf_counter()-_preflight_started-_pending_elapsed))
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='開始',percent=line_percent('session',0),detail=fmt,phase='session');log.info('PARALLEL_JOB_START line=%s job=%s index=%s/%s format=%s target=%s',line_name,j['name'],job_index,total_jobs,fmt,target)
  log.info('PIPELINE job=%s engine=api parallel_line=%s common_intermediate=%s format=%s planned_intermediate=%s converted=%s target=%s',j['name'],line_name,common_intermediate,fmt,planned,db,target)
  # 分割して取るか、そのまま取るか。判断は保存済みの裏付けだけで行い、ここでは測定しない。
  split_used=None;split_reason='';intermediate=None;api_direct_output=False;race_winner='';run_stats={}
  try:split_used,split_reason=plan_run_split(rp,j,cfg,fmt,int(j.get('_split_budget') or 1),line_name)
  except Exception as se:
   split_used=None;split_reason=f'判断に失敗しました: {se}';log.warning('SPLIT_RUN_PLAN_FAILED line=%s job=%s error=%s',line_name,j.get('name'),se)
  if not split_used:log.info('SPLIT_RUN_SKIP line=%s job=%s rne=%s 理由=%s',line_name,j.get('name'),rp,split_reason)
  if split_used:
   split_work=dde_work/f'split_{job_index}_{stamp}';split_work.mkdir(parents=True,exist_ok=True)
   api_csv=dde_work/f'navi_{job_index}_{stamp}.csv'
   try:
    if split_used.get('race'):
     expected_rows,expected_cols,race_winner,_rd=run_race_extraction(j,cfg,user,pw,server,split_work,split_used,api_csv,line_name,run_stats)
    else:
     expected_rows,expected_cols=run_split_extraction(j,cfg,user,pw,server,split_work,split_used,api_csv,line_name,run_stats)
    intermediate=api_csv
   except Exception as spe:
    # 公開するファイルを落とさないことを最優先にする。分割で転んだら、そのまま1本で取り直す。
    log.warning('SPLIT_RUN_FALLBACK line=%s job=%s rne=%s error=%s 分割なしでやり直します',line_name,j.get('name'),rp,spe)
    update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='分割なしで再実行',percent=20,detail=str(spe)[:80])
    split_used=None;intermediate=None
    try:
     if api_csv.exists():api_csv.unlink()
    except Exception:pass
   finally:
    shutil.rmtree(split_work,ignore_errors=True)
  if intermediate is None:
   _dll_started=time.perf_counter();api_client=NavigatorApi(resolve_path(cfg['symnavi_exe']),log,resolve_path(cfg.get('navigator_api_dll')) if cfg.get('navigator_api_dll') else None,base_dir=BASE,search_roots=dll_search_roots(cfg));phase_profile_add('api_load_dll',time.perf_counter()-_dll_started)
   update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='API接続',percent=line_percent('session',0.4),detail='セッション接続',phase='session');session_started=time.perf_counter();session_elapsed=api_client.open_session(user,pw,server);phase_profile_add('api_open_session',session_elapsed);log.info('PARALLEL_API_SESSION line=%s job=%s dll=%s elapsed=%.2fs is_opened=1',line_name,j['name'],api_client.dll_path,session_elapsed)
   profiles=api_data_source_profiles(resolve_path(cfg['symnavim_conf']))
   if not any(p.get('kind')=='oracle' for p in profiles):
    profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0','credential_source':'navigator_session'})
    log.info('API Oracle接続設定未指定。Navigator認証を1回だけ流用 line=%s job=%s credential_source=navigator_session user_configured=%s password_configured=%s',line_name,j['name'],bool(user),bool(pw))
   for profile in profiles:
    source=profile.get('credential_source') or 'explicit_config'
    elapsed=api_client.connect_data_source(profile);phase_profile_add('api_connect_source',elapsed)
    log.info('APIデータソース接続完了 line=%s job=%s section=%s kind=%s credential_source=%s elapsed=%.2fs',line_name,j['name'],profile['section'],profile['kind'],source,elapsed)
   api_rne=rp.resolve();rne_stat=api_rne.stat()
   with chdir_lock:
    previous_cwd=os.getcwd()
    try:
     os.chdir(api_rne.parent)
     log.info('APIカタログ読込条件 line=%s dll=%s cwd=%s catalog_full=%s catalog_name=%s extension=%s size=%s mtime_ns=%s strategy=original_fullpath',line_name,api_client.dll_path,os.getcwd(),api_rne,api_rne.name,api_rne.suffix,rne_stat.st_size,rne_stat.st_mtime_ns)
     t=phase_log('api_open_catalog',job=j['name'],line=line_name);handle,api_elapsed=api_client.open_catalog(api_rne);phase_log('api_open_catalog',t,job=j['name'],line=line_name,handle=handle,api_elapsed=f'{api_elapsed:.2f}s',strategy='original_fullpath')
    finally:os.chdir(previous_cwd)
   if (j.get('period') or {}).get('enabled'):update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='期間指定',percent=line_percent('session',0.9),detail='相対期間を適用',phase='session');apply_dynamic_period(api_client,handle,j,datetime.now(),line=line_name)
   # 前回の実績。工程ごとの見込みに使う（無ければ見当なしで、秒だけを刻む）。
   _tm=load_rne_timing(rp) or {};_lastrun=(load_job_runs().get(j['id']) or {}).get('metrics') or {}
   _expect_bytes=int(_lastrun.get('transfer_bytes') or 0) or split_expected_bytes(rp,j,cfg)
   _expect_rows=_tm.get('rows') or 0
   update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='問い合わせ実行',percent=line_percent('execute',0),detail='サーバー側で問い合わせを実行中',phase='execute')
   t=phase_log('api_execute_catalog',job=j['name'],line=line_name)
   with line_ticker(line_name,j,'execute',elapsed_tick(_tm.get('execute'),'問い合わせ実行',f'前回 {int(_expect_rows):,}件' if _expect_rows else '')):
    api_number,api_elapsed=api_client.execute(handle)
   phase_log('api_execute_catalog',t,job=j['name'],line=line_name,number=api_number,api_elapsed=f'{api_elapsed:.2f}s',rows_per_sec=f'{api_number/api_elapsed:.0f}' if api_elapsed>0 else '0')
   t=phase_log('api_get_dimensions',job=j['name'],line=line_name);expected_rows,expected_cols=api_client.dimensions(handle);phase_log('api_get_dimensions',t,job=j['name'],line=line_name,rows=expected_rows,columns=expected_cols)
   api_direct_output=False
   if allow_direct_xlsx:
    update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='受信・保存',percent=line_percent('transfer',0),detail='XLSXを直接受信',phase='transfer')
    try:
     if db.exists():
      try:db.unlink()
      except:pass
     save_wall_started=time.perf_counter();t=phase_log('api_save_xlsx_direct',job=j['name'],line=line_name,target=db,repeat='NAVI_NONREPEAT',ftype='NAVI_XLSX')
     with line_ticker(line_name,j,'transfer',growing_file_tick(db,_expect_bytes)):
      save_elapsed=api_client.save_xlsx(handle,db)
     save_wall_elapsed=time.perf_counter()-save_wall_started;phase_log('api_save_xlsx_direct',t,job=j['name'],line=line_name,api_elapsed=f'{save_elapsed:.2f}s',wall_elapsed=f'{save_wall_elapsed:.2f}s',size=db.stat().st_size if db.exists() else 0,throughput_kb_s=f'{(db.stat().st_size/1024/save_wall_elapsed):.1f}' if db.exists() and save_wall_elapsed>0 else '0')
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
    update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='受信・保存',percent=line_percent('transfer',0),detail='受信待ち',phase='transfer')
    api_csv=dde_work/f'navi_{job_index}_{stamp}.csv'
    t=phase_log('api_save_csv',job=j['name'],line=line_name)
    with line_ticker(line_name,j,'transfer',growing_file_tick(api_csv,_expect_bytes)):
     save_elapsed=api_client.save_csv(handle,api_csv)
    phase_log('api_save_csv',t,job=j['name'],line=line_name,api_elapsed=f'{save_elapsed:.2f}s',**save_metrics(api_csv,save_elapsed,expected_rows))
    if not api_csv.is_file() or api_csv.stat().st_size<=0:raise RuntimeError(f'API中間CSVが作成されませんでした: {api_csv}')
    intermediate=api_csv
   t=phase_log('api_close_catalog',job=j['name'],line=line_name);api_client.close_catalog();phase_log('api_close_catalog',t,job=j['name'],line=line_name)
  # 仕上げ（変換 → 公開 → 同時出力）は直列と同じ関数で行う。見せ方だけをここで足す。
  def _report(stage,**kw):
   if stage=='convert_start':update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='変換・検証',percent=line_percent('convert',0),detail=f'{fmt.upper()}へ変換中 · {int(expected_rows or 0):,}件',phase='convert')
   elif stage=='unchanged':update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='変更なし',percent=100,detail='前回と同じ内容のため更新しませんでした',elapsed=round(kw['total'],1))
   elif stage=='publish':update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='公開',percent=line_percent('publish',0),detail=f'{Path(target).name} へ公開中',phase='publish')
   elif stage=='extras':update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='同時出力',percent=line_percent('publish',0.6),detail=f'あと{len(extras)}形式を同じデータから作成中',phase='publish')
  def _joined():
   if accdb_prewarm is not None:
    join_started=time.perf_counter();alive=accdb_prewarm.is_alive();accdb_prewarm.join(timeout=2.0)
    log.info('ACCDB_PREWARM_JOIN line=%s alive_before=%s alive_after=%s elapsed=%.2fs',line_name,alive,accdb_prewarm.is_alive(),time.perf_counter()-join_started)
  fin=finish_one_job(j,cfg,intermediate=intermediate,db=db,target=target,backup=backup,out_dir=out_dir,
                     local_export=local_export,stamp=stamp,expected_rows=expected_rows,expected_cols=expected_cols,
                     fmt=fmt,extras=extras,api_direct_output=api_direct_output,job_started=job_started,
                     line=line_name,report=_report,on_published=_joined)
  if fin['unchanged']:
   total=fin['total']
   _tm2=load_rne_timing(rp) or {}
   return {'ok':True,'job':j['name'],'format':fmt,'rows':fin['rows'],'columns':fin['cols'],
           'elapsed':total,'target':str(target),'unchanged':True,
           'result':f'{j["name"]}: 前回と同じ内容のため更新しませんでした / {total:.1f}秒',
           'column_names':[],'rne_path':str(rp),'extra_formats':[],
           'split_parts':0,'split_shape':'','split_how':'','row_axis':'','axis_seconds':None,
           'split_reason':'','race_winner':'','execute_seconds':0,'save_seconds':0,
           'total_seconds':round(total,2),'transfer_bytes':0,'merge_seconds':0,'transfer_kbs':None}
  nr,nc=fin['rows'],fin['cols'];pub={'published':fin['published'],'pending':fin['pending']}
  extra_results=fin['extra_results'];total=fin['total']
  update_parallel_line(line_name,job=j['name'],job_id=j['id'],state='完了',percent=100,detail=f'{nr}件/{nc}列',elapsed=round(total,1));log.info('PARALLEL_JOB_RESULT line=%s job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s published=%s',line_name,j['name'],fmt,nr,nc,total,target,pub['published'])
  log.info('JOB_PROFILE line=%s job=%s rows=%s columns=%s %s',line_name,j['name'],nr,nc,phase_profile_summary())
  # 何分割で取れたのかは、結果の1行から分かるようにする。形（列/行/行×列）も添える。
  split_shape_text=(split_shape_label(split_used['mode'],len(split_used['plan']) or split_used['parts'],
                                      (split_used.get('row') or {}).get('parts',0)) if split_used else '')
  split_label=('' if not split_used else
               (f' / 競争は{"分割なし" if race_winner=="normal" else split_shape_text}の勝ち' if race_winner
                else f' / {split_shape_text}'))
  result=f'{j["name"]}: {nr}件/{nc}列 / {total:.1f}秒'+split_label+('' if pub['published'] else f' / 更新保留: {pub["pending"]}')+extra_format_note(extra_results)
  # 列名はここでしか分からないので、作業ファイルの見出しだけ読んで持ち帰る。書き込みは親プロセスが行う
  # （ワーカーが同時に設定DBへ書くと競合するため）。失敗しても抽出結果には影響させない。
  column_names=[]
  try:
   state,_cached=column_cache_state(rp)
   if state!='hit':
    read_started=time.perf_counter();column_names=read_header_names(db,j)
    log.info('COLUMN_CACHE_READ line=%s job=%s state=%s columns=%s file=%s elapsed=%.2fs',line_name,j['name'],state,len(column_names),db.name,time.perf_counter()-read_started)
  except Exception as ce:
   log.warning('COLUMN_CACHE_READ_FAILED line=%s job=%s error=%s',line_name,j['name'],ce)
  ph=_phase_profile.get('phases') or {}
  # 転送の内訳。分割なしは工程プロファイルから、分割・競争は各パートの実測から取る。
  execute_s=run_stats.get('execute_seconds',round(float(ph.get('api_execute_catalog') or 0),2))
  save_s=run_stats.get('transfer_seconds',round(float(ph.get('api_save_csv') or ph.get('api_save_xlsx_direct') or 0),2))
  tbytes=run_stats.get('transfer_bytes')
  if tbytes is None:
   try:tbytes=Path(intermediate).stat().st_size if intermediate and Path(intermediate).is_file() else 0
   except Exception:tbytes=0
  return {'ok':True,'job':j['name'],'format':fmt,'rows':nr,'columns':nc,'elapsed':total,'target':str(target),'result':result,
          # 公開できたかどうかは実績の文字列にしか残っていなかった。共有先が使用中で
          # 差し替えられなかったことに気づけるよう、値としても持ち帰る。
          'published':bool(pub['published']),'pending':str(pub.get('pending') or ''),
          'column_names':column_names,'rne_path':str(rp),'extra_formats':extra_results,
          'split_parts':(int(run_stats.get('parts') or 0) or (len(split_used['plan']) if split_used else 0)) if split_used else 0,
          'split_shape':(split_used['mode'] if split_used else ''),'split_how':split_shape_text if split_used else '',
          'row_axis':run_stats.get('row_axis') or '','axis_seconds':run_stats.get('axis_seconds'),
          'split_reason':split_reason,'race_winner':race_winner,
          'execute_seconds':execute_s,'save_seconds':save_s,'total_seconds':round(total,2),
          'transfer_bytes':int(tbytes or 0),'merge_seconds':run_stats.get('merge_seconds',0),
          'transfer_kbs':round((tbytes or 0)/1024/save_s,1) if save_s else None}
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


def relay_worker_line(line,job,worker_status,elapsed,pid=0):
 """ワーカーが書いた状態を、そのまま画面のラインへ渡す。

 決め打ちで項目を拾い直さないこと。以前ここで列挙していたため、あとから増えた項目
 （工程の点=phase、実測かどうか=measured）が画面まで届かず、点が光らなかった。
 親が決めるのは所要時間と対象IDだけで、あとはワーカーの言うとおりにする。
 """
 relay={k:v for k,v in (worker_status or {}).items() if k not in ('line','elapsed','updated_at','job_id')}
 relay.setdefault('state','処理中');relay.setdefault('percent',0);relay.setdefault('detail','')
 relay['job']=relay.get('job') or (job or {}).get('name','')
 if pid:relay.setdefault('pid',pid)
 update_parallel_line(line,job_id=(job or {}).get('id',''),elapsed=elapsed,**relay)
 return relay

def _read_worker_json(path,default=None):
 try:return json.loads(Path(path).read_text(encoding='utf-8'))
 except Exception:return default

def run_api_process_batch(jobs,cfg,user,pw,server,dde_work,backup,max_lines,trigger):
 """Run each Navigator API session in an isolated Python process.
 Finished lines immediately pull the next queued query until the reservation queue is empty.
 """
 batch_id=datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8]
 runtime=dde_work/'parallel_runtime'/('parallel_'+batch_id);runtime.mkdir(parents=True,exist_ok=True)
 # 重い対象から先に流す。バッチ全体の所要は一番重い対象で決まるため、それを最初に走らせないと
 # 後ろに回った分だけ全体が延びる。規模は前回実績の 行数×列数 を目安にする（実績が無い対象は
 # 大きさが読めないので先に始める）。並列実行では対象の順序自体に意味は無い。
 if len(jobs)>1:
  runs=load_job_runs()
  def _estimated_cells(job):
   run=runs.get(job.get('id')) or {}
   try:cells=int(run.get('rows') or 0)*int(run.get('cols') or 0)
   except Exception:cells=0
   return cells if cells>0 else float('inf')
  jobs=sorted(jobs,key=_estimated_cells,reverse=True)
  log.info('BATCH_ORDER strategy=heaviest_first order=%s',[(j['name'],'不明' if _estimated_cells(j)==float('inf') else int(_estimated_cells(j))) for j in jobs])
 queue=deque(enumerate(jobs,1));active={};results=[];failures=[];completed=0
 # 各対象(ジョブ)の実状態を job_id 単位で保持し、完了後に「待機」へ戻る不具合を防ぐ。
 completed_ids=[];failed_ids=[];all_job_ids=[j['id'] for j in jobs]
 with active_workers_lock:active_workers.clear()
 batch_started=time.perf_counter(); total=len(jobs); configured_lines=max(1,int(max_lines)); max_lines=max(1,min(int(max_lines),total)); batch_results=[]
 # 列分割は同時プロセスを増やす。設定した並列数を超えないよう、1対象あたりの持ち分を先に決める。
 # 対象がラインを埋め切っているときは持ち分が1になり、分割は行われない。
 split_budget=max(1,configured_lines//total)
 log.info('SPLIT_BUDGET configured_lines=%s jobs=%s per_job=%s',configured_lines,total,split_budget)
 for _j in jobs:_j['_split_budget']=split_budget
 set_status(parallel_lines=[{'line':f'ライン {n}','job':'','state':'待機','percent':0,'elapsed':0,'detail':'開始待ち','slot':n} for n in range(1,max_lines+1)],queue_total=total,queue_waiting=total,queue_active=0,queue_completed=0,queue_completed_ids=[],queue_failed_ids=[],queue_running_ids=[],queue_waiting_ids=list(all_job_ids),parallel_max_lines=max_lines,parallel_mode=True,symnavi_window=f'独立プロセス {max_lines}ライン')
 log.info('PARALLEL_BATCH_START model=process-isolated trigger=%s batch_id=%s runtime=%s jobs=%s max_lines=%s total_jobs=%s parent_pid=%s',trigger,batch_id,runtime,[j['rne'] for j in jobs],max_lines,total,os.getpid())
 def start_one(slot):
  index,job=queue.popleft();line=f'ライン {slot}'
  job_dir=runtime/f'line_{slot}_{index}';job_dir.mkdir(parents=True,exist_ok=True)
  payload={'job':job,'job_index':index,'total_jobs':total,'cfg':cfg,'user':user,'password':pw,'server':server,'dde_work':str(job_dir/'work'),'backup':str(backup),'line':line}
  Path(payload['dde_work']).mkdir(parents=True,exist_ok=True)
  payload_path=job_dir/'payload.json';result_path=job_dir/'result.json';status_path=job_dir/'status.json'
  payload_path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
  env=os.environ.copy();env['NAVI_WORKER_LINE']=line;env['NAVI_WORKER_STATUS']=str(status_path);env['NAVI_WORKER_RESULT']=str(result_path);env['NAVI_WORKER_SPAWN_AT']=repr(time.time())
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  proc=subprocess.Popen([sys.executable,str(BASE/'api_worker.py'),str(payload_path)],cwd=str(BASE),env=env,creationflags=flags)
  active[slot]={'proc':proc,'job':job,'index':index,'line':line,'status':status_path,'result':result_path,'started':time.perf_counter()}
  with active_workers_lock:active_workers[slot]=proc
  update_parallel_line(line,job=job['name'],job_id=job['id'],state='起動',percent=2,detail=f'予約 {index}/{total} / PID {proc.pid}',queue_index=index,slot=slot,started_at=datetime.now().isoformat(timespec='seconds'))
  log.info('WORKER_START batch_id=%s line=%s pid=%s job=%s queue_index=%s/%s',batch_id,line,proc.pid,job['name'],index,total)
 # ワーカーを一斉に起動すると、Navigator APIのセッション接続が競合して1本あたりの接続時間が
 # 数倍に伸びる（実測: 単独 約1.0秒 / 6本同時 2.3〜7.2秒）。少しずつずらして接続を重ねない。
 # 一番重い対象が先頭なので、遅れて起動する軽い対象は全体所要に影響しない。
 stagger=max(0,int(cfg['settings'].get('api_worker_stagger_ms',700) or 0))/1000.0
 for slot in range(1,max_lines+1):
  if not queue:break
  if slot>1 and stagger>0 and cancel_requested.wait(stagger):break
  start_one(slot)
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
    failed_ids.append(item['job']['id'])
    record_job_run(item['job']['id'],item['job']['name'],'cancelled',trigger,detail='ユーザーにより中断されました')
    update_parallel_line(item['line'],job=item['job']['name'],job_id=item['job']['id'],state='中断',percent=100,detail='ユーザーにより中断されました',elapsed=round(time.perf_counter()-item['started'],1))
    with active_workers_lock:active_workers.pop(slot,None)
    del active[slot]
   break
  for slot,item in list(active.items()):
   worker_status=_read_worker_json(item['status'])
   if worker_status:
    relay_worker_line(item['line'],item['job'],worker_status,
                      round(time.perf_counter()-item['started'],1),item['proc'].pid)
   rc=item['proc'].poll()
   if rc is None:continue
   result=_read_worker_json(item['result'],{'ok':False,'job':item['job']['name'],'error':f'Worker終了コード {rc}','elapsed':time.perf_counter()-item['started']})
   completed+=1
   (results if result.get('ok') else failures).append(result)
   (completed_ids if result.get('ok') else failed_ids).append(item['job']['id'])
   log.info('WORKER_END batch_id=%s line=%s pid=%s job=%s returncode=%s ok=%s elapsed=%.2fs',batch_id,item['line'],item['proc'].pid,item['job']['name'],rc,result.get('ok'),result.get('elapsed',0))
   batch_results.append({'job':item['job']['name'],'job_id':item['job']['id'],'status':'ok' if result.get('ok') else 'failed',
                         'detail':str(result.get('result') or result.get('error') or ''),'rows':result.get('rows'),'cols':result.get('columns'),
                         'elapsed':round(float(result.get('elapsed') or 0),1),'target':str(result.get('target') or ''),
                         'published':bool(result.get('published',True)),'pending':str(result.get('pending') or '')})
   set_status(job_results=list(batch_results))
   record_job_run(item['job']['id'],item['job']['name'],'ok' if result.get('ok') else 'failed',trigger,detail=(result.get('result') or result.get('error') or ''),rows=result.get('rows'),cols=result.get('columns'),output_file=Path(result.get('target') or '').name,
                  metrics={**{k:result.get(k) for k in ('elapsed','execute_seconds','save_seconds','merge_seconds','transfer_bytes','transfer_kbs','split_parts','split_shape','split_how','row_axis','axis_seconds','race_winner','format') if result.get(k) is not None},
                           # 公開できたか。鮮度の判定がこれを見る（実行できても差し替わっていない場合がある）
                           'published':bool(result.get('published',True)),'pending':str(result.get('pending') or '')})
   # RNE単位の実績。時間帯・端末・分け方まで残し、あとから条件別に見比べられるようにする。
   if result.get('rne_path'):
    record_rne_run(result['rne_path'],item['job'],'ok' if result.get('ok') else 'failed',trigger,
                   dict(result,rows=result.get('rows'),cols=result.get('columns'),lines=max_lines),engine='api')
   # ワーカーが持ち帰った列名をここで保存する。設定DBへの書き込みを親1本に集約して競合を避ける。
   if result.get('ok') and result.get('column_names'):
    save_column_cache(result.get('rne_path') or '',result['column_names'],rows=result.get('rows'),source='run',job=item['job'])
   # 所要時間の基準は「分割なし1本」の値でなければ意味がない。分割で取った回は記録しない。
   if result.get('ok') and result.get('rne_path') and not result.get('split_parts'):
    save_rne_timing(result['rne_path'],result.get('execute_seconds'),result.get('save_seconds'),
                    result.get('total_seconds'),result.get('rows'),result.get('columns'))
   if result.get('split_parts'):
    log.info('SPLIT_RUN_USED batch_id=%s job=%s 形=%s 片数=%s 軸=%s winner=%s elapsed=%.2fs',batch_id,item['job']['name'],
             result.get('split_how') or result.get('split_shape') or '-',result['split_parts'],
             result.get('row_axis') or '-',result.get('race_winner') or '-',result.get('elapsed') or 0)
   with active_workers_lock:active_workers.pop(slot,None)
   del active[slot]
   if queue and not cancel_requested.is_set():start_one(slot)
  waiting=len(queue);running=len(active)
  running_ids=[item['job']['id'] for item in active.values()]
  waiting_ids=[job['id'] for _,job in queue]
  set_status(completed_jobs=completed,current_index=min(completed+running,total),current_job_name=f'予約キュー処理中: 実行 {running} / 待機 {waiting}',step='save',step_label=f'API並列処理 実行 {running}・待機 {waiting}・完了 {completed}',step_percent=round(100*completed/max(1,total)),activity_detail=f'{max_lines}ラインで予約クエリを処理',activity_value=f'実行 {running} / 待機 {waiting} / 完了 {completed}/{total}',queue_total=total,queue_waiting=waiting,queue_active=running,queue_completed=completed,queue_completed_ids=list(completed_ids),queue_failed_ids=list(failed_ids),queue_running_ids=running_ids,queue_waiting_ids=waiting_ids,failed_jobs=len(failed_ids),job_errors=[{'job':x.get('job'),'error':str(x.get('error') or '')} for x in failures])
  time.sleep(.25)
 elapsed=time.perf_counter()-batch_started
 sequential_sum=sum(float(r.get('elapsed',0)) for r in results+failures);speedup=sequential_sum/elapsed if elapsed else 0
 summary='; '.join(f"{r.get('job')}={float(r.get('elapsed',0)):.1f}s" for r in results)
 log.info('PARALLEL_BATCH_END model=process-isolated total_jobs=%s succeeded=%s failed=%s max_lines=%s elapsed=%.2fs sequential_sum=%.2fs speedup=%.2fx job_elapsed_summary=%s',total,len(results),len(failures),max_lines,elapsed,sequential_sum,speedup,summary)
 set_status(parallel_speedup=round(speedup,2),queue_waiting=0,queue_active=0,queue_completed=completed,queue_completed_ids=list(completed_ids),queue_failed_ids=list(failed_ids),queue_running_ids=[],queue_waiting_ids=[],parallel_mode=True)
 shutil.rmtree(runtime,ignore_errors=True)
 log.info('PARALLEL_RUNTIME_CLEANUP path=%s exists_after=%s',runtime,runtime.exists())
 return results,failures,elapsed

def process(job_ids=None,trigger='manual',parallel_lines_override=None,run_id=None):
 if not run_lock.acquire(False):raise RuntimeError('別の処理が実行中です')
 cancel_requested.clear()
 proc=srv=api_client=None; access_prewarm_thread=None
 try:
  startup_started=time.perf_counter();cfg_started=time.perf_counter();cfg=load();log.info('STARTUP_PHASE phase=config_load elapsed=%.2fs',time.perf_counter()-cfg_started);jobs=[j for j in cfg['jobs'] if j.get('enabled') and (not job_ids or j['id'] in job_ids)]
  if not jobs:raise ValueError('実行対象がありません')
  selection_elapsed=time.perf_counter()-cfg_started;first_job=jobs[0]; first_fmt=normalize_output_format(first_job.get('output_format'),first_job.get('output_file')); first_target=resolve_path(first_job.get('output_folder') or cfg['default_output_folder'])/canonical_output_file(first_job.get('output_file'),first_fmt); progress.started=time.time(); requested_lines=max(1,min(int(parallel_lines_override or 1),len(jobs))); execution_mode='parallel' if str(cfg['settings'].get('extract_engine') or 'api').lower()=='api' else 'serial'; set_status(run_id=run_id or uuid.uuid4().hex,execution_mode=execution_mode,requested_lines=requested_lines,parallel_mode=(execution_mode=='parallel'),parallel_lines=[],queue_total=0,queue_waiting=0,queue_active=0,queue_completed=0,queue_completed_ids=[],queue_failed_ids=[],queue_running_ids=[],queue_waiting_ids=[j['id'] for j in jobs],job_results=[],parallel_max_lines=(requested_lines if execution_mode=='parallel' else 0),parallel_speedup=0,batch_job_ids=[j['id'] for j in jobs]); set_status(running=True,current='準備中',current_job_id=first_job['id'],current_job_name=first_job['name'],current_index=1,total_jobs=len(jobs),completed_jobs=0,failed_jobs=0,output_format=first_fmt,output_file=canonical_output_file(first_job.get('output_file'),first_fmt),output_target=str(first_target),started_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=0,symnavi_window='起動待ち',step='prepare',step_label='設定を確認しています',step_percent=3,last_result='実行中',error_detail='',job_errors=[]); log.info('BUILD_VERSION=%s',BUILD_VERSION); log.info('処理開始 trigger=%s jobs=%s',trigger,[j['rne'] for j in jobs]);log.info('STARTUP_PHASE phase=config_and_job_selection elapsed=%.2fs',selection_elapsed)
  # 何が要るかの判断は path_setting_roles に1本化する。画面が「いまは不要」と出している
  # ものを実行時にだけ必須にすると、直しようのない停止になる（v1.60.0〜v1.66.1は
  # symnavim.def が無いだけでAPI方式でも止まっていた）。
  _roles=path_setting_roles(cfg)
  for k in ('symnavi_exe','symnavim_conf','symnavim_def'):
   if _roles.get(k,('required',''))[0]!='required':continue
   if not resolve_path(cfg[k]).is_file():raise FileNotFoundError(f'{PATH_SETTING_LABEL.get(k,k)}がありません: {cfg[k]}')
  cred_started=time.perf_counter();user,pw,server,_=creds(resolve_path(cfg['symnavim_conf']));log.info('STARTUP_PHASE phase=credential_load elapsed=%.2fs',time.perf_counter()-cred_started);path_started=time.perf_counter();rne_root=resolve_path(cfg['rne_folder']);backup=resolve_path(cfg['backup_folder']);dde_work=dde_staging_folder();log.info('STARTUP_PHASE phase=path_prepare elapsed=%.2fs total=%.2fs',time.perf_counter()-path_started,time.perf_counter()-startup_started);log.info('共通一時保存先: %s',dde_work)
  # rne_folder設定は使われていない場合がある（対象ごとのrne_pathが優先）。実際にRNEがある場所を測る。
  try:probe_rne_dir=resolve_rne_path(jobs[0],cfg).parent
  except Exception:probe_rne_dir=rne_root
  log_run_environment(dde_work,probe_rne_dir)
  engine=str(cfg['settings'].get('extract_engine') or 'api').lower(); set_status(extract_engine=engine); log.info('抽出エンジン engine=%s stability_profile=%s',engine,cfg['settings'].get('stability_profile','stable_api_serial'))
  if any(normalize_output_format(j.get('output_format'),j.get('output_file'))=='accdb' for j in jobs):
   access_prewarm_thread=prewarm_access_async('process_contains_accdb')
  api_parallel_lines=max(1,min(int(cfg['settings'].get('api_parallel_max_lines',24) or 24),int(parallel_lines_override if parallel_lines_override is not None else cfg['settings'].get('api_parallel_lines',1) or 1)))
  # API方式は対象が1件でも独立プロセスで実行する。アプリ内で直接DLLを呼ぶとNaviSaveDataが
  # 一桁遅くなる（実測 約45KB/s に対しワーカー経由は 0.5〜4MB/s）ため、重い抽出ほど差が開く。
  isolated=engine=='api'
  log.info('PARALLEL_DECISION engine=%s selected_jobs=%s configured_lines=%s eligible=%s model=process-isolated',engine,len(jobs),api_parallel_lines,isolated)
  log.info('EXECUTION_MODE mode=%s requested_lines=%s selected_jobs=%s',('parallel-process' if isolated else 'serial'),api_parallel_lines,len(jobs))
  if isolated:
   results,failures,batch_elapsed=run_api_process_batch(jobs,cfg,user,pw,server,dde_work,backup,api_parallel_lines,trigger)
   if cancel_requested.is_set():raise RunCancelled(f'{len(results)}/{len(jobs)}件完了後に中断されました')
   if failures:
    set_status(job_errors=[{'job':r.get('job'),'error':str(r.get('error') or '')} for r in failures],failed_jobs=len(failures))
    raise RuntimeError('API実行で%d件失敗しました\n'%len(failures)+'\n'.join('・%s: %s'%(r.get('job'),r.get('error')) for r in failures))
   msg='正常終了 | '+(''.join(r['result'] for r in results) if len(results)==1 else '全件%sファイル / %.1f秒 | '%(len(results),batch_elapsed)+' | '.join(r['result'] for r in results))
   progress('complete','すべての処理が完了しました',100);set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-progress.started));log.info(msg)
   return
  # ここから下はDDE方式（engine='dde'）専用の直列経路。API方式は上のisolatedブロックで必ずreturnする。
  # engine=='api'の分岐は、DLLを直接読み込む設定に戻せるよう残してあるが通常は通らない。
  if engine=='api':
   from navigator_api import NavigatorApi
   progress('launch','Navigator APIを初期化しています',8); api_client=NavigatorApi(resolve_path(cfg['symnavi_exe']),log,resolve_path(cfg.get('navigator_api_dll')) if cfg.get('navigator_api_dll') else None,base_dir=BASE,search_roots=dll_search_roots(cfg)); set_status(symnavi_window='APIモード')
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
   # f-string内で同じ引用符をネストするとPython 3.12以降でしか解釈できず、3.11以下では
   # app.py全体がコンパイル不能になる。文字列連結で組み立て、旧バージョンでも起動できるようにする。
   progress('launch','SymfoNaviを起動しています',8); _symnavi_cmd='"'+str(resolve_path(cfg['symnavi_exe']))+'" -d -u"'+user+'","'+pw+'","'+server+'"'; proc=subprocess.Popen(_symnavi_cmd); set_status(symnavi_window='起動済み'); progress('dde','SymfoNaviへのDDE接続を待っています',15); srv,conv=dde_connect(int(cfg['settings']['dde_timeout_seconds'])); start_hidden_symnavi(proc,cfg['settings'])
  else:raise ValueError('抽出エンジンが不正です: '+engine)
  progress('ready','処理の準備が完了しました',20); results=[]; completed_ids=[]; job_results=[]
  set_status(job_results=[])
  for job_index,j in enumerate(jobs,1):
   if cancel_requested.is_set():raise RunCancelled(f'{job_index-1}/{len(jobs)}件完了後に中断されました')
   j['output_file']=resolve_output_filename(j,cfg); log.info('OUTPUT_NAME job=%s mode=%s pattern=%s resolved_file=%s',j['name'],j.get('naming_mode','fixed'),j.get('output_pattern',''),j['output_file'])
   set_status(current_index=job_index,current_job_id=j['id'],current_job_name=j['name'],queue_running_ids=[j['id']],queue_waiting_ids=[x['id'] for x in jobs[job_index:]],output_format=normalize_output_format(j.get('output_format'),j.get('output_file')),output_file=canonical_output_file(j.get('output_file'),normalize_output_format(j.get('output_format'),j.get('output_file'))))
   phase_profile_reset(); preflight_started=phase_log('job_preflight',job=j['name']); progress('open',f'{j["name"]}: 入出力先を確認しています',22,activity_detail='事前確認',activity_value='出力先・保留ファイル・RNEを確認'); rp=resolve_rne_path(j,cfg); out_dir=resolve_path(j.get('output_folder') or cfg['default_output_folder']); fmt=validate_output_contract(j,'before-extraction'); j['_accdb_template']=str(resolve_path(cfg.get('accdb_template','.\\assets\\empty.accdb'))); target=out_dir/j['output_file']; set_status(output_target=str(target)); log.info('実行設定 job=%s format=%s output_file=%s target=%s',j['name'],fmt,j['output_file'],target); apply_pending(target,backup,int(cfg['settings']['backup_generations']),backup_enabled=bool(cfg['settings'].get('backup_enabled',True)),retention_days=int(cfg['settings'].get('backup_retention_days',30)),generation_limit_enabled=bool(cfg['settings'].get('backup_generation_limit_enabled',True)),backup_mode=str(cfg['settings'].get('backup_mode','generations'))); phase_log('job_preflight',preflight_started,job=j['name'],rne=rp,target=target)
   if not rp.is_file():raise FileNotFoundError('RNEがありません: '+str(rp))
   stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f'); xls=dde_work/f'navi_{job_index}_{stamp}.xls'; local_export=dde_work/'export'; local_export.mkdir(parents=True,exist_ok=True); db=local_export/f'{Path(j["output_file"]).stem}_{stamp}{Path(j["output_file"]).suffix}'; log.info('変換作業先 local=%s',db); esc=lambda x:str(x).replace('"','""')
   # 同時に出す形式があるなら、共通の中間データを必ず通す（XLSXの直接受信からは他形式へ作り直せない）
   extras=job_extra_formats(j)
   allow_direct_xlsx=(engine=='api' and fmt=='xlsx' and not extras)
   api_planned=(db if allow_direct_xlsx else (dde_work/f'navi_{job_index}_{stamp}.csv' if engine=='api' else xls));common_intermediate=('API_DIRECT_XLSX' if allow_direct_xlsx else ('CSV' if engine=='api' else 'XLS'))
   if extras:log.info('MULTI_FORMAT job=%s primary=%s extras=%s note=抽出は1回のまま変換と公開だけを繰り返します',j['name'],fmt,','.join(extras))
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
    with chdir_lock:
     previous_cwd=os.getcwd()
     try:
      # cwdも元RNEフォルダーへ合わせ、RNE内部の相対参照とAPI側の探索条件を両立する。
      os.chdir(api_rne.parent)
      log.info('APIカタログ読込条件 dll=%s cwd=%s catalog_full=%s catalog_name=%s extension=%s size=%s mtime_ns=%s strategy=original_fullpath',api_client.dll_path,os.getcwd(),api_rne,api_rne.name,api_rne.suffix,rne_stat.st_size,rne_stat.st_mtime_ns)
      t=phase_log('api_open_catalog',job=j['name']); handle,api_elapsed=api_client.open_catalog(api_rne); phase_log('api_open_catalog',t,job=j['name'],handle=handle,api_elapsed=f'{api_elapsed:.2f}s',strategy='original_fullpath')
     finally:os.chdir(previous_cwd)
    if (j.get('period') or {}).get('enabled'):
     progress('open',f'{j["name"]}: 相対期間を適用しています',34,activity_detail='Navigator API 期間指定',activity_value=(compute_period(j.get('period'),datetime.now()) or {}).get('summary',''));applied=apply_dynamic_period(api_client,handle,j,datetime.now())
     if applied:log.info('実行設定 job=%s dynamic_period=%s',j['name'],applied.get('summary'))
    progress('save',f'{j["name"]}: APIで問い合わせを実行しています',38,activity_detail='Navigator API 2/3',activity_value='問い合わせ実行・ダウンロード')
    t=phase_log('api_execute_catalog',job=j['name']); api_number,api_elapsed=api_client.execute(handle); phase_log('api_execute_catalog',t,job=j['name'],number=api_number,api_elapsed=f'{api_elapsed:.2f}s',rows_per_sec=f'{api_number/api_elapsed:.0f}' if api_elapsed>0 else '0')
    t=phase_log('api_get_dimensions',job=j['name']);expected_rows,expected_cols=api_client.dimensions(handle);phase_log('api_get_dimensions',t,job=j['name'],rows=expected_rows,columns=expected_cols)
    api_direct_output=False;api_csv=None
    if allow_direct_xlsx:
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
     t=phase_log('api_save_csv',job=j['name']);save_elapsed=api_client.save_csv(handle,api_csv);phase_log('api_save_csv',t,job=j['name'],api_elapsed=f'{save_elapsed:.2f}s',**save_metrics(api_csv,save_elapsed,expected_rows))
     if not api_csv.is_file() or api_csv.stat().st_size<=0:raise RuntimeError(f'API中間CSVが作成されませんでした: {api_csv}')
     intermediate=api_csv
    progress('close',f'{j["name"]}: APIカタログを解放しています',62,activity_detail='API抽出完了',activity_value=f'期待値 {expected_rows}行 x {expected_cols}列');t=phase_log('api_close_catalog',job=j['name']);api_client.close_catalog();phase_log('api_close_catalog',t,job=j['name'])
   else:
    # DDEも工程ごとに進捗を出す。APIと同じ順（開く→抽出→検証→閉じる）で percent も単調に増やす。
    progress('open',f'{j["name"]}: RNEを開いています',28,current_job_id=j['id'],activity_detail='共通抽出工程 1/4',activity_value=str(rp))
    t=phase_log('rne_open',job=j['name']); dde_exec(conv,'Open',f'[Open("{esc(rp)}")]'); phase_log('rne_open',t,job=j['name'])
    progress('save',f'{j["name"]}: 共通XLSを生成しています',38,activity_detail='共通抽出工程 2/4',activity_value=str(xls))
    t=phase_log('xls_save',job=j['name']); dde_exec(conv,'Save',f'[Save("{esc(xls)}", "EXCEL")]',expected_output=xls); dde_save_seconds=phase_log('xls_save',t,job=j['name'])
    progress('wait',f'{j["name"]}: 共通XLSを検証しています',50,activity_detail='共通抽出工程 3/4',activity_value='ファイル安定・構造確認')
    t=phase_log('xls_stability',job=j['name']); wait_file(xls,int(cfg['settings']['output_wait_seconds']),j); phase_log('xls_stability',t,job=j['name'],size=xls.stat().st_size)
    intermediate=xls;expected_rows=None;expected_cols=None
    xls_bytes=xls.stat().st_size
    log.info('DDE_EXTRACT job=%s file=%s bytes=%s save_elapsed=%.2fs throughput_kb_s=%s',j['name'],xls,xls_bytes,dde_save_seconds or 0,f'{xls_bytes/1024/dde_save_seconds:.1f}' if dde_save_seconds else '0')
    progress('close',f'{j["name"]}: 抽出画面を閉じています',62,activity_detail='共通抽出工程 4/4',activity_value=f'{xls_bytes:,} bytes')
    t=phase_log('rne_close',job=j['name']); dde_exec(conv,'Close','[Close()]'); phase_log('rne_close',t,job=j['name'])
   if fmt=='accdb' and access_prewarm_thread is not None:
    join_started=time.perf_counter();alive_before=access_prewarm_thread.is_alive();access_prewarm_thread.join(timeout=2.0);log.info('ACCDB_PREWARM_JOIN alive_before=%s alive_after=%s elapsed=%.2fs',alive_before,access_prewarm_thread.is_alive(),time.perf_counter()-join_started)
   # 仕上げ（変換 → 公開 → 同時出力）は並列と同じ関数で行う。見せ方だけをここで足す。
   _direct=bool(allow_direct_xlsx and locals().get('api_direct_output'))
   def _report(stage,**kw):
    if stage=='unchanged':progress('publish',f'{j["name"]}: 前回と同じ内容のため更新しませんでした',95,activity_detail='変更なし',activity_value=str(target))
    elif stage=='convert':
     if kw.get('direct'):progress('export',f'{j["name"]}: API直接XLSXを検証しています',70,activity_detail='形式別変換工程',activity_value='CSV変換なし / API直接出力')
     else:progress('export',f'{j["name"]}: {fmt.upper()}へ変換しています',70,activity_detail='形式別変換工程',activity_value=f'{intermediate.suffix.upper()} -> {fmt.upper()}')
    elif stage=='publish':progress('publish',f'{j["name"]}: 検査済みファイルを公開しています',90,activity_detail='公開工程',activity_value=str(target))
    elif stage=='extras':progress('publish',f'{j["name"]}: 同じデータからあと{len(extras)}形式を作成しています',95,activity_detail='同時出力',activity_value='・'.join(OUTPUT_FORMAT_LABEL.get(x,x) for x in extras))
   fin=finish_one_job(j,cfg,intermediate=intermediate,db=db,target=target,backup=backup,out_dir=out_dir,
                      local_export=local_export,stamp=stamp,expected_rows=expected_rows,expected_cols=expected_cols,
                      fmt=fmt,extras=extras,api_direct_output=_direct,job_started=job_started,report=_report)
   if fin['unchanged']:
    total=fin['total']
    detail=f'前回と同じ内容のため更新しませんでした / {total:.1f}秒'
    results.append(f'{j["name"]}: '+detail); completed_ids.append(j['id'])
    record_job_run(j['id'],j['name'],'ok',trigger,detail=detail,rows=fin['rows'],cols=fin['cols'],output_file=j['output_file'],metrics={})
    job_results.append({'job':j['name'],'job_id':j['id'],'status':'ok','detail':detail,
                        'rows':fin['rows'],'cols':fin['cols'],
                        'elapsed':round(total,1),'target':str(target),'published':True,'unchanged':True})
    set_status(completed_jobs=job_index,queue_completed_ids=list(completed_ids),queue_running_ids=[],job_results=list(job_results))
    for p in (xls,locals().get('api_csv'),db):
     try:
      if p:p.unlink()
     except:pass
    continue
   nr,nc=fin['rows'],fin['cols'];pub={'published':fin['published'],'pending':fin['pending']}
   extra_results=fin['extra_results'];total=fin['total']
   detail=f'{nr}件/{nc}列 / {total:.1f}秒'+('' if pub['published'] else f' / 更新保留: {pub["pending"]}')+extra_format_note(extra_results)
   results.append(f'{j["name"]}: '+detail); completed_ids.append(j['id'])
   # 直列（DDE / アプリ内API）でも並列と同じ実績を残す。ここを空にすると一覧の実績欄が
   # 「件数だけ」になり、所要も転送量も後から追えなくなる。
   metrics=serial_run_metrics(engine,fmt,total,nr,nc,locals().get('intermediate'),locals().get('dde_save_seconds'))
   # 並列と同じ形で、公開できたかどうかも残す（鮮度の判定がこれを見る）
   metrics.update(published=bool(pub['published']),pending=str(pub.get('pending') or ''))
   record_job_run(j['id'],j['name'],'ok',trigger,detail=detail,rows=nr,cols=nc,output_file=j['output_file'],metrics=metrics)
   record_rne_run(rp,j,'ok',trigger,metrics,engine=engine,fmt=fmt)
   job_results.append({'job':j['name'],'job_id':j['id'],'status':'ok','detail':detail,'rows':nr,'cols':nc,'elapsed':round(total,1),'target':str(target),'published':bool(pub['published']),'pending':str(pub.get('pending') or '')})
   set_status(completed_jobs=job_index,queue_completed_ids=list(completed_ids),queue_running_ids=[],job_results=list(job_results))
   log.info('JOB_RESULT job=%s format=%s rows=%s columns=%s elapsed=%.2fs target=%s',j['name'],fmt,nr,nc,total,target); log.info('JOB_PROFILE job=%s rows=%s columns=%s %s',j['name'],nr,nc,phase_profile_summary())
   try:
    if column_cache_state(rp)[0]!='hit':save_column_cache(rp,read_header_names(db,j),rows=nr,source='run',job=j)
   except Exception as ce:log.warning('COLUMN_CACHE_READ_FAILED job=%s error=%s',j['name'],ce)
   # 元RNEはAPIが直接参照するため削除対象に含めない。生成物だけを後片付けする。
   for p in (xls,locals().get('api_csv'),db):
    try:
     if p:p.unlink()
    except:pass
  msg='正常終了 | '+' | '.join(results); progress('complete','すべての処理が完了しました',100); set_status(last_result=msg,last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-progress.started)); log.info(msg)
 except RunCancelled as e:
  msg='中断されました: '+str(e); set_status(step='cancelled',step_label='ユーザーの操作により中断しました',step_percent=100,last_result=msg,error_detail='',last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-getattr(progress,'started',time.time()))); log.info('RUN_CANCELLED %s',msg)
  if status.get('running') and status.get('current_job_id'):
   record_job_run(status['current_job_id'],status.get('current_job_name',''),'cancelled',trigger,detail=msg)
   set_status(queue_running_ids=[])
 except Exception as e:
  msg='異常終了: '+str(e); set_status(step='error',step_label='処理を完了できませんでした',failed_jobs=1,step_percent=100,last_result=msg,error_detail=str(e),last_finished_at=datetime.now().isoformat(timespec='seconds'),elapsed_seconds=int(time.time()-getattr(progress,'started',time.time()))); log.error('%s\n%s',msg,traceback.format_exc())
  if status.get('current_job_id'):
   record_job_run(status['current_job_id'],status.get('current_job_name',''),'failed',trigger,detail=str(e))
   # 直列実行では失敗を確定させるのがここしかない。入れておかないと一覧の行が
   # 「処理中」のまま止まり、どの対象で落ちたのかが画面から分からない。
   failed_ids=[x for x in (status.get('queue_failed_ids') or [])]+[status['current_job_id']]
   set_status(queue_failed_ids=list(dict.fromkeys(failed_ids)),queue_running_ids=[],
              job_results=list(status.get('job_results') or [])+[{'job':status.get('current_job_name','') or '実行対象','job_id':status['current_job_id'],'status':'failed','detail':str(e)}])
  if not status.get('job_errors'):set_status(job_errors=[{'job':status.get('current_job_name','') or '実行対象','error':str(e)}])
  raise
 finally:
  cancel_requested.clear()
  set_status(running=False,current='',current_job_id='',symnavi_window='終了済み')
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

def parallel_lines_cap(cfg=None):
 # 上限は設定値(api_parallel_max_lines)を単一の基準とする。ここを固定値で書くと、
 # 設定できる最大値と実際に効く値がずれ、設定した数が黙って切り捨てられる。
 try:
  settings=(cfg or load()).get('settings',{})
  return max(1,int(settings.get('api_parallel_max_lines',PARALLEL_LINES_SUPPORTED_MAX) or PARALLEL_LINES_SUPPORTED_MAX))
 except Exception:
  return PARALLEL_LINES_SUPPORTED_MAX
def clamp_parallel_lines(value,cfg=None,default=1):
 try:n=int(value if value is not None else default)
 except (TypeError,ValueError):n=default
 return max(1,min(parallel_lines_cap(cfg),n))

# ==== 失敗に気づく／自動で取り直す =========================================
# 自動実行は誰も見ていない時間に走る。これまでは失敗しても記録が残るだけで、
# 画面を開くまで分からず、次の予定時刻までデータが古いままだった。
#   ① 失敗したら、その場で知らせる（常駐アイコンの通知＋画面の常設バッジ）
#   ② 自動実行の失敗だけ、少し待って取り直す（手動は人が見ているので取り直さない）
alerts_lock=threading.Lock()
alerts=[]           # 画面へ出す未確認の知らせ
retry_lock=threading.Lock()
retry_waiting=[]    # {'due_at':epoch,'job_ids':[...],'attempt':n,'lines':n,'names':[...]}

def add_alert(kind,title,detail,job_names=None):
 """知らせを1件積む。常駐アイコンが使えるなら、そこへも出す。"""
 item={'id':uuid.uuid4().hex,'kind':kind,'title':title,'detail':str(detail or '')[:400],
       'jobs':list(job_names or []),'at':datetime.now().isoformat(timespec='seconds')}
 with alerts_lock:
  alerts.append(item)
  del alerts[:-50]   # 溜め込まない。読むのは直近だけ
 log.info('ALERT kind=%s title=%s jobs=%s detail=%s',kind,title,item['jobs'],item['detail'][:120])
 if tray and kind!='info':
  try:tray.notify(title,item['detail'][:200] or title)
  except Exception:log.warning('ALERT_NOTIFY_FAILED title=%s',title)
 return item

def pending_jobs_of_run():
 """直前の実行で「取れたのに、共有先へ差し替えられなかった」対象。

 公開先を誰かが開いていると、新しいファイルは *.pending_* として横に置かれ、
 共有先のファイルは古いままになる。それでも実行そのものは成功なので、状態は ok、
 鮮度も「最新」と出ていた。読み手は古いデータを最新だと思って使い続けてしまう。
 次の実行で自動的に適用されるが、それまで誰も気づけないのが問題だった。
 """
 out=[]
 for x in (status.get('job_results') or []):
  if not isinstance(x,dict) or x.get('status')!='ok':continue
  if x.get('published') is False:out.append({'job':str(x.get('job') or ''),'job_id':str(x.get('job_id') or ''),
                                             'target':str(x.get('target') or ''),'pending':str(x.get('pending') or '')})
 return out

def failed_jobs_of_run():
 """直前の実行で失敗した対象と、その理由。並列・直列のどちらも同じ場所に残る。"""
 ids=[x for x in (status.get('queue_failed_ids') or []) if x]
 errs=[x for x in (status.get('job_errors') or []) if isinstance(x,dict)]
 names=[str(x.get('job') or '') for x in errs if x.get('job')]
 # 対象ごとの理由がいちばん具体的。まとめのメッセージより先に使う。
 why=' / '.join(f'{x.get("job")}: {str(x.get("error") or "")[:120]}' for x in errs if x.get('error'))
 return ids,names,why

def schedule_retry(job_ids,names,lines,attempt,cfg,reason=''):
 """少し待ってから、失敗した対象だけを取り直す予約を入れる。

 すぐ取り直しても、サーバー混雑や回線の瞬断は直っていないことが多い。
 実際に流すのはスケジューラーの巡回（15秒ごと）が拾う。"""
 s=cfg['settings']
 if not bool(s.get('retry_enabled',True)):return None
 limit=max(0,min(5,int(s.get('retry_max',1) or 0)))
 if attempt>limit:
  add_alert('error','取り直しても失敗しました',
            f'{len(job_ids)}件が{limit}回の取り直しでも成功しませんでした: '+'・'.join(names[:5]),names)
  return None
 wait=max(1,min(180,int(s.get('retry_delay_minutes',5) or 5)))
 due=time.time()+wait*60
 with retry_lock:
  retry_waiting.append({'due_at':due,'job_ids':list(job_ids),'names':list(names),
                        'lines':lines,'attempt':attempt})
 log.info('RETRY_SCHEDULED jobs=%s attempt=%s/%s wait_minutes=%s reason=%s',names,attempt,limit,wait,reason)
 add_alert('warn',f'{wait}分後に取り直します',
           f'{len(job_ids)}件が失敗しました（{attempt}回目の取り直し / 最大{limit}回）: '+'・'.join(names[:5]),names)
 return due

def due_retries():
 """時刻が来た取り直しを取り出す。"""
 now=time.time();out=[]
 with retry_lock:
  keep=[]
  for r in retry_waiting:
   (out if r['due_at']<=now else keep).append(r)
  retry_waiting[:]=keep
 return out

def retry_view():
 with retry_lock:
  return [{'jobs':r['names'],'attempt':r['attempt'],
           'due_at':datetime.fromtimestamp(r['due_at']).isoformat(timespec='seconds')} for r in retry_waiting]

def after_command(item,error=''):
 """1つの実行が終わったところ。失敗と「更新保留」を知らせ、必要なら取り直しを予約する。"""
 try:
  # 保留は失敗ではないので、成功した実行でも必ず見る。ここを失敗と同じ枝に置くと、
  # すべて成功した実行（＝いちばん起きやすい形）で知らせが出ない。
  held=pending_jobs_of_run()
  if held:
   add_alert('warn',f'{len(held)}件が共有先へ反映できていません',
             '・'.join(x['job'] for x in held[:5])
             +'（公開先が使用中でした。新しいデータは横に控えてあり、次の実行で自動的に反映します）',
             [x['job'] for x in held])
   for x in held:log.warning('PUBLISH_HELD job=%s target=%s pending=%s',x['job'],x['target'],x['pending'])
  ids,names,why=failed_jobs_of_run()
  if not ids and not error:
   # 前の失敗が解消したことも伝える。取り直しで直ったのか分からないと落ち着かない。
   if int(item.get('attempt') or 0)>0:
    add_alert('info','取り直しで成功しました','・'.join(item.get('job_names') or [])[:200],item.get('job_names'))
   return
  cfg=load()
  if not names:names=list(item.get('job_names') or [])
  if not ids:ids=list(item.get('job_ids') or [])
  detail=str(why or error or status.get('error_detail') or status.get('last_result') or '')
  add_alert('error',f'{len(ids)}件の実行が失敗しました','・'.join(names[:5])+(f' / {detail}' if detail else ''),names)
  # 取り直すのは自動実行だけ。手動は人が見ているので、勝手に走らせない。
  if str(item.get('trigger') or '').startswith('schedule'):
   schedule_retry(ids,names,item.get('parallel_lines') or 1,int(item.get('attempt') or 0)+1,cfg,reason=detail[:80])
 except Exception:
  log.exception('AFTER_COMMAND_FAILED')

def enqueue_command(job_ids,trigger,parallel_lines,attempt=0):
 cfg=load(); selected=[j for j in cfg['jobs'] if j.get('enabled') and (not job_ids or j['id'] in job_ids)]
 if not selected:raise ValueError('実行対象がありません')
 # DDEはSymfoNavi画面を1つ操作する方式なので、並列ライン数の指定は効かない。
 # そのまま持たせると実行キューに「6ライン」と出て、実際の動き（1件ずつ）と食い違う。
 engine=str(cfg.get('settings',{}).get('extract_engine') or 'api').lower()
 lines=1 if engine=='dde' else clamp_parallel_lines(parallel_lines,cfg)
 item={'id':uuid.uuid4().hex,'job_ids':[j['id'] for j in selected],'job_names':[j['name'] for j in selected],'trigger':trigger,'parallel_lines':lines,'engine':engine,'attempt':int(attempt or 0),'enqueued_at':datetime.now().isoformat(timespec='seconds'),'count':len(selected)}
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
  err=''
  try:process(item['job_ids'],item['trigger'],item['parallel_lines'],item['id'])
  except Exception as e:err=str(e);log.error('COMMAND_QUEUE_FAILED id=%s error=%s',item['id'],e)
  finally:
   after_command(item,err)
   with command_queue_lock:active_command=None
   log.info('COMMAND_QUEUE_END id=%s remaining=%s',item['id'],len(command_queue))
   command_queue_event.set()

def schedule_key(job,rule,now,grace_minutes=0):
 kind=rule.get('type','daily'); tm=rule.get('time','06:00'); hh,mm=map(int,tm.split(':')) if ':' in tm else (6,0)
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60))); return str(int(now.timestamp()//(mins*60))) if rule.get('enabled') else None
 # 予定時刻ちょうどの1分間だけを見ていると、その1分が他の処理と重なっただけで
 # その日の実行が丸ごと飛ぶ。猶予時間内なら同じ鍵を返し、手が空いた時点で実行させる。
 # 鍵は日付＋時刻なので、猶予中に何度判定しても1日1回しか発火しない。
 # 日をまたぐ猶予は行わない（翌日に前日ぶんが走る事故を避ける）。
 scheduled=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
 delay=(now-scheduled).total_seconds()
 if delay<0 or delay>=max(60,int(grace_minutes or 0)*60):return None
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

def expand_rule_occurrences(rule,start,end,limit=400):
 """カレンダー表示用に、ルール1件が[start,end]の期間に実行される日時をすべて返す。
 interval（一定間隔）は件数が膨大になり得るため、日ごとの回数へ集約した要約情報を別途返す。"""
 if not rule.get('enabled',True):return [],[]
 kind=rule.get('type','daily'); tm=str(rule.get('time') or '06:00')
 try:hh,mm=map(int,tm.split(':'))
 except Exception:hh,mm=6,0
 points=[]; interval_days=[]
 day=start.date(); last_day=end.date()
 if kind=='interval':
  mins=max(1,int(rule.get('interval_minutes',60) or 60)); per_day=max(1,(24*60)//mins)
  d=day
  while d<=last_day:
   interval_days.append({'date':d.isoformat(),'minutes':mins,'count':per_day})
   d+=timedelta(days=1)
  return points,interval_days
 if kind=='weekdays':
  wd=set(rule.get('weekdays') or [])
  d=day
  while d<=last_day:
   if d.weekday() in wd:points.append(datetime(d.year,d.month,d.day,hh,mm))
   d+=timedelta(days=1)
 elif kind=='daily':
  d=day
  while d<=last_day:
   points.append(datetime(d.year,d.month,d.day,hh,mm)); d+=timedelta(days=1)
 elif kind=='monthly':
  days=rule.get('month_days') or [1]; d=day
  while d<=last_day:
   lastn=calendar.monthrange(d.year,d.month)[1]; target={(lastn if x==-1 else x) for x in days}
   if d.day in target:points.append(datetime(d.year,d.month,d.day,hh,mm))
   d+=timedelta(days=1)
 elif kind=='specific_dates':
  for ds in (rule.get('dates') or []):
   try:y,mo,da=map(int,str(ds).split('-'))
   except Exception:continue
   cand=datetime(y,mo,da,hh,mm)
   if start<=cand<=end:points.append(cand)
 return points[:limit],interval_days

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

# ==== ブラウザーを閉じた後の常駐（通知領域） ==============================
# タブが無くなっても、実行中・実行キューあり・自動実行の予定ありのいずれかなら常駐を続ける。
# 常駐中は通知領域にアイコンを出し、そこから画面を開く／終了できるようにする。
residency_state={'active':False,'reason':'','since':0.0}
tray=None
def pending_queue_count():
 with command_queue_lock:return len(command_queue)+(1 if active_command else 0)
def residency_reason():
 """常駐を続ける理由。無ければ空文字（＝終了してよい）。"""
 if status.get('running'):return '処理を実行中'
 queued=pending_queue_count()
 if queued:return f'実行キュー {queued}件が待機中'
 if any_enabled_schedule_exists():return '自動実行の予定あり'
 return ''
def tray_status_text():
 reason=residency_reason()
 if status.get('running'):
  return f'実行中 {status.get("completed_jobs",0)}/{status.get("total_jobs",0)}'
 return reason or '待機中'
def open_app_window():
 try:webbrowser.open(f'http://{HOST}:{PORT}')
 except Exception:log.exception('TRAY_OPEN_FAILED')
def request_shutdown_from_tray():
 # 通知領域からの終了も「アプリを終了」と同じ扱いにする。実行中なら先に中断してから終える。
 if status.get('running'):
  log.info('TRAY_EXIT_REQUESTED running=1 action=cancel_then_exit')
  cancel_requested.set()
  with active_workers_lock:workers=list(active_workers.values())
  for p in workers:
   try:p.terminate()
   except Exception:pass
  deadline=time.time()+30
  while status.get('running') and time.time()<deadline:time.sleep(0.3)
 else:
  log.info('TRAY_EXIT_REQUESTED running=0 action=exit')
 with command_queue_lock:command_queue.clear()
 flush_log()
 _flush_settings_on_exit('tray-exit');stop_event.set()
 if tray:
  try:tray.stop()
  except Exception:pass
 os._exit(0)
def start_tray():
 global tray
 if WORKER_MODE or os.name!='nt':return None
 try:
  from tray_icon import TrayIcon
  icon=BASE/'static'/'favicon.ico'
  tray=TrayIcon('SymfoNavi Data Hub',f'http://{HOST}:{PORT}',str(icon) if icon.is_file() else None,
                on_open=open_app_window,on_exit=request_shutdown_from_tray,status_text=tray_status_text,logger=log)
  return tray if tray.start() else None
 except Exception:
  # 常駐アイコンを作れなくてもアプリ本体は動かし続ける（自動実行を止めない）。
  log.exception('TRAY_INIT_FAILED');return None
def enter_residency(reason,client_ids=''):
 if residency_state['active']:
  if reason!=residency_state['reason']:
   residency_state['reason']=reason
   if tray:tray.refresh_tooltip()
  return
 residency_state.update(active=True,reason=reason,since=time.time())
 log.info('APP_RESIDENT_ENTER closing_clients=%s reason=%s action=keep_alive_with_tray',client_ids,reason)
 if tray:
  tray.refresh_tooltip()
  tray.notify('SymfoNavi Data Hub は常駐しています',
              f'{reason}のため実行を続けます。\n画面を開く・終了するには通知領域のアイコンを使用してください。')
def leave_residency():
 if not residency_state['active']:return
 residency_state.update(active=False,reason='',since=0.0)
 log.info('APP_RESIDENT_LEAVE reason=app_tab_reopened')
 if tray:tray.refresh_tooltip()
# =====================================================================

def heartbeat_watchdog():
 time.sleep(10)
 while not stop_event.wait(2):
  try:
   now=time.time()
   with heartbeat_lock:
    silence=now-last_heartbeat_at
    clients={k:dict(v) for k,v in heartbeat_clients.items()}
   # pagehide通知後も同じclient_idのハートビートが猶予時間内に戻れば、再読込・戻る/進む・BFCache復帰として終了を取り消す。
   closing=[(cid,v) for cid,v in clients.items() if v.get('closing_at') and now-float(v.get('closing_at') or 0)>=CLOSE_GRACE_SECONDS]
   # 明示的な終了通知が無いまま消えたタブ(ブラウザー強制終了・通信断など)を「常時接続中」と誤認すると、
   # 二度と自動終了できなくなる。最後の受信からの経過でも生存を判定する。
   active=[(cid,v) for cid,v in clients.items() if not v.get('closing_at') and now-float(v.get('last_seen') or 0)<HEARTBEAT_TIMEOUT_SECONDS]
   if closing and not active:
    ids=','.join(cid for cid,_ in closing)
    # 実行中・実行キューあり・自動実行の予定ありの場合は終了しない。ここで落とすと処理が中途半端に打ち切られ、
    # 並列実行中の各ラインのワーカープロセスが親を失って孤児化する。
    # 常駐へ切り替えるときは通知領域アイコンを出し、「見えない・止められない」状態にしない。
    reason=residency_reason()
    if reason:
     enter_residency(reason,ids);continue
    log.info('APP_TABS_EMPTY_CONFIRMED closing_clients=%s active_app_tabs=0 grace=%ss action=python_exit',ids,CLOSE_GRACE_SECONDS)
    flush_log()
    _flush_settings_on_exit('app-tabs-empty');stop_event.set();os._exit(0)
   elif active and residency_state['active']:
    leave_residency()
   # ハートビート途絶だけでは終了しない。ネットワーク断、スリープ、ブラウザー破棄との誤判定を避ける。
   # 状態は変わらないので、そのつど出すとログがこれだけで埋まる（実測 7時間ぶんで数千行）。
   # 最初の1回と、間隔を広げながらの節目だけ残す。分かることは同じで、量は1/100以下になる。
   if silence>HEARTBEAT_TIMEOUT_SECONDS:
    if _heartbeat_should_log(silence):
     log.warning('HEARTBEAT_DEGRADED silence=%.0fs server_kept_alive=1 note=次は%s後に出します',
                 silence,_heartbeat_next_label(silence))
   else:
    _heartbeat_notice['at']=0.0
  except Exception:
   log.exception('ハートビート監視エラー')

# 途絶の知らせは節目だけ。1分 → 5分 → 30分 → 1時間ごと、と間隔を広げる。
HEARTBEAT_NOTICE_STEPS=(60,300,1800,3600)
_heartbeat_notice={'at':0.0}

def _heartbeat_should_log(silence):
 """この途絶を残すか。前回から十分に間が空いたときだけ True。"""
 last=float(_heartbeat_notice.get('at') or 0)
 if last<=0:
  _heartbeat_notice['at']=silence;return True
 gap=silence-last
 want=next((x for x in HEARTBEAT_NOTICE_STEPS if silence<x*2),HEARTBEAT_NOTICE_STEPS[-1])
 if gap>=want:
  _heartbeat_notice['at']=silence;return True
 return False

def _heartbeat_next_label(silence):
 want=next((x for x in HEARTBEAT_NOTICE_STEPS if silence<x*2),HEARTBEAT_NOTICE_STEPS[-1])
 return f'{want//60}分' if want>=60 else f'{want}秒'

def scheduler():
 time.sleep(3)
 while not stop_event.wait(15):
  try:
   if status['running']:continue
   cfg=load(); now=datetime.now(); st=load_scheduler_state()
   rotate_log_if_needed(cfg)
   # 取り直しは予定より先に流す。待たせるほどデータが古いままになる。
   for r in due_retries():
    try:
     enqueue_command(r['job_ids'],f'schedule-retry:{r["attempt"]}',r['lines'],attempt=r['attempt'])
     log.info('RETRY_ENQUEUED jobs=%s attempt=%s',r['names'],r['attempt'])
    except Exception as re:log.warning('RETRY_ENQUEUE_FAILED jobs=%s error=%s',r['names'],re)
   catchup=int(cfg['settings'].get('schedule_catchup_minutes',30) or 0)
   due_ids=[]; due_rules=[]
   for j in cfg['jobs']:
    if not j.get('enabled'):continue
    for r in j.get('schedules',[]):
     if not r.get('enabled'):continue
     key=schedule_key(j,r,now,catchup); state_key=f'{j["id"]}:{r["id"]}'
     if key and st.get(state_key)!=key:
      st[state_key]=key; save_scheduler_state(state_key,key); due_ids.append(j['id']); due_rules.append(r.get('name',r['type'])); break
   if due_ids:
    # 自動実行も手動実行と同じ並列ライン設定で動かす。ここを1固定にすると、
    # 対象がまとまって走る夜間バッチほど並列化の効果を受けられない。
    lines=clamp_parallel_lines(cfg['settings'].get('api_parallel_lines',1),cfg)
    log.info('SCHEDULE_BATCH_READY jobs=%s count=%s rules=%s parallel_lines=%s',due_ids,len(due_ids),due_rules,lines)
    # 投入後もスケジューラーは常駐し続ける。ここでreturnするとスレッドが終了し、
    # 以降の自動実行がアプリ再起動まで一切発火しなくなる。
    enqueue_command(due_ids,f'schedule-batch:{len(due_ids)}',lines)
  except:log.exception('スケジュール判定エラー')
 log.info('SCHEDULER_STOPPED reason=stop_event')

def freshness_view():
 """いまのデータが、いつのものか。

 読み手にとっていちばん大事なのは「このファイルはいつのデータか」だが、これまでは
 対象一覧の実績欄に散っていて、まとめて見る場所が無かった。予定を過ぎても実行されて
 いないものも、カレンダーを開いて数えないと分からなかった。"""
 c=load();now=datetime.now();runs=load_job_runs();items=[]
 for j in c['jobs']:
  if not j.get('enabled'):continue
  run=runs.get(j['id']) or {}
  info=last_run_info(run)
  last=info.get('last_run') or ''
  age=None
  if last:
   try:age=int((now-datetime.fromisoformat(last)).total_seconds()//60)
   except Exception:age=None
  prev=job_schedule_preview(j,now)
  nxt=prev.get('next_run')
  # 予定を持っている対象は、その間隔を「これくらいで新しくなるはず」の目安に使う。
  gap=schedule_gap_minutes(j)
  overdue=bool(gap and age is not None and age>gap*2)
  # 実行できたことと、共有先が新しくなったことは別。公開先が使用中だと、成功したのに
  # 共有先は古いままになる。ここで「最新」と出すと、読み手はそれを信じてしまう。
  held=(run.get('metrics') or {}).get('published') is False
  if info.get('last_status')=='failed':state='failed'
  elif not last:state='never'
  elif held:state='held'
  elif overdue:state='stale'
  else:state='ok'
  items.append({'id':j['id'],'name':j['name'],'state':state,'last_run':last,'age_minutes':age,
                'next_run':nxt,'hint':prev.get('hint',''),'expect_minutes':gap,
                'status':info.get('last_status',''),'rows':(run.get('rows') if run else None),
                'output':info.get('last_output',''),'held':bool(held),
                'pending':str((run.get('metrics') or {}).get('pending') or '')})
 bad=[x for x in items if x['state']!='ok']
 held_n=len([x for x in items if x['state']=='held'])
 # 「取れているのに共有先が古い」は、失敗の次に急ぐ。読み手がいま騙されている状態なので、
 # 予定より遅れているだけのものより上へ出す。
 order={'failed':0,'held':1,'stale':2,'never':3,'ok':4}
 items.sort(key=lambda x:(order.get(x['state'],4),-(x['age_minutes'] or 0)))
 if held_n:summary=f'{held_n}件が共有先へ反映できていません'+(f'／ほか{len(bad)-held_n}件が確認待ち' if len(bad)>held_n else '')
 elif bad:summary=f'{len(bad)}件が確認待ちです'
 else:summary=f'{len(items)}件すべて予定どおり新しくなっています'
 return {'ok':not bad,'items':items,'attention':len(bad),'held':held_n,'summary':summary}

def schedule_gap_minutes(job):
 """この対象が新しくなる間隔の目安（分）。予定が無ければ None。"""
 best=None
 for r in job.get('schedules',[]):
  if not r.get('enabled'):continue
  k=r.get('type','daily')
  m={'interval':max(1,int(r.get('interval_minutes',60) or 60)),
     'daily':1440,'weekdays':1440*max(1,7//max(1,len(r.get('weekdays') or [1]))),
     'monthly':1440*30,'specific_dates':1440*30}.get(k,1440)
  best=m if best is None else min(best,m)
 return best




def open_api_catalog(c,rne_path):
 """セッションを開き、データソースへ接続し、RNEを読み込んで (api, handle) を返す。呼び出し側で api.close() すること。"""
 from navigator_api import NavigatorApi
 user,pw,server,_=creds(resolve_path(c['symnavim_conf']))
 api=NavigatorApi(resolve_path(c.get('symnavi_exe','')),log,resolve_path(c.get('navigator_api_dll')) if c.get('navigator_api_dll') else None,base_dir=BASE,search_roots=dll_search_roots(c))
 api.open_session(user,pw,server)
 profiles=api_data_source_profiles(resolve_path(c['symnavim_conf']))
 if not any(p.get('kind')=='oracle' for p in profiles):
  profiles.insert(0,{'section':'NavigatorCredentialFallback','kind':'oracle','user':user,'password':pw,'server':'','option':'','resource':'','resource_kind':'0'})
 for profile in profiles:api.connect_data_source(profile)
 with chdir_lock:
  prev=os.getcwd()
  try:
   os.chdir(Path(rne_path).parent);handle,_=api.open_catalog(Path(rne_path).resolve())
  finally:os.chdir(prev)
 return api,handle


def _spawn_split_parts(job,cfg,user,pw,server,work,jobs_spec,timeout=1800):
 """パートを同時に走らせ、全部そろうのを待つ。戻り値は投入順の結果一覧。"""
 return _spawn_racers(job,cfg,user,pw,server,work,jobs_spec,timeout)

def _spawn_racers(job,cfg,user,pw,server,work,jobs_spec,timeout=1800,stop_when=None,on_tick=None):
 """指定した取り方を独立プロセスで同時に起こし、終わった順に結果を集める。

 終わった順が要るのは競争のためだけではない。どのパートが足を引っ張ったかも、これで分かる。
 stop_when(done) が True を返した時点で、残っているプロセスは中断して打ち切る。
 中断されたプロセスの結果は ok=False / aborted=True で返す（失敗ではなく、要らなくなっただけ）。
 応答が返らないものがあると呼び出し側が返らなくなるため、必ず時間制限もつける。
 """
 procs=[];started=time.perf_counter();deadline=started+max(60,int(timeout))
 for spec in jobs_spec:
  d=work/f'part{spec["index"]}';d.mkdir(parents=True,exist_ok=True)
  payload={'job':job,'cfg':cfg,'user':user,'password':pw,'server':server,
           'split_part':{'out_csv':str(spec['out_csv']),'drop':spec['drop'],'label':spec['label'],
                         'row':spec.get('row'),'row_axis':spec.get('row_axis')}}
  pp=d/'payload.json';pp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
  env=os.environ.copy();env['NAVI_WORKER_RESULT']=str(d/'result.json');env['NAVI_WORKER_LINE']=spec['label']
  env['NAVI_WORKER_STATUS']=str(d/'status.json')
  env['NAVI_WORKER_SPAWN_AT']=repr(time.time())
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  procs.append({'spec':spec,'proc':subprocess.Popen([sys.executable,str(BASE/'api_worker.py'),str(pp)],cwd=str(BASE),env=env,creationflags=flags),
                'result':d/'result.json','status':d/'status.json','done':False})
 done={};order=0
 while any(not p['done'] for p in procs):
  now=time.perf_counter()
  for p in procs:
   if p['done']:continue
   rc=p['proc'].poll()
   if rc is None:
    if now>deadline:
     _kill_proc(p['proc'])
     log.warning('SPLIT_PART_TIMEOUT part=%s timeout=%ss',p['spec']['label'],timeout)
     p['done']=True;order+=1
     done[p['spec']['label']]=dict(ok=False,part=p['spec']['label'],group=p['spec'].get('group',''),
                                   error=f'{timeout}秒を超えたため中止しました',order=order,finished_at=round(now-started,2))
    continue
   p['done']=True;order+=1
   r=_read_worker_json(p['result'],{'ok':False,'part':p['spec']['label'],'error':f'Worker終了コード {rc}'})
   r['group']=p['spec'].get('group','');r['order']=order;r['finished_at']=round(now-started,2)
   done[p['spec']['label']]=r
  if stop_when and done and stop_when(list(done.values())):
   for p in procs:
    if p['done']:continue
    _kill_proc(p['proc']);p['done']=True
    done[p['spec']['label']]=dict(ok=False,aborted=True,part=p['spec']['label'],group=p['spec'].get('group',''),
                                  error='先に決着がついたため中断しました',finished_at=round(time.perf_counter()-started,2))
   break
  if any(not p['done'] for p in procs):
   # 進み具合を知らせる。書きかけのファイルの大きさが唯一の実測なので、それを見てもらう。
   if on_tick:
    try:on_tick(time.perf_counter()-started,[{'spec':p['spec'],'done':p['done'],
                                              'status':_read_worker_json(p['status'],{}) if p['status'].is_file() else {}}
                                             for p in procs])
    except Exception:pass
   time.sleep(0.2)
 return [done[s['label']] for s in jobs_spec]

def _kill_proc(proc):
 try:proc.terminate()
 except Exception:pass
 try:proc.wait(timeout=10)
 except Exception:
  try:proc.kill()
  except Exception:pass


def _split_trial_run(data,c,job):
 """列分割を影実行して、分割なしの結果とバイト比較する。公開はしない。

 別スレッドから呼ばれる。進捗は split_trial_state に書き、画面はそれを見に来る。

 既存の出力ファイルには一切触れない。速さと一致の両方を満たしたときだけ、
 その組み合わせを実運用の判断材料として記録する。
 """
 try:rp=resolve_rne_path(job,c)
 except Exception as e:return dict(ok=False,error=f'RNEパスの解決に失敗しました: {e}')
 if not Path(rp).is_file():return dict(ok=False,error=f'RNEが見つかりません: {rp}')
 # 分け方（列/行/行×列）は、どの条件を課すかを決める。列分割だけの条件を行分割へ持ち込むと
 # 成立するはずの分割が止まるので、いちばん先に確定させる。
 # 以前はこの行が下の方にあり、上の判定が mode を先に読んでいたため、列分割が成立しない
 # RNEで行分割を試すと UnboundLocalError で落ちていた（実測 2026-08-10 SIKAHIKINOW.RNE）。
 mode=str(data.get('mode') or 'column').lower()
 if mode not in ('column','row','grid'):mode='column'
 measure=normalize_measure(data.get('measure'),bool(data.get('race')))
 uses_columns=mode!='row'          # 行分割は列を1本も外さない。列まわりの条件は課さない。
 # 走り出す前に断るときは、必ず理由をログへ残す。以前は黙って戻っていたため、
 # 画面には短い文が出るだけで、なぜ止まったのかがログから追えなかった。
 def stop(reason,**kw):
  log.warning('SPLIT_TRIAL_ABORT rne=%s job=%s mode=%s 理由=%s',rp,job.get('name'),mode,reason)
  return dict(ok=False,error=reason,**kw)
 cached=load_column_cache(rp)
 if not cached or cached['stale'] or not cached['columns']:
  return stop('先に「列の分割可否を調べる」を実行してください（列定義が未取得か、RNEが更新されています）')
 removable=[x['name'] for x in (cached.get('classify') or []) if x.get('removable')]
 if not removable and uses_columns:
  return stop('分割して取得できる列がありません')
 columns=cached['columns'];trials=load_split_trials(rp)
 parts=int(data.get('parts') or 0)
 # 直近の出力から列ごとのデータ量と埋まり具合を測る。分割数の判断にも使うので先に済ませる。
 weights=None;anchors=[];coverage=0.0
 try:
  op=_viewer_output_path(job,c)
  if op.is_file():
   split_trial_stage('列の重みを測定中（直近の出力を1回読みます）',phase='weights',progress=0)
   wt=time.perf_counter();weights=column_weights(op,job,columns)
   if weights:
    anchors,coverage=pick_anchor_columns(removable,weights,int(c['settings'].get('split_anchor_limit',3) or 3))
    log.info('COLUMN_WEIGHTS rne=%s rows=%s total_bytes=%s anchors=%s coverage=%.4f elapsed=%.2fs',
             rp,weights['rows'],weights['total_bytes'],anchors or '(なし)',coverage,time.perf_counter()-wt)
  else:
   log.info('COLUMN_WEIGHTS_SKIP rne=%s 直近の出力ファイルがありません',rp)
 except Exception as we:
  log.warning('COLUMN_WEIGHTS_FAILED rne=%s error=%s',rp,we)
 # 錨が立たない＝担当列がすべて空になる行を防げない。行が落ちると分かっているので実行しない。
 # 行分割は列を外さないため、この心配がそもそも無い。
 if uses_columns and weights and not anchors and not data.get('force'):
  log.warning('SPLIT_NO_ANCHOR rne=%s coverage=%.4f',rp,coverage)
  return stop(f'行をつなぎ留める列（錨）が見つかりませんでした。'
              f'最も埋まっている列でも全行の{coverage*100:.1f}%しか覆えず、残りの行は担当列がすべて空になるため落ちます。'
              '錨を増やしても覆えないため、このRNEの現在の列構成では分割できません。',
              rowset_mismatch=True,anchor_coverage=coverage,no_anchor=True)
 # 同名の列が困るのは、列名で担当を決めて列名で突き合わせる列分割のときだけ。
 # 行分割はどの片も全列を持ち、縦に積むだけなので同名でも取り違えようがない。
 dupes=duplicate_columns(columns)
 if dupes and uses_columns and not data.get('force'):
  log.warning('SPLIT_TRIAL_DUPLICATES rne=%s names=%s',rp,[d['name'] for d in dupes[:10]])
  return stop('同じ名前の列が複数あるため、列分割は行えません（'
                    +'、'.join(f"{d['name']}×{d['count']}" for d in dupes[:5])
                    +('ほか' if len(dupes)>5 else '')
              +'）。列分割は列名で担当を決め、結合でも列名を突き合わせるため、'
               '同名の列があると外す対象を取り違えたり、結合で片方が消えたりします。'
               'RNE側で列名を分けてから再度お試しください。',duplicates=dupes)
 if parts<2:
  parts,_g,_d=recommend_split_parts(columns,removable,int(c['settings'].get('api_parallel_max_lines',4) or 4),
                                    trials,load_rne_timing(rp),weights,c['settings'],split_link_profile(rp))
  if parts<2:parts=2                              # 明示的な試行なので、推奨が1でも2で測る
 plan,keys=plan_column_split(columns,removable,parts,weights,anchors)
 if len(plan)<2 and uses_columns:return stop('この列構成では分割できません')
 # 「列を外すと返る行が変わる」のも列分割固有の話。行分割は列を外さないので当てはまらない。
 if uses_columns and split_incompatible(rp) and not anchors and not data.get('force'):
  return stop('このRNEは、列を外すと返ってくる行そのものが変わることが確認済みです。'
              '行をつなぎ留める錨の列も立てられないため、列分割は使えません。'
              '直近の出力ファイルがあれば錨を探せます。1回実行してから再度お試しください。',
              rowset_mismatch=True,known=True)
 if not keys:
  if uses_columns:return stop('全パートに残る列（結合キー）がないため、結合できません')
  # 行分割はどの片も全列を持つ。突き合わせは全列で行えばよく、結合キーは要らない。
  keys=list(columns)
  log.info('SPLIT_TRIAL_ROW_KEYS rne=%s 結合キーは使いません（行分割はどの片も全列を持ちます）。突き合わせは全%s列で行います',rp,len(keys))
 # 行分割・行×列の組み合わせ。列の割り当てはここまでで出来ているので、行の条件を足す。
 row_axis=None;row_axis_all=[];row_drift=None;row_skew=None;axis_hint={};axis_seconds=0.0;axis_choice=row_axis_choice(data,job);row_parts_want=max(2,min(8,int(data.get('row_parts') or 2)))
 row_parts=row_parts_want
 if mode in ('row','grid') and measure!='normal':
  # 行を絞れるのは管理ポイントだけ。「分け方を探す」で読んだ一覧があればそれを目安に使う。
  # 同じ問い合わせは20秒前後かかるので、ここでは繰り返さない。本番の軸と値は実行の直前に読み直す。
  sv=load_axis_survey(rp)
  if sv:
   row_axis_all=sv.get('axes') or []
   log.info('SPLIT_TRIAL_AXES_CACHED rne=%s 軸=%s本（%s の下調べを目安に使います。実測は実行直前に読み直します）',
            rp,len(row_axis_all),sv.get('taken_at'))
  else:
   log.info('SPLIT_TRIAL_AXES_SKIP rne=%s 下調べがないので、実行直前の読み直しだけで進めます',rp)
  # 軸の決め方は入口で確定させてある（指定が無ければ対象の設定、それも無ければ表側の1番目）。
  scores=axis_balance_scores(job,c,[a.get('name') for a in row_axis_all])
  row_blocks=blocked_row_axes(rp)
  row_axis,ranked,axis_why=pick_row_axis_by_mode(row_axis_all,row_parts,axis_choice['mode'],
                                                 axis_choice['index'],axis_choice['name'],scores,row_blocks)
  log.info('SPLIT_TRIAL_AXIS_MODE rne=%s 決め方=%s → %s',rp,axis_choice['mode'],axis_why)
  for x in ranked:
   _cnt,_chars=row_filter_cost(x,row_parts)
   log.info('SPLIT_TRIAL_AXIS 候補 %s#%s %s 型=%s 値=%s 条件式=%s種/約%s字 使える=%s（%s）',x['location'],x['index']+1,x['name'],
            x['type_name'],x.get('category_count'),_cnt,_chars,x['usable'] and x['enough'],x['reason'])
  axis_hint=row_axis or {}
  if row_axis:
   log.info('SPLIT_TRIAL_AXIS_PICK rne=%s 軸=%s（%s %s番目 / %s）値=%s 期間=%s',
            rp,row_axis['name'],row_axis['location'],row_axis['index']+1,row_axis['type_name'],
            row_axis.get('category_count'),row_axis.get('period'))
 work=LOCAL_RUNTIME/('split_trial_'+datetime.now().strftime('%Y%m%d_%H%M%S'));work.mkdir(parents=True,exist_ok=True)
 user,pw,server,_=creds(resolve_path(c['symnavim_conf']))
 log.info('SPLIT_TRIAL_START rne=%s job=%s mode=%s 列%s分割 行%s分割 columns=%s removable=%s keys=%s transfer_ratio=%.2f',
          rp,job['name'],mode,len(plan) if mode!='row' else 1,row_parts if mode!='column' else 1,
          len(columns),len(removable),len(keys),split_transfer_ratio(columns,removable,len(plan) if mode!='row' else 1))
 try:
  # 1) 分割なし。比較の基準であり、所要時間の基準でもある。
  base_csv=work/'normal.csv';t=time.perf_counter()
  trial_timeout=int(c['settings'].get('split_trial_timeout_seconds',1800) or 1800)
  race=bool(data.get('race'));results=None;split_run=None
  baseline=load_split_baseline(rp)
  if measure=='normal':
   # 基準だけを測る。比較も結合もしない。この値をあとで「分割だけ」の比較に使う。
   split_trial_stage('分割なしを実行中（基準を測ります）',phase='normal',progress=0,parts=1)
   base=_spawn_racers(job,c,user,pw,server,work,
                      [{'index':0,'label':'分割なし','group':'normal','drop':[],'out_csv':base_csv}],trial_timeout,
                      on_tick=lambda el,st:split_trial_tick('normal','分割なしを実行中',[str(base_csv)],expect_bytes,el,expect_seconds,states=st))[0]
   normal_elapsed=time.perf_counter()-t
   if not base.get('ok'):return dict(ok=False,measure='normal',error=f'分割なしの実行に失敗しました: {base.get("error")}')
   try:actual=read_header_names(base_csv,{'output_format':'csv'})
   except Exception:actual=[]
   if actual:columns=actual;save_column_cache(rp,columns,rows=base.get('rows'),source='trial',job=job)
   meta=save_split_baseline(rp,job,base_csv,base,columns,normal_elapsed)
   size=int(base.get('size') or 0)
   log.info('SPLIT_TRIAL_RESULT rne=%s 分割なしのみ rows=%s cols=%s size=%s 実行=%.2fs 保存=%.2fs 合計=%.2fs',
            rp,base.get('rows'),base.get('cols'),size,base.get('execute_elapsed') or 0,base.get('save_elapsed') or 0,normal_elapsed)
   return dict(ok=True,measure='normal',rne=str(rp),job=job['name'],how='分割なし（基準）',
                  rows=base.get('rows'),cols=base.get('cols'),normal_size=size,
                  normal_elapsed=round(normal_elapsed,2),
                  normal_execute=base.get('execute_elapsed'),normal_save=base.get('save_elapsed'),
                  baseline=meta,results=[base],trials=load_split_trials(rp))
  if mode in ('row','grid'):
   # ここが肝。事前に調べた一覧ではなく、いまサーバーが返す値で分割点を決める。
   split_trial_stage('行の軸をいま読み直しています（分割点はこの結果で決めます）',phase='weights',progress=0.8)
   # 本番でも毎回ここを通る。かかった秒数は「分割にすると余分に払う時間」なので、
   # 速さの裏付けから差し引く。差し引かないと本番の見積もりが実態より甘くなる。
   _axis_started=time.perf_counter()
   now=resolve_axis_now(job,c,rp,row_parts,'',hint=axis_hint,choice=axis_choice)
   axis_seconds=round(time.perf_counter()-_axis_started,2)
   log.info('SPLIT_TRIAL_AXIS_COST rne=%s 軸の読み直し=%.2fs（本番でも毎回かかるため、速さの裏付けから差し引きます）',rp,axis_seconds)
   if not now['axis']:
    return dict(ok=False,axes=now['ranked'],
                error=f'実行の直前に軸を読み直したところ、分けられませんでした: {now["error"]}')
   row_axis=now['axis'];row_drift=now['drift']
   row_parts_used=max(1,int(now['parts'] or 0))
   if row_parts_used<2:
    return dict(ok=False,axes=now['ranked'],
                error=f'いま「{row_axis["name"]}」で分けられるのは{row_parts_used}つだけです。'
                      '実行の時点で値が足りません（この瞬間のデータで判断しています）')
   if row_parts_used!=row_parts:
    log.info('SPLIT_TRIAL_PARTS_ADJUST rne=%s 頼まれた%s分割 → いまの値では%s分割',rp,row_parts,row_parts_used)
   row_parts=row_parts_used
   total_rows=int((load_rne_timing(rp) or {}).get('rows') or 0)
   ap=plan_axis_split(row_axis,row_parts,axis_value_weights(job,c,row_axis['name']),total_rows)
   if not ap:
    why=('期間が短すぎます' if row_axis.get('is_time')
         else f'値が{len(row_axis.get("categories") or [])}種しかありません')
    return dict(ok=False,error=f'「{row_axis["name"]}」を{row_parts}つに分けられませんでした（{why}）')
   for x in ap:
    log.info('SPLIT_TRIAL_ROWPART %s/%s %s 見込み%s行',x['index'],row_parts,
             (f"期間 {x['row_axis']['from']}〜{x['row_axis']['to']}" if x['row_axis']['kind']=='period'
              else f"値{len(x['row_axis']['values'])}種"),x['row_axis'].get('expect_rows'))
   # 片寄りの見立て。1つの値に行が集中している軸は、何組に分けても一番重い片が全体を決める。
   # 速くならない理由が分からないまま終わらないよう、ここで数字にしておく。
   row_skew=axis_skew(ap,axis_value_weights(job,c,row_axis['name']))
   if row_skew and row_skew['ratio']>=1.25:
    log.warning('SPLIT_TRIAL_ROW_SKEW rne=%s 軸=%s 一番重い片=%s行（均等なら%s行 / %.2f倍）%s',
                rp,row_axis['name'],row_skew['max_rows'],row_skew['even_rows'],row_skew['ratio'],
                f"最大の値が単独で{row_skew['top_share']:.0%}を占めます" if row_skew.get('top_share') else '')
  if mode=='row':
   part_specs=[{'index':x['index'],'label':f'行{x["index"]}/{row_parts}','group':'split','drop':[],
                'row_axis':x['row_axis'],'row_group':x['index'],'out_csv':work/f'row{x["index"]}.csv'} for x in ap]
  elif mode=='grid':
   part_specs=[]
   for x in ap:
    for cpart in plan:
     part_specs.append({'index':len(part_specs)+1,'label':f'行{x["index"]}×列{cpart["index"]}','group':'split',
                        'drop':list(cpart.get('drop') or []),'row_axis':x['row_axis'],
                        'row_group':x['index'],'col_group':cpart['index'],
                        'out_csv':work/f'g{x["index"]}_{cpart["index"]}.csv'})
  else:
   part_specs=[{'index':p['index'],'label':f'パート{p["index"]}/{len(plan)}','group':'split',
                'drop':p['drop'],'out_csv':work/f'part{p["index"]}.csv'} for p in plan]
  # 表示も記録も「実際に走らせる片の数」で行う。len(plan) は列の割り当ての数で、
  # 行分割のときは常に既定の2のままになり、3分割なのに「2分割」と出ていた。
  pieces=len(part_specs);col_parts=len(plan) if mode!='row' else 1
  with split_trial_lock:split_trial_state.update(mode=mode,pieces=pieces,parts=pieces)
  # 進み具合の目安。前回の出力の大きさと、前回の所要時間があれば、それを使う。
  # どちらも無い初回は経過時間だけで見当をつける（バーは9割で止まり、嘘をつかない）。
  expect_bytes=split_expected_bytes(rp,job,c)
  expect_seconds=(load_rne_timing(rp) or {}).get('total') or None
  part_paths=[str(x['out_csv']) for x in part_specs]
  if race:
   # 同じ回線を奪い合わせて、実際に何秒で決着するかを測る。どちらも最後まで走らせる。
   # 途中で打ち切ると「負けた方が何秒かかったか」が分からず、比較にならない。
   log.info('SPLIT_TRIAL_RACE rne=%s racers=%s（分割なし1本 ＋ %s片）',rp,pieces+1,pieces)
   racers=pieces+1
   split_trial_stage(f'競争中: 分割なし1本 対 {pieces}片（同時に{racers}プロセス）',phase='race',progress=0,parts=pieces)
   # 競争は分割なしと全パートが同時に書かれるので、期待値は「1本ぶん＋パート合計」。
   both=(expect_bytes or 0)*(1+split_expected_share(mode,columns,removable,col_parts,row_parts,weights)*pieces) if expect_bytes else 0
   allr=_spawn_racers(job,c,user,pw,server,work,
                      [{'index':0,'label':'分割なし','group':'normal','drop':[],'out_csv':base_csv}]+part_specs,trial_timeout,
                      on_tick=lambda el,st:split_trial_tick('race',f'競争中（{racers}プロセス同時）',[str(base_csv)]+part_paths,
                                                            both,el,(expect_seconds or 0)*1.6 or None,
                                                            f'{sum(1 for x in st if x["done"])}/{racers}本 完了',states=st))
   base=next((r for r in allr if r.get('group')=='normal'),{})
   results=[r for r in allr if r.get('group')=='split']
   normal_elapsed=base.get('finished_at') or (time.perf_counter()-t)
   split_run=max((r.get('finished_at') or 0) for r in results) if results else 0
   log.info('SPLIT_TRIAL_RACE_ORDER rne=%s %s',rp,' / '.join(
    f"{r.get('part')}={r.get('finished_at')}s" for r in sorted(allr,key=lambda r:r.get('finished_at') or 0)))
  elif measure=='split':
   # 分割だけを測る。基準は前に測って取ってあるものを使う（無ければ比較しないで測るだけ）。
   base={'ok':True,'part':'分割なし（保存済み）','rows':(baseline or {}).get('rows'),'cols':(baseline or {}).get('cols'),
         'size':(baseline or {}).get('size') or 0,'execute_elapsed':(baseline or {}).get('execute'),
         'save_elapsed':(baseline or {}).get('save'),'stored':True}
   normal_elapsed=float((baseline or {}).get('elapsed') or 0)
   if baseline:
    base_csv=Path(baseline['file'])
    if baseline.get('columns'):columns=list(baseline['columns']);keys=[x for x in columns if x not in set(removable)]
    log.info('SPLIT_TRIAL_BASELINE rne=%s 保存済みの基準を使います rows=%s size=%s elapsed=%.2fs 取得=%s（%s日前）',
             rp,baseline.get('rows'),baseline.get('size'),normal_elapsed,baseline.get('taken_at'),baseline.get('age_days'))
   else:
    log.info('SPLIT_TRIAL_BASELINE rne=%s 保存済みの基準がありません。比較せず分割だけを測ります',rp)
  else:
   split_trial_stage(f'分割なしを実行中（{split_how_label(mode,col_parts,row_parts)}と比較します）',phase='normal',progress=0,parts=pieces)
   base=_spawn_racers(job,c,user,pw,server,work,[{'index':0,'label':'分割なし','group':'normal','drop':[],'out_csv':base_csv}],trial_timeout,
                      on_tick=lambda el,st:split_trial_tick('normal','分割なしを実行中',[str(base_csv)],expect_bytes,el,expect_seconds,states=st))[0]
   normal_elapsed=time.perf_counter()-t
  if not base.get('ok'):return dict(ok=False,error=f'分割なしの実行に失敗しました: {base.get("error")}')
  # 列の並び順は、たった今実行した「分割なし」の見出し行を正とする。
  # 直近の出力ファイルはRNEを差し替えた直後だと古く、列数が食い違う（178対177）。
  try:
   actual=read_header_names(base_csv,{'output_format':'csv'}) if not base.get('stored') else []
  except Exception as he:
   actual=[];log.warning('SPLIT_TRIAL_HEADER_FAILED rne=%s error=%s',rp,he)
  if actual and actual!=columns:
   log.info('SPLIT_TRIAL_COLUMNS_REFRESH rne=%s cached=%s actual=%s 分割なしの見出しを正として採用',rp,len(columns),len(actual))
   added=[x for x in actual if x not in set(columns)]
   if added:log.info('SPLIT_TRIAL_COLUMNS_ADDED %s',' | '.join(added[:20]))
   columns=actual
   redup=duplicate_columns(columns)
   if redup and not data.get('force'):
    log.warning('SPLIT_TRIAL_DUPLICATES_ACTUAL rne=%s names=%s',rp,[d['name'] for d in redup[:10]])
    return dict(ok=False,duplicates=redup,
                error='実行した結果に同じ名前の列が含まれていたため、結合を行いませんでした（'
                      +'、'.join(f"{d['name']}×{d['count']}" for d in redup[:5])+'）。'
                      'RNE側で列名を分けてから再度お試しください。出力ファイルは更新していません。')
   save_column_cache(rp,columns,rows=base.get('rows'),source='trial',job=job)
   # 追加された列は分類が無いので固定列として扱う（全パートに残る＝結合に影響しない）。
   keys=[c for c in columns if c not in set(removable)]
  # 2) 分割あり。パートは同時に走らせる（競争のときは 1) で一緒に走り終えている）。
  if mode!='row':
   log.info('SPLIT_PLAN rne=%s 列%s分割 anchors=%s keep=%s bytes=%s',rp,col_parts,anchors or '(なし)',
            [len(p['keep']) for p in plan],[p.get('bytes') for p in plan])
  if results is None:
   # ここからは「分割なし」の実測がある。期待するバイト数も所要時間も、そこから作れる。
   split_bytes=(base.get('size') or 0)*split_expected_share(mode,columns,removable,col_parts,row_parts,weights)*pieces
   split_seconds=(normal_elapsed*predict_split_gain(columns,removable,col_parts,trials,load_rne_timing(rp),weights,split_link_profile(rp))
                  if mode=='column' else normal_elapsed)
   how=split_how_label(mode,col_parts,row_parts)
   # 基準が無い（「分割だけ測る」で、保存された基準も無い）ときに 0秒 と出すと嘘になる。
   vs=f'・分割なしは {normal_elapsed:.0f}秒' if normal_elapsed>0 else '・くらべる基準はまだありません'
   split_trial_stage(f'{how}を並列実行中（{pieces}プロセス同時{vs}）',phase='split',progress=0)
   t=time.perf_counter()
   results=_spawn_racers(job,c,user,pw,server,work,part_specs,trial_timeout,
                         on_tick=lambda el,st:split_trial_tick('split',f'{how}を並列実行中',
                                                               [str(x['out_csv']) for x in part_specs],split_bytes,el,split_seconds or None,
                                                               f'{sum(1 for x in st if x["done"])}/{pieces}片 完了',states=st))
   split_run=time.perf_counter()-t
  bad=[r for r in results if not r.get('ok')]
  if any(r.get('row_condition_ineffective') for r in bad):
   log.warning('SPLIT_TRIAL_ROWCOND_INEFFECTIVE rne=%s 列=%s 返った行数=%s（見込み %s）',
               rp,(row_axis or {}).get('name'),[r.get('rows') for r in bad],[r.get('expected_rows') for r in bad])
   record_split_trial(rp,job,pieces,None,None,normal_elapsed,None,False,
                      detail=f'{mode}: 行の軸で絞れず全件が返りました 軸={(row_axis or {}).get("name")}')
   return dict(ok=False,row_condition_ineffective=True,parts=pieces,results=results,
                  row_column=(row_axis or {}).get('name',''),normal_rows=base.get('rows'),
                  part_rows=[{'part':r.get('part'),'rows':r.get('rows'),'expected':r.get('expected_rows'),
                              'locate':r.get('row_locate',''),'form':r.get('row_form','')} for r in results],
                  error='行の条件が効きませんでした。条件の設定そのものは成功しています（rc=OK）が、'
                        'どのパートもほぼ全件を返しました。結合すると同じ行が'
                        f'{pieces}倍に増えるため、ここで中止しています。出力ファイルは更新していません。')
  if bad:
   # 「条件式が長すぎる」は、この軸の値が多すぎることが原因。何度やっても同じなので、
   # その軸を覚えて次から選ばないようにし、画面には次の手を書く。
   toolong=[r for r in bad if r.get('filter_too_long')]
   if toolong and row_axis:
    vals=max(int(r.get('row_axis_values') or 0) for r in toolong) or int(row_axis.get('category_count') or 0)
    block_row_axis(rp,row_axis.get('name',''),
                   f'{row_parts}分割で1片が外す値が多すぎ、検索条件式が長すぎるとサーバーに拒否されました',
                   server_message=str(toolong[0].get('error') or ''),parts=row_parts,values=vals)
    _cnt,_chars=row_filter_cost(row_axis,row_parts)
    record_split_trial(rp,job,pieces,None,None,normal_elapsed,None,False,
                       detail=f'{mode}: 条件式が長すぎる 軸={row_axis.get("name")} 値={vals}種')
    return dict(ok=False,parts=pieces,results=results,filter_too_long=True,
                   row_column=row_axis.get('name',''),row_values=vals,
                   error=f'「{row_axis.get("name","")}」は値が{vals:,}種あり、{row_parts}分割すると1片で'
                         f'約{_cnt:,}種（{_chars:,}字）を条件式へ並べることになります。'
                         'データベースが受け付ける長さを超えたため、問い合わせが拒否されました'
                         '（KVR52020 検索条件式が長すぎます）。'
                         'この軸は以後選ばないよう記録しました。値の種類が少ない軸（数十〜数百種）を選ぶと通ります。'
                         '出力ファイルは更新していません。')
   return dict(ok=False,error='分割実行に失敗しました: '+'; '.join(f'{r.get("part")}: {r.get("error")}' for r in bad),
                  parts=pieces,results=results)
  # 3) 結合して、分割なしの結果と突き合わせる。
  how={'column':f'{pieces}パートを横につなぎます','row':f'{pieces}パートを縦に積みます',
       'grid':f'{pieces}片を横につないでから縦に積みます'}[mode]
  split_trial_stage(f'結合中（{how}）',phase='merge',progress=0)
  merged=work/'merged.csv';t=time.perf_counter()
  try:
   if mode=='row':
    # 行は重複しないので、順に積むだけ。値の突き合わせは要らない。
    mrows,mcols=merge_row_parts([r['file'] for r in results],merged)
   elif mode=='grid':
    # まず行の組ごとに横へつなぎ、そのあと縦に積む。
    byrow={}
    for spec,r in zip(part_specs,results):byrow.setdefault(spec['row_group'],[]).append(r['file'])
    stitched=[]
    for g in sorted(byrow):
     out=work/f'rowgroup{g}.csv';merge_column_parts(byrow[g],out,keys,columns);stitched.append(out)
    mrows,mcols=merge_row_parts(stitched,merged)
   else:
    mrows,mcols=merge_column_parts([r['file'] for r in results],merged,keys,columns)
  except SplitRowsetMismatch as me:
   # 列を外すと返る行が変わる問い合わせ。速さ以前に分割が成立しないので、以後は勧めない。
   log.warning('SPLIT_TRIAL_ROWSET_MISMATCH rne=%s %s rows=%s error=%s',rp,split_how_label(mode,col_parts,row_parts),[r.get('rows') for r in results],me)
   record_split_trial(rp,job,pieces,None,None,normal_elapsed,None,False,
                      detail=f'{mode}: rowset first={me.first_rows} other={me.other_rows} part={me.part}')
   return dict(ok=False,error=str(me),parts=pieces,results=results,rowset_mismatch=True,
                  part_rows=[{'part':r.get('part'),'rows':r.get('rows'),'cols':r.get('cols')} for r in results],
                  normal_rows=base.get('rows'))
  except Exception as me:
   log.warning('SPLIT_TRIAL_MERGE_FAILED rne=%s error=%s',rp,me)
   return dict(ok=False,error=f'結合に失敗しました: {me}',parts=pieces,results=results)
  merge_elapsed=time.perf_counter()-t;split_elapsed=split_run+merge_elapsed
  # 比べる相手が無い場合（基準を1度も測っていない「分割だけ」）は、測るところまでで終える。
  compared=Path(base_csv).is_file()
  if compared:
   split_trial_stage('結果を比較中（分割なしと1行ずつ突き合わせます）'
                     +('' if not base.get('stored') else '［保存済みの基準］'),phase='compare',progress=0)
   cmp=compare_csv_content(base_csv,merged,keys,axis_column=(row_axis or {}).get('name',''))
  else:
   cmp={'reason':'比べる相手がありません（「分割なしだけ」を1度実行すると、次から比較できます）',
        'rows_a':None,'rows_b':mrows,'content_identical':False,'count_match':None}
  identical=bool(cmp.get('content_identical'))     # 並び順の違いは不一致としない
  log.info('SPLIT_TRIAL_COMPARE rne=%s byte_identical=%s content_identical=%s order_match=%s diff_rows=%s diff_cells=%s only_normal=%s only_merged=%s reason=%s',
           rp,cmp.get('byte_identical'),cmp.get('content_identical'),cmp.get('order_match'),
           cmp.get('diff_rows'),cmp.get('diff_cells'),cmp.get('only_in_a'),cmp.get('only_in_b'),cmp.get('reason'))
  for sm in (cmp.get('samples') or [])[:3]:
   log.info('SPLIT_TRIAL_DIFF key=%s %s',sm['key'],'; '.join(f"{c['name']}: 分割なし={c['a']!r} 結合={c['b']!r}" for c in sm['columns']))
  mx=cmp.get('missing_axis')
  if mx:
   # 欠けた行が1つの値に集中していれば絞り方の取りこぼし、ばらけていれば実行中にデータが動いただけ。
   why=('（すべて値が空の行です＝どのカテゴリにも当てはまらない行が落ちています。'
        'NaviReloadCategory の nonmatch に NAVI_NONMATCH を渡す必要があります）' if mx.get('all_blank')
        else '（1つの値に集中しています＝絞り方の取りこぼしです）' if mx['concentrated']
        else '（値がばらけています＝実行中にデータが動いた可能性が高いです）')
   log.warning('SPLIT_TRIAL_MISSING rne=%s 欠けた%s行の「%s」= %s種%s / 内訳: %s',
               rp,cmp.get('only_in_a'),mx['column'],mx['distinct'],why,
               ' / '.join(f"{x['value']!r}×{x['rows']}行" for x in mx['top']))
  a=base_csv.read_bytes() if compared else b''
  b=merged.read_bytes()
  detail='' if identical else f'diff_rows={cmp.get("diff_rows")} diff_cells={cmp.get("diff_cells")}'
  metrics={'normal_bytes':base.get('size'),'normal_save':base.get('save_elapsed'),'normal_execute':base.get('execute_elapsed'),
           'parts':[{'bytes':r.get('size'),'save':r.get('save_elapsed'),'execute':r.get('execute_elapsed'),'cols':r.get('cols')} for r in results],
           'fixed_share':(split_payload_profile(columns,removable,weights) or {}).get('fixed_share')}
  # 競争させた回は、両者が同じ回線を奪い合った値なので、単独で測った値と混ぜてはいけない。
  # 印を付けて残し、回線の見積もりと速度比の平均からは外す。
  metrics['race']=race;metrics['mode']=mode
  if mode!='column':metrics['row_column']=(row_axis or {}).get('name','');metrics['row_parts']=row_parts
  # 種類の違う試行を混ぜない。'列2分割' と '行2分割' は意味が違うので、平均を取ると嘘になる。
  tag=('race: ' if race else '')+('' if mode=='column' else f'{mode}: ')+('baseline: ' if base.get('stored') else '')
  speedup=(record_split_trial(rp,job,pieces,mrows,mcols,normal_elapsed,split_elapsed,identical,tag+detail,metrics)
           if normal_elapsed else None)
  if not normal_elapsed:
   log.info('SPLIT_TRIAL rne=%s %s 片数=%s split=%.2fs（基準が無いため速度比は出しません）',
            rp,split_how_label(mode,col_parts,row_parts),pieces,split_elapsed)
  # 実際に走らせた「分割なし」は基準として取っておく。次からは「分割だけ」で測れる。
  if measure=='both' and not base.get('stored'):
   save_split_baseline(rp,job,base_csv,base,columns,normal_elapsed)
  # 結果が一致した割り当ては、速さに関わらず保存する。「自動」は速さの裏付けも見るが、
  # 「競争」は速さを問わない（遅ければ競争に負けて捨てられるだけ）。
  # 実行時に測り直さないで済むよう、担当列の割り当てそのものを保存する。
  min_sp=float(c['settings'].get('split_min_speedup',1.05) or 1.05)
  plan_saved=False
  # 本番で払う時間は「分割の実行＋結合」に加えて、行を使う形では「軸の読み直し」も要る。
  # 裏付けとして残すのは、その全部を含めた実力値。見かけの倍率は別に残して両方見せる。
  run_elapsed_est=split_elapsed+(axis_seconds if mode in ('row','grid') else 0)
  run_speedup=(normal_elapsed/run_elapsed_est) if (normal_elapsed and run_elapsed_est>0) else None
  if identical and normal_elapsed:
   # 競争中の速度比は回線の奪い合いで沈むので、裏付けとしては記録しない（自動には使わせない）。
   proof=None if race else run_speedup
   rowspec=None
   if mode in ('row','grid'):
    rowspec={'parts':row_parts,'axis_name':(row_axis or {}).get('name',''),
             'axis_location':(row_axis or {}).get('location',''),'axis_index':(row_axis or {}).get('index',0),
             'axis_type':(row_axis or {}).get('type_name',''),'is_time':bool((row_axis or {}).get('is_time')),
             'choice_mode':axis_choice['mode'],'choice_index':axis_choice['index'],'choice_name':axis_choice['name'],
             'axis_seconds':axis_seconds,'raw_speedup':round(speedup,3) if speedup else None,
             'skew':(row_skew or {}).get('ratio')}
   plan_saved=save_split_plan(rp,columns,pieces if mode!='column' else col_parts,plan,keys,anchors,proof,mrows,mcols,
                              source='race' if race else 'trial',mode=mode,row=rowspec)
   if plan_saved and mode in ('row','grid'):
    log.info('SPLIT_PLAN_SAVE_ROW rne=%s %s 軸=%s 見かけ=%s倍 / 軸の読み直し%.1fsを含めた実力=%s倍',
             rp,split_how_label(mode,col_parts,row_parts),(row_axis or {}).get('name',''),
             f'{speedup:.2f}' if speedup else '-',axis_seconds,f'{run_speedup:.2f}' if run_speedup else '-')
  elif identical:
   log.info('SPLIT_PLAN_NOT_SAVED rne=%s mode=%s 基準（分割なし）を測っていないため、速さの裏付けが作れません',rp,mode)
  else:
   log.info('SPLIT_PLAN_NOT_SAVED rne=%s %s identical=%s speedup=%s 結果が一致しないため保存しません（理由: %s）',
            rp,split_how_label(mode,col_parts,row_parts),identical,f'{speedup:.2f}' if speedup else '-',cmp.get('reason'))
  lp=split_link_profile(rp)
  log.info('SPLIT_LINK rne=%s 回線の上限=%s KB/s 直近の単一速度=%s KB/s 伸びしろ=%s倍 有効な分割数=%s 実測=%s',
           rp,lp.get('capacity_kbs'),lp.get('base_kbs'),lp.get('headroom'),split_useful_parts(lp),
           [(p['parts'],p['base_kbs'],p['aggregate_kbs'],p['sigma']) for p in lp['points']])
  log.info('SPLIT_TRIAL_RESULT rne=%s %s 片数=%s identical=%s normal=%.2fs split=%.2fs(実行%.2fs+結合%.2fs) speedup=%s 行数=分割なし%s/結合%s',
           rp,split_how_label(mode,col_parts,row_parts),pieces,identical,normal_elapsed,split_elapsed,split_run,merge_elapsed,
           f'{speedup:.2f}' if speedup else '-',cmp.get('rows_a'),cmp.get('rows_b'))
  return dict(ok=True,measure=measure,compared=compared,baseline_used=bool(base.get('stored')),
                 baseline=(baseline if base.get('stored') else None),
                 rne=str(rp),job=job['name'],parts=pieces,identical=identical,mode=mode,
                 axis_seconds=axis_seconds or None,run_speedup=round(run_speedup,2) if run_speedup else None,
                 shape_label=split_shape_label(mode,col_parts,row_parts),
                 row_parts=row_parts if mode!='column' else 0,column_parts=col_parts,how=split_how_label(mode,col_parts,row_parts),
                 row_column=(row_axis or {}).get('name',''),row_axis=(dict(row_axis,categories=(row_axis.get('categories') or [])[:12]) if row_axis else None),
                 row_location=(row_axis or {}).get('location',''),row_type=(row_axis or {}).get('type_name',''),
                 row_parts_want=row_parts_want,row_drift=row_drift,row_skew=row_skew,
                 row_part_rows=[{'part':r.get('part'),'rows':r.get('rows'),'expected':r.get('expected_rows')}
                                for r in (results or []) if r.get('rows') is not None],
                 rows=mrows,cols=mcols,key_count=len(keys),
                 normal_elapsed=round(normal_elapsed,2) if normal_elapsed else None,
                 split_elapsed=round(split_elapsed,2),
                 split_run_elapsed=round(split_run,2),merge_elapsed=round(merge_elapsed,2),
                 speedup=round(speedup,2) if speedup else None,
                 transfer_ratio=round(split_expected_share(mode,columns,removable,col_parts,row_parts)*pieces,2),
                 normal_size=len(a),merged_size=len(b),results=results,compare=cmp,
                 parts_plan=[{'index':p['index'],'keep':len(p['keep']),'drop':len(p['drop'])} for p in plan],
                 plan_saved=bool(plan_saved),min_speedup=min_sp,split_mode=normalize_split_mode(job.get('split_mode')),
                 race=race,race_winner=('split' if split_elapsed<normal_elapsed else 'normal') if race else '',
                 race_order=[{'part':r.get('part'),'at':r.get('finished_at')} for r in
                             sorted(([base]+list(results)),key=lambda r:r.get('finished_at') or 0)] if race else [],
                 trials=load_split_trials(rp))
 except Exception as e:
  log.exception('SPLIT_TRIAL_FAILED rne=%s',rp)
  return dict(ok=False,error=str(e))
 finally:
  # 影実行の中間ファイルは残さない。公開もしていないので、ここで完結させる。
  try:shutil.rmtree(work,ignore_errors=True)
  except Exception:pass


# ---- 影実行の進行状態 -------------------------------------------------------
# 影実行は数分かかる。画面を占有すると、その間ログも他の機能も見られないため、
# 別スレッドで走らせて、状態だけを画面へ渡す。
split_trial_lock=threading.Lock()
def split_trial_blank(**over):
 """影実行の進み具合を白紙に戻した状態。始めるときは必ずここから作り直す。

 前は running と stage だけを書き換えていたので、percent・バイト数・片ごとの進み具合が
 前回のまま残り、始めた直後に「前回の100%のバー」と「前回の片」が見えていた。
 """
 st={'running':False,'stage':'','job':'','job_id':'','rne':'','started':0.0,'elapsed':0.0,'result':None,'parts':0,
     'percent':0,'phase':'','phase_index':0,'phase_total':4,'bytes':0,'expected_bytes':0,'note':'',
     'part_progress':[],'mode':'','pieces':0}
 st.update(over);return st

split_trial_state=split_trial_blank()

# 影実行の進み具合。工程ごとに、全体のどこからどこまでを占めるかを決めておく。
# 実測できるのは「書き出されつつあるファイルの大きさ」だけなので、進み具合はそこから出す。
# 大きさが分からない工程（重みの測定・結合）は、その工程の始まりの値のまま置く。
SPLIT_TRIAL_PHASES={'weights':(0,5,'列の重みを測定中'),'normal':(5,50,'分割なしを実行中'),
                    'split':(50,90,'分割を並列実行中'),'race':(5,90,'競争中'),
                    'merge':(90,97,'結合中'),'compare':(97,100,'結果を比較中')}

def split_expected_bytes(rne_path,job,cfg):
 """今回どれくらいのバイト数が返ってきそうか。進み具合の分母にだけ使う。

 いちばん確かなのは前回の影実行で測った「分割なし」の実バイト数。無ければ直近の出力ファイルの
 大きさで代用する（形式が違えば目安にしかならないが、分母としては十分）。
 """
 try:
  with settings_connection() as c:
   for r in c.execute("SELECT metrics FROM split_trials WHERE rne_key=? AND metrics<>'' ORDER BY id DESC LIMIT 5",(_rne_key(rne_path),)):
    nb=(_json_or_empty(r['metrics']) or {}).get('normal_bytes')
    if nb:return int(nb)
 except Exception:pass
 try:
  op=_viewer_output_path(job,cfg)
  if op.is_file():return int(op.stat().st_size)
 except Exception:pass
 return 0

_split_stage_logged={'text':'','at':0.0}
def split_trial_stage(stage,phase='',progress=None,**extra):
 """進み具合を書き込む。phase を渡すと、その工程の受け持ち範囲へ progress(0..1)を割り当てる。

 画面へは毎回書くが、ログは工程が変わったときと10秒ごとだけにする。0.4秒ごとに出すと
 1回の影実行で数百行になり、肝心の実測値が埋もれてしまうため。
 """
 lo,hi,_=SPLIT_TRIAL_PHASES.get(phase or '',(None,None,''))
 fields=dict(extra)
 if lo is not None:
  pct=lo if progress is None else lo+(hi-lo)*max(0.0,min(1.0,float(progress)))
  fields['percent']=round(pct,1);fields['phase']=phase
 with split_trial_lock:
  split_trial_state.update(stage=stage,elapsed=round(time.time()-(split_trial_state.get('started') or time.time()),1),**fields)
 head=stage.split('（')[0];now=time.time()
 if head!=_split_stage_logged['text'] or now-_split_stage_logged['at']>=10:
  _split_stage_logged.update(text=head,at=now);log.info('SPLIT_TRIAL_STAGE %s',stage)

SPLIT_PART_STEPS=['接続','RNEを開く','担当外の列を外す','行の条件を設定','問い合わせを実行','CSVへ保存','完了']

def split_part_progress(paths,states,expected_bytes):
 """パート1本ごとの進み具合。全体を1本の棒にまとめると、どのパートが遅れているのかも、
 いま何をしているのかも分からない。パートごとに「工程」と「書けたバイト数」を出す。

 工程はワーカーが status.json に書いたものをそのまま使う。バイト数は書きかけのCSVの
 大きさで、これが唯一の実測。分母は全体の見込みをパート数で割った値。
 """
 n=max(1,len(paths));each=(float(expected_bytes)/n) if expected_bytes else 0
 out=[]
 for i,f in enumerate(paths):
  try:b=Path(f).stat().st_size
  except Exception:b=0
  st=(states[i] if i<len(states) else {}) or {}
  info=st.get('status') or {}
  done=bool(st.get('done'))
  step=('完了' if done else (info.get('step') or '準備中'))
  pct=100.0 if done else (min(99.0,b/each*100.0) if each and b else 0.0)
  out.append({'part':(st.get('spec') or {}).get('label') or info.get('part') or f'{i+1}',
              'step':step,'step_index':(SPLIT_PART_STEPS.index(step)+1) if step in SPLIT_PART_STEPS else 0,
              'step_total':len(SPLIT_PART_STEPS),'bytes':b,'expected_bytes':int(each),
              'percent':round(pct,1),'done':done,'rows':info.get('rows') or 0,
              'elapsed':info.get('elapsed') or 0})
 return out

def split_trial_tick(phase,stage,paths,expected_bytes,elapsed,expected_seconds=None,note='',states=None):
 """走っている最中の進み具合を更新する。

 バイトで測れるならバイトで測る（これが唯一の実測）。まだ1バイトも出ていない間は
 サーバ側の問い合わせ実行中なので、そこだけ経過時間で見当をつける。
 見当は上限を9割に抑える。実測が始まる前に満杯にすると、バーが嘘をつくため。
 """
 got=0
 for f in paths:
  try:got+=Path(f).stat().st_size
  except Exception:pass          # まだ作られていないファイルは 0 として数える
 if expected_bytes and got:
  prog=min(0.99,got/float(expected_bytes))
  detail=f'{got/1024/1024:.1f} / 約{expected_bytes/1024/1024:.1f}MB'
 elif expected_seconds:
  prog=min(0.9,float(elapsed)/float(expected_seconds))
  detail=f'{elapsed:.0f}秒 / 見込み約{expected_seconds:.0f}秒'
 else:
  prog=min(0.9,float(elapsed)/120.0);detail=f'{elapsed:.0f}秒経過'
 split_trial_stage(f'{stage}（{detail}{"・"+note if note else ""}）',phase=phase,progress=prog,
                   bytes=got,expected_bytes=int(expected_bytes or 0),note=note,
                   part_progress=split_part_progress(paths,states or [],expected_bytes))





def row_split_breakdown(timing,deferred):
 """所要時間を「サーバー側で結果を作る時間」と「転送の時間」へ分ける。

 通常の実行(DOWNLOADNOW)は結果を作って送るところまでを含む。転送なしの実行(DOWNLOADLATER)は
 作るところまで。差が転送。行分割で縮む見込みがあるのはサーバー側で、転送は回線の上限に頭を
 押さえられる（ただし行分割は運ぶ量そのものを減らすので、そこは列分割より有利）。
 """
 t=timing or {};ex=float(t.get('execute') or 0);sv=float(t.get('save') or 0);total=ex+sv
 if not total:return {'known':False}
 if not deferred:return {'known':False,'execute':round(ex,2),'save':round(sv,2)}
 srv=max(0.0,min(ex,float(deferred.get('execute_seconds') or 0)))
 dl=max(0.0,ex-srv)                      # 通常の実行のうち、サーバー側の処理を除いた残り＝受信
 rows=t.get('rows') or deferred.get('rows') or 0
 out={'known':True,'execute':round(ex,2),'save':round(sv,2),'total':round(total,2),
      'server_seconds':round(srv,2),'download_seconds':round(dl,2),'format_seconds':round(sv,2),
      'server_share':round(srv/total,3),'download_share':round(dl/total,3),'format_share':round(sv/total,3),
      'rows':rows,
      # 旧来の呼び出し口。受信＋整形をまとめて「転送」と呼んでいたが、中身は別物なので内訳も返す。
      'transfer_seconds':round(dl+sv,2),'transfer_share':round((dl+sv)/total,3)}
 b=t.get('bytes') or 0
 if b:
  out['bytes']=int(b)
  out['download_kbs']=round(b/1024/dl,1) if dl>0 else None
  out['format_kbs']=round(b/1024/sv,1) if sv>0 else None
 return out



# ==== まとめて測る（ALL-IN） =============================================
# 1本ずつ測らせると、どれとどれを比べたのか、基準はいつのものか、を利用者が
# 覚えることになる。同じ基準の上で続けて測り、速い順に並べたものを返す。
#
# 基準（分割なし）は最初に1回だけ測る。以降の分け方は measure='split' で
# その基準と比べるので、N通りを測るのに N+1 回で済む（2N回にならない）。
SPLIT_BATCH_SHAPES=('column','row','grid')
SPLIT_BATCH_MAX=8
split_batch_lock=threading.RLock()
def split_batch_blank(**over):
 st={'running':False,'kind':'','job':'','job_id':'','rne':'','started':0.0,'elapsed':0.0,
     'index':0,'total':0,'items':[],'error':'','stop':False,'finished_at':''}
 st.update(over);return st
split_batch_state=split_batch_blank()

def split_batch_items(kind,data,job):
 """何を何回測るかを、始める前に確定させる。画面にもそのまま出す。"""
 items=[]
 parts=max(0,min(8,int(data.get('parts') or 0)))
 row_parts=max(2,min(8,int(data.get('row_parts') or 2)))
 if not data.get('reuse_baseline') or not load_split_baseline(resolve_rne_path(job,load())):
  items.append({'key':'normal','label':'分割なし（基準）','shape':'normal','axis':'',
                'why':'ほかの分け方は、この時間と比べます'})
 if kind=='axes':
  for name in [str(x).strip() for x in (data.get('axes') or []) if str(x).strip()][:SPLIT_BATCH_MAX]:
   items.append({'key':f'row:{name}','label':f'行{row_parts}分割（{name}）','shape':'row','axis':name,
                 'why':'この軸で行を絞ったときの速さ'})
 else:
  # 指定が無ければ3通りとも。空の一覧を渡されたときは「1つも選んでいない」として扱う
  # （既定へ勝手に戻すと、外したはずの分け方が測られる）。
  raw=data.get('shapes')
  want=[x for x in (SPLIT_BATCH_SHAPES if raw is None else raw) if x in SPLIT_BATCH_SHAPES]
  for shape in want:
   items.append({'key':shape,'label':split_how_label(shape,parts or 2,row_parts),'shape':shape,'axis':'',
                 'why':{'column':'列を分けて横につなぐ','row':'行を絞って縦に積む',
                        'grid':'行と列の両方で分ける'}[shape]})
 for x in items:x.update(state='待機',elapsed=None,speedup=None,identical=None,rows=None,error='',detail='')
 return items[:SPLIT_BATCH_MAX+1]

def split_batch_run_data(item,data):
 """1件ぶんの影実行に渡す指定。基準は1回だけ測り、以降はそれと比べる。"""
 d={'job_id':data.get('job_id'),'parts':int(data.get('parts') or 0),
    'row_parts':max(2,min(8,int(data.get('row_parts') or 2))),'race':False}
 if item['shape']=='normal':return dict(d,mode='column',measure='normal')
 d.update(mode=item['shape'],measure='split')
 if item.get('axis'):d.update(row_axis_mode='name',row_axis_name=item['axis'],row_axis_index=1)
 else:
  d.update(row_axis_mode=data.get('row_axis_mode'),row_axis_name=data.get('row_axis_name'),
           row_axis_index=data.get('row_axis_index'))
 return d

def split_batch_summary(items):
 """速い順に並べる。結果が一致しなかったものは順位を付けない（使えないため）。"""
 done=[x for x in items if x['state']=='完了' and x.get('elapsed')]
 base=next((x['elapsed'] for x in done if x['shape']=='normal'),None)
 rank=sorted([x for x in done if x['shape']!='normal' and x.get('identical')],key=lambda x:x['elapsed'])
 out=[]
 for i,x in enumerate(rank,1):
  out.append({'rank':i,'key':x['key'],'label':x['label'],'shape':x['shape'],'axis':x.get('axis',''),
              'elapsed':x['elapsed'],'speedup':x.get('speedup'),
              'saved':round(base-x['elapsed'],1) if base else None})
 return {'baseline':base,'ranked':out,
         'best':out[0] if out else None,
         'rejected':[{'label':x['label'],'why':x.get('error') or ('結果が一致しませんでした' if x.get('identical') is False else '測れませんでした')}
                     for x in items if x['state'] in ('失敗','完了') and not (x['state']=='完了' and (x.get('identical') or x['shape']=='normal'))]}




# ==== 調べものを裏で走らせる ============================================
# 「中身を読む」「分け方を探す」はサーバーへ問い合わせるので20秒前後かかる。
# これまでは待機モーダルで画面を塞いでいたが、影実行と同じように裏で走らせ、
# 進み具合を出して、閉じても続くようにする。
#
# 中身は既存の口をそのまま呼ぶ。ふるまいを二重に持たないためで、
# test_request_context はスレッドごとに独立しているので同時に走らせても混ざらない。
INSPECT_TASK_SPECS={
 'read':  ('period_control_points','/api/period-control-points','中身を読む',
           'RNEを開いて、管理ポイントとデータ項目を読んでいます',22.0),
 'column':('column_plan','/api/column-plan','列の分け方を探す',
           '列定義を用意して、分割できる列を判定しています',8.0),
 'row':   ('row_split_plan','/api/row-split-plan','行の分け方を探す',
           'RNEから、行を絞れる軸（管理ポイント）を読んでいます',24.0),
}
# 「RNEを調査」は上の3つを続けて走らせる。読むものは同じで、分けて押す理由が無い。
# 別々に押させると、どれをどの順で押したかを利用者が覚えることになる。
INSPECT_ALL_ORDER=('read','column','row')
INSPECT_ALL_SPEC=('RNEを調査','中身・列・行をまとめて読み、この RNE の控えとして保存しています',
                  sum(INSPECT_TASK_SPECS[k][4] for k in INSPECT_ALL_ORDER))
inspect_task_lock=threading.RLock()
def inspect_task_blank(**over):
 st={'running':False,'kind':'','stage':'','title':'','job':'','job_id':'','rne':'',
     'started':0.0,'elapsed':0.0,
     'percent':0.0,'result':None,'error':'','expected':0.0,'measured':False}
 st.update(over);return st

def task_target(data):
 """どの対象・どのRNEを調べているのかを、状態と一緒に持ち回るために取り出す。

 これが無いと、画面はどの調べものの結果なのか区別できず、別の対象の編集画面を
 開いても前の結果がそのまま出ていた（同じ内容がどのRNEでも出る、の原因）。
 """
 jid=str(data.get('job_id') or '')
 name=str(data.get('job_name') or '')
 rne=Path(str(data.get('rne_path') or '')).name
 if jid and (not rne or not name):
  try:
   job=next((x for x in load()['jobs'] if x['id']==jid),None)
   if job:
    rne=rne or str(job.get('rne') or Path(str(job.get('rne_path') or '')).name)
    name=name or str(job.get('name') or '')
  except Exception:pass
 return jid,name,rne
inspect_tasks={k:inspect_task_blank(kind=k) for k in INSPECT_TASK_SPECS}
inspect_tasks['all']=inspect_task_blank(kind='all')
inspect_task_seconds={}   # 種類ごとの直近の所要秒。見込みの分母にだけ使う

def inspect_task_percent(st):
 """まだ実測できないので、経過時間と直近の所要秒から見当をつける。
 満杯にはしない（9割で止める）。終わっていないのに100%と出すのは嘘になる。"""
 if not st.get('running'):return float(st.get('percent') or 0)
 exp=float(st.get('expected') or 0)
 el=max(0.0,time.time()-float(st.get('started') or time.time()))
 if exp<=0:return round(min(90.0,el/30.0*90.0),1)
 return round(min(90.0,el/exp*90.0),1)

def _run_inspect_endpoint(kind,data):
 """調べもの1件を、登録済みの口をそのまま呼んで実行する。ふるまいを二重に持たない。"""
 endpoint,path,title,detail,_sec=INSPECT_TASK_SPECS[kind]
 view=app.view_functions.get(endpoint)
 if view is None:raise RuntimeError(f'{endpoint} が登録されていません')
 with app.test_request_context(path,method='POST',json=data):
  rv=view()
 resp=rv[0] if isinstance(rv,tuple) else rv
 return resp.get_json(silent=True) or {}





def dll_search_roots(cfg=None):
 """DLLを探す範囲を、設定どおりの順番で絶対パスにして返す。

 設定は相対パス（.\\Config\\NAVIAP）でも書けるので、ここで一度だけ解決する。
 空にはしない。空になると探索が一切効かず、原因の分からない「見つかりません」になる。
 """
 try:values=(cfg if isinstance(cfg,dict) else load()).get('navigator_api_search_roots')
 except Exception:values=None
 if not isinstance(values,list) or not values:values=list(DEFAULT_DLL_SEARCH_ROOTS)
 out=[];seen=set()
 for raw in values:
  raw=str(raw or '').strip()
  if not raw:continue
  try:p=resolve_path(raw)
  except Exception:continue
  key=os.path.normcase(os.path.normpath(str(p)))
  if key in seen:continue
  seen.add(key);out.append(p)
 return out or [resolve_path(x) for x in DEFAULT_DLL_SEARCH_ROOTS]

def dll_diagnostic_issues(attempts,python_bits=None,exports=None,bound=None,requirement=None):
 issues=[];existing=[x for x in attempts if x.get('exists')]
 # 条件が渡されていなくても自分で求める。ここが空だと「何が必要か」を言えないまま
 # 「読み込めません」だけを出すことになり、別のPCで手が止まる。
 req=requirement or _dll_requirement() or {}
 bits=int(python_bits or req.get('required_bits') or struct.calcsize('P')*8)
 want=', '.join(req.get('preferred_folders') or [])
 roots=' / '.join(req.get('search_roots') or [])
 # 「何が必要か」を最初に置く。読み込めた場合でも、別のPCへ移すときに要る情報はこれ。
 issues.append({'level':'ok','title':f'このPCで必要なDLL: {bits}bit版 SymNaviA.dll',
                'detail':req.get('reason') or f'このアプリを動かしているPythonが{bits}bitのため、DLLも{bits}bit版でなければ読み込めません。',
                'action':(f'標準の配布フォルダーなら {want} の中にあるものが該当します。' if want else '')+(f' 探した範囲: {roots}' if roots else '')})
 if not existing:issues.append({'level':'error','title':'DLLが見つかりません','detail':f'検索範囲（{roots or "既定"}）と手動指定のどちらにも SymNaviA.dll がありません。','action':'「検索するフォルダー」に置き場所を追加して再検索するか、「手動で指定」でDLLを直接選んでください。'})
 mismatches=[x for x in existing if x.get('dll_bits') and int(x['dll_bits'])!=bits]
 if mismatches and not [x for x in attempts if x.get('result')=='loaded']:
  seen=', '.join(sorted({str(x.get('dll_bits'))+'bit' for x in mismatches}))
  issues.append({'level':'error','title':'見つかったDLLのbit数が合いません','detail':f'必要なのは{bits}bit版ですが、検出できたのは{seen}のDLLだけです。','action':(f'{want} のような{bits}bit版フォルダーを配置するか、そのフォルダーを検索範囲へ追加してください。' if want else f'{bits}bit版のDLLを配置してください。')})
 elif mismatches:
  issues.append({'level':'ok','title':'bit数が合わない候補は自動で除外しました','detail':'%d件を対象外にしています。'%len(mismatches),'action':f'{bits}bit版だけを使用します。除外は正常な動作です。'})
 errors=[x for x in attempts if x.get('result')=='load_error' or x.get('error')]
 if errors:
  missing=req.get('runtime_missing') or []
  issues.append({'level':'error','title':'DLLは存在しますが読み込めません','detail':str(errors[0].get('error') or 'WindowsがDLLをロードできませんでした。'),
                 'action':('Visual C++ 再頒布可能パッケージ（%dbit）が不足しています: %s'%(bits,', '.join(missing))) if missing else '同一フォルダーの依存DLL、Visual C++ランタイム、アクセス権を確認してください。'})
 if req.get('runtime_missing'):
  issues.append({'level':'error','title':f'Visual C++ ランタイム（{bits}bit）が不足しています','detail':'見つからないDLL: '+', '.join(req['runtime_missing']),'action':f'Microsoft Visual C++ 再頒布可能パッケージの{bits}bit版を導入してください。'})
 elif req.get('runtime'):
  issues.append({'level':'ok','title':f'Visual C++ ランタイム（{bits}bit）は揃っています','detail':'確認済み: '+', '.join(req['runtime']),'action':'このPCでは追加導入は不要です。'})
 loaded=[x for x in attempts if x.get('result')=='loaded']
 if loaded:issues.append({'level':'ok','title':'DLLを正常に読み込みました','detail':str(loaded[0].get('path') or ''),'action':'Navigator APIを利用できます。'})
 # このDLLで何ができるかは、アプリが使っている関数だけでは分からない。公開されている関数も提示する。
 if exports:
  unused=[x for x in exports if x not in set(bound or [])]
  issues.append({'level':'ok','title':'DLLが公開しているNavigator API関数 %d件'%len(exports),'detail':'このアプリが使用中 %d件 / 未使用 %d件'%(len(bound or []),len(unused)),'action':('未使用: '+', '.join(unused)) if unused else 'すべて使用しています。'})
 return issues

def _log_api_exports(dll,exports,bound):
 """DLLが公開しているNavigator API関数をログへ残す。

 画面で見えるだけだと転記が要る。速度改善の検討材料になるので、そのまま送れる形で残す。
 """
 if not exports:return
 used=set(bound or [])
 log.info('API_DIAG_EXPORTS dll=%s count=%s used=%s unused=%s',dll,len(exports),len(used),len([x for x in exports if x not in used]))
 log.info('API_DIAG_EXPORTS_ALL %s',','.join(exports))
 unused=[x for x in exports if x not in used]
 if unused:log.info('API_DIAG_EXPORTS_UNUSED %s',','.join(unused))

def _api_diag_cache_path():return LOCAL_RUNTIME/'api_diagnostic_cache.json'
def _dll_signature(path):
 try:
  p=Path(path);st=p.stat();return {'path':str(p),'size':st.st_size,'mtime_ns':st.st_mtime_ns}
 except OSError:return None
FAILED_DIAG_TTL_SECONDS=30
def _api_diag_search_key(c):
 """「どう探すか」を1つの値にまとめたもの。探し方を変えたら前の結果は使わない。"""
 if c is None:return ''
 try:return json.dumps({'roots':[str(x) for x in dll_search_roots(c)],
                        'manual':str(c.get('navigator_api_dll') or ''),
                        'exe':str(c.get('symnavi_exe') or '')},ensure_ascii=False,sort_keys=True)
 except Exception:return ''
def _read_api_diag_cache(c=None):
 """前回の診断結果を使い回せるか。

 成功は、そのDLLの署名（場所・大きさ・更新時刻）が変わらないかぎり有効。
 失敗も短い間だけ覚えておく。見つからなかったことを表す署名は無いので、
 これまでは毎回そのまま探し直していた ―― 探索は候補24件ぶんのフォルダー走査で、
 しかも対象にはネットワーク上の場所が入る。DLLが無いPCほど、画面を触るたびに
 いちばん重い処理が走っていた（実測: 1プロセスで同じ探索が79回）。
 探し方を変えたときと、%d秒たったときは、ちゃんと探し直す。
 """%FAILED_DIAG_TTL_SECONDS
 bits=struct.calcsize('P')*8
 try:
  d=json.loads(_api_diag_cache_path().read_text(encoding='utf-8'))
  if d.get('python_bits')!=bits:return None
  if d.get('ok'):
   sig=_dll_signature(d.get('dll',''))
   if sig and d.get('signature')==sig:return d
   return None
  if c is None or d.get('search_key')!=_api_diag_search_key(c):return None
  age=(datetime.now()-datetime.fromisoformat(str(d.get('cached_at')))).total_seconds()
  if 0<=age<FAILED_DIAG_TTL_SECONDS:
   d=dict(d);d['cache_age_seconds']=round(age,1);return d
 except Exception:pass
 return None
def _write_api_diag_cache(info,c=None):
 try:
  payload=dict(info);payload['signature']=_dll_signature(info.get('dll',''));payload['cached_at']=datetime.now().isoformat(timespec='seconds')
  payload['search_key']=_api_diag_search_key(c)
  tmp=_api_diag_cache_path().with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8');os.replace(tmp,_api_diag_cache_path())
 except Exception:log.exception('API診断キャッシュ保存失敗')


def api_readiness(info):
 """APIが使えるか、使えないなら何が足りないかを、ここだけで決める。

 これまでは「必要なDLL」「探す範囲」「手動で指定」「DLL診断」の4か所がそれぞれ
 別の言い方で状態を出していた。同じ画面に「そろっています」と「不足しています」が
 並ぶことがあり、どちらが本当なのか読み取れなかった。判定はこの関数だけが行い、
 画面はその結果をそのまま出す。
 """
 req=info.get('requirement') or {}
 attempts=info.get('attempts') or []
 pybits=info.get('python_bits') or req.get('python_bits') or 0
 used=str(info.get('dll') or '')
 loaded=bool(info.get('ok'))
 found=[a for a in attempts if a.get('exists')]
 fit=[a for a in found if a.get('dll_bits') and a.get('dll_bits')==pybits]
 exports=[x for x in (info.get('exports') or []) if str(x).lower().startswith('navi')]
 miss_rt=list(req.get('runtime_missing') or [])
 roots=[str(x) for x in (info.get('search_roots') or req.get('search_roots') or [])]
 items=[]
 items.append({'key':'dll','label':'SymNaviA.dll 本体',
   'need':f"{req.get('file_name','SymNaviA.dll')} が、探す範囲のどこかにあること",
   'have':(used or (found[0]['path'] if found else '')),
   'state':'ok' if (loaded and used) else ('warn' if found else 'ng'),
   'fix':'' if (loaded and used) else ('見つかってはいますが読み込めていません。下のbit数と依存ランタイムを確認してください'
         if found else '「DLLを探すフォルダー」に置き場所を足すか、「手動で指定」でファイルを直接選んでください')})
 dbits=info.get('dll_bits') or (fit[0].get('dll_bits') if fit else (found[0].get('dll_bits') if found else 0))
 items.append({'key':'bits','label':'bit数の一致',
   'need':f'このアプリのPythonは {pybits}bit。DLLも {pybits}bit 版であること',
   'have':(f'{dbits}bit' if dbits else ''),
   'state':('ok' if (dbits and dbits==pybits) else ('ng' if found else 'unknown')),
   'fix':'' if (dbits and dbits==pybits) else
         (f'見つかったDLLは {dbits}bit です。{pybits}bit 版（フォルダー名の末尾が'
          +('x64' if pybits==64 else 'x64でないもの')+'）を指してください' if dbits
          else 'DLLが見つかっていないため確認できません')})
 items.append({'key':'runtime','label':'依存ランタイム（Visual C++）',
   'need':'DLLが要求するVisual C++ 再頒布可能パッケージがこのPCに入っていること',
   'have':('不足なし' if not miss_rt else '不足: '+'、'.join(miss_rt)),
   'state':'ok' if not miss_rt else 'ng',
   'fix':'' if not miss_rt else 'Microsoft Visual C++ 再頒布可能パッケージを入れてください'})
 items.append({'key':'exports','label':'必要な関数',
   'need':'NaviOpenCatalog などの関数がDLLに含まれていること',
   'have':(f'{len(exports)}個を確認' if exports else ''),
   'state':'ok' if exports else ('ng' if found else 'unknown'),
   'fix':'' if exports else ('このファイルはNavigator APIのDLLではない可能性があります' if found
         else 'DLLが見つかっていないため確認できません')})
 items.append({'key':'roots','label':'探す範囲',
   'need':'DLLの置き場所が、探す範囲に入っていること',
   'have':(f'{len(roots)}か所を探して {len(found)}件を検出' if roots else ''),
   'state':'ok' if found else 'ng',
   'fix':'' if found else '「DLLを探すフォルダー」へ、NAVIAPの置き場所を足してください'})
 ng=[x for x in items if x['state']=='ng']
 warn=[x for x in items if x['state']=='warn']
 return {'ok':loaded,'items':items,
         'ready':len([x for x in items if x['state']=='ok']),'total':len(items),
         'blocking':(ng[0] if ng else (warn[0] if warn else None)),
         'used':used,'used_bits':info.get('dll_bits') or 0,'python_bits':pybits,
         'candidates':len(found),'fit':len(fit),
         'headline':('Navigator APIを使えます' if loaded else 'Navigator APIを使えません'),
         'detail':(f'{used}（{info.get("dll_bits") or pybits}bit）を使用します' if loaded
                   else (ng[0]['fix'] if ng else (warn[0]['fix'] if warn else '原因を特定できませんでした')))}

def _dll_requirement(cfg=None):
 """このPCで必要なDLLの条件。診断が失敗したときこそ必要な情報なので、常に返せるようにする。"""
 try:
  from navigator_api import dll_requirement
  return dll_requirement(BASE,[str(x) for x in dll_search_roots(cfg)])
 except Exception:
  log.exception('DLL_REQUIREMENT_FAILED');return {}





# 影実行を見ながらログも追いたい、という使い方が多い。1行ずつ全部返すと重いので、
# 絞り込みと行数の上限をサーバー側で受けられるようにする。既定の挙動は今までどおり。
LOG_FILTERS={
 'split':(r'SPLIT_|AXIS_|ROW_|COLUMN_|CONDITION_ITEMS|SPLIT_BASELINE','分割まわり'),
 'problem':(r'\[ERROR\]|\[WARNING\]','エラーと警告'),
 'all':('','すべて'),
}
LOG_READ_BYTES=4*1024*1024   # 末尾4MB。178列のログでも数万行ぶんある
def read_log_lines(limit=1200,q='',preset=''):
 # 省略でまとめている最中の行はまだファイルに出ていない。読む直前に書き出して、
 # 画面が「いま起きていること」より遅れて見えないようにする。
 flush_log()
 p=LOG_PATH
 if not p.exists():return [],0,0,False
 # 全文をメモリへ載せない。画面が見るのは末尾なので、末尾だけを読む。
 # 以前は毎回ファイル全体を read_text しており、育つほど1回の表示が重くなっていた。
 lines,size,clipped=tail_lines(p,LOG_READ_BYTES)
 total=len(lines)
 pat=(LOG_FILTERS.get(preset) or ('',''))[0]
 if pat:
  try:rx=re.compile(pat)
  except re.error:rx=None
  if rx:lines=[x for x in lines if rx.search(x)]
 q=str(q or '').strip()
 if q:
  try:rq=re.compile(q,re.I)
  except re.error:rq=None
  lines=[x for x in lines if (rq.search(x) if rq else q.lower() in x.lower())]
 n=max(1,min(int(limit or 1200),5000))
 return lines[-n:],total,size,clipped





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

PATH_SETTING_LABEL={'rne_folder':'RNE基本フォルダー','default_output_folder':'既定の出力先',
 'backup_folder':'バックアップ先','symnavi_exe':'SymNavi.exe','symnavim_conf':'symnavim.conf',
 'symnavim_def':'symnavim.def','accdb_template':'ACCDB空テンプレート','navigator_api_dll':'Navigator API DLL'}
PATH_SETTING_KIND={'rne_folder':'folder','default_output_folder':'folder','backup_folder':'folder',
 'symnavi_exe':'file','symnavim_conf':'file','symnavim_def':'file','accdb_template':'file',
 'navigator_api_dll':'file'}

def path_writable(p):
 """書けるかどうかは、実際に書いてみないと分からない（権限は見ただけでは分からない）。"""
 try:
  p=Path(p)
  if not p.is_dir():return None
  probe=p/f'.probe_{os.getpid()}'
  probe.write_bytes(b'x');probe.unlink()
  return True
 except Exception:return False

def path_setting_roles(c):
 """それぞれのパス設定が、いまの構成で本当に要るのかを決める。

 これまでは1つずつ「実体があるか」だけを見ていたため、使ってすらいない設定まで
 「このPCでは使えません」と赤で出していた。実測 2026-08-12: 対象がすべて個別の
 パスで解決できているのに、既定のままの RNE基本フォルダー(.\rne)が無いという理由で
 NGになり、実行は問題なく通るのに診断だけが赤かった。

 返す役割は3つ。
   required … いまの構成で必ず要る。無ければ実行が止まる
   fallback … 何かが欠けたときにだけ使う。無くても実行できるなら赤くしない
   unused   … いまの抽出方式・出力形式では使わない
 """
 jobs=c.get('jobs') or []
 engine=str((c.get('settings') or {}).get('extract_engine') or 'api').lower()
 # RNE基本フォルダーを実際に使うのは、対象が「ファイル名だけ」を持っているとき。
 # 個別のパス（絶対・UNC・.\ 始まり）を持つ対象は、この設定を一切見ない。
 def leans_on_rne_root(j):
  raw=str(j.get('rne_path') or j.get('rne') or '').strip()
  if not raw:return True
  expanded=os.path.expandvars(os.path.expanduser(raw))
  if Path(expanded).is_absolute() or expanded.startswith('\\\\'):return False
  return not raw.startswith(('.\\','..\\','./','../'))
 rne_users=[j for j in jobs if leans_on_rne_root(j)]
 out_users=[j for j in jobs if not str(j.get('output_folder') or '').strip()]
 def nobody(kind):
  return '対象がまだ無いため、いまは使いません' if not jobs else f'登録済みの{len(jobs)}件はすべて{kind}'
 # 同時に出す形式にACCDBが入っていれば、主の形式が何であってもテンプレートは要る
 accdb=[j for j in jobs if normalize_output_format(j.get('output_format'),j.get('output_file'))=='accdb'
        or 'accdb' in job_extra_formats(j)]
 roles={}
 # 対象のRNEが見つからないことは、この設定の落ち度ではない。個別のパスを持つ対象は
 # 基本フォルダーを一切見ないため（resolve_rne_pathが参照しない）、ここを直しても解決しない。
 # 見つからない対象は、その対象自身の問題として実行前診断が出す。
 roles['rne_folder']=('required',f'{len(rne_users)}件の対象がこの場所を基準にします') if rne_users else \
   ('fallback',nobody('個別のパスで解決できるため、この設定は使っていません'))
 roles['default_output_folder']=('required',f'{len(out_users)}件の対象がこの場所へ出力します') if out_users else \
   ('fallback',nobody('出力先を個別に持っています'))
 # 接続に関わる3つは、まとめて「DDEのもの」にはできない。使われ方がそれぞれ違う。
 # v1.60.0では3つ一括でDDE専用にしてしまい、API方式のときに symnavim.conf まで
 # 「いまは不要」と出ていた。実際にはこれが唯一の認証情報の出どころで、無ければ
 # APIセッションを開けない（起動ログの credential_load はこの読み取り）。
 roles['symnavim_conf']=('required','接続先と認証情報（利用者ID・パスワード・サーバー）をここから読みます。API・DDEのどちらでも要ります')
 # SymNavi.exe：DDEでは起動する本体そのもの。APIでは起動しないが、SymNaviA.dllが
 # 検索範囲で見つからなかったときに限り、この隣を最後に探す（candidate_dllsの終端）。
 roles['symnavi_exe']=('required','SymfoNaviを起動してDDEでつなぎます') if engine=='dde' else \
   ('fallback','APIでは起動しません。SymNaviA.dllが見つからないときだけ、この隣を探す手がかりに使います')
 # symnavim.def：このアプリは一度も読んでいない。DDEではSymfoNavi側が使う。
 roles['symnavim_def']=('required','DDE互換方式でSymfoNavi側が使います') if engine=='dde' else \
   ('unused','いまの抽出方式（Navigator API）では使いません')
 roles['navigator_api_dll']=(('fallback','手動で指定したときだけ使います。空なら探す範囲から自動で選びます')
   if engine=='api' else ('unused','いまの抽出方式（DDE互換）では使いません'))
 roles['accdb_template']=(('required',f'{len(accdb)}件の対象がACCDBで出力します') if accdb
   else ('unused','ACCDBで出力する対象がないため使いません'))
 roles['backup_folder']=(('required','出力を差し替える前に、いまのファイルをここへ控えます')
   if (c.get('settings') or {}).get('backup_enabled')!=False
   else ('unused','控えを取らない設定のため使いません'))
 return roles

def machine_path_view():
 """設定値が、このPCではどこを指すのか。設定・実体・状態を1か所で見せる。

 別のPCへ持って行くと壊れる設定（他人のプロファイル配下）が、いちばん見つけにくい。
 実際に走らせてから「アクセスが拒否されました」で気づくことになるので、先に出す。

 赤くするのは「いま要るのに使えない」ものだけ。使っていない設定の不足で赤を出すと、
 本当に直すべきものが埋もれる。
 """
 c=load();rows=[];roles=path_setting_roles(c)
 for key,label in PATH_SETTING_LABEL.items():
  raw=str(c.get(key) or '')
  kind=PATH_SETTING_KIND.get(key,'folder')
  role,why=roles.get(key,('required',''))
  try:real=resolve_path(raw)
  except Exception:real=Path(raw or '.')
  exists=bool(raw) and Path(real).exists()
  foreign=foreign_profile_path(raw)
  writable=path_writable(real) if (kind=='folder' and exists) else None
  note=''
  if foreign:
   # 他人のフォルダーは、使う予定が無くても直す価値がある（別のPCで必ず詰まる）
   state='ng';note=f'別の利用者のフォルダー（{foreign}）を指しています。このPCでは使えません'
  elif exists:
   state='ok'
   if is_pc_path(raw):note='このPCのローカル領域（PCごとに実体が変わります）'
   if writable is False:state='warn';note='書き込めません（権限を確認してください）'
   elif key=='symnavim_conf':
    # 認証ファイルは「在る」だけでは足りない。読めて、必要な3項目が揃っていて初めて接続できる。
    # 値そのものは出さない ―― どのセクションを使うかだけを言う。
    try:*_,sec=creds(real);note=f'読み取れます（[{sec}] の利用者ID・パスワード・サーバーを使います）'
    except Exception as e:state='ng';note=f'ファイルはありますが、読み取れません: {e}'
  elif role=='required':
   state='ng';note=('フォルダーがありません。'+why if kind=='folder' else 'ファイルがありません。'+why)
  elif role=='unused':
   state='ok';note=why+('' if raw else '（未設定）')
  else:   # fallback ―― 無くても実行できる。理由を添えて、赤くはしない
   state='ok'
   if not raw:note=why
   elif key=='default_output_folder':note=f'いまはありません（{why}）。出力するときに作られます'
   else:note=f'いまはありませんが、{why}'
  rows.append({'key':key,'label':label,'kind':kind,'configured':raw,'resolved':str(real),
               'exists':exists,'writable':writable,'role':role,'why':why,
               'portable':is_pc_path(raw) or not Path(raw).is_absolute() if raw else True,
               'foreign':foreign or '','state':state,'note':note})
 fixed=[{'label':'アプリの場所','path':str(BASE),'note':'このPCに置いてある実体'},
        {'label':'このPCのローカル領域','path':str(LOCAL_ROOT),'note':'<PC> が指す先。作業・控え・ログ・キャッシュの親'},
        {'label':'作業フォルダー','path':str(LOCAL_ROOT/'work'),'note':'抽出の途中ファイル。起動時に空にします'},
        {'label':'ログ','path':str(LOCAL_LOGS),'note':'実行ログの実体'},
        {'label':'設定の控え（このPC）','path':str(SETTINGS_DB),'note':'マスターから写した作業用'},
        {'label':'設定のマスター','path':str(MASTER_SETTINGS_DB),'note':'BOX上の正本。全PCで共有'}]
 bad=[x for x in rows if x['state']=='ng']
 warn=[x for x in rows if x['state']=='warn']
 used=[x for x in rows if x['role']!='unused']
 if bad:summary=f'{len(bad)}件がこのPCでは使えません'
 elif warn:summary=f'{len(warn)}件に注意があります'
 else:summary=f'いま使う{len(used)}件はすべてこのPCで解決できます'
 return {'ok':not bad,'rows':rows,'fixed':fixed,'profile':str(Path.home()),
         'user':os.environ.get('USERNAME') or os.environ.get('USER') or '',
         'host':socket.gethostname(),'summary':summary}







def _viewer_output_path(job,cfg):
 run=(load_job_runs().get(job.get('id')) or {});filename=str(run.get('output_file') or job.get('output_file') or '')
 folder=resolve_path(job.get('output_folder') or cfg.get('default_output_folder'));candidate=folder/filename
 if candidate.is_file():return candidate
 try:
  current=folder/resolve_output_filename(job,cfg)
  if current.is_file():return current
 except Exception:pass
 return candidate

def read_preview_data(path,job,limit=500):
 fmt=normalize_output_format(job.get('output_format'),path.name);headers=[];rows=[];total=None
 if fmt=='sqlite3':
  with sqlite3.connect(path) as conn:
   table=str(job.get('table') or '');names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_更新情報' ORDER BY name")]
   if table not in names:table=names[0] if names else ''
   if not table:raise ValueError('表示できるテーブルがありません')
   headers=[x[1] for x in conn.execute(f'PRAGMA table_info({qi(table)})')];total=conn.execute(f'SELECT COUNT(*) FROM {qi(table)}').fetchone()[0];rows=conn.execute(f'SELECT * FROM {qi(table)} LIMIT ?',(limit,)).fetchall()
 elif fmt in ('csv','txt'):
  data=None;delimiter=',' if fmt=='csv' else '\t'
  for enc in ('utf-8-sig','cp932','utf-8'):
   try:
    with path.open('r',encoding=enc,newline='') as h:data=list(csv.reader(h,delimiter=delimiter))
    break
   except UnicodeDecodeError:continue
  if data is None:raise UnicodeError('文字コードを判定できません')
  headers=data[0] if data else [];rows=data[1:limit+1];total=max(0,len(data)-1)
 elif fmt=='xlsx':
  from openpyxl import load_workbook
  wb=load_workbook(path,read_only=True,data_only=True)
  try:
   ws=wb[job.get('sheet')] if job.get('sheet') in wb.sheetnames else wb[wb.sheetnames[0]];it=ws.iter_rows(values_only=True);headers=list(next(it,()))
   for _,row in zip(range(limit),it):rows.append(row)
   total=max(0,(ws.max_row or 1)-1)
  finally:wb.close()
 elif fmt=='accdb':
  if os.name!='nt':raise RuntimeError('ACCDBプレビューはWindowsでのみ利用できます')
  import pythoncom,win32com.client
  pythoncom.CoInitialize();conn=None;rs=None
  try:
   errs=[]
   for provider in ('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0'):
    try:conn=win32com.client.Dispatch('ADODB.Connection');conn.Open(f'Provider={provider};Data Source={path};Persist Security Info=False;');break
    except Exception as e:errs.append(str(e));conn=None
   if not conn:raise RuntimeError('ACE OLEDBで開けません: '+' / '.join(errs))
   table=str(job.get('table') or '').replace(']',']]');rs=win32com.client.Dispatch('ADODB.Recordset');rs.Open(f'SELECT TOP {int(limit)} * FROM [{table}]',conn,0,1);headers=[str(rs.Fields(i).Name) for i in range(rs.Fields.Count)]
   while not rs.EOF:rows.append([rs.Fields(i).Value for i in range(rs.Fields.Count)]);rs.MoveNext()
  finally:
   try:
    if rs:rs.Close()
   except:pass
   try:
    if conn:conn.Close()
   except:pass
   pythoncom.CoUninitialize()
 else:raise ValueError(f'未対応形式です: {fmt}')
 headers=['' if x is None else str(x) for x in headers][:200];rows=[['' if v is None else str(v) for v in list(row)[:len(headers)]] for row in rows]
 return fmt,headers,rows,total






# 仕様書の一覧。実体が無くても一覧には出し、「見つかりません」と言えるようにする。



@app.post('/api/heartbeat')
def heartbeat():
 global last_heartbeat_at,browser_closed_explicit,browser_closing_at,heartbeat_total
 data=request.get_json(silent=True) or {}; app_id=str(data.get('app_id') or ''); client_id=str(data.get('client_id') or request.headers.get('X-Heartbeat-Client') or '')[:80]
 if app_id!=APP_ID or not client_id:return jsonify(ok=False,error='アプリタブ識別情報が不正です'),400
 now=time.time()
 with heartbeat_lock:
  last_heartbeat_at=now;browser_closed_explicit=False;browser_closing_at=0.0;heartbeat_total+=1
  previous=heartbeat_clients.get(client_id,{})
  heartbeat_clients[client_id]={'app_id':APP_ID,'instance_id':INSTANCE_ID,'last_seen':now,'user_agent':request.headers.get('User-Agent','')[:160],'closing_at':0.0,'recovered_count':int(previous.get('recovered_count') or 0)+(1 if previous.get('closing_at') else 0)}
  # 終了通知後に戻らなかったタブに加え、通知なく消えたタブ(強制終了・通信断)も回収する。
  # 放置すると client_id はページ読込ごとに増え、辞書が際限なく肥大化する。
  stale=[k for k,v in heartbeat_clients.items()
         if (v.get('closing_at') and now-float(v.get('closing_at') or 0)>86400)
         or (not v.get('closing_at') and now-float(v.get('last_seen') or 0)>HEARTBEAT_TIMEOUT_SECONDS*3)]
  for k in stale:heartbeat_clients.pop(k,None)
  if stale:log.info('HEARTBEAT_CLIENTS_PRUNED count=%s remaining=%s',len(stale),len(heartbeat_clients))
 return jsonify(ok=True,app_id=APP_ID,instance_id=INSTANCE_ID,server_time=datetime.now().isoformat(timespec='milliseconds'),received_at=now,timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS,total=heartbeat_total)

@app.get('/api/heartbeat-status')
def heartbeat_status():
 now=time.time()
 with heartbeat_lock:
  age=max(0,now-last_heartbeat_at);clients=[{'client_id':k,'age_seconds':round(now-v['last_seen'],1),'closing':bool(v.get('closing_at'))} for k,v in heartbeat_clients.items()]
 return jsonify(ok=True,app_id=APP_ID,instance_id=INSTANCE_ID,state='healthy' if age<30 else ('delayed' if age<HEARTBEAT_TIMEOUT_SECONDS else 'disconnected'),last_received=datetime.fromtimestamp(last_heartbeat_at).isoformat(timespec='seconds'),age_seconds=round(age,1),timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS,active_clients=sum(1 for x in clients if not x['closing']),recent_clients=sum(1 for x in clients if not x['closing'] and x['age_seconds']<30),closing_clients=sum(1 for x in clients if x['closing']),clients=clients,total=heartbeat_total,server_time=datetime.now().isoformat(timespec='seconds'),auto_shutdown_on_disconnect=False,exit_when_app_tabs_empty=True,close_grace_seconds=CLOSE_GRACE_SECONDS,resident=bool(residency_state['active']),resident_reason=residency_state['reason'],residency_pending_reason=residency_reason(),tray_available=bool(tray),queued_commands=pending_queue_count())

@app.post('/api/shutdown-app')
def shutdown_app():
 # 画面の「アプリを終了」。常駐条件が残っていても、ここからの終了は明示操作として尊重する。
 def stop():
  time.sleep(.4)
  with command_queue_lock:command_queue.clear()
  log.info('APP_EXIT_REQUESTED source=ui resident=%s',residency_state['active'])
  _flush_settings_on_exit('shutdown-app'); stop_event.set()
  if tray:
   try:tray.stop()
   except Exception:pass
  os._exit(0)
 threading.Thread(target=stop,daemon=True).start(); return jsonify(ok=True)

# 起動計測用: Flaskが最初のHTTP要求を処理した時刻を1度だけ記録する（＝サーバー実質稼働開始）。
_first_request_logged=False
@app.before_request
def _log_first_request():
 global _first_request_logged
 if _first_request_logged:return
 _first_request_logged=True
 try:spawn_at=float(os.environ.get('NAVI_APP_SPAWN_AT') or 0)
 except Exception:spawn_at=0
 ready_since_spawn=(time.time()-spawn_at) if spawn_at else -1
 log.info('APP_FIRST_REQUEST path=%s ready_since_spawn=%.2fs ready_since_import=%.2fs',request.path,ready_since_spawn,time.time()-_APP_IMPORT_DONE_AT)

@atexit.register
def shutdown():
 _flush_settings_on_exit('atexit'); stop_event.set()

# 画面からの求めに応える口（ルート）は navi_web.py にある。取り込みはここ ―― この行より
# 上がすべて出来上がってから読み込むので、向こうは本体の名前をそのまま受け取れる。
# ワーカーは抽出しかしないので読み込まない（受け口も、そのぶんの解析も要らない）。
if not WORKER_MODE:
 # 直接起動（python app.py）では、このファイルは __main__ という名前で動いている。
 # そのまま navi_web が「import app」すると、同じファイルがもう一度、別のモジュール
 # として読み込まれる。Flask本体も設定も別物になり、受け口は誰も見ていない側へ付く。
 #   実測 2026-08-17: 画面も /api/* もすべて404（url_mapには69件あるのに繋がらない）
 # 先に自分自身を 'app' として登録し、二重読み込みそのものを起こさせない。
 sys.modules.setdefault('app',sys.modules[__name__])
 import navi_web

if __name__=='__main__':
 if os.environ.get('NAVI_LAUNCHED_BY_GUARD')!='1':
  raise SystemExit('start.vbsから起動してください。app.pyの直接起動はサポートされていません。')
 try:_spawn_at=float(os.environ.get('NAVI_APP_SPAWN_AT') or 0)
 except Exception:_spawn_at=0
 if _spawn_at:log.info('APP_IMPORT_ELAPSED spawn_to_import=%.2fs note=interpreter_init+module_import+source_compile(BOX)',_APP_IMPORT_DONE_AT-_spawn_at)
 # どの版が動いているのかは、後からログだけを見て分かる必要がある。起動のいちばん最初に出す。
 startup_clock=time.perf_counter();log.info('APP_START version=%s build=%s released=%s source=%s local_root=%s pycache=%s',APP_VERSION,BUILD_VERSION,APP_RELEASED_AT,BASE,LOCAL_ROOT,os.environ.get('PYTHONPYCACHEPREFIX',''))
 _t=time.perf_counter(); shutil.rmtree(LOCAL_ROOT/'work',ignore_errors=True); (LOCAL_ROOT/'work').mkdir(parents=True,exist_ok=True); log.info('APP_START_WORKCLEAN elapsed=%.2fs',time.perf_counter()-_t)
 # 起動待ちモーダル(loading.html)は file:// から開くので、サーバーが立つまで版が分からない。
 # ここに置いておけば、ランチャーが次回の起動時に画面へ差し込める。
 # 中身はASCIIだけにする。ランチャー(VBScript)は既定でANSIとして読むので、
 # 日本語を混ぜると読み取り側の文字コードに左右される。版とビルドが分かれば足りる。
 try:(LOCAL_RUNTIME/'version.txt').write_text(f'{APP_VERSION}\t{BUILD_VERSION}',encoding='ascii')
 except Exception:log.exception('VERSION_STAMP_FAILED')
 _t=time.perf_counter(); migrate_legacy_settings(); log.info('APP_START_MIGRATION elapsed=%.2fs',time.perf_counter()-_t)
 _t=time.perf_counter(); threading.Thread(target=scheduler,daemon=True,name='scheduler').start(); threading.Thread(target=command_dispatcher,daemon=True,name='command-dispatcher').start(); threading.Thread(target=heartbeat_watchdog,daemon=True,name='heartbeat-watchdog').start(); log.info('APP_START_THREADS elapsed=%.2fs',time.perf_counter()-_t)
 _t=time.perf_counter(); log.info('APP_START_TRAY available=%s elapsed=%.2fs',bool(start_tray()),time.perf_counter()-_t)
 log.info('APP_START_TOTAL boot_to_run=%.2fs total_since_spawn=%.2fs',time.perf_counter()-startup_clock,(time.time()-_spawn_at) if _spawn_at else -1)
 # ポートが空いているかを先に確かめる。Flask(werkzeug)は束縛失敗を自前で処理して
 # 標準出力にだけ出して終了するため、そのままではログに何も残らず、
 # ランチャー側からは「起動確認がタイムアウト」としか見えない。
 _probe=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
 try:
  # Flask(werkzeug)と同じ条件で試す。これを付けないと、直前に終了したプロセスの
  # 後始末待ち(TIME_WAIT)が残っているだけで「使用中」と判定してしまい、
  # 本当は起動できるのに起動を諦めることになる（停止直後の再起動で起きる）。
  _probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  _probe.bind((HOST,PORT))
 except OSError as e:
  log.error('APP_PORT_IN_USE host=%s port=%s error=%s',HOST,PORT,e)
  log.error('APP_PORT_IN_USE_HINT 既にSymfoNavi Data Hubが起動しているか、前回のプロセスが残っています。'
            'stop_app.bat を実行するか、タスクマネージャーで python.exe / pythonw.exe を終了してから起動し直してください。')
  raise SystemExit(1)
 finally:
  _probe.close()
 try:
  app.run(host=HOST,port=PORT,debug=False,threaded=True)
 except Exception:
  log.exception('APP_RUN_FAILED host=%s port=%s',HOST,PORT);raise
