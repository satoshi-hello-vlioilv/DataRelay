"""データビュワーの表示列・計算列・条件の中身（2.2.0。static/viewer-model.js）。

WaveLog（list-formula.js・filters.js）から移した式と条件、このアプリで足した日付の関数・日付とみなす列の判定・列の当て方を、
node で動かして確かめる。画面での動きは自己診断（desktop/src/selftest.js）が確かめる。

実行: python -m unittest tests.test_viewer_model -v
"""
import json,shutil,subprocess,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
MODEL=ROOT/'static'/'viewer-model.js'


class ViewerModelTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.node=shutil.which('node')
  if not cls.node:raise unittest.SkipTest('node がありません')

 def js(self,expr,data=None):
  code=f"const M=require({json.dumps(str(MODEL))});const D=JSON.parse(process.argv[1]);console.log(JSON.stringify({expr}));"
  r=subprocess.run([self.node,'-e',code,json.dumps(data or {},ensure_ascii=False)],capture_output=True,text=True,encoding='utf-8',timeout=60)
  self.assertEqual(r.returncode,0,r.stderr)
  return json.loads(r.stdout)

 def run_formula(self,src,row):
  return self.js("M.compile(D.src).run(n=>D.row[n])",{'src':src,'row':row})

 def test_date_parse_forms(self):
  got=self.js("D.v.map(x=>{const t=M.parseDate(x);return t&&[t.y,t.m,t.d,t.h,t.mi]})",
              {'v':['2026-10-01','2026/10/1 8:05','2026.1.31','2026年10月1日','2026年10月1日 08時12分','20261001','202610010812','2026-10-01T08:12:30',
                    '2026-02-30','45000','10/01','2026-13-01','abc','']})
  self.assertEqual(got,[[2026,10,1,0,0],[2026,10,1,8,5],[2026,1,31,0,0],[2026,10,1,0,0],[2026,10,1,8,12],[2026,10,1,0,0],[2026,10,1,8,12],[2026,10,1,8,12],
                        None,None,None,None,None,None],'日付の書き方を読み、ありえない日・数量（45000）・月日だけは読まない')

 def test_date_functions(self):
  row={'着手日時':'2026-10-01 08:12','完了日時':'2026/10/05 17:00','空':'','数量':'12'}
  self.assertEqual(self.run_formula('year([着手日時])',row),2026)
  self.assertEqual(self.run_formula('ym([着手日時])',row),'2026-10')
  self.assertEqual(self.run_formula('date([着手日時])',row),'2026-10-01')
  self.assertEqual(self.run_formula('month([着手日時])',row),10)
  self.assertEqual(self.run_formula('day([着手日時])',row),1)
  self.assertEqual(self.run_formula('quarter([着手日時])',row),'2026-Q4')
  self.assertEqual(self.run_formula('week([着手日時])',row),'2026-W40')
  self.assertEqual(self.run_formula('weekday([着手日時])',row),'木')
  self.assertEqual(self.run_formula('hour([着手日時])',row),8)
  self.assertEqual(self.run_formula('fy([着手日時])',row),2026)
  self.assertEqual(self.run_formula("fy('2026-03-31')",row),2025,'年度は4月始まり')
  self.assertEqual(self.run_formula("fy('2026-03-31', 1)",row),2026,'開始月を変えられる')
  self.assertEqual(self.run_formula('days([着手日時], [完了日時])',row),4)
  self.assertIsNone(self.run_formula('ym([空])',row),'読めない値は空')
  self.assertIsNone(self.run_formula('year([数量])',row))
  self.assertEqual(self.run_formula("week('2027-01-01')",row),'2026-W53','年をまたぐ週は ISO の数え方')

 def test_ported_formula_semantics(self):
  row={'品番':'P-1023','枝番':'01','コード':'010','数量':'1,200','単価':'3'}
  self.assertEqual(self.run_formula('[品番]+[枝番]',row),'P-102301','片方が字なら連結')
  self.assertEqual(self.run_formula('[数量]*[単価]',row),3600,'3桁区切りの数も計算できる')
  self.assertEqual(self.run_formula('[コード] = 10',row),0,'先頭ゼロのコードを 10 と取り違えない')
  self.assertEqual(self.run_formula("if([数量] > 1000, '大口', '小口')",row),'大口','正しく3桁で区切った数は、比べるときも数')
  self.assertEqual(self.run_formula("[数量] = 1200",row),1)
  self.assertEqual(self.run_formula("mid([品番], 3, 2)",row),'10')
  self.assertEqual(self.run_formula("extract([品番], '(\\d+)', 1)",row),'1023')
  self.assertIsNone(self.run_formula('[数量] / 0',row),'0で割ると空（誤りにしない）')

 def test_check_reports_errors_while_typing(self):
  got=self.js("D.v.map(s=>M.check(s,['着手日時']))",{'v':['ym([着手日時])','ym([着手日時]','foo([着手日時])','ym([無い列])','year()','','eval("1")']})
  self.assertTrue(got[0]['ok'])
  self.assertEqual(got[1]['error'],') が必要です')
  self.assertEqual(got[2]['error'],'知らない関数です: foo')
  self.assertEqual(got[3]['error'],'無い列です: 無い列')
  self.assertEqual(got[4]['error'],'year は引数が1個です（0個でした）')
  self.assertEqual(got[5]['error'],'式を入力してください')
  self.assertFalse(got[6]['ok'],'eval は関数として使えない')

 def test_sigs_cover_funcs(self):
  got=self.js("[M.funcNames.slice().sort(),M.sigs.map(s=>s[0]).filter(n=>!['if','and','or','not'].includes(n)).sort()]")
  self.assertEqual(got[0],got[1],'関数の説明（sigs）と中身（FUNCS）が同じ顔ぶれ')

 def test_date_info(self):
  got=self.js("[M.dateInfo(D.a),M.dateInfo(D.b),M.dateInfo(D.c),M.dateInfo(D.d)]",
              {'a':['2026-10-01 08:12','2026-10-02 09:00','',None],'b':['2026-10-01','2026-10-02'],'c':['12','30','45000'],'d':['2026-10-01']+['x']*2})
  self.assertEqual(got,[{'date':True,'hasTime':True},{'date':True,'hasTime':False},{'date':False,'hasTime':False},{'date':False,'hasTime':False}])
  self.assertEqual(self.js("[M.datePartName('着手日時','ym'),M.datePartFormula('着手日時','ym'),M.datePartName('着手日時','fy')]"),
                   ['着手日時（年月）','ym([着手日時])','着手日時（年度）'])
  self.assertEqual(self.js("['ym([着手日時])',' date( [完了 日時] ) ','upper([品名])','ym([a])+1','fy([x], 1)'].map(M.datePartOf)"),
                   [['着手日時','ym'],['完了 日時','date'],None,None,None],'日付のまとめの式だけを見分ける（集計の札でまとめ方を切り替える）')

 def test_conditions(self):
  cases=[('contains','LS4-東','ls4',True),('contains','ＬＳ４','LS4',True),('not_contains','LS4','LS3',True),('eq','010','10',True),('eq','A','a',True),('neq','A','B',True),
         ('starts','P-1023','P-',True),('ends','P-1023','23',True),('gt','1,200','1000',True),('lte','5','05',True),
         ('gte','2026-10-05 08:00','2026-10-01',True),('lt','2026/9/30','2026-10-01',True),('lt','2026-10-01 09:00','2026-10-01 08:00',False),
         ('eq','2026-10-01 08:12','2026-10-01',True),('eq','2026-10-01 08:12','2026-10-01 08:13',False),
         ('gt','','5',False),('empty','  ','',True),('not_empty','x','',True)]
  got=self.js("D.c.map(([op,c,v])=>M.condMatch(op,c,v))",{'c':[[a,b,c] for a,b,c,_ in cases]})
  self.assertEqual(got,[x[3] for x in cases],'比べ方（数→日付→字・全角半角と大文字小文字は同じとみなす）')

 def test_apply_view(self):
  table={'headers':['工程','着手日時','数量'],'rows':[['研削','2026-09-30 08:00','3'],['研削','2026-10-01 09:00','5'],['検査','2026-10-02 10:00','2'],['検査','','1']]}
  view={'cols':[{'key':'着手日時（年月）','show':True,'label':'年月'},{'key':'工程','show':True},{'key':'数量','show':False}],
        'calc':[{'name':'着手日時（年月）','formula':'ym([着手日時])'},{'name':'倍','formula':'[数量]*2'},{'name':'壊れ','formula':'ym([着手日時]'},{'name':'工程','formula':'1'}],
        'filters':[{'column':'着手日時','op':'gte','value':'2026-10-01'},{'column':'無い','op':'eq','value':'x'},{'column':'工程','op':'eq','value':''}],'join':'and'}
  v=self.js("M.applyView(D.t,D.v)",{'t':table,'v':view})
  self.assertEqual(v['headers'],['工程','着手日時','数量','着手日時（年月）','倍','壊れ'],'計算列は元の列の後ろ。元の列と同じ名前の計算列は足さない')
  self.assertEqual([r[3] for r in v['rows']],['2026-09','2026-10','2026-10',None])
  self.assertEqual([r[4] for r in v['rows']],[6,10,4,2])
  self.assertEqual(set(v['calcErrors']),{'壊れ','工程'})
  self.assertEqual(v['order'],[3,0,2,1,4,5],'並びは cols の順、載っていない列は後ろへ元の順で')
  self.assertEqual(v['shown'],[3,0,1,4,5],'隠した列（数量）は見せない')
  self.assertEqual(v['labels'][3],'年月')
  self.assertEqual([r[0] for r in v['filtered']],['研削','検査'],'条件で絞る（値が空の条件は効かせない）')
  self.assertEqual(v['filterErrors'],['列「無い」がありません（この条件は効いていません）'])
  orv=self.js("M.applyView(D.t,D.v).filtered.length",{'t':table,'v':{'filters':[{'column':'工程','op':'eq','value':'検査'},{'column':'数量','op':'gte','value':'5'}],'join':'or'}})
  self.assertEqual(orv,3,'または')


if __name__=='__main__':
 unittest.main()
