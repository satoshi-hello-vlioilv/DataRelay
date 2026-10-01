"""集計表（表頭あり）の読み方。

RNEの「表の種類」が集計表で、表頭に管理ポイントを置くと、データ項目は表頭の
カテゴリの数だけ横に繰り返される。NaviSaveData の中間ファイルは見出しが段になり、
1段目に表頭の値（例: BOX番号 1, 2, 3 …）、2段目に表側の名前とデータ項目の名前が並ぶ。

    （空）      …（空）   | 1             1            … | 2             2            …
    倉入完了_年月日 … 用途名 | BOX実績_設備名 BOX実績_板厚 … | BOX実績_設備名 BOX実績_板厚 …

これを1段の見出しに畳む。表側の列は名前のまま、データ項目の列は「名前#ブロック番号」
（左から1, 2, …）にする。データの並びは1マスも動かさないので、値の位置は変わらない。

何段あるか・どこまでが表側かは、RNEに書いてある配置（表側／表頭／データ項目）で決める。
RNEは実行のたびに同じものを開くので、推測ではなく、その問い合わせの定義そのものである。
ただし中間ファイルの書き方（表頭の値をブロックの全列に書くか先頭だけか、表側の左上に
表頭名を書くか）は版や指定で揺れうるので、そこは決め打ちせず実物の見出しを見て合わせる。

DBも画面もAPIも触らない。ファイルと行を受け取って答えるだけなので、実機なしで確かめられる。
"""
from pathlib import Path

# 付帯情報（集計しないデータ項目）の物の種類。
DETAIL_CLASS='CRNELDataDetailObjectNew'
# 配置表。表の定義の末尾にあり、どの物をどこへ置いたかを番号で持つ。
#   LDT … データ項目   LRT … 表側（管理ポイント／表示列）   LCT … 表頭   LWT … 条件
TABLE_TAGS=('LDT','LRT','LCT','LWT')

# 表頭の段を探す範囲。表頭の管理ポイントの数＋データ項目の名前の段より上に、
# 表題などの行が入っても見つけられるだけの余裕を持たせる。
EXTRA_SCAN_ROWS=3


def _lines(path):
 """RNEを行に分ける。値の区切りはNUL文字なので '|' に置き換え、行の前後の区切りは落とす。"""
 raw=Path(path).read_bytes()
 return [x.replace('\x00','|').strip().strip('|').strip() for x in raw.decode('cp932',errors='replace').split('\n')]

def _ids(text):
 """'3|10|11|12' → [10, 11, 12]。先頭は個数。個数と合わないものは壊れているとみなす。"""
 parts=[x for x in str(text).split('|') if x!='']
 if not parts or not parts[0].isdigit():return None
 n=int(parts[0]);rest=parts[1:]
 if len(rest)!=n or not all(x.isdigit() for x in rest):return None
 return [int(x) for x in rest]

def _is_number(s):
 return s.lstrip('-').isdigit()

def read_rne_layout(path):
 """RNEから 表側・表頭・データ項目・条件 の名前を、画面の並び順で返す。読めなければ None。

 RNEは行の並びで物を書いていく形式で、物ごとに「種類の名前（CSymnaviObject::…）→ 番号 →
 目印（LAPOなど）→ 中身」と続く。中身の最初の文字列がその物の名前（数字だけの行は設定値なので飛ばす）。
 最後に配置表があり、表側・表頭などに置いた物を番号で列挙している。
 """
 try:lines=_lines(path)
 except (OSError,ValueError):return None
 if not lines or lines[0]!='NAVI>':return None
 objs={}
 for i,cls in enumerate(lines[:-2]):
  if not cls.startswith('CSymnaviObject::') or not _is_number(lines[i+1]):continue
  name=next((x for x in lines[i+3:i+10] if x and not _is_number(x)),'')
  objs[int(lines[i+1])]={'cls':cls,'tag':lines[i+2],'name':name}
 # 配置表は定義の最後にある。同じ目印が途中に現れても、最後のものを使う。
 pos={t:max((i for i,x in enumerate(lines) if x==t),default=-1) for t in TABLE_TAGS}
 if min(pos.values())<0:return None
 def lists(tag,count):
  # 目印の次は版番号（32）。その次から count 行が番号の並び。
  i=pos[tag]+2
  got=[_ids(x) for x in lines[i:i+count]]
  return None if any(g is None for g in got) else got
 ldt=lists('LDT',1);lrt=lists('LRT',2);lct=lists('LCT',2);lwt=lists('LWT',2)
 if None in (ldt,lrt,lct,lwt):return None
 def names(ids):
  got=[(objs.get(k) or {}).get('name') for k in ids]
  return None if not all(got) else got
 # 表側・表頭・条件の1行目は管理ポイント、データは1行だけ。番号の指す物の名前を引く。
 side=names(lrt[0]);head=names(lct[0]);data=names(ldt[0]);cond=names(lwt[0])
 if None in (side,head,data,cond):return None
 detail_only=all(DETAIL_CLASS in objs[k]['cls'] for k in ldt[0])
 return {'side':side,'head':head,'data':data,'cond':cond,
         'crosstab':bool(head),'detail_only':detail_only}

def describe(layout):
 """ログと画面に出す一言。"""
 if not layout:return 'RNEの形を読めませんでした'
 if not layout.get('crosstab'):return f'明細（表側{len(layout["side"])}・データ{len(layout["data"])}）'
 return (f'集計表（表側{len(layout["side"])}・表頭{"／".join(layout["head"])}・'
         f'データ{len(layout["data"])}{"・付帯情報" if layout.get("detail_only") else ""}）')


class HeaderShape:
 """中間ファイルの先頭から、見出しを何行読み、どう名前にするかの決まり。

 lookahead … 判断に使う先頭の行数（これだけ先読みしてから resolve を呼ぶ）
 resolve(rows) → (列名, 見出しとして使った行数, 情報)
 """
 def __init__(self,kind,layout=None):
  self.kind=kind;self.layout=layout
  if kind=='crosstab':self.lookahead=len(layout['head'])+1+EXTRA_SCAN_ROWS
  elif kind=='skip_first':self.lookahead=2
  else:self.lookahead=1

 def resolve(self,rows):
  rows=[list(r) for r in rows]
  if not rows:return None,0,{'kind':self.kind}
  if self.kind=='crosstab':return flatten_header(rows,self.layout)
  if self.kind=='skip_first':
   if len(rows)<2:return None,len(rows),{'kind':self.kind}
   return rows[1],2,{'kind':self.kind}
  return rows[0],1,{'kind':self.kind}

def header_shape(read_type,layout):
 """見出しの読み方を決める。

 表頭のあるRNE（集計表）は、読込形式の指定に関わらず段を畳む。RNEそのものが
 段になると言っているので、人が「集計表」を選び忘れても列がずれないようにする。
 表頭の無いRNEは、これまでどおり（「集計表」指定なら先頭1行を読み飛ばす）。
 """
 if layout and layout.get('crosstab'):return HeaderShape('crosstab',layout)
 if read_type=='集計表':return HeaderShape('skip_first')
 return HeaderShape('plain')


def _cell(row,i):
 return str(row[i]).replace('\r','').replace('\n','').strip() if i<len(row) and row[i] is not None else ''

def _names_row(rows,S,data):
 """データ項目の名前が並ぶ段を探す。表側より右が、データ項目の名前の繰り返しになっている行。"""
 D=len(data)
 for r,row in enumerate(rows):
  cells=[_cell(row,c) for c in range(S,len(row))]
  while cells and cells[-1]=='':cells.pop()
  if D and cells and len(cells)%D==0 and all(x==data[k%D] for k,x in enumerate(cells)):return r
 return None

def flatten_header(rows,layout):
 """段になった見出しを1段に畳む。戻り値は (列名, 見出しの行数, 情報)。

 表側の列 … 見出しの段のうち、いちばん下の空でない文字（ふつうは表側の名前）
 データの列 … データ項目の名前＋'#'＋ブロック番号。ブロックは表頭の値が変わるところで
              切り替わる（表頭の値が先頭の列にしか書かれていない形でも、右へ持ち越して読む）。
              表頭の値が読めないときも、同じ名前が2度目に出たところで次のブロックとみなす。
 """
 S=len(layout['side']);data=list(layout['data']);H=len(layout['head'])
 r=_names_row(rows,S,data)
 found=r is not None
 if not found:r=min(H,len(rows)-1)          # 見つからなければRNEの段数どおりに読む
 depth=r+1;head_rows=rows[:r];names_row=rows[r]
 width=max(len(x) for x in rows[:depth])
 names=[]
 for c in range(min(S,width)):
  cells=[_cell(x,c) for x in rows[:depth]]
  names.append(next((x for x in reversed(cells) if x),layout['side'][c]))
 # 表頭の値。空欄は左の値を持ち越す（表側の範囲から持ち越さないよう、データの範囲だけで行う）。
 carried=[]
 for hr in head_rows:
  line=[];last=''
  for c in range(S,width):
   v=_cell(hr,c);last=v or last;line.append(last)
  carried.append(line)
 block=0;prev_key=None;seen=set();labels=[]
 for k,c in enumerate(range(S,width)):
  item=_cell(names_row,c) or (data[k%len(data)] if data else f'Column{c+1}')
  key=tuple(line[k] for line in carried)
  if block==0 or key!=prev_key or item in seen:
   block+=1;seen=set();labels.append('／'.join(x for x in key if x))
  seen.add(item);prev_key=key
  names.append(f'{item}#{block}')
 D=len(data)
 structure_ok=found and D>0 and (width-S)%D==0
 return names,depth,{'kind':'crosstab','depth':depth,'side':S,'data':D,'blocks':block,
                     'labels':labels,'names_row_found':found,'structure_ok':structure_ok}

def columns_consistent(info,actual_cols,expected_cols):
 """列数の検査を、集計表の形に合わせて行う。

 集計表の列数は「表側＋データ項目×表頭のカテゴリ数」で、カテゴリ数は実行のたびに変わる。
 APIが返すフィールド数が展開後の列数か、展開前の定義（表側＋データ項目）かは
 実機で確かめられていないため、どちらでも通す。ただし見出しの形が検証できたときだけ。
 """
 if expected_cols is None or int(expected_cols)==int(actual_cols):return True
 if not info or info.get('kind')!='crosstab' or not info.get('structure_ok'):return False
 return int(expected_cols)==info['side']+info['data']
