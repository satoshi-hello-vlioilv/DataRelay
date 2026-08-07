from __future__ import annotations
import ctypes, os, re, shutil, struct, time
from pathlib import Path

NAVI_OK=0
NAVI_ERROR=0x1
NAVI_DOWNLOADNOW=0
NAVI_DOWNLOADLATER=0x1
NAVI_EOD=0x2
NAVI_CSV=1
NAVI_TXT=2
NAVI_XLSX=5
NAVI_XLS=9
NAVI_NOCHANGE=16
NAVI_NONREPEAT=8
NAVI_DBMS_ANYDB=8
# 期間指定の方法（時間型管理ポイントの変更で使用）
NAVI_MONTH=0   # 月度の期間指定 (fromTime/toTime は YYYYMM00)
NAVI_YMD=1     # 年月日の期間指定 (fromTime/toTime は YYYYMMDD)
# 管理ポイント・データ項目の位置情報
NAVI_ALL=0x1C
NAVI_SIDE=0x1
NAVI_HEAD=0x2
NAVI_COND=0x3
NAVI_DATA=0x4
NAVI_IN_DISP=0x0
NAVI_LABEL=0x0
# 管理ポイントの種類（NaviGetControlPointType）
NAVI_CONTROLPOINT_MASTER=0x1
NAVI_CONTROLPOINT_ALLVALUE=0x2
NAVI_CONTROLPOINT_CATEGORY=0x3
NAVI_CONTROLPOINT_BOUND=0x4
NAVI_CONTROLPOINT_TIME=0x5
NAVI_CONTROLPOINT_TEMPLATE=0x6
NAVI_CONTROLPOINT_UNKNOWN=0x7
NAVI_CONTROLPOINT_RULE=0x8
CONTROLPOINT_TYPE_NAMES={1:'マスタ型',2:'全値型',3:'カテゴリ型',4:'範囲型',5:'時間型',6:'ユーザ定義の時間型',7:'不明な型',8:'ルール型'}
# SymNaviApi.bas（Navigator Visual Basic Interface API 9.6.0）の定数定義そのまま。
ERROR_NAMES={
 0x3:'NAVI_ERROR_SYMFOWARE',0x4:'NAVI_ERROR_ORACLE',0x5:'NAVI_ERROR_SERVERENV',0x6:'NAVI_ERROR_LOGON',
 0x7:'NAVI_ERROR_CONNECT',0x8:'NAVI_ERROR_SERVER',0x9:'NAVI_ERROR_SESSION',0xA:'NAVI_ERROR_OPEN',
 0xB:'NAVI_ERROR_CATALOG',0xC:'NAVI_ERROR_EXECMD',0xD:'NAVI_ERROR_EXECUTE',0xE:'NAVI_ERROR_DOWNLOAD',
 0xF:'NAVI_ERROR_READ',0x10:'NAVI_ERROR_SAVEDATA',0x11:'NAVI_ERROR_CONTROLPOINT',0x12:'NAVI_ERROR_DATAITEM',
 0x13:'NAVI_ERROR_TYPE',0x14:'NAVI_ERROR_CATEGORY',0x15:'NAVI_ERROR_ZERO',0x16:'NAVI_ERROR_OVER8000',
 0x17:'NAVI_ERROR_NONMATCH',0x18:'NAVI_ERROR_VALUE',0x19:'NAVI_ERROR_RECONNECT',0x1A:'NAVI_ERROR_ITEM',
 0x1B:'NAVI_ERROR_EXECUTING',0x1C:'NAVI_ERROR_SQLSERVER',0x1D:'NAVI_ERROR_INGRES',0x1E:'NAVI_ERROR_DBKIND',
 0x1F:'NAVI_ERROR_SAVE',0x20:'NAVI_ERROR_FILENOTFOUND',0x21:'NAVI_ERROR_BADPATH',0x22:'NAVI_ERROR_ACCESSDENIED',
 0x23:'NAVI_ERROR_DISKFULL',0x24:'NAVI_ERROR_SHARINGVIOLATION',0x46:'NAVI_ERROR_CANNOTUSE',
 0x67:'NAVI_ERROR_CANNOT_SAVE',0x68:'NAVI_ERROR_USEDDATAITEM',0x96:'NAVI_ERROR_NOSUPPORT',
}
# 列分割で意味を持つエラー。原因を利用者向けの言葉に置き換えるために使う。
ERROR_HINTS={
 0x68:'この列は項目間演算に使われているため削除できません',
 0x1B:'問い合わせファイルの実行中です',
 0x12:'データ項目の取得・削除に失敗しました',
 0x11:'管理ポイントの取得・削除に失敗しました',
}

def _ansi(value):
    return str(value).encode('mbcs',errors='strict')

def pe_bits(path):
    try:
        with open(path,'rb') as f:
            if f.read(2)!=b'MZ': return None
            f.seek(0x3c); off=int.from_bytes(f.read(4),'little'); f.seek(off)
            if f.read(4)!=b'PE\0\0': return None
            machine=int.from_bytes(f.read(2),'little')
        return {0x14c:32,0x8664:64,0xaa64:64}.get(machine)
    except OSError:return None

def pe_exports(path):
    """DLLがエクスポートしている関数名を返す（読み込まずにPEのエクスポート表を解析する）。

    アプリがバインドしている関数だけでは、DLLに何ができるのか分からない。
    列の選択・並べ替えなど未使用の機能が公開されているかを、実機で確かめるために使う。
    """
    try:
        with open(path,'rb') as f:data=f.read()
    except OSError:return []
    try:
        if data[:2]!=b'MZ':return []
        pe=int.from_bytes(data[0x3c:0x40],'little')
        if data[pe:pe+4]!=b'PE\0\0':return []
        sections=int.from_bytes(data[pe+6:pe+8],'little')
        opt_size=int.from_bytes(data[pe+20:pe+22],'little')
        opt=pe+24
        magic=int.from_bytes(data[opt:opt+2],'little')
        dd=opt+(96 if magic==0x10b else 112)          # DataDirectory[0] = エクスポート表
        exp_rva=int.from_bytes(data[dd:dd+4],'little')
        if not exp_rva:return []
        secs=[]
        base=pe+24+opt_size
        for i in range(sections):
            h=base+i*40
            secs.append((int.from_bytes(data[h+12:h+16],'little'),      # VirtualAddress
                         int.from_bytes(data[h+8:h+12],'little'),       # VirtualSize
                         int.from_bytes(data[h+16:h+20],'little'),      # SizeOfRawData
                         int.from_bytes(data[h+20:h+24],'little')))     # PointerToRawData
        def off(rva):
            for va,vs,rs,pr in secs:
                if va<=rva<va+max(vs,rs):return rva-va+pr
            return None
        e=off(exp_rva)
        if e is None:return []
        count=int.from_bytes(data[e+24:e+28],'little')                  # NumberOfNames
        names_rva=int.from_bytes(data[e+32:e+36],'little')              # AddressOfNames
        table=off(names_rva)
        if table is None:return []
        out=[]
        for i in range(count):
            r=int.from_bytes(data[table+i*4:table+i*4+4],'little')
            o=off(r)
            if o is None:continue
            end=data.index(b'\0',o)
            out.append(data[o:end].decode('ascii','replace'))
        return sorted(out)
    except Exception:
        return []

NAVIAP_DEPLOY_FOLDERS=('debugdllVC14','debugdllVC14x64','dllVC14','dllVC14x64')

def sync_naviap_runtime(base_dir,source_root=None):
    """Copy the four product-side NAVIAP runtime folders into Config/NAVIAP.

    All files are copied, not only SymNaviA.dll, so dependent DLLs remain beside it.
    Existing identical files are retained; newer/different files are refreshed.
    """
    src=Path(source_root or r'C:\NAVIAP')
    dst=Path(base_dir)/'Config'/'NAVIAP'
    report={'source':str(src),'target':str(dst),'copied':[],'missing':[],'errors':[]}
    if not src.is_dir():
        report['errors'].append('製品側NAVIAPフォルダーがありません: '+str(src));return report
    for name in NAVIAP_DEPLOY_FOLDERS:
        sf=src/name;df=dst/name
        if not sf.is_dir():report['missing'].append(str(sf));continue
        try:
            df.mkdir(parents=True,exist_ok=True)
            for item in sf.rglob('*'):
                if not item.is_file():continue
                rel=item.relative_to(sf);target=df/rel;target.parent.mkdir(parents=True,exist_ok=True)
                refresh=not target.exists() or item.stat().st_size!=target.stat().st_size or item.stat().st_mtime_ns>target.stat().st_mtime_ns
                if refresh:shutil.copy2(item,target);report['copied'].append(str(target))
        except Exception as e:report['errors'].append(f'{sf}: {e}')
    return report

def candidate_dlls(symnavi_exe=None,configured_path=None,extra_roots=None,local_only=False,local_root=None):
    """C:\\NAVIAPを最優先し、利用可能なローカルDLLがなければ共有側を返す。

    local_rootは検証用の差し替え口。省略時は従来どおり C:\\NAVIAP を見る。
    """
    pybits=struct.calcsize('P')*8
    local_root=Path(local_root) if local_root else Path(r'C:\NAVIAP')
    rx=re.compile(r'(debugdll|dll)vc(\d+)(x64)?$',re.I)
    local=[]
    for name in NAVIAP_DEPLOY_FOLDERS:
        local.append(local_root/name/'SymNaviA.dll')
    try:
        if local_root.is_dir():
            local.extend(x/'SymNaviA.dll' for x in local_root.iterdir() if x.is_dir() and rx.match(x.name))
    except OSError:pass
    def unique(seq):
        out=[];seen=set()
        for c in seq:
            c=Path(c);key=os.path.normcase(os.path.normpath(str(c)))
            if key not in seen:seen.add(key);out.append(c)
        return out
    local=unique(local)
    # 64/32bit一致の実在DLLがローカルにあれば、BOX側には一切触れない。
    usable=[];other=[]
    for c in local:
        try:
            if c.is_file() and pe_bits(c)==pybits:usable.append(c)
            else:other.append(c)
        except OSError:other.append(c)
    if usable or local_only:
        return usable+other
    fallback=[]
    configured=None
    if configured_path:
        cp=Path(os.path.expandvars(os.path.expanduser(str(configured_path).strip())))
        configured=cp/'SymNaviA.dll' if cp.suffix.lower()!='.dll' else cp
        fallback.append(configured)
    roots=[Path(x) for x in (extra_roots or [])]
    if configured:
        for anc in configured.parents:
            if anc.name.upper()=='NAVIAP':roots.append(anc);break
    for root in unique(roots):
        for name in NAVIAP_DEPLOY_FOLDERS:fallback.append(root/name/'SymNaviA.dll')
        try:
            if root.is_dir():fallback.extend(x/'SymNaviA.dll' for x in root.iterdir() if x.is_dir() and rx.match(x.name))
        except OSError:pass
    if symnavi_exe:
        ep=Path(symnavi_exe);fallback += [ep.parent/'SymNaviA.dll',ep.parent.parent/'bin'/'SymNaviA.dll']
    fallback.append(Path('SymNaviA.dll'))
    return local+unique(fallback)

VC_RUNTIME_DLLS=('vcruntime140.dll','msvcp140.dll','vcruntime140_1.dll')

def missing_vc_runtime():
    """このプロセスと同じbit数で読み込めないVisual C++ランタイムを返す。

    SymNaviA.dllは存在するのに読み込めない場合、原因の多くはここ。
    SymfoNaviクライアントは32bitのため、64bit側のランタイムだけ入っていない端末がある。
    vcruntime140_1.dllは64bitにしか無いので32bitでは対象にしない。
    """
    if os.name!='nt':return []
    pybits=struct.calcsize('P')*8
    out=[]
    for name in VC_RUNTIME_DLLS:
        if name=='vcruntime140_1.dll' and pybits!=64:continue
        try:ctypes.WinDLL(name)
        except OSError:out.append(name)
    return out

class NavigatorApiError(RuntimeError):
    def __init__(self,operation,rc,detail=''):
        self.operation=operation;self.rc=int(rc);self.name=ERROR_NAMES.get(int(rc),'NAVI_ERROR_UNKNOWN')
        super().__init__(f'{operation}失敗 rc=0x{int(rc):X} name={self.name} {detail}'.strip())

class NavigatorApi:
    def __init__(self,symnavi_exe=None,logger=None,dll_path=None,base_dir=None):
        if os.name!='nt':raise RuntimeError('Navigator APIはWindowsでのみ利用できます')
        self.deploy_report=None
        extra_roots=[Path(base_dir)/'Config'/'NAVIAP',Path(base_dir)/'NAVIAP'] if base_dir else []
        self.log=logger;self.dll=None;self.dll_path='';self.dll_dirs=[];errors=[]
        self.attempts=[]
        pybits=struct.calcsize('P')*8
        for candidate in candidate_dlls(symnavi_exe,dll_path,extra_roots):
            bits=pe_bits(candidate) if Path(candidate).is_file() else None
            if bits and bits!=pybits:
                msg=f'{candidate}: DLL={bits}bit / Python={pybits}bit のため対象外';errors.append(msg);self.attempts.append({'path':str(candidate),'exists':True,'dll_bits':bits,'python_bits':pybits,'result':'bit_mismatch'});continue
            cp=Path(candidate)
            # 実在しない絶対パスは読み込みを試さない。WinDLLの「Could not find module
            # (or one of its dependencies)」は不在と依存不足を区別できず、原因を誤らせる。
            if cp.is_absolute() and not cp.is_file():
                errors.append(f'{candidate}: ファイルがありません');self.attempts.append({'path':str(cp),'exists':False,'dll_bits':None,'python_bits':pybits,'result':'not_found'});continue
            try:
                if cp.is_absolute() and cp.parent.is_dir() and hasattr(os,'add_dll_directory'):
                    self.dll_dirs.append(os.add_dll_directory(str(cp.parent)))
                self.dll=ctypes.WinDLL(str(cp));self.dll_path=str(cp);self.attempts.append({'path':str(cp),'exists':cp.is_file(),'dll_bits':bits,'python_bits':pybits,'result':'loaded'});break
            except OSError as e:
                detail=str(e)
                if cp.is_file():
                    vc=missing_vc_runtime()
                    detail+=(f' / DLL自体は存在します。Visual C++ 再頒布可能パッケージ({pybits}bit)が見つかりません: '+', '.join(vc)) if vc else ' / DLL自体は存在します。同一フォルダー内の依存DLLを確認してください'
                errors.append(f'{candidate}: {detail}');self.attempts.append({'path':str(candidate),'exists':cp.is_file(),'dll_bits':bits,'python_bits':pybits,'result':'load_error','error':detail})
        if not self.dll:raise RuntimeError('SymNaviA.dllを読み込めません。設定したDLLパスと同一フォルダー内の依存DLLを確認してください。'+' | '.join(errors))
        self._bind();self.opened=False;self.catalog=0
    def _bind(self):
        # Navigator APIのInteger/Longは32bit。Windowsではc_longも32bitだが、幅の前提を残さないため
        # c_int32を明示する（仕様書の推奨に合わせた）。
        L=ctypes.c_int32; P=ctypes.POINTER(L); S=ctypes.c_char_p
        d=self.dll
        # hasattr(WinDLL,'Navi...') はエクスポートされていれば何でもTrueになるので、
        # 「アプリが実際に使っている関数」の判定には使えない。ここで明示的に記録する。
        self.bound=set()
        d.NaviOpenSession.argtypes=[P,S,S,S];d.NaviOpenSession.restype=None
        d.NaviCloseSession.argtypes=[];d.NaviCloseSession.restype=None
        d.NaviIsSessionOpened.argtypes=[];d.NaviIsSessionOpened.restype=L
        d.NaviOpenCatalog.argtypes=[P,S];d.NaviOpenCatalog.restype=L
        d.NaviCloseCatalog.argtypes=[L];d.NaviCloseCatalog.restype=None
        d.NaviExecuteCatalog.argtypes=[L,P,P,L,L];d.NaviExecuteCatalog.restype=None
        d.NaviSaveData.argtypes=[L,P,S,L,L];d.NaviSaveData.restype=None
        d.NaviGetFieldNumber.argtypes=[L,P,P];d.NaviGetFieldNumber.restype=None
        d.NaviGetRecordNumber.argtypes=[L,P,P];d.NaviGetRecordNumber.restype=None
        # 見出しだけを取りに行くための2関数（5.3.6 / 5.3.7）。1行だけ受け取って打ち切ると、
        # NaviSaveData はその分しか書き出さない。列名の取得が全件転送なしで済む。
        if hasattr(d,'NaviDownLoadData'):
            d.NaviDownLoadData.argtypes=[L,P,L,P];d.NaviDownLoadData.restype=None
        if hasattr(d,'NaviTerminateDL'):
            d.NaviTerminateDL.argtypes=[L,P];d.NaviTerminateDL.restype=None
        d.NaviGetErrorCode.argtypes=[P];d.NaviGetErrorCode.restype=None
        d.NaviGetErrorMessage.argtypes=[P,ctypes.POINTER(ctypes.c_char_p)];d.NaviGetErrorMessage.restype=None
        d.NaviConnectOracle.argtypes=[P,S,S];d.NaviConnectOracle.restype=None
        d.NaviConnectSQLServer.argtypes=[P,S,S];d.NaviConnectSQLServer.restype=None
        d.NaviConnectRDA.argtypes=[P,S,S,S];d.NaviConnectRDA.restype=None
        d.NaviConnectBaseDBMS.argtypes=[P,L,S,S,S];d.NaviConnectBaseDBMS.restype=None
        if hasattr(d,'NaviConnectResource'):
            d.NaviConnectResource.argtypes=[P,S,L,S,S,S];d.NaviConnectResource.restype=None
        if hasattr(d,'NaviConnectResourceNoAuth'):
            d.NaviConnectResourceNoAuth.argtypes=[P];d.NaviConnectResourceNoAuth.restype=None
        # 時間型管理ポイントの相対期間（動的日付）変更で使用する管理ポイント操作関数群。
        # DLLが公開していない環境でも起動できるよう、存在するものだけをバインドする。
        if hasattr(d,'NaviGetControlPoint'):
            d.NaviGetControlPoint.argtypes=[L,P,S,L,L];d.NaviGetControlPoint.restype=L
        if hasattr(d,'NaviGetControlPointForTimeSpan'):
            d.NaviGetControlPointForTimeSpan.argtypes=[L,P];d.NaviGetControlPointForTimeSpan.restype=L
        if hasattr(d,'NaviChangePeriod'):
            d.NaviChangePeriod.argtypes=[L,P,L,S,S,S];d.NaviChangePeriod.restype=None
        if hasattr(d,'NaviChangePeriodKind'):
            d.NaviChangePeriodKind.argtypes=[L,P,L];d.NaviChangePeriodKind.restype=None
        if hasattr(d,'NaviGetControlPointNumber'):
            d.NaviGetControlPointNumber.argtypes=[L,P,L,P];d.NaviGetControlPointNumber.restype=None
        if hasattr(d,'NaviGetControlPoint2'):
            d.NaviGetControlPoint2.argtypes=[L,P,L,L];d.NaviGetControlPoint2.restype=L
        if hasattr(d,'NaviGetControlPointType'):
            d.NaviGetControlPointType.argtypes=[L,P,P];d.NaviGetControlPointType.restype=None
        if hasattr(d,'NaviGetNameCP'):
            d.NaviGetNameCP.argtypes=[L,P,L,S];d.NaviGetNameCP.restype=None
        # データ項目（列）の読み取り。管理ポイント側と同じ呼び出し規約に合わせている。
        if hasattr(d,'NaviGetDataItemNumber'):
            d.NaviGetDataItemNumber.argtypes=[L,P,L,P];d.NaviGetDataItemNumber.restype=None
        if hasattr(d,'NaviGetDataItem2'):
            d.NaviGetDataItem2.argtypes=[L,P,L,L];d.NaviGetDataItem2.restype=L
        # NaviGetNameDI(hDItem, rc, name) — 引数は3つ。NaviGetNameCP と違い master を取らない。
        # 4つで呼んでいたため、列名が全件空で返っていた。宣言は SymNaviApi.bas による。
        if hasattr(d,'NaviGetNameDI'):
            d.NaviGetNameDI.argtypes=[L,P,S];d.NaviGetNameDI.restype=None
        # NaviGetPeriod(hCPoint, rc, locate, condition, fromTime, toTime, reserve)
        if hasattr(d,'NaviGetPeriod'):
            d.NaviGetPeriod.argtypes=[L,P,L,P,S,S,S];d.NaviGetPeriod.restype=None
        # ここから下はマニュアル記載の書式そのまま。
        # NaviGetDataItem(hCatalog, rc, locate, label, order, reserve) -> hDItem（5.5.1）
        if hasattr(d,'NaviGetDataItem'):
            d.NaviGetDataItem.argtypes=[L,P,L,S,L,L];d.NaviGetDataItem.restype=L
        # NaviRemoveDataItem(hCatalog, hDItem, rc)（5.5.2）。管理ポイント系と違い rc が最後にくる。
        if hasattr(d,'NaviRemoveDataItem'):
            d.NaviRemoveDataItem.argtypes=[L,L,P];d.NaviRemoveDataItem.restype=None
        # NaviInvalidateExecution は実行後に列を変える場合のみ必要。並びは未確認なので、
        # マニュアルで裏が取れるまで呼び出さない（列の削除は実行前に行えば不要）。
        self.bound={n for n in dir(d) if n.startswith('Navi') and getattr(getattr(d,n,None),'argtypes',None) is not None}
    def info(self):
        pybits=struct.calcsize('P')*8;dllbits=pe_bits(self.dll_path);norm=os.path.normcase(os.path.normpath(str(self.dll_path)));local=os.path.normcase(os.path.normpath(r'C:\NAVIAP'))
        if norm==local or norm.startswith(local+os.sep):reason='ローカルのC:\\NAVIAP配下に、Pythonと同じ%d bitの利用可能なDLLがあるため最優先で選択しました。'%pybits
        elif 'config'+os.sep+'naviap' in norm.lower():reason='ローカルのC:\\NAVIAP配下に利用可能な%d bit DLLがなかったため、アプリ側Config\\NAVIAPのDLLをフォールバック選択しました。'%pybits
        else:reason='ローカル標準配置に利用可能なDLLがないため、互換候補の中からPythonと同じ%d bitのDLLを選択しました。'%pybits
        exports=pe_exports(self.dll_path)
        navi=[x for x in exports if x.lower().startswith('navi')]
        bound=sorted(getattr(self,'bound',set()))
        return {'ok':True,'dll':self.dll_path,'dll_bits':dllbits,'python_bits':pybits,'mode':'Navigator API','attempts':self.attempts,'deploy_report':self.deploy_report,'selection_reason':reason,'exports':navi,'exports_total':len(exports),'exports_bound':bound,'bit_diagnosis':f'Python {pybits} bit / DLL {dllbits or "不明"} bit / '+('一致' if dllbits==pybits else '不一致')}
    def error_code(self):
        code=ctypes.c_long()
        try:self.dll.NaviGetErrorCode(ctypes.byref(code));return int(code.value)
        except Exception:return 0
    def error_message(self):
        # 公式サンプルと同じく、詳細コードより先にNavigator Serverメッセージを取得する。
        rc=ctypes.c_long();message_ptr=ctypes.c_char_p()
        try:
            self.dll.NaviGetErrorMessage(ctypes.byref(rc),ctypes.byref(message_ptr))
            raw=message_ptr.value or b''
            message=raw.decode('mbcs',errors='replace').strip() if raw else ''
            return int(rc.value),message
        except Exception as e:
            return -1,f'NaviGetErrorMessage取得失敗: {e}'
    def _check(self,op,rc,detail=''):
        if int(rc.value)!=NAVI_OK:
            message_rc,message=self.error_message()
            detail_code=self.error_code()
            mapped=ERROR_NAMES.get(detail_code,'NAVI_ERROR_UNKNOWN')
            server_part=f' server_message_rc=0x{message_rc:X} server_message={message}' if message else f' server_message_rc=0x{message_rc:X} server_message=(なし)'
            raise NavigatorApiError(op,detail_code or rc.value,f'api_rc=0x{int(rc.value):X} detail_code=0x{detail_code:X} detail_name={mapped}{server_part} {detail}')
    def open_session(self,user,password,server):
        rc=ctypes.c_long();t=time.perf_counter();self.dll.NaviOpenSession(ctypes.byref(rc),_ansi(user),_ansi(password),_ansi(server));self._check('NaviOpenSession',rc)
        state=int(self.dll.NaviIsSessionOpened())
        if state!=1:raise NavigatorApiError('NaviIsSessionOpened',state,'NaviOpenSession後もセッション未接続')
        self.opened=True
        return time.perf_counter()-t
    def connect_data_source(self,profile):
        kind=str(profile.get('kind') or '').strip().lower();rc=ctypes.c_long();t=time.perf_counter()
        user=str(profile.get('user') or '');password=str(profile.get('password') or '');server=str(profile.get('server') or '')
        option=str(profile.get('option') or '');resource=str(profile.get('resource') or '')
        if kind=='oracle':self.dll.NaviConnectOracle(ctypes.byref(rc),_ansi(user),_ansi(password))
        elif kind in ('sqlserver','sql_server'):self.dll.NaviConnectSQLServer(ctypes.byref(rc),_ansi(user),_ansi(password))
        elif kind=='rda':self.dll.NaviConnectRDA(ctypes.byref(rc),_ansi(user),_ansi(password),_ansi(server))
        elif kind in ('postgres','postgresql','anydb','basedbms'):self.dll.NaviConnectBaseDBMS(ctypes.byref(rc),NAVI_DBMS_ANYDB,_ansi(user),_ansi(password),_ansi(option))
        elif kind=='resource':
            if not hasattr(self.dll,'NaviConnectResource'):raise RuntimeError('このDLLはNaviConnectResourceを公開していません')
            resource_kind=int(profile.get('resource_kind') or 0);self.dll.NaviConnectResource(ctypes.byref(rc),_ansi(resource),resource_kind,_ansi(user),_ansi(password),_ansi(option))
        elif kind in ('noauth','resource_noauth'):
            if not hasattr(self.dll,'NaviConnectResourceNoAuth'):raise RuntimeError('このDLLはNaviConnectResourceNoAuthを公開していません')
            self.dll.NaviConnectResourceNoAuth(ctypes.byref(rc))
        else:raise ValueError(f'未対応のAPIデータソース種別: {kind}')
        self._check('NaviConnect'+kind,rc,f'kind={kind} server={server} resource={resource}')
        return time.perf_counter()-t
    def open_catalog(self,path):
        # NaviOpenCatalogには必ず既存RNEの正規化済み絶対パスを渡す。
        # ファイル名だけに依存したcwd解決や、関連定義を切断する単体コピーを避ける。
        catalog=Path(path).expanduser()
        if not catalog.is_absolute():catalog=(Path.cwd()/catalog).resolve()
        else:catalog=catalog.resolve()
        if not catalog.is_file():raise FileNotFoundError(f'RNEカタログがありません: {catalog}')
        encoded=_ansi(catalog)
        rc=ctypes.c_long();t=time.perf_counter();h=int(self.dll.NaviOpenCatalog(ctypes.byref(rc),encoded));self._check('NaviOpenCatalog',rc,str(catalog));self.catalog=h
        return h,time.perf_counter()-t
    def execute(self,h):
        rc=ctypes.c_long();number=ctypes.c_long();reserve=ctypes.c_long();t=time.perf_counter();self.dll.NaviExecuteCatalog(h,ctypes.byref(rc),ctypes.byref(number),NAVI_DOWNLOADNOW,reserve);self._check('NaviExecuteCatalog',rc)
        return int(number.value),time.perf_counter()-t
    def supports_header_probe(self):
        """1行だけ受け取って見出しを得る方式が使えるDLLか。"""
        return hasattr(self.dll,'NaviDownLoadData') and hasattr(self.dll,'NaviTerminateDL')

    def execute_header_only(self,h,path,sample_rows=1):
        """列名だけを取りに行く。全件は転送しない。

        NAVI_DOWNLOADLATER で実行し、sample_rows 行だけダウンロードして打ち切る。マニュアル 5.3.6 の
        とおり NaviSaveData はダウンロード済みの分しか書き出さないので、見出し＋数行のファイルができる。
        戻り値は (保存にかかった秒数, ダウンロード行数, 問い合わせ結果の総行数)。
        """
        if not self.supports_header_probe():
            raise RuntimeError('このDLLは NaviDownLoadData / NaviTerminateDL を公開していません')
        rc=ctypes.c_long();number=ctypes.c_long();t=time.perf_counter()
        self.dll.NaviExecuteCatalog(h,ctypes.byref(rc),ctypes.byref(number),NAVI_DOWNLOADLATER,0)
        self._check('NaviExecuteCatalog(DOWNLOADLATER)',rc)
        execute_elapsed=time.perf_counter()-t
        got=ctypes.c_long();rc2=ctypes.c_long()
        self.dll.NaviDownLoadData(h,ctypes.byref(rc2),int(sample_rows),ctypes.byref(got))
        # 全件ダウンロード済みならNAVI_EODが返る。少数行の想定なので、そのどちらも正常扱いにする。
        if int(rc2.value) not in (NAVI_OK,NAVI_EOD):
            self._check('NaviDownLoadData',rc2)
        downloaded=int(got.value)
        rc3=ctypes.c_long()
        try:
            self.dll.NaviTerminateDL(h,ctypes.byref(rc3))
        except Exception:
            pass
        save_elapsed=self.save_csv(h,path)
        return execute_elapsed+save_elapsed,downloaded,int(number.value)

    def dimensions(self,h):
        rc=ctypes.c_long();rows=ctypes.c_long();cols=ctypes.c_long();self.dll.NaviGetRecordNumber(h,ctypes.byref(rc),ctypes.byref(rows));self._check('NaviGetRecordNumber',rc);self.dll.NaviGetFieldNumber(h,ctypes.byref(rc),ctypes.byref(cols));self._check('NaviGetFieldNumber',rc)
        return int(rows.value),int(cols.value)
    def save_data(self,h,path,ftype,repeat=NAVI_NONREPEAT):
        rc=ctypes.c_long();t=time.perf_counter();self.dll.NaviSaveData(h,ctypes.byref(rc),_ansi(path),int(ftype),int(repeat));self._check('NaviSaveData',rc,str(path));return time.perf_counter()-t
    def save_csv(self,h,path):
        return self.save_data(h,path,NAVI_CSV,NAVI_NONREPEAT)
    def save_txt(self,h,path):
        return self.save_data(h,path,NAVI_TXT,NAVI_NONREPEAT)
    def save_xlsx(self,h,path):
        return self.save_data(h,path,NAVI_XLSX,NAVI_NONREPEAT)
    def save_xls(self,h,path):
        return self.save_data(h,path,NAVI_XLS,NAVI_NONREPEAT)
    def supports_period_change(self):
        # 相対期間（動的日付）変更に最低限必要なAPIが公開されているか。
        return hasattr(self.dll,'NaviChangePeriod') and (hasattr(self.dll,'NaviGetControlPoint') or hasattr(self.dll,'NaviGetControlPointForTimeSpan'))
    def get_time_control_point(self,h,label='',order=0):
        # RNEに定義済みの時間型管理ポイントのハンドルを取得する。
        # label指定時は 条件→表側→表頭 の順に探索。未指定時は時間フィールドの時間型管理ポイントを使う。
        label=str(label or '').strip()
        if label:
            if not hasattr(self.dll,'NaviGetControlPoint'):
                raise RuntimeError('このDLLはNaviGetControlPointを公開していません。管理ポイント名指定は使用できません')
            last=None
            for locate,locname in ((NAVI_COND,'条件'),(NAVI_SIDE,'表側'),(NAVI_HEAD,'表頭')):
                rc=ctypes.c_long()
                hcp=int(self.dll.NaviGetControlPoint(h,ctypes.byref(rc),_ansi(label),locate,order))
                last=rc
                if int(rc.value)==NAVI_OK and hcp:
                    return hcp,locname
            self._check('NaviGetControlPoint',last or ctypes.c_long(1),f'label={label} が見つかりません')
        if hasattr(self.dll,'NaviGetControlPointForTimeSpan'):
            rc=ctypes.c_long()
            hcp=int(self.dll.NaviGetControlPointForTimeSpan(h,ctypes.byref(rc)))
            if int(rc.value)==NAVI_OK and hcp:
                return hcp,'時間フィールド'
            self._check('NaviGetControlPointForTimeSpan',rc,'時間フィールドの時間型管理ポイントを取得できません。管理ポイント名を指定してください')
        raise RuntimeError('時間型管理ポイントを特定できません。管理ポイント名を指定してください')
    def change_period(self,h_cp,condition,from_time,to_time,beginning=''):
        if not hasattr(self.dll,'NaviChangePeriod'):
            raise RuntimeError('このDLLはNaviChangePeriodを公開していません。相対期間の変更は使用できません')
        rc=ctypes.c_long();t=time.perf_counter()
        self.dll.NaviChangePeriod(h_cp,ctypes.byref(rc),int(condition),_ansi(from_time),_ansi(to_time),_ansi(beginning))
        self._check('NaviChangePeriod',rc,f'condition={condition} from={from_time} to={to_time}')
        return time.perf_counter()-t
    def apply_period(self,h,label,condition,from_time,to_time):
        # RNEを開いたカタログハンドルhに対し、時間型管理ポイントの期間を差し替える。
        h_cp,locname=self.get_time_control_point(h,label)
        self.change_period(h_cp,condition,from_time,to_time)
        return {'handle':h_cp,'locate':locname,'label':label or '(時間フィールド)'}
    @staticmethod
    def _readable_span(addr,limit=4096):
        """addr から安全に読める最大バイト数を返す。読めないなら0。

        ポインタらしき値でも、実際に読めるとは限らない。ctypes.string_at はNULが見つかるまで
        際限なく読むため、未割り当てページに入るとアクセス違反でプロセスごと落ちる（Pythonの
        例外にならないので捕まえられない）。VirtualQueryで実際にコミット済みで読める範囲を
        先に確かめ、その範囲内だけを読む。
        """
        if os.name!='nt':
            # 検証用（LinuxのCI/テスト）。実運用はWindowsだが、判定の分岐まで動かして確かめたい。
            try:
                with open('/proc/self/maps','r') as f:
                    for line in f:
                        rng,perm=line.split()[0],line.split()[1]
                        a,b=(int(x,16) for x in rng.split('-'))
                        if a<=addr<b:return max(0,min(limit,b-addr)) if 'r' in perm else 0
            except OSError:pass
            return 0
        class MBI(ctypes.Structure):
            _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),
                      ('AllocationProtect',ctypes.c_uint32),('__align',ctypes.c_uint32),
                      ('RegionSize',ctypes.c_size_t),('State',ctypes.c_uint32),
                      ('Protect',ctypes.c_uint32),('Type',ctypes.c_uint32),('__align2',ctypes.c_uint32)]
        MEM_COMMIT=0x1000
        READABLE=0x02|0x04|0x08|0x20|0x40|0x80    # READONLY/READWRITE/WRITECOPY/EXECUTE_READ/…
        PAGE_GUARD=0x100;PAGE_NOACCESS=0x01
        mbi=MBI();k=ctypes.windll.kernel32
        if not k.VirtualQuery(ctypes.c_void_p(addr),ctypes.byref(mbi),ctypes.sizeof(mbi)):return 0
        if mbi.State!=MEM_COMMIT:return 0
        prot=mbi.Protect
        if prot & (PAGE_GUARD|PAGE_NOACCESS) or not (prot & READABLE):return 0
        base=int(mbi.BaseAddress or 0)
        return max(0,min(limit,base+int(mbi.RegionSize)-addr))

    def _out_string(self,invoke,size=1024):
        """`name As String` のような文字列出力パラメタを安全に読む。

        VBの宣言では ByRef String だが、このDLLは自前バッファのアドレスを書き込む方式である
        （NaviGetErrorMessage が char** で正しく読めていることから分かる）。渡したバッファへ
        直接書く実装もあり得るため、形だけでは見分けられない。短い項目名はアドレスと同じ形に
        見えてしまうので、「文字として意味が通るか」で決める。
        アドレスとして参照するのは、その番地が実際に読めて、中身が名前として通る場合だけ。
        """
        psize=ctypes.sizeof(ctypes.c_void_p)
        # バッファは必ずゼロ埋めで渡す。番兵で埋めるとNULが1つも無くなり、DLLが入出力文字列として
        # 長さを測ろうとした場合にバッファの外まで走査してヒープを壊す（終了コード0xC0000374）。
        buf=ctypes.create_string_buffer(size);rc=ctypes.c_long(-1)
        invoke(buf,rc)
        if int(rc.value)!=NAVI_OK:return '',f'rc={int(rc.value)}'
        raw=bytes(buf.raw)
        if not any(raw[:psize+32]):return '','unwritten'
        head,tail=raw[:psize],raw[psize:psize+32]
        # ポインタらしき形なら、まず参照してみる。読めて名前として通ればそれが答え。
        if not any(tail) and head[-2:]==b'\x00\x00' and any(head[:psize-2]):
            addr=int.from_bytes(head,'little')
            if 0x10000<addr<0x7fffffffffff:
                span=self._readable_span(addr)
                if span:
                    try:text=self._plausible(ctypes.string_at(addr,span).split(b'\x00',1)[0])
                    except Exception:text=''
                    if text:return text,'ptr'
        # 参照できなかった場合、バッファの中身はアドレスの数値そのものかもしれない。
        # 名前として通るときだけ採用する。通らなければ空を返す（以前の文字化けを再現させない）。
        text=self._plausible(raw.split(b'\x00',1)[0])
        return (text,'buf') if text else ('','unreadable')

    @staticmethod
    def _plausible(body):
        """名前として通る文字列なら返す。通らなければ空文字。

        アドレスの数値をそのまま文字として読むと制御文字が混じる。これを弾くことで、
        ポインタ値を項目名として表示してしまう事故を防ぐ。
        """
        if not body:return ''
        try:text=body.decode('mbcs')
        except (UnicodeDecodeError,LookupError):return ''
        text=text.strip()
        if not text:return ''
        if any(ord(ch)<0x20 or ord(ch)==0x7f for ch in text):return ''
        return text

    def get_name_cp(self,h_cp):
        if not hasattr(self.dll,'NaviGetNameCP'):
            return ''
        try:
            name,_why=self._out_string(lambda buf,rc:self.dll.NaviGetNameCP(h_cp,ctypes.byref(rc),NAVI_LABEL,buf))
            return name
        except Exception:
            return ''
    def list_time_control_points(self,h,read_names=True):
        # RNEに含まれる管理ポイントを列挙し、時間型（TIME/TEMPLATE）を抽出する。
        # DLLが列挙APIを公開していない環境では明示的に失敗させる（手入力にフォールバックしてもらう）。
        if not (hasattr(self.dll,'NaviGetControlPointNumber') and hasattr(self.dll,'NaviGetControlPoint2') and hasattr(self.dll,'NaviGetControlPointType')):
            raise RuntimeError('このDLLは管理ポイント列挙API（NaviGetControlPointNumber/2/Type）を公開していません。管理ポイント名を手入力してください')
        out=[]
        for locate,locname in ((NAVI_COND,'条件'),(NAVI_SIDE,'表側'),(NAVI_HEAD,'表頭')):
            rc=ctypes.c_long();num=ctypes.c_long()
            try:
                self.dll.NaviGetControlPointNumber(h,ctypes.byref(rc),locate,ctypes.byref(num))
            except Exception:
                continue
            if int(rc.value)!=NAVI_OK:continue
            for idx in range(int(num.value)):
                rc2=ctypes.c_long()
                hcp=int(self.dll.NaviGetControlPoint2(h,ctypes.byref(rc2),locate,idx))
                if int(rc2.value)!=NAVI_OK or not hcp:continue
                ctype=None
                try:
                    rc3=ctypes.c_long();tp=ctypes.c_long()
                    self.dll.NaviGetControlPointType(hcp,ctypes.byref(rc3),ctypes.byref(tp))
                    if int(rc3.value)==NAVI_OK:ctype=int(tp.value)
                except Exception:ctype=None
                name=self.get_name_cp(hcp) if read_names else ''
                is_time=ctype in (NAVI_CONTROLPOINT_TIME,NAVI_CONTROLPOINT_TEMPLATE)
                out.append({'location':locname,'index':idx,'name':name or f'管理ポイント#{idx+1}','type':ctype,'type_name':CONTROLPOINT_TYPE_NAMES.get(ctype,'不明'),'is_time':is_time})
        return out
    def supports_column_split(self):
        """列分割ができるDLLか。マニュアルに載っている2関数だけで成立する。

        列名は直近の出力ファイルのヘッダーから取るので、未文書化の列挙APIは必須ではない。
        """
        return all(hasattr(self.dll,n) for n in ('NaviGetDataItem','NaviRemoveDataItem'))

    def supports_data_item_enum(self):
        """列を索引で列挙できるか。公式マニュアルに記載が無い関数群なので、参考情報の取得にのみ使う。"""
        return all(hasattr(self.dll,n) for n in ('NaviGetDataItemNumber','NaviGetDataItem2','NaviGetNameDI'))

    def get_name_di(self,h_di):
        """データ項目の見出しを取得する（SymNaviApi.bas: hDItem, rc, name の3引数）。

        取れた名前と判定に使った戻り値をあわせて返す。名前が空なのが呼び出しの失敗なのか、
        その項目に見出しが無いだけなのかをログで区別できるようにするため。
        """
        if not hasattr(self.dll,'NaviGetNameDI'):
            return '','no_export'
        try:
            return self._out_string(lambda buf,rc:self.dll.NaviGetNameDI(h_di,ctypes.byref(rc),buf))
        except Exception as e:
            return '',f'exc={type(e).__name__}'

    def field_number(self,h):
        """出力される列数（NaviGetFieldNumber）。データ項目の列挙結果と突き合わせる基準に使う。

        呼び出し規約は抽出後の行数・列数取得で実績があるものと同じ。ただし本来は実行後に呼ぶ関数なので、
        実行前のカタログでは 0 やエラーが返る可能性がある。取れなければ None を返すだけで先へ進む。
        """
        if not hasattr(self.dll,'NaviGetFieldNumber'):
            return None,'no_export'
        rc=ctypes.c_long(-1);num=ctypes.c_long(-1)
        try:
            self.dll.NaviGetFieldNumber(h,ctypes.byref(rc),ctypes.byref(num))
        except Exception as e:
            return None,f'exc={type(e).__name__}'
        if int(rc.value)!=NAVI_OK:
            return None,f'rc={int(rc.value)}'
        return int(num.value),'ok'

    def get_data_item(self,h_catalog,label,locate=NAVI_DATA,order=0):
        """項目名からデータ項目のハンドルを取得する（マニュアル 5.5.1）。

        列の列挙APIは公式マニュアルに無いため、列分割ではこの「名前で引く」経路を正規の手段とする。
        列名は直近の出力ファイルのヘッダーから得られるので、推測に頼らずに済む。
        locate は条件（NAVI_COND）かデータ（NAVI_DATA）のみ。同名の項目が複数ある場合は order で指定する。
        """
        if not hasattr(self.dll,'NaviGetDataItem'):
            raise RuntimeError('このDLLは NaviGetDataItem を公開していません')
        rc=ctypes.c_long(-1)
        h=int(self.dll.NaviGetDataItem(h_catalog,ctypes.byref(rc),locate,label.encode('mbcs'),order,0))
        self._check('NaviGetDataItem',rc)
        return h

    def column_layout(self,h_catalog,columns=None,read_names=True):
        """分割できる列と必ず残る列を求める。

        columns（直近の出力ファイルの列名）を渡した場合は、その名前で NaviGetDataItem を引いて
        判定する。この経路はDLLから文字列を受け取らないので、名前の受け渡しに起因する事故が起きない。
        列名が無い場合だけ、列挙APIで名前を読む。
        """
        items=self.list_data_items(h_catalog,read_names=read_names) if self.supports_data_item_enum() else []
        points=self.list_time_control_points(h_catalog,read_names=read_names) if hasattr(self.dll,'NaviGetControlPointNumber') else []
        cond=[x for x in items if x['location']=='条件']
        if columns:
            cls=self.classify_columns(h_catalog,columns)
            removable=[{'name':x['name'],'location':'データ'} for x in cls if x['removable']]
            fixed=[{'name':x['name'],'location':'表側など'} for x in cls if not x['removable']]
        else:
            removable=[x for x in items if x['location']=='データ']
            fixed=[x for x in points if x['location'] in ('表側','表頭')]
        return {'removable':removable,'fixed':fixed,'data_items':items,'control_points':points,
                'condition_items':cond}

    def classify_columns(self,h_catalog,names):
        """列名ごとに、削除できる列（データ項目）か、必ず残る列（管理ポイント由来）かを判定する。

        NaviGetDataItem をデータ欄・条件欄の順に試すだけで、削除も実行も行わない読み取り判定。
        必ず残る列は全パートに現れるので、そのまま横結合のキーになる。
        """
        out=[]
        for name in names:
            found=None
            # データ欄のみを対象にする。条件欄のデータ項目は絞り込み用で出力の列にはならないため、
            # ここに含めると分割できる列を1件多く数えてしまう。
            try:
                h=self.get_data_item(h_catalog,name,locate=NAVI_DATA)
            except Exception:
                h=0
            if h:found={'name':name,'removable':True,'locate':'データ','handle':h}
            out.append(found or {'name':name,'removable':False,'locate':'表側など','handle':0})
        return out

    def apply_column_split(self,h_catalog,drop_names):
        """担当外の列をカタログから外す。実行前に呼ぶこと。

        1件でも外せなければ、その時点で例外にする（部分的に外れた状態で問い合わせると、
        結合したときに列が食い違うため）。RNEファイルは変更しない。
        """
        removed=[];order={}
        for name in drop_names:
            # 同名の列が複数ある場合に備え、同じ名前の何番目かを数えながら指定する。
            k=order.get(name,0);order[name]=k+1
            try:
                h=self.get_data_item(h_catalog,name,locate=NAVI_DATA,order=k)
            except NavigatorApiError as e:
                raise NavigatorApiError('列分割:列の取得',e.rc,f'列「{name}」(order={k}) を取得できません: {e}')
            if not h:
                raise NavigatorApiError('列分割:列の取得',NAVI_ERROR,f'列「{name}」(order={k}) のハンドルが0です')
            try:
                self.remove_data_item(h_catalog,h)
            except NavigatorApiError as e:
                hint=ERROR_HINTS.get(e.rc,'')
                raise NavigatorApiError('列分割:列の削除',e.rc,f'列「{name}」を外せません{("・"+hint) if hint else ""}: {e}')
            removed.append(name)
        return removed

    def remove_data_item(self,h_catalog,h_di):
        """カタログ上のデータ項目を1つ削除する（マニュアル 5.5.2）。

        NaviSaveCatalog を呼ばない限りRNEファイル自体は変更されない。実行前にのみ使うこと。
        項目間演算に使われている項目は削除できず NAVI_ERROR_USEDDATAITEM になる。
        """
        if not hasattr(self.dll,'NaviRemoveDataItem'):
            raise RuntimeError('このDLLは NaviRemoveDataItem を公開していません')
        rc=ctypes.c_long(-1)
        self.dll.NaviRemoveDataItem(h_catalog,h_di,ctypes.byref(rc))
        self._check('NaviRemoveDataItem',rc)

    def list_data_items(self,h,read_names=True):
        """RNEに含まれるデータ項目（列）を列挙する。読み取りのみでカタログは変更しない。

        呼び出し規約は管理ポイント側（NaviGetControlPointNumber/2/NaviGetNameCP）と同型と仮定している。
        仮定が合っているかを実機ログだけで判定できるよう、位置ごとの戻り値を self.di_diag に残す。
        """
        if not all(hasattr(self.dll,n) for n in ('NaviGetDataItemNumber','NaviGetDataItem2','NaviGetNameDI')):
            raise RuntimeError('このDLLはデータ項目の列挙API（NaviGetDataItemNumber/2/NaviGetNameDI）を公開していません')
        out=[];diag=[]
        # マニュアル 5.5.1 のとおり、データ項目が置かれるのは条件フィールドとデータフィールドだけ。
        # 表側・表頭にあるのは管理ポイントなので、ここでは対象にしない。
        for locate,locname in ((NAVI_DATA,'データ'),(NAVI_COND,'条件')):
            rc=ctypes.c_long(-1);num=ctypes.c_long(-1)
            try:
                self.dll.NaviGetDataItemNumber(h,ctypes.byref(rc),locate,ctypes.byref(num))
            except Exception as e:
                diag.append(f'{locname}:num_exc={type(e).__name__}');continue
            if int(rc.value)!=NAVI_OK:
                diag.append(f'{locname}:num_rc={int(rc.value)}');continue
            named=0;handles=0;reasons={}
            for idx in range(int(num.value)):
                rc2=ctypes.c_long(-1)
                hdi=int(self.dll.NaviGetDataItem2(h,ctypes.byref(rc2),locate,idx))
                if int(rc2.value)!=NAVI_OK or not hdi:
                    reasons[f'item_rc={int(rc2.value)}']=reasons.get(f'item_rc={int(rc2.value)}',0)+1;continue
                handles+=1
                name,why=self.get_name_di(hdi) if read_names else ('','skipped')
                if name:named+=1
                else:reasons[f'name_{why}']=reasons.get(f'name_{why}',0)+1
                out.append({'location':locname,'index':idx,'handle':hdi,'name':name or f'データ項目#{idx+1}','named':bool(name)})
            detail=','.join(f'{k}x{v}' for k,v in sorted(reasons.items()))
            diag.append(f'{locname}:num={int(num.value)} handle={handles} named={named}'+(f' [{detail}]' if detail else ''))
        self.di_diag='; '.join(diag)
        return out

    def close_catalog(self):
        if self.catalog:
            self.dll.NaviCloseCatalog(self.catalog);self.catalog=0
    def close(self):
        try:self.close_catalog()
        finally:
            if self.opened:self.dll.NaviCloseSession();self.opened=False
