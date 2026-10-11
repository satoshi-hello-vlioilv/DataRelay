"""条件の値ごとに分けて出す（2.1.0。取り方は 2.1.1 で作り直し）。

1つの対象（RNE）から、指定した値ごとに別のファイルを出す。例: BOX実績_設備名 に LS3・LS4・DL2・KEN → 4ファイル。
RNEファイルは書き換えない（開いたカタログの条件と表側のカテゴリだけを、API で変える）。

取り方は2つ（METHODS）。どちらも、RNE の条件欄の絞り込み（例: LS4 だけ）を外し、表側の同じ名前の管理ポイントを
指定の値だけに絞って問い合わせ、受け取ったCSVを手元で値ごとに振り分けてから出す（ほかの値の行は混ざらない）。
- combined（まとめて1回）: 指定の値を全部入れて1回だけ問い合わせ、受け取ってから値ごとに分ける
- parallel（値ごとに並列）: 値ごとに別のワーカーで問い合わせる（RNE を値の数に分けたのと同じ）。データが大きいと速いことがある
対象ごとに選べ、「既定に従う」なら共通設定の既定（settings.variant_method）を使う。

ここは決まりだけを持つ（設定の形・取り方・ファイル名と置き場の決め方・分け方・外せたかの確かめ）。DBも画面もAPIも
触らないので、実機なしで確かめられる。問い合わせそのものは app.process_api_parallel_job が行う。
"""
import csv
from pathlib import Path

# ファイル名・置き場に書く「その回の値」。{値} と {value} のどちらでも書ける
TOKENS = ('値', 'value')
MAX_VALUES = 50          # 1つの対象で分ける数の上限（打ち間違いで数百回問い合わせないように）
METHODS = ('combined', 'parallel')     # まとめて1回 / 値ごとに並列
DEFAULT_METHOD = 'combined'            # 共通設定に何も無いときの既定（問い合わせが1回で済み、サーバーの負担が小さい）
METHOD_NAMES = {'combined': 'まとめて1回', 'parallel': '値ごとに並列', 'default': '既定に従う'}


def normalize(v):
    """画面・持ち込みから来た形を、保存する形にそろえる。
    → {'enabled', 'item'（条件欄の項目名）, 'values'（重ねない・前後の空白を落とす）, 'pattern'（ファイル名の型。空なら対象の名前の決め方）,
       'folder'（置き場の型。空なら対象の出力先）, 'method'（'default'・'combined'・'parallel'。知らない値は 'default'）}"""
    v = v if isinstance(v, dict) else {}
    seen, values = set(), []
    for x in v.get('values') or []:
        s = '' if x is None else str(x).strip()
        if s and s not in seen:
            seen.add(s)
            values.append(s)
    return {'enabled': bool(v.get('enabled')), 'item': str(v.get('item') or '').strip(),
            'values': values[:MAX_VALUES], 'pattern': str(v.get('pattern') or '').strip(),
            'folder': str(v.get('folder') or '').strip(),
            'method': str(v.get('method') or '') if str(v.get('method') or '') in METHODS else 'default'}


def default_method(settings):
    """共通設定の既定の取り方。知らない値・空なら DEFAULT_METHOD。"""
    m = str((settings or {}).get('variant_method') or '')
    return m if m in METHODS else DEFAULT_METHOD


def method(job, settings):
    """この対象を実際にどちらの取り方で動かすか。対象で選んでいればそれ、「既定に従う」なら共通設定の既定。"""
    m = normalize((job or {}).get('variants'))['method']
    return m if m in METHODS else default_method(settings)


def active(job):
    """この対象を値ごとに分けて出すか（入りにしてあり、項目と値が1つ以上ある）。"""
    v = normalize((job or {}).get('variants'))
    return bool(v['enabled'] and v['item'] and v['values'])


def has_token(text):
    """ファイル名・置き場の型に、その回の値（{値}・{値:upper} など）が入っているか。"""
    s = str(text or '')
    return any('{' + t + '}' in s or '{' + t + ':' in s for t in TOKENS)


def plan(job, render, base_name, base_folder, render_folder=None):
    """値ごとの出し先。render(型, 値) → 展開したファイル名（app.render_filename_template を値つきで呼ぶ）。
    render_folder(型, 値) → 展開した置き場（道の区切りを残す app.render_path_template。省けば render）。
    base_name: 対象のふだんの名前の決め方で作った名前（拡張子なし）、base_folder: 対象の出力先（型のまま）。
    → [{'value', 'stem'（拡張子なし）, 'folder'（型を展開した置き場。空なら対象の出力先）}]。

    名前: 型があればそれ、無ければ対象の名前の型に {値} があればそれ、どちらにも無ければ「ふだんの名前_値」。
    同じ名前・同じ置き場になる値があれば ValueError（あとの値が前の値のファイルを上書きしてしまう）。"""
    v = normalize((job or {}).get('variants'))
    job_pattern = str((job or {}).get('output_pattern') or '') if str((job or {}).get('naming_mode') or '') == 'template' else ''
    out, seen = [], {}
    for value in v['values']:
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


def split_csv(path, item, values, out_dir, encodings=('cp932', 'utf-8-sig', 'utf-8')):
    """まとめて1回で受け取った中間CSVを、item 列の値ごとのCSVに分ける（2.1.1）。
    → {'missing_column', 'header', 'found'（item 列に出てきた値。出てきた順）, 'rows'（全行数）,
       'parts': {値: {'path', 'rows'}}, 'encoding'}。

    値ごとのファイルは「その値の行だけ」を手元で振り分けて作るので、サーバー側の絞り込みが効いていなくても、
    ほかの値の行は混ざらない。空のマスは「上と同じ値を省いた」書き方（NAVI_NONREPEAT）の名残として、
    上の行の値を引き継ぐ（受け取りは NAVI_REPEAT にしているので、ふつうは空にならない）。全部のマスが空の行は飛ばす。
    元と同じ文字コード・同じ見出しで書く（あとの変換は、ふだんの中間CSVと同じ道を通る）。"""
    p, out = Path(path), Path(out_dir)
    want = list(values)
    for enc in encodings:
        try:
            with p.open('r', encoding=enc, newline='') as f:
                reader = csv.reader(f)
                head = next(reader, None)
                if head is None:
                    return {'missing_column': True, 'header': [], 'found': [], 'rows': 0, 'parts': {}, 'encoding': enc}
                names = [str(x).strip() for x in head]
                if item not in names:
                    return {'missing_column': True, 'header': names, 'found': [], 'rows': 0, 'parts': {}, 'encoding': enc}
                i = names.index(item)
                out.mkdir(parents=True, exist_ok=True)
                files, writers, counts, found, last, rows = {}, {}, {}, [], '', 0
                try:
                    for n, v in enumerate(want):
                        fp = out / ('part_%02d.csv' % n)
                        files[v] = fp.open('w', encoding=enc, newline='')
                        writers[v] = csv.writer(files[v], lineterminator='\r\n')
                        writers[v].writerow(head)
                        counts[v] = 0
                    for row in reader:
                        if not any(str(c).strip() for c in row):
                            continue   # 空の行は数えず、どの値にも入れない（上の値を引き継ぐと、空の行がその値のファイルに入る）
                        rows += 1
                        cell = str(row[i]).strip() if i < len(row) else ''
                        if not cell:
                            cell = last
                        last = cell
                        if cell and cell not in found:
                            found.append(cell)
                        if cell in writers:
                            if i < len(row) and not str(row[i]).strip():
                                row = list(row)
                                row[i] = cell
                            writers[cell].writerow(row)
                            counts[cell] += 1
                finally:
                    for f2 in files.values():
                        f2.close()
                return {'missing_column': False, 'header': names, 'found': found, 'rows': rows, 'encoding': enc,
                        'parts': {v: {'path': str(out / ('part_%02d.csv' % n)), 'rows': counts[v]} for n, v in enumerate(want)}}
        except UnicodeDecodeError:
            continue
    raise ValueError('中間CSVの文字コードを読めません: %s' % p)


def relaxed(found, rne_keys, values):
    """RNE の条件を外せたか。外す必要があった（RNE のキーに無い値を頼んだ）のに、返った行の値が RNE のキーの中だけなら、
    外せていない（ほかの値の行が0件なのが「無い」のか「取れていない」のか区別できないので、0件のファイルを出さず止める）。"""
    need = [v for v in values if v not in set(rne_keys or [])]
    if not need or not rne_keys:
        return True
    return any(v not in set(rne_keys) for v in found)


def summary(results):
    """値ごとの結果をまとめた1行（実績・知らせに出す）。results: [{'value', 'ok', 'rows', 'error'}]。"""
    ok = [r for r in results if r.get('ok')]
    ng = [r for r in results if not r.get('ok')]
    parts = [f"{r['value']} {int(r.get('rows') or 0):,}件" for r in ok]
    text = f'{len(ok)}/{len(results)}ファイル（' + '・'.join(parts) + '）' if parts else f'0/{len(results)}ファイル'
    if ng:
        text += ' / 失敗: ' + '・'.join(f"{r['value']}（{str(r.get('error') or '')[:60]}）" for r in ng)
    return text
