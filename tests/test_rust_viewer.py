"""データビュワー（CSV・TXT・SQLite3）が、Python（navi_web.data_viewer・app.read_preview_data・navi_localcopy.read_copy）と
Rust（desktop/core の viewer.rs・localcopy.rs）で同じ答えになるか（2.28.0）。

- CSV の読み方（CPython の _csv.c と同じ順）を、乱数の字で csv.reader と比べる
- 比べるルート: GET /api/data-viewer/jobs・GET /api/data-viewer/<job_id>。cp932・BOM 付き UTF-8・終わりの印の行・囲みの中の改行・
  タブ区切り・SQLite（表の選び方・_更新情報・小数・NULL）・空の SQLite・どの文字コードでも読めない CSV・公開している途中の印・
  無いファイル・無い対象・無い値で比べる
- 手元の写し（work\\read-cache）の名前が Python と同じ（同じ版の写しを Python と Rust で使い回せる）ことも比べる
- 値ごとに分けて出す対象（2.29.0。variants.rs）: 指定した値だけ・出てきた値すべて・値ごとの名前と置き場の型・対象の名前の型の {値}・
  前回の実行が作ったファイル（実行記録の variant_results）・同じ名前になる値・?value= の %XX と + で比べる
- EXCEL・同じ名前になる値（道が決まらない）・写しを替える場合は、Rust が Python へ回す
実行: python -m unittest tests.test_rust_viewer -v
"""
import csv,io,json,os,random,sqlite3,subprocess,sys,unittest
from contextlib import closing

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import test_rust_save  # noqa: E402
from test_rust_writes import ASK  # noqa: E402
from test_rust_config import MAKE  # noqa: E402
from test_rust_parity import ROOT  # noqa: E402

NOW='2026-11-02T09:05:07.123456'


def get(path):return {'method':'GET','path':path,'body':''}


class ViewerParityTest(unittest.TestCase):
 setUpClass=classmethod(test_rust_save.SaveParityTest.setUpClass.__func__)
 tearDownClass=classmethod(test_rust_save.SaveParityTest.tearDownClass.__func__)
 env,paths,py,twin=(getattr(test_rust_save.SaveParityTest,k) for k in ('env','paths','py','twin'))

 def rust(self,name,reqs):
  """道と ?以降（query）を分けて Rust の答え口へ送る。"""
  lines=''.join(json.dumps({'method':q['method'],'path':q['path'].split('?')[0],'query':q['path'].split('?',1)[1] if '?' in q['path'] else '',
                            'body':q.get('body',''),'headers':{}},ensure_ascii=False)+'\n' for q in reqs)
  r=subprocess.run([str(self.exe),'answer','--base',str(ROOT)],input=lines,env=dict(self.env(name),DATARELAY_FIXED_NOW=NOW),cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return [json.loads(x) for x in r.stdout.split('\n') if x.strip()]

 def test_csv_reader_like_python(self):
  rnd=random.Random(9)
  al=['a',',','"','\n','\r','\t',' ','あ','""','\r\n','x"y','\x00','\x1a']
  texts=[''.join(rnd.choice(al) for _ in range(rnd.randrange(0,18))) for _ in range(6000)]
  ds=[rnd.choice([',','\t']) for _ in texts]
  q=''.join(json.dumps({'fn':'csv','args':{'text':t,'delimiter':d}})+'\n' for t,d in zip(texts,ds))
  r=subprocess.run([str(self.exe),'call'],input=q,capture_output=True,text=True,encoding='utf-8',timeout=300)
  rs=[json.loads(x)['result'] for x in r.stdout.split('\n') if x.strip()]
  self.assertEqual(len(rs),len(texts))
  bad=[(t,d,x) for t,d,x in zip(texts,ds,rs) if x!='pass' and list(csv.reader(io.StringIO(t,newline=''),delimiter=d))!=x]
  self.assertEqual(bad[:5],[])
  self.assertLess(sum(x=='pass' for x in rs),10)

 def outputs(self):
  o=self.t/'viewer';o.mkdir(exist_ok=True)
  (o/'受注.csv').write_bytes('コード,名前,メモ\r\n1,"東京, 本社","改行\r\nあり"\r\n2,大阪,\r\n\x1a\r\n'.encode('cp932'))
  (o/'bom.csv').write_bytes(b'\xef\xbb\xbf'+'a,b\n1,2,3\n\n4\n'.encode('utf-8'))
  (o/'tab.txt').write_bytes('品番\t数\nA\t10\nB\t20\n'.encode('utf-8'))
  (o/'bad.csv').write_bytes(b'\x81\x20\xff\n')
  db=o/'在庫.sqlite3'
  if db.exists():db.unlink()
  with closing(sqlite3.connect(str(db))) as c,c:
   c.execute('CREATE TABLE "在庫" (品番 TEXT, 数 INTEGER, 単価 REAL, 備考 TEXT)')
   c.executemany('INSERT INTO "在庫" VALUES(?,?,?,?)',[('A',10,1.5,None),('B',-3,0.1+0.2,'x'),('C',None,1e20,''),('D',7,2.0,'あ')])
   c.execute('CREATE TABLE "_更新情報" (k TEXT)');c.execute('CREATE TABLE "z別表" (k TEXT)')
  empty=o/'空.sqlite3'
  if empty.exists():empty.unlink()
  with closing(sqlite3.connect(str(empty))) as c,c:c.execute('CREATE TABLE "_更新情報" (k TEXT)')
  (o/'途中.csv').write_bytes(b'a\n1\n');(o/'.途中.csv.123.incoming').write_bytes(b'')
  return o

 def make(self,name,extra_jobs=(),sql=()):
  o=self.outputs()
  job=lambda i,n,f,fmt,**k:dict(id=i,name=n,output_folder=str(o),output_file=f,output_format=fmt,naming_mode='fixed',**k)
  cfg={'jobs':[job('v1','受注','受注.csv','csv'),job('v2','BOM','bom.csv','csv'),job('v3','タブ','tab.txt','txt'),
               job('v4','在庫','在庫.sqlite3','sqlite',table='在庫'),job('v5','表の名前違い','在庫.sqlite3','sqlite3',table='無い表'),
               job('v6','空','空.sqlite3','sqlite3'),job('v7','読めない','bad.csv','csv'),job('v8','途中','途中.csv','csv'),
               job('v9','まだ無い','無い.csv','csv'),*extra_jobs]}
  self.py(MAKE,name,json.dumps({'cfg':cfg,'sql':list(sql)},ensure_ascii=False))
  return o

 def test_viewer(self):
  self.make('vbase');self.twin('vbase','vpy','vrs')
  reqs=[get('/api/data-viewer/jobs')]+[get(f'/api/data-viewer/v{i}') for i in range(1,10)]+[
        get('/api/data-viewer/v1?value='),get('/api/data-viewer/v1?value=x'),get('/api/data-viewer/無い'),get('/api/data-viewer/v1')]
  py=self.py(ASK,'vpy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('vrs',reqs)
  for q,p,x in zip(reqs,py,rs):
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {q["path"]}')
   self.assertEqual((x['status'],json.loads(x['body'])),(p['status'],json.loads(p['body'])),q['path'])
  # 見本が中身を持っていること
  b=[json.loads(p['body']) for p in py]
  self.assertTrue(b[1]['ok'] and b[1]['rows'] and b[4]['ok'] and b[4]['headers']==['品番','数','単価','備考'])
  self.assertEqual([b[i].get('error','')[:6] for i in (6,7)],['表示できるテ','文字コードを'])
  self.assertEqual(b[8].get('kind'),'copying')
  # 手元の写しの名前が同じ（同じ版の写しを使い回せる）
  names=[sorted(os.listdir(self.t/n/'local'/'work'/'read-cache')) for n in ('vpy','vrs')]
  self.assertEqual(names[0],names[1]);self.assertGreaterEqual(len(names[0]),5)
  # Rust の写しを Python が使い回す（写しを作り直さない）
  before=sorted(os.listdir(self.t/'vrs'/'local'/'work'/'read-cache'))
  again=self.py(ASK,'vrs',json.dumps([get('/api/data-viewer/v1')],ensure_ascii=False),NOW)[0]
  self.assertEqual(json.loads(again['body']),json.loads(py[1]['body']))
  self.assertEqual(sorted(os.listdir(self.t/'vrs'/'local'/'work'/'read-cache')),before)

 def test_variants(self):
  o=self.t/'viewer';o.mkdir(exist_ok=True)
  for n in ('受注_東京.csv','受注_大阪.csv','前回_名古屋.csv'):(o/n).write_bytes('コード,拠点\r\n1,x\r\n'.encode('cp932'))
  (o/'東京').mkdir(exist_ok=True);(o/'東京'/'月報.csv').write_bytes(b'a\n1\n')
  (o/'_').mkdir(exist_ok=True);(o/'_'/'月報.csv').write_bytes(b'a\n2\n')
  base=dict(output_folder=str(o),output_format='csv',naming_mode='fixed')
  var=lambda **k:{'enabled':True,'item':'拠点',**k}
  jobs=[dict(base,id='w1',name='指定',output_file='受注.csv',variants=var(values=['東京',' 大阪 ','東京','福岡',''])),
        dict(base,id='w2',name='置き場',output_file='x.csv',variants=var(values=['東京','..','a/b'],pattern='月報',folder=str(o)+'/{値}')),
        dict(base,id='w3',name='すべて',output_file='受注.csv',variants=var(scope='all')),
        dict(base,id='w4',name='まだ',output_file='受注.csv',variants=var(scope='all')),
        dict(base,id='w5',name='同じ名前',output_file='受注.csv',variants=var(values=['東京'],pattern='固定',folder='{値}{date}')),
        dict(base,id='w6',name='名前の型',output_file='受注.csv',naming_mode='template',output_pattern='{name}_{値:upper}_{date}',
             variants=var(values=['ab','東京'])),
        dict(base,id='w7',name='切ってある',output_file='受注.csv',variants={'enabled':False,'item':'拠点','values':['東京']}),
        dict(base,id='w8',name='項目なし',output_file='受注.csv',variants={'enabled':True,'values':['東京']}),
        dict(base,id='w9',name='前回',output_file='受注.csv',variants=var(values=['名古屋','東京']))]
  run=lambda i,res:("INSERT OR REPLACE INTO job_runs(job_id,job_name,finished_at,status,trigger,detail,rows,cols,output_file,updated_at,metrics) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",[i,i,'2026-11-01T10:00:00','success','manual','',3,2,'',
                                                     '2026-11-01T10:00:00',json.dumps({'variant_results':res},ensure_ascii=False)])
  sql=[run('w3',[{'value':'大阪','target':str(o/'受注_大阪.csv'),'ok':True,'rows':5},{'value':'東京','target':str(o)+'//受注_東京.csv','ok':False},
                 {'value':'札幌','target':str(o/'無い.csv'),'ok':True,'rows':0},{'value':None,'target':'x'},{'value':'大阪','target':str(o/'受注_大阪.csv'),'ok':True,'rows':6}]),
       run('w9',[{'value':'名古屋','target':str(o/'前回_名古屋.csv'),'ok':True,'rows':1},{'value':'東京','target':str(o/'無い.csv'),'ok':1,'rows':2}]),
       run('w1',[{'value':'大阪','ok':True,'rows':9}])]
  self.make('wbase',extra_jobs=jobs,sql=sql);self.twin('wbase','wpy','wrs')
  q='?value='
  reqs=[get('/api/data-viewer/jobs')]+[get(f'/api/data-viewer/w{i}') for i in range(1,10)]+[
        get('/api/data-viewer/w1'+q+'%E5%A4%A7%E9%98%AA'),get('/api/data-viewer/w1'+q+'福岡'),get('/api/data-viewer/w1'+q+'無い'),
        get('/api/data-viewer/w1'+q),get('/api/data-viewer/w2'+q+'..'),get('/api/data-viewer/w2'+q+'a%2Fb'),
        get('/api/data-viewer/w3'+q+'%E6%9D%B1%E4%BA%AC'),get('/api/data-viewer/w3'+q+'%e6%9c%ad%e5%b9%8c'),get('/api/data-viewer/w6'+q+'ab'),
        get('/api/data-viewer/w7'+q+'東京'),get('/api/data-viewer/v1'+q+'a+b'),get('/api/data-viewer/w1?x=1&value=%E6%9D%B1%E4%BA%AC&value=x'),
        get('/api/data-viewer/w1?valu%65=%zz')]
  py=self.py(ASK,'wpy',json.dumps(reqs,ensure_ascii=False),NOW)
  rs=self.rust('wrs',reqs)
  same=lambda body,env:json.loads(body.replace(json.dumps(str(self.t/env))[1:-1],'ENV'))   # 型の相対の置き場は、それぞれのデータの置き場で決まる
  for r,p,x in zip(reqs,py,rs):
   self.assertNotEqual(x['status'],0,f'Rust が答えなかった: {r["path"]}')
   self.assertEqual((x['status'],same(x['body'],'wrs')),(p['status'],same(p['body'],'wpy')),r['path'])
  # 見本が中身を持っていること（値ごとのファイルが並び、前回の実行の道と件数を使い、値で選べる）
  items={x['id']:x for x in json.loads(py[0]['body'])['items']}
  self.assertEqual([f['value'] for f in items['w1']['files']],['東京','大阪','福岡'])
  self.assertEqual([f['value'] for f in items['w3']['files']],['大阪','東京','札幌'])
  self.assertEqual(items['w3']['files'][0]['rows'],6);self.assertEqual(items['w4']['files'],[])
  self.assertEqual([f['file'] for f in items['w2']['files']],['月報.csv']*3)
  self.assertTrue(items['w9']['files'][0]['exists'] and items['w9']['files'][0]['file']=='前回_名古屋.csv')
  self.assertEqual(items['w7']['files'],[])
  b=[json.loads(p['body']) for p in py]
  self.assertEqual((b[10]['value'],b[10]['ok']),('大阪',True));self.assertEqual(b[14]['value'],'..')
  self.assertEqual(py[12]['status'],404);self.assertEqual(py[4]['status'],404)

 def test_python_only_cases(self):
  """EXCEL・同じ名前になる値・写しを替える場合は、Python へ回す。"""
  o=self.make('vonly',extra_jobs=[dict(id='x1',name='表計算',output_folder=str(self.t/'viewer'),output_file='受注.xlsx',output_format='xlsx'),
                                   dict(id='x2',name='同じ名前',output_folder=str(self.t/'viewer'),output_file='受注.csv',output_format='csv',
                                        variants={'enabled':True,'item':'拠点','values':['東京','大阪'],'pattern':'固定'})])
  (o/'受注.xlsx').write_bytes(b'PK')
  # 同じ名前になる値は道が決まらず、Python は Path('')（今いるフォルダー）を見るので、Rust は答えない
  rs=self.rust('vonly',[get('/api/data-viewer/x1'),get('/api/data-viewer/x2'),get('/api/data-viewer/jobs')])
  self.assertEqual([x['status'] for x in rs],[0,0,0])
  os.remove(self.paths('vonly')[1])
  self.assertEqual(self.rust('vonly',[get('/api/data-viewer/v1')])[0]['status'],0)


if __name__=='__main__':unittest.main()
