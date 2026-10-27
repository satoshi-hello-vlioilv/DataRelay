// 2.13.0 自動実行の一時停止（保守のあいだ、登録した自動実行をまとめて止める）の見せ方の案（CLAUDE.md §3）。
// 中身（止める・期限で戻る・ルールごとの入切を変えない）は本物にできている。ここで比べるのは置き場所と見せ方:
//  ・どこから止めるか ・止める長さの選び方 ・止めている間、それがどの画面からも分かるか ・戻し方
// 撮り方: 本物の画面に読み込み、window.TP.show(k, s) で案の状態にする。
//  s=1 ふだん（止める入口が見えるか） s=2 止める長さを選んでいるところ s=3 止めている間の対象ファイル s=4 止めている間のカレンダー
(() => {
 const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
 const N = { jobs: 17, rules: 20, since: '15:05', until: '23:59' };
 const css = `
 .tp-pill{display:inline-flex;align-items:center;gap:8px;height:var(--ctl-h,38px);padding:0 12px;border-radius:8px;font-size:12px;font-weight:800;white-space:nowrap;cursor:pointer;border:1px solid #ffffff3d;background:#ffffff12;color:#fff}
 .tp-pill i{width:30px;height:16px;border-radius:9px;background:#19b39a;position:relative;flex:0 0 auto}
 .tp-pill i::after{content:'';position:absolute;top:2px;left:16px;width:12px;height:12px;border-radius:50%;background:#fff}
 .tp-pill.off{background:#f5b335;color:#3d2600;border-color:#f5b335}
 .tp-pill.off i{background:#8a5a0c}.tp-pill.off i::after{left:2px}
 .tp-pill small{font-weight:700;opacity:.85}
 .tp-pop{position:fixed;z-index:60;width:360px;background:#fff;color:#17232d;border:1px solid #cfdbe1;border-radius:10px;box-shadow:0 18px 50px #0e253555;padding:14px 16px;font-size:12.5px}
 .tp-pop h3{margin:0 0 4px;font-size:14px;color:#17384e}
 .tp-pop p{margin:0 0 10px;color:#5d707a;line-height:1.55}
 .tp-pop label{display:flex;align-items:center;gap:8px;padding:7px 9px;border:1px solid #dbe5ea;border-radius:7px;margin-bottom:6px;font-weight:700;color:#294f63;cursor:pointer}
 .tp-pop label.on{border-color:#d39a2c;background:#fdf6e9;color:#6b4300}
 .tp-pop label input[type=radio]{width:15px;height:15px;margin:0}
 .tp-pop label small{margin-left:auto;color:#7b8e97;font-weight:600}
 .tp-pop label input[type=text]{flex:0 0 auto;width:92px;height:28px;margin-left:auto;padding:2px 6px}
 .tp-pop .tp-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:10px}
 .tp-go{background:#c27a05;color:#fff}
 .tp-band{display:flex;align-items:center;gap:12px;min-height:38px;margin:0 0 6px;padding:0 12px;border-radius:8px;background:#fdf3df;border:1px solid #efcf8f;color:#6b4300;font-size:12.5px}
 .tp-band b{font-size:13px}.tp-band .tp-sp{flex:1}
 .tp-band button{padding:5px 12px}
 .tp-ic{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#c27a05;color:#fff;font-size:10px;font-weight:900;flex:0 0 auto}
 .rp-next-bit.tp-off{color:#8a5a0c!important;font-weight:800}
 .rp-next-bit.tp-off s{color:#9aa8b0;font-weight:600;margin-left:4px}
 .cal-ev.ev-sched.tp-off,.cal-ev.ev-interval.tp-off{background:repeating-linear-gradient(135deg,#f3f5f6 0 6px,#e9edef 6px 12px)!important;color:#8b9aa2!important;text-decoration:line-through}
 .tp-calnote{display:flex;align-items:center;gap:10px;margin:0 0 8px;padding:7px 12px;border-radius:8px;background:#fdf3df;border:1px solid #efcf8f;color:#6b4300;font-size:12.5px}
 .tp-banner{flex:0 0 auto;margin:8px 0 0;border-radius:8px;display:flex;align-items:center;gap:12px;padding:7px var(--app-pad,16px);background:#f5b335;color:#3d2600;font-size:13px;font-weight:700}
 .tp-banner .tp-sp{flex:1}.tp-banner button{background:#3d2600;color:#fff;padding:5px 12px}
 .tp-modal{position:fixed;inset:0;z-index:70;background:#0d2433a8;display:grid;place-items:center}
 .tp-modal>div{width:620px;background:#fff;border-radius:12px;box-shadow:0 25px 80px #0e25358c}
 .tp-modal .mh{padding:14px 18px;border-bottom:1px solid #d7e0e5}.tp-modal .mh small{color:#087c98;font-weight:800}.tp-modal .mh h2{margin:2px 0 0;font-size:20px}
 .tp-modal .mb{padding:14px 18px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
 .tp-modal .mf{display:flex;justify-content:flex-end;gap:8px;padding:11px 18px;border-top:1px solid #d7e0e5;background:#f8fafb}
 .tp-skip{font-size:12px;color:#425661}.tp-skip b{display:block;margin-bottom:6px;color:#17384e}
 .tp-skip li{list-style:none;padding:4px 8px;border-radius:5px;background:#f3f5f6;margin-bottom:4px;text-decoration:line-through;color:#6b7f88}
 .tp-skip ul{margin:0;padding:0}
 .tp-quick{background:#ffffff14;border:1px solid #ffffff45;color:#fff}
 .tp-chip{display:inline-flex;align-items:center;gap:8px;height:var(--ctl-h,38px);padding:0 6px 0 12px;border-radius:8px;background:#f5b335;color:#3d2600;font-size:12px;font-weight:800;white-space:nowrap}
 .tp-chip button{padding:4px 9px;font-size:11.5px;background:#3d2600;color:#fff}
 .tp-chip button.ghost2{background:#ffffff8c;color:#3d2600}
 .tp-sw{display:inline-flex;align-items:center;gap:8px;padding:5px 10px;border-radius:999px;border:1px solid #cfe0e6;background:#fff;color:#294f63;font-size:12px;font-weight:800;cursor:pointer}
 .tp-sw i{width:28px;height:15px;border-radius:9px;background:#19b39a;position:relative}
 .tp-sw i::after{content:'';position:absolute;top:2px;left:15px;width:11px;height:11px;border-radius:50%;background:#fff}
 .tp-sw.off{background:#fdf3df;border-color:#efcf8f;color:#6b4300}.tp-sw.off i{background:#c27a05}.tp-sw.off i::after{left:2px}
 .tp-set{padding:18px 22px;background:#fff;border:1px solid #d7e0e5;border-radius:10px;max-width:760px}
 .tp-set h3{margin:0 0 4px;font-size:16px;color:#17384e}
 .tp-runtime-off{background:#f5b33526!important;box-shadow:inset 0 0 0 1px #f5b335}
 .tp-runtime-off #dot{background:#f5b335!important}
 `;
 const ensureCss = () => { if (!$('#tp-css')) { const s = document.createElement('style'); s.id = 'tp-css'; s.textContent = css; document.head.append(s); } };
 const tab = p => { document.querySelector(`nav button[data-p="${p}"]`)?.click(); };
 const at = (el, html, where = 'beforebegin') => { el.insertAdjacentHTML(where, html); };
 const place = (pop, anchor, align = 'right') => {
  const r = anchor.getBoundingClientRect(), w = pop.offsetWidth;
  pop.style.top = (r.bottom + 8) + 'px';
  pop.style.left = Math.max(12, Math.min(innerWidth - w - 12, align === 'right' ? r.right - w : r.left)) + 'px';
 };
 const choices = (sel = 1) => [
  ['1時間', '16:05 に再開'], ['今日の終わりまで', '23:59 に再開'], ['時刻を決める', '<input type="text" value="18:00" style="text-align:center">'], ['手で再開するまで', '']
 ].map(([t, s], i) => `<label class="${i === sel ? 'on' : ''}"><input type="radio" name="tp" ${i === sel ? 'checked' : ''}>${t}${s.startsWith('<') ? s : s ? `<small>${s}</small>` : ''}</label>`).join('');
 const popHtml = (title = '自動実行を一時停止', sel = 1) => `<div class="tp-pop"><h3>${title}</h3><p>${N.jobs}件の対象・${N.rules}ルールの自動実行を止めます。ルールごとの設定は変えません。手動の実行はできます。</p>${choices(sel)}<div class="tp-foot"><button class="secondary">やめる</button><button class="tp-go">止める</button></div></div>`;
 const pauseRows = () => $$('.rp-next-bit').forEach(e => { const t = e.textContent; if (!/^次は\s*本日/.test(t)) return; e.classList.add('tp-off'); e.innerHTML = `止めています<s>${t.replace(/^次は\s*/, '')}</s>`; });
 const pauseCal = () => { clearInterval(window.__tpCal); window.__tpCal = setInterval(markCal, 150); markCal(); };
 const markCal = () => {
  $$('#cal-grid .cal-cell[data-iso]').forEach(c => {
   const iso = c.dataset.iso, today = $('#cal-grid .cal-today')?.dataset.iso || '';
   if (iso === today) c.querySelectorAll('.cal-ev.ev-sched,.cal-ev.ev-interval').forEach(e => { const tm = (e.textContent.match(/^(\d\d):(\d\d)/) || [])[0]; if (e.classList.contains('ev-interval') || (tm && tm >= N.since)) e.classList.add('tp-off'); });
  });
 };
 const runAllBtn = () => $('#run-all');
 const band = (extra = '') => `<div class="tp-band" id="tp-band"><span class="tp-ic">Ⅱ</span><b>自動実行を止めています</b><span>${N.since} から・${N.until} に自動で再開（${N.jobs}件の対象・${N.rules}ルール）${extra}</span><span class="tp-sp"></span><button class="secondary">いま再開する</button></div>`;
 const calNote = (btn = true) => `<div class="tp-calnote" id="tp-calnote"><span class="tp-ic">Ⅱ</span><b>自動実行を止めています</b><span>${N.until} に自動で再開。斜線の予定は実行しません</span><span style="flex:1"></span>${btn ? '<button class="secondary">いま再開する</button>' : ''}</div>`;
 const calTop = () => $('#calendar .cal-shell');
 const jobsTop = () => $('#jobs .jobbar');

 const V = {
  // A: 窓の上の帯に「自動実行」のスイッチ。押すと長さを選ぶ吹き出し。止めている間はスイッチが黄色に変わり、再開の時刻を添える
  A(s) {
   const pill = off => `<button class="tp-pill ${off ? 'off' : ''}" id="tp-pill"><i></i>自動実行${off ? `<small>止めています・${N.until} に再開</small>` : '<small>動いています</small>'}</button>`;
   if (s === 4) tab('calendar');
   at(runAllBtn(), pill(s >= 3));
   if (s === 2) { document.body.insertAdjacentHTML('beforeend', popHtml()); place($('.tp-pop'), $('#tp-pill')); }
   if (s === 3) pauseRows();
   if (s === 4) pauseCal();
  },
  // B: 対象ファイルの上の段（件数の隣）にスイッチ。止めている間は一覧の上に黄色い帯と「いま再開する」
  B(s) {
   if (s === 4) tab('calendar');
   const sw = off => `<button class="tp-sw ${off ? 'off' : ''}" id="tp-sw"><i></i>自動実行 ${off ? '止めています' : '動いています'}</button>`;
   at($('#filter-open').closest('.jb-anchor'), sw(s >= 3));
   if (s === 2) { document.body.insertAdjacentHTML('beforeend', popHtml()); place($('.tp-pop'), $('#tp-sw'), 'left'); }
   if (s === 3) { at(jobsTop(), band(), 'afterend'); pauseRows(); }
   if (s === 4) pauseCal();
  },
  // C: カレンダーが入口。予定の見える場所で止める長さを決め、止める範囲を斜線で示す。対象ファイルには件数の隣に小さな札だけ
  C(s) {
   if (s !== 3) tab('calendar');
   const btn = `<button class="secondary" id="tp-calbtn">自動実行を一時停止…</button>`;
   const head = $('#calendar .cal-shell [class*="cal-view"], #calendar .cal-shell .seg') || $('#cal-title');
   if (s !== 3) at(head, btn, head.id === 'cal-title' ? 'afterend' : 'beforebegin');
   if (s === 2) { document.body.insertAdjacentHTML('beforeend', popHtml()); place($('.tp-pop'), $('#tp-calbtn'), 'left'); pauseCal(); }
   if (s === 3) { at($('#filter-open').closest('.jb-anchor'), `<span class="tp-sw off"><i></i>自動実行 止めています</span>`); pauseRows(); }
   if (s === 4) { at(calTop(), calNote(), 'afterbegin'); pauseCal(); }
  },
  // D: 終了ボタンの横の▼（終わり方のメニュー）に「自動実行を一時停止」。止めている間は右上の状態の札が黄色く「自動実行を止めています」
  D(s) {
   if (s === 4) tab('calendar');
   if (s === 2) {
    $('#exit-menu').hidden = false;
    $('#exit-menu').insertAdjacentHTML('beforeend', `<hr style="margin:4px 0;border:0;border-top:1px solid #e3eaee"><button type="button" role="menuitem" style="background:#fdf6e9"><b>自動実行を一時停止…</b><small>1時間・今日の終わりまで・時刻・手で再開するまで</small></button>`);
   }
   if (s >= 3) { const r = $('.runtime'); r.classList.add('tp-runtime-off'); r.querySelector('.rt-text').style.display = 'none'; r.insertAdjacentHTML('beforeend', `<span class="rt-text"><b>自動実行を停止中</b><span>${N.until} に再開</span></span>`); }
   if (s === 3) pauseRows();
   if (s === 4) pauseCal();
  },
  // E: 共通設定に「自動実行」の項目（スイッチと長さ）。止めている間は、どのタブでも窓のいちばん上に黄色い帯
  E(s) {
   if (s === 2) {
    tab('paths');
    const host = $('#paths .settings-main, #paths .settings-body, #paths') ;
    host.insertAdjacentHTML('afterbegin', `<div class="tp-set" id="tp-set" style="margin:14px 0"><h3>自動実行</h3><p style="margin:0 0 12px;color:#5d707a;font-size:12.5px">保守の間など、登録した自動実行をまとめて止めます。ルールごとの設定は変えません。</p><div style="display:flex;align-items:center;gap:10px;margin-bottom:10px"><span class="tp-sw off"><i></i>止める</span></div><div class="tp-pop" style="position:static;box-shadow:none;width:auto;border:0;padding:0">${choices(1)}</div></div>`);
   }
   if (s >= 3) { $('body>main').insertAdjacentHTML('afterbegin', `<div class="tp-banner" id="tp-banner"><span class="tp-ic" style="background:#3d2600">Ⅱ</span>自動実行を止めています（${N.since} から・${N.until} に自動で再開・${N.jobs}件の対象）<span class="tp-sp"></span><button>いま再開する</button></div>`); }
   if (s === 3) pauseRows();
   if (s === 4) { tab('calendar'); pauseCal(); }
  },
  // F（既定で済ませる）: 「1時間止める」を1回押すだけで止まる。止めている間は残り時間の札に「延ばす」「再開」。長さを変えたいときだけ札の▼
  F(s) {
   if (s === 4) tab('calendar');
   if (s === 1) at(runAllBtn(), `<button class="ctl tp-quick" id="tp-quick">Ⅱ 自動実行を1時間止める</button>`);
   if (s >= 2) at(runAllBtn(), `<span class="tp-chip" id="tp-chip"><span class="tp-ic" style="background:#3d2600">Ⅱ</span>自動実行を止めています・残り ${s === 2 ? '60' : '42'}分<button class="ghost2" id="tp-ext">延ばす ▾</button><button>再開</button></span>`);
   if (s === 2) {
    document.body.insertAdjacentHTML('beforeend', `<div class="tp-pop" style="width:300px"><h3>止める長さを変える</h3>${[['あと1時間', '16:47 まで'], ['今日の終わりまで', '23:59 まで'], ['時刻を決める', '<input type="text" value="18:00" style="text-align:center">'], ['手で再開するまで', '']].map(([t, x], i) => `<label class="${i === 0 ? 'on' : ''}"><input type="radio" name="tf" ${i === 0 ? 'checked' : ''}>${t}${x.startsWith('<') ? x : x ? `<small>${x}</small>` : ''}</label>`).join('')}</div>`);
    place($('.tp-pop'), $('#tp-ext'));
   }
   if (s === 3) pauseRows();
   if (s === 4) pauseCal();
  },
  // G（手順を分ける）: 「自動実行を止める…」で専用の窓。長さを選ぶと、その間に飛ばす予定が右に並ぶ（何が止まるかを見てから止める）
  G(s) {
   if (s === 4) tab('calendar');
   if (s <= 2) at(runAllBtn(), `<button class="ctl tp-quick" id="tp-open">Ⅱ 自動実行を止める…</button>`);
   if (s >= 3) at(runAllBtn(), `<span class="tp-chip"><span class="tp-ic" style="background:#3d2600">Ⅱ</span>自動実行を止めています・${N.until} に再開<button>再開</button></span>`);
   if (s === 2) document.body.insertAdjacentHTML('beforeend', `<div class="tp-modal"><div><div class="mh"><small>自動実行</small><h2>自動実行を一時停止</h2></div><div class="mb"><div class="tp-pop" style="position:static;box-shadow:none;border:0;padding:0;width:auto"><p>ルールごとの設定は変えません。手動の実行はできます。</p>${choices(1)}</div><div class="tp-skip"><b>この間に飛ばす予定 6件</b><ul><li>16:00 BOXTRACK</li><li>16:00 PRODPLAN</li><li>18:00 ANNEAL</li><li>18:00 BOXTRACK</li><li>定期（1時間ごと） 2件</li></ul><p style="margin-top:8px;color:#5d707a">明日 06:00 からは、ふだんどおり動きます</p></div></div><div class="mf"><button class="secondary">やめる</button><button class="tp-go">6件を飛ばして止める</button></div></div></div>`);
   if (s === 3) { at(jobsTop(), band(), 'afterend'); pauseRows(); }
   if (s === 4) { at(calTop(), calNote(), 'afterbegin'); pauseCal(); }
  },
 };
 window.TP = { keys: Object.keys(V), show(k, s) { ensureCss(); V[k](s); } };
})();
