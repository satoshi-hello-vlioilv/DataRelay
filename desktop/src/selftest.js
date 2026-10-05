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
      ok('データの基準は置き場（共有のアプリのフォルダー）', st.dataRoot === st.dir && st.dataRootSource === 'install', `${st.dataRootSource} ${st.dataRoot}`);
      r0 = await fetch('/api/path-convert', json({ value: '.\\config\\symnavim.conf', mode: 'absolute' }));
      const conv = await r0.json();
      ok('相対パスは共有のアプリのフォルダー基準（写しではない）', typeof conv.resolved === 'string' && conv.resolved.toLowerCase().startsWith(st.dataRoot.toLowerCase()) && conv.base.toLowerCase().startsWith(st.dataRoot.toLowerCase()), `${conv.resolved}`);
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

    // tkinter・os.startfile の置き換え（答えの形はいまと同じ {"path": ...}）
    // 設定のパスは相対（アプリフォルダー基準）・<PC>（この PC の作業場所）のことがある。窓は Python と同じ決まりで実際の場所へ直す
    const absolute = (p) => typeof p === 'string' && /^(?:\/|[A-Za-z]:[\\/]|\\\\)/.test(p);
    r = await fetch('/api/pick-file', json({ initial: 'samples/rne', types: [['RNEファイル', '*.RNE'], ['すべて', '*.*']] }));
    const picked = await r.json();
    ok('ファイル選択は窓が受け持つ（初期フォルダーの相対パスを直す）', by(r) === 'shell' && typeof picked.path === 'string' && absolute(picked.initial) && /rne$/.test(picked.initial), `${by(r)} ${picked.initial}`);
    r = await fetch('/api/pick-folder', json({ initial: '<PC>' }));
    const pickedDir = await r.json();
    ok('フォルダー選択は窓が受け持つ（<PC> を直す）', by(r) === 'shell' && absolute(pickedDir.initial) && !pickedDir.initial.includes('<PC>'), `${by(r)} ${pickedDir.initial}`);
    r = await fetch('/api/open-path', json({ path: 'static' }));
    const opened = await r.json();
    ok('エクスプローラーで開くは窓が受け持つ（相対パスを直す）', by(r) === 'shell' && opened.ok && absolute(opened.path) && /static$/.test(opened.path), `${by(r)} ${r.status} ${opened.path || opened.error}`);

    const info2 = await (await fetch('/__desktop/info')).json();
    ok('通知領域のアイコンがある', info2.tray === true, info2.tray);
    ok('保存したファイルを窓が覚えている', info2.saved.length === 2, info2.saved.join(' | '));

    // 常駐: 自動実行の予定を入れてから × を押す → 窓は隠れ、通知領域に残る（終わらない）
    const cur = await (await fetch('/api/config')).json();
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
