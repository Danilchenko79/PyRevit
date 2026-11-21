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
                  code466.ROUND1: u'PEER_Column Section Round1'}
STIRRUP_FAMILY = {code466.RECT: u'PEER_Rebar_Shape 52', code466.ROUND1: u'PEER_Rebar_Shape 60',
                  code466.ROUND2: None}
HOOP_FAMILY = u'PEER_Rebar_Shape 52'
TIE_FAMILIES = (u'PEER_Rebar_Shape 62', u'PEER_Rebar Shape 62')
NUMBER_FAMILY = u'PR_Column Number'
COL_TAG = (u'Detail items_Tag Rebar', u'Tag Rebar 2∅10')
BAR_TAG = (u'Detail items_Tag Rebar(Text Quantity)', u'Tag Rebar 2∅10@20 L=')
# the same tag with the dense spacing after the main one: @20/10 (its label shows
# Rebar_Stirrup Spacing Dense of the detail); used when the project has it
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
LIST_ITEM_GAP = 150.0     # between the details of the row (detail or its tag, whichever is wider)
TAG_ROOM = 500.0          # a bar tag is about this wide (the drawing measures the real one)
TAG_DROP = 250.0          # tag head under the detail
TAG_HEIGHT = 250.0
ROUND_TAG_EXTRA = 300.0   # Shape 60 has its radius dimension under the arc
TIE_WIDTH = 150.0
DETAIL_MARGIN = 60.0      # the shape's own dimension texts (width: they stand left, in the gap)
GAP = 300.0
TOP_TIE_GAP = 400.0       # horizontal tie above the section: concrete top -> tie (column tag between)
TOP_TIE_STEP = 300.0      # between several horizontal ties above
TOP_TAG_GAP = 120.0       # tie -> its tag on the right

REQUIRED = [SECTION_FAMILY[code466.RECT], SECTION_FAMILY[code466.ROUND2], SECTION_FAMILY[code466.ROUND1],
            u'PEER_Rebar_Shape 52', u'PEER_Rebar_Shape 60', u'PEER_Rebar_Shape 62', NUMBER_FAMILY]


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
                      ('hoop', HOOP_FAMILY), ('tie', TIE_FAMILIES[0]), ('number', NUMBER_FAMILY)):
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
    section: [(kind, family key, params, qty, rotate 90)]. A tie across b
    (horizontal) is the Shape 62 turned by 90 degrees."""
    shape, b, h, c = g['shape'], g['b'], g['h'], g.get('cover') or 25.0
    items = []
    if shape != code466.ROUND2:
        items.append(('stirrup', 'stirrup_' + shape,
                      {'Rebar_A': b - 2 * c, 'Rebar_B': h - 2 * c}, 1, False))
    # one detail per hoop size: the same hoop standing and lying is one bar
    # (one number), drawn as the first of them lies in the section
    hoops, order = {}, []
    for hp in result.get('hoops') or []:
        if hp['kind'] == 'rect':
            ab = tuple(round(v) for v in _hoop_dims(hp))
            k = tuple(sorted(ab))
            if k not in hoops:
                hoops[k] = [ab, 0]
                order.append(k)
            hoops[k][1] += 1
    for k in sorted(order):
        (a, bb), n = hoops[k]
        items.append(('hoop', 'hoop', {'Rebar_A': float(a), 'Rebar_B': float(bb)}, n, False))
    ties = {}
    for t in result.get('ties') or []:
        if t.get('kind') == 'v' or t.get('alt'):
            continue
        vertical = t['direction'] == code466.VERTICAL
        span = (h if vertical else b) - 2 * c
        k = (not vertical, round(span))
        ties[k] = ties.get(k, 0) + 1
    for (horizontal, span), n in sorted(ties.items()):
        items.append(('tie', 'tie', {'Rebar_B': float(span)}, n, horizontal))
    return items


def item_size(kind, prm, rotate):
    """(width, height) of one detail on the view, mm, with its own dimension texts."""
    if kind == 'tie':
        w, h = TIE_WIDTH, prm['Rebar_B'] + DETAIL_MARGIN
        return (h, w) if rotate else (w, h)
    return prm['Rebar_A'] + DETAIL_MARGIN, prm['Rebar_B'] + DETAIL_MARGIN


def on_top(kind, rotate):
    """A tie across b (horizontal in the section) is drawn above the section,
    centred over it, as it lies there; the rest go in the row to the right."""
    return kind == 'tie' and rotate


def extent(g, result):
    """{left, right, down, up} of one group's drawing from its insertion point
    (bottom-left corner of the concrete), mm. The details stand in one row to
    the right of the section, top at the top of the concrete, each tag under
    its detail."""
    b, h = g['b'], g['h']
    rows = grouping.mark_rows(grouping.marks_and_ranges(g['marks']))
    left = max(DIM_OFFSET + 100, max([MARK_START + sum(i['width'] for i in r) for r in rows] or [0]))
    right, low, up = b, 0.0, h + 200
    i, top = 0, h + TOP_TIE_GAP
    for kind, _, prm, _, rot in bar_list(result, g):
        w, hh = item_size(kind, prm, rot)
        if on_top(kind, rot):
            top += hh
            up = max(up, top + TAG_HEIGHT)
            right = max(right, (b + w) / 2.0 + TOP_TAG_GAP + TAG_ROOM)
            top += TOP_TIE_STEP
            continue
        right += (LIST_GAP if i == 0 else LIST_ITEM_GAP) + max(w, TAG_ROOM)
        i += 1
        low = max(low, hh + TAG_DROP + TAG_HEIGHT + (ROUND_TAG_EXTRA if kind == 'stirrup' and g['shape'] == code466.ROUND1 else 0))
    down = max(TEXT_DROP + MARK_DROP + MARK_STEP * max(1, len(rows)), low - h)
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
    inst = doc.Create.NewFamilyInstance(XYZ(ft(x0), ft(y0), 0), sym, view)
    _set(inst, values)
    doc.Regenerate()
    # bars of the section: tag at the top right corner
    if types['col_tag'] is not None:
        _tag(doc, view, inst, types['col_tag'], XYZ(ft(x0 + b), ft(y0 + h + 60), 0))
    _dim(doc, view, inst, 'Left', 'Right', XYZ(ft(x0), ft(y0 - DIM_OFFSET), 0),
         XYZ(ft(x0 + b), ft(y0 - DIM_OFFSET), 0), types['dim'])
    _dim(doc, view, inst, 'Bottom', 'Top', XYZ(ft(x0 - DIM_OFFSET), ft(y0), 0),
         XYZ(ft(x0 - DIM_OFFSET), ft(y0 + h), 0), types['dim'])
    txt = u'עמוד %d/%d' % (round(b / 10.0), round(h / 10.0))
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
    # bar list: one row to the right, top at the top of the concrete,
    # each detail as it lies in the section, its tag under it
    xs, ytop = x0 + b + LIST_GAP, y0 + h
    ytie = y0 + h + TOP_TIE_GAP
    row_tags, row_low = [], ft(y0 + h)
    for kind, key, prm, qty, rot in bar_list(result, g):
        s = types.get(key)
        if s is None:
            report['notes'].append(u'%s: no family for the %s' % (u', '.join(g['marks']), kind))
            continue
        el = doc.Create.NewFamilyInstance(XYZ(ft(xs), ft(ytop), 0), s, view)
        vals = dict(prm)
        vals['Rebar_Diameter'] = result['stirrup']['dia']
        vals['Rebar_Spacing'] = result['spacing'] or code466.DEFAULT_SPACING
        _set(el, vals)
        dense_ok = _set_dense(el, result.get('dense'))
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
                if bx is not None and types['bar_tag'] is not None:
                    tt = types['bar_tag_dense'] if dense_ok and types.get('bar_tag_dense') is not None                         else types['bar_tag']
                    _tag(doc, view, el, tt, XYZ(bx[2] + ft(TOP_TAG_GAP + 100), (bx[1] + bx[3]) / 2.0, 0))
                ytie += bh + TOP_TIE_STEP
            continue
        box = _move_top_left(doc, view, el, xs, ytop)
        w = item_size(kind, prm, rot)[0]
        if box is not None:
            w = (box[2] - box[0]) * FT
            if types['bar_tag'] is not None:
                drop = TAG_DROP + (ROUND_TAG_EXTRA if kind == 'stirrup' and g['shape'] == code466.ROUND1 else 0)
                tt = types['bar_tag_dense'] if dense_ok and types.get('bar_tag_dense') is not None else types['bar_tag']
                tag = _tag(doc, view, el, tt, XYZ(box[0] + ft(100), box[1] - ft(drop), 0))
                row_tags.append((tag, drop))
                row_low = min(row_low, box[1])
                doc.Regenerate()
                tb = tag.get_BoundingBox(view)
                if tb is not None:
                    w = max(w, (tb.Max.X - box[0]) * FT)
                else:
                    w = max(w, TAG_ROOM)
        xs += w + LIST_ITEM_GAP
    # the tags of the row on one line, under the lowest detail
    for tag, drop in row_tags:
        p = tag.TagHeadPosition
        tag.TagHeadPosition = XYZ(p.X, row_low - ft(drop), p.Z)
    if any(t.get('kind') == 'v' for t in result.get('ties') or []):
        report['notes'].append(u'%s: V-shaped tie drawn in the section, no shape family for the bar list'
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
