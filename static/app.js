const UI_BUILD='1.62.0-alerts';
let cfg,editing=null,editingRule=null,sortDir=1,scheduleInfo={},rowLive={},rowQueue={},statusFailCount=0,serverLostShown=false;const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)],E=s=>String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));const uid=()=>crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random();function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';setTimeout(()=>$('#toast').style.display='none',2500)}/* 設定は変えた瞬間に保存する。保存ボタンの押し忘れで、画面に見えている設定と
   実際に使われる設定が食い違うことがあったため、押す操作そのものを無くした。 */
let saveTimer=null,saveSeq=0,saveRetry=0;
function saveState(text,kind){let e=$('#dirty');if(e){e.textContent=text;e.className='autosave-state '+(kind||'')}}
function collectSettings(){if(!cfg||!cfg.settings)return;let s=cfg.settings,v=id=>$(id);
 if(v('#extract-engine'))s.extract_engine=v('#extract-engine').value;
 if(v('#dde'))s.dde_timeout_seconds=Math.max(1,Number(v('#dde').value)||1);
 if(v('#wait'))s.output_wait_seconds=Math.max(0,Number(v('#wait').value)||0);
 if(v('#gens'))s.backup_generations=Math.max(1,Math.min(9999,Number(v('#gens').value)||3));
 if(v('#backup-enabled'))s.backup_enabled=v('#backup-enabled').checked;
 if(v('#backup-mode'))s.backup_mode=v('#backup-mode').value||'generations';
 if(v('#backup-retention-days'))s.backup_retention_days=Math.max(1,Math.min(3650,Number(v('#backup-retention-days').value)||30));
 if(v('#schedule-catchup'))s.schedule_catchup_minutes=Math.max(0,Math.min(720,Number(v('#schedule-catchup').value)||0));
 if(v('#worker-stagger'))s.api_worker_stagger_ms=Math.max(0,Math.min(5000,Number(v('#worker-stagger').value)||0));
 if(v('#api-lines'))s.api_parallel_lines=Math.max(1,Math.min(24,Number(v('#api-lines').value)||6));
 if(v('#zero'))s.reject_zero_rows=v('#zero').checked;
 if(v('#retry-enabled'))s.retry_enabled=v('#retry-enabled').checked;
 if(v('#retry-delay'))s.retry_delay_minutes=Math.max(1,Math.min(180,Number(v('#retry-delay').value)||5));
 if(v('#retry-max'))s.retry_max=Math.max(0,Math.min(5,Number(v('#retry-max').value)||0));
 if(v('#hide-profile'))s.symnavi_hide_profile=v('#hide-profile').value;
 if(v('#hide-interval'))s.symnavi_hide_interval_seconds=Math.max(1,Number(v('#hide-interval').value)||2);
 if(v('#hide-action-duration'))s.symnavi_hide_action_duration_seconds=Math.max(.2,Number(v('#hide-action-duration').value)||.5);
 s.backup_generation_limit_enabled=s.backup_mode!=='days';s.stability_profile='balanced_api_parallel'}
function settingsPayload(){collectSettings();let payload=structuredClone(cfg||{});delete payload.credential_status;return payload}
function scheduleSave(delay=450){clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveSettingsNow(),delay)}
function saveFailed(why){if(saveRetry<3){saveRetry++;saveState(`保存できません（${why}）／${saveRetry}回目の再試行をします`,'is-ng');scheduleSave(3000)}else saveState(`保存できません（${why}）／画面を再読込してやり直してください`,'is-ng');return false}
async function saveSettingsNow(){clearTimeout(saveTimer);saveTimer=null;if(!cfg)return false;let payload=settingsPayload(),seq=++saveSeq;saveState('保存しています','is-saving');try{let r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(seq!==saveSeq)return true;if(!r.ok){let d=await r.json().catch(()=>({}));return saveFailed(d.error||('HTTP '+r.status))}saveRetry=0;saveState('自動保存しました '+new Date().toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit',second:'2-digit'}),'is-ok');return true}catch(e){if(seq!==saveSeq)return true;return saveFailed('サーバーへ届きませんでした')}}
/* 対象の編集画面は下書き（editing）を触っているので、閉じるまで保存しない。 */
function dirty(){if($('#editor')?.open||$('#rule-editor')?.open)return;saveRetry=0;saveState('変更を保存しています','is-saving');scheduleSave()}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'&&saveTimer)saveSettingsNow()});
window.addEventListener('beforeunload',()=>{if(!saveTimer||!cfg)return;clearTimeout(saveTimer);saveTimer=null;try{fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(settingsPayload()),keepalive:true})}catch{}});$$('nav button').forEach(b=>b.onclick=()=>{$$('nav button,section').forEach(x=>x.classList.remove('on'));b.classList.add('on');$('#'+b.dataset.p).classList.add('on');if(b.dataset.p==='logs')loadLog();if(b.dataset.p==='calendar')openCalendar();if(b.dataset.p==='viewer')loadViewerJobs()});
const paths={navigator_api_dll:['Navigator API DLL','file',[['DLLファイル','*.dll'],['すべて','*.*']]],symnavi_exe:['SymNavi.exe','file',[['実行ファイル','*.exe'],['すべて','*.*']]],symnavim_conf:['symnavim.conf','file',[['CONFファイル','*.conf'],['すべて','*.*']]],symnavim_def:['symnavim.def','file',[['DEFファイル','*.def'],['すべて','*.*']]],accdb_template:['ACCDB空テンプレート','file',[['Access Database','*.accdb'],['すべて','*.*']]],rne_folder:['RNE基本フォルダー','folder'],default_output_folder:['既定の出力先','folder'],backup_folder:['バックアップ先','folder']};
let waitingTimer=null,waitingStarted=0;function currentEngine(){return $('#extract-engine')?.value||cfg?.settings?.extract_engine||'api'}function waitingEngineLabel(context='common'){if(context==='api'||(context==='engine'&&currentEngine()==='api'))return 'NAVIGATOR API';if(context==='dde'||(context==='engine'&&currentEngine()==='dde'))return 'DDE COMPATIBILITY';return 'COMMON OPERATION'}function showWaiting(title='確認中',detail='処理を続行しています...',context='common'){let d=$('#waiting-dialog');$('#waiting-engine').textContent=waitingEngineLabel(context);$('#waiting-title').textContent=title;$('#waiting-detail').textContent=detail;waitingStarted=Date.now();clearInterval(waitingTimer);let tick=()=>{let sec=Math.floor((Date.now()-waitingStarted)/1000);$('#waiting-elapsed').textContent=`経過 ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`};tick();waitingTimer=setInterval(tick,1000);if(!d.open)d.showModal()}function updateWaiting(title,detail,context){if(title)$('#waiting-title').textContent=title;if(detail)$('#waiting-detail').textContent=detail;if(context)$('#waiting-engine').textContent=waitingEngineLabel(context)}function hideWaiting(){clearInterval(waitingTimer);waitingTimer=null;let d=$('#waiting-dialog');if(d?.open)d.close()}async function convertPath(input,mode){showWaiting('パス変換中',mode==='relative'?'アプリフォルダー基準へ変換しています...':'実際の絶対パスを解決しています...');try{let r=await fetch('/api/path-convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:input.value,mode})}),d=await r.json();if(!r.ok)return toast(d.error);input.value=d.value;updatePathBadge(input);dirty()}finally{hideWaiting()}}function updatePathBadge(input){let badge=input.closest('label')?.querySelector('.path-badge');if(!badge)return;let relative=input.value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(input.value);badge.textContent=relative?'相対パス / 基準: アプリフォルダー':'絶対パス';badge.className='path-badge '+(relative?'path-kind-relative':'path-kind-absolute')}function isRelativePath(value){return !!value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(value)}function enhancePathInput(input,kind='folder'){if(!input||input.dataset.pathEnhanced)return;input.dataset.pathEnhanced='1';let tools=document.createElement('div');tools.className='path-tools compact-path-tools';tools.innerHTML='<button type="button" class="pathmode path-toggle" title="絶対パスと相対パスを切り替えます"></button><small class="path-badge"></small>';input.closest('label')?.appendChild(tools);let toggle=tools.querySelector('.path-toggle');function refresh(){let relative=isRelativePath(input.value);toggle.textContent=relative?'相対 → 絶対':'絶対 → 相対';toggle.dataset.mode=relative?'absolute':'relative';updatePathBadge(input)}toggle.onclick=async()=>{await convertPath(input,toggle.dataset.mode);refresh()};input.addEventListener('input',refresh);input._refreshPathControl=refresh;refresh()}async function browse(kind,initial,types){showWaiting('参照画面を準備中','設定中のパスを解決して、その場所から開きます...');try{let url=kind==='folder'?'/api/pick-folder':'/api/pick-file',r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initial,types})}),d=await r.json();if(!r.ok)toast(d.error);return d.path||''}finally{hideWaiting()}}
async function checkConfiguredPath(item,jobId){showWaiting('ファイル存在確認中','設定場所と周辺フォルダーを検索しています...');try{let r=await fetch('/api/path-check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item,job_id:jobId})}),d=await r.json();if(!r.ok)return toast(d.error);showPathResult(d)}finally{hideWaiting()}}function showPathResult(d){let box=$('#suggest-content');if(d.ok){box.innerHTML=`<p class="path-ok">存在を確認しました。</p><code>${E(d.resolved)}</code>`}else if(d.candidates?.length){box.innerHTML=`<p class="path-ng">設定先には存在しません。</p><p>設定値: <code>${E(d.configured)}</code></p><p>実在する修正候補:</p><div class="candidate-list">${d.candidates.map(x=>`<div class="candidate"><code>${E(x)}</code><button class="apply-suggestion" data-path="${E(x)}">このパスへ修正</button></div>`).join('')}</div>`;box.querySelectorAll('.apply-suggestion').forEach(b=>b.onclick=async()=>{let r=await fetch('/api/apply-path-suggestion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item:d.item,job_id:d.job_id,candidate:b.dataset.path})}),x=await r.json();if(r.ok){$('#path-suggestion').close();toast('設定を修正しました');await init()}else toast(x.error)})}else{box.innerHTML=`<p class="path-ng">ファイルが見つかりません。</p><p>確認先: <code>${E(d.resolved)}</code></p><p class="reselect">上2階層・下1階層の検索範囲にも候補がありません。参照ボタンから再指定してください。</p>`}if(!$('#path-suggestion').open)$('#path-suggestion').showModal()}

function expectedExt(f){return {sqlite3:'.sqlite3',txt:'.txt',csv:'.csv',xlsx:'.xlsx',accdb:'.accdb'}[normalizeFormat(f)]||'.sqlite3'}
function normalizeFormat(f){f=String(f||'').trim().toLowerCase();return ({sqlite:'sqlite3',db:'sqlite3',access:'accdb',excel:'xlsx',xls:'xlsx'}[f]||f||'sqlite3')}
function canonicalOutputFile(name,format){let ext=expectedExt(format),leaf=String(name||'output').trim(),dot=leaf.lastIndexOf('.');if(dot>0)leaf=leaf.slice(0,dot);leaf=leaf.replace(/(?:sqlite3|sqlite|accdb|xlsx|xls|csv|txt)$/i,'');return (leaf||'output')+ext}
function outputStem(name){let leaf=String(name||'').trim(),dot=leaf.lastIndexOf('.');if(dot>0)leaf=leaf.slice(0,dot);leaf=leaf.replace(/(?:sqlite3|sqlite|accdb|xlsx|xls|csv|txt)$/i,'');return leaf}
function updateFixedNameNote(){let f=normalizeFormat($('#m-format')?.value),ext=expectedExt(f),stem=(($('#m-output-file')?.value||'').trim()||'output');if($('#m-ext-suffix'))$('#m-ext-suffix').textContent=ext;if($('#m-format-note'))$('#m-format-note').textContent=`選択中: ${formatName(f)}（拡張子 ${ext}）／ 最終ファイル名 → ${outputStem(stem)||'output'}${ext}`}
function syncOutputExtension(){let f=normalizeFormat($('#m-format')?.value),i=$('#m-output-file');if($('#m-format'))$('#m-format').value=f;if(i)i.value=outputStem(i.value);updateFixedNameNote();renderAlsoFormats()}
/* ==== 同時に出す形式 ========================================================
   抽出（問い合わせと転送）は形式に関係なく共通で、そこから先の変換だけが違う。
   だから形式を足しても増えるのは変換と公開だけで、取り直しは起きない。
   選ぶ側にその関係が見えないと「もう1回走らせるのでは」と思えてしまうので、
   選んだ結果できるファイルを、その場に名前で並べる。 */
const ALL_FORMATS=['sqlite3','csv','txt','xlsx','accdb'];
const FORMAT_USE={sqlite3:'アプリ・BIから読む',csv:'そのまま配る・取り込む',txt:'タブ区切りで取り込む',
 xlsx:'Excelで開く',accdb:'Accessで使う'};
function alsoFormats(){
 let f=normalizeFormat($('#m-format')?.value);
 return (editing?.extra_formats||[]).map(normalizeFormat).filter((x,i,a)=>x!==f&&a.indexOf(x)===i);
}
function alsoToggle(f){
 let cur=alsoFormats(),i=cur.indexOf(f);
 if(i<0){if(cur.length>=4)return toast('同時に出せるのは、主の形式のほかに4つまでです');cur.push(f)}
 else cur.splice(i,1);
 editing.extra_formats=cur;renderAlsoFormats();dirty()
}
function alsoPlanNames(){
 let f=normalizeFormat($('#m-format')?.value),stem;
 if(currentNamingMode()==='template'){
  let p=$('#m-name-preview');stem=outputStem((p?.textContent||'').trim())
 }
 if(!stem)stem=outputStem($('#m-output-file')?.value||'')||'output';
 return [f].concat(alsoFormats()).map(x=>({format:x,file:stem+expectedExt(x)}));
}
function renderAlsoFormats(){
 let box=$('#m-also');if(!box)return;
 let f=normalizeFormat($('#m-format')?.value),on=alsoFormats();
 box.innerHTML=ALL_FORMATS.map(x=>x===f
  ?`<span class="af-chip is-primary" title="出力形式で選んでいる形式です">${E(formatName(x))}<i>主</i></span>`
  :`<button type="button" class="af-chip${on.includes(x)?' on':''}" data-f="${E(x)}" aria-pressed="${on.includes(x)}">`
   +`${E(formatName(x))}<i>${E(FORMAT_USE[x]||'')}</i></button>`).join('');
 box.querySelectorAll('.af-chip[data-f]').forEach(b=>b.onclick=()=>alsoToggle(b.dataset.f));
 let plan=$('#m-also-plan');if(!plan)return;
 let names=alsoPlanNames();
 plan.className='af-plan'+(on.length?' on':'');
 plan.innerHTML=on.length
  ?`<b>1回の実行でできるファイル（${names.length}件）</b><div class="af-files">`
    +names.map((x,i)=>`<span class="af-file${i?'':' is-primary'}"><i>${E(formatName(x.format))}</i><b>${E(x.file)}</b></span>`).join('')
    +`</div><small>抽出は1回のままです。増えるのは変換と公開だけなので、別々に実行するより速く済みます。`
    +(on.includes('accdb')?'ACCESSはテンプレートが要ります（設定 → 変換環境）。':'')+`</small>`
  :`<small>選ばなければ、これまでどおり ${E(formatName(f))} だけを出します。</small>`;
}
function formatName(f){return {sqlite3:'SQLite3',txt:'TXT',csv:'CSV',xlsx:'EXCEL',accdb:'ACCESS'}[f]||f}
function segmentHtml(segments){return (segments||[]).map(s=>s.var?`<span class="fname-var">${E(s.text)}</span>`:E(s.text)).join('')}
function outputFileCell(j){
 // 変数扱いはバックエンドが実トークンの有無で判定した output_is_variable のみ。単に変数欄へ入力しただけでは変数バッジを出さない。
 if(j.output_is_variable){
  let segs=j.output_file_segments||[];
  let body=segs.length?segmentHtml(segs):E(j.output_file_preview||'(実行時に決定)');
  return `<div class="primarytext" title="${E(j.output_pattern||'')}"><span class="name-var-badge">変数</span>${body}</div><div class="subtext" title="${E(j.output_pattern||'')}">${E(j.output_pattern||'')} / ${E(formatName(j.output_format))}${alsoBadge(j)}</div>`;
 }
 return `<div class="primarytext">${E(j.output_file)}</div><div class="subtext">${E(formatName(j.output_format))}${alsoBadge(j)} / ${E(j.type)}</div>`;
}
function alsoBadge(j){
 // 1回の実行で複数の形式が出る対象は、一覧の時点で分かるようにする。
 let x=(j.extra_formats||[]).map(normalizeFormat);
 if(!x.length)return '';
 return `<span class="also-badge" title="1回の抽出から同時に出します: ${E(x.map(formatName).join(' / '))}">＋${x.map(formatName).join('・')}</span>`;
}function scheduleSummary(r){if(r.type==='daily')return `毎日 ${r.time}`;if(r.type==='weekdays')return `${(r.weekdays||[]).map(x=>'月火水木金土日'[x]).join('・')} ${r.time}`;if(r.type==='monthly')return `毎月 ${(r.month_days||[]).join(',')}日 ${r.time}`;if(r.type==='interval')return `${r.interval_minutes||60}分間隔`;if(r.type==='specific_dates')return `${(r.dates||[]).length}日指定 ${r.time}`;return ''}function typeName(t){return {daily:'毎日',weekdays:'曜日指定',monthly:'月日指定',interval:'一定間隔',specific_dates:'特定日'}[t]||t}
function filtered(){let q=$('#search').value.trim().toLowerCase(),fe=$('#filter-enabled').value,fs=$('#filter-schedule').value,sort=$('#sort').value;let a=cfg.jobs.filter(j=>[j.name,j.rne,j.rne_path,j.output_file,j.output_folder,j.table,j.output_format,j.comment].join(' ').toLowerCase().includes(q)).filter(j=>fe==='all'||fe==='enabled'&&j.enabled||fe==='disabled'&&!j.enabled).filter(j=>fs==='all'||fs==='scheduled'&&(j.schedules||[]).some(r=>r.enabled)||fs==='manual'&&!(j.schedules||[]).some(r=>r.enabled));let key=j=>sort==='name'?j.name:sort==='rne'?j.rne:sort==='output'?(j.output_folder||''):sort==='schedule'?(j.schedules||[]).filter(r=>r.enabled).length:cfg.jobs.indexOf(j);a.sort((x,y)=>typeof key(x)==='number'?(key(x)-key(y))*sortDir:String(key(x)).localeCompare(String(key(y)),'ja')*sortDir);return a}
// 出力先リンク: 1回クリックでフォルダーを開き、2回で詳細（設定編集）を開く。
// ブラウザは1回目のclickを先に配ってからdblclickを出すので、待たずに開くと必ずフォルダーが先に出てしまう。
// そこで開く動作だけを DBLCLICK_WINDOW ぶん遅らせ、その間に2回目が来たら取り消して詳細へ回す。
// フォルダーを開くのはエクスプローラーの起動を伴うので、この程度の遅れは体感に出ない。
//
// 2回目の判定は dblclick イベントに頼らず、自前で間隔を測る。dblclick が出るかどうかは
// OS側のダブルクリック速度の設定しだいで、そこが遅い環境では2連打が「単発クリック2回」として
// 届き、フォルダーが開いてしまうため。自前で測れば、どの環境でも同じ間隔で判定できる。
const DBLCLICK_WINDOW=400;   // Windowsのダブルクリック既定は500ms。実際の操作はおおむね300ms以内。
function bindOutputLink(l,j){
 let timer=null,last=0;
 l.title=`${l.dataset.path||''}\nクリックで出力先を開く / ダブルクリックで詳細を開く`;
 l.onclick=e=>{
  e.preventDefault();e.stopPropagation();
  let now=Date.now();
  if(timer&&now-last<DBLCLICK_WINDOW){        // 2回目: フォルダーを開くのは取りやめて詳細へ
   clearTimeout(timer);timer=null;last=0;openEditor(j);return;
  }
  last=now;clearTimeout(timer);
  timer=setTimeout(()=>{timer=null;openOutputFolder(l.dataset.path)},DBLCLICK_WINDOW);
 };
 // dblclick も来るが、詳細は上のclickで開き終えている。ここでは取り消しだけして二重に開かない。
 l.ondblclick=e=>{e.preventDefault();e.stopPropagation();clearTimeout(timer);timer=null};
}
async function openOutputFolder(path){
 try{
  let r=await fetch('/api/open-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}),d=await r.json();
  if(r.ok&&d.ok)toast('出力先を開きました');else toast(d.error||'出力先を開けませんでした');
 }catch{toast('出力先を開けませんでした')}
}
// 「選択を実行」は、選んだ件数をボタン自身に出す。押してから「選択してください」と
// 叱るのではなく、押せるかどうかが押す前に分かるようにする。
function updateSelCount(){
 let n=$$('#jobs-body .rowcheck:checked').length,b=$('#run-selected'),c=$('#sel-count');
 if(c){c.textContent=n;c.hidden=!n}
 if(b){b.disabled=!n;b.title=n?`チェックした ${n}件 を実行します`:'実行したい対象にチェックを入れてください'}
}
function render(){let a=filtered(),body=$('#jobs-body');let canReorder=(!$('#search').value.trim()&&$('#filter-enabled').value==='all'&&$('#filter-schedule').value==='all');body.innerHTML=a.map(j=>`<tr data-id="${j.id}" draggable="${canReorder}" class="${canReorder?'reorderable':''}"><td class="c-check"><span class="drag-handle" title="${canReorder?'ドラッグで並べ替え（ドロップ後は登録順表示へ戻ります）':'並べ替えは検索・絞り込み解除時に有効です'}">⋮⋮</span><input class="rowcheck" type="checkbox"></td><td><span class="state ${j.enabled?'on':'off'}">${j.enabled?'有効':'無効'}</span></td><td><div class="primarytext" title="${E(j.name)}">${E(j.name)}</div><div class="subtext">${E(j.table)} / ${E(j.sheet)}</div>${j.comment?`<div class="job-comment" title="${E(j.comment)}"><i class="jc-ic">用途</i><span>${E(j.comment)}</span></div>`:''}</td><td><div class="primarytext" title="${E(j.rne_path||j.rne)}">${E(j.rne)}</div><div class="subtext pathtext">${E(j.rne_path||'')}</div></td><td>${outputFileCell(j)}</td><td><a class="output-link" href="#" data-path="${E(j.output_folder||cfg.default_output_folder)}" title="出力先を開く">${E(j.output_folder||cfg.default_output_folder)}</a></td><td class="c-progress">${rowProgressCell(j)}</td><td><div class="rowactions"><button class="run-one" title="実行">実行</button><button class="edit secondary" title="詳細">詳細</button><button class="copy secondary" title="複製">複製</button><button class="delete danger" title="削除">削除</button></div></td></tr>`).join('');paintRowProgress();applyScheduleCells();updateSelCount();$('#empty').hidden=a.length>0;$('#summary').textContent=`表示 ${a.length}件 / 登録 ${cfg.jobs.length}件 / 有効 ${cfg.jobs.filter(j=>j.enabled).length}件 / 自動実行ルール ${cfg.jobs.flatMap(j=>j.schedules||[]).filter(r=>r.enabled).length}件`;body.querySelectorAll('tr').forEach(tr=>{let j=cfg.jobs.find(x=>x.id===tr.dataset.id);tr.onclick=e=>{if(!e.target.closest('button,a,input')){tr.classList.toggle('selected');let cb=tr.querySelector('.rowcheck');if(cb)cb.checked=tr.classList.contains('selected');updateSelCount()}};tr.querySelector('.rowcheck').onchange=e=>{tr.classList.toggle('selected',e.target.checked);updateSelCount()};tr.ondblclick=e=>{if(!e.target.closest('button,input,select,a'))openEditor(j)};tr.querySelector('.edit').onclick=()=>openEditor(j);tr.querySelector('.run-one').onclick=()=>runJobs([j.id]);tr.querySelector('.copy').onclick=()=>{let n=structuredClone(j);n.id=uid();n.name+=' コピー';n.schedules=(n.schedules||[]).map(r=>({...r,id:uid(),enabled:false}));cfg.jobs.splice(cfg.jobs.indexOf(j)+1,0,n);render();dirty()};tr.querySelector('.delete').onclick=()=>deleteJob(j);let l=tr.querySelector('.output-link');if(l)bindOutputLink(l,j);bindRowDnD(tr);tr.oncontextmenu=e=>{if(e.target.closest("a.output-link"))return;e.preventDefault();showJobContextMenu(e,j,tr)}})}
/* v1.9.0: 一覧のドラッグ&ドロップ並べ替え（問い合わせ順に反映）と管理単位の削除 */
let dragSrcId=null,dragGhost=null,dragTargetId=null,dragAfter=false,dragImage=null;
function clearDragVisuals(){
 if(dragGhost){dragGhost.remove();dragGhost=null}
 if(dragImage){dragImage.remove();dragImage=null}
 $$('#jobs-body tr').forEach(x=>x.classList.remove('drop-before','drop-after','drag-near'));
}
function makeDragGhost(source){
 let ghost=document.createElement('tr');ghost.className='drop-ghost';ghost.setAttribute('aria-hidden','true');
 let name=source.querySelector('td:nth-child(3) .primarytext')?.textContent||'選択した対象';
 ghost.innerHTML=`<td colspan="8"><div class="drop-ghost-inner"><i></i><span><b>${E(name)}</b> をここへ移動</span></div></td>`;
 return ghost;
}
function makeDragImage(source,e){
 let img=source.cloneNode(true);img.className='row-drag-image';img.removeAttribute('draggable');
 img.style.width=source.getBoundingClientRect().width+'px';document.body.appendChild(img);
 try{e.dataTransfer.setDragImage(img,28,Math.min(22,img.offsetHeight/2))}catch{}
 return img;
}
function placeDragGhost(target,after){
 if(!dragGhost)dragGhost=makeDragGhost(document.querySelector(`#jobs-body tr[data-id="${dragSrcId}"]`));
 let parent=target.parentNode,next=after?target.nextSibling:target;
 if(next!==dragGhost)parent.insertBefore(dragGhost,next);
 $$('#jobs-body tr').forEach(x=>x.classList.remove('drop-before','drop-after','drag-near'));
 target.classList.add(after?'drop-after':'drop-before','drag-near');
 dragTargetId=target.dataset.id;dragAfter=after;
}
function bindRowDnD(tr){
 if(tr.getAttribute('draggable')!=='true')return;
 tr.addEventListener('dragstart',e=>{dragSrcId=tr.dataset.id;dragTargetId=null;dragAfter=false;tr.classList.add('dragging');dragImage=makeDragImage(tr,e);requestAnimationFrame(()=>tr.classList.add('dragging-active'));try{e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',tr.dataset.id)}catch{}});
 tr.addEventListener('dragend',()=>{dragSrcId=null;dragTargetId=null;tr.classList.remove('dragging','dragging-active');clearDragVisuals()});
 tr.addEventListener('dragover',e=>{if(!dragSrcId||dragSrcId===tr.dataset.id)return;e.preventDefault();try{e.dataTransfer.dropEffect='move'}catch{}let r=tr.getBoundingClientRect(),after=(e.clientY-r.top)>r.height/2;placeDragGhost(tr,after)});
 tr.addEventListener('drop',e=>{e.preventDefault();e.stopPropagation();let srcId=dragSrcId||e.dataTransfer?.getData('text/plain'),targetId=dragTargetId||tr.dataset.id,after=dragTargetId!==null?dragAfter:(e.clientY-tr.getBoundingClientRect().top)>tr.getBoundingClientRect().height/2;if(!srcId||srcId===targetId){clearDragVisuals();return}clearDragVisuals();reorderJobs(srcId,targetId,after)})
}
async function reorderJobs(srcId,targetId,after){
 let from=cfg.jobs.findIndex(x=>x.id===srcId),to=cfg.jobs.findIndex(x=>x.id===targetId);
 if(from<0||to<0)return;
 let moved=cfg.jobs.splice(from,1)[0];
 let idx=cfg.jobs.findIndex(x=>x.id===targetId);
 cfg.jobs.splice(after?idx+1:idx,0,moved);
 // カラム並べ替え中の表示順と保存する問い合わせ順が食い違わないよう、ドロップ後は登録順へ戻す。
 if($('#sort'))$('#sort').value='order';sortDir=1;
 render();
 let payload=structuredClone(cfg);delete payload.credential_status;
 try{let rp=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(rp.ok){saveState('並び順を保存しました','is-ok');toast('問い合わせ順を更新しました')}else{dirty();toast('並び順を保存できませんでした。自動で再試行します')}}catch{dirty();toast('並び順を保存できませんでした。自動で再試行します')}
}
async function deleteJob(j){
 if(!confirm(`管理単位「${j.name}」を削除します。よろしいですか？\n登録内容と自動実行ルールが削除されます（この操作は元に戻せません）。`))return;
 let i=cfg.jobs.findIndex(x=>x.id===j.id);if(i<0)return;
 cfg.jobs.splice(i,1);render();
 let payload=structuredClone(cfg);delete payload.credential_status;
 try{let r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(r.ok){saveState('管理単位を削除しました','is-ok');await init();toast(`「${j.name}」を削除しました`)}else{dirty();toast('削除を保存できませんでした。自動で再試行します')}}catch{dirty();toast('削除を保存できませんでした。自動で再試行します')}
}
function fillSuggestions(){let sets={names:cfg.jobs.map(j=>j.name),rne:cfg.jobs.map(j=>j.rne_path),output:[cfg.default_output_folder,...cfg.jobs.map(j=>j.output_folder)],'output-file':cfg.jobs.map(j=>j.output_file),table:cfg.jobs.map(j=>j.table),sheet:cfg.jobs.map(j=>j.sheet)};Object.entries(sets).forEach(([k,v])=>$('#suggest-'+k).innerHTML=[...new Set(v.filter(Boolean))].map(x=>`<option value="${E(x)}">`).join(''))}
function rulesRender(){let box=$('#m-rules');box.innerHTML=editing.schedules.length?editing.schedules.map(r=>`<div class="rule-row" data-id="${r.id}"><input class="rule-toggle" type="checkbox" ${r.enabled?'checked':''}><b>${E(r.name)}</b><span class="rule-type">${typeName(r.type)}</span><span class="rule-summary">${E(scheduleSummary(r))}</span><button class="rule-edit secondary" type="button">編集</button><button class="rule-delete danger" type="button">削除</button></div>`).join(''):'<div class="empty">自動実行ルールはありません。手動実行のみです。</div>';box.querySelectorAll('.rule-row').forEach(el=>{let r=editing.schedules.find(x=>x.id===el.dataset.id);el.querySelector('.rule-toggle').onchange=e=>{r.enabled=e.target.checked;dirty()};el.querySelector('.rule-edit').onclick=()=>openRule(r);el.querySelector('.rule-delete').onclick=()=>{editing.schedules=editing.schedules.filter(x=>x.id!==r.id);rulesRender()}});updateRuleCount()}
let contextJob=null,contextRow=null;
function hideJobContextMenu(){let m=$('#job-context-menu');if(m)m.hidden=true;contextJob=null;contextRow=null}
function showJobContextMenu(e,j,tr){let m=$('#job-context-menu');if(!m)return;contextJob=j;contextRow=tr;m.hidden=false;let ids=contextTargets(),many=ids.length>1;if($('#jcm-name'))$('#jcm-name').textContent=many?`選択した ${ids.length}件`:(j.name||'');if($('#jcm-rne'))$('#jcm-rne').textContent=many?'まとめて実行できます':(j.rne||'');let rb=m.querySelector('[data-action="run"]');if(rb)rb.textContent=many?`選択した ${ids.length}件を実行`:'実行';let tb=m.querySelector('[data-action="toggle"]');if(tb)tb.textContent=j.enabled?'無効にする':'有効にする';let x=Math.min(e.clientX,innerWidth-m.offsetWidth-8),y=Math.min(e.clientY,innerHeight-m.offsetHeight-8);m.style.left=Math.max(8,x)+'px';m.style.top=Math.max(8,y)+'px'}
async function copyTextValue(v,label){try{await navigator.clipboard.writeText(v||'');toast(label+'をコピーしました')}catch{toast('クリップボードへコピーできませんでした')}}
async function openJobOutput(j){try{let r=await fetch('/api/open-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:j.output_folder||cfg.default_output_folder})}),d=await r.json();toast(r.ok&&d.ok?'出力先を開きました':d.error||'出力先を開けませんでした')}catch{toast('出力先を開けませんでした')}}
function duplicateJob(j){let n=structuredClone(j);n.id=uid();n.name+=' コピー';n.schedules=(n.schedules||[]).map(r=>({...r,id:uid(),enabled:false}));cfg.jobs.splice(cfg.jobs.indexOf(j)+1,0,n);render();dirty()}
/* 右クリックの操作盤。一覧の行から、その対象について「よくやること」へ直行できる。
   どの対象に対する操作なのかが分からないと押せないので、先頭に名前とRNEを出す。
   行を選んだ状態で右クリックしたときは、選択した全件が対象になる。 */
function contextTargets(){
 let ids=$$('#jobs-body .rowcheck:checked').map(x=>x.closest('tr').dataset.id);
 if(contextJob&&ids.includes(contextJob.id)&&ids.length>1)return ids;
 return contextJob?[contextJob.id]:[];
}
function jobFolder(path){return String(path||'').replace(/[\\/][^\\/]*$/,'')}
async function inspectNow(j){
 try{
  let d=await fetch('/api/inspect-task/all',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({job_id:j.id,rne_path:j.rne_path||j.rne,job_name:j.name,parts:2})}).then(r=>r.json());
  if(d.ok){toast(`「${j.name}」の調査を裏で始めました`);loadBgTasks()}else toast(d.error||'調査を始められませんでした');
 }catch{toast('調査を始められませんでした')}
}
function showJobLog(j){
 document.querySelector('[data-p="logs"]')?.click();
 setTimeout(()=>{let q=$('#log-filter-text');if(q){q.value=j.name;applyLogFilter()}
  toast(`ログを「${j.name}」で絞り込みました`)},120);
}
async function moveJob(j,dir){
 let i=cfg.jobs.findIndex(x=>x.id===j.id),to=i+dir;
 if(i<0||to<0||to>=cfg.jobs.length)return toast(dir<0?'すでに先頭です':'すでに最後です');
 await reorderJobs(j.id,cfg.jobs[to].id,dir>0);
}
if($('#job-context-menu')){$('#job-context-menu').onclick=e=>{
 let a=e.target.closest('[data-action]');if(!a||!contextJob)return;
 let j=contextJob,act=a.dataset.action,ids=contextTargets();
 hideJobContextMenu();
 if(act==='edit')openEditor(j);
 else if(act==='inspect'){openEditor(j);setEditorTab('inspect');inspGo('read')}
 else if(act==='inspect-now')inspectNow(j);
 else if(act==='run')runJobs(ids);
 else if(act==='open-output')openJobOutput(j);
 else if(act==='open-rne')openFolderPath(jobFolder(j.rne_path||j.rne)||cfg.rne_folder,'RNEのフォルダー');
 else if(act==='log')showJobLog(j);
 else if(act==='viewer'){document.querySelector('[data-p="viewer"]')?.click();setTimeout(()=>{let sel=$('#viewer-job');if(sel){sel.value=j.id;sel.dispatchEvent(new Event('change'))}},100)}
 else if(act==='copy-rne')copyTextValue(j.rne_path||j.rne,'RNEパス');
 else if(act==='copy-output')copyTextValue(j.output_folder||cfg.default_output_folder,'出力先');
 else if(act==='copy-file')copyTextValue(j.output_file||'','出力ファイル名');
 else if(act==='move-up')moveJob(j,-1);
 else if(act==='move-down')moveJob(j,1);
 else if(act==='duplicate')duplicateJob(j);
 else if(act==='toggle'){j.enabled=!j.enabled;render();dirty();toast(j.enabled?'有効にしました':'無効にしました')}
 else if(act==='delete')deleteJob(j)};
 document.addEventListener('click',e=>{if(!e.target.closest('#job-context-menu'))hideJobContextMenu()});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')hideJobContextMenu()});
 window.addEventListener('blur',hideJobContextMenu)}
async function openFolderPath(path,label){
 if(!path)return toast(`${label}が設定されていません`);
 try{let d=await fetch('/api/open-path',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path})}).then(r=>r.json());
  toast(d.ok?`${label}を開きました`:(d.error||`${label}を開けませんでした`))}
 catch{toast(`${label}を開けませんでした`)}
}
function openEditor(job){editing=structuredClone(job||{id:uid(),name:'新しい対象',enabled:true,rne:'NEW.RNE',rne_path:cfg.rne_folder+'\\NEW.RNE',output_folder:cfg.default_output_folder,output_format:'sqlite3',output_file:'NEW.sqlite3',extra_formats:[],table:'仕掛',sheet:'Page1',type:'詳細データ',naming_mode:'fixed',output_pattern:'',comment:'',split_mode:'auto',split_shape:'auto',period:{enabled:false,control_point:'',unit:'month',from_offset:-1,to_offset:0},schedules:[]});$('#modal-title').textContent=job?'対象を編集':'対象を追加';$('#m-id').value=editing.id;$('#m-name').value=editing.name;$('#m-enabled').checked=editing.enabled;$('#m-rne-path').value=editing.rne_path||'';$('#m-output').value=editing.output_folder||cfg.default_output_folder;editing.output_format=normalizeFormat(editing.output_format);editing.extra_formats=(editing.extra_formats||[]).map(normalizeFormat);$('#m-format').value=editing.output_format;$('#m-output-file').value=editing.output_file;$('#m-table').value=editing.table;$('#m-sheet').value=editing.sheet;$('#m-type').value=editing.type;if($('#m-comment'))$('#m-comment').value=editing.comment||'';if($('#m-split-mode'))$('#m-split-mode').value=editing.split_mode||'auto';if($('#m-split-shape'))$('#m-split-shape').value=editing.split_shape||'auto';if($('#m-axis-mode'))$('#m-axis-mode').value=editing.row_axis_mode||'first';if($('#m-axis-index'))$('#m-axis-index').value=editing.row_axis_index||1;AXIS_PICK.forEach(g=>{if($(g.n))$(g.n).innerHTML=`<option value="${E(editing.row_axis_name||'')}">${E(editing.row_axis_name||'（先に「RNEを調査」）')}</option>`;if($(g.m))$(g.m).value=editing.row_axis_mode||'first';if($(g.i))$(g.i).value=editing.row_axis_index||1});syncAxisPick();syncOutputExtension();initNaming(editing);setPeriodUI(editing.period);renderRuntimeSplit(null);inspReset();loadMaster(false);splitTrialPoll();rulesRender();updatePeriodBadge();setEditorTab('basic');$('#editor').showModal()}
$('#m-format').onchange=()=>{syncOutputExtension();if(currentNamingMode()==='template')refreshNamePreview()};$('#m-rne-check').onclick=async()=>{showWaiting('RNEファイル確認中','設定場所と周辺フォルダーを検索しています...');try{let temp={item:'rne',job_id:editing.id,label:editing.rne,configured:$('#m-rne-path').value,resolved:$('#m-rne-path').value,candidates:[],ok:false};let r=await fetch('/api/path-check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item:'rne',job_id:editing.id,value:$('#m-rne-path').value,expected_name:$('#m-rne-path').value.split(/[\\/]/).pop()})}),d=await r.json();if(r.ok)showPathResult(d);else toast(d.error)}finally{hideWaiting()}};$('#m-rne-pick').onclick=async()=>{let p=await browse('file',$('#m-rne-path').value,[['RNEファイル','*.RNE'],['すべて','*.*']]);if(p){let i=$('#m-rne-path'),wasRel=i.value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(i.value);i.value=p;if(wasRel)await convertPath(i,'relative');updatePathBadge(i);i._refreshPathControl?.()}};$('#m-output-pick').onclick=async()=>{let p=await browse('folder',$('#m-output').value);if(p){let i=$('#m-output'),wasRel=i.value&&!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(i.value);i.value=p;if(wasRel)await convertPath(i,'relative');updatePathBadge(i)}};enhancePathInput($('#m-rne-path'),'file');enhancePathInput($('#m-output'),'folder');$('#m-rne-path').addEventListener('input',()=>renderInspTarget());$('#m-name').addEventListener('input',()=>renderInspTarget());$('#add-rule').onclick=()=>openRule({id:uid(),enabled:true,name:'実行ルール',type:'daily',time:'06:00'},true);/* 編集中の内容を、対象の設定として確定する。
   「本番で使う」からもここを通す。測って選んだのに保存を押し忘れて効かない、
   という切れ目を作らないため（close=false なら画面は開いたまま）。 */
function collectJob(){
 syncOutputExtension();
 const f=normalizeFormat($('#m-format').value),file=canonicalOutputFile($('#m-output-file').value,f);
 return {...editing,name:$('#m-name').value.trim(),enabled:$('#m-enabled').checked,
  rne_path:$('#m-rne-path').value.trim(),rne:$('#m-rne-path').value.trim().split(/[\\/]/).pop(),
  output_folder:$('#m-output').value.trim(),output_format:f,output_file:file,extra_formats:alsoFormats(),
  table:$('#m-table').value.trim(),sheet:$('#m-sheet').value.trim(),type:$('#m-type').value,
  naming_mode:currentNamingMode(),output_pattern:$('#m-output-pattern').value.trim(),
  comment:($('#m-comment')?.value||'').trim(),
  split_mode:($('#m-split-mode')?.value||'auto'),split_shape:($('#m-split-shape')?.value||'auto'),
  row_axis_mode:($('#m-axis-mode')?.value||'first'),row_axis_index:Number($('#m-axis-index')?.value||1)||1,
  row_axis_name:($('#m-axis-name')?.value||''),period:currentPeriod()};
}
async function applyJob(close=true,quiet=false){
 const updated=collectJob();
 let i=cfg.jobs.findIndex(j=>j.id===updated.id);
 if(i<0)cfg.jobs.unshift(updated);else cfg.jobs[i]=updated;
 editing=structuredClone(updated);
 let payload=structuredClone(cfg);delete payload.credential_status;
 if(!quiet)showWaiting('設定を保存中',`${formatName(updated.output_format)} / ${updated.output_file}`);
 try{
  let r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();
  if(!r.ok)throw Error(d.error||'設定保存失敗');
  if(close){$('#editor').close();await init();toast(`保存完了: ${formatName(updated.output_format)} / ${updated.output_file}`)}
  else{render();saveState('対象の設定を保存しました','is-ok')}
  return true;
 }catch(x){toast(x.message);return false}
 finally{if(!quiet)hideWaiting()}
}
$('#apply').onclick=async e=>{e.preventDefault();await applyJob(true)};

/* V35: dynamic output filename builder */
let namePreviewTimer=null;
function currentNamingMode(){return document.querySelector('.naming-tab.on')?.dataset.mode||'fixed'}
function setNamingMode(mode){$$('.naming-tab').forEach(b=>b.classList.toggle('on',b.dataset.mode===mode));$('#naming-fixed')?.classList.toggle('on',mode==='fixed');$('#naming-template')?.classList.toggle('on',mode==='template');if(mode==='template')refreshNamePreview()}
function initNaming(job){if($('#m-output-pattern'))$('#m-output-pattern').value=job.output_pattern||'';setNamingMode(job.naming_mode==='template'?'template':'fixed')}
function insertToken(tok){let i=$('#m-output-pattern');if(!i)return;let s=i.selectionStart??i.value.length,e=i.selectionEnd??i.value.length;i.value=i.value.slice(0,s)+tok+i.value.slice(e);let pos=s+tok.length;i.focus();i.setSelectionRange(pos,pos);refreshNamePreview();dirty()}
function refreshNamePreview(){let el=$('#m-name-preview'),meta=$('#m-name-preview-meta');if(!el)return;let pattern=$('#m-output-pattern')?.value||'';if(!pattern.trim()){el.textContent='—';if(meta)meta.textContent='パターンを入力すると実ファイル名を試算します';return}clearTimeout(namePreviewTimer);namePreviewTimer=setTimeout(async()=>{try{let r=await fetch('/api/preview-filename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pattern,rne_path:$('#m-rne-path').value,name:$('#m-name').value,table:$('#m-table').value,format:normalizeFormat($('#m-format').value),output_file:$('#m-output-file').value})}),d=await r.json();if(!d.ok){el.textContent='(命名エラー)';if(meta)meta.textContent=d.error||'';return}if(d.segments&&d.segments.length)el.innerHTML=segmentHtml(d.segments);else el.textContent=d.filename;if(meta)meta.textContent=(d.is_variable?'色付き部分が変数です。':'変数は使われていません（固定文字）。')+(d.rne_found?` 対象RNE 更新日 ${d.rne_mtime} / 作成日 ${d.rne_ctime}`:' 対象RNEが未検出のため更新日・作成日は空になります')+` / 実行日時 ${d.now}`;renderAlsoFormats()}catch{el.textContent='(プレビュー取得失敗)';if(meta)meta.textContent=''}},250)}
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
if($('#m-output-file'))$('#m-output-file').addEventListener('input',()=>{updateFixedNameNote();renderAlsoFormats();dirty()});
/* v1.0.0: editor modal tabs (基本・入出力 / 自動実行) for a scroll-less layout */
function setEditorTab(tab){$$('.editor-tab').forEach(b=>b.classList.toggle('on',b.dataset.etab===tab));$$('.editor-pane').forEach(p=>p.classList.toggle('on',p.dataset.etab===tab))}
function currentEditorTab(){return document.querySelector('.editor-tab.on')?.dataset.etab||'basic'}
$$('.editor-tab').forEach(b=>b.onclick=()=>{setEditorTab(b.dataset.etab);if(b.dataset.etab==='inspect')inspTaskResume()});   // 調べものが走っていれば途中から追いかける
function updatePeriodBadge(){let b=$('#etab-period-on');if(b)b.hidden=!$('#m-period-enabled')?.checked}
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
function setExtractEngine(v){let s=$('#extract-engine');if(s)s.value=v;updateEngineUI();dirty()}/* ==== このPCでの実際の場所 ==================================================
   設定はBOXのマスターを通じて全PCへ配られる。絶対パスで特定の利用者の
   フォルダーを書くと、別のPCでは他人のフォルダーを指して実行できない。
   実際に走らせるまで気づけなかったので、設定の画面でそのまま見せる。 */
/* 実体が無いだけで赤くすると、本当に直すべきものが埋もれる。いまの構成で要るか
   （required / fallback / unused）はサーバーが決め、画面はその重みどおりに並べる。 */
const MP_STATE={ok:['使えます','ok'],warn:['注意','warn'],ng:['要対応','ng']};
const MP_ROLE={required:['','',0],fallback:['予備','fb',1],unused:['いまは不要','un',2]};
function mpWord(x){
 if(x.state!=='ok')return MP_STATE[x.state]||MP_STATE.ok;
 let r=MP_ROLE[x.role]||MP_ROLE.required;
 return r[0]?[r[0],r[1]]:MP_STATE.ok;
}
async function loadMachinePaths(){
 let box=$('#mp-rows');if(!box)return;
 try{
  let d=await fetch('/api/machine-paths',{cache:'no-store'}).then(r=>r.json());
  let who=$('#mp-who');
  if(who)who.textContent=`${d.host||''}${d.user?' / '+d.user:''}${d.profile?'（'+d.profile+'）':''}`;
  let st=$('#mp-state');
  if(st){st.textContent=d.summary||'';st.className='pill '+(d.ok?'pill-ok':'pill-ng')}
  // 直すべきものが上、いま使わないものが下。読む順がそのまま優先順になる。
  let order=x=>(x.state==='ng'?-2:x.state==='warn'?-1:(MP_ROLE[x.role]||MP_ROLE.required)[2]);
  let sorted=(d.rows||[]).map((x,i)=>[order(x),i,x]).sort((a,b)=>a[0]-b[0]||a[1]-b[1]).map(x=>x[2]);
  let mark=null;
  box.innerHTML=sorted.map(x=>{
   let [word,tone]=mpWord(x),head='';
   if(x.state==='ok'&&x.role==='unused'&&mark!=='un'){mark='un';head='<p class="mp-divider">いまの構成では使わない設定</p>'}
   return head+`<div class="mp-row is-${E(tone)}"><i>${E(word)}</i><div class="mp-main"><b>${E(x.label)}</b>`
    +`<code class="mp-set" title="${E(x.configured)}">設定: ${E(x.configured||'（未設定）')}</code>`
    +`<code class="mp-real" title="${E(x.resolved)}">実体: ${E(x.resolved)}</code>`
    +(x.note?`<small>${E(x.note)}</small>`:'')+`</div>`
    +(x.foreign?`<button type="button" class="secondary mp-fix" data-k="${E(x.key)}">このPCの場所へ直す</button>`:'')
    +`</div>`}).join('');
  let fb=$('#mp-fixed');
  if(fb)fb.innerHTML=(d.fixed||[]).map(x=>`<div class="mp-row is-fix"><i>固定</i><div class="mp-main">`
    +`<b>${E(x.label)}</b><code class="mp-real" title="${E(x.path)}">${E(x.path)}</code>`
    +`<small>${E(x.note)}</small></div></div>`).join('');
  $$('.mp-fix').forEach(b=>b.onclick=()=>{
   let k=b.dataset.k,inp=$('#'+k);
   let v=k==='backup_folder'?'<PC>\\backup':'<PC>\\'+k;
   cfg[k]=v;if(inp){inp.value=v;inp._refreshPathControl?.()}
   dirty();toast(`${k} をこのPCの場所（${v}）へ直しました`);setTimeout(loadMachinePaths,900);
  });
 }catch{box.innerHTML='<p class="ri-note">確認できませんでした。</p>'}
}
if($('#mp-reload'))$('#mp-reload').onclick=loadMachinePaths;
function updateHideProfileUI(){let p=$('#hide-profile').value,custom=p==='custom';$('#hide-interval-wrap').style.display=custom?'grid':'none';$('#hide-action-duration-wrap').style.display=custom?'grid':'none';let descriptions={action_only:'DDE操作直後だけ確認。常時監視なし',light:'3秒間隔。負荷を最優先',balanced:'2秒間隔。負荷と非表示性のバランス',standard:'1秒間隔。非表示性を優先',custom:'1秒以上で任意設定'};$('#hide-profile').title=descriptions[p]||''}async function init(){cfg=await fetch('/api/config').then(r=>r.json());cfg.jobs.forEach(j=>{j.id=j.id||uid();j.name=j.name||j.rne.replace(/\.RNE$/i,'');j.schedules=j.schedules||[]});$('#cred').textContent=cfg.credential_status;$('#pathform').innerHTML=Object.entries(paths).filter(([k])=>k!=='navigator_api_dll').map(([k,a])=>`<label>${a[0]}<div class="browse"><input id="${k}" value="${E(cfg[k]||'')}"><div class="path-actions">${['navigator_api_dll','symnavim_conf','symnavim_def','accdb_template'].includes(k)?`<button class="pathcheck verify-btn" data-k="${k}" type="button">確認</button>`:''}<button class="pathpick browse-btn" data-k="${k}" type="button">参照</button></div></div></label>`).join('');Object.entries(paths).filter(([k])=>k!=='navigator_api_dll').forEach(([k,a])=>{$('#'+k).onchange=e=>{cfg[k]=e.target.value;dirty()};document.querySelector(`[data-k="${k}"]`).onclick=async()=>{let p=await browse(a[1],cfg[k],a[2]);if(p){cfg[k]=p;$('#'+k).value=p;dirty()}}});$('#extract-engine').value=cfg.settings.extract_engine||'api';updateEngineUI();$('#dde').value=cfg.settings.dde_timeout_seconds;$('#wait').value=cfg.settings.output_wait_seconds;$('#gens').value=cfg.settings.backup_generations||3;if($('#backup-enabled'))$('#backup-enabled').checked=cfg.settings.backup_enabled!==false;if($('#backup-mode'))$('#backup-mode').value=cfg.settings.backup_mode||'generations';if($('#backup-retention-days'))$('#backup-retention-days').value=Number(cfg.settings.backup_retention_days||30);if($('#schedule-catchup'))$('#schedule-catchup').value=Number(cfg.settings.schedule_catchup_minutes??30);if($('#worker-stagger'))$('#worker-stagger').value=Number(cfg.settings.api_worker_stagger_ms??700);updateBackupOptions();if($('#api-lines')){$('#api-lines').value=Math.max(1,Math.min(24,Number(cfg.settings.api_parallel_lines||6)));$('#api-lines').title='既定は6ライン、設定可能範囲は1～24ラインです。変更した時点で保存されます。'}$('#zero').checked=cfg.settings.reject_zero_rows;if($('#retry-enabled')){$('#retry-enabled').checked=cfg.settings.retry_enabled!==false;$('#retry-delay').value=Number(cfg.settings.retry_delay_minutes??5);$('#retry-max').value=Number(cfg.settings.retry_max??1);updateRetryOptions()}$('#hide-profile').value=cfg.settings.symnavi_hide_profile||'balanced';$('#hide-interval').value=Math.max(1,Number(cfg.settings.symnavi_hide_interval_seconds||2));$('#hide-action-duration').value=Number(cfg.settings.symnavi_hide_action_duration_seconds||0.5);updateHideProfileUI();Object.keys(paths).filter(k=>k!=='navigator_api_dll').forEach(k=>enhancePathInput($('#'+k),paths[k][1]));let dllInput=$('#navigator-api-dll');if(dllInput){dllInput.value=cfg.navigator_api_dll||'';dllInput.oninput=()=>{cfg.navigator_api_dll=dllInput.value;dirty();
   let v=$('#api-readiness');if(v)v.className='api-readiness is-stale';};}let dllPick=$('#api-dll-pick');if(dllPick)dllPick.onclick=async()=>{let q=await browse('file',dllInput.value,paths.navigator_api_dll[2]);if(q){dllInput.value=q;cfg.navigator_api_dll=q;dirty();await testNavigatorApi()}};let dllCheck=$('#api-dll-check');if(dllCheck)dllCheck.onclick=()=>testNavigatorApi();if(!Array.isArray(cfg.navigator_api_search_roots))cfg.navigator_api_search_roots=DLL_DEFAULT_ROOTS.slice();renderDllRoots();loadDllRequirement();fillSuggestions();render();loadMachinePaths();saveState('設定を読み込みました／変更はすべて自動で保存されます','');$$('.pathcheck').forEach(b=>b.onclick=()=>checkConfiguredPath(b.dataset.k))}
['search','filter-enabled','filter-schedule','sort'].forEach(k=>$('#'+k).addEventListener(k==='search'?'input':'change',render));$$('.sortable').forEach(h=>h.onclick=()=>{$('#sort').value=h.dataset.sort;sortDir*=-1;render()});$('#add').onclick=()=>openEditor(null);$('#select-visible').onclick=()=>{$$('#jobs-body .rowcheck').forEach(x=>{x.checked=true;x.closest('tr').classList.add('selected')});updateSelCount()};$('#clear-selection').onclick=()=>{$$('#jobs-body .rowcheck').forEach(x=>{x.checked=false;x.closest('tr').classList.remove('selected')});updateSelCount()};function resetProgressView(){let q=$('#queue-summary');if(q){q.hidden=true;q.innerHTML=''}let pr=$('#p-results');if(pr){pr.hidden=true;pr.innerHTML=''}let b=$('#p-parallel-lines');if(b){b.hidden=true;b.innerHTML=''}document.querySelector('.current-box')?.classList.remove('parallel-hidden');$('#p-steps')?.classList.remove('parallel-hidden');$('#p-count').textContent='全体 0 / 0';$('#p-percent').textContent='0%';$('#p-bar').style.width='0%';$('#p-job').textContent='準備中';$('#p-output').textContent='';}async function runJobs(ids){resetProgressView();showWaiting(currentEngine()==='api'?'API処理を開始しています':'DDE処理を開始しています',currentEngine()==='api'?'APIセッションと実行対象を準備しています...':'SymfoNavi起動とDDE接続を準備しています...','engine');let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_ids:ids,parallel_lines:Math.max(1,Math.min(24,Number($('#api-lines')?.value||6)||6))})}),d=await r.json();hideWaiting();if(r.ok){toast(`実行キュー ${d.position}番へ追加しました`);await loadCommandQueue()}else toast(d.error)}$('#run-all').onclick=()=>runJobs(null);$('#run-selected').onclick=()=>{let ids=$$('#jobs-body .rowcheck:checked').map(x=>x.closest('tr').dataset.id);if(ids.length)runJobs(ids)};/* 保存ボタンの代わりに、値が変わったところで保存する。数値欄は打っている途中に
   何度も飛ばさないよう、まとめて少し待ってから送る（scheduleSave）。 */
['dde','wait','schedule-catchup','worker-stagger','hide-interval','hide-action-duration'].forEach(id=>{let e=$('#'+id);if(e){e.addEventListener('input',dirty);e.addEventListener('change',dirty)}});
['zero','extract-engine','hide-profile','backup-mode','backup-enabled'].forEach(id=>{let e=$('#'+id);if(e)e.addEventListener('change',dirty)});
['retry-delay','retry-max'].forEach(id=>{let e=$('#'+id);if(e){e.addEventListener('input',dirty);e.addEventListener('change',dirty)}});
if($('#retry-enabled'))$('#retry-enabled').addEventListener('change',()=>{updateRetryOptions();dirty()});
function updateRetryOptions(){let on=$('#retry-enabled')?.checked;let box=$('#retry-options');if(box)box.style.display=on?'':'none'}$('#validate').onclick=async()=>{showWaiting(currentEngine()==='api'?'API実行前診断中':'DDE実行前診断中','実際の設定値と配置を統合して確認しています...','engine');try{let r=await fetch('/api/validate',{method:'POST'}),d=await r.json();if(!r.ok)throw Error(d.error||'診断に失敗しました');renderDiagnostics(d);let dlg=$('#diagnostic-dialog');if(dlg&&!dlg.open)dlg.showModal()}catch(e){toast(e.message)}finally{hideWaiting()}};function renderDiagnostics(d){$('#check-scope').textContent=d.search_scope||'';let state=$('#diagnostic-state');state.textContent=d.summary||'';state.className='diag-state '+(d.ok?'is-ok':'is-ng');let c=d.counts||{};$('#diagnostic-counts').innerHTML=`<span class="dc-ok">正常 ${c.ok||0}</span><span class="dc-warn">注意 ${c.warning||0}</span><span class="dc-ng">要修正 ${c.error||0}</span>`;let groups={};(d.checks||[]).forEach((x,i)=>(groups[x.group]||(groups[x.group]=[])).push({...x,_i:i}));$('#checks').innerHTML=Object.entries(groups).map(([g,items])=>`<section class="diag-group"><h3>${E(g)}<small>${items.length}項目</small></h3>${items.map(x=>`<div class="diag-row ${E(x.level)}"><i>${x.level==='ok'?'OK':x.level==='warning'?'注意':'要修正'}</i><div><b>${E(x.label)}</b><span>${E(x.detail)}</span></div>${x.candidates?.length?`<button class="fix secondary" data-i="${x._i}">候補 ${x.candidates.length}件</button>`:''}</div>`).join('')}</section>`).join('');$$('#checks .fix').forEach(b=>b.onclick=()=>showPathResult(d.checks[Number(b.dataset.i)]))}if($('#diagnostic-close'))$('#diagnostic-close').onclick=()=>$('#diagnostic-dialog').close();if($('#diagnostic-close-foot'))$('#diagnostic-close-foot').onclick=()=>$('#diagnostic-dialog').close();let commandQueueOpen=false;async function loadCommandQueue(){try{let d=await fetch('/api/execution-queue',{cache:'no-store'}).then(r=>r.json()),list=$('#cq-list'),summary=$('#cq-summary');applyRowQueueProgress(d);if(!list||!summary)return;
 let st=latestStatus||{},running=!!st.running;
 // 実行中バッチの対象(job)単位の実状態。バッジ件数を実進捗に連動させる。
 let jobDone=running?(st.queue_completed_ids||[]).length:0,jobFail=running?(st.queue_failed_ids||[]).length:0;
 let jobRun=running?(st.execution_mode==='parallel'?(st.queue_running_ids||[]).length:(st.current_job_id?1:0)):0;
 let batchLen=running?((st.batch_job_ids||[]).length):0;
 let batchWait=Math.max(0,batchLen-jobDone-jobFail-jobRun);let batchFinished=jobDone+jobFail,batchPct=batchLen?Math.round(batchFinished/batchLen*100):0;
 // 実行待ちキュー（未開始の実行指令）に含まれる対象数。
 let queuedJobs=d.items.filter(x=>x.state==='waiting').reduce((s,x)=>s+(x.count||1),0);
 /* 実行キュー全体（実行中バッチ＋待機予約すべて）の進捗。個別キューの進捗バーと同じデータバー表現で全体像を示す。 */
 let overallTotal=batchLen+queuedJobs,overallDone=batchFinished,overallRun=jobRun,anyQueue=running||d.items.length>0;
 /* 完了件数だけで測ると、重い対象を6本並列で処理している最中はずっと0%のままになり、
    動いていることが伝わらない。実行中の各ラインの進捗を持ち分として足し、連続して動くようにする。 */
 let runFraction=(st.parallel_lines||[]).filter(l=>l.job&&l.percent>0&&l.percent<100).reduce((a,l)=>a+Math.min(1,l.percent/100),0);
 if(!runFraction&&overallRun)runFraction=overallRun*0.05;
 runFraction=Math.min(runFraction,Math.max(0,overallTotal-overallDone));
 let donePct=overallTotal?overallDone/overallTotal*100:0,runPct=overallTotal?runFraction/overallTotal*100:0;
 let overallPct=Math.min(100,Math.round(donePct+runPct));
 let qo=$('#cq-overall');if(qo){qo.hidden=!anyQueue;$('#cq-progress-label').textContent=`全体 ${overallDone} / ${overallTotal} 完了`+(overallRun?` ・ 実行中 ${overallRun}`:'');$('#cq-progress-percent').textContent=overallPct+'%';$('#cq-progress-bar').style.width=donePct.toFixed(1)+'%';let rb=$('#cq-progress-run');if(rb){rb.style.width=runPct.toFixed(1)+'%';rb.hidden=runPct<=0}let qt=qo.querySelector('.cq-progress-track');if(qt)qt.title=`完了 ${overallDone} / 実行中 ${overallRun} / 待機 ${Math.max(0,overallTotal-overallDone-overallRun)} / 全体 ${overallTotal}`;}
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
  return `<div class="cq-row ${x.state}"><span class="cq-pos">${x.state==='running'?'実行中':x.position+'番'}</span><div class="cq-main"><b>${E((x.job_names||[]).join(' / '))}</b><small>${x.state==='running'?E(stateInfo):('登録 '+E(x.enqueued_at||'')+' / '+(x.count||0)+'対象')}</small></div><span class="cq-mode">${x.engine==='dde'?'DDE 1件ずつ':x.parallel_lines>1?x.parallel_lines+'ライン':'API 1ライン'}</span><div class="cq-actions">${x.state==='waiting'?`<button class="secondary cq-up" data-id="${x.id}">上へ</button><button class="secondary cq-down" data-id="${x.id}">下へ</button><button class="danger cq-delete" data-id="${x.id}">解除</button>`:'<span>処理中は変更不可</span>'}</div></div>`}).join(''):'<div class="cq-empty">実行待ちのキューはありません</div>';list.hidden=!commandQueueOpen;$$('.cq-up,.cq-down').forEach(b=>b.onclick=async()=>{await fetch(`/api/execution-queue/${b.dataset.id}/move`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({direction:b.classList.contains('cq-up')?'up':'down'})});loadCommandQueue()});$$('.cq-delete').forEach(b=>b.onclick=async()=>{let r=await fetch(`/api/execution-queue/${b.dataset.id}`,{method:'DELETE'});if(r.ok)toast('実行キューから解除しました');loadCommandQueue()})}catch{}}{const cqToggle=$('#cq-toggle');if(cqToggle)cqToggle.onclick=()=>{commandQueueOpen=!commandQueueOpen;cqToggle.textContent=commandQueueOpen?'閉じる':'一覧';loadCommandQueue()};}function logLevel(line){return line.includes('[ERROR]')?'error':line.includes('[WARNING]')?'warning':'info'}function buildLogTree(text){let lines=(text||'').split(/\r?\n/).filter(Boolean),groups=[],current=null,job=null;for(let line of lines){if(line.includes('処理開始 trigger=')){current={title:line.slice(0,19)+'  実行指令',lines:[],jobs:[]};groups.push(current);job=null}else if(line.includes('設定保存 job=')){current={title:line.slice(0,19)+'  設定保存',lines:[line],jobs:[]};groups.push(current);job=null;continue}if(!current){current={title:'その他のログ',lines:[],jobs:[]};groups.push(current)}let m=line.match(/(?:PIPELINE|JOB_RESULT) job=([^ ]+)/);if(m){job=current.jobs.find(x=>x.name===m[1])||{name:m[1],lines:[]};if(!current.jobs.includes(job))current.jobs.push(job)}if(job)job.lines.push(line);else current.lines.push(line);if(line.includes('正常終了')||line.includes('異常終了'))job=null}return groups}function logLines(lines){return `<div class="log-lines">${lines.map(x=>`<div class="log-line ${logLevel(x)}">${E(x)}</div>`).join('')}</div>`}function renderLogTree(text){let groups=buildLogTree(text);renderedLogGroups=groups.slice().reverse();$('#log').innerHTML=renderedLogGroups.length?renderedLogGroups.map((g,gi)=>`<details class="log-action" ${gi===0?'open':''} data-gi="${gi}"><summary><span><b>実行指令 ${renderedLogGroups.length-gi}</b> ${E(g.title)}</span><small>${g.jobs.length}ファイル</small><span class="log-summary-actions"><button class="secondary log-copy-full" data-gi="${gi}">全文コピー</button><button class="secondary log-copy-summary" data-gi="${gi}">要約コピー</button><button class="secondary danger-lite log-delete-group" data-gi="${gi}">削除</button></span></summary>${g.lines.length?logLines(g.lines):''}${g.jobs.map(j=>`<details class="log-job"><summary>${E(j.name)} <small>${j.lines.length}行</small></summary>${logLines(j.lines)}</details>`).join('')}</details>`).join(''):'<div class="empty">ログなし</div>';$$('.log-copy-full').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();let g=renderedLogGroups[Number(b.dataset.gi)];textToClipboard(groupText(g,'full'),'選択した実行指令ログをコピーしました')});$$('.log-copy-summary').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();let g=renderedLogGroups[Number(b.dataset.gi)];textToClipboard(groupText(g,'summary'),'選択した実行指令の要約ログをコピーしました')});$$('.log-delete-group').forEach(b=>b.onclick=async e=>{e.preventDefault();e.stopPropagation();let g=renderedLogGroups[Number(b.dataset.gi)],txt=groupText(g,'full');if(!confirm('この実行指令ログを削除しますか？'))return;let r=await fetch('/api/log/delete-lines',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:txt.split(/\n/)})});if(r.ok){toast('選択した実行指令ログを削除しました');await loadLog()}})}let latestLogText='',renderedLogGroups=[];async function loadLog(){let d=await fetch('/api/log').then(r=>r.json());latestLogText=d.text||'';renderLogTree(latestLogText)}/* コピーするログから「省略の印」を取り除く。
   ログには「｜ LOG_DEDUP 同じ内容を14行省略（28.2秒間・これが最後の1行）」が付くことがある。
   これは画面で読むための注記で、貼り付け先では邪魔にしかならない。
   行そのものは残す（何が起きたかは消さない）。消すのは印だけ。 */
function stripLogNoise(text){
 return String(text||'').split(/\r?\n/)
  .map(x=>x.replace(/\s*｜\s*LOG_DEDUP [^\n]*$/,''))
  .join('\n');
}
function textToClipboard(text,msg){text=stripLogNoise(text);if(!text?.trim())return toast('コピー対象のログがありません');navigator.clipboard?.writeText(text).then(()=>toast(msg)).catch(()=>{let ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast(msg)})}function groupText(g,mode='full'){let lines=[];lines.push(...(g.lines||[]));(g.jobs||[]).forEach(j=>lines.push(...j.lines));if(mode==='summary')lines=lines.filter(x=>/処理開始|STARTUP_PHASE|RUN_ENVIRONMENT|EXECUTION_MODE|WORKER_READY|PIPELINE|STEP_END phase=(api_open_catalog|api_execute_catalog|api_save_csv|api_save_xlsx_direct|format_conversion|publish)|ACCDB_|SQLITE_|XLSX_|PUBLISH_|PENDING_APPLY|PENDING_SCAN|BATCH_ORDER|API_DIAG|JOB_RESULT|JOB_PROFILE|PARALLEL_BATCH_END|正常終了|異常終了/.test(x));return lines.join('\n').trim()}function copyAllLog(){textToClipboard(latestLogText,'表示中のログ全体をコピーしました')}async function copyReportLog(){await loadLog();let g=renderedLogGroups[0];if(g)return textToClipboard(groupText(g),'最新の実行指令ログをコピーしました');let lines=latestLogText.split(/\r?\n/),start=-1;for(let i=lines.length-1;i>=0;i--){if(lines[i].includes('処理開始 trigger=')){start=i;break}}textToClipboard((start>=0?lines.slice(start):lines).join('\n').trim(),'最新の実行指令ログをコピーしました')}async function clearLog(){if(!confirm('表示中の実行ログを消去しますか？'))return;let r=await fetch('/api/log/clear',{method:'POST'});if(r.ok){latestLogText='';renderLogTree('');toast('ログを消去しました')}}if($('#copy-all-log'))$('#copy-all-log').onclick=async()=>{await loadLog();copyAllLog()};if($('#copy-report-log'))$('#copy-report-log').onclick=copyReportLog;if($('#clear-log'))$('#clear-log').onclick=clearLog;if($('#reload'))$('#reload').onclick=loadLog;if($('#expand-logs'))$('#expand-logs').onclick=()=>$$('#log details').forEach(x=>x.open=true);if($('#collapse-logs'))$('#collapse-logs').onclick=()=>$$('#log details').forEach(x=>x.open=false);let lastRunning=false,lastTerminalShownKey='',activeRunId='',activeExecutionMode='serial',dismissedRunIds=new Set();/* 実際に流れる順番と同じ並びにする。ここが実行順とずれていると、進捗が
   「ファイル生成・安定確認」から「抽出画面を閉じる」へ戻ったように見える。 */
const stepOrder=['prepare','launch','dde','ready','open','save','wait','close','export','publish','complete'];function showProgress(){let d=$('#progress-dialog');if(!d.open)d.showModal()}function hhmmss(v){v=Math.floor(Math.max(0,Number(v)||0));return [Math.floor(v/3600),Math.floor((v%3600)/60),v%60].map(x=>String(x).padStart(2,'0')).join(':')}
/* 終わった対象の結果をその場で出す。ログを開かないと件数も所要も分からない、という状態にしない。
   直列（DDE / API 1ライン）はライン表示が無いぶん、ここが唯一の途中経過になる。 */
function renderRunResults(list){
 let box=$('#p-results');if(!box)return;
 if(!list.length){box.hidden=true;box.innerHTML='';return}
 let ok=list.filter(x=>x.status!=='failed').length,ng=list.length-ok;
 box.hidden=false;
 box.innerHTML=`<div class="pres-head"><b>できあがったファイル ${ok}件</b>${ng?`<span class="pres-ng">失敗 ${ng}件</span>`:''}</div>`+
  list.map(x=>`<div class="pres-row ${x.status==='failed'?'is-error':'is-ok'}"><i>${x.status==='failed'?'×':'✓'}</i><b title="${E(x.job||'')}">${E(x.job||'')}</b><span>${E(x.detail||'')}</span>${x.target?`<small title="${E(x.target)}">${E(String(x.target).split(/[\\/]/).pop())}</small>`:''}</div>`).join('');
}
function laneColumns(n){return n<=4?n:n<=12?4:6}function applyProgressEngine(engine){let api=engine==='api';$$('#p-steps li[data-api]').forEach(li=>li.textContent=api?li.dataset.api:li.dataset.dde)}function updateProgress(s){if(activeRunId&&s.run_id!==activeRunId)return;let engine=s.extract_engine||cfg?.settings?.extract_engine||'api';applyProgressEngine(engine);let isParallel=(s.execution_mode==='parallel');$('#progress-dialog .progress-modal').classList.toggle('serial-mode',!isParallel);$('#progress-dialog .progress-modal').classList.toggle('parallel-mode',isParallel);let overall=s.total_jobs?Math.round(((Math.max(0,s.current_index-1)+(s.step_percent||0)/100)/s.total_jobs)*100):(s.step_percent||0);if(s.step==='complete'||s.step==='error')overall=100;$('#p-title').textContent=s.step_label||'処理中';$('#p-count').textContent=`全体 ${s.completed_jobs||0} / ${s.total_jobs||0}`;$('#p-percent').textContent=overall+'%';$('#p-bar').style.width=overall+'%';$('#p-job').textContent=s.current_job_name||'準備中';let j=cfg?.jobs?.find(x=>x.id===s.current_job_id),fmt=s.output_format||j?.output_format,file=s.output_file||j?.output_file,target=s.output_target||(j?`${j.output_folder||cfg.default_output_folder}\\${file}`:'');$('#p-output').textContent=fmt?`${formatName(fmt)} → ${target}`:'';let liveElapsed=s.started_at?Math.max(Number(s.elapsed_seconds)||0,Math.floor((Date.now()-new Date(s.started_at).getTime())/1000)):(s.elapsed_seconds||0);$('#p-elapsed').textContent='経過時間 '+hhmmss(liveElapsed);$('#p-activity span').textContent=[s.activity_detail,s.activity_value].filter(Boolean).join(' / ')||'処理を継続しています';$('#p-engine').textContent=(engine==='dde'?'DDE互換 / 1件ずつ直列':(s.execution_mode==='parallel'?`Navigator API 並列 ${s.requested_lines||1}ライン`:'Navigator API / 1件ずつ直列'))+' / '+(s.running?'処理中':'終了');let box=document.querySelector('#p-parallel-lines');if(!box){box=document.createElement('div');box.id='p-parallel-lines';box.className='parallel-lines fixed-lanes';document.querySelector('.current-box')?.after(box)}let pls=(s.parallel_lines||[]).slice().sort((a,b)=>Number(String(a.line).match(/\d+/)?.[0]||0)-Number(String(b.line).match(/\d+/)?.[0]||0));let total=Number(s.queue_total||0),waiting=Number(s.queue_waiting||0),active=Number(s.queue_active||0),completed=Number(s.queue_completed||0),lineCount=Number(s.parallel_max_lines||pls.length||0),parallel=(s.execution_mode==='parallel'&&s.run_id===activeRunId);if(lineCount)box.style.setProperty('--lane-cols',laneColumns(lineCount));let queue=$('#queue-summary');if(queue){queue.hidden=!parallel;
 /* 数値だけでは全体のどこまで進んだか掴みにくいため、実行キュー一覧の帯へデータバーを併記する。 */
 let qPct=total?Math.round(completed/total*100):0;
 queue.innerHTML=parallel?`<div><small>予約総数</small><strong>${total}</strong></div><div class="queue-arrow">→</div><div class="q-active"><small>実行中</small><strong>${active}</strong><span>${lineCount}ライン</span></div><div class="q-wait"><small>待機</small><strong>${waiting}</strong></div><div class="q-done"><small>完了</small><strong>${completed}</strong></div><div class="q-overall" title="完了 ${completed} / 実行中 ${active} / 待機 ${waiting} / 全体 ${total}"><small>実行キュー全体 ${completed} / ${total} 完了${active?`（実行中 ${active}）`:''}</small><b>${qPct}%</b><div class="q-overall-track"><i style="width:${qPct}%"></i></div></div>`:'';}document.querySelector('.current-box')?.classList.toggle('parallel-hidden',parallel);$('#p-steps')?.classList.toggle('parallel-hidden',parallel);box.hidden=!parallel;if(parallel){let byLine=new Map(pls.map(x=>[x.line,x]));let stable=[];for(let n=1;n<=lineCount;n++)stable.push(byLine.get(`ライン ${n}`)||{line:`ライン ${n}`,job:'',state:'待機',percent:0,detail:'次の予約を待機',elapsed:0});box.innerHTML=stable.map(x=>{let state=String(x.state||'待機'),cls=state.includes('完了')?'is-done':state.includes('失敗')?'is-error':state.includes('待機')?'is-wait':'is-running';return `<article class="pline ${cls}"><header><b>${E(x.line)}</b><span>${E(state)}</span></header><strong title="${E(x.job||'')}">${E(x.job||'予約待ち')}</strong><div class="lane-progress"><i style="width:${Math.max(0,Math.min(100,Number(x.percent||0)))}%"></i></div><footer><small>${E(x.detail||'')}</small><time>${hhmmss(x.elapsed||0)}</time></footer></article>`}).join('')}else box.innerHTML='';let current=stepOrder.indexOf(s.step);$$('#p-steps li').forEach(li=>{let i=stepOrder.indexOf(li.dataset.step);li.className=s.step==='error'&&i===Math.max(0,current)?'error':i<current?'done':i===current?'active':''});let failed=s.step==='error',cancelled=s.step==='cancelled',done=s.step==='complete'||cancelled;$('#p-state').textContent=failed?'失敗':cancelled?'中断済み':done?'完了':'実行中';$('#p-state').classList.toggle('running',!failed&&!done);$('#p-activity i').style.display=(failed||done)?'none':'block';$('#p-state').style.background=failed?'#fff0ee':cancelled?'#f3eee0':done?'#e5f5ef':'#e6f4f6';renderRunResults(s.job_results||[]);$('#p-error').hidden=!failed;if(failed){let errs=s.job_errors||[];$('#p-error').innerHTML=errs.length?`<div class="perr-head">失敗した対象 ${errs.length}件</div>`+errs.map(x=>`<div class="perr-item"><b>${E(x.job||'対象')}</b><span>${E(x.error||'')}</span></div>`).join('')+`<div class="perr-foot">詳しい経過は「ログ・診断」で確認できます。</div>`:E(s.error_detail||s.last_result||'処理を完了できませんでした')}else $('#p-error').textContent='';$('#p-background').hidden=failed||done;$('#p-close').hidden=!(failed||done);let terminalKey=(s.started_at||'')+'|'+s.step;if((failed||done)&&!dismissedRunIds.has(activeRunId)&&terminalKey!==lastTerminalShownKey){lastTerminalShownKey=terminalKey;showProgress()}}$('#p-background').onclick=()=>{dismissedRunIds.add(activeRunId);$('#progress-dialog').close();toast('上部の処理インジケータから進捗を再表示できます')};$('#p-close').onclick=()=>{dismissedRunIds.add(activeRunId);$('#progress-dialog').close();resetProgressView()};async function openProgressModal(){if(!lastRunning)return;try{let s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());if(s.run_id){activeRunId=s.run_id;activeExecutionMode=s.execution_mode||'serial';dismissedRunIds.delete(activeRunId);updateProgress(s);showProgress()}}catch{toast('進捗情報を取得できませんでした')}}$('.runtime').onclick=openProgressModal;async function poll(){try{let s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());statusFailCount=0;hideServerLost();latestStatus=s;lastRunning=s.running;if(s.running&&s.run_id&&!activeRunId){activeRunId=s.run_id;activeExecutionMode=s.execution_mode||'serial';dismissedRunIds.add(activeRunId)}$('#st').textContent=s.running?'処理中':s.step==='error'?'処理失敗':s.step==='cancelled'?'中断済み':'待機中';$('#sub').textContent=s.running?s.step_label:(s.last_finished_at||'実行待ち');$('#dot').style.background=s.running?'#f0b429':s.step==='error'?'#e45b50':s.step==='cancelled'?'#8a94a0':'#3ed1a0';$('.runtime').classList.toggle('processing',s.running);$('#run-all').disabled=false;updateSelCount();loadCommandQueue();applyRowLiveProgress(s);if(activeRunId&&s.run_id===activeRunId&&(s.running||s.step==='complete'||s.step==='error'||s.step==='cancelled'))updateProgress(s)}catch{$('#st').textContent='接続エラー';statusFailCount++;if(statusFailCount>=3)showServerLost()}}

/* ==== SymNaviA.dll の探索 ==================================================
   別のPCで環境を作るとき、いちばん詰まるのがこのDLL。必要な条件（bit数）、探す範囲、
   見つからないときの手動指定を、この順番で1か所にまとめる。 */
const DLL_DEFAULT_ROOTS=['C:\\NAVIAP','.\\Config\\NAVIAP','.\\NAVIAP'];
function dllRoots(){let v=cfg&&cfg.navigator_api_search_roots;return Array.isArray(v)?v:[]}
function setDllRoots(list){if(cfg)cfg.navigator_api_search_roots=list;renderDllRoots()}
/* ==== Navigator API が使えるか ==============================================
   これまでは「必要なDLL」「探す範囲」「手動で指定」「DLL診断」の4か所が、
   それぞれ別の言い方で状態を出していた。同じ画面に「そろっています」と
   「不足しています」が並び、どちらが本当なのか読み取れなかった。
   判定はサーバーの api_readiness ひとつが行い、ここはその結果を出すだけ。 */
const AR_MARK={ok:['OK','is-ok'],ng:['要対応','is-ng'],warn:['注意','is-warn'],unknown:['未確認','is-unknown']};
function renderApiReadiness(r,note){
 let box=$('#api-readiness');if(!box)return;
 if(!r){box.className='api-readiness';box.textContent='確認中';return}
 box.className='api-readiness '+(r.ok?'is-ok':'is-ng');
 let items=r.items||[];
 box.innerHTML=`<div class="ar-verdict"><i>${r.ok?'使えます':'使えません'}</i>`
  +`<div><b>${E(r.headline||'')}</b><span>${E(r.detail||'')}</span></div>`
  +`<em>${r.ready}/${r.total} 項目</em></div>`
  +`<div class="ar-items">${items.map(x=>{
     let [word,tone]=AR_MARK[x.state]||AR_MARK.unknown;
     return `<div class="ar-item ${tone}"><i>${word}</i><div><b>${E(x.label)}</b>`
      +`<span>${E(x.have||'—')}</span><small>要件: ${E(x.need||'')}</small>`
      +(x.fix?`<small class="ar-fixnote">対処: ${E(x.fix)}</small>`:'')+`</div></div>`}).join('')}</div>`
  +(note?`<p class="ri-note">${E(note)}</p>`:'');
 // 足りないときだけ、直し方を開いておく。そろっているのに開くと、何が問題なのか紛れる。
 let fix=$('#api-fix');if(fix)fix.open=!r.ok;
 let det=$('#api-detail');if(det&&r.ok)det.open=false;
}
function renderDllRequirement(req,extra){
 let box=$('#dll-requirement');if(!box)return;
 if(!req||!req.required_bits){box.textContent='必要なDLLの条件を取得できませんでした。';return}
 let miss=req.runtime_missing||[],folders=(req.folders||[]);
 box.innerHTML=`<div class="dll-req-main"><b>${req.required_bits}bit版 ${E(req.file_name)}</b><span>${E(req.reason||'')}</span></div>`+
  `<div class="dll-req-grid">`+
  `<div><small>そのまま使えるフォルダー</small><b>${E((req.preferred_folders||[]).join(' / ')||'—')}</b></div>`+
  `<div><small>bit数が合わないフォルダー</small><b class="dim">${E((req.rejected_folders||[]).join(' / ')||'—')}</b></div>`+
  `<div><small>Visual C++ ランタイム（${req.required_bits}bit）</small><b class="${miss.length?'ng':'ok'}">${miss.length?'不足: '+E(miss.join(', ')):'揃っています'}</b></div>`+
  `<div><small>いま探している範囲</small><b>${E((req.search_roots||[]).join('  /  ')||'—')}</b></div>`+
  `</div>`+
  (folders.length?`<div class="dll-req-folders">${folders.map(f=>`<span class="${f.bits===req.required_bits?'fits':'unfits'}" title="${E(f.vc||'')}">${E(f.folder)}<em>${E(f.label)}</em></span>`).join('')}</div>`:'')+
  (extra?`<p class="hint">${E(extra)}</p>`:'');
}
async function loadDllRequirement(){
 try{let d=await fetch('/api/navigator-api/requirement',{cache:'no-store'}).then(r=>r.json());
  renderDllRequirement(d.requirement);
  if($('#dll-depth')&&d.depth)$('#dll-depth').value=String(d.depth);
  if(cfg&&!Array.isArray(cfg.navigator_api_search_roots))cfg.navigator_api_search_roots=DLL_DEFAULT_ROOTS.slice();
  renderDllRoots();
 }catch{}
}
function renderDllRoots(){
 let box=$('#dll-roots');if(!box)return;
 let roots=dllRoots();
 box.innerHTML=roots.length?roots.map((r,i)=>`<div class="dll-root"><span class="dll-root-no">${i+1}</span><input class="dll-root-input" data-i="${i}" value="${E(r)}" placeholder="例: C:\\NAVIAP"><div class="dll-root-btns"><button type="button" class="secondary dll-root-up" data-i="${i}"${i?'':' disabled'}>上へ</button><button type="button" class="secondary dll-root-pick" data-i="${i}">参照</button><button type="button" class="secondary danger-lite dll-root-del" data-i="${i}">削除</button></div></div>`).join(''):'<div class="dll-root-empty">検索するフォルダーがありません。「フォルダーを追加」で指定してください。</div>';
 $$('.dll-root-input').forEach(x=>x.onchange=()=>{let l=dllRoots().slice();l[Number(x.dataset.i)]=x.value.trim();setDllRoots(l);saveDllRoots()});
 $$('.dll-root-up').forEach(b=>b.onclick=()=>{let i=Number(b.dataset.i),l=dllRoots().slice();if(i<1)return;[l[i-1],l[i]]=[l[i],l[i-1]];setDllRoots(l);saveDllRoots('探す順番を変更しました')});
 $$('.dll-root-del').forEach(b=>b.onclick=()=>{let l=dllRoots().slice();l.splice(Number(b.dataset.i),1);setDllRoots(l);saveDllRoots('検索するフォルダーを削除しました')});
 $$('.dll-root-pick').forEach(b=>b.onclick=async()=>{let q=await browse('folder',dllRoots()[Number(b.dataset.i)]||'');if(!q)return;let l=dllRoots().slice();l[Number(b.dataset.i)]=q;setDllRoots(l);saveDllRoots('検索するフォルダーを変更しました')});
}
async function saveDllRoots(msg){
 try{
  let r=await fetch('/api/navigator-api/search-roots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({roots:dllRoots().filter(Boolean),depth:Number($('#dll-depth')?.value||3)})});
  let d=await r.json();
  if(r.ok){if(cfg)cfg.navigator_api_search_roots=d.roots;renderDllRoots();if(msg)toast(msg);await loadDllRequirement()}
  else toast(d.error||'検索範囲を保存できませんでした');
 }catch{toast('検索範囲を保存できませんでした')}
}
function dllFoundHtml(d){
 let found=d.found||[],scanned=d.roots||[];
 let head=`<div class="dll-found-head"><b>見つかったDLL ${found.length}件</b><span>そのまま使える ${(d.usable||[]).length}件 / 探した深さ ${d.max_depth}階層 / ${Number(d.elapsed||0).toFixed(1)}秒</span></div>`;
 let roots=`<div class="dll-scan-roots">${scanned.map(x=>`<span class="${x.exists?(x.files?'hit':'none'):'missing'}">${E(x.root)}<em>${x.error?E(x.error):x.exists?(x.files?x.files+'件':'0件'):'フォルダーがありません'}</em></span>`).join('')}</div>`;
 if(!found.length)return head+roots+'<p class="dll-found-empty">この範囲にSymNaviA.dllはありませんでした。フォルダーを追加するか、深さを増やして再検索してください。見つからない場合は下の「手動で指定」からファイルを直接選べます。</p>';
 return head+roots+found.map(x=>`<div class="dll-hit ${x.usable?'is-ok':'is-ng'}"><i>${x.usable?'使える':'使えない'}</i><div class="dll-hit-main"><code title="${E(x.path)}">${E(x.path)}</code><span>${E(x.reason)}</span><small>${E(x.label||x.folder||'')}${x.siblings>0?` / 同じフォルダーに依存DLL ${x.siblings}件`:' / 同じフォルダーに依存DLLなし'}${x.modified?' / '+E(x.modified):''}</small></div>${x.usable?`<button type="button" class="dll-use" data-path="${E(x.path)}">これを使う</button>`:''}</div>`).join('');
}
async function scanDlls(){
 let box=$('#dll-found'),btn=$('#dll-scan');if(!box)return;
 btn.disabled=true;showWaiting('DLLを検索中','指定された範囲を実際に開いて SymNaviA.dll を探しています...','api');
 try{
  let r=await fetch('/api/navigator-api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({roots:dllRoots().filter(Boolean),depth:Number($('#dll-depth')?.value||3)})}),d=await r.json();
  if(!d.ok){box.hidden=false;box.innerHTML=`<p class="dll-found-empty">検索できませんでした: ${E(d.error||'')}</p>`;return}
  renderDllRequirement(d.requirement);
  box.hidden=false;box.innerHTML=dllFoundHtml(d);
  $$('.dll-use').forEach(b=>b.onclick=()=>useDllPath(b.dataset.path));
  toast(`${(d.found||[]).length}件のDLLが見つかりました（使える ${(d.usable||[]).length}件）`);
 }finally{hideWaiting();btn.disabled=false}
}
async function useDllPath(path){
 let r=await fetch('/api/navigator-api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}),d=await r.json();
 let state=$('#dll-manual-state');
 if(!d.ok){if(state){state.hidden=false;state.className='dll-manual-state ng';state.textContent=d.error||'指定できませんでした'}return toast(d.error||'指定できませんでした')}
 if(cfg)cfg.navigator_api_dll=d.path;
 let inp=$('#navigator-api-dll');if(inp)inp.value=d.path;
 if(state){state.hidden=false;state.className='dll-manual-state '+(d.match?'ok':'ng');
  state.textContent=d.match?`使用するDLLに設定しました（${d.dll_bits}bit / Python ${d.python_bits}bit・一致）: ${d.path}`:d.warning}
 toast(d.match?'このDLLを使用する設定にしました':'指定しましたが、bit数が一致していません');
 await testNavigatorApi();
}
if($('#dll-scan'))$('#dll-scan').onclick=scanDlls;
if($('#dll-root-add'))$('#dll-root-add').onclick=async()=>{let q=await browse('folder','');if(!q)return;setDllRoots(dllRoots().concat([q]));await saveDllRoots('検索するフォルダーを追加しました')};
if($('#dll-root-reset'))$('#dll-root-reset').onclick=async()=>{setDllRoots(DLL_DEFAULT_ROOTS.slice());await saveDllRoots('検索するフォルダーを標準へ戻しました')};
if($('#dll-depth'))$('#dll-depth').onchange=()=>saveDllRoots();
async function testNavigatorApi(){
 let b=$('#api-test'),box=$('#api-attempts'),inp=$('#navigator-api-dll');
 if(inp&&cfg){cfg.navigator_api_dll=inp.value.trim();let payload=structuredClone(cfg);delete payload.credential_status;
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
 if(b)b.disabled=true;
 renderApiReadiness(null);
 showWaiting('Navigator APIを確認中','探す範囲の候補・bit数・依存ランタイムを順に確かめています...','api');
 try{
  let d=await fetch('/api/navigator-api-status?full=1',{cache:'no-store'}).then(r=>r.json());
  renderDllRequirement(d.requirement);
  renderApiReadiness(d.readiness,d.cached?'前回の確認結果です。':'');
  let attempts=d.attempts||[];
  if(box){
   let visible=attempts.filter(x=>x.exists||x.error),
       problem=x=>x.result==='loaded'?'これを使用しています':x.result==='bit_mismatch'?`bit数が合いません（DLL ${x.dll_bits}bit / Python ${x.python_bits}bit）`
         :x.error?'読み込めません（依存DLLまたはランタイムを確認）':'ファイルはあります';
   box.innerHTML=`<div class="api-attempt-head"><b>候補ごとの確認結果</b><span>探した ${attempts.length}件 / 実在 ${attempts.filter(x=>x.exists).length}件</span></div>`
    +(visible.length?visible.map(x=>`<div class="api-attempt ${x.result==='loaded'?'chosen':'found'}">`
      +`<i>${x.result==='loaded'?'使用':'候補'}</i><code title="${E(x.path)}">${E(x.path)}</code>`
      +`<span>${E(problem(x))}</span></div>`).join(''):'<p>実在する候補はありません。</p>');
  }
 }finally{hideWaiting();if(b)b.disabled=false}
}
$('#api-test').onclick=testNavigatorApi;$('#extract-engine').onchange=()=>{updateEngineUI();dirty()};$$('.engine-card').forEach(c=>c.onclick=()=>setExtractEngine(c.dataset.engine));setInterval(poll,1000);init().then(async()=>{poll();loadCommandQueue();try{
 let d=await fetch('/api/navigator-api-status',{cache:'no-store'}).then(r=>r.json());
 renderDllRequirement(d.requirement);
 renderApiReadiness(d.readiness,d.cached?'前回の確認結果です。「いま確認する」で取り直せます。':'');
}catch{renderApiReadiness(null)}})

$('#suggest-close').onclick=()=>$('#path-suggestion').close();
async function waitUntilNotRunning(timeoutMs){let start=Date.now();while(Date.now()-start<timeoutMs){try{let s=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());if(!s.running)return true}catch{return false}await new Promise(r=>setTimeout(r,500))}return false}
$('#app-exit').onclick=async()=>{if(lastRunning){if(!confirm('スケジュール実行が進行中です。中断してアプリを終了しますか？\n実行中の1件は安全な区切りまで進めてから停止し、以降の予約は開始しません。'))return;toast('実行を中断しています…');try{await fetch('/api/run/cancel',{method:'POST'})}catch{}await waitUntilNotRunning(20000)}else if(!confirm('SymfoNavi Data Hubを終了しますか？\n自動実行の予定が残っていても、この操作でアプリを完全に終了します。')){return}try{await fetch('/api/shutdown-app',{method:'POST'});document.body.innerHTML='<main style="max-width:680px;margin:80px auto;padding:24px"><article class="panel"><h2>アプリを終了しました</h2><p>このブラウザータブを閉じてください。</p></article></main>'}catch{window.close()}};

function resetEditorState(){editing=null;editingRule=null;$('#editor form')?.reset();$('#rule-editor form')?.reset();if($('#m-rules'))$('#m-rules').innerHTML='';if($('#r-detail'))$('#r-detail').innerHTML=''}$('#editor').addEventListener('close',resetEditorState);$('#rule-editor').addEventListener('close',()=>{editingRule=null;$('#rule-editor form')?.reset();if($('#r-detail'))$('#r-detail').innerHTML=''});$('#path-suggestion').addEventListener('close',()=>{$('#suggest-content').innerHTML=''});window.addEventListener('pageshow',()=>{$$('dialog').forEach(d=>{if(d.open)d.close()});resetEditorState()});

if($('#api-lines'))$('#api-lines').addEventListener('change',async e=>{let v=Math.max(1,Math.min(24,Number(e.target.value)||6));e.target.value=v;cfg.settings.api_parallel_lines=v;cfg.settings.stability_profile='balanced_api_parallel';try{let r=await fetch('/api/settings/parallel-lines',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:v})});if(r.ok)toast(`並列ライン数を${v}ラインで保存しました（次回以降も保持）`);else{dirty();toast(`次回実行は${v}ラインです（保存に失敗したため自動で再試行します）`)}}catch{dirty();toast(`次回実行は${v}ラインです（保存に失敗したため自動で再試行します）`)}});function updateBackupOptions(){let on=$('#backup-enabled')?.checked!==false,mode=$('#backup-mode')?.value||'generations',gens=Math.max(1,Number($('#gens')?.value)||3),days=Math.max(1,Number($('#backup-retention-days')?.value)||30);$('#backup-options')?.classList.toggle('is-disabled',!on);let useG=mode==='generations'||mode==='both',useD=mode==='days'||mode==='both';$('#backup-generation-field')?.classList.toggle('is-disabled',!useG);$('#backup-days-field')?.classList.toggle('is-disabled',!useD);let labels={generations:`世代方式 / ${gens}世代`,days:`日数方式 / ${days}日`,both:`複合方式 / ${gens}世代・${days}日`};let b=$('#backup-policy-badge');if(b)b.textContent=on?labels[mode]:'バックアップ無効'}if($('#backup-enabled'))$('#backup-enabled').addEventListener('change',()=>{updateBackupOptions();dirty()});if($('#backup-mode'))$('#backup-mode').addEventListener('change',()=>{updateBackupOptions();dirty()});if($('#backup-retention-days'))$('#backup-retention-days').addEventListener('input',e=>{e.target.value=Math.max(1,Math.min(3650,Number(e.target.value)||1));updateBackupOptions();dirty()});if($('#gens'))$('#gens').addEventListener('input',e=>{e.target.value=Math.max(1,Math.min(9999,Number(e.target.value)||1));updateBackupOptions();dirty()});if($('#backup-reset-default'))$('#backup-reset-default').onclick=()=>{$('#backup-enabled').checked=true;$('#backup-mode').value='generations';$('#gens').value=3;$('#backup-retention-days').value=30;updateBackupOptions();dirty()};$('#hide-profile').addEventListener('change',()=>{updateHideProfileUI();dirty()});$('#hide-interval').addEventListener('change',e=>{e.target.value=Math.max(1,Number(e.target.value)||1);dirty()});$('#hide-action-duration').addEventListener('change',dirty);


/* V29: vertical progress and structured log workspace */
function logKind(line){if(line.includes('[ERROR]')||line.includes('異常終了')||line.includes('FAILED')||line.includes('失敗'))return'error';if(line.includes('設定保存'))return'setting';if(line.includes('COMMAND_QUEUE'))return'queue';if(/PUBLISH_|phase=publish/.test(line))return'publish';if(/STARTUP_PHASE|STEP_END|elapsed=|SQLITE_|INTERMEDIATE_VALIDATION|PARALLEL_BATCH_END|JOB_RESULT|JOB_PROFILE|RUN_ENVIRONMENT|WORKER_READY/.test(line))return'performance';return'execution'}
function logKindLabel(k){return{execution:'実行',setting:'設定',queue:'キュー',performance:'計測',publish:'公開',error:'エラー'}[k]||'実行'}
function logMatches(line){let q=($('#log-filter-text')?.value||'').trim().toLowerCase(),k=$('#log-filter-kind')?.value||'all',lv=$('#log-filter-level')?.value||'all';return(!q||line.toLowerCase().includes(q))&&(k==='all'||logKind(line)===k)&&(lv==='all'||logLevel(line)===lv)}
function logLines(lines){return`<div class="log-lines">${lines.map(x=>{let k=logKind(x);return`<div class="log-line ${logLevel(x)} kind-${k}${x.includes('LOG_DEDUP')?' dedup':''}${logMatches(x)?'':' hidden-by-filter'}" data-line="${E(x)}"><input class="log-select" type="checkbox" aria-label="このログ行を選択"><span class="log-kind">${logKindLabel(k)}</span><span class="log-text">${E(x)}</span></div>`}).join('')}</div>`}
function filteredLogLines(){return $$('#log .log-line:not(.hidden-by-filter)').map(x=>x.dataset.line||'').filter(Boolean)}
function selectedLogLines(){return $$('#log .log-select:checked').map(x=>x.closest('.log-line')?.dataset.line||'').filter(Boolean)}
function updateLogSummary(){let a=$$('#log .log-line').length,v=$$('#log .log-line:not(.hidden-by-filter)').length,s=$$('#log .log-select:checked').length,g=$$('#log .log-group-select:checked').length;if($('#log-filter-summary'))$('#log-filter-summary').textContent=`表示 ${v}行 / 全体 ${a}行 / 選択 ${s}行`+(g?` / 実行指令 ${g}件`:'')}
function applyLogFilter(){ $$('#log .log-line').forEach(x=>x.classList.toggle('hidden-by-filter',!logMatches(x.dataset.line||'')));$$('#log .log-job,#log .log-action').forEach(x=>x.style.display=x.querySelector('.log-line:not(.hidden-by-filter)')?'':'none');updateLogSummary() }
function renderLogTree(text){let groups=buildLogTree(text);renderedLogGroups=groups.slice().reverse();$('#log').innerHTML=renderedLogGroups.length?renderedLogGroups.map((g,gi)=>`<details class="log-action" ${gi===0?'open':''} data-gi="${gi}"><summary><input class="log-group-select" type="checkbox" data-gi="${gi}" aria-label="この実行指令を選択"><span><b>実行指令 ${renderedLogGroups.length-gi}</b> ${E(g.title)}</span><small>${g.jobs.length}ファイル</small><span class="log-summary-actions"><button class="secondary log-copy-full" data-gi="${gi}">全文コピー</button><button class="secondary log-copy-summary" data-gi="${gi}">要約コピー</button><button class="secondary danger-lite log-delete-group" data-gi="${gi}">削除</button></span></summary>${g.lines.length?logLines(g.lines):''}${g.jobs.map(x=>`<details class="log-job"><summary>${E(x.name)} <small>${x.lines.length}行</small></summary>${logLines(x.lines)}</details>`).join('')}</details>`).join(''):'<div class="empty">ログなし</div>';$$('.log-copy-full').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();textToClipboard(groupText(renderedLogGroups[Number(b.dataset.gi)],'full'),'実行指令ログをコピーしました')});$$('.log-copy-summary').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();textToClipboard(groupText(renderedLogGroups[Number(b.dataset.gi)],'summary'),'要約ログをコピーしました')});$$('.log-delete-group').forEach(b=>b.onclick=async e=>{e.preventDefault();e.stopPropagation();let lines=groupText(renderedLogGroups[Number(b.dataset.gi)],'full').split(/\n/);if(confirm('この実行指令ログを削除しますか？'))await deleteLogRows(lines,'実行指令ログを削除しました')});$$('.log-select').forEach(x=>x.onchange=updateLogSummary);$$('.log-group-select').forEach(x=>{x.onclick=e=>e.stopPropagation();x.onchange=e=>{e.stopPropagation();x.closest('.log-action')?.classList.toggle('is-picked',x.checked);updateLogSummary()}});applyLogFilter()}
/* 実行指令のまとまりごとに選ぶ。1行ずつ拾わなくても、まとめて消せるようにする。 */
function selectedLogGroups(){return $$('#log .log-group-select:checked').map(x=>renderedLogGroups[Number(x.dataset.gi)]).filter(Boolean)}
function selectedGroupLines(){let seen=new Set();selectedLogGroups().forEach(g=>groupText(g,'full').split(/\n/).forEach(l=>{if(l.trim())seen.add(l)}));return [...seen]}
async function deleteLogRows(lines,message){if(!lines.length)return toast('対象ログがありません');let r=await fetch('/api/log/delete-lines',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines})});if(r.ok){toast(message);await loadLog()}else toast('ログを削除できませんでした')}
function bindV29LogWorkspace(){['log-filter-text','log-filter-kind','log-filter-level'].forEach(id=>{let x=$('#'+id);if(x)x.addEventListener(id==='log-filter-text'?'input':'change',applyLogFilter)});if($('#select-filtered-log'))$('#select-filtered-log').onclick=()=>{$$('#log .log-line:not(.hidden-by-filter) .log-select').forEach(x=>x.checked=true);updateLogSummary()};if($('#clear-log-selection'))$('#clear-log-selection').onclick=()=>{$$('#log .log-select,#log .log-group-select').forEach(x=>x.checked=false);$$('#log .log-action').forEach(x=>x.classList.remove('is-picked'));updateLogSummary()};if($('#select-all-groups'))$('#select-all-groups').onclick=()=>{let box=$$('#log .log-group-select'),on=box.some(x=>!x.checked);box.forEach(x=>{x.checked=on;x.closest('.log-action')?.classList.toggle('is-picked',on)});updateLogSummary()};if($('#copy-selected-groups'))$('#copy-selected-groups').onclick=()=>{let g=selectedLogGroups();if(!g.length)return toast('実行指令が選ばれていません');textToClipboard(g.map(x=>groupText(x,'full')).join('\n\n'),`${g.length}件の実行指令ログをコピーしました`)};if($('#delete-selected-groups'))$('#delete-selected-groups').onclick=()=>{let g=selectedLogGroups();if(!g.length)return toast('実行指令が選ばれていません');let x=selectedGroupLines();if(confirm(`選択した${g.length}件の実行指令（${x.length}行）を削除しますか？`))deleteLogRows(x,`${g.length}件の実行指令ログを削除しました`)};if($('#copy-filtered-log'))$('#copy-filtered-log').onclick=()=>textToClipboard(filteredLogLines().join('\n'),'表示中のログをコピーしました');if($('#delete-selected-log'))$('#delete-selected-log').onclick=()=>{let x=selectedLogLines();if(x.length&&confirm(`選択した${x.length}行を削除しますか？`))deleteLogRows(x,'選択ログを削除しました')};if($('#delete-filtered-log'))$('#delete-filtered-log').onclick=()=>{let x=filteredLogLines();if(x.length&&confirm(`表示中の${x.length}行を削除しますか？`))deleteLogRows(x,'表示中のログを削除しました')};if($('#delete-old-log'))$('#delete-old-log').onclick=async()=>{let days=Number($('#log-retention-days')?.value||30);if(!confirm(`${days}日以前のログを一括削除しますか？`))return;let r=await fetch('/api/log/delete-old',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days})}),d=await r.json();if(r.ok){toast(`${d.removed}行の古いログを削除しました`);await loadLog()}else toast(d.error||'古いログを削除できませんでした')}}
bindV29LogWorkspace();

/* V30: categorized settings navigation and in-app version management */
function bindSettingsNav(){$$('#settings-nav .settings-navbtn').forEach(b=>b.onclick=()=>{$$('#settings-nav .settings-navbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');$$('.settings-pane').forEach(x=>x.classList.remove('on'));document.querySelector(`.settings-pane[data-cat="${b.dataset.cat}"]`)?.classList.add('on');if(b.dataset.cat==='docs')loadDocs()})}
/* ============================================================
   仕様書ビュー。同梱のMarkdownをアプリの中で読む。
   外部ライブラリは使えないので、この文書に実際に出てくる記法だけを自前で描く
   （見出し・表・囲みコード・箇条書き・引用・水平線・強調・インラインコード）。
   先にすべてエスケープしてから組み立てるので、文書側のHTMLは実行されない。
   ============================================================ */
const MD_TAG={'原本':'orig','整理':'plan','要確認':'check'};
function mdInline(t){
 t=E(t);
 t=t.replace(/`([^`]+)`/g,(m,c)=>`<code>${c}</code>`);
 t=t.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');
 // [原本] [整理] [要確認] は読み分けの要なので、地の文と混ぜずに印にする
 t=t.replace(/\[(原本|整理|要確認)([^\]]*)\]/g,(m,k,rest)=>`<span class="md-tag t-${MD_TAG[k]}">${k}${rest}</span>`);
 return t;
}
function mdRender(src){
 let lines=String(src||'').replace(/\r\n?/g,'\n').split('\n'),out=[],toc=[],i=0,hid=0;
 const flushList=(items,ordered)=>`<${ordered?'ol':'ul'}>${items.join('')}</${ordered?'ol':'ul'}>`;
 while(i<lines.length){
  let ln=lines[i];
  // 囲みコード
  let fence=ln.match(/^```(\w*)\s*$/);
  if(fence){
   let body=[];i++;
   while(i<lines.length&&!/^```/.test(lines[i])){body.push(lines[i]);i++}
   i++;
   out.push(`<pre class="md-code"${fence[1]?` data-lang="${E(fence[1])}"`:''}><code>${E(body.join('\n'))}</code></pre>`);
   continue;
  }
  // 表（次の行が区切りなら表とみなす）
  if(/^\s*\|/.test(ln)&&i+1<lines.length&&/^\s*\|[\s:|-]+\|\s*$/.test(lines[i+1])){
   const cells=r=>r.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
   let head=cells(ln),rows=[];i+=2;
   while(i<lines.length&&/^\s*\|/.test(lines[i])){rows.push(cells(lines[i]));i++}
   out.push(`<div class="md-tablebox"><table class="md-table"><thead><tr>`
    +head.map(c=>`<th>${mdInline(c)}</th>`).join('')+`</tr></thead><tbody>`
    +rows.map(r=>`<tr>`+r.map(c=>`<td>${mdInline(c)}</td>`).join('')+`</tr>`).join('')
    +`</tbody></table></div>`);
   continue;
  }
  // 見出し
  let h=ln.match(/^(#{1,6})\s+(.*)$/);
  if(h){
   let lv=h[1].length,id='md-h'+(++hid),txt=h[2].replace(/\s*#+\s*$/,'');
   if(lv<=3)toc.push({id,level:lv,text:txt.replace(/`/g,'')});
   out.push(`<h${Math.min(lv+1,5)} id="${id}" class="md-h md-h${lv}">${mdInline(txt)}</h${Math.min(lv+1,5)}>`);
   i++;continue;
  }
  // 水平線
  if(/^\s*(---+|\*\*\*+)\s*$/.test(ln)){out.push('<hr class="md-hr">');i++;continue}
  // 引用
  if(/^\s*>\s?/.test(ln)){
   let body=[];
   while(i<lines.length&&/^\s*>\s?/.test(lines[i])){body.push(lines[i].replace(/^\s*>\s?/,''));i++}
   out.push(`<blockquote class="md-quote">${body.map(x=>mdInline(x)).join('<br>')}</blockquote>`);
   continue;
  }
  // 箇条書き（2スペースごとの入れ子まで）
  if(/^\s*([-*+]|\d+\.)\s+/.test(ln)){
   let ordered=/^\s*\d+\./.test(ln),stack=[[]],depth=[0];
   while(i<lines.length&&/^\s*([-*+]|\d+\.)\s+/.test(lines[i])){
    let m=lines[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/),ind=Math.floor(m[1].length/2),txt=m[3];
    // チェックリストは印を先に外し、本文を組み立ててから戻す（先に混ぜるとエスケープされる）
    let box=txt.match(/^\[([ xX])\]\s*/);
    if(box)txt=txt.slice(box[0].length);
    while(ind>depth[depth.length-1]){stack.push([]);depth.push(ind)}
    while(ind<depth[depth.length-1]){let done=stack.pop();depth.pop();
     let up=stack[stack.length-1];up[up.length-1]=up[up.length-1].replace(/<\/li>$/,flushList(done,false)+'</li>')}
    stack[stack.length-1].push(`<li${box?' class="md-task"':''}>`
     +(box?`<i class="md-check${/[xX]/.test(box[1])?' on':''}"></i>`:'')+mdInline(txt)+`</li>`);
    i++;
   }
   while(stack.length>1){let done=stack.pop();let up=stack[stack.length-1];
    up[up.length-1]=up[up.length-1].replace(/<\/li>$/,flushList(done,false)+'</li>')}
   out.push(flushList(stack[0],ordered));
   continue;
  }
  // 段落（空行まで）
  if(!ln.trim()){i++;continue}
  let para=[];
  while(i<lines.length&&lines[i].trim()&&!/^(#{1,6}\s|```|\s*\||\s*>|\s*([-*+]|\d+\.)\s|\s*---+\s*$)/.test(lines[i])){para.push(lines[i]);i++}
  if(para.length)out.push(`<p>${para.map(mdInline).join('<br>')}</p>`);
  else{out.push(`<p>${mdInline(ln)}</p>`);i++}
 }
 return {html:out.join(''),toc};
}
let docsLoaded=false,docCurrent='';
async function loadDocs(force){
 let box=$('#doc-list');if(!box)return;
 if(docsLoaded&&!force)return;
 try{
  let d=await fetch('/api/docs').then(r=>r.json());
  docsLoaded=true;
  box.innerHTML=(d.docs||[]).map(x=>`<button type="button" class="doc-item" data-doc="${E(x.id)}"${x.available?'':' disabled'}>`
   +`<b>${E(x.title)}</b><small>${E(x.summary)}</small>`
   +`<em>${x.available?`${Math.round(x.bytes/1024).toLocaleString()} KB · ${E(x.updated_at)}`:'配布物に見つかりません'}</em></button>`).join('')
   ||'<p class="hint">登録されている仕様書がありません。</p>';
  box.querySelectorAll('.doc-item').forEach(b=>b.onclick=()=>openDoc(b.dataset.doc));
  let first=box.querySelector('.doc-item:not([disabled])');
  if(first&&!docCurrent)openDoc(first.dataset.doc);
 }catch{box.innerHTML='<p class="hint">仕様書の一覧を取得できませんでした。</p>'}
}
async function openDoc(id){
 let head=$('#doc-head'),body=$('#doc-body'),toc=$('#doc-toc');if(!body)return;
 docCurrent=id;
 $$('#doc-list .doc-item').forEach(b=>b.classList.toggle('on',b.dataset.doc===id));
 body.innerHTML='<p class="hint">読み込み中...</p>';
 try{
  let d=await fetch('/api/docs/'+encodeURIComponent(id)).then(r=>r.json());
  if(!d.ok){head.innerHTML='';body.innerHTML=`<p class="ri-ng">${E(d.error||'読み込めませんでした')}</p>`;
   toc.innerHTML='';$('.doc-toc-label').hidden=true;return}
  let m=mdRender(d.text);
  head.innerHTML=`<h3>${E(d.title)}</h3><p class="doc-source">${E(d.source)}</p><p class="doc-path">${E(d.path)}</p>`;
  body.innerHTML=m.html;
  toc.innerHTML=m.toc.map(t=>`<a href="#${t.id}" class="doc-tocitem lv${t.level}" data-to="${t.id}">${E(t.text)}</a>`).join('');
  $('.doc-toc-label').hidden=!m.toc.length;
  toc.querySelectorAll('.doc-tocitem').forEach(a=>a.onclick=e=>{e.preventDefault();
   document.getElementById(a.dataset.to)?.scrollIntoView({block:'start',behavior:'smooth'})});
  body.scrollTop=0;
 }catch{body.innerHTML='<p class="ri-ng">読み込み中にエラーが発生しました。</p>'}
}

/* 更新履歴は【見出し】と空行で区切って書いてある。そこを本文と同じ点の列で出すと、
   どこが1つの話題なのか読み取れない。見出し・箇条書き・版の3層に分けて組み直す。 */
function changelogSections(notes){let secs=[],cur=null;(notes||[]).forEach(n=>{let t=String(n||'').trim();if(!t){cur=null;return}let m=t.match(/^【([^】]+)】([\s\S]*)$/);if(m){cur={head:m[1],items:[]};secs.push(cur);if(m[2].trim())cur.items.push(m[2].trim());return}if(!cur){cur={head:'',items:[]};secs.push(cur)}cur.items.push(t)});return secs}
function renderChangelog(list){let items=list||[];return items.map((e,i)=>{let secs=changelogSections(e.notes),n=secs.reduce((a,b)=>a+b.items.length,0),body=secs.map(sc=>`<div class="cl-sec">${sc.head?`<h4>${E(sc.head)}</h4>`:''}<ul>${sc.items.map(x=>`<li>${E(x)}</li>`).join('')}</ul></div>`).join('');return `<details class="cl-entry${i===0?' is-latest':''}"${i===0?' open':''}><summary><b class="cl-ver">${E(e.version)}</b>${i===0?'<i class="cl-flag">最新</i>':''}<span class="cl-title">${E(e.title)}</span><span class="cl-meta">${e.date?`<time>${E(e.date)}</time>`:''}<em>${n}件</em></span></summary><div class="cl-body">${body}</div></details>`}).join('')}
async function loadVersion(){try{let d=await fetch('/api/version').then(r=>r.json()),log=d.changelog||[],meta=`ビルド: ${d.build_version}`+(d.released_at?` / リリース日: ${d.released_at}`:'');if($('#version-badge'))$('#version-badge').textContent='ver '+d.version;if($('#version-current'))$('#version-current').textContent=`${d.version} ${d.title}`;if($('#version-meta'))$('#version-meta').innerHTML=`<span class="vchip"><i>リリース日</i><b>${E(d.released_at||'—')}</b></span>`+`<span class="vchip"><i>ビルド</i><b>${E(d.build_version||'—')}</b></span>`+`<span class="vchip"><i>画面</i><b>${E(UI_BUILD)}</b></span>`;if($('#version-count'))$('#version-count').textContent=`全${log.length}版 / 最新 ${d.version}`;if($('#version-changelog'))$('#version-changelog').innerHTML=renderChangelog(log);if($('#settings-version-summary'))$('#settings-version-summary').innerHTML=`<div class="version-current-badge"><b>${E(d.version)}</b><span>${E(d.title)}</span></div><p class="hint">${E(meta)}</p>`;if($('#settings-version-changelog'))$('#settings-version-changelog').innerHTML=renderChangelog(log)}catch{if($('#version-badge'))$('#version-badge').textContent='ver ?'}}
if($('#version-expand'))$('#version-expand').onclick=()=>$$('#version-changelog .cl-entry').forEach(x=>x.open=true);
if($('#version-collapse'))$('#version-collapse').onclick=()=>$$('#version-changelog .cl-entry').forEach((x,i)=>x.open=i===0);
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
// 2行に収めるため、直前の実行は「日時＋記号」だけにする。完了/失敗の別は記号と色で示し、
// 手動か定期かはマウスを載せたときに出す（列幅を食わずに情報は失わない）。
function lastRunShort(info){
 if(!info||!info.last_run)return '履歴なし';
 let d=new Date(info.last_run);if(isNaN(d))return String(info.last_run);
 let hm=`${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
 return hm+({ok:' ✓',failed:' ×',cancelled:' ▲'}[info.last_status]||'');
}
function lastRunTitle(info){
 if(!info||!info.last_run)return '実施履歴はまだありません';
 let trig=info.last_trigger==='schedule'?'定期実行':info.last_trigger==='manual'?'手動実行':'';
 return [lastRunLabel(info),trig,info.last_detail||''].filter(Boolean).join('\n');
}
function lastStatusClass(info){if(!info||!info.last_run)return 'none';return info.last_status==='ok'?'ok':info.last_status==='failed'?'ng':'warn'}
function fmtBytes(n){n=Number(n||0);if(!n)return '';return n>=1048576?`${(n/1048576).toFixed(1)}MB`:`${Math.max(1,Math.round(n/1024))}KB`}
function fmtSeconds(n){n=Number(n||0);if(!n)return '';return n>=60?`${Math.floor(n/60)}分${String(Math.round(n%60)).padStart(2,'0')}秒`:`${n.toFixed(1)}秒`}
// 実行が終わってから実績が画面に載るまでには、ほんの少し間がある（結果を保存し、
// それを読み直すまで）。その間を無言にすると「出ないのでは」と見えるので、
// 集計中であることをその場に出す。どの対象が待ちかは、実行前の記録と見比べて判断する。
let metricsPending={};
const METRICS_WAIT_MAX_MS=30000;   // 記録が来ないまま出し続けない。来ないなら黙って引っ込める。
function markMetricsPending(id){
 if(!id||id in metricsPending)return;
 metricsPending[id]={before:(scheduleInfo[id]&&scheduleInfo[id].last_run)||'',at:Date.now()};
}
function metricsIsPending(id){
 let p=metricsPending[id];if(!p)return false;
 let now=(scheduleInfo[id]&&scheduleInfo[id].last_run)||'';
 if(now&&now!==p.before){delete metricsPending[id];return false}          // 新しい記録が届いた
 if(Date.now()-p.at>METRICS_WAIT_MAX_MS){delete metricsPending[id];return false}
 return true;
}
// 直前の実行の実績。所要・転送量・転送速度・取り方（通常/N分割/競争）を1行で出す。
// どれか欠けていても、あるものだけ並べる（古い実績には転送量が入っていない）。
function lastMetricsRow(info,jobId){
 if(jobId&&metricsIsPending(jobId))
  return `<div class="rp-metrics is-pending"><span class="rp-mode calc">集計中</span><em>実行結果をまとめています…</em></div>`;
 let m=(info&&info.last_metrics)||{};
 if(!info||!info.last_run)return '';
 let mode=m.engine==='dde'?['dde','DDE']
  :m.race_winner?['race',`競争→${m.race_winner==='split'?(m.split_how||(m.split_parts||2)+'分割'):'分割なし'}`]
  :m.split_parts>1?[m.split_shape==='row'?'rowsplit':'split',m.split_how||`${m.split_parts}分割`]:['','通常'];
 let bits=[];
 if(m.elapsed)bits.push(fmtSeconds(m.elapsed));
 if(m.rows)bits.push(`${Number(m.rows).toLocaleString()}件`);
 if(m.transfer_bytes)bits.push(fmtBytes(m.transfer_bytes));
 if(m.transfer_kbs)bits.push(`${Math.round(m.transfer_kbs).toLocaleString()}KB/s`);
 if(!bits.length&&!m.split_parts)return '';
 let title=[m.elapsed?`所要 ${fmtSeconds(m.elapsed)}`:'',m.execute_seconds?`問い合わせ ${m.execute_seconds}s`:'',
  m.save_seconds?`転送 ${m.save_seconds}s`:'',m.axis_seconds?`軸の読み直し ${m.axis_seconds}s`:'',
  m.merge_seconds?`結合 ${m.merge_seconds}s`:'',m.row_axis?`行の軸 ${m.row_axis}`:'',
  m.cols?`${m.cols}列`:''].filter(Boolean).join(' / ');
 return `<div class="rp-metrics" title="${E(title)}"><span class="rp-mode ${mode[0]}">${E(mode[1])}</span>`
  +bits.map(b=>`<em>${E(b)}</em>`).join('<em class="rp-m-sep">·</em>')+`</div>`;
}
// 予定と実績で1行、実行の中身で1行。合わせて2行に収める。
function scheduleRowHtml(j,info){
 let next=info&&info.next_run?nextRunLabel(info.next_run):(info&&info.hint==='対象が無効'?'対象が無効':'予定なし');
 let hint=info?(info.hint==='対象が無効'?'':info.hint):(j.enabled?'':'対象が無効');
 return `<span class="rp-chip">次回</span><b class="rp-next" title="${E(hint||next)}">${E(next)}</b>`
  +`<span class="rp-chip alt">直前</span><span class="rp-last ${lastStatusClass(info)}" title="${E(lastRunTitle(info))}">${E(lastRunShort(info))}</span>`;
}
function rowProgressCell(j){
 let info=scheduleInfo[j.id];
 return `<div class="rowprogress" data-jobid="${j.id}"><div class="rp-schedule"><div class="rp-plan">${scheduleRowHtml(j,info)}</div>${lastMetricsRow(info,j.id)}</div><div class="rp-live"><div class="rp-live-top"><span class="rp-state"></span><span class="rp-dots"></span><time class="rp-elapsed"></time></div><div class="rp-track"><i class="rp-bar"></i></div><div class="rp-detail"></div></div></div>`;
}
async function loadSchedulePreview(){try{let d=await fetch('/api/schedule-preview').then(r=>r.json());scheduleInfo=Object.fromEntries((d.items||[]).map(x=>[x.id,x]));applyScheduleCells()}catch{}}
function applyScheduleCells(){$$('.rowprogress').forEach(el=>{if(el.classList.contains('is-running')||el.classList.contains('is-wait')||el.classList.contains('is-done')||el.classList.contains('is-error'))return;let j=cfg?.jobs?.find(x=>x.id===el.dataset.jobid);if(!j)return;let info=scheduleInfo[j.id];
 let pl=el.querySelector('.rp-plan');if(pl)pl.innerHTML=scheduleRowHtml(j,info);
 let sc=el.querySelector('.rp-schedule'),mt=el.querySelector('.rp-metrics');if(sc){let html=lastMetricsRow(info,j.id);if(mt)mt.remove();if(html)sc.insertAdjacentHTML('beforeend',html)}})}
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
   else{runningInfo[x.job_id]={cls:'is-running',state:x.state||'',detail:x.detail||'',elapsed:x.elapsed||0,percent:x.percent||0,phase:x.phase||'',measured:!!x.measured};}
  });
 }else if(s.running&&s.current_job_id){
  let cls=s.step==='error'?'is-error':(s.step==='complete'?'is-done':'is-running');
  if(cls==='is-running')runningInfo[s.current_job_id]={cls:'is-running',state:s.step_label||'',detail:[s.activity_detail,s.activity_value].filter(Boolean).join(' / '),elapsed:s.elapsed_seconds||0,percent:s.step_percent||0,phase:serialPhase(s.step)};
 }
 // バックエンドが確定した完了/失敗の対象を取り込む（累積・不可逆）。
 let doneBefore=runCompletedIds.size+runFailedIds.size;
 if(s.running){
  (s.queue_completed_ids||[]).forEach(id=>{runCompletedIds.add(id);if(!runDoneMeta[id])runDoneMeta[id]={cls:'is-done',state:'完了',detail:'このバッチで完了しました',elapsed:0,percent:100}});
  (s.queue_failed_ids||[]).forEach(id=>{runFailedIds.add(id);if(!runDoneMeta[id])runDoneMeta[id]={cls:'is-error',state:'失敗',detail:'',elapsed:0,percent:100}});
 }
 // 1件終わるたびに実績を取りに行く。60秒の定期取得を待つと、その間ずっと出てこない。
 if(runCompletedIds.size+runFailedIds.size>doneBefore){
  runCompletedIds.forEach(markMetricsPending);runFailedIds.forEach(markMetricsPending);
  loadSchedulePreview();
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
   applyScheduleCells();          // 予定表示へ戻る瞬間に、実績（または集計中）を出し直す
   loadSchedulePreview();         // 最後の1件ぶんの記録を取りこぼさない
  }
 }
 paintRowProgress();
}
function applyRowQueueProgress(d){
 rowQueue={};
 (d.items||[]).forEach(item=>{if(item.state!=='waiting')return;(item.job_ids||[]).forEach(id=>{if(!(id in rowQueue)||item.position<rowQueue[id])rowQueue[id]=item.position})});
 paintRowProgress();
}
// 工程を小さな点で並べ、いまどこかを示す。文字を読まなくても位置が分かる。
const LINE_STEPS=[['session','接続'],['execute','問い合わせ'],['transfer','受信'],['convert','変換'],['publish','公開']];
/* 直列実行の工程名を、並列ラインと同じ5つの点へ寄せる。方式が違っても行の見え方は同じにする。 */
const SERIAL_PHASE={prepare:'session',launch:'session',dde:'session',ready:'session',open:'execute',save:'execute',wait:'transfer',close:'transfer',export:'convert',publish:'publish',complete:'publish'};
function serialPhase(step){return SERIAL_PHASE[String(step||'')]||''}
function stepDotsHtml(phase){
 let at=LINE_STEPS.findIndex(x=>x[0]===phase);
 return LINE_STEPS.map((x,i)=>`<i class="rp-dot${at<0?'':i<at?' done':i===at?' now':''}" title="${x[1]}"></i>`).join('');
}
function paintRowProgress(){
 $$('.rowprogress').forEach(el=>{
  let id=el.dataset.jobid,live=rowLive[id];
  el.classList.remove('is-running','is-wait','is-done','is-error');
  if(live){
   el.classList.add(live.cls);
   el.querySelector('.rp-state').textContent=live.state;
   el.querySelector('.rp-elapsed').textContent=live.elapsed?hhmmss(live.elapsed):'';
   let bar=el.querySelector('.rp-bar');
   bar.style.width=Math.max(0,Math.min(100,Number(live.percent)||0))+'%';
   // 実測で伸びているのか、経過時間からの見当なのかを見分けられるようにする（影実行のバーと同じ約束）。
   bar.classList.toggle('guess',live.cls==='is-running'&&live.measured===false);
   el.querySelector('.rp-detail').textContent=live.detail;
   let dots=el.querySelector('.rp-dots');if(dots)dots.innerHTML=live.cls==='is-running'?stepDotsHtml(live.phase):'';
   el.title='クリックで進捗を表示';
  }else if(rowQueue[id]){
   el.classList.add('is-wait');
   el.querySelector('.rp-state').textContent='実行キュー待ち';
   el.querySelector('.rp-elapsed').textContent='';
   el.querySelector('.rp-bar').style.width='0%';
   let qd=el.querySelector('.rp-dots');if(qd)qd.innerHTML='';
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
const HEARTBEAT_APP_ID='SymfoNaviDataHub';
const HEARTBEAT_CLIENT_ID=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random());
let hb={lastSend:null,lastOk:null,latency:null,fails:0,reconnects:0,wasDown:false,sending:false};
function hbTime(d){return d?new Date(d).toLocaleTimeString('ja-JP',{hour12:false}):'—'}
function paintHeartbeat(serverStatus){let state=$('#hb-state');if(!state)return;let connected=hb.fails===0,label=connected?'正常':(hb.fails<3?'再接続中':'切断中'),cls=connected?'healthy':(hb.fails<3?'reconnecting':'disconnected');state.textContent=label;state.className='hb-status '+cls;$('#hb-last-send').textContent=hbTime(hb.lastSend);$('#hb-last-ok').textContent=hbTime(hb.lastOk);$('#hb-latency').textContent=hb.latency==null?'—':hb.latency+' ms';$('#hb-fails').textContent=hb.fails+'回';$('#hb-reconnects').textContent=hb.reconnects+'回';$('#hb-server-age').textContent=serverStatus?serverStatus.age_seconds+'秒':'—';if($('#hb-app-tabs'))$('#hb-app-tabs').textContent=serverStatus?serverStatus.active_clients+'個':'—';$('#hb-detail').textContent=connected?'通信は正常です。接続断が発生してもサーバーは停止せず自動復旧を待ちます。':'サーバーへ再接続しています。次回試行まで画面を開いたままお待ちください。'}
async function sendHeartbeat(){if(hb.sending)return false;hb.sending=true;hb.lastSend=new Date();let t=performance.now();try{let r=await fetch('/api/heartbeat',{method:'POST',headers:{'Content-Type':'application/json','X-Heartbeat-Client':HEARTBEAT_CLIENT_ID},body:JSON.stringify({app_id:HEARTBEAT_APP_ID,client_id:HEARTBEAT_CLIENT_ID}),cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);await r.json();hb.latency=Math.round(performance.now()-t);hb.lastOk=new Date();if(hb.wasDown)hb.reconnects++;hb.wasDown=false;hb.fails=0;let st=null;try{st=await fetch('/api/heartbeat-status',{cache:'no-store'}).then(x=>x.json())}catch{}paintHeartbeat(st);hideServerLost();return true}catch(e){hb.fails++;hb.wasDown=true;paintHeartbeat();if(hb.fails>=3)showServerLost();return false}finally{hb.sending=false}}
function startHeartbeat(){sendHeartbeat();let worker=null;try{const code="let t=null;onmessage=e=>{if(e.data==='start'){clearInterval(t);t=setInterval(()=>postMessage('tick'),10000)}else if(e.data==='stop'){clearInterval(t);t=null}}";worker=new Worker(URL.createObjectURL(new Blob([code],{type:'application/javascript'})));worker.onmessage=()=>sendHeartbeat();worker.postMessage('start')}catch(e){worker=null}setInterval(sendHeartbeat,10000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')sendHeartbeat()});window.addEventListener('focus',sendHeartbeat);window.addEventListener('pageshow',sendHeartbeat);if($('#hb-retry'))$('#hb-retry').onclick=sendHeartbeat}
startHeartbeat();
// タブ×・ウィンドウ×・遷移など「実際に閉じる」ときだけ明示通知。タブ切替(非アクティブ)ではpagehideは発火しないため誤検知しない。
// リロードでもpagehideは発火するが、再読込後のハートビートがバックエンドの明示クローズ判定を猶予内に解除するため終了しない。
function notifyBrowserClosing(event){if(event?.persisted)return;try{let body=new Blob([JSON.stringify({app_id:HEARTBEAT_APP_ID,client_id:HEARTBEAT_CLIENT_ID,reason:'pagehide',at:new Date().toISOString()})],{type:'application/json'});navigator.sendBeacon('/api/browser-closing',body)}catch(e){}}
window.addEventListener('pagehide',notifyBrowserClosing);

/* V34: keep the browser and the running state in sync — warn before closing during a run, and surface it clearly if the server itself disappears */
window.addEventListener('beforeunload',e=>{if(lastRunning){e.preventDefault();e.returnValue=''}});
/* 1.19.0: タブを閉じても常駐する条件を、閉じる前に一度だけ知らせる。
   実行中はブラウザー標準の確認が出るため、それ以外（予定あり・キューあり）のときだけ案内する。 */
let residencyHintShown=false;
async function noteResidencyOnce(){
 if(residencyHintShown||lastRunning)return;
 try{
  let d=await fetch('/api/heartbeat-status',{cache:'no-store'}).then(r=>r.json());
  if(!d.residency_pending_reason)return;
  residencyHintShown=true;
  toast(`このタブを閉じても「${d.residency_pending_reason}」のため常駐します。完全に終了するには「アプリを終了」を押してください。`);
 }catch{}
}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')noteResidencyOnce()});
function showServerLost(){if(serverLostShown)return;serverLostShown=true;let d=$('#server-lost-overlay');if(d&&!d.open)d.showModal()}
function hideServerLost(){if(!serverLostShown)return;serverLostShown=false;let d=$('#server-lost-overlay');if(d&&d.open)d.close()}
if($('#server-lost-reload'))$('#server-lost-reload').onclick=()=>sendHeartbeat();

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
function togglePeriodBody(){let on=$('#m-period-enabled')?.checked;let b=$('#period-body');if(b)b.hidden=!on;updatePeriodBadge()}
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
  if(!tps.length){if(rb)rb.innerHTML=`<p class="period-cp-ng">このRNEには時間型の管理ポイントがありません（管理ポイント ${d.count||0} 件を調べて0件）。</p><p class="period-cp-note">日付で絞り込む条件がRNE側に定義されていないため、抽出期間の自動指定は使えません。このチェックは外したままで問題ありません（RNEの設定どおりに実行されます）。RNEに何が入っているかは「入力データ」の<b>「RNEの中身を調べる」</b>で確認できます。</p>`;return}
  if(rb)rb.innerHTML=`<p class="period-cp-ok">時間型管理ポイントを ${tps.length} 件検出しました。クリックで設定します。</p><div class="period-cp-list">${tps.map(p=>`<button type="button" class="chip period-cp-pick" data-name="${E(p.name)}">${E(p.name)}<em>${E(p.location)}・${E(p.type_name)}</em></button>`).join('')}</div>`;
  rb.querySelectorAll('.period-cp-pick').forEach(x=>x.onclick=()=>{if($('#m-period-cp'))$('#m-period-cp').value=x.dataset.name;refreshPeriodPreview();dirty();toast(`対象を「${x.dataset.name}」に設定しました`)});
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="period-cp-ng">検出処理でエラーが発生しました。</p>`}}
 finally{hideWaiting()}
};

/* ============================================================
   RNEを調べる：4つの手順（①中身を読む ②分け方を探す ③速さを試す ④本番の動作）。
   機能を足すたびにボタンと説明が横並びに増えて散らかっていたので、左のレールで順番を示し、
   結果は必ず右の同じ場所へ出す形に畳み直した。同時に見える操作は1手順ぶんだけ。
   ============================================================ */
let inspPlan={column:null,row:null};
function inspGo(step){
 $$('.insp-step').forEach(b=>{let on=b.dataset.istep===step;b.classList.toggle('on',on);b.setAttribute('aria-selected',on)});
 $$('.insp-panel').forEach(x=>x.classList.toggle('on',x.dataset.istep===step));
}
// 手順の状態はレールに出す。開かなくても、どこまで進んだかが分かるようにするため。
function inspState(step,text,tone=''){
 let b=document.querySelector(`.insp-step[data-istep="${step}"]`);if(!b)return;
 let e=b.querySelector('.is-state');
 if(e){e.textContent=text;e.className='is-state'+(tone?' '+tone:'')}
 b.classList.toggle('done',tone==='ok');
}
/* 調べた結果は「中身」「列の分け方」「行の分け方」の3つ折りに出す。
   以前は手順2「分け方を探す」という別の手順に分かれていたが、読むものは同じで、
   分けて押す理由が無かった。押す場所は手順1の「RNEを調査」1つだけにする。 */
function inspFind(kind,text,tone){
 if(kind==='column'||kind==='row')inspPlan[kind]={text,tone};
 let f=document.querySelector(`.ri-fold[data-find="${kind}"]`);
 if(f){let e=f.querySelector('.rf-state');
  if(e){e.textContent=text;e.className='rf-state'+(tone?' '+tone:'')}
  f.classList.toggle('is-ng',tone==='ng');f.classList.toggle('is-ok',tone==='ok');
  // 駄目だったものは畳まない。畳むと、何が引っかかったのかを開くまで気づけない。
  if(tone==='ng')f.open=true}
 // レールの手順1には控えの状態（調査済み／要再調査／未調査）を出す。何度も調べ直す
 // 必要があるかどうかが、そこでの唯一の判断材料だから。個々の結果は折りたたみに出す。
 syncTrialControls();
}
/* 調べものは20秒前後サーバーを待つ。これまでは待機モーダルで画面を塞いでいたが、
   影実行と同じように裏で走らせる。進み具合はその手順の結果欄に出し、閉じても続く
   （状態はサーバーが持っているので、開き直せば途中から追いつく）。 */
const INSP_TASK={all:{box:'#m-rne-inspect-result',btn:'#m-rne-inspect-all',needJob:true}};
let inspTaskTimer={},inspTaskRender={};
function inspTaskProgress(kind,st){
 let rb=$(INSP_TASK[kind].box);if(!rb)return;
 rb.hidden=false;
 let pct=Math.max(0,Math.min(100,Number(st.percent||0)));
 rb.innerHTML=`<p class="ri-note"><b>${E(st.title||'')}</b>を実行中です`
  +`${st.rne?` ― 対象 <b>${E(st.rne)}</b>`:''}（経過 ${fmtSeconds(st.elapsed||0)||'0.0秒'}）</p>`
  +`<div class="tp-head"><span class="tp-phase">${E(st.stage||'準備中')}</span><b class="tp-pct">${pct.toFixed(0)}%</b></div>`
  +`<div class="tp-track"><i class="tp-bar guess" style="width:${pct}%"></i></div>`
  +`<p class="ri-note tp-guess">${st.measured?'前回の所要時間':'まだ実測がないため、おおよその見込み'}からの見当です`
  +`（サーバーの応答は途中で測れないため、満杯にはしません）。</p>`
  +`<p class="ri-note">この画面は閉じても構いません。実行中も他の機能を使えます。</p>`;
}
function inspTaskStop(kind){
 if(inspTaskTimer[kind]){clearInterval(inspTaskTimer[kind]);inspTaskTimer[kind]=null}
 let b=$(INSP_TASK[kind].btn);if(b)b.disabled=false;
}
/* いま開いている対象のものか。サーバーは1つしか状態を持たないので、ここで確かめないと
   別の対象の編集画面を開いたときに、前の対象の調査結果がそのまま出てしまう。 */
function inspTaskMine(st){
 if(!st)return false;
 // どの対象のものか名乗っていない状態は、他人のものだと決めつけない（古い状態が残っている場合）。
 if(!st.job_id)return true;
 return String(st.job_id)===String(editing?.id||'');
}
async function inspTaskPoll(kind){
 try{
  let st=await fetch('/api/inspect-task/'+kind,{cache:'no-store'}).then(r=>r.json());
  if(!inspTaskMine(st)){inspTaskStop(kind);return}
  if(st.running){inspTaskProgress(kind,st);return}
  inspTaskStop(kind);
  let fn=inspTaskRender[kind];
  if(fn&&st.result)fn(st.result);
 }catch{}
}
async function inspTaskRun(kind,body,render){
 let c=INSP_TASK[kind],rb=$(c.box);
 if(c.needJob&&(!editing?.id||!cfg.jobs.some(j=>j.id===editing.id))){
  if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">先に「設定を反映」で対象を保存してください。</p>`}return}
 inspTaskRender[kind]=render;
 try{
  let d=await fetch('/api/inspect-task/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify(body)}).then(r=>r.json());
  if(!d.ok){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">開始できませんでした。</p><p class="ri-note">${E(d.error||'')}</p>`}return}
  let b=$(c.btn);if(b)b.disabled=true;
  inspEmpty(kind,true);
  inspTaskProgress(kind,{title:d.title,stage:d.stage,percent:0,elapsed:0,measured:false});
  if(inspTaskTimer[kind])clearInterval(inspTaskTimer[kind]);
  inspTaskTimer[kind]=setInterval(()=>inspTaskPoll(kind),1000);
  inspTaskPoll(kind);   // 一度すぐ見る。もう終わっていれば1秒待たせない
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">開始時にエラーが発生しました。</p>`}}
}
// 手順を開き直したとき、まだ走っているものがあれば途中から追いかける。
function inspTaskResume(){
 Object.keys(INSP_TASK).forEach(async k=>{
  if(inspTaskTimer[k])return;
  try{
   let st=await fetch('/api/inspect-task/'+k,{cache:'no-store'}).then(r=>r.json());
   if(!st.running||!inspTaskMine(st))return;   // 別の対象の調査は、この画面へ出さない
   inspEmpty('read',true);inspTaskProgress(k,st);
   inspTaskRender[k]=inspTaskRender[k]||renderInspectAll;
   inspTaskTimer[k]=setInterval(()=>inspTaskPoll(k),1000);
  }catch{}
 });
}
/* ==== RNEの控え（マスタ） ====================================================
   同じファイルなら調べ直さなくてよい、を1行で言い切る。判断に要るのはそこだけ。
   何が控えてあるか（列・軸・所要・確認済みの割り当て）はその下に数字で並べる。 */
const MASTER_TONE={fresh:'is-fresh',stale:'is-stale',none:'is-none',missing:'is-missing'};
function renderMaster(m){
 let box=$('#m-master-state');if(!box)return;
 if(!m){box.className='master-state';box.textContent='確認中';return}
 box.className='master-state '+(MASTER_TONE[m.state]||'');
 let head={fresh:'調査済み ― 調べ直す必要はありません',stale:'RNEが更新されています ― 調べ直してください',
           none:'まだ調査していません',missing:'RNEファイルが見つかりません'}[m.state]||m.why;
 let c=m.columns||{},ax=m.axes||{},tm=m.timing||{},plans=m.plans||[];
 masterTiming=Number(tm.total||0)||0;
 if(typeof allinRefreshPlan==='function')allinRefreshPlan();
 let cells=[
  ['列',c.have?`${c.count}本`:'—',c.have?`外せる ${c.removable} / 固定 ${c.fixed}`:'未取得'],
  ['行の軸',ax.have?`${ax.count}本`:'—',ax.have?`分割に使える ${ax.usable}本`:'未取得'],
  ['所要時間',tm.have&&tm.total?fmtSeconds(tm.total):'—',tm.have&&tm.rows?`${Number(tm.rows).toLocaleString()}件の実測`:'未計測'],
  ['確認済みの分け方',plans.length?`${plans.length}通り`:'—',plans.length?plans.map(x=>x.how).join(' / '):'影実行で確認すると増えます'],
 ];
 box.innerHTML=`<div class="ms-head"><b>${E(head)}</b><span>${E(m.rne||'')}</span></div>`
  +`<div class="ms-grid">${cells.map(x=>`<div><small>${E(x[0])}</small><b>${E(x[1])}</b><span>${E(x[2])}</span></div>`).join('')}</div>`
  +(m.file?.modified?`<div class="ms-foot"><span>RNEの更新日時: ${E(m.file.modified)}</span>`
     +`<span>控えを取った日時: ${E(c.captured_at||ax.captured_at||'—')}</span></div>`:'')
  +((ax.blocked||[]).length?`<div class="ms-block"><b>使わないことにした軸 ${ax.blocked.length}件</b>`
     +ax.blocked.map(b=>`<span>${E(b.name)}<em>${E(b.reason||'')}</em></span>`).join('')
     +`<button id="m-block-clear" type="button" class="secondary">記録を取り消す</button></div>`:'');
 let cb=$('#m-block-clear');
 if(cb)cb.onclick=async()=>{
  let r=await fetch('/api/rne-master/clear-blocks',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({job_id:editing.id})}),d=await r.json();
  if(d.ok){toast(`${d.removed}件の記録を取り消しました`);renderMaster(d.master)}else toast(d.error||'取り消せませんでした');
 };
 inspState('read',{fresh:'調査済み',stale:'要再調査',none:'未調査',missing:'RNEなし'}[m.state]||'—',
           m.state==='fresh'?'ok':m.state==='none'?'':'ng');
 inspEmpty('read',m.state!=='none');
 // 控えに軸があるなら、全部の軸選択へそのまま入れる。「調査済み」と出しながら
 // 別の欄が「先に『RNEを調査』」と出ていては、どちらが本当か分からない。
 fillAxesFromMaster(ax.list||[]);
 renderNextStep(m);
}
async function loadMaster(stats){
 if(!editing?.id||!cfg.jobs.some(j=>j.id===editing.id)){renderMaster(null);return null}
 try{
  let r=await fetch('/api/rne-master',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({job_id:editing.id,stats:!!stats})}),d=await r.json();
  if(d.ok){renderMaster(d.master);return d}
  renderMaster(null);return null;
 }catch{renderMaster(null);return null}
}
/* 実績。条件ごとの平均だけを見せる。速い順に並べれば「どれが効いたか」は数字で分かる。 */
function renderRneStats(st){
 let box=$('#m-stats-body');if(!box)return;
 if(!st||!st.total){box.innerHTML='';inspEmpty('stats',false);inspState('stats','—','');return}
 inspEmpty('stats',true);
 let g=st.groups||{};
 // 見比べになるのは、値が2つ以上ある条件だけ。1つしか無いものはカードにせず、
 // 「この記録はどういう条件で取ったか」として1行にまとめる（並べても比較にならないため）。
 let keys=Object.keys(g).filter(k=>(g[k].items||[]).length);
 let multi=keys.filter(k=>g[k].items.length>1||k==='how');
 let single=keys.filter(k=>!multi.includes(k));
 let cards=multi.map(k=>{
  let it=g[k].items||[];
  return `<article class="rs-card"><header><b>${E(g[k].label)}</b><small>速い順</small></header>`
   +it.map(x=>`<div class="rs-row"><span>${E(x.key||'—')}</span><b>${fmtSeconds(x.avg)}</b>`
     +`<small>${x.runs}回 / 最短 ${fmtSeconds(x.min)} 最長 ${fmtSeconds(x.max)}</small></div>`).join('')
   +`</article>`;
 }).join('');
 box.innerHTML=`<div class="rs-sum"><b>記録 ${st.total}件</b><span>うち成功 ${st.ok}件</span>`
  +(single.length?`<em class="rs-fixed">${single.map(k=>`${E(g[k].label)}: ${E(g[k].items[0].key||'—')}`).join(' / ')}</em>`:'')
  +`</div>`
  +`<div class="rs-cards">${cards}</div>`
  +`<details class="rs-list"><summary>1回ごとの記録（新しい順に ${(st.runs||[]).length}件）</summary>`
  +`<div class="rs-table">${(st.runs||[]).map(r=>`<div class="rs-line ${r.status==='ok'?'':'is-ng'}">`
     +`<time>${E(String(r.finished_at||'').replace('T',' '))}</time>`
     +`<span>${E(r.how||'分割なし')}</span><b>${r.elapsed?fmtSeconds(r.elapsed):'—'}</b>`
     +`<small>${r.rows?Number(r.rows).toLocaleString()+'件':''}${r.row_axis?' / 軸 '+E(r.row_axis):''}`
     +`${r.host?' / '+E(r.host):''}</small></div>`).join('')}</div></details>`;
 inspState('stats',`${st.total}件`,'ok');
}
async function loadRneStats(){
 let d=await loadMaster(true);
 renderRneStats(d?.stats);
}
if($('#m-stats-reload'))$('#m-stats-reload').onclick=loadRneStats;
/* 裏で走っているものを、どの画面からでも見えるようにする。
   調べものも影実行も画面を閉じても続くので、走っていることが分からないと
   「終わったのか、始まってすらいないのか」を確かめる手立てが無くなる。 */
let bgTasks=[],bgTimer=null;
function renderBgTasks(){
 let box=$('#bg-task');if(!box)return;
 if(!bgTasks.length){box.hidden=true;return}
 let t=bgTasks[0],more=bgTasks.length-1;
 box.hidden=false;
 $('#bg-task-title').textContent=t.title+(more>0?` ほか${more}件`:'');
 $('#bg-task-sub').textContent=`${t.rne||t.job||'対象不明'} / ${Math.round(t.percent||0)}% / 経過 ${fmtSeconds(t.elapsed||0)}`;
 box.title=bgTasks.map(x=>`${x.title}: ${x.rne||x.job||'—'} ${Math.round(x.percent||0)}%\n${x.stage||''}`).join('\n\n');
}
async function loadBgTasks(){
 try{
  let d=await fetch('/api/background-tasks',{cache:'no-store'}).then(r=>r.json());
  bgTasks=d.tasks||[];
 }catch{bgTasks=[]}
 renderBgTasks();
}
if($('#bg-task'))$('#bg-task').onclick=()=>{
 let t=bgTasks[0];if(!t)return;
 let j=t.job_id&&cfg?.jobs?.find(x=>x.id===t.job_id);
 if(!j)return toast(`${t.title}: ${t.rne||t.job||''} ${t.stage||''}`);
 if($('#editor')?.open&&String(editing?.id)===String(j.id))return setEditorTab('inspect');
 if($('#editor')?.open)$('#editor').close();
 openEditor(j);setEditorTab('inspect');inspGo(t.type==='trial'?'trial':'read');
};
bgTimer=setInterval(loadBgTasks,2000);loadBgTasks();
/* ==== 失敗の知らせ ==========================================================
   自動実行は誰も見ていない時間に走る。これまでは失敗しても記録が残るだけで、
   画面を開いて実績欄を見るまで気づけなかった。上の帯に常設の印を出し、
   押せば何が起きたか・いつ取り直すかが分かるようにする。 */
const ALERT_KIND={error:['要対応','ab-error'],warn:['注意','ab-warn'],info:['お知らせ','ab-info']};
let alertState={alerts:[],retries:[]};
async function loadAlerts(){
 let box=$('#alert-badge');if(!box)return;
 try{
  let d=await fetch('/api/alerts',{cache:'no-store'}).then(r=>r.json());
  alertState=d;
  let n=d.count||0,waiting=(d.retries||[]).length;
  box.hidden=!n&&!waiting;
  if(box.hidden)return;
  let [word,tone]=ALERT_KIND[d.worst]||ALERT_KIND.info;
  box.className='ctl alert-badge '+tone;
  $('#alert-title').textContent=n?`${word} ${n}件`:'取り直し待ち';
  let last=(d.alerts||[])[d.alerts.length-1];
  $('#alert-sub').textContent=waiting?`${waiting}件が取り直し待ち`:(last?.jobs||[]).join('・').slice(0,40)||(last?.title||'');
  if($('#alert-dialog')?.open)renderAlerts();
 }catch{}
}
function renderAlerts(){
 let r=alertState.retries||[],rb=$('#alert-retry');
 if(rb){
  rb.hidden=!r.length;
  rb.innerHTML=r.length?`<b>取り直しを待っています（${r.length}件）</b>`
   +r.map(x=>`<div class="ar-line"><span>${E(x.jobs.join('・'))}</span><time>${E(String(x.due_at).replace('T',' '))} に実行</time><em>${x.attempt}回目</em></div>`).join('')
   +`<button type="button" id="alert-cancel-retry" class="secondary">取り直しをやめる</button>`:'';
  let btn=$('#alert-cancel-retry');
  if(btn)btn.onclick=async()=>{await fetch('/api/retries/cancel',{method:'POST'});toast('取り直しの予約を取り消しました');loadAlerts()};
 }
 // 重いものが上、同じ重さなら新しいものが上。溜まったときに「何が壊れているか」を
 // 探させない（このアプリの他の一覧と同じ並べ方）。
 let rank={error:0,warn:1,info:2};
 let list=$('#alert-list'),items=(alertState.alerts||[]).map((x,i)=>[rank[x.kind]??9,-i,x])
   .sort((a,b)=>a[0]-b[0]||a[1]-b[1]).map(x=>x[2]);
 if(!list)return;
 list.innerHTML=items.length?items.map(x=>{
  let [word,tone]=ALERT_KIND[x.kind]||ALERT_KIND.info;
  return `<div class="al-row is-${E(tone.replace('ab-',''))}"><i>${E(word)}</i><div><b>${E(x.title)}</b>`
   +`<small>${E(x.detail)}</small><time>${E(String(x.at).replace('T',' '))}</time></div></div>`}).join('')
  :'<p class="ri-note">未確認の知らせはありません。</p>';
}
if($('#alert-badge'))$('#alert-badge').onclick=()=>{renderAlerts();$('#alert-dialog')?.showModal()};
if($('#alert-close'))$('#alert-close').onclick=()=>$('#alert-dialog').close();
if($('#alert-close-foot'))$('#alert-close-foot').onclick=()=>$('#alert-dialog').close();
if($('#alert-clear'))$('#alert-clear').onclick=async()=>{
 await fetch('/api/alerts/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
 await loadAlerts();renderAlerts();toast('確認済みにしました');
};
setInterval(loadAlerts,5000);loadAlerts();
function inspEmpty(name,hide){let e=document.querySelector(`.ip-empty[data-empty="${name}"]`);if(e)e.hidden=!!hide}
/* 対象を開き直すたびに白紙へ戻す。前に開いていた対象の調査結果が残っていると、
   どのRNEを見ているのか分からなくなる（同じ内容がどのRNEでも出る、の原因）。 */
function inspReset(){
 Object.keys(INSP_TASK).forEach(k=>{inspTaskStop(k);inspTaskRender[k]=null});
 let ms=$('#m-master-state');if(ms){ms.className='master-state';ms.textContent='確認中'}
 let sb=$('#m-stats-body');if(sb)sb.innerHTML='';
 let tb=$('#m-rne-inspect-result');if(tb){tb.hidden=true;tb.innerHTML=''}
 let sr=$('#m-split-trial-result');if(sr){sr.hidden=true;sr.innerHTML=''}
 ['#m-rne-detail-result','#m-column-plan-result','#m-row-split-result']
  .forEach(id=>{let e=$(id);if(e)e.innerHTML='<p class="ri-note">「RNEを調査」を実行すると、ここに出ます。</p>'});
 $$('.ri-fold').forEach(f=>{f.open=false;f.classList.remove('is-ok','is-ng');
  let e=f.querySelector('.rf-state');if(e){e.textContent='未取得';e.className='rf-state'}});
 $$('.ip-empty').forEach(e=>e.hidden=false);
 inspPlan={column:null,row:null};
 inspState('read','未実行');inspState('trial','未実行');
 if(allinTimer){clearInterval(allinTimer);allinTimer=null}
 ['#allin-state','#allin-result'].forEach(id=>{let e=$(id);if(e){e.hidden=true;e.innerHTML=''}});
 allinFillAxes([]);allinSetKind('methods');allinRefreshPlan();allinResume();
 renderInspTarget();
 inspGo('read');syncTrialControls();
}
/* いまどのRNEを調べているのかを、手順1の先頭に必ず出す。ここが空だと、
   どの対象の画面なのかが結果からしか分からない。 */
function renderInspTarget(){
 let box=$('#m-insp-target');if(!box)return;
 if(!editing){box.className='insp-target';box.textContent='対象を確認中';return}
 let saved=!!(editing.id&&cfg?.jobs?.some(j=>j.id===editing.id));
 let path=($('#m-rne-path')?.value||editing.rne_path||'').trim();
 let name=path.split(/[\\/]/).pop()||editing.rne||'（未設定）';
 box.className='insp-target'+(saved?'':' is-draft');
 box.innerHTML=`<i class="it-badge">調査対象</i><b>${E(name)}</b><span>${E(editing.name||'')}</span>`
  +`<code title="${E(path)}">${E(path||'RNEのパスが未設定です')}</code>`
  +(saved?'':'<em class="it-draft">未保存 ― 先に「設定を反映」を押してください</em>');
}
// 方式に関係のない選択肢は出さない。列分割のときに「行」の数を選べても意味がないため。
function syncTrialControls(){
 let m=$('#m-split-mode-trial')?.value||'column';
 let meas=$('#m-split-measure')?.value||'split';
 // 測るものが「分割なしだけ」なら、方式も分割数も競争も意味がない。出さない。
 $$('.insp-panel[data-istep="trial"] [data-when]').forEach(l=>{
  l.hidden=(l.dataset.when==='split'&&meas==='normal')||(l.dataset.when==='both'&&meas!=='both')});
 $$('.trial-parts[data-need]').forEach(l=>{
  if(meas==='normal'){l.hidden=true;return}
  l.hidden=!(l.dataset.need===m||m==='grid')});
 // 軸の決め方は、行が絡む方式のときだけ出す（列分割には関係がない）。
 let ap=$('#trial-axis-pick');
 if(ap)ap.hidden=(meas==='normal')||!(m==='row'||m==='grid');
 let btn=$('#m-split-trial');
 if(btn)btn.textContent=({normal:'分割なしを測る',split:'分割を測る',both:'両方つづけて測る'})[meas]||'影実行を開始';
 let n=$('#trial-need');if(!n)return;
 if(meas==='normal'){
  n.innerHTML='分割なしで1本だけ実行し、<b>基準として保存</b>します。'
   +'この値は「分割だけ」を測ったときの比較相手になります。<b>出力ファイルは更新しません</b>。';
  return;
 }
 if(meas==='both'){
  n.innerHTML='分割なしと分割ありを<b>続けて</b>実行し、その場で比べます。1回で2回ぶんの時間がかかります。'
   +'<b>出力ファイルは更新しません</b>。';
  return;
 }
 // 下調べが済んでいるかを見て、案内を「まだ足りない」から「準備できた」へ切り替える。
 let done=m==='grid'?(inspPlan.column?.tone==='ok'&&inspPlan.row?.tone==='ok'):inspPlan[m]?.tone==='ok';
 let ready=({column:'列の割り当てができています。',row:'行の区切りができています。',
  grid:'列と行の両方がそろっています。片の数は 行×列 になります。'})[m];
 let todo=({column:'先に手順1の「RNEを調査」を実行してください。',
  row:'先に手順1の「RNEを調査」を実行してください。',
  grid:'先に手順1の「RNEを調査」を実行してください。片の数は 行×列 になります。'})[m];
 n.innerHTML=(done?ready:todo)+'<b>出力ファイルは更新しません</b>（比較するだけで、結果は公開しません）。';
}
$$('.insp-step').forEach(b=>b.onclick=()=>{
 let k=b.dataset.istep;inspGo(k);
 if(k==='run')loadRuntimeSplit();
 if(k==='read')loadMaster(false);
 if(k==='stats')loadRneStats();
});
if($('#m-split-mode-trial'))$('#m-split-mode-trial').onchange=syncTrialControls;
if($('#m-split-measure'))$('#m-split-measure').onchange=syncTrialControls;
syncTrialControls();

/* RNEの中身を調べる：管理ポイント（行の軸）とデータ項目（出力される列）をまとめて見せる。
   時間管理ポイントの検出は「抽出期間」タブ側の目的に絞ってあるので、RNE全体の把握はこちらで行う。 */
// RNEを1回で調べ切る。終わったら控えの状態と、手順2〜4の中身をまとめて出し直す。
if($('#m-rne-inspect-all'))$('#m-rne-inspect-all').onclick=()=>inspTaskRun('all',
  {job_id:editing?.id,rne_path:$('#m-rne-path')?.value||'',job_name:editing?.name||'',
   parts:Number($('#m-row-parts')?.value||2)||2,probe:!!$('#m-row-probe')?.checked,
   ...axisChoice()},renderInspectAll);
function renderInspectAll(d){
 let rb=$('#m-rne-inspect-result');if(rb)rb.hidden=false;
 let steps=d.steps||[];
 let head=d.ok?'<p class="ri-ok">RNEの調査が終わりました。控えとして保存しています。</p>'
  :`<p class="ri-ng">一部が読めませんでした。</p><p class="ri-note">${E(d.error||'')}</p>`;
 if(rb)rb.innerHTML=head
  +`<div class="ri-chips">${steps.map(x=>`<span class="ri-chip${x.ok?'':' unnamed'}">${E(x.title)}`
    +`<em>${x.ok?'OK':'NG'} / ${fmtSeconds(x.elapsed)}</em></span>`).join('')}</div>`
  +(steps.some(x=>!x.ok)?`<p class="ri-note">${steps.filter(x=>!x.ok).map(x=>E(x.title+': '+x.error)).join('<br>')}</p>`:'')
  +`<p class="ri-note">この控えは<b>RNEファイルが変わるまで</b>そのまま使えます。影実行でも本番の実行でも、同じ内容を読み直しません。</p>`;
 if(d.master)renderMaster(d.master); else loadMaster(false);
 // 手順2〜4の中身も、いま読んだ結果で出し直す（押し直させない）。
 if(d.read?.ok)try{renderRneInspect(d.read)}catch{}
 if(d.column?.ok)try{renderColumnPlan(d.column)}catch{}
 if(d.row?.ok)try{renderRowPlan(d.row)}catch{}
 // 調べた結果を手順2の既定にする。片方しか使えないなら、そちらを選んでおく。
 let tm=$('#m-split-mode-trial');
 if(tm&&tm.value!=='grid'){
  let col=inspPlan.column?.tone,row=inspPlan.row?.tone;
  if(col==='ok'&&row!=='ok')tm.value='column';
  else if(row==='ok'&&col!=='ok')tm.value='row';
  syncTrialControls();
 }
 loadRuntimeSplit();
}
function renderRneInspect(d){
 let rb=$('#m-rne-detail-result');
 try{
  if(rb)rb.hidden=false;
  if(!d.ok){if(rb)rb.innerHTML=`<p class="ri-ng">RNEを読み取れませんでした。</p><p class="ri-note">${E(d.error||'')}</p>`;inspEmpty('read',true);inspState('read','読み取れません','ng');return}
  let cps=d.points||[],tps=d.time_points||[],items=d.data_items||[],cols=d.output_columns||[];
  let cards=[
   `<div class="ri-card"><span>出力される列</span><b>${cols.length||'—'}</b><small>${cols.length?'直近の出力ファイルの見出し':'未取得'}</small></div>`,
   `<div class="ri-card"><span>管理ポイント</span><b>${cps.length}</b><small>うち時間型 ${tps.length}</small></div>`,
   `<div class="ri-card"><span>データ項目</span><b>${items.length}</b><small>条件・データ欄（参考値）</small></div>`];
  let body=`<div class="ri-cards">${cards.join('')}</div>`;
  if(cols.length)body+=`<details class="ri-list" open><summary>出力される列の一覧（${cols.length}件）</summary><div class="ri-chips">${cols.map(x=>`<span class="ri-chip">${E(x)}</span>`).join('')}</div></details>`;
  else if(d.output_column_error)body+=`<p class="ri-note">列名: ${E(d.output_column_error)}</p>`;
  if(cps.length)body+=`<details class="ri-list"><summary>管理ポイントの一覧（${cps.length}件）</summary><div class="ri-chips">${cps.map(x=>`<span class="ri-chip${x.is_time?' istime':''}">${E(x.name)}<em>${E(x.location)}・${E(x.type_name)}</em></span>`).join('')}</div></details>`;
  if(d.duplicates?.length)body+=`<p class="ri-ng">同じ名前の列が ${d.duplicates.length} 件あります</p>`
   +`<div class="ri-chips">`+d.duplicates.map(x=>`<span class="ri-chip unnamed">${E(x.name)}<em>${x.count}回</em></span>`).join('')+`</div>`
   +`<p class="ri-note">通常の実行には影響しませんが、この状態では列分割は行えません。RNE側で列名を分けてください。</p>`;
  body+=`<p class="ri-note">「出力される列」は直近の出力ファイルから読んだ確実な一覧です。「データ項目」はRNEから直接数えた参考値で、公式マニュアルに記載のない関数を使っているため一致しないことがあります。</p>`;
  if(rb)rb.innerHTML=body;
  inspEmpty('read',true);
  inspState('read',`出力${cols.length||'—'}列 · 管理${cps.length} · 項目${items.length}`,'ok');
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">解析中にエラーが発生しました。</p>`}inspEmpty('read',true);inspState('read','エラー','ng')}
}

/* 列の分割可否を調べる。分割で本当に効果が出るかは「分割して取得できる列」が何本あるかで決まるので、
   実装を進める前にこの数字だけを先に出せるようにしている。 */
const SOURCE_LABEL={cache:'保存済みの列定義',output:'直近の出力ファイル',probe:'1行だけの問い合わせ'};
function renderColumnPlan(d){
 let rb=$('#m-column-plan-result');
 try{
  if(rb)rb.hidden=false;
  if(!d.ok){if(rb)rb.innerHTML=`<p class="ri-ng">調べられませんでした。</p><p class="ri-note">${E(d.error||'')}</p>`;inspEmpty('column',true);inspFind('column','列 調べられません','ng');return}
  let rem=d.removable_count||0,fix=d.fixed_count||0;
  let total=(rem+fix)||d.column_count||0;
  let pct=total?Math.round(rem/total*100):0;
  // 3つ目の要素は良し悪し。以前ここで未定義の変数を見ていて、押すたびに必ず例外になり
  // 「調査中にエラーが発生しました」しか出ていなかった（1.37.0で修正）。
  let verdict=!total?['判定できず','列を数えられませんでした',false]
   :rem<2?['分割の効果は見込めません',`分割して取得できる列が ${rem} 本しかありません`,false]
   :pct<30?['効果は限定的です',`分割できるのは全体の ${pct}% です。残り ${fix} 本は全パートに必ず含まれます`,false]
   :['分割の効果が見込めます',`${rem} 本を分けられます（全体の ${pct}%）。${fix} 本は全パートに残り、結合キーになります`,true];
  let body=`<div class="ri-cards">`
   +`<div class="ri-card"><span>列の合計</span><b>${total}</b><small>${d.basis==='layout'?'RNEから直接数えた値':E(SOURCE_LABEL[d.source]||d.source||'—')}</small></div>`
   +`<div class="ri-card"><span>分割できる列</span><b>${rem}</b><small>データ項目（削除可）</small></div>`
   +`<div class="ri-card"><span>必ず残る列</span><b>${fix}</b><small>管理ポイント由来</small></div>`
   +`<div class="ri-card"><span>分割可能な割合</span><b>${pct}%</b><small>所要 ${d.elapsed}秒</small></div></div>`
   +`<p class="${verdict[2]&&!d.incompatible?'ri-ok':'ri-ng'}">${E(verdict[0])}</p><p class="ri-note">${E(verdict[1])}</p>`;
  if(d.recommended_parts>1)body+=`<p class="ri-note">推奨する分割数: ${d.recommended_parts}（見込み ${d.predicted_gain}倍）</p>`;
  let pf=d.payload;
  if(pf&&pf.unit==='bytes'&&pf.total){
   let fx=Math.round(pf.fixed_share*100);
   body+=`<p class="ri-note"><b>データ量の内訳</b>: 全パートに複製される固定列 ${fx}% ／ 分割できる列 ${100-fx}%。`
    +`何分割しても1パートは最低 ${fx}% を運ぶため、これが短縮の限界です。`
    +`RNEで固定列（管理ポイント）を減らすほど、分割が効くようになります。</p>`;
   let rows=(d.gain_detail||[]).filter(x=>x.parts>1)
     .map(x=>`<span class="ri-chip">${x.parts}分割<em>1パート ${Math.round(x.transfer_ratio*100)}% / 見込み ${x.predicted}倍</em></span>`).join('');
   if(rows)body+=`<div class="ri-chips">${rows}</div>`;
  }
  if(d.anchors?.length)body+=`<p class="ri-note">行をつなぎ留める錨の列: ${d.anchors.map(E).join('、')}（全行の ${Math.round((d.anchor_coverage||0)*100)}% を覆えます）</p>`;
  let lk=d.link||{},useful=d.useful_parts;
  if(lk.headroom){
   let ok=useful>1;
   body+=`<div class="ri-cards">`
    +`<div class="ri-card"><span>回線の上限</span><b>${lk.capacity_kbs}</b><small>KB/s（実測の最大）</small></div>`
    +`<div class="ri-card"><span>直近の単一速度</span><b>${lk.base_kbs}</b><small>KB/s（分割なし1本）</small></div>`
    +`<div class="ri-card"><span>伸びしろ</span><b>${lk.headroom}x</b><small>上限 ÷ 単一速度</small></div>`
    +`<div class="ri-card"><span>有効な分割数</span><b>${useful}</b><small>回線から見た上限</small></div></div>`
    +`<p class="${ok?'ri-ok':'ri-ng'}">${ok?`回線に余地があります。${useful}分割まで意味があります`:'回線に余地がありません。今は分割しても速くなりません'}</p>`
    +`<p class="ri-note">1本ですでに ${lk.base_kbs} KB/s 出ており、回線の上限は約 ${lk.capacity_kbs} KB/s です。`
    +`本数を増やしても合計は ${lk.headroom} 倍までしか伸びないため、各パートが運ぶ量（${Math.round((d.gain_detail||[]).find(x=>x.parts===2)?.transfer_ratio*100||0)}%）を下回れません。`
    +`回線が空いている時間帯は伸びしろが大きくなり、同じRNEでも結果が変わります。</p>`
    +`<p class="ri-note">実測: ${lk.points.map(p=>`${p.parts}本 単一${p.base_kbs}→合計${p.aggregate_kbs} KB/s（${p.sigma}倍）`).join(' / ')}</p>`;
  }else if(pf&&pf.unit==='bytes'){
   body+=`<p class="ri-note">分割が得になるかは回線の空き具合で決まります。影実行を1回行うと、回線の上限と伸びしろを実測して表示します。</p>`;
  }
  if(d.layout?.condition?.length)body+=`<p class="ri-note">ほかに条件欄のデータ項目が ${d.layout.condition.length} 件あります（絞り込み用で、出力の列にはなりません）。</p>`;
  if(d.column_count)body+=`<p class="ri-note">出力の並び順は ${E(SOURCE_LABEL[d.source]||d.source)} から ${d.column_count} 列ぶん取得済みです（結合時の列順に使います）。</p>`;
  if(d.probe?.downloaded_rows!=null)body+=`<p class="ri-note">1行だけの問い合わせ: ${d.probe.downloaded_rows}行 / ${d.probe.size}バイト / ${d.probe.elapsed}秒（全体は ${d.probe.total_rows} 行）</p>`;
  (d.notes||[]).forEach(n=>body+=`<p class="ri-note">${E(n)}</p>`);
  if(d.classify_error)body+=`<p class="ri-note">分類エラー: ${E(d.classify_error)}</p>`;
  if(rem)body+=`<details class="ri-list"><summary>分割して取得できる列（${rem}件）</summary><div class="ri-chips">${d.removable.map(x=>`<span class="ri-chip">${E(x)}</span>`).join('')}</div></details>`;
  if(fix)body+=`<details class="ri-list"><summary>全パートに必ず残る列（${fix}件）</summary><div class="ri-chips">${d.fixed.map(x=>`<span class="ri-chip istime">${E(x)}</span>`).join('')}</div></details>`;
  if(rb)rb.innerHTML=body;
  renderRuntimeSplit(d.runtime_split);
  inspEmpty('column',true);
  inspFind('column',rem<2?`列 分割不可（${rem}本）`:`列 ${rem}/${total}本を分割可`,rem<2?'ng':'ok');
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">調査中にエラーが発生しました。</p>`}inspEmpty('column',true);inspFind('column','列 エラー','ng')}
}

/* 分割の効果を試す（影実行）。分割あり・なしを続けて実行し、結合結果をバイト比較する。
   出力ファイルは更新しない。速いかどうかは実測でしか分からないため、判断材料をここで作る。 */
/* 影実行は数分かかるため、開始だけして裏で走らせる。画面は閉じてもよく、
   実行中もログ・診断など他の機能をそのまま使える。進み具合は結果欄に出す。 */
/* 影実行のログを、モーダルの中でそのまま追えるようにする。
   「ログ・診断」タブへ行き来しなくても、走らせながら見て、そのままコピーできる。
   絞り込みと行数の上限はサーバー側でかけるので、実行中に何度読んでも重くならない。 */
let ilogText='',ilogTimer=null,ilogBusy=false;
function ilogOpen(){return !!$('#insp-log')?.open}
function ilogLineHtml(x){
 return `<div class="log-line ${logLevel(x)}${x.includes('LOG_DEDUP')?' dedup':''}">${E(x)}</div>`;
}
/* ログを「ユーザーの操作」単位でまとめる。1回の操作で何十行も出るので、
   そのまま並べると、どこからどこまでが1つの操作なのかが読み取れない。
   操作の始まりになる印を決めておき、次の印までを1かたまりとして畳む。 */
const LOG_ACTIONS=[
 [/処理開始 trigger=/,       '実行'],
 [/SPLIT_TRIAL_START /,      '影実行（速さを試す）'],
 [/INSPECT_TASK_START /,     '調べもの'],
 // ROW_AXES / COLUMN_WEIGHTS などは操作の途中で出る。ここで切ると1つの操作が分かれてしまう。
 // 区切りにするのは「利用者が押した瞬間」に出る印だけ。
 [/設定保存 job=/,           '設定の保存'],
 [/APP_START /,              'アプリの起動'],
];
function logActionOf(line){
 for(let [re,label] of LOG_ACTIONS)if(re.test(line))return label;
 return '';
}
function logActionTitle(line,label){
 // 何に対する操作かが分かるよう、対象名かRNE名を添える
 let m=line.match(/(?:job|rne)=([^\s]+)/);
 let who=m?m[1].split(/[\\/]/).pop():'';
 return label+(who?`： ${who}`:'');
}
function logActionHtml(lines){
 let groups=[],cur=null;
 for(let line of lines){
  let label=logActionOf(line);
  if(label||!cur){
   cur={title:label?logActionTitle(line,label):'その他',at:line.slice(0,19),lines:[]};
   groups.push(cur);
  }
  cur.lines.push(line);
 }
 // 新しい操作を上に出す。いま見たいのはたいてい直前の操作。
 return groups.slice().reverse().map((g,i)=>{
  let bad=g.lines.filter(x=>x.includes('[ERROR]')).length,
      warn=g.lines.filter(x=>x.includes('[WARNING]')).length;
  return `<details class="ilog-act${bad?' has-error':(warn?' has-warn':'')}" ${i===0?'open':''}>`
   +`<summary><b>${E(g.title)}</b><span>${E(g.at)}</span>`
   +`<em>${g.lines.length}行${bad?` · エラー${bad}`:''}${warn?` · 警告${warn}`:''}</em></summary>`
   +g.lines.map(ilogLineHtml).join('')+`</details>`;
 }).join('');
}
async function ilogLoad(scroll=false){
 let box=$('#ilog-body');if(!box||ilogBusy)return;
 ilogBusy=true;
 try{
  let q=new URLSearchParams({limit:'400',filter:$('#ilog-filter')?.value||'split',q:$('#ilog-q')?.value||''});
  let d=await fetch('/api/log?'+q).then(r=>r.json());
  ilogText=d.text||'';
  let lines=ilogText?ilogText.split(/\r?\n/):[];
  box.innerHTML=lines.length
   ?(($('#ilog-group')?.value||'flat')==='action'?logActionHtml(lines):lines.map(ilogLineHtml).join(''))
   :'<p class="ri-note">この条件に当てはまるログはありません。</p>';
  let c=$('#ilog-count');
  if(c)c.textContent=lines.length?`${lines.length}行 / 全${Number(d.total||0).toLocaleString()}行`:'該当なし';
  if(scroll)box.scrollTop=box.scrollHeight;
 }catch{if(box)box.innerHTML='<p class="ri-ng">ログを読めませんでした。</p>'}
 finally{ilogBusy=false}
}
// 実行中は勝手に追いかける。止まったら追いかけるのもやめる（無駄に読みに行かない）。
function ilogFollow(running){
 let want=running&&ilogOpen()&&!!$('#ilog-follow')?.checked;
 if(want&&!ilogTimer){ilogTimer=setInterval(()=>ilogLoad(true),2000);ilogLoad(true)}
 if(!want&&ilogTimer){clearInterval(ilogTimer);ilogTimer=null}
}
if($('#ilog-group'))$('#ilog-group').onchange=()=>ilogLoad(false);
if($('#insp-log'))$('#insp-log').ontoggle=()=>{if(ilogOpen())ilogLoad(true);else ilogFollow(false)};
if($('#ilog-reload'))$('#ilog-reload').onclick=()=>ilogLoad(true);
if($('#ilog-filter'))$('#ilog-filter').onchange=()=>ilogLoad(true);
if($('#ilog-q'))$('#ilog-q').oninput=()=>{clearTimeout($('#ilog-q')._t);$('#ilog-q')._t=setTimeout(()=>ilogLoad(true),300)};
if($('#ilog-follow'))$('#ilog-follow').onchange=()=>ilogFollow(!!splitTrialTimer);
if($('#ilog-copy'))$('#ilog-copy').onclick=()=>textToClipboard(ilogText,'表示中のログをコピーしました');
if($('#ilog-copy-all'))$('#ilog-copy-all').onclick=async()=>{
 let d=await fetch('/api/log?limit=5000&filter=all').then(r=>r.json());
 textToClipboard(d.text||'','ログ全文をコピーしました');
};
// 消すのは絞り込んだ分ではなく実行ログ全体。取り返しがつかないので必ず確認する。
if($('#ilog-clear'))$('#ilog-clear').onclick=async()=>{
 if(!confirm('実行ログを消去しますか？（表示中の分だけでなく、ログ全体が消えます）'))return;
 let r=await fetch('/api/log/clear',{method:'POST'});
 if(r.ok){toast('ログを消去しました');ilogText='';await ilogLoad(true)}
 else toast('ログを消去できませんでした');
};

let splitTrialTimer=null;
const RUN_MODE_LABEL={auto:'自動',race:'競争させる',force:'常に分割',off:'使わない'};
const SHAPE_ICON={column:'列',row:'行',grid:'格'};
/* 手順4は「次に実行したらどうなるか」の一枚板。読む順番を1つに決める。
     1行目 … 何をするか（これだけ読めば足りる）
     カード … 確認済みの形と実測。使うものに印を付ける
     脚注   … 設定と条件
   形を選ばせないのが既定。実測でいちばん速かった形をアプリが選ぶ。 */
function speedText(v){return v?Number(v).toFixed(2)+'倍':''}
function shapeCard(p){
 let ic=SHAPE_ICON[p.shape]||'列';
 let bits=[];
 if(p.pieces)bits.push(`${p.pieces}片を同時に`);
 if(p.axis)bits.push(`軸: ${p.axis}`);
 if(p.rows)bits.push(`${Number(p.rows).toLocaleString()}件で一致`);
 let note='';
 if(p.shape!=='column'&&p.axis_seconds)
  note=`軸の読み直し ${Number(p.axis_seconds).toFixed(1)}秒を含めた実力です`
      +(p.raw_speedup?`（読み直しを除けば ${speedText(p.raw_speedup)}）`:'');
 return `<article class="sp-card ${p.chosen?'is-used':''} ${p.stale?'is-stale':''}">
  <i class="sp-ic sp-${E(p.shape)}">${ic}</i>
  <div class="sp-main"><b>${E(p.how)}</b><span>${E(bits.join(' / '))}</span>${note?`<small>${E(note)}</small>`:''}</div>
  <div class="sp-num"><strong>${speedText(p.speedup)||'—'}</strong><small>${p.speedup?'速い':'速さの裏付けなし'}</small></div>
  <div class="sp-tag">${p.chosen?'<em class="sp-used">これを使います</em>':''}${p.stale?'<em class="sp-old">RNEが更新されました</em>':''}</div>
 </article>`;
}
function renderRuntimeSplit(rs){
 let box=$('#m-split-run-state');if(!box)return;
 if(!rs){
  box.className='split-run-state';
  box.innerHTML='<div class="sp-head"><b>まだ調べていません</b><span>「いまの判定を見る」を押すと、次に本番で実行したときどうなるかが出ます。</span></div>';
  inspState('run','—','');return;
 }
 let mode=RUN_MODE_LABEL[rs.mode]||rs.mode;
 let saved=rs.saved||[],fresh=saved.filter(p=>!p.stale);
 let head,chip,tone;
 if(rs.active){
  box.className='split-run-state is-on';
  if(rs.mode==='race'){
   head=`分割なし1本と<b>${E(rs.how)}</b>を同時に走らせ、先に終わった方を使います`;
   chip=`競争 · ${rs.how}`;
  }else{
   head=`<b>${E(rs.how)}</b>で取得します`+(rs.observed_speedup?` — 実測 <b>${speedText(rs.observed_speedup)}</b>速い`:'');
   chip=`${mode} · ${rs.how}`;
  }
  tone='ok';
 }else{
  box.className='split-run-state is-off';
  head=`<b>分割せず1本</b>で取得します`;
  chip=`${mode} · 分割しない`;tone='';
 }
 let why=rs.active?'':(rs.reason||'');
 let foot=[`動作: ${mode}`,`分け方: ${(rs.shapes||[]).find(x=>x.id===rs.shape)?.label||rs.shape}`,
           `単独実行で使えるライン: ${rs.budget}本`];
 if(rs.mode==='auto')foot.push(`「自動」が求める短縮: ${rs.min_speedup}倍以上`);
 if(rs.active&&rs.proven_at)foot.push(`裏付けを得た日時: ${rs.proven_at}`);
 box.innerHTML=`<div class="sp-head"><b>次に実行すると ${head}</b>${why?`<span class="sp-why">${E(why)}</span>`:''}</div>`
  +(saved.length?`<div class="sp-cards">${saved.map(shapeCard).join('')}</div>`
    :`<p class="sp-empty">確認済みの分け方はまだありません。手順3の影実行で<b>結果が一致</b>すると、その形がここに並びます。`
     +`「自動」で使われるには、さらに <b>${rs.min_speedup}倍</b>以上の短縮が要ります。</p>`)
  +`<div class="sp-foot">${foot.map(x=>`<span>${E(x)}</span>`).join('')}</div>`;
 inspState('run',chip,tone);
 if(fresh.length>1&&rs.shape==='auto')
  box.insertAdjacentHTML('beforeend','<p class="sp-tip">確認済みの形が複数あります。「分け方: 自動」のままにしておけば、いちばん速かった形が使われます。</p>');
}
// 手順4を単独で更新する。手順2や手順3の副産物ではなく、いつでも今の判定を見に行ける。
async function loadRuntimeSplit(){
 if(!editing?.id)return;
 let btn=$('#m-split-refresh');if(btn)btn.disabled=true;
 try{
  let r=await fetch('/api/run-split-state',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({job_id:editing.id,split_mode:$('#m-split-mode')?.value||'auto',
                            split_shape:$('#m-split-shape')?.value||'auto'})}),d=await r.json();
  if(d.ok)renderRuntimeSplit(d.runtime_split);
  else toast(d.error||'判定を取得できませんでした');
 }catch{toast('判定を取得できませんでした')}
 finally{if(btn)btn.disabled=false}
}
if($('#m-split-refresh'))$('#m-split-refresh').onclick=loadRuntimeSplit;
if($('#m-split-shape'))$('#m-split-shape').onchange=loadRuntimeSplit;
if($('#m-split-mode'))$('#m-split-mode').onchange=loadRuntimeSplit;

/* 軸の決め方。調べずに決め打ちする道（表側#1・番号指定）と、調べてから選ぶ道（名前指定・
   偏りが少ないものを自動）の4通り。対象ごとに保存し、画面の無い本番の実行でも同じ軸を使う。 */
/* 同じ「軸の決め方」を、手順2（分け方を探す）と手順3（速さを試す）の両方に置く。
   影実行だけで完結させたいので、どちらで変えても両方に反映する。 */
const AXIS_PICK=[{m:'#m-axis-mode',i:'#m-axis-index',n:'#m-axis-name',
                  iw:'#m-axis-index-wrap',nw:'#m-axis-name-wrap',h:'#m-axis-hint'},
                 {m:'#m-axis-mode-t',i:'#m-axis-index-t',n:'#m-axis-name-t',
                  iw:'#m-axis-index-wrap-t',nw:'#m-axis-name-wrap-t',h:'#m-axis-hint-t'}];
const AXIS_HINT={
 first:'表側の1番目を使います。明細のRNEなら必ず1本はあるので、調べずに分けられます。',
 index:'表側の指定番号を使います。調べずに分けられます。使えなければ1番目に戻ります。',
 name:'名前で指定します。番号が動いても追随します。先に手順1の「RNEを調査」で候補を出してください。',
 balanced:'表側のうち、直近の出力で最も散らばっている軸を選びます。いちばん重い片が小さくなります。'};
function axisChoice(){
 return {row_axis_mode:$('#m-axis-mode')?.value||'first',
         row_axis_index:Number($('#m-axis-index')?.value||1)||1,
         row_axis_name:$('#m-axis-name')?.value||''};
}
function syncAxisPick(from){
 // どちらで変えても、もう一方へ写す
 let src=AXIS_PICK.find(x=>x.m===from)||AXIS_PICK[0];
 let m=$(src.m)?.value||'first',ix=Number($(src.i)?.value||1)||1,nm=$(src.n)?.value||'';
 AXIS_PICK.forEach(g=>{
  let sm=$(g.m);if(!sm)return;
  sm.value=m;
  if($(g.i))$(g.i).value=ix;
  if($(g.n)&&nm&&[...$(g.n).options].some(o=>o.value===nm))$(g.n).value=nm;
  if($(g.iw))$(g.iw).hidden=m!=='index';
  if($(g.nw))$(g.nw).hidden=m!=='name';
  if($(g.h))$(g.h).textContent=AXIS_HINT[m]||'';
 });
 if(editing){editing.row_axis_mode=m;editing.row_axis_index=ix;editing.row_axis_name=nm}
}
AXIS_PICK.forEach(g=>[g.m,g.i,g.n].forEach(id=>{
 let e=$(id);if(e)e.addEventListener('change',()=>{syncAxisPick(g.m);dirty()});
}));
// 調べた結果から、名前で選べる候補を作る（使える軸だけ・散らばりも見せる）
/* 控えの軸を、手順3の「軸の決め方」と、まとめて測るの候補へ同時に入れる。
   置き場所が2つあると、片方だけ空という食い違いが必ず起きる。 */
function fillAxesFromMaster(list){
 list=(list||[]).filter(x=>x&&x.name&&x.usable!==false);
 if(!list.length)return;
 fillAxisNames({axes:list.map(x=>({...x,usable:true,enough:true})),axis:null});
 allinFillAxes(list);
}
/* 調べ終わったら次に何をするのかを、その場に出す。手順の行き来を利用者に
   覚えさせない（測って終わり、では設定に結び付かない）。 */
function renderNextStep(m){
 let box=$('#insp-next');if(!box)return;
 let state=m?.state||'none',plans=(m?.plans||[]).length;
 let go=(step,label,why,tone)=>{box.className='insp-next '+(tone||'');
  box.innerHTML=`<div class="in-main"><b>次にすること</b><span>${E(why)}</span></div>`
   +`<button type="button" class="in-go" data-step="${step}">${E(label)}</button>`;
  let b=box.querySelector('.in-go');
  if(b)b.onclick=()=>{
   if(state==='missing')return setEditorTab('basic');
   inspGo(step);if(step==='run')loadRuntimeSplit();if(step==='stats')loadRneStats()}};
 if(state==='missing')return go('read','入出力タブを開く','このRNEを開けないため、調査も実行もできません。パスを直してください','is-ng');
 if(state!=='fresh')return go('read','RNEを調査','まずこのRNEを1回調べます。ここで読んだ内容を、以降の手順がそのまま使います','is-todo');
 if(!plans)return go('trial','速さを測りにいく','調査は済んでいます。次は分け方ごとの速さを実測して、いちばん速い形を決めます','is-todo');
 return go('run','本番の設定を見る',`裏付けの取れた分け方が ${plans}通りあります。本番でどれを使うかを確かめてください`,'is-ok');
}
function fillAxisNames(d){
 let list=(d.axes||[]).filter(x=>x.usable&&x.enough);
 let cur=$('#m-axis-name')?.value||editing?.row_axis_name||'';
 let html=list.length?list.map(x=>{
  let b=x.balance,extra=b?` / 最多${Math.round(b.top_share*100)}%`:'';
  return `<option value="${E(x.name)}">${E(x.location)}#${x.index+1} ${E(x.name)}（${Number(x.category_count||0).toLocaleString()}種${extra}）</option>`;
 }).join(''):'<option value="">（使える軸がありません）</option>';
 AXIS_PICK.forEach(g=>{
  let sel=$(g.n);if(!sel)return;
  sel.innerHTML=html;
  if(cur&&list.some(x=>x.name===cur))sel.value=cur;
  else if(d.axis?.name)sel.value=d.axis.name;
 });
}
function renderRowPlan(d){
 let rb=$('#m-row-split-result');
 try{
  if(rb)rb.hidden=false;
  if(!d.ok){if(rb)rb.innerHTML=`<p class="ri-ng">調べられませんでした。</p><p class="ri-note">${E(d.error||'')}</p>`;inspEmpty('row',true);inspFind('row','行 調べられません','ng');return}
  if(rb)rb.innerHTML=rowSplitRender(d);
  fillAxisNames(d);
  allinFillAxes(d.axes);
  inspEmpty('row',true);
  let ax=d.axis;
  inspFind('row',ax?`行 ${d.parts}分割可（${ax.name}）`:'行 使える軸なし',ax?'ok':'ng');
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">調査中にエラーが発生しました。</p>`}inspEmpty('row',true);inspFind('row','行 エラー','ng')}
}
// 行を絞れるのは管理ポイントだけ（出力される列に条件を付けても1行も絞れない）。
// どの軸が使えるかを、置かれている場所（表側／表頭／条件）ごとに出す。
function axisListHtml(d){
 let ax=d.axes||[],pick=d.axis;
 if(!ax.length){
  return `<p class="ri-ng">行を分けられる軸（管理ポイント）を読み取れませんでした</p>`
   +`<p class="ri-note">${E(d.axes_error||'このRNEには管理ポイントがありません')}</p>`;
 }
 let usable=ax.filter(x=>x.usable&&x.enough);
 let head=pick
  ?`<p class="ri-ok">「${E(pick.name)}」で ${d.parts}分割できます（${E(pick.location)}の${pick.index+1}番目 / ${E(pick.type_name)}）</p>`
   +`<p class="ri-note">${E(pick.reason)}。明細データの問い合わせなら<b>表側</b>に必ず軸があるので、`
   +`このRNEに限らず同じやり方で分けられます。直近の出力ファイルは要りません。</p>`
   +`<p class="ri-note"><b>ここに出ているのは、いま調べた時点の目安です。</b>`
   +`仕掛のように件数が動くものは、実行するころには値の顔ぶれが変わります。`
   +`実際の分割点は<b>実行する直前にもう一度読み直して、その場の値から決めます</b>`
   +`（値が足りなければ分割数もその場で下げます）。</p>`
  :`<p class="ri-ng">${d.parts}分割できる軸がありませんでした</p>`
   +`<p class="ri-note">${d.parts}種類以上の値を持つ管理ポイントか、期間が設定された時間型が要ります。</p>`;
 let rows=ax.map(x=>{
  let good=x.usable&&x.enough,me=pick&&x.location===pick.location&&x.index===pick.index;
  let val=x.is_time?`期間 ${E((x.period||{}).from||'?')}〜${E((x.period||{}).to||'?')}`
        :x.over8000?'値が8000件超'
        :(x.category_count!=null?`値 ${Number(x.category_count).toLocaleString()}種`:'値を読めません');
  return `<span class="ri-chip${me?' istime':(good?'':' unnamed')}">${me?'★ ':''}${E(x.location)}${x.index+1} ${E(x.name)}`
   +`<em>${E(x.type_name)} / ${val}${good?'':' / '+E(x.reason)}</em></span>`;
 }).join('');
 return head+`<div class="ri-chips">${rows}</div>`
  +`<p class="ri-note">★ が次に使う軸です。表側 → 表頭 → 条件 の順に、先頭から使える軸を選びます。`
  +`値は<b>サーバーのデータから読み込んで</b>数えています（${usable.length}本が使えます）。`
  +`<b>全値型</b>の軸は決まった値の一覧を持たないので、読み込ませてから数える必要があります。</p>`
  +(ax.some(x=>x.over8000)?`<p class="ri-note">「値が8000件超」と出ている軸は、DLLが一覧にできる上限`
     +`（NAVI_ERROR_OVER8000）を超えています。値の数が少ない別の軸を使います。</p>`:'')
  +(pick&&!pick.is_time&&(pick.categories||[]).length
    ?`<details class="ri-list"><summary>「${E(pick.name)}」の値（先頭 ${pick.categories.length}件）</summary>`
     +`<div class="ri-chips">${pick.categories.slice(0,60).map(v=>`<span class="ri-chip">${E(v)}</span>`).join('')}</div>`
     +`<p class="ri-note">これを ${d.parts}組へ順に配ります。組ごとの行数はサーバーに聞くまで分からないので、`
     +`偏りは実行後の行数で確かめます。</p></details>`:'');
}
function rowSplitRender(d){
 let b=d.breakdown||{},body=axisListHtml(d);
 // 行分割の見込み。行は重複しないので運ぶ量は増えず、転送は「回線の伸びしろ」の範囲で縮む。
 // サーバー側が縮むかは条件を付けて測るまで分からないので、縮まない場合と分割数ぶん縮む場合の幅で出す。
 let est=(()=>{
  if(!b.known)return {lo:'—',hi:'—'};
  let head=Math.max(1,Math.min(d.parts,(d.link&&d.link.headroom)||1));
  let tr=b.transfer_seconds/head;
  return {lo:(b.total/(b.server_seconds+tr)).toFixed(2),hi:(b.total/(b.server_seconds/d.parts+tr)).toFixed(2)};
 })();
 if(b.known){
  let srv=Math.round(b.server_share*100),dl=Math.round(b.download_share*100),fm=Math.round(b.format_share*100);
  body+=`<div class="ri-cards">`
   +`<div class="ri-card"><span>サーバー側で結果を作る</span><b>${b.server_seconds}s</b><small>全体の ${srv}%</small></div>`
   +`<div class="ri-card"><span>受信（回線）</span><b>${b.download_seconds}s</b><small>${dl}%${b.download_kbs?` · ${Math.round(b.download_kbs).toLocaleString()}KB/s`:''}</small></div>`
   +`<div class="ri-card"><span>整形・書き出し</span><b>${b.format_seconds}s</b><small>${fm}%${b.format_kbs?` · ${Math.round(b.format_kbs).toLocaleString()}KB/s`:''}</small></div>`
   +`<div class="ri-card"><span>${d.parts}分割の見込み</span><b>${est.lo}〜${est.hi}x</b><small>実行が縮まない〜分割数ぶん縮む</small></div></div>`
   +`<p class="ri-ok">行を分ければ、受信（${dl}%）と整形（${fm}%）はどちらも行数に比例して縮みます。`
   +`合わせて ${dl+fm}% です。サーバー側（${srv}%）も縮むかどうかが、測って確かめたい点です。</p>`
   +`<p class="ri-note">転送せずに問い合わせだけを実行した時間（${b.server_seconds}秒）が、サーバー側で結果を作るのにかかった時間です。`
   +`通常の実行（${b.execute}秒）との差 ${b.download_seconds}秒 が受信、そのあとの保存（${b.save}秒）が手元での整形です。`
   +`合計 ${b.total}秒 ／ ${Number(b.rows||0).toLocaleString()}行。この測定では1バイトも受信していません。</p>`
   +(b.format_kbs&&b.download_kbs?`<p class="ri-note">受信 ${Math.round(b.download_kbs)}KB/s に対し整形は ${Math.round(b.format_kbs)}KB/s。`
     +`整形は手元のCPU仕事なので、並列に走らせれば台数ぶん縮みます。受信は回線しだいです。</p>`:'');
 }else if(d.probe_error){
  body+=`<p class="ri-ng">所要時間の内訳を測れませんでした。</p><p class="ri-note">${E(d.probe_error)}</p>`;
 }else{
  body+=`<p class="ri-note">「所要時間の内訳も測る」を選ぶと、サーバー側で結果を作る時間と転送の時間を切り分けます（転送は発生しません）。行分割が効くかどうかは、その内訳でほぼ決まります。</p>`;
 }
 let cs=d.candidates||[];
 if(!cs.length){
  if(d.candidate_error)body+=`<p class="ri-note">列側の参考情報: ${E(d.candidate_error)}</p>`;
  return body;
 }
 // ここから下は「出力される列」から見た参考情報。行を絞る力は無い（データ欄には条件が効かない）。
 body+=`<details class="ri-list"><summary>参考: 出力される列から見た区切り（行は絞れません）</summary>`;
 // 絞り込みの条件が付くのは条件欄の項目だけ。ここを外すと、条件は rc=OK でも1行も絞られない。
 body+=`<p class="ri-note">最も均等に割れるのは「${E(cs[0].column)}」です</p>`
  +`<p class="ri-note">直近の出力 ${Number(d.sample_rows).toLocaleString()}行 を読んで、${d.columns}列のうち ${d.examined} 列を調べました`
  +`（データ項目 ${d.removable_count} 本は範囲で区切れます。管理ポイント ${d.fixed} 本はカテゴリの組分けになります）。`
  +`偏りは「いちばん重い組が、均等だった場合の何倍か」です（1.00 が完全に均等）。サーバーには触れていません。</p>`;
 body+=cs.map((x,i)=>{
  let head=`<summary>${E(x.column)}<em> 偏り ${x.balance} / ${x.method==='range'?'範囲で区切る':'カテゴリを組分け'}`
   +`${x.distinct?` / 値 ${Number(x.distinct).toLocaleString()}種`:' / 値は多数'}${x.exact?'':'（標本から推定）'}</em>`
   +`${x.in_condition?' <b class="ri-ok-in">条件欄</b>':' <b class="ri-warn-in">データ欄のみ・絞れません</b>'}`
   +`${x.order==='numeric'?' <b class="ri-warn-in">数値として比較</b>':''}${x.has_empty?' <b class="ri-warn-in">空値あり</b>':''}</summary>`;
  let rows=x.method==='range'
   ? `<div class="ri-chips">`+x.groups.map((g,k)=>`<span class="ri-chip">${k+1}組目<em>`
       +`${g.from_open?'＞':'≧'} ${E(String(g.from))} 〜 ≦ ${E(String(g.to))} / ${Number(g.rows).toLocaleString()}行 (${Math.round(g.share*100)}%)</em></span>`).join('')+`</div>`
       +(x.api?`<p class="ri-note"><b>NaviChangeConditionDI へ渡す条件</b>: `
          +x.api.calls.map(c=>`${c.part}組目 ${E(c.text)}`).join(' ／ ')
          +`<br>condition=${x.api.calls.map(c=>'0x'+c.condition.toString(16)).join(',')}`
          +` / range=${x.api.calls.map(c=>'0x'+c.range.toString(16)).join(',')}`
          +` / lcheck=${x.api.calls.map(c=>c.lcheck).join(',')} rcheck=${x.api.calls.map(c=>c.rcheck).join(',')}`
          +`（0=境界値を含む、1=含まない）</p>`:'')
   : `<div class="ri-chips">`+x.groups.map((g,k)=>`<span class="ri-chip">${k+1}組目<em>${Number(g.rows).toLocaleString()}行 (${Math.round(g.share*100)}%) / ${g.values.length}種</em></span>`).join('')+`</div>`
       +`<div class="ri-chips">`+x.groups.map((g,k)=>`<span class="ri-chip istime">${k+1}: ${g.values.slice(0,6).map(E).join('、')}${g.values.length>6?` ほか${g.values.length-6}`:''}</span>`).join('')+`</div>`;
  let warn='';
  if(x.order==='numeric')warn+=`<p class="ri-note">この列は数字だけなので、数として並べて区切りました。サーバー側が文字として比べる場合は境目がずれます。実際の行数は次の段階で数え直して確かめます。</p>`;
  if(x.has_empty)warn+=`<p class="ri-note">空の値が ${Number(x.empty_rows).toLocaleString()}行 あります。${x.api?'1組目の条件に NAVI_NULL を足して拾います。':'条件で拾い漏らすと行が落ちるため、実装時はどれかの組へ必ず含めます。'}</p>`;
  return `<details class="ri-list"${i?'':' open'}>${head}${rows}${warn}</details>`;
 }).join('');
 body+=`<p class="ri-note">これらは出力される列（データ欄）なので、条件を付けても1行も絞れません。`
  +`均等に割れる場所の目安としてのみ見てください。</p></details>`;
 return body;
}

const PHASE_LABEL={weights:'① 列の重みを測定',normal:'② 分割なしを実行',split:'③ 分割を並列実行',
 race:'②③ 競争（同時実行）',merge:'④ 結合',compare:'⑤ 結果を比較'};
// 1本にまとめた棒では、どの片が遅れているのかも、いま何をしているのかも分からない。
// 分割したぶんだけ棒を並べ、片ごとに「工程」と「書けたバイト数」を出す。
const PART_STEPS=['接続','RNEを開く','担当外の列を外す','行の条件を設定','問い合わせを実行','CSVへ保存','完了'];
function partProgressHtml(list){
 // 1本のときも出す。分割なしを測っているときこそ、いま何をしているのかが知りたい。
 if(!Array.isArray(list)||!list.length)return '';
 return `<div class="pp-list">`+list.map(x=>{
  let pct=Math.max(0,Math.min(100,Number(x.percent||0)));
  let idx=Number(x.step_index||0);
  let dots=PART_STEPS.map((s,i)=>`<i class="pp-dot${x.done?' done':(i+1===idx?' on':(i+1<idx?' done':''))}" title="${E(s)}"></i>`).join('');
  return `<div class="pp-row${x.done?' is-done':''}">`
   +`<div class="pp-head"><b>${E(x.part||'')}</b><span class="pp-step">${dots}<em>${E(x.step||'')}</em></span>`
   +`<span class="pp-num">${x.bytes?(x.bytes/1024/1024).toFixed(1)+' MB':'—'}${x.rows?` · ${Number(x.rows).toLocaleString()}行`:''}</span>`
   +`<b class="pp-pct">${pct.toFixed(0)}%</b></div>`
   +`<div class="pp-track"><i class="pp-bar${x.bytes?'':' guess'}" style="width:${pct}%"></i></div></div>`;
 }).join('')+`</div>`;
}
function splitTrialRender(d){
 let rb=$('#m-split-trial-result');if(!rb)return;
 // 走ってもいない・結果も無いなら、空の枠を残さない（何も無い箱が1つ増えるだけ）。
 if(!d.running&&!d.result){rb.hidden=true;rb.innerHTML='';return}
 rb.hidden=false;
 if(d.running){
  // 進み具合は「書き出されつつあるファイルの大きさ ÷ 見込みの大きさ」で出している。
  // まだ1バイトも出ていない間（サーバ側で問い合わせ実行中）は経過時間からの見当で、
  // その場合は縞模様にして「これは見当です」と分かるようにする。
  let pct=Math.max(0,Math.min(100,Number(d.percent||0)));
  let byBytes=Number(d.bytes||0)>0&&Number(d.expected_bytes||0)>0;
  let phase=PHASE_LABEL[d.phase]||'';
  inspEmpty('trial',true);
  inspState('trial',`実行中 ${pct.toFixed(0)}%`+(phase?` · ${phase.replace(/^[①-⑤]+\s*/,'')}`:''),'run');
  rb.innerHTML=`<p class="ri-note"><b>${E(d.job||'')}</b> の影実行を実行中です（経過 ${fmtSeconds(d.elapsed||0)}）</p>`
   +`<div class="tp-head"><span class="tp-phase">${E(phase)}</span><b class="tp-pct">${pct.toFixed(0)}%</b></div>`
   +`<div class="tp-track"><i class="tp-bar${byBytes?'':' guess'}" style="width:${pct}%"></i></div>`
   +`<p class="ri-note">${E(d.stage||'準備中')}</p>`
   +partProgressHtml(d.part_progress)
   +(byBytes?'':`<p class="ri-note tp-guess">まだ受信が始まっていないため、ここまでは経過時間からの見当です（実際に届き始めると実測に切り替わります）。</p>`)
   +`<p class="ri-note">この画面は閉じても構いません。実行中も他の機能を使えます。詳しい経過は「ログ・診断」で確認できます。</p>`;
  return;
 }
 let r=d.result;if(!r)return;
 if(!r.ok){
  let extra='';
  if(r.row_condition_ineffective){
   rb.innerHTML=`<p class="ri-ng">行の条件が効きませんでした（この列では行を分けられません）</p>`
    +`<p class="ri-note">${E(r.error||'')}</p>`
    +`<div class="ri-cards">`
    +`<div class="ri-card"><span>分割なし</span><b>${Number(r.normal_rows||0).toLocaleString()}</b><small>行</small></div>`
    +(r.part_rows||[]).map(x=>`<div class="ri-card"><span>${E(x.part)}</span><b>${Number(x.rows||0).toLocaleString()}</b>`
      +`<small>見込み ${Number(x.expected||0).toLocaleString()}行${x.locate?` / ${E(x.locate)}`:''}</small></div>`).join('')
    +`</div>`
    +`<p class="ri-note">絞り込みの条件は<b>条件欄</b>の項目に付くものです。出力される列（データ欄）に同じ条件を設定しても、`
    +`rc=OK が返るだけで1行も絞られません。「${E(r.row_column||'')}」が条件欄にあるかを、手順1の「中身を読む」で確認してください。</p>`
    +`<p class="ri-note">結合はしていません。出力ファイルも更新していません。</p>`;
   inspEmpty('trial',true);inspState('trial','行の条件が効かない','ng');
   return;
  }
  if(r.rowset_mismatch&&r.part_rows?.length)extra=`<div class="ri-cards">`
    +`<div class="ri-card"><span>分割なし</span><b>${r.normal_rows??'—'}</b><small>行</small></div>`
    +r.part_rows.map(x=>`<div class="ri-card"><span>${E(x.part)}</span><b>${x.rows}</b><small>行 / ${x.cols}列</small></div>`).join('')+`</div>`;
  if(r.duplicates?.length)extra=`<div class="ri-chips">`
    +r.duplicates.map(x=>`<span class="ri-chip unnamed">${E(x.name)}<em>${x.count}回</em></span>`).join('')+`</div>`
    +`<p class="ri-note">RNE側で列名を分ける（別名を付ける）と、分割できるようになります。</p>`;
  if(r.rowset_mismatch)extra+=`<p class="ri-note">結果は公開していません。既存の出力ファイルは無事です。</p>`;
  rb.innerHTML=`<p class="ri-ng">${r.duplicates?.length?'同じ名前の列があるため分割できません':(r.rowset_mismatch?'このRNEでは列分割を使えません':'試せませんでした。')}</p><p class="ri-note">${E(r.error||'')}</p>${extra}`;
  inspEmpty('trial',true);inspState('trial','失敗','ng');
  return;
 }
 if(r.measure==='normal'){
  // 基準の測定。比べる相手ではなく、これ自身が比べられる側になる。
  let mb=(r.normal_size||0)/1024/1024;
  let ex=Number(r.normal_execute||0),sv=Number(r.normal_save||0);
  let nb=`<div class="ri-cards">`
   +`<div class="ri-card"><span>分割なし 合計</span><b>${r.normal_elapsed}s</b><small>${mb.toFixed(2)} MB</small></div>`
   +`<div class="ri-card"><span>実行（サーバー＋受信）</span><b>${ex.toFixed(1)}s</b><small>${ex?Math.round(r.normal_size/1024/ex).toLocaleString():'—'} KB/s</small></div>`
   +`<div class="ri-card"><span>保存（整形）</span><b>${sv.toFixed(1)}s</b><small>${sv?Math.round(r.normal_size/1024/sv).toLocaleString():'—'} KB/s</small></div>`
   +`<div class="ri-card"><span>件数</span><b>${Number(r.rows||0).toLocaleString()}</b><small>${r.cols}列</small></div></div>`
   +`<p class="ri-ok">基準として保存しました</p>`
   +`<p class="ri-note">次に「分割だけ」を測ると、この値と比べます。分割のたびに分割なしを走らせ直す必要はありません。`
   +`ただし回線の混み具合は時間帯で変わるので、間があいたら測り直してください。</p>`
   +`<p class="ri-note">出力ファイルは更新していません（影実行）。</p>`;
  inspEmpty('trial',true);
  inspState('trial',`基準 ${r.normal_elapsed}s · ${Number(r.rows||0).toLocaleString()}件`,'ok');
  rb.innerHTML=nb;return;
 }
 let faster=r.speedup&&r.speedup>1.05,cp=r.compare||{};
 let verdict=!r.compared?['測りました（比較していません）',
    `所要時間は ${r.split_elapsed}秒 でした。比べる相手が無いので、速いかどうかも結果が正しいかも判定していません。`
    +`「分割なしだけ」を1度実行すると、次から比較できます`]
  :!r.identical?(cp.content_identical
   ?['内容は一致しました（並び順のみ相違）','行の中身はすべて一致しています。行の並び順だけが分割なしと違います']
   :[`結果が一致しませんでした`,E(cp.reason||'分割した結果と分割なしの結果が違います')])
  :faster?[`${r.speedup}倍 速くなりました`,`結果は分割なしと完全に一致し、所要時間が ${r.normal_elapsed}秒 から ${r.split_elapsed}秒 へ短縮しました`]
  :['速くなりませんでした',`結果は一致しましたが、所要時間は ${r.normal_elapsed}秒 に対し ${r.split_elapsed}秒 でした。この分割数では得になりません`];
 let how=r.how||(r.mode==='row'?`行${r.row_parts}分割`:r.mode==='grid'?`行${r.row_parts}×列${r.column_parts}（${r.parts}片）`:`列${r.parts}分割`);
 let body=`<div class="ri-cards">`
  +`<div class="ri-card"><span>分割なし${r.baseline_used?'（保存済み）':''}</span><b>${r.normal_elapsed??'—'}${r.normal_elapsed?'s':''}</b>`
   +`<small>${r.normal_size?(r.normal_size/1024/1024).toFixed(2)+' MB':'測っていません'}</small></div>`
  +`<div class="ri-card"><span>${E(how)}</span><b>${r.split_elapsed}s</b><small>実行 ${r.split_run_elapsed}s ＋ 結合 ${r.merge_elapsed}s</small></div>`
  +`<div class="ri-card"><span>速度比</span><b>${r.speedup?r.speedup+'x':'—'}</b><small>転送量 ${r.transfer_ratio}倍</small></div>`
  +`<div class="ri-card"><span>結果の一致</span><b>${r.identical?'一致':(cp.content_identical?'内容一致':'不一致')}</b><small>${r.rows}行 ${r.cols}列</small></div></div>`
  +`<p class="${r.identical&&faster?'ri-ok':'ri-ng'}">${E(verdict[0])}</p><p class="ri-note">${E(verdict[1])}</p>`
  +(r.baseline_used&&r.baseline?`<p class="ri-note">比べた相手は<b>保存済みの基準</b>です（${E(r.baseline.taken_at||'')}`
     +`${r.baseline.age_days!=null?` / ${r.baseline.age_days}日前`:''} ／ ${r.baseline.rows?Number(r.baseline.rows).toLocaleString()+'件':''}）。`
     +`回線の混み具合が違う時間帯どうしの比較になるため、速度比は目安です。同時に測りたいときは「両方つづけて」を選んでください。</p>`:'')
  +`<p class="ri-note">出力ファイルは更新していません（影実行）。結合キーは ${r.key_count} 列です。</p>`;
 if(cp.reason)body+=`<p class="ri-note">比較: ${E(cp.reason)}（行 ${cp.rows_a} 対 ${cp.rows_b} / 並び順一致 ${cp.order_match?'はい':'いいえ'}）</p>`;
 if(cp.count_match===false)body+=`<p class="ri-ng">結合結果の行数が分割なしと違います（${Number(cp.duplicated_rows||0).toLocaleString()}行 多い）。`
  +`同じ行が複数のパートに入っています。</p>`;
 if(cp.samples?.length)body+=`<details class="ri-list"><summary>違いの例（${cp.samples.length}件）</summary><div class="ri-chips">`
  +cp.samples.map(x=>x.columns.map(c=>`<span class="ri-chip unnamed">${E(c.name)}<em>${E(String(c.a).slice(0,18))} → ${E(String(c.b).slice(0,18))}</em></span>`).join('')).join('')+`</div></details>`;
 if(r.results?.length)body+=`<details class="ri-list"><summary>パートごとの内訳（${r.results.length}件）</summary><div class="ri-chips">`
  +r.results.map(x=>`<span class="ri-chip">${E(x.part)}<em>${x.cols}列 / ${x.elapsed}s / ${(x.size/1024/1024).toFixed(2)}MB</em></span>`).join('')+`</div></details>`;
 if(r.mode&&r.mode!=='column'){
  let ra=r.row_axis||{},dr=r.row_drift;
  if(dr&&(dr.added||dr.gone||dr.diff)){
   let ex=(dr.added_sample||[]).slice(0,5),
       how=dr.compared==='values'?`増えた ${dr.added} / 消えた ${dr.gone}`
         :`${dr.diff>0?'+':''}${Number(dr.diff||0).toLocaleString()}種。事前は見本しか読んでいないので、増減の内訳までは分かりません`;
   body+=`<p class="ri-note"><b>実行の直前に読み直した結果</b>: `
    +`事前 ${Number(dr.before||0).toLocaleString()}種 → 実行時 ${Number(dr.after||0).toLocaleString()}種`
    +`（${how}）。分割点はこの実行時の値から決めています。`
    +(dr.compared==='values'&&ex.length?` 増えた例: ${ex.map(E).join('、')}`:'')+`</p>`;
  }
  // 1つの値に行が集中している軸は、何組に分けても一番重い片が全体を決める。
  // 「分けたのに速くならない」の理由がここで分かる。
  let sk=r.row_skew;
  if(sk&&sk.ratio>=1.25){
   body+=`<p class="ri-note"><b>片寄っています</b>: 一番重い片が ${Number(sk.max_rows||0).toLocaleString()}行`
    +`（${sk.parts}等分なら ${Number(sk.even_rows||0).toLocaleString()}行 / <b>${sk.ratio}倍</b>）。`
    +(sk.top_share?`「${E(r.row_column||'')}」の値ひとつだけで全体の ${Math.round(sk.top_share*100)}% を占めるためです。`:'')
    +`並列で待たされるのは一番重い片なので、この軸では最大でも ${sk.ceiling}倍までしか縮みません。`
    +`分割数を増やしても頭打ちです。ほかの軸（値が散らばっているもの）を選ぶと改善します。</p>`;
  }
  if(r.row_parts_want&&r.row_parts&&r.row_parts_want!==r.row_parts)
   body+=`<p class="ri-note">頼まれたのは ${r.row_parts_want}分割ですが、実行時の値では ${r.row_parts}分割が上限でした。`
    +`その場で下げています。</p>`;
  if((r.row_part_rows||[]).length)body+=`<div class="ri-chips">`
   +r.row_part_rows.map(x=>`<span class="ri-chip">${E(x.part)}<em>${Number(x.rows||0).toLocaleString()}行`
     +`${x.expected?` / 見込み ${Number(x.expected).toLocaleString()}行`:''}</em></span>`).join('')+`</div>`;
  body+=`<p class="ri-note">行の軸: <b>${E(r.row_column||'')}</b>（${E(r.row_location||'')}${ra.index!=null?ra.index+1:''} / ${E(r.row_type||'')}）`
   +(ra.is_time?`。期間 ${E((ra.period||{}).from||'')}〜${E((ra.period||{}).to||'')} を ${r.row_parts}つに割りました。`
              :`。${ra.category_count!=null?Number(ra.category_count).toLocaleString()+'種の値':'値'}を ${r.row_parts}組へ配りました。`)
   +`行は重複しないので、合計で運ぶ量は分割なしと同じです${r.mode==='grid'?'が、列の固定分は片ごとに複製されます':''}。</p>`;
 }
 if(r.trials?.length)body+=`<p class="ri-note">これまでの実測: `+r.trials.map(t=>`${t.parts}分割 ${t.observed_speedup.toFixed(2)}倍（${t.samples}回）`).join(' / ')+`</p>`;
 if(r.race){
  let win=r.race_winner==='split'?`${r.parts}分割`:'分割なし';
  body+=`<p class="ri-note"><b>競争の結果: ${win}の勝ち</b>（分割なし ${r.normal_elapsed}s 対 ${r.parts}分割 ${r.split_elapsed}s）</p>`;
  if(r.race_order?.length)body+=`<div class="ri-chips">`+r.race_order.map((x,i)=>`<span class="ri-chip">${i+1}着 ${E(x.part)}<em>${x.at}s</em></span>`).join('')+`</div>`;
  body+=`<p class="ri-note">この値は同じ回線を奪い合った結果です。運ぶ量が多い分割なしの側がより強く痛むため、速度比は分割に有利へ振れます（実測相当の値で 1.11倍 対 1.29倍、伸びしろは 1.44倍 対 2.56倍）。単独で測った値と混ぜると分割しすぎる方向へ狂うので、回線の見積もりと速度比の平均からは除いています。</p>`;
 }
 inspEmpty('trial',true);
 inspState('trial',`${E(how)} ${r.speedup?r.speedup+'x':'—'} · ${r.identical?'一致':(cp.content_identical?'内容一致':'不一致')}`,
  r.identical&&faster?'ok':'ng');
 if(r.plan_saved)body+=`<p class="ri-ok">この ${r.parts}分割の割り当てを保存しました。`
  +(r.split_mode==='off'?'この対象は「使わない」設定のため、本番では分割しません。設定を「自動」にすると使われます。'
   :`次の本番実行から、この割り当てで ${r.parts}分割で取得します（実行時に測り直しはしません）。`)+`</p>`;
 else if(r.identical)body+=`<p class="ri-note">この割り当ては保存していません（本番では分割しません）。保存の条件は「結果が一致し、かつ ${r.min_speedup}倍以上速いこと」です。</p>`;
 rb.innerHTML=body;
}
let splitTrialSeen='';
async function splitTrialPoll(){
 try{
  let r=await fetch('/api/column-split-trial/status'),d=await r.json();
  // 別の対象の影実行を、この画面へ出さない（サーバーは1件しか状態を持たない）
  if(d.job_id&&editing?.id&&String(d.job_id)!==String(editing.id)){
   if(splitTrialTimer){clearInterval(splitTrialTimer);splitTrialTimer=null}return}
  splitTrialRender(d);
  if(!d.running){
   clearInterval(splitTrialTimer);splitTrialTimer=null;ilogFollow(false);if(ilogOpen())ilogLoad(true);
   // 影実行で裏付けが保存されたかもしれない。手順4を取り直して、いまの判定へ合わせる。
   if(d.result&&splitTrialSeen!==(d.result.rne||'')+String(d.elapsed||'')){
    splitTrialSeen=(d.result.rne||'')+String(d.elapsed||'');loadRuntimeSplit();
   }
  }
  else ilogFollow(true);
 }catch{}
}
if($('#m-split-trial'))$('#m-split-trial').onclick=async()=>{
 let rb=$('#m-split-trial-result');
 if(!editing?.id||!cfg.jobs.some(j=>j.id===editing.id)){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">先に「設定を反映」で対象を保存してください。</p>`}return}
 let parts=Number($('#m-split-parts')?.value||0);
 let race=!!$('#m-split-race')?.checked;
 let mode=$('#m-split-mode-trial')?.value||'column',rowParts=Number($('#m-row-trial-parts')?.value||2);
 let measure=$('#m-split-measure')?.value||'split';
 if(race)measure='both';
 try{
  let r=await fetch('/api/column-split-trial',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({job_id:editing.id,parts,race,mode,row_parts:rowParts,measure,...axisChoice()})}),d=await r.json();
  if(!d.ok){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">開始できませんでした。</p><p class="ri-note">${E(d.error||'')}</p>`}inspEmpty('trial',true);inspState('trial','開始できません','ng');return}
  toast(`${({normal:'分割なし（基準）',split:({column:'列分割',row:'行分割',grid:'行×列'})[mode],
             both:`分割なしと${({column:'列分割',row:'行分割',grid:'行×列'})[mode]}`})[measure]}の測定を開始しました。実行中も他の機能を使えます`);
  inspGo('trial');inspEmpty('trial',true);inspState('trial','開始しました','run');
  splitTrialRender({running:true,job:d.job,stage:'準備中',elapsed:0});
  if(splitTrialTimer)clearInterval(splitTrialTimer);
  splitTrialTimer=setInterval(splitTrialPoll,2000);splitTrialPoll();ilogFollow(true);
 }catch(x){if(rb){rb.hidden=false;rb.innerHTML=`<p class="ri-ng">開始時にエラーが発生しました。</p>`}}
};

/* ==== まとめて測る（ALL-IN） =================================================
   1本ずつ測らせると「どれとどれを、どの基準で比べたのか」を利用者が覚えることに
   なる。同じ基準の上で続けて測り、速い順に並べたものを1枚で返す。
   押すのは1つ、読むのは順位の表だけ、という形にしてある。 */
let allinTimer=null,allinKind='methods',allinAxes=[],masterTiming=0;
function allinShapes(){return $$('.allin-shape:checked').map(x=>x.value)}
function allinRowParts(){return Number($('#allin-row-parts')?.value||2)||2}
function allinParts(){return Number($('#allin-parts')?.value||0)||0}
function allinAxisPick(){return [$('#allin-axis-a')?.value||'',$('#allin-axis-b')?.value||''].filter(Boolean)}
/* 始める前に「何を何回測るか」を出す。押してから知るのでは遅い。 */
function allinPlanList(){
 let list=[],reuse=!!$('#allin-reuse')?.checked;
 if(!reuse)list.push('分割なし（基準）');
 if(allinKind==='axes')allinAxisPick().forEach(a=>list.push(`行${allinRowParts()}分割（${a}）`));
 else allinShapes().forEach(sh=>list.push(split_shape_label_js(sh)));
 return list;
}
function split_shape_label_js(shape){
 let c=allinParts()||2,r=allinRowParts();
 return shape==='row'?`行${r}分割`:shape==='grid'?`行${r}×列${c}（${r*c}片）`:`列${c}分割`;
}
function allinRefreshPlan(){
 let p=$('#allin-plan');if(!p)return;
 let list=allinPlanList(),n=list.length;
 let one=Number(masterTiming||0);
 let est=one?`／見込み 約${fmtSeconds(one*n)}`:'';
 let go=$('#allin-start');
 let measured=allinKind==='axes'?allinAxisPick().length:allinShapes().length;
 if(go)go.disabled=!measured;
 p.textContent=measured?`${n}本を続けて測ります: ${list.join(' → ')}${est}`
   :(allinKind==='axes'?'比べる軸を選んでください':'比べる分け方を1つ以上選んでください');
}
function allinSetKind(k){
 allinKind=k;
 $$('.allin-kind button').forEach(b=>b.classList.toggle('on',b.dataset.akind===k));
 $$('.allin-body').forEach(x=>x.hidden=x.dataset.akind!==k);
 allinRefreshPlan();
}
/* 調べた軸を、そのまま比較の候補にする。使えない軸は出さない（測っても失敗するため）。 */
function allinFillAxes(axes){
 allinAxes=(axes||[]).filter(x=>x&&x.usable!==false&&x.name);
 [['#allin-axis-a',0],['#allin-axis-b',1]].forEach(([id,i])=>{
  let sel=$(id);if(!sel)return;
  let keep=sel.value;
  sel.innerHTML=allinAxes.length?allinAxes.map(a=>`<option value="${E(a.name)}">${E(a.name)}`
    +`（${E(a.location||'')}${a.category_count?' '+Number(a.category_count).toLocaleString()+'種':''}）</option>`).join('')
   :'<option value="">（先に「RNEを調査」）</option>';
  if(keep&&allinAxes.some(a=>a.name===keep))sel.value=keep;
  else if(allinAxes[i])sel.value=allinAxes[i].name;
 });
 allinRefreshPlan();
}
function allinItemRow(x){
 let tone=x.state==='完了'?(x.identical===false?'is-ng':'is-ok'):x.state==='失敗'?'is-ng':
          x.state==='実行中'?'is-run':x.state==='中止'?'is-off':'';
 return `<div class="ai-item ${tone}"><i>${E(x.state)}</i><b>${E(x.label)}</b>`
  +`<span>${x.elapsed?fmtSeconds(x.elapsed):E(x.error||x.why||'')}</span>`
  +`${x.speedup?`<em>${x.speedup}倍</em>`:'<em></em>'}</div>`;
}
function allinRender(d){
 let box=$('#allin-state'),res=$('#allin-result');
 let items=d.items||[],sum=d.summary||{};
 if(box){
  box.hidden=!items.length;
  let ng=items.filter(x=>x.state==='失敗').length,off=items.filter(x=>x.state==='中止').length;
  box.innerHTML=items.length?`<div class="ai-head"><b>${d.running?`測定中 ${d.index}/${d.total}`
    :`測定おわり ― 完了 ${items.filter(x=>x.state==='完了').length}件`+(ng?` / 失敗 ${ng}件`:'')+(off?` / 中止 ${off}件`:'')}</b>`
   +`<span>${E(d.rne||'')}${d.elapsed?` / 経過 ${fmtSeconds(d.elapsed)}`:''}</span></div>`
   +items.map(allinItemRow).join(''):'';
 }
 let stop=$('#allin-stop'),go=$('#allin-start');
 if(stop)stop.hidden=!d.running;
 if(go)go.disabled=!!d.running;
 // 手順2のレールにも結果を出す。開かなくても、何がいちばん速かったかが分かる。
 if(items.length)inspState('trial',d.running?`測定中 ${d.index}/${d.total}`
   :(sum.best?`最速 ${sum.best.label}`:'使える分け方なし'),
   d.running?'run':(sum.best?'ok':'ng'));
 if(!res)return;
 let rank=sum.ranked||[];
 if(!rank.length&&!(sum.rejected||[]).length){res.hidden=true;res.innerHTML='';return}
 res.hidden=false;
 res.innerHTML=(sum.baseline?`<p class="ri-note">基準（分割なし）は <b>${fmtSeconds(sum.baseline)}</b>。下の順位はこの時間と比べたものです。`
   +`行を使う形は、本番で毎回かかる<b>軸の読み直し</b>も含めた実力値です。</p>`:'')
  +(rank.length?`<div class="ai-rank">${rank.map(x=>`<div class="ai-row${x.rank===1?' is-best':''}">`
    +`<i class="ai-no">${x.rank}</i><b>${E(x.label)}</b>`
    +`<span class="ai-time">${fmtSeconds(x.elapsed)}</span>`
    +`<span class="ai-up">${x.speedup?x.speedup+'倍':'—'}</span>`
    +`<span class="ai-save">${x.saved>0?`${fmtSeconds(x.saved)}短縮`:'短縮なし'}</span>`
    +`<button type="button" class="secondary ai-use" data-shape="${E(x.shape)}" data-axis="${E(x.axis||'')}">本番で使う</button>`
    +`</div>`).join('')}</div>`
   :'<p class="ri-ng">使える分け方がありませんでした。</p>')
  +((sum.rejected||[]).length?`<details class="ri-list"><summary>使えなかったもの（${sum.rejected.length}件）</summary>`
    +`<div class="ai-bad">${sum.rejected.map(x=>`<div><b>${E(x.label)}</b><span>${E(x.why)}</span></div>`).join('')}</div></details>`:'');
 // 測って選んだのに保存を押し忘れて効かない、という切れ目を作らない。
 // ここで対象の設定として確定させ、そのまま手順3を開いて結果を見せる。
 $$('.ai-use').forEach(b=>b.onclick=async()=>{
  let sh=b.dataset.shape,ax=b.dataset.axis;
  if($('#m-split-shape'))$('#m-split-shape').value=sh;
  if($('#m-split-mode'))$('#m-split-mode').value='auto';
  if(ax){AXIS_PICK.forEach(g=>{let n=$(g.n);if(n&&![...n.options].some(o=>o.value===ax))n.add(new Option(ax,ax))});
   if($('#m-axis-mode'))$('#m-axis-mode').value='name';
   if($('#m-axis-name'))$('#m-axis-name').value=ax;
   syncAxisPick('#m-axis-mode')}
  if(editing){editing.split_shape=sh;editing.split_mode='auto'}
  b.disabled=true;
  let saved=await applyJob(false,true);
  b.disabled=false;
  inspGo('run');loadRuntimeSplit();
  toast(saved?`本番の分け方を「${SPLIT_SHAPE_JP[sh]||sh}」${ax?`（軸 ${ax}）`:''}にして保存しました`
             :`「${SPLIT_SHAPE_JP[sh]||sh}」を選びましたが保存できませんでした。「設定を反映」を押してください`);
 });
}
const SPLIT_SHAPE_JP={column:'列分割',row:'行分割',grid:'行×列'};
/* 開き直したときに、まだ走っていれば途中から追いかける。画面を閉じても続くため。 */
async function allinResume(){
 try{
  let d=await fetch('/api/split-trial-batch/status',{cache:'no-store'}).then(r=>r.json());
  if(!d.running)return;
  if(d.job_id&&editing?.id&&String(d.job_id)!==String(editing.id))return;
  allinRender(d);
  if(allinTimer)clearInterval(allinTimer);
  allinTimer=setInterval(allinPoll,1500);
 }catch{}
}
async function allinPoll(){
 try{
  let d=await fetch('/api/split-trial-batch/status',{cache:'no-store'}).then(r=>r.json());
  // 別の対象のまとめ測定を、この画面へ出さない
  if(d.job_id&&editing?.id&&String(d.job_id)!==String(editing.id)){
   if(allinTimer){clearInterval(allinTimer);allinTimer=null}return}
  allinRender(d);
  if(d.running)splitTrialPoll();
  else if(allinTimer){clearInterval(allinTimer);allinTimer=null;loadRuntimeSplit();ilogFollow(false)}
 }catch{}
}
if($('#allin-start'))$('#allin-start').onclick=async()=>{
 let res=$('#allin-result');
 if(!editing?.id||!cfg.jobs.some(j=>j.id===editing.id))
  return toast('先に「設定を反映」で対象を保存してください');
 let payload={job_id:editing.id,kind:allinKind,parts:allinParts(),row_parts:allinRowParts(),
              reuse_baseline:!!$('#allin-reuse')?.checked,
              shapes:allinShapes(),axes:allinAxisPick(),...axisChoice()};
 try{
  let d=await fetch('/api/split-trial-batch',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify(payload)}).then(r=>r.json());
  if(!d.ok)return toast(d.error||'開始できませんでした');
  if(res){res.hidden=true;res.innerHTML=''}
  inspEmpty('trial',true);inspState('trial',`まとめて測定中 0/${d.total}`,'run');
  toast(`${d.total}本の測定を開始しました。実行中も他の機能を使えます`);
  if(allinTimer)clearInterval(allinTimer);
  allinTimer=setInterval(allinPoll,1500);allinPoll();ilogFollow(true);
 }catch{toast('開始時にエラーが発生しました')}
};
if($('#allin-stop'))$('#allin-stop').onclick=async()=>{
 let d=await fetch('/api/split-trial-batch/stop',{method:'POST'}).then(r=>r.json()).catch(()=>({}));
 toast(d.ok?'いま測っている1本を終えたら止めます':(d.error||'止められませんでした'));
};
$$('.allin-kind button').forEach(b=>b.onclick=()=>allinSetKind(b.dataset.akind));
['#allin-parts','#allin-row-parts','#allin-reuse','#allin-axis-a','#allin-axis-b']
 .forEach(id=>{let e=$(id);if(e)e.addEventListener('change',allinRefreshPlan)});
$$('.allin-shape').forEach(x=>x.addEventListener('change',allinRefreshPlan));

/* ============================================================
   v1.18.0 データビュワー：データ一覧 / 集計表 / グラフ の3タブ構成。
   集計表・グラフはカラムリスト(左) + 行・列・値のドロップゾーン(右)で構成し、
   Excelピボット互換の階層集計（行/列の多段階層・小計・総計・件数/合計/平均/最小/最大）を提供する。
   ============================================================ */
let viewerData=null,viewerRows=[],viewerFiltered=[],viewerPage=1,viewerSort={col:-1,dir:1};
let viewerView='list',pivotState={rows:[],columns:[],values:[],aggregate:'count',showSubtotals:true,showGrandTotal:true};
const VIEWER_PAGE_SIZE=100,PSEP='\u001f',CSEP='\u001e';
const CHART_COLORS=['#0d8191','#3a4d9c','#0b6b4c','#b5822a','#7658ae','#c9564a','#1f6aa8','#8a5f18','#5c8a2a','#a5372c','#5a6f77','#2c9c9c'];
const AGG_LABEL={count:'件数',sum:'合計',avg:'平均',min:'最小',max:'最大'};

async function loadViewerJobs(){let sel=$('#viewer-job');if(!sel)return;try{let d=await fetch('/api/data-viewer/jobs',{cache:'no-store'}).then(r=>r.json()),cur=sel.value;sel.innerHTML='<option value="">対象を選択</option>'+(d.items||[]).map(x=>`<option value="${E(x.id)}" ${x.exists?'':'disabled'}>${E(x.name)} / ${E(formatName(x.format))}${x.exists?'':'（未出力）'}</option>`).join('');sel.value=cur}catch{showViewerError('対象一覧を取得できませんでした')}}
function showViewerError(t){$('#viewer-error').hidden=false;$('#viewer-error').textContent=t;$('#viewer-empty').hidden=true;$('#viewer-list').hidden=true;$('#viewer-analysis').hidden=true}
function fieldName(i){return viewerData?.headers?.[Number(i)]||'(空欄)'}
function numericVal(v){let t=String(v??'').replace(/,/g,'').trim();return t!==''&&!isNaN(t)?Number(t):null}

/* ---------- データ一覧（検索・並べ替え・ページング） ---------- */
function compareViewer(a,b,c,d){let x=a[c]??'',y=b[c]??'',nx=String(x).replace(/,/g,'').trim(),ny=String(y).replace(/,/g,'').trim(),xn=nx!==''&&!isNaN(nx),yn=ny!==''&&!isNaN(ny);return (xn&&yn?(+nx-+ny):String(x).localeCompare(String(y),'ja',{numeric:true}))*d}
function applyViewerSearch(){if(!viewerData)return;let q=($('#viewer-search').value||'').trim().toLowerCase();viewerFiltered=q?viewerRows.filter(r=>r.some(v=>String(v).toLowerCase().includes(q))):viewerRows.slice();if(viewerSort.col>=0)viewerFiltered.sort((a,b)=>compareViewer(a,b,viewerSort.col,viewerSort.dir));viewerPage=1;renderViewerList();if(viewerView!=='list')renderAnalysis()}
function sortViewer(c){viewerSort=viewerSort.col===c?{col:c,dir:-viewerSort.dir}:{col:c,dir:1};applyViewerSearch()}
function renderViewerList(){if(!viewerData)return;let pages=Math.max(1,Math.ceil(viewerFiltered.length/VIEWER_PAGE_SIZE));viewerPage=Math.max(1,Math.min(pages,viewerPage));let start=(viewerPage-1)*VIEWER_PAGE_SIZE,rows=viewerFiltered.slice(start,start+VIEWER_PAGE_SIZE);$('#viewer-head').innerHTML='<tr><th class="viewer-rownum">No.</th>'+viewerData.headers.map((h,i)=>`<th class="viewer-sortable ${viewerSort.col===i?'sorted':''}" data-col="${i}">${E(h||'(空欄)')}<span>${viewerSort.col===i?(viewerSort.dir>0?'▲':'▼'):''}</span></th>`).join('')+'</tr>';$('#viewer-body').innerHTML=rows.length?rows.map((r,n)=>`<tr><td class="viewer-rownum">${start+n+1}</td>`+viewerData.headers.map((_,i)=>`<td title="${E(r[i]??'')}">${E(r[i]??'')}</td>`).join('')+'</tr>').join(''):`<tr><td class="viewer-nohit" colspan="${viewerData.headers.length+1}">一致するデータはありません</td></tr>`;$$('#viewer-head .viewer-sortable').forEach(x=>x.onclick=()=>sortViewer(+x.dataset.col));$('#viewer-page').textContent=`${viewerPage} / ${pages}`;$('#viewer-prev').disabled=viewerPage<=1;$('#viewer-next').disabled=viewerPage>=pages;$('#viewer-filter-summary').textContent=`${viewerFiltered.length.toLocaleString()} / ${viewerRows.length.toLocaleString()}行`}

/* ---------- 3タブ切替 ---------- */
function setViewerView(view){viewerView=view;['list','pivot','chart'].forEach(v=>$('#vtab-'+v)?.classList.toggle('on',v===view));let has=!!viewerData;$('#viewer-empty').hidden=has;$('#viewer-list').hidden=!has||view!=='list';$('#viewer-analysis').hidden=!has||view==='list';$('#chart-type-wrap').hidden=view!=='chart';if(!has)return;if(view==='list'){renderViewerList();return}$('#analysis-pivot-result').hidden=view!=='pivot';$('#analysis-chart-result').hidden=view!=='chart';buildPivotFields();renderAnalysis()}

/* ---------- カラムリスト & ドロップゾーン ---------- */
function usedRole(i){for(const r of['rows','columns','values'])if(pivotState[r].includes(i))return r;return null}
function buildPivotFields(){if(!viewerData)return;let q=($('#pivot-field-search')?.value||'').toLowerCase();let b=$('#pivot-field-list');b.innerHTML=viewerData.headers.map((h,i)=>({h:h||'(空欄)',i})).filter(x=>!q||x.h.toLowerCase().includes(q)).map(x=>{let ur=usedRole(x.i),tag=ur?`<span class="fl-tag t-${ur}">${ur==='rows'?'行':ur==='columns'?'列':'値'}</span>`:'';return `<button type="button" draggable="true" data-col="${x.i}" class="${ur?'used':''}"><i>⋮⋮</i><span class="fl-name">${E(x.h)}</span>${tag}</button>`}).join('');bindDraggables(b)}
function bindDraggables(root){root.querySelectorAll('[draggable][data-col]').forEach(x=>{x.ondragstart=e=>{e.dataTransfer.setData('text/plain',x.dataset.col);e.dataTransfer.setData('role',x.dataset.role||'');e.dataTransfer.effectAllowed='copyMove'}})}
function renderAxis(role){let zone=$('#pivot-'+role),arr=pivotState[role];let ph={rows:'行に展開するカラムをドロップ',columns:'列に展開するカラムをドロップ（任意）',values:'件数以外はここへ'}[role];zone.innerHTML=arr.length?arr.map((i,n)=>`<div class="chip-field" draggable="true" data-col="${i}" data-role="${role}" data-pos="${n}"><em>${n+1}</em><span class="cf-name" title="${E(fieldName(i))}">${E(fieldName(i))}</span><b data-remove="1" title="外す">×</b></div>`).join(''):`<span class="axis-ph">${ph}</span>`;bindDraggables(zone);zone.querySelectorAll('[data-remove]').forEach(b=>b.onclick=e=>{e.stopPropagation();let p=Number(b.parentElement.dataset.pos);pivotState[role].splice(p,1);refreshDesigner()})}
function refreshDesigner(){['rows','columns','values'].forEach(renderAxis);buildPivotFields();renderAnalysis()}
function addPivotField(role,index){index=Number(index);if(Number.isNaN(index))return;['rows','columns','values'].forEach(r=>{let p=pivotState[r].indexOf(index);if(p>=0)pivotState[r].splice(p,1)});if(role==='values')pivotState.values=[index];else pivotState[role].push(index);refreshDesigner()}

/* ---------- ピボット集計エンジン（階層・小計・総計） ---------- */
function leafIdsForPath(fp,depth){if(depth===0)return['ALL:'];const ids=['D:'+fp.join(PSEP)];for(let p=1;p<depth;p++)ids.push('S:'+fp.slice(0,p).join(PSEP));ids.push('G:');return ids}
function buildLeaves(records,fields,opts){opts=opts||{};const showSub=opts.subtotals!==false,showGrand=opts.grand!==false;if(!fields.length)return[{id:'ALL:',path:[],type:'all'}];const root=new Map();for(const rec of records){let node=root;for(const f of fields){const k=String(rec[f]??'');let nx=node.get(k);if(!nx){nx=new Map();node.set(k,nx)}node=nx}}const leaves=[];(function walk(node,prefix){const keys=[...node.keys()].sort((a,b)=>a.localeCompare(b,'ja',{numeric:true}));for(const k of keys){const path=[...prefix,k];if(path.length===fields.length)leaves.push({id:'D:'+path.join(PSEP),path,type:'data'});else{walk(node.get(k),path);if(showSub)leaves.push({id:'S:'+path.join(PSEP),path,type:'subtotal'})}}})(root,[]);if(showGrand)leaves.push({id:'G:',path:[],type:'grand'});return leaves}
function newAcc(){return{n:0,sn:0,sum:0,min:Infinity,max:-Infinity}}
function accAdd(a,raw,isCount){a.n++;if(!isCount){const num=numericVal(raw);if(num!==null){a.sn++;a.sum+=num;if(num<a.min)a.min=num;if(num>a.max)a.max=num}}}
function aggFromAcc(a,kind){if(!a)return null;if(kind==='count')return a.n;if(a.sn===0)return null;if(kind==='sum')return a.sum;if(kind==='avg')return a.sum/a.sn;if(kind==='min')return a.min;if(kind==='max')return a.max;return null}
function buildPivot(records,rowFields,colFields,value,kind,opts){const rowLeaves=buildLeaves(records,rowFields,opts),colLeaves=buildLeaves(records,colFields,opts),cells=new Map(),isCount=(kind==='count');for(const rec of records){const rFull=rowFields.map(f=>String(rec[f]??'')),cFull=colFields.map(f=>String(rec[f]??''));const rIds=leafIdsForPath(rFull,rowFields.length),cIds=leafIdsForPath(cFull,colFields.length),raw=isCount?1:rec[value];for(const ri of rIds)for(const ci of cIds){const key=ri+CSEP+ci;let a=cells.get(key);if(!a){a=newAcc();cells.set(key,a)}accAdd(a,raw,isCount)}}return{rowLeaves,colLeaves,cell:(rid,cid)=>aggFromAcc(cells.get(rid+CSEP+cid),kind)}}

/* ---------- 見出しのスパン計算（列＝横方向 / 行＝縦方向） ---------- */
function buildColHeaderRows(colLeaves,C,rowFieldNames,measureLabel){if(C===0){let cells=rowFieldNames.map(n=>({label:n,cls:'pivot-corner',rowspan:1,colspan:1}));cells.push({label:measureLabel,cls:'pivot-measure',rowspan:1,colspan:1});return[cells]}const rows=[];for(let L=0;L<C;L++){const cells=[];if(L===0&&rowFieldNames.length)cells.push({label:rowFieldNames.join('\n'),cls:'pivot-corner',rowspan:C,colspan:rowFieldNames.length});let i=0;while(i<colLeaves.length){const leaf=colLeaves[i];if(leaf.type==='grand'){if(L===0)cells.push({label:'総計',cls:'pivot-grand-h',rowspan:C,colspan:1});i++;continue}const hasGroup=(leaf.type==='data')||(leaf.type==='subtotal'&&L<leaf.path.length);if(hasGroup){const pref=leaf.path.slice(0,L+1).join(PSEP);let j=i;while(j<colLeaves.length){const lf=colLeaves[j],hg=(lf.type==='data')||(lf.type==='subtotal'&&L<lf.path.length);if(!hg)break;if(lf.path.slice(0,L+1).join(PSEP)!==pref)break;j++}cells.push({label:leaf.path[L]||'(空欄)',cls:'pivot-col-h',rowspan:1,colspan:j-i});i=j}else{const p=leaf.path.length;cells.push({label:(leaf.path[p-1]||'(空欄)')+' 小計',cls:'pivot-sub-h',rowspan:C-p,colspan:1});i++}}rows.push(cells)}return rows}
function computeRowHeaderCells(rowLeaves,R){const out=rowLeaves.map(()=>[]);for(let L=0;L<R;L++){let i=0;while(i<rowLeaves.length){const leaf=rowLeaves[i];if(leaf.type==='grand'){if(L===0)out[i].push({label:'総計',cls:'pivot-grand-h',colspan:R,rowspan:1,order:0});i++;continue}const hasGroup=(leaf.type==='data')||(leaf.type==='subtotal'&&L<leaf.path.length);if(!hasGroup){if(leaf.type==='subtotal'&&leaf.path.length===L)out[i].push({label:(leaf.path[L-1]||'(空欄)')+' 小計',cls:'pivot-sub-h',colspan:R-L,rowspan:1,order:L});i++;continue}const pref=leaf.path.slice(0,L+1).join(PSEP);let j=i;while(j<rowLeaves.length){const lf=rowLeaves[j],hg=(lf.type==='data')||(lf.type==='subtotal'&&L<lf.path.length);if(!hg)break;if(lf.path.slice(0,L+1).join(PSEP)!==pref)break;j++}out[i].push({label:leaf.path[L]||'(空欄)',cls:'pivot-row-h',rowspan:j-i,colspan:1,order:L});i=j}}out.forEach(cs=>cs.sort((a,b)=>a.order-b.order));return out}

/* ---------- 表示（数値整形） ---------- */
function pivotFormat(v){if(v===null||v===undefined||v==='')return '';if(typeof v!=='number')return String(v);return Number.isInteger(v)?v.toLocaleString():v.toLocaleString(undefined,{maximumFractionDigits:3})}
function cellClass(rleaf,cleaf){let c=[];if(rleaf.type==='grand')c.push('col-x');if(cleaf.type==='grand')c.push('col-grand');if(cleaf.type==='subtotal')c.push('col-subtotal');return c.join(' ')}

/* ---------- 集計表・グラフの描画 ---------- */
function renderAnalysis(){if(!viewerData)return;pivotState.aggregate=$('#pivot-aggregate').value;pivotState.showSubtotals=$('#pivot-show-subtotal')?$('#pivot-show-subtotal').checked:(pivotState.showSubtotals!==false);pivotState.showGrandTotal=$('#pivot-show-grand')?$('#pivot-show-grand').checked:(pivotState.showGrandTotal!==false);let kind=pivotState.aggregate,value=pivotState.values[0]??null;let hint=$('#pivot-hint');if(!pivotState.rows.length&&!pivotState.columns.length){hint.textContent='「行」に1つ以上カラムを配置してください。1つでも配置すれば値ごとの件数（グルーピング集計）を表示します。';$('#pivot-head').innerHTML='';$('#pivot-body').innerHTML='';$('#pivot-chart').innerHTML='<div class="chart-empty">行にカラムを配置すると集計を表示します。</div>';return}
 if(!pivotState.rows.length){hint.textContent='「行」に少なくとも1つカラムを配置してください（列だけの集計は行へ移してください）。';$('#pivot-head').innerHTML='';$('#pivot-body').innerHTML='';$('#pivot-chart').innerHTML='<div class="chart-empty">行にカラムを配置してください。</div>';return}
 if(kind!=='count'&&value===null){hint.textContent='カウント以外の集計では「値」へ数値カラムを配置してください。';$('#pivot-head').innerHTML='';$('#pivot-body').innerHTML='';$('#pivot-chart').innerHTML='<div class="chart-empty">値へ数値カラムを配置してください。</div>';return}
 let measureLabel=kind==='count'?'件数':`${fieldName(value)} の${AGG_LABEL[kind]}`;
 let opts={subtotals:pivotState.showSubtotals!==false,grand:pivotState.showGrandTotal!==false};
 let model=buildPivot(viewerFiltered,pivotState.rows,pivotState.columns,value,kind,opts);
 let rowData=model.rowLeaves.filter(l=>l.type==='data').length,colData=model.colLeaves.filter(l=>l.type==='data'||l.type==='all').length;
 let totalsNote=[opts.subtotals?'小計':'',opts.grand?'総計':''].filter(Boolean).join('・')||'小計・総計なし';
 hint.textContent=`行グループ ${rowData} × 列グループ ${colData} / 集計: ${measureLabel}（${totalsNote}）`;
 renderPivotTable(model,measureLabel);renderPivotChart(model,measureLabel)}
function renderPivotTable(model,measureLabel){let R=pivotState.rows.length,C=pivotState.columns.length;let rowNames=pivotState.rows.map(fieldName);let headRows=buildColHeaderRows(model.colLeaves,C,rowNames,measureLabel);$('#pivot-head').innerHTML=headRows.map(cells=>'<tr>'+cells.map(c=>`<th class="${c.cls}" colspan="${c.colspan||1}" rowspan="${c.rowspan||1}">${E(c.label)}</th>`).join('')+'</tr>').join('');
 let rowHdr=computeRowHeaderCells(model.rowLeaves,R);
 $('#pivot-body').innerHTML=model.rowLeaves.map((rleaf,ri)=>{let trcls=rleaf.type==='subtotal'?'row-subtotal':rleaf.type==='grand'?'row-grand':'';let ths=rowHdr[ri].map(c=>`<th class="${c.cls}" colspan="${c.colspan||1}" rowspan="${c.rowspan||1}">${E(c.label)}</th>`).join('');let tds=model.colLeaves.map(cleaf=>{let v=model.cell(rleaf.id,cleaf.id),cls=cellClass(rleaf,cleaf),txt=pivotFormat(v);return `<td class="${cls} ${txt===''?'pivot-cell-empty':''}">${E(txt)}</td>`}).join('');return `<tr class="${trcls}">${ths}${tds}</tr>`}).join('')}
function renderPivotChart(model,measureLabel){let box=$('#pivot-chart');let cats=model.rowLeaves.filter(l=>l.type==='data');let sers=model.colLeaves.filter(l=>l.type==='data'||l.type==='all');if(!cats.length){box.innerHTML='<div class="chart-empty">グラフ化できる行グループがありません。</div>';return}
 let CATMAX=60,SERMAX=12,catTrim=cats.length>CATMAX,serTrim=sers.length>SERMAX;cats=cats.slice(0,CATMAX);sers=sers.slice(0,SERMAX);
 let serLabel=s=>s.type==='all'?measureLabel:(s.path.join(' / ')||'(空欄)');
 let matrix=cats.map(c=>sers.map(s=>{let v=model.cell(c.id,s.id);return typeof v==='number'?v:0}));
 let maxV=Math.max(1,...matrix.flat().map(v=>Math.abs(v)));
 let type=$('#chart-type').value;
 let legend=sers.length>1?`<div class="chart-legend">${sers.map((s,si)=>`<span><i style="background:${CHART_COLORS[si%CHART_COLORS.length]}"></i>${E(serLabel(s))}</span>`).join('')}</div>`:'';
 let note=(catTrim||serTrim)?`<div class="chart-legend"><span>※ 表示は先頭 ${cats.length} 行グループ${serTrim?' / '+sers.length+' 系列':''} に制限しています</span></div>`:'';
 if(type==='bar'){let body=cats.map((c,ci)=>`<div class="bar-cat"><div class="bar-cat-label" title="${E(c.path.join(' / '))}">${E(c.path.join(' / ')||'(空欄)')}</div>${sers.map((s,si)=>{let v=matrix[ci][si];return `<div class="bar-row"><span title="${E(serLabel(s))}">${E(sers.length>1?serLabel(s):measureLabel)}</span><div class="bar-track"><i style="width:${Math.abs(v)/maxV*100}%;background:${CHART_COLORS[si%CHART_COLORS.length]}"></i></div><b>${E(pivotFormat(v))}</b></div>`}).join('')}</div>`).join('');box.innerHTML=`${legend}${note}<div class="chart-scroll"><div class="bar-chart">${body}</div></div>`;return}
 if(type==='column'){let groups=cats.map((c,ci)=>`<div class="col-group"><div class="col-bars">${sers.map((s,si)=>{let v=matrix[ci][si];return `<i title="${E(serLabel(s))}: ${E(pivotFormat(v))}" style="height:${Math.abs(v)/maxV*100}%;background:${CHART_COLORS[si%CHART_COLORS.length]}"></i>`}).join('')}</div><span title="${E(c.path.join(' / '))}">${E(c.path.join(' / ')||'(空欄)')}</span></div>`).join('');box.innerHTML=`${legend}${note}<div class="chart-scroll"><div class="column-chart">${groups}</div></div>`;return}
 // line
 let w=Math.max(680,cats.length*70),h=340,padL=54,padB=48,padT=14,padR=14;let x=i=>padL+(cats.length===1?(w-padL-padR)/2:(w-padL-padR)*i/(cats.length-1));let y=v=>h-padB-(h-padB-padT)*(maxV?Math.abs(v)/maxV:0);
 let grid=[0,.25,.5,.75,1].map(f=>{let gy=h-padB-(h-padB-padT)*f;return `<line class="chart-grid" x1="${padL}" y1="${gy}" x2="${w-padR}" y2="${gy}"/><text class="chart-axis-label" x="${padL-6}" y="${gy+3}" text-anchor="end">${E(pivotFormat(maxV*f))}</text>`}).join('');
 let lines=sers.map((s,si)=>{let pts=cats.map((c,ci)=>x(ci)+','+y(matrix[ci][si])).join(' ');let col=CHART_COLORS[si%CHART_COLORS.length];return `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2.5"/>`+cats.map((c,ci)=>`<circle cx="${x(ci)}" cy="${y(matrix[ci][si])}" r="3.2" fill="#fff" stroke="${col}" stroke-width="2"><title>${E(serLabel(s))} / ${E(c.path.join(' / '))}: ${E(pivotFormat(matrix[ci][si]))}</title></circle>`).join('')}).join('');
 let xlabels=cats.map((c,ci)=>`<text class="chart-axis-label" x="${x(ci)}" y="${h-padB+16}" text-anchor="middle">${E((c.path.join('/')||'(空欄)').slice(0,10))}</text>`).join('');
 box.innerHTML=`${legend}${note}<div class="chart-scroll"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="集計折れ線グラフ">${grid}<line class="chart-axis" x1="${padL}" y1="${h-padB}" x2="${w-padR}" y2="${h-padB}"/><line class="chart-axis" x1="${padL}" y1="${padT}" x2="${padL}" y2="${h-padB}"/>${lines}${xlabels}</svg></div>`}

/* ---------- 読み込み ---------- */
async function openViewer(){let id=$('#viewer-job').value;if(!id)return;showWaiting('データを読み込み中','公開済みファイルを読み取り専用で確認しています...');try{let d=await fetch('/api/data-viewer/'+encodeURIComponent(id),{cache:'no-store'}).then(r=>r.json());if(!d.ok)return showViewerError(d.error);viewerData=d;viewerRows=d.rows||[];viewerFiltered=viewerRows.slice();viewerSort={col:-1,dir:1};viewerPage=1;pivotState={rows:[],columns:[],values:[],aggregate:'count',showSubtotals:($('#pivot-show-subtotal')?$('#pivot-show-subtotal').checked:true),showGrandTotal:($('#pivot-show-grand')?$('#pivot-show-grand').checked:true)};$('#pivot-aggregate').value='count';$('#viewer-error').hidden=true;$('#viewer-meta').hidden=false;$('#viewer-name').textContent=d.name;$('#viewer-name').title=d.name;$('#viewer-format').textContent=formatName(d.format);$('#viewer-count').textContent=`${Number(d.total_rows??viewerRows.length).toLocaleString()}行 × ${d.headers.length}列`;$('#viewer-modified').textContent=(d.modified||'').replace('T',' ');$('#viewer-search').value='';$('#viewer-note').textContent=d.truncated?`先頭${Number(d.preview_limit).toLocaleString()}行を表示（全${Number(d.total_rows).toLocaleString()}行）`:d.path;refreshDesigner();renderViewerList();setViewerView('list')}catch{showViewerError('データを読み込めませんでした')}finally{hideWaiting()}}

/* ---------- イベント結線 ---------- */
if($('#viewer-load'))$('#viewer-load').onclick=openViewer;
if($('#viewer-job'))$('#viewer-job').onchange=()=>{$('#viewer-job').value&&openViewer()};
if($('#viewer-search'))$('#viewer-search').oninput=applyViewerSearch;
if($('#viewer-prev'))$('#viewer-prev').onclick=()=>{viewerPage--;renderViewerList()};
if($('#viewer-next'))$('#viewer-next').onclick=()=>{viewerPage++;renderViewerList()};
['list','pivot','chart'].forEach(v=>{let b=$('#vtab-'+v);if(b)b.onclick=()=>setViewerView(v)});
if($('#pivot-field-search'))$('#pivot-field-search').oninput=buildPivotFields;
$$('.viewer-v118 .axis-drop').forEach(z=>{z.ondragover=e=>{e.preventDefault();z.classList.add('over')};z.ondragleave=()=>z.classList.remove('over');z.ondrop=e=>{e.preventDefault();z.classList.remove('over');addPivotField(z.dataset.role,e.dataTransfer.getData('text/plain'))}});
if($('#pivot-aggregate'))$('#pivot-aggregate').onchange=()=>{pivotState.aggregate=$('#pivot-aggregate').value;renderAnalysis()};
if($('#chart-type'))$('#chart-type').onchange=renderAnalysis;
if($('#pivot-clear'))$('#pivot-clear').onclick=()=>{pivotState={rows:[],columns:[],values:[],aggregate:$('#pivot-aggregate').value,showSubtotals:($('#pivot-show-subtotal')?$('#pivot-show-subtotal').checked:true),showGrandTotal:($('#pivot-show-grand')?$('#pivot-show-grand').checked:true)};refreshDesigner()};
if($('#pivot-show-subtotal'))$('#pivot-show-subtotal').onchange=()=>{pivotState.showSubtotals=$('#pivot-show-subtotal').checked;renderAnalysis()};
if($('#pivot-show-grand'))$('#pivot-show-grand').onchange=()=>{pivotState.showGrandTotal=$('#pivot-show-grand').checked;renderAnalysis()};
if($('#pivot-export'))$('#pivot-export').onclick=exportPivot;
/* ---------- 集計結果のファイル出力（CSV / TXT / EXCEL）。現在の小計・総計の表示設定を反映した集計結果を出力する。 ---------- */
function buildFlatPivotMatrix(){
 if(!viewerData)return null;
 let kind=pivotState.aggregate,value=pivotState.values[0]??null;
 if(!pivotState.rows.length)return null;
 if(kind!=='count'&&value===null)return null;
 let measureLabel=kind==='count'?'件数':`${fieldName(value)} の${AGG_LABEL[kind]}`;
 let opts={subtotals:pivotState.showSubtotals!==false,grand:pivotState.showGrandTotal!==false};
 let model=buildPivot(viewerFiltered,pivotState.rows,pivotState.columns,value,kind,opts);
 let R=pivotState.rows.length,C=pivotState.columns.length,rowNames=pivotState.rows.map(fieldName);
 let colLabel=cl=>cl.type==='all'?measureLabel:cl.type==='grand'?'総計':cl.type==='subtotal'?((cl.path[cl.path.length-1]||'(空欄)')+' 小計'):(cl.path.join(' / ')||'(空欄)');
 let header=rowNames.map(n=>n||'(空欄)');
 if(C===0)header.push(measureLabel);else model.colLeaves.forEach(cl=>header.push(colLabel(cl)));
 let matrix=[header];
 model.rowLeaves.forEach(rl=>{
  let cells=[];
  if(rl.type==='grand'){cells.push('総計');for(let k=1;k<R;k++)cells.push('');}
  else if(rl.type==='subtotal'){let p=rl.path.length;for(let k=0;k<R;k++){if(k<p-1)cells.push(rl.path[k]||'(空欄)');else if(k===p-1)cells.push((rl.path[k]||'(空欄)')+' 小計');else cells.push('');}}
  else{for(let k=0;k<R;k++)cells.push(rl.path[k]!==undefined?(rl.path[k]||'(空欄)'):'');}
  model.colLeaves.forEach(cl=>{let v=model.cell(rl.id,cl.id);cells.push(v===null||v===undefined?'':(typeof v==='number'?String(v):String(v)));});
  matrix.push(cells);
 });
 return {matrix};
}
async function exportPivot(){
 let built=buildFlatPivotMatrix();
 if(!built){toast('先に「行」（必要に応じて「値」）を配置してください');return}
 let fmt=$('#pivot-export-format')?$('#pivot-export-format').value:'csv',base=(viewerData&&viewerData.name)||'集計結果';
 showWaiting('集計結果を出力中','ファイルを作成しています...');
 try{
  let r=await fetch('/api/data-viewer/export-pivot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({format:fmt,matrix:built.matrix,name:base})});
  if(!r.ok){let d=await r.json().catch(()=>({}));toast(d.error||'出力に失敗しました');return}
  let blob=await r.blob(),cd=r.headers.get('Content-Disposition')||'',m=cd.match(/filename\*=UTF-8''([^;]+)/),fname=m?decodeURIComponent(m[1]):`${base}.${fmt}`;
  let url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=fname;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);
  toast('集計結果を出力しました');
 }catch{toast('出力に失敗しました')}finally{hideWaiting()}
}
