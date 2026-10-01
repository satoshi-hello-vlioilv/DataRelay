"""分割の試し打ちと、その設計。

同じRNEを「分けずに1回」と「列や行で分けて同時に」の両方で実際に走らせ、
速いほうを実測で決める。決まった割り当ては保存され、次からの本番の抽出は
それを読むだけで済む ―― だからここは本番の実行経路には入っていない。

本番との行き来は一方通行になっている。こちらから本番の _spawn_racers を
呼ぶだけで、本番からこちらを呼ぶことは無い（実測 2026-08-12: 跨いでいる
呼び出しは1本、逆向きは0本）。分けられるのはそのため。

借り方は navi_web / navi_diag と同じ約束で、取り込んだ時点の実体を受け取る。
検査が app.X を差し替えても、こちら側は古いままになる。差し替える検査を
書くときは、app と navi_split の両方へ入れること。
共有している入れ物（split_trial_state など）は中身を書き換えるだけで、
丸ごと差し替わることはないので、実体を持っていて構わない。
"""
import contextlib,csv,json,shutil,sqlite3,time
from datetime import datetime
from pathlib import Path
import app
# 定数・鍵・共有の入れ物・例外クラス。丸ごと差し替わることが無いので、実体を持つ。
# 鍵と入れ物は「同じものを見ている」ことに意味があるため、写しを作ってはいけない。
from app import (LOCAL_RUNTIME, SPLIT_MEASURE, SPLIT_PART_STEPS, SPLIT_TRIAL_PHASES,
                 SplitRowsetMismatch, _split_stage_logged, log, settings_sync_lock,
                 split_trial_lock, split_trial_state)

def _borrow(name):
 """本体の関数は、取り込んだ時点の実体ではなく、呼ばれた時点で引く。

 実体で受け取ると、検査が app.X を差し替えてもこちらは古いままになる。
 v1.65.0で受け口を分けたときは、これに気づかず8本の検査が黙って素通りした。
 v1.71.0でここを分けたときも、影実行の検査が同じ理由で落ちている
 （app.creds などを差し替えても効かず、列の判定で止まった）。
 差し替えは検査だけの話ではなく、将来どこかで挿し替える余地でもあるので、
 借りる側で塞いでおく。1回の呼び出しにつき属性を1つ引くだけで、この処理は
 実際の抽出（数十秒）が支配的なため測れるほどの差にはならない。
 """
 def call(*a,**k):return getattr(app,name)(*a,**k)
 call.__name__=name;call.__qualname__='app.'+name
 return call

for _n in ('_mark_settings_dirty',
           '_rne_key',
           '_spawn_racers',
           '_viewer_output_path',
           'axis_balance_cached',
           'axis_option',
           'axis_value_weights',
           'block_row_axis',
           'blocked_row_axes',
           'creds',
           'crosstab_split_reason',
           'duplicate_columns',
           'load_column_cache',
           'load_rne_timing',
           'merge_column_parts',
           'merge_row_parts',
           'normalize_output_format',
           'normalize_row_axis_mode',
           'normalize_split_mode',
           'normalize_split_shape',
           'pick_row_axis_by_mode',
           'plan_axis_split',
           'qi',
           'read_header_names',
           'resolve_axis_now',
           'resolve_path',
           'resolve_rne_path',
           'rne_signature',
           'row_filter_cost',
           'save_column_cache',
           'settings_connection',
           'split_axis_reload_seconds',
           'split_expected_bytes',
           'split_payload_profile',
           'split_shape_label',
           'split_time_model',
           'split_transfer_ratio'):globals()[_n]=_borrow(_n)
del _n


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
  with contextlib.closing(sqlite3.connect(path)) as conn:
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

def split_trial_options(job,cfg,row_parts=2):
 """この対象で、いま何が測れるのか。測る前に1か所で決める。

 これまでは選択肢を全部出しておいて、走らせてから「分割して取得できる列がありません」と
 断っていた。しかも基準まで一緒に落ちるので、ほかの分け方が何と比べた数字なのかも
 分からなくなっていた（実測 2026-08-12 SIKALOT.RNE / removable=0）。
 選べるものと選べないものを、理由つきで先に返す。

 返すもの（それぞれ ok と why を持つ）:
   column … 列分割。外せる列が1本も無ければ選べない
   row    … 行分割。使える軸が1本も無ければ選べない。axes に軸の一覧
            （row_parts で判定する。片数が増えるほど条件式が長くなり、使える軸は減る）
   grid   … 行×列。両方が成り立つときだけ
   baseline … 保存済みの基準（あれば、いつ測ったものか）

 「走らせてみないと分からない」ものは、ここで先に潰す。値が空の行がある軸と、
 ひとつの値に行が集中している軸は、実測しなくても結果が分かっている：
 前者は必ず行が落ち（一致しない）、後者は分けても一番重い片が縮まない。
 どちらも1回2分前後を捨てることになるので、選べる側には出さない。
 """
 rp=resolve_rne_path(job,cfg)
 out={'rne':str(rp),'job':job.get('name',''),'ready':False,
      'column':{'ok':False,'why':''},'row':{'ok':False,'why':'','axes':[]},
      'grid':{'ok':False,'why':''},'baseline':None,'columns':0,'removable':0}
 if not Path(rp).is_file():
  # 理由を空で返すと、画面には「選べない」だけが出て手がかりが無くなる。
  why=f'RNEが見つかりません: {rp}'
  out['error']=why
  for k in ('column','row','grid'):out[k]['why']=why
  return out
 why=crosstab_split_reason(rp)
 if why:
  out['error']=why
  for k in ('column','row','grid'):out[k]['why']=why
  return out
 # 列と行は別々の控えから決める。列分割は列の一覧が要るが、行分割は管理ポイントの
 # 一覧しか要らない。まとめて「列を調べてください」と断っていたため、手順1が
 # 「行 2分割可」と出しているのに行分割へチェックを入れられなかった（利用者からの指摘）。
 # 使えるかどうかは片数しだい。行を絞る条件式は片数が増えるほど長くなり、ある長さで
 # サーバーに断られる（KVR52020）。画面で選んだ片数をそのまま渡してもらう。
 parts=max(2,min(8,int(row_parts or 2)))
 cached=load_column_cache(rp)
 col_ready=bool(cached and not cached.get('stale') and cached.get('columns'))
 if not col_ready:
  out['column']['why']=('RNEが更新されています。もう一度「RNEを調査」を実行してください'
                        if (cached and cached.get('stale')) else '先に「RNEを調査」で列を読み込んでください')
  out['need_columns']=True
 else:
  columns=cached['columns'];removable=[x['name'] for x in (cached.get('classify') or []) if x.get('removable')]
  out['columns']=len(columns);out['removable']=len(removable)
  # 断る理由は、実際に断っている理由でなければならない。同名の列があると列分割は
  # 成立しないのに、ここでは「外せる列」しか見ていなかったため「外せる189本」を
  # 数えて選ばせ、走らせたあとで「分割して取得できる列がありません」と、
  # 起きていないことを理由に断っていた（実測 2026-08-13 SIKALOT.RNE）。
  dupes=duplicate_columns(columns)
  # 直近の出力が無いと錨が立てられない。行が変わると分かっているRNEでは、
  # 錨なしの列分割は影実行の入口で必ず止まる。
  had_output=False
  try:had_output=_viewer_output_path(job,cfg).is_file()
  except Exception:had_output=False
  if dupes:
   names='、'.join(d['name'] for d in dupes[:3])+('ほか' if len(dupes)>3 else '')
   out['duplicates']=[d['name'] for d in dupes[:10]]
   out['column']={'ok':False,'why':f'同じ名前の列があります（{names}）。'
                  '列分割は列名で担当を決めて、結合でも列名を突き合わせるため、この形は成立しません'}
  elif not removable:
   out['column']={'ok':False,'why':f'外せる列が1本もありません（{len(columns)}本すべてが結合キーか必須です）'}
  elif split_incompatible(rp) and not had_output:
   out['column']={'ok':False,'why':'このRNEは、列を外すと返ってくる行そのものが変わることが確認済みです。'
                  '行をつなぎ留める錨の列は直近の出力から探しますが、その出力がまだありません。'
                  '1回実行してからお試しください'}
  else:
   out['column']={'ok':True,'why':f'{len(columns)}本のうち{len(removable)}本を分けて運べます'}
 # 行分割は軸しだい。下調べがあれば、使える軸をそのまま出す。
 sv=load_axis_survey(rp)
 axes=[]
 # 見込みを出すための材料。どれも保存済みの実測から引くだけで、問い合わせはしない。
 #   model  … 1片にかかる秒数の式（基準の実測が要る）
 #   axsec  … 行分割で毎回かかる軸の読み直し（本番でも払う）
 #   scores … 直近の出力から測った、軸ごとの散らばりと空の行
 model=split_time_model(rp,cfg.get('settings') or {})
 axsec=split_axis_reload_seconds(rp) or 0.0
 gate=float((cfg.get('settings') or {}).get('split_min_speedup',1.05) or 1.05)
 scores=axis_balance_cached(job,cfg,[a.get('name') for a in (sv.get('axes') or [])]) if sv else {}
 out['model']=model;out['axis_seconds']=axsec or None;out['min_speedup']=gate
 if sv:
  # 過去にサーバーが拒否した軸（条件式が長すぎた等）は、選べる側へ出さない。
  blocks=set(blocked_row_axes(rp))
  # 1本ずつの判定は axis_option が持つ（軸の判定はぜんぶ本体側にまとめてある）。
  for a in (sv.get('axes') or []):
   axes.append(axis_option(a,scores.get(a.get('name','')),parts,model,axsec,gate,a.get('name','') in blocks))
  # 使える軸は「見込みの速い順」に並べる。番号順に並べていたので、いちばん上の軸を
  # 選ぶと、たまたま偏った軸を掴んでいた。速くならない軸を先頭に置く理由は無い。
  axes.sort(key=lambda x:(not x['usable'],-((x['gain'] or {}).get('run_speedup') or 0),x['index']))
 out['row']['axes']=axes
 good=[x for x in axes if x['usable']]
 if good:
  best=good[0]
  tip=''
  if (best.get('gain') or {}).get('run_speedup'):
   tip=f'。いちばん速い見込みは「{best["name"]}」で{best["gain"]["run_speedup"]}倍'
  out['row']={'ok':True,'why':f'{len(good)}本の管理ポイントで行を絞れます'+tip,'axes':axes}
 elif sv:
  # 「1本も無い」と「あるが速くならない／行が落ちる」は、利用者から見て別の話。
  # 直し方が違うので、まとめて同じ文で断らない。
  slow=[x for x in axes if (x.get('gain') or {}).get('run_speedup')]
  blank=[x for x in axes if x.get('blank_rows')]
  if slow:
   b=max(slow,key=lambda x:x['gain']['run_speedup'])
   why=(f'{len(axes)}本の管理ポイントはどれも行が一か所に集まっていて、{parts}つに分けても速くなりません'
        f'（いちばんましな「{b["name"]}」で{b["gain"]["run_speedup"]}倍／基準は{gate}倍）。'
        '片数を増やすか、別の管理ポイントを持つRNEでお試しください')
  elif blank:
   why=(f'行を絞れる管理ポイントがありません（{len(blank)}本は値が空の行があり、'
        '分けるとその行が結果から落ちます）')
  else:
   why='行を絞れる管理ポイントがありません（値が2種以上あるものが要ります）'
  out['row']={'ok':False,'why':why,'axes':axes}
 else:
  out['row']={'ok':False,'why':'先に「RNEを調査」で管理ポイントを読み込んでください','axes':axes,'need_survey':True}
 # 測る画面を出せるかどうかは「列か行のどちらかが決まっているか」。片方だけでも測れる。
 out['ready']=bool(out['column']['ok'] or out['row']['ok'])
 # 行×列は両方が成り立つときだけ
 if out['column']['ok'] and out['row']['ok']:
  out['grid']={'ok':True,'why':'行と列の両方で分けます'}
 else:
  ng=[x for x,k in ((out['column']['why'],'column'),(out['row']['why'],'row')) if not out[k]['ok']]
  out['grid']={'ok':False,'why':'／'.join(ng) or '成り立ちません'}
 b=load_split_baseline(rp)
 if b:
  age=None
  try:age=round((datetime.now()-datetime.fromisoformat(str(b.get('taken_at')))).total_seconds()/60.0,1)
  except Exception:age=None
  out['baseline']={'taken_at':b.get('taken_at'),'age_minutes':age,'rows':b.get('rows'),
                   'elapsed':b.get('elapsed'),
                   # 本番のデータは動く。古い基準と比べると、分け方は正しいのに
                   # 「一致しません」になる（実測: 10分で41行が入れ替わった）。
                   'stale':bool(age is not None and age>10)}
 return out

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
 # 列の条件を課すのは「実際に列を外すとき」だけ。基準（分割なしを1回測るだけ）と行分割は
 # 列を1本も外さないので、外せる列が無くても走れる。
 #   実測 2026-08-12: removable=0 のRNEで基準が mode=column として投げられ、
 #   「分割して取得できる列がありません」で基準そのものが失敗していた。基準が無いと、
 #   ほかの分け方が何と比べた数字なのか分からなくなる（利用者からの指摘そのもの）。
 uses_columns=(mode!='row' and measure!='normal')
 # 走り出す前に断るときは、必ず理由をログへ残す。以前は黙って戻っていたため、
 # 画面には短い文が出るだけで、なぜ止まったのかがログから追えなかった。
 def stop(reason,**kw):
  log.warning('SPLIT_TRIAL_ABORT rne=%s job=%s mode=%s 理由=%s',rp,job.get('name'),mode,reason)
  return dict(ok=False,error=reason,**kw)
 why=crosstab_split_reason(rp)
 if why:return stop(why)
 cached=load_column_cache(rp)
 if not cached or cached['stale'] or not cached['columns']:
  return stop('先に「列の分割可否を調べる」を実行してください（列定義が未取得か、RNEが更新されています）')
 columns=cached['columns'];removable=[x['name'] for x in (cached.get('classify') or []) if x.get('removable')]
 # 同名の列が困るのは、列名で担当を決めて列名で突き合わせる列分割のときだけ。
 # 行分割はどの片も全列を持ち、縦に積むだけなので同名でも取り違えようがない。
 # この判定は「外せる列があるか」より先に置く。あとに置いていたので、外せる列が
 # 189本あって同名の列で止まっている状況でも「分割して取得できる列がありません」と、
 # 起きていないことを理由に断っていた（実測 2026-08-13 SIKALOT.RNE）。
 dupes=duplicate_columns(columns)
 if dupes and uses_columns and not data.get('force'):
  log.warning('SPLIT_TRIAL_DUPLICATES rne=%s names=%s',rp,[d['name'] for d in dupes[:10]])
  return stop('同じ名前の列が複数あるため、列分割は行えません（'
                    +'、'.join(f"{d['name']}×{d['count']}" for d in dupes[:5])
                    +('ほか' if len(dupes)>5 else '')
              +'）。列分割は列名で担当を決め、結合でも列名を突き合わせるため、'
               '同名の列があると外す対象を取り違えたり、結合で片方が消えたりします。'
               'RNE側で列名を分けてから再度お試しください。',duplicates=dupes)
 if not removable and uses_columns:
  return stop(f'分割して取得できる列がありません（{len(columns)}本すべてが結合キーか必須です）')
 trials=load_split_trials(rp)
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
  scores=axis_balance_cached(job,c,[a.get('name') for a in row_axis_all])
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
   # 走らせる前に、結末が分かっているものを止める。ここで止めれば2分が浮く。
   #   実測 2026-08-13 SIKALOT.RNE: 空の行が42行あると事前に記録していながら走らせ、
   #   64秒かけて「分割なしにだけ42行ある」＝一致しない、で終わった。
   # 判定は測る画面（split_trial_options）と同じ axis_option を通す。別々に書くと、
   # 画面では選べるのに走らせると断られる、という食い違いが必ずどこかで生まれる。
   opt=axis_option(row_axis,scores.get(row_axis.get('name','')),row_parts,
                   split_time_model(rp,c.get('settings') or {}),split_axis_reload_seconds(rp) or 0.0,
                   float(c['settings'].get('split_min_speedup',1.05) or 1.05))
   fc=opt.get('gain')
   if fc:
    # 見込みは必ずログへ残す。あとで実測と並べれば、式が合っているかを検算できる。
    log.info('SPLIT_TRIAL_AXIS_FORECAST rne=%s 軸=%s いちばん多い値=%.0f%% %s分割 → 一番重い片 約%.0fs '
             '見かけ%.2f倍 / 軸の読み直し%.0fsを含めた実力%.2f倍（分割なし %.0fs）',
             rp,row_axis['name'],(opt.get('top_share') or 0)*100,row_parts,fc['heavy_seconds'],fc['speedup'],
             fc['axis_seconds'],fc['run_speedup'],fc['normal_seconds'])
   if not opt['usable'] and not data.get('force'):
    return stop(f'「{row_axis["name"]}」は{opt["why"]}。別の軸か、別の片数でお試しください。',
                forecast=fc,axis=row_axis.get('name'),blank_rows=opt.get('blank_rows') or 0)
 work=LOCAL_RUNTIME/('split_trial_'+datetime.now().strftime('%Y%m%d_%H%M%S'));work.mkdir(parents=True,exist_ok=True)
 user,pw,server,_=creds(resolve_path(c['symnavim_conf']))
 # 基準は分け方を持たない。mode= に column と出ると「列分割を試して失敗した」と読めてしまう。
 log.info('SPLIT_TRIAL_START rne=%s job=%s mode=%s 列%s分割 行%s分割 columns=%s removable=%s keys=%s transfer_ratio=%.2f',
          rp,job['name'],('normal（分割なしの基準）' if measure=='normal' else mode),
          len(plan) if mode!='row' else 1,row_parts if mode!='column' else 1,
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
  # 保存済みの基準を使い回すと、時間がたつほど本番のデータが動く。過不足が両方向とも
  # 同数でセルの差が0なら、それは分け方の問題ではなく「基準が古い」だけ。
  #   実測 2026-08-12: 基準 22:35:52 に対し行分割 22:46〜22:49。only_normal=41 /
  #   only_merged=41 / diff_cells=0 で、良い結果（1.39倍）が捨てられていた。
  baseline_age=None
  if baseline and baseline.get('taken_at'):
   try:baseline_age=max(0.0,(datetime.now()-datetime.fromisoformat(str(baseline['taken_at']))).total_seconds())
   except Exception:baseline_age=None
  stale_baseline=bool(baseline and not identical
                      and int(cmp.get('only_normal') or 0)==int(cmp.get('only_merged') or 0)
                      and int(cmp.get('only_normal') or 0)>0
                      and not int(cmp.get('diff_cells') or 0)
                      and not (cmp.get('missing_axis') or {}).get('concentrated')
                      and not (cmp.get('missing_axis') or {}).get('all_blank'))
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
   if stale_baseline:
    log.warning('SPLIT_TRIAL_STALE_BASELINE rne=%s 基準を取ってから%.0f分たっています。'
                '過不足が両方向とも同数（%s行）でセルの差は0なので、分け方ではなく'
                '本番のデータが動いたと考えられます。基準を測り直してください',
                rp,(baseline_age or 0)/60.0,cmp.get('only_normal'))
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
                 stale_baseline=stale_baseline,baseline_age_seconds=round(baseline_age,1) if baseline_age else None,
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
