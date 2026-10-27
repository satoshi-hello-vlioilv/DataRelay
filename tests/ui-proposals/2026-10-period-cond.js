// 2.14.0 抽出期間の見せ方の案（CLAUDE.md §3）。条件欄の日付（時間型の管理ポイントが無い RNE）と、範囲の形（期間・以降・以前）を足す。
// 中身（計算・当て方・読み戻し）は本物にできている。ここで比べるのは、対象の設定の「2 抽出期間」の組み方だけ。
// 撮り方: 本物の画面で対象の設定を開き、window.TPD.show(k, s) で #period-body を案の形に差し替える。
//  s=1 条件欄の日付（払出日）・期間 3ヶ月前〜1ヶ月前  s=2 同じ RNE で「以降」  s=3 時間管理ポイント（月度）の RNE
(() => {
 const $ = s => document.querySelector(s);
 const S = {
  1: { t: 'cond', item: '払出日', rne: '2026/1/1 以降', range: 'between', unit: 'month', fo: 3, to: 1, lo: '2026/7/1', hi: '2026/9/30', prev: '2026/7/1 ～ 2026/9/30' },
  2: { t: 'cond', item: '払出日', rne: '2026/1/1 以降', range: 'from', unit: 'month', fo: 3, to: 0, lo: '2026/7/1', hi: '', prev: '2026/7/1 以降' },
  3: { t: 'point', cp: '月度', range: 'between', unit: 'month', fo: 1, to: 0, lo: '2026年9月度', hi: '2026年10月度', prev: '2026年9月度 ～ 2026年10月度' },
 };
 const css = `
 #period-body.tpd{display:grid;gap:12px}
 .tpd h4{margin:0;font-size:11.5px;font-weight:800;color:#43616b;letter-spacing:.02em;display:flex;align-items:center;gap:8px}
 .tpd h4 small{font-weight:600;color:#7d9098;font-size:10.5px}
 .tpd .seg{display:inline-flex;background:#eaf1f3;border:1px solid #d3e0e4;border-radius:8px;padding:3px;gap:3px}
 .tpd .seg button{background:transparent;color:#456;font-size:12px;padding:6px 14px;border-radius:6px;white-space:nowrap}
 .tpd .seg button.on{background:#fff;color:#08727f;box-shadow:0 1px 3px #15384d1f}
 .tpd .seg button:disabled{opacity:.45}
 .tpd .num{width:58px;height:32px;text-align:center;font-weight:700}
 .tpd .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;color:#2c4d58}
 .tpd .box{background:#fff;border:1px solid #cddce2;border-radius:9px;padding:9px 11px}
 .tpd .pv{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;background:#0f2b33;color:#e7f5f7;border-radius:8px;padding:9px 12px}
 .tpd .pv span{font-size:10px;font-weight:800;letter-spacing:.08em;color:#7fd4dd}.tpd .pv b{font-size:16px}.tpd .pv small{font-size:11px;color:#a9cbd2}
 .tpd .card{display:grid;gap:3px;text-align:left;background:#fff;border:1px solid #cddce2;border-radius:10px;padding:10px 12px;color:#294f63;cursor:pointer}
 .tpd .card.on{border:2px solid #14979e;background:#effafa;padding:9px 11px}
 .tpd .card b{font-size:13px}.tpd .card small{font-size:11px;color:#6b8089;font-weight:600}
 .tpd .card:disabled{opacity:.5}
 .tpd .chip2{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;background:#eaf6f8;border:1px solid #bfe1e6;color:#0b6570;font-size:11.5px;font-weight:800}
 .tpd .note{font-size:11px;color:#6b8089}
 .tpd select{height:32px;width:auto;padding:2px 8px}
 .tpd .tl{position:relative;height:58px;margin:4px 6px 0}
 .tpd .tl .axis{position:absolute;left:0;right:0;top:26px;height:6px;border-radius:3px;background:#e3ecef}
 .tpd .tl .rng{position:absolute;top:22px;height:14px;border-radius:7px;background:#22a6b0}
 .tpd .tl .rng.open{border-top-right-radius:0;border-bottom-right-radius:0;background:linear-gradient(90deg,#22a6b0 80%,#22a6b000)}
 .tpd .tl .tick{position:absolute;top:40px;font-size:10.5px;color:#6b8089;transform:translateX(-50%);white-space:nowrap}
 .tpd .tl .now{position:absolute;top:12px;bottom:18px;width:2px;background:#d04a3a}
 .tpd .tl .now::after{content:'今日';position:absolute;top:-13px;left:-10px;white-space:nowrap;font-size:10px;font-weight:800;color:#d04a3a}
 .tpd .tl .lab{position:absolute;top:2px;font-size:11px;font-weight:800;color:#0b6570;transform:translateX(-50%);white-space:nowrap}
 .tpd .two{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:14px;align-items:start}
 .tpd .cal{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
 .tpd .cal i{font-style:normal;text-align:center;padding:7px 0;border-radius:7px;background:#f1f5f7;color:#6b8089;font-size:11.5px;font-weight:700}
 .tpd .cal i.in{background:#22a6b0;color:#fff}.tpd .cal i.now{outline:2px solid #d04a3a;outline-offset:-2px}
 .tpd .presets{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
 .tpd .step{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px;align-items:center;padding:9px 0;border-bottom:1px dashed #dbe5ea}
 .tpd .step:last-of-type{border-bottom:0}
 .tpd .step>b{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#20404a}
 .tpd .step>b i{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#14979e;color:#fff;font-style:normal;font-size:11px}
 .tpd .found{display:flex;align-items:center;gap:10px;background:#effafa;border:1px solid #bfe1e6;border-radius:10px;padding:10px 12px;font-size:12.5px;color:#20404a}
 .tpd .found b{font-size:13px}
 .tpd .ln{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:14px;color:#20404a;line-height:2.2}
 .tpd .ln select,.tpd .ln input{font-size:13px}
 `;
 const seg = (opts, on, dis = []) => `<span class="seg">${opts.map(([v, l]) => `<button type="button" class="${v === on ? 'on' : ''}" ${dis.includes(v) ? 'disabled' : ''}>${l}</button>`).join('')}</span>`;
 const unitSeg = s => seg([['month', '月'], ['day', '日']], s.unit);
 const rangeSeg = s => seg([['between', '期間'], ['from', '以降'], ['to', '以前']], s.range, s.t === 'point' ? ['from', 'to'] : []);
 const off = (n, base) => `<span class="row"><input class="num" value="${n}"> ${base}</span>`;
 const startTxt = s => s.t === 'cond' ? (s.unit === 'month' ? 'ヶ月前の1日' : '日前') : 'ヶ月前（月度）';
 const endTxt = s => s.t === 'cond' ? (s.unit === 'month' ? 'ヶ月前の末日' : '日前') : 'ヶ月前（月度）';
 const pv = s => `<div class="pv"><span>抽出範囲プレビュー</span><b>${s.prev}</b><small>${s.t === 'cond' ? `条件欄「${s.item}」をこの範囲に差し替えます（RNE では ${s.rne}）` : `時間管理ポイント「${s.cp}」の期間を差し替えます`} ／ 処理日時 2026-10-27 基準</small></div>`;
 const target = s => s.t === 'cond' ? `<span class="chip2">条件欄の日付 ・ ${s.item}</span><span class="note">RNE では ${s.rne}</span>` : `<span class="chip2">時間管理ポイント ・ ${s.cp}</span>`;
 const V = {
  // A: 上から「当てる先」2枚のカード →「範囲の形」→「いつから・いつまで」→ プレビュー
  A: s => `<h4>当てる先 <small>RNE から見つけた日付の絞り込み</small></h4>
   <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
    <button type="button" class="card ${s.t === 'point' ? 'on' : ''}" ${s.t === 'cond' ? 'disabled' : ''}><b>時間管理ポイント</b><small>${s.t === 'point' ? '月度（この RNE の時間型）' : 'この RNE にはありません'}</small></button>
    <button type="button" class="card ${s.t === 'cond' ? 'on' : ''}" ${s.t === 'point' ? 'disabled' : ''}><b>条件欄の日付</b><small>${s.t === 'cond' ? `${s.item}（RNE では ${s.rne}）` : 'この RNE にはありません'}</small></button></div>
   <h4>範囲の形 ${s.t === 'point' ? '<small>時間管理ポイントは「期間」だけです</small>' : ''}</h4><div>${rangeSeg(s)}</div>
   <h4>いつから・いつまで <small>単位</small> ${unitSeg(s)}</h4>
   <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
    <div class="box"><span class="note">開始</span><div class="row">${s.range === 'to' ? '<span class="note">（決めない）</span>' : `今日から ${off(s.fo, startTxt(s))}`}</div></div>
    <div class="box"><span class="note">終了</span><div class="row">${s.range === 'from' ? '<span class="note">（決めない＝今日以降も含む）</span>' : `今日から ${off(s.to, endTxt(s))}`}</div></div></div>
   ${pv(s)}`,
  // B: 1文で組み立てる（文の中に入力を置く）
  B: s => `<h4>抽出する日付の範囲 <small>文を読むように決めます</small></h4>
   <div class="box"><div class="ln"><select><option>${s.t === 'cond' ? `条件欄の ${s.item}` : `時間管理ポイントの ${s.cp}`}</option></select> が
   ${s.range === 'to' ? '' : `<input class="num" value="${s.fo}"><select><option>${startTxt(s)}</option></select>`}
   <select><option>${{ between: 'から', from: 'から（終わりなし）', to: '' }[s.range]}</option></select>
   ${s.range === 'from' ? '' : `<input class="num" value="${s.to}"><select><option>${endTxt(s)}</option></select> まで`}</div></div>
   ${pv(s)}`,
  // C: 時間の線で範囲を見せる（今日の印と、色の帯）。入力は帯の下に1行
  C: s => {
   const pos = { 2026.06: 6, 2026.07: 20, 2026.08: 34, 2026.09: 48, 2026.10: 62, 2026.11: 76 };
   const L = 20, R = s.range === 'from' ? 100 : (s.t === 'point' ? 76 : 62), Lp = s.t === 'point' ? 48 : L;
   return `<h4>抽出する範囲 ${target(s)}</h4>
   <div class="tl"><div class="axis"></div><div class="rng ${s.range === 'from' ? 'open' : ''}" style="left:${Lp}%;right:${100 - R}%"></div>
   ${['6月', '7月', '8月', '9月', '10月', '11月'].map((m, i) => `<span class="tick" style="left:${6 + i * 14}%">${m}</span>`).join('')}
   <span class="now" style="left:${62 + 14 * 26 / 31}%"></span><span class="lab" style="left:${Lp}%">${s.lo}</span>${s.hi ? `<span class="lab" style="left:${R}%">${s.hi}</span>` : ''}</div>
   <div class="row">${rangeSeg(s)} ${unitSeg(s)} ${s.range !== 'to' ? `開始 ${off(s.fo, startTxt(s))}` : ''} ${s.range !== 'from' ? `終了 ${off(s.to, endTxt(s))}` : ''}</div>
   ${pv(s)}`;
  },
  // D: 左に決めること、右に大きな結果（月の並びに色）
  D: s => `<div class="two"><div style="display:grid;gap:10px">
    <h4>当てる先</h4><div class="row">${target(s)}</div>
    <h4>範囲の形</h4><div>${rangeSeg(s)}</div>
    <h4>単位</h4><div>${unitSeg(s)}</div>
    <div class="row">${s.range !== 'to' ? `開始 ${off(s.fo, startTxt(s))}` : ''}</div><div class="row">${s.range !== 'from' ? `終了 ${off(s.to, endTxt(s))}` : ''}</div></div>
   <div style="display:grid;gap:8px"><h4>抽出される範囲</h4><b style="font-size:20px;color:#0b4f5c">${s.prev}</b>
    <div class="cal">${['6月', '7月', '8月', '9月', '10月', '11月', '12月', '1月'].map((m, i) => `<i class="${(s.t === 'point' ? (i === 3 || i === 4) : s.range === 'from' ? i >= 1 : (i >= 1 && i <= 3)) ? 'in' : ''} ${i === 4 ? 'now' : ''}">${m}</i>`).join('')}</div>
    <span class="note">${s.t === 'cond' ? `条件欄「${s.item}」を差し替えます（RNE では ${s.rne}）` : `時間管理ポイント「${s.cp}」の期間を差し替えます`}</span></div></div>`,
  // E: よく使う形をカードで先に出し、結果の日付をカードに書く。細かい設定は下に畳む
  E: s => `<h4>よく使う範囲 <small>押すとそのまま決まります（結果の日付つき）</small></h4>
   <div class="presets">${(s.t === 'cond' ? [['直近3ヶ月（以降）', '2026/7/1 以降', s.range === 'from'], ['3ヶ月前〜先月', '2026/7/1 ～ 2026/9/30', s.range === 'between'], ['先月', '2026/9/1 ～ 2026/9/30'], ['今月', '2026/10/1 以降'], ['過去7日', '2026/10/20 以降'], ['昨日まで', '2026/10/26 以前'], ['前年', '2025/1/1 ～ 2025/12/31'], ['今年', '2026/1/1 以降']] : [['今月度', '2026年10月度'], ['前月度', '2026年9月度'], ['前月〜今月', '2026年9月度 ～ 10月度', true], ['3ヶ月前〜今月', '2026年7月度 ～ 10月度'], ['当日', '2026-10-27'], ['前日', '2026-10-26'], ['過去7日', '2026-10-21 ～ 27'], ['前日〜当日', '2026-10-26 ～ 27']]).map(([t, d, on]) => `<button type="button" class="card ${on ? 'on' : ''}"><b>${t}</b><small>${d}</small></button>`).join('')}</div>
   <details class="box" open><summary style="font-size:12px;font-weight:800;color:#43616b;cursor:pointer">細かく決める</summary><div class="row" style="margin-top:8px">${target(s)} ${rangeSeg(s)} ${unitSeg(s)} ${s.range !== 'to' ? `開始 ${off(s.fo, startTxt(s))}` : ''} ${s.range !== 'from' ? `終了 ${off(s.to, endTxt(s))}` : ''}</div></details>
   ${pv(s)}`,
  // F（既定で済ませる）: RNE を読んで見つけた絞り込みを1行で示し、「何ヶ月前から」だけを聞く。形・単位は見つけた物を既定にし、変えるときだけ開く
  F: s => `<div class="found"><b>${s.t === 'cond' ? `この RNE は条件欄の「${s.item}」で日付を絞っています` : `この RNE は時間管理ポイント「${s.cp}」で期間を絞っています`}</b><span class="note">${s.t === 'cond' ? `いまは ${s.rne}。実行のたびに、下の範囲へ差し替えます` : '実行のたびに、下の範囲へ差し替えます'}</span></div>
   <div class="box"><div class="ln">${s.range === 'to' ? '' : `<input class="num" value="${s.fo}"> ${startTxt(s)}`} ${{ between: 'から', from: 'から（終わりなし）', to: '' }[s.range]} ${s.range === 'from' ? '' : `<input class="num" value="${s.to}"> ${endTxt(s)} まで`}</div>
   <div class="row" style="margin-top:6px"><span class="note">範囲の形</span>${rangeSeg(s)}<span class="note" style="margin-left:10px">単位</span>${unitSeg(s)}</div></div>
   ${pv(s)}`,
  // G（手順を分ける）: ①どの日付で ②どんな形で ③どれだけ前から、を番号つきの3段に分ける
  G: s => `<div class="box" style="padding:4px 14px">
   <div class="step"><b><i>1</i>どの日付で絞るか</b><div class="row">${target(s)}</div></div>
   <div class="step"><b><i>2</i>どんな形で</b><div class="row">${rangeSeg(s)} <span class="note">${{ between: '始まりと終わりの両方を決めます', from: '始まりだけ決め、それ以降をすべて取ります', to: '終わりだけ決め、それ以前をすべて取ります' }[s.range]}</span></div></div>
   <div class="step"><b><i>3</i>いつから・いつまで</b><div class="row">${unitSeg(s)} ${s.range !== 'to' ? `開始 ${off(s.fo, startTxt(s))}` : ''} ${s.range !== 'from' ? `終了 ${off(s.to, endTxt(s))}` : ''}</div></div></div>
   ${pv(s)}`,
 };
 window.TPD = { keys: Object.keys(V), show(k, s) {
  if (!$('#tpd-css')) { const e = document.createElement('style'); e.id = 'tpd-css'; e.textContent = css; document.head.append(e); }
  const d = $('.period-enable-text small'); if (d) d.textContent = 'RNE の日付の絞り込み（時間管理ポイント、または条件欄の日付）を、実行のたびに相対の日付へ差し替えます。RNE ファイルは変えません（定期実行での日付更新に）。';
  const b = $('#period-body'); b.hidden = false; b.classList.add('tpd'); b.innerHTML = V[k](S[s]);
 } };
})();
