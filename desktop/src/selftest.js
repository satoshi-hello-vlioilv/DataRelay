// 本物の WebView の中から、窓・中身・画面のつながりを確かめる（DATARELAY_SELFTEST のときだけ流す。CI の自己診断）。
// 結果は /__desktop/selftest へ送り、窓がファイルに書いて終わる。
(async () => {
  const checks = [];
  const t0 = performance.now();
  const ok = (name, pass, detail) => checks.push({ name, ok: !!pass, detail: detail === undefined ? '' : String(detail) });
  const by = (r) => r.headers.get('X-DR-By');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const json = (b) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  let r0;
  try {
    const info = await (await fetch('/__desktop/info')).json();
    const program = info.info.program;
    if (info.mode === 'restart') {
      // 起こし直しの型: 外の試験が中身（Python）を強制終了する → 窓が問い合わせを待たずに起こし直す
      const first = (await (await fetch('/api/instance')).json()).instance_id;
      await fetch('/__desktop/note', json({ pid: info.info.backend.pid, instance: first }));
      let now = first, tries = 0;
      const t1 = performance.now();
      while (now === first && tries < 120) {
        await sleep(500);
        tries++;
        try { const r = await fetch('/api/instance'); if (r.ok) now = (await r.json()).instance_id; } catch (e) {}
      }
      ok('中身が止まっても、窓が起こし直す', now && now !== first, `${first} → ${now}（${Math.round(performance.now() - t1)}ms）`);
      const r = await fetch('/api/residency');
      ok('起こし直した中身が答える', r.status === 200, r.status);
      const st = await (await fetch('/api/desktop-status')).json();
      ok('アプリ監視に起こし直しが出る', st.restarts >= 1 && st.last_restart, `${st.restarts}回 ${st.last_restart}`);
      const result = { ok: checks.every((c) => c.ok), checks };
      await fetch('/__desktop/selftest', json(result));
      return;
    }
    if (info.mode === 'release-restart' && !info.relaunched) {
      // 開き直しの型: 画面の「開き直して新しい版にする」と同じ道（窓が後始末を頼み、新しい自分を --after-pid 付きで起こして終わる）。
      // 開き直した窓（relaunched）は、下の release の型の確かめを流す
      const r1 = await fetch('/api/restart-app', { method: 'POST' });
      const a = await r1.json();
      await fetch('/__desktop/note', json({ restart: r1.status, answer: a }));
      return;
    }
    if (info.mode === 'release' || info.mode === 'release-restart') {
      // 配布の型（1.98.0）: 外の試験が置き場を作り、入口（置き場の DataRelay.exe）から写した／写しを配る版へそろえたあとに流れる。
      // 写しの中身・データの基準・各PCの名乗りが、配布の決まりどおりかを確かめる（外の試験は版とファイルを確かめる）
      const mon = await (await fetch('/api/desktop-status')).json();
      ok('配布の置き場から写したアプリとして動く（アプリ監視）', mon.place === 'installed', `place=${mon.place} exe=${mon.exe} 入れ替え=${mon.release_note || 'なし'}`);
      let painted = '';
      for (let i = 0; i < 40 && painted !== '正常'; i++) { await sleep(250); painted = (document.getElementById('mon-state') || {}).textContent || ''; }
      ok('画面の監視欄が「正常」と出す', painted === '正常', painted);
      const st = await (await fetch('/api/release/status')).json();
      ok('配る版と同じ版で動く', st.release && st.local === st.release.version && st.pending === false, `手元 ${st.local} ／ 配る版 ${st.release && st.release.version}`);
      ok('置き場は入れた元（config\\install.json）から知る', st.installed && st.dirSource === 'install' && st.reachable, `${st.dirSource} ${st.dir} ${st.why || ''}`);
      // 2.3.0: 写したPCは共有のユーザーのフォルダー（<置き場>\\users\\<ログオン名>）にデータを持ち、中身は置き場の既定の設定から入る。
      // ログオン名が分からないときだけ、これまでどおり手元（写しの data）
      const sep = st.appRoot.includes('\\') ? '\\' : '/';
      const ud = await (await fetch('/api/users-root')).json();
      const wantUser = !!ud.name;
      ok('データの基準は共有のユーザーのフォルダー（ログオン名が分からなければ写しの data）',
         wantUser ? (st.dataRootSource === 'user' && st.dataRoot === ud.mine) : (st.dataRootSource === 'pc' && st.dataRoot === st.appRoot + sep + 'data'),
         `${st.dataRootSource} ${st.dataRoot} ／ ログオン名 ${ud.name || '(なし)'}`);
      r0 = await fetch('/api/path-convert', json({ value: '.\\rne\\SIKAODRNOW.RNE', mode: 'absolute' }));
      const conv = await r0.json();
      ok('相対パスで置き場に無い物はデータの基準から', typeof conv.resolved === 'string' && conv.resolved.toLowerCase().startsWith(st.dataRoot.toLowerCase()), `${conv.resolved}`);
      let got = null;
      for (let i = 0; i < 40; i++) { got = await (await fetch('/api/config')).json(); if ((got.jobs || []).length) break; await sleep(500); }
      ok('置き場の既定の設定から、対象が手元に入った（聞かずに）', (got.jobs || []).length === 6, `${(got.jobs || []).map((j) => j.name).join('・')}`);
      const offer = await (await fetch('/api/defaults/offer')).json();
      ok('入れた既定は、もう聞かない', offer.show === false, JSON.stringify({ show: offer.show, kind: offer.kind }));
      await fetch('/api/release/check', { method: 'POST' });
      const st2 = await (await fetch('/api/release/status')).json();
      const me = (st2.fleet || []).find((f) => f.version === st.local);
      ok('このPCが置き場へ版を名乗る（各PCの版）', !!me && me.place === 'installed' && me.outdated === false, me ? `${me.pc} ${me.version} ${me.place}` : JSON.stringify(st2.fleet));
      const brief = await (await fetch('/api/release/brief')).json();
      ok('上の帯の答え（新しい版なし・開き直してよい）', brief.place === 'installed' && brief.pending === false && brief.restartBlock === '', JSON.stringify({ pending: brief.pending, block: brief.restartBlock }));
      await fetch('/__desktop/note', json({ version: st.local, release_note: mon.release_note || '', dataRoot: st.dataRoot }));
      await fetch('/__desktop/selftest', json({ ok: checks.every((c) => c.ok), checks }));
      return;
    }
    if (info.mode === 'close') {
      // 閉じるだけの型: 常駐の理由が無いまま × を押す → 窓も中身も終わるはず（外の試験が終わり方を確かめる）
      const reason = (await (await fetch('/api/residency')).json()).reason;
      await fetch('/__desktop/note', json({ reason }));
      await fetch('/__desktop/close', { method: 'POST' });
      return;
    }

    let r = await fetch('/');
    const html = await r.text();
    ok('画面のひな形（/）は Rust が返す', r.status === 200 && by(r) === 'shell' && html.includes('DataRelay'), `${r.status} ${by(r)} ${html.length}B`);
    // アプリ監視: 窓が中身（Python）の様子を答え、画面の監視欄がそれを出す
    r = await fetch('/api/desktop-status');
    const mon = await r.json();
    ok('窓が中身の様子を答える（アプリ監視）', by(r) === 'shell' && mon.alive === true && mon.backend && mon.backend.pid === info.info.backend.pid, `${by(r)} alive=${mon.alive} pid=${mon.backend && mon.backend.pid}`);
    ok('exe の置き場が分かる（アプリ監視）', ['local', 'beside', 'env', 'installed'].includes(mon.place) && typeof mon.exe === 'string' && mon.exe.length > 0, `place=${mon.place} updated_from=${mon.updated_from || ''} exe=${mon.exe}`);
    let painted = '';
    for (let i = 0; i < 40 && painted !== '正常'; i++) { await sleep(250); painted = (document.getElementById('mon-state') || {}).textContent || ''; }
    ok('画面の監視欄が「正常」と出す', painted === '正常' && (document.getElementById('mon-pid') || {}).textContent === String(info.info.backend.pid), `${painted} pid=${(document.getElementById('mon-pid') || {}).textContent}`);

    // Navigator の接続情報（1.99.0）: 新しい置き場では未登録なので、初めて開いたときに登録を聞く。
    // 画面から保存すると「登録済み」と描き、パスワードはどの答えにも出ない。確かめたら消して元に戻す
    let asked = false;
    for (let i = 0; i < 40 && !asked; i++) { await sleep(250); asked = !!(document.getElementById('login-dialog') || {}).open; }
    ok('初めて開いたとき、接続情報の登録を聞く', asked, asked ? 'ダイアログが開いた' : '開かなかった');
    document.getElementById('login-server').value = 'SELFTEST-SV';
    document.getElementById('login-user').value = '自己診断';
    document.getElementById('login-password').value = 'pw-selftest-秘密';
    document.getElementById('login-save').click();
    let card = '';
    for (let i = 0; i < 40 && card !== 'このPCに登録済み'; i++) { await sleep(250); card = (document.getElementById('login-state') || {}).textContent || ''; }
    r = await fetch('/api/login');
    const loginRaw = await r.text();
    const login = JSON.parse(loginRaw);
    ok('画面から保存すると、このPCに登録済みと描く', card === 'このPCに登録済み' && login.saved && login.user === '自己診断' && !document.getElementById('login-dialog').open, `${card} ${login.server} ${login.where}`);
    ok('パスワードは画面への答えに出ない', !loginRaw.includes('pw-selftest') && login.has_password === true, `${loginRaw.length}B`);
    await fetch('/api/login/delete', { method: 'POST' });
    // 更新の休止の印（1.99.0）: 作る途中の木では出さない
    ok('作る途中の木では「更新 休止中」の印を出さない', (document.getElementById('update-badge') || {}).hidden === true, String((document.getElementById('update-badge') || {}).hidden));

    // 起動アイコン（1.99.2）: 窓が exe の場所を渡す。作る途中の木では作らず、理由を答える（本物のデスクトップを汚さない）
    r = await fetch('/api/shortcut');
    const sc = await r.json();
    ok('起動アイコンの状態を答える（作る途中の木では作らない）', r.status === 200 && sc.available === false && /作る途中/.test(sc.why || ''), `${sc.place} ${sc.why}`);
    r = await fetch('/api/shortcut/make', json({ where: ['desktop'] }));
    ok('作る途中の木では、頼まれても作らない', r.status === 400, r.status);

    // 配布と更新（1.98.0）: 作る途中の木では置き場＝アプリのフォルダー。配る版は無く、名乗らない
    r = await fetch('/api/release/status');
    const rel = await r.json();
    ok('配布と更新の状態を答える', r.status === 200 && rel.ok && rel.place === 'dev' && rel.dirSource === 'app' && rel.pending === false, `${r.status} place=${rel.place} dir=${rel.dirSource} reachable=${rel.reachable}`);
    ok('相対パスの基準（データの基準）は、作る途中ではアプリのフォルダー', rel.dataRoot === rel.appRoot && rel.dataRootSource !== 'install', `${rel.dataRootSource} ${rel.dataRoot}`);

    r = await fetch('/static/app.js');
    ok('静的ファイルは Rust が返す', r.status === 200 && by(r) === 'shell', `${r.status} ${by(r)}`);

    r = await fetch('/api/config');
    const cfg = await r.json();
    ok('API（設定の読み出し）', r.status === 200 && by(r) === 'python' && Array.isArray(cfg.jobs), `${cfg.jobs && cfg.jobs.length}件の対象`);

    r = await fetch('/api/rne-shape', json({ rne_path: `${program}/samples/rne/集計表形式サンプル.RNE` }));
    const shape = await r.json();
    ok('日本語のパスを渡す（集計表のRNEの形）', shape.ok && shape.crosstab && (shape.head || [])[0] === 'BOX番号', shape.summary);

    const big = 'あ'.repeat(350000); // UTF-8 で約1MB
    r = await fetch('/api/validate', json({ jobs: [{ name: '検査', comment: big }] }));
    ok('約1MBの日本語の本文を送る', r.status === 200, `${r.status}`);

    let t = performance.now();
    const many = await Promise.all(Array.from({ length: 40 }, () => fetch('/api/status').then((x) => x.json())));
    ok('同時に40本', many.every((x) => typeof x === 'object' && x !== null), `${Math.round(performance.now() - t)}ms`);

    t = performance.now();
    for (let i = 0; i < 20; i++) await (await fetch('/api/status')).json();
    const apiMs = (performance.now() - t) / 20;
    t = performance.now();
    for (let i = 0; i < 20; i++) await (await fetch('/static/app.css')).text();
    const staticMs = (performance.now() - t) / 20;
    ok('速さ（1回あたり）', apiMs < 200, `Python の API ${apiMs.toFixed(1)}ms / Rust の部品 ${staticMs.toFixed(1)}ms`);

    // ダウンロード: Python が「保存してください」と答えたら、窓が保存ダイアログで受けて書く（画面は移動しない）
    r = await fetch('/api/bundle/export?parts=jobs,schedules,layouts,recipes');
    const saved = decodeURIComponent(r.headers.get('X-DR-Saved') || '');
    ok('ダウンロードを窓が保存する（ZIP・日本語の名前）', r.status === 204 && /\.zip$/.test(saved), `${r.status} ${saved}`);
    r = await fetch('/api/data-viewer/export-pivot', json({ format: 'xlsx', name: '集計', matrix: [['用途', '件数'], ['缶材', 3]] }));
    const saved2 = decodeURIComponent(r.headers.get('X-DR-Saved') || '');
    ok('集計結果の EXCEL も窓が保存する', r.status === 204 && /\.xlsx$/.test(saved2), `${r.status} ${saved2}`);

    // 集計表: D&D を使わず、カラムの札を押すだけで表ができる（2.1.3。Windows の窓では D&D が届かず組めなかった）
    document.querySelector('nav button[data-p="viewer"]').click();
    setViewerTable({ name: '自己診断', headers: ['工程', '作業者', '数量'], rows: [['研削', '佐藤', '3'], ['研削', '鈴木', '5'], ['検査', '佐藤', '2']] }, '');
    applyViewerSearch(); refreshDesigner(); setViewerView('pivot');
    const quick = document.querySelectorAll('#pivot-empty:not([hidden]) .pv-quick button').length;
    document.querySelector('#pivot-field-list .pv-f[data-col="0"] .pv-r[data-role="rows"]').click();
    document.querySelector('#pivot-field-list .pv-f[data-col="1"] .pv-r[data-role="columns"]').click();
    document.querySelector('#pivot-field-list .pv-f[data-col="2"] .pv-r[data-role="values"]').click();
    const grand = [...document.querySelectorAll('#pivot-body tr.row-grand td')].map((td) => td.textContent).join(',');
    ok('集計表は札を押すだけで組める（行=工程・列=作業者・数量の合計）', quick > 0 && $('#pivot-measure').value === 'sum:2' && grand === '5,5,10' && !$('#analysis-pivot-result').hidden, `おすすめ ${quick} / 値 ${$('#pivot-measure').value} / 総計 ${grand}`);
    // 表示列・条件・日付のまとめ（2.2.0）: 帯の条件で絞った行から数え、日付の列を［年・月・日］で年月にまとめ、札の中で年へ切り替える
    setViewerTable({ name: '自己診断', headers: ['工程', '着手日時', '数量'], rows: [['研削', '2026-09-30 08:00', '3'], ['研削', '2026-10-01 09:00', '5'], ['検査', '2026-10-02 10:00', '2'], ['研削', '2027-01-05 07:00', '1']] }, '');
    applyViewerSearch(); refreshDesigner(); setViewerView('pivot');
    viewerSpec = { filters: [{ column: '工程', op: 'eq', value: '研削' }] }; viewerChanged('filters');
    const chips = document.querySelectorAll('#viewer-conds .vb-cond').length, hit = $('#viewer-filter-summary').textContent;
    document.querySelector('#pivot-field-list .pv-f[data-col="1"] .pv-d').click();
    document.querySelector('#pivot-date-pop [data-part="ym"]').click();
    const ymRows = [...document.querySelectorAll('#pivot-body tr th')].map((th) => th.textContent).join(',');
    const part = $('#pivot-rows .pv-part'); part.value = 'year'; part.dispatchEvent(new Event('change'));
    const yRows = [...document.querySelectorAll('#pivot-body tr th')].map((th) => th.textContent).join(',');
    setViewerView('list');
    const listHeads = [...document.querySelectorAll('#viewer-head th')].map((th) => th.textContent).join(',');
    ok('条件で絞った行から、日付の列を年月・年にまとめて数えられる（一覧にもまとめた列が出る）',
      chips === 1 && hit.startsWith('3') && ymRows === '2026-09,2026-10,2027-01,総計' && yRows === '2026,2027,総計' && listHeads.includes('着手日時（年月）') && listHeads.includes('着手日時（年）'),
      `条件 ${chips} / ${hit} / 年月 ${ymRows} / 年 ${yRows} / 一覧 ${listHeads}`);
    setViewerView('pivot');
    // ログ・診断（2.1.3）: 実行の記録と選んだ実行を描き、報告用の文を組める
    document.querySelector('nav button[data-p="logs"]').click();
    await loadLog();
    const runsShown = document.querySelectorAll('#log-runs .lg-run').length, sel = logRunSel();
    const report = sel ? logReportText(sel, { summary: true, env: true, issues: true }, logEnv()) : '';
    ok('ログ・診断は実行の記録を並べ、選んだ実行の報告用の文を組める', runsShown > 0 && !!sel && report.includes('■ 環境') && $('#log-run-title').textContent !== 'ログを読んでいます', `${runsShown}件 / ${$('#log-run-title').textContent} / ${report.length}字`);
    // 後処理（2.6.0）: 対象の編集のタブ「後処理」は入口（見本の無い新しい対象では、そのまま出すことと見本が無いことを言う）。
    // 編集は Power Query エディター: 見出しを押して列を選び、「変換」の札でピボット解除を足すと、Excel と同じ名前のステップが最後に足される
    openEditor(null);
    document.querySelector('.editor-tab[data-etab="post"]').click();
    let postNote = '';
    for (let i = 0; i < 40 && !postNote; i++) { await sleep(150); postNote = (postView && postView.no_sample) || ''; }
    const postOff = !!document.querySelector('#post-pane .post-state.off') && !!document.querySelector('#post-pane #post-open') && collectJob().post.enabled === false;
    $('#editor').close();
    mqOpen({ id: '', name: '自己診断の変換', description: '', code: 'let\n    ソース = #table({"品番", "4月", "5月"}, {{"A", 1, 2}, {"B", 3, null}})\nin\n    ソース', output: '' });
    for (let i = 0; i < 40 && !(mqView && mqView.ok); i++) await sleep(150);
    mqPickCol(0, {});
    const ribbonOn = !document.querySelector('#mqx-ribbon [data-op="unpivot"]').disabled;
    await mqOp('unpivot-other');
    const mqCols = ((mqView || {}).columns || []).map((c) => c.name).join(','), mqStep = (mqView || {}).step;
    ok('後処理の入口と、Power Query エディターの「変換」の札（列を選んでピボット解除を足す）',
      postOff && postNote.includes('一度実行すると') && ribbonOn && mqStep === 'ピボット解除された列' && mqCols === '品番,属性,値' && mqView.row_count === 3 && mqEditing.code.includes('Table.UnpivotOtherColumns(ソース, {"品番"}'),
      `入口 ${postOff} / ${postNote} / 札 ${ribbonOn} / ${mqStep} / ${mqCols} / ${mqView && mqView.row_count}行`);
    await mqClose(false);
    // 繰り返し列の展開（2.7.0）: 列名から「品名・数量 × 2回」を見つけ、見本を出し、「行に展開」でステップを足す（空の回は行にしない）
    mqOpen({ id: '', name: '自己診断の繰り返し', description: '', code: 'let\n    ソース = #table({"伝票", "品名1", "数量1", "品名2", "数量2", "合計"}, {{"A", "りんご", "1", "みかん", "2", "3"}, {"B", "なし", "5", null, null, "5"}})\nin\n    ソース', output: '' });
    for (let i = 0; i < 40 && !(mqView && mqView.ok); i++) await sleep(150);
    await mqOp('repeat');
    for (let i = 0; i < 60 && !(mqRep && !mqRep.busy && mqRep.after); i++) await sleep(150);
    const repFound = mqRep && mqRep.step ? `${mqRep.step.names.join('・')} × ${mqRep.step.groups.length}` : '';
    const repShown = !!document.querySelector('#mq-rep-body .mrp-strip') && !!document.querySelector('#mq-rep-body .mrp-tbl') && !$('#mq-rep-ok').disabled;
    $('#mq-rep-ok').click();
    for (let i = 0; i < 60 && !(mqView && mqView.step === '展開された繰り返し列'); i++) await sleep(150);
    const repCols = ((mqView || {}).columns || []).map((c) => c.name).join(',');
    ok('繰り返し列の展開（列名から見つけて、見本を見て、行に展開する）',
      repFound === '品名・数量 × 2' && repShown && !$('#mq-rep-dialog').open && repCols === '伝票,番号,品名,数量,合計' && mqView.row_count === 3,
      `${repFound} / 見本 ${repShown} / ${mqView && mqView.step} / ${repCols} / ${mqView && mqView.row_count}行`);
    await mqClose(false);
    document.querySelector('nav button[data-p="jobs"]').click();

    // 上部（2.9.0）: タブは帯の中。絞り込みは小窓にまとめ、いまの条件をボタンに要約する。選ぶと道具の段が選んだ物の操作に替わる
    const navInBar = !!document.querySelector('.appbar nav button[data-p="jobs"].on');
    $('#filter-open').click();
    await sleep(50);
    const popOpen = !$('#filter-pop').hidden && document.activeElement === $('#search');
    $('#filter-enabled').value = 'disabled';
    $('#filter-enabled').dispatchEvent(new Event('change'));
    const sumSet = $('#filter-summary').textContent, marked = $('#filter-open').classList.contains('is-set');
    $('#filter-reset').click();
    const sumReset = $('#filter-summary').textContent;
    document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    const popClosed = $('#filter-pop').hidden;
    const jobRows = document.querySelectorAll('#jobs-body tr').length;
    setAllSelected(true);
    const selShown = !document.querySelector('.jb-sel').hidden && document.querySelector('.jb-idle').hidden && $('#sel-count').textContent === String(jobRows);
    setAllSelected(false);
    const selBack = document.querySelector('.jb-sel').hidden && !document.querySelector('.jb-idle').hidden;
    ok('上部: タブは帯の中・絞り込みは小窓で要約をボタンに出し、選ぶと道具の段が選んだ物の操作に替わる',
      navInBar && popOpen && sumSet.startsWith('無効') && marked && sumReset === 'すべて・登録順' && popClosed && (jobRows === 0 || selShown) && selBack,
      `帯 ${navInBar} / 小窓 ${popOpen} / ${sumSet} → ${sumReset} / 閉じる ${popClosed} / 選択 ${jobRows}件 ${selShown} → ${selBack}`);

    // tkinter・os.startfile の置き換え（答えの形はいまと同じ {"path": ...}）
    // 設定のパスは相対（アプリフォルダー基準）・<PC>（この PC の作業場所）のことがある。窓は Python と同じ決まりで実際の場所へ直す
    const absolute = (p) => typeof p === 'string' && /^(?:\/|[A-Za-z]:[\\/]|\\\\)/.test(p);
    r = await fetch('/api/pick-file', json({ initial: 'samples/rne', types: [['RNEファイル', '*.RNE'], ['すべて', '*.*']] }));
    const picked = await r.json();
    ok('ファイル選択は窓が受け持つ（初期フォルダーの相対パスを直す）', by(r) === 'shell' && typeof picked.path === 'string' && absolute(picked.initial) && /rne$/.test(picked.initial), `${by(r)} ${picked.initial}`);
    r = await fetch('/api/pick-folder', json({ initial: '<PC>' }));
    const pickedDir = await r.json();
    ok('フォルダー選択は窓が受け持つ（<PC> を直す）', by(r) === 'shell' && absolute(pickedDir.initial) && !pickedDir.initial.includes('<PC>'), `${by(r)} ${pickedDir.initial}`);

    // 読取マスタの区切り（2.8.0）: 新規 → 区切り → 見本から列を作る → 名前を入れると自動で保存。一覧は1件1行で、種類で絞れる
    document.querySelector('nav button[data-group="masters"]').click();
    document.querySelector('button[data-p="layouts"]:not([data-group])').click();
    for (let i = 0; i < 40 && !layoutMeta.delimiters.length; i++) await sleep(150);
    $('#lay-add').click();
    await sleep(100);
    document.querySelector('#lay-mode button[data-mode="delimited"]').click();
    $('#lay-header-row').checked = true;
    $('#lay-sample').value = picked.initial.replace(/rne$/, 'text') + (picked.initial.includes('\\') ? '\\' : '/') + '受注明細.csv';
    await laySniff();
    const layCols = [...document.querySelectorAll('#lay-cols .lay-name')].map((x) => x.value).join(',');
    const laySmp = document.querySelector('#lay-cols .lay-col:nth-child(3) .lay-smp')?.textContent;
    $('#lay-name').value = '自己診断の区切り';
    $('#lay-name').dispatchEvent(new Event('input'));
    for (let i = 0; i < 60 && !/保存しました/.test($('#lay-autosave').textContent); i++) await sleep(150);
    const laySaved = (await (await fetch('/api/text-layouts')).json()).items.find((x) => x.name === '自己診断の区切り');
    document.querySelector('.lay-list-pane .ml-chips button[data-k="delimited"]').click();
    const layRows = [...document.querySelectorAll('#lay-list .ml-row')].map((x) => x.querySelector('.ml-name').textContent);
    ok('読取マスタの区切り（見本から列を作り、自動で保存し、一覧で区切りに絞れる）',
      layCols === '受注番号,受注日,得意先名,品名,数量,備考' && laySmp === '東和工業, 第二工場' && laySaved && laySaved.mode === 'delimited' &&
      laySaved.shape === '6列 / カンマ区切り' && layRows.includes('自己診断の区切り') && document.querySelectorAll('#lay-list .ml-row.ml-fx').length === 0,
      `${layCols} / ${laySmp} / ${$('#lay-autosave').textContent} / ${laySaved && laySaved.shape} / 区切り ${layRows.length}件`);
    if (laySaved) await fetch('/api/text-layouts/' + encodeURIComponent(laySaved.id), { method: 'DELETE' });
    document.querySelector('.lay-list-pane .ml-chips button[data-k=""]').click();
    document.querySelector('nav button[data-p="jobs"]').click();
    r = await fetch('/api/open-path', json({ path: 'static' }));
    const opened = await r.json();
    ok('エクスプローラーで開くは窓が受け持つ（相対パスを直す）', by(r) === 'shell' && opened.ok && absolute(opened.path) && /static$/.test(opened.path), `${by(r)} ${r.status} ${opened.path || opened.error}`);

    const info2 = await (await fetch('/__desktop/info')).json();
    ok('通知領域のアイコンがある', info2.tray === true, info2.tray);
    ok('保存したファイルを窓が覚えている', info2.saved.length === 2, info2.saved.join(' | '));

    // 常駐: 自動実行の予定を入れてから × を押す → 窓は隠れ、通知領域に残る（終わらない）
    const cur = await (await fetch('/api/config')).json();
    // 2.0.0 から雛形は空（対象は置き場の既定の設定から入る）。試す対象を1件足してから予定を入れる
    if (!cur.jobs.length) cur.jobs.push({ id: 'selftest-job', name: '自己診断', enabled: true, source: 'rne', rne: 'SIKAODRNOW.RNE', rne_path: `${program}/samples/defaults/rne/SIKAODRNOW.RNE`, output_folder: '<PC>\\selftest', output_file: 'selftest.csv', output_format: 'csv', schedules: [] });
    cur.jobs[0].schedules = [{ id: 'selftest', enabled: true, name: '毎朝', type: 'daily', time: '06:00' }];
    r = await fetch('/api/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cur) });
    const reason = (await (await fetch('/api/residency')).json()).reason;
    ok('自動実行の予定を入れると、常駐の理由がある', r.status === 200 && reason === '自動実行の予定あり', reason);
    await fetch('/__desktop/close', { method: 'POST' });
    let after = null;
    for (let i = 0; i < 30; i++) {
      await sleep(200);
      after = await (await fetch('/__desktop/info')).json();
      if (after.visible === false) break;
    }
    ok('× を押すと、窓は隠れて常駐する（終わらない）', after.visible === false && after.resident_reason === reason, `visible=${after.visible} reason=${after.resident_reason}`);
    r = await fetch('/api/status');
    ok('常駐中も中身（Python）は答える', r.status === 200, r.status);
    await fetch('/__desktop/show', { method: 'POST' });
    await sleep(300);
    const shown = await (await fetch('/__desktop/info')).json();
    ok('通知領域から開くと窓が戻る', shown.visible === true && shown.resident_reason === '', `visible=${shown.visible}`);

    // 画面の「タスクバーへ」: 窓が隠れて常駐する（アイコンは窓が持つので、いつでも引き受けられる）
    r = await fetch('/api/stay-resident', { method: 'POST' });
    const st = await r.json();
    ok('「タスクバーへ」は窓が受け持つ', by(r) === 'shell' && st.ok && st.tray_available, `${by(r)} ${st.reason}`);
    let hid = null;
    for (let i = 0; i < 30; i++) {
      await sleep(200);
      hid = await (await fetch('/__desktop/info')).json();
      if (hid.visible === false) break;
    }
    ok('「タスクバーへ」で窓が隠れる', hid.visible === false, `visible=${hid.visible}`);
    await fetch('/__desktop/show', { method: 'POST' });

    // ブラウザ版の受け口（心拍・閉じる知らせ）は中身から外してある（1.96.0）
    const gone = [];
    for (const [m, u] of [['POST', '/api/heartbeat'], ['GET', '/api/heartbeat-status'], ['POST', '/api/browser-closing']]) {
      const g = await fetch(u, m === 'POST' ? json({}) : {});
      gone.push(`${u}=${g.status}`);
    }
    ok('ブラウザ版の受け口（心拍・閉じる知らせ）が無い', gone.every((x) => x.endsWith('=404')), gone.join(' '));
  } catch (e) {
    ok('例外', false, e && e.stack ? e.stack : e);
  }
  const result = { ok: checks.every((c) => c.ok), elapsed_ms: Math.round(performance.now() - t0), ua: navigator.userAgent, checks };
  await fetch('/__desktop/selftest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
})();
