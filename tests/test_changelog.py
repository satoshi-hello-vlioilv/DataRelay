"""更新履歴（lib/navi_changelog.py）の題名と日付が、その版のものになっているか。

以前は版を上げるたびに、前の版の題名と日付を「いまの版の値」（APP_VERSION_TITLE・APP_RELEASED_AT）を
指したまま残していた。そのため古い版がみな最新の題名・日付を名乗っていた（149版のうち題名42版・日付95版）。
いまの版の値を指してよいのは先頭（最新）の1件だけ、と決めて、ここで見張る。

実行: python -m unittest tests.test_changelog -v
"""
import ast,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SRC=ROOT/'lib'/'navi_changelog.py'
sys.path.insert(0,str(ROOT/'lib'))

def entries():
 """CHANGELOG の各版を (版, 日付のノード, 題名のノード) で返す。値ではなく書き方を見る。"""
 tree=ast.parse(SRC.read_text(encoding='utf-8'))
 node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='CHANGELOG')
 out=[]
 for e in node.elts:
  d={k.value:v for k,v in zip(e.keys,e.values)}
  out.append((d['version'].value,d['date'],d['title']))
 return out

def vkey(v):return tuple(int(x) for x in v.split('.'))

class ChangelogTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import navi_version
  cls.v=navi_version;cls.items=entries()

 def test_latest_is_current_version(self):
  ver,date,title=self.items[0]
  self.assertEqual(ver,self.v.APP_VERSION)

 def test_only_latest_points_to_current_values(self):
  """先頭以外の版が、いまの版の題名・日付を指していない（＝その版の文字で書いてある）。"""
  bad=[f'{ver}: {k}' for ver,date,title in self.items[1:]
       for k,node in (('日付',date),('題名',title)) if not isinstance(node,ast.Constant)]
  self.assertEqual(bad,[])

 def test_versions_unique_and_descending(self):
  vs=[v for v,_,_ in self.items]
  self.assertEqual(len(vs),len(set(vs)),'同じ版が2回ある')
  self.assertEqual(vs,sorted(vs,key=vkey,reverse=True),'新しい順に並んでいない')

 def test_no_date_after_current_release(self):
  """いまの版より後の日付は、ありえない（記録の誤り）。"""
  bad=[f'{ver}: {d.value}' for ver,d,_ in self.items[1:] if isinstance(d,ast.Constant) and d.value and d.value>self.v.APP_RELEASED_AT]
  self.assertEqual(bad,[])

 def test_titles_are_distinct(self):
  """版ごとに題名が違う（同じ題名が並ぶのは、古い版が新しい題名を指していた名残）。"""
  titles=[t.value for _,_,t in self.items[1:] if isinstance(t,ast.Constant)]+[self.v.APP_VERSION_TITLE]
  dup=sorted({t for t in titles if titles.count(t)>1})
  self.assertEqual(dup,[])
