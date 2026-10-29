from pathlib import Path
import json,re,csv,hashlib,zipfile,textwrap
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from .schema import ModelSpec,quality

def cell(value):
    text=str(value)
    return "'"+text if text[:1] in '=+-@' else text

def deliverables(run:Path,spec:ModelSpec,revision:int):
    q=quality(spec);meta=json.loads((run/'geometry-validation.json').read_text());rows=json.loads((run/'balconies.json').read_text())
    with (run/'balcony-register.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['id','level_id','apartment','center_x_mm','width_mm','depth_mm','guard_height_mm','type_id','status','elevation_mm']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({k:cell(row.get(k,'')) for k in fields})
    c=canvas.Canvas(str(run/'drawings.pdf'));c.setTitle('OPENARCH - model drawings')
    ink=HexColor('#203c35');grey=HexColor('#68736e')
    def text(x,y,value,size=9):
        c.setFillColor(ink);c.setFont('Helvetica',size);c.drawString(x*mm,y*mm,value)
    def view(name,x,y,w,h):
        raw=(run/(name+'.svg')).read_text();bounds=meta['views'][name]['bounds'];bw=bounds[2]-bounds[0];bh=bounds[3]-bounds[1]
        fit_max=min(w/bw,h/bh);base=meta['views'][name]['scale'];required=1/(base*fit_max)
        denominator=next((n for n in [20,50,100,200,500,1000,2000,5000] if n>=required),10000)
        scale=1/denominator;fit=scale/base
        tx=x+(w-bw*fit)/2-bounds[0]*fit;ty=y+(h-bh*fit)/2-bounds[1]*fit
        c.saveState();c.translate(tx*mm,ty*mm);c.scale(fit,fit);c.setStrokeColor(ink);c.setLineWidth(.15*mm/fit)
        for path in re.findall(r'<path[^>]*\sd="([^"]+)"',raw):
            p=c.beginPath()
            for op,xx,yy in re.findall(r'([ML])\s+(-?[\d.]+)\s+(-?[\d.]+)',path):(p.moveTo if op=='M' else p.lineTo)(float(xx)*mm,float(yy)*mm)
            c.drawPath(p)
        c.restoreState();text(x,y-7,f'{name.upper()} / 1:{1/scale:.1f} at 100% print',10)
        bar=1000*scale;c.setLineWidth(.6*mm);c.line(x*mm,(y-12)*mm,(x+bar)*mm,(y-12)*mm);text(x,y-17,'1 m scale check',7)
        if name=='front':
            left=tx-spec.width.value_mm*scale/2;right=tx+spec.width.value_mm*scale/2
            yy=y+6;c.setLineWidth(.15*mm);c.line(left*mm,yy*mm,right*mm,yy*mm)
            for xx in [left,right]:c.line((xx-1)*mm,(yy-1)*mm,(xx+1)*mm,(yy+1)*mm)
            text((left+right)/2-9,yy+2,f'{spec.width.value_mm:g} mm',8)
            for level in spec.levels:
                ly=ty+(level.elevation.value_mm-meta['model_z_center_mm'])*scale
                text(right+3,ly,f'{level.id}: +{level.elevation.value_mm:g}',7)
    c.setPageSize((420*mm,297*mm));text(15,280,'OPENARCH / MODEL DRAWINGS',18)
    label='REVIEWED MODEL' if q['can_issue_reviewed'] else 'DRAFT - UNVERIFIED DIMENSIONS / PLACEMENTS'
    text(15,269,f'{label} / Revision {revision} / Not construction documentation',9)
    view('front',15,55,170,190);view('plan',215,173,185,72);view('section',215,55,185,86)
    text(15,17,f"Envelope: {spec.width.value_mm:g} x {spec.depth.value_mm:g} mm. Eaves: {spec.eaves.value_mm:g} mm.")
    text(15,10,'One rectangular building and one facade. Roof/trim profiles are simplified. See the evidence report for assumptions.',8)
    c.showPage();c.setPageSize((297*mm,210*mm));text(15,193,'BALCONY REGISTER / EVIDENCE',16);y=180
    text(15,y,f'{len(rows)} active placements / {q["reviewed_measurements"]} of {q["measurement_count"]} measurements reviewed. This is not an accuracy score.',9);y-=13
    for x,label in [(15,'BALCONY ID'),(100,'LEVEL'),(130,'WIDTH x DEPTH'),(195,'TYPE'),(250,'STATUS')]:text(x,y,label,8)
    y-=9
    for row in rows:
        if y<25:c.showPage();c.setPageSize((297*mm,210*mm));y=190
        text(15,y,str(row['id'])[:38],8);text(100,y,str(row['level_id'])[:15],8);text(130,y,f"{row['width_mm']:g} x {row['depth_mm']:g} mm",8);text(195,y,row['type_id'],8);text(250,y,row['status'],8);y-=7
    y-=8
    pending=[x for x in q['review'] if not x.startswith(('opening:','balcony:'))]
    notes=spec.notes+q['missing']+q['conflicts']+['Measurements to review: '+', '.join(pending),f"Openings to review: {sum(x.startswith('opening:') for x in q['review'])}. Balconies to review: {sum(x.startswith('balcony:') for x in q['review'])}.", 'Full field-level evidence and review flags are included in evidence-report.json.']
    for note in notes:
        for wrapped in textwrap.wrap(note,width=135,break_long_words=False,break_on_hyphens=False):
            if y<20:c.showPage();c.setPageSize((297*mm,210*mm));y=190
            text(15,y,wrapped,8);y-=5
    c.save()
    report={'revision':revision,'quality':q,'spec':spec.model_dump(),'limitations':['Rectangular massing and front facade only','Parametric balconies; simplified profiles and connections','Evidence completeness does not measure geometric accuracy','FreeCAD edits are not imported back into the app; edit the spec in the review screen']}
    (run/'evidence-report.json').write_text(json.dumps(report,indent=2))
    # Only generated outputs go in this download; original sources stay private.
    allowed={'building.FCStd','building.ifc','building.glb','presentation.blend','preview.png','front.svg','plan.svg','section.svg','drawings.pdf','balconies.json','balcony-register.csv','evidence-report.json','geometry-validation.json','ifc-validation.json','spec.json'}
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.name in allowed}
    (run/'manifest.json').write_text(json.dumps(manifest,indent=2))
    with zipfile.ZipFile(run/'model-package.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(set(manifest)|{'manifest.json'}):z.write(run/name,name)
