// 2.8.0 読取マスタ: 一覧を見渡しやすくする ＋ 区切り（記号・決まり）で読む方式を足す、の案（CLAUDE.md §3）。
// いま: 一覧は1件が5〜6行のカード（名前・形・用途メモ全文）で、30件のうち6件しか見えない。読み方は固定長だけ。
// 本物の画面（共通設定 → 読取マスタ。撮影用の環境に 固定長31件＋区切り5件）の .lay-wrap を案ごとに描き替える。
// 一覧の中身・形（/api/text-layouts の shape）・見本の値（/api/text-sniff・/api/text-preview）は本物の受け口の結果。
// 撮り方: await window.LL.show(k, view)。view 1 = 固定長のマスタ（スラブマスター）を開いたところ、
// view 2 = 区切りのマスタ（受注明細CSV）を開いたところ。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は上位3案 G・D・C と組合せ案 H〜K。
// 組合せ案で全案に共通した減点も直す: 名前が切れる（一覧の幅・印の列）／保存の帯が下の帯に隠れる・削除が保存の隣
// （保存は見出しの右へ、削除は下に離す）／1536 で列の表が見えない（読み方の欄を1段に詰める）／「固」と「固定長」の言い分け。
// 3回目は上位3案 H・I・K と組合せ案 L〜O。2回目で全案に残った欠点も直す: 名前が切れる（一覧を広げ、印を行の左の色の帯に）／
// スクロールの途中で欠けた行が見出しの下に透ける（行の頭で止める scroll-snap）／［保存］と下の帯「変更はすべて自動で保存されます」の食い違い
// （L・M・N は他の設定と同じく自動で保存し、状態だけを出す。O は保存を残し、下の帯の言葉をこの画面に合わせる）。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json());
 const CSS = `
 .ll *{box-sizing:border-box}
 .ll-wrap{display:grid;grid-template-columns:var(--ll-w,290px) minmax(0,1fr);gap:10px;align-items:start}
 .ll-pane{background:#fff;border:1px solid #dfe8eb;border-radius:11px;padding:10px;display:grid;gap:6px;position:sticky;top:0}
 .ll-pane h2{font-size:14px;margin:0;display:flex;align-items:center;gap:8px;white-space:nowrap}.ll-pane h2 small{font-size:11px;color:#6b7f88;font-weight:700}
 .ll-list{display:grid;gap:1px;max-height:calc(100vh - 350px);overflow:auto;align-content:start}
 .ll-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:7px;height:30px;padding:0 8px;border-radius:6px;background:transparent;color:#22404d;text-align:left;font-weight:600;font-size:12.5px;border:1px solid transparent}
 .ll-row:hover{background:#f0f7f9}.ll-row.on{background:#e3f2f5;border-color:#0d8191;color:#0b4f5c;font-weight:800}
 .ll-row .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .ll-row .mt{font-size:11px;color:#6b7f88;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums}
 .ll-tag{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:5px;font-size:10px;font-weight:900;font-style:normal;flex:none}
 .ll-tag.fx{background:#e3f1f4;color:#0b6577}.ll-tag.dl{background:#efe8f8;color:#5c3f96}
 .ll-tag.w{width:auto;padding:0 6px}
 .ll-row2{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1px 8px;padding:6px 9px;border-radius:7px;text-align:left;background:transparent;color:#22404d;border:1px solid transparent;height:auto}
 .ll-row2:hover{background:#f0f7f9}.ll-row2.on{background:#e3f2f5;border-color:#0d8191}
 .ll-row2 b{font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ll-row2 small{grid-column:1/-1;font-size:11px;color:#6b7f88;display:flex;gap:6px;align-items:center;white-space:nowrap;overflow:hidden}
 .ll-use{font-size:10.5px;font-weight:800;color:#087a57;background:#e5f5ef;border-radius:999px;padding:1px 7px;white-space:nowrap}
 .ll-grp{display:flex;align-items:center;gap:7px;padding:7px 6px 3px;font-size:11px;font-weight:900;color:#4f6873;position:sticky;top:0;background:#fff;z-index:1}
 .ll-grp i{font-style:normal}.ll-grp b{font-weight:800;color:#8b9ca3}
 .ll-exp{display:grid;gap:4px;margin:0 0 4px;padding:6px 9px 8px 33px;font-size:11px;color:#55707a;background:#f3f9fa;border-radius:0 0 7px 7px;line-height:1.55}
 .ll-tbl{border-collapse:collapse;width:100%;font-size:12px;table-layout:fixed}
 .ll-tbl th{position:sticky;top:0;z-index:2;scroll-snap-align:none;box-shadow:0 -10px 0 #fff;background:#f0f5f6;color:#4f6873;text-align:left;font-size:11px;padding:5px 8px;border-bottom:1px solid #dce6ea;white-space:nowrap}
 .ll-tbl td{padding:0 8px;height:30px;border-bottom:1px solid #eef3f5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#22404d}
 .ll-tbl tr.on td{background:#e3f2f5;font-weight:800;color:#0b4f5c}.ll-tbl td.n{text-align:right;font-variant-numeric:tabular-nums;color:#55707a}
 .ll-tbl td.d{color:#6b7f88}
 .ll-count{font-size:11px;color:#6b7f88;display:flex;gap:10px;align-items:center}
 .ll-filter{display:inline-flex;border:1px solid #c8d6dc;border-radius:7px;overflow:hidden}.ll-filter span{padding:3px 10px;font-size:11px;font-weight:800;color:#5a727c;border-left:1px solid #e3ebee}.ll-filter span:first-child{border-left:0}.ll-filter span.on{background:#0b6577;color:#fff}
 /* 編集 */
 .ll-edit{padding:14px 16px;margin:0;display:grid;gap:10px}
 .ll-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.ll-head h2{margin:0;font-size:17px}
 .ll-seg{display:inline-flex;border:1px solid #c8d6dc;border-radius:9px;overflow:hidden;background:#fff}
 .ll-seg span{display:grid;gap:0;padding:5px 14px;font-weight:800;font-size:12.5px;color:#5a727c;border-left:1px solid #e3ebee;white-space:nowrap;line-height:1.35}
 .ll-seg span small{font-size:10.5px;font-weight:600;color:inherit;opacity:.8}
 .ll-seg span:first-child{border-left:0}.ll-seg span.on{background:#0b6577;color:#fff}
 .ll-seg.big span{padding:8px 18px}
 .ll-chips{display:flex;gap:5px;flex-wrap:wrap;align-items:center}
 .ll-chips span{height:30px;display:inline-flex;align-items:center;padding:0 11px;border:1px solid #c8d6dc;border-radius:7px;font-size:12px;font-weight:700;color:#35505b;background:#fff;white-space:nowrap}
 .ll-chips span.on{background:#e3f2f5;border-color:#0b6577;color:#0b4f5c;box-shadow:inset 0 0 0 1px #0b6577}
 .ll-chips input{width:120px;height:30px}
 .ll-grid{display:grid;gap:8px 12px;grid-template-columns:repeat(4,minmax(0,1fr))}
 .ll-grid label{display:grid;gap:3px;font-size:12px;font-weight:700;color:#435661;min-width:0}
 .ll-grid label.w2{grid-column:span 2}.ll-grid label.w4{grid-column:1/-1}
 .ll-grid .sw{display:flex;align-items:center;gap:7px;align-self:end;height:35px}.ll-grid .sw input{width:17px;height:17px;margin:0}
 .ll-grid .sw small{display:block;font-weight:600;color:#6b7f88;font-size:10.5px}
 .ll-sample{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;gap:8px;align-items:center;padding:9px 11px;border:1px solid #cfe4e8;background:#f3f9fa;border-radius:9px}
 .ll-sample b{font-size:12px;color:#17384e;white-space:nowrap}.ll-sample input{height:32px;font-size:12px}
 .ll-found{display:flex;gap:8px;align-items:center;font-size:12px;color:#087a57;font-weight:700;flex-wrap:wrap}
 .ll-found .ok{background:#e2f4ec;color:#087a57;border-radius:999px;padding:2px 10px;font-weight:800}
 .ll-sect{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:900;color:#305265;border-bottom:1px solid #dbe4e9;padding:4px 0 6px}
 .ll-sect .sp{flex:1}.ll-sect .w{font-size:11px;font-weight:700;color:#0b6570;background:#eaf6f9;border-radius:6px;padding:2px 8px}
 .ll-sect i.st{font-style:normal;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:#0b6577;color:#fff;font-size:11px}
 .ll-cols-head,.ll-col{display:grid;gap:5px;align-items:center;grid-template-columns:var(--ll-cols)}
 .ll-cols-head{padding:0 4px 2px;font-size:10.5px;font-weight:900;color:#7f939b}
 .ll-cols{display:grid;gap:4px;max-height:420px;overflow:auto}
 .ll-col input,.ll-col select{height:29px;font-size:11.5px;min-width:0}.ll-col select{padding:0 4px}
 .ll-col .ro{background:#f2f7f8;color:#5d7681;text-align:center;border-style:dashed}
 .ll-col .smp{font-family:Consolas,"Yu Gothic UI",monospace;font-size:11.5px;color:#2b4d59;background:#f7fafb;border:1px solid #e2eaee;border-radius:6px;height:29px;display:flex;align-items:center;padding:0 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .ll-col .fld{text-align:center;font-weight:800;color:#5c3f96;background:#f6f1fc;border-color:#d9cdee}
 .ll-col .x{height:29px;padding:0;background:#fff;border:1px solid #e0d0ce;color:#a4463d;border-radius:7px}
 .ll-col.typed select{background:#eaf6f9;border-color:#bcdfe6;color:#0b6570;font-weight:700}
 .ll-col .off{background:#f5f7f8;border-style:dashed;color:#a8b8be}
 .ll-acts{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ll-acts button{height:30px;padding:0 11px;font-size:12px}
 .ll-pv{overflow:auto;border:1px solid #e2eaee;border-radius:8px}.ll-pv table{border-collapse:collapse;font-size:11px;width:max-content;min-width:100%}
 .ll-pv th{background:#eef5f6;color:#31505d;font-size:10.5px;padding:4px 7px;text-align:left;white-space:nowrap}.ll-pv td{padding:3px 7px;border-top:1px solid #eef3f5;font-family:Consolas,"Yu Gothic UI",monospace;white-space:nowrap;color:#2b4d59}
 .ll-foot{display:flex;align-items:center;gap:8px;border-top:1px solid #e6eef0;padding-top:10px}.ll-foot .sp{flex:1}.ll-foot .hint{margin:0}
 .ll-crumb{display:flex;align-items:center;gap:8px;font-size:12px;color:#4f6873}.ll-crumb button{height:28px;padding:0 10px;font-size:12px}
 .ll-combo{position:relative;display:grid;gap:4px}
 .ll-combo .box{display:flex;align-items:center;gap:8px;height:38px;border:1px solid #0b6577;border-radius:8px;padding:0 10px;background:#fff;font-weight:800;color:#17384e;box-shadow:0 0 0 3px #ccebef}
 .ll-combo .box .sp{flex:1}.ll-combo .box small{color:#6b7f88;font-weight:600}
 .ll-drop{position:absolute;top:44px;left:0;right:0;z-index:20;background:#fff;border:1px solid #c8d6dc;border-radius:9px;box-shadow:0 14px 40px #15384d33;padding:6px;display:grid;gap:4px}
 .ll-drop input{height:32px}
 .ll-steps{display:flex;gap:6px}.ll-steps span{flex:1;padding:7px 10px;border-radius:8px;background:#f1f5f6;color:#6b7f88;font-weight:800;border:1px solid #e1e9ec;white-space:nowrap;font-size:12px}
 .ll-steps span.on{background:#e3f3f5;border-color:#9fd1d9;color:#0b4f5c}
 .ll-seg.c span.on.fx{background:#0b6577}.ll-seg.c span.on.dl{background:#5c3f96}
 .ll-save{display:flex;align-items:center;gap:8px}.ll-save .st{font-size:11.5px;color:#6b7f88;font-weight:700;white-space:nowrap}
 .ll-save .st.dirty{color:#8a5a0c}.ll-save button{height:32px;padding:0 18px}
 .ll-grid.g6{grid-template-columns:minmax(0,1.1fr) minmax(0,1.35fr) minmax(0,1.1fr) minmax(0,.75fr) minmax(0,1fr) minmax(0,1fr)}
 .ll-dlrow{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.ll-dlrow .sw{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:700;color:#435661}.ll-dlrow .sw input{width:17px;height:17px;margin:0}.ll-dlrow .sw small{display:block;font-weight:600;color:#6b7f88;font-size:10.5px}
 .ll-del{display:flex;justify-content:flex-end;padding-top:6px;border-top:1px dashed #e3ebee}
 .ll-del button{background:transparent;color:#a4463d;font-size:12px;padding:4px 8px;font-weight:700}
 .ll-fchips{display:flex;gap:4px;flex:none}.ll-fchips span{font-size:11px;font-weight:800;color:#4f6873;border:1px solid #d3e0e5;border-radius:999px;padding:2px 9px;white-space:nowrap}
 .ll-fchips span.on{background:#17384e;border-color:#17384e;color:#fff}
 .ll-grp.fx{color:#0b6577}.ll-grp.dl{color:#5c3f96}.ll-grp .tw{font-style:normal;font-size:10px;color:#8b9ca3}
 .ll-grp{border-bottom:1px solid #e3ebee;margin-bottom:2px}
 .ll-tbl tr.g td{background:#f6f9fa;font-size:11px;font-weight:900;height:24px}
 .ll-tbl tr.g.fx td{color:#0b6577}.ll-tbl tr.g.dl td{color:#5c3f96}
 .ll-switch{display:flex;align-items:center;gap:6px}.ll-switch button{height:28px;padding:0 9px;font-size:12px}
 .ll-list.snap{scroll-snap-type:y mandatory;scroll-padding-top:var(--ll-sp,0px)}.ll-list.snap .ll-row,.ll-list.snap tr,.ll-list.snap .ll-grp{scroll-snap-align:start}
 .ll-row.sf{border-left:4px solid #8ccbd4;border-radius:0 6px 6px 0}.ll-row.sd{border-left:4px solid #b9a3dd;border-radius:0 6px 6px 0}
 .ll-row.sf.on{border-left-color:#0b6577}.ll-row.sd.on{border-left-color:#5c3f96}
 .ll-row.lt{font-weight:500}.ll-row.lt.on{font-weight:800}
 .ll-auto{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:#087a57;white-space:nowrap}
 .ll-auto i{width:8px;height:8px;border-radius:50%;background:#16a37a;display:inline-block}
 .ll-auto small{color:#6b7f88;font-weight:600}
 .ll-grp.sk{position:sticky;top:0;box-shadow:0 -10px 0 #fff}
 `;
 let D = null;
 async function load() {
  if (D) return D;
  const d = await fetch('/api/text-layouts', { cache: 'no-store' }).then(r => r.json());
  const items = d.items;
  const fixed = items.find(x => x.name.startsWith('スラブマスター'));
  const delim = items.find(x => x.name.startsWith('受注明細CSV'));
  const sniff = await post('/api/text-sniff', { path: delim.sample_path, layout: delim });
  const pv = await post('/api/text-preview', { path: delim.sample_path, layout: delim, lines: 4 });
  D = { items, fixed, delim, sniff, pv, meta: d };
  return D;
 }
 function ensureStyle() { if (!document.getElementById('ll-style')) { const s = document.createElement('style'); s.id = 'll-style'; s.textContent = CSS; document.head.appendChild(s); } }
 const isD = x => x.mode === 'delimited';
 const tag = (x, wide) => wide ? `<i class="ll-tag w ${isD(x) ? 'dl' : 'fx'}">${isD(x) ? '区切り' : '固定長'}</i>` : `<i class="ll-tag ${isD(x) ? 'dl' : 'fx'}" title="${isD(x) ? '区切り' : '固定長'}">${isD(x) ? '区' : '固'}</i>`;
 const metaShort = x => isD(x) ? `${x.columns.length}列` : `${x.columns.length}列`;
 const shape = x => x.shape;
 const used = x => (x.used_by || []).length;

 /* ---- 一覧（案ごと） ---- */
 const LIST = {
  // 1行（記号・名前・列数）。用途メモは名前にかざすと出る
  one(cur) {
   return `<aside class="ll-pane"><h2>読取マスタ <small>${D.items.length}件</small></h2>
    <div class="ll-list">${D.items.map(x => `<button type="button" class="ll-row${x.id === cur.id ? ' on' : ''}" title="${E(x.description)}">${tag(x)}<span class="nm">${E(x.name)}</span><span class="mt">${metaShort(x)}</span></button>`).join('')}</div></aside>`;
  },
  // 2行（名前／読み方・形・文字コード）
  two(cur) {
   return `<aside class="ll-pane"><h2>読取マスタ <small>${D.items.length}件</small></h2>
    <div class="ll-list" style="gap:2px">${D.items.map(x => `<button type="button" class="ll-row2${x.id === cur.id ? ' on' : ''}" title="${E(x.description)}"><b>${E(x.name)}</b>${used(x) ? `<span class="ll-use">使用中</span>` : '<span></span>'}<small>${tag(x)}${E(shape(x))} · ${E(x.encoding)}</small></button>`).join('')}</div></aside>`;
  },
  // 表（名前・読み方・列・形）。幅を少し広げる
  table(cur) {
   return `<aside class="ll-pane" style="padding:8px"><h2 style="padding:2px 4px">読取マスタ <small>${D.items.length}件</small></h2>
    <div class="ll-list"><table class="ll-tbl"><colgroup><col><col style="width:62px"><col style="width:52px"></colgroup>
    <thead><tr><th>マスタ名</th><th>読み方</th><th style="text-align:right">列</th></tr></thead>
    <tbody>${D.items.map(x => `<tr class="${x.id === cur.id ? 'on' : ''}" title="${E(x.description)}"><td>${E(x.name)}</td><td>${tag(x, true)}</td><td class="n">${x.columns.length}</td></tr>`).join('')}</tbody></table></div></aside>`;
  },
  // 読み方ごとにまとめる（見出しに件数）
  group(cur) {
   const g = (k, label) => { const xs = D.items.filter(x => (x.mode || 'fixed') === k); return `<div class="ll-grp">${tag({ mode: k })}${label}<b>${xs.length}</b></div>` + xs.map(x => `<button type="button" class="ll-row${x.id === cur.id ? ' on' : ''}" style="grid-template-columns:minmax(0,1fr) auto" title="${E(x.description)}"><span class="nm">${E(x.name)}</span><span class="mt">${metaShort(x)}</span></button>`).join(''); };
   return `<aside class="ll-pane"><h2>読取マスタ <small>${D.items.length}件</small></h2><div class="ll-list">${g('fixed', '固定長')}${g('delimited', '区切り')}</div></aside>`;
  },
  // 1行。選んでいる1件だけ開いて用途メモと形を出す
  accord(cur) {
   return `<aside class="ll-pane"><h2>読取マスタ <small>${D.items.length}件</small></h2>
    <div class="ll-list">${D.items.map(x => x.id === cur.id
     ? `<button type="button" class="ll-row on" style="border-radius:7px 7px 0 0">${tag(x)}<span class="nm">${E(x.name)}</span><span class="mt">${metaShort(x)}</span></button><div class="ll-exp"><span>${E(shape(x))} · ${E(x.encoding)}${used(x) ? ` · <span class="ll-use">${used(x)}件の対象が使用中</span>` : ''}</span><span>${E(x.description)}</span></div>`
     : `<button type="button" class="ll-row" title="${E(x.description)}">${tag(x)}<span class="nm">${E(x.name)}</span><span class="mt">${metaShort(x)}</span></button>`).join('')}</div></aside>`;
  },
 // H: 表の一覧（名前・読み方・列）＋読み方の絞り込み（件数つき）。印は文字で「固定長／区切り」
  filt(cur) {
   const nF = D.items.filter(x => !isD(x)).length, nD = D.items.filter(isD).length;
   return `<aside class="ll-pane" style="padding:8px"><h2 style="padding:2px 4px">読取マスタ <small>${D.items.length}件</small><span style="flex:1"></span><span class="ll-fchips"><span class="on">すべて</span><span>固定長 ${nF}</span><span>区切り ${nD}</span></span></h2>
    <div class="ll-list"><table class="ll-tbl"><colgroup><col><col style="width:66px"><col style="width:46px"></colgroup>
    <thead><tr><th>マスタ名</th><th>読み方</th><th style="text-align:right">列</th></tr></thead>
    <tbody>${D.items.map(x => `<tr class="${x.id === cur.id ? 'on' : ''}" title="${E(x.description)}"><td>${E(x.name)}</td><td>${tag(x, true)}</td><td class="n">${x.columns.length}</td></tr>`).join('')}</tbody></table></div></aside>`;
  },
  // I: 読み方ごとの見出し（色つき・件数・たためる）。行は名前と列数だけ
  group2(cur) {
   const g = (k, label) => { const xs = D.items.filter(x => (x.mode || 'fixed') === k); return `<div class="ll-grp ${k === 'fixed' ? 'fx' : 'dl'}">▾ ${tag({ mode: k }, true)}<b>${xs.length}件</b><span style="flex:1"></span><i class="tw">${k === 'fixed' ? '位置で切る' : '記号・決まりで分ける'}</i></div>` + xs.map(x => `<button type="button" class="ll-row${x.id === cur.id ? ' on' : ''}" style="grid-template-columns:minmax(0,1fr) auto" title="${E(x.description)}"><span class="nm">${E(x.name)}</span><span class="mt">${x.columns.length}列</span></button>`).join(''); };
   return `<aside class="ll-pane"><h2>読取マスタ <small>${D.items.length}件</small></h2><div class="ll-list">${g('fixed')}${g('delimited')}</div></aside>`;
  },
  // K: 表の一覧の中を、読み方の行でまとめる（印の列を持たないので名前が広い）
  tgroup(cur) {
   const g = k => { const xs = D.items.filter(x => (x.mode || 'fixed') === k); return `<tr class="g ${k === 'fixed' ? 'fx' : 'dl'}"><td colspan="2">${k === 'fixed' ? '固定長' : '区切り'}　${xs.length}件</td></tr>` + xs.map(x => `<tr class="${x.id === cur.id ? 'on' : ''}" title="${E(x.description)}"><td>${E(x.name)}</td><td class="n">${x.columns.length}</td></tr>`).join(''); };
   return `<aside class="ll-pane" style="padding:8px"><h2 style="padding:2px 4px">読取マスタ <small>${D.items.length}件</small></h2>
    <div class="ll-list"><table class="ll-tbl"><colgroup><col><col style="width:52px"></colgroup>
    <thead><tr><th>マスタ名</th><th style="text-align:right">列</th></tr></thead><tbody>${g('fixed')}${g('delimited')}</tbody></table></div></aside>`;
  },
 // L〜O の一覧。o.groups = 読み方の見出しでまとめる、o.filter = 絞り込み、印は行の左の色の帯（文字の印の列を持たないので名前が切れない）
  stripe(cur, o) {
   const nF = D.items.filter(x => !isD(x)).length, nD = D.items.filter(isD).length;
   const row = x => `<button type="button" class="ll-row lt ${isD(x) ? 'sd' : 'sf'}${x.id === cur.id ? ' on' : ''}" style="grid-template-columns:minmax(0,1fr) auto" title="${E(x.description)}"><span class="nm">${E(x.name)}</span><span class="mt">${x.columns.length}列</span></button>`;
   const grp = (k) => { const xs = D.items.filter(x => (x.mode || 'fixed') === k); return `<div class="ll-grp sk ${k === 'fixed' ? 'fx' : 'dl'}">${tag({ mode: k }, true)}<b>${xs.length}件</b><span style="flex:1"></span><i class="tw">${k === 'fixed' ? '位置で切る' : '記号・決まりで分ける'}</i></div>` + xs.map(row).join(''); };
   const filt = o.filter ? `<span style="flex:1"></span><span class="ll-fchips"><span class="on">すべて</span><span>固定長 ${nF}</span><span>区切り ${nD}</span></span>` : '';
   return `<aside class="ll-pane"><h2>読取マスタ <small>${D.items.length}件</small>${filt}</h2><div class="ll-list snap" style="--ll-sp:${o.groups ? '27px' : '0px'}">${o.groups ? grp('fixed') + grp('delimited') : D.items.map(row).join('')}</div></aside>`;
  },
 };

 /* ---- 編集（案ごとに部品の出し方を変える） ---- */
 function modeCtl(o, x) {
  const on = isD(x);
  if (o.mode === 'select') return '';
  return `<span class="ll-seg${o.mode === 'segbig' ? ' big' : ''}${o.v2 ? ' c' : ''}"><span class="${on ? '' : 'on fx'}">固定長<small>位置で切る</small></span><span class="${on ? 'on dl' : ''}">区切り<small>記号・決まりで分ける</small></span></span>`;
 }
 function delimCtl(o, x) {
  const k = x.delimiter;
  if (o.delim === 'chips') return `<div class="ll-chips">${D.meta.delimiters.map(d => `<span class="${d.value === k ? 'on' : ''}">${E(d.value === 'regex' ? '正規表現' : d.value === 'custom' ? '文字を指定' : d.label)}</span>`).join('')}</div>`;
  return `<select>${D.meta.delimiters.map(d => `<option ${d.value === k ? 'selected' : ''}>${E(d.label)}</option>`).join('')}</select>`;
 }
 function opts(o, x) {
  const sel = (items, v) => `<select>${items.map(i => `<option ${i.value === v ? 'selected' : ''}>${E(i.label)}</option>`).join('')}</select>`;
  const modeSel = o.mode === 'select' ? `<label>読み方${sel(D.meta.modes, x.mode)}</label>` : '';
  const common = `<label>先頭を読み飛ばす行数<input value="${x.skip_head}"></label><label class="sw"><input type="checkbox" ${x.skip_blank ? 'checked' : ''}><span>空行を飛ばす<small>空白だけの行も</small></span></label><label class="sw"><input type="checkbox" ${x.header_row ? 'checked' : ''}><span>1行目は見出し<small>列名はこのマスタの名前</small></span></label>`;
  if (o.v2) {
   const cb = (on, t, sm) => `<label class="sw"><input type="checkbox" ${on ? 'checked' : ''}><span>${t}<small>${sm}</small></span></label>`;
   const tail = `<label>先頭を飛ばす行数<input value="${x.skip_head}"></label>${cb(x.header_row, '1行目は見出し', '列名はこのマスタの名前')}${cb(x.skip_blank, '空行を飛ばす', '空白だけの行も')}`;
   if (!isD(x)) return `<div class="ll-grid g6"><label>文字コード${sel(D.meta.encodings, x.encoding)}</label><label>位置の数え方${sel(D.meta.units, x.unit)}</label><label>前後の空白${sel(D.meta.trims, x.trim)}</label>${tail}</div>`;
   return `<div class="ll-grid g6"><label class="w4" style="grid-column:1/-1">区切り<span class="ll-dlrow">${delimCtl(o, x)}${cb(x.collapse, '続いた区切りは1つ', '空白で桁をそろえた表')}</span></label><label>文字コード${sel(D.meta.encodings, x.encoding)}</label><label>囲み文字${sel(D.meta.quotes, x.quote)}</label><label>前後の空白${sel(D.meta.trims, x.trim)}</label>${tail}</div>`;
  }
  if (!isD(x)) return `<div class="ll-grid">${modeSel}<label>文字コード${sel(D.meta.encodings, x.encoding)}</label><label>位置の数え方${sel(D.meta.units, x.unit)}</label><label>前後の空白${sel(D.meta.trims, x.trim)}</label><label>末尾を読み飛ばす行数<input value="${x.skip_tail}"></label>${common}</div>`;
  const dl = o.delim === 'chips' ? `<label class="w4">区切り${delimCtl(o, x)}</label>` : `<label>区切り${delimCtl(o, x)}</label>`;
  return `<div class="ll-grid">${modeSel}${dl}<label>文字コード${sel(D.meta.encodings, x.encoding)}</label><label>囲み文字${sel(D.meta.quotes, x.quote)}</label><label>前後の空白${sel(D.meta.trims, x.trim)}</label><label class="sw"><input type="checkbox" ${x.collapse ? 'checked' : ''}><span>続いた区切りは1つ<small>空白で桁をそろえた表など</small></span></label>${common}</div>`;
 }
 function sampleBar(o, x) {
  const p = x.sample_path || '.\\text\\SLAB.txt';
  const found = isD(x) && o.found ? `<div class="ll-found"><span class="ok">見本から見つけました</span>${E(D.sniff.label)}区切り · ${D.sniff.columns.length}列 · 見出しあり</div>` : '';
  if (o.v2) return `<div class="ll-sample"><b>見本のファイル</b><input value="${E(p.replace(/.*\/env\/data\//, '.\\').replace(/\//g, '\\'))}"><button type="button" class="secondary">参照…</button><button type="button">${isD(x) ? '見本から列を作る' : '下読み'}</button>${isD(x) && o.found ? `<div class="ll-found" style="grid-column:1/-1"><span class="ok">見本から見つけました</span>${E(D.sniff.label)}区切り · ${D.sniff.columns.length}列 · 1行目は見出し</div>` : ''}</div>`;
  return `<div class="ll-sample"><b>見本のファイル</b><input value="${E(p.replace(/.*\/env\/data\//, '.\\').replace(/\//g, '\\'))}"><button type="button" class="secondary">参照…</button><button type="button">${isD(x) ? '見本から列を作る' : '下読み'}</button></div>${found}`;
 }
 function cols(o, x) {
  const t = D.meta.types;
  const sel = c => `<select>${t.map(i => `<option ${i.value === c.type ? 'selected' : ''}>${E(i.label)}</option>`).join('')}</select>`;
  const fmt = c => c.type === 'real' ? `<input value="${c.scale}">` : (c.type === 'date' || c.type === 'datetime') ? `<input value="${E(c.format)}">` : `<input class="off" disabled>`;
  const smp = isD(x) ? (D.pv.rows[0] || []) : [];
  let head, rows, colsVar;
  if (isD(x)) {
   colsVar = 'minmax(110px,1.1fr) 56px minmax(110px,1fr) 116px 100px minmax(80px,.9fr) 30px';
   head = '<span>列名</span><span>項目</span><span>見本の値（1件目）</span><span>型</span><span>書式・小数桁</span><span>メモ</span><span></span>';
   rows = x.columns.map((c, i) => `<div class="ll-col${c.type !== 'text' ? ' typed' : ''}"><input value="${E(c.name)}"><input class="fld" value="${c.field}"><span class="smp">${E(smp[i] ?? '')}</span>${sel(c)}${fmt(c)}<input placeholder="メモ" value="${E(c.note)}"><button type="button" class="x">×</button></div>`).join('');
  } else {
   colsVar = 'minmax(110px,1.3fr) 58px 58px 58px 116px 100px minmax(80px,1fr) 30px';
   head = '<span>列名</span><span>開始</span><span>長さ</span><span>終了</span><span>型</span><span>書式・小数桁</span><span>メモ</span><span></span>';
   rows = x.columns.map(c => `<div class="ll-col${c.type !== 'text' ? ' typed' : ''}"><input value="${E(c.name)}"><input value="${c.start}"><input value="${c.length}"><input class="ro" value="${c.end}">${sel(c)}${fmt(c)}<input placeholder="メモ" value="${E(c.note)}"><button type="button" class="x">×</button></div>`).join('');
  }
  const w = isD(x) ? `${x.columns.length}列 / 項目${x.width}個まで使用` : `1行あたり ${x.width}バイト / ${x.columns.length}列`;
  const st = o.steps ? `<i class="st">2</i>` : '';
  return `<div class="ll-sect">${st}切り出す列<span class="sp"></span><span class="w">${w}</span></div>
   <div style="--ll-cols:${colsVar};display:grid;gap:4px"><div class="ll-cols-head ll-col" style="height:auto">${head}</div><div class="ll-cols">${rows}</div></div>
   <div class="ll-acts"><button type="button" class="secondary">列を追加</button><button type="button" class="secondary">全列をこの型にする</button><button type="button" class="secondary">列名 ⇔ メモ を入れ替える</button><span class="hint" style="margin:0">${isD(x) ? '項目は、区切りで分けた何番目か（1から）です。' : '開始位置は1文字目を1として数えます。'}</span></div>`;
 }
 function preview(o, x) {
  if (!isD(x)) return '';
  const h = D.pv.headers.slice(0, 11), r = D.pv.rows.slice(0, 3);
  return `<div class="ll-sect">${o.steps ? '<i class="st">3</i>' : ''}できあがり（見本の先頭3件）</div><div class="ll-pv"><table><tr>${h.map(v => `<th>${E(v)}</th>`).join('')}</tr>${r.map(row => `<tr>${row.slice(0, 11).map(v => `<td>${E(v)}</td>`).join('')}</tr>`).join('')}</table></div>`;
 }
 function editor(o, x) {
  if (o.v2) return editor2(o, x);
  const title = `<div class="ll-head"><h2>${E(x.name)}</h2>${modeCtl(o, x)}<span class="sp" style="flex:1"></span>${used(x) ? `<span class="ll-use">${used(x)}件の対象が使用中</span>` : ''}</div>`;
  const names = `<div class="ll-grid"><label class="w2">マスタ名<input value="${E(x.name)}"></label><label class="w2">用途メモ<input value="${E(x.description)}"></label></div>`;
  const sect1 = o.steps ? `<div class="ll-sect"><i class="st">1</i>読み方</div>` : '';
  const top = o.sample === 'top' ? sampleBar(o, x) : '';
  const bottom = o.sample === 'bottom' ? `<div class="ll-sect">下読み（切った結果を確かめる）</div>${sampleBar(o, x)}` : '';
  const crumb = o.crumb ? `<div class="ll-crumb"><button type="button" class="secondary">← 一覧へ戻る</button><span>読取マスタ / ${E(x.name)}</span></div>` : '';
  return `<article class="panel ll-edit">${crumb}${title}${names}${sect1}${opts(o, x)}${top}${cols(o, x)}${o.sample === 'top' ? preview(o, x) : ''}${bottom}${o.sample === 'bottom' ? preview(o, x) : ''}
   <div class="ll-foot"><span class="hint">保存すると、使っている対象の次の実行から効きます</span><span class="sp"></span><button type="button" class="danger">削除</button><button type="button" class="primary">保存</button></div></article>`;
 }
 function editor2(o, x) {
  const sw = o.switcher ? `<span class="ll-switch"><button type="button" class="secondary">← 一覧</button><button type="button" class="secondary" title="前のマスタ">‹</button><button type="button" class="secondary" title="次のマスタ">›</button></span>` : '';
  const save = o.auto ? `<span class="ll-auto"><i></i>自動で保存しました<small>10:24</small></span>` : `<span class="ll-save"><span class="st">変更はありません</span><button type="button" class="primary">保存</button></span>`;
  const head = `<div class="ll-head">${sw}<h2>${E(x.name)}</h2>${modeCtl(o, x)}<span style="flex:1"></span>${used(x) ? `<span class="ll-use">${used(x)}件の対象が使用中</span>` : ''}${save}</div>`;
  const names = `<div class="ll-grid"><label class="w2">マスタ名<input value="${E(x.name)}"></label><label class="w2">用途メモ<input value="${E(x.description)}"></label></div>`;
  const s1 = `<div class="ll-sect"><i class="st">1</i>読み方</div>`;
  const step = o.steps;
  return `<article class="panel ll-edit">${head}${names}${step ? s1 : ''}${opts(o, x)}${sampleBar(o, x)}${cols(o, x)}${preview(o, x)}<div class="ll-del"><button type="button">このマスタを削除…</button></div></article>`;
 }
 function paint(html, w) {
  const wrap = document.querySelector('#layouts .lay-wrap');
  wrap.style.display = 'none';
  document.getElementById('ll-root')?.remove();
  const root = document.createElement('div'); root.id = 'll-root'; root.className = 'll';
  root.innerHTML = html; wrap.after(root);
  if (w) root.style.setProperty('--ll-w', w);
  root.querySelectorAll('.ll-list').forEach(l => {
   const on = l.querySelector('.on'); if (!on) return;
   const want = Math.max(0, on.offsetTop - l.clientHeight / 2);
   if (!l.classList.contains('snap')) { l.scrollTop = want; return; }
   // 行の頭で止める（上に残る見出しの高さぶんを引く）。欠けた行を見出しの下に残さない
   const g = l.querySelector('.ll-grp'); const sp = g ? g.offsetHeight + 2 : 0;
   l.style.setProperty('--ll-sp', sp + 'px');
   const rows = [...l.querySelectorAll('.ll-row,.ll-grp')];
   const top = x => Math.max(0, x.offsetTop - (x.classList.contains('ll-grp') ? 0 : sp));
   const max = l.scrollHeight - l.clientHeight;
   const fit = rows.filter(x => top(x) <= max);
   const r = fit.find(x => x.offsetTop >= want) || fit[fit.length - 1];
   l.scrollTop = top(r);
  });
 }
 const two = (list, o, w) => v => { const x = v === 2 ? D.delim : D.fixed; paint(`<div class="ll-wrap">${LIST[list](x)}${editor(o, x)}</div>`, w); };
 const P = {
  // A: 1行の一覧（記号・名前・列数）＋ 編集の上に読み方の切り替え・区切りは札・見本を上に
  A: two('one', { mode: 'seg', delim: 'chips', sample: 'top', found: true }),
  // B: 2行の一覧（名前／形）＋ 切り替え・区切りは選ぶ欄・見本は下（いまと同じ場所）
  B: two('two', { mode: 'seg', delim: 'select', sample: 'bottom' }, '300px'),
  // C: 表の一覧（名前・読み方・列）＋ 読み方も区切りも選ぶ欄
  C: two('table', { mode: 'select', delim: 'select', sample: 'top', found: true }, '330px'),
  // D: 読み方ごとにまとめた一覧 ＋ 切り替え・札・見本は下
  D: two('group', { mode: 'seg', delim: 'chips', sample: 'bottom' }),
  // E: 1行、選んだ1件だけ開く ＋ 切り替え・札・見本を上
  E: two('accord', { mode: 'seg', delim: 'chips', sample: 'top', found: true }),
  // F（方向が違う）: 左の一覧をやめ、上の選ぶ欄（検索つき）で選ぶ。編集が全幅になる
  F(v) {
   const x = v === 2 ? D.delim : D.fixed;
   const drop = v === 1 ? `<div class="ll-drop"><input placeholder="マスタ名・説明・列名で絞り込む"><div class="ll-list" style="max-height:330px">${D.items.slice(0, 14).map(y => `<button type="button" class="ll-row${y.id === x.id ? ' on' : ''}">${tag(y)}<span class="nm">${E(y.name)}</span><span class="mt">${E(y.shape)}</span></button>`).join('')}</div></div>` : '';
   paint(`<div style="display:grid;gap:10px"><div class="ll-combo"><div class="box">${tag(x)}<span>${E(x.name)}</span><small>${E(x.shape)}</small><span class="sp"></span><small>${D.items.length}件から選ぶ ▾</small></div>${drop}</div>${editor({ mode: 'seg', delim: 'chips', sample: 'top', found: true }, x)}</div>`);
  },
  // H = G の表＋絞り込みを左の欄に（一覧と編集を同時に）＋ 編集は G の番号の手順・保存は見出しの右・削除は下に離す
  H: two('filt', { v2: true, mode: 'seg', delim: 'chips', found: true, steps: true }, '340px'),
  // I = D の読み方ごとの見出し（色・件数・たためる）＋ 切り替えの色を見出しと揃える ＋ 見本は上・保存は見出しの右
  I: two('group2', { v2: true, mode: 'seg', delim: 'chips', found: true, steps: true }, '320px'),
  // J = G の画面分け＋編集の見出しで「← 一覧・前・次」（戻らずに替えられる）。一覧の画面は G のまま
  J(v) {
   if (v === 1) return P.G(1);
   paint(editor2({ v2: true, mode: 'seg', delim: 'chips', found: true, steps: true, switcher: true }, D.delim));
  },
  // K = C の表 ＋ D のまとめを表の中の行で（印の列を持たず名前が広い）＋ H と同じ編集
  K: two('tgroup', { v2: true, mode: 'seg', delim: 'chips', found: true, steps: true }, '320px'),
  // L = H の編集 ＋ 一覧は色の帯と絞り込み（印の列をやめて名前を切らない）＋ 自動で保存（状態だけを出す）
  L: v => { const x = v === 2 ? D.delim : D.fixed; paint(`<div class="ll-wrap">${LIST.stripe(x, { filter: true })}${editor2({ v2: true, mode: 'seg', delim: 'chips', found: true, steps: true, auto: true }, x)}</div>`, '330px'); },
  // M = L ＋ I の読み方の見出し（意味つき・上に残る）
  M: v => { const x = v === 2 ? D.delim : D.fixed; paint(`<div class="ll-wrap">${LIST.stripe(x, { filter: true, groups: true })}${editor2({ v2: true, mode: 'seg', delim: 'chips', found: true, steps: true, auto: true }, x)}</div>`, '330px'); },
  // N = K の簡素な行 ＋ 読み方の見出し（上に残る）＋ 色の帯。絞り込みは無し ＋ 自動で保存
  N: v => { const x = v === 2 ? D.delim : D.fixed; paint(`<div class="ll-wrap">${LIST.stripe(x, { groups: true })}${editor2({ v2: true, mode: 'seg', delim: 'chips', found: true, steps: true, auto: true }, x)}</div>`, '310px'); },
  // O = M の一覧 ＋ 保存は残す（マスタは保存で残る）。下の帯の言葉をこの画面に合わせる
  O: v => { const x = v === 2 ? D.delim : D.fixed; paint(`<div class="ll-wrap">${LIST.stripe(x, { filter: true, groups: true })}${editor2({ v2: true, mode: 'seg', delim: 'chips', found: true, steps: true }, x)}</div>`, '330px');
   const f = [...document.querySelectorAll('footer *')].find(e => /自動で保存/.test(e.textContent) && !e.children.length); if (f) f.textContent = '読取マスタは、画面の［保存］で残ります'; },
  // G（方向が違う）: 手順を分ける。一覧は全幅の表（見渡す画面）、開くと編集だけの画面（① 読み方 ② 列 ③ できあがり）
  G(v) {
   if (v === 1) {
    paint(`<article class="panel ll-edit"><div class="ll-head"><h2>読取マスタ</h2><span class="ll-count">${D.items.length}件 <span class="ll-filter"><span class="on">すべて</span><span>固定長 ${D.items.filter(x => !isD(x)).length}</span><span>区切り ${D.items.filter(isD).length}</span></span></span></div>
     <div class="ll-list" style="max-height:calc(100vh - 330px)"><table class="ll-tbl"><colgroup><col style="width:28%"><col style="width:80px"><col style="width:150px"><col style="width:90px"><col></colgroup><thead><tr><th>マスタ名</th><th>読み方</th><th>形</th><th>文字コード</th><th>用途メモ</th></tr></thead>
     <tbody>${D.items.map(x => `<tr class="${x.id === D.fixed.id ? 'on' : ''}"><td>${E(x.name)}</td><td>${tag(x, true)}</td><td class="d">${E(x.shape)}</td><td class="d">${E(x.encoding)}</td><td class="d">${E(x.description)}</td></tr>`).join('')}</tbody></table></div></article>`);
   } else {
    paint(editor({ mode: 'segbig', delim: 'chips', sample: 'top', found: true, steps: true, crumb: true }, D.delim));
   }
  },
 };
 window.LL = {
  keys: Object.keys(P),
  async show(k, v) { ensureStyle(); await load(); P[k](v); return true; },
 };
})();
