# -*- coding: utf-8 -*-
"""SlabLinks.creation
Logic module for 'Slab Links By Region': computes an NxN grid of vertical
shear links (shpilki) inside FilledRegion zones on a slab and creates them
as Rebar sets (one set per contiguous run along Y).

No UI here: doc/host/regions/options come in as arguments, results go out
as a dict. All fatal conditions are reported through result['fatal'].
"""

import math

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import *
from System.Collections.Generic import List

from Snippets._context_manager import ef_Transaction

# ---------------------------------------------------------------- constants
MM_PER_FT       = 304.8
DEFAULT_COVER_MM = 50.0                  # cover to the FACE of reinforcement, mm
POINT_TOL_FT    = 0.5 / MM_PER_FT        # 0.5 mm


# ---------------------------------------------------------------- 2D geometry helpers
def loop_to_polygon(loop):
    """Tessellate a CurveLoop into a flat list of (x, y) tuples (feet)."""
    pts = []
    for crv in loop:
        tess = list(crv.Tessellate())
        for p in tess[:-1]:          # drop last point, it is the next curve's start
            pts.append((p.X, p.Y))
    return pts


def polygon_area(poly):
    """Shoelace area (absolute value)."""
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) * 0.5


def point_in_polygon(x, y, poly):
    """Ray-casting test."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def dist_point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dist_to_polygon(x, y, poly):
    n = len(poly)
    best = float('inf')
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        d = dist_point_segment(x, y, ax, ay, bx, by)
        if d < best:
            best = d
    return best


# ---------------------------------------------------------------- host helpers
def get_slab_faces_z(host):
    """Return (z_bottom, z_top) of horizontal slab faces, in feet."""
    bot_refs = HostObjectUtils.GetBottomFaces(host)
    top_refs = HostObjectUtils.GetTopFaces(host)
    z_bot, z_top = [], []
    for r in bot_refs:
        f = host.GetGeometryObjectFromReference(r)
        if isinstance(f, PlanarFace):
            z_bot.append(f.Origin.Z)
    for r in top_refs:
        f = host.GetGeometryObjectFromReference(r)
        if isinstance(f, PlanarFace):
            z_top.append(f.Origin.Z)
    if not z_bot or not z_top:
        return None, None
    return min(z_bot), max(z_top)


def get_slab_polygons(host):
    """All loops of the bottom faces, split into outer boundary and holes.

    Returns (outer_poly, hole_polys):
      outer_poly - loop with the largest area = outer slab boundary
                   (None when no loops found);
      hole_polys - every other loop = slab openings (shafts, penetrations).
                   NB: on shape-edited slabs with several planar bottom faces
                   the outer loops of the smaller faces also land here; harmless,
                   since such points are rejected by the outer-boundary test anyway.
    """
    loops = []   # (poly, area)
    for r in HostObjectUtils.GetBottomFaces(host):
        f = host.GetGeometryObjectFromReference(r)
        if not isinstance(f, PlanarFace):
            continue
        for loop in f.GetEdgesAsCurveLoops():
            poly = loop_to_polygon(loop)
            a = polygon_area(poly)
            if poly and a > 0.0:
                loops.append((poly, a))
    if not loops:
        return None, []
    loops.sort(key=lambda pa: pa[1], reverse=True)
    outer = loops[0][0]
    holes = [pa[0] for pa in loops[1:]]
    return outer, holes


def region_polygons(region):
    """All loops of a FilledRegion as polygons (outer + holes)."""
    return [loop_to_polygon(loop) for loop in region.GetBoundaries()]


def point_in_region(x, y, loops):
    """Even-odd rule: inside an odd number of loops."""
    hits = 0
    for poly in loops:
        if point_in_polygon(x, y, poly):
            hits += 1
    return hits % 2 == 1


# ---------------------------------------------------------------- rebar shape helpers
def _el_name(el):
    """Element name; some types (RebarBarType etc.) hide Element.Name from IronPython."""
    try:
        n = el.Name
        if isinstance(n, basestring):
            return n
    except Exception:
        pass
    try:
        return Element.Name.GetValue(el)
    except Exception:
        return Element.Name.__get__(el)


def collect_link_shapes(doc):
    """RebarShapes usable for a vertical link: a single straight segment
    (hooks are part of the shape definition, e.g. O_(22), X_(22))."""
    shapes = []
    for s in FilteredElementCollector(doc).OfClass(RebarShape):
        try:
            d = s.GetRebarShapeDefinition()
            if isinstance(d, RebarShapeDefinitionBySegments) and d.NumberOfSegments == 1:
                shapes.append(s)
        except Exception:
            pass
    return shapes


def get_shape_end_hooks(doc, shape):
    """Match project RebarHookTypes to the shape's default end hooks
    (by hook angle + rebar style). Returns ([hook0, hook1], [orient0, orient1]);
    hook is None for a plain end."""
    hooks = [None, None]
    orients = [RebarHookOrientation.Right, RebarHookOrientation.Left]
    all_hooks = list(FilteredElementCollector(doc).OfClass(RebarHookType))
    for i in (0, 1):
        try:
            ang_deg = float(shape.GetDefaultHookAngle(i))
            orients[i] = shape.GetDefaultHookOrientation(i)
        except Exception:
            continue
        if ang_deg <= 0:
            continue
        for h in all_hooks:
            if h.Style == shape.RebarStyle and \
                    abs(math.degrees(h.HookAngle) - ang_deg) < 0.5:
                hooks[i] = h
                break
    return hooks, orients


def find_rebar_key_row(doc, name_part):
    """Row of the 'Types of rebar' key schedule whose name contains name_part
    (case-insensitive), e.g. '7.Chair'. None when not found."""
    for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
        try:
            if not vs.Definition.IsKeySchedule:
                continue
            if 'types of rebar' not in _el_name(vs).lower():
                continue
        except Exception:
            continue
        for k in FilteredElementCollector(doc, vs.Id):
            nm = _el_name(k)
            if nm and name_part.lower() in nm.lower():
                return k
    return None


# ---------------------------------------------------------------- pile zones
def in_exclusion_zone(x, y, zones):
    """zones: [(x, y, half_w, half_h)] axis-aligned squares (piles); feet."""
    for (zx, zy, hw, hh) in zones:
        if abs(x - zx) <= hw + POINT_TOL_FT and abs(y - zy) <= hh + POINT_TOL_FT:
            return True
    return False


# ---------------------------------------------------------------- edge-anchored grid
def region_edge_distance(loops, slab_poly, side, near_tol, n_samples=7):
    """Distance from one bbox side of a region ('xmin','xmax','ymin','ymax') to the
    slab outline in the OUTWARD direction, feet (median over samples along the side).
    Positive = the slab edge lies outside the region, slightly negative = the region
    was drawn a little past the edge. None when no slab edge is found near that side
    (farther than near_tol, or the side faces the slab interior)."""
    pts = [p for poly in loops for p in poly]
    if not pts:
        return None
    xmin = min(p[0] for p in pts); xmax = max(p[0] for p in pts)
    ymin = min(p[1] for p in pts); ymax = max(p[1] for p in pts)
    m = len(slab_poly)
    ds = []
    for i in range(n_samples):
        t = (i + 0.5) / float(n_samples)
        best = None
        if side in ('xmin', 'xmax'):
            y = ymin + (ymax - ymin) * t
            x0 = xmin if side == 'xmin' else xmax
            for j in range(m):
                ax, ay = slab_poly[j]
                bx, by = slab_poly[(j + 1) % m]
                if (ay > y) == (by > y):
                    continue
                xi = ax + (y - ay) * (bx - ax) / (by - ay)
                d = (x0 - xi) if side == 'xmin' else (xi - x0)
                if d >= -near_tol and (best is None or d < best):
                    best = d
        else:
            x = xmin + (xmax - xmin) * t
            y0 = ymin if side == 'ymin' else ymax
            for j in range(m):
                ax, ay = slab_poly[j]
                bx, by = slab_poly[(j + 1) % m]
                if (ax > x) == (bx > x):
                    continue
                yi = ay + (x - ax) * (by - ay) / (bx - ax)
                d = (y0 - yi) if side == 'ymin' else (yi - y0)
                if d >= -near_tol and (best is None or d < best):
                    best = d
        if best is not None and best < near_tol:
            ds.append(best)
    if len(ds) < (n_samples + 1) // 2:
        return None
    ds.sort()
    return ds[len(ds) // 2]


def region_grid_lines(loops, slab_poly, step_x, step_y, org_x, org_y, edge_off,
                      near_x=None, near_y=None):
    """Grid coordinates (xs, ys) for ONE region, feet.

    Default: the global anchored grid (org + k*step). On a side where the region lies
    within one step of the slab edge the grid RESTARTS from that edge: first line at
    edge + edge_off, then every step (user rule 2026-09-06: the edge row starts 150 mm
    from the slab edge - the edge zone belongs to the U-bars / "peshki")."""
    pts = [p for poly in loops for p in poly]
    xmin = min(p[0] for p in pts); xmax = max(p[0] for p in pts)
    ymin = min(p[1] for p in pts); ymax = max(p[1] for p in pts)
    near_x = near_x if near_x is not None else step_x
    near_y = near_y if near_y is not None else step_y

    def axis_lines(lo, hi, step, org, d_lo, d_hi):
        lines = []
        if d_lo is not None:
            v = (lo - d_lo) + edge_off          # from the low-side slab edge inwards
            while v <= hi + POINT_TOL_FT:
                lines.append(v)
                v += step
        elif d_hi is not None:
            v = (hi + d_hi) - edge_off          # from the high-side slab edge inwards
            while v >= lo - POINT_TOL_FT:
                lines.append(v)
                v -= step
        else:
            v = org + math.ceil((lo - org) / step - POINT_TOL_FT) * step
            while v <= hi + POINT_TOL_FT:
                lines.append(v)
                v += step
        lines.sort()
        return lines

    xs = axis_lines(xmin, xmax, step_x, org_x,
                    region_edge_distance(loops, slab_poly, 'xmin', near_x),
                    region_edge_distance(loops, slab_poly, 'xmax', near_x))
    ys = axis_lines(ymin, ymax, step_y, org_y,
                    region_edge_distance(loops, slab_poly, 'ymin', near_y),
                    region_edge_distance(loops, slab_poly, 'ymax', near_y))
    return xs, ys


# ---------------------------------------------------------------- main entry
def create_slab_links(doc, host, regions, opts):
    """Create vertical slab links (shpilki) on an NxN grid inside FilledRegion zones.
    opts (dict):
      'spacing_mm'       float > 0   - grid spacing NxN, mm
      'main_dia_mm'      float >= 0  - main bar diameter, mm (leg spans between main bar axes)
      'cover_mm'         float >= 0  - cover to the FACE of reinforcement, mm (default 50;
                                       NOT read from the slab's RebarCoverType)
      'bar_type'         RebarBarType
      'rebar_shape'      RebarShape or None - create by shape (CreateFromCurvesAndShape);
                         end hooks/orientations are derived from the shape itself
      'hook_type'        RebarHookType or None - fallback path when no shape is given
      'openings_as_edge' bool        - treat slab openings like slab edge (skip one row near them)
      'comment'          unicode     - text for Comments param of each set
      'rebar_key_name'   unicode     - part of the 'Types of rebar' key-schedule row name
                                       to assign to each set (default u'Chair')
    returns (dict):
      'created'       list of (Rebar, count_in_set)
      'errors'        list of unicode - per-run creation failures
      'hook_names'    list of unicode - hook types matched from the shape (may be empty)
      'rebar_key'     unicode or None - name of the assigned Types-of-rebar key row
      'leg_height_mm' float
      'fatal'         None, or unicode message when nothing could be created
                      (bad host faces, slab too thin, no outer polygon, no grid points);
                      when fatal is set, created == [].
    """
    result = {'created': [], 'errors': [], 'hook_names': [],
              'rebar_key': None, 'leg_height_mm': 0.0, 'fatal': None}

    def fail(msg):
        result['fatal'] = msg
        return result

    # ------------------------------------------------------------ host validity
    if not RebarHostData.GetRebarHostData(host).IsValidHost():
        return fail(u'Выбранная плита не является допустимым хостом арматуры.')

    spacing_mm  = float(opts['spacing_mm'])
    if spacing_mm <= 0:
        return fail(u'Некорректный шаг шпилек: {} мм (должен быть больше нуля).'.format(spacing_mm))
    main_dia_mm = float(opts['main_dia_mm'])
    bar_type    = opts['bar_type']
    rebar_shape = opts.get('rebar_shape', None)
    hook_type   = opts.get('hook_type', None)
    openings_as_edge = bool(opts.get('openings_as_edge', False))
    comment_text = opts.get('comment', u'')

    spacing_ft  = spacing_mm / MM_PER_FT
    main_dia_ft = main_dia_mm / MM_PER_FT

    # ------------------------------------------------------------ geometry prep
    z_bot, z_top = get_slab_faces_z(host)
    if z_bot is None:
        return fail(u'Не удалось определить верх/низ плиты (нужна горизонтальная плита).')

    # fixed cover to the face of reinforcement (user input, not the slab's cover type)
    cover_ft = float(opts.get('cover_mm', DEFAULT_COVER_MM)) / MM_PER_FT

    # straight leg of the link runs between centrelines of top and bottom main bars
    z1 = z_bot + cover_ft + main_dia_ft * 0.5
    z2 = z_top - cover_ft - main_dia_ft * 0.5
    if z2 - z1 < spacing_ft * 0.25:
        return fail(u'Плита слишком тонкая для шпильки с заданными защитными слоями.')
    result['leg_height_mm'] = (z2 - z1) * MM_PER_FT

    slab_poly, hole_polys = get_slab_polygons(host)
    if not slab_poly:
        return fail(u'Не удалось получить контур плиты.')

    # ------------------------------------------------------------ build grid points
    # Global bbox over all regions, grid starts at bbox.min + spacing/2
    all_loops = []
    for rg in regions:
        all_loops.append(region_polygons(rg))

    xs_all = [p[0] for loops in all_loops for poly in loops for p in poly]
    ys_all = [p[1] for loops in all_loops for poly in loops for p in poly]
    if not xs_all:
        return fail(u'У выбранных Filled Region не удалось получить геометрию границ.')
    xmin, xmax = min(xs_all), max(xs_all)
    ymin, ymax = min(ys_all), max(ys_all)

    # sanity cap: a tiny spacing on a huge zone would freeze Revit in the grid loop
    n_cells = ((xmax - xmin) / spacing_ft + 1.0) * ((ymax - ymin) / spacing_ft + 1.0)
    if n_cells > 2000000:
        return fail(u'Слишком мелкий шаг для выбранных зон: сетка превышает 2 млн точек. '
                    u'Увеличьте шаг или уменьшите зоны.')

    # edge rule: default - drop everything closer than one spacing to the slab edge;
    # 'edge_row' - keep the edge row, the grid of an edge region restarts at
    # edge + edge_offset (150 mm: the edge zone is taken by the U-bars)
    edge_row = bool(opts.get('edge_row', False))
    edge_off = float(opts.get('edge_offset_mm', 150.0)) / MM_PER_FT
    org_x = float(opts.get('grid_org_x_mm', 0.0)) / MM_PER_FT
    org_y = float(opts.get('grid_org_y_mm', 0.0)) / MM_PER_FT
    if edge_row:
        skip_edge_ft = edge_off - POINT_TOL_FT
    else:
        skip_edge_ft = spacing_ft - POINT_TOL_FT   # points closer than one spacing to slab edge
    zones = list(opts.get('exclusion_zones', []) or [])   # pile squares (x, y, hw, hh)

    def point_allowed(x, y):
        """Full point test: in a region, on the slab, away from edge, not in/near openings."""
        in_any = False
        for loops in all_loops:
            if point_in_region(x, y, loops):
                in_any = True
                break
        if not in_any:
            return False
        if zones and in_exclusion_zone(x, y, zones):
            return False
        if not point_in_polygon(x, y, slab_poly):
            return False
        if dist_to_polygon(x, y, slab_poly) < skip_edge_ft:
            return False
        for hole in hole_polys:
            # bug-fix vs v1.0: never place a link over an opening
            if point_in_polygon(x, y, hole):
                return False
            # optionally treat opening edges like the slab edge
            if openings_as_edge and dist_to_polygon(x, y, hole) < skip_edge_ft:
                return False
        return True

    columns = {}   # x -> set of y (set: the same point may come from two regions)
    if edge_row:
        for loops in all_loops:
            xs, ys = region_grid_lines(loops, slab_poly, spacing_ft, spacing_ft,
                                       org_x, org_y, edge_off)
            for x in xs:
                for y in ys:
                    if point_in_region(x, y, loops) and point_allowed(x, y):
                        columns.setdefault(round(x, 6), set()).add(round(y, 6))
    else:
        x = xmin + spacing_ft * 0.5
        while x <= xmax + POINT_TOL_FT:
            y = ymin + spacing_ft * 0.5
            while y <= ymax + POINT_TOL_FT:
                if point_allowed(x, y):
                    columns.setdefault(round(x, 6), set()).add(round(y, 6))
                y += spacing_ft
            x += spacing_ft

    if not columns:
        return fail(u'В выбранных зонах не найдено ни одной точки для шпилек '
                    u'(проверьте шаг и что зоны лежат внутри плиты).')

    # group each column into contiguous runs along Y (one Rebar set per run)
    runs = []   # (x, y_start, count)
    for xk in sorted(columns.keys()):
        ys = sorted(columns[xk])
        start = ys[0]
        count = 1
        for i in range(1, len(ys)):
            if abs(ys[i] - ys[i - 1] - spacing_ft) < POINT_TOL_FT:
                count += 1
            else:
                runs.append((xk, start, count))
                start = ys[i]
                count = 1
        runs.append((xk, start, count))

    # ------------------------------------------------------------ create rebar
    normal = XYZ.BasisY          # layout direction; hooks bend along X

    shape_hooks, shape_orients = [None, None], None
    if rebar_shape is not None:
        shape_hooks, shape_orients = get_shape_end_hooks(doc, rebar_shape)
        result['hook_names'] = [_el_name(h) for h in shape_hooks if h is not None]

    # 'Types of rebar' key-schedule row to stamp on every set (e.g. '7.Chair')
    key_row = find_rebar_key_row(doc, opts.get('rebar_key_name', u'Chair'))
    if key_row is not None:
        result['rebar_key'] = _el_name(key_row)

    with ef_Transaction(doc, 'PEER: Slab links by region'):
        for (xk, y0, count) in runs:
            try:
                p1 = XYZ(xk, y0, z1)
                p2 = XYZ(xk, y0, z2)
                curves = List[Curve]([Line.CreateBound(p1, p2)])
                if rebar_shape is not None:
                    rebar = Rebar.CreateFromCurvesAndShape(
                        doc, rebar_shape, bar_type, shape_hooks[0], shape_hooks[1],
                        host, normal, curves, shape_orients[0], shape_orients[1])
                else:
                    rebar = Rebar.CreateFromCurves(
                        doc, RebarStyle.Standard, bar_type, hook_type, hook_type, host, normal,
                        curves, RebarHookOrientation.Right, RebarHookOrientation.Left, True, True)
                if count > 1:
                    acc = rebar.GetShapeDrivenAccessor()
                    acc.SetLayoutAsFixedNumber(count, spacing_ft * (count - 1), True, True, True)
                cp = rebar.LookupParameter('Comments')
                if cp and not cp.IsReadOnly:
                    cp.Set(comment_text)
                if key_row is not None:
                    kp = rebar.LookupParameter('Types of Rebar')
                    if kp and not kp.IsReadOnly:
                        kp.Set(key_row.Id)
                result['created'].append((rebar, count))
            except Exception as e:
                result['errors'].append(u'x={:.0f} y={:.0f}: {}'.format(
                    xk * MM_PER_FT, y0 * MM_PER_FT, unicode(e)))

    # ef_Transaction swallows exceptions and rolls back silently: if that happened,
    # the created Rebar objects are no longer valid - report it instead of fake success
    if result['created'] and not result['created'][0][0].IsValidObject:
        result['created'] = []
        return fail(u'Транзакция откатилась из-за ошибки — шпильки не созданы '
                    u'(подробности в окне вывода pyRevit).')

    return result


def collect_chair_shapes(doc):
    """RebarShapes usable for a chair: three or more segments (foot-web-seat-web-foot)."""
    shapes = []
    for s in FilteredElementCollector(doc).OfClass(RebarShape):
        try:
            d = s.GetRebarShapeDefinition()
            if isinstance(d, RebarShapeDefinitionBySegments) and 3 <= d.NumberOfSegments <= 5:
                shapes.append(s)
        except Exception:
            pass
    return shapes


def create_slab_chairs(doc, host, regions, opts):
    """Create chairs ("lyagushki") inside FilledRegion zones.

    The chair is flat, in a vertical plane along Y: foot - web - seat - web - foot,
    both feet pointing the same way, so the feet of neighbouring rows meet end to end.
    Placed on a rectangular grid: 'step_x_mm' along the row, 'step_y_mm' between rows;
    the two webs of one chair are 'seat_mm' apart, which makes the webs a
    (step_x) x (seat) grid of support points.

    Height, user rule 2026-08-26:
        PR_B = slab thickness - cover_top - cover_bottom - main bar dia + chair dia
    i.e. the seat passes ABOVE the top mesh and the feet rest ON the bottom mesh.

    opts adds to the link options:
      'step_x_mm', 'step_y_mm', 'seat_mm', 'foot_mm' - floats, mm
      'chair_shape' - RebarShape or None (shape is matched automatically when None)
    """
    result = {'created': [], 'errors': [], 'hook_names': [], 'rebar_key': None,
              'leg_height_mm': 0.0, 'fatal': None}

    def fail(msg):
        result['fatal'] = msg
        return result

    if not RebarHostData.GetRebarHostData(host).IsValidHost():
        return fail(u'Выбранная плита не является допустимым хостом арматуры.')

    step_x = float(opts.get('step_x_mm', 200.0)) / MM_PER_FT
    step_y = float(opts.get('step_y_mm', 400.0)) / MM_PER_FT
    seat   = float(opts.get('seat_mm', 200.0)) / MM_PER_FT
    foot   = float(opts.get('foot_mm', 200.0)) / MM_PER_FT
    # 'Y' - the seat runs along Y, sets multiply along X (default)
    # 'X' - the seat runs along X, sets multiply along Y
    axis = (opts.get('chair_axis', 'Y') or 'Y').upper()
    if step_x <= 0 or step_y <= 0 or seat <= 0:
        return fail(u'Шаг и полка лягушки должны быть больше нуля.')

    bar_type    = opts['bar_type']
    chair_dia   = bar_type.BarNominalDiameter
    # user rule 2026-08-26: every size the user types is OUT-TO-OUT (already includes the bar
    # diameter), so the centreline geometry is built smaller by the diameter
    seat = seat - chair_dia
    foot = max(0.0, foot - chair_dia * 0.5)
    if seat <= 0:
        return fail(u'Полка лягушки меньше диаметра стержня.')
    main_dia    = float(opts.get('main_dia_mm', 25.0)) / MM_PER_FT
    cover       = float(opts.get('cover_mm', DEFAULT_COVER_MM)) / MM_PER_FT
    comment_txt = opts.get('comment', u'')

    z_bot, z_top = get_slab_faces_z(host)
    if z_bot is None:
        return fail(u'Не удалось определить верх/низ плиты (нужна горизонтальная плита).')

    # feet rest on the bottom mesh, the seat passes above the top mesh
    z_foot = z_bot + cover + main_dia + chair_dia * 0.5
    z_seat = z_top - cover + chair_dia * 0.5
    height_mm = (z_seat - z_foot) * MM_PER_FT
    if height_mm < 50.0:
        return fail(u'Плита слишком тонкая для лягушки: расчётная высота {:.0f} мм.'.format(height_mm))
    result['leg_height_mm'] = height_mm

    slab_poly, hole_polys = get_slab_polygons(host)
    if not slab_poly:
        return fail(u'Не удалось получить контур плиты.')

    all_loops = [region_polygons(rg) for rg in regions]
    xs_all = [p[0] for loops in all_loops for poly in loops for p in poly]
    ys_all = [p[1] for loops in all_loops for poly in loops for p in poly]
    if not xs_all:
        return fail(u'У выбранных Filled Region не удалось получить геометрию границ.')
    xmin, xmax = min(xs_all), max(xs_all)
    ymin, ymax = min(ys_all), max(ys_all)

    n_cells = ((xmax - xmin) / step_x + 1.0) * ((ymax - ymin) / step_y + 1.0)
    if n_cells > 2000000:
        return fail(u'Слишком мелкий шаг для выбранных зон: сетка превышает 2 млн точек.')

    openings_as_edge = bool(opts.get('openings_as_edge', False))
    # a chair only needs its feet to stay in concrete, so the edge margin is the cover, not a
    # whole grid row (that rule belongs to the vertical links)
    skip_edge = cover + chair_dia

    def on_slab(x, y):
        """Point is inside the slab outline (and not in an opening) - used for the feet ends."""
        if not point_in_polygon(x, y, slab_poly):
            return False
        if dist_to_polygon(x, y, slab_poly) < cover:
            return False
        for hole in hole_polys:
            if point_in_polygon(x, y, hole):
                return False
        return True

    zones = list(opts.get('exclusion_zones', []) or [])   # pile squares (x, y, hw, hh)

    def web_ok(x, y):
        """A support point (web foot) must sit in a region, on the slab, away from edges."""
        in_any = False
        for loops in all_loops:
            if point_in_region(x, y, loops):
                in_any = True
                break
        if not in_any:
            return False
        if zones and in_exclusion_zone(x, y, zones):
            return False
        if not point_in_polygon(x, y, slab_poly):
            return False
        if dist_to_polygon(x, y, slab_poly) < skip_edge:
            return False
        for hole in hole_polys:
            if point_in_polygon(x, y, hole):
                return False
            if openings_as_edge and dist_to_polygon(x, y, hole) < skip_edge:
                return False
        return True

    # rows: v = coordinate along the seat, u = along the set; both webs must be usable
    def xy(u, v):
        return (u, v) if axis == 'Y' else (v, u)

    # step_x is always "along the row", step_y "between rows" - independent of the axis
    step_u, step_v = step_x, step_y
    if axis == 'Y':
        umin, umax, vmin, vmax = xmin, xmax, ymin, ymax
    else:
        umin, umax, vmin, vmax = ymin, ymax, xmin, xmax

    # grid anchor (mm): chairs land on round coordinates of the user's system;
    # e.g. 91897;367850 aligns the grid with the sheet coordinates of the HRSG model
    org_x = float(opts.get('grid_org_x_mm', 0.0)) / MM_PER_FT
    org_y = float(opts.get('grid_org_y_mm', 0.0)) / MM_PER_FT
    org_u, org_v = (org_x, org_y) if axis == 'Y' else (org_y, org_x)

    def snap(v0, step, org):
        return org + math.ceil((v0 - org) / step - POINT_TOL_FT) * step

    rows = {}
    v = snap(vmin, step_v, org_v)
    while v <= vmax + POINT_TOL_FT:
        u = snap(umin, step_u, org_u)
        while u <= umax + POINT_TOL_FT:
            p1 = xy(u, v); p2 = xy(u, v - seat)
            # the feet stick out perpendicular to the seat by 'foot' - keep them in concrete
            feet = [xy(u + foot, v), xy(u + foot, v - seat),
                    xy(u - foot, v), xy(u - foot, v - seat)]
            ok_feet = True
            for f in feet:
                if not on_slab(f[0], f[1]):
                    ok_feet = False
                    break
            if ok_feet and web_ok(p1[0], p1[1]) and web_ok(p2[0], p2[1]):
                rows.setdefault(round(v, 6), []).append(u)
            u += step_u
        v += step_v

    if not rows:
        return fail(u'В выбранных зонах не найдено ни одной точки для лягушек '
                    u'(проверьте шаг и что зоны лежат внутри плиты).')

    chair_shape = opts.get('chair_shape', None)
    key_row = find_rebar_key_row(doc, opts.get('rebar_key_name', u'Chair'))
    if key_row is not None:
        result['rebar_key'] = _el_name(key_row)

    # feet of the chair are 90-degree HOOKS turned out of the web plane
    hook0, hook1 = None, None
    orient0, orient1 = RebarHookOrientation.Right, RebarHookOrientation.Right
    if chair_shape is not None:
        hooks, orients = get_shape_end_hooks(doc, chair_shape)
        hook0, hook1 = hooks[0], hooks[1]
        if orients:
            orient0, orient1 = orients[0], orients[1]
    if hook0 is None or hook1 is None:
        for h in FilteredElementCollector(doc).OfClass(RebarHookType):
            try:
                if abs(math.degrees(h.HookAngle) - 90.0) < 0.5:
                    hook0 = hook0 or h
                    hook1 = hook1 or h
            except Exception:
                pass
    result['hook_names'] = [_el_name(h) for h in (hook0, hook1) if h is not None]
    rot_start = float(opts.get('hook_rot_start', 90.0)) * math.pi / 180.0
    rot_end   = float(opts.get('hook_rot_end', 270.0)) * math.pi / 180.0

    # seat along Y -> web plane YZ, feet along X ; seat along X -> web plane XZ, feet along Y
    normal = XYZ.BasisX if axis == 'Y' else XYZ.BasisY

    with ef_Transaction(doc, 'PEER: Slab chairs by region'):
        for yk in sorted(rows.keys()):
            xs = sorted(rows[yk])
            runs = []
            start = xs[0]
            count = 1
            for i in range(1, len(xs)):
                if abs(xs[i] - xs[i - 1] - step_u) < POINT_TOL_FT:
                    count += 1
                else:
                    runs.append((start, count))
                    start = xs[i]
                    count = 1
            runs.append((start, count))

            for (x0, count) in runs:
                try:
                    def P3(v_off, z):
                        a, b = xy(x0, yk + v_off)
                        return XYZ(a, b, z)
                    # web - seat - web in one plane; the feet are 90-degree hooks rotated
                    # out of that plane (user rule 2026-08-26: seat along X -> feet along Y)
                    pts = [P3(0.0, z_foot), P3(0.0, z_seat),
                           P3(-seat, z_seat), P3(-seat, z_foot)]
                    curves = List[Curve]()
                    for i in range(len(pts) - 1):
                        curves.Add(Line.CreateBound(pts[i], pts[i + 1]))
                    rebar = None
                    if rebar is None:
                        rebar = Rebar.CreateFromCurves(
                            doc, RebarStyle.Standard, bar_type, hook0, hook1, host, normal,
                            curves, orient0, orient1, True, True)
                    if rebar is None:
                        raise Exception(u'Revit не создал стержень (проверьте, что зона '
                                        u'лежит внутри плиты и высота лягушки помещается)')
                    if count > 1:
                        acc = rebar.GetShapeDrivenAccessor()
                        acc.SetLayoutAsFixedNumber(count, step_u * (count - 1),
                                                   True, True, True)
                    # turn both feet out of the web plane, both to the same side
                    for pname, val in (('Hook Rotation At Start', rot_start),
                                       ('Hook Rotation At End', rot_end)):
                        hp = rebar.LookupParameter(pname)
                        if hp is not None and not hp.IsReadOnly:
                            try:
                                hp.Set(val)
                            except Exception:
                                pass
                    # stamp the requested shape (Revit matches an auto shape on creation)
                    if chair_shape is not None:
                        sp = rebar.get_Parameter(BuiltInParameter.REBAR_SHAPE)
                        if sp is not None and not sp.IsReadOnly:
                            try:
                                sp.Set(chair_shape.Id)
                            except Exception:
                                pass
                    cp = rebar.LookupParameter('Comments')
                    if cp and not cp.IsReadOnly:
                        cp.Set(comment_txt or u'CHAIR H={:.0f}'.format(height_mm))
                    if key_row is not None:
                        kp = rebar.LookupParameter('Types of Rebar')
                        if kp and not kp.IsReadOnly:
                            kp.Set(key_row.Id)
                    result['created'].append((rebar, count))
                except Exception as e:
                    result['errors'].append(u'x={:.0f} y={:.0f}: {}'.format(
                        x0 * MM_PER_FT, yk * MM_PER_FT, unicode(e)))

        # Revit sometimes spreads the set to the wrong side of the curves; measure the
        # actual direction of every set and repair it (flip the side, translate as a
        # last resort) so no chair leaves its region
        doc.Regenerate()
        want = XYZ.BasisX if axis == 'Y' else XYZ.BasisY
        for (rebar, count) in result['created']:
            if count < 2:
                continue
            try:
                acc = rebar.GetShapeDrivenAccessor()
                d = (acc.GetBarPositionTransform(1).Origin -
                     acc.GetBarPositionTransform(0).Origin)
                if d.DotProduct(want) >= 0.0:
                    continue
                acc.SetLayoutAsFixedNumber(count, step_u * (count - 1), False, True, True)
                doc.Regenerate()
                d = (acc.GetBarPositionTransform(1).Origin -
                     acc.GetBarPositionTransform(0).Origin)
                if d.DotProduct(want) < 0.0:
                    ElementTransformUtils.MoveElement(
                        doc, rebar.Id, want.Multiply(step_u * (count - 1)))
            except Exception:
                pass

    if result['created'] and not result['created'][0][0].IsValidObject:
        result['created'] = []
        return fail(u'Транзакция откатилась из-за ошибки — лягушки не созданы.')
    return result
