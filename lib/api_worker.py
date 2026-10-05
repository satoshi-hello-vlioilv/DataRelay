from __future__ import annotations
import json, os, sys, traceback
from pathlib import Path

_local_root=Path(os.environ.get('NAVI_LOCAL_ROOT') or os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home()/'DataRelay')
os.environ['NAVI_LOCAL_ROOT']=str(_local_root)
os.environ['PYTHONPYCACHEPREFIX']=str(_local_root/'pycache')
os.environ['PYTHONDONTWRITEBYTECODE']='0'
# appの取り込み前に立てる必要がある。ワーカーは抽出処理だけを行うためHTTP層(Flask)を読み込まない。
os.environ['NAVI_WORKER_MODE']='1'

# 本体（app.py）は1つ上、いっしょに使う部品はこの lib/ にある。
# ワーカーは別プロセスなので、探し先は自分で用意する必要がある。
_here=Path(__file__).resolve().parent
sys.path.insert(0,str(_here))
sys.path.insert(0,str(_here.parent))

def atomic_json(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(tmp,p)

def login(payload):
    """Navigator への (利用者ID, パスワード, サーバー)。パスワードは payload.json に書かない（1.99.0。これまでは
    平文で一時ファイルに書いていた）。ワーカーは本体と同じ利用者で動くので、同じ置き場から自分で読む。"""
    from app import navi_login
    user,pw,server,_=navi_login(payload.get('cfg'))
    return user,pw,server

def main():
    payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    if 'user' in payload:
        payload['user'],payload['password'],payload['server']=login(payload)
    if payload.get('diag'):
        # DLLの診断。読み込み(LoadLibrary)そのものが落ちることがあるので、ここに閉じ込める。
        from app import process_api_diag
        result=process_api_diag(payload['cfg'])
        atomic_json(os.environ['NAVI_WORKER_RESULT'],result)
        return 0 if result.get('ok') else 2
    if payload.get('inspect'):
        # RNEの読み取り。DLL側で落ちても本体プロセスを巻き込まないよう、ここに閉じ込める。
        from app import process_catalog_inspect
        result=process_catalog_inspect(payload['job'],payload['cfg'],payload['user'],payload['password'],
                                       payload['server'],payload['inspect'].get('want'))
        atomic_json(os.environ['NAVI_WORKER_RESULT'],result)
        return 0 if result.get('ok') else 2
    if payload.get('split_part'):
        # 分割の1パート。担当外の列を外し、担当する行だけに絞って問い合わせ、CSVへ保存する。
        from app import process_split_part
        sp=payload['split_part']
        result=process_split_part(payload['job'],payload['cfg'],payload['user'],payload['password'],payload['server'],
                                  Path(sp['out_csv']),sp.get('drop') or [],sp.get('label') or '',sp.get('row'),
                                  sp.get('row_axis'))
        atomic_json(os.environ['NAVI_WORKER_RESULT'],result)
        return 0 if result.get('ok') else 2
    from app import process_api_parallel_job
    result=process_api_parallel_job(payload['job'],payload['job_index'],payload['total_jobs'],payload['cfg'],payload['user'],payload['password'],payload['server'],Path(payload['dde_work']),Path(payload['backup']))
    atomic_json(os.environ['NAVI_WORKER_RESULT'],result)
    return 0 if result.get('ok') else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except SystemExit:raise
    except Exception as e:
        atomic_json(os.environ.get('NAVI_WORKER_RESULT','worker_result.json'),{'ok':False,'job':'','error':str(e),'traceback':traceback.format_exc()})
        raise
