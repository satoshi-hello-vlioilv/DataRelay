// 2.1.1「値ごとに分けて出す」の進み具合の案（CLAUDE.md §3）。一覧の行（.rowprogress の .rp-live）と、
// 進捗の窓のライン（#p-parallel-lines .pline）に、案ごとの DOM と CSS を当てて再現する。
// 状態はどの案も同じ: 1回の問い合わせ（6値まとめて）は済み、LS4・LS3 は作成済み、DL2 を作成中、TLV・CAL・FS4 は待ち。
// 撮り方: 撮影用の仕掛けで window.VP.show(k)。1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const ITEMS = [{ v: 'LS4', s: 'ok', n: 8520 }, { v: 'LS3', s: 'ok', n: 8104 }, { v: 'DL2', s: 'run', n: 8312 }, { v: 'TLV', s: 'wait', n: 8290 }, { v: 'CAL', s: 'wait', n: 8402 }, { v: 'FS4', s: 'wait', n: 8252 }];
 const N = ITEMS.length, DONE = ITEMS.filter(x => x.s === 'ok').length, PCT = 86;
 const mark = s => ({ ok: '✓', ng: '×', run: '…', wait: '' }[s]);
 const chip = x => `<em class="vp-c vp-${x.s}" title="${E(x.v)} ${x.n.toLocaleString()}件">${E(x.v)}${mark(x.s) ? `<b>${mark(x.s)}</b>` : ''}</em>`;
 const seg = () => `<span class="vp-seg">${ITEMS.map(x => `<i class="vp-s vp-${x.s}" title="${E(x.v)}"></i>`).join('')}</span>`;
 const segName = () => `<span class="vp-seg vp-segn">${ITEMS.map(x => `<i class="vp-s vp-${x.s}" title="${E(x.v)}">${E(x.v)}</i>`).join('')}</span>`;
 const bar = (p = PCT) => `<div class="rp-track"><i class="rp-bar" style="width:${p}%"></i></div>`;
 const V = {
  A: { name: 'A 文字だけ（状態に k/N、詳しくに値）', row: () => `<div class="rp-live-top"><span class="rp-state">値ごとに作成 3/6</span><time class="rp-elapsed">00:03:00</time></div>${bar()}<div class="rp-detail">DL2 · 変換・検証 · 8,312件</div>`,
   lane: () => `<header><b>ライン 1</b><span>値ごとに作成 3/6</span></header><strong>設備単位実績</strong><div class="lane-progress"><i style="width:${PCT}%"></i></div><footer><small>DL2 · 変換・検証 · 8,312件</small><time>00:03:00</time></footer>` },
  B: { name: 'B バーを値の数で区切る（済・作成中・待ちの色）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6 済</span><time class="rp-elapsed">00:03:00</time></div>${seg()}<div class="rp-detail">DL2 を作成中 · 8,312件</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6 済</span></header><strong>設備単位実績</strong>${seg()}<footer><small>DL2 を作成中 · 8,312件</small><time>00:03:00</time></footer>` },
  C: { name: 'C バーの下に値の札（✓・…）', row: () => `<div class="rp-live-top"><span class="rp-state">値ごとに作成</span><time class="rp-elapsed">00:03:00</time></div>${bar()}<div class="vp-chips">${ITEMS.map(chip).join('')}</div>`,
   lane: () => `<header><b>ライン 1</b><span>値ごとに作成</span></header><strong>設備単位実績</strong><div class="lane-progress"><i style="width:${PCT}%"></i></div><div class="vp-chips">${ITEMS.map(chip).join('')}</div><footer><small>DL2 · 変換・検証</small><time>00:03:00</time></footer>` },
  D: { name: 'D 2段のバー（上: 問い合わせ 1回、下: ファイル k/N）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6</span><time class="rp-elapsed">00:03:00</time></div><div class="vp-two"><small>問い合わせ</small><div class="rp-track"><i class="rp-bar" style="width:100%"></i></div><small>ファイル</small><div class="rp-track"><i class="rp-bar vp-b2" style="width:${(DONE + .4) / N * 100}%"></i></div></div><div class="rp-detail">DL2 · 変換・検証</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6</span></header><strong>設備単位実績</strong><div class="vp-two"><small>問い合わせ 49,880件</small><div class="lane-progress"><i style="width:100%"></i></div><small>ファイル</small><div class="lane-progress"><i class="vp-b2" style="width:${(DONE + .4) / N * 100}%"></i></div></div><footer><small>DL2 · 変換・検証</small><time>00:03:00</time></footer>` },
  E: { name: 'E 右に大きな k/N と今の値', row: () => `<div class="vp-e"><div><div class="rp-live-top"><span class="rp-state">値ごとに作成</span><time class="rp-elapsed">00:03:00</time></div>${bar()}<div class="rp-detail">DL2 · 変換・検証 · 8,312件</div></div><b class="vp-big">2<small>/6</small></b></div>`,
   lane: () => `<header><b>ライン 1</b><span>値ごとに作成</span></header><div class="vp-e"><strong>設備単位実績</strong><b class="vp-big">2<small>/6</small></b></div><div class="lane-progress"><i style="width:${PCT}%"></i></div><footer><small>DL2 · 変換・検証</small><time>00:03:00</time></footer>` },
  F: { name: 'F 段階の点（問い合わせ → 受け取り → 分ける → ファイル）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイルを作成</span><time class="rp-elapsed">00:03:00</time></div><div class="vp-steps"><span class="done">問い合わせ</span><span class="done">受け取り</span><span class="done">分ける</span><span class="now">ファイル 2/6</span></div><div class="rp-detail">DL2 · 変換・検証</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイルを作成</span></header><strong>設備単位実績</strong><div class="vp-steps"><span class="done">問い合わせ</span><span class="done">受け取り</span><span class="done">分ける</span><span class="now">ファイル 2/6</span></div><footer><small>DL2 · 変換・検証</small><time>00:03:00</time></footer>` },
  G: { name: 'G 行は短く、窓のラインに値ごとの一覧表', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6</span><time class="rp-elapsed">00:03:00</time></div>${bar()}<div class="rp-detail">DL2 を作成中（詳しくは進捗の窓）</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6</span></header><strong>設備単位実績</strong><div class="lane-progress"><i style="width:${PCT}%"></i></div><table class="vp-tbl">${ITEMS.map(x => `<tr class="vp-${x.s}"><td>${mark(x.s) || '・'}</td><td><b>${E(x.v)}</b></td><td>${x.s === 'ok' ? x.n.toLocaleString() + '件' : x.s === 'run' ? '作成中' : '待ち'}</td></tr>`).join('')}</table><footer><small>問い合わせ 1回 · 49,880件</small><time>00:03:00</time></footer>` },
  // 2回目の組合せ案（1回目の上位 B・C・G のエッセンスを組み直す）
  H: { name: 'H 区切りバー＋詳しくに「済の値・今の値」（B＋Cの名前を文字で）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6 済</span><time class="rp-elapsed">00:03:00</time></div>${seg()}<div class="rp-detail">作成中 DL2 · 済 LS4・LS3</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6 済</span></header><strong>設備単位実績</strong>${seg()}<footer><small>作成中 DL2 · 済 LS4・LS3</small><time>00:03:00</time></footer>` },
  I: { name: 'I 区切りバー＋例外だけ札（作成中・失敗の値だけ名前を出す）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6 済</span><time class="rp-elapsed">00:03:00</time></div>${seg()}<div class="vp-chips">${ITEMS.filter(x => x.s === 'run' || x.s === 'ng').map(chip).join('')}<small class="vp-rest">ほか 済2・待ち3</small></div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6 済</span></header><strong>設備単位実績</strong>${seg()}<div class="vp-chips">${ITEMS.filter(x => x.s === 'run' || x.s === 'ng').map(chip).join('')}<small class="vp-rest">ほか 済2・待ち3</small></div><footer><small>問い合わせ 1回 · 49,880件</small><time>00:03:00</time></footer>` },
  J: { name: 'J 区切りバー＋ラインに開ける値の一覧（B＋G、一覧は既定で閉じる）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6 済</span><time class="rp-elapsed">00:03:00</time></div>${seg()}<div class="rp-detail">DL2 を作成中 · 8,312件</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6 済</span></header><strong>設備単位実績</strong>${seg()}<footer><small>DL2 を作成中 · 8,312件</small><time>00:03:00</time></footer><details class="vp-det"><summary>値ごとの結果（6）</summary></details>` },
  K: { name: 'K 区切りの中に値の名前（太いバー。B＋Cを1本に）', row: () => `<div class="rp-live-top"><span class="rp-state">ファイル 2/6 済</span><time class="rp-elapsed">00:03:00</time></div>${segName()}<div class="rp-detail">DL2 · 変換・検証 · 8,312件</div>`,
   lane: () => `<header><b>ライン 1</b><span>ファイル 2/6 済</span></header><strong>設備単位実績</strong>${segName()}<footer><small>DL2 · 変換・検証</small><time>00:03:00</time></footer>` },
 };
 const CSS = `
  .pline div.vp-chips,.pline div.vp-two,.pline div.vp-e,.pline div.vp-steps,.pline div.vp-e>div{height:auto;background:none;overflow:visible;border-radius:0}
  .vp-seg{display:grid;grid-template-columns:repeat(${N},1fr);gap:3px;height:8px;margin:5px 0 3px}.vp-s{border-radius:3px;background:#dbe5e9}.vp-s.vp-ok{background:#20a37a}.vp-s.vp-run{background:linear-gradient(90deg,#1b8fa6 40%,#cfe7ec 40%)}.vp-s.vp-ng{background:#c9574c}
  .vp-chips{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}.vp-c{font-style:normal;font-size:10.5px;font-weight:800;padding:0 6px;border-radius:9px;background:#eef2f4;color:#7a8a92;display:inline-flex;gap:3px;align-items:center}
  .vp-c.vp-ok{background:#e5f5ef;color:#0a6b4c}.vp-c.vp-run{background:#e3f3f5;color:#14576a;outline:1px solid #8cc8d3}.vp-c.vp-ng{background:#fde7e4;color:#a5372c}
  .vp-two{display:grid;grid-template-columns:auto 1fr;gap:3px 6px;align-items:center;margin:4px 0}.vp-two small{font-size:10px;color:#647581}.vp-b2{background:#1d6f8f!important}
  .vp-e{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center}.vp-big{font:800 22px/1 "Yu Gothic UI",sans-serif;color:#14576a}.vp-big small{font-size:12px;color:#647581}
  .vp-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:3px;margin:5px 0}.vp-steps span{font-size:10px;text-align:center;padding:2px 0;border-radius:4px;background:#eef2f4;color:#7a8a92;font-weight:700}.vp-steps .done{background:#e5f5ef;color:#0a6b4c}.vp-steps .now{background:#1b8fa6;color:#fff}
  .pline div.vp-chips{height:auto}.vp-rest{font-size:10px;color:#647581;align-self:center;margin-left:2px}.vp-segn{height:16px}.vp-segn .vp-s{font:800 9.5px/16px "Yu Gothic UI",sans-serif;text-align:center;color:#62747c;overflow:hidden;white-space:nowrap}.vp-segn .vp-ok{color:#fff}.vp-segn .vp-run{color:#0d4b5a}.vp-det summary{font-size:10.5px;color:#14576a;font-weight:700;cursor:pointer}
  .vp-tbl{width:100%;border-collapse:collapse;font-size:11.5px;margin:6px 0}.vp-tbl td{padding:1px 6px;border-bottom:1px solid #e7edf0}.vp-tbl .vp-ok td:first-child{color:#0a6b4c}.vp-tbl .vp-run{background:#f0f8fa}.vp-tbl .vp-wait{color:#93a4ab}
 `;
 function style(css) { let s = document.getElementById('vp-style'); if (!s) { s = document.createElement('style'); s.id = 'vp-style'; document.head.appendChild(s) } s.textContent = CSS + (css || '') }
 window.VP = {
  V, ITEMS,
  show(k) {
   style(V[k].css); stopPolling();
   const live = document.querySelector('.rowprogress[data-jobid="lot"] .rp-live'); if (live) live.innerHTML = V[k].row();
   const lane = document.querySelector('#p-parallel-lines .pline'); if (lane) lane.innerHTML = V[k].lane();
   if (live) live.dataset.vp = k;
  },
 };
 // 撮るあいだ、画面の定期更新に上書きされないよう止める
 function stopPolling() { window.__vpFrozen = true; const id = setInterval(() => { }, 1e9); for (let i = 1; i < id; i++) clearInterval(i) }
})();
