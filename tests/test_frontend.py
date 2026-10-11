"""画面（static/app.js・templates/index.html）と窓（desktop/src/main.rs）のつながりを、静的に確かめる。

画面の組み替え（2.1.3: 集計表・共通設定・ログ）で、JS が探す要素が HTML から消えると、
その欄だけが黙って動かなくなる。D&D が窓に横取りされて集計表が組めなかった不具合（2.1.3）も、ここで再発を止める。
本物の WebView の中での動き（札を押して表ができる）は、自己診断（desktop/src/selftest.js）が確かめる。

実行: python -m unittest tests.test_frontend -v
"""
import json,re,shutil,subprocess,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
JS=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
HTML=(ROOT/'templates'/'index.html').read_text(encoding='utf-8')
MAIN=(ROOT/'desktop'/'src'/'main.rs').read_text(encoding='utf-8')


class IdWiringTest(unittest.TestCase):
 def test_every_id_the_script_looks_for_exists(self):
  refs=set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)",JS))|set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)",JS))
  have=set(re.findall(r'id="([A-Za-z0-9_-]+)"',HTML))|set(re.findall(r'id="([A-Za-z0-9_-]+)"',JS))|set(re.findall(r"\.id='([A-Za-z0-9_-]+)'",JS))
  self.assertGreater(len(refs),300)
  self.assertEqual(sorted(refs-have),[],'JS が探す id は、HTML（か JS が作る部品）にある')

 def test_ids_are_unique(self):
  ids=re.findall(r'id="([A-Za-z0-9_-]+)"',HTML)
  self.assertEqual(sorted({x for x in ids if ids.count(x)>1}),[],'HTML の id は重ならない')


class DragDropTest(unittest.TestCase):
 """Windows の窓（Tauri）は、WebView2 の D&D を横取りする。外さないと画面の HTML5 の D&D（集計表・並べ替え・ファイル落とし）が届かない"""
 def test_window_hands_drag_and_drop_to_the_page(self):
  w=MAIN[MAIN.index('fn window('):]
  w=w[:w.index('.build()')]
  self.assertIn('WebviewWindowBuilder::new(app, "main"',w)
  self.assertIn('.disable_drag_drop_handler()',w,'窓の作りで D&D の横取りを外す')

 def test_stray_file_drop_does_not_navigate(self):
  self.assertRegex(JS,r"window\.addEventListener\('dragover',e=>\{if\(!e\.defaultPrevented&&\[\.\.\.\(e\.dataTransfer\?\.types\|\|\[\]\)\]\.includes\('Files'\)\)",
                   '落とし先の無い所へファイルを落としても、WebView がファイルを開きに行かない')


class PivotDesignerTest(unittest.TestCase):
 """集計表の組み立て（2.1.3 案 J）: 札を押すだけで組める。値は1つの選択（件数・合計など）"""
 def test_buttons_and_sentence(self):
  for i in ('pivot-field-list','pivot-rows','pivot-columns','pivot-measure','pivot-empty','pivot-export-open','pivot-export-pop','pivot-export','pivot-clear'):
   self.assertIn(f'id="{i}"',HTML,i)
  self.assertNotIn('pivot-aggregate',HTML+JS,'集計方法は値の選択へまとめた')
  self.assertIn("togglePivotField(x.dataset.role,x.dataset.col)",JS,'札を押すと置く（D&D だけに頼らない）')
  self.assertRegex(HTML,r'id="pivot-rows"[^>]*class="pv-slot axis-drop"|class="pv-slot axis-drop"[^>]*data-role="rows"','D&D の落とし先も残す')


LOG='''2026-10-10 15:22:10,440 [INFO] [pid 4120] 設定保存 job=設備単位実績 値ごと=7値
2026-10-11 06:00:00,102 [INFO] [pid 4120] 処理開始 trigger=schedule-batch:3 jobs=3
2026-10-11 06:00:01,870 [INFO] [pid 4120] WORKER_START batch_id=b1 line=1 pid=5124 job=設備単位実績 queue_index=1/3
2026-10-11 06:00:02,870 [INFO] [pid 4120] WORKER_START batch_id=b1 line=2 pid=5125 job=在庫一覧 queue_index=2/3
2026-10-11 06:00:41,205 [ERROR] [pid 5125] PARALLEL_JOB_ERROR line=2 job=在庫一覧 elapsed=40.34s error=条件の項目が見つかりません: 倉庫区分
Traceback (most recent call last):
RuntimeError: 条件の項目が見つかりません
2026-10-11 06:01:30,118 [INFO] [pid 4120] PARALLEL_JOB_RESULT line=1 job=設備単位実績 format=sqlite3 rows=14102 columns=10 elapsed=89.95s target=x
2026-10-11 06:01:31,000 [INFO] [pid 4120] JOB_RESULT job=受注残 engine=text format=xlsx rows=30 columns=4 elapsed=1.00s target=y
2026-10-11 06:01:36,560 [WARNING] [pid 4120] 異常終了: 1件失敗しました
2026-10-11 07:00:00,000 [INFO] [pid 4120] 処理開始 trigger=manual jobs=1
2026-10-11 07:00:01,000 [INFO] [pid 4120] PIPELINE job=途中で止まった対象 engine=api
2026-10-11 07:40:12,018 [INFO] [pid 4120] 処理開始 trigger=manual jobs=1
2026-10-11 07:40:12,061 [INFO] [pid 4120] VARIANTS_START line=1 job=設備単位実績 method=combined item=BOX values=LS4,LS3,DL2
2026-10-11 07:42:41,950 [INFO] [pid 4120] PARALLEL_JOB_RESULT line=1 job=設備単位実績 format=sqlite3 rows=4030 columns=10 elapsed=149.88s target=x
2026-10-11 07:42:42,002 [INFO] [pid 4120] 正常終了 | 設備単位実績 4030行
2026-10-11 07:50:00,000 [INFO] [pid 4120] 処理開始 trigger=manual jobs=2
'''


class LogParseTest(unittest.TestCase):
 """ログ・診断（2.1.3 案 K）のログの読み解き。app.js の logparse の塊だけを node で動かす"""
 @classmethod
 def setUpClass(cls):
  cls.node=shutil.which('node')
  if not cls.node:raise unittest.SkipTest('node がありません')
  a=JS.index('/* ---- logparse begin ---- */');b=JS.index('/* ---- logparse end ---- */')
  cls.block=JS[a:b]

 def run_js(self,expr):
  code=self.block+'\nconst runs=buildLogRuns(parseLogEntries(process.argv[1]));\nconsole.log(JSON.stringify('+expr+'));'
  r=subprocess.run([self.node,'-e',code,LOG],capture_output=True,text=True,encoding='utf-8',timeout=60)
  self.assertEqual(r.returncode,0,r.stderr)
  return json.loads(r.stdout)

 def test_runs_newest_first_with_state(self):
  got=self.run_js("runs.map(r=>[r.kind,r.no,r.state,r.failed,logRunState(r)[1]])")
  self.assertEqual(got,[['run',4,'running',0,'実行中'],['run',3,'ok',0,'成功'],['run',2,'stopped',0,'終わりの記録なし'],
                        ['run',1,'ng',1,'失敗 1'],['other',0,'other',0,'その他']],'新しい順。終わりの記録の無い古い実行は「止まった」、最後の実行は「実行中」')

 def test_jobs_rows_and_titles(self):
  got=self.run_js("[runs[3].jobs.map(j=>[j.name,j.state,j.rows]),runs[3].rows,runs[3].seconds,logTriggerName(runs[3].trigger),logRunTitle(runs[1]),logRunTitle(runs[3]),logRunTitle(runs[4])]")
  self.assertEqual(got[0],[['設備単位実績','ok',14102],['在庫一覧','ng',None],['受注残','ok',30]],'API の結果・失敗と、手元の処理の結果を対象ごとに拾う')
  self.assertEqual(got[1:4],[14132,96,'自動'])
  self.assertEqual(got[4],'設備単位実績（値ごと 3値）')
  self.assertEqual(got[5],'3件（設備単位実績・在庫一覧 ほか）')
  self.assertEqual(got[6],'起動・設定の保存など（設定の保存 1回）')

 def test_continuation_lines_join_the_error(self):
  got=self.run_js("runs[3].entries.filter(e=>e.level==='ERROR').map(e=>[e.raw.length,e.msg.split('\\n').length])")
  self.assertEqual(got,[[3,3]],'例外の続き（時刻で始まらない行）は、直前のエラーの1件にまとめる')

 def test_report_text(self):
  rep=self.run_js("logReportText(runs[3],{summary:true,env:true,issues:true,full:false},{'版':'2.1.3','同時実行ライン':6},1)")
  self.assertIn('■ 実行指令 1 · 2026-10-11 06:00:00 · 自動',rep)
  self.assertIn('  - 在庫一覧: 失敗 40.3秒 / 条件の項目が見つかりません: 倉庫区分',rep)
  self.assertIn('■ 環境\n  版: 2.1.3\n  同時実行ライン: 6',rep)
  self.assertIn('■ エラーと注意の行（2件・前後1行）',rep)
  self.assertIn('RuntimeError: 条件の項目が見つかりません',rep,'エラーの続きの行も写す')
  self.assertNotIn('処理開始 trigger=schedule',rep,'前後1行より外は写さない')
  full=self.run_js("logReportText(runs[3],{full:true},null)")
  self.assertIn('■ この実行のログの全文',full);self.assertIn('処理開始 trigger=schedule-batch:3',full)


if __name__=='__main__':
 unittest.main()
