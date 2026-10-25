"""対象のグループ（2.11.0。2.12.0 で5階層まで）。

グループは対象ごとの「グループの道筋」1つで持つ（jobs の group_name）。別の表は作らない。
・道筋は「親/子/孫」のように / で区切る（例: 生産・品質/品質/圧延）。5階層まで
・グループの並びは、一覧の並び（display_order）で最初に出てくる順。グループを動かすのは、対象の並べ替えと同じ
・名前の無い対象は「グループなし」。グループを解くのは、その段を道筋から外すこと（対象は消えない）
・畳んだかどうかは見る人ごとの都合なので、画面（その PC）で覚える。設定には入れない
"""
import re

GROUP_SEP='/'
GROUP_DEPTH=5
GROUP_MAX=40   # 1段の名前の長さ
_SPACE=re.compile(r'\s+')


def normalize_group(name):
 """グループの道筋を整える。

 段ごとに、続く空白を1つにまとめて前後を落とし、長すぎる名前は切る。空の段は落とし、6段目より下は捨てる。
 文字でない物は空（グループなし）。画面（static/app.js の normGroup）と同じ決まり。
 """
 if not isinstance(name,str):return ''
 parts=[_SPACE.sub(' ',p).strip()[:GROUP_MAX] for p in name.split(GROUP_SEP)]
 return GROUP_SEP.join([p for p in parts if p][:GROUP_DEPTH])
