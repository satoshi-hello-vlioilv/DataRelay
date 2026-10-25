// 2.11.0 対象ファイル一覧のグループ（畳む・グループ単位で実行する・まとまりで見る）の案（CLAUDE.md §3）。
// いま: 30件が1本の表に登録順で並ぶだけ。仕事のまとまり（仕掛・生産・出荷…）は名前から読み取るしかなく、
// まとめて実行するには1件ずつチェックを入れる。
// 本物の画面（撮影用の環境に対象30件）の表を、案ごとに組み替える。グループの分け方は案を比べるための仮のもの（名前から）。
// 撮り方: window.TG.show(k, view)。view 1 = すべて開いた一覧、2 = いくつか畳んだ、3 = あるグループを実行中、4 = グループの操作を開いた。
(() => {
 const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const svg = (d, w = 15) => `<svg viewBox="0 0 24 24" width="${w}" height="${w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
 const IC = { down: '<path d="M6 9.5l6 6 6-6"/>', right: '<path d="M9.5 6l6 6-6 6"/>', play: '<path d="M8 5.5v13l10.5-6.5z"/>', more: '<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>', folder: '<path d="M3.5 6.5h6l2 2h9v10h-17z"/>', plus: '<path d="M12 5v14M5 12h14"/>', layers: '<path d="M12 4l9 5-9 5-9-5z"/><path d="M3 14l9 5 9-5"/>' };
 // 仮のグループ（名前から）。色はグループの印（帯・点）に使う
 const GROUPS = [
  { key: 'sk', name: '仕掛', color: '#0f8a8f', of: n => /^SIKA|仕掛|LOTHIST|BOXTRACK/.test(n) },
  { key: 'pr', name: '生産・品質', color: '#4a67c9', of: n => /作業実績|PRODPLAN|QCRESULT|YIELD|DEFECT|FURNACE|ANNEAL|ROLL|CUTPLAN|THICK|PITCH|GRADE|SLAB|COIL/.test(n) },
  { key: 'sh', name: '出荷・在庫', color: '#b5730f', of: n => /SHIP|INVSTOCK|ORDER|PACK|CLAIM/.test(n) },
  { key: 'mg', name: '管理・保全', color: '#8a55b3', of: n => /COST|MAINT|ENERGY|SCRAP/.test(n) },
 ];
 const NONE = { key: '', name: 'グループなし', color: '#9aa9b0' };
 const CSS = `
 .tg-head td{padding:0!important;background:#f3f7f9;border-bottom:1px solid #dbe5ea;height:38px}
 .tg-bar{display:flex;align-items:center;gap:10px;height:38px;padding:0 10px 0 6px;position:relative}
 .tg-bar .tg-tw{width:26px;height:26px;display:grid;place-items:center;border-radius:6px;background:transparent;color:#4f6873;padding:0}
 .tg-bar .tg-tw:hover{background:#e3edf0;filter:none}
 .tg-bar b{font-size:13px;color:#17384e}
 .tg-bar .tg-n{font-size:11.5px;color:#6b7f88;font-weight:700}
 .tg-chips{display:flex;gap:6px;align-items:center}
 .tg-chip{font-size:11px;font-weight:800;border-radius:999px;padding:1px 8px;white-space:nowrap}
 .tg-chip.ok{background:#e5f5ef;color:#087a57}.tg-chip.off{background:#edf0f2;color:#6e7880}.tg-chip.warn{background:#fdf3e1;color:#8a5a0c}.tg-chip.ng{background:#fdeeec;color:#a4463d}
 .tg-bar .sp{flex:1}
 .tg-run{height:28px;display:inline-flex;align-items:center;gap:5px;padding:0 11px;border-radius:7px;background:#fff;border:1px solid #9fcfd6;color:#0b6577;font-size:12px;font-weight:800}
 .tg-run:hover{background:#e8f5f7;filter:none}
 .tg-more{width:28px;height:28px;padding:0;display:grid;place-items:center;border-radius:7px;background:transparent;color:#4f6873;border:1px solid transparent}
 .tg-more:hover{background:#e3edf0;filter:none}
 .tg-head.closed td{background:#f8fafb}
 .tg-dot{width:10px;height:10px;border-radius:3px;flex:none}
 .tg-stripe td:first-child{box-shadow:inset 4px 0 0 var(--gc)}
 .tg-head.stripe .tg-bar{border-left:4px solid var(--gc);padding-left:4px}
 .tg-prog{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:800;color:#0b6577}
 .tg-prog i{display:block;width:140px;height:7px;border-radius:999px;background:#dce7ea;overflow:hidden}
 .tg-prog i b{display:block;height:100%;width:var(--p);background:linear-gradient(90deg,#14a39f,#237fbc)}
 .tg-menu{position:absolute;right:8px;top:36px;z-index:40;background:#fff;border:1px solid #c8d6dc;border-radius:10px;box-shadow:0 14px 40px #15384d33;padding:6px;display:grid;gap:2px;min-width:230px}
 .tg-menu button{height:32px;padding:0 10px;text-align:left;background:transparent;color:#22404d;font-size:12.5px;font-weight:700;border-radius:6px;display:flex;align-items:center;gap:8px}
 .tg-menu button small{margin-left:auto;color:#8b9ca3;font-weight:600}
 .tg-menu hr{border:0;border-top:1px solid #eef3f5;margin:3px 0}
 .tg-menu .danger{color:#a4463d}
 .tg-hide{display:none!important}
 /* 2回目（組合せ）: 塗りの実行・見出しを上に残す・まとめて選ぶ・止める・跳ぶ */
 .tg-run.solid{background:#0b7f8c;border-color:#0b7f8c;color:#fff}.tg-run.solid:hover{background:#086f7b}
 .tg-run.stop{background:#fff;border-color:#e2b4ae;color:#a4463d}
 .tg-head.sticky td{position:sticky;top:var(--th,37px);z-index:3}
 .tg-ck{width:16px!important;height:16px!important;margin:0 2px 0 4px}
 .tg-next{font-size:11.5px;color:#5b707a;font-weight:700;white-space:nowrap}
 .tg-jump{display:flex;align-items:center;gap:6px;margin:0 0 6px;flex:none;flex-wrap:nowrap;overflow:hidden}
 .tg-jump button{height:28px;display:inline-flex;align-items:center;gap:6px;padding:0 10px;border-radius:7px;border:1px solid #d3e0e5;background:#fff;color:#35505b;font-size:12px;font-weight:800}
 .tg-jump button small{font-weight:700;color:#7f929a}.tg-jump .lab{font-size:11.5px;color:#6b7f88;font-weight:800;margin-right:2px}
 .tg-jump .sp{flex:1}
 .tg-seg{display:inline-flex;height:8px;width:120px;border-radius:999px;overflow:hidden;background:#e6ecef}
 .tg-seg i{display:block;height:100%}
 .tg-head.sticky td.tg-ckcell{padding:0 8px!important;vertical-align:middle}
 .tg-names{font-size:11.5px;color:#7a8d96;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1 1 auto;margin-left:6px}
 .tg-jump .dotst{width:7px;height:7px;border-radius:50%;display:inline-block}

 /* C: 左のグループの一覧 */
 .tg-split{display:grid;grid-template-columns:220px minmax(0,1fr);gap:10px;min-height:0;flex:1}
 .tg-side{background:#fff;border:1px solid #d7e0e5;border-radius:10px;padding:8px;display:flex;flex-direction:column;gap:2px;overflow:auto}
 .tg-side h4{margin:2px 6px 6px;font-size:12px;color:#4f6873}
 .tg-side button{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:8px;height:36px;padding:0 8px;border-radius:7px;background:transparent;color:#22404d;font-size:12.5px;font-weight:700;text-align:left}
 .tg-side button.on{background:#e3f2f5;color:#0b4f5c}
 .tg-side button small{color:#7f929a;font-weight:700}
 .tg-side .tg-side-run{margin-top:auto}
 /* D: 札で切り替え */
 .tg-tabs{display:flex;align-items:center;gap:6px;margin:0 0 6px;flex:none}
 .tg-tabs button{height:30px;display:inline-flex;align-items:center;gap:6px;padding:0 12px;border-radius:999px;border:1px solid #d3e0e5;background:#fff;color:#35505b;font-size:12px;font-weight:800}
 .tg-tabs button.on{background:#17384e;border-color:#17384e;color:#fff}
 .tg-tabs button small{font-weight:700;opacity:.75}
 .tg-tabs .sp{flex:1}
 /* E: グループごとの札 */
 .tg-card-gap td{height:10px!important;padding:0!important;background:#f3f6f8!important;border:0!important}
 .tg-head.card td{background:#fff;border-top:1px solid #d7e0e5;border-bottom:2px solid var(--gc)}
 .tg-head.card .tg-bar b{font-size:14px}
 /* F: まとめ方 */
 .tg-by{display:inline-flex;border:1px solid #c8d6dc;border-radius:7px;overflow:hidden;background:#fff}
 .tg-by span{padding:0 10px;height:28px;display:inline-flex;align-items:center;font-size:12px;font-weight:700;color:#5a727c;border-left:1px solid #e3ebee}
 .tg-by span:first-child{border-left:0}.tg-by span.on{background:#0b6577;color:#fff}
 /* G: 実行セット */
 .tg-set{display:inline-flex;align-items:center;gap:6px}
 .tg-setpop{position:absolute;top:38px;left:0;z-index:40;background:#fff;border:1px solid #c8d6dc;border-radius:10px;box-shadow:0 14px 40px #15384d33;padding:8px;display:grid;gap:4px;width:420px}
 .tg-setpop .row{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;gap:8px;align-items:center;height:34px;padding:0 6px;border-radius:7px}
 .tg-setpop .row:hover{background:#f1f7f9}
 .tg-setpop b{font-size:12.5px}.tg-setpop small{color:#7f929a;font-size:11px}
 .tg-tag{font-size:10.5px;font-weight:800;border-radius:5px;padding:0 6px;margin-left:6px;color:#fff;vertical-align:1px}
 `;
 const st = () => { if (!$('#tg-style')) document.head.insertAdjacentHTML('beforeend', `<style id="tg-style">${CSS}</style>`); };
 const rows = () => $$('#jobs-body tr').filter(tr => tr.dataset.id);
 const nameOf = tr => tr.querySelector('.primarytext')?.textContent || '';
 const groupOf = tr => GROUPS.find(g => g.of(nameOf(tr))) || NONE;
 const ncol = () => $$('#jobs-head th').length;
 function summary(trs) {
  const on = trs.filter(t => /有効/.test(t.querySelector('.state')?.textContent || '')).length;
  const never = trs.filter(t => /未実行/.test(t.querySelector('.rowprogress')?.textContent || '')).length;
  return { n: trs.length, on, off: trs.length - on, never };
 }
 const chips = s => `<span class="tg-chips"><span class="tg-chip ok">有効 ${s.on}</span>${s.off ? `<span class="tg-chip off">無効 ${s.off}</span>` : ''}${s.never ? `<span class="tg-chip warn">未実行 ${s.never}</span>` : ''}</span>`;
 const btn = (cls, ic, label, extra = '') => `<button type="button" class="${cls}" ${extra}>${ic ? svg(IC[ic], 14) : ''}${label || ''}</button>`;
 function menu(g) {
  return `<div class="tg-menu" role="menu">${btn('', 'play', `「${E(g.name)}」を実行<small>有効なものだけ</small>`)}${btn('', '', 'このグループの対象をすべて選ぶ')}<hr>${btn('', '', 'すべて有効にする')}${btn('', '', 'すべて無効にする')}<hr>${btn('', '', '名前を変える…')}${btn('', '', '上へ<small>グループの並び</small>')}${btn('', '', '下へ')}<hr>${btn('danger', '', 'グループを解く<small>対象は残ります</small>')}</div>`;
 }
 // 状態を1本の帯で（緑=有効で前回成功・橙=未実行・灰=無効）
 const seg = s => `<span class="tg-chips"><span class="tg-seg" title="有効 ${s.on}・無効 ${s.off}・未実行 ${s.never}"><i style="width:${(s.on - Math.min(s.on, s.never)) / s.n * 100}%;background:#16a37a"></i><i style="width:${Math.min(s.on, s.never) / s.n * 100}%;background:#e0a33a"></i><i style="width:${s.off / s.n * 100}%;background:#b8c3c8"></i></span><span class="tg-chip ok">有効 ${s.on}</span>${s.off ? `<span class="tg-chip off">無効 ${s.off}</span>` : ''}${s.never ? `<span class="tg-chip warn">未実行 ${s.never}</span>` : ''}</span>`;
 // 実行中の様子（本物の画面と同じ: 行の進み具合・右上の状態）。2回目は全案に入れる（1回目は見本の作りが足りず、行が「未実行」のままだった）
 function live(key) {
  const trs = rows().filter(t => groupOf(t).key === key && /有効/.test(t.querySelector('.state')?.textContent || ''));
  trs.forEach((t, i) => {
   const rp = t.querySelector('.rowprogress'); if (!rp) return;
   const st = i < 2 ? ['is-done', '完了', 100, '12,480行 ・ 0:41'] : i < 4 ? ['is-running', '実行中', i === 2 ? 64 : 31, i === 2 ? '問い合わせ中 ・ 0:22' : '保存中 ・ 0:09'] : ['is-wait', '待ち', 0, `待ち ${i - 3}番目`];
   rp.classList.add(st[0]); rp.querySelector('.rp-state').textContent = st[1]; rp.querySelector('.rp-bar').style.width = st[2] + '%'; rp.querySelector('.rp-detail').textContent = st[3];
  });
  const stt = $('#st'), sub = $('#sub'); if (stt) stt.textContent = '処理中'; if (sub) sub.textContent = `仕掛 2 / ${trs.length}`;
 }
 function foldBtn(v) {
  const sp = $('#jobs .jb-idle .jb-sp'); sp?.insertAdjacentHTML('afterend', btn('tbtn', v === 2 ? 'down' : 'right', v === 2 ? 'すべて開く' : 'すべて畳む', 'title="グループをすべて畳む・開く"'));
 }
 function jump(v) {
  const all = rows(), bar = document.createElement('div'); bar.className = 'tg-jump';
  bar.innerHTML = `<span class="lab">グループ</span>` + GROUPS.map(g => `<button type="button"><i class="tg-dot" style="background:${g.color}"></i>${E(g.name)} <small>${all.filter(t => groupOf(t) === g).length}</small>${TG.r3 ? `<span class="dotst" title="確認待ちあり" style="background:#e0a33a"></span>` : ''}</button>`).join('')
   + `<span class="sp"></span>` + btn('tbtn', '', v === 2 ? 'すべて開く' : 'すべて畳む');
  $('#jobs .tablebox').before(bar);
 }
 // 表の中に見出し行を差し込み、行をグループの順に並べ直す
 function inTable(o) {
  const body = $('#jobs-body'), all = rows(), n = ncol();
  const by = [...GROUPS, NONE].map(g => ({ g, trs: all.filter(t => groupOf(t) === g) })).filter(x => x.trs.length);
  by.forEach(({ g, trs }, gi) => {
   const s = summary(trs), closed = (o.closed || []).includes(g.key), running = o.running === g.key, menuOpen = o.menu === g.key;
   if (o.card && gi) body.insertAdjacentHTML('beforeend', `<tr class="tg-card-gap"><td colspan="${n}"></td></tr>`);
   const head = document.createElement('tr');
   head.className = `tg-head${closed ? ' closed' : ''}${o.stripe ? ' stripe' : ''}${o.card ? ' card' : ''}${o.sticky ? ' sticky' : ''}`;
   head.style.setProperty('--gc', g.color);
   // align: 見出しのチェックを、行のチェックと同じ列（1列目）に置く
   const sv = running && o.liveChips ? { ...s, never: Math.max(0, s.never - 2) } : s;
   head.innerHTML = (o.align ? `<td class="tg-ckcell"><span class="drag-handle" style="visibility:hidden">⋮⋮</span><input type="checkbox" class="rowcheck" title="このグループの対象をすべて選ぶ"></td><td colspan="${n - 1}">` : `<td colspan="${n}">`)
    + `<div class="tg-bar">${btn('tg-tw', closed ? 'right' : 'down', '', `aria-expanded="${!closed}" title="${closed ? '開く' : '畳む'}"`)}`
    + (o.dot ? `<i class="tg-dot" style="background:${g.color}"></i>` : '')
    + (o.check && !o.align ? `<input type="checkbox" class="tg-ck" title="このグループの対象をすべて選ぶ">` : '')
    + `<b>${E(g.name)}</b><span class="tg-n">${s.n}件</span>${o.seg ? seg(sv) : chips(sv)}`
    + (o.names && closed ? `<span class="tg-names">${trs.slice(0, 6).map(nameOf).map(E).join('・')}${trs.length > 6 ? ` ほか${trs.length - 6}件` : ''}</span>` : '')
    + (o.next && g.key && !running ? `<span class="tg-next">次回 ${g.key === 'sk' ? '今日 14:00' : g.key === 'pr' ? '明日 06:00' : '手動のみ'}</span>` : '') + `<span class="sp"></span>`
    + (running ? `<span class="tg-prog">実行中 2 / ${s.on}<i style="--p:${Math.round(200 / Math.max(1, s.on))}%"><b></b></i></span>` : '')
    + (running && o.stop ? btn('tg-run stop', '', '■ 止める') : '')
    + (g.key || o.runNone ? (running && o.stop ? '' : btn(`tg-run${o.solid ? ' solid' : ''}`, 'play', running ? '実行中…' : (o.runLabel || 'グループを実行'), running ? 'disabled' : '')) : '')
    + btn('tg-more', 'more', '', 'title="グループの操作"') + (menuOpen ? menu(g) : '') + `</div></td>`;
   body.append(head);
   trs.forEach(t => { if (o.stripe) { t.classList.add('tg-stripe'); t.style.setProperty('--gc', g.color); } if (closed) t.classList.add('tg-hide'); body.append(t); });
  });
 }
 const P = {};
 // A: 表の中にグループの見出し行（畳む・件数と状態・グループを実行・…）
 P.A = v => inTable({ closed: v === 2 ? ['pr', 'mg'] : [], running: v === 3 ? 'sk' : '', menu: v === 4 ? 'sk' : '' });
 // B: A ＋ グループの色（見出しと行の左に同じ色の帯）
 P.B = v => inTable({ stripe: true, dot: true, closed: v === 2 ? ['pr', 'mg'] : [], running: v === 3 ? 'sk' : '', menu: v === 4 ? 'sk' : '' });
 // C: 左にグループの一覧（件数・選ぶと絞る）＋ その下にグループを実行
 P.C = v => {
  const sec = $('#jobs'), box = sec.querySelector('.tablebox'), all = rows(), pick = v === 2 ? 'pr' : v === 3 ? 'sk' : 'sh';
  const wrap = document.createElement('div'); wrap.className = 'tg-split';
  const side = document.createElement('div'); side.className = 'tg-side';
  const cnt = g => all.filter(t => groupOf(t) === g).length;
  side.innerHTML = `<h4>グループ</h4><button type="button" class="${v === 1 ? 'on' : ''}">${svg(IC.layers, 14)}<span>すべて</span><small>${all.length}</small></button>`
   + [...GROUPS, NONE].map(g => `<button type="button" class="${v !== 1 && g.key === pick ? 'on' : ''}"><i class="tg-dot" style="background:${g.color}"></i><span>${E(g.name)}</span><small>${cnt(g)}</small></button>`).join('')
   + `<button type="button" class="tg-side-run tg-run">${svg(IC.play, 14)}${v === 1 ? 'すべてを実行' : '選んだグループを実行'}</button>`;
  box.before(wrap); wrap.append(side, box);
  if (v !== 1) all.forEach(t => { if (groupOf(t).key !== pick) t.classList.add('tg-hide'); });
  if (v === 3) side.querySelector('.tg-side-run').innerHTML = `${svg(IC.play, 14)}実行中 2 / 6`;
  if (v === 4) side.querySelector('button.on').insertAdjacentHTML('beforeend', menu(GROUPS[2]).replace('tg-menu', 'tg-menu" style="left:200px;right:auto;top:auto'));
 };
 // D: 表の上にグループの札（すべて・各グループ）。選んだグループに絞り、道具の段に「このグループを実行」
 P.D = v => {
  const all = rows(), pick = v === 1 ? '' : v === 2 ? 'pr' : v === 3 ? 'sk' : 'sh';
  const tabs = document.createElement('div'); tabs.className = 'tg-tabs'; tabs.style.position = 'relative';
  tabs.innerHTML = `<button type="button" class="${!pick ? 'on' : ''}">すべて <small>${all.length}</small></button>`
   + [...GROUPS, NONE].map(g => `<button type="button" class="${g.key === pick && pick ? 'on' : ''}"><i class="tg-dot" style="background:${g.color}"></i>${E(g.name)} <small>${all.filter(t => groupOf(t) === g).length}</small></button>`).join('')
   + `<span class="sp"></span>` + (pick ? (v === 3 ? `<span class="tg-prog">実行中 2 / 6<i style="--p:33%"><b></b></i></span>` : btn('tg-run', 'play', `「${E((GROUPS.find(g => g.key === pick) || NONE).name)}」を実行`)) + btn('tg-more', 'more', '') : '')
   + (v === 4 ? menu(GROUPS[2]).replace('tg-menu', 'tg-menu" style="top:34px') : '');
  $('#jobs .tablebox').before(tabs);
  if (pick) all.forEach(t => { if (groupOf(t).key !== pick) t.classList.add('tg-hide'); });
 };
 // E: グループごとの札（見出しを大きく、札と札の間を空ける）
 P.E = v => inTable({ card: true, dot: true, closed: v === 2 ? ['pr', 'mg'] : [], running: v === 3 ? 'sk' : '', menu: v === 4 ? 'sk' : '' });
 // F（方向が違う）: 手で分けず、まとめ方を選ぶ（出力先・予定・入力の種類）。見出し行は自動
 P.F = v => {
  const bar = $('#jobs .jb-idle'); bar?.querySelector('.jb-sp')?.insertAdjacentHTML('beforebegin', `<span class="tg-by"><span>まとめない</span><span class="on">出力先ごと</span><span>予定ごと</span><span>入力の種類ごと</span></span>`);
  // 出力先の代わりに仮のグループ（見た目は同じ）。名前は出力先らしく
  const old = GROUPS.map(g => g.name); const rename = ['\\\\Nlmsrvngy03\\Read\\【New】仕掛\\SQL', '\\\\Nlmsrvngy03\\Read\\生産\\SQL', '\\\\Nlmsrvngy03\\Read\\出荷\\SQL', '\\\\Nlmsrvngy03\\Read\\管理\\SQL'];
  GROUPS.forEach((g, i) => g.name = rename[i]);
  inTable({ closed: v === 2 ? ['pr', 'mg'] : [], running: v === 3 ? 'sk' : '', menu: v === 4 ? 'sk' : '', runLabel: 'この出力先を実行' });
  GROUPS.forEach((g, i) => g.name = old[i]);
 };
 // G（方向が違う）: グループを「実行セット」として持つ。表はそのまま（名前の横に札）。道具の段の「実行セット▾」から実行する
 P.G = v => {
  rows().forEach(t => { const g = groupOf(t); if (g.key) t.querySelector('.primarytext')?.insertAdjacentHTML('beforeend', `<span class="tg-tag" style="background:${g.color}">${E(g.name)}</span>`); });
  const bar = $('#jobs .jb-idle'), anchor = document.createElement('div'); anchor.className = 'jb-anchor tg-set';
  anchor.innerHTML = btn('tbtn', 'layers', '実行セット', '') + (v === 4 || v === 2 ? `<div class="tg-setpop">${GROUPS.map(g => { const s = summary(rows().filter(t => groupOf(t) === g)); return `<div class="row"><i class="tg-dot" style="background:${g.color}"></i><span><b>${E(g.name)}</b> <small>${s.n}件・有効 ${s.on}</small></span>${btn('tg-run', 'play', '実行')}${btn('tg-more', 'more', '')}</div>`; }).join('')}<div class="row">${btn('tbtn', 'plus', '選んだ対象からセットを作る')}</div></div>` : '');
  bar?.querySelector('[data-filter-btn],#filter-open')?.closest('.jb-anchor')?.after(anchor);
  if (v === 3) anchor.insertAdjacentHTML('beforeend', `<span class="tg-prog" style="margin-left:8px">仕掛 実行中 2 / 6<i style="--p:33%"><b></b></i></span>`);
 };

 // ---- 2回目: 組合せ4案（1回目の上位 E・A・B の良いところと、採点で挙がった欠点の直し） ----
 const R2 = v => ({ card: true, dot: true, solid: true, sticky: true, closed: v === 2 ? ['pr', 'mg'] : [], running: v === 3 ? 'sk' : '', menu: v === 4 ? 'sk' : '' });
 // H: E ＋ グループの実行を行の「実行」と同じ塗りに ＋ 見出しを表の上に残す（長いグループでも、どのグループの行か分かる）
 P.H = v => inTable(R2(v));
 // I: H ＋ 見出しのチェックでグループをまとめて選ぶ ＋ 実行中は「実行中…」の代わりに「止める」
 P.I = v => inTable({ ...R2(v), check: true, stop: true });
 // J: H ＋ 表の上にグループの札（押すとそのグループへ跳んで開く）と「すべて畳む／開く」 ＋ 状態を1本の帯でも示す
 P.J = v => { jump(v); inTable({ ...R2(v), seg: true }); };
 // K: H ＋ 見出しに次の予定（いつ動くか） ＋ 止める ＋ 見出しのチェック
 P.K = v => inTable({ ...R2(v), next: true, stop: true, check: true });

 // ---- 3回目: 組合せ4案（2回目の上位 I・J・H の良いところと、残った欠点の直し） ----
 // 直し: 見出しのチェックを行のチェックと同じ列に・貼り付く見出しの隙間を無くす・実行中は札の数も進む
 const R3 = v => ({ ...R2(v), stop: true, check: true, align: true, liveChips: true });
 // L: I ＋ 直し
 P.L = v => inTable(R3(v));
 // M: L ＋ 表の上にグループの札（跳ぶ・確認待ちの点）と「すべて畳む／開く」
 P.M = v => { TG.r3 = true; jump(v); inTable(R3(v)); };
 // N: L ＋ 道具の段に「すべて畳む／開く」（段を増やさない）
 P.N = v => { foldBtn(v); inTable(R3(v)); };
 // O: N ＋ 畳んだ見出しに中の対象の名前を並べる（開かずに何が入っているか分かる）
 P.O = v => { foldBtn(v); inTable({ ...R3(v), names: true }); };
 window.TG = { keys: Object.keys(P), live: false, show(k, v) { st(); const th = $('#jobs-head'); if (th) document.documentElement.style.setProperty('--th', th.offsetHeight + 'px'); P[k](v); if (this.live && v === 3) live('sk'); return true; } };
})();
