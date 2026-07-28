from __future__ import annotations
import os
from pathlib import Path

# BOX上へ__pycache__を書き込まず、ユーザー別のローカル領域へ永続配置する。
_local_root = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or Path.home()) / "SymfoNaviDataHub"
_pycache = _local_root / "pycache"
_pycache.mkdir(parents=True, exist_ok=True)
os.environ["NAVI_LOCAL_ROOT"] = str(_local_root)
os.environ["PYTHONPYCACHEPREFIX"] = str(_pycache)
os.environ["PYTHONDONTWRITEBYTECODE"] = "0"

from launch_guard import main
if __name__ == '__main__':
    raise SystemExit(main())
