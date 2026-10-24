"""後処理（2.6.0）: 取り出した表を、変換して出す前に M の式で整える。

前半は取り決めと式（lib/navi_post.py・navi_m の外から渡す名前）だけを単独で、後半はアプリの道（app.py を本当に読み込み、
対象を実行してファイルができる・下読み・クエリとして保存・後処理にクエリを使う・持ち出しと持ち込み）を確かめる。

実行: python -m unittest tests.test_post -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]

import navi_m as M  # noqa: E402
import navi_post as P  # noqa: E402


def run(steps, columns, rows):
    code = P.compile({'enabled': True, 'steps': steps})
    t = M.force(M.Document.from_text(code, '後処理', inputs={M.INPUT_NAME: M.MTable(columns, rows)}).evaluate())
    return t.columns, [[M.force(x) if isinstance(x, M.Thunk) else x for x in r] for r in t.rows]


WIDE = (['品番', '工程', '1月', '2月'],
        [['A', '組立', '1,200', '3'], ['B', '組立', None, '5'], ['A', '検査', '7', None]])


class StepsTest(unittest.TestCase):
    def test_unpivot_other_columns_drops_empty_cells(self):
        cols, rows = run([{'op': 'unpivot', 'columns': ['品番', '工程']}], *WIDE)
        self.assertEqual(cols, ['品番', '工程', '属性', '値'])
        self.assertEqual(rows, [['A', '組立', '1月', '1,200'], ['A', '組立', '2月', '3'], ['B', '組立', '2月', '5'],
                                ['A', '検査', '1月', '7']], '空のセルは出さない（Power Query と同じ）')

    def test_unpivot_selected_and_names(self):
        cols, rows = run([{'op': 'unpivot', 'mode': 'selected', 'columns': ['2月'], 'attr': '月', 'value': '数量'}], *WIDE)
        self.assertEqual(cols, ['品番', '工程', '1月', '月', '数量'])
        self.assertEqual(len(rows), 2)

    def test_round_trip_unpivot_then_pivot_sums_text_numbers(self):
        steps = [{'op': 'unpivot', 'columns': ['品番', '工程']}, {'op': 'select', 'columns': ['品番', '属性', '値']},
                 {'op': 'pivot', 'column': '属性', 'value': '値', 'agg': 'sum'}]
        cols, rows = run(steps, *WIDE)
        self.assertEqual(cols, ['品番', '1月', '2月'])
        self.assertEqual(rows, [['A', 1207, 3], ['B', None, 5]], '「1,200」のような文字も数に直して合計する')

    def test_pivot_without_aggregation_marks_duplicates(self):
        cols, rows = run([{'op': 'pivot', 'column': '工程', 'value': '1月', 'agg': 'none'}],
                         ['品番', '工程', '1月'], [['A', '組立', '1'], ['A', '組立', '2'], ['B', '検査', '3']])
        self.assertEqual(cols, ['品番', '組立', '検査'])
        self.assertIsInstance(rows[0][1], M.ErrorCell, '集計しないのに値が2つあれば、そのセルは誤り（Power Query と同じ）')
        self.assertEqual(rows[1][2], '3')

    def test_pivot_count_and_blank_header(self):
        cols, rows = run([{'op': 'pivot', 'column': '工程', 'value': '1月', 'agg': 'count'}],
                         ['品番', '工程', '1月'], [['A', '組立', 'x'], ['A', None, 'y']])
        self.assertEqual(cols, ['品番', '組立', ''], 'null の値は空の見出しにまとめる')
        self.assertEqual(rows, [['A', 1, 1]])

    def test_group(self):
        steps = [{'op': 'group', 'keys': ['工程'], 'aggs': [{'func': 'sum', 'column': '1月'}, {'func': 'count'},
                                                           {'func': 'count_distinct', 'column': '品番', 'name': '品番数'}]}]
        cols, rows = run(steps, *WIDE)
        self.assertEqual(cols, ['工程', '1月の合計', '件数', '品番数'])
        self.assertEqual(rows, [['組立', 1200, 2, 2], ['検査', 7, 1, 1]])

    def test_rename_sort_and_m_step(self):
        steps = [{'op': 'rename', 'pairs': [['品番', 'ITEM']]}, {'op': 'sort', 'keys': [['ITEM', 'desc'], ['工程', 'asc']]},
                 {'op': 'm', 'expr': 'Table.SelectRows(前, each [工程] = "組立")'}]
        cols, rows = run(steps, *WIDE)
        self.assertEqual(cols[0], 'ITEM')
        self.assertEqual([r[0] for r in rows], ['B', 'A'])

    def test_odd_column_names(self):
        cols, rows = run([{'op': 'group', 'keys': ['a"b'], 'aggs': [{'func': 'sum', 'column': '[x] 1'}]}],
                         ['a"b', '[x] 1'], [['k', '2'], ['k', '3']])
        self.assertEqual(cols, ['a"b', '[x] 1の合計'])
        self.assertEqual(rows, [['k', 5]])

    def test_step_names_like_power_query(self):
        code, made = P.compile_steps([{'op': 'pivot', 'column': 'a', 'value': 'b', 'agg': 'sum'},
                                      {'op': 'group', 'keys': ['a'], 'aggs': [{'func': 'max', 'column': 'c'}]}])
        self.assertEqual([n for _i, n in made], ['変更された型', 'ピボットされた列', '変更された型 1', 'グループ化された行'])
        self.assertEqual([i for i, _n in made], [0, 0, 1, 1], '手順の番号へ戻せる')
        self.assertTrue(code.startswith('let\n    ソース = 取り出した表,'))


class RulesTest(unittest.TestCase):
    def test_normalize_unused_is_empty(self):
        self.assertEqual(P.normalize(None), {})
        self.assertEqual(P.normalize({'enabled': False, 'steps': []}), {})
        self.assertFalse(P.active({'post': {'enabled': True, 'steps': []}}))
        self.assertTrue(P.active({'post': {'enabled': True, 'steps': [{'op': 'select', 'columns': ['a']}]}}))
        self.assertFalse(P.active({'post': {'enabled': False, 'steps': [{'op': 'select', 'columns': ['a']}]}}))
        self.assertTrue(P.active({'post': {'enabled': True, 'mode': 'query', 'query_id': 'q'}}))

    def test_problems_name_the_step(self):
        bad = P.problems({'enabled': True, 'steps': [{'op': 'pivot', 'column': 'a', 'value': 'a'}, {'op': 'unpivot'}]})
        self.assertIn('1番目（ピボット）: 見出しにする列と値の列は、別の列を選んでください', bad)
        self.assertIn('2番目（ピボット解除）: 残す列（キー）を選んでください', bad)
        self.assertEqual(P.problems({'enabled': True, 'mode': 'query'}), ['後処理: クエリを選んでください'])
        self.assertIn('選んだクエリがありません', P.problems({'enabled': True, 'mode': 'query', 'query_id': 'x'}, lambda i: False)[0])
        self.assertEqual(P.problems({'enabled': False}), [])

    def test_unknown_ops_are_dropped(self):
        self.assertEqual(P.normalize({'enabled': True, 'steps': [{'op': 'rm -rf'}, {'op': 'select', 'columns': ['a', 'a']}]})['steps'],
                         [{'op': 'select', 'columns': ['a']}])

    def test_summary(self):
        self.assertEqual(P.summary({'enabled': True, 'steps': [{'op': 'unpivot', 'columns': ['a']}, {'op': 'pivot'}]}),
                         '後処理 ピボット解除 → ピボット')
        self.assertEqual(P.summary({'enabled': True, 'mode': 'query', 'query_id': 'x'}, '集計'), '後処理 クエリ「集計」')


class InputNameTest(unittest.TestCase):
    def test_input_name_is_not_missing_and_says_why_without_input(self):
        doc = M.Document.from_text('let a = 取り出した表 in a', 'x')
        self.assertEqual(doc.missing_names(), [], '取り出した表は足りない名前として知らせない')
        self.assertTrue(doc.uses_input())
        with self.assertRaises(M.MError) as e:
            doc.evaluate()
        self.assertIn('取り出した表が入る名前', e.exception.message)

    def test_query_with_same_name_wins(self):
        doc = M.Document.from_text('// 取り出した表\n1\n\n// 出す\nlet a = 取り出した表 + 1 in a', 'x')
        self.assertFalse(doc.uses_input())
        self.assertEqual(doc.evaluate('出す'), 2)


CODE = r'''
import json,sqlite3,sys,csv,io,zipfile
from datetime import datetime
from pathlib import Path
tmp=Path(sys.argv[2]).resolve();sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import openpyxl
import app,navi_paths,navi_web,navi_textrun,navi_mrun,navi_post
place=tmp/'share'/'DataRelay';folder=place/'実績';folder.mkdir(parents=True)
wb=openpyxl.Workbook();ws=wb.active;ws.title='月別';ws.append(('品番','工程','1月','2月'))
for r in (('A','組立',1200,3),('B','組立',None,5),('A','検査',7,None)):ws.append(r)
wb.save(folder/'月別.xlsx')
copy=tmp/'pc'/'DataRelay';(copy/'data').mkdir(parents=True)
app.DATA_ROOT=Path(str(copy/'data'))
navi_paths.setup(app.DATA_ROOT,tmp/'local',copy,'pc');navi_paths.set_place(place)
out={}
c=app.app.test_client()
code='let\n    ソース = Excel.Workbook(File.Contents(".\\\\実績\\\\月別.xlsx"), true){[Item="月別",Kind="Sheet"]}[Data],\n    型 = Table.TransformColumnTypes(ソース, {{"1月", Int64.Type}, {"2月", Int64.Type}})\nin\n    型'
qid=c.post('/api/m-queries',json={'name':'月別','code':code}).get_json()['query']['id']
out['meta']=c.get('/api/post/meta').get_json()
cfg=app.load()
steps=[{'op':'unpivot','columns':['品番','工程'],'attr':'月','value':'数量'},
       {'op':'group','keys':['品番','月'],'aggs':[{'func':'sum','column':'数量','name':'数量'}]},
       {'op':'sort','keys':[['品番','asc'],['月','asc']]}]
job={'id':'J1','name':'月別を縦に','enabled':True,'source':'mquery','query_id':qid,'rne':'','rne_path':'',
     'output_folder':str(tmp/'out'),'output_format':'sqlite3','output_file':'縦.sqlite3','extra_formats':['csv'],'table':'',
     'sheet':'Page1','type':'詳細データ','naming_mode':'fixed','schedules':[],
     'post':{'enabled':True,'mode':'steps','steps':steps}}
cfg['jobs']=[job];app.save(cfg)
cfg=app.load();j=cfg['jobs'][0]
out['saved_post']=j.get('post')
# 保存前（見本なし）の下読み
out['preview_before']=c.post('/api/post/preview',json={'job_id':'J1','post':j['post']}).get_json()
res=navi_textrun.run_one_local(dict(j),cfg,tmp/'work',tmp/'backup','manual',1,1)
out['run']=res
db=tmp/'out'/'縦.sqlite3'
if db.is_file():
 con=sqlite3.connect(db);t=[r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like '\\_%' escape '\\'")][0]
 out['schema']=[list(r) for r in con.execute(f'pragma table_info("{t}")')]
 out['rows']=[list(r) for r in con.execute(f'select * from "{t}"')]
 con.close()
csvf=tmp/'out'/'縦.csv'
out['csv']=csvf.read_text(encoding='utf-8-sig') if csvf.is_file() else None
out['work_left']=sorted(p.name for p in (tmp/'work').glob('*.csv'))
# 実行のあとは、この PC に控えた後処理の前の表で下読みできる。手順を押すとその手順のあとの表
out['preview']=c.post('/api/post/preview',json={'job_id':'J1','post':j['post']}).get_json()
out['preview_step0']=c.post('/api/post/preview',json={'job_id':'J1','post':j['post'],'step':0}).get_json()
bad={'enabled':True,'steps':[{'op':'select','columns':['無い列']}]}
out['preview_bad']=c.post('/api/post/preview',json={'job_id':'J1','post':bad}).get_json()
# 手順をクエリとして保存 → 後処理にクエリを使う
r=c.post('/api/post/to-query',json={'post':j['post'],'name':'縦持ち','job_name':j['name']})
out['to_query']=r.get_json()
pq=out['to_query']['query']
out['mq_preview']=c.post('/api/m-query/preview',json={'code':pq['code'],'name':pq['name'],'query_id':pq['id'],'sample_job':'J1'}).get_json()
cfg=app.load();j=cfg['jobs'][0];j['post']={'enabled':True,'mode':'query','query_id':pq['id']};j['extra_formats']=[];cfg['jobs']=[j];app.save(cfg)
cfg=app.load();j=cfg['jobs'][0]
res2=navi_textrun.run_one_local(dict(j),cfg,tmp/'work',tmp/'backup','manual',1,1)
out['run_query']=res2
con=sqlite3.connect(db);t=[r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like '\\_%' escape '\\'")][0]
out['rows_query']=[list(r) for r in con.execute(f'select * from "{t}"')];con.close()
out['delete_used']=c.delete('/api/m-queries/'+pq['id']).get_json()
# 持ち出し → 持ち込み（後処理のクエリも名前で結び直す）
z=c.get('/api/bundle/export?parts=jobs,queries');blob=z.data
jobs_json=json.loads(zipfile.ZipFile(io.BytesIO(blob)).read('jobs.json'))
out['exported_post']=jobs_json['jobs'][0].get('post')
cfg=app.load();cfg['jobs']=[];app.save(cfg)
r=c.post('/api/bundle/import',data=blob,content_type='application/zip');out['import']=r.get_json()
cfg=app.load();qs={q['name']:q['id'] for q in navi_mrun.load_m_queries()}
out['after_import']=cfg['jobs'][0].get('post',{}).get('query_id')==qs.get('縦持ち')
# 後処理が止まる式なら、公開しない（前の出力は残る）
cfg=app.load();j=cfg['jobs'][0];j['post']=bad;cfg['jobs']=[j];app.save(cfg);cfg=app.load()
out['run_bad']=navi_textrun.run_one_local(dict(cfg['jobs'][0]),cfg,tmp/'work',tmp/'backup','manual',1,1)
con=sqlite3.connect(db);out['rows_after_bad']=con.execute(f'select count(*) from "{t}"').fetchone()[0];con.close()
print(json.dumps(out,ensure_ascii=False,default=str))
'''


class PostAppTest(unittest.TestCase):
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

    def test_meta(self):
        m = self.o['meta']
        self.assertEqual([x['op'] for x in m['ops']][:3], ['unpivot', 'pivot', 'group'])
        self.assertEqual(m['input_name'], '取り出した表')

    def test_saved_with_job(self):
        self.assertEqual(self.o['saved_post']['steps'][0]['attr'], '月')
        self.assertIn('一度実行すると', self.o['preview_before']['no_sample'])

    def test_run_applies_post_before_writing(self):
        o = self.o
        self.assertTrue(o['run']['ok'], o['run'])
        self.assertIn('後処理 ピボット解除 → グループ化 → 並べ替え 3件→3件', o['run']['detail'])
        self.assertEqual([r[1] for r in o['schema']], ['品番', '月', '数量'])
        self.assertEqual({r[1]: r[2] for r in o['schema']}['数量'], 'INTEGER', '集計した列は数の型で書く')
        self.assertEqual(o['rows'], [['A', '1月', 1207], ['A', '2月', 3], ['B', '2月', 5]], 'B の1月は空のセルなので縦にしたとき出ない')
        self.assertTrue(o['csv'].startswith('品番,月,数量'), '同時に出す形式にも後処理が掛かる')
        self.assertEqual(o['work_left'], [], '後処理の中間CSVは残さない')

    def test_preview_uses_sample(self):
        p = self.o['preview']
        self.assertTrue(p['ok'], p)
        self.assertEqual(p['input']['source'], 'sample')
        self.assertEqual(p['input']['columns'], ['品番', '工程', '1月', '2月'])
        self.assertEqual([c['name'] for c in p['columns']], ['品番', '月', '数量'])
        info = p['step_info']
        self.assertEqual(len(info), 3)
        self.assertEqual(info[2]['rows'], p['row_count'])
        self.assertEqual(info[0]['columns'], ['品番', '工程', '月', '数量'], '手順ごとの列（次の手順の列の候補）')
        self.assertEqual(info[0]['rows'], 4, '空のセルは出さない（3行×2か月=6 のうち空が2つ）')
        self.assertEqual(p['input']['types'], ['text', 'text', 'integer', 'integer'])
        s0 = self.o['preview_step0']
        self.assertEqual([c['name'] for c in s0['columns']], ['品番', '工程', '月', '数量'], '1番目の手順のあとの表')
        b = self.o['preview_bad']
        self.assertFalse(b['ok'])
        self.assertEqual(b['error_step'], 0, '止まった手順の番号を返す')
        self.assertEqual(b['step_info'], [None], '止まった手順から先の大きさは出さない')
        self.assertIn('無い列', b['error']['message'])

    def test_to_query_and_run_with_query(self):
        o = self.o
        self.assertTrue(o['to_query']['ok'], o['to_query'])
        self.assertIn('取り出した表', o['to_query']['query']['code'])
        mp = o['mq_preview']
        self.assertTrue(mp['ok'], mp)
        self.assertEqual(mp['input_sample']['job'], '月別を縦に', 'クエリの編集でも、使っている対象の見本で下読みする')
        self.assertTrue(o['run_query']['ok'], o['run_query'])
        self.assertIn('後処理 クエリ「', o['run_query']['detail'])
        self.assertEqual(o['rows_query'], o['rows'])
        self.assertFalse(o['delete_used']['ok'], '後処理に使っているクエリは消さない')

    def test_bundle(self):
        e = self.o['exported_post']
        self.assertEqual(e['query_name'], '縦持ち')
        self.assertNotIn('query_id', e)
        self.assertTrue(self.o['after_import'], '持ち込んだ先のクエリへ名前で結び直す')

    def test_failed_post_does_not_publish(self):
        self.assertFalse(self.o['run_bad']['ok'])
        self.assertIn('無い列', self.o['run_bad']['error'])
        self.assertEqual(self.o['rows_after_bad'], len(self.o['rows_query']), '止まったら前の出力のまま')


if __name__ == '__main__':
    unittest.main()
