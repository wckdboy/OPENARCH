from pathlib import Path
import os,json,math
import bpy
from mathutils import Vector

job=json.loads(Path(os.environ['OPENARCH_JOB']).read_text(encoding='utf-8'));O=Path(job['output']);s=job['spec']
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
colors={'wall':(.72,.66,.52,1),'floor':(.65,.62,.54,1),'roof':(.23,.12,.07,1),'trim':(.91,.88,.79,1),'glass':(.08,.19,.24,1),'steel':(.27,.31,.30,1),'deck':(.31,.16,.07,1)}
materials={}
for name,col in colors.items():
    m=bpy.data.materials.new(name);m.diffuse_color=col;m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=col;p.inputs['Roughness'].default_value=.28 if name in ['glass','steel'] else .7
    if name=='steel':p.inputs['Metallic'].default_value=.7
    materials[name]=m
for item in json.loads((O/'mesh.json').read_text()):
    mesh=bpy.data.meshes.new(item['name']);mesh.from_pydata([[x/1000 for x in v] for v in item['vertices_mm']],[],item['faces']);mesh.update()
    obj=bpy.data.objects.new(item['name'],mesh);bpy.context.collection.objects.link(obj);obj.data.materials.append(materials[item['material']]);obj['BalconyID']=item['balcony_id']
    mod=obj.modifiers.new('Edge highlights','BEVEL');mod.width=.003;mod.segments=2
W=s['width']['value_mm']/1000;D=s['depth']['value_mm']/1000;H=(s['eaves']['value_mm']+(0 if s.get('footprint') else s['roof_rise']['value_mm']))/1000
bpy.ops.mesh.primitive_plane_add(size=max(W,D,H)*12,location=(W/2,D/2,-.25))
ground=bpy.data.materials.new('Ground');ground.diffuse_color=(.55,.56,.53,1);bpy.context.object.data.materials.append(ground)
scene=bpy.context.scene;world=bpy.data.worlds.new('Daylight');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.78,.85,1,1);world.node_tree.nodes['Background'].inputs[1].default_value=.6;scene.world=world
bpy.ops.object.light_add(type='SUN',location=(W,-D,H));sun=bpy.context.object;sun.rotation_euler=(math.radians(30),math.radians(-25),math.radians(-30));sun.data.energy=2.2;sun.data.angle=.12
bpy.ops.object.camera_add(location=(W*1.65,-max(D,W)*1.7,H*.9));cam=bpy.context.object;cam.data.type='ORTHO';cam.data.ortho_scale=max(H*1.4,W*1.5,D*1.6);cam.rotation_euler=(Vector((W/2,D*.25,H*.45))-cam.location).to_track_quat('-Z','Y').to_euler();scene.camera=cam
if s.get('footprint'):
    cam.location.z=H*2.3;cam.data.ortho_scale=max(W*1.8,D*1.9,H*1.5)
    cam.rotation_euler=(Vector((W/2,D/2,H*.35))-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True;scene.render.resolution_x=1600;scene.render.resolution_y=1200;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='AgX';scene.render.filepath=str(O/'preview.png')
bpy.ops.render.render(write_still=True);bpy.ops.wm.save_as_mainfile(filepath=str(O/'presentation.blend'))
bpy.ops.export_scene.gltf(filepath=str(O/'building.glb'),export_format='GLB',use_selection=False)
print('RENDER_COMPLETE',flush=True)
