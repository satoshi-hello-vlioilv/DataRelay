// 2.9.0 上部のメニューまわり（アプリの帯・画面の切り替え・対象ファイルの道具の段・左右の余白）を詰め直す案（CLAUDE.md §3）。
// いま: 帯 68px → タブ 55px → 検索の段 → 件数と操作の2行 → 実行キューの段 と積まれ、表の見出しが 1728 で上から約24%、
// 確認待ちの知らせが出ると約43%（1536 では約57%）まで下がる。左右の余白は 1728 で約63px。検索欄はほとんど使わない。
// 本物の画面（撮影用の環境に対象30件・うち25件が確認待ち）の DOM を案ごとに組み替える。本物の部品（選ぶ欄・ボタン・
// 知らせの帯）はそのまま動かして使うので、押したときの働きは本物と同じ。
// 撮り方: window.TB.show(k, view)。view 1 = 対象ファイル（通常）、2 = 確認待ちの知らせあり、3 = 共通設定、4 = 3件を選んだところ。
(() => {
 const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const svg = (d, w = 16) => `<svg viewBox="0 0 24 24" width="${w}" height="${w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
 const IC = {
  jobs: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  viewer: '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9.5h17M9.5 9.5V20"/>',
  paths: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M5.5 18.5l2.1-2.1M16.4 7.6l2.1-2.1"/>',
  logs: '<path d="M6 3.5h9l3.5 3.5v13.5H6z"/><path d="M9 11h7M9 15h7"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  filter: '<path d="M4 5h16l-6.2 7.4V19l-3.6-1.8v-4.8z"/>',
  view: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M9 4.5v15M15 4.5v15"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  warn: '<path d="M12 4l9 16H3z"/><path d="M12 10v4.5M12 17.4v.1"/>',
  down: '<path d="M6 9.5l6 6 6-6"/>',
  right: '<path d="M9.5 6l6 6-6 6"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  out: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  more: '<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>',
 };
 const CSS = `
 body.tb{--g:16px}
 body.tb>main{width:calc(100vw - var(--g)*2)!important;max-width:none!important}
 body.tb .appbar,body.tb footer{padding-left:var(--g)!important;padding-right:var(--g)!important}
 /* 帯の共通: 低く・状態は1行 */
 body.tb .appbar{min-height:0!important;height:var(--bar-h,46px);padding-top:0!important;padding-bottom:0!important;gap:12px;--ctl-h:32px;--ctl-r:8px}
 body.tb .brand{margin-right:0;flex:none}
 body.tb .brand h1{font-size:17px;letter-spacing:.01em}
 body.tb .brand-title{align-items:center;gap:8px}
 body.tb .version-badge{padding:2px 8px;font-size:10px}
 body.tb .appbar-tools{margin-left:auto;gap:8px}
 body.tb .runtime{min-width:0;padding:0 11px;gap:7px}
 body.tb .rt-text{display:flex!important;align-items:baseline;gap:7px}
 body.tb .rt-text b{font-size:12px}
 body.tb .rt-text span{display:inline!important;font-size:11px}
 body.tb .ctl{font-size:12px}
 body.tb .ctl-group.tb-split{border:0;background:transparent;gap:6px;overflow:visible}
 body.tb .ctl-group.tb-split .ctl{border:1px solid var(--ctl-edge);border-radius:var(--ctl-r);box-shadow:none}
 body.tb .ctl-group.tb-split #run-all{border-color:transparent}
 body.tb .tb-hidden{display:none!important}
 /* 頭 one: タブを帯の中へ */
 body.tb-h-one .appbar>nav{margin:0;border:0;align-self:stretch;display:flex;gap:2px;min-height:0;padding-left:10px;margin-left:6px;border-left:1px solid #ffffff22}
 body.tb-h-one .appbar>nav button{color:#a9c7d2;padding:0 14px;border-radius:0;border-bottom:3px solid transparent;border-top:3px solid transparent;font-size:13px;height:100%;background:transparent}
 body.tb-h-one .appbar>nav button:hover{color:#fff;background:#ffffff0d}
 body.tb-h-one .appbar>nav button.on{color:#fff;border-bottom-color:#3fd0c9;background:#ffffff14}
 /* 頭 two: 帯とタブの2段、どちらも低く */
 body.tb-h-two{--bar-h:42px}
 body.tb-h-two main>nav{margin:0 0 6px!important;min-height:0!important;height:36px;border-bottom:1px solid var(--line)}
 body.tb-h-two main>nav button{padding:0 14px;height:36px;font-size:13px}
 /* 頭 rail: 左の縦の列 */
 body.tb-h-rail{--rail:76px}
 body.tb-h-rail .appbar{padding-left:calc(var(--rail) + var(--g))!important;--bar-h:44px}
 body.tb-h-rail>main{margin-left:calc(var(--rail) + var(--g))!important;width:calc(100vw - var(--rail) - var(--g)*2)!important}
 body.tb-h-rail footer{padding-left:calc(var(--rail) + var(--g))!important}
 .tb-rail{position:fixed;left:0;top:0;bottom:0;width:var(--rail);background:linear-gradient(180deg,#132d40,#1b5670);z-index:20;display:flex;flex-direction:column;align-items:stretch;padding-top:52px;gap:2px}
 .tb-rail .tb-logo{position:absolute;top:8px;left:0;right:0;display:grid;place-items:center}
 .tb-rail .tb-logo i{width:30px;height:30px;border-radius:8px;background:#3fd0c9;color:#10303f;font-style:normal;font-weight:900;display:grid;place-items:center;font-size:15px}
 .tb-rail nav{display:flex;flex-direction:column;border:0;margin:0;gap:2px}
 .tb-rail nav button{display:grid;justify-items:center;gap:4px;padding:10px 2px;color:#a9c7d2;background:transparent;border:0;border-left:3px solid transparent;border-radius:0;font-size:10.5px;line-height:1.2;white-space:normal}
 .tb-rail nav button:hover{color:#fff;background:#ffffff0d}
 .tb-rail nav button.on{color:#fff;background:#ffffff17;border-left-color:#3fd0c9}
 body.tb-h-rail .brand h1{font-size:16px}
 /* 下の段（共通設定の中の切り替え）: 低く・説明は隠す */
 body.tb .subnav{margin:0 0 6px!important;padding:3px!important}
 body.tb .subnav button{padding:4px 12px!important}
 body.tb .subnav-note{display:none}
 body.tb-h-one #paths.on,body.tb-h-one .settings-shell{margin-top:0}
 /* 対象ファイルの道具の段 */
 body.tb #jobs>.commandbar,body.tb #jobs>.listmeta,body.tb #jobs>#command-queue{display:none!important}
 body.tb #jobs.on{display:flex!important;flex-direction:column}
 body.tb #jobs>.tablebox{flex:1 1 auto;min-height:0}
 .tb-bar{display:flex;align-items:center;gap:8px;height:40px;margin:6px 0;flex:none;position:relative}
 body.tb-h-two .tb-bar{margin-top:0}
 .tb-bar .sp{flex:1}
 .tb-count{display:flex;align-items:baseline;gap:8px;white-space:nowrap;padding-right:6px}
 .tb-count b{font-size:15px;color:#17384e}.tb-count b small{font-size:11.5px;font-weight:700;color:#4f6873;margin-left:2px}
 .tb-count span{font-size:11.5px;color:#6b7f88}
 .tb-bar select{height:30px;width:auto;padding:0 26px 0 10px;font-size:12px;border-color:#c8d6dc;color:#2b4b59;border-radius:7px;background-color:#fff}
 .tb-bar select.tb-set{border-color:#0b6577;background:#e8f5f7;color:#0b4f5c;font-weight:800}
 .tb-btn{height:30px;display:inline-flex;align-items:center;gap:6px;padding:0 11px;font-size:12px;font-weight:700;border-radius:7px;background:#fff;color:#2b4b59;border:1px solid #c8d6dc;white-space:nowrap}
 .tb-btn:hover{background:#f1f7f9;filter:none}
 .tb-btn.icon{width:30px;padding:0;justify-content:center;color:#4f6873}
 .tb-btn.add{background:#0b6577;color:#fff;border-color:#0b6577}
 .tb-btn.add:hover{background:#0d7a8d}
 .tb-btn.on{background:#e8f5f7;border-color:#0b6577;color:#0b4f5c}
 .tb-chip{height:28px;display:inline-flex;align-items:center;gap:6px;padding:0 10px 0 9px;font-size:12px;font-weight:800;border-radius:999px;white-space:nowrap;border:1px solid transparent}
 .tb-chip.warn{background:#fdf3e1;color:#8a5a0c;border-color:#efd6a6}
 .tb-chip.warn:hover{background:#fbebcc;filter:none}
 .tb-chip.q{background:#eef4f6;color:#46616c;border-color:#d9e5ea;font-weight:700}
 .tb-chip b{font-size:13px}
 .tb-search{display:flex;align-items:center;gap:6px;height:30px;border:1px solid #c8d6dc;border-radius:7px;background:#fff;padding:0 8px;color:#6b7f88;width:190px}
 .tb-search input{border:0;height:28px;padding:0;font-size:12px;outline:0!important;background:transparent}
 .tb-sep{width:1px;height:20px;background:#d5e1e6;margin:0 2px}
 .tb-pop{position:absolute;top:38px;z-index:30;background:#fff;border:1px solid #c8d6dc;border-radius:10px;box-shadow:0 14px 40px #15384d33;padding:8px;display:grid;gap:4px}
 .tb-pop h4{margin:2px 4px 4px;font-size:12px;color:#7a5a18;display:flex;align-items:center;gap:8px}
 .tb-pop h4 small{font-weight:600;color:#8b9ca3;font-size:11px}
 .tb-fresh-list{display:grid;gap:2px;width:520px}
 .tb-fresh-list button{display:grid;grid-template-columns:62px minmax(0,1fr) auto;gap:10px;align-items:center;height:30px;padding:0 8px;background:transparent;color:#22404d;border-radius:6px;text-align:left;font-size:12px;font-weight:700}
 .tb-fresh-list button:hover{background:#f6f1e6}
 .tb-fresh-list i{font-style:normal;font-size:10.5px;font-weight:900;text-align:center;border-radius:999px;padding:2px 0;color:#8a5f19;background:#f7efe0}
 .tb-fresh-list small{color:#7f929a;font-weight:600;font-size:11px}
 .tb-pop .tb-pop-foot{display:flex;align-items:center;gap:8px;border-top:1px solid #eef3f5;margin-top:4px;padding:7px 4px 2px;font-size:11px;color:#6b7f88}
 .tb-pop .tb-pop-foot button{margin-left:auto;height:26px;padding:0 10px;font-size:11.5px}
 .tb-line{display:flex;align-items:center;gap:10px;height:34px;margin:0 0 6px;padding:0 10px;border:1px solid #efd6a6;border-radius:8px;background:#fdf6e9;color:#7a5a18;font-size:12px;flex:none}
 .tb-line b{font-weight:900}.tb-line span{color:#8a6a2c;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
 .tb-line .sp{flex:1}.tb-line button{height:24px;padding:0 9px;font-size:11.5px;background:transparent;color:#8a5a0c;border:1px solid #e5c98f;border-radius:6px}
 .tb-line button.x{border:0;padding:0 4px;color:#a08850}
 .tb-fold{display:flex;align-items:center;gap:8px;height:36px;margin:0 0 6px;padding:0 8px;background:#f1f6f8;border:1px solid #dbe6ea;border-radius:8px;flex:none}
 .tb-fold small{color:#6b7f88;font-size:11px}
 .tb-sel{display:flex;align-items:center;gap:8px;height:40px;padding:0 6px 0 12px;border-radius:9px;background:#0f4d5e;color:#fff}
 .tb-sel b{font-size:13px;white-space:nowrap}.tb-sel b em{font-style:normal;font-size:16px;margin-right:2px}
 .tb-sel .tb-btn{background:#ffffff14;border-color:#ffffff33;color:#fff}
 .tb-sel .tb-btn:hover{background:#ffffff26}
 .tb-sel .tb-btn.go{background:#14a89f;border-color:transparent}
 .tb-sel .tb-btn.x{background:transparent;border-color:transparent;color:#cfe3ea}
 .tb-float{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);z-index:15;box-shadow:0 12px 34px #0b253766}
 .tb-th-sub{display:block;font-size:10.5px;font-weight:600;color:#7f929a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-transform:none;letter-spacing:0}
 .tb-th-sub a{color:#4f7f8e;text-decoration:none}
 .tb-thf{display:inline-flex;align-items:center;gap:3px;margin-left:4px;padding:1px 5px;border-radius:5px;background:#e3edf0;color:#40606c;font-size:10.5px;font-weight:800;vertical-align:middle}
 .tb-thf.on{background:#0b6577;color:#fff}
 .tb-th-add{float:right;height:22px;padding:0 9px;font-size:11px;border-radius:6px;background:#0b6577;color:#fff;display:inline-flex;align-items:center;gap:4px}
 .tb-nav-tools{display:flex;align-items:center;gap:6px;margin-left:auto;padding-left:12px}
 .tb-tabcount{display:inline-block;margin-left:6px;padding:0 6px;border-radius:999px;background:#ffffff1f;font-size:10.5px;color:#d9eef2;line-height:1.6}
 .appbar .tb-chip.warn{height:30px}
 body.tb tr.tb-stale td:first-child{box-shadow:inset 4px 0 0 #e0a43a}
 /* 下の帯: 低く・言うことは1つ */
 body.tb footer{min-height:0!important;height:30px;padding-top:0!important;padding-bottom:0!important;gap:8px}
 body.tb footer .autosave-lead{display:none}
 body.tb footer .autosave-state{margin-left:0;background:transparent;border:0;padding:0;font-size:11.5px}
 body.tb footer .tb-foot-hint{margin-left:auto;font-size:11px;color:#7f929a}
 body.tb footer .tb-foot-hint b{color:#4f6873}
 `;
 const st = () => { if (!$('#tb-style')) document.head.insertAdjacentHTML('beforeend', `<style id="tb-style">${CSS}</style>`); };
 const btn = (cls, ic, label, extra = '') => `<button type="button" class="tb-btn ${cls}" ${extra}>${ic ? svg(IC[ic], 15) : ''}${label ? `<span>${label}</span>` : ''}</button>`;
 function counts() {
  const t = $('#summary .lm-counts')?.textContent || $('#summary')?.textContent || '';
  const n = k => +(t.match(new RegExp(k + '\\s*(\\d+)'))?.[1] || 0);
  return { show: n('表示'), all: n('登録'), on: n('有効'), rules: n('自動実行ルール') };
 }
 function fresh() {
  const box = $('#fresh-board');
  if (!box || box.hidden) return null;
  const head = box.querySelector('.fb-head b')?.textContent || '';
  const rows = [...box.querySelectorAll('.fb-row')].map(r => ({ word: r.querySelector('i')?.textContent, name: r.querySelector('b')?.textContent, when: r.querySelector('span')?.textContent, note: r.querySelector('small')?.textContent }));
  return { n: +(head.match(/(\d+)/)?.[1] || rows.length), rows };
 }
 const selected = () => $$('#jobs-body tr.selected').length;
 const commonOut = () => $('#summary .lm-common .output-link')?.textContent || '';
 function freshPop(f, left) {
  const names = $$('#jobs-body tr').slice(0, 8).map(tr => tr.querySelector('.primarytext')?.textContent).filter(Boolean);
  const rows = (f.rows.length ? f.rows : []).concat(names.slice(f.rows.length, 8).map(n => ({ word: '未実行', name: n, when: 'まだ一度も実行していません', note: '手動のみ' })));
  return `<div class="tb-pop" style="left:${left}px"><h4>${svg(IC.warn, 14)}確認待ち ${f.n}件<small>共有のファイルが古い対象。押すと開きます</small></h4>
   <div class="tb-fresh-list">${rows.slice(0, 8).map(r => `<button type="button"><i>${E(r.word)}</i><span>${E(r.name)}</span><small>${E(r.when)}</small></button>`).join('')}</div>
   <div class="tb-pop-foot">ほか ${Math.max(0, f.n - 8)}件は一覧で色の付いた行です<button type="button" class="secondary">一覧をこの${f.n}件に絞る</button></div></div>`;
 }
 /* 頭（帯とタブ） */
 function head(kind) {
  document.body.classList.add('tb', 'tb-h-' + kind);
  const nav = $('main>nav') || $('.appbar>nav') || $('.tb-rail nav');
  if (kind === 'one') $('.appbar .brand').after(nav);
  if (kind === 'rail') {
   const r = document.createElement('aside'); r.className = 'tb-rail'; r.innerHTML = '<div class="tb-logo"><i>D</i></div>';
   document.body.append(r); r.append(nav);
   nav.querySelectorAll('button').forEach(b => { if (b.querySelector('svg')) return; const t = { viewer: 'データ<br>ビュワー', jobs: '対象<br>ファイル' }[b.dataset.p]; if (t) b.innerHTML = t; b.insertAdjacentHTML('afterbegin', svg(IC[b.dataset.p] || IC.jobs, 20)); });
  }
  // 選択を実行と全件実行を離す（押し間違えを減らす）
  $('.ctl-group')?.classList.add('tb-split');
 }
 function runtime(queueInStatus) {
  const sub = $('#sub'); if (sub && queueInStatus) sub.textContent = 'キュー 0件';
 }
 function foot(hint = true) {
  const f = $('footer'); if (!f || f.querySelector('.tb-foot-hint')) return;
  if (hint) f.insertAdjacentHTML('beforeend', '<span class="tb-foot-hint">行を<b>右クリック</b>で 複製・削除・出力先を開く ／ 状態の札を押すと有効・無効</span>');
 }
 function outInHeader() {
  const th = $$('#jobs-head th').find(x => x.textContent.trim().startsWith('出力先'));
  const p = commonOut(); if (th && p && !th.querySelector('.tb-th-sub')) th.insertAdjacentHTML('beforeend', `<span class="tb-th-sub">共通: <a href="#">${E(p)}</a></span>`);
 }
 function bar(html) { const b = document.createElement('div'); b.className = 'tb-bar'; b.innerHTML = html; $('#jobs').prepend(b); return b; }
 function moveSelects(b, at) {
  const slot = b.querySelector(at);
  ['#filter-enabled', '#filter-schedule', '#sort'].forEach(s => { const x = $(s); slot.append(x); x.classList.toggle('tb-set', x.value !== x.options[0].value); });
 }
 function countHtml(c, wide = true) {
  return `<span class="tb-count"><b>${c.show === c.all ? c.all : `${c.show} / ${c.all}`}<small>件</small></b>${wide ? `<span>有効 ${c.on} ・ 自動実行 ${c.rules}</span>` : ''}</span>`;
 }
 function selBar(n, cls = '') {
  return `<div class="tb-sel ${cls}"><b><em>${n}</em>件を選択中</b>${btn('go', 'play', '選んだ対象を実行')}${btn('', 'edit', 'まとめて変更')}${btn('', 'out', '書き出す')}${btn('x', 'x', '選択を解除')}</div>`;
 }
 const P = {};
 /* A: タブを帯へ（1段）＋ 道具は1段（件数・絞り込み3つ・確認待ちの札・検索は虫眼鏡・表示のメニュー・新規追加）＋ キューは帯の状態へ */
 P.A = v => {
  head('one'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  const b = bar(`${countHtml(c)}<span class="tb-sep"></span><span class="tb-f" style="display:flex;gap:6px"></span>${f ? `<button type="button" class="tb-chip warn">${svg(IC.warn, 14)}確認待ち <b>${f.n}</b>${svg(IC.down, 13)}</button>` : ''}
   <span class="sp"></span>${n ? `<span class="tb-chip q">${n}件を選択中</span>${btn('', 'edit', 'まとめて変更')}${btn('', 'out', '書き出す')}${btn('', 'x', '解除')}<span class="tb-sep"></span>` : ''}${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示', 'title="列の表示・全件を選ぶ"')}${btn('add', 'plus', '新規追加')}`);
  moveSelects(b, '.tb-f');
  if (f && v === 2) b.insertAdjacentHTML('beforeend', freshPop(f, 520));
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* B: 帯とタブの2段（どちらも低く）＋ 道具は1段（小さな検索欄を右端に）＋ 確認待ちは1行の帯（開ける）＋ キューは道具の段の札 */
 P.B = v => {
  head('two'); foot();
  const c = counts(), f = fresh(), n = selected();
  const b = bar(`${countHtml(c)}<span class="tb-sep"></span><span class="tb-f" style="display:flex;gap:6px"></span><button type="button" class="tb-chip q">キュー 待機なし ${svg(IC.down, 13)}</button>
   <span class="sp"></span>${n ? `<span class="tb-chip q">${n}件を選択中</span>${btn('', 'edit', 'まとめて変更')}${btn('', 'out', '書き出す')}${btn('', 'x', '解除')}<span class="tb-sep"></span>` : ''}<label class="tb-search">${svg(IC.search, 14)}<input placeholder="検索"></label>${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
  moveSelects(b, '.tb-f');
  if (f) b.insertAdjacentHTML('afterend', `<div class="tb-line">${svg(IC.warn, 15)}<b>確認待ち ${f.n}件</b><span>${f.rows.map(r => E(r.name)).join('・')} ほか${f.n - f.rows.length}件 ― 共有のファイルが古い対象</span><span class="sp"></span><button type="button">一覧を絞る</button><button type="button" class="x" title="閉じる">${svg(IC.x, 14)}</button></div>`);
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* C: 左の縦の列で画面を切り替える ＋ 上の帯は低く ＋ 道具は A と同じ1段 */
 P.C = v => {
  head('rail'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  const b = bar(`${countHtml(c)}<span class="tb-sep"></span><span class="tb-f" style="display:flex;gap:6px"></span>${f ? `<button type="button" class="tb-chip warn">${svg(IC.warn, 14)}確認待ち <b>${f.n}</b>${svg(IC.down, 13)}</button>` : ''}
   <span class="sp"></span>${n ? `<span class="tb-chip q">${n}件を選択中</span>${btn('', 'edit', 'まとめて変更')}${btn('', 'out', '書き出す')}${btn('', 'x', '解除')}<span class="tb-sep"></span>` : ''}${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
  moveSelects(b, '.tb-f');
  if (f && v === 2) b.insertAdjacentHTML('beforeend', freshPop(f, 520));
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* D: 道具の段を無くし、絞り込みは表の見出しの中（状態▾・予定▾・見出しを押して並べ替え）。新規追加は見出しの右端。
       確認待ちは帯の札、件数はタブの横。選んだときだけ表の下に浮く操作の帯 */
 P.D = v => {
  head('one'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  $('.appbar nav button[data-p="jobs"]')?.insertAdjacentHTML('beforeend', `<span class="tb-tabcount">${c.all}</span>`);
  if (f) $('.appbar-tools').insertAdjacentHTML('afterbegin', `<button type="button" class="tb-chip warn">${svg(IC.warn, 14)}確認待ち <b>${f.n}</b></button>`);
  $$('#jobs-head th').forEach(th => {
   const t = th.textContent.trim();
   if (t.startsWith('状態')) th.insertAdjacentHTML('beforeend', '<span class="tb-thf" title="有効・無効で絞る">▾</span>');
   if (t.startsWith('管理名称')) th.insertAdjacentHTML('beforeend', `<span class="tb-thf" title="検索（Ctrl+F）">${svg(IC.search, 11)}</span>`);
   if (t.startsWith('進捗')) th.insertAdjacentHTML('beforeend', '<span class="tb-thf">予定 すべて▾</span>');
   if (t.startsWith('操作')) th.insertAdjacentHTML('beforeend', `<button type="button" class="tb-th-add">${svg(IC.plus, 12)}新規追加</button>`);
  });
  $('#jobs').prepend(Object.assign(document.createElement('div'), { style: 'height:8px;flex:none' }));
  if (n) { $('#jobs>.tablebox').style.position = 'relative'; $('#jobs>.tablebox').insertAdjacentHTML('beforeend', selBar(n, 'tb-float')); }
  if (f && v === 2) { const a = $('.appbar .tb-chip.warn'); a.style.position = 'relative'; document.body.insertAdjacentHTML('beforeend', freshPop(f, 0).replace('class="tb-pop"', `class="tb-pop" style="position:fixed;top:44px;right:${innerWidth - a.getBoundingClientRect().right}px;left:auto"`)); }
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* E: 帯とタブの2段 ＋ 道具はたたむ（件数と「絞り込み・並べ替え ▸」だけ。開くと選ぶ欄が出る）＋ 確認待ちは1行の帯 */
 P.E = v => {
  head('two'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  const b = bar(`${countHtml(c)}<button type="button" class="tb-btn">${svg(IC.right, 13)}絞り込み・並べ替え <small style="color:#7f929a;font-weight:600">すべて／登録順</small></button><span class="tb-f tb-hidden"></span>
   <span class="sp"></span>${n ? `<span class="tb-chip q">${n}件を選択中</span>${btn('', 'edit', 'まとめて変更')}${btn('', 'out', '書き出す')}${btn('', 'x', '解除')}<span class="tb-sep"></span>` : ''}${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
  moveSelects(b, '.tb-f');
  if (f) b.insertAdjacentHTML('afterend', `<div class="tb-line">${svg(IC.warn, 15)}<b>確認待ち ${f.n}件</b><span>${f.rows.map(r => E(r.name)).join('・')} ほか${f.n - f.rows.length}件 ― 共有のファイルが古い対象</span><span class="sp"></span><button type="button">一覧を絞る</button><button type="button" class="x">${svg(IC.x, 14)}</button></div>`);
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* F（方向が違う）: 既定で済ませて例外だけ出す。表の上には何も置かない。新規追加と「⋯」（絞り込み・検索・列の表示）はタブの右端、
       件数は下の帯、確認待ちは行の左の色と帯の札だけ。選んだときだけ道具の段が出る */
 P.F = v => {
  head('one'); runtime(true);
  const c = counts(), f = fresh(), n = selected();
  $('.appbar nav').insertAdjacentHTML('beforeend', '');
  $('.appbar .brand').insertAdjacentHTML('afterend', '');
  $('.appbar nav').after(Object.assign(document.createElement('span'), { className: 'tb-nav-tools', innerHTML: `<button type="button" class="tb-btn add" style="height:30px">${svg(IC.plus, 15)}新規追加</button><button type="button" class="tb-btn icon" style="background:#ffffff14;border-color:#ffffff33;color:#d9eef2" title="絞り込み・検索・列の表示">${svg(IC.more, 16)}</button>` }));
  if (f) $('.appbar-tools').insertAdjacentHTML('afterbegin', `<button type="button" class="tb-chip warn">${svg(IC.warn, 14)}確認待ち <b>${f.n}</b></button>`);
  if (f) $$('#jobs-body tr').slice(0, f.n).forEach(tr => tr.classList.add('tb-stale'));
  $('footer').insertAdjacentHTML('beforeend', `<span class="tb-foot-hint">${c.all}件 ・ 有効 ${c.on} ・ 自動実行 ${c.rules} ／ 行を<b>右クリック</b>で複製・削除など</span>`);
  if (n) { const b = bar(selBar(n)); b.style.margin = '6px 0'; } else $('#jobs').prepend(Object.assign(document.createElement('div'), { style: 'height:8px;flex:none' }));
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* G（方向が違う）: 道具の段の中身を場面で入れ替える。ふだんは件数・「絞り込み▾」（3つの選ぶ欄と検索を1つのポップオーバーに）・新規追加。
       選ぶと段ごと「選んだ対象への操作」に替わる（選択を実行もここへ移し、帯の全件実行から離す）。確認待ちは札 */
 P.G = v => {
  head('one'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  $('#run-selected')?.classList.add('tb-hidden');
  if (n) { bar(selBar(n)); }
  else {
   const b = bar(`${countHtml(c)}<button type="button" class="tb-btn">${svg(IC.filter, 14)}絞り込み <small style="color:#7f929a;font-weight:600">すべて・登録順</small>${svg(IC.down, 13)}</button><span class="tb-f tb-hidden"></span>${f ? `<button type="button" class="tb-chip warn">${svg(IC.warn, 14)}確認待ち <b>${f.n}</b>${svg(IC.down, 13)}</button>` : ''}
    <span class="sp"></span>${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
   moveSelects(b, '.tb-f');
   if (f && v === 2) b.insertAdjacentHTML('beforeend', freshPop(f, 330));
  }
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 /* ---- 2回目: 上位3案 E・G・B ＋ 組合せ案 H〜K ----
    1回目で全案に残った欠点も直す: 『色の付いた行』と書いたのに行に色が無い（確認待ちの行に左の橙の線を付ける）／
    検索の入口が見えない（虫眼鏡を常に出す）／帯・タブ・道具の3段で表が下がる／選択を実行が2か所／『›』が開く物か分からない（▾ に） */
 const markStale = () => $$('#jobs-body tr').forEach(tr => { if (/有効/.test(tr.querySelector('.state')?.textContent || '')) tr.classList.add('tb-stale'); });
 const strip = f => `<div class="tb-line">${svg(IC.warn, 15)}<b>確認待ち ${f.n}件</b><span>一度も実行していない・共有のファイルが古い対象です（表の左に橙の線）　${f.rows.map(r => E(r.name)).join('・')} ほか</span><span class="sp"></span><button type="button">この${f.n}件に絞る</button><button type="button" class="x" title="閉じる（新しい問題が起きたら、また出します）">${svg(IC.x, 14)}</button></div>`;
 const filterBtn = () => `<button type="button" class="tb-btn" aria-haspopup="true">${svg(IC.filter, 14)}絞り込み <small style="color:#7f929a;font-weight:600">すべて・登録順</small>${svg(IC.down, 13)}</button>`;
 // H = G（帯は1段・道具の段は場面で入れ替え）＋ E の1行の知らせ（開かずに読める）＋ 行の左の橙の線 ＋ 虫眼鏡
 P.H = v => {
  head('one'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  $('#run-selected')?.classList.add('tb-hidden');
  if (n) bar(selBar(n));
  else {
   const b = bar(`${countHtml(c)}${filterBtn()}<span class="tb-f tb-hidden"></span><span class="sp"></span>${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
   moveSelects(b, '.tb-f');
   if (f) b.insertAdjacentHTML('afterend', strip(f));
  }
  if (f) markStale();
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 // I = 帯は低い1段（アプリ名・状態・全件実行・終了）＋ 2段目の左にタブ・右にこの画面の道具（件数・絞り込み▾・虫眼鏡・表示・新規追加）。
 //     タブと道具を同じ段に置いて3段を2段に。知らせは1行の帯・行の橙の線。選ぶと道具の側が選んだ物の操作に替わる
 P.I = v => {
  head('two'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  $('#run-selected')?.classList.add('tb-hidden');
  const nav = $('main>nav'); nav.style.cssText = 'display:flex;align-items:center;height:44px;margin:0 0 6px!important';
  const tools = document.createElement('div'); tools.className = 'tb-bar'; tools.style.cssText = 'margin:0 0 0 auto;height:40px';
  if (n) tools.innerHTML = selBar(n);
  else { tools.innerHTML = `${countHtml(c, false)}${filterBtn()}<span class="tb-f tb-hidden"></span>${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`; moveSelects(tools, '.tb-f'); }
  nav.append(tools);
  if (f && !n) $('#jobs').prepend(Object.assign(document.createElement('div'), { innerHTML: strip(f), style: 'flex:none' }));
  else $('#jobs').prepend(Object.assign(document.createElement('div'), { style: 'height:2px;flex:none' }));
  if (f) markStale();
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 // J = H ＋ 知らせを道具の段の中へ（行を足さない）。橙の部分に件数・何の対象か・この件数に絞る
 P.J = v => {
  head('one'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  $('#run-selected')?.classList.add('tb-hidden');
  if (n) bar(selBar(n));
  else {
   const b = bar(`${countHtml(c)}${filterBtn()}<span class="tb-f tb-hidden"></span>${f ? `<span class="tb-line" style="margin:0;height:32px;flex:1;min-width:0">${svg(IC.warn, 15)}<b style="white-space:nowrap">確認待ち ${f.n}件</b><span>一度も実行していない・共有のファイルが古い対象（左に橙の線）</span><span class="sp"></span><button type="button" style="white-space:nowrap">この${f.n}件に絞る</button><button type="button" class="x">${svg(IC.x, 14)}</button></span>` : '<span class="sp"></span>'}${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
   moveSelects(b, '.tb-f');
  }
  if (f) markStale();
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 // K = H ＋ 絞り込みはその場で選べる小さな選ぶ欄（1手で変えられる。既定の『すべて』は淡く、変えたら色が付く）
 P.K = v => {
  head('one'); runtime(true); foot();
  const c = counts(), f = fresh(), n = selected();
  $('#run-selected')?.classList.add('tb-hidden');
  if (n) bar(selBar(n));
  else {
   const b = bar(`${countHtml(c)}<span class="tb-sep"></span><span class="tb-f" style="display:flex;gap:6px"></span><span class="sp"></span>${btn('icon', 'search', '', 'title="検索（Ctrl+F）"')}${btn('', 'view', '表示')}${btn('add', 'plus', '新規追加')}`);
   moveSelects(b, '.tb-f');
   b.querySelectorAll('select').forEach(s => { s.style.cssText = 'border-color:#dbe5e9;background-color:#f6f9fa;color:#5a727c'; });
   if (f) b.insertAdjacentHTML('afterend', strip(f));
  }
  if (f) markStale();
  $('#fresh-board').classList.add('tb-hidden'); outInHeader();
 };
 window.TB = {
  keys: () => Object.keys(P),
  show(k, v) {
   st();
   if (v === 3) { P[k](1); $('nav button[data-p="paths"]')?.click(); return true; }
   P[k](v); return true;
  },
 };
})();
