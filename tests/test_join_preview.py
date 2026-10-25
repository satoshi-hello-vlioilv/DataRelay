"""ファイル結合の下読み（2.10.1）。

・名前は保存のための決まりで、繋ぎ方とは関係が無い。作りかけ（名前がまだ無い）でも下読みできる
・できあがりの件数は、先頭だけ取ったときも全体で数える（見せた行数を件数にしない）

画面側の安定性（古い返事を捨てる・打っている欄を描き直しで消さない・保存しても開き直さない）は、
本物の画面を動かして確かめる（PR に評価の結果を書いた）。

実行: python -m unittest tests.test_join_preview -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]
import navi_join as J  # noqa: E402

ORDERS = (['品番', '数量'], [[f'P{i:03d}', str(i)] for i in range(1, 21)])
ITEMS = (['品番', '品名'], [[f'P{i:03d}', f'品名{i}'] for i in range(1, 11)])


def reader(src, limit=None):
 h, rows = ORDERS if 'orders' in src['path'] else ITEMS
 return h, rows[:limit] if limit else rows


def recipe(kind='left', name=''):
 return {'name': name, 'sources': [{'path': 'orders.csv'}, {'path': 'items.csv'}],
         'joins': [{'type': kind, 'keys': [{'left': '品番', 'right': '品番'}]}], 'columns': []}


class JoinPreviewTest(unittest.TestCase):
 def test_preview_without_a_name(self):
  out = J.preview_recipe(recipe(name=''), reader, lines=12)
  self.assertTrue(out['ok'], out.get('error'))

 def test_total_rows_are_counted_beyond_the_shown_rows(self):
  out = J.preview_recipe(recipe('left'), reader, lines=12)
  self.assertEqual(len(out['rows']), 12)
  self.assertEqual(out['stats']['rows'], 20, '左を全部残す: 20行（見せたのは先頭12行）')
  self.assertEqual(out['stats']['shown'], 12)
  out = J.preview_recipe(recipe('inner'), reader, lines=12)
  self.assertEqual(out['stats']['rows'], 10, '両方にあるものだけ: 10行')

 def test_save_still_requires_a_name(self):
  self.assertIn('結合マスタ名を入れてください', J.validate_recipe(recipe(name='')))


if __name__ == '__main__':
 unittest.main()
