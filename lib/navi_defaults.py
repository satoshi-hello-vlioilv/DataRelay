"""置き場の「既定の設定」―― 新しいPCへ渡す最初の設定（2.0.0）。

2.0.0 から、設定（対象の登録・自動実行の予定・読取マスタ・結合マスタ・共通設定・RNE）は各PCの手元（写しの data）に持つ。
配る版はプログラムだけにして、PCごとの中身の出どころを置き場の `defaults\\` に1つ置く:

  defaults\\manifest.json      … 何が入っているか（id・いつ・誰が・どのPCから・件数・項目の名前）
  defaults\\jobs.json          … 対象の登録   ┐
  defaults\\schedules.json     … 自動実行の予定 │ 形は「登録内容の持ち出し」（navi_bundle）と同じ。
  defaults\\text-layouts.json  … 読取マスタ   │ ZIP にせず並べて置くので、メモ帳でもそのまま読める
  defaults\\join-recipes.json  … 結合マスタ   ┘
  defaults\\settings.json      … 共通設定（出力先・抽出方式・控え など。接続の認証情報は入れない）
  defaults\\rne\\              … 対象が使う RNE（対象の rne_path は .\\rne\\<名前> に直して入れる）

各PCは手元の data\\data.json に「どの既定（id）まで見たか」を持ち、置き場の既定が新しくなれば画面が聞く:
  上書き   … 既定にある物は既定の中身にする（同じ名前の物は置き換え、無い物は足す）。既定に無い手元の物は残す
  差分追加 … 既定にあって手元に無い物だけを足す（同じ名前の手元の物は触らない）
  今のまま … 何も変えない（この既定はもう聞かない）
どれを選んでも、当てる前に手元の設定の控えを取る（data\\backup\\）。

ここは置き場のファイルと、手元の印（data.json）と、比べ方・当て方の決まりだけを持つ。設定 DB と画面は触らない
（取り込みは navi_web が navi_bundle と同じ道で行う）。試験が直に呼べるように、場所はすべて引数で受け取る。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import navi_bundle

DIR = 'defaults'
MANIFEST = 'manifest.json'
SETTINGS = 'settings.json'
RNE_DIR = 'rne'
KIND = 'datarelay-defaults'
SETTINGS_KIND = 'datarelay-settings'
PARTS = navi_bundle.PARTS                  # jobs・schedules・layouts・recipes
ALL_PARTS = PARTS + ('settings', 'rne')
PART_LABEL = dict(navi_bundle.PART_LABEL, settings='共通設定', rne='RNE')
# 共通設定として渡す項目（パス・抽出方式・控え・並列など）。渡さない物: 置き場（update_dir・各PCが入れた元から知る）、
# 接続の認証情報（各PCの資格情報マネージャー）、設定の版（settings_revision）。
COMMON_KEYS = ('default_output_folder', 'text_folder', 'rne_folder', 'backup_folder', 'symnavi_exe', 'symnavim_def',
               'accdb_template', 'navigator_api_dll', 'navigator_api_search_roots')
MODES = ('overwrite', 'add', 'keep')
MODE_LABEL = {'overwrite': '上書き', 'add': '差分追加', 'keep': '今のまま'}
MARK = 'data.json'
BACKUP_DIR = 'backup'
BACKUP_KEEP = 10


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.%s.%d.tmp' % (path.name, os.getpid()))
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return data


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ==== 置き場の既定 ====
def folder(base):
    return Path(base) / DIR


def read(base):
    """置き場の既定。無ければ None。→ {'manifest', 'jobs', 'schedules', 'layouts', 'recipes', 'settings', 'rne': {名前: 道}}"""
    d = folder(base)
    man = _read_json(d / MANIFEST)
    if not isinstance(man, dict) or man.get('kind') != KIND:
        return None
    out = {'manifest': man, 'rne': {}}
    for part in PARTS:
        out[part] = _read_json(d / navi_bundle.PART_FILE[part])
    st = _read_json(d / SETTINGS)
    out['settings'] = st if isinstance(st, dict) and st.get('kind') == SETTINGS_KIND else None
    try:
        out['rne'] = {p.name: p for p in sorted((d / RNE_DIR).iterdir()) if p.is_file()}
    except OSError:
        pass
    return out


def names_of(part, payload):
    """持ち出しの形から、項目の名前の並び。"""
    if not isinstance(payload, dict):
        return []
    if part == 'schedules':
        return [str(x.get('job_name') or '') for x in payload.get('jobs') or []]
    key = navi_bundle.PART_LIST_KEY[part]
    return [str(x.get('name') or '') for x in payload.get(key) or []]


def summary(d):
    """画面に出す中身（件数と名前）。d は read() の答え。"""
    if not d:
        return {'exists': False}
    man = d['manifest']
    parts = {p: names_of(p, d.get(p)) for p in PARTS}
    parts['rne'] = sorted(d.get('rne') or {})
    st = d.get('settings') or {}
    return {'exists': True, 'id': man.get('id', ''), 'savedAt': man.get('savedAt', ''), 'savedBy': man.get('savedBy', ''),
            'pc': man.get('pc', ''), 'appVersion': man.get('appVersion', ''), 'note': man.get('note', ''),
            'parts': parts, 'counts': {p: len(v) for p, v in parts.items()},
            'settings': bool(st), 'settingsKeys': sorted((st.get('top') or {}).keys())}


def write(base, payloads, settings=None, rne_files=None, uid='', pc='', app_version='', note=''):
    """既定を置く（まるごと入れ替える）。途中のフォルダーへ書いてから名前を替える（半端な既定を残さない）。
    payloads: {部分: 持ち出しの形}（無い部分は空で置く）、settings: {'top': {...}, 'settings': {...}} か None、
    rne_files: {置く名前: 元のファイルの道}。→ 置いた manifest。"""
    base = Path(base)
    d = folder(base)
    tmp = base / ('.%s.%d.tmp' % (DIR, os.getpid()))
    old = base / ('.%s.%d.old' % (DIR, os.getpid()))
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        counts = {}
        for part in PARTS:
            body = payloads.get(part) if payloads else None
            if body is None:
                body = _empty(part)
            _write_json(tmp / navi_bundle.PART_FILE[part], body)
            counts[part] = len(names_of(part, body))
        if settings:
            _write_json(tmp / SETTINGS, {'kind': SETTINGS_KIND, 'top': dict(settings.get('top') or {}),
                                         'settings': dict(settings.get('settings') or {})})
        (tmp / RNE_DIR).mkdir()
        for name, src in sorted((rne_files or {}).items()):
            shutil.copyfile(src, tmp / RNE_DIR / name)
        counts['rne'] = len(rne_files or {})
        man = {'kind': KIND, 'id': uuid.uuid4().hex, 'savedAt': _now(), 'savedBy': uid, 'pc': pc,
               'appVersion': app_version, 'note': str(note or '')[:200], 'counts': counts, 'settings': bool(settings)}
        _write_json(tmp / MANIFEST, man)
        if d.exists():
            os.replace(d, old)
        os.replace(tmp, d)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        if old.exists() and not d.exists():
            os.replace(old, d)
        raise
    shutil.rmtree(old, ignore_errors=True)
    return man


def _empty(part):
    if part == 'jobs':
        return navi_bundle.jobs_export([])
    if part == 'schedules':
        return navi_bundle.schedules_export([])
    key = navi_bundle.PART_LIST_KEY[part]
    return {'kind': navi_bundle.PART_KIND[part], 'version': 1, 'count': 0, key: []}


def remove(base):
    """既定を消す（新しいPCは空から始まる）。→ 消したか。"""
    d = folder(base)
    if not d.exists():
        return False
    trash = Path(base) / ('.%s.%d.del' % (DIR, os.getpid()))
    os.replace(d, trash)
    shutil.rmtree(trash, ignore_errors=True)
    return True


def without(d, part, names):
    """既定 d から、部分 part の名前 names を外した (payloads, settings, rne_files)。write() へそのまま渡せる。
    対象を外すと、その予定も外す。RNE は、残った対象が使っていなければ外す。"""
    names = set(names)
    payloads = {p: json.loads(json.dumps(d.get(p))) if d.get(p) else _empty(p) for p in PARTS}
    settings = d.get('settings')
    rne = dict(d.get('rne') or {})
    if part == 'settings':
        settings = None
    elif part == 'rne':
        rne = {k: v for k, v in rne.items() if k not in names}
    else:
        key = 'jobs' if part == 'schedules' else navi_bundle.PART_LIST_KEY[part]
        field = 'job_name' if part == 'schedules' else 'name'
        body = payloads[part]
        body[key] = [x for x in body.get(key) or [] if str(x.get(field) or '') not in names]
        if part == 'jobs':
            sch = payloads['schedules']
            sch['jobs'] = [x for x in sch.get('jobs') or [] if str(x.get('job_name') or '') not in names]
            used = {rne_name(j) for j in body['jobs']}
            rne = {k: v for k, v in rne.items() if k in used}
    for p in PARTS:
        payloads[p]['count'] = len(names_of(p, payloads[p]))
    return payloads, settings, rne


def rne_name(job):
    """既定の中の対象が使う RNE の名前（.\\rne\\<名前> の <名前>）。RNE の対象でなければ空。"""
    if str(job.get('source') or 'rne') != 'rne':
        return ''
    raw = str(job.get('rne_path') or job.get('rne') or '').replace('\\', '/')
    return raw.rsplit('/', 1)[-1]


# ==== 手元と比べる ====
_VOLATILE = ('id', 'exported_at', 'updated_at', 'created_at')


def _strip(v):
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items() if k not in _VOLATILE}
    if isinstance(v, list):
        return [_strip(x) for x in v]
    return v


def _canon(item):
    """比べるための形（鍵の順・id・書き出した時刻に左右されない）。対象・マスタは辞書、予定は規則の並び。"""
    return json.dumps(_strip(item), ensure_ascii=False, sort_keys=True)


def _items(part, payload):
    if not isinstance(payload, dict):
        return {}
    if part == 'schedules':
        return {str(x.get('job_name') or ''): x.get('schedules') or [] for x in payload.get('jobs') or []}
    return {str(x.get('name') or ''): x for x in payload.get(navi_bundle.PART_LIST_KEY[part]) or []}


def diff(d, local, local_rne_dir=None):
    """既定 d と手元（local＝同じ持ち出しの形の {部分: 中身}）の違い。部分ごとに
    add（既定にあって手元に無い）・change（同じ名前で中身が違う）・same・local（手元だけ）の名前。"""
    out = {}
    for part in PARTS:
        a, b = _items(part, d.get(part)), _items(part, local.get(part))
        out[part] = {'add': sorted(n for n in a if n not in b),
                     'change': sorted(n for n in a if n in b and _canon(a[n]) != _canon(b[n])),
                     'same': sorted(n for n in a if n in b and _canon(a[n]) == _canon(b[n])),
                     'local': sorted(n for n in b if n not in a)}
    rne = d.get('rne') or {}
    have = Path(local_rne_dir) if local_rne_dir else None
    r = {'add': [], 'change': [], 'same': [], 'local': []}
    for name, src in sorted(rne.items()):
        dst = have / name if have else None
        if not dst or not dst.is_file():
            r['add'].append(name)
        elif _sha256(dst) != _sha256(src):
            r['change'].append(name)
        else:
            r['same'].append(name)
    out['rne'] = r
    st = d.get('settings') or {}
    out['settings'] = {'add': [], 'change': ['共通設定'] if st else [], 'same': [], 'local': []}
    return out


def picks(mode, dif):
    """選んだ当て方で、部分ごとに当てる名前。上書き＝add+change、差分追加＝add、今のまま＝なし。"""
    if mode not in MODES:
        raise ValueError('当て方が分かりません: %r' % mode)
    take = {'overwrite': ('add', 'change'), 'add': ('add',), 'keep': ()}[mode]
    return {p: [n for k in take for n in v.get(k, [])] for p, v in dif.items()}


def has_data(local):
    """手元に何か登録してあるか（無ければ聞かずに既定を当てる）。"""
    return any(names_of(p, local.get(p)) for p in ('jobs', 'layouts', 'recipes'))


# ==== 手元の印（data\\data.json）と控え ====
def read_mark(data_root):
    m = _read_json(Path(data_root) / MARK)
    return m if isinstance(m, dict) else None


def write_mark(data_root, **kw):
    """印を書く（前の値に重ねる）。→ 書いた印。"""
    m = dict(read_mark(data_root) or {'createdAt': _now()})
    m.update(kw)
    m['updatedAt'] = _now()
    _write_json(Path(data_root) / MARK, m)
    return m


def backup(data_root, files, label):
    """当てる前の控え（data\\backup\\<時刻>-<label>\\）。files: {控えの中の名前: 元の道}。古い物は BACKUP_KEEP 個まで残す。
    → 控えのフォルダー。"""
    root = Path(data_root) / BACKUP_DIR
    dest = root / ('%s-%s' % (time.strftime('%Y%m%d-%H%M%S'), label))
    dest.mkdir(parents=True, exist_ok=True)
    for name, src in files.items():
        src = Path(src)
        if src.is_dir():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
        elif src.is_file():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / name)
    olds = sorted(x for x in root.iterdir() if x.is_dir())
    for x in olds[:-BACKUP_KEEP]:
        shutil.rmtree(x, ignore_errors=True)
    return dest
