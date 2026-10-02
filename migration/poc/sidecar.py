# -*- coding: utf-8 -*-
"""【検証用の試作】デスクトップ版（Tauri）の窓口: 標準入出力でアプリへ問い合わせる。ポートを開かない。

実行では使わない。移行の可否を確かめるためのもの（migration/FEASIBILITY.md の「検証1」）。
Defect-Pitch-Analyzer の program/sidecar.py（版 2.0.0）と同じ枠の形にしてある。Rust 側も同じ形で読み書きする。

枠の形（両方向とも同じ。テキストの行と生のバイトを混ぜる）:
    ヘッダー: JSON 1行（UTF-8・改行で終わる）。"len" が本文のバイト数
    本文    : len バイトそのまま（base64 にしない。大きな一覧・ZIP・XLSXでも膨らませない）
  問い合わせ {"id", "method", "path", "query", "headers": {名前: 値}, "len"}
  答え       {"id", "status", "headers": [[名前, 値], ...], "len"}
  知らせ     {"id": 0, "event": "ready" | "fatal", ...}（id 0 は問い合わせに使わない）

DataRelay の本体（app.py の Flask）はそのまま WSGI として呼ぶ。画面・ルート・試験はいまと同じものを使う。
抽出のワーカー（lib/api_worker.py）はこのプロセスの子として起動される。子の標準出力は fd 1 を
標準エラーへ向け直してあるので、子が print しても枠には混ざらない。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # migration/poc/ の2つ上 ＝ アプリのフォルダ
BASE_URL = 'http://datarelay.localhost/'            # Tauri（WebView2）が自前の仕組みに付ける名前に合わせる
WORKERS = 16                                        # 長い問い合わせ（RNEの調査など）の間も、進み具合の確認に答える


def read_frame(stream):
    """→ (ヘッダー dict, 本文 bytes)。入力が閉じたら None。"""
    line = stream.readline()
    if not line:
        return None
    head = json.loads(line.decode('utf-8'))
    n = int(head.get('len') or 0)
    body = stream.read(n) if n else b''
    if len(body) != n:
        return None
    return head, body


class Writer:
    """答えを書く係（複数の糸から呼ばれても、1つの枠を混ぜずに書く）。"""

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()

    def send(self, head: dict, body: bytes = b'') -> None:
        line = json.dumps({**head, 'len': len(body)}, ensure_ascii=False).encode('utf-8') + b'\n'
        with self.lock:
            self.stream.write(line + body)
            self.stream.flush()


def handle(app, head: dict, body: bytes):
    """問い合わせ → (答えのヘッダー, 本文)。アプリの中で何が起きても答えは返す。"""
    from werkzeug.test import EnvironBuilder, run_wsgi_app
    rid = head.get('id')
    try:
        env = EnvironBuilder(path=head.get('path') or '/', base_url=BASE_URL, query_string=head.get('query') or '',
                             method=(head.get('method') or 'GET').upper(),
                             headers=list((head.get('headers') or {}).items()), data=body).get_environ()
        app_iter, status, headers = run_wsgi_app(app, env, buffered=True)
        try:
            out = b''.join(app_iter)
        finally:
            getattr(app_iter, 'close', lambda: None)()
        return {'id': rid, 'status': int(str(status).split()[0]),
                'headers': [[k, v] for k, v in headers.items() if k.lower() != 'content-length']}, out
    except Exception as e:
        msg = json.dumps({'error': f'問い合わせを処理できませんでした: {e}', 'type': type(e).__name__},
                         ensure_ascii=False).encode('utf-8')
        return {'id': rid, 'status': 500, 'headers': [['Content-Type', 'application/json']]}, msg


def serve(app, rin, writer: Writer, workers: int = WORKERS) -> None:
    def one(head, body):
        h, b = handle(app, head, body)
        writer.send(h, b)

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='sidecar')
    try:
        while True:
            try:
                frame = read_frame(rin)
            except (ValueError, UnicodeDecodeError) as e:   # 壊れた枠。答える先（id）が分からないので知らせて続ける
                writer.send({'id': 0, 'event': 'bad-frame', 'error': str(e)})
                continue
            if frame is None:
                break
            pool.submit(one, *frame)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def protocol_streams():
    """枠を通す入出力。fd 1 は標準エラーへ向け直す（本体・子プロセスの print が枠に混ざらない）。"""
    rin = sys.stdin.buffer
    out = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    try:
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        pass
    sys.stdout = sys.stderr
    return rin, Writer(out)


def main() -> int:
    started = time.perf_counter()
    rin, writer = protocol_streams()
    try:
        sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]
        import app as datarelay
    except Exception as e:
        writer.send({'id': 0, 'event': 'fatal', 'error': f'{type(e).__name__}: {e}'})
        return 1
    writer.send({'id': 0, 'event': 'ready', 'version': datarelay.APP_VERSION, 'pid': os.getpid(),
                 'python': sys.executable, 'elapsed': round(time.perf_counter() - started, 3)})
    serve(datarelay.app, rin, writer)
    os._exit(0)


if __name__ == '__main__':
    raise SystemExit(main())
