"""Excel のブック（.xlsx・.xlsm）のセルの値を、中の XML から直接・1回で読む（2.4.0。Power Query の Excel.Workbook 用）。

openpyxl の読み取り専用の形と同じ値にする（試験で突き合わせている）:
- 数: 小数点か E があれば float、無ければ int。日付の書式のセルは日時（1未満は時刻、[h]:mm などは時間の長さ）
- 文字: 共有文字・その場の文字は、ふりがな（<rPh>）を除いて連結する
- 真偽: bool。誤り: '#N/A' などの記号のまま返す（呼ぶ側が誤りのセルにする）。日付にできない数は '#VALUE!'
- 使っている範囲: シートの <dimension>（無い・1セルだけのときは中身から）
日付の書式の判定・シリアル値の変換・名前付き範囲の解釈は openpyxl の関数をそのまま使う（判定の規則を二重に持たない）。
ただし1点だけ openpyxl と変える: 日本語版などの Excel だけが持つ組み込みの日付・時刻の書式（番号 27〜36・50〜58。
yyyy"年"m"月"d"日"・和暦・h"時"mm"分" など）は、openpyxl が知らず数のまま読むが、Power Query は日付・時刻として読むので、そちらに合わせる。
速いのは、セルごとの部品を作らないことと、範囲を求めるためにシートを読み直さないこと。
読めない形（Strict Open XML など）は Unsupported を出し、呼ぶ側が openpyxl で読む。
"""
import zipfile
from contextlib import contextmanager
from xml.etree.ElementTree import ParseError, fromstring, iterparse

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS = '{%s}' % MAIN
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
_C, _V, _IS, _T, _R, _ROW, _SI = NS + 'c', NS + 'v', NS + 'is', NS + 't', NS + 'r', NS + 'row', NS + 'si'
_DIM, _DATA = NS + 'dimension', NS + 'sheetData'


# 東アジア版の Excel の組み込みの日付・時刻の書式（ECMA-376 第1部 18.8.30。書式の文字はブックに書かれない）
EAST_ASIAN_DATE_FORMATS = frozenset(range(27, 37)) | frozenset(range(50, 59))


class Unsupported(Exception):
    """この読み方では読まない形（呼ぶ側は openpyxl に任せる）。"""


class XError(str):
    """誤りのセル（#N/A など）。文字と見分けるための印。"""


def part(base, target):
    """ブックの中の部品の場所。Excel は「worksheets/sheet1.xml」（相対）、ほかの道具は「/xl/…」（絶対）と書く。"""
    target = target or ''
    if target.startswith('/'):
        return target.lstrip('/')
    parts = base.split('/') if base else []
    for seg in target.split('/'):
        if seg == '..':
            if parts:
                parts.pop()
        elif seg and seg != '.':
            parts.append(seg)
    return '/'.join(parts)


def _text(node):
    """<si>・<is> の文字（openpyxl の Text.content と同じ: 直下の <t> と <r><t>。ふりがなの <rPh> は入れない）。"""
    out = []
    for ch in node:
        if ch.tag == _T:
            out.append(ch.text or '')
        elif ch.tag == _R:
            t = ch.find(_T)
            if t is not None:
                out.append(t.text or '')
    return ''.join(out)


def col_index(ref):
    """'AB12' → 28（列の番号。数字の前の英字だけを見る）。"""
    n = 0
    for ch in ref:
        o = ord(ch)
        if o < 65:
            break
        n = n * 26 + ((o - 96) if o > 96 else (o - 64))
    return n


def _row_of(ref):
    i = 0
    while i < len(ref) and ref[i].isalpha():
        i += 1
    return int(ref[i:]) if i < len(ref) else None


def parse_ref(ref):
    """'A1:G9' → (1, 1, 9, 7)。範囲でなければ None。"""
    ref = (ref or '').replace('$', '')
    if ':' not in ref:
        return None
    a, b = ref.split(':', 1)
    r1, r2 = _row_of(a), _row_of(b)
    if not r1 or not r2:
        return None
    return r1, col_index(a), r2, col_index(b)


class Book:
    """1つのブック。部品（共有文字・書式）は使うときに1回だけ読む。
    ファイルは読むときだけ開き、読み終えたらすぐ閉じる（開いたままだと、Windows では利用者が元の Excel を
    上書き保存・削除できなくなる）。"""

    def __init__(self, src):
        from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900
        self.src = src
        try:
            with self._zip() as z:
                names = set(z.namelist())
                wb = fromstring(z.read('xl/workbook.xml'))
                rels = fromstring(z.read('xl/_rels/workbook.xml.rels'))
        except (KeyError, zipfile.BadZipFile, ParseError, OSError) as e:
            raise Unsupported(str(e))
        if wb.tag != NS + 'workbook':
            raise Unsupported('Transitional の形ではありません')
        pr = wb.find(NS + 'workbookPr')
        self.epoch = CALENDAR_MAC_1904 if pr is not None and pr.get('date1904') in ('1', 'true') else CALENDAR_WINDOWS_1900
        rel = {x.get('Id'): (x.get('Type', ''), part('xl', x.get('Target'))) for x in rels}
        self.sheets = []
        for sh in wb.iter(NS + 'sheet'):
            typ, path = rel.get(sh.get(RID), ('', ''))
            if typ.endswith('/worksheet'):
                if path not in names:
                    raise Unsupported(f'シートの部品がありません: {path}')
                self.sheets.append((sh.get('name'), sh.get('state') or 'visible', path))
        self._by_name = {n: p for n, _, p in self.sheets}
        self.defined = [(d.get('name'), d.text or '') for d in wb.iter(NS + 'definedName')
                        if d.get('localSheetId') is None and d.get('hidden') not in ('1', 'true')]
        self._parts = {t.rsplit('/', 1)[-1]: p for t, p in rel.values()}
        self._strings = None
        self._dates = None
        self._cache = {}

    @contextmanager
    def _zip(self):
        with zipfile.ZipFile(self.src) as z:
            yield z

    def has(self, name):
        return name in self._by_name

    def strings(self):
        if self._strings is None:
            out = []
            p = self._parts.get('sharedStrings')
            if p:
                with self._zip() as z, z.open(p) as f:
                    for _, el in iterparse(f):
                        if el.tag == _SI:
                            out.append(_text(el).replace('x005F_', ''))
                            el.clear()
            self._strings = out
        return self._strings

    def date_styles(self):
        """日付・時間の長さの書式を持つセルの書式番号（openpyxl の Stylesheet._normalise_numbers と同じ判定）。"""
        if self._dates is None:
            from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format, is_timedelta_format
            dates, spans = set(), set()
            p = self._parts.get('styles')
            if p:
                with self._zip() as z:
                    st = fromstring(z.read(p))
                custom = {}
                nf = st.find(NS + 'numFmts')
                for x in (nf if nf is not None else []):
                    try:
                        custom[int(x.get('numFmtId'))] = x.get('formatCode')
                    except (TypeError, ValueError):
                        continue
                xfs = st.find(NS + 'cellXfs')
                for i, xf in enumerate(xfs if xfs is not None else []):
                    try:
                        fid = int(xf.get('numFmtId', 0))
                    except ValueError:
                        fid = 0
                    fmt = custom[fid] if fid in custom else BUILTIN_FORMATS.get(fid)
                    if is_date_format(fmt) or (fid not in custom and fid in EAST_ASIAN_DATE_FORMATS):
                        dates.add(i)
                    if is_timedelta_format(fmt):
                        spans.add(i)
            self._dates = (dates, spans)
        return self._dates

    def dimension(self, name):
        """シートが書いている使っている範囲（<dimension>）。sheetData より前だけを読む。"""
        with self._zip() as z, z.open(self._by_name[name]) as f:
            for ev, el in iterparse(f, events=('start',)):
                if el.tag == _DIM:
                    return parse_ref(el.get('ref'))
                if el.tag == _DATA:
                    return None
        return None

    def rows(self, name, stop=None):
        """[(行番号, [(列番号, 値)])]。stop の行を超えたら読むのをやめる。値は None・int・float・str・bool・日時・XError。"""
        key = (name, stop)
        if key in self._cache:
            return self._cache[key]
        if (name, None) in self._cache:
            got = self._cache[(name, None)]
            if stop is None:
                return got
            sub = [r for r in got if r[0] <= stop]
            return sub + got[len(sub):len(sub) + 1]   # 止めた印（stop より先の最初の行）も渡す
        from openpyxl.utils.datetime import from_excel, from_ISO8601
        strings = None
        dates, spans = self.date_styles()
        epoch = self.epoch
        out = []
        r_no = 0
        with self._zip() as z, z.open(self._by_name[name]) as f:
            for _, el in iterparse(f):
                if el.tag != _ROW:
                    continue
                r = el.get('r')
                r_no = int(float(r)) if r else r_no + 1
                if stop is not None and r_no > stop:
                    out.append((r_no, []))   # 止めた印（呼ぶ側が残りの行を空で埋めるため。openpyxl と同じ）
                    break
                cells = []
                c_no = 0
                for c in el:
                    if c.tag != _C:
                        continue
                    ref = c.get('r')
                    c_no = col_index(ref) if ref else c_no + 1
                    t = c.get('t')
                    if t == 'inlineStr':
                        node = c.find(_IS)
                        v = _text(node) if node is not None else None
                    else:
                        v = c.findtext(_V) or None
                        if v is None:
                            pass
                        elif t is None or t == 'n':
                            v = float(v) if ('.' in v or 'E' in v or 'e' in v) else int(v)
                            s = c.get('s')
                            if s and dates and int(s) in dates:
                                try:
                                    v = from_excel(v, epoch, timedelta=int(s) in spans)
                                except (OverflowError, ValueError):
                                    v = XError('#VALUE!')
                        elif t == 's':
                            if strings is None:
                                strings = self.strings()
                            v = strings[int(v)]
                        elif t == 'b':
                            v = bool(int(v))
                        elif t == 'e':
                            v = XError(v)
                        elif t == 'd':
                            v = from_ISO8601(v)
                    cells.append((c_no, v))
                out.append((r_no, cells))
                el.clear()
        self._cache[key] = out
        return out

    def used(self, name):
        """使っている範囲（行・列の最小と最大）。<dimension> を使い、無い・1セルなら中身から（空の文字は使っていない扱い）。"""
        dim = self.dimension(name)
        if dim and dim != (1, 1, 1, 1):
            return dim
        lo_r = lo_c = hi_r = hi_c = None
        for r, cells in self.rows(name):
            for c, v in cells:
                if v is None or v == '':
                    continue
                lo_r = r if lo_r is None else min(lo_r, r)
                hi_r = r if hi_r is None else max(hi_r, r)
                lo_c = c if lo_c is None else min(lo_c, c)
                hi_c = c if hi_c is None else max(hi_c, c)
        return lo_r, lo_c, hi_r, hi_c

    def grid(self, name, lo_r, lo_c, hi_r, hi_c, cap=None):
        """範囲の表（行のリスト）と、cap 行で切ったかどうか。openpyxl の iter_rows(min_row, max_row, min_col, max_col) と同じ行を返す:
        間の抜けた行は空で埋め、範囲の下端より先に行があって止めたときだけ、下端まで空の行で埋める。"""
        width = hi_c - lo_c + 1
        last = hi_r if not cap else min(hi_r, lo_r + cap - 1)
        out = []
        n = lo_r
        broke = False
        for r, cells in self.rows(name, stop=last):
            if r > last:
                broke = True
                break
            while n < r:
                out.append([None] * width)
                n += 1
            if n == r:
                row = [None] * width
                for c, v in cells:
                    if lo_c <= c <= hi_c:
                        row[c - lo_c] = v
                out.append(row)
                n += 1
        if broke:
            while n <= last:
                out.append([None] * width)
                n += 1
        return out, bool(cap) and len(out) >= cap

    def destinations(self):
        """名前付き範囲 → [(名前, シート, 範囲)]（openpyxl の DefinedName.destinations の先頭）。"""
        from openpyxl.workbook.defined_name import DefinedName
        out = []
        for name, text in self.defined:
            if not name or name.startswith('_xlnm'):
                continue
            try:
                for sheet, ref in DefinedName(name, attr_text=text).destinations:
                    out.append((name, sheet, ref))
                    break
            except Exception:
                continue
        return out
