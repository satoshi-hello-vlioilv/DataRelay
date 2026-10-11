// 2.1.3 共通設定の横幅の使い方の案（CLAUDE.md §3）。
// いま: 項目の右側（入力欄の先）と、区分によっては下半分が空き、欄ごとに幅がばらばらで右端がそろわない。
// 本物の画面の #paths .settings-shell（左の欄と区分の中身）を、案ごとの組み立てで置き換えて再現する（中身は全案で共通）。
// アプリの CSS（section を隠す・nav の形・input の幅）を受けないよう、同じ位置に重ねた箱（body の直下）へ描く。
// 撮り方: window.SW.show(k, view)。view 1 = 「動かし方」、view 2 = 「接続」（接続情報は登録済み・API は使える）。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 // ---- 部品 ----
 const st = (k, t) => `<span class="sw-st sw-${k}">${t}</span>`;
 const num = (v, u, w = 80) => `<span class="sw-num"><input value="${E(v)}" style="width:${w}px"><em>${u}</em></span>`;
 const tog = (on, t) => `<label class="sw-tog"><i class="${on ? 'on' : ''}"></i><span>${t}</span></label>`;
 const seg = (opts, cur) => `<div class="sw-seg">${opts.map(([v, b, s]) => `<span class="${v === cur ? 'on' : ''}"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</span>`).join('')}</div>`;
 const rec = t => `<i class="sw-rec">推奨 ${t}</i>`;
 const btn = (t, p) => `<button class="${p ? 'sw-btn' : 'sw-btn2'}">${t}</button>`;
 const path = (v) => `<div class="sw-path"><input value="${E(v)}">${btn('確認')}${btn('参照')}</div>`;
 // 項目: label・ctrl・説明・推奨
 const RUN = [
  { l: '同時実行ライン', c: num(6, 'ライン'), d: 'いくつの対象を同時に取るか。1 は直列、2〜5 は軽め、7〜24 は環境しだい', r: '6ライン' },
  { l: '値ごとに分けて出すときの既定の取り方', c: seg([['b', 'まとめて1回', '問い合わせ1回・受け取ってから分ける'], ['p', '値ごとに並列', '値ごとに同時に問い合わせ']], 'b'), d: '対象の設定で「既定に従う」を選んだ対象が、この取り方で動きます。どちらでも出るファイルは同じ', r: 'まとめて1回' },
  { l: '失敗したときの取り直し', c: `${tog(true, '自動実行が失敗したら取り直す')}<div class="sw-row">${num(5, '分後')}${num(1, '回まで')}</div>`, d: '自動実行が失敗したとき、失敗した対象だけを待ってから取り直します（手動の実行は取り直しません）', r: '入・5分後・1回' },
  { l: '自動実行の取りこぼし', c: num(30, '分以内なら遅れて実行'), d: '予定の時刻にほかの処理が動いていたとき、この時間内なら手が空いてから実行します（0 なら実行しない）', r: '30分以内' },
 ];
 const ADV = '<div class="sw-adv"><b>詳しい調整</b><span>ライン起動の間隔・手元の処理のライン・結合の待ち合わせ・ログの大きさ</span>' + st('ok', 'すべて推奨どおり') + '</div>';
 const LOGIN = `<div class="sw-card sw-login"><div class="sw-h"><b>Navigator の接続情報</b>${st('ok', '登録済み')}</div><dl class="sw-dl"><dt>サーバー</dt><dd>navsv01</dd><dt>利用者ID</dt><dd>harada</dd><dt>保存先</dt><dd>このPCの資格情報マネージャー</dd></dl><div class="sw-row">${btn('変える')}<button class="sw-link">ほかの symnavim.conf から取り込む</button><button class="sw-link sw-danger">このPCから消す</button></div></div>`;
 const CONF = `<div class="sw-card sw-conf"><div class="sw-h"><b>symnavim.conf（接続情報の取り込み元）</b>${st('off', '予備')}</div>${path('.\\config\\symnavim.conf')}<small class="sw-note">接続情報がこのPCに未登録のあいだだけ、ここから読みます。登録済みなので、いまは使っていません</small></div>`;
 const CHECKS = [['SymNaviA.dll 本体', 'C:\\NAVIAP\\dllVC14x64\\SymNaviA.dll'], ['bit数の一致', '64bit'], ['依存ランタイム（Visual C++）', '不足なし'], ['必要な関数', '53個を確認'], ['探す範囲', '3か所を探して 4件を検出']];
 const API = (mode) => `<div class="sw-card sw-api"><div class="sw-h"><b>Navigator API の状態</b>${st('ok', '使えます')}<span class="sw-sp"></span>${btn('いま確認する')}</div>${mode === 'tiles' ? `<div class="sw-tiles">${CHECKS.map(([a, b]) => `<div>${st('ok', 'OK')}<b>${a}</b><small>${E(b)}</small></div>`).join('')}</div>` : mode === 'line' ? `<div class="sw-apiline">${CHECKS.map(([a, b]) => `<span>${st('ok', 'OK')} ${a}</span>`).join('')}</div><small class="sw-note sw-mono">${E(CHECKS[0][1])}</small>` : `<div class="sw-checks">${CHECKS.map(([a, b]) => `<div>${st('ok', 'OK')}<b>${a}</b><small>${E(b)}</small></div>`).join('')}</div>`}<details class="sw-more"><summary>候補ごとの確認結果と、必要なものの一覧</summary></details></div>`;
 const FIX = `<details class="sw-card sw-fix"><summary><b>DLL の探し方・指定の仕方</b><span>見つからないときはここで直します</span></summary></details>`;
 // 左の欄
 const NAV = (cat, wide) => `<div class="sw-nav ${wide ? 'wide' : ''}">${[['summary', '概', 'まとめ', 'いまの状態', ['ok', 'OK']], ['conn', '接', '接続', 'Navigator へつなぐ情報と API', ['ok', '使えます']], ['place', '場', '場所', '出力先・RNE・控えの置き場', ['ok', '4か所OK']], ['run', '動', '動かし方', '同時に動かす数・失敗したとき', ['ok', '推奨どおり']], ['safe', '守', '守り', '0件のとき・差し替える前の控え', ['ok', '推奨どおり']]].map(([k, i, t, s, b]) => `<button class="${k === cat ? 'on' : ''}"><i>${i}</i><span><b>${t}</b><small>${s}</small></span>${st(b[0], b[1])}</button>`).join('')}<em>管理</em>${[['出', '登録内容の持ち出し', 'ZIPで書き出し・取り込み'], ['配', '配布と更新', '配る版・新しいPCへの配り方'], ['仕', '仕様書', 'Navigator APIの原典'], ['版', 'バージョン情報', '更新履歴を確認']].map(([i, t, s]) => `<button><i>${i}</i><span><b>${t}</b><small>${s}</small></span></button>`).join('')}</div>`;
 const head = (t, s, b) => `<header class="sw-ph"><h3>${t}</h3>${b ? st(b[0], b[1]) : ''}<span>${s}</span></header>`;
 const RUNH = head('動かし方', '同時に動かす数・値ごとの取り方・失敗したとき', ['ok', '推奨どおり']);
 const CONNH = head('接続', 'Navigator へつなぐ情報と、Navigator API の状態', ['ok', '使えます']);
 // 項目の並べ方
 const f2 = x => `<div class="sw-f2"><div class="sw-l"><b>${x.l}</b>${rec(x.r)}<small>${x.d}</small></div><div class="sw-c">${x.c}</div></div>`;
 const f3 = x => `<div class="sw-f3"><div class="sw-l"><b>${x.l}</b></div><div class="sw-c">${x.c}</div><div class="sw-d">${rec(x.r)}<small>${x.d}</small></div></div>`;
 const fcard = x => `<div class="sw-card sw-fc"><div class="sw-l"><b>${x.l}</b>${rec(x.r)}</div><div class="sw-c">${x.c}</div><small class="sw-dd">${x.d}</small></div>`;

 const BANNER = v => `<div class="sw-banner">${st('ok', v === 1 ? '推奨と違う所はありません' : '直すところはありません')}<span>${v === 1 ? '推奨と違う値には黄色の印と「推奨に戻す」が出ます' : '接続情報は登録済み、API は使えます'}</span></div>`;
 const f3e = x => `<div class="sw-f3"><div class="sw-l"><b>${x.l}</b></div><div class="sw-c">${x.c}</div><div class="sw-d">${rec(x.r)}<small>${x.d}</small><small class="sw-eff">変えると: 次の実行から効きます</small></div></div>`;
 const shell = (cat, body, o = {}) => `<div class="sw-shell ${o.nonav ? 'nonav' : ''} ${o.cls || ''}">${o.nonav ? '' : NAV(cat, o.wide)}<div class="sw-main">${body}</div></div>`;
 const V = {
  A: { t: '項目を3列に（項目｜設定｜説明と推奨）', html: v => shell(v === 1 ? 'run' : 'conn', v === 1
    ? `<div class="sw-pane">${RUNH}<div class="sw-list">${RUN.map(f3).join('')}</div>${ADV}</div>`
    : `<div class="sw-pane">${CONNH}<div class="sw-cols2">${LOGIN}${API('list')}</div><div class="sw-cols2">${CONF}${FIX}</div></div>`) },
  B: { t: '項目をカードにして2段組', html: v => shell(v === 1 ? 'run' : 'conn', v === 1
    ? `<div class="sw-pane">${RUNH}<div class="sw-grid2">${RUN.map(fcard).join('')}</div>${ADV}</div>`
    : `<div class="sw-pane">${CONNH}<div class="sw-grid2">${LOGIN}${CONF}</div>${API('tiles')}${FIX}</div>`) },
  C: { t: '読みやすい幅で中央にそろえる', html: v => shell(v === 1 ? 'run' : 'conn', `<div class="sw-pane sw-center">${v === 1 ? RUNH + `<div class="sw-list">${RUN.map(f2).join('')}</div>${ADV}` : CONNH + LOGIN + CONF + API('list') + FIX}</div>`) },
  D: { t: '上のタブ＋全幅の2段組', html: v => `<div class="sw-shell nonav"><div class="sw-main"><div class="sw-tabs">${[['summary', 'まとめ'], ['conn', '接続'], ['place', '場所'], ['run', '動かし方'], ['safe', '守り']].map(([k, t]) => `<button class="${(v === 1 ? 'run' : 'conn') === k ? 'on' : ''}">${t} ${st('ok', 'OK')}</button>`).join('')}<span class="sw-sp"></span><button>持ち出し</button><button>配布と更新</button><button>仕様書</button><button>版</button></div>${v === 1
    ? `<div class="sw-pane">${RUNH}<div class="sw-grid2 plain">${RUN.map(f2).join('')}</div>${ADV}</div>`
    : `<div class="sw-pane">${CONNH}<div class="sw-cols2">${LOGIN + CONF}<div>${API('list')}${FIX}</div></div></div>`}</div></div>` },
  E: { t: '全区分を1画面に並べる（区分を開かない）', html: v => shell('summary', `<div class="sw-dash">
    <div class="sw-card sw-dp">${head('接続', 'Navigator へつなぐ情報と API', ['ok', '使えます'])}<dl class="sw-dl"><dt>接続情報</dt><dd>navsv01 · harada ${st('ok', '登録済み')}</dd><dt>API</dt><dd>SymNaviA.dll 64bit ${st('ok', '使えます')}</dd></dl><div class="sw-row">${btn('変える')}${btn('いま確認する')}</div></div>
    <div class="sw-card sw-dp">${head('場所', '出力先・RNE・控え', ['ok', '4か所OK'])}<dl class="sw-dl"><dt>既定の出力先</dt><dd class="sw-mono">\\\\nlmsrvngy03\\Read\\【New】実績</dd><dt>RNE</dt><dd class="sw-mono">.\\rne</dd><dt>控え</dt><dd class="sw-mono">&lt;PC&gt;\\backup</dd></dl></div>
    <div class="sw-card sw-dp ${v === 1 ? 'focus' : ''}">${head('動かし方', '同時に動かす数・失敗したとき', ['ok', '推奨どおり'])}<div class="sw-mini">${RUN.map(x => `<div><b>${x.l}</b>${x.c}</div>`).join('')}</div></div>
    <div class="sw-card sw-dp">${head('守り', '0件のとき・控え', ['ok', '推奨どおり'])}<div class="sw-mini"><div><b>0件なら公開しない</b>${tog(true, '入')}</div><div><b>差し替える前の控え</b>${tog(true, '世代で残す・3世代')}</div></div></div></div>`, { nonav: false }) },
  F: { t: '右に「この項目について」の欄（方向の違う案）', html: v => shell(v === 1 ? 'run' : 'conn', `<div class="sw-insp"><div class="sw-pane">${v === 1 ? RUNH + `<div class="sw-list">${RUN.map((x, i) => `<div class="sw-f2 ${i === 0 ? 'sel' : ''}"><div class="sw-l"><b>${x.l}</b>${rec(x.r)}</div><div class="sw-c">${x.c}</div></div>`).join('')}</div>${ADV}` : CONNH + LOGIN + CONF + API('line') + FIX}</div>
    <aside class="sw-card sw-help"><small>この項目について</small><b>${v === 1 ? '同時実行ライン' : 'Navigator API の状態'}</b><p>${v === 1 ? 'いくつの対象を同時に取るか。多いほど早く終わりますが、Navigator のサーバーと、このPCの負荷が増えます。' : 'SymNaviA.dll が見つかり、64bit で読み込め、必要な関数がそろっているかを確かめます。'}</p><dl class="sw-dl"><dt>推奨</dt><dd>${v === 1 ? '6ライン' : '—'}</dd><dt>いま</dt><dd>${v === 1 ? '6ライン（推奨どおり）' : '使えます'}</dd><dt>変えると</dt><dd>${v === 1 ? '次の実行から効きます' : '—'}</dd></dl><small class="sw-note">項目にカーソルを合わせると、ここが変わります</small></aside></div>`) },
  G: { t: '推奨と違う所・要対応だけを出し、ほかは一覧で（方向の違う案）', html: v => shell(v === 1 ? 'run' : 'conn', `<div class="sw-pane">${v === 1 ? RUNH + `<div class="sw-exc">${st('ok', '推奨と違う所はありません')}<span>変えるときは、下の一覧の行を押します</span></div><table class="sw-tbl"><tbody>${RUN.map(x => `<tr><th>${x.l}</th><td>${x.r}</td><td>${st('ok', '推奨どおり')}</td><td><button class="sw-link">変える</button></td></tr>`).join('')}<tr><th>詳しい調整（4項目）</th><td>すべて推奨どおり</td><td>${st('ok', '推奨どおり')}</td><td><button class="sw-link">変える</button></td></tr></tbody></table>`
    : CONNH + `<div class="sw-exc">${st('ok', '直すところはありません')}<span>接続情報は登録済み、API は使えます</span></div><table class="sw-tbl"><tbody><tr><th>接続情報</th><td>navsv01 · harada（このPCの資格情報マネージャー）</td><td>${st('ok', '登録済み')}</td><td><button class="sw-link">変える</button></td></tr>${CHECKS.map(([a, b]) => `<tr><th>${a}</th><td class="sw-mono">${E(b)}</td><td>${st('ok', 'OK')}</td><td></td></tr>`).join('')}<tr><th>symnavim.conf</th><td class="sw-mono">.\\config\\symnavim.conf</td><td>${st('off', '予備')}</td><td><button class="sw-link">変える</button></td></tr></tbody></table>${FIX}`}</div>`) },
  // ---- 2回目: 組合せ案 ----
  H: { t: 'A の3列＋G の「推奨と違う所」の帯＋F の「変えると」', html: v => shell(v === 1 ? 'run' : 'conn', v === 1
    ? `<div class="sw-pane">${RUNH}${BANNER(1)}<div class="sw-list">${RUN.map(f3e).join('')}</div>${ADV}</div>`
    : `<div class="sw-pane">${CONNH}${BANNER(2)}<div class="sw-cols2">${LOGIN}${API('list')}</div><div class="sw-cols2">${CONF}${FIX}</div></div>`) },
  I: { t: 'A の項目＋F を区分のまとめの欄に（右に常に出す）', html: v => shell(v === 1 ? 'run' : 'conn', `<div class="sw-insp"><div class="sw-pane">${v === 1 ? RUNH + `<div class="sw-list">${RUN.map(f2).join('')}</div>${ADV}` : CONNH + LOGIN + CONF + API('line') + FIX}</div>
    <aside class="sw-card sw-help"><small>この区分</small><b>${v === 1 ? '動かし方' : '接続'}</b><dl class="sw-dl"><dt>状態</dt><dd>${v === 1 ? st('ok', '推奨どおり') : st('ok', '使えます')}</dd><dt>推奨と違う</dt><dd>${v === 1 ? 'なし' : '—'}</dd><dt>最後の変更</dt><dd>10/11 07:48</dd></dl><p>${v === 1 ? '変えた値は次の実行から効きます。迷ったら「推奨に戻す」で戻せます。' : 'API が使えないときは、下の「DLL の探し方」から直します。'}</p></aside></div>`) },
  J: { t: 'G の表の見た目＋A の3列（その場で変える）＋帯', html: v => shell(v === 1 ? 'run' : 'conn', v === 1
    ? `<div class="sw-pane">${RUNH}${BANNER(1)}<div class="sw-tbl3">${RUN.map(x => `<div class="sw-tr"><b>${x.l}</b><div class="sw-c">${x.c}</div><div class="sw-d">${rec(x.r)}<small>${x.d}</small></div></div>`).join('')}</div>${ADV}</div>`
    : `<div class="sw-pane">${CONNH}${BANNER(2)}<div class="sw-tbl3">${[['Navigator の接続情報', `<span>navsv01 · harada</span><div class="sw-row">${btn('変える')}<button class="sw-link sw-danger">このPCから消す</button></div>`, 'このPCの資格情報マネージャーに保存しています'], ['Navigator API', `<span class="sw-mono">C:\\NAVIAP\\dllVC14x64\\SymNaviA.dll</span><div class="sw-apiline">${CHECKS.slice(1).map(([a]) => `<span>${st('ok', 'OK')} ${a}</span>`).join('')}</div>`, '64bit で読み込め、必要な関数がそろっています'], ['symnavim.conf', path('.\\config\\symnavim.conf'), '接続情報が未登録のあいだだけ読みます（いまは使っていません）']].map(([a, b, c]) => `<div class="sw-tr"><b>${a}</b><div class="sw-c">${b}</div><div class="sw-d"><small>${c}</small></div></div>`).join('')}</div>${FIX}</div>`) },
  K: { t: 'A の3列＋E（短い区分をまとめて縦を使う。動かし方と守りを1つに）', html: v => shell(v === 1 ? 'run' : 'conn', v === 1
    ? `<div class="sw-pane">${head('動かし方と守り', '同時に動かす数・失敗したとき・0件のとき・控え', ['ok', '推奨どおり'])}<div class="sw-sub">動かし方</div><div class="sw-list">${RUN.map(f3).join('')}</div>${ADV}<div class="sw-sub">守り</div><div class="sw-list">${[{ l: '0件なら公開しない', c: tog(true, '0件なら、いまのファイルを残す'), d: '取れた行が0件のとき、いまのファイルを差し替えずに残します', r: '入' }, { l: '差し替える前の控え', c: tog(true, '差し替える前に控えを取る') + seg([['g', '世代で残す'], ['d', '日数で残す'], ['b', '両方で残す']], 'g'), d: '控えは「場所」の控えの置き場へ取ります', r: '入・世代・3世代' }].map(f3).join('')}</div></div>`
    : `<div class="sw-pane">${CONNH}<div class="sw-cols2">${LOGIN}${API('list')}</div><div class="sw-cols2">${CONF}${FIX}</div></div>`, { cls: 'k' }) },
 };
 const CSS = `
  #sw-overlay{position:fixed;z-index:50;background:#f3f6f8;font-family:"Yu Gothic UI",Meiryo,sans-serif;font-size:13px;color:#17232d;overflow:hidden}
  #sw-overlay *{box-sizing:border-box}#sw-overlay button{font:inherit;cursor:pointer;color:#17384e}#sw-overlay input{font:inherit;width:auto;height:auto}
  #sw-overlay label{display:inline-flex;align-items:center;gap:8px;margin:0;font-size:inherit;font-weight:inherit;color:inherit}
  .sw-shell{display:grid;grid-template-columns:270px minmax(0,1fr);gap:16px;height:100%;min-height:0}.sw-shell.nonav{grid-template-columns:minmax(0,1fr)}
  .sw-nav{display:flex;flex-direction:column;gap:3px;padding:8px;background:#fff;border:1px solid #d7e0e5;border-radius:12px;align-self:start}
  .sw-nav button{display:grid;grid-template-columns:30px minmax(0,1fr) auto;align-items:center;gap:9px;padding:9px 10px;border:1px solid transparent;border-radius:9px;background:transparent;text-align:left}
  .sw-nav button.on{background:#e8f4f6;border-color:#bfe0e6}.sw-nav i{font-style:normal;display:grid;place-items:center;width:28px;height:28px;border-radius:8px;background:#eef3f5;color:#087c98;font-weight:800;font-size:12px}
  .sw-nav b{display:block;font-size:13px}.sw-nav small{display:block;font-size:10.5px;color:#647581;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sw-nav em{font-style:normal;font-size:10.5px;color:#7b8c93;font-weight:800;padding:10px 10px 2px}
  .sw-main{min-width:0;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:12px}
  .sw-pane{display:flex;flex-direction:column;gap:12px;padding:16px 20px;background:#fff;border:1px solid #d7e0e5;border-radius:12px}
  .sw-ph{display:flex;align-items:baseline;gap:10px}.sw-ph h3{margin:0;font-size:18px}.sw-ph>span:last-child{color:#4d6670;font-size:12px}
  .sw-st{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:10px;white-space:nowrap;font-style:normal}.sw-ok{background:#e1f3ea;color:#0a6a4a}.sw-off{background:#eef2f4;color:#6d8088}.sw-w{background:#fbefd7;color:#8a5a00}
  .sw-rec{display:inline-block;font-style:normal;font-size:10.5px;font-weight:700;color:#0b6f7f;background:#e6f4f6;border-radius:9px;padding:1px 8px}
  .sw-num{display:inline-flex;align-items:center;gap:6px}#sw-overlay .sw-num input{height:32px;border:1px solid #cdd9de;border-radius:7px;padding:0 8px;text-align:right;font-size:14px}.sw-num em{font-style:normal;color:#4d6670;font-size:12px}
  .sw-tog{cursor:pointer}.sw-tog i{width:36px;height:20px;border-radius:10px;background:#c5d2d7;position:relative}.sw-tog i.on{background:#0d8191}.sw-tog i::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff}.sw-tog i.on::after{left:18px}
  .sw-seg{display:inline-grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);border:1px solid #c9d8de;border-radius:9px;overflow:hidden;max-width:620px}.sw-seg span{display:grid;gap:1px;padding:7px 12px;border-left:1px solid #dbe5e9}.sw-seg span:first-child{border-left:0}.sw-seg span.on{background:#e8f4f6;box-shadow:inset 0 -3px 0 #0d8191}.sw-seg small{font-size:10.5px;color:#647581}
  .sw-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.sw-sp{flex:1}
  .sw-btn{height:32px;padding:0 14px;border:0;border-radius:7px;background:#087c98;color:#fff!important;font-weight:800}.sw-btn2{height:32px;padding:0 12px;border:1px solid #c9d8de;border-radius:7px;background:#fff;font-weight:700}
  .sw-link{border:0;background:none;color:#087c98!important;font-weight:700;padding:0 4px}.sw-danger{color:#a5372c!important}
  .sw-path{display:flex;gap:6px}#sw-overlay .sw-path input{flex:1;min-width:0;height:32px;border:1px solid #cdd9de;border-radius:7px;padding:0 9px;font-family:Consolas,monospace}
  .sw-note{color:#5d737d;font-size:11px}.sw-mono{font-family:Consolas,monospace;font-size:12px}
  .sw-card{background:#fff;border:1px solid #d7e0e5;border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:8px}
  .sw-h{display:flex;align-items:center;gap:8px}.sw-h b{font-size:14px}
  .sw-dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;margin:0}.sw-dl dt{color:#647581;font-size:12px}.sw-dl dd{margin:0;font-weight:700}
  .sw-checks{display:grid;gap:4px}.sw-checks>div{display:grid;grid-template-columns:44px 210px minmax(0,1fr);align-items:center;gap:8px;padding:6px 8px;border:1px solid #e6edf0;border-radius:7px}.sw-checks small{color:#4d6670;font-family:Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .sw-tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.sw-tiles>div{display:grid;gap:3px;padding:8px 10px;border:1px solid #e6edf0;border-radius:8px;min-width:0}.sw-tiles small{color:#4d6670;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sw-tiles .sw-st{justify-self:start}
  .sw-apiline{display:flex;flex-wrap:wrap;gap:6px 14px}
  .sw-more summary,.sw-fix summary{cursor:pointer;color:#087c98;font-weight:700;font-size:12px}.sw-fix summary{display:flex;gap:10px;align-items:baseline;color:#17384e}.sw-fix summary span{color:#647581;font-weight:400}
  .sw-list{display:flex;flex-direction:column}
  .sw-f2{display:grid;grid-template-columns:minmax(220px,38%) minmax(0,1fr);gap:20px;padding:13px 0;border-top:1px solid #eef3f5}.sw-f2:first-child{border-top:0}.sw-f2.sel{background:#f4fafb;margin:0 -12px;padding:13px 12px;border-radius:8px}
  .sw-l{display:flex;flex-direction:column;align-items:flex-start;gap:4px}.sw-l b{font-size:13.5px}.sw-l small{color:#647581;font-size:11.5px;line-height:1.55}.sw-c{display:flex;flex-direction:column;align-items:flex-start;gap:8px;min-width:0}
  .sw-f3{display:grid;grid-template-columns:240px minmax(300px,1fr) minmax(260px,1fr);gap:24px;align-items:start;padding:14px 0;border-top:1px solid #eef3f5}.sw-f3:first-child{border-top:0}.sw-d{display:flex;flex-direction:column;align-items:flex-start;gap:5px;padding-left:16px;border-left:2px solid #eef3f5}.sw-d small{color:#4d6670;font-size:12px;line-height:1.6}
  .sw-adv{display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f7fafb;border:1px solid #e6edf0;border-radius:8px}.sw-adv b{color:#087c98}.sw-adv span{color:#647581;font-size:12px}
  .sw-cols2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;align-items:start}
  .sw-grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:stretch}.sw-fc .sw-dd{color:#647581;font-size:11.5px;line-height:1.55}.sw-grid2.plain{gap:0 32px}.sw-grid2.plain .sw-f2{grid-template-columns:1fr;gap:8px}
  .sw-center{max-width:1100px;width:100%;margin:0 auto}
  .sw-tabs{display:flex;gap:4px;padding:5px;background:#fff;border:1px solid #d7e0e5;border-radius:10px}.sw-tabs button{padding:8px 14px;border:0;border-radius:7px;background:transparent;font-weight:700}.sw-tabs button.on{background:#e8f4f6;box-shadow:inset 0 -3px 0 #0d8191}
  .sw-dash{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-content:start}.sw-dp{padding:14px 16px}.sw-dp.focus{border-color:#7fc0cc;box-shadow:0 0 0 3px #e2f2f5}.sw-dp .sw-ph h3{font-size:15px}
  .sw-mini{display:grid;gap:10px}.sw-mini>div{display:grid;grid-template-columns:200px minmax(0,1fr);align-items:center;gap:12px}.sw-mini b{font-size:12.5px}.sw-mini .sw-seg small{display:none}
  .sw-insp{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:12px;align-items:start}.sw-help{position:sticky;top:0}.sw-help>small{color:#647581;font-weight:700}.sw-help>b{font-size:16px}.sw-help p{margin:0;color:#33505c;line-height:1.7}
  .sw-exc{display:flex;align-items:center;gap:12px;padding:12px 14px;background:#f1f9f5;border:1px solid #cfe8dc;border-radius:9px}.sw-exc span{color:#4d6670}

  .sw-banner{display:flex;align-items:center;gap:12px;padding:9px 12px;background:#f1f9f5;border:1px solid #cfe8dc;border-radius:9px}.sw-banner span{color:#4d6670;font-size:12px}
  .sw-eff{color:#0b6f7f!important;font-weight:700}
  .sw-tbl3{display:grid;border:1px solid #e1e9ec;border-radius:9px;overflow:hidden}.sw-tr{display:grid;grid-template-columns:240px minmax(300px,1fr) minmax(260px,1fr);gap:24px;align-items:start;padding:12px 14px;border-top:1px solid #eef3f5}.sw-tr:first-child{border-top:0}.sw-tr:nth-child(even){background:#fafcfc}.sw-tr>b{font-size:13.5px}
  .sw-sub{font-size:12px;font-weight:800;color:#647581;letter-spacing:.05em;padding-top:6px;border-top:1px solid #e6edf0}
  .sw-tbl{width:100%;border-collapse:collapse}.sw-tbl th,.sw-tbl td{padding:10px 12px;border-bottom:1px solid #eef3f5;text-align:left}.sw-tbl th{width:280px;font-weight:700}.sw-tbl td:nth-child(3){width:120px}.sw-tbl td:last-child{width:80px;text-align:right}
 `;
 function style() { let s = document.getElementById('sw-style'); if (!s) { s = document.createElement('style'); s.id = 'sw-style'; document.head.appendChild(s) } s.textContent = CSS }
 window.SW = {
  V,
  show(k, v = 1) {
   style(); const r = document.querySelector('#paths .settings-shell').getBoundingClientRect();
   let host = document.getElementById('sw-overlay'); if (!host) { host = document.createElement('div'); host.id = 'sw-overlay'; document.body.appendChild(host) }
   Object.assign(host.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: (innerHeight - r.top - 60) + 'px' }); host.innerHTML = V[k].html(v);
  },
 };
})();
