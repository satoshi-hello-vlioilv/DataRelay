"""テキストの読み取り（読取マスタの下読みと区切りの見当付け）が、Python（navi_text）と Rust（desktop/core の textread.rs）で
同じ答えになるか（2.26.0）。

- 文字コードの読み方（bytes.decode(enc, errors='replace')）を、cp932 は全部の2バイトの組と1バイト、ほかは乱数のバイト列で比べる
- 比べるルート: POST /api/text-preview・POST /api/text-sniff。業務のファイルで起きること（見出し・読み飛ばし・空行・終わりの印 0x1A・
  全角の途中で切れる列・型と型に読めない値・\r\n と \r の混じった改行・囲みの中の区切りと改行・連続をまとめる・BOM）を入れた見本で比べる
- Python でしか同じに決められない物（正規表現の区切り・euc_jp・float() が読むかもしれない字）は、Rust が Python へ回すことも確かめる
実行: python -m unittest tests.test_rust_text -v
"""
import json,os,random,subprocess,sys,unittest

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_writes import ASK,post  # noqa: E402
from test_rust_config import MAKE  # noqa: E402

NOW='2026-11-02T09:05:07.123456'

COL=lambda name,start,length,**k:dict(name=name,start=start,length=length,**k)


class TextReadParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,rust=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','rust'))

 def call(self,calls):
  r=subprocess.run([str(self.exe),'call'],input=''.join(json.dumps(c)+'\n' for c in calls),capture_output=True,text=True,encoding='utf-8',timeout=300)
  self.assertEqual(r.returncode,0,r.stderr)
  return [json.loads(x)['result'] for x in r.stdout.split('\n') if x.strip()]

 def test_decode_like_python(self):
  """cp932 は全部の1バイトと2バイトの組（先頭 0x81〜0x9F・0xE0〜0xFC）、ほかは乱数で、errors='replace' の読み方まで同じ。"""
  rnd=random.Random(11)
  fuzz=[bytes(rnd.choice([rnd.randrange(256),0x82,0xa0,0x81,0x20,0xe0,0xef,0xfc,0x0a]) for _ in range(rnd.randrange(1,14))) for _ in range(4000)]
  sets={'cp932':[bytes([c]) for c in range(256)]+[bytes([c,c2]) for c in [*range(0x81,0xa0),*range(0xe0,0xfd)] for c2 in range(256)]+fuzz,
        'utf-8':[bytes([c]) for c in range(256)]+fuzz,'utf-8-sig':[b'\xef\xbb\xbfa\xef\xbb\xbf']+fuzz,'latin-1':fuzz}
  for enc,bs in sets.items():
   rs=self.call([{'fn':'decode','args':{'enc':enc,'hex':b.hex()}} for b in bs])
   bad=[(b.hex(),b.decode(enc,errors='replace'),x) for b,x in zip(bs,rs) if b.decode(enc,errors='replace')!=x]
   self.assertEqual(bad,[],f'{enc}: {len(bad)}件違う')
  self.assertEqual(self.call([{'fn':'decode','args':{'enc':e,'hex':'41'}} for e in ('euc_jp','shift_jis','utf-16')]),['pass']*3)

 def files(self):
  d=self.t/'texts';d.mkdir(exist_ok=True)
  sj=lambda s:s.encode('cp932')
  fixed=b'\r\n'.join([sj('ヘッダーの説明行'),sj('コード名前　　　数量日付    日時          '),
                      sj('A001受注一覧　　0012320260105202601050930  '),sj('A002出荷　　　　00045-20261301202602280000  '),
                      b'',sj('A003在庫ﾊﾝｶｸ  1,2002026/1/52026022812345'),sj('A00'),b'\x1a\x1a',sj('末尾1'),sj('末尾2')])+b'\r\n\x1a'
  (d/'fixed.txt').write_bytes(fixed)
  (d/'chars.txt').write_bytes('名前あいう|12\r\n二行目えお\r三行目かきくけこさ|3\n\n  \n年月2026年01月02日'.encode('utf-8'))
  csv='コード,名前,メモ\r\n1,"東京, 本社","改行\r\nあり"\r\n2,"大阪 ""支店""",x\r\n3,,\r\n4,"閉じない\r\n'
  (d/'data.csv').write_bytes(csv.encode('cp932'))
  (d/'tab.tsv').write_bytes('品番\t品名\t品名\t数\nA\tねじ\tM3\t10\nB\tナット\tM3\t20\nC\t座金\t\t5\n'.encode('utf-8'))
  (d/'semi.txt').write_bytes('a;b;c\n1;2;3\n4;5;6\n9;9;9\n7;8\n'.encode('utf-8'))
  (d/'space.txt').write_bytes('品番   名前     数\nA1     ねじ     10\nB22    ナット   200\n'.encode('cp932'))
  (d/'pipe.txt').write_bytes('x | y | z\n1 | 2 | 3\n'.encode('utf-8'))
  (d/'bom.txt').write_bytes(b'\xef\xbb\xbf'+'ABあ12\nCDい34\n'.encode('utf-8'))
  (d/'tie.txt').write_bytes('a,b\nc,d,e\n'.encode('utf-8'))
  return d

 def test_preview_and_sniff(self):
  self.py(MAKE,'tx',json.dumps({'cfg':{'jobs':[]}}))
  d=self.files()
  f=lambda n:str(d/n)
  fixed=dict(encoding='cp932',unit='byte',skip_head=1,skip_tail=2,header_row=True,skip_blank=True,
             columns=[COL('コード',1,4),COL('名前',5,12),COL('数量',17,6,type='real',scale=2),COL('日付',23,8,type='date'),
                      COL('日時',31,12,type='datetime',format='YYYYMMDDHHMI'),COL('切れ目',6,2)])
  reqs=[
   post('/api/text-preview',{'layout':fixed,'path':f('fixed.txt'),'lines':50}),
   post('/api/text-preview',{'layout':dict(fixed,skip_tail=0,header_row=False,skip_blank=False,trim='none'),'path':f('fixed.txt'),'lines':'3'}),
   post('/api/text-preview',{'layout':dict(fixed,columns=fixed['columns'][:2]+[COL('数量',17,6,type='integer'),COL('日付',23,8,type='date',format='YYYY/M/D')]),'path':f('fixed.txt')}),
   post('/api/text-preview',{'layout':{'encoding':'utf-8','unit':'char','trim':'right','columns':[COL('名',1,5),COL('残り',6,30),COL('年',3,10,type='date',format='YYYY年MM月DD日')]},'path':f('chars.txt'),'lines':0}),
   post('/api/text-preview',{'layout':{'mode':'delimited','encoding':'cp932','header_row':True,'columns':[{'name':'名前','field':2},{'name':'メモ','field':3},{'name':'無い','field':9}]},'path':f('data.csv')}),
   post('/api/text-preview',{'layout':{'mode':'delimited','delimiter':'custom','delimiter_text':' | ','quote':'none','encoding':'utf-8','columns':[{'name':'z','field':3},{'name':'x'}]},'path':f('pipe.txt')}),
   post('/api/text-preview',{'layout':{'mode':'delimited','delimiter':'space','collapse':True,'encoding':'cp932','columns':[{'name':'a'},{'name':'b'},{'name':'c','type':'integer'}]},'path':f('space.txt')}),
   post('/api/text-preview',{'layout':{'encoding':'utf-8-sig','unit':'byte','columns':[COL('a',1,2),COL('b',3,3),COL('c',6,2,type='integer')]},'path':f('bom.txt')}),
   post('/api/text-preview',{'layout':{'encoding':'cp932','columns':[COL('a',1,0)]},'path':f('fixed.txt')}),       # 長さ0 → 確かめで断る
   post('/api/text-preview',{'layout':{'encoding':'cp932','columns':[COL('a',1,2)]},'path':f('無い.txt')}),
   post('/api/text-preview',{'layout':{'encoding':'cp932','columns':[COL('a',1,2)]},'path':'相対の名前.txt'}),
   post('/api/text-preview',{'layout':{'columns':[COL('a',1,2)]}}),
   post('/api/text-preview',{'layout':{'sample_path':f('fixed.txt'),'columns':[COL('a',1,4)]}}),
   post('/api/text-sniff',{'layout':{'encoding':'utf-8','header_row':True},'path':f('tab.tsv')}),
   post('/api/text-sniff',{'layout':{'encoding':'utf-8'},'path':f('semi.txt')}),
   post('/api/text-sniff',{'layout':{'encoding':'cp932','header_row':True},'path':f('space.txt')}),
   post('/api/text-sniff',{'layout':{'encoding':'cp932','header_row':True},'path':f('data.csv')}),
   post('/api/text-sniff',{'layout':{'encoding':'utf-8','delimiter':'custom','delimiter_text':' | '},'path':f('pipe.txt')}),
   post('/api/text-sniff',{'layout':{'encoding':'cp932','skip_head':99},'path':f('data.csv')}),
   post('/api/text-sniff',{'layout':{},'path':f('無い.txt')}),
   post('/api/text-sniff',{'layout':{}}),
  ]
  py=self.py(ASK,'tx',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('tx',reqs)
  for q,p,x in zip(reqs,py,rs):
   what=q['path']+' '+q['body'][:160]
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {what}')
   a,b=json.loads(p['body']),json.loads(x['body'])
   if a!=b:
    diff={k:(a.get(k),b.get(k)) for k in set(a)|set(b) if a.get(k)!=b.get(k)}
    self.fail(f'{what}\n{json.dumps(diff,ensure_ascii=False)[:2000]}')
   self.assertEqual(x['status'],p['status'],what)
  # 見本が中身を持っていること（空どうしを比べて合格にしない）
  first=json.loads(py[0]['body'])
  self.assertTrue(first['ok'] and first['rows'] and first['stat']['broken_cells'] and first['stat']['type_errors'] and first['stat']['skipped_junk'],first)
  self.assertEqual([json.loads(p['body'])['ok'] for p in py[13:18]],[True]*5)
  self.assertEqual({json.loads(p['body'])['delimiter'] for p in py[13:16]},{'tab','semicolon','space'})

 def test_random_layouts(self):
  """乱数で作った読取マスタとファイル（300組）で、下読みの答えが同じ。Rust が回した物は数えて、半分より多くは回さないことも見る。"""
  self.py(MAKE,'tr',json.dumps({'cfg':{'jobs':[]}}))
  d=self.t/'rand';d.mkdir(exist_ok=True)
  rnd=random.Random(5)
  pieces=['A','b','1','23','0045','-','+',',','.',' ','　','"','|',';','\t','あ','ｱ','漢字','2026','0105','\x1a','\x00','','1e3','ー']
  reqs=[]
  for i in range(300):
   enc=rnd.choice(['cp932','utf-8','utf-8-sig'])
   lines=[''.join(rnd.choice(pieces) for _ in range(rnd.randrange(0,14))) for _ in range(rnd.randrange(1,9))]
   nl=rnd.choice(['\n','\r\n','\r'])
   raw=nl.join(lines).encode(enc,errors='replace')
   if rnd.random()<.2:raw+=bytes([rnd.choice([0x82,0x81,0xe0,0xff])])
   p=d/f'r{i}.txt';p.write_bytes(raw)
   mode=rnd.choice(['fixed','delimited'])
   types=['text','text','integer','numeric','real','date','datetime']
   cols=[]
   for k in range(rnd.randrange(1,5)):
    t=rnd.choice(types)
    c={'name':f'c{k}','start':rnd.randrange(1,10),'length':rnd.randrange(1,8),'field':rnd.randrange(1,5),'type':t}
    if t=='real':c['scale']=rnd.randrange(0,4)
    if t in('date','datetime'):c['format']=rnd.choice(['YYYYMMDD','YYMMDD','YYYY/MM/DD','YYYY年MM月DD日','YYYYMMDDHHMI'])
    cols.append(c)
   lay={'encoding':enc,'unit':rnd.choice(['char','byte']),'mode':mode,'trim':rnd.choice(['both','right','left','none']),
        'delimiter':rnd.choice(['comma','tab','semicolon','pipe','space','custom']),'delimiter_text':rnd.choice([' | ','ー','"',',,']),
        'quote':rnd.choice(['double','single','none']),'collapse':rnd.random()<.3,'skip_head':rnd.randrange(0,3),'skip_tail':rnd.randrange(0,3),
        'skip_blank':rnd.random()<.6,'header_row':rnd.random()<.3,'columns':cols}
   reqs.append(post('/api/text-preview',{'layout':lay,'path':str(p),'lines':rnd.randrange(1,20)}))
   reqs.append(post('/api/text-sniff',{'layout':lay,'path':str(p)}))
  py=self.py(ASK,'tr',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('tr',reqs)
  passed=0
  for q,p,x in zip(reqs,py,rs):
   if x['status']==0:passed+=1;continue
   a,b=json.loads(p['body']),json.loads(x['body'])
   if (p['status'],a)!=(x['status'],b):
    diff={k:(a.get(k),b.get(k)) for k in set(a)|set(b) if a.get(k)!=b.get(k)}
    self.fail(f'{q["path"]} {q["body"][:400]}\n{p["status"]} {x["status"]} {json.dumps(diff,ensure_ascii=False)[:1500]}')
  print(f'\n  乱数の下読み: {len(reqs)} 件（Python へ回した {passed}）');self.assertLess(passed,len(reqs)//2,f'{passed}件を Python へ回した（多すぎる）')

 def test_sign_only_number_is_not_a_crash(self):
  """数の列の値が符号だけ（「-」「+,」）でも落ちない。以前は IndexError で下読みも実行も止まっていた（2.26.0 で直した）。"""
  sys.path[:0]=[str(test_rust_save.ROOT/'lib')]
  from navi_text import _to_number
  self.assertEqual([_to_number(v,0,i) for v in ('-','+,',' - ') for i in (True,False)],[None]*6)
  self.assertEqual(_to_number('12-',0,True),'-12')

 def test_python_only_cases(self):
  """正規表現の区切り・euc_jp・数でない行数・float() が読むかもしれない字・見当付けで最も多い数が並ぶ場合は、Python へ回す。"""
  self.py(MAKE,'tp',json.dumps({'cfg':{'jobs':[]}}))
  d=self.files()
  reqs=[post('/api/text-preview',{'layout':{'mode':'delimited','delimiter':'regex','delimiter_text':r'\s+','columns':[{'name':'a'}]},'path':str(d/'space.txt')}),
        post('/api/text-preview',{'layout':{'encoding':'euc_jp','columns':[COL('a',1,2)]},'path':str(d/'fixed.txt')}),
        post('/api/text-preview',{'layout':{'encoding':'cp932','columns':[COL('a',1,2)]},'path':str(d/'fixed.txt'),'lines':'x'}),
        post('/api/text-preview',{'layout':{'mode':'delimited','encoding':'utf-8','delimiter':'semicolon','columns':[{'name':'n','type':'numeric'}]},'path':str(self.sci(d))}),
        post('/api/text-sniff',{'layout':{'encoding':'utf-8'},'path':str(d/'tie.txt')}),
        post('/api/text-preview','[1]')]
  self.assertEqual([x['status'] for x in self.rust('tp',reqs)],[0]*len(reqs))

 def sci(self,d):
  p=d/'sci.txt';p.write_bytes(b'1e5\n2\n');return p


if __name__=='__main__':unittest.main()
