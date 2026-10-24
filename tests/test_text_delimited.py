"""読取マスタの区切り方式（2.8.0）。固定長と同じ取り決めの上で、1行を値の並びへ分けるところだけが違う。

確かめること:
- 区切りの種類（記号・文字を指定・正規表現）と、囲み文字・"" ・囲みの中の区切りと改行・連続をまとめる
- 列は「何番目の項目か」で取り、型・前後の空白・見出し・読み飛ばしは固定長と同じ道を通る
- 見本からの見当付け（区切りと列名）
- 古いマスタ（mode を持たない）はこれまでどおり固定長
- EXCEL の書き出し・取り込みで、読み方と項目番号が往復する
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import navi_text as T
import navi_book as B


def write(tmp,name,text,encoding='utf-8'):
 p=Path(tmp)/name;p.write_bytes(text.encode(encoding));return p


class Split(unittest.TestCase):
 def sp(self,**kw):return T.splitter(dict({'mode':'delimited'},**kw))

 def test_comma_with_quotes(self):
  f=self.sp(delimiter='comma')
  self.assertEqual(f('1,"x,y",3'),['1','x,y','3'])
  self.assertEqual(f('a,"he said ""hi""",'),['a','he said "hi"',''])
  # 囲みは値の頭にあるときだけ。途中の " は文字（5" のような寸法）
  self.assertEqual(f('5" pipe,2'),['5" pipe','2'])
  self.assertFalse(f.open('5" pipe,2'))
  self.assertTrue(f.open('a,"not closed'))

 def test_named_and_custom(self):
  self.assertEqual(self.sp(delimiter='tab')('a\tb\t'),['a','b',''])
  self.assertEqual(self.sp(delimiter='pipe')('a|b'),['a','b'])
  self.assertEqual(self.sp(delimiter='semicolon')('a;b'),['a','b'])
  # 文字を指定: 2文字以上でも、前後の空白込みでも、そのまま区切りになる
  self.assertEqual(self.sp(delimiter='custom',delimiter_text=' / ')('a / b/c / d'),['a','b/c','d'])
  self.assertEqual(self.sp(delimiter='custom',delimiter_text='::',quote='none')('a::"b::c"'),['a','"b','c"'])

 def test_collapse_and_regex(self):
  self.assertEqual(self.sp(delimiter='space',collapse=True,quote='none')('  a   b c '),['a','b','c'])
  self.assertEqual(self.sp(delimiter='space',quote='none')('a  b'),['a','','b'])
  self.assertEqual(self.sp(delimiter='regex',delimiter_text=r'\s*[;/]\s*')('a ; b/c'),['a','b','c'])


class Read(unittest.TestCase):
 def test_fields_types_header_and_multiline(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=write(tmp,'j.csv','番号,品名,数量,日付\r\nA1,"ボルト, M8", 0120 ,2026/10/01\r\nA2,"備考に\n改行",5,2026/10/02\r\n\r\nA3,ナット\r\n','cp932')
   lay={'name':'受注','mode':'delimited','delimiter':'comma','encoding':'cp932','header_row':True,
        'columns':[{'name':'日付','field':4,'type':'date','format':'YYYY/MM/DD'},{'name':'番号'},
                   {'name':'数量','field':3,'type':'integer'},{'name':'品名','field':2}]}
   self.assertEqual(T.validate_layout(lay),[])
   # field を書いていない列は並び順（2列目の「番号」は 2 番目）。ここでは明示して確かめる
   lay['columns'][1]['field']=1
   h,body,st=T.read_text_rows(p,lay)
   self.assertEqual(h,['日付','番号','数量','品名'])
   self.assertEqual(body,[['2026-10-01','A1','120','ボルト, M8'],['2026-10-02','A2','5','備考に\n改行'],['','A3','','ナット']])
   self.assertEqual(st['mode'],'delimited')
   self.assertEqual(st['short_rows'],1)            # A3 は項目が4つに足りない
   self.assertEqual(st['skipped_blank'],1)
   pv=T.preview_text(p,lay)
   self.assertTrue(pv['ok'])
   self.assertTrue(any('項目が4個に足りず' in n for n in pv['notes']),pv['notes'])

 def test_intermediate_csv(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=write(tmp,'k.txt','a|b|c\nd|e|f\n')
   lay={'name':'k','mode':'delimited','delimiter':'pipe','encoding':'utf-8','columns':[{'name':'X','field':3},{'name':'Y','field':1}]}
   n,cols,_st=T.write_intermediate_csv(p,lay,Path(tmp)/'out.csv')
   self.assertEqual((n,cols),(2,2))
   self.assertEqual((Path(tmp)/'out.csv').read_text(encoding='utf-8-sig').splitlines(),['X,Y','c,a','f,d'])


class Layout(unittest.TestCase):
 def test_old_layout_stays_fixed(self):
  l=T.normalize_layout({'name':'x','columns':[{'name':'a','start':1,'length':3}]})
  self.assertEqual(l['mode'],'fixed')
  self.assertEqual(T.layout_shape(l),'1列 / 3バイト')

 def test_shape_and_validate(self):
  base={'name':'x','mode':'delimited','columns':[{'name':'a'},{'name':'b','field':5}]}
  self.assertEqual(T.layout_shape(base),'2列 / カンマ区切り')
  self.assertEqual(T.layout_width(base),5)
  self.assertEqual(T.layout_gaps(base),[(2,4)])
  self.assertEqual(T.layout_shape(dict(base,delimiter='custom',delimiter_text='::')),'2列 / 「::」区切り')
  self.assertIn('区切りの文字を入れてください',T.validate_layout(dict(base,delimiter='custom')))
  self.assertTrue(any('読めません' in x for x in T.validate_layout(dict(base,delimiter='regex',delimiter_text='('))))
  self.assertTrue(any('空の文字にも当たります' in x for x in T.validate_layout(dict(base,delimiter='regex',delimiter_text=r'\s*'))))
  # 区切りでは長さ0を咎めない（長さは使わない）
  self.assertEqual(T.validate_layout(dict(base,columns=[{'name':'a','length':0}])),[])

 def test_sniff(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=write(tmp,'t.tsv','コード\t名前\t名前\n1\tA\tB\n2\tC\tD\n')
   g=T.sniff_delimited(p,{'header_row':True,'encoding':'utf-8'})
   self.assertTrue(g['ok'])
   self.assertEqual(g['delimiter'],'tab')
   self.assertEqual([c['name'] for c in g['columns']],['コード','名前','名前_2'])
   self.assertEqual([c['sample'] for c in g['columns']],['1','A','B'])
   q=write(tmp,'s.txt','A01   12.5   OK\nA02    3.0   NG\n')
   g=T.sniff_delimited(q,{'encoding':'utf-8'})
   self.assertEqual((g['delimiter'],g['collapse'],len(g['columns'])),('space',True,3))

 def test_export_json_roundtrip(self):
  lay={'name':'x','mode':'delimited','delimiter':'regex','delimiter_text':r'\s*;\s*','quote':'none','collapse':True,
       'columns':[{'name':'a','field':2}]}
  got,bad=T.layouts_import(T.layouts_export([lay]))
  self.assertEqual(bad,[])
  self.assertEqual({k:got[0][k] for k in ('mode','delimiter','delimiter_text','quote','collapse')},
                   {'mode':'delimited','delimiter':'regex','delimiter_text':r'\s*;\s*','quote':'none','collapse':True})
  self.assertEqual(got[0]['columns'][0]['field'],2)

 def test_xlsx_roundtrip(self):
  lays=[T.normalize_layout({'name':'区切りのもの','mode':'delimited','delimiter':'custom','delimiter_text':' / ',
                            'columns':[{'name':'a','field':3},{'name':'b','field':1}]}),
        T.normalize_layout({'name':'固定長のもの','columns':[{'name':'c','start':4,'length':2}]})]
  with tempfile.TemporaryDirectory() as tmp:
   dst=Path(tmp)/'m.xlsx'
   B.layouts_to_xlsx(lays,dst)
   got,bad=B.layouts_from_xlsx(dst)
   self.assertEqual(bad,[])
   d,f=(T.normalize_layout(x) for x in got)
   self.assertEqual((d['mode'],d['delimiter'],d['delimiter_text']),('delimited','custom',' / '))
   self.assertEqual([c['field'] for c in d['columns']],[3,1])
   self.assertEqual(f['mode'],'fixed')
   self.assertEqual((f['columns'][0]['start'],f['columns'][0]['length']),(4,2))


APP_CODE=r'''
import json,sys
from pathlib import Path
tmp=Path(sys.argv[2]).resolve();sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_paths,navi_textrun
copy=tmp/'pc'/'DataRelay';(copy/'data').mkdir(parents=True)
app.DATA_ROOT=Path(str(copy/'data'))
navi_paths.setup(app.DATA_ROOT,tmp/'local',copy,'pc')
src=tmp/'受注.csv';src.write_bytes('番号,品名,数量\r\nA1,"ボルト, M8",120\r\nA2,ナット,5\r\n'.encode('cp932'))
c=app.app.test_client();out={}
out['sniff']=c.post('/api/text-sniff',json={'path':str(src),'layout':{'header_row':True,'encoding':'cp932'}}).get_json()
cols=[{'name':x['name'],'field':x['field'],'type':'integer' if x['field']==3 else 'text'} for x in out['sniff']['columns']]
r=c.post('/api/text-layouts',json={'name':'受注CSV','mode':'delimited','delimiter':'comma','header_row':True,'encoding':'cp932','columns':cols})
out['save']=[r.status_code,r.get_json()]
lid=r.get_json()['layout']['id']
lst=c.get('/api/text-layouts').get_json()
out['item']={k:lst['items'][0][k] for k in ('mode','delimiter','quote','shape','width')}
out['meta']=[len(lst.get('modes') or []),len(lst.get('delimiters') or []),len(lst.get('quotes') or [])]
cfg=app.load()
cfg['jobs']=[{'id':'J1','name':'受注','enabled':True,'source':'text','text_path':str(src),'layout_id':lid,'rne':'','rne_path':'',
     'output_folder':str(tmp/'out'),'output_format':'csv','output_file':'受注.csv','table':'','sheet':'Page1',
     'type':'詳細データ','naming_mode':'fixed','schedules':[]}]
app.save(cfg);cfg=app.load()
out['run']=navi_textrun.run_one_local(dict(cfg['jobs'][0]),cfg,tmp/'work',tmp/'backup','manual',1,1)
f=tmp/'out'/'受注.csv'
out['csv']=f.read_text(encoding='utf-8-sig') if f.is_file() else None
x=c.get('/api/text-layouts/export?format=xlsx');out['xlsx']=x.status_code
r=c.post('/api/text-layouts/import?filename=m.xlsx',data=x.data,content_type='application/octet-stream')
out['reimport']=r.get_json()
out['after']={k:c.get('/api/text-layouts').get_json()['items'][0][k] for k in ('mode','delimiter','shape')}
# 登録内容の ZIP（共通設定の書き出し）でも往復する。対象から外してから消し、持ち込み直す
cfg=app.load();cfg['jobs']=[];app.save(cfg)
z=c.get('/api/bundle/export?parts=layouts');out['zip']=z.status_code
for x in c.get('/api/text-layouts').get_json()['items']:c.delete('/api/text-layouts/'+x['id'])
r=c.post('/api/bundle/import',data=z.data,content_type='application/zip');out['zip_import']=r.status_code
items=c.get('/api/text-layouts').get_json()['items']
out['zip_after']={k:items[0][k] for k in ('mode','delimiter','shape')} if items else None
print(json.dumps(out,ensure_ascii=False,default=str))
'''


class AppPath(unittest.TestCase):
 """受け口で保存・一覧・見当付けをし、入力がテキストの対象を実行して CSV ができるところまで。控えDBの読み方の列も往復する。"""
 @classmethod
 def setUpClass(cls):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'boot'),
            NAVI_CONFIG_DIR=str(Path(d)/'cfg'),PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',APP_CODE,str(ROOT),d],cwd=d,env=env,capture_output=True,text=True,
                    encoding='utf-8',timeout=240)
   if r.returncode!=0:raise AssertionError(r.stderr[-4000:])
   cls.o=json.loads(r.stdout.strip().splitlines()[-1])

 def test_saved_and_listed(self):
  o=self.o
  self.assertEqual(o['sniff']['delimiter'],'comma')
  self.assertEqual(o['save'][0],200,o['save'])
  self.assertEqual(o['item'],{'mode':'delimited','delimiter':'comma','quote':'double','shape':'3列 / カンマ区切り','width':3})
  self.assertEqual(o['meta'],[2,7,3])

 def test_run_to_csv(self):
  self.assertEqual(self.o['csv'].splitlines(),['番号,品名,数量','A1,"ボルト, M8",120','A2,ナット,5'],self.o['run'])

 def test_xlsx_reimport_keeps_mode(self):
  self.assertEqual(self.o['xlsx'],200)
  self.assertTrue(self.o['reimport']['ok'],self.o['reimport'])
  self.assertEqual(self.o['after'],{'mode':'delimited','delimiter':'comma','shape':'3列 / カンマ区切り'})

 def test_bundle_zip_keeps_mode(self):
  self.assertEqual((self.o['zip'],self.o['zip_import']),(200,200))
  self.assertEqual(self.o['zip_after'],{'mode':'delimited','delimiter':'comma','shape':'3列 / カンマ区切り'})


if __name__=='__main__':unittest.main()
