"use strict";
/* viewer-model.js: データビュワーの「表示列・計算列・条件」の中身（2.2.0）。画面には触らない。
   ============================================================
   WaveLog（list-formula.js・filters.js・list-columns.js）の作りをこのアプリへ移したもの。
     ・式で作る列（計算列）。**eval を使わない**——式は利用者が書き、対象の設定として保存され、
       持ち出しで別のPCでも動く。自前で字句解析→構文解析→評価をし、書ける物を最初から限る。
     ・壊れた式は列ごと落とさず、その行だけ空にする。誤りは書いている最中に check() が言う。
     ・条件（絞り込み）は WaveLog と同じ12の比べ方。数に読めれば数で、日付に読めれば日付で比べる。
   このアプリで足したもの:
     ・日付の関数（year・month・day・ym・date・quarter・week・weekday・hour・fy・days）。
       集計で「年・年月・年月日…でまとめる」は、この関数を使う計算列として作る（汎用の列の仕組みの中）。
     ・日付とみなせる列の判定（dateInfo）。
     ・列の当て方（applyView）: 元の表＋計算列 → 並び・表示・表示名 → 条件で絞る。
   画面（app.js）は window.DRV を、試験（tests/test_viewer_model.py）は node の require で使う。 */
(function(root){
 const MAX_LEN=2000;
 const NUM=/^\d+(\.\d+)?/;

 /* ---------- 字句解析 ---------- */
 function lex(src){
  const out=[];let i=0;const s=String(src||'');
  while(i<s.length){
   const ch=s[i];
   if(/\s/.test(ch)){i++;continue}
   if(ch==='['){const end=s.indexOf(']',i+1);if(end<0)throw Error('列名の [ ] が閉じていません');out.push({t:'col',v:s.slice(i+1,end)});i=end+1;continue}
   if(ch==="'"||ch==='"'){const q=ch;let j=i+1,buf='';while(j<s.length&&s[j]!==q){buf+=s[j];j++}
    if(j>=s.length)throw Error('文字列の引用符が閉じていません');out.push({t:'str',v:buf});i=j+1;continue}
   const m=s.slice(i).match(NUM);
   if(m){out.push({t:'num',v:parseFloat(m[0])});i+=m[0].length;continue}
   const two=s.slice(i,i+2);
   if(two==='<='||two==='>='||two==='<>'||two==='!='){out.push({t:'op',v:two==='!='?'<>':two});i+=2;continue}
   if('+-*/%(),'.includes(ch)){out.push({t:ch==='('||ch===')'||ch===','?ch:'op',v:ch});i++;continue}
   if(ch==='='||ch==='<'||ch==='>'){out.push({t:'op',v:ch});i++;continue}
   const w=s.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
   if(w){out.push({t:'name',v:w[0].toLowerCase()});i+=w[0].length;continue}
   throw Error(`使えない文字です: ${ch}`);
  }
  return out;
 }

 /* ---------- 構文解析（下降型） ---------- */
 function parse(src){
  if(String(src||'').length>MAX_LEN)throw Error(`式が長すぎます（${MAX_LEN}文字まで）`);
  const ts=lex(src);let p=0;
  const peek=()=>ts[p];
  const eat=(t,v)=>{const x=ts[p];if(!x||x.t!==t||(v!==undefined&&x.v!==v))return null;p++;return x};
  const expect=(t,v)=>{const x=eat(t,v);if(!x)throw Error(`${v||t} が必要です`);return x};
  const isName=v=>peek()&&peek().t==='name'&&peek().v===v;
  const isOp=list=>peek()&&peek().t==='op'&&list.includes(peek().v);
  function orExpr(){let n=andExpr();while(isName('or')){p++;n={k:'or',a:n,b:andExpr()}}return n}
  function andExpr(){let n=cmpExpr();while(isName('and')){p++;n={k:'and',a:n,b:cmpExpr()}}return n}
  function cmpExpr(){let n=addExpr();while(isOp(['=','<>','<','<=','>','>='])){const op=ts[p++].v;n={k:'cmp',op,a:n,b:addExpr()}}return n}
  function addExpr(){let n=mulExpr();while(isOp(['+','-'])){const op=ts[p++].v;n={k:'bin',op,a:n,b:mulExpr()}}return n}
  function mulExpr(){let n=unary();while(isOp(['*','/','%'])){const op=ts[p++].v;n={k:'bin',op,a:n,b:unary()}}return n}
  function unary(){
   if(isOp(['-'])){p++;return {k:'neg',a:unary()}}
   if(isName('not')){p++;return {k:'not',a:unary()}}
   return atom();
  }
  function atom(){
   const x=peek();if(!x)throw Error('式が途中で終わっています');
   if(x.t==='num'){p++;return {k:'num',v:x.v}}
   if(x.t==='str'){p++;return {k:'str',v:x.v}}
   if(x.t==='col'){p++;return {k:'col',v:x.v}}
   if(x.t==='('){p++;const n=orExpr();expect(')');return n}
   if(x.t==='name'){
    p++;
    if(!eat('('))throw Error(`関数の ( が必要です: ${x.v}`);
    const args=[];
    if(!eat(')')){args.push(orExpr());while(eat(','))args.push(orExpr());expect(')')}
    /* 知らない関数・引数の数の誤りはここで断る（評価まで待つと、実データの行が全部空になってから気づく） */
    if(x.v!=='if'&&!Object.prototype.hasOwnProperty.call(FUNCS,x.v))throw Error(`知らない関数です: ${x.v}`);
    if(x.v==='if'&&args.length<2)throw Error('if は if(条件, 真のとき, 偽のとき) です');
    const need=ARITY[x.v];
    if(need!==undefined&&args.length!==need)throw Error(`${x.v} は引数が${need}個です（${args.length}個でした）`);
    const rng=ARITY_RANGE[x.v];
    if(rng&&(args.length<rng[0]||args.length>rng[1]))throw Error(`${x.v} は引数が${rng[0]}〜${rng[1]}個です（${args.length}個でした）`);
    if(REGEX_FUNCS.has(x.v)&&args[1]&&args[1].k==='str'){try{reOf(String(args[1].v),'')}catch(e){throw Error(`${x.v} の正規表現として読めません: ${e.message}`)}}
    return {k:'call',name:x.v,args};
   }
   throw Error('式として読めません');
  }
  const node=orExpr();
  if(p<ts.length)throw Error('式の後ろに余分なものがあります');
  return node;
 }

 /* ---------- 値の読み方 ---------- */
 const textOf=v=>v===null||v===undefined?'':String(v);
 const numOf=v=>{if(v===null||v===undefined||v==='')return null;if(typeof v==='number')return v;const n=parseFloat(String(v).replace(/,/g,''));return Number.isFinite(n)?n:null};
 const truthy=v=>{const n=numOf(v);return n===null?textOf(v)!=='':n!==0};
 /* 表示ルール・条件の比べ方（WaveLog §9.477）: 両辺が数に読めれば数で（前後の空白・3桁区切り・先頭ゼロ・+ を許す）。 */
 const LOOSE_NUM=/^[-+]?(\d+\.?\d*|\.\d+)$/;
 const looseNum=v=>{const t=textOf(v).trim().replace(/,/g,'');if(!t||!LOOSE_NUM.test(t))return null;const n=Number(t);return Number.isFinite(n)?n:null};
 /* 比較演算子（=など）は厳しく読む: 元の字へ戻して一致するときだけ数（'010' = 10 を真にしない。先頭ゼロのコードの照合を壊さない） */
 /* このアプリで足した: 正しく3桁で区切った数（1,200・12,345.5）も数（先頭ゼロの心配が無い書き方なので） */
 const THOUSANDS=/^-?[1-9]\d{0,2}(,\d{3})+(\.\d+)?$/;
 const strictNum=v=>{if(typeof v==='number')return v;const s=textOf(v).trim();if(s==='')return null;if(THOUSANDS.test(s))return Number(s.replace(/,/g,''));const n=Number(s);return Number.isFinite(n)&&String(n)===s?n:null};

 /* ---------- 日付（このアプリで足した） ----------
    日付とみなす書き方: 2026-10-01 / 2026/10/1 / 2026.10.1 / 2026年10月1日 / 20261001（8桁）。後ろに時刻（08:12・8:12:30・
    T08:12）が続いてもよい。12〜14桁の数字（202610010812）も年月日時分（秒）として読む。月日の範囲が合わない物は日付としない。
    Excel の日付の通し番号（45000 など）は数量と見分けられないので読まない。 */
 const DATE_RE=/^\s*(\d{4})\s*(?:[-\/.]|年)\s*(\d{1,2})\s*(?:[-\/.]|月)\s*(\d{1,2})\s*日?(?:[ T　]+(\d{1,2})[:時](\d{1,2})分?(?::?(\d{1,2})(?:[.,]\d+)?秒?)?)?\s*$/;
 const COMPACT_RE=/^\s*(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(\d{2})?)?\s*$/;
 const pad=(n,w=2)=>String(n).padStart(w,'0');
 function parseDate(v){
  if(v===null||v===undefined)return null;
  if(v instanceof Date)return Number.isNaN(v.getTime())?null:{y:v.getFullYear(),m:v.getMonth()+1,d:v.getDate(),h:v.getHours(),mi:v.getMinutes(),s:v.getSeconds()};
  const s=String(v);if(s.length>40)return null;
  let m=s.match(DATE_RE)||s.match(COMPACT_RE);
  if(!m)return null;
  const y=+m[1],mo=+m[2],d=+m[3],h=m[4]===undefined?0:+m[4],mi=m[5]===undefined?0:+m[5],se=m[6]===undefined?0:+m[6];
  if(y<1900||y>2999||mo<1||mo>12||d<1||h>23||mi>59||se>59)return null;
  const last=new Date(Date.UTC(y,mo,0)).getUTCDate();
  if(d>last)return null;
  return {y,m:mo,d,h,mi,s:se};
 }
 const isoOf=t=>`${t.y}-${pad(t.m)}-${pad(t.d)}`;
 const stampOf=t=>`${isoOf(t)} ${pad(t.h)}:${pad(t.mi)}:${pad(t.s)}`;
 const dayNo=t=>Math.floor(Date.UTC(t.y,t.m-1,t.d)/86400000);
 const WEEKDAY='日月火水木金土';
 function isoWeek(t){
  const d=new Date(Date.UTC(t.y,t.m-1,t.d)),wd=(d.getUTCDay()+6)%7;
  d.setUTCDate(d.getUTCDate()-wd+3);
  const y=d.getUTCFullYear(),first=new Date(Date.UTC(y,0,4));
  const w=1+Math.round(((d-first)/86400000-3+((first.getUTCDay()+6)%7))/7);
  return `${y}-W${pad(w)}`;
 }
 const dateFn=f=>a=>{const t=parseDate(a[0]);return t?f(t,a):null};
 /* 年度: 既定は4月始まり（引数で開始月を変えられる） */
 const fyOf=(t,start)=>{const st=Math.max(1,Math.min(12,start||4));return t.m>=st?t.y:t.y-1};

 /* ---------- 文字列の抽出・変換（WaveLog §9.464） ---------- */
 const RE_MAX=200,reCache=new Map();
 function reOf(src,flags){const k=flags+'\u0000'+src;if(reCache.has(k))return reCache.get(k);
  if(src.length>RE_MAX)throw Error(`正規表現は${RE_MAX}文字までです`);const re=new RegExp(src,flags);if(reCache.size>200)reCache.clear();reCache.set(k,re);return re}
 const posOf=v=>{const n=numOf(v);return n===null?1:Math.max(1,Math.floor(n))};
 function cmp(a,b){
  const x=looseNum(a),y=looseNum(b);
  if(x!==null&&y!==null)return x<y?-1:x>y?1:0;
  const da=parseDate(a),db=parseDate(b);
  if(da&&db){const s=stampOf(da),t=stampOf(db);return s<t?-1:s>t?1:0}
  const s=textOf(a),t=textOf(b);return s<t?-1:s>t?1:0;
 }
 const FUNCS={
  num:a=>numOf(a[0]),text:a=>textOf(a[0]),
  abs:a=>{const n=numOf(a[0]);return n===null?null:Math.abs(n)},
  round:a=>{const n=numOf(a[0]);if(n===null)return null;const d=Math.max(0,Math.min(8,numOf(a[1])||0)),p=Math.pow(10,d);return Math.round(n*p)/p},
  len:a=>textOf(a[0]).length,
  left:a=>textOf(a[0]).slice(0,Math.max(0,numOf(a[1])||0)),
  right:a=>{const n=Math.max(0,numOf(a[1])||0);return n?textOf(a[0]).slice(-n):''},
  trim:a=>textOf(a[0]).trim(),upper:a=>textOf(a[0]).toUpperCase(),lower:a=>textOf(a[0]).toLowerCase(),
  concat:a=>a.map(textOf).join(''),
  coalesce:a=>{for(const v of a){if(v!==null&&v!==undefined&&v!=='')return v}return ''},
  mid:a=>{const t=textOf(a[0]),st=posOf(a[1])-1,n=a.length>2?Math.max(0,numOf(a[2])||0):t.length;return t.slice(st,st+n)},
  find:a=>{const i=textOf(a[0]).indexOf(textOf(a[1]));return i<0?0:i+1},
  replace:a=>textOf(a[0]).split(textOf(a[1])).join(textOf(a[2])),
  extract:a=>{const m=textOf(a[0]).match(reOf(textOf(a[1]),''));if(!m)return '';const g=a.length>2?Math.max(0,numOf(a[2])||0):0;return m[g]===undefined?'':m[g]},
  match:a=>reOf(textOf(a[1]),'').test(textOf(a[0]))?1:0,
  regreplace:a=>textOf(a[0]).replace(reOf(textOf(a[1]),'g'),textOf(a[2])),
  split:a=>{const sep=textOf(a[1]),parts=sep?textOf(a[0]).split(sep):[textOf(a[0])],v=parts[posOf(a[2])-1];return v===undefined?'':v},
  contains:a=>textOf(a[0]).includes(textOf(a[1]))?1:0,
  cmp:a=>cmp(a[0],a[1]),
  startswith:a=>textOf(a[0]).startsWith(textOf(a[1]))?1:0,
  endswith:a=>textOf(a[0]).endsWith(textOf(a[1]))?1:0,
  hankaku:a=>textOf(a[0]).normalize('NFKC'),
  padleft:a=>textOf(a[0]).padStart(Math.max(0,Math.min(64,numOf(a[1])||0)),a.length>2?(textOf(a[2])||'0'):'0'),
  /* 日付（読めない値は空） */
  date:dateFn(t=>isoOf(t)),
  year:dateFn(t=>t.y),
  month:dateFn(t=>t.m),
  day:dateFn(t=>t.d),
  ym:dateFn(t=>`${t.y}-${pad(t.m)}`),
  quarter:dateFn(t=>`${t.y}-Q${Math.ceil(t.m/3)}`),
  week:dateFn(t=>isoWeek(t)),
  weekday:dateFn(t=>WEEKDAY[new Date(Date.UTC(t.y,t.m-1,t.d)).getUTCDay()]),
  hour:dateFn(t=>t.h),
  fy:dateFn((t,a)=>fyOf(t,numOf(a[1]))),
  days:a=>{const x=parseDate(a[0]),y=parseDate(a[1]);return x&&y?dayNo(y)-dayNo(x):null},
 };
 const ARITY={cmp:2,num:1,text:1,abs:1,round:2,len:1,left:2,right:2,trim:1,upper:1,lower:1,find:2,replace:3,match:2,regreplace:3,split:3,contains:2,startswith:2,endswith:2,hankaku:1,
  date:1,year:1,month:1,day:1,ym:1,quarter:1,week:1,weekday:1,hour:1,days:2};
 const ARITY_RANGE={mid:[2,3],extract:[2,3],padleft:[2,3],fy:[1,2]};
 const REGEX_FUNCS=new Set(['extract','match','regreplace']);

 function evalNode(n,get){
  switch(n.k){
   case 'num':case 'str':return n.v;
   case 'col':{const v=get(n.v);return v===undefined?null:v}
   case 'neg':{const a=numOf(evalNode(n.a,get));return a===null?null:-a}
   case 'not':return truthy(evalNode(n.a,get))?0:1;
   case 'and':return (truthy(evalNode(n.a,get))&&truthy(evalNode(n.b,get)))?1:0;
   case 'or':return (truthy(evalNode(n.a,get))||truthy(evalNode(n.b,get)))?1:0;
   case 'cmp':{const a=evalNode(n.a,get),b=evalNode(n.b,get),x=strictNum(a),y=strictNum(b);
    const [l,r]=(x!==null&&y!==null)?[x,y]:[textOf(a),textOf(b)];
    switch(n.op){case '=':return l===r?1:0;case '<>':return l!==r?1:0;case '<':return l<r?1:0;case '<=':return l<=r?1:0;case '>':return l>r?1:0;default:return l>=r?1:0}}
   case 'bin':{const a=evalNode(n.a,get),b=evalNode(n.b,get);
    if(n.op==='+'){const x=numOf(a),y=numOf(b);if(x!==null&&y!==null)return x+y;return textOf(a)+textOf(b)}
    const x=numOf(a),y=numOf(b);if(x===null||y===null)return null;
    if(n.op==='-')return x-y;if(n.op==='*')return x*y;if(n.op==='/')return y===0?null:x/y;return y===0?null:x%y}
   case 'call':{
    if(n.name==='if')return truthy(evalNode(n.args[0],get))?evalNode(n.args[1],get):(n.args.length>2?evalNode(n.args[2],get):'');
    return FUNCS[n.name](n.args.map(a=>evalNode(a,get)));
   }
  }
  return null;
 }
 function columnsUsed(node,out){out=out||new Set();if(!node||typeof node!=='object')return out;if(node.k==='col')out.add(node.v);
  ['a','b'].forEach(k=>{if(node[k])columnsUsed(node[k],out)});(node.args||[]).forEach(a=>columnsUsed(a,out));return out}
 /* 式を1回だけ解いて使い回す。run(get) の get は「列名 → その行の値」 */
 function compile(src){const node=parse(src);return {columns:[...columnsUsed(node)],run(get){try{return evalNode(node,get)}catch(e){return null}}}}
 function check(src,known){
  if(!String(src||'').trim())return {ok:false,error:'式を入力してください'};
  try{const c=compile(src);if(known){const miss=c.columns.filter(x=>!known.includes(x));if(miss.length)return {ok:false,error:`無い列です: ${miss.join('・')}`}}return {ok:true,columns:c.columns}}
  catch(e){return {ok:false,error:e.message}}
 }

 /* ---------- 日付とみなせる列（このアプリで足した） ----------
    空でない値を最大 sample 件見て、9割以上が日付に読めれば日付の列。時刻を持つ値があれば hasTime。 */
 function dateInfo(values,sample=300){
  let seen=0,ok=0,time=false;
  for(const v of values){const s=textOf(v).trim();if(!s)continue;if(++seen>sample)break;const t=parseDate(s);if(t){ok++;if(t.h||t.mi||t.s||/[:時T]/.test(s))time=true}}
  return {date:seen>0&&ok/Math.min(seen,sample)>=0.9,hasTime:time};
 }
 /* 日付の列から作れる「まとめ方」。集計の日付のまとめも、この式の計算列として作る */
 const DATE_PARTS=[
  ['year','年','year'],['ym','年月','ym'],['date','年月日','date'],['quarter','四半期','quarter'],['week','週','week'],
  ['month','月（年をまたいで）','month'],['weekday','曜日','weekday'],['hour','時','hour'],['fy','年度（4月始まり）','fy'],
 ];
 const datePart=k=>DATE_PARTS.find(x=>x[0]===k)||null;
 const datePartName=(col,k)=>{const p=datePart(k);return p?`${col}（${p[1].replace(/（.*）/,'')}）`:col};
 const datePartFormula=(col,k)=>{const p=datePart(k);return p?`${p[2]}([${col}])`:''};

 /* ---------- 条件（WaveLog filters.js の12の比べ方） ---------- */
 const OPS=[['contains','含む'],['not_contains','含まない'],['eq','＝ 一致'],['neq','≠ 不一致'],['starts','前方一致'],['ends','後方一致'],
  ['gt','> より大きい'],['gte','>= 以上'],['lt','< より小さい'],['lte','<= 以下'],['empty','空欄'],['not_empty','空欄以外']];
 const noValueOp=op=>op==='empty'||op==='not_empty';
 const fold=v=>textOf(v).normalize('NFKC').toLowerCase();
 /* 1つの条件が、その行の値に合うか。等しいかは字で（大文字小文字・全角半角は同じとみなす）、大小は cmp（数→日付→字） */
 function condMatch(op,cell,value){
  const c=fold(cell).trim(),v=fold(value).trim();
  switch(op){
   case 'contains':return c.includes(v);
   case 'not_contains':return !c.includes(v);
   case 'eq':return c===v||(looseNum(cell)!==null&&looseNum(cell)===looseNum(value))||sameDate(cell,value);
   case 'neq':return !(c===v||(looseNum(cell)!==null&&looseNum(cell)===looseNum(value))||sameDate(cell,value));
   case 'starts':return c.startsWith(v);
   case 'ends':return c.endsWith(v);
   case 'gt':return c!==''&&cmp(cell,value)>0;
   case 'gte':return c!==''&&cmp(cell,value)>=0;
   case 'lt':return c!==''&&cmp(cell,value)<0;
   case 'lte':return c!==''&&cmp(cell,value)<=0;
   case 'empty':return c==='';
   case 'not_empty':return c!=='';
  }
  return true;
 }
 /* 日付だけ書いた条件（2026-10-01）は、時刻つきの値（2026-10-01 08:12）にも一致とみなす */
 function sameDate(cell,value){const a=parseDate(cell),b=parseDate(value);if(!a||!b)return false;
  return /\d[:時]/.test(textOf(value))?stampOf(a)===stampOf(b):isoOf(a)===isoOf(b)}

 /* ---------- 列の当て方 ----------
    view = {cols:[{key,show,label}], calc:[{name,formula}], filters:[{column,op,value}], join:'and'|'or'}
    1. 元の表（headers・rows）の後ろに、計算列を順に足す（前の計算列を式で使える）
    2. 並び（cols の順。載っていない列は後ろへ、元の順で）と表示（show）と表示名（label）を決める
    3. 条件で行を絞る
    返す: {headers（元の名前＋計算列の名前）, rows（足した後の行）, order（見せる順の列番号。隠す列も含む）,
           shown（見せる列番号）, labels（列番号→表示名）, calcErrors（名前→誤り）, filtered（条件に合う行）, filterErrors} */
 function applyView(table,view){
  view=view||{};
  const src=(table&&table.headers)||[],rowsIn=(table&&table.rows)||[];
  const headers=src.slice(),calcErrors={},calcs=[];
  for(const c of (view.calc||[])){
   const name=textOf(c&&c.name).trim();
   if(!name||headers.includes(name)){if(name)calcErrors[name]='同じ名前の列があります';continue}
   const chk=check(c.formula,headers);
   headers.push(name);
   if(!chk.ok){calcErrors[name]=chk.error;calcs.push(null);continue}
   calcs.push(compile(c.formula));
  }
  const at=new Map(headers.map((h,i)=>[h,i]));
  const rows=calcs.length?rowsIn.map(r=>{const out=r.slice();for(let k=0;k<calcs.length;k++){const f=calcs[k];
    out[src.length+k]=f?f.run(n=>{const i=at.get(n);return i===undefined||i>=out.length?null:out[i]}):null}return out}):rowsIn;
  const seen=new Set(),order=[];
  for(const c of (view.cols||[])){const i=at.get(c&&c.key);if(i!==undefined&&!seen.has(i)){seen.add(i);order.push(i)}}
  headers.forEach((_,i)=>{if(!seen.has(i))order.push(i)});
  const hidden=new Set((view.cols||[]).filter(c=>c&&c.show===false).map(c=>at.get(c.key)).filter(i=>i!==undefined));
  const shown=order.filter(i=>!hidden.has(i));
  const labels=headers.map((h,i)=>{const c=(view.cols||[]).find(x=>x&&x.key===h);return (c&&textOf(c.label).trim())||h});
  const {rows:filtered,errors:filterErrors}=applyFilters(headers,rows,view.filters,view.join);
  return {headers,rows,order,shown,labels,calcErrors,filtered,filterErrors};
 }
 function applyFilters(headers,rows,filters,join){
  const errors=[],conds=[];
  for(const f of (filters||[])){
   if(!f)continue;const i=headers.indexOf(f.column);
   if(i<0){errors.push(`列「${f.column}」がありません（この条件は効いていません）`);continue}
   if(!OPS.some(o=>o[0]===f.op)){errors.push(`比べ方「${f.op}」を知りません`);continue}
   if(!noValueOp(f.op)&&textOf(f.value).trim()==='')continue;
   conds.push([i,f.op,f.value]);
  }
  if(!conds.length)return {rows,errors};
  const any=join==='or';
  return {rows:rows.filter(r=>any?conds.some(([i,op,v])=>condMatch(op,r[i],v)):conds.every(([i,op,v])=>condMatch(op,r[i],v))),errors};
 }
 const condLabel=f=>`${f.column} ${(OPS.find(o=>o[0]===f.op)||[,f.op])[1]}${noValueOp(f.op)?'':' '+textOf(f.value)}`;

 /* 関数の名前と引数の形（候補の表示・説明に使う。FUNCS に足したらここにも足す。試験が突き合わせる） */
 const SIGS=[
  ['if','条件, 真のとき, 偽のとき','条件で切り替える'],['and','','論理（a and b）'],['or','','論理（a or b）'],['not','','論理（not a）'],
  ['round','x, 桁','四捨五入'],['abs','x','絶対値'],['num','x','数として読む'],['text','x','文字として読む'],
  ['len','x','文字数'],['left','x, 文字数','左から切り出す'],['right','x, 文字数','右から切り出す'],['mid','x, 何文字目, 文字数','途中を切り出す（位置は1から）'],
  ['find','x, 字','字の位置（無ければ0）'],['split','x, 区切り, 何番目','区切って何番目か'],['trim','x','前後の空白を取る'],
  ['upper','x','大文字へ'],['lower','x','小文字へ'],['concat','a, b','つなぐ'],['coalesce','a, b','空ならb'],
  ['replace','x, 字, 置く字','字を置き換える'],['regreplace','x, 正規表現, 置く字','正規表現で置き換える'],['hankaku','x','全角の英数を半角へ'],['padleft','x, 桁, 字','左を字で埋める'],
  ['extract','x, 正規表現, 組','正規表現で抜き出す'],['match','x, 正規表現','正規表現に合うか'],['contains','x, 字','字を含むか'],
  ['cmp','a, b','比べる（数→日付→字・-1／0／1）'],['startswith','x, 字','字で始まるか'],['endswith','x, 字','字で終わるか'],
  ['date','x','日付（2026-10-01）'],['year','x','年（2026）'],['month','x','月（1〜12）'],['day','x','日（1〜31）'],['ym','x','年月（2026-10）'],
  ['quarter','x','四半期（2026-Q4）'],['week','x','週（2026-W40・月曜始まり）'],['weekday','x','曜日（月〜日）'],['hour','x','時（0〜23）'],
  ['fy','x, 開始月','年度（既定は4月始まり）'],['days','a, b','a から b までの日数'],
 ];
 const API={parse,compile,check,cmp,truthy,parseDate,dateInfo,DATE_PARTS,datePart,datePartName,datePartFormula,
  OPS,noValueOp,condMatch,condLabel,applyView,applyFilters,sigs:SIGS,funcNames:Object.keys(FUNCS),MAX_LEN};
 if(typeof module==='object'&&module.exports)module.exports=API;
 else root.DRV=API;
})(typeof window!=='undefined'?window:globalThis);
