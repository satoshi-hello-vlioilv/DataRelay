"""クエリ（Power Query の M の式。2.4.0）を、アプリの道で通す（lib/navi_mrun.py・navi_web の受け口・navi_textrun）。

app.py を本当に読み込み、受け口でクエリを保存・下読みし、対象（入力の種類 mquery）を実行して、SQLite3・CSV の
ファイルができるところまでを確かめる。言語そのものの確かめは tests/test_mquery.py。

実行: python -m unittest tests.test_mquery_app -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CODE = r'''
import json,sqlite3,sys,csv,io
from datetime import datetime
from pathlib import Path
tmp=Path(sys.argv[2]).resolve();sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import openpyxl
import app,navi_paths,navi_web,navi_textrun,navi_mrun,navi_orderrun
place=tmp/'share'/'DataRelay';folder=place/'日報';(folder/'sub').mkdir(parents=True)
for name,rows in (('日報_0101.xlsx',[(datetime(2024,1,1),'A-01',10,120.5),(datetime(2024,1,1),'B-02',None,80)]),
                  ('sub/日報_0102.xlsx',[(datetime(2024,1,2),'C-03','x',99)])):
 wb=openpyxl.Workbook();ws=wb.active;ws.title='実績';ws.append(('日付','品番','数量','単価'))
 for r in rows:ws.append(r)
 wb.save(folder/name)
copy=tmp/'pc'/'DataRelay';(copy/'data').mkdir(parents=True)
app.DATA_ROOT=Path(str(copy/'data'))
navi_paths.setup(app.DATA_ROOT,tmp/'local',copy,'pc');navi_paths.set_place(place)
out={}
c=app.app.test_client()
code="""let
    ソース = Folder.Files(".\\日報"),
    抽出 = Table.SelectRows(ソース, each [Extension] = ".xlsx"),
    データ = Table.AddColumn(抽出, "D", each Excel.Workbook([Content], true){[Item="実績",Kind="Sheet"]}[Data]),
    名前 = Table.RenameColumns(Table.SelectColumns(データ, {"Name", "D"}), {"Name", "Source.Name"}),
    展開 = Table.ExpandTableColumn(名前, "D", {"日付", "品番", "数量", "単価"}),
    型 = Table.TransformColumnTypes(展開, {{"日付", type date}, {"数量", Int64.Type}, {"単価", Currency.Type}})
in
    型"""
r=c.post('/api/m-queries',json={'name':'日報','code':code})
out['save']=[r.status_code,r.get_json()]
qid=r.get_json()['query']['id']
out['dup']=c.post('/api/m-queries',json={'name':'日報','code':'1'}).get_json()
out['bad']=c.post('/api/m-queries',json={'name':'壊れた','code':'let a = (1 in a'}).get_json()
out['list']=c.get('/api/m-queries').get_json()
out['preview']=c.post('/api/m-query/preview',json={'code':code,'name':'日報'}).get_json()
out['preview_step']=c.post('/api/m-query/preview',json={'code':code,'name':'日報','step':'抽出'}).get_json()
out['preview_err']=c.post('/api/m-query/preview',json={'code':code.replace('"実績"','"無い"'),'name':'日報'}).get_json()
out['preview_syntax']=c.post('/api/m-query/preview',json={'code':'let\n a = 1,\n b = (2\nin b','name':'x'}).get_json()
out['folder']=c.post('/api/m-query/folder',json={'folder':'.\\日報'}).get_json()
built=c.post('/api/m-query/build',json={'folder':'.\\日報','sheet':'実績','pattern':'日報'}).get_json()
out['built']=built
out['built_preview']=c.post('/api/m-query/preview',json={'code':built['code'],'name':'作った'}).get_json()
# 見本のファイル（サンプル ファイルの最後のステップ …{0}[Content]）の候補と、書き換える番号の場所
sample_code='// 日報\nlet a = 1 in a\n\n// サンプル ファイル\nlet\n    ソース = Folder.Files(".\\日報"),\n    #"抽出" = Table.SelectRows(ソース, each [Extension] = ".xlsx"),\n    ナビゲーション1 = #"抽出"{0}[Content]\nin\n    ナビゲーション1\n'
sm=c.post('/api/m-query/samples',json={'code':sample_code,'name':'x'}).get_json()
out['samples']={k:sm.get(k) for k in ('ok','query','step','base','index','total')}
out['samples']['names']=[f['name'] for f in sm.get('files') or []]
out['samples']['at']=sample_code[sm['span'][0]:sm['span'][1]] if sm.get('span') else None
# 対象を作って実行する（SQLite3 と CSV を同時に出す）
cfg=app.load()
job={'id':'J1','name':'日報の集約','enabled':True,'source':'mquery','query_id':qid,'query_out':'','rne':'','rne_path':'',
     'output_folder':str(tmp/'out'),'output_format':'sqlite3','output_file':'日報.sqlite3','extra_formats':['csv'],'table':'',
     'sheet':'Page1','type':'詳細データ','naming_mode':'fixed','schedules':[]}
cfg['jobs']=[job];app.save(cfg)
cfg=app.load();j=cfg['jobs'][0]
out['job_loaded']={k:j.get(k) for k in ('source','query_id','query_out','table')}
res=navi_textrun.run_one_local(dict(j),cfg,tmp/'work',tmp/'backup','manual',1,1)
out['run']=res
db=tmp/'out'/'日報.sqlite3'
if db.is_file():
 con=sqlite3.connect(db);tname=[r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like '\\_%' escape '\\'")]
 out['tables']=tname
 out['schema']=[list(r) for r in con.execute(f'pragma table_info("{tname[0]}")')]
 out['rows']=[list(r) for r in con.execute(f'select * from "{tname[0]}"')]
 con.close()
csvf=tmp/'out'/'日報.csv'
out['csv']=csvf.read_text(encoding='utf-8-sig') if csvf.is_file() else None
# 使っている対象があるうちは消せない
r=c.delete('/api/m-queries/'+qid);out['delete_used']=[r.status_code,r.get_json()]
# 持ち出し → 消す → 持ち込み（名前で結び直す）
z=c.get('/api/bundle/export?parts=jobs,queries');out['export_status']=z.status_code
blob=z.data
import zipfile
names=zipfile.ZipFile(io.BytesIO(blob)).namelist();out['zip_names']=names
jobs_json=json.loads(zipfile.ZipFile(io.BytesIO(blob)).read('jobs.json'))
out['exported_job']={k:jobs_json['jobs'][0].get(k) for k in ('source','mquery_name','query_id')}
cfg=app.load();cfg['jobs']=[];app.save(cfg)
out['delete_free']=c.delete('/api/m-queries/'+qid).get_json()
r=c.post('/api/bundle/import',data=blob,content_type='application/zip')
out['import']=r.get_json()
cfg=app.load();qs=navi_mrun.load_m_queries()
out['after_import']={'queries':[q['name'] for q in qs],'job_query':cfg['jobs'][0].get('query_id')==qs[0]['id'] if cfg['jobs'] and qs else None}
# 単体の持ち出し（.pq）と取り込み（式そのもののテキスト）
pq=c.get('/api/m-queries/export?format=m&ids='+qs[0]['id'])
out['pq']=[pq.status_code,pq.headers.get('Content-Disposition'),pq.data.decode('utf-8')[:3]]
r=c.post('/api/m-queries/import?filename=別の式.pq',data='let x = 1 in x'.encode('utf-8'),content_type='text/plain')
out['import_text']=r.get_json()
# Excel の「接続ファイルのエクスポート」（.odc）をそのまま受ける。出すクエリは接続文字列の Location
sys.path.insert(0,sys.argv[1])
from tests.test_mquery import odc_text
odc=odc_text([('出す表','let a = 補助 + 1 in a'),('補助','41')],'出す表')
r=c.post('/api/m-queries/import?filename=クエリ - 出す表.odc',data=odc,content_type='application/octet-stream')
out['import_odc']=r.get_json()
q=[x for x in navi_mrun.load_m_queries() if x['name']=='出す表']
out['odc_query']={'output':q[0]['output'],'value':navi_mrun.preview(q[0]['code'],'出す表').get('value')} if q else None
# 材料: クエリが読むフォルダーに出力を置く対象は、先に作る
cfg=app.load()
maker={'id':'J0','name':'作る側','enabled':True,'source':'text','text_path':'x.txt','layout_id':'','output_folder':str(folder),
       'output_format':'csv','output_file':'日報_追加.csv','schedules':[]}
cfg['jobs']=[cfg['jobs'][0],maker];app.save(cfg);cfg=app.load()
deps=navi_orderrun.job_dependencies(cfg['jobs'],cfg)
out['deps']={cfg['jobs'][0]['name']:sorted(deps.get(cfg['jobs'][0]['id']) or [])}
out['maker_id']=[x['id'] for x in cfg['jobs'] if x['name']=='作る側']
print(json.dumps(out,ensure_ascii=False,default=str))
'''


class MQueryAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, NAVI_LOCAL_ROOT=str(Path(d) / 'local'), NAVI_DATA_ROOT=str(Path(d) / 'boot'),
                       NAVI_CONFIG_DIR=str(Path(d) / 'cfg'), PYTHONIOENCODING='utf-8')
            r = subprocess.run([sys.executable, '-c', CODE, str(ROOT), d], cwd=d, env=env, capture_output=True, text=True,
                               encoding='utf-8', timeout=240)
            if r.returncode != 0:
                raise AssertionError(r.stderr[-4000:])
            cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_save_and_list(self):
        o = self.o
        self.assertEqual(o['save'][0], 200, o['save'])
        self.assertFalse(o['dup']['ok'], '同じ名前は重ねない（名前で結び直すため）')
        self.assertIn('同じ名前', o['dup']['error'])
        self.assertFalse(o['bad']['ok'])
        self.assertIn('1行', o['bad']['error'], '読めない式は何行目かを付けて断る')
        item = o['list']['items'][0]
        self.assertEqual(item['queries'], ['日報'])
        self.assertEqual(item['main'], '日報')

    def test_preview(self):
        p = self.o['preview']
        self.assertTrue(p['ok'], p)
        self.assertEqual(p['queries'][0]['steps'], ['ソース', '抽出', 'データ', '名前', '展開', '型'])
        self.assertEqual(p['step'], '型')
        self.assertEqual([c['name'] for c in p['columns']], ['Source.Name', '日付', '品番', '数量', '単価'])
        self.assertEqual([c['out'] for c in p['columns']], ['text', 'date', 'text', 'integer', 'numeric'])
        self.assertEqual(p['row_count'], 3)
        self.assertEqual(p['error_cells'], 1)
        self.assertEqual(p['rows'][0][:2], ['日報_0101.xlsx', '2024/01/01'], '日付は ja-JP の見え方で返す')
        self.assertEqual(p['rows'][2][3], {'e': '「x」を整数に変換できませんでした。'})
        ps = self.o['preview_step']
        self.assertEqual(ps['step'], '抽出')
        self.assertIn('Content', [c['name'] for c in ps['columns']])
        self.assertEqual(ps['rows'][0][0], {'n': 'Binary'}, '入れ子の値は種類の名前で見せる（Power Query と同じ）')

    def test_preview_errors_point_to_place(self):
        e = self.o['preview_err']
        self.assertFalse(e['ok'])
        self.assertEqual(e['error']['step'], '展開', 'どのステップで止まったか')
        self.assertEqual(e['error']['origin_step'], 'データ', 'もとはどのステップで起きた誤りか（セルの誤りとして運ばれてきた）')
        self.assertIn('もとはステップ「データ」', e['error']['where'])
        self.assertIn('シート名', e['error']['message'])
        s = self.o['preview_syntax']
        self.assertFalse(s['ok'])
        self.assertEqual(s['error']['line'], 4)

    def test_folder_and_build(self):
        f = self.o['folder']
        self.assertTrue(f['ok'], f)
        self.assertEqual(f['total'], 2)
        self.assertEqual(f['sheets'], ['実績'])
        b = self.o['built_preview']
        self.assertTrue(b['ok'], b)
        self.assertEqual([c['name'] for c in b['columns']], ['Source.Name', '日付', '品番', '数量', '単価'])
        self.assertEqual(b['row_count'], 3)
        self.assertIn('Folder.Files(".\\日報")', self.o['built']['code'])

    def test_run_writes_files(self):
        o = self.o
        self.assertEqual(o['job_loaded']['source'], 'mquery')
        self.assertEqual(o['job_loaded']['table'], 'DATA', '手元のファイルから作る入力の表の既定は DATA')
        self.assertTrue(o['run']['ok'], o['run'])
        self.assertIn('3件/5列', o['run']['detail'])
        self.assertIn('誤りのセル 1か所', o['run']['detail'], '空にしたセルがあることを結果に出す')
        types = {r[1]: r[2] for r in o['schema']}
        self.assertEqual(types['数量'], 'INTEGER')
        self.assertEqual(types['単価'], 'REAL')
        self.assertEqual(o['rows'][0], ['日報_0101.xlsx', '2024-01-01', 'A-01', 10, 120.5])
        self.assertIsNone(o['rows'][2][3], '誤りのセルは空')
        self.assertTrue(o['csv'].startswith('Source.Name,日付,品番,数量,単価'), o['csv'][:80])

    def test_delete_and_bundle(self):
        o = self.o
        self.assertEqual(o['delete_used'][0], 409)
        self.assertIn('日報の集約', o['delete_used'][1]['error'])
        self.assertIn('m-queries.json', o['zip_names'])
        self.assertEqual(o['exported_job'], {'source': 'mquery', 'mquery_name': '日報', 'query_id': None},
                         'id は持ち出さず名前で持つ')
        self.assertTrue(o['delete_free']['ok'])
        self.assertTrue(o['import']['ok'], o['import'])
        self.assertEqual(o['after_import']['queries'], ['日報'])
        self.assertTrue(o['after_import']['job_query'], '持ち込んだ対象が、持ち込んだクエリへ名前で結び直る')
        self.assertEqual(o['pq'][0], 200)
        self.assertIn('.pq', o['pq'][1])
        self.assertTrue(o['import_text']['ok'])
        self.assertEqual(o['import_text']['added'], ['別の式'], '式そのもののファイルは、ファイル名をクエリ名にする')

    def test_samples(self):
        sm = self.o['samples']
        self.assertEqual(sm['names'], ['日報_0101.xlsx', '日報_0102.xlsx'], '見本の候補は元のファイル名で並べる（下のフォルダーも）')
        self.assertEqual((sm['query'], sm['step'], sm['base'], sm['index'], sm['at']), ('サンプル ファイル', 'ナビゲーション1', '抽出', 0, '0'),
                         '書き換えるのは …{0}[Content] の番号')

    def test_import_odc(self):
        self.assertTrue(self.o['import_odc']['ok'], self.o['import_odc'])
        self.assertEqual(self.o['import_odc']['added'], ['出す表'], '.odc は出すクエリの名前で1つのクエリにまとめる')
        self.assertEqual(self.o['odc_query'], {'output': '出す表', 'value': 42}, '補助のクエリも一緒に入り、名前で参照できる')

    def test_dependencies(self):
        self.assertEqual(self.o['deps']['日報の集約'], self.o['maker_id'], 'クエリが読むフォルダーへ出力する対象を待つ')


if __name__ == '__main__':
    unittest.main()
