"""マスタをEXCELで出し入れする。

JSONでの持ち出しは、機械にとっては正しいが、人にとっては読めない。読取マスタの
列定義は300行を超えることがあり、そういうものは実際にはEXCELで作られている
（仕様書がEXCELなのだから当然で、いまも手で写して入れている）。

だから、そのまま開いて、並べ替えて、埋めて、返せる形で出す。列の並びと見出しは
画面の言葉にそろえてあり、読み込むときも見出しの名前で拾う ―― 列を足したり
並べ替えたりしても壊れない。

形は「1シート＝1つの表」。1つのマスタを1シートにすると読みやすいが、シート名には
長さと使えない文字の制限があり、マスタ名をそのまま置けない。名前で困るくらいなら、
一覧と明細に分けて、名前の列で結ぶほうが確かで、EXCELの絞り込みもそのまま使える。

  読取マスタ … 「読取マスタ」（1行＝1マスタ）＋「列」（1行＝1列）
  結合マスタ … 「結合マスタ」＋「ファイル」＋「つなぎ目」＋「出す列」

app.py から分けてある。本体の状態は一切見ない（受け取るのは整えた取り決めだけ）。
"""
from datetime import datetime
from pathlib import Path
from navi_log import log

BOOK_FORMATS=('json','xlsx')
BOOK_FORMAT_LABEL={'json':'JSON（そのまま持ち運ぶ）','xlsx':'EXCEL（開いて直せる）'}

# 見出しと、取り決めの中の名前の対応。読み書きの両方がこれ1つを見る
# ―― 書くときと読むときで別々に並べると、片方だけ直したときに気づけない。
LAYOUT_SHEET='読取マスタ'
LAYOUT_COLS_SHEET='列'
LAYOUT_FIELDS=[('マスタ名','name'),('用途メモ','description'),('文字コード','encoding'),
               ('単位','unit'),('空白の扱い','trim'),('先頭を読み飛ばす','skip_head'),
               ('末尾を読み飛ばす','skip_tail'),('空行を飛ばす','skip_blank'),
               ('1行目は見出し','header_row'),('テーブル名','table')]
LAYOUT_COL_FIELDS=[('マスタ名',None),('順',None),('列名','name'),('開始位置','start'),
                   ('長さ','length'),('型','type'),('小数桁','scale'),('書式','format'),('メモ','note')]

RECIPE_SHEET='結合マスタ'
RECIPE_SRC_SHEET='ファイル'
RECIPE_JOIN_SHEET='つなぎ目'
RECIPE_COL_SHEET='出す列'
RECIPE_FIELDS=[('結合マスタ名','name'),('用途メモ','description')]
RECIPE_SRC_FIELDS=[('結合マスタ名',None),('記号','alias'),('表示名','name'),('場所','path'),
                   ('形式','format'),('テーブル','table'),('シート','sheet'),('読取マスタ',None)]
RECIPE_JOIN_FIELDS=[('結合マスタ名',None),('つなぎ目',None),('繋ぎ方',None),('左の列','left'),('右の列','right')]
RECIPE_COL_FIELDS=[('結合マスタ名',None),('元','source'),('列名','name'),('別名','as')]

_YES,_NO='はい','いいえ'
def _b(v):return _YES if v else _NO
def _unb(v):
 t=str(v or '').strip().lower()
 return t in (_YES,'true','1','yes','y','on','o','✓','はい')

def _txt(v):return '' if v is None else str(v).strip()
def _num(v,default=0):
 try:return int(float(str(v).strip()))
 except Exception:return default

# ---- 書き出し --------------------------------------------------------------
def _sheet(wb,title,headers,rows,widths=None,first=False):
 ws=wb.active if first else wb.create_sheet()
 ws.title=title
 ws.append(list(headers))
 for r in rows:ws.append(list(r))
 from openpyxl.styles import Font,PatternFill,Alignment
 head=Font(bold=True,color='FF1F4E5A');fill=PatternFill('solid',fgColor='FFEAF3F5')
 for c in ws[1]:
  c.font=head;c.fill=fill;c.alignment=Alignment(vertical='center')
 # 見出しは常に見えるところに置く。300行の列定義を上下すると、何の列だったかを
 # すぐ見失う ―― EXCELで直すことを前提にする以上、ここは要る。
 ws.freeze_panes='A2'
 ws.auto_filter.ref=ws.dimensions
 for i,w in enumerate(widths or [],1):
  ws.column_dimensions[ws.cell(row=1,column=i).column_letter].width=w
 return ws

def _stamp_sheet(wb,kind,count):
 ws=wb.create_sheet();ws.title='このファイルについて'
 for row in (['種類',kind],['書き出した日時',datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
             ['件数',count],
             ['','']  ,
             ['使い方','値を直してから、取り込みで読み込みます。'],
             ['','見出しの名前で拾うので、列を並べ替えても、右へ列を足しても構いません。'],
             ['','見出しの行そのものは消さないでください。'],
             ['','このシートは読み込みでは見ません。'],):
  ws.append(row)
 ws.column_dimensions['A'].width=18;ws.column_dimensions['B'].width=76
 from openpyxl.styles import Font
 for i in (1,2,3,5):ws.cell(row=i,column=1).font=Font(bold=True)
 ws.cell(row=5,column=1).value='使い方'
 return ws

def layouts_to_xlsx(layouts,dst):
 """読取マスタをEXCELへ。1行＝1マスタ、列は別シートに1行＝1列で並べる。"""
 from openpyxl import Workbook
 wb=Workbook()
 rows=[]
 for x in (layouts or []):
  rows.append([_b(x[k]) if k in ('skip_blank','header_row') else x.get(k,'') for _h,k in LAYOUT_FIELDS])
 _sheet(wb,LAYOUT_SHEET,[h for h,_k in LAYOUT_FIELDS],rows,
        widths=[26,34,12,8,12,15,15,12,13,16],first=True)
 crows=[]
 for x in (layouts or []):
  for i,c in enumerate(x.get('columns') or [],1):
   crows.append([x.get('name',''),i]+[c.get(k,'') for _h,k in LAYOUT_COL_FIELDS[2:]])
 _sheet(wb,LAYOUT_COLS_SHEET,[h for h,_k in LAYOUT_COL_FIELDS],crows,
        widths=[26,6,28,11,9,9,9,20,30])
 _stamp_sheet(wb,'読取マスタ',len(layouts or []))
 Path(dst).parent.mkdir(parents=True,exist_ok=True)
 wb.save(dst);wb.close()
 log.info('BOOK_EXPORT kind=読取マスタ count=%s columns=%s file=%s',len(layouts or []),len(crows),dst)
 return dst

def recipes_to_xlsx(recipes,dst,join_label=None):
 """結合マスタをEXCELへ。ファイル・つなぎ目・出す列を、それぞれ1シートに。"""
 from openpyxl import Workbook
 label=join_label or (lambda t:t)
 wb=Workbook()
 _sheet(wb,RECIPE_SHEET,[h for h,_k in RECIPE_FIELDS],
        [[x.get(k,'') for _h,k in RECIPE_FIELDS] for x in (recipes or [])],
        widths=[30,44],first=True)
 srows=[]
 for x in (recipes or []):
  for s in x.get('sources') or []:
   srows.append([x.get('name',''),s.get('alias',''),s.get('name',''),s.get('path',''),
                 s.get('format',''),s.get('table',''),s.get('sheet',''),s.get('_layout_name','')])
 _sheet(wb,RECIPE_SRC_SHEET,[h for h,_k in RECIPE_SRC_FIELDS],srows,widths=[30,7,22,56,11,16,14,22])
 jrows=[]
 for x in (recipes or []):
  for i,j in enumerate(x.get('joins') or [],1):
   keys=j.get('keys') or [{'left':'','right':''}]
   for k in keys:
    jrows.append([x.get('name',''),i,label(j.get('type','inner')),k.get('left',''),k.get('right','')])
 _sheet(wb,RECIPE_JOIN_SHEET,[h for h,_k in RECIPE_JOIN_FIELDS],jrows,widths=[30,9,22,26,26])
 crows=[]
 for x in (recipes or []):
  for c in x.get('columns') or []:
   crows.append([x.get('name',''),c.get('source',''),c.get('name',''),c.get('as','')])
 _sheet(wb,RECIPE_COL_SHEET,[h for h,_k in RECIPE_COL_FIELDS],crows,widths=[30,7,28,28])
 _stamp_sheet(wb,'結合マスタ',len(recipes or []))
 Path(dst).parent.mkdir(parents=True,exist_ok=True)
 wb.save(dst);wb.close()
 log.info('BOOK_EXPORT kind=結合マスタ count=%s ファイル=%s つなぎ目=%s file=%s',
          len(recipes or []),len(srows),len(jrows),dst)
 return dst

# ---- 読み込み --------------------------------------------------------------
def _read_sheet(wb,title):
 """1シートを「見出し→値」の辞書の並びで読む。

 見出しの名前で拾うので、列を並べ替えても、右へ覚え書きの列を足しても壊れない。
 EXCELで直すことを前提にする以上、そこは崩れないようにしておく。
 """
 if title not in wb.sheetnames:return []
 ws=wb[title];it=ws.iter_rows(values_only=True)
 head=[_txt(x) for x in (next(it,()) or ())]
 if not any(head):return []
 out=[]
 for row in it:
  if not any(x is not None and _txt(x) for x in row):continue    # 空行は飛ばす
  out.append({head[i]:row[i] for i in range(min(len(head),len(row))) if head[i]})
 return out

def _pick(row,label,default=''):
 v=row.get(label)
 return default if v is None else v

def layouts_from_xlsx(src,label_to_type=None,label_to_encoding=None,label_to_unit=None,label_to_trim=None):
 """EXCELから読取マスタを組み立てる。(取り決めの並び, 読めなかった理由) を返す。

 値は画面の言葉でも、内部の言葉でも受ける。EXCELで直すのは人なので、「整数」と
 書いても "integer" と書いても通るのが当たり前 ―― どちらか片方しか受けないのは、
 こちらの都合を人に押しつけているだけ。
 """
 from openpyxl import load_workbook
 bad=[]
 try:wb=load_workbook(src,read_only=True,data_only=True)
 except Exception as e:return [],[f'EXCELとして読めません: {e}']
 try:
  heads=_read_sheet(wb,LAYOUT_SHEET)
  cols=_read_sheet(wb,LAYOUT_COLS_SHEET)
 finally:wb.close()
 if not heads:
  return [],[f'「{LAYOUT_SHEET}」シートが見つからないか、中身がありません'
             f'（書き出したEXCELと同じ形にしてください）']
 by={}
 for c in cols:
  nm=_txt(_pick(c,'マスタ名'))
  if not nm:continue
  by.setdefault(nm,[]).append(c)
 out=[]
 for h in heads:
  name=_txt(_pick(h,'マスタ名'))
  if not name:continue
  mine=by.get(name) or []
  # 「順」があればその順、無ければ書いてある順。EXCELで並べ替えた結果を尊重する。
  try:mine=sorted(mine,key=lambda c:_num(_pick(c,'順'),10**6))
  except Exception:pass
  if not mine:bad.append(f'「{name}」に列が1つもありません（「{LAYOUT_COLS_SHEET}」シートを確認してください）')
  columns=[]
  for c in mine:
   cn=_txt(_pick(c,'列名'))
   if not cn:continue
   columns.append({'name':cn,'start':_num(_pick(c,'開始位置'),1),'length':_num(_pick(c,'長さ'),1),
                   'type':(label_to_type or (lambda v:v))(_txt(_pick(c,'型'))),
                   'scale':_num(_pick(c,'小数桁'),0),'format':_txt(_pick(c,'書式')),
                   'note':_txt(_pick(c,'メモ'))})
  out.append({'name':name,'description':_txt(_pick(h,'用途メモ')),
              'encoding':(label_to_encoding or (lambda v:v))(_txt(_pick(h,'文字コード'))),
              'unit':(label_to_unit or (lambda v:v))(_txt(_pick(h,'単位'))),
              'trim':(label_to_trim or (lambda v:v))(_txt(_pick(h,'空白の扱い'))),
              'skip_head':_num(_pick(h,'先頭を読み飛ばす'),0),'skip_tail':_num(_pick(h,'末尾を読み飛ばす'),0),
              'skip_blank':_unb(_pick(h,'空行を飛ばす',_YES)),'header_row':_unb(_pick(h,'1行目は見出し')),
              'table':_txt(_pick(h,'テーブル名')),'columns':columns})
 if not out:bad.append('取り込める読取マスタが1件もありませんでした')
 return out,bad

def recipes_from_xlsx(src,label_to_join=None,name_to_layout=None):
 """EXCELから結合マスタを組み立てる。(取り決めの並び, 読めなかった理由) を返す。"""
 from openpyxl import load_workbook
 bad=[]
 try:wb=load_workbook(src,read_only=True,data_only=True)
 except Exception as e:return [],[f'EXCELとして読めません: {e}']
 try:
  heads=_read_sheet(wb,RECIPE_SHEET)
  srcs=_read_sheet(wb,RECIPE_SRC_SHEET)
  joins=_read_sheet(wb,RECIPE_JOIN_SHEET)
  cols=_read_sheet(wb,RECIPE_COL_SHEET)
 finally:wb.close()
 if not heads:
  return [],[f'「{RECIPE_SHEET}」シートが見つからないか、中身がありません'
             f'（書き出したEXCELと同じ形にしてください）']
 def group(rows,key='結合マスタ名'):
  g={}
  for r in rows:
   nm=_txt(_pick(r,key))
   if nm:g.setdefault(nm,[]).append(r)
  return g
 gs,gj,gc=group(srcs),group(joins),group(cols)
 out=[]
 for h in heads:
  name=_txt(_pick(h,'結合マスタ名'))
  if not name:continue
  sources=[]
  for s in gs.get(name) or []:
   path=_txt(_pick(s,'場所'))
   if not path:continue
   sources.append({'alias':_txt(_pick(s,'記号')),'name':_txt(_pick(s,'表示名')),'path':path,
                   'format':_txt(_pick(s,'形式')).lower(),'table':_txt(_pick(s,'テーブル')),
                   'sheet':_txt(_pick(s,'シート')),
                   'layout_id':(name_to_layout or (lambda v:''))(_txt(_pick(s,'読取マスタ')))})
  # つなぎ目は「何番目か」でまとめる。1つのつなぎ目にキーを何組も書けるようにするため。
  byn={}
  for j in gj.get(name) or []:
   n=_num(_pick(j,'つなぎ目'),1)
   d=byn.setdefault(n,{'type':(label_to_join or (lambda v:v))(_txt(_pick(j,'繋ぎ方'))),'keys':[]})
   left=_txt(_pick(j,'左の列'));right=_txt(_pick(j,'右の列'))
   if left or right:d['keys'].append({'left':left,'right':right})
  jl=[byn[k] for k in sorted(byn)]
  columns=[{'source':_txt(_pick(c,'元')),'name':_txt(_pick(c,'列名')),'as':_txt(_pick(c,'別名'))}
           for c in (gc.get(name) or []) if _txt(_pick(c,'列名'))]
  if len(sources)<2:
   bad.append(f'「{name}」のファイルが{len(sources)}件です（「{RECIPE_SRC_SHEET}」シートに2件以上必要です）')
   continue
  out.append({'name':name,'description':_txt(_pick(h,'用途メモ')),
              'sources':sources,'joins':jl,'columns':columns})
 if not out and not bad:bad.append('取り込める結合マスタが1件もありませんでした')
 return out,bad

def sniff(src):
 """このEXCELは、読取マスタと結合マスタのどちらか。'layout' / 'recipe' / ''。

 落としたファイルが何なのかは、こちらで見れば分かる。人に選ばせる必要がない。
 """
 from openpyxl import load_workbook
 try:
  wb=load_workbook(src,read_only=True,data_only=True)
  names=set(wb.sheetnames);wb.close()
 except Exception:return ''
 if LAYOUT_SHEET in names:return 'layout'
 if RECIPE_SHEET in names:return 'recipe'
 return ''
