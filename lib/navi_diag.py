"""このPCで、いまの設定が本当に使えるのか。

「設定した場所は在るか」「いまの抽出方式でそれは要るのか」「データは新しいか」
「APIは使える状態か」――どれも読むだけで、実行中の状態を書き換えない。だから
本体から切り離せる。逆に本体は、実行の前に path_setting_roles だけを使う。

赤くするのは「いま要るのに使えない」ものだけ。使っていない設定の不足で赤を出すと、
本当に直すべきものが埋もれる（v1.60.0）。その判断はここに集めてある。

本体（app.py）から借りているものは下の import にすべて並べてある。取り込みは
app.py のいちばん最後で行うので、そこまでに本体側は出来上がっている。

借り方は navi_web と同じ約束にしてある ―― 取り込んだ時点の実体を受け取る。
そのため検査が app.load などを差し替えても、こちら側は古いままになる。
v1.65.0では、それに気づかず8本の検査が黙って素通りしていた。差し替える検査を
書くときは、app と navi_diag の両方へ入れること（既存の _patch と同じ）。
"""
import json,os,socket,struct
from datetime import datetime
from pathlib import Path
from navi_paths import is_pc_path,foreign_profile_path
import app
from app import (
    BASE, DATA_ROOT, DATA_ROOT_SOURCE, LOCAL_LOGS, LOCAL_ROOT, LOCAL_RUNTIME, MASTER_SETTINGS_DB, SETTINGS_DB,
    NAVI_VAULT, dll_search_roots, job_extra_formats, job_schedule_preview, last_run_info,
    load, load_job_runs, log, normalize_output_format, resolve_path, schedule_gap_minutes,
    settings_connection,
)
import navi_secret

# データの基準（相対パスと設定のマスターの基準）をどこで決めたか（navi_paths.data_root の出どころ）。
DATA_ROOT_NOTES={'app':'相対パスと設定のマスターの基準。共有から直に動かしているので、アプリの場所と同じ',
                 'pc':'相対パスと設定のマスターの基準。このPCの手元（写しの data）。置き場の「既定の設定」から作りました',
                 'install':'相対パスと設定のマスターの基準。共有の設定を使っています（2.0.0 より前に写したPC。手元へ移すかを画面で選べます）',
                 'local':'相対パスと設定のマスターの基準。このPCだけの上書き（config\\local.json）',
                 'env':'相対パスと設定のマスターの基準。環境変数 NAVI_DATA_ROOT（確かめるとき）'}

# 予定を持たない対象にも「いつまでなら新しいと言えるか」の目安を持たせる。
# 1.88.0まで、目安は予定からしか作っていなかった。そのため手動でしか実行しない対象は
# 何日経っても ok のままで、19日前のファイルに緑の印が付いていた（実測: age 28052分
# ／ state ok）。読み手が日付を引き算して初めて古さに気づく状態は、作ってはいけない。
MANUAL_FRESH_DEFAULT=4320      # 3日。実績から間隔を測れないうちの目安。

def observed_gap_minutes(job_id):
 """これまで実際にどれくらいの間隔で実行されてきたか（分）。中央値を返す。

 予定が無くても、人はだいたい決まった頻度で回している。その実績を目安にする。
 間隔が2つ取れない（＝実行が3回に満たない）うちは決めつけず None を返す ――
 1回や2回の間隔をその対象の「ふつう」と見なすと、たまたま連続で実行しただけの
 対象が、少し空いただけで古い扱いになる。
 """
 try:
  with settings_connection() as c:
   rows=[r[0] for r in c.execute(
     'SELECT finished_at FROM run_history WHERE job_id=? ORDER BY id DESC LIMIT 12',(job_id,))]
 except Exception:
  return None
 ts=[]
 for x in rows:
  try:ts.append(datetime.fromisoformat(str(x)))
  except Exception:pass
 if len(ts)<3:return None
 # 取り出した順ではなく時刻で並べ直す。追記の順と時刻の順は普段そろっているが、
 # そろっている前提で引き算すると、ずれた1件で間隔が全部負になり、目安が消える。
 ts.sort(reverse=True)
 gaps=sorted(g for g in (int((ts[i]-ts[i+1]).total_seconds()//60) for i in range(len(ts)-1)) if g>0)
 if len(gaps)<2:return None
 return gaps[len(gaps)//2]

def fresh_expectation(job):
 """この対象が「これくらいで新しくなるはず」の分数と、その根拠を返す。

 根拠を一緒に返すのは、画面での言い方を変えるため。予定があるなら「予定より
 遅れています」でよいが、予定が無い対象に同じ言い方をすると、ありもしない予定に
 遅れたことになる。実際には「しばらく実行していません」でしかない。
 """
 gap=schedule_gap_minutes(job)
 if gap:return gap,'schedule'
 gap=observed_gap_minutes(job['id'])
 if gap:return gap,'observed'
 return MANUAL_FRESH_DEFAULT,'default'

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
  # 予定があればその間隔を、無ければ実績の間隔を「これくらいで新しくなるはず」の
  # 目安にする。どちらも取れないうちは既定の日数で見る（目安ゼロにはしない）。
  gap,gap_from=fresh_expectation(j)
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
                'expect_source':gap_from,
                'status':info.get('last_status',''),'rows':(run.get('rows') if run else None),
                'output':info.get('last_output',''),'held':bool(held),
                'pending':str((run.get('metrics') or {}).get('pending') or ''),
                # 差し替えられなかった理由と、粘った時間と、次にすること。
                # 何が起きたのか分からないまま「共有先が古いまま」とだけ出すのは、
                # 直しようのない不安を置いていくのと同じ。
                'hold_reason':str((run.get('metrics') or {}).get('hold_reason') or ''),
                'hold_waited':(run.get('metrics') or {}).get('hold_waited'),
                'hold_attempts':(run.get('metrics') or {}).get('hold_attempts'),
                'hold_advice':list((run.get('metrics') or {}).get('hold_advice') or [])})
 bad=[x for x in items if x['state']!='ok']
 held_n=len([x for x in items if x['state']=='held'])
 # 「取れているのに共有先が古い」は、失敗の次に急ぐ。読み手がいま騙されている状態なので、
 # 予定より遅れているだけのものより上へ出す。
 order={'failed':0,'held':1,'stale':2,'never':3,'ok':4}
 items.sort(key=lambda x:(order.get(x['state'],4),-(x['age_minutes'] or 0)))
 if held_n:summary=f'{held_n}件が共有先へ反映できていません'+(f'／ほか{len(bad)-held_n}件が確認待ち' if len(bad)>held_n else '')
 elif bad:summary=f'{len(bad)}件が確認待ちです'
 # 「予定どおり」とは言わない ―― 予定を持たない対象も同じ数に入っている。
 else:summary=f'{len(items)}件すべて新しい状態です'
 return {'ok':not bad,'items':items,'attention':len(bad),'held':held_n,'summary':summary}

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

def nearby_search_roots():
 roots=[]
 for p in (BASE,BASE.parent,BASE.parent.parent,DATA_ROOT,DATA_ROOT.parent):
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

PATH_SETTING_LABEL={'rne_folder':'RNE基本フォルダー','text_folder':'固定長テキストの基本フォルダー',
 'default_output_folder':'既定の出力先',
 'backup_folder':'バックアップ先','symnavi_exe':'SymNavi.exe','symnavim_conf':'symnavim.conf',
 'symnavim_def':'symnavim.def','accdb_template':'ACCDB空テンプレート','navigator_api_dll':'Navigator API DLL'}

PATH_SETTING_KIND={'rne_folder':'folder','text_folder':'folder','default_output_folder':'folder','backup_folder':'folder',
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
 # 固定長テキストの基本フォルダー。名前だけを書いた対象と、結合で読むファイルがここを基準にする。
 # RNE基本フォルダーと同じ考え方で、個別のパスを持つものはこの設定を一切見ない。
 def leans_on_text_root(raw):
  raw=str(raw or '').strip()
  if not raw:return False
  expanded=os.path.expandvars(os.path.expanduser(raw))
  if Path(expanded).is_absolute() or expanded.startswith('\\\\'):return False
  return not raw.startswith(('.\\','..\\','./','../'))
 text_users=[j for j in jobs if str(j.get('source') or '')=='text' and leans_on_text_root(j.get('text_path'))]
 join_users=[x for r in (c.get('join_recipes') or []) for x in (r.get('sources') or [])
             if leans_on_text_root(x.get('path'))]
 if text_users or join_users:
  roles['text_folder']=('required',
    '、'.join([f'{len(text_users)}件の対象' for _ in [1] if text_users]
             +[f'結合マスタの{len(join_users)}ファイル' for _ in [1] if join_users])+'がこの場所を基準にします')
 else:
  roles['text_folder']=('fallback','ファイル名だけで登録したときの基準です。いまはすべて個別のパスで解決できています')
 # 接続に関わる3つは、まとめて「DDEのもの」にはできない。使われ方がそれぞれ違う。
 # symnavim.conf は 1.99.0 から認証情報の「取り込み元」になった。正本はこのPCの置き場（資格情報マネージャー）で、
 # 登録済みならこのファイルは読まない。未登録のあいだだけ読む（配った日に抽出を止めないため）。
 # 無いことは赤くしない ―― 足りないのは「接続情報」で、それは事前診断の「Navigator の接続情報」が言う。
 try:saved=bool(NAVI_VAULT.load())
 except Exception:saved=False
 roles['symnavim_conf']=(('unused','接続情報はこのPCに登録済みのため、このファイルは読みません。共有に置いたままなら消してかまいません')
   if saved else ('fallback','接続情報がこのPCに未登録のあいだだけ、ここから読みます。「Navigator の接続情報」で取り込めば要らなくなります'))
 # SymNavi.exe：DDEでは起動する本体そのもの。APIでは起動しないが、SymNaviA.dllが
 # 検索範囲で見つからなかったときに限り、この隣を最後に探す（candidate_dllsの終端）。
 roles['symnavi_exe']=('required','SymfoNaviを起動してDDEでつなぎます') if engine=='dde' else \
   ('fallback','APIでは起動しません。SymNaviA.dllが見つからないときだけ、この隣を探す手がかりに使います')
 # symnavim.def：このアプリは中身を一度も読まず、SymfoNavi へ場所を渡してもいない（SymNavi.exe へは利用者ID・
 # パスワード・サーバーを引数で渡す）。DDEで指定してあれば「在ること」だけを実行前に確かめる。
 # 1.99.0 から空にできる ―― 空なら確かめない（アプリのフォルダーへ同梱しなくてよい）。
 if engine!='dde':roles['symnavim_def']=('unused','いまの抽出方式（Navigator API）では使いません')
 elif str(c.get('symnavim_def') or '').strip():
  roles['symnavim_def']=('required','DDE互換方式で、ここに在ることを実行前に確かめます（中身はアプリは読まず、SymfoNavi 側が使います）')
 else:
  roles['symnavim_def']=('fallback','未設定のため確かめません。アプリはこのファイルを読みません（SymfoNavi 側が自分の置き場で使います）')
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
    # 登録済みのPCで残っているなら、平文のパスワードが共有に置きっぱなしという注意（読まないので赤ではない）。
    if role=='unused':state='warn';note='接続情報はこのPCに登録済みです。このファイルには平文のパスワードが入っているので、共有から消してください'
    else:
     try:sec=navi_secret.read_conf(real)['section'];note=f'読み取れます（[{sec}] の利用者ID・パスワード・サーバー）。'+why
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
 fixed=[{'label':'アプリの場所','path':str(BASE),'note':'動いているプログラムの実体'},
        {'label':'データの基準','path':str(DATA_ROOT),'note':DATA_ROOT_NOTES.get(DATA_ROOT_SOURCE,'')},
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
