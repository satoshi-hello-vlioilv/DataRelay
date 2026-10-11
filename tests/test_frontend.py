"""画面（static/app.js・templates/index.html）と窓（desktop/src/main.rs）のつながりを、静的に確かめる。

画面の組み替え（2.1.3: 集計表・共通設定・ログ）で、JS が探す要素が HTML から消えると、
その欄だけが黙って動かなくなる。D&D が窓に横取りされて集計表が組めなかった不具合（2.1.3）も、ここで再発を止める。
本物の WebView の中での動き（札を押して表ができる）は、自己診断（desktop/src/selftest.js）が確かめる。

実行: python -m unittest tests.test_frontend -v
"""
import re,unittest
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


if __name__=='__main__':
 unittest.main()
