"""手元の対象（テキスト・結合・クエリ）を、ワーカー（lib/api_worker.py の local）で1件通す型（2.35.0）。

Rust の実行役（段 5d〜）が、どの対象もプロセスとして起こせるようにするための下ごしらえ。確かめること:
- ワーカーが、その場で流したとき（navi_textrun.run_one_local）と同じ出力ファイルと同じ記録（record_job_run へ渡す形）を作る
- ワーカーは設定DBへ書かない（実行の記録は親が書く。RNE のワーカーと同じ約束）。材料の待ち合わせもしない（親が受け持つ）
- 工程の様子を NAVI_WORKER_STATUS へ書き、結果を NAVI_WORKER_RESULT へ書く（終了コードは成功 0・失敗 2）
- 失敗（読取マスタが無い・ファイルが無い）も、その場で流したときと同じ記録になる
実行: python -m unittest tests.test_local_worker -v
"""
import json,os,re,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

CODE=r'''
import json,os,sqlite3,subprocess,sys
from pathlib import Path
tmp=Path(sys.argv[2]);sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_textrun
src=tmp/'受注.csv';src.write_bytes('番号,品名,数量\r\nA1,"ボルト, M8",120\r\nA2,ナット,5\r\n'.encode('cp932'))
c=app.app.test_client()
cols=[{'name':'番号','field':1},{'name':'品名','field':2},{'name':'数量','field':3,'type':'integer'}]
lid=c.post('/api/text-layouts',json={'name':'受注CSV','mode':'delimited','delimiter':'comma','header_row':True,'encoding':'cp932','columns':cols}).get_json()['layout']['id']
def job(i,out,**k):
 return dict({'id':i,'name':'受注'+i,'enabled':True,'source':'text','text_path':str(src),'layout_id':lid,'rne':'','rne_path':'',
              'output_folder':str(tmp/out),'output_format':'csv','output_file':'受注.csv','table':'','sheet':'Page1',
              'type':'詳細データ','naming_mode':'fixed','schedules':[]},**k)
cfg=app.load()
cfg['jobs']=[job('W1','w'),job('P1','p'),job('W2','w2',layout_id='無い'),job('P2','p2',layout_id='無い'),
             job('W3','w3',text_path=str(tmp/'無い.csv')),job('P3','p3',text_path=str(tmp/'無い.csv'))]
app.save(cfg);cfg=app.load();jobs={j['id']:j for j in cfg['jobs']}
def runs():
 with sqlite3.connect(str(app.SETTINGS_DB)) as d:return d.execute('SELECT COUNT(*) FROM run_history').fetchone()[0]
out={'before':runs(),'worker':{}}
for wid in ('W1','W2','W3'):
 w=tmp/('wk_'+wid);w.mkdir()
 payload={'local':{'trigger':'manual','slot':2,'held':{'waited':3.5}},'job':jobs[wid],'cfg':cfg,'job_index':1,'total_jobs':1,
          'work':str(tmp/'work'),'backup':str(tmp/'backup')}
 (w/'payload.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
 env=dict(os.environ,NAVI_WORKER_RESULT=str(w/'result.json'),NAVI_WORKER_STATUS=str(w/'status.json'),NAVI_WORKER_LINE='ライン 2')
 rc=subprocess.run([sys.executable,str(Path(sys.argv[1])/'lib'/'api_worker.py'),str(w/'payload.json')],env=env,cwd=sys.argv[1],
                   capture_output=True,text=True,encoding='utf-8',timeout=240).returncode
 rd=lambda n:json.loads((w/n).read_text(encoding='utf-8')) if (w/n).is_file() else None
 out['worker'][wid]={'rc':rc,'result':rd('result.json'),'status':rd('status.json')}
out['after_worker']=runs()
out['inproc']={}
for pid in ('P1','P2','P3'):
 out['inproc'][pid]=navi_textrun.run_one_local(dict(jobs[pid]),cfg,tmp/'work',tmp/'backup','manual',1,1)
with sqlite3.connect(str(app.SETTINGS_DB)) as d:
 d.row_factory=sqlite3.Row
 out['recorded']={r['job_id']:{'status':r['status'],'detail':r['detail'],'rows':r['rows'],'cols':r['cols'],'output_file':r['output_file'],
                               'metrics':json.loads(r['metrics'] or '{}')} for r in d.execute('SELECT * FROM job_runs')}
for n in ('w','p'):
 f=tmp/n/'受注.csv';out['csv_'+n]=f.read_text(encoding='utf-8-sig') if f.is_file() else None
print(json.dumps(out,ensure_ascii=False,default=str))
'''


def as_recorded(rec):
 """record_job_run が書く形（渡さなかった項目は既定の値で入る）。"""
 return dict({'rows':None,'cols':None,'output_file':'','metrics':{}},**rec)


def plain(v):
 """所要の秒（毎回違う）と、対象ごとに違う名前を除いた形。"""
 if isinstance(v,dict):return {k:plain(x) for k,x in v.items() if k not in ('elapsed','total_seconds','seconds','wait_seconds')}
 if isinstance(v,list):return [plain(x) for x in v]
 if isinstance(v,str):
  v=re.sub(r'[\d.]+秒','N秒',v)
  v=re.sub(r'^[WP](\d)$',r'X\1',v)                      # 対象の id（ワーカーは W・その場は P）
  return re.sub(r'受注[WP]','受注X',re.sub(r'([\\/])[wp](\d?)([\\/])',r'\1x\2\3',v))   # 名前と出力先のフォルダー
 return v


class LocalWorkerTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();d=Path(cls.tmp.name)
  env=dict(os.environ,NAVI_LOCAL_ROOT=str(d/'local'),NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),
           NAVI_SECRET_FILE=str(d/'s.json'),PYTHONIOENCODING='utf-8',DATARELAY_NO_BOOT='1')
  r=subprocess.run([sys.executable,'-c',CODE,str(ROOT),str(d)],cwd=str(ROOT),env=env,capture_output=True,text=True,encoding='utf-8',timeout=600)
  if r.returncode:raise AssertionError(r.stderr[-4000:])
  cls.o=json.loads(r.stdout.strip().splitlines()[-1])

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def test_worker_does_not_write_settings(self):
  self.assertEqual(self.o['after_worker'],self.o['before'],'ワーカーは実行の記録を書かない（親が書く）')

 def test_same_output_and_record_as_inprocess(self):
  w=self.o['worker']['W1'];self.assertEqual(w['rc'],0,w)
  res=w['result'];rec=res['record']
  self.assertTrue(res['ok']);self.assertEqual(self.o['csv_w'],self.o['csv_p'])
  self.assertEqual(self.o['csv_w'].splitlines(),['番号,品名,数量','A1,"ボルト, M8",120','A2,ナット,5'])
  # 親が書くはずの記録は、その場で流したときに書かれた記録と同じ（材料を待った秒は、ワーカーへ渡した値が入る）
  self.assertEqual(rec['metrics'].get('wait_seconds'),3.5)
  self.assertEqual(plain(as_recorded(rec)),plain(self.o['recorded']['P1']))
  self.assertEqual(plain({k:v for k,v in res.items() if k!='record'}),plain(self.o['inproc']['P1']))

 def test_failures_match(self):
  for wid,pid in (('W2','P2'),('W3','P3')):
   w=self.o['worker'][wid];self.assertEqual(w['rc'],2,w)
   self.assertEqual(plain(as_recorded(w['result']['record'])),plain(self.o['recorded'][pid]))
   self.assertEqual(plain({k:v for k,v in w['result'].items() if k!='record'}),plain(self.o['inproc'][pid]))
  self.assertIn('読取マスタ',self.o['worker']['W2']['result']['error'])

 def test_status_file(self):
  st=self.o['worker']['W1']['status']
  self.assertEqual((st['line'],st['job'],st['job_id'],st['slot']),('ライン 2','受注W1','W1',2))
  self.assertIn(st['state'],('読み取り','変換','公開','同時出力','変更なし'))
  self.assertTrue(st['pid'] and st['updated_at'])


if __name__=='__main__':unittest.main()
