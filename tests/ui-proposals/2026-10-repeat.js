// 2.7.0 繰り返し列の展開（1行に番号付きで繰り返し入っている列を、繰り返しごとの行に戻す）の案（CLAUDE.md §3）。
// いま: この操作は無い。M の式を詳細エディターで手で書くしかない（110列が横に並び、何をすればよいかが画面に無い）。
// 本物の Power Query エディター（撮影用の環境の後処理のクエリ「受注明細の後処理」。見本は 伝票10列 ＋ 明細10列×9回 ＋ 10列 の 40行）に、
// 案ごとの入口・ダイアログを差し込む。見つけた繰り返し・展開したあとの表は、本物の受け口（/api/m-query/repeat・add-step・preview）の結果。
// 撮り方: await window.RP.show(k, view)。view 1 = 開いた直後（列名から見つけた形）、view 2 = 例外（並びで決める・まとめた名前が共通の列と重なる）。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は上位3案 B・E・D と組合せ案 H〜K、3回目は上位3案 K・H・I と組合せ案 L〜O。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json());
 const CSS = `
 .rp *{box-sizing:border-box}
 dialog.rp-dlg .modal{width:min(1120px,94vw)}
 dialog.rp-dlg.w-s .modal{width:min(760px,94vw)} dialog.rp-dlg.w-m .modal{width:min(940px,94vw)}
 .rp{display:grid;gap:12px;font-size:12.5px;color:#22414c;min-width:0}
 .rp .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}.rp .sp{flex:1}
 .rp .lead{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:9px;background:#eef7f8;border:1px solid #cfe4e8;color:#24434d;flex-wrap:wrap}
 .rp .lead b{color:#0b4f5c}.rp .lead.warn{background:#fff6e5;border-color:#f0d9a8;color:#6e4a0a}.rp .lead.warn b{color:#7a4f00}
 .rp .lead.ng{background:#fff0ee;border-color:#f0c9c2;color:#8d2a1c}
 .rp .seg{display:inline-flex;border:1px solid #c8d6dc;border-radius:8px;overflow:hidden;background:#fff}
 .rp .seg span{padding:6px 13px;font-weight:800;color:#5a727c;border-left:1px solid #e3ebee;white-space:nowrap}.rp .seg span:first-child{border-left:0}
 .rp .seg span.on{background:#0b6577;color:#fff}
 .rp .pill{display:inline-flex;gap:4px;align-items:center;padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:800;background:#eef3f5;color:#35505b;white-space:nowrap}
 .rp .pill.ok{background:#e2f4ec;color:#087a57}.rp .pill.warn{background:#fff4dc;color:#8a5a0c}.rp .pill.ng{background:#fff0ee;color:#a12d1a}
 .rp .card{border:1px solid #dce6ea;border-radius:10px;background:#fff;padding:10px 12px;display:grid;gap:8px;min-width:0;align-content:start}
 .rp .cap{display:flex;align-items:center;gap:8px;font-weight:800;color:#17384e}.rp .cap small{font-weight:600;color:#6b7f88}
 .rp .cap i{font-style:normal;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:#0b6577;color:#fff;font-size:11px}
 .rp .note{color:#6b7f88;font-size:11.5px}
 .rp input.f,.rp .numf input{height:30px;border:1px solid #c8d6dc;border-radius:7px;padding:0 8px;font:inherit;font-size:12.5px;background:#fff;width:100%;min-width:0}
 .rp input.f.bad{border-color:#d0574a;background:#fff6f5;box-shadow:0 0 0 2px #f6d2cc}
 .rp .chk{display:flex;align-items:center;gap:6px;font-weight:700;color:#2f4a55;white-space:nowrap}.rp .chk input{width:16px;height:16px;margin:0}
 .rp .tbl{overflow:auto;border:1px solid #dce6ea;border-radius:9px;background:#fff;min-width:0}
 .rp table{border-collapse:collapse;font-size:12px;width:max-content;min-width:100%}
 .rp th{position:sticky;top:0;background:#f0f5f6;color:#35505b;text-align:left;font-size:11.5px;padding:5px 9px;border-bottom:1px solid #dce6ea;white-space:nowrap;z-index:1}
 .rp th.new{background:#e2f2f4;color:#0b4f5c}.rp th.idx{background:#efe8f8;color:#5c3f96}
 .rp td{padding:4px 9px;border-top:1px solid #f0f4f5;white-space:nowrap}
 .rp td.nul{color:#a7b5bb;font-style:italic}.rp td.src{color:#55707a;font-size:11.5px}.rp td.miss{color:#b7c4c9}
 .rp td.k{font-weight:800;color:#5c3f96}.rp tr.grp td{border-top:2px solid #cfe1e6}
 .rp .strip{display:flex;gap:1px;height:30px;border-radius:7px;overflow:hidden;border:1px solid #d3e0e5;background:#fff}
 .rp .strip span{flex:1;min-width:0;background:#e7edf0}
 .rp .strip span.r0{background:#0b6577}.rp .strip span.r1{background:#5fb3c0}.rp .strip span.r2{background:#2f8f9e}.rp .strip span.r3{background:#8ccbd4}
 .rp .strip span.ng{background:#d0574a}
 .rp .strip-l{display:flex;font-size:11px;color:#4f6873;font-weight:700}.rp .strip-l span{text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .rp .names{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px 8px}
 .rp .nm{display:grid;gap:2px}.rp .nm small{font-size:10.5px;color:#7b8f97;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .rp .numf{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
 .rp .numf label{display:grid;gap:3px;font-weight:800;font-size:12px;color:#17384e}.rp .numf label small{font-weight:600;color:#6b7f88}
 .rp .unit{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:6px}.rp .unit em{font-style:normal;color:#596d77}
 .rp .steps{display:flex;gap:6px}.rp .steps span{flex:1;padding:7px 10px;border-radius:8px;background:#f1f5f6;color:#6b7f88;font-weight:800;border:1px solid #e1e9ec;white-space:nowrap}
 .rp .steps span.on{background:#e3f3f5;border-color:#9fd1d9;color:#0b4f5c}.rp .steps span.done{color:#087a57;background:#eef8f3;border-color:#cfe9dc}
 .rp .cands{display:grid;gap:6px;align-content:start}
 .rp .cand{display:grid;gap:3px;padding:9px 11px;border-radius:9px;border:1px solid #dce6ea;background:#fff;color:#2f4a55}
 .rp .cand b{color:#17384e}.rp .cand small{color:#6b7f88}.rp .cand.on{border-color:#0b6577;box-shadow:inset 3px 0 #0b6577;background:#f2fafb}
 .rp .split{display:grid;grid-template-columns:260px minmax(0,1fr);gap:12px;min-width:0}
 .rp .arrow{font-size:18px;color:#7b8f97;text-align:center}
 .rp .ba{display:grid;grid-template-columns:minmax(0,1fr) 26px minmax(0,1.3fr);gap:8px;align-items:center;min-width:0}
 .rp .sum{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}.rp .sum b{font-size:15px;color:#0b4f5c}
 .rp .err{color:#a12d1a;font-weight:700;font-size:11.5px}
 .rp-banner{display:flex;align-items:center;gap:10px;padding:8px 12px;margin:0 0 6px;border-radius:8px;background:#e2f4ec;border:1px solid #bfe3d1;color:#1d4a3a;font-size:12.5px;flex-wrap:wrap}
 .rp-banner b{color:#087a57}.rp-banner .sp{flex:1}.rp-banner button{height:28px;padding:0 11px;font-size:12px}
 .rp-banner.info{background:#eef7f8;border-color:#cfe4e8;color:#24434d}.rp-banner.info b{color:#0b4f5c}
 .rp-pop{position:fixed;z-index:60;background:#fff;border:1px solid #c8d6dc;border-radius:10px;box-shadow:0 14px 40px rgba(15,45,60,.25);padding:12px 14px;width:620px}
 .rp-band{display:flex;height:20px;margin:0 0 2px;font-size:10.5px;font-weight:800;color:#fff}
 .rp-band span{display:flex;align-items:center;justify-content:center;border-right:1px solid #fff;white-space:nowrap;overflow:hidden}
 .mqx-rb.rp-new{border-color:#0b6577;background:#f2fafb}
 .rp .errbar{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:9px;background:#fff0ee;border:1px solid #f0c9c2;color:#8d2a1c;font-weight:700}
 .rp .errbar i{font-style:normal;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:#c2412f;color:#fff;font-size:12px;font-weight:900}
 .rp .nm .why{color:#a12d1a;font-weight:700;font-size:10.5px}
 .rp .rec{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px 12px;border-radius:10px;border:1px solid #9fd1d9;background:#f2fafb}
 .rp .rec .big{font-size:16px;font-weight:900;color:#0b4f5c;white-space:nowrap}.rp .rec small{color:#4f6873}
 .rp .rec.manual{border-color:#e6cf9b;background:#fffaf0}.rp .rec.manual .big{color:#7a4f00}
 .rp details.more summary{cursor:pointer;font-weight:800;color:#0b6577;list-style:none}.rp details.more summary::before{content:'▸ ';}.rp details.more[open] summary::before{content:'▾ '}
 .rp .left{display:grid;gap:10px;align-content:start}
 .rp .nm small.bad{color:#a12d1a;font-weight:800}
 .rp .tog{display:flex;align-items:center;gap:8px;width:100%;height:34px;padding:0 12px;border:1px solid #c8d6dc;border-radius:8px;background:#f6f9fa;color:#17384e;font-weight:800;font-size:12.5px;cursor:pointer}
 .rp .tog em{font-style:normal;font-weight:600;color:#6b7f88}.rp .tog .sp{flex:1}.rp .tog b{color:#0b6577}
 .rp .chips{display:flex;flex-wrap:wrap;gap:5px}.rp .chips span{padding:3px 9px;border-radius:999px;background:#e3f3f5;color:#0b4f5c;font-weight:800;font-size:11.5px}
 .rp .chips span.bad{background:#fff0ee;color:#a12d1a;box-shadow:inset 0 0 0 1px #e8a79c}
 .rp .noafter{padding:14px;border:1px dashed #e0b9b1;border-radius:9px;background:#fffaf9;color:#8d2a1c;font-weight:700;text-align:center}
 .rp .recbox{display:grid;gap:8px;padding:10px 12px;border-radius:10px;border:1px solid #9fd1d9;background:#f2fafb}
 .rp .recbox.manual{border-color:#e6cf9b;background:#fffaf0}
 .rp .recbox .top{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.rp .recbox .big{font-size:16px;font-weight:900;color:#0b4f5c;white-space:nowrap}
 .rp .recbox.manual .big{color:#7a4f00}.rp .recbox small{color:#4f6873}
 .rp .inl{display:flex;align-items:center;gap:6px;font-weight:800;color:#17384e;white-space:nowrap}.rp .inl input{width:64px;height:30px;border:1px solid #c8d6dc;border-radius:7px;padding:0 8px;font:inherit}
 `;
 let D = null;   // 本物のデータ（列・見つけた繰り返し・展開したあとの表）
 async function load() {
  if (D) return D;
  const cols = mqView.columns.map(c => c.name);
  const det = await post('/api/m-query/repeat', { columns: cols, layout: { start: 11, width: 10, count: 9 } });
  const cand = det.candidates[0];
  const add = await post('/api/m-query/add-step', { code: mqEditing.code, name: mqEditing.name, step: cand.step });
  const pv = await post('/api/m-query/preview', { code: add.code, name: mqEditing.name, sample_job: 'J1', query_id: mqEditing.id });
  const bad = { ...cand.step, names: cand.step.names.map(n => n === '備考' ? '状態' : n) };
  const chk = await post('/api/m-query/repeat', { columns: cols, step: bad });
  D = { cols, cand, layout: det.layout, after: pv, rowsIn: mqView.row_count, bad, problems: chk.problems };
  D.fit = innerHeight < 1000 ? 4 : 8;
  D.fit3 = innerHeight < 1000 ? 6 : 9;   // 展開したあとの表の行数（フル HD でも窓の中で切れないように）
  return D;
 }
 const st = () => D.cand.step;
 const W = () => st().names.length, N = () => st().groups.length;
 const where = () => `${D.cand.first}〜${D.cand.last}列目`;
 const outSize = () => `${D.rowsIn}行 → ${D.after.row_count}行 · ${D.after.columns.length}列`;
 const names = v => v === 2 ? D.bad.names : st().names;
 const badName = (v, n) => v === 2 && n === '状態';
 function ensureStyle() { if (!document.getElementById('rp-style')) { const s = document.createElement('style'); s.id = 'rp-style'; s.textContent = CSS; document.head.appendChild(s) } }
 function ribbon(lit) {
  const box = document.getElementById('mqx-ribbon'); if (!box) return;
  mqRenderRibbon();
  const w = box.querySelector('.mqx-rbw'); if (!w) return;
  w.insertAdjacentHTML('afterend', `<span class="mqx-rbw"><button type="button" class="mqx-rb${lit ? ' rp-new' : ''}"><i>⇊</i>繰り返し列の展開</button></span>`);
 }
 function dialog(cls, title, body, foot) {
  let d = document.getElementById('rp-dlg');
  if (!d) { d = document.createElement('dialog'); d.id = 'rp-dlg'; document.getElementById('mq-editor').appendChild(d) }
  d.className = 'rp-dlg ' + cls;
  d.innerHTML = `<div class="modal"><div class="modalhead"><div><small>変換</small><h2>${title}</h2></div><button type="button" class="iconbtn" aria-label="閉じる">×</button></div>
   <div class="modalbody"><div class="rp">${body}</div></div><div class="modalfoot">${foot}</div></div>`;
  if (!d.open) d.showModal();
 }
 const foot = (v, ok = '行に展開', extra = '') => `${extra}<small class="mq-op-note" style="margin-right:auto">${v === 2 ? `<span class="err">${E(D.problems[0] || '')}</span>` : E(outSize())}</small>
   <button type="button" class="secondary">キャンセル</button><button type="button"${v === 2 ? ' disabled' : ''}>${ok}</button>`;
 function strip(v, opt = {}) {
  const used = new Map(); st().groups.forEach((g, k) => g.forEach(c => c && used.set(c, k)));
  const cells = D.cols.map(c => used.has(c) ? `<span class="r${used.get(c) % 2 ? 1 : 0}${opt.first && used.get(c) === 0 ? '' : ''}" title="${E(c)}"></span>` : '<span></span>').join('');
  const L = D.cols.length, a = D.cand.first - 1, b = D.cand.last;
  const lab = `<div class="strip-l"><span style="flex:${a}">共通 1〜${a}列目</span>${st().groups.map((g, k) => `<span style="flex:${W()}">${k + 1}回目</span>`).join('')}<span style="flex:${L - b}">共通 ${b + 1}〜${L}列目</span></div>`;
  return `<div class="strip">${cells}</div>${lab}`;
 }
 function matrix(v, cut = 9) {
  const gs = st().groups.slice(0, cut);
  return `<div class="tbl" style="max-height:${v === 2 ? 330 : 360}px"><table><thead><tr><th class="new">まとめた列の名前</th>${gs.map((g, k) => `<th>${st().numbers[k]}回目</th>`).join('')}</tr></thead><tbody>
   ${names(v).map((n, j) => `<tr><td style="padding:3px 6px"><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}" style="width:130px"></td>${gs.map(g => g[j] ? `<td class="src">${E(g[j])}</td>` : '<td class="miss">（無い）</td>').join('')}</tr>`).join('')}
   </tbody></table></div>`;
 }
 function afterTable(maxRows = 9, colsShown = null) {
  const a = D.after, cols = a.columns.map(c => c.name), idx = cols.indexOf(st().index);
  const pick = colsShown || cols.map((_, i) => i);
  return `<div class="tbl"><table><thead><tr>${pick.map(i => `<th class="${i === idx ? 'idx' : (i > idx && i <= idx + W()) ? 'new' : ''}">${E(cols[i])}</th>`).join('')}</tr></thead><tbody>
   ${a.rows.slice(0, maxRows).map((r, q) => `<tr class="${q && r[0] !== a.rows[q - 1][0] ? 'grp' : ''}">${pick.map(i => r[i] === null ? '<td class="nul">null</td>' : `<td class="${i === idx ? 'k' : ''}">${E(r[i])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
 }
 const opts = v => `<div class="row"><label class="numf" style="display:flex;align-items:center;gap:6px;font-weight:800;color:#17384e">番号の列の名前<input class="f" value="${E(st().index)}" style="width:110px"></label>
   <label class="chk"><input type="checkbox" checked>値がすべて空の回は行にしない</label><span class="note">（9回分の枠のうち、使っていない回）</span></div>`;
 const modeSeg = v => `<span class="seg"><span class="${v === 2 ? '' : 'on'}">列名から見つける</span><span class="${v === 2 ? 'on' : ''}">並びで決める</span></span>`;
 const layoutFields = v => `<div class="numf"><label>先頭の列<span class="unit"><input value="${D.cand.first}"><em>列目（品番1）</em></span></label><label>1回分の列数<span class="unit"><input value="${W()}"><em>列</em></span></label><label>回数<span class="unit"><input value="${N()}"><em>回</em></span></label></div>`;
 const errbar = () => `<div class="errbar"><i>!</i><span>${E(D.problems[0])}</span></div>`;
 const nameGrid = (v, at) => `<div class="names">${names(v).map((n, j) => { const src = `<small>${at === 'above' ? '' : '← '}${E(st().groups[0][j])} … ${E(st().groups[N() - 1][j])}</small>`;
   const inp = `<input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}">`; return `<div class="nm">${at === 'above' ? src + inp : inp + src}${badName(v, n) ? '<span class="why">共通の列にある名前</span>' : ''}</div>` }).join('')}</div>`;
 // 3回目: 誤りは元の列の注記と同じ場所に出す（同じ段のほかの欄がずれない）
 const nameGrid3 = v => `<div class="names">${names(v).map((n, j) => `<div class="nm"><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}">${badName(v, n) ? '<small class="bad">共通の列にある名前です</small>' : `<small>← ${E(st().groups[0][j])} … ${E(st().groups[N() - 1][j])}</small>`}</div>`).join('')}</div>`;
 const recBox = (v, inner = '') => `<div class="recbox${v === 2 ? ' manual' : ''}"><div class="top"><span class="big">${W()}列 × ${N()}回</span><small>${v === 2 ? `並びで決めています（${D.cand.first}列目から）` : `${E(where())}を、列名から見つけました`}</small><span class="sp" style="flex:1"></span>${modeSeg(v)}</div>${inner}${strip(v)}</div>`;
 const noAfter = () => `<div class="noafter">名前が重なっているため、展開したあとの表はまだ出せません（名前を直すと出ます）</div>`;
 const after3 = v => `<div class="card"><div class="cap">展開したあと <small>${v === 2 ? '' : E(outSize())}</small></div>${v === 2 ? noAfter() : afterTable(D.fit3, firstCols())}</div>`;
 const tog = (v, open) => `<button type="button" class="tog"><b>${open ? '▾' : '▸'}</b>まとめた列の名前・番号の列・空の回の扱いを直す<span class="sp"></span><em>${E(names(v).slice(0, 4).join('・'))} ほか${W() - 4}列 · 番号の列「${E(st().index)}」</em></button>`;
 const foot2 = v => `<small class="mq-op-note" style="margin-right:auto">${v === 2 ? '<span class="err">名前を直すと展開できます</span>' : E(outSize())}</small>
   <button type="button" class="secondary">キャンセル</button><button type="button"${v === 2 ? ' disabled' : ''}>行に展開</button>`;
 const firstCols = () => [0, 1, 2, 3, 9, 10, 11, 12, 13, 14, 15];
 const P = {
  // A 対応表: まとめた名前（行）× 回（列）の表で、どの列がどこへ入るかを全部見せる
  A(v) {
   ribbon(true);
   const head = `<div class="lead"><b>${E(where())}に、${W()}列 × ${N()}回の繰り返しを見つけました</b><span>共通の列 ${D.cand.common}列は、どの行にもそのまま写します</span><span class="sp"></span>${modeSeg(v)}</div>`;
   dialog('', '繰り返し列の展開', head + (v === 2 ? layoutFields(v) : '') + matrix(v) + opts(v), foot(v));
  },
  // B 帯と前後: 列の並びを色の帯で見せ、名前を並べて直し、1行が何行になるかを前後で見せる
  B(v) {
   ribbon(true);
   const body = `<div class="card"><div class="cap">繰り返しの列 <small>${E(where())} · ${W()}列 × ${N()}回</small><span class="sp"></span>${modeSeg(v)}</div>${v === 2 ? layoutFields(v) : ''}${strip(v)}</div>
    <div class="card"><div class="cap">まとめた列の名前 <small>列名から番号を除いた名前です。直せます</small></div><div class="names">${names(v).map((n, j) => `<div class="nm"><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}"><small>${E(st().groups[0][j])} … ${E(st().groups[N() - 1][j])}</small></div>`).join('')}</div>${opts(v)}</div>
    <div class="card"><div class="cap">展開したあと <small>${E(outSize())}（伝票 J24100 は ${D.after.rows.filter(r => r[0] === 'J24100').length}行に）</small></div>${afterTable(8, firstCols())}</div>`;
   dialog('', '繰り返し列の展開', body, foot(v));
  },
  // C 手順を分ける: ①繰り返しの列 ②まとめた名前 ③確かめる、を順に進める
  C(v) {
   ribbon(true);
   const steps = `<div class="steps"><span class="${v === 2 ? 'done' : 'on'}">① 繰り返しの列</span><span class="${v === 2 ? 'on' : ''}">② まとめた列の名前</span><span>③ 確かめる</span></div>`;
   const body = v === 2 ? steps + `<div class="card"><div class="cap">まとめた列の名前 <small>${W()}列</small></div><div class="names">${names(v).map((n, j) => `<div class="nm"><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}"><small>${E(st().groups[0][j])}</small></div>`).join('')}</div>${opts(v)}</div>`
    : steps + `<div class="card"><div class="cap">どの列が繰り返しか <span class="sp"></span>${modeSeg(v)}</div><div class="sum"><b>${E(where())}</b><span>${W()}列 × ${N()}回（品番1〜備考1 が1回分）</span></div>${strip(v)}<div class="note">違うときは「並びで決める」で、先頭の列・列数・回数を入れます</div></div>`;
   dialog('w-m', '繰り返し列の展開', body, `<small class="mq-op-note" style="margin-right:auto">${v === 2 ? `<span class="err">${E(D.problems[0])}</span>` : ''}</small><button type="button" class="secondary">${v === 2 ? '戻る' : 'キャンセル'}</button><button type="button"${v === 2 ? ' disabled' : ''}>次へ</button>`);
  },
  // D 数で決める: 先頭の列・列数・回数の3つの欄（見つけた値が入っている）と、名前の一覧
  D(v) {
   ribbon(true);
   const body = `<div class="lead${v === 2 ? ' warn' : ''}"><b>${v === 2 ? '並びを手で決めています' : '列名から見つけた値を入れました'}</b><span>${v === 2 ? '列名から見つけた値に戻すには「見つけ直す」' : '違うときは数を直します'}</span><span class="sp"></span><button type="button" class="secondary" style="height:28px;padding:0 10px">見つけ直す</button></div>
    ${layoutFields(v)}
    <div class="card"><div class="cap">まとめた列の名前</div><div class="names">${names(v).map((n, j) => `<div class="nm"><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}"><small>← ${E(st().groups[0][j])}</small></div>`).join('')}</div></div>${opts(v)}`;
   dialog('w-m', '繰り返し列の展開', body, foot(v));
  },
  // E 候補と中身: 左に見つけた候補（と「並びで決める」）、右に選んだ候補の名前と、展開したあとの表
  E(v) {
   ribbon(true);
   const cands = `<div class="cands"><div class="cap">繰り返しの候補</div><div class="cand${v === 2 ? '' : ' on'}"><b>${W()}列 × ${N()}回</b><small>${E(where())} · 品番1〜備考9</small><span class="pill ok">おすすめ</span></div>
    <div class="cand${v === 2 ? ' on' : ''}"><b>並びで決める</b><small>先頭の列・列数・回数を入れる</small></div></div>`;
   const right = `<div class="card">${v === 2 ? layoutFields(v) : ''}<div class="cap">まとめた列の名前 <small>1回目の列 → 名前</small></div><div class="names">${names(v).map((n, j) => `<div class="nm"><small>${E(st().groups[0][j])}</small><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}"></div>`).join('')}</div>${opts(v)}</div>
    <div class="card"><div class="cap">展開したあと <small>${E(outSize())}</small></div>${afterTable(6, firstCols())}</div>`;
   dialog('', '繰り返し列の展開', `<div class="split">${cands}<div style="display:grid;gap:10px;min-width:0">${right}</div></div>`, foot(v));
  },
  // F（方向が違う）既定で済ませて例外だけ: 押すとすぐ見つけた形で足し、表の上の帯で結果を言う。直すときだけ小さな枠を開く
  async F(v) {
   await mqAddStep(st());
   ribbon(false);
   const tb = document.querySelector('.mqx-grid,.mqx-table,#mqx-table') || document.querySelector('#mq-editor table')?.closest('div');
   const html = `<div class="rp-banner" id="rp-banner"><b>✓ ${E(where())}の ${W()}列 × ${N()}回 を行にしました</b><span>${E(st().names.slice(0, 4).join('・'))} ほか${W() - 4}列 · 番号の列「${E(st().index)}」 · ${E(outSize())}</span><span class="sp"></span><button type="button" class="secondary">名前や範囲を直す</button><button type="button" class="secondary">元に戻す</button></div>`;
   document.getElementById('rp-banner')?.remove();
   tb?.insertAdjacentHTML('beforebegin', html);
   if (v === 2) {
    const b = document.querySelector('#rp-banner button').getBoundingClientRect();
    document.body.insertAdjacentHTML('beforeend', `<div class="rp-pop rp" style="left:${b.right - 620}px;top:${b.bottom + 6}px;position:fixed"><div class="row">${modeSeg(v)}<span class="sp"></span></div>${layoutFields(v)}
     <div class="names">${names(v).map((n, j) => `<div class="nm"><input class="f${badName(v, n) ? ' bad' : ''}" value="${E(n)}"><small>${E(st().groups[0][j])}</small></div>`).join('')}</div>
     <div class="row"><span class="err">${E(D.problems[0])}</span><span class="sp"></span><button type="button" class="secondary">やめる</button><button type="button" disabled>直す</button></div></div>`);
   }
  },
  // G（方向が違う）表の見出しで見せる: 見出しの上に「共通・1回目・2回目…」の色の帯を出し、繰り返しを表の上で確かめてから押す
  G(v) {
   ribbon(true);
   const head = document.querySelector('#mq-editor thead tr');
   if (head) {
    const ths = [...head.children], used = new Map(); st().groups.forEach((g, k) => g.forEach(c => c && used.set(c, k)));
    ths.forEach(th => { const n = th.textContent.replace(/^(ABC|123|1\.2|日付)\s*/, '').trim(); if (used.has(n)) { const k = used.get(n); th.style.boxShadow = `inset 0 4px ${k % 2 ? '#5fb3c0' : '#0b6577'}`; th.style.background = k % 2 ? '#eef8fa' : '#e3f3f5' } });
   }
   const tb = document.querySelector('#mq-editor table')?.closest('div');
   document.getElementById('rp-banner')?.remove();
   const msg = v === 2 ? `<b>選んだ10列（品番1〜備考1）を1回分として、同じ並びを ${N()}回分見つけました</b><span>まとめた名前: ${names(v).map(n => n === '状態' ? `<u style="color:#a12d1a">${n}</u>` : E(n)).join('・')}</span><span class="err">${E(D.problems[0])}</span>`
    : `<b>繰り返しを見つけました: ${E(where())} · ${W()}列 × ${N()}回</b><span>見出しの色の帯が1回分です（濃い・薄いが交互）。違うときは、1回分の見出しを選んでから押します</span>`;
   tb?.insertAdjacentHTML('beforebegin', `<div class="rp-banner info" id="rp-banner">${msg}<span class="sp"></span><button type="button" class="secondary">名前を直す</button><button type="button"${v === 2 ? ' disabled' : ''}>行に展開</button></div>`);
  },
  // ---- 2回目: 組合せ案 -------------------------------------------------------------
  // H = B の帯・名前・展開したあと ＋ E の「おすすめ」の札を要約に ＋ 誤りを上の帯と欄の下とボタンの横に
  H(v) {
   ribbon(true);
   const rec = v === 2 ? `<div class="rec manual"><span class="big">${W()}列 × ${N()}回</span><small>並びで決めています（${D.cand.first}列目から）</small>${modeSeg(v)}</div>`
    : `<div class="rec"><span class="big">${W()}列 × ${N()}回</span><small>${E(where())} · 品番1〜備考9 · <span class="pill ok">列名から見つけました</span></small>${modeSeg(v)}</div>`;
   const body = rec + (v === 2 ? errbar() + layoutFields(v) : '') + `<div>${strip(v)}</div>
    <div class="card"><div class="cap">まとめた列の名前 <small>列名から番号を除いた名前です。直せます</small></div>${nameGrid(v, 'below')}${opts(v)}</div>
    <div class="card"><div class="cap">展開したあと <small>${E(outSize())}</small></div>${afterTable(D.fit, firstCols())}</div>`;
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
  // I = B ＋ D: 先頭の列・列数・回数の欄をいつも出し（見つけた値入り）、帯がその範囲を示す。「見つけ直す」で自動に戻る
  I(v) {
   ribbon(true);
   const head = `<div class="lead${v === 2 ? ' warn' : ''}"><b>${v === 2 ? '並びを手で決めています' : `列名から見つけました: ${E(where())}`}</b><span>${v === 2 ? '' : '違うときは、下の数を直します'}</span><span class="sp"></span>${v === 2 ? '<button type="button" class="secondary" style="height:28px;padding:0 10px">列名から見つけ直す</button>' : ''}</div>`;
   const body = head + (v === 2 ? errbar() : '') + `<div class="card">${layoutFields(v)}${strip(v)}</div>
    <div class="card"><div class="cap">まとめた列の名前</div>${nameGrid(v, 'below')}${opts(v)}</div>
    <div class="card"><div class="cap">展開したあと <small>${E(outSize())}</small></div>${afterTable(D.fit, firstCols())}</div>`;
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
  // J = E の2枚の並び（左: 候補・要約・帯・番号と空の扱い、右: 名前と展開したあと）。左の空きを埋める
  J(v) {
   ribbon(true);
   const left = `<div class="left"><div class="cap">繰り返しの見つけ方</div>
    <div class="cand${v === 2 ? '' : ' on'}"><b>列名から見つける</b><small>${W()}列 × ${N()}回 · ${E(where())}</small>${v === 2 ? '' : '<span class="pill ok">おすすめ</span>'}</div>
    <div class="cand${v === 2 ? ' on' : ''}"><b>並びで決める</b><small>先頭の列・列数・回数を入れる</small></div>
    ${v === 2 ? `<div class="card" style="padding:8px">${layoutFields(v).replace('repeat(3,minmax(0,1fr))', '1fr')}</div>` : ''}
    <div class="card" style="padding:8px">${strip(v).replace(/<div class="strip-l">[\s\S]*<\/div>$/, '')}<small class="note">共通 ${D.cand.common}列 · 繰り返し ${D.cand.columns}列</small></div>
    <div class="card" style="padding:8px"><label style="display:grid;gap:3px;font-weight:800">番号の列の名前<input class="f" value="${E(st().index)}"></label><label class="chk"><input type="checkbox" checked>値がすべて空の回は行にしない</label></div></div>`;
   const right = `<div style="display:grid;gap:10px;min-width:0;align-content:start">${v === 2 ? errbar() : ''}<div class="card"><div class="cap">まとめた列の名前 <small>1回目の列 → 名前</small></div>${nameGrid(v, 'above')}</div>
    <div class="card"><div class="cap">展開したあと <small>${E(outSize())}</small></div>${afterTable(D.fit, firstCols())}</div></div>`;
   dialog('', '繰り返し列の展開', `<div class="split">${left}${right}</div>`, foot2(v));
  },
  // K = 既定で済ませて例外だけ: 帯と要約と展開したあとだけを見せ、名前の一覧は畳む（誤りのときは開いて欄を示す）
  K(v) {
   ribbon(true);
   const rec = `<div class="rec${v === 2 ? ' manual' : ''}"><span class="big">${W()}列 × ${N()}回</span><small>${v === 2 ? `並びで決めています（${D.cand.first}列目から）` : `${E(where())}を、列名から見つけました`}</small>${modeSeg(v)}</div>`;
   const body = rec + (v === 2 ? errbar() + layoutFields(v) : '') + `<div>${strip(v)}</div>
    <div class="card"><div class="cap">展開したあと <small>${E(outSize())} · まとめた列: ${E(names(v).join('・'))}</small></div>${afterTable(D.fit, firstCols())}</div>
    <details class="more"${v === 2 ? ' open' : ''}><summary>まとめた列の名前・番号の列・空の回の扱いを直す</summary><div style="display:grid;gap:8px;margin-top:8px">${nameGrid(v, 'below')}${opts(v)}</div></details>`;
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
  // ---- 3回目: 組合せ案 -------------------------------------------------------------
  // L = K の直し: 畳む所をボタンの形に、誤りは注記の場所に、例外では直す欄を赤い帯のすぐ下に
  L(v) {
   ribbon(true);
   const edit = `<div style="display:grid;gap:8px">${nameGrid3(v)}${opts(v)}</div>`;
   const body = recBox(v, v === 2 ? layoutFields(v) : '') + (v === 2 ? errbar() + tog(v, true) + edit + after3(v) : after3(v) + tog(v, false));
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
  // M = K ＋ H: 要約と帯を1つの枠に。まとめた名前は札で読ませ（畳まない）、直すときだけ欄にする
  M(v) {
   ribbon(true);
   const chips = `<div class="card"><div class="cap">まとめた列 <small>番号を除いた名前 · 番号の列「${E(st().index)}」 · 値がすべて空の回は行にしない</small><span class="sp" style="flex:1"></span>${v === 2 ? '' : '<button type="button" class="secondary" style="height:28px;padding:0 10px">名前を直す</button>'}</div>
    ${v === 2 ? nameGrid3(v) + opts(v) : `<div class="chips">${names(v).map(n => `<span>${E(n)}</span>`).join('')}</div>`}</div>`;
   const body = recBox(v, v === 2 ? layoutFields(v) : '') + (v === 2 ? errbar() : '') + chips + after3(v);
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
  // N = K ＋ I: 先頭の列・列数・回数を要約の枠の中に1行で（いつも直せる）。「列名から見つけ直す」はいつも同じ場所
  N(v) {
   ribbon(true);
   const inl = `<div class="row"><label class="inl">先頭<input value="${D.cand.first}">列目</label><label class="inl">1回分<input value="${W()}">列</label><label class="inl">回数<input value="${N()}">回</label><span class="sp"></span><button type="button" class="secondary" style="height:28px;padding:0 10px"${v === 2 ? '' : ' disabled'}>列名から見つけ直す</button></div>`;
   const box = `<div class="recbox${v === 2 ? ' manual' : ''}"><div class="top"><span class="big">${W()}列 × ${N()}回</span><small>${v === 2 ? '並びを手で決めています' : `${E(where())}を、列名から見つけました`}</small></div>${inl}${strip(v)}</div>`;
   const edit = `<div style="display:grid;gap:8px">${nameGrid3(v)}${opts(v)}</div>`;
   const body = box + (v === 2 ? errbar() + tog(v, true) + edit + after3(v) : after3(v) + tog(v, false));
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
  // O = H の直し: すべて見せたまま詰める（帯は枠の中、名前は注記の場所に誤り、見本は行を増やす）
  O(v) {
   ribbon(true);
   const body = recBox(v, v === 2 ? layoutFields(v) : '') + (v === 2 ? errbar() : '') + `<div class="card"><div class="cap">まとめた列の名前 <small>列名から番号を除いた名前です。直せます</small></div>${nameGrid3(v)}${opts(v)}</div>` + after3(v);
   dialog('', '繰り返し列の展開', body, foot2(v));
  },
 };
 window.RP = {
  keys: Object.keys(P),
  async show(k, v) {
   ensureStyle(); await load();
   document.getElementById('rp-dlg')?.close(); document.querySelectorAll('.rp-pop,#rp-banner').forEach(x => x.remove());
   await P[k](v); return true;
  },
 };
})();
