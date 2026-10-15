'use strict';
const $ = id => document.getElementById(id);
const catalog = globalThis.FH2_CATALOG;
const core = globalThis.FH2;
let SQL, session = null, files = null, manifests = null, availableRevisions = [], busy = false;
const labels = {destinations:'Destinations unlocked',events:'Regular events unlocked',perks:'Perks unlocked',discover:'Map discoveries revealed',boards:'Boards marked as collected',buckets:'Solo challenges recorded as completed',championships:'Championship history recorded as won'};
const profileFields = [['Credits','credits-input'],['XP','xp-input']];
function status(message, error=false) { $('status').textContent=message; $('status').className='status'+(error?' error':''); }
function setBusy(value) {
  busy=value; document.body.classList.toggle('is-busy',value);
  $('folder-picker').disabled=value; $('change-file').disabled=value; $('export-button').disabled=value;
  $('editor').inert=value;
}
function option(value,label) { const node=document.createElement('option');node.value=String(value);node.textContent=label;return node; }
function selectedGarage() { const input=document.querySelector('input[name=garage-choice]:checked');if(!input)throw new Error('Select a garage car.');return Number(input.value); }
function selectedCatalog() { if(!$('car-catalog').value)throw new Error('Select a catalog model.');return Number($('car-catalog').value); }
function renderGarage() {
  const selected=document.querySelector('input[name=garage-choice]:checked')?.value;
  const current=core.readProfile(session.profile,'CareerCar');
  $('garage-rows').replaceChildren();
  for(const car of session.garage()) {
    const meta=catalog.cars.find(c=>c.id===car.CarId),tr=document.createElement('tr');
    const td=document.createElement('td'),radio=document.createElement('input');radio.type='radio';radio.name='garage-choice';radio.value=String(car.Id);radio.setAttribute('aria-label',`Select garage car ${car.Id}`);radio.checked=selected?Number(selected)===car.Id:car.Id===current;td.append(radio);tr.append(td);
    for(const value of [`${meta?.name||'Model '+car.CarId} · #${car.Id}`,['D','C','B','A','S1','S2','X','R'][car.ClassID]||String(car.ClassID),car.Id===current?'Active':car.PartsValue>0?'Modified':'Garage']){const cell=document.createElement('td');cell.textContent=value;tr.append(cell);}
    $('garage-rows').append(tr);
  }
  $('garage-count').textContent=`${session.garage().length} cars`;
}
function renderCars() {
  const search=$('car-search').value.trim().toLocaleLowerCase('en-US'),old=$('car-catalog').value;
  const cars=catalog.cars.filter(c=>c.eligible && `${c.name} ${c.id}`.toLocaleLowerCase('en-US').includes(search));
  $('car-catalog').replaceChildren(...cars.map(c=>option(c.id,`${c.name} · ID ${c.id}${c.contentId?' · additional content':''}`)));
  if(cars.some(c=>String(c.id)===old))$('car-catalog').value=old;
  else if(cars.length)$('car-catalog').selectedIndex=0;
  carInfo();
}
function carInfo() {
  const car=catalog.cars.find(c=>String(c.id)===$('car-catalog').value);
  $('car-info').textContent=car?`${car.price.toLocaleString('en-US')} CR base value. Stock parts are sourced from the game database.${car.hasLivery?' Special livery: game initialization has not been verified.':''}${car.contentId?' Requires the corresponding content to be installed.':''}`:'No models found.';
  $('add-car-button').disabled=!car; $('replace-car-button').disabled=!car;
}
function renderEvents() {
  const q=$('event-search').value.trim().toLocaleLowerCase('en-US');
  const events=catalog.progression.events.filter(e=>`${e.id} ${e.name}`.toLocaleLowerCase('en-US').includes(q));
  $('event-catalog').replaceChildren(...events.map(e=>option(e.id,`#${e.id} · ${e.name} · ${e.region==='island'?'island':'mainland'}`)));
  if(events.length)$('event-catalog').selectedIndex=0;
  $('unlock-event-button').disabled=!events.length;
}
function renderProgress() {
  const counters=[['Career_EventUnlock','event unlock records'],['Career_DestinationUnlock','destinations'],['Career_ChampionshipsWon','championships won'],['PerkUnlock','perks']];
  $('progress-stats').replaceChildren(...counters.map(([t,label])=>{const e=document.createElement('span');e.textContent=`${session.count(t)} ${label}`;return e;}));
}
function renderStoryProperties() {
  const object=session.xml.objects.get($('story-object').value);
  $('story-property').replaceChildren(...Array.from(object.props,([key])=>option(key,key)));
  renderStoryValue();
}
function renderStoryValue() {
  const id=$('story-object').value,name=$('story-property').value,value=session.xml.get(id,name);
  const editable=/^(true|false|-?\d+)$/.test(value);
  $('story-value').value=value;$('story-value').disabled=!editable;$('story-apply').disabled=!editable;
  $('story-current').textContent=editable?`Prepared value: ${value}. Booleans use true or false; IDs must be numbers.`:`Value ${value}: read-only enumeration.`;
}
function renderChanges() {
  $('change-log').replaceChildren(...session.log.map(item=>{const li=document.createElement('li');li.textContent=labels[item.replace('Applied: ','')]||item;return li;}));
  const pending=profileFields.filter(([n,id])=>String(core.readProfile(session.profile,n))!==$(id).value).length + Number(session.xml.get('TombolaState','Spins')!==$('spins-input').value) + Number(session.xml.get('skills','CurrentSkillTokensTotal')!==$('skills-input').value);
  $('change-summary').textContent=`${session.log.length} actions applied to this copy; ${pending} profile fields will be applied on export.`;
}
function showSession() {
  for(const [name,id] of profileFields)$(id).value=core.readProfile(session.profile,name);
  $('spins-input').value=session.xml.get('TombolaState','Spins');$('skills-input').value=session.xml.get('skills','CurrentSkillTokensTotal');
  $('loaded-name').textContent=session.revision.user.split('/')[0];
  $('loaded-meta').textContent=`Revision ${session.revision.id} · ${files.size} files · integrity verified`;
  $('loaded-file').classList.remove('hidden');$('dropzone').classList.add('hidden');$('editor').classList.remove('hidden');
  renderGarage();renderProgress();renderStoryProperties();renderChanges();
}
function replaceSession(revision) {
  const next=new core.SaveSession(SQL,files,revision,manifests,catalog);
  session?.close();session=next;showSession();
}
async function loadSelection(selectedFiles) {
  if(busy)return;
  setBusy(true);status('Checking backup files and hashes…');
  try {
    let total=0;const nextFiles=new Map();
    for(const {file,path} of selectedFiles) {
      core.safePath(path);total+=file.size;
      if(total>256*1024*1024 || nextFiles.size>=10000)throw new Error('Backup exceeds the local limit of 256 MB or 10,000 files.');
      if(nextFiles.has(path))throw new Error('Duplicate path in backup.');
      nextFiles.set(path,new Uint8Array(await file.arrayBuffer()));
    }
    const nextManifests=await core.validateManifests(nextFiles), nextRevisions=core.revisions(nextManifests);
    if(!nextRevisions.length)throw new Error('Backup has no complete profile revision.');
    if(new Set(nextRevisions.map(r=>r.user)).size!==1)throw new Error('Select player-1 containing a single User_ profile.');
    const next=new core.SaveSession(SQL,nextFiles,nextRevisions[0],nextManifests,catalog);
    session?.close();session=next;files=nextFiles;manifests=nextManifests;availableRevisions=nextRevisions;
    $('revision-picker').replaceChildren(...availableRevisions.map((r,i)=>option(r.id,`${r.id}${i===0?' · latest':''}`)));
    showSession();status('Backup verified. Changes will only be saved to the exported copy.');
  } catch(error) {status(error.message,true);}
  finally {setBusy(false);$('folder-picker').value='';}
}
function action(fn) {if(busy||!session)return;try{fn();renderGarage();renderProgress();renderChanges();status('Change prepared in memory. Export the ZIP to save your copy.');}catch(e){status(e.message,true);}}
$('folder-picker').addEventListener('change',()=>{if($('folder-picker').files.length)loadSelection(Array.from($('folder-picker').files,file=>({file,path:file.webkitRelativePath})));});
$('change-file').addEventListener('click',()=>$('folder-picker').click());
$('revision-picker').addEventListener('change',()=>{if(busy)return;try{replaceSession(availableRevisions.find(r=>r.id===$('revision-picker').value));status('Revision loaded. Previous edits were discarded.');}catch(e){$('revision-picker').value=session.revision.id;status(e.message,true);}});
$('reset-button').addEventListener('click',()=>{if(!busy){replaceSession(session.revision);status('Changes discarded; original data restored in memory.');}});
for(const button of document.querySelectorAll('[data-tab]'))button.addEventListener('click',()=>{for(const b of document.querySelectorAll('[data-tab]'))b.classList.toggle('selected',b===button);for(const p of document.querySelectorAll('.tab-panel'))p.classList.toggle('hidden',p.id!=='tab-'+button.dataset.tab);});
$('car-search').addEventListener('input',renderCars);$('car-catalog').addEventListener('change',carInfo);
$('event-search').addEventListener('input',renderEvents);
$('add-car-button').addEventListener('click',()=>action(()=>session.addStock(selectedCatalog())));
$('replace-car-button').addEventListener('click',()=>action(()=>session.addStock(selectedCatalog(),selectedGarage())));
$('duplicate-car-button').addEventListener('click',()=>action(()=>session.duplicateCar(selectedGarage())));
$('current-car-button').addEventListener('click',()=>action(()=>session.setCurrentCar(selectedGarage())));
for(const button of document.querySelectorAll('[data-preset]'))button.addEventListener('click',()=>action(()=>session.applyPreset(button.dataset.preset)));
$('unlock-event-button').addEventListener('click',()=>action(()=>session.unlockEvent($('event-catalog').value)));
$('story-object').addEventListener('change',renderStoryProperties);$('story-property').addEventListener('change',renderStoryValue);
$('story-apply').addEventListener('click',()=>action(()=>{session.setStoryProperty($('story-object').value,$('story-property').value,$('story-value').value);renderStoryValue();}));
for(const id of ['credits-input','spins-input','xp-input','skills-input'])$(id).addEventListener('input',()=>{if(session)renderChanges();});
$('export-button').addEventListener('click',async()=>{
  if(busy||!session)return;setBusy(true);status('Validating changes and building ZIP…');
  try {
    const values=profileFields.map(([n,id])=>[n,core.integer($(id).value,n,2147483647)]);
    const spins=core.integer($('spins-input').value,'Wheelspins'),skills=core.integer($('skills-input').value,'Skill tokens');
    for(const [name,n] of values)session.setProfile(name,n);
    session.setSpins(spins);session.setSkillTokens(skills);
    const result=await session.exportFiles(),blob=core.makeZip(result),url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=`fh2-edited-${session.revision.id}.zip`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    renderChanges();status('ZIP exported and integrity verified. Progress features other than perks still need in-game testing.');
  }catch(error){status(error.message,true);}finally{setBusy(false);}
});
async function droppedFiles(entry,prefix='') {
  if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));return[{file,path:prefix+entry.name}];}
  if(!entry.isDirectory)return[];const reader=entry.createReader(),all=[];
  while(true){const batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!batch.length)break;for(const child of batch)all.push(...await droppedFiles(child,prefix+entry.name+'/'));}
  return all;
}
$('dropzone').addEventListener('keydown',e=>{if(!busy&&(e.key==='Enter'||e.key===' ')){e.preventDefault();$('folder-picker').click();}});
for(const name of ['dragenter','dragover'])$('dropzone').addEventListener(name,e=>{e.preventDefault();if(!busy)$('dropzone').classList.add('dragging');});
for(const name of ['dragleave','drop'])$('dropzone').addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.remove('dragging');});
$('dropzone').addEventListener('drop',async e=>{if(busy)return;try{const entries=Array.from(e.dataTransfer.items).map(i=>i.webkitGetAsEntry?.()).filter(Boolean),selected=[];for(const entry of entries)selected.push(...await droppedFiles(entry));if(selected.length)await loadSelection(selected);}catch(error){status(error.message,true);}});
setBusy(true);
initSqlJs().then(module=>{SQL=module;renderCars();renderEvents();setBusy(false);status('Ready. Select your player-1 backup folder.');}).catch(error=>{status(`Could not initialize SQLite: ${error.message}`,true);});
