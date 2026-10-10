"""条件の値ごとに分けて出す（2.1.0）。

1つの対象（RNE）を、条件欄のデータ項目のキーだけ差し替えて値の数だけ問い合わせ、値ごとに別のファイルへ出す。
例: BOX実績_設備名 に LS3・LS4・DL2・KEN → 4回問い合わせて4ファイル。RNEファイルは書き換えない
（API の NaviChangeConditionDI で、開いたカタログの条件だけを差し替える）。

ここは決まりだけを持つ（設定の形・ファイル名と置き場の決め方・絞れたかの確かめ）。DBも画面もAPIも触らないので、
実機なしで確かめられる。問い合わせそのものは app.process_api_parallel_job が値ごとに1回ずつ行う。
"""
import csv
from pathlib import Path

# ファイル名・置き場に書く「その回の値」。{値} と {value} のどちらでも書ける
TOKENS = ('値', 'value')
MAX_VALUES = 50          # 1つの対象で分ける数の上限（打ち間違いで数百回問い合わせないように）
SAMPLE_OTHERS = 3        # 絞れていなかったとき、知らせに出す「ほかの値」の数


def normalize(v):
    """画面・持ち込みから来た形を、保存する形にそろえる。
    → {'enabled', 'item'（条件欄の項目名）, 'values'（重ねない・前後の空白を落とす）, 'pattern'（ファイル名の型。空なら対象の名前の決め方）,
       'folder'（置き場の型。空なら対象の出力先）}"""
    v = v if isinstance(v, dict) else {}
    seen, values = set(), []
    for x in v.get('values') or []:
        s = '' if x is None else str(x).strip()
        if s and s not in seen:
            seen.add(s)
            values.append(s)
    return {'enabled': bool(v.get('enabled')), 'item': str(v.get('item') or '').strip(),
            'values': values[:MAX_VALUES], 'pattern': str(v.get('pattern') or '').strip(),
            'folder': str(v.get('folder') or '').strip()}


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


def check_rows(path, item, value, encodings=('cp932', 'utf-8-sig', 'utf-8')):
    """問い合わせた結果（中間CSV）が、本当にその値だけに絞れているか。
    → {'checked'（列があって確かめられたか）, 'rows', 'other'（その値以外に入っていた値。最大 SAMPLE_OTHERS 個）}。

    条件を差し替えても、渡し方によっては rc=OK のまま1行も絞られないことがある（行分割で実測済み）。黙って全件を
    値ごとのファイルにしないよう、出力に同じ名前の列があれば中身で確かめる。空のマスは「上と同じ値を省いた」書き方
    （NAVI_NONREPEAT）なので数えない。列が無ければ確かめられないので checked=False で返す（止めはしない）。"""
    p = Path(path)
    for enc in encodings:
        try:
            with p.open('r', encoding=enc, newline='') as f:
                reader = csv.reader(f)
                head = next(reader, None)
                if head is None:
                    return {'checked': False, 'rows': 0, 'other': []}
                names = [str(x).strip() for x in head]
                if item not in names:
                    return {'checked': False, 'rows': sum(1 for _ in reader), 'other': []}
                i = names.index(item)
                rows, other = 0, []
                for row in reader:
                    rows += 1
                    cell = str(row[i]).strip() if i < len(row) else ''
                    if cell and cell != value and cell not in other and len(other) < SAMPLE_OTHERS:
                        other.append(cell)
                return {'checked': True, 'rows': rows, 'other': other}
        except UnicodeDecodeError:
            continue
    return {'checked': False, 'rows': 0, 'other': []}


def summary(results):
    """値ごとの結果をまとめた1行（実績・知らせに出す）。results: [{'value', 'ok', 'rows', 'error'}]。"""
    ok = [r for r in results if r.get('ok')]
    ng = [r for r in results if not r.get('ok')]
    parts = [f"{r['value']} {int(r.get('rows') or 0):,}件" for r in ok]
    text = f'{len(ok)}/{len(results)}ファイル（' + '・'.join(parts) + '）' if parts else f'0/{len(results)}ファイル'
    if ng:
        text += ' / 失敗: ' + '・'.join(f"{r['value']}（{str(r.get('error') or '')[:60]}）" for r in ng)
    return text
