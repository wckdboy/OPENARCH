"""Generate a fictional fixture from scratch. No source/customer assets are used."""
from pathlib import Path
import uuid,hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from . import storage

def create_sources(root:Path):
    ident=uuid.uuid4().hex;target=root/'sources'/(ident+'.pdf')
    c=canvas.Canvas(str(target),pagesize=(297*mm,210*mm));c.setTitle('Synthetic training-free demonstration')
    c.setFont('Helvetica-Bold',16);c.drawString(15*mm,194*mm,'SYNTHETIC ELEVATION / NOT A REAL PROPERTY')
    # A deliberately invented building, drawn at 1:100.
    W,H,D=12600,10400,8200;ox,oy=25*mm,30*mm;scale=mm/100
    c.setLineWidth(.4);c.rect(ox,oy,W*scale,H*scale)
    for z in [0,3200,6400]:
        for x in [1600,5600,9600]:c.rect(ox+x*scale,oy+z*scale,1400*scale,2200*scale)
    labels=['Facade width: 12600 mm','Building depth: 8200 mm','Eaves height: 10400 mm','Roof rise: 1700 mm','Wall thickness: 380 mm','Level G: 0 mm','Level L1: 3200 mm','Level L2: 6400 mm']
    c.setFont('Helvetica',10)
    for i,label in enumerate(labels):c.drawString(180*mm,(150-i*8)*mm,label)
    c.showPage();c.setFont('Helvetica-Bold',16);c.drawString(15*mm,194*mm,'SYNTHETIC PLAN')
    c.rect(25*mm,55*mm,W*scale,D*scale);c.rect(25*mm+380*scale,55*mm+380*scale,(W-760)*scale,(D-760)*scale)
    c.setFont('Helvetica',10);c.drawString(180*mm,150*mm,'Building width: 12600 mm');c.drawString(180*mm,140*mm,'Building depth: 8200 mm');c.drawString(180*mm,130*mm,'Illustration only / 1:100');c.save()
    record={'id':ident,'name':'synthetic-drawings.pdf','stored_name':target.name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    storage.mutate(root.name,lambda s:s.update(files=[record],status='uploaded'))
