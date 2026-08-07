from __future__ import annotations
import json, os, sys, traceback
from pathlib import Path

_local_root=Path(os.environ.get('NAVI_LOCAL_ROOT') or os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home()/'SymfoNaviDataHub')
os.environ['NAVI_LOCAL_ROOT']=str(_local_root)
os.environ['PYTHONPYCACHEPREFIX']=str(_local_root/'pycache')
os.environ['PYTHONDONTWRITEBYTECODE']='0'
# appの取り込み前に立てる必要がある。ワーカーは抽出処理だけを行うためHTTP層(Flask)を読み込まない。
os.environ['NAVI_WORKER_MODE']='1'

def atomic_json(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(tmp,p)

def main():
    payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    if payload.get('split_part'):
        # 列分割の1パート。担当外の列を外して問い合わせ、CSVへ保存するだけを行う。
        from app import process_split_part
        sp=payload['split_part']
        result=process_split_part(payload['job'],payload['cfg'],payload['user'],payload['password'],payload['server'],
                                  Path(sp['out_csv']),sp.get('drop') or [],sp.get('label') or '')
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
