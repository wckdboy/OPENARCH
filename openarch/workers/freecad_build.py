"""Standalone worker for FreeCADCmd. Consumes validated JSON; never executes input code."""
from pathlib import Path
import os,json,time,uuid,re,math
import FreeCAD as A,Part,TechDraw
from PySide import QtCore

job=json.loads(Path(os.environ['OPENARCH_JOB']).read_text(encoding='utf-8'))
O=Path(job['output']);O.mkdir(exist_ok=True);s=job['spec'];V=A.Vector
q=QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
d=A.newDocument('OPENARCH');visible=[]

def box(name,l,w,h,x,y,z,material='wall',category='IfcBuildingElementProxy',bid='',show=True,frame=None):
    o=d.addObject('Part::Box',name)
    for prop,value in [('Length',l),('Width',w),('Height',h),('Placement.Base.x',x),('Placement.Base.y',y),('Placement.Base.z',z)]:
        if isinstance(value,str):o.setExpression(prop,value)
        elif '.' not in prop:setattr(o,prop,value)
        else:
            p=o.Placement;setattr(p.Base,prop[-1],value);o.Placement=p
    if frame:
        tx,ty=frame['tangent'];ox,oy=frame['origin']
        o.Placement=A.Placement(V(ox+tx*x-ty*y,oy+ty*x+tx*y,z),A.Rotation(V(0,0,1),frame['angle_deg']))
    tag(o,material,category,bid)
    o.Visibility=show
    if show:visible.append(o)
    return o

def tag(o,mat,cls,bid=''):
    for k,value in [('Material',mat),('IfcClass',cls),('BalconyID',bid)]:
        if k not in o.PropertiesList:o.addProperty('App::PropertyString',k,'Identity')
        setattr(o,k,value)

def feature(name,shape,mat,cls):
    o=d.addObject('Part::Feature',name);o.Shape=shape;tag(o,mat,cls);visible.append(o);return o

W=s['width']['value_mm'];D=s['depth']['value_mm'];H=s['eaves']['value_mm'];T=s['wall_thickness']['value_mm'];R=s['roof_rise']['value_mm']
ZMIN=min([0]+[l['elevation']['value_mm'] for l in s['levels']])
footprint=job.get('footprint_geometry');frames=job.get('facades') or {'front':{'origin':[0,0],'tangent':[1,0],'angle_deg':0}}
if footprint:R=0
params=d.addObject('App::FeaturePython','BuildingDimensions')
for k,value in [('Width',W),('Depth',D),('Eaves',H),('Wall',T),('RoofRise',R)]:params.addProperty('App::PropertyLength',k,'Dimensions');setattr(params,k,value)
if footprint:
    def ring_face(points):
        # OCC coplanar Booleans need consistent face normals; a clockwise hole
        # is still cut using an upward-facing tool face.
        if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))<0:points=list(reversed(points))
        verts=[V(x,y,0) for x,y in points];return Part.Face(Part.makePolygon(verts+[verts[0]]))
    footprint_face=ring_face(footprint['rings'][0])
    for ring in footprint['rings'][1:]:footprint_face=footprint_face.cut(ring_face(ring))
    footprint_face=footprint_face.removeSplitter()
    assert len(footprint_face.Faces)==1 and len(footprint_face.Wires)==len(footprint['rings']),'Disconnected or incorrect footprint topology'
    volume=footprint_face.extrude(V(0,0,H-ZMIN));volume.translate(V(0,0,ZMIN));strips=[]
    for frame in frames.values():
        ox,oy=frame['origin'];tx,ty=frame['tangent'];length=frame['length_mm']
        points=[(ox+tx*x-ty*y,oy+ty*x+tx*y) for x,y in [(-T,0),(length+T,0),(length+T,T),(-T,T)]]
        strip=ring_face(points).extrude(V(0,0,H-ZMIN));strip.translate(V(0,0,ZMIN));strips.append(strip)
    shape=strips[0].multiFuse(strips[1:]).common(volume).removeSplitter()
    interior_slab=footprint_face.extrude(V(0,0,180)).cut(shape).removeSplitter()
    shell=d.addObject('Part::Feature','PolygonWallShell');shell.Shape=shape
else:
    outer=box('Outer','BuildingDimensions.Width','BuildingDimensions.Depth',f'BuildingDimensions.Eaves-({ZMIN} mm)',0,0,ZMIN,show=False)
    inner=box('Inner','BuildingDimensions.Width-2*BuildingDimensions.Wall','BuildingDimensions.Depth-2*BuildingDimensions.Wall',f'BuildingDimensions.Eaves-({ZMIN} mm)+10 mm','BuildingDimensions.Wall','BuildingDimensions.Wall',ZMIN-5,show=False)
    shell=d.addObject('Part::Cut','WallShell');shell.Base=outer;shell.Tool=inner;outer.Visibility=False;inner.Visibility=False
opening_tools=[]
for i,o in enumerate(s['openings']):
    frame=frames[o.get('facade_id','front')]
    cut=box('OpeningTool'+str(i),o['width_mm'],T+20,o['height_mm'],o['x_mm'],-10,o['z_mm'],show=False,frame=frame)
    opening_tools.append(cut)
    # Inset glazing and simple opening trims are presentation details, not joinery.
    x,z,w,h=o['x_mm'],o['z_mm'],o['width_mm'],o['height_mm']
    box('Glass'+str(i),w-80,12,h-80,x+40,T*.55,z+40,'glass',frame=frame)
    for j,xx in enumerate([x,x+w-40]):box(f'Jamb{i}_{j}',40,70,h,xx,T*.5,z,'trim',frame=frame)
    box('Head'+str(i),w-80,70,40,x+40,T*.5,z+h-40,'trim',frame=frame)
    box('Sill'+str(i),w-80,70,40,x+40,T*.5,z,'trim',frame=frame)
    box('Mullion'+str(i),35,70,h-80,x+w/2-17.5,T*.5,z+40,'trim',frame=frame)
    box('Lintel'+str(i),w+160,65,90,x-80,-65,z+h,'trim',frame=frame)
if opening_tools:
    toolset=d.addObject('Part::Compound','OpeningTools');toolset.Links=opening_tools
    result=d.addObject('Part::Cut','WallOpenings');result.Base=shell;result.Tool=toolset
    shell.Visibility=False;toolset.Visibility=False
    for tool in opening_tools:tool.Visibility=False
    shell=result
tag(shell,'wall','IfcWall');shell.Visibility=True;visible.append(shell)
levels={l['id']:l['elevation']['value_mm'] for l in s['levels']}
for i,z in enumerate(levels.values()):
    if footprint:
        slab=interior_slab.copy();slab.translate(V(0,0,z-180));feature('Floor'+str(i),slab,'floor','IfcSlab')
    else:box('Floor'+str(i),W-2*T,D-2*T,180,T,T,z-180,'floor','IfcSlab')
if footprint:
    roof=footprint_face.extrude(V(0,0,180));roof.translate(V(0,0,H));feature('RoofPlaceholder',roof,'roof','IfcRoof')
elif R>0:
    poly=Part.makePolygon([V(-150,-200,H),V(-150,D/2,H+R),V(-150,D+200,H),V(-150,-200,H)])
    feature('Roof',Part.Face(poly).extrude(V(W+300,0,0)),'roof','IfcRoof')
else:box('Roof',W+200,D+200,180,-100,-100,H,'roof','IfcRoof')
if not footprint:box('Cornice',W+160,160,130,-80,-160,H-130,'trim')
registry=[]
for i,b in enumerate(s['balconies']):
    if b['status']=='excluded':continue
    group=d.addObject('App::Part',f'Balcony{i}');group.Label=b['id']
    frame=frames[b.get('facade_id','front')]
    group.Placement=A.Placement(V(*frame['origin'],0),A.Rotation(V(0,0,1),frame['angle_deg']))
    p=d.addObject('App::FeaturePython',f'B{i}Dimensions');group.addObject(p);p.Label='EDIT '+b['id']
    for k,value in [('Width',b['width_mm']),('Depth',b['depth_mm']),('Guard',b['guard_height_mm']),('CenterX',b['center_x_mm']),('Level',levels[b['level_id']])]:p.addProperty('App::PropertyLength',k,'Dimensions');setattr(p,k,value)
    p.addProperty('App::PropertyString','BalconyID','Identity');p.BalconyID=b['id'];ref=p.Name+'.'
    start=len(visible)
    def bb(n,l,w,h,x,y,z,mat='steel',cls='IfcMember'):
        obj=box(f'B{i}_{n}',l,w,h,x,y,z,mat,cls,b['id']);group.addObject(obj);return obj
    bb('FrameFront',ref+'Width',55,180,ref+'CenterX-'+ref+'Width/2','-'+ref+'Depth',ref+'Level-180 mm')
    bb('FrameBack',ref+'Width',55,180,ref+'CenterX-'+ref+'Width/2',-55,ref+'Level-180 mm')
    for side,x in [('L',ref+'CenterX-'+ref+'Width/2'),('R',ref+'CenterX+'+ref+'Width/2-55 mm')]:
        bb('Frame'+side,55,ref+'Depth-110 mm',180,x,'-'+ref+'Depth+55 mm',ref+'Level-180 mm')
    bb('Deck',ref+'Width-110 mm',ref+'Depth-110 mm',28,ref+'CenterX-'+ref+'Width/2+55 mm','-'+ref+'Depth+55 mm',ref+'Level-28 mm','deck','IfcSlab')
    bb('TopFront',ref+'Width',45,20,ref+'CenterX-'+ref+'Width/2','-'+ref+'Depth',ref+'Level+'+ref+'Guard-20 mm',cls='IfcRailing')
    for side,x in [('L',ref+'CenterX-'+ref+'Width/2'),('R',ref+'CenterX+'+ref+'Width/2-45 mm')]:
        bb('Top'+side,45,ref+'Depth-45 mm',20,x,'-'+ref+'Depth+45 mm',ref+'Level+'+ref+'Guard-20 mm',cls='IfcRailing')
    if b['type_id']=='solid_guard':
        bb('PanelFront',ref+'Width-60 mm',12,ref+'Guard-90 mm',ref+'CenterX-'+ref+'Width/2+30 mm','-'+ref+'Depth+18 mm',ref+'Level+40 mm','steel','IfcRailing')
        for side,x in [('L',ref+'CenterX-'+ref+'Width/2+18 mm'),('R',ref+'CenterX+'+ref+'Width/2-30 mm')]:bb('Panel'+side,12,ref+'Depth-60 mm',ref+'Guard-90 mm',x,'-'+ref+'Depth+30 mm',ref+'Level+40 mm','steel','IfcRailing')
    else:
        # Count is fixed in this generated document; spacing/lengths remain native expressions.
        count=max(2,round(b['width_mm']/100)+1)
        for j in range(count):bb('PicketF'+str(j),8,25,ref+'Guard-60 mm',ref+f'CenterX-{ref}Width/2+20 mm+({ref}Width-48 mm)*{j}/{count-1}','-'+ref+'Depth+10 mm',ref+'Level+40 mm',cls='IfcRailing')
        count=max(2,round(b['depth_mm']/100))
        for side,x in [('L',ref+'CenterX-'+ref+'Width/2+10 mm'),('R',ref+'CenterX+'+ref+'Width/2-35 mm')]:
            for j in range(count):bb('Picket'+side+str(j),25,8,ref+'Guard-60 mm',x,'-'+ref+f'Depth+35 mm+({ref}Depth-70 mm)*{j}/{count-1}',ref+'Level+40 mm',cls='IfcRailing')
    registry.append(dict(b,elevation_mm=levels[b['level_id']],freecad_object=group.Name))
d.recompute()
assert all(o.Shape.isValid() and o.Shape.Solids for o in visible),'Invalid generated solid'
mesh=[]
for o in visible:
    shape=o.Shape.copy();shape.Placement=o.getGlobalPlacement();vs,fs=shape.tessellate(4)
    mesh.append({'name':o.Name,'material':o.Material,'ifc_class':o.IfcClass,'balcony_id':o.BalconyID,'vertices_mm':[[v.x,v.y,v.z] for v in vs],'faces':[list(f) for f in fs]})
(O/'mesh.json').write_text(json.dumps(mesh));(O/'balconies.json').write_text(json.dumps(registry,indent=2))

# Cut away geometry above the plan's cut plane and below the selected storey.
plan_z=min([z for z in levels.values() if z>0],default=0)
world_shapes=[]
for o in visible:
    shape=o.Shape.copy();shape.Placement=o.getGlobalPlacement();world_shapes.append(shape)
compound=Part.makeCompound(world_shapes)
world_source=d.addObject('Part::Feature','WorldDrawingGeometry');world_source.Shape=compound;world_source.Visibility=False
clip=Part.makeBox(W+20000,D+20000,1500,V(-10000,-10000,plan_z-250))
plan_parts=[]
for shape in world_shapes:
    if shape.BoundBox.intersect(clip.BoundBox):
        part=shape.common(clip)
        if not part.isNull():plan_parts.append(part)
plan_shape=Part.makeCompound(plan_parts)
plan_source=d.addObject('Part::Feature','PlanCutGeometry');plan_source.Shape=plan_shape;plan_source.Visibility=False
template=O/'sheet-template.svg';template.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297"><text x="12" y="15" font-size="5">OPENARCH / DRAFT</text></svg>')
page=d.addObject('TechDraw::DrawPage','Drawings');tpl=d.addObject('TechDraw::DrawSVGTemplate','Template');tpl.Template=str(template);page.Template=tpl
scale=min(.01,180/(H+R),175/W)
def view(name,source,direction,x,y):
    v=d.addObject('TechDraw::DrawViewPart',name);page.addView(v);v.Source=source;v.Direction=direction;v.CoarseView=True;v.ScaleType='Custom';v.Scale=scale;v.X=x;v.Y=y;return v
front=view('Front',[world_source],(0,-1,0),110,160)
front.XDirection=(-1,0,0)
plan=view('Plan',[plan_source],(0,0,1),300,210)
section=d.addObject('TechDraw::DrawViewSection','Section');page.addView(section);section.BaseView=front;section.XDirection=(0,-1,0);section.Direction=(1,0,0);section.Source=[world_source];section.SectionNormal=(1,0,0);section.SectionOrigin=(W/2,D/2,H/2);section.ScaleType='Custom';section.Scale=scale;section.CoarseView=True;section.X=300;section.Y=90
d.recompute()
deadline=time.monotonic()+12
while time.monotonic()<deadline:q.processEvents();time.sleep(.025)
views={}
for v in [front,plan,section]:
    assert len(v.getVisibleEdges())>0,'Empty drawing '+v.Name
    raw=TechDraw.viewPartAsSvg(v);pts=[tuple(map(float,p)) for p in re.findall(r'[ML]\s+(-?[\d.]+)\s+(-?[\d.]+)',raw)]
    xs,ys=zip(*pts);bounds=[min(xs),min(ys),max(xs),max(ys)]
    raw=raw.replace('stroke-width="0.7"','stroke-width="0.18"')
    (O/(v.Name.lower()+'.svg')).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{bounds[2]-bounds[0]+4}mm" height="{bounds[3]-bounds[1]+4}mm" viewBox="{bounds[0]-2} {-bounds[3]-2} {bounds[2]-bounds[0]+4} {bounds[3]-bounds[1]+4}"><g transform="scale(1,-1)">{raw}</g></svg>')
    views[v.Name.lower()]={'bounds':bounds,'scale':scale,'visible_edges':len(v.getVisibleEdges())}
if 'KeepUpdated' in page.PropertiesList:page.KeepUpdated=False
d.saveAs(str(O/'building.FCStd'));A.closeDocument(d.Name)
(O/'geometry-validation.json').write_text(json.dumps({'valid_solids':True,'wall_min_z_mm':min(v[2] for m in mesh if m['ifc_class']=='IfcWall' for v in m['vertices_mm']),'object_count':len(visible),'balcony_count':len(registry),'views':views,'plan_cut_elevation_mm':plan_z+1250,'model_z_center_mm':(compound.BoundBox.ZMin+compound.BoundBox.ZMax)/2,'footprint_area_mm2':footprint_face.Area if footprint else W*D,'courtyard_count':len(footprint['rings'])-1 if footprint else 0,'roof_placeholder':bool(footprint)},indent=2))

# IFC4 exchange, generated from the exact meshes used for the render.
import ifcopenshell,ifcopenshell.api,ifcopenshell.validate
f=ifcopenshell.file(schema='IFC4');api=ifcopenshell.api.run
def root(cls,name,key):
    e=api('root.create_entity',f,ifc_class=cls,name=name);e.GlobalId=ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL,job['project_id']+'/'+key).hex);return e
project=root('IfcProject','Local balcony project','project');site=root('IfcSite','Site','site');building=root('IfcBuilding','Building','building')
api('unit.assign_unit',f,units=[api('unit.add_si_unit',f,unit_type='LENGTHUNIT')])
context=api('context.add_context',f,context_type='Model');body=api('context.add_context',f,context_type='Model',context_identifier='Body',target_view='MODEL_VIEW',parent=context)
api('aggregate.assign_object',f,products=[site],relating_object=project);api('aggregate.assign_object',f,products=[building],relating_object=site)
stores={}
for key,z in levels.items():
    e=root('IfcBuildingStorey',key,'level/'+key);e.Elevation=z/1000;api('aggregate.assign_object',f,products=[e],relating_object=building);stores[key]=e
assemblies={}
for b in registry:
    e=root('IfcElementAssembly',b['id'],'balcony/'+b['id']);e.PredefinedType='USERDEFINED';e.ObjectType='Balcony';api('spatial.assign_container',f,products=[e],relating_structure=stores[b['level_id']])
    p=api('pset.add_pset',f,product=e,name='OPENARCH');api('pset.edit_pset',f,pset=p,properties={'BalconyID':b['id'],'FacadeID':b.get('facade_id','front'),'Width_mm':b['width_mm'],'Depth_mm':b['depth_mm'],'Apartment':b['apartment'],'Status':b['status']});assemblies[b['id']]=e
for m in mesh:
    e=root(m['ifc_class'],m['name'],'part/'+m['name'])
    rep=api('geometry.add_mesh_representation',f,context=body,vertices=[[[x/1000 for x in v] for v in m['vertices_mm']]],faces=[m['faces']]);api('geometry.assign_representation',f,product=e,representation=rep);api('geometry.edit_object_placement',f,product=e)
    if m['balcony_id']:api('aggregate.assign_object',f,products=[e],relating_object=assemblies[m['balcony_id']])
    else:api('spatial.assign_container',f,products=[e],relating_structure=building)
f.write(str(O/'building.ifc'));logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(ifcopenshell.open(str(O/'building.ifc')),logger)
(O/'ifc-validation.json').write_text(json.dumps({'schema':'IFC4','issues':logger.statements},default=str,indent=2))
assert not logger.statements,'IFC validation failed'
print('CAD_COMPLETE',flush=True)
