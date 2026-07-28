from __future__ import annotations
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:5031'
# VBSランチャーが起動待ちモーダル(loading.html)を開き、準備完了で自動的にアプリへ遷移する。
# その場合はサーバー側でブラウザーを二重に開かない（NAVI_BROWSER_BY_VBS=1 で抑止）。
BROWSER_BY_VBS = os.environ.get('NAVI_BROWSER_BY_VBS') == '1'
LOCAL_ROOT = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home()) / 'SymfoNaviDataHub'
RUNTIME = LOCAL_ROOT / 'runtime'
INFO = RUNTIME / 'app_instance.json'
LOG = LOCAL_ROOT / 'logs' / 'launcher.log'
MUTEX_NAME = 'Local\\SymfoNaviDataHub_' + hashlib.sha256(str(BASE).lower().encode('utf-8')).hexdigest()[:20]
ERROR_ALREADY_EXISTS = 183
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
DETACHED_PROCESS = 0x00000008 if os.name == 'nt' else 0

def log(message: str) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')

def probe(timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(URL + '/api/instance', timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
            return r.status == 200 and data.get('app') in ('SymfoNaviDataHub','NaviToSQLite')
    except Exception:
        return False

def open_browser_best_effort() -> bool:
    """既定ブラウザーを複数方式で呼び出す。Falseを成功扱いしない。"""
    methods = [('webbrowser', lambda: webbrowser.open(URL, new=1, autoraise=True))]
    if os.name == 'nt':
        methods.extend([
            ('os.startfile', lambda: (os.startfile(URL), True)[1]),  # type: ignore[attr-defined]
            ('cmd-start', lambda: subprocess.Popen(['cmd', '/d', '/c', 'start', '', URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)),
            ('powershell', lambda: subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-Command', 'Start-Process', URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)),
        ])
    for name, method in methods:
        try:
            result = method()
            accepted = bool(result) or isinstance(result, subprocess.Popen)
            log(f'ブラウザー起動要求 method={name} accepted={accepted} result={result}')
            if accepted:
                return True
        except Exception as e:
            log(f'ブラウザー起動要求失敗 method={name} error={e}')
    log('ブラウザー起動要求は全方式で失敗しました。サーバーは起動済みです。URL=' + URL)
    return False


def write_info(launcher_pid: int, python_pid: int | None = None) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    payload = {
        'launcher_pid': launcher_pid,
        'python_pid': python_pid,
        'app_path': str(BASE),
        'url': URL,
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    INFO.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

def spawn_app() -> subprocess.Popen:
    env = os.environ.copy()
    env['NAVI_LAUNCHED_BY_GUARD'] = '1'
    env['NAVI_LOCAL_ROOT'] = str(LOCAL_ROOT)
    env['PYTHONPYCACHEPREFIX'] = str(LOCAL_ROOT / 'pycache')
    # 起動計測用: サーバープロセス(app.py)へ生成時刻(wall clock)を渡し、
    # インタプリタ初期化＋モジュール取り込み＋app.pyコンパイルの所要時間を app.py 側で計測する。
    env['NAVI_APP_SPAWN_AT'] = repr(time.time())
    flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    return subprocess.Popen(
        [sys.executable, str(BASE / 'app.py')],
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=False,
        creationflags=flags,
    )

def main() -> int:
    if os.name != 'nt':
        print('このランチャーはWindows用です。')
        return 2
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError()
    already = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    server_ready = False
    proc: subprocess.Popen | None = None
    try:
        if already:
            for _ in range(30):
                if probe():
                    log('既存インスタンスを検出。新規起動せず既存画面を開きます。')
                    if not BROWSER_BY_VBS:
                        open_browser_best_effort()
                    return 0
                time.sleep(0.25)
            log('多重起動ロックは存在しますが既存サーバーが応答しません。起動を中止します。')
            print('既存の起動処理が残っています。タスクマネージャーでこのアプリのPythonを終了するか、停止バッチを実行してください。')
            return 2
        if probe():
            log('既存サーバー応答あり。新規起動せず既存画面を開きます。')
            if not BROWSER_BY_VBS:
                open_browser_best_effort()
            return 0
        write_info(os.getpid(), None)
        log(f'新規インスタンス起動 launcher_pid={os.getpid()}')
        proc = spawn_app()
        write_info(os.getpid(), proc.pid)
        log(f'アプリサーバープロセス起動 python_pid={proc.pid}')
        spawn_started = time.perf_counter()
        for _ in range(160):
            if probe():
                server_ready = True
                # サーバー起動完了までの実測秒。初回・アップデート時・BOX影響の切り分けに使用する。
                log('アプリサーバー応答確認。ランチャーは終了し、サーバーは継続稼働します。'
                    f' server_ready_elapsed={time.perf_counter() - spawn_started:.2f}s')
                if not BROWSER_BY_VBS:
                    open_browser_best_effort()
                return 0
            if proc.poll() is not None:
                log(f'アプリサーバーが起動前に終了 returncode={proc.returncode}')
                break
            time.sleep(0.25)
        print('アプリサーバーの起動を確認できませんでした。%LOCALAPPDATA%\\SymfoNaviDataHub\\logs\\launcher.log と app.log を確認してください。')
        return 2
    finally:
        if not server_ready:
            try:
                INFO.unlink()
            except OSError:
                pass
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)

if __name__ == '__main__':
    raise SystemExit(main())
