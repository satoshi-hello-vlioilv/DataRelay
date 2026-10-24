"""繰り返し列の展開（2.7.0）: 1行に番号付きで繰り返し入っている列（品名1・数量1・品名2・数量2…）を、繰り返しごとの行に戻す。

前半は列名から繰り返しを見つける（共通の名前・番号・番号の列の名前）、並びで決める（手で）、足りないところの言葉。
後半は式に直して本当に評価し、出る表（列の並び・行の並び・空の回・無い列）と、大きな表での速さを確かめる。

実行: python -m unittest tests.test_repeat -v
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]

import navi_m as M  # noqa: E402
import navi_post as P  # noqa: E402

LEFT = [f'共通{i}' for i in range(1, 11)]
RIGHT = [f'後{i}' for i in range(1, 11)]
STEMS = ['品名', '数量', '単価', '金額', '納期', '区分', '備考', '倉庫', '棚', '担当']
WIDE = LEFT + [f'{s}{k}' for k in range(1, 10) for s in STEMS] + RIGHT     # 利用者の例: 1〜10・101〜110列目が共通、11〜100列目が10列×9回


def run(steps, columns, rows):
    code = P.compile({'enabled': True, 'steps': steps})
    t = M.force(M.Document.from_text(code, '後処理', inputs={M.INPUT_NAME: M.MTable(columns, rows)}).evaluate())
    return t.columns, [[M.force(x) for x in r] for r in t.rows]


class FindTest(unittest.TestCase):
    CASES = [
        ('共通10＋10列×9回＋共通10', WIDE, STEMS, 9, '番号'),
        ('並びが列ごと（品名1〜3 → 数量1〜3）', ['ID'] + [f'{s}{k}' for s in ('品名', '数量') for k in (1, 2, 3)], ['品名', '数量'], 3, '番号'),
        ('ゼロ埋めと全角の数字', ['ID'] + [f'{s}{k}' for k in ('０１', '０２') for s in ('品名', '数量')], ['品名', '数量'], 2, '番号'),
        ('同じ前置き（明細1_品名）', ['伝票'] + [f'明細{k}_{s}' for k in (1, 2, 3) for s in ('品名', '数量')] + ['合計'],
         ['品名', '数量'], 3, '明細番号'),
        ('番号を囲む括弧（品名(1)）', ['伝票'] + [f'{s}({k})' for k in (1, 2) for s in ('品名', '数量')], ['品名', '数量'], 2, '番号'),
        ('一部の回に無い列（備考は1・2回目だけ）',
         ['伝票'] + [x for k in (1, 2, 3, 4) for x in [f'品名{k}', f'数量{k}'] + ([f'備考{k}'] if k < 3 else [])],
         ['品名', '数量', '備考'], 4, '番号'),
        ('番号のすぐ後ろの単位（2024年1月売上）', ['店'] + [f'2024年{m}月{s}' for m in (1, 2, 3) for s in ('売上', '数量')],
         ['売上', '数量'], 3, '2024年月'),
        ('第1回_品名', ['伝票'] + [f'第{k}回_{s}' for k in (1, 2) for s in ('品名', '数量')], ['品名', '数量'], 2, '回'),
        ('共通の列に同じ名前がある', ['品名'] + [f'品名{k}' for k in (1, 2)], ['品名_2'], 2, '番号'),
        ('1列だけの繰り返し（1月〜3月）', ['店', '1月', '2月', '3月'], ['値'], 3, '月'),
    ]

    def test_cases(self):
        for name, cols, names, count, index in self.CASES:
            with self.subTest(name):
                c = P.find_repeats(cols)
                self.assertTrue(c, '見つからない')
                st = c[0]['step']
                self.assertEqual((st['names'], len(st['groups']), st['index']), (names, count, index))
                self.assertEqual(c[0]['common'] + c[0]['columns'], len(cols), '列はどれも共通か繰り返しのどちらか')

    def test_users_example_positions(self):
        c = P.find_repeats(WIDE)[0]
        self.assertEqual((c['first'], c['last'], c['width'], c['count'], c['layout'], c['missing']), (11, 100, 10, 9, 'block', 0))
        self.assertEqual(c['step']['numbers'], list(range(1, 10)))
        self.assertEqual(c['step']['groups'][1][:2], ['品名2', '数量2'])
        others = P.find_repeats(WIDE)[1:]
        self.assertTrue(all(x['columns'] < c['columns'] for x in others), '多く覆う案が先（共通1〜10 のような1列の繰り返しは後ろ）')

    def test_no_numbers(self):
        self.assertEqual(P.find_repeats(['A', 'B', 'C']), [])
        self.assertEqual(P.find_repeats(['A1', 'B']), [], '番号が1つだけの列は繰り返しではない')

    def test_one_column_read_two_ways_is_used_once(self):
        c = P.find_repeats(['店'] + [f'2024年{m}月{s}' for m in (1, 2) for s in ('売上', '数量')])
        used = [x for cand in c for g in cand['step']['groups'] for x in g if x]
        self.assertEqual(len(used), len(set(used)), '2024 と 月 の2通りに読める列を、2つの案に入れない')


class LayoutTest(unittest.TestCase):
    def test_layout_like_auto(self):
        c = P.repeat_by_layout(WIDE, 11, 10, 9)
        self.assertEqual(c['step']['names'], STEMS)
        self.assertEqual(c['step']['numbers'], list(range(1, 10)))
        self.assertEqual(c['how'], 'layout')

    def test_layout_without_numbers(self):
        c = P.repeat_by_layout(['ID', 'a', 'b', 'a2', 'x'], 2, 2, 2)
        self.assertEqual(c['step']['names'], ['a', 'b'], '番号で揃わない列は、1回目の列の名前')
        self.assertEqual(c['step']['groups'], [['a', 'b'], ['a2', 'x']])

    def test_layout_out_of_range(self):
        with self.assertRaises(ValueError):
            P.repeat_by_layout(['a', 'b', 'c'], 2, 2, 2)


class RulesTest(unittest.TestCase):
    def step(self, **kw):
        return P.normalize_step({'op': 'repeat', 'groups': [['a1', 'b1'], ['a2', 'b2']], 'names': ['a', 'b'], **kw})

    def test_normalize(self):
        s = self.step(numbers=[3, 1])
        self.assertEqual(s['numbers'], [1, 2], '番号は増える並びだけ（行の中の順をこれで決めるので）')
        self.assertEqual(s['index'], '番号')
        self.assertTrue(s['drop_empty'])
        s = P.normalize_step({'op': 'repeat', 'groups': [['a1'], ['a2', 'b2', 'c2']], 'names': ['a', 'b']})
        self.assertEqual(s['groups'], [['a1', None], ['a2', 'b2']], '組は名前の数にそろえ、無い列は None')

    def test_problems(self):
        self.assertEqual(P.repeat_problems(self.step()), [])
        self.assertIn('繰り返しを2回分以上選んでください', P.repeat_problems(P.normalize_step({'op': 'repeat', 'groups': [['a']], 'names': ['a']})))
        self.assertIn('まとめた列の名前が重なっています（a）', P.repeat_problems(self.step(names=['a', 'a']))[0])
        self.assertIn('番号', P.repeat_problems(self.step(names=['番号', 'b']))[0])
        self.assertIn('同じ列が2回以上', P.repeat_problems(P.normalize_step({'op': 'repeat', 'groups': [['a1'], ['a1']], 'names': ['a']}))[0])
        bad = P.repeat_problems(self.step(), ['a1', 'b1', 'a2', 'b2', 'a'])
        self.assertEqual(bad, ['共通の列と同じ名前です（a）。まとめた列の名前を変えてください'])
        self.assertIn('表に無い列があります（b2）', P.repeat_problems(self.step(), ['a1', 'b1', 'a2'])[0])
        self.assertIn('1番目（繰り返し列の展開）', P.problems({'enabled': True, 'steps': [{'op': 'repeat'}]})[0])

    def test_summary(self):
        self.assertEqual(P.step_summary(self.step()), '2列×2回 を行に（a・b）')
        self.assertEqual(P.summary({'enabled': True, 'steps': [self.step()]}), '後処理 繰り返し列の展開')


class RunTest(unittest.TestCase):
    COLS = ['伝票', '品名1', '数量1', '備考1', '品名2', '数量2', '備考2', '品名3', '数量3', '合計']
    ROWS = [['A', 'りんご', '1', '甘い', 'みかん', '2', None, None, None, '3'],
            ['B', 'なし', '5', None, None, None, None, None, None, '5']]

    def test_rows_and_columns(self):
        st = P.find_repeats(self.COLS)[0]['step']
        cols, rows = run([st], self.COLS, self.ROWS)
        self.assertEqual(cols, ['伝票', '番号', '品名', '数量', '備考', '合計'], '共通の列は元の左右に、番号とまとめた列は繰り返しのあった所に')
        self.assertEqual(rows, [['A', 1, 'りんご', '1', '甘い', '3'], ['A', 2, 'みかん', '2', None, '3'], ['B', 1, 'なし', '5', None, '5']],
                         '元の行の順・番号の順。値がすべて空の回（A の3回目、B の2・3回目）は行にしない。3回目に無い備考は空')

    def test_keep_empty(self):
        st = dict(P.find_repeats(self.COLS)[0]['step'], drop_empty=False)
        _cols, rows = run([st], self.COLS, self.ROWS)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[2], ['A', 3, None, None, None, '3'])

    def test_common_columns_are_found_in_the_query(self):
        st = P.find_repeats(self.COLS)[0]['step']
        cols, _rows = run([st], self.COLS + ['足した列'], [r + ['x'] for r in self.ROWS])
        self.assertEqual(cols[-1], '足した列', '共通の列は式の中で求めるので、あとから列が増えても写る')

    def test_numbers_from_names_and_odd_names(self):
        cols = ['k', 'a"b 01', 'x[1]', 'a"b 03', 'x[3]']
        st = P.find_repeats(cols)[0]['step']
        self.assertEqual(st['numbers'], [1, 3])
        c, rows = run([st], cols, [['K', '1', '2', '3', '4']])
        self.assertEqual(c, ['k', '番号'] + st['names'])
        self.assertEqual([r[1] for r in rows], [1, 3], '番号の列には、列名の番号を入れる')

    def test_speed(self):
        """表示（エディターの下読み: 見本 1,000 行）は 1 秒より十分短く、実行の 2 万行（展開して 10 万行）も止まらずに終わる。"""
        st = P.find_repeats(WIDE)[0]['step']
        rows = [[f'v{q}_{i}' if not 60 <= i < 100 else None for i in range(110)] for q in range(1000)]
        t0 = time.perf_counter()
        cols, out = run([st], WIDE, rows)
        took = time.perf_counter() - t0
        self.assertEqual((len(cols), len(out)), (31, 5000))
        self.assertLess(took, 2.0, f'1,000行で {took:.2f}秒')


if __name__ == '__main__':
    unittest.main()
