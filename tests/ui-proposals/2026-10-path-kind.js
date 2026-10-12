// 2.2.4 パスの欄の「書き方の札」と「どこの物を読んでいるか」（CLAUDE.md §3）。
// いま: 札は「相対パス / 基準: アプリフォルダー」か「絶対パス」の2つだけ。<PC>\… も %USERPROFILE%\… も相対と出る。
// 基準の名前が古い（実際は配布の置き場）。編集画面では、欄が空のうちに札を作るので、値が入っても「絶対パス」のまま。
// 置き場に無く、データの基準（写しの data）の物を使っていても、それを言う言葉が無い。
// 本物の画面（共通設定 → 場所、対象の編集）の .path-tools と .pf-note を、案ごとに描き替える。中身は撮影用の環境の実の値。
// 撮り方: window.PB.show(k)。1回目 A〜G（5案＋方向の違う2案 F・G）。2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 // 書き方の種類（実装では navi_paths.path_kind が決め、/api/machine-paths・/api/path-convert が返す）
 const KIND = v => { v = String(v || '').trim(); if (!v) return 'empty'; if (/^<PC>/i.test(v)) return 'pc'; if (/^%[^%]+%|^~|^\$/.test(v)) return 'env';
  if (/^\\\\/.test(v)) return 'unc'; if (/^[A-Za-z]:[\\/]/.test(v) || v.startsWith('/')) return 'abs'; return 'rel' };
 const WORD = { rel: '相対パス', abs: '絶対パス', unc: '共有（UNC）', pc: 'このPCの場所', env: '利用者ごとの場所', empty: '未設定' };
 const BASE = { place: '置き場', data: 'データの基準', app: 'アプリの場所', local: 'このPC', none: '' };
 let ROOTS = {};
 const where = (kind, real) => { real = String(real || '');
  if (kind === 'pc') return 'local'; if (kind !== 'rel') return 'none';
  if (ROOTS.place && real.startsWith(ROOTS.place)) return 'place'; if (ROOTS.data && real.startsWith(ROOTS.data)) return 'data';
  if (ROOTS.app && real.startsWith(ROOTS.app)) return 'app'; return 'place' };
 const tail = (base, real) => { const r = ROOTS[base] || ''; let t = r && real.startsWith(r) ? real.slice(r.length) : real; return t.replace(/\//g, '\\') || '\\' };
 const fields = () => { const out = [];
  document.querySelectorAll('#pathform .pf-row').forEach(row => { const i = row.querySelector('input'); if (!i) return; const k = row.id.replace(/^pf-/, '');
   const r = (window.__PB_ROWS || []).find(x => x.key === k) || {}; out.push({ row, input: i, tools: row.querySelector('.path-tools'), note: row.querySelector('.pf-note'), real: r.resolved || '', exists: !!r.exists }) });
  const ed = document.getElementById('m-rne-path'); if (ed && ed.offsetParent) out.push({ row: ed.closest('label'), input: ed, tools: ed.closest('label').querySelector('.path-tools'), note: null, real: (ROOTS.place || '') + '/rne/NEW.RNE', exists: false, editor: true });
  return out.map(f => { f.kind = KIND(f.input.value); f.base = where(f.kind, f.real); f.fell = f.kind === 'rel' && f.base !== 'place'; return f }) };
 const toggle = f => f.kind === 'rel' ? '絶対パスに書き換える' : (f.kind === 'abs' || f.kind === 'unc') ? '相対パスに書き換える' : '';
 const btn = (f, cls = '') => toggle(f) ? `<button type="button" class="pathmode path-toggle ${cls}">${toggle(f)}</button>` : '';
 const fellText = f => `置き場に無いので、${BASE[f.base]}の物を使っています`;
 const CSS = `
  .pbx{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;line-height:1.5}
  .pbx .chip{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-weight:800;font-size:11.5px;white-space:nowrap}
  .k-rel{background:#e3f1f4;color:#0b6577}.k-abs,.k-unc{background:#eef1f3;color:#4b5f69}.k-pc{background:#ece8f6;color:#5a3f93}.k-env{background:#e9eef8;color:#2f4f8a}
  .k-fell{background:#fbf0dc;color:#8a5a0c}.k-miss{background:#fbe9e6;color:#a4463d}
  .pbx .sub{color:#4d6670}.pbx .amber{color:#8a5a0c;font-weight:700}.pbx .red{color:#a4463d;font-weight:700}
  .pbx code{font-size:11.5px;background:#f3f6f8;padding:1px 6px;border-radius:5px;color:#27434f}
  .pbx .path-toggle{padding:3px 8px!important;font-size:11.5px!important;min-height:0!important}
  .pbx .linkish{background:none!important;border:0!important;color:#0b6577!important;text-decoration:underline;padding:0!important}
  .pbx .dot{width:8px;height:8px;border-radius:50%;display:inline-block}.d-ok{background:#087a57}.d-fell{background:#c58a2b}.d-miss{background:#b93b32}.d-na{background:#a9b6bc}
  .pb-two{display:grid;gap:3px}.pb-two .line2{font-size:12px;color:#4d6670}.pb-two .line2.amber{color:#8a5a0c}
  .pb-crumb{display:inline-flex;align-items:stretch;border:1px solid #d4e0e5;border-radius:6px;overflow:hidden;font-size:12px}
  .pb-crumb b{padding:2px 8px;background:#e3f1f4;color:#0b6577}.pb-crumb.fell b{background:#fbf0dc;color:#8a5a0c}.pb-crumb.pc b{background:#ece8f6;color:#5a3f93}.pb-crumb.env b{background:#e9eef8;color:#2f4f8a}
  .pb-crumb span{padding:2px 8px;color:#27434f;font-family:Consolas,monospace;background:#fff}
  .pb-adorn{display:flex;align-items:stretch}.pb-adorn .pre{display:flex;align-items:center;padding:0 9px;border:1px solid #c8d6dc;border-right:0;border-radius:8px 0 0 8px;font-size:12px;font-weight:800;white-space:nowrap}
  .pb-adorn input{border-radius:0 8px 8px 0!important}
  .pre.k-rel{background:#e3f1f4}.pre.k-fell{background:#fbf0dc}.pre.k-pc{background:#ece8f6}.pre.k-env{background:#e9eef8}
  .pb-exc{display:flex;gap:8px;align-items:center;padding:5px 9px;border-radius:7px;background:#fdf6e8;border:1px solid #efdcb5;color:#7a4c06;font-size:12px;font-weight:700}
  .pb-exc.info{background:#f4f1fa;border-color:#e0d8f0;color:#4d3a7c;font-weight:600}
  .pb-more{color:#7a8b93;font-size:11.5px}`;
 const V = {
  A: { name: 'A 札の言葉を正す（いまの形のまま）', html: f => `<div class="pbx">${btn(f)}<span class="chip k-${f.fell ? 'fell' : f.kind}">${f.kind === 'rel' ? (f.fell ? '相対パス / ' + BASE[f.base] + 'の物' : '相対パス / 基準: 置き場') : WORD[f.kind]}</span></div>` },
  B: { name: 'B 実体を1行で（→ 置き場\\rne ●）', html: f => { const d = f.kind === 'rel' || f.kind === 'pc' ? `${BASE[f.base]}${tail(f.base, f.real)}` : '';
   return `<div class="pbx"><span class="dot ${f.fell ? 'd-fell' : f.exists ? 'd-ok' : 'd-na'}"></span><span class="sub">${WORD[f.kind]}</span>${d ? `<span class="sub">→</span><code>${E(d)}</code>` : ''}${f.fell ? `<span class="amber">（置き場に無い）</span>` : ''}${btn(f, 'linkish')}</div>` } },
  C: { name: 'C 基準の札＋残りの道（パンくず）', html: f => { if (f.kind === 'abs' || f.kind === 'unc') return `<div class="pbx"><span class="chip k-abs">${WORD[f.kind]}</span>${btn(f)}</div>`;
   const head = f.kind === 'env' ? '%USERPROFILE%' : BASE[f.base]; const rest = f.kind === 'env' ? f.input.value.replace(/^%[^%]+%/, '') : tail(f.base, f.real);
   return `<div class="pbx"><span class="pb-crumb ${f.fell ? 'fell' : f.kind}"><b>${E(head)}</b><span>${E(rest)}</span></span>${f.fell ? '<span class="amber">置き場に無いので、こちらを使っています</span>' : ''}${btn(f)}</div>` } },
  D: { name: 'D 色の札だけ（詳しくは指を置くと）', html: f => `<div class="pbx"><span class="chip k-${f.fell ? 'fell' : f.kind}" title="${E(f.real)}">${f.fell ? '別の場所の物' : f.kind === 'rel' ? '置き場から' : WORD[f.kind]}</span><span class="pb-more">ⓘ</span>${btn(f, 'linkish')}</div>` },
  E: { name: 'E 2段（書き方／見つかった場所）', html: f => `<div class="pb-two"><div class="pbx"><span class="chip k-${f.kind}">${WORD[f.kind]}</span>${btn(f)}</div>${f.kind === 'rel' || f.kind === 'pc' || f.kind === 'env' ? `<div class="line2 ${f.fell ? 'amber' : ''}">${f.fell ? fellText(f) : f.kind === 'env' ? '使う人のプロファイルの下（PCごと・人ごとに実体が変わります）' : f.kind === 'pc' ? 'このPCのローカル領域から（PCごとに実体が変わります）' : '置き場から読みます'}</div>` : ''}</div>` },
  F: { name: 'F 既定は黙り、例外だけ言う', html: f => f.fell ? `<div class="pb-exc">⚠ ${fellText(f)}<span class="sub" style="font-weight:600;color:#7a4c06">（${E(BASE[f.base] + tail(f.base, f.real))}）</span></div>` : (f.kind === 'pc' || f.kind === 'env') ? `<div class="pb-exc info">${f.kind === 'pc' ? 'このPCのローカル領域を指します（PCごとに変わります）' : '使う人のプロファイルを指します（人ごとに変わります）'}</div>` : `<div class="pbx">${btn(f, 'linkish')}</div>` },
  G: { name: 'G 欄の頭に基準を固定で出す', html: f => `<div class="pbx">${f.fell ? `<span class="amber">${fellText(f)}</span>` : ''}${btn(f, 'linkish')}</div>`, adorn: f => f.kind === 'rel' ? (f.fell ? ['k-fell', BASE[f.base] + ' \\'] : ['k-rel', '置き場 \\']) : f.kind === 'pc' ? ['k-pc', 'このPC'] : f.kind === 'env' ? ['k-env', '利用者ごと'] : null },
 };
 // ---- 2回目: 組合せ案（C の基準の札を土台に、F の「例外は帯で言う」、B の「状態の点」、E の「例外だけ2行目」を合わせる）
 const crumb = (f, extra = '') => { if (f.kind === 'abs' || f.kind === 'unc') return `<span class="chip k-abs">${WORD[f.kind]}</span>`;
  const head = f.kind === 'env' ? '利用者ごと' : BASE[f.base]; const rest = f.kind === 'env' ? f.input.value.replace(/^%[^%]+%/, '') : tail(f.base, f.real);
  return `<span class="pb-crumb ${f.fell ? 'fell' : f.kind}"${extra}><b>${E(head)}</b><span>${E(rest)}</span></span>` };
 Object.assign(V, {
  H: { name: 'H 基準の札＋例外は帯（C+F）', html: f => `<div class="pb-two"><div class="pbx">${crumb(f)}${btn(f, 'linkish')}</div>${f.fell ? `<div class="pb-exc">⚠ ${fellText(f)}</div>` : ''}</div>` },
  I: { name: 'I 基準の札＋状態の点（C+B）', html: f => `<div class="pbx"><span class="dot ${f.fell ? 'd-fell' : f.exists ? 'd-ok' : 'd-na'}"></span>${crumb(f)}${f.fell ? '<span class="amber">置き場に無い</span>' : ''}${btn(f, 'linkish')}</div>` },
  J: { name: 'J 普段は控えめな道・例外は帯（F+B）', html: f => f.fell ? `<div class="pb-exc">⚠ ${fellText(f)}　<code>${E(BASE[f.base] + tail(f.base, f.real))}</code></div>` : `<div class="pbx"><span class="sub">${f.kind === 'rel' || f.kind === 'pc' ? E(BASE[f.base] + tail(f.base, f.real)) : WORD[f.kind]}</span>${btn(f, 'linkish')}</div>` },
  K: { name: 'K 基準の札＋例外だけ2行目（C+E）', html: f => `<div class="pb-two"><div class="pbx">${crumb(f)}${btn(f, 'linkish')}</div>${f.fell ? `<div class="line2 amber">${fellText(f)}</div>` : ''}</div>` },
 });
 window.PB = { V, show: async k => {
  if (!window.__PB_ROWS) { const d = await fetch('/api/machine-paths').then(r => r.json()); window.__PB_ROWS = d.rows;
   const fx = n => ((d.fixed || []).find(x => x.label === n) || {}).path || ''; ROOTS = { place: fx('相対パスの基準'), data: fx('データの基準'), app: fx('アプリの場所'), local: fx('このPCのローカル領域') } }
  let st = document.getElementById('pb-style'); if (!st) { st = document.createElement('style'); st.id = 'pb-style'; document.head.appendChild(st) } st.textContent = CSS + (V[k].css || '');
  for (const f of fields()) {
   if (!f.tools) continue; f.tools.innerHTML = V[k].html(f); f.tools.classList.remove('compact-path-tools');
   const wrap = f.input.parentElement; wrap.querySelectorAll('.pre').forEach(x => x.remove()); wrap.classList.remove('pb-adorn');
   const a = V[k].adorn && V[k].adorn(f); if (a) { wrap.classList.add('pb-adorn'); wrap.insertAdjacentHTML('afterbegin', `<span class="pre ${a[0]}">${E(a[1])}</span>`) }
  }
 } };
})();
