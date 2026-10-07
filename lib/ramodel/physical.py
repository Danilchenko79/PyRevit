# -*- coding: utf-8 -*-
"""Collection and parsing of physical load-bearing elements."""
import clr
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory, BuiltInParameter,
                               Wall, WallKind, Floor, FamilyInstance, Opening, XYZ, Line,
                               StorageType, Solid, GeometryInstance, Options, ViewDetailLevel)
from ramodel import util
from ramodel.geom import EPS, dist2d
from ramodel.levels import is_structural_floor

try:
    clr.AddReference('RevitAPIIFC')
    from Autodesk.Revit.DB.IFC import ExporterIFCUtils
except Exception:
    ExporterIFCUtils = None


def is_structural_wall(w):
    p = w.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    return bool(p and p.AsInteger() == 1)


def collect(doc, ids=None, view_id=None):
    """Load-bearing walls, columns, beams, slabs.

    ids     - restrict to a set of ElementId (selection);
    view_id - only elements visible in the view.
    """
    allowed = None if ids is None else set(util.eid_int(i) for i in ids)

    def coll(cat):
        c = FilteredElementCollector(doc, view_id) if view_id else FilteredElementCollector(doc)
        return c.OfCategory(cat).WhereElementIsNotElementType().ToElements()

    def ok(e):
        return allowed is None or util.eid_int(e.Id) in allowed

    walls = []
    for w in coll(BuiltInCategory.OST_Walls):
        if not isinstance(w, Wall) or not ok(w) or not is_structural_wall(w):
            continue
        if w.WallType.Kind in (WallKind.Stacked, WallKind.Curtain):
            continue
        walls.append(w)
    cols = [c for c in coll(BuiltInCategory.OST_StructuralColumns)
            if isinstance(c, FamilyInstance) and ok(c)]
    beams = [b for b in coll(BuiltInCategory.OST_StructuralFraming)
             if isinstance(b, FamilyInstance) and ok(b)]
    floors = [f for f in coll(BuiltInCategory.OST_Floors)
              if isinstance(f, Floor) and ok(f) and is_structural_floor(f)]
    return {'walls': walls, 'columns': cols, 'beams': beams, 'floors': floors}


def all_elements(sets):
    res = []
    for k in ('walls', 'columns', 'beams', 'floors'):
        res.extend(sets[k])
    return res


# --------------------------------------------------------------------- walls

def core_offset(wall):
    """(offset from the location line to the core axis along wall.Orientation, core thickness), ft."""
    w = wall.Width
    core_ext, core_int = w / 2.0, -w / 2.0
    cs = wall.WallType.GetCompoundStructure()
    if cs is not None:
        try:
            layers = cs.GetLayers()
            first = cs.GetFirstCoreLayerIndex()
            last = cs.GetLastCoreLayerIndex()
            pos = w / 2.0      # exterior face
            ext = intr = None
            for i in range(layers.Count):
                if i == first:
                    ext = pos
                pos -= layers[i].Width
                if i == last:
                    intr = pos
            if ext is not None and intr is not None and ext - intr > EPS:
                core_ext, core_int = ext, intr
        except Exception:
            pass
    core_c = (core_ext + core_int) / 2.0
    p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
    key = p.AsInteger() if p else 0
    loc = {0: 0.0, 1: core_c, 2: w / 2.0, 3: -w / 2.0, 4: core_ext, 5: core_int}.get(key, 0.0)
    return core_c - loc, core_ext - core_int


class WallInfo(object):
    """Wall core axis in plan, thickness, bottom and top elevations."""

    def __init__(self, wall):
        self.wall = wall
        self.ok = False
        self.reason = u''
        loc = wall.Location
        crv = getattr(loc, 'Curve', None)
        if not isinstance(crv, Line):
            self.reason = u'curved wall or no location line'
            return
        off, self.t = core_offset(wall)
        self.normal = wall.Orientation
        shift = self.normal.Multiply(off)
        a = crv.GetEndPoint(0).Add(shift)
        b = crv.GetEndPoint(1).Add(shift)
        self.p0 = XYZ(a.X, a.Y, 0.0)
        self.p1 = XYZ(b.X, b.Y, 0.0)
        if dist2d(self.p0, self.p1) < 10 * EPS:
            self.reason = u'zero length'
            return
        self.set_line(self.p0, self.p1)
        self.orig_p0, self.orig_p1 = self.p0, self.p1
        self.width = wall.Width
        self.id = util.eid_int(wall.Id)
        self.bands = []
        # elevations after snapping to slab axes (filled by align.Aligner)
        self.ax_bot = self.ax_top = None
        self.zb = self.zt = None
        bb = wall.get_BoundingBox(None)
        if bb is None:
            self.reason = u'no geometry'
            return
        self.z0, self.z1 = bb.Min.Z, bb.Max.Z
        self.ok = True

    def set_line(self, p0, p1):
        """New axis in plan (after alignment)."""
        self.p0 = XYZ(p0.X, p0.Y, 0.0)
        self.p1 = XYZ(p1.X, p1.Y, 0.0)
        self.L = dist2d(self.p0, self.p1)
        self.d = self.p1.Subtract(self.p0).Normalize()

    def mid(self):
        return self.pt(self.L / 2.0, 0.0)

    def pt(self, s, z):
        """Point on the axis at distance s from the start, at elevation z."""
        return XYZ(self.p0.X + self.d.X * s, self.p0.Y + self.d.Y * s, z)

    def param(self, p):
        return (p.X - self.p0.X) * self.d.X + (p.Y - self.p0.Y) * self.d.Y

    def offset(self, p):
        """Distance from a point to the wall axis in plan."""
        return abs((p.X - self.p0.X) * self.d.Y - (p.Y - self.p0.Y) * self.d.X)

    def plan_bbox(self):
        return (min(self.p0.X, self.p1.X), min(self.p0.Y, self.p1.Y),
                max(self.p0.X, self.p1.X), max(self.p0.Y, self.p1.Y))


def is_slanted_wall(wall):
    """Slanted wall, Revit 2021+ (cross-section "Slanted")."""
    try:
        from Autodesk.Revit.DB import WallCrossSection
    except Exception:
        return False             # no slanted walls before Revit 2021
    try:
        return wall.CrossSection != WallCrossSection.Vertical
    except Exception:
        pass
    try:                         # enum values: SingleSlanted=0, Vertical=1, Tapered=2
        p = wall.get_Parameter(BuiltInParameter.WALL_CROSS_SECTION)
        return bool(p and p.AsInteger() != int(WallCrossSection.Vertical))
    except Exception:
        return False


def _bbox_corners(bb):
    res = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                res.append(XYZ(x, y, z))
    return res


def opening_points(doc, wall, el):
    """Opening outline points and the method used to obtain them."""
    if isinstance(el, Opening):
        try:
            if el.IsRectBoundary:
                return list(el.BoundaryRect), 'rect'
            return [c.GetEndPoint(0) for c in el.BoundaryCurves], 'curves'
        except Exception:
            pass
    if isinstance(el, FamilyInstance) and ExporterIFCUtils is not None:
        try:
            res = ExporterIFCUtils.GetInstanceCutoutFromWall(doc, wall, el)
            loop = res[0] if isinstance(res, tuple) else res
            pts = []
            for c in loop:
                pts.extend(c.Tessellate())
            if pts:
                return pts, 'cutout'
        except Exception:
            pass
    bb = el.get_BoundingBox(None)
    if bb is not None:
        return _bbox_corners(bb), 'bbox'
    return None, None


def wall_openings(doc, wi):
    """Wall openings: dict(id, t0, t1, z0, z1, src). t - along the axis from the start, ft."""
    res = []
    try:
        ids = wi.wall.FindInserts(True, False, True, True)     # + embedded curtain walls
    except Exception:
        return res
    for iid in ids:
        el = doc.GetElement(iid)
        if el is None:
            continue
        pts, src = opening_points(doc, wi.wall, el)
        if not pts:
            continue
        ts = [wi.param(p) for p in pts]
        zs = [p.Z for p in pts]
        t0, t1 = max(min(ts), 0.0), min(max(ts), wi.L)
        if t1 - t0 <= EPS:
            continue
        res.append({'id': iid, 't0': t0, 't1': t1, 'z0': min(zs), 'z1': max(zs), 'src': src})
    res.sort(key=lambda o: o['t0'])
    return res


# ------------------------------------------------------------------- sections

AREA_TOL = 0.03          # section area deviation from b*h (or pi*d^2/4), fraction
_SECTION_CACHE = {}


def _from_structural_section(symbol):
    """From the type "Section Shape" (Revit 2020+). Solid rectangle and circle only."""
    try:
        ss = symbol.GetStructuralSection()
    except Exception:
        return None
    if ss is None:
        return None
    name = ss.GetType().Name.lower()
    if 'hollow' in name or 'pipe' in name or 'tube' in name:
        return None
    try:
        if ('round' in name or 'circ' in name) and ss.Diameter > EPS:
            return 'round', ss.Diameter, ss.Diameter
        if 'rect' in name and ss.Width > EPS and ss.Height > EPS:
            return 'rect', ss.Width, ss.Height
    except Exception:
        pass
    return None


def _solids(geo, out):
    for g in geo:
        if isinstance(g, Solid) and g.Volume > EPS:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            _solids(g.GetSymbolGeometry(), out)
    return out


def _from_geometry(symbol):
    """From the type geometry in family coordinates: beam axis along X, width along Y,
    height along Z; column axis along Z, section in the XY plane. The shape is
    determined by the area V/L."""
    opts = Options()
    opts.DetailLevel = ViewDetailLevel.Fine
    geo = symbol.get_Geometry(opts)
    solids = _solids(geo, []) if geo is not None else []
    if not solids:
        return None
    lo, hi = [1e9] * 3, [-1e9] * 3
    for s in solids:
        bb = s.GetBoundingBox()
        for p in (bb.Min, bb.Max):
            q = bb.Transform.OfPoint(p)
            for i, c in enumerate((q.X, q.Y, q.Z)):
                lo[i] = min(lo[i], c)
                hi[i] = max(hi[i], c)
    ext = [hi[i] - lo[i] for i in range(3)]
    is_col = (symbol.Category is not None and
              symbol.Category.Id.IntegerValue == int(BuiltInCategory.OST_StructuralColumns))
    L, b, h = (ext[2], ext[0], ext[1]) if is_col else (ext[0], ext[1], ext[2])
    if L < EPS or b < EPS or h < EPS:
        return None
    area = sum(s.Volume for s in solids) / L
    if abs(area - b * h) <= AREA_TOL * b * h:
        return 'rect', b, h
    d = (b + h) / 2.0
    circle = 3.141592653589793 * d * d / 4.0
    if abs(b - h) <= AREA_TOL * d and abs(area - circle) <= AREA_TOL * circle:
        return 'round', d, d
    return None


def section_dims(symbol, cfg=None):
    """('rect', b, h) | ('round', d, d) | (None, None, None). Dimensions in ft.
    Independent of parameter names: type "Section Shape", otherwise type geometry."""
    if symbol is None:
        return None, None, None
    key = (symbol.Document.Title, symbol.Id.IntegerValue)
    if key not in _SECTION_CACHE:
        res = None
        try:
            res = _from_structural_section(symbol) or _from_geometry(symbol)
        except Exception:
            res = None
        _SECTION_CACHE[key] = res or (None, None, None)
    return _SECTION_CACHE[key]


def section_kind_label(kind, b, h):
    if kind == 'rect':
        return u'{}x{}'.format(util.mm(b), util.mm(h))
    if kind == 'round':
        return u'Ø{}'.format(util.mm(b))
    return u'?'
