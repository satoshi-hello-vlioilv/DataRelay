"""固定長テキストの読み取り ―― 何文字目から何文字を、どの列にするか。

RNEはサーバーへ問い合わせて表を受け取る。こちらは手元のテキストファイルを、
決めた位置で切って表にする。そこから先（SQLite3・XLSX・CSV・TXTへの変換、公開、
控え、同時出力）はRNEとまったく同じ道を通る ―― 変換に渡す中間CSVの作り方だけが違う。

切り方は「読取マスタ」として名前を付けて保存し、対象から選んで使う。同じ形式の
ファイルが複数あるなら、マスタは1つで足りる。

app.py から分けてある。本体の状態は一切見ない（読むのはファイルと、渡された取り決めだけ）。
"""
import csv,json
from datetime import datetime
from pathlib import Path
from navi_log import log
# 型の名前は navi_output に置いてある（決める側と使う側で語彙を2つに割らないため）。
from navi_output import COLUMN_TYPES,COLUMN_TYPE_LABEL,COLUMN_TYPE_NOTE,normalize_column_type

# 文字コード。固定長のテキストは業務システムからの受け渡しが多く、既定はcp932。
TEXT_ENCODINGS=('cp932','utf-8-sig','utf-8','euc_jp','shift_jis','utf-16','latin-1')
TEXT_ENCODING_LABEL={'cp932':'Shift-JIS（cp932）','utf-8-sig':'UTF-8（BOM付き）','utf-8':'UTF-8',
                     'euc_jp':'EUC-JP','shift_jis':'Shift-JIS（標準）','utf-16':'UTF-16','latin-1':'Latin-1'}
# 位置の数え方。日本語が入る固定長は、たいていバイトで桁を決めている（全角1文字=2バイト）。
# どちらなのかはファイルを見ないと分からないので、選べるようにして、下読みで確かめてもらう。
TEXT_UNITS=('char','byte')
TEXT_UNIT_LABEL={'char':'文字数で数える','byte':'バイト数で数える（全角は2）'}
TRIM_MODES=('both','right','left','none')
TRIM_LABEL={'both':'前後の空白を取る','right':'後ろの空白だけ取る','left':'前の空白だけ取る','none':'そのまま'}
LAYOUT_EXPORT_KIND='symfonavi-text-layouts'
LAYOUT_EXPORT_VERSION=1
# 列の数に、こちらの都合で上限は置かない。固定長のレイアウトは数百項目になることが
# ふつうにあり、200で黙って切っていたため、200項目を超えるマスタは登録した時点で
# 後ろが消えていた（実測: 製造マスター REC SIZE 1395 が 1058バイト/200列で保存）。
# 実際に効く上限は「どの形式で出すか」の側にある（navi_output.output_column_limit）。
# ここに残すのは、壊れた取り込みで際限なく増えないための歯止めだけで、超えたら断る。
MAX_COLUMNS=4096
# 日付・日時の読み方。書式は「並び」だけを書いてもらい、区切り文字は何でも読み飛ばす
# （YYYYMMDD も YYYY/MM/DD も YYYY年MM月DD日 も、同じ仕組みで読める）。
STAMP_TOKENS=('YYYY','YY','MM','DD','HH','MI','NN','SS')
# MM は月にも分にも使われる。世の中の仕様書は YYYYMMDDHHMMSS と書くのがふつうなので、
# 「時（HH）より後ろの MM は分」として読む。MI・NN と書いてあれば、位置によらず分。
STAMP_ROLE={'YYYY':'Y','YY':'y','MM':'M','DD':'D','HH':'h','MI':'m','NN':'m','SS':'s'}
DATE_FORMAT_DEFAULT='YYYYMMDD'
DATETIME_FORMAT_DEFAULT='YYYYMMDDHHMMSS'
# よく使う書式。画面の候補に出すだけで、手で書いた書式も受け付ける。
STAMP_FORMAT_SAMPLES=('YYYYMMDD','YYMMDD','YYYY/MM/DD','YYYY-MM-DD','YYYY年MM月DD日',
                      'YYYYMMDDHHMMSS','YYYYMMDDHHMM','YYYY/MM/DD HH:MM:SS')
# 2桁の年の読み替え。69以下は2000年代、70以上は1900年代（広く使われている区切り）。
CENTURY_PIVOT=69
MAX_SCALE=9

def _int(v,default=0):
 try:return int(str(v).strip())
 except Exception:return default

def normalize_column(c,index=0):
 """1つの列の取り決めを整える。終了位置で書かれていれば長さへ直す。

 開始位置は1始まり（画面でもテキストエディタでも1文字目は1）。長さと終了位置の
 どちらで書いても構わないが、持ち方は「開始＋長さ」の1通りに寄せる ―― 2通りで
 持つと、片方だけ直したときに食い違う。

 型は既定が文字。これまでのマスタには型が入っていないので、読み込んだ時点で
 全部「文字」になり、これまでとまったく同じ結果になる。
 """
 c=dict(c or {})
 start=max(1,_int(c.get('start'),1))
 length=_int(c.get('length'),0)
 if length<1:
  end=_int(c.get('end'),0)
  length=(end-start+1) if end>=start else 0
 t=normalize_column_type(c.get('type'))
 fmt=str(c.get('format') or '').strip()
 if t in ('date','datetime') and not fmt:
  fmt=DATE_FORMAT_DEFAULT if t=='date' else DATETIME_FORMAT_DEFAULT
 if t not in ('date','datetime'):fmt=''
 return {'name':str(c.get('name') or '').strip() or f'列{index+1}',
         'start':start,'length':max(0,length),'end':start+max(0,length)-1,
         'type':t,'scale':max(0,min(MAX_SCALE,_int(c.get('scale'),0))) if t=='real' else 0,
         'format':fmt,
         'note':str(c.get('note') or '').strip()}

# ---- 型のあてはめ ----------------------------------------------------------
# ここでやるのは「読んだ文字を、決めた型の書き方へ揃える」ところまで。中間CSVは
# 文字で受け渡すので、返すのも文字。実際に型として持たせるのは書き出す側
# （navi_output.sqlite_column_type ほか）で、その2つを1本の取り決めで繋いでいる。
def _stamp_plan(pattern):
 """書式を「どの位置から何文字を、何として読むか」の並びへ直す。

 YYYY/YY/MM/DD/HH/MI(NN)/SS を順に拾い、それ以外の文字は区切りとして読み飛ばす。
 こうしておくと、区切りのある書式も無い書式も同じ道で読める。
 返すのは (役割, 桁数) の並び。役割は Y y M D h m s と、区切りの None。"""
 plan=[];i=0;p=str(pattern or '');seen_hour=False
 while i<len(p):
  for tok in STAMP_TOKENS:
   if p.startswith(tok,i):
    role=STAMP_ROLE[tok]
    # 時より後ろの MM は分。YYYYMMDDHHMMSS をそのまま書けるようにするため。
    if tok=='MM' and seen_hour:role='m'
    if role=='h':seen_hour=True
    plan.append((role,len(tok)));i+=len(tok);break
  else:
   plan.append((None,1));i+=1
 return plan

def _parse_stamp(value,pattern,want_time):
 """書式どおりに読めたら (年,月,日,時,分,秒)。読めなければ None。"""
 s=str(value or '').strip()
 if not s:return None
 got={};pos=0
 for role,n in _stamp_plan(pattern):
  if role is None:
   pos+=1;continue                     # 区切りは中身を見ない（/ でも - でも 年 でもよい）
  chunk=s[pos:pos+n];pos+=n
  if len(chunk)!=n or not chunk.isdigit():return None
  got[role]=int(chunk)
 if pos<len(s.rstrip()):return None     # 余りがあるなら書式が合っていない
 y=got.get('Y')
 if y is None and 'y' in got:y=(2000+got['y']) if got['y']<=CENTURY_PIVOT else (1900+got['y'])
 mo=got.get('M',1);d=got.get('D',1);h=got.get('h',0);mi=got.get('m',0);se=got.get('s',0)
 if y is None:return None
 try:datetime(y,mo,d,h,mi,se)           # 20260231 のような日付はここで落ちる
 except ValueError:return None
 return (y,mo,d,h,mi,se) if want_time else (y,mo,d,0,0,0)

def _to_number(text,scale,integer_only):
 """数字として読む。読めなければ None。

 前の0・桁区切りのカンマ・前後の空白は落とす。末尾の符号（123-）も読む ――
 基幹システムからの固定長では、負の数をこう書いてくることがある。"""
 s=str(text or '').strip().replace(',','').replace('　','')
 if not s:return ''
 sign=''
 if s[-1] in '+-':sign='-' if s[-1]=='-' else '';s=s[:-1].strip()
 if s[:1] in '+-':
  sign='-' if s[0]=='-' else sign;s=s[1:]
 if not s:return None
 if integer_only:
  if not s.isdigit():return None
  return sign+str(int(s))
 if s.isdigit():
  # 小数点が書かれていない。桁を決めてあれば、その桁数ぶんを小数として入れる
  # （0012345 で桁2 なら 123.45）。決めていなければ整数のまま。
  # ここで float を通さないのは、桁の多い値が指数表記や丸めになるのを避けるため。
  if scale:
   s=s.rjust(scale+1,'0');return sign+str(int(s[:-scale]))+'.'+s[-scale:]
  return sign+str(int(s))
 head,dot,tail=s.partition('.')
 if dot and (head=='' or head.isdigit()) and (tail=='' or tail.isdigit()):
  # 整数部の前の0だけ落とす。小数部は書いてあるとおりに残す（0012.50 → 12.50）。
  # 末尾の0を落とすと「小数第2位まで」という情報が消えてしまう。
  return sign+str(int(head or '0'))+'.'+(tail or '0')
 try:float(s)
 except ValueError:return None
 return sign+s

def _converter(col):
 """列1本ぶんの変換。文字（既定）なら None を返し、呼ぶ側で何もしない。"""
 t=col.get('type') or 'text'
 if t=='text':return None
 if t=='integer':return lambda v:_to_number(v,0,True)
 if t=='numeric':return lambda v:_to_number(v,0,False)
 if t=='real':
  scale=int(col.get('scale') or 0)
  return lambda v:_to_number(v,scale,False)
 want_time=(t=='datetime');pattern=col.get('format') or (DATETIME_FORMAT_DEFAULT if want_time else DATE_FORMAT_DEFAULT)
 def stamp(v):
  if not str(v or '').strip():return ''
  got=_parse_stamp(v,pattern,want_time)
  if not got:return None
  y,mo,d,h,mi,se=got
  return f'{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{se:02d}' if want_time else f'{y:04d}-{mo:02d}-{d:02d}'
 return stamp

def layout_converters(layout):
 """列ごとの変換の並び。1つも型を決めていなければ空（そのぶん何もしない）。"""
 cols=layout['columns'] if isinstance(layout,dict) and 'columns' in layout else normalize_layout(layout)['columns']
 fns=[_converter(c) for c in cols]
 return fns if any(fns) else []

def layout_column_types(layout):
 """列名 → 型。書き出す側へ渡すのはこれ（並び順ではなく名前で渡す）。"""
 l=layout if isinstance(layout,dict) and 'columns' in layout else normalize_layout(layout)
 return {c['name']:c.get('type') or 'text' for c in l['columns']}

def normalize_layout(d):
 """読取マスタ1件を整える。壊れた値は既定へ倒す（保存を断るのは validate_layout）。"""
 d=dict(d or {})
 enc=str(d.get('encoding') or '').strip().lower().replace('-','_')
 enc={'utf_8':'utf-8','utf_8_sig':'utf-8-sig','sjis':'cp932','ms932':'cp932','utf_16':'utf-16',
      'latin_1':'latin-1'}.get(enc,str(d.get('encoding') or '').strip().lower())
 if enc not in TEXT_ENCODINGS:enc='cp932'
 unit=str(d.get('unit') or '').strip().lower()
 if unit not in TEXT_UNITS:unit='byte'
 trim=str(d.get('trim') or '').strip().lower()
 if trim not in TRIM_MODES:trim='both'
 cols=[normalize_column(c,i) for i,c in enumerate(d.get('columns') or [])]
 return {'id':str(d.get('id') or '').strip(),
         'name':str(d.get('name') or '').strip(),
         'description':str(d.get('description') or '').strip(),
         'encoding':enc,'unit':unit,'trim':trim,
         'skip_head':max(0,min(999,_int(d.get('skip_head'),0))),
         'skip_tail':max(0,min(999,_int(d.get('skip_tail'),0))),
         'skip_blank':bool(d.get('skip_blank',True)),
         'header_row':bool(d.get('header_row',False)),
         'columns':cols,
         'sample_path':str(d.get('sample_path') or '').strip(),
         'updated_at':str(d.get('updated_at') or '')}

def validate_layout(layout):
 """このままでは使えない、という理由。空なら保存してよい。

 直せるものは normalize が直す。ここに挙げるのは、直すと利用者の意図を
 勝手に決めてしまうもの（名前が無い・列が無い・同じ名前がある）だけ。
 """
 l=normalize_layout(layout);bad=[]
 if not l['name']:bad.append('マスタ名を入れてください')
 if not l['columns']:bad.append('列を1つ以上決めてください')
 # 切って黙って通すのではなく、断って気づけるようにする。
 if len(l['columns'])>MAX_COLUMNS:
  bad.append(f'列が多すぎます（{len(l["columns"]):,}本）。{MAX_COLUMNS:,}本までにしてください')
 seen={}
 for i,c in enumerate(l['columns'],1):
  if c['length']<1:bad.append(f'{i}番目「{c["name"]}」の長さが0です。長さか終了位置を入れてください')
  # 日付・日時は書式で読む。年が無い書式では、いつの日付か決まらない。
  if c['type'] in ('date','datetime'):
   plan=[t for t,_ in _stamp_plan(c['format']) if t]
   if not plan:bad.append(f'{i}番目「{c["name"]}」の書式が空です（例 {DATE_FORMAT_DEFAULT}）')
   elif 'Y' not in plan and 'y' not in plan:
    bad.append(f'{i}番目「{c["name"]}」の書式に年がありません（YYYY か YY を入れてください）: {c["format"]}')
   elif c['type']=='datetime' and not [t for t in plan if t in ('h','m','s')]:
    bad.append(f'{i}番目「{c["name"]}」は日時ですが、書式に時刻がありません（HH・MM・SS）: {c["format"]}')
   else:
    need=sum(n for t,n in _stamp_plan(c['format']))
    if need>c['length']:
     bad.append(f'{i}番目「{c["name"]}」の書式は{need}桁必要ですが、切り出す長さが{c["length"]}しかありません')
  seen[c['name']]=seen.get(c['name'],0)+1
 dupes=[k for k,v in seen.items() if v>1]
 # 同じ名前の列は、SQLite3のテーブルもXLSXの見出しも作れない（分割でも同じ理由で断っている）。
 if dupes:bad.append('同じ名前の列があります（'+'、'.join(dupes[:5])+'）。列名は重ならないようにしてください')
 return bad

def layout_width(layout):
 """この取り決めが必要とする長さ。1行がこれより短ければ、足りない列は空になる。"""
 cols=normalize_layout(layout)['columns']
 return max([c['end'] for c in cols] or [0])

def layout_overlaps(layout):
 """重なっている列の組。使えないわけではない（日付の全体と年だけ、など）ので、知らせるだけ。"""
 cols=sorted(normalize_layout(layout)['columns'],key=lambda c:(c['start'],c['end']))
 out=[]
 for a,b in zip(cols,cols[1:]):
  if b['start']<=a['end']:out.append((a['name'],b['name']))
 return out

def layout_gaps(layout):
 """どの列にも入らない範囲。読み飛ばしているだけなので、これも知らせるだけ。"""
 cols=sorted(normalize_layout(layout)['columns'],key=lambda c:(c['start'],c['end']))
 out=[];pos=1
 for c in cols:
  if c['start']>pos:out.append((pos,c['start']-1))
  pos=max(pos,c['end']+1)
 return out

def _trim(value,mode):
 if mode=='both':return value.strip()
 if mode=='right':return value.rstrip()
 if mode=='left':return value.lstrip()
 return value

def _slice_char(line,cols,trim):
 return [_trim(line[c['start']-1:c['end']],trim) for c in cols]

def _slice_byte(raw,cols,encoding,trim,stat):
 out=[]
 for c in cols:
  chunk=raw[c['start']-1:c['end']]
  try:
   out.append(_trim(chunk.decode(encoding),trim))
  except UnicodeDecodeError:
   # 桁の切れ目が全角文字の途中に来ている。位置か単位の取り決めが合っていない印。
   stat['broken_cells']+=1
   out.append(_trim(chunk.decode(encoding,errors='replace'),trim))
 return out

def _read_lines(path,encoding,unit):
 """1行ずつ返す。バイトで数えるときは、生のバイト列のまま返す。

 改行だけは先に落とす。CR/LF/CRLFのどれでも同じに扱う（受け渡しの経路で変わるため）。
 """
 path=Path(path)
 if unit=='byte':
  with path.open('rb') as f:
   for raw in f:
    yield raw.rstrip(b'\r\n')
 else:
  with path.open('r',encoding=encoding,errors='replace',newline='') as f:
   for line in f:
    yield line.rstrip('\r\n')

def read_text_rows(path,layout,limit=None,keep_raw=False):
 """固定長テキストを表にする。(見出し, 本体, 内訳) を返す。

 内訳（stat）には、読んだ行数・飛ばした行数・短かった行数・切れ目が文字の途中に
 来た数を入れる。これが分かると「位置がずれている」「単位が違う」を後から追える。
 """
 l=normalize_layout(layout);cols=l['columns']
 if not cols:raise ValueError('読取マスタに列がありません')
 width=layout_width(l)
 headers=[c['name'] for c in cols]
 body=[];raws=[]
 stat={'lines':0,'rows':0,'skipped_blank':0,'skipped_head':0,'skipped_tail':0,
       'short_rows':0,'broken_cells':0,'width':width,'unit':l['unit'],'encoding':l['encoding'],
       'types':layout_column_types(l),'type_errors':0,'type_samples':{}}
 # 型を1つも決めていなければ、ここは丸ごと通らない（これまでとまったく同じ道）。
 convs=layout_converters(l)
 def typed(values):
  for i,fn in enumerate(convs):
   if fn is None:continue
   got=fn(values[i])
   if got is None:
    # 決めた型に読めない値。黙って通すと、出来上がったファイルの型が嘘になる。
    # 空にしたうえで数え、どの列のどんな値だったかを1つ覚えておく。
    stat['type_errors']+=1
    stat['type_samples'].setdefault(headers[i],values[i])
    values[i]=''
   else:values[i]=got
  return values
 tail=max(0,l['skip_tail'])
 hold=[]                                   # 末尾を捨てるぶんだけ手元に留める
 blank=(b'' if l['unit']=='byte' else '')
 def take(line):
  if l['unit']=='byte':
   if len(line)<width:stat['short_rows']+=1
   out=_slice_byte(line,cols,l['encoding'],l['trim'],stat)
  else:
   if len(line)<width:stat['short_rows']+=1
   out=_slice_char(line,cols,l['trim'])
  return typed(out) if convs else out
 header_seen=[False]
 for line in _read_lines(path,l['encoding'],l['unit']):
  stat['lines']+=1
  if stat['lines']<=l['skip_head']:
   stat['skipped_head']+=1;continue
  if l['skip_blank'] and line.strip()==blank:
   stat['skipped_blank']+=1;continue
  if l['header_row'] and not header_seen[0]:
   # 1行目が見出しの行。列名はマスタ側の名前を使う（ファイル側の表記ゆれに引きずられない）。
   header_seen[0]=True;stat['skipped_head']+=1;continue
  hold.append(line)
  if len(hold)<=tail:continue
  use=hold.pop(0)
  body.append(take(use))
  if keep_raw:raws.append(use.decode(l['encoding'],errors='replace') if l['unit']=='byte' else use)
  stat['rows']+=1
  if limit and stat['rows']>=int(limit):break
 stat['skipped_tail']=len(hold) if not limit else 0
 if keep_raw:return headers,body,stat,raws
 return headers,body,stat

def preview_text(path,layout,lines=12):
 """下読み。生の行と、切り出した結果を並べて返す。

 位置が合っているかどうかは、数字を見比べるより、切った結果を見るほうが早い。
 """
 p=Path(path)
 out={'ok':False,'path':str(p),'headers':[],'rows':[],'raw':[],'stat':{},
      'overlaps':[[a,b] for a,b in layout_overlaps(layout)],
      'gaps':[[a,b] for a,b in layout_gaps(layout)],'notes':[]}
 bad=validate_layout(layout)
 if bad:
  out['error']='／'.join(bad);return out
 if not p.is_file():
  out['error']=f'ファイルがありません: {p}';return out
 try:
  headers,body,stat,raws=read_text_rows(p,layout,limit=max(1,min(100,int(lines or 12))),keep_raw=True)
 except Exception as e:
  log.warning('TEXT_PREVIEW_FAILED path=%s error=%s',p,e)
  out['error']=f'読み取れませんでした: {e}';return out
 out.update(ok=True,headers=headers,rows=body,raw=raws,stat=stat,size=p.stat().st_size,
            types=[c['type'] for c in normalize_layout(layout)['columns']])
 if stat['short_rows']:
  out['notes'].append(f'{stat["short_rows"]}行が取り決めより短く、足りない列は空になりました'
                      f'（この取り決めは{stat["width"]}{"バイト" if stat["unit"]=="byte" else "文字"}必要です）')
 if stat['broken_cells']:
  out['notes'].append(f'{stat["broken_cells"]}か所で、切れ目が文字の途中に来ました。'
                      '位置の数え方（文字／バイト）か、開始位置が合っていない可能性があります')
 if stat['type_errors']:
  # どの列のどんな値だったかまで出す。「型が合いません」だけでは直しようがない。
  ex='、'.join(f'{k}「{v}」' for k,v in list(stat['type_samples'].items())[:3])
  out['notes'].append(f'{stat["type_errors"]}か所が、決めた型に読めませんでした（空にしています）: {ex}。'
                      '型や書式・小数桁、または開始位置を確かめてください')
 if out['overlaps']:
  out['notes'].append('重なっている列があります: '+'、'.join(f'{a}↔{b}' for a,b in out['overlaps'][:3]))
 return out

def write_intermediate_csv(path,layout,dst,reject_zero=False,encoding='utf-8-sig'):
 """固定長テキストを、変換に渡す中間CSVへ書き出す。

 ここから先はRNEとまったく同じ道（read_extract → export_data → 公開）。
 中間CSVの文字コードだけは、読み手へ別に伝える（既定の推測順ではcp932が先に来るため）。
 """
 p=Path(path);dst=Path(dst)
 if not p.is_file():raise FileNotFoundError(f'テキストファイルがありません: {p}')
 headers,body,stat=read_text_rows(p,layout)
 if reject_zero and not body:raise ValueError('読み取り0件のため出力を中止しました')
 dst.parent.mkdir(parents=True,exist_ok=True)
 with dst.open('w',encoding=encoding,newline='') as f:
  w=csv.writer(f,quoting=csv.QUOTE_MINIMAL);w.writerow(headers);w.writerows(body)
 log.info('TEXT_READ file=%s size=%s encoding=%s unit=%s width=%s 行=%s（読んだ行%s 空%s 見出し・先頭%s 末尾%s）'
          ' 短い行=%s 文字の途中で切れた=%s 列=%s 中間CSV=%s',
          p,p.stat().st_size,stat['encoding'],stat['unit'],stat['width'],stat['rows'],stat['lines'],
          stat['skipped_blank'],stat['skipped_head'],stat['skipped_tail'],stat['short_rows'],
          stat['broken_cells'],len(headers),dst)
 if stat['short_rows']:
  log.warning('TEXT_SHORT_ROWS file=%s 行=%s が%s%sに足りません。足りない列は空になります',
              p,stat['short_rows'],stat['width'],'バイト' if stat['unit']=='byte' else '文字')
 if stat['broken_cells']:
  log.warning('TEXT_BROKEN_CELLS file=%s 箇所=%s 切れ目が文字の途中に来ています。'
              '位置の数え方（文字／バイト）か開始位置を確かめてください',p,stat['broken_cells'])
 if stat['type_errors']:
  log.warning('TEXT_TYPE_ERRORS file=%s 箇所=%s 決めた型に読めない値を空にしました 例=%s',
              p,stat['type_errors'],'、'.join(f'{k}「{v}」' for k,v in list(stat['type_samples'].items())[:3]))
 typed={k:v for k,v in stat['types'].items() if v!='text'}
 if typed:log.info('TEXT_COLUMN_TYPES file=%s 型を決めた列=%s 内訳=%s',p,len(typed),typed)
 return len(body),len(headers),stat

# ---- 持ち出しと取り込み ----------------------------------------------------
# 同じ読み方を別のPCでも使えるようにする。中身は素のJSONで、開けば読める形にする
# （読めない形で持ち出すと、アプリが動かないときに手も足も出なくなる）。
def layouts_export(layouts):
 return {'kind':LAYOUT_EXPORT_KIND,'version':LAYOUT_EXPORT_VERSION,
         'exported_at':datetime.now().isoformat(timespec='seconds'),
         'count':len(layouts or []),
         'layouts':[{k:v for k,v in normalize_layout(x).items() if k!='id'} for x in (layouts or [])]}

def layouts_import(payload):
 """取り込む。読めたものと、読めなかった理由を返す。

 中身が違うファイルを黙って取り込むと、マスタが壊れる。印（kind）を必ず確かめる。
 """
 if isinstance(payload,(str,bytes)):
  try:payload=json.loads(payload if isinstance(payload,str) else payload.decode('utf-8-sig'))
  except Exception as e:return [],[f'JSONとして読めません: {e}']
 if isinstance(payload,list):payload={'kind':LAYOUT_EXPORT_KIND,'layouts':payload}
 if not isinstance(payload,dict):return [],['読取マスタの持ち出しファイルではありません']
 if str(payload.get('kind') or '')!=LAYOUT_EXPORT_KIND:
  return [],[f'読取マスタの持ち出しファイルではありません（kind={payload.get("kind") or "なし"}）']
 out=[];bad=[]
 for i,x in enumerate(payload.get('layouts') or [],1):
  l=normalize_layout(x);l['id']=''
  problems=validate_layout(l)
  if problems:bad.append(f'{i}件目「{l["name"] or "名前なし"}」: '+'／'.join(problems));continue
  out.append(l)
 if not out and not bad:bad.append('取り込めるマスタが1件もありませんでした')
 return out,bad
