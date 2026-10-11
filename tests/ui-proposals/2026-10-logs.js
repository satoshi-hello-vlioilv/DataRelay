// 2.1.3 ログ・診断のタブの案（CLAUDE.md §3）。
// いま: アプリ監視（8つの札）と事前診断が上半分を固定で占め、1536 では実行ログの1行目が画面の下端。
// 実行ログの上にも、選ぶ・写す・消すのボタンが15個並ぶ。
// 本物の画面の #logs と同じ位置（タブの下から下の帯の上まで）に重ねた箱（body の直下）へ描く。中身は全案で共通の作り物。
// 撮り方: window.LG.show(k, view)。view 1 = 開いた直後（最新の実行が見えている）、view 2 = 失敗した実行（06:00 の自動実行）を見ているところ。
// 1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 // ---- 中身（作り物の実行の記録） ----
 const RUNS = [
  { n: 6, at: '10/11 07:40', trig: '手動', what: '設備単位実績（値ごと 7値）', jobs: 1, ok: true, sec: 150, rows: '14,293行', err: 0 },
  { n: 5, at: '10/11 06:00', trig: '自動', what: '朝の定時（6件）', jobs: 6, ok: false, sec: 92, rows: '41,820行', err: 1 },
  { n: 4, at: '10/10 18:00', trig: '自動', what: '夕方の定時（6件）', jobs: 6, ok: true, sec: 88, rows: '40,112行', err: 0 },
  { n: 3, at: '10/10 15:22', trig: '設定', what: '設定保存（設備単位実績）', jobs: 0, ok: true, sec: 0, rows: '', err: 0, setting: true },
  { n: 2, at: '10/10 12:00', trig: '自動', what: '昼の定時（6件）', jobs: 6, ok: true, sec: 90, rows: '39,877行', err: 0 },
  { n: 1, at: '10/10 06:00', trig: '自動', what: '朝の定時（6件）', jobs: 6, ok: true, sec: 95, rows: '41,003行', err: 0 },
 ];
 const L = (t, lv, msg) => ({ t, lv, msg });
 const LINES = {
  6: [L('07:40:12,018', 'INFO', '処理開始 trigger=manual jobs=1'), L('07:40:12,044', 'INFO', 'RUN_ENVIRONMENT cpu=8 work_write_mb_s=412.3 rne_scan_ms=31 rne_files=12'),
   L('07:40:12,061', 'INFO', 'VARIANTS_START line=1 job=設備単位実績 method=combined item=BOX実績_設備名 values=LS4,LS3,DL2,TLV,CAL,FS4,KEN'),
   L('07:40:12,402', 'INFO', 'VARIANT_CONDITION line=1 job=設備単位実績 item=BOX実績_設備名 relax=NULL以外 restrict=担当外を1件ずつ外す'),
   L('07:42:31,880', 'INFO', 'VARIANT_SPLIT line=1 job=設備単位実績 rows=14293 found=7 per_value=LS4:769,LS3:1238,DL2:2023,TLV:2197,CAL:1165,FS4:3410,KEN:3491 outside=0'),
   L('07:42:41,950', 'INFO', 'PARALLEL_JOB_RESULT line=1 job=設備単位実績 format=sqlite3 rows=14293 columns=10 elapsed=149.88s'),
   L('07:42:42,002', 'INFO', '正常終了 job=設備単位実績 rows=14293 elapsed=150.0s')],
  5: [L('06:00:00,102', 'INFO', '処理開始 trigger=schedule jobs=6'), L('06:00:00,140', 'INFO', 'RUN_ENVIRONMENT cpu=8 work_write_mb_s=405.1 rne_scan_ms=29 rne_files=12'),
   L('06:00:00,151', 'INFO', 'BATCH_ORDER strategy=heaviest_first order=設備単位実績,仕掛ロット,在庫一覧,出荷予定,受注残,不良集計'),
   L('06:00:00,163', 'INFO', 'PARALLEL_BATCH_START model=process-isolated trigger=schedule batch_id=b0611 jobs=6 max_lines=6'),
   L('06:00:00,870', 'INFO', 'WORKER_START batch_id=b0611 line=3 pid=5124 job=在庫一覧 queue_index=3/6'),
   L('06:00:41,205', 'ERROR', 'PIPELINE job=在庫一覧 phase=api_execute_catalog error=NaviExecuteCatalog が -12 を返しました（条件の項目が見つかりません: 倉庫区分）'),
   L('06:00:41,210', 'INFO', 'WORKER_END batch_id=b0611 line=3 pid=5124 job=在庫一覧 returncode=1 ok=False elapsed=40.34s'),
   L('06:00:41,233', 'WARNING', '異常終了 job=在庫一覧 理由=条件の項目が見つかりません: 倉庫区分（RNE の条件を見直してください）'),
   L('06:01:30,118', 'INFO', 'PARALLEL_JOB_RESULT line=1 job=設備単位実績 format=sqlite3 rows=14102 columns=10 elapsed=89.95s'),
   L('06:01:32,555', 'INFO', 'PARALLEL_BATCH_END model=process-isolated total_jobs=6 succeeded=5 failed=1 max_lines=6 elapsed=92.39s')],
 };
 const JOBS5 = [['設備単位実績', true, '14,102行', '90s'], ['仕掛ロット', true, '8,214行', '31s'], ['在庫一覧', false, '条件の項目が見つかりません: 倉庫区分', '40s'], ['出荷予定', true, '6,021行', '22s'], ['受注残', true, '9,330行', '27s'], ['不良集計', true, '4,153行', '18s']];
 const st = (k, t) => `<span class="lg-st lg-${k}">${t}</span>`;
 const runSt = r => r.setting ? st('off', '設定') : r.ok ? st('ok', '成功') : st('ng', `失敗 ${r.err}`);
 const lv = l => l.lv === 'ERROR' ? 'err' : l.lv === 'WARNING' ? 'warn' : '';
 const lines = (n, o = {}) => `<div class="lg-lines ${o.wrap ? 'wrap' : ''}">${(LINES[n] || LINES[6]).map(l => `<div class="lg-ln ${lv(l)}">${o.check ? '<input type="checkbox">' : ''}<time>${l.t}</time><b>${l.lv === 'INFO' ? '' : l.lv}</b><span>${E(l.msg)}</span></div>`).join('')}</div>`;
 const runList = (sel, o = {}) => `<div class="lg-runs">${o.head === false ? '' : `<div class="lg-runsh"><b>実行の記録</b><small>新しい順</small></div>`}${RUNS.map(r => `<button class="lg-run ${r.n === sel ? 'on' : ''} ${r.ok ? '' : 'bad'}"><span class="lg-rt"><time>${r.at}</time><em>${r.trig}</em></span><b>${E(r.what)}</b><span class="lg-rs">${runSt(r)}${r.sec ? `<small>${r.sec}秒${r.rows ? ' · ' + r.rows : ''}</small>` : ''}</span></button>`).join('')}</div>`;
 const runHead = (n, o = {}) => { const r = RUNS.find(x => x.n === n); return `<div class="lg-dh"><div><b>実行指令 ${r.n}</b><span>${r.at} · ${r.trig} · ${E(r.what)}</span></div>${runSt(r)}<span class="lg-sp"></span>${o.copy !== false ? `<button class="lg-btn">報告用にコピー</button><button class="lg-btn2">全文コピー</button>` : ''}<button class="lg-ib" title="この実行のログを消す">消す</button></div>` };
 const jobsOf = n => n === 5 ? `<div class="lg-jobs">${JOBS5.map(([j, ok, d, s]) => `<span class="${ok ? '' : 'bad'}">${ok ? st('ok', '成功') : st('ng', '失敗')}<b>${j}</b><small>${E(d)} · ${s}</small></span>`).join('')}</div>` : `<div class="lg-jobs"><span>${st('ok', '成功')}<b>設備単位実績</b><small>14,293行（7値） · 150s</small></span></div>`;
 const tools = (o = {}) => `<div class="lg-tools"><input class="lg-q" placeholder="対象名・工程・エラーの言葉で探す"><select><option>すべての種類</option></select><select><option>すべてのレベル</option></select>${o.extra || ''}<span class="lg-sp"></span>${o.right || '<button class="lg-btn2">再読込</button><button class="lg-btn2">その他 ▾</button>'}</div>`;
 const band = (o = {}) => `<div class="lg-band">${st('ok', 'アプリ 正常')}<span>中身 pid 874 · Python 3.12 · 往復 4ms · 起こし直し 0回</span><span class="lg-sep"></span>${st('ok', '事前診断 OK')}<span>10/11 07:39 · 接続・API・RNE の置き場</span><span class="lg-sp"></span><button class="lg-btn2">診断を実行</button>${o.more === false ? '' : '<button class="lg-link">アプリ監視の詳細 ▾</button>'}</div>`;
 const MON = `<div class="lg-card lg-mon"><div class="lg-h"><b>アプリ監視</b>${st('ok', '正常')}</div><dl><dt>中身の pid</dt><dd>874</dd><dt>Python</dt><dd>3.12.6</dd><dt>中身の版</dt><dd>2.1.2</dd><dt>往復時間</dt><dd>4ms</dd><dt>起こし直し</dt><dd>0回</dd><dt>exe の置き場</dt><dd>手元（installed）</dd><dt>最終確認</dt><dd>07:49:58</dd></dl><button class="lg-btn2">今すぐ確認</button></div>`;
 const DIAG = `<div class="lg-card lg-diag"><div class="lg-h"><b>事前診断</b>${st('ok', 'OK')}</div><small>10/11 07:39 · 接続・API・RNE の置き場</small><button class="lg-btn2">診断を実行</button></div>`;

 const errLines = n => `<div class="lg-lines">${(LINES[n] || []).filter(l => l.lv !== 'INFO').map(l => `<div class="lg-ln ${lv(l)}"><time>${l.t}</time><b>${l.lv}</b><span>${E(l.msg)}</span></div>`).join('')}</div>`;
 const REPORT_POP = `<div class="lg-pop"><b>報告用にコピー</b><small>この実行について、次をまとめて写します</small><label><input type="checkbox" checked>要約（結果・時間・対象ごとの結果）</label><label><input type="checkbox" checked>環境（版・PC・API・同時実行ライン）</label><label><input type="checkbox" checked>エラーと注意の行（前後3行も）</label><label><input type="checkbox">この実行のログの全文</label><div class="lg-row"><button class="lg-btn">写す</button><small>約 1.2KB</small></div></div>`;
 const jobsLine = n => `<div class="lg-jline">${(n === 5 ? JOBS5 : [['設備単位実績', true, '14,293行（7値）', '150s']]).map(([j, ok, d]) => `<span class="${ok ? '' : 'bad'}" title="${E(d)}">${ok ? st('ok', '成功') : st('ng', '失敗')} ${j}${ok ? '' : `<small>${E(d)}</small>`}</span>`).join('')}</div>`;
 function runListDays(sel, onlyBad) {
  const days = [['今日 10/11', RUNS.filter(r => r.at.startsWith('10/11'))], ['10/10', RUNS.filter(r => r.at.startsWith('10/10'))]];
  return `<div class="lg-runs"><div class="lg-runsh"><b>実行の記録</b><span class="lg-sp"></span><label class="lg-tg"><input type="checkbox" ${onlyBad ? 'checked' : ''}>失敗だけ</label></div>${days.map(([d, rs]) => { rs = onlyBad ? rs.filter(r => !r.ok && !r.setting) : rs; return rs.length ? `<em class="lg-day">${d}</em>` + rs.map(r => `<button class="lg-run ${r.n === sel ? 'on' : ''} ${r.ok ? '' : 'bad'}"><span class="lg-rt"><time>${r.at.slice(6)}</time><em>${r.trig}</em>${runSt(r)}</span><b>${E(r.what)}</b>${r.sec ? `<small class="lg-rm">${r.sec}秒${r.rows ? ' · ' + r.rows : ''}</small>` : ''}</button>`).join('') : '' }).join('')}</div>`;
 }
 const V = {
  A: { t: '監視と診断を1行の帯に畳み、ログを全面に', html: v => `<div class="lg-col">${band()}<div class="lg-card lg-main">${tools()}<div class="lg-tree">${[6, 5, 4].map(n => `<div class="lg-g ${n === (v === 2 ? 5 : 6) ? 'open' : ''}">${runHead(n, { copy: true })}${n === (v === 2 ? 5 : 6) ? lines(n) : ''}</div>`).join('')}</div></div></div>` },
  B: { t: '2ペイン（左に実行の一覧、右に選んだ実行のログ）', html: v => `<div class="lg-col">${band()}<div class="lg-two">${runList(v === 2 ? 5 : 6)}<div class="lg-card lg-detail">${runHead(v === 2 ? 5 : 6)}${tools({ right: '' })}${lines(v === 2 ? 5 : 6)}</div></div></div>` },
  C: { t: '3列（実行の一覧｜ログ｜監視と診断）', html: v => `<div class="lg-three">${runList(v === 2 ? 5 : 6)}<div class="lg-card lg-detail">${runHead(v === 2 ? 5 : 6)}${tools({ right: '' })}${lines(v === 2 ? 5 : 6, { wrap: true })}</div><div class="lg-side">${MON}${DIAG}</div></div>` },
  D: { t: '小さなタブに分ける（実行ログ｜アプリ監視｜事前診断）', html: v => `<div class="lg-col"><div class="lg-tabs"><button class="on">実行ログ</button><button>アプリ監視 ${st('ok', '正常')}</button><button>事前診断 ${st('ok', 'OK')}</button></div><div class="lg-card lg-main">${tools()}<div class="lg-tree">${[6, 5, 4, 3].map(n => `<div class="lg-g ${n === (v === 2 ? 5 : 6) ? 'open' : ''}">${runHead(n)}${n === (v === 2 ? 5 : 6) ? lines(n) : ''}</div>`).join('')}</div></div></div>` },
  E: { t: '上に実行の時間の並び、下に選んだ実行のログ', html: v => `<div class="lg-col">${band()}<div class="lg-card lg-tl"><div class="lg-axis">${['10/10 06:00', '12:00', '18:00', '10/11 00:00', '06:00', '12:00'].map(x => `<span>${x}</span>`).join('')}</div><div class="lg-bars">${RUNS.filter(r => !r.setting).map((r, i) => `<i class="${r.ok ? '' : 'bad'} ${r.n === (v === 2 ? 5 : 6) ? 'on' : ''}" style="left:${[86, 66, 50, 18, 2][i]}%" title="${r.at}"><b>${r.at.slice(6)}</b></i>`).join('')}<i class="set" style="left:44%"></i></div></div><div class="lg-card lg-detail">${runHead(v === 2 ? 5 : 6)}${tools({ right: '' })}${lines(v === 2 ? 5 : 6)}</div></div>` },
  F: { t: '最新の実行の要約を先に（方向の違う案）', html: v => { const n = v === 2 ? 5 : 6, r = RUNS.find(x => x.n === n); return `<div class="lg-col">${band()}<div class="lg-sum lg-card"><div class="lg-sumh"><div><small>${v === 2 ? '選んだ実行' : '最新の実行'}</small><b>${r.at} · ${r.trig} · ${E(r.what)}</b></div>${runSt(r)}<span class="lg-big">${r.sec}秒</span><span class="lg-big">${r.rows}</span><span class="lg-sp"></span><button class="lg-btn">報告用にコピー</button></div>${jobsOf(n)}${n === 5 ? `<div class="lg-errbox"><b>エラーの行</b>${lines(5).replace(/<div class="lg-ln ">[\s\S]*?<\/div>/g, '')}</div>` : ''}</div><div class="lg-card lg-older"><div class="lg-h"><b>ほかの実行</b><small>押すと要約が変わります</small><span class="lg-sp"></span><button class="lg-link">全部のログを見る</button></div><div class="lg-chips">${RUNS.map(x => `<button class="${x.n === n ? 'on' : ''} ${x.ok ? '' : 'bad'}">${x.at} ${runSt(x)}</button>`).join('')}</div></div></div>` } },
  G: { t: '目的から入る（方向の違う案）', html: v => `<div class="lg-col">${band({ more: false })}<div class="lg-goals">${[['報', '不具合・改良を伝える', '実行を選ぶと、要約・環境・エラーの行をまとめて写します', v === 2], ['見', '実行の記録を見る', '実行ごとの結果と、ログの全文', v !== 2], ['監', 'アプリの様子', '中身の起こし直し・往復時間・exe の置き場', false], ['診', '事前に診断する', '接続・API・RNE の置き場をまとめて確かめる', false]].map(([i, t, s, on]) => `<button class="${on ? 'on' : ''}"><i>${i}</i><b>${t}</b><small>${s}</small></button>`).join('')}</div>${v === 2 ? `<div class="lg-card lg-report"><b>1. 伝えたい実行を選ぶ</b><div class="lg-chips">${RUNS.slice(0, 4).map(x => `<button class="${x.n === 5 ? 'on' : ''} ${x.ok ? '' : 'bad'}">${x.at} ${runSt(x)}</button>`).join('')}</div><b>2. 写す中身</b><div class="lg-chips"><button class="on">要約</button><button class="on">環境（版・PC・API）</button><button class="on">エラーの行</button><button>全文</button></div><div class="lg-preview">${lines(5)}</div><button class="lg-btn">3. まとめてコピー</button></div>` : `<div class="lg-two">${runList(6)}<div class="lg-card lg-detail">${runHead(6)}${lines(6)}</div></div>`}</div>` },
  // ---- 2回目: 組合せ案（すべて B の2ペインが土台） ----
  H: { t: 'B＋F（選んだ実行の対象ごとの結果とエラーの行を、ログの上に）', html: v => { const n = v === 2 ? 5 : 6; return `<div class="lg-col">${band()}<div class="lg-two">${runList(n)}<div class="lg-card lg-detail">${runHead(n)}<div class="lg-pad">${jobsOf(n)}${n === 5 ? `<div class="lg-errbox"><b>エラーの行</b>${errLines(5)}</div>` : ''}</div>${tools({ right: '' })}${lines(n)}</div></div></div>` } },
  I: { t: 'B＋G（報告用に写す中身を選べる小窓）', html: v => { const n = v === 2 ? 5 : 6; return `<div class="lg-col">${band()}<div class="lg-two">${runList(n)}<div class="lg-card lg-detail" style="position:relative">${runHead(n)}${tools({ right: '' })}${lines(n)}${v === 2 ? REPORT_POP : ''}</div></div></div>` } },
  J: { t: 'B＋E（一覧を日ごとに区切り、失敗だけに絞れる。ログはエラーへ移れる）', html: v => { const n = v === 2 ? 5 : 6; return `<div class="lg-col">${band()}<div class="lg-two">${runListDays(n, v === 2)}<div class="lg-card lg-detail">${runHead(n)}${tools({ right: n === 5 ? '<button class="lg-btn2">↓ エラーへ（1）</button>' : '' })}${lines(n)}</div></div></div>` } },
  K: { t: 'B＋F（対象ごとの結果を1行に）＋G（写す中身を選ぶ）＋J（失敗だけ）', html: v => { const n = v === 2 ? 5 : 6; return `<div class="lg-col">${band()}<div class="lg-two">${runListDays(n, false)}<div class="lg-card lg-detail" style="position:relative">${runHead(n)}<div class="lg-pad">${jobsLine(n)}</div>${tools({ right: n === 5 ? '<button class="lg-btn2">↓ エラーへ（1）</button>' : '' })}${lines(n)}${v === 2 ? REPORT_POP : ''}</div></div></div>` } },
 };
 const CSS = `
  #lg-overlay{position:fixed;z-index:50;background:#f3f6f8;font-family:"Yu Gothic UI",Meiryo,sans-serif;font-size:12.5px;color:#17232d;overflow:hidden}
  #lg-overlay *{box-sizing:border-box}#lg-overlay button{font:inherit;cursor:pointer;color:#17384e}#lg-overlay input,#lg-overlay select{font:inherit;width:auto;height:30px;border:1px solid #cdd9de;border-radius:7px;padding:0 8px;background:#fff}
  #lg-overlay input[type=checkbox]{width:14px;height:14px;padding:0}
  .lg-col{height:100%;min-height:0;display:flex;flex-direction:column;gap:8px}
  .lg-card{background:#fff;border:1px solid #d7e0e5;border-radius:10px}
  .lg-st{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:10px;white-space:nowrap}.lg-ok{background:#e1f3ea;color:#0a6a4a}.lg-ng{background:#fde5e1;color:#a5372c}.lg-off{background:#eef2f4;color:#6d8088}.lg-w{background:#fbefd7;color:#8a5a00}
  .lg-band{display:flex;align-items:center;gap:10px;padding:7px 12px;background:#fff;border:1px solid #d7e0e5;border-radius:10px;flex:none}.lg-band>span:not(.lg-st):not(.lg-sp):not(.lg-sep){color:#4d6670;font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.lg-sep{width:1px;height:18px;background:#d7e0e5}
  .lg-sp{flex:1}.lg-btn{height:30px;padding:0 14px;border:0;border-radius:7px;background:#087c98;color:#fff!important;font-weight:800;white-space:nowrap}.lg-btn2{height:30px;padding:0 12px;border:1px solid #c9d8de;border-radius:7px;background:#fff;font-weight:700;white-space:nowrap}.lg-link{border:0;background:none;color:#087c98!important;font-weight:700;white-space:nowrap}
  .lg-ib{height:26px;padding:0 8px;border:1px solid #efcdc7;border-radius:6px;background:#fff;color:#a5372c!important;font-size:11px}
  .lg-main{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}
  .lg-tools{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #e6edf0;flex:none}.lg-q{flex:0 1 420px}
  .lg-tree{flex:1;min-height:0;overflow:auto;padding:8px;display:flex;flex-direction:column;gap:6px}
  .lg-g{border:1px solid #e1e9ec;border-radius:8px;overflow:hidden}.lg-g:not(.open){background:#fafcfc}
  .lg-dh{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid #e6edf0;flex:none}.lg-dh>div{display:grid;gap:1px;min-width:0}.lg-dh>div b{font-size:13.5px}.lg-dh>div span{color:#4d6670;font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lg-lines{background:#0f2430;color:#d7e6ec;font:12px/1.55 Consolas,"MS Gothic",monospace;padding:6px 0;overflow:auto}.lg-lines.wrap .lg-ln span{white-space:normal}
  .lg-ln{display:grid;grid-template-columns:96px 64px minmax(0,1fr);gap:8px;padding:2px 12px;align-items:baseline}.lg-ln:has(input){grid-template-columns:16px 96px 64px minmax(0,1fr)}.lg-ln>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.lg-ln time{color:#7fa3b3}.lg-ln b{font-weight:800}
  .lg-ln.err{background:#4a1f1f;color:#ffd9d4}.lg-ln.err b{color:#ff9b8f}.lg-ln.warn{background:#3f3418;color:#fde9b8}.lg-ln.warn b{color:#f3c55b}
  .lg-two{flex:1;min-height:0;display:grid;grid-template-columns:330px minmax(0,1fr);gap:8px}
  .lg-runs{min-height:0;overflow:auto;background:#fff;border:1px solid #d7e0e5;border-radius:10px;padding:6px;display:flex;flex-direction:column;gap:4px}.lg-runsh{display:flex;align-items:baseline;gap:8px;padding:4px 6px 6px}.lg-runsh b{font-size:13.5px}.lg-runsh small{color:#647581}
  .lg-run{display:grid;gap:2px;text-align:left;padding:8px 10px;border:1px solid #e6edf0;border-radius:8px;background:#fff}.lg-run.on{background:#e8f4f6;border-color:#9fcbd6;box-shadow:inset 3px 0 0 #087c98}.lg-run.bad{border-color:#f0d3ce}.lg-run.bad.on{background:#fdf1ef;box-shadow:inset 3px 0 0 #b93b32}
  .lg-rt{display:flex;gap:8px;align-items:baseline}.lg-rt time{font:12px Consolas,monospace;color:#33505c}.lg-rt em{font-style:normal;font-size:10.5px;color:#647581}.lg-run>b{font-size:12.5px}.lg-rs{display:flex;gap:8px;align-items:center}.lg-rs small{color:#647581;font-size:11px}
  .lg-detail{min-height:0;display:flex;flex-direction:column;overflow:hidden;flex:1}.lg-detail .lg-lines{flex:1;min-height:0}
  .lg-three{height:100%;min-height:0;display:grid;grid-template-columns:300px minmax(0,1fr) 280px;gap:8px}.lg-side{display:flex;flex-direction:column;gap:8px;min-height:0}
  .lg-mon,.lg-diag{padding:10px 12px;display:flex;flex-direction:column;gap:8px}.lg-h{display:flex;align-items:center;gap:8px}.lg-h b{font-size:13.5px}.lg-h small{color:#647581}.lg-mon dl{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:0}.lg-mon dt{color:#647581}.lg-mon dd{margin:0;font-weight:700}.lg-diag small{color:#647581}
  .lg-tabs{display:flex;gap:4px;padding:4px;background:#fff;border:1px solid #d7e0e5;border-radius:10px;flex:none}.lg-tabs button{display:flex;align-items:center;gap:8px;padding:7px 14px;border:0;border-radius:7px;background:transparent;font-weight:700}.lg-tabs button.on{background:#e8f4f6;box-shadow:inset 0 -3px 0 #087c98}
  .lg-tl{flex:none;padding:10px 14px 8px}.lg-axis{display:flex;justify-content:space-between;color:#647581;font-size:11px}.lg-bars{position:relative;height:40px;margin-top:6px;border-top:1px solid #e6edf0}.lg-bars i{position:absolute;top:8px;width:9%;height:22px;border-radius:5px;background:#bfe3d4}.lg-bars i b{position:absolute;top:24px;left:0;font:10px Consolas;color:#647581;font-weight:400}.lg-bars i.bad{background:#f2b9b1}.lg-bars i.on{outline:2px solid #087c98}.lg-bars i.set{width:6px;background:#c9d4d8}
  .lg-sum{flex:none;padding:12px 14px;display:flex;flex-direction:column;gap:10px}.lg-sumh{display:flex;align-items:center;gap:12px}.lg-sumh>div{display:grid}.lg-sumh small{color:#647581}.lg-sumh b{font-size:15px}.lg-big{font-size:18px;font-weight:800;color:#17384e}
  .lg-jobs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.lg-jobs span{display:grid;grid-template-columns:auto 1fr;column-gap:8px;padding:7px 10px;border:1px solid #e6edf0;border-radius:8px}.lg-jobs span small{grid-column:2;color:#647581;font-size:11px}.lg-jobs span.bad{border-color:#f0d3ce;background:#fdf6f5}
  .lg-errbox{display:grid;gap:4px}.lg-errbox .lg-lines{border-radius:7px}
  .lg-older{flex:1;min-height:0;padding:10px 12px;display:flex;flex-direction:column;gap:8px}.lg-chips{display:flex;flex-wrap:wrap;gap:6px}.lg-chips button{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border:1px solid #d7e0e5;border-radius:8px;background:#fff;font:12px Consolas,monospace}.lg-chips button.on{background:#e8f4f6;border-color:#9fcbd6}.lg-chips button.bad{border-color:#f0d3ce}

  .lg-pad{padding:8px 12px;display:flex;flex-direction:column;gap:8px;border-bottom:1px solid #e6edf0;flex:none}
  .lg-pop{position:absolute;right:12px;top:46px;z-index:5;width:340px;display:flex;flex-direction:column;gap:7px;padding:12px 14px;background:#fff;border:1px solid #9fcbd6;border-radius:10px;box-shadow:0 14px 34px #17384e40}.lg-pop>b{font-size:14px}.lg-pop>small{color:#647581}.lg-pop label{display:flex;align-items:center;gap:8px;font-size:12.5px}.lg-row{display:flex;align-items:center;gap:10px}.lg-row small{color:#647581}
  .lg-jline{display:flex;flex-wrap:wrap;gap:6px}.lg-jline>span{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border:1px solid #e6edf0;border-radius:7px;font-size:12px}.lg-jline>span.bad{border-color:#f0d3ce;background:#fdf6f5}.lg-jline small{color:#a5372c}
  .lg-day{font-style:normal;font-size:11px;font-weight:800;color:#647581;padding:6px 6px 2px;letter-spacing:.04em}.lg-tg{display:inline-flex;align-items:center;gap:5px;font-size:12px}.lg-rt .lg-st{margin-left:auto}.lg-rm{color:#647581;font-size:11px}
  .lg-goals{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;flex:none}.lg-goals button{display:grid;grid-template-columns:auto 1fr;column-gap:10px;text-align:left;padding:12px;border:1px solid #d7e0e5;border-radius:10px;background:#fff}.lg-goals button.on{border-color:#087c98;background:#e8f4f6}.lg-goals i{grid-row:span 2;font-style:normal;display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:#eef3f5;color:#087c98;font-weight:900}.lg-goals b{font-size:13.5px}.lg-goals small{color:#647581;font-size:11px}
  .lg-report{flex:1;min-height:0;padding:12px 14px;display:flex;flex-direction:column;gap:8px}.lg-report>b{font-size:13px}.lg-preview{flex:1;min-height:0;overflow:auto;border-radius:8px}.lg-preview .lg-lines{height:100%}.lg-report>.lg-btn{align-self:flex-start}
 `;
 function style() { let s = document.getElementById('lg-style'); if (!s) { s = document.createElement('style'); s.id = 'lg-style'; document.head.appendChild(s) } s.textContent = CSS }
 window.LG = {
  V,
  show(k, v = 1) {
   style(); const r = document.querySelector('#logs').getBoundingClientRect(), foot = document.querySelector('footer, .statusbar, #footer');
   const bottom = foot ? foot.getBoundingClientRect().top : innerHeight - 60;
   let host = document.getElementById('lg-overlay'); if (!host) { host = document.createElement('div'); host.id = 'lg-overlay'; document.body.appendChild(host) }
   Object.assign(host.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: (bottom - r.top) + 'px' }); host.innerHTML = V[k].html(v);
  },
 };
})();
