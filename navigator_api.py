from __future__ import annotations
import ctypes, os, struct, time
from pathlib import Path

NAVI_OK=0
NAVI_DOWNLOADNOW=0
NAVI_CSV=1
NAVI_TXT=2
NAVI_XLSX=5
NAVI_XLS=9
NAVI_NOCHANGE=16
NAVI_NONREPEAT=8
NAVI_DBMS_ANYDB=8
ERROR_NAMES={
 3:'NAVI_ERROR_SYMFOWARE',4:'NAVI_ERROR_ORACLE',5:'NAVI_ERROR_SERVERENV',6:'NAVI_ERROR_LOGON',
 7:'NAVI_ERROR_CONNECT',8:'NAVI_ERROR_SERVER',9:'NAVI_ERROR_SESSION',10:'NAVI_ERROR_OPEN',
 11:'NAVI_ERROR_CATALOG',12:'NAVI_ERROR_EXECMD',13:'NAVI_ERROR_EXECUTE',14:'NAVI_ERROR_DOWNLOAD',
 15:'NAVI_ERROR_READ',16:'NAVI_ERROR_SAVEDATA',31:'NAVI_ERROR_SAVE',32:'NAVI_ERROR_FILENOTFOUND',
 33:'NAVI_ERROR_BADPATH',34:'NAVI_ERROR_ACCESSDENIED',35:'NAVI_ERROR_DISKFULL',36:'NAVI_ERROR_SHARINGVIOLATION'
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

def candidate_dlls(symnavi_exe=None,configured_path=None):
    pybits=struct.calcsize('P')*8
    fixed=[
      Path(r'C:\NAVIAP\debugdllVC14x64\SymNaviA.dll'),
      Path(r'C:\NAVIAP\dllVC14x64\SymNaviA.dll'),
      Path(r'C:\NAVIAP\debugdllVC14\SymNaviA.dll'),
      Path(r'C:\NAVIAP\dllVC14\SymNaviA.dll')]
    out=[]
    if configured_path:
        cp=Path(configured_path);out.append(cp/'SymNaviA.dll' if cp.suffix.lower()!='.dll' else cp)
    out.extend(fixed)
    if symnavi_exe:
        p=Path(symnavi_exe);out += [p.parent/'SymNaviA.dll',p.parent.parent/'bin'/'SymNaviA.dll']
    out.append(Path('SymNaviA.dll'))
    unique=[];seen=set()
    for p in out:
        key=str(p).lower()
        if key not in seen:seen.add(key);unique.append(p)
    return sorted(unique,key=lambda p:(0 if p.is_file() and pe_bits(p)==pybits else 1,0 if p.is_file() else 1))

class NavigatorApiError(RuntimeError):
    def __init__(self,operation,rc,detail=''):
        self.operation=operation;self.rc=int(rc);self.name=ERROR_NAMES.get(int(rc),'NAVI_ERROR_UNKNOWN')
        super().__init__(f'{operation}失敗 rc=0x{int(rc):X} name={self.name} {detail}'.strip())

class NavigatorApi:
    def __init__(self,symnavi_exe=None,logger=None,dll_path=None):
        if os.name!='nt':raise RuntimeError('Navigator APIはWindowsでのみ利用できます')
        self.log=logger;self.dll=None;self.dll_path='';self.dll_dirs=[];errors=[]
        self.attempts=[]
        pybits=struct.calcsize('P')*8
        for candidate in candidate_dlls(symnavi_exe,dll_path):
            bits=pe_bits(candidate) if Path(candidate).is_file() else None
            if bits and bits!=pybits:
                msg=f'{candidate}: DLL={bits}bit / Python={pybits}bit のため対象外';errors.append(msg);self.attempts.append({'path':str(candidate),'exists':True,'dll_bits':bits,'python_bits':pybits,'result':'bit_mismatch'});continue
            try:
                cp=Path(candidate)
                if cp.is_absolute() and cp.parent.is_dir() and hasattr(os,'add_dll_directory'):
                    self.dll_dirs.append(os.add_dll_directory(str(cp.parent)))
                self.dll=ctypes.WinDLL(str(cp));self.dll_path=str(cp);self.attempts.append({'path':str(cp),'exists':cp.is_file(),'dll_bits':bits,'python_bits':pybits,'result':'loaded'});break
            except OSError as e:
                errors.append(f'{candidate}: {e}');self.attempts.append({'path':str(candidate),'exists':Path(candidate).is_file(),'dll_bits':bits,'python_bits':pybits,'result':'load_error','error':str(e)})
        if not self.dll:raise RuntimeError('SymNaviA.dllを読み込めません。設定したDLLパスと同一フォルダー内の依存DLLを確認してください。'+' | '.join(errors))
        self._bind();self.opened=False;self.catalog=0
    def _bind(self):
        L=ctypes.c_long; P=ctypes.POINTER(L); S=ctypes.c_char_p
        d=self.dll
        d.NaviOpenSession.argtypes=[P,S,S,S];d.NaviOpenSession.restype=None
        d.NaviCloseSession.argtypes=[];d.NaviCloseSession.restype=None
        d.NaviIsSessionOpened.argtypes=[];d.NaviIsSessionOpened.restype=L
        d.NaviOpenCatalog.argtypes=[P,S];d.NaviOpenCatalog.restype=L
        d.NaviCloseCatalog.argtypes=[L];d.NaviCloseCatalog.restype=None
        d.NaviExecuteCatalog.argtypes=[L,P,P,L,L];d.NaviExecuteCatalog.restype=None
        d.NaviSaveData.argtypes=[L,P,S,L,L];d.NaviSaveData.restype=None
        d.NaviGetFieldNumber.argtypes=[L,P,P];d.NaviGetFieldNumber.restype=None
        d.NaviGetRecordNumber.argtypes=[L,P,P];d.NaviGetRecordNumber.restype=None
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
    def info(self):
        return {'ok':True,'dll':self.dll_path,'dll_bits':pe_bits(self.dll_path),'python_bits':struct.calcsize('P')*8,'mode':'Navigator API','attempts':self.attempts}
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
    def close_catalog(self):
        if self.catalog:
            self.dll.NaviCloseCatalog(self.catalog);self.catalog=0
    def close(self):
        try:self.close_catalog()
        finally:
            if self.opened:self.dll.NaviCloseSession();self.opened=False
