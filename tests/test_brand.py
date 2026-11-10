"""アイコンと起動画面（2.25.0）の静的な確かめ。

- 窓（desktop/src/main.rs）が起動画面へ送る工程の名前は、どれも起動画面（desktop/splash/index.html）の工程にある
  （名前がずれると、窓が送った工程が黙って捨てられ、起動画面は最初の工程のまま止まって見える）
- 起動画面は、窓が呼ぶ splash.step と splash.fail を持つ
- アイコン（desktop/icons/icon.ico）は、125% の画面で Windows が使う大きさ（20・40 を含む）をそれぞれ持ち、
  32px 以下は太い版（大きい版を縮めた物ではない）。画面のタブのアイコン（static/favicon.svg）は窓のアイコンと同じ形
実行: python -m unittest tests.test_brand -v
"""
import re,struct,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SPLASH=ROOT/'desktop'/'splash'/'index.html'
MAIN=ROOT/'desktop'/'src'/'main.rs'
ICO=ROOT/'desktop'/'icons'/'icon.ico'


def ico_sizes(path):
 """ICO の見出しから、入っているフレームの大きさ（0 は 256）。"""
 b=path.read_bytes()
 _,kind,n=struct.unpack('<HHH',b[:6])
 assert kind==1,'ICO ではありません'
 return sorted((w or 256) for w,_h,*_ in (struct.unpack('<BBBBHHII',b[6+16*i:22+16*i]) for i in range(n)))


class SplashTest(unittest.TestCase):
 def test_steps_sent_by_the_window_exist(self):
  sent=set(re.findall(r'step\(&?app, "([a-z]+)"',MAIN.read_text(encoding='utf-8')))
  self.assertGreaterEqual(sent,{'update','python','backend','open'})
  html=SPLASH.read_text(encoding='utf-8')
  have=set(re.findall(r"\{ id: '([a-z]+)', label:",html))
  self.assertEqual(sent-have,set(),'窓が送るのに、起動画面に無い工程')

 def test_api_the_window_calls(self):
  html=SPLASH.read_text(encoding='utf-8')
  self.assertIn('window.splash = {',html)
  for name in ('step(id, state, detail)','fail(title, detail)'):self.assertIn(name,html)
  # 外の物（字形・絵・スクリプト）を読みに行かない（起動の最中で、ネットにつながらない PC もある）
  self.assertNotRegex(html,r'(?:src|href)=["\']https?:')


class IconTest(unittest.TestCase):
 def test_ico_has_every_size_windows_uses(self):
  self.assertEqual(ico_sizes(ICO),[16,20,24,32,40,48,64,128,256])

 def test_small_frames_are_drawn_bold(self):
  """32px 以下は太い版（窓の枠の無い形）。大きい版の縮小なら、16px で表の線が潰れる。"""
  try:from PIL import Image
  except Exception:self.skipTest('Pillow がありません')
  im=Image.open(ICO)
  im.size=(32,32);small=im.convert('RGBA')
  im.size=(256,256);big=im.convert('RGBA').resize((32,32),Image.LANCZOS)
  diff=sum(abs(a-b) for p,q in zip(small.getdata(),big.getdata()) for a,b in zip(p,q))
  self.assertGreater(diff,32*32*4*8,'32px が大きい版を縮めただけになっている')

 def test_favicon_matches_window_icon(self):
  svg=(ROOT/'static'/'favicon.svg').read_text(encoding='utf-8')
  html=SPLASH.read_text(encoding='utf-8')
  # 形の決め手（表と送り出す矢印）が同じ
  for part in ('M162 90L208 128L162 166','M60 120h92M60 146h92M60 172h64'):
   self.assertIn(part,svg);self.assertIn(part,html)


if __name__=='__main__':unittest.main()
