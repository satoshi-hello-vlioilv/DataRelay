"""条件の値ごとに分けて出す（2.1.0。取り方は 2.1.1 で作り直し）。

1つの対象（RNE）から、指定した値ごとに別のファイルを出す。例: BOX実績_設備名 に LS3・LS4・DL2・KEN → 4ファイル。
RNEファイルは書き換えない（開いたカタログの条件と表側のカテゴリだけを、API で変える）。

取り方は2つ（METHODS）。どちらも、RNE の条件欄の絞り込み（例: LS4 だけ）を外し、表側の同じ名前の管理ポイントを
指定の値だけに絞って問い合わせ、受け取ったCSVを手元で値ごとに振り分けてから出す（ほかの値の行は混ざらない）。
- combined（まとめて1回）: 指定の値を全部入れて1回だけ問い合わせ、受け取ってから値ごとに分ける
- parallel（値ごとに並列）: 値ごとに別のワーカーで問い合わせる（RNE を値の数に分けたのと同じ）。データが大きいと速いことがある
対象ごとに選べ、「既定に従う」なら共通設定の既定（settings.variant_method）を使う。

分ける値の決め方は2つ（SCOPES。2.5.0）。
- listed（指定した値だけ）: 値を並べて指定する。値の数だけファイルができる
- all（出てきた値すべて）: 値を指定しない。RNE の条件欄の絞り込みを外して1回だけ問い合わせ、返ってきた行に出てきた値の数だけ
  ファイルを作る。値は問い合わせるまで分からないので、取り方はいつも「まとめて1回」（値ごとに並列は、値を先に知っている必要がある）
いくつの値（＝ファイル）が出てくるかは、同じ問い合わせを1回して数えれば先に分かる（count_csv。ファイルは作らない）。
数えなくても設定して実行できる。

ここは決まりだけを持つ（設定の形・取り方・ファイル名と置き場の決め方・分け方・外せたかの確かめ）。DBも画面もAPIも
触らないので、実機なしで確かめられる。問い合わせそのものは app.process_api_parallel_job が行う。
"""
import csv
from pathlib import Path

# ファイル名・置き場に書く「その回の値」。{値} と {value} のどちらでも書ける
TOKENS = ('値', 'value')
MAX_VALUES = 50          # 1つの対象で分ける数の上限（打ち間違いで数百回問い合わせないように）
MAX_FOUND = 300          # 出てきた値すべてで作るファイルの上限（日時や番号のような項目を選んだとき、何千ものファイルを作らないように）
SCOPES = ('listed', 'all')             # 指定した値だけ / 出てきた値すべて
SCOPE_NAMES = {'listed': '指定した値だけ', 'all': '出てきた値すべて'}
METHODS = ('combined', 'parallel')     # まとめて1回 / 値ごとに並列
DEFAULT_METHOD = 'combined'            # 共通設定に何も無いときの既定（問い合わせが1回で済み、サーバーの負担が小さい）
METHOD_NAMES = {'combined': 'まとめて1回', 'parallel': '値ごとに並列', 'default': '既定に従う'}


def normalize(v):
    """画面・持ち込みから来た形を、保存する形にそろえる。
    → {'enabled', 'item'（条件欄の項目名）, 'scope'（'listed' 指定した値だけ・'all' 出てきた値すべて。知らない値は 'listed'）,
       'values'（重ねない・前後の空白を落とす。'all' では使わないが、切り替えて戻ったときのために残す）, 'pattern'（ファイル名の型。空なら対象の名前の決め方）,
       'folder'（置き場の型。空なら対象の出力先）, 'method'（'default'・'combined'・'parallel'。知らない値は 'default'）}"""
    v = v if isinstance(v, dict) else {}
    seen, values = set(), []
    for x in v.get('values') or []:
        s = '' if x is None else str(x).strip()
        if s and s not in seen:
            seen.add(s)
            values.append(s)
    return {'enabled': bool(v.get('enabled')), 'item': str(v.get('item') or '').strip(),
            'scope': str(v.get('scope') or '') if str(v.get('scope') or '') in SCOPES else 'listed',
            'values': values[:MAX_VALUES], 'pattern': str(v.get('pattern') or '').strip(),
            'folder': str(v.get('folder') or '').strip(),
            'method': str(v.get('method') or '') if str(v.get('method') or '') in METHODS else 'default'}


def everything(v):
    """出てきた値すべてで分けるか（v は対象でも、variants でもよい）。"""
    v = v if isinstance(v, dict) else {}
    return normalize(v.get('variants') if 'variants' in v else v)['scope'] == 'all'


def default_method(settings):
    """共通設定の既定の取り方。知らない値・空なら DEFAULT_METHOD。"""
    m = str((settings or {}).get('variant_method') or '')
    return m if m in METHODS else DEFAULT_METHOD


def method(job, settings):
    """この対象を実際にどちらの取り方で動かすか。対象で選んでいればそれ、「既定に従う」なら共通設定の既定。
    出てきた値すべてで分けるときは、値が問い合わせるまで分からないので、いつもまとめて1回。"""
    v = normalize((job or {}).get('variants'))
    if v['scope'] == 'all':
        return 'combined'
    return v['method'] if v['method'] in METHODS else default_method(settings)


def active(job):
    """この対象を値ごとに分けて出すか（入りにしてあり、項目がある。指定した値だけなら、値が1つ以上ある）。"""
    v = normalize((job or {}).get('variants'))
    return bool(v['enabled'] and v['item'] and (v['values'] or v['scope'] == 'all'))


def has_token(text):
    """ファイル名・置き場の型に、その回の値（{値}・{値:upper} など）が入っているか。"""
    s = str(text or '')
    return any('{' + t + '}' in s or '{' + t + ':' in s for t in TOKENS)


def plan(job, render, base_name, base_folder, render_folder=None, values=None):
    """値ごとの出し先。render(型, 値) → 展開したファイル名（app.render_filename_template を値つきで呼ぶ）。
    render_folder(型, 値) → 展開した置き場（道の区切りを残す app.render_path_template。省けば render）。
    base_name: 対象のふだんの名前の決め方で作った名前（拡張子なし）、base_folder: 対象の出力先（型のまま）。
    values: 値の並び（出てきた値すべてのときに、出てきた値・数えた値を渡す）。省けば設定の値。
    → [{'value', 'stem'（拡張子なし）, 'folder'（型を展開した置き場。空なら対象の出力先）}]。

    名前: 型があればそれ、無ければ対象の名前の型に {値} があればそれ、どちらにも無ければ「ふだんの名前_値」。
    同じ名前・同じ置き場になる値があれば ValueError（あとの値が前の値のファイルを上書きしてしまう）。"""
    v = normalize((job or {}).get('variants'))
    job_pattern = str((job or {}).get('output_pattern') or '') if str((job or {}).get('naming_mode') or '') == 'template' else ''
    out, seen = [], {}
    for value in (v['values'] if values is None else [str(x) for x in values]):
        if v['pattern']:
            stem = render(v['pattern'], value)
        elif has_token(job_pattern):
            stem = render(job_pattern, value)
        else:
            stem = render(str(base_name) + '_{値}', value)
        folder = (render_folder or render)(v['folder'], value) if v['folder'] else str(base_folder or '')
        key = (folder.lower(), stem.lower())
        if key in seen:
            raise ValueError(f'「{seen[key]}」と「{value}」が同じファイル名（{stem}）になります。'
                             f'ファイル名か置き場に {{値}} を入れてください')
        seen[key] = value
        out.append({'value': value, 'stem': stem, 'folder': folder})
    return out


def name_error(v):
    """出てきた値すべてのとき、実行する前に分かる名前の衝突。ファイル名の型にも置き場にも {値} が無いと、
    出てきた値が2つ以上あれば全部が同じ名前になる（値を先に知らないので、plan では実行するまで分からない）。→ 断りの文か ''。"""
    v = normalize(v.get('variants') if isinstance(v, dict) and 'variants' in v else v)
    if v['scope'] != 'all' or not v['pattern'] or has_token(v['pattern']) or has_token(v['folder']):
        return ''
    return f'ファイル名「{v["pattern"]}」に {{値}} がありません。出てきた値が2つ以上あると同じ名前になるので、ファイル名か置き場に {{値}} を入れてください'


def _scan(path, item, open_part, encodings, reset=lambda: None):
    """中間CSVを1回読み、item 列の値ごとに行を書き手へ渡す。split_csv と count_csv の共通の読み方。
    空のマスは「上と同じ値を省いた」書き方（NAVI_NONREPEAT）の名残として、上の行の値を引き継ぐ（受け取りは NAVI_REPEAT に
    しているので、ふつうは空にならない）。全部のマスが空の行は飛ばす。先頭から値が空の行は、どの値にも入れず blank に数える。
    open_part(値, 見出し, 文字コード) → 行を受け取る関数か None（その値は捨てる）。初めて出てきた値で1回だけ呼ぶ。
    文字コードを読み違えたら、reset() で書きかけを片付けてから次の文字コードで読み直す。
    → {'missing_column', 'header', 'found'（出てきた順）, 'rows', 'blank', 'encoding'}"""
    p = Path(path)
    for enc in encodings:
        reset()
        try:
            with p.open('r', encoding=enc, newline='') as f:
                reader = csv.reader(f)
                head = next(reader, None)
                names = [str(x).strip() for x in head] if head is not None else []
                if head is None or item not in names:
                    return {'missing_column': True, 'header': names, 'found': [], 'rows': 0, 'blank': 0, 'encoding': enc}
                i = names.index(item)
                sinks, found, last, rows, blank = {}, [], '', 0, 0
                for row in reader:
                    if not any(str(c).strip() for c in row):
                        continue   # 空の行は数えず、どの値にも入れない（上の値を引き継ぐと、空の行がその値のファイルに入る）
                    rows += 1
                    own = str(row[i]).strip() if i < len(row) else ''
                    cell = own or last
                    last = cell
                    if not cell:
                        blank += 1
                        continue
                    if cell not in sinks:
                        found.append(cell)
                        sinks[cell] = open_part(cell, head, enc)
                    if sinks[cell] is not None:
                        if not own:
                            row = list(row)
                            row[i] = cell
                        sinks[cell](row)
                return {'missing_column': False, 'header': names, 'found': found, 'rows': rows, 'blank': blank,
                        'encoding': enc, 'head': head}
        except UnicodeDecodeError:
            continue
    raise ValueError('中間CSVの文字コードを読めません: %s' % p)


def split_csv(path, item, values, out_dir, encodings=('cp932', 'utf-8-sig', 'utf-8'), limit=MAX_FOUND):
    """まとめて1回で受け取った中間CSVを、item 列の値ごとのCSVに分ける（2.1.1）。
    values: 分ける値の並び。None なら出てきた値すべて（2.5.0）。その値の数が limit を超えたら ValueError。
    → {'missing_column', 'header', 'found'（item 列に出てきた値。出てきた順）, 'rows'（全行数）, 'blank'（値が空でどこにも入れなかった行）,
       'parts': {値: {'path', 'rows'}}（values を渡したときはその並び。1行も無い値も空のファイルを作る。None なら出てきた順）, 'encoding'}。

    値ごとのファイルは「その値の行だけ」を手元で振り分けて作るので、サーバー側の絞り込みが効いていなくても、
    ほかの値の行は混ざらない。元と同じ文字コード・同じ見出しで書く（あとの変換は、ふだんの中間CSVと同じ道を通る）。"""
    out = Path(out_dir)
    want = None if values is None else list(values)
    files, counts, order = {}, {}, []

    def reset():
        for f2 in files.values():
            f2.close()
        files.clear(), counts.clear(), order.clear()

    def open_part(value, head, enc):
        if want is not None and value not in want:
            return None
        if want is None and len(order) >= int(limit):
            raise ValueError(f'出てきた値が {int(limit)} を超えました。値ごとのファイルは {int(limit)} までです。'
                             '分ける項目が合っているか（日時や番号のように値が多い項目でないか）を確かめてください')
        n = len(order) if want is None else want.index(value)
        files[value] = (out / ('part_%02d.csv' % n)).open('w', encoding=enc, newline='')
        w = csv.writer(files[value], lineterminator='\r\n')
        w.writerow(head)
        counts[value] = 0
        order.append(value)

        def put(row):
            w.writerow(row)
            counts[value] += 1
        return put

    out.mkdir(parents=True, exist_ok=True)
    try:
        got = _scan(path, item, open_part, encodings, reset)
        if got['missing_column']:
            return {**got, 'parts': {}}
        for v in want or []:   # 指定した値は、1行も無くても空のファイルを作る（0件を断るのは、あとの変換）
            if v not in files:
                open_part(v, got['head'], got['encoding'])
        got.pop('head', None)
        keys = want if want is not None else order
        return {**got, 'parts': {v: {'path': files[v].name, 'rows': counts[v]} for v in keys}}
    finally:
        reset()


def count_csv(path, item, encodings=('cp932', 'utf-8-sig', 'utf-8')):
    """中間CSVの item 列に、どの値が何行あるか（ファイルは作らない。「出てきた値を数える」で使う）。
    → {'missing_column', 'header', 'values': [{'value', 'rows'}]（出てきた順）, 'rows', 'blank', 'encoding'}。"""
    counts = {}

    def open_part(value, head, enc):
        counts[value] = 0

        def put(row):
            counts[value] += 1
        return put
    got = _scan(path, item, open_part, encodings, counts.clear)
    return {'missing_column': got['missing_column'], 'header': got['header'], 'rows': got['rows'], 'blank': got['blank'],
            'encoding': got['encoding'], 'values': [{'value': v, 'rows': counts[v]} for v in got['found']]}


def need_relax(values, rne_keys, everything_=False):
    """RNE の条件欄の絞り込みを外す必要があるか。
    指定した値だけ: RNE のキーに無い値を頼んでいれば外す。出てきた値すべて: RNE がキーで絞っていれば外す（絞っていなければ、外さなくても全部の値が返る）。"""
    keys = set(rne_keys or [])
    if everything_:
        return bool(keys)
    return any(v not in keys for v in values or [])


def relax_hint(values, rne_keys):
    """外す形の2つ目（一致＋キー1つ）に渡すキー。指定した値の1つ目、無ければ RNE のいまのキー。"""
    return str((list(values or []) or list(rne_keys or []) or [''])[0])


def relaxed(found, rne_keys, values, everything_=False):
    """RNE の条件を外せたか。外す必要があった（RNE のキーに無い値を頼んだ）のに、返った行の値が RNE のキーの中だけなら、
    外せていない（ほかの値の行が0件なのが「無い」のか「取れていない」のか区別できないので、0件のファイルを出さず止める）。
    出てきた値すべてでは、外す必要があった（RNE がキーで絞っている）のに RNE のキーの値しか返らなければ、外せていないかもしれない
    （ほかの値が本当に無いのかもしれない。0件のファイルは作らないので止めず、呼ぶ側が知らせに書く）。"""
    if not rne_keys or not need_relax(values, rne_keys, everything_):
        return True
    return any(v not in set(rne_keys) for v in found)


def count_record(counted, item, signature, period, taken_at):
    """数えた結果を控える形。signature: RNE の (更新時刻, 大きさ)、period: 対象の期間指定（数えたときの条件）。"""
    return {'item': str(item), 'values': list(counted.get('values') or []), 'rows': int(counted.get('rows') or 0),
            'blank': int(counted.get('blank') or 0), 'taken_at': str(taken_at),
            'rne_mtime_ns': str((signature or ('', ''))[0] or ''), 'rne_size': int((signature or ('', 0))[1] or 0),
            'period': period if isinstance(period, dict) else {}}


def count_state(rec, item, signature, period):
    """控えた数が、いまの設定でも使えるか。→ 'none'（控えが無い・項目が違う）・'stale'（RNE か期間指定が変わった）・'fresh'。
    数は「数えたときの条件」での値なので、相対期間（先月など）なら日が変わると中身も変わりうる。それは画面で数えた日時を添えて示す。"""
    if not isinstance(rec, dict) or str(rec.get('item') or '') != str(item or '') or not item:
        return 'none'
    same_rne = str(rec.get('rne_mtime_ns') or '') == str((signature or ('', ''))[0] or '') and \
        int(rec.get('rne_size') or 0) == int((signature or ('', 0))[1] or 0)
    same_period = (rec.get('period') or {}) == (period if isinstance(period, dict) else {})
    return 'fresh' if same_rne and same_period else 'stale'


def query_text(ov):
    """問い合わせの前に出す一言（値を絞る段・実行中）。ov は実行時の条件の差し替え。"""
    if ov.get('all'):
        return f'{ov["item"]} の絞り込みを外し、出てきた値すべてを1回で問い合わせます'
    return f'{ov["item"]} を {len(ov["values"])}値（{"・".join(ov["values"])}）に絞ります'


def summary(results):
    """値ごとの結果をまとめた1行（実績・知らせに出す）。results: [{'value', 'ok', 'rows', 'error'}]。"""
    ok = [r for r in results if r.get('ok')]
    ng = [r for r in results if not r.get('ok')]
    parts = [f"{r['value']} {int(r.get('rows') or 0):,}件" for r in ok]
    text = f'{len(ok)}/{len(results)}ファイル（' + '・'.join(parts) + '）' if parts else f'0/{len(results)}ファイル'
    if ng:
        text += ' / 失敗: ' + '・'.join(f"{r['value']}（{str(r.get('error') or '')[:60]}）" for r in ng)
    return text
