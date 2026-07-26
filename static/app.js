const UI_BUILD='1.7.0-dynamic-period';
let cfg,editing=null,editingRule=null,sortDir=1,scheduleInfo={},rowLive={},rowQueue={},statusFailCount=0,serverLostShown=false;const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)],E=s=>String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));const uid=()=>crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random();function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';setTimeout(()=>$('#toast').style.display='none',2500)}function dirty(){$('#dirty').textContent='未保存の変更があります'}$$('nav button').forEach(b=>b.onclick=()=>{$$('nav button,section').forEach(x=>x.classList.remove('on'));b.classList.add('on');$('#'+b.dataset.p).classList.add('on');if(b.dataset.p==='logs')loadLog();if(b.dataset.p==='calendar')openCalendar()});
const paths={navigator_api_dll:['Navigator API DLL','file',[['DLLファイル','*.dll'],['すべて','*.*']]],symnavi_exe:['SymNavi.exe','file',[['実行ファイル','*.exe'],['すべて','*.*']]],symnavim_conf:['symnavim.conf','file',[['CONFファイル','*.conf'],['すべて','*.*']]],symnavim_def:['symnavim.def','file',[['DEFファイル','*.def'],['すべて','*.*']]],accdb_template:['ACCDB空テンプレート','file',[['Access Database','*.accdb'],['すべて','*.*']]],rne_folder:['RNE基本フォルダー','folder'],default_output_folder:['既定の出力先','folder'],backup_folder:['バックアップ先','folder']};
let waitingTimer=null,waitingStarted=0;function currentEngine(){return $('#extract-engine')?.value||cfg?.settings?.extract_engine||'api'}function waitingEngineLabel(context='common'){if(context==='api'||(context==='engine'&&currentEngine()==='api'))return 'NAVIGATOR API';if(context==='dde'||(context==='engine'&&currentEngine()==='dde'))return 'DDE COMPATIBILITY';return 'COMMON OPERATION'}function showWaiting(title='確認中',detail='処理を続行しています...',context='common'){let d=$('#waiting-dialog');$('#waiting-engine').textContent=waitingEngineLabel(context);$('#waiting-title').textContent=title;$('#waiting-detail').textContent=detail;waitingStarted=Date.now();clearInterval(waitingTimer);let tick=()=>{let sec=Math.floor((Date.now()-waitingStarted)/1000);$('#waiting-elapsed').textContent=`経過 ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`};tick();waitingTimer=setInterval(tick,1000);if(!d.open)d.showModal()}function updateWaiting(title,detail,context){if(title)$('#waiting-title').textContent=title;if(detail)$('#waiting-detail').textContent=detail;if(context)$('#waiting-engine').textContent=waitingEngineLabel(context)}function hideWaiting(){clearInterval(waitingTimer);waitingTimer=null;let d=$('#waiting-dialog');if(d?.open)d.close()}async function convertPath(input,mode){showWaiting('パス変換中',mode==='relative'?'アプリフォルダー基準へ変換しています...':'実際の絶対パスを解決しています...');try{let r=await fetch('/api/path-convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:input.value,mode})}),d=await r.json();if(!r.ok)return toast(d.error);input.value=d.value;updatePathBadge(input);dirty()}finally{hideWaiting()}}function updatePathBadge(input){let badge=input.closest('label')?.querySelector('.path-badge');if(!badge)return;let relative=input.value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(input.value);badge.textContent=relative?'相対パス / 基準: アプリフォルダー':'絶対パス';badge.className='path-badge '+(relative?'path-kind-relative':'path-kind-absolute')}function isRelativePath(value){return !!value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(value)}function enhancePathInput(input,kind='folder'){if(!input||input.dataset.pathEnhanced)return;input.dataset.pathEnhanced='1';let tools=document.createElement('div');tools.className='path-tools compact-path-tools';tools.innerHTML='<button type="button" class="pathmode path-toggle" title="絶対パスと相対パスを切り替えます"></button><small class="path-badge"></small>';input.closest('label')?.appendChild(tools);let toggle=tools.querySelector('.path-toggle');function refresh(){let relative=isRelativePath(input.value);toggle.textContent=relative?'相対 → 絶対':'絶対 → 相対';toggle.dataset.mode=relative?'absolute':'relative';updatePathBadge(input)}toggle.onclick=async()=>{await convertPath(input,toggle.dataset.mode);refresh()};input.addEventListener('input',refresh);input._refreshPathControl=refresh;refresh()}async function browse(kind,initial,types){showWaiting('参照画面を準備中','設定中のパスを解決して、その場所から開きます...');try{let url=kind==='folder'?'/api/pick-folder':'/api/pick-file',r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initial,types})}),d=await r.json();if(!r.ok)toast(d.error);return d.path||''}finally{hideWaiting()}}
async function checkConfiguredPath(item,jobId){showWaiting('ファイル存在確認中','設定場所と周辺フォルダーを検索しています...');try{let r=await fetch('/api/path-check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item,job_id:jobId})}),d=await r.json();if(!r.ok)return toast(d.error);showPathResult(d)}finally{hideWaiting()}}function showPathResult(d){let box=$('#suggest-content');if(d.ok){box.innerHTML=`<p class="path-ok">存在を確認しました。</p><code>${E(d.resolved)}</code>`}else if(d.candidates?.length){box.innerHTML=`<p class="path-ng">設定先には存在しません。</p><p>設定値: <code>${E(d.configured)}</code></p><p>実在する修正候補:</p><div class="candidate-list">${d.candidates.map(x=>`<div class="candidate"><code>${E(x)}</code><button class="apply-suggestion" data-path="${E(x)}">このパスへ修正</button></div>`).join('')}</div>`;box.querySelectorAll('.apply-suggestion').forEach(b=>b.onclick=async()=>{let r=await fetch('/api/apply-path-suggestion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item:d.item,job_id:d.job_id,candidate:b.dataset.path})}),x=await r.json();if(r.ok){$('#path-suggestion').close();toast('設定を修正しました');await init()}else toast(x.error)})}else{box.innerHTML=`<p class="path-ng">ファイルが見つかりません。</p><p>確認先: <code>${E(d.resolved)}</code></p><p class="reselect">上2階層・下1階層の検索範囲にも候補がありません。参照ボタンから再指定してください。</p>`}if(!$('#path-suggestion').open)$('#path-suggestion').showModal()}

function expectedExt(f){return {sqlite3:'.sqlite3',txt:'.txt',csv:'.csv',xlsx:'.xlsx',accdb:'.accdb'}[normalizeFormat(f)]||'.sqlite3'}
function normalizeFormat(f){f=String(f||'').trim().toLowerCase();return ({sqlite:'sqlite3',db:'sqlite3',access:'accdb',excel:'xlsx',xls:'xlsx'}[f]||f||'sqlite3')}
function canonicalOutputFile(name,format){let ext=expectedExt(format),leaf=String(name||'output').trim(),dot=leaf.lastIndexOf('.');if(dot>0)leaf=leaf.slice(0,dot);leaf=leaf.replace(/(?:sqlite3|sqlite|accdb|xlsx|xls|csv|txt)$/i,'');return (leaf||'output')+ext}
function outputStem(name){let leaf=String(name||'').trim(),dot=leaf.lastIndexOf('.');if(dot>0)leaf=leaf.slice(0,dot);leaf=leaf.replace(/(?:sqlite3|sqlite|accdb|xlsx|xls|csv|txt)$/i,'');return leaf}
function updateFixedNameNote(){let f=normalizeFormat($('#m-format')?.value),ext=expectedExt(f),stem=(($('#m-output-file')?.value||'').trim()||'output');if($('#m-ext-suffix'))$('#m-ext-suffix').textContent=ext;if($('#m-format-note'))$('#m-format-note').textContent=`選択中: ${formatName(f)}（拡張子 ${ext}）／ 最終ファイル名 → ${outputStem(stem)||'output'}${ext}`}
function syncOutputExtension(){let f=normalizeFormat($('#m-format')?.value),i=$('#m-output-file');if($('#m-format'))$('#m-format').value=f;if(i)i.value=outputStem(i.value);updateFixedNameNote()}
function formatName(f){return {sqlite3:'SQLite3',txt:'TXT',csv:'CSV',xlsx:'EXCEL',accdb:'ACCESS'}[f]||f}
function segmentHtml(segments){return (segments||[]).map(s=>s.var?`<span class="fname-var">${E(s.text)}</span>`:E(s.text)).join('')}
function outputFileCell(j){
 // 変数扱いはバックエンドが実トークンの有無で判定した output_is_variable のみ。単に変数欄へ入力しただけでは変数バッジを出さない。
 if(j.output_is_variable){
  let segs=j.output_file_segments||[];
  let body=segs.length?segmentHtml(segs):E(j.output_file_preview||'(実行時に決定)');
  return `<div class="primarytext" title="${E(j.output_pattern||'')}"><span class="name-var-badge">変数</span>${body}</div><div class="subtext" title="${E(j.output_pattern||'')}">${E(j.output_pattern||'')} / ${E(formatName(j.output_format))}</div>`;
 }
 return `<div class="primarytext">${E(j.output_file)}</div><div class="subtext">${E(formatName(j.output_format))} / ${E(j.type)}</div>`;
}function scheduleSummary(r){if(r.type==='daily')return `毎日 ${r.time}`;if(r.type==='weekdays')return `${(r.weekdays||[]).map(x=>'月火水木金土日'[x]).join('・')} ${r.time}`;if(r.type==='monthly')return `毎月 ${(r.month_days||[]).join(',')}日 ${r.time}`;if(r.type==='interval')return `${r.interval_minutes||60}分間隔`;if(r.type==='specific_dates')return `${(r.dates||[]).length}日指定 ${r.time}`;return ''}function typeName(t){return {daily:'毎日',weekdays:'曜日指定',monthly:'月日指定',interval:'一定間隔',specific_dates:'特定日'}[t]||t}
function filtered(){let q=$('#search').value.trim().toLowerCase(),fe=$('#filter-enabled').value,fs=$('#filter-schedule').value,sort=$('#sort').value;let a=cfg.jobs.filter(j=>[j.name,j.rne,j.rne_path,j.output_file,j.output_folder,j.table,j.output_format,j.comment].join(' ').toLowerCase().includes(q)).filter(j=>fe==='all'||fe==='enabled'&&j.enabled||fe==='disabled'&&!j.enabled).filter(j=>fs==='all'||fs==='scheduled'&&(j.schedules||[]).some(r=>r.enabled)||fs==='manual'&&!(j.schedules||[]).some(r=>r.enabled));let key=j=>sort==='name'?j.name:sort==='rne'?j.rne:sort==='output'?(j.output_folder||''):sort==='schedule'?(j.schedules||[]).filter(r=>r.enabled).length:cfg.jobs.indexOf(j);a.sort((x,y)=>typeof key(x)==='number'?(key(x)-key(y))*sortDir:String(key(x)).localeCompare(String(key(y)),'ja')*sortDir);return a}
function render(){let a=filtered(),body=$('#jobs-body');let canReorder=($('#sort').value==='order'&&sortDir===1&&!$('#search').value.trim()&&$('#filter-enabled').value==='all'&&$('#filter-schedule').value==='all');body.innerHTML=a.map(j=>`<tr data-id="${j.id}" draggable="${canReorder}" class="${canReorder?'reorderable':''}"><td class="c-check"><span class="drag-handle" title="${canReorder?'ドラッグで並べ替え（問い合わせ順に反映）':'並べ替えは「登録順」かつ絞り込み解除時に有効です'}">⋮⋮</span><input class="rowcheck" type="checkbox"></td><td><span class="state ${j.enabled?'on':'off'}">${j.enabled?'有効':'無効'}</span></td><td><div class="primarytext" title="${E(j.name)}">${E(j.name)}</div><div class="subtext">${E(j.table)} / ${E(j.sheet)}</div>${j.comment?`<div class="job-comment" title="${E(j.comment)}"><i class="jc-ic">用途</i><span>${E(j.comment)}</span></div>`:''}</td><td><div class="primarytext" title="${E(j.rne_path||j.rne)}">${E(j.rne)}</div><div class="subtext pathtext">${E(j.rne_path||'')}</div></td><td>${outputFileCell(j)}</td><td><a class="output-link" href="#" data-path="${E(j.output_folder||cfg.default_output_folder)}" title="出力先を開く">${E(j.output_folder||cfg.default_output_folder)}</a></td><td class="c-progress">${rowProgressCell(j)}</td><td><div class="rowactions"><button class="run-one" title="実行">実行</button><button class="edit secondary" title="詳細">詳細</button><button class="copy secondary" title="複製">複製</button><button class="delete danger" title="削除">削除</button></div></td></tr>`).join('');paintRowProgress();applyScheduleCells();$('#empty').hidden=a.length>0;$('#summary').textContent=`表示 ${a.length}件 / 登録 ${cfg.jobs.length}件 / 有効 ${cfg.jobs.filter(j=>j.enabled).length}件 / 自動実行ルール ${cfg.jobs.flatMap(j=>j.schedules||[]).filter(r=>r.enabled).length}件`;body.querySelectorAll('tr').forEach(tr=>{let j=cfg.jobs.find(x=>x.id===tr.dataset.id);tr.onclick=e=>{if(!e.target.closest('button,a,input')){tr.classList.toggle('selected');let cb=tr.querySelector('.rowcheck');if(cb)cb.checked=tr.classList.contains('selected');}};tr.querySelector('.rowcheck').onchange=e=>tr.classList.toggle('selected',e.target.checked);tr.ondblclick=e=>{if(!e.target.closest('button,input,select,a'))openEditor(j)};tr.querySelector('.edit').onclick=()=>openEditor(j);tr.querySelector('.run-one').onclick=()=>runJobs([j.id]);tr.querySelector('.copy').onclick=()=>{let n=structuredClone(j);n.id=uid();n.name+=' コピー';n.schedules=(n.schedules||[]).map(r=>({...r,id:uid(),enabled:false}));cfg.jobs.splice(cfg.jobs.indexOf(j)+1,0,n);render();dirty()};tr.querySelector('.delete').onclick=()=>deleteJob(j);let l=tr.querySelector('.output-link');if(l)l.onclick=async(e)=>{e.preventDefault();e.stopPropagation();try{let r=await fetch('/api/open-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:l.dataset.path})}),d=await r.json();if(r.ok&&d.ok)toast('出力先を開きました');else toast(d.error||'出力先を開けませんでした')}catch{toast('出力先を開けませんでした')}};bindRowDnD(tr)})}
/* v1.9.0: 一覧のドラッグ&ドロップ並べ替え（問い合わせ順に反映）と管理単位の削除 */
let dragSrcId=null;
function bindRowDnD(tr){
 if(tr.getAttribute('draggable')!=='true')return;
 tr.addEventListener('dragstart',e=>{dragSrcId=tr.dataset.id;tr.classList.add('dragging');try{e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',tr.dataset.id)}catch{}});
 tr.addEventListener('dragend',()=>{dragSrcId=null;tr.classList.remove('dragging');$$('#jobs-body tr').forEach(x=>x.classList.remove('drop-before','drop-after'))});
 tr.addEventListener('dragover',e=>{if(!dragSrcId||dragSrcId===tr.dataset.id)return;e.preventDefault();try{e.dataTransfer.dropEffect='move'}catch{}let r=tr.getBoundingClientRect(),after=(e.clientY-r.top)>r.height/2;tr.classList.toggle('drop-after',after);tr.classList.toggle('drop-before',!after)});
 tr.addEventListener('dragleave',()=>{tr.classList.remove('drop-before','drop-after')});
 tr.addEventListener('drop',e=>{e.preventDefault();let srcId=dragSrcId||e.dataTransfer?.getData('text/plain');tr.classList.remove('drop-before','drop-after');if(!srcId||srcId===tr.dataset.id)return;let r=tr.getBoundingClientRect(),after=(e.clientY-r.top)>r.height/2;reorderJobs(srcId,tr.dataset.id,after)})
}
async function reorderJobs(srcId,targetId,after){
 let from=cfg.jobs.findIndex(x=>x.id===srcId),to=cfg.jobs.findIndex(x=>x.id===targetId);
 if(from<0||to<0)return;
 let moved=cfg.jobs.splice(from,1)[0];
 let idx=cfg.jobs.findIndex(x=>x.id===targetId);
 cfg.jobs.splice(after?idx+1:idx,0,moved);
 render();
 let payload=structuredClone(cfg);delete payload.credential_status;
 try{let rp=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(rp.ok){$('#dirty').textContent='並び順を保存しました';toast('問い合わせ順を更新しました')}else{dirty();toast('並び順の保存に失敗しました。設定を保存してください')}}catch{dirty();toast('並び順の保存に失敗しました。設定を保存してください')}
}
async function deleteJob(j){
 if(!confirm(`管理単位「${j.name}」を削除します。よろしいですか？\n登録内容と自動実行ルールが削除されます（この操作は元に戻せません）。`))return;
 let i=cfg.jobs.findIndex(x=>x.id===j.id);if(i<0)return;
 cfg.jobs.splice(i,1);render();
 let payload=structuredClone(cfg);delete payload.credential_status;
 try{let r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(r.ok){$('#dirty').textContent='管理単位を削除しました';await init();toast(`「${j.name}」を削除しました`)}else{dirty();toast('削除の保存に失敗しました。設定を保存してください')}}catch{dirty();toast('削除の保存に失敗しました。設定を保存してください')}
}
function fillSuggestions(){let sets={names:cfg.jobs.map(j=>j.name),rne:cfg.jobs.map(j=>j.rne_path),output:[cfg.default_output_folder,...cfg.jobs.map(j=>j.output_folder)],'output-file':cfg.jobs.map(j=>j.output_file),table:cfg.jobs.map(j=>j.table),sheet:cfg.jobs.map(j=>j.sheet)};Object.entries(sets).forEach(([k,v])=>$('#suggest-'+k).innerHTML=[...new Set(v.filter(Boolean))].map(x=>`<option value="${E(x)}">`).join(''))}
function rulesRender(){let box=$('#m-rules');box.innerHTML=editing.schedules.length?editing.schedules.map(r=>`<div class="rule-row" data-id="${r.id}"><input class="rule-toggle" type="checkbox" ${r.enabled?'checked':''}><b>${E(r.name)}</b><span class="rule-type">${typeName(r.type)}</span><span class="rule-summary">${E(scheduleSummary(r))}</span><button class="rule-edit secondary" type="button">編集</button><button class="rule-delete danger" type="button">削除</button></div>`).join(''):'<div class="empty">自動実行ルールはありません。手動実行のみです。</div>';box.querySelectorAll('.rule-row').forEach(el=>{let r=editing.schedules.find(x=>x.id===el.dataset.id);el.querySelector('.rule-toggle').onchange=e=>{r.enabled=e.target.checked;dirty()};el.querySelector('.rule-edit').onclick=()=>openRule(r);el.querySelector('.rule-delete').onclick=()=>{editing.schedules=editing.schedules.filter(x=>x.id!==r.id);rulesRender()}});updateRuleCount()}
function openEditor(job){editing=structuredClone(job||{id:uid(),name:'新しい対象',enabled:true,rne:'NEW.RNE',rne_path:cfg.rne_folder+'\\NEW.RNE',output_folder:cfg.default_output_folder,output_format:'sqlite3',output_file:'NEW.sqlite3',table:'仕掛',sheet:'Page1',type:'詳細データ',naming_mode:'fixed',output_pattern:'',comment:'',period:{enabled:false,control_point:'',unit:'month',from_offset:-1,to_offset:0},schedules:[]});$('#modal-title').textContent=job?'対象を編集':'対象を追加';$('#m-id').value=editing.id;$('#m-name').value=editing.name;$('#m-enabled').checked=editing.enabled;$('#m-rne-path').value=editing.rne_path||'';$('#m-output').value=editing.output_folder||cfg.default_output_folder;editing.output_format=normalizeFormat(editing.output_format);$('#m-format').value=editing.output_format;$('#m-output-file').value=editing.output_file;$('#m-table').value=editing.table;$('#m-sheet').value=editing.sheet;$('#m-type').value=editing.type;if($('#m-comment'))$('#m-comment').value=editing.comment||'';syncOutputExtension();initNaming(editing);setPeriodUI(editing.period);rulesRender();setEditorTab('io');$('#editor').showModal()}
$('#m-format').onchange=()=>{syncOutputExtension();if(currentNamingMode()==='template')refreshNamePreview()};$('#m-rne-check').onclick=async()=>{showWaiting('RNEファイル確認中','設定場所と周辺フォルダーを検索しています...');try{let temp={item:'rne',job_id:editing.id,label:editing.rne,configured:$('#m-rne-path').value,resolved:$('#m-rne-path').value,candidates:[],ok:false};let r=await fetch('/api/path-check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item:'rne',job_id:editing.id,value:$('#m-rne-path').value,expected_name:$('#m-rne-path').value.split(/[\\/]/).pop()})}),d=await r.json();if(r.ok)showPathResult(d);else toast(d.error)}finally{hideWaiting()}};$('#m-rne-pick').onclick=async()=>{let p=await browse('file',$('#m-rne-path').value,[['RNEファイル','*.RNE'],['すべて','*.*']]);if(p){let i=$('#m-rne-path'),wasRel=i.value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(i.value);i.value=p;if(wasRel)await convertPath(i,'relative');updatePathBadge(i);i._refreshPathControl?.()}};$('#m-output-pick').onclick=async()=>{let p=await browse('folder',$('#m-output').value);if(p){let i=$('#m-output'),wasRel=i.value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(i.value);i.value=p;if(wasRel)await convertPath(i,'relative');updatePathBadge(i)}};enhancePathInput($('#m-rne-path'),'file');enhancePathInput($('#m-output'),'folder');$('#add-rule').onclick=()=>openRule({id:uid(),enabled:true,name:'実行ルール',type:'daily',time:'06:00'},true);$('#apply').onclick=async e=>{e.preventDefault();syncOutputExtension();const f=normalizeFormat($('#m-format').value),file=canonicalOutputFile($('#m-output-file').value,f),updated={...editing,name:$('#m-name').value.trim(),enabled:$('#m-enabled').checked,rne_path:$('#m-rne-path').value.trim(),rne:$('#m-rne-path').value.trim().split(/[\\/]/).pop(),output_folder:$('#m-output').value.trim(),output_format:f,output_file:file,table:$('#m-table').value.trim(),sheet:$('#m-sheet').value.trim(),type:$('#m-type').value,naming_mode:currentNamingMode(),output_pattern:$('#m-output-pattern').value.trim(),comment:($('#m-comment')?.value||'').trim(),period:currentPeriod()};let i=cfg.jobs.findIndex(j=>j.id===updated.id);if(i<0)cfg.jobs.unshift(updated);else cfg.jobs[i]=updated;let payload=structuredClone(cfg);delete payload.credential_status;showWaiting('設定を保存中',`${formatName(f)} / ${file}`);try{let r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(!r.ok)throw Error(d.error||'設定保存失敗');$('#editor').close();await init();toast(`保存完了: ${formatName(f)} / ${file}`)}catch(x){toast(x.message)}finally{hideWaiting()}};
/* V35: dynamic output filename builder */
let namePreviewTimer=null;
function currentNamingMode(){return document.querySelector('.naming-tab.on')?.dataset.mode||'fixed'}
function setNamingMode(mode){$$('.naming-tab').forEach(b=>b.classList.toggle('on',b.dataset.mode===mode));$('#naming-fixed')?.classList.toggle('on',mode==='fixed');$('#naming-template')?.classList.toggle('on',mode==='template');if(mode==='template')refreshNamePreview()}
function initNaming(job){if($('#m-output-pattern'))$('#m-output-pattern').value=job.output_pattern||'';setNamingMode(job.naming_mode==='template'?'template':'fixed')}
function insertToken(tok){let i=$('#m-output-pattern');if(!i)return;let s=i.selectionStart??i.value.length,e=i.selectionEnd??i.value.length;i.value=i.value.slice(0,s)+tok+i.value.slice(e);let pos=s+tok.length;i.focus();i.setSelectionRange(pos,pos);refreshNamePreview();dirty()}
function refreshNamePreview(){let el=$('#m-name-preview'),meta=$('#m-name-preview-meta');if(!el)return;let pattern=$('#m-output-pattern')?.value||'';if(!pattern.trim()){el.textContent='—';if(meta)meta.textContent='パターンを入力すると実ファイル名を試算します';return}clearTimeout(namePreviewTimer);namePreviewTimer=setTimeout(async()=>{try{let r=await fetch('/api/preview-filename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pattern,rne_path:$('#m-rne-path').value,name:$('#m-name').value,table:$('#m-table').value,format:normalizeFormat($('#m-format').value),output_file:$('#m-output-file').value})}),d=await r.json();if(!d.ok){el.textContent='(命名エラー)';if(meta)meta.textContent=d.error||'';return}if(d.segments&&d.segments.length)el.innerHTML=segmentHtml(d.segments);else el.textContent=d.filename;if(meta)meta.textContent=(d.is_variable?'色付き部分が変数です。':'変数は使われていません（固定文字）。')+(d.rne_found?` 対象RNE 更新日 ${d.rne_mtime} / 作成日 ${d.rne_ctime}`:' 対象RNEが未検出のため更新日・作成日は空になります')+` / 実行日時 ${d.now}`}catch{el.textContent='(プレビュー取得失敗)';if(meta)meta.textContent=''}},250)}
$$('.naming-tab').forEach(b=>b.onclick=()=>{setNamingMode(b.dataset.mode);dirty()});
function setPattern(p){let i=$('#m-output-pattern');if(!i)return;i.value=p;refreshNamePreview();dirty();i.focus();i.setSelectionRange(i.value.length,i.value.length)}
$$('#naming-template [data-token]').forEach(b=>b.onclick=()=>insertToken(b.dataset.token));
$$('#naming-template .chip-preset[data-pattern]').forEach(b=>b.onclick=()=>setPattern(b.dataset.pattern));
if($('#m-digit-insert'))$('#m-digit-insert').onclick=()=>{let v=($('#m-digit-pattern')?.value||'').trim();if(!v)return toast('YYYYMD などの桁数パターンを入力してください');let tok=/[:]/.test(v)?`{time:${v}}`:`{date:${v}}`;insertToken(tok)};
if($('#m-digit-pattern'))$('#m-digit-pattern').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('#m-digit-insert')?.click()}});
/* 日付・時刻の変数タグビルダー: 使う部分と桁(Y/M/D/h/m/s の数)を選び {now:...} タグを1つ生成する。Excelの書式設定に近い操作感。 */
const VTB_ORDER=['year','month','day','hour','min','sec'],VTB_LETTER={year:'Y',month:'M',day:'D',hour:'h',min:'m',sec:'s'};
/* 日付の対象(現在日時 / 対象ファイル更新日 / 対象ファイル作成日)を、日付の計算(年月日のずらし)と桁数(Y/M/Dの数)の指定とセットで1つの変数タグに組み立てる。 */
const VTB_SOURCES={now:'現在日時',rne_mtime:'対象ファイル更新日',rne_ctime:'対象ファイル作成日'};
let vtbWidth={year:4,month:2,day:2,hour:0,min:0,sec:0},vtbSep='',vtbSource='now',vtbOffset={y:0,m:0,d:0};
function vtbFormat(){let parts=[];VTB_ORDER.forEach(k=>{let w=vtbWidth[k]||0;if(w>0)parts.push(VTB_LETTER[k].repeat(w))});return parts.join(vtbSep)}
/* 日付の計算をタグへ埋め込むオフセット文字列(例: +2Y-1M-7D)。0の単位は省略。年→月→日の順。 */
function vtbOffsetText(){return [['Y',vtbOffset.y|0],['M',vtbOffset.m|0],['D',vtbOffset.d|0]].filter(([u,n])=>n).map(([u,n])=>(n>0?'+':'')+n+u).join('')}
function vtbToken(){let f=vtbFormat();return f?`{${vtbSource}${vtbOffsetText()}:${f}}`:''}
/* 例示用: 基準日へ年月日のずらしを適用する。月末を跨ぐ場合はExcelのEDATE同様に月末へ丸める。 */
function applyVtbOffset(d){let nd=new Date(d),om=(vtbOffset.y|0)*12+(vtbOffset.m|0);if(om){let total=nd.getFullYear()*12+nd.getMonth()+om,y=Math.floor(total/12),m=((total%12)+12)%12,last=new Date(y,m+1,0).getDate();nd=new Date(y,m,Math.min(nd.getDate(),last),nd.getHours(),nd.getMinutes(),nd.getSeconds())}if(vtbOffset.d|0)nd.setDate(nd.getDate()+(vtbOffset.d|0));return nd}
function formatCustomLocal(fmt,d){d=d||new Date();let out='',re=/(Y+|M+|D+|h+|m+|s+|[^YMDhms]+)/g,mm;while((mm=re.exec(fmt))){let run=mm[0],ch=run[0],n=run.length;if(ch==='Y')out+=(n<4?String(d.getFullYear()%(10**n)).padStart(n,'0'):String(d.getFullYear()));else if(ch==='M')out+=String(d.getMonth()+1).padStart(n,'0');else if(ch==='D')out+=String(d.getDate()).padStart(n,'0');else if(ch==='h')out+=String(d.getHours()).padStart(n,'0');else if(ch==='m')out+=String(d.getMinutes()).padStart(n,'0');else if(ch==='s')out+=String(d.getSeconds()).padStart(n,'0');else out+=run}return out}
function vtbOffsetLabel(){let p=[];if(vtbOffset.y|0)p.push(`${Math.abs(vtbOffset.y)}年${vtbOffset.y>0?'後':'前'}`);if(vtbOffset.m|0)p.push(`${Math.abs(vtbOffset.m)}ヶ月${vtbOffset.m>0?'後':'前'}`);if(vtbOffset.d|0)p.push(`${Math.abs(vtbOffset.d)}日${vtbOffset.d>0?'後':'前'}`);return p.join('・')}
function vtbSyncOffsetInputs(){$$('#naming-template .vtb-offbox').forEach(box=>{let k=box.dataset.off,inp=box.querySelector('.vtb-offnum');if(inp)inp.value=Math.trunc(Number(vtbOffset[k])||0)})}
function vtbMarkOffsetPreset(){$$('#naming-template .vtb-offchip').forEach(b=>b.classList.toggle('on',Number(b.dataset.y)===(vtbOffset.y|0)&&Number(b.dataset.m)===(vtbOffset.m|0)&&Number(b.dataset.d)===(vtbOffset.d|0)))}
function vtbRefresh(){let tok=vtbToken(),f=vtbFormat();if($('#vtb-token'))$('#vtb-token').textContent=tok||'（対象と部分を選択）';vtbMarkOffsetPreset();
 let ex=$('#vtb-example');if(ex){if(!f){ex.textContent='—';}else{let sample=formatCustomLocal(f,applyVtbOffset(new Date())),calc=vtbOffsetLabel(),srcNote=vtbSource==='now'?'':`${VTB_SOURCES[vtbSource]}基準`,note=[srcNote,calc?`計算: ${calc}`:''].filter(Boolean).join(' / ');ex.textContent=note?`${sample}（${note}）`:sample}}}
function bindVarTagBuilder(){
 $$('#naming-template .vtb-srcbtn').forEach(b=>b.onclick=()=>{$$('#naming-template .vtb-srcbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');vtbSource=b.dataset.src||'now';vtbRefresh()});
 $$('#naming-template .vtb-offbox').forEach(box=>{let k=box.dataset.off,inp=box.querySelector('.vtb-offnum');box.querySelectorAll('button[data-step]').forEach(b=>b.onclick=()=>{vtbOffset[k]=(Math.trunc(Number(vtbOffset[k])||0))+Number(b.dataset.step);vtbSyncOffsetInputs();vtbRefresh()});if(inp)inp.addEventListener('input',()=>{vtbOffset[k]=Math.trunc(Number(inp.value)||0);vtbRefresh()})});
 $$('#naming-template .vtb-offchip').forEach(b=>b.onclick=()=>{vtbOffset={y:Number(b.dataset.y)||0,m:Number(b.dataset.m)||0,d:Number(b.dataset.d)||0};vtbSyncOffsetInputs();vtbRefresh()});
 $$('#naming-template .vtb-part').forEach(part=>{let key=part.dataset.part;part.querySelectorAll('.vtb-opts button').forEach(b=>b.onclick=()=>{part.querySelectorAll('.vtb-opts button').forEach(x=>x.classList.remove('on'));b.classList.add('on');vtbWidth[key]=Number(b.dataset.w)||0;vtbRefresh()})});
 $$('#naming-template .vtb-sepbtn').forEach(b=>b.onclick=()=>{$$('#naming-template .vtb-sepbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');vtbSep=b.dataset.sep||'';vtbRefresh()});
 let ins=$('#vtb-insert');if(ins)ins.onclick=()=>{let tok=vtbToken();if(!tok)return toast('日付・時刻の部分を1つ以上選んでください');insertToken(tok)};
 vtbSyncOffsetInputs();vtbRefresh();
}
bindVarTagBuilder();
if($('#m-output-pattern'))$('#m-output-pattern').addEventListener('input',()=>{refreshNamePreview();dirty()});
if($('#m-output-file'))$('#m-output-file').addEventListener('input',()=>{updateFixedNameNote();dirty()});
/* v1.0.0: editor modal tabs (基本・入出力 / 自動実行) for a scroll-less layout */
function setEditorTab(tab){$$('.editor-tab').forEach(b=>b.classList.toggle('on',b.dataset.etab===tab));$$('.editor-pane').forEach(p=>p.classList.toggle('on',p.dataset.etab===tab))}
function currentEditorTab(){return document.querySelector('.editor-tab.on')?.dataset.etab||'io'}
$$('.editor-tab').forEach(b=>b.onclick=()=>setEditorTab(b.dataset.etab));
function updateRuleCount(){let n=(editing?.schedules||[]).length,active=(editing?.schedules||[]).filter(r=>r.enabled).length,badge=$('#etab-rule-count');if(!badge)return;badge.hidden=n===0;badge.textContent=active?`${active}/${n}`:String(n);badge.title=`登録ルール ${n}件 / 有効 ${active}件`}
let ruleCalYM=null;
function detailRender(){let t=$('#r-type').value,d=$('#r-detail');
 $('#r-time-wrap').style.display=t==='interval'?'none':'grid';
 $$('#r-type-seg .pattern-card').forEach(c=>c.classList.toggle('on',c.dataset.type===t));
 if(t==='daily')d.innerHTML='<div class="rule-detail-note"><b>毎日実行</b><span>上で指定した時刻に毎日実行します。</span></div>';
 if(t==='weekdays'){let sel=editingRule.weekdays||[];d.innerHTML=`<span class="rule-section-label">実行する曜日</span><div class="weekday-chips">${['月','火','水','木','金','土','日'].map((x,i)=>`<label class="wchip ${sel.includes(i)?'on':''} ${i===5?'sat':''} ${i===6?'sun':''}"><input type="checkbox" value="${i}" ${sel.includes(i)?'checked':''}><span>${x}</span></label>`).join('')}</div><div class="chip-quick"><button type="button" class="mini-btn" data-wd="weekday">平日</button><button type="button" class="mini-btn" data-wd="weekend">週末</button><button type="button" class="mini-btn" data-wd="all">毎日</button><button type="button" class="mini-btn" data-wd="none">解除</button></div><p class="hint">選択した曜日に、上で指定した時刻で実行します。</p>`;$$('#r-detail .wchip input').forEach(cb=>cb.onchange=()=>cb.closest('.wchip').classList.toggle('on',cb.checked));$$('#r-detail .chip-quick .mini-btn').forEach(b=>b.onclick=()=>{let map={weekday:[0,1,2,3,4],weekend:[5,6],all:[0,1,2,3,4,5,6],none:[]}[b.dataset.wd]||[];$$('#r-detail .wchip input').forEach(cb=>{cb.checked=map.includes(Number(cb.value));cb.closest('.wchip').classList.toggle('on',cb.checked)})})}
 if(t==='monthly'){let sel=editingRule.month_days||[1];d.innerHTML=`<span class="rule-section-label">実行する日（毎月）</span><div class="monthday-grid">${Array.from({length:31},(_,k)=>k+1).map(n=>`<button type="button" class="mday ${sel.includes(n)?'on':''}" data-day="${n}">${n}</button>`).join('')}<button type="button" class="mday mday-last ${sel.includes(-1)?'on':''}" data-day="-1">月末</button></div><input id="r-monthdays" type="hidden" value="${E(sel.join(','))}"><p class="hint">選択した日に毎月実行します。「月末」はその月の最終日です。</p>`;$$('#r-detail .mday').forEach(b=>b.onclick=()=>{b.classList.toggle('on');$('#r-monthdays').value=$$('#r-detail .mday.on').map(x=>Number(x.dataset.day)).join(',')})}
 if(t==='interval'){let mins=editingRule.interval_minutes||60;d.innerHTML=`<span class="rule-section-label">実行間隔</span><div class="interval-field"><input id="r-interval" type="number" min="1" value="${mins}"><em>分ごと</em></div><div class="chip-quick">${[15,30,60,120,240].map(v=>`<button type="button" class="mini-btn" data-min="${v}">${v>=60?(v/60)+'時間':v+'分'}</button>`).join('')}</div><p class="hint">アプリ起動中、指定間隔ごとに実行します（時刻指定なし）。</p>`;$$('#r-detail .chip-quick .mini-btn').forEach(b=>b.onclick=()=>{$('#r-interval').value=b.dataset.min})}
 if(t==='specific_dates'){let sel=(editingRule.dates||[]).slice();d.innerHTML=`<span class="rule-section-label">実行する特定日</span><div class="mini-cal"><div class="mini-cal-head"><button type="button" class="iconnav mc-prev" aria-label="前の月">‹</button><b class="mc-title"></b><button type="button" class="iconnav mc-next" aria-label="次の月">›</button></div><div class="mini-cal-week"><span class="wk-sun">日</span><span>月</span><span>火</span><span>水</span><span>木</span><span>金</span><span class="wk-sat">土</span></div><div class="mini-cal-grid"></div></div><div class="picked-dates" id="r-picked"></div><input id="r-dates" type="hidden" value="${E(sel.join(','))}"><p class="hint">カレンダーの日付をクリックして複数選択できます。選択済みはタグの×からも解除できます。</p>`;let base=sel.length?new Date(sel[0]+'T00:00:00'):new Date();if(isNaN(base))base=new Date();ruleCalYM={y:base.getFullYear(),m:base.getMonth()+1};renderMiniCal()}}
function renderMiniCal(){let hid=$('#r-dates');if(!hid||!ruleCalYM)return;let sel=hid.value.split(',').map(x=>x.trim()).filter(Boolean),{y,m}=ruleCalYM;let start=new Date(y,m-1,1).getDay(),days=new Date(y,m,0).getDate();let title=$('#r-detail .mc-title');if(title)title.textContent=`${y}年${m}月`;let grid=$('#r-detail .mini-cal-grid');if(!grid)return;let cells='';for(let i=0;i<start;i++)cells+='<span class="mc-empty"></span>';for(let dn=1;dn<=days;dn++){let iso=`${y}-${String(m).padStart(2,'0')}-${String(dn).padStart(2,'0')}`,dow=new Date(y,m-1,dn).getDay();cells+=`<button type="button" class="mc-day ${sel.includes(iso)?'on':''} ${dow===0?'sun':''} ${dow===6?'sat':''}" data-iso="${iso}">${dn}</button>`}grid.innerHTML=cells;$$('#r-detail .mc-day').forEach(b=>b.onclick=()=>{let iso=b.dataset.iso,cur=hid.value.split(',').map(x=>x.trim()).filter(Boolean),i=cur.indexOf(iso);if(i<0)cur.push(iso);else cur.splice(i,1);cur.sort();hid.value=cur.join(',');renderMiniCal()});let pv=$('#r-detail .mc-prev'),nx=$('#r-detail .mc-next');if(pv)pv.onclick=()=>{ruleCalYM.m--;if(ruleCalYM.m<1){ruleCalYM.m=12;ruleCalYM.y--}renderMiniCal()};if(nx)nx.onclick=()=>{ruleCalYM.m++;if(ruleCalYM.m>12){ruleCalYM.m=1;ruleCalYM.y++}renderMiniCal()};renderPickedDates()}
function renderPickedDates(){let hid=$('#r-dates'),box=$('#r-picked');if(!hid||!box)return;let sel=hid.value.split(',').map(x=>x.trim()).filter(Boolean);box.innerHTML=sel.length?sel.map(x=>`<span class="date-tag" data-iso="${x}">${x}<i>×</i></span>`).join(''):'<span class="picked-empty">未選択</span>';$$('#r-picked .date-tag i').forEach(ic=>ic.onclick=()=>{let iso=ic.parentElement.dataset.iso,cur=hid.value.split(',').map(x=>x.trim()).filter(Boolean).filter(x=>x!==iso);hid.value=cur.join(',');renderMiniCal()})}
function currentRuleFromForm(){let r={type:$('#r-type')?.value||'daily',time:$('#r-time')?.value||'06:00'};if(r.type==='weekdays')r.weekdays=$$('#r-detail input:checked').map(x=>Number(x.value));if(r.type==='monthly')r.month_days=($('#r-monthdays')?.value||'').split(',').map(Number).filter(Number.isFinite);if(r.type==='interval')r.interval_minutes=Number($('#r-interval')?.value||60);if(r.type==='specific_dates')r.dates=($('#r-dates')?.value||'').split(',').map(x=>x.trim()).filter(Boolean);return r}
function updateRuleLiveSummary(){let el=$('#r-live-summary');if(!el)return;let s=scheduleSummary(currentRuleFromForm());el.textContent=s||'条件を選択してください'}
/* v1.4.0: 自動実行スケジュールのおすすめプリセット(サジェスト)。
   実務でよく使う組み合わせをワンクリックで一括入力し、その後に個別調整できる。
   icon: パターン種別の識別記号 / sub: 実行タイミングの短い説明。*/
const RULE_PRESETS=[
 {label:'平日 始業前',sub:'月〜金 8:30',icon:'週',type:'weekdays',time:'08:30',weekdays:[0,1,2,3,4],name:'平日始業前更新'},
 {label:'平日 昼休み',sub:'月〜金 12:00',icon:'週',type:'weekdays',time:'12:00',weekdays:[0,1,2,3,4],name:'平日昼休み更新'},
 {label:'平日 終業後',sub:'月〜金 17:30',icon:'週',type:'weekdays',time:'17:30',weekdays:[0,1,2,3,4],name:'平日終業後更新'},
 {label:'毎日 夜間',sub:'毎日 22:00',icon:'毎',type:'daily',time:'22:00',name:'夜間更新'},
 {label:'毎日 早朝',sub:'毎日 6:00',icon:'毎',type:'daily',time:'06:00',name:'早朝更新'},
 {label:'1時間ごと',sub:'稼働中 60分間隔',icon:'間',type:'interval',interval_minutes:60,name:'1時間ごと更新'},
 {label:'30分ごと',sub:'稼働中 30分間隔',icon:'間',type:'interval',interval_minutes:30,name:'30分ごと更新'},
 {label:'月初 更新',sub:'毎月1日 6:00',icon:'月',type:'monthly',time:'06:00',month_days:[1],name:'月初更新'},
 {label:'月末 更新',sub:'毎月末 22:00',icon:'月',type:'monthly',time:'22:00',month_days:[-1],name:'月末更新'},
];
function sameSet(a,b){let x=[...new Set((a||[]).map(Number))].sort((m,n)=>m-n),y=[...new Set((b||[]).map(Number))].sort((m,n)=>m-n);return x.length===y.length&&x.every((v,i)=>v===y[i])}
function presetMatches(p){let r=currentRuleFromForm();if(r.type!==p.type)return false;if(p.type!=='interval'&&(r.time||'')!==(p.time||''))return false;if(p.type==='weekdays')return sameSet(r.weekdays,p.weekdays);if(p.type==='monthly')return sameSet(r.month_days,p.month_days);if(p.type==='interval')return Number(r.interval_minutes)===Number(p.interval_minutes);return true}
function markActivePreset(){$$('#r-presets .preset-chip').forEach((b,i)=>b.classList.toggle('on',presetMatches(RULE_PRESETS[i])))}
function renderPresets(){let box=$('#r-presets');if(!box)return;box.innerHTML=RULE_PRESETS.map((p,i)=>`<button type="button" class="preset-chip" role="option" data-i="${i}" title="${E(p.label)}（${E(p.sub)}）"><i class="preset-ic pi-${p.type}">${E(p.icon)}</i><span class="preset-tx"><b>${E(p.label)}</b><small>${E(p.sub)}</small></span></button>`).join('');box.querySelectorAll('.preset-chip').forEach(b=>b.onclick=()=>applyPreset(RULE_PRESETS[Number(b.dataset.i)]));markActivePreset()}
function applyPreset(p){if(!editingRule)return;editingRule.type=p.type;editingRule.time=p.time||editingRule.time||'06:00';if(p.type==='weekdays')editingRule.weekdays=(p.weekdays||[]).slice();if(p.type==='monthly')editingRule.month_days=(p.month_days||[1]).slice();if(p.type==='interval')editingRule.interval_minutes=p.interval_minutes||60;if($('#r-type'))$('#r-type').value=p.type;if($('#r-time'))$('#r-time').value=editingRule.time;let nm=$('#r-name');if(nm&&(!nm.value.trim()||RULE_PRESETS.some(x=>x.name===nm.value.trim())))nm.value=p.name;detailRender();updateRuleLiveSummary();markActivePreset();toast(`「${p.label}」の条件を入力しました。個別に調整できます`)}
function onRuleFormChange(){updateRuleLiveSummary();markActivePreset()}
function openRule(r,isNew=false){editingRule=structuredClone(r);editingRule._new=isNew;$('#r-id').value=r.id;$('#r-name').value=r.name;$('#r-enabled').checked=r.enabled;$('#r-type').value=r.type;$('#r-time').value=r.time||'06:00';detailRender();updateRuleLiveSummary();renderPresets();$('#rule-editor').showModal()}$('#r-type').onchange=()=>{editingRule.type=$('#r-type').value;detailRender();onRuleFormChange()};
$$('#r-type-seg .pattern-card').forEach(c=>c.onclick=()=>{$('#r-type').value=c.dataset.type;if(editingRule)editingRule.type=c.dataset.type;detailRender();onRuleFormChange()});
$$('#r-time-wrap .time-chip').forEach(b=>b.onclick=()=>{if($('#r-time'))$('#r-time').value=b.dataset.time;onRuleFormChange()});
if($('#rule-editor')){$('#rule-editor').addEventListener('input',onRuleFormChange);$('#rule-editor').addEventListener('change',onRuleFormChange)}
$('#rule-apply').onclick=e=>{e.preventDefault();editingRule.name=$('#r-name').value.trim();editingRule.enabled=$('#r-enabled').checked;editingRule.type=$('#r-type').value;editingRule.time=$('#r-time').value;if(editingRule.type==='weekdays')editingRule.weekdays=$$('#r-detail input:checked').map(x=>Number(x.value));if(editingRule.type==='monthly')editingRule.month_days=$('#r-monthdays').value.split(',').map(Number).filter(Number.isFinite);if(editingRule.type==='interval')editingRule.interval_minutes=Number($('#r-interval').value);if(editingRule.type==='specific_dates')editingRule.dates=$('#r-dates').value.split(',').map(x=>x.trim()).filter(Boolean);delete editingRule._new;let i=editing.schedules.findIndex(r=>r.id===editingRule.id);if(i<0)editing.schedules.push(editingRule);else editing.schedules[i]=editingRule;$('#rule-editor').close();rulesRender()};
function updateEngineUI(){let engine=$('#extract-engine')?.value||'api',api=engine==='api',badge=$('#engine-scope-badge');$$('.engine-card').forEach(c=>{let on=c.dataset.engine===engine;c.classList.toggle('on',on);c.setAttribute('aria-selected',on?'true':'false')});$$('.engine-api-only').forEach(el=>el.style.display=api?'':'none');$$('.engine-dde-only').forEach(el=>el.style.display=api?'none':'');if(badge){badge.textContent=api?'選択中: Navigator API（並列処理を使用）':'選択中: DDE互換（画面制御を使用）';badge.classList.remove('pill-muted');badge.classList.add('pill-active')}}
function setExtractEngine(v){let s=$('#extract-engine');if(s)s.value=v;updateEngineUI();dirty()}function updateHideProfileUI(){let p=$('#hide-profile').value,custom=p==='custom';$('#hide-interval-wrap').style.display=custom?'grid':'none';$('#hide-action-duration-wrap').style.display=custom?'grid':'none';let descriptions={action_only:'DDE操作直後だけ確認。常時監視なし',light:'3秒間隔。負荷を最優先',balanced:'2秒間隔。負荷と非表示性のバランス',standard:'1秒間隔。非表示性を優先',custom:'1秒以上で任意設定'};$('#hide-profile').title=descriptions[p]||''}async function init(){cfg=await fetch('/api/config').then(r=>r.json());cfg.jobs.forEach(j=>{j.id=j.id||uid();j.name=j.name||j.rne.replace(/\.RNE$/i,'');j.schedules=j.schedules||[]});$('#cred').textContent=cfg.credential_status;$('#pathform').innerHTML=Object.entries(paths).map(([k,a])=>`<label>${a[0]}<div class="browse"><input id="${k}" value="${E(cfg[k]||'')}"><div class="path-actions">${['navigator_api_dll','symnavim_conf','symnavim_def','accdb_template'].includes(k)?`<button class="pathcheck verify-btn" data-k="${k}" type="button">確認</button>`:''}<button class="pathpick browse-btn" data-k="${k}" type="button">参照</button></div></div></label>`).join('');Object.entries(paths).forEach(([k,a])=>{$('#'+k).onchange=e=>{cfg[k]=e.target.value;dirty()};document.querySelector(`[data-k="${k}"]`).onclick=async()=>{let p=await browse(a[1],cfg[k],a[2]);if(p){cfg[k]=p;$('#'+k).value=p;dirty()}}});$('#extract-engine').value=cfg.settings.extract_engine||'api';updateEngineUI();$('#dde').value=cfg.settings.dde_timeout_seconds;$('#wait').value=cfg.settings.output_wait_seconds;$('#gens').value=cfg.settings.backup_generations;if($('#api-lines')){$('#api-lines').value=Math.max(1,Math.min(8,Number(cfg.settings.api_parallel_lines||2)));$('#api-lines').title='既定は2ラインです。変更するとその値が即時保存され、次回起動以降も保持されます。'}$('#zero').checked=cfg.settings.reject_zero_rows;$('#hide-profile').value=cfg.settings.symnavi_hide_profile||'balanced';$('#hide-interval').value=Math.max(1,Number(cfg.settings.symnavi_hide_interval_seconds||2));$('#hide-action-duration').value=Number(cfg.settings.symnavi_hide_action_duration_seconds||0.5);updateHideProfileUI();Object.keys(paths).forEach(k=>enhancePathInput($('#'+k),paths[k][1]));fillSuggestions();render();$('#dirty').textContent='設定を読み込みました';$$('.pathcheck').forEach(b=>b.onclick=()=>checkConfiguredPath(b.dataset.k))}
['search','filter-enabled','filter-schedule','sort'].forEach(k=>$('#'+k).addEventListener(k==='search'?'input':'change',render));$$('.sortable').forEach(h=>h.onclick=()=>{$('#sort').value=h.dataset.sort;sortDir*=-1;render()});$('#add').onclick=()=>openEditor(null);$('#select-visible').onclick=()=>{$$('#jobs-body .rowcheck').forEach(x=>{x.checked=true;x.closest('tr').classList.add('selected')})};$('#clear-selection').onclick=()=>{$$('#jobs-body .rowcheck').forEach(x=>{x.checked=false;x.closest('tr').classList.remove('selected')})};function resetProgressView(){let q=$('#queue-summary');if(q){q.hidden=true;q.innerHTML=''}let b=$('#p-parallel-lines');if(b){b.hidden=true;b.innerHTML=''}document.querySelector('.current-box')?.classList.remove('parallel-hidden');$('#p-steps')?.classList.remove('parallel-hidden');$('#p-count').textContent='全体 0 / 0';$('#p-percent').textContent='0%';$('#p-bar').style.width='0%';$('#p-job').textContent='準備中';$('#p-output').textContent='';}async function runJobs(ids){resetProgressView();showWaiting(currentEngine()==='api'?'API処理を開始しています':'DDE処理を開始しています',currentEngine()==='api'?'APIセッションと実行対象を準備しています...':'SymfoNavi起動とDDE接続を準備しています...','engine');let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_ids:ids,parallel_lines:Math.max(1,Math.min(8,Number($('#api-lines')?.value||2)||2))})}),d=await r.json();hideWaiting();if(r.ok){toast(`実行キュー ${d.position}番へ追加しました`);await loadCommandQueue()}else toast(d.error)}$('#run-all').onclick=()=>runJobs(null);$('#run-selected').onclick=()=>{let ids=$$('#jobs-body .rowcheck:checked').map(x=>x.closest('tr').dataset.id);ids.length?runJobs(ids):toast('実行対象を選択してください')};$('#save').onclick=async()=>{cfg.settings.extract_engine=$('#extract-engine').value;cfg.settings.dde_timeout_seconds=Number($('#dde').value);cfg.settings.output_wait_seconds=Number($('#wait').value);cfg.settings.backup_generations=Number($('#gens').value);cfg.settings.api_parallel_lines=Math.max(1,Math.min(8,Number($('#api-lines')?.value||2)||2));cfg.settings.stability_profile='balanced_api_parallel';cfg.settings.reject_zero_rows=$('#zero').checked;cfg.settings.symnavi_hide_profile=$('#hide-profile').value;cfg.settings.symnavi_hide_interval_seconds=Math.max(1,Number($('#hide-interval').value)||2);cfg.settings.symnavi_hide_action_duration_seconds=Math.max(.2,Number($('#hide-action-duration').value)||.5);delete cfg.credential_status;let r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});if(r.ok){$('#dirty').textContent='設定を保存しました';await init();toast('設定DBへ保存し、再読込しました')}};$('#validate').onclick=async()=>{showWaiting(currentEngine()==='api'?'API実行前診断中':'DDE実行前診断中',currentEngine()==='api'?'API DLL、RNE、出力先、変換環境を確認しています...':'SymfoNavi、DDE設定、RNE、出力先を確認しています...','engine');try{let d=await fetch('/api/validate',{method:'POST'}).then(r=>r.json());$('#check-scope').textContent='候補検索範囲: '+d.search_scope;$('#checks').innerHTML=d.checks.map((x,i)=>`<div class="check"><b class="${x.ok?'ok':'ng'}">${x.ok?'OK':'NG'}</b><strong>${E(x.label)}</strong><span>${E(x.detail)}${x.needs_reselect?'<br><em class="reselect">候補なし。再指定してください。</em>':''}</span>${x.candidates?.length?`<button class="fix secondary" data-i="${i}">候補 ${x.candidates.length}件</button>`:''}</div>`).join('');$$('#checks .fix').forEach(b=>b.onclick=()=>showPathResult(d.checks[Number(b.dataset.i)]))}finally{hideWaiting()}};let commandQueueOpen=false;async function loadCommandQueue(){try{let d=await fetch('/api/execution-queue',{cache:'no-store'}).then(r=>r.json()),list=$('#cq-list'),summary=$('#cq-summary');applyRowQueueProgress(d);if(!list||!summary)return;
 let st=latestStatus||{},running=!!st.running;
 // 実行中バッチの対象(job)単位の実状態。バッジ件数を実進捗に連動させる。
 let jobDone=running?(st.queue_completed_ids||[]).length:0,jobFail=running?(st.queue_failed_ids||[]).length:0;
 let jobRun=running?(st.execution_mode==='parallel'?(st.queue_running_ids||[]).length:(st.current_job_id?1:0)):0;
 let batchLen=running?((st.batch_job_ids||[]).length):0;
 let batchWait=Math.max(0,batchLen-jobDone-jobFail-jobRun);
 // 実行待ちキュー（未開始の実行指令）に含まれる対象数。
 let queuedJobs=d.items.filter(x=>x.state==='waiting').reduce((s,x)=>s+(x.count||1),0);
 let totalWait=batchWait+queuedJobs;
 let isSched=x=>String(x.trigger||'').startsWith('schedule');
 let schedJobs=d.items.filter(isSched).reduce((s,x)=>s+(x.count||1),0),manualJobs=d.items.filter(x=>!isSched(x)).reduce((s,x)=>s+(x.count||1),0);
 if(!running&&!d.items.length){summary.innerHTML='<span class="cq-badge cq-idle">待機なし</span>';}
 else{summary.innerHTML=
  `<span class="cq-badge cq-run">処理中 ${jobRun}件</span>`+
  `<span class="cq-badge cq-done">完了 ${jobDone}件</span>`+
  (jobFail?`<span class="cq-badge cq-fail">失敗 ${jobFail}件</span>`:'')+
  `<span class="cq-badge cq-wait">待機 ${totalWait}件</span>`+
  `<span class="cq-badge cq-sep" aria-hidden="true"></span>`+
  `<span class="cq-badge cq-auto">定期 ${schedJobs}件</span>`+
  `<span class="cq-badge cq-manual">即実行 ${manualJobs}件</span>`;}
 list.innerHTML=d.items.length?d.items.map(x=>{
  let stateInfo=x.state==='running'?(running?`処理中 ${jobRun} / 完了 ${jobDone}${jobFail?' / 失敗 '+jobFail:''} / 待機 ${batchWait}`:'処理中'):`${x.position}番目に実行予定`;
  return `<div class="cq-row ${x.state}"><span class="cq-pos">${x.state==='running'?'実行中':x.position+'番'}</span><div class="cq-main"><b>${E((x.job_names||[]).join(' / '))}</b><small>${x.state==='running'?E(stateInfo):('登録 '+E(x.enqueued_at||'')+' / '+(x.count||0)+'対象')}</small></div><span class="cq-mode">${x.parallel_lines>1?x.parallel_lines+'ライン':'安定1ライン'}</span><div class="cq-actions">${x.state==='waiting'?`<button class="secondary cq-up" data-id="${x.id}">上へ</button><button class="secondary cq-down" data-id="${x.id}">下へ</button><button class="danger cq-delete" data-id="${x.id}">解除</button>`:'<span>処理中は変更不可</span>'}</div></div>`}).join(''):'<div class="cq-empty">実行待ちのキューはありません</div>';list.hidden=!commandQueueOpen;$$('.cq-up,.cq-down').forEach(b=>b.onclick=async()=>{await fetch(`/api/execution-queue/${b.dataset.id}/move`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({direction:b.classList.contains('cq-up')?'up':'down'})});loadCommandQueue()});$$('.cq-delete').forEach(b=>b.onclick=async()=>{let r=await fetch(`/api/execution-queue/${b.dataset.id}`,{method:'DELETE'});if(r.ok)toast('実行キューから解除しました');loadCommandQueue()})}catch{}}{const cqToggle=$('#cq-toggle');if(cqToggle)cqToggle.onclick=()=>{commandQueueOpen=!commandQueueOpen;cqToggle.textContent=commandQueueOpen?'閉じる':'一覧';loadCommandQueue()};}function logLevel(line){return line.includes('[ERROR]')?'error':line.includes('[WARNING]')?'warning':'info'}function buildLogTree(text){let lines=(text||'').split(/\r?\n/).filter(Boolean),groups=[],current=null,job=null;for(let line of lines){if(line.includes('処理開始 trigger=')){current={title:line.slice(0,19)+'  実行指令',lines:[],jobs:[]};groups.push(current);job=null}else if(line.includes('設定保存 job=')){current={title:line.slice(0,19)+'  設定保存',lines:[line],jobs:[]};groups.push(current);job=null;continue}if(!current){current={title:'その他のログ',lines:[],jobs:[]};groups.push(current)}let m=line.match(/(?:PIPELINE|JOB_RESULT) job=([^ ]+)/);if(m){job=current.jobs.find(x=>x.name===m[1])||{name:m[1],lines:[]};if(!current.jobs.includes(job))current.jobs.push(job)}if(job)job.lines.push(line);else current.lines.push(line);if(line.includes('正常終了')||line.includes('異常終了'))job=null}return groups}function logLines(lines){return `<div class="log-lines">${lines.map(x=>`<div class="log-line ${logLevel(x)}">${E(x)}</div>`).join('')}</div>`}function renderLogTree(text){let groups=buildLogTree(text);renderedLogGroups=groups.slice().reverse();$('#log').innerHTML=renderedLogGroups.length?renderedLogGroups.map((g,gi)=>`<details class="log-action" ${gi===0?'open':''} data-gi="${gi}"><summary><span><b>実行指令 ${renderedLogGroups.length-gi}</b> ${E(g.title)}</span><small>${g.jobs.length}ファイル</small><span class="log-summary-actions"><button class="secondary log-copy-full" data-gi="${gi}">全文コピー</button><button class="secondary log-copy-summary" data-gi="${gi}">要約コピー</button><button class="secondary danger-lite log-delete-group" data-gi="${gi}">削除</button></span></summary>${g.lines.length?logLines(g.lines):''}${g.jobs.map(j=>`<details class="log-job"><summary>${E(j.name)} <small>${j.lines.length}行</small></summary>${logLines(j.lines)}</details>`).join('')}</details>`).join(''):'<div class="empty">ログなし</div>';$$('.log-copy-full').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();let g=renderedLogGroups[Number(b.dataset.gi)];textToClipboard(groupText(g,'full'),'選択した実行指令ログをコピーしました')});$$('.log-copy-summary').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();let g=renderedLogGroups[Number(b.dataset.gi)];textToClipboard(groupText(g,'summary'),'選択した実行指令の要約ログをコピーしました')});$$('.log-delete-group').forEach(b=>b.onclick=async e=>{e.preventDefault();e.stopPropagation();let g=renderedLogGroups[Number(b.dataset.gi)],txt=groupText(g,'full');if(!confirm('この実行指令ログを削除しますか？'))return;let r=await fetch('/api/log/delete-lines',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:txt.split(/\n/)})});if(r.ok){toast('選択した実行指令ログを削除しました');await loadLog()}})}let latestLogText='',renderedLogGroups=[];async function loadLog(){let d=await fetch('/api/log').then(r=>r.json());latestLogText=d.text||'';renderLogTree(latestLogText)}function textToClipboard(text,msg){if(!text?.trim())return toast('コピー対象のログがありません');navigator.clipboard?.writeText(text).then(()=>toast(msg)).catch(()=>{let ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast(msg)})}function groupText(g,mode='full'){let lines=[];lines.push(...(g.lines||[]));(g.jobs||[]).forEach(j=>lines.push(...j.lines));if(mode==='summary')lines=lines.filter(x=>/処理開始|STARTUP_PHASE|PIPELINE|STEP_END phase=(api_open_catalog|api_execute_catalog|api_save_csv|api_save_xlsx_direct|format_conversion|publish)|ACCDB_|SQLITE_|XLSX_|PUBLISH_|JOB_RESULT|正常終了|異常終了/.test(x));return lines.join('\n').trim()}function copyAllLog(){textToClipboard(latestLogText,'表示中のログ全体をコピーしました')}async function copyReportLog(){await loadLog();let g=renderedLogGroups[0];if(g)return textToClipboard(groupText(g),'最新の実行指令ログをコピーしました');let lines=latestLogText.split(/\r?\n/),start=-1;for(let i=lines.length-1;i>=0;i--){if(lines[i].includes('処理開始 trigger=')){start=i;break}}textToClipboard((start>=0?lines.slice(start):lines).join('\n').trim(),'最新の実行指令ログをコピーしました')}async function clearLog(){if(!confirm('表示中の実行ログを消去しますか？'))return;let r=await fetch('/api/log/clear',{method:'POST'});if(r.ok){latestLogText='';renderLogTree('');toast('ログを消去しました')}}if($('#copy-all-log'))$('#copy-all-log').onclick=async()=>{await loadLog();copyAllLog()};if($('#copy-report-log'))$('#copy-report-log').onclick=copyReportLog;if($('#clear-log'))$('#clear-log').onclick=clearLog;if($('#reload'))$('#reload').onclick=loadLog;if($('#expand-logs'))$('#expand-logs').onclick=()=>$$('#log details').forEach(x=>x.open=true);if($('#collapse-logs'))$('#collapse-logs').onclick=()=>$$('#log details').forEach(x=>x.open=false);let lastRunning=false,lastTerminalShownKey='',activeRunId='',activeExecutionMode='serial',dismissedRunIds=new Set();const stepOrder=['prepare','launch','dde','ready','open','save','close','wait','export','publish','complete'];function showProgress(){let d=$('#progress-dialog');if(!d.open)d.showModal()}function hhmmss(v){v=Math.floor(Math.max(0,Number(v)||0));return [Math.floor(v/3600),Math.floor((v%3600)/60),v%60].map(x=>String(x).padStart(2,'0')).join(':')}
function laneColumns(n){return ({1:1,2:2,3:3,4:4,5:3,6:3,7:4,8:4})[n]||Math.max(1,Math.min(4,n||1))}function applyProgressEngine(engine){let api=engine==='api';$$('#p-steps li[data-api]').forEach(li=>li.textContent=api?li.dataset.api:li.dataset.dde);$('#p-engine').textContent=api?'抽出方式: Navigator API':'抽出方式: DDE互換'}function updateProgress(s){if(activeRunId&&s.run_id!==activeRunId)return;let engine=s.extract_engine||cfg?.settings?.extract_engine||'api';applyProgressEngine(engine);let isParallel=(s.execution_mode==='parallel');$('#progress-dialog .progress-modal').classList.toggle('serial-mode',!isParallel);$('#progress-dialog .progress-modal').classList.toggle('parallel-mode',isParallel);let overall=s.total_jobs?Math.round(((Math.max(0,s.current_index-1)+(s.step_percent||0)/100)/s.total_jobs)*100):(s.step_percent||0);if(s.step==='complete'||s.step==='error')overall=100;$('#p-title').textContent=s.step_label||'処理中';$('#p-count').textContent=`全体 ${s.completed_jobs||0} / ${s.total_jobs||0}`;$('#p-percent').textContent=overall+'%';$('#p-bar').style.width=overall+'%';$('#p-job').textContent=s.current_job_name||'準備中';let j=cfg?.jobs?.find(x=>x.id===s.current_job_id),fmt=s.output_format||j?.output_format,file=s.output_file||j?.output_file,target=s.output_target||(j?`${j.output_folder||cfg.default_output_folder}\\${file}`:'');$('#p-output').textContent=fmt?`${formatName(fmt)} → ${target}`:'';let liveElapsed=s.started_at?Math.max(Number(s.elapsed_seconds)||0,Math.floor((Date.now()-new Date(s.started_at).getTime())/1000)):(s.elapsed_seconds||0);$('#p-elapsed').textContent='経過時間 '+hhmmss(liveElapsed);$('#p-activity span').textContent=[s.activity_detail,s.activity_value].filter(Boolean).join(' / ')||'処理を継続しています';$('#p-engine').textContent=(s.execution_mode==='parallel'?`API並列 ${s.requested_lines||1}ライン`:'API安定運転 1ライン')+' / '+(s.running?'処理中':'終了');let box=document.querySelector('#p-parallel-lines');if(!box){box=document.createElement('div');box.id='p-parallel-lines';box.className='parallel-lines fixed-lanes';document.querySelector('.current-box')?.after(box)}let pls=(s.parallel_lines||[]).slice().sort((a,b)=>Number(String(a.line).match(/\d+/)?.[0]||0)-Number(String(b.line).match(/\d+/)?.[0]||0));let total=Number(s.queue_total||0),waiting=Number(s.queue_waiting||0),active=Number(s.queue_active||0),completed=Number(s.queue_completed||0),lineCount=Number(s.parallel_max_lines||pls.length||0),parallel=(s.execution_mode==='parallel'&&s.run_id===activeRunId);if(lineCount)box.style.setProperty('--lane-cols',laneColumns(lineCount));let queue=$('#queue-summary');if(queue){queue.hidden=!parallel;queue.innerHTML=parallel?`<div><small>予約総数</small><strong>${total}</strong></div><div class="queue-arrow">→</div><div class="q-active"><small>実行中</small><strong>${active}</strong><span>${lineCount}ライン</span></div><div class="q-wait"><small>待機</small><strong>${waiting}</strong></div><div class="q-done"><small>完了</small><strong>${completed}</strong></div>`:'';}document.querySelector('.current-box')?.classList.toggle('parallel-hidden',parallel);$('#p-steps')?.classList.toggle('parallel-hidden',parallel);box.hidden=!parallel;if(parallel){let byLine=new Map(pls.map(x=>[x.line,x]));let stable=[];for(let n=1;n<=lineCount;n++)stable.push(byLine.get(`ライン ${n}`)||{line:`ライン ${n}`,job:'',state:'待機',percent:0,detail:'次の予約を待機',elapsed:0});box.innerHTML=stable.map(x=>{let state=String(x.state||'待機'),cls=state.includes('完了')?'is-done':state.includes('失敗')?'is-error':state.includes('待機')?'is-wait':'is-running';return `<article class="pline ${cls}"><header><b>${E(x.line)}</b><span>${E(state)}</span></header><strong title="${E(x.job||'')}">${E(x.job||'予約待ち')}</strong><div class="lane-progress"><i style="width:${Math.max(0,Math.min(100,Number(x.percent||0)))}%"></i></div><footer><small>${E(x.detail||'')}</small><time>${hhmmss(x.elapsed||0)}</time></footer></article>`}).join('')}else box.innerHTML='';let current=stepOrder.indexOf(s.step);$$('#p-steps li').forEach(li=>{let i=stepOrder.indexOf(li.dataset.step);li.className=s.step==='error'&&i===Math.max(0,current)?'error':i<current?'done':i===current?'active':''});let failed=s.step==='error',cancelled=s.step==='cancelled',done=s.step==='complete'||cancelled;$('#p-state').textContent=failed?'失敗':cancelled?'中断済み':done?'完了':'実行中';$('#p-state').classList.toggle('running',!failed&&!done);$('#p-activity i').style.display=(failed||done)?'none':'block';$('#p-state').style.background=failed?'#fff0ee':cancelled?'#f3eee0':done?'#e5f5ef':'#e6f4f6';$('#p-error').hidden=!failed;$('#p-error').textContent=failed?(s.error_detail||s.last_result):'';$('#p-background').hidden=failed||done;$('#p-close').hidden=!(failed||done);let terminalKey=(s.started_at||'')+'|'+s.step;if((failed||done)&&!dismissedRunIds.has(activeRunId)&&terminalKey!==lastTerminalShownKey){lastTerminalShownKey=terminalKey;showProgress()}}$('#p-background').onclick=()=>{dismissedRunIds.add(activeRunId);$('#progress-dialog').close();toast('上部の処理インジケータから進捗を再表示できます')};$('#p-close').onclick=()=>{dismissedRunIds.add(activeRunId);$('#progress-dialog').close();resetProgressView()};async function openProgressModal(){if(!lastRunning)return;try{let s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());if(s.run_id){activeRunId=s.run_id;activeExecutionMode=s.execution_mode||'serial';dismissedRunIds.delete(activeRunId);updateProgress(s);showProgress()}}catch{toast('進捗情報を取得できませんでした')}}$('.runtime').onclick=openProgressModal;async function poll(){try{let s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());statusFailCount=0;hideServerLost();latestStatus=s;lastRunning=s.running;if(s.running&&s.run_id&&!activeRunId){activeRunId=s.run_id;activeExecutionMode=s.execution_mode||'serial';dismissedRunIds.add(activeRunId)}$('#st').textContent=s.running?'処理中':s.step==='error'?'処理失敗':s.step==='cancelled'?'中断済み':'待機中';$('#sub').textContent=s.running?s.step_label:(s.last_finished_at||'実行待ち');$('#dot').style.background=s.running?'#f0b429':s.step==='error'?'#e45b50':s.step==='cancelled'?'#8a94a0':'#3ed1a0';$('.runtime').classList.toggle('processing',s.running);$('#run-all').disabled=false;$('#run-selected').disabled=false;loadCommandQueue();applyRowLiveProgress(s);if(activeRunId&&s.run_id===activeRunId&&(s.running||s.step==='complete'||s.step==='error'||s.step==='cancelled'))updateProgress(s)}catch{$('#st').textContent='接続エラー';statusFailCount++;if(statusFailCount>=3)showServerLost()}}
async function testNavigatorApi(){let b=$('#api-test'),out=$('#api-status');b.disabled=true;out.textContent='診断中';showWaiting('Navigator APIを診断中','DLL候補、ビット数、依存関係、API関数を確認しています...','api');try{let d=await fetch('/api/navigator-api-status').then(r=>r.json());out.textContent=d.ok?`利用可能 / DLL ${d.dll_bits||'?'}bit / Python ${d.python_bits}bit / ${d.dll}`:`利用不可 / ${d.error}`;out.title=(d.attempts||[]).map(x=>`${x.exists?'存在':'なし'} / DLL ${x.dll_bits||'?'}bit / Python ${x.python_bits||'?'}bit / ${x.path}${x.error?' / '+x.error:''}`).join('\n');out.className=d.ok?'ok':'ng'}finally{hideWaiting();b.disabled=false}}$('#api-test').onclick=testNavigatorApi;$('#extract-engine').onchange=()=>{updateEngineUI();dirty()};$$('.engine-card').forEach(c=>c.onclick=()=>setExtractEngine(c.dataset.engine));setInterval(poll,1000);init().then(()=>{poll();loadCommandQueue();testNavigatorApi()})

$('#suggest-close').onclick=()=>$('#path-suggestion').close();
async function waitUntilNotRunning(timeoutMs){let start=Date.now();while(Date.now()-start<timeoutMs){try{let s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());if(!s.running)return true}catch{return false}await new Promise(r=>setTimeout(r,500))}return false}
$('#app-exit').onclick=async()=>{if(lastRunning){if(!confirm('スケジュール実行が進行中です。中断してアプリを終了しますか？\n実行中の1件は安全な区切りまで進めてから停止し、以降の予約は開始しません。'))return;toast('実行を中断しています…');try{await fetch('/api/run/cancel',{method:'POST'})}catch{}await waitUntilNotRunning(20000)}else if(!confirm('SymfoNavi Data Hubを終了しますか？')){return}try{await fetch('/api/shutdown-app',{method:'POST'});document.body.innerHTML='<main style="max-width:680px;margin:80px auto;padding:24px"><article class="panel"><h2>アプリを終了しました</h2><p>このブラウザータブを閉じてください。</p></article></main>'}catch{window.close()}};

function resetEditorState(){editing=null;editingRule=null;$('#editor form')?.reset();$('#rule-editor form')?.reset();if($('#m-rules'))$('#m-rules').innerHTML='';if($('#r-detail'))$('#r-detail').innerHTML=''}$('#editor').addEventListener('close',resetEditorState);$('#rule-editor').addEventListener('close',()=>{editingRule=null;$('#rule-editor form')?.reset();if($('#r-detail'))$('#r-detail').innerHTML=''});$('#path-suggestion').addEventListener('close',()=>{$('#suggest-content').innerHTML=''});window.addEventListener('pageshow',()=>{$$('dialog').forEach(d=>{if(d.open)d.close()});resetEditorState()});

if($('#api-lines'))$('#api-lines').addEventListener('change',async e=>{let v=Math.max(1,Math.min(8,Number(e.target.value)||2));e.target.value=v;cfg.settings.api_parallel_lines=v;cfg.settings.stability_profile='balanced_api_parallel';try{let r=await fetch('/api/settings/parallel-lines',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:v})});if(r.ok)toast(`並列ライン数を${v}ラインで保存しました（次回以降も保持）`);else{dirty();toast(`次回実行は${v}ラインです（保存失敗のため設定を保存してください）`)}}catch{dirty();toast(`次回実行は${v}ラインです（保存失敗のため設定を保存してください）`)}});$('#hide-profile').addEventListener('change',()=>{updateHideProfileUI();dirty()});$('#hide-interval').addEventListener('change',e=>{e.target.value=Math.max(1,Number(e.target.value)||1);dirty()});$('#hide-action-duration').addEventListener('change',dirty);


/* V29: vertical progress and structured log workspace */
function logKind(line){if(line.includes('[ERROR]')||line.includes('異常終了')||line.includes('FAILED')||line.includes('失敗'))return'error';if(line.includes('設定保存'))return'setting';if(line.includes('COMMAND_QUEUE'))return'queue';if(/PUBLISH_|phase=publish/.test(line))return'publish';if(/STARTUP_PHASE|STEP_END|elapsed=|SQLITE_|INTERMEDIATE_VALIDATION|PARALLEL_BATCH_END|JOB_RESULT/.test(line))return'performance';return'execution'}
function logKindLabel(k){return{execution:'実行',setting:'設定',queue:'キュー',performance:'計測',publish:'公開',error:'エラー'}[k]||'実行'}
function logMatches(line){let q=($('#log-filter-text')?.value||'').trim().toLowerCase(),k=$('#log-filter-kind')?.value||'all',lv=$('#log-filter-level')?.value||'all';return(!q||line.toLowerCase().includes(q))&&(k==='all'||logKind(line)===k)&&(lv==='all'||logLevel(line)===lv)}
function logLines(lines){return`<div class="log-lines">${lines.map(x=>{let k=logKind(x);return`<div class="log-line ${logLevel(x)} kind-${k}${logMatches(x)?'':' hidden-by-filter'}" data-line="${E(x)}"><input class="log-select" type="checkbox" aria-label="このログ行を選択"><span class="log-kind">${logKindLabel(k)}</span><span class="log-text">${E(x)}</span></div>`}).join('')}</div>`}
function filteredLogLines(){return $$('#log .log-line:not(.hidden-by-filter)').map(x=>x.dataset.line||'').filter(Boolean)}
function selectedLogLines(){return $$('#log .log-select:checked').map(x=>x.closest('.log-line')?.dataset.line||'').filter(Boolean)}
function updateLogSummary(){let a=$$('#log .log-line').length,v=$$('#log .log-line:not(.hidden-by-filter)').length,s=$$('#log .log-select:checked').length;if($('#log-filter-summary'))$('#log-filter-summary').textContent=`表示 ${v}行 / 全体 ${a}行 / 選択 ${s}行`}
function applyLogFilter(){ $$('#log .log-line').forEach(x=>x.classList.toggle('hidden-by-filter',!logMatches(x.dataset.line||'')));$$('#log .log-job,#log .log-action').forEach(x=>x.style.display=x.querySelector('.log-line:not(.hidden-by-filter)')?'':'none');updateLogSummary() }
function renderLogTree(text){let groups=buildLogTree(text);renderedLogGroups=groups.slice().reverse();$('#log').innerHTML=renderedLogGroups.length?renderedLogGroups.map((g,gi)=>`<details class="log-action" ${gi===0?'open':''} data-gi="${gi}"><summary><span><b>実行指令 ${renderedLogGroups.length-gi}</b> ${E(g.title)}</span><small>${g.jobs.length}ファイル</small><span class="log-summary-actions"><button class="secondary log-copy-full" data-gi="${gi}">全文コピー</button><button class="secondary log-copy-summary" data-gi="${gi}">要約コピー</button><button class="secondary danger-lite log-delete-group" data-gi="${gi}">削除</button></span></summary>${g.lines.length?logLines(g.lines):''}${g.jobs.map(x=>`<details class="log-job"><summary>${E(x.name)} <small>${x.lines.length}行</small></summary>${logLines(x.lines)}</details>`).join('')}</details>`).join(''):'<div class="empty">ログなし</div>';$$('.log-copy-full').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();textToClipboard(groupText(renderedLogGroups[Number(b.dataset.gi)],'full'),'実行指令ログをコピーしました')});$$('.log-copy-summary').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();textToClipboard(groupText(renderedLogGroups[Number(b.dataset.gi)],'summary'),'要約ログをコピーしました')});$$('.log-delete-group').forEach(b=>b.onclick=async e=>{e.preventDefault();e.stopPropagation();let lines=groupText(renderedLogGroups[Number(b.dataset.gi)],'full').split(/\n/);if(confirm('この実行指令ログを削除しますか？'))await deleteLogRows(lines,'実行指令ログを削除しました')});$$('.log-select').forEach(x=>x.onchange=updateLogSummary);applyLogFilter()}
async function deleteLogRows(lines,message){if(!lines.length)return toast('対象ログがありません');let r=await fetch('/api/log/delete-lines',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines})});if(r.ok){toast(message);await loadLog()}else toast('ログを削除できませんでした')}
function bindV29LogWorkspace(){['log-filter-text','log-filter-kind','log-filter-level'].forEach(id=>{let x=$('#'+id);if(x)x.addEventListener(id==='log-filter-text'?'input':'change',applyLogFilter)});if($('#select-filtered-log'))$('#select-filtered-log').onclick=()=>{$$('#log .log-line:not(.hidden-by-filter) .log-select').forEach(x=>x.checked=true);updateLogSummary()};if($('#clear-log-selection'))$('#clear-log-selection').onclick=()=>{$$('#log .log-select').forEach(x=>x.checked=false);updateLogSummary()};if($('#copy-filtered-log'))$('#copy-filtered-log').onclick=()=>textToClipboard(filteredLogLines().join('\n'),'表示中のログをコピーしました');if($('#delete-selected-log'))$('#delete-selected-log').onclick=()=>{let x=selectedLogLines();if(x.length&&confirm(`選択した${x.length}行を削除しますか？`))deleteLogRows(x,'選択ログを削除しました')};if($('#delete-filtered-log'))$('#delete-filtered-log').onclick=()=>{let x=filteredLogLines();if(x.length&&confirm(`表示中の${x.length}行を削除しますか？`))deleteLogRows(x,'表示中のログを削除しました')};if($('#delete-old-log'))$('#delete-old-log').onclick=async()=>{let days=Number($('#log-retention-days')?.value||30);if(!confirm(`${days}日以前のログを一括削除しますか？`))return;let r=await fetch('/api/log/delete-old',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days})}),d=await r.json();if(r.ok){toast(`${d.removed}行の古いログを削除しました`);await loadLog()}else toast(d.error||'古いログを削除できませんでした')}}
bindV29LogWorkspace();

/* V30: categorized settings navigation and in-app version management */
function bindSettingsNav(){$$('#settings-nav .settings-navbtn').forEach(b=>b.onclick=()=>{$$('#settings-nav .settings-navbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');$$('.settings-pane').forEach(x=>x.classList.remove('on'));document.querySelector(`.settings-pane[data-cat="${b.dataset.cat}"]`)?.classList.add('on')})}
function renderChangelog(list){return (list||[]).map(e=>`<div class="changelog-entry"><div class="changelog-head"><b>${E(e.version)}</b>${e.date?`<time>${E(e.date)}</time>`:''}</div><div class="changelog-title">${E(e.title)}</div><ul>${(e.notes||[]).map(n=>`<li>${E(n)}</li>`).join('')}</ul></div>`).join('')}
async function loadVersion(){try{let d=await fetch('/api/version').then(r=>r.json()),meta=`ビルド: ${d.build_version}`+(d.released_at?` / リリース日: ${d.released_at}`:'');if($('#version-badge'))$('#version-badge').textContent='ver '+d.version;if($('#version-current'))$('#version-current').textContent=`${d.version} ${d.title}`;if($('#version-meta'))$('#version-meta').textContent=meta;if($('#version-changelog'))$('#version-changelog').innerHTML=renderChangelog(d.changelog);if($('#settings-version-summary'))$('#settings-version-summary').innerHTML=`<div class="version-current-badge"><b>${E(d.version)}</b><span>${E(d.title)}</span></div><p class="hint">${E(meta)}</p>`;if($('#settings-version-changelog'))$('#settings-version-changelog').innerHTML=renderChangelog(d.changelog)}catch{if($('#version-badge'))$('#version-badge').textContent='ver ?'}}
if($('#version-badge'))$('#version-badge').onclick=()=>{if(!$('#version-dialog').open)$('#version-dialog').showModal()};
if($('#version-close'))$('#version-close').onclick=()=>$('#version-dialog').close();
bindSettingsNav();loadVersion();

/* V32: unified progress display in the target file list — next scheduled run + live execution bar in one cell */
function nextRunLabel(iso){
 if(!iso)return '予定なし';
 let d=new Date(iso);if(isNaN(d))return '予定なし';
 let now=new Date(),hm=`${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
 let sameDay=d.toDateString()===now.toDateString();
 let tomorrow=new Date(now);tomorrow.setDate(now.getDate()+1);
 if(sameDay)return `本日 ${hm}`;
 if(d.toDateString()===tomorrow.toDateString())return `明日 ${hm}`;
 return `${d.getMonth()+1}/${d.getDate()}(${'日月火水木金土'[d.getDay()]}) ${hm}`;
}
function lastRunLabel(info){if(!info||!info.last_run)return '';let d=new Date(info.last_run);if(isNaN(d))return String(info.last_run);let hm=`${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;let st=info.last_status==='ok'?'✓完了':info.last_status==='failed'?'×失敗':info.last_status==='cancelled'?'▲中断':'';let trig=info.last_trigger==='schedule'?'定期':info.last_trigger==='manual'?'手動':'';return `${hm} ${st}${trig?' ('+trig+')':''}`.trim()}
function lastStatusClass(info){if(!info||!info.last_run)return 'none';return info.last_status==='ok'?'ok':info.last_status==='failed'?'ng':'warn'}
function rowProgressCell(j){
 let info=scheduleInfo[j.id],next=info&&info.next_run?nextRunLabel(info.next_run):(info&&info.hint==='対象が無効'?'対象が無効':'予定なし'),hint=info?(info.hint==='対象が無効'?'':info.hint):(j.enabled?'':'対象が無効');
 return `<div class="rowprogress" data-jobid="${j.id}"><div class="rp-schedule"><div class="rp-next-row"><span class="rp-next-label">次回</span><b class="rp-next">${E(next)}</b><span class="rp-hint">${E(hint)}</span></div><div class="rp-last-row"><span class="rp-last-label">直前</span><span class="rp-last ${lastStatusClass(info)}">${E(lastRunLabel(info)||'実施履歴なし')}</span></div></div><div class="rp-live"><div class="rp-live-top"><span class="rp-state"></span><time class="rp-elapsed"></time></div><div class="rp-track"><i class="rp-bar"></i></div><div class="rp-detail"></div></div></div>`;
}
async function loadSchedulePreview(){try{let d=await fetch('/api/schedule-preview').then(r=>r.json());scheduleInfo=Object.fromEntries((d.items||[]).map(x=>[x.id,x]));applyScheduleCells()}catch{}}
function applyScheduleCells(){$$('.rowprogress').forEach(el=>{if(el.classList.contains('is-running')||el.classList.contains('is-wait')||el.classList.contains('is-done')||el.classList.contains('is-error'))return;let j=cfg?.jobs?.find(x=>x.id===el.dataset.jobid);if(!j)return;let info=scheduleInfo[j.id],next=info&&info.next_run?nextRunLabel(info.next_run):(info&&info.hint==='対象が無効'?'対象が無効':'予定なし'),hint=info?(info.hint==='対象が無効'?'':info.hint):(j.enabled?'':'対象が無効');let nx=el.querySelector('.rp-next'),hn=el.querySelector('.rp-hint');if(nx)nx.textContent=next;if(hn)hn.textContent=hint;let ls=el.querySelector('.rp-last');if(ls){ls.textContent=lastRunLabel(info)||'実施履歴なし';ls.className='rp-last '+lastStatusClass(info)}})}
function jobStateClass(stateText){stateText=String(stateText||'');if(stateText.includes('失敗')||stateText.includes('中断'))return'is-error';if(stateText.includes('完了'))return'is-done';return'is-running'}
const ROW_DONE_HOLD_MS=6000;
/* 実行中の1バッチについて、対象(job_id)ごとの確定状態をクライアント側でも保持する。
   バックエンドの queue_completed_ids / queue_failed_ids を採用し、完了後に「順番待ち」へ戻る不具合を防ぐ。 */
let runCompletedIds=new Set(),runFailedIds=new Set(),runDoneMeta={},lastRunActive=false,runFinishedAt=0,latestStatus=null,rowRunId='';
function applyRowLiveProgress(s){
 let now=Date.now();
 // 新しい実行(run_id)を検知したら、前回バッチの確定状態をリセットする。
 if(s.run_id&&s.run_id!==rowRunId){rowRunId=s.run_id;runCompletedIds.clear();runFailedIds.clear();runDoneMeta={};lastRunActive=false;runFinishedAt=0;}
 let runningInfo={};
 // 現在ラインで処理中の対象（進捗つき）。完了・失敗はここではなく確定集合で扱う。
 if(s.running&&s.execution_mode==='parallel'){
  (s.parallel_lines||[]).forEach(x=>{if(!x.job_id||!x.job)return;let cls=jobStateClass(x.state);
   if(cls==='is-done'){runCompletedIds.add(x.job_id);runDoneMeta[x.job_id]={cls:'is-done',state:x.state||'完了',detail:x.detail||'処理が完了しました',elapsed:x.elapsed||0,percent:100};}
   else if(cls==='is-error'){runFailedIds.add(x.job_id);runDoneMeta[x.job_id]={cls:'is-error',state:x.state||'失敗',detail:x.detail||'',elapsed:x.elapsed||0,percent:100};}
   else{runningInfo[x.job_id]={cls:'is-running',state:x.state||'',detail:x.detail||'',elapsed:x.elapsed||0,percent:x.percent||0};}
  });
 }else if(s.running&&s.current_job_id){
  let cls=s.step==='error'?'is-error':(s.step==='complete'?'is-done':'is-running');
  if(cls==='is-running')runningInfo[s.current_job_id]={cls:'is-running',state:s.step_label||'',detail:[s.activity_detail,s.activity_value].filter(Boolean).join(' / '),elapsed:s.elapsed_seconds||0,percent:s.step_percent||0};
 }
 // バックエンドが確定した完了/失敗の対象を取り込む（累積・不可逆）。
 if(s.running){
  (s.queue_completed_ids||[]).forEach(id=>{runCompletedIds.add(id);if(!runDoneMeta[id])runDoneMeta[id]={cls:'is-done',state:'完了',detail:'このバッチで完了しました',elapsed:0,percent:100}});
  (s.queue_failed_ids||[]).forEach(id=>{runFailedIds.add(id);if(!runDoneMeta[id])runDoneMeta[id]={cls:'is-error',state:'失敗',detail:'',elapsed:0,percent:100}});
 }
 rowLive={};
 if(s.running){
  lastRunActive=true;runFinishedAt=0;
  // 順番待ち: このバッチの対象のうち、処理中でも完了でも失敗でもないもの。
  (s.batch_job_ids||[]).forEach(id=>{
   if(runningInfo[id]||runCompletedIds.has(id)||runFailedIds.has(id))return;
   rowLive[id]={cls:'is-wait',state:'このバッチ内で順番待ち',detail:'開始を待っています',elapsed:0,percent:0};
  });
  Object.entries(runningInfo).forEach(([id,v])=>rowLive[id]=v);
  runCompletedIds.forEach(id=>{if(!runningInfo[id])rowLive[id]=runDoneMeta[id]||{cls:'is-done',state:'完了',detail:'',elapsed:0,percent:100}});
  runFailedIds.forEach(id=>{if(!runningInfo[id])rowLive[id]=runDoneMeta[id]||{cls:'is-error',state:'失敗',detail:'',elapsed:0,percent:100}});
 }else if(lastRunActive){
  // 実行終了直後は完了/失敗の結果を少しの間だけ残し、その後スケジュール表示へ戻す。
  if(!runFinishedAt)runFinishedAt=now;
  if(now-runFinishedAt<=ROW_DONE_HOLD_MS){
   runCompletedIds.forEach(id=>rowLive[id]=runDoneMeta[id]||{cls:'is-done',state:'完了',detail:'処理が完了しました',elapsed:0,percent:100});
   runFailedIds.forEach(id=>rowLive[id]=runDoneMeta[id]||{cls:'is-error',state:'失敗',detail:'',elapsed:0,percent:100});
  }else{
   lastRunActive=false;runCompletedIds.clear();runFailedIds.clear();runDoneMeta={};
  }
 }
 paintRowProgress();
}
function applyRowQueueProgress(d){
 rowQueue={};
 (d.items||[]).forEach(item=>{if(item.state!=='waiting')return;(item.job_ids||[]).forEach(id=>{if(!(id in rowQueue)||item.position<rowQueue[id])rowQueue[id]=item.position})});
 paintRowProgress();
}
function paintRowProgress(){
 $$('.rowprogress').forEach(el=>{
  let id=el.dataset.jobid,live=rowLive[id];
  el.classList.remove('is-running','is-wait','is-done','is-error');
  if(live){
   el.classList.add(live.cls);
   el.querySelector('.rp-state').textContent=live.state;
   el.querySelector('.rp-elapsed').textContent=live.elapsed?hhmmss(live.elapsed):'';
   el.querySelector('.rp-bar').style.width=Math.max(0,Math.min(100,Number(live.percent)||0))+'%';
   el.querySelector('.rp-detail').textContent=live.detail;
   el.title='クリックで進捗を表示';
  }else if(rowQueue[id]){
   el.classList.add('is-wait');
   el.querySelector('.rp-state').textContent='実行キュー待ち';
   el.querySelector('.rp-elapsed').textContent='';
   el.querySelector('.rp-bar').style.width='0%';
   el.querySelector('.rp-detail').textContent=`${rowQueue[id]}番目に実行予定`;
   el.title='クリックで進捗を表示';
  }else{
   el.title='';
  }
 })
}
document.addEventListener('click',e=>{let el=e.target.closest('.rowprogress');if(!el)return;if(el.classList.contains('is-running')||el.classList.contains('is-wait')||el.classList.contains('is-done')||el.classList.contains('is-error'))openProgressModal()});
setInterval(loadSchedulePreview,60000);loadSchedulePreview();

/* 0.9.0&0.12.0 (旧V33/V36): browser heartbeat — lets the backend detect an ABANDONED (closed) tab and self-terminate, while NOT mistaking a merely
   inactive/background tab for a closed one. Background tabs throttle setInterval (often to ~1/min), so a main-thread timer alone
   caused false "browser closed" detections. We now: (1) drive the heartbeat from a Web Worker whose timer resists background
   throttling, with a main-thread fallback; (2) send an immediate heartbeat whenever the tab becomes visible again; and
   (3) send an explicit close beacon on real close so genuine closes are detected fast without killing on tab-switch/reload. */
function sendHeartbeat(){fetch('/api/heartbeat',{method:'POST',keepalive:true}).catch(()=>{})}
function startHeartbeat(){
 sendHeartbeat();
 let worker=null;
 try{
  const code="let t=null;onmessage=e=>{if(e.data==='start'){clearInterval(t);t=setInterval(()=>postMessage('tick'),10000);}else if(e.data==='stop'){clearInterval(t);t=null}};";
  worker=new Worker(URL.createObjectURL(new Blob([code],{type:'application/javascript'})));
  worker.onmessage=()=>sendHeartbeat();
  worker.postMessage('start');
 }catch(e){worker=null}
 // 保険: Workerが使えない環境でも、抑制されにくいよう短めの間隔で送る。バックエンド側のしきい値(200秒)が誤検知を防ぐ。
 setInterval(sendHeartbeat,10000);
 // タブが再びアクティブになった瞬間に即送信して、抑制中に開いた無音時間をすぐ埋める。
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')sendHeartbeat()});
 window.addEventListener('focus',sendHeartbeat);
 window.addEventListener('pageshow',sendHeartbeat);
}
startHeartbeat();
// タブ×・ウィンドウ×・遷移など「実際に閉じる」ときだけ明示通知。タブ切替(非アクティブ)ではpagehideは発火しないため誤検知しない。
// リロードでもpagehideは発火するが、再読込後のハートビートがバックエンドの明示クローズ判定を猶予内に解除するため終了しない。
function notifyBrowserClosing(){try{navigator.sendBeacon('/api/browser-closing')}catch(e){}}
window.addEventListener('pagehide',notifyBrowserClosing);

/* V34: keep the browser and the running state in sync — warn before closing during a run, and surface it clearly if the server itself disappears */
window.addEventListener('beforeunload',e=>{if(lastRunning){e.preventDefault();e.returnValue=''}});
function showServerLost(){if(serverLostShown)return;serverLostShown=true;let d=$('#server-lost-overlay');if(d&&!d.open)d.showModal()}
function hideServerLost(){if(!serverLostShown)return;serverLostShown=false;let d=$('#server-lost-overlay');if(d&&d.open)d.close()}
if($('#server-lost-reload'))$('#server-lost-reload').onclick=()=>location.reload();

/* v1.2.0: カレンダービュー — 予定(自動実行)と実施履歴を月カレンダーへ色分け表示し、日単位で確認・編集導線を提供する */
let calYM=null,calView='both',calData=null,calJobFilter='all',calBound=false;
function openCalendar(){
 if(!calYM){let n=new Date();calYM={y:n.getFullYear(),m:n.getMonth()+1}}
 if(!calBound){
  calBound=true;
  if($('#cal-prev'))$('#cal-prev').onclick=()=>{calYM.m--;if(calYM.m<1){calYM.m=12;calYM.y--}loadCalendar()};
  if($('#cal-next'))$('#cal-next').onclick=()=>{calYM.m++;if(calYM.m>12){calYM.m=1;calYM.y++}loadCalendar()};
  if($('#cal-today'))$('#cal-today').onclick=()=>{let n=new Date();calYM={y:n.getFullYear(),m:n.getMonth()+1};loadCalendar()};
  $$('#calendar .cal-viewbtn').forEach(b=>b.onclick=()=>{calView=b.dataset.view;$$('#calendar .cal-viewbtn').forEach(x=>x.classList.toggle('on',x===b));renderCalendar()});
  if($('#cal-job-filter'))$('#cal-job-filter').onchange=e=>{calJobFilter=e.target.value;renderCalendar()};
  if($('#cal-day-close'))$('#cal-day-close').onclick=()=>$('#cal-day-dialog').close();
 }
 if($('#cal-job-filter')&&cfg?.jobs){let cur=calJobFilter;$('#cal-job-filter').innerHTML='<option value="all">対象: すべて</option>'+cfg.jobs.map(j=>`<option value="${j.id}">${E(j.name)}</option>`).join('');$('#cal-job-filter').value=cfg.jobs.some(j=>j.id===cur)?cur:'all';calJobFilter=$('#cal-job-filter').value}
 loadCalendar();
}
async function loadCalendar(){
 try{let d=await fetch(`/api/calendar?year=${calYM.y}&month=${calYM.m}`,{cache:'no-store'}).then(r=>r.json());calData=d;renderCalendar()}
 catch{if($('#cal-grid'))$('#cal-grid').innerHTML='<div class="empty">カレンダー情報を取得できませんでした。</div>'}
}
function calStatusClass(s){return s==='ok'?'ok':s==='failed'?'ng':'warn'}
function renderCalendar(){
 if(!calData)return;let {y,m}=calYM;
 if($('#cal-title'))$('#cal-title').textContent=`${y}年 ${m}月`;
 let filt=x=>calJobFilter==='all'||x.job_id===calJobFilter;
 let sched=(calData.scheduled||[]).filter(filt),exec=(calData.executed||[]).filter(filt),intervals=(calData.interval||[]);
 let intFilt=intervals.map(d=>({date:d.date,items:(d.items||[]).filter(it=>calJobFilter==='all'||it.job_id===calJobFilter)})).filter(d=>d.items.length);
 if($('#cal-summary')){let okN=exec.filter(x=>x.status==='ok').length,ngN=exec.filter(x=>x.status==='failed').length;$('#cal-summary').innerHTML=`この月: 予定 <b>${sched.length}</b>件 / 定期(間隔) <b>${intFilt.length?'あり':'なし'}</b> / 実績 完了 <b>${okN}</b>・失敗 <b>${ngN}</b>`}
 let byS={},byE={},byI={};
 sched.forEach(x=>{(byS[x.date]=byS[x.date]||[]).push(x)});
 exec.forEach(x=>{(byE[x.date]=byE[x.date]||[]).push(x)});
 intFilt.forEach(d=>{byI[d.date]=d.items});
 let start=new Date(y,m-1,1).getDay(),days=new Date(y,m,0).getDate(),today=calData.today;
 let cells='';
 for(let i=0;i<start;i++)cells+='<div class="cal-cell cal-empty"></div>';
 for(let dn=1;dn<=days;dn++){
  let iso=`${y}-${String(m).padStart(2,'0')}-${String(dn).padStart(2,'0')}`,dow=new Date(y,m-1,dn).getDay(),ev='';
  if(calView!=='executed'){
   (byS[iso]||[]).slice(0,4).forEach(x=>{ev+=`<button type="button" class="cal-ev ev-sched" data-jobid="${x.job_id}" title="${E(x.job_name)} ${x.time}（${E(x.rule_name)}）">${x.time} ${E(x.job_name)}</button>`});
   if(byI[iso])ev+=`<span class="cal-ev ev-interval" title="一定間隔の定期実行">定期 ${byI[iso].length}件</span>`;
   let ms=(byS[iso]||[]).length-4;if(ms>0)ev+=`<span class="cal-more">予定＋${ms}件</span>`;
  }
  if(calView!=='scheduled'){
   (byE[iso]||[]).slice(0,3).forEach(x=>{ev+=`<span class="cal-ev ev-exec ${calStatusClass(x.status)}" title="${E(x.job_name)} ${x.time} ${x.status}">${x.time} ${E(x.job_name)}</span>`});
   let me=(byE[iso]||[]).length-3;if(me>0)ev+=`<span class="cal-more">実績＋${me}件</span>`;
  }
  let cls=['cal-cell'];if(iso===today)cls.push('cal-today');if(dow===0)cls.push('sun');if(dow===6)cls.push('sat');
  cells+=`<div class="${cls.join(' ')}" data-iso="${iso}"><div class="cal-date"><span>${dn}</span></div><div class="cal-events">${ev}</div></div>`;
 }
 $('#cal-grid').innerHTML=cells;
 $$('#cal-grid .cal-cell[data-iso]').forEach(c=>c.onclick=e=>{if(e.target.closest('.cal-ev.ev-sched'))return;openCalDay(c.dataset.iso)});
 $$('#cal-grid .cal-ev.ev-sched').forEach(b=>b.onclick=e=>{e.stopPropagation();let j=cfg?.jobs?.find(x=>x.id===b.dataset.jobid);if(j){openEditor(j);setEditorTab('schedule')}});
}
function openCalDay(iso){
 if(!calData)return;
 let filt=x=>calJobFilter==='all'||x.job_id===calJobFilter;
 let sched=(calData.scheduled||[]).filter(x=>x.date===iso&&filt(x)),exec=(calData.executed||[]).filter(x=>x.date===iso&&filt(x)),ints=(calData.interval||[]).filter(d=>d.date===iso).flatMap(d=>d.items||[]).filter(it=>calJobFilter==='all'||it.job_id===calJobFilter);
 $('#cal-day-title').textContent=iso.replace(/-/g,'/');
 let html=`<div class="calday-sec"><h3>予定 (${sched.length+ints.length})</h3>`;
 if(sched.length||ints.length){
  html+='<div class="calday-list">';
  sched.sort((a,b)=>a.time.localeCompare(b.time)).forEach(x=>{html+=`<div class="calday-item sched"><span class="ci-time">${x.time}</span><div class="ci-main"><b>${E(x.job_name)}</b><small>${E(x.rule_name||'')} / ${typeName(x.rule_type)}</small></div><button class="secondary ci-edit" data-jobid="${x.job_id}">編集</button><button class="ci-run" data-jobid="${x.job_id}">今すぐ</button></div>`});
  ints.forEach(x=>{html+=`<div class="calday-item interval"><span class="ci-time">定期</span><div class="ci-main"><b>${E(x.job_name)}</b><small>${E(x.rule_name||'')} / ${x.minutes}分ごと（約${x.count}回/日）</small></div><button class="secondary ci-edit" data-jobid="${x.job_id}">編集</button></div>`});
  html+='</div>';
 }else html+='<p class="calday-empty">この日の予定はありません。</p>';
 html+=`</div><div class="calday-sec"><div class="calday-sechead"><h3>実績 (${exec.length})</h3>${exec.length?`<button type="button" class="secondary danger-lite ci-clear-day" data-date="${iso}">この日の実績を全削除</button>`:''}</div>`;
 if(exec.length){
  html+='<div class="calday-list">';
  exec.sort((a,b)=>a.time.localeCompare(b.time)).forEach(x=>{let st=x.status==='ok'?'完了':x.status==='failed'?'失敗':x.status==='cancelled'?'中断':x.status;html+=`<div class="calday-item exec ${calStatusClass(x.status)}"><span class="ci-time">${x.time}</span><div class="ci-main"><b>${E(x.job_name)}</b><small>${st} / ${x.trigger==='schedule'?'定期':'即実行'}${x.rows!=null?` / ${x.rows}行×${x.cols}列`:''}</small></div>${x.id!=null?`<button class="secondary danger-lite ci-del" data-id="${x.id}" title="この実施記録を削除します">削除</button>`:''}</div>`});
  html+='</div>';
 }else html+='<p class="calday-empty">この日の実績はありません。</p>';
 html+='</div>';
 $('#cal-day-body').innerHTML=html;
 if($('#cal-quick-job')&&cfg?.jobs)$('#cal-quick-job').innerHTML=cfg.jobs.map(j=>`<option value="${j.id}">${E(j.name)}</option>`).join('');
 if($('#cal-quick-add'))$('#cal-quick-add').dataset.date=iso;
 $$('#cal-day-body .ci-edit').forEach(b=>b.onclick=()=>{let j=cfg?.jobs?.find(x=>x.id===b.dataset.jobid);if(j){$('#cal-day-dialog').close();openEditor(j);setEditorTab('schedule')}});
 $$('#cal-day-body .ci-run').forEach(b=>b.onclick=()=>{runJobs([b.dataset.jobid]);$('#cal-day-dialog').close()});
 $$('#cal-day-body .ci-del').forEach(b=>b.onclick=async()=>{if(!confirm('この実施記録を削除しますか？（この操作は元に戻せません）'))return;let r=await fetch('/api/run-history/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[Number(b.dataset.id)]})}),d=await r.json().catch(()=>({}));if(r.ok){toast('実施記録を削除しました');await loadCalendar();await loadSchedulePreview();openCalDay(iso)}else toast(d.error||'削除できませんでした')});
 let clr=$('#cal-day-body .ci-clear-day');if(clr)clr.onclick=async()=>{let cnt=exec.length;if(!confirm(`${iso.replace(/-/g,'/')} の実績 ${cnt}件を削除しますか？（この操作は元に戻せません）`))return;let r=await fetch('/api/run-history/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:iso,job_id:calJobFilter})}),d=await r.json().catch(()=>({}));if(r.ok){toast(`${d.removed}件の実績を削除しました`);await loadCalendar();await loadSchedulePreview();openCalDay(iso)}else toast(d.error||'削除できませんでした')};
 if(!$('#cal-day-dialog').open)$('#cal-day-dialog').showModal();
}
if($('#cal-quick-add'))$('#cal-quick-add').onclick=async()=>{let date=$('#cal-quick-add').dataset.date,job=$('#cal-quick-job')?.value,tm=$('#cal-quick-time')?.value||'06:00';if(!job||!date)return toast('対象と日付を確認してください');let r=await fetch('/api/schedule/quick-add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job,date,time:tm})}),d=await r.json();if(r.ok){toast(`${date} の単発実行を追加しました`);$('#cal-day-dialog').close();await init();await loadCalendar()}else toast(d.error||'追加できませんでした')};
if($('#cal-day-dialog'))$('#cal-day-dialog').addEventListener('close',()=>{if($('#cal-day-body'))$('#cal-day-body').innerHTML=''});

/* ============================================================
   v1.7.0: 抽出期間（動的日付）。RNEに定義済みの時間型管理ポイントへ、
   処理日時を基準にした相対期間を実行直前に適用する。RNE/カラムは変更しない。
   認知心理学(近接・即時フィードバック) / 情報アーキテクチャ(単位→開始→終了の順序) / 色彩調和(入力系の系統色)。
   ============================================================ */
let periodPreviewTimer=null;
function currentPeriodUnit(){return document.querySelector('#period-unit-seg .period-unitbtn.on')?.dataset.unit||'month'}
function periodDir(id){return Number(document.querySelector('#'+id+' .po-dirbtn.on')?.dataset.dir||-1)}
function setPeriodDir(id,dir){$$('#'+id+' .po-dirbtn').forEach(b=>b.classList.toggle('on',Number(b.dataset.dir)===Number(dir)))}
function currentPeriod(){
 let enabled=$('#m-period-enabled')?.checked||false;
 let unit=currentPeriodUnit();
 let fromMag=Math.abs(Math.trunc(Number($('#m-period-from')?.value)||0));
 let toMag=Math.abs(Math.trunc(Number($('#m-period-to')?.value)||0));
 return {enabled,unit,control_point:($('#m-period-cp')?.value||'').trim(),from_offset:fromMag*periodDir('period-from-dir'),to_offset:toMag*periodDir('period-to-dir')};
}
function setPeriodUnit(unit){
 unit=(unit==='day')?'day':'month';
 $$('#period-unit-seg .period-unitbtn').forEach(b=>b.classList.toggle('on',b.dataset.unit===unit));
 let baseText=unit==='month'?'当月':'当日',unitText=unit==='month'?'ヶ月':'日';
 $$('#period-body .po-base').forEach(el=>el.textContent=baseText);
 $$('#period-body .po-unit').forEach(el=>el.textContent=unitText);
}
function togglePeriodBody(){let on=$('#m-period-enabled')?.checked;let b=$('#period-body');if(b)b.hidden=!on}
function setPeriodUI(p){
 p=p||{};
 if($('#m-period-enabled'))$('#m-period-enabled').checked=!!p.enabled;
 setPeriodUnit(p.unit==='day'?'day':'month');
 let fo=Math.trunc(Number(p.from_offset)||0),to=Math.trunc(Number(p.to_offset)||0);
 if($('#m-period-from'))$('#m-period-from').value=Math.abs(fo);
 if($('#m-period-to'))$('#m-period-to').value=Math.abs(to);
 setPeriodDir('period-from-dir',fo>0?1:-1);
 setPeriodDir('period-to-dir',to>0?1:-1);
 if($('#m-period-cp'))$('#m-period-cp').value=p.control_point||'';
 let rb=$('#m-period-cp-result');if(rb){rb.hidden=true;rb.innerHTML=''}
 togglePeriodBody();
 refreshPeriodPreview();
}
function refreshPeriodPreview(){
 let el=$('#m-period-preview'),meta=$('#m-period-preview-meta');if(!el)return;
 if(!$('#m-period-enabled')?.checked){el.textContent='—';if(meta)meta.textContent='抽出期間の自動指定は無効です（RNEの設定のまま実行します）';return}
 let body=currentPeriod();
 clearTimeout(periodPreviewTimer);
 periodPreviewTimer=setTimeout(async()=>{
  try{
   let r=await fetch('/api/period-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json();
   if(!d.ok){el.textContent='(期間エラー)';if(meta)meta.textContent=d.error||'';return}
   el.textContent=d.summary;
   let cp=body.control_point?`対象: ${body.control_point}`:'対象: 時間フィールドの時間型を自動選択';
   if(meta)meta.textContent=`${cp} / 内部指定 ${d.from_time}〜${d.to_time} / 処理日時 ${d.now} 基準`;
  }catch{el.textContent='(プレビュー取得失敗)';if(meta)meta.textContent=''}
 },200);
}
function onPeriodChange(){togglePeriodBody();refreshPeriodPreview();dirty()}
if($('#m-period-enabled'))$('#m-period-enabled').addEventListener('change',onPeriodChange);
$$('#period-unit-seg .period-unitbtn').forEach(b=>b.onclick=()=>{setPeriodUnit(b.dataset.unit);refreshPeriodPreview();dirty()});
$$('#period-from-dir .po-dirbtn').forEach(b=>b.onclick=()=>{setPeriodDir('period-from-dir',b.dataset.dir);refreshPeriodPreview();dirty()});
$$('#period-to-dir .po-dirbtn').forEach(b=>b.onclick=()=>{setPeriodDir('period-to-dir',b.dataset.dir);refreshPeriodPreview();dirty()});
['m-period-from','m-period-to','m-period-cp'].forEach(id=>{let e=$('#'+id);if(e)e.addEventListener('input',()=>{refreshPeriodPreview();dirty()})});
$$('#period-body .period-preset').forEach(b=>b.onclick=()=>{
 setPeriodUnit(b.dataset.unit);
 let fo=Number(b.dataset.from||0),to=Number(b.dataset.to||0);
 if($('#m-period-from'))$('#m-period-from').value=Math.abs(fo);
 if($('#m-period-to'))$('#m-period-to').value=Math.abs(to);
 setPeriodDir('period-from-dir',fo>0?1:-1);
 setPeriodDir('period-to-dir',to>0?1:-1);
 refreshPeriodPreview();dirty();
});
if($('#m-period-detect'))$('#m-period-detect').onclick=async()=>{
 let rb=$('#m-period-cp-result');
 showWaiting('管理ポイントを検出中','RNEを開いて時間型管理ポイントを取得しています...','api');
 try{
  let r=await fetch('/api/period-control-points',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:editing?.id,rne_path:$('#m-rne-path')?.value||''})}),d=await r.json();
  if(rb){rb.hidden=false;}
  if(!d.ok){if(rb)rb.innerHTML=`<p class="period-cp-ng">自動検出できませんでした。管理ポイント名を手入力するか、空欄（自動）でお試しください。</p><p class="period-cp-note">${E(d.error||'')}</p>`;return}
  let tps=d.time_points||[];
  let dl=$('#suggest-period-cp');if(dl&&tps.length)dl.innerHTML=tps.map(p=>`<option value="${E(p.name)}">`).join('');
  if(!tps.length){if(rb)rb.innerHTML=`<p class="period-cp-ng">時間型管理ポイントが見つかりませんでした（全${d.count||0}件中0件）。空欄（自動）でお試しください。</p>`;return}
  if(rb)rb.innerHTML=`<p class="period-cp-ok">時間型管理ポイントを ${tps.length} 件検出しました。クリックで設定します。</p><div class="period-cp-list">${tps.map(p=>`<button type="button" class="chip period-cp-pick" data-name="${E(p.name)}">${E(p.name)}<em>${E(p.location)}・${E(p.type_name)}</em></button>`).join('')}</div>`;
  rb.querySelectorAll('.period-cp-pick').forEach(x=>x.onclick=()=>{if($('#m-period-cp'))$('#m-period-cp').value=x.dataset.name;refreshPeriodPreview();dirty();toast(`対象を「${x.dataset.name}」に設定しました`)});
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="period-cp-ng">検出処理でエラーが発生しました。</p>`}}
 finally{hideWaiting()}
};
