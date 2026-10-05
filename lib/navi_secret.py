"""Navigator への接続情報を、このPCの利用者だけが読める場所に置く（1.99.0）。

これまでは接続先・利用者ID・パスワードを symnavim.conf（平文の INI）に書き、アプリのフォルダー（共有・BOX）に
置いていた。共有に置けば読める人すべてにパスワードが見え、配る zip に入れることもできない。

置き場は Windows の「資格情報マネージャー」（汎用資格情報）。中身は Windows が利用者ごとに暗号化して持つ
（DPAPI）。同じPCの別の利用者・別のPCからは読めず、利用者はコントロール パネルの「資格情報マネージャー」で
見る・消すことができる。アプリの中身（Python）も抽出ワーカーも同じ利用者で動くので、どちらからでも読める。

ここは置き場と、symnavim.conf の読み方（取り込みと、まだ取り込んでいないPCの読み手）だけを持つ。
画面・設定・時計は触らない ―― Windows 以外ではファイルの置き場（FileVault）に替えて、実機なしで確かめる。
"""
from __future__ import annotations

import configparser
import json
import os
import sys
import time
from pathlib import Path

TARGET = 'DataRelay/Navigator'          # 資格情報マネージャーでの名前（ここで探せば見つかる）
BLOB_LIMIT = 5 * 512                    # 汎用資格情報の中身の上限（CRED_MAX_CREDENTIAL_BLOB_SIZE）
DECLINED_FILE = 'login_declined.json'   # 「Navigator を使わない」と答えたこと（このPC・利用者ごと）

# 追加のデータソース（symnavim.conf の [ApiOracle] などのセクション）。名前の綴りの揺れは英数字だけで比べる。
PROFILE_KINDS = {'apioracle': 'oracle', 'apisqlserver': 'sqlserver', 'apirda': 'rda', 'apipostgres': 'postgres',
                 'apiresource': 'resource', 'apiresourcenoauth': 'noauth'}
PROFILE_FIELDS = ('section', 'kind', 'user', 'password', 'server', 'option', 'resource', 'resource_kind')


# ==== symnavim.conf の読み方（取り込みと、まだ取り込んでいないPCの読み手が同じものを使う） ====
def _parser(text):
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str.lower
    cp.read_string(text)
    return cp


def read_conf_text(path):
    """symnavim.conf を文字列で読む。CP932 / UTF-8 のどちらでも読める（現場には両方ある）。"""
    raw = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError('symnavim.conf の文字コードを読めません（CP932 か UTF-8 で保存してください）')


def parse_conf(text):
    """symnavim.conf の中身を、置き場に入れる形 {server, user, password, section, profiles} にする。

    使うセクションは [Default]、無ければ Connect_ で始まる最初のもの、それも無ければ先頭（これまでの creds() と同じ）。
    追加のデータソースは、明示されたセクションだけを読む（enabled=no は外す）。"""
    try:
        cp = _parser(text)
    except configparser.Error as e:
        raise ValueError(f'symnavim.conf の書き方を読めません: {e}') from e
    if not cp.sections():
        raise ValueError('symnavim.confを読み取れません')
    sec = 'Default' if cp.has_section('Default') else next(
        (x for x in cp.sections() if x.lower().startswith('connect_')), cp.sections()[0])
    d = {k.lower(): v.strip() for k, v in cp.items(sec)}
    out = {'server': d.get('symnaviserver', ''), 'user': d.get('symnaviuserid', ''),
           'password': d.get('symnavipasswd', ''), 'section': sec, 'profiles': []}
    if not (out['server'] and out['user'] and out['password']):
        raise ValueError(f'[{sec}]にSymNaviUSERID、SymNaviPASSWD、SymNaviServerが必要です')
    for section in cp.sections():
        kind = PROFILE_KINDS.get(''.join(ch for ch in section.lower() if ch.isalnum()))
        if not kind:
            continue
        p = {k.lower(): v.strip() for k, v in cp.items(section)}
        if str(p.get('enabled', 'yes')).lower() in ('0', 'no', 'false', 'off'):
            continue
        out['profiles'].append({'section': section, 'kind': kind, 'user': p.get('user', p.get('userid', '')),
                                'password': p.get('password', p.get('passwd', '')), 'server': p.get('server', ''),
                                'option': p.get('option', p.get('opt', '')),
                                'resource': p.get('resource', p.get('resourcename', '')),
                                'resource_kind': p.get('resource_kind', p.get('resourcekind', '0'))})
    return out


def read_conf(path):
    return parse_conf(read_conf_text(path))


# ==== 置き場に入れる形 ====
def clean(data):
    """画面や取り込みから来た値を、置き場に入れる形へそろえる。足りなければ理由を添えて断る。"""
    if not isinstance(data, dict):
        raise ValueError('接続情報の形が正しくありません')
    out = {k: str(data.get(k) or '').strip() for k in ('server', 'user', 'password')}
    missing = [w for k, w in (('server', 'サーバー'), ('user', '利用者ID'), ('password', 'パスワード')) if not out[k]]
    if missing:
        raise ValueError('、'.join(missing) + 'を入れてください')
    out['section'] = str(data.get('section') or '').strip()
    profiles = []
    for p in data.get('profiles') or []:
        if not isinstance(p, dict) or p.get('kind') not in PROFILE_KINDS.values():
            continue
        profiles.append({k: str(p.get(k) or '').strip() for k in PROFILE_FIELDS})
    out['profiles'] = profiles
    return out


def merge(old, new):
    """画面から直すとき、パスワードを空のまま送れば前のものを使う（サーバーだけ直すのに打ち直させない）。"""
    new = dict(new or {})
    if old and not str(new.get('password') or '').strip() and str(new.get('user') or '').strip() == old.get('user'):
        new['password'] = old.get('password', '')
    if old and 'profiles' not in new:
        new['profiles'] = old.get('profiles') or []
    return new


def public(data):
    """画面へ返す形。パスワードは返さない（入っているかどうかだけ）。利用者IDは秘密ではないので出す。"""
    if not data:
        return {'saved': False}
    return {'saved': True, 'server': data.get('server', ''), 'user': data.get('user', ''),
            'has_password': bool(data.get('password')), 'section': data.get('section', ''),
            'profiles': [{'section': p.get('section', ''), 'kind': p.get('kind', ''), 'server': p.get('server', '')}
                         for p in data.get('profiles') or []],
            'saved_at': data.get('saved_at', ''), 'origin': data.get('origin', '')}


def encode(data):
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(blob) > BLOB_LIMIT:
        raise ValueError(f'接続情報が長すぎて保存できません（{len(blob)} バイト。上限 {BLOB_LIMIT} バイト）。'
                         '追加のデータソースを減らしてください')
    return blob


def stamp(data, source):
    return dict(data, saved_at=time.strftime('%Y-%m-%dT%H:%M:%S'), origin=source)


# ==== 置き場 ====
class WindowsVault:
    """Windows の資格情報マネージャー（汎用資格情報・このPCに限る）。advapi32 を ctypes で直に呼ぶ ――
    pywin32 の CredWrite は中身を文字列で渡すと UTF-16 に直すかどうかが版で揺れるので、バイト列を自分で決める。"""
    kind = 'windows'
    label = 'Windows の資格情報マネージャー'

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2      # このPCだけ（移動プロファイルで別のPCへ持ち出さない）
    ERROR_NOT_FOUND = 1168

    def __init__(self, target=TARGET):
        import ctypes
        from ctypes import wintypes
        self.target = target
        self._c = ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [('dwLowDateTime', wintypes.DWORD), ('dwHighDateTime', wintypes.DWORD)]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                        ('Comment', wintypes.LPWSTR), ('LastWritten', FILETIME),
                        ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                        ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
                        ('UserName', wintypes.LPWSTR)]

        self._CREDENTIAL = CREDENTIAL
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        self._write = adv.CredWriteW
        self._write.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        self._write.restype = wintypes.BOOL
        self._read = adv.CredReadW
        self._read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        self._read.restype = wintypes.BOOL
        self._delete = adv.CredDeleteW
        self._delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._delete.restype = wintypes.BOOL
        self._free = adv.CredFree
        self._free.argtypes = [ctypes.c_void_p]
        self._free.restype = None

    @property
    def where(self):
        return f'{self.label}（汎用資格情報「{self.target}」）'

    def _fail(self, what):
        code = self._c.get_last_error()
        raise OSError(code, f'{what}に失敗しました（Windows のエラー {code}: {self._c.FormatError(code).strip()}）')

    def load(self):
        c = self._c
        ptr = c.POINTER(self._CREDENTIAL)()
        if not self._read(self.target, self.CRED_TYPE_GENERIC, 0, c.byref(ptr)):
            if c.get_last_error() == self.ERROR_NOT_FOUND:
                return None
            self._fail('資格情報の読み取り')
        try:
            cred = ptr.contents
            blob = c.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            self._free(ptr)
        return json.loads(blob.decode('utf-8'))

    def save(self, data):
        c = self._c
        blob = encode(data)
        buf = (c.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self._CREDENTIAL()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = self.target
        cred.Comment = 'DataRelay: Navigator への接続情報（アプリの画面から登録・変更します）'
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = c.cast(buf, c.POINTER(c.c_ubyte))
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = str(data.get('user') or '')
        if not self._write(c.byref(cred), 0):
            self._fail('資格情報の保存')

    def delete(self):
        if not self._delete(self.target, self.CRED_TYPE_GENERIC, 0):
            if self._c.get_last_error() == self.ERROR_NOT_FOUND:
                return False
            self._fail('資格情報の削除')
        return True


class FileVault:
    """ファイルの置き場（Windows 以外・試験用）。暗号化はしない ―― 持ち主だけが読める権限（0600）にするだけ。
    Windows では使わない（NAVI_SECRET_FILE で試験から明示したときだけ）。"""
    kind = 'file'
    label = '利用者のフォルダーのファイル（暗号化なし・試験用）'

    def __init__(self, path):
        self.path = Path(path)

    @property
    def where(self):
        return f'{self.label}: {self.path}'

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None

    def save(self, data):
        blob = encode(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(blob)
        os.replace(tmp, self.path)

    def delete(self):
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


def default_vault(local_root):
    """このPCでの置き場。試験は NAVI_SECRET_FILE でファイルへ向ける（CI の資格情報マネージャーを汚さない）。"""
    override = os.environ.get('NAVI_SECRET_FILE')
    if override:
        return FileVault(override)
    if sys.platform == 'win32':
        return WindowsVault()
    return FileVault(Path(local_root) / 'secrets' / 'navigator.json')


# ==== 「Navigator を使わない」と答えたこと（初めて開いたときの問いを繰り返さない） ====
def _declined_path(local_root):
    return Path(local_root) / 'runtime' / DECLINED_FILE


def declined(local_root):
    return _declined_path(local_root).is_file()


def decline(local_root, yes=True):
    p = _declined_path(local_root)
    if not yes:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'declined_at': time.strftime('%Y-%m-%dT%H:%M:%S')}), encoding='utf-8')
