// 2.1.0「条件の値ごとに分けて出す」の案（CLAUDE.md §3）。対象の編集（#editor）に、案ごとの DOM と CSS を当てて再現する。
// データはどの案も同じ実データ（/api/variants/preview: RNE の条件欄の項目といまのキー、値ごとの出し先）。
// 撮り方: 撮影用の仕掛けで window.VV.show(k)。1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const VALUES = ['LS3', 'LS4', 'DL2', 'KEN'];
 let P = null; // 見込み（受け口の答え）
 async function load() {
  const j = cfg.jobs.find(x => x.id === 'lot');
  const body = { rne: j.rne, rne_path: j.rne_path, name: j.name, output_format: j.output_format, output_file: j.output_file, output_folder: j.output_folder,
   variants: { item: 'BOX実績_設備名', values: VALUES } };
  P = await (await fetch('/api/variants/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
  P.job = j; return P;
 }
 const cond = () => (P.conditions || [])[0] || { name: 'BOX実績_設備名', keys: [] };
 const chips = (edit = true) => `<span class="vv-chips">${VALUES.map(v => `<em>${E(v)}${edit ? '<button type="button" aria-label="外す">×</button>' : ''}</em>`).join('')}${edit ? '<input class="vv-add" placeholder="値を足す（Enter）">' : ''}</span>`;
 const fileList = (cls = '') => `<ul class="vv-files ${cls}">${P.files.map(f => `<li><b>${E(f.value)}</b><code>${E(f.file)}</code></li>`).join('')}</ul>`;
 const folderLine = () => `<span class="vv-folder">置き場: <code>${E(P.files[0]?.folder || '')}</code></span>`;
 const detect = () => `<span class="vv-detect">RNE の条件: <b>${E(cond().name)}</b> = ${cond().keys.map(E).join('・') || '（なし）'}</span>`;
 const sw = (label, sub) => `<label class="switch vv-switch"><input type="checkbox" checked><span>${label}<small>${sub}</small></span></label>`;
 const itemSel = () => `<label>分ける項目（RNE の条件欄）<select><option>${E(cond().name)}（いま ${cond().keys.map(E).join('・')}）</option></select></label>`;
 const nameRule = () => `<label>ファイル名<div class="vv-name"><input value="LOTACH_{値}"><span class="vv-ext">.xlsx</span></div><small class="vv-tip"><code>{値}</code> がそれぞれの値（LS3 など）に置き換わります</small></label>`;
 const folderIn = () => `<label>置き場<div class="browse"><input value="${E(P.job.output_folder)}"><button type="button" class="secondary">参照</button></div><small class="vv-tip">空なら出力フォルダー。<code>{値}</code> を入れると値ごとのフォルダー</small></label>`;
 const CSS = `
  .vv-box{border:1px solid #cfe0e6;border-radius:10px;background:#f7fbfc;padding:12px 14px;display:grid;gap:10px}
  .vv-switch{display:flex!important}.vv-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 8px;border:1px solid #aebdc6;border-radius:7px;background:#fff;min-height:38px}
  .vv-chips em{font-style:normal;display:inline-flex;align-items:center;gap:2px;padding:2px 3px 2px 10px;border-radius:999px;background:#e3f3f5;color:#14576a;font-weight:700;font-size:12.5px}
  .vv-chips em button{background:transparent;color:#5c7e89;padding:0 6px;font-size:13px}.vv-chips .vv-add{border:0;height:26px;width:150px;padding:0 4px}
  .vv-files{margin:0;padding:0;list-style:none;display:grid;gap:4px}.vv-files li{display:grid;grid-template-columns:52px 1fr;gap:8px;align-items:center;font-size:12.5px}
  .vv-files li b{font-size:11px;color:#14576a;background:#e3f3f5;border-radius:5px;text-align:center;padding:1px 0}.vv-files code{font:12px Consolas,monospace;color:#263d48;overflow-wrap:anywhere}
  .vv-folder{font-size:11.5px;color:#5d7380}.vv-folder code{font:11.5px Consolas,monospace}
  .vv-detect{font-size:12px;color:#3c5662}.vv-detect b{color:#14576a}
  .vv-name{display:grid;grid-template-columns:1fr auto;border:1px solid #aebdc6;border-radius:6px;overflow:hidden}.vv-name input{border:0}.vv-ext{font:13px Consolas,monospace;color:#0b7e8f;background:#eef6f8;padding:8px 10px}
  .vv-tip{font-size:11px;color:#647581;font-weight:400}.vv-tip code{font:11px Consolas,monospace;background:#eef3f5;padding:0 4px;border-radius:3px}
  .vv-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}.vv-grid label{font-size:12px;font-weight:700;color:#425661;display:grid;gap:4px}
  .vv-head{display:flex;align-items:center;gap:10px;justify-content:space-between}.vv-head h4{margin:0;font-size:13px;color:#203d4a}
 `;
 // 案ごとに、どこへ何を差し込むか
 const V = {
  A: { name: 'A 新しいタブ「5 値ごとに分ける」', tab: true, html: () => `<div class="vv-box">${sw('条件の値ごとに分けて出す', '値の数だけ問い合わせ、値ごとに別のファイルを作ります（API 方式）')}${detect()}
    <div class="vv-grid">${itemSel()}<label>値<span>${chips()}</span></label>${nameRule()}${folderIn()}</div>
    <div><div class="vv-head"><h4>できあがるファイル（${P.files.length}）</h4>${folderLine()}</div>${fileList()}</div></div>` },
  B: { name: 'B「2 ファイル名」の下に区画', where: 'naming', html: () => `<div class="sectiontitle">条件の値ごとに分けて出す</div><div class="vv-box">${sw('値ごとに分けて出す', '上のファイル名に {値} を入れると、値ごとの名前になります（無ければ末尾に _値）')}
    <div class="vv-grid">${itemSel()}<label>値<span>${chips()}</span></label></div>${fileList()}</div>` },
  C: { name: 'C「1」の出力データ欄の空きに収める', where: 'output', html: () => `<div class="vv-box">${sw('条件の値ごとに分けて出す', detect().replace(/<[^>]+>/g, ''))}<label class="vv-l">値${chips()}</label>${fileList('vv-compact')}<small class="vv-tip">ファイル名は「2 ファイル名」で。<code>{値}</code> が値に置き換わります</small></div>` },
  D: { name: 'D 値ごとの表（名前・置き場を行ごとに直せる）', tab: true, html: () => `<div class="vv-box">${sw('条件の値ごとに分けて出す', '1行が1ファイル。名前と置き場は行ごとに直せます')}${detect()}
    <table class="rel-table"><thead><tr><th>値</th><th>ファイル名</th><th>置き場</th><th></th></tr></thead><tbody>${P.files.map(f => `<tr><td><b>${E(f.value)}</b></td><td><input value="${E(f.file)}"></td><td><input value="${E(f.folder)}"></td><td><button type="button" class="textbtn">外す</button></td></tr>`).join('')}</tbody></table>
    <div><button type="button" class="secondary">＋ 値を足す</button></div></div>` },
  E: { name: 'E 入力（RNE）の下で先回りして出す', where: 'input', html: () => `<div class="vv-box vv-e"><div class="vv-head"><span>${detect()}</span><span class="pill">値ごとに分けて出す: 入</span></div>
    <label class="vv-l">この値ごとに1ファイル${chips()}</label>${fileList('vv-compact')}${folderLine()}</div>` },
  F: { name: 'F 手順で進める（何で → どの値 → 名前と置き場 → 確認）', tab: true, html: () => `<div class="vv-steps"><span class="done">① 何で分ける <b>${E(cond().name)}</b></span><span class="on">② どの値</span><span>③ 名前と置き場</span><span>④ 確認</span></div>
    <div class="vv-box"><h4 style="margin:0">② どの値ごとにファイルを作りますか</h4><p class="vv-tip" style="margin:0">RNE にはいま <b>${cond().keys.map(E).join('・')}</b> が入っています。足した値の数だけファイルができます。</p>${chips()}
    <div style="display:flex;gap:8px;justify-content:flex-end"><button type="button" class="secondary">戻る</button><button type="button">次へ（名前と置き場）</button></div></div>` },
  G: { name: 'G 文章で組み立てる（1文を読めば分かる）', where: 'output', html: () => `<div class="vv-box vv-g">${sw('条件の値ごとに分けて出す', '')}<p class="vv-sentence"><select><option>${E(cond().name)}</option></select> が ${chips()} の<b>それぞれ</b>について、
    <span class="vv-name vv-inl"><input value="LOTACH_{値}"><span class="vv-ext">.xlsx</span></span> として出力フォルダーへ出す</p>${fileList('vv-compact')}</div>` },
 };
 // ---- 2回目（1回目 A87・D78・F76 で僅差）: 良いところを組み合わせた H〜K ----
 // A の「1か所で完結」、D の「1行1ファイルで道まで見える」、F の「何から決めるかの順」、E/C の「1ページ目で先回り」、G の「1文で読める」
 const toggle = on => `<div class="vv-toggle"><label><input type="checkbox"${on ? ' checked' : ''}><b>条件の値ごとに分けて出す</b></label><span>値の数だけ問い合わせ、値ごとに別のファイルを作ります（API 方式）</span></div>`;
 const sentence = () => `<p class="vv-say"><b>${E(cond().name)}</b> が <b>${VALUES.join('・')}</b> のそれぞれについて、<b>${P.files.length}ファイル</b>を作ります</p>`;
 const fileTable = () => `<table class="rel-table vv-ft"><thead><tr><th>値</th><th>できあがるファイル</th></tr></thead><tbody>${P.files.map((f, i) => `<tr><td><b class="vv-v">${E(f.value)}</b>${f.value === (cond().keys[0] || '') ? '<i class="rel-tag is-here">RNE の今の値</i>' : ''}</td><td><code>${E(f.path)}</code></td></tr>`).join('')}</tbody></table>`;
 const num = (n, t) => `<span class="vv-num">${n}</span><b>${t}</b>`;
 const leftNumbered = () => `<div class="vv-col">
   <div class="vv-f">${num('①', '分ける項目')}<select><option>${E(cond().name)}（RNE の条件欄・いま ${cond().keys.map(E).join('・')}）</option></select></div>
   <div class="vv-f">${num('②', '値')}${chips()}<small class="vv-tip">値の数だけファイルができます。Enter で足し、× で外します</small></div>
   <div class="vv-f">${num('③', 'ファイル名')}<div class="vv-name"><input value="LOTACH_{値}"><span class="vv-ext">.xlsx</span></div><small class="vv-tip"><code>{値}</code> が値に置き換わります。日付などの変数も使えます</small></div>
   <div class="vv-f">${num('④', '置き場')}<div class="browse"><input value="" placeholder="${E(P.job.output_folder)}（出力フォルダー）"><button type="button" class="secondary">参照</button></div><small class="vv-tip">空なら出力フォルダー。<code>{値}</code> で値ごとのフォルダー</small></div></div>`;
 Object.assign(V, {
  H: { name: 'H タブ・左で決めて右にできあがり（A+D）', tab: true, html: () => `<div class="vv-box">${toggle(true)}<div class="vv-two">${leftNumbered()}<div class="vv-col"><h4 class="vv-h">できあがるファイル（${P.files.length}）</h4>${fileTable()}</div></div></div>` },
  I: { name: 'I タブ＋1ページ目で先回り（A+E+C）', tab: true, also: 'card', html: () => `<div class="vv-box">${toggle(true)}${detect()}<div class="vv-grid">${itemSel()}<label>値<span>${chips()}</span></label>${nameRule()}${folderIn()}</div><div><h4 class="vv-h">できあがるファイル（${P.files.length}）</h4>${fileList()}</div></div>` },
  J: { name: 'J タブ・番号順に全部見せて1文で確かめる（A+F+G）', tab: true, html: () => `<div class="vv-box">${toggle(true)}${sentence()}${leftNumbered().replace('vv-col', 'vv-col vv-wide')}<div><h4 class="vv-h">できあがるファイル</h4>${fileList()}</div></div>` },
  K: { name: 'K タブ・番号順と表、1文、1ページ目の札（H+J+I）', tab: true, also: 'card', html: () => `<div class="vv-box">${toggle(true)}${sentence()}<div class="vv-two">${leftNumbered()}<div class="vv-col"><h4 class="vv-h">できあがるファイル（${P.files.length}）</h4>${fileTable()}</div></div></div>` },
 });
 // 1ページ目（基本と入出力）の札。RNE に条件があれば先回りして出し、入なら何ファイルできるかを出す
 const card = () => `<div class="vv-card"><span class="vv-card-k">値ごとに分けて出す</span><b>入 · ${P.files.length}ファイル</b><span class="vv-card-v">${E(cond().name)} = ${VALUES.join('・')}</span><button type="button" class="textbtn">設定を開く ›</button></div>`;
 const CSS2 = `.vv-toggle{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}.vv-toggle label{display:flex;align-items:center;gap:8px;font-size:14px;color:#203d4a}.vv-toggle input{width:18px;height:18px}.vv-toggle span{font-size:12px;color:#647581}
  .vv-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:16px;align-items:start}.vv-col{display:grid;gap:12px;min-width:0}.vv-f{display:grid;gap:5px}.vv-f>b{font-size:12px;color:#425661}
  .vv-num{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#0b7e8f;color:#fff;font-size:11px;font-weight:800;margin-right:6px;vertical-align:middle}.vv-f>b{display:inline}
  .vv-h{margin:0 0 6px;font-size:13px;color:#203d4a}.vv-ft code{font:12px Consolas,monospace;overflow-wrap:anywhere}.vv-v{color:#14576a}
  .vv-say{margin:0;padding:8px 12px;border-radius:8px;background:#fff;border:1px solid #d5e5ea;font-size:13px;color:#263d48}.vv-say b{color:#14576a}
  .vv-wide{grid-template-columns:1fr 1fr;display:grid;gap:12px 16px}
  .vv-card{display:grid;grid-template-columns:auto 1fr auto;grid-template-rows:auto auto;gap:2px 10px;align-items:center;padding:10px 12px;border:1px solid #c3dfec;border-radius:9px;background:#eef6fb;margin:8px 0}
  .vv-card-k{font-size:11px;font-weight:800;color:#155f80}.vv-card b{font-size:13px;color:#14445c}.vv-card-v{grid-column:1/3;font-size:12px;color:#4b6a7a}.vv-card button{grid-row:1/3;grid-column:3}
  .vv-steps{display:flex;gap:6px;margin-bottom:10px}.vv-steps span{flex:1;padding:8px 10px;border-radius:8px;background:#eef3f5;color:#647581;font-size:12px;font-weight:700}
  .vv-steps .on{background:#0b7e8f;color:#fff}.vv-steps .done{background:#e3f3f5;color:#14576a}.vv-steps b{font-weight:700}
  .vv-sentence{margin:0;line-height:2.4;font-size:13px;color:#263d48;display:flex;flex-wrap:wrap;align-items:center;gap:6px}.vv-sentence select{width:auto;height:30px}
  .vv-inl{display:inline-grid!important;width:220px}.vv-compact li{grid-template-columns:44px 1fr}.vv-l{display:grid;gap:4px;font-size:12px;font-weight:700;color:#425661}
  .rel-table input{height:30px}`;
 function style() { let s = document.getElementById('vv-style'); if (!s) { s = document.createElement('style'); s.id = 'vv-style'; document.head.appendChild(s) } s.textContent = CSS + CSS2 }
 function clear() { document.querySelectorAll('.vv-slot').forEach(x => x.remove()); document.querySelectorAll('[data-etab="vv"]').forEach(x => x.remove()) }
 window.VV = {
  V, load,
  async card() { if (!P) await load(); style(); document.querySelectorAll('.vv-card').forEach(x => x.remove()); setEditorTab('basic'); const d = document.createElement('div'); d.innerHTML = card(); document.querySelector('.trendbox').before(d.firstElementChild) },
  async show(k) {
   if (!P) await load(); style(); clear();
   const v = V[k], slot = document.createElement('div'); slot.className = 'vv-slot'; slot.innerHTML = v.html();
   if (v.tab) {
    const tab = document.createElement('button'); tab.type = 'button'; tab.className = 'editor-tab'; tab.dataset.etab = 'vv';
    tab.innerHTML = '<i class="etab-badge eb-name">5</i><span class="etab-text"><b>値ごとに分ける</b><small>条件の値ごとに別ファイル</small></span><span class="etab-count">4</span>';
    document.querySelector('.editor-tabsep').before(tab);
    const pane = document.createElement('div'); pane.className = 'editor-pane'; pane.dataset.etab = 'vv'; pane.appendChild(slot);
    document.querySelector('.editor-pane[data-etab="schedule"]').after(pane);
    document.querySelectorAll('.editor-tab').forEach(t => t.classList.toggle('on', t.dataset.etab === 'vv'));
    document.querySelectorAll('.editor-pane').forEach(p => p.classList.toggle('on', p.dataset.etab === 'vv'));
   } else if (v.where === 'naming') { setEditorTab('naming'); document.querySelector('.editor-pane[data-etab="naming"]').appendChild(slot) }
   else if (v.where === 'output') { setEditorTab('basic'); document.querySelector('.trendbox').before(slot) }
   else if (v.where === 'input') { setEditorTab('basic'); document.querySelector('.src-pane[data-src="rne"]').appendChild(slot) }
  },
 };
})();
