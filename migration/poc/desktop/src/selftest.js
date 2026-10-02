// 【検証用】本物の WebView の中から、窓・中身・画面のつながりを確かめる（DATARELAY_SELFTEST のときだけ流す）。
// 結果は /__desktop/selftest へ送り、窓がファイルに書いて終わる。
(async () => {
  const checks = [];
  const t0 = performance.now();
  const ok = (name, pass, detail) => checks.push({ name, ok: !!pass, detail: detail === undefined ? '' : String(detail) });
  const by = (r) => r.headers.get('X-DR-By');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const json = (b) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  try {
    const info = await (await fetch('/__desktop/info')).json();
    const program = info.info.program;
    if (info.mode === 'close') {
      // 閉じるだけの型: 常駐の理由が無いまま × を押す → 窓も中身も終わるはず（外の試験が終わり方を確かめる）
      const reason = (await (await fetch('/api/heartbeat-status')).json()).residency_pending_reason;
      await fetch('/__desktop/note', json({ reason }));
      await fetch('/__desktop/close', { method: 'POST' });
      return;
    }

    let r = await fetch('/');
    const html = await r.text();
    ok('画面（/）を Python が作る', r.status === 200 && by(r) === 'python' && html.includes('DataRelay'), `${r.status} ${by(r)} ${html.length}B`);

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
    r = await fetch('/api/pick-file', json({ initial: program, types: [['RNEファイル', '*.RNE'], ['すべて', '*.*']] }));
    const picked = await r.json();
    ok('ファイル選択は窓が受け持つ', by(r) === 'shell' && typeof picked.path === 'string', `${by(r)} ${picked.path}`);
    r = await fetch('/api/pick-folder', json({ initial: program }));
    ok('フォルダー選択は窓が受け持つ', by(r) === 'shell' && typeof (await r.json()).path === 'string', by(r));
    r = await fetch('/api/open-path', json({ path: program }));
    ok('エクスプローラーで開くは窓が受け持つ', by(r) === 'shell' && (await r.json()).ok, by(r));

    const info2 = await (await fetch('/__desktop/info')).json();
    ok('通知領域のアイコンがある', info2.tray === true, info2.tray);
    ok('保存したファイルを窓が覚えている', info2.saved.length === 2, info2.saved.join(' | '));

    // 常駐: 自動実行の予定を入れてから × を押す → 窓は隠れ、通知領域に残る（終わらない）
    const cur = await (await fetch('/api/config')).json();
    cur.jobs[0].schedules = [{ id: 'selftest', enabled: true, name: '毎朝', type: 'daily', time: '06:00' }];
    r = await fetch('/api/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cur) });
    const reason = (await (await fetch('/api/heartbeat-status')).json()).residency_pending_reason;
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
  } catch (e) {
    ok('例外', false, e && e.stack ? e.stack : e);
  }
  const result = { ok: checks.every((c) => c.ok), elapsed_ms: Math.round(performance.now() - t0), ua: navigator.userAgent, checks };
  await fetch('/__desktop/selftest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
})();
