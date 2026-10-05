"""配布の置き場に版を残し、配る版を決める（1.98.0・WaveLog の配布の仕組みを取り入れた）。

置き場（`dir_choice()`）の中身:
  versions/<版>/      … 版ごとの中身と manifest.json（全ファイルの道・大きさ・sha256・入れ替える項目 payload）
  release.json        … 配る版（全PCが起動のたびにそろえる版。誰が・いつ・前の版も控える）
  DataRelay.exe       … 配る入口。新しいPCにはこの exe のアドレスだけを渡す（初回の起動でこのPCへ写して開く）
  install.json        … 新しいPCへ渡す最初の設定（データの基準＝共有のアプリのフォルダー・設定のマスターの在りか）
  fleet/<PC>.json     … 各PCが名乗る版（誰がまだ古い版か・どこで動いているかを見るため）

置き場の既定は**アプリのフォルダーそのもの**（共有から直に動かしてきたフォルダー）。そうすると:
  - 置き場の決まった字を持たなくてよい（どの職場の共有でもそのまま使える）
  - 皆が使ってきた共有の DataRelay.exe がそのまま配る入口になる（配る版を決めた日から、ダブルクリックした
    PCは自分の写しへ移る。アドレスを配り直さなくてよい）
  - 設定のマスター（Config\\app_settings.sqlite3）も同じフォルダーにあるので、新しいPCへ渡す設定が要らない

役目の分け方:
  ・ここ（Python）… ZIP を検めて版を置く・配る版を決める・状態を答える・各PCの版を集める（画面の「配布と更新」）
  ・窓（Rust・desktop/src/release.rs）… 起動画面の中で、中身（Python）を起こす**前に** release.json を読み、
    手元の版と違えば版のフォルダーを写して sha256 を確かめ、項目ごとに入れ替える（動いている Python の
    ファイルを入れ替えないため）。初回のインストールも同じ道（desktop/src/install.rs）。
**データ（設定のマスター・接続ファイル・登録した RNE）は版に入れない**――共有のアプリのフォルダーに残り、
各PCの写しはそこを指す（navi_paths.data_root）。

このファイルは app を読み込まない（置き場とアプリの場所を引数で受け取る）。試験が直に呼べるように。
"""
import hashlib
import json
import os
import re
import shutil
import socket
import threading
import time
import zipfile
from pathlib import Path

import navi_paths

# ---- 名前（窓の release.rs・install.rs と同じ字） ----
ENTRY_EXE = 'DataRelay.exe'
MANIFEST = 'manifest.json'
RELEASE = 'release.json'
VERSIONS = 'versions'
FLEET = 'fleet'
SEED = navi_paths.SEED_FILE        # install.json（置き場の物は渡す設定、写しの config\ の物は窓が書いた控え）
LOCAL = navi_paths.LOCAL_FILE      # local.json（このPCだけの上書き。書くのは人）
MIRROR = 'update.json'             # 共有の設定（置き場）の控え。窓は Python を起こす前に置き場を知る必要がある
CONFIG_KEY = 'update_dir'          # 置き場を指す鍵（local.json・update.json・共有の設定）
DATA_KEY = navi_paths.DATA_KEY     # データの基準を指す鍵（install.json・local.json）
FROM_KEY = 'from'                  # 写しの config\install.json が持つ「入れた元の置き場」
# 版に欠かせない物（無い ZIP は断る）。
REQUIRED = ('app.py', 'sidecar.py', 'lib/navi_version.py', 'templates/index.html', ENTRY_EXE)
# データと配る物が同じフォルダーに同居している名前。項目を1段下で数える（config\rne を入れ替えても、
# 同じフォルダーの install.json・local.json・update.json は残る）。Windows は大文字小文字を区別しない。
MIXED = ('config',)
# 版に入れない名前（どの段でも）。
SKIP = ('__pycache__', '.update', '.git')
# 版の字（窓と同じ読み方）: 数字で始まり、英数字・点・ハイフンだけ。道に混ぜる前に確かめる。
_SAFE_VERSION = re.compile(r'^[0-9][0-9A-Za-z.\-]{0,40}$')
_VERSION_RE = re.compile(r"^APP_VERSION\s*=\s*['\"]([0-9][0-9A-Za-z.\-]*)['\"]", re.M)
# 共有に届くかを確かめる長さ。届かない UNC は OS が数十秒待たせることがある（画面を止めない）。
REACH_SEC = 3.0
# 置いている最中に終わった書きかけを片付けるまでの長さ（別のPCがいま置いている物を消さない）。
STALE_SEC = 3600
# 各PCの名乗りが古いとみなすまでの長さ（画面で薄く出す）。
FLEET_STALE_SEC = 7 * 86400


# ==== 版の字 ====
def version_in(text):
    """navi_version.py の中身から版の字を読む（ZIP の中身は import しない）。"""
    m = _VERSION_RE.search(text or '')
    return m.group(1) if m else ''


def safe_version(v):
    return bool(_SAFE_VERSION.match(str(v or '')))


def version_key(v):
    """版を数として比べる（1.10.0 > 1.9.0）。数でない欠片は0。"""
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r'[.\-]', str(v or '')))


# ==== 置き場 ====
def installed(app_root):
    """配布の置き場から写したアプリか（窓が config\\install.json を書く）。"""
    return (Path(app_root) / 'config' / SEED).is_file()


def dir_choice(app_root, shared=''):
    """→ (置き場, 出どころ)。決める順（窓の release.rs の update_dir と同じ）:
       local（このPCの config\\local.json）→ shared（共有の設定）→ install（このPCを入れた元）→ app（アプリのフォルダー）。"""
    conf = Path(app_root) / 'config'
    local = str(navi_paths.read_json(conf / LOCAL).get(CONFIG_KEY) or '').strip()
    if local:
        return Path(navi_paths.expand(local)), 'local'
    if str(shared or '').strip():
        return Path(navi_paths.expand(shared)), 'shared'
    origin = str(navi_paths.read_json(conf / SEED).get(FROM_KEY) or '').strip()
    if origin:
        return Path(navi_paths.expand(origin)), 'install'
    return Path(app_root), 'app'


def remember(app_root, shared=''):
    """共有の設定（置き場）を窓の読む控え（config\\update.json）へ写す。**変わったときだけ書く**。→ 書いたか。
    書き手はこの関数だけ（窓は読むだけ）。"""
    target = Path(app_root) / 'config' / MIRROR
    text = json.dumps({CONFIG_KEY: str(shared or '').strip()}, ensure_ascii=False)
    try:
        if target.is_file() and target.read_text(encoding='utf-8') == text:
            return False
        if not str(shared or '').strip() and not target.exists():
            return False                       # 覚えることが無い（空の控えを作らない）
        _write_text(target, text)
        return True
    except OSError:
        return False


def reachable(path, wait=REACH_SEC):
    """置き場に届くか（`wait` 秒で打ち切る）。→ (届いたか, 理由)。**作らない**（見るだけ）。"""
    path = Path(path)
    out = {}

    def look():
        try:
            out['ok'] = path.is_dir()
            if not out['ok']:
                out['why'] = '置き場のフォルダーが見つかりません'
        except OSError as e:
            out['why'] = str(e)
    t = threading.Thread(target=look, name='release-reach', daemon=True)
    t.start()
    t.join(wait)
    if t.is_alive():
        return False, '%d秒待っても置き場に届きません（%s）' % (wait, path)
    if out.get('ok'):
        return True, ''
    return False, '置き場を開けません（%s）: %s' % (path, out.get('why') or '不明')


# ==== 小さな道具 ====
def _write_text(target, text):
    """途中のファイルへ書いてから名前を変える（読む側が半端な物を見ない）。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name('%s.%d.tmp' % (target.name, os.getpid()))
    try:
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _read_json(path):
    v = navi_paths.read_json(path)
    return v or None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def who():
    """置いた人・決めた人の名乗り（ログインの仕組みが無いので、Windows の利用者名とPC名）。"""
    user = os.environ.get('USERNAME') or os.environ.get('USER') or '?'
    return '%s@%s' % (user, pc_name())


def pc_name():
    return os.environ.get('COMPUTERNAME') or socket.gethostname() or '?'


# ==== ZIP を検めて版を置く ====
def _zip_root(names):
    """ZIP の中でアプリのフォルダーにあたる頭（Release の DataRelay.zip は `DataRelay/` が付く）。無ければ None。"""
    marker = 'lib/navi_version.py'
    for n in names:
        if n == marker or n.endswith('/' + marker):
            return n[:-len(marker)]
    return None


def _payload_name(rel):
    """ZIP の中の道（頭を外したもの）が版に入れてよい物か。危ない道（..・絶対・ドライブ）と SKIP は入れない。"""
    parts = rel.split('/')
    if not rel or rel.startswith('/') or any(p in ('', '..') for p in parts) or ':' in parts[0]:
        return False
    return not any(p in SKIP for p in parts)


def payload_item(rel):
    """道が属する入れ替えの項目（最上位の名前。MIXED は1段下まで）。"""
    parts = rel.split('/')
    if parts[0].lower() in MIXED and len(parts) >= 2:
        return '/'.join(parts[:2])
    return parts[0]


def _manifest(version, files, extra=None):
    """目録の形（窓の release.rs が読む）。payload は files から数える（ZIP に入っていた物＝配る物）。"""
    files = sorted(files, key=lambda f: f['path'])
    out = {'version': version, 'payload': sorted({payload_item(f['path']) for f in files}), 'files': files,
           'bytes': sum(f['size'] for f in files)}
    out.update(extra or {})
    return out


def _quiet_tick(**_kw):
    """進み具合を受け取らない呼び手の既定。"""


def sweep_partial(base, older=STALE_SEC):
    """置いている最中に終わった書きかけ（versions/.<版>.<pid>.tmp）を片付ける。`older` 秒より古い物だけ。→ 片付けた数。"""
    root = Path(base) / VERSIONS
    gone = 0
    try:
        dirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith('.') and d.name.endswith('.tmp')]
    except OSError:
        return 0
    for d in dirs:
        try:
            if time.time() - d.stat().st_mtime < older:
                continue
            shutil.rmtree(d)
            gone += 1
        except OSError:
            pass
    return gone


def _open_zip(source):
    """ZIP を検める。→ (ZipFile, 頭を外した道→ZIPの名前, 版, None) か (None, None, None, 断る理由)。"""
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as e:
        return None, None, None, 'ZIP ファイルとして読めません（GitHub の Releases の DataRelay.zip を選んでください）: %s' % e
    names = zf.namelist()
    head = _zip_root(names)
    if head is None:
        zf.close()
        return None, None, None, 'DataRelay の ZIP ではありません（lib/navi_version.py が入っていません）。'
    rel = {n[len(head):]: n for n in names if n.startswith(head) and not n.endswith('/')}
    lack = [r for r in REQUIRED if r not in rel]
    version = version_in(zf.read(rel['lib/navi_version.py']).decode('utf-8', 'replace')) if not lack else ''
    why = ('欠かせない物が入っていません: ' + '・'.join(lack) if lack
           else '' if safe_version(version) else '版を読めません（APP_VERSION）: %r' % version)
    if why:
        zf.close()
        return None, None, None, why
    return zf, {r: n for r, n in rel.items() if _payload_name(r)}, version, None


def _copy_payload(zf, rel, tmp, tick):
    """版に入れる物を tmp へ写す。**写しながら sha256 を数える**（共有は遅いので読み直さない）。→ 目録の files。"""
    total = len(rel)
    total_bytes = sum(zf.getinfo(n).file_size for n in rel.values())
    files, done_bytes = [], 0
    for i, (r, n) in enumerate(sorted(rel.items()), 1):
        target = tmp / r
        target.parent.mkdir(parents=True, exist_ok=True)
        h, size = hashlib.sha256(), 0
        with zf.open(n) as src, open(target, 'wb') as out:
            for chunk in iter(lambda: src.read(1 << 20), b''):
                h.update(chunk)
                out.write(chunk)
                size += len(chunk)
        mode = (zf.getinfo(n).external_attr >> 16) & 0o777
        if mode & 0o111:                       # 実行できる印（Windows 以外で作った ZIP の exe）は残す
            os.chmod(target, mode | 0o600)
        files.append({'path': r, 'size': size, 'sha256': h.hexdigest()})
        done_bytes += size
        tick(stage='copy', done=i, total=total, bytes=done_bytes, totalBytes=total_bytes)
    return files


def publish_zip(source, base, uid='', tick=_quiet_tick):
    """ZIP（Release の DataRelay.zip）を検めて versions/<版>/ として置く。`source` は ZIP の道（または開いたファイル）。

    断る: ZIP でない・DataRelay の物でない・欠かせない物が無い・**同じ版がもう在る**（版を上げずに置き直すと、
    もうその版を写したPCと中身が食い違う）。途中のフォルダーへ書いてから名前を変える（半端な版を残さない）。
    `tick(stage=…)` へ進み具合を渡す（check → copy（done/total・bytes/totalBytes）→ finish）。"""
    base = Path(base)
    tick(stage='check')
    sweep_partial(base)
    zf, rel, version, why = _open_zip(source)
    if why:
        return {'ok': False, 'error': why}
    with zf:
        dest = base / VERSIONS / version
        if dest.exists():
            return {'ok': False, 'error': '版 %s はもう置いてあります。版を上げた ZIP を選んでください。' % version,
                    'version': version}
        tick(stage='copy', version=version, done=0, total=len(rel), bytes=0,
             totalBytes=sum(zf.getinfo(n).file_size for n in rel.values()))
        tmp = base / VERSIONS / ('.%s.%d.tmp' % (version, os.getpid()))
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            files = _copy_payload(zf, rel, tmp, tick)
            tick(stage='finish')
            man = _manifest(version, files, {'placedAt': time.strftime('%Y-%m-%d %H:%M'), 'placedBy': uid or who(),
                                             'source': str(source) if isinstance(source, (str, Path)) else ''})
            (tmp / MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, dest)
        except OSError as e:
            shutil.rmtree(tmp, ignore_errors=True)
            return {'ok': False, 'error': '置き場へ書けません（%s）: %s' % (base, e)}
    return {'ok': True, 'version': version, 'files': len(man['files']), 'bytes': man['bytes']}


# ---- いま置いている版の進み具合（このPCで1本だけ・画面が問い合わせて描く） ----
_RUN_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_PROGRESS = {'state': 'idle'}


def _set_progress(**kw):
    with _STATE_LOCK:
        _PROGRESS.update(kw)


def progress():
    """いま置いている版の進み具合（state: idle／running／done／failed）。経過秒も添える。"""
    with _STATE_LOCK:
        out = dict(_PROGRESS)
    if out.get('startedAt'):
        out['elapsed'] = round((out.get('endedAt') or time.time()) - out['startedAt'], 1)
    return out


def publishing():
    return progress().get('state') == 'running'


def run_publish(source, base, uid=''):
    """画面の「ZIP から版を置く」の1本。**このPCで同時に置けるのは1本だけ**（2本目は理由を返す）。"""
    if not _RUN_LOCK.acquire(blocking=False):
        return {'ok': False, 'busy': True, 'error': 'いま別の版を置いています。置き終わってから選んでください。'}
    try:
        with _STATE_LOCK:
            _PROGRESS.clear()
            _PROGRESS.update(state='running', stage='check', source=str(source), startedAt=time.time())
        try:
            out = publish_zip(source, base, uid, tick=_set_progress)
        except Exception as e:                 # 進み具合を「置いている」のまま残さない
            out = {'ok': False, 'error': '版を置けませんでした: %s' % e}
        _set_progress(state='done' if out.get('ok') else 'failed', endedAt=time.time(),
                      result=out, error=out.get('error', ''))
        return out
    finally:
        _RUN_LOCK.release()


def start_publish(source, base, uid=''):
    """裏の糸で置き始める（画面は progress() を問い合わせて描く）。→ 始めたか・断った理由。"""
    if publishing():
        return {'ok': False, 'busy': True, 'error': 'いま別の版を置いています。置き終わってから選んでください。'}
    if not Path(source).is_file():
        return {'ok': False, 'error': 'ZIP が見つかりません: %s' % source}
    threading.Thread(target=run_publish, args=(source, base, uid), name='release-publish', daemon=True).start()
    return {'ok': True}


# ==== 置いてある版・配る版 ====
def versions(base):
    """置いてある版（新しい順）。manifest の無いフォルダー（書きかけ・手で置いた物）は数えない。"""
    out = []
    try:
        dirs = [d for d in (Path(base) / VERSIONS).iterdir() if d.is_dir() and not d.name.startswith('.')]
    except OSError:
        return out
    for d in dirs:
        m = _read_json(d / MANIFEST)
        if not isinstance(m, dict) or m.get('version') != d.name:
            continue
        out.append({'version': d.name, 'placedAt': m.get('placedAt', ''), 'placedBy': m.get('placedBy', ''),
                    'source': Path(str(m.get('source') or '')).name, 'files': len(m.get('files') or []),
                    'bytes': m.get('bytes', 0)})
    return sorted(out, key=lambda v: version_key(v['version']), reverse=True)


def release(base):
    """配る版（release.json）。決めていなければ None。"""
    r = _read_json(Path(base) / RELEASE)
    return r if isinstance(r, dict) and r.get('version') else None


def place_entry(version, base):
    """配る入口（置き場の直下の DataRelay.exe）をその版の exe にする。→ 置けなかった理由（置けたら空）。
    入口から起こされた exe はすぐこのPCの写しへ渡して終わるので、掴まれている時間は短い。"""
    base = Path(base)
    src = base / VERSIONS / version / ENTRY_EXE
    dst = base / ENTRY_EXE
    try:
        if dst.is_file() and dst.stat().st_size == src.stat().st_size and _sha256(dst) == _sha256(src):
            return ''
        tmp = dst.with_name('%s.%d.tmp' % (dst.name, os.getpid()))
        shutil.copyfile(src, tmp)
        shutil.copymode(src, tmp)
        os.replace(tmp, dst)
        return ''
    except OSError as e:
        return ('配る入口（%s）を置き換えられませんでした: %s。どこかのPCが入口から開いている最中かもしれません。'
                '少しおいて、もう一度「この版を配る」を押してください。' % (dst, e))


def place_seed(base, data_root):
    """新しいPCへ渡す最初の設定（置き場の install.json）を書く。→ 書けなかった理由（書けたら空）。
    渡すのはデータの基準だけ（そのPCの物は渡さない）。自分のプロファイルの下なら %USERPROFILE% へ直して書く
    （BOX Drive は利用者ごとに場所が違う）。"""
    base = Path(base)
    try:
        _write_text(base / SEED, json.dumps({DATA_KEY: navi_paths.portable(str(data_root))}, ensure_ascii=False, indent=1))
        return ''
    except OSError as e:
        return '新しいPCへ渡す設定を書けませんでした（%s）: %s' % (base / SEED, e)


def set_release(version, base, data_root, uid=''):
    """配る版を決める（前の版も控える）。**置いてある版だけ**選べる。前の版へ戻すのも同じ（選び直すだけ）。
    あわせて配る入口と新しいPCへ渡す設定を置く。この2つが置けなくても配る版は決まっている（各PCの更新は進む）。"""
    base = Path(base)
    if version not in {v['version'] for v in versions(base)}:
        return {'ok': False, 'error': '版 %s は置き場にありません。先に ZIP から置いてください。' % version}
    prev = release(base)
    doc = {'version': version, 'setAt': time.strftime('%Y-%m-%d %H:%M'), 'setBy': uid or who(),
           'previous': (prev or {}).get('version', '')}
    try:
        _write_text(base / RELEASE, json.dumps(doc, ensure_ascii=False, indent=1))
    except OSError as e:
        return {'ok': False, 'error': '配る版を書けません（%s）: %s' % (base, e)}
    notes = [x for x in (place_entry(version, base), place_seed(base, data_root)) if x]
    return {'ok': True, **doc, 'notes': notes}


def entry_info(base):
    """新しいPCへ渡すもの（入口のアドレスと、渡す設定）。画面はこれを出すだけ。"""
    entry = Path(base) / ENTRY_EXE
    seed = navi_paths.read_json(Path(base) / SEED)
    return {'path': str(entry), 'exists': entry.is_file(), 'dataRoot': str(seed.get(DATA_KEY) or '')}


# ==== 各PCの名乗り ====
def _fleet_file(base, pc, user):
    safe = re.sub(r'[^0-9A-Za-z._-]+', '_', '%s-%s' % (pc, user)).strip('_') or 'unknown'
    return Path(base) / FLEET / (safe + '.json')


def announce(base, version, place, app_root, data_root):
    """このPCの版を置き場へ名乗る（fleet/<PC>-<利用者>.json）。→ 書けなかった理由（書けたら空）。"""
    user = os.environ.get('USERNAME') or os.environ.get('USER') or '?'
    doc = {'pc': pc_name(), 'user': user, 'version': version, 'place': place, 'app': str(app_root),
           'dataRoot': str(data_root), 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'epoch': int(time.time())}
    try:
        _write_text(_fleet_file(base, doc['pc'], user), json.dumps(doc, ensure_ascii=False, indent=1))
        return ''
    except OSError as e:
        return str(e)


def fleet(base, want='', now=None):
    """各PCの名乗り（新しい順）。配る版と違えば outdated、長く名乗らなければ stale。"""
    now = now or time.time()
    out = []
    try:
        files = list((Path(base) / FLEET).glob('*.json'))
    except OSError:
        return out
    for f in files:
        d = _read_json(f)
        if not isinstance(d, dict) or not d.get('version'):
            continue
        age = max(0, int(now - int(d.get('epoch') or 0)))
        out.append({'pc': d.get('pc', ''), 'user': d.get('user', ''), 'version': d['version'], 'place': d.get('place', ''),
                    'at': d.get('at', ''), 'age': age, 'stale': age > FLEET_STALE_SEC,
                    'outdated': bool(want) and d['version'] != want})
    return sorted(out, key=lambda x: x['age'])


# ==== 画面へ渡す形（判定はここ・画面は読むだけ） ====
def status(app_root, data_root, version, shared='', place=''):
    base, source = dir_choice(app_root, shared)
    ok, why = reachable(base)
    if ok:
        sweep_partial(base)
    rel = release(base) if ok else None
    want = (rel or {}).get('version', '')
    is_installed = installed(app_root)
    return {'dir': str(base), 'dirSource': source, 'shared': str(shared or ''), 'reachable': ok, 'why': why,
            'local': version, 'place': place or ('installed' if is_installed else 'app'), 'installed': is_installed,
            'appRoot': str(app_root), 'dataRoot': str(data_root),
            'release': rel, 'versions': versions(base) if ok else [],
            # 次の起動でそろえるか（窓が同じ比べ方をする）。写していないPCは、次の起動で写しへ移る
            'pending': bool(want and want != version),
            'publishing': publishing(),
            'entry': entry_info(base) if ok else None,
            'fleet': fleet(base, want) if ok else []}


# ==== 開いたままのPCへ「新しい版が配られた」と知らせる ====
class Watch:
    """配る版を数分おきに読み、この版と違えば1回だけ知らせる（常駐したままのPCは開き直さないので、
    知らせないと古い版のまま動き続ける）。置き場の控え（update.json）の写しと各PCの名乗りも同じ間隔で行う。"""

    def __init__(self, every=600):
        self.every = every
        self.lock = threading.Lock()
        self.last = {'checked': 0.0, 'want': '', 'dir': '', 'reachable': None, 'why': ''}
        self.told = ''

    def check(self, app_root, data_root, version, shared, place, tell=None, announce_too=True):
        base, _source = dir_choice(app_root, shared)
        remember(app_root, shared)
        ok, why = reachable(base)
        want = ((release(base) or {}).get('version', '') if ok else '')
        if ok and want and announce_too:      # 配り始めるまでは名乗らない（置き場を散らかさない）
            announce(base, version, place, app_root, data_root)
        with self.lock:
            self.last = {'checked': time.time(), 'want': want, 'dir': str(base), 'reachable': ok, 'why': why}
            fresh = bool(want and want != version and want != self.told)
            if fresh:
                self.told = want
        if fresh and tell:
            tell(want)
        return self.snapshot(version)

    def snapshot(self, version):
        with self.lock:
            out = dict(self.last)
        out['pending'] = bool(out['want'] and out['want'] != version)
        return out
