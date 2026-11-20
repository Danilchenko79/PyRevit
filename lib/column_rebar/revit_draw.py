# -*- coding: utf-8 -*-
"""Drawing the column sections on a drafting view (Revit, IronPython 2.7).
Called by the new Create Column button inside ONE TransactionGroup (one Undo);
every change here runs in the caller's open Transaction.

Per group (a row of the table):
  section     PEER_Column Section / Round2 / Round1 with code466 -> slots values
  tag         'Detail items_Tag Rebar' : 'Tag Rebar 2D10' (bars of the section)
  dimensions  b and h, text u'עמוד b/h' (cm), mark symbols PR_Column Number
  bar list    to the right, one under the other, each with its tag - what the
              schedules count: perimeter stirrup (Shape 52 / 60), inner hoops
              (Shape 52, quantity), straight ties (Shape 62, quantity)
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
TEXT_TYPE = u'Structural 3.5'
DIM_TYPE = u'PEER-Linear'

# layout, model mm at 1:25 (as the old button)
DIM_OFFSET = 152.4
TEXT_DROP = 365.8
MARK_DROP = 55.0
MARK_STEP = 210.0
MARK_START = 210.0
LIST_GAP = 400.0          # section -> bar list
LIST_ITEM_GAP = 250.0
TAG_ROOM = 900.0
GAP = 300.0

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


def bar_list(result, g):
    """What goes to the right of the section: [(kind, family key, params, qty, note)]."""
    shape, b, h, c = g['shape'], g['b'], g['h'], g.get('cover') or 25.0
    st = result['stirrup']
    items = []
    if shape != code466.ROUND2:
        items.append(('stirrup', 'stirrup_' + shape,
                      {'Rebar_A': b - 2 * c, 'Rebar_B': h - 2 * c}, 1, u''))
    hoops = {}
    for hp in result.get('hoops') or []:
        if hp['kind'] == 'rect':
            k = (round(hp['a']), round(hp['b']))
            hoops[k] = hoops.get(k, 0) + 1
    for (a, bb), n in sorted(hoops.items()):
        items.append(('hoop', 'hoop', {'Rebar_A': float(a), 'Rebar_B': float(bb)}, n, u''))
    ties = {}
    for t in result.get('ties') or []:
        if t.get('kind') == 'v' or t.get('alt'):
            continue
        span = (h if t['direction'] == code466.VERTICAL else b) - 2 * c
        ties[round(span)] = ties.get(round(span), 0) + 1
    for span, n in sorted(ties.items()):
        items.append(('tie', 'tie', {'Rebar_B': float(span)}, n, u''))
    return items


def extent(g, result):
    """{left, right, down, up} of one group's drawing from its insertion point
    (bottom-left corner of the concrete), mm."""
    b, h = g['b'], g['h']
    rows = grouping.mark_rows(grouping.marks_and_ranges(g['marks']))
    left = max(DIM_OFFSET + 100, max([MARK_START + sum(i['width'] for i in r) for r in rows] or [0]))
    items = bar_list(result, g)
    widest = max([max(p.get('Rebar_A', 0.0), p.get('Rebar_B', 0.0) if k == 'tie' else p.get('Rebar_A', 0.0))
                  for k, _, p, _, _ in items] or [0.0])
    right = b + LIST_GAP + widest + TAG_ROOM
    tall = sum((p.get('Rebar_B', 0.0) if k != 'tie' else 150.0) + LIST_ITEM_GAP + 200 for k, _, p, _, _ in items)
    up = h + 200
    down = max(TEXT_DROP + MARK_DROP + MARK_STEP * max(1, len(rows)), tall - h)
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


def _move_bbox_top_left(doc, view, el, x, y):
    doc.Regenerate()
    bb = el.get_BoundingBox(view)
    if bb is None:
        return None
    ElementTransformUtils.MoveElement(doc, el.Id, XYZ(ft(x) - bb.Min.X, ft(y) - bb.Max.Y, 0))
    doc.Regenerate()
    return el.get_BoundingBox(view)


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
    # bar list
    xs, ycur = x0 + b + LIST_GAP, y0 + h
    st = result['stirrup']
    for kind, key, prm, qty, note in bar_list(result, g):
        s = types.get(key)
        if s is None:
            report['notes'].append(u'%s: no family for the %s' % (u', '.join(g['marks']), kind))
            continue
        el = doc.Create.NewFamilyInstance(XYZ(ft(xs), ft(ycur), 0), s, view)
        vals = dict(prm)
        vals['Rebar_Diameter'] = st['dia']
        vals['Rebar_Spacing'] = result['spacing'] or 200.0
        _set(el, vals)
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
        bb = _move_bbox_top_left(doc, view, el, xs, ycur)
        if bb is not None and types['bar_tag'] is not None:
            _tag(doc, view, el, types['bar_tag'], XYZ(bb.Max.X + ft(150), (bb.Min.Y + bb.Max.Y) / 2, 0))
            ycur = bb.Min.Y * FT - LIST_ITEM_GAP
        else:
            ycur -= 300
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
