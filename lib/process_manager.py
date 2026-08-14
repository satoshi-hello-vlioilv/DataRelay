import json,os,subprocess,sys,time,urllib.request
from pathlib import Path
BASE=Path(__file__).resolve().parent.parent; LOCAL_ROOT=Path(os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or Path.home())/'SymfoNaviDataHub'; INFO=LOCAL_ROOT/'runtime'/'app_instance.json'; URL='http://127.0.0.1:5031'
def req(path,method='GET'):
 try:
  with urllib.request.urlopen(urllib.request.Request(URL+path,method=method),timeout=1.2) as r:return r.status,r.read().decode()
 except:return 0,''
def cmdline(pid):
 try:return subprocess.check_output(['powershell','-NoProfile','-Command',f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],text=True,encoding='utf-8',errors='replace',timeout=5).strip()
 except:return ''
def stop():
 code,body=req('/api/instance')
 if code==200 and ('SymfoNaviDataHub' in body or 'NaviToSQLite' in body):req('/api/shutdown-app','POST');time.sleep(1.5)
 try:data=json.loads(INFO.read_text(encoding='utf-8'))
 except:data={}
 for key in ('python_pid','launcher_pid'):
  pid=data.get(key); line=cmdline(pid).lower() if pid else ''
  if pid and str(BASE).lower() in line and ('app.py' in line or 'launch_guard.py' in line):subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:INFO.unlink()
 except:pass
 print('SymfoNavi Data Hubの停止処理が完了しました。')
if __name__=='__main__':stop()
