"""対象のグループ（2.11.0）。

グループは対象ごとの「グループ名」1つで持つ（jobs の group_name）。別の表は作らない。
・グループの並びは、一覧の並び（display_order）で最初に出てくる順。グループを上下へ動かすのは、対象の並べ替えと同じ
・名前の無い対象は「グループなし」。グループを解くのは、その名前を空にすること（対象は消えない）
・畳んだかどうかは見る人ごとの都合なので、画面（その PC）で覚える。設定には入れない
"""
import re

GROUP_MAX=40
_SPACE=re.compile(r'\s+')


def normalize_group(name):
 """グループ名を整える。続く空白を1つにまとめて前後を落とし、長すぎる名前は切る。文字でない物は空（グループなし）。"""
 if not isinstance(name,str):return ''
 return _SPACE.sub(' ',name).strip()[:GROUP_MAX]

