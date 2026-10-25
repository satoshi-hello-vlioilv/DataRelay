"""テキストの読み取り: 読めない記号だけの行（ファイルの終わりの印 0x1A など）を、データにせず外す（2.10.1）。

元のシステムによっては、最後の改行のあとに「ファイルの終わり」の印（Ctrl+Z ＝ 0x1A）や NUL を付けて書き出す。
これまでは、その行も1件として読み、出力の最後に「□」だけの行ができていた（空行ではないので「空行を飛ばす」では外れない）。

実行: python -m unittest tests.test_text_junk -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]
import navi_text as T  # noqa: E402

FIXED = {'name': '固定', 'mode': 'fixed', 'encoding': 'cp932', 'unit': 'char',
         'columns': [{'name': '品番', 'start': 1, 'length': 3}, {'name': '数量', 'start': 4, 'length': 3}]}
DELIM = {'name': '区切り', 'mode': 'delimited', 'delimiter': 'comma', 'encoding': 'cp932',
         'columns': [{'name': '品番', 'field': 1}, {'name': '数量', 'field': 2}]}


def rows(text, layout, **kw):
 with tempfile.TemporaryDirectory() as t:
  p = Path(t) / 'x.txt'
  p.write_bytes(text if isinstance(text, bytes) else text.encode('cp932'))
  h, body, stat = T.read_text_rows(p, dict(layout, **kw))
  return body, stat


class JunkLineTest(unittest.TestCase):
 def test_eof_mark_after_last_line_is_cut(self):
  for layout in (FIXED, dict(FIXED, unit='byte'), DELIM):
   text = 'A01001\r\nB02002\r\n\x1a' if layout['mode'] == 'fixed' else 'A01,001\r\nB02,002\r\n\x1a'
   body, stat = rows(text, layout)
   self.assertEqual(len(body), 2, (layout['mode'], layout.get('unit'), body))
   self.assertEqual(stat['skipped_junk'], 1)

 def test_cut_even_when_blank_lines_are_kept(self):
  body, stat = rows('A01001\r\n\x1a\r\n', FIXED, skip_blank=False)
  self.assertEqual(body, [['A01', '001']])
  self.assertEqual(stat['skipped_junk'], 1)

 def test_nul_and_other_controls_only(self):
  body, stat = rows(b'A01001\r\n\x00\x00\x00\x00\r\n\x1a\x1a\r\n\x7f\r\n', FIXED)
  self.assertEqual(body, [['A01', '001']])
  self.assertEqual(stat['skipped_junk'], 3)

 def test_junk_in_the_middle_is_cut_too(self):
  body, stat = rows('A01001\r\n\x1a\r\nB02002\r\n', FIXED)
  self.assertEqual([r[0] for r in body], ['A01', 'B02'])
  self.assertEqual(stat['skipped_junk'], 1)

 def test_eof_mark_glued_to_the_last_line(self):
  """最後の改行が無く、印が最後の行の後ろに付いているとき。行は残し、印だけを外す"""
  body, stat = rows('A01001\r\nB02002\x1a', FIXED)
  self.assertEqual(body, [['A01', '001'], ['B02', '002']])
  body, stat = rows('A01,001\r\nB02,002\x1a', DELIM)
  self.assertEqual(body, [['A01', '001'], ['B02', '002']])

 def test_real_data_is_kept(self):
  """タブ・空白・全角の文字・記号の入った行はデータ。外さない"""
  body, stat = rows('A01001\r\n\t  \t001\r\n＊＊＊999\r\n', FIXED, skip_blank=True)
  self.assertEqual(len(body), 3, body)
  self.assertEqual(stat['skipped_junk'], 0)

 def test_tail_skip_counts_after_junk_is_removed(self):
  """末尾を読み飛ばす行数は、印の行を除いた本当の行で数える（印の行で1行ぶん食われない）"""
  body, stat = rows('A01001\r\nB02002\r\nTOTAL1\r\n\x1a', FIXED, skip_tail=1)
  self.assertEqual([r[0] for r in body], ['A01', 'B02'])

 def test_preview_says_what_was_cut(self):
  with tempfile.TemporaryDirectory() as t:
   p = Path(t) / 'x.txt'
   p.write_bytes(b'A01001\r\n\x1a')
   out = T.preview_text(p, FIXED)
  self.assertTrue(out['ok'], out)
  self.assertEqual(len(out['rows']), 1)
  self.assertTrue(any('読めない記号だけの行' in n for n in out['notes']), out['notes'])

 def test_csv_rows_of_only_junk(self):
  """CSV を読んだ行（結合の材料・データビュワー）も、印だけの行は外せる"""
  self.assertTrue(T.is_junk_row(['\x1a']))
  self.assertTrue(T.is_junk_row(['\x1a', '', '']))
  self.assertFalse(T.is_junk_row(['', '', '']))
  self.assertFalse(T.is_junk_row(['A01', '\x1a']))


if __name__ == '__main__':
 unittest.main()
