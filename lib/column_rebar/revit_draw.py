# -*- coding: utf-8 -*-
"""Drawing the column sections on a drafting view (Revit, IronPython 2.7).
Called by the new Create Column button inside ONE TransactionGroup (one Undo);
every change here runs in the caller's open Transaction.

Per group (a row of the table):
  section     PEER_Column Section / Round2 / Round1 with code466 -> slots values
  tag         'Detail items_Tag Rebar' : 'Tag Rebar 2D10' (bars of the section)
  dimensions  b and h, text u'עמוד b/h' (cm), mark symbols PR_Column Number
  bar list    one row to the right of the section, each detail turned as it
              lies in the section, its tag under it - what the schedules
              count: perimeter stirrup (Shape 52 / 60), inner hoops (Shape 52,
              quantity), straight ties (Shape 62, quantity; across b turned 90)
The V-shaped tie has no 2D shape family yet: it is drawn in the section and
reported, it is not in the bar list.
"""

import math

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, DimensionType, ElementId, ElementTypeGroup,
                               ElementTransformUtils, FamilySymbol, FilteredElementCollector,
                               IndependentTag, Line, Reference, ReferenceArray, StorageType,
                               TagMode, TagOrientation, TextNote, TextNoteType, XYZ)

from column_rebar import code466, grouping, revit_collect, revit_params, slots

FT = 304.8
SECTION_FAMILY = {code466.RECT: u'PEER_Column Section', code466.ROUND2: u'PEER_Column Section Round2',
                  code466.ROUND1: u'PEER_Column Section Round1', code466.CIRCLE: u'PEER_Column Section Round'}
STIRRUP_FAMILY = {code466.RECT: u'PEER_Rebar_Shape 52', code466.ROUND1: u'PEER_Rebar_Shape 60',
                  code466.ROUND2: u'PEER_Rebar_Shape 65', code466.CIRCLE: u'PEER_Rebar_Shape 75'}
VTIE_FAMILY = u'PEER_Rebar_Shape 66'   # V-shaped tie (pointed or flat end) for the schedules
U_FAMILY = u'PEER_Rebar_Shape 64'       # half-round U-bar of a rounded column (contour split)
HOOP_FAMILY = u'PEER_Rebar_Shape 52'
TIE_FAMILIES = (u'PEER_Rebar_Shape 62', u'PEER_Rebar Shape 62')
NUMBER_FAMILY = u'PR_Column Number'
COL_TAG = (u'Detail items_Tag Rebar', u'Tag Rebar 2∅10')
# the details' tag (user 2026-11-21: 'take the other tag'): the plain Detail items_Tag Rebar shows
# the count from the project parameter Rebar_Quantity (number, Detail Items in the office template)
BAR_TAG = (u'Detail items_Tag Rebar', u'Tag Rebar 2∅10@20  L=')
# the same tag with the dense spacing after the main one: @20/10; used when the project has it
BAR_TAG_DENSE = u'Tag Rebar 2∅10@20/10 L='
DENSE_GUID = '5242800f-7b14-44da-a656-3d6e2a183a5c'     # Rebar_Stirrup Spacing Dense
TEXT_TYPE = u'Structural 3.5'
DIM_TYPE = u'PEER-Linear'

# layout, model mm at 1:25 (as the old button)
DIM_OFFSET = 152.4
TEXT_DROP = 365.8
MARK_DROP = 55.0
MARK_STEP = 210.0
MARK_START = 210.0
LIST_GAP = 300.0          # section -> bar list
OVERLAP = 0.4             # a detail may go this part of the previous one's width into it (user 2026-11-21)
DROP_IN = 150.0           # ... and this lower when it is as tall as the previous one
EDGE_CLEAR = 50.0         # ... but its side never within this of the other's side (lines run together)
TAG_GAP = 100.0           # between the tags on the tag line
TAG_LINE = 40.0           # tag line: on the section title line (TEXT_DROP), this lower
LIST_ITEM_GAP = 150.0     # between the details of the row (detail or its tag, whichever is wider)
TAG_ROOM = 500.0          # a bar tag is about this wide (the drawing measures the real one)
TAG_HEIGHT = 250.0
TIE_WIDTH = 150.0
DETAIL_MARGIN = 60.0      # the shape's own dimension texts (width: they stand left, in the gap)
GAP = 300.0
TOP_TIE_GAP = 400.0       # horizontal tie above the section: concrete top -> tie (column tag between)
TOP_TIE_STEP = 300.0      # between several horizontal ties above
TOP_TAG_GAP = 120.0       # tie -> its tag on the right

REQUIRED = [SECTION_FAMILY[code466.RECT], SECTION_FAMILY[code466.ROUND2], SECTION_FAMILY[code466.ROUND1],
            SECTION_FAMILY[code466.CIRCLE], STIRRUP_FAMILY[code466.CIRCLE],
            u'PEER_Rebar_Shape 52', u'PEER_Rebar_Shape 60', u'PEER_Rebar_Shape 62',
            STIRRUP_FAMILY[code466.ROUND2], U_FAMILY, VTIE_FAMILY, NUMBER_FAMILY]


def next_x(x, w, rng, w2, rng2, kind2=None):
    """(left, drop) of the next detail (w2 wide, heights rng2 = (bottom, top)
    in the section) after one at x, w wide, heights rng; mm. User 2026-11-21:
    'the detail a little inside and a little lower - then all is clear':
    - shorter and within the previous one's heights (an inner hoop beside the
      stirrup): a little inside, at its own height;
    - an inner hoop as tall as the previous one: a little inside and DROP_IN lower;
    at least half of it stays out. Everything else (ties, V-ties, U-bars)
    stands clear. Sides closer than EDGE_CLEAR would run together."""
    if kind2 != 'hoop':                  # only inner hoops go in (a V's flat end would lie on the stirrup)
        return x + w + LIST_ITEM_GAP, 0.0
    inside = (rng2[0] >= rng[0] - 1.0 and rng2[1] <= rng[1] + 1.0 and
              (rng2[1] - rng2[0]) <= 0.75 * (rng[1] - rng[0]))
    ov = min(OVERLAP * w, 0.5 * w2)
    if ov >= EDGE_CLEAR:
        return x + w - ov, (0.0 if inside else DROP_IN)
    return x + w + LIST_ITEM_GAP, 0.0


def ft(mm):
    return mm / FT


def symbol(doc, family, type_name=None, category=None):
    col = FilteredElementCollector(doc).OfClass(FamilySymbol)
    if category is not None:
        col = col.OfCategory(category)
    for s in col:
        if s.FamilyName != family:
            continue
        if type_name is None:
            return s
        p = s.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p is not None and p.AsString() == type_name:
            return s
    return None


def find_types(doc):
    """Everything the drawing needs, found once. Missing ones -> names in 'missing'."""
    t = {'missing': []}
    for shape, fam in SECTION_FAMILY.items():
        t[shape] = symbol(doc, fam)
    for shape, fam in STIRRUP_FAMILY.items():
        t['stirrup_' + shape] = symbol(doc, fam) if fam else None
    t['hoop'] = symbol(doc, HOOP_FAMILY)
    t['u_round'] = symbol(doc, U_FAMILY)
    t['vtie'] = symbol(doc, VTIE_FAMILY)
    t['tie'] = None
    for fam in TIE_FAMILIES:
        t['tie'] = t['tie'] or symbol(doc, fam)
    t['number'] = symbol(doc, NUMBER_FAMILY)
    t['col_tag'] = symbol(doc, COL_TAG[0], COL_TAG[1], BuiltInCategory.OST_DetailComponentTags)
    t['bar_tag'] = symbol(doc, BAR_TAG[0], BAR_TAG[1], BuiltInCategory.OST_DetailComponentTags)
    t['bar_tag_dense'] = symbol(doc, BAR_TAG[0], BAR_TAG_DENSE, BuiltInCategory.OST_DetailComponentTags)
    t['dim'] = None
    for d in FilteredElementCollector(doc).OfClass(DimensionType):
        p = d.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p is not None and p.AsString() == DIM_TYPE:
            t['dim'] = d
    t['text'] = None
    for x in FilteredElementCollector(doc).OfClass(TextNoteType):
        p = x.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p is not None and p.AsString() == TEXT_TYPE:
            t['text'] = x.Id
    if t['text'] is None:
        t['text'] = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType)
    for key, name in (('col_tag', u'%s : %s' % COL_TAG), ('bar_tag', u'%s : %s' % BAR_TAG),
                      ('hoop', HOOP_FAMILY), ('tie', TIE_FAMILIES[0]), ('number', NUMBER_FAMILY),
                      ('u_round', U_FAMILY)):
        if t[key] is None:
            t['missing'].append(name)
    return t


def activate(types):
    """Every family type the drawing places must be active - inside the transaction."""
    for v in types.values():
        if isinstance(v, FamilySymbol) and not v.IsActive:
            v.Activate()


def _hoop_dims(hp):
    """(Rebar_A along x, Rebar_B along y) of an inner hoop as it lies in the section."""
    x1, y1, x2, y2 = hp['box']
    small, big = sorted((hp['a'], hp['b']))
    return (big, small) if abs(x2 - x1) >= abs(y2 - y1) else (small, big)


def bar_list(result, g):
    """What goes to the right of the section, each detail as it lies in the
    section: [(kind, family key, params, qty, rotate 90, top)]. top - the top
    of the bar in the section, mm from the bottom of the concrete: the detail
    stands at that height (user 2026-11-21: 'where it is in the section').
    A tie across b (horizontal) is the Shape 62 turned by 90 degrees (above
    the section, top None)."""
    shape, b, h, c = g['shape'], g['b'], g['h'], g.get('cover') or 25.0
    dl = g.get('dia') or 16.0
    st = result.get('stirrup') or {}
    dw = st.get('dia') or 8.0
    R = b / 2.0
    items = []
    if st.get('contour') == code466.CONTOUR_SPLIT:
        # rounded, split: the rect hoop over the straight part + the U-bar (bottom one, arc down)
        r_, u = st['rect'], st['u']
        top = (h - R + dl / 2.0 + dw) if shape == code466.ROUND2 else h - c
        items.append(('stirrup', 'hoop', {'Rebar_A': r_['a'], 'Rebar_B': r_['b']}, 1, False, top))
        items.append(('u', 'u_round', {'Rebar_A': u['a'], 'Rebar_B': u['b']}, u['count'], False, R + u['leg']))
    else:
        items.append(('stirrup', 'stirrup_' + shape,
                      {'Rebar_A': b - 2 * c, 'Rebar_B': h - 2 * c}, 1, False, h - c))
    # one detail per hoop size: the same hoop standing and lying is one bar
    # (one number), drawn as the first of them lies in the section
    hoops, order = {}, []
    for hp in result.get('hoops') or []:
        if hp['kind'] == 'rect':
            ab = tuple(round(v) for v in _hoop_dims(hp))
            k = tuple(sorted(ab))
            if k not in hoops:
                hoops[k] = [ab, 0, max(hp['box'][1], hp['box'][3]) + dl / 2.0 + dw]
                order.append(k)
            hoops[k][1] += 1
    for k in sorted(order):
        (a, bb), n, top = hoops[k]
        items.append(('hoop', 'hoop', {'Rebar_A': float(a), 'Rebar_B': float(bb)}, n, False, top))
    ties = {}
    for t in result.get('ties') or []:
        if t.get('kind') == 'v' or t.get('alt'):
            continue
        vertical = t['direction'] == code466.VERTICAL
        span = (h if vertical else b) - 2 * c
        k = (not vertical, round(span))
        ties[k] = ties.get(k, 0) + 1
    for (horizontal, span), n in sorted(ties.items()):
        items.append(('tie', 'tie', {'Rebar_B': float(span)}, n, horizontal, None if horizontal else h - c))
    # V-shaped ties (Shape 66): W across the end bars, depth from the face, out to out;
    # the flat end round two bars E apart; one detail per size, as the first lies
    vts, vorder = {}, []
    for t in result.get('ties') or []:
        if t.get('kind') != 'v' or t.get('alt'):
            continue
        p1, apex, p2 = t['points']
        span = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        depth = abs((p2[0] - p1[0]) * (apex[1] - p1[1]) - (p2[1] - p1[1]) * (apex[0] - p1[0])) / span
        flat = t.get('flat')
        e = math.hypot(flat[1][0] - flat[0][0], flat[1][1] - flat[0][1]) if flat else 0.0
        k = (round(span + dl + 2 * dw), round(depth + dl + 2 * dw), 1 if flat else 0, round(e))
        if k not in vts:
            top = max(p1[1], p2[1], apex[1]) + dl / 2.0 + dw
            vts[k] = [0, t['direction'] == code466.HORIZONTAL, top]
            vorder.append(k)
        vts[k][0] += 1
    for k in vorder:
        (w_, d_, wide, e), (n, rot, top) = k, vts[k]
        items.append(('vtie', 'vtie', {'Rebar_A': float(w_), 'Rebar_B': float(d_), 'Wide': wide, 'E': float(e or 100)},
                      n, rot, top))
    return items


def item_size(kind, prm, rotate):
    """(width, height) of one detail on the view, mm, with its own dimension texts."""
    if kind == 'tie':
        w, h = TIE_WIDTH, prm['Rebar_B'] + DETAIL_MARGIN
        return (h, w) if rotate else (w, h)
    w, h = prm['Rebar_A'] + DETAIL_MARGIN, prm['Rebar_B'] + DETAIL_MARGIN
    return (h, w) if rotate else (w, h)


def on_top(kind, rotate):
    """A tie across b (horizontal in the section) is drawn above the section,
    centred over it, as it lies there; the rest go in the row to the right."""
    return kind == 'tie' and rotate


def extent(g, result):
    """{left, right, down, up} of one group's drawing from its insertion point
    (bottom-left corner of the concrete), mm. The details stand in one row to
    the right of the section, each at its height in the section, a little into
    each other; their tags on the title line."""
    b, h = g['b'], g['h']
    rows = grouping.mark_rows(grouping.marks_and_ranges(g['marks']))
    left = max(DIM_OFFSET + 100, max([MARK_START + sum(i['width'] for i in r) for r in rows] or [0]))
    right, up = b, h + 200
    i, top, tag_r = 0, h + TOP_TIE_GAP, b + LIST_GAP
    x = b + LIST_GAP
    prev = None
    for kind, key, prm, _, rot, ttop in bar_list(result, g):
        w, hh = item_size(kind, prm, rot)
        if on_top(kind, rot):
            top += hh
            up = max(up, top + TAG_HEIGHT)
            right = max(right, (b + w) / 2.0 + TOP_TAG_GAP + TAG_ROOM)
            top += TOP_TIE_STEP
            continue
        rng = (ttop - hh, ttop)
        if prev is not None:
            x, dy = next_x(prev[0], prev[1], prev[2], w, rng, kind)
            rng = (rng[0] - dy, rng[1] - dy)
        tag_r = max(tag_r, x) + TAG_ROOM + TAG_GAP
        right = max(right, x + w, tag_r)
        prev = (x, w, rng)
        i += 1
    down = TEXT_DROP + MARK_DROP + MARK_STEP * max(1, len(rows))
    return {'left': left, 'right': right, 'down': down, 'up': up}


def _set(el, values):
    for k, v in values.items():
        p = el.LookupParameter(k)
        if p is None or p.IsReadOnly:
            continue
        if p.StorageType == StorageType.Integer:
            p.Set(int(v))
        elif k.startswith('Rebar_Quantity') and p.StorageType == StorageType.Double and 'Text' not in k:
            p.Set(float(v))
        elif p.StorageType == StorageType.String:
            p.Set(u'%s' % v)
        else:
            p.Set(ft(v))


def _set_dense(el, dense):
    """Dense spacing onto the detail (shared Rebar_Stirrup Spacing Dense); False
    when the detail family has no such parameter (older library family)."""
    from System import Guid
    if not dense:
        return False
    p = el.get_Parameter(Guid(DENSE_GUID))
    if p is None or p.IsReadOnly:
        return False
    p.Set(ft(dense))
    return True


def _tag(doc, view, el, tag_type, head):
    tag = IndependentTag.Create(doc, view.Id, Reference(el), False, TagMode.TM_ADDBY_CATEGORY,
                                TagOrientation.Horizontal, head)
    tag.ChangeTypeId(tag_type.Id)
    try:
        tag.TagHeadPosition = head
    except Exception:
        pass
    return tag


def _dim(doc, view, inst, a, b_, p0, p1, dim_type):
    ra, rb = inst.GetReferenceByName(a), inst.GetReferenceByName(b_)
    if ra is None or rb is None:
        return None
    arr = ReferenceArray()
    arr.Append(ra)
    arr.Append(rb)
    if dim_type is not None:
        return doc.Create.NewDimension(view, Line.CreateBound(p0, p1), arr, dim_type)
    return doc.Create.NewDimension(view, Line.CreateBound(p0, p1), arr)


def _lines_box(doc, view, el):
    """(min x, min y, max x, max y) in feet of the VISIBLE lines of a detail on
    the view. Its bounding box takes the hidden variants of the family too and
    reaches far below the drawn shape."""
    from Autodesk.Revit.DB import Curve, GeometryInstance, Options
    o = Options()
    o.View = view
    pts = []

    def walk(geo):
        for g in geo:
            if isinstance(g, GeometryInstance):
                walk(g.GetInstanceGeometry())
            elif isinstance(g, Curve):
                for t in g.Tessellate():
                    pts.append(t)
    geo = el.get_Geometry(o)
    if geo is not None:
        walk(geo)
    if not pts:
        bb = el.get_BoundingBox(view)
        return None if bb is None else (bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y)
    return (min(q.X for q in pts), min(q.Y for q in pts), max(q.X for q in pts), max(q.Y for q in pts))


def _move_top_left(doc, view, el, x, y):
    """Visible lines of the detail: top-left corner to (x, y) mm."""
    doc.Regenerate()
    box = _lines_box(doc, view, el)
    if box is None:
        return None
    ElementTransformUtils.MoveElement(doc, el.Id, XYZ(ft(x) - box[0], ft(y) - box[3], 0))
    doc.Regenerate()
    return _lines_box(doc, view, el)


def draw_group(doc, view, g, result, values, origin, types, report):
    """One group at origin (x, y) mm = bottom-left corner of its concrete."""
    x0, y0 = origin
    b, h = g['b'], g['h']
    sym = types[g['shape']]
    ix, iy = slots.insertion(g['shape'], b, h)          # the round family: origin at the centre
    inst = doc.Create.NewFamilyInstance(XYZ(ft(x0 + ix), ft(y0 + iy), 0), sym, view)
    _set(inst, values)
    doc.Regenerate()
    # bars of the section: tag at the top right corner
    if types['col_tag'] is not None:
        _tag(doc, view, inst, types['col_tag'], XYZ(ft(x0 + b), ft(y0 + h + 60), 0))
    _dim(doc, view, inst, 'Left', 'Right', XYZ(ft(x0), ft(y0 - DIM_OFFSET), 0),
         XYZ(ft(x0 + b), ft(y0 - DIM_OFFSET), 0), types['dim'])
    _dim(doc, view, inst, 'Bottom', 'Top', XYZ(ft(x0 - DIM_OFFSET), ft(y0), 0),
         XYZ(ft(x0 - DIM_OFFSET), ft(y0 + h), 0), types['dim'])
    txt = (u'עמוד Ø%d' % round(b / 10.0) if g['shape'] == code466.CIRCLE else
           u'עמוד %d/%d' % (round(b / 10.0), round(h / 10.0)))
    TextNote.Create(doc, view.Id, XYZ(ft(x0), ft(y0 - TEXT_DROP), 0), txt, types['text'])
    # marks
    if types['number'] is not None:
        y = y0 - TEXT_DROP - MARK_DROP
        for row in grouping.mark_rows(grouping.marks_and_ranges(g['marks'])):
            x = x0 - MARK_START
            for it in row:
                m = doc.Create.NewFamilyInstance(XYZ(ft(x), ft(y), 0), types['number'], view)
                for k, v in (('Num', it['num']), ('Num2', it['num2'] or u'')):
                    p = m.LookupParameter(k)
                    if p is not None:
                        p.Set(v)
                p = m.LookupParameter('Num+')
                if p is not None:
                    p.Set(1 if it['num_plus'] else 0)
                x -= it['width']
            y -= MARK_STEP
    # bar list: one row to the right, each detail as it lies in the section and
    # at its height there, a little into the next one (OVERLAP); the tags on
    # one line with the section title, in the order of the details
    xs, ytop = x0 + b + LIST_GAP, y0 + h
    ytie = y0 + h + TOP_TIE_GAP
    tag_y = ft(y0 - TEXT_DROP - TAG_LINE)
    tag_min = None                                   # feet: the next tag starts right of it
    prev = None                                      # (x, w, heights) of the last detail of the row, mm
    for kind, key, prm, qty, rot, top in bar_list(result, g):
        if not on_top(kind, rot):
            w_, h_ = item_size(kind, prm, rot)
            rng = (top - h_, top)
            if prev is not None:
                nx, dy = next_x(prev[0] - x0, prev[1], prev[2], w_, rng, kind)
                xs = x0 + nx
                top, rng = top - dy, (rng[0] - dy, rng[1] - dy)
        s = types.get(key)
        if s is None:
            if kind != 'vtie':                          # reported once below
                report['notes'].append(u'%s: no family for the %s' % (u', '.join(g['marks']), kind))
            continue
        el = doc.Create.NewFamilyInstance(XYZ(ft(xs), ft(ytop), 0), s, view)
        vals = dict(prm)
        vals['Rebar_Diameter'] = result['stirrup']['dia']
        vals['Rebar_Spacing'] = result['spacing'] or code466.DEFAULT_SPACING
        _set(el, vals)
        dense_ok = _set_dense(el, result.get('dense'))
        tt = types['bar_tag_dense'] if dense_ok and types.get('bar_tag_dense') is not None else types['bar_tag']
        if kind != 'stirrup' and qty:
            for k in ('Rebar_Quantity Text',):
                p = el.LookupParameter(k)
                if p is not None and not p.IsReadOnly:
                    p.Set(u'%d' % qty)
            p = el.LookupParameter('Rebar_Quantity')
            if p is not None and not p.IsReadOnly:
                try:
                    p.Set(int(qty)) if p.StorageType == StorageType.Integer else p.Set(float(qty))
                except Exception:
                    pass
        if rot:
            doc.Regenerate()
            ElementTransformUtils.RotateElement(doc, el.Id, Line.CreateBound(XYZ(ft(xs), ft(ytop), 0),
                                                                             XYZ(ft(xs), ft(ytop), 1)),
                                                math.pi / 2.0)
        if on_top(kind, rot):
            doc.Regenerate()
            bx = _lines_box(doc, view, el)
            if bx is not None:
                bw, bh = (bx[2] - bx[0]) * FT, (bx[3] - bx[1]) * FT
                bx = _move_top_left(doc, view, el, x0 + (b - bw) / 2.0, ytie + bh)
                if bx is not None and tt is not None:
                    _tag(doc, view, el, tt, XYZ(bx[2] + ft(TOP_TAG_GAP + 100), (bx[1] + bx[3]) / 2.0, 0))
                ytie += bh + TOP_TIE_STEP
            continue
        box = _move_top_left(doc, view, el, xs, y0 + (top if top is not None else h))
        w = item_size(kind, prm, rot)[0]
        if box is not None:
            w = (box[2] - box[0]) * FT
            if tt is not None:
                tag = _tag(doc, view, el, tt, XYZ(box[0] + ft(100), tag_y, 0))
                doc.Regenerate()
                tb = tag.get_BoundingBox(view)
                if tb is not None:
                    if tag_min is not None and tb.Min.X < tag_min:
                        ElementTransformUtils.MoveElement(doc, tag.Id, XYZ(tag_min - tb.Min.X, 0, 0))
                        doc.Regenerate()
                        tb = tag.get_BoundingBox(view)
                    tag_min = tb.Max.X + ft(TAG_GAP)
            xs = box[0] * FT
        prev = (xs, w, rng)
    if types.get('vtie') is None and any(t.get('kind') == 'v' for t in result.get('ties') or []):
        report['notes'].append(u'%s: V-shaped tie drawn in the section, no Shape 66 in the project for the bar list'
                               % u', '.join(g['marks']))


def write_columns(doc, g, result):
    """What the table changed and the label, onto every 3D column of the group."""
    for cid in g['ids']:
        col = doc.GetElement(cid)
        if col is None:
            continue
        for name, v, length in (('Rebar_QuantityX', g['qb'], False), ('Rebar_QuantityY', g['qh'], False),
                                ('Rebar_Diameter', g['dia'], True)):
            p = revit_params.param(col, name)
            if p is not None and not p.IsReadOnly:
                p.Set(ft(v) if length else float(v))
        revit_params.write_label(col, result)


def pack(groups, results, max_width):
    from column_rebar import layout
    ex = [extent(g, r) for g, r in zip(groups, results)]
    return layout.pack(ex, max_width)
