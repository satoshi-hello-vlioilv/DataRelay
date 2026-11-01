"""更新履歴（lib/changelog.toml）の題名と日付が、その版のものになっているか。

以前は版を上げるたびに、前の版の題名と日付を「いまの版の値」（APP_VERSION_TITLE・APP_RELEASED_AT）を
指したまま残していた。そのため古い版がみな最新の題名・日付を名乗っていた（149版のうち題名42版・日付95版）。
2.15.0 で更新履歴を TOML のデータへ移し（Rust の中身と同じものを読むため）、どの版も題名・日付を文字で持つ。
ここでは、先頭（最新）の1件が lib/navi_version.py の値と同じで、ほかの版がその値を名乗っていないことを見張る。

実行: python -m unittest tests.test_changelog -v
"""
import sys,tomllib,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SRC=ROOT/'lib'/'changelog.toml'
sys.path.insert(0,str(ROOT/'lib'))

def vkey(v):return tuple(int(x) for x in v.split('.'))

class ChangelogTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import navi_version
  cls.v=navi_version;cls.data=tomllib.loads(SRC.read_text(encoding='utf-8'));cls.items=cls.data['release']

 def test_latest_is_current_version(self):
  top=self.items[0]
  self.assertEqual((top['version'],top['date'],top['title']),(self.v.APP_VERSION,self.v.APP_RELEASED_AT,self.v.APP_VERSION_TITLE),
                   '先頭は navi_version.py と同じ版・日付・題名')

 def test_every_entry_has_the_same_shape(self):
  bad=[e.get('version') for e in self.items if set(e)!={'version','date','title','notes'} or not all(isinstance(n,str) for n in e['notes'])]
  self.assertEqual(bad,[])

 def test_versions_unique_and_descending(self):
  vs=[e['version'] for e in self.items]
  self.assertEqual(len(vs),len(set(vs)),'同じ版が2回ある')
  self.assertEqual(vs,sorted(vs,key=vkey,reverse=True),'新しい順に並んでいない')

 def test_no_date_after_current_release(self):
  """いまの版より後の日付は、ありえない（記録の誤り）。"""
  bad=[f"{e['version']}: {e['date']}" for e in self.items[1:] if e['date'] and e['date']>self.v.APP_RELEASED_AT]
  self.assertEqual(bad,[])

 def test_titles_are_distinct(self):
  """版ごとに題名が違う（同じ題名が並ぶのは、古い版が新しい題名を名乗っていた名残）。"""
  titles=[e['title'] for e in self.items]
  dup=sorted({t for t in titles if titles.count(t)>1})
  self.assertEqual(dup,[])

 def test_python_reads_the_same_data(self):
  import navi_changelog
  self.assertEqual((navi_changelog.CHANGELOG,navi_changelog.DOCS),(self.items,self.data['doc']))
