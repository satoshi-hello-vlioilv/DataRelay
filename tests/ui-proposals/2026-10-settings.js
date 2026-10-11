// 2.1.2 共通設定をゼロから作り直す案（CLAUDE.md §3）。DDE と使っていない設定を外したあとの「残す設定」だけで作る。
// 本物の画面の #paths .settings-shell を、案ごとの組み立てで置き換えて再現する（部品と中身は全案で共通）。
// アプリの CSS（section を隠す・nav の形・main の格子の位置・#paths の文字の大きさ）を受けないよう、設定欄と同じ位置に重ねた箱（body の直下）へ描く。
// 撮り方: 撮影用の仕掛けで window.SX.show(k, view)。view 1 = 開いた直後、view 2 = 「動かし方」を見ているところ。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 // ---- 中身（全案で同じ） ----
 const st = (k, t) => `<span class="sx-st sx-${k}">${t}</span>`;
 const path = (v, s, note) => `<div class="sx-path"><input value="${E(v)}" spellcheck="false"><button class="sx-btn2">参照</button></div>${note ? `<small class="sx-note">${s ? st(s[0], s[1]) + ' ' : ''}${note}</small>` : ''}`;
 const num = (v, u, w = 90) => `<span class="sx-num"><input value="${E(v)}" style="width:${w}px"><em>${u}</em></span>`;
 const tog = (on, t) => `<label class="sx-tog"><input type="checkbox" ${on ? 'checked' : ''}><i></i><span>${t}</span></label>`;
 const seg = (opts, cur) => `<div class="sx-seg">${opts.map(([v, b, s]) => `<label class="${v === cur ? 'on' : ''}"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</label>`).join('')}</div>`;
 const field = (label, ctrl, hint, rec) => `<div class="sx-f"><div class="sx-fl"><b>${label}</b>${rec ? `<i class="sx-rec">${rec}</i>` : ''}${hint ? `<small>${hint}</small>` : ''}</div><div class="sx-fc">${ctrl}</div></div>`;
 const G = {
  conn: { t: '接続', s: 'Navigator へつなぐ情報と、API の状態', badge: ['ok', '使えます'], body: () =>
   field('Navigator の接続情報', `<div class="sx-row">${st('ok', '登録済み')}<span class="sx-mono">サーバー navsv01 · 利用者ID harada</span><button class="sx-btn2">変える</button><button class="sx-link">このPCから消す</button></div>`, 'このPCの資格情報マネージャーに保存しています') +
   field('Navigator API', `<div class="sx-row">${st('ok', '使えます')}<span class="sx-mono">C:\\NAVIAP\\dllVC14x64\\SymNaviA.dll · 64bit</span><button class="sx-btn2">もう一度確かめる</button></div>`, '') +
   `<details class="sx-more"><summary>DLL が見つからないとき（探す範囲・手で指定）</summary></details>` },
  place: { t: '場所', s: 'RNE・出力先・控えなどの置き場', badge: ['ok', '5か所OK'], body: () =>
   field('既定の出力先', path('\\\\nlmsrvngy03\\Read\\【New】実績', ['ok', 'OK'], '出力先を持たない対象（3件）がここへ出します'), '') +
   field('RNE の置き場', path('.\\rne', ['ok', 'OK'], 'ファイル名だけの RNE（3件）がここを基準にします'), '') +
   field('控えの置き場', path('<PC>\\backup', ['ok', 'OK'], '差し替える前のファイルをここへ控えます（PCごと）'), '') +
   field('固定長テキストの置き場', path('\\\\nlmfanago02d\\QPMS', ['off', '使っていません'], 'すべて個別のパスで登録されています'), '') +
   field('ACCDB の雛形', path('.\\assets\\empty.accdb', ['off', '使っていません'], 'ACCDB で出す対象がありません'), '') },
  run: { t: '動かし方', s: '同時に動かす数・取り方・失敗したとき', badge: ['n', '6ライン'], body: () =>
   field('同時実行ライン', num(6, 'ライン', 70) + `<small class="sx-scale">1 直列 · 2〜5 軽め · <b>6 推奨</b> · 7〜24 環境しだい</small>`, 'いくつの対象を同時に取るか', '推奨 6') +
   field('値ごとに分けて出すときの既定の取り方', seg([['combined', 'まとめて1回', '問い合わせ1回 · 受け取ってから分ける'], ['parallel', '値ごとに並列', '値ごとに同時に問い合わせ']], 'combined'), '対象ごとに変えられます', '推奨 まとめて1回') +
   field('失敗したときの取り直し', tog(true, '自動実行が失敗したら取り直す') + `<div class="sx-row sx-sub">${num(5, '分後', 60)}${num(1, '回まで', 50)}</div>`, '手動の実行は取り直しません', '推奨 5分後·1回') +
   field('自動実行の取りこぼし', num(30, '分以内なら遅れて実行', 60), 'PCが止まっていて予定の時刻を過ぎたとき', '推奨 30分') +
   `<details class="sx-more"><summary>詳しい調整（ライン起動の間隔・手元の処理のライン・結合の待ち合わせ・ログ）</summary></details>` },
  safe: { t: '守り', s: '0件のとき・差し替える前の控え', badge: ['ok', '3世代'], body: () =>
   field('0件なら公開しない', tog(true, '取れた行が0件なら、いまのファイルを残す'), '', '推奨 入') +
   field('差し替える前の控え', tog(true, '控えを取る') + `<div class="sx-row sx-sub">${seg([['g', '世代で残す'], ['d', '日数で残す']], 'g')}${num(3, '世代', 50)}</div>`, '控えの置き場は「場所」', '推奨 3世代') },
 };
 const ADMIN = [['bundle', '登録内容の持ち出し', 'ZIPで書き出し・取り込み'], ['release', '配布と更新', '配る版・新しいPCへの配り方'], ['docs', '仕様書', 'Navigator API の原典'], ['version', 'バージョン情報', '更新履歴']];
 const ORDER = ['conn', 'place', 'run', 'safe'];
 const ICON = { conn: '接', place: '場', run: '動', safe: '守', bundle: '出', release: '配', docs: '仕', version: '版' };
 const card = (k, open = true) => `<article class="sx-card" id="sx-${k}"><header><h3>${G[k].t}</h3><span>${G[k].s}</span>${st(G[k].badge[0], G[k].badge[1])}</header>${open ? `<div class="sx-body">${G[k].body()}</div>` : ''}</article>`;
 const nav = (cur, withAdmin = true, extra = '') => `<div class="sx-nav">${extra}${ORDER.map(k => `<button class="${k === cur ? 'on' : ''}"><i>${ICON[k]}</i><span><b>${G[k].t}</b><small>${G[k].s}</small></span>${st(G[k].badge[0], G[k].badge[1])}</button>`).join('')}${withAdmin ? `<em>管理</em>${ADMIN.map(([k, t, s]) => `<button><i>${ICON[k]}</i><span><b>${t}</b><small>${s}</small></span></button>`).join('')}` : ''}</div>`;
 const V = {
  A: { name: 'A 左に4つの区分（接続・場所・動かし方・守り）＋管理。区分は1画面に収まる短い一枚', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : 'conn')}<div class="sx-main">${card(v === 2 ? 'run' : 'conn')}</div></div>` },
  B: { name: 'B 1ページに全部を縦に並べ、左の目次で飛ぶ（今いる区分が光る）', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : 'conn', true)}<div class="sx-main sx-scroll" data-to="${v === 2 ? 'sx-run' : ''}">${ORDER.map(k => card(k)).join('')}</div></div>` },
  C: { name: 'C 先頭に「状態のまとめ」（区分ごとに OK・要対応と今の値）。押すと区分へ', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : '', true, `<button class="${v === 2 ? '' : 'on'}"><i>概</i><span><b>まとめ</b><small>いまの状態</small></span></button>`)}<div class="sx-main">${v === 2 ? card('run') : `<article class="sx-card"><header><h3>いまの共通設定</h3><span>直すところはありません</span></header><div class="sx-sum">${ORDER.map(k => `<button class="sx-sumc">${st(G[k].badge[0], G[k].badge[1])}<b>${G[k].t}</b><small>${{ conn: '接続情報 登録済み · API 使えます', place: '出力先・RNE・控え OK · 2か所は使っていません', run: '6ライン · まとめて1回 · 取り直し 5分後1回', safe: '0件なら公開しない · 控え 3世代' }[k]}</small></button>`).join('')}</div></article>`}</div></div>` },
  D: { name: 'D 2列: 左「ふだん変える」（出力先・同時実行ライン・控え・取り直し）、右「たまに見る」（接続・場所の残り・詳しい調整）', html: v => `<div class="sx-shell sx-nonav"><div class="sx-main sx-two"><article class="sx-card"><header><h3>ふだん変える</h3></header><div class="sx-body">${field('既定の出力先', path('\\\\nlmsrvngy03\\Read\\【New】実績', ['ok', 'OK'], ''), '')}${field('同時実行ライン', num(6, 'ライン', 70), '', '推奨 6')}${field('値ごとの既定の取り方', seg([['combined', 'まとめて1回'], ['parallel', '値ごとに並列']], 'combined'), '')}${field('差し替える前の控え', tog(true, '控えを取る') + `<div class="sx-row sx-sub">${num(3, '世代', 50)}</div>`, '')}${field('失敗したときの取り直し', tog(true, '取り直す') + `<div class="sx-row sx-sub">${num(5, '分後', 60)}${num(1, '回', 50)}</div>`, '')}</div></article><article class="sx-card sx-quiet"><header><h3>たまに見る</h3></header><div class="sx-body">${field('接続', `<div class="sx-row">${st('ok', '登録済み')}${st('ok', 'API 使えます')}<button class="sx-link">開く</button></div>`, '')}${field('RNE・控え・テキスト・ACCDB の置き場', `<div class="sx-row">${st('ok', '2か所OK')}${st('off', '2か所は使っていません')}<button class="sx-link">開く</button></div>`, '')}${field('0件なら公開しない', tog(true, '入'), '')}${field('自動実行の取りこぼし', num(30, '分以内', 60), '')}<details class="sx-more"><summary>詳しい調整</summary></details></div></article><div class="sx-adminrow">${ADMIN.map(([k, t]) => `<button>${t}</button>`).join('')}</div></div></div>` },
  E: { name: 'E 上にタブ（接続｜場所｜動かし方｜守り｜管理）、本文は横いっぱいの2列', html: v => `<div class="sx-shell sx-nonav"><div class="sx-main"><div class="sx-tabs">${ORDER.map(k => `<button class="${k === (v === 2 ? 'run' : 'conn') ? 'on' : ''}">${G[k].t}${st(G[k].badge[0], G[k].badge[1])}</button>`).join('')}<button>管理</button></div><div class="sx-grid2">${card(v === 2 ? 'run' : 'conn')}</div></div></div>` },
  F: { name: 'F （方向違い）推奨のままの項目は1行に畳み、推奨と違う・要対応の項目だけ開いて出す', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : 'conn')}<div class="sx-main"><article class="sx-card"><header><h3>${G[v === 2 ? 'run' : 'conn'].t}</h3><span>推奨と違う項目だけ開いています</span><button class="sx-btn2">推奨に戻す</button></header><div class="sx-body">${v === 2 ? `<div class="sx-fold">${st('ok', '推奨')}<b>同時実行ライン</b><span>6ライン</span><button class="sx-link">変える</button></div><div class="sx-fold">${st('ok', '推奨')}<b>値ごとの既定の取り方</b><span>まとめて1回</span><button class="sx-link">変える</button></div>${field('失敗したときの取り直し', tog(true, '自動実行が失敗したら取り直す') + `<div class="sx-row sx-sub">${num(10, '分後', 60)}${num(2, '回まで', 50)}</div>`, '推奨は 5分後・1回', '推奨と違う')}<div class="sx-fold">${st('ok', '推奨')}<b>自動実行の取りこぼし</b><span>30分以内なら遅れて実行</span><button class="sx-link">変える</button></div><div class="sx-fold">${st('ok', '推奨')}<b>詳しい調整</b><span>すべて推奨のまま</span><button class="sx-link">開く</button></div>` : `<div class="sx-fold">${st('ok', 'OK')}<b>Navigator の接続情報</b><span>登録済み · navsv01 · harada</span><button class="sx-link">変える</button></div><div class="sx-fold">${st('ok', 'OK')}<b>Navigator API</b><span>使えます · 64bit</span><button class="sx-link">詳しく</button></div>`}</div></article></div></div>` },
  G: { name: 'G （方向違い）「何をしますか」から入る（したいことを選ぶと、その設定だけ出す）', html: v => `<div class="sx-shell sx-nonav"><div class="sx-main">${v === 2 ? `<div class="sx-crumb"><button class="sx-link">‹ したいことを選び直す</button><b>同時に動かす数・取り方を変える</b></div><article class="sx-card"><div class="sx-body">${field('同時実行ライン', num(6, 'ライン', 70), 'いくつの対象を同時に取るか', '推奨 6')}${field('値ごとに分けて出すときの既定の取り方', seg([['combined', 'まとめて1回', '問い合わせ1回'], ['parallel', '値ごとに並列', '値ごとに同時']], 'combined'), '')}</div></article>` : `<article class="sx-card"><header><h3>何をしますか</h3><span>選ぶと、その設定だけを出します</span></header><div class="sx-tasks">${[['出力先を変える', '既定の出力先'], ['同時に動かす数・取り方を変える', '同時実行ライン · 値ごとの取り方'], ['控えの取り方を変える', '0件のとき · 控えの世代'], ['失敗したときの動きを変える', '取り直し · 取りこぼし'], ['接続を直す・確かめる', '接続情報 · Navigator API'], ['置き場を変える', 'RNE · 控え · テキスト · ACCDB'], ['登録内容を持ち出す・配る', '持ち出し · 配布と更新']].map(([t, s]) => `<button class="sx-task"><b>${t}</b><small>${s}</small></button>`).join('')}</div></article>`}</div></div>` },
  // 2回目の組合せ案（1回目の上位 C・A・F のエッセンス）
  H: { name: 'H C のまとめ＋A の区分＋F の「推奨と違う」印（まとめにも推奨と違う項目を出す）', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : '', true, `<button class="${v === 2 ? '' : 'on'}"><i>概</i><span><b>まとめ</b><small>いまの状態</small></span>${st('w', '推奨と違う 1')}</button>`)}<div class="sx-main">${v === 2 ? runDev() : `<article class="sx-card"><header><h3>いまの共通設定</h3><span>直すところはありません · 推奨と違う項目が1つあります</span></header><div class="sx-sum">${ORDER.map(k => `<button class="sx-sumc">${st(k === 'run' ? 'w' : G[k].badge[0], k === 'run' ? '推奨と違う 1' : G[k].badge[1])}<b>${G[k].t}</b><small>${SUM[k]}</small></button>`).join('')}</div></article>`}</div></div>` },
  I: { name: 'I A の区分の見出しに今の値の要約（C を左の欄へ）＋F の印。まとめの画面は持たない', html: v => `<div class="sx-shell sx-wide">${navSum(v === 2 ? 'run' : 'conn')}<div class="sx-main">${v === 2 ? runDev() : card('conn')}</div></div>` },
  J: { name: 'J C のまとめに、よく変える値をその場で変えられる欄を置く（同時実行ライン・出力先・控え）', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : '', true, `<button class="${v === 2 ? '' : 'on'}"><i>概</i><span><b>まとめ</b><small>いまの状態</small></span></button>`)}<div class="sx-main">${v === 2 ? card('run') : `<article class="sx-card"><header><h3>いまの共通設定</h3><span>直すところはありません</span></header><div class="sx-sum">${ORDER.map(k => `<div class="sx-sumc">${st(G[k].badge[0], G[k].badge[1])}<b>${G[k].t}</b><small>${SUM[k]}</small>${QUICK[k] || ''}</div>`).join('')}</div></article>`}</div></div>` },
  K: { name: 'K A の区分で全部を開いたまま、推奨の印と「推奨と違う」（黄）を項目ごとに。区分ごとに「推奨に戻す」', html: v => `<div class="sx-shell">${nav(v === 2 ? 'run' : 'conn')}<div class="sx-main">${v === 2 ? runDev(true) : card('conn')}</div></div>` },
 };
 const SUM = { conn: '接続情報 登録済み · API 使えます', place: '出力先・RNE・控え OK · 2か所は使っていません', run: '6ライン · まとめて1回 · 取り直し 10分後2回（推奨は5分後1回）', safe: '0件なら公開しない · 控え 3世代' };
 const QUICK = { place: `<div class="sx-q">${path('\\\\nlmsrvngy03\\Read\\【New】実績')}</div>`, run: `<div class="sx-q">${num(6, 'ライン', 60)}</div>`, safe: `<div class="sx-q">${num(3, '世代', 50)}</div>` };
 function runDev(withReset) {
  return `<article class="sx-card"><header><h3>動かし方</h3><span>同時に動かす数・取り方・失敗したとき</span>${withReset ? '<button class="sx-btn2">この区分を推奨に戻す</button>' : ''}</header><div class="sx-body">` +
   field('同時実行ライン', num(6, 'ライン', 70) + `<small class="sx-scale">1 直列 · 2〜5 軽め · <b>6 推奨</b> · 7〜24 環境しだい</small>`, 'いくつの対象を同時に取るか', '推奨 6') +
   field('値ごとに分けて出すときの既定の取り方', seg([['combined', 'まとめて1回', '問い合わせ1回 · 受け取ってから分ける'], ['parallel', '値ごとに並列', '値ごとに同時に問い合わせ']], 'combined'), '対象ごとに変えられます', '推奨 まとめて1回') +
   `<div class="sx-dev">` + field('失敗したときの取り直し', tog(true, '自動実行が失敗したら取り直す') + `<div class="sx-row sx-sub">${num(10, '分後', 60)}${num(2, '回まで', 50)}<button class="sx-link">推奨（5分後・1回）に戻す</button></div>`, '手動の実行は取り直しません', '推奨と違う') + `</div>` +
   field('自動実行の取りこぼし', num(30, '分以内なら遅れて実行', 60), 'PCが止まっていて予定の時刻を過ぎたとき', '推奨 30分') +
   `<details class="sx-more"><summary>詳しい調整（ライン起動の間隔・手元の処理のライン・結合の待ち合わせ・ログ） · すべて推奨のまま</summary></details></div></article>`;
 }
 const navSum = (cur) => `<div class="sx-nav sx-navsum">${ORDER.map(k => `<button class="${k === cur ? 'on' : ''}"><i>${ICON[k]}</i><span><b>${G[k].t}</b><small>${SUM[k]}</small></span>${k === 'run' ? st('w', '推奨と違う') : st(G[k].badge[0], G[k].badge[1])}</button>`).join('')}<em>管理</em>${ADMIN.map(([k, t, s]) => `<button><i>${ICON[k]}</i><span><b>${t}</b><small>${s}</small></span></button>`).join('')}</div>`;
 const CSS = `
  #sx-overlay{position:fixed;z-index:50;background:#f3f6f8;font-family:"Yu Gothic UI",Meiryo,sans-serif}
  #sx-overlay button{font:inherit}
  .sx-shell{display:grid;grid-template-columns:250px minmax(0,1fr);gap:14px;height:100%;min-height:0;font-size:13px;color:#17232d}
  .sx-shell.sx-nonav{grid-template-columns:minmax(0,1fr)}
  .sx-nav{display:flex;flex-direction:column;gap:4px;padding:8px;background:#fff;border:1px solid #d7e0e5;border-radius:12px;align-self:start}
  .sx-nav button{display:grid;grid-template-columns:30px minmax(0,1fr) auto;align-items:center;gap:9px;padding:9px 10px;border:1px solid transparent;border-radius:9px;background:transparent;color:#17232d;text-align:left;cursor:pointer}
  .sx-nav button.on{background:#e8f4f6;border-color:#bfe0e6}.sx-nav button i{font-style:normal;display:grid;place-items:center;width:28px;height:28px;border-radius:8px;background:#eef3f5;color:#087c98;font-weight:800;font-size:12px}
  .sx-nav button b{display:block;font-size:13px}.sx-nav button small{display:block;font-size:10.5px;color:#647581;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sx-nav em{font-style:normal;font-size:10.5px;color:#7b8c93;font-weight:800;padding:10px 10px 2px;letter-spacing:.06em}
  .sx-main{min-width:0;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:12px}
  .sx-card{background:#fff;border:1px solid #d7e0e5;border-radius:12px;box-shadow:0 2px 8px rgba(23,56,78,.05)}
  .sx-card>header{display:flex;align-items:baseline;gap:10px;padding:13px 18px;border-bottom:1px solid #e6edf0}.sx-card>header h3{margin:0;font-size:16px}.sx-card>header>span:not(.sx-st){color:#647581;font-size:12px;flex:1}
  .sx-body{padding:4px 18px 10px}
  .sx-f{display:grid;grid-template-columns:minmax(180px,30%) minmax(0,1fr);gap:16px;padding:13px 0;border-bottom:1px solid #eef3f5}.sx-f:last-child{border-bottom:0}
  .sx-fl b{display:block;font-size:13px}.sx-fl small{display:block;color:#647581;font-size:11px;margin-top:2px}.sx-rec{display:inline-block;font-style:normal;font-size:10.5px;color:#0b6f7f;background:#e6f4f6;border-radius:9px;padding:0 7px;margin-top:4px}
  .sx-fc{min-width:0;display:grid;gap:6px;align-content:start}
  .sx-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.sx-sub{margin-left:2px}
  .sx-mono{font-family:Consolas,monospace;font-size:12px;color:#344b56}
  .sx-path{display:flex;gap:6px}.sx-path input{flex:1;min-width:0;height:32px;border:1px solid #cdd9de;border-radius:7px;padding:0 9px;font:12.5px Consolas,monospace}
  .sx-note{color:#5d737d;font-size:11px}
  .sx-num{display:inline-flex;align-items:center;gap:5px}.sx-num input{height:32px;border:1px solid #cdd9de;border-radius:7px;padding:0 8px;font-size:14px;text-align:right}.sx-num em{font-style:normal;color:#4d6670;font-size:12px}
  .sx-scale{color:#647581;font-size:11px}.sx-scale b{color:#0b6f7f}
  .sx-tog{display:inline-flex;align-items:center;gap:8px;cursor:pointer}.sx-tog input{display:none}.sx-tog i{width:34px;height:19px;border-radius:10px;background:#c5d2d7;position:relative}.sx-tog i::after{content:'';position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;background:#fff;transition:.15s}.sx-tog input:checked+i{background:#149aa5}.sx-tog input:checked+i::after{left:17px}
  .sx-seg{display:inline-grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);border:1px solid #c9d8de;border-radius:9px;overflow:hidden;max-width:560px}.sx-seg label{display:grid;gap:1px;padding:6px 12px;border-left:1px solid #dbe5e9;background:#fff;cursor:pointer}.sx-seg label:first-child{border-left:0}.sx-seg label.on{background:#e3f3f5;box-shadow:inset 0 -2px 0 #149aa5}.sx-seg b{font-size:12.5px}.sx-seg small{font-size:10.5px;color:#60757c}
  .sx-st{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:10px;white-space:nowrap}.sx-ok{background:#e1f3ea;color:#0a6a4a}.sx-w{background:#fbefd7;color:#8a5a00}.sx-off{background:#eef2f4;color:#6d8088}.sx-ng{background:#fde5e1;color:#a5372c}.sx-n{background:#e6f1f4;color:#215f6f}
  .sx-btn2{height:30px;padding:0 12px;border:1px solid #c9d8de;border-radius:7px;background:#fff;color:#17384e;font-weight:700;font-size:12px;cursor:pointer}.sx-link{border:0;background:none;color:#087c98;font-weight:700;font-size:12px;cursor:pointer;padding:0 4px}
  .sx-more{margin:6px 0 4px}.sx-more summary{cursor:pointer;color:#087c98;font-weight:700;font-size:12px}
  .sx-sum{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:14px 18px}.sx-sumc{display:grid;gap:4px;text-align:left;padding:14px;border:1px solid #d7e0e5;border-radius:10px;background:#fbfdfd;cursor:pointer;color:#17232d}.sx-sumc b{font-size:15px}.sx-sumc small{color:#4d6670;font-size:12px}.sx-sumc .sx-st{justify-self:start}
  .sx-two{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:14px;align-content:start}.sx-two .sx-f{grid-template-columns:minmax(140px,36%) minmax(0,1fr)}.sx-quiet{background:#fafcfc}.sx-adminrow{grid-column:1 / -1;display:flex;gap:8px}.sx-adminrow button{border:1px solid #d7e0e5;background:#fff;color:#17384e;border-radius:8px;padding:7px 12px;font-weight:700;font-size:12px}
  .sx-tabs{display:flex;gap:6px;padding:5px;background:#eef3f5;border:1px solid #d7e0e5;border-radius:10px}.sx-tabs button{display:flex;align-items:center;gap:8px;padding:8px 16px;border:0;border-radius:7px;background:transparent;color:#4a6270;font-weight:700;font-size:13px}.sx-tabs button.on{background:#fff;color:#0b5f73;box-shadow:0 1px 4px rgba(23,56,78,.1)}
  .sx-grid2 .sx-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:28px}.sx-grid2 .sx-f{grid-template-columns:1fr;gap:6px}
  .sx-fold{display:grid;grid-template-columns:auto 220px minmax(0,1fr) auto;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid #eef3f5}.sx-fold b{font-size:13px}.sx-fold span{color:#4d6670;font-size:12.5px}
  .sx-tasks{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;padding:14px 18px}.sx-task{display:grid;gap:4px;text-align:left;padding:16px;border:1px solid #d7e0e5;border-radius:10px;background:#fff;cursor:pointer;color:#17232d}.sx-task b{font-size:14px}.sx-task small{color:#647581;font-size:11.5px}
  .sx-dev{margin:0 -18px;padding:0 18px;background:#fffaf0;box-shadow:inset 3px 0 0 #d9a33a}.sx-dev .sx-rec{background:#fbefd7;color:#8a5a00}
  .sx-wide{grid-template-columns:330px minmax(0,1fr)}.sx-navsum button small{white-space:normal;line-height:1.4}
  .sx-q{margin-top:6px}.sx-sumc .sx-path input{height:28px}
  .sx-crumb{display:flex;align-items:center;gap:12px}.sx-crumb b{font-size:15px}
 `;
 function style() { let s = document.getElementById('sx-style'); if (!s) { s = document.createElement('style'); s.id = 'sx-style'; document.head.appendChild(s) } s.textContent = CSS }
 window.SX = {
  V, G,
  show(k, v = 1) {
   style(); const r = document.querySelector('#paths .settings-shell').getBoundingClientRect();
   let host = document.getElementById('sx-overlay'); if (!host) { host = document.createElement('div'); host.id = 'sx-overlay'; document.body.appendChild(host) }
   Object.assign(host.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' }); host.innerHTML = V[k].html(v);
   const sc = host.querySelector('.sx-scroll[data-to]'); if (sc && sc.dataset.to) { const t = document.getElementById(sc.dataset.to); if (t) sc.scrollTop = t.offsetTop - sc.offsetTop - 4 }
  },
 };
})();
