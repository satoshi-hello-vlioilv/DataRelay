"""テキストの読み取り ―― 何文字目から何文字を（固定長）、または区切りの何番目を（区切り）、どの列にするか。

RNEはサーバーへ問い合わせて表を受け取る。こちらは手元のテキストファイルを、
決めた位置で切って表にする。そこから先（SQLite3・XLSX・CSV・TXTへの変換、公開、
控え、同時出力）はRNEとまったく同じ道を通る ―― 変換に渡す中間CSVの作り方だけが違う。

切り方は2通り（2.8.0）。固定長は「開始位置と長さ」で切り、区切りは「区切り（カンマ・タブ・
任意の文字・正規表現）で分けた何番目の項目か」で取る。どちらも列の型・前後の空白・読み飛ばしは同じ道を通る
（違うのは1行を値の並びへ分けるところだけ）。

切り方は「読取マスタ」として名前を付けて保存し、対象から選んで使う。同じ形式の
ファイルが複数あるなら、マスタは1つで足りる。

app.py から分けてある。本体の状態は一切見ない（読むのはファイルと、渡された取り決めだけ）。
"""
import csv,json,re
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
# 読み方。固定長（位置で切る）と区切り（記号や決まりで分ける）。これまでのマスタは mode を持たないので固定長。
TEXT_MODES=('fixed','delimited')
TEXT_MODE_LABEL={'fixed':'固定長（位置で切る）','delimited':'区切り（記号で分ける）'}
# 区切り。よく使う記号は名前で選べるようにし、それ以外は「文字を指定」か「正規表現（決まり）」で書いてもらう。
DELIMITERS=('comma','tab','semicolon','pipe','space','custom','regex')
DELIMITER_LABEL={'comma':'カンマ（,）','tab':'タブ','semicolon':'セミコロン（;）','pipe':'縦線（|）',
                 'space':'空白','custom':'文字を指定','regex':'正規表現（決まりで分ける）'}
DELIMITER_CHAR={'comma':',','tab':'\t','semicolon':';','pipe':'|','space':' '}
# 囲み文字。値の中に区切りが入るとき、"…" で囲んで書くのが CSV の決まり（"" は " 1文字）。
QUOTES=('double','single','none')
QUOTE_LABEL={'double':'ダブルクォート（"）','single':'シングルクォート（\'）','none':'囲みなし'}
QUOTE_CHAR={'double':'"','single':"'",'none':''}
# 囲みの中の改行で1件が何行にも続くとき、どこまでを1件として待つか。閉じ忘れの囲みで
# ファイルの残り全部を1件にしてしまわないための歯止め。
MAX_RECORD_LINES=1000
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

def normalize_column(c,index=0,mode='fixed'):
 """1つの列の取り決めを整える。終了位置で書かれていれば長さへ直す。

 区切りでは、位置の代わりに「何番目の項目か」（field。1始まり）を持つ。書いていなければ
 並び順（1列目は1番目）。開始・長さは使わないが、固定長へ戻したときのために消さずに持つ。

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
         'field':max(1,_int(c.get('field'),index+1)) if mode=='delimited' else max(0,_int(c.get('field'),0)),
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
 mode=str(d.get('mode') or '').strip().lower()
 if mode not in TEXT_MODES:mode='fixed'
 delim=str(d.get('delimiter') or '').strip().lower()
 if delim not in DELIMITERS:delim='comma'
 # 区切りの文字は前後の空白も意味を持つ（「 / 」で分けたい、がある）。正規表現も同じ。だから削らない。
 dtext=str(d.get('delimiter_text') or '') if delim in ('custom','regex') else ''
 quote=str(d.get('quote') or '').strip().lower()
 if quote not in QUOTES:quote='double'
 cols=[normalize_column(c,i,mode) for i,c in enumerate(d.get('columns') or [])]
 return {'id':str(d.get('id') or '').strip(),
         'name':str(d.get('name') or '').strip(),
         'description':str(d.get('description') or '').strip(),
         'mode':mode,'delimiter':delim,'delimiter_text':dtext,'quote':quote,
         'collapse':bool(d.get('collapse',False)),
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
 if l['mode']=='delimited':
  if l['delimiter'] in ('custom','regex') and not l['delimiter_text']:
   bad.append('区切りの文字を入れてください' if l['delimiter']=='custom' else '区切りの決まり（正規表現）を入れてください')
  elif l['delimiter']=='regex':
   try:
    if re.compile(l['delimiter_text']).search(''):bad.append('区切りの決まり（正規表現）が空の文字にも当たります。1文字以上に当たる形にしてください')
   except re.error as e:bad.append(f'区切りの決まり（正規表現）が読めません: {e}')
 seen={}
 for i,c in enumerate(l['columns'],1):
  if l['mode']=='fixed' and c['length']<1:bad.append(f'{i}番目「{c["name"]}」の長さが0です。長さか終了位置を入れてください')
  # 日付・日時は書式で読む。年が無い書式では、いつの日付か決まらない。
  if c['type'] in ('date','datetime'):
   plan=[t for t,_ in _stamp_plan(c['format']) if t]
   if not plan:bad.append(f'{i}番目「{c["name"]}」の書式が空です（例 {DATE_FORMAT_DEFAULT}）')
   elif 'Y' not in plan and 'y' not in plan:
    bad.append(f'{i}番目「{c["name"]}」の書式に年がありません（YYYY か YY を入れてください）: {c["format"]}')
   elif c['type']=='datetime' and not [t for t in plan if t in ('h','m','s')]:
    bad.append(f'{i}番目「{c["name"]}」は日時ですが、書式に時刻がありません（HH・MM・SS）: {c["format"]}')
   elif l['mode']=='fixed':
    need=sum(n for t,n in _stamp_plan(c['format']))
    if need>c['length']:
     bad.append(f'{i}番目「{c["name"]}」の書式は{need}桁必要ですが、切り出す長さが{c["length"]}しかありません')
  seen[c['name']]=seen.get(c['name'],0)+1
 dupes=[k for k,v in seen.items() if v>1]
 # 同じ名前の列は、SQLite3のテーブルもXLSXの見出しも作れない（分割でも同じ理由で断っている）。
 if dupes:bad.append('同じ名前の列があります（'+'、'.join(dupes[:5])+'）。列名は重ならないようにしてください')
 return bad

def _span(c,mode):
 """列が占める範囲 (始め, 終わり)。固定長は文字・バイトの位置、区切りは項目の番号。"""
 return (c['field'],c['field']) if mode=='delimited' else (c['start'],c['end'])

def layout_width(layout):
 """この取り決めが必要とする長さ。1行がこれより短ければ、足りない列は空になる。
 区切りでは、要る項目の数（いちばん後ろの項目の番号）。"""
 l=normalize_layout(layout)
 return max([_span(c,l['mode'])[1] for c in l['columns']] or [0])

def delimiter_label(layout):
 """区切りの呼び名（画面・記録の言葉）。文字を指定・正規表現は、書いた中身まで見せる。"""
 l=normalize_layout(layout)
 if l['delimiter']=='custom':return f'「{l["delimiter_text"]}」'
 if l['delimiter']=='regex':return f'正規表現 {l["delimiter_text"]}'
 return DELIMITER_LABEL[l['delimiter']].split('（')[0]

def layout_shape(layout):
 """マスタの形を1行で言う（一覧・対象の登録・記録で同じ言い方にするため、ここ1か所で作る）。
 固定長 → 「12列 / 66バイト」、区切り → 「12列 / カンマ区切り」。"""
 l=normalize_layout(layout);n=len(l['columns'])
 if l['mode']=='delimited':return f'{n}列 / {delimiter_label(l)}区切り'
 return f'{n}列 / {layout_width(l)}{"バイト" if l["unit"]=="byte" else "文字"}'

def layout_overlaps(layout):
 """重なっている列の組。使えないわけではない（日付の全体と年だけ、など）ので、知らせるだけ。
 区切りでは、同じ項目を2つの列で取っている組。"""
 l=normalize_layout(layout)
 cols=sorted(l['columns'],key=lambda c:_span(c,l['mode']))
 out=[]
 for a,b in zip(cols,cols[1:]):
  if _span(b,l['mode'])[0]<=_span(a,l['mode'])[1]:out.append((a['name'],b['name']))
 return out

def layout_gaps(layout):
 """どの列にも入らない範囲。読み飛ばしているだけなので、これも知らせるだけ。
 区切りでは、取っていない項目の番号の範囲。"""
 l=normalize_layout(layout)
 cols=sorted(l['columns'],key=lambda c:_span(c,l['mode']))
 cols=[{'start':_span(c,l['mode'])[0],'end':_span(c,l['mode'])[1]} for c in cols]
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

# ---- 区切り: 1件を値の並びへ分ける ------------------------------------------
def splitter(layout):
 """1件（文字列）を値の並びへ分ける関数を返す。区切りの種類ごとの違いは、ここだけに閉じ込める。

 - 正規表現: 決まりに当たったところで分ける（囲みは見ない。決まりで書く人は囲みも決まりで書く）
 - 記号・文字: 囲み文字の中の区切りは値の一部。"" は " 1文字。囲みは値の頭にあるときだけ囲み（途中の " は文字）
 - 連続をまとめる: 続いた区切りを1つとみなし、空の項目を作らない（空白で桁をそろえた表など）
 返す関数には .open（囲みが閉じないまま終わったか）を付ける。囲みの中の改行で1件が続くのを、
 分けるのと同じ読み方で見分けるため（数え方を2つ持つと、片方だけ直したときに食い違う）。
 """
 l=normalize_layout(layout);collapse=l['collapse']
 drop=(lambda xs:[x for x in xs if x!=''] or ['']) if collapse else (lambda xs:xs)
 if l['delimiter']=='regex':
  rx=re.compile(l['delimiter_text'])
  split=lambda s:drop(rx.split(s))
  split.open=lambda s:False
  return split
 sep=l['delimiter_text'] if l['delimiter']=='custom' else DELIMITER_CHAR[l['delimiter']]
 q=QUOTE_CHAR[l['quote']];n=len(sep)
 if not q:
  split=lambda s:drop(s.split(sep))
  split.open=lambda s:False
  return split
 def scan(s):
  out=[];buf=[];i=0;L=len(s);start=True;opened=False
  while True:
   if i>=L:out.append(''.join(buf));break
   if start and s[i]==q:
    # 囲まれた値。閉じの囲みまで読む。閉じの後ろから区切りまでの文字は、そのまま値に足す。
    i+=1;opened=True
    while i<L:
     if s[i]==q:
      if i+1<L and s[i+1]==q:buf.append(q);i+=2;continue
      i+=1;opened=False;break
     buf.append(s[i]);i+=1
    start=False;continue
   if s.startswith(sep,i):
    out.append(''.join(buf));buf=[];i+=n;start=True
    continue
   buf.append(s[i]);i+=1;start=False
  return drop(out),opened
 split=lambda s:scan(s)[0]
 split.open=lambda s:scan(s)[1]
 return split

def _read_records(path,layout):
 """区切りの1件ずつ。囲みの中の改行は値の一部なので、閉じるまで次の行を足して1件にする。
 返すのは (件の文字列, 使った物理行の数)。閉じ忘れは MAX_RECORD_LINES 行で打ち切る。"""
 l=normalize_layout(layout);still_open=splitter(l).open
 hold=[]
 with Path(path).open('r',encoding=l['encoding'],errors='replace',newline='') as f:
  for line in f:
   line=line.rstrip('\r\n')
   if hold:
    hold.append(line)
    rec='\n'.join(hold)
    if still_open(rec) and len(hold)<MAX_RECORD_LINES:continue
    yield rec,len(hold);hold=[];continue
   if still_open(line):hold=[line];continue
   yield line,1
 if hold:yield '\n'.join(hold),len(hold)

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

# 読めない記号だけの行（2.10.1）。元のシステムによっては、最後の改行のあとに「ファイルの終わり」の印
# （Ctrl+Z ＝ 0x1A）や NUL を付けて書き出す。空行ではないので「空行を飛ばす」では外れず、出力の最後に
# 「□」だけの行ができていた。タブ・改行以外の制御文字と DEL、読めなかった文字（U+FFFD）だけでできた行は、
# どんな取り決めでもデータにはならないので、設定によらず外して数える。
EOF_MARK='\x1a'
_JUNK_CHARS=frozenset(chr(c) for c in range(0x20) if chr(c)!='\t')|{'\x7f','\ufffd'}
_JUNK_BYTES=frozenset(c for c in range(0x20) if c!=0x09)|{0x7f}

def is_junk_line(line):
 """読めない記号だけの行か。空白・タブだけの行は空行なので、ここでは数えない（「空行を飛ばす」に任せる）。"""
 if isinstance(line,bytes):
  body=line.strip(b' \t')
  return bool(body) and all(c in _JUNK_BYTES for c in body)
 body=line.strip(' \t\u3000')
 return bool(body) and all(c in _JUNK_CHARS for c in body)

def is_junk_row(cells):
 """CSV などで読んだ1行が、空か読めない記号だけのセルでできているか（終わりの印だけの行が1件になったもの）。"""
 vals=[str(c or '') for c in (cells or [])]
 return any(is_junk_line(v) for v in vals) and all(not v.strip(' \t\u3000') or is_junk_line(v) for v in vals)

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
       'skipped_junk':0,'short_rows':0,'broken_cells':0,'width':width,'unit':l['unit'],'encoding':l['encoding'],
       'mode':l['mode'],'fields_max':0,
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
 delimited=(l['mode']=='delimited')
 blank=(b'' if l['unit']=='byte' and not delimited else '')
 split=splitter(l) if delimited else None
 picks=[c['field']-1 for c in cols] if delimited else None
 def take(line):
  if delimited:
   vals=split(line)
   if len(vals)>stat['fields_max']:stat['fields_max']=len(vals)
   if len(vals)<width:stat['short_rows']+=1
   out=[_trim(vals[k],l['trim']) if k<len(vals) else '' for k in picks]
  elif l['unit']=='byte':
   if len(line)<width:stat['short_rows']+=1
   out=_slice_byte(line,cols,l['encoding'],l['trim'],stat)
  else:
   if len(line)<width:stat['short_rows']+=1
   out=_slice_char(line,cols,l['trim'])
  return typed(out) if convs else out
 header_seen=[False]
 source=(_read_records(path,l) if delimited else ((x,1) for x in _read_lines(path,l['encoding'],l['unit'])))
 for line,used in source:
  stat['lines']+=used
  if stat['lines']<=l['skip_head']:
   stat['skipped_head']+=1;continue
  if is_junk_line(line):
   stat['skipped_junk']+=1;continue
  # 最後の行の後ろに付いた終わりの印（改行が無いとき）は、印だけを外して行は残す
  mark=EOF_MARK.encode() if isinstance(line,bytes) else EOF_MARK
  if line.endswith(mark):line=line.rstrip(mark)
  if l['skip_blank'] and line.strip()==blank:
   stat['skipped_blank']+=1;continue
  if l['header_row'] and not header_seen[0]:
   # 1行目が見出しの行。列名はマスタ側の名前を使う（ファイル側の表記ゆれに引きずられない）。
   header_seen[0]=True;stat['skipped_head']+=1;continue
  hold.append(line)
  if len(hold)<=tail:continue
  use=hold.pop(0)
  body.append(take(use))
  if keep_raw:raws.append(use.decode(l['encoding'],errors='replace') if isinstance(use,bytes) else use)
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
 # 名前は保存のための決まりで、切り方とは関係が無い。作りかけ（名前がまだ無い）でも下読みできるようにする。
 l=normalize_layout(layout)
 bad=validate_layout(dict(l,name=l['name'] or '下読み'))
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
 # 区切りでは、1件目の項目そのもの（取った列ではなく、分けた全部）も返す。画面が「項目の何番目に
 # 何が入っているか」を列の横に出すため ―― 番号を直したとき、その場で値が変わって見える。
 if stat['mode']=='delimited' and raws:out['fields']=splitter(layout)(raws[0])
 if stat['skipped_junk']:
  out['notes'].append(f'読めない記号だけの行（ファイルの終わりの印など）{stat["skipped_junk"]}行は、データにせず外しました')
 if stat['short_rows']:
  if stat['mode']=='delimited':
   out['notes'].append(f'{stat["short_rows"]}行は項目が{stat["width"]}個に足りず、足りない列は空になりました'
                       '（区切りか囲み文字が合っていない可能性があります）')
  else:
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

# 見本から見当を付ける候補。空白は最後（他の記号が無いときだけ、続いた空白を1つとして見る）。
SNIFF_DELIMITERS=('tab','comma','semicolon','pipe')
SNIFF_LINES=30

def sniff_delimited(path,layout,lines=SNIFF_LINES):
 """見本のファイルから、区切りと列の見当を付ける（区切りの初めの1回を、考えずに済ませるため）。

 区切りは、先頭の数十件で「どの件も同じ数に分かれ、しかも2つ以上に分かれる」記号を選ぶ。
 該当が無ければ空白（続いた空白は1つ）。利用者が区切りを決めているなら（文字を指定・正規表現）、それを使う。
 列は1件目から作る。「1行目は見出し」なら見出しの文字を列名にし、2件目を見本の値にする。
 返すのは {'ok','delimiter','delimiter_text','collapse','quote','columns':[{'name','field','sample'}],'records'}。
 """
 l=normalize_layout(dict(layout or {},mode='delimited'))
 p=Path(path)
 if not p.is_file():return {'ok':False,'error':f'ファイルがありません: {p}'}
 recs=[]
 try:
  for rec,_used in _read_records(p,l):
   if len(recs)>=int(lines)+l['skip_head']:break
   recs.append(rec)
 except Exception as e:
  log.warning('TEXT_SNIFF_FAILED path=%s error=%s',p,e)
  return {'ok':False,'error':f'読み取れませんでした: {e}'}
 recs=[r for r in recs[l['skip_head']:] if r.strip()]
 if not recs:return {'ok':False,'error':'中身のある行が見つかりませんでした（文字コードと、先頭を読み飛ばす行数を確かめてください）'}
 chosen=None
 if l['delimiter'] in ('custom','regex') and l['delimiter_text']:chosen=dict(l)
 else:
  best=None
  for d in SNIFF_DELIMITERS:
   cand=dict(l,delimiter=d,collapse=False)
   counts=[len(splitter(cand)(r)) for r in recs]
   # 揃っている割合が高く、分かれる数が多いものを選ぶ（末尾の1件だけ短い、などは許す）。
   top=max(set(counts),key=counts.count)
   if top<2:continue
   score=(counts.count(top)/len(counts),top)
   if best is None or score>best[0]:best=(score,cand)
  chosen=best[1] if best and best[0][0]>=0.8 else dict(l,delimiter='space',collapse=True,quote='none')
 split=splitter(chosen)
 first=split(recs[0]);second=split(recs[1]) if len(recs)>1 else []
 head=l['header_row']
 names=[(x.strip() or f'列{i+1}') if head else f'列{i+1}' for i,x in enumerate(first)]
 sample=second if head else first
 # 見出しの重なりは、そのままでは保存できない。番号を付けて分ける（直すのは利用者に任せる）。
 seen={}
 for i,n in enumerate(names):
  seen[n]=seen.get(n,0)+1
  if seen[n]>1:names[i]=f'{n}_{seen[n]}'
 cols=[{'name':n,'field':i+1,'sample':(sample[i] if i<len(sample) else '')[:60]} for i,n in enumerate(names)]
 if len(cols)>MAX_COLUMNS:cols=cols[:MAX_COLUMNS]
 log.info('TEXT_SNIFF path=%s delimiter=%s collapse=%s 列=%s 見た件=%s 見出し=%s',
          p,chosen['delimiter'],chosen['collapse'],len(cols),len(recs),head)
 return {'ok':True,'delimiter':chosen['delimiter'],'delimiter_text':chosen.get('delimiter_text',''),
         'collapse':chosen['collapse'],'quote':chosen['quote'],'columns':cols,'records':len(recs),
         'label':delimiter_label(chosen)}

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
 log.info('TEXT_READ file=%s size=%s mode=%s encoding=%s unit=%s width=%s 行=%s（読んだ行%s 空%s 読めない記号だけ%s 見出し・先頭%s 末尾%s）'
          ' 短い行=%s 文字の途中で切れた=%s 列=%s 中間CSV=%s',
          p,p.stat().st_size,stat['mode'],stat['encoding'],stat['unit'],stat['width'],stat['rows'],stat['lines'],
          stat['skipped_blank'],stat['skipped_junk'],stat['skipped_head'],stat['skipped_tail'],stat['short_rows'],
          stat['broken_cells'],len(headers),dst)
 if stat['short_rows']:
  log.warning('TEXT_SHORT_ROWS file=%s 行=%s が%s%sに足りません。足りない列は空になります',
              p,stat['short_rows'],stat['width'],
              '項目' if stat['mode']=='delimited' else 'バイト' if stat['unit']=='byte' else '文字')
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
