import pytest
from fastapi.testclient import TestClient
from openarch.schema import ModelSpec,Footprint,Opening,Balcony,quality
from openarch.footprint import geometry,balcony_polygon,inside
from openarch.extract import suggest_balconies
from openarch.server import app,TOKEN


def ring(ident,points):
    return {'id':ident,'points':[{'id':f'p{i}','x':x,'y':y} for i,(x,y) in enumerate(points)]}


def courtyard_spec(scale=1):
    measure=lambda n:{'value_mm':n,'method':'manual','reviewed':False}
    return ModelSpec.model_validate({'footprint':{'coordinate_system':'cartesian',
        'outer':ring('outer',[(0,0),(20000,0),(20000,16000),(0,16000)]),
        'courtyards':[ring('court',[(6000,4000),(14000,4000),(14000,12000),(6000,12000)])],
        'mm_per_unit':measure(scale)},'eaves':measure(11000),'roof_rise':measure(0),'wall_thickness':measure(350),
        'levels':[{'id':'G','elevation':measure(0)},{'id':'L1','elevation':measure(3200)},{'id':'L2','elevation':measure(6400)}]})


def test_unscaled_trace_is_retained_but_never_buildable():
    s=courtyard_spec(None)
    assert len(s.footprint.outer.points)==4 and s.width.value_mm is None
    assert 'footprint scale' in quality(s)['missing'] and not quality(s)['can_build_draft']


def test_courtyard_area_and_inward_facing_frames():
    s=courtyard_spec();g=geometry(s.footprint)
    assert g['area_mm2']==256_000_000 and s.width.value_mm==20000
    for f in g['facades']:
        if not f['courtyard']:continue
        b=Balcony(id='a',facade_id=f['id'],level_id='L1',center_x_mm=4000)
        p=balcony_polygon(b,f)[2]
        assert inside(p,g['rings'][1])
    assert quality(s)['can_build_draft'] and not quality(s)['can_issue_reviewed']


@pytest.mark.parametrize('points',[[(0,0),(20000,16000),(0,16000),(20000,0)],[(0,0),(20000,0),(10000,0),(10000,16000),(0,16000)]])
def test_crossing_or_backtracking_outer_boundary_is_rejected(points):
    data=courtyard_spec().footprint.model_dump();data['outer']=ring('outer',points)
    with pytest.raises(ValueError):Footprint.model_validate(data)


@pytest.mark.parametrize('points',[[(0,4000),(8000,4000),(8000,9000),(0,9000)],[(19000,4000),(23000,4000),(23000,9000),(19000,9000)]])
def test_courtyard_cannot_touch_or_leave_building(points):
    data=courtyard_spec().footprint.model_dump();data['courtyards']=[ring('court',points)]
    with pytest.raises(ValueError):Footprint.model_validate(data)


def test_facade_ids_survive_reversed_vertex_order():
    data=courtyard_spec().footprint.model_dump();before={f['id'] for f in geometry(data)['facades']}
    data['outer']['points'].reverse();data['courtyards'][0]['points'].reverse()
    after={f['id'] for f in geometry(data)['facades']}
    assert before==after


def test_angled_facade_attachment_is_not_a_false_building_collision():
    data=courtyard_spec().model_dump()
    data['footprint']['outer']=ring('outer',[(0,0),(20000,0),(20000,6000),(10000,6000),(16000,16000),(10000,20000),(0,6000)])
    data['footprint']['courtyards']=[]
    spec=ModelSpec.model_validate(data)
    for i,f in enumerate(geometry(spec.footprint)['facades']):
        if i in [0,3,5]:spec.balconies.append(Balcony(id=f'b{i}',facade_id=f['id'],level_id='L1',center_x_mm=f['length_mm']/2,width_mm=1800,depth_mm=1000))
    assert quality(spec)['conflicts']==[]


def test_proposals_use_their_source_facade_and_detect_opposing_overlap():
    s=courtyard_spec();facades=geometry(s.footprint)['facades']
    courts=[f for f in facades if f['courtyard']]
    for i,f in enumerate([courts[0],courts[2]]):
        s.openings.append(Opening(id=f'door{i}',facade_id=f['id'],x_mm=3300,z_mm=3200,width_mm=1400,height_mm=2200,kind='door'))
    suggest_balconies(s)
    assert {b.facade_id for b in s.balconies}=={courts[0]['id'],courts[2]['id']}
    assert not quality(s)['conflicts']
    # Different facade IDs can still overlap around a narrow courtyard corner.
    s.balconies[0].depth_mm=4000;s.balconies[1].depth_mm=4000
    s.balconies[1].facade_id=courts[1]['id'];s.balconies[1].center_x_mm=6000
    s.balconies[0].center_x_mm=2000
    assert any('Overlapping balconies' in c for c in quality(s)['conflicts'])


def test_upload_hash_deduplicates_aliases_and_preserves_pages(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENARCH_DATA_DIR',str(tmp_path/'private'))
    from reportlab.pdfgen.canvas import Canvas
    import io
    stream=io.BytesIO();c=Canvas(stream);c.drawString(20,30,'Fictional source');c.showPage();c.save();data=stream.getvalue()
    with TestClient(app) as client:
        headers={'X-Openarch-Token':TOKEN};s=client.post('/api/projects',json={'name':'Generic archive'},headers=headers).json()
        url='/api/projects/'+s['id']+'/uploads'
        result=client.post(url,files=[('files',('first.pdf',data)),('files',('second.pdf',data))],headers=headers).json()
        assert len(result['files'])==1 and result['files'][0]['aliases']==['second.pdf']
