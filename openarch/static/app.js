'use strict';
const $=id=>document.getElementById(id);
let config,project=null,currentTab='sources',selectedPages=new Set(),page=null,points=[],pageImage=null;
const labels={width:'Facade width',depth:'Building depth',eaves:'Eaves height',roof_rise:'Roof rise',wall_thickness:'Wall thickness'};
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function error(e){$('error').textContent=e.message||String(e);$('error').hidden=false;}
async function api(url,method='GET',body){
  const headers={};if(method!=='GET')headers['X-Openarch-Token']=config.token;
  if(body && !(body instanceof FormData)){headers['Content-Type']='application/json';body=JSON.stringify(body);}
  const r=await fetch(url,{method,headers,body});const data=await r.json();
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;
}
function guard(fn){return async e=>{try{$('error').hidden=true;await fn(e);}catch(err){error(err);}};}
function endpoint(path=''){return '/api/projects/'+project.id+path;}
function setTab(name){currentTab=name;for(const b of document.querySelectorAll('[data-tab]'))b.classList.toggle('active',b.dataset.tab===name);for(const p of document.querySelectorAll('.panel'))p.hidden=p.id!=='tab-'+name;}
async function projectList(){
  const list=await api('/api/projects');$('project-list').replaceChildren();
  for(const p of list){const b=node('button','project-item'+(project?.id===p.id?' active':''),p.name);b.dataset.project=p.id;b.append(node('span','',p.status.replaceAll('_',' ')));b.onclick=guard(()=>openProject(p.id));$('project-list').append(b);}
}
async function openProject(id){project=await api('/api/projects/'+id);selectedPages.clear();render();await projectList();}
function progress(){
  const busy=project.busy;$('status').textContent=project.status.replaceAll('_',' ');$('revision').textContent='Revision '+project.revision;
  $('job-progress').hidden=!busy;const ev=project.events.at(-1);$('job-stage').textContent=ev?.stage||'Processing';$('job-message').textContent=ev?.message||'';
  for(const id of ['analyze-local','cloud-analyze','save-evidence','save-balconies','save-openings','add-opening','suggest','save-json','save-page','build'])$(id).disabled=busy;
  $('build').disabled=busy||!project.quality.can_build_draft||!config.capabilities.freecad;
  $('cloud-analyze').disabled=busy||!config.capabilities.cloud;
  if(project.status==='failed'&&ev)error(new Error(ev.message));
  const item=[...$('project-list').children].find(x=>x.dataset.project===project.id);if(item)item.querySelector('span').textContent=project.status.replaceAll('_',' ');
}
function render(){
  $('welcome').hidden=true;$('workspace').hidden=false;$('project-title').textContent=project.name;$('heading-name').textContent=project.name;
  progress();renderSources();renderEvidence();renderBalconies();renderOutputs();setTab(currentTab);
}
function renderSources(){
  $('file-count').textContent='('+project.files.length+')';$('files').replaceChildren();$('files').classList.toggle('empty',!project.files.length);
  if(!project.files.length)$('files').textContent='No files yet.';
  for(const f of project.files){const row=node('div','file-row',f.name);row.append(node('span','',(f.bytes/1024/1024).toFixed(1)+' MB'));$('files').append(row);}
  $('cloud-status').textContent=config.capabilities.cloud?'Cloud adapter configured. Nothing is sent until you opt in and start a cloud job.':'Cloud adapter is off. Configure OPENAI_API_KEY and OPENAI_MODEL on the local server to use it.';
  $('page-grid').replaceChildren();
  for(const p of project.pages){const card=node('article','page-card');const b=node('button');b.setAttribute('aria-label','Inspect page '+p.number+' '+p.kind);const img=node('img');img.src=endpoint('/pages/'+p.preview);img.alt=p.kind+' page '+p.number;b.append(img);b.onclick=()=>inspectPage(p);card.append(b);
    const label=node('label','check');const box=node('input');box.type='checkbox';box.checked=selectedPages.has(p.id);box.setAttribute('aria-label','Select page '+p.number+' for cloud analysis');box.onchange=()=>box.checked?selectedPages.add(p.id):selectedPages.delete(p.id);label.append(box,node('span','',p.kind+' · p'+p.number));card.append(label);$('page-grid').append(card);}
}
function measureCard(key,m){
  const card=node('div','measure-card');card.dataset.measure=key;const label=node('label','',labels[key]||key);const input=node('input');input.type='number';input.step='any';input.value=m.value_mm??'';input.placeholder='Unknown';input.dataset.value='true';input.setAttribute('aria-label',labels[key]||key);label.append(input);
  const check=node('label','check');const cb=node('input');cb.type='checkbox';cb.checked=m.reviewed;cb.dataset.review='true';cb.setAttribute('aria-label','Reviewed '+(labels[key]||key));check.append(cb,node('span','','Reviewed against source'));input.oninput=()=>{cb.checked=false;};
  card.append(label,node('small','',m.method+(m.source_page?' · source '+m.source_page.slice(-9):' · no source reference')),check);return card;
}
function renderEvidence(){
  const q=project.quality;$('quality').replaceChildren();for(const [num,label] of [[q.missing.length,'Missing inputs'],[q.review.length,'Items to review'],[q.conflicts.length,'Geometry conflicts']]){const c=node('div','quality-card');c.append(node('strong','',num),node('span','',label));$('quality').append(c);}
  $('measures').replaceChildren();for(const [key,label] of Object.entries(labels))$('measures').append(measureCard(key,project.spec[key]));
  $('levels').replaceChildren();for(const l of project.spec.levels)addLevelRow(l.id,l.elevation);
  $('issues').replaceChildren();for(const issue of [...q.missing.map(x=>'Missing: '+x),...q.conflicts,...q.review.map(x=>'Review: '+x)])$('issues').append(node('li','',issue));
  $('notes').replaceChildren();for(const note of project.spec.notes)$('notes').append(node('li','',note));$('spec-json').value=JSON.stringify(project.spec,null,2);
  renderOpenings();
}
function renderOpenings(){
  $('opening-rows').replaceChildren();
  for(const o of project.spec.openings)addOpeningRow(o);
  drawFacade();
}
function addOpeningRow(o){
  const row=node('tr');row.dataset.id=o.id;row.append(node('td','',o.id));
  for(const key of ['x_mm','z_mm','width_mm','height_mm','kind','reviewed']){
    const td=node('td');let input;
    if(key==='kind'){input=node('select');for(const val of ['window','door']){const opt=node('option','',val);opt.value=val;input.append(opt);}input.value=o.kind;}
    else{input=node('input');input.type=key==='reviewed'?'checkbox':'number';if(key==='reviewed')input.checked=o.reviewed;else input.value=o[key];}
    input.dataset.key=key;input.setAttribute('aria-label',key+' '+o.id);input.onchange=()=>{if(key!=='reviewed')row.querySelector('[data-key=reviewed]').checked=false;drawFacade(readOpenings());};td.append(input);row.append(td);
  }$('opening-rows').append(row);
}
function readOpenings(){return [...$('opening-rows').children].map(row=>{const old=project.spec.openings.find(o=>o.id===row.dataset.id)||{id:row.dataset.id,source_page:null,confidence:0,reviewed:false};const o={...old};for(const input of row.querySelectorAll('[data-key]'))o[input.dataset.key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;return o;});}
function drawFacade(openings=project.spec.openings){
  const canvas=$('facade-overlay'),ctx=canvas.getContext('2d');canvas.width=1200;canvas.height=500;ctx.fillStyle='#f0f3e9';ctx.fillRect(0,0,1200,500);const w=project.spec.width.value_mm,h=project.spec.eaves.value_mm;if(!w||!h){ctx.fillStyle='#718077';ctx.font='20px sans-serif';ctx.fillText('Set facade width and eaves height to preview openings.',40,250);return;}
  const scale=Math.min(1000/w,400/h),ox=(1200-w*scale)/2,base=450;ctx.fillStyle='#e2e4d8';ctx.strokeStyle='#53664d';ctx.fillRect(ox,base-h*scale,w*scale,h*scale);ctx.strokeRect(ox,base-h*scale,w*scale,h*scale);
  for(const o of openings){ctx.fillStyle='#fff';ctx.strokeStyle=o.reviewed?'#315744':'#b47b37';ctx.lineWidth=2;ctx.fillRect(ox+o.x_mm*scale,base-(o.z_mm+o.height_mm)*scale,o.width_mm*scale,o.height_mm*scale);ctx.strokeRect(ox+o.x_mm*scale,base-(o.z_mm+o.height_mm)*scale,o.width_mm*scale,o.height_mm*scale);}
  for(const b of project.spec.balconies){if(b.status==='excluded')continue;const z=project.spec.levels.find(l=>l.id===b.level_id)?.elevation.value_mm;if(z===null||z===undefined)continue;ctx.strokeStyle='#517a57';ctx.lineWidth=2;ctx.strokeRect(ox+(b.center_x_mm-b.width_mm/2)*scale,base-(z+b.guard_height_mm)*scale,b.width_mm*scale,b.guard_height_mm*scale);}
  ctx.fillStyle='#61705a';ctx.font='14px sans-serif';ctx.fillText('FRONT FACADE / DRAFT REVIEW OVERLAY',25,28);
}
function addLevelRow(id='',m={value_mm:null,reviewed:false}){
  const row=node('div','level-row');row.dataset.original=id;const name=node('input');name.value=id;name.placeholder='Level ID';name.setAttribute('aria-label','Level ID');name.dataset.key='id';
  const input=node('input');input.type='number';input.value=m.value_mm??'';input.placeholder='Elevation mm';input.setAttribute('aria-label','Elevation for '+id);input.dataset.key='elevation';
  const label=node('label','check');const cb=node('input');cb.type='checkbox';cb.checked=m.reviewed;cb.dataset.key='reviewed';label.append(cb,node('span','','Reviewed'));input.oninput=()=>cb.checked=false;row.append(name,input,label);$('levels').append(row);
}
function readMeasure(card,old){const value=card.querySelector('[data-value]').value;const n=value===''?null:Number(value);const m={...old,value_mm:n,reviewed:card.querySelector('[data-review]').checked};if(n!==old.value_mm){m.method='manual';m.source_page=null;m.confidence=0;}return m;}
async function saveSpec(spec){project=await api(endpoint('/spec'),'PUT',{revision:project.revision,spec});render();}
function renderBalconies(){
  $('balcony-rows').replaceChildren();
  for(const b of project.spec.balconies){const tr=node('tr');tr.dataset.id=b.id;tr.append(node('td','',b.id));
    for(const key of ['level_id','center_x_mm','width_mm','depth_mm','guard_height_mm','type_id','apartment','status']){
      const td=node('td');let input;
      if(['level_id','type_id','status'].includes(key)){input=node('select');const opts=key==='level_id'?project.spec.levels.map(l=>l.id):key==='type_id'?['steel_picket','solid_guard']:['proposed','reviewed','excluded'];for(const val of opts){const opt=node('option','',val);opt.value=val;input.append(opt);}input.value=b[key];}
      else{input=node('input');input.type=key==='apartment'?'text':'number';input.value=b[key];}
      input.dataset.key=key;input.setAttribute('aria-label',key+' '+b.id);input.onchange=()=>{if(key!=='status')tr.querySelector('[data-key=status]').value='proposed';};td.append(input);tr.append(td);
    }$('balcony-rows').append(tr);
  }
  if(!project.spec.balconies.length){const row=node('tr');const td=node('td','','No proposals yet. Add floor levels/openings, then suggest placements.');td.colSpan=9;row.append(td);$('balcony-rows').append(row);}
}
function runUrl(name){const run=project.runs.at(-1);return endpoint('/runs/'+run.id+'/'+name);}
function renderOutputs(){
  const caps=config.capabilities;$('build-requirements').textContent=!caps.freecad?'FreeCAD is not configured. Set FREECAD_CMD on the server.':!caps.blender?'FreeCAD ready. Configure BLENDER_EXE to add rendered images and a Blender scene.':'FreeCAD and Blender are ready. New builds keep prior exports as separate revisions.';
  const run=project.runs.at(-1);$('output-empty').hidden=!!run;$('output-content').hidden=!run;
  if(run){$('output-label').textContent=(run.draft?'DRAFT · ':'REVIEWED MODEL · ')+'Revision '+run.revision+(run.revision!==project.revision?' · Older than current edits; regenerate to update.':'');$('render-preview').hidden=!run.rendered;if(run.rendered)$('render-preview').src=runUrl('preview.png');
    $('download-links').replaceChildren();const links=[['model-package.zip','Complete model package ↗'],['building.FCStd','Editable FreeCAD model'],['drawings.pdf','Plans, elevations & section'],['building.ifc','IFC exchange model'],['balcony-register.csv','Balcony register'],['evidence-report.json','Evidence & assumptions']];if(run.rendered)links.push(['presentation.blend','Blender scene'],['building.glb','3D model · GLB']);
    for(const [name,label] of links){const a=node('a','',label);a.href=runUrl(name);a.target='_blank';a.rel='noopener';$('download-links').append(a);}$('vector-preview').src=runUrl('front.svg');}
  $('event-log').replaceChildren();for(const e of [...project.events].reverse())$('event-log').append(node('li','',new Date(e.at).toLocaleTimeString()+' · '+e.message));
}
function inspectPage(p){page=p;points=[];$('page-kind').value=p.kind;$('known-mm').value=p.calibration?.known_mm??'';$('page-text').textContent=p.text||'No text extracted. Configure local OCR or opt in to cloud interpretation.';pageImage=new Image();pageImage.onload=drawPage;pageImage.src=endpoint('/pages/'+p.preview);$('page-dialog').showModal();}
function drawPage(){const canvas=$('page-canvas');canvas.width=page.width_px;canvas.height=page.height_px;const ctx=canvas.getContext('2d');ctx.drawImage(pageImage,0,0,canvas.width,canvas.height);ctx.strokeStyle='#d26f3c';ctx.fillStyle='#d26f3c';ctx.lineWidth=3;
  for(const [x,y] of points){ctx.beginPath();ctx.arc(x,y,8,0,Math.PI*2);ctx.fill();}if(points.length===2){ctx.beginPath();ctx.moveTo(...points[0]);ctx.lineTo(...points[1]);ctx.stroke();}
  let msg=points.length+' of 2 points selected.';if(page.calibration)msg+=' Saved scale: '+page.calibration.mm_per_px.toFixed(3)+' mm/px.';
  if(points.length===2&&page.calibration)msg+=' Selected distance: '+Math.round(Math.hypot(points[1][0]-points[0][0],points[1][1]-points[0][1])*page.calibration.mm_per_px)+' mm.';$('calibration-state').textContent=msg;
}
async function localAnalyze(){await api(endpoint('/analyze'),'POST',{mode:'local',auto_build:true});project=await api(endpoint());render();}
async function init(){
  config=await api('/api/config');await projectList();
  for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>setTab(b.dataset.tab);
  for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{$('vector-preview').src=runUrl(b.dataset.view+'.svg');};
  for(const id of ['new-project','start-project'])$(id).onclick=()=>{$('new-dialog').showModal();$('project-name').focus();};$('cancel-new').onclick=()=>$('new-dialog').close();
  $('new-form').onsubmit=guard(async e=>{e.preventDefault();project=await api('/api/projects','POST',{name:$('project-name').value});$('new-dialog').close();$('new-form').reset();currentTab='sources';render();await projectList();});
  $('demo').onclick=guard(async()=>{$('demo').disabled=true;try{project=await api('/api/demo','POST');currentTab='outputs';render();await projectList();await localAnalyze();}finally{$('demo').disabled=false;}});
  $('source-files').onchange=()=>{$('selected-files').textContent=[...$('source-files').files].map(f=>f.name).join(', ');};
  $('upload-form').onsubmit=guard(async e=>{e.preventDefault();if(project.busy)throw new Error('Wait for the current job');const body=new FormData();for(const f of $('source-files').files)body.append('files',f);project=await api(endpoint('/uploads'),'POST',body);$('upload-form').reset();$('selected-files').textContent='';render();await localAnalyze();});
  $('analyze-local').onclick=guard(localAnalyze);
  $('cloud-analyze').onclick=guard(async()=>{if(!$('cloud-consent').checked)throw new Error('Opt in for this job before sending pages.');if(selectedPages.size<1||selectedPages.size>8)throw new Error('Select between 1 and 8 prepared pages.');await api(endpoint('/analyze'),'POST',{mode:'cloud',cloud_consent:true,page_ids:[...selectedPages],auto_build:true});$('cloud-consent').checked=false;project=await api(endpoint());render();});
  $('save-evidence').onclick=guard(async()=>{const spec=structuredClone(project.spec);for(const card of $('measures').children)spec[card.dataset.measure]=readMeasure(card,spec[card.dataset.measure]);spec.levels=[...$('levels').children].map(row=>{const old=project.spec.levels.find(l=>l.id===row.dataset.original)?.elevation||{value_mm:null,source_page:null,method:'unknown',confidence:0,reviewed:false};const val=row.querySelector('[data-key=elevation]').value;const value=val===''?null:Number(val);return {id:row.querySelector('[data-key=id]').value,elevation:{...old,value_mm:value,reviewed:row.querySelector('[data-key=reviewed]').checked,...(value!==old.value_mm?{method:'manual',source_page:null,confidence:0}:{})}};});await saveSpec(spec);});
  $('add-level').onclick=()=>addLevelRow();$('save-json').onclick=guard(()=>saveSpec(JSON.parse($('spec-json').value)));
  $('add-opening').onclick=()=>{addOpeningRow({id:'manual-'+crypto.randomUUID().slice(0,8),x_mm:500,z_mm:800,width_mm:1200,height_mm:1600,kind:'window',reviewed:false});drawFacade(readOpenings());};
  $('save-openings').onclick=guard(async()=>{const spec=structuredClone(project.spec);spec.openings=readOpenings();await saveSpec(spec);});
  $('suggest').onclick=guard(async()=>{project=await api(endpoint('/suggest'),'POST',{width_mm:Number($('proposal-width').value),depth_mm:Number($('proposal-depth').value),include_windows:$('include-windows').checked});render();});
  $('save-balconies').onclick=guard(async()=>{const spec=structuredClone(project.spec);for(const row of $('balcony-rows').querySelectorAll('[data-id]')){const b=spec.balconies.find(b=>b.id===row.dataset.id);for(const input of row.querySelectorAll('[data-key]'))b[input.dataset.key]=input.type==='number'?Number(input.value):input.value;}await saveSpec(spec);});
  $('build').onclick=guard(async()=>{await api(endpoint('/build'),'POST');project=await api(endpoint());render();});
  $('close-page').onclick=()=>$('page-dialog').close();$('clear-points').onclick=()=>{points=[];drawPage();};
  $('page-canvas').onclick=e=>{const rect=e.currentTarget.getBoundingClientRect();if(points.length===2)points=[];points.push([(e.clientX-rect.left)*page.width_px/rect.width,(e.clientY-rect.top)*page.height_px/rect.height]);drawPage();};
  $('save-page').onclick=guard(async()=>{if(points.length===1)throw new Error('Select the second calibration point.');project=await api(endpoint('/pages/'+page.id),'PUT',{kind:$('page-kind').value,points:points.length===2?points:null,known_mm:points.length===2?Number($('known-mm').value):null});$('page-dialog').close();render();});
  setInterval(async()=>{if(!project)return;try{const next=await api(endpoint());const changed=next.revision!==project.revision||next.pages.length!==project.pages.length||next.runs.length!==project.runs.length;project=next;if(changed)render();else progress();}catch(e){error(e);}},2000);
}
init().catch(error);
