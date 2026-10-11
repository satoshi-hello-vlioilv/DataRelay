// 2.2.0 データビュワーに「表示列の編集・条件・日付のまとめ」を入れる案（CLAUDE.md §3）。
// WaveLog の表示列の編集とフィルタを移すとき、このアプリのデータビュワーにどう置くかを比べる。
// 本物の画面の値の札の下（データ一覧・集計表の欄）に重ねた箱（body の直下）へ描く。表の中身は本物のデータ（viewerData）から作り、
// 計算列は static/viewer-model.js（DRV）で求める（撮り方: 先に viewer-model.js を読み込む）。
// window.VC.show(k, view)。view 1 = データ一覧（条件「工程 = 研削」、着手日時から「年月日」の列を足して表示列を編集しているところ）、
// view 2 = 集計表（着手日時を年月日でまとめ、工程ごとの件数）。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const H0 = () => (typeof viewerData !== 'undefined' && viewerData?.headers) || [];
 const R0 = () => (typeof viewerRows !== 'undefined' && viewerRows) || [];
 const VIEW = { cols: [{ key: '着手日時（年月日）' }, { key: 'ﾛｯﾄ番号' }, { key: '品名' }, { key: '工程' }, { key: '数量' }, { key: '作業者' }, { key: '着手日時', show: false }, { key: '完了日時', show: false }, { key: '仕掛区分', show: false }, { key: 'BOX実績_設備名', show: false }, { key: '不良数' }],
  calc: [{ name: '着手日時（年月日）', formula: 'date([着手日時])' }], filters: [{ column: '工程', op: 'eq', value: '研削' }] };
 const V1 = () => DRV.applyView({ headers: H0(), rows: R0() }, VIEW);
 // ---- 部品 ----
 const btn = (t, p) => `<button class="${p ? 'vc-btn' : 'vc-btn2'}">${t}</button>`;
 const chip = (t, x = true) => `<span class="vc-cond"><span>${t}</span>${x ? '<b>×</b>' : ''}</span>`;
 const tag = (t, c = '') => `<i class="vc-tag ${c}">${t}</i>`;
 function listTable(o = {}) {
  const v = V1(), cols = o.all ? v.order : v.shown, rows = (o.unfiltered ? v.rows : v.filtered).slice(0, o.n || 16);
  const th = cols.map(i => `<th class="${v.headers[i].includes('（') ? 'calc' : ''}">${E(v.labels[i])}${o.menu && i === o.menu ? ' <b class="vc-dd">▾</b>' : o.menu ? ' <i class="vc-dd2">▾</i>' : ''}</th>`).join('');
  return `<div class="vc-tbox"><table class="vc-t"><thead><tr><th class="no">No.</th>${th}</tr></thead><tbody>${rows.map((r, n) => `<tr><td class="no">${n + 1}</td>${cols.map(i => `<td class="${v.headers[i].includes('（') ? 'calc' : ''}">${E(r[i] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
 }
 const count = () => { const v = V1(); return `<span class="vc-count">${v.filtered.length.toLocaleString()} / ${v.rows.length.toLocaleString()}行</span>` };
 const search = () => `<input class="vc-search" placeholder="全列を対象に検索">`;
 function pivot(o = {}) {
  const v = V1(), di = v.headers.indexOf('着手日時（年月日）'), pi = v.headers.indexOf('工程'), rows = v.rows, rk = [...new Set(rows.map(r => r[di]))].filter(Boolean).sort(), ck = [...new Set(rows.map(r => r[pi]))].sort(), m = new Map();
  rows.forEach(r => { const k = r[di] + '\t' + r[pi]; m.set(k, (m.get(k) || 0) + 1) });
  const tot = a => ck.reduce((s, b) => s + (m.get(a + '\t' + b) || 0), 0);
  return `<div class="vc-tbox fit"><table class="vc-t pv"><thead><tr><th>${o.label || '着手日時（年月日）'}</th>${ck.map(b => `<th>${E(b)}</th>`).join('')}<th class="gt">総計</th></tr></thead><tbody>${rk.map(a => `<tr><th>${E(a)}</th>${ck.map(b => `<td>${m.get(a + '\t' + b) || ''}</td>`).join('')}<td class="gt">${tot(a)}</td></tr>`).join('')}<tr class="grand"><th>総計</th>${ck.map(b => `<td>${rk.reduce((s, a) => s + (m.get(a + '\t' + b) || 0), 0)}</td>`).join('')}<td class="gt">${rows.length}</td></tr></tbody></table><small class="vc-cap">行 ${rk.length} × 列 ${ck.length} ・ 件数 ・ ${rows.length} 行から</small></div>`;
 }
 const kinds = n => { const i = H0().indexOf(n); return i < 0 ? '' : new Set(R0().map(r => r[i])).size };
 const isDate = n => /日時/.test(n);
 // 集計表の左のカラム一覧（今の形）
 function fields(o = {}) {
  const names = o.withCalc ? [...H0(), '着手日時（年月日）'] : H0();
  return names.map(n => {
   const on = n === (o.rowsOn || '') ? 'rows' : n === '工程' ? 'columns' : '';
   return `<div class="vc-f ${on ? 'on' : ''} ${n.includes('（') ? 'calcf' : ''}"><span><b>${E(n)}</b><small>${n.includes('（') ? '計算列 · ' : ''}${kinds(n) || 9} 種類</small></span>${o.dateBtn && isDate(n) ? `<button class="vc-dbtn ${o.dateOpen === n ? 'open' : ''}">年・月・日 ▾</button>` : ''}<button class="vc-r r ${on === 'rows' ? 'on' : ''}">行</button><button class="vc-r c ${on === 'columns' ? 'on' : ''}">列</button></div>${o.dateOpen === n ? `<div class="vc-dmenu"><small>「${E(n)}」をまとめる</small>${DRV.DATE_PARTS.slice(0, 8).map(p => `<button class="${p[0] === 'date' ? 'on' : ''}">${p[1].replace(/（.*）/, '')}</button>`).join('')}</div>` : ''}`;
  }).join('');
 }
 const sentence = (rowChip, extra = '') => `<div class="vc-sent">${rowChip}<span>ごとに、</span><span class="vc-chip c">工程 <b>×</b></span><span>別の</span><select class="vc-sel"><option>件数</option></select><span>を出す</span>${extra}<span class="vc-sp"></span><label class="vc-ck"><input type="checkbox" checked>小計</label><label class="vc-ck"><input type="checkbox" checked>総計</label>${btn('出力…')}</div>`;
 const rowChip = (t = '着手日時（年月日）') => `<span class="vc-chip r">${t} <b>×</b></span>`;
 const pivotWork = (o = {}) => `<div class="vc-pv"><div class="vc-fields"><div class="vc-cap2"><b>カラム</b><small>札を押すと上の文に入ります</small></div><input class="vc-search w" placeholder="カラムを検索"><div class="vc-list">${fields(o)}</div></div><div class="vc-pw">${o.sentence || sentence(rowChip())}${pivot(o)}</div></div>`;
 // 表示列のパネル（WaveLog の2面: 左＝列のリスト・右＝選んだ列の設定）
 function colPanel(o = {}) {
  const v = V1();
  const list = v.order.map(i => { const h = v.headers[i], show = v.shown.includes(i), sel = h === '着手日時（年月日）';
   return `<div class="vc-ci ${sel ? 'sel' : ''} ${show ? '' : 'off'}"><i class="vc-grip">⋮⋮</i><input type="checkbox" ${show ? 'checked' : ''}><span class="vc-cn"><b>${E(v.labels[i])}</b>${h.includes('（') ? tag('計算列', 'calc') : ''}${isDate(h) ? tag('日付', 'date') : ''}</span><small>${E(v.rows[0][i] ?? '')}</small></div>` }).join('');
  const detail = `<div class="vc-cd"><div class="vc-cdh"><b>着手日時（年月日）</b>${tag('計算列', 'calc')}</div>
   <label class="vc-fl">表示名<input value="着手日時（年月日）"></label>
   <label class="vc-fl">作り方の式<input class="mono" value="date([着手日時])"></label><small class="vc-ok">✓ 式は正しく読めます · 見本: ${E(v.rows[0][v.headers.indexOf('着手日時（年月日）')])}</small>
   <div class="vc-fl"><span>日付から作る（着手日時）</span><div class="vc-parts">${DRV.DATE_PARTS.map(p => `<button class="${p[0] === 'date' ? 'on' : ''}">${p[1].replace(/（.*）/, '')}</button>`).join('')}</div></div>
   <div class="vc-row">${btn('この列を消す')}<span class="vc-sp"></span>${btn('閉じる', true)}</div></div>`;
  return `<div class="vc-panel ${o.cls || ''}"><div class="vc-ph"><b>表示列</b><small>設備単位実績 · 対象ごとに保存</small><span class="vc-sp"></span>${btn('＋ 計算列を足す')}${btn('すべて表示')}${btn('元に戻す')}</div><div class="vc-pb"><div class="vc-cl">${list}</div>${detail}</div></div>`;
 }
 const condEditor = () => `<div class="vc-pop vc-condpop"><b>条件を足す</b><div class="vc-row"><select><option>工程</option></select><select><option>＝ 一致</option></select><input value="研削"></div><div class="vc-sugg"><small>この列の値:</small><button class="on">研削 254</button><button>仕上 257</button><button>検査 258</button></div><div class="vc-row"><label class="vc-ck"><input type="radio" checked>すべて満たす</label><label class="vc-ck"><input type="radio">どれかを満たす</label><span class="vc-sp"></span>${btn('足す', true)}</div></div>`;
 const bar = (o = {}) => `<div class="vc-bar">${search()}<span class="vc-sep"></span><span class="vc-lbl">条件 ${o.n ?? 1}</span>${o.n === 0 ? '' : chip('工程 ＝ 研削')}<button class="vc-add">＋ 条件</button>${o.n === 0 ? '' : '<button class="vc-link">すべて外す</button>'}<span class="vc-sp"></span>${count()}<span class="vc-sep"></span><button class="vc-btn2 ic">▦ 表示列 ${tag('11列中7', 'n')}</button>${btn('前へ')}<span class="vc-pg">1 / 2</span>${btn('次へ')}</div>`;
 const V = {
  A: { t: 'WaveLog の形: 帯（検索｜条件｜表示列）＋表示列の2面パネル。集計は日付の列に「年・月・日」', html: v => v === 1
    ? `<div class="vc-col">${bar()}<div class="vc-stack">${listTable()}${colPanel({ cls: 'float' })}</div></div>`
    : `<div class="vc-col">${pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）', dateBtn: true, dateOpen: '着手日時' })}</div>` },
  B: { t: '右の引き出し（列｜条件）', html: v => `<div class="vc-col">${v === 1 ? `<div class="vc-bar">${search()}<span class="vc-sp"></span>${count()}<button class="vc-btn2 on">⚙ 列と条件</button></div>` : ''}<div class="vc-drw">${v === 1 ? listTable() : pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）' })}<aside class="vc-drawer"><div class="vc-tabs"><button class="on">列</button><button>条件 1</button><button>計算列 1</button></div>${v === 1 ? `<div class="vc-cl">${colPanel().match(/<div class="vc-cl">([\s\S]*?)<\/div><div class="vc-cd">/)[1]}</div>` : `<div class="vc-dsec"><b>日付のまとめ方</b><small>着手日時</small><div class="vc-parts">${DRV.DATE_PARTS.map(p => `<button class="${p[0] === 'date' ? 'on' : ''}">${p[1].replace(/（.*）/, '')}</button>`).join('')}</div><small>完了日時</small><div class="vc-parts">${DRV.DATE_PARTS.map(p => `<button>${p[1].replace(/（.*）/, '')}</button>`).join('')}</div></div>`}</aside></div></div>` },
  C: { t: '左の常設のカラム欄（一覧と集計で同じ欄）', html: v => `<div class="vc-col"><div class="vc-pv"><div class="vc-fields"><div class="vc-cap2"><b>カラム</b><small>${v === 1 ? '☑ 表示 ・ ⚲ 条件 ・ 日付は「年・月・日」' : '札を押すと上の文に入ります'}</small></div><input class="vc-search w" placeholder="カラムを検索"><div class="vc-list">${v === 1 ? [...H0(), '着手日時（年月日）'].map(n => `<div class="vc-f2 ${n === '工程' ? 'hasc' : ''}"><input type="checkbox" ${['着手日時', '完了日時', '仕掛区分', 'BOX実績_設備名'].includes(n) ? '' : 'checked'}><span><b>${E(n)}</b><small>${n === '工程' ? '＝ 研削' : (kinds(n) || 9) + ' 種類'}</small></span>${isDate(n) ? '<button class="vc-dbtn">年・月・日 ▾</button>' : ''}<button class="vc-ic ${n === '工程' ? 'on' : ''}">⚲</button></div>`).join('') : fields({ withCalc: true, rowsOn: '着手日時（年月日）', dateBtn: true })}</div></div><div class="vc-pw">${v === 1 ? `<div class="vc-bar">${search()}<span class="vc-lbl">条件 1</span>${chip('工程 ＝ 研削')}<span class="vc-sp"></span>${count()}</div>${listTable()}` : sentence(rowChip()) + pivot()}</div></div></div>` },
  D: { t: '列の見出しから（Excel のオートフィルタの形）', html: v => `<div class="vc-col">${v === 1 ? `<div class="vc-bar">${search()}<span class="vc-lbl">条件 1</span>${chip('工程 ＝ 研削')}<span class="vc-sp"></span>${count()}</div><div class="vc-stack">${listTable({ menu: 4 })}<div class="vc-pop vc-hmenu"><button>↑ 小さい順</button><button>↓ 大きい順</button><hr><b>値で絞る</b><label class="vc-ck"><input type="checkbox" checked>研削 254</label><label class="vc-ck"><input type="checkbox">仕上 257</label><label class="vc-ck"><input type="checkbox">検査 258</label><button>条件を書く…</button><hr><button>この列を隠す</button><button>名前を変える…</button><button>日付でまとめた列を足す ▸</button></div></div>` : pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）', sentence: sentence(`<span class="vc-chip r">着手日時（年月日） <b>▾</b></span>`) })}</div>` },
  E: { t: '集計の札の中でまとめ方を選ぶ（一覧は A の帯）', html: v => v === 1
    ? `<div class="vc-col">${bar()}<div class="vc-stack">${listTable()}${colPanel({ cls: 'float' })}</div></div>`
    : `<div class="vc-col">${pivotWork({ rowsOn: '着手日時', sentence: sentence(`<span class="vc-chip r">着手日時 <select class="vc-in"><option>年月日</option></select> <b>×</b></span>`), label: '着手日時（年月日）' })}</div>` },
  F: { t: 'おすすめから（日付の列を見つけて、まとめた列と条件を候補で出す・方向の違う案）', html: v => `<div class="vc-col">${v === 1 ? bar() : ''}<div class="vc-reco"><b>この表の日付</b><span>着手日時・完了日時（時刻つき）</span><span class="vc-sep"></span><small>まとめた列を足す:</small><button class="on">着手日時の年月日 ✓</button><button>着手日時の年月</button><button>着手日時の曜日</button><button>完了日時の年月日</button><span class="vc-sp"></span><small>よく使う条件:</small><button>工程 ＝ 研削 ✓</button><button>作業者 ＝ 佐藤</button></div>${v === 1 ? listTable() : pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）' })}</div>` },
  G: { t: '式のバー（列を足すのも条件も式で書く・方向の違う案）', html: v => `<div class="vc-col"><div class="vc-fx"><b>列を足す</b><input class="name" value="着手日時（年月日）"><span>=</span><input class="mono" value="date([着手日時])"><span class="vc-ok">✓</span>${btn('足す', true)}<span class="vc-sep"></span><b>条件</b><input class="mono" value="[工程] = '研削'"><span class="vc-ok">✓ 254行</span><div class="vc-sg"><b>date</b>(x) 日付（2026-10-01）<br><b>ym</b>(x) 年月<br><b>year</b>(x) 年<br><b>weekday</b>(x) 曜日</div></div>${v === 1 ? listTable() : pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）' })}</div>` },
  // ---- 2回目: 組合せ案（どれも A の帯と表示列のパネルが土台） ----
  H: { t: 'A＋E（カラムの「年・月・日」で計算列を作り、行の札でもまとめ方を切り替えられる）', html: v => v === 1
    ? `<div class="vc-col">${bar()}<div class="vc-stack">${listTable()}${colPanel({ cls: 'float' })}</div></div>`
    : `<div class="vc-col">${pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）', dateBtn: true, sentence: sentence(`<span class="vc-chip r">着手日時 <select class="vc-in"><option>年月日</option></select> <b>×</b></span>`) })}</div>` },
  I: { t: 'A＋F（表示列のパネルと集計の空の画面に、日付のまとめのおすすめを出す）', html: v => v === 1
    ? `<div class="vc-col">${bar()}<div class="vc-reco"><b>日付の列</b><span>着手日時・完了日時</span><small>まとめた列を足す:</small><button class="on">着手日時の年月日 ✓</button><button>着手日時の年月</button><button>完了日時の年月日</button></div><div class="vc-stack">${listTable()}${colPanel({ cls: 'float' })}</div></div>`
    : `<div class="vc-col">${pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）', dateBtn: true })}</div>` },
  J: { t: 'A＋C（集計のカラム一覧にも条件の印。条件は一覧・集計・グラフで共通）', html: v => v === 1
    ? `<div class="vc-col">${bar()}<div class="vc-stack">${listTable()}${condEditor().replace('vc-condpop', 'vc-condpop at')}</div></div>`
    : `<div class="vc-col">${bar({ n: 1 }).replace(/<button class="vc-btn2">前へ.*$/, '</div>')}${pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）', dateBtn: true })}</div>` },
  K: { t: 'A＋E＋F＋J（帯の条件は全タブ共通・値の候補で選ぶ／カラムの「年・月・日」／行の札で切り替え／空の画面におすすめ）', html: v => v === 1
    ? `<div class="vc-col">${bar()}<div class="vc-stack">${listTable()}${colPanel({ cls: 'float' })}${condEditor().replace('vc-condpop', 'vc-condpop at2')}</div></div>`
    : `<div class="vc-col">${bar({ n: 1 }).replace(/<button class="vc-btn2 ic">.*$/, '</div>')}${pivotWork({ withCalc: true, rowsOn: '着手日時（年月日）', dateBtn: true, dateOpen: '着手日時', sentence: sentence(`<span class="vc-chip r">着手日時 <select class="vc-in"><option>年月日</option></select> <b>×</b></span>`) })}</div>` },
 };
 const CSS = `
  #vc-overlay{position:fixed;z-index:50;background:#f3f6f8;font-family:"Yu Gothic UI",Meiryo,sans-serif;font-size:12.5px;color:#17232d;overflow:hidden}
  #vc-overlay *{box-sizing:border-box}#vc-overlay button{font:inherit;cursor:pointer;color:#17384e}#vc-overlay input,#vc-overlay select{font:inherit;width:auto;height:30px;border:1px solid #cdd9de;border-radius:7px;padding:0 8px;background:#fff}
  #vc-overlay input[type=checkbox],#vc-overlay input[type=radio]{width:14px;height:14px;padding:0;margin:0}#vc-overlay label{display:inline-flex;align-items:center;gap:6px;margin:0;font-size:12px;font-weight:600;color:#33505c}
  .vc-col{height:100%;display:flex;flex-direction:column;gap:8px;min-height:0}
  .vc-bar{flex:none;display:flex;align-items:center;gap:8px;padding:7px 10px;background:#fff;border:1px solid #d7e0e5;border-radius:10px}
  .vc-search{width:260px!important}.vc-search.w{width:100%!important}.vc-sep{width:1px;height:20px;background:#d7e0e5}.vc-sp{flex:1}
  .vc-lbl{font-weight:800;color:#33505c}.vc-cond{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 6px 0 10px;border:1px solid #9fcbd6;border-radius:14px;background:#e8f4f6;font-weight:700;color:#0b6f7f}.vc-cond b{color:#9a5550}
  .vc-add{height:28px;padding:0 10px;border:1px dashed #9fbac4;border-radius:14px;background:#f7fafb;font-weight:800}.vc-link{border:0;background:none;color:#087c98!important;font-weight:700}
  .vc-count{color:#647581;font-size:11.5px}.vc-pg{color:#647581}
  .vc-btn{height:30px;padding:0 14px;border:0;border-radius:7px;background:#087c98;color:#fff!important;font-weight:800}.vc-btn2{height:30px;padding:0 12px;border:1px solid #c9d8de;border-radius:7px;background:#fff;font-weight:700;white-space:nowrap}.vc-btn2.on{background:#e8f4f6;border-color:#9fcbd6}
  .vc-tag{font-style:normal;font-size:10px;font-weight:800;padding:1px 6px;border-radius:5px;background:#eef2f4;color:#647581}.vc-tag.calc{background:#f1eafb;color:#6a3fa0}.vc-tag.date{background:#e6f1fb;color:#1d5f9a}.vc-tag.n{background:#e8f4f6;color:#0b6f7f}
  .vc-stack{position:relative;flex:1;min-height:0;display:flex;flex-direction:column}
  .vc-tbox{flex:1;min-height:0;overflow:auto;background:#fff;border:1px solid #d7e0e5;border-radius:10px}.vc-tbox.fit{flex:0 1 auto;align-self:flex-start;max-width:100%}
  .vc-t{border-collapse:collapse;font-variant-numeric:tabular-nums;width:100%}.vc-t th,.vc-t td{padding:6px 10px;border-bottom:1px solid #eef3f5;white-space:nowrap;text-align:left}.vc-t thead th{position:sticky;top:0;background:#eef3f5;color:#33505c;font-size:12px}
  .vc-t th.calc{background:#f1eafb;color:#6a3fa0}.vc-t td.calc{background:#faf7fe;color:#4b2d78;font-weight:700}.vc-t .no{color:#8a9aa1;text-align:right;width:44px}
  .vc-dd{color:#087c98}.vc-dd2{font-style:normal;color:#9aabb2;font-size:10px}
  .vc-t.pv{width:auto}.vc-t.pv td{text-align:right;min-width:84px}.vc-t.pv tbody th{background:#f7fafb}.vc-t .gt{background:#f0f5f7;font-weight:800}.vc-t .grand th,.vc-t .grand td{background:#e9f0f3;font-weight:900}.vc-cap{display:block;padding:6px 10px;color:#647581;font-size:11px}
  .vc-pv{flex:1;min-height:0;display:grid;grid-template-columns:300px minmax(0,1fr);gap:8px}.vc-fields{min-height:0;display:flex;flex-direction:column;gap:6px;padding:10px;background:#fff;border:1px solid #d7e0e5;border-radius:10px}
  .vc-cap2{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.vc-cap2 b{font-size:13.5px}.vc-cap2 small{color:#647581;font-size:10.5px}
  .vc-list{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:4px}.vc-list>*{flex:none}
  .vc-f,.vc-f2{display:grid;grid-template-columns:minmax(0,1fr) auto 34px 34px;align-items:center;gap:4px;min-height:40px;padding:3px 5px 3px 10px;border:1px solid #d7e2e6;border-radius:8px}.vc-f.on{background:#f5f9fa}.vc-f.calcf{border-color:#cdb6ea;background:#faf7fe}
  .vc-f2{grid-template-columns:16px minmax(0,1fr) auto 30px}.vc-f2.hasc{border-color:#9fcbd6;background:#f2f9fa}
  .vc-f span,.vc-f2 span{display:grid;line-height:1.3;min-width:0}.vc-f b,.vc-f2 b{font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vc-f small,.vc-f2 small{font-size:10px;color:#6c8189}
  .vc-r{height:28px;padding:0;border:1px solid;border-radius:6px;font-weight:900;font-size:11.5px;opacity:.6}.vc-r.on{opacity:1;box-shadow:inset 0 0 0 2px currentColor}.vc-r.r{background:#e2f1f4;color:#0b6d86;border-color:#a8d2dc}.vc-r.c{background:#e6ecfa;color:#3a4d9c;border-color:#bccaee}
  .vc-dbtn{height:26px;padding:0 8px;border:1px solid #a9c9e8;border-radius:6px;background:#e6f1fb;color:#1d5f9a!important;font-size:11px;font-weight:800;white-space:nowrap}.vc-dbtn.open{box-shadow:inset 0 0 0 2px #1d5f9a}
  .vc-ic{height:26px;border:1px solid #d7e0e5;border-radius:6px;background:#fff;color:#647581!important}.vc-ic.on{background:#e8f4f6;color:#0b6f7f!important;border-color:#9fcbd6}
  .vc-dmenu{display:flex;flex-wrap:wrap;gap:4px;padding:8px;margin:-2px 0 2px 18px;border:1px solid #a9c9e8;border-radius:8px;background:#fff;box-shadow:0 10px 24px #17384e2a}.vc-dmenu small{width:100%;color:#4d6670;font-size:10.5px}.vc-dmenu button{height:26px;padding:0 8px;border:1px solid #d7e0e5;border-radius:6px;background:#fff;font-size:11.5px}.vc-dmenu button.on{background:#e6f1fb;border-color:#1d5f9a;color:#1d5f9a!important;font-weight:800}
  .vc-pw{min-width:0;min-height:0;display:flex;flex-direction:column;gap:8px}
  .vc-sent{flex:none;display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;padding:8px 12px;background:#fff;border:1px solid #d7e0e5;border-radius:10px;font-size:14px;font-weight:700}
  .vc-chip{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 8px 0 10px;border:1px solid;border-radius:7px;font-weight:800;font-size:13px}.vc-chip.r{background:#e2f1f4;color:#0b6d86;border-color:#a8d2dc}.vc-chip.c{background:#e6ecfa;color:#3a4d9c;border-color:#bccaee}.vc-chip b{color:#9a5550}
  .vc-in{height:24px!important;padding:0 4px!important;font-size:12px!important;border-color:#a8d2dc!important}
  .vc-sel{font-weight:800;color:#0b6b4c;background:#e4f3ea!important;border-color:#a9d6bf!important}.vc-ck{font-size:12px}
  .vc-panel{display:flex;flex-direction:column;background:#fff;border:1px solid #9fcbd6;border-radius:12px;box-shadow:0 18px 44px #17384e40;overflow:hidden}.vc-panel.float{position:absolute;right:16px;top:8px;bottom:8px;width:880px}
  .vc-ph{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid #e6edf0}.vc-ph b{font-size:15px}.vc-ph small{color:#647581}
  .vc-pb{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 380px}
  .vc-cl{min-height:0;overflow:auto;padding:8px;display:flex;flex-direction:column;gap:3px;border-right:1px solid #eef3f5}
  .vc-ci{display:grid;grid-template-columns:14px 16px minmax(0,1fr) minmax(0,120px);align-items:center;gap:8px;padding:6px 8px;border:1px solid #eef3f5;border-radius:7px}.vc-ci.sel{background:#e8f4f6;border-color:#9fcbd6}.vc-ci.off{opacity:.55}
  .vc-grip{font-style:normal;color:#9aabb2;letter-spacing:-2px}.vc-cn{display:flex;align-items:center;gap:6px;min-width:0}.vc-cn b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vc-ci small{color:#647581;font-family:Consolas,monospace;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .vc-cd{display:flex;flex-direction:column;gap:10px;padding:12px 14px;min-height:0;overflow:auto}.vc-cdh{display:flex;align-items:center;gap:8px}.vc-cdh b{font-size:14px}
  .vc-fl{display:grid!important;gap:4px!important;font-size:11.5px!important;color:#647581!important}.vc-fl input{width:100%!important;color:#17232d}.mono{font-family:Consolas,monospace!important}
  .vc-ok{color:#0a6a4a;font-size:11.5px;font-weight:700}.vc-parts{display:flex;flex-wrap:wrap;gap:4px}.vc-parts button{height:28px;padding:0 9px;border:1px solid #d7e0e5;border-radius:6px;background:#fff;font-size:12px}.vc-parts button.on{background:#e6f1fb;border-color:#1d5f9a;color:#1d5f9a!important;font-weight:800}
  .vc-row{display:flex;align-items:center;gap:8px}
  .vc-drw{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:8px}.vc-drawer{min-height:0;display:flex;flex-direction:column;gap:6px;padding:8px;background:#fff;border:1px solid #9fcbd6;border-radius:10px}
  .vc-tabs{display:flex;gap:4px}.vc-tabs button{flex:1;height:30px;border:1px solid #d7e0e5;border-radius:7px;background:#fff;font-weight:700}.vc-tabs button.on{background:#e8f4f6;border-color:#9fcbd6}
  .vc-drawer .vc-cl{border:0;padding:0}.vc-drawer .vc-ci{grid-template-columns:14px 16px minmax(0,1fr) 80px}.vc-dsec{display:flex;flex-direction:column;gap:6px;padding:6px}.vc-dsec small{color:#647581}
  .vc-pop{position:absolute;z-index:3;display:flex;flex-direction:column;gap:6px;padding:10px 12px;background:#fff;border:1px solid #9fcbd6;border-radius:10px;box-shadow:0 14px 34px #17384e40}
  .vc-hmenu{left:520px;top:34px;width:240px}.vc-hmenu>button{text-align:left;height:28px;border:0;background:none;padding:0 6px;border-radius:5px;font-weight:700}.vc-hmenu>button:hover{background:#eef5f7}.vc-hmenu hr{width:100%;border:0;border-top:1px solid #e6edf0;margin:2px 0}
  .vc-reco{flex:none;display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;padding:8px 12px;background:#f2f8fd;border:1px solid #c6dcef;border-radius:10px}.vc-reco>b{color:#1d5f9a}.vc-reco>span{color:#4d6670}.vc-reco small{color:#647581}.vc-reco button{height:28px;padding:0 10px;border:1px solid #c6dcef;border-radius:14px;background:#fff;font-size:12px}.vc-reco button.on{background:#e6f1fb;border-color:#1d5f9a;color:#1d5f9a!important;font-weight:800}
  .vc-fx{position:relative;flex:none;display:flex;align-items:center;gap:8px;padding:8px 12px;background:#fff;border:1px solid #d7e0e5;border-radius:10px}.vc-fx input.name{width:180px!important}.vc-fx input.mono{width:240px!important}
  .vc-condpop.at{left:420px;top:4px;width:440px}.vc-condpop.at2{left:420px;top:-4px;width:430px}.vc-condpop .vc-row input{width:140px!important}.vc-sugg{display:flex;flex-wrap:wrap;gap:4px;align-items:center}.vc-sugg small{color:#647581}.vc-sugg button{height:26px;padding:0 8px;border:1px solid #d7e0e5;border-radius:13px;background:#fff;font-size:11.5px}.vc-sugg button.on{background:#e8f4f6;border-color:#087c98;color:#0b6f7f!important;font-weight:800}
  .vc-sg{position:absolute;left:330px;top:44px;z-index:3;padding:8px 12px;background:#fff;border:1px solid #9fcbd6;border-radius:8px;box-shadow:0 12px 28px #17384e33;font-size:12px;line-height:1.8;color:#4d6670}.vc-sg b{color:#087c98;font-family:Consolas,monospace}
 `;
 function style() { let s = document.getElementById('vc-style'); if (!s) { s = document.createElement('style'); s.id = 'vc-style'; document.head.appendChild(s) } s.textContent = CSS }
 window.VC = {
  V,
  show(k, v = 1) {
   style(); const vals = document.querySelector('#viewer-values'), top = (vals && !vals.hidden ? vals : document.querySelector('.viewer-topbar')).getBoundingClientRect().bottom + 8;
   const sh = document.querySelector('.viewer-shell').getBoundingClientRect(), foot = document.querySelector('footer').getBoundingClientRect().top - 2;
   let host = document.getElementById('vc-overlay'); if (!host) { host = document.createElement('div'); host.id = 'vc-overlay'; document.body.appendChild(host) }
   Object.assign(host.style, { left: sh.left + 'px', top: top + 'px', width: sh.width + 'px', height: (foot - top) + 'px' }); host.innerHTML = V[k].html(v);
  },
 };
})();
