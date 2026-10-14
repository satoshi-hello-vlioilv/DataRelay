"""M 言語（Excel の Power Query の式）を読んで評価する（2.4.0）。

Excel の詳細エディターに出る式を、貼り付けたまま動かすのが目当て。受ける形は3つ:
- 1本の式（`let … in …` など）
- クエリの一覧で「コピー」したときの、`// クエリ名` の行で区切った複数本
- `section Section1; shared 名前 = 式;` の文書
複数本のときは互いに名前で参照できる（「フォルダーから結合」が作る補助クエリ ―― サンプル ファイル・
パラメーター1・ファイルの変換 ―― が、そのまま動く）。

ここは言語だけを持つ（字句 → 構文 → 評価）。関数（Table.SelectRows など）は navi_mlib、ファイルを読む口
（Folder.Files・Excel.Workbook など）は navi_msource にある。DB も画面も触らないので、机の上で確かめられる。

評価は Power Query と同じく遅延する: let の各ステップとレコードの各フィールドは、使われたときに初めて求める
（使わないステップの誤りで止まらない）。表は行ごとの式（each）を素直に回す。
"""
import contextvars
import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta


# ---- 誤り ----------------------------------------------------------------------
class MError(Exception):
    """M の誤りの値。理由（Reason）・説明（Message）・詳細（Detail）を持つ。

    どのクエリのどのステップで起きたかは、最初に気づいた let が書き込む（内側が勝つ）。"""

    def __init__(self, message, reason='Expression.Error', detail=None):
        super().__init__(message)
        self.message = str(message)
        self.reason = str(reason or 'Expression.Error')
        self.detail = detail
        self.query = None
        self.step = None
        self.origin = None      # セルの誤りとして運ばれてきたとき、もとはどのクエリのどのステップで起きたか

    def where(self):
        bits = []
        if self.query:
            bits.append(f'クエリ「{self.query}」')
        if self.step:
            bits.append(f'ステップ「{self.step}」')
        out = ' の '.join(bits)
        if self.origin and self.origin != (self.query, self.step):
            q, st = self.origin
            out += f'（もとは{"クエリ「" + q + "」の " if q and q != self.query else ""}ステップ「{st}」で起きた誤り）'
        return out

    def mark_origin(self):
        """セルの誤りとして残すときに呼ぶ。いま求めているステップを、もとの場所として覚える。"""
        if self.origin is None:
            self.origin = _STEP.get()
        return self

    def __str__(self):
        w = self.where()
        return f'{w}: {self.message}' if w else self.message


class MSyntaxError(MError):
    """書き方の誤り。何行目の何文字目かを持つ（貼り付けた式のどこを直せばよいか分かるように）。"""

    def __init__(self, message, line=0, col=0):
        super().__init__(f'{line}行{col}文字目: {message}' if line else message, 'Expression.SyntaxError')
        self.line = line
        self.col = col


# ---- 値 ------------------------------------------------------------------------
# null → None、logical → bool、number → int/float、text → str、date/datetime/time → datetime の型、
# duration → timedelta、list → Python の list、record → MRecord、table → MTable、function → MFunction、
# type → MType、binary → MBinary（navi_msource）。
_MISS = object()


class ErrorCell:
    """表のセルに入った誤り。触ったとき（フィールドを読んだとき）に初めて誤りになる。

    Power Query でも、型の変換に失敗したセルは「Error」として残り、行ごと捨てたり置き換えたりできる。"""
    __slots__ = ('error',)

    def __init__(self, error):
        self.error = error


_STEP = contextvars.ContextVar('navi_m_step', default=None)


class Thunk:
    """まだ求めていない値（let のステップ・レコードのフィールド）。1回だけ求めて覚える（誤りも覚える）。"""
    __slots__ = ('fn', 'value', 'state', 'name', 'query')

    def __init__(self, fn, name=None, query=None):
        self.fn = fn
        self.value = None
        self.state = 0          # 0=まだ 1=求めている最中 2=値 3=誤り
        self.name = name
        self.query = query

    def get(self):
        if self.state == 2:
            return self.value
        if self.state == 3:
            raise self.value
        if self.state == 1:
            raise MError(f'「{self.name}」が自分自身を参照しています（循環参照）' if self.name else '循環参照です')
        self.state = 1
        token = _STEP.set((self.query, self.name)) if self.name and self.query and self.name != self.query else None
        try:
            v = force(self.fn())
        except MError as e:
            # どこで起きたかは、最初に気づいたステップが書く（クエリそのものの Thunk はクエリ名だけ）
            if self.name and e.step is None and self.name != self.query:
                e.step = self.name
                e.query = self.query
            elif self.query and e.query is None:
                e.query = self.query
            self.state, self.value = 3, e
            raise
        except RecursionError:
            e = MError('式が深すぎて評価できません（再帰が深すぎます）')
            e.step, e.query = self.name, self.query
            self.state, self.value = 3, e
            raise e
        finally:
            if token is not None:
                _STEP.reset(token)
        self.state, self.value = 2, v
        self.fn = None
        return v


def force(v):
    """遅延の値・セルの誤りを、ふつうの値にする。"""
    if isinstance(v, Thunk):
        return v.get()
    if isinstance(v, ErrorCell):
        raise v.error
    return v


class MRecord:
    """レコード。名前の並び・値の並び・名前→位置 の3つで持つ。

    表の行から作るレコードは、表の 名前→位置 を共有する（行ごとに辞書を作らない）。"""
    __slots__ = ('names', 'vals', 'index')

    def __init__(self, names, vals, index=None):
        self.names = names
        self.vals = vals
        self.index = index if index is not None else {n: i for i, n in enumerate(names)}

    @classmethod
    def of(cls, pairs):
        pairs = list(pairs.items()) if isinstance(pairs, dict) else list(pairs)
        return cls([k for k, _ in pairs], [v for _, v in pairs])

    def has(self, name):
        return name in self.index

    def get(self, name, default=_MISS):
        i = self.index.get(name)
        if i is None:
            if default is _MISS:
                raise MError(f'レコードのフィールド「{name}」が見つかりませんでした。', 'Expression.Error',
                             MRecord.of({'Field': name}))
            return default
        v = self.vals[i]
        if isinstance(v, (Thunk, ErrorCell)):
            v = force(v)
        return v

    def raw(self, name):
        return self.vals[self.index[name]]

    def items(self):
        return [(n, self.get(n)) for n in self.names]

    def __repr__(self):
        return '[' + ', '.join(f'{n}=…' for n in self.names) + ']'


class MTable:
    """表。列名の並び・行（list の list）・列の型（並び。None は any）。"""
    __slots__ = ('columns', 'rows', 'types', '_index')

    def __init__(self, columns, rows, types=None):
        self.columns = list(columns)
        self.rows = rows
        self.types = list(types) if types is not None else [None] * len(self.columns)
        if len(self.types) != len(self.columns):
            self.types = (self.types + [None] * len(self.columns))[:len(self.columns)]
        self._index = None
        if len(set(self.columns)) != len(self.columns):
            dup = sorted({c for c in self.columns if self.columns.count(c) > 1})
            raise MError(f'列名が重なっています: {", ".join(dup[:5])}')

    def index(self):
        if self._index is None:
            self._index = {c: i for i, c in enumerate(self.columns)}
        return self._index

    def col(self, name):
        i = self.index().get(name)
        if i is None:
            raise MError(f'テーブルの列「{name}」が見つかりませんでした。', 'Expression.Error',
                         MRecord.of({'Column': name}))
        return i

    def record(self, row):
        return MRecord(self.columns, row, self.index())

    def records(self):
        idx = self.index()
        return [MRecord(self.columns, r, idx) for r in self.rows]

    def __repr__(self):
        return f'<table {len(self.rows)}行×{len(self.columns)}列>'


class MType:
    """型の値。kind（text・number…）と、数の細かい型（Int64 など）・null を許すか・中身の型を持つ。"""
    __slots__ = ('kind', 'nullable', 'facet', 'fields', 'item', 'open')

    def __init__(self, kind, nullable=False, facet=None, fields=None, item=None, open_=False):
        self.kind = kind
        self.nullable = nullable
        self.facet = facet
        self.fields = fields          # record・table: [(名前, MType)]
        self.item = item              # list: 中身の型
        self.open = open_

    def name(self):
        base = (self.facet + '.Type') if self.facet else self.kind
        return ('nullable ' if self.nullable and self.kind not in ('any', 'null') else '') + base

    def __repr__(self):
        return f'type {self.name()}'


PRIMITIVE_TYPES = ('any', 'anynonnull', 'binary', 'date', 'datetime', 'datetimezone', 'duration', 'function',
                   'list', 'logical', 'none', 'null', 'number', 'record', 'table', 'text', 'time', 'type')


class MFunction:
    """関数。利用者が書いた関数（params・body・env）か、組み込み（py）。"""
    __slots__ = ('name', 'params', 'body', 'env', 'py', 'min', 'max')

    def __init__(self, name=None, params=None, body=None, env=None, py=None, min_=0, max_=0):
        self.name = name
        self.params = params or []
        self.body = body
        self.env = env
        self.py = py
        if py is None:
            self.min = sum(1 for p in self.params if not p[1])
            self.max = len(self.params)
        else:
            self.min, self.max = min_, max_

    def __repr__(self):
        return f'<function {self.name or ""}>'


def call(f, args):
    """関数を呼ぶ。組み込みでも、利用者が書いた関数（each・(x) => …）でも同じ口。"""
    f = force(f)
    if not isinstance(f, MFunction):
        raise MError(f'関数ではない値（{type_name(f)}）を呼び出そうとしました。')
    n = len(args)
    if n < f.min or n > f.max:
        want = f'{f.min}' if f.min == f.max else f'{f.min}〜{f.max}'
        raise MError(f'{f.name or "関数"} の引数は {want} 個ですが、{n} 個渡されました。')
    if f.py is not None:
        if n < f.max:
            args = list(args) + [None] * (f.max - n)
        try:
            return f.py(*args)
        except MError:
            raise
        except RecursionError:
            raise MError('式が深すぎて評価できません（再帰が深すぎます）')
        except (TypeError, ValueError, IndexError, KeyError, ZeroDivisionError, OverflowError, AttributeError) as e:
            raise MError(f'{f.name}: {_py_reason(e)}')
    vars_ = {}
    for i, (pname, _opt, _t) in enumerate(f.params):
        vars_[pname] = args[i] if i < n else None
    return f.body(Env(vars_, f.env))


def _py_reason(e):
    s = str(e) or type(e).__name__
    if isinstance(e, ZeroDivisionError):
        return '0 で割りました'
    return s


class Env:
    """名前の置き場の連なり（内側 → 外側）。値は Thunk のままでもよい（引くときに求める）。"""
    __slots__ = ('vars', 'parent')

    def __init__(self, vars_, parent=None):
        self.vars = vars_
        self.parent = parent

    def lookup(self, name):
        e = self
        while e is not None:
            v = e.vars.get(name, _MISS)
            if v is not _MISS:
                return force(v)
            e = e.parent
        if '.' in name and name.split('.')[0] in _namespaces():
            raise MError(f'関数「{name}」はこのアプリではまだ使えません。', 'Expression.Error', MRecord.of({'Name': name}))
        raise MError(f'名前「{name}」が見つかりませんでした。綴りと、参照先のクエリも一緒に貼り付けたかを確かめてください。',
                     'Expression.Error', MRecord.of({'Name': name}))

    def has(self, name):
        e = self
        while e is not None:
            if name in e.vars:
                return True
            e = e.parent
        return False


_NS = []


def _namespaces():
    if not _NS:
        import navi_mlib
        _NS.append(navi_mlib.namespaces() | {'Excel', 'Csv', 'Folder', 'File', 'Web', 'Sql', 'Json', 'Xml', 'OData',
                                              'SharePoint', 'Odbc', 'OleDb', 'Access', 'Pdf', 'Html', 'Splitter',
                                              'Combiner', 'Replacer', 'Comparer', 'Cube', 'Accessing', 'Action',
                                              'Uri', 'Guid', 'Type', 'Value', 'Variable', 'Embedded', 'Geography'})
    return _NS[0]


# ---- 値の扱い（比べる・並べる・型の名前）----------------------------------------
def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def num(v):
    """整数で表せる小数は整数にそろえる（6/3 は 2。M の number は1種類なので見た目を合わせる）。"""
    if isinstance(v, float) and v.is_integer() and abs(v) < 9007199254740992:
        return int(v)
    return v


def type_name(v):
    v = force(v) if isinstance(v, Thunk) else v
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'logical'
    if is_number(v):
        return 'number'
    if isinstance(v, str):
        return 'text'
    if isinstance(v, datetime):
        return 'datetimezone' if v.tzinfo else 'datetime'
    if isinstance(v, date):
        return 'date'
    if isinstance(v, time):
        return 'time'
    if isinstance(v, timedelta):
        return 'duration'
    if isinstance(v, list):
        return 'list'
    if isinstance(v, MRecord):
        return 'record'
    if isinstance(v, MTable):
        return 'table'
    if isinstance(v, MFunction):
        return 'function'
    if isinstance(v, MType):
        return 'type'
    if getattr(v, 'is_binary', False):
        return 'binary'
    return 'any'


def type_of(v):
    return MType(type_name(v))


def is_type(v, t):
    """v is t。数の細かい型（Int64.Type）は number として見る（Power Query と同じ）。"""
    k = t.kind
    if k == 'any':
        return True
    if v is None:
        return k == 'null' or t.nullable
    if k == 'anynonnull':
        return True
    return type_name(v) == k


def equal(a, b):
    a, b = force(a), force(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a) and is_number(b):
        if isinstance(a, float) and math.isnan(a) or isinstance(b, float) and math.isnan(b):
            return False
        return a == b
    ta, tb = type_name(a), type_name(b)
    if ta != tb:
        return False
    if ta == 'list':
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if ta == 'record':
        return set(a.names) == set(b.names) and all(equal(a.get(n), b.get(n)) for n in a.names)
    if ta == 'table':
        if a.columns != b.columns or len(a.rows) != len(b.rows):
            return False
        return all(equal(x, y) for ra, rb in zip(a.rows, b.rows) for x, y in zip(ra, rb))
    if ta == 'binary':
        return a.data() == b.data()
    if ta == 'type':
        return a.kind == b.kind and a.facet == b.facet and a.nullable == b.nullable
    return a == b


_ORDERABLE = ('number', 'text', 'logical', 'date', 'datetime', 'datetimezone', 'time', 'duration')


def compare(a, b):
    """< > のための比べ方。どちらかが null なら None（M では比べた結果が null になる）。"""
    a, b = force(a), force(b)
    if a is None or b is None:
        return None
    ta, tb = type_name(a), type_name(b)
    if ta != tb or ta not in _ORDERABLE:
        raise MError(f'{ta} と {tb} は大小を比べられません。')
    if a < b:
        return -1
    return 1 if a > b else 0


_SORT_RANK = {'null': 0, 'logical': 1, 'number': 2, 'date': 3, 'datetime': 4, 'datetimezone': 5, 'time': 6,
              'duration': 7, 'text': 8}


def sort_key(v):
    """並べ替えの鍵。null がいちばん前。種類が混ざっても落ちないよう、種類の順を先に置く。"""
    v = force(v)
    t = type_name(v)
    r = _SORT_RANK.get(t, 9)
    if r == 9:
        return (r, str(v))
    if t == 'null':
        return (0, 0)
    if t == 'number' and isinstance(v, float) and math.isnan(v):
        return (r, -math.inf)
    if t == 'datetimezone':
        return (r, v.timestamp())
    return (r, v)


def truthy(v, where='条件'):
    v = force(v)
    if isinstance(v, bool):
        return v
    raise MError(f'{where}が true／false ではありません（{type_name(v)}）。')


# ---- 演算 ----------------------------------------------------------------------
def _arith(op, a, b):
    a, b = force(a), force(b)
    if a is None or b is None:
        return None
    if is_number(a) and is_number(b):
        if op == '+':
            return num(a + b)
        if op == '-':
            return num(a - b)
        if op == '*':
            return num(a * b)
        if op == '/':
            if b == 0:
                if a == 0 or (isinstance(a, float) and math.isnan(a)):
                    return math.nan
                return math.inf if a > 0 else -math.inf
            return num(a / b)
    ta, tb = type_name(a), type_name(b)
    try:
        if op == '+':
            if ta in ('date', 'datetime', 'datetimezone', 'time') and tb == 'duration':
                return _add_dur(a, b)
            if ta == 'duration' and tb in ('date', 'datetime', 'datetimezone', 'time'):
                return _add_dur(b, a)
            if ta == tb == 'duration':
                return a + b
        elif op == '-':
            if ta in ('date', 'datetime', 'datetimezone', 'time') and tb == 'duration':
                return _add_dur(a, -b)
            if ta == tb and ta in ('date', 'datetime', 'datetimezone'):
                return a - b
            if ta == tb == 'time':
                return datetime.combine(date.min, a) - datetime.combine(date.min, b)
            if ta == tb == 'duration':
                return a - b
        elif op == '*':
            if ta == 'duration' and tb == 'number':
                return a * b
            if ta == 'number' and tb == 'duration':
                return b * a
        elif op == '/':
            if ta == 'duration' and tb == 'number':
                return a / b
            if ta == tb == 'duration':
                return num(a / b)
    except OverflowError:
        raise MError('日付・時間の計算が範囲を超えました。')
    hint = '（文字をつなぐときは & を使います）' if op == '+' and 'text' in (ta, tb) else ''
    raise MError(f'演算子 {op} は {ta} と {tb} に使えません{hint}。')


def _add_dur(a, d):
    if isinstance(a, time):
        return (datetime.combine(date(2000, 1, 1), a) + d).time()
    if isinstance(a, datetime):
        return a + d
    # date + duration は日付のまま（時刻のぶんは切り捨てる。Power Query と同じ）
    return a + timedelta(days=d.days)


def concat(a, b):
    a, b = force(a), force(b)
    if a is None or b is None:
        return None
    ta, tb = type_name(a), type_name(b)
    if ta == tb == 'text':
        return a + b
    if ta == tb == 'list':
        return a + b
    if ta == tb == 'record':
        pairs = {n: a.raw(n) for n in a.names}
        for n in b.names:
            pairs[n] = b.raw(n)
        return MRecord.of(pairs)
    if ta == tb == 'table':
        from navi_mlib import table_combine
        return table_combine([a, b])
    if ta == 'date' and tb == 'time':
        return datetime.combine(a, b)
    raise MError(f'演算子 & は {ta} と {tb} に使えません。')


def _not(a):
    a = force(a)
    if a is None:
        return None
    return not truthy(a, 'not の値')


def _neg(a):
    a = force(a)
    if a is None:
        return None
    if is_number(a):
        return num(-a)
    if isinstance(a, timedelta):
        return -a
    raise MError(f'- は {type_name(a)} に使えません。')


def item_of(target, key, optional):
    """x{…}。リストなら位置、表なら位置かレコード（一致する1行）。"""
    target, key = force(target), force(key)
    if isinstance(target, list):
        if not is_number(key):
            raise MError('リストの要素は番号で指定します。')
        i = int(key)
        if 0 <= i < len(target):
            return force(target[i])
        if optional:
            return None
        raise MError(f'リストの要素が足りません（{i}番目を読もうとしましたが、{len(target)}個しかありません）。',
                     'Expression.Error')
    if isinstance(target, MTable):
        if is_number(key):
            i = int(key)
            if 0 <= i < len(target.rows):
                return target.record(target.rows[i])
            if optional:
                return None
            raise MError(f'テーブルの行が足りません（{i}番目を読もうとしましたが、{len(target.rows)}行しかありません）。')
        if isinstance(key, MRecord):
            cols = [(target.col(n), key.get(n)) for n in key.names]
            hits = [r for r in target.rows if all(equal(r[i], v) for i, v in cols)]
            if len(hits) == 1:
                return target.record(hits[0])
            if not hits:
                if optional:
                    return None
                what = ', '.join(f'{n}={_show(key.get(n))}' for n in key.names)
                raise MError(f'キーに一致する行がありませんでした（{what}）。'
                             + ('シート名・テーブル名が合っているか確かめてください。' if 'Item' in key.names else ''),
                             'Expression.Error')
            raise MError('キーに一致する行が複数ありました。', 'Expression.Error')
        raise MError('テーブルの行は番号かレコードで指定します。')
    if target is None and optional:
        return None
    raise MError(f'{type_name(target)} に {{…}} は使えません。')


def field_of(target, name, optional):
    target = force(target)
    if isinstance(target, MRecord):
        if optional and not target.has(name):
            return None
        return target.get(name)
    if isinstance(target, MTable):
        if optional and name not in target.index():
            return None
        i = target.col(name)
        return [r[i] for r in target.rows]
    if target is None and optional:
        return None
    raise MError(f'{type_name(target)} から [{name}] は読めません（レコードかテーブルではありません）。')


def project(target, names, optional):
    target = force(target)
    if isinstance(target, MRecord):
        pairs = []
        for n in names:
            if target.has(n):
                pairs.append((n, target.raw(n)))
            elif optional:
                pairs.append((n, None))
            else:
                target.get(n)
        return MRecord.of(pairs)
    if isinstance(target, MTable):
        from navi_mlib import table_select_columns
        return table_select_columns(target, list(names), 2 if optional else 0)
    raise MError(f'{type_name(target)} に [[…]] は使えません。')


def _show(v):
    try:
        v = force(v)
    except MError:
        return 'Error'
    if v is None:
        return 'null'
    if isinstance(v, str):
        return '"' + v + '"'
    return str(v)


# ---- 字句 ----------------------------------------------------------------------
KEYWORDS = {'and', 'as', 'each', 'else', 'error', 'false', 'if', 'in', 'is', 'let', 'meta', 'not', 'null', 'or',
            'otherwise', 'section', 'shared', 'then', 'true', 'try', 'type', 'catch'}
_OPS3 = ('...',)
_OPS2 = ('=>', '<=', '>=', '<>', '..', '??')
_OPS1 = set('=<>+-*/&()[]{},;!?@')


def _id_start(ch):
    return ch == '_' or ch.isalpha()


def _id_part(ch):
    return ch == '_' or ch.isalnum() or unicodedata.category(ch) in ('Mn', 'Mc', 'Pc', 'Cf')


class Tok:
    __slots__ = ('kind', 'value', 'start', 'end')

    def __init__(self, kind, value, start, end):
        self.kind, self.value, self.start, self.end = kind, value, start, end

    def __repr__(self):
        return f'{self.kind}:{self.value!r}'


_ESCAPES = {'cr': '\r', 'lf': '\n', 'tab': '\t', '#': '#'}


def _text_escape(body):
    out = []
    for part in body.split(','):
        p = part.strip()
        if p.lower() in _ESCAPES:
            out.append(_ESCAPES[p.lower()])
        elif len(p) in (4, 8) and all(c in '0123456789abcdefABCDEF' for c in p):
            out.append(chr(int(p, 16)))
        else:
            return None
    return ''.join(out)


def tokenize(src):
    toks = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in ' \t\r\n﻿　' or ch.isspace():
            i += 1
            continue
        if src.startswith('//', i):
            j = src.find('\n', i)
            i = n if j < 0 else j
            continue
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            if j < 0:
                raise _syntax(src, i, 'コメント /* が閉じていません')
            i = j + 2
            continue
        start = i
        if ch == '"':
            text, i = _read_text(src, i)
            toks.append(Tok('text', text, start, i))
            continue
        if ch == '#':
            if i + 1 < n and src[i + 1] == '"':
                text, i = _read_text(src, i + 1)
                toks.append(Tok('qid', text, start, i))
                continue
            j = i + 1
            while j < n and _id_part(src[j]):
                j += 1
            if j == i + 1:
                raise _syntax(src, i, '# の後ろが読めません')
            toks.append(Tok('id', src[i:j], start, j))
            i = j
            continue
        if ch.isdigit() or (ch == '.' and i + 1 < n and src[i + 1].isdigit() and not src.startswith('..', i)):
            v, i = _read_number(src, i)
            toks.append(Tok('num', v, start, i))
            continue
        if _id_start(ch):
            j = i + 1
            while j < n:
                c = src[j]
                if _id_part(c):
                    j += 1
                elif c == '.' and j + 1 < n and _id_start(src[j + 1]):
                    j += 1
                else:
                    break
            word = src[i:j]
            toks.append(Tok('kw' if word in KEYWORDS else 'id', word, start, j))
            i = j
            continue
        three, two = src[i:i + 3], src[i:i + 2]
        if three in _OPS3:
            toks.append(Tok('op', three, start, i + 3))
            i += 3
            continue
        if two in _OPS2:
            toks.append(Tok('op', two, start, i + 2))
            i += 2
            continue
        if ch in _OPS1:
            toks.append(Tok('op', ch, start, i + 1))
            i += 1
            continue
        # 一般化した名前（[売上$] など）の中にだけ現れる文字。式の中に出たら構文で断る
        toks.append(Tok('other', ch, start, i + 1))
        i += 1
    toks.append(Tok('eof', None, n, n))
    return toks


def _read_text(src, i):
    """"…" を読む。"" は " 1文字、#(cr) #(lf) #(tab) #(000D) は制御文字。"""
    n = len(src)
    out = []
    j = i + 1
    while True:
        if j >= n:
            raise _syntax(src, i, '文字列 " が閉じていません')
        c = src[j]
        if c == '"':
            if j + 1 < n and src[j + 1] == '"':
                out.append('"')
                j += 2
                continue
            return ''.join(out), j + 1
        if c == '#' and src.startswith('#(', j):
            k = src.find(')', j)
            if k > 0:
                esc = _text_escape(src[j + 2:k])
                if esc is not None:
                    out.append(esc)
                    j = k + 1
                    continue
        out.append(c)
        j += 1


def _read_number(src, i):
    n = len(src)
    if src.startswith(('0x', '0X'), i):
        j = i + 2
        while j < n and src[j] in '0123456789abcdefABCDEF':
            j += 1
        return int(src[i + 2:j], 16), j
    j = i
    while j < n and src[j].isdigit():
        j += 1
    is_float = False
    if j < n and src[j] == '.' and j + 1 < n and src[j + 1].isdigit():
        is_float = True
        j += 1
        while j < n and src[j].isdigit():
            j += 1
    if j < n and src[j] in 'eE':
        k = j + 1
        if k < n and src[k] in '+-':
            k += 1
        if k < n and src[k].isdigit():
            is_float = True
            j = k
            while j < n and src[j].isdigit():
                j += 1
    text = unicodedata.normalize('NFKC', src[i:j])
    return (num(float(text)) if is_float else int(text)), j


def _line_col(src, pos):
    line = src.count('\n', 0, pos) + 1
    col = pos - (src.rfind('\n', 0, pos) + 1) + 1
    return line, col


def _syntax(src, pos, message):
    line, col = _line_col(src, pos)
    return MSyntaxError(message, line, col)


# ---- 構文 ----------------------------------------------------------------------
# 式は tuple の木にする（1つ目が種類）。評価は compile_node で Python の関数へ直してから行う。
class Parser:
    def __init__(self, src):
        self.src = src
        self.toks = tokenize(src)
        self.i = 0

    # 字句の読み進め
    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        if t.kind != 'eof':
            self.i += 1
        return t

    def at(self, kind, value=None, k=0):
        t = self.peek(k)
        return t.kind == kind and (value is None or t.value == value)

    def at_op(self, value, k=0):
        return self.at('op', value, k)

    def at_kw(self, value, k=0):
        return self.at('kw', value, k)

    def take_op(self, value):
        if self.at_op(value):
            self.next()
            return True
        return False

    def expect_op(self, value, what=None):
        if not self.take_op(value):
            self.fail(f'「{value}」が要るところに「{self.describe()}」があります' + (f'（{what}）' if what else ''))

    def expect_kw(self, value):
        if not self.at_kw(value):
            self.fail(f'「{value}」が要るところに「{self.describe()}」があります')
        self.next()

    def describe(self):
        t = self.peek()
        if t.kind == 'eof':
            return '式の終わり'
        return self.src[t.start:t.end]

    def fail(self, message, tok=None):
        t = tok or self.peek()
        raise _syntax(self.src, t.start, message)

    # 文書
    def parse_document(self):
        if self.at_kw('section'):
            return self.parse_section()
        e = self.parse_expression()
        if not self.at('eof'):
            self.fail(f'式の終わりのあとに「{self.describe()}」が続いています（カンマや括弧の数を確かめてください）')
        return e

    def parse_section(self):
        self.expect_kw('section')
        if self.at('id') or self.at('qid'):
            self.next()
        self.expect_op(';')
        members = []
        while not self.at('eof'):
            if self.at_op('['):          # 属性 [ … ] は読み飛ばす
                depth = 0
                while True:
                    t = self.next()
                    if t.kind == 'eof':
                        self.fail('[ が閉じていません')
                    if t.kind == 'op' and t.value == '[':
                        depth += 1
                    elif t.kind == 'op' and t.value == ']':
                        depth -= 1
                        if depth == 0:
                            break
            if self.at_kw('shared'):
                self.next()
            name = self.parse_name('クエリの名前')
            self.expect_op('=')
            start = self.peek().start          # 式の文字は = のあとから（名前を含めると、取り出した式が自分を参照する）
            e = self.parse_expression()
            end = self.peek().start
            self.expect_op(';', 'section の各クエリは ; で終わります')
            members.append((name, e, self.src[start:end].strip(), start + (len(self.src[start:end]) - len(self.src[start:end].lstrip()))))
        return ('section', members)

    def parse_name(self, what='名前'):
        t = self.peek()
        if t.kind in ('id', 'qid'):
            self.next()
            return t.value
        if t.kind == 'kw' and t.value in ('shared', 'section', 'catch'):
            self.next()
            return t.value
        self.fail(f'{what}が要るところに「{self.describe()}」があります')

    # 式
    def parse_expression(self):
        t = self.peek()
        if t.kind == 'kw':
            v = t.value
            if v == 'let':
                return self.parse_let()
            if v == 'if':
                return self.parse_if()
            if v == 'each':
                self.next()
                return ('fn', [('_', False, None)], None, self.parse_expression(), 'each')
            if v == 'error':
                self.next()
                return ('error', self.parse_expression())
            if v == 'try':
                return self.parse_try()
        if t.kind == 'op' and t.value == '(' and self.function_ahead():
            return self.parse_function()
        return self.parse_coalesce()

    def parse_let(self):
        self.expect_kw('let')
        binds = []
        while True:
            t = self.peek()
            name = self.parse_name('ステップの名前')
            self.expect_op('=', f'ステップ「{name}」')
            e_start = self.peek().start
            e = self.parse_expression()
            binds.append((name, e, (t.start, e_start, self.toks[self.i - 1].end)))
            if self.take_op(','):
                continue
            if self.at_kw('in'):
                break
            self.fail(f'ステップ「{name}」のあとに「,」か「in」が要るところに「{self.describe()}」があります')
        self.expect_kw('in')
        return ('let', binds, self.parse_expression())

    def parse_if(self):
        self.expect_kw('if')
        c = self.parse_expression()
        self.expect_kw('then')
        a = self.parse_expression()
        self.expect_kw('else')
        return ('if', c, a, self.parse_expression())

    def parse_try(self):
        self.expect_kw('try')
        e = self.parse_expression()
        if self.at_kw('otherwise'):
            self.next()
            return ('try', e, self.parse_expression(), None)
        if self.at_kw('catch'):
            self.next()
            if not self.function_ahead():
                self.fail('catch のあとには (e) => … の形の関数を書きます')
            return ('try', e, None, self.parse_function())
        return ('try', e, None, None)

    def function_ahead(self):
        """いまの ( が関数の引数の並びか（対になる ) のあとに => か as … => が来るか）。"""
        if not self.at_op('('):
            return False
        depth, k = 0, 0
        while True:
            t = self.peek(k)
            if t.kind == 'eof':
                return False
            if t.kind == 'op' and t.value in '([{':
                depth += 1
            elif t.kind == 'op' and t.value in ')]}':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        nx = self.peek(k + 1)
        if nx.kind == 'op' and nx.value == '=>':
            return True
        if nx.kind == 'kw' and nx.value == 'as':
            j = k + 2
            if self.peek(j).kind == 'id' and self.peek(j).value == 'nullable':
                j += 1
            return self.peek(j + 1).kind == 'op' and self.peek(j + 1).value == '=>'
        return False

    def parse_function(self):
        self.expect_op('(')
        params = []
        if not self.at_op(')'):
            while True:
                optional = False
                if self.at('id', 'optional') and self.peek(1).kind in ('id', 'qid'):
                    self.next()
                    optional = True
                name = self.parse_name('引数の名前')
                t = None
                if self.at_kw('as'):
                    self.next()
                    t = self.parse_type_ref()
                params.append((name, optional, t))
                if not self.take_op(','):
                    break
        self.expect_op(')')
        if self.at_kw('as'):
            self.next()
            self.parse_type_ref()
        self.expect_op('=>')
        return ('fn', params, None, self.parse_expression(), None)

    def parse_coalesce(self):
        a = self.parse_or()
        if self.take_op('??'):
            return ('coalesce', a, self.parse_coalesce())
        return a

    def parse_or(self):
        a = self.parse_and()
        while self.at_kw('or'):
            self.next()
            a = ('or', a, self.parse_and())
        return a

    def parse_and(self):
        a = self.parse_is()
        while self.at_kw('and'):
            self.next()
            a = ('and', a, self.parse_is())
        return a

    def parse_is(self):
        a = self.parse_as()
        while self.at_kw('is'):
            self.next()
            a = ('is', a, self.parse_type_ref())
        return a

    def parse_as(self):
        a = self.parse_eq()
        while self.at_kw('as'):
            self.next()
            a = ('as', a, self.parse_type_ref())
        return a

    def parse_eq(self):
        a = self.parse_rel()
        while self.at('op') and self.peek().value in ('=', '<>'):
            op = self.next().value
            a = ('bin', op, a, self.parse_rel())
        return a

    def parse_rel(self):
        a = self.parse_add()
        while self.at('op') and self.peek().value in ('<', '>', '<=', '>='):
            op = self.next().value
            a = ('bin', op, a, self.parse_add())
        return a

    def parse_add(self):
        a = self.parse_mul()
        while self.at('op') and self.peek().value in ('+', '-', '&'):
            op = self.next().value
            a = ('bin', op, a, self.parse_mul())
        return a

    def parse_mul(self):
        a = self.parse_meta()
        while self.at('op') and self.peek().value in ('*', '/'):
            op = self.next().value
            a = ('bin', op, a, self.parse_meta())
        return a

    def parse_meta(self):
        a = self.parse_unary()
        while self.at_kw('meta'):
            self.next()
            a = ('meta', a, self.parse_unary())
        return a

    def parse_unary(self):
        t = self.peek()
        if t.kind == 'op' and t.value in ('+', '-'):
            self.next()
            e = self.parse_unary()
            return ('neg', e) if t.value == '-' else ('pos', e)
        if t.kind == 'kw':
            if t.value == 'not':
                self.next()
                return ('not', self.parse_unary())
            if t.value == 'type':
                self.next()
                return ('const', self.parse_type_expr())
            if t.value in ('let', 'if', 'each', 'error', 'try'):
                return self.parse_expression()
        if t.kind == 'op' and t.value == '(' and self.function_ahead():
            return self.parse_function()
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            if self.at_op('{'):
                self.next()
                key = self.parse_expression()
                self.expect_op('}')
                e = ('item', e, key, self.take_op('?'))
            elif self.at_op('['):
                if self.at_op('[', 1):
                    names = self.parse_projection()
                    e = ('proj', e, names, self.take_op('?'))
                else:
                    self.next()
                    name = self.parse_general_name((']',))
                    self.expect_op(']')
                    e = ('field', e, name, self.take_op('?'))
            elif self.at_op('('):
                self.next()
                args = []
                if not self.at_op(')'):
                    while True:
                        args.append(self.parse_expression())
                        if not self.take_op(','):
                            break
                self.expect_op(')', '関数の引数の終わり')
                e = ('call', e, args)
            else:
                return e

    def parse_projection(self):
        self.expect_op('[')
        names = []
        while True:
            self.expect_op('[')
            names.append(self.parse_general_name((']',)))
            self.expect_op(']')
            if not self.take_op(','):
                break
        self.expect_op(']')
        return names

    def parse_general_name(self, stops):
        """[ ] の中の名前（空白・ドットを含んでよい: [Date accessed]・[Source.Name]）。元の綴りのまま取る。"""
        t = self.peek()
        if t.kind == 'qid':
            self.next()
            return t.value
        first = None
        last = None
        while True:
            t = self.peek()
            if t.kind == 'eof' or (t.kind == 'op' and t.value in stops):
                break
            if t.kind == 'op' and t.value in (',', '[', ']', '{', '}') and t.value not in stops:
                break
            first = first or t
            last = t
            self.next()
        if first is None:
            self.fail('名前が要るところに「' + self.describe() + '」があります')
        return self.src[first.start:last.end].strip()

    def record_ahead(self):
        """[ のあと、] より先に = が来るならレコードの書き方、来なければ _ のフィールド。"""
        depth, k = 0, 1
        while True:
            t = self.peek(k)
            if t.kind == 'eof':
                return False
            if t.kind == 'op':
                if t.value in '([{':
                    depth += 1
                elif t.value in ')}':
                    depth -= 1
                elif t.value == ']':
                    if depth == 0:
                        return False
                    depth -= 1
                elif t.value == '=' and depth == 0:
                    return True
                elif t.value == ',' and depth == 0:
                    return True
            k += 1

    def parse_primary(self):
        t = self.peek()
        k = t.kind
        if k == 'num' or k == 'text':
            self.next()
            return ('const', t.value)
        if k == 'kw':
            if t.value in ('true', 'false'):
                self.next()
                return ('const', t.value == 'true')
            if t.value == 'null':
                self.next()
                return ('const', None)
        if k in ('id', 'qid'):
            self.next()
            return ('id', t.value, t.start)
        if k == 'op':
            v = t.value
            if v == '@':
                self.next()
                return ('id', self.parse_name(), t.start)
            if v == '(':
                self.next()
                e = self.parse_expression()
                self.expect_op(')', '括弧の終わり')
                return e
            if v == '{':
                return self.parse_list()
            if v == '[':
                if self.at_op('[', 1):
                    return ('proj', None, self.parse_projection(), self.take_op('?'))
                if self.at_op(']', 1):
                    self.next()
                    self.next()
                    return ('record', [])
                if self.record_ahead():
                    return self.parse_record()
                self.next()
                name = self.parse_general_name((']',))
                self.expect_op(']')
                return ('field', None, name, self.take_op('?'))
            if v == '...':
                self.next()
                return ('error', ('const', 'まだ書かれていない式（...）です'))
        self.fail(f'ここに「{self.describe()}」は書けません')

    def parse_list(self):
        self.expect_op('{')
        items = []
        if not self.at_op('}'):
            while True:
                a = self.parse_expression()
                if self.take_op('..'):
                    items.append(('range', a, self.parse_expression()))
                else:
                    items.append(a)
                if not self.take_op(','):
                    break
        self.expect_op('}', 'リストの終わり')
        return ('list', items)

    def parse_record(self):
        self.expect_op('[')
        fields = []
        while True:
            name = self.parse_general_name(('=',))
            self.expect_op('=', f'フィールド「{name}」')
            fields.append((name, self.parse_expression()))
            if not self.take_op(','):
                break
        self.expect_op(']', 'レコードの終わり')
        return ('record', fields)

    # 型
    def parse_type_ref(self):
        """as・is のあとの型（nullable 付きの基本の型。ほかは式として読み、評価して型にする）。"""
        nullable = False
        if self.at('id', 'nullable'):
            self.next()
            nullable = True
        t = self.peek()
        if t.kind in ('id', 'kw') and t.value in PRIMITIVE_TYPES:
            self.next()
            return ('const', MType(t.value, nullable))
        e = self.parse_postfix()
        return ('nullable', e) if nullable else e

    def parse_type_expr(self):
        """type のあとの型。基本の型・nullable・{型}・[a = 型]・table [ … ]・function (…) as 型。"""
        t = self.peek()
        if t.kind == 'id' and t.value == 'nullable':
            self.next()
            inner = self.parse_type_expr()
            if isinstance(inner, MType):
                inner.nullable = True
            return inner
        if t.kind in ('id', 'kw') and t.value in PRIMITIVE_TYPES:
            self.next()
            if t.value == 'table' and self.at_op('['):
                rec = self.parse_record_type()
                return MType('table', fields=rec.fields)
            if t.value == 'function' and self.at_op('('):
                self.skip_balanced()
                if self.at_kw('as'):
                    self.next()
                    self.parse_type_expr()
                return MType('function')
            return MType(t.value)
        if self.at_op('{'):
            self.next()
            item = self.parse_type_expr()
            self.expect_op('}')
            return MType('list', item=item if isinstance(item, MType) else None)
        if self.at_op('['):
            return self.parse_record_type()
        if self.at_op('('):
            self.next()
            inner = self.parse_type_expr()
            self.expect_op(')')
            return inner
        # Int64.Type などの名前。評価しないと分からないので、型の名前だけ見て決める
        if t.kind in ('id', 'qid'):
            self.next()
            return _NAMED_TYPES.get(t.value) or MType('any')
        self.fail(f'型が要るところに「{self.describe()}」があります')

    def parse_record_type(self):
        self.expect_op('[')
        fields, open_ = [], False
        if not self.at_op(']'):
            while True:
                if self.at_op('...'):
                    self.next()
                    open_ = True
                    break
                if self.at('id', 'optional') and not self.at_op('=', 1):
                    self.next()
                name = self.parse_general_name(('=', ',', ']'))
                ft = MType('any')
                if self.take_op('='):
                    got = self.parse_type_expr()
                    ft = got if isinstance(got, MType) else MType('any')
                fields.append((name, ft))
                if not self.take_op(','):
                    break
        self.expect_op(']')
        return MType('record', fields=fields, open_=open_)

    def skip_balanced(self):
        depth = 0
        while True:
            t = self.next()
            if t.kind == 'eof':
                self.fail('括弧が閉じていません')
            if t.kind == 'op' and t.value in '([{':
                depth += 1
            elif t.kind == 'op' and t.value in ')]}':
                depth -= 1
                if depth == 0:
                    return


# Int64.Type などの名前の型（式の中でも型の中でも同じものを指す）
_NAMED_TYPES = {}


def _named(name, kind, facet=None):
    _NAMED_TYPES[name] = MType(kind, facet=facet)


for _n, _f in (('Int64', 'Int64'), ('Int32', 'Int32'), ('Int16', 'Int16'), ('Int8', 'Int8'), ('Byte', 'Byte'),
               ('Currency', 'Currency'), ('Percentage', 'Percentage'), ('Decimal', 'Decimal'),
               ('Double', 'Double'), ('Single', 'Single'), ('Number', None)):
    _named(f'{_n}.Type', 'number', _f)
for _n, _k in (('Text', 'text'), ('Date', 'date'), ('DateTime', 'datetime'), ('DateTimeZone', 'datetimezone'),
               ('Time', 'time'), ('Duration', 'duration'), ('Logical', 'logical'), ('Binary', 'binary'),
               ('List', 'list'), ('Record', 'record'), ('Table', 'table'), ('Function', 'function'),
               ('Type', 'type'), ('Any', 'any'), ('Null', 'null'), ('None', 'none'), ('Character', 'text'),
               ('Guid', 'text'), ('Uri', 'text'), ('Password', 'text')):
    _named(f'{_n}.Type', _k)
del _n, _f, _k


def named_types():
    return dict(_NAMED_TYPES)


def parse(src):
    return Parser(src).parse_document()


# ---- 評価（木 → Python の関数）---------------------------------------------------
def compile_node(node, query=None):
    """式の木を、env を受け取って値を返す関数へ直す。行ごとに評価する each を速く回すため。"""
    k = node[0]
    if k == 'const':
        v = node[1]
        return lambda env: v
    if k == 'id':
        name = node[1]
        return lambda env: env.lookup(name)
    if k == 'let':
        binds = [(n, compile_node(e, query)) for n, e, _ in node[1]]
        body = compile_node(node[2], query)

        def run_let(env):
            e = Env({}, env)
            for n, fn in binds:
                e.vars[n] = Thunk((lambda fn=fn: fn(e)), n, query)
            return body(e)
        return run_let
    if k == 'if':
        c, a, b = (compile_node(x, query) for x in node[1:4])
        return lambda env: a(env) if truthy(c(env), 'if の条件') else b(env)
    if k == 'fn':
        params = node[1]
        body = compile_node(node[3], query)
        label = 'each' if node[4] == 'each' else None

        def make_fn(env):
            return MFunction(label, params, body, env)
        return make_fn
    if k == 'error':
        inner = compile_node(node[1], query)

        def raise_error(env):
            v = force(inner(env))
            if isinstance(v, MRecord):
                raise MError(_s(v.get('Message', '')) or 'エラー', _s(v.get('Reason', '')) or 'Expression.Error',
                             v.get('Detail', None))
            raise MError(_s(v) if v is not None else 'エラー')
        return raise_error
    if k == 'try':
        inner = compile_node(node[1], query)
        other = compile_node(node[2], query) if node[2] is not None else None
        catch = compile_node(node[3], query) if node[3] is not None else None

        def run_try(env):
            try:
                v = force(inner(env))
            except MError as e:
                if other is not None:
                    return other(env)
                if catch is not None:
                    f = catch(env)
                    return call(f, [error_record(e)] if f.max >= 1 else [])
                return MRecord.of({'HasError': True, 'Error': error_record(e)})
            if other is not None or catch is not None:
                return v
            return MRecord.of({'HasError': False, 'Value': v})
        return run_try
    if k == 'coalesce':
        a, b = compile_node(node[1], query), compile_node(node[2], query)

        def run_coalesce(env):
            v = force(a(env))
            return b(env) if v is None else v
        return run_coalesce
    if k == 'or':
        a, b = compile_node(node[1], query), compile_node(node[2], query)

        def run_or(env):
            x = force(a(env))
            if x is True:
                return True
            if x is not None and not isinstance(x, bool):
                truthy(x, 'or の左')
            y = force(b(env))
            if y is True:
                return True
            if y is not None and not isinstance(y, bool):
                truthy(y, 'or の右')
            return None if (x is None or y is None) else False
        return run_or
    if k == 'and':
        a, b = compile_node(node[1], query), compile_node(node[2], query)

        def run_and(env):
            x = force(a(env))
            if x is False:
                return False
            if x is not None and not isinstance(x, bool):
                truthy(x, 'and の左')
            y = force(b(env))
            if y is False:
                return False
            if y is not None and not isinstance(y, bool):
                truthy(y, 'and の右')
            return None if (x is None or y is None) else True
        return run_and
    if k == 'not':
        a = compile_node(node[1], query)
        return lambda env: _not(a(env))
    if k == 'neg':
        a = compile_node(node[1], query)
        return lambda env: _neg(a(env))
    if k == 'pos':
        a = compile_node(node[1], query)
        return lambda env: force(a(env))
    if k == 'bin':
        op = node[1]
        a, b = compile_node(node[2], query), compile_node(node[3], query)
        if op == '=':
            return lambda env: equal(a(env), b(env))
        if op == '<>':
            return lambda env: not equal(a(env), b(env))
        if op in ('<', '>', '<=', '>='):
            test = {'<': lambda r: r < 0, '>': lambda r: r > 0, '<=': lambda r: r <= 0, '>=': lambda r: r >= 0}[op]

            def run_cmp(env):
                r = compare(a(env), b(env))
                return None if r is None else test(r)
            return run_cmp
        if op == '&':
            return lambda env: concat(a(env), b(env))
        return lambda env: _arith(op, a(env), b(env))
    if k == 'is':
        a, t = compile_node(node[1], query), compile_node(node[2], query)
        return lambda env: is_type(force(a(env)), _as_type(t(env)))
    if k == 'as':
        a, t = compile_node(node[1], query), compile_node(node[2], query)

        def run_as(env):
            v = force(a(env))
            tt = _as_type(t(env))
            if not is_type(v, tt):
                raise MError(f'{type_name(v)} の値を {tt.name()} として扱えません。')
            return v
        return run_as
    if k == 'nullable':
        a = compile_node(node[1], query)

        def run_nullable(env):
            t = _as_type(a(env))
            return MType(t.kind, True, t.facet, t.fields, t.item)
        return run_nullable
    if k == 'meta':
        a = compile_node(node[1], query)
        return lambda env: a(env)       # メタデータは持たない（値だけ使う。パラメーターの印など）
    if k == 'list':
        parts = []
        for it in node[1]:
            if it[0] == 'range':
                parts.append(('range', compile_node(it[1], query), compile_node(it[2], query)))
            else:
                parts.append(('one', compile_node(it, query), None))

        def run_list(env):
            out = []
            for kind, a, b in parts:
                if kind == 'one':
                    out.append(a(env))
                else:
                    lo, hi = force(a(env)), force(b(env))
                    if isinstance(lo, str) and isinstance(hi, str) and len(lo) == len(hi) == 1:
                        out.extend(chr(c) for c in range(ord(lo), ord(hi) + 1))     # {"0".."9"}・{"A".."Z"}
                        continue
                    if not (is_number(lo) and is_number(hi)):
                        raise MError('{a..b} は整数か1文字で書きます。')
                    out.extend(range(int(lo), int(hi) + 1))
            return out
        return run_list
    if k == 'record':
        fields = [(n, compile_node(e, query)) for n, e in node[1]]
        names = [n for n, _ in fields]
        if len(set(names)) != len(names):
            raise MError('レコードに同じ名前のフィールドが2つあります。')

        def run_record(env):
            e = Env({}, env)
            vals = []
            for n, fn in fields:
                th = Thunk((lambda fn=fn: fn(e)), None)
                e.vars[n] = th
                vals.append(th)
            return MRecord(names, vals)
        return run_record
    if k == 'field':
        name, optional = node[2], node[3]
        if node[1] is None:
            return lambda env: field_of(env.lookup('_'), name, optional)
        t = compile_node(node[1], query)
        return lambda env: field_of(t(env), name, optional)
    if k == 'proj':
        names, optional = node[2], node[3]
        if node[1] is None:
            return lambda env: project(env.lookup('_'), names, optional)
        t = compile_node(node[1], query)
        return lambda env: project(t(env), names, optional)
    if k == 'item':
        t, key, optional = compile_node(node[1], query), compile_node(node[2], query), node[3]
        return lambda env: item_of(t(env), key(env), optional)
    if k == 'call':
        f = compile_node(node[1], query)
        args = [compile_node(a, query) for a in node[2]]

        def run_call(env):
            fn = force(f(env))
            return call(fn, [force(a(env)) for a in args])
        return run_call
    raise MError(f'評価できない式です（{k}）')


def _s(v):
    return '' if v is None else str(v)


def _as_type(v):
    v = force(v)
    if isinstance(v, MType):
        return v
    raise MError(f'型が要るところに {type_name(v)} があります。')


def error_record(e):
    return MRecord.of({'Reason': e.reason, 'Message': e.message, 'Detail': e.detail})


# ---- 文書（複数のクエリ）---------------------------------------------------------
_HOST = contextvars.ContextVar('navi_m_host', default=None)


def host():
    """いま評価している文書の、外の世界とのつなぎ（パスの読み替え・下読みの行数など）。"""
    return _HOST.get()


class Host:
    """評価の外側から渡すもの。

    resolve: パスの読み替え（相対パス → 配布の置き場 など）。row_cap: 下読みのとき、1つのシートから読む行の上限。
    file_cap: 下読みのとき、フォルダーから読むファイルの上限。notes: 下読みで省いたことなどを書き留める。"""

    def __init__(self, resolve=None, row_cap=None, file_cap=None, now=None):
        self.resolve = resolve or (lambda p: p)
        self.row_cap = row_cap
        self.file_cap = file_cap
        self.now = now
        self.notes = []
        self.files_read = []

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)


class Query:
    __slots__ = ('name', 'text', 'node', 'error', 'offset', 'start')

    def __init__(self, name, text, node=None, error=None, offset=0, start=None):
        # offset: 式の木の位置の原点（貼り付けた全体の中）。start: この式の文字の始まり（全体の中）
        self.name, self.text, self.node, self.error, self.offset = name, text, node, error, offset
        self.start = offset if start is None else start


def _split_queries(text):
    """`// 名前` の行（行頭）で区切った複数のクエリ。区切りが無ければ None。"""
    lines = text.splitlines()
    heads = []
    for i, line in enumerate(lines):
        if line.startswith('//') and not line.startswith('///'):
            name = line[2:].strip()
            if name and not name.startswith('/'):
                heads.append((i, name))
    if not heads:
        return None
    chunks = []
    lead = '\n'.join(lines[:heads[0][0]]).strip()
    if lead:
        return None             # 区切りの前に式があるなら、コメントはただのコメント
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    for k, (i, name) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        raw = '\n'.join(lines[i + 1:end])
        body = raw.strip()
        if not body:
            continue
        chunks.append((name, body, starts[i + 1] + (len(raw) - len(raw.lstrip()))))
    return chunks or None


def read_queries(text, default_name='クエリ1'):
    """貼り付けた文字から、クエリの並びを作る。書き方の誤りは例外（何行目かを付けて）。"""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
    if not text.strip():
        raise MSyntaxError('式がありません。Power Query の詳細エディターの中身を貼り付けてください。')
    head = text.lstrip()
    if head.startswith('section') and (len(head) == 7 or not _id_part(head[7])):
        node = parse(text)
        return [Query(n, t, e, offset=0, start=o) for n, e, t, o in node[1]]
    chunks = _split_queries(text)
    if chunks and len(chunks) >= 1:
        out, first_err = [], None
        for name, body, offset in chunks:
            try:
                out.append(Query(name, body, parse(body), offset=offset))
            except MSyntaxError as e:
                first_err = first_err or (name, e)
                break
        if first_err is None:
            names = [q.name for q in out]
            if len(set(names)) != len(names):
                raise MSyntaxError('同じ名前のクエリが2つあります: ' + ', '.join(sorted({n for n in names if names.count(n) > 1})))
            return out
        # 区切りで分けて読めないときは、全体を1本として読んでみる（区切りに見えたのがただのコメントだった）
        try:
            return [Query(chunks[0][0] if len(chunks) == 1 else default_name, text, parse(text))]
        except MSyntaxError:
            name, e = first_err
            raise MSyntaxError(f'クエリ「{name}」の {e.message}', e.line, e.col) from None
    return [Query(default_name, text, parse(text))]


def referenced_names(node, acc=None):
    """式の中で名前として参照しているもの（関数名も含む）。どのクエリが主かを決めるのに使う。"""
    acc = set() if acc is None else acc
    if isinstance(node, tuple):
        if node and node[0] == 'id':
            acc.add(node[1])
            return acc
        for x in node[1:]:
            referenced_names(x, acc)
    elif isinstance(node, list):
        for x in node:
            referenced_names(x, acc)
    return acc


_HELPER_NAMES = re.compile(r'^(サンプル ファイル(の変換)?|ファイルの変換|パラメーター\d+|Sample File|Transform Sample File|Transform File'
                           r'|Parameter\d+)( \(\d+\))?( から .+| from .+)?$')


def is_helper_name(name):
    """Excel の「フォルダーから結合」が作る補助クエリの名前か（日本語版・英語版。(2) 付き・「〜から」付きも）。"""
    return bool(_HELPER_NAMES.match(str(name or '')))


class Document:
    """クエリの集まり。互いに名前で参照でき、標準の関数（navi_mlib）の上に乗る。"""

    def __init__(self, queries, library=None):
        self.queries = list(queries)
        self.by_name = {q.name: q for q in self.queries}
        if library is None:
            import navi_mlib
            library = navi_mlib.library()
        self.library = library

    @classmethod
    def from_text(cls, text, default_name='クエリ1', library=None):
        return cls(read_queries(text, default_name), library)

    def names(self):
        return [q.name for q in self.queries]

    def main_name(self):
        """出力に使うクエリの既定: ほかのクエリから参照されていない、ヘルパー クエリでも関数でもないクエリの最後のもの。

        「フォルダーから結合」の見本用のクエリ（サンプル ファイルの変換）も、どこからも参照されないので、名前で外す。"""
        used = set()
        for q in self.queries:
            used |= referenced_names(q.node) & set(self.by_name) - {q.name}
        free = [q.name for q in self.queries if q.name not in used]
        best = [n for n in free if not is_helper_name(n) and self.kind(n) == 'query']
        return (best or free or self.names())[-1]

    def helpers(self):
        """Excel の画面で「ヘルパー クエリ」の箱に入るもの（名前が決まった形か、ほかのクエリから参照されている物）。"""
        used = set()
        for q in self.queries:
            used |= referenced_names(q.node) & set(self.by_name) - {q.name}
        return [n for n in self.names() if is_helper_name(n) or n in used]

    def dependencies(self, name):
        q = self.by_name[name]
        return sorted(referenced_names(q.node) & set(self.by_name) - {name})

    def step_spans(self, name):
        """ステップごとの式の場所（貼り付けた全体の中の [始まり, 終わり)）。数式バーで1つのステップだけを見せ、直すために使う。"""
        q = self.by_name[name]
        if q.node and q.node[0] == 'let':
            return [(n, q.offset + p[1], q.offset + p[2]) for n, _e, p in q.node[1]]
        return [(name, q.start, q.start + len(q.text))]

    def kind(self, name):
        """クエリの種類: 'function'（関数）・'parameter'（パラメーター）・'query'（表などを返すふつうのクエリ）。"""
        node = self.by_name[name].node
        if node and node[0] == 'meta':
            return 'parameter'
        if node and node[0] == 'fn':
            return 'function'
        if node and node[0] == 'let' and node[2][0] == 'id':
            for n, e, _p in node[1]:
                if n == node[2][1] and e[0] == 'fn':
                    return 'function'
        return 'query'

    def missing_names(self):
        """式の中で使っているのに、どこにも無い名前（関数でもステップでも引数でもクエリでもない）。

        詳細エディターからはメインのクエリしか写せないので、補助のクエリ（ファイルの変換 など）を置き忘れやすい。
        実行して初めて分かるのでは遅いので、貼り付けた時点で知らせるために使う。"""
        used, bound = set(), set(self.by_name) | {'_'}

        def walk(node):
            if not isinstance(node, tuple) or not node:
                return
            k = node[0]
            if k == 'id':
                used.add(node[1])
            elif k == 'let':
                for n, e, _p in node[1]:
                    bound.add(n)
                    walk(e)
                walk(node[2])
            elif k == 'fn':
                bound.update(p[0] for p in node[1])
                walk(node[3])
            elif k == 'record':
                for n, e in node[1]:
                    bound.add(n)
                    walk(e)
            elif k == 'list':
                for it in node[1]:
                    walk(it)
            elif k == 'call':
                walk(node[1])
                for a in node[2]:
                    walk(a)
            elif k == 'section':
                for m in node[1]:
                    walk(m[1])
            else:
                for x in node[1:]:
                    if isinstance(x, tuple):
                        walk(x)
        for q in self.queries:
            walk(q.node)
        return sorted(n for n in used - bound if n not in self.library and n not in _NAMED_TYPES)

    def steps(self, name):
        """クエリの「適用したステップ」（いちばん外の let の各ステップ）。let でなければ1つだけ。"""
        q = self.by_name[name]
        if q.node and q.node[0] == 'let':
            return [n for n, _e, _p in q.node[1]]
        return [name]

    def _env(self, host_):
        root = Env(self.library)
        qenv = Env({}, root)
        for q in self.queries:
            qenv.vars[q.name] = Thunk((lambda q=q: compile_node(q.node, q.name)(qenv)), q.name, q.name)
        return qenv

    def evaluate(self, name=None, host_=None, step=None):
        """クエリ（名前が無ければ主のクエリ）を評価して値を返す。step を渡すと、そのステップまでの値。"""
        name = name or self.main_name()
        if name not in self.by_name:
            raise MError(f'クエリ「{name}」がありません（あるのは {", ".join(self.names())}）。')
        token = _HOST.set(host_ or Host())
        try:
            env = self._env(host_)
            q = self.by_name[name]
            if step is not None and q.node[0] == 'let' and step in self.steps(name):
                e = Env({}, env)
                binds = [(n, compile_node(x, name)) for n, x, _ in q.node[1]]
                for n, fn in binds:
                    e.vars[n] = Thunk((lambda fn=fn: fn(e)), n, name)
                return force(e.vars[step])
            try:
                return force(env.vars[name])
            except MError as e:
                if e.query is None:
                    e.query = name
                raise
        finally:
            _HOST.reset(token)
