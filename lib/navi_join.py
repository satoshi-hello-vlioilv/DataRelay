"""複数のファイルを、キーで突き合わせて1つの表にする。

読取マスタが「1つのファイルをどう切るか」なら、こちらは「複数のファイルをどう繋ぐか」。
繋ぎ方に名前を付けて保存し（結合マスタ）、対象から選んで使う。そこから先の変換・公開・
控え・同時出力は、RNEでも固定長テキストでもまったく同じ道を通る。

繋ぐ仕事そのものはSQLiteに任せる。読み込んだ表をメモリ上のDBへ置き、SELECT文を組み立てて
実行する ―― 自前で突き合わせを書くより速く、正しく、そして「何が起きたか」を数えられる。

いちばん難しいのは結合の失敗が静かなことで、キーを1つ間違えただけで0件になったり、
何倍にも膨らんだりする。しかもファイルは出来上がってしまう。だから、走らせる前に
「このつなぎ目で何件合うのか」を必ず数えて見せる。

app.py から分けてある。本体の状態は一切見ない（読むのはファイルと、渡された取り決めだけ）。
"""
import csv,json,sqlite3
from datetime import datetime
from pathlib import Path
from navi_log import log

JOIN_TYPES=('inner','left','full')
JOIN_TYPE_LABEL={'inner':'両方にあるものだけ','left':'左を全部残す','right':'右を全部残す','full':'どちらも全部残す'}
JOIN_TYPE_NOTE={'inner':'キーが一致した行だけを出します',
                'left':'左に無い行は出ません。右に無いものは空欄で残ります',
                'full':'どちらか片方にしか無い行も、空欄付きで残します'}
JOIN_TYPE_SQL={'inner':'INNER JOIN','left':'LEFT JOIN','full':'FULL OUTER JOIN'}
SOURCE_FORMATS=('csv','txt','xlsx','sqlite3','accdb','fixed')
SOURCE_FORMAT_LABEL={'csv':'CSV','txt':'TXT（タブ区切り）','xlsx':'EXCEL','sqlite3':'SQLite3',
                     'accdb':'ACCESS','fixed':'固定長テキスト（読取マスタ）'}
RECIPE_EXPORT_KIND='symfonavi-join-recipes'
RECIPE_EXPORT_VERSION=1
MAX_SOURCES=8
ALIASES='ABCDEFGH'

def qi(name):
 """識別子を引用符でくくる。中の引用符は二重にして閉じさせない。"""
 return '"'+str(name).replace('"','""')+'"'

_full_join_ok=None
def sqlite_supports_full():
 """このPythonのSQLiteが FULL OUTER JOIN を書けるか（3.39以降）。

 書けない環境で選ばせると、走らせて初めて落ちる。選ばせない側で使う。
 """
 global _full_join_ok
 if _full_join_ok is None:
  try:
   c=sqlite3.connect(':memory:')
   c.execute('CREATE TABLE a(x)');c.execute('CREATE TABLE b(x)')
   c.execute('SELECT * FROM a FULL OUTER JOIN b ON a.x=b.x');c.close()
   _full_join_ok=True
  except Exception:
   _full_join_ok=False
   log.info('JOIN_FULL_UNSUPPORTED sqlite=%s（「どちらも全部残す」は選べません）',sqlite3.sqlite_version)
 return _full_join_ok

def join_types_available():
 return [t for t in JOIN_TYPES if t!='full' or sqlite_supports_full()]

def normalize_source(d,index=0):
 d=dict(d or {})
 fmt=str(d.get('format') or '').strip().lower()
 fmt={'sqlite':'sqlite3','db':'sqlite3','excel':'xlsx','xls':'xlsx','text':'fixed'}.get(fmt,fmt)
 if fmt not in SOURCE_FORMATS:
  ext=Path(str(d.get('path') or '')).suffix.lower()
  fmt={'.csv':'csv','.txt':'txt','.xlsx':'xlsx','.sqlite3':'sqlite3','.sqlite':'sqlite3',
       '.db':'sqlite3','.accdb':'accdb'}.get(ext,'csv')
 return {'alias':str(d.get('alias') or (ALIASES[index] if index<len(ALIASES) else f'S{index+1}')),
         'name':str(d.get('name') or '').strip(),
         'path':str(d.get('path') or '').strip(),'format':fmt,
         'table':str(d.get('table') or '').strip(),'sheet':str(d.get('sheet') or '').strip(),
         'layout_id':str(d.get('layout_id') or '').strip()}

def normalize_join(d):
 d=dict(d or {})
 t=str(d.get('type') or '').strip().lower()
 if t not in JOIN_TYPES:t='inner'
 keys=[]
 for k in (d.get('keys') or []):
  left=str((k or {}).get('left') or '').strip();right=str((k or {}).get('right') or '').strip()
  if left or right:keys.append({'left':left,'right':right})
 return {'type':t,'keys':keys[:6]}

def normalize_recipe(d):
 """結合マスタ1件を整える。

 繋ぎ方は「左から右へ1本の鎖」にしてある。2つ目のファイルは1つ目へ、3つ目はそこまでの
 結果へ繋ぐ。枝分かれを許すと、画面でも頭の中でも組み立てが一気に難しくなる ――
 実務で要るのはほとんど鎖なので、そこだけを、迷いようのない形で持つ。
 """
 d=dict(d or {})
 srcs=[normalize_source(x,i) for i,x in enumerate(d.get('sources') or [])][:MAX_SOURCES]
 for i,s in enumerate(srcs):s['alias']=ALIASES[i] if i<len(ALIASES) else f'S{i+1}'
 joins=[normalize_join(x) for x in (d.get('joins') or [])]
 # つなぎ目は「2つ目以降のファイルの数」ぶん。足りなければ足し、多ければ切る。
 need=max(0,len(srcs)-1)
 while len(joins)<need:joins.append(normalize_join({}))
 joins=joins[:need]
 cols=[]
 for c in (d.get('columns') or []):
  c=dict(c or {})
  name=str(c.get('name') or '').strip()
  if not name:continue
  cols.append({'source':str(c.get('source') or 'A').strip(),'name':name,
               'as':str(c.get('as') or '').strip()})
 return {'id':str(d.get('id') or '').strip(),'name':str(d.get('name') or '').strip(),
         'description':str(d.get('description') or '').strip(),
         'sources':srcs,'joins':joins,'columns':cols,
         'updated_at':str(d.get('updated_at') or '')}

def validate_recipe(recipe):
 """このままでは使えない理由。空なら保存してよい。"""
 r=normalize_recipe(recipe);bad=[]
 if not r['name']:bad.append('結合マスタ名を入れてください')
 if len(r['sources'])<2:bad.append('ファイルを2つ以上選んでください（結合するものが1つでは繋げません）')
 for i,s in enumerate(r['sources'],1):
  if not s['path']:bad.append(f'{i}つ目のファイルの場所を入れてください')
  if s['format']=='fixed' and not s['layout_id']:
   bad.append(f'{i}つ目は固定長テキストです。読取マスタを選んでください')
 for i,j in enumerate(r['joins'],1):
  ok=[k for k in j['keys'] if k['left'] and k['right']]
  if not ok:bad.append(f'{i}つ目のつなぎ目に、突き合わせる列（キー）を1組以上決めてください')
  if j['type']=='full' and not sqlite_supports_full():
   bad.append(f'{i}つ目のつなぎ目「どちらも全部残す」は、このPCのSQLite（{sqlite3.sqlite_version}）では使えません')
 seen={}
 for c in r['columns']:
  out=c['as'] or c['name']
  seen[out]=seen.get(out,0)+1
 dupes=[k for k,v in seen.items() if v>1]
 if dupes:bad.append('出す列の名前が重なっています（'+'、'.join(dupes[:5])+'）。別名を付けてください')
 return bad

# ---- 読み込み --------------------------------------------------------------
def read_source(src,reader,layouts=None,limit=None):
 """1つのファイルを (見出し, 本体) で読む。

 これまでの出力形式（CSV・TXT・EXCEL・SQLite3・ACCESS）はデータビュワーと同じ読み手を
 使う。同じものを2通りに読むと、画面で見えているものと結合の中身がずれる。
 """
 s=normalize_source(src)
 if s['format']=='fixed':
  lay=(layouts or {}).get(s['layout_id'])
  if not lay:raise ValueError(f'{s["alias"]}: 読取マスタが見つかりません')
  from navi_text import read_text_rows
  headers,rows,_stat=read_text_rows(s['path'],lay,limit=limit)
  return headers,[list(r) for r in rows]
 headers,rows=reader(s,limit)
 return list(headers),[list(r) for r in rows]

def _table_name(alias):return 't_'+str(alias)

def load_sources(recipe,reader,layouts=None,limit=None):
 """全部のファイルをメモリ上のDBへ置く。(接続, 表ごとの内訳) を返す。"""
 r=normalize_recipe(recipe)
 conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
 meta=[]
 for s in r['sources']:
  headers,rows=read_source(s,reader,layouts,limit)
  if not headers:raise ValueError(f'{s["alias"]}（{Path(s["path"]).name}）に列がありません')
  # 同じ名前の列は、後ろに番号を足して区別する（結合の突き合わせで取り違えないため）。
  seen={};cols=[]
  for h in headers:
   h=str(h) if h is not None else ''
   h=h or f'列{len(cols)+1}'
   if h in seen:seen[h]+=1;h=f'{h}_{seen[h]}'
   else:seen[h]=1
   cols.append(h)
  t=_table_name(s['alias'])
  conn.execute(f'CREATE TABLE {qi(t)} ('+','.join(qi(c)+' TEXT' for c in cols)+')')
  conn.executemany(f'INSERT INTO {qi(t)} VALUES('+','.join('?' for _ in cols)+')',
                   [[('' if v is None else str(v)) for v in (row+['']*(len(cols)-len(row)))[:len(cols)]] for row in rows])
  meta.append({'alias':s['alias'],'table':t,'columns':cols,'rows':len(rows),
               'path':s['path'],'format':s['format'],
               'name':s['name'] or Path(s['path']).name})
 return conn,meta

def auto_columns(recipe,meta):
 """出す列を決めていないときの既定。1つ目の全部と、2つ目以降の「まだ無い名前」。

 何も選ばなくても、たいてい欲しい形になるようにしておく。キーの列が2度出ないのも
 ここで効く（同じ名前は先に出たほうを残す）。
 """
 out=[];used=set()
 for m in meta:
  for c in m['columns']:
   if c in used:continue
   used.add(c);out.append({'source':m['alias'],'name':c,'as':''})
 return out

def build_sql(recipe,meta,limit=None):
 """組み立てたSELECT文と、出す列の名前を返す。"""
 r=normalize_recipe(recipe)
 by={m['alias']:m for m in meta}
 cols=r['columns'] or auto_columns(r,meta)
 select=[]
 names=[]
 for c in cols:
  m=by.get(c['source']) or meta[0]
  if c['name'] not in m['columns']:continue
  out=c['as'] or c['name']
  select.append(f'{qi(m["table"])}.{qi(c["name"])} AS {qi(out)}')
  names.append(out)
 if not select:raise ValueError('出す列が1つもありません')
 sql=['SELECT '+', '.join(select),'FROM '+qi(meta[0]['table'])]
 for i,j in enumerate(r['joins']):
  right=meta[i+1];left=meta[i]
  on=[]
  for k in j['keys']:
   if not (k['left'] and k['right']):continue
   # 左のキーは「そこまでの鎖のどこか」に在る。名前で持っているので、後ろから探す。
   lt=next((m for m in reversed(meta[:i+1]) if k['left'] in m['columns']),left)
   on.append(f'{qi(lt["table"])}.{qi(k["left"])} = {qi(right["table"])}.{qi(k["right"])}')
  if not on:raise ValueError(f'{i+1}つ目のつなぎ目にキーがありません')
  sql.append(f'{JOIN_TYPE_SQL[j["type"]]} {qi(right["table"])} ON '+' AND '.join(on))
 if limit:sql.append(f'LIMIT {int(limit)}')
 return '\n'.join(sql),names

def join_stats(conn,recipe,meta):
 """つなぎ目ごとに、何件合ったのかを数える。

 結合の失敗は静かに起きる。キーを1つ間違えただけで0件になったり、何倍にも膨らんだり
 する。走らせる前にここを見せるのが、いちばん効く確かめ方。
 """
 r=normalize_recipe(recipe);out=[]
 for i,j in enumerate(r['joins']):
  left=meta[i];right=meta[i+1]
  keys=[k for k in j['keys'] if k['left'] and k['right']]
  if not keys:
   out.append({'index':i,'ok':False,'why':'キーが決まっていません'});continue
  lt=qi(left['table']);rt=qi(right['table'])
  on=' AND '.join(f'{lt}.{qi(k["left"])} = {rt}.{qi(k["right"])}' for k in keys)
  def one(sql):
   try:return int(conn.execute(sql).fetchone()[0])
   except Exception:return None
  both=one(f'SELECT COUNT(*) FROM {lt} WHERE EXISTS(SELECT 1 FROM {rt} WHERE {on})')
  lonly=one(f'SELECT COUNT(*) FROM {lt} WHERE NOT EXISTS(SELECT 1 FROM {rt} WHERE {on})')
  ronly=one(f'SELECT COUNT(*) FROM {rt} WHERE NOT EXISTS(SELECT 1 FROM {lt} WHERE {on})')
  paired=one(f'SELECT COUNT(*) FROM {lt} INNER JOIN {rt} ON {on}')
  note=''
  if both==0:note='キーが1組も一致していません。突き合わせる列が合っているか確かめてください'
  elif paired is not None and both is not None and paired>both:
   note=f'右に同じキーが複数あるため、行が{paired}件へ増えます（左は{both}件）'
  out.append({'index':i,'ok':bool(both),'type':j['type'],
              'left':left['name'],'right':right['name'],
              'left_rows':left['rows'],'right_rows':right['rows'],
              'both':both,'left_only':lonly,'right_only':ronly,'paired':paired,'why':note})
 return out

def run_recipe(recipe,reader,layouts=None,limit=None,source_limit=None):
 """結合を実行して (見出し, 本体, 内訳) を返す。"""
 conn,meta=load_sources(recipe,reader,layouts,source_limit)
 try:
  sql,names=build_sql(recipe,meta,limit)
  # 合わなかった側は NULL で返る。CSVへは空欄として書きたいので、ここで揃えておく。
  rows=[['' if v is None else v for v in r] for r in conn.execute(sql)]
  stats={'sources':[{k:m[k] for k in ('alias','name','rows','columns','format')} for m in meta],
         'joins':join_stats(conn,recipe,meta),'rows':len(rows),'columns':len(names),'sql':sql}
  return names,rows,stats
 finally:
  conn.close()

def preview_recipe(recipe,reader,layouts=None,lines=12,source_limit=2000):
 """下読み。組み立てたSQLと、つなぎ目ごとの一致もそのまま返す。

 source_limit を付けているのは、確かめるだけのために全部を読み込まないため。
 件数の内訳は「読み込んだぶんの中での話」なので、その旨も返す。
 """
 out={'ok':False,'headers':[],'rows':[],'stats':{},'notes':[]}
 bad=validate_recipe(recipe)
 if bad:
  out['error']='／'.join(bad);return out
 try:
  names,rows,stats=run_recipe(recipe,reader,layouts,limit=max(1,min(200,int(lines or 12))),source_limit=source_limit)
 except Exception as e:
  log.warning('JOIN_PREVIEW_FAILED error=%s',e)
  out['error']=str(e);return out
 out.update(ok=True,headers=names,rows=rows,stats=stats,
            partial=any(m['rows']>=source_limit for m in stats['sources']))
 if out['partial']:
  out['notes'].append(f'確かめのため、各ファイルの先頭{source_limit:,}行だけを読んでいます。'
                      '件数の内訳もその範囲での数字です')
 for j in stats['joins']:
  if j.get('why'):out['notes'].append(f'{j.get("left","")}→{j.get("right","")}: {j["why"]}')
 return out

def write_intermediate_csv(recipe,reader,dst,layouts=None,reject_zero=False,encoding='utf-8-sig'):
 """結合の結果を、変換に渡す中間CSVへ書き出す。ここから先はRNEと同じ道。"""
 dst=Path(dst)
 names,rows,stats=run_recipe(recipe,reader,layouts)
 if reject_zero and not rows:raise ValueError('結合の結果が0件のため出力を中止しました')
 dst.parent.mkdir(parents=True,exist_ok=True)
 with dst.open('w',encoding=encoding,newline='') as f:
  w=csv.writer(f,quoting=csv.QUOTE_MINIMAL);w.writerow(names);w.writerows(rows)
 log.info('JOIN_READ ファイル=%s 行=%s 列=%s 中間CSV=%s',
          [(m['alias'],m['name'],m['rows']) for m in stats['sources']],len(rows),len(names),dst)
 for j in stats['joins']:
  log.info('JOIN_MATCH %s→%s 種類=%s 両方=%s 左だけ=%s 右だけ=%s 結合後=%s %s',
           j.get('left'),j.get('right'),j.get('type'),j.get('both'),j.get('left_only'),
           j.get('right_only'),j.get('paired'),j.get('why') or '')
  if j.get('both')==0:
   log.warning('JOIN_NO_MATCH %s→%s キーが1組も一致していません',j.get('left'),j.get('right'))
 return len(rows),len(names),stats

# ---- キーの見当を付ける ----------------------------------------------------
# 300列あるファイルを2つ並べて「突き合わせる列を選んでください」は、あまりに酷い。
# 名前が似ているとも限らない（品番／品目コード／ITEM_CD は同じものを指す）。
# だから、名前ではなく中身で見当を付ける ―― 実データを少し読んで、値が実際に
# 重なっている列の組を探す。これは人が目でやると何時間もかかり、機械なら一瞬で済む。

# 総当たりはしない。左の値から「値→その値を持つ列」の索引を作り、右の値でその索引を
# 引く。300列×300列の90,000通りを1つずつ突き合わせるのではなく、読んだ値の数だけの
# 手間で全部の組が数えられる。
KEY_SAMPLE_ROWS=2000
KEY_MAX_DISTINCT=4000
KEY_MIN_SCORE=0.30

def _key_sets(headers,rows):
 """列ごとの「空でない値の集合」。全部同じ値の列と、空ばかりの列は外す。"""
 out={}
 for i,h in enumerate(headers or []):
  vals=set()
  for r in rows:
   if len(vals)>=KEY_MAX_DISTINCT:break
   v=r[i] if i<len(r) else ''
   v=('' if v is None else str(v)).strip()
   if v:vals.add(v)
  # 1種類しかない列はキーにならない（全部が一致してしまい、意味のない100%になる）。
  if len(vals)>=2:out[i]=vals
 return out

def _name_score(a,b):
 """名前の近さ。中身が同じくらい重なる組が複数あるときの、最後の決め手にだけ使う。"""
 a=str(a or '').strip().lower();b=str(b or '').strip().lower()
 if not a or not b:return 0.0
 if a==b:return 1.0
 if a in b or b in a:return 0.6
 sa=set(a);sb=set(b)
 return 0.3*len(sa&sb)/max(1,len(sa|sb))

def suggest_keys(left_headers,left_rows,right_headers,right_rows,limit=5):
 """実データで重なっている列の組を、強い順に返す。

 score は「少ないほうの種類数のうち、何割が相手にもあったか」。左に900種類、右に
 50,000種類あって900種類全部が見つかれば1.0 ―― 明細と台帳の関係はこの形になる。

 unique は「右で1件に決まるか」。ここが偽なら、繋いだ結果は行が増える。走らせて
 から気付くのでは遅いので、選ぶ前に言う。
 """
 lrows=list(left_rows or [])[:KEY_SAMPLE_ROWS]
 rrows=list(right_rows or [])[:KEY_SAMPLE_ROWS]
 lsets=_key_sets(left_headers,lrows);rsets=_key_sets(right_headers,rrows)
 if not lsets or not rsets:return []
 index={}
 for i,vals in lsets.items():
  for v in vals:index.setdefault(v,[]).append(i)
 hits={}
 for j,vals in rsets.items():
  for v in vals:
   for i in index.get(v,()):hits[(i,j)]=hits.get((i,j),0)+1
 out=[]
 for (i,j),n in hits.items():
  small=min(len(lsets[i]),len(rsets[j]))
  score=n/small if small else 0.0
  if score<KEY_MIN_SCORE:continue
  lname=left_headers[i];rname=right_headers[j]
  # 右が1行に決まるか（読んだぶんの中での話）。増えるなら増えると言う。
  rvals=[str(r[j]).strip() for r in rrows if j<len(r) and str(r[j] if r[j] is not None else '').strip()]
  unique=len(rvals)==len(set(rvals))
  out.append({'left':lname,'right':rname,'score':round(score,4),'matched':n,
              'left_distinct':len(lsets[i]),'right_distinct':len(rsets[j]),
              'unique':unique,'same_name':lname==rname,
              '_rank':(score,min(1.0,small/50),_name_score(lname,rname))})
 # 重なりの割合がいちばん、次に種類の多さ（2種類の区分より900種類の品番）、最後に名前。
 out.sort(key=lambda x:x['_rank'],reverse=True)
 seen_l=set();seen_r=set();picked=[]
 for x in out:
  # 同じ列を何度も勧めない。1つの列は1つの相手とだけ組ませて並べる。
  if x['left'] in seen_l or x['right'] in seen_r:continue
  seen_l.add(x['left']);seen_r.add(x['right'])
  x.pop('_rank');picked.append(x)
  if len(picked)>=max(1,int(limit or 5)):break
 return picked

# ---- 持ち出しと取り込み ----------------------------------------------------
def recipes_export(recipes):
 return {'kind':RECIPE_EXPORT_KIND,'version':RECIPE_EXPORT_VERSION,
         'exported_at':datetime.now().isoformat(timespec='seconds'),
         'count':len(recipes or []),
         'recipes':[{k:v for k,v in normalize_recipe(x).items() if k!='id'} for x in (recipes or [])]}

def recipes_import(payload):
 if isinstance(payload,(str,bytes)):
  try:payload=json.loads(payload if isinstance(payload,str) else payload.decode('utf-8-sig'))
  except Exception as e:return [],[f'JSONとして読めません: {e}']
 if isinstance(payload,list):payload={'kind':RECIPE_EXPORT_KIND,'recipes':payload}
 if not isinstance(payload,dict):return [],['結合マスタの持ち出しファイルではありません']
 if str(payload.get('kind') or '')!=RECIPE_EXPORT_KIND:
  return [],[f'結合マスタの持ち出しファイルではありません（kind={payload.get("kind") or "なし"}）']
 out=[];bad=[]
 for i,x in enumerate(payload.get('recipes') or [],1):
  r=normalize_recipe(x);r['id']=''
  problems=validate_recipe(r)
  if problems:bad.append(f'{i}件目「{r["name"] or "名前なし"}」: '+'／'.join(problems));continue
  out.append(r)
 if not out and not bad:bad.append('取り込める結合マスタが1件もありませんでした')
 return out,bad
