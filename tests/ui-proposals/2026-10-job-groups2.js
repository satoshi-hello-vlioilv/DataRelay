// 2.12.0 グループの5階層・ドラッグ・範囲選択の見せ方の案（CLAUDE.md §3）。
// 中身（木の並び・ドラッグ・SHIFT の範囲選択・列の幅）は本物の画面にできている。ここで比べるのは見せ方だけ:
//  ・親子（5階層まで）の読ませ方 ・選んだ行の見せ方 ・ドラッグで落とす先の示し方
// 撮り方: 本物の画面に読み込み、window.TG2.style(k) で案の見た目にする（状態 v1〜v5 は撮る側が作る）。
(() => {
 const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const CSS = {
  // A: 字下げ＋段の案内線（行の左にも、その段の深さぶんの線）。選んだ行は淡い地色＋左の太い線。落とす先は線と「ここへ入れる」
  A: `
  #jobs.tg2-A .grp-crumb{display:none}
  #jobs.tg2-A tr[data-id] td.col-check{box-shadow:inset calc(var(--rd,0)*12px) 0 0 -0px transparent}
  #jobs.tg2-A tr[data-id] td:first-child{background-image:repeating-linear-gradient(90deg,transparent 0 10px,#c9d8de 10px 11px);background-size:calc(var(--rd,0)*11px) 100%;background-repeat:no-repeat}
  #jobs.tg2-A tbody tr.selected{outline:0;background:#e2f3f6}
  #jobs.tg2-A tbody tr.selected td:first-child{box-shadow:inset 4px 0 0 #0b7f8c}
  #jobs.tg2-A tbody tr.grp-head.drop-into .grp-bar::after{content:'ここへ入れる';margin-left:8px;font-size:11px;font-weight:800;color:#0b6577;background:#fff;border:1px solid #9fcfd6;border-radius:999px;padding:1px 9px}`,
  // B: 子の見出しに上の段の名前（パンくず）を添える＋字下げ。選んだ行は地色＋チェック、上の段に「どのグループから何件」。落とす先は点線の枠と「『品質』へ入れる」
  B: `
  #jobs.tg2-B tbody tr.selected{outline:0;background:#e6f4f7}
  #jobs.tg2-B tbody tr.selected .primarytext{color:#0b4f5c}
  #jobs.tg2-B tbody tr.grp-head.drop-into td{box-shadow:inset 0 0 0 2px #0d8191;background:#eef8fa}
  #jobs.tg2-B tbody tr.grp-head.drop-into td{outline:2px dashed #0d8191;outline-offset:-4px}
  #jobs.tg2-B .tg2-into{margin-left:8px;font-size:11.5px;font-weight:800;color:#0b6577}
  #jobs.tg2-B .tg2-selsum{font-size:12px;color:#cfe3ea;margin-left:6px;white-space:nowrap}`,
  // C: 段の深さを見出しの地色の濃淡で（深いほど淡い）＋字下げ。選んだ行は地色＋太字の名前。落とす先は見出しを塗る
  C: `
  #jobs.tg2-C .grp-crumb{display:none}
  #jobs.tg2-C tr.grp-head[data-depth="0"] td{background:color-mix(in srgb,var(--gc) 10%,#fff)}
  #jobs.tg2-C tr.grp-head[data-depth="1"] td{background:color-mix(in srgb,var(--gc) 6%,#fff)}
  #jobs.tg2-C tr.grp-head[data-depth="2"] td{background:color-mix(in srgb,var(--gc) 3%,#fff)}
  #jobs.tg2-C tbody tr.selected{outline:0;background:#e3f2f5}
  #jobs.tg2-C tbody tr.selected .col-name .primarytext{font-weight:900}
  #jobs.tg2-C tbody tr.grp-head.drop-into td{background:#cfeaee!important;box-shadow:inset 0 0 0 2px #0d8191}`,
  // D: エクスプローラーのような木の線（├ └）を見出しに。選んだ行は左の線だけ。落とす先は吹き出し「ここへ移動」
  D: `
  #jobs.tg2-D .grp-crumb{display:none}
  #jobs.tg2-D .grp-indent{position:relative}
  #jobs.tg2-D tr.is-sub .grp-indent::after{content:'';position:absolute;right:4px;top:-14px;width:10px;height:26px;border-left:1.5px solid #9fb3bb;border-bottom:1.5px solid #9fb3bb;border-bottom-left-radius:4px}
  #jobs.tg2-D tbody tr.selected{outline:0;background:transparent}
  #jobs.tg2-D tbody tr.selected td:first-child{box-shadow:inset 5px 0 0 #0b7f8c}
  #jobs.tg2-D tbody tr.grp-head.drop-into .grp-bar::after{content:'ここへ移動';margin-left:8px;font-size:11px;font-weight:800;color:#fff;background:#0b7f8c;border-radius:6px;padding:2px 9px}
  #jobs.tg2-D tbody tr.grp-head.drop-into td{box-shadow:inset 0 -3px 0 #0b7f8c}`,
  // E: パンくず＋字下げ。選んだ行は「つながった1つの塊」の枠（行ごとの枠を重ねない）。子の見出しの実行は小さく
  E: `
  #jobs.tg2-E tbody tr.selected{outline:0;background:#e6f4f7}
  #jobs.tg2-E tbody tr.selected td{box-shadow:inset 0 0 0 0 transparent}
  #jobs.tg2-E tbody tr.selected.sel-first td{box-shadow:inset 0 2px 0 #16a0a4}
  #jobs.tg2-E tbody tr.selected.sel-last td{box-shadow:inset 0 -2px 0 #16a0a4}
  #jobs.tg2-E tbody tr.selected.sel-first.sel-last td{box-shadow:inset 0 2px 0 #16a0a4,inset 0 -2px 0 #16a0a4}
  #jobs.tg2-E tbody tr.selected td:first-child{border-left:3px solid #16a0a4}
  #jobs.tg2-E tr.is-sub .grp-run{height:26px;padding:0 10px;font-size:11.5px}
  #jobs.tg2-E tbody tr.grp-head.drop-into td{box-shadow:inset 0 0 0 2px #0d8191;background:#eef8fa}`,
  // F（方向が違う）: グループの木を表の左に出す。親子・件数・落とし先・並べ替えは木で、表の見出しは今のまま
  F: `
  #jobs.tg2-F .tg2-split{display:grid;grid-template-columns:230px minmax(0,1fr);gap:10px;min-height:0}
  #jobs.tg2-F .tg2-tree{background:#fff;border:1px solid #d7e0e5;border-radius:10px;padding:8px 6px;display:flex;flex-direction:column;gap:1px;overflow:auto;align-self:start}
  #jobs.tg2-F .tg2-tree h4{margin:2px 8px 6px;font-size:12px;color:#4f6873}
  #jobs.tg2-F .tg2-tree div{display:grid;grid-template-columns:auto auto minmax(0,1fr) auto;gap:6px;align-items:center;height:30px;padding:0 8px 0 calc(8px + var(--d)*16px);border-radius:6px;font-size:12.5px;font-weight:700;color:#22404d}
  #jobs.tg2-F .tg2-tree div small{color:#7f929a;font-weight:700}
  #jobs.tg2-F .tg2-tree div.into{background:#e3f4f6;box-shadow:inset 0 0 0 2px #0d8191}
  #jobs.tg2-F .tg2-tree div.before{box-shadow:inset 0 2px 0 #0d8191}
  #jobs.tg2-F .tg2-tree i{width:9px;height:9px;border-radius:3px}
  #jobs.tg2-F tbody tr.selected{outline:0;background:#e2f3f6}
  #jobs.tg2-F tbody tr.selected td:first-child{box-shadow:inset 4px 0 0 #0b7f8c}`,
  // G（方向が違う）: 見出しはいちばん上の段だけ。下の段は行の名前の上に「圧延 › 計測」の道筋で示す（字下げの段を作らない）
  G: `
  #jobs.tg2-G tr.grp-head.is-sub{display:none}
  #jobs.tg2-G .tg2-path{display:inline-block;font-size:10.5px;font-weight:800;color:#fff;border-radius:5px;padding:0 6px;margin-right:6px;background:var(--gc)}
  #jobs.tg2-G tbody tr.selected{outline:0;background:#e2f3f6}
  #jobs.tg2-G tbody tr.selected td:first-child{box-shadow:inset 4px 0 0 #0b7f8c}
  #jobs.tg2-G tbody tr.grp-head.drop-into td{box-shadow:inset 0 0 0 2px #0d8191;background:#eef8fa}`,
 };
 const DOM = {
  A() { // 行に、属する段の深さ（--rd）を持たせる
   let d = 0; $$('#jobs-body tr').forEach(tr => { if (tr.classList.contains('grp-head')) d = +tr.dataset.depth + 1; else if (tr.dataset.id) tr.style.setProperty('--rd', groupOf(cfg.jobs.find(j => j.id === tr.dataset.id)) ? d : 0) });
  },
  B() {
   $$('#jobs-body tr.grp-head.drop-into .grp-sp').forEach(sp => sp.insertAdjacentHTML('beforebegin', `<span class="tg2-into">「${E(groupLeaf(sp.closest('tr').dataset.group))}」へ入れる</span>`));
   const n = $$('#jobs-body tr.selected').length; if (n) { const by = {}; $$('#jobs-body tr.selected').forEach(tr => { const g = groupLeaf(groupOf(cfg.jobs.find(j => j.id === tr.dataset.id))); by[g] = (by[g] || 0) + 1 });
    $('#jobs .jb-sel b')?.insertAdjacentHTML('afterend', `<span class="tg2-selsum">${Object.entries(by).map(([g, k]) => `${E(g)} ${k}件`).join('・')}</span>`) }
  },
  E() { const rows = $$('#jobs-body tr'); rows.forEach((tr, i) => { if (!tr.classList.contains('selected')) return; if (!rows[i - 1]?.classList.contains('selected')) tr.classList.add('sel-first'); if (!rows[i + 1]?.classList.contains('selected')) tr.classList.add('sel-last') }) },
  F() {
   const box = $('#jobs .tablebox'), wrap = document.createElement('div'), tree = document.createElement('div'); wrap.className = 'tg2-split'; tree.className = 'tg2-tree';
   const into = $('#jobs-body tr.grp-head.drop-into')?.dataset.group, before = $('#jobs-body tr.grp-head.drop-before')?.dataset.group;
   tree.innerHTML = '<h4>グループ</h4>' + [...groupOrder(), ''].map(p => { const d = p ? groupParts(p).length - 1 : 0, n = groupJobs(p).length; if (!n) return '';
    return `<div style="--d:${d}" class="${p === into ? 'into' : p === before ? 'before' : ''}"><span>${groupClosed.has(p) ? '▸' : '▾'}</span><i style="background:${groupColor(p)}"></i><span>${E(groupLeaf(p))}</span><small>${n}</small></div>` }).join('');
   box.before(wrap); wrap.append(tree, box);
  },
  G() {
   $$('#jobs-body tr[data-id]').forEach(tr => { const g = groupOf(cfg.jobs.find(j => j.id === tr.dataset.id)), ps = groupParts(g); if (ps.length > 1) tr.querySelector('.col-name .primarytext')?.insertAdjacentHTML('afterbegin', `<span class="tg2-path" style="--gc:${groupColor(g)}">${E(ps.slice(1).join(' › '))}</span>`) });
   // 見出しの件数は、いちばん上の段のまとまり全体
  },
 };

 // ---- 2回目: 組合せ（1回目の上位 B・C・E の良いところと、全案で弱かった「グループの並べ替え」の示し方の強化） ----
 const F = {
  sel: `tbody tr.selected{outline:0;background:#e6f4f7}
  tbody tr.selected.sel-first td{box-shadow:inset 0 2px 0 #16a0a4}
  tbody tr.selected.sel-last td{box-shadow:inset 0 -2px 0 #16a0a4}
  tbody tr.selected.sel-first.sel-last td{box-shadow:inset 0 2px 0 #16a0a4,inset 0 -2px 0 #16a0a4}
  tbody tr.selected td:last-child{box-shadow:inset -2px 0 0 #16a0a4}
  tbody tr.selected td.col-check{box-shadow:inset 2px 0 0 #16a0a4}
  .tg2-selsum{font-size:12px;color:#cfe3ea;margin-left:6px;white-space:nowrap}`,
  ink: `tbody tr.selected .col-name .primarytext{color:#17384e;font-weight:900}`,
  into: `tbody tr.grp-head.drop-into td{background:#eef8fa;outline:2px dashed #0d8191;outline-offset:-4px}
  .tg2-into{margin-left:8px;font-size:11.5px;font-weight:800;color:#0b6577}`,
  tint: `tr.grp-head[data-depth="0"] td{background:color-mix(in srgb,var(--gc) 9%,#fff)}
  tr.grp-head[data-depth="1"] td{background:color-mix(in srgb,var(--gc) 5%,#fff)}
  tr.grp-head[data-depth="2"] td,tr.grp-head[data-depth="3"] td,tr.grp-head[data-depth="4"] td{background:color-mix(in srgb,var(--gc) 3%,#fff)}`,
  move: `tbody tr.grp-head.dragging{opacity:1}
  tbody tr.grp-head.dragging td{background:repeating-linear-gradient(135deg,#f3f6f8 0 8px,#e9eff2 8px 16px)!important;color:#7a8d96}
  tbody tr.grp-head.dragging .grp-bar{opacity:.55}
  tbody tr.grp-head.drop-before td{box-shadow:inset 0 4px 0 #0d8191!important}
  .tg2-move{position:absolute;left:50%;top:-9px;transform:translateX(-50%);font-size:11px;font-weight:800;color:#fff;background:#0d8191;border-radius:999px;padding:1px 10px;white-space:nowrap;z-index:5}
  .tg2-moving{margin-left:8px;font-size:11px;font-weight:800;color:#5d727c;border:1px dashed #9fb3bb;border-radius:999px;padding:0 8px}`,
 };
 const R2 = { H: ['sel', 'into', 'move'], I: ['sel', 'into', 'move', 'tint'], J: ['sel', 'ink', 'into', 'move'], K: ['sel', 'ink', 'into', 'move', 'tint'] };
 for (const [k, fs] of Object.entries(R2)) CSS[k] = fs.map(f => F[f].replace(/(^|\n)\s*([^\n{]+)\{/g, (m, a, sel) => `${a}#jobs.tg2-${k} ${sel.split(',').join(`,#jobs.tg2-${k} `)}{`)).join('\n');
 const r2dom = () => { DOM.E(); DOM.B();
  const b = $('#jobs-body tr.grp-head.drop-before'), d = $('#jobs-body tr.grp-head.dragging');
  if (b && d) { const bar = b.querySelector('.grp-bar'); bar.style.position = 'relative'; bar.insertAdjacentHTML('afterbegin', `<span class="tg2-move">「${E(groupLeaf(d.dataset.group))}」をここへ（「${E(groupLeaf(b.dataset.group))}」の前）</span>`);
   d.querySelector('.grp-name')?.insertAdjacentHTML('afterend', '<span class="tg2-moving">動かしています</span>') } };
 ['H', 'I', 'J', 'K'].forEach(k => DOM[k] = r2dom);
 window.TG2 = { keys: Object.keys(CSS), style(k) { if (!CSS[k]) return; document.head.insertAdjacentHTML('beforeend', `<style>${CSS[k]}</style>`); $('#jobs').classList.add('tg2-' + k); DOM[k]?.(); return true } };
})();
