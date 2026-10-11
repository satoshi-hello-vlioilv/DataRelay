// 2.1.1 編集画面のタブの順番と、「値ごとに分ける」の取り方（まとめて1回・値ごとに並列）を選ぶ場所の案（CLAUDE.md §3）。
// 本物の編集画面（6値の対象を開いた状態）に、案ごとにタブの並べ替え・見出し・取り方の部品を当てて再現する。
// 撮り方: 撮影用の仕掛けで window.TO.show(k)。1回目 A〜G（5案＋方向の違う2案 E・F）、2回目は組合せ案 H〜K。
(() => {
 const NAMES = { basic: ['基本と入出力', '名称・RNE・出力先'], period: ['抽出期間', '動的な日付指定'], variant: ['値ごとに分ける', '条件の値ごとに別ファイル'],
  naming: ['ファイル名', '形式・命名パターン'], schedule: ['自動実行', 'スケジュール'] };
 const OPTS = [['default', '既定に従う', 'いまは まとめて1回'], ['combined', 'まとめて1回', '問い合わせ1回 · 受け取ってから分ける'], ['parallel', '値ごとに並列', '値ごとに同時に問い合わせ · 最大6本']];
 const radios = (cls) => `<div class="${cls}">${OPTS.map(([k, b, s], i) => `<label class="${i === 0 ? 'on' : ''}"><input type="radio" name="to-m" ${i === 0 ? 'checked' : ''}><b>${b}</b><small>${s}</small></label>`).join('')}</div>`;
 // 取り方の部品: M1 = 入切のすぐ下に横並び、M2 = 左の欄の5番目、M3 = 右の「できあがるファイル」の上に今の取り方を1行で（押すと選べる）
 const M = {
  M1: () => `<div class="to-method to-m1"><span class="to-ml">取り方</span>${radios('to-seg')}</div>`,
  M2: () => `<div class="var-f to-m2"><span class="var-l"><i>5</i>取り方<small>速い方を選べます。既定は共通設定の「抽出方式」で決めます</small></span>${radios('to-list')}</div>`,
  M4: () => `<div class="to-m4"><div class="to-m4h"><span class="to-ml">取り方</span><small>問い合わせ1回 → 受け取ってから6ファイルに分けます</small></div>${radios('to-pills')}</div>`,
  M3: () => `<div class="to-m3"><span class="to-ml">取り方</span><b>まとめて1回</b><small>既定に従う · 問い合わせ1回で ${6}ファイル</small><button type="button" class="textbtn">変える ›</button></div>`,
 };
 const V = {
  A: { name: 'A 流れ順（基本→期間→値ごと→ファイル名→自動実行）＋取り方は入切の下', order: ['basic', 'period', 'variant', 'naming', 'schedule'], m: 'M1' },
  B: { name: 'B ファイル名の隣（基本→ファイル名→値ごと→期間→自動実行）＋入切の下', order: ['basic', 'naming', 'variant', 'period', 'schedule'], m: 'M1' },
  C: { name: 'C ファイル名のあと（基本→期間→ファイル名→値ごと→自動実行）＋入切の下', order: ['basic', 'period', 'naming', 'variant', 'schedule'], m: 'M1' },
  D: { name: 'D 段の見出し（取り出す｜分けて名付ける｜動かす）＋取り方は左の欄の5番目', order: ['basic', 'period', 'variant', 'naming', 'schedule'], m: 'M2',
   groups: [['取り出す', 2], ['分けて名付ける', 2], ['動かす', 1]] },
  G: { name: 'G 矢印でつなぐ手順（基本→期間→値ごと→ファイル名→自動実行）＋取り方は右の上に1行', order: ['basic', 'period', 'variant', 'naming', 'schedule'], m: 'M3', arrows: true },
  E: { name: 'E （方向違い）値ごとをファイル名のタブへ入れる（基本→期間→ファイル名と分け方→自動実行）', order: ['basic', 'period', 'naming', 'schedule'], m: 'M1', merge: true },
  F: { name: 'F （方向違い）使うときだけタブを出す（切なら基本の札だけ。入なら基本の次に出る）＋右の上に1行', order: ['basic', 'variant', 'period', 'naming', 'schedule'], m: 'M3', onlyOn: true },
  // 2回目の組合せ案（1回目の上位 A・G・C のエッセンス: 抽出の条件をまとめる順、今の取り方と結果を言葉で、ファイル名のあとに置く順）
  H: { name: 'H A の順＋入切の下で選ぶ＋上の1文に取り方と結果', order: ['basic', 'period', 'variant', 'naming', 'schedule'], m: 'M1', say: true },
  I: { name: 'I H＋タブに細い区切り（取り出す条件｜出す形｜動かす）', order: ['basic', 'period', 'variant', 'naming', 'schedule'], m: 'M1', say: true, dividers: [3, 4] },
  J: { name: 'J C の順（基本→期間→ファイル名→値ごと→自動実行）＋入切の下＋1文', order: ['basic', 'period', 'naming', 'variant', 'schedule'], m: 'M1', say: true },
  K: { name: 'K A の順＋右上に取り方の札（3つから選ぶ＋結果の見込み）', order: ['basic', 'period', 'variant', 'naming', 'schedule'], m: 'M4', say: true },
 };
 const CSS = `
  .to-method{display:flex;align-items:center;gap:10px;margin:2px 0 8px}.to-ml{font-size:11.5px;font-weight:800;color:#3e5964;flex:none}
  .to-seg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;border:1px solid #c9d8de;border-radius:9px;overflow:hidden;flex:1}
  .to-seg label{display:grid;gap:1px;padding:5px 10px;cursor:pointer;border-left:1px solid #dbe5e9;background:#fff}.to-seg label:first-child{border-left:0}
  .to-seg label.on{background:#e3f3f5;box-shadow:inset 0 -2px 0 #149aa5}.to-seg input{display:none}.to-seg b{font-size:12px;color:#1d3440}.to-seg small{font-size:10.5px;color:#60757c}
  .to-list{display:grid;gap:4px}.to-list label{display:grid;grid-template-columns:auto 1fr;column-gap:7px;align-items:center;padding:4px 8px;border:1px solid #dbe5e9;border-radius:8px;background:#fff}
  .to-list label.on{border-color:#7cc3cc;background:#eef8f9}.to-list input{grid-row:span 2}.to-list b{font-size:12px}.to-list small{font-size:10.5px;color:#60757c}
  .to-m3{display:flex;align-items:baseline;gap:8px;padding:7px 10px;margin:0 0 8px;border:1px solid #cfe2e7;border-radius:9px;background:#f3fafb}.to-m3 b{font-size:13px;color:#14576a}.to-m3 small{font-size:10.5px;color:#60757c;flex:1}
  .to-m4{display:grid;gap:5px;padding:8px 10px;margin:0 0 8px;border:1px solid #cfe2e7;border-radius:9px;background:#f3fafb}.to-m4h{display:flex;gap:8px;align-items:baseline}.to-m4h small{font-size:10.5px;color:#46636d}
  .to-pills{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.to-pills label{display:grid;padding:4px 8px;border:1px solid #d3e0e5;border-radius:7px;background:#fff}.to-pills label.on{border-color:#149aa5;background:#e3f3f5;box-shadow:inset 0 0 0 1px #149aa5}.to-pills input{display:none}.to-pills b{font-size:12px}.to-pills small{font-size:10px;color:#60757c}
  .to-div{width:1px;align-self:stretch;margin:6px 2px;background:#c3d2d8}
  .to-grp{display:flex;flex-direction:column;gap:3px}.to-grp>em{font-style:normal;font-size:10px;font-weight:800;color:#6b818a;letter-spacing:.04em;padding-left:4px}.to-grp>div{display:flex;gap:6px}
  .editor-tabs.to-arrows .editor-tab:not(.etab-tool):not(:last-of-type)::after{content:'›';position:absolute;right:-9px;top:50%;transform:translateY(-50%);font:800 16px/1 sans-serif;color:#9fb3ba}
  .editor-tabs.to-arrows .editor-tab{position:relative}
 `;
 function style() { let s = document.getElementById('to-style'); if (!s) { s = document.createElement('style'); s.id = 'to-style'; document.head.appendChild(s) } s.textContent = CSS }
 function show(k) {
  style(); const v = V[k], bar = document.querySelector('#editor .editor-tabs'), sep = bar.querySelector('.editor-tabsep');
  const tab = id => bar.querySelector(`.editor-tab[data-etab="${id}"]`);
  Object.keys(NAMES).forEach(id => { tab(id).hidden = !v.order.includes(id) });
  if (v.groups) {
   let i = 0; v.groups.forEach(([label, n]) => { const g = document.createElement('div'); g.className = 'to-grp'; g.innerHTML = `<em>${label}</em><div></div>`; v.order.slice(i, i + n).forEach(id => g.lastChild.appendChild(tab(id))); i += n; bar.insertBefore(g, sep) });
  } else v.order.forEach(id => bar.insertBefore(tab(id), sep));
  v.order.forEach((id, i) => { tab(id).querySelector('.etab-badge').textContent = i + 1 });
  (v.dividers || []).forEach(n => { const d = document.createElement('span'); d.className = 'to-div'; bar.insertBefore(d, tab(v.order[n])) });
  if (v.say) document.querySelector('#m-var-say').innerHTML = '<b>BOX実績_設備名</b> の <b>LS4・LS3・DL2・TLV・CAL・FS4</b> を<b>まとめて1回</b>で問い合わせ、受け取ってから値ごとに分けて <b>6ファイル</b> を作ります。';
  if (v.merge) { tab('naming').querySelector('b').textContent = 'ファイル名と分け方'; tab('naming').querySelector('small').textContent = '形式・命名・値ごとに分ける' }
  bar.classList.toggle('to-arrows', !!v.arrows);
  const box = document.querySelector('.var-box');
  if (v.m === 'M1') document.querySelector('#m-var-say').insertAdjacentHTML('beforebegin', M.M1());
  if (v.m === 'M2') document.querySelector('.var-col').insertAdjacentHTML('beforeend', M.M2());
  if (v.m === 'M4') document.querySelector('.var-col+.var-col .var-h').insertAdjacentHTML('beforebegin', M.M4());
  if (v.m === 'M3') document.querySelector('.var-col+.var-col .var-h').insertAdjacentHTML('beforebegin', M.M3());
  if (v.merge) {
   const pane = document.querySelector('.editor-pane[data-etab="naming"]'); pane.insertAdjacentHTML('beforeend', '<h3 class="to-sec" style="margin:14px 0 6px;font-size:13px">値ごとに分ける</h3>'); pane.appendChild(box);
   setEditorTab('naming'); pane.scrollIntoView({ block: 'end' }); box.scrollIntoView({ block: 'end' });
  } else setEditorTab('variant');
 }
 window.TO = { V, show };
})();
