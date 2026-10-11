// 2.1.2 データビュワーで、値ごとに分けて出した対象のファイルを1つずつ見る案（CLAUDE.md §3）。
// 本物のビュワー（設備単位実績の LS4 を開いた状態）に、案ごとの部品を当てて再現する。
// 状態: 7値のうち LS4・LS3・DL2・TLV・CAL は作成済み、FS4・KEN はまだ無い。
// 撮り方: 撮影用の仕掛けで window.VF.show(k)。1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const FILES = [['LS4', 769], ['LS3', 1238], ['DL2', 2023], ['TLV', 2197], ['CAL', 1165], ['FS4', null], ['KEN', null]];
 const n = x => x == null ? '未出力' : x.toLocaleString() + '件';
 const MADE = FILES.filter(x => x[1] != null).length, ALL = FILES.reduce((a, x) => a + (x[1] || 0), 0);
 const chips = (cur = 'LS4', withAll = false) => `${withAll ? `<button class="vf-chip ${cur === '' ? 'on' : ''}"><b>すべて</b><small>${ALL.toLocaleString()}件</small></button><i class="vf-sep"></i>` : ''}${FILES.map(([v, r]) => `<button class="vf-chip ${v === cur ? 'on' : ''} ${r == null ? 'off' : ''}" ${r == null ? 'disabled' : ''}><b>${v}</b><small>${n(r)}</small></button>`).join('')}`;
 const V = {
  A: { name: 'A データの選択肢に値を並べる（対象ごとのまとまりの中に 値・件数）', run() {
   setSelect('設備単位実績 · LS4 / SQLite3'); pill('LS4');
   document.querySelector('.viewer-source').insertAdjacentHTML('beforeend', `<div class="vf-pop"><em>設備単位実績（値ごと ${MADE}/${FILES.length}）</em>${FILES.map(([v, r]) => `<div class="${v === 'LS4' ? 'on' : ''} ${r == null ? 'off' : ''}"><span>${v}</span><small>${n(r)}</small></div>`).join('')}<em>仕掛ロット</em><div><span>SIKALOTNOW</span><small>50件</small></div></div>`);
  } },
  B: { name: 'B 対象の隣に「値」の選択を出す', run() {
   document.querySelector('.viewer-source').insertAdjacentHTML('beforeend', `<label class="vf-sel">値<select><option>LS4 · 769件</option></select></label>`); pill('LS4');
  } },
  C: { name: 'C 上の帯の下に、値の札を並べて切り替える（未出力は灰色）', run() {
   pill('LS4'); document.querySelector('.viewer-topbar').insertAdjacentHTML('afterend', `<div class="vf-row"><span class="vf-l">値ごとのファイル <b>${MADE}/${FILES.length}</b></span>${chips()}</div>`);
  } },
  D: { name: 'D 左に対象と値の木を出す（ファイルを選ぶ欄）', run() {
   const shell = document.querySelector('.viewer-shell'); shell.classList.add('vf-tree-on');
   shell.insertAdjacentHTML('afterbegin', `<aside class="vf-tree"><b>設備単位実績</b>${FILES.map(([v, r]) => `<div class="${v === 'LS4' ? 'on' : ''} ${r == null ? 'off' : ''}"><span>${v}</span><small>${n(r)}</small></div>`).join('')}<b>仕掛ロット</b><div><span>SIKALOTNOW</span><small>50件</small></div></aside>`); pill('LS4');
  } },
  E: { name: 'E 対象名の札の横に、値を区切りのタブで並べる', run() {
   const m = document.getElementById('viewer-meta'); m.querySelector('#viewer-name').insertAdjacentHTML('afterend', `<div class="vf-tabs">${FILES.map(([v, r]) => `<button class="${v === 'LS4' ? 'on' : ''} ${r == null ? 'off' : ''}">${v}</button>`).join('')}</div>`);
  } },
  F: { name: 'F （方向違い）値ごとのファイルをまとめて1つの表で見て、値で絞る', run() {
   pill('すべて'); document.getElementById('viewer-count').textContent = `${ALL.toLocaleString()}行 × 10列（5ファイル）`;
   document.querySelector('.viewer-topbar').insertAdjacentHTML('afterend', `<div class="vf-row"><span class="vf-l">値で絞る</span>${chips('', true)}</div>`);
   document.getElementById('viewer-filter-summary').textContent = `${ALL.toLocaleString()} / ${ALL.toLocaleString()}行`;
  } },
  // 2回目の組合せ案（1回目の上位 C・F・G のエッセンス）
  H: { name: 'H C の札＋データの選択肢にも値を並べる（A。値が多いときはこちらから）', run() {
   V.C.run(); setSelect('設備単位実績 · LS4 / SQLite3');
  } },
  I: { name: 'I C の札の先頭に「すべて」（F。まとめて1つの表でも見られる）', run() {
   pill('LS4'); document.querySelector('.viewer-topbar').insertAdjacentHTML('afterend', `<div class="vf-row"><span class="vf-l">値ごとのファイル <b>${MADE}/${FILES.length}</b></span>${chips('LS4', true)}</div>`);
  } },
  J: { name: 'J 作成済みの値だけ札にし、未出力はまとめて文字で（例外だけ出す）', run() {
   pill('LS4'); document.querySelector('.viewer-topbar').insertAdjacentHTML('afterend', `<div class="vf-row"><span class="vf-l">値ごとのファイル</span>${FILES.filter(x => x[1] != null).map(([v, r]) => `<button class="vf-chip ${v === 'LS4' ? 'on' : ''}"><b>${v}</b><small>${n(r)}</small></button>`).join('')}<span class="vf-miss">未出力: FS4・KEN（前回の実行で作られていません）</span></div>`);
  } },
  K: { name: 'K C の札＋右端に開いているファイルの名前と更新日時（G）', run() {
   pill('LS4'); document.querySelector('.viewer-topbar').insertAdjacentHTML('afterend', `<div class="vf-row"><span class="vf-l">値ごとのファイル <b>${MADE}/${FILES.length}</b></span>${chips()}<span class="vf-file">実績_LS4.sqlite3 · 10-11 05:45</span></div>`);
  } },
  G: { name: 'G （方向違い）先に値ごとのファイルの一覧（件数・更新日時）を見せ、押して開く', run() {
   pill('7ファイル'); document.getElementById('viewer-list').hidden = true;
   document.querySelector('.viewer-topbar').insertAdjacentHTML('afterend', `<div class="vf-cards">${FILES.map(([v, r]) => `<button class="vf-card ${r == null ? 'off' : ''}"><b>${v}</b><span>${n(r)}</span><small>${r == null ? '前回の実行で作られていません' : '実績_' + v + '.sqlite3 · 10-11 05:45'}</small></button>`).join('')}</div>`);
  } },
 };
 const CSS = `
  .viewer-v118:has(.vf-row),.viewer-v118:has(.vf-cards){grid-template-rows:auto auto minmax(0,1fr)}
  .vf-chip,.vf-tabs button,.vf-card{color:#1d3440!important}.vf-chip b,.vf-chip small,.vf-tabs button,.vf-card b,.vf-card span,.vf-card small{text-shadow:none}
  .vf-cards{align-self:start}
  .vf-pop{position:absolute;z-index:30;top:calc(100% - 4px);left:0;min-width:300px;background:#fff;border:1px solid #c9d8de;border-radius:8px;box-shadow:0 8px 24px rgba(23,56,78,.18);padding:4px 0;font-size:13px}
  .vf-pop em{display:block;font-style:normal;font-size:11px;font-weight:800;color:#5d737d;padding:6px 12px 2px}.vf-pop div{display:flex;justify-content:space-between;padding:4px 12px 4px 22px}.vf-pop div.on{background:#1b8fa6;color:#fff}.vf-pop div.off{color:#a2b1b7}.vf-pop small{font-size:11px}
  .viewer-source{position:relative}
  .vf-sel{display:grid;font-size:11px;color:#5d737d;font-weight:700}.vf-sel select{min-width:150px;height:36px;font-size:14px}
  .vf-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:8px 12px;margin:-4px 0 8px;background:#f6fafb;border:1px solid #dbe6ea;border-radius:10px}
  .vf-l{font-size:12px;font-weight:800;color:#3e5964;margin-right:4px}.vf-l b{color:#14576a}
  .vf-chip{display:inline-flex;align-items:baseline;gap:6px;padding:4px 11px;border:1px solid #cfdde2;border-radius:16px;background:#fff;cursor:pointer;font:inherit}.vf-chip b{font-size:13px;color:#1d3440!important}.vf-chip small{font-size:11px;color:#60757c!important}
  .vf-chip.on{background:#149aa5;border-color:#149aa5}.vf-chip.on b,.vf-chip.on small{color:#fff!important}.vf-chip.off{background:#f1f4f5;border-style:dashed;cursor:not-allowed}.vf-chip.off b,.vf-chip.off small{color:#9aabb2!important}
  .vf-miss{font-size:12px;color:#7b8c93;margin-left:6px}.vf-file{margin-left:auto;font-size:11.5px;color:#4d6670;font-family:Consolas,monospace}
  .vf-sep{width:1px;height:20px;background:#cfdce1;margin:0 4px}
  .viewer-shell.vf-tree-on{display:grid;grid-template-columns:200px minmax(0,1fr);column-gap:12px}.viewer-shell.vf-tree-on>*:not(.vf-tree){grid-column:2}
  .vf-tree{grid-column:1;grid-row:1 / span 9;border:1px solid #dbe6ea;border-radius:10px;background:#fff;padding:8px 0;font-size:13px;align-self:start}.vf-tree b{display:block;padding:6px 12px;font-size:12px;color:#3e5964}
  .vf-tree div{display:flex;justify-content:space-between;padding:4px 12px 4px 24px;cursor:pointer}.vf-tree div.on{background:#e3f3f5;box-shadow:inset 3px 0 0 #149aa5;font-weight:700}.vf-tree div.off{color:#a2b1b7}.vf-tree small{font-size:11px;color:#60757c}
  .vf-tabs{display:inline-flex;border:1px solid #cfdde2;border-radius:8px;overflow:hidden}.vf-tabs button{border:0;border-left:1px solid #dbe5e9;background:#fff;padding:3px 10px;font:700 12px inherit;cursor:pointer}.vf-tabs button:first-child{border-left:0}.vf-tabs button.on{background:#149aa5;color:#fff!important}.vf-tabs button.off{color:#a2b1b7!important;background:#f4f6f7}
  .vf-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin:0 0 10px}
  .vf-card{display:grid;gap:3px;text-align:left;padding:12px 14px;border:1px solid #d3e0e5;border-left:4px solid #1f936b;border-radius:10px;background:#fff;cursor:pointer;font:inherit}.vf-card b{font-size:18px;color:#1d3440}.vf-card span{font-size:14px;font-weight:700;color:#14576a!important}.vf-card small{font-size:11px;color:#60757c!important}
  .vf-card.off{border-left-color:#b9c6cb;background:#f6f8f9}.vf-card.off b,.vf-card.off span{color:#9aabb2!important}
 `;
 function setSelect(text) { const s = document.getElementById('viewer-job'); s.innerHTML = `<option>${E(text)}</option>` }
 function pill(text) { const nm = document.getElementById('viewer-name'); nm.textContent = `設備単位実績 · ${text}` }
 function style(css) { let s = document.getElementById('vf-style'); if (!s) { s = document.createElement('style'); s.id = 'vf-style'; document.head.appendChild(s) } s.textContent = CSS + (css || '') }
 window.VF = {
  V, FILES, CSS, style,
  async show(k) {
   style(V[k].css);
   const s = document.getElementById('viewer-job'); s.value = 'lot'; s.dispatchEvent(new Event('change'));
   await new Promise(r => setTimeout(r, 1200));
   V[k].run();
  },
 };
})();
