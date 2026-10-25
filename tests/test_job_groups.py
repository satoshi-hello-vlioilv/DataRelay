"""対象のグループの保存（2.11.0。lib/navi_groups.py と jobs.group_name）。

・グループ名は対象ごとに1つ。保存して読み直しても同じ。空ならグループなし
・持ち出し（ZIP）に入る。グループなしの対象には書かない（既定の設定と比べたとき、全部が「違う」にならないように）
・持ち込んだ対象のグループ名は、そのまま残る

実行: python -m unittest tests.test_job_groups -v
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_bundle as NB  # noqa: E402
import navi_groups as NG  # noqa: E402

STORE=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_bundle
c=app.load()
job=lambda i,g:{'id':i,'name':i,'enabled':True,'source':'rne','rne':i+'.RNE','rne_path':'.\\rne\\'+i+'.RNE','output_format':'sqlite3','output_file':i+'.sqlite3','schedules':[],'group':g}
c['jobs']=[job('a','  仕掛　 推移 '),job('b',''),job('c',None),job('d','x'*80)]
app.save(c,quiet=True)
got=app.load()
ex=navi_bundle.jobs_export(got['jobs'])
print(json.dumps({'groups':[j['group'] for j in got['jobs']],'export':[j.get('group') for j in ex['jobs']]},ensure_ascii=False))
"""


class NormalizeTest(unittest.TestCase):
 def test_shape(self):
  self.assertEqual(NG.normalize_group('  仕掛 \t 推移  '),'仕掛 推移','続く空白は1つ・前後は落とす')
  self.assertEqual(NG.normalize_group('仕掛　推移'),'仕掛 推移','全角の空白も空白として1つにする')
  self.assertEqual(NG.normalize_group(None),'')
  self.assertEqual(NG.normalize_group(3),'','文字でない物はグループなし')
  self.assertEqual(len(NG.normalize_group('あ'*100)),NG.GROUP_MAX)


class BundleTest(unittest.TestCase):
 def test_import_keeps_the_group(self):
  payload=NB.jobs_export([{'id':'x','name':'仕掛','source':'rne','rne':'A.RNE','output_file':'a.sqlite3','group':'仕掛'}])
  jobs,bad=NB.jobs_import(payload)
  self.assertEqual(bad,[])
  self.assertEqual(jobs[0]['group'],'仕掛')


class StoreTest(unittest.TestCase):
 def test_roundtrip_and_export(self):
  with tempfile.TemporaryDirectory() as d:
   env=dict(os.environ,NAVI_LOCAL_ROOT=str(Path(d)/'local'),NAVI_DATA_ROOT=str(Path(d)/'data'),NAVI_CONFIG_DIR=str(Path(d)/'data'/'Config'),
            NAVI_SECRET_FILE=str(Path(d)/'local'/'s.json'),DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8')
   r=subprocess.run([sys.executable,'-c',STORE,str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
   self.assertEqual(r.returncode,0,r.stderr[-3000:])
   v=json.loads(r.stdout.strip().splitlines()[-1])
  self.assertEqual(v['groups'],['仕掛 推移','','','x'*NG.GROUP_MAX],'保存のときに整える。空と無しはグループなし')
  self.assertEqual(v['export'],['仕掛 推移',None,None,'x'*NG.GROUP_MAX],'持ち出しに入る。グループなしの対象には書かない')


if __name__=='__main__':
 unittest.main()
