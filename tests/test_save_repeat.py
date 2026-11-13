"""Navigator へ結果の保存を頼むときの「ラベルの繰り返し」の指定（2.39.1）。

NaviSaveData の repeat は REPEAT（省かずに書く）・NONREPEAT（省く）・NOCHANGE（RNE に保存した設定のまま）の3つ
（config/docs/Navigator_API.md §4.6）。アプリが必ず繰り返しを要るとき（集計表の表頭・値ごとに分ける出力）だけ REPEAT にし、
それ以外は RNE の設定に任せる（NOCHANGE）。以前は NONREPEAT を渡していたので、RNE で「ラベルを繰り返す」にしていても、
表側の同じ値が省かれて空欄になっていた。

Navigator には繋がない。DLL の代わりに、渡された引数を控える物を置いて確かめる。
実行: python -m unittest tests.test_save_repeat -v
"""
import os,re,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'lib')]
import navigator_api as N  # noqa: E402

N._ansi=lambda v:str(v).encode('cp932')   # mbcs は Windows にしか無い


class FakeDll:
 def __init__(self):self.saved=[]
 def NaviSaveData(self,h,rc,path,ftype,repeat):self.saved.append((int(ftype),int(repeat)))


def api():
 a=object.__new__(N.NavigatorApi);a.dll=FakeDll();a._check=lambda *x,**k:None
 return a


class SaveRepeatTest(unittest.TestCase):
 def test_constants(self):
  self.assertEqual((N.NAVI_REPEAT,N.NAVI_NONREPEAT,N.NAVI_NOCHANGE),(0x04,0x08,0x10))

 def test_follow_rne_unless_required(self):
  a=api()
  a.save_csv(1,Path('x.csv'));a.save_csv(1,Path('x.csv'),repeat_labels=True);a.save_xlsx(1,Path('x.xlsx'))
  self.assertEqual(a.dll.saved,[(N.NAVI_CSV,N.NAVI_NOCHANGE),(N.NAVI_CSV,N.NAVI_REPEAT),(N.NAVI_XLSX,N.NAVI_NOCHANGE)],
                   '繰り返しを要らないときは RNE の設定のまま（NOCHANGE）。省く（NONREPEAT）と、RNE の「ラベルを繰り返す」が効かない')

 def test_no_caller_forces_nonrepeat(self):
  """実行・分割の片・見出しの下読みのどれも、省く書き方を名指ししない（同じ RNE は、分割してもしなくても同じ書き方で出す）。"""
  for f in (ROOT/'app.py',ROOT/'lib'/'navigator_api.py',*sorted((ROOT/'lib').glob('navi_*.py')),ROOT/'lib'/'api_worker.py'):
   code=f.read_text(encoding='utf-8-sig')
   # 引数・既定値・ログの値として渡している所（説明の文と、定数を決める行は見ない）
   hits=[i+1 for i,l in enumerate(code.splitlines()) if re.search(r"[,(=]\s*'?NAVI_NONREPEAT\b",l)]
   self.assertEqual(hits,[],f'{f.name} が NAVI_NONREPEAT を渡している行')


if __name__=='__main__':unittest.main()
