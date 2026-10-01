"""集計表（表頭あり・付帯情報を集計しない）RNEを、リスト形式へ読めるかの評価。

実行:  python -m unittest tests.test_crosstab -v
採点表: python tests/test_crosstab.py

Navigatorサーバーには繋がないので、NaviSaveData が書く中間CSVをここで組み立てて読ませる。
組み立て方は1通りに決め打ちしない。実機で確かめられていない部分（表頭の値を
ブロックの全列に書くか先頭だけか、表側の左上に表頭名が入るか、表側の同じ値を
繰り返すか）は、ありうる形をすべて作って、どれでも同じリストになることを確かめる。

正解（ORACLE）はRNEの解析結果を使わず、画面（レイアウトの指定）から手で書き起こしてある。
解析器の答え合わせを解析器自身にさせないためである。
"""
import csv,itertools,os,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'lib')]
SAMPLE=ROOT/'samples'/'rne'/'集計表形式サンプル.RNE'

# 画面「レイアウトの指定」から書き起こした正解。
ORACLE={
 'side':['倉入完了_年月日','ﾛｯﾄ番号','鋳造番号','ｵｰﾀﾞｰ番号','製造材質','製造調質',
         '製造板厚','製造板幅','製造板丈','用途ｺｰﾄﾞ','用途名'],
 'head':['BOX番号'],
 'data':['BOX実績_設備名','BOX実績_板厚','BOX実績_板幅','BOX実績_板丈',
         'BOX実績_良品重量','BOX実績_枚本数','BOX実績_作業開始_日付','BOX実績_作業終了_日付'],
}

# 正解のデータ。ロットごとに、通ったBOX（工程）の実績を持つ。
# A と B は倉入日が同じ ―― 表側を繰り返さない書き方だと、Bの倉入日が空欄になる。
# B は BOX5 を通っていない ―― その列は空欄が正しい。
# BOX番号は連番とは限らない（1, 2, 5）。列名には並び順ではなく、この値そのものを使う。
LOTS=[
 {'side':['2026/09/01','L001','C01','O01','A1100','H14','1.00','1000','2000','U1','缶材'],
  'boxes':{1:['CRM1','1.2','1010','2010','950','10','2026/08/20','2026/08/21'],
           2:['SLT1','1.0','1000','2000','900','10','2026/08/25','2026/08/26'],
           5:['PKG1','1.0','1000','2000','890','10','2026/08/28','2026/08/28']}},
 {'side':['2026/09/01','L002','C01','O02','A1100','H14','1.00','1000','2000','U1','缶材'],
  'boxes':{1:['CRM1','1.2','1010','2010','800','8','2026/08/20','2026/08/21'],
           2:['SLT2','1.0','1000','2000','780','8','2026/08/26','2026/08/27']}},
 {'side':['2026/09/02','L003','C02','O03','A5052','O','2.00','1200','2400','U2','建材'],
  'boxes':{1:['CRM2','2.2','1210','2410','1500','5','2026/08/22','2026/08/23'],
           2:['SLT1','2.0','1200','2400','1450','5','2026/08/29','2026/08/30'],
           5:['PKG2','2.0','1200','2400','1440','5','2026/08/31','2026/08/31']}},
]
CATEGORIES=[1,2,5]   # 表頭 BOX番号 のカテゴリ（サーバーが返す並び）

def truth_list():
 """正解のリスト形式。見出しは 表側 ＋ データ項目#BOX番号の値。"""
 hs=list(ORACLE['side'])+[f'{d}#{cat}' for cat in CATEGORIES for d in ORACLE['data']]
 body=[]
 for lot in LOTS:
  row=list(lot['side'])
  for cat in CATEGORIES:row+=lot['boxes'].get(cat,['']*len(ORACLE['data']))
  body.append(row)
 return hs,body

def navi_csv(head_repeat=True,side_repeat=True,head_label=False):
 """NaviSaveData(NAVI_CSV) が書くであろう中間CSVの行を組み立てる。

 head_repeat … 表頭の値をブロックの全列に書く（NAVI_REPEAT）か、先頭列だけか（NAVI_NONREPEAT）
 side_repeat … 表側の同じ値を毎行書く（NAVI_REPEAT）か、上と同じなら空欄にするか
 head_label  … 表頭の段の、表側側の右端に表頭名（BOX番号）が入るか
 """
 S=len(ORACLE['side']);D=len(ORACLE['data'])
 top=['']*S
 if head_label:top[-1]=ORACLE['head'][0]
 for cat in CATEGORIES:
  top+=[str(cat)]*D if head_repeat else [str(cat)]+['']*(D-1)
 rows=[top,list(ORACLE['side'])+list(ORACLE['data'])*len(CATEGORIES)]
 prev=None
 for lot in LOTS:
  side=list(lot['side'])
  if not side_repeat and prev:
   # 階層の見せ方：左から順に、上の行と同じ値が続くあいだだけ空欄にする
   for i in range(S):
    if side[i]!=prev[i]:break
    side[i]=''
  prev=list(lot['side'])
  row=side
  for cat in CATEGORIES:row+=lot['boxes'].get(cat,['']*D)
  rows.append(row)
 return rows

VARIANTS=[dict(head_repeat=h,side_repeat=s,head_label=l)
          for h,s,l in itertools.product((True,False),(True,False),(False,True))]

def write_csv(rows,path):
 with open(path,'w',encoding='cp932',newline='') as f:csv.writer(f).writerows(rows)

def evaluate(hs,body):
 """読み取った結果を正解と突き合わせ、観点ごとの合否を返す（評価関数）。"""
 ths,tbody=truth_list()
 S=len(ORACLE['side'])
 out={}
 out['列名が重複しない']=len(set(hs))==len(hs)
 out['列数が正しい']=len(hs)==len(ths)
 out['表側の列名が正しい']=hs[:S]==ths[:S]
 out['データ列に表頭の値が付く']=hs[S:]==ths[S:]
 out['件数が正しい（見出しが本体に混ざらない）']=len(body)==len(tbody)
 out['表側の値が欠けない']=len(body)==len(tbody) and all(b[:S]==t[:S] for b,t in zip(body,tbody))
 out['値の位置がずれない']=len(body)==len(tbody) and all(b==t for b,t in zip(body,tbody))
 return out

class CrosstabLayoutTest(unittest.TestCase):
 """RNEの解析が、画面どおりの 表側・表頭・データ項目 を返すか。"""
 def test_sample_layout(self):
  import navi_crosstab
  lay=navi_crosstab.read_rne_layout(SAMPLE)
  self.assertIsNotNone(lay)
  self.assertEqual(lay['side'],ORACLE['side'])
  self.assertEqual(lay['head'],ORACLE['head'])
  self.assertEqual(lay['data'],ORACLE['data'])
  self.assertTrue(lay['crosstab'])
  self.assertTrue(lay['detail_only'])

 def test_detail_rnes_are_not_crosstab(self):
  """既存の明細RNEは表頭を持たない。読み方が変わらないことの裏付け。"""
  import navi_crosstab
  for p in sorted((ROOT/'config'/'rne').glob('*.RNE')):
   lay=navi_crosstab.read_rne_layout(p)
   self.assertIsNotNone(lay,p.name)
   self.assertEqual(lay['head'],[],p.name)
   self.assertFalse(lay['crosstab'],p.name)
   self.assertTrue(lay['side'],p.name)

 def test_unreadable_file_is_none(self):
  import navi_crosstab
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'broken.RNE';p.write_bytes(b'\x00NAVI>\x00\n32\n')
   self.assertIsNone(navi_crosstab.read_rne_layout(p))
   self.assertIsNone(navi_crosstab.read_rne_layout(Path(d)/'missing.RNE'))

class CrosstabReadTest(unittest.TestCase):
 """中間CSVを、アプリの読み取り（read_extract）でリスト形式にできるか。"""
 @classmethod
 def setUpClass(cls):
  import app,navi_crosstab
  cls.app=app;cls.layout=navi_crosstab.read_rne_layout(SAMPLE)
  cls.tmp=tempfile.TemporaryDirectory()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def read(self,rows,job_type='詳細データ',layout=True,expected_rows=None,expected_cols=None):
  p=Path(self.tmp.name)/'navi.csv';write_csv(rows,p)
  job={'name':'t','type':job_type}
  if layout:job['_rne_layout']=self.layout
  return self.app.read_extract(p,job,False,expected_rows,expected_cols)

 def test_every_variant_becomes_the_same_list(self):
  for v in VARIANTS:
   # 表側を繰り返さない形は、実行では NAVI_REPEAT を指定して避ける。読みで埋め戻しはしない
   # （本当に空欄の値と区別できないため）。ここでは列名と件数・位置だけを見る。
   with self.subTest(**v):
    hs,body=self.read(navi_csv(**v))
    score=evaluate(hs,body)
    keys=list(score) if v['side_repeat'] else [k for k in score if k not in ('表側の値が欠けない','値の位置がずれない')]
    self.assertEqual({k:score[k] for k in keys},{k:True for k in keys})

 def test_reading_type_does_not_matter(self):
  """読込形式を「集計表」にしていても、していなくても同じ結果になる（RNEで決まる）。"""
  a=self.read(navi_csv(),'詳細データ');b=self.read(navi_csv(),'集計表')
  self.assertEqual(a,b)

 def test_counts_check(self):
  """件数検査は本体の行数で行う。見出しが2段あっても行数は変わらない。"""
  ths,tbody=truth_list()
  hs,body=self.read(navi_csv(),expected_rows=len(tbody),expected_cols=len(ths))
  self.assertEqual(len(body),len(tbody))
  with self.assertRaises(RuntimeError):self.read(navi_csv(),expected_rows=len(tbody)+1)

 def test_field_count_of_definition_is_accepted(self):
  """フィールド数が「表側＋データ項目」（展開前）で返っても、形が検証できれば通す。"""
  ths,tbody=truth_list()
  hs,body=self.read(navi_csv(),expected_rows=len(tbody),expected_cols=len(ORACLE['side'])+len(ORACLE['data']))
  self.assertEqual(hs,ths)
  with self.assertRaises(RuntimeError):self.read(navi_csv(),expected_rows=len(tbody),expected_cols=5)

 def test_zero_rows(self):
  rows=navi_csv()[:2]
  hs,body=self.read(rows)
  self.assertEqual(hs,truth_list()[0]);self.assertEqual(body,[])

 def test_detail_rne_unchanged(self):
  """表頭の無いRNEはこれまでどおり1行目が見出し。"""
  rows=[['a','b'],['1','2'],['3','4']]
  hs,body=self.read(rows,layout=False)
  self.assertEqual(hs,['a','b']);self.assertEqual(body,[['1','2'],['3','4']])
  # これまでの「集計表」指定（表頭の無いRNE）は、先頭1行を読み飛ばす動きのまま
  hs,body=self.read([['title',''],['a','b'],['1','2']],job_type='集計表',layout=False)
  self.assertEqual(hs,['a','b']);self.assertEqual(body,[['1','2']])

 def test_xls_intermediate(self):
  """DDE経由の中間XLSも同じ読み方になる。"""
  import navi_crosstab
  rows=navi_csv(head_repeat=False,head_label=True)
  shape=navi_crosstab.header_shape('詳細データ',self.layout)
  names,used,info=shape.resolve(rows[:shape.lookahead])
  self.assertEqual(used,2);self.assertEqual(names,truth_list()[0]);self.assertTrue(info['structure_ok'])

class CrosstabNamingTest(unittest.TestCase):
 """データ列の名前の付け方。表頭の値を使い、重なったら連番で分ける。"""
 LAY={'side':['K'],'head':['H'],'data':['a','b'],'cond':[],'crosstab':True,'detail_only':True}

 def names(self,top,lay=None,extra_top=None):
  import navi_crosstab
  lay=lay or self.LAY;D=len(lay['data'])
  rows=([extra_top] if extra_top else [])+[top,['K']+lay['data']*((len(top)-1)//D),['k1']+['v']*(len(top)-1)]
  names,used,info=navi_crosstab.flatten_header(rows,lay)
  self.assertEqual(used,len(rows)-1)
  return names

 def test_values_not_order(self):
  """並び順ではなく値。1, 2, 5 なら #1, #2, #5（#3 にはならない）。"""
  self.assertEqual(self.names(['','1','1','2','2','5','5']),
                   ['K','a#1','b#1','a#2','b#2','a#5','b#5'])

 def test_text_values(self):
  self.assertEqual(self.names(['','CRM','','SLT','']),['K','a#CRM','b#CRM','a#SLT','b#SLT'])

 def test_duplicate_values_get_serial(self):
  """同じ値のブロックが重なったら、2つ目から _2, _3 … を付ける（1つ目はそのまま）。"""
  # 値を全列に書く形（隣り合う同じ値は、同じ名前の2度目で次のブロックと分かる）
  self.assertEqual(self.names(['','3','3','3','3','4','4','3','3']),
                   ['K','a#3','b#3','a#3_2','b#3_2','a#4','b#4','a#3_3','b#3_3'])
  # 値を先頭の列だけに書く形
  self.assertEqual(self.names(['','3','','3','','4','']),
                   ['K','a#3','b#3','a#3_2','b#3_2','a#4','b#4'])

 def test_serial_does_not_collide_with_real_value(self):
  """連番で作る名前が本物の値と重なるときは、本物の値が名前を持ち、連番の側がずれる。

  値「3」が2回と値「3_2」がある。2つ目の「3」を 3_2 にすると本物の 3_2 と区別できなくなるので、
  3_3 にする。本物の値の列名は、ほかのブロックの有無で変わらない。"""
  got=self.names(['','3','','3','','3_2',''])
  self.assertEqual(got,['K','a#3','b#3','a#3_3','b#3_3','a#3_2','b#3_2'])

 def test_blank_value(self):
  """表頭の値が空（NULLのカテゴリなど）は「空欄」。重なれば同じく連番。"""
  self.assertEqual(self.names(['','','','1','']),['K','a#空欄','b#空欄','a#1','b#1'])
  self.assertEqual(self.names(['','','','','']),['K','a#空欄','b#空欄','a#空欄_2','b#空欄_2'])
  # 値を全列に書く形（NAVI_REPEAT）で、途中のカテゴリが空。左の「3」を持ち越して 3_2 にしてはいけない
  self.assertEqual(self.names(['','3','3','','','4','4']),['K','a#3','b#3','a#空欄','b#空欄','a#4','b#4'])

 def test_xls_numbers(self):
  """中間XLSでは数値が 1.0 で来る。列名は 1 にする。"""
  self.assertEqual(self.names(['',1.0,1.0,2.0,2.0]),['K','a#1','b#1','a#2','b#2'])

 def test_two_head_levels(self):
  """表頭が2段なら、上から順に「／」でつなぐ。"""
  lay=dict(self.LAY,head=['H1','H2'])
  self.assertEqual(self.names(['','1','','1','','2',''],lay,extra_top=['','A','','','','','']),
                   ['K','a#A／1','b#A／1','a#A／1_2','b#A／1_2','a#A／2','b#A／2'])

class CrosstabExportTest(unittest.TestCase):
 """中間CSV → 出力ファイル（CSV・TXT・EXCEL・SQLite3）まで通し、読み戻して正解と比べる。"""
 def test_formats(self):
  import app,navi_crosstab
  lay=navi_crosstab.read_rne_layout(SAMPLE);ths,tbody=truth_list()
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'navi.csv';write_csv(navi_csv(head_repeat=False,head_label=True),src)
   for fmt in ('csv','txt','xlsx','sqlite3'):
    with self.subTest(fmt=fmt):
     job={'name':'t','type':'詳細データ','output_format':fmt,'output_file':f'out.{fmt}',
          'table':'t','sheet':'Page1','rne':SAMPLE.name,'_rne_layout':lay}
     dst=Path(d)/f'out.{fmt}'
     app.export_data(src,dst,job,False,len(tbody),len(ths))
     _fmt,hs,rows,total,_cols=app.read_preview_data(dst,job,limit=100)
     self.assertEqual(hs,ths);self.assertEqual(total,len(tbody))
     self.assertEqual(evaluate(hs,rows),{k:True for k in evaluate(ths,tbody)})

 def test_split_is_refused(self):
  import app
  why=app.crosstab_split_reason(SAMPLE)
  self.assertIn('集計表',why)
  self.assertEqual(app.crosstab_split_reason(ROOT/'config'/'rne'/'SIKAODRNOW.RNE'),'')

def scorecard():
 """観点ごとの合否を、形のバリエーション別に表で出す。"""
 import app,navi_crosstab
 lay=navi_crosstab.read_rne_layout(SAMPLE)
 cases=[('読込形式=詳細データ',{'type':'詳細データ'}),('読込形式=集計表',{'type':'集計表'})]
 with tempfile.TemporaryDirectory() as d:
  p=Path(d)/'navi.csv'
  for label,job in cases:
   for use_layout in (False,True):
    print(f'\n■ {label} / {"今回の読み方（RNEの形で決める）" if use_layout else "従来の読み方（RNEの形を見ない）"}')
    for v in VARIANTS:
     write_csv(navi_csv(**v),p)
     j=dict(job,name='t',**({'_rne_layout':lay} if use_layout else {}))
     try:
      hs,body=app.read_extract(p,j,False)
      s=evaluate(hs,body);ng=[k for k,x in s.items() if not x]
      res='OK' if not ng else 'NG: '+' / '.join(ng)
     except Exception as e:res=f'例外: {e}'
     tag=' '.join([('表頭=全列' if v['head_repeat'] else '表頭=先頭のみ'),
                   ('表側=毎行' if v['side_repeat'] else '表側=省略'),
                   ('左上=表頭名' if v['head_label'] else '左上=空')])
     if not v['side_repeat']:tag+=' ※'
     print(f'  {tag:<30} {res}')
 print('\n※ 表側を省く形（NAVI_NONREPEAT）。値が欠けるのは読み方では直せない（本当の空欄と区別できない）ため、'
       '\n  実行では集計表に NAVI_REPEAT を指定して、この形そのものを出させない。')

if __name__=='__main__':scorecard()
