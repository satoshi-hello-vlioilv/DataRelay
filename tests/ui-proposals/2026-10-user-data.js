// 2.3.0 ユーザーごとのデータ（共通設定 → 配布と更新）の案（CLAUDE.md §3）。
// いま: 見出しの説明は「設定は各PCの手元（写しの data）」のまま。「このPC」の札の「データの基準」は道が末尾で切れ、誰のデータか・
// どこにあるかが分からない。ユーザーの置き場を変える所が無い。
// 本物の画面の「このPC」の段のすぐ下に、案ごとの段を差し込む。中身は撮影用の環境の /api/users-root の実の値。
// 撮り方: window.UD.show(k)。1回目 A〜G（5案＋方向の違う2案 F・G）、2回目は組合せ案 H〜K。
(() => {
 const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
 const tail = (p, n = 3) => { const a = String(p || '').split(/[\\/]/).filter(Boolean); return (a.length > n ? '…\\' : '') + a.slice(-n).join('\\') };
 const CSS = `
  .ud{display:grid;gap:10px}
  .ud .facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
  .ud .fact{border:1px solid #dce6ea;border-radius:9px;background:#fff;padding:9px 12px;display:grid;gap:3px;min-width:0}
  .ud .fact small{font-size:11px;color:#6b7f88;font-weight:800}.ud .fact b{font-size:13.5px;color:#17384e;overflow-wrap:anywhere}
  .ud .fact code{font-size:11.5px;color:#27434f;overflow-wrap:anywhere}
  .ud .ok{color:#087a57}.ud .warn{color:#8a5a0c}
  .ud .pill{display:inline-flex;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:800;background:#e2f4ec;color:#087a57}
  .ud .row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .ud .line{display:flex;align-items:center;gap:12px;padding:10px 13px;border:1px solid #cce8db;background:#f2faf6;border-radius:9px;flex-wrap:wrap}
  .ud .line p{margin:0;font-size:12.5px;color:#2f4a55;flex:1;min-width:280px}
  .ud .form{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto;gap:8px;align-items:center}
  .ud .form input{height:35px;border:1px solid #c8d6dc;border-radius:8px;padding:0 10px;font:inherit;min-width:0}
  .ud details{border:1px solid #dce6ea;border-radius:9px;background:#fbfdfd;padding:8px 12px}.ud summary{cursor:pointer;font-weight:800;font-size:12.5px;color:#17384e}
  .ud table{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff;border:1px solid #dce6ea;border-radius:9px;overflow:hidden}
  .ud th,.ud td{padding:7px 12px;border-top:1px solid #edf1f2;text-align:left}.ud thead th{border-top:0;background:#f0f5f6;color:#4d6670;font-size:11.5px}
  .ud tr.me td{background:#eef7f9;font-weight:800}
  .ud .steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;counter-reset:s}
  .ud .step{border:1px solid #dce6ea;border-radius:9px;padding:10px 12px;background:#fff;font-size:12.5px;color:#2f4a55}
  .ud .step b{display:block;color:#17384e;margin-bottom:3px}.ud .step b::before{counter-increment:s;content:counter(s) '. ';color:#0b6577}
  .ud .note{font-size:12px;color:#5b6f79;margin:0}
  .ud .two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
  .ud .card{border:1px solid #dce6ea;border-radius:10px;padding:11px 13px;background:#fff;display:grid;gap:6px;align-content:start;min-width:0}
  .ud .card h4{margin:0;font-size:13px;color:#17384e}
  .ud .big{font-size:15px;font-weight:800;color:#17384e}
  .ud .crumb{display:inline-flex;border:1px solid #d4e0e5;border-radius:6px;overflow:hidden;font-size:12px;max-width:100%}
  .ud .crumb b{padding:2px 8px;background:#e3f1f4;color:#0b6577;white-space:nowrap}.ud .crumb span{padding:2px 8px;background:#fff;font-family:Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  @media(max-width:1100px){.ud .facts,.ud .steps,.ud .two{grid-template-columns:1fr}}`;
 const form = (x, label = 'この置き場にする') => `<div class="form"><input value="${E(x.configured)}" placeholder="空なら既定（${E(tail(x.defaultRoot, 2))}）"><button type="button" class="browse-btn">参照</button><button type="button">${label}</button><button type="button" class="secondary">既定に戻す</button></div>`;
 const state = x => x.inUse ? `<span class="pill">このデータで動いています</span>` : `<span class="pill" style="background:#fbf0dc;color:#8a5a0c">置き場が届かないので、このPCの写しの data を使っています</span>`;
 const V = {
  A: { name: 'A 事実の札3枚＋畳んだ「置き場を変える」', html: x => `<div class="ud"><div class="facts">
    <div class="fact"><small>あなた（Windows のログオン名）</small><b>${E(x.name)}</b></div>
    <div class="fact"><small>あなたのデータ</small><code>${E(x.mine)}</code></div>
    <div class="fact"><small>状態</small><b class="ok">${x.inUse ? 'このデータで動いています' : '写しの data を使っています'}</b></div></div>
    <details><summary>ユーザーの置き場を変える（全員の分が並ぶフォルダー）</summary><div style="margin-top:8px">${form(x)}</div></details></div>` },
  B: { name: 'B 1行の要約＋「変える」で開く', html: x => `<div class="ud"><div class="line"><p><b>${E(x.name)}</b> さんのデータは共有にあります: <code>${E(x.mine)}</code>。PC が変わっても、共有からインストールすればこのデータで起動します。</p><button type="button" class="secondary">置き場を変える</button></div></div>` },
  C: { name: 'C 入力欄を常に出す', html: x => `<div class="ud"><label class="stacked-field"><span>ユーザーの置き場（全員の分が並ぶ・全PCが同じ値を見る）</span>${form(x)}</label><p class="note">あなたのデータ: <code>${E(x.mine)}</code>　${state(x)}</p></div>` },
  D: { name: 'D 登録している人の一覧', html: x => `<div class="ud"><div class="row"><b style="font-size:13px">ユーザーの置き場</b><code>${E(x.root)}</code><button type="button" class="secondary">変える</button></div>
    <table><thead><tr><th>ログオン名</th><th>フォルダー</th></tr></thead><tbody>${x.users.map(u => `<tr class="${u === x.name ? 'me' : ''}"><td>${E(u)}${u === x.name ? '（あなた）' : ''}</td><td><code>${E(tail(x.root + '\\' + u, 3))}</code></td></tr>`).join('')}</tbody></table></div>` },
  E: { name: 'E 2つの札（あなたのデータ／全員の置き場）', html: x => `<div class="ud"><div class="two">
    <div class="card"><h4>あなたのデータ</h4><div class="big">${E(x.name)}</div><code style="font-size:11.5px;overflow-wrap:anywhere">${E(x.mine)}</code>${state(x)}</div>
    <div class="card"><h4>ユーザーの置き場（全員共通）</h4><code style="font-size:11.5px;overflow-wrap:anywhere">${E(x.root)}</code><small style="color:#5b6f79">${x.users.length}人分のデータが並んでいます</small>${form(x, '変える')}</div></div></div>` },
  F: { name: 'F 既定は黙り、変える所は「置き場を変える」の中', html: x => `<div class="ud"><p class="note">✓ あなたのデータ（${E(x.name)}）は共有にあります。PC が変わっても、そのまま使えます。</p></div>`, extra: x => form(x) },
  G: { name: 'G PC を替えるときの手順として見せる', html: x => `<div class="ud"><div class="steps">
    <div class="step"><b>新しいPCで共有の DataRelay.exe を開く</b>入口: <code>${E(tail(x.root, 3).replace(/\\users$/, '') + '\\DataRelay.exe')}</code></div>
    <div class="step"><b>自動で写して起動</b><code>${E(tail(x.mine, 3))}</code> のデータで開きます</div>
    <div class="step"><b>接続情報を1回だけ入れ直す</b>パスワードはPCごとの保護領域にあるため</div></div>
    <details><summary>ユーザーの置き場を変える</summary><div style="margin-top:8px">${form(x)}</div></details></div>` },
 };
 // ---- 2回目: 組合せ案
 Object.assign(V, {
  H: { name: 'H 2つの札＋変える所は畳む（E+A）', html: x => `<div class="ud"><div class="two">
    <div class="card"><h4>あなたのデータ</h4><div class="big">${E(x.name)}</div><code style="font-size:11.5px;overflow-wrap:anywhere">${E(x.mine)}</code>${state(x)}</div>
    <div class="card"><h4>ユーザーの置き場（全員共通）</h4><code style="font-size:11.5px;overflow-wrap:anywhere">${E(x.root)}</code><small style="color:#5b6f79">${x.users.length}人分のデータ・PC が変わっても共有からインストールすればそのまま</small></div></div>
    <details><summary>ユーザーの置き場を変える</summary><div style="margin-top:8px">${form(x)}<p class="note" style="margin-top:6px">いまある全員のフォルダーを新しい置き場へ写します（元は残します）。開き直すと新しい置き場を使います。</p></div></details></div>` },
  I: { name: 'I 1行の要約＋手順の3つ（B+G）', html: x => `<div class="ud"><div class="line"><p><b>${E(x.name)}</b> さんのデータ: <code>${E(x.mine)}</code></p>${state(x)}<button type="button" class="secondary">置き場を変える</button></div>
    <div class="steps"><div class="step"><b>共有の DataRelay.exe を開く</b>新しいPCで</div><div class="step"><b>自動で写して起動</b>このデータで開きます</div><div class="step"><b>接続情報を入れ直す</b>1回だけ</div></div></div>` },
  J: { name: 'J 事実の札＋人の一覧は畳む（A+D）', html: x => `<div class="ud"><div class="facts">
    <div class="fact"><small>あなた</small><b>${E(x.name)}</b></div><div class="fact"><small>あなたのデータ</small><code>${E(x.mine)}</code></div><div class="fact"><small>状態</small><b class="ok">${x.inUse ? 'このデータで動いています' : '写しの data'}</b></div></div>
    <details><summary>ユーザーの置き場（${x.users.length}人）・変える</summary><div style="margin-top:8px;display:grid;gap:8px"><code>${E(x.root)}</code>${form(x)}</div></details></div>` },
  K: { name: 'K 基準の札で道を見せる＋畳む（E+パスの札）', html: x => `<div class="ud"><div class="line" style="background:#fff;border-color:#dce6ea"><p style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>${E(x.name)}</b><span class="crumb"><b>ユーザーの置き場</b><span>\\${E(x.name)}</span></span>${state(x)}</p></div>
    <details><summary>ユーザーの置き場を変える（いま: ${E(tail(x.root, 3))}）</summary><div style="margin-top:8px">${form(x)}</div></details></div>` },
 });
 window.UD = { V, show: async k => {
  const x = window.__UD || (window.__UD = await fetch('/api/users-root').then(r => r.json()));
  let st = document.getElementById('ud-style'); if (!st) { st = document.createElement('style'); st.id = 'ud-style'; document.head.appendChild(st) } st.textContent = CSS;
  document.getElementById('ud-block')?.remove(); document.getElementById('ud-extra')?.remove();
  const here = document.querySelector('article[data-cat="release"] .rel-block');
  here.insertAdjacentHTML('afterend', `<div class="settings-block rel-block" id="ud-block"><span class="settings-subhead">ユーザーごとのデータ</span>${V[k].html(x)}</div>`);
  if (V[k].extra) { const d = document.querySelector('article[data-cat="release"] details.rel-dir .rel-dir-body'); if (d) d.insertAdjacentHTML('beforeend', `<div id="ud-extra" style="margin-top:12px"><label class="stacked-field"><span>ユーザーの置き場</span></label>${V[k].extra(x)}</div>`) }
  const head = document.querySelector('article[data-cat="release"] .panelhead p');
  if (head && !head.dataset.ud) { head.dataset.ud = 1; head.textContent = '各PCはアプリを自分のPCへ写して動かし、起動のたびに「配る版」へそろえます。設定（対象・予定・RNE・共通設定）は共有のユーザーのフォルダーにあり、PC が変わっても共有からインストールすればそのまま使えます。' }
  window.scrollTo(0, 0);
 } };
})();
