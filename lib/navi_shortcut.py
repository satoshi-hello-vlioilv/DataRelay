"""起動アイコン（デスクトップとスタートメニューの .lnk）を、このPCの写しへ向ける（1.98.0）。

配布の置き場から写したPC（窓が config\\install.json を書いたアプリ）では、起動の入口はこのPCの
<写し>\\DataRelay.exe になる。デスクトップにそこを指すアイコンが無ければ、画面が「作りますか」と聞く
（勝手に作らない。断ったら同じ exe については聞き直さない）。

前からあるアイコン（共有の DataRelay.exe・install_local.cmd が置いた %LOCALAPPDATA%\\DataRelay\\bin\\DataRelay.exe を
指すもの）は、作る代わりに**向け直す**（名前と置き場所は利用者のもののまま。同じアイコンが2つ並ばない）。
アイコンは名前ではなく**行き先**で見分ける（利用者が名前を変えていても見つける）。行き先の名前が DataRelay.exe の
ものだけを DataRelay のアイコンとみなす。

.lnk はシェルのオブジェクトなので、Windows の部品（IShellLinkW・pywin32 の COM）で作る・読む。
決め方（どれを向け直すか・どの名前で作るか）はこのファイルの関数が持ち、シェルは差し替えられる（試験は偽物を渡す）。
"""
import json
import os
from pathlib import Path

EXE_NAME = 'DataRelay.exe'
LINK_NAME = 'DataRelay'
DESCRIPTION = 'DataRelay（このPCの写しを開きます）'
DECLINED_FILE = 'shortcut.json'


class WindowsShell:
    """.lnk を Windows の部品で作る・読む（Windows だけ）。

    WScript.Shell（WSH）は使わない ―― 名前やフォルダーに日本語が入ると「?」に化けて保存できない（1.98.0 の CI で実測。
    アカウント名が日本語の PC ではデスクトップの場所そのものが日本語になる）。文字を UTF-16 のまま渡す
    IShellLinkW・IPersistFile と、デスクトップの場所を聞く SHGetFolderPathW を pywin32 から直に呼ぶ（WaveLog と同じ部品）。"""

    def __init__(self):
        import pythoncom                       # pywin32（config\requirements.txt）
        from win32com.shell import shell, shellcon
        # 画面の問い合わせは別の糸で答える。COM はその糸ごとに初期化が要る（無いと「CoInitialize が呼ばれていない」で断られる）。
        # 同じ糸で何度呼んでもよい
        pythoncom.CoInitialize()
        self.pc, self.shell, self.con = pythoncom, shell, shellcon

    def folder(self, kind):
        """'desktop'／'programs'（スタートメニューのプログラム）。OneDrive へ移したデスクトップも正しく返る。"""
        csidl = {'desktop': self.con.CSIDL_DESKTOPDIRECTORY, 'programs': self.con.CSIDL_PROGRAMS}[kind]
        return Path(self.shell.SHGetFolderPath(0, csidl, None, 0))

    def _link(self):
        return self.pc.CoCreateInstance(self.shell.CLSID_ShellLink, None, self.pc.CLSCTX_INPROC_SERVER, self.shell.IID_IShellLink)

    def target(self, link):
        try:
            sc = self._link()
            sc.QueryInterface(self.pc.IID_IPersistFile).Load(str(link), 0)
            # SLGP_RAWPATH（4）＝書かれたままの道（環境変数を展開しない・短い名前へ直さない）
            return str(sc.GetPath(getattr(self.shell, 'SLGP_RAWPATH', 4))[0] or '')
        except Exception:
            return ''

    def make(self, link, target, workdir, description):
        sc = self._link()
        sc.SetPath(str(target))
        sc.SetWorkingDirectory(str(workdir))
        sc.SetIconLocation(str(target), 0)
        sc.SetDescription(description)
        sc.QueryInterface(self.pc.IID_IPersistFile).Save(str(link), 0)


def available():
    """このPCで .lnk を扱えるか（Windows で pywin32 が読める）。"""
    if os.name != 'nt':
        return False
    try:
        from win32com.shell import shell  # noqa: F401
        return True
    except Exception:
        return False


def _same(a, b):
    """同じ場所か（大文字小文字・区切りの違いをならす。Windows の道は大文字小文字を区別しない）。"""
    norm = lambda p: os.path.normcase(os.path.normpath(str(p or '').strip().strip('"'))).replace('/', '\\').lower()
    return bool(str(a or '').strip()) and norm(a) == norm(b)


def _is_datarelay(target):
    return str(target or '').replace('/', '\\').rsplit('\\', 1)[-1].lower() == EXE_NAME.lower()


def scan(shell, exe):
    """デスクトップとスタートメニューの DataRelay のアイコン。→ {'ours': [...], 'old': [...]}（どちらも道の並び）。"""
    ours, old = [], []
    for kind in ('desktop', 'programs'):
        try:
            links = sorted(shell.folder(kind).glob('*.lnk'))
        except OSError:
            continue
        for link in links:
            t = shell.target(link)
            if _same(t, exe):
                ours.append({'path': str(link), 'where': kind})
            elif _is_datarelay(t):
                old.append({'path': str(link), 'where': kind, 'target': t})
    return {'ours': ours, 'old': old}


def free_name(folder, base=LINK_NAME):
    """folder で使っていない .lnk の名前（DataRelay.lnk → DataRelay (2).lnk …）。"""
    folder = Path(folder)
    for n in range(1, 100):
        name = '%s.lnk' % base if n == 1 else '%s (%d).lnk' % (base, n)
        if not (folder / name).exists():
            return folder / name
    return folder / ('%s (%d).lnk' % (base, os.getpid()))


WHERE = {'desktop': 'デスクトップ', 'programs': 'スタートメニュー'}


def ensure(shell, exe, where=('desktop',), retarget=None):
    """アイコンをこの exe へ向ける。前からある DataRelay のアイコンを向け直し（`retarget` の場所だけ。None はすべて）、
    `where` の場所に無ければ作る。→ {'made': [...], 'retargeted': [...], 'errors': [...]}"""
    exe = Path(exe)
    found = scan(shell, exe)
    out = {'made': [], 'retargeted': [], 'errors': []}
    for item in found['old']:
        if retarget is not None and item['where'] not in retarget:
            continue
        try:
            shell.make(item['path'], exe, exe.parent, DESCRIPTION)
            out['retargeted'].append(item['path'])
        except Exception as e:
            out['errors'].append('%s: %s' % (item['path'], e))
    for kind in where:
        if any(x['where'] == kind for x in found['ours'] + found['old']):
            continue                           # その場所にはもうある（古い物は向け直す対象）。2つ並べない
        try:
            link = free_name(shell.folder(kind))
            shell.make(link, exe, exe.parent, DESCRIPTION)
            out['made'].append(str(link))
        except Exception as e:
            out['errors'].append('%s: %s' % (WHERE.get(kind, kind), e))
    return out


def target_exe(app_root, place, running=''):
    """起動アイコンが指す exe と、作れないときの理由。→ (exe か None, 理由)。
    配布から写した形（installed）はその写しの DataRelay.exe。それ以外は、いま動いている exe（窓が DATARELAY_EXE で渡す）――
    共有から直に動かす形は共有の exe、exe だけ手元に置いた形は手元の exe。作る途中の木では作らない（試験が本物のデスクトップを汚さない）。"""
    if place == 'dev':
        return None, '作る途中の木（開発用のフォルダー）では起動アイコンを作りません'
    if place == 'installed':
        exe = Path(app_root) / EXE_NAME
        return (exe, '') if exe.is_file() else (None, 'このPCの写しに %s が見つかりません（%s）' % (EXE_NAME, exe))
    for cand in (str(running or '').strip(), str(Path(app_root) / EXE_NAME)):
        if cand and _is_datarelay(cand) and Path(cand).is_file():
            return Path(cand), ''
    return None, 'DataRelay.exe の場所が分かりません（DataRelay.exe から開くと作れます）'


def state(shell, exe, local_root, why=''):
    """画面「起動アイコン」の答え。場所ごとに、この exe を指すアイコンがあるか・古い場所を指すアイコンがあるか。"""
    out = {'available': bool(shell is not None and exe is not None), 'exe': str(exe or ''), 'why': why,
           'declined': bool(exe is not None and declined(local_root, exe)), 'places': [], 'old': []}
    if shell is None and not why:
        out['why'] = 'このPCでは起動アイコンを作れません（Windows と pywin32 が要ります）'
    if not out['available']:
        return out
    found = scan(shell, exe)
    for kind, label in WHERE.items():
        try:
            folder = str(shell.folder(kind))
        except Exception:
            folder = ''
        out['places'].append({'where': kind, 'label': label, 'folder': folder,
                              'links': [x['path'] for x in found['ours'] if x['where'] == kind],
                              'old': [{'path': x['path'], 'target': x['target']} for x in found['old'] if x['where'] == kind]})
    out['old'] = [{'path': x['path'], 'where': WHERE.get(x['where'], x['where']), 'target': x['target']} for x in found['old']]
    return out


# ---- 断ったことを覚える（このPCのローカル領域・利用者ごと） ----
def _declined_path(local_root):
    return Path(local_root) / 'runtime' / DECLINED_FILE


def declined(local_root, exe):
    try:
        data = json.loads(_declined_path(local_root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and _same(data.get('declined'), exe)


def decline(local_root, exe):
    p = _declined_path(local_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'declined': str(exe)}, ensure_ascii=False), encoding='utf-8')


def undecline(local_root):
    """断ったことを忘れる（あとから自分で作ったとき。断ったままだと、また消したときに聞けない）。"""
    _declined_path(local_root).unlink(missing_ok=True)


def offer(shell, exe, local_root, installed):
    """画面が「作りますか」と聞くか。聞くのは: 配布から写したアプリ・デスクトップに写しを指すアイコンが無い・断っていない。"""
    if not installed or shell is None:
        return {'show': False, 'available': shell is not None, 'ours': [], 'old': []}
    found = scan(shell, exe)
    have = any(x['where'] == 'desktop' for x in found['ours'])
    return {'show': not have and not declined(local_root, exe), 'available': True,
            'ours': [x['path'] for x in found['ours']], 'old': [x['path'] for x in found['old']]}
