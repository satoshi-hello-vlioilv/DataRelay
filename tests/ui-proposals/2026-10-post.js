// 2.6.0 後処理（取り出した表を、出す前に Power Query の式で整える。ピボット・ピボット解除など）の案（CLAUDE.md §3）。
// いま: 対象の編集に後処理の場所は無い。整えるには、入力を Power Query にして式を書くしかなく、RNE・固定長・結合の表は整えられない。
// 本物の画面の「対象の編集」（撮影用の環境の対象「月別実績（縦持ち）」。入力は Power Query で、月が列に並ぶ横持ちの表）に、
// 案ごとのタブ・欄を差し込む。表の中身は本物の下読み（/api/post/preview）の結果。
// 組んだ手順: ①ピボット解除（品番・品名・工程 以外を「月」「数量」の縦に）→ ②ピボット（工程を見出しに、数量の合計）。
// 撮り方: await window.PP.show(k, view)。view 1 = 組んだあと（2つ目の手順を選んでいる）、view 2 = 初めて開いたとき（まだ何もない）。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は上位3案 B・G・A と組合せ案 H〜K、3回目は上位3案 H・J・B と組合せ案 L〜O。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const STEPS = [{ op: 'unpivot', mode: 'other', columns: ['品番', '品名', '工程'], attr: '月', value: '数量' },
  { op: 'pivot', column: '工程', value: '数量', agg: 'sum' }];
 const OPS = [['unpivot', 'ピボット解除', '横の列を縦に', '⇣'], ['pivot', 'ピボット', '値を見出しにして横へ', '⇢'], ['group', 'グループ化', 'まとめて合計・件数', 'Σ'],
  ['select', '列の選択', '残す列と並び', '▥'], ['rename', '名前の変更', '列の名前', 'Aa'], ['sort', '並べ替え', '行の順', '⇅'], ['m', 'M の式', '自由に書く', 'fx']];
 const CSS = `
 .pp{display:grid;gap:12px;font-size:12.5px;color:#22414c;min-width:0}
 .pp *{box-sizing:border-box}
 .pp .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}
 .pp .sp{flex:1}
 .pp .lead{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:10px;background:#f2f8f9;border:1px solid #d7e7ea;color:#24434d}
 .pp .lead b{color:#0b4f5c}
 .pp .seg{display:inline-flex;border:1px solid #c8d6dc;border-radius:9px;overflow:hidden;background:#fff}
 .pp .seg span{padding:7px 14px;font-weight:800;color:#5a727c;border-left:1px solid #e3ebee;white-space:nowrap}.pp .seg span:first-child{border-left:0}
 .pp .seg span.on{background:#0b6577;color:#fff}
 .pp .btn{height:32px;border-radius:8px;border:1px solid #c8d6dc;background:#fff;color:#17384e;font-weight:800;padding:0 12px;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
 .pp .btn.pri{background:#0b6577;border-color:#0b6577;color:#fff}.pp .btn.sm{height:27px;font-size:12px;padding:0 9px}
 .pp .btn.ghost{border-color:transparent;background:transparent;color:#0b6577}
 .pp .card{border:1px solid #dce6ea;border-radius:10px;background:#fff;padding:10px 12px;display:grid;gap:8px;min-width:0;align-content:start}
 .pp .cap{display:flex;align-items:center;gap:8px;font-weight:800;color:#17384e}.pp .cap small{font-weight:600;color:#6b7f88}
 .pp .note{color:#6b7f88;font-size:11.5px}
 .pp .pill{display:inline-flex;gap:4px;align-items:center;padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:800;background:#eef3f5;color:#35505b;white-space:nowrap}
 .pp .pill.ok{background:#e2f4ec;color:#087a57}.pp .pill.warn{background:#fff4dc;color:#8a5a0c}.pp .pill.ng{background:#fff0ee;color:#a12d1a}
 .pp .psteps{display:grid;gap:3px;align-content:start}
 .pp .pstep{display:grid;grid-template-columns:22px 26px minmax(0,1fr) auto;gap:6px;align-items:center;padding:6px 8px;border-radius:8px;border:1px solid transparent;color:#2f4a55}
 .pp .pstep i{font-style:normal;font-size:11px;color:#7b8f97;text-align:right}
 .pp .pstep .ic{width:24px;height:24px;border-radius:6px;display:grid;place-items:center;background:#eef4f6;color:#0b6577;font-weight:900;font-size:12px}
 .pp .pstep b{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pp .pstep small{display:block;color:#6b7f88;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .pp .pstep.on{background:#e6f4f6;border-color:#9fd1d9;color:#0b4f5c}.pp .pstep.src .ic{background:#f1eaf9;color:#5c3f96}
 .pp .pstep .x{color:#9aabb2;font-weight:900}
 .pp .tbl{overflow:auto;border:1px solid #dce6ea;border-radius:9px;background:#fff;min-width:0}
 .pp table{border-collapse:collapse;font-size:12px;width:max-content;min-width:100%}
 .pp th{position:sticky;top:0;background:#f0f5f6;color:#35505b;text-align:left;font-size:11.5px;padding:5px 9px;border-bottom:1px solid #dce6ea;white-space:nowrap}
 .pp th em{font-style:normal;font-size:10px;color:#0b6577;background:#e6f4f6;border-radius:4px;padding:0 4px;margin-right:4px}
 .pp th.new{background:#e9f6ef}.pp th.sel{background:#d8eef2;box-shadow:inset 0 -3px #0b6577}
 .pp th input{margin:0 4px 0 0;vertical-align:-2px}
 .pp td{padding:4px 9px;border-top:1px solid #f0f4f5;white-space:nowrap}
 .pp td.n{text-align:right;font-variant-numeric:tabular-nums}.pp td.nul{color:#a7b5bb;font-style:italic}
 .pp td.rn{color:#9aabb2;text-align:right;background:#fafcfc}
 .pp .form{display:grid;gap:8px}
 .pp .f{display:grid;gap:4px;font-weight:800;font-size:12px;color:#17384e}.pp .f small{font-weight:600;color:#6b7f88}
 .pp .sel-box{height:32px;border:1px solid #c8d6dc;border-radius:8px;padding:0 10px;display:flex;align-items:center;background:#fff;font-weight:600;color:#22414c;justify-content:space-between}
 .pp .sel-box::after{content:'▾';color:#7b8f97}
 .pp .chips{display:flex;gap:5px;flex-wrap:wrap}
 .pp .chip{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:999px;border:1px solid #d3e0e5;background:#fff;font-size:11.5px;color:#2f4a55;white-space:nowrap}
 .pp .chip.on{background:#0b6577;border-color:#0b6577;color:#fff;font-weight:800}
 .pp .chip.key{background:#f1eaf9;border-color:#d9c9ef;color:#5c3f96;font-weight:800}
 .pp .addgrid{display:grid;gap:4px}
 .pp .add{display:grid;grid-template-columns:26px minmax(0,1fr);gap:8px;align-items:center;padding:6px 8px;border-radius:8px;border:1px solid #e3ebee;background:#fbfdfd}
 .pp .add .ic{width:26px;height:26px;border-radius:7px;display:grid;place-items:center;background:#e6f4f6;color:#0b6577;font-weight:900}
 .pp .add b{display:block;font-weight:800;color:#17384e}.pp .add small{display:block;color:#6b7f88;font-size:11px}
 .pp .flow{display:flex;align-items:stretch;gap:0;flex-wrap:nowrap;overflow:auto;padding-bottom:2px}
 .pp .node{border:1px solid #dce6ea;background:#fff;border-radius:10px;padding:7px 12px;display:grid;gap:2px;min-width:132px}
 .pp .node b{color:#17384e;font-weight:800}.pp .node small{color:#6b7f88}
 .pp .node.on{border-color:#0b6577;box-shadow:0 0 0 2px #cfe9ee;background:#f2fafb}.pp .node.io{background:#f6f9fa}.pp .node.out{background:#e9f6ef;border-color:#b9e0cc}
 .pp .node.addn{border-style:dashed;color:#0b6577;font-weight:800;display:flex;align-items:center;justify-content:center;min-width:120px}
 .pp .arr{display:grid;place-items:center;color:#9aabb2;font-weight:900;padding:0 6px}
 .pp .big{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
 .pp .bigc{border:1px solid #dce6ea;border-radius:12px;background:#fff;padding:12px;display:grid;gap:8px;align-content:start}
 .pp .bigc b{font-size:13.5px;color:#17384e}.pp .bigc small{color:#6b7f88}
 .pp .bigc.on{border-color:#0b6577;box-shadow:0 0 0 2px #cfe9ee}
 .pp .mini{display:flex;align-items:center;gap:6px}.pp .mini table{font-size:10px;min-width:0}.pp .mini td,.pp .mini th{padding:1px 4px}
 .pp .empty{border:1.5px dashed #c8d6dc;border-radius:12px;padding:22px;display:grid;gap:10px;place-items:center;text-align:center;color:#4b6670;background:#fbfdfd}
 .pp .empty b{font-size:14px;color:#17384e}
 .pp .sug{border:1px solid #f2d79a;background:#fffaf0;border-radius:12px;padding:12px 14px;display:grid;gap:8px}
 .pp .sug b{color:#7a4d06;font-size:13.5px}
 .pp .tbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:7px 10px;border-radius:9px;background:#0b6577;color:#fff}
 .pp .tbar .btn{height:28px;font-size:12px;border-color:#5fa5b2;background:#0f7487;color:#fff}.pp .tbar .btn.on{background:#fff;color:#0b6577}
 .pp .crumb{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
 .pp .io3{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.8fr) minmax(0,1fr);gap:14px}
 .pp .pqx{display:grid;grid-template-columns:200px minmax(0,1fr) 250px;gap:10px;min-height:0}
 .pp .fx{font-family:Consolas,monospace;font-size:12px;border:1px solid #dce6ea;border-radius:8px;padding:6px 10px;background:#fbfcfd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .pp .fx i{font-style:italic;color:#0b6577;font-weight:800;margin-right:8px}
 .pp .stat{display:flex;justify-content:space-between;padding:5px 10px;border-radius:7px;background:#0b6577;color:#fff;font-weight:800;font-size:11.5px}
 .pp .warnline{color:#8a5a0c;background:#fff4dc;border-radius:8px;padding:6px 10px;font-weight:700}

 .pp{--pph:330px}
 @media (max-height:900px){.pp{--pph:232px}}
 .pp .tblv{max-height:var(--pph)}
 .pp .stline{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
 .pp .state{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;font-weight:800;font-size:12px}
 .pp .state.off{background:#eef3f5;color:#4a6270}.pp .state.on{background:#e2f4ec;color:#087a57}
 .pp .state::before{content:'';width:8px;height:8px;border-radius:50%;background:currentColor}
 .pp .textbtn{color:#a12d1a;font-weight:800;text-decoration:underline;text-underline-offset:3px}
 .pp .fl2{display:flex;align-items:stretch;gap:0;min-width:0}
 .pp .fl2 .node{min-width:0;flex:1 1 0}.pp .fl2 .node.io,.pp .fl2 .node.out{flex:0 0 auto;min-width:118px}
 .pp .fl2 .node small{white-space:normal;line-height:1.35}
 .pp .fl2 .node .k{display:flex;gap:6px;align-items:center}.pp .fl2 .node .k i{font-style:normal;width:20px;height:20px;border-radius:6px;display:grid;place-items:center;background:#e6f4f6;color:#0b6577;font-size:11px;font-weight:900}
 .pp .fl2 .node.on .k i{background:#0b6577;color:#fff}
 .pp .fl2 .node em{font-style:normal;font-size:11px;color:#8a5a0c}
 .pp .pal{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
 .pp .pal>b{font-size:12px;color:#17384e;margin-right:2px}
 .pp .palb{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 11px 0 6px;border-radius:8px;border:1px solid #c8d6dc;background:#fff;font-weight:800;color:#17384e;white-space:nowrap}
 .pp .palb span{width:20px;height:20px;border-radius:5px;display:grid;place-items:center;background:#e6f4f6;color:#0b6577;font-size:11px}
 .pp .palb.main{border-color:#0b6577}
 .pp .form2{display:grid;gap:8px}
 .pp .form2 .h{display:grid;gap:2px}.pp .form2 .h b{font-size:13px;color:#17384e;white-space:nowrap}.pp .form2 .h small{color:#6b7f88}
 .pp .info{border:1px solid #b9dde5;background:#f0f8fa;border-radius:10px;padding:10px 12px;display:grid;gap:6px}
 .pp .info b{color:#0b4f5c;font-size:13px}
 .pp .dcard{border:1px solid #dce6ea;border-radius:10px;background:#fff;padding:8px 10px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 10px;align-items:center}
 .pp .dcard b{color:#17384e;font-size:12.5px}.pp .dcard small{color:#6b7f88;font-size:11px;grid-column:2}
 .pp .dcard .mini{grid-row:span 2}
 .pp .pstep2{display:grid;grid-template-columns:20px 24px minmax(0,1fr) auto;gap:6px;align-items:start;padding:6px 8px;border-radius:8px;border:1px solid transparent}
 .pp .pstep2 .ic{width:24px;height:24px;border-radius:6px;display:grid;place-items:center;background:#eef4f6;color:#0b6577;font-weight:900;font-size:12px}
 .pp .pstep2 i{font-style:normal;font-size:11px;color:#7b8f97;text-align:right;padding-top:4px}
 .pp .pstep2 b{display:block;font-weight:800;color:#17384e}.pp .pstep2 small{display:block;color:#6b7f88;line-height:1.35}
 .pp .pstep2.on{background:#e6f4f6;border-color:#9fd1d9}.pp .pstep2.src .ic{background:#f1eaf9;color:#5c3f96}
 .pp .pstep2 .x{color:#9aabb2;font-weight:900;padding-top:4px}
 .pp .tb{display:flex;align-items:center;gap:8px;flex-wrap:wrap}

 .pp.fill{display:grid;grid-template-rows:auto auto auto minmax(0,1fr);height:var(--pp-h,560px)}
 .pp.fill.r5{grid-template-rows:auto auto auto auto minmax(0,1fr)}
 .pp .grow{display:grid;grid-template-rows:minmax(0,1fr) auto;min-height:0;overflow:hidden}
 .pp .grow .tbl{max-height:none;min-height:0;border-radius:9px 9px 0 0}
 .pp .grow .stat{border-radius:0 0 8px 8px}
 .pp .fl3{display:grid;grid-template-columns:minmax(0,.8fr) 18px minmax(0,1.25fr) 18px minmax(0,1.25fr) 18px minmax(0,1fr) 18px minmax(0,.8fr);align-items:stretch}
 .pp .fl3 .arr{padding:0}
 .pp .fl3 .node{min-width:0}.pp .fl3 .node small{white-space:normal;line-height:1.35}
 .pp .fl3 .node .k{display:flex;gap:6px;align-items:center}.pp .fl3 .node .k i{font-style:normal;width:20px;height:20px;border-radius:6px;display:grid;place-items:center;background:#e6f4f6;color:#0b6577;font-size:11px;font-weight:900}
 .pp .fl3 .node.on .k i{background:#0b6577;color:#fff}.pp .fl3 .node em{font-style:normal;font-size:11px;color:#8a5a0c}
 .pp .node.next{border:1.5px dashed #0b6577;background:#f2fafb;display:grid;gap:3px;align-content:center}
 .pp .node.next b{color:#0b6577}.pp .node.next .btn{justify-self:start}
 .pp .palb .rec{font-style:normal;font-size:10px;font-weight:900;color:#fff;background:#0b6577;border-radius:4px;padding:0 4px;width:auto;height:auto;margin-left:2px}
 .pp .palb.recd{border-color:#0b6577;box-shadow:0 0 0 2px #cfe9ee;background:#f2fafb}
 .pp .hint1{display:flex;align-items:center;gap:8px;color:#0b4f5c;font-weight:700}
 .eb-post{background:#fdeef3;color:#9a2f5a}
 `;
 let data = null;
 function style() { if (!document.getElementById('pp-style')) { const s = document.createElement('style'); s.id = 'pp-style'; s.textContent = CSS; document.head.appendChild(s) } }
 async function prev(steps, step) {
  return fetch('/api/post/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: 'J1', post: { enabled: true, steps }, step }) }).then(r => r.json())
 }
 async function load() {
  if (data) return data;
  const [inp, s1, out] = await Promise.all([prev([]), prev(STEPS, 0), prev(STEPS)]);
  data = { inp, s1, out };
  return data;
 }
 function table(d, rows, opts = {}) {
  const cols = d.columns || [];
  const fresh = new Set(opts.fresh || []), sel = new Set(opts.sel || []);
  const head = cols.map(c => `<th class="${fresh.has(c.name) ? 'new' : ''}${sel.has(c.name) ? ' sel' : ''}">${opts.check ? `<input type="checkbox"${sel.has(c.name) ? ' checked' : ''}>` : ''}<em>${c.out === 'text' ? 'ABC' : '123'}</em>${E(c.name)}</th>`).join('');
  const body = (d.rows || []).slice(0, rows).map((r, i) => `<tr>${opts.rn ? `<td class="rn">${i + 1}</td>` : ''}${r.map((v, k) => v === null ? '<td class="nul">null</td>' : `<td class="${typeof v === 'number' ? 'n' : ''}">${E(v)}</td>`).join('')}</tr>`).join('');
  return `<div class="tbl" style="max-height:${opts.h || 300}px"><table><thead><tr>${opts.rn ? '<th></th>' : ''}${head}</tr></thead><tbody>${body}</tbody></table></div>`
 }
 const sz = d => `${d.row_count}行 × ${(d.columns || []).length}列`;
 function stepList(on, opts = {}) {
  const items = [`<div class="pstep src"><i></i><span class="ic">▤</span><span><b>取り出した表</b><small>${sz(data.inp)} · 前回の実行の見本</small></span><span></span></div>`,
   `<div class="pstep${on === 0 ? ' on' : ''}"><i>1</i><span class="ic">⇣</span><span><b>ピボット解除</b><small>品番・品名・工程 以外を縦に（月・数量）</small></span><span class="x">${opts.x === false ? '' : '×'}</span></div>`,
   `<div class="pstep${on === 1 ? ' on' : ''}"><i>2</i><span class="ic">⇢</span><span><b>ピボット</b><small>工程 を見出しに・数量 の合計</small></span><span class="x">${opts.x === false ? '' : '×'}</span></div>`];
  return `<div class="psteps">${items.join('')}</div>`
 }
 const MODE = (k = 1) => `<div class="seg"><span${k === 0 ? ' class="on"' : ''}>後処理をしない</span><span${k === 1 ? ' class="on"' : ''}>手順で組む</span><span${k === 2 ? ' class="on"' : ''}>クエリを使う</span></div>`;
 function pivotForm(compact) {
  return `<div class="form">
  <div class="cap">2 · ピボット <small>1つの列の値を見出しにして横に並べ、値の列を集計します</small></div>
  <div style="display:grid;grid-template-columns:${compact ? '1fr' : 'repeat(3,minmax(0,1fr))'};gap:8px">
  <label class="f">見出しにする列<span class="sel-box">工程</span><small>切削・組立・検査 の3列になります</small></label>
  <label class="f">値の列<span class="sel-box">数量</span></label>
  <label class="f">集計<span class="sel-box">合計</span><small>文字の数（1,200 など）も数に直して合計</small></label></div></div>`
 }
 function addList(col) {
  return `<div class="addgrid" style="grid-template-columns:${col || '1fr'}">${OPS.map(o => `<div class="add"><span class="ic">${o[3]}</span><span><b>${o[1]}</b><small>${o[2]}</small></span></div>`).join('')}</div>`
 }
 const RESULT = () => `<div class="row"><span class="pill">取り出した表 ${sz(data.inp)}</span><span class="note">→</span><span class="pill ok">出す表 ${sz(data.out)}</span><span class="note">見本は前回の実行で取り出した表（2026-10-24 06:35）の ${data.out.input.rows}行</span></div>`;
 const EMPTY_LEAD = '取り出した表を、ファイルに出す前に整えます（Excel の Power Query と同じ）。横に並んだ月を縦にする・値を見出しにして横に並べる・まとめて合計する、など。';


 // ---- 2回目の部品（1回目の減点を埋める: 見出しが折り返さない・説明を切らない・空のときの状態・行数の理由・フル HD の高さ）
 const tableV = (d, rows, opts = {}) => table(d, rows, opts).replace('class="tbl" style="max-height:' + (opts.h || 300) + 'px"', 'class="tbl tblv"');
 const dropped = () => data.inp.row_count * ((data.inp.columns || []).length - 3) - data.s1.row_count;
 const MODE2 = view => view === 2
  ? `<div class="stline"><span class="state off">後処理なし · 取り出した表のまま出します</span><span class="note">下の手順を1つ足すと、後処理が入ります</span><span class="sp"></span><span class="seg"><span class="on">手順で組む</span><span>クエリを使う</span></span></div>`
  : `<div class="stline"><span class="state on">後処理あり · 手順 2</span>${RESULT()}<span class="sp"></span><span class="seg"><span class="on">手順で組む</span><span>クエリを使う</span></span></div>`;
 const flow2 = on => `<div class="fl2"><div class="node io"><b>取り出した表</b><small>${sz(data.inp)}</small></div><span class="arr">→</span>
  <div class="node${on === 0 ? ' on' : ''}"><span class="k"><i>1</i><b>ピボット解除</b></span><small>品番・品名・工程 以外を縦に（月・数量）</small><small>${sz(data.s1)} <em>空のセル ${dropped()}件は出さない</em></small></div><span class="arr">→</span>
  <div class="node${on === 1 ? ' on' : ''}"><span class="k"><i>2</i><b>ピボット</b></span><small>工程 を見出しに · 数量 の合計</small><small>${sz(data.out)}</small></div><span class="arr">→</span>
  <div class="node out"><b>出す表</b><small>${sz(data.out)}</small></div></div>`;
 const flow2empty = () => `<div class="fl2"><div class="node io"><b>取り出した表</b><small>${sz(data.inp)}</small></div><span class="arr">→</span><div class="node addn">手順はまだありません</div><span class="arr">→</span><div class="node out"><b>出す表</b><small>取り出した表のまま</small></div></div>`;
 const pal = (label = '手順を足す') => `<div class="pal"><b>${label}</b>${OPS.map((o, i) => `<span class="palb${i < 3 ? ' main' : ''}"><span>${o[3]}</span>${o[1]}</span>`).join('')}</div>`;
 function pivotForm2(cols = 3) {
  return `<div class="form2"><div class="h"><b>2 · ピボット</b><small>1つの列の値を見出しにして横に並べ、値の列を集計します</small></div>
  <div style="display:grid;grid-template-columns:repeat(${cols},minmax(0,1fr));gap:8px">
  <label class="f">見出しにする列<span class="sel-box">工程</span><small>切削・組立・検査 の3列になります</small></label>
  <label class="f">値の列<span class="sel-box">数量</span></label>
  <label class="f">集計<span class="sel-box">合計</span><small>1,200 のような文字も数にして合計</small></label></div>
  <div class="row"><span class="sp"></span><span class="btn sm">この手順を消す</span></div></div>`
 }
 const SUG = () => `<div class="info"><b>4月〜9月 の6列は、月が横に並んでいるようです。縦に（ピボット解除）しますか？</b>
  <span class="note">品番・品名・工程 はそのまま残し、「月」「数量」の2列にします（${sz(data.inp)} → ${sz(data.s1)}。空のセル ${dropped()}件は出しません）。</span>
  <div class="row"><span class="btn pri">縦にする</span><span class="btn">ほかの手順を選ぶ</span></div></div>`;
 function steps2(on) {
  return `<div class="psteps"><div class="pstep2 src"><i></i><span class="ic">▤</span><span><b>取り出した表</b><small>${sz(data.inp)} · 前回の実行の見本</small></span><span></span></div>
  <div class="pstep2${on === 0 ? ' on' : ''}"><i>1</i><span class="ic">⇣</span><span><b>ピボット解除</b><small>品番・品名・工程 以外を縦に（月・数量）<br>${sz(data.s1)} · 空のセル ${dropped()}件は出さない</small></span><span class="x">×</span></div>
  <div class="pstep2${on === 1 ? ' on' : ''}"><i>2</i><span class="ic">⇢</span><span><b>ピボット</b><small>工程 を見出しに · 数量 の合計<br>${sz(data.out)}</small></span><span class="x">×</span></div></div>`
 }
 const MINI = {
  unpivot: ['横に並んだ列を縦に', 'ピボット解除', [['品番', '4月', '5月'], [['A', 3, 5]]], [['品番', '月', '値'], [['A', '4月', 3], ['A', '5月', 5]]]],
  pivot: ['値を見出しにして横に', 'ピボット', [['品番', '工程', '値'], [['A', '切削', 3], ['A', '組立', 5]]], [['品番', '切削', '組立'], [['A', 3, 5]]]],
  group: ['まとめて合計・件数', 'グループ化', [['品番', '値'], [['A', 3], ['A', 5]]], [['品番', '合計'], [['A', 8]]]],
 };
 const mt = ([h, r]) => `<table><tr>${h.map(x => `<th>${x}</th>`).join('')}</tr>${r.map(x => `<tr>${x.map(y => `<td>${y}</td>`).join('')}</tr>`).join('')}</table>`;
 const dcards = () => `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) minmax(0,.9fr);gap:8px">${Object.values(MINI).map(m => `<div class="dcard"><div class="mini">${mt(m[2])}<span class="arr">→</span>${mt(m[3])}</div><b>${m[0]}</b><small>${m[1]}</small></div>`).join('')}
  <div class="dcard" style="grid-template-columns:1fr"><b>列を整える</b><div class="pal">${OPS.slice(3).map(o => `<span class="palb" style="height:24px;font-size:11.5px"><span>${o[3]}</span>${o[1]}</span>`).join('')}</div></div></div>`;


 // ---- 3回目の部品（2回目の減点を埋める: 表は残りの高さいっぱい＋下に帯で終わりを示す・骨組みを2つの場面でそろえる・次の候補・ボタンの形をそろえる・札の幅）
 const tableG = (d, rows, opts, foot) => `<div class="grow">${table(d, rows, opts).replace(/style="max-height:\d+px"/, '')}<div class="stat"><span>${foot}</span><span>見本は前回の実行で取り出した表（${data.inp.row_count}行）</span></div></div>`;
 const ACT = () => `<span class="btn sm">式を見る</span><span class="btn sm">クエリとして保存</span>`;
 const flow3 = (on, next) => `<div class="fl3"><div class="node io"><b>取り出した表</b><small>${sz(data.inp)}</small></div><span class="arr">→</span>
  <div class="node${on === 0 ? ' on' : ''}"><span class="k"><i>1</i><b>ピボット解除</b></span><small>品番・品名・工程 以外を縦に（月・数量）</small><small>${sz(data.s1)} <em>空のセル ${dropped()}件は出さない</em></small></div><span class="arr">→</span>
  <div class="node${on === 1 ? ' on' : ''}"><span class="k"><i>2</i><b>ピボット</b></span><small>工程 を見出しに · 数量 の合計</small><small>${sz(data.out)}</small></div><span class="arr">→</span>
  ${next ? `<div class="node next"><b>次の候補: グループ化</b><small>品番・月 ごとに合計</small><span class="btn sm">足す</span></div>` : `<div class="node addn">＋ 下から足す</div>`}<span class="arr">→</span>
  <div class="node out"><b>出す表</b><small>${sz(data.out)}</small></div></div>`;
 const flow3empty = next => `<div class="fl3"><div class="node io"><b>取り出した表</b><small>${sz(data.inp)}</small></div><span class="arr">→</span>
  ${next ? `<div class="node next" style="grid-column:span 5"><b>おすすめ: ピボット解除（4月〜9月 の6列を縦に）</b><small>月が横に並んでいるようです。品番・品名・工程 は残し「月」「数量」の2列に（→ ${sz(data.s1)}。空のセル ${dropped()}件は出さない）</small><span class="btn sm pri">縦にする</span></div>`
   : `<div class="node addn" style="grid-column:span 5">手順はまだありません（下の「手順を足す」から選びます）</div>`}<span class="arr">→</span>
  <div class="node out"><b>出す表</b><small>取り出した表のまま</small></div></div>`;
 const pal3 = rec => `<div class="pal"><b>手順を足す</b>${OPS.map((o, i) => `<span class="palb${i < 3 ? ' main' : ''}${rec === o[0] ? ' recd' : ''}"><span>${o[3]}</span>${o[1]}${rec === o[0] ? '<i class="rec">おすすめ</i>' : ''}</span>`).join('')}</div>`;
 function pivotRow() {
  return `<div class="card" style="grid-template-columns:auto repeat(3,minmax(0,1fr)) auto;align-items:end;gap:10px">
  <div class="form2"><div class="h"><b>2 · ピボット</b><small>値を見出しにして横へ</small></div></div>
  <label class="f">見出しにする列<span class="sel-box">工程</span></label><label class="f">値の列<span class="sel-box">数量</span></label><label class="f">集計<span class="sel-box">合計</span></label>
  <span class="btn sm">この手順を消す</span></div>`
 }

 // ---- 案 --------------------------------------------------------------------------
 const P = {
  // A: タブ「後処理」＋ Power Query エディターと同じ3列（左に手順を足す・中に表・右に適用したステップと選んだ手順の設定）
  A(view) {
   if (view === 2) return `<div class="pp"><div class="row">${MODE(0)}<span class="note">${EMPTY_LEAD}</span></div>
    <div style="display:grid;grid-template-columns:220px minmax(0,1fr) 280px;gap:10px">
    <div class="card"><div class="cap">手順を足す</div>${addList()}</div>
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${table(data.inp, 14, { h: 420 })}</div>
    <div class="card"><div class="cap">適用したステップ</div><p class="note">まだありません。左の「手順を足す」から選ぶと、ここに並び、真ん中の表が変わります。</p></div></div></div>`;
   return `<div class="pp"><div class="row">${MODE(1)}<span class="sp"></span>${RESULT()}</div>
    <div style="display:grid;grid-template-columns:220px minmax(0,1fr) 300px;gap:10px">
    <div class="card"><div class="cap">手順を足す</div>${addList()}</div>
    <div class="card"><div class="cap">2 · ピボット のあと <small>${sz(data.out)}</small></div>${table(data.out, 14, { h: 420, fresh: ['切削', '組立', '検査'] })}</div>
    <div class="card"><div class="cap">適用したステップ</div>${stepList(1)}<hr style="border:0;border-top:1px solid #edf1f2;margin:2px 0">${pivotForm(true)}<div class="row"><span class="btn sm">クエリとして保存</span><span class="btn sm ghost">式を見る</span></div></div></div></div>`
  },
  // B: 上に流れ（取り出した表 → 手順 → 出す表）、下に選んだ手順の設定と表
  B(view) {
   if (view === 2) return `<div class="pp"><div class="row">${MODE(0)}<span class="note">${EMPTY_LEAD}</span></div>
    <div class="flow"><div class="node io"><b>取り出した表</b><small>${sz(data.inp)}</small></div><span class="arr">→</span><div class="node addn">＋ 手順を足す</div><span class="arr">→</span><div class="node out"><b>出す表</b><small>そのまま</small></div></div>
    <div class="card"><div class="cap">取り出した表 <small>前回の実行の見本</small></div>${table(data.inp, 14, { h: 400 })}</div></div>`;
   return `<div class="pp"><div class="row">${MODE(1)}<span class="sp"></span><span class="btn sm">クエリとして保存</span><span class="btn sm ghost">式を見る</span></div>
    <div class="flow"><div class="node io"><b>取り出した表</b><small>${sz(data.inp)}</small></div><span class="arr">→</span>
    <div class="node"><b>1 ピボット解除</b><small>月・数量 の縦に · ${sz(data.s1)}</small></div><span class="arr">→</span>
    <div class="node on"><b>2 ピボット</b><small>工程 を見出しに · 合計</small></div><span class="arr">→</span>
    <div class="node addn">＋ 手順を足す</div><span class="arr">→</span><div class="node out"><b>出す表</b><small>${sz(data.out)}</small></div></div>
    <div style="display:grid;grid-template-columns:330px minmax(0,1fr);gap:10px"><div class="card">${pivotForm(true)}<div class="row"><span class="btn sm">この手順を消す</span></div></div>
    <div class="card"><div class="cap">2 のあとの表 <small>${sz(data.out)}</small></div>${table(data.out, 12, { h: 340, fresh: ['切削', '組立', '検査'] })}</div></div></div>`
  },
  // C: 前後の表を左右に並べ、あいだに手順の列
  C(view) {
   if (view === 2) return `<div class="pp"><div class="row">${MODE(0)}<span class="note">${EMPTY_LEAD}</span></div>
    <div style="display:grid;grid-template-columns:minmax(0,1fr) 250px minmax(0,1fr);gap:10px">
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)}</small></div>${table(data.inp, 14, { h: 420 })}</div>
    <div class="card"><div class="cap">手順</div><div class="empty" style="padding:14px"><b>手順はまだありません</b><span class="btn pri sm">＋ 手順を足す</span></div></div>
    <div class="card"><div class="cap">出す表 <small>いまは取り出した表のまま</small></div>${table(data.inp, 14, { h: 420 })}</div></div></div>`;
   return `<div class="pp"><div class="row">${MODE(1)}<span class="sp"></span>${RESULT()}</div>
    <div style="display:grid;grid-template-columns:minmax(0,1fr) 270px minmax(0,1fr);gap:10px">
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)}</small></div>${table(data.inp, 14, { h: 420 })}</div>
    <div class="card"><div class="cap">手順</div>${stepList(1)}${pivotForm(true)}<span class="btn sm">＋ 手順を足す</span></div>
    <div class="card"><div class="cap">出す表 <small>${sz(data.out)}</small></div>${table(data.out, 14, { h: 420, fresh: ['切削', '組立', '検査'] })}</div></div></div>`
  },
  // D: やりたいことを図で選ぶ（横→縦・縦→横・まとめる・列を整える）
  D(view) {
   const mini = (a, b) => `<div class="mini">${a}<span class="arr">→</span>${b}</div>`;
   const t = (h, r) => `<table><tr>${h.map(x => `<th>${x}</th>`).join('')}</tr>${r.map(x => `<tr>${x.map(y => `<td>${y}</td>`).join('')}</tr>`).join('')}</table>`;
   const cards = (on) => `<div class="big">
    <div class="bigc${on === 0 ? ' on' : ''}"><b>横に並んだ列を縦に</b><small>ピボット解除</small>${mini(t(['品番', '4月', '5月'], [['A', 3, 5]]), t(['品番', '月', '値'], [['A', '4月', 3], ['A', '5月', 5]]))}</div>
    <div class="bigc${on === 1 ? ' on' : ''}"><b>値を見出しにして横に</b><small>ピボット</small>${mini(t(['品番', '工程', '値'], [['A', '切削', 3], ['A', '組立', 5]]), t(['品番', '切削', '組立'], [['A', 3, 5]]))}</div>
    <div class="bigc"><b>まとめて合計・件数</b><small>グループ化</small>${mini(t(['品番', '値'], [['A', 3], ['A', 5]]), t(['品番', '合計'], [['A', 8]]))}</div>
    <div class="bigc"><b>列を整える</b><small>列の選択・名前の変更・並べ替え・M の式</small><div class="chips"><span class="chip">列の選択</span><span class="chip">名前の変更</span><span class="chip">並べ替え</span><span class="chip">M の式</span></div></div></div>`;
   if (view === 2) return `<div class="pp"><div class="row">${MODE(0)}<span class="note">${EMPTY_LEAD}</span></div><div class="cap">何をしますか</div>${cards(-1)}
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${table(data.inp, 8, { h: 260 })}</div></div>`;
   return `<div class="pp"><div class="row">${MODE(1)}<span class="sp"></span>${RESULT()}</div><div class="cap">次に何をしますか</div>${cards(1)}
    <div style="display:grid;grid-template-columns:300px minmax(0,1fr);gap:10px"><div class="card"><div class="cap">手順</div>${stepList(1)}${pivotForm(true)}</div>
    <div class="card"><div class="cap">出す表 <small>${sz(data.out)}</small></div>${table(data.out, 9, { h: 290, fresh: ['切削', '組立', '検査'] })}</div></div></div>`
  },
  // E: タブは増やさない。基本と入出力に「入力 → 整える → 出力」の3段。整え方は Power Query エディターと同じ全画面の窓で
  E(view) {
   if (view === 2) return 'basic';
   return `<div class="pp" style="height:100%"><div class="row" style="border-bottom:1px solid #e3ebee;padding-bottom:8px"><b style="font-size:13px;color:#17384e">後処理の編集</b><span class="note">月別実績（縦持ち）</span>${MODE(1)}<span class="sp"></span><span class="btn">クエリとして保存</span><span class="btn">保存せずに閉じる</span><span class="btn pri">閉じて保存</span></div>
    <div class="pqx"><div class="card"><div class="cap">手順を足す</div>${addList()}</div>
    <div class="card" style="grid-template-rows:auto auto minmax(0,1fr) auto"><div class="fx"><i>fx</i>Table.Pivot(見出し, List.Distinct(見出し[工程]), "工程", "数量", List.Sum)</div>${pivotForm(false)}${table(data.out, 16, { h: 430, rn: true, fresh: ['切削', '組立', '検査'] })}<div class="stat"><span>${sz(data.out)}（見本 ${data.out.input.rows}行から）</span><span>取り出した表 ${sz(data.inp)}</span></div></div>
    <div class="card"><div class="cap">適用したステップ</div>${stepList(1)}</div></div></div>`
  },
  // F（方向が違う）: 表の見出しを直接選んで操作する。手順は上のパンくず
  F(view) {
   if (view === 2) return `<div class="pp"><div class="row">${MODE(0)}<span class="note">表の見出しを選ぶと、その列でできることが上に出ます</span></div>
    <div class="tbar"><b>選んだ列 3</b><span class="btn on">選んだ列以外を縦に（ピボット解除）</span><span class="btn">選んだ列を縦に</span><span class="btn">グループ化のキーに</span><span class="btn">残す</span><span class="btn">名前を変える</span></div>
    ${table(data.inp, 14, { h: 430, check: true, sel: ['品番', '品名', '工程'] })}</div>`;
   return `<div class="pp"><div class="row">${MODE(1)}<div class="crumb"><span class="chip key">取り出した表</span>›<span class="chip">1 ピボット解除</span>›<span class="chip on">2 ピボット</span></div><span class="sp"></span>${RESULT()}</div>
    <div class="tbar"><b>2 · ピボット</b><span>見出しにする列 <u>工程</u> · 値の列 <u>数量</u> · 集計 <u>合計</u></span><span class="sp"></span><span class="btn">直す</span><span class="btn">この手順を消す</span></div>
    ${table(data.out, 14, { h: 430, check: true, fresh: ['切削', '組立', '検査'] })}</div>`
  },
  // G（方向が違う）: 見本から形を見抜いて「こうしますか」を1押しで。細かい手順は畳んでおく
  G(view) {
   if (view === 2) return `<div class="pp"><div class="row">${MODE(0)}<span class="note">${EMPTY_LEAD}</span></div>
    <div class="sug"><b>4月〜9月 の6列は、月が横に並んでいるようです。縦に（ピボット解除）しますか？</b>
    <span class="note">品番・品名・工程 はそのまま残し、「月」「数量」の2列にします（24行 → 約${data.s1.row_count}行）。</span>
    <div class="row"><span class="btn pri">縦にする</span><span class="btn">細かく組む</span><span class="btn ghost">このままでよい</span></div></div>
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${table(data.inp, 12, { h: 380 })}</div></div>`;
   return `<div class="pp"><div class="row">${MODE(1)}<span class="sp"></span>${RESULT()}</div>
    <div class="card"><div class="cap">組んだ後処理 <small>ピボット解除 → ピボット</small><span class="sp"></span><span class="btn sm">細かく組む ▾</span></div>
    <div class="note">① 4月〜9月 を縦に（月・数量）　② 工程 を見出しに横へ（数量の合計）</div></div>
    <div class="sug"><b>次の候補: 「工程」の列が 切削・組立・検査 の3つの値です。見出しにして横に並べますか？</b><div class="row"><span class="btn pri">済み（②）</span><span class="btn ghost">ほかの候補</span></div></div>
    <div class="card"><div class="cap">出す表 <small>${sz(data.out)}</small></div>${table(data.out, 11, { h: 330, fresh: ['切削', '組立', '検査'] })}</div></div>`
  },
  // H（組合せ）: B の流れ ＋ A の「手順の候補がいつも見える」＋ G の提案（空のとき）。空のときの状態は「後処理なし」と言い切る
  H(view) {
   if (view === 2) return `<div class="pp">${MODE2(2)}${flow2empty()}${SUG()}${pal()}
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${tableV(data.inp, 12)}</div></div>`;
   return `<div class="pp">${MODE2(1)}${flow2(1)}${pal()}
    <div style="display:grid;grid-template-columns:340px minmax(0,1fr);gap:10px"><div class="card">${pivotForm2(1)}</div>
    <div class="card"><div class="cap">2 のあとの表 = 出す表 <small>${sz(data.out)}</small><span class="sp"></span><span class="btn sm ghost">式を見る</span><span class="btn sm">クエリとして保存</span></div>${tableV(data.out, 12, { fresh: ['切削', '組立', '検査'] })}</div></div></div>`
  },
  // I（組合せ）: A の Power Query エディターと同じ3列を詰め直す（右の欄を広げ、手順の説明を切らない・設定の見出しを1行に）＋ G の提案（空のとき）
  I(view) {
   const head = `<div class="tb">${MODE2(view)}</div>`;
   if (view === 2) return `<div class="pp">${head}<div style="display:grid;grid-template-columns:200px minmax(0,1fr) 330px;gap:10px">
    <div class="card"><div class="cap">手順を足す</div>${addList()}</div>
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${tableV(data.inp, 12)}</div>
    <div class="card"><div class="cap">適用したステップ</div><p class="note">まだありません。左から選ぶと、ここに並び、真ん中の表が変わります。</p>${SUG()}</div></div></div>`;
   return `<div class="pp">${head}<div style="display:grid;grid-template-columns:200px minmax(0,1fr) 330px;gap:10px">
    <div class="card"><div class="cap">手順を足す</div>${addList()}</div>
    <div class="card"><div class="cap">2 · ピボット のあと = 出す表 <small>${sz(data.out)}</small><span class="sp"></span><span class="btn sm ghost">式を見る</span><span class="btn sm">クエリとして保存</span></div>${tableV(data.out, 12, { fresh: ['切削', '組立', '検査'] })}</div>
    <div class="card"><div class="cap">適用したステップ</div>${steps2(1)}<hr style="border:0;border-top:1px solid #edf1f2;margin:2px 0">${pivotForm2(1)}</div></div></div>`
  },
  // J（組合せ）: G の「見本から提案して1押し」を主に、組んだあとは B の流れで見せる（文だけの要約にしない）。手順の候補は流れの下にいつも出す
  J(view) {
   if (view === 2) return `<div class="pp">${MODE2(2)}${SUG()}${pal('自分で選ぶ')}
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${tableV(data.inp, 12)}</div></div>`;
   return `<div class="pp">${MODE2(1)}${flow2(1)}
    <div class="info" style="grid-template-columns:minmax(0,1fr) auto;align-items:center"><span><b>次の手順の候補</b><span class="note">「月」ごとの合計が要るなら、グループ化（品番・月 ごとに 切削・組立・検査 の合計）を足せます。</span></span><span class="btn sm">グループ化を足す</span></div>
    ${pal()}<div style="display:grid;grid-template-columns:330px minmax(0,1fr);gap:10px"><div class="card">${pivotForm2(1)}</div>
    <div class="card"><div class="cap">出す表 <small>${sz(data.out)}</small><span class="sp"></span><span class="btn sm">クエリとして保存</span></div>${tableV(data.out, 9, { fresh: ['切削', '組立', '検査'] })}</div></div></div>`
  },
  // K（組合せ）: B の流れ ＋ D の図（変換の前後のミニ表）を「手順を足す」に。図は低く1段に収め、設定と表を押し下げない
  K(view) {
   if (view === 2) return `<div class="pp">${MODE2(2)}${flow2empty()}<div class="cap">手順を足す <small>図の形に整えます</small></div>${dcards()}
    <div class="card"><div class="cap">取り出した表 <small>${sz(data.inp)} · 前回の実行の見本</small></div>${tableV(data.inp, 10)}</div></div>`;
   return `<div class="pp">${MODE2(1)}${flow2(1)}<div class="cap">手順を足す</div>${dcards()}
    <div style="display:grid;grid-template-columns:330px minmax(0,1fr);gap:10px"><div class="card">${pivotForm2(1)}</div>
    <div class="card"><div class="cap">出す表 <small>${sz(data.out)}</small><span class="sp"></span><span class="btn sm">クエリとして保存</span></div>${tableV(data.out, 8, { fresh: ['切削', '組立', '検査'] })}</div></div></div>`
  },
  // L（組合せ）: H ＋ J の「次の候補」を流れの中の札に（帯を増やさない）。2つの場面で骨組みをそろえ、表は残りの高さいっぱい
  L(view) {
   if (view === 2) return `<div class="pp fill">${MODE2(2)}${flow3empty(true)}${pal3('unpivot')}
    <div class="card grow0" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">取り出した表 <small>前回の実行の見本</small></div>${tableG(data.inp, 40, {}, sz(data.inp))}</div></div>`;
   return `<div class="pp fill">${MODE2(1)}${flow3(1, true)}${pal3()}
    <div style="display:grid;grid-template-columns:330px minmax(0,1fr);gap:10px;min-height:0"><div class="card">${pivotForm2(1)}</div>
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">2 のあとの表 = 出す表<span class="sp"></span>${ACT()}</div>${tableG(data.out, 60, { fresh: ['切削', '組立', '検査'] }, sz(data.out))}</div></div></div>`
  },
  // M（組合せ）: H の骨組み ＋ 提案は「手順を足す」の中の「おすすめ」印と1行の理由に（帯を出さない）
  M(view) {
   if (view === 2) return `<div class="pp fill r5">${MODE2(2)}${flow3empty(false)}${pal3('unpivot')}<div class="hint1">おすすめ: 4月〜9月 の6列は月が横に並んでいるようです。「ピボット解除」で「月」「数量」の縦にできます。<span class="btn sm pri">縦にする</span></div>
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">取り出した表 <small>前回の実行の見本</small></div>${tableG(data.inp, 40, {}, sz(data.inp))}</div></div>`;
   return `<div class="pp fill r5">${MODE2(1)}${flow3(1, false)}${pal3('group')}<div class="hint1">おすすめ: 「月」ごとの合計が要るなら「グループ化」（品番・月 ごとに 切削・組立・検査 の合計）。<span class="btn sm">グループ化を足す</span></div>
    <div style="display:grid;grid-template-columns:330px minmax(0,1fr);gap:10px;min-height:0"><div class="card">${pivotForm2(1)}</div>
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">2 のあとの表 = 出す表<span class="sp"></span>${ACT()}</div>${tableG(data.out, 60, { fresh: ['切削', '組立', '検査'] }, sz(data.out))}</div></div></div>`
  },
  // N（組合せ）: J の「候補が主」＋ 流れの骨組みを2つの場面でそろえる。選んだ手順の設定は表の上に横1行（表を広く）
  N(view) {
   if (view === 2) return `<div class="pp fill">${MODE2(2)}${flow3empty(true)}${pal3('unpivot')}
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">取り出した表 <small>前回の実行の見本</small></div>${tableG(data.inp, 40, {}, sz(data.inp))}</div></div>`;
   return `<div class="pp fill r5">${MODE2(1)}${flow3(1, true)}${pal3()}${pivotRow()}
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">2 のあとの表 = 出す表<span class="sp"></span>${ACT()}</div>${tableG(data.out, 60, { fresh: ['切削', '組立', '検査'] }, sz(data.out))}</div></div>`
  },
  // O（組合せ）: H の骨組みのまま、設定は表の上に横1行（表を全幅に）。提案は空のときだけ流れの中に
  O(view) {
   if (view === 2) return `<div class="pp fill">${MODE2(2)}${flow3empty(true)}${pal3()}
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">取り出した表 <small>前回の実行の見本</small></div>${tableG(data.inp, 40, {}, sz(data.inp))}</div></div>`;
   return `<div class="pp fill r5">${MODE2(1)}${flow3(1, false)}${pal3()}${pivotRow()}
    <div class="card" style="min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)"><div class="cap">2 のあとの表 = 出す表<span class="sp"></span>${ACT()}</div>${tableG(data.out, 60, { fresh: ['切削', '組立', '検査'] }, sz(data.out))}</div></div>`
  },
 };

 // ---- 本物の画面へ差し込む --------------------------------------------------------------
 function addTab() {
  if (document.querySelector('.editor-tab[data-etab="post"]')) return;
  const after = document.querySelector('.editor-tab[data-etab="variant"]');
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'editor-tab'; b.dataset.etab = 'post'; b.setAttribute('role', 'tab');
  b.innerHTML = '<i class="etab-badge eb-post">?</i><span class="etab-text"><b>後処理</b><small>ピボット・集計で整える</small></span><span class="etab-count">ON</span>';
  after.after(b);
  const pane = document.createElement('div'); pane.className = 'editor-pane'; pane.dataset.etab = 'post';
  document.querySelector('.editor-pane[data-etab="naming"]').before(pane);
  b.onclick = () => setEditorTab('post');
  setSource(currentSource());   // 番号を振り直す
 }
 function basicStage(view) {
  // E: 基本と入出力の入力と出力のあいだに「整える」
  const io = document.querySelector('.io-columns');
  if (!io || io.querySelector('.pp-mid')) return;
  io.style.gridTemplateColumns = 'minmax(0,1fr) minmax(0,.62fr) minmax(0,1fr)';
  const mid = document.createElement('div'); mid.className = 'io-col pp-mid';
  mid.innerHTML = `<div class="sectiontitle"><i class="sect-badge eb-post">整</i>後処理（出す前に整える）</div><div class="pp">${view === 2
   ? `<div class="empty"><b>そのまま出します</b><span class="note">横の月を縦にする・値を見出しにする・合計する、などを足せます</span><span class="btn pri sm">整え方を開く</span></div>`
   : `<div class="card"><div class="cap">ピボット解除 → ピボット</div><span class="note">${sz(data.inp)} → ${sz(data.out)}</span><span class="btn sm">整え方を開く</span></div>`}</div>`;
  io.children[0].after(mid);
 }
 async function show(k, view = 1) {
  style(); await load();
  const html = P[k](view);
  if (k === 'E') {
   document.querySelector('.editor-tab[data-etab="post"]')?.remove();
   if (view === 2) { setEditorTab('basic'); basicStage(2); return }
   basicStage(1); setEditorTab('basic');
   let ov = document.getElementById('pp-full');
   if (!ov) { ov = document.createElement('dialog'); ov.id = 'pp-full'; ov.className = 'mq-editor-dialog'; document.body.appendChild(ov) }
   ov.innerHTML = `<div class="mqe" style="padding:10px 12px;height:100%">${html}</div>`;
   ov.showModal(); return
  }
  addTab();
  const tab = document.querySelector('.editor-tab[data-etab="post"]');
  tab.querySelector('.etab-count').hidden = view === 2;
  const pane = document.querySelector('.editor-pane[data-etab="post"]');
  pane.innerHTML = html;
  setEditorTab('post');
  const body = pane.closest('.modalbody'), pp = pane.querySelector('.pp.fill');
  if (body && pp) pp.style.setProperty('--pp-h', Math.max(360, body.clientHeight - (pane.offsetTop - body.offsetTop) - 20) + 'px');
 }
 window.PP = { show, load, P };
})();
