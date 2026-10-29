'use strict';
let outline=null,outlinePage=null,outlineImage=null,activeRing=0;
function newRing(id){return {id,points:[]};}
function outlineRings(){return outline?[outline.outer,...outline.courtyards]:[];}
function footprintPage(){return project.pages.find(p=>p.id===$('footprint-page').value);}
function renderFootprint(){
  const select=$('footprint-page');select.replaceChildren();
  for(const p of project.pages){const f=project.files.find(f=>f.id===p.file_id);const opt=node('option','',(f?.name||'Source')+' · p'+p.number+' · '+p.kind);opt.value=p.id;select.append(opt);}
  outline=project.spec.footprint?structuredClone(project.spec.footprint):null;
  if(outline?.source_page)select.value=outline.source_page;
  activeRing=0;loadFootprintPage();
  $('trace-orthographic').checked=false;
  $('footprint-reviewed').checked=outline?.reviewed||false;
  $('footprint-facades').replaceChildren();
  for(const f of project.facades||[]){if(f.id==='front')continue;const item=node('li','',f.label+' · corners '+f.start_corner+' → '+f.end_corner+' · '+(f.length_mm/1000).toFixed(2)+' m');item.title=f.id;$('footprint-facades').append(item);}
}
function loadFootprintPage(){
  outlinePage=footprintPage();outlineImage=null;
  if(!outlinePage){drawFootprint();return;}
  const image=new Image(),pageId=outlinePage.id;
  image.onload=()=>{if(outlinePage?.id===pageId){outlineImage=image;drawFootprint();}};
  image.src=endpoint('/pages/'+outlinePage.preview);
}
function drawFootprint(){
  const canvas=$('footprint-canvas'),ctx=canvas.getContext('2d');canvas.width=outlinePage?.width_px||1200;canvas.height=outlinePage?.height_px||600;
  ctx.fillStyle='#e9ede3';ctx.fillRect(0,0,canvas.width,canvas.height);
  if(outlineImage)ctx.drawImage(outlineImage,0,0,canvas.width,canvas.height);
  const line=Math.max(2,canvas.width/450);
  if(outline){
    const native=outline.source_page&&outline.source_page===outlinePage?.id;
    const pts=outline.outer.points,xs=pts.map(p=>p.x),ys=pts.map(p=>p.y),minX=Math.min(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
    const scale=native?1:Math.min((canvas.width-80)/(Math.max(...xs)-minX||1),(canvas.height-80)/(maxY-minY||1));
    const point=p=>native?p:{x:40+(p.x-minX)*scale,y:40+(outline.coordinate_system==='cartesian'?maxY-p.y:p.y-minY)*scale};
    outlineRings().forEach((ring,index)=>{if(!ring.points.length)return;ctx.strokeStyle=index===0?'#e15832':'#297aa0';ctx.fillStyle=index===0?'#e1583225':'#297aa030';ctx.lineWidth=line;
      ctx.beginPath();ring.points.map(point).forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));if(ring.points.length>2)ctx.closePath();ctx.fill();ctx.stroke();
      ctx.font=`bold ${Math.max(16,canvas.width/85)}px sans-serif`;for(const [i,p] of ring.points.map(point).entries()){ctx.beginPath();ctx.arc(p.x,p.y,line*1.6,0,Math.PI*2);ctx.fillStyle=index===activeRing?'#ffcf4b':'#fff';ctx.fill();ctx.fillStyle='#162d24';ctx.fillText(String(i+1),p.x+line*2,p.y-line*2);}
    });
  }
  const ring=outlineRings()[activeRing];$('trace-state').textContent=outline?`${ring?.points.length||0} corners in active ${activeRing===0?'outer boundary':'courtyard'}. `+(outline.mm_per_unit.value_mm===null?'UNSCALED — saved as a sketch; metric model generation is blocked.':outline.mm_per_unit.value_mm.toFixed(3)+' mm/source unit · scale still needs source review.'):'Choose a source page, then start tracing its outer boundary.';
  $('trace-rings').replaceChildren();outlineRings().forEach((r,i)=>{const opt=node('option','',i===0?'Outer boundary':'Courtyard '+i);opt.value=i;$('trace-rings').append(opt);});$('trace-rings').value=activeRing;
}
function bindFootprint(){
  $('footprint-page').onchange=()=>{outline=null;activeRing=0;$('footprint-reviewed').checked=false;$('trace-orthographic').checked=false;loadFootprintPage();};
  $('trace-start').onclick=()=>{if(!outlinePage)return;outline={outer:newRing('outer'),courtyards:[],coordinate_system:'image',source_page:outlinePage.id,mm_per_unit:{value_mm:null,method:'unknown',source_page:outlinePage.id,confidence:0,reviewed:false},reviewed:false,confidence:0};activeRing=0;$('footprint-reviewed').checked=false;drawFootprint();};
  $('trace-hole').onclick=guard(()=>{if(!outline||outline.outer.points.length<3)throw new Error('Trace at least three outer corners first.');outline.courtyards.push(newRing('court-'+crypto.randomUUID().slice(0,8)));activeRing=outline.courtyards.length;outline.reviewed=false;$('footprint-reviewed').checked=false;drawFootprint();});
  $('trace-rings').onchange=()=>{activeRing=Number($('trace-rings').value);drawFootprint();};
  $('trace-undo').onclick=()=>{outlineRings()[activeRing]?.points.pop();$('footprint-reviewed').checked=false;drawFootprint();};
  $('trace-delete').onclick=()=>{if(activeRing>0){outline.courtyards.splice(activeRing-1,1);activeRing=0;$('footprint-reviewed').checked=false;drawFootprint();}};
  $('footprint-canvas').onclick=e=>{if(!outline||outline.source_page!==outlinePage?.id)return;const r=e.currentTarget.getBoundingClientRect();outlineRings()[activeRing].points.push({id:crypto.randomUUID().slice(0,8),x:Math.round((e.clientX-r.left)*e.currentTarget.width/r.width),y:Math.round((e.clientY-r.top)*e.currentTarget.height/r.height)});$('footprint-reviewed').checked=false;drawFootprint();};
  $('trace-scale').onclick=guard(()=>{if(!outline||!outlinePage?.calibration)throw new Error('Use Inspect & calibrate on this page to set a known distance first.');if(!$('trace-orthographic').checked)throw new Error('A single scale requires an orthographic drawing. Oblique imagery must be rectified first.');outline.mm_per_unit={value_mm:outlinePage.calibration.mm_per_px,method:'calibrated',source_page:outlinePage.id,confidence:.7,reviewed:false};drawFootprint();});
  $('trace-unscale').onclick=()=>{if(outline){outline.mm_per_unit.value_mm=null;outline.mm_per_unit.reviewed=false;$('footprint-reviewed').checked=false;drawFootprint();}};
  $('save-footprint').onclick=guard(async()=>{if(!outline)throw new Error('Start a trace first.');outline.reviewed=$('footprint-reviewed').checked;outline.mm_per_unit.reviewed=outline.reviewed&&outline.mm_per_unit.value_mm!==null;const spec=structuredClone(project.spec);spec.footprint=outline;await saveSpec(spec);});
}
