from __future__ import annotations
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
HOST = '127.0.0.1'
PORT = 5031
URL = f'http://{HOST}:{PORT}'
# VBSランチャーが起動待ちモーダル(loading.html)を開き、準備完了で自動的にアプリへ遷移する。
# その場合はサーバー側でブラウザーを二重に開かない（NAVI_BROWSER_BY_VBS=1 で抑止）。
BROWSER_BY_VBS = os.environ.get('NAVI_BROWSER_BY_VBS') == '1'
APP_NAME = 'DataRelay'
LEGACY_LOCAL_NAMES = ('SymfoNaviDataHub', 'NaviToSQLite')
LOCAL_ROOT = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home()) / APP_NAME
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from navi_paths import migrate_local_root
    migrate_local_root(LOCAL_ROOT, LEGACY_LOCAL_NAMES)
except Exception:
    pass
RUNTIME = LOCAL_ROOT / 'runtime'
INFO = RUNTIME / 'app_instance.json'
LOG = LOCAL_ROOT / 'logs' / 'launcher.log'
MUTEX_NAME = 'Local\\' + APP_NAME + '_' + hashlib.sha256(str(BASE).lower().encode('utf-8')).hexdigest()[:20]
ERROR_ALREADY_EXISTS = 183
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
DETACHED_PROCESS = 0x00000008 if os.name == 'nt' else 0

def log(message: str) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')

APP_NAMES = ('DataRelay', 'SymfoNaviDataHub', 'NaviToSQLite')
_OPENER = None
probe_error = ''

def direct_opener():
    """自分自身への問い合わせを、社内プロキシへ回させないための口。

    urllib は Windows のインターネットオプション（レジストリ）のプロキシ設定を読む。
    例外一覧に 127.0.0.1 が入っていない端末では、自分自身への問い合わせまでプロキシへ
    送られ、必ず失敗する。VBS 側の確認は MSXML2.ServerXMLHTTP を使っていてこの設定を
    読まないので、同じPCの同じ瞬間に「VBSは応答あり／Pythonは応答なし」という食い違いが
    起きる（実測: vbs_launcher.log は SERVER_READY、launcher.log は確認できず）。
    ProxyHandler({}) を明示して、この経路だけは必ず直に出す。
    """
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _OPENER

def probe(timeout: float = 0.8) -> bool:
    global probe_error
    try:
        with direct_opener().open(URL + '/api/instance', timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
            if r.status == 200 and data.get('app') in APP_NAMES:
                probe_error = ''
                return True
            probe_error = f'status={r.status} app={data.get("app")!r}'
            return False
    except Exception as e:
        # 理由を握りつぶすと「なぜ確認できないのか」が二度と分からない。最後の1件だけ残す。
        probe_error = f'{type(e).__name__}: {e}'
        return False

def port_listening(timeout: float = 0.5) -> bool:
    """5031番で誰かが待ち受けているか。HTTPクライアントの設定に一切左右されない。

    「応答を確認できない」と「動いていない」は別物。止めてよいかを決めるのはこちら。
    """
    import socket
    try:
        with socket.create_connection((HOST, PORT), timeout):
            return True
    except OSError:
        return False

def open_browser_best_effort() -> bool:
    """既定ブラウザーを複数方式で呼び出す。Falseを成功扱いしない。"""
    # 起動待ちモーダルが開いている通常の経路では、ここは一度も通らない。
    # 取り込みもそのときまで遅らせる（起動のたびに払う理由が無い）。
    import webbrowser
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

def crash_log_handle():
    """サーバープロセスの標準エラーの行き先。

    これまで DEVNULL へ捨てていた。落ちた理由（Pythonの例外・DLLの異常終了）が
    そこにしか出ないことがあり、捨てていると「消えた」としか分からなくなる。
    追記で開いて残す ―― 落ちなければ何も書かれないので、増え続けることはない。
    """
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        return open(LOG.parent / 'stderr.log', 'ab')
    except Exception:
        return subprocess.DEVNULL

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
        stderr=crash_log_handle(),
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
    spawned = False
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
            if port_listening():
                log('既存サーバーはHTTPで確認できませんが ' + URL + ' で待ち受けています。'
                    f'既存インスタンスとして扱います。 last_probe_error={probe_error}')
                if not BROWSER_BY_VBS:
                    open_browser_best_effort()
                return 0
            log('多重起動ロックは存在しますが既存サーバーが応答しません。起動を中止します。'
                f' last_probe_error={probe_error}')
            print('既存の起動処理が残っています。タスクマネージャーでこのアプリのPythonを終了するか、停止バッチを実行してください。')
            return 2
        if probe():
            log('既存サーバー応答あり。新規起動せず既存画面を開きます。')
            if not BROWSER_BY_VBS:
                open_browser_best_effort()
            return 0
        write_info(os.getpid(), None)
        log(f'新規インスタンス起動 launcher_pid={os.getpid()}')
        proc = spawn_app(); spawned = True
        write_info(os.getpid(), proc.pid)
        log(f'アプリサーバープロセス起動 python_pid={proc.pid}')
        spawn_started = time.perf_counter()
        # 0.25秒の等間隔で聞き直していたので、立ち上がってから気づくまで平均0.12秒
        # 待っていた。相手は同じPCの中なので、立ち上がりそうな最初のうちは細かく聞く。
        while time.perf_counter() - spawn_started < 40:
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
            time.sleep(0.05 if time.perf_counter() - spawn_started < 4 else 0.25)
        # ここで無条件に停止していた（1.90.0〜1.92.0）。そのため、実際には動いている
        # サーバーを起動40秒後に必ず殺していた ―― 画面には「サーバーとの接続が切れました」
        # とだけ出るので、アプリが突然落ちたようにしか見えない。
        # 「応答を確認できない」と「動いていない」は別物。止める前に待ち受けを直接見る。
        if proc is not None and proc.poll() is None and port_listening():
            server_ready = True
            log('HTTPでの起動確認はできませんでしたが、' + URL + ' で待ち受けています。'
                'サーバーは動いているので停止しません。'
                f' last_probe_error={probe_error}')
            if not BROWSER_BY_VBS:
                open_browser_best_effort()
            return 0
        # 待ち受けも無い＝本当に立ち上がっていない。置き去りにすると、誰も知らないプロセスが
        # ポートを掴んだまま残る（次の起動もできなくなる）ので、ここでだけ片付ける。
        if proc is not None and proc.poll() is None:
            log('起動確認できないまま制限時間に達しました（待ち受けもありません）。'
                f'起こしたサーバーを停止します。 last_probe_error={probe_error}')
            try:
                proc.terminate(); proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        print('アプリサーバーの起動を確認できませんでした。%LOCALAPPDATA%\\'+APP_NAME+'\\logs\\launcher.log と app.log を確認してください。')
        return 2
    finally:
        # 消してよいのは「自分が起こして、しかも起動を確認できなかった」ときだけ。
        # 既存インスタンスを見つけて戻る道でも消していたため、動いているアプリの
        # app_instance.json が失われ、停止バッチがPIDを見つけられなくなっていた
        # （それでも「停止処理が完了しました」とだけ出る）。
        if spawned and not server_ready:
            try:
                INFO.unlink()
            except OSError:
                pass
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)

if __name__ == '__main__':
    raise SystemExit(main())
