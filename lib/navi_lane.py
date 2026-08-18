"""何を、どの順で、いくつ同時に流すか ―― ラインの割り当て。

大まかな順番は決まっている。RNE → テキスト → 結合。ただしこれは「上から順に1つずつ」
という意味ではない。RNEはNavigatorへの問い合わせ待ち、テキストは手元のファイルの
読み書き待ちで、待つ相手が違う ―― 互いの材料にもならないので、同時に流してよい。
1.88.0まではテキストと結合を全部片付けてからRNEを始めていたので、どちらか一方が
走っているあいだ、もう一方のラインは空のまま待っていた。

順番が要るのは、材料を作る側と使う側のあいだだけ。だからここで決めるのは2つ。

  ・その対象の材料はそろっているか（そろっていないものは、まだ流さない）
  ・そろっているものが複数あるとき、どれを先に流すか（RNE → テキスト → 結合）

結合どうしが材料にし合っているときは、いちばん後ろへ回す ―― ほかが済んでからで
ないと、どのみち走れない。先に呼び出しても、順番待ちでラインを1本ふさぐだけになる。

判断はここに閉じてある。時計もスレッドもファイルも触らないので、実際に走らせずに
机の上で全部確かめられる（navi_order.py と同じ約束）。
"""

# 流す順の「大まかな順番」。同時に走れるものが複数あるとき、どれから配るか。
# 数が小さいほど先。RNEを先頭に置くのは、いちばん時間がかかり、しかも結合の材料に
# なりやすいから ―― 遅れて始めると、その遅れがそのまま後ろ全部に伝わる。
KIND_TIER={'rne':0,'text':1,'join':2}
TIER_JOIN_CHAIN=3
TIER_LABEL={0:'RNE',1:'テキスト',2:'結合',3:'結合（材料も結合）'}

# 手元の処理へ既定で何本ぶん割り当てるか（自動のとき）。青天井にすると共有フォルダー
# への読み書きが渋滞して、ラインを増やすほど遅くなる。
LOCAL_LINES_AUTO_MAX=4

LOCAL_KINDS=('text','join')


def build_plan(jobs,deps,kinds):
 """対象1件ごとに「種類・順位・待つ相手」を決める。並び順は増やしも減らしもしない。

 待つ相手は、この実行に入っているものだけに絞る。入っていない対象を待たせると、
 誰も動かしていないものを永遠に待つことになる（そちらは navi_order.py の
 待ち合わせが、別の実行や別のPCの様子を見て判断する）。
 """
 ids={j['id'] for j in jobs}
 plan=[]
 for n,j in enumerate(jobs):
  need={d for d in (deps.get(j['id']) or set()) if d in ids and d!=j['id']}
  plan.append({'id':j['id'],'name':j.get('name',''),'job':j,
               'kind':str(kinds.get(j['id']) or 'rne'),'order':n,'needs':need,'tier':0})
 by={e['id']:e for e in plan}
 for e in plan:
  t=KIND_TIER.get(e['kind'],KIND_TIER['join'])
  if t==KIND_TIER['join'] and any(by[d]['kind']=='join' for d in e['needs']):t=TIER_JOIN_CHAIN
  e['tier']=t
 return plan


def ready(plan,done,started,kinds=None):
 """いま流してよいものを、流す順に返す。

 材料がそろっていて、まだ誰も取っていないもの。同じだけ流せるなら、大まかな順番
 （RNE → テキスト → 結合）が先のものから。同じ順位のなかは登録順のまま。
 """
 done=set(done or ());started=set(started or ())
 out=[e for e in plan
      if e['id'] not in started and e['id'] not in done
      and (kinds is None or e['kind'] in kinds)
      and not (e['needs']-done)]
 out.sort(key=lambda e:(e['tier'],e['order']))
 return out


def unreachable(plan,failed,done=()):
 """材料が失敗したので、もう走れないもの。

 待たせ続けても材料は来ない。ここで見つけて「なぜ走らなかったか」を言うほうが、
 黙って順番待ちのまま終わるより直しようがある。孫（材料の材料）まで数える。
 """
 done=set(done or ());bad=set(failed or ())
 seed=set(bad)
 changed=True
 while changed:
  changed=False
  for e in plan:
   if e['id'] in bad or e['id'] in done:continue
   if e['needs']&bad:bad.add(e['id']);changed=True
 out=[e for e in plan if e['id'] in bad and e['id'] not in seed and e['id'] not in done]
 out.sort(key=lambda e:(e['tier'],e['order']))
 return out


def names_of(ids,plan):
 """idの一覧を、読める名前の一覧へ。並びは流す順（idの文字列順では意味を持たない）。"""
 by={e['id']:e for e in plan}
 return [by[i]['name'] for i in sorted(set(ids or ()),key=lambda x:(by[x]['tier'],by[x]['order']) if x in by else (99,99)) if i in by]


def blocking_names(entry,plan,done):
 """その対象が、いま誰を待っているのか。画面とログに出すための名前。"""
 return names_of(entry['needs']-set(done or ()),plan)


def local_lines(configured,batch_lines,local_count):
 """手元の処理（テキスト・結合）へ何本ぶん割り当てるか。

 0（自動）なら、並列ライン数に合わせて控えめに取る。RNEはNavigatorの応答待ち、
 手元の処理は読み書き待ちで、待つ相手が違う ―― 同じ本数を取り合っているわけでは
 ないので、RNEの持ち分から引くことはしない。
 """
 try:n=int(configured or 0)
 except Exception:n=0
 if n<=0:n=min(LOCAL_LINES_AUTO_MAX,max(1,int(batch_lines or 1)))
 return max(1,min(n,max(1,int(local_count or 1))))


def plan_text(plan):
 """並べ方を1行で。ログを読む人が「なぜこの順なのか」を追えるように。"""
 g={}
 for e in sorted(plan,key=lambda e:(e['tier'],e['order'])):g.setdefault(e['tier'],[]).append(e['name'])
 return ' → '.join(f'{TIER_LABEL.get(t,t)}: '+'・'.join(v) for t,v in sorted(g.items()))


def wait_text(plan):
 """材料を待つ対象と、その相手。順番が付いた理由を、そのまま読める形で。"""
 out=[]
 by={e['id']:e for e in plan}
 for e in sorted(plan,key=lambda e:(e['tier'],e['order'])):
  if not e['needs']:continue
  out.append(f'{e["name"]}←'+'・'.join(by[d]['name'] for d in sorted(e['needs']) if d in by))
 return '／'.join(out)
