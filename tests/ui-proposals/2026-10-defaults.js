// 2.0.0「既定の設定」の案（CLAUDE.md §3）。いまの画面の #def-dialog-body（起動時の3択）と #def-body・#rel-versions
// （配布と更新の既定の設定の欄と版の一覧）に、案ごとの DOM と CSS を当てて再現する。データはどの案も同じ実データ
// （/api/defaults/offer・/api/defaults・/api/release/status）。撮り方: 撮影用の仕掛けで window.DV.dialog(k)／DV.block(k)。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const PART = { jobs: '対象の登録', schedules: '自動実行の予定', layouts: '読取マスタ', recipes: '結合マスタ', rne: 'RNE', settings: '共通設定' };
 const ORDER = ['jobs', 'schedules', 'layouts', 'recipes', 'rne', 'settings'];
 const cnt = (dif, p, k) => ((dif[p] || {})[k] || []).length;
 const sum = (dif, k) => ORDER.reduce((n, p) => n + cnt(dif, p, k), 0);
 const when = s => String(s || '').replace('T', ' ').slice(0, 16);
 const head = o => {
  const d = o.defaults || {};
  const title = o.kind === 'migrate' ? 'この版から、設定はこのPCの手元に置きます' : '置き場の既定の設定が新しくなりました';
  const lead = o.kind === 'migrate' ? 'これまでは共有の設定を全PCで使っていました。この版からは各PCが手元に持ちます。置き場の既定の設定との合わせ方を選んでください。'
   : `${E(when(d.savedAt))} に ${E(d.savedBy)}（${E(d.pc)}）が置きました。${d.note ? '「' + E(d.note) + '」' : ''}`;
  return { title, lead };
 };
 const effect = (o, m) => {
  const dif = o.diff || {};
  if (m === 'overwrite') return `${sum(dif, 'change')}件を既定の中身に置き換え、${sum(dif, 'add')}件を足します。手元だけの${sum(dif, 'local')}件は残します`;
  if (m === 'add') return `足りない${sum(dif, 'add')}件だけを足します。手元で変えた物は触りません`;
  return o.kind === 'migrate' ? 'いまの共有の設定をこのPCの手元へ写して、そのまま使います' : '何も変えません。この既定はもう聞きません';
 };
 const MODES = [['add', '差分追加'], ['overwrite', '上書き'], ['keep', '今のまま']];
 const foot = o => `<p class="dv-safe">どれを選んでも、変える前に手元の設定の控えを取ります${o.kind === 'migrate' ? '。選ぶと一度開き直します' : ''}。</p>`;
 const names = (dif, p, k) => ((dif[p] || {})[k] || []).map(E).join('・') || '—';

 const DIALOG = {
  A: { name: 'A 3枚の選択カード', css: `
   .dvA .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
   .dvA .card{display:grid;gap:6px;align-content:start;text-align:left;padding:14px;border:1.5px solid var(--line);border-radius:10px;background:#fff;color:#203f4d;font-weight:400;cursor:pointer}
   .dvA .card b{font-size:15px}.dvA .card small{font-size:12px;color:#4f6772;line-height:1.55}
   .dvA .card.on{border-color:#0b7e8f;box-shadow:0 0 0 3px #cdeef1;background:#f4fbfc}`,
   html: o => { const h = head(o); return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvA"><p class="dv-lead">${h.lead}</p>
    <div class="cards">${MODES.map(([m, l], i) => `<button type="button" class="card${i === 0 ? ' on' : ''}"><b>${l}</b><small>${effect(o, m)}</small></button>`).join('')}</div>${foot(o)}</div>
    <div class="modalfoot"><button type="button" class="secondary">あとで決める</button><button type="button">差分追加で進める</button></div>` } },
  B: { name: 'B 違いの表＋3つのボタン', css: `
   .dvB table{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}.dvB th,.dvB td{padding:6px 9px;border-bottom:1px solid #e3eaee;text-align:right}
   .dvB th:first-child,.dvB td:first-child{text-align:left}.dvB th{font-size:11px;color:#647581}.dvB td.z{color:#b0bcc2}
   .dvB .btns{display:flex;gap:8px;justify-content:flex-end}`,
   html: o => { const h = head(o), dif = o.diff || {}; const td = (p, k) => { const n = cnt(dif, p, k); return `<td class="${n ? '' : 'z'}">${n || '0'}</td>` };
    return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvB"><p class="dv-lead">${h.lead}</p>
    <table><thead><tr><th>項目</th><th>既定にだけある（足す）</th><th>中身が違う</th><th>手元にだけある</th></tr></thead><tbody>${ORDER.filter(p => p !== 'settings').map(p => `<tr><td>${PART[p]}</td>${td(p, 'add')}${td(p, 'change')}${td(p, 'local')}</tr>`).join('')}</tbody></table>${foot(o)}</div>
    <div class="modalfoot"><button type="button" class="secondary">今のまま</button><button type="button" class="secondary">上書き</button><button type="button">差分追加</button></div>` } },
  C: { name: 'C 選ぶと右に「何が起きるか」', css: `
   .dvC .two{display:grid;grid-template-columns:220px 1fr;gap:14px;min-height:240px}
   .dvC .opts{display:grid;gap:6px;align-content:start}.dvC .opt{display:grid;gap:2px;padding:10px 12px;border:1.5px solid var(--line);border-radius:9px;cursor:pointer}
   .dvC .opt.on{border-color:#0b7e8f;background:#f4fbfc}.dvC .opt b{font-size:14px;color:#203f4d}.dvC .opt small{font-size:11px;color:#647581}
   .dvC .what{border:1px solid #dce6ea;border-radius:9px;background:#f8fbfc;padding:12px 14px;display:grid;gap:8px;align-content:start;font-size:12.5px}
   .dvC .what h4{margin:0;font-size:13px;color:#203f4d}.dvC .row{display:grid;grid-template-columns:110px 1fr;gap:8px}.dvC .row i{font-style:normal;font-weight:800;font-size:11px;color:#647581}
   .dvC .row.add i{color:#0a6b4c}.dvC .row.chg i{color:#8a5200}`,
   html: o => { const h = head(o), dif = o.diff || {};
    return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvC"><p class="dv-lead">${h.lead}</p><div class="two">
    <div class="opts">${MODES.map(([m, l], i) => `<div class="opt${i === 0 ? ' on' : ''}"><b>${l}</b><small>${m === 'add' ? '足りない物だけ' : m === 'overwrite' ? '既定にある物は既定の中身へ' : '何も変えない'}</small></div>`).join('')}</div>
    <div class="what"><h4>差分追加を選ぶと</h4><div class="row add"><i>足す</i><span>${names(dif, 'jobs', 'add')}（対象）・予定 ${cnt(dif, 'schedules', 'add')}件のうち新しい対象の分</span></div>
     <div class="row"><i>触らない</i><span>${names(dif, 'jobs', 'change')}（中身が違う）・${names(dif, 'jobs', 'local')}（手元だけ）</span></div></div></div>${foot(o)}</div>
    <div class="modalfoot"><button type="button" class="secondary">あとで決める</button><button type="button">差分追加で進める</button></div>` } },
  D: { name: 'D 1行の要約と3つのボタン（詳しくは開く）', css: `
   .dvD .sum{font-size:14px;color:#203f4d;margin:0}.dvD details{font-size:12px;color:#4f6772}.dvD summary{cursor:pointer;color:#0b7e8f;font-weight:700}
   .dvD .btns{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.dvD .btns button{display:grid;gap:3px;padding:10px;text-align:center}.dvD .btns small{font-size:10.5px;font-weight:400;opacity:.85}`,
   html: o => { const h = head(o), dif = o.diff || {};
    return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvD"><p class="dv-lead">${h.lead}</p>
    <p class="sum">既定にだけある物 <b>${sum(dif, 'add')}件</b>・中身が違う物 <b>${sum(dif, 'change')}件</b>・手元にだけある物 <b>${sum(dif, 'local')}件</b></p>
    <details><summary>名前を見る</summary><p>足す: ${names(dif, 'jobs', 'add')}／違う: ${names(dif, 'jobs', 'change')}／手元だけ: ${names(dif, 'jobs', 'local')}</p></details>
    <div class="btns">${MODES.map(([m, l], i) => `<button type="button" class="${i ? 'secondary' : ''}">${l}<small>${m === 'add' ? '足りない物だけ' : m === 'overwrite' ? '既定の中身へ' : '変えない'}</small></button>`).join('')}</div>${foot(o)}</div>` } },
  E: { name: 'E 2段階（何が違うか → 選ぶ）', css: `
   .dvE .steps{display:flex;gap:6px;font-size:11px;font-weight:800;color:#93a4ab}.dvE .steps .on{color:#0b7e8f}
   .dvE ul{margin:0;padding-left:18px;font-size:12.5px;line-height:1.8;color:#203f4d}.dvE li b{color:#0a6b4c}.dvE li.chg b{color:#8a5200}`,
   html: o => { const h = head(o), dif = o.diff || {};
    return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvE"><div class="steps"><span class="on">1. 何が違うか</span><span>›</span><span>2. 合わせ方を選ぶ</span></div><p class="dv-lead">${h.lead}</p>
    <ul><li>既定にだけある: <b>${names(dif, 'jobs', 'add')}</b></li><li class="chg">中身が違う: <b>${names(dif, 'jobs', 'change')}</b></li><li>手元にだけある: ${names(dif, 'jobs', 'local')}</li><li>自動実行の予定: 既定に ${cnt(dif, 'schedules', 'add')}件</li></ul></div>
    <div class="modalfoot"><button type="button" class="secondary">あとで決める</button><button type="button">次へ（合わせ方を選ぶ）</button></div>` } },
 };

 // ---- 既定の設定の欄＋版の一覧（消す） ----
 const facts = d => `<div class="rel-facts"><div><small>置いた日時</small><b>${E(when(d.savedAt))}</b></div><div><small>置いた人・PC</small><b>${E(d.savedBy)}・${E(d.pc)}</b></div>`
  + `<div><small>対象</small><b>${d.counts.jobs}件</b></div><div><small>予定</small><b>${d.counts.schedules}件</b></div><div><small>RNE</small><b>${d.counts.rne}個</b></div></div>`;
 const verRows = (st, mode) => (st.versions || []).map(v => {
  const want = st.release?.version, on = (st.fleet || []).filter(f => f.version === v.version).map(f => f.pc);
  const del = v.version === want ? '' : mode === 'menu' ? '<button type="button" class="secondary dv-more">…</button>' : `<button type="button" class="${mode === 'text' ? 'textbtn dv-del-t' : 'secondary dv-del'}">消す</button>`;
  return `<tr class="${v.version === want ? 'is-current' : ''}"><td><b>${E(v.version)}</b></td><td>${E(v.placedAt)}</td><td>${E(v.placedBy)}</td><td>${v.version === want ? '<i class="rel-tag is-ok">配布中</i>' : on.length ? `<i class="rel-tag is-warn">${E(on.join('・'))} が使用中</i>` : '<span class="rel-muted">—</span>'}</td>`
   + `<td class="rel-act">${v.version === want ? '<span class="rel-muted">配っています</span>' : '<button type="button" class="secondary">この版へ戻す</button>'} ${del}</td></tr>` }).join('');
 const verTable = (st, mode) => `<table class="rel-table"><thead><tr><th>版</th><th>置いた日時</th><th>置いた人</th><th>状態</th><th></th></tr></thead><tbody>${verRows(st, mode)}</tbody></table>`;
 const partList = (d, cls) => ORDER.filter(p => p !== 'settings').map(p => `<div class="${cls}"><b>${PART[p]}</b><span>${(d.parts[p] || []).length ? d.parts[p].map(n => `<em>${E(n)}<button type="button" title="既定から外す">×</button></em>`).join('') : '<i>なし</i>'}</span></div>`).join('');
 const BLOCK = {
  A: { name: 'A 事実の札＋項目の札（×で外す）＋版の行に「消す」', css: `
   .bvA{display:grid;gap:10px}.bvA .parts{display:grid;gap:6px}.bvA .pl{display:grid;grid-template-columns:110px 1fr;gap:8px;align-items:start;font-size:12px}
   .bvA .pl b{color:#4f6772;font-size:11px;padding-top:4px}.bvA .pl span{display:flex;flex-wrap:wrap;gap:5px}.bvA .pl i{color:#93a4ab;font-style:normal}
   .bvA em{font-style:normal;display:inline-flex;align-items:center;gap:4px;padding:3px 4px 3px 9px;border:1px solid #d5e1e6;border-radius:999px;background:#fff}
   .bvA em button{background:transparent;color:#93a4ab;padding:0 5px;font-size:13px}.bvA .acts{display:flex;gap:8px}`,
   html: (d) => `<div class="bvA">${facts(d)}<div class="parts">${partList(d, 'pl')}</div><div class="acts"><button type="button">このPCの設定から作り直す…</button><button type="button" class="textbtn" style="color:#a4463d">既定を消す</button></div></div>`,
   ver: st => verTable(st, 'button') },
  B: { name: 'B 1枚の表（項目・名前・外す）', css: `.bvB table{width:100%}.bvB .acts{display:flex;gap:8px;justify-content:flex-end;margin-bottom:8px}`,
   html: d => `<div class="bvB"><div class="acts"><span class="rel-note" style="margin-right:auto">${E(when(d.savedAt))}・${E(d.savedBy)}（${E(d.pc)}）</span><button type="button">作り直す…</button><button type="button" class="secondary">消す</button></div>
    <table class="rel-table"><thead><tr><th>項目</th><th>名前</th><th></th></tr></thead><tbody>${ORDER.filter(p => p !== 'settings').flatMap(p => (d.parts[p] || []).map(n => `<tr><td>${PART[p]}</td><td>${E(n)}</td><td class="rel-act"><button type="button" class="textbtn">外す</button></td></tr>`)).join('')}</tbody></table></div>`,
   ver: st => verTable(st, 'text') },
  C: { name: 'C 項目ごとの札（件数、開くと名前）', css: `
   .bvC .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}.bvC details{border:1px solid #dce6ea;border-radius:9px;background:#f8fbfc;padding:9px 12px}
   .bvC summary{cursor:pointer;display:flex;justify-content:space-between;font-weight:700;color:#203f4d}.bvC summary span{color:#0b7e8f}.bvC ul{margin:6px 0 0;padding-left:16px;font-size:12px}
   .bvC .acts{display:flex;gap:8px;margin-top:10px}`,
   html: d => `<div class="bvC"><p class="rel-note">${E(when(d.savedAt))}・${E(d.savedBy)}（${E(d.pc)}）${d.note ? '「' + E(d.note) + '」' : ''}</p><div class="grid">${ORDER.filter(p => p !== 'settings').map((p, i) => `<details${i === 0 ? ' open' : ''}><summary>${PART[p]}<span>${(d.parts[p] || []).length}</span></summary><ul>${(d.parts[p] || []).map(n => `<li>${E(n)} <button type="button" class="textbtn">外す</button></li>`).join('') || '<li>なし</li>'}</ul></details>`).join('')}</div>
    <div class="acts"><button type="button">このPCの設定から作り直す…</button><button type="button" class="secondary">既定を消す</button></div></div>`,
   ver: st => verTable(st, 'menu') },
  D: { name: 'D 左に既定・右にこのPCとの違い', css: `
   .bvD{display:grid;grid-template-columns:1fr 1fr;gap:12px}.bvD section{border:1px solid #dce6ea;border-radius:9px;padding:10px 12px;background:#fff;display:grid;gap:6px;align-content:start}
   .bvD h4{margin:0;font-size:13px}.bvD p{margin:0;font-size:12px}.bvD .acts{display:flex;gap:8px}`,
   html: d => `<div class="bvD"><section><h4>置き場の既定</h4><p>${E(when(d.savedAt))}・${E(d.savedBy)}（${E(d.pc)}）</p><p>対象 ${d.counts.jobs}・予定 ${d.counts.schedules}・RNE ${d.counts.rne}</p><div class="acts"><button type="button">作り直す…</button><button type="button" class="secondary">消す</button></div></section>
    <section><h4>このPCとの違い</h4><p>既定にだけある: 出荷予定（新規）</p><p>中身が違う: SIKALOTDEF・SIKALOTNOW</p><p>手元にだけある: 第2工場の仕掛（手元だけ）</p></section></div>`,
   ver: st => verTable(st, 'button') },
  E: { name: 'E 1行の要約＋「中身を見る・直す」画面', css: `.bvE{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid #dce6ea;border-radius:9px;background:#fff}.bvE p{margin:0;flex:1;font-size:13px}`,
   html: d => `<div class="bvE"><p><b>対象 ${d.counts.jobs}件・予定 ${d.counts.schedules}件・RNE ${d.counts.rne}個</b>　${E(when(d.savedAt))}・${E(d.savedBy)}</p><button type="button">中身を見る・直す…</button></div>`,
   ver: st => verTable(st, 'button') },
 };

 // ---- 2回目（僅差のため）: 複合案 F・G・H。1回目の上位は 3択＝C・A、既定の欄＝A・D ----
 const effNames = (o, m) => { const dif = o.diff || {};
  const rows = m === 'add' ? [['足す', 'add', 'jobs', 'add'], ['予定を足す', 'add', 'schedules', 'addNew'], ['触らない', 'keep', 'jobs', 'change'], ['残す', 'keep', 'jobs', 'local']]
   : m === 'overwrite' ? [['足す', 'add', 'jobs', 'add'], ['置き換える', 'chg', 'jobs', 'change'], ['予定を合わせる', 'chg', 'schedules', 'add'], ['残す', 'keep', 'jobs', 'local']]
   : [['変えない', 'keep', 'jobs', 'all']];
  return rows.map(([l, c, p, k]) => { let v;
   if (k === 'addNew') v = ((dif.schedules || {}).add || []).filter(n => ((dif.jobs || {}).add || []).includes(n));
   else if (k === 'all') v = ['すべて（この既定はもう聞きません）']; else v = (dif[p] || {})[k] || [];
   return v.length ? `<div class="r ${c}"><i>${l}</i><span>${v.map(E).join('・')}${p === 'schedules' && k !== 'all' ? ' の予定' : ''}</span></div>` : '' }).join('') };
 Object.assign(DIALOG, {
  F: { name: 'F カードで選ぶ＋下に「何が起きるか」（A+C）', css: DIALOG.A.css + `
   .dvF .what{margin-top:10px;border:1px solid #dce6ea;border-radius:9px;background:#f8fbfc;padding:10px 14px;display:grid;gap:6px;font-size:12.5px}
   .dvF .what h4{margin:0;font-size:12px;color:#647581}.dvF .r{display:grid;grid-template-columns:110px 1fr;gap:8px}.dvF .r i{font-style:normal;font-weight:800;font-size:11px;color:#647581}
   .dvF .r.add i{color:#0a6b4c}.dvF .r.chg i{color:#8a5200}`,
   html: o => { const h = head(o); return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvA dvF"><p class="dv-lead">${h.lead}</p>
    <div class="cards">${MODES.map(([m, l], i) => `<button type="button" class="card${i === 0 ? ' on' : ''}"><b>${l}</b><small>${m === 'add' ? '足りない物だけ足す' : m === 'overwrite' ? '既定にある物は既定の中身へ' : '何も変えない'}</small></button>`).join('')}</div>
    <div class="what"><h4>差分追加を選ぶと</h4>${effNames(o, 'add')}</div>${foot(o)}</div>
    <div class="modalfoot"><button type="button" class="secondary">あとで決める</button><button type="button">差分追加で進める</button></div>` } },
  G: { name: 'G 違いの表＋カードで選ぶ（A+B）', css: DIALOG.A.css + DIALOG.B.css,
   html: o => { const h = head(o), dif = o.diff || {}; const td = (p, k) => { const n = cnt(dif, p, k); return `<td class="${n ? '' : 'z'}">${n || '0'}</td>` };
    return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvA dvB"><p class="dv-lead">${h.lead}</p>
    <table><thead><tr><th>項目</th><th>既定にだけある</th><th>中身が違う</th><th>手元にだけある</th></tr></thead><tbody>${['jobs', 'schedules', 'rne'].map(p => `<tr><td>${PART[p]}</td>${td(p, 'add')}${td(p, 'change')}${td(p, 'local')}</tr>`).join('')}</tbody></table>
    <div class="cards" style="margin-top:10px">${MODES.map(([m, l], i) => `<button type="button" class="card${i === 0 ? ' on' : ''}"><b>${l}</b><small>${m === 'add' ? '足りない物だけ足す' : m === 'overwrite' ? '既定にある物は既定の中身へ' : '何も変えない'}</small></button>`).join('')}</div>${foot(o)}</div>
    <div class="modalfoot"><button type="button" class="secondary">あとで決める</button><button type="button">差分追加で進める</button></div>` } },
  H: { name: 'H 左で選ぶ＋右に項目ごとの名前（C+E）', css: DIALOG.C.css + `.dvH .two{min-height:0}.dvH .what .r{display:grid;grid-template-columns:110px 1fr;gap:8px}.dvH .r i{font-style:normal;font-weight:800;font-size:11px;color:#647581}.dvH .r.add i{color:#0a6b4c}.dvH .r.chg i{color:#8a5200}`,
   html: o => { const h = head(o);
    return `<div class="modalhead"><div><small>既定の設定</small><h2>${h.title}</h2></div></div><div class="modalbody dvC dvH"><p class="dv-lead">${h.lead}</p><div class="two">
    <div class="opts">${MODES.map(([m, l], i) => `<div class="opt${i === 0 ? ' on' : ''}"><b>${l}</b><small>${m === 'add' ? '足りない物だけ' : m === 'overwrite' ? '既定にある物は既定の中身へ' : '何も変えない'}</small></div>`).join('')}</div>
    <div class="what"><h4>差分追加を選ぶと</h4>${effNames(o, 'add')}</div></div>${foot(o)}</div>
    <div class="modalfoot"><button type="button" class="secondary">あとで決める</button><button type="button">差分追加で進める</button></div>` } },
 });
 const chips = d => ORDER.filter(p => p !== 'settings' && (d.parts[p] || []).length).map(p => `<div class="pl"><b>${PART[p]} <span class="n">${d.parts[p].length}</span></b><span>${d.parts[p].map(n => `<em>${E(n)}<button type="button" title="既定から外す" aria-label="${E(n)} を既定から外す">外す</button></em>`).join('')}</span></div>`).join('');
 const empties = d => { const z = ORDER.filter(p => p !== 'settings' && !(d.parts[p] || []).length).map(p => PART[p]); return z.length ? `<div class="pl"><b>入っていない</b><span class="z">${z.join('・')}</span></div>` : '' };
 Object.assign(BLOCK, {
  F: { name: 'F 札と項目＋「このPCとの違い」1行（A+D）', css: BLOCK.A.css + `.bvA .dif{font-size:12px;color:#4f6772;padding:7px 10px;background:#f6f9fa;border-radius:7px}.bvA .dif b{color:#8a5200}`,
   html: d => BLOCK.A.html(d).replace('<div class="parts">', `<p class="dif">このPCとの違い: 既定にだけある <b>1件</b>・中身が違う <b>2件</b>・手元にだけある 1件</p><div class="parts">`), ver: st => verTable(st, 'button') },
  G: { name: 'G 札と要約、名前は開くと出る（A+E）', css: BLOCK.A.css + `.bvA details summary{cursor:pointer;color:#0b7e8f;font-weight:700;font-size:12px}`,
   html: d => `<div class="bvA">${facts(d)}<details><summary>中身の名前を見る・外す</summary><div class="parts">${partList(d, 'pl')}</div></details><div class="acts"><button type="button">このPCの設定から作り直す…</button><button type="button" class="textbtn" style="color:#a4463d">既定を消す</button></div></div>`,
   ver: st => verTable(st, 'button') },
  H: { name: 'H 札と項目（空は1行・外すを大きく・共通設定も）（A+C）', css: BLOCK.A.css + `
   .bvA .pl b .n{display:inline-block;min-width:18px;padding:0 5px;border-radius:999px;background:#e7f4f6;color:#216177;font-size:10px;text-align:center}
   .bvA .pl .z{color:#93a4ab;font-size:12px;padding-top:3px}.bvA em button{font-size:11px;color:#8a5f5a;border-left:1px solid #e3eaee;border-radius:0;padding:2px 7px;margin-left:2px}
   .bvA em button:hover{color:#a4463d;background:#fdf0ee}`,
   html: d => `<div class="bvA">${facts(d)}<div class="parts">${chips(d)}${empties(d)}<div class="pl"><b>共通設定</b><span class="z">${d.settings ? '入っています（出力先・抽出方式・控え など）' : '入っていない'}</span></div></div><div class="acts"><button type="button">このPCの設定から作り直す…</button><button type="button" class="textbtn" style="color:#a4463d">既定を消す</button></div></div>`,
   ver: st => verTable(st, 'button') },
 });
 window.DV = {
  DIALOG, BLOCK,
  async dialog(k) {
   const o = await (await fetch('/api/defaults/offer')).json(), v = DIALOG[k];
   style('dv-style', '.dv-lead{margin:0 0 10px;font-size:12.5px;line-height:1.65;color:#38505c}.dv-safe{margin:10px 0 0;font-size:11px;color:#647581}.def-modal{width:min(760px,94vw)}' + v.css);
   document.getElementById('def-dialog-body').innerHTML = v.html(o);
   const dlg = document.getElementById('def-dialog'); if (!dlg.open) dlg.showModal();
  },
  async block(k) {
   const d = (await (await fetch('/api/defaults')).json()).defaults, st = await (await fetch('/api/release/status')).json(), v = BLOCK[k];
   style('bv-style', '.rel-tag.is-warn{background:#fbf0dc;color:#8a5200}' + v.css);
   document.getElementById('def-body').innerHTML = v.html(d);
   document.getElementById('rel-versions').innerHTML = v.ver(st);
  },
 };
 function style(id, css) { let s = document.getElementById(id); if (!s) { s = document.createElement('style'); s.id = id; document.head.appendChild(s) } s.textContent = css }
})();
