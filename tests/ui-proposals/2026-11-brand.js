// 2.25.0 アイコンと起動画面の案（CLAUDE.md §3）。
// いま: アイコンは横棒3本と点（メニューの印に見え、データを運ぶ・繋ぐ働きを思わせない。20px では点が消える）。
// 起動画面は広い窓の中央に小さなカードだけ（製品の印が無い・全体の進み具合が無い・失敗のとき次の手が無い）。
// 1回目 A〜G（5案＋方向の違う2案 F・G）。案ごとに「アイコン＋起動画面」を1組にする。
// 撮り方: node shoot.mjs tests/ui-proposals/2026-11-brand.js <出力>（作業用の道具。§3「まだ無いもの」）。
// 起動画面は window.splash.step(id, state, detail) と window.splash.fail(title, detail) を受ける（desktop/src/main.rs が呼ぶ）。
// id は update・python・backend・open、state は now・ok・bad・wait・skip。

// ---- アイコン（viewBox 0 0 256 256。small は 32px 以下で使う太い版） ----
const BG = (r = 56, m = 8) => `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#143349"/><stop offset="1" stop-color="#0a87a0"/></linearGradient>
<linearGradient id="hl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>
<rect x="${m}" y="${m}" width="${256 - 2 * m}" height="${256 - 2 * m}" rx="${r}" fill="url(#g)"/><rect x="${m}" y="${m}" width="${256 - 2 * m}" height="${256 - 2 * m}" rx="${r}" fill="url(#hl)"/>`;
const svg = (body, small) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">${small ? BG(48, 0) : BG()}${body}</svg>`;
const MINT = '#5fe3d8';

const ICONS = {
 // 元（左）→ 中継（中央・青緑）→ 2つの出力（右）
 A: w => `<path d="M60 128H128M128 128C162 128 160 ${w ? 76 : 82} 196 ${w ? 76 : 82}M128 128C162 128 160 ${w ? 180 : 174} 196 ${w ? 180 : 174}" stroke="#fff" stroke-width="${w ? 24 : 14}" fill="none" stroke-linecap="round"/>
<circle cx="${w ? 56 : 60}" cy="128" r="${w ? 30 : 22}" fill="#fff"/><circle cx="128" cy="128" r="${w ? 28 : 21}" fill="${MINT}"/>
<circle cx="196" cy="${w ? 76 : 82}" r="${w ? 26 : 19}" fill="#fff"/><circle cx="196" cy="${w ? 180 : 174}" r="${w ? 26 : 19}" fill="#fff"/>`,
 // データの筒 → 弧の矢印 → 書類
 B: w => w ? `<path d="M40 84V172A52 18 0 0 0 144 172V84" fill="#fff"/><ellipse cx="92" cy="84" rx="52" ry="18" fill="#fff"/><path d="M40 120A52 18 0 0 0 144 120" stroke="#0e5f77" stroke-width="10" fill="none"/>
<path d="M164 128H214M190 102L216 128L190 154" stroke="${MINT}" stroke-width="24" fill="none" stroke-linecap="round" stroke-linejoin="round"/>` :
  `<path d="M44 92V170A40 14 0 0 0 124 170V92" fill="#fff"/><ellipse cx="84" cy="92" rx="40" ry="14" fill="#fff"/><path d="M44 118A40 14 0 0 0 124 118M44 144A40 14 0 0 0 124 144" stroke="#0e5f77" stroke-width="6" fill="none"/>
<path d="M150 112h44l20 20v68a6 6 0 0 1-6 6h-58a6 6 0 0 1-6-6v-82a6 6 0 0 1 6-6z" fill="#fff"/><path d="M194 112v20h20" fill="#cfe9ef"/><path d="M160 150h40M160 166h40M160 182h28" stroke="#0e5f77" stroke-width="6" stroke-linecap="round"/>
<path d="M92 66C120 34 170 40 184 92" stroke="${MINT}" stroke-width="12" fill="none" stroke-linecap="round"/><path d="M168 86L186 102L198 80" stroke="${MINT}" stroke-width="12" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
 // 表から矢印で送り出す（いまの横棒を引き継ぐ）
 C: w => w ? `<path d="M40 76h104M40 128h80M40 180h104" stroke="#fff" stroke-width="28" stroke-linecap="round"/>
<path d="M150 84L204 128L150 172" stroke="#0f3a52" stroke-width="44" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M150 84L204 128L150 172" stroke="${MINT}" stroke-width="26" fill="none" stroke-linecap="round" stroke-linejoin="round"/>` :
  `<rect x="44" y="60" width="124" height="136" rx="16" fill="#fff"/><path d="M60 60h92a16 16 0 0 1 16 16v16H44V76a16 16 0 0 1 16-16z" fill="#0f6a84"/>
<path d="M60 120h92M60 146h92M60 172h64" stroke="#b7d3dc" stroke-width="10" stroke-linecap="round"/>
<path d="M162 90L208 128L162 166" stroke="#0f3a52" stroke-width="40" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M162 90L208 128L162 166" stroke="${MINT}" stroke-width="22" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
 // D の字の中を矢印が通る
 D: w => `<path d="M${w ? 58 : 66} ${w ? 50 : 58}H124A${w ? 78 : 70} ${w ? 78 : 70} 0 0 1 124 ${w ? 206 : 198}H${w ? 58 : 66}Z" stroke="#fff" stroke-width="${w ? 28 : 22}" fill="none" stroke-linejoin="round"/>
<path d="M${w ? 86 : 94} 128H${w ? 160 : 154}M${w ? 132 : 130} ${w ? 100 : 104}L${w ? 160 : 154} 128L${w ? 132 : 130} ${w ? 156 : 152}" stroke="${MINT}" stroke-width="${w ? 24 : 18}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
 // 回る矢印（決めた時刻に繰り返す）と表
 E: w => `<path d="M171 ${w ? 52 : 58}A${w ? 88 : 80} ${w ? 88 : 80} 0 1 1 ${w ? 82 : 86} ${w ? 55 : 60}" stroke="${MINT}" stroke-width="${w ? 24 : 16}" fill="none" stroke-linecap="round"/>
<path d="M${w ? 49 : 57} ${w ? 42 : 52}L${w ? 82 : 86} ${w ? 55 : 60}L${w ? 73 : 78} ${w ? 88 : 89}" stroke="${MINT}" stroke-width="${w ? 24 : 16}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
${w ? '<path d="M96 108h64M96 148h64" stroke="#fff" stroke-width="24" stroke-linecap="round"/>' : '<path d="M96 104h64M96 128h48M96 152h64" stroke="#fff" stroke-width="16" stroke-linecap="round"/>'}`,
 // 点（データ）と二重の矢印（先へ送る）
 F: w => `<circle cx="${w ? 58 : 62}" cy="128" r="${w ? 30 : 24}" fill="#fff"/>
<path d="M${w ? 106 : 104} ${w ? 72 : 80}L${w ? 158 : 152} 128L${w ? 106 : 104} ${w ? 184 : 176}" stroke="#fff" stroke-width="${w ? 30 : 24}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M${w ? 156 : 152} ${w ? 72 : 80}L${w ? 208 : 200} 128L${w ? 156 : 152} ${w ? 184 : 176}" stroke="${MINT}" stroke-width="${w ? 30 : 24}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
 // 重なる層（データ）。いちばん下（出力）を青緑に
 G: w => `<path d="M128 ${w ? 44 : 52}L${w ? 214 : 204} ${w ? 92 : 94}L128 ${w ? 140 : 136}L${w ? 42 : 52} ${w ? 92 : 94}Z" fill="#fff"/>
<path d="M${w ? 42 : 52} ${w ? 136 : 132}L128 ${w ? 184 : 174}L${w ? 214 : 204} ${w ? 136 : 132}" stroke="#fff" stroke-width="${w ? 22 : 16}" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>
${w ? '' : `<path d="M52 170L128 212L204 170" stroke="${MINT}" stroke-width="16" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`}`,
};
const icon = k => ({ svg: svg(ICONS[k](false), false), small: svg(ICONS[k](true), true) });

// ---- 起動画面の共通の中身（工程の持ち方と、窓からの呼び口） ----
const STEPS = [
 { id: 'update', label: '配る版にそろえる', hint: '配布の置き場から写したアプリだけ、起動のたびに確かめます' },
 { id: 'python', label: 'Python を探す', hint: 'ブラウザ版と同じ Python を使います' },
 { id: 'backend', label: '中身を読み込む', hint: '' },
 { id: 'open', label: '画面を開く', hint: '' },
];
const CORE_JS = `
const STEPS=${JSON.stringify(STEPS)};
const S={};STEPS.forEach(s=>S[s.id]={state:'wait',detail:s.hint});S.update.state='now';
let FAIL=null;
const E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list=()=>STEPS.map(s=>({...s,...S[s.id]}));
const done=()=>list().filter(s=>s.state==='ok'||s.state==='skip').length;
const current=()=>list().find(s=>s.state==='bad')||list().find(s=>s.state==='now')||list().find(s=>s.state==='wait');
const ICO={ok:'<svg viewBox="0 0 20 20"><path d="M5 10.5l3.2 3.2L15 6.8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 bad:'<svg viewBox="0 0 20 20"><path d="M10 5.5v5.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="10" cy="14.6" r="1.5" fill="currentColor"/></svg>',
 now:'<svg viewBox="0 0 20 20" class="spin"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="2.4"/><path d="M10 3a7 7 0 0 1 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
 wait:'<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="6" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
 skip:'<svg viewBox="0 0 20 20"><path d="M6 10h8" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>'};
function copyFail(b){try{navigator.clipboard.writeText(FAIL.title+'\\n'+FAIL.detail);b.textContent='写しました';}catch(e){b.textContent='写せませんでした';}}
function view(){render(list(),FAIL);}
window.splash={step(id,state,detail){if(!S[id])return;S[id].state=state;if(detail!==undefined)S[id].detail=detail;view();},fail(title,detail){FAIL={title,detail};view();}};
`;
const BASE_CSS = `:root{--navy:#17384e;--blue:#087c98;--blue2:#075f78;--teal:#16a0a4;--mint:#5fe3d8;--ok:#087a57;--bad:#b93b32;--muted:#5d6f7a;--line:#d7e0e5;--soft:#f3f6f8}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;font-family:"Yu Gothic UI",Meiryo,sans-serif;color:var(--navy)}
.spin{animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}svg.spin{transform-origin:50% 50%}
.copy{font:inherit;font-size:12px;font-weight:700;border:1px solid #e3b5b0;background:#fff;color:var(--bad);border-radius:7px;padding:6px 12px;cursor:pointer}`;
const page = (css, body, renderJs) => `<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>DataRelay</title><style>${BASE_CSS}${css}</style></head>
<body>${body}<script>${CORE_JS}${renderJs};view();</script></body></html>`;
const inline = (k, size) => svg(ICONS[k](size <= 32), size <= 32).replace('<svg ', `<svg width="${size}" height="${size}" aria-hidden="true" `).replace(/id="(g|hl)"/g, `id="$1${k}${size}"`).replace(/url\(#(g|hl)\)/g, `url(#$1${k}${size})`);
const failBox = cls => `(f?\`<div class="${cls}"><div class="fh"><b>\${E(f.title)}</b><button class="copy" onclick="copyFail(this)">内容を写す</button></div><pre>\${E(f.detail)}</pre><p>直したら、アプリを開き直してください。</p></div>\`:'')`;
const TAG = 'Navigator のデータを、決めた時刻に、決めた形で届けます';

const SPLASH = {
 // A: 中央に大きく。名前と働き → 全体の進み具合 → 工程の札
 A: page(`body{display:grid;place-items:center;background:radial-gradient(1200px 700px at 50% 38%,#e8f6f8,#f3f6f8 60%,#eef2f4)}
.wrap{width:min(620px,90vw);text-align:center}.logo{filter:drop-shadow(0 14px 28px #0a5a7033)}
h1{margin:18px 0 4px;font-size:34px;letter-spacing:.01em}.tag{margin:0 0 30px;color:var(--muted);font-size:14px}
.bar{height:8px;border-radius:8px;background:#dfe9ed;overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,#0c839e,#20b5aa);border-radius:8px;transition:width .4s}
.bar.bad i{background:var(--bad)}.now{display:flex;justify-content:space-between;margin:10px 2px 18px;font-size:13px;color:var(--muted)}.now b{color:var(--navy)}
.chips{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.chip{display:flex;align-items:center;gap:6px;justify-content:center;padding:8px 6px;border-radius:9px;background:#fff;border:1px solid var(--line);font-size:12px;color:var(--muted)}
.chip svg{width:16px;height:16px;flex:none}.chip.ok{color:var(--ok);border-color:#cce8db}.chip.now{color:var(--blue2);border-color:#9cd5db;background:#eaf6f8;font-weight:700}.chip.bad{color:var(--bad);border-color:#efc4bf;background:#fff1ef;font-weight:700}
.fail{margin-top:18px;text-align:left;background:#fff;border:1px solid #efc4bf;border-left:4px solid var(--bad);border-radius:10px;padding:14px 16px}.fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fh b{color:var(--bad);font-size:15px}
.fail pre{margin:10px 0 6px;padding:10px 12px;background:#fbf4f3;border-radius:7px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#5c2a25}.fail p{margin:0;font-size:12px;color:var(--muted)}`,
  `<div class="wrap"><div class="logo">${inline('A', 104)}</div><h1>DataRelay</h1><p class="tag">${TAG}</p><div id="r"></div></div>`,
  `function render(l,f){const c=current();const n=done();const bad=l.some(s=>s.state==='bad');
document.getElementById('r').innerHTML=\`<div class="bar \${bad?'bad':''}"><i style="width:\${Math.max(6,(n+(c&&c.state==='now'?.5:0))/l.length*100)}%"></i></div>
<div class="now"><span><b>\${E(c?c.label:'')}</b>　\${E(c?c.detail:'')}</span><span>\${n} / \${l.length}</span></div>
<div class="chips">\${l.map(s=>\`<div class="chip \${s.state}">\${ICO[s.state]||ICO.wait}\${E(s.label)}</div>\`).join('')}</div>\${${failBox('fail')}}\`}`),

 // B: 左に名前の面、右に工程の時間軸
 B: page(`body{display:grid;grid-template-columns:minmax(380px,40%) 1fr;background:#f3f6f8}
.side{background:linear-gradient(150deg,#123047,#0a7f98);color:#fff;display:flex;flex-direction:column;justify-content:center;padding:0 7vw}
.side h1{margin:22px 0 8px;font-size:38px}.side p{margin:0;font-size:15px;line-height:1.7;opacity:.85;max-width:330px}
.main{display:flex;align-items:center;justify-content:center;padding:40px}.box{width:min(560px,100%)}
.box h2{margin:0 0 4px;font-size:20px}.box .sub{margin:0 0 22px;color:var(--muted);font-size:13px}
ol{list-style:none;margin:0;padding:0}li{display:grid;grid-template-columns:30px 1fr;gap:14px;position:relative;padding-bottom:22px;color:var(--muted)}
li:before{content:'';position:absolute;left:14px;top:30px;bottom:2px;width:2px;background:#d7e2e7}li:last-child:before{display:none}
li .d{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:#fff;border:2px solid #cdd9df}li .d svg{width:18px;height:18px}
li b{display:block;font-size:15px;color:var(--navy);margin-top:4px}li small{display:block;font-size:12px;margin-top:3px;word-break:break-all}
li.ok .d{background:var(--ok);border-color:var(--ok);color:#fff}li.ok:before{background:var(--ok)}li.now .d{border-color:var(--blue);color:var(--blue)}li.now b{color:var(--blue2)}
li.bad .d{background:var(--bad);border-color:var(--bad);color:#fff}li.bad b,li.bad small{color:var(--bad)}li.skip .d{border-style:dashed}
.fail{margin-top:6px;background:#fff;border:1px solid #efc4bf;border-left:4px solid var(--bad);border-radius:10px;padding:14px 16px}.fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fh b{color:var(--bad);font-size:15px}
.fail pre{margin:10px 0 6px;padding:10px 12px;background:#fbf4f3;border-radius:7px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#5c2a25}.fail p{margin:0;font-size:12px;color:var(--muted)}`,
  `<div class="side">${inline('B', 112)}<h1>DataRelay</h1><p>${TAG}</p></div><div class="main"><div class="box"><h2>起動しています</h2><p class="sub" id="sub"></p><ol id="r"></ol><div id="f"></div></div></div>`,
  `function render(l,f){const n=done();document.getElementById('sub').textContent=l.some(s=>s.state==='bad')?'起動を止めました。下の内容を確かめてください':\`4つのうち \${n} つ済みました\`;
document.getElementById('r').innerHTML=l.map(s=>\`<li class="\${s.state}"><span class="d">\${ICO[s.state]||''}</span><div><b>\${E(s.label)}</b><small>\${E(s.detail)}</small></div></li>\`).join('');
document.getElementById('f').innerHTML=${failBox('fail')}}`),

 // C: 横に4つの駅が並ぶ中継の線路
 C: page(`body{display:grid;place-items:center;background:linear-gradient(180deg,#eef4f6,#f6f8f9)}
.card{width:min(820px,90vw);background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:0 24px 60px #15384d1c;padding:34px 40px 30px}
.head{display:flex;align-items:center;gap:16px}.head h1{margin:0;font-size:28px}.head p{margin:2px 0 0;color:var(--muted);font-size:13px}
.track{display:grid;grid-template-columns:repeat(4,1fr);margin:34px 0 22px;position:relative}
.track:before{content:'';position:absolute;left:12.5%;right:12.5%;top:17px;height:4px;background:#e1eaee;border-radius:4px}
.track .fill{position:absolute;left:12.5%;top:17px;height:4px;background:linear-gradient(90deg,#0c839e,#20b5aa);border-radius:4px;transition:width .4s}
.st{text-align:center;position:relative;color:var(--muted);font-size:13px}.st .d{width:38px;height:38px;margin:0 auto 10px;border-radius:50%;display:grid;place-items:center;background:#fff;border:3px solid #cfdbe1}.st .d svg{width:20px;height:20px}
.st.ok .d{background:var(--ok);border-color:var(--ok);color:#fff}.st.ok{color:var(--ok)}.st.now .d{border-color:var(--blue);color:var(--blue)}.st.now{color:var(--blue2);font-weight:700}
.st.bad .d{background:var(--bad);border-color:var(--bad);color:#fff}.st.bad{color:var(--bad);font-weight:700}.st.skip .d{border-style:dashed}
.detail{background:#f3f8fa;border-radius:10px;padding:12px 16px;font-size:13px;color:var(--muted);word-break:break-all}.detail b{color:var(--navy);margin-right:8px}
.fail{margin-top:14px;border:1px solid #efc4bf;border-left:4px solid var(--bad);border-radius:10px;padding:14px 16px;background:#fff8f7}.fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fh b{color:var(--bad);font-size:15px}
.fail pre{margin:10px 0 6px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#5c2a25}.fail p{margin:0;font-size:12px;color:var(--muted)}`,
  `<div class="card"><div class="head">${inline('C', 64)}<div><h1>DataRelay</h1><p>${TAG}</p></div></div><div id="r"></div></div>`,
  `function render(l,f){const c=current();const n=done();const last=l.reduce((a,s,i)=>s.state!=='wait'?i:a,0);
document.getElementById('r').innerHTML=\`<div class="track"><div class="fill" style="width:\${last/(l.length-1)*75}%"></div>\${l.map(s=>\`<div class="st \${s.state}"><div class="d">\${ICO[s.state]||''}</div>\${E(s.label)}</div>\`).join('')}</div>
<div class="detail"><b>\${E(c?c.label:'')}</b>\${E(c?c.detail:'')}</div>\${${failBox('fail')}}\`}`),

 // D: 今のカードを磨く（名前の頭にアイコン・全体の進み具合・状態の印を図に）
 D: page(`body{display:grid;place-items:center;background:#eef3f5}
.card{width:min(640px,90vw);background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 20px 56px #15384d1f;overflow:hidden}
.top{height:4px;background:#e3ebee}.top i{display:block;height:100%;background:linear-gradient(90deg,#0c839e,#20b5aa);transition:width .4s}.top.bad i{background:var(--bad)}
.in{padding:26px 30px}.head{display:flex;align-items:center;gap:14px;margin-bottom:20px}.head h1{margin:0;font-size:24px}.head p{margin:2px 0 0;color:var(--muted);font-size:12px}
ol{list-style:none;margin:0;padding:0;display:grid;gap:8px}li{display:grid;grid-template-columns:24px 1fr;gap:12px;align-items:start;padding:11px 14px;border:1px solid var(--line);border-radius:10px;color:var(--muted);font-size:13px}
li svg{width:20px;height:20px;margin-top:1px}li b{display:block;color:var(--navy)}li small{display:block;font-size:12px;margin-top:2px;word-break:break-all}
li.ok{color:var(--ok);border-color:#cce8db;background:#f2faf6}li.ok b{color:var(--ok)}li.now{color:var(--blue2);border-color:#9cd5db;background:#eef8fa}li.now b{color:var(--blue2)}
li.bad{color:var(--bad);border-color:#efc4bf;background:#fff4f2}li.bad b{color:var(--bad)}li.skip{border-style:dashed}
.fail{margin-top:14px;border-left:4px solid var(--bad);border-radius:8px;padding:12px 14px;background:#fff4f2}.fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fh b{color:var(--bad)}
.fail pre{margin:8px 0 6px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#5c2a25}.fail p{margin:0;font-size:12px;color:var(--muted)}`,
  `<div class="card"><div class="top" id="top"><i></i></div><div class="in"><div class="head">${inline('D', 52)}<div><h1>DataRelay</h1><p id="sub"></p></div></div><ol id="r"></ol><div id="f"></div></div></div>`,
  `function render(l,f){const n=done();const bad=l.some(s=>s.state==='bad');const t=document.getElementById('top');t.className='top'+(bad?' bad':'');t.firstChild.style.width=Math.max(4,n/l.length*100)+'%';
document.getElementById('sub').textContent=bad?'起動を止めました':\`起動しています（\${n} / \${l.length}）\`;
document.getElementById('r').innerHTML=l.map(s=>\`<li class="\${s.state}">\${ICO[s.state]||''}<div><b>\${E(s.label)}</b>\${s.detail?\`<small>\${E(s.detail)}</small>\`:''}</div></li>\`).join('');
document.getElementById('f').innerHTML=${failBox('fail')}}`),

 // E: 暗い全面（流れる線を背景に）
 E: page(`body{display:grid;place-items:center;background:radial-gradient(1100px 700px at 50% 30%,#164a63,#0b2232 70%);color:#e9f4f7}
body:before{content:'';position:fixed;inset:0;background:repeating-linear-gradient(115deg,transparent 0 46px,#ffffff08 46px 47px)}
.wrap{position:relative;width:min(560px,90vw);text-align:center}h1{margin:18px 0 4px;font-size:32px;color:#fff}.tag{margin:0 0 28px;color:#a9c6d0;font-size:14px}
.glass{text-align:left;background:#ffffff10;border:1px solid #ffffff22;border-radius:14px;padding:8px;backdrop-filter:blur(6px)}
.row{display:grid;grid-template-columns:24px 1fr;gap:12px;padding:10px 12px;border-radius:9px;color:#9fb9c3;font-size:13px}.row svg{width:20px;height:20px}
.row b{display:block;color:#e9f4f7}.row small{display:block;font-size:12px;margin-top:2px;word-break:break-all}
.row.ok{color:#6ee0b6}.row.now{background:#ffffff14;color:var(--mint)}.row.bad{background:#b93b3233;color:#ff9d93}.row.bad b{color:#ffc4bd}
.fail{margin-top:14px;text-align:left;background:#2a1517;border:1px solid #b93b3299;border-radius:12px;padding:14px 16px}.fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fh b{color:#ffb3aa}
.fail pre{margin:10px 0 6px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#f2d4d0}.fail p{margin:0;font-size:12px;color:#c9a3a0}.copy{background:transparent;color:#ffb3aa;border-color:#b93b32}`,
  `<div class="wrap">${inline('E', 96)}<h1>DataRelay</h1><p class="tag">${TAG}</p><div class="glass" id="r"></div><div id="f"></div></div>`,
  `function render(l,f){document.getElementById('r').innerHTML=l.map(s=>\`<div class="row \${s.state}">\${ICO[s.state]||''}<div><b>\${E(s.label)}</b>\${s.detail?\`<small>\${E(s.detail)}</small>\`:''}</div></div>\`).join('');
document.getElementById('f').innerHTML=${failBox('fail')}}`),

 // F（方向の違う案）: 既定は1行だけ。問題が起きたときだけ、どこで止まったかと次の手を出す
 F: page(`body{display:grid;place-items:center;background:#f4f7f8}
.wrap{width:min(560px,90vw);text-align:center}h1{margin:16px 0 26px;font-size:28px}
.line{display:inline-flex;align-items:center;gap:10px;font-size:14px;color:var(--muted)}.line svg{width:18px;height:18px;color:var(--blue)}
.thin{width:220px;height:3px;margin:14px auto 0;background:#e0e8eb;border-radius:3px;overflow:hidden;position:relative}.thin i{position:absolute;inset:0;width:40%;background:var(--teal);border-radius:3px;animation:mv 1.3s ease-in-out infinite}
@keyframes mv{0%{left:-40%}100%{left:100%}}
.prob{margin-top:22px;text-align:left;background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 18px 50px #15384d18;padding:18px 20px}
.prob h2{margin:0 0 12px;font-size:16px;color:var(--bad)}.steps{display:flex;gap:6px;margin-bottom:14px}.steps span{flex:1;display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted);padding:6px 8px;border-radius:7px;background:#f3f6f8}
.steps svg{width:14px;height:14px;flex:none}.steps .ok{color:var(--ok)}.steps .bad{color:var(--bad);background:#fff1ef;font-weight:700}
.fail .fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fail .fh b{font-size:14px}.fail pre{margin:8px 0 6px;padding:10px 12px;background:#f6f8f9;border-radius:7px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#3b4b55}.fail p{margin:0;font-size:12px;color:var(--muted)}`,
  `<div class="wrap">${inline('F', 92)}<h1>DataRelay</h1><div id="r"></div></div>`,
  `function render(l,f){const c=current();const bad=l.find(s=>s.state==='bad');const r=document.getElementById('r');
if(!bad&&!f){r.innerHTML=\`<div class="line">\${ICO.now}\${E(c?c.label:'')}しています…</div><div class="thin"><i></i></div>\`;return;}
r.innerHTML=\`<div class="prob"><h2>\${E(bad?bad.label:'起動')}で止まりました</h2><div class="steps">\${l.map(s=>\`<span class="\${s.state}">\${ICO[s.state]||''}\${E(s.label)}</span>\`).join('')}</div>\${${failBox('fail')}}</div>\`}`),

 // G（方向の違う案）: アプリの画面の骨組みを先に出し、そのまま本物の画面へ続ける。進み具合は帯の右に
 G: page(`body{background:#f3f6f8}
.appbar{height:68px;background:linear-gradient(115deg,#153247,#1e6079);color:#fff;display:flex;align-items:center;gap:12px;padding:0 max(22px,calc((100vw - 1580px)/2))}
.appbar h1{margin:0;font-size:22px}.pill{margin-left:auto;display:flex;align-items:center;gap:10px;background:#ffffff14;border:1px solid #ffffff38;border-radius:9px;padding:7px 14px;font-size:12px}
.pill svg{width:18px;height:18px;color:var(--mint)}.pill b{display:block;font-size:13px}.pill span{opacity:.8}
main{max-width:1580px;margin:0 auto;padding:0 22px}.nav{display:flex;gap:28px;border-bottom:1px solid var(--line);padding:16px 4px 10px;margin-bottom:14px}.nav i,.sk{display:block;background:linear-gradient(90deg,#e4ebee,#eff4f6,#e4ebee);background-size:200% 100%;animation:sh 1.6s linear infinite;border-radius:6px}
.nav i{width:96px;height:14px}@keyframes sh{to{background-position:-200% 0}}
.table{background:#fff;border:1px solid var(--line);border-radius:9px;padding:14px}.tr{display:grid;grid-template-columns:40px 1.2fr 1fr 1fr 2fr 160px;gap:18px;padding:14px 4px;border-bottom:1px solid #edf1f3}.tr .sk{height:12px}
.over{position:fixed;left:50%;top:52%;transform:translate(-50%,-50%);width:min(560px,90vw);background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 24px 70px #15384d2e;padding:18px 20px}
.over .st{display:flex;gap:6px}.over .st span{flex:1;display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);padding:8px;border-radius:8px;background:#f3f6f8}.over svg{width:16px;height:16px;flex:none}
.over .ok{color:var(--ok)}.over .now{color:var(--blue2);background:#eaf6f8;font-weight:700}.over .bad{color:var(--bad);background:#fff1ef;font-weight:700}
.over .msg{margin-top:12px;font-size:13px;color:var(--muted);word-break:break-all}.over .msg b{color:var(--navy);margin-right:8px}
.fail{margin-top:12px;border-left:4px solid var(--bad);border-radius:8px;padding:12px 14px;background:#fff4f2}.fh{display:flex;justify-content:space-between;align-items:center;gap:10px}.fh b{color:var(--bad)}
.fail pre{margin:8px 0 6px;white-space:pre-wrap;word-break:break-all;font:12px/1.6 Consolas,"Yu Gothic UI",monospace;color:#5c2a25}.fail p{margin:0;font-size:12px;color:var(--muted)}`,
  `<header class="appbar">${inline('G', 36)}<h1>DataRelay</h1><div class="pill" id="pill"></div></header>
<main><div class="nav"><i></i><i></i><i></i><i></i><i></i></div><div class="table">${Array.from({ length: 9 }, () => '<div class="tr"><i class="sk"></i><i class="sk"></i><i class="sk"></i><i class="sk"></i><i class="sk"></i><i class="sk"></i></div>').join('')}</div></main>
<div class="over" id="r"></div>`,
  `function render(l,f){const c=current();const n=done();document.getElementById('pill').innerHTML=\`\${ICO[c&&c.state==='bad'?'bad':'now']}<div><b>\${c&&c.state==='bad'?'起動を止めました':'起動しています'}</b><span>\${n} / \${l.length}　\${E(c?c.label:'')}</span></div>\`;
document.getElementById('r').innerHTML=\`<div class="st">\${l.map(s=>\`<span class="\${s.state}">\${ICO[s.state]||''}\${E(s.label)}</span>\`).join('')}</div><div class="msg"><b>\${E(c?c.label:'')}</b>\${E(c?c.detail:'')}</div>\${${failBox('fail')}}\`}`),
};

const NAMES = {
 A: ['中継の点 ＋ 中央に大きく', 'アイコン: 元→中継→2つの出力に分かれる線。起動画面: 大きなアイコンと名前・働きの一言、全体の進み具合の帯、工程の札4つ'],
 B: ['筒から書類へ ＋ 左右に分ける', 'アイコン: データの筒から書類へ渡す矢印。起動画面: 左に名前の面（紺）、右に工程の時間軸'],
 C: ['表から送り出す ＋ 中継の線路', 'アイコン: 表（いまの横棒を引き継ぐ）から矢印で送り出す。起動画面: 4つの駅が横に並ぶ線路と、いまの工程の説明'],
 D: ['D と矢印 ＋ 今のカードを磨く', 'アイコン: D の字の中を矢印が通る。起動画面: いまのカードに、アイコン・全体の進み具合の帯・図の状態の印を足す'],
 E: ['回る矢印と表 ＋ 暗い全面', 'アイコン: 決めた時刻に繰り返す回る矢印と表。起動画面: 暗い全面と、半透明の工程の一覧'],
 F: ['点と二重の矢印 ＋ 既定は1行（方向の違う案）', '既定で済ませて例外だけ出す: ふだんは「いま何をしているか」の1行と細い帯だけ。止まったときだけ、どこで止まったか・内容・写すボタンを出す'],
 G: ['重なる層 ＋ 画面の骨組み（方向の違う案）', '手順を画面に続ける: 本物の画面の帯と骨組みを先に出し、進み具合は帯の右と中央の小窓。開き終わると、そのまま本物の画面に替わる'],
};

module.exports = Object.fromEntries(Object.keys(SPLASH).map(k => [k, { name: NAMES[k][0], idea: NAMES[k][1], icon: icon(k), splash: SPLASH[k] }]));
module.exports._parts = { ICONS, SPLASH, STEPS, svg, icon, page, inline, failBox, TAG, BASE_CSS, CORE_JS };
