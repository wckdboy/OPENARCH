from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os,json,subprocess,uuid,shutil
from . import storage
from .schema import ModelSpec,quality
from .intake import ingest
from .extract import local_extract,cloud_extract,suggest_balconies
from .drawings import deliverables

# Serializes PDFium and limits CPU/memory pressure. Jobs persist state, not a broker.
EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix='balcony-worker')
WORKERS=Path(__file__).resolve().parent/'workers'

def capabilities():
    return {'freecad':bool(os.environ.get('FREECAD_CMD') or shutil.which('FreeCADCmd') or shutil.which('FreeCADCmd.exe')),
            'blender':bool(os.environ.get('BLENDER_EXE') or shutil.which('blender')),
            'ocr':bool(os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')),
            'cloud':bool(os.environ.get('OPENAI_API_KEY') and os.environ.get('OPENAI_MODEL'))}

def save_spec(pid,spec,reason):
    def update(state):
        # Preserve a local revision before replacing any accepted interpretation.
        hist=storage.folder(pid)/'history';hist.mkdir(exist_ok=True)
        storage.atomic(hist/f"spec-{state['revision']:05}.json",state['spec'])
        state['spec']=spec.model_dump();state['revision']+=1
    storage.mutate(pid,update);storage.event(pid,'review',reason)

def analysis_job(pid,mode,consent,page_ids,auto_build):
    try:
        state=storage.read(pid)
        pages=state['pages'] or ingest(pid)
        storage.event(pid,'interpreting','Interpreting source evidence locally' if mode=='local' else 'Sending selected page previews/text to opted-in cloud service')
        if mode=='cloud':
            chosen=[p for p in pages if p['id'] in page_ids]
            spec=cloud_extract(chosen,storage.folder(pid),consent)
        else:spec=local_extract(pages)
        spec=suggest_balconies(spec)
        save_spec(pid,spec,'Draft evidence extracted. Review dimensions and proposed balconies.')
        if auto_build and quality(spec)['can_build_draft'] and capabilities()['freecad']:
            build_job(pid,release=False)
        elif auto_build:
            storage.event(pid,'needs_input','Automatic drafting paused: missing/conflicting dimensions or FreeCAD is not configured.')
    except Exception as exc:
        storage.event(pid,'failed',safe_error(exc))
    finally:storage.release(pid)

def safe_error(exc):
    # Credentials/raw cloud responses and absolute private paths must never be sent to the UI.
    if isinstance(exc,ValueError):return str(exc)[:700]
    if isinstance(exc,subprocess.TimeoutExpired):return 'A modelling step exceeded its time limit. Check the private run log.'
    return type(exc).__name__+': job failed. Check local configuration and private logs.'

def run_worker(exe,args,env,log,marker,timeout):
    with log.open('w',encoding='utf-8') as out:
        result=subprocess.run([exe,*args],env=env,stdout=out,stderr=subprocess.STDOUT,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or marker not in log.read_text(encoding='utf-8',errors='replace'):
        raise ValueError('Model step failed: '+log.name+'. The log stays in the private project directory.')

def build_job(pid,release=True):
    run=None
    try:
        state=storage.read(pid);spec=ModelSpec.model_validate(state['spec']);q=quality(spec)
        if not q['can_build_draft']:raise ValueError('Resolve missing dimensions and geometry conflicts before generating a draft')
        fc=os.environ.get('FREECAD_CMD') or shutil.which('FreeCADCmd') or shutil.which('FreeCADCmd.exe')
        if not fc:raise ValueError('Set FREECAD_CMD to your FreeCADCmd executable')
        run_id=str(uuid.uuid4());run=storage.folder(pid)/'runs'/run_id;run.mkdir()
        storage.atomic(run/'spec.json',spec.model_dump());storage.atomic(run/'job.json',{'project_id':pid,'revision':state['revision'],'output':str(run),'spec':spec.model_dump()})
        storage.event(pid,'modelling','Building native FreeCAD solids, views and IFC')
        # FreeCAD's document temp names are long; keep the profile outside UUID run paths.
        profile=storage.data_root()/'.freecad-profile';profile.mkdir(exist_ok=True);env=os.environ.copy()
        env.pop('OPENAI_API_KEY',None);env['OPENARCH_JOB']=str(run/'job.json')
        for key in ['FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP']:env[key]=str(profile)
        run_worker(fc,[str(WORKERS/'freecad_build.py')],env,run/'freecad.log','CAD_COMPLETE',420)
        blender=os.environ.get('BLENDER_EXE') or shutil.which('blender')
        if blender:
            storage.event(pid,'rendering','Rendering the generated geometry in Blender')
            run_worker(blender,['--background','--factory-startup','--python',str(WORKERS/'blender_render.py')],env,run/'blender.log','RENDER_COMPLETE',420)
        storage.event(pid,'packaging','Creating drawing sheets, register and evidence report')
        deliverables(run,spec,state['revision'])
        record={'id':run_id,'revision':state['revision'],'created_at':storage.now(),'draft':not q['can_issue_reviewed'],'rendered':bool(blender)}
        storage.mutate(pid,lambda s:s['runs'].append(record));storage.event(pid,'ready','Model package ready'+(' (draft)' if record['draft'] else ''))
    except Exception as exc:
        storage.event(pid,'failed',safe_error(exc))
    finally:
        if release:storage.release(pid)
