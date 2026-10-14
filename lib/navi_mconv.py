"""M の値の変換と書式（2.4.0）。Text.From・Number.FromText・Date.ToText などの土台。

文化圏（Culture）は ja-JP を既定にする（日本語版の Excel で作った式が、同じ読み方・書き方で動くように）。
ほかに en-US・en-GB・de-DE・fr-FR を持つ（小数点・桁区切り・日付の並びが違う代表）。
書式の文字（yyyy/MM/dd・#,##0.00 など）は .NET の書き方に合わせる（Power Query はそれを使う）。
"""
import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import (ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal,
                     InvalidOperation)

from navi_m import MError, MRecord, MType, force, is_number, num, type_name


# ---- 文化圏 ----------------------------------------------------------------------
_JA_DAYS = ('月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日', '日曜日')
_EN_DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
_EN_MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
              'November', 'December')
_DE_MONTHS = ('Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober',
              'November', 'Dezember')
_DE_DAYS = ('Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag')
_FR_MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
              'novembre', 'décembre')
_FR_DAYS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')

CULTURES = {
    'ja-JP': {'dec': '.', 'grp': ',', 'order': 'ymd', 'd': 'yyyy/MM/dd', 'D': 'yyyy年M月d日', 't': 'H:mm', 'T': 'H:mm:ss',
              'M': 'M月d日', 'Y': 'yyyy年M月', 'months': tuple(f'{i}月' for i in range(1, 13)),
              'months_abbr': tuple(f'{i}月' for i in range(1, 13)), 'days': _JA_DAYS,
              'days_abbr': tuple(d[0] for d in _JA_DAYS), 'am': '午前', 'pm': '午後', 'cur': '¥', 'true': 'TRUE'},
    'en-US': {'dec': '.', 'grp': ',', 'order': 'mdy', 'd': 'M/d/yyyy', 'D': 'dddd, MMMM d, yyyy', 't': 'h:mm tt',
              'T': 'h:mm:ss tt', 'M': 'MMMM d', 'Y': 'MMMM yyyy', 'months': _EN_MONTHS,
              'months_abbr': tuple(m[:3] for m in _EN_MONTHS), 'days': _EN_DAYS,
              'days_abbr': tuple(d[:3] for d in _EN_DAYS), 'am': 'AM', 'pm': 'PM', 'cur': '$'},
    'en-GB': {'dec': '.', 'grp': ',', 'order': 'dmy', 'd': 'dd/MM/yyyy', 'D': 'dd MMMM yyyy', 't': 'HH:mm',
              'T': 'HH:mm:ss', 'M': 'd MMMM', 'Y': 'MMMM yyyy', 'months': _EN_MONTHS,
              'months_abbr': tuple(m[:3] for m in _EN_MONTHS), 'days': _EN_DAYS,
              'days_abbr': tuple(d[:3] for d in _EN_DAYS), 'am': 'am', 'pm': 'pm', 'cur': '£'},
    'de-DE': {'dec': ',', 'grp': '.', 'order': 'dmy', 'd': 'dd.MM.yyyy', 'D': 'dddd, d. MMMM yyyy', 't': 'HH:mm',
              'T': 'HH:mm:ss', 'M': 'd. MMMM', 'Y': 'MMMM yyyy', 'months': _DE_MONTHS,
              'months_abbr': tuple(m[:3] for m in _DE_MONTHS), 'days': _DE_DAYS,
              'days_abbr': tuple(d[:2] for d in _DE_DAYS), 'am': '', 'pm': '', 'cur': '€'},
    'fr-FR': {'dec': ',', 'grp': ' ', 'order': 'dmy', 'd': 'dd/MM/yyyy', 'D': 'dddd d MMMM yyyy', 't': 'HH:mm',
              'T': 'HH:mm:ss', 'M': 'd MMMM', 'Y': 'MMMM yyyy', 'months': _FR_MONTHS,
              'months_abbr': tuple(m[:4] + '.' for m in _FR_MONTHS), 'days': _FR_DAYS,
              'days_abbr': tuple(d[:3] + '.' for d in _FR_DAYS), 'am': '', 'pm': '', 'cur': '€'},
}
DEFAULT_CULTURE = 'ja-JP'


def culture(name=None):
    name = str(name or DEFAULT_CULTURE)
    if name in CULTURES:
        return CULTURES[name]
    head = name.split('-')[0].lower()
    for k, v in CULTURES.items():
        if k.split('-')[0].lower() == head:
            return v
    return CULTURES[DEFAULT_CULTURE]


def options(v, key='Format'):
    """書式の引数は "yyyy" か [Format="yyyy", Culture="ja-JP"] か、culture の文字列。→ (書式, 文化圏)。"""
    v = force(v)
    if isinstance(v, MRecord):
        return (v.get('Format', None), v.get('Culture', None))
    return (v, None)


# ---- 数 --------------------------------------------------------------------------
_NUM_CLEAN = re.compile(r'[\s  ]')


def parse_number(text, cult=None):
    """文字 → 数。桁区切り・通貨記号・％・(123) の負数・全角数字を読む。読めなければ None。"""
    c = culture(cult)
    s = unicodedata.normalize('NFKC', str(text)).strip()
    if not s:
        return None
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg, s = True, s[1:-1].strip()
    pct = s.endswith('%')
    if pct:
        s = s[:-1].strip()
    for sym in ('¥', '￥', '$', '€', '£', c.get('cur', '')):
        if sym:
            s = s.replace(sym, '')
    s = _NUM_CLEAN.sub('', s)
    if s.endswith('-') and not s.startswith('-'):
        neg, s = not neg, s[:-1]
    if c['grp']:
        s = s.replace(c['grp'], '')
    if c['dec'] != '.':
        s = s.replace('.', '').replace(c['dec'], '.')
    low = s.lower()
    if low in ('infinity', '∞', '+infinity'):
        v = math.inf
    elif low in ('-infinity', '-∞'):
        v = -math.inf
    elif low == 'nan':
        v = math.nan
    else:
        if not re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', s):
            if re.fullmatch(r'0[xX][0-9a-fA-F]+', s):
                v = int(s, 16)
            else:
                return None
        else:
            v = float(s) if any(ch in s for ch in '.eE') else int(s)
    if pct:
        v = v / 100
    if neg:
        v = -v
    return num(v)


def to_number(v, cult=None, what='数値'):
    v = force(v)
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if is_number(v):
        return v
    if isinstance(v, str):
        got = parse_number(v, cult)
        if got is None:
            raise MError(f'「{v}」を{what}に変換できませんでした。', 'DataFormat.Error', v)
        return got
    if isinstance(v, datetime):
        return num(serial_from_datetime(v))
    if isinstance(v, date):
        return (v - _EPOCH).days
    if isinstance(v, time):
        return num((v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6) / 86400)
    if isinstance(v, timedelta):
        return num(v.total_seconds() / 86400)
    raise MError(f'{type_name(v)} を{what}に変換できません。', 'Expression.Error')


def round_number(x, digits=0, mode=None):
    """Number.Round。RoundingMode は「ちょうど中間のときにどちらへ寄せるか」だけを決める（既定は偶数へ。Power Query と同じ）。"""
    x = force(x)
    if x is None:
        return None
    if not is_number(x):
        raise MError(f'{type_name(x)} は丸められません。')
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return x
    digits = int(force(digits) or 0)
    mode = 4 if force(mode) is None else int(force(mode))
    # 0=Up（中間は大きい方へ）1=Down（小さい方へ）2=AwayFromZero 3=TowardZero 4=ToEven
    if mode == 0:
        rounding = ROUND_HALF_UP if x >= 0 else ROUND_HALF_DOWN
    elif mode == 1:
        rounding = ROUND_HALF_DOWN if x >= 0 else ROUND_HALF_UP
    else:
        rounding = {2: ROUND_HALF_UP, 3: ROUND_HALF_DOWN}.get(mode, ROUND_HALF_EVEN)
    return _quantize(x, digits, rounding)


def round_direction(x, digits=0, up=True):
    """Number.RoundUp・RoundDown（中間に限らず、上・下へ寄せる）。"""
    x = force(x)
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return x
    return _quantize(x, int(force(digits) or 0), ROUND_CEILING if up else ROUND_FLOOR)


def round_toward_zero(x, digits=0):
    x = force(x)
    if x is None:
        return None
    return _quantize(x, int(force(digits) or 0), ROUND_DOWN)


def _quantize(x, digits, rounding):
    q = Decimal(1).scaleb(-digits)
    try:
        d = Decimal(repr(x) if isinstance(x, float) else str(x)).quantize(q, rounding=rounding)
    except InvalidOperation:
        return x
    return num(float(d)) if (digits > 0 or d != d.to_integral_value()) else int(d)


def to_int64(v, cult=None):
    n = to_number(v, cult, '整数')
    if n is None:
        return None
    if isinstance(n, float):
        if math.isnan(n) or math.isinf(n):
            raise MError('整数に変換できない数です。', 'DataFormat.Error', n)
        return int(round_number(n, 0, 4))
    return n


# ---- 日付・時刻 ------------------------------------------------------------------
_EPOCH = date(1899, 12, 30)        # Excel・Power Query の日付の通し番号の起点


def serial_from_datetime(v):
    return (v.date() - _EPOCH).days + (v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6) / 86400


def datetime_from_serial(n):
    days = math.floor(n)
    frac = n - days
    us = round(frac * 86400 * 1e6)
    return datetime.combine(_EPOCH + timedelta(days=days), time()) + timedelta(microseconds=us)


_DATE_PATTERNS = (
    # 年が先（ISO・日本の書き方）
    (re.compile(r'^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})'), 'ymd'),
    (re.compile(r'^(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日'), 'ymd'),
    (re.compile(r'^(\d{4})(\d{2})(\d{2})(?=$|[T\s])'), 'ymd'),
    # 年が後ろ（並びは文化圏しだい）
    (re.compile(r'^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})'), 'xxy'),
)
_TIME_RE = re.compile(r'(?:^|[T\s])(午前|午後|AM|PM|am|pm)?\s*(\d{1,2})[:時](\d{1,2})(?:[:分](\d{1,2})(?:秒)?(?:[.,](\d{1,7}))?)?'
                      r'\s*(午前|午後|AM|PM|am|pm|a\.m\.|p\.m\.)?')
_MONTH_WORDS = {}
for _c in CULTURES.values():
    for _i, _m in enumerate(_c['months']):
        _MONTH_WORDS[_m.lower()] = _i + 1
    for _i, _m in enumerate(_c['months_abbr']):
        _MONTH_WORDS[_m.lower().rstrip('.')] = _i + 1


def _parse_date_part(s, cult):
    c = culture(cult)
    for rx, order in _DATE_PATTERNS:
        m = rx.match(s)
        if m:
            a, b, y = (int(x) for x in m.groups())
            if order == 'ymd':
                y, mo, d = a, b, y
            elif c['order'] == 'mdy':
                mo, d = a, b
            else:
                d, mo = a, b
            return date(y, mo, d), s[m.end():]
    # 年と月だけ（2024年10月・2024/10・2024-10）は、その月の1日（.NET の ja-JP と同じ読み方）
    m = re.match(r'^(\d{4})年\s*(\d{1,2})月(?!\s*\d)', s) or re.match(r'^(\d{4})[/\-.](\d{1,2})(?=$|\s)', s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1), s[m.end():]
    # 2桁の年（24/10/01）。年が先の文化圏だけ。29 までは 2000 年代（.NET の既定の区切り）
    if c['order'] == 'ymd':
        m = re.match(r'^(\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})(?=$|[T\s])', s)
        if m:
            yy = int(m.group(1))
            return date(2000 + yy if yy <= 29 else 1900 + yy, int(m.group(2)), int(m.group(3))), s[m.end():]
    # 月と日だけ（10月1日）は今年
    m = re.match(r'^(\d{1,2})月\s*(\d{1,2})日', s)
    if m:
        return date(date.today().year, int(m.group(1)), int(m.group(2))), s[m.end():]
    # 1 January 2024 / January 1, 2024 / Jan 1 2024
    m = re.match(r'^(\d{1,2})\.?\s+([A-Za-zÀ-ÿ]+)\.?\s+(\d{4})', s)
    if m and m.group(2).lower() in _MONTH_WORDS:
        return date(int(m.group(3)), _MONTH_WORDS[m.group(2).lower()], int(m.group(1))), s[m.end():]
    m = re.match(r'^([A-Za-zÀ-ÿ]+)\.?\s+(\d{1,2}),?\s+(\d{4})', s)
    if m and m.group(1).lower() in _MONTH_WORDS:
        return date(int(m.group(3)), _MONTH_WORDS[m.group(1).lower()], int(m.group(2))), s[m.end():]
    return None, s


def _parse_time_part(s):
    m = _TIME_RE.search(s)
    if not m:
        return None
    ap = m.group(1) or m.group(6)
    h, mi = int(m.group(2)), int(m.group(3))
    se = int(m.group(4) or 0)
    frac = m.group(5) or ''
    us = int((frac + '000000')[:6]) if frac else 0
    if ap:
        pm = ap.lower().startswith('p') or ap == '午後'
        if pm and h < 12:
            h += 12
        if not pm and h == 12:
            h = 0
    return time(h, mi, se, us)


def parse_datetime_text(text, cult=None, want='datetime'):
    """文字 → 日付・日時・時刻。読めなければ None。"""
    s = unicodedata.normalize('NFKC', str(text)).strip()
    if not s:
        return None
    try:
        d, rest = _parse_date_part(s, cult)
        if want == 'time':
            t = _parse_time_part(s)
            return t
        if d is None:
            return None
        if want == 'date':
            return d
        t = _parse_time_part(rest) if rest.strip() else None
        return datetime.combine(d, t or time())
    except ValueError:
        return None


def to_date(v, cult=None):
    v = force(v)
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if is_number(v):
        return datetime_from_serial(v).date()
    if isinstance(v, str):
        got = parse_datetime_text(v, cult, 'date')
        if got is None:
            raise MError(f'「{v}」を日付に変換できませんでした。', 'DataFormat.Error', v)
        return got
    raise MError(f'{type_name(v)} を日付に変換できません。')


def to_datetime(v, cult=None):
    v = force(v)
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, date):
        return datetime.combine(v, time())
    if is_number(v):
        return datetime_from_serial(v)
    if isinstance(v, time):
        return datetime.combine(_EPOCH, v)
    if isinstance(v, str):
        got = parse_datetime_text(v, cult, 'datetime')
        if got is None:
            raise MError(f'「{v}」を日時に変換できませんでした。', 'DataFormat.Error', v)
        return got
    raise MError(f'{type_name(v)} を日時に変換できません。')


def to_time(v, cult=None):
    v = force(v)
    if v is None:
        return None
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.time()
    if is_number(v):
        return datetime_from_serial(v % 1 if v >= 0 else v).time()
    if isinstance(v, str):
        got = parse_datetime_text(v, cult, 'time')
        if got is None:
            raise MError(f'「{v}」を時刻に変換できませんでした。', 'DataFormat.Error', v)
        return got
    raise MError(f'{type_name(v)} を時刻に変換できません。')


def to_duration(v, cult=None):
    v = force(v)
    if v is None:
        return None
    if isinstance(v, timedelta):
        return v
    if is_number(v):
        return timedelta(days=v)
    if isinstance(v, str):
        m = re.fullmatch(r'\s*(-)?(?:(\d+)\.)?(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.(\d+))?)?\s*', v)
        if m:
            sign = -1 if m.group(1) else 1
            d = timedelta(days=int(m.group(2) or 0), hours=int(m.group(3)), minutes=int(m.group(4)),
                          seconds=int(m.group(5) or 0), microseconds=int(((m.group(6) or '') + '000000')[:6]))
            return d * sign
        raise MError(f'「{v}」を期間に変換できませんでした。', 'DataFormat.Error', v)
    raise MError(f'{type_name(v)} を期間に変換できません。')


def to_logical(v, cult=None):
    v = force(v)
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if is_number(v):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ('true', 'yes'):
            return True
        if s in ('false', 'no'):
            return False
        raise MError(f'「{v}」を true／false に変換できませんでした。', 'DataFormat.Error', v)
    raise MError(f'{type_name(v)} を true／false に変換できません。')


# ---- 書式（.NET の書き方）--------------------------------------------------------
_DT_TOKEN = re.compile(r"yyyy|yyy|yy|y|MMMM|MMM|MM|M|dddd|ddd|dd|d|HH|H|hh|h|mm|m|ss|s|fffffff|ffffff|fffff|ffff|fff|ff|f|"
                       r"FFF|FF|F|tt|t|gg|g|zzz|zz|z|K|'[^']*'|\"[^\"]*\"|\\.|.", re.S)


def format_datetime(v, fmt=None, cult=None):
    """日付・日時・時刻を文字にする。書式が無ければ文化圏の既定（ja-JP: 2024/01/05・9:03:00）。"""
    c = culture(cult)
    if fmt is None or fmt == '':
        if isinstance(v, datetime):
            fmt = c['d'] + ' ' + c['T']
        elif isinstance(v, date):
            fmt = c['d']
        else:
            fmt = c['T']
    if len(fmt) == 1:
        std = {'d': c['d'], 'D': c['D'], 't': c['t'], 'T': c['T'], 'g': c['d'] + ' ' + c['t'],
               'G': c['d'] + ' ' + c['T'], 'f': c['D'] + ' ' + c['t'], 'F': c['D'] + ' ' + c['T'],
               'M': c['M'], 'm': c['M'], 'Y': c['Y'], 'y': c['Y'], 's': "yyyy'-'MM'-'dd'T'HH':'mm':'ss",
               'u': "yyyy'-'MM'-'dd HH':'mm':'ss'Z'", 'o': "yyyy'-'MM'-'dd'T'HH':'mm':'ss'.'fffffff",
               'O': "yyyy'-'MM'-'dd'T'HH':'mm':'ss'.'fffffff"}
        if fmt in std:
            fmt = std[fmt]
    if isinstance(v, datetime):
        d, t = v.date(), v.time()
    elif isinstance(v, date):
        d, t = v, time()
    else:
        d, t = date(1, 1, 1), v
    out = []
    for tok in _DT_TOKEN.findall(fmt):
        if tok in ('yyyy', 'yyy'):
            out.append(f'{d.year:04d}')
        elif tok == 'yy':
            out.append(f'{d.year % 100:02d}')
        elif tok == 'y':
            out.append(str(d.year % 100))
        elif tok == 'MMMM':
            out.append(c['months'][d.month - 1])
        elif tok == 'MMM':
            out.append(c['months_abbr'][d.month - 1])
        elif tok == 'MM':
            out.append(f'{d.month:02d}')
        elif tok == 'M':
            out.append(str(d.month))
        elif tok == 'dddd':
            out.append(c['days'][d.weekday()])
        elif tok == 'ddd':
            out.append(c['days_abbr'][d.weekday()])
        elif tok == 'dd':
            out.append(f'{d.day:02d}')
        elif tok == 'd':
            out.append(str(d.day))
        elif tok == 'HH':
            out.append(f'{t.hour:02d}')
        elif tok == 'H':
            out.append(str(t.hour))
        elif tok == 'hh':
            out.append(f'{(t.hour % 12) or 12:02d}')
        elif tok == 'h':
            out.append(str((t.hour % 12) or 12))
        elif tok == 'mm':
            out.append(f'{t.minute:02d}')
        elif tok == 'm':
            out.append(str(t.minute))
        elif tok == 'ss':
            out.append(f'{t.second:02d}')
        elif tok == 's':
            out.append(str(t.second))
        elif tok[0] in 'fF':
            digits = f'{t.microsecond:06d}0'[:len(tok)]
            out.append(digits.rstrip('0') if tok[0] == 'F' else digits)
        elif tok == 'tt':
            out.append(c['pm'] if t.hour >= 12 else c['am'])
        elif tok == 't':
            out.append((c['pm'] if t.hour >= 12 else c['am'])[:1])
        elif tok in ('gg', 'g'):
            out.append('西暦' if culture(cult) is CULTURES['ja-JP'] else 'A.D.')
        elif tok in ('zzz', 'zz', 'z', 'K'):
            off = v.utcoffset() if isinstance(v, datetime) and v.tzinfo else None
            if off is not None:
                mins = int(off.total_seconds() // 60)
                sign = '+' if mins >= 0 else '-'
                mins = abs(mins)
                out.append(f'{sign}{mins // 60:02d}:{mins % 60:02d}' if tok in ('zzz', 'K') else f'{sign}{mins // 60:02d}')
        elif tok[0] in "'\"" and len(tok) >= 2:
            out.append(tok[1:-1])
        elif tok[0] == '\\' and len(tok) == 2:
            out.append(tok[1])
        elif tok == '/':
            out.append('/')
        else:
            out.append(tok)
    return ''.join(out)


def _group(int_text, sep):
    s = int_text
    parts = []
    while len(s) > 3:
        parts.append(s[-3:])
        s = s[:-3]
    parts.append(s)
    return sep.join(reversed(parts))


def _fixed(x, digits):
    q = Decimal(1).scaleb(-digits) if digits > 0 else Decimal(1)
    d = Decimal(repr(float(x)) if isinstance(x, float) else str(x)).quantize(q, rounding=ROUND_HALF_UP)
    return format(d, 'f')


def format_number(x, fmt=None, cult=None):
    """数を文字にする。書式が無ければ素の形（1・0.5・1E-05）。N2・F0・P1・D3・0.00・#,##0 などを読む。"""
    c = culture(cult)
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return 'NaN' if math.isnan(x) else ('∞' if x > 0 else '-∞')
    if not fmt:
        return plain_number(x, c)
    m = re.fullmatch(r'([CcDdEeFfGgNnPpRrXx])(\d{0,2})', fmt)
    if m:
        kind, prec = m.group(1).upper(), m.group(2)
        p = int(prec) if prec else None
        if kind == 'D':
            n = int(x)
            s = str(abs(n)).rjust(p or 1, '0')
            return ('-' if n < 0 else '') + s
        if kind == 'X':
            s = format(int(x), 'x' if m.group(1) == 'x' else 'X')
            return s.rjust(p or 1, '0')
        if kind in ('F', 'N', 'C', 'P'):
            v = x * 100 if kind == 'P' else x
            digits = 2 if p is None else p
            s = _fixed(abs(v), digits)
            ip, _, fp = s.partition('.')
            if kind in ('N', 'C', 'P'):
                ip = _group(ip, c['grp'])
            body = ip + ((c['dec'] + fp) if fp else '')
            neg = v < 0 and any(ch not in '0.' for ch in s)
            if kind == 'P':
                body += '%'
            if kind == 'C':
                body = c['cur'] + body
            return ('-' if neg else '') + body
        if kind == 'E':
            digits = 6 if p is None else p
            s = f'{x:.{digits}E}'
            mant, _, exp = s.partition('E')
            return mant.replace('.', c['dec']) + 'E' + exp[0] + exp[1:].rjust(3, '0')
        return plain_number(x, c)
    return _custom_number(x, fmt, c)


def plain_number(x, c=None):
    c = c or culture()
    if isinstance(x, bool):
        return 'TRUE' if x else 'FALSE'
    if isinstance(x, int):
        return str(x)
    r = repr(x)
    if 'e' in r or 'E' in r:
        mant, _, exp = r.upper().partition('E')
        sign = exp[0] if exp[0] in '+-' else '+'
        digits = exp.lstrip('+-').lstrip('0') or '0'
        r = f'{mant}E{sign}{digits.rjust(2, "0")}'
    elif r.endswith('.0'):
        r = r[:-2]
    return r.replace('.', c['dec']) if c['dec'] != '.' else r


def _custom_number(x, fmt, c):
    sections = _split_sections(fmt)
    if len(sections) >= 2 and x < 0:
        fmt, x = sections[1], -x
    elif len(sections) >= 3 and x == 0:
        fmt = sections[2]
    else:
        fmt = sections[0]
    lit = []

    def keep(m):
        lit.append(m.group(0)[1:-1] if m.group(0)[0] in "'\"" else m.group(0)[1:])
        return '\x00'
    core = re.sub(r"'[^']*'|\"[^\"]*\"|\\.", keep, fmt)
    pct = core.count('%')
    v = x * (100 ** pct)
    if '‰' in core:
        v *= 1000
    m = re.search(r'[0#][0#,]*(?:\.[0#]*)?|\.[0#]+', core)
    if not m:
        out = core
    else:
        spec = m.group(0)
        ip, _, fp = spec.partition('.')
        grouping = ',' in ip.strip(',')
        scale_commas = len(ip) - len(ip.rstrip(','))
        v = v / (1000 ** scale_commas)
        ip = ip.replace(',', '')
        min_int = ip.count('0')
        min_frac, max_frac = fp.count('0'), len(fp)
        s = _fixed(abs(v), max_frac)
        a, _, b = s.partition('.')
        b = b.rstrip('0')
        if len(b) < min_frac:
            b = b + '0' * (min_frac - len(b))
        a = a.lstrip('0')
        a = a.rjust(min_int, '0') if min_int else a
        if grouping and a:
            a = _group(a, c['grp'])
        body = a + ((c['dec'] + b) if b else '')
        if not body:
            body = '0' if not min_int and not b else body
        neg = v < 0 and (a.strip('0' + c['grp']) or b.strip('0')) and len(sections) < 2
        out = core[:m.start()] + ('-' if neg else '') + body + core[m.end():]
    it = iter(lit)
    return re.sub('\x00', lambda _m: next(it), out)


def _split_sections(fmt):
    out, cur, q = [], [], None
    i = 0
    while i < len(fmt):
        ch = fmt[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            cur.append(ch)
        elif ch == '\\' and i + 1 < len(fmt):
            cur.append(fmt[i:i + 2])
            i += 1
        elif ch == ';':
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append(''.join(cur))
    return out


def format_duration(d):
    total = d.total_seconds()
    sign = '-' if total < 0 else ''
    d = abs(d)
    days = d.days
    secs = d.seconds
    h, rem = divmod(secs, 3600)
    mi, se = divmod(rem, 60)
    frac = f'.{d.microseconds:06d}0' if d.microseconds else ''
    return f'{sign}{days}.{h:02d}:{mi:02d}:{se:02d}{frac}' if days else f'{sign}{h:02d}:{mi:02d}:{se:02d}{frac}'


def to_text(v, fmt=None, cult=None):
    """Text.From。null は null のまま。"""
    v = force(v)
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if is_number(v):
        return format_number(v, fmt, cult)
    if isinstance(v, (date, time)):
        return format_datetime(v, fmt, cult)
    if isinstance(v, timedelta):
        return format_duration(v)
    if getattr(v, 'is_binary', False):
        import base64
        return base64.b64encode(v.data()).decode('ascii')
    raise MError(f'{type_name(v)} を文字に変換できません。', 'Expression.Error')


# ---- 型への変換（Table.TransformColumnTypes など）-------------------------------
def converter(t, cult=None):
    """型 → 値を変換する関数。失敗は MError（呼ぶ側がセルの誤りにする）。"""
    if not isinstance(t, MType):
        raise MError('型が要るところに型ではない値があります。')
    k, facet = t.kind, t.facet
    if k == 'text':
        return lambda v: to_text(v, None, cult)
    if k == 'number':
        if facet in ('Int64', 'Int32', 'Int16', 'Int8', 'Byte'):
            return lambda v: to_int64(v, cult)
        if facet == 'Currency':
            return lambda v: None if (n := to_number(v, cult)) is None else round_number(n, 4, 4)
        if facet == 'Percentage':
            return lambda v: to_number(v, cult)
        return lambda v: to_number(v, cult)
    if k == 'date':
        return lambda v: to_date(v, cult)
    if k in ('datetime', 'datetimezone'):
        return lambda v: to_datetime(v, cult)
    if k == 'time':
        return lambda v: to_time(v, cult)
    if k == 'duration':
        return lambda v: to_duration(v, cult)
    if k == 'logical':
        return lambda v: to_logical(v, cult)
    if k in ('any', 'anynonnull', 'null', 'none'):
        return lambda v: force(v)

    def check(v):
        v = force(v)
        if v is not None and type_name(v) != k:
            raise MError(f'{type_name(v)} を {k} に変換できません。')
        return v
    return check


def cell_text(v):
    """表のセルを、ファイルへ書く文字にする（日付は 2024-01-05、日時は 2024-01-05 09:03:00）。"""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ''
        s = f'{v:.15g}'
        if 'e' in s:
            s = repr(v)
        return s
    if isinstance(v, datetime):
        base = v.strftime('%Y-%m-%d %H:%M:%S')
        return base
    if isinstance(v, date):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, time):
        return v.strftime('%H:%M:%S')
    if isinstance(v, timedelta):
        return format_duration(v)
    if isinstance(v, str):
        return v
    return type_name(v).capitalize()
