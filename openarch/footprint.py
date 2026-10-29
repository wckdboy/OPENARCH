"""Small, dependency-free polygon checks and facade frames, in millimetres.

The source trace is retained in its original coordinate system. No geographic
coordinates, scale or building dimensions are inferred by this module.
"""
import math

EPS = 1e-7


def area(points):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in edges(points))/2


def edges(points):
    return zip(points, points[1:]+points[:1])


def cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def on_segment(p,a,b):
    return side(a,b,p)==0 and min(a[0],b[0])-EPS<=p[0]<=max(a[0],b[0])+EPS and min(a[1],b[1])-EPS<=p[1]<=max(a[1],b[1])+EPS


def side(a,b,p):
    value=cross(a,b,p);tolerance=EPS*max(math.dist(a,b),1)
    return 0 if abs(value)<=tolerance else 1 if value>0 else -1


def intersects(a,b,c,d):
    if any(on_segment(p,u,v) for p,u,v in [(a,c,d),(b,c,d),(c,a,b),(d,a,b)]):return True
    return side(a,b,c)*side(a,b,d)<0 and side(c,d,a)*side(c,d,b)<0


def inside(point,ring):
    if any(on_segment(point,a,b) for a,b in edges(ring)):return False
    x,y=point;result=False
    for a,b in edges(ring):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:result=not result
    return result


def validate_rings(rings):
    """Reject crossing, touching, nested or zero-area rings before CAD execution."""
    for ring in rings:
        if len(ring)<3 or abs(area(ring))<EPS:raise ValueError('A footprint ring needs at least three non-collinear corners')
        es=list(edges(ring))
        for i,(a,b) in enumerate(es):
            if math.dist(a,b)<EPS:raise ValueError('Repeated footprint corner')
            prev=ring[(i-1)%len(ring)]
            if abs(cross(prev,a,b))<EPS and (prev[0]-a[0])*(b[0]-a[0])+(prev[1]-a[1])*(b[1]-a[1])>0:
                raise ValueError('Footprint edge doubles back on itself')
            for j,(c,d) in enumerate(es):
                if j<=i or j==i+1 or (i==0 and j==len(es)-1):continue
                if intersects(a,b,c,d):raise ValueError('Footprint edges cross or touch')
    for i,hole in enumerate(rings[1:],1):
        if not all(inside(p,rings[0]) for p in hole):raise ValueError('Courtyards must be strictly inside the outer boundary')
        for previous in rings[:i]:
            if any(intersects(a,b,c,d) for a,b in edges(hole) for c,d in edges(previous)):
                raise ValueError('Footprint rings cross or touch')
        for other in rings[1:i]:
            if inside(hole[0],other) or inside(other[0],hole):raise ValueError('Courtyards cannot overlap or nest')


def geometry(footprint):
    """Return a normalized model and persistent facade IDs, or None if unscaled."""
    if hasattr(footprint,'model_dump'):footprint=footprint.model_dump()
    rings=[footprint['outer'],*footprint['courtyards']]
    source=[[[p['x'],p['y']] for p in ring['points']] for ring in rings]
    validate_rings(source)
    scale=footprint['mm_per_unit']['value_mm']
    if scale is None:return None
    if not 0.001<=scale<=10000:raise ValueError('Footprint scale must be between 0.001 and 10000 mm per source unit')
    xs=[p[0] for p in source[0]];ys=[p[1] for p in source[0]]
    w=(max(xs)-min(xs))*scale;d=(max(ys)-min(ys))*scale
    if min(w,d)<1500 or max(w,d)>200000:raise ValueError('Scaled footprint must fit within 1.5 to 200 metres on each axis')
    metric=[];facades=[]
    for index,(ring,coords) in enumerate(zip(rings,source)):
        pts=[[(x-min(xs))*scale,(max(ys)-y if footprint['coordinate_system']=='image' else y-min(ys))*scale] for x,y in coords]
        # Building interior must lie to the left: outer CCW, courtyards CW.
        reverse=(area(pts)>0)!=(index==0)
        metric.append(list(reversed(pts)) if reverse else pts)
        for i,(a,b) in enumerate(edges(pts)):
            ids=sorted([ring['points'][i]['id'],ring['points'][(i+1)%len(pts)]['id']])
            if reverse:a,b=b,a
            length=math.dist(a,b)
            if length<100:raise ValueError('A scaled facade edge is shorter than 100 mm')
            facades.append({'id':ring['id']+':'+':'.join(ids),'label':f"{'Outer' if index==0 else 'Courtyard '+str(index)} edge {i+1}",
                            'start_corner':(i+1)%len(pts)+1 if reverse else i+1,'end_corner':i+1 if reverse else (i+1)%len(pts)+1,
                            'origin':a,'end':b,'length_mm':length,'angle_deg':math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])),
                            'tangent':[(b[0]-a[0])/length,(b[1]-a[1])/length], 'courtyard':index>0})
    return {'rings':metric,'facades':facades,'width_mm':w,'depth_mm':d,'area_mm2':abs(area(metric[0]))-sum(abs(area(p)) for p in metric[1:])}


def facade_map(spec):
    if spec.footprint:
        g=geometry(spec.footprint)
        return {f['id']:f for f in g['facades']} if g else {}
    return {'front':{'id':'front','label':'Front','origin':[0,0],'end':[spec.width.value_mm or 0,0],
                     'length_mm':spec.width.value_mm,'angle_deg':0,'tangent':[1,0],'courtyard':False}}


def balcony_polygon(b,frame):
    x,y=frame['origin'];tx,ty=frame['tangent']
    return [[x+tx*u-ty*v,y+ty*u+tx*v] for u,v in [(b.center_x_mm-b.width_mm/2,0),(b.center_x_mm+b.width_mm/2,0),(b.center_x_mm+b.width_mm/2,-b.depth_mm),(b.center_x_mm-b.width_mm/2,-b.depth_mm)]]


def convex_overlap(a,b):
    # Separating-axis test; boundary contact alone is not an overlap.
    for p,q in [*edges(a),*edges(b)]:
        length=math.dist(p,q);axis=[(p[1]-q[1])/length,(q[0]-p[0])/length]
        pa=[x*axis[0]+y*axis[1] for x,y in a];pb=[x*axis[0]+y*axis[1] for x,y in b]
        if min(max(pa),max(pb))-max(min(pa),min(pb))<=EPS:return False
    return True


def overlaps_building(rect,rings):
    def in_building(p):
        return inside(p,rings[0]) and not any(inside(p,h) or any(on_segment(p,a,b) for a,b in edges(h)) for h in rings[1:])
    # Facade attachment lies exactly on the boundary and is permitted.
    center=[sum(p[k] for p in rect)/4 for k in (0,1)]
    if any(in_building(p) for p in [*rect,center]):return True
    for ring in rings:
        if any(inside(p,rect) for p in ring):return True
        for a,b in edges(rect):
            for c,d in edges(ring):
                if side(a,b,c)*side(a,b,d)<0 and side(c,d,a)*side(c,d,b)<0:return True
    return False
