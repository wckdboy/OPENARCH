from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import secrets,json,uuid,hashlib,os
from fastapi import FastAPI,UploadFile,File,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import Field
from .schema import Strict,ModelSpec,quality
from . import storage,pipeline
from .intake import ALLOWED,MAX_FILE,MAX_TOTAL,calibration
from .extract import suggest_balconies

TOKEN=secrets.token_urlsafe(32)
STATIC=Path(__file__).resolve().parent/'static'
@asynccontextmanager
async def lifespan(app):
    storage.recover_interrupted()
    yield

app=FastAPI(title='OPENARCH',docs_url=None,redoc_url=None,lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

@app.middleware('http')
async def local_boundary(request:Request,call_next):
    if request.method not in ['GET','HEAD','OPTIONS']:
        if not secrets.compare_digest(request.headers.get('X-Openarch-Token',''),TOKEN):return JSONResponse({'detail':'Invalid local session token'},403)
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):return JSONResponse({'detail':'Cross-origin mutation blocked'},403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

@app.exception_handler(ValueError)
async def invalid(request,exc):return JSONResponse({'detail':str(exc)[:700]},422)
@app.exception_handler(FileNotFoundError)
async def missing(request,exc):return JSONResponse({'detail':'Project or file not found'},404)

def public_state(s):
    value=dict(s);value['quality']=quality(ModelSpec.model_validate(s['spec']))
    # OCR text is available in the review screen, but filesystem paths never are.
    return value

def idle(pid):
    if storage.read(pid)['busy']:raise HTTPException(409,'Wait for the running job')

@app.get('/api/config')
def config():return {'token':TOKEN,'capabilities':pipeline.capabilities(),'version':'0.1.0','privacy':'Local storage; cloud disabled unless explicitly selected per job'}

class NewProject(Strict):
    name:str=Field(min_length=1,max_length=100)
@app.post('/api/projects')
def new_project(data:NewProject):return public_state(storage.create(data.name.strip()))
@app.get('/api/projects')
def projects():
    result=[]
    for p in storage.data_root().glob('*/project.json'):
        s=json.loads(p.read_text(encoding='utf-8'));result.append({k:s.get(k) for k in ['id','name','status','created_at','updated_at','revision','busy']})
    return sorted(result,key=lambda s:s.get('updated_at') or s['created_at'],reverse=True)
@app.get('/api/projects/{pid}')
def project(pid:str):return public_state(storage.read(pid))

@app.post('/api/projects/{pid}/uploads')
async def uploads(pid:str,files:list[UploadFile]=File(...)):
    idle(pid);state=storage.read(pid)
    if len(files)+len(state['files'])>30:raise HTTPException(413,'Maximum 30 source files')
    storage.acquire(pid)
    remaining=MAX_TOTAL-sum(f['bytes'] for f in state['files']);pending=[];root=storage.folder(pid)
    try:
        for upload in files:
            ext=Path(upload.filename or '').suffix.lower()
            if ext not in ALLOWED:raise HTTPException(415,'Upload PDF, PNG, JPG or WEBP. CAD client files are not accepted.')
            ident=uuid.uuid4().hex;path=root/'sources'/(ident+ext);size=0;sha=hashlib.sha256()
            pending.append({'id':ident,'stored_name':path.name,'name':Path(upload.filename.replace('\\','/')).name[:160],'bytes':0,'sha256':''})
            with path.open('wb') as f:
                while chunk:=await upload.read(1024*1024):
                    size+=len(chunk);remaining-=len(chunk)
                    if size>MAX_FILE or remaining<0:raise HTTPException(413,'Limit: 30 MB per file / 120 MB per project')
                    f.write(chunk);sha.update(chunk)
            if size==0:raise HTTPException(422,'Empty file')
            # Signature check stops renamed non-image/non-PDF data before it reaches a parser.
            head=path.read_bytes()[:16]
            if ext=='.pdf' and not head.startswith(b'%PDF-'):raise HTTPException(415,'Invalid PDF signature')
            if ext!='.pdf':
                from PIL import Image
                try:
                    with Image.open(path) as img:
                        if img.width*img.height>30_000_000:raise ValueError('Image exceeds 30 megapixels')
                        img.verify()
                except Exception:raise HTTPException(415,'Invalid or oversized image') from None
            pending[-1].update(bytes=size,sha256=sha.hexdigest())
        def update(s):s['files'].extend(pending);s['pages']=[];s['status']='uploaded'
        storage.mutate(pid,update)
        return public_state(storage.read(pid))
    except Exception:
        for f in pending:(root/'sources'/f['stored_name']).unlink(missing_ok=True)
        raise
    finally:
        for f in files:await f.close()
        storage.release(pid)

class Analyze(Strict):
    mode:str=Field(default='local',pattern='^(local|cloud)$')
    cloud_consent:bool=False
    page_ids:list[str]=Field(default_factory=list,max_length=8)
    auto_build:bool=True
@app.post('/api/projects/{pid}/analyze')
def analyze(pid:str,data:Analyze):
    if not storage.read(pid)['files']:raise HTTPException(422,'Upload sources first')
    if data.mode=='cloud':
        if not data.cloud_consent:raise HTTPException(403,'Explicit opt-in is required for this cloud job')
        if not pipeline.capabilities()['cloud']:raise HTTPException(422,'Cloud credentials/model are not configured')
        if not data.page_ids:raise HTTPException(422,'Prepare pages locally and select 1-8 pages first')
    storage.acquire(pid)
    storage.event(pid,'queued','Analysis queued')
    pipeline.EXECUTOR.submit(pipeline.analysis_job,pid,data.mode,data.cloud_consent,data.page_ids,data.auto_build)
    return {'queued':True}

class SpecEdit(Strict):
    revision:int
    spec:ModelSpec
@app.put('/api/projects/{pid}/spec')
def edit_spec(pid:str,data:SpecEdit):
    with storage.LOCK:
        idle(pid)
        if storage.read(pid)['revision']!=data.revision:raise HTTPException(409,'This project changed. Reload before saving.')
        pipeline.save_spec(pid,data.spec,'Model specification updated locally')
    return public_state(storage.read(pid))

class Proposal(Strict):
    width_mm:float=Field(default=2400,ge=600,le=8000)
    depth_mm:float=Field(default=1300,ge=500,le=4000)
    include_windows:bool=False
@app.post('/api/projects/{pid}/suggest')
def propose(pid:str,data:Proposal):
    idle(pid);spec=ModelSpec.model_validate(storage.read(pid)['spec'])
    pipeline.save_spec(pid,suggest_balconies(spec,data.width_mm,data.depth_mm,data.include_windows),'Balcony proposals added without duplicating existing IDs')
    return public_state(storage.read(pid))

class PageEdit(Strict):
    kind:str=Field(pattern='^(plan|section|elevation|photo|unknown)$')
    points:list[list[float]]|None=None
    known_mm:float|None=None
@app.put('/api/projects/{pid}/pages/{page_id}')
def edit_page(pid:str,page_id:str,data:PageEdit):
    idle(pid)
    def update(s):
        page=next((p for p in s['pages'] if p['id']==page_id),None)
        if page is None:raise ValueError('Page not found')
        page['kind']=data.kind
        if data.points is not None:
            if len(data.points)!=2 or any(len(p)!=2 for p in data.points) or data.known_mm is None:raise ValueError('Choose two points and a known dimension')
            page['calibration']=calibration(*data.points[0],*data.points[1],data.known_mm,page['width_px'],page['height_px'])
    storage.mutate(pid,update);return public_state(storage.read(pid))

@app.post('/api/projects/{pid}/build')
def build(pid:str):
    s=storage.read(pid);q=quality(ModelSpec.model_validate(s['spec']))
    if not q['can_build_draft']:raise HTTPException(422,'Missing dimensions or geometry conflicts')
    storage.acquire(pid);storage.event(pid,'queued','Model build queued');pipeline.EXECUTOR.submit(pipeline.build_job,pid)
    return {'queued':True}

@app.get('/api/projects/{pid}/pages/{name}')
def page_image(pid:str,name:str):return FileResponse(storage.safe_file(pid,'pages',name),media_type='image/png')

DOWNLOADS={'preview.png','building.FCStd','building.ifc','building.glb','presentation.blend','drawings.pdf','front.svg','plan.svg','section.svg','model-package.zip','balconies.json','balcony-register.csv','evidence-report.json','manifest.json','spec.json'}
@app.get('/api/projects/{pid}/runs/{run_id}/{name}')
def download(pid:str,run_id:str,name:str):
    storage.valid_id(run_id)
    if name not in DOWNLOADS:raise HTTPException(404)
    if run_id not in {r['id'] for r in storage.read(pid)['runs']}:raise HTTPException(404)
    path=storage.folder(pid)/'runs'/run_id/name
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path,filename=None if name.endswith(('.png','.svg')) else name)

@app.post('/api/demo')
def demo():
    from .synthetic import create_sources
    s=storage.create('Synthetic courtyard');create_sources(storage.folder(s['id']))
    return public_state(storage.read(s['id']))

@app.get('/')
def index():return FileResponse(STATIC/'index.html')
app.mount('/static',StaticFiles(directory=STATIC),name='static')
