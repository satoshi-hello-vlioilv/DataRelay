"""後処理（2.6.0）: 取り出した表を、変換して出す前に Power Query の M の式で整える取り決め。

どの入力（RNE・固定長テキスト・結合・Power Query）でも、取り出した表は最後に中間データになって finish_one_job を通る。
その入口で、この取り決めの式を当ててから変換・公開へ渡す（Excel でいえば、読み込んだ表にもう1本クエリを重ねる）。

作り方は2つ。どちらも最後は M の式で、評価は navi_m（言語）・navi_mrun（表の出し入れ）が受け持つ。
  steps … 手順を選んで組む（ピボット解除・ピボット・グループ化・列の選択・名前の変更・並べ替え・M の式）。
          compile() が Power Query と同じ関数（Table.UnpivotOtherColumns・Table.Pivot など）の式に直す。
  query … 保存したクエリ（共通設定 → Power Query）を使う。式は取り出した表を INPUT_NAME（取り出した表）で受け取る。

ここは本体（app）を読まない。形を整える・式に直す・言葉にする、だけを持つ（試験で単独に確かめられるように）。
"""
from navi_m import INPUT_NAME

MODES = ('steps', 'query')
MAX_STEPS = 30
MAX_NAMES = 200               # 1つの手順で選べる列の数の上限（貼り間違いで何万列も入れないため）
MAX_EXPR = 20_000             # M の式の手順1つの上限（文字数）

# 手順の種類。並びは画面の「手順を足す」の並び（よく使う順）。step は Power Query が付けるステップ名（日本語版）。
OPS = {
    'unpivot': {'label': 'ピボット解除', 'step': 'ピボット解除された列',
                'help': '横に並んだ列（1月・2月…）を、「属性」「値」の2列の縦持ちにします'},
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
