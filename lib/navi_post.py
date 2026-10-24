"""後処理（2.6.0）: 取り出した表を、変換して出す前に Power Query の M の式で整える取り決め。

どの入力（RNE・固定長テキスト・結合・Power Query）でも、取り出した表は最後に中間データになって finish_one_job を通る。
その入口で、この取り決めの式を当ててから変換・公開へ渡す（Excel でいえば、読み込んだ表にもう1本クエリを重ねる）。

作り方は2つ。どちらも最後は M の式で、評価は navi_m（言語）・navi_mrun（表の出し入れ）が受け持つ。
  steps … 手順を選んで組む（ピボット解除・繰り返し列の展開・ピボット・グループ化・列の選択・名前の変更・並べ替え・M の式）。
          compile() が Power Query と同じ関数（Table.UnpivotOtherColumns・Table.Pivot など）の式に直す。
  query … 保存したクエリ（共通設定 → Power Query）を使う。式は取り出した表を INPUT_NAME（取り出した表）で受け取る。

ここは本体（app）を読まない。形を整える・式に直す・言葉にする、だけを持つ（試験で単独に確かめられるように）。
"""
import re

from navi_m import INPUT_NAME

MODES = ('steps', 'query')
MAX_STEPS = 30
MAX_NAMES = 200               # 1つの手順で選べる列の数の上限（貼り間違いで何万列も入れないため）
MAX_EXPR = 20_000             # M の式の手順1つの上限（文字数）
MAX_REPEATS = 500             # 繰り返し列の展開で、1行を何回分に分けるかの上限

# 手順の種類。並びは画面の「手順を足す」の並び（よく使う順）。step は Power Query が付けるステップ名（日本語版）。
OPS = {
    'unpivot': {'label': 'ピボット解除', 'step': 'ピボット解除された列',
                'help': '横に並んだ列（1月・2月…）を、「属性」「値」の2列の縦持ちにします'},
    'repeat': {'label': '繰り返し列の展開', 'step': '展開された繰り返し列',
               'help': '番号付きで横に繰り返す列（品名1・数量1・品名2・数量2…）を、番号を除いた名前の列にまとめ、繰り返しごとの行にします'},
    'pivot': {'label': 'ピボット', 'step': 'ピボットされた列',
              'help': '1つの列の値（1月・2月…）を見出しにして横に並べ、値の列を集計します'},
    'group': {'label': 'グループ化', 'step': 'グループ化された行',
              'help': 'キーの列ごとに行をまとめ、合計・件数などを出します'},
    'select': {'label': '他の列の削除', 'step': '削除された他の列',
               'help': '選んだ列だけを、選んだ順に残します'},
    'remove': {'label': '列の削除', 'step': '削除された列',
               'help': '選んだ列を消します'},
    'rename': {'label': '名前の変更', 'step': '名前が変更された列',
               'help': '列の名前を変えます'},
    'sort': {'label': '並べ替え', 'step': '並べ替えられた行',
             'help': '列の値で行を並べ替えます'},
    'm': {'label': 'M の式', 'step': 'カスタム',
          'help': '1つ前の表を「前」で受け取り、M の式で整えます（例: Table.SelectRows(前, each [数量] > 0)）'},
}

# 集計の仕方。num: 数として集める（文字の列を数に直してから集める）。
AGGS = {
    'sum': {'label': '合計', 'list': 'List.Sum', 'num': True},
    'count': {'label': '件数', 'list': 'List.Count', 'num': False},
    'average': {'label': '平均', 'list': 'List.Average', 'num': True},
    'min': {'label': '最小', 'list': 'List.Min', 'num': True},
    'max': {'label': '最大', 'list': 'List.Max', 'num': True},
    'first': {'label': '最初の値', 'list': 'List.First', 'num': False},
    'none': {'label': '集計しない', 'list': '', 'num': False},
}
GROUP_AGGS = ('count', 'sum', 'average', 'min', 'max', 'count_distinct')
GROUP_AGG_LABEL = {'count': '件数', 'sum': '合計', 'average': '平均', 'min': '最小', 'max': '最大',
                   'count_distinct': '個別の件数'}


def _text(v, limit=200):
    return str(v if v is not None else '').strip()[:limit]


def _names(v):
    out = []
    for x in (v if isinstance(v, (list, tuple)) else []):
        n = _text(x)
        if n and n not in out:
            out.append(n)
    return out[:MAX_NAMES]


# ---- 取り決めの形 ------------------------------------------------------------------
def normalize_step(s):
    s = dict(s or {})
    op = _text(s.get('op'))
    if op not in OPS:
        return None
    if op == 'unpivot':
        mode = 'selected' if s.get('mode') == 'selected' else 'other'
        return {'op': op, 'mode': mode, 'columns': _names(s.get('columns')),
                'attr': _text(s.get('attr')) or '属性', 'value': _text(s.get('value')) or '値'}
    if op == 'repeat':
        return _normalize_repeat(s)
    if op == 'pivot':
        agg = _text(s.get('agg'))
        return {'op': op, 'column': _text(s.get('column')), 'value': _text(s.get('value')),
                'agg': agg if agg in AGGS else 'sum'}
    if op == 'group':
        aggs = []
        for a in (s.get('aggs') if isinstance(s.get('aggs'), list) else [])[:MAX_NAMES]:
            a = dict(a or {})
            fn = _text(a.get('func'))
            fn = fn if fn in GROUP_AGGS else 'count'
            col = '' if fn == 'count' else _text(a.get('column'))
            aggs.append({'func': fn, 'column': col,
                         'name': _text(a.get('name')) or (GROUP_AGG_LABEL[fn] if fn == 'count' else f'{col}の{GROUP_AGG_LABEL[fn]}')})
        return {'op': op, 'keys': _names(s.get('keys')), 'aggs': aggs or [{'func': 'count', 'column': '', 'name': '件数'}]}
    if op in ('select', 'remove'):
        return {'op': op, 'columns': _names(s.get('columns'))}
    if op == 'rename':
        pairs = []
        for p in (s.get('pairs') if isinstance(s.get('pairs'), list) else [])[:MAX_NAMES]:
            if isinstance(p, (list, tuple)) and len(p) == 2 and _text(p[0]) and _text(p[1]):
                pairs.append([_text(p[0]), _text(p[1])])
        return {'op': op, 'pairs': pairs}
    if op == 'sort':
        keys = []
        for p in (s.get('keys') if isinstance(s.get('keys'), list) else [])[:MAX_NAMES]:
            if isinstance(p, (list, tuple)) and p and _text(p[0]):
                keys.append([_text(p[0]), 'desc' if len(p) > 1 and p[1] == 'desc' else 'asc'])
        return {'op': op, 'keys': keys}
    return {'op': op, 'expr': str(s.get('expr') or '').replace('\r\n', '\n')[:MAX_EXPR]}


def normalize(d):
    """対象の post（後処理）の欄を整える。使っていなければ {}（持ち出し・保存で欄を増やさない）。"""
    d = d if isinstance(d, dict) else {}
    steps = [x for x in (normalize_step(s) for s in (d.get('steps') if isinstance(d.get('steps'), list) else [])[:MAX_STEPS]) if x]
    mode = d.get('mode') if d.get('mode') in MODES else 'steps'
    out = {'enabled': bool(d.get('enabled')), 'mode': mode, 'steps': steps,
           'query_id': _text(d.get('query_id')), 'query_out': _text(d.get('query_out'))}
    if not out['enabled'] and not steps and not out['query_id']:
        return {}
    return out


def active(job):
    """この対象に後処理が掛かるか（入っていて、中身がある）。"""
    p = normalize((job or {}).get('post'))
    if not p.get('enabled'):
        return False
    return bool(p['steps']) if p['mode'] == 'steps' else bool(p['query_id'])


# ---- 式に直す ----------------------------------------------------------------------
def m_text(s):
    return '"' + str(s).replace('"', '""') + '"'


def m_name(s):
    """ステップ名・列名を M の名前に（Power Query と同じく、いつも #"…" で書く）。"""
    return '#' + m_text(s)


_KEYWORDS = {'and', 'as', 'each', 'else', 'error', 'false', 'if', 'in', 'is', 'let', 'meta', 'not', 'null', 'or', 'otherwise',
             'section', 'shared', 'then', 'true', 'try', 'type'}


def m_ref(name):
    """ステップを指す名前。そのまま書ける名前（ソース など）は囲まず、記号や空白を含む名前は #"…" で書く（Power Query と同じ）。"""
    simple = name and all(ch.isalnum() or ch == '_' for ch in name) and not name[0].isdigit() and name not in _KEYWORDS
    return name if simple else m_name(name)


def m_list(names):
    return '{' + ', '.join(m_text(n) for n in names) + '}'


def _to_number(prev, cols):
    return f'Table.TransformColumnTypes({prev}, {{{", ".join("{" + m_text(c) + ", type number}" for c in cols)}}})'


def step_problems(s, n):
    """手順1つの足りないところ（画面と保存で同じ言葉を出す）。n は何番目か（1から）。"""
    head = f'{n}番目（{OPS[s["op"]]["label"]}）: '
    op = s['op']
    if op == 'unpivot' and not s['columns']:
        return [head + ('解除する列' if s['mode'] == 'selected' else '残す列（キー）') + 'を選んでください']
    if op == 'pivot':
        bad = []
        if not s['column']:
            bad.append(head + '見出しにする列を選んでください')
        if not s['value']:
            bad.append(head + '値の列を選んでください')
        if s['column'] and s['column'] == s['value']:
            bad.append(head + '見出しにする列と値の列は、別の列を選んでください')
        return bad
    if op == 'group':
        bad = [] if s['keys'] else [head + 'まとめるキーの列を選んでください']
        bad += [head + f'「{a["name"]}」の元の列を選んでください' for a in s['aggs'] if a['func'] != 'count' and not a['column']]
        names = s['keys'] + [a['name'] for a in s['aggs']]
        dup = sorted({x for x in names if names.count(x) > 1})
        if dup:
            bad.append(head + f'列の名前が重なっています（{"・".join(dup)}）')
        return bad
    if op in ('select', 'remove') and not s['columns']:
        return [head + ('残す列' if op == 'select' else '消す列') + 'を選んでください']
    if op == 'rename' and not s['pairs']:
        return [head + '変える列と新しい名前を入れてください']
    if op == 'sort' and not s['keys']:
        return [head + '並べ替える列を選んでください']
    if op == 'repeat':
        return repeat_problems(s, head=head)
    if op == 'm' and not s['expr'].strip():
        return [head + '式を入れてください']
    return []


def problems(post, query_exists=None):
    """保存してよいか（駄目な理由の一覧）。入っていない取り決めは問わない。query_exists(id) でクエリがあるかを聞く。"""
    p = normalize(post)
    if not p.get('enabled'):
        return []
    if p['mode'] == 'query':
        if not p['query_id']:
            return ['後処理: クエリを選んでください']
        if query_exists and not query_exists(p['query_id']):
            return ['後処理: 選んだクエリがありません（削除されています）。選び直してください']
        return []
    if not p['steps']:
        return ['後処理: 手順を1つ以上足してください（使わないなら「後処理をしない」にします）']
    out = []
    for n, s in enumerate(p['steps'], 1):
        out += step_problems(s, n)
    return out


def _field(name):
    """[列名] の中の名前。英数字・空白・_ だけならそのまま、記号を含むときは #"…" で書く。"""
    simple = all(ch.isalnum() or ch in '_ ' for ch in name) and not name[:1].isdigit() and name.strip() == name
    return name if simple else m_name(name)


def _step_builders(s):
    """手順1つ → [(ステップ名の元, 式を作る関数(1つ前のステップを指す名前) )]。

    数として集める列は、Power Query と同じく先に「変更された型」のステップを挟む（取り出した表は文字なので）。"""
    op, base = s['op'], OPS[s['op']]['step']
    if op == 'repeat':
        return _repeat_builders(s)
    if op == 'unpivot':
        fn = 'Table.Unpivot' if s['mode'] == 'selected' else 'Table.UnpivotOtherColumns'
        return [(base, lambda p: f'{fn}({p}, {m_list(s["columns"])}, {m_text(s["attr"])}, {m_text(s["value"])})')]
    if op == 'pivot':
        a = AGGS[s['agg']]
        tail = f', {a["list"]}' if a['list'] else ''
        # 見出しは出てきた値の順（Power Query の「ピボット列」と同じ List.Distinct）。見出しの列は先に文字にそろえ、
        # null は空の見出しにまとめる（数や日付の値も、列名になる文字で突き合わせる）
        col = m_text(s['column'])
        pivot = (base, lambda p: (f'let 見出し = Table.TransformColumns({p}, {{{{{col}, each if _ = null then "" else Text.From(_), type text}}}}) in\n'
                                  f'        Table.Pivot(見出し, List.Distinct(見出し[{_field(s["column"])}]), {col}, {m_text(s["value"])}{tail})'))
        return ([('変更された型', lambda p: _to_number(p, [s['value']]))] if a['num'] else []) + [pivot]
    if op == 'group':
        nums = list(dict.fromkeys(a['column'] for a in s['aggs'] if a['func'] in ('sum', 'average', 'min', 'max')))
        aggs = []
        for a in s['aggs']:
            f, name = a['func'], m_text(a['name'])
            if f == 'count':
                aggs.append(f'{{{name}, each Table.RowCount(_), Int64.Type}}')
            elif f == 'count_distinct':
                aggs.append(f'{{{name}, each List.Count(List.Distinct([{_field(a["column"])}])), Int64.Type}}')
            else:
                fn = {'sum': 'List.Sum', 'average': 'List.Average', 'min': 'List.Min', 'max': 'List.Max'}[f]
                # 型は付けない（整数だけなら整数、小数があれば小数として書く。navi_mrun.column_type が中身から決める）
                aggs.append(f'{{{name}, each {fn}([{_field(a["column"])}])}}')
        group = (base, lambda p: f'Table.Group({p}, {m_list(s["keys"])}, {{{", ".join(aggs)}}})')
        return ([('変更された型', lambda p: _to_number(p, nums))] if nums else []) + [group]
    if op == 'select':
        return [(base, lambda p: f'Table.SelectColumns({p}, {m_list(s["columns"])})')]
    if op == 'remove':
        return [(base, lambda p: f'Table.RemoveColumns({p}, {m_list(s["columns"])})')]
    if op == 'rename':
        pairs = ', '.join('{' + m_text(x) + ', ' + m_text(y) + '}' for x, y in s['pairs'])
        return [(base, lambda p: f'Table.RenameColumns({p}, {{{pairs}}})')]
    if op == 'sort':
        keys = ', '.join('{' + m_text(c) + ', ' + ('Order.Descending' if d == 'desc' else 'Order.Ascending') + '}'
                         for c, d in s['keys'])
        return [(base, lambda p: f'Table.Sort({p}, {{{keys}}})')]
    expr = s['expr'].strip()
    return [(base, lambda p: f'let 前 = {p} in\n        {expr}')]


def compile_steps(steps, source=INPUT_NAME):
    """手順の並び → (M の式, [(手順の番号 0〜, ステップ名)])。ステップ名は Power Query と同じく、重なったら「 1」「 2」を付ける。"""
    lines, made, used = [f'    ソース = {source}'], [], {'ソース'}
    ref = 'ソース'
    for i, s in enumerate(x for x in (normalize_step(y) for y in steps) if x):
        for base, build in _step_builders(s):
            name, k = base, 1
            while name in used:
                name = f'{base} {k}'
                k += 1
            used.add(name)
            lines.append(f'    {m_name(name)} = {build(ref)}')
            made.append((i, name))
            ref = m_name(name)
    return 'let\n' + ',\n'.join(lines) + '\nin\n    ' + ref, made


def compile(post):
    """取り決め → 評価する M の式。query のときは None（式はクエリの側にある）。"""
    p = normalize(post)
    if p.get('mode') != 'steps':
        return None
    return compile_steps(p['steps'])[0]


# ---- 言葉にする（一覧・結果・ログ）------------------------------------------------
def step_summary(s):
    op = s['op']
    if op == 'repeat':
        return repeat_summary(s)
    if op == 'unpivot':
        cols = '・'.join(s['columns'][:3]) + ('ほか' if len(s['columns']) > 3 else '')
        return (f'{cols} を縦に' if s['mode'] == 'selected' else f'{cols} 以外を縦に') + f'（{s["attr"]}・{s["value"]}）'
    if op == 'pivot':
        return f'{s["column"]} を見出しに・{s["value"]} の{AGGS[s["agg"]]["label"]}'
    if op == 'group':
        return '・'.join(s['keys'][:3]) + ' ごとに ' + '・'.join(a['name'] for a in s['aggs'][:3])
    if op == 'select':
        return f'{len(s["columns"])}列を残す'
    if op == 'remove':
        return '・'.join(s['columns'][:3]) + ('ほか' if len(s['columns']) > 3 else '') + ' を消す'
    if op == 'rename':
        return '・'.join(f'{a}→{b}' for a, b in s['pairs'][:2]) + ('ほか' if len(s['pairs']) > 2 else '')
    if op == 'sort':
        return '・'.join(f'{c}{"↓" if d == "desc" else "↑"}' for c, d in s['keys'][:3])
    return (s['expr'].strip().splitlines() or [''])[0][:40]


def summary(post, query_name=''):
    """一覧の行・実行結果に添える1行（例: 後処理 ピボット解除 → ピボット）。使っていなければ ''。"""
    p = normalize(post)
    if not p.get('enabled'):
        return ''
    if p['mode'] == 'query':
        return f'後処理 クエリ「{query_name or "（選ばれていません）"}」'
    return '後処理 ' + ' → '.join(OPS[s['op']]['label'] for s in p['steps'])


# ---- 既存の式に、手順を1つ足す（Power Query エディターの「変換」の札。2.6.0）--------------------------
def step_parts(s, used, ref):
    """手順1つ → [(ステップ名, 式)]。ステップ名は used（そのクエリのステップ名）と重ならないように「 1」「 2」を付ける。
    ref は1つ前のステップを指す名前（M の書き方）。足した名前は used に入れる。"""
    out = []
    for base, build in _step_builders(s):
        name, k = base, 1
        while name in used:
            name = f'{base} {k}'
            k += 1
        used.add(name)
        out.append((name, build(ref)))
        ref = m_name(name)
    return out


# ---- 繰り返し列の展開（2.7.0）------------------------------------------------------------
# 1行に、同じ並びの列が番号付きで繰り返し入っている表（品名1・数量1・品名2・数量2…）を、繰り返しごとの行に戻す。
#   groups  … 繰り返しごとの元の列 [[品名1, 数量1], [品名2, 数量2], …]。どの組も names と同じ長さで、無い列は None（空として出す）
#   numbers … 組ごとの番号（列名の番号。手で決めたときは 1, 2, …）。番号の列に入れ、元の行の中の順もこれで決める
#   names   … まとめた列の名前（列名から番号を除いた共通の名前）
#   index   … 番号を入れる列の名前。drop_empty … 値がすべて空の組は行にしない（枠だけ用意された空きの繰り返し）
# 繰り返しの列のほか（共通の列）は、すべてそのまま各行に写す。共通の列は式の中で求めるので、あとから列が増えても崩れない。
REPEAT_INDEX = '番号'
_RUN = re.compile(r'\d+')           # 列名の中の番号（全角の数字も \d に入り、int() で読める）
_MARK = '\0'                        # 型（番号を抜いた列名）の中で、番号のあった場所
_SEPS = ' 　_-－‐・.:：/／#＃'
_BRACKETS = ('()', '（）', '[]', '［］', '【】', '<>', '＜＞', '「」')


def _normalize_repeat(s):
    names = [_text(x) for x in (s.get('names') if isinstance(s.get('names'), list) else [])][:MAX_NAMES]
    raw = [g for g in (s.get('groups') if isinstance(s.get('groups'), list) else []) if isinstance(g, (list, tuple))][:MAX_REPEATS]
    width = len(names) or max((len(g) for g in raw), default=0)
    width = min(width, MAX_NAMES)
    groups = [[(_text(x) or None) for x in list(g)[:width]] + [None] * (width - len(g)) for g in raw]
    if not names:
        names = [''] * width
    nums = s.get('numbers') if isinstance(s.get('numbers'), list) else []
    try:
        nums = [int(x) for x in nums]
    except (TypeError, ValueError):
        nums = []
    if len(nums) != len(groups) or any(b <= a for a, b in zip(nums, nums[1:])):
        nums = list(range(1, len(groups) + 1))       # 番号は、組の並びの順に増える（行の中の順をこれで決めるため）
    return {'op': 'repeat', 'groups': groups, 'numbers': nums, 'names': names,
            'index': _text(s.get('index')) or REPEAT_INDEX, 'drop_empty': s.get('drop_empty') is not False}


def repeat_problems(s, columns=None, head=''):
    """繰り返し列の展開の足りないところ。columns（いまの表の列）が分かれば、無い列・共通の列との名前の重なりも見る。"""
    bad = []
    if len(s['groups']) < 2:
        bad.append(head + '繰り返しを2回分以上選んでください')
    if not s['names']:
        return bad + [head + 'まとめる列（1回分の列）を選んでください']
    if any(not n for n in s['names']):
        bad.append(head + 'まとめた列の名前を、すべて入れてください')
    used = [c for g in s['groups'] for c in g if c]
    dup = sorted({c for c in used if used.count(c) > 1})
    if dup:
        bad.append(head + f'同じ列が2回以上入っています（{"・".join(dup[:5])}）')
    if any(all(c is None for c in g) for g in s['groups']):
        bad.append(head + '列が1つも無い回があります')
    outs = s['names'] + [s['index']]
    same = sorted({n for n in outs if n and outs.count(n) > 1})
    if same:
        bad.append(head + f'まとめた列の名前が重なっています（{"・".join(same)}）')
    if any(n.startswith('__') for n in outs):
        bad.append(head + '「__」で始まる名前は使えません（中で使う列の名前です）')
    if columns is not None:
        have = set(columns)
        lost = [c for c in used if c not in have]
        if lost:
            bad.append(head + f'表に無い列があります（{"・".join(lost[:5])}{"ほか" if len(lost) > 5 else ""}）')
        common = have - set(used)
        clash = [n for n in outs if n in common]
        if clash:
            bad.append(head + f'共通の列と同じ名前です（{"・".join(clash)}）。まとめた列の名前を変えてください')
    return bad


def _repeat_builders(s):
    groups = ',\n                '.join('{' + ', '.join(m_text(c) if c else 'null' for c in g) + '}' for g in s['groups'])   # 1回分ずつ1行
    nums = '{' + ', '.join(str(n) for n in s['numbers']) + '}'
    idx = m_text(s['index'])
    keep = (f'\n            空を除く = Table.SelectRows(積む, each {" or ".join(f"[{_field(n)}] <> null" for n in s["names"])}),'
            if s['drop_empty'] else '\n            空を除く = 積む,')

    # 組ごとに「ほかの組の列を除く → 番号を除いた名前に変える → 番号を足す」を表のまま行い（1行ずつの関数より速い）、
    # 積んでから元の行の順・番号の順に並べ直す。共通の列は、元の表で最初の繰り返しの列より左のものを左に、ほかを右に置く
    def build(p):
        return (f'let\n            組 = {{\n                {groups}}},\n            番号の値 = {nums},\n            名前 = {m_list(s["names"])},\n'
                f'            全列 = List.RemoveNulls(List.Combine(組)),\n            列 = Table.ColumnNames({p}),\n'
                f'            行番号 = Table.AddIndexColumn({p}, "__行", 0, 1),\n'
                f'            各組 = List.Transform(List.Positions(組), (i) => Table.AddColumn(Table.RenameColumns('
                f'Table.RemoveColumns(行番号, List.RemoveItems(全列, 組{{i}})), List.Select(List.Zip({{組{{i}}, 名前}}), each _{{0}} <> null)), '
                f'{idx}, each 番号の値{{i}}, Int64.Type)),\n            積む = Table.Combine(各組),{keep}\n'
                f'            並べる = Table.Sort(空を除く, {{{{"__行", Order.Ascending}}, {{{idx}, Order.Ascending}}}}),\n'
                f'            左 = List.FirstN(列, each not List.Contains(全列, _))\n        in\n'
                f'            Table.SelectColumns(並べる, 左 & {{{idx}}} & 名前 & List.RemoveItems(列, 左 & 全列))')
    return [(OPS['repeat']['step'], build)]


def repeat_summary(s):
    names = '・'.join(s['names'][:3]) + ('ほか' if len(s['names']) > 3 else '')
    return f'{len(s["names"])}列×{len(s["groups"])}回 を行に（{names}）'


# ---- 繰り返しを見つける（列名から）・並びで決める ---------------------------------------
_UNITS = '回月日年期週号番次目件'       # 番号のすぐ後ろの単位（第1回・1月）は番号の一部として、番号の列の名前に回す


def _unbracket(t):
    """番号を囲む括弧を除く（品名(#) → 品名#）。"""
    for b in _BRACKETS:
        t = t.replace(b[0] + _MARK + b[1], _MARK)
    return t


def clean_name(t):
    """型（番号を抜いた列名）→ まとめた列の名前。番号の跡の空の括弧・区切りを除く（品名(1) → 品名、明細_1_品名 → 明細_品名）。"""
    a, _, z = _unbracket(t).partition(_MARK)
    a, z = a.rstrip(_SEPS), z.lstrip(_SEPS)
    joint = next((ch for ch in t.replace(_MARK, '') if ch in _SEPS), '_') if a and z else ''
    return (a + joint + z).strip(_SEPS) or t.replace(_MARK, '').strip() or '値'


def _names_for(templates):
    """型の並び → (まとめた列の名前, 番号の列の名前)。

    みな同じ前置き（明細1_品名 の「明細」）なら除いて短くし、番号の列を「明細番号」にする。番号のすぐ後ろの単位
    （2024年1月売上 の「月」）もみな同じなら、番号の一部として名前から除き、番号の列を「2024年月」にする。"""
    parts = [_unbracket(t).split(_MARK, 1) for t in templates]
    full = [clean_name(t) for t in templates]
    unit = parts[0][1][:1] if parts[0][1][:1] in _UNITS and len({p[1][:1] for p in parts}) == 1 else ''
    if unit:
        parts = [[a, z[1:]] for a, z in parts]
    head = parts[0][0] if len(parts) >= 2 and len({p[0] for p in parts}) == 1 else ''   # 1列だけの繰り返しは前置きが名前
    if head.strip(_SEPS) or unit:
        short = [clean_name((a if not head else '') + _MARK + z) for a, z in parts]
        if all(short) and len(set(short)) == len(short) and short != [''] * len(short):
            full = short
            base = head.strip(_SEPS)
            base = base[:-1] if base.endswith('第') else base
            return _distinct(full), (base + unit if unit else base + REPEAT_INDEX) or REPEAT_INDEX
    return _distinct(full), REPEAT_INDEX


def _distinct(names, taken=()):
    out, seen = [], set(taken)
    for n in names:
        m, k = n, 2
        while m in seen:
            m, k = f'{n}_{k}', k + 1
        seen.add(m)
        out.append(m)
    return out


def _finish(columns, groups, numbers, names, how, index=REPEAT_INDEX):
    """見つけた・決めた繰り返し → 画面に出す1案（手順の形＋説明）。"""
    used = {c for g in groups for c in g if c}
    common = [c for c in columns if c not in used]
    idx = _distinct([index], common)[0]
    names = _distinct(names, common + [idx])
    at = {c: i for i, c in enumerate(columns)}
    pos = sorted(at[c] for c in used)
    rank = {p: r for r, p in enumerate(pos)}           # 繰り返しの列の中で何番目か
    first = [c for c in groups[0] if c] if groups else []
    step = {'op': 'repeat', 'groups': groups, 'numbers': numbers, 'names': names, 'index': idx, 'drop_empty': True}
    # 1回分ずつ固まって並んでいるか（品番1〜備考1、品番2〜…）。列ごとの並び（品番1〜9、品名1〜9…）なら mixed
    block = bool(names) and len(pos) == len(groups) * len(names) and all(
        rank[at[c]] // len(names) == k for k, g in enumerate(groups) for c in g if c)
    return {'how': how, 'step': step, 'width': len(names), 'count': len(groups), 'columns': len(used),
            'missing': sum(1 for g in groups for c in g if not c), 'common': len(common),
            'first': pos[0] + 1 if pos else 0, 'last': pos[-1] + 1 if pos else 0,
            'layout': 'block' if block else 'mixed', 'sample': first[:4]}


def find_repeats(columns, limit=5):
    """列名から、番号付きで繰り返す列のまとまりを見つける。→ 覆う列の多い順の案（_finish の形）。

    列名の中の数字を1か所ずつ抜いて「型」にし（品名12 → 品名#）、2つ以上の番号を持つ型を、同じ番号の組を持つもの同士でまとめる。
    番号の一部が無い型（備考が 1〜8 だけ など）は、範囲の中にあれば同じまとまりに入れ、無い回は空にする。"""
    columns = [str(c) for c in columns]
    tpl = {}                                    # 型 → {番号: 列の位置}
    for ci, c in enumerate(columns):
        for m in _RUN.finditer(c):
            t = c[:m.start()] + _MARK + c[m.end():]
            tpl.setdefault(t, {}).setdefault(int(m.group()), ci)
    tpl = {t: v for t, v in tpl.items() if len(v) >= 2}
    by_set = {}
    for t, v in tpl.items():
        by_set.setdefault(frozenset(v), []).append(t)
    clusters = sorted(by_set.items(), key=lambda kv: (-len(kv[0]) * len(kv[1]), -len(kv[0])))
    out, taken = [], set()
    for nums, ts in clusters:
        if len(nums) * len(ts) < 2:
            continue
        span = [i for t in ts for i in tpl[t].values()]
        lo, hi = min(span), max(span)
        # 番号の欠けた型（ほかのまとまりで、番号がこのまとまりの一部で、列がこのまとまりの範囲の中にある）を足す
        extra = [t for n2, t2 in by_set.items() if n2 < nums and len(n2) * 2 >= len(nums) for t in t2
                 if all(lo <= i <= hi for i in tpl[t].values())]
        ts = sorted(set(ts) | set(extra), key=lambda t: min(tpl[t].values()))
        cols = {i for t in ts for i in tpl[t].values()}
        if cols & taken:                        # 同じ列を別の数字で読んだまとまり（2024年1月 の 2024 など）は、多く覆う方だけ
            ts = [t for t in ts if not set(tpl[t].values()) & taken]
            cols = {i for t in ts for i in tpl[t].values()}
            if len(ts) * len(nums) < 2 or not ts:
                continue
        taken |= cols
        order = sorted(nums)
        groups = [[columns[tpl[t][k]] if k in tpl[t] else None for t in ts] for k in order]
        names, index = _names_for(ts)
        out.append(_finish(columns, groups, order, names, 'auto', index))
        if len(out) >= limit:
            break
    return sorted(out, key=lambda c: -c['columns'])


def repeat_by_layout(columns, start, width, count):
    """並びで決める（手で）: start 列目（1から）から width 列ずつ count 回。名前は、回ごとに変わる番号を除いた共通の部分。"""
    columns = [str(c) for c in columns]
    start, width, count = int(start), int(width), int(count)
    if start < 1 or width < 1 or count < 1 or start - 1 + width * count > len(columns):
        raise ValueError(f'{start}列目から {width}列×{count}回 は、表の列（{len(columns)}列）を超えます')
    groups = [columns[start - 1 + k * width: start - 1 + (k + 1) * width] for k in range(count)]
    names, nums = [], None
    for j in range(width):
        col = [g[j] for g in groups]
        name = col[0]
        for m in _RUN.finditer(col[0]):
            t = col[0][:m.start()] + _MARK + col[0][m.end():]
            got = [_match_number(t, c) for c in col]
            if None not in got and len(set(got)) == count:
                name = clean_name(t)
                nums = nums or (got if all(b > a for a, b in zip(got, got[1:])) else None)
                break
        names.append(name)
    return _finish(columns, [list(g) for g in groups], nums or list(range(1, count + 1)), _distinct(names), 'layout')


def _match_number(t, c):
    a, z = t.split(_MARK, 1)
    if c.startswith(a) and c.endswith(z) and len(c) > len(a) + len(z):
        mid = c[len(a):len(c) - len(z)]
        if _RUN.fullmatch(mid):
            return int(mid)
    return None
