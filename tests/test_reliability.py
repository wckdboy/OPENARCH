import io
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from openarch import storage, pipeline
from openarch.extract import local_extract
from openarch.schema import ModelSpec, Measure, Level, Opening, Balcony, quality
from openarch.review import invalidate_dependents
from openarch.processes import run_logged, terminate_tree
from openarch.server import app, TOKEN


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENARCH_DATA_DIR', str(tmp_path/'private'))


def page(text):
    return {'id':'source-1','text':text,'kind':'plan','rects':[]}


def spec():
    return ModelSpec(width=Measure(value_mm=16000),depth=Measure(value_mm=11000),
                     eaves=Measure(value_mm=12000),levels=[Level(id='L1',elevation=Measure(value_mm=3200))],
                     openings=[Opening(id='door',x_mm=2000,z_mm=3200,width_mm=1200,height_mm=2200,kind='door',reviewed=True)],
                     balconies=[Balcony(id='b',level_id='L1',center_x_mm=2600,source_opening='door',status='reviewed')])


def test_three_conflicting_level_labels_remain_unknown():
    result=local_extract([page('Level L1: 3000 mm\nLevel L1: 3100 mm\nLevel L1: 3000 mm')])
    assert result.levels[0].elevation.value_mm is None
    assert len([n for n in result.notes if 'Conflicting elevations' in n])==1


def test_centimetres_decimal_commas_and_negative_basement():
    result=local_extract([page('Facade width: 1480 cm\nBuilding depth: 9,25 m\nLevel B1: -240 cm')])
    assert result.width.value_mm==14800 and result.depth.value_mm==9250
    assert result.levels[0].elevation.value_mm==-2400


def test_reanalysis_preserves_manual_geometry_and_saves_proposal(monkeypatch):
    state=storage.create('Fictional reviewed model');pid=state['id'];old=spec();old.width.method='manual'
    storage.mutate(pid,lambda s:s.update(spec=old.model_dump(),revision=4,pages=[page('Facade width: 18000 mm')]))
    storage.acquire(pid)
    build=Mock();monkeypatch.setattr(pipeline,'build_job',build)
    pipeline.analysis_job(pid,'local',False,[],True)
    after=storage.read(pid)
    assert after['spec']==old.model_dump() and after['revision']==4 and not after['busy']
    candidate=json.loads((storage.folder(pid)/'analysis-proposals'/(after['analysis_proposal']['id']+'.json')).read_text())
    assert candidate['width']['value_mm']==18000 and not build.called


@pytest.mark.parametrize('change',['width','eaves','floor','door'])
def test_geometry_edits_invalidate_dependent_balcony_review(change):
    before=spec();after=before.model_copy(deep=True)
    if change in ['width','eaves']:getattr(after,change).value_mm+=500
    if change=='floor':after.levels[0].elevation.value_mm+=100
    if change=='door':after.openings[0].x_mm+=200
    invalidate_dependents(before,after)
    assert after.balconies[0].status=='proposed'
    if change in ['width','eaves']:assert not after.openings[0].reviewed


def test_unchanged_geometry_does_not_revoke_review():
    before=spec();after=before.model_copy(deep=True);after.notes.append('Reviewed source')
    assert invalidate_dependents(before,after).balconies[0].status=='reviewed'


def test_duplicate_upload_does_not_consume_remaining_project_quota(monkeypatch):
    import openarch.server as server
    stream=io.BytesIO();c=Canvas(stream);c.drawString(20,30,'Fictional plan');c.showPage();c.save();blob=stream.getvalue()
    monkeypatch.setattr(server,'MAX_TOTAL',len(blob)+10)
    with TestClient(app) as client:
        headers={'X-Openarch-Token':TOKEN};state=client.post('/api/projects',json={'name':'Quota'},headers=headers).json()
        url='/api/projects/'+state['id']+'/uploads'
        assert client.post(url,files={'files':('first.pdf',blob)},headers=headers).status_code==200
        response=client.post(url,files={'files':('alias.pdf',blob)},headers=headers)
        assert response.status_code==200 and len(response.json()['files'])==1
        assert response.json()['files'][0]['aliases']==['alias.pdf']


def test_submission_failure_releases_project_lock(monkeypatch):
    with TestClient(app) as client:
        state=storage.create('Queue failure');pid=state['id'];storage.mutate(pid,lambda s:s.update(spec=spec().model_dump()))
        monkeypatch.setattr(pipeline.EXECUTOR,'submit',Mock(side_effect=RuntimeError('shutdown')))
        response=client.post('/api/projects/'+pid+'/build',headers={'X-Openarch-Token':TOKEN})
        assert response.status_code==503 and not storage.read(pid)['busy']
        assert storage.read(pid)['status']=='failed'


def test_cloud_rejects_unknown_or_duplicate_pages_without_queuing(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only');monkeypatch.setenv('OPENAI_MODEL','test-model')
    with TestClient(app) as client:
        state=storage.create('Selected sources');pid=state['id'];storage.mutate(pid,lambda s:s.update(files=[{'id':'source'}],pages=[page('')]))
        queued=Mock();monkeypatch.setattr(pipeline.EXECUTOR,'submit',queued)
        for ids in [['source-1','unknown'],['source-1','source-1']]:
            response=client.post('/api/projects/'+pid+'/analyze',json={'mode':'cloud','cloud_consent':True,'page_ids':ids},headers={'X-Openarch-Token':TOKEN})
            assert response.status_code==422
        assert not queued.called and not storage.read(pid)['busy']


def test_worker_timeout_stops_the_owned_process(tmp_path):
    script=tmp_path/'slow.py';script.write_text('import time\ntime.sleep(60)\n')
    with pytest.raises(subprocess.TimeoutExpired):
        run_logged(sys.executable,[str(script)],os.environ.copy(),tmp_path/'worker.log','DONE',.15)


def test_worker_requires_success_marker(tmp_path):
    with pytest.raises(ValueError,match='Model step failed'):
        run_logged(sys.executable,['-c','print("partial")'],os.environ.copy(),tmp_path/'worker.log','DONE',10)


def test_worker_preserves_tool_output_and_completion_marker(tmp_path):
    log=tmp_path/'success.log'
    run_logged(sys.executable,['-c','print("DONE",flush=True)'],os.environ.copy(),log,'DONE',10)
    assert 'DONE' in log.read_text()


def test_tree_cleanup_failure_still_reaps_launcher(monkeypatch):
    import openarch.processes as processes
    monkeypatch.setattr(processes,'os',SimpleNamespace(name='nt'))
    job=Mock(terminate=Mock(side_effect=OSError('cleanup failed')))
    process=Mock(pid=123,poll=Mock(return_value=None))
    with pytest.raises(OSError):terminate_tree(process,job)
    process.kill.assert_called_once();process.wait.assert_called_once_with(timeout=15)


def test_worker_timeout_stops_spawned_child(tmp_path):
    heartbeat=tmp_path/'heartbeat';child_id=tmp_path/'child-id'
    child='import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile True:\n p.write_text(str(time.time_ns()))\n time.sleep(.03)\n'
    parent=tmp_path/'launcher.py'
    parent.write_text('import subprocess,sys,time,pathlib\n'
                      f'child=subprocess.Popen([sys.executable,"-c",{child!r},sys.argv[1]])\n'
                      'pathlib.Path(sys.argv[2]).write_text(str(child.pid))\ntime.sleep(60)\n')
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_logged(sys.executable,[str(parent),str(heartbeat),str(child_id)],os.environ.copy(),tmp_path/'tree.log','DONE',1)
        assert heartbeat.exists(),'Child must start before timeout for this test to be meaningful'
        before=heartbeat.read_text();time.sleep(.15)
        assert heartbeat.read_text()==before,'Timed-out worker left its child running'
    finally:
        # Clean up only this test child if the implementation regresses.
        if child_id.exists():
            try:os.kill(int(child_id.read_text()),__import__('signal').SIGTERM)
            except (ProcessLookupError,OSError):pass


def test_overlapping_openings_block_generation():
    model=spec();other=model.openings[0].model_copy();other.id='duplicate';model.openings.append(other)
    assert any('Overlapping openings' in item for item in quality(model)['conflicts'])


def test_deleted_access_opening_blocks_attached_balcony():
    model=spec();model.openings=[]
    assert 'Missing access opening: b' in quality(model)['conflicts']


def test_image_footprint_requires_orthographic_confirmation():
    from test_footprint import courtyard_spec
    model=courtyard_spec();model.footprint.coordinate_system='image'
    assert 'orthographic source confirmation' in quality(model)['missing']
    model.footprint.projection='orthographic'
    assert quality(model)['can_build_draft']


def test_changed_source_calibration_invalidates_metric_trace():
    from test_footprint import courtyard_spec
    with TestClient(app) as client:
        state=storage.create('Calibration change');pid=state['id'];model=courtyard_spec()
        model.footprint.source_page='source-1';model.footprint.mm_per_unit.method='calibrated';model.footprint.reviewed=True
        p=page('');p.update(width_px=1000,height_px=1000,calibration={'mm_per_px':1})
        storage.mutate(pid,lambda s:s.update(spec=model.model_dump(),pages=[p]))
        response=client.put('/api/projects/'+pid+'/pages/source-1',json={'kind':'plan','points':[[0,0],[100,0]],'known_mm':5000},headers={'X-Openarch-Token':TOKEN})
        assert response.status_code==200,response.text
        result=response.json();assert result['revision']==1 and result['spec']['footprint']['mm_per_unit']['value_mm'] is None
        assert not result['quality']['can_build_draft']


def test_poppler_route_does_not_open_pdfium(tmp_path,monkeypatch):
    import openarch.intake as intake
    from PIL import Image
    state=storage.create('Rasterizer isolation');root=storage.folder(state['id']);pdf=root/'sources'/'fiction.pdf'
    c=Canvas(str(pdf));c.drawString(20,30,'Facade width: 16000 mm');c.showPage();c.save()
    storage.mutate(state['id'],lambda s:s.update(files=[{'id':'fiction','stored_name':'fiction.pdf'}]))
    monkeypatch.setenv('PDFTOPPM_EXE','configured-poppler')
    monkeypatch.setattr(intake.pdfium,'PdfDocument',Mock(side_effect=AssertionError('PDFium must not open')))
    def render(args,**kwargs):
        Image.new('RGB',(200,300),'white').save(args[-1]+'.png')
        return Mock(returncode=0)
    monkeypatch.setattr(intake.subprocess,'run',render)
    pages=intake.ingest(state['id']);assert len(pages)==1 and pages[0]['width_px']==200


def test_validation_failure_does_not_echo_provider_payload():
    from pydantic import ValidationError
    try:ModelSpec.model_validate({'private-provider-payload':'do not echo'})
    except ValidationError as exc:assert 'do not echo' not in pipeline.safe_error(exc)
