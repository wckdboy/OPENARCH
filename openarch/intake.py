from pathlib import Path
from contextlib import nullcontext
import hashlib, uuid, re, os, subprocess, shutil
from PIL import Image, ImageOps
import pdfplumber
import pypdfium2 as pdfium
from . import storage

MAX_FILE=100*1024*1024
MAX_TOTAL=300*1024*1024
MAX_PAGES=100
ALLOWED={".pdf",".png",".jpg",".jpeg",".webp"}

def kind(text):
    s=text.lower()
    if re.search(r'\b(section|snit)\b',s):return "section"
    if re.search(r'\b(elevation|facade|facaden|facadetegning)\b',s):return "elevation"
    if re.search(r'\b(plan|floorplan|plantegning|etageplan)\b',s):return "plan"
    return "unknown"

def ocr(path):
    exe=os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not exe:return "", "No local OCR engine configured"
    result=subprocess.run([exe,str(path),"stdout","--psm","11"],capture_output=True,text=True,timeout=60,encoding="utf-8",errors="replace",creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return (result.stdout[:100000],None) if result.returncode==0 else ("","Local OCR failed")

def ingest(pid):
    """Called by the single worker: PDFium is not thread-safe."""
    state=storage.read(pid);root=storage.folder(pid);pages=[]
    old={p['id']:p for p in state['pages']}
    poppler=os.environ.get('PDFTOPPM_EXE') or shutil.which('pdftoppm')
    for src in state["files"]:
        if len(pages)>=MAX_PAGES:raise ValueError("Limit: 100 pages per project")
        path=root/"sources"/src["stored_name"]
        if path.suffix==".pdf":
            with pdfplumber.open(path) as textdoc, (nullcontext(None) if poppler else pdfium.PdfDocument(path)) as renderdoc:
                if len(textdoc.pages)+len(pages)>MAX_PAGES:raise ValueError("Limit: 100 pages per project")
                for i,page in enumerate(textdoc.pages):
                    ident=f"{src['id']}-{i+1}"
                    target=root/"pages"/(ident+".png")
                    if ident in old and target.is_file():
                        # Preserve the pixel coordinate system of saved calibration/traces.
                        with Image.open(target) as rendered:img=rendered.convert('RGB')
                    elif poppler:
                        result=subprocess.run([poppler,'-f',str(i+1),'-l',str(i+1),'-singlefile','-scale-to','2200','-png',str(path),str(target.with_suffix(''))],capture_output=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        if result.returncode or not target.is_file():raise ValueError('PDF page rendering failed')
                        with Image.open(target) as rendered:img=rendered.convert('RGB')
                    else:
                        rp=renderdoc[i];scale=min(2.2,2200/max(rp.get_size()))
                        bmp=rp.render(scale=scale);img=bmp.to_pil().convert("RGB");img.save(target)
                        bmp.close();rp.close()
                    txt=(page.extract_text() or "")[:100000];warning=None
                    if len(txt.strip())<20:txt,warning=ocr(target)
                    rects=[{"x":r['x0'],"y":r['top'],"w":r['width'],"h":r['height']} for r in page.rects[:3000] if r['width']>1 and r['height']>1]
                    pages.append({"id":ident,"file_id":src['id'],"number":i+1,"kind":kind(txt),"text":txt,"width_px":img.width,"height_px":img.height,"width_pt":page.width,"height_pt":page.height,"rects":rects,"preview":ident+".png","warning":warning,"calibration":None})
        else:
            with Image.open(path) as raw:
                if raw.width*raw.height>30_000_000:raise ValueError("Image exceeds 30 megapixels")
                img=ImageOps.exif_transpose(raw).convert("RGB");img.thumbnail((2200,2200))
                ident=src['id']+"-1";target=root/"pages"/(ident+".png");img.save(target)
                txt,warning=ocr(target)
                pages.append({"id":ident,"file_id":src['id'],"number":1,"kind":kind(txt),"text":txt,"width_px":img.width,"height_px":img.height,"width_pt":None,"height_pt":None,"rects":[],"preview":ident+".png","warning":warning,"calibration":None})
        storage.event(pid,"intake",f"Prepared {len(pages)} pages")
    for p in pages:
        if p['id'] in old:
            p['kind']=old[p['id']]['kind'];p['calibration']=old[p['id']].get('calibration')
    storage.mutate(pid,lambda s:s.update(pages=pages,pages_pending=False))
    return pages

def calibration(x1,y1,x2,y2,known_mm,width,height):
    import math
    if not all(math.isfinite(x) for x in [x1,y1,x2,y2,known_mm]):raise ValueError("Calibration must be finite")
    if not (0<=x1<=width and 0<=x2<=width and 0<=y1<=height and 0<=y2<=height):raise ValueError("Points outside image")
    distance=math.hypot(x2-x1,y2-y1)
    if distance<5 or not 10<=known_mm<=200000:raise ValueError("Choose distinct points and a valid measured length")
    return {"points":[[x1,y1],[x2,y2]],"known_mm":known_mm,"mm_per_px":known_mm/distance}
