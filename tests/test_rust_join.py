"""結合マスタの組み立てを助ける受け口のうち、設定から答える物が、Python（navi_web・navi_joinrun・navi_order・navi_localcopy）と
Rust（desktop/core の joinplan.rs）で同じ答えになるか（2.27.0）。

比べるルート: GET /api/join-candidates・POST /api/join-order・POST /api/join-cache/clear、POST /api/join-source（2.30.0。joinplan.rs・localcopy.sample）、
POST /api/join-keys・POST /api/join-preview（2.31.0。joinrun.rs）
見本の設定: 決まった名前で出す対象（追加の形式つき）・名前を型で作る対象（今日の名前のファイルがある）・出力先を共通の既定から取る対象
（前回の実行の記録に別の名前のファイルが残っている）・相対の出力先・結合マスタ（自分の対象が作るファイル・読取フォルダーの名前だけの指定・無いファイル）。
写しの置き場（work\\read-cache）には、写し・控えの .json・フォルダーを置いて、数え方と消し方を比べる。
POST /api/join-source は、CSV（cp932・先頭だけ写す 4MB 超・囲みの中の改行で切り戻す・1行が長すぎて写せない）・TXT・SQLite3（表の選び方・_ で始まる表・
表の無い物）・固定長と区切りのテキスト（読取マスタ）・読めない文字コード・無いファイル・無い読取マスタで比べ、2回目は写しを使い回すこと、
写しの名前が Python と同じことも比べる。EXCEL・ACCESS は Python へ回す。
POST /api/join-keys・POST /api/join-preview は、明細と台帳（2,000 行を超える・右に同じキーが2つ）・SQLite3 の3つ目（鎖の前のほうの列をキーにする）・
固定長の読取マスタ・出す列の指定（別名・無い列）・一致しないキー・右に無い列（SQLite の断り）・大文字小文字だけ違う列（SQLite の断り）・
空のファイル・読めない文字コード・無いファイル・ファイルが1つ・つなぎ目の番号の外・行数の上限で比べる。
実行: python -m unittest tests.test_rust_join -v
"""
import json,os,shutil,sqlite3,subprocess,sys,unittest
from contextlib import closing

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_writes import ASK,LAYOUT,DELIM,post  # noqa: E402
from test_rust_config import MAKE  # noqa: E402
from test_rust_parity import ROOT  # noqa: E402

NOW='2026-11-02T09:05:07.123456'


def get(path):return {'method':'GET','path':path,'body':''}


class JoinPlanParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,rust,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','rust','twin'))

 def make(self,name,settings=None):
  a=self.t/'outA';b=self.t/'outB';a.mkdir(exist_ok=True);b.mkdir(exist_ok=True)
  for p,t in ((a/'a.csv',1767225600),(a/'日次_20261102.sqlite3',1767312000),(b/'old.txt',1767398400),(b/'在庫.csv',1767225600)):
   p.write_bytes(b'x'*7);os.utime(p,(t,t))
  cfg={'default_output_folder':str(b),'text_folder':str(b),'settings':dict({'join_wait_lookahead_seconds':'30','join_wait_poll_seconds':0},**(settings or {})),
       'jobs':[
        {'id':'j1','name':'受注','output_folder':str(a),'output_format':'csv','output_file':'a.csv','extra_formats':['xlsx'],'naming_mode':'fixed','enabled':True},
        {'id':'j2','name':'日次','output_folder':str(a),'output_format':'sqlite','naming_mode':'template','output_pattern':'{name}_{now:YYYYMMDD}','enabled':False},
        {'id':'j3','name':'在庫','output_folder':'','output_format':'txt','output_file':'b.txt'},
        {'id':'j4','name':'相対','output_folder':'.\\out','output_format':'xlsx','output_file':'r.xlsx'},
       ]}
  recipe=['INSERT INTO join_recipes (id,display_order,name,description,sources_json,joins_json,columns_json,updated_at) VALUES(?,?,?,?,?,?,?,?)',
          ['R1',0,'受注と在庫','',json.dumps([{'path':str(a/'a.csv')},{'path':'在庫.csv'},{'path':'無い.csv','format':'txt'},{'path':''}]),'[]','[]','t']]
  runs=["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j3','在庫','t','ok','manual','',1,1,'old.txt','t','')",[]]
  self.py(MAKE,name,json.dumps({'cfg':cfg,'sql':[recipe,runs]},ensure_ascii=False))
  cache=self.t/name/'local'/'work'/'read-cache';cache.mkdir(parents=True,exist_ok=True)
  (cache/'0123456789abcdef.csv').write_bytes(b'12345');(cache/'fedcba9876543210.json').write_bytes(b'{}');(cache/'sub').mkdir(exist_ok=True)
  return a,b

 def test_candidates_order_and_cache(self):
  a,_b=self.make('jbase');self.twin('jbase','jpy','jrs')
  reqs=[get('/api/join-candidates'),
        post('/api/join-order',{'recipe':{'sources':[{'path':str(a/'a.csv')},{'path':'在庫.csv'},{'path':str(a/'日次_20261102.sqlite3')},{'path':str(a/'a.xlsx')},{'path':''},{'path':'無い.csv'}]}}),
        post('/api/join-order',{}),
        post('/api/join-order','null'),
        post('/api/join-cache/clear',{}),
        get('/api/join-candidates')]
  py=self.py(ASK,'jpy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('jrs',reqs)
  for q,p,x in zip(reqs,py,rs):
   what=f'{q["method"]} {q["path"]} {q.get("body","")[:100]}'
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {what}')
   # 写しの置き場（jpy・jrs）の中を指す道は、置き場の名前だけ同じ字に直して比べる（相対の出力先・写しの置き場）
   a1,b1=(json.loads(t.replace('/jpy/','/J/').replace('/jrs/','/J/').replace('\\\\jpy\\\\','\\\\J\\\\').replace('\\\\jrs\\\\','\\\\J\\\\')) for t in (p['body'],x['body']))
   self.assertEqual((x["status"],b1),(p["status"],a1),what)
  first=json.loads(py[0]['body']);order=json.loads(py[1]['body'])
  # 見本が中身を持っていること
  self.assertGreaterEqual(len(first['items']),6);self.assertTrue(any(i['exists'] for i in first['items']) and any(i['role']=='recipe' for i in first['items']))
  self.assertEqual(first['cache']['count'],1)
  self.assertEqual(order['made_count'],3);self.assertEqual(order['wait'],{'enabled':True,'lookahead':30,'max_wait':600,'poll':5})
  self.assertEqual(json.loads(py[4]['body'])['removed'],2,'写しと控えを消し、フォルダーは消さない')

 def test_job_dependencies(self):
  """材料の関係（navi_orderrun.job_dependencies と joinplan::dependencies。2.39.0）。黒板が、どの対象を先に流すかを決めるのに使う。
  クエリの対象（M の式を読む）が入っていれば、段 6 までは Python へ回す。"""
  a=self.t/'depA';b=self.t/'depB';a.mkdir(exist_ok=True);b.mkdir(exist_ok=True);(b/'old.txt').write_bytes(b'x')
  cfg={'default_output_folder':str(b),'text_folder':str(b),
       'jobs':[{'id':'j1','name':'受注','output_folder':str(a),'output_format':'csv','output_file':'a.csv','extra_formats':['xlsx'],'naming_mode':'fixed'},
               {'id':'j2','name':'日次','output_folder':str(a),'output_format':'sqlite','naming_mode':'template','output_pattern':'{name}_固定'},
               {'id':'j3','name':'在庫','output_folder':'','output_format':'txt','output_file':'b.txt'},
               {'id':'j5','name':'結合1','source':'join','recipe_id':'R1','output_folder':str(a),'output_format':'csv','output_file':'結合1.csv','naming_mode':'fixed'},
               {'id':'j6','name':'結合2','source':'join','recipe_id':' R2 ','output_folder':str(b),'output_format':'csv','output_file':'結合2.csv','naming_mode':'fixed'},
               {'id':'j7','name':'無いマスタ','source':'join','recipe_id':'R9','output_file':'n.csv'},
               {'id':'j8','name':'マスタなし','source':'join','recipe_id':'','output_file':'m.csv'},
               {'id':'j9','name':'テキスト','source':'text','output_file':'t.csv'},
               {'id':'jm','name':'クエリ','source':'mquery','query_id':'Q1','output_file':'q.csv'}]}
  def recipe(rid,sources):
   return ['INSERT INTO join_recipes (id,display_order,name,description,sources_json,joins_json,columns_json,updated_at) VALUES(?,?,?,?,?,?,?,?)',
           [rid,0,rid,'',json.dumps(sources,ensure_ascii=False),'[]','[]','t']]
  sql=[recipe('R1',[{'path':str(a/'a.csv')},{'path':'old.txt'},{'path':str(a/'A.XLSX')},{'path':str(a/'結合1.csv')},{'path':'無い.csv'},{'path':''}]),
       recipe('R2',[{'path':str(a/'日次_固定.sqlite3')},{'path':str(a/'結合1.csv')},{'path':str(b/'b.txt')}]),
       ["INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) VALUES('j3','在庫','t','ok','manual','',1,1,'old.txt','t','')",[]]]
  self.py(MAKE,'depbase',json.dumps({'cfg':cfg,'sql':sql},ensure_ascii=False))
  code=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_orderrun
a=json.loads(sys.stdin.read());c=app.load();out=[]
for ids in a:
 jobs=[j for j in c['jobs'] if not ids or j['id'] in ids]
 out.append({k:sorted(v) for k,v in navi_orderrun.job_dependencies(jobs,c).items()})
print(json.dumps(out,ensure_ascii=False))
"""
  asks=[['j1','j2','j3','j5','j6','j7','j8','j9'],['j6'],[]]
  py=self.py(code,'depbase',json.dumps(asks),NOW)
  r=subprocess.run([str(self.exe),'call'],input=''.join(json.dumps({'fn':'job_dependencies','args':{'base':str(ROOT),'ids':i}})+'\n' for i in asks),
                   env=dict(self.env('depbase'),DATARELAY_FIXED_NOW=NOW),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  rs=[json.loads(x)['result'] for x in r.stdout.splitlines() if x.strip()]
  self.assertEqual(rs[:2],py[:2])
  self.assertEqual(rs[2],{'pass':True},'クエリの対象が入っていれば Python へ回す')
  want={'j1':[],'j2':[],'j3':[],'j5':['j1','j3'],'j6':['j2','j3','j5'],'j7':[],'j8':[],'j9':[]}
  self.assertEqual(py[0],want,'大文字小文字だけ違う材料も作り手にたどり着く。自分の出力は数えない')

 def sources(self):
  o=self.t/'src';o.mkdir(exist_ok=True)
  (o/'受注.csv').write_bytes('コード,名前,メモ\r\n1,"東京, 本社","改行\r\nあり"\r\n2,大阪,\r\n3,名古屋\r\n4,福岡\r\n'.encode('cp932'))
  # 4MB の切れ目を、囲みの中の改行がまたぐようにする（切れ目の前の改行は囲みの中なので、もう1行戻して切る）
  cut=4*1024*1024;parts=[b'k,v\n'];n=4;i=0
  while n<cut-20:parts.append(b'%d,"value %d"\n'%(i,i));n+=len(parts[-1]);i+=1
  head=b''.join(parts);self.big_head=len(head)
  big=head+b'9,"'+b'y'*10+b'\n'+b'z'*40+b'"\n'+b''.join(b'%d,"v"\n'%i for i in range(50000))
  (o/'大きい.csv').write_bytes(big)
  (o/'長い1行.CSV').write_bytes(b','.join(b'x'*1000 for _ in range(5200)))   # 改行の無い 5MB（1欄は csv の上限より短い）
  (o/'tab.txt').write_bytes('品番\t数\nA\t10\nB\t20\n'.encode('utf-8'))
  (o/'bad.csv').write_bytes(b'\x81\x20\xff\n')
  (o/'固定.txt').write_bytes(('\n\n'+'20261101'+'2026/11/01 09:05'+' '*5+'1.5  '+'  12\n').encode('cp932'))
  (o/'区切り.dat').write_bytes('a | b | c | d | e\n1 | 2 | 3 | 4 | 5\n'.encode('utf-8'))
  for n,tables in (('在庫.SQLITE3',('在庫','_更新情報','_隠し','b別表')),('空.sqlite3',('_更新情報',))):
   db=o/n
   if db.exists():db.unlink()
   with closing(sqlite3.connect(str(db))) as c,c:
    for t in tables:c.execute(f'CREATE TABLE "{t}" (品番 TEXT, 数 INTEGER)')
    if '在庫' in tables:c.executemany('INSERT INTO "在庫" VALUES(?,?)',[('A',1),('B',None),('C',3),('D',4)])
  return o

 def test_join_source(self):
  o=self.sources()
  self.make('sbase')
  self.py(ASK,'sbase',json.dumps([post('/api/text-layouts',dict(LAYOUT,id='L1')),post('/api/text-layouts',dict(DELIM,id='L2'))],ensure_ascii=False),NOW)
  self.twin('sbase','spy','srs')
  src=lambda **k:post('/api/join-source',k)
  reqs=[src(path=str(o/'受注.csv')),src(path=str(o/'受注.csv')),src(path=' '+str(o/'大きい.csv')+' ',format=' CSV '),src(path=str(o/'長い1行.CSV')),
        src(path=str(o/'tab.txt')),src(path=str(o/'tab.txt'),format='csv'),src(path=str(o/'在庫.SQLITE3')),src(path=str(o/'在庫.SQLITE3'),table='b別表'),
        src(path=str(o/'在庫.SQLITE3'),format='sqlite',table='無い'),src(path=str(o/'空.sqlite3')),src(path=str(o/'bad.csv')),
        src(path=str(o/'固定.txt'),format='fixed',layout_id=' L1 '),src(path=str(o/'区切り.dat'),format='FIXED',layout_id='L2'),
        src(path=str(o/'固定.txt'),format='fixed',layout_id='無い'),src(path=str(o/'固定.txt'),format='fixed'),src(path=str(o/'無い.txt'),format='fixed',layout_id='L1'),
        src(path=str(o/'無い.csv')),src(path=''),src(),post('/api/join-source','null'),src(path='tab.txt'),src(path=str(o/'大きい.csv'))]
  py=self.py(ASK,'spy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('srs',reqs)
  def same(body):
   d=json.loads(body.replace('/spy/','/S/').replace('/srs/','/S/').replace('\\\\spy\\\\','\\\\S\\\\').replace('\\\\srs\\\\','\\\\S\\\\'))
   if isinstance(d.get('copy'),dict) and 'elapsed' in d['copy']:d['copy']['elapsed']=0   # 写すのにかかった秒は毎回違う
   return d
  for q,p,x in zip(reqs,py,rs):
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {q["body"]}')
   self.assertEqual((x['status'],same(x['body'])),(p['status'],same(p['body'])),q['body'])
  b=[json.loads(p['body']) for p in py]
  # 見本が中身を持っていること
  self.assertEqual((b[0]['rows'],b[0]['copy']['cached'],b[1]['copy']['cached']),(4,False,True))
  self.assertTrue(b[2]['partial'] and b[2]['copy']['mode']=='prefix' and b[2]['copy']['bytes']==self.big_head,b[2]['copy'])
  self.assertEqual(b[3]['copy']['note'][:6],'1行も切り出');self.assertEqual(b[6]['tables'],['b別表','在庫'])
  self.assertEqual([b[i]['ok'] for i in (11,12)],[True,True]);self.assertEqual(b[10]['error'],'読み取れませんでした: 文字コードを判定できません')
  self.assertEqual(b[9]['error'],'読み取れませんでした: 表示できるテーブルがありません')
  # 写しの名前が同じ（どちらが写しても使い回せる）
  names=[sorted(os.listdir(self.t/n/'local'/'work'/'read-cache')) for n in ('spy','srs')]
  self.assertEqual(names[0],names[1]);self.assertGreaterEqual(len(names[0]),12)
  again=self.py(ASK,'srs',json.dumps([src(path=str(o/'受注.csv'))],ensure_ascii=False),NOW)[0]
  self.assertTrue(json.loads(again['body'])['copy']['cached'],'Rust の写しを Python が使い回す')

 def join_sources(self):
  o=self.sources()
  rows=['受注番号,品番,数量']+[f'O{i:05d},P{i%50+1:03d},{i%9+1}' for i in range(2500)]
  (o/'明細.csv').write_bytes(('\r\n'.join(rows)+'\r\n').encode('cp932'))
  led=['ITEM_CD,品名,単価']+[f'P{i:03d},品{i},{100+i*7}' for i in range(1,81)]+['P003,品3の別名,999']
  (o/'台帳.csv').write_bytes(('\n'.join(led)+'\n').encode('utf-8-sig'))
  (o/'大小.csv').write_bytes(b'a,A\n1,2\n')
  (o/'空.csv').write_bytes(b'')
  db=o/'倉庫.sqlite3'
  if db.exists():db.unlink()
  with closing(sqlite3.connect(str(db))) as c,c:
   c.execute('CREATE TABLE "倉庫" (品番 TEXT, 棚 TEXT, 数 INTEGER)')
   c.executemany('INSERT INTO "倉庫" VALUES(?,?,?)',[(f'P{i:03d}',f'棚{i%4}',i) for i in range(1,40,2)])
  return o

 def test_join_keys_and_preview(self):
  o=self.join_sources()
  self.make('kbase')
  self.py(ASK,'kbase',json.dumps([post('/api/text-layouts',dict(DELIM,id='L2'))],ensure_ascii=False),NOW)
  self.twin('kbase','kpy','krs')
  A={'path':str(o/'明細.csv')};B={'path':str(o/'台帳.csv')};C={'path':str(o/'倉庫.sqlite3'),'table':'倉庫'}
  k=lambda l,r,t='inner':{'type':t,'keys':[{'left':l,'right':r}]}
  rec=lambda srcs,joins,**x:dict({'name':'','sources':srcs,'joins':joins},**x)
  keys=lambda r,**x:post('/api/join-keys',dict({'recipe':r},**x))
  pre=lambda r,**x:post('/api/join-preview',dict({'recipe':r},**x))
  reqs=[keys(rec([A,B],[])),keys(rec([A,B,C],[]),index=1),keys(rec([A,B,C],[]),index='1',limit=1),keys(rec([A,B],[]),index=5),
        keys(rec([A,{'path':str(o/'無い.csv')}],[])),keys(rec([B,{'path':str(o/'bad.csv')}],[])),keys(rec([{'path':str(o/'受注.csv')},{'path':str(o/'大きい.csv')}],[])),
        keys(rec([A,{'path':str(o/'区切り.dat'),'format':'fixed','layout_id':'L2'}],[])),keys({}),post('/api/join-keys','null'),
        pre(rec([A,B],[k('品番','ITEM_CD')])),pre(rec([A,B],[k('品番','ITEM_CD','left')],name='名前つき',columns=[{'source':'A','name':'受注番号'},{'source':'B','name':'品名','as':'名前'},{'source':'B','name':'無い列'},{'source':'Z','name':'数量'}]),lines=3),
        pre(rec([A,B,C],[k('品番','ITEM_CD'),k('品番','品番','left')]),lines=500),pre(rec([A,B],[k('数量','ITEM_CD')])),pre(rec([A,B],[k('品番','無い列')])),
        pre(rec([A,{'path':str(o/'大小.csv')}],[k('品番','a')])),pre(rec([A,{'path':str(o/'空.csv')}],[k('品番','x')])),pre(rec([A,{'path':str(o/'bad.csv')}],[k('品番','x')])),
        pre(rec([A,{'path':str(o/'無い.csv')}],[k('品番','x')])),pre(rec([A],[])),pre(rec([A,B],[{'type':'left','keys':[]}])),
        pre(rec([B,{'path':str(o/'区切り.dat'),'format':'fixed','layout_id':'L2'}],[k('ITEM_CD','x')])),pre(rec([B,{'path':str(o/'区切り.dat'),'format':'fixed','layout_id':'無い'}],[k('ITEM_CD','a')])),
        pre(rec([{'path':str(o/'受注.csv')},{'path':str(o/'大きい.csv')}],[k('コード','k')])),pre(rec([A,B],[k('品番','ITEM_CD')]),lines='2'),pre({}),
        pre(rec([A,B],[k('品番','ITEM_CD')],columns=[{'name':'無い'}]))]
  py=self.py(ASK,'kpy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('krs',reqs)
  def same(body):
   d=json.loads(body.replace('/kpy/','/K/').replace('/krs/','/K/').replace('\\\\kpy\\\\','\\\\K\\\\').replace('\\\\krs\\\\','\\\\K\\\\'))
   for x in d.get('copies') or []:x['elapsed']=0   # 写すのにかかった秒は毎回違う
   return d
  for q,p,x in zip(reqs,py,rs):
   what=f'{q["path"]} {q["body"][:200]}'
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {what}')
   self.assertEqual((x['status'],same(x['body'])),(p['status'],same(p['body'])),what)
  b=[json.loads(p['body']) for p in py]
  # 見本が中身を持っていること
  self.assertEqual((b[0]['items'][0]['left'],b[0]['items'][0]['right'],b[0]['items'][0]['score'],b[0]['sampled']),('品番','ITEM_CD',1.0,True))
  self.assertFalse(b[0]['items'][0]['unique'])
  self.assertEqual(b[1]['items'][0]['right'],'品番');self.assertEqual(len(b[2]['items']),1)
  self.assertEqual([py[i]['status'] for i in (3,4,5)],[400,400,400])
  self.assertTrue(b[10]['ok'] and b[10]['partial'] and b[10]['stats']['rows']>2000 and b[10]['stats']['joins'][0]['paired']>b[10]['stats']['joins'][0]['both'])
  self.assertEqual(b[11]['headers'],['受注番号','名前','数量']);self.assertEqual(len(b[11]['rows']),3)
  self.assertEqual(len(b[12]['rows']),200);self.assertEqual(b[13]['stats']['joins'][0]['both'],0)
  self.assertIn('no such column',b[14]['error']);self.assertIn('duplicate column',b[15]['error'])
  self.assertIn('に列がありません',b[16]['error']);self.assertTrue(b[21]['ok'],b[21])
  self.assertTrue(any('ローカルへ写した先頭だけ' in n for n in b[23]['notes']))

 def test_python_only_cases(self):
  """待つ設定・行数が int() で読めない値（Python は落ちる）・辞書でない本文・EXCEL と ACCESS の材料・「どちらも全部残す」は、Python へ回す。"""
  self.make('jbad',settings={'join_wait_max_seconds':'abc'})
  rs=self.rust('jbad',[post('/api/join-order',{'recipe':{}}),post('/api/join-order','[1]'),post('/api/join-order',{'recipe':[1]})])
  self.assertEqual([x['status'] for x in rs],[0,0,0])
  # EXCEL・ACCESS は写す前に Python へ回す（写しを2度作らない）
  o=self.t/'src';o.mkdir(exist_ok=True);(o/'表.xlsx').write_bytes(b'PK');(o/'表.accdb').write_bytes(b'x')
  rs=self.rust('jbad',[post('/api/join-source',{'path':str(o/'表.xlsx')}),post('/api/join-source',{'path':str(o/'表.accdb')}),
                       post('/api/join-source',{'path':str(o/'表.accdb'),'format':'xlsx'}),post('/api/join-source','[1]')])
  self.assertEqual([x['status'] for x in rs],[0,0,0,0])
  # 結合の下読みとキーの見当: EXCEL・ACCESS を読む取り決め、「どちらも全部残す」、行数が int() で読めない値
  two=lambda b,**k:{'recipe':{'sources':[{'path':str(o/'表.accdb')},b],'joins':[{'type':k.get('t','inner'),'keys':[{'left':'a','right':'b'}]}]}}
  rs=self.rust('jbad',[post('/api/join-preview',two({'path':'x.csv'})),post('/api/join-keys',two({'path':'x.csv'})),
                       post('/api/join-preview',{'recipe':{'sources':[{'path':'a.csv'},{'path':'b.csv'}],'joins':[{'type':'full','keys':[{'left':'a','right':'b'}]}]}}),
                       post('/api/join-preview',{'recipe':{},'lines':'x'}),post('/api/join-keys',{'recipe':{},'index':'x'}),post('/api/join-preview',{'recipe':[1]})])
  self.assertEqual([x['status'] for x in rs],[0,0,0,0,0,0])
  self.assertFalse([n for n in os.listdir(self.t/'jbad'/'local'/'work'/'read-cache') if n.endswith('.xlsx') or n.endswith('.accdb')])
  os.remove(self.paths('jbad')[1])
  self.assertEqual(self.rust('jbad',[get('/api/join-candidates')])[0]['status'],0,'写しを替える場合は回す')


if __name__=='__main__':unittest.main()
