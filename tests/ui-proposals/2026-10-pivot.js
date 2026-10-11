// 2.1.3 集計表の組み立て方の案（CLAUDE.md §3）。
// 不具合: Windows の窓（Tauri）が WebView2 の D&D を横取りし、カラムを行・列・値へ置けなかった。
// 窓の側は直すが、D&D だけに頼らず、押すだけで組めて、組んだ状態が一目で分かる形を比べる。
// 本物の画面の #viewer-analysis（データビュワーの集計表の欄）と同じ位置に重ねた箱（body の直下）へ描く。
// 表の数は本物のデータ（viewerFiltered）から数える。
// 撮り方: 撮影用の仕掛けで window.PX.show(k, view)。view 1 = 集計表を開いた直後（何も置いていない）、
// view 2 = 行に「工程」、列に「作業者」、件数を数えたところ。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const H = () => (typeof viewerData !== 'undefined' && viewerData?.headers) || ['仕掛区分', 'BOX実績_設備名', 'ﾛｯﾄ番号', '品名', '工程', '数量', '着手日時', '完了日時', '作業者', '不良数'];
 const ROWS = () => (typeof viewerFiltered !== 'undefined' && viewerFiltered) || [];
 const ROLE = { rows: '行', columns: '列', values: '値' };
 const ix = n => H().indexOf(n);
 // ---- 数える（本物のデータから） ----
 function count(rf, cf) {
  const rs = ROWS(), r = ix(rf), c = ix(cf), rk = [], ck = [], m = new Map();
  for (const x of rs) { const a = String(x[r] ?? ''), b = String(x[c] ?? ''); if (!rk.includes(a)) rk.push(a); if (!ck.includes(b)) ck.push(b); const k = a + '\t' + b; m.set(k, (m.get(k) || 0) + 1) }
  rk.sort(); ck.sort();
  return { rk, ck, v: (a, b) => m.get(a + '\t' + b) || 0, rt: a => ck.reduce((s, b) => s + (m.get(a + '\t' + b) || 0), 0), ct: b => rk.reduce((s, a) => s + (m.get(a + '\t' + b) || 0), 0), all: rs.length };
 }
 const distinct = n => new Set(ROWS().map(x => String(x[ix(n)] ?? ''))).size;
 // ---- 部品 ----
 const chip = (n, role, x = true) => `<span class="px-chip px-${role}"><em>${ROLE[role]}</em>${E(n)}${x ? '<b>×</b>' : ''}</span>`;
 const tag = role => `<i class="px-tag px-${role}">${ROLE[role]}</i>`;
 const used = { '工程': 'rows', '作業者': 'columns' };
 const opts = (wide) => `<div class="px-opts ${wide ? 'wide' : ''}"><label>集計方法<select><option>件数</option></select></label><label class="px-ck"><input type="checkbox" checked>小計</label><label class="px-ck"><input type="checkbox" checked>総計</label><span class="px-sp"></span><select class="px-fmt"><option>CSV</option></select><button class="px-btn">集計結果を出力</button></div>`;
 function table(fit = true, label = '件数') {
  const d = count('工程', '作業者');
  return `<div class="px-tbox"><table class="px-t ${fit ? 'fit' : 'stretch'}"><thead><tr><th class="px-corner">工程 ＼ 作業者</th>${d.ck.map(b => `<th>${E(b)}</th>`).join('')}<th class="px-gt">総計</th></tr></thead><tbody>${d.rk.map(a => `<tr><th>${E(a)}</th>${d.ck.map(b => `<td>${d.v(a, b).toLocaleString()}</td>`).join('')}<td class="px-gt">${d.rt(a).toLocaleString()}</td></tr>`).join('')}<tr class="px-grand"><th>総計</th>${d.ck.map(b => `<td>${d.ct(b).toLocaleString()}</td>`).join('')}<td class="px-gt">${d.all.toLocaleString()}</td></tr></tbody></table><small class="px-cap">行 ${d.rk.length} × 列 ${d.ck.length}　${label}　全 ${d.all.toLocaleString()} 行から</small></div>`;
 }
 const empty = (b, s) => `<div class="px-empty"><b>${b}</b><span>${s}</span></div>`;
 // カラムの一覧（押して置く／D&D）。kind: 'menu' = 押すと置き先の小窓、'btn3' = 行・列・値の札、'check' = チェック
 function fields(kind, v, menuOn) {
  return H().map(n => {
   const u = v === 2 ? used[n] : null, num = /数量|不良数/.test(n);
   if (kind === 'btn3') return `<div class="px-f3 ${u ? 'on' : ''}"><span>${E(n)}</span>${['rows', 'columns', 'values'].map(r => `<button class="px-r px-${r} ${u === r ? 'on' : ''}" title="${ROLE[r]}へ">${ROLE[r]}</button>`).join('')}</div>`;
   if (kind === 'check') return `<label class="px-fc ${u ? 'on' : ''}"><input type="checkbox" ${u ? 'checked' : ''}><span>${E(n)}</span>${u ? tag(u) : num ? '<i class="px-num">数</i>' : ''}</label>`;
   return `<button class="px-fl ${u ? 'on' : ''}"><i>⋮⋮</i><span>${E(n)}</span>${u ? tag(u) : ''}</button>${menuOn === n ? `<div class="px-menu"><small>「${E(n)}」を置く</small><button class="px-rows">行へ</button><button class="px-columns">列へ</button><button class="px-values">値へ</button></div>` : ''}`;
  }).join('');
 }
 const bar = (v, ph) => `<div class="px-bar"><div class="px-slot"><i class="px-sl px-rows">行</i>${v === 2 ? chip('工程', 'rows') : `<span class="px-ph">${ph.rows}</span>`}</div><div class="px-slot"><i class="px-sl px-columns">列</i>${v === 2 ? chip('作業者', 'columns') : `<span class="px-ph">${ph.columns}</span>`}</div><div class="px-slot"><i class="px-sl px-values">値</i><span class="px-chip px-values px-fixed">件数</span></div><span class="px-sp"></span><label class="px-ck"><input type="checkbox" checked>小計</label><label class="px-ck"><input type="checkbox" checked>総計</label><button class="px-btn2">出力…</button><button class="px-link">すべて外す</button></div>`;

 // ---- 2回目の部品 ----
 const isNum = n => /数量|不良数/.test(n);
 function fields2(v) {
  return H().map(n => { const u = v === 2 ? used[n] : null, k = distinct(n);
   return `<div class="px-f3 ${u ? 'on' : ''}"><span>${E(n)}<small class="px-kinds ${k > 50 ? 'many' : ''}">${k.toLocaleString()} 種類</small></span>${['rows', 'columns'].map(r => `<button class="px-r px-${r} ${u === r ? 'on' : ''}">${ROLE[r]}</button>`).join('')}${isNum(n) ? `<button class="px-r px-values">値</button>` : '<i></i>'}</div>` }).join('');
 }
 const valSel = () => `<select class="px-vsel"><option>件数</option><option>数量 の合計</option><option>数量 の平均</option><option>不良数 の合計</option></select>`;
 const bar2 = v => `<div class="px-bar"><div class="px-slot"><i class="px-sl px-rows">行</i>${v === 2 ? chip2('工程', 'rows') : `<span class="px-ph">カラムの［行］を押す</span>`}</div><div class="px-slot"><i class="px-sl px-columns">列</i>${v === 2 ? chip2('作業者', 'columns') : `<span class="px-ph">（任意）</span>`}</div><div class="px-slot"><i class="px-sl px-values">値</i>${valSel()}</div><span class="px-sp"></span><label class="px-ck"><input type="checkbox" checked>小計</label><label class="px-ck"><input type="checkbox" checked>総計</label><button class="px-btn2">出力…</button><button class="px-link">すべて外す</button></div>`;
 const chip2 = (n, role) => `<span class="px-chip px-${role}">${E(n)}<b>×</b></span>`;
 function quick(inTop) {
  const few = H().filter(n => { const k = distinct(n); return k >= 2 && k <= 12 && !isNum(n) }), nums = H().filter(isNum), q = [];
  for (let i = 0; i < few.length && q.length < 3; i++) for (let j = i + 1; j < few.length && q.length < 3; j++) if (/工程|作業者|品名/.test(few[i]) && /工程|作業者|品名/.test(few[j])) q.push([few[i], few[j], '件数']);
  few.filter(n => /品名|工程/.test(n)).slice(0, 2).forEach(a => q.push([a, '', nums[0] + ' の合計']));
  return `<div class="px-empty"><b>${inTop ? '「行」の［＋ カラム］から選ぶと集計します' : 'カラムの［行］を押すと、値ごとの件数が出ます'}</b><span>種類の少ないカラムが行・列に向いています。すぐに見るなら:</span><div class="px-quick">${q.map(([a, b, m]) => `<button><b>${E(a)}${b ? ' × ' + E(b) : ' ごと'}</b><small>${E(m)}</small></button>`).join('')}</div></div>`;
 }
 const dropGrouped = () => { const g = [['種類が少ない（行・列に向く）', H().filter(n => { const k = distinct(n); return k <= 12 && !isNum(n) })], ['数（値に向く）', H().filter(isNum)], ['種類が多い（日時・番号）', H().filter(n => distinct(n) > 12 && !isNum(n))]];
  return `<div class="px-drop g">${g.map(([t, a]) => `<em>${t}</em>${a.map(n => `<button>${E(n)}<small>${distinct(n).toLocaleString()} 種類</small></button>`).join('')}`).join('')}</div>` };
 const V = {
  A: { t: '今の配置＋押すと置き先', html: v => `<div class="px-a">
    <div class="px-side"><div class="px-cap2"><b>カラム</b><small>押す か ドラッグで置く</small></div><input class="px-search" placeholder="カラムを検索"><div class="px-list">${fields('menu', v, v === 1 ? '工程' : null)}</div>
     <div class="px-sidefoot"><label>集計方法<select><option>カウント（件数）</option></select></label><button class="px-btn2">配置をすべてクリア</button><label class="px-ck"><input type="checkbox" checked>小計を表示</label><label class="px-ck"><input type="checkbox" checked>総計を表示</label><select><option>CSV (.csv)</option></select><button class="px-btn">集計結果を出力</button></div></div>
    <div class="px-mid"><div class="px-zone"><i class="px-sl px-values">値</i><span class="px-ph">件数以外はここへ</span></div><div class="px-zone tall"><i class="px-sl px-rows">行</i>${v === 2 ? chip('工程', 'rows') : '<span class="px-ph">行に展開するカラム</span>'}</div></div>
    <div class="px-right"><div class="px-zone"><i class="px-sl px-columns">列</i>${v === 2 ? chip('作業者', 'columns') : '<span class="px-ph">列に展開するカラム（任意）</span>'}</div>
     ${v === 2 ? table(false) : `<div class="px-hint">「行」に1つ以上カラムを置いてください。</div>`}</div></div>` },
  B: { t: 'カラムごとに［行］［列］［値］の札', html: v => `<div class="px-b">
    <div class="px-side"><div class="px-cap2"><b>カラム</b><small>札を押すと置きます</small></div><input class="px-search" placeholder="カラムを検索"><div class="px-list">${fields('btn3', v)}</div></div>
    <div class="px-work">${bar(v, { rows: 'カラムの［行］を押す', columns: '（任意）' })}${v === 2 ? table(true) : empty('左のカラムの［行］を押すと、値ごとの件数が出ます', '例: 工程の［行］→ 工程ごとの件数。さらに作業者の［列］で、工程×作業者の表になります。')}</div></div>` },
  C: { t: '上の欄で選ぶだけ（一覧なし）', html: v => `<div class="px-c">
    <div class="px-top"><div class="px-pick"><i class="px-sl px-rows">行</i>${v === 2 ? chip('工程', 'rows') : ''}<button class="px-add">＋ カラム</button>${v === 1 ? `<div class="px-drop">${H().map(n => `<button>${E(n)}</button>`).join('')}</div>` : ''}</div><div class="px-pick"><i class="px-sl px-columns">列</i>${v === 2 ? chip('作業者', 'columns') : ''}<button class="px-add">＋ カラム</button></div><div class="px-pick"><i class="px-sl px-values">値</i><select><option>件数</option><option>数量 の合計</option></select></div>${opts(false)}</div>
    ${v === 2 ? table(false) : empty('「行」の［＋ カラム］から選ぶと集計します', '列は任意です。値は件数のほか、数のカラムの合計・平均も選べます。')}</div>` },
  D: { t: 'Excel のピボット風（右に作業欄）', html: v => `<div class="px-d">
    <div class="px-dl">${v === 2 ? table(true) : empty('右のカラムにチェックを入れると集計します', 'チェックしたカラムは「行」へ入ります。列・値へは下の欄で移せます。')}</div>
    <div class="px-dr"><div class="px-cap2"><b>カラム</b><small>チェック＝行へ</small></div><input class="px-search" placeholder="カラムを検索"><div class="px-list ck">${fields('check', v)}</div>
     <div class="px-quad"><div><i class="px-sl px-columns">列</i>${v === 2 ? chip('作業者', 'columns') : ''}</div><div><i class="px-sl px-rows">行</i>${v === 2 ? chip('工程', 'rows') : ''}</div><div><i class="px-sl px-values">値</i><span class="px-chip px-values px-fixed">件数</span></div><div><small>集計方法</small><select><option>件数</option></select></div></div>
     <div class="px-dfoot"><label class="px-ck"><input type="checkbox" checked>小計</label><label class="px-ck"><input type="checkbox" checked>総計</label><button class="px-btn">出力…</button></div></div></div>` },
  E: { t: '文で組む', html: v => `<div class="px-e">
    <div class="px-sent"><span>${v === 2 ? '<button class="px-sel px-rows">工程 ▾</button>' : '<button class="px-sel px-rows px-empty2">カラムを選ぶ ▾</button>'} ごとに、</span><span>${v === 2 ? '<button class="px-sel px-columns">作業者 ▾</button> 別の' : '<button class="px-sel px-columns px-empty2">（列は任意） ▾</button> 別の'}</span><span><button class="px-sel px-values">件数 ▾</button> を数える</span><button class="px-link">＋ 段を足す</button>${v === 1 ? `<div class="px-drop at">${H().map(n => `<button>${E(n)}</button>`).join('')}</div>` : ''}${opts(true)}</div>
    ${v === 2 ? table(false) : empty('上の文の［カラムを選ぶ］から始めます', '「工程 ごとに、作業者 別の 件数 を数える」のように、文を埋めると表になります。')}</div>` },
  F: { t: 'おすすめの集計から始める（方向の違う案）', html: v => {
    const cands = H().filter(n => { const k = distinct(n); return k >= 2 && k <= 12 }), nums = H().filter(n => /数量|不良数/.test(n)), sug = [];
    for (let i = 0; i < cands.length; i++) for (let j = i + 1; j < cands.length && sug.length < 4; j++) sug.push([cands[i], cands[j], '件数']);
    cands.slice(0, 2).forEach(a => nums.slice(0, 1).forEach(n => sug.push([a, '', n + ' の合計'])));
    return `<div class="px-f">${v === 1 ? `<div class="px-sugh"><b>おすすめの集計</b><small>値の種類が少ないカラムから作りました。押すと表になります</small><span class="px-sp"></span><button class="px-btn2">自分で組む</button></div><div class="px-sug">${sug.map(([a, b, m]) => `<button class="px-card"><b>${E(a)}${b ? ' × ' + E(b) : ''}</b><small>${E(m)} · ${distinct(a)}${b ? '×' + distinct(b) : ''} の表</small><span class="px-mini">${[...Array(Math.min(6, distinct(a)))].map((_, i) => `<i style="height:${30 + ((i * 37) % 60)}%"></i>`).join('')}</span></button>`).join('')}</div>` : `${bar(2, {})}<div class="px-back"><button class="px-link">← おすすめに戻る</button></div>${table(true)}`}</div>` } },
  G: { t: '手順に分ける（方向の違う案）', html: v => `<div class="px-g">
    <div class="px-steps"><div class="px-step ${v === 1 ? 'on' : 'done'}"><em>1</em><b>行にするカラム</b><small>${v === 2 ? '工程' : '必須'}</small></div><div class="px-step ${v === 2 ? 'done' : ''}"><em>2</em><b>列にするカラム</b><small>${v === 2 ? '作業者' : '任意'}</small></div><div class="px-step ${v === 2 ? 'done' : ''}"><em>3</em><b>数えるもの</b><small>件数</small></div><span class="px-sp"></span>${v === 2 ? '<button class="px-btn2">組み直す</button>' : ''}</div>
    ${v === 1 ? `<div class="px-stepbody"><b>1. 行にするカラムを選んでください</b><small>表の左に縦に並ぶ見出しになります</small><div class="px-grid">${H().map(n => `<button>${E(n)}<small>${distinct(n)} 種類</small></button>`).join('')}</div><div class="px-stepfoot"><button class="px-btn" disabled>次へ（列を選ぶ）</button></div></div>` : `${opts(true)}${table(true)}`}</div>` },
  // ---- 2回目: 組合せ案 ----
  H: { t: 'B の札＋C の上の欄（値の選び方も）＋G の種類の数＋F の始め方', html: v => `<div class="px-b">
    <div class="px-side"><div class="px-cap2"><b>カラム</b><small>札を押すと置きます（数のカラムだけ［値］）</small></div><input class="px-search" placeholder="カラムを検索"><div class="px-list">${fields2(v)}</div></div>
    <div class="px-work">${bar2(v)}${v === 2 ? table(true) : quick()}</div></div>` },
  I: { t: 'C の上の欄＋G の種類の数（選ぶ欄で）＋F の始め方', html: v => `<div class="px-c">
    <div class="px-top"><div class="px-pick"><i class="px-sl px-rows">行</i>${v === 2 ? chip('工程', 'rows') : ''}<button class="px-add">＋ カラム</button>${v === 1 ? dropGrouped() : ''}</div><div class="px-pick"><i class="px-sl px-columns">列</i>${v === 2 ? chip('作業者', 'columns') : ''}<button class="px-add">＋ カラム</button></div><div class="px-pick"><i class="px-sl px-values">値</i>${valSel()}</div>${opts(false).replace('<label>集計方法<select><option>件数</option></select></label>', '')}</div>
    ${v === 2 ? table(true) : quick(true)}</div>` },
  J: { t: 'E の文を上の欄に＋B の札の一覧＋G の種類の数', html: v => `<div class="px-b">
    <div class="px-side"><div class="px-cap2"><b>カラム</b><small>札を押すと文に入ります</small></div><input class="px-search" placeholder="カラムを検索"><div class="px-list">${fields2(v)}</div></div>
    <div class="px-work"><div class="px-sent sm"><span>${v === 2 ? chip('工程', 'rows') : '<span class="px-hole px-rows">行のカラム</span>'} ごとに、</span><span>${v === 2 ? chip('作業者', 'columns') : '<span class="px-hole px-columns">列のカラム（任意）</span>'} 別の</span><span>${valSel()} を出す</span><span class="px-sp"></span><label class="px-ck"><input type="checkbox" checked>小計</label><label class="px-ck"><input type="checkbox" checked>総計</label><button class="px-btn2">出力…</button></div>${v === 2 ? table(true) : quick()}</div></div>` },
  K: { t: 'D の左右（表を左に広く）＋B の札＋C の上の欄', html: v => `<div class="px-k">
    <div class="px-work">${bar2(v)}${v === 2 ? table(true) : quick()}</div>
    <div class="px-side"><div class="px-cap2"><b>カラム</b><small>札を押すと置きます</small></div><input class="px-search" placeholder="カラムを検索"><div class="px-list">${fields2(v)}</div></div></div>` },
 };
 const CSS = `
  #px-overlay{position:fixed;z-index:50;background:#f3f6f8;font-family:"Yu Gothic UI",Meiryo,sans-serif;font-size:12.5px;color:#17232d;overflow:hidden}
  #px-overlay *{box-sizing:border-box}#px-overlay button{font:inherit;color:#17384e;cursor:pointer}#px-overlay select{font:inherit;height:28px;border:1px solid #cdd9de;border-radius:6px;background:#fff;padding:0 6px;color:#17232d}
  #px-overlay input{font:inherit;width:auto;height:auto}#px-overlay input[type=checkbox]{width:14px;height:14px;margin:0;padding:0}#px-overlay select{width:auto}
  #px-overlay label{display:inline-flex;align-items:center;gap:6px;margin:0;padding:0;font-size:12px;font-weight:600;color:#33505c;width:auto;min-width:0}
  .px-a,.px-b,.px-c,.px-d,.px-e,.px-f,.px-g{height:100%;min-height:0}
  .px-side,.px-dr,.px-mid>.px-zone,.px-right>.px-zone,.px-top,.px-bar,.px-sent,.px-steps,.px-stepbody,.px-sugh{background:#fff;border:1px solid #d7e0e5;border-radius:10px}
  .px-a{display:grid;grid-template-columns:230px 210px minmax(0,1fr);gap:8px}
  .px-side{display:flex;flex-direction:column;gap:6px;padding:10px;min-height:0}
  .px-cap2{display:flex;align-items:baseline;gap:8px}.px-cap2 b{font-size:14px}.px-cap2 small{color:#647581;font-size:10.5px}
  .px-search{width:100%!important;height:30px!important;border:1px solid #cdd9de;border-radius:7px;padding:0 9px}
  .px-list{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:5px;position:relative}.px-list>*{flex-shrink:0}
  .px-fl{display:flex;align-items:center;gap:8px;height:34px;padding:0 10px;border:1px solid #d7e0e5;border-radius:7px;background:#fff;text-align:left;font-weight:700}.px-fl i{font-style:normal;color:#9aabb2;letter-spacing:-2px}.px-fl span{flex:1}.px-fl.on{background:#f4f7f8;color:#8a9aa1}
  .px-menu{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;padding:8px;margin:-2px 0 4px 18px;border:1px solid #9fcbd6;border-radius:8px;background:#fff;box-shadow:0 10px 24px #17384e30}.px-menu small{grid-column:1/-1;color:#4d6670;font-size:10.5px}.px-menu button{height:28px;border-radius:6px;border:1px solid;font-weight:800}
  .px-sidefoot{display:grid;gap:6px;padding-top:8px;border-top:1px solid #e6edf0}.px-sidefoot label{display:grid;gap:3px;font-size:10.5px;color:#647581}
  .px-mid{display:grid;grid-template-rows:auto minmax(0,1fr);gap:8px;min-height:0}.px-zone{padding:10px;display:flex;flex-wrap:wrap;align-content:flex-start;gap:6px;min-height:70px}.px-zone.tall{min-height:0}
  .px-right{display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:8px;min-height:0}
  .px-hint{padding:8px 12px;background:#eef3f5;border-radius:8px;color:#4d6670}
  .px-sl{font-style:normal;display:inline-grid;place-items:center;min-width:24px;height:22px;padding:0 6px;border-radius:6px;font-weight:900;font-size:11px}
  .px-rows{background:#e6f1fb;color:#1d5f9a;border-color:#a9c9e8!important}.px-columns{background:#f1eafb;color:#6a3fa0;border-color:#cdb6ea!important}.px-values{background:#e5f4ec;color:#1f6e49;border-color:#a9d6bf!important}
  .px-ph{color:#8a9aa1;font-size:11.5px;align-self:center}
  .px-chip{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 6px 0 4px;border:1px solid;border-radius:7px;font-weight:800}.px-chip em{font-style:normal;font-size:10px;padding:1px 5px;border-radius:5px;background:#ffffffb0}.px-chip b{color:#9b4a40;font-weight:900;padding:0 3px}.px-chip.px-fixed{padding:0 10px}
  .px-tag{font-style:normal;font-size:10px;font-weight:900;padding:1px 6px;border-radius:5px;border:1px solid}
  .px-tbox{min-height:0;overflow:auto;background:#fff;border:1px solid #d7e0e5;border-radius:10px;padding:0 0 6px;display:flex;flex-direction:column}
  .px-t{border-collapse:collapse;font-variant-numeric:tabular-nums;align-self:flex-start}.px-t.stretch{align-self:stretch}.px-t.stretch{width:100%}.px-t.fit{width:auto}
  .px-t th,.px-t td{padding:6px 12px;border-bottom:1px solid #e6edf0;white-space:nowrap}.px-t thead th{background:#eef3f5;color:#33505c;font-size:12px;position:sticky;top:0}.px-t.fit td,.px-t.fit thead th:not(.px-corner){min-width:96px}
  .px-t tbody th{text-align:left;background:#f7fafb}.px-t td{text-align:right}.px-t .px-gt{background:#f0f5f7;font-weight:800}.px-grand th,.px-grand td{background:#e9f0f3;font-weight:900;border-top:2px solid #c9d8de}
  .px-corner{text-align:left;color:#647581}
  .px-cap{padding:6px 12px 0;color:#647581;font-size:11px}
  .px-empty{display:grid;place-content:center;gap:8px;text-align:center;background:#fff;border:1px dashed #c3d3d9;border-radius:10px;min-height:0;padding:30px}.px-empty b{font-size:16px;color:#17384e}.px-empty span{color:#4d6670;max-width:560px;line-height:1.6}
  .px-b{display:grid;grid-template-columns:300px minmax(0,1fr);gap:8px}
  .px-f3{display:grid;grid-template-columns:minmax(0,1fr) repeat(3,34px);align-items:center;gap:4px;height:34px;padding:0 4px 0 10px;border:1px solid #d7e0e5;border-radius:7px;font-weight:700}.px-f3.on{background:#f7fafb}
  .px-r{height:26px;border:1px solid;border-radius:6px;font-weight:900;font-size:11px;opacity:.55}.px-r.on{opacity:1;box-shadow:inset 0 0 0 2px currentColor}.px-f3:hover .px-r{opacity:1}
  .px-work{display:grid;grid-template-rows:auto minmax(0,1fr);gap:8px;min-height:0}
  .px-bar{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:8px 10px}.px-slot{display:flex;align-items:center;gap:6px;padding-right:10px;border-right:1px solid #e6edf0}
  .px-sp{flex:1}.px-ck{display:inline-flex;align-items:center;gap:4px;font-size:12px}
  .px-btn{height:30px;padding:0 14px;border:0;border-radius:7px;background:#087c98;color:#fff!important;font-weight:800}.px-btn[disabled]{background:#9fbfc8}
  .px-btn2{height:30px;padding:0 12px;border:1px solid #c9d8de;border-radius:7px;background:#fff;font-weight:700}.px-link{border:0;background:none;color:#087c98!important;font-weight:700}
  .px-c{display:grid;grid-template-rows:auto minmax(0,1fr);gap:8px}
  .px-top{display:flex;align-items:center;gap:10px;padding:8px 10px;flex-wrap:wrap;position:relative}.px-pick{display:flex;align-items:center;gap:6px;padding-right:10px;border-right:1px solid #e6edf0;position:relative}
  .px-add{height:28px;padding:0 10px;border:1px dashed #9fbac4;border-radius:7px;background:#f7fafb;font-weight:800}
  .px-drop{position:absolute;top:36px;left:0;z-index:3;display:grid;min-width:200px;padding:6px;background:#fff;border:1px solid #9fcbd6;border-radius:8px;box-shadow:0 12px 26px #17384e33}.px-drop button{text-align:left;padding:6px 10px;border:0;background:none;border-radius:5px}.px-drop button:hover,.px-drop button:nth-child(5){background:#e8f4f6}
  .px-drop.at{top:52px;left:12px}
  .px-opts{display:flex;align-items:center;gap:10px;margin-left:auto}.px-opts label{display:inline-flex;align-items:center;gap:6px}.px-opts.wide{margin:0;padding:6px 10px;background:#fff;border:1px solid #d7e0e5;border-radius:10px}
  .px-d{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:8px}.px-dl{display:grid;min-height:0}
  .px-dr{display:flex;flex-direction:column;gap:6px;padding:10px;min-height:0}.px-list.ck{gap:2px}.px-fc{display:flex;align-items:center;gap:8px;height:28px;padding:0 6px;border-radius:5px}.px-fc span{flex:1}.px-fc.on{background:#f1f7f9}.px-num{font-style:normal;font-size:10px;color:#647581;border:1px solid #d7e0e5;border-radius:4px;padding:0 4px}
  .px-quad{display:grid;grid-template-columns:1fr 1fr;gap:6px}.px-quad>div{display:flex;flex-wrap:wrap;align-content:flex-start;gap:5px;min-height:62px;padding:6px;border:1px solid #d7e0e5;border-radius:7px;background:#fbfdfd}.px-quad small{width:100%;color:#647581;font-size:10.5px}
  .px-dfoot{display:flex;align-items:center;gap:8px;padding-top:6px;border-top:1px solid #e6edf0}.px-dfoot .px-btn{margin-left:auto}
  .px-e{display:grid;grid-template-rows:auto minmax(0,1fr);gap:8px}
  .px-sent{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:12px 14px;font-size:16px;font-weight:700;position:relative}.px-sel{height:34px;padding:0 12px;border:1px solid;border-radius:8px;font-weight:900;font-size:15px}.px-empty2{border-style:dashed!important}.px-sent .px-opts{font-size:12px;font-weight:400}
  .px-f{display:grid;grid-template-rows:auto minmax(0,1fr);gap:8px;align-content:start}.px-f:has(.px-back){grid-template-rows:auto auto minmax(0,1fr)}
  .px-sugh{display:flex;align-items:baseline;gap:10px;padding:10px 14px}.px-sugh b{font-size:15px}.px-sugh small{color:#647581}
  .px-sug{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-content:start}.px-card{display:grid;gap:4px;text-align:left;padding:14px;border:1px solid #d7e0e5;border-radius:10px;background:#fff}.px-card b{font-size:15px}.px-card small{color:#647581}.px-mini{display:flex;align-items:flex-end;gap:4px;height:46px;margin-top:6px}.px-mini i{width:16px;background:#9fcbd6;border-radius:3px 3px 0 0}
  .px-back{margin:-2px 0}
  .px-g{display:grid;grid-template-rows:auto minmax(0,1fr);gap:8px}.px-g:has(.px-opts){grid-template-rows:auto auto minmax(0,1fr)}
  .px-steps{display:flex;align-items:center;gap:8px;padding:8px 10px}.px-step{display:grid;grid-template-columns:auto auto;column-gap:8px;align-items:center;padding:6px 14px 6px 8px;border:1px solid #d7e0e5;border-radius:999px;background:#fbfdfd}.px-step em{grid-row:span 2;font-style:normal;display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#dfe8ec;font-weight:900}.px-step b{font-size:12.5px}.px-step small{color:#647581;font-size:10.5px}.px-step.on{border-color:#087c98;background:#e8f4f6}.px-step.on em{background:#087c98;color:#fff}.px-step.done em{background:#1f8a5b;color:#fff}
  .px-stepbody{display:flex;flex-direction:column;gap:8px;padding:16px;min-height:0}.px-stepbody b{font-size:16px}.px-stepbody>small{color:#647581}
  .px-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.px-grid button{display:grid;gap:2px;padding:12px;border:1px solid #d7e0e5;border-radius:9px;background:#fff;text-align:left;font-weight:800}.px-grid small{color:#647581;font-weight:400}

  .px-kinds{display:block;font-size:10px;color:#7d9098;font-weight:400}.px-kinds.many{color:#a7b5bb}.px-f3{height:40px}.px-f3>i{display:block}
  .px-f3>span{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;line-height:1.25}
  .px-vsel{font-weight:800}
  .px-quick{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin-top:6px}.px-quick button{display:grid;gap:1px;padding:8px 14px;border:1px solid #bcd6de;border-radius:9px;background:#f5fafb;text-align:left}.px-quick b{font-size:13px}.px-quick small{color:#647581}
  .px-drop.g{min-width:250px}.px-drop.g em{font-style:normal;font-size:10.5px;color:#647581;padding:6px 10px 2px;font-weight:800}.px-drop.g button{display:flex;justify-content:space-between;gap:12px}.px-drop.g small{color:#8a9aa1}
  .px-sent.sm{font-size:14px;padding:8px 12px}.px-hole{display:inline-flex;align-items:center;height:28px;padding:0 10px;border:1px dashed;border-radius:7px;font-size:12px;font-weight:700}
  .px-k{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:8px;height:100%;min-height:0}
  .px-stepfoot{display:flex;justify-content:flex-end;margin-top:auto}
 `;
 function style() { let s = document.getElementById('px-style'); if (!s) { s = document.createElement('style'); s.id = 'px-style'; document.head.appendChild(s) } s.textContent = CSS }
 window.PX = {
  V,
  show(k, v = 1) {
   style(); const r = document.querySelector('#viewer-analysis').getBoundingClientRect();
   let host = document.getElementById('px-overlay'); if (!host) { host = document.createElement('div'); host.id = 'px-overlay'; document.body.appendChild(host) }
   Object.assign(host.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' }); host.innerHTML = V[k].html(v);
  },
 };
})();
