from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Measure(Strict):
    value_mm: float | None = Field(default=None, ge=-10000, le=200000)
    source_page: str | None = None
    method: Literal["unknown", "dimension", "calibrated", "inferred", "assumed", "manual"] = "unknown"
    confidence: float = Field(default=0, ge=0, le=1)
    reviewed: bool = False

class Level(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    elevation: Measure

class Corner(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,20}$")
    x: float = Field(ge=-200000, le=200000)
    y: float = Field(ge=-200000, le=200000)

class Ring(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,20}$")
    points: list[Corner] = Field(min_length=3, max_length=100)

class Footprint(Strict):
    outer: Ring
    courtyards: list[Ring] = Field(default_factory=list, max_length=8)
    coordinate_system: Literal['image','cartesian'] = 'image'
    mm_per_unit: Measure = Field(default_factory=Measure)
    source_page: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    reviewed: bool = False

    @model_validator(mode='after')
    def valid_geometry(self):
        from .footprint import geometry
        rings=[self.outer,*self.courtyards]
        if len({r.id for r in rings})!=len(rings):raise ValueError('Footprint ring IDs must be unique')
        for r in rings:
            if len({p.id for p in r.points})!=len(r.points):raise ValueError('Corner IDs must be unique within a ring')
        geometry(self)
        return self

class Opening(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    x_mm: float = Field(ge=0, le=200000)
    z_mm: float = Field(ge=0, le=200000)
    width_mm: float = Field(gt=100, le=10000)
    height_mm: float = Field(gt=100, le=10000)
    kind: Literal["window", "door"] = "window"
    source_page: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    reviewed: bool = False
    facade_id: str = Field(default='front', max_length=80)

class Balcony(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    level_id: str
    center_x_mm: float = Field(ge=0, le=200000)
    width_mm: float = Field(default=2400, ge=600, le=8000)
    depth_mm: float = Field(default=1300, ge=500, le=4000)
    guard_height_mm: float = Field(default=1100, ge=500, le=2000)
    type_id: Literal["steel_picket", "solid_guard"] = "steel_picket"
    apartment: str = Field(default="", max_length=100)
    status: Literal["proposed", "reviewed", "excluded"] = "proposed"
    source_opening: str | None = None
    facade_id: str = Field(default='front', max_length=80)

class ModelSpec(Strict):
    footprint: Footprint | None = None
    width: Measure = Field(default_factory=Measure)
    depth: Measure = Field(default_factory=Measure)
    eaves: Measure = Field(default_factory=Measure)
    roof_rise: Measure = Field(default_factory=lambda: Measure(value_mm=1800, method="assumed"))
    wall_thickness: Measure = Field(default_factory=lambda: Measure(value_mm=400, method="assumed"))
    levels: list[Level] = Field(default_factory=list, max_length=30)
    openings: list[Opening] = Field(default_factory=list, max_length=500)
    balconies: list[Balcony] = Field(default_factory=list, max_length=200)
    notes: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        for group in (self.levels, self.openings, self.balconies):
            ids = [x.id for x in group]
            if len(ids) != len(set(ids)):
                raise ValueError("Object IDs must be unique within each category")
        if self.footprint:
            from .footprint import geometry
            g=geometry(self.footprint)
            for name in ['width','depth']:
                m=self.footprint.mm_per_unit.model_copy()
                m.value_mm=g[name+'_mm'] if g else None
                m.source_page=self.footprint.source_page
                m.reviewed=bool(self.footprint.reviewed and m.reviewed)
                setattr(self,name,m)
        return self

def quality(spec: ModelSpec) -> dict:
    """Evidence completeness, never a claimed geometric accuracy percentage."""
    missing, review, conflicts = [], [], []
    from .footprint import facade_map, balcony_polygon, convex_overlap, geometry, overlaps_building
    facades=facade_map(spec)
    footprint_geometry=geometry(spec.footprint) if spec.footprint else None
    measures = {n: getattr(spec, n) for n in ["width", "depth", "eaves", "roof_rise", "wall_thickness"]}
    if spec.footprint:measures.pop('roof_rise')
    measures.update({"level:" + x.id: x.elevation for x in spec.levels})
    for key, m in measures.items():
        if m.value_mm is None:
            missing.append(key)
        elif not m.reviewed:
            review.append(key)
    if not spec.levels:
        missing.append("levels")
    if spec.footprint:
        if spec.footprint.mm_per_unit.value_mm is None:missing.append('footprint scale')
        if not spec.footprint.reviewed:review.append('footprint boundary')
        if not spec.footprint.mm_per_unit.reviewed:review.append('footprint scale')
        # Polygon roof topology is deliberately not invented from the perimeter.
        review.append('polygon roof is a flat placeholder; pitched roof design is pending')
    for key in ["width", "depth", "eaves"]:
        m = getattr(spec, key)
        if m.value_mm is not None and m.value_mm < 1500:
            conflicts.append(key + " must be at least 1500 mm")
    w, h, t = spec.width.value_mm, spec.eaves.value_mm, spec.wall_thickness.value_mm
    if spec.roof_rise.value_mm is not None and spec.roof_rise.value_mm < 0:
        conflicts.append("Roof rise cannot be negative")
    if t is not None and (t < 100 or (w and t * 2 >= w) or (spec.depth.value_mm and t * 2 >= spec.depth.value_mm)):
        conflicts.append("Wall thickness is outside the building envelope")
    levels = {l.id: l.elevation.value_mm for l in spec.levels}
    zs = [z for z in levels.values() if z is not None]
    if len(zs) != len(set(zs)):
        conflicts.append("Duplicate floor elevations")
    if h and any(z >= h for z in zs):
        conflicts.append("A floor is at or above the eaves")
    for o in spec.openings:
        if not o.reviewed:
            review.append("opening:" + o.id)
        f=facades.get(o.facade_id)
        if not f:conflicts.append('Unknown opening facade: '+o.id)
        if f and f['length_mm'] and (o.x_mm + o.width_mm > f['length_mm'] or (h and o.z_mm + o.height_mm > h)):
            conflicts.append("Opening outside facade: " + o.id)
    active = [b for b in spec.balconies if b.status != "excluded"]
    for b in active:
        if b.level_id not in levels or levels[b.level_id] is None:
            conflicts.append("Missing balcony level: " + b.id)
        f=facades.get(b.facade_id)
        if not f:conflicts.append('Unknown balcony facade: '+b.id)
        if f and f['length_mm'] and (b.center_x_mm-b.width_mm/2 < 0 or b.center_x_mm+b.width_mm/2 > f['length_mm']):
            conflicts.append("Balcony outside facade: " + b.id)
        if b.status != "reviewed":
            review.append("balcony:" + b.id)
        if f and footprint_geometry and overlaps_building(balcony_polygon(b,f),footprint_geometry['rings']):
            conflicts.append('Balcony intersects building footprint: '+b.id)
    for i,a in enumerate(active):
        for b in active[i+1:]:
            za,zb=levels.get(a.level_id),levels.get(b.level_id)
            fa,fb=facades.get(a.facade_id),facades.get(b.facade_id)
            if fa and fb and za is not None and zb is not None and max(za-180,zb-180)<min(za+a.guard_height_mm,zb+b.guard_height_mm) and convex_overlap(balcony_polygon(a,fa),balcony_polygon(b,fb)):
                conflicts.append("Overlapping balconies: " + a.id + ", " + b.id)
    checked = sum(m.reviewed and m.value_mm is not None for m in measures.values())
    return {"missing": missing, "review": review, "conflicts": conflicts,
            "reviewed_measurements": checked, "measurement_count": len(measures),
            "can_build_draft": not missing and not conflicts,
            "can_issue_reviewed": not missing and not conflicts and not review}
