"""起動アイコン（デスクトップとスタートメニューの .lnk）を、このPCの写しへ向ける（1.98.0）。

配布の置き場から写したPC（窓が config\\install.json を書いたアプリ）では、起動の入口はこのPCの
<写し>\\DataRelay.exe になる。デスクトップにそこを指すアイコンが無ければ、画面が「作りますか」と聞く
（勝手に作らない。断ったら同じ exe については聞き直さない）。

前からあるアイコン（共有の DataRelay.exe・install_local.cmd が置いた %LOCALAPPDATA%\\DataRelay\\bin\\DataRelay.exe を
指すもの）は、作る代わりに**向け直す**（名前と置き場所は利用者のもののまま。同じアイコンが2つ並ばない）。
アイコンは名前ではなく**行き先**で見分ける（利用者が名前を変えていても見つける）。行き先の名前が DataRelay.exe の
ものだけを DataRelay のアイコンとみなす。

.lnk はシェルのオブジェクトなので、Windows の部品（WScript.Shell・pywin32 の COM）で作る・読む。
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
    """WScript.Shell を通してシェルのフォルダーと .lnk を扱う（Windows だけ）。"""

    def __init__(self):
        import pythoncom                       # pywin32（config\requirements.txt）
        import win32com.client
        # 画面の問い合わせは別の糸で答える。COM はその糸ごとに初期化が要る（無いと「CoInitialize が呼ばれていない」で断られる）。
        # 同じ糸で何度呼んでもよい
        pythoncom.CoInitialize()
        self.sh = win32com.client.Dispatch('WScript.Shell')

    def folder(self, kind):
        """'desktop'／'programs'（スタートメニューのプログラム）。OneDrive へ移したデスクトップも正しく返る。"""
        return Path(self.sh.SpecialFolders({'desktop': 'Desktop', 'programs': 'Programs'}[kind]))

    def target(self, link):
        try:
            return str(self.sh.CreateShortcut(str(link)).TargetPath or '')
        except Exception:
            return ''

    def make(self, link, target, workdir, description):
        sc = self.sh.CreateShortcut(str(link))
        sc.TargetPath = str(target)
        sc.WorkingDirectory = str(workdir)
        sc.IconLocation = '%s,0' % target
        sc.Description = description
        sc.Save()


def available():
    """このPCで .lnk を扱えるか（Windows で pywin32 が読める）。"""
    if os.name != 'nt':
        return False
    try:
        import win32com.client  # noqa: F401
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


def ensure(shell, exe):
    """アイコンをこのPCの写しへ向ける。前からある DataRelay のアイコンは向け直し、デスクトップに無ければ作る。
    → {'made': [...], 'retargeted': [...], 'errors': [...]}"""
    exe = Path(exe)
    found = scan(shell, exe)
    out = {'made': [], 'retargeted': [], 'errors': []}
    for item in found['old']:
        try:
            shell.make(item['path'], exe, exe.parent, DESCRIPTION)
            out['retargeted'].append(item['path'])
        except Exception as e:
            out['errors'].append('%s: %s' % (item['path'], e))
    on_desktop = any(x['where'] == 'desktop' for x in found['ours'] + found['old'])
    if not on_desktop:
        try:
            link = free_name(shell.folder('desktop'))
            shell.make(link, exe, exe.parent, DESCRIPTION)
            out['made'].append(str(link))
        except Exception as e:
            out['errors'].append('デスクトップ: %s' % e)
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


def offer(shell, exe, local_root, installed):
    """画面が「作りますか」と聞くか。聞くのは: 配布から写したアプリ・デスクトップに写しを指すアイコンが無い・断っていない。"""
    if not installed or shell is None:
        return {'show': False, 'available': shell is not None, 'ours': [], 'old': []}
    found = scan(shell, exe)
    have = any(x['where'] == 'desktop' for x in found['ours'])
    return {'show': not have and not declined(local_root, exe), 'available': True,
            'ours': [x['path'] for x in found['ours']], 'old': [x['path'] for x in found['old']]}
