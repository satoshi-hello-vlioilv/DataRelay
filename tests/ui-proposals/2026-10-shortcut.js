// 起動アイコン欄の5案。いまの画面の #sc-block の中身を、案ごとの DOM と CSS に組み替えて再現する（同じ scState を使う）。
window.SC_VARIANTS = {
 A: { name: 'A 場所ごとの札（いまの実装）', css: '', html: null },
 B: { name: 'B 一覧の行', css: `
  .vB{border:1px solid #dce6ea;border-radius:9px;background:#fff;overflow:hidden}
  .vB>div{display:grid;grid-template-columns:150px 1fr auto;align-items:center;gap:12px;padding:9px 12px;border-top:1px solid #e7edf0}
  .vB>div:first-child{border-top:0}.vB b{font-size:13px;color:#203f4d}
  .vB span{font-size:12px;color:#4f6772}.vB span i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:0}
  .vB .on i{background:var(--ok)}.vB .old i{background:#c58a2b}.vB .no i{background:#b8c4ca}.vB .old{color:#7a4c06}`,
  html: x => `<div class="vB">${x.places.map(p => { const on = p.links.length, old = (p.old||[]).length;
   return `<div><b>${p.label}</b><span class="${on?'on':old?'old':'no'}"><i></i>${on?'あります（'+p.links[0].split(/[\\/]/).pop()+'）':old?'古い場所を指しています（'+p.old[0].path.split(/[\\/]/).pop()+'）':'ありません'}</span>${on?'<span></span>':`<button class="${old?'secondary':''}">${old?'向け直す':'作る'}</button>`}</div>` }).join('')}</div>` },
 C: { name: 'C 要約と1つのボタン', css: `
  .vC{display:flex;align-items:center;gap:14px;padding:11px 13px;border:1px solid #ecd3a3;background:#fdf8ee;border-radius:9px}
  .vC.ok{border-color:#cce8db;background:#f2faf6}.vC p{margin:0;font-size:12.5px;color:#3c5662;flex:1}.vC b{color:#7a4c06}`,
  html: x => { const bad = x.places.filter(p => !p.links.length);
   return `<div class="vC${bad.length?'':' ok'}"><p>${x.places.map(p => `${p.label}: ${p.links.length?'あり':(p.old||[]).length?'<b>古い場所を指しています</b>':'<b>ありません</b>'}`).join('　／　')}</p>${bad.length?'<button>足りないところをそろえる</button>':''}</div>` } },
 D: { name: 'D 選んで作る（チェック）', css: `
  .vD{display:grid;gap:6px;padding:10px 12px;border:1px solid #dce6ea;border-radius:9px;background:#fff}
  .vD label{display:flex;align-items:center;gap:9px;font-size:12.5px;color:#203f4d}.vD input{width:16px;height:16px}
  .vD small{color:#647581}.vD .old small{color:#7a4c06}.vD button{justify-self:start;margin-top:4px}`,
  html: x => `<div class="vD">${x.places.map(p => { const on = p.links.length, old = (p.old||[]).length;
   return `<label class="${old&&!on?'old':''}"><input type="checkbox" ${on?'disabled':'checked'}><b>${p.label}</b><small>${on?'あります':old?'古い場所を指しています（向け直します）':'ありません（作ります）'}</small></label>` }).join('')}<button>選んだ場所に作る・向け直す</button></div>` },
 E: { name: 'E 事実の札（このPCの欄と同じ形）', css: `
  .vE .rel-facts>div{grid-template-columns:1fr auto;align-items:center}.vE .rel-facts small,.vE .rel-facts b{grid-column:1}
  .vE .rel-facts button{grid-column:2;grid-row:1/3;padding:5px 9px;font-size:11.5px}`,
  html: x => `<div class="vE"><div class="rel-facts">${x.places.map(p => { const on = p.links.length, old = (p.old||[]).length;
   return `<div class="${on?'is-ok':old?'is-warn':'is-idle'}"><small>${p.label}</small><b>${on?'あります':old?'古い場所を指しています':'ありません'}</b>${on?'':`<button class="${old?'secondary':''}">${old?'向け直す':'作る'}</button>`}</div>` }).join('')}</div></div>` },
};
window.applyVariant = k => {
 const v = SC_VARIANTS[k], x = scState, box = document.getElementById('sc-places');
 let st = document.getElementById('v-style'); if (!st) { st = document.createElement('style'); st.id = 'v-style'; document.head.appendChild(st) }
 st.textContent = v.css; if (v.html) box.outerHTML = `<div id="sc-places">${v.html(x)}</div>`;
};
// ---- 僅差だったので、複合案 F・G・H を足す（A の札を土台に、E・B・C の良いところを合わせる）
const _card = (x, opt) => x.places.map(p => { const on = p.links.length, old = (p.old||[]).length, nm = t => String(t).split(/[\\/]/).pop();
 const word = on ? 'あります' : old ? '古い場所を指しています' : 'ありません', file = on ? nm(p.links[0]) : old ? nm(p.old[0].path) : '';
 const btn = on ? '' : `<button class="${old?'secondary':''}">${old?'ここへ向け直す':p.label+'に作る'}</button>`;
 const tone = on ? ' is-on' : old ? ' is-old' : '';
 if (opt === 'F') return `<div class="sc-place${tone} vF"><i>${on?'✓':old?'!':'○'}</i><div><small class="lbl">${p.label}</small><b>${word}</b>${file?`<small>${file}</small>`:''}</div>${btn}</div>`;
 return `<div class="sc-place${tone} vG"><i>${on?'✓':old?'!':'○'}</i><div><b>${p.label}</b><small><em class="dot"></em>${word}${file?'（'+file+'）':''}</small></div>${btn}</div>` }).join('');
Object.assign(window.SC_VARIANTS, {
 F: { name: 'F 札＋事実の札の字組み（A+E）', css: `.vF small.lbl{font-size:10px;font-weight:900;color:#71858e}.vF b{font-size:13.5px}.sc-place.is-old.vF b{color:#7a4c06}.sc-place.is-on.vF b{color:var(--ok)}`,
  html: x => `<div class="sc-places">${_card(x,'F')}</div>` },
 G: { name: 'G 札＋点と言葉（A+B）', css: `.vG .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:#b8c4ca}.is-on.vG .dot{background:var(--ok)}.is-old.vG .dot{background:#c58a2b}`,
  html: x => `<div class="sc-places">${_card(x,'G')}</div>` },
 H: { name: 'H 札＋まとめてそろえる（A+C）', css: `.vH-all{display:flex;justify-content:flex-end;margin-top:8px}`,
  html: x => { const bad = x.places.filter(p => !p.links.length).length;
   return `<div class="sc-places">${_card(x,'A')}</div>${bad>=2?'<div class="vH-all"><button>足りないところをまとめてそろえる</button></div>':''}` } },
});
