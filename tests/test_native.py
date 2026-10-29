"""Opt-in real FreeCAD integration. Only invented geometry is used."""
import json
import os
from pathlib import Path
import pytest
from openarch.pipeline import run_worker, WORKERS
from openarch.schema import ModelSpec, Measure, Level, Opening
from openarch.footprint import geometry, facade_map

pytestmark=pytest.mark.skipif(os.environ.get('OPENARCH_TEST_NATIVE')!='1',reason='Set OPENARCH_TEST_NATIVE=1 and FREECAD_CMD for native tests')


@pytest.mark.parametrize('polygon',[False,True])
def test_native_model_views_and_ifc(tmp_path,polygon):
    if polygon:
        from test_footprint import courtyard_spec
        spec=courtyard_spec();facade=next(iter(facade_map(spec)))
    else:
        spec=ModelSpec(width=Measure(value_mm=13000),depth=Measure(value_mm=9000),eaves=Measure(value_mm=10000),levels=[Level(id='G',elevation=Measure(value_mm=0)),Level(id='L1',elevation=Measure(value_mm=3200))]);facade='front'
    spec.levels.append(Level(id='B1',elevation=Measure(value_mm=-2500)))
    spec.openings=[Opening(id='a',facade_id=facade,x_mm=1000,z_mm=900,width_mm=1200,height_mm=1600),Opening(id='b',facade_id=facade,x_mm=3000,z_mm=900,width_mm=1200,height_mm=1600)]
    job={'project_id':'00000000-0000-4000-8000-000000000001','revision':1,'output':str(tmp_path),'spec':spec.model_dump(),'footprint_geometry':geometry(spec.footprint) if polygon else None,'facades':facade_map(spec)}
    path=tmp_path/'job.json';path.write_text(json.dumps(job));env=os.environ.copy();env.pop('OPENAI_API_KEY',None);env['OPENARCH_JOB']=str(path)
    # Short profile path avoids Windows MAX_PATH failures in FreeCAD internals.
    profile=Path(os.environ.get('OPENARCH_NATIVE_PROFILE',str(tmp_path/'fc')));profile.mkdir(exist_ok=True)
    for key in ['FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP']:env[key]=str(profile)
    run_worker(os.environ['FREECAD_CMD'],[str(WORKERS/'freecad_build.py')],env,tmp_path/'worker.log','CAD_COMPLETE',240)
    check=json.loads((tmp_path/'geometry-validation.json').read_text())
    assert check['valid_solids'] and check['wall_min_z_mm']==-2500
    assert check['courtyard_count']==int(polygon)
    assert all(v['visible_edges']>0 for v in check['views'].values())
    assert json.loads((tmp_path/'ifc-validation.json').read_text())['issues']==[]
    assert (tmp_path/'building.FCStd').stat().st_size>10000
