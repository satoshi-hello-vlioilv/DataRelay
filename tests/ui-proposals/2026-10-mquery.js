// 2.4.0 Power Query（クエリの編集）の案（CLAUDE.md §3）。
// いま: クエリの画面は無い。共通設定のサブナビ（基本設定・読取マスタ・ファイル結合）は「左に一覧・右に編集」。結合の画面は
// 組み立てと「できあがりを見る」が上下に離れ、結果を見るには下まで送る。
// 本物の画面の「Power Query」の右の欄（#mq-edit）に、案ごとの中身を差し込む。中身は撮影用の環境の本物のクエリ
// （Excel の「フォルダーから結合」の5本を貼り付けた物）と、本物の下読み（/api/m-query/preview）の結果。
// 撮り方: window.PQ.show(k, view)。view 1 = 開いた直後（最後のステップ）、view 2 = 式が止まったとき（シート名の誤り）。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const CSS = `
 .pq{display:grid;gap:10px;font-size:12.5px;color:#22414c}
 .pq .q-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
 .pq .q-grow{flex:1;min-width:0}
 .pq input.q-t{height:34px;border:1px solid #c8d6dc;border-radius:8px;padding:0 10px;font:inherit;min-width:0;width:100%;box-sizing:border-box}
 .pq label.q-f{display:grid;gap:4px;font-weight:800;font-size:12px;color:#17384e}
 .pq .q-head{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;gap:10px;align-items:end}
 .pq .q-btn{height:34px;border-radius:8px;border:1px solid #c8d6dc;background:#fff;color:#17384e;font-weight:800;padding:0 14px;font:inherit;font-weight:800;cursor:pointer;white-space:nowrap}
 .pq .q-btn.q-pri{background:#0b6577;border-color:#0b6577;color:#fff}
 .pq .q-btn.q-sm{height:28px;padding:0 10px;font-size:12px}
 .pq .q-code{color:#22414c;font-family:Consolas,"BIZ UDGothic","MS Gothic",monospace;font-size:12px;line-height:1.55;background:#fbfcfd;border:1px solid #c8d6dc;border-radius:9px;margin:0;overflow:auto;counter-reset:ln;white-space:pre;padding:6px 0}
 .pq .q-code span{display:block;padding:0 10px 0 46px;position:relative}
 .pq .q-code span::before{counter-increment:ln;content:counter(ln);position:absolute;left:0;width:34px;text-align:right;color:#9aabb2}
 .pq .q-code span.q-cur{background:#e6f4f6}.pq .q-code span.q-bad{background:#fff0ee}
 .pq .q-code .q-kw{color:#7a3e9d;font-weight:700}.pq .q-code .q-str{color:#a45a00}.pq .q-code .q-fn{color:#0b6577}
 .pq .q-steps{display:grid;gap:2px;align-content:start;counter-reset:st}
 .pq .q-step{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:6px;align-items:center;padding:5px 8px;border-radius:7px;color:#2f4a55;cursor:pointer;border:1px solid transparent}
 .pq .q-step::before{counter-increment:st;content:counter(st);font-size:10.5px;color:#7b8f97;text-align:right}
 .pq .q-step b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .pq .q-step.q-on{background:#e6f4f6;border-color:#9fd1d9;color:#0b4f5c}.pq .q-step.q-on b{font-weight:800}
 .pq .q-step.q-err{background:#fff0ee;border-color:#f1b8ae;color:#a12d1a}
 .pq .q-step.q-after{opacity:.45}
 .pq .q-step i{font-style:normal;font-size:11px}
 .pq .q-chips{display:flex;gap:4px;flex-wrap:wrap}
 .pq .q-chip{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:999px;border:1px solid #d3e0e5;background:#fff;font-size:11.5px;color:#2f4a55;white-space:nowrap}
 .pq .q-chip.q-on{background:#0b6577;border-color:#0b6577;color:#fff;font-weight:800}
 .pq .q-chip.q-err{background:#fff0ee;border-color:#f1b8ae;color:#a12d1a;font-weight:800}
 .pq .q-chip.q-main::after{content:'出す';font-size:10px;background:#e2f4ec;color:#087a57;border-radius:4px;padding:0 4px;margin-left:2px}
 .pq .q-chip.q-on.q-main::after{background:#fff;color:#0b6577}
 .pq .q-stat{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
 .pq .q-pill{display:inline-flex;gap:4px;align-items:center;padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:800;background:#eef3f5;color:#35505b}
 .pq .q-pill.q-ok{background:#e2f4ec;color:#087a57}.pq .q-pill.q-warn{background:#fff4dc;color:#8a5a0c}.pq .q-pill.q-ng{background:#fff0ee;color:#a12d1a}
 .pq .q-tbl{overflow:auto;border:1px solid #dce6ea;border-radius:9px;background:#fff}
 .pq table{border-collapse:collapse;font-size:12px;width:max-content;min-width:100%}
 .pq th{position:sticky;top:0;background:#f0f5f6;color:#35505b;text-align:left;font-size:11.5px;padding:5px 9px;border-bottom:1px solid #dce6ea;white-space:nowrap}
 .pq th small{display:block;font-weight:600;color:#7b8f97;font-size:10.5px}
 .pq td{padding:4px 9px;border-top:1px solid #f0f4f5;white-space:nowrap;max-width:220px;overflow:hidden;text-overflow:ellipsis}
 .pq td.q-n{text-align:right;font-variant-numeric:tabular-nums}
 .pq td.q-nul{color:#a7b5bb;font-style:italic}
 .pq td.q-e{background:#fff0ee;color:#a12d1a;font-weight:800}
 .pq td.q-nest{color:#0b6577;font-weight:700}
 .pq .q-err{border:1px solid #f1b8ae;background:#fff6f4;border-radius:9px;padding:10px 12px;display:grid;gap:4px}
 .pq .q-err b{color:#a12d1a;font-size:13px}.pq .q-err p{margin:0;color:#5b2a20}
 .pq .q-err small{color:#7a4a40}
 .pq .q-card{border:1px solid #dce6ea;border-radius:10px;background:#fff;padding:10px 12px;display:grid;gap:8px;min-width:0}
 .pq .q-cap{display:flex;align-items:center;gap:8px;font-weight:800;color:#17384e;font-size:12.5px}
 .pq .q-cap small{font-weight:600;color:#6b7f88}
 .pq .q-tabs{display:flex;gap:2px;border-bottom:1px solid #dce6ea}
 .pq .q-tab{padding:7px 14px;border-radius:8px 8px 0 0;font-weight:800;color:#5a727c;border:1px solid transparent;border-bottom:0}
 .pq .q-tab.q-on{background:#fff;border-color:#dce6ea;color:#0b6577;margin-bottom:-1px}
 .pq .q-wiz{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
 .pq .q-wz{display:flex;gap:8px;align-items:center;padding:8px 12px;border-radius:9px;border:1px solid #dce6ea;background:#f6f9fa;color:#5a727c;font-weight:800}
 .pq .q-wz i{font-style:normal;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:#dfe8eb;color:#35505b;font-size:12px}
 .pq .q-wz.q-on{background:#e6f4f6;border-color:#9fd1d9;color:#0b4f5c}.pq .q-wz.q-on i{background:#0b6577;color:#fff}
 .pq .q-wz.q-done i{background:#087a57;color:#fff}
 .pq .q-seg{display:inline-flex;border:1px solid #c8d6dc;border-radius:8px;overflow:hidden}
 .pq .q-seg span{padding:6px 12px;font-weight:800;color:#5a727c;background:#fff}.pq .q-seg span.q-on{background:#0b6577;color:#fff}
 .pq .q-note{color:#6b7f88;font-size:11.5px}
 .pq details{border:1px solid #dce6ea;border-radius:9px;background:#fbfdfd;padding:7px 12px}.pq summary{cursor:pointer;font-weight:800;color:#17384e}
 .pq .q-foot{display:flex;gap:8px;align-items:center;justify-content:flex-end;border-top:1px solid #edf1f2;padding-top:10px}
 .pq .q-rail{display:grid;gap:8px;align-content:start}
 .pq .q-grid2{display:grid;gap:10px}
 .pq .q-form4{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr) minmax(0,1fr);gap:10px;align-items:end}
 `;
 let st = null;
 function style() { if (!document.getElementById('pq-style')) { const s = document.createElement('style'); s.id = 'pq-style'; s.textContent = CSS; document.head.appendChild(s) } }
 const KW = /\b(let|in|each|if|then|else|and|or|not|type|null|true|false|meta|try|otherwise)\b/g;
 function hl(line) { return E(line).replace(/(&quot;.*?&quot;)/g, '<em class="q-str">$1</em>').replace(KW, '<em class="q-kw">$1</em>').replace(/\b([A-Z][A-Za-z]+\.[A-Z][A-Za-z]+)\b/g, '<em class="q-fn">$1</em>') }
 function code(text, rows, curLine, badLine) {
  const lines = String(text).split('\n');
  return `<pre class="q-code" style="max-height:${rows * 18.6 + 12}px">${lines.map((l, i) => `<span class="${i + 1 === curLine ? 'q-cur' : ''}${i + 1 === badLine ? ' q-bad' : ''}">${hl(l) || ' '}</span>`).join('').replace(/<em /g, '<i style="font-style:normal" ').replace(/<\/em>/g, '</i>')}</pre>`
 }
 function stepLine(name) { const lines = st.code.split('\n'); const i = lines.findIndex(l => l.includes(name.length > 2 ? name : name + ' =')); return i + 1 }
 function cell(v, t) {
  if (v === null || v === undefined) return '<td class="q-nul">null</td>';
  if (typeof v === 'object') return v.e ? `<td class="q-e" title="${E(v.e)}">Error</td>` : `<td class="q-nest">${E(v.n)}</td>`;
  if (typeof v === 'number') { const pct = /Percentage/.test(t || ''); return `<td class="q-n">${E(pct ? (v * 100).toFixed(2) + '%' : Number.isInteger(v) ? v : +v.toPrecision(12))}</td>` }
  return `<td>${E(v)}</td>`
 }
 const TL = { text: 'ABC 文字', integer: '123 整数', numeric: '1.2 数', date: '日付', datetime: '日時' };
 function table(d, h, n = 40) {
  if (!d.ok) return '';
  return `<div class="q-tbl" style="max-height:${h}px"><table><thead><tr><th>#</th>${d.columns.map(c => `<th>${E(c.name)}<small>${E(TL[c.out] || c.out)}</small></th>`).join('')}</tr></thead><tbody>${d.rows.slice(0, n).map((r, i) => `<tr><td class="q-n q-nul">${i + 1}</td>${r.map((v, j) => cell(v, d.columns[j].type)).join('')}</tr>`).join('')}</tbody></table></div>`
 }
 function status(d, compact) {
  if (!d.ok) return `<span class="q-pill q-ng">止まりました: ${E(d.error.step || '')}</span>`;
  return `<span class="q-pill q-ok">${d.row_count}行 × ${d.columns.length}列</span>${d.error_cells ? `<span class="q-pill q-warn">誤りのセル ${d.error_cells}</span>` : ''}${compact ? '' : `<span class="q-pill">${d.elapsed}秒</span>`}`
 }
 function errBox(d) {
  if (d.ok) return '';
  const e = d.error;
  return `<div class="q-err"><b>ステップ「${E(e.step)}」で止まりました${e.origin_step ? `（もとは「${E(e.origin_step)}」）` : ''}</b><p>${E(e.message)}</p><small>クエリ「${E(e.query)}」 · 式の ${stepLine(e.origin_step || e.step)} 行目 · 直したら「確かめる」を押す</small></div>`
 }
 function steps(d, opts = {}) {
  const q = d.queries.find(x => x.name === d.query) || d.queries[0];
  const errAt = d.ok ? -1 : q.steps.indexOf(d.error.origin_step || d.error.step);
  const cur = d.ok ? q.steps.indexOf(d.step) : errAt;
  return `<div class="q-steps">${q.steps.map((s, i) => `<div class="q-step${i === cur && d.ok ? ' q-on' : ''}${i === errAt ? ' q-err' : ''}${errAt >= 0 && i > errAt ? ' q-after' : ''}"><b title="${E(s)}">${E(s)}</b><i>${i === errAt ? '⚠' : (errAt >= 0 && i > errAt ? '' : '✓')}</i></div>`).join('')}</div>`
 }
 function stepChips(d) {
  const q = d.queries.find(x => x.name === d.query) || d.queries[0];
  const errAt = d.ok ? -1 : q.steps.indexOf(d.error.origin_step || d.error.step);
  return `<div class="q-chips">${q.steps.map((s, i) => `<span class="q-chip${i === q.steps.length - 1 && d.ok ? ' q-on' : ''}${i === errAt ? ' q-err' : ''}">${i + 1}. ${E(s)}</span>`).join('')}</div>`
 }
 function queries(d) { return `<div class="q-chips">${d.queries.map(q => `<span class="q-chip${q.name === d.query ? ' q-on' : ''}${q.main ? ' q-main' : ''}">${E(q.name)}</span>`).join('')}</div>` }
 function head(extra = '') {
  return `<div class="q-head"><label class="q-f">クエリ名<input class="q-t" value="${E(st.item.name)}"></label><label class="q-f">用途メモ<input class="q-t" value="${E(st.item.description || '')}"></label><div class="q-row">${extra}<button class="q-btn q-pri">保存</button></div></div>`
 }
 const IO = '<button class="q-btn q-sm">貼り付け</button><button class="q-btn q-sm">フォルダーから作る</button>';
 const D = {
  // A: Power Query の画面と同じ並び（左にクエリとステップ、真ん中に式、下に結果）
  A(d) {
   return `${head()}<div style="display:grid;grid-template-columns:230px minmax(0,1fr);gap:10px">
   <div class="q-rail"><div class="q-card"><div class="q-cap">クエリ<small>${d.queries.length}本</small></div><div class="q-steps">${d.queries.map(q => `<div class="q-step${q.name === d.query ? ' q-on' : ''}"><b>${E(q.name)}</b><i>${q.main ? '出す' : ''}</i></div>`).join('')}</div></div>
   <div class="q-card"><div class="q-cap">適用したステップ</div>${steps(d)}</div></div>
   <div class="q-grid2"><div class="q-row"><div class="q-stat q-grow">${status(d)}</div>${IO}<button class="q-btn q-sm">確かめる</button></div>${code(st.code, 11, stepLine(d.step), d.ok ? 0 : stepLine(d.error.origin_step || d.error.step))}${errBox(d)}${table(d, 300)}</div></div>`
  },
  // B: 式と結果を左右に（左は式だけ、右にステップと結果）
  B(d) {
   return `${head()}<div style="display:grid;grid-template-columns:minmax(0,0.9fr) minmax(0,1.1fr);gap:10px">
   <div class="q-card"><div class="q-cap">式（M）<span class="q-grow"></span>${IO}</div>${code(st.code, 30, 0, d.ok ? 0 : stepLine(d.error.origin_step || d.error.step))}</div>
   <div class="q-grid2" style="align-content:start"><div class="q-card"><div class="q-cap">クエリ</div>${queries(d)}<div class="q-cap">ステップ</div>${stepChips(d)}</div><div class="q-row q-stat">${status(d)}</div>${errBox(d)}${table(d, 360)}</div></div>`
  },
  // C: 上から順に（式 → ステップ → 結果）
  C(d) {
   return `${head(IO)}<div class="q-card"><div class="q-cap">式（M）<small>Excel の詳細エディターの中身をそのまま貼り付けます</small></div>${code(st.code, 9, 0, d.ok ? 0 : stepLine(d.error.origin_step || d.error.step))}</div>
   <div class="q-card"><div class="q-row"><div class="q-cap">クエリ</div>${queries(d)}</div><div class="q-row"><div class="q-cap">ステップ</div>${stepChips(d)}</div></div>
   <div class="q-row q-stat">${status(d)}</div>${errBox(d)}${table(d, 260)}`
  },
  // D: タブで切り替え（式／結果）。ステップは右の欄にいつも出す
  D(d) {
   return `${head()}<div style="display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:10px"><div class="q-grid2"><div class="q-tabs"><span class="q-tab">式（M）</span><span class="q-tab q-on">結果</span><span class="q-grow"></span><div class="q-stat">${status(d, 1)}</div></div>${errBox(d)}${table(d, 470)}</div>
   <div class="q-rail"><div class="q-card"><div class="q-cap">クエリ</div>${queries(d)}</div><div class="q-card"><div class="q-cap">適用したステップ</div>${steps(d)}</div><div class="q-row">${IO}</div></div></div>`
  },
  // E: 結果が主役（式は下の引き出しに畳む）
  E(d) {
   return `${head()}<div style="display:grid;grid-template-columns:220px minmax(0,1fr);gap:10px"><div class="q-rail"><div class="q-card"><div class="q-cap">ステップ</div>${steps(d)}</div></div>
   <div class="q-grid2"><div class="q-row"><div class="q-stat q-grow">${status(d)}</div>${queries(d)}</div>${errBox(d)}${table(d, 420)}<details><summary>式（M）を見る・直す（${st.code.split('\n').length}行）</summary></details></div></div>`
  },
  // F（方向の違う案: 手順を分ける）: ①取り込む → ②確かめる → ③保存
  F(d) {
   return `<div class="q-wiz"><div class="q-wz q-done"><i>✓</i>取り込む（貼り付け・フォルダーから）</div><div class="q-wz q-on"><i>2</i>確かめる（ステップと結果）</div><div class="q-wz"><i>3</i>名前を付けて保存</div></div>
   <div style="display:grid;grid-template-columns:240px minmax(0,1fr);gap:10px"><div class="q-rail"><div class="q-card"><div class="q-cap">クエリ</div>${queries(d)}</div><div class="q-card"><div class="q-cap">ステップ</div>${steps(d)}</div></div>
   <div class="q-grid2"><div class="q-row q-stat">${status(d)}</div>${errBox(d)}${table(d, 400)}</div></div><div class="q-foot"><button class="q-btn">戻る（式を直す）</button><button class="q-btn q-pri">次へ（保存）</button></div>`
  },
  // G（方向の違う案: 既定で済ませて例外だけ）: フォルダー・シートの欄が主、式は畳む。止まったときだけ式と場所を出す
  G(d) {
   return `${head()}<div class="q-card"><div class="q-row"><span class="q-seg"><span class="q-on">フォルダーから作る</span><span>式を貼り付ける</span></span><span class="q-note">Excel の式を持っているなら「式を貼り付ける」</span></div>
   <div class="q-form4"><label class="q-f">フォルダー<input class="q-t" value=".\\日報"></label><label class="q-f">シート<input class="q-t" value="実績"></label><label class="q-f">ファイル名に含む<input class="q-t" value=""></label></div></div>
   <div class="q-row q-stat">${status(d)}</div>${errBox(d)}${d.ok ? '' : code(st.code, 6, 0, stepLine(d.error.origin_step || d.error.step))}${table(d, 360)}<details><summary>作った式（M）を見る</summary></details>`
  },
 };
 // 2回目: 1回目の上位（E・A・D）の良いところと、誤りの場面で見えた欠け（止まったクエリに印が無い・式が止まった行を
 // 見せない）を埋める組合せ案。共通の決まり: 止まったら、止まったクエリに ⚠ を付けて自動で選び、そのステップに印、
 // 式は止まった行へ送って赤くする。式の欄は、選んでいるクエリの部分から見せる。
 const errQ = d => d.ok ? d.query : (d.error.origin_query || d.error.query);
 const errS = d => d.ok ? '' : (d.error.origin_step || d.error.step);
 function qList(d) {
  const sel = errQ(d);
  return `<div class="q-steps">${d.queries.map(q => `<div class="q-step${q.name === sel ? (d.ok ? ' q-on' : ' q-err') : ''}"><b>${E(q.name)}</b><i>${!d.ok && q.name === sel ? '⚠' : q.main ? '出す' : ''}</i></div>`).join('')}</div>`
 }
 function stepsOf(d) {
  const q = d.queries.find(x => x.name === errQ(d)) || d.queries[0];
  const errAt = d.ok ? -1 : q.steps.indexOf(errS(d));
  const cur = d.ok ? q.steps.length - 1 : errAt;
  return `<div class="q-cap" style="font-size:11.5px;color:#6b7f88">${E(q.name)} のステップ</div><div class="q-steps">${q.steps.map((s, i) => `<div class="q-step${i === cur && d.ok ? ' q-on' : ''}${i === errAt ? ' q-err' : ''}${errAt >= 0 && i > errAt ? ' q-after' : ''}"><b title="${E(s)}">${E(s)}</b><i>${i === errAt ? '⚠' : (errAt >= 0 && i > errAt ? '' : '✓')}</i></div>`).join('')}</div>`
 }
 function qStart(name) { const lines = st.code.split('\n'); const i = lines.findIndex(l => l.trim() === '// ' + name); return i < 0 ? 1 : i + 1 }
 function codeAt(d, rows) {
  const lines = st.code.split('\n');
  const bad = d.ok ? 0 : (() => { const s0 = qStart(errQ(d)); const i = lines.findIndex((l, k) => k >= s0 && l.includes(errS(d) + ' =')); return i + 1 })();
  const from = d.ok ? qStart(d.query) : Math.max(1, bad - 2);
  const part = lines.slice(from - 1, from - 1 + rows);
  return `<pre class="q-code" style="counter-reset:ln ${from - 1}">${part.map((l, i) => `<span class="${from + i === bad ? 'q-bad' : ''}">${hl(l) || ' '}</span>`).join('').replace(/<em /g, '<i style="font-style:normal" ').replace(/<\/em>/g, '</i>')}</pre>`
 }
 const NEXT = d => d.ok ? '<span class="q-note">式を直したら「確かめる」、よければ「保存」</span>' : `<span class="q-note" style="color:#a12d1a;font-weight:800">⚠ の行を直して「確かめる」</span>`;
 const IO2 = '<button class="q-btn q-sm">ファイルから取り込む（.odc・Excel）</button><button class="q-btn q-sm">フォルダーから作る</button>';
 // H: E（結果が主役）＋A（クエリとステップを左に縦に）＋止まったら式を自動で開いて止まった行へ
 D.H = d => `${head()}<div style="display:grid;grid-template-columns:240px minmax(0,1fr);gap:10px"><div class="q-rail"><div class="q-card"><div class="q-cap">クエリ<small>${d.queries.length}本</small></div>${qList(d)}</div><div class="q-card">${stepsOf(d)}</div></div>
   <div class="q-grid2" style="align-content:start"><div class="q-row"><div class="q-stat q-grow">${status(d)}</div>${IO2}<button class="q-btn q-sm q-pri">確かめる</button></div>${errBox(d)}${d.ok ? table(d, 330) : ''}<details ${d.ok ? '' : 'open'}><summary>式（M）· ${st.code.split('\n').length}行 ${d.ok ? '' : '— 止まった行'}</summary>${codeAt(d, d.ok ? 8 : 9)}</details></div></div>`;
 // I（利用者から届いた Power Query エディターの画面を手本に描き直した）: 左にクエリの一覧（ヘルパー クエリとその他のクエリに
 // 分け、表・fx・パラメーターの印）、真ん中に数式バー（選んだステップの式だけ）と表、右に「クエリの設定」（名前・用途・適用した
 // ステップ）、下に状態の帯（何列・何行・誤りのセル・下読みの範囲）。式の全体は「詳細エディター」で開く（Excel と同じ）。
 const ICON = { query: '▦', function: 'fx', parameter: '⚙' };
 function tree(d) {
  const sel = errQ(d);
  const item = q => `<div class="q-step${q.name === sel ? (d.ok ? ' q-on' : ' q-err') : ''}" style="grid-template-columns:22px minmax(0,1fr) auto"><span style="font-size:11px;color:#0b6577;font-weight:800">${ICON[q.kind] || '▦'}</span><b>${E(q.name)}</b><i>${!d.ok && q.name === sel ? '⚠' : q.main ? '出す' : ''}</i></div>`;
  const h = d.queries.filter(q => q.helper), o = d.queries.filter(q => !q.helper);
  return `${h.length ? `<div class="q-note">▾ ヘルパー クエリ [${h.length}]</div>${h.map(item).join('')}` : ''}<div class="q-note">▾ その他のクエリ [${o.length}]</div>${o.map(item).join('')}`
 }
 function fxBar(d) {
  const q = d.queries.find(x => x.name === errQ(d)) || d.queries[0];
  const i = d.ok ? q.steps.length - 1 : q.steps.indexOf(errS(d));
  const sp = q.spans[i] || [0, 0];
  const text = st.code.slice(sp[0], sp[1]).replace(/\s+/g, ' ');
  return `<div class="q-row" style="border:1px solid ${d.ok ? '#c8d6dc' : '#f1b8ae'};border-radius:8px;background:${d.ok ? '#fff' : '#fff6f4'};padding:4px 6px;gap:6px;flex-wrap:nowrap"><span class="q-note" style="font-weight:800;color:#0b6577">fx</span><code style="font-family:Consolas,monospace;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0">= ${E(text)}</code><button class="q-btn q-sm">詳細エディター</button></div>`
 }
 function statusBar(d) {
  return `<div class="q-row" style="background:#0b6577;color:#fff;border-radius:7px;padding:5px 10px;font-size:11.5px;font-weight:700">${d.ok ? `${d.columns.length} 列, ${d.row_count} 行${d.error_cells ? ` · 誤りのセル ${d.error_cells}` : ''} · 各シートの先頭 1000 行で下読み` : `止まりました: クエリ「${E(errQ(d))}」のステップ「${E(errS(d))}」`}<span class="q-grow"></span>${d.elapsed}秒</div>`
 }
 D.I = d => `<div style="display:grid;grid-template-columns:220px minmax(0,1fr) 250px;gap:10px">
   <div class="q-card" style="align-content:start;gap:3px"><div class="q-cap">クエリ<small>[${d.queries.length}]</small></div>${tree(d)}</div>
   <div class="q-grid2" style="align-content:start">${fxBar(d)}${d.ok ? table(d, 455) : errBox(d) + codeAt(d, 9)}${statusBar(d)}</div>
   <div class="q-card" style="align-content:start"><div class="q-cap">クエリの設定</div><label class="q-f">名前<input class="q-t" value="${E(st.item.name)}"></label><label class="q-f">用途メモ<input class="q-t" value="${E(st.item.description || '')}"></label><div class="q-cap">適用したステップ</div>${stepsOf(d)}<div class="q-row"><button class="q-btn q-sm">取り込み（.odc・Excel）</button><button class="q-btn q-sm">フォルダーから作る</button></div><div class="q-row"><button class="q-btn q-sm">確かめる</button><span class="q-grow"></span><button class="q-btn q-pri">保存</button></div></div></div>`;
 // J: D（タブ）＋E: 結果と式をタブで切り替え、止まったら式のタブへ自動で切り替えて止まった行へ
 D.J = d => `${head()}<div style="display:grid;grid-template-columns:230px minmax(0,1fr);gap:10px"><div class="q-rail"><div class="q-card"><div class="q-cap">クエリ</div>${qList(d)}</div><div class="q-card">${stepsOf(d)}</div></div>
   <div class="q-grid2" style="align-content:start"><div class="q-tabs"><span class="q-tab${d.ok ? ' q-on' : ''}">結果</span><span class="q-tab${d.ok ? '' : ' q-on'}">式（M）${d.ok ? '' : ' ⚠'}</span><span class="q-grow"></span><div class="q-stat">${status(d, 1)}</div></div>${errBox(d)}${d.ok ? table(d, 400) : codeAt(d, 14)}<div class="q-row">${NEXT(d)}<span class="q-grow"></span>${IO2}<button class="q-btn q-sm q-pri">確かめる</button></div></div></div>`;
 // K: A を詰めた形: 左にステップ（主）とクエリ、右は「式の窓（選んだクエリの部分・7行）→ 結果」。次の一手を状態の行に言葉で出す（F）
 D.K = d => `${head()}<div style="display:grid;grid-template-columns:230px minmax(0,1fr);gap:10px"><div class="q-rail"><div class="q-card"><div class="q-cap">クエリ</div>${qList(d)}</div><div class="q-card">${stepsOf(d)}</div></div>
   <div class="q-grid2" style="align-content:start"><div class="q-row"><div class="q-stat">${status(d)}</div>${NEXT(d)}<span class="q-grow"></span>${IO2}<button class="q-btn q-sm q-pri">確かめる</button></div>${codeAt(d, 7)}${errBox(d)}${d.ok ? table(d, 300) : ''}</div></div>`;

 async function load() {
  const list = await fetch('/api/m-queries').then(r => r.json());
  const item = list.items.find(x => x.name === '日報の集約') || list.items[0];
  const post = body => fetch('/api/m-query/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
  const ok = await post({ code: item.code, name: item.name });
  const bad = await post({ code: item.code.replace(/"実績"/g, '"実績表"'), name: item.name });
  st = { item, code: item.code, ok, bad };
 }
 window.PQ = {
  async show(k, view = 1) {
   style(); if (!st) await load();
   document.querySelector('[data-p="mqueries"]')?.click();
   await new Promise(r => setTimeout(r, 300));
   if (typeof mqOpen === 'function') mqOpen(mqCache.find(x => x.name === st.item.name));
   const box = document.getElementById('mq-edit'); box.hidden = false; document.getElementById('mq-empty').hidden = true;
   box.innerHTML = `<div class="pq">${D[k](view === 2 ? st.bad : st.ok)}</div>`;
  },
  keys: Object.keys(D)
 };
})();
