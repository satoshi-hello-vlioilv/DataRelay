// 2.10.0 共通設定（読取マスタ・ファイル結合・Power Query）の道具の段とスクロールを、対象ファイルの画面（2.9.0）と同じ考えで詰める案（CLAUDE.md §3）。
// いま: 下の段の切り替えの下に「検索（幅いっぱい）・新規作成・書き出し／形式／取り込み」の1段。一覧の高さは画面の高さから決め打ち
// （100vh - 320px）で、編集が長いと画面全体（section）がスクロールし、左の一覧ごと流れてがたつく（1536 で 46〜157px）。
// 本物の画面（撮影用の環境に 読取マスタ35件・結合8件・クエリ6件）の DOM を案ごとに組み替える。部品（検索欄・ボタン）は本物を動かして使う。
// 撮り方: await window.TM.show(k, view)。view 1 = 読取マスタ（固定長を開いた）、2 = 読取マスタ（区切りを開いた）、
// 3 = ファイル結合（1件を開いた）、4 = Power Query、5 = 基本設定。
(() => {
 const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
 const svg = (d, w = 15) => `<svg viewBox="0 0 24 24" width="${w}" height="${w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
 const IC = {
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  io: '<path d="M7 4v13M3.5 13.5L7 17l3.5-3.5M17 20V7M13.5 10.5L17 7l3.5 3.5"/>',
  down: '<path d="M6 9.5l6 6 6-6"/>',
  filter: '<path d="M4 5h16l-6.2 7.4V19l-3.6-1.8v-4.8z"/>',
  back: '<path d="M14.5 6l-6 6 6 6"/>',
  list: '<path d="M4 6h16M4 12h16M4 18h10"/>',
 };
 const SEC = { layouts: { add: '#lay-add', search: '#lay-search', noun: '読取マスタ' }, joins: { add: '#jn-add', search: '#jn-search', noun: '結合マスタ' }, mqueries: { add: '#mq-add', search: '#mq-search', noun: 'クエリ' } };
 const CSS = `
 /* 共通: 画面全体はスクロールさせない。一覧と編集は、それぞれの枠の中だけで送る */
 body.tm main>#layouts.on,body.tm main>#joins.on,body.tm main>#mqueries.on{display:flex!important;flex-direction:column;overflow:hidden!important;padding-bottom:8px}
 body.tm section.on>.commandbar{display:none!important}
 body.tm .lay-wrap,body.tm .jn-wrap{flex:1 1 auto;min-height:0;align-items:stretch;margin-top:6px}
 body.tm .ml-pane{display:flex;flex-direction:column;min-height:0}
 body.tm .ml-list{flex:1;min-height:0;display:flex;flex-direction:column}
 body.tm .ml-scroll{max-height:none!important;flex:1;min-height:0}
 body.tm .lay-wrap>.panel,body.tm .jn-wrap>.panel{margin:0;min-height:0;max-height:100%;overflow:auto;align-self:stretch}
 body.tm .lay-wrap>.lay-empty,body.tm .jn-wrap>.lay-empty{align-self:start}
 body.tm .subnav{margin:6px 0 0!important}
 /* 作る前の採点で全案に共通の直し: 基本設定の左の枠を一覧と同じ幅に（切り替えても左端と境目が動かない）。
    ファイル結合の［削除］を［保存］の隣から離す（読取マスタと同じく下に文字で） */
 body.tm .settings-shell{grid-template-columns:330px minmax(0,1fr);gap:10px}
 body.tm #paths.on{padding-top:6px}
 body.tm .jn-edit .lay-foot{flex-wrap:wrap}
 body.tm .jn-edit #jn-delete{order:9;flex-basis:100%;text-align:right;background:transparent;color:#a4463d;font-size:12px;padding:4px 0 0;border-top:1px dashed #e3ebee;border-radius:0}
 .tm-ic{height:28px;width:28px;display:inline-grid;place-items:center;padding:0;border-radius:7px;background:#fff;border:1px solid #c8d6dc;color:#4f6873}
 .tm-ic:hover{background:#f1f7f9;filter:none}
 .tm-add{height:28px;display:inline-flex;align-items:center;gap:5px;padding:0 10px;border-radius:7px;background:#0b6577;color:#fff;font-size:12px;font-weight:700;border:0;white-space:nowrap}
 .tm-btn{height:28px;display:inline-flex;align-items:center;gap:5px;padding:0 10px;border-radius:7px;background:#fff;color:#2b4b59;border:1px solid #c8d6dc;font-size:12px;font-weight:700;white-space:nowrap}
 .tm-btn small{font-weight:600;color:#7f929a;font-size:11px}
 /* 一覧の見出しに道具を置くとき: 1段目 名前・件数・道具、2段目 種類の札 */
 body.tm-head .ml-head{flex-wrap:wrap;align-items:center;row-gap:6px}
 body.tm-head .ml-head .tm-tools{margin-left:auto;display:flex;gap:4px}
 body.tm-head .ml-chips-slot{order:9;flex-basis:100%;margin-left:0}
 /* 下の段の右に道具を置くとき */
 body.tm-sub .subnav{align-items:center}
 .tm-subtools{margin-left:auto;display:flex;align-items:center;gap:6px;padding-right:3px}
 .tm-subtools .tm-search{display:flex;align-items:center;gap:6px;height:28px;border:1px solid #c8d6dc;border-radius:7px;background:#fff;padding:0 8px;color:#6b7f88;width:200px}
 .tm-subtools .tm-search input{border:0;height:26px;padding:0;font-size:12px;outline:0!important}
 /* 対象ファイルと同じ1段 */
 .tm-bar{display:flex;align-items:center;gap:8px;height:40px;margin:6px 0 0;flex:none}
 .tm-bar .sp{flex:1}
 /* 編集の見出しを上に残す */
 body.tm-sticky .lay-head{position:sticky;top:-14px;z-index:4;background:#fff;margin:-14px -16px 0;padding:12px 16px 8px;border-bottom:1px solid #e6eef0}
 body.tm-sticky .jn-edit>.fieldgrid:first-child{position:sticky;top:-14px;z-index:4;background:#fff;margin:-14px -16px 0;padding:12px 16px 8px;border-bottom:1px solid #e6eef0}
 /* 詰める */
 body.tm-dense .lay-edit,body.tm-dense .jn-edit{padding:10px 14px;gap:7px}
 body.tm-dense .lay-edit input,body.tm-dense .lay-edit select,body.tm-dense .jn-edit input,body.tm-dense .jn-edit select{height:30px}
 body.tm-dense .lay-col input,body.tm-dense .lay-col select{height:28px}
 body.tm-dense .lay-cols{gap:3px}
 body.tm-dense .sectiontitle{padding:4px 0 4px;margin-bottom:4px}
 body.tm-dense.tm-sticky .lay-head{top:-10px;margin:-10px -14px 0;padding:8px 14px 6px}
 /* たたむ */
 details.tm-fold{border:1px solid #e3ebee;border-radius:8px;padding:0 10px;background:#fbfdfd}
 details.tm-fold>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;height:34px;font-size:12px;font-weight:900;color:#305265}
 details.tm-fold>summary::before{content:'▸';color:#0b6577}
 details.tm-fold[open]>summary::before{content:'▾'}
 details.tm-fold>summary small{font-weight:600;color:#7f929a}
 /* 一覧を畳む（選ぶ欄） */
 body.tm-combo .lay-wrap,body.tm-combo .jn-wrap{grid-template-columns:minmax(0,1fr)!important}
 body.tm-combo .ml-pane{display:none!important}
 .tm-combo-box{display:flex;align-items:center;gap:8px;height:36px;padding:0 10px;border:1px solid #0b6577;border-radius:8px;background:#fff;font-weight:800;color:#17384e;margin:6px 0 0;flex:none;box-shadow:0 0 0 3px #e3f2f5}
 .tm-combo-box .sp{flex:1}.tm-combo-box small{color:#6b7f88;font-weight:600}
 /* 手順を分ける（一覧の画面 → 編集の画面） */
 body.tm-two .lay-wrap,body.tm-two .jn-wrap{grid-template-columns:minmax(0,1fr)!important}
 body.tm-two.tm-editing .ml-pane{display:none!important}
 body.tm-two:not(.tm-editing) .lay-wrap>.panel,body.tm-two:not(.tm-editing) .jn-wrap>.panel{display:none!important}
 .tm-crumb{display:flex;align-items:center;gap:8px;height:36px;margin:6px 0 0;flex:none;font-size:12px;color:#4f6873}
 .tm-crumb b{color:#17384e;font-size:13px}
 `;
 const st = () => { if (!$('#tm-style')) document.head.insertAdjacentHTML('beforeend', `<style id="tm-style">${CSS}</style>`); };
 const cur = () => Object.keys(SEC).find(k => $('#' + k)?.classList.contains('on')) || '';
 const count = sec => $(`#${sec} .ml-count`)?.textContent || '';
 const ioBtn = (label = '出し入れ') => `<button type="button" class="tm-btn" title="書き出し・取り込み（EXCEL・JSON）">${svg(IC.io, 14)}${label}${svg(IC.down, 12)}</button>`;
 const addBtn = (sec, label = '新規作成') => `<button type="button" class="tm-add" data-tm-add="${sec}">${svg(IC.plus, 14)}${label}</button>`;
 function wire(root) { root.querySelectorAll('[data-tm-add]').forEach(b => b.onclick = () => $(SEC[b.dataset.tmAdd].add).click()); }
 // 道具を一覧の見出しへ（虫眼鏡・出し入れ・新規）
 function toolsInHead(sec, opt = {}) {
  const head = $(`#${sec} .ml-head`); if (!head || head.querySelector('.tm-tools')) return;
  const t = document.createElement('span'); t.className = 'tm-tools';
  t.innerHTML = `<button type="button" class="tm-ic" title="検索（Ctrl+F）">${svg(IC.search, 14)}</button><button type="button" class="tm-ic" title="書き出し・取り込み">${svg(IC.io, 14)}</button>${addBtn(sec, opt.addLabel || '新規')}`;
  head.querySelector('.ml-count').after(t); wire(t);
 }
 // 道具を下の段の右へ
 function toolsInSub(sec, opt = {}) {
  const sub = $('#subnav'); if (!sub || !sec) return;
  sub.querySelector('.tm-subtools')?.remove();
  const t = document.createElement('span'); t.className = 'tm-subtools';
  t.innerHTML = (opt.search ? `<label class="tm-search">${svg(IC.search, 13)}<input placeholder="${SEC[sec].noun}を検索"></label>` : `<button type="button" class="tm-ic" title="検索（Ctrl+F）">${svg(IC.search, 14)}</button>`)
   + ioBtn() + addBtn(sec);
  sub.append(t); wire(t);
 }
 // 対象ファイルと同じ1段（件数・絞り込み・出し入れ・新規作成）
 function toolsBar(sec) {
  const s = $('#' + sec); if (!s || s.querySelector('.tm-bar')) return;
  const b = document.createElement('div'); b.className = 'tm-bar';
  const kinds = sec === 'layouts' ? 'すべて' : 'すべて';
  b.innerHTML = `<span class="jb-count"><b>${count(sec).replace('件', '')}<small>件</small></b></span><button type="button" class="tbtn">${svg(IC.filter, 14)}絞り込み<small>${kinds}</small>${svg(IC.down, 13)}</button><span class="sp"></span><button type="button" class="tbtn icon" title="検索（Ctrl+F）">${svg(IC.search, 15)}</button>${ioBtn().replace('tm-btn', 'tbtn')}${addBtn(sec).replace('tm-add', 'tbtn add')}`;
  s.querySelector('.commandbar').after(b); wire(b);
  if (sec === 'layouts') { const slot = $('#layouts .ml-chips-slot'); if (slot) { slot.style.display = 'none'; } }
 }
 function fold(sel, title, note) {
  const box = $(sel); if (!box || box.closest('details')) return;
  const head = box.previousElementSibling?.classList.contains('sectiontitle') ? box.previousElementSibling : null;
  const d = document.createElement('details'); d.className = 'tm-fold';
  d.innerHTML = `<summary>${title}<small>${note || ''}</small></summary>`;
  box.before(d); if (head) head.remove(); d.append(box);
 }
 function combo(sec) {
  const s = $('#' + sec); if (!s || s.querySelector('.tm-combo-box')) return;
  const name = $(`#${sec} .ml-row.on .ml-name`)?.textContent || `${SEC[sec].noun}を選ぶ`;
  const c = document.createElement('div'); c.className = 'tm-combo-box';
  c.innerHTML = `${svg(IC.list, 15)}<span>${name}</span><span class="sp"></span><small>${count(sec)}から選ぶ</small>${svg(IC.down, 14)}`;
  s.querySelector('.commandbar').after(c);
 }
 function crumb(sec, editing) {
  const s = $('#' + sec); if (!s || s.querySelector('.tm-crumb')) return;
  const c = document.createElement('div'); c.className = 'tm-crumb';
  const name = $(`#${sec} .ml-row.on .ml-name`)?.textContent || '';
  c.innerHTML = editing && name ? `<button type="button" class="tm-btn">${svg(IC.back, 14)}${SEC[sec].noun}の一覧（${count(sec)}）</button><b>${name}</b>`
   : `<b>${SEC[sec].noun}</b><span>${count(sec)}</span>`;
  s.querySelector('.commandbar').after(c);
  document.body.classList.toggle('tm-editing', !!(editing && name));
 }
 const base = (...cls) => { document.body.classList.add('tm', ...cls); };
 const P = {
  // A: 道具を一覧の見出しへ（虫眼鏡・出し入れ・新規）。上の段は無くす。一覧と編集はそれぞれの枠で送る
  A: v => { base('tm-head'); const s = cur(); if (s) toolsInHead(s); },
  // B: 道具を下の段（基本設定・読取マスタ…の切り替え）の右へ。編集の見出しは上に残す
  B: v => { base('tm-sub', 'tm-sticky'); toolsInSub(cur()); },
  // C: 対象ファイルと同じ1段（件数・絞り込み・虫眼鏡・出し入れ・新規作成）。種類の札は絞り込みへ
  C: v => { base(); const s = cur(); if (s) toolsBar(s); },
  // D: A ＋ 編集の見出しを上に残す ＋ 編集を詰めて、1728 では送らずに収める
  D: v => { base('tm-head', 'tm-sticky', 'tm-dense'); const s = cur(); if (s) toolsInHead(s); },
  // E: B ＋ 「できあがり」「組み立てたSQL」をたたむ（開けば見える）。編集が縦に短くなる
  E: v => { base('tm-sub', 'tm-sticky'); toolsInSub(cur()); fold('#lay-preview-result', '③ できあがり（見本の先頭）', '開くと見本の先頭を出します'); fold('#jn-preview', 'できあがりを見る', '開くと先頭の行を出します'); },
  // F（方向が違う）: 一覧の枠をやめ、上の選ぶ欄（検索つき）で選ぶ。編集が全幅になり、送らずに収まる
  F: v => { base('tm-sub', 'tm-combo'); const s = cur(); toolsInSub(s); if (s && v !== 4) combo(s); if (v === 4) document.body.classList.remove('tm-combo'); },
  // G（方向が違う）: 手順を分ける。一覧の画面（全幅）→ 開くと編集だけの画面（← 一覧へ）。どちらも1枚で送りが1か所
  G: v => { base('tm-sub', 'tm-two'); const s = cur(); toolsInSub(s); if (s) crumb(s, v !== 4); },
 };
 /* ---- 2回目: 上位3案 D・B・C ＋ 組合せ案 H〜K ----
    1回目で全案に残った欠点も直す: 編集の段の間が縦に間延びする（枠の高さに合わせて段が引き伸ばされる → 上詰め）／
    1536 で列の表が2〜3行しか見えない（編集を詰める）／出し入れがアイコンだけ（文字と▾）／件数が2か所／
    種類の無いファイル結合・Power Query にも絞り込みが出る（種類があるときだけ） */
 const CSS2 = `
 body.tm-fix .lay-edit,body.tm-fix .jn-edit{align-content:start}
 body.tm-fix .lay-edit{gap:8px}
 body.tm-nohead .ml-head{display:none}
 .tm-subtools .tm-add{height:28px}
 body.tm-tabs .tm-tabbar{display:flex;align-items:flex-end;gap:2px;border-bottom:1px solid #dbe4e9;margin-top:4px}
 body.tm-tabs .tm-tabbar button{height:32px;padding:0 14px;background:transparent;color:#5d7681;font-size:12.5px;font-weight:800;border-radius:7px 7px 0 0;border:1px solid transparent;border-bottom:0;display:inline-flex;align-items:center;gap:7px}
 body.tm-tabs .tm-tabbar button.on{background:#fff;color:#0b4f5c;border-color:#dbe4e9;margin-bottom:-1px}
 body.tm-tabs .tm-tabbar button i{font-style:normal;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:#0b6577;color:#fff;font-size:11px}
 body.tm-tabs .tm-tabbar button small{font-weight:700;color:#7f929a}
 body.tm-tabs .tm-tabbar .sp{flex:1}
 body.tm-tabs .tm-tabbar .note{font-size:11px;color:#0b6570;background:#eaf6f9;border-radius:6px;padding:2px 8px;margin-bottom:5px}
 body.tm-tabs .tm-hide{display:none!important}
 `;
 const st2 = () => { st(); if (!$('#tm-style2')) document.head.insertAdjacentHTML('beforeend', `<style id="tm-style2">${CSS2}</style>`); };
 const hasKinds = sec => sec === 'layouts';
 const filterBtn = cls => `<button type="button" class="${cls}" aria-haspopup="true">${svg(IC.filter, 14)}絞り込み<small>すべて</small>${svg(IC.down, 13)}</button>`;
 // 下の段の右に、対象ファイルと同じ形の道具（絞り込みは種類があるときだけ・件数は一覧の見出しに1か所）
 function subTools2(sec) {
  const sub = $('#subnav'); if (!sub || !sec) return;
  sub.querySelector('.tm-subtools')?.remove();
  const t = document.createElement('span'); t.className = 'tm-subtools';
  t.innerHTML = (hasKinds(sec) ? filterBtn('tm-btn') : '') + `<button type="button" class="tm-ic" title="検索（Ctrl+F）">${svg(IC.search, 14)}</button>` + ioBtn() + addBtn(sec);
  sub.append(t); wire(t);
  if (hasKinds(sec)) { const slot = $('#layouts .ml-chips-slot'); if (slot) slot.style.display = 'none'; }
 }
 // 対象ファイルと同じ1段を、一覧の見出しの代わりに置く（件数は1か所・種類は絞り込みへ）
 function bar2(sec) {
  const s = $('#' + sec); if (!s || s.querySelector('.tm-bar')) return;
  const b = document.createElement('div'); b.className = 'tm-bar';
  b.innerHTML = `<span class="jb-count"><b>${count(sec).replace('件', '')}<small>件</small></b><span>${SEC[sec].noun}</span></span>${hasKinds(sec) ? filterBtn('tbtn') : ''}<span class="sp"></span><button type="button" class="tbtn icon" title="検索（Ctrl+F）">${svg(IC.search, 15)}</button>${ioBtn().replace('tm-btn', 'tbtn')}${addBtn(sec).replace('tm-add', 'tbtn add')}`;
  s.querySelector('.commandbar').after(b); wire(b);
 }
 // 編集の ② と ③ をタブにする（列の表が編集の高さを全部使える）
 function tabs(sec) {
  const ed = sec === 'layouts' ? $('#lay-edit') : sec === 'joins' ? $('#jn-edit') : null; if (!ed || ed.querySelector('.tm-tabbar')) return;
  const titles = [...ed.querySelectorAll(':scope > .sectiontitle')];
  const [t2, t3] = sec === 'layouts' ? [titles[1], titles[2]] : [titles[1], titles[2]];
  if (!t2 || !t3) return;
  const kids = [...ed.children], i2 = kids.indexOf(t2), i3 = kids.indexOf(t3);
  const part3 = kids.slice(i3 + 1).filter(x => !x.classList.contains('lay-remove') && !x.classList.contains('lay-foot'));
  const note = t2.querySelector('.lay-cols-badge,.jn-col-mode,.lay-badge,span:last-child');
  const bar = document.createElement('div'); bar.className = 'tm-tabbar';
  const n2 = sec === 'layouts' ? '切り出す列' : '出す列', n3 = sec === 'layouts' ? 'できあがり' : 'できあがりを見る';
  const cnt = sec === 'layouts' ? `${ed.querySelectorAll('#lay-cols .lay-col').length}列` : '';
  bar.innerHTML = `<button type="button" class="on"><i>2</i>${n2}<small>${cnt}</small></button><button type="button"><i>3</i>${n3}<small>見本の先頭</small></button><span class="sp"></span>`;
  t2.before(bar); if (note && sec === 'layouts') { note.classList.add('note'); bar.append(note); }
  t2.classList.add('tm-hide'); t3.classList.add('tm-hide'); part3.forEach(x => x.classList.add('tm-hide'));
 }
 Object.assign(P, {
  // H = C の形（絞り込み・虫眼鏡・出し入れ・新規作成）を B の置き場所（下の段の右）へ。段を足さない。件数は一覧の見出しに1か所。
  //     編集は上詰め・詰める・見出しを上に残す
  H: v => { base('tm-fix', 'tm-sub', 'tm-sticky', 'tm-dense'); subTools2(cur()); },
  // I = C の1段を一覧の見出しの代わりに置く（件数・絞り込み・虫眼鏡・出し入れ・新規作成）。一覧は行から始まる。上詰め・詰める・見出しを上に残す
  I: v => { base('tm-fix', 'tm-nohead', 'tm-sticky', 'tm-dense'); const s = cur(); if (s) bar2(s); },
  // J = D（道具を一覧の見出しへ）＋ 出し入れを文字と▾に・新規作成を濃い色で ＋ 上詰め
  J: v => {
   base('tm-fix', 'tm-head', 'tm-sticky', 'tm-dense'); const s = cur(); if (!s) return;
   const head = $(`#${s} .ml-head`); if (!head || head.querySelector('.tm-tools')) return;
   const t = document.createElement('span'); t.className = 'tm-tools';
   t.innerHTML = `<button type="button" class="tm-ic" title="検索（Ctrl+F）">${svg(IC.search, 14)}</button>${ioBtn()}${addBtn(s, '新規')}`;
   head.querySelector('.ml-count').after(t); wire(t);
  },
  // K = H ＋ 編集の「② 列」と「③ できあがり」をタブに（列の表が編集の高さを使える。見本は押せば見える）
  K: v => { base('tm-fix', 'tm-sub', 'tm-sticky', 'tm-dense', 'tm-tabs'); const s = cur(); subTools2(s); if (s) tabs(s); },
 });
 window.TM = { keys: Object.keys(P), show(k, v) { st2(); P[k](v); return true; } };
})();
