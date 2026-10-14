"""M の標準関数（2.4.0）。Table.*・List.*・Text.*・Number.*・Date.*・Record.* など。

Power Query の画面操作が書き出す関数（行の絞り込み・列の削除・型の変更・ヘッダーの昇格・列の展開・ピボット解除・
グループ化・マージ・列の分割・値の置換・フィル など）を、同じ引数の形で受ける。名前と引数の形は Microsoft の
説明書（Power Query M 関数リファレンス）に合わせ、まだ無い関数は「まだ使えません」と名前を挙げて断る。

セルの誤り: 列を作る・変える関数（AddColumn・TransformColumns・TransformColumnTypes など）で1つのセルが失敗しても、
クエリ全体は止めずに、そのセルを誤りとして残す（Power Query と同じ。RemoveRowsWithErrors などで扱える）。
"""
import functools
import inspect
import math
import random
import re
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone

import navi_mconv as C
from navi_m import (ErrorCell, MError, MFunction, MRecord, MTable, MType, call, compare, equal, force, is_number,
                    is_type, named_types, num, sort_key, truthy, type_name)

_LIB = {}


def m(*names):
    """関数を M の名前で登録する。引数の数は Python の定義から取る（既定値のある引数は省略できる）。"""
    def deco(fn):
        ps = list(inspect.signature(fn).parameters.values())
        f = MFunction(names[0], py=fn, min_=sum(1 for p in ps if p.default is inspect.Parameter.empty), max_=len(ps))
        for n in names:
            _LIB[n] = f
        return fn
    return deco


def const(name, value):
    _LIB[name] = value


def library():
    """評価に使う名前の表（関数・定数・型）。文書ごとに写して使う（書き換えが他へ漏れないように）。"""
    import navi_msource       # noqa: F401  ファイルを読む口（Folder.Files など）をここで登録する
    return dict(_LIB)


def namespaces():
    return {n.split('.')[0] for n in _LIB if '.' in n}


# ---- 引数の整え方 ------------------------------------------------------------------
def _tbl(v, fname=''):
    v = force(v)
    if not isinstance(v, MTable):
        raise MError(f'{fname or "この関数"} にはテーブルを渡します（{type_name(v)} が渡されました）。')
    return v


def _lst(v, fname=''):
    v = force(v)
    if not isinstance(v, list):
        raise MError(f'{fname or "この関数"} にはリストを渡します（{type_name(v)} が渡されました）。')
    return v


def _rec(v, fname=''):
    v = force(v)
    if not isinstance(v, MRecord):
        raise MError(f'{fname or "この関数"} にはレコードを渡します（{type_name(v)} が渡されました）。')
    return v


def _txt(v, fname=''):
    v = force(v)
    if v is None or isinstance(v, str):
        return v
    raise MError(f'{fname or "この関数"} には文字を渡します（{type_name(v)} が渡されました）。')


def _num(v, fname=''):
    v = force(v)
    if v is None or is_number(v):
        return v
    raise MError(f'{fname or "この関数"} には数を渡します（{type_name(v)} が渡されました）。')


def _fn(v):
    v = force(v)
    if not isinstance(v, MFunction):
        raise MError(f'関数が要るところに {type_name(v)} があります。')
    return v


def _names(v):
    """列名の指定（"A" か {"A","B"}）→ 文字の並び。"""
    v = force(v)
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(force(x)) for x in v]
    raise MError('列名は文字か、文字のリストで指定します。')


def _pairs(v):
    """{"A", x} か {{"A", x}, {"B", y}} → [[A, x], [B, y]]。"""
    v = force(v)
    if not isinstance(v, list):
        raise MError('{ "列名", 値 } の形のリストを渡します。')
    if v and not isinstance(force(v[0]), list):
        return [[force(x) for x in v]]
    return [[force(x) for x in _lst(p)] for p in v]


def _vals(lst):
    return [force(x) for x in lst]


def _cell(fn, *args):
    """セル1つぶんの計算。失敗はセルの誤りとして残す（クエリ全体は止めない）。"""
    try:
        return force(fn(*args))
    except MError as e:
        return ErrorCell(e.mark_origin())


def _missing(v):
    v = force(v)
    return 0 if v is None else int(v)


def _key(v, ci=False):
    """同じかどうかを辞書で数えるための鍵（Distinct・Group・Join）。true と 1 は別、1 と 1.0 は同じ。"""
    v = force(v)
    if v is None:
        return ('n',)
    if isinstance(v, bool):
        return ('b', v)
    if is_number(v):
        return ('x', v)
    if isinstance(v, str):
        return ('t', v.casefold() if ci else v)
    if isinstance(v, list):
        return ('l', tuple(_key(x, ci) for x in v))
    if isinstance(v, MRecord):
        return ('r', tuple(sorted((n, _key(v.get(n), ci)) for n in v.names)))
    if isinstance(v, MTable):
        return ('tb', tuple(v.columns), tuple(tuple(_key(x, ci) for x in r) for r in v.rows))
    return (type_name(v), v)


def _ignore_case(comparer):
    comparer = force(comparer)
    return isinstance(comparer, MFunction) and 'IgnoreCase' in (comparer.name or '')


def _culture(v):
    v = force(v)
    if isinstance(v, MRecord):
        return v.get('Culture', None)
    return v


def _types_of(t, names):
    return [t.types[t.col(n)] for n in names]


# ---- 定数 ------------------------------------------------------------------------
for _ns, _items in {
    'Order': ('Ascending', 'Descending'),
    'JoinKind': ('Inner', 'LeftOuter', 'RightOuter', 'FullOuter', 'LeftAnti', 'RightAnti'),
    'JoinAlgorithm': ('Dynamic', 'PairwiseHash', 'SortMerge', 'LeftHash', 'RightHash', 'LeftIndex', 'RightIndex'),
    'JoinSide': ('Left', 'Right'),
    'MissingField': ('Error', 'Ignore', 'UseNull'),
    'QuoteStyle': ('None', 'Csv'),
    'CsvStyle': ('QuoteAfterDelimiter', 'QuoteAlways'),
    'ExtraValues': ('List', 'Error', 'Ignore'),
    'GroupKind': ('Local', 'Global'),
    'Occurrence': ('First', 'Last', 'All'),
    'RoundingMode': ('Up', 'Down', 'AwayFromZero', 'TowardZero', 'ToEven'),
    'Day': ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'),
    'RelativePosition': ('FromStart', 'FromEnd'),
    'Precision': ('Double', 'Decimal'),
    'TraceLevel': ('Critical', 'Error', 'Warning', 'Information', 'Verbose'),
    'PercentileMode': ('ExcelInclusive', 'ExcelExclusive', 'SqlDisc', 'SqlCont'),
}.items():
    for _i, _n in enumerate(_items):
        const(f'{_ns}.{_n}', _i)
for _n, _v in (('Utf8', 65001), ('Utf16', 1200), ('Unicode', 1200), ('BigEndianUnicode', 1201), ('Ascii', 20127),
               ('Windows', 1252), ('Utf32', 12000)):
    const(f'TextEncoding.{_n}', _v)
const('Culture.Current', C.DEFAULT_CULTURE)
const('#infinity', math.inf)
const('#nan', math.nan)
const('Number.PI', math.pi)
const('Number.E', math.e)
const('Number.Epsilon', 5e-324)
const('Number.MaxValue', 1.7976931348623157e308)
const('Number.MinValue', -1.7976931348623157e308)
const('Number.PositiveInfinity', math.inf)
const('Number.NegativeInfinity', -math.inf)
const('Number.NaN', math.nan)
for _n, _t in named_types().items():
    const(_n, _t)
del _ns, _items, _i, _n, _v, _t


# ---- 比べ方（Comparer）----------------------------------------------------------
def _comparer(name, ci):
    def cmp(a, b):
        a, b = force(a), force(b)
        if ci and isinstance(a, str) and isinstance(b, str):
            a, b = a.casefold(), b.casefold()
        if equal(a, b):
            return 0
        r = compare(a, b)
        return 0 if r is None else r
    return MFunction(name, py=cmp, min_=2, max_=2)


_LIB['Comparer.Ordinal'] = _comparer('Comparer.Ordinal', False)
_LIB['Comparer.OrdinalIgnoreCase'] = _comparer('Comparer.OrdinalIgnoreCase', True)


@m('Comparer.FromCulture')
def comparer_from_culture(cult, ignore_case=None):
    return _comparer('Comparer.FromCulture' + ('.IgnoreCase' if force(ignore_case) else ''), bool(force(ignore_case)))


@m('Comparer.Equals')
def comparer_equals(comparer, a, b):
    return call(comparer, [a, b]) == 0


# ---- 値・型・誤り ----------------------------------------------------------------
@m('Value.Is')
def value_is(v, t):
    return is_type(force(v), force(t))


@m('Value.As')
def value_as(v, t):
    v = force(v)
    if not is_type(v, force(t)):
        raise MError(f'{type_name(v)} の値を {force(t).name()} として扱えません。')
    return v


@m('Value.Type')
def value_type(v):
    v = force(v)
    if isinstance(v, MTable):
        return MType('table', fields=[(c, t or MType('any')) for c, t in zip(v.columns, v.types)])
    return MType(type_name(v))


@m('Value.Equals', 'Value.NullableEquals')
def value_equals(a, b, precision=None):
    return equal(a, b)


@m('Value.Compare')
def value_compare(a, b, precision=None):
    if equal(a, b):
        return 0
    return -1 if sort_key(a) < sort_key(b) else 1


@m('Value.ReplaceType')
def value_replace_type(v, t):
    v, t = force(v), force(t)
    if isinstance(v, MTable) and isinstance(t, MType) and t.kind == 'table' and t.fields:
        if len(t.fields) != len(v.columns):
            raise MError(f'型の列の数（{len(t.fields)}）とテーブルの列の数（{len(v.columns)}）が合いません。')
        return MTable([n for n, _ in t.fields], v.rows, [ft for _, ft in t.fields])
    return v


@m('Value.Metadata')
def value_metadata(v):
    return MRecord.of({})


@m('Value.RemoveMetadata', 'Table.Buffer', 'List.Buffer', 'Binary.Buffer', 'Table.StopFolding',
   'Table.ConformToPageReader')
def value_identity(v, options=None):
    return force(v)


@m('Value.FromText')
def value_from_text(text, cult=None):
    s = _txt(text)
    if s is None:
        return None
    for conv in (lambda x: C.parse_number(x, cult), lambda x: C.parse_datetime_text(x, cult)):
        got = conv(s)
        if got is not None:
            return got
    if s.lower() in ('true', 'false'):
        return s.lower() == 'true'
    return s


@m('Type.Is')
def type_is(a, b):
    a, b = force(a), force(b)
    return b.kind == 'any' or a.kind == b.kind


@m('Type.TableColumn')
def type_table_column(t, column):
    t = force(t)
    for n, ft in (t.fields or []):
        if n == column:
            return ft
    raise MError(f'型に列「{column}」がありません。')


@m('Type.ListItem')
def type_list_item(t):
    return force(t).item or MType('any')


@m('Type.NonNullable')
def type_non_nullable(t):
    t = force(t)
    return MType(t.kind, False, t.facet, t.fields, t.item)


@m('Error.Record')
def error_record(reason, message=None, detail=None):
    return MRecord.of({'Reason': force(reason), 'Message': force(message), 'Detail': force(detail)})


@m('Diagnostics.Trace')
def diagnostics_trace(level, message, value, delayed=None):
    v = force(value)
    return call(v, []) if isinstance(v, MFunction) and force(delayed) else v


@m('Function.Invoke')
def function_invoke(f, args):
    return call(f, _vals(_lst(args)))


@m('Function.InvokeAfter')
def function_invoke_after(f, delay):
    return call(f, [])


@m('Expression.Evaluate')
def expression_evaluate(text, env=None):
    import navi_m
    node = navi_m.parse(_txt(text))
    base = navi_m.Env(library())
    env = force(env)
    if isinstance(env, MRecord):
        base = navi_m.Env({n: env.raw(n) for n in env.names}, base)
    return navi_m.compile_node(node)(base)


@m('Expression.Constant')
def expression_constant(v):
    v = force(v)
    if isinstance(v, str):
        return '"' + v.replace('"', '""') + '"'
    return C.to_text(v) if v is not None else 'null'


# ---- 論理 ------------------------------------------------------------------------
@m('Logical.From')
def logical_from(v, cult=None):
    return C.to_logical(v)


@m('Logical.FromText')
def logical_from_text(v):
    v = _txt(v)
    if v is None:
        return None
    s = v.strip().lower()
    if s in ('true', 'false'):
        return s == 'true'
    raise MError(f'「{v}」を true／false に変換できませんでした。', 'DataFormat.Error', v)


@m('Logical.ToText')
def logical_to_text(v):
    v = force(v)
    return None if v is None else ('true' if truthy(v) else 'false')


# ---- 数 --------------------------------------------------------------------------
@m('Number.From', 'Decimal.From', 'Double.From', 'Single.From', 'Percentage.From')
def number_from(v, cult=None, rounding=None):
    return C.to_number(v, _culture(cult))


@m('Int64.From', 'Int32.From', 'Int16.From', 'Int8.From', 'Byte.From')
def int64_from(v, cult=None, rounding=None):
    n = C.to_number(v, _culture(cult))
    if n is None:
        return None
    return int(C.round_number(n, 0, 4 if force(rounding) is None else force(rounding)))


@m('Currency.From')
def currency_from(v, cult=None, rounding=None):
    n = C.to_number(v, _culture(cult))
    return None if n is None else C.round_number(n, 4, 4 if force(rounding) is None else force(rounding))


@m('Number.FromText')
def number_from_text(text, cult=None):
    t = _txt(text, 'Number.FromText')
    return None if t is None else C.to_number(t, _culture(cult))


@m('Number.ToText')
def number_to_text(n, fmt=None, cult=None):
    n = _num(n, 'Number.ToText')
    if n is None:
        return None
    f, c2 = C.options(fmt)
    return C.format_number(n, f, _culture(cult) or c2)


@m('Number.Round')
def number_round(n, digits=None, mode=None):
    return C.round_number(_num(n, 'Number.Round'), digits, mode)


@m('Number.RoundUp')
def number_round_up(n, digits=None):
    return C.round_direction(_num(n, 'Number.RoundUp'), digits, True)


@m('Number.RoundDown')
def number_round_down(n, digits=None):
    return C.round_direction(_num(n, 'Number.RoundDown'), digits, False)


@m('Number.RoundTowardZero')
def number_round_toward_zero(n, digits=None):
    return C.round_toward_zero(_num(n), digits)


@m('Number.RoundAwayFromZero')
def number_round_away(n, digits=None):
    n = _num(n)
    if n is None:
        return None
    return C.round_direction(n, digits, n >= 0)


def _num1(fn, name):
    def f(n):
        n = _num(n, name)
        return None if n is None else num(fn(n))
    m(name)(f)


_num1(abs, 'Number.Abs')
_num1(lambda n: (n > 0) - (n < 0), 'Number.Sign')
_num1(lambda n: math.sqrt(n) if n >= 0 else math.nan, 'Number.Sqrt')
_num1(math.exp, 'Number.Exp')
_num1(lambda n: math.log(n) if n > 0 else (-math.inf if n == 0 else math.nan), 'Number.Ln')
_num1(lambda n: math.log10(n) if n > 0 else (-math.inf if n == 0 else math.nan), 'Number.Log10')
_num1(lambda n: math.factorial(int(n)), 'Number.Factorial')
_num1(math.sin, 'Number.Sin')
_num1(math.cos, 'Number.Cos')
_num1(math.tan, 'Number.Tan')
_num1(math.atan, 'Number.Atan')


@m('Number.Log')
def number_log(n, base=None):
    n = _num(n)
    if n is None:
        return None
    b = force(base)
    return num(math.log(n) if b is None else math.log(n, b))


@m('Number.Power')
def number_power(n, p):
    n, p = _num(n), _num(p)
    return None if n is None or p is None else num(n ** p)


@m('Number.Mod')
def number_mod(n, d, precision=None):
    n, d = _num(n), _num(d)
    if n is None or d is None:
        return None
    if d == 0:
        raise MError('0 で割った余りは求められません。', 'Expression.Error')
    return num(math.fmod(n, d)) if isinstance(n, float) or isinstance(d, float) else int(math.fmod(n, d))


@m('Number.IntegerDivide')
def number_integer_divide(n, d, precision=None):
    n, d = _num(n), _num(d)
    if n is None or d is None:
        return None
    if d == 0:
        raise MError('0 で割りました。', 'Expression.Error')
    return int(n / d)


@m('Number.IsNaN')
def number_is_nan(n):
    n = force(n)
    return isinstance(n, float) and math.isnan(n)


@m('Number.IsEven')
def number_is_even(n):
    return int(_num(n)) % 2 == 0


@m('Number.IsOdd')
def number_is_odd(n):
    return int(_num(n)) % 2 == 1


@m('Number.Random')
def number_random():
    return random.random()


@m('Number.RandomBetween')
def number_random_between(lo, hi):
    return random.uniform(force(lo), force(hi))


@m('Number.BitwiseAnd')
def number_bitwise_and(a, b):
    return int(force(a)) & int(force(b))


@m('Number.BitwiseOr')
def number_bitwise_or(a, b):
    return int(force(a)) | int(force(b))


# ---- 文字 ------------------------------------------------------------------------
@m('Text.From')
def text_from(v, cult=None):
    return C.to_text(v, None, _culture(cult))


@m('Text.Length')
def text_length(t):
    t = _txt(t, 'Text.Length')
    return None if t is None else len(t)


@m('Text.Upper')
def text_upper(t, cult=None):
    t = _txt(t, 'Text.Upper')
    return None if t is None else t.upper()


@m('Text.Lower')
def text_lower(t, cult=None):
    t = _txt(t, 'Text.Lower')
    return None if t is None else t.lower()


@m('Text.Proper')
def text_proper(t, cult=None):
    t = _txt(t, 'Text.Proper')
    return None if t is None else re.sub(r'\w+', lambda mm: mm.group(0)[:1].upper() + mm.group(0)[1:].lower(), t)


def _trim_chars(chars):
    chars = force(chars)
    if chars is None:
        return None
    if isinstance(chars, list):
        return ''.join(_vals(chars))
    return chars


@m('Text.Trim')
def text_trim(t, chars=None):
    t = _txt(t, 'Text.Trim')
    return None if t is None else t.strip(_trim_chars(chars))


@m('Text.TrimStart')
def text_trim_start(t, chars=None):
    t = _txt(t, 'Text.TrimStart')
    return None if t is None else t.lstrip(_trim_chars(chars))


@m('Text.TrimEnd')
def text_trim_end(t, chars=None):
    t = _txt(t, 'Text.TrimEnd')
    return None if t is None else t.rstrip(_trim_chars(chars))


@m('Text.Clean')
def text_clean(t):
    t = _txt(t, 'Text.Clean')
    return None if t is None else ''.join(ch for ch in t if unicodedata.category(ch) != 'Cc')


def _ci_text(a, comparer):
    return (a.casefold() if _ignore_case(comparer) else a)


@m('Text.Contains')
def text_contains(t, sub, comparer=None):
    t, sub = _txt(t, 'Text.Contains'), _txt(sub, 'Text.Contains')
    if t is None:
        return None
    return _ci_text(sub, comparer) in _ci_text(t, comparer)


@m('Text.StartsWith')
def text_starts_with(t, sub, comparer=None):
    t, sub = _txt(t, 'Text.StartsWith'), _txt(sub, 'Text.StartsWith')
    if t is None:
        return None
    return _ci_text(t, comparer).startswith(_ci_text(sub, comparer))


@m('Text.EndsWith')
def text_ends_with(t, sub, comparer=None):
    t, sub = _txt(t, 'Text.EndsWith'), _txt(sub, 'Text.EndsWith')
    if t is None:
        return None
    return _ci_text(t, comparer).endswith(_ci_text(sub, comparer))


@m('Text.Start')
def text_start(t, count):
    t = _txt(t, 'Text.Start')
    return None if t is None else t[:int(force(count))]


@m('Text.End')
def text_end(t, count):
    t = _txt(t, 'Text.End')
    n = int(force(count))
    return None if t is None else (t[-n:] if n else '')


@m('Text.Middle')
def text_middle(t, start, count=None):
    t = _txt(t, 'Text.Middle')
    if t is None:
        return None
    s = int(force(start))
    if s > len(t):
        raise MError('Text.Middle: 開始位置が文字の長さを超えています。')
    c = force(count)
    return t[s:] if c is None else t[s:s + int(c)]


@m('Text.Range')
def text_range(t, offset, count=None):
    t = _txt(t, 'Text.Range')
    if t is None:
        return None
    s = int(force(offset))
    c = force(count)
    if s > len(t) or (c is not None and s + int(c) > len(t)):
        raise MError('Text.Range: 範囲が文字の長さを超えています。', 'Expression.Error')
    return t[s:] if c is None else t[s:s + int(c)]


@m('Text.At')
def text_at(t, index):
    t = _txt(t, 'Text.At')
    i = int(force(index))
    if t is None:
        return None
    if not 0 <= i < len(t):
        raise MError('Text.At: 位置が文字の長さを超えています。')
    return t[i]


@m('Text.Replace')
def text_replace(t, old, new):
    t = _txt(t, 'Text.Replace')
    if t is None:
        return None
    old = _txt(old, 'Text.Replace')
    return t.replace(old, _txt(new, 'Text.Replace') or '') if old else t


@m('Text.ReplaceRange')
def text_replace_range(t, offset, count, new):
    t = _txt(t)
    if t is None:
        return None
    o, c = int(force(offset)), int(force(count))
    return t[:o] + (force(new) or '') + t[o + c:]


@m('Text.RemoveRange')
def text_remove_range(t, offset, count=None):
    t = _txt(t)
    if t is None:
        return None
    o = int(force(offset))
    c = 1 if force(count) is None else int(force(count))
    return t[:o] + t[o + c:]


@m('Text.Insert')
def text_insert(t, offset, new):
    t = _txt(t)
    if t is None:
        return None
    o = int(force(offset))
    return t[:o] + (force(new) or '') + t[o:]


def _char_set(chars):
    chars = force(chars)
    if isinstance(chars, str):
        return set(chars)
    return {str(force(x)) for x in _lst(chars)}


@m('Text.Remove')
def text_remove(t, chars):
    t = _txt(t, 'Text.Remove')
    if t is None:
        return None
    s = _char_set(chars)
    return ''.join(ch for ch in t if ch not in s)


@m('Text.Select')
def text_select(t, chars):
    t = _txt(t, 'Text.Select')
    if t is None:
        return None
    s = _char_set(chars)
    return ''.join(ch for ch in t if ch in s)


@m('Text.Split')
def text_split(t, sep):
    t = _txt(t, 'Text.Split')
    if t is None:
        return None
    sep = _txt(sep)
    return t.split(sep) if sep else list(t)


@m('Text.SplitAny')
def text_split_any(t, seps):
    t = _txt(t, 'Text.SplitAny')
    if t is None:
        return None
    if not seps:
        return [t]
    return re.split('[' + re.escape(force(seps)) + ']', t)


@m('Text.Combine')
def text_combine(texts, sep=None):
    parts = [x for x in _vals(_lst(texts, 'Text.Combine')) if x is not None]
    for p in parts:
        if not isinstance(p, str):
            raise MError(f'Text.Combine には文字のリストを渡します（{type_name(p)} が入っています）。')
    return (force(sep) or '').join(parts)


@m('Text.PadStart')
def text_pad_start(t, count, ch=None):
    t = _txt(t, 'Text.PadStart')
    return None if t is None else t.rjust(int(force(count)), force(ch) or ' ')


@m('Text.PadEnd')
def text_pad_end(t, count, ch=None):
    t = _txt(t, 'Text.PadEnd')
    return None if t is None else t.ljust(int(force(count)), force(ch) or ' ')


@m('Text.Repeat')
def text_repeat(t, count):
    t = _txt(t)
    return None if t is None else t * int(force(count))


@m('Text.Reverse')
def text_reverse(t):
    t = _txt(t)
    return None if t is None else t[::-1]


@m('Text.ToList')
def text_to_list(t):
    return list(_txt(t) or '')


@m('Text.PositionOf')
def text_position_of(t, sub, occurrence=None, comparer=None):
    t, sub = _txt(t), _txt(sub)
    if t is None:
        return None
    a, b = _ci_text(t, comparer), _ci_text(sub, comparer)
    occ = force(occurrence) or 0
    if occ == 1:
        return a.rfind(b)
    if occ == 2:
        out, i = [], a.find(b)
        while i >= 0:
            out.append(i)
            i = a.find(b, i + max(1, len(b)))
        return out
    return a.find(b)


@m('Text.PositionOfAny')
def text_position_of_any(t, chars, occurrence=None):
    t = _txt(t)
    if t is None:
        return None
    s = _char_set(chars)
    pos = [i for i, ch in enumerate(t) if ch in s]
    occ = force(occurrence) or 0
    if occ == 2:
        return pos
    if not pos:
        return -1
    return pos[-1] if occ == 1 else pos[0]


def _delim_index(index):
    """Text.BeforeDelimiter などの index: 数か {数, RelativePosition.FromEnd}。→ (何番目, 後ろから数えるか)。"""
    index = force(index)
    if index is None:
        return 0, False
    if isinstance(index, list):
        v = _vals(index)
        return int(v[0]), bool(len(v) > 1 and v[1] == 1)
    return int(index), False


def _find_delim(t, d, index):
    n, from_end = _delim_index(index)
    pos = []
    i = t.find(d)
    while i >= 0:
        pos.append(i)
        i = t.find(d, i + max(1, len(d)))
    if from_end:
        pos = pos[::-1]
    return pos[n] if n < len(pos) else None


@m('Text.BeforeDelimiter')
def text_before_delimiter(t, d, index=None):
    t = _txt(t, 'Text.BeforeDelimiter')
    if t is None:
        return None
    p = _find_delim(t, force(d), index)
    return t if p is None else t[:p]


@m('Text.AfterDelimiter')
def text_after_delimiter(t, d, index=None):
    t = _txt(t, 'Text.AfterDelimiter')
    if t is None:
        return None
    d = force(d)
    p = _find_delim(t, d, index)
    return '' if p is None else t[p + len(d):]


@m('Text.BetweenDelimiters')
def text_between_delimiters(t, start, end, start_index=None, end_index=None):
    t = _txt(t, 'Text.BetweenDelimiters')
    if t is None:
        return None
    s, e = force(start), force(end)
    p = _find_delim(t, s, start_index)
    if p is None:
        return ''
    rest = t[p + len(s):]
    q = _find_delim(rest, e, end_index)
    return rest if q is None else rest[:q]


@m('Text.Format')
def text_format(fmt, args, cult=None):
    fmt, args = _txt(fmt), force(args)

    def rep(mm):
        key = mm.group(1) or mm.group(2)
        v = args.get(key) if isinstance(args, MRecord) else force(args[int(key)])
        return C.to_text(v, None, _culture(cult)) or ''
    return re.sub(r'#\{(\d+)\}|#\[([^\]]+)\]', rep, fmt)


@m('Text.NewGuid')
def text_new_guid():
    return str(uuid.uuid4())


@m('Text.FromBinary')
def text_from_binary(b, encoding=None):
    b = force(b)
    if b is None:
        return None
    return _decode(b.data(), force(encoding))


@m('Text.ToBinary')
def text_to_binary(t, encoding=None, include_bom=None):
    from navi_msource import MBinary
    return MBinary(data=(_txt(t) or '').encode(_codec(force(encoding))))


def _codec(cp):
    return {65001: 'utf-8', 1200: 'utf-16-le', 1201: 'utf-16-be', 20127: 'ascii', 1252: 'cp1252', 932: 'cp932',
            12000: 'utf-32-le', 20932: 'euc_jp', 51932: 'euc_jp', 50220: 'iso2022_jp'}.get(cp, 'utf-8')


def _decode(data, cp=None):
    if cp:
        codec = _codec(cp)
        if codec == 'utf-8' and data.startswith(b'\xef\xbb\xbf'):
            data = data[3:]
        return data.decode(codec, errors='replace')
    if data.startswith(b'\xef\xbb\xbf'):
        return data[3:].decode('utf-8', errors='replace')
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16', errors='replace')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp932', errors='replace')


@m('Character.FromNumber')
def character_from_number(n):
    n = force(n)
    return None if n is None else chr(int(n))


@m('Character.ToNumber')
def character_to_number(c):
    c = force(c)
    return None if c is None else ord(c)


@m('Lines.FromText')
def lines_from_text(t, quote_style=None, include_breaks=None):
    return (_txt(t) or '').splitlines()


@m('Lines.FromBinary')
def lines_from_binary(b, quote_style=None, include_breaks=None, encoding=None):
    return _decode(force(b).data(), force(encoding)).splitlines()


@m('Lines.ToText')
def lines_to_text(lines, sep=None):
    s = force(sep)
    s = '\r\n' if s is None else s
    return ''.join(str(x) + s for x in _vals(_lst(lines)))


# ---- 分割・結合・置換の関数を作る関数 ------------------------------------------------
def _fn1(name, py, n=1):
    return MFunction(name, py=py, min_=n, max_=n)


def _split_csv(t, d):
    """引用符（"）の中の区切りでは切らない（QuoteStyle.Csv）。"""
    out, cur, q, i = [], [], False, 0
    while i < len(t):
        ch = t[i]
        if q:
            if ch == '"':
                if i + 1 < len(t) and t[i + 1] == '"':
                    cur.append('"')
                    i += 1
                else:
                    q = False
            else:
                cur.append(ch)
        elif ch == '"' and not cur:
            q = True
        elif d and t.startswith(d, i):
            out.append(''.join(cur))
            cur = []
            i += len(d)
            continue
        else:
            cur.append(ch)
        i += 1
    out.append(''.join(cur))
    return out


@m('Splitter.SplitTextByDelimiter')
def splitter_by_delimiter(d, quote_style=None, csv_style=None):
    d = force(d)
    csvq = force(quote_style) == 1

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        if csvq:
            return _split_csv(t, d)
        return t.split(d) if d else [t]
    return _fn1('Splitter', split)


@m('Splitter.SplitTextByEachDelimiter')
def splitter_by_each_delimiter(ds, quote_style=None, start_at_end=None):
    ds = _vals(_lst(ds))
    from_end = bool(force(start_at_end))

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        out = []
        if from_end:
            for d in ds:
                i = t.rfind(d)
                if i < 0:
                    break
                out.insert(0, t[i + len(d):])
                t = t[:i]
            return [t] + out
        for d in ds:
            i = t.find(d)
            if i < 0:
                break
            out.append(t[:i])
            t = t[i + len(d):]
        return out + [t]
    return _fn1('Splitter', split)


@m('Splitter.SplitTextByAnyDelimiter')
def splitter_by_any_delimiter(ds, quote_style=None, start_at_end=None):
    ds = sorted(_vals(_lst(ds)), key=len, reverse=True)
    rx = re.compile('|'.join(re.escape(d) for d in ds if d)) if ds else None

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        return rx.split(t) if rx else [t]
    return _fn1('Splitter', split)


@m('Splitter.SplitTextByPositions')
def splitter_by_positions(positions, start_at_end=None):
    pos = [int(x) for x in _vals(_lst(positions))]

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        cuts = pos + [len(t)]
        return [t[cuts[i]:cuts[i + 1]] if cuts[i] <= len(t) else None for i in range(len(pos))]
    return _fn1('Splitter', split)


@m('Splitter.SplitTextByLengths')
def splitter_by_lengths(lengths, start_at_end=None):
    lens = [int(x) for x in _vals(_lst(lengths))]

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        out, i = [], 0
        for n in lens:
            out.append(t[i:i + n] if i < len(t) else None)
            i += n
        return out
    return _fn1('Splitter', split)


@m('Splitter.SplitTextByRepeatedLengths')
def splitter_by_repeated_lengths(length, start_at_end=None):
    n = int(force(length))

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        return [t[i:i + n] for i in range(0, len(t), n)] or ['']
    return _fn1('Splitter', split)


@m('Splitter.SplitByNothing')
def splitter_by_nothing():
    return _fn1('Splitter', lambda v: [force(v)])


def _char_test(spec):
    spec = force(spec)
    if isinstance(spec, MFunction):
        return lambda ch: truthy(call(spec, [ch]))
    s = _char_set(spec)
    return lambda ch: ch in s


@m('Splitter.SplitTextByCharacterTransition')
def splitter_by_character_transition(before, after):
    b, a = _char_test(before), _char_test(after)

    def split(t):
        t = force(t)
        if t is None:
            return [None]
        t = C.to_text(t)
        out, start = [], 0
        for i in range(1, len(t)):
            if b(t[i - 1]) and a(t[i]):
                out.append(t[start:i])
                start = i
        out.append(t[start:])
        return out
    return _fn1('Splitter', split)


@m('Splitter.SplitTextByWhitespace')
def splitter_by_whitespace(quote_style=None):
    return _fn1('Splitter', lambda t: None if force(t) is None else C.to_text(force(t)).split())


@m('Combiner.CombineTextByDelimiter')
def combiner_by_delimiter(d, quote_style=None):
    d = force(d)
    return _fn1('Combiner', lambda lst: d.join('' if force(x) is None else C.to_text(force(x)) for x in _lst(lst)))


@m('Combiner.CombineTextByEachDelimiter')
def combiner_by_each_delimiter(ds, quote_style=None):
    ds = _vals(_lst(ds))

    def comb(lst):
        vals = ['' if force(x) is None else C.to_text(force(x)) for x in _lst(lst)]
        out = vals[0] if vals else ''
        for i, v in enumerate(vals[1:]):
            out += (ds[i] if i < len(ds) else '') + v
        return out
    return _fn1('Combiner', comb)


@m('Combiner.CombineTextByLengths')
def combiner_by_lengths(lengths, template=None):
    lens = [int(x) for x in _vals(_lst(lengths))]
    return _fn1('Combiner', lambda lst: ''.join(('' if force(x) is None else C.to_text(force(x)))[:n].ljust(n)
                                                 for x, n in zip(_lst(lst), lens)))


@m('Replacer.ReplaceText')
def replacer_replace_text(v, old, new):
    v = force(v)
    if not isinstance(v, str):
        return v
    old = force(old)
    return v.replace(old, force(new) or '') if old else v


@m('Replacer.ReplaceValue')
def replacer_replace_value(v, old, new):
    return force(new) if equal(v, old) else force(v)


# ---- 日付・時刻 ------------------------------------------------------------------
def _date_like(v, name):
    v = force(v)
    if v is None or isinstance(v, (date, datetime)):
        return v
    raise MError(f'{name} には日付か日時を渡します（{type_name(v)} が渡されました）。')


def _keep_kind(orig, d):
    """日付を渡せば日付、日時を渡せば日時で返す。"""
    if isinstance(orig, datetime):
        return datetime.combine(d, orig.time()).replace(tzinfo=orig.tzinfo)
    return d


def _add_months(v, n):
    d = v.date() if isinstance(v, datetime) else v
    mo = d.month - 1 + int(n)
    y, mo = d.year + mo // 12, mo % 12 + 1
    last = _days_in_month(y, mo)
    return _keep_kind(v, date(y, mo, min(d.day, last)))


def _days_in_month(y, mo):
    nxt = date(y + (mo == 12), mo % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


def _m_weekday(d):
    """M の曜日（日=0 … 土=6）。"""
    return (d.weekday() + 1) % 7


@m('#date')
def hash_date(y, mo, d):
    try:
        return date(int(force(y)), int(force(mo)), int(force(d)))
    except ValueError as e:
        raise MError(f'#date: 日付として正しくありません（{e}）。')


@m('#datetime')
def hash_datetime(y, mo, d, h, mi, s):
    s = force(s)
    sec = int(s)
    us = round((s - sec) * 1e6)
    try:
        return datetime(int(force(y)), int(force(mo)), int(force(d)), int(force(h)), int(force(mi)), sec, us)
    except ValueError as e:
        raise MError(f'#datetime: 日時として正しくありません（{e}）。')


@m('#datetimezone')
def hash_datetimezone(y, mo, d, h, mi, s, oh, om):
    dt = hash_datetime(y, mo, d, h, mi, s)
    return dt.replace(tzinfo=timezone(timedelta(hours=int(force(oh)), minutes=int(force(om)))))


@m('#time')
def hash_time(h, mi, s):
    s = force(s)
    sec = int(s)
    h = int(force(h))
    if h == 24:
        return time(0, 0, 0)
    return time(h, int(force(mi)), sec, round((s - sec) * 1e6))


@m('#duration')
def hash_duration(d, h, mi, s):
    return timedelta(days=force(d), hours=force(h), minutes=force(mi), seconds=force(s))


@m('#binary')
def hash_binary(v):
    from navi_msource import MBinary
    v = force(v)
    if isinstance(v, str):
        import base64
        return MBinary(data=base64.b64decode(v))
    return MBinary(data=bytes(int(force(x)) for x in v))


@m('Date.From')
def date_from(v, cult=None):
    return C.to_date(v, _culture(cult))


@m('Date.FromText')
def date_from_text(t, cult=None):
    t = _txt(t, 'Date.FromText')
    if t is None:
        return None
    f, c2 = C.options(cult)
    if isinstance(force(cult), MRecord) and f:
        return _parse_with_format(t, f, 'date')
    return C.to_date(t, c2 if isinstance(force(cult), MRecord) else force(cult))


@m('DateTime.From')
def datetime_from(v, cult=None):
    return C.to_datetime(v, _culture(cult))


@m('DateTime.FromText')
def datetime_from_text(t, cult=None):
    t = _txt(t, 'DateTime.FromText')
    if t is None:
        return None
    f, c2 = C.options(cult)
    if isinstance(force(cult), MRecord) and f:
        return _parse_with_format(t, f, 'datetime')
    return C.to_datetime(t, c2 if isinstance(force(cult), MRecord) else force(cult))


@m('DateTimeZone.From')
def datetimezone_from(v, cult=None):
    d = C.to_datetime(v, _culture(cult))
    return None if d is None else d.astimezone()


@m('Time.From')
def time_from(v, cult=None):
    return C.to_time(v, _culture(cult))


@m('Time.FromText')
def time_from_text(t, cult=None):
    return C.to_time(_txt(t), _culture(cult))


@m('Duration.From')
def duration_from(v):
    return C.to_duration(v)


@m('Duration.FromText')
def duration_from_text(t):
    return C.to_duration(_txt(t))


def _parse_with_format(text, fmt, want):
    """[Format="yyyyMMdd"] の読み方。書式の文字の並びどおりに切って読む。"""
    pat = ''
    groups = []
    for tok in C._DT_TOKEN.findall(fmt):
        if tok in ('yyyy',):
            pat += r'(\d{4})'
            groups.append('y')
        elif tok == 'yy':
            pat += r'(\d{2})'
            groups.append('yy')
        elif tok in ('MM', 'dd', 'HH', 'hh', 'mm', 'ss'):
            pat += r'(\d{2})'
            groups.append(tok)
        elif tok in ('M', 'd', 'H', 'h', 'm', 's'):
            pat += r'(\d{1,2})'
            groups.append(tok * 2)
        elif tok[0] in "'\"":
            pat += re.escape(tok[1:-1])
        else:
            pat += re.escape(tok)
    mm = re.fullmatch(pat, text.strip())
    if not mm:
        raise MError(f'「{text}」は書式「{fmt}」に合いません。', 'DataFormat.Error', text)
    got = {'y': 1900, 'MM': 1, 'dd': 1, 'HH': 0, 'mm': 0, 'ss': 0}
    for g, v in zip(groups, mm.groups()):
        if g == 'yy':
            got['y'] = 2000 + int(v) if int(v) <= 29 else 1900 + int(v)
        else:
            got['HH' if g == 'hh' else g] = int(v)
    try:
        dt = datetime(got['y'], got['MM'], got['dd'], got['HH'], got['mm'], got['ss'])
    except ValueError:
        raise MError(f'「{text}」は日付として正しくありません。', 'DataFormat.Error', text)
    return dt.date() if want == 'date' else dt


@m('Date.ToText')
def date_to_text(v, fmt=None, cult=None):
    v = force(v)
    if v is None:
        return None
    f, c2 = C.options(fmt)
    return C.format_datetime(v, f, _culture(cult) or c2)


@m('DateTime.ToText', 'DateTimeZone.ToText', 'Time.ToText')
def datetime_to_text(v, fmt=None, cult=None):
    v = force(v)
    if v is None:
        return None
    f, c2 = C.options(fmt)
    return C.format_datetime(v, f, _culture(cult) or c2)


@m('Duration.ToText')
def duration_to_text(v, fmt=None):
    v = force(v)
    return None if v is None else C.format_duration(v)


def _part(name, fn):
    def f(v):
        v = force(v)
        if v is None:
            return None
        return fn(v)
    m(name)(f)


_part('Date.Year', lambda v: v.year)
_part('Date.Month', lambda v: v.month)
_part('Date.Day', lambda v: v.day)
_part('Date.DayOfYear', lambda v: v.timetuple().tm_yday)
_part('Date.QuarterOfYear', lambda v: (v.month - 1) // 3 + 1)
_part('Date.DaysInMonth', lambda v: _days_in_month(v.year, v.month))
_part('Date.IsLeapYear', lambda v: (v.year % 4 == 0 and v.year % 100 != 0) or v.year % 400 == 0)
_part('Date.StartOfMonth', lambda v: _keep_kind(v, date(v.year, v.month, 1)) if not isinstance(v, datetime)
      else datetime(v.year, v.month, 1))
_part('Date.StartOfYear', lambda v: date(v.year, 1, 1) if not isinstance(v, datetime) else datetime(v.year, 1, 1))
_part('Date.StartOfQuarter', lambda v: (date if not isinstance(v, datetime) else datetime)(v.year, (v.month - 1) // 3 * 3 + 1, 1))
_part('Date.StartOfDay', lambda v: datetime(v.year, v.month, v.day) if isinstance(v, datetime) else v)
_part('Time.Hour', lambda v: v.hour)
_part('Time.Minute', lambda v: v.minute)
_part('Time.Second', lambda v: num(v.second + v.microsecond / 1e6))
_part('Time.StartOfHour', lambda v: v.replace(minute=0, second=0, microsecond=0))
_part('DateTime.Date', lambda v: v.date() if isinstance(v, datetime) else v)
_part('DateTime.Time', lambda v: v.time() if isinstance(v, datetime) else time())
_part('DateTimeZone.RemoveZone', lambda v: v.replace(tzinfo=None))
_part('DateTimeZone.ZoneHours', lambda v: int(v.utcoffset().total_seconds() // 3600) if v.tzinfo else None)
_part('Duration.Days', lambda v: v.days if v >= timedelta(0) else -((-v).days))
_part('Duration.Hours', lambda v: (abs(v).seconds // 3600) * (1 if v >= timedelta(0) else -1))
_part('Duration.Minutes', lambda v: (abs(v).seconds % 3600 // 60) * (1 if v >= timedelta(0) else -1))
_part('Duration.Seconds', lambda v: num((abs(v).seconds % 60 + abs(v).microseconds / 1e6) * (1 if v >= timedelta(0) else -1)))
_part('Duration.TotalDays', lambda v: num(v.total_seconds() / 86400))
_part('Duration.TotalHours', lambda v: num(v.total_seconds() / 3600))
_part('Duration.TotalMinutes', lambda v: num(v.total_seconds() / 60))
_part('Duration.TotalSeconds', lambda v: num(v.total_seconds()))


def _end_of(v, d):
    if isinstance(v, datetime):
        return datetime.combine(d, time(23, 59, 59, 999999))
    return d


_part('Date.EndOfMonth', lambda v: _end_of(v, date(v.year, v.month, _days_in_month(v.year, v.month))))
_part('Date.EndOfYear', lambda v: _end_of(v, date(v.year, 12, 31)))
_part('Date.EndOfQuarter', lambda v: _end_of(v, date(v.year, (v.month - 1) // 3 * 3 + 3,
                                                     _days_in_month(v.year, (v.month - 1) // 3 * 3 + 3))))
_part('Date.EndOfDay', lambda v: _end_of(v, v.date() if isinstance(v, datetime) else v))


@m('Date.AddDays')
def date_add_days(v, n):
    v = _date_like(v, 'Date.AddDays')
    return None if v is None else v + timedelta(days=int(force(n)))


@m('Date.AddWeeks')
def date_add_weeks(v, n):
    v = _date_like(v, 'Date.AddWeeks')
    return None if v is None else v + timedelta(days=7 * int(force(n)))


@m('Date.AddMonths')
def date_add_months(v, n):
    v = _date_like(v, 'Date.AddMonths')
    return None if v is None else _add_months(v, force(n))


@m('Date.AddQuarters')
def date_add_quarters(v, n):
    v = _date_like(v, 'Date.AddQuarters')
    return None if v is None else _add_months(v, 3 * int(force(n)))


@m('Date.AddYears')
def date_add_years(v, n):
    v = _date_like(v, 'Date.AddYears')
    return None if v is None else _add_months(v, 12 * int(force(n)))


@m('Date.DayOfWeek')
def date_day_of_week(v, first=None):
    v = force(v)
    if v is None:
        return None
    f = 0 if force(first) is None else int(force(first))
    return (_m_weekday(v) - f) % 7


@m('Date.DayOfWeekName')
def date_day_of_week_name(v, cult=None):
    v = force(v)
    return None if v is None else C.culture(_culture(cult))['days'][v.weekday()]


@m('Date.MonthName')
def date_month_name(v, cult=None):
    v = force(v)
    return None if v is None else C.culture(_culture(cult))['months'][v.month - 1]


@m('Date.WeekOfYear')
def date_week_of_year(v, first=None):
    v = force(v)
    if v is None:
        return None
    f = 0 if force(first) is None else int(force(first))
    jan1 = date(v.year, 1, 1)
    offset = (_m_weekday(jan1) - f) % 7
    return (v.timetuple().tm_yday - 1 + offset) // 7 + 1


@m('Date.WeekOfMonth')
def date_week_of_month(v, first=None):
    v = force(v)
    if v is None:
        return None
    f = 0 if force(first) is None else int(force(first))
    first_day = date(v.year, v.month, 1)
    offset = (_m_weekday(first_day) - f) % 7
    return (v.day - 1 + offset) // 7 + 1


@m('Date.StartOfWeek')
def date_start_of_week(v, first=None):
    v = force(v)
    if v is None:
        return None
    f = 0 if force(first) is None else int(force(first))
    back = (_m_weekday(v) - f) % 7
    d = (v.date() if isinstance(v, datetime) else v) - timedelta(days=back)
    return datetime.combine(d, time()) if isinstance(v, datetime) else d


@m('Date.EndOfWeek')
def date_end_of_week(v, first=None):
    s = date_start_of_week(v, first)
    if s is None:
        return None
    e = (s.date() if isinstance(s, datetime) else s) + timedelta(days=6)
    return _end_of(force(v), e)


@m('Date.ToRecord')
def date_to_record(v):
    v = force(v)
    return MRecord.of({'Year': v.year, 'Month': v.month, 'Day': v.day})


@m('DateTime.ToRecord')
def datetime_to_record(v):
    v = force(v)
    return MRecord.of({'Year': v.year, 'Month': v.month, 'Day': v.day, 'Hour': v.hour, 'Minute': v.minute,
                       'Second': num(v.second + v.microsecond / 1e6)})


@m('Time.ToRecord')
def time_to_record(v):
    v = force(v)
    return MRecord.of({'Hour': v.hour, 'Minute': v.minute, 'Second': num(v.second + v.microsecond / 1e6)})


@m('Date.FromRecord')
def date_from_record(r):
    r = _rec(r)
    return date(int(r.get('Year')), int(r.get('Month')), int(r.get('Day')))


def _now():
    from navi_m import host
    h = host()
    return (h.now if h and h.now else datetime.now()).replace(microsecond=0)


@m('DateTime.LocalNow', 'DateTime.FixedLocalNow')
def datetime_local_now():
    return _now()


@m('DateTimeZone.LocalNow', 'DateTimeZone.FixedLocalNow')
def datetimezone_local_now():
    return _now().astimezone()


@m('DateTimeZone.UtcNow', 'DateTimeZone.FixedUtcNow')
def datetimezone_utc_now():
    return _now().astimezone(timezone.utc)


@m('DateTime.IsInPreviousNDays')
def datetime_is_in_previous_n_days(v, n):
    v = force(v)
    if v is None:
        return None
    today = _now().date()
    d = v.date() if isinstance(v, datetime) else v
    return today - timedelta(days=int(force(n))) <= d < today


@m('Date.IsInCurrentMonth')
def date_is_in_current_month(v):
    v = force(v)
    if v is None:
        return None
    t = _now()
    return v.year == t.year and v.month == t.month


@m('Date.IsInCurrentYear')
def date_is_in_current_year(v):
    v = force(v)
    return None if v is None else v.year == _now().year


@m('Date.IsInPreviousMonth')
def date_is_in_previous_month(v):
    v = force(v)
    if v is None:
        return None
    p = _add_months(_now().date(), -1)
    return v.year == p.year and v.month == p.month


# ---- リスト ----------------------------------------------------------------------
def _nums(lst, name):
    out = []
    for x in _vals(_lst(lst, name)):
        if x is None:
            continue
        if isinstance(x, bool) or not (is_number(x) or isinstance(x, timedelta)):
            raise MError(f'{name} には数のリストを渡します（{type_name(x)} が入っています）。')
        out.append(x)
    return out


@m('List.Sum')
def list_sum(lst, precision=None):
    xs = _nums(lst, 'List.Sum')
    if not xs:
        return None
    if isinstance(xs[0], timedelta):
        return sum(xs, timedelta())
    return num(math.fsum(xs)) if any(isinstance(x, float) for x in xs) else sum(xs)


@m('List.Product')
def list_product(lst, precision=None):
    xs = _nums(lst, 'List.Product')
    return num(math.prod(xs)) if xs else None


@m('List.Average')
def list_average(lst, precision=None):
    xs = _nums(lst, 'List.Average')
    if not xs:
        return None
    if isinstance(xs[0], timedelta):
        return sum(xs, timedelta()) / len(xs)
    return num(math.fsum(xs) / len(xs))


@m('List.Median')
def list_median(lst, precision=None):
    xs = sorted(x for x in _vals(_lst(lst)) if x is not None)
    if not xs:
        return None
    n = len(xs)
    if n % 2:
        return xs[n // 2]
    a, b = xs[n // 2 - 1], xs[n // 2]
    return num((a + b) / 2) if is_number(a) else a


@m('List.Mode')
def list_mode(lst, equation=None):
    xs = _vals(_lst(lst))
    if not xs:
        raise MError('List.Mode: 空のリストです。')
    counts = {}
    for x in xs:
        k = _key(x)
        counts.setdefault(k, [x, 0])[1] += 1
    best = max(c[1] for c in counts.values())
    return next(c[0] for c in counts.values() if c[1] == best)


@m('List.StandardDeviation')
def list_stdev(lst):
    xs = _nums(lst, 'List.StandardDeviation')
    if len(xs) < 2:
        return None
    mean = math.fsum(xs) / len(xs)
    return math.sqrt(math.fsum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def _minmax(lst, default, comparer, want_max):
    xs = [x for x in _vals(_lst(lst)) if x is not None]
    if not xs:
        return force(default)
    comparer = force(comparer)
    if isinstance(comparer, MFunction) and comparer.max == 2:
        key = functools.cmp_to_key(lambda a, b: int(call(comparer, [a, b])))
    elif isinstance(comparer, MFunction):
        return (max if want_max else min)(xs, key=lambda x: sort_key(call(comparer, [x])))
    else:
        key = sort_key
    return (max if want_max else min)(xs, key=key)


@m('List.Max')
def list_max(lst, default=None, comparer=None, include_nulls=None):
    return _minmax(lst, default, comparer, True)


@m('List.Min')
def list_min(lst, default=None, comparer=None, include_nulls=None):
    return _minmax(lst, default, comparer, False)


@m('List.MaxN')
def list_max_n(lst, count_or_condition, comparer=None, include_nulls=None):
    xs = sorted((x for x in _vals(_lst(lst)) if x is not None), key=sort_key, reverse=True)
    return _first_n(xs, count_or_condition)


@m('List.MinN')
def list_min_n(lst, count_or_condition, comparer=None, include_nulls=None):
    xs = sorted((x for x in _vals(_lst(lst)) if x is not None), key=sort_key)
    return _first_n(xs, count_or_condition)


@m('List.Count')
def list_count(lst):
    return len(_lst(lst, 'List.Count'))


@m('List.NonNullCount')
def list_non_null_count(lst):
    return sum(1 for x in _vals(_lst(lst, 'List.NonNullCount')) if x is not None)


@m('List.IsEmpty')
def list_is_empty(lst):
    return not _lst(lst, 'List.IsEmpty')


@m('List.Distinct')
def list_distinct(lst, comparer=None):
    ci = _ignore_case(comparer)
    seen, out = set(), []
    for x in _vals(_lst(lst, 'List.Distinct')):
        k = _key(x, ci)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


@m('List.IsDistinct')
def list_is_distinct(lst, comparer=None):
    xs = _lst(lst)
    return len(list_distinct(xs, comparer)) == len(xs)


@m('List.Contains')
def list_contains(lst, value, comparer=None):
    ci = _ignore_case(comparer)
    k = _key(value, ci)
    return any(_key(x, ci) == k for x in _lst(lst, 'List.Contains'))


@m('List.ContainsAny')
def list_contains_any(lst, values, comparer=None):
    ci = _ignore_case(comparer)
    have = {_key(x, ci) for x in _lst(lst)}
    return any(_key(v, ci) in have for v in _lst(values))


@m('List.ContainsAll')
def list_contains_all(lst, values, comparer=None):
    ci = _ignore_case(comparer)
    have = {_key(x, ci) for x in _lst(lst)}
    return all(_key(v, ci) in have for v in _lst(values))


@m('List.First')
def list_first(lst, default=None):
    xs = _lst(lst, 'List.First')
    return force(xs[0]) if xs else force(default)


@m('List.Last')
def list_last(lst, default=None):
    xs = _lst(lst, 'List.Last')
    return force(xs[-1]) if xs else force(default)


def _first_n(xs, count_or_condition):
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        out = []
        for x in xs:
            if not truthy(call(c, [x])):
                break
            out.append(x)
        return out
    return list(xs[:int(c)]) if c is not None else list(xs[:1])


def _skip_n(xs, count_or_condition):
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        i = 0
        while i < len(xs) and truthy(call(c, [xs[i]])):
            i += 1
        return list(xs[i:])
    return list(xs[int(c) if c is not None else 1:])


@m('List.FirstN')
def list_first_n(lst, count_or_condition):
    return _first_n(_lst(lst, 'List.FirstN'), count_or_condition)


@m('List.LastN')
def list_last_n(lst, count_or_condition=None):
    xs = _lst(lst, 'List.LastN')
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        return _first_n(xs[::-1], c)[::-1]
    n = 1 if c is None else int(c)
    return list(xs[-n:]) if n else []


@m('List.Skip', 'List.RemoveFirstN')
def list_skip(lst, count_or_condition=None):
    return _skip_n(_lst(lst, 'List.Skip'), count_or_condition)


@m('List.RemoveLastN')
def list_remove_last_n(lst, count_or_condition=None):
    xs = _lst(lst)
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        return _skip_n(xs[::-1], c)[::-1]
    n = 1 if c is None else int(c)
    return list(xs[:-n]) if n else list(xs)


@m('List.Range')
def list_range(lst, offset, count=None):
    xs = _lst(lst)
    o = int(force(offset))
    c = force(count)
    return list(xs[o:]) if c is None else list(xs[o:o + int(c)])


@m('List.Select')
def list_select(lst, cond):
    f = _fn(cond)
    return [x for x in _lst(lst, 'List.Select') if _is_true(call(f, [force(x)]))]


def _is_true(v):
    v = force(v)
    if v is None:
        return False
    return truthy(v)


@m('List.Transform')
def list_transform(lst, fn):
    f = _fn(fn)
    return [call(f, [force(x)]) for x in _lst(lst, 'List.Transform')]


@m('List.TransformMany')
def list_transform_many(lst, coll, result):
    out = []
    for x in _lst(lst):
        for y in _lst(call(coll, [force(x)])):
            out.append(call(result, [force(x), force(y)]))
    return out


@m('List.Accumulate')
def list_accumulate(lst, seed, fn):
    acc = force(seed)
    for x in _lst(lst, 'List.Accumulate'):
        acc = force(call(fn, [acc, force(x)]))
    return acc


@m('List.Generate')
def list_generate(initial, cond, nxt, selector=None):
    out = []
    v = force(call(initial, []))
    sel = force(selector)
    for _ in range(1000000):
        if not _is_true(call(cond, [v])):
            break
        out.append(call(sel, [v]) if sel is not None else v)
        v = force(call(nxt, [v]))
    return out


def _sort_list(xs, criteria):
    crit = force(criteria)
    if crit is None:
        return sorted(xs, key=sort_key)
    if is_number(crit):
        return sorted(xs, key=sort_key, reverse=crit == 1)
    if isinstance(crit, MFunction):
        if crit.max >= 2:
            return sorted(xs, key=functools.cmp_to_key(lambda a, b: int(force(call(crit, [a, b])))))
        return sorted(xs, key=lambda x: sort_key(call(crit, [x])))
    if isinstance(crit, list):
        sel, order = force(crit[0]), int(force(crit[1])) if len(crit) > 1 else 0
        return sorted(xs, key=lambda x: sort_key(call(sel, [x])), reverse=order == 1)
    raise MError('List.Sort の並べ方の指定が読めません。')


@m('List.Sort')
def list_sort(lst, criteria=None):
    return _sort_list(_vals(_lst(lst, 'List.Sort')), criteria)


@m('List.Reverse')
def list_reverse(lst):
    return list(_lst(lst))[::-1]


@m('List.Combine')
def list_combine(lists):
    out = []
    for x in _lst(lists, 'List.Combine'):
        out.extend(_lst(x, 'List.Combine'))
    return out


@m('List.Zip')
def list_zip(lists):
    ls = [_lst(x) for x in _lst(lists)]
    n = max((len(x) for x in ls), default=0)
    return [[(x[i] if i < len(x) else None) for x in ls] for i in range(n)]


@m('List.Numbers')
def list_numbers(start, count, increment=None):
    s, c = force(start), int(force(count))
    inc = 1 if force(increment) is None else force(increment)
    return [num(s + i * inc) for i in range(c)]


@m('List.Dates', 'List.DateTimes', 'List.Durations', 'List.Times')
def list_dates(start, count, step):
    s, c, st = force(start), int(force(count)), force(step)
    return [s + i * st if not isinstance(s, time) else (datetime.combine(date(2000, 1, 1), s) + i * st).time()
            for i in range(c)]


@m('List.Positions')
def list_positions(lst):
    return list(range(len(_lst(lst))))


@m('List.PositionOf')
def list_position_of(lst, value, occurrence=None, comparer=None):
    ci = _ignore_case(comparer)
    k = _key(value, ci)
    pos = [i for i, x in enumerate(_lst(lst)) if _key(x, ci) == k]
    occ = force(occurrence) or 0
    if occ == 2:
        return pos
    if not pos:
        return -1
    return pos[-1] if occ == 1 else pos[0]


@m('List.PositionOfAny')
def list_position_of_any(lst, values, occurrence=None, comparer=None):
    ci = _ignore_case(comparer)
    ks = {_key(v, ci) for v in _lst(values)}
    pos = [i for i, x in enumerate(_lst(lst)) if _key(x, ci) in ks]
    occ = force(occurrence) or 0
    if occ == 2:
        return pos
    if not pos:
        return -1
    return pos[-1] if occ == 1 else pos[0]


@m('List.RemoveNulls')
def list_remove_nulls(lst):
    return [x for x in _vals(_lst(lst)) if x is not None]


@m('List.RemoveItems', 'List.RemoveMatchingItems')
def list_remove_items(lst, items, comparer=None):
    ci = _ignore_case(comparer)
    ks = {_key(v, ci) for v in _lst(items)}
    return [x for x in _lst(lst) if _key(x, ci) not in ks]


@m('List.RemoveRange')
def list_remove_range(lst, index, count=None):
    xs = list(_lst(lst))
    i = int(force(index))
    c = 1 if force(count) is None else int(force(count))
    return xs[:i] + xs[i + c:]


@m('List.InsertRange')
def list_insert_range(lst, index, values):
    xs = list(_lst(lst))
    i = int(force(index))
    return xs[:i] + list(_lst(values)) + xs[i:]


@m('List.ReplaceRange')
def list_replace_range(lst, index, count, values):
    xs = list(_lst(lst))
    i, c = int(force(index)), int(force(count))
    return xs[:i] + list(_lst(values)) + xs[i + c:]


@m('List.ReplaceValue')
def list_replace_value(lst, old, new, replacer):
    return [call(replacer, [force(x), force(old), force(new)]) for x in _lst(lst)]


@m('List.ReplaceMatchingItems')
def list_replace_matching(lst, replacements, comparer=None):
    pairs = [(_key(force(p[0])), force(p[1])) for p in (_lst(x) for x in _lst(replacements))]
    out = []
    for x in _lst(lst):
        k = _key(x)
        for pk, nv in pairs:
            if pk == k:
                x = nv
                break
        out.append(x)
    return out


@m('List.Repeat')
def list_repeat(lst, count):
    return list(_lst(lst)) * int(force(count))


@m('List.Single')
def list_single(lst):
    xs = _lst(lst)
    if len(xs) != 1:
        raise MError(f'List.Single: 要素が1つではありません（{len(xs)}個）。')
    return force(xs[0])


@m('List.SingleOrDefault')
def list_single_or_default(lst, default=None):
    xs = _lst(lst)
    if len(xs) > 1:
        raise MError('List.SingleOrDefault: 要素が2つ以上あります。')
    return force(xs[0]) if xs else force(default)


@m('List.Union')
def list_union(lists, comparer=None):
    ci = _ignore_case(comparer)
    out, counts = [], {}
    for lst in _lst(lists):
        here = {}
        for x in _lst(lst):
            k = _key(x, ci)
            here[k] = here.get(k, 0) + 1
            if here[k] > counts.get(k, 0):
                counts[k] = here[k]
                out.append(x)
    return out


@m('List.Intersect')
def list_intersect(lists, comparer=None):
    ci = _ignore_case(comparer)
    ls = [_lst(x) for x in _lst(lists)]
    if not ls:
        return []
    others = [{_key(x, ci) for x in lst} for lst in ls[1:]]
    out, seen = [], set()
    for x in ls[0]:
        k = _key(x, ci)
        if k not in seen and all(k in o for o in others):
            seen.add(k)
            out.append(x)
    return out


@m('List.Difference')
def list_difference(a, b, comparer=None):
    ci = _ignore_case(comparer)
    remove = {}
    for x in _lst(b):
        k = _key(x, ci)
        remove[k] = remove.get(k, 0) + 1
    out = []
    for x in _lst(a):
        k = _key(x, ci)
        if remove.get(k, 0):
            remove[k] -= 1
            continue
        out.append(x)
    return out


@m('List.AnyTrue')
def list_any_true(lst):
    return any(force(x) is True for x in _lst(lst))


@m('List.AllTrue')
def list_all_true(lst):
    return all(force(x) is True for x in _lst(lst))


@m('List.MatchesAll')
def list_matches_all(lst, cond):
    return all(_is_true(call(cond, [force(x)])) for x in _lst(lst))


@m('List.MatchesAny')
def list_matches_any(lst, cond):
    return any(_is_true(call(cond, [force(x)])) for x in _lst(lst))


@m('List.Split')
def list_split(lst, size):
    xs, n = _lst(lst), int(force(size))
    return [list(xs[i:i + n]) for i in range(0, len(xs), n)]


@m('List.Alternate')
def list_alternate(lst, count, repeat_interval=None, offset=None):
    xs = _lst(lst)
    c = int(force(count))
    ri = force(repeat_interval)
    off = int(force(offset) or 0)
    if ri is None:
        return list(xs[:off]) + list(xs[off + c:])
    ri = int(ri)
    out = list(xs[:off])
    i = off
    while i < len(xs):
        i += c
        out.extend(xs[i:i + ri])
        i += ri
    return out


# ---- レコード --------------------------------------------------------------------
@m('Record.Field')
def record_field(r, name):
    return _rec(r, 'Record.Field').get(force(name))


@m('Record.FieldOrDefault')
def record_field_or_default(r, name, default=None):
    r = force(r)
    if r is None:
        return force(default)
    return _rec(r).get(force(name), force(default))


@m('Record.FieldNames')
def record_field_names(r):
    return list(_rec(r, 'Record.FieldNames').names)


@m('Record.FieldValues', 'Record.ToList')
def record_field_values(r):
    r = _rec(r)
    return [r.get(n) for n in r.names]


@m('Record.FieldCount')
def record_field_count(r):
    return len(_rec(r).names)


@m('Record.HasFields')
def record_has_fields(r, fields):
    r = _rec(r)
    return all(r.has(n) for n in _names(fields))


@m('Record.AddField')
def record_add_field(r, name, value, delayed=None):
    r = _rec(r)
    name = force(name)
    if r.has(name):
        raise MError(f'フィールド「{name}」はもうあります。')
    return MRecord(list(r.names) + [name], list(r.vals) + [value])


def _select_fields(r, names, missing):
    pairs = []
    for n in names:
        if r.has(n):
            pairs.append((n, r.raw(n)))
        elif missing == 2:
            pairs.append((n, None))
        elif missing == 0:
            raise MError(f'レコードのフィールド「{n}」が見つかりませんでした。')
    return MRecord.of(pairs)


@m('Record.SelectFields')
def record_select_fields(r, fields, missing=None):
    return _select_fields(_rec(r), _names(fields), _missing(missing))


@m('Record.RemoveFields')
def record_remove_fields(r, fields, missing=None):
    r = _rec(r)
    drop = _names(fields)
    if _missing(missing) == 0:
        for n in drop:
            if not r.has(n):
                raise MError(f'レコードのフィールド「{n}」が見つかりませんでした。')
    return MRecord.of([(n, r.raw(n)) for n in r.names if n not in drop])


@m('Record.RenameFields')
def record_rename_fields(r, renames, missing=None):
    r = _rec(r)
    mp = {str(a): str(b) for a, b in _pairs(renames)}
    if _missing(missing) == 0:
        for a in mp:
            if not r.has(a):
                raise MError(f'レコードのフィールド「{a}」が見つかりませんでした。')
    return MRecord.of([(mp.get(n, n), r.raw(n)) for n in r.names])


@m('Record.ReorderFields')
def record_reorder_fields(r, order, missing=None):
    r = _rec(r)
    names = _names(order)
    slots = sorted(r.names.index(n) for n in names if r.has(n))
    want = [n for n in names if r.has(n)]
    out = list(r.names)
    for pos, n in zip(slots, want):
        out[pos] = n
    return MRecord.of([(n, r.raw(n)) for n in out])


@m('Record.TransformFields')
def record_transform_fields(r, ops, missing=None):
    r = _rec(r)
    pairs = {n: r.raw(n) for n in r.names}
    for op in _pairs(ops):
        n, f = op[0], op[1]
        if n not in pairs:
            if _missing(missing) == 0:
                raise MError(f'レコードのフィールド「{n}」が見つかりませんでした。')
            continue
        pairs[n] = call(f, [force(pairs[n])])
    return MRecord.of(pairs)


@m('Record.Combine')
def record_combine(records):
    pairs = {}
    for r in _lst(records, 'Record.Combine'):
        r = _rec(r)
        for n in r.names:
            pairs[n] = r.raw(n)
    return MRecord.of(pairs)


@m('Record.FromList')
def record_from_list(values, fields):
    vs = _lst(values)
    f = force(fields)
    names = [n for n, _ in f.fields] if isinstance(f, MType) else _names(f)
    if len(vs) != len(names):
        raise MError('Record.FromList: 値と名前の数が合いません。')
    return MRecord(names, list(vs))


@m('Record.ToTable')
def record_to_table(r):
    r = _rec(r)
    return MTable(['Name', 'Value'], [[n, r.raw(n)] for n in r.names])


@m('Record.FromTable')
def record_from_table(t):
    t = _tbl(t)
    ni, vi = t.col('Name'), t.col('Value')
    return MRecord.of([(force(r[ni]), r[vi]) for r in t.rows])


# ---- テーブル: 作る・形を知る ----------------------------------------------------
def _column_spec(cols):
    """列の指定（数・名前のリスト・テーブルの型）→ (名前, 型)。"""
    cols = force(cols)
    if isinstance(cols, MType):
        return [n for n, _ in (cols.fields or [])], [t for _, t in (cols.fields or [])]
    if is_number(cols):
        return [f'Column{i + 1}' for i in range(int(cols))], None
    names = _names(cols)
    return names, None


@m('#table', 'Table.FromRows')
def table_from_rows(cols, rows=None):
    # #table(columns, rows) と Table.FromRows(rows, columns) は引数の順が逆
    a, b = force(cols), force(rows)
    if isinstance(a, list) and (not a or isinstance(force(a[0]), list)) and not isinstance(b, list):
        rows_, colspec = a, b
    elif isinstance(a, list) and isinstance(b, list) and a and isinstance(force(a[0]), list):
        rows_, colspec = a, b
    else:
        colspec, rows_ = a, b
    rows_ = [list(_lst(r)) for r in _lst(rows_ if rows_ is not None else [])]
    if colspec is None:
        n = max((len(r) for r in rows_), default=0)
        names, types = [f'Column{i + 1}' for i in range(n)], None
    else:
        names, types = _column_spec(colspec)
    for r in rows_:
        if len(r) != len(names):
            raise MError(f'行の値の数（{len(r)}）と列の数（{len(names)}）が合いません。')
    return MTable(names, rows_, types)


@m('Table.FromRecords')
def table_from_records(records, columns=None, missing=None):
    recs = [_rec(r) for r in _lst(records, 'Table.FromRecords')]
    if force(columns) is not None:
        names, types = _column_spec(columns)
    else:
        names, types = (list(recs[0].names) if recs else []), None
        for r in recs[1:]:
            for n in r.names:
                if n not in names:
                    if _missing(missing) == 0:
                        raise MError(f'レコードのフィールドがそろっていません（「{n}」）。')
                    names.append(n)
    rows = []
    for r in recs:
        row = []
        for n in names:
            if r.has(n):
                row.append(r.raw(n))
            elif _missing(missing) in (1, 2) or force(columns) is None:
                row.append(None)
            else:
                raise MError(f'レコードのフィールド「{n}」が見つかりませんでした。')
        rows.append(row)
    return MTable(names, rows, types)


@m('Table.FromColumns')
def table_from_columns(lists, columns=None):
    ls = [list(_lst(x)) for x in _lst(lists)]
    n = max((len(x) for x in ls), default=0)
    if force(columns) is None:
        names, types = [f'Column{i + 1}' for i in range(len(ls))], None
    else:
        names, types = _column_spec(columns)
    rows = [[(x[i] if i < len(x) else None) for x in ls] for i in range(n)]
    return MTable(names, rows, types)


@m('Table.FromList')
def table_from_list(lst, splitter=None, columns=None, default=None, extra=None):
    xs = _lst(lst)
    sp = force(splitter)
    if sp is None:
        sp = splitter_by_delimiter(',')
    parts = [[force(v) for v in _lst(call(sp, [force(x)]))] if force(x) is not None or sp else [None] for x in xs]
    if force(columns) is None:
        n = max((len(p) for p in parts), default=1)
        names, types = [f'Column{i + 1}' for i in range(n)], None
    else:
        names, types = _column_spec(columns)
    d = force(default)
    rows = []
    for p in parts:
        if len(p) > len(names) and (force(extra) in (None, 1)):
            raise MError('Table.FromList: 列より多い値があります。')
        rows.append((p + [d] * len(names))[:len(names)])
    return MTable(names, rows, types)


@m('Table.FromValue')
def table_from_value(v, options=None):
    v = force(v)
    if isinstance(v, MRecord):
        return MTable(['Name', 'Value'], [[n, v.raw(n)] for n in v.names])
    if isinstance(v, list):
        return MTable(['Value'], [[x] for x in v])
    return MTable(['Value'], [[v]])


@m('Table.ColumnNames')
def table_column_names(t):
    return list(_tbl(t, 'Table.ColumnNames').columns)


@m('Table.ColumnCount')
def table_column_count(t):
    return len(_tbl(t).columns)


@m('Table.RowCount', 'Table.ApproximateRowCount')
def table_row_count(t):
    return len(_tbl(t, 'Table.RowCount').rows)


@m('Table.IsEmpty')
def table_is_empty(t):
    return not _tbl(t).rows


@m('Table.HasColumns')
def table_has_columns(t, cols):
    t = _tbl(t)
    return all(c in t.index() for c in _names(cols))


@m('Table.Column')
def table_column(t, col):
    t = _tbl(t, 'Table.Column')
    i = t.col(force(col))
    return [r[i] for r in t.rows]


@m('Table.ToRows')
def table_to_rows(t):
    return [list(r) for r in _tbl(t).rows]


@m('Table.ToRecords')
def table_to_records(t):
    return _tbl(t).records()


@m('Table.ToColumns')
def table_to_columns(t):
    t = _tbl(t)
    return [[r[i] for r in t.rows] for i in range(len(t.columns))]


@m('Table.ToList')
def table_to_list(t, combiner=None):
    t = _tbl(t)
    cb = force(combiner) or combiner_by_delimiter(',')
    return [call(cb, [list(r)]) for r in t.rows]


@m('Table.TransformRows')
def table_transform_rows(t, fn):
    t = _tbl(t)
    return [call(fn, [rec]) for rec in t.records()]


@m('Table.ColumnsOfType')
def table_columns_of_type(t, types):
    t = _tbl(t)
    want = [force(x) for x in _lst(types)]
    out = []
    for c, ty in zip(t.columns, t.types):
        ty = ty or MType('any')
        if any(w.kind == ty.kind and (w.facet is None or w.facet == ty.facet) and w.nullable == ty.nullable
               for w in want):
            out.append(c)
    return out


@m('Table.Schema')
def table_schema(t):
    t = _tbl(t)
    rows = []
    for i, (c, ty) in enumerate(zip(t.columns, t.types)):
        ty = ty or MType('any')
        rows.append([c, i, ty.name(), ty.kind, ty.nullable])
    return MTable(['Name', 'Position', 'TypeName', 'Kind', 'IsNullable'], rows)


# ---- テーブル: 列 ----------------------------------------------------------------
def _resolve_cols(t, names, missing, fname):
    out = []
    for n in names:
        if n in t.index():
            out.append(n)
        elif missing == 0:
            raise MError(f'{fname}: テーブルの列「{n}」が見つかりませんでした。', 'Expression.Error',
                         MRecord.of({'Column': n}))
    return out


@m('Table.SelectColumns')
def table_select_columns(t, cols, missing=None):
    t = _tbl(t, 'Table.SelectColumns')
    names = _names(cols)
    miss = _missing(missing)
    idx = []
    for n in names:
        if n in t.index():
            idx.append(t.col(n))
        elif miss == 2:
            idx.append(None)
        elif miss == 0:
            raise MError(f'Table.SelectColumns: テーブルの列「{n}」が見つかりませんでした。', 'Expression.Error',
                         MRecord.of({'Column': n}))
    keep_names = [n for n in names if n in t.index() or miss == 2]
    rows = [[(r[i] if i is not None else None) for i in idx] for r in t.rows]
    return MTable(keep_names, rows, [(t.types[i] if i is not None else None) for i in idx])


@m('Table.RemoveColumns')
def table_remove_columns(t, cols, missing=None):
    t = _tbl(t, 'Table.RemoveColumns')
    drop = set(_resolve_cols(t, _names(cols), _missing(missing), 'Table.RemoveColumns'))
    keep = [i for i, c in enumerate(t.columns) if c not in drop]
    return MTable([t.columns[i] for i in keep], [[r[i] for i in keep] for r in t.rows], [t.types[i] for i in keep])


@m('Table.RenameColumns')
def table_rename_columns(t, renames, missing=None):
    t = _tbl(t, 'Table.RenameColumns')
    mp = {}
    for p in _pairs(renames):
        if len(p) != 2:
            raise MError('Table.RenameColumns: { "古い名前", "新しい名前" } の形で書きます。')
        mp[str(p[0])] = str(p[1])
    _resolve_cols(t, list(mp), _missing(missing), 'Table.RenameColumns')
    names = [mp.get(c, c) for c in t.columns]
    return MTable(names, t.rows, t.types)


@m('Table.ReorderColumns')
def table_reorder_columns(t, order, missing=None):
    t = _tbl(t, 'Table.ReorderColumns')
    want = _resolve_cols(t, _names(order), _missing(missing), 'Table.ReorderColumns')
    slots = sorted(t.col(n) for n in want)
    out = list(t.columns)
    for pos, n in zip(slots, want):
        out[pos] = n
    idx = [t.col(n) for n in out]
    return MTable(out, [[r[i] for i in idx] for r in t.rows], [t.types[i] for i in idx])


@m('Table.TransformColumnNames')
def table_transform_column_names(t, fn, options=None):
    t = _tbl(t)
    names = [force(call(fn, [c])) for c in t.columns]
    return MTable(names, t.rows, t.types)


@m('Table.PrefixColumns')
def table_prefix_columns(t, prefix):
    t = _tbl(t)
    p = force(prefix)
    return MTable([f'{p}.{c}' for c in t.columns], t.rows, t.types)


@m('Table.DuplicateColumn')
def table_duplicate_column(t, col, new, typ=None):
    t = _tbl(t, 'Table.DuplicateColumn')
    i = t.col(force(col))
    return MTable(t.columns + [force(new)], [list(r) + [r[i]] for r in t.rows],
                  t.types + [force(typ) or t.types[i]])


@m('Table.AddColumn')
def table_add_column(t, name, fn, typ=None):
    t = _tbl(t, 'Table.AddColumn')
    f = _fn(fn)
    idx = t.index()
    cols = t.columns
    rows = []
    for r in t.rows:
        rec = MRecord(cols, r, idx)
        rows.append(list(r) + [_cell(call, f, [rec])])
    return MTable(cols + [force(name)], rows, t.types + [force(typ)])


@m('Table.AddIndexColumn')
def table_add_index_column(t, name, start=None, step=None, typ=None):
    t = _tbl(t, 'Table.AddIndexColumn')
    s = 0 if force(start) is None else force(start)
    st = 1 if force(step) is None else force(step)
    return MTable(t.columns + [force(name)], [list(r) + [num(s + i * st)] for i, r in enumerate(t.rows)],
                  t.types + [force(typ) or MType('number', facet='Int64')])


def _transform_ops(ops):
    ops = force(ops)
    if not isinstance(ops, list):
        raise MError('Table.TransformColumns の変換の指定が読めません。')
    if ops and isinstance(force(ops[0]), str):
        ops = [ops]
    out = []
    for op in ops:
        op = _vals(_lst(op))
        out.append((op[0], op[1], op[2] if len(op) > 2 else None))
    return out


@m('Table.TransformColumns')
def table_transform_columns(t, ops, default=None, missing=None):
    t = _tbl(t, 'Table.TransformColumns')
    rows = [list(r) for r in t.rows]
    types = list(t.types)
    done = set()
    for name, f, typ in _transform_ops(ops):
        if name not in t.index():
            if _missing(missing) == 0:
                raise MError(f'Table.TransformColumns: テーブルの列「{name}」が見つかりませんでした。',
                             'Expression.Error', MRecord.of({'Column': name}))
            continue
        i = t.col(name)
        done.add(i)
        f = _fn(f)
        for r in rows:
            v = r[i]
            r[i] = v if isinstance(v, ErrorCell) else _cell(call, f, [v])
        if typ is not None:
            types[i] = typ
    d = force(default)
    if d is not None:
        d = _fn(d)
        for i in range(len(t.columns)):
            if i in done:
                continue
            for r in rows:
                v = r[i]
                r[i] = v if isinstance(v, ErrorCell) else _cell(call, d, [v])
    return MTable(t.columns, rows, types)


@m('Table.TransformColumnTypes')
def table_transform_column_types(t, ops, cult=None):
    t = _tbl(t, 'Table.TransformColumnTypes')
    opt = force(cult)
    if isinstance(opt, MRecord):
        culture_name, missing = opt.get('Culture', None), _missing(opt.get('MissingField', None))
    else:
        culture_name, missing = opt, 0
    rows = [list(r) for r in t.rows]
    types = list(t.types)
    for p in _pairs(ops):
        name, typ = str(p[0]), p[1]
        if name not in t.index():
            if missing == 0:
                raise MError(f'Table.TransformColumnTypes: テーブルの列「{name}」が見つかりませんでした。',
                             'Expression.Error', MRecord.of({'Column': name}))
            continue
        i = t.col(name)
        conv = C.converter(typ, culture_name)
        for r in rows:
            v = r[i]
            if isinstance(v, ErrorCell) or v is None:
                continue
            try:
                r[i] = conv(v)
            except MError as e:
                r[i] = ErrorCell(e.mark_origin())
        types[i] = typ
    return MTable(t.columns, rows, types)


@m('Table.CombineColumns')
def table_combine_columns(t, cols, combiner, new):
    t = _tbl(t, 'Table.CombineColumns')
    names = _names(cols)
    idx = [t.col(n) for n in names]
    keep = [i for i in range(len(t.columns)) if i not in idx]
    at = min(idx) if idx else len(t.columns)
    insert = sum(1 for i in keep if i < at)
    cb = _fn(combiner)
    out_cols = [t.columns[i] for i in keep]
    out_cols.insert(insert, force(new))
    out_types = [t.types[i] for i in keep]
    out_types.insert(insert, None)
    rows = []
    for r in t.rows:
        row = [r[i] for i in keep]
        row.insert(insert, _cell(call, cb, [[r[i] for i in idx]]))
        rows.append(row)
    return MTable(out_cols, rows, out_types)


@m('Table.SplitColumn')
def table_split_column(t, col, splitter, names_or_count=None, default=None, extra=None):
    t = _tbl(t, 'Table.SplitColumn')
    name = force(col)
    i = t.col(name)
    sp = _fn(splitter)
    parts = []
    for r in t.rows:
        v = r[i]
        if isinstance(v, ErrorCell):
            parts.append(v)
            continue
        v = force(v)
        parts.append([None] if v is None else [force(x) for x in _lst(call(sp, [v]))])
    spec = force(names_or_count)
    if spec is None:
        n = max((len(p) for p in parts if isinstance(p, list)), default=1)
        new = [f'{name}.{k + 1}' for k in range(n)]
    elif is_number(spec):
        new = [f'{name}.{k + 1}' for k in range(int(spec))]
    else:
        new = _names(spec)
    d = force(default)
    rows = []
    for r, p in zip(t.rows, parts):
        cells = [p] * len(new) if isinstance(p, ErrorCell) else (p + [d] * len(new))[:len(new)]
        rows.append(list(r[:i]) + cells + list(r[i + 1:]))
    return MTable(t.columns[:i] + new + t.columns[i + 1:], rows, t.types[:i] + [None] * len(new) + t.types[i + 1:])


# ---- テーブル: 行 ----------------------------------------------------------------
@m('Table.SelectRows')
def table_select_rows(t, cond):
    t = _tbl(t, 'Table.SelectRows')
    f = _fn(cond)
    idx, cols = t.index(), t.columns
    out = []
    for r in t.rows:
        v = force(call(f, [MRecord(cols, r, idx)]))
        if v is True:
            out.append(r)
        elif v is not None and v is not False:
            raise MError(f'行を選ぶ条件が true／false になりません（{type_name(v)}）。')
    return MTable(cols, out, t.types)


@m('Table.FirstN', 'Table.Top')
def table_first_n(t, count_or_condition):
    t = _tbl(t, 'Table.FirstN')
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        out = []
        for r in t.rows:
            if not _is_true(call(c, [t.record(r)])):
                break
            out.append(r)
        return MTable(t.columns, out, t.types)
    return MTable(t.columns, t.rows[:int(c)], t.types)


@m('Table.LastN')
def table_last_n(t, count_or_condition):
    t = _tbl(t, 'Table.LastN')
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        out = []
        for r in reversed(t.rows):
            if not _is_true(call(c, [t.record(r)])):
                break
            out.append(r)
        return MTable(t.columns, out[::-1], t.types)
    n = int(c)
    return MTable(t.columns, t.rows[-n:] if n else [], t.types)


@m('Table.Skip', 'Table.RemoveFirstN')
def table_skip(t, count_or_condition=None):
    t = _tbl(t, 'Table.Skip')
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        i = 0
        while i < len(t.rows) and _is_true(call(c, [t.record(t.rows[i])])):
            i += 1
        return MTable(t.columns, t.rows[i:], t.types)
    return MTable(t.columns, t.rows[(1 if c is None else int(c)):], t.types)


@m('Table.RemoveLastN')
def table_remove_last_n(t, count_or_condition=None):
    t = _tbl(t, 'Table.RemoveLastN')
    c = force(count_or_condition)
    if isinstance(c, MFunction):
        i = len(t.rows)
        while i > 0 and _is_true(call(c, [t.record(t.rows[i - 1])])):
            i -= 1
        return MTable(t.columns, t.rows[:i], t.types)
    n = 1 if c is None else int(c)
    return MTable(t.columns, t.rows[:-n] if n else list(t.rows), t.types)


@m('Table.Range')
def table_range(t, offset, count=None):
    t = _tbl(t, 'Table.Range')
    o = int(force(offset))
    c = force(count)
    return MTable(t.columns, t.rows[o:] if c is None else t.rows[o:o + int(c)], t.types)


@m('Table.RemoveRows')
def table_remove_rows(t, offset, count=None):
    t = _tbl(t, 'Table.RemoveRows')
    o = int(force(offset))
    c = 1 if force(count) is None else int(force(count))
    return MTable(t.columns, t.rows[:o] + t.rows[o + c:], t.types)


@m('Table.AlternateRows')
def table_alternate_rows(t, offset, skip, take):
    t = _tbl(t)
    o, s, k = int(force(offset)), int(force(skip)), int(force(take))
    out = list(t.rows[:o])
    i = o
    while i < len(t.rows):
        i += s
        out.extend(t.rows[i:i + k])
        i += k
    return MTable(t.columns, out, t.types)


@m('Table.ReverseRows')
def table_reverse_rows(t):
    t = _tbl(t)
    return MTable(t.columns, t.rows[::-1], t.types)


@m('Table.Repeat')
def table_repeat(t, count):
    t = _tbl(t)
    return MTable(t.columns, t.rows * int(force(count)), t.types)


@m('Table.First')
def table_first(t, default=None):
    t = _tbl(t, 'Table.First')
    return t.record(t.rows[0]) if t.rows else force(default)


@m('Table.Last')
def table_last(t, default=None):
    t = _tbl(t, 'Table.Last')
    return t.record(t.rows[-1]) if t.rows else force(default)


@m('Table.FirstValue')
def table_first_value(t, default=None):
    t = _tbl(t)
    return force(t.rows[0][0]) if t.rows and t.columns else force(default)


@m('Table.SingleRow')
def table_single_row(t):
    t = _tbl(t)
    if len(t.rows) != 1:
        raise MError(f'Table.SingleRow: 行が1行ではありません（{len(t.rows)}行）。')
    return t.record(t.rows[0])


@m('Table.InsertRows')
def table_insert_rows(t, offset, records):
    t = _tbl(t)
    o = int(force(offset))
    new = [[_rec(r).raw(c) if _rec(r).has(c) else None for c in t.columns] for r in _lst(records)]
    return MTable(t.columns, t.rows[:o] + new + t.rows[o:], t.types)


def _row_has_error(r, idx):
    return any(isinstance(r[i], ErrorCell) or (isinstance(r[i], _thunk_types()) and _thunk_error(r[i])) for i in idx)


def _thunk_types():
    from navi_m import Thunk
    return Thunk


def _thunk_error(v):
    try:
        force(v)
        return False
    except MError:
        return True


@m('Table.RemoveRowsWithErrors')
def table_remove_rows_with_errors(t, cols=None):
    t = _tbl(t, 'Table.RemoveRowsWithErrors')
    idx = [t.col(n) for n in _names(cols)] if force(cols) is not None else range(len(t.columns))
    return MTable(t.columns, [r for r in t.rows if not _row_has_error(r, idx)], t.types)


@m('Table.SelectRowsWithErrors')
def table_select_rows_with_errors(t, cols=None):
    t = _tbl(t, 'Table.SelectRowsWithErrors')
    idx = [t.col(n) for n in _names(cols)] if force(cols) is not None else range(len(t.columns))
    return MTable(t.columns, [r for r in t.rows if _row_has_error(r, idx)], t.types)


@m('Table.ReplaceErrorValues')
def table_replace_error_values(t, ops):
    t = _tbl(t, 'Table.ReplaceErrorValues')
    rows = [list(r) for r in t.rows]
    for p in _pairs(ops):
        i = t.col(str(p[0]))
        for r in rows:
            if isinstance(r[i], ErrorCell):
                r[i] = p[1]
    return MTable(t.columns, rows, t.types)


@m('Table.ReplaceValue')
def table_replace_value(t, old, new, replacer, cols):
    t = _tbl(t, 'Table.ReplaceValue')
    rp = _fn(replacer)
    idx = [t.col(n) for n in _names(cols)]
    old, new = force(old), force(new)
    rows = []
    for r in t.rows:
        rec = t.record(r) if isinstance(old, MFunction) or isinstance(new, MFunction) else None
        o = call(old, [rec]) if isinstance(old, MFunction) else old
        n = call(new, [rec]) if isinstance(new, MFunction) else new
        row = list(r)
        for i in idx:
            if isinstance(row[i], ErrorCell):
                continue
            row[i] = _cell(call, rp, [force(row[i]), o, n])
        rows.append(row)
    return MTable(t.columns, rows, t.types)


def _fill(t, cols, down):
    t = _tbl(t)
    idx = [t.col(n) for n in _names(cols)]
    rows = [list(r) for r in t.rows]
    seq = rows if down else rows[::-1]
    last = {i: None for i in idx}
    for r in seq:
        for i in idx:
            v = r[i]
            if not isinstance(v, ErrorCell) and force(v) is None:
                r[i] = last[i]
            else:
                last[i] = v
    return MTable(t.columns, rows, t.types)


@m('Table.FillDown')
def table_fill_down(t, cols):
    return _fill(t, cols, True)


@m('Table.FillUp')
def table_fill_up(t, cols):
    return _fill(t, cols, False)


def _sort_specs(t, crit):
    crit = force(crit)
    if isinstance(crit, list) and len(crit) == 2 and not isinstance(force(crit[0]), list) \
            and is_number(force(crit[1])):
        crit = [crit]
    if not isinstance(crit, list):
        crit = [crit]
    specs = []
    for c in crit:
        c = force(c)
        order = 0
        if isinstance(c, list):
            sel = force(c[0])
            order = int(force(c[1])) if len(c) > 1 else 0
        else:
            sel = c
        if isinstance(sel, str):
            i = t.col(sel)
            specs.append((lambda r, i=i: sort_key(r[i]), order))
        elif isinstance(sel, MFunction) and sel.max >= 2:
            specs.append(('cmp', sel, order))
        elif isinstance(sel, MFunction):
            specs.append((lambda r, f=sel: sort_key(call(f, [t.record(r)])), order))
        else:
            raise MError('Table.Sort の並べ方の指定が読めません。')
    return specs


@m('Table.Sort')
def table_sort(t, crit):
    t = _tbl(t, 'Table.Sort')
    rows = list(t.rows)
    for spec in reversed(_sort_specs(t, crit)):
        if spec[0] == 'cmp':
            f = spec[1]
            rows.sort(key=functools.cmp_to_key(lambda a, b: int(force(call(f, [t.record(a), t.record(b)])))),
                      reverse=spec[2] == 1)
        else:
            rows.sort(key=spec[0], reverse=spec[1] == 1)
    return MTable(t.columns, rows, t.types)


@m('Table.Distinct')
def table_distinct(t, crit=None):
    t = _tbl(t, 'Table.Distinct')
    crit = force(crit)
    ci = False
    cols = None
    if isinstance(crit, MFunction):
        ci = _ignore_case(crit)
    elif isinstance(crit, list) and len(crit) == 2 and isinstance(force(crit[1]), MFunction):
        cols, ci = _names(crit[0]), _ignore_case(crit[1])
    elif crit is not None:
        cols = _names(crit)
    idx = [t.col(c) for c in cols] if cols else list(range(len(t.columns)))
    seen, out = set(), []
    for r in t.rows:
        k = tuple(_key(r[i], ci) for i in idx)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return MTable(t.columns, out, t.types)


@m('Table.IsDistinct')
def table_is_distinct(t, crit=None):
    t = _tbl(t)
    return len(table_distinct(t, crit).rows) == len(t.rows)


@m('Table.MatchesAllRows')
def table_matches_all_rows(t, cond):
    t = _tbl(t)
    return all(_is_true(call(cond, [rec])) for rec in t.records())


@m('Table.MatchesAnyRows')
def table_matches_any_rows(t, cond):
    t = _tbl(t)
    return any(_is_true(call(cond, [rec])) for rec in t.records())


@m('Table.FindText')
def table_find_text(t, text):
    t = _tbl(t)
    s = force(text)
    out = [r for r in t.rows if any(isinstance(force(v), str) and s in force(v) for v in r
                                     if not isinstance(v, ErrorCell))]
    return MTable(t.columns, out, t.types)


@m('Table.Max')
def table_max(t, crit, default=None):
    t = _tbl(t)
    if not t.rows:
        return force(default)
    return t.record(table_sort(t, [crit, 1]).rows[0])


@m('Table.Min')
def table_min(t, crit, default=None):
    t = _tbl(t)
    if not t.rows:
        return force(default)
    return t.record(table_sort(t, [crit, 0]).rows[0])


@m('Table.Split')
def table_split(t, size):
    t = _tbl(t)
    n = int(force(size))
    return [MTable(t.columns, t.rows[i:i + n], t.types) for i in range(0, len(t.rows), n)]


# ---- テーブル: 見出し・転置 --------------------------------------------------------
@m('Table.PromoteHeaders')
def table_promote_headers(t, options=None):
    t = _tbl(t, 'Table.PromoteHeaders')
    if not t.rows:
        return t
    opt = force(options)
    all_scalars = bool(opt.get('PromoteAllScalars', False)) if isinstance(opt, MRecord) else False
    cult = opt.get('Culture', None) if isinstance(opt, MRecord) else None
    names, seen = [], set()
    for i, v in enumerate(t.rows[0]):
        v = None if isinstance(v, ErrorCell) else force(v)
        if isinstance(v, str) and v != '':
            n = v
        elif v is not None and v != '' and all_scalars and not isinstance(v, (list, MRecord, MTable)):
            n = C.to_text(v, None, cult)
        else:
            n = f'Column{i + 1}'
        base, k = n, 0
        while n in seen:
            k += 1
            n = f'{base}_{k}'
        seen.add(n)
        names.append(n)
    return MTable(names, t.rows[1:], [None] * len(names))


@m('Table.DemoteHeaders')
def table_demote_headers(t):
    t = _tbl(t, 'Table.DemoteHeaders')
    return MTable([f'Column{i + 1}' for i in range(len(t.columns))], [list(t.columns)] + [list(r) for r in t.rows])


@m('Table.Transpose')
def table_transpose(t, cols=None):
    t = _tbl(t, 'Table.Transpose')
    n = len(t.rows)
    names = _column_spec(cols)[0] if force(cols) is not None else [f'Column{i + 1}' for i in range(n)]
    rows = [[t.rows[r][c] for r in range(n)] for c in range(len(t.columns))]
    return MTable(names, rows)


# ---- テーブル: 結合・展開 ----------------------------------------------------------
@m('Table.Combine')
def table_combine(tables, columns=None):
    ts = [_tbl(x, 'Table.Combine') for x in _lst(tables, 'Table.Combine')]
    if force(columns) is not None:
        names, _types = _column_spec(columns)
    else:
        names = []
        seen = set()
        for x in ts:
            for c in x.columns:
                if c not in seen:
                    seen.add(c)
                    names.append(c)
    types = []
    for c in names:
        got = [x.types[x.col(c)] for x in ts if c in x.index()]
        first = got[0] if got else None
        same = first is not None and all(g is not None and g.kind == first.kind and g.facet == first.facet
                                         for g in got) and len(got) == len(ts)
        types.append(first if same else None)
    rows = []
    for x in ts:
        idx = [x.index().get(c) for c in names]
        rows.extend([[(r[i] if i is not None else None) for i in idx] for r in x.rows])
    return MTable(names, rows, types)


def _expand_names(spec_names, new_names):
    names = _names(spec_names)
    new = _names(new_names) if force(new_names) is not None else names
    if len(new) != len(names):
        raise MError('展開する列の名前と、新しい名前の数が合いません。')
    return names, new


@m('Table.ExpandTableColumn')
def table_expand_table_column(t, col, names, new_names=None):
    t = _tbl(t, 'Table.ExpandTableColumn')
    i = t.col(force(col))
    names, new = _expand_names(names, new_names)
    clash = [n for n in new if n in t.index() and n != t.columns[i]]
    if clash:
        raise MError(f'展開した列の名前「{clash[0]}」が、もとの列と重なっています。')
    rows = []
    types = None
    for r in t.rows:
        v = force(r[i])
        if v is None:
            rows.append(list(r[:i]) + [None] * len(names) + list(r[i + 1:]))
            continue
        if not isinstance(v, MTable):
            raise MError(f'列「{t.columns[i]}」の中身がテーブルではありません（{type_name(v)}）。')
        idx = [v.index().get(n) for n in names]
        if types is None:
            types = [(v.types[j] if j is not None else None) for j in idx]
        if not v.rows:
            rows.append(list(r[:i]) + [None] * len(names) + list(r[i + 1:]))
            continue
        for nr in v.rows:
            rows.append(list(r[:i]) + [(nr[j] if j is not None else None) for j in idx] + list(r[i + 1:]))
    return MTable(t.columns[:i] + new + t.columns[i + 1:], rows,
                  t.types[:i] + (types or [None] * len(new)) + t.types[i + 1:])


@m('Table.ExpandRecordColumn')
def table_expand_record_column(t, col, names, new_names=None):
    t = _tbl(t, 'Table.ExpandRecordColumn')
    i = t.col(force(col))
    names, new = _expand_names(names, new_names)
    rows = []
    for r in t.rows:
        v = force(r[i])
        if v is None:
            cells = [None] * len(names)
        elif isinstance(v, MRecord):
            cells = [(v.raw(n) if v.has(n) else None) for n in names]
        else:
            raise MError(f'列「{t.columns[i]}」の中身がレコードではありません（{type_name(v)}）。')
        rows.append(list(r[:i]) + cells + list(r[i + 1:]))
    return MTable(t.columns[:i] + new + t.columns[i + 1:], rows, t.types[:i] + [None] * len(new) + t.types[i + 1:])


@m('Table.ExpandListColumn')
def table_expand_list_column(t, col):
    t = _tbl(t, 'Table.ExpandListColumn')
    i = t.col(force(col))
    rows = []
    for r in t.rows:
        v = force(r[i])
        if v is None or (isinstance(v, list) and not v):
            rows.append(list(r[:i]) + [None] + list(r[i + 1:]))
        elif isinstance(v, list):
            for x in v:
                rows.append(list(r[:i]) + [x] + list(r[i + 1:]))
        else:
            raise MError(f'列「{t.columns[i]}」の中身がリストではありません（{type_name(v)}）。')
    return MTable(t.columns, rows, t.types[:i] + [None] + t.types[i + 1:])


@m('Table.AggregateTableColumn')
def table_aggregate_table_column(t, col, aggregations):
    t = _tbl(t)
    i = t.col(force(col))
    specs = [_vals(_lst(a)) for a in _lst(aggregations)]
    rows = []
    for r in t.rows:
        v = force(r[i])
        cells = []
        for s in specs:
            vals = [] if v is None else table_column(v, s[0])
            cells.append(_cell(call, s[1], [vals]))
        rows.append(list(r[:i]) + cells + list(r[i + 1:]))
    return MTable(t.columns[:i] + [s[2] for s in specs] + t.columns[i + 1:], rows)


def _join_index(t, keys, ci):
    idx = [t.col(k) for k in keys]
    out = {}
    for n, r in enumerate(t.rows):
        out.setdefault(tuple(_key(r[i], ci) for i in idx), []).append(n)
    return idx, out


def _join_ci(comparers):
    c = force(comparers)
    if isinstance(c, list):
        return any(_ignore_case(x) for x in c)
    return _ignore_case(c)


@m('Table.NestedJoin')
def table_nested_join(t1, key1, t2, key2, new, kind=None, comparers=None):
    a, b = _tbl(t1, 'Table.NestedJoin'), _tbl(t2, 'Table.NestedJoin')
    k1, k2 = _names(key1), _names(key2)
    if len(k1) != len(k2):
        raise MError('Table.NestedJoin: キーの列の数が左右で違います。')
    kind = 1 if force(kind) is None else int(force(kind))
    ci = _join_ci(comparers)
    ia = [a.col(k) for k in k1]
    _ib, index = _join_index(b, k2, ci)
    used = set()
    rows = []
    name = force(new)
    if name in a.index():
        raise MError(f'列「{name}」はもうあります。')
    for r in a.rows:
        hits = index.get(tuple(_key(r[i], ci) for i in ia), [])
        used.update(hits)
        if kind == 0 and not hits:
            continue
        if kind == 4 and hits:
            continue
        if kind in (2, 5):
            continue
        rows.append(list(r) + [MTable(b.columns, [b.rows[h] for h in hits], b.types)])
    if kind in (2, 3, 5):
        if kind == 2:
            rows = []
            for r in a.rows:
                hits = index.get(tuple(_key(r[i], ci) for i in ia), [])
                if hits:
                    rows.append(list(r) + [MTable(b.columns, [b.rows[h] for h in hits], b.types)])
        for n, r in enumerate(b.rows):
            if n not in used:
                rows.append([None] * len(a.columns) + [MTable(b.columns, [r], b.types)])
    return MTable(a.columns + [name], rows, a.types + [MType('table')])


@m('Table.Join')
def table_join(t1, key1, t2, key2, kind=None, algorithm=None, comparers=None):
    a, b = _tbl(t1, 'Table.Join'), _tbl(t2, 'Table.Join')
    k1, k2 = _names(key1), _names(key2)
    clash = [c for c in b.columns if c in a.index()]
    if clash:
        raise MError(f'Table.Join: 左右のテーブルに同じ名前の列「{clash[0]}」があります（先に名前を変えるか、NestedJoin を使ってください）。')
    kind = 0 if force(kind) is None else int(force(kind))
    ci = _join_ci(comparers)
    ia = [a.col(k) for k in k1]
    _ib, index = _join_index(b, k2, ci)
    used, rows = set(), []
    for r in a.rows:
        hits = index.get(tuple(_key(r[i], ci) for i in ia), [])
        used.update(hits)
        if hits:
            if kind in (4, 5):
                continue
            for h in hits:
                rows.append(list(r) + list(b.rows[h]))
        elif kind in (1, 3, 4):
            rows.append(list(r) + [None] * len(b.columns))
    if kind in (2, 3, 5):
        for n, r in enumerate(b.rows):
            if n not in used:
                rows.append([None] * len(a.columns) + list(r))
    if kind == 5:
        rows = [r for r in rows if all(x is None for x in r[:len(a.columns)])]
    return MTable(a.columns + b.columns, rows, a.types + b.types)


# ---- テーブル: グループ化・ピボット ------------------------------------------------
@m('Table.Group')
def table_group(t, keys, aggregated, kind=None, comparer=None):
    t = _tbl(t, 'Table.Group')
    knames = _names(keys)
    kidx = [t.col(k) for k in knames]
    aggs = force(aggregated)
    if aggs and not isinstance(force(aggs[0]), list):
        aggs = [aggs]
    specs = [_vals(_lst(a)) for a in aggs]
    ci = _ignore_case(comparer)
    local = force(kind) == 0
    groups, order = {}, []
    last = None
    for r in t.rows:
        k = tuple(_key(r[i], ci) for i in kidx)
        if local:
            if last is None or last[0] != k:
                last = (k, [])
                order.append(last)
            last[1].append(r)
        else:
            if k not in groups:
                groups[k] = []
                order.append((k, groups[k]))
            groups[k].append(r)
    rows = []
    for _k, members in order:
        sub = MTable(t.columns, members, t.types)
        row = [members[0][i] for i in kidx]
        for s in specs:
            row.append(_cell(call, s[1], [sub]))
        rows.append(row)
    return MTable(knames + [s[0] for s in specs], rows,
                  [t.types[i] for i in kidx] + [(s[2] if len(s) > 2 else None) for s in specs])


@m('Table.Unpivot')
def table_unpivot(t, cols, attr, value):
    t = _tbl(t, 'Table.Unpivot')
    piv = set(_names(cols))
    for c in piv:
        t.col(c)
    return _unpivot(t, [i for i, c in enumerate(t.columns) if c in piv], force(attr), force(value))


@m('Table.UnpivotOtherColumns')
def table_unpivot_other_columns(t, keep, attr, value):
    t = _tbl(t, 'Table.UnpivotOtherColumns')
    keep = set(_names(keep))
    for c in keep:
        t.col(c)
    return _unpivot(t, [i for i, c in enumerate(t.columns) if c not in keep], force(attr), force(value))


def _unpivot(t, piv, attr, value):
    keep = [i for i in range(len(t.columns)) if i not in piv]
    rows = []
    for r in t.rows:
        base = [r[i] for i in keep]
        for i in piv:
            v = r[i]
            if not isinstance(v, ErrorCell) and force(v) is None:
                continue        # 値が null のセルは出さない（Power Query と同じ）
            rows.append(base + [t.columns[i], v])
    return MTable([t.columns[i] for i in keep] + [attr, value], rows,
                  [t.types[i] for i in keep] + [MType('text'), None])


@m('Table.Pivot')
def table_pivot(t, values, attr, value, agg=None):
    t = _tbl(t, 'Table.Pivot')
    ai, vi = t.col(force(attr)), t.col(force(value))
    pv = _vals(_lst(values))
    names = [C.to_text(x) if x is not None else '' for x in pv]
    pos = {_key(x): n for n, x in enumerate(pv)}
    others = [i for i in range(len(t.columns)) if i not in (ai, vi)]
    groups, order = {}, []
    for r in t.rows:
        k = tuple(_key(r[i]) for i in others)
        if k not in groups:
            groups[k] = (r, [[] for _ in pv])
            order.append(k)
        p = pos.get(_key(r[ai]))
        if p is not None:
            groups[k][1][p].append(r[vi])
    f = force(agg)
    rows = []
    for k in order:
        first, cells = groups[k]
        row = [first[i] for i in others]
        for vals in cells:
            if f is not None:
                row.append(_cell(call, f, [vals]))
            elif len(vals) > 1:
                row.append(ErrorCell(MError('列の値が多すぎます（集計の関数を指定してください）。',
                                            'Expression.Error').mark_origin()))
            else:
                row.append(vals[0] if vals else None)
        rows.append(row)
    return MTable([t.columns[i] for i in others] + names, rows, [t.types[i] for i in others] + [None] * len(names))
