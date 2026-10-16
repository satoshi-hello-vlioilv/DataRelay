"""抽出期間の管理ポイントの見つけ方と、期間の読み戻し（2.5.2）。

実機（2026-10-16・同じ 2.5.1・同じ LOTACH.RNE）で、PC によって失敗した。違いは対象の設定（2.3.0 から利用者ごと）で、
失敗した PC の対象は「管理ポイント名」が空だった。名前が空のときは NaviGetControlPointForTimeSpan（RNE の「時間フィールド」に
決めた時間型）だけを試していたが、LOTACH.RNE の期間は条件欄の「月度」にあり、時間フィールドとしては決まっていないので
NAVI_ERROR_CONTROLPOINT で止まっていた。名前が空でも、RNE の時間型の管理ポイントから選ぶ。
もう1つ、期間の読み戻し（NaviGetPeriod）は ByRef String で、DLL は文字列のありか（アドレス）を書く。それを文字として読み、
化けていた（from=(N)ﾖ）。ほかの文字列の受け取り（_out_string）と同じ読み方にする。DLL は偽物。
実行: python -m unittest tests.test_period_point -v
"""
import ctypes,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navigator_api as N

class JapaneseWindows(unittest.TestCase):
 """日本語の Windows と同じ cp932 で確かめる（mbcs は Linux に無く、CI の英語版 Windows では cp1252 で日本語の名前を扱えない）。
 試験の間だけ替え、ほかの試験には持ち越さない。"""
 def setUp(self):self._ansi=N.ANSI;N.ANSI='cp932'
 def tearDown(self):N.ANSI=self._ansi

KEEP=[]   # DLL が持っている文字列（ありかを書くので、試験の間は消さない）

def put(buf,text,as_pointer):
 """DLL が ByRef String に書く形: as_pointer なら文字列のありか、そうでなければ文字そのもの。"""
 if as_pointer:
  s=ctypes.create_string_buffer(text.encode('ascii'));KEEP.append(s)
  ctypes.memmove(buf,ctypes.byref(ctypes.c_void_p(ctypes.addressof(s))),ctypes.sizeof(ctypes.c_void_p))
 else:
  ctypes.memmove(buf,text.encode('ascii')+b'\0',len(text)+1)

class Dll:
 """points: (置き場, 名前, 型) の並び。timespan: 時間フィールドの時間型があるか。"""
 def __init__(self,points,timespan=False,pointer=True):
  self.points=points;self.timespan=timespan;self.pointer=pointer;self.period=('20250400','20250600')
 def _rc(self,rc,v):ctypes.cast(rc,ctypes.POINTER(ctypes.c_long)).contents.value=v
 def NaviGetControlPointForTimeSpan(self,h,rc):
  self._rc(rc,N.NAVI_OK if self.timespan else 0x11);return 77 if self.timespan else 0
 def NaviGetControlPoint(self,h,rc,label,locate,order):
  name=label.decode(N.ANSI) if isinstance(label,bytes) else str(label)
  for i,(loc,n,_t) in enumerate(self.points):
   if loc==locate and n==name:self._rc(rc,N.NAVI_OK);return 100+i
  self._rc(rc,0x11);return 0
 def NaviGetControlPointNumber(self,h,rc,locate,num):
  self._rc(rc,N.NAVI_OK);ctypes.cast(num,ctypes.POINTER(ctypes.c_long)).contents.value=sum(1 for p in self.points if p[0]==locate)
 def NaviGetControlPoint2(self,h,rc,locate,idx):
  mine=[i for i,p in enumerate(self.points) if p[0]==locate]
  self._rc(rc,N.NAVI_OK);return 100+mine[idx]
 def NaviGetControlPointType(self,hcp,rc,tp):
  self._rc(rc,N.NAVI_OK);ctypes.cast(tp,ctypes.POINTER(ctypes.c_long)).contents.value=self.points[hcp-100][2]
 def NaviGetNameCP(self,hcp,rc,kind,buf):
  self._rc(rc,N.NAVI_OK);put(buf,'',False) if hcp==77 else None
  if hcp!=77:
   n=self.points[hcp-100][1].encode(N.ANSI);ctypes.memmove(buf,n+b'\0',len(n)+1)
 def NaviGetPeriod(self,hcp,rc,disp,cond,f,t,r):
  self._rc(rc,N.NAVI_OK);ctypes.cast(cond,ctypes.POINTER(ctypes.c_long)).contents.value=0
  put(f,self.period[0],self.pointer);put(t,self.period[1],self.pointer);put(r,'',False)
 def NaviChangePeriod(self,hcp,rc,cond,f,t,b):
  self._rc(rc,N.NAVI_OK);self.period=(f.decode(),t.decode())
 def NaviGetLastError(self,*a):return 0x11

def api(dll):
 a=N.NavigatorApi.__new__(N.NavigatorApi);a.dll=dll;a.log=None
 a.error_message=lambda:(3,'');a.error_code=lambda:0x11
 return a

TIME=N.NAVI_CONTROLPOINT_TIME;CAT=3
LOTACH=[(N.NAVI_COND,'BOX実績_設備名',CAT),(N.NAVI_COND,'月度',TIME),(N.NAVI_SIDE,'仕掛区分',CAT),(N.NAVI_SIDE,'BOX実績_設備名',CAT)]


@unittest.skipUnless(sys.platform.startswith('linux') or sys.platform=='win32','ctypes の番地を読む')
class ControlPointTest(JapaneseWindows):
 def test_blank_name_uses_the_time_point_in_the_rne(self):
  """失敗した PC と同じ: 名前が空・時間フィールドなし・条件に時間型「月度」→ 月度を使う（以前は NAVI_ERROR_CONTROLPOINT で止まった）。"""
  a=api(Dll(LOTACH))
  info=a.apply_period(1,'',0,'20260600','20261000')
  self.assertEqual((info['handle'],info['locate'],info['label']),(101,'条件','月度'))
  self.assertEqual(a.dll.period,('20260600','20261000'),'期間を変えた')

 def test_named_point_still_found(self):
  """成功した PC と同じ: 名前「月度」で探して見つかる。"""
  info=api(Dll(LOTACH)).apply_period(1,'月度',0,'20260600','20261000')
  self.assertEqual((info['handle'],info['locate'],info['label']),(101,'条件','月度'))

 def test_time_field_is_used_first_when_the_rne_has_one(self):
  """RNE に時間フィールドが決まっていれば、これまでどおりそれを使う。"""
  info=api(Dll(LOTACH,timespan=True)).apply_period(1,'',0,'20260600','20261000')
  self.assertEqual((info['handle'],info['locate']),(77,'時間フィールド'))

 def test_unit_decides_between_several_time_points(self):
  """時間型が2つ（月度・年月日）あれば、月度の指定には「月」の付く方、年月日の指定には「日」の付く方。条件欄を先に見る。"""
  pts=[(N.NAVI_SIDE,'年月日',TIME),(N.NAVI_COND,'年月日',TIME),(N.NAVI_COND,'月度',TIME)]
  self.assertEqual(api(Dll(pts)).apply_period(1,'',0,'20260600','20261000')['label'],'月度')
  self.assertEqual(api(Dll(pts)).apply_period(1,'',1,'20260601','20261016')['label'],'年月日')

 def test_no_time_point_says_what_to_do(self):
  """時間型が1つも無ければ、名前を決めてもらう（何を探したかを添える）。"""
  with self.assertRaises(Exception) as e:api(Dll([(N.NAVI_COND,'BOX実績_設備名',CAT)])).apply_period(1,'',0,'20260600','20261000')
  self.assertIn('時間型の管理ポイントがありません',str(e.exception))


class ReadbackTest(JapaneseWindows):
 def test_period_written_as_address_is_read(self):
  """DLL が期間の文字列のありかを書いても、期間として読める（以前は from=(N)ﾖ のように化けた）。"""
  self.assertEqual(api(Dll(LOTACH,pointer=True)).get_period(101),{'condition':0,'from':'20250400','to':'20250600'})

 def test_period_written_in_place_is_read(self):
  """渡した入れ物へ直接書く DLL でも読める。"""
  self.assertEqual(api(Dll(LOTACH,pointer=False)).get_period(101),{'condition':0,'from':'20250400','to':'20250600'})

 def test_readback_confirms_the_change(self):
  """変えた直後の読み戻しで、頼んだ期間になっているのが分かる（判定 match に使える形）。"""
  info=api(Dll(LOTACH)).apply_period(1,'月度',0,'20260600','20261000')
  self.assertEqual((info['before']['from'],info['after']['from'],info['after']['to']),('20250400','20260600','20261000'))


if __name__=='__main__':
 unittest.main()
