// 2.5.0「出てきた値すべて」と「出てくる値を数える」の案（CLAUDE.md §3）。対象の編集（#editor）の「値ごとに分ける」タブの中身（.var-box）を、
// 案ごとの DOM と CSS に差し替えて再現する。データはどの案も同じ実データ（/api/variants/preview: 条件欄の項目といまのキー・数えた値と行数・出し先）。
// 撮り方: 撮影用の仕掛けで window.VV.show('A1') など。末尾 1 = 出てきた値すべてを選び、まだ数えていない / 2 = 数えたあと。
// 1回目 A〜G（5案＋方向の違う2案 F・G）。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const N = n => Number(n || 0).toLocaleString();
 let P = null;
 async function load() {
  const j = cfg.jobs.find(x => x.id === 'lot');
  const body = { id: j.id, rne: j.rne, rne_path: j.rne_path, name: j.name, output_format: j.output_format, output_file: j.output_file, output_folder: j.output_folder,
   period: j.period, variants: { item: 'BOX実績_設備名', scope: 'all' } };
  P = await (await fetch('/api/variants/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
  P.job = j; return P;
 }
 const cond = () => (P.conditions || [])[0] || { name: 'BOX実績_設備名', keys: ['LS4'] };
 const C = () => P.counted || { values: [], rows: 0, taken_at: '' };
 const when = () => { const t = new Date(C().taken_at); return `${t.getMonth() + 1}/${t.getDate()} ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`; };
 const folder = () => P.files[0]?.folder || P.job.output_folder;
 // 共通の部品（いまの画面と同じ形・言葉）
 const head = () => `<div class="var-toggle"><label><input type="checkbox" checked><b>条件の値ごとに分けて出す</b></label><span>RNE の条件の絞り込みを外し、値ごとに別のファイルを作ります（API 方式。RNE ファイルは書き換えません）</span></div>`;
 const method = (all) => `<div class="var-method"><span class="var-method-l">取り方</span><div class="var-method-seg">
   <label class="${all ? 'vv-off' : 'on'}"><b>既定に従う</b><small>いまは まとめて1回</small></label>
   <label class="${all ? 'on' : ''}"><b>まとめて1回</b><small>問い合わせ1回 · 受け取ってから分ける</small></label>
   <label class="vv-off"><b>値ごとに並列</b><small>${all ? '値を指定したときだけ' : '値ごとに同時に問い合わせ'}</small></label></div></div>`;
 const item = () => `<label class="var-f"><span class="var-l"><i>1</i>分ける項目<small>RNE の条件欄にある項目</small></span><input value="${E(cond().name)}"><span class="var-detect">RNE の条件欄: <button type="button" class="var-pick">${E(cond().name)}<small>いま ${E(cond().keys.join('・'))}</small></button></span></label>`;
 const name = () => `<label class="var-f"><span class="var-l"><i>3</i>ファイル名<small><code>{値}</code> が値に置き換わります。空なら「ファイル名」タブの名前_値</small></span><span class="var-name"><input placeholder="LOTACH_{値}（空のときの名前）"><em>.xlsx</em></span></label>`;
 const place = () => `<label class="var-f"><span class="var-l"><i>4</i>置き場<small>空なら出力フォルダー。<code>{値}</code> を入れると値ごとのフォルダー</small></span><span class="browse"><input placeholder="${E(folder())}（出力フォルダー）"><button type="button" class="secondary">参照</button></span></label>`;
 const say = (counted) => `<p class="var-say"><b>${E(cond().name)}</b> の絞り込みを外して<b>まとめて1回</b>で問い合わせ、<b>出てきた値すべて</b>で値ごとのファイルを作ります${counted ? `（いまの条件では <b>${C().values.length}ファイル</b>）` : ''}。</p>`;
 const countBtn = (counted, cls = '') => `<button type="button" class="${counted ? 'secondary' : ''} vv-count ${cls}">${counted ? '数え直す' : '出てくる値を数える'}</button>`;
 const countNote = () => `<small class="vv-tip">いまの条件で1回問い合わせて数えます（ファイルは作りません）。数えなくても実行できます。</small>`;
 const fileTable = (withRows = true) => `<table class="rel-table var-table"><thead><tr><th>値</th><th>できあがるファイル</th>${withRows ? '<th class="vv-r">行数</th>' : ''}</tr></thead><tbody>${P.files.map(f => `<tr><td><b>${E(f.value)}</b>${cond().keys.includes(f.value) ? '<i class="rel-tag is-here">RNE の今の値</i>' : ''}</td><td><code>${E(f.file)}</code></td>${withRows ? `<td class="vv-r">${N(f.rows)}</td>` : ''}</tr>`).join('')}</tbody></table><small class="vv-tip">置き場: <code>${E(folder())}</code></small>`;
 const pending = (text) => `<div class="var-empty vv-pend">${text}</div>`;
 const stamp = () => `<span class="vv-stamp"><b>${C().values.length}ファイル</b> · ${N(C().rows)}件 · ${when()} に数えた（いまの条件）</span>`;
 const seg2 = (all) => `<div class="vv-seg"><label class="${all ? '' : 'on'}"><b>指定した値だけ</b><small>値の数だけファイル</small></label><label class="${all ? 'on' : ''}"><b>出てきた値すべて</b><small>出てきた値の数だけファイル</small></label></div>`;
 const CSS = `
  .vv-seg{display:grid;grid-template-columns:1fr 1fr;border:1px solid #c9d8de;border-radius:9px;overflow:hidden;background:#fff}
  .vv-seg label{display:grid;gap:1px;padding:6px 11px;border-left:1px solid #dbe5e9;cursor:pointer}.vv-seg label:first-child{border-left:0}
  .vv-seg label.on{background:#e3f3f5;box-shadow:inset 0 -2px 0 #149aa5}.vv-seg b{font-size:12px;color:#1d3440}.vv-seg small{font-size:10.5px;color:#5d7380;font-weight:400}
  .var-method-seg label.vv-off{opacity:.45;cursor:not-allowed}
  .vv-tip{font-size:11px;color:#647581;font-weight:400}.vv-tip code{font:11px Consolas,monospace;background:#eef3f5;padding:0 4px;border-radius:3px}
  .vv-all{display:grid;gap:4px;padding:9px 11px;border:1px solid #bfe0e6;border-radius:8px;background:#fff;font-size:12px;color:#263d48}
  .vv-all b{color:#14576a}
  .vv-hd{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 6px}.vv-hd h4{margin:0;font-size:13px;color:#203d4a}
  .vv-r{text-align:right!important;white-space:nowrap;font-variant-numeric:tabular-nums}
  .vv-pend{display:grid;gap:8px;justify-items:start;line-height:1.6}
  .vv-stamp{font-size:12px;color:#425661}.vv-stamp b{color:#14576a;font-size:13px}
  .vv-strip{display:flex;align-items:center;gap:12px;padding:9px 12px;border-radius:8px;border:1px solid #bfe0e6;background:#eef8fa}
  .vv-strip.is-none{background:#fff;border-style:dashed}.vv-strip .vv-k{font-size:11.5px;font-weight:800;color:#155f80}.vv-strip .vv-sp{flex:1}
  .vv-check{display:flex;gap:8px;align-items:center;font-size:12.5px;color:#203d4a;font-weight:700}.vv-check input{width:16px;height:16px}
  .vv-allchip{display:inline-flex;align-items:center;gap:6px;padding:3px 12px;border-radius:999px;background:#0b7e8f;color:#fff;font-weight:800;font-size:12.5px}
  .vv-link{background:none;border:0;color:#0b6f80;text-decoration:underline;padding:0 4px;font-size:12px}
  .vv-cards{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .vv-card{display:grid;gap:5px;align-content:start;padding:11px 13px;border:1px solid #c9d8de;border-radius:10px;background:#fff;cursor:pointer;font-size:12px;color:#425661}
  .vv-card.on{border:2px solid #149aa5;background:#f2fafb;padding:10px 12px}.vv-card b{font-size:13px;color:#1d3440}
  .vv-card .vv-pic{font:11px Consolas,monospace;color:#3d6370;background:#eef6f8;border-radius:6px;padding:5px 8px}
  .vv-list{border:1px solid #cfdde2;border-radius:8px;background:#fff;max-height:260px;overflow:auto}
  .vv-list label{display:grid;grid-template-columns:18px 1fr auto;gap:8px;align-items:center;padding:6px 10px;border-top:1px solid #edf2f4;font-size:12.5px}
  .vv-list label:first-child{border-top:0;background:#f2fafb;font-weight:800;color:#14576a}
  .vv-list label.is-dim{color:#8a9aa2}
 `;
 const two = (left, right) => `<div class="var-two"><div class="var-col">${left}</div><div class="var-col">${right}</div></div>`;
 const valuesF = (inner, note = '値の数だけファイルができます') => `<div class="var-f"><span class="var-l"><i>2</i>値<small>${note}</small></span>${inner}</div>`;
 const allNote = () => `<div class="vv-all"><span>値は指定しません。実行のたびに <b>${E(cond().name)}</b> に出てきた値ごとにファイルを作ります。</span><small class="vv-tip">値を先に知る必要がないので、取り方は「まとめて1回」になります。</small></div>`;
 const V = {
  A: { name: 'A「2 値」に2択の切替＋右列の見出しに「数える」', html: (c) => head() + method(true) + say(c) + two(
    item() + valuesF(seg2(true) + allNote(), '指定するか、出てきた値すべてか') + name() + place(),
    `<div class="vv-hd"><h4>できあがるファイル${c ? `（${C().values.length}）` : '（見込み）'}</h4>${countBtn(c)}</div>` +
    (c ? `${stamp()}${fileTable()}` : pending(`出てきた値の数だけファイルができます。いくつになるかは「出てくる値を数える」で確かめられます。<br>${countNote()}`))) },
  B: { name: 'B「2 値」をラジオの縦2択にし、数えた結果をその下に', html: (c) => head() + method(true) + say(c) + two(
    item() + valuesF(`<label class="vv-check"><input type="radio" name="vvb">指定した値だけ</label><label class="vv-check"><input type="radio" name="vvb" checked>出てきた値すべて（実行のたびに出てきた値ごと）</label>
     <div class="vv-all">${c ? stamp() : '<span>まだ数えていません。数えなくても実行できます。</span>'}<span>${countBtn(c)}</span>${countNote()}</div>`, '値の決め方') + name() + place(),
    `<h4 class="var-h">できあがるファイル${c ? `<span>（${C().values.length}）</span>` : ''}</h4>` + (c ? fileTable() : pending('数えると、ここに値ごとのファイルの名前と行数が並びます。'))) },
  C: { name: 'C 全幅の「見込み」帯（何ファイルになるか）＋「値を指定しない」チェック', html: (c) => head() + method(true) + say(c) +
    `<div class="vv-strip ${c ? '' : 'is-none'}"><span class="vv-k">見込み</span><span class="vv-sp">${c ? stamp() : '<span class="vv-stamp">まだ数えていません。数えなくても実行でき、出てきた値の数だけファイルを作ります。</span>'}</span>${countBtn(c)}</div>` + two(
    item() + valuesF(`<label class="vv-check"><input type="checkbox" checked>値を指定しない（出てきた値すべて）</label><div class="var-chips vv-dim" style="opacity:.45"><input placeholder="値を足す（Enter）" disabled></div>`) + name() + place(),
    `<h4 class="var-h">できあがるファイル</h4>` + (c ? fileTable() : pending('数えると、ここに値ごとのファイルの名前と行数が並びます。'))) },
  D: { name: 'D 値の欄に「出てきた値すべて」の札（チップ）を置き、横に「数える」', html: (c) => head() + method(true) + say(c) + two(
    item() + valuesF(`<div class="var-chips"><span class="vv-allchip">出てきた値すべて<button type="button" class="vv-link" style="color:#fff">×</button></span><input placeholder="値を指定する（Enter で足すと、指定した値だけになります）"></div>
      <span style="display:flex;gap:10px;align-items:center">${countBtn(c)}${c ? stamp() : '<span class="vv-tip">いくつのファイルになるかを確かめられます（数えなくても実行できます）</span>'}</span>`, '空なら出てきた値すべて。値を足すと、その値だけ') + name() + place(),
    `<h4 class="var-h">できあがるファイル${c ? `<span>（${C().values.length}）</span>` : ''}</h4>` + (c ? fileTable() : pending('出てきた値の数だけファイルができます。数えると、ここに並びます。'))) },
  E: { name: 'E 上の1文を「状態の帯」にし、ファイル数と数えるを1文の中に', html: (c) => head() + method(true) +
    `<div class="var-say" style="display:flex;align-items:center;gap:12px"><span style="flex:1"><b>${E(cond().name)}</b> の<b>出てきた値すべて</b>でファイルを作ります。${c ? `いまの条件では <b>${C().values.length}ファイル</b>（${N(C().rows)}件 · ${when()} に数えた）。` : 'いくつになるかは、まだ数えていません（数えなくても実行できます）。'}</span>${countBtn(c)}</div>` + two(
    item() + valuesF(seg2(true), '指定するか、出てきた値すべてか') + name() + place(),
    `<h4 class="var-h">できあがるファイル${c ? `<span>（${C().values.length}）</span>` : ''}</h4>` + (c ? fileTable() : pending('出てきた値の数だけファイルができます。'))) },
  F: { name: 'F（方向の違う案）手順を分ける: 値の決め方を2枚の札で選び、選んだ札の中で数える', html: (c) => head() + method(true) + two(
    item() + valuesF(`<div class="vv-cards"><div class="vv-card"><b>指定した値だけ</b><span>決めた値の数だけファイルを作る</span><span class="vv-pic">LS3 · LS4 → 2ファイル</span></div>
      <div class="vv-card on"><b>✓ 出てきた値すべて</b><span>実行のたびに出てきた値ごとに作る</span><span class="vv-pic">${c ? `いまの条件 → ${C().values.length}ファイル` : '? ファイル（数えると分かる）'}</span>${countBtn(c)}${c ? `<small class="vv-tip">${when()} に数えた · ${N(C().rows)}件</small>` : '<small class="vv-tip">数えなくても実行できます</small>'}</div></div>`, '値の決め方') + name() + place(),
    `<h4 class="var-h">できあがるファイル${c ? `<span>（${C().values.length}）</span>` : ''}</h4>` + (c ? fileTable() : pending('数えると、ここに値ごとのファイルの名前と行数が並びます。'))) },
  G: { name: 'G（方向の違う案）先に数えて一覧から選ぶ: 「すべて」の行を入れると出てきた値すべて', html: (c) => head() + method(true) + two(
    item() + valuesF(`<div class="vv-list"><label><input type="checkbox" checked><span>すべて（これから出てくる値も）</span><span class="vv-tip">${c ? `${C().values.length}値` : ''}</span></label>${c ? C().values.map(v => `<label class="is-dim"><input type="checkbox" checked disabled><span>${E(v.value)}</span><span class="vv-r">${N(v.rows)}件</span></label>`).join('') : `<label class="is-dim" style="grid-template-columns:1fr"><span>値の一覧は、数えると並びます。「すべて」を外すと、選んだ値だけになります。</span></label>`}</div>
      <span style="display:flex;gap:10px;align-items:center">${countBtn(c)}<span class="vv-tip">${c ? `${when()} に数えた（いまの条件）` : '数えなくても実行できます'}</span></span>`, 'いまの条件で出てくる値') + name() + place(),
    `<h4 class="var-h">できあがるファイル${c ? `<span>（${C().values.length}）</span>` : ''}</h4>` + (c ? fileTable() : pending('数えると、ここに値ごとのファイルの名前と行数が並びます。'))) },
 };
 async function show(k) {
  if (!P) await load();
  if (!document.getElementById('vv-css')) { const st = document.createElement('style'); st.id = 'vv-css'; st.textContent = CSS; document.head.appendChild(st); }
  const box = document.querySelector('.editor-pane[data-etab="variant"] .var-box');
  const v = V[k[0]], counted = k[1] === '2';
  box.innerHTML = v.html(counted);
  // 数える前は見込みの道が無いので、表は数えたときだけ出る（P.files は数えた控えから来る）
 }
 window.VV = { show, V, load };
})();
