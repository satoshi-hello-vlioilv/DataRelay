"""設定の読み出し（GET /api/config）が、Python（app.load・navi_web.get_config）と Rust（desktop/core の config.rs・naming.rs）で同じか（2.19.0）。

2 段で確かめる:
  1) 関数ごと … 欄の整え方（値ごとに分ける・ビュワー・後処理・グループ・読取マスタ・結合マスタ・クエリ・出力形式）と、
                ファイル名の型（日付のずらし・記号の数の書式・strftime・字の切り出し・変数の展開）へ、決まった種から作った
                いろいろな値（数・真偽・None・全角・空白・並び・辞書）を入れ、Python の関数と Rust の関数の答えを比べる。
                Python が落ちる値では、Rust は「答えない（Python へ回す）」でなければならない。
  2) ルート   … 設定の写しの見本（対象・予定・読取マスタ・結合マスタ・クエリ・共通設定・変わった値）を Python 自身に作らせ、
                GET /api/config の答えを比べる。いま Python が読めば写しを替える場合（マスターのほうが新しい・別のマスターの写し・
                表の形が古い・移行がまだ）と、Python が落ちる値の場合は、Rust が答えない（Python へ回す）ことを確かめる。
実行: python -m unittest tests.test_rust_config -v
"""
import json,os,random,sqlite3,subprocess,sys,tempfile,unittest
from contextlib import closing   # with sqlite3.connect() は確定するだけで閉じない（Windows では開いたままのファイルを消せない）
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tests'))
from test_rust_parity import core_exe,EXE  # noqa: E402
from test_rust_paths import ref_python  # noqa: E402

FIXED='2026-11-01T09:05:07.123456'

PY_FN=r"""
import json,sys
from datetime import datetime
from pathlib import Path,PureWindowsPath
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app,navi_variants,navi_viewer,navi_post,navi_groups,navi_text,navi_join,navi_mrun,navi_output,navi_paths
def dt(a):return datetime.fromisoformat(a['dt'])
F={
 'py_str':lambda a:str(a['v']),
 'normalize_variants':lambda a:navi_variants.normalize(a['v']),
 'normalize_viewer':lambda a:navi_viewer.normalize(a['v']),
 'normalize_post':lambda a:navi_post.normalize(a['v']),
 'normalize_group':lambda a:navi_groups.normalize_group(a.get('v')),
 'normalize_layout':lambda a:navi_text.normalize_layout(a['d']),
 'normalize_recipe':lambda a:navi_join.normalize_recipe(a['d']),
 'normalize_query':lambda a:navi_mrun.normalize_query(a['d']),
 'normalize_output_format':lambda a:navi_output.normalize_output_format(a.get('value'),a.get('filename','')),
 'canonical_output_file':lambda a:navi_output.canonical_output_file(a.get('filename'),a['fmt']),
 'job_extra_formats':lambda a:navi_output.job_extra_formats(a['job']),
 'strftime':lambda a:dt(a).strftime(a['fmt']),
 'format_custom_datetime':lambda a:app.format_custom_datetime(dt(a),a['pattern']),
 'apply_date_offset':lambda a:app.apply_date_offset(dt(a),a['offset']).isoformat(timespec='microseconds'),
 'apply_text_op':lambda a:app._apply_text_op(a['value'],a['arg']),
 'split_source_offset':lambda a:list(app.split_source_offset(a['key'])),
 'has_template_variables':lambda a:app.has_template_variables(a['pattern']),
 'render_filename_template':lambda a:app.render_filename_template(a['template'],job=a.get('job'),rne_path=a.get('rne_path'),now=dt(a)),
 'render_filename_segments':lambda a:app.render_filename_segments(a['template'],job=a.get('job'),rne_path=a.get('rne_path'),now=dt(a)),
 'render_path_template':lambda a:app.render_path_template(a['template'],job=a.get('job'),rne_path=a.get('rne_path'),now=dt(a)),
 'variants_has_token':lambda a:navi_variants.has_token(a['text']),
 'variants_plan':lambda a:navi_variants.plan(a['job'],lambda t,v:app.render_filename_template(t,job={**a['job'],'_variant_value':v},now=dt(a)),a['base'],a['folder'],
                                             lambda t,v:app.render_path_template(t,job={**a['job'],'_variant_value':v},now=dt(a)),a['values']),
 'py_name':lambda a:Path(a['value']).name,
 'py_name_nt':lambda a:PureWindowsPath(a['value']).name,
 'py_stem':lambda a:Path(a['value']).stem,
 'py_suffix':lambda a:Path(a['value']).suffix,
 'foreign_profile_path':lambda a:navi_paths.foreign_profile_path(a['value']),
}
out=[]
for q in json.loads(sys.stdin.read()):
 try:out.append({'ok':True,'result':F[q['fn']](q['args'])})
 except Exception as e:out.append({'ok':False,'error':f'{type(e).__name__}: {e}'})
print(json.dumps(out))
"""

# いろいろな値（Python が字にする・数にする・並べるときの癖が出る物）
ATOMS=[None,True,False,0,1,-3,7,2.5,-0.5,1e16,1.5e-5,'', ' ', ' a ','ab','A B','abc','0','1','-2','+3',' 5 ','1_0','３','x1','\u3000値\u3000',
       'selected','other','desc','asc','or','all','listed','combined','parallel','steps','query','sum','count','average','none','first',
       'utf-8','UTF_8','sjis','ms932','latin_1','byte','char','left','right','none','delimited','fixed','custom','regex','tab',
       'date','datetime','real','integer','num','float','str','time','text','YYMMDD','a.csv','b.XLSX','c.db','x.sqlite','t.txt']


def rnd_value(r,depth=0):
 k=r.random()
 if depth<2 and k<0.12:return [rnd_value(r,depth+1) for _ in range(r.randint(0,4))]
 if depth<2 and k<0.2:return {r.choice(['a','key','name','op','x']):rnd_value(r,depth+1) for _ in range(r.randint(0,3))}
 return r.choice(ATOMS)


def maybe(r,d,key,gen,p=0.75):
 if r.random()<p:d[key]=gen()


def gen_variants(r):
 d={}
 for k in ('enabled','item','scope','pattern','folder','method'):maybe(r,d,k,lambda:rnd_value(r))
 maybe(r,d,'values',lambda:r.choice([[rnd_value(r) for _ in range(r.randint(0,60))],rnd_value(r),'abca',{'x':1,'y':2}]))
 return d if r.random()<0.9 else rnd_value(r)


def gen_viewer(r):
 def col():return r.choice([{'key':rnd_value(r),'show':rnd_value(r),'label':rnd_value(r)},{'key':r.choice(['a','b','a ']),'show':False},rnd_value(r)])
 d={}
 maybe(r,d,'cols',lambda:r.choice([[col() for _ in range(r.randint(0,6))],rnd_value(r),'abc']))
 maybe(r,d,'calc',lambda:[r.choice([{'name':rnd_value(r),'formula':rnd_value(r)},{'name':'n','formula':'1+1'},rnd_value(r)]) for _ in range(r.randint(0,4))])
 maybe(r,d,'filters',lambda:[r.choice([{'column':rnd_value(r),'op':r.choice(['eq','gt','contains','bad',rnd_value(r)]),'value':rnd_value(r)},rnd_value(r)]) for _ in range(r.randint(0,4))])
 maybe(r,d,'join',lambda:r.choice(['or','and',rnd_value(r)]))
 return d if r.random()<0.92 else rnd_value(r)


def gen_step(r):
 op=r.choice(['unpivot','repeat','pivot','group','select','remove','rename','sort','m','bad',rnd_value(r)])
 s={'op':op}
 for k in ('mode','columns','attr','value','column','agg','keys','aggs','pairs','expr','names','groups','numbers','index','drop_empty'):
  if r.random()<0.4:s[k]=rnd_value(r)
 if op=='group' and r.random()<0.6:s['aggs']=[r.choice([{'func':r.choice(['sum','count','bad']),'column':rnd_value(r),'name':rnd_value(r)},rnd_value(r),[['func','sum']]]) for _ in range(r.randint(0,3))]
 if op=='rename' and r.random()<0.6:s['pairs']=[r.choice([['a','b'],['a',''],['x'],rnd_value(r)]) for _ in range(r.randint(0,3))]
 if op=='sort' and r.random()<0.6:s['keys']=[r.choice([['a','desc'],['b'],[],['', 'desc'],rnd_value(r)]) for _ in range(r.randint(0,3))]
 if op=='repeat' and r.random()<0.7:
  s['groups']=[[rnd_value(r) for _ in range(r.randint(0,4))] for _ in range(r.randint(0,4))]
  s['numbers']=r.choice([[1,2,3],[3,2],['1','2'],[1.5,2.5],[None],list(range(1,len(s['groups'])+1))])
  if r.random()<0.5:s['names']=[rnd_value(r) for _ in range(r.randint(0,3))]
 if op=='m' and r.random()<0.6:s['expr']=r.choice(['a\r\nb','x'*30,rnd_value(r)])
 return r.choice([s,s,s,[['op','m'],['expr','1']],'ab',None])


def gen_post(r):
 d={}
 maybe(r,d,'steps',lambda:r.choice([[gen_step(r) for _ in range(r.randint(0,5))],rnd_value(r)]))
 for k in ('enabled','mode','query_id','query_out'):maybe(r,d,k,lambda:rnd_value(r),0.5)
 return d if r.random()<0.92 else rnd_value(r)


def gen_column(r):
 c={}
 for k in ('name','start','length','end','field','type','scale','format','note'):maybe(r,c,k,lambda:rnd_value(r),0.5)
 return r.choice([c,c,c,[['name','x']],{}])


def gen_layout(r):
 d={}
 for k in ('id','name','description','encoding','unit','trim','mode','delimiter','delimiter_text','quote','collapse','skip_head','skip_tail','skip_blank','header_row','sample_path','updated_at'):
  maybe(r,d,k,lambda:rnd_value(r),0.6)
 maybe(r,d,'columns',lambda:r.choice([[gen_column(r) for _ in range(r.randint(0,4))],rnd_value(r)]))
 return d


def gen_recipe(r):
 d={}
 for k in ('id','name','description','updated_at'):maybe(r,d,k,lambda:rnd_value(r),0.6)
 def src():
  s={}
  for k in ('alias','name','path','format','table','sheet','layout_id'):maybe(r,s,k,lambda:rnd_value(r),0.5)
  return r.choice([s,s,{}])
 def join():
  j={}
  maybe(r,j,'type',lambda:r.choice(['inner','LEFT','full','right',rnd_value(r)]))
  maybe(r,j,'keys',lambda:r.choice([[r.choice([{'left':rnd_value(r),'right':rnd_value(r)},None,{}]) for _ in range(r.randint(0,8))],rnd_value(r)]))
  return j
 maybe(r,d,'sources',lambda:r.choice([[src() for _ in range(r.randint(0,10))],rnd_value(r)]))
 maybe(r,d,'joins',lambda:r.choice([[join() for _ in range(r.randint(0,4))],rnd_value(r)]))
 maybe(r,d,'columns',lambda:r.choice([[r.choice([{'source':rnd_value(r),'name':rnd_value(r),'as':rnd_value(r)},{}]) for _ in range(r.randint(0,4))],rnd_value(r)]))
 return d


DIRECTIVES='aAbBCdDeFgGHIjmMnprRStTuUVwWyY%fzZ'


def gen_strftime(r):
 parts=[]
 for _ in range(r.randint(1,6)):
  k=r.random()
  if k<0.6:parts.append('%'+r.choice(DIRECTIVES))
  elif k<0.65:parts.append('%:z')
  elif k<0.7 and os.name!='nt':parts.append('%'+r.choice('-_0^#')+r.choice('dmHMSjeYyaAbBp'))
  else:parts.append(r.choice(['_','-','年','x',' ','%%','%%f']))
 return ''.join(parts)


TOKEN_KEYS=['now','exec','datetime','date','time','rne_mtime','mtime','rne_ctime','ctime','rne','rne_name','rne_stem','name','job','table','値','value','unknown','Now']


def gen_token(r):
 key=r.choice(TOKEN_KEYS)
 if r.random()<0.35:key+=''.join(r.choice(['+1D','-1M','+2Y','-7d','+3W','-1H','+30I','-15S','+１D','+1X','+99999Y'])  for _ in range(r.randint(1,2)))
 arg=r.choice(['','YYYYMMDD','YYMD','%Y-%m-%d','%H%M','%Q' if os.name!='nt' else '%d','left:2','right:3','mid:1:2','mid:-3:2','upper','lower','replace:a:b','replace:x','left:x','h:m:s','YYYYYY'])
 return '{'+(' ' if r.random()<0.1 else '')+key+(':'+arg if arg else '')+'}'


def gen_template(r):
 return ''.join(r.choice([gen_token(r),gen_token(r),'_','-',' ','.','a/b','x:y','  ','{','}','{{now}}','{rne']) for _ in range(r.randint(0,5)))


def cases(seed=20261102):
 r=random.Random(seed);out=[]
 def add(fn,**a):out.append({'fn':fn,'args':a})
 for v in ATOMS+[[1,'a',None,True,2.5],{'k':'v'},[[1,2],{'a':[None]}],'it\'s','say "hi"','\'"','\t\n\\','\x01\x7f\x85\u200b']:add('py_str',v=v)
 for _ in range(400):add('normalize_variants',v=gen_variants(r))
 for _ in range(400):add('normalize_viewer',v=gen_viewer(r))
 for _ in range(500):add('normalize_post',v=gen_post(r))
 for v in ATOMS+['a/b','  営業 　部 / /a/b/c/d/e/f',' '+'x'*50,'/','a//b',None,['a']]:add('normalize_group',v=v)
 for _ in range(300):add('normalize_layout',d=gen_layout(r))
 for _ in range(300):add('normalize_recipe',d=gen_recipe(r))
 for _ in range(60):add('normalize_query',d={k:rnd_value(r) for k in ('id','name','description','code','output','updated_at') if r.random()<0.7})
 add('normalize_query',d={'code':'a\r\nb\rc'})
 for v in ATOMS:
  for f in ['','a.csv','b.ACCDB','x.sqlite3','y.TXT','z.xlsx','q.db',None,5]:add('normalize_output_format',value=v,filename=f)
 for f in ATOMS+['勤怠CSV.csv','勤怠.csv.csv','a.b.c','..','.csv','x.','C:/d/e.f.txt','dir/','',None,'a\\b.csv']:
  for fmt in ('sqlite3','txt','csv','xlsx','accdb'):add('canonical_output_file',filename=f,fmt=fmt)
 for _ in range(200):
  job={'output_format':rnd_value(r),'output_file':r.choice(['a.csv','b.xlsx','',None,'c'])}
  job['extra_formats']=r.choice([[rnd_value(r) for _ in range(r.randint(0,6))],'["csv","xlsx","txt"]','csv, xlsx\u3000txt','[1,2]','"csv"','{','{"csv":1}','5','',None,5,rnd_value(r)])
  add('job_extra_formats',job=job)
 dts=['2026-11-01T09:05:07.123456','2024-02-29T23:59:59.000001','0001-01-01T00:00:00.000000','9999-12-31T12:00:00.999999','2026-01-04T00:30:00.000000','2027-01-01T13:00:00.500000']
 for _ in range(400):add('strftime',dt=r.choice(dts),fmt=gen_strftime(r))
 for f in ['%','abc%','%Y%','%%','%c','%x','%X','%s' if os.name!='nt' else '%y','\x00%Y']:add('strftime',dt=dts[0],fmt=f)
 for _ in range(150):add('format_custom_datetime',dt=r.choice(dts),pattern=''.join(r.choice(['Y','YY','YYYY','YYYYYY','M','MM','D','dd','H','hh','m','ss','s','S','-','年','/','x',' ']) for _ in range(r.randint(0,6))))
 for _ in range(200):add('apply_date_offset',dt=r.choice(dts),offset=''.join(r.choice(['+1D','-1M','+2Y','-7d','+3W','-1H','+30I','-15S','+１D','+1X','x','+-1D','-13M','+12M','+99999999D','+9999Y','-2026Y','+0D']) for _ in range(r.randint(0,3))))
 for v in ['ABCDEFG','仕掛データ','','ß','ﬀx']:
  for a in ['','left:3','left:-1','left: 2 ','left:x','left','right:2','right:0','right:99','mid:2:3','mid:-3:2','mid:1','mid:-1:-1','upper','LOWER',' upper ','replace:B:x','replace:B','replace::-','replace','unknown:1','left:99999999999999999999','right:-99999999999999999999']:add('apply_text_op',value=v,arg=a)
 for k in ['now','now-1M','now-1M+2D','now-1Mx','rne','', '_','a1','now+１D','now-1M ','x+1','Now+1Y']:add('split_source_offset',key=k)
 for _ in range(150):add('has_template_variables',pattern=gen_template(r))
 jobs=[{'rne':'C:/rne/仕掛.RNE','rne_path':'','name':'日次 集計','table':'仕掛'},{'rne':'','rne_path':'\\\\srv\\share\\x.y.rne','name':5,'table':None},{'rne':None,'name':' a:b ','_variant_value':'東京'},{}]
 for _ in range(400):
  add('render_filename_template',template=gen_template(r),job=r.choice(jobs),dt=r.choice(dts))
  add('render_filename_segments',template=gen_template(r),job=r.choice(jobs),dt=r.choice(dts))
 pjobs=jobs+[{'_variant_value':v,'name':'n'} for v in ['..','.',' . ','a/b','x:..',' 東京 ','.a.','...','',' ']]
 for _ in range(300):
  add('render_path_template',template=r.choice(['D:\\出力\\','/srv/','',' ','..\\','{値}/','a/'])+gen_template(r)+r.choice(['','\\x','/y',' ']),job=r.choice(pjobs),dt=r.choice(dts))
 for _ in range(80):add('variants_has_token',text=gen_template(r)+r.choice(['','{値:','{value}','{値 }','値']))
 vals=['東京','大阪','TOKYO','tokyo','..','a/b','ab','AB',' ','x']
 for _ in range(300):
  v={'enabled':True,'item':'拠点','values':r.sample(vals,r.randint(0,4)),'pattern':r.choice(['','{値}','固定','{name}_{値:upper}','{date}','{値:lower}_{rne}']),
     'folder':r.choice(['','D:\\{値}','/o/{値:upper}','固定','{値}{date}'])}
  job={'name':r.choice(['受注','a b']),'naming_mode':r.choice(['template','fixed','TEMPLATE','']),'output_pattern':r.choice(['','{name}_{値}','{date}','{value:lower}x']),
       'variants':v}
  add('variants_plan',job=job,base=r.choice(['受注','a{name}','']),folder=r.choice(['','D:\\out']),values=r.choice([None,r.sample(vals,r.randint(0,4))]) or v['values'],dt=r.choice(dts))
 for v in ['','.','..','a','a.b','.a','a.','a.b.c','dir/','/','//x','a/b/c.d','C:','C:\\','C:x.y','c:/a/b.c','\\\\srv\\sh','\\\\srv\\sh\\f.g','a\\b.c','  ','x/./y','...']:
  for fn in ('py_name','py_name_nt','py_stem','py_suffix'):add(fn,value=v)
 home=str(Path.home())
 for v in ['','<PC>\\backup','C:\\Users\\other\\x','C:/Users/Other/AppData','D:\\data\\backup','\\\\srv\\Users\\bob\\y','relative\\Users\\bob',home+'/x','~/x','$HOME/x','C:\\ユーザー\\太郎\\a','C:\\Documents and Settings\\a\\b','C:\\users']:
  add('foreign_profile_path',value=v)
 return out


def run_both(qs,env=None):
 exe=core_exe()
 if not exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
 with tempfile.TemporaryDirectory() as t:
  e=dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(Path(t)/'local'),NAVI_DATA_ROOT=str(Path(t)/'data'),
         NAVI_CONFIG_DIR=str(Path(t)/'data'/'Config'),NAVI_SECRET_FILE=str(Path(t)/'s.json'),**(env or {}))
  stdin=json.dumps(qs,ensure_ascii=False)
  r=subprocess.run([ref_python(),'-c',PY_FN,str(ROOT)],input=stdin,env=e,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=600)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  py=json.loads(r.stdout.strip().split('\n')[-1])
  r=subprocess.run([str(exe),'call'],input='\n'.join(json.dumps(q,ensure_ascii=False) for q in qs)+'\n',env=e,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=600)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  rs=[json.loads(x) for x in r.stdout.split('\n') if x.strip()]   # splitlines は \x85・\u2028 でも分ける
 return py,rs


def canon(v):
 return json.dumps(v,sort_keys=True,ensure_ascii=False)


class ConfigFunctionParityTest(unittest.TestCase):
 def test_functions(self):
  qs=cases();py,rs=run_both(qs)
  self.assertEqual(len(py),len(qs));self.assertEqual(len(rs),len(qs))
  bad=[];passed={}
  for q,p,x in zip(qs,py,rs):
   if not x.get('ok'):bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}: Rust が失敗 {x.get("error")}');continue
   got=x['result']
   if got=={'pass':True}:
    # Rust は答えない（Python へ回す）。Python が落ちる値なら当然。Python が答える値でも許すが、数を数えて出す
    passed[q['fn']]=passed.get(q['fn'],0)+(0 if not p['ok'] else 1);continue
   if got=={'error':True}:
    if p['ok']:bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}: Python={p["result"]!r} Rust=失敗')
    continue
   if not p['ok']:bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}: Python は落ちる（{p["error"]}）のに Rust が答えた {got!r}'[:600]);continue
   if canon(p['result'])!=canon(got):bad.append(f'{q["fn"]} {json.dumps(q["args"],ensure_ascii=False)[:300]}:\n  PY={canon(p["result"])[:400]}\n  RS={canon(got)[:400]}')
  self.assertEqual(bad,[],f'{len(bad)} 件の食い違い:\n'+'\n'.join(bad[:40]))
  # Python が答えるのに Rust が回した数（多すぎれば、Rust が答えられる範囲が狭すぎる）
  self.assertLessEqual(sum(passed.values()),len(qs)//100,f'Python が答えるのに Rust が回した数: {passed}')
  print(f'\n  関数ごとの突き合わせ: {len(qs)} 件（Python が答えるのに Rust が回した: {passed or 0}）')


# ==== ルートの突き合わせ ===================================================

MAKE=r"""
import json,sqlite3,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
spec=json.loads(sys.stdin.read())
app.init_settings_db()
if spec.get('cfg') is not None:
 app._save_local(spec['cfg'],quiet=True)
with sqlite3.connect(str(app.SETTINGS_DB)) as c:
 for sql,params in spec.get('sql',[]):c.execute(sql,params)
app.flush_local_to_master('test')
print(json.dumps({'local':str(app.SETTINGS_DB),'master':str(app.MASTER_SETTINGS_DB)}))
"""

ASK=r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
from datetime import datetime as _dt
import app,navi_web
class Fixed(_dt):
 @classmethod
 def now(cls,tz=None):return _dt.fromisoformat(sys.argv[2])
navi_web.datetime=Fixed
r=app.app.test_client().get('/api/config')
print(json.dumps({'status':r.status_code,'body':r.get_data(as_text=True)},ensure_ascii=False))
"""

STEPS=[{'op':'unpivot','mode':'selected','columns':['1月','2月','1月',''],'attr':'','value':'数'},
       {'op':'repeat','groups':[['品名1','数量1'],['品名2','']],'names':['品名','数量'],'numbers':[1,2]},
       {'op':'pivot','column':'月','value':'数','agg':'avg'},
       {'op':'group','keys':['部署'],'aggs':[{'func':'sum','column':'数'},{'func':'bad'}]},
       {'op':'select','columns':['a','b']},{'op':'rename','pairs':[['a','A'],['b']]},{'op':'sort','keys':[['a','desc'],['b']]},
       {'op':'m','expr':'Table.SelectRows(前, each [数] > 0)\r\n'},{'op':'nope'}]


def full_cfg(rne_rel):
 return {
  'rne_folder':'.\\rne','backup_folder':'','symnavi_exe':'old.exe','navigator_api_search_depth':'abc','navigator_api_search_roots':'C:\\x',
  'settings':{'api_parallel_lines':3,'stability_profile':'stable_api_serial','extract_engine':'dde','split_min_part_mb':4.5},
  'jobs':[
   {'id':'j1','name':'日次 仕掛','rne':rne_rel,'rne_path':'','output_folder':'D:\\out','output_format':'Excel','output_file':'仕掛CSV.csv',
    'table':'仕掛','sheet':'Page1','type':'詳細データ','naming_mode':'template','output_pattern':'{rne}_{now-1D:YYYYMMDD}_{rne_mtime:%Y%m%d%H%M}_{name:left:2}',
    'comment':'メモ','group':' 営業 / 月次 ','split_mode':'FORCE','split_shape':'row','row_axis_mode':'Name','row_axis_index':3,'row_axis_name':'部署',
    'extra_formats':['csv','xlsx','txt','bad'],'index_columns':[' a ','', 'b'],'skip_if_unchanged':True,'source':'RNE',
    'period':{'enabled':True,'target':'cond','range':'from','unit':'day','from_offset':-30,'cond_item':' 日付 '},
    'variants':{'enabled':True,'item':'拠点','values':['東京',' 大阪 ','東京',''],'method':'parallel','pattern':'{値}_{date}'},
    'viewer':{'cols':[{'key':'a','show':False,'label':'A'},{'key':'a'}],'filters':[{'column':'a','op':'gt','value':1}],'join':'or'},
    'post':{'enabled':True,'steps':STEPS},
    'schedules':[{'name':'朝','type':'weekly','time':'07:30','weekdays':[0,2,4]},{'type':'interval','interval_minutes':0},
                 {'type':'monthly','month_days':[1,15,31],'enabled':False},{'type':'dates','dates':['2026-12-01']}]},
   {'id':'j2','name':'固定名','rne':'x.RNE','output_format':'','output_file':'勤怠.csv.csv','naming_mode':'fixed','output_pattern':'{now}',
    'extra_formats':[],'source':'text','text_path':'a.txt','layout_id':'L1','post':{},'variants':{},'viewer':{}},
   {'id':'j3','name':'型だけ','rne':'','output_format':'sqlite','output_file':'','naming_mode':'TEMPLATE','output_pattern':'SIKALOTDEF{unknown}','source':'join','recipe_id':'R1'},
   {'id':'j4','name':'ずらしが大きすぎる','rne':rne_rel,'output_format':'csv','naming_mode':'template','output_pattern':'{now+99999Y}_{date}','source':'mquery','query_id':'Q1','extra_formats':['xlsx']},
   {'id':'j5','name':'値ごと','rne':rne_rel,'output_format':'txt','naming_mode':'template','output_pattern':'{値}{value}{rne_ctime:YY}{table:replace:仕:し}','table':'仕掛'},
  ]}


def layout_sql(now='2026-11-01T00:00:00'):
 return [
  ['INSERT INTO text_layouts (id,display_order,name,description,encoding,unit,trim,skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at,parse_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   ['L1',0,' 固定 ','説明','SJIS','CHAR','x',2,1000,0,1,json.dumps([{'name':'a','start':3,'end':7,'type':'int'},{'start':'x','length':'4','type':'date'},{'type':'real','scale':12},'bad'],ensure_ascii=False),' s.txt ',now,
    json.dumps({'mode':'delimited','delimiter':'custom','delimiter_text':' | ','quote':'single','collapse':1,'extra':1})]],
  ['INSERT INTO text_layouts (id,display_order,name,description,encoding,unit,trim,skip_head,skip_tail,skip_blank,header_row,columns_json,sample_path,updated_at,parse_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   ['L2',0,'壊れた JSON','','utf-8','byte','both','a',-3,1,0,'{','',now,'[1]']],
  ['INSERT INTO join_recipes (id,display_order,name,description,sources_json,joins_json,columns_json,updated_at) VALUES(?,?,?,?,?,?,?,?)',
   ['R1',1,'結合','',json.dumps([{'path':'a.CSV'},{'path':'b.db','format':'TEXT','alias':'Z'},{'path':'c.unknown'}]),
    json.dumps([{'type':'LEFT','keys':[{'left':'k','right':'k'},{'left':' ','right':''},None]}]),json.dumps([{'name':'k','source':''},{'name':''},{'name':'v','as':'値'}]),now]],
  ['INSERT INTO m_queries (id,display_order,name,description,code,output_query,updated_at) VALUES(?,?,?,?,?,?,?)',['Q1',0,' クエリ ','',"let\r\n a=1\rin a",' 出力 ',now]],
 ]


class ConfigRouteParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.exe=core_exe()
  if not cls.exe:raise AssertionError(f'Rust の答え口（desktop/target/debug/{EXE}）がありません。先に `cd desktop && cargo build --locked` を流してください')
  cls.tmp=tempfile.TemporaryDirectory();cls.t=Path(cls.tmp.name).resolve()

 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()

 def env(self,name,extra=None):
  d=self.t/name
  return dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(d/'local'),
              NAVI_DATA_ROOT=str(d/'data'),NAVI_CONFIG_DIR=str(d/'data'/'Config'),NAVI_SECRET_FILE=str(d/'s.json'),**(extra or {}))

 def make(self,name,cfg=None,sql=(),env=None):
  e=self.env(name,env)
  r=subprocess.run([ref_python(),'-c',MAKE,str(ROOT)],input=json.dumps({'cfg':cfg,'sql':list(sql)},ensure_ascii=False),env=e,cwd=str(ROOT),
                   capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().splitlines()[-1])

 def rust(self,name,env=None):
  r=subprocess.run([str(self.exe),'answer','--base',str(ROOT)],input=json.dumps({'method':'GET','path':'/api/config','query':'','body':''})+'\n',
                   env=dict(self.env(name,env),DATARELAY_FIXED_NOW=FIXED),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=120)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().splitlines()[-1])

 def python(self,name,env=None):
  r=subprocess.run([ref_python(),'-c',ASK,str(ROOT),FIXED],env=self.env(name,env),cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  if r.returncode:raise AssertionError(r.stderr[-3000:])
  return json.loads(r.stdout.strip().splitlines()[-1])

 def compare(self,name,env=None):
  rs=self.rust(name,env)
  self.assertEqual(rs['status'],200,f'{name}: Rust が答えなかった（{rs["status"]}）')
  py=self.python(name,env)
  self.assertEqual(py['status'],200,py['body'][:2000])
  a,b=json.loads(py['body']),json.loads(rs['body'])
  diff=[k for k in sorted(set(a)|set(b)) if canon(a.get(k))!=canon(b.get(k))]
  if 'jobs' in diff and len(a.get('jobs',[]))==len(b.get('jobs',[])):
   for i,(x,y) in enumerate(zip(a['jobs'],b['jobs'])):
    for k in sorted(set(x)|set(y)):
     if canon(x.get(k))!=canon(y.get(k)):print(f'  jobs[{i}].{k}\n    PY={canon(x.get(k))[:600]}\n    RS={canon(y.get(k))[:600]}')
  self.assertEqual(diff,[],f'{name}: 食い違う鍵 '+', '.join(f'{k}: PY={canon(a.get(k))[:300]} RS={canon(b.get(k))[:300]}' for k in diff if k!='jobs'))
  return a

 def rne(self,name):
  p=self.t/name/'data'/'rne'/'仕掛 日次.RNE';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'x')
  os.utime(p,(1767225600.25,1767225600.75))   # 2026-01-01 の決まった時刻（秒の小数も）
  return '仕掛 日次.RNE'

 def test_full_settings(self):
  """対象・予定・読取マスタ・結合マスタ・クエリ・共通設定を一通り。出力名の試算（型・RNE の時刻・大きすぎるずらし）も。"""
  rne=self.rne('full')
  self.make('full',full_cfg(rne),layout_sql())
  a=self.compare('full')
  j=a['jobs']
  self.assertTrue(j[0]['output_is_variable']);self.assertIn('20261031',j[0]['output_file_preview'])
  self.assertEqual(j[3]['output_file_preview'],'','ずらしが 9999 年を出る型は、試算を空にする')
  self.assertEqual(j[3]['output_plan'],[])
  self.assertFalse(j[2]['output_is_variable'],'知らない変数だけの型は変数扱いしない')
  self.assertEqual(a['backup_folder'],'<PC>\\backup')

 def test_odd_values(self):
  """字の欄に数・小数・空（NULL）・壊れた JSON が入っていても、Python と同じに読む（SQLite は欄の型を強制しない）。"""
  self.make('odd',{'jobs':[{'id':'o1','name':'x'},{'id':'o2','name':'y'}],'settings':{'backup_mode':'days'},'backup_folder':'C:\\Users\\someone_else\\backup2'},[
   ["UPDATE jobs SET name=123,output_file=5,output_format=?,rne=7.5,naming_mode=?,output_pattern=?,extra_formats=?,index_columns=?,period_json=?,variants_json=?,viewer_json=?,post_json=?,group_name=? WHERE id='o1'",
    ['XLS','template','{name}{table}','csv, xlsx  txt','["a",1,null," "]','{bad','[1,2]','"str"','{"steps":"abc","enabled":0}','a/ /b']],
   ["UPDATE jobs SET extra_formats=?,index_columns=?,period_json=?,variants_json=?,row_axis_index=?,skip_if_unchanged=?,enabled=? WHERE id='o2'",
    ['"csv"',5,'{"enabled":1,"from_offset":"x"}','{"values":{"a":1,"b":2}}','4.9','0','0']],
   ["INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",['s1','o1',0,'1','朝','daily',None,None,None,None,None,'t']],
   ["INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",['s2','o1',1,0,5,'interval','',15.0,'',None,'[]','t']],
   ["INSERT OR REPLACE INTO app_settings VALUES('navigator_api_search_depth','99','int','t')",[]],
   ["INSERT OR REPLACE INTO app_settings VALUES('navigator_api_search_roots','[]','json','t')",[]],
   ["INSERT OR REPLACE INTO app_settings VALUES('flag','1','bool','t')",[]],
   ["INSERT OR REPLACE INTO app_settings VALUES('num',3.5,'text','t')",[]],
   ["INSERT OR REPLACE INTO app_settings VALUES('n2',7,'bool','t')",[]],
   ["INSERT OR REPLACE INTO schema_info(key,value) VALUES('settings_revision',' 0012 ')",[]],
  ])
  a=self.compare('odd')
  self.assertEqual(a['backup_folder'],'<PC>\\backup','別の人のプロファイルの下は <PC> へ読み替える')

 def test_backup_folder_kept(self):
  """自分で決めた控えの置き場（プロファイルと関係の無い場所）はそのまま（前後の空白も残す。読み替えるときだけ見る）。"""
  self.make('keep',{'jobs':[],'backup_folder':' D:\\控え ','text_folder':'E:\\t'})
  self.assertEqual(self.compare('keep')['backup_folder'],' D:\\控え ')

 def test_empty(self):
  """対象が1つも無い・共通設定も無い（雛形の無い初回に近い）。"""
  self.make('empty',None)
  self.compare('empty')

 def assert_passes(self,name,why,env=None):
  rs=self.rust(name,env)
  self.assertEqual(rs['status'],0,f'{why}: Rust は答えず Python へ回すはず（{rs["status"]} {rs["body"][:200]}）')

 def test_not_settled_goes_to_python(self):
  """いま Python が読めば写しを替える場合は、Rust は答えない。"""
  paths=self.make('newer',{'jobs':[{'id':'a','name':'a'}]})
  with closing(sqlite3.connect(paths['master'])) as c,c:c.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('settings_revision','99')")
  self.assert_passes('newer','マスターの版のほうが新しい（Python が取り込む）')
  # 一度 Python が読めば（取り込めば）、Rust も答える
  self.python('newer');self.assertEqual(self.rust('newer')['status'],200)

  paths=self.make('owner',{'jobs':[]})
  Path(paths['local']).with_name('app_settings.master.txt').write_text('/elsewhere/app_settings.sqlite3',encoding='utf-8')
  self.assert_passes('owner','写しが別のマスターの物（Python が退けて取り直す）')

  paths=self.make('migrate',{'jobs':[]})
  with closing(sqlite3.connect(paths['local'])) as c,c:c.execute("DELETE FROM schema_info WHERE key='migrated_parallel_max_lines_24'")
  self.assert_passes('migrate','設定の移行がまだ（Python が値を書き換える）')

  paths=self.make('nomaster',{'jobs':[]})
  os.remove(paths['master'])
  self.assert_passes('nomaster','マスターが無い（Python が作る）')

  self.assert_passes('nothing','写しも無い（まだ一度も起きていない）')

 def test_old_schema_goes_to_python(self):
  """表の形が古い写し（列が足りない）は、Python が列を足してから読む。Rust は答えない。"""
  paths=self.make('old',{'jobs':[{'id':'a','name':'a'}]})
  with closing(sqlite3.connect(paths['local'])) as c,c:c.execute('ALTER TABLE jobs DROP COLUMN group_name')
  self.assert_passes('old','jobs に group_name が無い')

 def test_broken_values_go_to_python(self):
  """Python が落ちる値（壊れた JSON の設定・予定）・Python だけが読める値（NaN）・バイナリは、Rust は答えない。"""
  for name,sql in [('badjson',["INSERT OR REPLACE INTO app_settings VALUES('x','{','json','t')",[]]),
                   ('nan',["INSERT OR REPLACE INTO app_settings VALUES('x','[NaN]','json','t')",[]]),
                   ('bigint',["INSERT OR REPLACE INTO app_settings VALUES('x','[123456789012345678901234]','json','t')",[]]),
                   ('blob',["INSERT OR REPLACE INTO app_settings VALUES('x',x'00ff','text','t')",[]]),
                   ('badint',["INSERT OR REPLACE INTO app_settings VALUES('x','abc','int','t')",[]]),
                   ('badsettings',["INSERT OR REPLACE INTO app_settings VALUES('settings','[1]','json','t')",[]]),
                   ('weekdays',["INSERT INTO schedules VALUES('s','a',0,1,'n','weekly','06:00',NULL,'[1,',NULL,NULL,'t')",[]]),
                   ('axis',["UPDATE jobs SET row_axis_index='x'",[]])]:
   self.make(name,{'jobs':[{'id':'a','name':'a'}]},[sql])
   self.assert_passes(name,name)
   py=self.python(name)
   if name in ('badjson','weekdays','axis','badint','badsettings'):self.assertEqual(py['status'],500,f'{name}: Python も落ちる値のはず')


RETRY=r"""
import json,os,sys,tempfile
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
real=os.replace;calls=[]
def busy(n):
 def f(a,b):
  calls.append(1)
  if len(calls)<=n:raise PermissionError(32,'別のプロセスが使用中')
  real(a,b)
 return f
out={}
with tempfile.TemporaryDirectory() as t:
 a,b=Path(t)/'a',Path(t)/'b';a.write_text('new',encoding='utf-8');b.write_text('old',encoding='utf-8')
 app.os.replace=busy(2);app.replace_retry(a,b,tries=5,wait=0)
 out['retried']=[len(calls),b.read_text(encoding='utf-8')]
 calls.clear();a.write_text('x',encoding='utf-8');app.os.replace=busy(99)
 try:app.replace_retry(a,b,tries=3,wait=0);out['gave_up']='no'
 except PermissionError:out['gave_up']=len(calls)
app.os.replace=real
print(json.dumps(out))
"""


class ReplaceRetryTest(unittest.TestCase):
 """Windows は開いているファイルを置き換えられない。Rust の中身が設定の写し・マスターを読んでいる数ミリ秒と、Python の取り込み・
 書き戻しが重なっても、置き換えを落とさず待つ（2.19.0。Linux では起きないので、置き換えが断られる場合を作って確かめる）。"""
 def test_waits_while_the_file_is_open(self):
  with tempfile.TemporaryDirectory() as t:
   e=dict(os.environ,DATARELAY_NO_BOOT='1',PYTHONIOENCODING='utf-8',NAVI_LOCAL_ROOT=str(Path(t)/'l'),NAVI_DATA_ROOT=str(Path(t)/'d'),
          NAVI_CONFIG_DIR=str(Path(t)/'d'/'C'),NAVI_SECRET_FILE=str(Path(t)/'s.json'))
   r=subprocess.run([ref_python(),'-c',RETRY,str(ROOT)],env=e,cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',timeout=300)
  self.assertEqual(r.returncode,0,r.stderr[-2000:])
  out=json.loads(r.stdout.strip().split('\n')[-1])
  self.assertEqual(out['retried'],[3,'new'],'2回断られても、3回目で置き換える')
  self.assertEqual(out['gave_up'],3,'ずっと断られるなら、決めた回数でやめて知らせる')

 def test_pull_and_flush_use_it(self):
  src=(ROOT/'app.py').read_text(encoding='utf-8')
  self.assertIn("shutil.copy2(MASTER_SETTINGS_DB,tmp); replace_retry(tmp,SETTINGS_DB)",src,'マスター → 写しの取り込み')
  self.assertIn("shutil.copy2(stage,tmp); replace_retry(tmp,MASTER_SETTINGS_DB)",src,'写し → マスターの書き戻し')


if __name__=='__main__':unittest.main()
