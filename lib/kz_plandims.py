# -*- coding: utf-8 -*-
"""kz_plandims - linear dimensions on a slab plan (RE view).

Rules come from two reference sets, PRKL-S-BLD 160B and GFN-ST-3 140-3:

    * dimensions live only on the RE view (Ceiling Plan, template PEER RE);
      the matching GR view stays clean,
    * one dimension type, PEER-Linear, never a value override,
    * every witness point is an element FACE - no grid, no wall centreline,
    * an outer chain hugs the facade it measures, it does not float at the
      bounding box; a cross-shaped plan therefore gets one local chain per
      facade run plus one overall chain,
    * interior chains run along the main internal wall lines and pick up
      every wall, opening or slab edge they cross - thickness, clear span,
      thickness, clear span.

What each chain is made of:

    LOCAL   one per facade run. The silhouette of a side is split into runs
            of similar depth; each run gets a chain 10 paper mm off its own
            edge with a point at every jog and, optionally, every opening
            jamb in the facade wall.
    OVERALL one per side, one row further out than the outermost local
            chain, two points: the extreme faces of the building.
    INTERIOR one per major internal wall line. Points are all faces
            perpendicular to the line that touch the wall band.

The building outline is taken from walls and columns only. Slabs and beams
are excluded on purpose: cantilever balconies and their edge beams would
stretch the overall size (23730 -> 29790 mm on PRKL 160RE).

Placement never trusts the first guess: a line that would run through
outline geometry or on top of a chain already placed is pushed outward
row by row until it is clear.

Rerun safety: chains made here carry a duplicate of the base type named
"PEER-Linear (AUTO)". Only those are removed on the next run, so
hand-drawn chains survive.

Links: the documentation model often holds nothing but views, with the
concrete sitting in a linked structural model. Geometry is therefore read
from a list of SOURCES (kz_links) - the host first, then every loaded link
that carries structure - and everything a source yields is put into host
coordinates before it is measured. A face of a linked element becomes
dimensionable through a link reference; the view, the annotation on it and
the chains we make stay in the host document.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, ElementId, Element,
    Transaction, TransactionGroup, XYZ, Line, Solid,
    GeometryInstance, PlanarFace, PlanViewPlane, ReferenceArray, Reference,
    Dimension, Wall, ElementCategoryFilter, LogicalOrFilter,
)

from System.Collections.Generic import List

from AutoSections.convert import mm, to_ft
from kz_dress import find_dim_type
import kz_links

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

SIDES = ('BOTTOM', 'TOP', 'LEFT', 'RIGHT')

LOCAL_ROWS = True              # a chain per facade run
OVERALL_ROW = True             # one overall chain per side
INTERIOR_ROWS = True           # chains along internal wall lines
INCLUDE_OPENINGS = True        # opening jambs in facade walls join the local chain
GRID_ROWS = False              # a chain of grid spacings per side; the button asks

CORE_ONLY = True               # bind to the structural core, not to finish layers
MIN_FACE_AREA_M2 = 0.001       # a face smaller than this is a joint artefact
AVOID_ANNOTATION = True        # keep chains off existing text, tags and dimensions
ANNOTATION_CLEAR_MM = 2.0      # paper mm of air to leave around existing annotation
SLAB_EDGES = True              # balconies: depth from the wall and width along the edge
SLAB_HOLES = True              # openings in the slab: extents from the nearest wall
LOCATE_WALLS = True            # every wall left unreferenced gets a short chain of its own

SLAB_OUT_TOL_MM = 100.0        # a slab edge further out than this is a cantilever
SLAB_RIM_TOL_MM = 450.0        # a slab edge this close to the walls is the perimeter, not a hole
SLAB_MIN_THICK_MM = 120.0      # thinner slab pieces are toppings, not structure
BALCONY_DEPTH_MM = (300.0, 4000.0)   # a cantilever outside this range is not a balcony
HOLE_SIZE_MM = (300.0, 6000.0)       # a slab hole outside this range is not dimensioned
LOCATE_MAX_REACH_MM = 12000.0  # farthest anchor a locating chain may reach for

FIRST_OFFSET_PAPER_MM = 10.0   # first row, paper mm off the edge it measures
ROW_GAP_PAPER_MM = 10.0        # gap between rows, paper mm

RUN_GROUP_TOL_MM = 1000.0      # contiguous silhouette pieces within this depth form one run
MIN_RUN_MM = 1500.0            # a run shorter than this merges into its neighbour
JAMB_END_MARGIN_MM = 150.0     # a face closer than this to a wall end is not a jamb

INTERIOR_MIN_FRACTION = 0.12   # wall line must cover this share of the plan...
INTERIOR_MIN_LENGTH_MM = 3500.0  # ...and be at least this long to get a chain
INTERIOR_MIN_SPACING_MM = 1500.0 # lines closer than this share one chain (longer wins)
INTERIOR_MAX_PER_AXIS = 8      # longest lines first
INTERIOR_CLUSTER_MM = 120.0    # walls whose centrelines sit within this are one line
INTERIOR_BAND_EXTRA_MM = 50.0  # how far past the wall faces a point may sit and still count

MERGE_TOL_MM = 5.0             # points closer than this are one point
MIN_SEGMENT_MM = 100.0         # never create a segment shorter than this
REF_SEARCH_TOL_MM = 60.0       # how far to look for the face under a point
DUPLICATE_DROP_FRACTION = 1.0  # a chain whose every segment is already shown is dropped
MAX_WITNESS_MM = 3000.0        # a face further than this from the line is not a witness
OVERALL_MAX_WITNESS_MM = 6000.0  # the overall chain may reach a little further
CLEAR_TRIES = 6                # how many rows outward a blocked line may move

BASE_TYPE = u'PEER-Linear'
AUTO_SUFFIX = u' (AUTO)'
TEMPLATE_HINT = u'PEER RE'

# Anything that may become a witness point.
CATEGORIES = (
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Floors,
    BuiltInCategory.OST_StructuralFraming,
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_Columns,
)

# What defines the building outline. Slabs and beams stay out.
OUTLINE_CATEGORIES = (
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_Columns,
)

# What an interior chain may bind to. Beams and slab edges along a wall
# line only add 100 mm noise, so walls alone by default.
INTERIOR_CATEGORIES = (
    BuiltInCategory.OST_Walls,
)

AXIS_TOL = 0.999               # how closely a normal must follow an axis
VERTICAL_TOL = 0.02            # how closely a normal must stay horizontal

BELOW_SLAB_ONLY = True         # bind only to elements that start below the view level
BELOW_SLAB_TOL_MM = 100.0      # an element whose base is this close to the level counts as "on" it

# side -> (sweep along X?, take the minimum coordinate?)
SIDE_SPEC = {
    'BOTTOM': (True, True),
    'TOP': (True, False),
    'LEFT': (False, True),
    'RIGHT': (False, False),
}


# ---------------------------------------------------------------------------
# Geometry records
# ---------------------------------------------------------------------------

class FaceRec(object):
    """One planar vertical face flattened onto the plan, in host coordinates."""

    __slots__ = ('ref', 'nx', 'ny', 'xmin', 'xmax', 'ymin', 'ymax',
                 'elem_id', 'in_outline', 'bic', 'height', 'src_idx')

    def __init__(self, ref, nx, ny, xmin, xmax, ymin, ymax,
                 elem_id, in_outline, bic, height=0.0, src_idx=0):
        self.ref = ref
        self.nx = nx
        self.ny = ny
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax
        self.elem_id = elem_id
        self.in_outline = in_outline
        self.bic = bic
        self.height = height   # vertical extent: for a slab edge, the slab thickness
        self.src_idx = src_idx  # which source it came from; 0 is the host

    @property
    def key(self):
        """Identity across documents: element ids repeat from one to the next."""
        return (self.src_idx, self.elem_id)

    def perp_to(self, scan_is_x):
        """Does the face normal run along the sweep axis (X for H chains)?"""
        return abs(self.nx) >= AXIS_TOL if scan_is_x else abs(self.ny) >= AXIS_TOL

    def pos(self, scan_is_x):
        """Position along the sweep axis (meaningful for perpendicular faces)."""
        return 0.5 * (self.xmin + self.xmax) if scan_is_x else 0.5 * (self.ymin + self.ymax)

    def span(self, scan_is_x):
        """Extent along the sweep axis."""
        return (self.xmin, self.xmax) if scan_is_x else (self.ymin, self.ymax)

    def cross(self, scan_is_x):
        """Extent across the sweep axis."""
        return (self.ymin, self.ymax) if scan_is_x else (self.xmin, self.xmax)


class WallRec(object):
    """A straight wall as a band on the plan, in host coordinates."""

    __slots__ = ('elem_id', 'axis', 'a', 'b', 'c', 'hw', 'src_idx')

    def __init__(self, elem_id, axis, a, b, c, hw, src_idx=0):
        self.elem_id = elem_id
        self.axis = axis      # 'X', 'Y' or 'SKEW'
        self.a = a            # span start along its axis
        self.b = b            # span end along its axis
        self.c = c            # centreline position across its axis
        self.hw = hw          # half width
        self.src_idx = src_idx  # which source it came from; 0 is the host

    @property
    def key(self):
        """Identity across documents: element ids repeat from one to the next."""
        return (self.src_idx, self.elem_id)


def _iter_solids(geo, xform):
    """Yield (solid, transform), walking nested instances.

    Nested instances go through GetSymbolGeometry, not GetInstanceGeometry:
    only symbol geometry carries a Reference a dimension can bind to. The
    accumulated transform puts the points back into model space.
    """
    if geo is None:
        return
    for obj in geo:
        if isinstance(obj, GeometryInstance):
            for item in _iter_solids(obj.GetSymbolGeometry(),
                                     xform.Multiply(obj.Transform)):
                yield item
        elif isinstance(obj, Solid):
            try:
                if obj.Faces.Size > 0:
                    yield (obj, xform)
            except Exception:
                continue


def _face_bounds(face, xform):
    xs = []
    ys = []
    zs = []
    try:
        for loop in face.EdgeLoops:
            for edge in loop:
                for p in edge.Tessellate():
                    q = xform.OfPoint(p)
                    xs.append(q.X)
                    ys.append(q.Y)
                    zs.append(q.Z)
    except Exception:
        return None
    if not xs:
        return None
    return (min(xs), max(xs), min(ys), max(ys), max(zs) - min(zs))


def _is_core_face(el, face, doc):
    """For a layered wall, is this face on the structural core?

    Single-layer walls (all the concrete ones here) pass straight through.
    On a layered wall a face is accepted when it lies on a core boundary,
    so finish layers never carry a dimension.
    """
    if not isinstance(el, Wall):
        return True
    try:
        cs = doc.GetElement(el.GetTypeId()).GetCompoundStructure()
    except Exception:
        return True
    if cs is None or cs.LayerCount <= 1:
        return True
    try:
        first = cs.GetFirstCoreLayerIndex()
        last = cs.GetLastCoreLayerIndex()
        inner = 0.0
        outer = 0.0
        for i in range(cs.LayerCount):
            w = cs.GetLayerWidth(i)
            if i < first:
                inner += w
            if i > last:
                outer += w
        half = 0.5 * el.Width
        # distance from the wall centreline to each core boundary
        core_out = half - inner
        core_in = half - outer
        n = face.FaceNormal
        if abs(n.Z) > VERTICAL_TOL:
            return True
        lc = el.Location.Curve
        p0 = lc.GetEndPoint(0)
        o = face.Origin
        d = abs((o.X - p0.X) * n.X + (o.Y - p0.Y) * n.Y)
        tol = to_ft(REF_SEARCH_TOL_MM)
        return abs(d - core_out) <= tol or abs(d - core_in) <= tol
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def plan_sources(doc, view):
    """The documents this view takes geometry from, the host first.

    A link that carries no structure at all - furniture, MEP, the site -
    is left out: walking it costs time and can only drag foreign geometry
    into a chain. The host stays in the list even when it holds nothing,
    so a model without links behaves exactly as it did before.
    """
    srcs = kz_links.structural_sources(doc, view, CATEGORIES)
    if not srcs or srcs[0].is_link:
        srcs.insert(0, kz_links.sources(doc, view, include_links=False)[0])
    return srcs


def _collector(src, view, bic):
    """Elements of one category in one source.

    A view id belongs to the host document, so a linked element cannot be
    filtered by the view at all: the whole link is collected and cut down
    afterwards by the crop and the view level.
    """
    col = (FilteredElementCollector(src.doc) if src.is_link
           else FilteredElementCollector(src.doc, view.Id))
    return col.OfCategory(bic).WhereElementIsNotElementType()


def _host_box(el, src):
    """(xmin, xmax, ymin, ymax, zmin, zmax) of an element, in host coordinates."""
    if src.is_link:
        return kz_links.host_bbox(el, src.xform)
    try:
        bb = el.get_BoundingBox(None)
    except Exception:
        return None
    if bb is None:
        return None
    return (bb.Min.X, bb.Max.X, bb.Min.Y, bb.Max.Y, bb.Min.Z, bb.Max.Z)


def crop_bounds(view):
    """Plan extents of an active crop box in host coordinates, else None."""
    try:
        if not view.CropBoxActive:
            return None
        cb = view.CropBox
    except Exception:
        return None
    if cb is None:
        return None
    xs = []
    ys = []
    for x in (cb.Min.X, cb.Max.X):
        for y in (cb.Min.Y, cb.Max.Y):
            for z in (cb.Min.Z, cb.Max.Z):
                q = cb.Transform.OfPoint(XYZ(x, y, z))
                xs.append(q.X)
                ys.append(q.Y)
    return (min(xs), max(xs), min(ys), max(ys))


def _outside_crop(box, crop):
    """Is the element wholly outside the crop? An unknown box stays in."""
    if crop is None or box is None:
        return False
    return (box[1] < crop[0] or box[0] > crop[1]
            or box[3] < crop[2] or box[2] > crop[3])


def view_ceiling(view):
    """Elevation above which an element is not what this plan is about.

    The RE view range reaches 10 mm above the slab, so the walls that
    START on this slab show up as a projected sliver next to the cut walls
    from below. Both have the same footprint; only the cut ones are what
    the sheet is about, and a dimension tied to the sliver has nothing
    visible to hang on. Keep elements that begin below the slab.

    Level.Elevation is measured from the project base point; bounding
    boxes are in internal coordinates. ProjectElevation is the one that
    matches geometry - on KRM the two differ by 844 mm.
    """
    if not BELOW_SLAB_ONLY:
        return None
    try:
        if view.GenLevel is not None:
            return view.GenLevel.ProjectElevation - to_ft(BELOW_SLAB_TOL_MM)
    except Exception:
        return None
    return None


def view_floor(view):
    """Bottom of the view range in host coordinates, or None when unlimited.

    The host collector already drops whatever the view range excludes. A
    linked element is seen by no view at all, so without this bound every
    storey of the link would arrive at once and the footprints of the
    floors below would be measured together with this one.

    The lower of the two bottom planes wins, and an unlimited one means no
    bound: the rule has to match what Revit draws, never cut deeper.
    """
    try:
        vr = view.GetViewRange()
    except Exception:
        return None
    lo = None
    for plane in (PlanViewPlane.ViewDepthPlane, PlanViewPlane.BottomClipPlane):
        try:
            lid = vr.GetLevelId(plane)
            if lid == ElementId.InvalidElementId:
                return None
            lvl = view.Document.GetElement(lid)
            if lvl is None:
                return None
            z = lvl.ProjectElevation + vr.GetOffset(plane)
        except Exception:
            continue    # a ceiling plan has no view depth plane
        lo = z if lo is None else min(lo, z)
    return lo


def _link_visible(el, src, crop, ceiling, floor):
    """Cut a linked element down to what the host view would have shown.

    Three tests stand in for the view filter the host gets for free: the
    element must reach into the view range from below, must start below
    the slab, and must touch the crop. A box that cannot be read keeps the
    element - dimensioning something extra beats missing a wall.
    """
    box = _host_box(el, src)
    if box is None:
        return True
    if ceiling is not None and box[4] >= ceiling:
        return False
    # the same slack the ceiling test uses, so an element ending exactly on
    # the bottom plane is kept rather than lost to rounding
    if floor is not None and box[5] < floor - to_ft(BELOW_SLAB_TOL_MM):
        return False
    return not _outside_crop(box, crop)


def selection_filter(srcs, only):
    """Predicate over FaceRec/WallRec for the user's pre-selection.

    `only` holds ids of the HOST document: an element id means that
    element, the id of a RevitLinkInstance means everything that link
    holds - a single element inside a link cannot be picked in the host.
    """
    whole = set()
    for src in srcs:
        if src.is_link and src.link.Id.IntegerValue in only:
            whole.add(src.index)

    def keep(rec):
        return rec.src_idx in whole or (rec.src_idx == 0 and rec.elem_id in only)
    return keep


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect_faces(doc, view, srcs=None):
    """Every vertical axis-aligned face of the elements visible on the view.

    Read from every source and reported in host coordinates: the solid walk
    starts with the source transform, so both the normals and the bounds of
    a linked face come out in the space the chains are built in.
    """
    if srcs is None:
        srcs = plan_sources(doc, view)
    crop = crop_bounds(view)
    ceiling = view_ceiling(view)
    floor = view_floor(view)

    recs = []
    skipped = 0
    for src in srcs:
        opts = kz_links.source_options(src, view)
        for bic in CATEGORIES:
            in_outline = bic in OUTLINE_CATEGORIES
            try:
                col = _collector(src, view, bic)
            except Exception:
                continue
            for el in col:
                if src.is_link:
                    if not _link_visible(el, src, crop, ceiling, floor):
                        continue
                elif ceiling is not None:
                    box = _host_box(el, src)
                    if box is not None and box[4] >= ceiling:
                        continue
                try:
                    geo = el.get_Geometry(opts)
                except Exception:
                    skipped += 1
                    continue
                for solid, xf in _iter_solids(geo, src.xform):
                    for face in solid.Faces:
                        if not isinstance(face, PlanarFace):
                            continue
                        try:
                            n = xf.OfVector(face.FaceNormal)
                        except Exception:
                            continue
                        if abs(n.Z) > VERTICAL_TOL:
                            continue
                        if abs(n.X) < AXIS_TOL and abs(n.Y) < AXIS_TOL:
                            continue
                        if face.Reference is None:
                            continue
                        # A T- or L-joint between walls leaves slivers of face
                        # behind; they carry a valid reference and would anchor
                        # a dimension to something invisible on the sheet.
                        try:
                            if face.Area < MIN_FACE_AREA_M2 / 0.092903:
                                continue
                        except Exception:
                            pass
                        # the wall type lives in the element's own document
                        if CORE_ONLY and not _is_core_face(el, face, src.doc):
                            continue
                        ref = src.ref(face.Reference)
                        if ref is None:
                            continue   # a linked face the host cannot bind to
                        bb = _face_bounds(face, xf)
                        if bb is None:
                            continue
                        recs.append(FaceRec(ref, n.X, n.Y,
                                            bb[0], bb[1], bb[2], bb[3],
                                            el.Id.IntegerValue, in_outline, bic,
                                            bb[4], src.index))
    return recs, skipped


def collect_grids(doc, view, srcs=None):
    """Grids visible on the view, as {'scan', 'pos', 'ref', 'name'}.

    scan is True for a grid that a horizontal chain measures, i.e. a grid
    line running along Y. The reference is the grid itself, which is what
    Revit dimensions to; a linked grid goes through a link reference.
    Positions are host coordinates, and a linked grid sitting on a host one
    is dropped: the host grid is the one the sheet is drawn on.
    """
    if srcs is None:
        srcs = plan_sources(doc, view)
    tol = to_ft(MERGE_TOL_MM)
    out = []
    for src in srcs:
        try:
            col = _collector(src, view, BuiltInCategory.OST_Grids)
        except Exception:
            continue
        for g in col:
            try:
                c = g.Curve
                a = src.to_host(c.GetEndPoint(0))
                b = src.to_host(c.GetEndPoint(1))
            except Exception:
                continue
            dx = abs(b.X - a.X)
            dy = abs(b.Y - a.Y)
            if dy > dx * 100.0:
                rec = {'scan': True, 'pos': 0.5 * (a.X + b.X),
                       'lo': min(a.Y, b.Y), 'hi': max(a.Y, b.Y),
                       'name': g.Name}
            elif dx > dy * 100.0:
                rec = {'scan': False, 'pos': 0.5 * (a.Y + b.Y),
                       'lo': min(a.X, b.X), 'hi': max(a.X, b.X),
                       'name': g.Name}
            else:
                continue
            if src.is_link and any(o['scan'] == rec['scan']
                                   and abs(o['pos'] - rec['pos']) <= tol
                                   for o in out):
                continue
            ref = src.ref(Reference(g))
            if ref is None:
                continue
            rec['ref'] = ref
            out.append(rec)
    return out


def grid_chains(grids, view, box, rows, gap, first):
    """One chain of grid spacings per side, outside the local rows."""
    if not grids:
        return []
    x0, x1, y0, y1 = box
    out = []
    for scan_is_x, side in ((True, 'BOTTOM'), (False, 'LEFT')):
        gs = sorted([g for g in grids if g['scan'] == scan_is_x], key=lambda g: g['pos'])
        if len(gs) < 2:
            continue
        pts = [(g['pos'], g) for g in gs]
        a, b = pts[0][0], pts[-1][0]
        edge = y0 if scan_is_x else x0
        outer = edge - first
        for pc, pa, pb in rows[scan_is_x]:
            if pc < outer and pb > a and pa < b:
                outer = pc
        const = clear_const(outer - gap, -gap,
                            [lambda c, _r=rows[scan_is_x], _a=a, _b=b: _row_blocks(_r, c, _a, _b, gap)])
        rows[scan_is_x].append((const, a, b))
        out.append({'kind': 'GRID', 'side': side, 'scan_is_x': scan_is_x,
                    'const': const, 'points': pts, 'grid': True,
                    'label': u'{} grid spacings'.format(side)})
    return out


def collect_walls(doc, view, srcs=None):
    """Straight walls on the view as bands, in host coordinates.

    The location curve is put into host space before the X/Y/SKEW
    classification, so a band of a linked wall lands where its faces do.
    """
    if srcs is None:
        srcs = plan_sources(doc, view)
    crop = crop_bounds(view)
    ceiling = view_ceiling(view)
    floor = view_floor(view)
    out = []
    for src in srcs:
        try:
            col = _collector(src, view, BuiltInCategory.OST_Walls)
        except Exception:
            continue
        for w in col:
            if not isinstance(w, Wall):
                continue
            if src.is_link and not _link_visible(w, src, crop, ceiling, floor):
                continue
            try:
                lc = w.Location.Curve
                p0 = src.to_host(lc.GetEndPoint(0))
                p1 = src.to_host(lc.GetEndPoint(1))
                hw = 0.5 * w.Width
            except Exception:
                continue
            dx = abs(p1.X - p0.X)
            dy = abs(p1.Y - p0.Y)
            if dx > dy * 100.0:
                out.append(WallRec(w.Id.IntegerValue, 'X',
                                   min(p0.X, p1.X), max(p0.X, p1.X),
                                   0.5 * (p0.Y + p1.Y), hw, src.index))
            elif dy > dx * 100.0:
                out.append(WallRec(w.Id.IntegerValue, 'Y',
                                   min(p0.Y, p1.Y), max(p0.Y, p1.Y),
                                   0.5 * (p0.X + p1.X), hw, src.index))
            else:
                out.append(WallRec(w.Id.IntegerValue, 'SKEW',
                                   0.0, 0.0, 0.0, hw, src.index))

    # Walls stacked on the same footprint (the wall below the slab and the
    # one starting on it both fall into the RE view range) count once,
    # otherwise every wall line looks twice as long as it is. The match is
    # on geometry, not on identity, so the same wall present in the host
    # and in a link collapses the same way - the host copy comes first and
    # is the one kept.
    tol = to_ft(MERGE_TOL_MM)
    unique = []
    for w in out:
        dup = False
        for u in unique:
            if (u.axis == w.axis and abs(u.c - w.c) <= tol
                    and abs(u.a - w.a) <= tol and abs(u.b - w.b) <= tol
                    and abs(u.hw - w.hw) <= tol):
                dup = True
                break
        if not dup:
            unique.append(w)
    return unique


# ---------------------------------------------------------------------------
# Silhouette
# ---------------------------------------------------------------------------

def _subtract(a, b, covered):
    free = [(a, b)]
    for cs, ce in covered:
        nxt = []
        for fs, fe in free:
            if ce <= fs or cs >= fe:
                nxt.append((fs, fe))
                continue
            if cs > fs:
                nxt.append((fs, cs))
            if ce < fe:
                nxt.append((ce, fe))
        free = nxt
        if not free:
            break
    return free


def _insert(covered, a, b):
    items = list(covered)
    items.append((a, b))
    items.sort()
    out = []
    for it in items:
        if out and it[0] <= out[-1][1] + 1e-9:
            if it[1] > out[-1][1]:
                out[-1] = (out[-1][0], it[1])
        else:
            out.append((it[0], it[1]))
    return out


def build_profile(faces, scan_is_x, take_min):
    """Edge profile of one side, outline categories only.

    Returns [start, end, value, face] pieces sorted by start. A face
    perpendicular to the sweep has no span and drops out, so only faces
    running along the sweep shape the profile - which is what a silhouette is.
    """
    items = []
    for fr in faces:
        if not fr.in_outline:
            continue
        a, b = fr.span(scan_is_x)
        lo, hi = fr.cross(scan_is_x)
        v = lo if take_min else hi
        if b - a < to_ft(1.0):
            continue
        items.append((v, a, b, fr))

    items.sort(key=lambda t: t[0], reverse=(not take_min))

    covered = []
    raw = []
    for v, a, b, fr in items:
        for fa, fb in _subtract(a, b, covered):
            if fb - fa < to_ft(1.0):
                continue
            raw.append((fa, fb, v, fr))
            covered = _insert(covered, fa, fb)
    raw.sort(key=lambda p: p[0])

    tol = to_ft(MERGE_TOL_MM)
    merged = []
    for p in raw:
        if (merged and abs(merged[-1][2] - p[2]) <= tol
                and abs(merged[-1][1] - p[0]) <= tol):
            merged[-1][1] = p[1]
        else:
            merged.append([p[0], p[1], p[2], p[3]])
    return merged


def profile_value_at(pieces, pos):
    for a, b, v, _f in pieces:
        if a - 1e-9 <= pos <= b + 1e-9:
            return v
    return None


def group_runs(pieces, take_min):
    """Split a profile into facade runs.

    Contiguous pieces whose depth differs by less than RUN_GROUP_TOL form
    one run; runs shorter than MIN_RUN merge into the neighbour whose depth
    is closer. Each run is {'a', 'b', 'level', 'pieces'} where level is the
    outermost depth inside the run.
    """
    if not pieces:
        return []
    gtol = to_ft(RUN_GROUP_TOL_MM)
    runs = []
    cur = None
    for p in pieces:
        if cur is None:
            cur = {'a': p[0], 'b': p[1], 'pieces': [p]}
            continue
        gap = p[0] - cur['b']
        lv = cur['pieces'][0][2]
        # extreme of the current run
        for q in cur['pieces']:
            if take_min:
                lv = min(lv, q[2])
            else:
                lv = max(lv, q[2])
        if gap <= gtol and abs(p[2] - lv) <= gtol:
            cur['pieces'].append(p)
            cur['b'] = p[1]
        else:
            runs.append(cur)
            cur = {'a': p[0], 'b': p[1], 'pieces': [p]}
    if cur is not None:
        runs.append(cur)

    def relevel(r):
        vals = [q[2] for q in r['pieces']]
        r['level'] = min(vals) if take_min else max(vals)

    def absorb(i, j):
        """Fold run i into run j."""
        tgt = runs[j]
        src = runs[i]
        tgt['pieces'] = sorted(tgt['pieces'] + src['pieces'], key=lambda q: q[0])
        tgt['a'] = min(tgt['a'], src['a'])
        tgt['b'] = max(tgt['b'], src['b'])
        relevel(tgt)
        del runs[i]

    for r in runs:
        relevel(r)

    # Fold short runs into the neighbour of closer depth, then fuse
    # neighbours that ended up at the same depth; repeat until stable.
    min_run = to_ft(MIN_RUN_MM)
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r['b'] - r['a'] >= min_run:
                continue
            cands = []
            if i > 0:
                cands.append(i - 1)
            if i < len(runs) - 1:
                cands.append(i + 1)
            j = min(cands, key=lambda k: abs(runs[k]['level'] - r['level']))
            absorb(i, j)
            changed = True
            break
        if changed:
            continue
        for i in range(len(runs) - 1):
            if abs(runs[i]['level'] - runs[i + 1]['level']) <= gtol:
                absorb(i + 1, i)
                changed = True
                break

    # Bridge runs of one depth across deeper runs between them: a row of
    # stubs on the facade line becomes one chain, the recess between two
    # wings becomes one long segment. The deeper runs keep their own chains.
    def deeper_than(level, ref):
        return level > ref + gtol if take_min else level < ref - gtol

    changed = True
    while changed:
        changed = False
        n = len(runs)
        for i in range(n):
            for j in range(i + 2, n):
                if abs(runs[i]['level'] - runs[j]['level']) > gtol:
                    continue
                if take_min:
                    outer = min(runs[i]['level'], runs[j]['level'])
                else:
                    outer = max(runs[i]['level'], runs[j]['level'])
                ok = True
                for k in range(i + 1, j):
                    if not deeper_than(runs[k]['level'], outer):
                        ok = False
                        break
                if not ok:
                    continue
                runs[i]['pieces'] = sorted(runs[i]['pieces'] + runs[j]['pieces'],
                                           key=lambda q: q[0])
                runs[i]['b'] = max(runs[i]['b'], runs[j]['b'])
                relevel(runs[i])
                del runs[j]
                changed = True
                break
            if changed:
                break
    return runs


def jog_points(pieces, jog_mm=0.0, take_min=True):
    """Witness points along a piece list: ends plus every jog over jog_mm.

    Where two pieces meet, a jog gives one point at the shared boundary.
    Where two pieces do not meet (a recess bridged by the run, or a gap in
    the outline), both piece ends become points: they are the faces that
    bound the recess.

    The cross-axis hint of a jog is the OUTER of the two depths, i.e. the
    side the dimension line is on. A midpoint hint fails on a deep notch:
    the wall end at the facade is 5 m from the midpoint and gets rejected,
    and the chain skips the near edge of every deep recess.
    """
    if not pieces:
        return []
    tol = to_ft(MERGE_TOL_MM)
    major = to_ft(jog_mm)
    pts = [(pieces[0][0], pieces[0][2])]
    for i in range(len(pieces) - 1):
        cur = pieces[i]
        nxt = pieces[i + 1]
        jog = abs(nxt[2] - cur[2])
        gap = nxt[0] - cur[1]
        if gap > tol:
            pts.append((cur[1], cur[2]))
            pts.append((nxt[0], nxt[2]))
            continue
        if jog <= tol or jog < major:
            continue
        outer = min(cur[2], nxt[2]) if take_min else max(cur[2], nxt[2])
        pts.append((0.5 * (cur[1] + nxt[0]), outer))
    pts.append((pieces[-1][1], pieces[-1][2]))
    out = []
    for p in pts:
        if out and abs(p[0] - out[-1][0]) <= tol:
            continue
        out.append(p)
    return out


def find_ref(faces, scan_is_x, pos, hint, outline_only=True, max_witness=None):
    """Face perpendicular to the chain sitting at pos, nearest to hint.

    Only outline categories by default: a slab edge or a beam that happens
    to share the coordinate is not what an outer chain measures. A face
    further than max_witness from the hint is rejected outright rather
    than accepted as the least bad option - that is how a chain ends up
    tied to a wall on the far side of the plan.
    """
    tol = to_ft(REF_SEARCH_TOL_MM)
    limit = to_ft(MAX_WITNESS_MM if max_witness is None else max_witness)
    best = None
    best_d = None
    for fr in faces:
        if outline_only and not fr.in_outline:
            continue
        if not fr.perp_to(scan_is_x):
            continue
        if abs(fr.pos(scan_is_x) - pos) > tol:
            continue
        lo, hi = fr.cross(scan_is_x)
        if lo - tol <= hint <= hi + tol:
            d = 0.0
        else:
            d = min(abs(lo - hint), abs(hi - hint))
        if d > limit:
            continue
        if best_d is None or d < best_d:
            best_d = d
            best = fr
    return best


def witness_length(fr, scan_is_x, const):
    """Gap between the dimension line and the face it binds to."""
    lo, hi = fr.cross(scan_is_x)
    if lo <= const <= hi:
        return 0.0
    return min(abs(lo - const), abs(hi - const))


def outline(faces):
    """Overall size from the outline categories, cantilevers excluded."""
    core = [f for f in faces if f.in_outline] or list(faces)
    return (min(f.xmin for f in core), max(f.xmax for f in core),
            min(f.ymin for f in core), max(f.ymax for f in core))


# ---------------------------------------------------------------------------
# Openings in facade walls
# ---------------------------------------------------------------------------

def jamb_points(faces, walls, scan_is_x, level, a, b):
    """Faces inside facade walls of one run, i.e. opening jambs.

    A facade wall is a wall running along the sweep whose outer face sits
    at the run level. Faces perpendicular to the sweep that belong to it
    and sit away from both wall ends are jambs of openings cut into it.
    """
    axis = 'X' if scan_is_x else 'Y'
    margin = to_ft(JAMB_END_MARGIN_MM)
    tol = to_ft(REF_SEARCH_TOL_MM)
    facade = {}
    for w in walls:
        if w.axis != axis:
            continue
        if w.b <= a or w.a >= b:
            continue
        if min(abs(w.c - w.hw - level), abs(w.c + w.hw - level)) > tol:
            continue
        facade[w.key] = w
    pts = []
    for fr in faces:
        w = facade.get(fr.key)
        if w is None or not fr.perp_to(scan_is_x):
            continue
        pos = fr.pos(scan_is_x)
        if pos < a or pos > b:
            continue
        if pos - w.a < margin or w.b - pos < margin:
            continue
        pts.append((pos, fr))
    return pts


# ---------------------------------------------------------------------------
# Interior wall lines
# ---------------------------------------------------------------------------

def wall_lines(walls, axis):
    """Cluster walls of one axis into lines: {'c', 'hw', 'a', 'b', 'length'}."""
    tol = to_ft(INTERIOR_CLUSTER_MM)
    items = sorted([w for w in walls if w.axis == axis], key=lambda w: w.c)
    lines = []
    cur = None
    for w in items:
        if cur is not None and abs(w.c - cur['c_ref']) <= tol:
            cur['walls'].append(w)
        else:
            cur = {'c_ref': w.c, 'walls': [w]}
            lines.append(cur)
    out = []
    for ln in lines:
        ws = ln['walls']
        total = sum(w.b - w.a for w in ws)
        if total <= 0:
            continue
        c = sum((w.b - w.a) * w.c for w in ws) / total
        out.append({
            'c': c,
            'hw': max(w.hw for w in ws),
            'a': min(w.a for w in ws),
            'b': max(w.b for w in ws),
            'length': total,
            'walls': ws,
        })
    return out


def is_interior_line(line, profile_min, profile_max):
    """Is there outline geometry on both sides of this wall line?

    Sampled along every wall of the line: a sample counts as interior when
    the silhouette reaches further out than the wall on both sides. A
    facade wall fails on its outer side; a spine wall in a cross-shaped
    plan passes except where it alone forms the notch.
    """
    tol = to_ft(REF_SEARCH_TOL_MM)
    step = to_ft(250.0)
    lo_face = line['c'] - line['hw']
    hi_face = line['c'] + line['hw']
    total = 0
    inside = 0
    for w in line['walls']:
        pos = w.a + 0.5 * step
        while pos < w.b:
            total += 1
            vmin = profile_value_at(profile_min, pos)
            vmax = profile_value_at(profile_max, pos)
            if (vmin is not None and vmax is not None
                    and vmin < lo_face - tol and vmax > hi_face + tol):
                inside += 1
            pos += step
    return total > 0 and inside >= 0.5 * total


def interior_points(faces, scan_is_x, c, hw):
    """Every face perpendicular to the sweep that touches the wall band."""
    extra = to_ft(INTERIOR_BAND_EXTRA_MM)
    lo = c - hw - extra
    hi = c + hw + extra
    pts = []
    for fr in faces:
        if fr.bic not in INTERIOR_CATEGORIES:
            continue
        if not fr.perp_to(scan_is_x):
            continue
        clo, chi = fr.cross(scan_is_x)
        if chi < lo or clo > hi:
            continue
        pts.append((fr.pos(scan_is_x), fr))
    pts.sort(key=lambda t: t[0])
    return pts


# ---------------------------------------------------------------------------
# Slab edges, slab openings, wall coverage
# ---------------------------------------------------------------------------

def _on_profile(fr, scan_is_x, profiles):
    """Does this face sit at the outer silhouette? Slab edges usually run
    on the wall centreline, so the tolerance is a wall thickness, not a
    snapping distance."""
    tol = to_ft(SLAB_RIM_TOL_MM)
    p = fr.pos(scan_is_x)
    lo, hi = fr.cross(scan_is_x)
    mid = 0.5 * (lo + hi)
    names = ('LEFT', 'RIGHT') if scan_is_x else ('BOTTOM', 'TOP')
    for nm in names:
        v = profile_value_at(profiles.get(nm, []), mid)
        if v is not None and abs(v - p) <= tol:
            return True
    return False


def _outside_profile(fr, scan_is_x, profiles):
    """The side on which this face sticks out past the walls, or None."""
    tol = to_ft(SLAB_OUT_TOL_MM)
    p = fr.pos(scan_is_x)
    lo, hi = fr.cross(scan_is_x)
    mid = 0.5 * (lo + hi)
    if scan_is_x:
        vmin = profile_value_at(profiles.get('LEFT', []), mid)
        vmax = profile_value_at(profiles.get('RIGHT', []), mid)
        if vmin is not None and p < vmin - tol:
            return 'LEFT'
        if vmax is not None and p > vmax + tol:
            return 'RIGHT'
    else:
        vmin = profile_value_at(profiles.get('BOTTOM', []), mid)
        vmax = profile_value_at(profiles.get('TOP', []), mid)
        if vmin is not None and p < vmin - tol:
            return 'BOTTOM'
        if vmax is not None and p > vmax + tol:
            return 'TOP'
    return None


def _opposite_exists(fr, floor_faces, scan_is_x):
    """Another slab face on the same plane, facing the other way: a joint
    between two slab pieces, not the edge of a hole."""
    tol = to_ft(MERGE_TOL_MM)
    p = fr.pos(scan_is_x)
    a, b = fr.cross(scan_is_x)
    n1 = fr.nx if scan_is_x else fr.ny
    for g in floor_faces:
        if g is fr or not g.perp_to(scan_is_x):
            continue
        if abs(g.pos(scan_is_x) - p) > tol:
            continue
        n2 = g.nx if scan_is_x else g.ny
        if n1 * n2 >= 0:
            continue
        ga, gb = g.cross(scan_is_x)
        if gb <= a + tol or ga >= b - tol:
            continue
        return True
    return False


def slab_features(faces, profiles):
    """Cantilever slab edges and holes in the slab.

    Returns (balconies, holes).
    balcony: {'side', 'floor', 'edge': FaceRec, 'sides': [FaceRec]}
    hole:    {'xfaces', 'yfaces', 'x0', 'x1', 'y0', 'y1'}
    """
    # structural slab pieces only: toppings and finishes are thin
    fl = [f for f in faces if f.bic == BuiltInCategory.OST_Floors
          and f.height >= to_ft(SLAB_MIN_THICK_MM)]
    tol_out = to_ft(SLAB_OUT_TOL_MM)
    d_lo, d_hi = to_ft(BALCONY_DEPTH_MM[0]), to_ft(BALCONY_DEPTH_MM[1])

    balconies = {}
    for fr in fl:
        for scan_is_x in (True, False):
            if not fr.perp_to(scan_is_x):
                continue
            side = _outside_profile(fr, scan_is_x, profiles)
            if side is None:
                continue
            outward = fr.nx if scan_is_x else fr.ny
            sign = -1.0 if side in ('LEFT', 'BOTTOM') else 1.0
            if outward * sign <= 0:
                continue
            # how far past the walls: a balcony, not a slab covering a recess
            lo, hi = fr.cross(scan_is_x)
            v = profile_value_at(profiles.get(side, []), 0.5 * (lo + hi))
            if v is None:
                continue
            depth = (fr.pos(scan_is_x) - v) * sign
            if depth < d_lo or depth > d_hi:
                continue
            key = (fr.key, side)
            rec = balconies.setdefault(key, {'side': side, 'floor': fr.key,
                                             'edge': None, 'sides': []})
            if rec['edge'] is None or (fr.pos(scan_is_x) - rec['edge'].pos(scan_is_x)) * sign > 0:
                rec['edge'] = fr
    for rec in balconies.values():
        side = rec['side']
        side_scan = side in ('BOTTOM', 'TOP')   # side faces of a bottom balcony run along Y
        sign = -1.0 if side in ('LEFT', 'BOTTOM') else 1.0
        for fr in fl:
            if fr.key != rec['floor'] or not fr.perp_to(side_scan):
                continue
            lo, hi = fr.cross(side_scan)
            reach = lo if sign < 0 else hi
            v = profile_value_at(profiles.get(side, []), fr.pos(side_scan))
            if v is None:
                continue
            if (reach - v) * sign > tol_out:
                rec['sides'].append(fr)

    inner = []
    for fr in fl:
        for scan_is_x in (True, False):
            if not fr.perp_to(scan_is_x):
                continue
            if _outside_profile(fr, scan_is_x, profiles) is not None:
                continue
            if _on_profile(fr, scan_is_x, profiles):
                continue
            if _opposite_exists(fr, fl, scan_is_x):
                continue
            inner.append(fr)
    join = to_ft(100.0)
    groups = []
    for fr in inner:
        home = None
        for g in groups:
            if (fr.xmin <= g['x1'] + join and fr.xmax >= g['x0'] - join
                    and fr.ymin <= g['y1'] + join and fr.ymax >= g['y0'] - join):
                home = g
                break
        if home is None:
            home = {'x0': fr.xmin, 'x1': fr.xmax, 'y0': fr.ymin, 'y1': fr.ymax, 'faces': []}
            groups.append(home)
        home['faces'].append(fr)
        home['x0'] = min(home['x0'], fr.xmin)
        home['x1'] = max(home['x1'], fr.xmax)
        home['y0'] = min(home['y0'], fr.ymin)
        home['y1'] = max(home['y1'], fr.ymax)
    # A hole is a closed rectangle of slab edges facing INTO it: a left edge
    # with normal +X, a right edge with normal -X, and the same across Y,
    # each pair a sensible distance apart. Joints between slab pieces and
    # stray edges do not pass this.
    h_lo, h_hi = to_ft(HOLE_SIZE_MM[0]), to_ft(HOLE_SIZE_MM[1])
    holes = []
    for g in groups:
        xl = [f for f in g['faces'] if f.perp_to(True) and f.nx > 0]
        xr = [f for f in g['faces'] if f.perp_to(True) and f.nx < 0]
        yb = [f for f in g['faces'] if f.perp_to(False) and f.ny > 0]
        yt = [f for f in g['faces'] if f.perp_to(False) and f.ny < 0]
        if not (xl and xr and yb and yt):
            continue
        x0 = min(f.pos(True) for f in xl)
        x1 = max(f.pos(True) for f in xr)
        y0 = min(f.pos(False) for f in yb)
        y1 = max(f.pos(False) for f in yt)
        if not (h_lo <= x1 - x0 <= h_hi and h_lo <= y1 - y0 <= h_hi):
            continue
        holes.append({'xfaces': xl + xr, 'yfaces': yb + yt,
                      'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1})
    return list(balconies.values()), holes


def _plane_keys(entries):
    """Every plane a kept chain binds to, as (axis, 10 mm bucket).

    Coverage is by plane, not by face: three collinear wall pieces on one
    line are located by one chain, they do not each need their own.
    """
    keys = set()
    for e in entries:
        if e['kind'] == 'NOTE':
            continue
        for pos, _fr in e['points']:
            keys.add((e['scan_is_x'], int(round(mm(pos) / 10.0))))
    return keys


def _covered(sides, scan, keys):
    for fr in sides:
        k = (scan, int(round(mm(fr.pos(scan)) / 10.0)))
        if k in keys or (scan, k[1] - 1) in keys or (scan, k[1] + 1) in keys:
            return True
    return False


def wall_side_faces(w, faces):
    """The two side planes of a wall band, as faces (any element on them)."""
    side_scan = (w.axis == 'Y')
    tol = to_ft(REF_SEARCH_TOL_MM)
    out = []
    for fr in faces:
        if fr.bic != BuiltInCategory.OST_Walls or not fr.perp_to(side_scan):
            continue
        p = fr.pos(side_scan)
        if abs(p - (w.c - w.hw)) > tol and abs(p - (w.c + w.hw)) > tol:
            continue
        lo, hi = fr.cross(side_scan)
        if hi <= w.a or lo >= w.b:
            continue
        out.append(fr)
    return out


def _nearest_anchor(entries, faces, chain_scan, span_a, span_b, near_pos, far_pos, skip_key, reach):
    """A referenced face on the chain axis overlapping [span_a, span_b],
    else any wall face there; nearest to the wall being located.

    `skip_key` is the (source, id) pair of the element being located, or
    None when nothing has to be skipped.
    """
    cands = []
    for e in entries:
        if e['kind'] == 'NOTE' or e['scan_is_x'] != chain_scan:
            continue
        for _p, fr in e['points']:
            lo, hi = fr.cross(chain_scan)
            if hi <= span_a or lo >= span_b or fr.key == skip_key:
                continue
            d = min(abs(fr.pos(chain_scan) - near_pos), abs(fr.pos(chain_scan) - far_pos))
            # an anchor on one of the wall's own planes gives a chain that
            # shows nothing but the thickness
            if to_ft(MIN_SEGMENT_MM) < d <= reach:
                cands.append((d, fr))
    if not cands:
        for fr in faces:
            if fr.bic != BuiltInCategory.OST_Walls or not fr.perp_to(chain_scan):
                continue
            if fr.key == skip_key:
                continue
            lo, hi = fr.cross(chain_scan)
            if hi <= span_a or lo >= span_b:
                continue
            d = min(abs(fr.pos(chain_scan) - near_pos), abs(fr.pos(chain_scan) - far_pos))
            if to_ft(MIN_SEGMENT_MM) < d <= reach:
                cands.append((d, fr))
    if not cands:
        return None
    cands.sort(key=lambda t: t[0])
    return cands[0][1]


def locate_chains(walls, faces, entries, view):
    """A short chain for every wall no kept chain refers to.

    The chain crosses the wall: from the nearest plane already on the
    sheet to the wall's two faces. That is what makes every wall findable
    without any chain having to span the whole building.
    """
    keys = _plane_keys(entries)
    scale = float(view.Scale)
    gap = to_ft(ROW_GAP_PAPER_MM * scale)
    reach = to_ft(LOCATE_MAX_REACH_MM)
    rows = {True: [], False: []}
    for e in entries:
        if e['kind'] == 'NOTE':
            continue
        rows[e['scan_is_x']].append((e['const'], e['points'][0][0], e['points'][-1][0]))
    out = []
    notes = []
    for w in walls:
        if w.axis == 'SKEW':
            continue
        sides = wall_side_faces(w, faces)
        if not sides:
            continue
        chain_scan = (w.axis == 'Y')
        if _covered(sides, chain_scan, keys):
            continue
        near = min(sides, key=lambda f: f.pos(chain_scan))
        far = max(sides, key=lambda f: f.pos(chain_scan))
        anchor = _nearest_anchor(entries + out, faces, chain_scan, w.a, w.b,
                                 near.pos(chain_scan), far.pos(chain_scan), w.key, reach)
        if anchor is None:
            notes.append(u'wall at {:.0f} left unlocated: no anchor within reach'.format(mm(w.c)))
            continue
        lo, hi = anchor.cross(chain_scan)
        oa, ob = max(lo, w.a), min(hi, w.b)
        const0 = 0.5 * (oa + ob)
        pts = _dedupe([(anchor.pos(chain_scan), anchor), (near.pos(chain_scan), near), (far.pos(chain_scan), far)])
        if len(pts) < 3:
            notes.append(u'wall at {:.0f} left unlocated: anchor sits on its own plane'.format(mm(w.c)))
            continue
        a, b = pts[0][0], pts[-1][0]
        checks = [
            lambda c, _s=chain_scan, _a=a, _b=b: _wall_blocks(walls, _s, c, _a, _b),
            lambda c, _r=rows[chain_scan], _a=a, _b=b: _row_blocks(_r, c, _a, _b, gap),
        ]
        const = clear_const(const0, gap, checks)
        rows[chain_scan].append((const, a, b))
        for pos, _fr in pts:
            keys.add((chain_scan, int(round(mm(pos) / 10.0))))
        out.append({'kind': 'LOCATE', 'side': w.axis, 'scan_is_x': chain_scan,
                    'const': const, 'points': pts,
                    'label': u'locate wall at {:.0f}'.format(mm(w.c))})
    return out, notes


def facade_locate_chains(facade_lines, walls, faces, entries, view):
    """One compact chain per facade line for the walls that meet it and are
    not located yet: from the nearest plane already on the sheet, across
    those walls, to the next known plane. Placed inside the building."""
    keys = _plane_keys(entries)
    scale = float(view.Scale)
    first = to_ft(FIRST_OFFSET_PAPER_MM * scale)
    gap = to_ft(ROW_GAP_PAPER_MM * scale)
    tol = to_ft(REF_SEARCH_TOL_MM)
    extra = to_ft(INTERIOR_BAND_EXTRA_MM)
    min_seg = to_ft(MIN_SEGMENT_MM)
    rows = {True: [], False: []}
    for e in entries:
        if e['kind'] == 'NOTE':
            continue
        rows[e['scan_is_x']].append((e['const'], e['points'][0][0], e['points'][-1][0]))
    out = []
    for ln in facade_lines:
        chain_scan = ln['scan']
        band_lo = ln['c'] - ln['hw'] - extra
        band_hi = ln['c'] + ln['hw'] + extra
        pending = []
        for w in walls:
            if w.axis == ln['axis'] or w.axis == 'SKEW':
                continue
            touches = (band_lo - tol <= w.a <= band_hi + tol) or (band_lo - tol <= w.b <= band_hi + tol)
            if not touches or not (ln['a'] - tol <= w.c <= ln['b'] + tol):
                continue
            sides = wall_side_faces(w, faces)
            if not sides or _covered(sides, chain_scan, keys):
                continue
            pending.append(sides)
        if not pending:
            continue
        pts = []
        for sides in pending:
            for f in sides:
                pts.append((f.pos(chain_scan), f))
        pts = _dedupe(pts)
        lo_pos, hi_pos = pts[0][0], pts[-1][0]
        left = right = None
        for e in entries + out:
            if e['kind'] == 'NOTE' or e['scan_is_x'] != chain_scan:
                continue
            for _p, fr in e['points']:
                flo, fhi = fr.cross(chain_scan)
                if fhi <= band_lo or flo >= band_hi:
                    continue
                p = fr.pos(chain_scan)
                if p < lo_pos - min_seg and (left is None or p > left.pos(chain_scan)):
                    left = fr
                if p > hi_pos + min_seg and (right is None or p < right.pos(chain_scan)):
                    right = fr
        if left is None and right is None:
            continue
        if left is not None:
            pts.append((left.pos(chain_scan), left))
        if right is not None:
            pts.append((right.pos(chain_scan), right))
        pts = _dedupe(pts)
        if len(pts) < 2:
            continue
        a, b = pts[0][0], pts[-1][0]
        sign = 1.0 if ln['c'] < ln['centre'] else -1.0
        checks = [
            lambda c, _s=chain_scan, _a=a, _b=b: _wall_blocks(walls, _s, c, _a, _b),
            lambda c, _r=rows[chain_scan], _a=a, _b=b: _row_blocks(_r, c, _a, _b, gap),
        ]
        const = clear_const(ln['c'] + sign * (ln['hw'] + first), sign * gap, checks)
        rows[chain_scan].append((const, a, b))
        for pos, _fr in pts:
            keys.add((chain_scan, int(round(mm(pos) / 10.0))))
        out.append({'kind': 'LOCATE', 'side': ln['axis'], 'scan_is_x': chain_scan,
                    'const': const, 'points': pts,
                    'label': u'walls meeting the facade at {:.0f}'.format(mm(ln['c']))})
    return out


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def _dedupe(points):
    """Sort by position, drop points closer than MIN_SEGMENT."""
    min_seg = to_ft(MIN_SEGMENT_MM)
    pts = sorted(points, key=lambda t: t[0])
    out = []
    for p in pts:
        if out and abs(p[0] - out[-1][0]) < min_seg:
            continue
        out.append(p)
    return out


def _wall_blocks(walls, scan_is_x, const, a, b):
    """Would a line at const across [a, b] run inside a wall body?"""
    axis = 'X' if scan_is_x else 'Y'
    margin = to_ft(50.0)
    for w in walls:
        if w.axis != axis:
            continue
        if w.b <= a or w.a >= b:
            continue
        if abs(w.c - const) < w.hw + margin:
            return True
    return False


def _profile_blocks(pieces, take_min, const, a, b):
    """Would a line at const across [a, b] cut through the silhouette?

    Exact for the outline categories: the profile is the outermost
    geometry, so the line is inside a body wherever the profile reaches
    further out than the line.
    """
    tol = to_ft(MERGE_TOL_MM)
    for pa, pb, pv, _f in pieces:
        if pb <= a or pa >= b:
            continue
        if take_min:
            if pv < const + tol:
                return True
        else:
            if pv > const - tol:
                return True
    return False


def _row_blocks(placed, const, a, b, gap):
    """Two parallel chains with overlapping spans need a full row between
    them, or their texts collide."""
    for pc, pa, pb in placed:
        if pb <= a or pa >= b:
            continue
        if abs(pc - const) < 0.9 * gap:
            return True
    return False


def annotation_boxes(doc, view):
    """Plan extents of the annotation already on the view: text, tags and
    dimensions that are not ours. A chain must not be laid over them."""
    if not AVOID_ANNOTATION:
        return []
    cats = (BuiltInCategory.OST_TextNotes, BuiltInCategory.OST_Dimensions,
            BuiltInCategory.OST_GenericAnnotation, BuiltInCategory.OST_WallTags,
            BuiltInCategory.OST_StructuralFramingTags, BuiltInCategory.OST_FloorTags,
            BuiltInCategory.OST_MultiCategoryTags, BuiltInCategory.OST_SpotElevations)
    marker = auto_type(doc, False)
    marker_id = marker.Id if marker is not None else None
    boxes = []
    for bic in cats:
        try:
            col = (FilteredElementCollector(doc, view.Id)
                   .OfCategory(bic).WhereElementIsNotElementType())
        except Exception:
            continue
        for el in col:
            if marker_id is not None and el.GetTypeId() == marker_id:
                continue
            try:
                bb = el.get_BoundingBox(view)
            except Exception:
                bb = None
            if bb is None:
                continue
            boxes.append((bb.Min.X, bb.Max.X, bb.Min.Y, bb.Max.Y))
    return boxes


def _annotation_blocks(boxes, scan_is_x, const, a, b, clear):
    """Would a chain line at const across [a, b] land on existing text?"""
    for xmin, xmax, ymin, ymax in boxes:
        if scan_is_x:
            if xmax <= a or xmin >= b:
                continue
            if ymin - clear <= const <= ymax + clear:
                return True
        else:
            if ymax <= a or ymin >= b:
                continue
            if xmin - clear <= const <= xmax + clear:
                return True
    return False


def clear_const(const, step, checks):
    """Push a line outward (by step) until every check passes."""
    for _i in range(CLEAR_TRIES):
        blocked = False
        for chk in checks:
            if chk(const):
                blocked = True
                break
        if not blocked:
            return const
        const += step
    return const


def plan_chains(faces, walls, view, sides=SIDES, grids=None, anno=None):
    """Work out every chain without touching the model.

    Returns (entries, box). Each entry:
        kind      'LOCAL' | 'OVERALL' | 'INTERIOR'
        scan_is_x True for horizontal chains
        const     cross-axis position of the dimension line (ft)
        points    [(pos, FaceRec)] sorted along the sweep
        label     short text for reports
    """
    box = outline(faces)
    x0, x1, y0, y1 = box
    scale = float(view.Scale)
    first = to_ft(FIRST_OFFSET_PAPER_MM * scale)
    gap = to_ft(ROW_GAP_PAPER_MM * scale)

    entries = []
    skipped_overall = []
    facade_lines = []
    profiles = {}
    anno = anno or []
    anno_clear = to_ft(ANNOTATION_CLEAR_MM * scale)

    def anno_check(scan, a, b):
        return lambda c, _s=scan, _a=a, _b=b: _annotation_blocks(anno, _s, c, _a, _b, anno_clear)
    for side in sides:
        if side not in SIDE_SPEC:
            continue
        scan_is_x, take_min = SIDE_SPEC[side]
        profiles[side] = build_profile(faces, scan_is_x, take_min)

    # ---- outer chains, side by side
    for side in sides:
        if side not in SIDE_SPEC:
            continue
        scan_is_x, take_min = SIDE_SPEC[side]
        pieces = profiles[side]
        if not pieces:
            continue
        sign = -1.0 if take_min else 1.0
        placed = []

        def outer_checks(a, b, _p=pieces, _s=scan_is_x, _m=take_min, _pl=placed):
            return [
                lambda c: _profile_blocks(_p, _m, c, a, b),
                lambda c: _wall_blocks(walls, _s, c, a, b),
                lambda c: _row_blocks(_pl, c, a, b, gap),
                anno_check(_s, a, b),
            ]

        if LOCAL_ROWS:
            for run in group_runs(pieces, take_min):
                pts = []
                for pos, hint in jog_points(run['pieces'], 0.0, take_min):
                    fr = find_ref(faces, scan_is_x, pos, hint)
                    if fr is not None:
                        pts.append((pos, fr))
                if INCLUDE_OPENINGS:
                    pts.extend(jamb_points(faces, walls, scan_is_x,
                                           run['level'], run['a'], run['b']))
                pts = _dedupe(pts)
                if len(pts) < 2:
                    continue
                a, b = pts[0][0], pts[-1][0]
                const = clear_const(run['level'] + sign * first, sign * gap,
                                    outer_checks(a, b))
                placed.append((const, a, b))
                entries.append({
                    'kind': 'LOCAL', 'side': side, 'scan_is_x': scan_is_x,
                    'const': const, 'points': pts,
                    'label': u'{} local'.format(side),
                })

        if OVERALL_ROW:
            edge = (y0 if take_min else y1) if scan_is_x else (x0 if take_min else x1)
            # one row beyond the outermost local chain on this side
            outer = edge + sign * first
            for pc, _pa, _pb in placed:
                if (pc - outer) * sign > 0:
                    outer = pc
            const = outer + sign * gap
            # the extreme faces nearest to the line, not nearest to whatever
            # piece happens to end the profile: on a cross-shaped plan the
            # far corner of the silhouette may sit half a building away
            pts = []
            for pos in (pieces[0][0], pieces[-1][1]):
                fr = find_ref(faces, scan_is_x, pos, const,
                              max_witness=OVERALL_MAX_WITNESS_MM)
                if fr is not None:
                    pts.append((pos, fr))
            pts = _dedupe(pts)
            if len(pts) >= 2:
                a, b = pts[0][0], pts[-1][0]
                const = clear_const(const, sign * gap, outer_checks(a, b))
                placed.append((const, a, b))
                entries.append({
                    'kind': 'OVERALL', 'side': side, 'scan_is_x': scan_is_x,
                    'const': const, 'points': pts,
                    'label': u'{} overall'.format(side),
                })
            else:
                skipped_overall.append(side)

    # ---- interior chains along the main wall lines
    if INTERIOR_ROWS:
        width = x1 - x0
        height = y1 - y0
        cx = 0.5 * (x0 + x1)
        cy = 0.5 * (y0 + y1)
        for axis, scan_is_x, extent, centre, pmin, pmax in (
                ('X', True, width, cy, profiles.get('BOTTOM', []), profiles.get('TOP', [])),
                ('Y', False, height, cx, profiles.get('LEFT', []), profiles.get('RIGHT', []))):
            need = max(to_ft(INTERIOR_MIN_LENGTH_MM), INTERIOR_MIN_FRACTION * extent)
            # A facade wall line gets a through-chain too, placed on the
            # inside: it is the chain that locates the walls meeting that
            # facade, which the outer chain does not show when they end
            # flush. Duplicates against other chains are dropped later.
            # Interior lines get through-chains here. Facade lines are kept
            # aside: a chain along a facade is only worth its ink when walls
            # meeting that facade are left unlocated, which is decided at the
            # end (see facade_locate_chains).
            lines = []
            for ln in wall_lines(walls, axis):
                if ln['length'] < need:
                    continue
                ln['facade'] = not is_interior_line(ln, pmin, pmax)
                ln['axis'] = axis
                ln['scan'] = scan_is_x
                ln['centre'] = centre
                if ln['facade']:
                    facade_lines.append(ln)
                    continue
                lines.append(ln)
            lines.sort(key=lambda ln: -ln['length'])
            spacing = to_ft(INTERIOR_MIN_SPACING_MM)
            chosen = []
            for ln in lines:
                if any(abs(ln['c'] - o['c']) < spacing for o in chosen):
                    continue
                chosen.append(ln)
                if len(chosen) >= INTERIOR_MAX_PER_AXIS:
                    break
            placed = []
            for ln in chosen:
                pts = _dedupe(interior_points(faces, scan_is_x, ln['c'], ln['hw']))
                if len(pts) < 2:
                    continue
                a, b = pts[0][0], pts[-1][0]
                # prefer the side facing the plan centre, fall back to the other;
                # a facade line never falls back, its chain stays inside
                pref = 1.0 if ln['c'] < centre else -1.0
                base = ln['hw'] + first
                checks = [
                    lambda c, _s=scan_is_x, _a=a, _b=b: _wall_blocks(walls, _s, c, _a, _b),
                    lambda c, _pl=placed, _a=a, _b=b: _row_blocks(_pl, c, _a, _b, gap),
                    anno_check(scan_is_x, a, b),
                ]
                best = None
                sides_to_try = (pref,) if ln.get('facade') else (pref, -pref)
                for sign in sides_to_try:
                    const = clear_const(ln['c'] + sign * base, sign * gap, checks)
                    dist = abs(const - ln['c'])
                    if best is None or dist < best[1]:
                        best = (const, dist)
                const = best[0]
                placed.append((const, a, b))
                entries.append({
                    'kind': 'INTERIOR', 'side': axis, 'scan_is_x': scan_is_x,
                    'const': const, 'points': pts,
                    'label': u'{} line at {:.0f}'.format(
                        'H' if scan_is_x else 'V', mm(ln['c'])),
                })

    # ---- slab: cantilever edges and holes
    if SLAB_EDGES or SLAB_HOLES:
        rows = {True: [], False: []}
        for e in entries:
            rows[e['scan_is_x']].append((e['const'], e['points'][0][0], e['points'][-1][0]))
        balconies, holes = slab_features(faces, profiles)
        reach = to_ft(LOCATE_MAX_REACH_MM)

        def row_check(scan, a, b, _rows=rows):
            return [lambda c, _s=scan, _a=a, _b=b: _wall_blocks(walls, _s, c, _a, _b),
                    lambda c, _s=scan, _a=a, _b=b: _row_blocks(_rows[_s], c, _a, _b, gap),
                    anno_check(scan, a, b)]

        if SLAB_EDGES:
            for bal in balconies:
                side = bal['side']
                edge = bal['edge']
                if edge is None:
                    continue
                depth_scan = side in ('LEFT', 'RIGHT')
                sign = -1.0 if side in ('LEFT', 'BOTTOM') else 1.0
                lo, hi = edge.cross(depth_scan)
                mid = 0.5 * (lo + hi)
                facade_pos = profile_value_at(profiles.get(side, []), mid)
                fac = None
                if facade_pos is not None:
                    fac = find_ref(faces, depth_scan, facade_pos, mid)
                if fac is not None:
                    pts = _dedupe([(fac.pos(depth_scan), fac), (edge.pos(depth_scan), edge)])
                    if len(pts) >= 2:
                        a, b = pts[0][0], pts[-1][0]
                        const = clear_const(mid, gap, row_check(depth_scan, a, b))
                        rows[depth_scan].append((const, a, b))
                        entries.append({'kind': 'SLAB', 'side': side, 'scan_is_x': depth_scan,
                                        'const': const, 'points': pts,
                                        'label': u'{} balcony depth'.format(side)})
                if len(bal['sides']) >= 2:
                    width_scan = not depth_scan
                    pts = _dedupe([(f.pos(width_scan), f) for f in bal['sides']])
                    if len(pts) >= 2:
                        a, b = pts[0][0], pts[-1][0]
                        const = clear_const(edge.pos(depth_scan) + sign * first, sign * gap,
                                            row_check(width_scan, a, b))
                        rows[width_scan].append((const, a, b))
                        entries.append({'kind': 'SLAB', 'side': side, 'scan_is_x': width_scan,
                                        'const': const, 'points': pts,
                                        'label': u'{} balcony width'.format(side)})

        if SLAB_HOLES:
            for h in holes:
                for scan, hf, c0, c1 in ((True, h['xfaces'], h['y0'], h['y1']),
                                         (False, h['yfaces'], h['x0'], h['x1'])):
                    pts = _dedupe([(f.pos(scan), f) for f in hf])
                    if len(pts) < 2:
                        continue
                    anchor = _nearest_anchor(entries, faces, scan, c0, c1,
                                             pts[0][0], pts[-1][0], None, reach)
                    if anchor is not None:
                        pts = _dedupe(pts + [(anchor.pos(scan), anchor)])
                    a, b = pts[0][0], pts[-1][0]
                    const = clear_const(c1 + first, gap, row_check(scan, a, b))
                    rows[scan].append((const, a, b))
                    entries.append({'kind': 'OPENING', 'side': 'H' if scan else 'V', 'scan_is_x': scan,
                                    'const': const, 'points': pts,
                                    'label': u'slab opening {}'.format('width' if scan else 'depth')})

    # Final guard on every chain: a point whose face sits further from the
    # line than MAX_WITNESS is dropped; a chain left with one point goes.
    limit = to_ft(MAX_WITNESS_MM)
    kept = []
    for e in entries:
        if e.get('grid'):
            kept.append(e)
            continue
        lim = to_ft(OVERALL_MAX_WITNESS_MM) if e['kind'] == 'OVERALL' else limit
        pts = [(pos, fr) for pos, fr in e['points']
               if witness_length(fr, e['scan_is_x'], e['const']) <= lim]
        e['dropped'] = len(e['points']) - len(pts)
        e['points'] = pts
        if len(pts) >= 2:
            kept.append(e)
    entries = kept

    # Two chains showing the same number between the same faces say nothing
    # twice. Outer local chains win, then the overall, then interior lines:
    # a later chain whose segments are mostly already on the sheet is dropped.
    prio = {'LOCAL': 0, 'OVERALL': 1, 'SLAB': 2, 'OPENING': 3, 'INTERIOR': 4, 'GRID': 5}
    ordered = sorted(entries, key=lambda e: (prio.get(e['kind'], 9), -len(e['points'])))
    seen = set()
    dropped = []
    kept = []
    for e in ordered:
        if e.get('grid'):
            kept.append(e)
            continue
        pts = e['points']
        keys = []
        for i in range(len(pts) - 1):
            # a segment is the pair of planes it runs between: 24200 across
            # the bottom and 24200 across the top of a rectangle are one and
            # the same number, whichever wall ends the faces belong to
            a = int(round(mm(pts[i][0]) / 10.0))
            b = int(round(mm(pts[i + 1][0]) / 10.0))
            keys.append((e['scan_is_x'], a, b))
        dup = sum(1 for k in keys if k in seen)
        if keys and dup >= DUPLICATE_DROP_FRACTION * len(keys):
            dropped.append(e)
            continue
        for k in keys:
            seen.add(k)
        kept.append(e)
    entries = kept

    # ---- every wall must be findable: first one compact chain per facade
    # for the walls meeting it, then a short chain for whatever is left
    locate_notes = []
    if LOCATE_WALLS:
        for e in facade_locate_chains(facade_lines, walls, faces, entries, view):
            entries.append(e)
        extra, locate_notes = locate_chains(walls, faces, entries, view)
        lim = to_ft(MAX_WITNESS_MM)
        for e in extra:
            pts = [(pos, fr) for pos, fr in e['points']
                   if witness_length(fr, e['scan_is_x'], e['const']) <= lim]
            if len(pts) >= 2:
                e['points'] = pts
                entries.append(e)
    for n in locate_notes:
        entries.append({'kind': 'NOTE', 'side': '-', 'scan_is_x': True,
                        'const': 0.0, 'points': [], 'label': n})

    for e in dropped:
        entries.append({'kind': 'NOTE', 'side': e['side'], 'scan_is_x': e['scan_is_x'],
                        'const': 0.0, 'points': [],
                        'label': u'{} dropped: repeats segments already dimensioned'.format(e['label'])})
    for side in skipped_overall:
        entries.append({'kind': 'NOTE', 'side': side, 'scan_is_x': True,
                        'const': 0.0, 'points': [],
                        'label': u'{} overall skipped: extreme faces too far from the edge'.format(side)})

    # ---- grid spacings, one chain per direction, outermost of all
    if GRID_ROWS and grids:
        rows = {True: [], False: []}
        for e in entries:
            if e['kind'] == 'NOTE':
                continue
            rows[e['scan_is_x']].append((e['const'], e['points'][0][0], e['points'][-1][0]))
        for e in grid_chains(grids, view, box, rows, gap, first):
            entries.append(e)
    return entries, box


def dim_line(entry, z):
    a = entry['points'][0][0]
    b = entry['points'][-1][0]
    c = entry['const']
    if entry['scan_is_x']:
        return Line.CreateBound(XYZ(a, c, z), XYZ(b, c, z))
    return Line.CreateBound(XYZ(c, a, z), XYZ(c, b, z))


# ---------------------------------------------------------------------------
# Model access
# ---------------------------------------------------------------------------

def auto_type(doc, create):
    """The marker type: a duplicate of PEER-Linear, graphics unchanged."""
    name = BASE_TYPE + AUTO_SUFFIX
    existing = find_dim_type(doc, name)
    if existing is not None:
        return existing
    if not create:
        return None
    base = find_dim_type(doc, BASE_TYPE)
    if base is None:
        return None
    return base.Duplicate(name)


def delete_previous(doc, view, marker):
    ids = List[ElementId]()
    count = 0
    for d in (FilteredElementCollector(doc, view.Id)
              .OfClass(Dimension).WhereElementIsNotElementType()):
        if d.GetTypeId() == marker.Id:
            ids.Add(d.Id)
            count += 1
    if count:
        doc.Delete(ids)
    return count


def view_level_z(view):
    try:
        if view.GenLevel:
            return view.GenLevel.ProjectElevation
    except Exception:
        pass
    return 0.0


def template_name(doc, view):
    if view.ViewTemplateId == ElementId.InvalidElementId:
        return u''
    tmpl = doc.GetElement(view.ViewTemplateId)
    if tmpl is None:
        return u''
    try:
        return Element.Name.GetValue(tmpl)
    except Exception:
        return u''


def _describe(entry):
    segs = len(entry['points']) - 1
    span = mm(abs(entry['points'][-1][0] - entry['points'][0][0]))
    return u'{} ({} seg, {:.0f} mm)'.format(entry['label'], segs, span)


def set_options(grid_rows=None, sides=None):
    """Runtime switches the button offers the engineer."""
    global GRID_ROWS
    if grid_rows is not None:
        GRID_ROWS = bool(grid_rows)
    return GRID_ROWS


def annotate_view(doc, view, sides=SIDES, only=None):
    """Place every chain on one plan view. Call inside a transaction.

    `only` limits the work to a set of host element ids (the user's
    selection); the id of a link instance means everything from that link.
    """
    warns = []
    placed = []

    # one source list for the whole view: the records carry its indices
    srcs = plan_sources(doc, view)
    keep = selection_filter(srcs, only) if only else None

    faces, skipped = collect_faces(doc, view, srcs)
    if keep is not None:
        faces = [f for f in faces if keep(f)]
    if len(faces) < 4:
        warns.append(u'{}: no geometry to dimension'.format(view.Name))
        return placed, warns
    if skipped:
        warns.append(u'{}: {} elements gave no geometry'.format(view.Name, skipped))
    walls = collect_walls(doc, view, srcs)
    if keep is not None:
        walls = [w for w in walls if keep(w)]
    grids = collect_grids(doc, view, srcs) if GRID_ROWS else []
    anno = annotation_boxes(doc, view)

    entries, _box = plan_chains(faces, walls, view, sides, grids, anno)
    if not entries:
        warns.append(u'{}: no chain could be assembled'.format(view.Name))
        return placed, warns

    marker = auto_type(doc, True)
    if marker is None:
        warns.append(u'{}: dimension type "{}" not found'.format(view.Name, BASE_TYPE))
        return placed, warns

    removed = delete_previous(doc, view, marker)
    if removed:
        placed.append(u'removed {} previous'.format(removed))

    z = view_level_z(view)
    for entry in entries:
        if entry['kind'] == 'NOTE':
            warns.append(u'{}: {}'.format(view.Name, entry['label']))
            continue
        refs = ReferenceArray()
        for _pos, fr in entry['points']:
            refs.Append(fr['ref'] if isinstance(fr, dict) else fr.ref)
        if refs.Size < 2:
            continue
        try:
            dim = doc.Create.NewDimension(view, dim_line(entry, z), refs, marker)
        except Exception as ex:
            warns.append(u'{} {}: {}'.format(view.Name, entry['label'], ex))
            continue
        if dim is None:
            warns.append(u'{} {}: nothing created'.format(view.Name, entry['label']))
            continue
        placed.append(_describe(entry))
    return placed, warns


def annotate_views(doc, views, sides=SIDES, only=None):
    """One undo step for the whole run, whatever it touched."""
    done = 0
    warns = []
    report = []
    tg = TransactionGroup(doc, u'KZ Plan Dims')
    tg.Start()
    try:
        with Transaction(doc, u'KZ Plan Dims') as t:
            t.Start()
            for view in views:
                try:
                    placed, w = annotate_view(doc, view, sides, only)
                except Exception as ex:
                    warns.append(u'{}: {}'.format(view.Name, ex))
                    report.append((view.Name, []))
                    continue
                warns.extend(w)
                report.append((view.Name, placed))
                if placed:
                    done += 1
            t.Commit()
        tg.Assimilate()
    except Exception:
        tg.RollBack()
        raise
    return done, warns, report


def preview_views(doc, views, sides=SIDES, values=True, only=None):
    """Same maths, no model change. Returns (report, warnings)."""
    warns = []
    report = []
    for view in views:
        srcs = plan_sources(doc, view)
        keep = selection_filter(srcs, only) if only else None
        faces, _sk = collect_faces(doc, view, srcs)
        if keep is not None:
            faces = [f for f in faces if keep(f)]
        if len(faces) < 4:
            warns.append(u'{}: no geometry to dimension'.format(view.Name))
            report.append((view.Name, []))
            continue
        walls = collect_walls(doc, view, srcs)
        if keep is not None:
            walls = [w for w in walls if keep(w)]
        grids = collect_grids(doc, view, srcs) if GRID_ROWS else []
        anno = annotation_boxes(doc, view)
        entries, _box = plan_chains(faces, walls, view, sides, grids, anno)
        lines = []
        for e in entries:
            if e['kind'] == 'NOTE':
                warns.append(u'{}: {}'.format(view.Name, e['label']))
                continue
            txt = _describe(e)
            if e.get('dropped'):
                txt += u' [{} far points dropped]'.format(e['dropped'])
            if values:
                segs = []
                prev = None
                for pos, _fr in e['points']:
                    if prev is not None:
                        segs.append(u'{:.0f}'.format(mm(pos - prev)))
                    prev = pos
                shown = u'/'.join(segs[:14])
                if len(segs) > 14:
                    shown += u'/...'
                txt += u': ' + shown
            lines.append(txt)
        report.append((view.Name, lines))
    return report, warns
