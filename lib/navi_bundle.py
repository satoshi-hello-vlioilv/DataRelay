"""登録した中身の持ち出しと持ち込み ―― 一式をZIPで、部分だけでも。

別のPCへ移すとき、新しく組むとき、控えを取っておくとき。そのたびに画面を見ながら
同じものを打ち直すのは、時間がかかるうえに必ず取りこぼす。登録したものを1つの
ファイルにまとめて持ち出し、持ち込み先で元に戻せるようにする。

持ち出すのは4つ。どれを入れるかは選べる（1つだけ選べば、それが個別の持ち出しになる）。

  対象の登録      … 何を、どこから読んで、どこへ出すか
  自動実行の予定  … いつ動かすか（対象の名前で結び直す）
  読取マスタ      … 固定長テキストを、どの位置で切るか
  結合マスタ      … 複数のファイルを、どの列で繋ぐか

中身は素のJSONで、ZIPを開けばそのまま読める形にする ―― 読めない形で持ち出すと、
アプリが動かないときに手も足も出なくなる。読取マスタと結合マスタは、これまでの
単体の持ち出しとまったく同じ形にしてある。ZIPから1つ取り出して、これまでどおり
「読取マスタの取り込み」へ渡してもそのまま通る。

id は持ち出さない。持ち込む先では別のものを指してしまうので、結び直しは名前で行う
（対象が使う読取マスタ・結合マスタも、名前を一緒に書いておく）。

ここは決まりだけを持つ。DBも画面も時計も触らないので、実際に走らせずに確かめられる
（navi_lane.py・navi_order.py と同じ約束）。共通設定（パス・接続先・控えの置き場所）は
持ち出さない ―― PCごとに違うものを持ち込むと、他人のフォルダーを指したまま動き出す。
"""
from __future__ import annotations
import io,json,re,zipfile
from datetime import datetime

BUNDLE_KIND='datarelay-bundle'
BUNDLE_VERSION=1
JOBS_KIND='datarelay-jobs'
JOBS_VERSION=1
SCHEDULES_KIND='datarelay-schedules'
SCHEDULES_VERSION=1
# 読取マスタと結合マスタは、これまでの単体の持ち出しと同じ印を使う（互換のため）。
LAYOUTS_KIND='symfonavi-text-layouts'
RECIPES_KIND='symfonavi-join-recipes'

PARTS=('jobs','schedules','layouts','recipes')
PART_LABEL={'jobs':'対象の登録','schedules':'自動実行の予定','layouts':'読取マスタ','recipes':'結合マスタ'}
PART_FILE={'jobs':'jobs.json','schedules':'schedules.json',
           'layouts':'text-layouts.json','recipes':'join-recipes.json'}
PART_KIND={'jobs':JOBS_KIND,'schedules':SCHEDULES_KIND,'layouts':LAYOUTS_KIND,'recipes':RECIPES_KIND}
# 中身の数え方（持ち出したものが何件かを、開かずに知りたい）。
PART_LIST_KEY={'jobs':'jobs','schedules':'jobs','layouts':'layouts','recipes':'recipes'}
MANIFEST='manifest.json'
README='README.txt'

# 対象から持ち出さない項目。id は持ち込む先で別のものを指すので置いていく。
# schedules は「自動実行の予定」として別に持ち出す（片方だけ持ち込めるようにするため）。
JOB_DROP=('id','schedules')
# 予定に持たせる項目。ここに無いものは持ち出さない。
SCHEDULE_TYPES=('daily','weekdays','monthly','specific_dates','interval')
TIME_RE=re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')
MAX_ITEMS=2000


def _now():
 return datetime.now().isoformat(timespec='seconds')


def _text(v,limit=400):
 return str(v if v is not None else '')[:limit]


# ---- 対象の登録 -------------------------------------------------------------
def job_export_one(job,layout_name='',recipe_name=''):
 """1件を持ち出す形へ。id は落とし、結び直しのための名前を足す。"""
 out={k:v for k,v in dict(job or {}).items() if k not in JOB_DROP}
 # 読取マスタ・結合マスタの id は環境ごとに違う。名前で結び直せるようにしておく。
 out.pop('layout_id',None);out.pop('recipe_id',None)
 # 値ごとに分けて出す（2.1.0）を使っていない対象は、その欄を書かない。2.0.0 までに書き出した物と同じ形にそろえる
 # （書くと、既定の設定と手元を比べたとき、使っていない全部の対象が「中身が違う」になる）
 v=out.get('variants')
 if not (isinstance(v,dict) and (v.get('enabled') or v.get('item') or v.get('values'))):out.pop('variants',None)
 if layout_name:out['layout_name']=_text(layout_name,120)
 if recipe_name:out['recipe_name']=_text(recipe_name,120)
 return out


def jobs_export(jobs,layout_name_of=None,recipe_name_of=None):
 """対象の登録を持ち出す。

 読取マスタ・結合マスタの名前は、引く手だてを呼ぶ側から渡してもらう（ここはDBを見ない）。
 """
 ln=layout_name_of or (lambda i:'')
 rn=recipe_name_of or (lambda i:'')
 items=[job_export_one(j,ln(j.get('layout_id') or ''),rn(j.get('recipe_id') or '')) for j in (jobs or [])]
 return {'kind':JOBS_KIND,'version':JOBS_VERSION,'exported_at':_now(),
         'count':len(items),'jobs':items}


def validate_job(job):
 """持ち込んでよいか。駄目な理由の一覧を返す（空なら通す）。"""
 bad=[]
 if not str(job.get('name') or '').strip():bad.append('名前がありません')
 src=str(job.get('source') or 'rne')
 if src not in ('rne','text','join'):bad.append(f'入力の種類が分かりません（{src}）')
 if src=='rne' and not str(job.get('rne') or job.get('rne_path') or '').strip():
  bad.append('RNEの指定がありません')
 if src=='text' and not str(job.get('text_path') or '').strip():
  bad.append('読み込むテキストの指定がありません')
 if not str(job.get('output_file') or '').strip():bad.append('出力ファイル名がありません')
 return bad


def jobs_import(payload):
 """取り込む。読めたものと、読めなかった理由を返す。

 中身が違うファイルを黙って取り込むと、登録が壊れる。印（kind）を必ず確かめる。
 """
 payload,err=_as_payload(payload,JOBS_KIND,'対象の登録')
 if err:return [],[err]
 out=[];bad=[]
 for i,x in enumerate((payload.get('jobs') or [])[:MAX_ITEMS],1):
  if not isinstance(x,dict):bad.append(f'{i}件目: 読める形ではありません');continue
  j={k:v for k,v in x.items() if k not in JOB_DROP}
  problems=validate_job(j)
  if problems:bad.append(f'{i}件目「{_text(j.get("name"),60) or "名前なし"}」: '+'／'.join(problems));continue
  out.append(j)
 if not out and not bad:bad.append('取り込める対象が1件もありませんでした')
 return out,bad


# ---- 自動実行の予定 ---------------------------------------------------------
def normalize_rule(rule):
 """予定1件を整える。持ち込む先で使える形に寄せる（id は置いていく）。"""
 r=dict(rule or {})
 kind=str(r.get('type') or 'daily')
 if kind not in SCHEDULE_TYPES:kind='daily'
 tm=str(r.get('time') or '06:00')
 if not TIME_RE.match(tm):tm='06:00'
 out={'enabled':bool(r.get('enabled',True)),'name':_text(r.get('name') or '実行ルール',80),
      'type':kind,'time':tm}
 if kind=='interval':
  try:out['interval_minutes']=max(1,int(r.get('interval_minutes') or 60))
  except (TypeError,ValueError):out['interval_minutes']=60
 if kind=='weekdays':
  out['weekdays']=sorted({int(x) for x in (r.get('weekdays') or []) if str(x).lstrip('-').isdigit() and 0<=int(x)<=6})
 if kind=='monthly':
  # 月末は -1 で持つ。1〜31 と -1 だけを通す。
  days=sorted({int(x) for x in (r.get('month_days') or []) if str(x).lstrip('-').isdigit()
               and (1<=int(x)<=31 or int(x)==-1)})
  out['month_days']=days or [1]
 if kind=='specific_dates':
  out['dates']=[str(x)[:10] for x in (r.get('dates') or []) if re.match(r'^\d{4}-\d{2}-\d{2}',str(x))][:200]
 return out


def validate_rule(rule):
 bad=[]
 kind=str(rule.get('type') or '')
 if kind not in SCHEDULE_TYPES:bad.append(f'実行パターンが分かりません（{kind}）')
 if kind=='weekdays' and not rule.get('weekdays'):bad.append('曜日が選ばれていません')
 if kind=='specific_dates' and not rule.get('dates'):bad.append('日付が選ばれていません')
 return bad


def schedules_export(jobs):
 """自動実行の予定を、対象の名前ごとに持ち出す。

 予定は対象にぶら下がっているが、別に持ち出せるようにしてある ―― 対象はそのままで
 予定だけを別のPCへ揃えたい、ということがあるため。結び直しは名前で行う。
 """
 items=[]
 for j in (jobs or []):
  rules=[normalize_rule(r) for r in (j.get('schedules') or [])]
  if not rules:continue
  items.append({'job_name':_text(j.get('name'),120),'schedules':rules})
 return {'kind':SCHEDULES_KIND,'version':SCHEDULES_VERSION,'exported_at':_now(),
         'count':sum(len(x['schedules']) for x in items),'jobs':items}


def schedules_import(payload):
 """取り込む。(対象名 → 予定の一覧) と、読めなかった理由を返す。"""
 payload,err=_as_payload(payload,SCHEDULES_KIND,'自動実行の予定')
 if err:return [],[err]
 out=[];bad=[]
 for i,x in enumerate((payload.get('jobs') or [])[:MAX_ITEMS],1):
  if not isinstance(x,dict):bad.append(f'{i}件目: 読める形ではありません');continue
  name=_text(x.get('job_name'),120).strip()
  if not name:bad.append(f'{i}件目: どの対象の予定か分かりません（名前がありません）');continue
  rules=[]
  for n,r in enumerate((x.get('schedules') or [])[:200],1):
   rule=normalize_rule(r);problems=validate_rule(rule)
   if problems:bad.append(f'「{name}」の{n}件目: '+'／'.join(problems));continue
   rules.append(rule)
  if not rules:continue
  out.append({'job_name':name,'schedules':rules})
 if not out and not bad:bad.append('取り込める予定が1件もありませんでした')
 return out,bad


# ---- 共通 -------------------------------------------------------------------
def _as_payload(payload,kind,label):
 """JSONを読み、印を確かめる。(中身, 駄目な理由) を返す。"""
 if isinstance(payload,(str,bytes)):
  try:payload=json.loads(payload if isinstance(payload,str) else payload.decode('utf-8-sig'))
  except Exception as e:return None,f'JSONとして読めません: {e}'
 if not isinstance(payload,dict):return None,f'{label}の持ち出しファイルではありません'
 if str(payload.get('kind') or '')!=kind:
  return None,f'{label}の持ち出しファイルではありません（kind={payload.get("kind") or "なし"}）'
 return payload,''


def part_of_kind(kind):
 """印から、どの部分かを引く。分からなければ空文字。"""
 for p,k in PART_KIND.items():
  if k==str(kind or ''):return p
 return ''


def count_of(part,payload):
 """その部分に何件入っているか。"""
 if not isinstance(payload,dict):return 0
 if part=='schedules':
  return sum(len(x.get('schedules') or []) for x in (payload.get('jobs') or []) if isinstance(x,dict))
 return len(payload.get(PART_LIST_KEY.get(part,'')) or [])


def readme_text(parts,counts,app_version=''):
 """ZIPを開いた人が、中身を見ずに分かるように。"""
 lines=['DataRelay 登録内容の持ち出し','',
        f'書き出した日時: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}']
 if app_version:lines.append(f'書き出したアプリの版: {app_version}')
 lines+=['','入っているもの:']
 for p in PARTS:
  if p not in parts:continue
  lines.append(f'  {PART_FILE[p]:<20} {PART_LABEL[p]}  {counts.get(p,0)}件')
 lines+=['','戻し方:',
         '  アプリの「共通設定」→「登録内容の持ち出し・持ち込み」で、このZIPをそのまま渡してください。',
         '  同じ名前のものは置き換え、無いものは追加します（登録済みのほかのものは消しません）。','',
         '中身について:',
         '  ・素のJSONです。ZIPを開けば、そのまま読めます。',
         '  ・text-layouts.json と join-recipes.json は、これまでの単体の持ち込みへ',
         '    そのまま渡すこともできます。',
         '  ・対象が使う読取マスタ・結合マスタは、名前で結び直します。',
         '  ・自動実行の予定は、対象の名前で結び直します。',
         '  ・共通設定（各種フォルダーの場所・接続先・控えの置き場所）は入っていません。',
         '    PCごとに違うものなので、持ち込むと他人のフォルダーを指したまま動き出します。',
         '  ・実行の実績（いつ何件出したか）も入っていません。','']
 return '\n'.join(lines)


def build_zip(payloads,app_version=''):
 """部分ごとのJSONを1つのZIPにまとめて、バイト列で返す。

 payloads は {'jobs':{...},'layouts':{...}} の形。入っているものだけを詰める。
 """
 parts=[p for p in PARTS if p in (payloads or {}) and payloads[p] is not None]
 counts={p:count_of(p,payloads[p]) for p in parts}
 manifest={'kind':BUNDLE_KIND,'version':BUNDLE_VERSION,'exported_at':_now(),
           'app_version':str(app_version or ''),
           'parts':[{'part':p,'label':PART_LABEL[p],'file':PART_FILE[p],
                     'kind':PART_KIND[p],'count':counts[p]} for p in parts],
           'counts':counts}
 buf=io.BytesIO()
 # 素のJSONを詰める。開いた人が読めることを、圧縮率より優先する（それでも十分小さい）。
 with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr(MANIFEST,json.dumps(manifest,ensure_ascii=False,indent=1))
  z.writestr(README,readme_text(parts,counts,app_version))
  for p in parts:
   z.writestr(PART_FILE[p],json.dumps(payloads[p],ensure_ascii=False,indent=1))
 return buf.getvalue(),manifest


def looks_like_bundle(blob):
 """このバイト列は、この一式のZIPか。EXCELもZIPなので、中身の名前で見分ける。"""
 if not blob or blob[:2]!=b'PK':return False
 try:
  with zipfile.ZipFile(io.BytesIO(blob)) as z:
   names=set(z.namelist())
   return MANIFEST in names or any(f in names for f in PART_FILE.values())
 except Exception:
  return False


def read_zip(blob):
 """ZIPから部分ごとのJSONを取り出す。(中身, 覚書, 読めなかった理由) を返す。

 覚書（manifest）が無くても、入っているファイルの名前と印から読み取る ―― 手で
 組み直したZIPや、1つだけ入れ替えたZIPでも受け取れるようにするため。
 """
 out={};bad=[];manifest={}
 try:
  with zipfile.ZipFile(io.BytesIO(blob)) as z:
   names=set(z.namelist())
   if MANIFEST in names:
    try:manifest=json.loads(z.read(MANIFEST).decode('utf-8-sig'))
    except Exception as e:bad.append(f'{MANIFEST} を読めません: {e}')
   if isinstance(manifest,dict) and manifest.get('kind') and str(manifest['kind'])!=BUNDLE_KIND:
    return {},{},[f'DataRelay の持ち出しファイルではありません（kind={manifest.get("kind")}）']
   for part,fname in PART_FILE.items():
    if fname not in names:continue
    try:body=json.loads(z.read(fname).decode('utf-8-sig'))
    except Exception as e:bad.append(f'{fname} を読めません: {e}');continue
    if not isinstance(body,dict) or str(body.get('kind') or '')!=PART_KIND[part]:
     bad.append(f'{fname} の中身が {PART_LABEL[part]} ではありません');continue
    out[part]=body
 except zipfile.BadZipFile:
  return {},{},['ZIPとして読めません']
 except Exception as e:
  return {},{},[f'読み取れません: {e}']
 if not out and not bad:bad.append('取り込めるものが1件も入っていません')
 return out,(manifest if isinstance(manifest,dict) else {}),bad


def wanted_parts(raw):
 """画面から来た「どれを入れるか」を、決まった並びの一覧へ。空なら全部。"""
 if raw is None:return list(PARTS)
 if isinstance(raw,str):raw=[x.strip() for x in raw.split(',')]
 want={str(x).strip() for x in (raw or [])}
 if not want or 'all' in want:return list(PARTS)
 return [p for p in PARTS if p in want]


def summary_text(result):
 """持ち込んだ結果を、画面へ出す1行に。"""
 out=[]
 for p in PARTS:
  r=(result or {}).get(p)
  if not r:continue
  n_add=len(r.get('added') or []);n_rep=len(r.get('replaced') or [])
  if not n_add and not n_rep:continue
  out.append(f'{PART_LABEL[p]} 追加{n_add}・置き換え{n_rep}')
 return ' / '.join(out) or '取り込んだものはありません'
